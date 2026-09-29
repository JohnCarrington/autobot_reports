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
        if _broker_sl_amend_fn is not None:
            _broker_sl_amend_fn(deal_id, new_stop, limit_level)
        else:
            from ig_auth import get_ig_session
            ig, _h, _a = get_ig_session()
            ig.update_open_position(
                limit_level=limit_level,
                stop_level=new_stop,
                deal_id=deal_id,
            )
        logger.info(
            "[SCALE_OUT] broker SL amended: %s deal=%s stop=%.1f limit=%.1f",
            pos_key, deal_id, new_stop, limit_level,
        )
        return True
    except Exception as exc:
        logger.warning(
            "[SCALE_OUT] broker SL amend failed for %s: %s", pos_key, exc,
        )
        return False


# ── Scale-out master flag (2026-05-23) ──────────────────────────────────
SCALE_OUT_AT_10P_ENABLED = (os.getenv("SCALE_OUT_AT_10P_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes")
SCALE_OUT_TRIGGER_PIPS = float(os.getenv("SCALE_OUT_TRIGGER_PIPS", "10") or 10.0)
SCALE_OUT_FRACTION = float(os.getenv("SCALE_OUT_FRACTION", "0.5") or 0.5)


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

        # Pull the actual fill price for accurate partial_bank_pips
        # (fallback to current mid if IG didn't return a level).
        partial_exit_price = None
        try:
            if isinstance(resp, dict):
                partial_exit_price = _safe_float(resp.get("level"))
        except Exception:
            partial_exit_price = None
        if partial_exit_price is None:
            partial_exit_price = _safe_float(st.get("last_mid"))

        # Compute realised partial bank in pips.
        partial_bank_pips = 0.0
        if partial_exit_price is not None:
            if direction == "BUY":
                partial_bank_pips = (float(partial_exit_price) - float(entry)) / float(ppp)
            else:
                partial_bank_pips = (float(entry) - float(partial_exit_price)) / float(ppp)
        partial_bank_pips = round(float(partial_bank_pips), 2)
        partial_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 2) move runner's broker SL to BE, preserve original TP.
        tp_pips = _safe_float(st.get("tp"), 0.0) or 0.0
        if direction == "BUY":
            runner_tp_price = float(entry) + float(tp_pips) * float(ppp)
        else:
            runner_tp_price = float(entry) - float(tp_pips) * float(ppp)
        _amend_broker_sl(pos_key, new_sl_price=float(entry),
                         current_tp_price=runner_tp_price)

        # 3) update EPIC_STATE so reconciliation + future management
        #    knows we're now a 1-unit runner.
        new_size = float(cur_size) - float(scale_size)
        st["size"] = new_size
        st["partial_bank_pips"] = partial_bank_pips
        st["partial_bank_ts"] = partial_ts
        st["scaled_out"] = True
        # Software SL bookkeeping in pips (broker SL is now at entry).
        st["sl"] = 0.0

        # 4) latch the dispatcher.
        meta["scaled_out"] = True

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
            }
            logger.info(
                f"[TradeManager] Restored profit state for {epic}: "
                f"best_pnl={meta.get('best_pnl_pips'):.2f} "
                f"scaled_out={bool(meta.get('scaled_out'))} "
                f"trail_armed={bool(meta.get('trail_armed'))}"
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


def _detect_ig_close_reason(state_obj: dict, exit_hint: Any) -> str:
    """
    Infer whether a position that vanished from IG was a TP hit, SL hit,
    or a genuine external/manual close by comparing the implied PnL pips
    against the stored tp/sl distances.
    """
    try:
        entry = float(state_obj.get("entry_price") or 0)
        direction = str(state_obj.get("direction") or "").upper()
        pip_size = float(state_obj.get("pip_size") or 1.0)
        sl_pips = float(state_obj.get("sl") or 0)
        tp_pips = float(state_obj.get("tp") or 0)
        exit_p = float(exit_hint) if exit_hint is not None else None

        if entry <= 0 or pip_size <= 0 or exit_p is None or direction not in ("BUY", "SELL"):
            return "External/manual close detected (IG open positions)"

        pnl_pips = _calculate_pnl_pips(direction, entry, exit_p, pip_size)
        tolerance = 3.0  # pips

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
        else:
            _dir = str(st.get("direction") or "").upper()
            if _dir in ("BUY", "SELL"):
                _update_consolidation_state(pk, _dir, float(mid))

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

                if st.get("active") and pk in _BRIEFING_TP_BY_EPIC:
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
                logger.info("[BRIEFING_TP] %s SL hit @ %.1f (phase=%s, pnl=%.1fp)",
                            epic, current, phase, pnl_pips)
                _close_trade_best_effort(epic, f"BRIEFING_TP_SL_{phase}", current)
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
        if _max_hold_min is not None and age_s >= float(_max_hold_min) * 60:
            # BE skip: when BRIEFING_EXEC_REGIME_MAX_HOLD_ENABLED=0 (default),
            # BE positions are exempt from REGIME_MAX_HOLD and ride to SL/TP/EOD.
            if _is_be_pm and not _BE_REGIME_MAX_HOLD_ENABLED:
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
        if SCALE_OUT_AT_10P_ENABLED and not meta.get("scaled_out") \
                and float(best_pnl) >= SCALE_OUT_TRIGGER_PIPS:
            try:
                _scale_out_50pct(epic, pair, ppp, meta)
            except Exception as _so_exc:
                logger.warning(
                    "[SCALE_OUT] %s _scale_out_50pct raised: %s",
                    epic, _so_exc,
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

            close_reason = _detect_ig_close_reason(state_obj, exit_hint)

            # Prime exit_price + close_reason on the state object so the
            # downstream close_trade() path reports the IG-detected values
            # (PnL, alert, signal_log outcome) rather than defaulting.
            state_obj["exit_price"] = exit_hint
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
# Module-level instance for legacy imports
# ============================================================
trade_manager = TradeManager()
