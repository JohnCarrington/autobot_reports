#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
trade_manager.py — CANONICAL WRAPPER (MULTI-EPIC SAFE) + LIVE TRADE MANAGEMENT
===============================================================================

Purpose:
- Preserve legacy imports so nothing breaks.
- Provide canonical TradeManager class API (per your architecture).
- Delegate execution/state to trade_executor.py (single source of truth).
- Add higher-level live trade management, especially for LIQUIDITY_SWEEP.

Critical fixes / changes:
- EPIC-aware monitoring remains mandatory (prevents cross-epic contamination).
- IG position monitoring remains in place for external/manual close detection.
- Sweep trades now get a probation / stall-management layer here rather than
  relying on trade_executor.py to decide trade health.
- Added manager-side profit protection for all live trades:
    * profit lock after a configurable trigger
    * dynamic retrace floor once trade has extended far enough
    * closes from TradeManager if unrealised profit materially gives back

Design split:
- strategy_logic.py = decide whether to enter
- trade_executor.py = submit / confirm / close / low-level stop logic
- trade_manager.py = manage the trade while it is live

Pre-check (Continual Errors Ledger / House Rules):
- #83 .env must be loaded before importing env-dependent modules.
- #96 open_sb_now.py is golden and remains untouched.
- #99 / #106 sl/tp unit contract remains in strategy/executor; this file only manages live trades.
- #24 / #104 no price normalization.
- Scope lock: compat-first changes only; preserve public API and module-level re-exports.
"""

from __future__ import annotations

import json as _json_stdlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# ============================================================
# ENV (must be loaded before importing env-dependent modules)
# ============================================================
load_dotenv()

logger = logging.getLogger("AutoBot")

# ============================================================
# Delegate implementation: trade_executor is the engine
# ============================================================
import trade_executor as _exec


def _pair_from_epic(epic: str) -> str:
    """Extract pair name from IG epic, e.g. 'CS.D.USDJPY.TODAY.IP' -> 'USDJPY'."""
    parts = epic.split(".")
    return parts[2] if len(parts) >= 3 else epic.upper()


# Points-per-pip: imported from shared pair_config
from pair_config import get_ppp as _ppp


# ============================================================
# IG open positions helper (read-only)
# ============================================================
from close_sb_now import get_open_positions

try:
    from close_intent_journal import has_recent_intent as _close_intent_has_recent
except Exception:  # pragma: no cover — journal must never break trading
    def _close_intent_has_recent(*_a, **_kw):  # type: ignore
        return False, None

# Grace window in seconds for the reconciler to treat a vanished position
# as bot-driven when a stamp exists in the close-intent journal. Sized to
# survive the OTC-call ↔ broker-confirm ↔ next-reconciler-poll race. Bumping
# this only widens the "trust the stamp" window — it never suppresses a
# genuine external close outside the window.
RECONCILE_STAMP_GRACE_S = float(os.getenv("RECONCILE_STAMP_GRACE_S", "30") or 30.0)

# ── Naked-foreign-position alert (2026-08-03) ───────────────────────────────
# Shared IG account Z3G4CJ is used by 161 (this host) AND by Johnny (mobile
# / web) AND by the sibling FXi host. Any manual open from the IG mobile app
# WITHOUT a stop attached is an existential risk to shared equity — nobody
# gets paged, the position drifts, and by the time it's noticed the account
# is already bleeding.
#
# Motivating case: 2026-08-03 14:35 UTC — a MOBILE SELL was opened by
# Johnny with no stop. Discovered by forensics at ~20:00 (five hours later).
# This sweep enumerates positions on the shared account, matches them
# against every owned state key on this host, and if a position is (a)
# unowned by 161, (b) has stopLevel == None, and (c) has been open longer
# than FOREIGN_POSITION_ALERT_MIN minutes, emits ONE Telegram warning per
# deal_id per calendar day (UTC).
#
# ALERT-ONLY. We never close, never amend, never place stops on foreign
# positions — those are somebody else's trades, and touching them is worse
# than leaving them alone.
FOREIGN_POSITION_ALERT_MIN = float(os.getenv("FOREIGN_POSITION_ALERT_MIN", "10") or 10.0)
FOREIGN_POSITION_ALERT_ENABLED = (
    os.getenv("FOREIGN_POSITION_ALERT_ENABLED", "1") or "1"
).strip() == "1"
FOREIGN_POSITION_ALERT_STATE_PATH = Path(
    os.getenv("FOREIGN_POSITION_ALERT_STATE_PATH",
              "/opt/tradingbot/logs/foreign_position_alerts.json")
)

# ============================================================
# Legacy-friendly module-level re-exports (compatibility)
# ============================================================
TRADE_STATE = _exec.TRADE_STATE
TRADE_STATE_BY_EPIC = getattr(_exec, "TRADE_STATE_BY_EPIC", {})

execute_trade = _exec.execute_trade
update_trade_state = _exec.update_trade_state
close_position = _exec.close_position
close_all_positions_for_epic = _exec.close_all_positions_for_epic
apply_trailing_stop = _exec.apply_trailing_stop
has_active_trade_for_mode = _exec.has_active_trade_for_mode
get_all_positions_for_epic = _exec.get_all_positions_for_epic

# Some executor versions do not expose handle_partial_exit as a public function.
handle_partial_exit = getattr(_exec, "handle_partial_exit", None)

# ============================================================
# CONFIG — LIVE MANAGEMENT
# ============================================================
# Trade manager owns post-entry quality checks for sweeps.
LIQUIDITY_SWEEP_MODE = (os.getenv("SWEEP_MODE_NAME", "LIQUIDITY_SWEEP") or "LIQUIDITY_SWEEP").strip().upper()

# How often we poll IG open positions (seconds)
IG_MONITOR_EVERY_S = float(os.getenv("IG_MONITOR_EVERY_S", "10") or 10.0)

# LS-thread refactor (2026-05-08): when LS_ASYNC_DISPATCH=1 (default), the
# external-close sweep moves to the rest_sweeps daemon thread and the
# inline call in monitor_positions() is suppressed. Set to 0 to keep the
# sweep on the LS thread (rollback escape hatch).
_LS_ASYNC_DISPATCH = (os.getenv("LS_ASYNC_DISPATCH", "1") or "1").strip() != "0"

# Sweep probation / stall logic.
# Philosophy: do NOT over-filter entry, but require the trade to prove itself after entry.
SWEEP_PROBATION_ENABLED = os.getenv('SWEEP_PROBATION_ENABLED', '1').strip() == '1'
SWEEP_PROBATION_SECONDS = float(os.getenv("SWEEP_PROBATION_SECONDS", "300") or 300.0)
SWEEP_STALL_SECONDS = float(os.getenv("SWEEP_STALL_SECONDS", "300") or 300.0)
SWEEP_MIN_PROGRESS_PIPS = float(os.getenv("SWEEP_MIN_PROGRESS_PIPS", "1.5") or 1.5)
SWEEP_STALL_GRACE_PIPS = float(os.getenv("SWEEP_STALL_GRACE_PIPS", "1") or 1.0)

# Pair-specific overrides for lower-volatility instruments
SWEEP_MIN_PROGRESS_PIPS_OVERRIDES: Dict[str, float] = {
    "USDJPY": float(os.getenv("SWEEP_MIN_PROGRESS_PIPS_USDJPY", "1.0") or 1.0),
    "USDCAD": float(os.getenv("SWEEP_MIN_PROGRESS_PIPS_USDCAD", "1.0") or 1.0),
}

# Optional post-entry momentum observation for sweeps.
# This is intentionally NOT a hard pre-entry gate.
SWEEP_REQUIRE_POST_ENTRY_MOMENTUM = (os.getenv("SWEEP_REQUIRE_POST_ENTRY_MOMENTUM", "0") or "0").strip() == "1"
SWEEP_MOMENTUM_GRACE_SECONDS = float(os.getenv("SWEEP_MOMENTUM_GRACE_SECONDS", "180") or 180.0)

# Optional protection if caller passes a sweep extreme in native IG units.
SWEEP_EXTREME_RETEST_TOLERANCE_PIPS = float(
    os.getenv("SWEEP_EXTREME_RETEST_TOLERANCE_PIPS", "3.0") or 3.0
)
SWEEP_EXTREME_RETEST_ENABLED = os.getenv('SWEEP_EXTREME_RETEST_ENABLED', '1') == '1'

# Software trailing stop for LIQUIDITY_SWEEP trades.
# After the trade moves SWEEP_TRAIL_ACTIVATE_PIPS in profit, a trail is armed.
# The trail floor = best_pnl - SWEEP_TRAIL_OFFSET_PIPS.
# If current pnl falls back through the floor, the trade is closed manager-side.
SWEEP_TRAIL_ACTIVATE_PIPS = float(os.getenv("SWEEP_TRAIL_ACTIVATE_PIPS", "20") or 20.0)
SWEEP_TRAIL_OFFSET_PIPS = float(os.getenv("SWEEP_TRAIL_OFFSET_PIPS", "8") or 8.0)
SWEEP_TRAIL_EPSILON_PIPS = float(os.getenv("SWEEP_TRAIL_EPSILON_PIPS", "0.25") or 0.25)
SWEEP_TRAIL_FLOOR_MIN_PIPS = float(os.getenv("SWEEP_TRAIL_FLOOR_MIN_PIPS", "10") or 10.0)

# Manager-side profit protection (MPP) was REMOVED 2026-05-23. Net was
# −105p / 55d (gross saves +193p, strangle cost −132p). The +10p / 50%
# scale-out + broker BE stop is now the sole profit protection.
# Removed constants: PROFIT_LOCK_ENABLED, PROFIT_LOCK_TRIGGER_PIPS,
# PROFIT_LOCK_FLOOR_PIPS, PROFIT_TRAIL_START_PIPS, PROFIT_TRAIL_OFFSET_PIPS,
# PROFIT_LOCK_MIN_AGE_SECONDS, PROFIT_LOCK_RETRACE_EPSILON_PIPS,
# PROFIT_PROTECT_ARM_PCT, PROFIT_PROTECT_FLOOR_PCT, _LIQ_TRAIL_RATIO,
# TRADE_MANAGER_LIQ_ARM_PIPS, TRADE_MANAGER_LIQ_FLOOR_PIPS,
# _PAIR_LIQ_ARM, _PAIR_LIQ_FLOOR.

# Post-TP1 continuation: instead of closing at TP1, hold and watch for reversal.
# Close on: (1) aggressive reversal candle, (2) price drops below TP1, (3) 10-pip retrace from peak.
POST_TP1_ENABLED = os.getenv("TRADE_MANAGER_POST_TP1_ENABLED", "1").strip() == "1"
POST_TP1_REVERSAL_BODY_PIPS = float(os.getenv("TRADE_MANAGER_POST_TP1_REVERSAL_BODY", "8") or 8.0)
POST_TP1_MAX_RETRACE_PIPS = float(os.getenv("TRADE_MANAGER_POST_TP1_MAX_RETRACE", "10") or 10.0)

# Consolidation hold — freeze trail floor when price stops making new extremes.
CONSOLIDATION_HOLD_ENABLED = (os.getenv("TRADE_MANAGER_CONSOLIDATION_HOLD_ENABLED", "1") or "1").strip() == "1"
CONSOLIDATION_CANDLES = int(os.getenv("TRADE_MANAGER_CONSOLIDATION_CANDLES", "6") or 6)
_CONSOLIDATION_CANDLE_SECONDS = 300  # 5-minute candle periods

# ============================================================
# CONFIG — BRIEFING-LEVEL TP MANAGEMENT
# ============================================================
BRIEFING_TP_ENABLED = (os.getenv("BRIEFING_TP_ENABLED", "1") or "1").strip() == "1"
BRIEFING_TP_MODE = "BRIEFING_LIQUIDITY"

# Fixed SL per pair (pips)
BRIEFING_TP_SL_PIPS: Dict[str, float] = {"USDJPY": 12.0}
BRIEFING_TP_SL_DEFAULT = 20.0  # widened 12→20 2026-05-23: give trades room to breathe past noise before +10p scale-out trigger. USDJPY stays at 12.

# Fallback TPs when no briefing levels available (pips from entry)
BRIEFING_TP_FALLBACK_TP1 = 30.0
BRIEFING_TP_FALLBACK_TP2 = 50.0
BRIEFING_TP_FALLBACK_TP3 = 80.0

# Synthetic level increment when fewer than 3 briefing levels (pips)
BRIEFING_TP_SYNTH_INCREMENT = 20.0

# Minimum distance for TP levels (skip levels closer than this)
BRIEFING_TP_MIN_TP1_PIPS = float(os.getenv("BRIEFING_TP_MIN_TP1_PIPS", "15") or 15.0)
BRIEFING_TP_MIN_TP_GAP_PIPS = float(os.getenv("BRIEFING_TP_MIN_TP_GAP_PIPS", "10") or 10.0)

# Pullback trail between TP levels: close if price retraces this many pips
# from the swing high/low reached since the last TP was hit
BRIEFING_TP_PULLBACK_PIPS = float(os.getenv("BRIEFING_TP_PULLBACK_PIPS", "25") or 25.0)

# Briefing level priority weights (higher = checked first for TP3)
_LEVEL_PRIORITY = {"major_resistance": 3, "major_support": 3,
                   "resistance": 2, "support": 2,
                   "briefing_liquidity_buy": 1, "briefing_liquidity_sell": 1}

# ============================================================
# CONFIG — TRAILING STOP AFTER TP1 (BRIEFING_SWEEP + WINDOW_SWEEP)
# ============================================================
TRAIL_AFTER_TP1_PIPS = float(os.getenv("TRAIL_AFTER_TP1_PIPS", "15") or 15.0)
_TRAIL_AFTER_TP1_MODES = {"BRIEFING_SWEEP", "WINDOW_SWEEP"}
# BB_REVERSAL exits on per-leg SL/TP only — no trail, no indicator-driven exits.

# ============================================================
# CONFIG — BB_PIERCE_RUN time stop (GBPUSD_BB_BOUNCE_L/_S)
# ============================================================
# Strategy is in gbpusd_bb_bounce.py. As of 2026-05-03, BB_PIERCE_RUN
# uses the multi-tier briefing-TP system shared with BRIEFING_SWEEP /
# BB_REVERSAL_TRENDING / 3CO (registered via setup_briefing_tp at trade
# open and managed by _monitor_briefing_tp).
#
# The only BB_PIERCE_RUN-specific runtime knobs that remain are:
#   - BB_PIERCE_RUN_MODES — used below in the REGIME_MAX_HOLD override
#     to extend the per-mode max-hold from 120m to 240m. The 240m cap
#     is what enforces the time stop now (the dedicated trail consumer
#     was removed).
BB_PIERCE_RUN_MODES = frozenset({
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
    # BB_REV_PAT (V-shaped + Arc reversal) shares the same time-stop
    # semantics as BB_PIERCE_RUN — both are GBPUSD BB-fade strategies
    # that need 240m to reach the multi-tier briefing TPs.
    "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
    # EMA_PULLBACK (continuation pullback into the EMA ribbon). Same
    # 240m time-stop semantics — runner targets the origin BB band and
    # may need the full window to reach it post-scale-out.
    "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
})
# BB_BOUNCE_BE_STOP_MODES removed 2026-05-23: the prior +10p/+3p BB_BOUNCE
# BE-stop branch (commit 1f33d75) has been superseded by the universal +10p
# / 50% scale-out (SCALE_OUT_AT_10P_ENABLED, _scale_out_50pct). One
# +10p trigger system across all strategies; no fighting mechanisms.
BB_PIERCE_RUN_TIME_STOP_MINUTES  = float(os.getenv("BB_PIERCE_RUN_TIME_STOP_MINUTES", "240") or 240.0)
# Broker TP distance for BB_PIERCE_RUN positions — must mirror the
# value emitted by gbpusd_bb_bounce.BROKER_TP_PIPS so SL-amend calls
# preserve the existing limit_level. If those drift apart, the SL-amend
# would shift the broker TP. 100p is a safety sentinel; tier exits
# happen at market via _monitor_briefing_tp well before this hits.
BB_PIERCE_RUN_BROKER_TP_PIPS = float(os.getenv("BB_PIERCE_RUN_BROKER_TP_PIPS", "100") or 100.0)
# Test seam: substitutable amend hook. Default None → real
# ig.update_open_position. Probes set this to a recorder.
_bbpr_broker_sl_amend_fn = None  # type: ignore[var-annotated]

# ============================================================
# CONFIG — structure-exit with-trend suppress (2026-06-23)
# ============================================================
# Kill-switched: when the LIVE engine regime is WITH-TREND for the trade's
# direction, skip the structure_exit hook so a correctly-directioned trade
# isn't knocked out by a 5-bar-extreme pullback before the trend pays.
# Default OFF. Fail-open: a missing or unrecognised regime must never
# suppress a protective exit — structure_exit runs as today in that case.
# Reads winning_regime from regime_engine.latest_result(pair), NOT the
# flattened detector and NOT regime_at_fire (frozen at entry).
STRUCTURE_EXIT_WITH_TREND_SUPPRESS_ENABLED = (
    os.getenv("STRUCTURE_EXIT_WITH_TREND_SUPPRESS_ENABLED", "0") or "0"
).strip() == "1"
_STRUCTURE_EXIT_WT_LONG_REGIMES = frozenset(
    r.strip().upper()
    for r in (
        os.getenv(
            "STRUCTURE_EXIT_WT_LONG_REGIMES",
            "TREND_FORMING_UP,STRONG_TREND_UP,BREAKOUT_FORMING_UP",
        ) or ""
    ).split(",")
    if r.strip()
)
_STRUCTURE_EXIT_WT_SHORT_REGIMES = frozenset(
    r.strip().upper()
    for r in (
        os.getenv(
            "STRUCTURE_EXIT_WT_SHORT_REGIMES",
            "TREND_FORMING_DOWN,STRONG_TREND_DOWN,BREAKOUT_FORMING_DOWN",
        ) or ""
    ).split(",")
    if r.strip()
)

# Per-strategy exemption set for STRUCTURE_EXIT (2026-06-25). BB_BOUNCE
# is counter-trend by design — WT-suppress can never protect it, and a
# 5-bar opposite-extreme break is exactly what a fade trades against.
# Forensic showed structure_exit was knocking out BB_BOUNCE positions
# before SL/TP could resolve. Exempt by default; flag-overridable.
STRUCTURE_EXIT_EXEMPT_BB_BOUNCE = (
    os.getenv("STRUCTURE_EXIT_EXEMPT_BB_BOUNCE", "1") or "1"
).strip() == "1"
_STRUCTURE_EXIT_EXEMPT_MODES_BUILTIN = frozenset({
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
})
# LEVEL_BOUNCE (gbpusd_level_bounce.py) — three-candle level bounce, 100p
# SL is the sole exit. Structure-exit's opposite-swing-break flip is the
# whole point of the trade at C1; letting it re-close the position ~30
# minutes later is exactly the management this mode is exempt from.
# Decoupled from _STRUCTURE_EXIT_EXEMPT_MODES gate — an unconditional
# short-circuit lives at :4118 so the LEVEL_BOUNCE exemption can never
# be turned off by flipping STRUCTURE_EXIT_EXEMPT_BB_BOUNCE=0.
_LEVEL_BOUNCE_MODES: frozenset = frozenset({
    "GBPUSD_LEVEL_BOUNCE_L", "GBPUSD_LEVEL_BOUNCE_S",
})
# 2026-08-14 — TREND_V3 UM variant (gbpusd_trend_v3.MODE_NAME_UM_
# LONG/SHORT). Unmanaged by design, mirrors LEVEL_BOUNCE exemption
# mechanics: STRUCTURE_EXIT skipped, REGIME_MAX_HOLD disabled (max_
# hold_min=None), universal +10p scale-out skipped, briefing
# invalidation skipped. Sole exits: SL/TP (12p / 100p) and the
# TREND_V3_UM_EOD_CLOSE sweep in autobot._apply_trend_v3_um_eod_close.
_TREND_V3_UM_MODES: frozenset = frozenset({
    "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
})
# 2026-08-10 (task 161): env-drivable extension. Corpus of 76 STRUCTURE_EXIT
# closes (Jun 1 – Aug 10) showed the rule is net-costly on BRIEFING_EXECUTION
# (n=8, +126.8p delta, 3 TP-hits) and GBPUSD_EMA_PULLBACK_S (n=11, +130.6p
# delta, 6 TP-hits). Same-day SL/TP reconstruction; scale-out not modelled —
# revisit if native telemetry contradicts.
_STRUCTURE_EXIT_EXEMPT_MODES_EXTRA = frozenset(
    m.strip().upper()
    for m in (os.getenv("STRUCTURE_EXIT_EXEMPT_MODES_EXTRA", "") or "").split(",")
    if m.strip()
)
_STRUCTURE_EXIT_EXEMPT_MODES = (
    _STRUCTURE_EXIT_EXEMPT_MODES_BUILTIN | _STRUCTURE_EXIT_EXEMPT_MODES_EXTRA
)
logger.info(
    "[STRUCTURE-EXIT] effective_exempt_modes=%s (builtin=%s extra=%s enabled=%s)",
    sorted(_STRUCTURE_EXIT_EXEMPT_MODES),
    sorted(_STRUCTURE_EXIT_EXEMPT_MODES_BUILTIN),
    sorted(_STRUCTURE_EXIT_EXEMPT_MODES_EXTRA),
    STRUCTURE_EXIT_EXEMPT_BB_BOUNCE,
)


# ─────────────────────────────────────────────────────────────────────
# STRUCTURE_EXIT skip-log dedup (2026-08-26).
# The four "STRUCTURE_EXIT skipped …" logs below (LEVEL_BOUNCE,
# TREND_V3_UM, BB-FLIP, BB_FREED) run inside the per-tick monitor and
# were emitting one line per tick — thousands per position per hour.
# Dedup keyed on (pos_key, tag): log once per new 5m bar bucket
# (300s alignment) and on any tag change. journalctl noise drops from
# ~4k/hour/position to ~12/hour/position.
_STRUCTURE_SKIP_LAST: dict = {}  # pk -> (tag, bucket_5m)


def _log_structure_skip_once(pk: str, tag: str, msg: str, *args) -> None:
    try:
        bucket = int(time.time()) // 300
    except Exception:
        bucket = 0
    prev = _STRUCTURE_SKIP_LAST.get(pk)
    if prev == (tag, bucket):
        return
    _STRUCTURE_SKIP_LAST[pk] = (tag, bucket)
    logger.info(msg, *args)


def _amend_broker_sl_for_bbpr(pos_key: str, new_sl_price: float) -> bool:
    """Amend the broker-side SL for a BB_PIERCE_RUN position, preserving
    the existing 100p TP. Called at TP1/TP2 HOLD verdicts in
    _monitor_briefing_tp. The broker TP is intentionally NOT amended —
    it stays at the entry +/- BB_PIERCE_RUN_BROKER_TP_PIPS that was set
    at order open. Tier exits (CLOSE verdicts, TP3) close at market via
    _close_trade_best_effort and don't go through this function.

    pos_key: "<epic>|<mode>" — same key used by EPIC_STATE.
    new_sl_price: absolute price for the new stop level.

    Returns True on successful amend, False on any failure (defensive —
    failures log but never raise; software-tracked SL in
    meta["sl_price"] is the always-on fallback).
    """
    try:
        st = _state_for_epic(pos_key)
        deal_id = st.get("dealId") or st.get("deal_id")
        direction = str(st.get("direction") or "").upper()
        entry = _safe_float(st.get("entry_price"))
        if not deal_id or direction not in ("BUY", "SELL") or entry is None or entry <= 0:
            logger.warning(
                "[BB_PIERCE_RUN] broker SL amend skipped: missing context "
                "(deal_id=%s direction=%s entry=%s)",
                deal_id, direction, entry,
            )
            return False
        epic_name = str(st.get("epic") or pos_key.split("|", 1)[0])
        pair = _pair_from_epic(epic_name)
        ppp = _ppp(pair)
        # Preserve the existing TP at entry +/- 100p (matches what the
        # strategy emitted at order open). Do NOT compute from current
        # price — we want the TP UNCHANGED relative to entry.
        if direction == "BUY":
            limit_level = round(entry + BB_PIERCE_RUN_BROKER_TP_PIPS * ppp, 1)
        else:
            limit_level = round(entry - BB_PIERCE_RUN_BROKER_TP_PIPS * ppp, 1)
        new_stop = round(float(new_sl_price), 1)
        if _bbpr_broker_sl_amend_fn is not None:
            _bbpr_broker_sl_amend_fn(deal_id, new_stop, limit_level)
        else:
            from ig_auth import get_ig_session
            ig, _h, _a = get_ig_session()
            ig.update_open_position(
                limit_level=limit_level,
                stop_level=new_stop,
                deal_id=deal_id,
            )
        logger.info(
            "[BB_PIERCE_RUN] broker SL amended: %s deal=%s stop=%.1f limit=%.1f (TP unchanged)",
            pos_key, deal_id, new_stop, limit_level,
        )
        return True
    except Exception as exc:
        logger.warning(
            "[BB_PIERCE_RUN] broker SL amend failed for %s: %s",
            pos_key, exc,
        )
        return False


def _is_bbpr_pos(epic_pos_key: str) -> bool:
    """True if this pos_key belongs to a BB_PIERCE_RUN position. Used
    to gate the broker-SL-amend behaviour inside _monitor_briefing_tp."""
    try:
        st = _state_for_epic(epic_pos_key)
        return str(st.get("mode") or "").upper() in BB_PIERCE_RUN_MODES
    except Exception:
        return False


# ── Generic broker-side SL/TP amend (2026-05-23) ────────────────────────
# Sibling of _amend_broker_sl_for_bbpr, kept separate so existing BBPR
# call sites stay byte-identical. Used by _scale_out_50pct to move the
# runner's stop to BE while preserving its original TP.
_broker_sl_amend_fn = None  # test seam (mirrors _bbpr_broker_sl_amend_fn)


# ── SL-amend failure backoff + circuit-break (2026-07-21) ──────────────
# Added after the 2026-07-20 08:00-08:21 incident: a broker-side
# ATTACHED_ORDER_LEVEL_ERROR (invalid stop-distance) rejection caused the
# BB_TRAIL/SCALE_OUT retry loop to fire ~1 amend/sec for 21 minutes,
# which then tripped IG's rate-limiter (HTTP 403 on positions endpoints).
# The healthy path is untouched — the first F1 failures still retry
# immediately every tick. Only sustained failure engages the backoff.
# Env read at call-time so a tune takes effect on the next tick without
# restart. Defaults from the incident post-mortem.
SL_AMEND_BACKOFF_AFTER = int(os.getenv("SL_AMEND_BACKOFF_AFTER", "3") or 3)
SL_AMEND_BACKOFF_SECS = float(os.getenv("SL_AMEND_BACKOFF_SECS", "30") or 30.0)
SL_AMEND_BACKOFF2_AFTER = int(os.getenv("SL_AMEND_BACKOFF2_AFTER", "10") or 10)
SL_AMEND_BACKOFF2_SECS = float(os.getenv("SL_AMEND_BACKOFF2_SECS", "120") or 120.0)
SL_AMEND_CIRCUIT_AFTER = int(os.getenv("SL_AMEND_CIRCUIT_AFTER", "20") or 20)
SL_AMEND_ALERTS_ENABLED_DEFAULT = "1"

# ── Pre-flight IG min-distance DEFER margin (2026-07-21) ───────────────
# Cushion added on top of the raw per-pair IG min-stop distance so a
# tick of price movement between the pre-flight check and the API call
# doesn't still trip ATTACHED_ORDER_LEVEL_ERROR. Read at call-time.
SL_AMEND_MIN_DIST_MARGIN_PIPS = float(
    os.getenv("SL_AMEND_MIN_DIST_MARGIN_PIPS", "0.5") or 0.5
)

# ── Amend-clamp per-pair IG min-stop distance (FX PIPS, 2026-07-21) ────
# Sourced from IG /markets/{epic} dealingRules.minNormalStopOrLimit-
# Distance. IG returns the value with unit=POINTS; for spread-bet FX
# pairs in this codebase, 1 IG POINT == 1 unit in st["last_mid"]/entry
# scale == 1 fx-pip (codebase 13476.8 == fx 1.34768, so a 1-unit
# codebase distance == 0.0001 fx == 1 pip). Values here are therefore
# in fx-pips DIRECTLY — no ppp division.
#
# Kept separate from trade_executor._IG_MIN_STOP_PTS on purpose: that
# constant governs ORDER PLACEMENT (which floors sl_pips to a
# conservative 12 for GBPUSD) and current placement behaviour depends
# on it. The amend clamp needs the ACTUAL broker minimum (much smaller
# than the placement floor); reusing _IG_MIN_STOP_PTS was the bug that
# produced the "12.5-pip effective min" and would have deferred every
# 6-8p BE/trail amend indefinitely.
#
# Defaults verified against IG dealingRules on 2026-07-21:
#   GBPUSD 4.0, EURUSD 2.0, USDJPY 6.0, USDCAD 4.0, GBPJPY 4.0.
# GBPUSD 4.0 also cross-verified against 2026-07-20 storm evidence:
#   08:00:29 accepted at 7.35p distance, 08:00:30 rejected at 1.55p.
# Override via <PAIR>_IG_MIN_STOP_PIPS env; read at call-time.
_IG_MIN_STOP_PIPS_FALLBACK = 4.0
_IG_MIN_STOP_PIPS_DEFAULTS: Dict[str, float] = {
    "GBPUSD": 4.0,
    "EURUSD": 2.0,
    "USDJPY": 6.0,
    "USDCAD": 4.0,
    "GBPJPY": 4.0,
}


def _ig_min_stop_pips_for_pair(pair: str) -> float:
    """Amend-clamp per-pair IG min-stop distance in FX pips.
    <PAIR>_IG_MIN_STOP_PIPS env overrides the default."""
    _env = os.getenv(f"{pair}_IG_MIN_STOP_PIPS")
    if _env:
        try:
            return float(_env)
        except (TypeError, ValueError):
            pass
    return _IG_MIN_STOP_PIPS_DEFAULTS.get(pair, _IG_MIN_STOP_PIPS_FALLBACK)


# ── Live IG dealingRules fetch (2026-09-14, defect #9) ─────────────────
# The 2026-09-14 17:58:48 GBPUSD_TREND_V3_L incident (see
# reports-public/be_amend_incident_20260914_*) proved IG's real
# minNormalStopOrLimitDistance for GBPUSD had drifted well above the
# hardcoded 4.0-pip default: four BE-at-entry proposals sitting 9.0p
# from bid were rejected with ATTACHED_ORDER_LEVEL_ERROR, then a 12.0p
# proposal from the ratchet was accepted. The pre-flight defer at
# threshold 4.5p never triggered, so every rejection reached IG.
#
# Fix: consult IG's actual dealingRules for the epic and cache the
# value. On any amend rejection with reason ATTACHED_ORDER_LEVEL_ERROR
# we invalidate the cache so the next call refetches fresh.
#
# Per 2026-09-14 operator ruling: if the broker API cannot establish a
# current safe minimum distance, we DEFER the amend rather than infer
# or clamp — better to hold the last-accepted broker stop than send a
# guess that IG will bounce.
#
# Cache keyed by epic. Value: (min_stop_pips: float, fetched_at: float).
# TTL default 900s (15 min); refresh on rejection is immediate.
import threading as _threading_stdlib
_MARKET_MIN_STOP_CACHE: Dict[str, tuple[float, float]] = {}
_MARKET_MIN_STOP_LOCK = _threading_stdlib.Lock()
SL_AMEND_LIVE_DEALING_RULES_TTL_SECS = float(
    os.getenv("SL_AMEND_LIVE_DEALING_RULES_TTL_SECS", "900") or 900.0
)

# ── dealingRules fetch-failure backoff (2026-09-14, final activation) ──
# Per-epic negative cache. Complements the positive cache above: when
# fetch_market_by_epic fails or returns a malformed rule, we stop
# hammering IG. Repeated ticks during an outage would otherwise re-enter
# the fetch path each call (positive cache is empty → no short-circuit),
# eventually tripping IG's rate limiter — the same failure mode the
# 2026-07-20 SL-amend storm produced downstream. The downstream
# SL-amend backoff cannot help here because fail-closed preflight
# prevents the broker amend from ever being called: no amend, no
# amend-failure signal, no downstream throttle.
#
# Retry intervals, bounded and non-tunable from tests: 5s, 15s, 30s,
# 60s, 120s, then 300s cap. Continuously failing over 15 minutes = 8
# fetch attempts (t=0,5,20,50,110,230,530,830).
#
# Failure record captures only what is safe to persist: count, reason
# category (FETCH_EXCEPTION / PARSE_EXCEPTION / MALFORMED_RULE /
# UNSUPPORTED_UNIT / EMPTY_RESPONSE), exception TYPE name (never the
# message), failure timestamp and next-retry timestamp. Credentials,
# response bodies and exception messages are never stored or logged.
_FETCH_BACKOFF_INTERVALS_SECS: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0, 120.0)
_FETCH_BACKOFF_MAX_SECS: float = 300.0
_MARKET_MIN_STOP_FAILURE: Dict[str, Dict[str, Any]] = {}
# In-flight reservation: epics currently being fetched by some caller.
# A concurrent caller that finds the epic reserved returns the cached
# value (or None) rather than launching a duplicate REST call.
_MARKET_MIN_STOP_INFLIGHT: set = set()
# Observability rate-limit: at most one FETCH_FAILED / FETCH_BACKOFF row
# per epic per _FETCH_OBS_LOG_INTERVAL_SECS window. FETCH_RECOVERED is
# an edge event and always emitted.
_FETCH_OBS_LOG_INTERVAL_SECS: float = 60.0
_MARKET_MIN_STOP_OBS_LAST: Dict[tuple, float] = {}


def _fetch_backoff_delay_for_count(count: int) -> float:
    """Bounded retry delay for consecutive-failure ``count``.
    1→5s, 2→15s, 3→30s, 4→60s, 5→120s, ≥6→300s (cap)."""
    if count <= 0:
        return 0.0
    if count <= len(_FETCH_BACKOFF_INTERVALS_SECS):
        return _FETCH_BACKOFF_INTERVALS_SECS[count - 1]
    return _FETCH_BACKOFF_MAX_SECS


def _emit_fetch_obs(
    event: str, epic: str, cache_source: str, *,
    failure_count: Optional[int] = None,
    reason_category: Optional[str] = None,
    retry_delay_secs: Optional[float] = None,
    next_retry_ts: Optional[float] = None,
) -> None:
    """Structured, rate-bounded observability row for the fetch-backoff.

    No secrets, no raw broker response, no exception messages — only
    the reason CATEGORY and (for exception origins) the exception TYPE
    is captured upstream and passed as ``reason_category``.
    """
    try:
        now = time.time()
        key = (str(epic), str(event))
        with _MARKET_MIN_STOP_LOCK:
            last = _MARKET_MIN_STOP_OBS_LAST.get(key, 0.0)
            gated = (
                event != "FETCH_RECOVERED"
                and (now - last) < _FETCH_OBS_LOG_INTERVAL_SECS
            )
            if not gated:
                _MARKET_MIN_STOP_OBS_LAST[key] = now
        if gated:
            return
        parts = [f"event={event}", f"epic={epic}", f"cache_source={cache_source}"]
        if failure_count is not None:
            parts.append(f"failure_count={int(failure_count)}")
        if reason_category is not None:
            parts.append(f"reason_category={reason_category}")
        if retry_delay_secs is not None:
            parts.append(f"retry_delay_secs={float(retry_delay_secs):.1f}")
        if next_retry_ts is not None:
            parts.append(f"next_retry_ts={float(next_retry_ts):.3f}")
        logger.info("[IG_MIN_STOP_FETCH_OBS] %s", " ".join(parts))
    except Exception:
        pass


# ── Preflight structured result (2026-09-14 review, blockers fix) ─────
# One immutable object describes an amend preflight decision. Consumed
# by _amend_broker_sl for both the DEFER branch and the observability
# receipt so a single logical attempt cannot resolve broker rules more
# than once (see blocker 4).
#
# Reason vocabulary:
#   * OK                          — safe to submit.
#   * MARKET_PRICE_UNAVAILABLE    — required bid (BUY) / offer (SELL)
#                                    absent; DEFER.
#   * LIVE_RULE_UNAVAILABLE       — source != "live"; DEFER (blocker 1).
#   * MIN_DISTANCE_NOT_SATISFIED  — proposed stop inside IG's live
#                                    corridor from the authoritative
#                                    side; DEFER.
#   * PREFLIGHT_EXCEPTION         — an unexpected exception was raised
#                                    while resolving preflight state.
#                                    DEFER (fail-closed; blocker 2).
@dataclass(frozen=True)
class _AmendPreflight:
    defer: bool
    reason: str
    validation_price: Optional[float] = None
    validation_side: str = "UNKNOWN"
    dist_pips: Optional[float] = None
    min_distance_pips: Optional[float] = None
    margin_pips: float = 0.0
    threshold_pips: Optional[float] = None
    source: str = "none"
    rule_ts: Optional[float] = None
    rule_age_secs: Optional[float] = None
    exception_type: str = ""


def _resolve_ig_min_stop_pips_with_ts(
    epic: str, pair: str,
) -> tuple[Optional[float], str, Optional[float]]:
    """Return (value, source, cache_ts). Extension of
    _resolve_ig_min_stop_pips that exposes the cache entry's timestamp
    so the preflight can compute rule age for observability."""
    live_or_stale = _fetch_ig_min_stop_for_epic(epic)
    if live_or_stale is not None:
        now = time.time()
        with _MARKET_MIN_STOP_LOCK:
            cached = _MARKET_MIN_STOP_CACHE.get(str(epic))
        if cached is not None:
            _val, _ts = cached
            src = "live" if (now - _ts) < SL_AMEND_LIVE_DEALING_RULES_TTL_SECS else "cached"
            return float(live_or_stale), src, float(_ts)
        # Value came from _fetch_ig_min_stop_for_epic but the cache is
        # somehow empty (race / cleared between read and here). Treat as
        # stale-source, no timestamp available.
        return float(live_or_stale), "cached", None
    return (_ig_min_stop_pips_for_pair(pair), "static", None)


def _fetch_ig_min_stop_for_epic(
    epic: str, force_refresh: bool = False,
) -> Optional[float]:
    """Fetch IG's dealingRules.minNormalStopOrLimitDistance for ``epic``.

    Returns the value in FX pips (== IG POINTS for FX spread-bet). None
    on any failure — callers MUST decide whether to proceed (per
    2026-09-14 operator ruling: absent a safe current value, DEFER the
    amend rather than infer or clamp).

    Positive cache holds for SL_AMEND_LIVE_DEALING_RULES_TTL_SECS
    (default 15 min). Negative cache (fetch-failure backoff) suppresses
    fetch_market_by_epic calls during a broker outage — see the
    _FETCH_BACKOFF_* constants above. ``force_refresh=True`` bypasses
    the positive cache; it does NOT bypass the failure backoff (a
    per-tick force-refresh loop would defeat the negative cache).
    """
    if not epic:
        return None
    epic_s = str(epic)
    now = time.time()

    # ── Fast path + gate check under the lock. Do NOT hold the lock
    #    across the network call.
    with _MARKET_MIN_STOP_LOCK:
        cached = _MARKET_MIN_STOP_CACHE.get(epic_s)
        if cached is not None and not force_refresh:
            _val, _ts = cached
            if now - _ts < SL_AMEND_LIVE_DEALING_RULES_TTL_SECS:
                return float(_val)
        failure = _MARKET_MIN_STOP_FAILURE.get(epic_s)
        in_backoff = (
            failure is not None
            and now < float(failure.get("next_retry_ts", 0.0) or 0.0)
        )
        if in_backoff:
            _emit_backoff_epic = epic_s
            _emit_backoff_count = int(failure.get("count", 0) or 0)
            _emit_backoff_reason = str(failure.get("reason", "") or "")
            _emit_backoff_next = float(failure.get("next_retry_ts", 0.0) or 0.0)
            _emit_backoff_source = "cached" if cached is not None else "none"
            _stale_val = float(cached[0]) if cached is not None else None
        else:
            _emit_backoff_epic = None
            _stale_val = None
        if in_backoff or epic_s in _MARKET_MIN_STOP_INFLIGHT:
            # Either back-off active OR another thread is already fetching
            # this epic. Return current cache state without launching a
            # second REST call. Concurrent-tick collapse to one request.
            if in_backoff:
                # Emit outside the lock below; capture snapshot above.
                pass
            _return_stale = float(cached[0]) if cached is not None else None
            _skip_fetch = True
        else:
            _MARKET_MIN_STOP_INFLIGHT.add(epic_s)
            _skip_fetch = False

    if _skip_fetch:
        if _emit_backoff_epic is not None:
            _emit_fetch_obs(
                "FETCH_BACKOFF", _emit_backoff_epic,
                _emit_backoff_source,
                failure_count=_emit_backoff_count,
                reason_category=_emit_backoff_reason or None,
                retry_delay_secs=max(0.0, _emit_backoff_next - now),
                next_retry_ts=_emit_backoff_next,
            )
        return _return_stale

    _val_f: Optional[float] = None
    _reason_cat: Optional[str] = None
    _exc_type: str = ""
    try:
        try:
            from ig_auth import get_ig_session as _get_ig
            ig, _h, _a = _get_ig()
            resp = ig.fetch_market_by_epic(epic_s)
        except Exception as _fetch_exc:
            _exc_type = type(_fetch_exc).__name__
            _reason_cat = "FETCH_EXCEPTION"
            resp = None

        if _reason_cat is None:
            try:
                rules = None
                if isinstance(resp, dict):
                    rules = resp.get("dealingRules") or {}
                else:
                    rules = getattr(resp, "dealingRules", None) or {}
                _mnd = None
                if isinstance(rules, dict):
                    _mnd = rules.get("minNormalStopOrLimitDistance")
                else:
                    _mnd = getattr(rules, "minNormalStopOrLimitDistance", None)
                _val = None
                _unit = None
                if isinstance(_mnd, dict):
                    _val = _mnd.get("value")
                    _unit = _mnd.get("unit")
                elif _mnd is not None:
                    _val = getattr(_mnd, "value", None)
                    _unit = getattr(_mnd, "unit", None)
                if _val is None:
                    _reason_cat = "EMPTY_RESPONSE"
                elif (
                    _unit is not None
                    and str(_unit).upper() not in ("POINTS", "")
                ):
                    _reason_cat = "UNSUPPORTED_UNIT"
                else:
                    _val_f = float(_val)
            except Exception as _parse_exc:
                _exc_type = type(_parse_exc).__name__
                _reason_cat = "PARSE_EXCEPTION"

        # Commit success / failure to state under the lock.
        with _MARKET_MIN_STOP_LOCK:
            if _val_f is not None:
                _MARKET_MIN_STOP_CACHE[epic_s] = (_val_f, now)
                prior_failure = _MARKET_MIN_STOP_FAILURE.pop(epic_s, None)
                new_count = 0
                delay = 0.0
                next_retry_ts = 0.0
            else:
                prior = _MARKET_MIN_STOP_FAILURE.get(epic_s)
                prev_count = int(prior.get("count", 0)) if prior else 0
                new_count = prev_count + 1
                delay = _fetch_backoff_delay_for_count(new_count)
                next_retry_ts = now + delay
                _MARKET_MIN_STOP_FAILURE[epic_s] = {
                    "count": new_count,
                    "reason": _reason_cat or "UNKNOWN",
                    "exc_type": _exc_type,
                    "failed_at": now,
                    "next_retry_ts": next_retry_ts,
                }
                prior_failure = None

        if _val_f is not None:
            if prior_failure is not None:
                _emit_fetch_obs(
                    "FETCH_RECOVERED", epic_s, "live",
                    failure_count=int(prior_failure.get("count", 0) or 0),
                    reason_category=None,
                )
            logger.debug(
                "[IG_MIN_STOP_FETCH] %s = %.2fp (cached %ds)",
                epic_s, _val_f, int(SL_AMEND_LIVE_DEALING_RULES_TTL_SECS),
            )
            return _val_f

        _cache_source = "cached" if cached is not None else "none"
        _emit_fetch_obs(
            "FETCH_FAILED", epic_s, _cache_source,
            failure_count=new_count,
            reason_category=_reason_cat,
            retry_delay_secs=delay,
            next_retry_ts=next_retry_ts,
        )
        return float(cached[0]) if cached is not None else None
    finally:
        with _MARKET_MIN_STOP_LOCK:
            _MARKET_MIN_STOP_INFLIGHT.discard(epic_s)


def _invalidate_ig_min_stop_cache(epic: str) -> None:
    """Drop the cached dealingRules min-stop for ``epic`` after
    ATTACHED_ORDER_LEVEL_ERROR so the next fetch reads fresh.

    Also clears the fetch-failure gate — but only when a positive cache
    entry actually existed. That asymmetry matters: during backoff the
    positive cache is empty, so an invalidation call in that state is
    a no-op and cannot promote a repeated ATTACHED_ORDER_LEVEL_ERROR
    tick into a per-tick forced fetch. First rejection with a live rule
    clears cache+gate and allows exactly one immediate refetch; if that
    refetch fails, the normal backoff engages and subsequent rejections
    (with no positive cache to invalidate) have no effect on the gate.
    """
    if not epic:
        return
    epic_s = str(epic)
    with _MARKET_MIN_STOP_LOCK:
        had_positive = _MARKET_MIN_STOP_CACHE.pop(epic_s, None) is not None
        if had_positive:
            _MARKET_MIN_STOP_FAILURE.pop(epic_s, None)


def _stop_owner_hint(pos_key: str) -> str:
    """Best-effort naming of which manager currently owns the broker
    stop for ``pos_key``. Consulted only by observability; never used
    to gate a decision. Returns one of: 'RATCHET', 'LADDER',
    'BB_BOUNCE', 'PROFILE', 'EXECUTOR', 'UNKNOWN'."""
    try:
        import tiered_ratchet as _tr
        if _tr.is_ratchet_active(pos_key):
            return "RATCHET"
    except Exception:
        pass
    try:
        import level_ladder as _ll
        if _ll.is_ladder_active(pos_key):
            return "LADDER"
    except Exception:
        pass
    try:
        _meta = _PROFIT_MGMT_BY_EPIC.get(pos_key) or {}
        if _meta.get("bb_trail_lock", 0):
            return "BB_BOUNCE"
        if _meta.get("profile_id"):
            return "PROFILE"
    except Exception:
        pass
    return "EXECUTOR"


def _emit_amend_attempt_row(
    *,
    pos_key: str,
    epic: str,
    pair: str,
    direction: str,
    deal_id: Optional[str],
    deal_ref: Optional[str],
    prev_stop: float,
    requested_stop: float,
    bid: Optional[float],
    offer: Optional[float],
    live_mid: Optional[float],
    min_distance: Optional[float],
    min_distance_unit: str,
    min_distance_source: str,
    threshold_pips: Optional[float],
    dist_pips: Optional[float],
    decision: str,
    local_reason: str = "",
    broker_status: str = "",
    broker_reason: str = "",
    confirmed_stop: Optional[float] = None,
    stop_owner: str = "",
    level: str = "info",
    # Post-2026-09-14 blocker-fix additions. All optional (default None
    # or ""). New callers pass the preflight struct's fields; older
    # callers that don't set them still produce a coherent row.
    validation_price: Optional[float] = None,
    validation_side: str = "",
    rule_age_secs: Optional[float] = None,
    decision_reason: str = "",
) -> None:
    """Emit one structured amend-attempt row per Item 6 of the
    2026-09-14 defect-#9 brief. Never raises; observability only."""
    try:
        _mode = pos_key.split("|", 1)[1] if "|" in pos_key else "-"

        def _fmt(v: Any, spec: str) -> str:
            if v is None:
                return "None"
            try:
                return format(float(v), spec)
            except (TypeError, ValueError):
                return str(v)

        _row = (
            "[SL_AMEND_ATTEMPT] pos_key=%s pair=%s epic=%s strategy=%s "
            "direction=%s deal=%s dealRef=%s prev_stop=%s requested_stop=%s "
            "bid=%s offer=%s live_mid=%s validation_side=%s validation_price=%s "
            "min_distance=%s unit=%s src=%s rule_age_secs=%s "
            "threshold=%s dist=%s decision=%s decision_reason=%s local_reason=%s "
            "broker_status=%s broker_reason=%s confirmed_stop=%s owner=%s"
        )
        _args = (
            pos_key, pair, epic, _mode,
            direction, deal_id or "-", deal_ref or "-",
            _fmt(prev_stop, ".5f"), _fmt(requested_stop, ".5f"),
            _fmt(bid, ".5f"), _fmt(offer, ".5f"), _fmt(live_mid, ".5f"),
            (validation_side or "-"),
            _fmt(validation_price, ".5f") if validation_price is not None else "None",
            _fmt(min_distance, ".2f") if min_distance is not None else "None",
            (min_distance_unit or "-"), (min_distance_source or "-"),
            _fmt(rule_age_secs, ".1f") if rule_age_secs is not None else "None",
            _fmt(threshold_pips, ".2f") if threshold_pips is not None else "None",
            _fmt(dist_pips, ".2f") if dist_pips is not None else "None",
            decision, (decision_reason or "-"), (local_reason or "-"),
            (broker_status or "-"), (broker_reason or "-"),
            _fmt(confirmed_stop, ".5f") if confirmed_stop is not None else "-",
            stop_owner or "-",
        )
        if str(level).lower() == "debug":
            logger.debug(_row, *_args)
        elif str(level).lower() == "warning":
            logger.warning(_row, *_args)
        else:
            logger.info(_row, *_args)
    except Exception:
        pass


def _resolve_ig_min_stop_pips(
    epic: str, pair: str,
) -> tuple[Optional[float], str]:
    """Return (min_stop_pips, source). Source is one of:
      * "live"     — freshly fetched IG dealingRules (safe to submit).
      * "cached"   — stale cache, live fetch failed. Not authoritative
                     for authorising an amend; the pre-flight guard
                     DEFERs on this source (see blocker 1).
      * "static"   — no live/cached value; per-pair hardcoded default.
                     Never authoritative — pre-flight DEFERs.
      * "none"     — nothing was available. DEFER.

    Thin wrapper over _resolve_ig_min_stop_pips_with_ts that discards
    the timestamp. Preserved for existing readers.
    """
    _val, _src, _ = _resolve_ig_min_stop_pips_with_ts(epic, pair)
    return _val, _src


def _sl_amend_should_gate(pos_key: str, new_sl_price: float,
                          direction: str) -> tuple[bool, str]:
    """Consult the per-position failure tracker. Return (allow, reason).

    Called at the top of _amend_broker_sl before hitting the broker.
    - allow=True, reason="ok"        — proceed with amend as normal.
    - allow=True, reason="ratchet"   — breaker was open but this is a
                                       genuinely higher lock; grant one
                                       attempt so a recovered session
                                       plus a new peak can still lock.
    - allow=False, reason=<why>      — suppress; caller returns False
                                       without hitting the broker.

    Direction of ratchet: BUY → higher sl_price is better; SELL → lower.
    Read env at call-time so a knob change takes effect on the next tick.
    """
    meta = _PROFIT_MGMT_BY_EPIC.get(pos_key)
    if meta is None:
        return True, "ok"
    fails = int(meta.get("consecutive_amend_failures", 0) or 0)
    if fails <= 0:
        return True, "ok"

    _bo_after = int(os.getenv("SL_AMEND_BACKOFF_AFTER", "")
                    or SL_AMEND_BACKOFF_AFTER)
    _bo_secs = float(os.getenv("SL_AMEND_BACKOFF_SECS", "")
                     or SL_AMEND_BACKOFF_SECS)
    _bo2_after = int(os.getenv("SL_AMEND_BACKOFF2_AFTER", "")
                     or SL_AMEND_BACKOFF2_AFTER)
    _bo2_secs = float(os.getenv("SL_AMEND_BACKOFF2_SECS", "")
                      or SL_AMEND_BACKOFF2_SECS)
    _cb_after = int(os.getenv("SL_AMEND_CIRCUIT_AFTER", "")
                    or SL_AMEND_CIRCUIT_AFTER)

    last_attempt_sl = meta.get("last_amend_attempt_sl")
    ratchet = False
    if last_attempt_sl is not None:
        try:
            _last = float(last_attempt_sl)
            _new = float(new_sl_price)
            _dir = str(direction or "").upper()
            if _dir == "BUY" and _new > _last:
                ratchet = True
            elif _dir == "SELL" and _new < _last:
                ratchet = True
        except (TypeError, ValueError):
            ratchet = False

    # Circuit-break: hard stop unless a new ratchet re-opens for one attempt.
    if fails >= _cb_after:
        if ratchet:
            return True, "ratchet"
        return False, "circuit_break"

    # Backoff tiers — min gap between attempts. A ratchet does NOT jump
    # the queue for tier-1/tier-2 (only circuit-break re-opens on ratchet)
    # because the goal here is to reduce load on a broker that's saying
    # NO to our proposed levels; a slightly-different SL is still likely
    # to be rejected for the same reason.
    last_ts = float(meta.get("last_amend_attempt_ts", 0.0) or 0.0)
    now = time.time()
    if fails >= _bo2_after:
        if now - last_ts < _bo2_secs:
            return False, "backoff2"
    elif fails >= _bo_after:
        if now - last_ts < _bo_secs:
            return False, "backoff1"

    return True, "ok"


def _sl_amend_was_suppressed(pos_key: str) -> bool:
    """True iff the most recent _amend_broker_sl call for pos_key was
    suppressed by the backoff/circuit-break gate (broker was NOT
    contacted). Callers use this to skip their per-caller "amend NOT
    confirmed" warning during the backoff window."""
    meta = _PROFIT_MGMT_BY_EPIC.get(pos_key)
    if meta is None:
        return False
    return bool(meta.get("_sl_amend_last_suppressed", False))


def _sl_amend_on_success(pos_key: str, new_sl_price: float) -> None:
    """Reset the failure tracker after a confirmed amend. Closes the
    breaker if it was open. Called on any successful amend."""
    meta = _PROFIT_MGMT_BY_EPIC.get(pos_key)
    if meta is None:
        return
    was_broken = int(meta.get("consecutive_amend_failures", 0) or 0) >= int(
        os.getenv("SL_AMEND_CIRCUIT_AFTER", "") or SL_AMEND_CIRCUIT_AFTER
    )
    meta["consecutive_amend_failures"] = 0
    meta["last_amend_attempt_ts"] = time.time()
    meta["last_amend_attempt_sl"] = float(new_sl_price)
    meta["last_known_sl_price"] = float(new_sl_price)
    meta.pop("_sl_amend_backoff_logged", None)
    meta.pop("_sl_amend_circuit_logged", None)
    if was_broken:
        logger.info(
            "[SL_AMEND_BREAKER] %s closed on success — new_sl=%.5f",
            pos_key, float(new_sl_price),
        )


def _sl_amend_on_failure(pos_key: str, new_sl_price: float,
                         direction: str) -> None:
    """Increment the failure tracker after a rejected/failed amend.
    Emits one log on entering each backoff tier and one on circuit-break;
    subsequent suppressed attempts stay silent. Fires a Telegram alert
    on circuit-break when SL_AMEND_ALERTS_ENABLED=1 (default)."""
    meta = _PROFIT_MGMT_BY_EPIC.get(pos_key)
    if meta is None:
        meta = {}
        _PROFIT_MGMT_BY_EPIC[pos_key] = meta
    fails = int(meta.get("consecutive_amend_failures", 0) or 0) + 1
    meta["consecutive_amend_failures"] = fails
    meta["last_amend_attempt_ts"] = time.time()
    meta["last_amend_attempt_sl"] = float(new_sl_price)

    _bo_after = int(os.getenv("SL_AMEND_BACKOFF_AFTER", "")
                    or SL_AMEND_BACKOFF_AFTER)
    _bo_secs = float(os.getenv("SL_AMEND_BACKOFF_SECS", "")
                     or SL_AMEND_BACKOFF_SECS)
    _bo2_after = int(os.getenv("SL_AMEND_BACKOFF2_AFTER", "")
                     or SL_AMEND_BACKOFF2_AFTER)
    _bo2_secs = float(os.getenv("SL_AMEND_BACKOFF2_SECS", "")
                      or SL_AMEND_BACKOFF2_SECS)
    _cb_after = int(os.getenv("SL_AMEND_CIRCUIT_AFTER", "")
                    or SL_AMEND_CIRCUIT_AFTER)

    logged_tier = meta.get("_sl_amend_backoff_logged")
    if fails == _bo_after and logged_tier != "1":
        logger.info(
            "[SL_AMEND_BACKOFF] %s entering backoff tier 1 — %d consecutive "
            "failures; min gap between attempts %.0fs until success or tier 2",
            pos_key, fails, _bo_secs,
        )
        meta["_sl_amend_backoff_logged"] = "1"
    elif fails == _bo2_after and logged_tier != "2":
        logger.warning(
            "[SL_AMEND_BACKOFF] %s entering backoff tier 2 — %d consecutive "
            "failures; min gap between attempts %.0fs until success or circuit-break",
            pos_key, fails, _bo2_secs,
        )
        meta["_sl_amend_backoff_logged"] = "2"

    if fails == _cb_after and not meta.get("_sl_amend_circuit_logged"):
        meta["_sl_amend_circuit_logged"] = True
        _first_ts = float(
            meta.get("_sl_amend_first_fail_ts") or meta["last_amend_attempt_ts"]
        )
        _first_iso = datetime.fromtimestamp(_first_ts, tz=timezone.utc).isoformat()
        _last_known = meta.get("last_known_sl_price", "unknown")
        logger.warning(
            "[SL_AMEND_CIRCUIT] %s CIRCUIT-BREAK — %d consecutive amend "
            "failures since %s; suppressing further attempts. "
            "Broker SL may be STALE at %s. Ratchet-reopen on next NEW lock.",
            pos_key, fails, _first_iso, _last_known,
        )
        _alerts_on = (
            os.getenv("SL_AMEND_ALERTS_ENABLED", SL_AMEND_ALERTS_ENABLED_DEFAULT)
            or SL_AMEND_ALERTS_ENABLED_DEFAULT
        ).strip().lower() in ("1", "true", "yes", "on")
        if _alerts_on:
            try:
                # Same alert channel as TRADE OPENED/CLOSED — send_error_alert
                # reuses send_telegram_message, so it hits the same chat as
                # send_trade_close_alert.
                st = _state_for_epic(pos_key)
                deal_id = st.get("dealId") or st.get("deal_id") or pos_key
                mode = str(st.get("mode") or "unknown")
                from telegram_alerts import send_error_alert
                send_error_alert(
                    "⚠️ SL AMEND CIRCUIT-BREAK "
                    f"deal={deal_id} mode={mode} — "
                    f"{fails} consecutive amend failures since {_first_iso}. "
                    f"Broker SL may be STALE at {_last_known}. "
                    "Manual check required."
                )
            except Exception as _tg_exc:
                logger.debug(
                    "[SL_AMEND_CIRCUIT] telegram alert failed: %s", _tg_exc,
                )

    # Stamp the first-fail timestamp once so the alert message has an
    # anchor to the start of the failure window.
    if fails == 1:
        meta["_sl_amend_first_fail_ts"] = meta["last_amend_attempt_ts"]


def _sl_amend_preflight_min_distance(
    pos_key: str, new_sl_price: float, pair: str,
    direction: Optional[str] = None,
) -> _AmendPreflight:
    """Compute the pre-flight amend decision as one immutable struct.

    Post-2026-09-14 review posture (four activation blockers closed):
      * Only source="live" (fresh IG dealingRules ≤ TTL) authorises a
        submit. "cached"/"static"/"none" DEFER — a stale cached value
        is not an authoritative current broker rule.
      * Missing authoritative validation price DEFERs (fail-closed).
        For a BUY position IG validates the attached stop against the
        current BID (the price at which the stop closes the position
        by selling). For a SELL, the current OFFER. Missing that side
        means the preflight cannot prove broker validity, so it must
        preserve the previously confirmed broker stop.
      * Any exception raised while resolving preflight state DEFERs
        (fail-closed) with reason PREFLIGHT_EXCEPTION and the
        exception's type name recorded for observability.

    Returned struct is consumed by both the DEFER path and the
    [SL_AMEND_ATTEMPT] receipt so a logical attempt resolves broker
    rules exactly once.

    A DEFER never contacts the broker and never increments
    consecutive_amend_failures — the failure-tracker / backoff /
    circuit-break state is preserved.
    """
    _margin_pips = float(
        os.getenv("SL_AMEND_MIN_DIST_MARGIN_PIPS", "")
        or SL_AMEND_MIN_DIST_MARGIN_PIPS
    )
    try:
        st = _state_for_epic(pos_key)
        _dir = str(direction or st.get("direction") or "").upper()
        if _dir == "BUY":
            _side_label = "BID"
            _side_price = _safe_float(st.get("last_bid"), None)
        elif _dir == "SELL":
            _side_label = "OFFER"
            _side_price = (
                _safe_float(st.get("last_ask"), None)
                if st.get("last_ask") is not None
                else _safe_float(st.get("last_offer"), None)
            )
        else:
            return _AmendPreflight(
                defer=True, reason="MARKET_PRICE_UNAVAILABLE",
                validation_side="UNKNOWN", margin_pips=_margin_pips,
            )
        if _side_price is None or _side_price <= 0:
            return _AmendPreflight(
                defer=True, reason="MARKET_PRICE_UNAVAILABLE",
                validation_side=_side_label, margin_pips=_margin_pips,
            )

        _epic = str(st.get("epic") or pos_key.split("|", 1)[0])
        _min_pips, _src, _rule_ts = _resolve_ig_min_stop_pips_with_ts(
            _epic, pair,
        )
        _rule_age = None
        if _rule_ts is not None:
            _rule_age = max(0.0, time.time() - float(_rule_ts))

        if _src != "live" or _min_pips is None:
            logger.debug(
                "[SL_AMEND_DEFER_RULE] pos_key=%s pair=%s src=%s — DEFER "
                "(proposed=%.5f %s=%.5f)",
                pos_key, pair, _src, float(new_sl_price),
                _side_label, float(_side_price),
            )
            # Compute a threshold for the observability receipt when we
            # do have a non-live value (static/stale cache); this DOES
            # NOT authorise submission — the preflight is already DEFER.
            _thr_obs = (
                (float(_min_pips) + _margin_pips)
                if _min_pips is not None else None
            )
            return _AmendPreflight(
                defer=True, reason="LIVE_RULE_UNAVAILABLE",
                validation_price=float(_side_price),
                validation_side=_side_label,
                min_distance_pips=_min_pips,
                margin_pips=_margin_pips,
                threshold_pips=_thr_obs,
                source=_src, rule_ts=_rule_ts, rule_age_secs=_rule_age,
            )

        _threshold_pips = float(_min_pips) + _margin_pips
        # Direction-signed distance from the authoritative price side.
        # IG validates a BUY stop against the current BID (stop must be
        # below bid by min_distance); a SELL stop against the current
        # OFFER (stop must be above offer by min_distance). See the
        # blocker-fix commit rationale for the API-side derivation.
        if _dir == "BUY":
            _dist_pips = float(_side_price) - float(new_sl_price)
        else:
            _dist_pips = float(new_sl_price) - float(_side_price)

        if _dist_pips < _threshold_pips:
            return _AmendPreflight(
                defer=True, reason="MIN_DISTANCE_NOT_SATISFIED",
                validation_price=float(_side_price),
                validation_side=_side_label,
                dist_pips=_dist_pips,
                min_distance_pips=float(_min_pips),
                margin_pips=_margin_pips,
                threshold_pips=_threshold_pips,
                source=_src, rule_ts=_rule_ts, rule_age_secs=_rule_age,
            )

        return _AmendPreflight(
            defer=False, reason="OK",
            validation_price=float(_side_price),
            validation_side=_side_label,
            dist_pips=_dist_pips,
            min_distance_pips=float(_min_pips),
            margin_pips=_margin_pips,
            threshold_pips=_threshold_pips,
            source=_src, rule_ts=_rule_ts, rule_age_secs=_rule_age,
        )
    except Exception as _pf_exc:
        # Fail-closed: an unexpected exception cannot authorise an
        # amend. Preserve the last confirmed broker stop and log the
        # exception's TYPE only — the payload may carry account or
        # credential data (e.g. from an IG SDK error) so we do not
        # log the full message body here.
        logger.debug(
            "[SL_AMEND_PREFLIGHT_EXCEPTION] pos_key=%s type=%s",
            pos_key, type(_pf_exc).__name__,
        )
        return _AmendPreflight(
            defer=True, reason="PREFLIGHT_EXCEPTION",
            margin_pips=_margin_pips,
            exception_type=type(_pf_exc).__name__,
        )


def _sl_amend_should_defer_min_distance(
    pos_key: str, new_sl_price: float, pair: str,
    direction: Optional[str] = None,
) -> tuple[bool, float, float]:
    """Back-compat wrapper. Return (defer, dist_pips, threshold_pips).

    Delegates to _sl_amend_preflight_min_distance so tests and any
    older callers that unpack the 3-tuple continue to work. New
    production code should call the preflight helper directly and use
    the immutable _AmendPreflight struct end-to-end.
    """
    _pf = _sl_amend_preflight_min_distance(
        pos_key, new_sl_price, pair, direction,
    )
    return (
        bool(_pf.defer),
        float(_pf.dist_pips if _pf.dist_pips is not None else 0.0),
        float(_pf.threshold_pips if _pf.threshold_pips is not None
              else _pf.margin_pips),
    )


def _amend_broker_sl(pos_key: str, new_sl_price: float,
                     current_tp_price: float) -> bool:
    """Amend broker SL + preserve given TP for ANY position.

    `pos_key`         — "<epic>|<mode>" (same key used by EPIC_STATE).
    `new_sl_price`    — absolute price for the new stop level.
    `current_tp_price`— absolute price to keep as the broker's limit_level.

    Returns True on success, False on any failure (defensive — failures
    log but never raise; software-tracked SL stays as fallback).
    """
    try:
        st = _state_for_epic(pos_key)
        deal_id = st.get("dealId") or st.get("deal_id")
        direction = str(st.get("direction") or "").upper()
        entry = _safe_float(st.get("entry_price"))
        if not deal_id or direction not in ("BUY", "SELL") or entry is None or entry <= 0:
            logger.warning(
                "[SCALE_OUT] broker SL amend skipped: missing context "
                "(deal_id=%s direction=%s entry=%s)",
                deal_id, direction, entry,
            )
            return False
        new_stop = round(float(new_sl_price), 1)
        limit_level = round(float(current_tp_price), 1)
        # Pre-flight IG min-distance DEFER (2026-07-21). If the proposed
        # SL is inside IG's per-pair min-stop distance from the freshest
        # in-process tick, skip the API attempt: it would bounce with
        # ATTACHED_ORDER_LEVEL_ERROR. Ratchet state in the caller is
        # untouched (the SAME lock is re-proposed on the next monitor
        # tick), and consecutive_amend_failures is NOT incremented —
        # a DEFER is not a rejection, so it must not feed the breaker.
        # Fixes root cause of the 2026-07-20 storm (lock +10.7p, price
        # ~1p away → ~1000 attempts before the c0d34cc breaker tripped).
        _pair = _pair_from_epic(str(st.get("epic") or pos_key.split("|", 1)[0]))
        # Single preflight resolution per attempt. The returned
        # _AmendPreflight struct is threaded through the DEFER / REJECT
        # / SUBMIT_ACCEPTED branches so a logical amend never resolves
        # broker rules twice (blocker 4).
        _pf = _sl_amend_preflight_min_distance(
            pos_key, float(new_stop), _pair, direction,
        )
        if _pf.defer:
            _meta_defer = _PROFIT_MGMT_BY_EPIC.get(pos_key)
            if _meta_defer is None:
                _meta_defer = {}
                _PROFIT_MGMT_BY_EPIC[pos_key] = _meta_defer
            # Mark suppressed so callers skip their per-caller
            # "amend NOT confirmed" warning — a deferral is expected.
            _meta_defer["_sl_amend_last_suppressed"] = True
            logger.debug(
                "[SL_AMEND_DEFER] deal=%s proposed=%.5f reason=%s "
                "side=%s dist=%s threshold=%s src=%s",
                deal_id, float(new_stop), _pf.reason,
                _pf.validation_side,
                ("%.2fp" % _pf.dist_pips) if _pf.dist_pips is not None else "None",
                ("%.2fp" % _pf.threshold_pips) if _pf.threshold_pips is not None else "None",
                _pf.source,
            )
            _epic_def = str(st.get("epic") or pos_key.split("|", 1)[0])
            _emit_amend_attempt_row(
                pos_key=pos_key, epic=_epic_def, pair=_pair,
                direction=direction, deal_id=deal_id, deal_ref=None,
                prev_stop=float(_meta_defer.get("last_known_sl_price", 0.0) or 0.0),
                requested_stop=float(new_stop),
                bid=_safe_float(st.get("last_bid"), None),
                offer=_safe_float(st.get("last_ask") or st.get("last_offer"), None),
                live_mid=_safe_float(st.get("last_mid"), None),
                min_distance=_pf.min_distance_pips,
                min_distance_unit="POINTS",
                min_distance_source=_pf.source,
                threshold_pips=_pf.threshold_pips,
                dist_pips=_pf.dist_pips,
                decision="DEFER_LOCAL",
                decision_reason=_pf.reason,
                local_reason=(
                    f"exception={_pf.exception_type}"
                    if _pf.reason == "PREFLIGHT_EXCEPTION"
                    else _pf.reason.lower()
                ),
                validation_price=_pf.validation_price,
                validation_side=_pf.validation_side,
                rule_age_secs=_pf.rule_age_secs,
                stop_owner=_stop_owner_hint(pos_key),
                level="debug",
            )
            return False
        # Failure-aware gate. Suppresses attempts (and their log spam)
        # once F1 consecutive rejections have set the backoff, and hard-
        # stops after F3 with a Telegram alert. A genuinely NEW ratchet
        # (higher lock for BUY, lower for SELL) grants ONE attempt after
        # circuit-break so a recovered session + new peak can still lock.
        # Callers check _sl_amend_was_suppressed(pos_key) to decide
        # whether to also skip their per-caller "amend NOT confirmed"
        # warning — the point of the backoff is to stop the log spam.
        _gate_ok, _gate_reason = _sl_amend_should_gate(
            pos_key, new_stop, direction,
        )
        _meta_gate = _PROFIT_MGMT_BY_EPIC.get(pos_key)
        if _meta_gate is None:
            _meta_gate = {}
            _PROFIT_MGMT_BY_EPIC[pos_key] = _meta_gate
        if not _gate_ok:
            _meta_gate["_sl_amend_last_suppressed"] = True
            return False
        _meta_gate["_sl_amend_last_suppressed"] = False
        if _broker_sl_amend_fn is not None:
            _resp = _broker_sl_amend_fn(deal_id, new_stop, limit_level)
        else:
            from ig_auth import get_ig_session
            ig, _h, _a = get_ig_session()
            _resp = ig.update_open_position(
                limit_level=limit_level,
                stop_level=new_stop,
                deal_id=deal_id,
            )
        # Inspect IG's confirm-shape response the same way the partial-close
        # path does at _scale_out_50pct (:1668) — a 2xx that carries
        # dealStatus != "ACCEPTED" is a rejection, not a success. Pre-fix
        # the return value was discarded, so an embedded rejection stamped
        # last_amended_sl_price and misled _detect_ig_close_reason (live
        # incident 2026-06-29 deal DIAAAAXVHRL2ZAH).
        if not _resp or (isinstance(_resp, dict) and str(_resp.get("dealStatus") or "").upper() != "ACCEPTED"):
            _reason = (
                str(_resp.get("reason")) if isinstance(_resp, dict) and _resp.get("reason") is not None
                else str(_resp) if _resp is not None
                else "empty response"
            )
            logger.warning(
                "[SCALE_OUT] broker SL amend NOT ACCEPTED for %s: deal=%s resp=%s",
                pos_key, deal_id, _resp,
            )
            try:
                _meta = _PROFIT_MGMT_BY_EPIC.get(pos_key)
                if _meta is None:
                    _meta = {}
                    _PROFIT_MGMT_BY_EPIC[pos_key] = _meta
                _meta["last_amend_reject_reason"] = _reason
            except Exception:
                pass
            # Defect #9 (2026-09-14): on IG's min-distance rejection,
            # invalidate the cached dealingRules for this epic so the
            # next amend attempt refetches. This defends against IG rule
            # changes that raise the effective minimum above what we last
            # cached. Also emit a structured observability row (Item 6).
            try:
                _epic_str = str(st.get("epic") or pos_key.split("|", 1)[0])
                if str(_reason).upper() == "ATTACHED_ORDER_LEVEL_ERROR":
                    _invalidate_ig_min_stop_cache(_epic_str)
                _dealref = None
                _broker_status = ""
                if isinstance(_resp, dict):
                    _dealref = _resp.get("dealReference")
                    _broker_status = str(_resp.get("dealStatus") or "")
                # Reuse the preflight struct captured at the top of the
                # attempt — do NOT re-resolve broker rules here. That
                # protects against classification drift between decision
                # and receipt (blocker 4).
                _emit_amend_attempt_row(
                    pos_key=pos_key, epic=_epic_str, pair=_pair,
                    direction=direction, deal_id=deal_id, deal_ref=_dealref,
                    prev_stop=float(_meta.get("last_known_sl_price", 0.0) or 0.0),
                    requested_stop=float(new_stop),
                    bid=_safe_float(st.get("last_bid"), None),
                    offer=_safe_float(st.get("last_ask") or st.get("last_offer"), None),
                    live_mid=_safe_float(st.get("last_mid"), None),
                    min_distance=_pf.min_distance_pips,
                    min_distance_unit="POINTS",
                    min_distance_source=_pf.source,
                    threshold_pips=_pf.threshold_pips,
                    dist_pips=_pf.dist_pips,
                    decision="REJECT_BROKER",
                    decision_reason=_pf.reason,
                    local_reason="",
                    broker_status=_broker_status,
                    broker_reason=str(_reason),
                    confirmed_stop=None,
                    validation_price=_pf.validation_price,
                    validation_side=_pf.validation_side,
                    rule_age_secs=_pf.rule_age_secs,
                    stop_owner=_stop_owner_hint(pos_key),
                    level="info",
                )
            except Exception:
                pass
            _sl_amend_on_failure(pos_key, new_stop, direction)
            return False
        logger.info(
            "[SCALE_OUT] broker SL amended: %s deal=%s stop=%.1f limit=%.1f",
            pos_key, deal_id, new_stop, limit_level,
        )
        # Defect #9 (2026-09-14): structured "one row per state transition"
        # observability (Item 6). Correlates the request-path deal_id with
        # the response confirm dealReference, bid/offer/mid at attempt,
        # applicable min-distance and its source, and the decision. Only
        # fired on ACCEPTED — the REJECT_BROKER equivalent is emitted
        # above in the not-ACCEPTED branch.
        try:
            _epic_str_ok = str(st.get("epic") or pos_key.split("|", 1)[0])
            _dealref_ok = None
            _broker_status_ok = ""
            _confirmed_stop_ok = None
            if isinstance(_resp, dict):
                _dealref_ok = _resp.get("dealReference")
                _broker_status_ok = str(_resp.get("dealStatus") or "")
                _confirmed_stop_ok = _resp.get("stopLevel")
            _meta_read = _PROFIT_MGMT_BY_EPIC.get(pos_key) or {}
            # Reuse the preflight struct captured at the top of the
            # attempt (blocker 4). No re-resolution against IG.
            _emit_amend_attempt_row(
                pos_key=pos_key, epic=_epic_str_ok, pair=_pair,
                direction=direction, deal_id=deal_id, deal_ref=_dealref_ok,
                prev_stop=float(_meta_read.get("last_known_sl_price", 0.0) or 0.0),
                requested_stop=float(new_stop),
                bid=_safe_float(st.get("last_bid"), None),
                offer=_safe_float(st.get("last_ask") or st.get("last_offer"), None),
                live_mid=_safe_float(st.get("last_mid"), None),
                min_distance=_pf.min_distance_pips,
                min_distance_unit="POINTS",
                min_distance_source=_pf.source,
                threshold_pips=_pf.threshold_pips,
                dist_pips=_pf.dist_pips,
                decision="SUBMIT_ACCEPTED",
                decision_reason=_pf.reason,
                local_reason="",
                broker_status=_broker_status_ok,
                broker_reason="",
                # On ACCEPTED IG usually echoes stopLevel back; fall back
                # to the requested value when not present (some update
                # endpoints omit it on success).
                confirmed_stop=(
                    _confirmed_stop_ok if _confirmed_stop_ok is not None
                    else float(new_stop)
                ),
                validation_price=_pf.validation_price,
                validation_side=_pf.validation_side,
                rule_age_secs=_pf.rule_age_secs,
                stop_owner=_stop_owner_hint(pos_key),
                level="info",
            )
        except Exception:
            pass
        # Stash the latest amended SL price on the profit-mgmt meta so the
        # broker-side close classifier can recognise a trail/BE/amended-SL
        # exit (see _detect_ig_close_reason). Persisted across restarts.
        # Only reached on confirmed ACCEPTED response.
        try:
            _meta = _PROFIT_MGMT_BY_EPIC.get(pos_key)
            if _meta is None:
                _meta = {}
                _PROFIT_MGMT_BY_EPIC[pos_key] = _meta
            _meta["last_amended_sl_price"] = float(new_stop)
            _meta["last_amended_sl_ts"] = time.time()
            # Parallel to last_amended_sl_price (2026-08-14): the same PUT
            # sets both stop and limit, so record the amended limit too. Lets
            # _detect_ig_close_reason recognise a limit fill against the
            # amended level directly, instead of inferring via last_mid vs
            # entry+tp_pips (last_mid can trail the fill by several pips —
            # see the 08:38:12 GBPUSD_TREND_V3_L mislabel).
            _meta["last_amended_limit_price"] = float(limit_level)
            _meta["last_amended_limit_ts"] = time.time()
            _meta.pop("last_amend_reject_reason", None)
        except Exception:
            pass
        _sl_amend_on_success(pos_key, new_stop)
        return True
    except Exception as exc:
        logger.warning(
            "[SCALE_OUT] broker SL amend failed for %s: %s", pos_key, exc,
        )
        try:
            _dir = str(_state_for_epic(pos_key).get("direction") or "").upper()
        except Exception:
            _dir = ""
        _sl_amend_on_failure(pos_key, round(float(new_sl_price), 1), _dir)
        return False


# ── Scale-out master flag (2026-05-23) ──────────────────────────────────
SCALE_OUT_AT_10P_ENABLED = (os.getenv("SCALE_OUT_AT_10P_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes")
SCALE_OUT_TRIGGER_PIPS = float(os.getenv("SCALE_OUT_TRIGGER_PIPS", "10") or 10.0)
SCALE_OUT_FRACTION = float(os.getenv("SCALE_OUT_FRACTION", "0.5") or 0.5)

# ── Trend-style runner trail (2026-05-23) ────────────────────────────────
# After scale-out fires (broker SL → BE, half banked), trend-style strategies
# get a 3-step ratcheting trail driven by peak MFE. Non-trend scaled runners
# (BB_BOUNCE / BB_REV_PAT / BRIEFING_EXECUTION etc.) ride BE+TP unchanged —
# their natural target is mean/opposite-band, not extended trend.
#
# Step trigger / lock pattern: SL moves to entry + (peak - offset). Never
# regresses, never below BE. 8p offset gives ~5-7p 5m-noise room (does NOT
# strangle — runner at +12 just past scale-out sits at BE, not closed).
_TREND_RUNNER_STYLE_MODES: frozenset = frozenset({
    "GBPUSD_TREND_L", "GBPUSD_TREND_S",
    # STRUCTURE_BREAK was briefly added here (2026-06-15) to share TREND's
    # stepped ratchet. Reverted same day in favour of a dedicated continuous
    # peak-pivot trail (_apply_structure_break_runner_trail below). gbpusd_
    # trend's stepped path stays unchanged.
    # EMA_PULLBACK is a continuation strategy and trend-style by design —
    # added 2026-06-27 so the runner inherits the same stepped trail
    # (+15/+25/+40 triggers, lock = trigger − OFFSET, BE-floored). Trail
    # math is entry-relative and pnl-driven (see _apply_trend_runner_trail
    # below), so it is safe with EMA_PULLBACK's SL=12p — by the time the
    # trail engages the broker SL is already at BE (scale-out moved it),
    # and the first lock (+7p at peak +15p) sits well above BE.
    "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
})
TREND_TRAIL_OFFSET_PIPS = float(os.getenv("REGIME_TREND_TRAIL_OFFSET_PIPS", "8") or 8.0)
# Step thresholds: peak MFE in pips. Step lock = peak - offset.
TREND_TRAIL_STEP_TRIGGERS_PIPS = (15.0, 25.0, 40.0)
# Kill-switch added 2026-06-30 (third of three: SB 479e280, BB_BOUNCE 363ee0c,
# now TREND/EMA_PULLBACK). 30-day forensic of 17 scaled-out EMA_PULLBACK
# runners found the trail effectively never engages: activate threshold
# (+15p, step 1) sits on top of the EMA_PULLBACK TP target (+15p), so the
# broker TP closes the runner before the trail's first step can ratchet.
# Zero TRAIL_STOP rows in 30 days; 7/17 hit TP, the rest sat in the BE
# band (mfe < 15p) or were manual closes. The L+97.8 vs trail+75.0 and
# S+60.0 vs +77.8 replay split is N=17 noise on a no-op trail. For
# GBPUSD_TREND_L/_S (TP=80p, where the +15/+25/+40 steps would have
# headroom), zero fires in the 30-day window — untested in live. With
# this flag "0" (default) the runner sits at the BE SL installed by
# scale-out and rides to broker TP / REGIME_MAX_HOLD / structure_exit
# only — matching BB_REV_PAT/BRIEFING/SB-trail-off/BB_BOUNCE-trail-off
# behaviour. Flip to "1" for byte-identical legacy stepped trail. Env
# read at function call-time so a flip takes effect on the next tick
# without restart.
TREND_RUNNER_TRAIL_ENABLED_DEFAULT = "0"


# ── BB_BOUNCE runner trail (2026-06-05) ──────────────────────────────────
# Post-scale-out trail for GBPUSD_BB_BOUNCE_L/S runners. Same SL primitive
# as scale-out's BE move (_amend_broker_sl) so there is ONE SL path:
# entry (BE) ≤ broker_SL ≤ entry + (peak − offset). Monotonic upward.
# Activate only past +ACTIVATE pips of peak MFE; floor at entry (the BE
# move already installed at scale-out). Gated on meta["scaled_out"] AND
# meta["be_amend_ok"] — without a confirmed BE we must not start moving
# the broker SL further (would compound the unconfirmed-amend risk).
#
# Per-leg kill-switch (2026-06-30, reconciles 363ee0c with honest
# full-window counterfactual). Original 363ee0c flipped both legs OFF
# based on a 30-min one-sided peak-excursion calc that was a windowed
# MFE summary, not an actual exit walk: 7 of 8 "continuations" reverted
# to BE within ~35-102 min, just past the replay clip. Full-window walk
# of all 17 BB_BOUNCE TRAIL_STOPs over 2026-06-16..30:
#   L (8 trades): trail-on banked +61.0p; BE+TP-off would have banked
#       +0.0p (all 8 reverted to BE within ~102 min, none reached TP).
#       → L leg WINS with trail ON. Default "1".
#   S (9 trades): trail-on banked +113.2p; BE+TP-off would have banked
#       +300.0p (3 of 9 reach broker TP, other 6 to BE). → S leg WINS
#       with trail OFF (+186.85p edge, though tail-dependent on 3 wins).
#       Default "0".
# So the gate is asymmetric: L trail ON (byte-identical legacy trail),
# S trail OFF (rides BE installed by scale-out + broker TP + time-stop).
# Either side flippable from .env without restart (read at call-time).
#
# Note: the prior single-flag BB_BOUNCE_RUNNER_TRAIL_ENABLED is GONE.
# A value in .env for the old name is now ignored.
BB_BOUNCE_L_RUNNER_TRAIL_ENABLED_DEFAULT = "1"
BB_BOUNCE_S_RUNNER_TRAIL_ENABLED_DEFAULT = "0"
BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS = float(
    os.getenv("BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS", "12") or 12.0
)
BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS = float(
    os.getenv("BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS", "6") or 6.0
)
_BB_BOUNCE_TRAIL_MODES: frozenset = frozenset({
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
})


# ── EMA_PULLBACK runner trail (2026-07-20) ───────────────────────────────
# Post-scale-out peak-pivot trail for GBPUSD_EMA_PULLBACK_L/S runners.
# Reuses the same primitive as BB_BOUNCE (_apply_peak_pivot_runner_trail_core
# + _amend_broker_sl); one SL path per position: entry (BE, installed by
# scale-out) ≤ broker_SL ≤ entry + (peak − OFFSET). Monotonic upward,
# floor enforced by max(0, peak − OFFSET) so the trail can never amend SL
# below the BE that scale-out installed. Gated on meta["scaled_out"] AND
# meta["be_amend_ok"] AND mode ∈ _EMA_PULLBACK_TRAIL_MODES.
#
# Defaults 20/8 (activate/offset): activates only after price commits
# past +20p (a proper runner), then trails 8p behind peak. EMA_PULLBACK's
# fire-time TP is +15p, but scale-out at +10p already banked half and the
# runner rides broker-TP-or-trail; the ACTIVATE=20 arms only when peak
# clears the fire-time TP, giving the runner room past the scale-out
# ledge before the trail engages.
#
# Kill-switch EMA_PULLBACK_RUNNER_TRAIL_ENABLED (default "1"). When "0"
# the trail no-ops — the runner sits at the BE installed by scale-out and
# rides to broker TP / REGIME_MAX_HOLD / structure_exit only (byte-
# identical to the pre-2026-07-20 EMA_PULLBACK runner path where the
# stepped trend trail is off by default and never engaged in practice).
EMA_PULLBACK_RUNNER_TRAIL_ENABLED_DEFAULT = "1"
EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS = float(
    os.getenv("EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS", "20") or 20.0
)
EMA_PULLBACK_RUNNER_TRAIL_OFFSET_PIPS = float(
    os.getenv("EMA_PULLBACK_RUNNER_TRAIL_OFFSET_PIPS", "8") or 8.0
)
_EMA_PULLBACK_TRAIL_MODES: frozenset = frozenset({
    "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
})


# ── BB_BOUNCE post-scale runner floor (2026-07-01) ───────────────────────
# Applies to BOTH GBPUSD_BB_BOUNCE_L and _S. After scale-out fires and
# peak MFE clears ARM_PIPS (default 10p), floor the broker SL at
# entry + FLOOR_PIPS × ppp (default +5p, BUY; mirrored for SELL). Ratchet-
# up-only via the SHARED meta["bb_bounce_trail_lock_pips"] marker — the
# same variable the L trail uses. This gives free max()-composition:
#   L leg: trail sets lock=peak-6 once peak≥12; floor arms at peak≥10 with
#          lock=5. Whichever is higher wins — as peak climbs, the trail's
#          lock (peak-6) exceeds 5 at peak≥11, so the trail takes over and
#          the floor never fights it. The floor's only job is to catch a
#          post-scale give-back that occurs BEFORE the trail activates
#          (peak stalled at 10–11p, then reverts).
#   S leg: trail is OFF by default, so nothing else writes the lock. The
#          floor is the sole post-scale protection above BE — once peak
#          clears 10p, SL sits at +5p and can only be hit by a give-back
#          that comes down through +5p. A runner that stays above +5p is
#          never below the floor, so this cannot touch a winner.
# The rule is max(existing_stop, floor). Because the lock variable is
# strictly monotonic (all writers only raise it), sharing it with the
# trail IS the max() — no separate reconciliation needed.
BB_BOUNCE_POST_SCALE_FLOOR_ENABLED_DEFAULT = "1"
BB_BOUNCE_POST_SCALE_FLOOR_PIPS = float(
    os.getenv("BB_BOUNCE_POST_SCALE_FLOOR_PIPS", "5") or 5.0
)
BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS = float(
    os.getenv("BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS", "10") or 10.0
)


# ── BB_BOUNCE condition-aware exit profile (2026-08-06) ─────────────────
# Squeeze full-close vs expanded runner-mode. One-shot decision at the
# first bar reaching +EXIT_PROFILE_TRIGGER_PIPS favourable excursion:
# raw BB(20,2) width_pips (ruler; width_norm logged only) selects
# SQUEEZE (full-close at entry ± max(SQUEEZE_TARGET, 1.2·width)) vs
# EXPANDED/NEUTRAL (standard scale-out + trail unchanged). Thresholds
# from the 2026-08-06 width calibration pass (95 t7-reaching fires;
# 13/13 BIG25 monsters had width_pips@t7 ≥ 12.05p, median 16.6p).
# Default OFF in code; env activates.
EXIT_PROFILE_ENABLED_DEFAULT = "0"
EXIT_PROFILE_TRIGGER_PIPS_DEFAULT = 7.0
EXIT_SQUEEZE_WIDTH_PIPS_DEFAULT = 12.0
EXIT_EXPANDED_WIDTH_PIPS_DEFAULT = 14.0
EXIT_SQUEEZE_TARGET_PIPS_DEFAULT = 10.0
EXIT_PROFILE_RECHECK_BARS_DEFAULT = 6

# 2026-08-12: SQUEEZE partial-then-trail (env kill-switch, default OFF).
# When enabled, the SQUEEZE branch banks the scale-out fraction at the
# target instead of full-closing, then hands the remainder to the
# existing BB_BOUNCE runner trail + post-scale floor exactly as a normal
# scale-out would. Motivating case: 2026-08-11 05:50 GBPUSD_BB_BOUNCE_S
# @ 13512.3 → SQUEEZE full-closed at 13502.0 (+10.3p) at 06:33 while
# price ran to 13494.85 by 07:40 (17.45p from entry, 7.15p left on the
# table). EXPANDED / NEUTRAL / REVERTED_EXPANDED branches unchanged.
EXIT_PROFILE_SQUEEZE_PARTIAL_ENABLED_DEFAULT = "0"


def _exit_profile_enabled() -> bool:
    return (
        os.getenv("EXIT_PROFILE_ENABLED", EXIT_PROFILE_ENABLED_DEFAULT)
        or EXIT_PROFILE_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")


def _exit_profile_squeeze_partial_enabled() -> bool:
    return (
        os.getenv("EXIT_PROFILE_SQUEEZE_PARTIAL_ENABLED",
                  EXIT_PROFILE_SQUEEZE_PARTIAL_ENABLED_DEFAULT)
        or EXIT_PROFILE_SQUEEZE_PARTIAL_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")


def _exit_profile_env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or "").strip() or default)
    except Exception:
        return float(default)


def _exit_profile_env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except Exception:
        return int(default)


def _apply_exit_profile(
    epic: str,
    st: Dict[str, Any],
    meta: Dict[str, Any],
    pair: str,
    pip_size: float,
    entry_price: float,
    direction: str,
    current_price: float,
    best_pnl: float,
) -> None:
    """Condition-aware BB_BOUNCE exit profile — see header block above.

    State-machine on meta["exit_profile"]:
      undecided         : trigger evaluation when best_pnl >= trigger_pips
      decided/SQUEEZE   : per-tick target check + one recheck at
                          RECHECK_BARS completed bars; on revert flips
                          to REVERTED_EXPANDED so the standard scale-out
                          gate re-opens on the next tick.
      decided/EXPANDED  : no ongoing action (existing stack proceeds)
      decided/NEUTRAL   : no ongoing action (existing stack proceeds)
      decided/REVERTED_EXPANDED : same as EXPANDED (post-recheck)
      decided/CLOSED    : target hit, close issued (idempotency)
    """
    trigger_pips = _exit_profile_env_float(
        "EXIT_PROFILE_TRIGGER_PIPS", EXIT_PROFILE_TRIGGER_PIPS_DEFAULT,
    )
    squeeze_w = _exit_profile_env_float(
        "EXIT_SQUEEZE_WIDTH_PIPS", EXIT_SQUEEZE_WIDTH_PIPS_DEFAULT,
    )
    expanded_w = _exit_profile_env_float(
        "EXIT_EXPANDED_WIDTH_PIPS", EXIT_EXPANDED_WIDTH_PIPS_DEFAULT,
    )
    squeeze_target = _exit_profile_env_float(
        "EXIT_SQUEEZE_TARGET_PIPS", EXIT_SQUEEZE_TARGET_PIPS_DEFAULT,
    )
    recheck_bars = _exit_profile_env_int(
        "EXIT_PROFILE_RECHECK_BARS", EXIT_PROFILE_RECHECK_BARS_DEFAULT,
    )

    ep = meta.get("exit_profile")
    deal_id = st.get("dealId") or st.get("deal_id") or epic

    # ── Undecided branch: trigger fires when best_pnl >= trigger_pips ──
    if not ep or not ep.get("decided"):
        if float(best_pnl) < float(trigger_pips):
            return
        # One-shot decision. Fetch closes; if unavailable, skip (no
        # decision recorded — will re-attempt next tick).
        try:
            import candle_builder as _cb
            df = _cb.get_df(pair)
        except Exception as _cb_exc:
            logger.warning(
                "[EXIT-PROFILE] %s candle_builder.get_df raised: %s "
                "(will retry next tick)",
                deal_id, _cb_exc,
            )
            return
        if df is None or getattr(df, "empty", True):
            return
        try:
            closes = df["close"].astype(float).tolist()
            highs = df["high"].astype(float).tolist()
            lows = df["low"].astype(float).tolist()
        except Exception:
            return
        try:
            import ribbon_state as _rs
            bw = _rs.band_width(closes, highs=highs, lows=lows,
                                pip_size=float(pip_size))
        except Exception as _bw_exc:
            logger.warning(
                "[EXIT-PROFILE] %s band_width raised: %s "
                "(will retry next tick)",
                deal_id, _bw_exc,
            )
            return
        if bw is None:
            # <40 bars — insufficient seed. Do not stamp a decision;
            # next tick may have enough bars.
            return
        width_pips, width_norm = bw

        # Classify.
        # CHOP-mode override (2026-08-12): when chop_mode.should_force_
        # squeeze() is True at decision time, force mode_dec = "SQUEEZE"
        # regardless of measured width. This does NOT touch the
        # EXPANDED / NEUTRAL branches themselves — it re-routes the
        # decision into the existing SQUEEZE branch which already owns
        # target computation, per-tick target check, recheck-to-
        # REVERTED_EXPANDED, and partial-vs-full-close switch. Kill-
        # switch: CHOP_MODE_FORCE_SQUEEZE=0 disables the override even
        # when the master CHOP_MODE_ENABLED=1.
        _cm_force = False
        try:
            import chop_mode as _cm
            _cm_force = bool(_cm.should_force_squeeze())
        except Exception as _cm_exc:
            logger.debug("[CHOP-MODE] force_squeeze check raised: %s", _cm_exc)
        if _cm_force or width_pips < float(squeeze_w):
            mode_dec = "SQUEEZE"
            _tgt = max(float(squeeze_target), 1.2 * float(width_pips))
            if direction == "BUY":
                target_price = float(entry_price) + _tgt * float(pip_size)
            else:
                target_price = float(entry_price) - _tgt * float(pip_size)
            target_desc = f"{target_price:.5f} (+{_tgt:.2f}p)"
            if _cm_force and width_pips >= float(squeeze_w):
                logger.info(
                    "[EXIT-PROFILE] %s CHOP_MODE_FORCE_SQUEEZE — "
                    "measured width=%.2f (>=%.2f) overridden to SQUEEZE",
                    deal_id, float(width_pips), float(squeeze_w),
                )
        elif width_pips >= float(expanded_w):
            mode_dec = "EXPANDED"
            target_price = None
            target_desc = "n/a"
        else:
            mode_dec = "NEUTRAL"
            target_price = None
            target_desc = "n/a"

        # Trigger-bar timestamp for recheck bar counting.
        trigger_bar_ts = None
        try:
            trigger_bar_ts = str(df["time"].iloc[-1])
        except Exception:
            pass

        meta["exit_profile"] = {
            "decided": True,
            "mode": mode_dec,
            "trigger_pips": float(best_pnl),
            "width_pips": float(width_pips),
            "width_norm": (float(width_norm) if width_norm is not None else None),
            "target_price": target_price,
            "target_pips": (float(_tgt) if mode_dec == "SQUEEZE" else None),
            "trigger_bar_ts": trigger_bar_ts,
            "recheck_done": False,
            "closed": False,
        }
        _norm_str = f"{width_norm:.3f}" if width_norm is not None else "n/a"
        logger.info(
            "[EXIT-PROFILE] %s trigger@+%.1f width=%.2f (norm=%s) "
            "mode=%s target=%s",
            deal_id, float(trigger_pips), float(width_pips), _norm_str,
            mode_dec, target_desc,
        )
        return

    # ── Decided branch ────────────────────────────────────────────────
    mode_dec = str(ep.get("mode") or "").upper()

    # EXPANDED / NEUTRAL / REVERTED_EXPANDED: nothing further to do here.
    # The standard scale-out + trail stack runs unchanged for the
    # position; scale-out's own +8p gate remains authoritative.
    if mode_dec in ("EXPANDED", "NEUTRAL", "REVERTED_EXPANDED", "CLOSED"):
        return

    if mode_dec != "SQUEEZE":
        return  # unknown mode — leave alone

    # SQUEEZE: check target, then (optionally) recheck.
    if ep.get("closed"):
        return

    target_price = ep.get("target_price")
    if target_price is None:
        return  # defensive — SQUEEZE without a target shouldn't happen

    hit = False
    if direction == "BUY":
        hit = float(current_price) >= float(target_price)
    else:
        hit = float(current_price) <= float(target_price)

    if hit:
        # 2026-08-12: partial-then-trail branch. When the kill-switch is
        # on, bank the scale-out fraction via _scale_out_50pct (line 2578,
        # invoked identically at line 5151 by the universal +10p scale
        # gate) and let the BB_BOUNCE runner trail + post-scale floor
        # manage the remainder. _scale_out_50pct sets meta["scaled_out"]=
        # True + meta["be_amend_ok"], which is exactly what the trail
        # gates on (line 1697-1701) and what the floor uses to arm.
        # Fallback: on partial failure (size<2, amend rejected, exception)
        # the meta latches are NOT set, so we do NOT mark ep["closed"];
        # the next tick re-attempts. Full-close path is unchanged when
        # the flag is off.
        if _exit_profile_squeeze_partial_enabled():
            try:
                _scale_out_50pct(epic, pair, float(pip_size), meta)
            except Exception as _partial_exc:
                logger.warning(
                    "[EXIT-PROFILE] %s squeeze partial raised: %s",
                    deal_id, _partial_exc,
                )
                return
            if meta.get("scaled_out"):
                ep["closed"] = True
                realised_pips = _calculate_pnl_pips(
                    direction, float(entry_price), float(current_price),
                    float(pip_size),
                )
                logger.info(
                    "[EXIT-PROFILE] partial-close SQUEEZE %s @ %.5f "
                    "+%.1fp (EXIT_PROFILE_SQUEEZE_PARTIAL) width_was=%.2f "
                    "— runner handed to BB_BOUNCE trail/floor",
                    deal_id, float(current_price), float(realised_pips),
                    float(ep.get("width_pips") or 0.0),
                )
            else:
                logger.warning(
                    "[EXIT-PROFILE] %s partial did NOT set scaled_out — "
                    "leaving ep.closed=False so next tick re-attempts",
                    deal_id,
                )
            return

        # Close the entire position via the same close machinery every
        # other strategy exit uses (see _close_trade_best_effort at
        # trade_manager.py:2948 → _exec.close_position).
        try:
            _close_trade_best_effort(
                epic, "EXIT_PROFILE_SQUEEZE", float(target_price),
            )
            ep["closed"] = True
            realised_pips = _calculate_pnl_pips(
                direction, float(entry_price), float(current_price),
                float(pip_size),
            )
            logger.info(
                "[EXIT-PROFILE] full-close %s @ %.5f +%.1fp width_was=%.2f",
                deal_id, float(current_price), float(realised_pips),
                float(ep.get("width_pips") or 0.0),
            )
        except Exception as _cl_exc:
            logger.warning(
                "[EXIT-PROFILE] %s squeeze close raised: %s",
                deal_id, _cl_exc,
            )
        return

    # Re-check clause. One-shot after RECHECK_BARS completed bars.
    if ep.get("recheck_done"):
        return
    trig_ts = ep.get("trigger_bar_ts")
    if not trig_ts:
        return
    try:
        import candle_builder as _cb
        df = _cb.get_df(pair)
    except Exception:
        return
    if df is None or getattr(df, "empty", True):
        return
    try:
        # Count completed bars strictly AFTER trigger_bar_ts.
        _times = df["time"].astype(str).tolist()
        bars_since = sum(1 for t in _times if t > str(trig_ts))
    except Exception:
        return
    if bars_since < int(recheck_bars):
        return

    # Perform the recheck: recompute width; revert only if now >= expanded_w.
    try:
        closes = df["close"].astype(float).tolist()
        highs = df["high"].astype(float).tolist()
        lows = df["low"].astype(float).tolist()
        import ribbon_state as _rs
        bw2 = _rs.band_width(closes, highs=highs, lows=lows,
                             pip_size=float(pip_size))
    except Exception as _rc_exc:
        logger.warning(
            "[EXIT-PROFILE] %s recheck band_width raised: %s "
            "(marking recheck_done to avoid re-attempt loop)",
            deal_id, _rc_exc,
        )
        ep["recheck_done"] = True
        return
    if bw2 is None:
        ep["recheck_done"] = True
        return
    w2_pips, w2_norm = bw2
    ep["recheck_done"] = True
    _norm_str = f"{w2_norm:.3f}" if w2_norm is not None else "n/a"
    if w2_pips >= float(expanded_w):
        # Revert. Downstream scale-out gate is (meta.get("exit_profile")
        # or {}).get("mode") == "SQUEEZE" — flipping to
        # REVERTED_EXPANDED re-opens scale-out on the next tick:
        # best_pnl is already >= trigger_pips (7.0), so scale-out
        # fires as soon as best_pnl >= SCALE_OUT_TRIGGER_PIPS (env=8),
        # and the standard trail follows.
        ep["mode"] = "REVERTED_EXPANDED"
        logger.info(
            "[EXIT-PROFILE] recheck %s bars_since=%d width=%.2f "
            "(norm=%s) -> REVERTED_EXPANDED (scale-out+trail re-armed)",
            deal_id, int(bars_since), float(w2_pips), _norm_str,
        )
    else:
        logger.info(
            "[EXIT-PROFILE] recheck %s bars_since=%d width=%.2f "
            "(norm=%s) -> SQUEEZE unchanged (target=%.5f still armed)",
            deal_id, int(bars_since), float(w2_pips), _norm_str,
            float(target_price),
        )


# ── Uniform runner trail+floor rollout (2026-07-29) ──────────────────────
# Master kill-flag for the uniform trail+floor rollout across fade-type
# strategies. Sizing: peak-pivot activate=12 offset=6, floor arm=10 lock=5
# — data-derived from the 162-scaled-runner corpus (2026-07-29 analysis:
# recovered-pullback p85=6.5p, median post-scale peak 16.6p, BE_STOP pool
# gives back 8.6p median).
#
# When "1" (default):
#   - BB_BOUNCE_S runner trail: engages (env override BB_BOUNCE_S_RUNNER_
#     TRAIL_ENABLED=1 flips it on; without this kill-flag the .env override
#     would still take effect, so the kill-flag is the master).
#   - EMA_PULLBACK_L/S trail: activate/offset FORCED to 12/6 (any env
#     override for EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS / _OFFSET_PIPS
#     is ignored under the master).
#   - NEWS_STRATEGY_CONT trail: activate/offset FORCED to 12/6 (env
#     override ignored under the master).
#   - Post-scale FLOOR: extended to _EMA_PULLBACK_TRAIL_MODES and
#     _NEWS_STRATEGY_CONT_TRAIL_MODES in addition to _BB_BOUNCE_TRAIL_MODES.
#     arm=10p lock=5p unchanged.
#
# When "0" — one-flip revert to pre-2026-07-29 behaviour:
#   - BB_BOUNCE_S trail forced OFF regardless of .env override.
#   - EMA_PB trail reverts to code default 20/8 (env ignored).
#   - NEWS_CONT trail reverts to code default 20/12 (env ignored).
#   - Floor modes revert to BB_BOUNCE_L/S only.
#   - BB_BOUNCE_L trail is untouched either way — the L trail was already
#     act=12 off=6 with floor arm=10 lock=5 pre-rollout.
#
# STRUCTURE_BREAK and CONFIRMATION_FALLBACK are OUT OF SCOPE — SB stays on
# BE+TP+REGIME_MAX_HOLD (its 80p-TP geometry is hurt by the peak-pivot
# trail per 2026-07-29 sim ΔTot −15.5p); CONFIRMATION_FALLBACK has N=3 in
# the corpus (no statistical basis).
UNIFORM_RUNNER_TRAIL_ENABLED_DEFAULT = "1"


def _uniform_trail_enabled() -> bool:
    return (
        os.getenv("UNIFORM_RUNNER_TRAIL_ENABLED",
                  UNIFORM_RUNNER_TRAIL_ENABLED_DEFAULT)
        or UNIFORM_RUNNER_TRAIL_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")


def _apply_pivot_break_targets(
    epic: str,
    st: Dict[str, Any],
    meta: Dict[str, Any],
    pair: str,
    pip_size: float,
    entry_price: float,
    direction: str,
    current_price: float,
) -> None:
    """PIVOT_BREAK target management: R1/S1 scale + R2/S2 runner via
    3-bar structure trail.

    Runs on every management tick for a PIVOT_BREAK position. Two phases:

    (1) Pre-scale — while meta["scaled_out"] is False, watch for price
        to cross the scale target (R1 for BUY / S1 for SELL) as encoded
        by the strategy in st["decision_debug"]["scale_target_price"].
        On cross, delegate the partial-close + BE-move to
        _scale_out_50pct (trade_manager.py:2658) — the same primitive
        the universal +10p gate uses. Idempotent via meta["scaled_out"]
        set by _scale_out_50pct itself.

    (2) Post-scale — the runner rides broker BE + broker TP (set to R2/
        S2 by trade_executor from decision.tp) until either the R2/S2
        limit fires or the structure trail closes. The structure trail
        reuses structure_exit.should_exit_structure (structure_exit.py:58)
        with a lookback override of PIVOT_BREAK_STRUCTURE_LOOKBACK_BARS
        (default 3), invoked from _monitor_ls_tick's post-scale hook
        addition below.

    Fail-open: any exception logs + returns; the trade continues under
    broker SL/TP without further intervention.
    """
    try:
        mode = str(st.get("mode") or "").upper()
        if mode not in _PIVOT_BREAK_TRAIL_MODES:
            return
        if meta.get("scaled_out"):
            return
        dbg = st.get("decision_debug") or {}
        scale_target = dbg.get("scale_target_price")
        if scale_target is None:
            return
        scale_target = float(scale_target)
        hit = False
        if direction == "BUY":
            hit = float(current_price) >= scale_target
        else:
            hit = float(current_price) <= scale_target
        if not hit:
            return
        deal_id = st.get("dealId") or st.get("deal_id") or epic
        logger.info(
            "[PIVOT_BREAK] %s scale target %s reached — current=%.5f target=%.5f",
            deal_id, "R1" if direction == "BUY" else "S1",
            float(current_price), float(scale_target),
        )
        _scale_out_50pct(epic, pair, float(pip_size), meta)
    except Exception as exc:
        logger.warning(
            "[PIVOT_BREAK] target hook raised for %s: %s",
            epic, exc,
        )


def _pivot_break_structure_lookback() -> int:
    """Runner-trail lookback for PIVOT_BREAK positions.

    Called by _pivot_break_should_exit_structure when st["mode"] is in
    _PIVOT_BREAK_TRAIL_MODES so PIVOT_BREAK runners trail under the prior
    3-bar extreme rather than the default 5. Env-tunable.
    """
    try:
        return int(os.getenv("PIVOT_BREAK_STRUCTURE_LOOKBACK_BARS", "3") or 3)
    except (TypeError, ValueError):
        return 3


def _pivot_break_should_exit_structure(
    symbol: str,
    direction: str,
    current_price: float,
) -> Tuple[bool, str]:
    """Structural runner trail for PIVOT_BREAK.

    Mirrors structure_exit.should_exit_structure (structure_exit.py:58) —
    same swing-detector logic on the same 5M bars via candle_builder —
    but scoped to PIVOT_BREAK's PIVOT_BREAK_STRUCTURE_LOOKBACK_BARS
    (default 3). Kept as a small local helper rather than an API
    extension of structure_exit so structure_exit's shared contract with
    the other five strategies that call it remains byte-identical.

    Semantics — mirrors structure_exit.py:118-128:
      SELL: exit when last 5m close > max(high) of prior N bars
      BUY:  exit when last 5m close < min(low)  of prior N bars

    No min_profit_pips gate — PIVOT_BREAK invokes this only post-scale,
    at which point the broker SL is already at BE and the runner is
    playing offense. Fail-open on any error.
    """
    try:
        lookback = _pivot_break_structure_lookback()
        try:
            import candle_builder
            df = candle_builder.get_df_raw(symbol)
        except Exception as exc:
            return False, f"candle_builder_unavailable:{exc}"
        if df is None or len(df) < lookback + 1:
            return False, "insufficient_5m_bars"
        recent = df.tail(lookback + 1)
        prior = recent.iloc[:-1]
        last = recent.iloc[-1]
        last_close = float(last.get("close"))
        direction_u = str(direction).upper()
        if direction_u in ("SELL", "SHORT", "S"):
            prior_high = float(prior["high"].max())
            if last_close > prior_high:
                return True, (
                    f"pivot_break_structure_flip_up: last_close={last_close:.5f} "
                    f"> prior_{lookback}_high={prior_high:.5f}"
                )
        elif direction_u in ("BUY", "LONG", "L"):
            prior_low = float(prior["low"].min())
            if last_close < prior_low:
                return True, (
                    f"pivot_break_structure_flip_down: last_close={last_close:.5f} "
                    f"< prior_{lookback}_low={prior_low:.5f}"
                )
        return False, "no_flip"
    except Exception as exc:
        return False, f"error:{exc}"


# ── Range-scalp Phase 2 profit floor ──────────────────────────────────────
# Under REGIME_MATRIX_ENABLED=1 the range-scalp does not force-close when
# effective_regime leaves RANGE_ROTATION (see _monitor_bb_range_scalp);
# instead a monotonic profit floor protects gains beyond
# RANGE_SCALP_FLOOR_TRIGGER_PIPS by ratcheting the broker SL to
# entry ± RANGE_SCALP_FLOOR_LOCK_PIPS × ppp. Mirrors the shape of
# _apply_bb_bounce_post_scale_floor (2026-06-25).
RANGE_SCALP_FLOOR_ENABLED_DEFAULT = "1"
RANGE_SCALP_FLOOR_TRIGGER_PIPS = float(
    os.getenv("RANGE_SCALP_FLOOR_TRIGGER_PIPS", "8") or 8.0
)
RANGE_SCALP_FLOOR_LOCK_PIPS = float(
    os.getenv("RANGE_SCALP_FLOOR_LOCK_PIPS", "8") or 8.0
)
RANGE_SCALP_ON_PROMOTION = (
    os.getenv("RANGE_SCALP_ON_PROMOTION", "ride") or "ride"
).strip().lower()
_REGIME_MATRIX_ENABLED_TM = (
    os.getenv("REGIME_MATRIX_ENABLED", "0") or "0"
).strip().lower() in ("1", "true", "yes", "on")

# ── Phase 3 regime-keyed management (2026-07-09) ─────────────────────────
# Master flag REGIME_MGMT_ENABLED (default 0). When ON, positions carrying
# a profile_id in _PROFILE_MANAGED bypass the legacy per-strategy trail
# multiplex (dispatch site trade_manager.py:3658-3724) and route through
# a profile-specific manager. RANGE and LEGACY profile trades run the
# legacy path unchanged — RANGE gets the telemetry stamp only, matching
# the "change no behaviour" clause in the build spec.
_REGIME_MGMT_ENABLED_TM = (
    os.getenv("REGIME_MGMT_ENABLED", "0") or "0"
).strip().lower() in ("1", "true", "yes", "on")

REGIME_MGMT_SCALE_TRIGGER_PIPS = float(
    os.getenv("REGIME_MGMT_SCALE_TRIGGER_PIPS", "8") or 8.0
)

# STRONG profile knobs — trail template cloned from
# _apply_structure_break_runner_trail with its own env space.
REGIME_MGMT_STRONG_TRAIL_ENABLED_DEFAULT = "1"
REGIME_MGMT_STRONG_TRAIL_OFFSET_PIPS = float(
    os.getenv("REGIME_MGMT_STRONG_TRAIL_OFFSET_PIPS", "8") or 8.0
)

# STRONG profile TP release (Fix 2, 2026-07-16). When ON, the +8p
# scale-out amend replaces the fire-time TP with a far sentinel so the
# runner cannot die at fire-time TP — the peak−8 ratchet + REGIME_LEFT
# exit own the runner's exit. Knob-off (default 0) = byte-identical to
# pre-Fix-2 behaviour (BE amend preserves fire-time TP). FORMING and
# LEGACY profiles are NOT touched by this knob (see _scale_out_50pct).
REGIME_MGMT_STRONG_TP_RELEASE = (
    os.getenv("REGIME_MGMT_STRONG_TP_RELEASE", "0") or "0"
).strip().lower() in ("1", "true", "yes", "on")
# Sentinel = entry ± this pips. Reads TREND_V3_MAX_TARGET_PIPS by
# design — same 200p ceiling TREND_V3 already uses when clamping its
# initial target (gbpusd_trend_v3.MAX_TARGET_PIPS). trading_ig's
# update_open_position wrapper omits limitLevel when None (rest.py:886)
# → cannot clear the broker TP through the wrapper; sentinel is the
# operationally correct alternative.
REGIME_MGMT_STRONG_TP_RELEASE_PIPS = float(
    os.getenv("TREND_V3_MAX_TARGET_PIPS", "200") or 200.0
)

# FORMING profile ladder — climbs broker TP through fixed pip levels.
# Default matches select_tp_levels fallback ladder (30/50/80) so the
# numbers aren't novel.
REGIME_MGMT_LADDER_PIPS_RAW = os.getenv(
    "REGIME_MGMT_LADDER_PIPS", "30,50,80"
) or "30,50,80"
try:
    REGIME_MGMT_LADDER_PIPS = tuple(
        float(x.strip()) for x in REGIME_MGMT_LADDER_PIPS_RAW.split(",")
        if x.strip()
    )
    if len(REGIME_MGMT_LADDER_PIPS) < 2:
        raise ValueError("need at least two rungs")
except Exception:
    REGIME_MGMT_LADDER_PIPS = (30.0, 50.0, 80.0)

_PROFILE_MANAGED = frozenset({"STRONG", "FORMING"})


def _skip_legacy_helper_for_profile(st: Dict[str, Any]) -> bool:
    """Guard: legacy trail/floor helpers must NOT fire on profile-managed
    trades. Recon Q5 collision guard 5.2 — the profile owns SL amends
    (STRONG) or TP amends (FORMING); a legacy helper double-amending
    against a different lock key would fight the profile's ratchet.
    Returns True when the helper should early-return.

    RANGE and LEGACY / None profiles return False — legacy helpers run
    unchanged, matching the "change no behaviour" clause for RANGE.
    """
    if not _REGIME_MGMT_ENABLED_TM:
        return False
    return str(st.get("profile_id") or "").upper() in _PROFILE_MANAGED


# ── STRUCTURE_BREAK runner trail (2026-06-15) ─────────────────────────────
# Dedicated continuous peak-pivot trail for GBPUSD_STRUCTURE_BREAK_L/_S
# runners. Same SL primitive as BB_BOUNCE/TREND trails (_amend_broker_sl)
# so there is ONE SL path per position: entry (BE) ≤ broker_SL ≤
# entry + (peak − offset) for BUY (mirror for SELL). Monotonic upward.
#
# CONTINUOUS from entry — no step triggers and no separate activation
# threshold; the max(0, peak − offset) clamp keeps SL at BE until peak ≥
# offset, then the SL trails one-for-one with peak. With OFFSET = 8p:
#   peak +8p  → lock +0p (still BE)
#   peak +10p → lock +2p
#   peak +15p → lock +7p
#   peak +20p → lock +12p
#   peak +40p → lock +32p
# Engages ONLY when meta["scaled_out"] is True (the +10p / 50% scale-out
# has fired and moved broker SL to BE) AND meta["be_amend_ok"] is True
# (BE move confirmed — same prerequisite the BB_BOUNCE trail uses).
STRUCTURE_BREAK_RUNNER_TRAIL_OFFSET_PIPS = float(
    os.getenv("STRUCTURE_BREAK_TRAIL_OFFSET_PIPS", "8") or 8.0
)
# Kill-switch for the trail above (2026-06-30). Default OFF per 30-day
# replay of 77 scaled-out runners: the +8p continuous trail is net-
# negative vs pure BE — it clips the TP-tail (the ~19% of runners that
# reach broker TP and carry the edge, ~+383p) at +7-47p locks. Pure BE
# banked +953p vs the trail's +685p (−268p). On SB-only: SB_L +107p BE
# vs +54p trailed, SB_S +95p vs +24p. With this flag "0" the runner sits
# at BE (set by scale-out) and rides to broker TP / structure_exit /
# REGIME_MAX_HOLD only — matching BB_REV_PAT/BRIEFING behaviour. Flip
# to "1" for byte-identical legacy trail behaviour. Env read at function
# call-time so a flip takes effect on the next tick without restart.
STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED_DEFAULT = "0"
_STRUCTURE_BREAK_TRAIL_MODES: frozenset = frozenset({
    "GBPUSD_STRUCTURE_BREAK_L", "GBPUSD_STRUCTURE_BREAK_S",
})
# PIVOT_BREAK mode set — coil-at-pivot entry with R1/S1 scale + R2/S2
# runner + 3-bar structure trail. See gbpusd_pivot_break.py.
_PIVOT_BREAK_TRAIL_MODES: frozenset = frozenset({
    "GBPUSD_PIVOT_BREAK_L", "GBPUSD_PIVOT_BREAK_S",
})
# REGIME_MAX_HOLD cap for PIVOT_BREAK. The 2026-08-12 breakout took 125
# minutes to reach R1; the runner phase needs headroom beyond the pair's
# regime-router default (NEWS=60, SWEEP=120, TREND=240). Pin to a wide
# 480-min ceiling so the pre-scale phase has room to reach R1 on a slow
# grind. Post-scale, REGIME_MAX_HOLD_SCALED_OUT_EXEMPT already exempts
# the runner regardless of this value.
PIVOT_BREAK_MAX_HOLD_MIN = int(
    os.getenv("PIVOT_BREAK_MAX_HOLD_MIN", "480") or 480
)
# REGIME_MAX_HOLD per-mode override for structure_break (2026-06-18).
# Without this, structure_break inherits the pair's regime_router default
# (NEWS=60, SWEEP=120, TREND=240). On NEWS days that 60-min cap clipped
# the 06-18 07:25 SHORT mid-trail at +15.6p while +43.9p of run remained.
# Pin to 240m so the continuous peak-pivot trail (see
# _apply_structure_break_runner_trail) owns the exit instead of the
# regime-of-the-day clock. Env-tunable; reuses _STRUCTURE_BREAK_TRAIL_MODES
# so the mode set is co-located with the trail it serves.
STRUCTURE_BREAK_TIME_STOP_MINUTES = float(
    os.getenv("STRUCTURE_BREAK_TIME_STOP_MINUTES", "240") or 240.0
)


# ── NEWS_STRATEGY_CONT runner trail (2026-07-03) ─────────────────────────
# Post-scale-out peak-pivot trail for NEWS_STRATEGY_CONT runners. Same
# SL primitive as BB_BOUNCE/SB/scale-out (_amend_broker_sl), monotonic
# upward, guarded on scaled_out + be_amend_ok + mode.
#
# WHY WIDER THAN BB_BOUNCE (20/12 vs 12/6): news whipsaws in two-way
# spikes. 2026-06-11 GBPUSD SELL ran the RIGHT direction +38.9p AFTER
# hitting SL first — a tight trail (12/6) would activate on the initial
# up-tick and get chopped by the reversal. 20p activation defers the
# trail until price commits directionally, at which point 12p offset
# gives ~5-10p noise room around news candles.
#
# CEILING BACKSTOP: news_strategy.py extends the runner TP at fire time
# to fade_caps.max_tp_pips (default NEWS_FADE_MAX_TP_PIPS=50) when the
# flag is on. This trail runs BENEATH that ceiling — if price rockets
# to +50p before the trail can ratchet, the broker TP fires and profit
# is taken at the ceiling. The trail is the primary runner exit for the
# common continuation case (+20-40p range); the ceiling catches the
# rare +50p spike.
#
# Kill-switch: NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED (default "1").
# When "0": (a) news_strategy.py skips the TP-ceiling extension at fire
# time (runner keeps the small spike-geometry TP), and (b) this trail
# no-ops. Byte-identical to pre-2026-07-03 behaviour when off for the
# WHOLE lifecycle of a position (flag flips only affect new fires and
# the next trail-eval tick; mid-flight runners retain their TP).
NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED_DEFAULT = "1"
NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS = float(
    os.getenv("NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS", "20") or 20.0
)
NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS = float(
    os.getenv("NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS", "12") or 12.0
)
_NEWS_STRATEGY_CONT_TRAIL_MODES: frozenset = frozenset({
    "NEWS_STRATEGY_CONT",
})


def _apply_trend_runner_trail(epic: str, pos_key: str, st: Dict[str, Any],
                              meta: Dict[str, Any], pair: str, ppp: float,
                              best_pnl_pips: float) -> None:
    """Ratchet broker SL up as the runner's peak MFE extends.

    Engages ONLY when:
        TREND_RUNNER_TRAIL_ENABLED is "1" (kill switch, default "0"), AND
        meta["scaled_out"] is True, AND
        strategy mode is in _TREND_RUNNER_STYLE_MODES (TREND_L/S +
        EMA_PULLBACK_L/S).
    SL moves are monotonic (never regress), floored at entry (BE). Uses
    _amend_broker_sl with the original broker TP preserved.

    Kill-switched via TREND_RUNNER_TRAIL_ENABLED (default "0", OFF).
    When OFF, the trail does not run — the runner sits at the BE SL
    installed by scale-out and rides to broker TP / REGIME_MAX_HOLD /
    structure_exit only. Scale-out itself (_scale_out_50pct) is not
    gated by this flag and continues to fire normally.
    """
    if _skip_legacy_helper_for_profile(st):
        return  # Phase 3 collision guard 5.2 — profile owns the runner
    # Kill-switch (2026-06-30). Read env at call-time so a flip takes
    # effect on the next tick without restart. Gate runs BEFORE the
    # mode/scaled_out checks so when ENABLED=1 the rest of the function
    # is byte-identical to the legacy path.
    _trail_enabled = (
        os.getenv("TREND_RUNNER_TRAIL_ENABLED",
                  TREND_RUNNER_TRAIL_ENABLED_DEFAULT)
        or TREND_RUNNER_TRAIL_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")
    if not _trail_enabled:
        mode = str(st.get("mode") or "").upper()
        if mode in _TREND_RUNNER_STYLE_MODES and meta.get("scaled_out"):
            if not meta.get("_trend_trail_off_logged"):
                deal_id = st.get("dealId") or st.get("deal_id") or pos_key
                logger.info(
                    "[TM] TREND/EMA_PULLBACK runner trail OFF (flag) — "
                    "riding BE+TP+time-stop, deal=%s mode=%s",
                    deal_id, mode,
                )
                meta["_trend_trail_off_logged"] = True
        return
    if not meta.get("scaled_out"):
        return
    mode = str(st.get("mode") or "").upper()
    if mode not in _TREND_RUNNER_STYLE_MODES:
        return

    # Compute the step that the current peak qualifies for. peak − offset
    # is the lock distance; the broker SL price = entry ± lock × ppp.
    triggers = TREND_TRAIL_STEP_TRIGGERS_PIPS
    qualifying_step = 0
    for i, trig in enumerate(triggers, start=1):
        if float(best_pnl_pips) >= trig:
            qualifying_step = i
    prior_step = int(meta.get("trend_trail_step") or 0)
    if qualifying_step <= prior_step:
        return  # no new step to commit (or below first trigger)

    # Compute lock distance for the new step: peak − offset (or stepped).
    # We use the step's trigger value (15/25/40) as the "peak floor" to keep
    # locks predictable; lock = trigger − offset.
    trigger_for_step = triggers[qualifying_step - 1]
    lock_pips = max(0.0, trigger_for_step - TREND_TRAIL_OFFSET_PIPS)

    entry = _safe_float(st.get("entry_price"), None)
    direction = str(st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return
    if direction == "BUY":
        new_sl_price = float(entry) + lock_pips * float(ppp)
    else:
        new_sl_price = float(entry) - lock_pips * float(ppp)

    tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
    if direction == "BUY":
        runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
    else:
        runner_tp_price = float(entry) - float(tp_pips) * float(ppp)

    try:
        _amend_broker_sl(pos_key, new_sl_price=new_sl_price,
                         current_tp_price=runner_tp_price)
        meta["trend_trail_step"] = qualifying_step
        meta["trend_trail_lock_pips"] = lock_pips
        logger.info(
            "[TREND_TRAIL] %s step=%d peak=%.1fp lock=+%.1fp new_sl=%.5f",
            epic, qualifying_step, best_pnl_pips, lock_pips, new_sl_price,
        )
    except Exception as exc:
        logger.warning(
            "[TREND_TRAIL] %s step=%d amend failed: %s",
            epic, qualifying_step, exc,
        )


def _apply_bb_bounce_runner_trail(epic: str, pos_key: str, st: Dict[str, Any],
                                  meta: Dict[str, Any], pair: str, ppp: float,
                                  best_pnl_pips: float) -> None:
    """Smooth peak-pivot trail for BB_BOUNCE runners post scale-out.

    Engages ONLY when:
        the per-leg kill-switch for st["mode"] is "1" (default: L="1",
            S="0" — see header comment for the full-window counterfactual
            that justifies the asymmetry), AND
        meta["scaled_out"] is True (partial banked, broker SL at entry), AND
        meta["be_amend_ok"] is True (BE amend confirmed; without it the trail
            would start ratcheting an un-known broker SL), AND
        st["mode"] in _BB_BOUNCE_TRAIL_MODES (BB_BOUNCE_L/S only — gbpusd_trend
            uses _apply_trend_runner_trail's stepped path).

    Lock rule: proposed_lock_pips = max(0, peak_pnl - OFFSET).
    Ratchets upward only via meta["bb_bounce_trail_lock_pips"]; never regresses.
    Floor is entry (BE), guaranteed by max(0, ...) — the trail can never amend
    SL below the BE move that scale-out installed.

    SL amend uses _amend_broker_sl, same primitive as scale-out's BE move,
    preserving the original broker TP at entry ± tp_pips × ppp.

    Per-leg kill-switch (2026-06-30): BB_BOUNCE_L_RUNNER_TRAIL_ENABLED
    (default "1") and BB_BOUNCE_S_RUNNER_TRAIL_ENABLED (default "0").
    When OFF for a leg, the trail does not run — the runner sits at the
    BE SL installed by scale-out and rides to broker TP / REGIME_MAX_HOLD
    / structure_exit only. Scale-out itself (_scale_out_50pct) is NOT
    gated by these flags and continues to fire normally for both legs.
    """
    if _skip_legacy_helper_for_profile(st):
        return  # Phase 3 collision guard 5.2 — profile owns the runner
    # Range-mode BB flip mode (2026-08-15): trail is DISABLED for any
    # position tagged range_mode_flip. Sole exits are BB_RANGE_TARGET,
    # BB_FLIP, broker stop, or NY_CLOSE. (BB_RANGE_TARGET added 2026-08-16
    # per operator: opposite-band touch = primary target; the flip is now
    # secondary and fires only if an opposite BB setup arrives before
    # the touch.)
    if meta.get("range_mode_flip"):
        return
    # Per-leg gate (2026-06-30). Determine which flag governs this trade
    # by mode; read env at call-time so a flip takes effect on the next
    # tick without restart. When the leg's flag is "1" the rest of the
    # function below is byte-identical to the legacy path (pre-363ee0c).
    mode = str(st.get("mode") or "").upper()
    if mode == "GBPUSD_BB_BOUNCE_L":
        _env_name = "BB_BOUNCE_L_RUNNER_TRAIL_ENABLED"
        _env_default = BB_BOUNCE_L_RUNNER_TRAIL_ENABLED_DEFAULT
        _leg_activate_env = "BB_BOUNCE_L_RUNNER_TRAIL_ACTIVATE_PIPS"
        _leg_offset_env = "BB_BOUNCE_L_RUNNER_TRAIL_OFFSET_PIPS"
    elif mode == "GBPUSD_BB_BOUNCE_S":
        _env_name = "BB_BOUNCE_S_RUNNER_TRAIL_ENABLED"
        _env_default = BB_BOUNCE_S_RUNNER_TRAIL_ENABLED_DEFAULT
        _leg_activate_env = "BB_BOUNCE_S_RUNNER_TRAIL_ACTIVATE_PIPS"
        _leg_offset_env = "BB_BOUNCE_S_RUNNER_TRAIL_OFFSET_PIPS"
    else:
        # Not a BB_BOUNCE mode — never trail here (matches the legacy
        # `mode not in _BB_BOUNCE_TRAIL_MODES` early-return).
        return
    _trail_enabled = (
        os.getenv(_env_name, _env_default) or _env_default
    ).strip().lower() in ("1", "true", "yes", "on")
    # Uniform kill-flag (2026-07-29): when the master rollout flag is off,
    # BB_BOUNCE_S reverts to its pre-uniform OFF regardless of any .env
    # override. BB_BOUNCE_L is unaffected — it was already ON at the
    # uniform 12/6 geometry pre-rollout.
    if mode == "GBPUSD_BB_BOUNCE_S" and not _uniform_trail_enabled():
        _trail_enabled = False
    if not _trail_enabled:
        if meta.get("scaled_out") and not meta.get("_bb_trail_off_logged"):
            deal_id = st.get("dealId") or st.get("deal_id") or pos_key
            logger.info(
                "[TM] BB_BOUNCE runner trail OFF (flag) — riding "
                "BE+TP+time-stop, deal=%s mode=%s flag=%s",
                deal_id, mode, _env_name,
            )
            meta["_bb_trail_off_logged"] = True
        return
    if not meta.get("scaled_out"):
        return
    if not meta.get("be_amend_ok"):
        return
    if mode not in _BB_BOUNCE_TRAIL_MODES:
        return

    # Per-leg activate/offset knobs (2026-07-01). Read env at call-time so
    # Johnny can tune L and S independently without restart. Each leg-
    # specific key falls back to the shared BB_BOUNCE_RUNNER_TRAIL_*
    # value, which itself defaults to 12/6. Semantics unchanged when no
    # leg-specific override is set — byte-identical to the pre-2026-07-01
    # path with the shared globals.
    try:
        _leg_activate = float(
            os.getenv(_leg_activate_env, "")
            or os.getenv("BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS", "")
            or BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS
        )
    except (TypeError, ValueError):
        _leg_activate = float(BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS)
    try:
        _leg_offset = float(
            os.getenv(_leg_offset_env, "")
            or os.getenv("BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS", "")
            or BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS
        )
    except (TypeError, ValueError):
        _leg_offset = float(BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS)

    _apply_peak_pivot_runner_trail_core(
        pos_key, st, meta, ppp, best_pnl_pips,
        activate_pips=_leg_activate,
        offset_pips=_leg_offset,
        lock_meta_key="bb_bounce_trail_lock_pips",
        log_prefix="BB_TRAIL",
    )


def _apply_peak_pivot_runner_trail_core(
    pos_key: str, st: Dict[str, Any], meta: Dict[str, Any],
    ppp: float, best_pnl_pips: float, *,
    activate_pips: float, offset_pips: float,
    lock_meta_key: str, log_prefix: str,
) -> None:
    """Shared peak-pivot ratchet primitive (BB_BOUNCE / EMA_PULLBACK).

    Arms once best_pnl_pips ≥ activate_pips, then proposes
    lock_pips = max(0, best_pnl_pips − offset_pips) and amends the broker
    SL to entry ± lock_pips × ppp. Ratchets upward only via
    meta[lock_meta_key]; monotonic — never regresses, never below entry
    (max(0, ...) is the BE floor). Preserves the runner's broker TP.

    Caller owns: enable flag, mode gate, scaled_out / be_amend_ok
    preconditions, and any "trail OFF" logging.
    """
    if float(best_pnl_pips) < float(activate_pips):
        return

    proposed_lock = max(0.0, float(best_pnl_pips) - float(offset_pips))
    prior_lock = float(meta.get(lock_meta_key) or 0.0)
    if proposed_lock <= prior_lock:
        return  # monotonic; nothing to commit

    entry = _safe_float(st.get("entry_price"), None)
    direction = str(st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return

    if direction == "BUY":
        new_sl_price = float(entry) + proposed_lock * float(ppp)
    else:
        new_sl_price = float(entry) - proposed_lock * float(ppp)

    tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
    if direction == "BUY":
        runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
    else:
        runner_tp_price = float(entry) - float(tp_pips) * float(ppp)

    try:
        ok = _amend_broker_sl(pos_key, new_sl_price=new_sl_price,
                              current_tp_price=runner_tp_price)
    except Exception as exc:
        logger.warning(
            "[%s] %s amend raised: %s — peak=%.1fp proposed_lock=+%.1fp",
            log_prefix, pos_key, exc, best_pnl_pips, proposed_lock,
        )
        return

    if ok:
        meta[lock_meta_key] = proposed_lock
        logger.info(
            "[%s] %s mode=%s peak=%.1fp lock=+%.1fp prior_lock=+%.1fp "
            "new_sl=%.5f entry=%.5f ppp=%.3f",
            log_prefix, pos_key, str(st.get("mode") or ""),
            best_pnl_pips, proposed_lock, prior_lock,
            new_sl_price, float(entry), float(ppp),
        )
    elif not _sl_amend_was_suppressed(pos_key):
        logger.warning(
            "[%s] %s amend NOT confirmed — peak=%.1fp proposed_lock=+%.1fp "
            "(prior_lock unchanged at +%.1fp; will retry on next ratchet step)",
            log_prefix, pos_key, best_pnl_pips, proposed_lock, prior_lock,
        )


def _apply_ema_pullback_runner_trail(epic: str, pos_key: str,
                                     st: Dict[str, Any],
                                     meta: Dict[str, Any], pair: str,
                                     ppp: float,
                                     best_pnl_pips: float) -> None:
    """Peak-pivot runner trail for EMA_PULLBACK (2026-07-20).

    Reuses _apply_peak_pivot_runner_trail_core — same SL primitive as
    BB_BOUNCE, monotonic, BE-floored. Defaults 20/8 (activate/offset).

    Engages ONLY when:
        EMA_PULLBACK_RUNNER_TRAIL_ENABLED is "1" (default; kill-switch), AND
        meta["scaled_out"] is True (partial banked, broker SL at entry), AND
        meta["be_amend_ok"] is True (BE amend confirmed; without it the
            trail would ratchet an un-known broker SL), AND
        st["mode"] in _EMA_PULLBACK_TRAIL_MODES (EMA_PULLBACK_L/S only).

    When OFF: no-op — runner sits at the BE installed by scale-out and
    rides broker TP / REGIME_MAX_HOLD / structure_exit only. Byte-
    identical to pre-2026-07-20 behaviour (the stepped trend trail was
    off by default and never engaged in practice for EMA_PULLBACK).

    Composition with the exit stack:
        - Above BE: proposed_lock is max(0, peak − OFFSET) so the amended
          SL is always ≥ entry (BUY) / ≤ entry (SELL). The BE installed
          by scale-out is the floor; the trail can only move SL further
          into profit.
        - Structure_exit: skipped for scaled+be_amend_ok runners at the
          general call site (trade_manager.py:2940-2946); once the trail
          arms, the broker SL is authoritative.
        - REGIME_MAX_HOLD: exempt for scaled runners
          (REGIME_MAX_HOLD_SCALED_OUT_EXEMPT_ENABLED=1 default).
        - Broker SL amend, not manager market-close — matches BB_BOUNCE.
    """
    if _skip_legacy_helper_for_profile(st):
        return  # Phase 3 collision guard 5.2 — profile owns the runner
    _trail_enabled = (
        os.getenv("EMA_PULLBACK_RUNNER_TRAIL_ENABLED",
                  EMA_PULLBACK_RUNNER_TRAIL_ENABLED_DEFAULT)
        or EMA_PULLBACK_RUNNER_TRAIL_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")
    mode = str(st.get("mode") or "").upper()
    if not _trail_enabled:
        if mode in _EMA_PULLBACK_TRAIL_MODES and meta.get("scaled_out"):
            if not meta.get("_ema_pb_trail_off_logged"):
                deal_id = st.get("dealId") or st.get("deal_id") or pos_key
                logger.info(
                    "[TM] EMA_PULLBACK runner trail OFF (flag) — riding "
                    "BE+TP+time-stop, deal=%s mode=%s",
                    deal_id, mode,
                )
                meta["_ema_pb_trail_off_logged"] = True
        return
    if not meta.get("scaled_out"):
        return
    if not meta.get("be_amend_ok"):
        return
    if mode not in _EMA_PULLBACK_TRAIL_MODES:
        return

    # Uniform kill-flag (2026-07-29): master flag forces the data-sized
    # 12/6 geometry across fade-type strategies. When master is off, revert
    # to pre-2026-07-29 code defaults (20/8) HARDCODED — the .env override
    # is intentionally NOT honoured under revert so the kill-flag is a
    # true one-flip revert regardless of .env state (which will still
    # carry the uniform 12/6 values as documentation).
    if _uniform_trail_enabled():
        _activate = 12.0
        _offset = 6.0
    else:
        _activate = 20.0   # pre-uniform default; hardcoded for revert-safety
        _offset = 8.0      # pre-uniform default; hardcoded for revert-safety

    _apply_peak_pivot_runner_trail_core(
        pos_key, st, meta, ppp, best_pnl_pips,
        activate_pips=_activate,
        offset_pips=_offset,
        lock_meta_key="ema_pullback_trail_lock_pips",
        log_prefix="EMA_PB_TRAIL",
    )


def _apply_bb_bounce_post_scale_floor(epic: str, pos_key: str,
                                      st: Dict[str, Any],
                                      meta: Dict[str, Any], pair: str,
                                      ppp: float,
                                      best_pnl_pips: float) -> None:
    """Post-scale runner-stop FLOOR for BB_BOUNCE (both L and S).

    Rule: once meta["scaled_out"] is True AND peak MFE ≥ ARM_PIPS (10p),
    the broker SL is FLOORED at entry ± FLOOR_PIPS × ppp (default +5p).
    Composed with the L trail via the shared meta["bb_bounce_trail_lock_pips"]
    monotonic marker — writes are guarded by proposed > prior_lock, so this
    is a pure ratchet-up: new_stop = max(existing_stop, floor). Never
    reduces an existing stop.

    On L: coexists with _apply_bb_bounce_runner_trail. Both write the same
    lock variable, both only ratchet up, so whichever proposes a higher
    lock wins. Once the trail's lock (peak−6) exceeds the floor (5), the
    trail runs the show; the floor stays dormant. The floor only "wins"
    while peak sits in the 10–11p band before the trail activates at +12.

    On S: the trail is OFF by default, so the floor is the sole writer of
    the lock variable — the runner's only post-scale protection above BE.

    Kill-switch: BB_BOUNCE_POST_SCALE_FLOOR_ENABLED (default "1"). When
    "0", this function no-ops and behaviour reverts to the pre-existing
    stop path (BE from scale-out + L trail on L, BE only on S).
    """
    if _skip_legacy_helper_for_profile(st):
        return  # Phase 3 collision guard 5.2 — profile owns the runner
    # Range-mode BB flip mode (2026-08-15): floor is DISABLED for any
    # position tagged range_mode_flip.
    if meta.get("range_mode_flip"):
        return
    _floor_enabled = (
        os.getenv("BB_BOUNCE_POST_SCALE_FLOOR_ENABLED",
                  BB_BOUNCE_POST_SCALE_FLOOR_ENABLED_DEFAULT)
        or BB_BOUNCE_POST_SCALE_FLOOR_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")
    if not _floor_enabled:
        return
    if not meta.get("scaled_out"):
        return
    if not meta.get("be_amend_ok"):
        return
    mode = str(st.get("mode") or "").upper()
    # Uniform kill-flag (2026-07-29): extend the floor to EMA_PULLBACK_L/S
    # and NEWS_STRATEGY_CONT modes when master is on. Reverts to
    # BB_BOUNCE_L/S only when master is off. Same arm=10p/lock=5p geometry
    # for all covered modes. The floor writes meta["bb_bounce_trail_lock_
    # pips"] and meta["bb_bounce_post_scale_floor_applied"] regardless of
    # mode — the lock key is shared with the L trail for max()-composition
    # on BB, and is independent from EMA_PB's/NEWS_CONT's per-strategy lock
    # keys (their trail dispatchers write their own keys; broker SL is
    # authoritative and both writers are monotonic-up-only so they compose
    # safely at the broker even without sharing the meta key).
    _effective_floor_modes = _BB_BOUNCE_TRAIL_MODES
    if _uniform_trail_enabled():
        _effective_floor_modes = (
            _BB_BOUNCE_TRAIL_MODES
            | _EMA_PULLBACK_TRAIL_MODES
            | _NEWS_STRATEGY_CONT_TRAIL_MODES
        )
    if mode not in _effective_floor_modes:
        return
    if float(best_pnl_pips) < BB_BOUNCE_POST_SCALE_FLOOR_ARM_PIPS:
        return

    proposed_lock = float(BB_BOUNCE_POST_SCALE_FLOOR_PIPS)
    prior_lock = float(meta.get("bb_bounce_trail_lock_pips") or 0.0)
    if proposed_lock <= prior_lock:
        # Ratchet-up-only: existing stop already at or above the floor.
        # This is how the floor composes with the L trail — once the
        # trail has ratcheted past +5p, this branch returns cleanly.
        return

    entry = _safe_float(st.get("entry_price"), None)
    direction = str(st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return

    if direction == "BUY":
        new_sl_price = float(entry) + proposed_lock * float(ppp)
    else:
        new_sl_price = float(entry) - proposed_lock * float(ppp)

    tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
    if direction == "BUY":
        runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
    else:
        runner_tp_price = float(entry) - float(tp_pips) * float(ppp)

    try:
        ok = _amend_broker_sl(pos_key, new_sl_price=new_sl_price,
                              current_tp_price=runner_tp_price)
    except Exception as exc:
        logger.warning(
            "[BB_FLOOR] %s amend raised: %s — peak=%.1fp floor=+%.1fp",
            pos_key, exc, best_pnl_pips, proposed_lock,
        )
        return

    if ok:
        meta["bb_bounce_trail_lock_pips"] = proposed_lock
        # State flag read by _detect_ig_close_reason to distinguish a
        # genuine post-scale BE stop from a post-scale FLOOR stop. Once
        # the floor has moved the SL above entry, any subsequent SL hit
        # is a FLOOR_STOP_POST_SCALEOUT — not a break-even close.
        meta["bb_bounce_post_scale_floor_applied"] = True
        logger.info(
            "[BB_FLOOR] %s mode=%s peak=%.1fp floor=+%.1fp prior_lock=+%.1fp "
            "new_sl=%.5f entry=%.5f ppp=%.3f",
            pos_key, mode, best_pnl_pips, proposed_lock, prior_lock,
            new_sl_price, float(entry), float(ppp),
        )
    elif not _sl_amend_was_suppressed(pos_key):
        logger.warning(
            "[BB_FLOOR] %s amend NOT confirmed — peak=%.1fp floor=+%.1fp "
            "(prior_lock unchanged at +%.1fp; will retry next tick)",
            pos_key, best_pnl_pips, proposed_lock, prior_lock,
        )


def _apply_range_scalp_floor(epic: str, pos_key: str,
                             st: Dict[str, Any],
                             range_meta: Dict[str, Any],
                             ppp: float,
                             best_pnl_pips: float) -> None:
    """Range-scalp profit floor (Phase 2).

    Rule: once peak MFE ≥ RANGE_SCALP_FLOOR_TRIGGER_PIPS (default +8p),
    the broker SL is FLOORED at entry ± RANGE_SCALP_FLOOR_LOCK_PIPS × ppp
    in the position's favour. Monotonic-up-only via the
    range_scalp_floor_lock_pips marker on the range-scalp meta — writes
    are guarded by proposed > prior_lock so this can never move the stop
    against the position. Applies regardless of the effective_regime.

    Mirrors _apply_bb_bounce_post_scale_floor (line 865). Same shape,
    same broker call (_amend_broker_sl), same never-loosens invariant.

    Kill-switch: RANGE_SCALP_FLOOR_ENABLED (default "1").
    """
    _floor_enabled = (
        os.getenv("RANGE_SCALP_FLOOR_ENABLED",
                  RANGE_SCALP_FLOOR_ENABLED_DEFAULT)
        or RANGE_SCALP_FLOOR_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")
    if not _floor_enabled:
        return
    if float(best_pnl_pips) < RANGE_SCALP_FLOOR_TRIGGER_PIPS:
        return

    proposed_lock = float(RANGE_SCALP_FLOOR_LOCK_PIPS)
    prior_lock = float(range_meta.get("range_scalp_floor_lock_pips") or 0.0)
    if proposed_lock <= prior_lock:
        return  # Ratchet-up-only: existing lock already at or above floor.

    entry = _safe_float(st.get("entry_price"), None)
    if entry is None:
        entry = _safe_float(range_meta.get("entry_price"), None)
    direction = str(range_meta.get("direction") or st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return

    if direction == "BUY":
        new_sl_price = float(entry) + proposed_lock * float(ppp)
    else:
        new_sl_price = float(entry) - proposed_lock * float(ppp)

    tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
    if direction == "BUY":
        runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
    else:
        runner_tp_price = float(entry) - float(tp_pips) * float(ppp)

    try:
        ok = _amend_broker_sl(pos_key, new_sl_price=new_sl_price,
                              current_tp_price=runner_tp_price)
    except Exception as exc:
        logger.warning(
            "[RANGE_SCALP_FLOOR] %s amend raised: %s — peak=%.1fp floor=+%.1fp",
            pos_key, exc, best_pnl_pips, proposed_lock,
        )
        return

    if ok:
        range_meta["range_scalp_floor_lock_pips"] = proposed_lock
        logger.info(
            "[RANGE_SCALP_FLOOR] %s dir=%s peak=%.1fp floor=+%.1fp "
            "prior_lock=+%.1fp new_sl=%.5f entry=%.5f ppp=%.3f",
            pos_key, direction, best_pnl_pips, proposed_lock, prior_lock,
            new_sl_price, float(entry), float(ppp),
        )
    elif not _sl_amend_was_suppressed(pos_key):
        logger.warning(
            "[RANGE_SCALP_FLOOR] %s amend NOT confirmed — peak=%.1fp "
            "floor=+%.1fp (prior_lock unchanged at +%.1fp; retry next tick)",
            pos_key, best_pnl_pips, proposed_lock, prior_lock,
        )


def _apply_structure_break_runner_trail(epic: str, pos_key: str,
                                        st: Dict[str, Any],
                                        meta: Dict[str, Any], pair: str,
                                        ppp: float,
                                        best_pnl_pips: float) -> None:
    """Continuous peak-pivot trail for STRUCTURE_BREAK runners post scale-out.

    Engages ONLY when:
        meta["scaled_out"] is True   (partial banked, broker SL at entry), AND
        meta["be_amend_ok"] is True  (BE move confirmed by broker), AND
        st["mode"] in _STRUCTURE_BREAK_TRAIL_MODES.

    Lock rule (continuous, no step triggers):
        proposed_lock_pips = max(0.0, peak_pnl - OFFSET)
        new_sl_price       = entry ± proposed_lock_pips × ppp

    Both `peak_pnl` and the lock are computed off the ORIGINAL ENTRY price
    (best_pnl_pips is peak MFE in pips since entry; the SL price is
    entry ± lock × ppp). Monotonic upward — never regresses. Floor at entry
    (BE) is guaranteed by the max(0, ...) clamp. Until peak ≥ OFFSET the
    proposed lock is 0 and the SL stays at BE.

    SL amend uses _amend_broker_sl, the same primitive as scale-out's BE
    move, preserving the original broker TP (80p default per
    STRUCTURE_BREAK_RUNNER_TP_PIPS).

    Kill-switched via STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED (default "0",
    OFF). When OFF, the trail does not run — the runner sits at the BE
    SL installed by scale-out and rides to broker TP / REGIME_MAX_HOLD /
    structure_exit only. Scale-out itself (_scale_out_50pct) is not
    gated by this flag and continues to fire normally.
    """
    if _skip_legacy_helper_for_profile(st):
        return  # Phase 3 collision guard 5.2 — profile owns the runner
    # Kill-switch (2026-06-30). Read env at call-time so a flip takes
    # effect on the next tick without restart. Gate runs BEFORE the
    # mode check so when ENABLED=1 the rest of the function is byte-
    # identical to the legacy path.
    _trail_enabled = (
        os.getenv("STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED",
                  STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED_DEFAULT)
        or STRUCTURE_BREAK_RUNNER_TRAIL_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")
    if not _trail_enabled:
        mode = str(st.get("mode") or "").upper()
        if mode in _STRUCTURE_BREAK_TRAIL_MODES and meta.get("scaled_out"):
            if not meta.get("_sb_trail_off_logged"):
                deal_id = st.get("dealId") or st.get("deal_id") or pos_key
                logger.info(
                    "[TM] SB runner trail OFF (flag) — riding BE+TP+time-stop, "
                    "deal=%s mode=%s",
                    deal_id, mode,
                )
                meta["_sb_trail_off_logged"] = True
        return
    if not meta.get("scaled_out"):
        return
    if not meta.get("be_amend_ok"):
        return
    mode = str(st.get("mode") or "").upper()
    if mode not in _STRUCTURE_BREAK_TRAIL_MODES:
        return

    proposed_lock = max(0.0,
                        float(best_pnl_pips) - STRUCTURE_BREAK_RUNNER_TRAIL_OFFSET_PIPS)
    prior_lock = float(meta.get("structure_break_trail_lock_pips") or 0.0)
    if proposed_lock <= prior_lock:
        return  # monotonic; nothing to commit

    entry = _safe_float(st.get("entry_price"), None)
    direction = str(st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return

    if direction == "BUY":
        new_sl_price = float(entry) + proposed_lock * float(ppp)
    else:
        new_sl_price = float(entry) - proposed_lock * float(ppp)

    tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
    if direction == "BUY":
        runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
    else:
        runner_tp_price = float(entry) - float(tp_pips) * float(ppp)

    try:
        ok = _amend_broker_sl(pos_key, new_sl_price=new_sl_price,
                              current_tp_price=runner_tp_price)
    except Exception as exc:
        logger.warning(
            "[SB_TRAIL] %s amend raised: %s — peak=%.1fp proposed_lock=+%.1fp",
            pos_key, exc, best_pnl_pips, proposed_lock,
        )
        return

    if ok:
        meta["structure_break_trail_lock_pips"] = proposed_lock
        logger.info(
            "[SB_TRAIL] %s mode=%s peak=%.1fp lock=+%.1fp prior_lock=+%.1fp "
            "new_sl=%.5f entry=%.5f ppp=%.3f",
            pos_key, mode, best_pnl_pips, proposed_lock, prior_lock,
            new_sl_price, float(entry), float(ppp),
        )
    elif not _sl_amend_was_suppressed(pos_key):
        logger.warning(
            "[SB_TRAIL] %s amend NOT confirmed — peak=%.1fp proposed_lock=+%.1fp "
            "(prior_lock unchanged at +%.1fp; will retry next bar)",
            pos_key, best_pnl_pips, proposed_lock, prior_lock,
        )


def _apply_news_cont_runner_trail(epic: str, pos_key: str,
                                   st: Dict[str, Any],
                                   meta: Dict[str, Any], pair: str,
                                   ppp: float,
                                   best_pnl_pips: float) -> None:
    """Peak-pivot runner trail for NEWS_STRATEGY_CONT (2026-07-03).

    Engages ONLY when:
        NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED is "1" (default), AND
        meta["scaled_out"] is True (partial banked, broker SL at entry), AND
        meta["be_amend_ok"] is True (BE amend confirmed by broker), AND
        st["mode"] in _NEWS_STRATEGY_CONT_TRAIL_MODES (NEWS_STRATEGY_CONT only —
            NEWS_STRATEGY_FADE is the losing leg, benched, and untouched).

    Lock rule:
        peak_pnl < ACTIVATE (default 20p)   → no-op (arms nothing).
        peak_pnl ≥ ACTIVATE                 → proposed_lock =
                                              max(0, peak_pnl - OFFSET (default 12p))
        Ratchets upward only via meta["news_cont_trail_lock_pips"];
        never regresses. Floor at entry (BE) is guaranteed by max(0, ...).

    SL amend uses _amend_broker_sl, same primitive as scale-out's BE
    move. Preserves the runner's broker TP at whatever news_strategy.py
    set at fire time — with the flag ON that is the fade ceiling
    (fade_caps.max_tp_pips, default 50p); with the flag OFF the TP is
    the spike-geometry value and this function no-ops anyway.

    Telemetry: first-engage stamps
        meta["news_cont_trail_activation_pips"]         (ACTIVATE at first ratchet)
        meta["news_cont_trail_offset_pips"]             (OFFSET at first ratchet)
        meta["news_cont_trail_peak_at_activation_pips"] (peak at first ratchet)
    and every ratchet emits [NEWS_TRAIL] log lines. The OUTCOME JOIN can
    read the meta stamps to distinguish trail_stop vs tp_ceiling vs BE.
    """
    if _skip_legacy_helper_for_profile(st):
        return  # Phase 3 collision guard 5.2 — profile owns the runner
    _trail_enabled = (
        os.getenv("NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED",
                  NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED_DEFAULT)
        or NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")
    if not _trail_enabled:
        return
    if not meta.get("scaled_out"):
        return
    if not meta.get("be_amend_ok"):
        return
    mode = str(st.get("mode") or "").upper()
    if mode not in _NEWS_STRATEGY_CONT_TRAIL_MODES:
        return

    # Uniform kill-flag (2026-07-29): master flag forces 12/6 across
    # fade-type strategies. When master is off, revert to pre-2026-07-29
    # code defaults (20/12) HARDCODED — .env override intentionally NOT
    # honoured under revert so the kill-flag is a true one-flip revert
    # regardless of .env state.
    if _uniform_trail_enabled():
        _activate = 12.0
        _offset = 6.0
    else:
        _activate = 20.0   # pre-uniform default; hardcoded for revert-safety
        _offset = 12.0     # pre-uniform default; hardcoded for revert-safety

    if float(best_pnl_pips) < _activate:
        return

    proposed_lock = max(0.0, float(best_pnl_pips) - _offset)
    prior_lock = float(meta.get("news_cont_trail_lock_pips") or 0.0)
    if proposed_lock <= prior_lock:
        return

    entry = _safe_float(st.get("entry_price"), None)
    direction = str(st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return

    if direction == "BUY":
        new_sl_price = float(entry) + proposed_lock * float(ppp)
    else:
        new_sl_price = float(entry) - proposed_lock * float(ppp)

    tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
    if direction == "BUY":
        runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
    else:
        runner_tp_price = float(entry) - float(tp_pips) * float(ppp)

    try:
        ok = _amend_broker_sl(pos_key, new_sl_price=new_sl_price,
                              current_tp_price=runner_tp_price)
    except Exception as exc:
        logger.warning(
            "[NEWS_TRAIL] %s amend raised: %s — peak=%.1fp proposed_lock=+%.1fp",
            pos_key, exc, best_pnl_pips, proposed_lock,
        )
        return

    if ok:
        meta["news_cont_trail_lock_pips"] = proposed_lock
        if meta.get("news_cont_trail_activation_pips") is None:
            meta["news_cont_trail_activation_pips"] = float(_activate)
            meta["news_cont_trail_offset_pips"] = float(_offset)
            meta["news_cont_trail_peak_at_activation_pips"] = float(best_pnl_pips)
        logger.info(
            "[NEWS_TRAIL] %s mode=%s peak=%.1fp lock=+%.1fp prior_lock=+%.1fp "
            "new_sl=%.5f entry=%.5f ppp=%.3f (activate=%.1f offset=%.1f)",
            pos_key, mode, best_pnl_pips, proposed_lock, prior_lock,
            new_sl_price, float(entry), float(ppp), _activate, _offset,
        )
    elif not _sl_amend_was_suppressed(pos_key):
        logger.warning(
            "[NEWS_TRAIL] %s amend NOT confirmed — peak=%.1fp proposed_lock=+%.1fp "
            "(prior_lock unchanged at +%.1fp; will retry on next ratchet step)",
            pos_key, best_pnl_pips, proposed_lock, prior_lock,
        )


def _apply_strong_profile_runner_trail(epic: str, pos_key: str,
                                       st: Dict[str, Any],
                                       meta: Dict[str, Any], pair: str,
                                       ppp: float,
                                       best_pnl_pips: float) -> None:
    """STRONG profile runner trail (Phase 3, 2026-07-09).

    Cloned from _apply_structure_break_runner_trail (recon Q3b) —
    continuous peak-pivot with the same monotonic guard and the same
    _amend_broker_sl broker call. Own env knobs
    (REGIME_MGMT_STRONG_TRAIL_*) and own lock key
    (`meta["profile_strong_trail_lock_pips"]`) so it composes cleanly
    with the legacy per-strategy trails when both are wired for the
    same position (never the case under the profile dispatch — this
    helper only runs when the dispatch has already routed away from
    the legacy multiplex).

    Engages ONLY when:
        REGIME_MGMT_STRONG_TRAIL_ENABLED is "1" (default), AND
        meta["scaled_out"] is True (profile scale + BE has completed), AND
        meta["be_amend_ok"] is True.

    Mode-agnostic — the profile has already selected the trade at fire;
    this helper accepts any mode. The mode filter is the profile
    dispatcher, not the trail body.
    """
    _trail_enabled = (
        os.getenv("REGIME_MGMT_STRONG_TRAIL_ENABLED",
                  REGIME_MGMT_STRONG_TRAIL_ENABLED_DEFAULT)
        or REGIME_MGMT_STRONG_TRAIL_ENABLED_DEFAULT
    ).strip().lower() in ("1", "true", "yes", "on")
    if not _trail_enabled:
        return
    if not meta.get("scaled_out"):
        return
    if not meta.get("be_amend_ok"):
        return

    proposed_lock = max(
        0.0,
        float(best_pnl_pips) - REGIME_MGMT_STRONG_TRAIL_OFFSET_PIPS,
    )
    prior_lock = float(meta.get("profile_strong_trail_lock_pips") or 0.0)
    if proposed_lock <= prior_lock:
        return  # monotonic; never against the position

    entry = _safe_float(st.get("entry_price"), None)
    direction = str(st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return

    if direction == "BUY":
        new_sl_price = float(entry) + proposed_lock * float(ppp)
    else:
        new_sl_price = float(entry) - proposed_lock * float(ppp)

    tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
    if direction == "BUY":
        runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
    else:
        runner_tp_price = float(entry) - float(tp_pips) * float(ppp)

    try:
        ok = _amend_broker_sl(pos_key, new_sl_price=new_sl_price,
                              current_tp_price=runner_tp_price)
    except Exception as exc:
        logger.warning(
            "[PROFILE:STRONG] %s trail amend raised: %s — peak=%.1fp "
            "proposed_lock=+%.1fp",
            pos_key, exc, best_pnl_pips, proposed_lock,
        )
        return

    profile_id = str(st.get("profile_id") or "")
    if ok:
        meta["profile_strong_trail_lock_pips"] = proposed_lock
        logger.info(
            "[PROFILE:STRONG] %s profile=%s peak=%.1fp lock=+%.1fp "
            "prior_lock=+%.1fp new_sl=%.5f entry=%.5f ppp=%.3f",
            pos_key, profile_id, best_pnl_pips, proposed_lock, prior_lock,
            new_sl_price, float(entry), float(ppp),
        )
    elif not _sl_amend_was_suppressed(pos_key):
        logger.warning(
            "[PROFILE:STRONG] %s trail amend NOT confirmed — peak=%.1fp "
            "proposed_lock=+%.1fp (prior_lock unchanged at +%.1fp; retry next tick)",
            pos_key, best_pnl_pips, proposed_lock, prior_lock,
        )


def _apply_forming_profile_tp_ladder(epic: str, pos_key: str,
                                     st: Dict[str, Any],
                                     meta: Dict[str, Any], pair: str,
                                     ppp: float,
                                     best_pnl_pips: float) -> None:
    """FORMING profile runner — broker TP climbs through the fixed ladder.

    Post-scale (meta["scaled_out"]=True + be_amend_ok=True):
      - Initialize the broker LIMIT at REGIME_MGMT_LADDER_PIPS[0].
      - When peak MFE reaches the current rung, advance to the next rung
        and amend the broker LIMIT upward via _amend_broker_sl (its
        current_tp_price parameter — recon Q3 confirmed the primitive
        handles both SL and TP atomically).
      - SL stays at BE for the whole life — the ladder is the exit;
        no trail on FORMING runners.

    Monotonic TP climb — the rung index only advances forward, mirroring
    the never-loosens invariant of the SL floors. Broker LIMIT is never
    amended downward.

    Ladder defaults REGIME_MGMT_LADDER_PIPS=30,50,80 match
    select_tp_levels's fallback ladder so the numbers aren't novel.
    """
    if not meta.get("scaled_out"):
        return
    if not meta.get("be_amend_ok"):
        return
    rungs = REGIME_MGMT_LADDER_PIPS
    if not rungs:
        return

    entry = _safe_float(st.get("entry_price"), None)
    direction = str(st.get("direction") or "").upper()
    if entry is None or direction not in ("BUY", "SELL"):
        return

    be_sl_price = float(entry)  # SL pinned at BE for FORMING

    def _price_at(pips: float) -> float:
        if direction == "BUY":
            return float(entry) + float(pips) * float(ppp)
        return float(entry) - float(pips) * float(ppp)

    cur_idx = int(meta.get("profile_forming_rung_idx", -1))

    # Initialization: first tick post-scale amends TP to rung 0.
    if cur_idx < 0:
        rung0 = float(rungs[0])
        try:
            ok = _amend_broker_sl(pos_key, new_sl_price=be_sl_price,
                                  current_tp_price=_price_at(rung0))
        except Exception as exc:
            logger.warning(
                "[PROFILE:FORMING] %s ladder init amend raised: %s",
                pos_key, exc,
            )
            return
        if ok:
            meta["profile_forming_rung_idx"] = 0
            st["tp"] = rung0
            logger.info(
                "[PROFILE:FORMING] %s ladder init: rung0=+%.1fp entry=%.5f "
                "tp_price=%.5f (rungs=%s)",
                pos_key, rung0, float(entry), _price_at(rung0),
                ",".join(f"{r:g}" for r in rungs),
            )
        elif not _sl_amend_was_suppressed(pos_key):
            logger.warning(
                "[PROFILE:FORMING] %s ladder init NOT confirmed — "
                "will retry next tick", pos_key,
            )
        return

    # Already initialized; clamp defensively if a stale meta points
    # beyond the current rung tuple (config change during a live trade).
    if cur_idx >= len(rungs) - 1:
        return

    cur_rung = float(rungs[cur_idx])
    if float(best_pnl_pips) < cur_rung:
        return  # not yet at the rung threshold

    next_idx = cur_idx + 1
    next_rung = float(rungs[next_idx])
    try:
        ok = _amend_broker_sl(pos_key, new_sl_price=be_sl_price,
                              current_tp_price=_price_at(next_rung))
    except Exception as exc:
        logger.warning(
            "[PROFILE:FORMING] %s rung climb %d→%d amend raised: %s",
            pos_key, cur_idx, next_idx, exc,
        )
        return
    if ok:
        meta["profile_forming_rung_idx"] = next_idx
        st["tp"] = next_rung
        logger.info(
            "[PROFILE:FORMING] %s rung climb %d→%d peak=%.1fp "
            "prev_rung=+%.1fp new_rung=+%.1fp tp_price=%.5f",
            pos_key, cur_idx, next_idx, best_pnl_pips, cur_rung, next_rung,
            _price_at(next_rung),
        )
    elif not _sl_amend_was_suppressed(pos_key):
        logger.warning(
            "[PROFILE:FORMING] %s rung climb %d→%d NOT confirmed — "
            "will retry next tick", pos_key, cur_idx, next_idx,
        )


def _dispatch_profile_management(epic: str, pos_key: str,
                                 st: Dict[str, Any],
                                 meta: Dict[str, Any], pair: str,
                                 ppp: float,
                                 best_pnl_pips: float) -> bool:
    """Route open-position management to the profile-specific manager
    for STRONG / FORMING trades. Returns True when the profile owns
    this tick (caller must skip the legacy multiplex); False when the
    legacy path should run.

    RANGE and LEGACY profiles ALWAYS return False so the range-scalp
    path and legacy per-strategy trails run unchanged.

    Order inside the profile manager:
      1. Scale-out at +REGIME_MGMT_SCALE_TRIGGER_PIPS (default 8p) via
         _scale_out_50pct — shares meta["scaled_out"] with the universal
         path so exactly one scale ever fires per position (recon 5.1).
      2. Runner:
           STRONG  → _apply_strong_profile_runner_trail (peak-pivot SL)
           FORMING → _apply_forming_profile_tp_ladder (broker-TP climb)
                     [Phase 3 C2 — introduced in the next commit]
    """
    if not _REGIME_MGMT_ENABLED_TM:
        return False
    profile_id = str(st.get("profile_id") or "").upper()
    if profile_id not in _PROFILE_MANAGED:
        return False

    # Profile-scoped scale-out: same primitive as the universal path,
    # sharing meta["scaled_out"] so no double scale is possible. The
    # universal +8p path at :3604 is exempted for profile-managed
    # trades in the C3 collision guards commit.
    if not meta.get("scaled_out"):
        if float(best_pnl_pips) >= REGIME_MGMT_SCALE_TRIGGER_PIPS:
            try:
                _scale_out_50pct(pos_key, pair, ppp, meta)
                logger.info(
                    "[PROFILE:%s] %s scale-out fired @ +%.1fp "
                    "(REGIME_MGMT_SCALE_TRIGGER_PIPS=%.1f)",
                    profile_id, pos_key, best_pnl_pips,
                    REGIME_MGMT_SCALE_TRIGGER_PIPS,
                )
            except Exception as _sc_exc:
                logger.warning(
                    "[PROFILE:%s] %s scale-out failed: %s",
                    profile_id, pos_key, _sc_exc,
                )
        # Regardless of scale outcome this tick: caller should skip
        # the legacy multiplex — profile owns the position.
        return True

    # Post-scale runner dispatch.
    try:
        if profile_id == "STRONG":
            _apply_strong_profile_runner_trail(
                epic, pos_key, st, meta, pair, ppp, best_pnl_pips,
            )
        elif profile_id == "FORMING":
            _apply_forming_profile_tp_ladder(
                epic, pos_key, st, meta, pair, ppp, best_pnl_pips,
            )
    except Exception as _pr_exc:
        logger.warning(
            "[PROFILE:%s] %s runner dispatch raised: %s",
            profile_id, pos_key, _pr_exc,
        )
    return True


def _scale_out_50pct(pos_key: str, pair: str, ppp: float, meta: Dict[str, Any]) -> None:
    """Fire the +10p / 50% scale-out:
      1) close 50% of the deal at IG via partial-close API (bypasses
         close_trade so _on_trade_close does NOT fire and EPIC_STATE
         is not reset — the runner remains).
      2) move the runner's broker SL to entry (BE), preserve original TP.
      3) update EPIC_STATE: size /= 2, partial_bank_pips, scaled_out=True.
      4) update _PROFIT_MGMT_BY_EPIC[epic]["scaled_out"]=True so this
         dispatcher does not re-arm on the next tick.
      5) emit signal_logger.log_partial so the open record records the
         partial bank — _on_trade_close later adds the runner outcome.

    Defensive — all failures log + return early; nothing raises.
    """
    try:
        st = _state_for_epic(pos_key)
        if not st.get("active"):
            return
        if st.get("scaled_out"):
            return  # belt-and-braces; the meta flag is the primary guard
        deal_id = st.get("dealId") or st.get("deal_id")
        direction = str(st.get("direction") or "").upper()
        entry = _safe_float(st.get("entry_price"))
        cur_size = _safe_float(st.get("size"))
        if not deal_id or direction not in ("BUY", "SELL") or entry is None or entry <= 0:
            logger.warning(
                "[SCALE_OUT] skip %s — missing context "
                "(deal_id=%s dir=%s entry=%s size=%s)",
                pos_key, deal_id, direction, entry, cur_size,
            )
            return
        if cur_size is None or cur_size < 2.0:
            logger.info(
                "[SCALE_OUT] skip %s — size=%s < 2.0; nothing to scale",
                pos_key, cur_size,
            )
            return

        close_dir = "SELL" if direction == "BUY" else "BUY"
        scale_size = max(1.0, round(float(cur_size) * SCALE_OUT_FRACTION, 2))

        # 1) partial close at IG.
        try:
            from close_sb_now import _close_position_by_deal
            resp = _close_position_by_deal(
                deal_id, close_dir, scale_size,
                intent_path="SCALE_OUT:_scale_out_50pct",
                intent_reason="scale_out_50pct",
                intent_partial=True,
            )
        except Exception as exc:
            logger.warning("[SCALE_OUT] %s partial-close call raised: %s", pos_key, exc)
            return
        if not resp or (isinstance(resp, dict) and str(resp.get("dealStatus") or "").upper() != "ACCEPTED"):
            logger.warning(
                "[SCALE_OUT] %s partial-close NOT ACCEPTED (resp=%s) — will retry next tick",
                pos_key, resp,
            )
            return

        # Pull the actual fill price for accurate partial_bank_pips.
        # If IG's confirm response carries "level" → real fill (authoritative).
        # If not → fall back to last_mid for a best-effort number BUT flag
        # partial_fill_estimated=True so the log record (and downstream
        # clean-run analysis on total_pnl_pips) can distinguish a real fill
        # from a stale-mid estimate. Same null-vs-zero discipline as the
        # confirmation engine: a missing fill must be a KNOWN UNKNOWN.
        partial_exit_price = None
        partial_fill_estimated = False
        try:
            if isinstance(resp, dict):
                partial_exit_price = _safe_float(resp.get("level"))
        except Exception:
            partial_exit_price = None
        if partial_exit_price is None:
            partial_exit_price = _safe_float(st.get("last_mid"))
            partial_fill_estimated = True

        # Compute realised partial bank in pips.
        partial_bank_pips = 0.0
        if partial_exit_price is not None:
            if direction == "BUY":
                partial_bank_pips = (float(partial_exit_price) - float(entry)) / float(ppp)
            else:
                partial_bank_pips = (float(entry) - float(partial_exit_price)) / float(ppp)
        partial_bank_pips = round(float(partial_bank_pips), 2)
        partial_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Distinguish real-fill vs estimated-fill in the logs so the
        # operator can see at a glance which path ran for any scale-out.
        if not partial_fill_estimated and partial_exit_price is not None:
            logger.info(
                "[SCALE-OUT] %s partial fill price from BROKER level=%.5f (bank=%+.2fp)",
                pos_key, float(partial_exit_price), partial_bank_pips,
            )
        else:
            logger.warning(
                "[SCALE-OUT] %s ⚠️ no broker level in response — partial_bank "
                "ESTIMATED from last_mid=%s (flagged estimated, bank=%+.2fp)",
                pos_key,
                f"{partial_exit_price:.5f}" if partial_exit_price is not None else "N/A",
                partial_bank_pips,
            )

        # 2) move runner's broker SL to BE, preserve original TP.
        #
        # 2026-06-05: capture amend success on `st["be_amend_ok"]` so the
        # structure_exit gate and the bb_bounce runner trail can decide
        # whether broker BE is actually held. Pre-fix the result was
        # ignored — a silently-failed amend left broker SL at the original
        # 20p stop while st["sl"]=0 and meta["scaled_out"]=True falsely
        # implied BE protection (06-03 06:30 incident: runner closed
        # -10.5p via structure_exit because BE never propagated).
        # Single short retry handles IG's "still settling" rejection
        # window after a confirmation; if it still fails, leave structure_exit
        # available as the -10p safety net (better than the unstopped 20p).
        tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
        # Fix 2 (2026-07-16) — STRONG profile TP release. When the knob
        # is on and profile_id==STRONG, replace the fire-time TP with a
        # far sentinel (entry ± REGIME_MGMT_STRONG_TP_RELEASE_PIPS) so
        # the runner cannot die at fire-time TP. FORMING owns TP via
        # ladder (untouched); LEGACY / RANGE preserve fire-time TP.
        _profile_id_sc = str(st.get("profile_id") or "").upper()
        _tp_released = (
            REGIME_MGMT_STRONG_TP_RELEASE
            and _profile_id_sc == "STRONG"
        )
        if _tp_released:
            _runner_tp_pips = float(REGIME_MGMT_STRONG_TP_RELEASE_PIPS)
        else:
            _runner_tp_pips = float(tp_pips)
        if direction == "BUY":
            runner_tp_price = float(entry) + _runner_tp_pips * float(ppp)
        else:
            runner_tp_price = float(entry) - _runner_tp_pips * float(ppp)
        _be_ok = _amend_broker_sl(pos_key, new_sl_price=float(entry),
                                  current_tp_price=runner_tp_price)
        if not _be_ok:
            time.sleep(0.5)
            _be_ok = _amend_broker_sl(pos_key, new_sl_price=float(entry),
                                      current_tp_price=runner_tp_price)
        # Defect #8 fix (2026-09-10). Live incident 2026-09-09: post-scale
        # BE amend rejected by IG (ATTACHED_ORDER_LEVEL_ERROR) because the
        # entry price sat inside IG's min-stop distance from live. The
        # 2-try BE loop above then gave up and the runner rode its
        # original 20p SL until close. Fix: if BE is rejected, retry ONCE
        # with the tightest IG-legal stop — live_mid ± (IG min-stop dist
        # + margin) in the unfavorable direction. This is not BE, but
        # sits between entry and the original fire-time SL, so the
        # runner is materially better protected than "no amend at all".
        # `be_amend_ok` stays False so profile trails (which assume SL=BE)
        # do NOT engage — the runner just holds the safe SL and rides
        # original TP. LOUD [BE-AMEND-FAILED] alert only fires when BOTH
        # BE and safe-SL are rejected.
        _safe_sl_ok = False
        _safe_sl_price = None
        if not _be_ok:
            try:
                _live_mid = _safe_float(st.get("last_mid"), None)
                _min_pips = _ig_min_stop_pips_for_pair(pair)
                _margin_pips = float(
                    os.getenv("SL_AMEND_MIN_DIST_MARGIN_PIPS", "")
                    or SL_AMEND_MIN_DIST_MARGIN_PIPS
                )
                _safe_offset_pips = float(_min_pips) + float(_margin_pips)
                if _live_mid is not None and float(_live_mid) > 0:
                    if direction == "BUY":
                        _safe_sl_price = float(_live_mid) - _safe_offset_pips * float(ppp)
                    else:
                        _safe_sl_price = float(_live_mid) + _safe_offset_pips * float(ppp)
                    logger.info(
                        "[SCALE_OUT] %s BE rejected; retry with IG-min-safe SL "
                        "live_mid=%.5f offset=%.2fp (min=%.2f + margin=%.2f) "
                        "safe_sl=%.5f entry=%.5f",
                        pos_key, float(_live_mid), _safe_offset_pips,
                        float(_min_pips), float(_margin_pips),
                        float(_safe_sl_price), float(entry),
                    )
                    _safe_sl_ok = _amend_broker_sl(
                        pos_key,
                        new_sl_price=float(_safe_sl_price),
                        current_tp_price=runner_tp_price,
                    )
                    if _safe_sl_ok:
                        logger.info(
                            "[SCALE_OUT] %s IG-min-safe SL ACCEPTED at %.5f "
                            "(runner protected BELOW BE; %.2fp from live_mid; "
                            "profile trails remain OFF — be_amend_ok=False)",
                            pos_key, float(_safe_sl_price), _safe_offset_pips,
                        )
                else:
                    logger.warning(
                        "[SCALE_OUT] %s IG-min-safe SL skipped — no live_mid",
                        pos_key,
                    )
            except Exception as _safe_exc:
                logger.warning(
                    "[SCALE_OUT] %s IG-min-safe SL retry raised: %s",
                    pos_key, _safe_exc,
                )
        st["be_amend_ok"] = bool(_be_ok)
        # Bookkeeping: the safe-SL fallback is not BE but it IS a real
        # broker stop that the close classifier and reconciliation
        # should see. Record it on epic state so downstream reads have
        # the current broker SL price without another IG round-trip.
        if _safe_sl_ok and _safe_sl_price is not None:
            st["safe_sl_amend_ok"] = True
            st["safe_sl_price"] = float(_safe_sl_price)
        if _tp_released and _be_ok:
            # Preserve released TP so the peak-pivot ratchet's re-read of
            # st["tp"] (line ~1435) keeps the sentinel across amends.
            # Snapshot the original for telemetry / post-mortem.
            if st.get("tp_at_fire") is None:
                st["tp_at_fire"] = float(tp_pips)
            st["tp"] = float(_runner_tp_pips)
            logger.info(
                "[PROFILE:STRONG] %s runner TP released pos=%s "
                "was=+%.1fp now=+%.1fp entry=%.5f tp_price=%.5f",
                pos_key, pos_key, float(tp_pips),
                _runner_tp_pips, float(entry), runner_tp_price,
            )
        elif _tp_released and not _be_ok:
            # Amend fail already logged + retried inside _amend_broker_sl.
            # Downstream Telegram page (BE-fail block below) is augmented
            # to name the TP-release attempt.
            logger.warning(
                "[PROFILE:STRONG] %s runner TP release NOT confirmed — "
                "BE amend rejected twice; runner rides original SL and "
                "original TP (see BE-fail Telegram page).",
                pos_key,
            )
        if not _be_ok:
            logger.warning(
                "[SCALE_OUT] %s BE amend NOT confirmed after retry — "
                "structure_exit remains active as -10p safety net; "
                "bb_bounce trail will not engage until BE confirms.",
                pos_key,
            )
            # Live-risk event: runner is now sized as scale-out expects
            # but sits behind the original SL. Page the operator via the
            # same telegram_alerts channel used by the success alert
            # below (send_error_alert reuses send_telegram_message).
            # Defect #8 gating (2026-09-10): LOUD [BE-AMEND-FAILED] only
            # when the IG-min-safe SL fallback ALSO failed. If safe-SL
            # landed the runner is under-protected vs BE but still
            # materially better than the original 20p SL — an info-line
            # is enough, no operator page.
            if not _safe_sl_ok:
                logger.error(
                    "[BE-AMEND-FAILED] %s runner riding ORIGINAL SL — "
                    "deal=%s reject=%s (both BE and IG-min-safe SL rejected)",
                    pos_key, deal_id,
                    meta.get("last_amend_reject_reason") or "unknown",
                )
                try:
                    _reject_reason = str(meta.get("last_amend_reject_reason") or "unknown")
                    _release_note = (
                        " (TP release attempted, ALSO failed — runner "
                        "sits behind ORIGINAL SL and ORIGINAL TP)"
                        if _tp_released else ""
                    )
                    from telegram_alerts import send_error_alert
                    send_error_alert(
                        f"[BE-AMEND-FAILED] RUNNER RIDING ORIGINAL SL{_release_note}\n"
                        f"Pair: {pair}\n"
                        f"Deal: {deal_id}\n"
                        f"Reason: {_reject_reason}\n"
                        f"Both BE (=entry) and IG-min-safe SL "
                        f"(from live_mid) were rejected."
                    )
                except Exception as _tg_exc:
                    logger.debug(
                        "[SCALE_OUT] BE-fail telegram alert failed: %s", _tg_exc,
                    )
            else:
                logger.warning(
                    "[SCALE_OUT] %s BE rejected but IG-min-safe SL landed "
                    "at %.5f — runner protected below BE (no alert; "
                    "profile trails remain OFF)",
                    pos_key, float(_safe_sl_price) if _safe_sl_price is not None else 0.0,
                )

        # 3) update EPIC_STATE so reconciliation + future management
        #    knows we're now a 1-unit runner.
        new_size = float(cur_size) - float(scale_size)
        st["size"] = new_size
        st["partial_bank_pips"] = partial_bank_pips
        st["partial_bank_ts"] = partial_ts
        st["partial_fill_estimated"] = bool(partial_fill_estimated)
        st["scaled_out"] = True
        # Software SL bookkeeping in pips (broker SL is now at entry).
        st["sl"] = 0.0

        # 4) latch the dispatcher.
        meta["scaled_out"] = True
        meta["be_amend_ok"] = bool(_be_ok)

        # 5) log the partial to signal_log so the open record carries the
        #    bank — _on_trade_close later patches outcome with total_pnl_pips.
        try:
            import signal_logger as _sl
            _sl_id = st.get("signal_log_id")
            if _sl_id and hasattr(_sl, "log_partial"):
                _sl.log_partial(
                    trade_id=str(_sl_id),
                    partial_pnl_pips=partial_bank_pips,
                    partial_exit_price=float(partial_exit_price) if partial_exit_price is not None else None,
                    partial_ts=partial_ts,
                    runner_size=new_size,
                    runner_sl_price=float(entry),
                    partial_fill_estimated=bool(partial_fill_estimated),
                )
        except Exception as exc:
            logger.debug("[SCALE_OUT] log_partial failed for %s: %s", pos_key, exc)

        # 6) Telegram alert (best-effort).
        try:
            from telegram_alerts import send_partial_exit_alert
            send_partial_exit_alert(
                epic=str(st.get("epic") or pos_key.split("|", 1)[0]),
                pct="50%",
                pnl_pips=partial_bank_pips,
                reason=f"scale_out_+{SCALE_OUT_TRIGGER_PIPS:.0f}p",
            )
        except Exception as exc:
            logger.debug("[SCALE_OUT] telegram alert failed: %s", exc)

        logger.info(
            "[SCALE_OUT] %s FIRED — closed %.2f of %.2f at %s (bank=%+.2fp), "
            "runner=%.2f at BE (entry=%.5f tp=%.5f)",
            pos_key, scale_size, cur_size,
            f"{partial_exit_price:.5f}" if partial_exit_price is not None else "N/A",
            partial_bank_pips, new_size, float(entry), runner_tp_price,
        )
    except Exception as exc:
        logger.warning(
            "[SCALE_OUT] %s dispatch raised (swallowed): %s",
            pos_key, exc, exc_info=True,
        )

# ── BRIEFING_EXECUTION simple-exits (2026-04-21) ──────────────────────
# BE rides to SL / TP / EOD only; REGIME_MAX_HOLD is env-gated off.
# Flip to "1" to enable REGIME_MAX_HOLD for BE trades.
# (MPP-companion flag BRIEFING_EXEC_PROFIT_PROTECT_ENABLED removed
# 2026-05-23 along with MPP itself.)
_BE_REGIME_MAX_HOLD_ENABLED = (os.getenv("BRIEFING_EXEC_REGIME_MAX_HOLD_ENABLED", "0") or "0").strip() == "1"


def _is_briefing_exec_mode(mode: Any) -> bool:
    """True if mode is BRIEFING_EXECUTION (prefix match for future suffixes)."""
    return str(mode or "").strip().upper().startswith("BRIEFING_EXECUTION")

# ============================================================
# CONFIG — WINDOW SWEEP DETECTOR (single-phase: BB touch + hist reducing)
# ============================================================
WINDOW_SWEEP_ENABLED = (os.getenv("WINDOW_SWEEP_ENABLED", "0") or "0").strip() == "1"
WINDOW_SWEEP_CLOSE_PRE_NEWS = (os.getenv("WINDOW_SWEEP_CLOSE_PRE_NEWS", "1") or "1").strip() == "1"

# Two daily windows (BST). Converted to UTC at runtime based on BST flag.
WINDOW_SWEEP_MORNING_BST = (6, 45, 11, 30)    # 06:45-11:30 BST (London open through mid-morning)
WINDOW_SWEEP_AFTERNOON_BST = (13, 30, 17, 0)  # 13:30-17:00 BST (NY session through close)

# SL
WINDOW_SWEEP_SL_PIPS = float(os.getenv("WINDOW_SWEEP_SL_PIPS", "20") or 20.0)

# Internal management metadata (per epic)
_SWEEP_MGMT_BY_EPIC: Dict[str, Dict[str, Any]] = {}
_PROFIT_MGMT_BY_EPIC: Dict[str, Dict[str, Any]] = {}
_CONSOLIDATION_BY_EPIC: Dict[str, Dict[str, Any]] = {}
_BRIEFING_TP_BY_EPIC: Dict[str, Dict[str, Any]] = {}

# TM V2 shadow seam dedup (ruling 2026-09-24 §3): {deal_id: bar_open_iso}.
# Ensures per-tick polling emits at most one shadow row per completed
# 5-minute bar per position. Cleared on trade close via _clear_profit_meta
# where practical, otherwise self-heals via the bar_open comparison.
_TMV2_SEAM_BAR_KEY: Dict[str, str] = {}

# One-time proof-of-arm sentinel for the §21.6 adaptive band exit at
# _monitor_profit_protection :5536. Set to True after the first in-scope
# position reaches that site so the "[qm_exit] armed ..." INFO fires
# exactly once per process lifetime, regardless of QM_ADAPTIVE_EXIT_ENABLED.
_QM_EXIT_ARMED_LOGGED: bool = False

# Kill-switch observability: track the last-seen QM_ADAPTIVE_EXIT_ENABLED
# string so a transition (including the very first observation) emits an
# INFO. Makes both directions of the flip visible in the journal — proof
# that the running process is READING the flag per-decision.
# Sentinel value None ⇒ never observed yet; first eval will log
# "None -> <curr>".
_QM_EXIT_LAST_FLAG_SEEN: Optional[str] = None

# ── RANGE_ROTATION BB_BOUNCE single-exit scalp registry (2026-07-07) ───
# Populated by register_bb_range_scalp() at trade open when BB_BOUNCE
# fires under RANGE_ROTATION with the single-exit switch on. Its
# presence tells _monitor_bb_range_scalp to watch the position's
# regime and close at market if winning_regime leaves RANGE_ROTATION
# (the range premise is void → the range scalp ends). Cleared on
# position deactivation (mirrors _BRIEFING_TP_BY_EPIC lifecycle).
_BB_RANGE_SCALP_BY_EPIC: Dict[str, Dict[str, Any]] = {}


def register_bb_range_scalp(
    epic: str,
    entry_price: float,
    direction: str,
    opposite_band_price: float,
    pair: str = "GBPUSD",
) -> None:
    """Register a RANGE_ROTATION BB_BOUNCE single-exit scalp for
    regime-exit monitoring.

    Called from autobot.py at trade open INSTEAD of setup_briefing_tp
    when the strategy's decision.debug carries range_scalp=True. The
    tier machine is intentionally NOT registered — the broker LIMIT
    at the opposite band is the real exit. This registry only drives
    the "close if regime leaves RANGE_ROTATION" safety.
    """
    _BB_RANGE_SCALP_BY_EPIC[str(epic)] = {
        "entry_price": float(entry_price),
        "direction": str(direction).upper(),
        "opposite_band_price": float(opposite_band_price),
        "pair": str(pair).upper(),
        "opened_ts": time.time(),
    }
    logger.info(
        "[BB_RANGE_SCALP] %s registered: dir=%s entry=%.5f opp_band=%.5f "
        "pair=%s — tier machine suppressed, regime-exit close armed",
        epic, str(direction).upper(), float(entry_price),
        float(opposite_band_price), str(pair).upper(),
    )

_PROFIT_STATE_PATH = os.path.join(
    os.getenv("CACHE_DIR", "/opt/tradingbot/cache"), "profit_mgmt_state.json"
)


def _persist_profit_state() -> None:
    """Write _PROFIT_MGMT_BY_EPIC to disk for restart recovery.

    Persists the scale-out idempotency guard and best_pnl bookkeeping.
    Without "scaled_out" persisted, a mid-trade restart would re-scale
    the same runner twice (the meta flag is the primary idempotency
    guard inside _scale_out_50pct). trail_armed is kept for the
    separate sweep-trail manager which shares this dict.
    """
    try:
        import json as _json
        data = {}
        for epic, meta in _PROFIT_MGMT_BY_EPIC.items():
            data[epic] = {
                "best_pnl_pips": meta.get("best_pnl_pips"),
                "scaled_out": bool(meta.get("scaled_out")),
                "trail_armed": meta.get("trail_armed"),
                # Trend-trail step (0/1/2/3) — survives restart so the
                # ratchet doesn't move backward post-recovery.
                "trend_trail_step": int(meta.get("trend_trail_step") or 0),
                # 2026-06-05: BE-amend confirmation + bb_bounce trail
                # lock state. be_amend_ok survives restart so the gate
                # decisions stay coherent across processes; the lock
                # pips ratchet survives so the trail doesn't regress.
                "be_amend_ok": bool(meta.get("be_amend_ok")),
                "bb_bounce_trail_lock_pips": float(meta.get("bb_bounce_trail_lock_pips") or 0.0),
                # 2026-07-18: post-scale FLOOR state — persists so the
                # IG-close classifier can label FLOOR_STOP_POST_SCALEOUT
                # correctly across a mid-trade restart.
                "bb_bounce_post_scale_floor_applied": bool(
                    meta.get("bb_bounce_post_scale_floor_applied")
                ),
                # 2026-06-12: latest broker-amended SL level (and stamp), so
                # the IG-close classifier can recognise a trail/BE/amended-SL
                # hit instead of mislabelling it as "External/manual close".
                "last_amended_sl_price": (
                    float(meta["last_amended_sl_price"])
                    if meta.get("last_amended_sl_price") is not None else None
                ),
                "last_amended_sl_ts": (
                    float(meta["last_amended_sl_ts"])
                    if meta.get("last_amended_sl_ts") is not None else None
                ),
                # 2026-08-14: mirrors last_amended_sl_*. See _amend_broker_sl.
                "last_amended_limit_price": (
                    float(meta["last_amended_limit_price"])
                    if meta.get("last_amended_limit_price") is not None else None
                ),
                "last_amended_limit_ts": (
                    float(meta["last_amended_limit_ts"])
                    if meta.get("last_amended_limit_ts") is not None else None
                ),
            }
        with open(_PROFIT_STATE_PATH, "w") as f:
            _json.dump(data, f)
    except Exception:
        pass  # Best-effort persistence, never block trading


def _load_profit_state() -> Dict[str, Dict[str, Any]]:
    """Load persisted profit management state from disk."""
    try:
        import json as _json
        with open(_PROFIT_STATE_PATH) as f:
            return _json.load(f)
    except Exception:
        return {}


def restore_profit_state_for_active_trades(active_epics: set) -> None:
    """Restore persisted profit state for trades that survived a restart.

    Call after reconcile_open_positions() with the set of active epics.
    Restores scaled_out so the scale-out trigger does NOT re-fire on an
    already-scaled runner; restores best_pnl_pips so the trigger
    threshold check still references the actual peak; restores
    trail_armed for the sweep-trail manager.
    """
    saved = _load_profit_state()
    for epic, meta in saved.items():
        if epic in active_epics and epic not in _PROFIT_MGMT_BY_EPIC:
            _PROFIT_MGMT_BY_EPIC[epic] = {
                "created_ts": time.time(),
                "best_pnl_pips": meta.get("best_pnl_pips", 0),
                "last_pnl_pips": meta.get("best_pnl_pips", 0),
                "scaled_out": bool(meta.get("scaled_out")),
                "trail_armed": bool(meta.get("trail_armed")),
                "trend_trail_step": int(meta.get("trend_trail_step") or 0),
                # 2026-06-05: BE/trail recovery fields. be_amend_ok defaults
                # to False on legacy saves (field absent pre-this-change); a
                # one-shot BE-recover amend in _monitor_profit_protection
                # will re-enforce broker BE for surviving scaled runners
                # and stamp this field True on success.
                "be_amend_ok": bool(meta.get("be_amend_ok")),
                "bb_bounce_trail_lock_pips": float(meta.get("bb_bounce_trail_lock_pips") or 0.0),
                # 2026-07-18: post-scale FLOOR state — see _persist_profit_state.
                "bb_bounce_post_scale_floor_applied": bool(
                    meta.get("bb_bounce_post_scale_floor_applied")
                ),
                # 2026-06-12: latest broker-amended SL level + stamp.
                "last_amended_sl_price": (
                    float(meta["last_amended_sl_price"])
                    if meta.get("last_amended_sl_price") is not None else None
                ),
                "last_amended_sl_ts": (
                    float(meta["last_amended_sl_ts"])
                    if meta.get("last_amended_sl_ts") is not None else None
                ),
                # 2026-08-14: mirrors last_amended_sl_*.
                "last_amended_limit_price": (
                    float(meta["last_amended_limit_price"])
                    if meta.get("last_amended_limit_price") is not None else None
                ),
                "last_amended_limit_ts": (
                    float(meta["last_amended_limit_ts"])
                    if meta.get("last_amended_limit_ts") is not None else None
                ),
            }
            logger.info(
                f"[TradeManager] Restored profit state for {epic}: "
                f"best_pnl={meta.get('best_pnl_pips'):.2f} "
                f"scaled_out={bool(meta.get('scaled_out'))} "
                f"trail_armed={bool(meta.get('trail_armed'))} "
                f"be_amend_ok={bool(meta.get('be_amend_ok'))} "
                f"bb_trail_lock={float(meta.get('bb_bounce_trail_lock_pips') or 0.0):.1f}p"
            )


# ============================================================
# HELPERS
# ============================================================
def _safe_str(x: Any) -> str:
    try:
        return str(x)
    except Exception:
        return ""


def _safe_float(x: Any, fallback: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return fallback
        out = float(x)
        if out != out:  # NaN
            return fallback
        return out
    except Exception:
        return fallback


def _extract_positions_list(open_pos: Any) -> list:
    """
    close_sb_now.get_open_positions() can return:
      - list of positions
      - dict with "positions" list
      - other shapes
    Normalize to a list.
    """
    if open_pos is None:
        return []
    if isinstance(open_pos, list):
        return open_pos
    if isinstance(open_pos, dict):
        v = open_pos.get("positions")
        if isinstance(v, list):
            return v
    return []


def _position_matches_trade_state(pos_item: Any, deal_id: Optional[str], epic: Optional[str]) -> bool:
    """
    Try to match either by deal id (best), else by epic.
    Handles common IG shapes: item["position"]["dealId"], etc.
    """
    if not isinstance(pos_item, dict):
        return False

    # IG often returns {"position": {...}, "market": {...}}
    pos = pos_item.get("position") if isinstance(pos_item.get("position"), dict) else pos_item

    pid = _safe_str(pos.get("dealId") or pos.get("deal_id") or pos.get("dealID") or "")
    pepic = _safe_str(pos.get("epic") or pos.get("instrumentName") or "")

    if deal_id and pid and pid == deal_id:
        return True

    # Fallback to epic match (less reliable but better than nothing)
    if epic and pepic and pepic == epic:
        return True

    return False


def _state_for_epic(epic: str) -> Dict[str, Any]:
    fn = getattr(_exec, "_state_for_epic", None)
    if callable(fn):
        return fn(str(epic))

    e = str(epic or "").strip() or "UNKNOWN"
    st = TRADE_STATE_BY_EPIC.get(e)
    if isinstance(st, dict):
        return st
    return {}


def _reset_trade_state(epic: str) -> None:
    fn = getattr(_exec, "_reset_trade_state", None)
    if callable(fn):
        fn(str(epic))
        return

    st = _state_for_epic(epic)
    try:
        st.clear()
        st.update({"active": False, "epic": str(epic)})
    except Exception:
        pass


def _is_liquidity_sweep_mode(mode_val: Any) -> bool:
    try:
        return str(mode_val or "").strip().upper() == LIQUIDITY_SWEEP_MODE
    except Exception:
        return False


def _effective_price_for_management(direction: str, mid_price: float, bid: Any = None, ask: Any = None) -> float:
    """
    Match executor semantics:
      - BUY trades managed against bid when available
      - SELL trades managed against ask when available
    """
    d = str(direction or "").upper()
    b = _safe_float(bid, None)
    a = _safe_float(ask, None)
    m = float(mid_price)

    if d == "BUY" and b is not None:
        return float(b)
    if d == "SELL" and a is not None:
        return float(a)
    return m


def _calculate_pnl_pips(direction: str, entry_price: float, current_price: float, pip_size: float) -> float:
    d = str(direction or "").upper()
    if pip_size <= 0:
        return 0.0
    if d == "BUY":
        return (float(current_price) - float(entry_price)) / float(pip_size)
    if d == "SELL":
        return (float(entry_price) - float(current_price)) / float(pip_size)
    return 0.0


_CLOSE_REASON_TRAIL_AWARE_ENABLED = (
    os.getenv("CLOSE_REASON_TRAIL_AWARE_ENABLED", "1") or "1"
).strip().lower() in ("1", "true", "yes", "on")
_CLOSE_REASON_MATCH_TOLERANCE_PIPS = float(
    os.getenv("CLOSE_REASON_MATCH_TOLERANCE_PIPS", "3.0") or 3.0
)
# Wider tolerance for the amended-limit branch (2026-08-14). SL fills are
# triggered at the stop level; limit fills often complete a tick before
# the sweep observes state, so last_mid can trail the actual fill by more
# than the 3.0p SL default. The 2026-08-14 GBPUSD_TREND_V3_L case was 3.35p
# adrift (last_mid=13549.05 vs amended limit=13545.7); 5.0p accommodates
# it with ~1.65p headroom. Only applies to the amended-limit branch, so
# it can't broaden SL/BE matching.
_CLOSE_REASON_LIMIT_MATCH_TOLERANCE_PIPS = float(
    os.getenv("CLOSE_REASON_LIMIT_MATCH_TOLERANCE_PIPS", "5.0") or 5.0
)


def _detect_ig_close_reason(state_obj: dict, exit_hint: Any,
                            pos_key: Any = None) -> str:
    """
    Infer whether a position that vanished from IG was a TP hit, SL hit,
    a trail/BE/amended-SL hit, or a genuine external/manual close.

    Order of checks (with CLOSE_REASON_TRAIL_AWARE_ENABLED=1, the default):

      1. If profit-mgmt meta carries `last_amended_sl_price` for this
         pos_key AND recorded close_price is within tolerance of that
         level, emit one of:
           - "FLOOR_STOP_POST_SCALEOUT"  — scaled_out + bb_bounce_post_scale_floor_applied
                                           (SL was ratcheted above entry by
                                           _apply_bb_bounce_post_scale_floor;
                                           a genuine +Np win, not BE — see
                                           2026-07-18 mislabel fix)
           - "TRAIL_STOP"                — scaled_out + bb_bounce_trail_lock_pips > 0
                                           (BB_BOUNCE runner trail moved SL
                                           above entry, floor never armed)
           - "BE_STOP_POST_SCALEOUT"     — scaled_out + neither of the above
                                           (SL sat at entry; genuine break-even)
           - "AMENDED_SL_HIT"            — not scaled_out (manual / pre-scale BE move)
      2. If profit-mgmt meta carries `last_amended_limit_price` for this
         pos_key AND exit price is within the wider limit tolerance of that
         level, emit "TP hit" (same label as branch 4 so downstream exit-
         type mapping is unchanged; the branch just uses the amended level
         directly instead of inferring TP via last_mid vs entry+tp_pips,
         which can miss when last_mid trails the actual fill).
         Ordered after the amended-SL branch: SL and limit sit on opposite
         sides of entry, so the branches can't collide, but keeping AMENDED
         SL first preserves the existing docstring order and the scaled-out
         labelling path (FLOOR/TRAIL/BE) that only runs on the SL side.
      3. Original ±SL distance match → "SL hit"
      4. Original ±TP distance match → "TP hit"
      5. Pre-scale-out BE band (0..be_offset+tol) → "Breakeven stop hit (IG server-side)"
      6. Catch-all → "External close (not initiated by this host)"

    Setting CLOSE_REASON_TRAIL_AWARE_ENABLED=0 restores the pre-2026-06-12
    behaviour: trail-aware step 1 is skipped, only steps 2-5 run.

    `pos_key` is the EPIC_STATE key ("<epic>|<mode>"); used to look up
    `_PROFIT_MGMT_BY_EPIC` for trail/amend state. When None, the
    trail-aware branch is skipped (callers that already passed the
    full state object without a key keep the old behaviour).
    """
    tolerance = float(_CLOSE_REASON_MATCH_TOLERANCE_PIPS)
    try:
        entry = float(state_obj.get("entry_price") or 0)
        direction = str(state_obj.get("direction") or "").upper()
        pip_size = float(state_obj.get("pip_size") or 1.0)
        sl_pips = float(state_obj.get("sl") or 0)
        tp_pips = float(state_obj.get("tp") or 0)
        exit_p = float(exit_hint) if exit_hint is not None else None

        if entry <= 0 or pip_size <= 0 or exit_p is None or direction not in ("BUY", "SELL"):
            return "External close (not initiated by this host)"

        # ── 1. Trail-aware: close price near the last broker-amended SL ──
        if _CLOSE_REASON_TRAIL_AWARE_ENABLED and pos_key is not None:
            try:
                _meta = _PROFIT_MGMT_BY_EPIC.get(pos_key)
            except Exception:
                _meta = None
            if isinstance(_meta, dict):
                last_amend = _meta.get("last_amended_sl_price")
                if last_amend is not None:
                    try:
                        diff_pips = abs(float(exit_p) - float(last_amend)) / float(pip_size)
                    except Exception:
                        diff_pips = None
                    if diff_pips is not None and diff_pips <= tolerance:
                        scaled = bool(_meta.get("scaled_out"))
                        floor_applied = bool(
                            _meta.get("bb_bounce_post_scale_floor_applied")
                        )
                        lock = float(_meta.get("bb_bounce_trail_lock_pips") or 0.0)
                        # State-driven, not distance-driven: the floor helper
                        # sets bb_bounce_post_scale_floor_applied on its
                        # successful amend, so a subsequent SL hit is a
                        # FLOOR stop regardless of the closed pip magnitude.
                        # Checked BEFORE the lock branch because the floor
                        # ALSO writes bb_bounce_trail_lock_pips (both keys
                        # go true when the floor arms).
                        if scaled and floor_applied:
                            return "FLOOR_STOP_POST_SCALEOUT"
                        if scaled and lock > 0:
                            return "TRAIL_STOP"
                        if scaled:
                            return "BE_STOP_POST_SCALEOUT"
                        return "AMENDED_SL_HIT"

                # ── 1b. Trail-aware: close price near the last broker-amended
                # limit (2026-08-14). See _amend_broker_sl for the write site.
                last_amend_limit = _meta.get("last_amended_limit_price")
                if last_amend_limit is not None:
                    try:
                        diff_limit_pips = abs(float(exit_p) - float(last_amend_limit)) / float(pip_size)
                    except Exception:
                        diff_limit_pips = None
                    if diff_limit_pips is not None and diff_limit_pips <= float(
                        _CLOSE_REASON_LIMIT_MATCH_TOLERANCE_PIPS
                    ):
                        return "TP hit"

        pnl_pips = _calculate_pnl_pips(direction, entry, exit_p, pip_size)

        if tp_pips > 0 and abs(pnl_pips - tp_pips) <= tolerance:
            return "TP hit"
        if sl_pips > 0 and abs(pnl_pips + sl_pips) <= tolerance:
            return "SL hit"

        # Breakeven stop: PnL is small and positive (0 to BE offset + tolerance).
        # SOFTWARE_BE_OFFSET_PIPS defaults to 1; read it if available.
        try:
            be_offset = float(os.getenv("SOFTWARE_BE_OFFSET_PIPS", "1"))
        except Exception:
            be_offset = 1.0
        if 0 <= pnl_pips <= be_offset + tolerance:
            return "Breakeven stop hit (IG server-side)"
    except Exception:
        pass
    return "External close (not initiated by this host)"


def _close_trade_best_effort(epic: str, reason: str, exit_hint_price: float) -> Any:
    return _exec.close_position(
        epic=str(epic),
        reason=str(reason),
        exit_hint_price=float(exit_hint_price),
    )


# ============================================================
# Consolidation hold helpers
# ============================================================
def _update_consolidation_state(epic: str, direction: str, mid_price: float) -> None:
    """
    Track whether price is consolidating (no new extreme in N candles).

    Called once per tick from monitor_positions before individual monitors run.
    """
    if not CONSOLIDATION_HOLD_ENABLED:
        return

    now = time.time()
    candle_ts = int(now // _CONSOLIDATION_CANDLE_SECONDS) * _CONSOLIDATION_CANDLE_SECONDS

    meta = _CONSOLIDATION_BY_EPIC.get(epic)
    if meta is None:
        _CONSOLIDATION_BY_EPIC[epic] = {
            "current_candle_ts": candle_ts,
            "best_extreme": mid_price,
            "candle_had_new_extreme": True,
            "candles_without_extreme": 0,
            "consolidation_active": False,
        }
        return

    # Candle boundary transition
    if candle_ts != meta["current_candle_ts"]:
        elapsed = max(1, (candle_ts - meta["current_candle_ts"]) // _CONSOLIDATION_CANDLE_SECONDS)
        if meta["candle_had_new_extreme"]:
            meta["candles_without_extreme"] = 0
        else:
            meta["candles_without_extreme"] += elapsed
        meta["current_candle_ts"] = candle_ts
        meta["candle_had_new_extreme"] = False

    # Check for new extreme in trade direction
    new_extreme = False
    if direction == "BUY" and mid_price > meta["best_extreme"]:
        new_extreme = True
        meta["best_extreme"] = mid_price
    elif direction == "SELL" and mid_price < meta["best_extreme"]:
        new_extreme = True
        meta["best_extreme"] = mid_price

    was_active = meta["consolidation_active"]

    if new_extreme:
        meta["candle_had_new_extreme"] = True
        meta["candles_without_extreme"] = 0
        if was_active:
            meta["consolidation_active"] = False
            logger.debug(
                f"[TradeManager] {epic} {direction}: consolidation hold released "
                f"— new {'high' if direction == 'BUY' else 'low'}, floor unfrozen"
            )
    elif meta["candles_without_extreme"] >= CONSOLIDATION_CANDLES and not was_active:
        meta["consolidation_active"] = True
        extreme_type = "high" if direction == "BUY" else "low"
        # Include current floor from profit meta if available
        profit_meta = _PROFIT_MGMT_BY_EPIC.get(epic)
        floor_val = profit_meta.get("locked_floor_pips") if profit_meta else None
        floor_str = f" — floor frozen at {floor_val:.2f} pips" if floor_val is not None else ""
        logger.debug(
            f"[TradeManager] {epic} {direction}: consolidation hold active "
            f"({meta['candles_without_extreme']} candles, no new {extreme_type}){floor_str}"
        )


def _is_consolidation_active(epic: str) -> bool:
    """Return True if consolidation hold is currently active for this epic."""
    if not CONSOLIDATION_HOLD_ENABLED:
        return False
    meta = _CONSOLIDATION_BY_EPIC.get(epic)
    return bool(meta and meta.get("consolidation_active"))


def _apply_consolidation_hold(meta: Dict[str, Any], best_pnl: float) -> float:
    """
    Return the effective best_pnl to use for floor calculation.

    During consolidation hold, returns the frozen snapshot so the floor
    does not advance.  When consolidation is inactive the snapshot is
    kept in sync with actual best_pnl.
    """
    consol_active = meta.get("_consol_active", False)

    if consol_active:
        # Floor stays frozen — return the snapshot taken when consolidation began
        return float(meta.get("_consol_frozen_best_pnl", best_pnl))

    # Not consolidated — keep snapshot up-to-date
    meta["_consol_frozen_best_pnl"] = best_pnl
    return best_pnl


# ============================================================
# WINDOW SWEEP DETECTOR
# ============================================================
def check_window_sweep(
    sym: str,
    candle_ts,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    bb_upper: float,
    bb_lower: float,
    macd_hist_vals: list,
    briefing: Optional[Dict[str, Any]],
    is_bst: bool = True,
) -> Optional[Dict[str, Any]]:
    """Single-phase WINDOW_SWEEP detector.

    Entry fires immediately on the 5M candle close that meets both:
      BUY: low < lower BB AND prior 3 candles hist positive & reducing
           (bullish momentum exhausting before price hits lower BB)
      SELL: high > upper BB AND prior 3 candles hist negative & reducing
           (bearish momentum exhausting before price hits upper BB)

    macd_hist_vals should be the 3 candles BEFORE the pierce candle (raw
    signed values, not absolute).  Briefing bias filters direction only.
    """
    if not WINDOW_SWEEP_ENABLED:
        return None
    if bb_upper is None or bb_lower is None:
        return None
    if candle_high is None or candle_low is None or candle_close is None:
        return None

    # Convert candle timestamp to BST hour/minute for window check
    try:
        if hasattr(candle_ts, 'hour'):
            utc_h, utc_m = candle_ts.hour, candle_ts.minute
        else:
            utc_h, utc_m = 0, 0
    except Exception:
        return None

    bst_h = utc_h + (1 if is_bst else 0)
    bst_minutes = bst_h * 60 + utc_m

    morning = WINDOW_SWEEP_MORNING_BST
    afternoon = WINDOW_SWEEP_AFTERNOON_BST
    morn_start = morning[0] * 60 + morning[1]
    morn_end = morning[2] * 60 + morning[3]
    aftn_start = afternoon[0] * 60 + afternoon[1]
    aftn_end = afternoon[2] * 60 + afternoon[3]

    if morn_start <= bst_minutes < morn_end:
        window = "MORNING"
    elif aftn_start <= bst_minutes < aftn_end:
        window = "AFTERNOON"
    else:
        return None

    # BB touch check
    lower_touch = float(candle_low) <= float(bb_lower)   # BUY setup
    upper_touch = float(candle_high) >= float(bb_upper)  # SELL setup
    if not lower_touch and not upper_touch:
        return None

    direction = "BUY" if lower_touch else "SELL"

    # No briefing bias filter — WINDOW_SWEEP fires on price action only

    # MACD histogram: 3 candles before pierce must be correct sign & reducing
    #   BUY:  hist was positive (green) and reducing — bullish momentum exhausting
    #   SELL: hist was negative (red) and reducing — bearish momentum exhausting
    if macd_hist_vals is None or len(macd_hist_vals) < 3:
        return None
    raw3 = [float(v) for v in macd_hist_vals[-3:]]
    if direction == "BUY":
        # All 3 must be positive (green)
        if not all(v > 0 for v in raw3):
            return None
    else:
        # All 3 must be negative (red)
        if not all(v < 0 for v in raw3):
            return None
    h3 = [abs(v) for v in raw3]
    if not (h3[2] < h3[1] < h3[0]):
        return None

    pierce_price = float(candle_low) if lower_touch else float(candle_high)
    bb_band = float(bb_lower) if lower_touch else float(bb_upper)

    logger.info(
        "[WINDOW_SWEEP] %s %s %s ENTRY @ %.5f — BB %s=%.5f, pierce=%.5f, "
        "hist %s reducing [%.6f→%.6f→%.6f]",
        sym, window, direction, float(candle_close),
        "lower" if lower_touch else "upper", bb_band, pierce_price,
        "green" if direction == "BUY" else "red",
        h3[0], h3[1], h3[2],
    )

    return {
        "direction": direction,
        "window": window,
        "pierce_price": pierce_price,
        "bb_band": bb_band,
        "close": float(candle_close),
    }


# ============================================================
# BRIEFING-LEVEL TP SELECTION
# ============================================================
def select_tp_levels(
    entry_price: float,
    direction: str,
    briefing_levels: list,
    pair: str = "GBPUSD",
) -> Dict[str, Any]:
    """Select TP1/TP2/TP3 from briefing levels beyond entry in trade direction.

    Args:
        entry_price: Trade entry price (IG points).
        direction: "BUY" or "SELL".
        briefing_levels: List of dicts with keys: price, level_type, source, major.
            level_type: "resistance" or "support"
            source: e.g. "briefing_resistance", "briefing_liquidity_buy"
            major: bool — True for major levels
        pair: Pair name for SL lookup.

    Returns:
        Dict with keys: tp1, tp2, tp3 (price levels), tp1_pips, tp2_pips, tp3_pips,
        sl_pips, levels_used (list of dicts), fallback (bool).
    """
    d = str(direction or "").upper()
    ppp = _ppp(pair)
    sl_pips = BRIEFING_TP_SL_PIPS.get(pair, BRIEFING_TP_SL_DEFAULT)

    # No briefing levels → fixed fallback
    if not briefing_levels:
        sign = 1.0 if d == "BUY" else -1.0
        return {
            "tp1": entry_price + BRIEFING_TP_FALLBACK_TP1 * ppp * sign,
            "tp2": entry_price + BRIEFING_TP_FALLBACK_TP2 * ppp * sign,
            "tp3": entry_price + BRIEFING_TP_FALLBACK_TP3 * ppp * sign,
            "tp1_pips": BRIEFING_TP_FALLBACK_TP1,
            "tp2_pips": BRIEFING_TP_FALLBACK_TP2,
            "tp3_pips": BRIEFING_TP_FALLBACK_TP3,
            "sl_pips": sl_pips,
            "levels_used": [],
            "fallback": True,
        }

    # Filter levels beyond entry in trade direction, sorted by distance
    beyond = []
    for lv in briefing_levels:
        price = _safe_float(lv.get("price") if isinstance(lv, dict) else getattr(lv, "price", None), None)
        if price is None:
            continue
        major = (lv.get("major") if isinstance(lv, dict) else getattr(lv, "major", False)) or False
        source = str(lv.get("source") if isinstance(lv, dict) else getattr(lv, "source", "")) or ""

        if d == "BUY" and price > entry_price:
            dist_pips = (price - entry_price) / ppp
            beyond.append({"price": price, "dist_pips": dist_pips, "major": major, "source": source})
        elif d == "SELL" and price < entry_price:
            dist_pips = (entry_price - price) / ppp
            beyond.append({"price": price, "dist_pips": dist_pips, "major": major, "source": source})

    # Sort by distance (nearest first)
    beyond.sort(key=lambda x: x["dist_pips"])

    # Assign TP1, TP2, TP3 with minimum distance filters
    tp_levels = []
    sign = 1.0 if d == "BUY" else -1.0

    for lv in beyond:
        if len(tp_levels) >= 3:
            break
        if len(tp_levels) == 0:
            # TP1: enforce minimum distance
            if lv["dist_pips"] < BRIEFING_TP_MIN_TP1_PIPS:
                continue
            tp_levels.append(lv)
        elif len(tp_levels) == 1:
            # TP2: enforce minimum gap from TP1
            gap = lv["dist_pips"] - tp_levels[0]["dist_pips"]
            if gap < BRIEFING_TP_MIN_TP_GAP_PIPS:
                continue
            tp_levels.append(lv)
        else:
            # TP3: prefer major level, enforce min gap from TP2
            gap = lv["dist_pips"] - tp_levels[1]["dist_pips"]
            if gap < BRIEFING_TP_MIN_TP_GAP_PIPS:
                continue
            tp_levels.append(lv)

    # If we didn't find TP3 but have major levels further out, use nearest major
    if len(tp_levels) == 2:
        last_dist = tp_levels[-1]["dist_pips"]
        major_candidates = [lv for lv in beyond
                          if lv["major"] and lv["dist_pips"] > last_dist + BRIEFING_TP_MIN_TP_GAP_PIPS]
        if major_candidates:
            tp_levels.append(major_candidates[0])

    # Fallback: pad with synthetic levels at +20 pip increments
    while len(tp_levels) < 3:
        last_pips = tp_levels[-1]["dist_pips"] if tp_levels else 0
        synth_pips = last_pips + BRIEFING_TP_SYNTH_INCREMENT
        synth_price = entry_price + synth_pips * ppp * sign
        tp_levels.append({"price": synth_price, "dist_pips": synth_pips, "major": False, "source": "synthetic"})

    return {
        "tp1": tp_levels[0]["price"],
        "tp2": tp_levels[1]["price"],
        "tp3": tp_levels[2]["price"],
        "tp1_pips": tp_levels[0]["dist_pips"],
        "tp2_pips": tp_levels[1]["dist_pips"],
        "tp3_pips": tp_levels[2]["dist_pips"],
        "sl_pips": sl_pips,
        "levels_used": tp_levels,
        "fallback": False,
    }


# ============================================================
# MOMENTUM CHECK
# ============================================================
def check_momentum(
    direction: str,
    macd_hist_current: float,
    macd_hist_prev: float,
    candle_bodies: list,
    recent_highs: list,
    recent_lows: list,
) -> str:
    """Evaluate momentum at a TP level. Called at TP1 and TP2.

    Args:
        direction: "BUY" or "SELL".
        macd_hist_current: Current bar MACD histogram value.
        macd_hist_prev: Previous bar MACD histogram value.
        candle_bodies: Last 3 candle bodies as (open, close) tuples.
        recent_highs: Last 2 candle highs.
        recent_lows: Last 2 candle lows.

    Returns:
        "HOLD" if all three conditions YES (continue to next TP).
        "CLOSE" if any two conditions are NO (close position).
    """
    d = str(direction or "").upper()
    conditions_met = 0

    # Condition 1: MACD histogram expanding in trade direction
    try:
        curr = float(macd_hist_current)
        prev = float(macd_hist_prev)
        if d == "BUY":
            # Expanding = current bar larger (more positive) than previous
            macd_expanding = curr > prev
        else:
            # Expanding = current bar more negative than previous
            macd_expanding = curr < prev
        if macd_expanding:
            conditions_met += 1
    except (TypeError, ValueError):
        pass  # Missing data counts as NO

    # Condition 2: At least 2 of last 3 candle bodies closing in trade direction
    try:
        bodies_in_dir = 0
        for o, c in candle_bodies[-3:]:
            if d == "BUY" and float(c) > float(o):
                bodies_in_dir += 1
            elif d == "SELL" and float(c) < float(o):
                bodies_in_dir += 1
        if bodies_in_dir >= 2:
            conditions_met += 1
    except (TypeError, ValueError, IndexError):
        pass

    # Condition 3: Price made new extreme in last 2 candles
    try:
        if d == "BUY":
            # New high: most recent high > previous high
            if len(recent_highs) >= 2 and float(recent_highs[-1]) > float(recent_highs[-2]):
                conditions_met += 1
        else:
            # New low: most recent low < previous low
            if len(recent_lows) >= 2 and float(recent_lows[-1]) < float(recent_lows[-2]):
                conditions_met += 1
    except (TypeError, ValueError, IndexError):
        pass

    # HOLD if all 3 YES, CLOSE if 2+ are NO (i.e. conditions_met <= 1)
    if conditions_met >= 3:
        return "HOLD"
    return "CLOSE"


class TradeManager:
    """
    Canonical wrapper class that delegates to trade_executor and adds live management.

    Methods:
      - open_position(direction, size)
      - close_position(epic)
      - monitor_positions(epic, mid_price, **kwargs)
      - update_trailing_stop(epic, mid_price, **kwargs)
      - handle_partial_exit(epic, mid_price, **kwargs)
    """

    def __init__(self):
        self.state = _exec.TRADE_STATE
        self._last_ig_monitor_ts = 0.0
        self._last_external_close_alerted_deal_id = None

    @property
    def active_trades(self):
        """
        Multi-epic-safe active trade view: {epic: state} if active else {}.
        Falls back to legacy single-state behavior if needed.
        """
        out: Dict[str, Dict[str, Any]] = {}
        try:
            if isinstance(TRADE_STATE_BY_EPIC, dict) and TRADE_STATE_BY_EPIC:
                for epic, st in TRADE_STATE_BY_EPIC.items():
                    if isinstance(st, dict) and st.get("active"):
                        out[str(epic)] = st
                if out:
                    return out
        except Exception:
            pass

        try:
            if self.state.get("active"):
                epic = self.state.get("epic") or "UNKNOWN"
                return {str(epic): self.state}
        except Exception:
            pass
        return {}

    def open_position(self, direction, size):
        raise NotImplementedError(
            "TradeManager.open_position() requires a StrategyDecision + epic in this bot. "
            "Use trade_executor.execute_trade(decision, epic)."
        )

    def close_position(self, epic):
        st = _state_for_epic(epic)
        if not st.get("active"):
            return None
        return _exec.close_position(
            epic=str(epic),
            reason="manual close (TradeManager)",
            exit_hint_price=st.get("last_mid") or st.get("exit_price") or st.get("entry_price"),
        )

    def monitor_positions(self, epic, mid_price, **kwargs):
        """
        Called on each tick by the orchestrator.

        Iterates ALL active positions for this epic (multiple strategies can
        hold simultaneous positions on the same instrument).

        Per position:
        1) Delegates low-level tick management to executor.
        2) Applies manager-side profit protection.
        3) Applies higher-level LIQUIDITY_SWEEP live trade management.
        4) Periodically polls IG open positions for external close detection.

        Supported kwargs (all optional, native IG units unless noted):
          bid, ask
          upper_band / lower_band (or bb_upper / bb_lower / boll_upper / boll_lower)
          macd_hist, prev_macd_hist
          sweep_extreme
        """
        epic = str(epic or "").strip()
        if not epic:
            return None

        mid = _safe_float(mid_price, None)
        if mid is None:
            return None

        bid = kwargs.get("bid")
        ask = kwargs.get("ask")

        # Get all active positions for this epic (may be multiple strategies)
        active_positions = _exec.get_all_positions_for_epic(epic)

        out = None
        for pk, _pos_st in active_positions:
            try:
                out = self._monitor_single_position(pk, epic, mid, bid, ask, kwargs)
            except Exception as e:
                logger.error(f"[TRADE_MANAGER] monitor error {pk}: {type(e).__name__}: {e}")

        # Also update last_mid for any non-active state (so new opens get a price)
        if not active_positions:
            # No active positions — just update executor state for the epic
            try:
                _exec.update_trade_state(
                    epic=epic,
                    mid_price=float(mid),
                    bid=bid,
                    ask=ask,
                    upper_band=kwargs.get("upper_band", kwargs.get("bb_upper", kwargs.get("boll_upper"))),
                    lower_band=kwargs.get("lower_band", kwargs.get("bb_lower", kwargs.get("boll_lower"))),
                )
            except Exception:
                pass

        # 4) IG monitoring on a timer (don't hammer IG).
        # Refactor (2026-05-08): when LS_ASYNC_DISPATCH=1 the rest_sweeps
        # daemon owns this cadence; we suppress the inline call so the
        # sweep runs on its own thread instead of piggybacking the LS
        # callback. The inline path is preserved as the rollback path.
        if not _LS_ASYNC_DISPATCH:
            now = time.time()
            if (now - self._last_ig_monitor_ts) >= float(IG_MONITOR_EVERY_S):
                self._last_ig_monitor_ts = now
                try:
                    self._check_ig_open_positions_for_external_close()
                except Exception as e:
                    logger.error(f"[TRADE_MANAGER] IG monitor error: {type(e).__name__}: {e}")
                # Piggyback the naked-foreign-position sweep on the same
                # cadence — /positions is already fetched by the block
                # above, and the marginal cost is one Python dict scan.
                try:
                    self._check_foreign_naked_positions()
                except Exception as e:
                    logger.error(f"[FOREIGN_ALERT] inline sweep error: {type(e).__name__}: {e}")

        return out

    def run_external_close_sweep(self) -> None:
        """Public entry point for the rest_sweeps daemon to drive the
        external-close sweep on its own cadence. Body delegates to the
        existing internal method; safe to call concurrently with
        monitor_positions (the cadence flag is the only shared state).

        As of 2026-08-03 this also drives the naked-foreign-position
        sweep, on the same cadence and the same /positions payload
        (get_open_positions is called independently inside each check —
        the marginal cost is one extra REST hit every IG_MONITOR_EVERY_S)."""
        try:
            self._check_ig_open_positions_for_external_close()
        except Exception as e:
            logger.error(
                f"[TRADE_MANAGER] external-close sweep error: {type(e).__name__}: {e}"
            )
        try:
            self._check_foreign_naked_positions()
        except Exception as e:
            logger.error(
                f"[FOREIGN_ALERT] sweep error: {type(e).__name__}: {e}"
            )
        # Occupancy lifecycle repair (DEFECT-2026-09-18-A):
        # Reconcile local occupancy stores with IG-authoritative
        # open-position set on the same cadence as external-close.
        # Cheap: both reconcilers are no-ops when everything is in sync.
        # SKIP_BROKER_UNKNOWN receipt on IG unavailability.
        try:
            self._reconcile_occupancy_with_ig()
        except Exception as e:
            logger.error(
                f"[RECONCILE-OCCUPANCY] sweep error: {type(e).__name__}: {e}"
            )

    def _reconcile_occupancy_with_ig(self) -> None:
        """Occupancy lifecycle repair (DEFECT-2026-09-18-A) — periodic
        authoritative reconciliation.

        When IG is reachable, its open-positions payload is authoritative:
          * `trade_executor.reconcile_epic_state_with_broker(deal_ids)`
            clears any active=True / pending_open=True EPIC_STATE entry
            whose deal_id is not currently open at IG.
          * `central_execution_gate.reconcile_reservations_with_broker(deal_ids)`
            drops any occupied reservation whose deal_id is not open.

        When IG is unavailable (get_open_positions raised OR returned
        None), both reconcilers are invoked with `open_deal_ids=None`
        which returns a SKIP_BROKER_UNKNOWN receipt without mutating
        state — the bounded conservative fallback. An empty list [] is
        treated as "IG has zero opens" ONLY when the fetch was
        successful. This satisfies the operator requirement:
        "Never interpret an empty result caused by an API error as
        'no open positions.'"

        Never logs credentials or full broker payloads — only deal IDs
        and counts. Idempotent; safe to call every sweep.
        """
        import central_execution_gate as _gate
        import trade_executor as _te

        # Rev.3 §1 — snapshot-safety: capture eligible deal_ids BEFORE
        # requesting IG so reconciliation cannot remove positions
        # confirmed after the broker snapshot was requested.
        eligible_epic_state = _te.snapshot_active_deal_ids()
        eligible_reservations = _gate.snapshot_occupied_reservation_deal_ids()

        # Rev.3 §2 — orphan sweep: bounded lifecycle for active-but-no-
        # deal_id entries. Runs every reconciliation cycle. Grace is
        # generous (60s) so a legitimate create-then-attach window is
        # never affected.
        try:
            _te.sweep_orphan_active_no_deal()
        except Exception as exc:
            logger.warning(
                "[RECONCILE-OCCUPANCY] orphan sweep failed: %s: %s",
                type(exc).__name__, exc,
            )

        broker_ok = True
        open_pos = None
        try:
            open_pos = get_open_positions()
        except Exception as exc:
            broker_ok = False
            logger.warning(
                "[RECONCILE-OCCUPANCY] get_open_positions raised %s: %s "
                "(applying bounded fallback: SKIP_BROKER_UNKNOWN)",
                type(exc).__name__, exc,
            )
        if not broker_ok or open_pos is None:
            _te.reconcile_epic_state_with_broker(None)
            _gate.reconcile_reservations_with_broker(None)
            return
        items = _extract_positions_list(open_pos)
        open_deal_ids: List[str] = []
        for it in items:
            try:
                pos_block = it.get("position") if isinstance(it, dict) else None
                if isinstance(pos_block, dict):
                    did = str(pos_block.get("dealId") or "").strip()
                else:
                    did = str(it.get("dealId") or "").strip() if isinstance(it, dict) else ""
                if did:
                    open_deal_ids.append(did)
            except Exception:
                continue
        r_exec = _te.reconcile_epic_state_with_broker(
            open_deal_ids,
            eligible_deal_ids=eligible_epic_state,
        )
        r_gate = _gate.reconcile_reservations_with_broker(
            open_deal_ids,
            eligible_deal_ids=eligible_reservations,
        )
        if r_exec.get("cleared_pos_keys") or r_gate.get("removed_reservation_ids"):
            logger.info(
                "[RECONCILE-OCCUPANCY] repaired local state: "
                "epic_state_cleared=%d reservations_cleared=%d broker_open=%d "
                "epic_preserved_post_snapshot=%d res_preserved_post_snapshot=%d",
                len(r_exec.get("cleared_pos_keys") or []),
                len(r_gate.get("removed_reservation_ids") or []),
                len(open_deal_ids),
                len(r_exec.get("preserved_post_snapshot_deal_ids") or []),
                len(r_gate.get("preserved_post_snapshot_deal_ids") or []),
            )

    def _monitor_single_position(self, pk, epic, mid, bid, ask, kwargs):
        """Monitor a single position identified by pos_key."""
        # 1) executor update
        out = _exec.update_trade_state(
            epic=pk,
            mid_price=float(mid),
            bid=bid,
            ask=ask,
            upper_band=kwargs.get("upper_band", kwargs.get("bb_upper", kwargs.get("boll_upper"))),
            lower_band=kwargs.get("lower_band", kwargs.get("bb_lower", kwargs.get("boll_lower"))),
        )

        st = _state_for_epic(pk)

        try:
            st["last_mid"] = float(mid)
        except Exception:
            pass

        # Stamp bid / offer on the per-position state so the amend
        # preflight can validate a proposed stop against the correct
        # side (BUY→bid, SELL→offer). Landed 2026-09-14 review; the
        # streamer already carries bid+ask, autobot passes them through
        # monitor_positions, and _monitor_single_position receives them
        # here — but until this write the values never reached the
        # per-position state and the preflight had no authoritative side
        # to consult.
        try:
            if bid is not None:
                _bid_f = _safe_float(bid, None)
                if _bid_f is not None:
                    st["last_bid"] = float(_bid_f)
            if ask is not None:
                _ask_f = _safe_float(ask, None)
                if _ask_f is not None:
                    st["last_ask"] = float(_ask_f)
        except Exception:
            pass

        if not st.get("active"):
            self._clear_profit_meta(pk)
            self._clear_sweep_meta(pk)
            self._clear_consolidation_meta(pk)
            self._clear_briefing_tp_meta(pk)
            self._clear_bb_range_scalp_meta(pk)
        else:
            _dir = str(st.get("direction") or "").upper()
            if _dir in ("BUY", "SELL"):
                _update_consolidation_state(pk, _dir, float(mid))

                # ──────────────────────────────────────────────────────
                # Structure-exit hook (Piece 3, 2026-05-29). Close on
                # opposite-structure break (5M close beyond prior-N-bar
                # extreme against the position). Default ON per replay
                # (+115.9p across 27 losing trades).
                # Toggle via STRUCTURE_EXIT_ENABLED. Pure read of the 5M
                # builder; never raises (fail-open on any error).
                #
                # 2026-06-05: SKIP this hook when (scaled_out AND
                # be_amend_ok). On a scaled runner with confirmed broker BE,
                # structure_exit closing at -10p mid would close BELOW entry
                # — the exact bug that bit 06-03 06:30 (-10.5p exit on a
                # runner whose broker SL was supposed to be at entry). The
                # single SL path for a scaled-and-BE-confirmed runner is the
                # broker SL: scale_out's BE move plus the bb_bounce trail
                # ratchet sitting above it. If be_amend_ok is False (amend
                # didn't confirm), KEEP structure_exit available — it's a
                # better safety net at -10p than the original 20p stop.
                # ──────────────────────────────────────────────────────
                try:
                    # Read scale-out state from BOTH st AND _PROFIT_MGMT_BY_EPIC.
                    # After restart, reconcile_open_positions rebuilds st from IG
                    # (which doesn't carry scaled_out); _PROFIT_MGMT_BY_EPIC is
                    # restored from disk by restore_profit_state_for_active_trades
                    # and IS the authoritative scale-out / BE-amend record.
                    _se_meta = _PROFIT_MGMT_BY_EPIC.get(pk) or {}
                    _scaled_ok = (
                        (bool(st.get("scaled_out")) or bool(_se_meta.get("scaled_out")))
                        and
                        (bool(st.get("be_amend_ok")) or bool(_se_meta.get("be_amend_ok")))
                    )
                    # PIVOT_BREAK: structure_exit is the SPECIFIED runner
                    # trail (structure_exit.py:58), not a bypass — it must
                    # run post-scale with a 3-bar lookback via
                    # PIVOT_BREAK_STRUCTURE_LOOKBACK_BARS. The default
                    # _scaled_ok short-circuit assumes a broker BE +
                    # peak-pivot trail is authoritative; PIVOT_BREAK's
                    # contract is different, so override.
                    _pb_mode = str(st.get("mode") or "").upper() in _PIVOT_BREAK_TRAIL_MODES
                    if _scaled_ok and not _pb_mode:
                        pass  # broker BE + trail are authoritative on this runner
                    else:
                        import structure_exit as _se
                        _entry_px = float(st.get("entry_price") or st.get("entry") or 0.0)
                        _se_mode = str(st.get("mode") or "").strip().upper()
                        # Stage 12 ONE_STRATEGY — HOLD-oriented management is
                        # authoritative for FAMILY_ONE_STRATEGY positions.
                        # structure_exit is a legacy interpretive close whose
                        # heuristic (last close beyond N-bar swing) recreates a
                        # second directional decision downstream of Stage 9 and
                        # can prematurely exit a valid HOLD. The one_strategy_
                        # management module and the mechanical broker SL are
                        # the ONLY authorised exit paths for ONE_STRATEGY.
                        # Runs BEFORE every other short-circuit so no gate
                        # env-flip can re-enable structure_exit on ONE_STRATEGY.
                        if _se_mode == "ONE_STRATEGY":
                            _log_structure_skip_once(
                                pk, "ONE_STRATEGY",
                                "[ONE_STRATEGY] STRUCTURE_EXIT skipped mode=%s "
                                "— HOLD-oriented management is authoritative "
                                "(exits only on later opposite Stage 9 event "
                                "or broker SL)",
                                _se_mode,
                            )
                            _entry_px = 0.0  # short-circuits the block below
                        # LEVEL_BOUNCE — unmanaged by design. Unconditional
                        # short-circuit: does NOT read STRUCTURE_EXIT_EXEMPT_
                        # BB_BOUNCE. Runs BEFORE the BB_BOUNCE-family gate
                        # so a future flip of that env can't accidentally
                        # re-enable structure_exit on LEVEL_BOUNCE. See
                        # _LEVEL_BOUNCE_MODES declaration (:328).
                        elif _se_mode in _LEVEL_BOUNCE_MODES:
                            _log_structure_skip_once(
                                pk, "LEVEL_BOUNCE",
                                "[LEVEL_BOUNCE] STRUCTURE_EXIT skipped mode=%s "
                                "— unmanaged (100p SL is sole exit)",
                                _se_mode,
                            )
                            _entry_px = 0.0  # short-circuits the block below
                        # 2026-08-14 TREND_V3 UM — mirror the LEVEL_BOUNCE
                        # unconditional short-circuit. Unmanaged by design;
                        # 12p SL / 100p TP is the whole risk model until
                        # TREND_V3_UM_EOD_CLOSE fires. Structure_exit here
                        # would defeat the point of the variant.
                        elif _se_mode in _TREND_V3_UM_MODES:
                            _log_structure_skip_once(
                                pk, "TREND_V3_UM",
                                "[TREND_V3_UM] STRUCTURE_EXIT skipped mode=%s "
                                "— unmanaged (12p SL / 100p TP / EOD close)",
                                _se_mode,
                            )
                            _entry_px = 0.0  # short-circuits the block below
                        # 2026-08-15 range-mode BB flip mode — unconditional
                        # short-circuit that runs BEFORE the BB_BOUNCE-family
                        # env gate below. Belt-and-braces so a flip of
                        # STRUCTURE_EXIT_EXEMPT_BB_BOUNCE=0 cannot re-enable
                        # structure_exit on a range-mode BB position.
                        elif bool(_se_meta.get("range_mode_flip")):
                            _log_structure_skip_once(
                                pk, "BB-FLIP",
                                "[BB-FLIP] STRUCTURE_EXIT skipped mode=%s "
                                "range_mode_flip=True — sole exits "
                                "BB_RANGE_TARGET/BB_FLIP/broker/NY_CLOSE",
                                _se_mode,
                            )
                            _entry_px = 0.0  # short-circuits the block below
                        # BB_BOUNCE per-mode exempt (2026-06-25, Johnny's
                        # directive). Counter-trend fade — let it run to
                        # its own SL/TP; structure-flips are noise here.
                        elif (
                            STRUCTURE_EXIT_EXEMPT_BB_BOUNCE
                            and _se_mode in _STRUCTURE_EXIT_EXEMPT_MODES
                        ):
                            _log_structure_skip_once(
                                pk, "BB_FREED",
                                "[BB_FREED] STRUCTURE_EXIT skipped mode=%s — exempt",
                                _se_mode,
                            )
                            _entry_px = 0.0  # short-circuits the block below
                        if _entry_px > 0.0:
                            _sym_se = _pair_from_epic(epic)
                            # With-trend suppress (kill-switched, default OFF).
                            # Fail-open: any error / unknown regime / cache miss
                            # → _wt_skip stays False so structure_exit runs.
                            _wt_skip = False
                            if STRUCTURE_EXIT_WITH_TREND_SUPPRESS_ENABLED:
                                try:
                                    import regime_engine as _re
                                    _live = _re.latest_result(_sym_se)
                                    _wreg = str((_live or {}).get("winning_regime") or "").upper()
                                    if _wreg:
                                        if _dir == "BUY" and _wreg in _STRUCTURE_EXIT_WT_LONG_REGIMES:
                                            _wt_skip = True
                                        elif _dir == "SELL" and _wreg in _STRUCTURE_EXIT_WT_SHORT_REGIMES:
                                            _wt_skip = True
                                    if _wt_skip:
                                        logger.info(
                                            "[STRUCTURE-EXIT] with-trend suppress: %s dir=%s regime=%s",
                                            pk, _dir, _wreg,
                                        )
                                except Exception as _wt_exc:
                                    logger.debug(
                                        "[STRUCTURE-EXIT] with-trend suppress probe error (fail-open): %s",
                                        _wt_exc,
                                    )
                                    _wt_skip = False
                            if not _wt_skip:
                                if _pb_mode:
                                    # PIVOT_BREAK uses a shorter (3-bar)
                                    # structural window than the default
                                    # 5. Mirrors structure_exit's swing
                                    # detector logic on the same 5M bars,
                                    # differing only in lookback.
                                    _should_close, _se_reason = (
                                        _pivot_break_should_exit_structure(
                                            symbol=_sym_se,
                                            direction=_dir,
                                            current_price=float(mid),
                                        )
                                    )
                                else:
                                    _should_close, _se_reason = _se.should_exit_structure(
                                        symbol=_sym_se,
                                        direction=_dir,
                                        entry_price=_entry_px,
                                        current_price=float(mid),
                                        pip_size=1.0,
                                    )
                                if _should_close:
                                    logger.info(
                                        "[STRUCTURE-EXIT] closing %s: %s",
                                        pk, _se_reason,
                                    )
                                    _exec.close_position(
                                        epic=pk,
                                        reason=f"STRUCTURE_EXIT:{_se_reason}",
                                        exit_hint_price=float(mid),
                                    )
                                    return out
                except Exception as _se_exc:
                    logger.debug("[STRUCTURE-EXIT] hook error (fail-open): %s", _se_exc)

                try:
                    self._monitor_profit_protection(
                        epic=pk,
                        mid_price=float(mid),
                        bid=bid,
                        ask=ask,
                    )
                except Exception as e:
                    logger.error(f"[TRADE_MANAGER] profit monitor error {pk}: {type(e).__name__}: {e}")

                st = _state_for_epic(pk)

                # ── Phase 2B Increment 2 measurement hook ─────────────
                # Behaviour-neutral ownership snapshot + STRUCTURE_EXIT
                # counterfactual shadow. OFF-gated by
                # PHASE2B_MEASUREMENT_ENABLED (default 0). The adapter
                # itself is fail-silent and never mutates production
                # state; this env check keeps the OFF path a single
                # dict lookup so per-tick overhead is negligible.
                if os.getenv("PHASE2B_MEASUREMENT_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
                    try:
                        from phase2b_inc2_ownership_adapter import emit_snapshot_if_new_bar as _p2b_inc2_emit
                        _p2b_inc2_emit(pk=pk, epic=epic, st=st, bid=bid, ask=ask, mid=float(mid))
                    except Exception:
                        pass  # fail-silent per measurement_writer contract
                # ──────────────────────────────────────────────────────

                # Phase 3 collision guard 5.4: profile-managed positions
                # own the TP path (STRONG runs a trail with preserved TP,
                # FORMING climbs its own ladder). Skip the briefing-TP
                # multiplex here so a fire that carries BOTH a briefing
                # plan and a profile stamp does not double-manage. Would
                # be a no-op in practice today (profile-managed fires
                # never set up a briefing plan), but the guard is cheap
                # insurance and satisfies the mutual-exclusion contract.
                _profile_id_btp = str(st.get("profile_id") or "").upper()
                _btp_profile_gated = (
                    _REGIME_MGMT_ENABLED_TM
                    and _profile_id_btp in _PROFILE_MANAGED
                )
                if st.get("active") and pk in _BRIEFING_TP_BY_EPIC \
                        and not _btp_profile_gated:
                    try:
                        self._monitor_briefing_tp(
                            epic=pk,
                            mid_price=float(mid),
                            bid=bid,
                            ask=ask,
                            macd_hist=kwargs.get("macd_hist"),
                            prev_macd_hist=kwargs.get("prev_macd_hist"),
                            candle_bodies=kwargs.get("candle_bodies"),
                            recent_highs=kwargs.get("recent_highs"),
                            recent_lows=kwargs.get("recent_lows"),
                            news_blackout=bool(kwargs.get("news_blackout", False)),
                            df_5m=kwargs.get("df_5m"),
                        )
                    except Exception as e:
                        logger.error(f"[TRADE_MANAGER] briefing TP error {pk}: {type(e).__name__}: {e}")

                # RANGE_ROTATION BB_BOUNCE single-exit scalp — close at
                # market if the range premise ends (winning_regime
                # leaves RANGE_ROTATION). No tier plan is attached for
                # these trades; broker LIMIT at the opposite band is
                # the only other exit besides SL.
                if st.get("active") and pk in _BB_RANGE_SCALP_BY_EPIC:
                    try:
                        self._monitor_bb_range_scalp(
                            epic=pk,
                            mid_price=float(mid),
                        )
                    except Exception as e:
                        logger.error(
                            f"[TRADE_MANAGER] bb range-scalp monitor error "
                            f"{pk}: {type(e).__name__}: {e}"
                        )

                st = _state_for_epic(pk)

                if st.get("active") and _is_liquidity_sweep_mode(st.get("mode")):
                    try:
                        self._monitor_liquidity_sweep(
                            epic=pk,
                            mid_price=float(mid),
                            bid=bid,
                            ask=ask,
                            macd_hist=kwargs.get("macd_hist"),
                            prev_macd_hist=kwargs.get("prev_macd_hist"),
                            sweep_extreme=kwargs.get("sweep_extreme"),
                        )
                    except Exception as e:
                        logger.error(f"[TRADE_MANAGER] sweep monitor error {pk}: {type(e).__name__}: {e}")

                st = _state_for_epic(pk)

        return out

    # --------------------------------------------------------
    # Post-TP1 continuation: hold past TP1, close on reversal
    # --------------------------------------------------------
    def _monitor_post_tp1(
        self,
        epic: str,
        mid_price: float,
        st: Dict[str, Any],
    ) -> None:
        """Detect TP1 breach and manage continuation.

        Before TP1: do nothing (IG SL handles downside, no IG limit set).
        At TP1: enter continuation mode, track post-TP1 peak.
        After TP1: close on reversal candle, below-TP1 drop, or max retrace.
        """
        entry = _safe_float(st.get("entry_price"), None)
        direction = str(st.get("direction") or "").upper()
        tp1_pips = _safe_float(st.get("tp"), 0) or 0

        if not entry or not direction or tp1_pips <= 0:
            return

        pair = _pair_from_epic(epic)
        ppp = _ppp(pair)

        if direction == "BUY":
            pnl_pips = (mid_price - entry) / ppp
        else:
            pnl_pips = (entry - mid_price) / ppp

        if not st.get("_post_tp1_active"):
            # Activate on pnl >= TP1 (live: tick-level, so this is close to candle-close)
            if pnl_pips < tp1_pips:
                return
            st["_post_tp1_active"] = True
            st["_post_tp1_peak_pips"] = pnl_pips
            st["_post_tp1_prev_mid"] = mid_price
            logger.info(
                "[TRADE_MANAGER] %s TP1 reached (%.1f pips) — continuation watch active",
                epic, pnl_pips,
            )
            return

        # --- Continuation mode active ---
        peak = _safe_float(st.get("_post_tp1_peak_pips"), pnl_pips)
        if pnl_pips > peak:
            st["_post_tp1_peak_pips"] = pnl_pips
            peak = pnl_pips

        # Exit 1: price drops 5 pips below TP1 — close at TP1 level (don't give back)
        if pnl_pips < tp1_pips - 5.0:
            tp1_price = entry + tp1_pips * ppp if direction == "BUY" else entry - tp1_pips * ppp
            logger.info(
                "[TRADE_MANAGER] %s post-TP1 dropped 5p below TP1 (pnl=%.1f < %.1f) — closing at TP1",
                epic, pnl_pips, tp1_pips - 5.0,
            )
            _exec.close_position(epic=epic, reason="POST_TP1_BELOW_TP1", exit_hint_price=tp1_price)
            return

        # Exit condition 2: retrace from post-TP1 peak exceeds max
        retrace = peak - pnl_pips
        if retrace >= POST_TP1_MAX_RETRACE_PIPS:
            logger.info(
                "[TRADE_MANAGER] %s post-TP1 retrace %.1f pips from peak %.1f — closing",
                epic, retrace, peak,
            )
            _exec.close_position(epic=epic, reason="POST_TP1_MAX_RETRACE", exit_hint_price=mid_price)
            return

        # Exit condition 3: aggressive reversal candle
        # Check on 5M candle closes — we detect this via significant mid-price jumps
        # that represent a full candle body in the opposing direction.
        prev_mid = _safe_float(st.get("_post_tp1_prev_mid"), mid_price)
        candle_body_pips = abs(mid_price - prev_mid) / ppp

        if candle_body_pips >= POST_TP1_REVERSAL_BODY_PIPS:
            # Check if the move is in the opposing direction
            if direction == "BUY" and mid_price < prev_mid:
                logger.info(
                    "[TRADE_MANAGER] %s post-TP1 reversal candle (body=%.1f pips, SELL) — closing",
                    epic, candle_body_pips,
                )
                _exec.close_position(epic=epic, reason="POST_TP1_REVERSAL", exit_hint_price=mid_price)
                return
            elif direction == "SELL" and mid_price > prev_mid:
                logger.info(
                    "[TRADE_MANAGER] %s post-TP1 reversal candle (body=%.1f pips, BUY) — closing",
                    epic, candle_body_pips,
                )
                _exec.close_position(epic=epic, reason="POST_TP1_REVERSAL", exit_hint_price=mid_price)
                return

        st["_post_tp1_prev_mid"] = mid_price

    # --------------------------------------------------------
    # Briefing-level TP management
    # --------------------------------------------------------
    def setup_briefing_tp(
        self,
        epic: str,
        entry_price: float,
        direction: str,
        briefing_levels: list,
        pair: str = "GBPUSD",
        bb_reversal_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Called at trade open to configure TP1/TP2/TP3 from briefing levels.

        Stores TP plan in _BRIEFING_TP_BY_EPIC and returns the plan dict.

        bb_reversal_mode: "RANGING" or "TRENDING" — only consulted when the
        position's mode is BB_REVERSAL. RANGING preserves the existing
        early-return single-TP behaviour; TRENDING enables momentum-gated
        TP1→TP2→TP3 progression in _monitor_bb_reversal_trending.
        """
        tp_plan = select_tp_levels(entry_price, direction, briefing_levels, pair)
        ppp = _ppp(pair)
        _bb_mode_norm = (str(bb_reversal_mode).upper() if bb_reversal_mode else "RANGING")
        if _bb_mode_norm not in ("RANGING", "TRENDING"):
            _bb_mode_norm = "RANGING"
        _BRIEFING_TP_BY_EPIC[epic] = {
            "entry_price": float(entry_price),
            "direction": str(direction).upper(),
            "pair": pair,
            "tp1": tp_plan["tp1"],
            "tp2": tp_plan["tp2"],
            "tp3": tp_plan["tp3"],
            "tp1_pips": tp_plan["tp1_pips"],
            "tp2_pips": tp_plan["tp2_pips"],
            "tp3_pips": tp_plan["tp3_pips"],
            "sl_pips": tp_plan["sl_pips"],
            "levels_used": tp_plan["levels_used"],
            "fallback": tp_plan["fallback"],
            "current_phase": "OPEN",  # OPEN → TP1_PASSED → TP2_PASSED → TP3_HIT → CLOSED
            "sl_price": (entry_price - tp_plan["sl_pips"] * ppp) if direction.upper() == "BUY"
                        else (entry_price + tp_plan["sl_pips"] * ppp),
            "swing_extreme": float(entry_price),  # Tracks best price for pullback trail
            "bb_reversal_mode": _bb_mode_norm,
        }
        logger.info(
            "[BRIEFING_TP] %s setup: TP1=%.1f (%.1fp) TP2=%.1f (%.1fp) TP3=%.1f (%.1fp) SL=%.1fp%s",
            epic, tp_plan["tp1"], tp_plan["tp1_pips"],
            tp_plan["tp2"], tp_plan["tp2_pips"],
            tp_plan["tp3"], tp_plan["tp3_pips"],
            tp_plan["sl_pips"], " [fallback]" if tp_plan["fallback"] else "",
        )
        return tp_plan

    def _monitor_briefing_tp(
        self,
        epic: str,
        mid_price: float,
        bid: Any = None,
        ask: Any = None,
        macd_hist: Any = None,
        prev_macd_hist: Any = None,
        candle_bodies: Optional[list] = None,
        recent_highs: Optional[list] = None,
        recent_lows: Optional[list] = None,
        news_blackout: bool = False,
        df_5m: Any = None,
    ) -> None:
        """Monitor trade against briefing-level TP1/TP2/TP3 targets.

        Called each tick from monitor_positions for BRIEFING_LIQUIDITY trades
        that have a briefing TP plan configured via setup_briefing_tp().
        """
        meta = _BRIEFING_TP_BY_EPIC.get(epic)
        if meta is None:
            return

        st = _state_for_epic(epic)
        if not st.get("active"):
            self._clear_briefing_tp_meta(epic)
            return

        direction = meta["direction"]
        entry = meta["entry_price"]
        pair = meta["pair"]
        ppp = _ppp(pair)

        current = _effective_price_for_management(direction, float(mid_price), bid=bid, ask=ask)
        pnl_pips = _calculate_pnl_pips(direction, entry, current, ppp)
        phase = meta["current_phase"]

        # Update swing extreme for pullback trail
        if direction == "BUY":
            if current > meta["swing_extreme"]:
                meta["swing_extreme"] = current
        else:
            if current < meta["swing_extreme"]:
                meta["swing_extreme"] = current

        # --- News blackout handling ---
        if news_blackout and phase != "CLOSED":
            tp1_dist = meta["tp1_pips"]
            if pnl_pips > 0:
                reason = "NEWS_BLACKOUT_PROFIT"
                logger.info("[BRIEFING_TP] %s news blackout — closing in profit (%.1fp)", epic, pnl_pips)
                _close_trade_best_effort(epic, reason, current)
                self._clear_briefing_tp_meta(epic)
                try:
                    import telegram_alerts
                    telegram_alerts.send_status_update(
                        f"📰 {pair} closed @ news blackout — +{pnl_pips:.1f}p"
                    )
                except Exception:
                    pass
                return
            else:
                # Negative profit — let SL handle it
                return

        # --- BB_REVERSAL: mode-aware split.
        # RANGING: broker holds SL/TP; no software progression.
        # TRENDING: broker limit sits at TP3 so the position stays alive past
        #   TP1/TP2 for software momentum gating. Delegate to the dedicated
        #   handler which reuses check_momentum() unchanged.
        # Note: v4 BB_REVERSAL never sets bb_reversal_mode and does not call
        #   setup_briefing_tp, so neither branch fires for v4 legs.
        trade_mode_early = str(_state_for_epic(epic).get("mode") or "").strip().upper()
        if trade_mode_early == "BB_REVERSAL":
            bb_mode = str(meta.get("bb_reversal_mode", "RANGING")).upper()
            if bb_mode == "RANGING":
                return
            self._monitor_bb_reversal_trending(
                epic=epic, meta=meta, st=st,
                current=current, direction=direction, entry=entry, pair=pair, ppp=ppp,
                pnl_pips=pnl_pips, df_5m=df_5m,
                macd_hist=macd_hist, prev_macd_hist=prev_macd_hist,
                candle_bodies=candle_bodies, recent_highs=recent_highs, recent_lows=recent_lows,
            )
            return

        # --- SL check (software SL for the managed level) ---
        sl_price = meta.get("sl_price")
        if sl_price is not None:
            sl_hit = (direction == "BUY" and current <= sl_price) or \
                     (direction == "SELL" and current >= sl_price)
            if sl_hit:
                # 2026-07-28: derive close_reason from the position's mode so
                # BB_BOUNCE / BB_REV_PAT / EMA_PULLBACK / CONFIRMATION_FALLBACK
                # fills that delegate to the tier machinery no longer inherit
                # briefing-execution vocabulary. BRIEFING_EXECUTION positions
                # keep `BRIEFING_TP_SL_{phase}` for downstream compat
                # (trades_api._classify_exit_type at :1058). Non-briefing
                # positions emit `{MODE}_TIER_SL_{phase}` — same TP/SL
                # disambiguation via pnl sign, but attributes the close to
                # the strategy that owns the position.
                _mode_for_label = (
                    _exec._mode_from_pos_key(epic) if "|" in str(epic) else "DEFAULT"
                )
                if _is_briefing_exec_mode(_mode_for_label):
                    _close_reason = f"BRIEFING_TP_SL_{phase}"
                else:
                    _close_reason = f"{_mode_for_label}_TIER_SL_{phase}"
                logger.info("[BRIEFING_TP] %s SL hit @ %.1f (phase=%s, pnl=%.1fp, reason=%s)",
                            epic, current, phase, pnl_pips, _close_reason)
                _close_trade_best_effort(epic, _close_reason, current)
                self._clear_briefing_tp_meta(epic)
                return

        # --- Pullback trail between levels ---
        if phase in ("TP1", "TP2"):
            swing = meta["swing_extreme"]
            if direction == "BUY":
                pullback = (swing - current) / ppp
            else:
                pullback = (current - swing) / ppp
            if pullback >= BRIEFING_TP_PULLBACK_PIPS:
                lock_pips = pnl_pips
                logger.info("[BRIEFING_TP] %s pullback trail hit (%.1fp from swing) — locking +%.1fp",
                            epic, pullback, lock_pips)
                _close_trade_best_effort(epic, f"BRIEFING_TP_PULLBACK_{phase}", current)
                self._clear_briefing_tp_meta(epic)
                try:
                    import telegram_alerts
                    telegram_alerts.send_status_update(
                        f"📉 {pair} pullback trail — closed +{lock_pips:.1f}p (retraced {pullback:.0f}p from swing)"
                    )
                except Exception:
                    pass
                return

        # --- Determine trade mode for TP handling ---
        trade_mode = str(st.get("mode") or "").strip().upper()
        _trade_reason = str(st.get("reason") or "").lower()

        # WINDOW_SWEEP morning = scalp with fixed TP/SL on IG, no trail, no time limit.
        _ws_morning = trade_mode == "WINDOW_SWEEP" and "morning" in _trade_reason
        if _ws_morning:
            return  # IG handles TP and SL — no trail, no BE, no max hold

        _use_trail_after_tp1 = trade_mode in _TRAIL_AFTER_TP1_MODES

        # --- WINDOW_SWEEP pre-news close ---
        if trade_mode == "WINDOW_SWEEP" and WINDOW_SWEEP_CLOSE_PRE_NEWS:
            try:
                from news_blackout import is_news_blackout as _ws_news_check
                from datetime import datetime as _dt, timezone as _tz
                _ws_in_blackout, _ws_reason = _ws_news_check(_dt.now(_tz.utc))
                if _ws_in_blackout:
                    logger.info(
                        "[WINDOW_SWEEP] %s pre-news close: %s (pnl=%.1fp)",
                        epic, _ws_reason, pnl_pips,
                    )
                    _close_trade_best_effort(epic, "WINDOW_SWEEP_PRE_NEWS", current)
                    self._clear_briefing_tp_meta(epic)
                    try:
                        import telegram_alerts
                        telegram_alerts.send_status_update(
                            f"\U0001f4f0 {pair} WINDOW_SWEEP closed pre-news ({pnl_pips:+.1f}p) — {_ws_reason}"
                        )
                    except Exception:
                        pass
                    return
            except Exception as e:
                logger.debug("[WINDOW_SWEEP] pre-news check error: %s", e)

        # --- TP level checks ---
        tp1_hit = (direction == "BUY" and current >= meta["tp1"]) or \
                  (direction == "SELL" and current <= meta["tp1"])

        # Sanity guard: TP1 cannot be hit while PnL is negative. If this fires,
        # meta["tp1"] is on the wrong side of entry (stored incorrectly).
        # Log and neutralise the flag so normal management runs instead.
        if tp1_hit and pnl_pips < 0:
            logger.error(
                "[BRIEFING_TP] %s TP1 sanity guard: tp1_hit=True but PnL=%+.1fp "
                "(direction=%s entry=%.1f current=%.1f tp1=%.1f) — ignoring TP1, "
                "falling through to normal management",
                epic, pnl_pips, direction, entry, current, meta["tp1"],
            )
            tp1_hit = False

        # =====================================================================
        # TRAILING STOP AFTER TP1 (BRIEFING_SWEEP + WINDOW_SWEEP)
        # Once TP1 is reached, arm a trailing stop at TRAIL_AFTER_TP1_PIPS
        # behind the best price. Close when price retraces that distance.
        # =====================================================================
        if _use_trail_after_tp1:
            trail_armed = bool(meta.get("_tp1_trail_armed"))

            if trail_armed:
                # Trail is active — update best price and check retrace
                best = meta["_tp1_trail_best"]
                _trail_pips_eff = TRAIL_AFTER_TP1_PIPS
                trail_dist = _trail_pips_eff * ppp
                if direction == "BUY":
                    if current > best:
                        meta["_tp1_trail_best"] = current
                        best = current
                    retrace = best - current
                else:
                    if current < best:
                        meta["_tp1_trail_best"] = current
                        best = current
                    retrace = current - best
                retrace_pips = retrace / ppp

                if retrace >= trail_dist:
                    logger.info(
                        "[BRIEFING_TP] %s trail stop hit: retrace %.1fp from peak (trail=%.0fp) — closing +%.1fp",
                        epic, retrace_pips, _trail_pips_eff, pnl_pips,
                    )
                    _close_trade_best_effort(epic, "TRAIL_AFTER_TP1", current)
                    self._clear_briefing_tp_meta(epic)
                    try:
                        import telegram_alerts
                        telegram_alerts.send_status_update(
                            f"📈 {pair} trail stop +{pnl_pips:.1f}p (retraced {retrace_pips:.0f}p from peak)"
                        )
                    except Exception:
                        pass
                return

            # Trail not yet armed — check if TP1 is hit to arm it
            if tp1_hit and phase == "OPEN":
                meta["_tp1_trail_armed"] = True
                meta["_tp1_trail_best"] = current
                meta["current_phase"] = "TP1"
                meta["sl_price"] = entry  # breakeven
                logger.info(
                    "[BRIEFING_TP] %s TP1 reached (+%.1fp) — trailing stop armed at %.0f pips behind peak",
                    epic, pnl_pips, TRAIL_AFTER_TP1_PIPS,
                )
                try:
                    import telegram_alerts
                    telegram_alerts.send_status_update(
                        f"📈 {pair} TP1 +{pnl_pips:.1f}p — trail armed ({TRAIL_AFTER_TP1_PIPS:.0f}p). SL → breakeven"
                    )
                except Exception:
                    pass
            return

        # =====================================================================
        # STANDARD TP1/TP2/TP3 MOMENTUM LOGIC (other strategies)
        # =====================================================================
        tp2_hit = (direction == "BUY" and current >= meta["tp2"]) or \
                  (direction == "SELL" and current <= meta["tp2"])
        tp3_hit = (direction == "BUY" and current >= meta["tp3"]) or \
                  (direction == "SELL" and current <= meta["tp3"])

        # TP3: always close
        if tp3_hit and phase in ("OPEN", "TP1", "TP2"):
            logger.info("[BRIEFING_TP] %s TP3 hit @ %.1f (+%.1fp)", epic, current, pnl_pips)
            _close_trade_best_effort(epic, "BRIEFING_TP3_HIT", current)
            self._clear_briefing_tp_meta(epic)
            try:
                import telegram_alerts
                telegram_alerts.send_status_update(
                    f"🏁 {pair} TP3 +{pnl_pips:.1f}p @ {current:.1f} — closing at major level"
                )
            except Exception:
                pass
            return

        # TP2: momentum check
        if tp2_hit and phase == "TP1":
            mom = check_momentum(
                direction,
                macd_hist or 0, prev_macd_hist or 0,
                candle_bodies or [], recent_highs or [], recent_lows or [],
            )
            if mom == "HOLD":
                # Move SL to TP1 level, continue to TP3
                meta["current_phase"] = "TP2"
                meta["sl_price"] = meta["tp1"]
                meta["swing_extreme"] = current  # Reset swing tracking
                # BB_PIERCE_RUN: also amend the broker-side SL to TP1
                # price (broker TP stays at 100p — unchanged). Other
                # strategies remain software-tracked SL only.
                if _is_bbpr_pos(epic):
                    _amend_broker_sl_for_bbpr(epic, float(meta["tp1"]))
                logger.info("[BRIEFING_TP] %s TP2 hit — momentum HOLD, SL→TP1 (%.1f), targeting TP3",
                            epic, meta["tp1"])
                try:
                    import telegram_alerts
                    telegram_alerts.send_status_update(
                        f"📈 {pair} TP2 +{pnl_pips:.1f}p @ {current:.1f} — momentum holds, "
                        f"running to TP3. SL → TP1 ({meta['tp1']:.1f})"
                    )
                except Exception:
                    pass
            else:
                # Momentum fading — close
                logger.info("[BRIEFING_TP] %s TP2 hit — momentum CLOSE (+%.1fp)", epic, pnl_pips)
                _close_trade_best_effort(epic, "BRIEFING_TP2_CLOSE", current)
                self._clear_briefing_tp_meta(epic)
                try:
                    import telegram_alerts
                    telegram_alerts.send_status_update(
                        f"📈 {pair} TP2 +{pnl_pips:.1f}p @ {current:.1f} — closing"
                    )
                except Exception:
                    pass
            return

        # TP1: momentum check
        if tp1_hit and phase == "OPEN":
            mom = check_momentum(
                direction,
                macd_hist or 0, prev_macd_hist or 0,
                candle_bodies or [], recent_highs or [], recent_lows or [],
            )
            if mom == "HOLD":
                # Move SL to breakeven, continue to TP2
                meta["current_phase"] = "TP1"
                meta["sl_price"] = entry  # breakeven
                meta["swing_extreme"] = current  # Reset swing tracking
                # BB_PIERCE_RUN: also amend the broker-side SL to entry
                # (BE), broker TP stays at 100p. Other strategies remain
                # software-tracked SL only.
                if _is_bbpr_pos(epic):
                    _amend_broker_sl_for_bbpr(epic, float(entry))
                logger.info("[BRIEFING_TP] %s TP1 hit — momentum HOLD, SL→breakeven, targeting TP2",
                            epic)
                try:
                    import telegram_alerts
                    telegram_alerts.send_status_update(
                        f"📈 {pair} TP1 +{pnl_pips:.1f}p @ {current:.1f} — momentum holds, "
                        f"running to TP2. SL → breakeven"
                    )
                except Exception:
                    pass
            else:
                # Momentum fading — close
                logger.info("[BRIEFING_TP] %s TP1 hit — momentum CLOSE (+%.1fp)", epic, pnl_pips)
                _close_trade_best_effort(epic, "BRIEFING_TP1_CLOSE", current)
                self._clear_briefing_tp_meta(epic)
                try:
                    import telegram_alerts
                    telegram_alerts.send_status_update(
                        f"📈 {pair} TP1 +{pnl_pips:.1f}p @ {current:.1f} — momentum fading, closing"
                    )
                except Exception:
                    pass
            return

    def _clear_briefing_tp_meta(self, epic: str) -> None:
        try:
            _BRIEFING_TP_BY_EPIC.pop(str(epic), None)
        except Exception:
            pass

    def _clear_bb_range_scalp_meta(self, epic: str) -> None:
        """Clear the RANGE_ROTATION BB_BOUNCE single-exit scalp registry
        entry (mirrors _clear_briefing_tp_meta). Called when the
        position deactivates."""
        try:
            _BB_RANGE_SCALP_BY_EPIC.pop(str(epic), None)
        except Exception:
            pass

    def _monitor_bb_range_scalp(self, epic: str, mid_price: float) -> None:
        """Monitor a RANGE_ROTATION BB_BOUNCE single-exit scalp.

        Phase 2 (REGIME_MATRIX_ENABLED=1):
          * Keys off regime_matrix.effective_regime(), not raw
            winning_regime, so raw label flicker (Phase 1 snap-back
            cycles absorbed by the matrix dwell) does not churn-close.
          * When the effective regime leaves RANGE_ROTATION the position
            HOLDS by default (RANGE_SCALP_ON_PROMOTION=ride) and rides
            toward its snapshotted opposite-band exit (broker LIMIT
            placed at entry time; see gbpusd_bb_bounce.py:1467-1490).
          * RANGE_SCALP_ON_PROMOTION=close restores the legacy
            force-close for rollback.
          * Profit floor: at +RANGE_SCALP_FLOOR_TRIGGER_PIPS (default
            8.0) the broker SL is ratcheted to entry +
            RANGE_SCALP_FLOOR_LOCK_PIPS × ppp in the position's favour
            via _apply_range_scalp_floor() (mirror of the BB_BOUNCE
            post-scale floor). Monotonic-up-only; NEVER moves the stop
            against the position. Applies regardless of the regime.

        Legacy (REGIME_MATRIX_ENABLED=0):
          * Reads raw winning_regime from regime_engine.latest_result;
            closes at market on any label other than RANGE_ROTATION.
          * Byte-identical to pre-Phase 2 behaviour.

        Fail-safe: any exception in the regime read leaves the trade
        open. Cheap: one regime read per range-scalp per monitor tick.
        """
        meta = _BB_RANGE_SCALP_BY_EPIC.get(str(epic))
        if meta is None:
            return
        st = _state_for_epic(epic)
        if not st.get("active"):
            self._clear_bb_range_scalp_meta(epic)
            return

        # ── Compute PnL and update peak MFE ────────────────────────
        _entry = float(meta.get("entry_price") or 0.0)
        _direction = str(meta.get("direction") or "").upper()
        try:
            _pnl_pips = (
                (float(mid_price) - _entry) if _direction == "BUY"
                else (_entry - float(mid_price))
            ) / float(_ppp(str(meta.get("pair") or "GBPUSD").upper()))
        except Exception:
            _pnl_pips = 0.0
        _best = float(meta.get("best_pnl_pips") or 0.0)
        if _pnl_pips > _best:
            meta["best_pnl_pips"] = float(_pnl_pips)
            _best = _pnl_pips

        # ── Profit floor (independent of regime; ratchet-up only) ──
        try:
            _pair = str(meta.get("pair") or "GBPUSD").upper()
            _ppp_v = float(_ppp(_pair))
            _apply_range_scalp_floor(
                epic=epic, pos_key=str(epic), st=st,
                range_meta=meta, ppp=_ppp_v, best_pnl_pips=_best,
            )
        except Exception as _floor_exc:
            logger.warning(
                "[BB_RANGE_SCALP] %s floor apply failed: %s",
                epic, _floor_exc,
            )

        # ── Regime read (effective under matrix, raw under legacy) ──
        try:
            if _REGIME_MATRIX_ENABLED_TM:
                import regime_matrix as _rm
                _winning_rs = str(
                    _rm.effective_regime(meta.get("pair") or "GBPUSD") or ""
                ).upper()
            else:
                import regime_engine as _re_rs
                _rg_rs = _re_rs.latest_result(meta.get("pair") or "GBPUSD") or {}
                _winning_rs = str(_rg_rs.get("winning_regime") or "").upper()
        except Exception as _re_exc:
            logger.warning(
                "[BB_RANGE_SCALP] %s regime read failed: %s — leaving "
                "position open (soft-fail)",
                epic, _re_exc,
            )
            return
        if _winning_rs == "RANGE_ROTATION":
            return

        # ── Effective regime has left RANGE_ROTATION ────────────────
        # Under matrix + ride: hold; the broker LIMIT / SL floor take
        # over. Log once per new effective label so operators can trace
        # the promotion path without spam.
        if _REGIME_MATRIX_ENABLED_TM and RANGE_SCALP_ON_PROMOTION == "ride":
            _last_seen = str(meta.get("last_seen_effective") or "")
            if _last_seen != _winning_rs:
                meta["last_seen_effective"] = _winning_rs
                logger.info(
                    "[BB_RANGE_SCALP] %s regime_change_ride: dir=%s "
                    "entry=%.5f current=%.5f effective_now=%s "
                    "pnl_pips=%.2f best=%.2f — riding to opposite-band "
                    "exit (RANGE_SCALP_ON_PROMOTION=ride)",
                    epic, _direction, _entry, float(mid_price),
                    _winning_rs or "UNKNOWN", _pnl_pips, _best,
                )
            return

        # ── Force-close path (legacy + rollback) ────────────────────
        logger.info(
            "[BB_RANGE_SCALP] %s range_scalp_regime_exit: ts=%s dir=%s "
            "entry=%.5f current=%.5f regime_now=%s pnl_pips=%.2f — "
            "closing at market (matrix=%s, on_promotion=%s)",
            epic, time.time(), _direction, _entry, float(mid_price),
            _winning_rs or "UNKNOWN", _pnl_pips,
            "on" if _REGIME_MATRIX_ENABLED_TM else "off",
            RANGE_SCALP_ON_PROMOTION,
        )
        try:
            _exec.close_position(
                epic=str(epic),
                reason="range_scalp_regime_exit",
                exit_hint_price=float(mid_price),
            )
        except Exception as _close_exc:
            logger.error(
                "[BB_RANGE_SCALP] %s close_position failed: %s",
                epic, _close_exc,
            )
            return
        self._clear_bb_range_scalp_meta(epic)

    # --------------------------------------------------------
    # BB_REVERSAL TRENDING — momentum-gated TP1 → TP2 → TP3
    # --------------------------------------------------------
    def _monitor_bb_reversal_trending(
        self,
        epic: str,
        meta: Dict[str, Any],
        st: Dict[str, Any],
        current: float,
        direction: str,
        entry: float,
        pair: str,
        ppp: float,
        pnl_pips: float,
        df_5m: Any = None,
        macd_hist: Any = None,
        prev_macd_hist: Any = None,
        candle_bodies: Optional[list] = None,
        recent_highs: Optional[list] = None,
        recent_lows: Optional[list] = None,
    ) -> None:
        """BB_REVERSAL trending-mode progression.

        State machine: OPEN → TP1_PASSED → TP2_PASSED → (TP3 closed by IG)
        At TP1 / TP2 hit:  call check_momentum(); HOLD ratchets SL and continues,
        CLOSE exits at the current TP price.
        SL is software-tracked (meta["sl_price"]) AND IG-side; whichever fires
        first wins. No indicator-driven exit — only SL and TP close the trade.
        """
        phase = meta.get("current_phase", "OPEN")

        # Software SL ratchet (set by HOLD branches below) — IG also has its
        # own SL, but the ratcheted entry+1 / TP1 stops only live in software.
        sl_price = meta.get("sl_price")
        if sl_price is not None and phase in ("TP1_PASSED", "TP2_PASSED"):
            sl_hit = (direction == "BUY" and current <= sl_price) or \
                     (direction == "SELL" and current >= sl_price)
            if sl_hit:
                logger.info(
                    "[BB_REVERSAL] %s ratchet SL hit @ %.1f phase=%s pnl=%+.1fp",
                    epic, current, phase, pnl_pips,
                )
                _close_trade_best_effort(epic, f"bb_reversal_ratchet_sl_{phase.lower()}", current)
                self._clear_briefing_tp_meta(epic)
                return

        # ---- TP-level reach detection (intrabar via tick) ----
        tp1_reached = (direction == "BUY" and current >= meta["tp1"]) or \
                      (direction == "SELL" and current <= meta["tp1"])
        tp2_reached = (direction == "BUY" and current >= meta["tp2"]) or \
                      (direction == "SELL" and current <= meta["tp2"])
        tp3_reached = (direction == "BUY" and current >= meta["tp3"]) or \
                      (direction == "SELL" and current <= meta["tp3"])

        # TP3 hit — IG limit closes. Just record + clear meta.
        if tp3_reached and phase in ("OPEN", "TP1_PASSED", "TP2_PASSED"):
            logger.info(
                "[BB_REVERSAL] %s TP3 hit @ %.1f (+%.1fp) — IG limit",
                epic, current, pnl_pips,
            )
            # IG executes the limit; we just clean up software state.
            self._clear_briefing_tp_meta(epic)
            return

        # If macd_hist / candles weren't passed, try to derive from df_5m so the
        # momentum check has real inputs. Falls back to whatever's available.
        if df_5m is not None and (candle_bodies is None or recent_highs is None or recent_lows is None
                                  or macd_hist is None):
            try:
                _bodies, _highs, _lows, _mh, _pmh = self._extract_momentum_inputs(df_5m)
                if candle_bodies is None: candle_bodies = _bodies
                if recent_highs is None:  recent_highs  = _highs
                if recent_lows is None:   recent_lows   = _lows
                if macd_hist is None:     macd_hist     = _mh
                if prev_macd_hist is None: prev_macd_hist = _pmh
            except Exception as _ex:
                logger.debug("[BB_REVERSAL] %s momentum-input extract failed: %s", epic, _ex)

        # TP2 hit — only valid if we already passed TP1 with HOLD.
        if tp2_reached and phase == "TP1_PASSED":
            mom = check_momentum(
                direction,
                macd_hist or 0, prev_macd_hist or 0,
                candle_bodies or [], recent_highs or [], recent_lows or [],
            )
            self._log_momentum("TP2", direction, mom, macd_hist, prev_macd_hist,
                               candle_bodies, recent_highs, recent_lows)
            if mom == "HOLD":
                meta["current_phase"] = "TP2_PASSED"
                meta["sl_price"] = float(meta["tp1"])
                logger.info(
                    "[BB_REVERSAL] %s TP2 hit action=extend new_sl=%.1f (TP1) target=TP3",
                    epic, meta["sl_price"],
                )
            else:
                logger.info(
                    "[BB_REVERSAL] %s TP2 hit action=close at %.1f (+%.1fp) — momentum=CLOSE",
                    epic, float(meta["tp2"]), pnl_pips,
                )
                _close_trade_best_effort(epic, "tp2_trending_momentum_close", float(meta["tp2"]))
                self._clear_briefing_tp_meta(epic)
            return

        # TP1 hit — only valid if we are still in OPEN (haven't passed TP1 yet).
        if tp1_reached and phase == "OPEN":
            mom = check_momentum(
                direction,
                macd_hist or 0, prev_macd_hist or 0,
                candle_bodies or [], recent_highs or [], recent_lows or [],
            )
            self._log_momentum("TP1", direction, mom, macd_hist, prev_macd_hist,
                               candle_bodies, recent_highs, recent_lows)
            if mom == "HOLD":
                meta["current_phase"] = "TP1_PASSED"
                # SL ratchet: entry +1 pip in trade direction (matches BE-amend offset)
                meta["sl_price"] = (entry + 1.0 * ppp) if direction == "BUY" else (entry - 1.0 * ppp)
                logger.info(
                    "[BB_REVERSAL] %s TP1 hit action=extend new_sl=%.1f (entry+1p) target=TP2",
                    epic, meta["sl_price"],
                )
            else:
                logger.info(
                    "[BB_REVERSAL] %s TP1 hit action=close at %.1f (+%.1fp) — momentum=CLOSE",
                    epic, float(meta["tp1"]), pnl_pips,
                )
                _close_trade_best_effort(epic, "tp1_trending_momentum_close", float(meta["tp1"]))
                self._clear_briefing_tp_meta(epic)
            return

    @staticmethod
    def _extract_momentum_inputs(df_5m: Any):
        """Return (candle_bodies, recent_highs, recent_lows, macd_hist, prev_macd_hist)
        from a 5M OHLC DataFrame. Used by BB_REVERSAL trending branch only."""
        import pandas as _pd
        if df_5m is None or not hasattr(df_5m, "iloc") or len(df_5m) < 4:
            return [], [], [], None, None
        last3 = df_5m.iloc[-3:]
        bodies = [(float(r["open"]), float(r["close"])) for _, r in last3.iterrows()]
        highs  = [float(df_5m.iloc[-2]["high"]), float(df_5m.iloc[-1]["high"])]
        lows   = [float(df_5m.iloc[-2]["low"]),  float(df_5m.iloc[-1]["low"])]
        # Try to read MACD histogram if column already on df; otherwise None
        # (caller falls back to whatever was passed via kwargs).
        mh = pmh = None
        for col in df_5m.columns:
            if str(col).upper().startswith("MACD_HIST"):
                try:
                    mh  = float(df_5m.iloc[-1][col])
                    pmh = float(df_5m.iloc[-2][col])
                    break
                except Exception:
                    pass
        return bodies, highs, lows, mh, pmh

    @staticmethod
    def _log_momentum(label, direction, verdict, mh, pmh, bodies, highs, lows):
        try:
            d = str(direction).upper()
            macd_expand = (float(mh or 0) > float(pmh or 0)) if d == "BUY" \
                          else (float(mh or 0) < float(pmh or 0))
            bodies_in_dir = 0
            for o, c in (bodies or [])[-3:]:
                if d == "BUY" and float(c) > float(o): bodies_in_dir += 1
                elif d == "SELL" and float(c) < float(o): bodies_in_dir += 1
            if d == "BUY":
                new_extreme = len(highs or []) >= 2 and float(highs[-1]) > float(highs[-2])
            else:
                new_extreme = len(lows or []) >= 2 and float(lows[-1]) < float(lows[-2])
            logger.info(
                "[BB_REVERSAL] momentum_check at %s: macd_expand=%s body_direction=%d new_extreme=%s → %s",
                label, macd_expand, bodies_in_dir, new_extreme, verdict,
            )
        except Exception:
            logger.info("[BB_REVERSAL] momentum_check at %s: → %s", label, verdict)

    # --------------------------------------------------------
    # Manager-side profit protection (all strategies)
    # --------------------------------------------------------
    def _monitor_profit_protection(
        self,
        epic: str,
        mid_price: float,
        bid: Any = None,
        ask: Any = None,
    ) -> None:
        """
        Manager-side lifecycle: REGIME_MAX_HOLD + universal +10p/50% scale-out.

        MPP (arm/floor/retrace close) was removed 2026-05-23 — true-net was
        −105p / 55d (gross saves +193p, strangle cost −132p, load-bearing
        saves only +27p). The +10p scale-out + broker BE stop is now the
        sole profit protection: half banked at +10, runner SL at entry,
        runner rides to broker SL/TP.

        TM v2 consultation hook (2026-09-14): after the existing exit
        logic runs, if TRADE_MANAGER_LIVE=1, consult trade_manager_v2 for
        the §51-§63 diagnosis. When the flag is 0 the consultation is
        skipped entirely (byte-identical behaviour). At flag=1 the
        diagnosis is written to logs/tm_shadow.jsonl but does NOT yet
        drive exit action — the exit-authority migration is a Phase §63
        follow-up. Consulting = the module is reached and speaks; acting
        on its recommendation is a separate step.
        """
        st = _state_for_epic(epic)
        if not st.get("active"):
            self._clear_profit_meta(epic)
            return

        entry = _safe_float(st.get("entry_price"), None)
        pip_size = _safe_float(st.get("pip_size"), None)
        direction = str(st.get("direction") or "").upper()
        open_time = _safe_float(st.get("open_time"), None)

        if entry is None or pip_size is None or pip_size <= 0 or direction not in ("BUY", "SELL"):
            return

        # TM v2 consultation — fail-silent, flag-gated, no exit-action.
        try:
            self._maybe_consult_tm_v2(
                epic=epic, st=st, mid_price=mid_price,
                entry=entry, pip_size=pip_size, direction=direction,
            )
        except Exception as _tmv2_exc:
            logger.debug("[TM-V2] consult raised: %s", _tmv2_exc)

        # BB_REVERSAL v4: per-leg SL + per-leg TP only. No BE, no trail, no
        # profit-protect, no time exit, no max-hold, no indicator-driven exits.
        # SL and TP are set at entry and never moved (broker-side).
        # A trade can run across window boundaries — windows only gate entries.
        _pm_trade_mode = str(st.get("mode") or "").upper()
        if _pm_trade_mode == "BB_REVERSAL":
            self._clear_profit_meta(epic)
            return

        # BRIEFING_EXECUTION simple-exits: short-circuit when REGIME_MAX_HOLD
        # is disabled — MPP was the other manager-side mechanism and has been
        # removed (2026-05-23). With both off there is nothing for this
        # function to do for BE trades; rides to SL/TP/EOD.
        _is_be_pm = _is_briefing_exec_mode(_pm_trade_mode)
        if _is_be_pm and not _BE_REGIME_MAX_HOLD_ENABLED:
            if not st.get("_be_pm_skip_logged"):
                logger.info(
                    "[%s] [BRIEFING-EXEC] skipped REGIME_MAX_HOLD "
                    "(env disabled; SL/TP/EOD are the only exits)", epic,
                )
                st["_be_pm_skip_logged"] = True
            self._clear_profit_meta(epic)
            return

        now = time.time()
        age_s = max(0.0, now - float(open_time or now))

        # ── Regime max_hold_minutes: force close if trade held too long ──
        _pm_meta = _PROFIT_MGMT_BY_EPIC.get(epic) or {}
        _pm_regime_exit = _pm_meta.get("regime_exit") or {}
        _max_hold_min = _pm_regime_exit.get("max_hold_minutes")
        # Per-mode override — RAW_REVERSAL needs 120 minutes regardless of
        # the active per-pair regime (which may be NEWS=60 on event days).
        # BB_PIERCE_RUN (GBPUSD_BB_BOUNCE_L/_S) extends to 240m. This is
        # the only time-stop mechanism for BB_PIERCE_RUN now that the
        # dedicated trail consumer was removed (2026-05-03); the multi-
        # tier briefing-TP path (_monitor_briefing_tp) handles SL/TP
        # progression.
        _pm_mode_for_mh = str(st.get("mode") or "").upper()
        if _pm_mode_for_mh in (
            "GBPUSD_RAW_REVERSAL_L", "GBPUSD_RAW_REVERSAL_S",
        ):
            _max_hold_min = 120
        elif _pm_mode_for_mh in BB_PIERCE_RUN_MODES:
            _max_hold_min = BB_PIERCE_RUN_TIME_STOP_MINUTES
        elif _pm_mode_for_mh in _STRUCTURE_BREAK_TRAIL_MODES:
            # structure_break has its own continuous peak-pivot trail; pin
            # to runner tier so the regime-of-the-day cap (NEWS=60 etc.)
            # doesn't preempt it. See STRUCTURE_BREAK_TIME_STOP_MINUTES.
            _max_hold_min = STRUCTURE_BREAK_TIME_STOP_MINUTES
        elif _pm_mode_for_mh in ("GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S"):
            # TREND_V3 owns its own exit (flatten-exhaustion / structural-break /
            # regime-leave) inside gbpusd_trend_v3.monitor_exits. The trade_manager
            # cap here is the wide safety net only — disabling the per-regime
            # 60/120/240-min cap so a real daily-trend ride is not choked.
            _max_hold_min = int(os.getenv("TREND_V3_MAX_HOLD_MIN", "1440"))
        elif _pm_mode_for_mh in _PIVOT_BREAK_TRAIL_MODES:
            # PIVOT_BREAK — the 2026-08-12 template took 125 minutes to
            # reach R1 and another 10 for R2. The regime-of-the-day cap
            # (NEWS=60, SWEEP=120) would clip the pre-scale phase.
            # Pin to PIVOT_BREAK_MAX_HOLD_MIN (default 480) so a slow
            # grind can complete; the SCALED_OUT_EXEMPT below then
            # releases the runner once R1 has been banked.
            _max_hold_min = int(PIVOT_BREAK_MAX_HOLD_MIN)
        elif _pm_mode_for_mh in _LEVEL_BOUNCE_MODES:
            # LEVEL_BOUNCE — research (90d) shows median time to first
            # forward pivot ≈ 1h42; NEWS=60 / SWEEP=120 would close the
            # trade mid-move. Unmanaged by design → disable the cap by
            # setting max_hold_min = None. The 100p SL is the only exit.
            _max_hold_min = None
        elif _pm_mode_for_mh in _TREND_V3_UM_MODES:
            # 2026-08-14 TREND_V3 UM — mirrors LEVEL_BOUNCE. Unmanaged;
            # sole exits are 12p SL / 100p TP / TREND_V3_UM_EOD_CLOSE.
            # Disable the regime-of-the-day cap so the runner is not
            # clipped mid-move.
            _max_hold_min = None
        # 2026-08-15 range-mode BB flip mode: mirrors LEVEL_BOUNCE.
        # Sole exits are BB_RANGE_TARGET / BB_FLIP / broker stop / NY_CLOSE.
        # (BB_RANGE_TARGET 2026-08-16 — opposite-band touch.) Disable the
        # regime-of-the-day cap so the runner can flip cleanly.
        if bool(_pm_meta.get("range_mode_flip")):
            _max_hold_min = None
        # 2026-07-27: env kill-switch on the max-hold force close.
        # Default "1" preserves current behaviour byte-identically.
        # When "0", skip the close and emit ONE INFO per trade per
        # breach so the disabled clock stays observable in logs. The
        # flip sequence (operator-controlled): shadow -> evidence in
        # [RUNNER-MOMENTUM] lines -> enforce -> then flip this to 0.
        # 2026-08-25: hoisted above the scaled-out pre-check so that
        # branch stays silent when the master gate is off — previously
        # the scaled-out INFO fired even with REGIME_MAX_HOLD disabled,
        # duplicating the disabled-path INFO in the enforcement branch.
        # runtime-read: deliberate — tests reload module then setenv; do not hoist.
        _regime_max_hold_enabled = (
            (os.getenv("REGIME_MAX_HOLD_ENABLED", "1") or "1")
            .strip().lower() in ("1", "true", "yes", "on")
        )
        # ── Scaled-out exemption (2026-06-18) ──────────────────────────
        # Once the universal +10p scale-out has fired, the trade is in
        # runner-trail mode: the strategy-specific trail
        # (_apply_trend_runner_trail / _apply_bb_bounce_runner_trail /
        # _apply_structure_break_runner_trail) or the broker SL@BE+TP
        # owns the exit. Audit 2026-06-18 (window 06-05..06-18) found
        # 4/4 REGIME_MAX_HOLD closes were trailing winners clipped,
        # 0 losers rescued, +66.4p of post-close MFE left behind.
        # Env read call-time so a flag flip takes effect on the next
        # tick without restart. Disables ONLY the max_hold close; the
        # rest of profit progression continues normally.
        # 2026-08-25: gated behind _regime_max_hold_enabled — when the
        # master gate is off the enforcement branch owns the single
        # per-trade INFO, so this pre-check must not double-log.
        _scaled_out_exempt_enabled = (
            (os.getenv("REGIME_MAX_HOLD_SCALED_OUT_EXEMPT_ENABLED", "1") or "1")
            .strip().lower() in ("1", "true", "yes")
        )
        if (
            _regime_max_hold_enabled
            and _scaled_out_exempt_enabled
            and bool(_pm_meta.get("scaled_out"))
            and _max_hold_min is not None
            and age_s >= float(_max_hold_min) * 60
        ):
            if not st.get("_max_hold_scaled_out_skip_logged"):
                logger.info(
                    "[%s] [REGIME_MAX_HOLD] skipped: meta.scaled_out=True "
                    "(trail / broker SL@BE+TP owns exit) age=%.0fm limit=%sm",
                    epic, age_s / 60, _max_hold_min,
                )
                st["_max_hold_scaled_out_skip_logged"] = True
            _max_hold_min = None
        if _max_hold_min is not None and age_s >= float(_max_hold_min) * 60:
            if not _regime_max_hold_enabled:
                if not st.get("_regime_max_hold_disabled_skip_logged"):
                    _deal_id_mh = st.get("dealId") or st.get("deal_id") or epic
                    logger.info(
                        "[%s] [REGIME-MAX-HOLD] SKIPPED (disabled) deal=%s "
                        "elapsed=%.0fm limit=%sm",
                        epic, _deal_id_mh, age_s / 60, _max_hold_min,
                    )
                    st["_regime_max_hold_disabled_skip_logged"] = True
            # BE skip: when BRIEFING_EXEC_REGIME_MAX_HOLD_ENABLED=0 (default),
            # BE positions are exempt from REGIME_MAX_HOLD and ride to SL/TP/EOD.
            elif _is_be_pm and not _BE_REGIME_MAX_HOLD_ENABLED:
                if not st.get("_be_regime_max_hold_skip_logged"):
                    logger.info(
                        "[%s] [BRIEFING-EXEC] skipped REGIME_MAX_HOLD (env disabled, "
                        "trade age %.0fm >= limit %sm)",
                        epic, age_s / 60, _max_hold_min,
                    )
                    st["_be_regime_max_hold_skip_logged"] = True
            else:
                pair_mh = _pair_from_epic(epic)
                current_mh = _effective_price_for_management(direction, float(mid_price), bid=bid, ask=ask)
                pnl_mh = _calculate_pnl_pips(direction, float(entry), float(current_mh), float(pip_size))
                logger.info(
                    f"[{epic}] REGIME_MAX_HOLD: trade open {age_s/60:.0f}m >= limit {_max_hold_min}m "
                    f"— force close (pnl={pnl_mh:.1f})"
                )
                _exec.close_position(epic=epic, reason="REGIME_MAX_HOLD", exit_hint_price=float(mid_price))
                try:
                    from telegram_alerts import send_telegram_message
                    send_telegram_message(
                        f"<b>Regime max hold:</b> {pair_mh} closed after {age_s/60:.0f}m "
                        f"(limit={_max_hold_min}m, pnl={pnl_mh:.1f}p)"
                    )
                except Exception:
                    pass
                return

        current = _effective_price_for_management(direction, float(mid_price), bid=bid, ask=ask)
        pnl_pips = _calculate_pnl_pips(direction, float(entry), float(current), float(pip_size))

        # BRIEFING_LIQUIDITY / BRIEFING_SWEEP rely on SL + trailing stop after TP1 only.
        # WINDOW_SWEEP morning = scalp with fixed TP/SL on IG, no profit management.
        trade_mode = str(st.get("mode") or "").strip().upper()
        _pm_reason = str(st.get("reason") or "").lower()
        if trade_mode in ("BRIEFING_LIQUIDITY", "BRIEFING_SWEEP"):
            return
        if trade_mode == "WINDOW_SWEEP" and "morning" in _pm_reason:
            return

        pair = _pair_from_epic(epic)
        ppp = _ppp(epic)

        meta = _PROFIT_MGMT_BY_EPIC.get(epic)
        # 2026-08-15 belt-and-braces guard for the per-position meta leak that
        # produced the 2026-08-14 17:30 GBPUSD_BB_BOUNCE_L inheritance
        # (first AUTO-CUT eval showed best=7.50 best_close=6.45 — the peaks of
        # the 15:30 position that had closed 11 minutes earlier). Primary fix
        # is _purge_per_position_meta wired to trade_executor's close callback
        # (see module tail); this branch catches any close-path that misses it.
        _cur_deal_id = str(st.get("dealId") or st.get("deal_id") or "")
        if meta is not None and _cur_deal_id:
            _meta_deal_id = str(meta.get("_deal_id") or "")
            if _meta_deal_id and _meta_deal_id != _cur_deal_id:
                logger.info(
                    "[META_HYGIENE] %s stale profit meta detected: "
                    "meta_deal=%s cur_deal=%s — re-initialising",
                    epic, _meta_deal_id, _cur_deal_id,
                )
                meta = None
        if meta is None:
            # Load regime exit config at trade open (consumed by REGIME_MAX_HOLD).
            _regime_exit = None
            try:
                import regime_router
                _regime_exit = regime_router.get_exit_config(pair)
            except Exception:
                pass
            meta = {
                "created_ts": now,
                "best_pnl_pips": pnl_pips,
                "last_pnl_pips": pnl_pips,
                # trail_armed kept for sweep-trail manager (separate function);
                # it sets/reads this on _PROFIT_MGMT_BY_EPIC[epic] too.
                "trail_armed": False,
                "regime_exit": _regime_exit,
                # Position identity tag — used by the belt-and-braces stale
                # meta check above to detect leak between successive positions
                # on the same pos_key. "" when opened pre-confirm (dealId not
                # yet populated); the check no-ops for empty ids either side.
                "_deal_id": _cur_deal_id,
                # Range-mode BB flip marker (2026-08-15 build). Propagated
                # from st at creation and re-synced on every management
                # pass so a late-set tag still flows through.
                "range_mode_flip": bool(st.get("range_mode_flip")),
            }
            _PROFIT_MGMT_BY_EPIC[epic] = meta
        else:
            # Stamp deal_id on meta the first time we see one (e.g., meta was
            # created by another code path before dealId was populated on st).
            if _cur_deal_id and not meta.get("_deal_id"):
                meta["_deal_id"] = _cur_deal_id
            best_prev = _safe_float(meta.get("best_pnl_pips"), pnl_pips)
            if best_prev is None:
                best_prev = pnl_pips
            meta["best_pnl_pips"] = max(float(best_prev), float(pnl_pips))
            meta["last_pnl_pips"] = pnl_pips
            # Re-sync range_mode_flip from st (belt-and-braces for the
            # case where the tag was set after meta creation, e.g. legacy
            # meta rebuilt on restart via _rebuild_profit_state).
            if st.get("range_mode_flip") and not meta.get("range_mode_flip"):
                meta["range_mode_flip"] = True

        best_pnl = _safe_float(meta.get("best_pnl_pips"), pnl_pips)
        if best_pnl is None:
            best_pnl = pnl_pips

        # ── BB range-mode opposite-band target (2026-08-16) ───────────
        # Operator ruling: in range_mode, the BB flip position's target
        # IS the opposite Bollinger band edge. Close on TOUCH (bar
        # extreme reaches the opposite band), not on a confirmed
        # opposite-bounce setup.
        #
        # This close is SENIOR alongside the BB_FLIP path (autobot.
        # _apply_bb_bounce_range_flip). The flip-on-confirmed-opposite
        # path stays and is now secondary — it only fires if an opposite
        # BB_BOUNCE decision arrives BEFORE the bar extreme reaches the
        # opposite band.
        #
        # Ordering when both are pending on the same 5m bar:
        #   1. Per-tick trade_manager profit_mgmt runs FIRST (autobot
        #      LS tick handler → _monitor_profit_protection). This
        #      block sees the intra-bar high/low and fires
        #      BB_RANGE_TARGET immediately.
        #   2. On the 5m close, candle_builder → _on_5m_close_bb_bounce
        #      → _apply_bb_bounce_range_flip runs LAST. It finds the
        #      slot empty (position already closed by the target) and
        #      opens the opposite BB fire as a FRESH entry — not a flip.
        # If a mid-bar tick misses the touch (unlikely — trade_manager
        # is called on every LS tick), the close callback ordering
        # gives BB_FLIP the slot: close_position on the same pos_key
        # is idempotent, so a same-tick double-fire is safe.
        #
        # Reads bb_upper / bb_lower via candle_builder + the strategy's
        # own _bb_20_2 (gbpusd_bb_bounce.py:965 — the exact function
        # the LIVE strategy uses at fire time; import cited).
        # Kill-switch: BB_RANGE_TARGET_ENABLED (default "1").
        _bb_range_trail_modes = _BB_BOUNCE_TRAIL_MODES
        _bbrt_is_bb_flip = (
            str(st.get("mode") or "").upper() in _bb_range_trail_modes
            and bool(meta.get("range_mode_flip"))
        )
        _bbrt_enabled = (
            (os.getenv("BB_RANGE_TARGET_ENABLED", "1") or "1")
            .strip().lower() in ("1", "true", "yes", "on")
        )
        # ── Quiet-Market §21.6 adaptive-exit — LIVE call site (2026-08-26)
        # For the six QM in-scope modes, when QM_ADAPTIVE_EXIT_ENABLED=1:
        #   * fetch the most-recent CLOSED 5m bar for this pair
        #   * once per bar per position (idempotent via _qm_last_bar_ts):
        #     call qm_adaptive_exit.evaluate() with the bar's OHLC + BB
        #     bands and act on the returned decision (HOLD /
        #     EXIT_CLOSE_INSIDE / PROMOTE_TO_RUNNER / …).
        # The env flag is read PER-CALL — NOT hoisted to a module constant.
        # When flag=0 the block is a no-op and _qm_defers_range_target stays
        # False so the legacy BB_RANGE_TARGET gate below reduces to its
        # byte-identical pre-QM conjunction.
        _qm_defers_range_target = False
        _qm_in_scope_modes = {
            "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
            "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
            "GBPUSD_BB_REV_L", "GBPUSD_BB_REV_L_S",
        }
        _mode_up_qm = str(st.get("mode") or "").upper()
        _qm_flag_raw = (
            (os.getenv("QM_ADAPTIVE_EXIT_ENABLED", "0") or "0").strip().lower()
        )
        _qm_flag_now = _qm_flag_raw in ("1", "true", "yes", "on")
        # Kill-switch observability: log any transition of the read env
        # value vs the last observation. Fires on the very first in-scope
        # eval after process start (None -> "1" or None -> "0") and on
        # every subsequent flip in either direction. Proof line for
        # "the running process is picking up the new flag value".
        global _QM_EXIT_LAST_FLAG_SEEN
        if (_mode_up_qm in _qm_in_scope_modes
                and _QM_EXIT_LAST_FLAG_SEEN != _qm_flag_raw):
            try:
                _branch = "adaptive" if _qm_flag_now else "legacy"
                logger.info(
                    "[qm_exit] flag transition observed: %s -> %s "
                    "(mode=%s, decision-branch=%s)",
                    _QM_EXIT_LAST_FLAG_SEEN, _qm_flag_raw,
                    _mode_up_qm, _branch,
                )
                _QM_EXIT_LAST_FLAG_SEEN = _qm_flag_raw
            except Exception:
                pass
        # One-time proof-of-arm log: fires the first time this site is
        # reached by any in-scope position after process start, REGARDLESS
        # of the QM flag value. Without this the integration was silent
        # when flag=0 and unverifiable pre-flip. Guarded by module-level
        # sentinel _QM_EXIT_ARMED_LOGGED so it emits exactly once per
        # process. See ADDENDUM 2 report for the rationale.
        global _QM_EXIT_ARMED_LOGGED
        if _mode_up_qm in _qm_in_scope_modes and not _QM_EXIT_ARMED_LOGGED:
            try:
                logger.info(
                    "[qm_exit] armed: adaptive band exit active for %d modes, "
                    "flag=%s (first in-scope eval: epic=%s mode=%s dir=%s)",
                    len(_qm_in_scope_modes),
                    ("1" if _qm_flag_now else "0"),
                    epic, _mode_up_qm, direction,
                )
                _QM_EXIT_ARMED_LOGGED = True
            except Exception:
                pass
        if _mode_up_qm in _qm_in_scope_modes and _qm_flag_now:
            _qm_defers_range_target = True  # single-authority: skip BB_RANGE_TARGET below
            try:
                import qm_adaptive_exit as _qmx
                import candle_builder as _cb_qm
                _df_qm = _cb_qm.get_df(pair)
                if _df_qm is not None and not getattr(_df_qm, "empty", True) \
                        and len(_df_qm) >= 1:
                    _last_row = _df_qm.iloc[-1]
                    _bar_ts_raw = _last_row.name
                    if hasattr(_bar_ts_raw, "isoformat"):
                        _bar_ts_iso = _bar_ts_raw.isoformat()
                    else:
                        _bar_ts_iso = str(_bar_ts_raw)
                    # Idempotent per bar per position — read the marker off
                    # st so it survives across ticks.
                    _last_seen_bar = str(st.get("_qm_last_bar_ts") or "")
                    if _bar_ts_iso and _bar_ts_iso != _last_seen_bar:
                        _bb_up_qm = None
                        _bb_lo_qm = None
                        for _col in ("BB_UPPER_20_2", "BB_UPPER_20", "BB_U"):
                            if _col in _df_qm.columns:
                                _bb_up_qm = float(_last_row[_col])
                                break
                        for _col in ("BB_LOWER_20_2", "BB_LOWER_20", "BB_L"):
                            if _col in _df_qm.columns:
                                _bb_lo_qm = float(_last_row[_col])
                                break
                        _bar_snap = _qmx.BarSnapshot(
                            ts=_bar_ts_iso,
                            open=float(_last_row["open"]),
                            high=float(_last_row["high"]),
                            low=float(_last_row["low"]),
                            close=float(_last_row["close"]),
                            bb_upper=_bb_up_qm,
                            bb_lower=_bb_lo_qm,
                        )
                        # qm_state lives on the position dict at st['meta']
                        # so it moves with the position lifecycle (purged
                        # on close via trade_executor's close callback) and
                        # matches the slot BUILD 4 shadow reads for
                        # coherence.
                        _qm_meta = st.setdefault("meta", {}) if isinstance(st, dict) else {}
                        _qm_state_d = _qm_meta.get("qm_state") if isinstance(_qm_meta, dict) else None
                        if _qm_state_d is None:
                            _qm_state = _qmx.QmPositionState(
                                pos_key=epic, mode=_mode_up_qm,
                                direction=direction, entry_price=float(entry),
                            )
                        else:
                            try:
                                _qm_state = _qmx.QmPositionState(**_qm_state_d)
                            except Exception:
                                _qm_state = _qmx.QmPositionState(
                                    pos_key=epic, mode=_mode_up_qm,
                                    direction=direction, entry_price=float(entry),
                                )
                        _dec = _qmx.evaluate(_qm_state, _bar_snap)
                        if _dec.state_after is not None and isinstance(_qm_meta, dict):
                            from dataclasses import asdict as _asdict_qm
                            _qm_meta["qm_state"] = _asdict_qm(_dec.state_after)
                        st["_qm_last_bar_ts"] = _bar_ts_iso
                        if _dec.action == _qmx.D_EXIT_CLOSE_INSIDE:
                            _exit_hint = float(_dec.exit_price or _bar_snap.close)
                            logger.warning(
                                "[QM_EXIT] %s mode=%s dir=%s reason=%s "
                                "exit_hint=%.5f bar_ts=%s",
                                epic, _mode_up_qm, direction, _dec.reason,
                                _exit_hint, _bar_ts_iso,
                            )
                            _exec.close_position(
                                epic=epic, reason="QM_BAND_CLOSE_INSIDE",
                                exit_hint_price=_exit_hint,
                            )
                            return
                        elif _dec.action == _qmx.D_PROMOTE_TO_RUNNER:
                            if isinstance(_qm_meta, dict):
                                _qm_meta["qm_runner_promoted"] = True
                            logger.info(
                                "[QM_PROMOTE] %s mode=%s dir=%s bar_ts=%s "
                                "— QM stands down, ratchet owns",
                                epic, _mode_up_qm, direction, _bar_ts_iso,
                            )
                        # HOLD / HANDED_OFF / OUT_OF_SCOPE / DISABLED_LEGACY:
                        # fall through to legacy management; QM has stood down
                        # or is deferring to its own state machine.
            except Exception as _qm_exc:
                logger.warning("[QM_EXIT] %s eval raised: %s", epic, _qm_exc)
        if _bbrt_is_bb_flip and _bbrt_enabled and not _qm_defers_range_target:
            try:
                import candle_builder as _cb_bbrt
                _df_bbrt = _cb_bbrt.get_df(pair)
                _closes_bbrt = None
                _bar_high_bbrt = None
                _bar_low_bbrt = None
                if _df_bbrt is not None and not getattr(_df_bbrt, "empty", True):
                    _closes_bbrt = _df_bbrt["close"].astype(float).tolist()
                    _bar_high_bbrt = float(_df_bbrt["high"].iloc[-1])
                    _bar_low_bbrt  = float(_df_bbrt["low"].iloc[-1])
                if _closes_bbrt is not None and len(_closes_bbrt) >= 20:
                    from gbpusd_bb_bounce import _bb_20_2 as _bbrt_bb
                    _bbrt_lo, _bbrt_mid, _bbrt_up = _bbrt_bb(_closes_bbrt)
                    _bbrt_touch = False
                    _bbrt_tag = None
                    _bbrt_touch_price = None
                    if direction == "BUY" and _bar_high_bbrt is not None \
                            and _bar_high_bbrt >= _bbrt_up:
                        _bbrt_touch = True
                        _bbrt_tag = "upper"
                        _bbrt_touch_price = _bar_high_bbrt
                    elif direction == "SELL" and _bar_low_bbrt is not None \
                            and _bar_low_bbrt <= _bbrt_lo:
                        _bbrt_touch = True
                        _bbrt_tag = "lower"
                        _bbrt_touch_price = _bar_low_bbrt
                    if _bbrt_touch:
                        _bbrt_pnl = _calculate_pnl_pips(
                            direction, float(entry), float(_bbrt_touch_price),
                            float(pip_size),
                        )
                        logger.warning(
                            "[BB-RANGE-TARGET] pair=%s epic=%s dir=%s "
                            "opposite=%s touch_price=%.2f bb_upper=%.2f "
                            "bb_lower=%.2f entry=%.2f pnl=%.1fp — "
                            "closing at market (range_mode_flip target; "
                            "senior alongside BB_FLIP)",
                            pair, epic, direction, _bbrt_tag,
                            float(_bbrt_touch_price), float(_bbrt_up),
                            float(_bbrt_lo), float(entry), float(_bbrt_pnl),
                        )
                        try:
                            from telegram_alerts import send_telegram_message
                            send_telegram_message(
                                f"🎯 <b>[BB-RANGE-TARGET]</b> {pair} {direction}\n"
                                f"Opposite band ({_bbrt_tag}) touched at "
                                f"<code>{_bbrt_touch_price:.2f}</code>\n"
                                f"BB: upper=<code>{_bbrt_up:.2f}</code> "
                                f"lower=<code>{_bbrt_lo:.2f}</code>\n"
                                f"P&amp;L: <b>{_bbrt_pnl:+.1f}p</b>  "
                                f"Reason: <code>BB_RANGE_TARGET</code>"
                            )
                        except Exception:
                            pass
                        _exec.close_position(
                            epic=epic, reason="BB_RANGE_TARGET",
                            exit_hint_price=float(_bbrt_touch_price),
                        )
                        # Meta-hygiene: close_position triggers the
                        # registered close-callback → _purge_per_position_meta
                        # (module tail :6909). Nothing to purge here.
                        return
            except Exception as _bbrt_exc:
                logger.warning(
                    "[BB-RANGE-TARGET] %s eval raised: %s", epic, _bbrt_exc,
                )

        # ── PIVOT_BREAK price-target scale hook ────────────────────────
        # For PIVOT_BREAK positions the scale trigger is a PRICE cross
        # (R1 for BUY / S1 for SELL), not a pip P&L. Runs before the
        # universal +10p gate so it can bank at R1 even when R1 sits
        # short of +10p from entry. See _apply_pivot_break_targets.
        if str(st.get("mode") or "").upper() in _PIVOT_BREAK_TRAIL_MODES:
            try:
                _apply_pivot_break_targets(
                    epic=epic, st=st, meta=meta, pair=pair,
                    pip_size=float(pip_size),
                    entry_price=float(entry),
                    direction=direction,
                    current_price=float(current),
                )
            except Exception as _pb_exc:
                logger.warning(
                    "[PIVOT_BREAK] target hook raised: %s", _pb_exc,
                )

        # ── BB_BOUNCE condition-aware EXIT PROFILE (2026-08-06) ────────
        # One-shot decision at first +EXIT_PROFILE_TRIGGER_PIPS (default
        # 7.0p) — MUST run before the universal scale-out gate below so
        # the SQUEEZE branch can block scale-out before it fires. Ordering:
        #   TRIGGER 7.0  <  SCALE_OUT_TRIGGER (env=8, code default 10).
        # Gated to BB_BOUNCE modes only; default OFF; env activates.
        # Range-mode BB flip mode: exit profile is disabled per spec —
        # sole exits are BB_RANGE_TARGET, BB_FLIP, broker stop, or NY_CLOSE.
        if (_exit_profile_enabled()
                and str(st.get("mode") or "").upper() in _BB_BOUNCE_TRAIL_MODES
                and not meta.get("range_mode_flip")):
            try:
                _apply_exit_profile(
                    epic=epic, st=st, meta=meta, pair=pair,
                    pip_size=float(pip_size),
                    entry_price=float(entry),
                    direction=direction,
                    current_price=float(current),
                    best_pnl=float(best_pnl),
                )
            except Exception as _ep_exc:
                logger.warning(
                    "[EXIT-PROFILE] %s _apply_exit_profile raised: %s",
                    epic, _ep_exc,
                )

        # ── AUTO-K premise-death cut (2026-08-09) ──────────────────────
        # Runs AFTER the exit profile so a SQUEEZE-mode BB_BOUNCE position
        # is still eligible if it goes underwater with accelerating adverse
        # velocity AND has never touched +5p (wobble-winners are protected
        # by the never-touched-lock guard inside auto_k.eval_and_close).
        # Per-family MAE thresholds; NEWS_CONT_LEG excluded by env default.
        # Operator K / broker stop / STRUCTURE_EXIT remain senior and
        # independent — auto-K only issues a market close via the same
        # close_position primitive (with reason=AUTO_K_PREMISE).
        # Per-bar throttle: only evaluate when a new completed 5m bar
        # arrives (meta["_autok_last_bar_ts"] tracks it).
        # 2026-08-15 range-mode BB flip mode: AUTO_K is disabled for any
        # position tagged range_mode_flip. Sole exits are BB_RANGE_TARGET /
        # BB_FLIP / broker stop / NY_CLOSE — an AUTO_K premise-death cut
        # would defeat the
        # flip semantics (a BB fade being unwound by the fresh opposite
        # is not "premise dead", it is the primary exit). One-shot INFO
        # so the [AUTO-CUT] telemetry shows why no eval ran.
        _autok_range_skip = bool(meta.get("range_mode_flip"))
        if _autok_range_skip and not meta.get("_autok_range_mode_skip_logged"):
            logger.info(
                "[AUTO-CUT] skipped mode=%s — meta.range_mode_flip=True "
                "(sole exits: BB_RANGE_TARGET / BB_FLIP / broker stop / NY_CLOSE)",
                str(st.get("mode") or ""),
            )
            meta["_autok_range_mode_skip_logged"] = True
        try:
            import auto_k as _autok
            if (not _autok_range_skip
                    and _autok._enabled()
                    and _autok.threshold_for_mode(st.get("mode")) is not None):
                import candle_builder as _cb_autok
                _df_ak = _cb_autok.get_df(pair)
                if _df_ak is not None and not getattr(_df_ak, "empty", True):
                    _last_ts = str(_df_ak["time"].iloc[-1]) if "time" in _df_ak.columns else None
                    _prev_ts = meta.get("_autok_last_bar_ts")
                    if _last_ts is not None and _last_ts != _prev_ts:
                        meta["_autok_last_bar_ts"] = _last_ts
                        _closes = _df_ak["close"].astype(float).tolist()
                        _highs = _df_ak["high"].astype(float).tolist()
                        _lows = _df_ak["low"].astype(float).tolist()
                        # 2026-08-11: ratchet a per-bar-close MFE (distinct
                        # from meta["best_pnl_pips"] which is per-tick).
                        # auto_k gate 3 consults this under
                        # AUTOK_TOUCHED_LOCK_ON_CLOSE=1 so a wick-spike +5p
                        # bar cannot exempt the position from auto-cut.
                        try:
                            _bar_close = float(_closes[-1])
                            if str(direction).upper() == "BUY":
                                _close_pnl = (_bar_close - float(entry)) / float(ppp)
                            else:
                                _close_pnl = (float(entry) - _bar_close) / float(ppp)
                            _prev_best_close = meta.get("best_close_pnl_pips")
                            if _prev_best_close is None:
                                meta["best_close_pnl_pips"] = float(_close_pnl)
                            else:
                                meta["best_close_pnl_pips"] = max(
                                    float(_prev_best_close), float(_close_pnl),
                                )
                        except Exception:
                            pass
                        _best_close_arg = meta.get("best_close_pnl_pips")
                        # 2026-08-26 SESSION 2 — LEVEL_BOUNCE ACCEPTANCE
                        # branch inside auto_k reads level_price /
                        # level_name / level_side from the strategy's
                        # decision.debug snapshot. Pass the whole
                        # decision_debug dict so future consumers can
                        # read more context without another wiring pass.
                        _strategy_meta = dict(st.get("decision_debug") or {})
                        _dec = _autok.eval_and_close(
                            epic=epic, pos_key=epic, pair=pair,
                            mode=str(st.get("mode") or ""),
                            direction=direction,
                            entry_price=float(entry),
                            current_price=float(current),
                            ppp=float(ppp),
                            best_pnl_pips=float(best_pnl),
                            closes_5m=_closes, highs_5m=_highs, lows_5m=_lows,
                            trade_id=str(st.get("dealId") or st.get("deal_id") or ""),
                            best_close_pnl_pips=(
                                float(_best_close_arg)
                                if _best_close_arg is not None else None
                            ),
                            strategy_meta=_strategy_meta,
                        )
                        if _dec is not None and _dec.get("kind") == "CUT":
                            # Position closed — exit the management pass so
                            # no downstream branch (scale-out, trails,
                            # BE-recover, STRUCTURE_EXIT, timed exits) tries
                            # to act on a position that is no longer open.
                            return
        except Exception as _ak_exc:
            logger.warning("[AUTO-K] eval raised (fail-open): %s", _ak_exc)

        # ── UNIVERSAL +10p / 50% SCALE-OUT (2026-05-23) ────────────────
        # Sole profit protection now that MPP has been stripped. Idempotent
        # via meta["scaled_out"]. Bypasses close_trade so _on_trade_close
        # does NOT fire and EPIC_STATE is not reset — the runner remains
        # with broker SL at BE and original broker TP, and the +10p partial
        # bank is recorded for the OUTCOME JOIN total_pnl computation.
        # Phase 3 collision guard 5.1: profile-managed trades own their
        # scale-out. Universal path skips them so only ONE scale-out
        # ever fires per position (guaranteed by the shared meta
        # ["scaled_out"] key). RANGE / LEGACY / None fall through to
        # the universal path unchanged.
        # 2026-08-06: exit-profile SQUEEZE additionally blocks scale-out
        # so a SQUEEZE-flagged position rides its own full-close target
        # (or its recheck flip to REVERTED_EXPANDED) instead of banking
        # 50% and arming the trail. The revert path uses "REVERTED_
        # EXPANDED" so this gate re-opens on the next tick.
        _profile_id_scale = str(st.get("profile_id") or "").upper()
        _universal_scale_gated = (
            _REGIME_MGMT_ENABLED_TM and _profile_id_scale in _PROFILE_MANAGED
        )
        _ep_scale_blocked = (
            str(((meta.get("exit_profile") or {}).get("mode") or "")).upper() == "SQUEEZE"
        )
        # 2026-08-09: NEWS_CONT_LEG exit geometry is news-native (BE +
        # structure trail, both owned by news_continuation.manage_open_position).
        # No universal scale-out on this mode — the two paths would
        # double-manage the SL.
        _news_cont_leg = (str(st.get("mode") or "").upper() == "NEWS_CONT_LEG")
        # LEVEL_BOUNCE exemption: the +10p scale-out would bank half of an
        # unmanaged position that is explicitly designed to ride to its
        # 100p SL or wherever the tape takes it. Universal scale-out is
        # ON by default (SCALE_OUT_AT_10P_ENABLED=1); this per-mode skip
        # is the exemption. See _LEVEL_BOUNCE_MODES (:328).
        _level_bounce = (
            str(st.get("mode") or "").upper() in _LEVEL_BOUNCE_MODES
        )
        # 2026-08-14 TREND_V3 UM — same exemption. +10p scale-out would
        # bank half of an unmanaged runner engineered to ride to 100p
        # TP or the EOD flatten.
        _trend_v3_um = (
            str(st.get("mode") or "").upper() in _TREND_V3_UM_MODES
        )
        # 2026-08-15 range-mode BB flip mode — scale-out is DISABLED for
        # any range-mode BB position (sole exits: BB_RANGE_TARGET, BB_FLIP,
        # broker stop, NY_CLOSE). Prevents scale-out from installing a BE that would
        # take over from the broker SL and flatten a flippable runner.
        _range_mode_flip = bool(meta.get("range_mode_flip"))
        # 2026-08-20 level_ladder — a ladder-managed position rides to the
        # next pivot rung and back to structure; scale-out would install a
        # BE that competes with the ladder's ratchet. Inert under the
        # default LADDER_ENABLED=0.
        try:
            import level_ladder as _ll
            _ll_mode = str(st.get("mode") or "").upper()
            _ladder_managed = _ll.is_ladder_active(f"{epic}|{_ll_mode}")
        except Exception:
            _ladder_managed = False
        # 2026-09-29 Repair 3 — ONE_STRATEGY positions are HOLD-oriented
        # per one_strategy_management.py docstring §5-9 ("HOLD WHILE THE
        # DEMONSTRATED MOVEMENT REMAINS VALID"). Legacy universal +10p
        # scale-out was never authorised for ONE_STRATEGY; when it fired
        # on Monday 2026-09-28 GBPUSD LONG (deal DIAAAAYJVP7PBA6) it
        # cascaded into the "scaled_ok_broker_be_authoritative"
        # STRUCTURE_EXIT suppression which left the residual with
        # thesis_invalidation_owner_status=NONE. Exempting ONE_STRATEGY
        # here restores the HOLD-oriented design intent. Legacy modes
        # are unaffected. See
        # reports-public/autobot_one_strategy_management_repair_20260929.md.
        _one_strategy = (str(st.get("mode") or "").upper() == "ONE_STRATEGY")
        if (SCALE_OUT_AT_10P_ENABLED and not _universal_scale_gated
                and not _ep_scale_blocked
                and not _news_cont_leg
                and not _level_bounce
                and not _trend_v3_um
                and not _range_mode_flip
                and not _ladder_managed
                and not _one_strategy
                and not meta.get("scaled_out")
                and float(best_pnl) >= SCALE_OUT_TRIGGER_PIPS):
            try:
                _scale_out_50pct(epic, pair, ppp, meta)
            except Exception as _so_exc:
                logger.warning(
                    "[SCALE_OUT] %s _scale_out_50pct raised: %s",
                    epic, _so_exc,
                )

        # ── BE-recover durable retry (2026-06-05, revised 2026-09-14) ──
        # If a scaled runner is not yet marked be_amend_ok, re-issue the
        # BE amend. The 2026-09-14 defect #9 revision removed the
        # one-shot `be_recover_attempted` latch — an ATTACHED_ORDER_
        # LEVEL_ERROR rejection now records BE_PENDING_MIN_DISTANCE and
        # the retry re-fires on subsequent ticks, gated by the
        # pre-flight defer + failure-aware backoff inside
        # `_amend_broker_sl`. Behaviour on success is unchanged.
        # Post-restart safety: pre-flight defer + IG's transactional
        # rejection contract mean the broker's last-accepted stop is
        # preserved through repeated failures.
        if (meta.get("scaled_out") and not meta.get("be_amend_ok")
                and not meta.get("range_mode_flip")):
            try:
                _entry = _safe_float(st.get("entry_price"))
                _direction = str(st.get("direction") or "").upper()
                _tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
                if _entry is not None and _direction in ("BUY", "SELL"):
                    if _direction == "BUY":
                        _runner_tp_price = _entry + _tp_pips * float(ppp)
                    else:
                        _runner_tp_price = _entry - _tp_pips * float(ppp)
                    _ok = _amend_broker_sl(epic, new_sl_price=_entry,
                                           current_tp_price=_runner_tp_price)
                    st["be_amend_ok"] = bool(_ok)
                    meta["be_amend_ok"] = bool(_ok)
                    # Preserve legacy field name for downstream reads
                    # that gate on "we already tried at least once".
                    meta["be_recover_attempted"] = True
                    if _ok:
                        meta.pop("be_pending_min_distance", None)
                        meta.pop("be_pending_min_distance_since", None)
                        logger.info(
                            "[BE_RECOVER] %s ✓ BE amend accepted → be_amend_ok=True "
                            "(entry=%.5f, runner_tp=%.5f)",
                            epic, _entry, _runner_tp_price,
                        )
                    else:
                        _reject_reason = str(
                            meta.get("last_amend_reject_reason") or ""
                        ).upper()
                        _suppressed = bool(
                            meta.get("_sl_amend_last_suppressed", False)
                        )
                        _min_dist = (
                            _reject_reason == "ATTACHED_ORDER_LEVEL_ERROR"
                            or _suppressed
                        )
                        if _min_dist and not meta.get("be_pending_min_distance"):
                            meta["be_pending_min_distance"] = True
                            meta["be_pending_min_distance_since"] = time.time()
                            logger.warning(
                                "[BE_PENDING_MIN_DISTANCE] %s BE inside IG "
                                "min-stop corridor — retain existing broker "
                                "stop, retry on next qualifying tick "
                                "(reject=%s local_defer=%s)",
                                epic,
                                _reject_reason or "-",
                                "yes" if _suppressed else "no",
                            )
                        elif not _min_dist:
                            # Non-min-distance failure — keep the historical
                            # WARNING so operator visibility on non-recoverable
                            # errors (network, credentials, missing state)
                            # matches pre-defect-#9 behaviour.
                            logger.warning(
                                "[BE_RECOVER] %s BE amend FAILED — "
                                "structure_exit remains active as -10p safety net; "
                                "bb_bounce trail will not engage (reject=%s).",
                                epic, _reject_reason or "-",
                            )
            except Exception as _be_rec_exc:
                logger.warning(
                    "[BE_RECOVER] %s exception: %s",
                    epic, _be_rec_exc,
                )
                # Do NOT latch be_recover_attempted here — the exception
                # may be transient (session refresh, module import); a
                # tick later the retry can still succeed.

        # ── Phase 3 regime-keyed profile dispatch ──────────────────────
        # When REGIME_MGMT_ENABLED=1 and st carries a profile_id in
        # _PROFILE_MANAGED (STRONG or FORMING), route management to the
        # profile-specific manager and SKIP the legacy multiplex below.
        # RANGE and LEGACY / None fall through to the legacy path
        # unchanged so the range-scalp path and every non-profile
        # strategy are byte-identical to pre-Phase 3.
        try:
            if _dispatch_profile_management(
                epic, epic, st, meta, pair, ppp, best_pnl,
            ):
                _persist_profit_state()
                return
        except Exception as _pd_exc:
            logger.warning(
                "[PROFILE] %s _dispatch_profile_management raised: %s "
                "— falling through to legacy multiplex",
                epic, _pd_exc,
            )

        # ── Trend-style runner trail (post scale-out) ──────────────────
        # Ratchets broker SL upward as the runner extends. Only engages
        # for modes in _TREND_RUNNER_STYLE_MODES and only when scaled_out.
        # Non-trend scaled runners ride BE+TP unchanged.
        try:
            _apply_trend_runner_trail(epic, epic, st, meta, pair, ppp, best_pnl)
        except Exception as _tr_exc:
            logger.warning(
                "[TREND_TRAIL] %s _apply_trend_runner_trail raised: %s",
                epic, _tr_exc,
            )

        # ── BB_BOUNCE runner trail (post scale-out) ────────────────────
        # 2026-06-05. Smooth peak-pivot trail, activate ≥+12p, lock=peak-6p.
        # Same SL primitive as scale-out's BE — one SL path per position.
        # Self-gated on enable flag + mode + scaled_out + be_amend_ok.
        try:
            _apply_bb_bounce_runner_trail(epic, epic, st, meta, pair, ppp, best_pnl)
        except Exception as _bb_exc:
            logger.warning(
                "[BB_TRAIL] %s _apply_bb_bounce_runner_trail raised: %s",
                epic, _bb_exc,
            )

        # ── BB_BOUNCE post-scale runner floor (2026-07-01) ─────────────
        # Ratchet-up-only floor at +5p, arms once peak ≥ +10p post-scale.
        # Applies to BOTH L and S. Writes the SAME meta lock as the L trail
        # (bb_bounce_trail_lock_pips) — pure max() composition, floor never
        # fights the trail. Must run AFTER the trail so a same-tick trail
        # ratchet is respected; the floor's `proposed <= prior` guard then
        # no-ops. Self-gated on enable flag + mode + scaled_out + be_amend_ok.
        try:
            _apply_bb_bounce_post_scale_floor(epic, epic, st, meta, pair, ppp, best_pnl)
        except Exception as _bbf_exc:
            logger.warning(
                "[BB_FLOOR] %s _apply_bb_bounce_post_scale_floor raised: %s",
                epic, _bbf_exc,
            )

        # ── EMA_PULLBACK runner trail (post scale-out) ─────────────────
        # 2026-07-20. Peak-pivot trail via _apply_peak_pivot_runner_trail_core
        # (same primitive as BB_BOUNCE). Defaults 20/8 (activate/offset).
        # Self-gated on EMA_PULLBACK_RUNNER_TRAIL_ENABLED + mode +
        # scaled_out + be_amend_ok. When kill-switched OFF, runner sits
        # at BE installed by scale-out and rides broker TP / structure_exit
        # / REGIME_MAX_HOLD only.
        try:
            _apply_ema_pullback_runner_trail(epic, epic, st, meta, pair, ppp, best_pnl)
        except Exception as _ep_exc:
            logger.warning(
                "[EMA_PB_TRAIL] %s _apply_ema_pullback_runner_trail raised: %s",
                epic, _ep_exc,
            )

        # ── STRUCTURE_BREAK runner trail (post scale-out) ──────────────
        # 2026-06-15. Continuous peak-pivot trail, lock=peak-OFFSET (8p),
        # no activation threshold (BE floor enforced via max(0,...)).
        # Distinct mode set from TREND/BB_BOUNCE; self-gated on mode +
        # scaled_out + be_amend_ok.
        try:
            _apply_structure_break_runner_trail(epic, epic, st, meta, pair, ppp, best_pnl)
        except Exception as _sb_exc:
            logger.warning(
                "[SB_TRAIL] %s _apply_structure_break_runner_trail raised: %s",
                epic, _sb_exc,
            )

        # ── NEWS_STRATEGY_CONT runner trail (post scale-out) ───────────
        # 2026-07-03. Peak-pivot trail, activate=20p, lock=peak-12p.
        # Wider than BB_BOUNCE (12/6) because news whipsaws (06-11 SELL
        # ran the right direction +38.9p but only AFTER hitting SL first;
        # a tight trail gets chopped by the two-way spike). Ceiling
        # backstop is the fade cap TP set at fire time in news_strategy.py.
        # Self-gated on enable flag + mode==NEWS_STRATEGY_CONT +
        # scaled_out + be_amend_ok — no-op for FADE and all other modes.
        try:
            _apply_news_cont_runner_trail(epic, epic, st, meta, pair, ppp, best_pnl)
        except Exception as _nc_exc:
            logger.warning(
                "[NEWS_TRAIL] %s _apply_news_cont_runner_trail raised: %s",
                epic, _nc_exc,
            )

        _persist_profit_state()

    def _clear_profit_meta(self, epic: str) -> None:
        try:
            _PROFIT_MGMT_BY_EPIC.pop(str(epic), None)
        except Exception:
            pass

    # --------------------------------------------------------
    # TM v2 consultation (§51–§63) — ruling 2026-09-24 §3 cadence
    # --------------------------------------------------------
    def _maybe_consult_tm_v2(
        self,
        *,
        epic: str,
        st: Dict[str, Any],
        mid_price: float,
        entry: float,
        pip_size: float,
        direction: str,
    ) -> None:
        """Consult trade_manager_v2 for the §51-§63 exit-authority
        diagnosis when TRADE_MANAGER_LIVE=1. Ruling 2026-09-24 §3:
        causal 5-minute bar-close cadence. Per-tick polling MUST NOT
        produce multiple recommendations for the same completed 5-minute
        bar. Dedup key = (deal_id, floor(now_utc, 5min)) — the first
        tick inside each 5m window that reaches this hook produces the
        shadow row; subsequent ticks in the same window are no-ops.

        Ruling §3 also requires GENUINE recent_bars: real closed 5m
        candles up to and including the most recent bar_open. The seam
        reuses tm_corpus_writer._load_causal_bars so V2's bounce +
        deterioration primitives see the same history the Phase 13
        sweep sees. Ruling §5 freshness is surfaced via
        news_trend_classifier.snapshot(symbol)['snapshot_staleness_seconds'].

        Wiring-rule citations for TM v2:
          * Initializer — trade_manager_v2.py:72 (TRADE_MANAGER_LIVE
            read at import).
          * Driver      — this hook (trade_manager.py, per-position
            poll from _monitor_profit_protection; bar-close-deduplicated).
          * Consumer    — logs/tm_shadow.jsonl (append per bar-close per
            deal). §66 grader reads this row + realised outcome. Kept
            in parallel with the Phase 13 corpus log per ruling §4
            for parity/provenance during this increment.
        """
        _live_flag = str(os.getenv("TRADE_MANAGER_LIVE", "0")).strip().lower()
        if _live_flag not in ("1", "true", "yes", "on"):
            return
        try:
            import trade_manager_v2 as _tmv2
        except Exception as exc:
            logger.debug("[TM-V2] import failed: %s", exc)
            return
        try:
            from datetime import datetime, timedelta, timezone
            # ── Ruling §3 cadence: floor now → 5m bar-open. Dedup by
            # (deal_id, bar_open_iso) so per-tick polling emits one
            # shadow row per completed 5m window per position.
            now = datetime.now(timezone.utc)
            bar_open_dt = now.replace(
                minute=(now.minute // 5) * 5,
                second=0, microsecond=0,
            )
            bar_open_iso = bar_open_dt.isoformat()
            deal_id = str(st.get("deal_id") or st.get("_deal_id") or "")
            if deal_id:
                _cache = _TMV2_SEAM_BAR_KEY  # module-level dedup dict
                if _cache.get(deal_id) == bar_open_iso:
                    return
                _cache[deal_id] = bar_open_iso

            open_ts = _safe_float(st.get("open_time"), None)
            entry_ts = (
                datetime.fromtimestamp(open_ts, tz=timezone.utc)
                if open_ts else datetime.now(timezone.utc)
            )
            price = float(mid_price)
            # Signed pnl pips (positive = favourable).
            if direction == "BUY":
                pnl_pips = (price - entry) / pip_size
            else:
                pnl_pips = (entry - price) / pip_size
            mfe_pips = float(st.get("mfe_pips") or max(pnl_pips, 0.0))
            mae_pips = float(st.get("mae_pips") or max(-pnl_pips, 0.0))
            symbol = (
                _pair_from_epic(epic)
                if callable(globals().get("_pair_from_epic"))
                else str(epic)
            )
            # ── Ruling §3: genuine recent_bars from the candle archive.
            recent_bars: tuple = ()
            try:
                import tm_corpus_writer as _tm_cw
                _bars = _tm_cw._load_causal_bars(symbol, bar_open_iso)
                # Newest tail — V2 default bounce window is ~20 bars.
                _tail_n = int(os.getenv("TM_V2_RECENT_BARS", "20"))
                _tail = _bars[-_tail_n:] if _tail_n > 0 else []
                recent_bars = tuple(
                    (b["ts"], b["open"], b["high"], b["low"], b["close"])
                    for b in _tail
                )
            except Exception as _rb_exc:
                logger.debug("[TM-V2] recent_bars load failed: %s", _rb_exc)
            # Use the most recent CLOSED bar's ts+OHLC as the snap's
            # "current bar" (causal). If archive load returned nothing
            # (weekend / early boot) fall back to a synthetic single
            # bar so V2 still runs.
            if recent_bars:
                _last = recent_bars[-1]
                bar_ts_snap = _last[0]
                bar_o, bar_h, bar_l, bar_c = _last[1], _last[2], _last[3], _last[4]
            else:
                bar_ts_snap = bar_open_dt
                bar_o = bar_h = bar_l = bar_c = price

            # ── Ruling §5: freshness from news_trend_classifier snapshot.
            ctx_staleness = None
            try:
                import news_trend_classifier as _ntc
                _news = _ntc.snapshot(symbol)
                if isinstance(_news, dict):
                    ctx_staleness = _news.get("snapshot_staleness_seconds")
            except Exception as _fr_exc:
                logger.debug("[TM-V2] news_trend snapshot failed: %s", _fr_exc)

            snap = _tmv2.TradeSnapshot(
                symbol=symbol,
                direction=direction,
                entry_price=float(entry),
                entry_ts=entry_ts,
                deal_id=deal_id,
                strategy=str(st.get("mode") or ""),
                bar_ts=bar_ts_snap if hasattr(bar_ts_snap, "isoformat") else bar_open_dt,
                bar_open=float(bar_o), bar_high=float(bar_h),
                bar_low=float(bar_l), bar_close=float(bar_c),
                recent_bars=recent_bars,
                pip_size=float(pip_size),
                current_pnl_pips=float(pnl_pips),
                mfe_pips=float(mfe_pips),
                mae_pips=float(mae_pips),
                actual_stop_price=_safe_float(st.get("stop_price"), None),
                actual_position_size=_safe_float(st.get("size"), None),
                exit_stack_name=str(st.get("exit_stack") or ""),
            )
            try:
                decision = _tmv2.diagnose(
                    snap,
                    extra_ctx={"context_staleness_seconds": ctx_staleness},
                )
            except TypeError:
                # Back-compat for a tm_v2 that predates extra_ctx.
                decision = _tmv2.diagnose(snap)
            row = _tmv2.shadow_row(snap, decision, actual_action=None)
            # Stamp the freshness signal + bar-close cadence marker so
            # parity checks can distinguish per-bar rows.
            try:
                row["context_staleness_seconds"] = ctx_staleness
                row["seam_bar_open"] = bar_open_iso
                row["seam_cadence"] = "5m_bar_close"
            except Exception:
                pass
            try:
                import json as _json
                import os as _os
                path = _tmv2.SHADOW_LOG_PATH
                _os.makedirs(_os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(_json.dumps(row, default=str, sort_keys=True) + "\n")
            except Exception as _wr_exc:
                logger.debug("[TM-V2] shadow write failed: %s", _wr_exc)
        except Exception as exc:
            logger.debug("[TM-V2] consult inner raised: %s", exc)

    # --------------------------------------------------------
    # Sweep-specific live management
    # --------------------------------------------------------
    def _monitor_liquidity_sweep(
        self,
        epic: str,
        mid_price: float,
        bid: Any = None,
        ask: Any = None,
        macd_hist: Any = None,
        prev_macd_hist: Any = None,
        sweep_extreme: Any = None,
    ) -> None:
        """
        Post-entry sweep management philosophy:
        - Do NOT demand classic trend momentum at entry.
        - Once in, require the reversal to prove itself within a probation window.
        - If it stalls / goes nowhere, cut it early instead of waiting for full SL.
        - If it develops, let executor's BE/trailing logic continue to manage the runner.
        """
        st = _state_for_epic(epic)
        if not st.get("active"):
            self._clear_sweep_meta(epic)
            return
        if not _is_liquidity_sweep_mode(st.get("mode")):
            self._clear_sweep_meta(epic)
            return

        entry = _safe_float(st.get("entry_price"), None)
        pip_size = _safe_float(st.get("pip_size"), None)
        direction = str(st.get("direction") or "").upper()
        open_time = _safe_float(st.get("open_time"), None)

        if entry is None or pip_size is None or pip_size <= 0 or direction not in ("BUY", "SELL"):
            return

        now = time.time()
        age_s = max(0.0, now - float(open_time or now))
        current = _effective_price_for_management(direction, float(mid_price), bid=bid, ask=ask)
        pnl_pips = _calculate_pnl_pips(direction, float(entry), float(current), float(pip_size))

        meta = _SWEEP_MGMT_BY_EPIC.get(epic)
        if meta is None:
            meta = {
                "created_ts": now,
                "best_pnl_pips": pnl_pips,
                "last_progress_ts": now,
                "probation_done": False,
                "momentum_confirmed": False,
                "trail_armed": False,
            }
            _SWEEP_MGMT_BY_EPIC[epic] = meta
        else:
            best_prev = _safe_float(meta.get("best_pnl_pips"), pnl_pips)
            if best_prev is None:
                best_prev = pnl_pips
            if pnl_pips > float(best_prev) + 0.05:
                meta["best_pnl_pips"] = pnl_pips
                meta["last_progress_ts"] = now
            else:
                meta["best_pnl_pips"] = max(float(best_prev), float(pnl_pips))

        # Optional post-entry momentum observation.
        momentum_ok: Optional[bool] = None
        mh = _safe_float(macd_hist, None)
        pmh = _safe_float(prev_macd_hist, None)
        if mh is not None and pmh is not None:
            if direction == "BUY":
                momentum_ok = bool(mh > pmh)
            else:
                momentum_ok = bool(mh < pmh)
            if momentum_ok:
                meta["momentum_confirmed"] = True

        # Optional sweep-extreme retest invalidation (only if caller supplies sweep_extreme).
        if SWEEP_EXTREME_RETEST_ENABLED:
            sx = _safe_float(sweep_extreme, None)
            if sx is not None:
                tol_pts = float(SWEEP_EXTREME_RETEST_TOLERANCE_PIPS) * float(pip_size)
                if direction == "BUY":
                    if float(current) <= float(sx) + float(tol_pts):
                        logger.info(
                            f"[{epic}] sweep extreme retest fail: cur={current:.5f} extreme={sx:.5f} tol_pts={tol_pts:.5f}"
                        )
                        _exec.close_position(
                            epic=epic,
                            reason="SWEEP_EXTREME_RETEST",
                            exit_hint_price=float(current),
                        )
                        self._clear_sweep_meta(epic)
                        self._clear_profit_meta(epic)
                        return
                else:
                    if float(current) >= float(sx) - float(tol_pts):
                        logger.info(
                            f"[{epic}] sweep extreme retest fail: cur={current:.5f} extreme={sx:.5f} tol_pts={tol_pts:.5f}"
                        )
                        _exec.close_position(
                            epic=epic,
                            reason="SWEEP_EXTREME_RETEST",
                            exit_hint_price=float(current),
                        )
                        self._clear_sweep_meta(epic)
                        self._clear_profit_meta(epic)
                        return

        best_pnl = _safe_float(meta.get("best_pnl_pips"), pnl_pips)
        if best_pnl is None:
            best_pnl = pnl_pips

        # Probation check: if the sweep has not separated from entry enough,
        # close it early instead of waiting for a full SL.
        if SWEEP_PROBATION_ENABLED:
            if age_s >= float(SWEEP_PROBATION_SECONDS) and not bool(meta.get("probation_done")):
                _pair = _pair_from_epic(epic)
                _min_progress = SWEEP_MIN_PROGRESS_PIPS_OVERRIDES.get(_pair, SWEEP_MIN_PROGRESS_PIPS)
                fail_for_no_progress = float(best_pnl) < float(_min_progress)

                fail_for_momentum = False
                if SWEEP_REQUIRE_POST_ENTRY_MOMENTUM and age_s >= float(SWEEP_MOMENTUM_GRACE_SECONDS):
                    if momentum_ok is False and not bool(meta.get("momentum_confirmed")):
                        fail_for_momentum = True

                if fail_for_no_progress or fail_for_momentum:
                    logger.info(
                        f"[{epic}] sweep probation fail: age={age_s:.1f}s best_pnl={best_pnl:.2f} "
                        f"cur_pnl={pnl_pips:.2f} momentum_ok={momentum_ok}"
                    )
                    _exec.close_position(
                        epic=epic,
                        reason="SWEEP_STALLED_PROBATION",
                        exit_hint_price=float(current),
                    )
                    self._clear_sweep_meta(epic)
                    self._clear_profit_meta(epic)
                    return

                meta["probation_done"] = True

            # Longer-horizon stall check after probation.
            if age_s >= float(SWEEP_STALL_SECONDS):
                if float(best_pnl) < float(SWEEP_STALL_GRACE_PIPS):
                    logger.info(
                        f"[{epic}] sweep stall exit: age={age_s:.1f}s best_pnl={best_pnl:.2f} cur_pnl={pnl_pips:.2f}"
                    )
                    _exec.close_position(
                        epic=epic,
                        reason="SWEEP_STALL_NO_PROGRESS",
                        exit_hint_price=float(current),
                    )
                    self._clear_sweep_meta(epic)
                    self._clear_profit_meta(epic)
                    return

        # GBPUSD V1/V3 sweeps: hold to TP1, no sweep trail — SL or TP1 only
        _entry_src = str(st.get("entry_source", "") or "")
        _is_gbp_v1v3 = (
            _pair_from_epic(epic) in ("GBPUSD", "GBPJPY")
            and any(_entry_src.startswith(f"sweep_v{v}") for v in (1, 3))
        )
        if _is_gbp_v1v3:
            return

        # Software trailing stop (sweep-specific).
        # Uses regime exit_config if available, falls back to env constants.
        _sw_ppp = _ppp(epic)
        _r_exit = meta.get("regime_exit") or {}
        _r_trail_activate = float(_r_exit.get("trail_activate_pips", SWEEP_TRAIL_ACTIVATE_PIPS))
        _r_trail_distance = float(_r_exit.get("trail_distance_pips", SWEEP_TRAIL_OFFSET_PIPS))
        if not bool(meta.get("trail_armed")) and float(best_pnl) >= _r_trail_activate * _sw_ppp:
            meta["trail_armed"] = True
            logger.info(
                f"[{epic}] sweep software trail armed: best_pnl={best_pnl:.2f} "
                f"offset={_r_trail_distance * _sw_ppp:.2f} (regime={_r_exit.get('max_hold_minutes', '?')}m)"
            )

        if bool(meta.get("trail_armed")):
            # Consolidation hold: freeze floor by using snapshot best_pnl
            meta["_consol_active"] = _is_consolidation_active(epic)
            floor_best_pnl = _apply_consolidation_hold(meta, best_pnl)

            trail_floor = max(
                float(floor_best_pnl) - _r_trail_distance * _sw_ppp,
                float(SWEEP_TRAIL_FLOOR_MIN_PIPS) * _sw_ppp,
            )
            breach_level = trail_floor - float(SWEEP_TRAIL_EPSILON_PIPS) * _sw_ppp
            if float(pnl_pips) <= breach_level:
                logger.info(
                    f"[{epic}] sweep software trail hit: cur_pnl={pnl_pips:.2f} "
                    f"best_pnl={best_pnl:.2f} trail_floor={trail_floor:.2f} "
                    f"min_floor={SWEEP_TRAIL_FLOOR_MIN_PIPS:.2f}"
                )
                _exec.close_position(
                    epic=epic,
                    reason="SWEEP_TRAIL_STOP",
                    exit_hint_price=float(current),
                )
                self._clear_sweep_meta(epic)
                self._clear_profit_meta(epic)
                return

        # If the executor already closed the trade via BE/trail/etc, clear metadata.
        if not st.get("active"):
            self._clear_sweep_meta(epic)
            self._clear_profit_meta(epic)

    def _clear_sweep_meta(self, epic: str) -> None:
        try:
            _SWEEP_MGMT_BY_EPIC.pop(str(epic), None)
        except Exception:
            pass

    def _clear_consolidation_meta(self, epic: str) -> None:
        try:
            _CONSOLIDATION_BY_EPIC.pop(str(epic), None)
        except Exception:
            pass

    # --------------------------------------------------------
    # IG open positions monitoring (minimal external close detect)
    # --------------------------------------------------------
    def _check_ig_open_positions_for_external_close(self) -> None:
        active_items = []
        try:
            active_items = [
                (str(pk), st)
                for pk, st in TRADE_STATE_BY_EPIC.items()
                if isinstance(st, dict) and st.get("active")
            ]
        except Exception:
            active_items = []

        if not active_items:
            # Fallback to legacy single-state view if needed.
            try:
                if self.state.get("active"):
                    active_items = [(_safe_str(self.state.get("epic") or "UNKNOWN"), self.state)]
            except Exception:
                active_items = []

        if not active_items:
            return

        open_pos = get_open_positions()
        if open_pos is None:
            logger.warning("[TRADE_MANAGER] get_open_positions returned None; skipping external close check")
            return
        items = _extract_positions_list(open_pos)

        for state_pk, state_obj in active_items:
            deal_id = _safe_str(state_obj.get("deal_id") or state_obj.get("dealId") or "")
            real_epic = state_obj.get("epic") or (_exec._epic_from_pos_key(state_pk) if "|" in state_pk else state_pk)
            if not real_epic and not deal_id:
                continue

            if deal_id and self._last_external_close_alerted_deal_id == deal_id:
                continue

            found = False
            for item in items:
                if _position_matches_trade_state(item, deal_id=deal_id or None, epic=real_epic or None):
                    found = True
                    break

            if found:
                continue

            # ── Stamp-first check (2026-08-03) ─────────────────────────────
            # Before treating this vanished position as external/manual,
            # consult the close-intent journal. Any close_trade() /
            # scale-out that owns this position has stamped its deal_id
            # BEFORE issuing the OTC POST (see close_sb_now
            # ._close_position_by_deal + close_intent_journal.record_intent),
            # so a recent intent stamp is authoritative proof this is a
            # bot-driven close. The reconciler must not double-alert.
            #
            # Motivating incidents (2026-08-03):
            #   06:35:01 GBPUSD structure exit → 06:35:03 external Telegram
            #   14:30    EURUSD SL sweep       →         external Telegram
            # In both cases the pre-reset state_obj still carried
            # `close_reason`, but by the time close_trade re-fired it saw
            # the reset (`active=False`) state and returned None, and the
            # fallback path emitted the wrong external-close alert.
            if deal_id:
                _stamped, _stamp_row = _close_intent_has_recent(
                    deal_id, RECONCILE_STAMP_GRACE_S,
                )
                if _stamped:
                    logger.debug(
                        "[TRADE_MANAGER] external-close sweep: skipping pos_key=%s "
                        "deal_id=%s — close-intent journal shows bot-driven close "
                        "(path=%r reason=%r partial=%s ts=%s, within %.1fs grace)",
                        state_pk, deal_id,
                        _stamp_row.get("path") if _stamp_row else "?",
                        _stamp_row.get("expected_reason") if _stamp_row else "?",
                        _stamp_row.get("partial") if _stamp_row else "?",
                        _stamp_row.get("ts_utc") if _stamp_row else "?",
                        RECONCILE_STAMP_GRACE_S,
                    )
                    # Record so the same deal_id can't be re-considered
                    # this poll cycle (defensive; the check above already
                    # short-circuits on repeat).
                    self._last_external_close_alerted_deal_id = deal_id
                    continue

            exit_hint = (
                state_obj.get("last_mid")
                or state_obj.get("exit_price")
                or state_obj.get("entry_price")
                or None
            )

            close_reason = _detect_ig_close_reason(state_obj, exit_hint, pos_key=state_pk)

            # Prime exit_price + close_reason on the state object so the
            # downstream close_trade() path reports the IG-detected values
            # (PnL, alert, signal_log outcome) rather than defaulting.
            state_obj["exit_price"] = exit_hint

            # Race-guard (2026-06-12): if a bot-driven exit path
            # (structure_exit, REGIME_MAX_HOLD, BB_REVERSAL leg close, etc.)
            # already stamped close_reason on this state object this tick,
            # do NOT overwrite it with the sweep's classification. The
            # state object is reset to close_reason=None at trade open
            # (trade_executor.py:1316), so any truthy value means an
            # in-flight bot close already owns the label.
            #
            # NOTE: this is a belt-and-braces fallback for the pre-journal
            # race. The stamp-first check above is the authoritative guard.
            # We keep this branch so that if the journal write ever fails
            # silently, we still degrade in the safe direction.
            _existing_reason = str(state_obj.get("close_reason") or "").strip()
            if _existing_reason:
                logger.info(
                    "[TRADE_MANAGER] external-close sweep deferring label "
                    "for pos_key=%s — bot-driven exit already stamped "
                    "close_reason=%r (sweep would have set %r); "
                    "no external Telegram will be sent",
                    state_pk, _existing_reason, close_reason,
                )
                # Attempt to converge state via close_trade so callbacks
                # fire once, but SUPPRESS the fallback external-close
                # alert — a bot exit label is present, this is not an
                # external close by definition.
                try:
                    _exec.close_trade(state_pk)
                except Exception:
                    logger.exception(
                        "[TRADE_MANAGER] close_trade raised while converging "
                        "bot-stamped close for pos_key=%s", state_pk,
                    )
                self._clear_sweep_meta(state_pk)
                self._clear_profit_meta(state_pk)
                self._clear_consolidation_meta(state_pk)
                if deal_id:
                    self._last_external_close_alerted_deal_id = deal_id
                continue

            state_obj["close_reason"] = close_reason

            # Route broker-initiated closes through close_trade() so the
            # _CLOSE_CALLBACKS chain fires — that's what patches
            # signal_log.jsonl (the outcome=null bug) and converges
            # strategy state (e.g. bb_reversal legs) via the same path
            # bot-initiated closes take. close_trade() handles
            # already-closed positions safely via its broker_side_close
            # branch (trade_executor.py:1117-1148).
            closed_via_callbacks = False
            try:
                closed_via_callbacks = bool(_exec.close_trade(state_pk))
            except Exception:
                logger.exception(
                    "[TRADE_MANAGER] close_trade raised for external-close pos_key=%s",
                    state_pk,
                )

            if not closed_via_callbacks:
                # Callbacks didn't fire (close_trade returned None or threw).
                # Fall back to the prior local-only path so the event isn't
                # lost — alert, then clear state. This is the single legit
                # external-close Telegram site.
                self._send_external_close_alert_best_effort(
                    epic=real_epic or None,
                    deal_id=deal_id or None,
                    direction=str(state_obj.get("direction") or ""),
                    entry_price=state_obj.get("entry_price"),
                    exit_price=exit_hint,
                    pnl_pips=None,
                    reason=close_reason,
                )
                self._clear_state_external_close(
                    epic=state_pk,
                    reason="external/manual close (IG monitor)",
                )

            self._clear_sweep_meta(state_pk)
            self._clear_profit_meta(state_pk)
            self._clear_consolidation_meta(state_pk)
            if deal_id:
                self._last_external_close_alerted_deal_id = deal_id

    # --------------------------------------------------------
    # Naked-foreign-position sweep (2026-08-03)
    # --------------------------------------------------------
    def _load_foreign_alert_state(self) -> Dict[str, str]:
        """Load {deal_id: last_alert_utc_date} from the dedup state file.
        Returns {} on any error (missing file, malformed JSON) — a missed
        dedup risks a duplicate alert, not a silent trade."""
        if not hasattr(self, "_foreign_alert_mem"):
            self._foreign_alert_mem = None
        if self._foreign_alert_mem is not None:
            return self._foreign_alert_mem
        state: Dict[str, str] = {}
        try:
            if FOREIGN_POSITION_ALERT_STATE_PATH.exists():
                with FOREIGN_POSITION_ALERT_STATE_PATH.open("r", encoding="utf-8") as fh:
                    data = _json_stdlib.load(fh)
                    if isinstance(data, dict):
                        state = {str(k): str(v) for k, v in data.items()}
        except Exception as exc:
            logger.warning("[FOREIGN_ALERT] state load failed: %s", exc)
        self._foreign_alert_mem = state
        return state

    def _save_foreign_alert_state(self) -> None:
        """Persist the in-memory dedup map. Best-effort — write failures
        degrade to "may re-alert on restart" which is acceptable."""
        try:
            FOREIGN_POSITION_ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = FOREIGN_POSITION_ALERT_STATE_PATH.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                _json_stdlib.dump(self._foreign_alert_mem or {}, fh)
            tmp.replace(FOREIGN_POSITION_ALERT_STATE_PATH)
        except Exception as exc:
            logger.warning("[FOREIGN_ALERT] state save failed: %s", exc)

    def _pos_created_epoch(self, pos: dict) -> Optional[float]:
        """Parse createdDate / createdDateUTC → epoch seconds. IG returns
        either 'YYYY/MM/DD HH:MM:SS:sss' (createdDate, local BST) or ISO-ish
        'YYYY-MM-DDTHH:MM:SS' (createdDateUTC). We prefer the UTC field."""
        for key in ("createdDateUTC", "createdDate"):
            raw = str(pos.get(key) or "").strip()
            if not raw:
                continue
            # Normalise IG's 'YYYY/MM/DD HH:MM:SS:sss' shape → ISO-ish.
            r = raw.replace("/", "-")
            # createdDate has millis as ':sss' (colon separator).
            if ":" in r and len(r) >= 21 and r[-4] == ":":
                r = r[:-4] + "." + r[-3:]
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    dt_ = datetime.strptime(r, fmt)
                    # createdDate is broker-local (BST). createdDateUTC is UTC.
                    # We can't reliably resolve the BST offset here, so we
                    # treat the parsed value as UTC (conservative — makes
                    # ages appear slightly older, never younger).
                    return dt_.replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    continue
        return None

    def _check_foreign_naked_positions(self) -> None:
        """Alert once per UTC day per deal_id on foreign positions with
        no stop attached. Foreign = not matched by ANY owned trade state
        on this host. Never touches the positions — alert-only.

        Motivating incident: 2026-08-03 14:35 UTC Johnny opened a MOBILE
        SELL on the shared account with no stop; forensics caught it at
        ~20:00. The bot has no line-of-sight to Johnny's phone, so a
        server-side sweep is the only reliable safety net."""
        if not FOREIGN_POSITION_ALERT_ENABLED:
            return
        try:
            open_pos = get_open_positions()
        except Exception as exc:
            logger.warning("[FOREIGN_ALERT] get_open_positions failed: %s", exc)
            return
        if open_pos is None:
            # API/network failure — position state is unknown; do NOT
            # assume all positions are foreign or we'd page on every
            # bot-owned trade.
            return
        items = _extract_positions_list(open_pos)
        if not items:
            return

        # Build the set of owned (deal_id, epic) tuples in one pass so
        # the O(items × owned) match is cheap.
        owned_deal_ids: set[str] = set()
        owned_epics: set[str] = set()
        try:
            for pk, st in TRADE_STATE_BY_EPIC.items():
                if not (isinstance(st, dict) and st.get("active")):
                    continue
                did = _safe_str(st.get("deal_id") or st.get("dealId") or "")
                if did:
                    owned_deal_ids.add(did)
                ep = _safe_str(st.get("epic") or "")
                if ep:
                    owned_epics.add(ep)
        except Exception:
            pass
        # Legacy single-state fallback (belt & braces).
        try:
            if self.state.get("active"):
                did = _safe_str(self.state.get("deal_id") or "")
                if did:
                    owned_deal_ids.add(did)
                ep = _safe_str(self.state.get("epic") or "")
                if ep:
                    owned_epics.add(ep)
        except Exception:
            pass

        state = self._load_foreign_alert_state()
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_epoch = time.time()
        age_threshold_s = float(FOREIGN_POSITION_ALERT_MIN) * 60.0
        state_changed = False

        for item in items:
            pos = item.get("position") if isinstance(item.get("position"), dict) else item
            market = item.get("market") if isinstance(item.get("market"), dict) else {}

            deal_id = _safe_str(pos.get("dealId") or pos.get("deal_id") or "")
            epic = _safe_str(pos.get("epic") or market.get("epic") or "")

            if not deal_id:
                # Nothing to dedup against — skip (extremely rare, IG
                # always returns dealId on the /positions payload).
                continue

            # Foreign check — deal_id match OR epic match to any owned state.
            if deal_id in owned_deal_ids:
                continue
            if epic and epic in owned_epics:
                # Could be a bot position whose state we lost sight of
                # (e.g. after a restart before signal_log rehydration).
                # Safer to skip than to spam.
                continue

            stop_level = pos.get("stopLevel")
            if stop_level not in (None, "", 0, 0.0):
                continue  # protected — not our problem

            created_ep = self._pos_created_epoch(pos)
            if created_ep is None:
                continue  # can't judge age
            age_s = now_epoch - created_ep
            if age_s < age_threshold_s:
                continue  # give the human a chance to attach a stop

            # Dedup: once per deal_id per UTC day.
            if state.get(deal_id) == today_utc:
                continue

            direction = _safe_str(pos.get("direction") or "").upper() or "?"
            size = pos.get("size")
            level = pos.get("level") or pos.get("openLevel") or pos.get("openLevelValue")
            open_ts = str(pos.get("createdDateUTC") or pos.get("createdDate") or "")
            age_min = int(round(age_s / 60.0))

            msg = (
                "⚠ Unprotected foreign position on shared account: "
                f"{direction} {size} {epic} @ {level}, open since {open_ts} "
                f"({age_min}m ago), no stop attached."
            )
            logger.warning("[FOREIGN_ALERT] %s (deal_id=%s)", msg, deal_id)

            sent = False
            try:
                # telegram_alerts.send() is the compat shim over
                # send_telegram_message that everything else in the codebase
                # uses; keeps the wire-format consistent with the rest of
                # the operator's inbox.
                from telegram_alerts import send as _tg_send  # type: ignore
                if callable(_tg_send):
                    _tg_send(msg)
                    sent = True
            except Exception:
                logger.exception("[FOREIGN_ALERT] telegram dispatch failed")
            _ = sent  # dedup logic below is unconditional — either the
            # telegram send worked (great), or it didn't (still logged as
            # WARNING above). Either way we mark the day-seen so a
            # broken telegram doesn't blast the operator on every poll.

            state[deal_id] = today_utc
            state_changed = True

        if state_changed:
            self._save_foreign_alert_state()

    def run_foreign_position_sweep(self) -> None:
        """Public entry point mirroring run_external_close_sweep — lets the
        rest_sweeps daemon drive the naked-position check on its own
        cadence."""
        try:
            self._check_foreign_naked_positions()
        except Exception as exc:
            logger.error("[FOREIGN_ALERT] sweep error: %s: %s", type(exc).__name__, exc)

    def _send_external_close_alert_best_effort(
        self,
        epic: Optional[str],
        deal_id: Optional[str],
        exit_price: Any,
        reason: str,
        direction: str = "",
        entry_price: Any = None,
        pnl_pips: Any = None,
    ) -> None:
        """
        Only sends if telegram_alerts.send_trade_close_alert exists.
        Keeps this file safe even if your telegram module doesn't have that function.
        """
        try:
            from telegram_alerts import send_trade_close_alert  # type: ignore

            if callable(send_trade_close_alert):
                send_trade_close_alert(
                    epic=epic,
                    direction=direction,
                    entry=entry_price,
                    exit_price=exit_price,
                    pnl_pips=pnl_pips,
                    pnl_cash=None,
                    reason=reason,
                    deal_id=deal_id,
                )
        except Exception:
            # Silent: monitoring should never crash trading.
            return

    def _clear_state_external_close(self, epic: str, reason: str) -> None:
        """
        Clear TRADE_STATE / per-epic state without sending any IG order.
        """
        try:
            _reset_trade_state(epic)
            st = _state_for_epic(epic)
            st["close_reason"] = reason
            return
        except Exception:
            pass

        try:
            self.state["active"] = False
            self.state["close_reason"] = reason
        except Exception:
            try:
                self.state["active"] = False
            except Exception:
                pass


# ============================================================
# BRIEFING INVALIDATION CHECK (all strategies, 5M close)
# ============================================================
BRIEF_INVALIDATION_ENABLED = (os.getenv("BRIEF_INVALIDATION_ENABLED", "1") or "1").strip() == "1"


def check_briefing_invalidation(payload: dict) -> None:
    """5M candle close callback: close any active trade whose briefing
    invalidation level has been breached.

    Called from the candle builder's 5M close callback chain.
    Applies to ALL strategies (WINDOW_SWEEP, EMA_PULLBACK, BRIEFING_SWEEP, etc.).
    BRIEFING_EXECUTION and BB_REVERSAL handle their own exits, so they are skipped.
    """
    if not BRIEF_INVALIDATION_ENABLED:
        return

    candle = payload.get("candle") or {}
    candle_close = candle.get("close")
    symbol = str(payload.get("symbol") or "").upper()
    if candle_close is None or not symbol:
        return
    candle_close = float(candle_close)

    # Iterate all active positions in EPIC_STATE
    for pk, st in list(_exec.EPIC_STATE.items()):
        if not st.get("active"):
            continue

        # Skip strategies that manage their own exits.
        # BRIEFING_EXECUTION has its own invalidation logic.
        # BB_REVERSAL exits on per-leg SL/TP only; the briefing invalidation
        # direction may not match a given BB_REVERSAL leg's direction.
        # NEWS_TICK / NEWS_STRATEGY fire on actual news data, not briefing
        # structure — the inherited invalidation_price (set blanket on every
        # EPIC_STATE entry by trade_executor.py:986) is irrelevant to news
        # context. Added 2026-04-28 after 2/9 NEWS_TICK trades (USDJPY
        # 04-21 23:50 and 04-22 00:00) closed at briefing-rollover boundaries.
        mode = str(st.get("mode") or "").upper()
        if mode in (
            "BRIEFING_EXECUTION", "BB_REVERSAL", "NEWS_TICK", "NEWS_STRATEGY",
            # GBPUSD_RAW_REVERSAL fires AGAINST the briefing-implied trend at
            # exhaustion. The blanket invalidation_price written to EPIC_STATE
            # at open time is not meaningful for a counter-move setup — exempt.
            "GBPUSD_RAW_REVERSAL_L", "GBPUSD_RAW_REVERSAL_S",
            # GBPUSD_BB_BOUNCE — pure BB-pierce-and-recover, decoupled from
            # briefing thesis by design. Same exemption rationale.
            "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
            # GBPUSD_BB_REV_PAT — same BB-fade family as BB_BOUNCE,
            # decoupled from briefing thesis. Same exemption rationale.
            "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
            # GBPUSD_EMA_PULLBACK — geometric BB-touch → EMA-pierce
            # continuation. Direction comes from the 5M-stack trend +
            # band-of-origin, not from briefing structure — exempt.
            "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
            # GBPUSD_TREND_L/S — cascade-driven trend strategy with its
            # own cascade-flip exit. Briefing thesis is informational
            # only for this strategy (the cascade is the directional
            # truth, not the daily briefing). Added 2026-05-13.
            "GBPUSD_TREND_L", "GBPUSD_TREND_S",
            # GBPUSD_LEVEL_BOUNCE_L/S — unmanaged three-candle level
            # bounce. Trade direction is chosen by BB pierce vs outer
            # pivot, decoupled from the daily briefing thesis. 100p SL
            # is the sole exit; briefing invalidation must not fire.
            "GBPUSD_LEVEL_BOUNCE_L", "GBPUSD_LEVEL_BOUNCE_S",
            # 2026-08-14 GBPUSD_TREND_V3_UM_L/S — unmanaged variant of
            # TREND_V3 (12p SL / 100p TP / EOD flatten). Same rationale
            # as LEVEL_BOUNCE: decoupled from the briefing thesis; the
            # variant's whole point is to ride an already-certified
            # trend without briefing/structural early exits.
            "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
        ):
            continue

        inv_price = st.get("invalidation_price")
        inv_dir = st.get("invalidation_direction")
        if inv_price is None or inv_dir is None:
            continue

        # Match symbol — extract pair from the pos_key's epic portion
        epic = str(st.get("epic") or pk.split("|")[0])
        pair = _pair_from_epic(epic)
        if pair != symbol:
            continue

        triggered = False
        if inv_dir == "above" and candle_close > inv_price:
            triggered = True
        elif inv_dir == "below" and candle_close < inv_price:
            triggered = True

        if not triggered:
            continue

        direction = st.get("direction", "")
        entry = st.get("entry_price") or 0
        ppp = _ppp(pair)
        current = candle_close
        if direction == "BUY":
            pnl_pips = (current - entry) / ppp if ppp else 0
        else:
            pnl_pips = (entry - current) / ppp if ppp else 0

        logger.info(
            "[BRIEF_INVALIDATED] %s (%s) 5M close %.1f %s %.1f — closing (pnl=%.1fp)",
            pk, mode, candle_close, inv_dir, inv_price, pnl_pips,
        )

        try:
            _exec.close_position(pos_key=pk, reason="BRIEF_INVALIDATED", exit_hint_price=candle_close)
        except Exception as e:
            logger.error("[BRIEF_INVALIDATED] close failed for %s: %s", pk, e)
            continue

        try:
            import telegram_alerts
            telegram_alerts.send_status_update(
                f"\U0001f6ab {pair} {mode} INVALIDATED: 5M close {candle_close:.1f} "
                f"{inv_dir} {inv_price:.1f} ({pnl_pips:+.1f}p)"
            )
        except Exception:
            pass


# ============================================================
# UNIVERSAL RUNNER MOMENTUM CHECK (all strategies, post scale-out, 5M close)
# ============================================================
# 2026-07-27. Same M1 = sign(MACD-hist) alignment rule that TREND_V3
# already uses on its runners (gbpusd_trend_v3.monitor_exits, +612p sim
# vs -98p actual across 34 fills) — extracted to runner_momentum.py so
# every scaled-out runner across every strategy can consume it.
#
# Modes:
#   off      — evaluate nothing.
#   shadow   — evaluate + log, close nothing (DEFAULT).
#   enforce  — WOULD_EXIT closes the runner via _exec.close_position.
#
# Gated per-trade on meta["scaled_out"] is True — this is the universal
# post-scale-out runner path (TREND_RUNNER_STYLE, BB_BOUNCE, EMA_PULLBACK,
# STRUCTURE_BREAK, NEWS_STRATEGY_CONT, STRONG/FORMING profiles). Trades
# that never scaled don't have a runner leg and aren't evaluated.
#
# TREND_V3 modes are SKIPPED here — the enforced exhaustion-gated check
# in gbpusd_trend_v3.monitor_exits already owns that path (proven, live)
# and this universal wrapper must not double-evaluate or double-close
# them regardless of RUNNER_MOMENTUM_CHECK_MODE.
#
# Evaluation failures never touch the trade — the outer try/except wraps
# the whole per-trade block and downgrades to HOLD on any exception.
_UNIVERSAL_RUNNER_MOMENTUM_TREND_V3_MODES = (
    "GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S",
)


def check_universal_runner_momentum(payload: dict) -> None:
    """5M candle close callback: universal exhaustion-gated momentum check
    for scaled-out runners across ALL strategies.

    Payload contract mirrors the other 5M close callbacks (candle_builder):
      payload["symbol"]  -> pair symbol (e.g. "GBPUSD")
      payload["df_5m"]   -> enriched 5M DataFrame with MACD_HIST_35_45_30

    Reads RUNNER_MOMENTUM_CHECK_MODE at call time so a flip takes effect
    on the next 5M close without restart.
    """
    try:
        _mode_raw = (os.getenv("RUNNER_MOMENTUM_CHECK_MODE", "shadow") or "shadow").strip().lower()
        if _mode_raw not in ("off", "shadow", "enforce"):
            _mode_raw = "shadow"  # unknown value -> safe default
        if _mode_raw == "off":
            return

        df_5m = payload.get("df_5m")
        symbol = str(payload.get("symbol") or "").upper()
        if df_5m is None or not symbol:
            return

        # Read MACD histogram ONCE per callback firing — same value applied
        # to every runner on this pair. Failure -> silent no-op (HOLD-safe).
        try:
            from runner_momentum import (
                evaluate_runner_verdict as _eval,
                macd_hist_last_and_contracting as _mh,
            )
        except Exception as _imp_exc:
            logger.debug("[RUNNER-MOMENTUM] import failed: %s", _imp_exc)
            return

        macd_last, _macd_contracting = _mh(df_5m)

        for pk, st in list(_exec.EPIC_STATE.items()):
            try:
                if not st.get("active"):
                    continue

                epic = str(st.get("epic") or pk.split("|")[0])
                pair = _pair_from_epic(epic)
                if pair != symbol:
                    continue

                mode = str(st.get("mode") or "").upper()

                # TREND_V3 owns its own enforced check — do not double-eval
                # or double-close under any RUNNER_MOMENTUM_CHECK_MODE.
                if mode in _UNIVERSAL_RUNNER_MOMENTUM_TREND_V3_MODES:
                    continue

                # Only scaled-out runners qualify — pre-scale positions
                # are still riding the initial SL/TP; the universal +10p
                # scale-out has not fired yet, so there is no "runner leg"
                # to gate.
                meta = _PROFIT_MGMT_BY_EPIC.get(epic) or {}
                if not meta.get("scaled_out"):
                    continue

                direction = str(st.get("direction") or "").upper()
                if direction not in ("BUY", "SELL"):
                    continue

                verdict = _eval(direction, macd_last)
                deal_id = st.get("dealId") or st.get("deal_id") or pk

                if verdict["verdict"] == "HOLD":
                    logger.info(
                        "[RUNNER-MOMENTUM] deal=%s strategy=%s verdict=HOLD "
                        "mode=%s reason=%s",
                        deal_id, mode, _mode_raw, verdict["reason"],
                    )
                    continue

                # WOULD_EXIT
                if _mode_raw == "shadow":
                    logger.info(
                        "[RUNNER-MOMENTUM] deal=%s strategy=%s verdict=WOULD_EXIT "
                        "mode=shadow reason=%s (no close — shadow only)",
                        deal_id, mode, verdict["reason"],
                    )
                    continue

                # enforce
                logger.info(
                    "[RUNNER-MOMENTUM] deal=%s strategy=%s verdict=WOULD_EXIT "
                    "mode=enforce reason=%s — closing runner",
                    deal_id, mode, verdict["reason"],
                )
                try:
                    _exec.close_position(
                        pos_key=pk,
                        reason="RUNNER_MOMENTUM_EXIT",
                    )
                except Exception as _cl_exc:
                    logger.warning(
                        "[RUNNER-MOMENTUM] close failed pk=%s: %s",
                        pk, _cl_exc,
                    )
            except Exception as _one_exc:
                # Per-trade guard: an evaluation failure NEVER touches the
                # trade. Log at debug and continue with the next slot.
                logger.debug(
                    "[RUNNER-MOMENTUM] per-trade eval failed pk=%s: %s",
                    pk, _one_exc,
                )
                continue
    except Exception as _outer_exc:
        # Outer guard: never propagate into the 5M close callback chain.
        logger.debug("[RUNNER-MOMENTUM] outer guard: %s", _outer_exc)


# ============================================================
# Per-position meta hygiene (2026-08-15)
# ============================================================
# Fix for the leak identified 2026-08-14 17:30 GBPUSD_BB_BOUNCE_L: the AUTO-CUT
# eval at 17:30:02 read best=7.50 best_close=6.45 — the peaks of the 15:30
# position that had closed at 17:18:56 — because _reset_trade_state() in
# trade_executor blanks EPIC_STATE[pos_key] but does NOT purge
# _PROFIT_MGMT_BY_EPIC[pos_key]. The next-tick clear at
# _monitor_single_position:4139 relies on the pk still being in
# get_all_positions_for_epic, which it is not after reset, so the meta is
# retained indefinitely until a new position opens on the same pos_key and
# inherits it. Register a close callback so meta is purged inline on close,
# before any subsequent open can read it.
def _purge_per_position_meta(pos_key: str) -> None:
    """Purge every per-position meta store keyed on pos_key.

    Runs from trade_executor's close-callback chain (see
    register_trade_close_callback at trade_executor.py:610). Belt in the
    two-layer defence:
      - Belt (this function): inline purge on close, guaranteed to fire
        before any subsequent execute_trade can re-populate the pos_key.
      - Braces (_monitor_profit_protection:~5393): compares meta["_deal_id"]
        against st["dealId"] and re-inits on mismatch, in case some close
        path bypasses the callback chain.

    Purges every store known to key on pos_key (or epic — pos_key IS the
    same string, "{epic}|{mode}", used by all these dicts). Fail-open per
    store so one popped key does not block the others.
    """
    pk = str(pos_key)
    for _store in (_PROFIT_MGMT_BY_EPIC, _BRIEFING_TP_BY_EPIC,
                   _CONSOLIDATION_BY_EPIC, _SWEEP_MGMT_BY_EPIC,
                   _BB_RANGE_SCALP_BY_EPIC):
        try:
            _store.pop(pk, None)
        except Exception:
            pass


try:
    _exec.register_trade_close_callback(
        lambda pos_key, exit_price, pnl_pips, close_reason, **_kw: (
            _purge_per_position_meta(pos_key)
        )
    )
except Exception as _reg_exc:
    logger.warning("[META_HYGIENE] close-callback register failed: %s", _reg_exc)


# ============================================================
# Module-level instance for legacy imports
# ============================================================
trade_manager = TradeManager()


# ============================================================
# Phase 13 Seam B (2026-09-23) — V1 action instrumentation
# ============================================================
#
# Fail-silent wrappers around the three canonical V1 TM decision
# terminals: _amend_broker_sl, _scale_out_50pct, and the close-callback
# fan-out. Guarded by TM_CORPUS_WRITER_PRODUCTION (default OFF); when
# OFF the wrappers become byte-identical no-ops around the originals.
# Authority=NONE: wrappers NEVER alter arguments, return value, side
# effects, or raise. Any exception in the instrumentation is
# DEBUG-stamped and swallowed.
#
# Design: at module-load time we replace three globals with
# functools.wraps-preserving wrappers. Existing callers see the same
# name, same signature, same return value. The wrappers observe
# pre-state + post-state and emit a TM_ACTION row via
# tm_corpus_writer.record_action.
def _phase13_seam_b_install() -> None:
    try:
        import functools as _ft
        try:
            import tm_corpus_writer as _cw
        except Exception as _cw_ie:  # pragma: no cover
            logger.debug("[TM_CORPUS_SEAM_B] tm_corpus_writer not importable: %s",
                          _cw_ie)
            return

        # --- Wrap _amend_broker_sl ------------------------------------
        try:
            _orig_amend = _amend_broker_sl

            @_ft.wraps(_orig_amend)
            def _amend_broker_sl_seam_b(pos_key, new_sl_price, current_tp_price):
                # Capture pre-state defensively; failures never block the call.
                _pre_sl = None
                _direction = None
                _epic = None
                _deal_id = None
                _pair_val = None
                try:
                    _st = _PROFIT_MGMT_BY_EPIC.get(pos_key) or {}
                    _pre_sl = _st.get("sl")
                    # Also fall back to trade_executor.EPIC_STATE
                    try:
                        import trade_executor as _te_pre
                        _es = _te_pre.EPIC_STATE.get(pos_key) or {}
                        if _pre_sl is None:
                            _pre_sl = _es.get("sl")
                        _direction = str(_es.get("direction") or "").upper() or None
                        _epic = _es.get("epic")
                        _deal_id = _es.get("deal_id") or _es.get("dealId")
                        _pair_val = _es.get("pair")
                    except Exception:
                        pass
                except Exception:
                    pass
                _ok = _orig_amend(pos_key, new_sl_price, current_tp_price)
                # Emit action row — fail-silent + guard-checked.
                try:
                    if _cw.is_enabled():
                        _cw.record_action({
                            "deal_id": _deal_id,
                            "pos_key": pos_key,
                            "epic": _epic,
                            "pair": _pair_val,
                            "direction": _direction,
                            "strategy": None,
                            "strategy_family": None,
                            "tm_v1_action_atom": "AMEND_SL",
                            "executed": bool(_ok),
                            "pre_sl": _pre_sl,
                            "post_sl": float(new_sl_price)
                                if _ok and new_sl_price is not None else None,
                            "reason": "amend_broker_sl",
                        })
                except Exception as _ex:
                    logger.debug("[TM_CORPUS_SEAM_B] amend action emit failed: %s", _ex)
                return _ok

            globals()["_amend_broker_sl"] = _amend_broker_sl_seam_b
        except Exception as _wr_ex:
            logger.debug("[TM_CORPUS_SEAM_B] amend wrapper install failed: %s", _wr_ex)

        # --- Wrap _scale_out_50pct ------------------------------------
        try:
            _orig_scale = _scale_out_50pct

            @_ft.wraps(_orig_scale)
            def _scale_out_50pct_seam_b(pos_key, pair, ppp, meta):
                _pre_size = None
                _pre_scaled = False
                _direction = None
                _epic = None
                _deal_id = None
                try:
                    import trade_executor as _te_pre
                    _es = _te_pre.EPIC_STATE.get(pos_key) or {}
                    _pre_size = _es.get("size")
                    _pre_scaled = bool(_es.get("scaled_out"))
                    _direction = str(_es.get("direction") or "").upper() or None
                    _epic = _es.get("epic")
                    _deal_id = _es.get("deal_id") or _es.get("dealId")
                except Exception:
                    pass
                _orig_scale(pos_key, pair, ppp, meta)
                _post_size = None
                _post_scaled = _pre_scaled
                try:
                    import trade_executor as _te_post
                    _es2 = _te_post.EPIC_STATE.get(pos_key) or {}
                    _post_size = _es2.get("size")
                    _post_scaled = bool(_es2.get("scaled_out"))
                except Exception:
                    pass
                # Success iff scaled_out flipped False → True
                _ok = bool(_post_scaled) and not _pre_scaled
                try:
                    if _cw.is_enabled():
                        _cw.record_action({
                            "deal_id": _deal_id,
                            "pos_key": pos_key,
                            "epic": _epic,
                            "pair": pair,
                            "direction": _direction,
                            "strategy": None,
                            "strategy_family": None,
                            "tm_v1_action_atom": "SCALE_OUT_50",
                            "executed": _ok,
                            "pre_size": _pre_size,
                            "post_size": _post_size,
                            "reason": "scale_out_50pct",
                        })
                except Exception as _ex:
                    logger.debug("[TM_CORPUS_SEAM_B] scale action emit failed: %s", _ex)

            globals()["_scale_out_50pct"] = _scale_out_50pct_seam_b
        except Exception as _wr_ex:
            logger.debug("[TM_CORPUS_SEAM_B] scale wrapper install failed: %s", _wr_ex)

        # --- Register a separate CLOSE observer via the existing
        # trade_executor close-callback fan-out (does NOT wrap any
        # trade_manager function; adds a new subscriber alongside the
        # META_HYGIENE / occupancy-repair callbacks).
        try:
            def _seam_b_on_trade_close(pos_key, exit_price, pnl_pips,
                                        close_reason, **_kw):
                try:
                    if not _cw.is_enabled():
                        return
                    _direction = None
                    _epic = None
                    _deal_id = _kw.get("deal_id")
                    _pair_val = None
                    _strategy = None
                    try:
                        import trade_executor as _te_close
                        _es = _te_close.EPIC_STATE.get(pos_key) or {}
                        _direction = str(_es.get("direction") or "").upper() or None
                        _epic = _es.get("epic")
                        if not _deal_id:
                            _deal_id = _es.get("deal_id") or _es.get("dealId")
                        _pair_val = _es.get("pair")
                        _strategy = _es.get("mode")
                    except Exception:
                        pass
                    _cw.record_action({
                        "deal_id": _deal_id,
                        "pos_key": pos_key,
                        "epic": _epic,
                        "pair": _pair_val,
                        "direction": _direction,
                        "strategy": _strategy,
                        "strategy_family": None,
                        "tm_v1_action_atom": "CLOSE",
                        "executed": True,
                        "exit_price": exit_price,
                        "pnl_pips": pnl_pips,
                        "reason": str(close_reason or ""),
                    })
                except Exception as _ex:
                    logger.debug("[TM_CORPUS_SEAM_B] close action emit failed: %s", _ex)

            _exec.register_trade_close_callback(_seam_b_on_trade_close)
        except Exception as _cb_ex:
            logger.debug("[TM_CORPUS_SEAM_B] close-callback register failed: %s", _cb_ex)
    except Exception as _outer:
        logger.debug("[TM_CORPUS_SEAM_B] install failed: %s", _outer)


_phase13_seam_b_install()
