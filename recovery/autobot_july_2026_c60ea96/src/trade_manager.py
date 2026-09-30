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

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
_STRUCTURE_EXIT_EXEMPT_MODES = frozenset({
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
})


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


def _sl_amend_should_defer_min_distance(
    pos_key: str, new_sl_price: float, pair: str,
) -> tuple[bool, float, float]:
    """Pre-flight IG-min-distance guard. Return (defer, dist_pips, threshold_pips).

    Prevents amend attempts guaranteed to be rejected with
    ATTACHED_ORDER_LEVEL_ERROR when the proposed SL is inside IG's
    per-pair min-stop-distance from the live price. Root cause of the
    2026-07-20 08:00-08:21 storm: trail proposed SL ~1.55p from live
    price, every API attempt bounced, retried ~1000× before the c0d34cc
    circuit-breaker contained it.

    Distance and threshold are both in FX PIPS. In this codebase's price
    scale, 1 unit == 0.0001 fx == 1 pip (e.g., codebase 13476.8 == fx
    1.34768), so |sl - live_mid| is already the pip distance — no ppp
    division. The per-pair minimum comes from _ig_min_stop_pips_for_pair
    which sources IG's actual dealingRules.minNormalStopOrLimitDistance
    (verified against API on 2026-07-21).

    A DEFER is NOT a failure — the caller returns False without
    incrementing consecutive_amend_failures (breaker untouched) and the
    caller's ratchet state (prior lock in caller meta) is preserved, so
    the SAME lock is re-proposed on the next monitor tick against a
    tick-fresh live price.

    Fail-open on missing/invalid live_mid so healthy paths remain
    byte-identical when tick data is momentarily unavailable.
    """
    try:
        st = _state_for_epic(pos_key)
        live_mid = _safe_float(st.get("last_mid"), None)
        if live_mid is None or live_mid <= 0:
            return False, 0.0, 0.0
        _min_pips = _ig_min_stop_pips_for_pair(pair)
        _margin_pips = float(
            os.getenv("SL_AMEND_MIN_DIST_MARGIN_PIPS", "")
            or SL_AMEND_MIN_DIST_MARGIN_PIPS
        )
        _threshold_pips = _min_pips + _margin_pips
        _dist_pips = abs(float(new_sl_price) - float(live_mid))
        if _dist_pips < _threshold_pips:
            return True, _dist_pips, _threshold_pips
        return False, _dist_pips, _threshold_pips
    except Exception:
        return False, 0.0, 0.0


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
        _defer, _dist_pips, _threshold_pips = _sl_amend_should_defer_min_distance(
            pos_key, float(new_stop), _pair,
        )
        if _defer:
            _meta_defer = _PROFIT_MGMT_BY_EPIC.get(pos_key)
            if _meta_defer is None:
                _meta_defer = {}
                _PROFIT_MGMT_BY_EPIC[pos_key] = _meta_defer
            # Mark suppressed so callers skip their per-caller
            # "amend NOT confirmed" warning — a deferral is expected.
            _meta_defer["_sl_amend_last_suppressed"] = True
            logger.debug(
                "[SL_AMEND_DEFER] deal=%s proposed=%.5f dist=%.2fp min=%.2fp",
                deal_id, float(new_stop), _dist_pips, _threshold_pips,
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
            _sl_amend_on_failure(pos_key, new_stop, direction)
            return False
        logger.info(
            "[SCALE_OUT] broker SL amended: %s deal=%s stop=%.1f limit=%.1f",
            pos_key, deal_id, new_stop, limit_level,
        )
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

    # Read activate/offset at call-time so a tune takes effect on the
    # next tick without restart. Fall back to module-init defaults.
    try:
        _activate = float(
            os.getenv("EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS", "")
            or EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS
        )
    except (TypeError, ValueError):
        _activate = float(EMA_PULLBACK_RUNNER_TRAIL_ACTIVATE_PIPS)
    try:
        _offset = float(
            os.getenv("EMA_PULLBACK_RUNNER_TRAIL_OFFSET_PIPS", "")
            or EMA_PULLBACK_RUNNER_TRAIL_OFFSET_PIPS
        )
    except (TypeError, ValueError):
        _offset = float(EMA_PULLBACK_RUNNER_TRAIL_OFFSET_PIPS)

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
    if mode not in _BB_BOUNCE_TRAIL_MODES:
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

    # Env-tunable knobs read at call-time so Johnny can retune without
    # restart. Fall back to the module-level defaults on parse errors.
    try:
        _activate = float(
            os.getenv("NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS", "")
            or NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS
        )
    except (TypeError, ValueError):
        _activate = float(NEWS_STRATEGY_CONT_RUNNER_TRAIL_ACTIVATE_PIPS)
    try:
        _offset = float(
            os.getenv("NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS", "")
            or NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS
        )
    except (TypeError, ValueError):
        _offset = float(NEWS_STRATEGY_CONT_RUNNER_TRAIL_OFFSET_PIPS)

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
            resp = _close_position_by_deal(deal_id, close_dir, scale_size)
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
        st["be_amend_ok"] = bool(_be_ok)
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
            try:
                _reject_reason = str(meta.get("last_amend_reject_reason") or "unknown")
                _release_note = (
                    " (TP release attempted, ALSO failed — runner "
                    "sits behind ORIGINAL SL and ORIGINAL TP)"
                    if _tp_released else ""
                )
                from telegram_alerts import send_error_alert
                send_error_alert(
                    f"RUNNER RIDING ORIGINAL SL — BE AMEND FAILED{_release_note}\n"
                    f"Pair: {pair}\n"
                    f"Deal: {deal_id}\n"
                    f"Reason: {_reject_reason}"
                )
            except Exception as _tg_exc:
                logger.debug(
                    "[SCALE_OUT] BE-fail telegram alert failed: %s", _tg_exc,
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
      2. Original ±SL distance match → "SL hit"
      3. Original ±TP distance match → "TP hit"
      4. Pre-scale-out BE band (0..be_offset+tol) → "Breakeven stop hit (IG server-side)"
      5. Catch-all → "External/manual close detected (IG open positions)"

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
            return "External/manual close detected (IG open positions)"

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
    return "External/manual close detected (IG open positions)"


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

        return out

    def run_external_close_sweep(self) -> None:
        """Public entry point for the rest_sweeps daemon to drive the
        external-close sweep on its own cadence. Body delegates to the
        existing internal method; safe to call concurrently with
        monitor_positions (the cadence flag is the only shared state)."""
        try:
            self._check_ig_open_positions_for_external_close()
        except Exception as e:
            logger.error(
                f"[TRADE_MANAGER] external-close sweep error: {type(e).__name__}: {e}"
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
                    if _scaled_ok:
                        pass  # broker BE + trail are authoritative on this runner
                    else:
                        import structure_exit as _se
                        _entry_px = float(st.get("entry_price") or st.get("entry") or 0.0)
                        _se_mode = str(st.get("mode") or "").strip().upper()
                        # BB_BOUNCE per-mode exempt (2026-06-25, Johnny's
                        # directive). Counter-trend fade — let it run to
                        # its own SL/TP; structure-flips are noise here.
                        if (
                            STRUCTURE_EXIT_EXEMPT_BB_BOUNCE
                            and _se_mode in _STRUCTURE_EXIT_EXEMPT_MODES
                        ):
                            logger.info(
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
        _scaled_out_exempt_enabled = (
            (os.getenv("REGIME_MAX_HOLD_SCALED_OUT_EXEMPT_ENABLED", "1") or "1")
            .strip().lower() in ("1", "true", "yes")
        )
        if (
            _scaled_out_exempt_enabled
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
            # 2026-07-27: env kill-switch on the max-hold force close.
            # Default "1" preserves current behaviour byte-identically.
            # When "0", skip the close and emit ONE INFO per trade per
            # breach so the disabled clock stays observable in logs. The
            # flip sequence (operator-controlled): shadow -> evidence in
            # [RUNNER-MOMENTUM] lines -> enforce -> then flip this to 0.
            _regime_max_hold_enabled = (
                (os.getenv("REGIME_MAX_HOLD_ENABLED", "1") or "1")
                .strip().lower() in ("1", "true", "yes", "on")
            )
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
            }
            _PROFIT_MGMT_BY_EPIC[epic] = meta
        else:
            best_prev = _safe_float(meta.get("best_pnl_pips"), pnl_pips)
            if best_prev is None:
                best_prev = pnl_pips
            meta["best_pnl_pips"] = max(float(best_prev), float(pnl_pips))
            meta["last_pnl_pips"] = pnl_pips

        best_pnl = _safe_float(meta.get("best_pnl_pips"), pnl_pips)
        if best_pnl is None:
            best_pnl = pnl_pips

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
        _profile_id_scale = str(st.get("profile_id") or "").upper()
        _universal_scale_gated = (
            _REGIME_MGMT_ENABLED_TM and _profile_id_scale in _PROFILE_MANAGED
        )
        if (SCALE_OUT_AT_10P_ENABLED and not _universal_scale_gated
                and not meta.get("scaled_out")
                and float(best_pnl) >= SCALE_OUT_TRIGGER_PIPS):
            try:
                _scale_out_50pct(epic, pair, ppp, meta)
            except Exception as _so_exc:
                logger.warning(
                    "[SCALE_OUT] %s _scale_out_50pct raised: %s",
                    epic, _so_exc,
                )

        # ── BE-recover one-shot (2026-06-05) ───────────────────────────
        # If a scaled runner was restored from persistence WITHOUT
        # be_amend_ok (e.g., legacy save predates this field, or the
        # original scale-out's amend silently failed), re-issue the BE
        # amend once. Stamp `meta["be_recover_attempted"]` so we don't
        # spin every tick. Successful recover stamps both st + meta
        # be_amend_ok=True, which unlocks the bb_bounce trail and shuts
        # off structure_exit on this runner (its broker BE is now real).
        if meta.get("scaled_out") and not meta.get("be_amend_ok") \
                and not meta.get("be_recover_attempted"):
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
                    meta["be_recover_attempted"] = True
                    if _ok:
                        logger.info(
                            "[BE_RECOVER] %s re-issued BE amend → be_amend_ok=True "
                            "(entry=%.5f, runner_tp=%.5f)",
                            epic, _entry, _runner_tp_price,
                        )
                    else:
                        logger.warning(
                            "[BE_RECOVER] %s BE re-amend FAILED — "
                            "structure_exit remains active as -10p safety net; "
                            "bb_bounce trail will not engage.",
                            epic,
                        )
            except Exception as _be_rec_exc:
                logger.warning(
                    "[BE_RECOVER] %s exception (will not retry): %s",
                    epic, _be_rec_exc,
                )
                meta["be_recover_attempted"] = True

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
            _existing_reason = str(state_obj.get("close_reason") or "").strip()
            if _existing_reason:
                logger.info(
                    "[TRADE_MANAGER] external-close sweep deferring label "
                    "for pos_key=%s — bot-driven exit already stamped "
                    "close_reason=%r (sweep would have set %r)",
                    state_pk, _existing_reason, close_reason,
                )
            else:
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
                # lost — alert, then clear state.
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
# Module-level instance for legacy imports
# ============================================================
trade_manager = TradeManager()
