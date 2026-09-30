# =========================
# FILE: trade_executor.py
# =========================
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
trade_executor.py

MULTI-POSITION PER EPIC + CONFIRMATION-BASED OPENS
WITH PENDING TRADE LOCK

Each strategy manages its own position independently, keyed by
pos_key = "{epic}|{mode}".  Multiple strategies (e.g. BRIEFING_SWEEP
and WINDOW_SWEEP) can hold simultaneous positions on the same epic.

Updated:
- Final SL/TP sanitization guard before calling open_sb_now.
- Rejects tiny / invalid / contaminated TP/SL values.
- Keeps pip-distance contract intact (#99 / #106).
- Does not touch open_sb_now.py (#96).
- Synchronizes legacy TRADE_STATE with per-epic state.
- Guards get_ig_session() and clears pending_open on failure.
- Validates decision.entry as numeric and finite.
- Logs richer rejection / confirmation diagnostics.
- Verifies close success against IG open positions before resetting local state.
- Sanitizes confirmed IG entry level and falls back to requested entry.
- Ensures close alerts always have a non-blank reason.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# ============================================================
# ENVIRONMENT
# ============================================================
load_dotenv()

from open_sb_now import open_sb_now
from close_sb_now import close_sb_now, close_by_deal_id, get_open_positions
from ig_auth import get_ig_session
from telegram_alerts import (
    send_trade_open_alert,
    send_trade_close_alert,
)
import execution_latency_metrics as _elm

logger = logging.getLogger("AutoBot")

# ============================================================
# Pre-broker block telemetry slot (single-consumer; cleared each call)
# ============================================================
# Telemetry-only slot used by direct-dispatch wrappers (e.g. autobot's
# BB_BOUNCE wrapper at autobot.py:3788) to recover the pre-broker block
# stage + reason after execute_trade returns None. The wrapper calls
# consume_last_block_info() immediately after the failed call to
# back-annotate forensic_fires.jsonl. Cleared at execute_trade entry
# so cross-call leakage is impossible. NOT consumed by trading logic.
_LAST_BLOCK_INFO: Optional[Dict[str, Any]] = None


def _set_block_info(stage: str, reason: str) -> None:
    """Record the pre-broker block stage + reason. Never raises."""
    global _LAST_BLOCK_INFO
    try:
        _LAST_BLOCK_INFO = {
            "stage": str(stage),
            "reason": str(reason),
            "ts_ms": _elm.now_epoch_ms(),
        }
    except Exception:
        pass


def _clear_block_info() -> None:
    """Clear the slot at execute_trade entry."""
    global _LAST_BLOCK_INFO
    _LAST_BLOCK_INFO = None


def consume_last_block_info() -> Optional[Dict[str, Any]]:
    """Pop the pre-broker block stage/reason recorded during the most
    recent execute_trade call. Returns None if no block was recorded
    (either the trade fired, or execute_trade hasn't been called).

    Single-consumer contract: after read, the slot is cleared so a
    second call returns None — prevents a stale block from a previous
    candidate being mis-attributed to a later one.
    """
    global _LAST_BLOCK_INFO
    info = _LAST_BLOCK_INFO
    _LAST_BLOCK_INFO = None
    return info


# ============================================================
# CONFIG
# ============================================================

TRADE_SIZE = float(os.getenv("TRADE_SIZE", "1"))
DEFAULT_SL_PIPS = float(os.getenv("DEFAULT_SL_PIPS", "12"))
DEFAULT_TP_PIPS = float(os.getenv("DEFAULT_TP_PIPS", "30"))

# Regime matrix (Phase 2). Used to gate legacy regime-adjacent gates
# (HTF authority, conviction, cross-bias, GUARDS observable) off when
# the matrix owns enablement. No-op when flag=0.
_REGIME_MATRIX_ENABLED_TE = (
    os.getenv("REGIME_MATRIX_ENABLED", "0") or "0"
).strip().lower() in ("1", "true", "yes", "on")
# DIRECTION_ROUTER_SHADOW block (2026-06-23) removed 2026-07-08 under the
# regime matrix build. Was shadow-only at both flag values; enforcement
# path never wired. Deleted flags: DIRECTION_ROUTER_SHADOW_ENABLED,
# DIRECTION_ROUTER_ENFORCE_ENABLED, DIRECTION_ROUTER_SHADOW_LOG_PATH.
# Recon phase2_recon_2026-07-08.md Q1.5.


# MIN_RR_THRESHOLD removed 2026-04-30 — dispatcher R:R gate stripped
# per dispatcher-decoupling. R:R is a strategy-owned concern; each
# strategy specifies its own SL/TP. The portfolio-wide floor was a
# thesis-level intervention that doesn't belong at this layer.

def _pair_from_epic(epic_str: str) -> str:
    """CS.D.GBPUSD.TODAY.IP -> GBPUSD"""
    parts = str(epic_str or "").split(".")
    return parts[2].upper() if len(parts) >= 3 else str(epic_str).upper()


def _regime_snapshot_for_alert(pair: str) -> Optional[Dict[str, Any]]:
    """Display-only regime snapshot for Telegram TRADE OPENED alert.

    Reads the SAME module-level cache signal_logger.log_open uses
    (regime_engine.latest_result — a dict cache populated on 5M closes).
    NOT a fresh engine call; no computation, no disk read. Returns None
    on any failure so the alert path can never fail because of this.
    Fields consumed by the alert: winning_regime, label_path,
    confidence_final. GATES NOTHING — display only.
    """
    try:
        import regime_engine as _regime_engine
        _r = _regime_engine.latest_result(pair)
        if isinstance(_r, dict):
            return _r
    except Exception:
        pass
    return None


# ── FXi LOCATION-SCORE gate helpers (2026-07-15) ────────────────────
# Score-and-stamp verdict computed at the executor choke point. Stamps
# every assessed fire (journal, always). Vetoes only when the total
# score is at or below FXI_VETO_FLOOR (-90). Master flag
# FXI_LEVEL_VETO_ENABLED gates the whole assessment. NEWS_* modes are
# exempt (filtered at the seam). Fail-open: no plan / reader None / any
# exception → score None → no stamp, no veto, one WARN max per process.

_FXI_LOC_WARN_EMITTED = False


def _fxi_loc_warn_once(msg: str, exc: Optional[BaseException] = None) -> None:
    """Emit at most one WARNING per process for FXi-location fail-open
    events. Subsequent occurrences fall through to DEBUG so the log
    isn't spammed on repeated Neon / regime-cache errors."""
    global _FXI_LOC_WARN_EMITTED
    tail = f": {exc!r}" if exc is not None else ""
    if not _FXI_LOC_WARN_EMITTED:
        logger.warning("%s%s", msg, tail)
        _FXI_LOC_WARN_EMITTED = True
    else:
        logger.debug("%s%s", msg, tail)


def _fxi_location_family(mode: str) -> Optional[str]:
    """Return 'TREND' or 'FADE' from a pair-prefixed strategy mode; None
    for anything else. NEWS_* is handled by the caller (exempt from
    assessment). Substring match: names at the seam are pair-prefixed
    (e.g. GBPUSD_TREND_V3, GBPUSD_BB_BOUNCE_L, GBPUSD_BB_REV_PAT_S)."""
    m = (mode or "").upper()
    if not m:
        return None
    if "TREND_V3" in m or "EMA_PULLBACK" in m or "STRUCTURE_BREAK" in m:
        return "TREND"
    if "BB_BOUNCE" in m or "CONFIRMATION_FALLBACK" in m or "BB_REV" in m:
        return "FADE"
    return None


def _fxi_regime_agrees(regime: str, direction: str) -> bool:
    """True iff engine's winning_regime is a STRONG/FORMING trend whose
    direction matches the fire (BUY↔UP, SELL↔DOWN). CHOP / missing /
    non-trend regimes return False."""
    r = (regime or "").upper()
    d = (direction or "").upper()
    if ("STRONG_TREND_" not in r) and ("TREND_FORMING_" not in r):
        return False
    if r.endswith("_UP") and d == "BUY":
        return True
    if r.endswith("_DOWN") and d == "SELL":
        return True
    return False


def _fxi_regime_opposes(regime: str, direction: str) -> bool:
    """True iff engine's winning_regime is a STRONG/FORMING trend whose
    direction is the OPPOSITE of the fire (BUY vs a DOWN regime, SELL
    vs an UP regime). CHOP / missing → False."""
    r = (regime or "").upper()
    d = (direction or "").upper()
    if ("STRONG_TREND_" not in r) and ("TREND_FORMING_" not in r):
        return False
    if r.endswith("_DOWN") and d == "BUY":
        return True
    if r.endswith("_UP") and d == "SELL":
        return True
    return False


def _fxi_location_assess(
    pair: str,
    direction: str,
    entry_price: Optional[float],
    mode: str,
) -> Optional[Dict[str, Any]]:
    """Score the fire's LOCATION against today's FXi plan + the engine's
    held regime. Fail-open: return None on any missing input / reader
    None / exception — the caller then neither stamps nor vetoes.

    Returned dict on success::

        {
          "score":       int,   # sum of clause weights
          "veto":        bool,  # score <= FXI_VETO_FLOOR
          "clauses":     [str], # e.g. ["P1_STANDASIDE_TREND-100"]
          "plan_state":  str|None,
          "plan_target": float|None,
          "regime_held": str|None,
          "dist_00":     float, # entry's distance to nearest 00 (pips)
        }
    """
    try:
        d = (direction or "").upper()
        if d not in ("BUY", "SELL") or entry_price is None:
            return None

        try:
            import fxi_briefing_reader as _fxi_reader
            plan = _fxi_reader.get_today_plan(pair)
        except Exception as _rd_exc:
            _fxi_loc_warn_once("[FXI_LOCATION] reader import/call failed", _rd_exc)
            return None
        if not isinstance(plan, dict):
            return None

        plan_state = _safe_str(plan.get("state")).strip().upper() or None
        plan_dir = _safe_str(plan.get("direction")).strip().upper() or None
        _pt_raw = plan.get("plan_target")
        try:
            plan_target = float(_pt_raw) if _pt_raw is not None else None
        except (TypeError, ValueError):
            plan_target = None

        # Plan levels (support + resistance) as a flat float list. When the
        # reader returns None / no key_levels, this stays empty and P4
        # degrades to the 00-grid test alone.
        _plan_levels: List[float] = []
        for _lk in ("support_levels", "resistance_levels"):
            _lv = plan.get(_lk)
            if isinstance(_lv, (list, tuple)):
                for _x in _lv:
                    try:
                        _plan_levels.append(float(_x))
                    except (TypeError, ValueError):
                        continue

        try:
            import regime_engine as _re
            _rr = _re.latest_result(pair) or {}
        except Exception as _re_exc:
            _fxi_loc_warn_once("[FXI_LOCATION] regime cache read failed", _re_exc)
            _rr = {}
        regime_held = _safe_str(_rr.get("winning_regime")).strip().upper() or None

        family = _fxi_location_family(mode)
        ep = float(entry_price)
        mod100 = ep % 100.0
        dist_00 = min(mod100, 100.0 - mod100)

        # Distance to the nearest plan level (support ∪ resistance). None
        # when the plan carries no levels; consumers should fall back to
        # dist_00 in that case.
        _dist_plan_level: Optional[float] = None
        if _plan_levels:
            _dist_plan_level = min(abs(ep - _lv) for _lv in _plan_levels)
        dist_nearest_level = (
            min(dist_00, _dist_plan_level)
            if _dist_plan_level is not None
            else dist_00
        )

        score = 0
        clauses: List[str] = []

        # P1: STAND_ASIDE × TREND family — plan says no trend today; a
        # trend-family fire ignores that call.
        if (
            os.getenv("FXI_P_STANDASIDE_TREND_ENABLED", "1") == "1"
            and plan_state == "STAND_ASIDE"
            and family == "TREND"
        ):
            _w = int(os.getenv("FXI_P_STANDASIDE_TREND", "-100"))
            score += _w
            clauses.append(f"P1_STANDASIDE_TREND{_w:+d}")

        # P2: BEYOND_TARGET — plan is in the fire's direction and the
        # fire's entry is past plan target by more than a 2p tolerance
        # (BUY: entry ≥ target+2; SELL: entry ≤ target-2).
        if (
            os.getenv("FXI_P_BEYOND_TARGET_ENABLED", "1") == "1"
            and plan_target is not None
            and plan_dir in ("BUY", "SELL")
            and plan_dir == d
        ):
            _beyond = (
                (d == "BUY" and ep >= plan_target + 2.0)
                or (d == "SELL" and ep <= plan_target - 2.0)
            )
            if _beyond:
                _w = int(os.getenv("FXI_P_BEYOND_TARGET", "-100"))
                score += _w
                clauses.append(f"P2_BEYOND_TARGET{_w:+d}")

        # P3: WITH_MOVE_00_OVERSHOOT — entry is 3-20p past the nearest
        # 00 in the fire's direction AND the engine's held regime
        # agrees with that direction (continuation chase). Regime
        # neutral / opposing / absent → clause does not apply.
        if os.getenv("FXI_P_00_OVERSHOOT_ENABLED", "1") == "1":
            if d == "BUY":
                _overshoot = 3.0 <= mod100 <= 20.0
            else:
                _overshoot = 3.0 <= (100.0 - mod100) <= 20.0
            if _overshoot and _fxi_regime_agrees(regime_held or "", d):
                _w = int(os.getenv("FXI_P_00_OVERSHOOT", "-40"))
                score += _w
                clauses.append(f"P3_00_OVERSHOOT{_w:+d}")

        # C1: REVERSAL_RECLAIM — fire OPPOSES a STRONG/FORMING regime
        # AND entry is within 20p of a 00 figure. Rewards the reclaim
        # shape (counter-move entry off a round number).
        if (
            os.getenv("FXI_C_REVERSAL_ENABLED", "1") == "1"
            and _fxi_regime_opposes(regime_held or "", d)
            and dist_00 <= 20.0
        ):
            _w = int(os.getenv("FXI_C_REVERSAL", "40"))
            score += _w
            clauses.append(f"C1_REVERSAL{_w:+d}")

        # C2: FADE_FAMILY_STANDASIDE — plan's no-trend call is
        # consistent with a mean-reversion setup; mild positive.
        if (
            os.getenv("FXI_C_FADE_SA_ENABLED", "1") == "1"
            and plan_state == "STAND_ASIDE"
            and family == "FADE"
        ):
            _w = int(os.getenv("FXI_C_FADE_SA", "20"))
            score += _w
            clauses.append(f"C2_FADE_SA{_w:+d}")

        # P4: UNANCHORED_FADE — fire OPPOSES a STRONG/FORMING regime,
        # entry is >radius from the nearest 00 figure AND >radius from
        # every known plan level (support + resistance). Fades in the
        # void — no round-number reclaim, no S/R anchor — are the ones
        # that get run over. When the plan carries no levels (reader None
        # / empty key_levels), the plan-level test is vacuously true and
        # the 00-grid test decides alone.
        # Mutual exclusivity with C1: C1 requires dist_00 <= 20; P4
        # requires dist_00 > FXI_P4_LEVEL_RADIUS_PIPS (default 20). With
        # the default radius they cannot both fire on the same entry.
        if (
            os.getenv("FXI_P4_ENABLED", "1") == "1"
            and _fxi_regime_opposes(regime_held or "", d)
        ):
            _radius = float(os.getenv("FXI_P4_LEVEL_RADIUS_PIPS", "20"))
            _off_00 = dist_00 > _radius
            _off_plan = (
                _dist_plan_level is None or _dist_plan_level > _radius
            )
            if _off_00 and _off_plan:
                _w = int(os.getenv("FXI_P_UNANCHORED_FADE", "-100"))
                score += _w
                clauses.append(f"P4_UNANCHORED_FADE{_w:+d}")

        floor = int(os.getenv("FXI_VETO_FLOOR", "-90"))
        return {
            "score": score,
            "veto": score <= floor,
            "clauses": clauses,
            "plan_state": plan_state,
            "plan_target": plan_target,
            "regime_held": regime_held,
            "dist_00": round(dist_00, 2),
            "dist_nearest_level": round(dist_nearest_level, 2),
        }
    except Exception as _fx_exc:
        _fxi_loc_warn_once("[FXI_LOCATION] assess exception", _fx_exc)
        return None


CONFIRM_RETRIES = int(os.getenv("CONFIRM_RETRIES", "6"))
CONFIRM_SLEEP_SECS = float(os.getenv("CONFIRM_SLEEP_SECS", "0.35"))

DEFAULT_PIP_SIZE = float(os.getenv("DEFAULT_PIP_SIZE", "1"))

MIN_SL_PIPS = float(os.getenv("MIN_SL_PIPS", "2") or 2.0)
MIN_TP_PIPS = float(os.getenv("MIN_TP_PIPS", "2") or 2.0)
MAX_REASONABLE_SL_PIPS = float(os.getenv("MAX_REASONABLE_SL_PIPS", "500") or 500.0)
MAX_REASONABLE_TP_PIPS = float(os.getenv("MAX_REASONABLE_TP_PIPS", "1000") or 1000.0)

# IG broker minimum stop/limit distance (IG POINTS) — orders below this are rejected.
# GBPUSD requires 12 pts minimum; others are lower. 12 is a safe global floor.
MIN_STOP_DISTANCE_PIPS = float(os.getenv("MIN_STOP_DISTANCE_PIPS", "12.0"))
MIN_LIMIT_DISTANCE_PIPS = float(os.getenv("MIN_LIMIT_DISTANCE_PIPS", "12.0"))

# Per-pair minimum SL floors: imported from shared pair_config
from pair_config import MIN_SL_PIPS as _PAIR_MIN_SL_PIPS

# Points-per-pip: imported from shared pair_config
from pair_config import POINTS_PER_PIP as _POINTS_PER_PIP, DEFAULT_PPP as _DEFAULT_PPP

# Per-pair IG API minimum stop distances (in IG POINTS), from /markets/{epic} API.
_IG_MIN_STOP_PTS: Dict[str, float] = {
    "GBPUSD": float(os.getenv("GBPUSD_IG_MIN_STOP_PTS", "12")),
    "EURUSD": float(os.getenv("EURUSD_IG_MIN_STOP_PTS", "6")),
    "USDJPY": float(os.getenv("USDJPY_IG_MIN_STOP_PTS", "2")),
    "USDCAD": float(os.getenv("USDCAD_IG_MIN_STOP_PTS", "4")),
    "GBPJPY": float(os.getenv("GBPJPY_IG_MIN_STOP_PTS", "12")),
}


def _ppp_for_pair(pair: str) -> float:
    """Return IG points-per-pip for a pair."""
    return _POINTS_PER_PIP.get(pair, _DEFAULT_PPP)

BLOCK_INVALID_DISTANCES = (os.getenv("BLOCK_INVALID_DISTANCES", "1") or "1").strip() == "1"

CLOSE_VERIFY_RETRIES = int(os.getenv("CLOSE_VERIFY_RETRIES", "6") or 6)
CLOSE_VERIFY_SLEEP_SECS = float(os.getenv("CLOSE_VERIFY_SLEEP_SECS", "0.5") or 0.5)

# Retries for fetching the close deal confirmation (actual fill level).
# By the time close-verify passes, IG has already settled the trade, so
# the confirmation is usually available on the first attempt.  Kept
# deliberately small to avoid adding latency to the close path.
CLOSE_CONFIRM_RETRIES = int(os.getenv("CLOSE_CONFIRM_RETRIES", "3") or 3)
CLOSE_CONFIRM_SLEEP_SECS = float(os.getenv("CLOSE_CONFIRM_SLEEP_SECS", "0.5") or 0.5)


def _enrich_alert_debug(
    dbg: Optional[Dict[str, Any]],
    entry_price: Any,
    sl_pips: Any,
    direction: str,
    pair: str,
) -> Dict[str, Any]:
    """Populate sl_price / sl_source / level_price / level_source into the
    alert debug dict so telegram_alerts.send_trade_open_alert never renders
    empty parens. On IG spread-bet feeds 1 pip == 1 point, so the broker SL
    price is entry ± sl_pips scaled by points-per-pip. Strategy-provided
    values win: setdefault preserves anything the caller already supplied.
    """
    out: Dict[str, Any] = dict(dbg) if isinstance(dbg, dict) else {}
    try:
        e = float(entry_price)
        s = float(sl_pips)
        ppp = _ppp_for_pair(pair)
        sign = -1.0 if str(direction).upper() == "BUY" else 1.0
        broker_sl = e + sign * s * ppp
        out.setdefault("sl_price", round(broker_sl, 1))
    except (TypeError, ValueError):
        pass
    out.setdefault("sl_source", "broker")
    out.setdefault("level_price", None)
    out.setdefault("level_source", None)
    return out


# ============================================================
# STATE
# ============================================================

_STATE_TEMPLATE: Dict[str, Any] = {
    "active": False,
    "pending_open": False,
    "epic": None,
    "direction": None,
    "entry_price": None,
    "requested_entry_price": None,
    "dealReference": None,
    "dealId": None,
    "deal_id": None,
    "size": None,
    "open_time": None,
    "mode": None,
    "reason": None,
    "sl": None,
    "tp": None,
    "pip_size": DEFAULT_PIP_SIZE,
    "last_mid": None,
    "exit_price": None,
    "close_reason": None,
    "invalidation_price": None,
    "invalidation_direction": None,
    # Scale-out bookkeeping (2026-05-23). Populated by trade_manager._scale_out_50pct
    # when the +10p/50% partial close fires. _on_trade_close reads these to
    # compute total_pnl_pips = partial_bank_pips + runner_pnl_pips so the
    # regime_instance_id OUTCOME JOIN reflects the FULL trade, not half.
    "original_size": None,
    "partial_bank_pips": None,
    "partial_bank_ts": None,
    "scaled_out": False,
    # Phase 3 regime-keyed management. profile_id is stamped at fire
    # from regime_matrix.effective_regime() and never re-evaluated for
    # the position's life. LEGACY = current per-strategy behaviour.
    # Set to None on state creation; concrete value only after
    # ACCEPTED via _stamp_profile_at_fire().
    "profile_id": None,
    "regime_at_fire_effective": None,
}

EPIC_STATE: Dict[str, Dict[str, Any]] = {}
TRADE_STATE_BY_EPIC = EPIC_STATE
TRADE_STATE: Dict[str, Any] = {}


# ── Phase 3 regime-keyed management ───────────────────────────────
# Master flag REGIME_MGMT_ENABLED (default 0 = current behaviour).
# When ON, ACCEPTED trades receive a profile_id stamp from the matrix's
# effective_regime at fire; profile-managed trades bypass the legacy
# per-strategy trail multiplex in trade_manager.
REGIME_MGMT_ENABLED = (
    os.getenv("REGIME_MGMT_ENABLED", "0") or "0"
).strip().lower() in ("1", "true", "yes", "on")

_REGIME_TO_PROFILE = {
    "STRONG_TREND_UP":    "STRONG",
    "STRONG_TREND_DOWN":  "STRONG",
    "TREND_FORMING_UP":   "FORMING",
    "TREND_FORMING_DOWN": "FORMING",
    "RANGE_ROTATION":     "RANGE",
}


def _stamp_profile_at_fire(st: Dict[str, Any], epic: str) -> None:
    """Stamp profile_id and regime_at_fire_effective on EPIC_STATE at
    fire time. No-op when REGIME_MGMT_ENABLED=0. Called from each of
    the three ACCEPTED branches in execute_trade.

    Mapping (from Phase 3 build spec):
      STRONG_TREND_UP / DOWN  → "STRONG"
      TREND_FORMING_UP / DOWN → "FORMING"
      RANGE_ROTATION          → "RANGE" (telemetry only; scalp path unchanged)
      CHOP / UNKNOWN / matrix-off / any error → "LEGACY"

    Reconciliation / restart: state dicts rebuilt from broker positions
    on restart never pass through this stamp — they default to
    profile_id=None and are treated as LEGACY by trade_manager.
    """
    if not REGIME_MGMT_ENABLED:
        return
    try:
        import regime_matrix as _rm
        _sym = _pair_from_epic(epic)
        _eff = _rm.effective_regime(_sym)
        eff_str = str(_eff or "").upper() or None
        st["regime_at_fire_effective"] = eff_str
        st["profile_id"] = _REGIME_TO_PROFILE.get(eff_str or "", "LEGACY")
    except Exception as _stamp_exc:
        logger.warning(
            "[REGIME_MGMT] profile stamp failed for %s (fail-safe → LEGACY): %s",
            epic, _stamp_exc,
        )
        st["profile_id"] = "LEGACY"
        st["regime_at_fire_effective"] = None

# ------------------------------------------------------------
# EPIC_STATE_LOCK (LS-thread refactor 2026-05-08)
# ------------------------------------------------------------
# RLock guarding cross-pair iterations of EPIC_STATE. Per-pair workers
# serialize same-pair access naturally (one drainer per pair), but
# ITERATIONS that span pairs (pair_concurrency_check, SYNC orphan
# sweep) need a brief lock so a different pair's worker
# doesn't mutate the dict mid-iteration.
#
# Granularity is microseconds — a snapshot pass over a small dict.
# Reentrant because some call sites (execute_trade open path) hold the
# lock around a count-and-reserve sequence that itself reads EPIC_STATE.
EPIC_STATE_LOCK: threading.RLock = threading.RLock()

# Close-event callbacks: fn(pos_key, exit_price, pnl_pips, close_reason)
_CLOSE_CALLBACKS: List[Callable] = []
# Open-event callbacks: fn(pos_key, decision)
_OPEN_CALLBACKS: List[Callable] = []


def register_trade_close_callback(fn: Callable) -> None:
    """Register a callback invoked after a trade closes successfully.

    Signature: fn(pos_key: str, exit_price: Optional[float],
                  pnl_pips: Optional[float], close_reason: str)
    pos_key is "{epic}|{mode}".
    """
    _CLOSE_CALLBACKS.append(fn)


def register_trade_open_callback(fn: Callable) -> None:
    """Register a callback invoked after a trade is ACCEPTED by the broker.

    Signature: fn(pos_key: str, decision: Any)
    The decision is the StrategyDecision that was passed to execute_trade().
    Strategies use this to confirm pending proposals have actually opened —
    the state-gate that prevents the DAILY_DOUBLE dormancy bug.
    """
    _OPEN_CALLBACKS.append(fn)


def _fire_open_callbacks(pos_key: str, decision: Any) -> None:
    """Notify all registered strategies that a trade opened. A callback
    exception means the broker opened the position but the strategy did
    NOT record it — a silent orphan. This is a real-money risk: the next
    BB_REVERSAL evaluate() would ignore the leg and could over-pyramid or
    fire an opposite direction. Logs LEG-ORPHAN-DETECTED at ERROR and
    attempts a Telegram alert so a human can manually reconcile.
    """
    for cb in list(_OPEN_CALLBACKS):
        try:
            cb(pos_key, decision)
        except Exception as e:
            cb_name = getattr(cb, "__name__", repr(cb))
            mode = ""
            try:
                mode = str(getattr(decision, "mode", "") or "")
            except Exception:
                pass
            logger.error(
                "LEG-ORPHAN-DETECTED pos_key=%s mode=%s callback=%s "
                "error=%s: %s — broker position opened but strategy did "
                "NOT record the leg. Manual reconciliation required.",
                pos_key, mode, cb_name, type(e).__name__, e,
            )
            try:
                from telegram_alerts import send_telegram_message
                # wait=True: per ls_refactor_safety_audit_20260508.md §4,
                # this is the one telegram callsite that needs synchronous
                # delivery — it fires on broker-state divergence and the
                # alert must reach the operator before the next trade
                # decision is made. All other callsites are observability
                # or run on process boundaries (atexit drains those).
                send_telegram_message(
                    f"🚨 <b>LEG-ORPHAN-DETECTED</b>\n"
                    f"pos_key: <code>{pos_key}</code>\n"
                    f"mode: <code>{mode}</code>\n"
                    f"callback: <code>{cb_name}</code>\n"
                    f"error: <code>{type(e).__name__}: {e}</code>\n"
                    f"Position opened at broker; strategy state did NOT record it. "
                    f"Manual reconciliation required.",
                    wait=True,
                )
            except Exception as _alert_exc:
                logger.error(
                    "LEG-ORPHAN-DETECTED telegram alert also failed: %s: %s",
                    type(_alert_exc).__name__, _alert_exc,
                )


# ============================================================
# POSITION KEY HELPERS
# ============================================================

def _pos_key(epic: str, mode: str) -> str:
    """Build a position key from epic and strategy mode."""
    return f"{str(epic).strip()}|{str(mode or 'DEFAULT').strip().upper()}"


def _epic_from_pos_key(pos_key: str) -> str:
    """Extract the epic portion from a position key."""
    return pos_key.split("|", 1)[0]


def _mode_from_pos_key(pos_key: str) -> str:
    """Extract the mode portion from a position key."""
    parts = pos_key.split("|", 1)
    return parts[1] if len(parts) > 1 else "DEFAULT"


def get_all_positions_for_epic(epic: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Return list of (pos_key, state_dict) for all active/pending positions on this epic."""
    epic = str(epic).strip()
    prefix = epic + "|"
    # Snapshot via list() so a concurrent EPIC_STATE mutation on another
    # thread (e.g. cross-pair worker creating a new pk) cannot raise
    # RuntimeError: dictionary changed size during iteration mid-list-comp
    # and silently kill the per-tick monitor. Mirrors the existing
    # snapshot pattern at count_open_positions_by_pair_direction (~L600).
    return [
        (k, v) for k, v in list(EPIC_STATE.items())
        if k.startswith(prefix) and (v.get("active") or v.get("pending_open"))
    ]


def find_open_state_by_dealid(deal_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Return (pos_key, state) for the first EPIC_STATE entry whose dealId matches.

    Scans *all* entries regardless of epic or pos_key suffix, used by the sync
    loop to find orphaned pos_keys when a dealId disappears from IG.
    """
    if not deal_id:
        return None
    did = str(deal_id)
    # Snapshot via list() — same rationale as get_all_positions_for_epic.
    for k, v in list(EPIC_STATE.items()):
        st_did = str(v.get("dealId") or v.get("deal_id") or "")
        if st_did == did and (v.get("active") or v.get("pending_open")):
            return (k, v)
    return None


# ──────────────────────────────────────────────────────────────
# Signal-log lookup — used by reconcile to recover the originating
# strategy/mode and the signal_log trade_id so close-outcome patching
# continues to work after a restart.
# ──────────────────────────────────────────────────────────────
_SIGNAL_LOG_PATH = "/opt/tradingbot/logs/signal_log.jsonl"

# Foreign-deals telemetry log — appended to (one JSONL row per skipped
# foreign IG position observed during reconcile). PURE LOGGING — no live
# code path reads this. Override via env for tests.
_FOREIGN_DEALS_LOG_PATH = os.getenv(
    "FOREIGN_DEALS_LOG_PATH",
    "/opt/tradingbot/logs/foreign_deals_observed.jsonl",
)


def _log_foreign_deal(record: Dict[str, Any]) -> None:
    """Append one foreign-deal observation. Never raises."""
    try:
        import json
        from pathlib import Path
        from datetime import datetime, timezone
        record = dict(record)
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        p = Path(_FOREIGN_DEALS_LOG_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")
    except Exception as exc:  # noqa: BLE001 — telemetry must never raise
        try:
            logger.debug("[RECONCILE] foreign-deal telemetry write failed: %s", exc)
        except Exception:
            pass


def lookup_signal_log_by_deal_id(
    deal_id: str,
    scan_lines: int = 2000,
) -> Optional[Dict[str, Any]]:
    """Find the most recent signal_log entry whose deal_id matches.

    Used by startup reconciliation to recover the original strategy mode for
    a position that survived a service restart. Strongest match available —
    deal_id is the broker's unique id and cannot collide. Returns None if
    deal_id is empty, the log file is missing, or no entry matches.
    """
    if not deal_id:
        return None
    try:
        import json
        from collections import deque
        try:
            with open(_SIGNAL_LOG_PATH, "r", encoding="utf-8") as f:
                tail = deque(f, maxlen=scan_lines)
        except FileNotFoundError:
            return None

        target = str(deal_id).strip()
        match = None
        for line in tail:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except Exception:
                continue
            if str(rec.get("deal_id") or "").strip() == target:
                match = rec  # last wins (most recent)
        return match
    except Exception:
        return None


def lookup_signal_log_by_deal_reference(
    deal_reference: str,
    scan_lines: int = 2000,
) -> Optional[Dict[str, Any]]:
    """Find the most recent signal_log entry whose dealReference matches.

    Same shape as lookup_signal_log_by_deal_id but keys on dealReference,
    which is the bot-chosen request id stamped at dispatch (vs the broker-
    assigned dealId). Useful as a secondary key for the own-deals-only
    reconcile gate when a race left the dealId blank in signal_log but the
    dealReference is still present. Returns None on missing file, empty
    input, or no match — same swallow-all semantics as the deal_id helper.
    """
    if not deal_reference:
        return None
    try:
        import json
        from collections import deque
        try:
            with open(_SIGNAL_LOG_PATH, "r", encoding="utf-8") as f:
                tail = deque(f, maxlen=scan_lines)
        except FileNotFoundError:
            return None

        target = str(deal_reference).strip()
        match = None
        for line in tail:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except Exception:
                continue
            for key in ("dealReference", "deal_reference"):
                v = rec.get(key)
                if v is not None and str(v).strip() == target:
                    match = rec
                    break
        return match
    except Exception:
        return None


def lookup_signal_log_open(
    epic: str,
    direction: str,
    entry_price: Optional[float],
    tolerance_pips: float = 0.5,
    pip_size: float = 0.0001,
    scan_lines: int = 400,
) -> Optional[Dict[str, Any]]:
    """Find the most recent OPEN signal_log entry matching this epic + direction +
    entry_price (within tolerance). Returns the parsed record (dict) or None.

    Prefers entries with outcome == null (still open) over already-closed ones.
    """
    if not epic or not direction or entry_price is None:
        return None
    try:
        import json
        from collections import deque
        try:
            with open(_SIGNAL_LOG_PATH, "r", encoding="utf-8") as f:
                tail = deque(f, maxlen=scan_lines)
        except FileNotFoundError:
            return None

        dir_u = str(direction).upper()
        ep_s = str(epic).strip()
        tol_price = tolerance_pips * float(pip_size or 0.0001) * 10000  # in price-unit pips as logged (×10000)
        # The signal_log's "entry" field is already stored in the same units as
        # the rest of the codebase (e.g. 13530.3 for 1.35303). Tolerance of
        # 0.5 pips equals 0.5 in those units.
        tol = float(tolerance_pips)

        best_open = None
        best_closed = None
        for line in tail:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except Exception:
                continue
            if str(rec.get("epic") or "") != ep_s:
                continue
            if str(rec.get("direction") or "").upper() != dir_u:
                continue
            ep_f = rec.get("entry")
            if ep_f is None:
                continue
            try:
                if abs(float(ep_f) - float(entry_price)) > tol:
                    continue
            except Exception:
                continue
            if rec.get("outcome") is None:
                best_open = rec  # keep scanning; last wins (most recent)
            else:
                best_closed = rec
        return best_open or best_closed
    except Exception:
        return None


def _sync_legacy_trade_state_from(st: Optional[Dict[str, Any]]) -> None:
    try:
        TRADE_STATE.clear()
        if isinstance(st, dict):
            TRADE_STATE.update(st)
    except Exception:
        pass


def _state_for_epic(pos_key: str) -> Dict[str, Any]:
    """Get or create state for a position key.

    Accepts either a pos_key ("{epic}|{mode}") or a bare epic for backward
    compatibility.  When a bare epic is given, returns the first active
    position for that epic, or creates a DEFAULT-mode entry.
    """
    pos_key = str(pos_key).strip()
    if "|" not in pos_key:
        # Bare epic — find first active position, or create DEFAULT.
        # Snapshot via list() — same rationale as get_all_positions_for_epic.
        prefix = pos_key + "|"
        for k, v in list(EPIC_STATE.items()):
            if k.startswith(prefix) and (v.get("active") or v.get("pending_open")):
                _sync_legacy_trade_state_from(v)
                return v
        pos_key = _pos_key(pos_key, "DEFAULT")
    if pos_key not in EPIC_STATE:
        epic = _epic_from_pos_key(pos_key)
        EPIC_STATE[pos_key] = dict(_STATE_TEMPLATE)
        EPIC_STATE[pos_key]["epic"] = epic
    st = EPIC_STATE[pos_key]
    _sync_legacy_trade_state_from(st)
    return st


def _reset_trade_state(pos_key: str) -> None:
    pos_key = str(pos_key).strip()
    epic = _epic_from_pos_key(pos_key)
    EPIC_STATE[pos_key] = dict(_STATE_TEMPLATE)
    EPIC_STATE[pos_key]["epic"] = epic
    _sync_legacy_trade_state_from(EPIC_STATE[pos_key])


# ============================================================
# PUBLIC STATE HELPERS
# ============================================================

def has_active_trade(epic: str) -> bool:
    """Return True if ANY position is active or pending for this epic."""
    epic = str(epic).strip()
    prefix = epic + "|"
    # Snapshot via list() — same rationale as get_all_positions_for_epic.
    for k, v in list(EPIC_STATE.items()):
        if k.startswith(prefix) and (v.get("active") or v.get("pending_open")):
            return True
    return False


def has_active_trade_for_mode(epic: str, mode: str) -> bool:
    """Return True if a position is active/pending for this specific epic+mode."""
    pk = _pos_key(epic, mode)
    st = EPIC_STATE.get(pk)
    return bool(st and (st.get("active") or st.get("pending_open")))


def count_open_positions_by_pair_direction(pair: str, direction: str) -> int:
    """Count active or pending-open positions in EPIC_STATE matching a given
    pair (e.g. "GBPUSD") and direction ("BUY" / "SELL"). Used by the
    pair-concurrency cap. Counts both committed (active=True) and just-staged
    (pending_open=True) entries; this is the "if I add another, would the
    cap be exceeded?" semantics the cap-check requires."""
    pair_u = str(pair).upper()
    direction_u = str(direction).upper()
    count = 0
    # EPIC_STATE_LOCK: snapshot iteration to prevent concurrent pair-worker
    # mutation from racing the cap count.
    with EPIC_STATE_LOCK:
        items = list(EPIC_STATE.items())
    for k, st in items:
        if not (st.get("active") or st.get("pending_open")):
            continue
        epic_part = k.split("|", 1)[0]
        if _pair_from_epic(epic_part) != pair_u:
            continue
        if str(st.get("direction") or "").upper() != direction_u:
            continue
        count += 1
    return count


def _env_int_safe(name: str, default: int = 0) -> int:
    """Read an integer env var, treating '' / None / non-numeric as `default`."""
    v = os.getenv(name, "")
    if v is None:
        return default
    v = v.strip()
    if not v:
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def pair_concurrency_check(pair: str, direction: str) -> Tuple[bool, str]:
    """Check whether a new entry on `pair` in `direction` would breach the
    concurrency caps configured via env vars:
        {PAIR}_MAX_CONCURRENT       -- total open positions on pair
        {PAIR}_MAX_PER_DIRECTION    -- total open in that direction

    Both <= 0 (or unset / empty) means "no cap on that dimension".
    Returns (allowed, reason). `reason` is empty when allowed.
    """
    pair_u = str(pair).upper()
    direction_u = str(direction).upper()

    max_total   = _env_int_safe(f"{pair_u}_MAX_CONCURRENT")
    max_per_dir = _env_int_safe(f"{pair_u}_MAX_PER_DIRECTION")

    if max_total <= 0 and max_per_dir <= 0:
        return True, ""

    open_long  = count_open_positions_by_pair_direction(pair_u, "BUY")
    open_short = count_open_positions_by_pair_direction(pair_u, "SELL")
    total_open = open_long + open_short

    if max_total > 0 and total_open >= max_total:
        return False, f"{pair_u} at max concurrent ({total_open}/{max_total})"

    if max_per_dir > 0:
        if direction_u == "BUY" and open_long >= max_per_dir:
            return False, f"{pair_u} at max per-direction LONG ({open_long}/{max_per_dir})"
        if direction_u == "SELL" and open_short >= max_per_dir:
            return False, f"{pair_u} at max per-direction SHORT ({open_short}/{max_per_dir})"

    return True, ""


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _to_float_or_none(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:
            return None
        return v
    except Exception:
        return None


def _safe_str(x: Any) -> str:
    try:
        return str(x)
    except Exception:
        return ""


def _extract_positions_list(open_pos: Any) -> list:
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
    if not isinstance(pos_item, dict):
        return False

    pos = pos_item.get("position") if isinstance(pos_item.get("position"), dict) else pos_item

    pid = _safe_str(pos.get("dealId") or pos.get("deal_id") or pos.get("dealID") or "")
    pepic = _safe_str(pos.get("epic") or pos.get("instrumentName") or "")

    if deal_id and pid and pid == deal_id:
        return True
    if epic and pepic and pepic == epic:
        return True
    return False


def _position_still_open(epic: str, deal_id: Optional[str]) -> bool:
    try:
        open_pos = get_open_positions()
        if open_pos is None:
            # API error — cannot confirm closure; assume still open to prevent false close alert.
            logger.warning(f"[CLOSE_VERIFY] get_open_positions returned None for {epic}; assuming still open")
            return True
        items = _extract_positions_list(open_pos)
        for item in items:
            if _position_matches_trade_state(item, deal_id=deal_id or None, epic=epic or None):
                return True
        return False
    except Exception as e:
        logger.error(f"[CLOSE_VERIFY] open positions check failed for {epic}: {type(e).__name__}: {e}")
        return True


def _sanitize_distance(
    *,
    label: str,
    raw_value: Any,
    min_pips: float,
    max_pips: float,
    fallback: float,
) -> Tuple[Optional[float], Optional[str]]:
    v = _to_float_or_none(raw_value)

    if v is None:
        if BLOCK_INVALID_DISTANCES:
            return None, f"{label}_missing_or_non_numeric"
        logger.warning(f"[DISTANCE_SANITIZE] {label} invalid -> fallback {fallback}")
        return float(fallback), None

    if not (v > 0):
        if BLOCK_INVALID_DISTANCES:
            return None, f"{label}_non_positive"
        logger.warning(f"[DISTANCE_SANITIZE] {label} non-positive ({v}) -> fallback {fallback}")
        return float(fallback), None

    if v < float(min_pips):
        if BLOCK_INVALID_DISTANCES:
            return None, f"{label}_below_min_{min_pips:g}"
        logger.warning(f"[DISTANCE_SANITIZE] {label} too small ({v}) -> clamp {min_pips}")
        return float(min_pips), None

    if v > float(max_pips):
        if BLOCK_INVALID_DISTANCES:
            return None, f"{label}_above_max_{max_pips:g}"
        logger.warning(f"[DISTANCE_SANITIZE] {label} too large ({v}) -> clamp {max_pips}")
        return float(max_pips), None

    return float(v), None


def _extract_rejection_detail(conf: Any) -> str:
    if not isinstance(conf, dict):
        return ""
    keys = [
        "reason",
        "status",
        "errorCode",
        "error_code",
        "dealStatus",
        "message",
        "dealReference",
        "dealId",
    ]
    parts = []
    for k in keys:
        if k in conf and conf.get(k) not in (None, ""):
            parts.append(f"{k}={conf.get(k)}")
    return " ".join(parts).strip()


def _close_reason_or_default(st: Dict[str, Any], default_reason: str) -> str:
    raw = st.get("close_reason")
    if raw is None:
        return default_reason
    reason = _safe_str(raw).strip()
    # Avoid the literal string "None" leaking through when upstream stored
    # None via `st["close_reason"] = None` and a later caller coerced it.
    if not reason or reason.lower() == "none":
        return default_reason
    return reason


# ============================================================
# EXECUTE TRADE
# ============================================================

def execute_trade(decision: Any, epic: str):
    # Clear the telemetry slot at entry so a previous block can't leak
    # into this call's annotation. Wrappers read via consume_last_block_info().
    _clear_block_info()

    epic = str(epic).strip()

    # ── Execution-latency: dispatch entry timestamp ───────────────────────
    # Captured before any work / gating so we measure the full dispatch
    # path.  t_decision is read from the strategy's decision.debug so we
    # don't have to modify every strategy file; if missing we fall back
    # to t_dispatch (post-refactor strategies will set it explicitly so
    # the queue lag becomes measurable).
    _t_dispatch = _elm.now_epoch_ms()
    try:
        _dec_dbg_for_ts = getattr(decision, "debug", None) or {}
        _t_decision = _dec_dbg_for_ts.get("t_decision_epoch_ms")
        if _t_decision is not None:
            _t_decision = int(_t_decision)
    except Exception:
        _t_decision = None
    if _t_decision is None:
        # Pre-refactor: strategies don't set t_decision, so dispatch
        # is the earliest measurable timestamp.  decision_to_dispatch
        # will be 0 in this case, which is the correct baseline.
        _t_decision = _t_dispatch

    if not epic:
        logger.error("❌ execute_trade called with blank epic")
        return None

    # (Direction-router shadow call removed 2026-07-08 per Phase 2 build —
    # was shadow-only; enforcement never ramped. See config block at top.)

    # ------------------------------------------------------------
    # Fire-time staleness recheck — hybrid guard (2026-05-28 rebuild).
    #
    # Original b2d2425 guard compared `now − latest_5M_bar_close` against
    # a 60s threshold. For 5M-bar-driven strategies (evaluate-then-execute
    # within seconds of bar close) that correctly catches the race where
    # candle_lag goes CRITICAL between is_stale() probe and dispatch.
    # For TICK-driven strategies (NEWS_TICK at autobot.py:2682,
    # NEWS_STRATEGY at autobot.py:2878) the same formula trips on normal
    # mid-bar timing — `now − last_5M_close` cycles 0→300s every 5 min,
    # so any fire >60s into the current 5M interval was being blocked on
    # a healthy feed (~80% of wall-clock time). See
    # reports/candle_lag_operational_audit_20260508.md (cited in commit
    # b2d2425) for the original-incident framing.
    #
    # Hybrid: block iff EITHER tick_age > T1 (tick-feed stall) OR
    # bar_age > T2 (coarse aggregator-stall backstop, deliberately loose).
    # T1 catches the upstream cause the original incidents shared
    # (tick-feed delay → late 5M bar → late close → race). T2 stays in
    # play for the rarer "aggregator stuck while ticks still flow" case.
    # Both None → fail-open (matches the pre-existing contract).
    # The upstream is_stale() probe at autobot.py:2851-2867 (NEWS_STRATEGY
    # dispatch) remains the first layer; this is still the final backstop.
    # ------------------------------------------------------------
    _T1 = float(os.getenv("RACE_TICK_AGE_SECS", "30"))   # tick-feed stall ceiling
    _T2 = float(os.getenv("RACE_BAR_AGE_SECS", "420"))   # aggregator-stall backstop (loose)
    try:
        import candle_lag_monitor as _clm
        _sym = _pair_from_epic(epic)
        _tick_age = _clm.tick_age(_sym)
        _bar_age = _clm.live_lag(_sym)
        _tick_trip = (_tick_age is not None and _tick_age > _T1)
        _bar_trip = (_bar_age is not None and _bar_age > _T2)
        if _tick_trip or _bar_trip:
            _mode_dbg = _safe_str(getattr(decision, "mode", None)).strip().upper() or "?"
            _sig_dbg = _safe_str(getattr(decision, "signal", None)).strip().upper() or "?"
            _tripped = ",".join(
                lbl for lbl, hit in (("tick", _tick_trip), ("bar", _bar_trip)) if hit
            )
            _tick_dbg = f"{_tick_age:.1f}" if _tick_age is not None else "n/a"
            _bar_dbg = f"{_bar_age:.1f}" if _bar_age is not None else "n/a"
            logger.warning(
                "[RACE_CAUGHT] strategy=%s pair=%s signal=%s "
                "tick_age=%ss (T1=%.0f) bar_age=%ss (T2=%.0f) tripped=%s "
                "— fire blocked at execute boundary",
                _mode_dbg, _sym, _sig_dbg,
                _tick_dbg, _T1, _bar_dbg, _T2, _tripped,
            )
            _set_block_info(
                "RACE_CAUGHT",
                f"tripped={_tripped} tick_age={_tick_dbg}s bar_age={_bar_dbg}s",
            )
            try:
                from telegram_alerts import send_telegram_message
                send_telegram_message(
                    f"🛡️ <b>RACE_CAUGHT</b> — fire blocked at execute boundary\n"
                    f"Pair: <code>{_sym}</code> "
                    f"Strategy: <code>{_mode_dbg}</code> "
                    f"Signal: <code>{_sig_dbg}</code>\n"
                    f"tick_age: <b>{_tick_dbg}s</b> (T1 {_T1:.0f}s)  "
                    f"bar_age: <b>{_bar_dbg}s</b> (T2 {_T2:.0f}s)\n"
                    f"tripped: <code>{_tripped}</code>"
                )
            except Exception:
                pass
            return None
    except Exception as _race_exc:
        logger.debug("[RACE_CAUGHT] guard error: %s", _race_exc)

    mode = _safe_str(getattr(decision, "mode", None)).strip().upper() or "DEFAULT"

    # ------------------------------------------------------------
    # HTF-authority gate (2026-06-04). Under REGIME_MATRIX_ENABLED=1
    # the matrix owns enablement — this gate is gated off. Module
    # stays on disk this phase per spec §D.
    # ------------------------------------------------------------
    if not _REGIME_MATRIX_ENABLED_TE:
        try:
            import htf_authority as _hauth
            _sym_h = _pair_from_epic(epic)
            _dir_h = _safe_str(getattr(decision, "signal", None)).strip().upper()
            if _sym_h and _dir_h in ("BUY", "SELL"):
                _ok_h, _reason_h, _ = _hauth.evaluate(_sym_h, _dir_h, mode)
                if not _ok_h:
                    logger.info(
                        "[HTF-AUTHORITY] BLOCKED %s %s %s — %s",
                        _sym_h, _dir_h, mode, _reason_h,
                    )
                    _set_block_info("HTF_AUTHORITY", str(_reason_h))
                    return None
                logger.debug(
                    "[HTF-AUTHORITY] PASS %s %s %s — %s",
                    _sym_h, _dir_h, mode, _reason_h,
                )
        except Exception as _hauth_exc:
            # Fail-open on infrastructure errors — never let the authority
            # gate's own failures block a fire that would otherwise proceed.
            logger.debug("[HTF-AUTHORITY] gate error (fail-open): %s", _hauth_exc)

    # ------------------------------------------------------------
    # Conviction gate (2026-05-29). Gated off under the matrix per
    # spec §D. Module stays on disk this phase.
    # ------------------------------------------------------------
    if not _REGIME_MATRIX_ENABLED_TE:
        try:
            import conviction_gate as _cg
            _sym_cg = _pair_from_epic(epic)
            _dir_cg = _safe_str(getattr(decision, "signal", None)).strip().upper()
            if _sym_cg and _dir_cg in ("BUY", "SELL"):
                _ok, _reason, _details = _cg.evaluate(_sym_cg, _dir_cg, mode)
                if not _ok:
                    logger.info(
                        "[CONVICTION] BLOCKED %s %s %s — %s",
                        _sym_cg, _dir_cg, mode, _reason,
                    )
                    _set_block_info("CONVICTION_GATE", str(_reason))
                    return None
                logger.debug(
                    "[CONVICTION] PASS %s %s %s", _sym_cg, _dir_cg, mode,
                )
                # Regime-direction gate (Piece 2). Default OFF per replay; honour
                # env override if user enables. Independent of conviction gates.
                _ok2, _reason2, _ = _cg.evaluate_direction(_sym_cg, _dir_cg, mode)
                if not _ok2:
                    logger.info(
                        "[REGIME-DIR] BLOCKED %s %s %s — %s",
                        _sym_cg, _dir_cg, mode, _reason2,
                    )
                    _set_block_info("REGIME_DIR", str(_reason2))
                    return None
                logger.debug(
                    "[REGIME-DIR] PASS %s %s %s", _sym_cg, _dir_cg, mode,
                )
        except Exception as _cg_exc:
            # Fail-open on infrastructure errors — never let the gate's own
            # failures block a fire that would otherwise have proceeded.
            logger.debug("[CONVICTION] gate error (fail-open): %s", _cg_exc)

    # ------------------------------------------------------------
    # CROSS-STRATEGY DIRECTIONAL BIAS GATE (2026-07-08). Gated off
    # under the matrix per spec §D.
    # ------------------------------------------------------------
    if not _REGIME_MATRIX_ENABLED_TE and os.getenv("CROSS_BIAS_GATE_ENABLED", "1") == "1":
        try:
            _sym_b = _pair_from_epic(epic)
            _dir_b = _safe_str(getattr(decision, "signal", None)).strip().upper()
            if _sym_b and _dir_b in ("BUY", "SELL"):
                import regime_engine as _re_b
                _live_b = _re_b.latest_result(_sym_b) or {}
                _bias = _safe_str(_live_b.get("directional_bias")).strip().upper()
                _conf_raw = _live_b.get("confidence_final")
                _conf = float(_conf_raw) if _conf_raw is not None else None
                _min_conf = float(os.getenv("CROSS_BIAS_GATE_MIN_CONF", "0.25"))
                _opposed = (
                    (_bias == "LONG" and _dir_b == "SELL")
                    or (_bias == "SHORT" and _dir_b == "BUY")
                )
                if _opposed and _conf is not None and _conf >= _min_conf:
                    _regime = _safe_str(_live_b.get("winning_regime")).strip().upper()
                    _reason_b = (
                        f"counter_bias_blocked dir={_dir_b} bias={_bias} "
                        f"conf={_conf:.3f}>={_min_conf:.3f} regime={_regime}"
                    )
                    logger.info(
                        "[CROSS-BIAS] BLOCKED %s %s %s — %s",
                        _sym_b, _dir_b, mode, _reason_b,
                    )
                    _set_block_info("CROSS_BIAS_GATE", _reason_b)
                    try:
                        import json as _json_b
                        from datetime import datetime as _dt_b, timezone as _tz_b
                        os.makedirs("logs", exist_ok=True)
                        _rec = {
                            "ts": _dt_b.now(_tz_b.utc).isoformat(),
                            "symbol": _sym_b,
                            "strategy": mode,
                            "direction": _dir_b,
                            "bias": _bias,
                            "confidence": round(_conf, 6),
                            "min_conf": _min_conf,
                            "regime": _regime,
                            "reason": "counter_bias_blocked",
                        }
                        with open("logs/cross_bias_gate.jsonl", "a", encoding="utf-8") as _fh:
                            _fh.write(_json_b.dumps(_rec) + "\n")
                    except Exception as _log_exc:
                        logger.debug("[CROSS-BIAS] log write failed: %s", _log_exc)
                    return None
        except Exception as _cb_exc:
            # Fail-open — the cross-bias gate's own failures must never
            # block a fire that would otherwise proceed.
            logger.debug("[CROSS-BIAS] gate error (fail-open): %s", _cb_exc)

    # ------------------------------------------------------------
    # FXi LOCATION-SCORE gate (2026-07-15). Every assessed fire is
    # STAMPED to the journal (pass or veto). Only fires whose total
    # score is ≤ FXI_VETO_FLOOR (-90 default) are vetoed. Master flag
    # FXI_LEVEL_VETO_ENABLED (default "1") gates the whole thing.
    # NEWS_* modes are exempt (skipped entirely). Fail-open: reader
    # returns None / any exception → no stamp, no veto, one WARN max.
    # ------------------------------------------------------------
    if os.getenv("FXI_LEVEL_VETO_ENABLED", "1") == "1" and not mode.startswith("NEWS_"):
        try:
            _fxi_pair = _pair_from_epic(epic)
            _fxi_dir = _safe_str(getattr(decision, "signal", None)).strip().upper()
            _fxi_entry = _to_float_or_none(getattr(decision, "entry", None))
            _fxi_res = _fxi_location_assess(_fxi_pair, _fxi_dir, _fxi_entry, mode)
            if _fxi_res is not None:
                _clauses_str = ",".join(_fxi_res["clauses"]) if _fxi_res["clauses"] else "-"
                _pt_val = _fxi_res["plan_target"]
                _pt_str = f"{_pt_val:.1f}" if _pt_val is not None else "n/a"
                _entry_str = f"{_fxi_entry:.2f}" if _fxi_entry is not None else "n/a"
                logger.info(
                    "[FXI_LOCATION] score=%d clauses=%s pair=%s dir=%s "
                    "strategy=%s entry=%s plan_state=%s plan_target=%s "
                    "dist_00=%s dist_nearest_level=%s regime_held=%s",
                    _fxi_res["score"], _clauses_str, _fxi_pair, _fxi_dir,
                    mode, _entry_str, _fxi_res["plan_state"], _pt_str,
                    _fxi_res["dist_00"], _fxi_res.get("dist_nearest_level"),
                    _fxi_res["regime_held"],
                )
                if _fxi_res["veto"]:
                    logger.info(
                        "[FXI_LEVEL_VETO] score=%d clauses=%s pair=%s dir=%s "
                        "strategy=%s entry=%s plan_state=%s plan_target=%s "
                        "dist_00=%s dist_nearest_level=%s regime_held=%s",
                        _fxi_res["score"], _clauses_str, _fxi_pair, _fxi_dir,
                        mode, _entry_str, _fxi_res["plan_state"], _pt_str,
                        _fxi_res["dist_00"], _fxi_res.get("dist_nearest_level"),
                        _fxi_res["regime_held"],
                    )
                    _set_block_info(
                        "FXI_LEVEL_VETO",
                        f"score={_fxi_res['score']} clauses={_clauses_str}",
                    )
                    return None
        except Exception as _fx_seam_exc:
            # Fail-open — the FXi-location gate's own failures must
            # never block a fire that would otherwise proceed.
            logger.debug("[FXI_LOCATION] seam error (fail-open): %s", _fx_seam_exc)

    # Pair-concurrency cap. Check BEFORE allocating a pos_key or staging
    # pending_open, so blocked signals don't perturb state. This is a
    # drop-not-queue policy: if the setup is still valid 5 minutes from
    # now, it'll re-fire from the strategy's normal evaluation path.
    #
    # Modes in _PAIR_CONCURRENCY_BYPASS_MODES are exempt — they manage
    # their own per-direction slot internally (e.g. BB_PIERCE_RUN's
    # has_open_long/has_open_short slot enforcement at the strategy gate),
    # and would otherwise be blocked by the cross-mode aggregate count
    # when other strategies hold a same-direction position on the pair.
    _PAIR_CONCURRENCY_BYPASS_MODES = (
        "GBPUSD_BB_BOUNCE_L",
        "GBPUSD_BB_BOUNCE_S",
        "GBPUSD_BB_REV_PAT_L",
        "GBPUSD_BB_REV_PAT_S",
    )
    _pair_for_cap = _pair_from_epic(epic)
    _direction_for_cap = _safe_str(getattr(decision, "signal", None)).strip().upper()
    if _direction_for_cap in ("BUY", "SELL") and mode not in _PAIR_CONCURRENCY_BYPASS_MODES:
        _allowed, _cap_reason = pair_concurrency_check(_pair_for_cap, _direction_for_cap)
        if not _allowed:
            logger.info(
                "[CONCURRENCY-CAP] %s %s suppressed — %s mode=%s",
                _pair_for_cap, _direction_for_cap, _cap_reason, mode,
            )
            _set_block_info("CONCURRENCY_CAP", str(_cap_reason))
            return None

    # ------------------------------------------------------------
    # GBPUSD anti-hedge gate (2026-07-21). Portfolio-level. Blocks a
    # new GBPUSD entry when ALL of:
    #   (a) an opposite-direction GBPUSD position is open, AND
    #   (b) 5m PAUSE state present (equal-extreme plateau on last B
    #       closed 5m bars: >=E share a high within T pips of the
    #       B-bar max, OR >=E share a low within T pips of the
    #       B-bar min), AND
    #   (c) mode NOT in GBPUSD_ANTIHEDGE_EXEMPT_MODES (BB_BOUNCE
    #       always allowed to open — fading is its premise).
    # Same-direction entries and exits/scale-outs/trails untouched.
    # Kill-switch GBPUSD_ANTIHEDGE_BLOCK_ENABLED=0 → byte-identical
    # to pre-gate behaviour.
    # ------------------------------------------------------------
    if os.getenv("GBPUSD_ANTIHEDGE_BLOCK_ENABLED", "1") == "1":
        try:
            _ah_pair = _pair_from_epic(epic)
            _ah_dir = _safe_str(getattr(decision, "signal", None)).strip().upper()
            if _ah_pair == "GBPUSD" and _ah_dir in ("BUY", "SELL"):
                _ah_opp = "SELL" if _ah_dir == "BUY" else "BUY"
                _ah_hit = None
                with EPIC_STATE_LOCK:
                    _ah_items = list(EPIC_STATE.items())
                for _k, _s in _ah_items:
                    if not (_s.get("active") or _s.get("pending_open")):
                        continue
                    _ep = str(_k).split("|", 1)[0]
                    if _pair_from_epic(_ep) != "GBPUSD":
                        continue
                    _sd = str(_s.get("direction") or "").upper()
                    if _sd != _ah_opp:
                        continue
                    _sm = str(
                        _s.get("mode")
                        or (_k.split("|", 1)[1] if "|" in _k else "")
                    ).upper()
                    _ah_hit = {
                        "mode": _sm or "?",
                        "direction": _sd,
                        "dealId": _s.get("dealId") or _s.get("deal_id") or "",
                        "pos_key": _k,
                    }
                    break
                if _ah_hit is not None:
                    _ah_pause = False
                    _ah_eq_hi = 0
                    _ah_eq_lo = 0
                    try:
                        import candle_builder as _cb_ah
                        _df_ah = _cb_ah.get_df_raw("GBPUSD")
                        _B = int(float(
                            os.getenv("GBPUSD_ANTIHEDGE_PAUSE_LOOKBACK", "12") or 12
                        ))
                        _E = int(float(
                            os.getenv("GBPUSD_ANTIHEDGE_PAUSE_EQ_BARS", "4") or 4
                        ))
                        _T = float(
                            os.getenv("GBPUSD_ANTIHEDGE_PAUSE_TOL_PIPS", "2.0") or 2.0
                        )
                        _tol = _T * 0.0001  # GBPUSD pip = 0.0001
                        if (
                            _df_ah is not None
                            and not _df_ah.empty
                            and _B > 0
                            and _E > 0
                        ):
                            _tail = _df_ah.tail(_B)
                            if len(_tail) >= _E:
                                _hs = [float(x) for x in _tail["high"].tolist()]
                                _ls = [float(x) for x in _tail["low"].tolist()]
                                _hi_max = max(_hs)
                                _lo_min = min(_ls)
                                _ah_eq_hi = sum(
                                    1 for h in _hs if (_hi_max - h) <= _tol
                                )
                                _ah_eq_lo = sum(
                                    1 for l in _ls if (l - _lo_min) <= _tol
                                )
                                _ah_pause = (_ah_eq_hi >= _E) or (_ah_eq_lo >= _E)
                    except Exception as _ah_pexc:
                        logger.debug(
                            "[ANTIHEDGE] pause probe failed: %s", _ah_pexc
                        )

                    _ah_exempt_raw = os.getenv(
                        "GBPUSD_ANTIHEDGE_EXEMPT_MODES",
                        "GBPUSD_BB_BOUNCE_L,GBPUSD_BB_BOUNCE_S",
                    ) or ""
                    _ah_exempt = {
                        m.strip().upper()
                        for m in _ah_exempt_raw.split(",")
                        if m.strip()
                    }
                    _ah_is_exempt = mode in _ah_exempt
                    _ah_block = bool(_ah_pause) and not _ah_is_exempt

                    _ah_decision = "BLOCK" if _ah_block else "ALLOW"
                    _ah_pause_flag = "Y" if _ah_pause else "N"
                    logger.info(
                        "[ANTIHEDGE] %s %s %s pause=%s eq_hi=%d eq_lo=%d "
                        "— opposite %s %s open deal=%s",
                        _ah_decision, mode, _ah_dir, _ah_pause_flag,
                        _ah_eq_hi, _ah_eq_lo,
                        _ah_hit["mode"], _ah_hit["direction"], _ah_hit["dealId"],
                    )
                    try:
                        import json as _json_ah
                        from datetime import datetime as _dt_ah, timezone as _tz_ah
                        os.makedirs("logs", exist_ok=True)
                        _ah_rec = {
                            "ts": _dt_ah.now(_tz_ah.utc).isoformat(),
                            "decision": _ah_decision,
                            "strategy": mode,
                            "pair": "GBPUSD",
                            "direction": _ah_dir,
                            "pause": bool(_ah_pause),
                            "eq_high_count": int(_ah_eq_hi),
                            "eq_low_count": int(_ah_eq_lo),
                            "exempt": bool(_ah_is_exempt),
                            "opposite_mode": _ah_hit["mode"],
                            "opposite_direction": _ah_hit["direction"],
                            "opposite_deal_id": str(_ah_hit["dealId"]),
                            "opposite_pos_key": _ah_hit["pos_key"],
                        }
                        with open(
                            "logs/gbpusd_antihedge_gate.jsonl",
                            "a", encoding="utf-8",
                        ) as _fh_ah:
                            _fh_ah.write(_json_ah.dumps(_ah_rec) + "\n")
                    except Exception as _ah_lexc:
                        logger.debug(
                            "[ANTIHEDGE] jsonl write failed: %s", _ah_lexc
                        )

                    if _ah_block:
                        _set_block_info(
                            "GBPUSD_ANTIHEDGE",
                            (
                                f"pause=Y eq_hi={_ah_eq_hi} eq_lo={_ah_eq_lo} "
                                f"opposite={_ah_hit['mode']}/{_ah_hit['direction']} "
                                f"deal={_ah_hit['dealId']}"
                            ),
                        )
                        return None
        except Exception as _ah_exc:
            # Fail-open — the anti-hedge gate's own failures must never
            # block a fire that would otherwise proceed.
            logger.debug("[ANTIHEDGE] gate error (fail-open): %s", _ah_exc)

    pk = _pos_key(epic, mode)

    st = _state_for_epic(pk)

    if st["active"] or st["pending_open"]:
        # BB_REVERSAL pyramids — allow multiple simultaneous positions per epic
        # by suffixing the pos_key. Each position is then managed independently
        # (its own broker-side SL/TP) via its own EPIC_STATE entry.
        if mode == "BB_REVERSAL":
            pk = _pos_key(epic, f"{mode}_{int(time.time()*1000)}")
            st = _state_for_epic(pk)
            logger.info(
                "BB_REVERSAL pyramid entry for %s — using pos_key=%s", epic, pk
            )
        else:
            logger.warning(
                f"⚠️ Trade blocked for {epic} mode={mode} — active={st['active']} pending={st['pending_open']}"
            )
            _set_block_info(
                "DUPLICATE_ACTIVE",
                f"active={st['active']} pending={st['pending_open']} mode={mode}",
            )
            return None

    # Set pending_open immediately to prevent concurrent duplicate submissions.
    # Cleared on success (ACCEPTED), rejection (REJECTED), or timeout.
    st["pending_open"] = True
    st["_pos_key"] = pk

    direction = _safe_str(getattr(decision, "signal", None)).strip().upper()

    if direction not in ("BUY", "SELL"):
        logger.error(f"❌ Invalid trade signal: {direction}")
        st["pending_open"] = False
        _set_block_info("INVALID_DIRECTION", f"signal={direction}")
        return None

    entry_price = _to_float_or_none(getattr(decision, "entry", None))
    if entry_price is None:
        logger.error("❌ Missing or invalid entry price")
        st["pending_open"] = False
        _set_block_info("MISSING_ENTRY", "entry_price is None or non-numeric")
        return None

    raw_sl_pips = getattr(decision, "sl", DEFAULT_SL_PIPS)
    raw_tp_pips = getattr(decision, "tp", DEFAULT_TP_PIPS)

    st["mode"] = getattr(decision, "mode", None)
    st["reason"] = getattr(decision, "reason", None)
    st["requested_entry_price"] = float(entry_price)
    # Persist entry_source so trade_manager can identify V1/V3 sweeps
    _dbg = getattr(decision, "debug", None) or {}
    st["entry_source"] = _dbg.get("entry_source", "")

    pip_size = getattr(decision, "pip_size", None)
    if pip_size is None:
        try:
            dbg = getattr(decision, "debug", None) or {}
            pip_size = dbg.get("pip_size")
        except Exception:
            pip_size = None

    if pip_size is not None:
        try:
            st["pip_size"] = float(pip_size)
        except Exception:
            pass
    else:
        # pip_size not provided — log a warning so we can spot missing propagation
        logger.warning(
            f"⚠️ [{epic}] pip_size not set on decision, using default {DEFAULT_PIP_SIZE}"
        )

    # Validate: pip_size=1.0 is expected for JPY pairs but suspect for others.
    # Flag non-JPY epics where pip_size resolved to 1.0 so we catch mis-propagation.
    _effective_pip = float(st.get("pip_size") or DEFAULT_PIP_SIZE)
    _epic_upper = epic.upper()
    if _effective_pip == 1.0 and "JPY" not in _epic_upper:
        logger.warning(
            f"⚠️ [{epic}] pip_size=1.0 on non-JPY pair — verify this is correct "
            f"(source: {'decision' if pip_size is not None else 'default'})"
        )

    sl_pips, sl_err = _sanitize_distance(
        label="sl",
        raw_value=raw_sl_pips,
        min_pips=float(MIN_SL_PIPS),
        max_pips=float(MAX_REASONABLE_SL_PIPS),
        fallback=float(DEFAULT_SL_PIPS),
    )
    # tp_pips=0.0 OR tp_pips is None semantically means "no broker TP" —
    # the strategy will close at market via its own exit logic (cascade
    # flip, software trailing stop, EOD close, etc.). Pre-2026-05-13 the
    # executor rejected 0/None as `tp_non_positive`; that killed
    # GBPUSD_TREND_S's 09:40 fire today. Negative values are still
    # invalid (caught by _sanitize_distance below).
    _raw_tp_as_float = _to_float_or_none(raw_tp_pips)
    if raw_tp_pips is None or (_raw_tp_as_float is not None and _raw_tp_as_float == 0.0):
        tp_pips, tp_err = None, None
    else:
        tp_pips, tp_err = _sanitize_distance(
            label="tp",
            raw_value=raw_tp_pips,
            min_pips=float(MIN_TP_PIPS),
            max_pips=float(MAX_REASONABLE_TP_PIPS),
            fallback=float(DEFAULT_TP_PIPS),
        )

    try:
        logger.info(
            f"[EXECUTE_TRADE] {epic} raw distances: "
            f"sl={raw_sl_pips} tp={raw_tp_pips} mode={st.get('mode')} reason={st.get('reason')}"
        )
    except Exception:
        pass

    if sl_err or tp_err:
        logger.warning(
            f"⚠️ Trade blocked for {epic} due to invalid distances: "
            f"sl_err={sl_err} tp_err={tp_err} raw_sl={raw_sl_pips} raw_tp={raw_tp_pips}"
        )
        st["close_reason"] = f"blocked_invalid_distances:{sl_err or ''}|{tp_err or ''}"
        try:
            dbg = getattr(decision, "debug", None) or {}
            setattr(
                decision,
                "debug",
                {
                    **dbg,
                    "executor_blocked": True,
                    "executor_block_reason": st["close_reason"],
                    "raw_sl_pips": raw_sl_pips,
                    "raw_tp_pips": raw_tp_pips,
                },
            )
        except Exception:
            pass
        st["pending_open"] = False
        _sync_legacy_trade_state_from(st)
        _set_block_info(
            "INVALID_DISTANCES",
            f"sl_err={sl_err or ''} tp_err={tp_err or ''}",
        )
        return None

    st["sl"] = sl_pips
    st["tp"] = tp_pips
    _sync_legacy_trade_state_from(st)

    # Minimum R:R gate removed 2026-04-30. Each strategy specifies its
    # own SL/TP; degenerate R:R is a strategy-internal sizing concern.

    # SL/TP distance pipeline: pips → IG points → clamped to minimums.
    # Strategy outputs pips; IG API expects points. 1 pip = PPP IG points.
    pair = _pair_from_epic(epic)
    ppp = _ppp_for_pair(pair)

    # Step 1: Convert strategy SL/TP (pips) to IG points.
    # tp_pips=None means "no broker TP" — limit_distance stays None and
    # IG's CREATE_POSITION receives no limit (open_sb_now already passes
    # limit_distance through, and IG treats None as 'no take-profit').
    sl_pts = sl_pips * ppp
    tp_pts = (tp_pips * ppp) if tp_pips is not None else None
    raw_sl_pts = sl_pts
    raw_tp_pts = tp_pts

    # Step 2: Apply per-pair IG API minimum (hard floor from IG)
    ig_min = _IG_MIN_STOP_PTS.get(pair, MIN_STOP_DISTANCE_PIPS)
    sl_pts = max(sl_pts, ig_min)
    if tp_pts is not None:
        tp_pts = max(tp_pts, ig_min)

    # Observability: flag when IG-min inflates TP above strategy intent. The TP
    # announced to Telegram still uses the strategy's requested price, so this
    # log is the authoritative record of what actually sits at the broker.
    if tp_pts is not None and raw_tp_pts is not None and tp_pts > raw_tp_pts + 1e-6:
        logger.info(
            f"[executor] {pair} TP clamped up by broker min: "
            f"raw={raw_tp_pts / ppp:.1f}p → ig_min={ig_min / ppp:.1f}p "
            f"(strategy intent was {tp_pips:.1f}p)"
        )

    # Step 3: Apply global broker floor (covers unknown pairs)
    sl_pts = max(sl_pts, MIN_STOP_DISTANCE_PIPS)
    if tp_pts is not None:
        tp_pts = max(tp_pts, MIN_LIMIT_DISTANCE_PIPS)

    # Step 4: Apply per-pair volatility floor (our minimum, in pips → points)
    pair_min_pips = _PAIR_MIN_SL_PIPS.get(pair)
    if pair_min_pips is not None:
        pair_min_pts = pair_min_pips * ppp
        sl_pts = max(sl_pts, pair_min_pts)

    stop_distance = sl_pts
    limit_distance = tp_pts  # may be None — open_sb_now passes through

    _tp_changed = (
        (limit_distance is None and raw_tp_pts is not None)
        or (limit_distance is not None and raw_tp_pts is None)
        or (limit_distance is not None and raw_tp_pts is not None
            and limit_distance != raw_tp_pts)
    )
    if stop_distance != raw_sl_pts or _tp_changed:
        logger.info(
            f"[executor] {pair} SL: raw={sl_pips:.1f}pips → {raw_sl_pts:.0f}pts → "
            f"IG min={ig_min:.0f}pts → volatility floor="
            f"{pair_min_pips * ppp:.0f}pts → final={stop_distance:.0f}pts "
            f"({stop_distance / ppp:.1f}pips)"
        )

    logger.info(
        f"📤 Submitting order {direction} {epic} "
        f"(sanitized sl={stop_distance} tp={limit_distance})"
    )

    # Use orchestrator-calculated size if provided, otherwise fall back to TRADE_SIZE.
    trade_size = TRADE_SIZE
    decision_size = getattr(decision, "size", None)
    if decision_size is not None:
        try:
            decision_size = float(decision_size)
            if decision_size > 0:
                trade_size = decision_size
        except (ValueError, TypeError):
            pass

    # ── Execution-latency: IG REST request boundary ───────────────────────
    _t_ig_request = _elm.now_epoch_ms()
    try:
        result = open_sb_now(
            direction=direction,
            epic=epic,
            size=trade_size,
            limit_distance=limit_distance,
            stop_distance=stop_distance,
        )
    except Exception:
        st["pending_open"] = False
        _sync_legacy_trade_state_from(st)
        logger.exception(f"❌ Order submission failed for {epic}")
        return None
    # IG REST ack — synchronous response containing dealReference.
    _t_ig_ack = _elm.now_epoch_ms()

    if not isinstance(result, dict):
        st["pending_open"] = False
        _sync_legacy_trade_state_from(st)
        logger.error(f"❌ Unexpected order result type for {epic}: {type(result).__name__}")
        return None

    deal_reference = result.get("dealReference")

    if not deal_reference:
        st["pending_open"] = False
        _sync_legacy_trade_state_from(st)
        logger.error("❌ Missing dealReference from IG")
        return None

    try:
        session_obj = get_ig_session()
        if not isinstance(session_obj, (tuple, list)) or len(session_obj) < 1:
            raise ValueError(f"unexpected get_ig_session() return shape: {type(session_obj).__name__}")
        ig = session_obj[0]
        if ig is None:
            raise ValueError("get_ig_session() returned empty IG client")
    except Exception as e:
        st["pending_open"] = False
        st["close_reason"] = f"session_acquire_failed:{type(e).__name__}"
        _sync_legacy_trade_state_from(st)
        logger.error(f"❌ Session acquisition failed for {epic}: {type(e).__name__}: {e}")
        return None

    try:
        for _ in range(CONFIRM_RETRIES):
            try:
                conf = ig.fetch_deal_by_deal_reference(deal_reference)
            except Exception as e:
                logger.warning(f"[OPEN_CONFIRM] fetch_deal_by_deal_reference failed for {epic}: {type(e).__name__}: {e}")
                time.sleep(CONFIRM_SLEEP_SECS)
                continue

            if not isinstance(conf, dict):
                logger.warning(f"[OPEN_CONFIRM] non-dict confirmation for {epic}: {type(conf).__name__}")
                time.sleep(CONFIRM_SLEEP_SECS)
                continue

            status = conf.get("dealStatus")

            if status == "ACCEPTED":
                # Execution-latency: deal confirmation (final fill price
                # and dealId returned from /confirms/{dealReference}).
                _t_ig_confirm = _elm.now_epoch_ms()
                confirmed_level = _to_float_or_none(conf.get("level"))
                if confirmed_level is None:
                    confirmed_level = _to_float_or_none(st.get("requested_entry_price"))

                st["active"] = True
                st["pending_open"] = False
                st["dealReference"] = deal_reference
                st["dealId"] = conf.get("dealId")
                st["deal_id"] = conf.get("dealId")
                st["entry_price"] = confirmed_level
                st["direction"] = direction
                st["size"] = trade_size
                # Snapshot original_size so post-scale state can distinguish
                # "ran from size N" vs "ran from size N/2 after scale-out".
                # Used by _on_trade_close to compute total_pnl_pips correctly.
                st["original_size"] = trade_size
                st["open_time"] = time.time()
                _stamp_profile_at_fire(st, epic)

                # Persist fire-path latency timestamps onto EPIC_STATE so
                # autobot's signal_logger.log_open call site can read them
                # and merge into the open record. Read LS_ASYNC_DISPATCH at
                # fire time (not module load).
                _ls_flag = _elm.ls_async_dispatch_flag()
                _fire_latency = _elm.build_fire_latency_record(
                    t_decision=_t_decision,
                    t_dispatch=_t_dispatch,
                    t_ig_request=_t_ig_request,
                    t_ig_ack=_t_ig_ack,
                    t_ig_confirm=_t_ig_confirm,
                    ls_async_dispatch=_ls_flag,
                )
                st["fire_latency"] = _fire_latency
                _sync_legacy_trade_state_from(st)

                # Emit single-line FIRE-LATENCY summary.
                _elm.log_fire_latency(
                    strategy=str(st.get("mode") or mode or ""),
                    pair=_pair_from_epic(epic),
                    deltas=_fire_latency,
                    ls_async_dispatch=_ls_flag,
                )

                logger.info(f"✅ Trade OPENED {epic} {direction}")

                # Persist strategy-specific metadata into EPIC_STATE so a
                # mid-session restart can reconstruct per-leg state. For
                # BB_REVERSAL v4 this carries slot / tp_tier / window /
                # bbr_proposal_id so the strategy's startup reconstruction
                # knows exactly which slot each broker position occupies.
                try:
                    _dbg = getattr(decision, "debug", None) or {}
                    for _k in ("slot", "tp_tier", "window", "bbr_proposal_id"):
                        if _k in _dbg:
                            st[_k] = _dbg[_k]
                except Exception:
                    pass

                # Strategy open-callback (e.g. BB_REVERSAL PendingProposal →
                # committed leg promotion). Fires synchronously before any
                # slower bookkeeping so the strategy's state converges fast.
                _fire_open_callbacks(pk, decision)

                # Store briefing invalidation level for this trade
                try:
                    import morning_briefing
                    from briefing_execution import _parse_invalidation
                    _pair = _pair_from_epic(epic)
                    _brief = morning_briefing.get_briefing(_pair)
                    if _brief:
                        _plans = _brief.get("trading_plans") or []
                        _plan0 = _plans[0] if _plans else {}
                        _inv_text = _plan0.get("invalidation") or ""
                        _inv_price, _inv_dir = _parse_invalidation(_inv_text)
                        if _inv_price is not None and _inv_dir is not None:
                            st["invalidation_price"] = _inv_price
                            st["invalidation_direction"] = _inv_dir
                            logger.info(
                                "[INVALIDATION] %s stored: close %s %.1f (from: %s)",
                                epic, _inv_dir, _inv_price, _inv_text[:80],
                            )
                except Exception as _inv_err:
                    logger.debug("[INVALIDATION] failed to read briefing for %s: %s", epic, _inv_err)

                try:
                    _dbg = getattr(decision, "debug", None) or {}
                    _tg_dispatch = _elm.now_epoch_ms()
                    _pair = _pair_from_epic(epic)
                    _regime_snap = _regime_snapshot_for_alert(_pair)
                    _alert_dbg = None
                    if _dbg.get("tp_plan"):
                        _alert_dbg = _enrich_alert_debug(
                            _dbg, st["entry_price"], sl_pips, direction, _pair,
                        )
                    send_trade_open_alert(
                        epic,
                        direction,
                        TRADE_SIZE,
                        st["entry_price"],
                        sl_pips,
                        tp_pips,
                        mode=st.get("mode", "") or "",
                        debug=_alert_dbg,
                        regime=_regime_snap,
                    )
                    _tg_complete = _elm.now_epoch_ms()
                    _elm.log_tg_latency(
                        event_kind="trade_open",
                        pair=_pair_from_epic(epic),
                        t_event=_t_dispatch,
                        t_dispatch=_tg_dispatch,
                        t_complete=_tg_complete,
                    )
                except Exception:
                    logger.exception(f"❌ send_trade_open_alert failed for {epic}")

                return st

            if status == "REJECTED":
                st["pending_open"] = False
                st["close_reason"] = "trade_rejected"
                _sync_legacy_trade_state_from(st)
                detail = _extract_rejection_detail(conf)
                logger.error(f"❌ Trade REJECTED for {epic} {detail}".strip())
                return None

            time.sleep(CONFIRM_SLEEP_SECS)

    except Exception as e:
        st["pending_open"] = False
        st["close_reason"] = f"confirmation_flow_exception:{type(e).__name__}"
        _sync_legacy_trade_state_from(st)
        logger.error(f"❌ Unexpected confirmation-flow error for {epic}: {type(e).__name__}: {e}")
        return None

    # Confirmation timed out — but the order may have been placed on IG's side.
    # Query open positions to check before assuming failure (Fix #14).
    logger.warning(
        f"⚠️ [{epic}] Confirmation timeout after {CONFIRM_RETRIES} retries — "
        f"checking IG open positions for dealReference={deal_reference}"
    )
    try:
        positions = get_open_positions()
        if positions:
            for p in positions:
                _pos = (p.get("position") or {})
                _mkt = (p.get("market") or {})
                _p_epic = str(_mkt.get("epic") or "").strip()
                _p_deal_id = str(_pos.get("dealId") or "").strip()
                _p_deal_ref = str(_pos.get("dealReference") or "").strip()
                if _p_epic == epic or _p_deal_ref == deal_reference:
                    # The order DID go through — reconcile it
                    _t_ig_confirm = _elm.now_epoch_ms()
                    confirmed_level = _to_float_or_none(
                        _pos.get("openLevel") or _pos.get("level")
                    )
                    if confirmed_level is None:
                        confirmed_level = _to_float_or_none(st.get("requested_entry_price"))

                    st["active"] = True
                    st["pending_open"] = False
                    st["dealReference"] = deal_reference
                    st["dealId"] = _p_deal_id or None
                    st["deal_id"] = _p_deal_id or None
                    st["entry_price"] = confirmed_level
                    st["direction"] = direction
                    st["size"] = trade_size
                    st["open_time"] = time.time()
                    _stamp_profile_at_fire(st, epic)
                    st["close_reason"] = None
                    _ls_flag = _elm.ls_async_dispatch_flag()
                    _fire_latency = _elm.build_fire_latency_record(
                        t_decision=_t_decision,
                        t_dispatch=_t_dispatch,
                        t_ig_request=_t_ig_request,
                        t_ig_ack=_t_ig_ack,
                        t_ig_confirm=_t_ig_confirm,
                        ls_async_dispatch=_ls_flag,
                    )
                    st["fire_latency"] = _fire_latency
                    _sync_legacy_trade_state_from(st)
                    _elm.log_fire_latency(
                        strategy=str(st.get("mode") or mode or ""),
                        pair=_pair_from_epic(epic),
                        deltas=_fire_latency,
                        ls_async_dispatch=_ls_flag,
                    )

                    logger.warning(
                        f"🔄 [{epic}] Post-timeout reconciliation: order WAS filled! "
                        f"dealId={_p_deal_id} entry={confirmed_level} — recovered."
                    )

                    # Strategy open-callback — same contract as the ACCEPTED
                    # branch above. The broker confirmed the fill via
                    # get_open_positions, so this is a real open and
                    # strategies must converge their state accordingly.
                    _fire_open_callbacks(pk, decision)

                    try:
                        _dbg = getattr(decision, "debug", None) or {}
                        _tg_dispatch = _elm.now_epoch_ms()
                        _pair = _pair_from_epic(epic)
                        _regime_snap = _regime_snapshot_for_alert(_pair)
                        _alert_dbg = None
                        if _dbg.get("tp_plan"):
                            _alert_dbg = _enrich_alert_debug(
                                _dbg, st["entry_price"], sl_pips, direction, _pair,
                            )
                        send_trade_open_alert(
                            epic, direction, trade_size, st["entry_price"],
                            sl_pips, tp_pips,
                            mode=st.get("mode", "") or "",
                            debug=_alert_dbg,
                            regime=_regime_snap,
                        )
                        _tg_complete = _elm.now_epoch_ms()
                        _elm.log_tg_latency(
                            event_kind="trade_open",
                            pair=_pair_from_epic(epic),
                            t_event=_t_dispatch,
                            t_dispatch=_tg_dispatch,
                            t_complete=_tg_complete,
                        )
                    except Exception:
                        logger.exception(f"❌ send_trade_open_alert failed for {epic} (post-timeout)")

                    return st
    except Exception as _recon_exc:
        logger.warning(f"⚠️ [{epic}] Post-timeout position check failed: {_recon_exc}")

    # Retry position check up to 3 times with a short delay
    for _retry in range(2):
        try:
            time.sleep(1.0)
            positions = get_open_positions()
            if positions:
                for p in positions:
                    _pos = (p.get("position") or {})
                    _mkt = (p.get("market") or {})
                    _p_epic = str(_mkt.get("epic") or "").strip()
                    if _p_epic == epic:
                        _t_ig_confirm = _elm.now_epoch_ms()
                        confirmed_level = _to_float_or_none(
                            _pos.get("openLevel") or _pos.get("level")
                        )
                        _p_deal_id = str(_pos.get("dealId") or "").strip()
                        st["active"] = True
                        st["pending_open"] = False
                        st["dealId"] = _p_deal_id or None
                        st["deal_id"] = _p_deal_id or None
                        st["entry_price"] = confirmed_level or st.get("requested_entry_price")
                        st["direction"] = direction
                        st["size"] = trade_size
                        st["open_time"] = time.time()
                        _stamp_profile_at_fire(st, epic)
                        st["close_reason"] = None
                        _ls_flag = _elm.ls_async_dispatch_flag()
                        _fire_latency = _elm.build_fire_latency_record(
                            t_decision=_t_decision,
                            t_dispatch=_t_dispatch,
                            t_ig_request=_t_ig_request,
                            t_ig_ack=_t_ig_ack,
                            t_ig_confirm=_t_ig_confirm,
                            ls_async_dispatch=_ls_flag,
                        )
                        st["fire_latency"] = _fire_latency
                        _sync_legacy_trade_state_from(st)
                        _elm.log_fire_latency(
                            strategy=str(st.get("mode") or mode or ""),
                            pair=_pair_from_epic(epic),
                            deltas=_fire_latency,
                            ls_async_dispatch=_ls_flag,
                        )
                        logger.warning(
                            f"🔄 [{epic}] Post-timeout retry {_retry+2}: order WAS filled! "
                            f"dealId={_p_deal_id} entry={confirmed_level}"
                        )
                        # Strategy open-callback — same contract as the
                        # ACCEPTED branch above. The retry loop matched an
                        # IG-side open position, so this is a real open.
                        _fire_open_callbacks(pk, decision)
                        return st
        except Exception:
            pass

    st["pending_open"] = False
    st["close_reason"] = "trade_confirmation_timeout"
    _sync_legacy_trade_state_from(st)

    logger.critical(
        f"❌ CRITICAL: Trade confirmation timeout for {epic} "
        f"dealReference={deal_reference} — no matching position found after 3 checks. "
        f"MANUAL CHECK REQUIRED on IG platform."
    )
    try:
        send_trade_close_alert(
            epic, direction, 0, 0, 0, 0, reason="CONFIRMATION_TIMEOUT_ORPHAN_CHECK",
        )
    except Exception:
        pass

    return None


# ============================================================
# LOW LEVEL STATE UPDATE
# ============================================================

def update_trade_state(
    epic: str,
    mid_price: float,
    bid: Any = None,
    ask: Any = None,
    upper_band: Any = None,
    lower_band: Any = None,
):
    st = _state_for_epic(epic)

    try:
        st["last_mid"] = float(mid_price)
    except Exception:
        pass

    _sync_legacy_trade_state_from(st)
    return st


def apply_trailing_stop(
    epic: str,
    mid_price: float,
    bid: Any = None,
    ask: Any = None,
):
    st = _state_for_epic(epic)

    try:
        st["last_mid"] = float(mid_price)
    except Exception:
        pass

    _sync_legacy_trade_state_from(st)
    return None


# ============================================================
# CLOSE TRADE
# ============================================================

def close_trade(pos_key: str):
    pos_key = str(pos_key).strip()
    st = _state_for_epic(pos_key)
    epic = _epic_from_pos_key(pos_key) if "|" in pos_key else pos_key

    # ── Per-position close-in-flight guard (2026-06-12) ───────────────────
    # Atomic check-and-set under EPIC_STATE_LOCK so concurrent callers
    # (LS-tick exit path + external-close sweep daemon, etc.) cannot both
    # pass the active check and race their callback chains (Telegram alert,
    # sentinel push, EXIT-LATENCY log). The body executes OUTSIDE the lock
    # — only the CAS is locked, so the ~100ms–1s IG REST round-trip doesn't
    # block other state operations.
    #
    # Cleanup of _closing_in_flight:
    #   - Success path: _reset_trade_state at the end of the body REPLACES
    #     EPIC_STATE[pos_key] with a fresh dict from _STATE_TEMPLATE
    #     (trade_executor.py:445), which has no _closing_in_flight key.
    #     A subsequent close_trade(pos_key) reads the new dict via
    #     _state_for_epic and sees the flag absent (= falsy). Implicit
    #     clear — no explicit reset on the success path.
    #   - Early returns inside the body (broker-still-open after a failed
    #     close_by_deal_id, and close-verify-still-open) clear the flag
    #     explicitly so a retry on the same dict can enter.
    #   - Any uncaught exception clears the flag via the BaseException
    #     handler at the bottom and re-raises.
    with EPIC_STATE_LOCK:
        if not st["active"] or st.get("_closing_in_flight"):
            return None
        st["_closing_in_flight"] = True

    try:
        # ── Execution-latency: exit-trigger boundary ──────────────────────────
        # close_trade() is called by callers that have already detected the
        # exit condition (SL/TP poll, briefing close, manual close).  Treat
        # function entry as the trigger boundary.  Callers that detect the
        # condition strictly earlier can override by setting
        # st["t_exit_trigger_epoch_ms"] before calling close_trade.
        _t_exit_trigger = st.get("t_exit_trigger_epoch_ms") or _elm.now_epoch_ms()

        deal_id = _safe_str(st.get("deal_id") or st.get("dealId") or "")

        # Close by deal_id to target the specific position (not all on this epic).
        close_resp: Any = None
        # Exit-dispatch boundary captured immediately before the IG REST call.
        _t_exit_dispatch = _elm.now_epoch_ms()
        broker_side_close = False  # set True when close_by_deal_id fails because
                                    # the position is already closed at broker
                                    # (SL hit, manual IG web close, liquidation).
                                    # We still fire callbacks so strategy state
                                    # converges (Tier C fix, 2026-04-23).
        try:
            if deal_id:
                close_resp = close_by_deal_id(deal_id)
            else:
                # Fallback: close by epic (legacy / no deal_id)
                close_resp = close_sb_now(epic)
        except Exception as _close_exc:
            # If the broker already closed this position, continue to fire
            # callbacks rather than dropping the close event. Strategy state
            # (e.g. bb_reversal.state.legs) needs to converge on reality even
            # when the explicit REST close failed.
            try:
                _already_closed = not _position_still_open(epic=epic, deal_id=deal_id or None)
            except Exception:
                _already_closed = False
            if not _already_closed:
                logger.exception(f"❌ Close trade failed {epic} (pos_key={pos_key})")
                # Position is still alive at the broker — clear the in-flight
                # flag so a retry can enter.
                with EPIC_STATE_LOCK:
                    st["_closing_in_flight"] = False
                return None
            logger.info(
                "[%s] close_by_deal_id failed but broker confirms position is closed "
                "(pos_key=%s deal_id=%s) — firing callbacks with upstream reason "
                "(or BROKER_SIDE_CLOSE if none). Exception was: %s: %s",
                epic, pos_key, deal_id or "-",
                type(_close_exc).__name__, _close_exc,
            )
            broker_side_close = True
            close_resp = None

        still_open = True
        for _ in range(CLOSE_VERIFY_RETRIES):
            still_open = _position_still_open(epic=epic, deal_id=deal_id or None)
            if not still_open:
                break
            time.sleep(CLOSE_VERIFY_SLEEP_SECS)

        if still_open:
            logger.error(
                f"❌ Close verification failed for {epic} (pos_key={pos_key}) — position still appears open; "
                f"local state preserved"
            )
            _sync_legacy_trade_state_from(st)
            # Position still open — clear the in-flight flag so a retry can enter.
            with EPIC_STATE_LOCK:
                st["_closing_in_flight"] = False
            return None

        # ── Execution-latency: exit confirmation boundary ─────────────────────
        # The position is no longer open at IG — record the confirm timestamp
        # so the latency record can be persisted alongside the close patch.
        _t_exit_confirm = _elm.now_epoch_ms()
        _ls_flag = _elm.ls_async_dispatch_flag()
        _exit_latency = _elm.build_exit_latency_record(
            t_exit_trigger=_t_exit_trigger,
            t_exit_dispatch=_t_exit_dispatch,
            t_exit_confirm=_t_exit_confirm,
            ls_async_dispatch=_ls_flag,
        )
        st["exit_latency"] = _exit_latency
        _elm.log_exit_latency(
            strategy=str(st.get("mode") or ""),
            pair=_pair_from_epic(epic),
            deltas=_exit_latency,
            ls_async_dispatch=_ls_flag,
        )

        # Fetch the confirmed IG fill level and overwrite the pre-execution hint
        # price that callers stored in st["exit_price"].  The hint is the market
        # price at the moment the close condition was *detected*; the actual fill
        # can differ once the market order executes on IG's side.  Falls back
        # silently to the hint if the confirmation cannot be obtained.
        try:
            close_ref = None
            if isinstance(close_resp, dict):
                close_ref = close_resp.get("dealReference")
            if close_ref:
                session_obj = get_ig_session()
                ig = session_obj[0] if isinstance(session_obj, (tuple, list)) and session_obj else None
                if ig is not None:
                    for _ in range(CLOSE_CONFIRM_RETRIES):
                        try:
                            conf = ig.fetch_deal_by_deal_reference(close_ref)
                            if isinstance(conf, dict) and conf.get("dealStatus") == "ACCEPTED":
                                fill_level = _to_float_or_none(conf.get("level"))
                                if fill_level is not None:
                                    hint = st.get("exit_price")
                                    st["exit_price"] = fill_level
                                    logger.info(
                                        f"[{epic}] close confirmation: fill_level={fill_level} "
                                        f"(hint was {hint})"
                                    )
                                break
                        except Exception:
                            pass
                        time.sleep(CLOSE_CONFIRM_SLEEP_SECS)
        except Exception:
            logger.exception(f"[{epic}] close confirmation fetch failed; using hint price for PnL")

        try:
            entry_p = _to_float_or_none(st.get("entry_price"))
            exit_p = _to_float_or_none(st.get("exit_price"))
            if exit_p is None:
                exit_p = _to_float_or_none(st.get("last_mid"))

            direction_s = str(st.get("direction") or "")
            pip_sz = float(st.get("pip_size") or 1.0)
            pnl_pips = None

            try:
                if entry_p is not None and exit_p is not None and pip_sz > 0:
                    if direction_s == "BUY":
                        pnl_pips = (float(exit_p) - float(entry_p)) / pip_sz
                    elif direction_s == "SELL":
                        pnl_pips = (float(entry_p) - float(exit_p)) / pip_sz
            except Exception:
                pass

            # Tier C: if close_by_deal_id failed because the broker already
            # closed the position (SL hit, manual close, liquidation), prefer
            # any reason the upstream caller set on st (PRE_NEWS_CLOSE,
            # SYNC_NO_POSITION, etc.); else label BROKER_SIDE_CLOSE.
            _default_reason = "BROKER_SIDE_CLOSE" if broker_side_close else "closed_verified"
            _close_reason_str = _close_reason_or_default(st, _default_reason)
            _tg_dispatch = _elm.now_epoch_ms()
            send_trade_close_alert(
                epic,
                direction_s,
                entry_p,
                exit_p,
                pnl_pips,
                None,
                _close_reason_str,
                mode=st.get("mode", "") or "",
            )
            _tg_complete = _elm.now_epoch_ms()
            _elm.log_tg_latency(
                event_kind="trade_close",
                pair=_pair_from_epic(epic),
                t_event=_t_exit_trigger,
                t_dispatch=_tg_dispatch,
                t_complete=_tg_complete,
            )
            # Tier B: forward deal_id to strategy close-callbacks so they can
            # disambiguate legs that share an un-suffixed pos_key. Fall back
            # to the legacy signature for any callback that has not yet been
            # updated to accept deal_id.
            _cb_deal_id = deal_id or None
            for _cb in _CLOSE_CALLBACKS:
                try:
                    _cb(pos_key, exit_p, pnl_pips, _close_reason_str, deal_id=_cb_deal_id)
                except TypeError:
                    try:
                        _cb(pos_key, exit_p, pnl_pips, _close_reason_str)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            logger.exception(f"❌ send_trade_close_alert failed for {epic}")

        _reset_trade_state(pos_key)

        logger.info(f"🔒 Trade closed for {epic} (pos_key={pos_key})")
        return True
    except BaseException:
        # Body raised before reaching _reset_trade_state. Clear the in-flight
        # flag so a retry on the same pos_key (whose EPIC_STATE entry is
        # still the original dict) can enter, then re-raise.
        with EPIC_STATE_LOCK:
            st["_closing_in_flight"] = False
        raise


def _today_variant(epic: str) -> str:
    """Normalise an IG epic to its TODAY.IP variant (CFD.IP → TODAY.IP).

    Mirrors native_5m_source._today_epic / streamer_ls._split_today_cfd so
    reconcile compares apples-to-apples regardless of which variant the
    .env stores in EPICS_JSON. The Lightstreamer per-tick callback emits
    the TODAY variant (LS subscription tries TODAY first via
    _subscribe_with_fallback), so EPIC_STATE keys MUST be TODAY for the
    watcher (has_active_trade / monitor_positions) to find restored rows.
    Idempotent; epics with fewer than 4 dot-parts pass through unchanged.
    """
    parts = str(epic).split(".")
    if len(parts) < 4:
        return str(epic)
    return ".".join(parts[:3]) + ".TODAY.IP"


def reconcile_open_positions(
    epic_map: Dict[str, str],
    mode_map: Optional[Dict[str, str]] = None,
) -> Tuple[int, int]:
    """
    Startup reconciliation: poll IG for open positions and reconstruct local
    trade state for any positions not already tracked in EPIC_STATE.

    Call this once during bot initialisation, before the tick loop starts,
    so that trade_manager can immediately protect positions that survived a
    bot restart (sweep trail, profit protection, etc.).

    Args:
        epic_map:  symbol → epic (CFD.IP or TODAY.IP — both normalise to
                   TODAY for the membership check; see _today_variant).
        mode_map:  optional deal_id → mode OR epic → mode hint recovered
                   from sweep journal.  Checked by deal_id first, then epic.

    Returns:
        (restored, seen): restored = number of positions reconstructed into
        EPIC_STATE; seen = number of IG positions returned for any of our
        epics (post-normalisation). seen distinguishes "no IG positions"
        from "IG had positions but we skipped them all" so the caller can
        emit an honest "No orphaned positions" only when seen == 0.
    """
    positions = get_open_positions()
    if not positions:
        logger.info("[RECONCILE] No open IG positions found.")
        return 0, 0

    # Compare on the TODAY variant on BOTH sides. EPICS_JSON commonly holds
    # CFD.IP (REST preload requires CFD on demo) while IG /positions returns
    # TODAY.IP — without this normalisation every inherited position was
    # silently dropped by a bare `continue`, leaving the open trade without
    # a watcher.
    known_epics: set = {_today_variant(e) for e in epic_map.values()}
    seen = 0
    # Build set of deal_ids already tracked in EPIC_STATE
    tracked_deal_ids: set = set()
    for _pk, _st in EPIC_STATE.items():
        did = _st.get("dealId") or _st.get("deal_id")
        if did and _st.get("active"):
            tracked_deal_ids.add(str(did))
    count = 0

    # ──────────────────────────────────────────────────────────────
    # Own-deals-only gate (ported from droplet-144, 2026-06-12).
    # The IG demo account is shared across droplets. Without this gate
    # a same-pair open from a sibling droplet would be adopted with
    # mode=DEFAULT (the existing :1893+ fallback) and immediately
    # subject to this host's trade_manager — meaning we could close,
    # trail, or scale-out a position the sibling owns.
    #
    # When ON (default), require dealId OR dealReference to match a
    # signal_log row originated by THIS host. Foreign deals get a WARN
    # and a row in foreign_deals_observed.jsonl; they NEVER enter
    # EPIC_STATE. Kill-switch=0 restores the pre-gate adopt-everything
    # behaviour for a forced fleet-wide rollback (NAME parity with 144).
    #
    # File-missing / corrupted signal_log: treated as "everything
    # foreign" with a loud one-shot WARN. Accepted trade-off — the
    # alternative (fail-open and adopt anyway) is the exact failure
    # mode this gate was added to prevent.
    # ──────────────────────────────────────────────────────────────
    _own_deals_only = (
        os.getenv("RECONCILE_OWN_DEALS_ONLY", "1") or "1"
    ).strip() == "1"
    _signal_log_readable = False
    if _own_deals_only:
        try:
            _signal_log_readable = os.path.isfile(_SIGNAL_LOG_PATH) and (
                os.path.getsize(_SIGNAL_LOG_PATH) > 0
            )
        except Exception:
            _signal_log_readable = False
        if not _signal_log_readable:
            logger.warning(
                "[RECONCILE] ⚠️ RECONCILE_OWN_DEALS_ONLY=1 but signal_log "
                "is missing or empty at %s — ALL IG positions will be "
                "treated as foreign and skipped. Set RECONCILE_OWN_DEALS_ONLY=0 "
                "if this host should adopt unverified deals.",
                _SIGNAL_LOG_PATH,
            )

    for p in positions:
        if not isinstance(p, dict):
            continue

        market = p.get("market") or {}
        pos = p.get("position") or {}

        epic_raw = str(market.get("epic") or "").strip()
        epic = _today_variant(epic_raw) if epic_raw else ""
        if not epic or epic not in known_epics:
            if epic_raw:
                logger.debug(
                    "[RECONCILE] skip epic=%s (normalised=%s) — not in "
                    "epic_map TODAY-set %s",
                    epic_raw, epic, sorted(known_epics),
                )
            continue
        seen += 1

        deal_id = str(pos.get("dealId") or "").strip() or None

        # Skip if this deal_id is already tracked
        if deal_id and deal_id in tracked_deal_ids:
            logger.info(f"[RECONCILE] {epic} dealId={deal_id} already tracked; skipping.")
            continue

        direction = str(pos.get("direction") or "").upper()
        if direction not in ("BUY", "SELL"):
            logger.warning(f"[RECONCILE] {epic} unrecognised direction={direction!r}; skipping.")
            continue

        deal_reference = str(pos.get("dealReference") or "").strip() or None

        # ── Own-deals-only gate (per-deal check) ──────────────────
        # Skip foreign deals before any state mutation. Origin = a
        # signal_log row keyed on either dealId or dealReference,
        # whichever the dispatcher persisted at trade open. File-
        # missing/empty was handled by the one-shot WARN above;
        # here we just treat every deal as foreign in that case.
        if _own_deals_only:
            _own_by_deal = bool(
                _signal_log_readable
                and deal_id
                and lookup_signal_log_by_deal_id(deal_id) is not None
            )
            _own_by_ref = bool(
                _signal_log_readable
                and not _own_by_deal
                and deal_reference
                and lookup_signal_log_by_deal_reference(deal_reference) is not None
            )
            if not (_own_by_deal or _own_by_ref):
                size_for_log = _to_float_or_none(
                    pos.get("dealSize") or pos.get("size") or pos.get("contractSize")
                )
                logger.warning(
                    "[RECONCILE] %s dealId=%s dealRef=%s direction=%s "
                    "size=%s — FOREIGN (no signal_log origin on this host); "
                    "leaving untouched. Set RECONCILE_OWN_DEALS_ONLY=0 to "
                    "restore the prior adopt-everything behaviour.",
                    epic_raw or epic, deal_id, deal_reference, direction, size_for_log,
                )
                _log_foreign_deal({
                    "epic": epic_raw or epic,
                    "dealId": deal_id,
                    "dealReference": deal_reference,
                    "direction": direction,
                    "size": size_for_log,
                    "signal_log_readable": _signal_log_readable,
                    "host": os.getenv("HOSTNAME") or os.uname().nodename,
                })
                continue

        entry_price = _to_float_or_none(pos.get("openLevel") or pos.get("level"))
        size = _to_float_or_none(pos.get("dealSize") or pos.get("size") or pos.get("contractSize")) or TRADE_SIZE

        # Recover open_time from IG's UTC timestamp field.
        open_time: float = time.time()
        for date_field in ("createdDateUTC", "createdDate"):
            raw_dt = pos.get(date_field)
            if not raw_dt:
                continue
            s = str(raw_dt).strip()
            parsed = False
            try:
                from datetime import datetime as _dt, timezone as _tz
                open_time = _dt.fromisoformat(s).replace(tzinfo=_tz.utc).timestamp()
                parsed = True
            except Exception:
                pass
            if not parsed:
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    normalised = s.replace("/", "-").rsplit(":", 1)[0]
                    open_time = _dt.strptime(normalised, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_tz.utc).timestamp()
                    parsed = True
                except Exception:
                    pass
            if parsed:
                break

        sl_pips: Optional[float] = _to_float_or_none(
            pos.get("stopDistance") or pos.get("trailingStopDistance")
        )
        tp_pips: Optional[float] = _to_float_or_none(pos.get("limitDistance"))

        if sl_pips is None and entry_price is not None:
            stop_level = _to_float_or_none(pos.get("stopLevel"))
            if stop_level is not None:
                sl_pips = abs(float(stop_level) - float(entry_price))

        if tp_pips is None and entry_price is not None:
            limit_level = _to_float_or_none(pos.get("limitLevel"))
            if limit_level is not None:
                tp_pips = abs(float(limit_level) - float(entry_price))

        # Resolve mode. Priority:
        #   1. signal_log match by deal_id  (strongest — broker's unique id)
        #   2. mode_map[deal_id]            (sweep journal specific dealId → mode)
        #   3. signal_log match by epic + direction + entry_price (fuzzy)
        #   4. mode_map[epic]               (sweep journal epic-level fallback)
        # If all four miss, fall through to DEFAULT and emit a WARN with the
        # full deal metadata so we can debug the missing strategy tag later.
        # The DEFAULT path subjects the position to MPP / BRIEF_INVALIDATED
        # exits the originating strategy may have been exempt from — see the
        # 2026-04-28 BB_REVERSAL pyramid leg that lost its tag through a
        # mid-session restart and got clipped at +13.7p when MPP fired.
        mode = None
        signal_log_id: Optional[str] = None

        sl_rec_by_deal = lookup_signal_log_by_deal_id(deal_id) if deal_id else None
        if sl_rec_by_deal is not None:
            sl_strategy = str(sl_rec_by_deal.get("strategy") or "").strip() or None
            sl_id = str(sl_rec_by_deal.get("id") or "").strip() or None
            if sl_id:
                signal_log_id = sl_id
            if sl_strategy:
                mode = sl_strategy
                logger.info(
                    f"[RECONCILE] restored mode={mode} for deal={deal_id} "
                    f"(was about to be tagged DEFAULT)"
                )

        if not mode and mode_map and deal_id:
            mode = mode_map.get(deal_id)
            if mode:
                logger.info(
                    f"[RECONCILE] restored mode={mode} for deal={deal_id} "
                    f"from sweep journal (was about to be tagged DEFAULT)"
                )

        if not mode:
            sl_rec = lookup_signal_log_open(epic, direction, entry_price)
            if sl_rec is not None:
                sl_strategy = str(sl_rec.get("strategy") or "").strip() or None
                sl_id = str(sl_rec.get("id") or "").strip() or None
                if sl_id and not signal_log_id:
                    signal_log_id = sl_id
                if sl_strategy:
                    mode = sl_strategy
                    logger.info(
                        f"[RECONCILE] {epic} mode={mode} recovered from signal_log "
                        f"by entry-price match (id={signal_log_id}, "
                        f"direction={direction}, entry={entry_price})"
                    )

        if not mode and mode_map:
            mode = mode_map.get(epic)
            if mode:
                logger.info(
                    f"[RECONCILE] {epic} mode={mode} recovered from sweep journal "
                    f"(epic-level fallback)"
                )

        if not mode:
            logger.warning(
                f"[RECONCILE] ⚠️ {epic} {direction} could not recover strategy "
                f"tag — falling through to DEFAULT. "
                f"deal_id={deal_id} dealRef={deal_reference} entry={entry_price} "
                f"sl_pips={sl_pips} tp_pips={tp_pips}. "
                f"Position will be subject to DEFAULT trade_manager exits "
                f"(MPP / BRIEF_INVALIDATED) the originating strategy may have "
                f"been exempt from."
            )

        pk = _pos_key(epic, mode or "DEFAULT")

        # If this pos_key already exists and is active, append a suffix
        if pk in EPIC_STATE and EPIC_STATE[pk].get("active"):
            pk = _pos_key(epic, f"{mode or 'DEFAULT'}_{deal_id or count}")

        st = _state_for_epic(pk)
        st.update({
            "active": True,
            "pending_open": False,
            "epic": epic,
            "direction": direction,
            "entry_price": entry_price,
            "requested_entry_price": entry_price,
            "dealId": deal_id,
            "deal_id": deal_id,
            "dealReference": deal_reference,
            "size": size,
            "open_time": open_time,
            "mode": mode,
            "pip_size": DEFAULT_PIP_SIZE,
            "sl": sl_pips,
            "tp": tp_pips,
            "close_reason": None,
            "exit_price": None,
            "_pos_key": pk,
            "signal_log_id": signal_log_id,
        })
        _sync_legacy_trade_state_from(st)
        if deal_id:
            tracked_deal_ids.add(deal_id)

        RECONCILE_DEFAULT_SL_PIPS = 20.0
        if sl_pips is None:
            sl_pips = RECONCILE_DEFAULT_SL_PIPS
            st["sl"] = sl_pips
            _sync_legacy_trade_state_from(st)
            logger.critical(
                f"🚨 [RECONCILE] {epic} {direction} has NO stop-loss from IG — "
                f"applied default SL of {RECONCILE_DEFAULT_SL_PIPS} pips. "
                f"entry={entry_price} dealId={deal_id}. "
                f"VERIFY this position has broker-side protection!"
            )

        logger.info(
            f"[RECONCILE] ✅ Restored {epic} {direction} entry={entry_price} "
            f"dealId={deal_id} sl_pips={sl_pips} tp_pips={tp_pips} "
            f"mode={mode} pos_key={pk} open_time={open_time:.0f}"
        )
        count += 1

    # Clear stale pending_open flags for pos_keys with no matching IG position.
    ig_deal_ids = set()
    for p in positions:
        did = ((p.get("position") or {}).get("dealId") or "")
        if did:
            ig_deal_ids.add(str(did))
    for pk, st in EPIC_STATE.items():
        if st.get("pending_open") and not st.get("active"):
            st_deal = st.get("dealId") or st.get("deal_id") or ""
            epic_of_pk = _epic_from_pos_key(pk) if "|" in pk else pk
            if st_deal and str(st_deal) not in ig_deal_ids:
                st["pending_open"] = False
                _sync_legacy_trade_state_from(st)
                pair = _pair_from_epic(epic_of_pk)
                logger.info(
                    f"[executor] {pair}: cleared stale pending_open — no matching IG position found"
                )

    return count, seen


def close_position(
    epic: str = "",
    reason: Optional[str] = None,
    exit_hint_price: Optional[float] = None,
    *,
    pos_key: Optional[str] = None,
):
    """Close a specific position.

    Accepts either pos_key (preferred) or bare epic (backward compat — closes
    the first active position found for that epic).
    """
    if pos_key:
        pk = str(pos_key).strip()
    else:
        pk = str(epic).strip()
    st = _state_for_epic(pk)
    _real_epic = st.get("epic") or _epic_from_pos_key(pk) if "|" in pk else pk

    if exit_hint_price is not None:
        try:
            hint = float(exit_hint_price)
            entry = _to_float_or_none(st.get("entry_price"))
            if entry is not None and entry > 0:
                deviation = abs(hint - entry) / entry
                if deviation > 0.20:
                    logger.warning(
                        "[%s] exit_hint_price %.1f rejected: %.0f%% from entry %.1f "
                        "(likely wrong instrument); using last_mid instead",
                        _real_epic, hint, deviation * 100, entry,
                    )
                    hint = _to_float_or_none(st.get("last_mid"))
            if hint is not None:
                st["exit_price"] = hint
        except Exception:
            pass

    if reason:
        st["close_reason"] = str(reason)

    _sync_legacy_trade_state_from(st)
    # Determine the pos_key that _state_for_epic actually resolved to
    resolved_pk = st.get("_pos_key") or pk
    return close_trade(resolved_pk)


def close_all_positions_for_epic(
    epic: str,
    reason: Optional[str] = None,
    exit_hint_price: Optional[float] = None,
):
    """Close ALL active positions for the given epic (all modes)."""
    epic = str(epic).strip()
    positions = get_all_positions_for_epic(epic)
    if not positions:
        return None
    results = []
    for pk, _st in positions:
        try:
            r = close_position(pos_key=pk, reason=reason, exit_hint_price=exit_hint_price)
            results.append(r)
        except Exception as e:
            logger.error(f"❌ close_all_positions_for_epic: failed for {pk}: {e}")
    return results[-1] if results else None
