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

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

# ============================================================
# ENVIRONMENT
# ============================================================
load_dotenv()

from open_sb_now import open_sb_now
from close_sb_now import close_sb_now, close_by_deal_id, get_open_positions


class _RatchetArmSkip(Exception):
    """Sentinel — control-flow exit from the ratchet-arm broker-SL block
    without triggering the generic Exception handler that WARN-logs a
    failure. Used by the tp-absent and already-inside guards (2026-08-22
    Item 2 fix)."""
    pass


def _ratchet_arm_should_install_broker_sl(
    tp_pips: float,
    existing_sl_pips: float,
    init_sl_pips: float,
) -> Tuple[bool, str]:
    """Pure guard used by the ratchet-arm broker-SL install block.

    Returns (install, reason).
      install=False, reason="tp_absent"       — tp missing/zero. Refuse to
        submit a stop-only PUT via `_amend_broker_sl` (whose contract sends
        BOTH stop and limit atomically) because passing `current_tp_price=
        entry ± 0*pip = entry` puts a broker limit AT entry, which triggers
        on any fill. This was the shipped-in-88f075d bug.
      install=False, reason="already_inside"  — an execute_trade SL is
        already inside RATCHET_INIT_SL_PIPS (i.e. safer / closer to entry).
        The ratchet must ONLY tighten, so leave it alone.
      install=True, reason="ok"               — both guards clear; caller
        should compute the SL/TP prices and amend.

    Extracted 2026-08-22 (Item 2 fix) so the guard is unit-testable outside
    the confirmation flow. Kept pure — no logging, no state, no IG calls.
    """
    if tp_pips <= 0.0:
        return False, "tp_absent"
    if 0.0 < existing_sl_pips <= init_sl_pips:
        return False, "already_inside"
    return True, "ok"
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


def peek_last_block_info() -> Optional[Dict[str, Any]]:
    """Read the slot WITHOUT clearing it. Lets multiple consumers (the
    autobot back-annotation + the execution_rejection_log telemetry
    wrapper) both read the same block-info row without racing."""
    return _LAST_BLOCK_INFO


# ============================================================
# CONFIG
# ============================================================

TRADE_SIZE = float(os.getenv("TRADE_SIZE", "1"))
DEFAULT_SL_PIPS = float(os.getenv("DEFAULT_SL_PIPS", "12"))
DEFAULT_TP_PIPS = float(os.getenv("DEFAULT_TP_PIPS", "30"))

# Sibling-safe ownership. Flipping RECONCILE_OWN_DEALS_ONLY to 0 restores
# the pre-2026-09 adopt-every-IG-position behaviour; on a shared account
# that silently adopts another bot's positions and exposes them to every
# manage-position exit in this process. Emit CRITICAL at import so a
# misconfiguration shows up at service start, not after the first close.
def _warn_if_reconcile_gate_disabled() -> bool:
    """Emit CRITICAL iff RECONCILE_OWN_DEALS_ONLY is explicitly off.
    Returns True iff the warning was emitted (useful for tests)."""
    if (os.getenv("RECONCILE_OWN_DEALS_ONLY", "1") or "1").strip() != "1":
        logger.critical(
            "[OWNERSHIP] RECONCILE_OWN_DEALS_ONLY=0 — reconcile will adopt "
            "every IG position on this account, including positions opened "
            "by a sibling bot sharing this account. Set "
            "RECONCILE_OWN_DEALS_ONLY=1 (the default) to restore "
            "sibling-safe reconcile."
        )
        return True
    return False


_warn_if_reconcile_gate_disabled()

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


# ── Phase 2B identity envelope (§3.4) ───────────────────────────────
# Typed, optional identity context the dispatch adapter constructs
# from orchestrator_v2.submit()'s canonical Candidate and threads
# into execute_trade. Absent identity_context => LEGACY_EXTERNAL_BYPASS
# origin; POSITION_OPEN's candidate_id / parent_event_id fields MUST
# be null on that path (no fabrication).
#
# The dataclass is homed in measurement_writer (side-effect-free
# module) so callers can build one without importing this module
# (which triggers load_dotenv on import). It is re-exported here
# for API compatibility with callers that consume it via the
# executor's public surface.
from measurement_writer import Phase2bIdentityContext  # noqa: F401  (re-export)


# ── Phase 2B family derivation (mode → strategy_family, LEGACY FALLBACK ONLY)

# When identity_context.strategy_family is present, it is authoritative.
# This mapping is consulted ONLY for LEGACY_EXTERNAL_BYPASS fires
# (NEWS_STRATEGY tick path etc.) that never went through
# orchestrator_v2.submit(). Ordered longest-prefix first so
# BB_REVERSAL_PATTERNS beats BB_REV etc.
_PHASE2B_FAMILY_TOKENS = (
    ("BB_REVERSAL_PATTERNS", "BB_REVERSAL_PATTERNS"),
    ("BB_REVERSAL", "BB_REVERSAL_PATTERNS"),
    ("BB_BOUNCE", "BB_BOUNCE"),
    ("LEVEL_BOUNCE", "LEVEL_BOUNCE"),
    ("EMA_PULLBACK", "EMA_PULLBACK"),
    ("STRUCTURE_BREAK", "STRUCTURE_BREAK"),
    ("TREND_V3", "TREND_V3"),
    ("PIVOT_BREAK", "PIVOT_BREAK"),
    ("CONFIRMATION_FALLBACK", "CONFIRMATION_FALLBACK"),
    ("NEWS_CONT_LEG", "NEWS_CONTINUATION"),
    ("NEWS_CONTINUATION", "NEWS_CONTINUATION"),
    ("NEWS_STRATEGY", "NEWS_STRATEGY"),
    ("NEWS_TICK", "NEWS_TICK"),
    ("NEWS_TREND", "NEWS_TREND"),
    ("QM_V2", "QM_V2"),
    ("BRIEFING_V5", "BRIEFING_V5"),
    ("BRIEFING_EXECUTION", "BRIEFING_EXECUTION"),
    ("BRIEFING", "BRIEFING_EXECUTION"),
    ("H1_PIERCE", "H1_PIERCE"),
    ("LIQUIDITY_SWEEP", "LIQUIDITY_SWEEP"),
)


def _phase2b_family_from_mode(mode: str) -> str:
    """DOCUMENTED LEGACY FALLBACK — coarse mapping from mode string to
    strategy_family when no canonical Phase2bIdentityContext was
    supplied (i.e. the fire arrived via a legacy/external bypass path).

    A canonical strategy_family in the identity envelope OVERRIDES this
    mapping. Deterministic, longest-prefix match; falls back to
    `UNKNOWN` when no token matches. Never raises.
    """
    try:
        m = str(mode or "").upper()
        if not m:
            return "UNKNOWN"
        for token, family in _PHASE2B_FAMILY_TOKENS:
            if token in m:
                return family
        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _phase2b_bar_ts_from_context_or_fallback(
    identity_context: Optional[Phase2bIdentityContext],
    decision: Any,
) -> Tuple[str, str]:
    """Return (bar_ts_iso, provenance).

    Priority:
      1. identity_context.detected_ts (PROPAGATED_FROM_ORIGINAL_EVENT).
      2. decision.debug["entry_bar_ts"] (PROPAGATED — legacy caller
         convention set by BB_BOUNCE / LEVEL_BOUNCE).
      3. floor(now, 5m) fallback (RECONSTRUCTED_OR_INFERRED — MUST NOT
         be presented as the detector's original ts).

    The provenance label is written into the row's identity_provenance
    map so downstream analysis never treats a fallback ts as the
    detector's real bar boundary.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    # Try context first — authoritative when present.
    ctx_ts = getattr(identity_context, "detected_ts", None) if identity_context else None
    if ctx_ts:
        try:
            if hasattr(ctx_ts, "astimezone"):
                return ctx_ts.astimezone(_tz.utc).isoformat(), "PROPAGATED_FROM_ORIGINAL_EVENT"
            s = str(ctx_ts).replace("Z", "+00:00")
            parsed = _dt.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_tz.utc)
            return parsed.astimezone(_tz.utc).isoformat(), "PROPAGATED_FROM_ORIGINAL_EVENT"
        except Exception:
            pass

    # Legacy convention: decision.debug["entry_bar_ts"]. Also treated
    # as PROPAGATED because the detector explicitly stamped it.
    try:
        dbg = getattr(decision, "debug", None) or {}
        raw = dbg.get("entry_bar_ts") or getattr(decision, "entry_bar_ts", None)
        if raw is not None:
            if hasattr(raw, "astimezone"):
                return raw.astimezone(_tz.utc).isoformat(), "PROPAGATED_FROM_ORIGINAL_EVENT"
            s = str(raw).replace("Z", "+00:00")
            parsed = _dt.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_tz.utc)
            return parsed.astimezone(_tz.utc).isoformat(), "PROPAGATED_FROM_ORIGINAL_EVENT"
    except Exception:
        pass

    # Last-resort floor-5m — explicitly labelled RECONSTRUCTED so
    # downstream never treats it as the original detector ts.
    try:
        now = _dt.now(_tz.utc)
        floored = now - _td(
            minutes=(now.minute % 5),
            seconds=now.second,
            microseconds=now.microsecond,
        )
        return floored.isoformat(), "RECONSTRUCTED_OR_INFERRED"
    except Exception:
        return "", "MISSING"


# Backwards-compat shim kept for any external caller; new code should
# use _phase2b_bar_ts_from_context_or_fallback directly.
def _phase2b_bar_ts_for_emit(decision: Any) -> str:
    ts, _prov = _phase2b_bar_ts_from_context_or_fallback(None, decision)
    return ts


# ── POSITION_OPEN dedup by broker dealId ────────────────────────────
# Bounded per-process set (deque + set) so a retry for the same
# confirmed deal cannot emit two rows. dealId is broker-authoritative
# unique. Never grows without bound.

import threading as _phase2b_threading
from collections import deque as _phase2b_deque

_PHASE2B_EMITTED_LOCK = _phase2b_threading.Lock()
_PHASE2B_EMITTED_ORDER: "_phase2b_deque[str]" = _phase2b_deque(maxlen=1024)
_PHASE2B_EMITTED_SET: set = set()


def _phase2b_position_open_seen(deal_id: str) -> bool:
    """Return True if this deal_id has already produced a POSITION_OPEN
    in this process. Registers the deal_id atomically."""
    if not deal_id:
        return False
    with _PHASE2B_EMITTED_LOCK:
        if deal_id in _PHASE2B_EMITTED_SET:
            return True
        # If the deque is full, deque.append will drop the oldest;
        # keep the set in sync so it also bounds.
        if len(_PHASE2B_EMITTED_ORDER) == _PHASE2B_EMITTED_ORDER.maxlen:
            oldest = _PHASE2B_EMITTED_ORDER[0]
            _PHASE2B_EMITTED_SET.discard(oldest)
        _PHASE2B_EMITTED_ORDER.append(deal_id)
        _PHASE2B_EMITTED_SET.add(deal_id)
    return False


def _phase2b_reset_dedup_for_tests() -> None:
    """Test-only: clear the dedup set so each test starts fresh."""
    with _PHASE2B_EMITTED_LOCK:
        _PHASE2B_EMITTED_ORDER.clear()
        _PHASE2B_EMITTED_SET.clear()


def _emit_phase2b_position_open(*,
                                 st: Dict[str, Any],
                                 decision: Any,
                                 epic: str,
                                 direction: str,
                                 trade_size: float,
                                 sl_pips: Optional[float],
                                 tp_pips: Optional[float],
                                 deal_id: Optional[str],
                                 deal_reference: Optional[str],
                                 confirmation_received_at_epoch_ms: Optional[int] = None,
                                 broker_open_time_epoch_ms: Optional[int] = None,
                                 deal_reference_broker_echoed: Optional[bool] = None,
                                 local_position_key: Optional[str] = None,
                                 identity_context: Optional[Phase2bIdentityContext] = None,
                                 # ``open_epoch_ms`` retained as an
                                 # alias for
                                 # ``confirmation_received_at_epoch_ms``
                                 # for the small number of internal
                                 # tests written against the earlier
                                 # signature. Callers SHOULD use the
                                 # explicit name; new production code
                                 # does.
                                 open_epoch_ms: Optional[int] = None,
                                 ) -> bool:
    """Emit one POSITION_OPEN measurement row on the confirmed-fill
    seam. Never raises. Returns True on successful enqueue, False on
    OFF / rejected / missing-writer / duplicate-deal.

    Wiring rule: initializer = measurement_writer module import;
    driver = trade_executor.execute_trade confirmed-fill branch;
    consumer = phase2b_measurement.jsonl.

    Origin resolution:
      * identity_context supplied → origin = CANONICAL. All identity
        fields are PROPAGATED from the original Candidate.
      * identity_context is None → origin = LEGACY_EXTERNAL_BYPASS.
        candidate_id and parent_event_id MUST be null in the row —
        no fabrication. strategy_family falls back to the mode
        mapping and is labelled RECONSTRUCTED_OR_INFERRED.

    Duplicate suppression: dealId is broker-authoritative unique;
    a second call with the same dealId (retry, reconciliation) is a
    no-op returning False.

    This is telemetry only. No admission, exit, or broker call is
    influenced by any code path in this helper. Any exception is
    swallowed and does not propagate into execute_trade's return
    value.
    """
    try:
        import measurement_writer as _mw
    except Exception:
        return False
    try:
        if not _mw.is_enabled():
            return False
        # Deduplicate by broker dealId (retries / reconciliation).
        _did_str = str(deal_id) if deal_id else ""
        if _did_str and _phase2b_position_open_seen(_did_str):
            return False

        # ── Identity resolution ────────────────────────────────────
        canonical = identity_context is not None
        origin = _mw.ORIGIN_CANONICAL if canonical else _mw.ORIGIN_LEGACY_EXTERNAL_BYPASS

        pair = (
            str(identity_context.pair).upper() if canonical and identity_context.pair
            else _pair_from_epic(epic)
        )
        mode = str(st.get("mode") or getattr(decision, "mode", "") or "").upper()
        strategy = (
            str(identity_context.strategy) if canonical and identity_context.strategy
            else (mode or None)
        )
        # Family: canonical envelope overrides the mode-fallback.
        family_from_context = (
            str(identity_context.strategy_family).upper()
            if canonical and identity_context.strategy_family
            else None
        )
        family = family_from_context or _phase2b_family_from_mode(mode)
        side_raw = (
            str(identity_context.side).upper()
            if canonical and identity_context.side
            else str(direction or "").upper()
        )
        # Canonical Candidate side vocab is LONG/SHORT; broker side is
        # BUY/SELL. Normalise to BUY/SELL for the measurement row.
        if side_raw == "LONG":
            side = "BUY"
        elif side_raw == "SHORT":
            side = "SELL"
        else:
            side = side_raw

        # candidate_id: propagate or explicitly MISSING.
        originating_candidate_id: Optional[str] = None
        parent_event_id: Optional[str] = None
        parent_candidate_id: Optional[str] = None
        bounce_event_id: Optional[str] = None
        level_id: Optional[str] = None
        propagated_oid: Optional[str] = None
        if canonical:
            originating_candidate_id = str(identity_context.candidate_id) if identity_context.candidate_id else None
            parent_event_id = (
                str(identity_context.parent_event_id)
                if identity_context.parent_event_id
                else None
            )
            propagated_oid = (
                str(identity_context.observation_event_id)
                if identity_context.observation_event_id
                else None
            )
            parent_candidate_id = (
                str(identity_context.parent_candidate_id)
                if identity_context.parent_candidate_id
                else None
            )
            bounce_event_id = (
                str(identity_context.bounce_event_id)
                if identity_context.bounce_event_id
                else None
            )
            level_id = (
                str(identity_context.level_id)
                if identity_context.level_id
                else None
            )

        bar_ts, bar_ts_prov = _phase2b_bar_ts_from_context_or_fallback(
            identity_context, decision,
        )

        # ``open_epoch_ms`` is a backwards-compatible alias for
        # ``confirmation_received_at_epoch_ms`` — the LOCAL wall-clock
        # at /confirms return. It is NOT a broker open timestamp.
        if confirmation_received_at_epoch_ms is None:
            confirmation_received_at_epoch_ms = open_epoch_ms

        # dealReference provenance: client generates the reference and
        # uploads it to IG; IG's accepted /confirms body echoes the
        # same reference. The caller passes
        # ``deal_reference_broker_echoed=True`` when it has confirmed
        # the accepted-confirmation body actually returned the same
        # reference; otherwise the row records only CLIENT_GENERATED.
        _dr_prov = (
            "MISSING" if not deal_reference
            else (
                "CLIENT_GENERATED_BROKER_CORRELATED"
                if bool(deal_reference_broker_echoed)
                else "CLIENT_GENERATED"
            )
        )

        # Per-field identity_provenance map (frozen vocab).
        prov = {
            "origin": (
                "PROPAGATED_FROM_ORIGINAL_EVENT" if canonical
                else "MISSING"
            ),
            "originating_candidate_id": (
                "PROPAGATED_FROM_ORIGINAL_EVENT"
                if originating_candidate_id
                else "MISSING"
            ),
            "parent_event_id": (
                "PROPAGATED_FROM_ORIGINAL_EVENT"
                if parent_event_id
                else "MISSING"
            ),
            "originating_observation_event_id": (
                "PROPAGATED_FROM_ORIGINAL_EVENT" if propagated_oid
                else (
                    "DERIVED_WITHOUT_IDENTITY_LOSS"
                    if canonical and bar_ts_prov == "PROPAGATED_FROM_ORIGINAL_EVENT"
                    else "RECONSTRUCTED_OR_INFERRED"
                )
            ),
            "strategy_family": (
                "PROPAGATED_FROM_ORIGINAL_EVENT"
                if family_from_context
                else "RECONSTRUCTED_OR_INFERRED"
            ),
            "strategy": (
                "PROPAGATED_FROM_ORIGINAL_EVENT" if canonical
                else "RECONSTRUCTED_OR_INFERRED"
            ),
            "pair": (
                "PROPAGATED_FROM_ORIGINAL_EVENT" if canonical
                else "RECONSTRUCTED_OR_INFERRED"
            ),
            "side": (
                "PROPAGATED_FROM_ORIGINAL_EVENT" if canonical
                else "BROKER_CONFIRMED"
            ),
            "deal_id": "BROKER_CONFIRMED" if _did_str else "MISSING",
            "deal_reference": _dr_prov,
            "position_id": "BROKER_CONFIRMED" if _did_str else "MISSING",
            "confirmation_received_at_epoch_ms": (
                "LOCAL_CONFIRMATION_RECEIVED_AT"
                if confirmation_received_at_epoch_ms is not None
                else "MISSING"
            ),
            "broker_open_time_epoch_ms": (
                "BROKER_CONFIRMED"
                if broker_open_time_epoch_ms is not None
                else "MISSING"
            ),
            "local_position_key": (
                "CLIENT_GENERATED" if local_position_key else "MISSING"
            ),
            "bar_ts_utc": bar_ts_prov,
        }

        # ── Numeric coercion (fail-silent, never raise) ────────────
        _tp = float(tp_pips) if tp_pips is not None else None
        _sl = float(sl_pips) if sl_pips is not None else None
        _entry = st.get("entry_price")
        try:
            _entry_f = float(_entry) if _entry is not None else None
        except Exception:
            _entry_f = None
        _pip = st.get("pip_size")
        try:
            _pip_f = float(_pip) if _pip is not None else None
        except Exception:
            _pip_f = None

        row = _mw.build_position_open(
            pair=pair, timeframe="5m",
            bar_ts_utc=bar_ts,
            detector_family=family,
            side=side,
            source_class=_mw.SOURCE_PRODUCTION_OBSERVED,
            source_module="trade_executor",
            source_caller="trade_executor.execute_trade",
            origin=origin,
            identity_provenance=prov,
            deal_id=(_did_str or None),
            deal_reference=(str(deal_reference) if deal_reference else None),
            deal_reference_broker_echoed=deal_reference_broker_echoed,
            originating_candidate_id=originating_candidate_id,
            originating_observation_event_id=propagated_oid,
            parent_event_id=parent_event_id,
            parent_candidate_id=parent_candidate_id,
            bounce_event_id=bounce_event_id,
            entry_price=_entry_f,
            entry_price_source="ig_fill",
            sl_pips=_sl,
            tp1_pips=_tp,
            broker_tp_pips=_tp,
            confirmation_received_at_epoch_ms=(
                int(confirmation_received_at_epoch_ms)
                if confirmation_received_at_epoch_ms is not None
                else None
            ),
            broker_open_time_epoch_ms=(
                int(broker_open_time_epoch_ms)
                if broker_open_time_epoch_ms is not None
                else None
            ),
            epic=str(epic),
            strategy=strategy,
            trade_size=(float(trade_size) if trade_size is not None else None),
            pip_size=_pip_f,
            level_id=level_id,
            local_position_key=local_position_key,
            bar_ts_provenance=bar_ts_prov,
        )
        return bool(_mw.append(row))
    except Exception:
        # Fail-silent: measurement must not propagate errors into the
        # trading path.
        try:
            logger.debug("[phase2b] POSITION_OPEN emit swallowed exc", exc_info=True)
        except Exception:
            pass
        return False


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


def proposed_broker_stop_price(
    entry_price: Any,
    sl_pips: Any,
    direction: str,
    pair: str,
) -> Optional[float]:
    """A28 (operator ruling, 2026-10-05) — the single authoritative
    arithmetic that turns a proposed entry + a stop-distance in pips
    into the broker stop PRICE for an IG spread-bet feed.

    On IG spread-bet feeds 1 pip == 1 point. The broker-side stop
    price for a submitted order is:

        BUY  (LONG):  entry_price - sl_pips * ppp
        SELL (SHORT): entry_price + sl_pips * ppp

    where ``ppp = _ppp_for_pair(pair)``.

    Reused by:
      * ``_enrich_alert_debug`` (the alert-time computation that
        populates the telegram-alert dict); and
      * A28 structural-inside-protection check (one_strategy_emitter
        + the integrated replay harness).

    Returns None on malformed inputs.
    """
    try:
        e = float(entry_price)
        s = float(sl_pips)
    except (TypeError, ValueError):
        return None
    ppp = _ppp_for_pair(pair)
    sign = -1.0 if str(direction).upper() == "BUY" else 1.0
    return e + sign * s * ppp


def _enrich_alert_debug(
    dbg: Optional[Dict[str, Any]],
    entry_price: Any,
    sl_pips: Any,
    direction: str,
    pair: str,
) -> Dict[str, Any]:
    """Populate sl_price / sl_source / level_price / level_source into the
    alert debug dict so telegram_alerts.send_trade_open_alert never renders
    empty parens. The stop PRICE computation is delegated to
    ``proposed_broker_stop_price`` so A28 reuses the same arithmetic
    (no duplicated pip conversion). Strategy-provided values win:
    setdefault preserves anything the caller already supplied.
    """
    out: Dict[str, Any] = dict(dbg) if isinstance(dbg, dict) else {}
    broker_sl = proposed_broker_stop_price(
        entry_price, sl_pips, direction, pair,
    )
    if broker_sl is not None:
        out.setdefault("sl_price", round(broker_sl, 1))
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
    # Bid / offer stamped by update_trade_state and by
    # trade_manager._monitor_single_position. Consumed by the amend
    # preflight (BUY→last_bid, SELL→last_ask) so a proposed stop is
    # validated against the authoritative closing-side price rather
    # than the midpoint.
    "last_bid": None,
    "last_ask": None,
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

# ──────────────────────────────────────────────────────────────────────
# Build 2 (v2/build2) — vanished-close emission + supersession.
#
# `close_trade` fires _CLOSE_CALLBACKS at trade_executor.py:4802 for every
# explicit close with the real broker fill price (price_source =
# AUTHORITATIVE_BROKER_CLOSE).
#
# The three vanished-close paths (reconcile_open_positions,
# _sweep_expired_orphans, post-restart signal_log_integrity reconcile)
# previously bypassed the callback. Now they fire via two helpers:
#
#   _emit_vanished_close(pk, reason)
#       Fires an ESTIMATED_LAST_MID close row keyed by deal_id. One per
#       deal_id — a second attempt is deduped. Spawns a background
#       daemon that tries to fetch IG's real close (activity history)
#       after a short delay so an AUTHORITATIVE_IG_HISTORY row can
#       SUPERSEDE the estimate for readers.
#
#   _emit_authoritative_close(pk, exit_price, pnl_pips, reason, deal_id)
#       Fires an AUTHORITATIVE_IG_HISTORY close row. One per deal_id —
#       a second attempt is deduped. ALLOWED after a prior estimated
#       row for the same deal_id (that is the supersession path).
#
# Readers of logs/unified_trades.jsonl use trade_log.read_closes_by_
# deal_id to collapse to one row per deal, taking AUTHORITATIVE over
# ESTIMATED.
# ──────────────────────────────────────────────────────────────────────
_ESTIMATED_CLOSE_EMITTED: set = set()
_AUTHORITATIVE_CLOSE_EMITTED: set = set()
_VANISHED_CLOSE_LOCK = threading.Lock()

# Env knob: default-on prompt-fetch after a vanish. Set to "0" to disable
# in tests / replays where the IG REST path isn't live.
_PROMPT_AUTH_ENABLED = os.getenv("TRADE_LOG_PROMPT_AUTHORITATIVE_ENABLED", "1") != "0"
# Seconds to wait before polling IG activity history for the vanished
# deal. IG populates /history/transactions a few seconds after a
# server-side close; 30 s is a conservative margin.
_PROMPT_AUTH_DELAY_SECS = float(os.getenv("TRADE_LOG_PROMPT_AUTHORITATIVE_DELAY_SECS", "30"))


def _emit_vanished_close(pos_key: str, reason: str) -> None:
    """Fire _CLOSE_CALLBACKS for a position whose state is about to be
    reset because the broker no longer has it.

    Emits an ESTIMATED_LAST_MID row — exit_price falls back to the last
    tick mid, pnl_pips is None. One per deal_id (deduped against
    _ESTIMATED_CLOSE_EMITTED). If the deal_id has already received an
    AUTHORITATIVE close (via supersession from the daily reconciler),
    the estimated emit is suppressed because the authoritative row is
    already in the log and more accurate.

    After the estimated row is written, spawns a background daemon that
    waits _PROMPT_AUTH_DELAY_SECS and attempts to fetch IG's real close
    for this deal_id; if found, emits an AUTHORITATIVE_IG_HISTORY row
    that supersedes the estimate.
    """
    try:
        with EPIC_STATE_LOCK:
            st = EPIC_STATE.get(pos_key) or {}
            if not (st.get("active") or st.get("pending_open")):
                return
            deal_id = str(st.get("deal_id") or st.get("dealId") or "")
            last_mid = st.get("last_mid")
            exit_hint = st.get("exit_price") or last_mid
            direction = str(st.get("direction") or "").upper()
            entry_price = st.get("entry_price")
            pair = _pair_from_epic(st.get("epic") or _epic_from_pos_key(pos_key))
        with _VANISHED_CLOSE_LOCK:
            if deal_id and deal_id in _AUTHORITATIVE_CLOSE_EMITTED:
                return
            if deal_id and deal_id in _ESTIMATED_CLOSE_EMITTED:
                return
            if deal_id:
                _ESTIMATED_CLOSE_EMITTED.add(deal_id)
                if len(_ESTIMATED_CLOSE_EMITTED) > 10000:
                    _ESTIMATED_CLOSE_EMITTED.clear()
                    _ESTIMATED_CLOSE_EMITTED.add(deal_id)
        _fire_close_callbacks(
            pos_key=pos_key,
            exit_price=exit_hint,
            pnl_pips=None,
            close_reason=reason,
            deal_id=deal_id or None,
            price_source="ESTIMATED_LAST_MID",
        )
        if _PROMPT_AUTH_ENABLED and deal_id:
            try:
                _spawn_prompt_authoritative_fetch(
                    pos_key=pos_key, deal_id=deal_id,
                    direction=direction, entry_price=entry_price,
                    pair=pair,
                )
            except Exception as _spawn_exc:
                logger.warning(
                    "[VANISHED_CLOSE] prompt-fetch spawn failed for pk=%s "
                    "did=%s: %s", pos_key, deal_id, _spawn_exc,
                )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("[VANISHED_CLOSE] emit failed for pk=%s: %s", pos_key, exc)


def _emit_authoritative_close(
    pos_key: str,
    exit_price: Optional[float],
    pnl_pips: Optional[float],
    reason: str,
    *,
    deal_id: Optional[str],
) -> None:
    """Fire _CLOSE_CALLBACKS with an AUTHORITATIVE_IG_HISTORY row.

    One per deal_id (deduped). Writes even if a prior ESTIMATED_LAST_MID
    row exists for the same deal_id — that is the supersession path.
    After this call, future _emit_vanished_close for the same deal_id
    is a no-op (authoritative is final).
    """
    try:
        did = str(deal_id or "")
        with _VANISHED_CLOSE_LOCK:
            if did and did in _AUTHORITATIVE_CLOSE_EMITTED:
                return
            if did:
                _AUTHORITATIVE_CLOSE_EMITTED.add(did)
                if len(_AUTHORITATIVE_CLOSE_EMITTED) > 10000:
                    _AUTHORITATIVE_CLOSE_EMITTED.clear()
                    _AUTHORITATIVE_CLOSE_EMITTED.add(did)
        _fire_close_callbacks(
            pos_key=pos_key,
            exit_price=exit_price,
            pnl_pips=pnl_pips,
            close_reason=reason,
            deal_id=did or None,
            price_source="AUTHORITATIVE_IG_HISTORY",
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "[AUTHORITATIVE_CLOSE] emit failed for pk=%s did=%s: %s",
            pos_key, deal_id, exc,
        )


def _fire_close_callbacks(
    pos_key: str,
    exit_price: Optional[float],
    pnl_pips: Optional[float],
    close_reason: str,
    *,
    deal_id: Optional[str],
    price_source: Optional[str],
) -> None:
    """Walk _CLOSE_CALLBACKS, trying the price_source-aware kwarg form
    first and falling back to deal_id-only / legacy forms so callbacks
    that have not been updated keep working."""
    for _cb in list(_CLOSE_CALLBACKS):
        _delivered = False
        try:
            _cb(pos_key, exit_price, pnl_pips, close_reason,
                deal_id=deal_id, price_source=price_source)
            _delivered = True
        except TypeError:
            pass
        except Exception:
            _delivered = True  # swallowed; don't fall back
        if _delivered:
            continue
        try:
            _cb(pos_key, exit_price, pnl_pips, close_reason, deal_id=deal_id)
            _delivered = True
        except TypeError:
            pass
        except Exception:
            _delivered = True
        if _delivered:
            continue
        try:
            _cb(pos_key, exit_price, pnl_pips, close_reason)
        except Exception:
            pass


def _spawn_prompt_authoritative_fetch(
    *,
    pos_key: str,
    deal_id: str,
    direction: str,
    entry_price: Any,
    pair: str,
) -> None:
    """Spawn a daemon thread that, after a short delay, tries to fetch
    IG's authoritative close for ``deal_id`` and emits an
    AUTHORITATIVE_IG_HISTORY row that supersedes the just-written
    estimate.

    Best-effort. If IG REST fails, the daily reconciler
    (``signal_log_integrity.reconcile_for_date``) is the backstop.
    """
    def _worker() -> None:
        try:
            time.sleep(_PROMPT_AUTH_DELAY_SECS)
        except Exception:
            return
        try:
            import signal_log_integrity as _sli
            # Today's UTC date — the only window where a just-vanished
            # position would be found in /history/transactions.
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            txs = _sli._fetch_ig_transactions(today_utc)
            if not txs:
                return
            match = None
            for tx in txs:
                if str(tx.get("dealId") or "") == deal_id:
                    match = tx
                    break
            if match is None:
                return
            # Reuse the existing math.
            try:
                open_lvl = float(match.get("openLevel"))
                close_lvl = float(match.get("closeLevel"))
            except Exception:
                return
            sign = 1.0 if direction == "BUY" else -1.0
            pnl_pips = round((close_lvl - open_lvl) * sign, 2)
            _emit_authoritative_close(
                pos_key=pos_key,
                exit_price=close_lvl,
                pnl_pips=pnl_pips,
                reason="IG_RECONCILE_PROMPT",
                deal_id=deal_id,
            )
        except Exception as exc:
            logger.debug(
                "[PROMPT_AUTH] fetch failed for did=%s: %s",
                deal_id, exc,
            )
    threading.Thread(
        target=_worker,
        name=f"prompt-auth-{deal_id[:12]}",
        daemon=True,
    ).start()


def _reset_vanished_close_for_tests() -> None:
    """Clear the dedup sets. Not for prod."""
    with _VANISHED_CLOSE_LOCK:
        _ESTIMATED_CLOSE_EMITTED.clear()
        _AUTHORITATIVE_CLOSE_EMITTED.clear()


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


# ─────────────────────────────────────────────────────────────
# Candidate-corpus fallback ownership source (Repair 9, 2026-09-29)
#
# The signal_log write path stopped for orchestrator-routed families
# (ONE_STRATEGY, QM_V2, V2_PICK_BOUNCE, BRIEFING_EXECUTION) at
# 2026-09-25 16:00:06 UTC because those families dispatch through
# strategy_dispatch_adapter.submit_and_execute → orchestrator_v2
# → candidate_corpus_writer (execution recorded to candidate_corpus)
# instead of the legacy autobot.py post-execute log_open sites.
# candidate_corpus continued to record every successful open with
# executed=True + execution_deal_id + execution_deal_ref + candidate_id
# + strategy_family + source_path + execution_ts — a complete AutoBot
# origination chain — but reconcile only consulted signal_log for
# ownership attribution, so proven AutoBot positions would be
# misclassified as FOREIGN on restart.
#
# Repair 9 adds candidate_corpus as a SECOND durable ownership source,
# consulted only when signal_log doesn't find a match. Sibling-bot deals
# are still never adopted because candidate_corpus is written by
# AutoBot's own orchestrator/adapter seam — a sibling bot on the shared
# IG account cannot produce a candidate_corpus row on this host.
# ─────────────────────────────────────────────────────────────

_CANDIDATE_CORPUS_LIVE_PATH = "/opt/tradingbot/logs/candidate_corpus.jsonl"
_CANDIDATE_CORPUS_ROTATED_GLOB = "/opt/tradingbot/logs/candidate_corpus.jsonl-*"
_CANDIDATE_CORPUS_ROTATED_LIMIT = 30
_CANDIDATE_CORPUS_SCAN_LINES = 20000


def _iter_candidate_corpus_paths() -> list:
    """Return candidate_corpus paths in newest-first order: live then rotated."""
    import glob
    paths: list = []
    try:
        if os.path.isfile(_CANDIDATE_CORPUS_LIVE_PATH):
            paths.append(_CANDIDATE_CORPUS_LIVE_PATH)
    except Exception:
        pass
    try:
        rotated = [p for p in glob.glob(_CANDIDATE_CORPUS_ROTATED_GLOB)
                   if not p.endswith(".gz")
                   and ".PURGE_" not in p
                   and ".PURGE_NOTE" not in p]
        rotated.sort(reverse=True)
        paths.extend(rotated[:_CANDIDATE_CORPUS_ROTATED_LIMIT])
    except Exception:
        pass
    return paths


def _candidate_corpus_row_proves_ownership(row: Dict[str, Any]) -> bool:
    """A candidate_corpus row establishes AutoBot ownership iff it carries
    the complete durable execution chain:
      * executed is True (AutoBot recorded a successful open),
      * execution_deal_id is a non-empty string (broker acknowledged),
      * candidate_id is a non-empty string (AutoBot Candidate identity),
      * execution_ts is a non-empty string (AutoBot dispatch timestamp).

    Operator §3 explicitly permits candidate-corpus ownership evidence when
    these are all present. Rows that are merely observed candidates
    (executed=False, no execution_deal_id) do NOT prove ownership.
    """
    try:
        if not row.get("executed"):
            return False
        if not str(row.get("execution_deal_id") or "").strip():
            return False
        if not str(row.get("candidate_id") or "").strip():
            return False
        if not str(row.get("execution_ts") or "").strip():
            return False
        return True
    except Exception:
        return False


def _scan_candidate_corpus(match_deal_id: Optional[str],
                           match_deal_ref: Optional[str]) -> Optional[Dict[str, Any]]:
    """Scan candidate_corpus files newest-first for a row whose
    execution_deal_id OR execution_deal_ref exactly matches the target
    AND which passes the ownership-proof predicate. Returns the first
    matching row (which is the most recent, live before rotated), or None.

    EXACT ID MATCH ONLY. No fuzzy pair/time matching (operator §4).
    """
    if not match_deal_id and not match_deal_ref:
        return None
    md = str(match_deal_id or "").strip()
    mr = str(match_deal_ref or "").strip()
    import json as _json
    from collections import deque as _deque
    for path in _iter_candidate_corpus_paths():
        try:
            with open(path, "r", encoding="utf-8") as f:
                tail = _deque(f, maxlen=_CANDIDATE_CORPUS_SCAN_LINES)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        match = None
        for line in tail:
            s = line.strip()
            if not s:
                continue
            try:
                rec = _json.loads(s)
            except Exception:
                continue
            eid = str(rec.get("execution_deal_id") or "").strip()
            eref = str(rec.get("execution_deal_ref") or "").strip()
            hit = (md and eid == md) or (mr and eref == mr)
            if hit and _candidate_corpus_row_proves_ownership(rec):
                match = rec  # last-write-wins within the file
        if match is not None:
            return match
    return None


def lookup_candidate_corpus_by_deal_id(deal_id: str) -> Optional[Dict[str, Any]]:
    """Return the candidate_corpus row proving AutoBot origination for
    `deal_id`, or None. See _candidate_corpus_row_proves_ownership for
    the ownership predicate. Exact-match only.
    """
    if not deal_id:
        return None
    return _scan_candidate_corpus(match_deal_id=str(deal_id).strip(),
                                  match_deal_ref=None)


def lookup_candidate_corpus_by_deal_reference(deal_reference: str) -> Optional[Dict[str, Any]]:
    """Return the candidate_corpus row proving AutoBot origination for
    `deal_reference`, or None. Same predicate as the deal_id variant.
    """
    if not deal_reference:
        return None
    return _scan_candidate_corpus(match_deal_id=None,
                                  match_deal_ref=str(deal_reference).strip())


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
    briefing_priority = _briefing_priority_enabled()
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
        # BRIEFING_PRIORITY (2026-10-06): briefing positions do not
        # count toward other routes' per-pair / per-direction caps.
        if briefing_priority and _epic_state_is_briefing(k, st):
            continue
        # BOUNCE_ENGINE (BUILD_NOTES.md step 3): bounce engine owns its
        # own position allowance and must not consume other routes'
        # caps. Gated by BOUNCE_ENGINE_ENABLED so legacy counts are
        # byte-identical when the flag is off.
        if _bounce_engine_enabled() and _epic_state_is_bounce_engine(k, st):
            continue
        count += 1
    return count


def snapshot_active_deal_ids() -> Set[str]:
    """Capture the set of deal_ids for currently active/pending-open
    EPIC_STATE entries. Held under EPIC_STATE_LOCK so a single point-in-time
    snapshot is returned. Used as the `eligible_deal_ids` input to
    `reconcile_epic_state_with_broker` for snapshot-safe reconciliation.

    Rev.3 §1: the reconciliation snapshot boundary is defined by this
    capture — a position confirmed AFTER this call cannot appear here
    and is therefore ineligible for removal by the reconciliation that
    consumes this snapshot. This closes the race:

      T0  caller captures pre-snapshot deal_ids  (this call)
      T1  caller releases lock, requests IG /positions  (network I/O)
      T2  another thread confirms a new position with deal_id NEW-X
          → EPIC_STATE[pk] now has active=True, deal_id=NEW-X, but
            NEW-X is NOT in the pre-snapshot set from T0
      T3  IG response arrives without NEW-X (older-than-T2 view)
      T4  reconcile invoked with eligible_deal_ids=pre_snapshot
          → NEW-X is not in eligible set → NOT cleared. Safe.
    """
    with EPIC_STATE_LOCK:
        eligible: Set[str] = set()
        for st in EPIC_STATE.values():
            if not (st.get("active") or st.get("pending_open")):
                continue
            did = str(st.get("deal_id") or st.get("dealId") or "").strip()
            if did:
                eligible.add(did)
    return eligible


def reconcile_epic_state_with_broker(
    open_deal_ids: Optional[Any],
    *,
    eligible_deal_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Repair `EPIC_STATE` against an authoritative broker snapshot.

    Args:
      open_deal_ids: iterable of currently-open deal_id strings from IG.
        When None, treat broker state as unknown and return SKIP receipt
        without touching local state (bounded conservative fallback:
        never interpret a missing/errored broker response as
        "no positions open").
      eligible_deal_ids: set of deal_ids that were present in a
        pre-snapshot capture (see `snapshot_active_deal_ids`). If
        provided, ONLY entries whose deal_id is in this set are
        candidates for removal — entries created or updated AFTER the
        pre-snapshot moment are preserved. Rev.3 §1 snapshot-safety.
        When None (rev.2 back-compat), all no-deal_id-matching entries
        are removed — retains previous behaviour for tests that
        pre-date the eligibility parameter, but callers producing
        real broker snapshots SHOULD always pass this.

    Semantics:
      * An EPIC_STATE entry with active=True or pending_open=True whose
        deal_id is present, in the eligible set (or eligibility unset),
        but NOT in the broker set → cleared via the existing
        `_reset_trade_state` code path.
      * An entry with active=True but deal_id absent/empty is LEFT ALONE
        by this reconciler — it may be in the create-then-attach window.
        Rev.3 §2 defines a separate bounded lifecycle for such orphans:
        see `sweep_orphan_active_no_deal(max_age_s=...)`.
      * A broker-open deal_id with no matching EPIC_STATE entry → NOT
        invented (that is a manual/external position, not gate-tracked
        state).
      * With eligible_deal_ids provided: an entry whose deal_id is NOT
        in the eligible set (i.e. it was created/updated post-snapshot)
        is preserved regardless of the broker response.

    Returns a receipt (safe to log — only deal_ids and pos_keys):
      {
        "receipt": "OK" | "SKIP_BROKER_UNKNOWN",
        "local_active_before": int,
        "broker_open_count": int,
        "cleared_pos_keys": [str],
        "cleared_deal_ids": [str],
        "preserved_post_snapshot_deal_ids": [str],
        "local_active_after": int,
      }
    """
    if open_deal_ids is None:
        with EPIC_STATE_LOCK:
            local_active = sum(
                1 for st in EPIC_STATE.values()
                if st.get("active") or st.get("pending_open")
            )
        return {
            "receipt": "SKIP_BROKER_UNKNOWN",
            "local_active_before": local_active,
            "broker_open_count": -1,
            "cleared_pos_keys": [],
            "cleared_deal_ids": [],
            "preserved_post_snapshot_deal_ids": [],
            "local_active_after": local_active,
        }
    broker_set = {str(x).strip() for x in open_deal_ids if str(x).strip()}
    elig = None
    if eligible_deal_ids is not None:
        elig = {str(x).strip() for x in eligible_deal_ids if str(x).strip()}
    cleared_pks: List[str] = []
    cleared_dids: List[str] = []
    preserved_post_snapshot: List[str] = []
    with EPIC_STATE_LOCK:
        active_before = sum(
            1 for st in EPIC_STATE.values()
            if st.get("active") or st.get("pending_open")
        )
        to_clear: List[Tuple[str, str]] = []
        for pk, st in list(EPIC_STATE.items()):
            if not (st.get("active") or st.get("pending_open")):
                continue
            did = str(st.get("deal_id") or st.get("dealId") or "").strip()
            if not did:
                # No deal_id attached — cannot authoritatively reconcile.
                # See sweep_orphan_active_no_deal for bounded lifecycle.
                continue
            if elig is not None and did not in elig:
                # Post-snapshot creation/update — preserve. Rev.3 §1.
                preserved_post_snapshot.append(did)
                continue
            if did not in broker_set:
                to_clear.append((pk, did))
    # Perform resets OUTSIDE the lock — _reset_trade_state re-acquires
    # its own locking via _state_for_epic (single-writer semantics).
    for pk, did in to_clear:
        try:
            # Build-2 gap closure: broker lost the position — emit a
            # CLOSE callback so the unified trade log sees exactly one
            # row for this deal_id (close_trade's own fire never ran
            # because the reconciler, not the strategy, discovered the
            # vanish).  Idempotent per deal_id.
            _emit_vanished_close(pk, reason="IG_RECONCILE_CLEAR")
            _reset_trade_state(pk)
            cleared_pks.append(pk)
            cleared_dids.append(did)
        except Exception as exc:
            logger.warning(
                "[EXEC-RECONCILE] failed to reset pos_key=%s deal_id=%s: %s",
                pk, did, exc,
            )
    with EPIC_STATE_LOCK:
        active_after = sum(
            1 for st in EPIC_STATE.values()
            if st.get("active") or st.get("pending_open")
        )
    if cleared_pks or preserved_post_snapshot:
        logger.info(
            "[EXEC-RECONCILE] cleared %d stale EPIC_STATE entry(ies), "
            "preserved %d post-snapshot; "
            "local_active %d→%d broker_open=%d pos_keys=%s deals=%s",
            len(cleared_pks), len(preserved_post_snapshot),
            active_before, active_after,
            len(broker_set), cleared_pks, cleared_dids,
        )
    return {
        "receipt": "OK",
        "local_active_before": active_before,
        "broker_open_count": len(broker_set),
        "cleared_pos_keys": cleared_pks,
        "cleared_deal_ids": cleared_dids,
        "preserved_post_snapshot_deal_ids": preserved_post_snapshot,
        "local_active_after": active_after,
    }


# Rev.3 §2 — orphan sweep for active-but-no-deal_id entries.
#
# Some code paths set active=True (or pending_open=True) BEFORE the
# broker's deal_id is available (create-then-attach window). In the
# normal flow, deal_id is stamped in the same execute_trade call and
# the window is measured in milliseconds. If anything raises between
# the flag being set and the deal_id being attached, EPIC_STATE holds
# an orphan that this reconciler cannot address (no deal_id → no way
# to correlate with the broker set).
#
# Bounded lifecycle: an entry with (active or pending_open) and no
# deal_id is tracked from first observation. If it remains for longer
# than a grace period, it is cleared as an orphan. Grace defaults to
# 60s — well beyond a legitimate create-then-attach window.
#
# The tracking dict below is private to this module and only touched
# by sweep_orphan_active_no_deal + snapshot_active_no_deal (a test
# helper). It never inflates the occupancy counts read by the gate
# — that continues to iterate EPIC_STATE directly.

_ORPHAN_FIRST_SEEN_TS: Dict[str, float] = {}
_ORPHAN_LOCK = threading.RLock()
_ORPHAN_GRACE_S_DEFAULT = 60.0


def _reset_orphan_tracking_for_tests() -> None:
    """Test hook — clear orphan tracking state."""
    with _ORPHAN_LOCK:
        _ORPHAN_FIRST_SEEN_TS.clear()


def sweep_orphan_active_no_deal(
    max_age_s: float = _ORPHAN_GRACE_S_DEFAULT,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Clear EPIC_STATE entries with active/pending-open flags set for
    longer than `max_age_s` seconds without a deal_id being stamped.

    Rev.3 §2 — bounded orphan lifecycle. Prevents a no-deal_id stale
    entry from contributing indefinitely to occupancy counts.

    On each call:
      * Any active/pending entry without a deal_id is added to
        `_ORPHAN_FIRST_SEEN_TS[pos_key]` if not already present.
      * Any entry that has recovered a deal_id (or become inactive)
        is removed from tracking.
      * Any entry tracked for longer than `max_age_s` is cleared
        via `_reset_trade_state`.

    Returns a receipt (safe to log — pos_keys only, no PII):
      {
        "cleared_orphan_pos_keys": [str],
        "tracking_count": int,
        "grace_s": float,
      }
    """
    now_ts = time.time() if now is None else float(now)
    grace = float(max_age_s)
    cleared: List[str] = []
    with EPIC_STATE_LOCK:
        snapshot = list(EPIC_STATE.items())
    with _ORPHAN_LOCK:
        # 1) Remove tracking for entries that recovered a deal_id or
        #    are no longer active.
        for pk in list(_ORPHAN_FIRST_SEEN_TS.keys()):
            st = None
            for pkx, stx in snapshot:
                if pkx == pk:
                    st = stx
                    break
            if st is None:
                _ORPHAN_FIRST_SEEN_TS.pop(pk, None)
                continue
            if not (st.get("active") or st.get("pending_open")):
                _ORPHAN_FIRST_SEEN_TS.pop(pk, None)
                continue
            did = str(st.get("deal_id") or st.get("dealId") or "").strip()
            if did:
                _ORPHAN_FIRST_SEEN_TS.pop(pk, None)
                continue
        # 2) Insert tracking for newly-orphaned entries.
        for pk, st in snapshot:
            if not (st.get("active") or st.get("pending_open")):
                continue
            did = str(st.get("deal_id") or st.get("dealId") or "").strip()
            if did:
                continue
            _ORPHAN_FIRST_SEEN_TS.setdefault(pk, now_ts)
        # 3) Clear entries beyond grace.
        expired_pks = [
            pk for pk, ts in _ORPHAN_FIRST_SEEN_TS.items()
            if (now_ts - ts) > grace
        ]
    for pk in expired_pks:
        try:
            # Build-2 gap closure: an "orphan" here is a pos_key whose
            # state is active but carries no deal_id (strategy wrote the
            # state but never got a dealId back — upstream fire failed
            # or died mid-flight). Firing the callback with no deal_id
            # produces a row that the trade-log reader can still bucket
            # by pos_key / timestamp.  _emit_vanished_close dedup key is
            # the deal_id, so empty-deal_id orphans each emit once.
            _emit_vanished_close(pk, reason="ORPHAN_SWEEP")
            _reset_trade_state(pk)
            with _ORPHAN_LOCK:
                _ORPHAN_FIRST_SEEN_TS.pop(pk, None)
            cleared.append(pk)
        except Exception as exc:
            logger.warning(
                "[EXEC-ORPHAN-SWEEP] failed to reset pos_key=%s: %s",
                pk, exc,
            )
    with _ORPHAN_LOCK:
        tracking_count = len(_ORPHAN_FIRST_SEEN_TS)
    if cleared:
        logger.info(
            "[EXEC-ORPHAN-SWEEP] cleared %d orphan(s) (no deal_id > %.0fs): %s",
            len(cleared), grace, cleared,
        )
    return {
        "cleared_orphan_pos_keys": cleared,
        "tracking_count": tracking_count,
        "grace_s": grace,
    }


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
# EXECUTION-AUTHORITY FIREWALL (operator ruling 2026-09-29)
# ------------------------------------------------------------
# Only ONE_STRATEGY, BRIEFING_EXECUTION, V2_PICK_BOUNCE may open
# new broker positions on GBPUSD or EURUSD. Every other family
# is refused at this seam. This is an execution-ownership
# firewall, NOT a market-direction or setup-quality gate.
#
# Placement rationale: guards ONLY the new-open path
# (execute_trade). Close/amend/scale primitives (close_sb_now,
# close_by_deal_id, update_open_position) are on separate seams
# and are deliberately NOT touched — active-position management
# must continue.
#
# Independence rationale: the CENTRAL_EXECUTION_GATE runs in
# SHADOW mode by default and cannot be relied upon to block
# legacy dispatch. The operator ruling is that SHADOW must never
# mean legacy strategies can bypass the authority allowlist —
# so this firewall enforces regardless of any central-gate flag.
# The only kill switch is EXECUTION_AUTHORITY_FIREWALL_ENABLED
# (default "1"); an operator emergency can disable but a
# missing/blank env var leaves it enabled.
# ============================================================

_EXEC_AUTH_ALLOWED_FAMILIES: frozenset = frozenset({
    "ONE_STRATEGY",
    "BRIEFING_EXECUTION",
    "BRIEFING_V5",
    "V2_PICK_BOUNCE",
})
# Mode prefixes: matched as either exact string or "<prefix>_..."
# so that ONE_STRATEGY, BRIEFING_EXECUTION (both emitted as exact
# strings by their emitters) and V2_PICK_BOUNCE_{ENGINE}_{SIDE}
# broker modes are all accepted.
_EXEC_AUTH_ALLOWED_MODE_PREFIXES: Tuple[str, ...] = (
    "ONE_STRATEGY",
    "BRIEFING_EXECUTION",
    "BRIEFING_V5",
    "V2_PICK_BOUNCE",
)
_EXEC_AUTH_GUARDED_PAIRS: frozenset = frozenset({"GBPUSD", "EURUSD"})
_EXEC_AUTH_FIREWALL_LOG: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "logs",
    "execution_firewall.jsonl",
)


def _exec_auth_firewall_enabled() -> bool:
    """Kill switch. Default: enabled. Not gated by CENTRAL_EXECUTION_GATE_SHADOW."""
    return os.getenv("EXECUTION_AUTHORITY_FIREWALL_ENABLED", "1").strip() != "0"


def _exec_auth_identify(
    decision: Any,
    identity_context: Optional[Phase2bIdentityContext],
) -> Tuple[str, str, str, str]:
    """Return (family, source_path, mode, candidate_id) — upper-cased strings.

    Precedence: identity_context (canonical, when the adapter builds it)
    then falls back to decision.mode (the broker mode string). Legacy
    dispatch sites route through autobot.execute_trade with
    _p1_strategy_family=FAMILY_UNKNOWN — those arrive with family
    ``"UNKNOWN"`` here, so the mode-string fallback is load-bearing for
    the BRIEFING_EXECUTION path (its decision.mode is exactly
    ``"BRIEFING_EXECUTION"``).
    """
    family = ""
    source_path = ""
    candidate_id = ""
    if identity_context is not None:
        family = str(getattr(identity_context, "strategy_family", "") or "").strip().upper()
        source_path = str(getattr(identity_context, "source_path", "") or "").strip().upper()
        candidate_id = str(getattr(identity_context, "candidate_id", "") or "")
    mode = _safe_str(getattr(decision, "mode", None)).strip().upper()
    return family, source_path, mode, candidate_id


def _exec_auth_is_permitted(family: str, mode: str) -> bool:
    """True iff the family or the mode identifies one of the permitted authorities.

    The mode-string check is a prefix match so V2_PICK_BOUNCE variants
    (V2_PICK_BOUNCE_SLOW_REJECTION_L, ..._CONTINUATION_S) are accepted.
    QM_V2 (VELOCITY) is a distinct family — this predicate must return
    False for it. That is guaranteed because family=="QM_V2" is not in
    the allowlist and mode=="QM_V2_VELOCITY_S" does not have any of the
    three permitted prefixes.

    Build 2 Phase 2 (2026-10-06): the HYPOTHESIS family is admitted
    conditionally when ``HYPOTHESIS_TRADE_ENABLED=1``. Both the family
    tag and the mode prefix ``HYPOTHESIS`` are accepted so direct
    ``trade_executor.execute_trade`` callers (without an
    ``identity_context``) can place HYPOTHESIS fires. Flag defaults
    off → byte-identical to pre-Phase-2 behaviour.
    """
    if family in _EXEC_AUTH_ALLOWED_FAMILIES:
        return True
    # HYPOTHESIS family admission (Phase 2 2026-10-06) + stretch
    # reversal (Phase 2b) share the same family tag; either flag
    # opens the gate.
    _hyp_live = (
        os.getenv("HYPOTHESIS_TRADE_ENABLED", "0").strip() == "1"
        or os.getenv("STRETCH_REVERSAL_ENABLED", "0").strip() == "1"
    )
    if _hyp_live and family == "HYPOTHESIS":
        return True
    # Phase 3 (operator-system 2026-10-06): SYSTEM_REVERSAL family +
    # mode prefix admitted when SYSTEM_REVERSAL_ENABLED=1.
    _sys_rev_live = os.getenv("SYSTEM_REVERSAL_ENABLED", "0").strip() == "1"
    if _sys_rev_live and family == "SYSTEM_REVERSAL":
        return True
    # BOUNCE_ENGINE (bounce_engine/BUILD_NOTES.md step 3): admitted
    # with its own position allowance when BOUNCE_ENGINE_ENABLED=1.
    # Modes BOUNCE_A_L / BOUNCE_A_S are the engine's own mode tags.
    _bounce_live = os.getenv("BOUNCE_ENGINE_ENABLED", "0").strip() == "1"
    if _bounce_live and family == "BOUNCE_ENGINE":
        return True
    # Session 5 (2026-10-08): BB_BOUNCE_ADMIT=1 / TREND_V3_ADMIT=1 admit
    # the GBPUSD BB_BOUNCE and TREND_V3 families through the execution
    # firewall. Both flags default OFF so the firewall behaviour is
    # byte-identical when they are not set. The matching cutover-guard
    # pass-throughs live in central_execution_gate._execute_gate.
    _bb_admit_live = os.getenv("BB_BOUNCE_ADMIT", "0").strip() == "1"
    if _bb_admit_live and family == "BB_BOUNCE":
        return True
    _trend_v3_admit_live = os.getenv("TREND_V3_ADMIT", "0").strip() == "1"
    if _trend_v3_admit_live and family == "TREND_V3":
        return True
    # 2026-10-19 operator admit: QM_REVERSAL_ADMIT=1 opens the firewall
    # for QM reversal, but ONLY at the exact-mode level — NOT at the
    # QM_V2 family level. The QM_V2 family tag is retained on the
    # strategy identity for provenance / telemetry (candidate_corpus
    # groups all QM_V2 fires together), but a family-level admit would
    # also admit the untested QM_V2 velocity path, which is explicitly
    # out of scope. Admission therefore drops through to the exact-
    # mode block below (lines ~2600-2605) and the family branch above
    # at _EXEC_AUTH_ALLOWED_FAMILIES does NOT include QM_V2.
    _qm_rev_admit_live = os.getenv("QM_REVERSAL_ADMIT", "0").strip() == "1"
    if mode:
        for prefix in _EXEC_AUTH_ALLOWED_MODE_PREFIXES:
            if mode == prefix or mode.startswith(prefix + "_"):
                return True
        if _hyp_live and (mode == "HYPOTHESIS" or mode.startswith("HYPOTHESIS_")
                          or ("_HYPOTHESIS_" in mode)):
            return True
        if _sys_rev_live and (mode == "SYSTEM_REVERSAL"
                              or mode.startswith("SYSTEM_REVERSAL_")
                              or ("_SYSTEM_REVERSAL_" in mode)):
            return True
        if _bounce_live and (mode in _BOUNCE_ENGINE_MODES
                             or any(mode.startswith(p)
                                    for p in _BOUNCE_MODE_PREFIXES)):
            return True
        if _bb_admit_live and (mode == "GBPUSD_BB_BOUNCE_L"
                               or mode == "GBPUSD_BB_BOUNCE_S"):
            return True
        if _trend_v3_admit_live and mode in (
            "GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S",
            "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
        ):
            return True
        # 2026-10-19 operator admit — exact-mode match only. The
        # QM reversal detector (qm_reversal_detector.py) emits
        # strategy="QM_REVERSAL_L" / "QM_REVERSAL_S". The admit
        # does NOT accept any QM_V2_* velocity mode, nor an
        # arbitrary QM_REVERSAL_<suffix>. If the detector adds new
        # mode strings in future they must be enumerated here.
        if _qm_rev_admit_live and mode in (
            "QM_REVERSAL_L", "QM_REVERSAL_S",
        ):
            return True
    return False


def _exec_auth_log_refusal(
    *,
    pair: str,
    epic: str,
    family: str,
    source_path: str,
    mode: str,
    side: str,
    candidate_id: str,
) -> None:
    """Durable refusal telemetry — writes logs/execution_firewall.jsonl + WARN log.

    Fields per the operator ruling §9: ts, pair, strategy/family,
    source_path, side, candidate/signal/event id, result=REFUSED,
    reason=EXECUTION_AUTHORITY_NOT_PERMITTED.
    """
    ts_dt = datetime.now(timezone.utc)
    row = {
        "ts_utc": ts_dt.isoformat(),
        "ts_epoch_ms": int(ts_dt.timestamp() * 1000.0),
        "pair": pair,
        "epic": epic,
        "strategy_family": family,
        "source_path": source_path,
        "mode": mode,
        "side": side,
        "candidate_id": candidate_id,
        "result": "REFUSED",
        "reason": "EXECUTION_AUTHORITY_NOT_PERMITTED",
    }
    try:
        os.makedirs(os.path.dirname(_EXEC_AUTH_FIREWALL_LOG), exist_ok=True)
        with open(_EXEC_AUTH_FIREWALL_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as exc:
        logger.warning("[EXEC_AUTH_FIREWALL] telemetry write failed: %s", exc)
    logger.warning(
        "[EXEC_AUTH_FIREWALL] REFUSED pair=%s mode=%s family=%s source=%s "
        "side=%s reason=EXECUTION_AUTHORITY_NOT_PERMITTED",
        pair, mode or "?", family or "?", source_path or "?", side or "?",
    )


# ============================================================
# AUTOBOT AGGREGATE POSITION CAP — Repair 8, operator ruling 2026-09-29.
#
# For each guarded epic, the combined number of AutoBot-owned open +
# pending-open positions across the three authorised execution
# authorities (ONE_STRATEGY, BRIEFING_EXECUTION, V2_PICK_BOUNCE) must
# never exceed AUTOBOT_AGGREGATE_POSITION_CAP (default 2). This is
# NOT an IG-account-wide cap: sibling bots share the demo account and
# have their own independent caps.
#
# AutoBot ownership is inherent to EPIC_STATE. That map only holds
# positions this AutoBot instance itself opened (see line ~2981 where
# pending_open is stamped inside the reservation) OR positions the
# startup reconcile positively attributed to this host by matching
# their dealId / dealReference in this host's signal_log.jsonl (see
# reconcile_open_positions RECONCILE_OWN_DEALS_ONLY gate at
# line ~4368). Foreign deals — sibling AutoBot instance or hand
# trader — are logged to logs/foreign_deals_observed.jsonl and are
# never adopted into EPIC_STATE. They therefore do not consume
# AutoBot capacity, and AutoBot's opens do not consume theirs.
#
# Per operator §4: any AutoBot-owned position whose exact
# authorised-family cannot be reconstructed still counts. Because
# every entry in EPIC_STATE is by construction AutoBot-owned, and
# because the counter includes ALL active/pending entries for the
# pair regardless of their `mode` field, the cap already covers the
# three named families plus the "unreconstructable" bucket in a
# single pass. Legacy families from before Repair 1 (BB_BOUNCE,
# TREND_V3, …) that were reconciled into EPIC_STATE at startup are
# still AutoBot-owned and thus still consume the aggregate.
#
# Enforcement site is the reservation block in execute_trade (a few
# lines above the `open_sb_now` broker seam), held under
# EPIC_STATE_LOCK across the count and the `pending_open = True`
# reservation flip so two simultaneous AutoBot candidates cannot
# both observe the same free slot (operator §9 race protection).
# No cross-bot lock is introduced (operator §9 forbids that).
# ============================================================

_AUTOBOT_AGG_CAP_GUARDED_PAIRS: frozenset = frozenset({"GBPUSD", "EURUSD"})
_AUTOBOT_AGG_CAP_LOG: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "logs",
    "autobot_aggregate_position_cap.jsonl",
)


# ── BRIEFING_PRIORITY_ENABLED (2026-10-06) ────────────────────────────
# When ON:
#   1. Briefing positions (BRIEFING_EXECUTION / BRIEFING_V5) are NOT
#      counted by _autobot_agg_cap_count_for_pair or by
#      count_open_positions_by_pair_direction. Other routes therefore
#      only see non-briefing positions when they check their own caps.
#   2. A briefing trade bypasses: AGGREGATE_POSITION_CAP,
#      CONCURRENCY_CAP, GBPUSD_ANTIHEDGE and COHERENCE (one-book
#      opposing-direction) blocks on GBPUSD and EURUSD.
# Flag default off → byte-identical to pre-flag behaviour. Briefing's
# own internal limits (one position per plan, its per-pair rules) are
# untouched because they live inside briefing_execution.py, not here.
_BRIEFING_PRIORITY_FAMILIES: frozenset = frozenset(
    {"BRIEFING_EXECUTION", "BRIEFING_V5"}
)

# BOUNCE_ENGINE position tags. The engine owns its own allowance; its
# positions must not consume briefing / V5 / other-family capacity
# (BUILD_NOTES.md step 3 "its own position allowance").
_BOUNCE_ENGINE_FAMILIES: frozenset = frozenset({"BOUNCE_ENGINE"})
# All eight (setup, side) tags for the 8-slot engine. Setup A legacy
# tags stay; squeeze, trend-pullback and setup-C added for the 2026-10-08
# concurrent-positions build. Prefix check still covers BOUNCE_A_* for
# any legacy variant.
_BOUNCE_ENGINE_MODES: frozenset = frozenset({
    "BOUNCE_A_L", "BOUNCE_A_S",
    "BOUNCE_SQ_L", "BOUNCE_SQ_S",
    "BOUNCE_TR_L", "BOUNCE_TR_S",
    "BOUNCE_C_L", "BOUNCE_C_S",
    # V3 Structural Momentum (bounce_engine/v3/) is engine-managed
    # the same way the other bounce modes are. Including the four
    # V3 tags here lets pair-concurrency counting
    # (`count_open_positions_by_pair_direction` via
    # `_epic_state_is_bounce_engine`) exempt V3 from the shared
    # per-pair caps — matching the parallel exemption in
    # `trade_manager._BOUNCE_ENGINE_MODES`. Without this, a V3
    # position consumes a cap slot that briefing / Setup A/C/SQ/TR
    # would otherwise claim.
    "V3_BB_L", "V3_BB_S",
    "V3_EMA_L", "V3_EMA_S",
})
_BOUNCE_MODE_PREFIXES: tuple = (
    "BOUNCE_A_", "BOUNCE_SQ_", "BOUNCE_TR_", "BOUNCE_C_", "V3_",
)


def _bounce_engine_enabled() -> bool:
    return (os.getenv("BOUNCE_ENGINE_ENABLED", "0") or "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _is_bounce_engine_mode(mode_or_family: Any) -> bool:
    s = str(mode_or_family or "").strip().upper()
    if not s:
        return False
    if s in _BOUNCE_ENGINE_FAMILIES or s in _BOUNCE_ENGINE_MODES:
        return True
    return any(s.startswith(p) for p in _BOUNCE_MODE_PREFIXES)


def _epic_state_is_bounce_engine(k: str, state: dict) -> bool:
    """Does an EPIC_STATE entry belong to the bounce engine? Checks
    the ``mode`` / ``family`` fields on the state dict first, then
    falls back to the ``|`` suffix of the pos_key."""
    for field in ("mode", "family", "strategy_family"):
        v = state.get(field)
        if v and _is_bounce_engine_mode(v):
            return True
    if "|" in k:
        return _is_bounce_engine_mode(k.split("|", 1)[1])
    return False


def _briefing_priority_enabled() -> bool:
    return (os.getenv("BRIEFING_PRIORITY_ENABLED", "0") or "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _is_briefing_priority_mode(mode_or_family: Any) -> bool:
    """True iff ``mode_or_family`` resolves to BRIEFING_EXECUTION or
    BRIEFING_V5 (direct equality or prefix form like
    ``BRIEFING_EXECUTION_SELL``)."""
    s = str(mode_or_family or "").strip().upper()
    if not s:
        return False
    if s in _BRIEFING_PRIORITY_FAMILIES:
        return True
    for prefix in _BRIEFING_PRIORITY_FAMILIES:
        if s.startswith(prefix + "_"):
            return True
    return False


def _epic_state_is_briefing(k: str, state: dict) -> bool:
    """Does an EPIC_STATE entry belong to the briefing route? Checks
    the ``mode`` / ``family`` fields on the state dict first, then
    falls back to the ``|`` suffix of the pos_key."""
    for field in ("mode", "family", "strategy_family"):
        v = state.get(field)
        if v and _is_briefing_priority_mode(v):
            return True
    if "|" in k:
        return _is_briefing_priority_mode(k.split("|", 1)[1])
    return False


def _autobot_agg_cap_enabled() -> bool:
    """Kill switch. Default: enabled. Independent of EXECUTION_AUTHORITY_FIREWALL_ENABLED."""
    return os.getenv("AUTOBOT_AGGREGATE_POSITION_CAP_ENABLED", "1").strip() != "0"


def _autobot_agg_cap_limit() -> int:
    """Aggregate cap value. Default: 2 per operator ruling 2026-09-29."""
    try:
        v = int(str(os.getenv("AUTOBOT_AGGREGATE_POSITION_CAP", "2") or "2").strip())
    except Exception:
        v = 2
    return max(0, v)


# Max age for a pending_open reservation before it's treated as stale
# (abandoned by a leaked return path). Default 30 seconds — well above
# the normal confirm cycle (ack + ms-latency), below any reasonable
# human reaction time. Env override:
# AUTOBOT_AGG_CAP_PENDING_MAX_AGE_SECS.
def _agg_cap_pending_max_age_secs() -> float:
    try:
        v = float(os.getenv("AUTOBOT_AGG_CAP_PENDING_MAX_AGE_SECS", "30") or "30")
        return v if v > 0 else 30.0
    except Exception:
        return 30.0


def _autobot_agg_cap_count_for_pair(pair_upper: str, *, exclude_pos_key: Optional[str] = None) -> int:
    """Count AutoBot-owned open + genuinely in-flight positions on the
    given pair.

    Counts EPIC_STATE entries whose epic resolves to `pair_upper` AND
    one of:
      * ``active=True`` (confirmed broker position), OR
      * ``pending_open=True`` AND the reservation is FRESH — either
        has a ``dealReference`` present (broker call dispatched) OR a
        ``pending_open_ts`` within
        ``AUTOBOT_AGG_CAP_PENDING_MAX_AGE_SECS`` seconds of now (the
        candidate is between the reservation flip and the broker
        submit).

    Stale ``pending_open`` entries (no dealReference, timestamp older
    than the cap) are treated as abandoned reservations: they are
    neither counted nor cleaned up here (cleanup happens via the
    wrapper's release path). The ``exclude_pos_key`` argument allows
    the caller to exclude the entry it is about to reserve for
    itself.

    MUST be called while EPIC_STATE_LOCK is held to be race-safe with
    the reservation flip a few lines below.
    """
    now = _elm.now_epoch_ms() / 1000.0
    max_age = _agg_cap_pending_max_age_secs()
    briefing_priority = _briefing_priority_enabled()
    count = 0
    for _k, _v in EPIC_STATE.items():
        if exclude_pos_key is not None and _k == exclude_pos_key:
            continue
        if _pair_from_epic(_k.split("|", 1)[0]) != pair_upper:
            continue
        # BRIEFING_PRIORITY (2026-10-06): briefing positions do not count
        # toward other routes' aggregate cap.
        if briefing_priority and _epic_state_is_briefing(_k, _v):
            continue
        # BOUNCE_ENGINE (BUILD_NOTES.md step 3): bounce engine owns its
        # own allowance and must not consume the AutoBot aggregate cap.
        if _bounce_engine_enabled() and _epic_state_is_bounce_engine(_k, _v):
            continue
        if _v.get("active"):
            count += 1
            continue
        if _v.get("pending_open"):
            # Fresh = either a dealReference exists (broker call sent),
            # or the reservation timestamp is within max_age, or the
            # timestamp is MISSING entirely (preserves backward compat
            # with EPIC_STATE snapshots that predate the ts stamp —
            # live code always stamps). STALE only when ts is present
            # AND exceeds max_age.
            if _v.get("dealReference") or _v.get("deal_reference"):
                count += 1
                continue
            ts = _v.get("pending_open_ts")
            if ts is None:
                count += 1  # unknown age → treat as fresh (safe default)
                continue
            try:
                ts_f = float(ts)
            except (TypeError, ValueError):
                count += 1
                continue
            if (now - ts_f) <= max_age:
                count += 1
                continue
            # else: stale pending — don't count.
    return count


def _release_stale_pending_opens(pair_upper: Optional[str] = None) -> int:
    """Clear any ``pending_open`` reservation older than
    AUTOBOT_AGG_CAP_PENDING_MAX_AGE_SECS with no dealReference. Pair-
    scoped when ``pair_upper`` is given; otherwise all pairs. Returns
    the number of entries released. MUST be called under
    EPIC_STATE_LOCK."""
    now = _elm.now_epoch_ms() / 1000.0
    max_age = _agg_cap_pending_max_age_secs()
    released = 0
    for _k, _v in list(EPIC_STATE.items()):
        if pair_upper is not None:
            if _pair_from_epic(_k.split("|", 1)[0]) != pair_upper:
                continue
        if not _v.get("pending_open"):
            continue
        if _v.get("dealReference") or _v.get("deal_reference"):
            continue
        ts = _v.get("pending_open_ts")
        if ts is None:
            # No stamp → cannot measure age; leave the pending as-is.
            # (A code path that forgot to stamp is suspect but the
            # safe default is to preserve the reservation.)
            continue
        try:
            ts_f = float(ts)
        except (TypeError, ValueError):
            continue
        if (now - ts_f) > max_age:
            _v["pending_open"] = False
            _v["pending_open_ts"] = None
            released += 1
    return released


def _autobot_agg_cap_log_refusal(
    *,
    pair: str,
    epic: str,
    family: str,
    source_path: str,
    mode: str,
    side: str,
    candidate_id: str,
    current_count: int,
    cap: int,
) -> None:
    """Durable refusal telemetry — writes logs/autobot_aggregate_position_cap.jsonl + WARN."""
    ts_dt = datetime.now(timezone.utc)
    row = {
        "ts_utc": ts_dt.isoformat(),
        "ts_epoch_ms": int(ts_dt.timestamp() * 1000.0),
        "pair": pair,
        "epic": epic,
        "strategy_family": family,
        "source_path": source_path,
        "mode": mode,
        "side": side,
        "candidate_id": candidate_id,
        "current_autobot_count": current_count,
        "cap": cap,
        "result": "REFUSED",
        "reason": "AGGREGATE_POSITION_CAP",
    }
    try:
        os.makedirs(os.path.dirname(_AUTOBOT_AGG_CAP_LOG), exist_ok=True)
        with open(_AUTOBOT_AGG_CAP_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as exc:
        logger.warning("[AUTOBOT_AGG_CAP] telemetry write failed: %s", exc)
    logger.warning(
        "[AUTOBOT_AGG_CAP] REFUSED pair=%s epic=%s mode=%s family=%s "
        "side=%s current=%d cap=%d reason=AGGREGATE_POSITION_CAP",
        pair, epic, mode or "?", family or "?", side or "?",
        current_count, cap,
    )


# ============================================================
# EXECUTE TRADE
# ============================================================

def execute_trade(decision: Any, epic: str,
                  *, identity_context: Optional[Phase2bIdentityContext] = None):
    # ``identity_context`` is an OPTIONAL, KWARG-ONLY Phase 2B identity
    # envelope constructed by strategy_dispatch_adapter from the
    # orchestrator_v2.submit() Candidate. Legacy callers (NEWS_STRATEGY
    # tick path, tests, direct callers) pass nothing — those fires
    # emit a POSITION_OPEN row with origin=LEGACY_EXTERNAL_BYPASS and
    # candidate_id explicitly null. Argument does NOT alter admission,
    # sizing, stops, targets, or any broker action — telemetry only.
    # Clear the telemetry slot at entry so a previous block can't leak
    # into this call's annotation. Wrappers read via consume_last_block_info().
    _clear_block_info()

    epic = str(epic).strip()

    # ── TRADE_PAIRS seam (Build 2 v2/build2) ─────────────────────────
    # Belt-and-braces reject for pairs not in TRADE_PAIRS. The dispatch
    # adapter (strategy_dispatch_adapter.submit_and_execute_with_
    # disposition:415) already blocks for the Phase-1 shim; this guard
    # covers DIRECT callers that bypass the shim (orchestrator.py:568,
    # regime_router_engine.py:263, and any legacy test harness). Fire
    # before any work — no latency timestamp, no reservation, no
    # candidate_id, no broker call.
    try:
        import pair_scope as _ps
        _pair_check = _pair_from_epic(epic)
        # Family / mode for the BRIEFING carve-out (BRIEFING_TRADE_PAIRS).
        try:
            _tp_family, _tp_source, _tp_mode, _tp_cand_id = _exec_auth_identify(
                decision, identity_context,
            )
        except Exception:
            _tp_family = ""
            _tp_mode = _safe_str(getattr(decision, "mode", None)).strip().upper()
        if _pair_check and not _ps.can_trade(
            _pair_check, family=_tp_family, mode=_tp_mode,
        ):
            logger.info(
                "[execute_trade] TRADE_PAIRS blocked: pair=%s family=%s mode=%s "
                "trade_pairs=%s briefing_trade_pairs=%s — refusing bypass "
                "of dispatch adapter.",
                _pair_check, _tp_family, _tp_mode,
                sorted(_ps.trade_pairs()),
                sorted(_ps.briefing_trade_pairs()),
            )
            _set_block_info(
                "TRADE_PAIRS",
                f"pair={_pair_check} family={_tp_family} mode={_tp_mode} "
                f"not in trade_pairs/briefing_trade_pairs",
            )
            return None
    except Exception as _ps_exc:  # pragma: no cover — defensive
        logger.warning(
            "[execute_trade] pair_scope check failed (allowing fall-through): %s",
            _ps_exc,
        )

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
        _set_block_info("BLANK_EPIC", "epic argument empty")
        return None

    # ------------------------------------------------------------
    # EXECUTION-AUTHORITY FIREWALL — operator ruling 2026-09-29.
    # Placed at the earliest guard slot so no downstream branch can
    # accidentally admit a family the operator has not authorised.
    # Guards ONLY new opens on GBPUSD/EURUSD; close/amend/scale
    # primitives are on separate seams and are not touched.
    # ------------------------------------------------------------
    if _exec_auth_firewall_enabled():
        _fw_pair = _pair_from_epic(epic)
        if _fw_pair in _EXEC_AUTH_GUARDED_PAIRS:
            _fw_family, _fw_source, _fw_mode, _fw_cand_id = _exec_auth_identify(
                decision, identity_context,
            )
            if not _exec_auth_is_permitted(_fw_family, _fw_mode):
                _fw_side = _safe_str(getattr(decision, "signal", None)).strip().upper()
                _exec_auth_log_refusal(
                    pair=_fw_pair,
                    epic=epic,
                    family=_fw_family,
                    source_path=_fw_source,
                    mode=_fw_mode,
                    side=_fw_side,
                    candidate_id=_fw_cand_id,
                )
                _set_block_info(
                    "EXECUTION_AUTHORITY_NOT_PERMITTED",
                    f"family={_fw_family or '?'} mode={_fw_mode or '?'}",
                )
                return None
            # Belt-and-braces (2026-10-06): V2_PICK_BOUNCE mode-prefix
            # or family must respect V2_PICK_BOUNCE_ENABLED. The
            # qm_v2_executor top-level gate also checks it; this
            # catches any dispatch path that bypasses that gate.
            _v2pb_flag = (
                os.getenv("V2_PICK_BOUNCE_ENABLED", "0").strip().lower()
                in ("1", "true", "yes", "on")
            )
            if not _v2pb_flag:
                _fw_mode_u = str(_fw_mode or "").upper()
                _is_v2pb_mode = (
                    _fw_family == "V2_PICK_BOUNCE"
                    or _fw_mode_u == "V2_PICK_BOUNCE"
                    or _fw_mode_u.startswith("V2_PICK_BOUNCE_")
                )
                if _is_v2pb_mode:
                    logger.warning(
                        "[V2_PICK_BOUNCE_FLAG] refusing fire — "
                        "V2_PICK_BOUNCE_ENABLED=0 but family=%s mode=%s",
                        _fw_family, _fw_mode,
                    )
                    _set_block_info(
                        "V2_PICK_BOUNCE_DISABLED",
                        f"V2_PICK_BOUNCE_ENABLED=0 family={_fw_family} mode={_fw_mode}",
                    )
                    return None

    # ------------------------------------------------------------
    # POSITIONS-VISIBILITY SAFETY GATE (2026-10-19 repair).
    #
    # When /positions returns UNKNOWN (continuous HTTP 500 / None), the
    # AUTOBOT_AGGREGATE_POSITION_CAP cannot be checked against the real
    # broker state — the count comes from local EPIC_STATE which may
    # diverge from IG. Opening a new position under this condition can
    # push the broker over its real cap or create ghost positions.
    #
    # The gate is ON by default. Set EXEC_POSITIONS_VISIBILITY_REQUIRED
    # =0 to disable (e.g. a brand-new install with no prior state and
    # intentionally untracked positions on IG).
    #
    # The gate consults close_sb_now.positions_state_visible() which
    # tracks the last successful /positions fetch's age. max_age_s
    # defaults to POSITIONS_VISIBILITY_MAX_AGE_S (default 120s — covers
    # ~12 retry cycles of the 10s external-close sweep plus a safety
    # margin).
    #
    # 2026-10-19 (post-review): fail-CLOSED. If the gate's own code
    # cannot determine broker visibility — import error, exception
    # from the visibility helpers, unexpected return value — refuse
    # the new order. The pre-review fail-OPEN was unsafe: a broken
    # gate silently restored the exact divergence the gate exists to
    # prevent. See block info stage GATE_INTERNAL_ERROR below.
    # ------------------------------------------------------------
    _pv_required = (
        os.getenv("EXEC_POSITIONS_VISIBILITY_REQUIRED", "1").strip() != "0"
    )
    if _pv_required:
        _pv_block_stage: Optional[str] = None
        _pv_block_detail: Optional[str] = None
        _pv_diag_for_log: Dict[str, Any] = {}
        try:
            from close_sb_now import positions_state_visible as _pv_visible
            from close_sb_now import last_fetch_status as _pv_status
            _pv_max_age = float(
                os.getenv("POSITIONS_VISIBILITY_MAX_AGE_S", "120") or 120.0
            )
            _pv_visible_result = _pv_visible(max_age_s=_pv_max_age)
            # Defensive: visibility helper must return a bool. Anything
            # else is an indeterminate state → fail-closed.
            if not isinstance(_pv_visible_result, bool):
                _pv_block_stage = "POSITIONS_VISIBILITY_INDETERMINATE"
                _pv_block_detail = (
                    f"positions_state_visible returned non-bool "
                    f"type={type(_pv_visible_result).__name__!r} "
                    f"value={_pv_visible_result!r}"
                )
                _pv_diag_for_log = _pv_status() if callable(_pv_status) else {}
            elif _pv_visible_result is False:
                _pv_diag_for_log = _pv_status()
                _pv_block_stage = "POSITIONS_VISIBILITY_UNKNOWN"
                _pv_block_detail = (
                    f"state={_pv_diag_for_log.get('state')} "
                    f"http={_pv_diag_for_log.get('http_status')} "
                    f"consecutive_failures={_pv_diag_for_log.get('consecutive_failures')} "
                    f"age_s={_pv_diag_for_log.get('age_s')}"
                )
        except Exception as _pv_exc:
            # Fail-CLOSED (2026-10-19 post-review correction). The
            # exception path previously fell through; it now refuses
            # the submission so a defect in the gate itself cannot
            # restore the exact divergence we are guarding against.
            _pv_block_stage = "POSITIONS_VISIBILITY_GATE_INTERNAL_ERROR"
            _pv_block_detail = (
                f"gate internal error — {type(_pv_exc).__name__}: {_pv_exc}"
            )
            _pv_diag_for_log = {"exception": type(_pv_exc).__name__}

        if _pv_block_stage is not None:
            _pv_pair = _pair_from_epic(epic)
            try:
                _pv_family, _pv_src, _pv_mode, _pv_cand = _exec_auth_identify(
                    decision, identity_context,
                )
            except Exception:
                _pv_family = _pv_src = _pv_mode = _pv_cand = None
            _pv_side = _safe_str(
                getattr(decision, "signal", None)
            ).strip().upper()
            logger.warning(
                "[POSITIONS_VISIBILITY] REFUSING new order — "
                "stage=%s pair=%s family=%s mode=%s side=%s cand=%s "
                "detail=%s diagnostics=%s",
                _pv_block_stage, _pv_pair, _pv_family, _pv_mode,
                _pv_side, _pv_cand, _pv_block_detail, _pv_diag_for_log,
            )
            _set_block_info(_pv_block_stage, _pv_block_detail or "")
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
    # DAY_TIER_MASK / subtype-policy / direction-lock removed
    # 2026-08-21. The drought follow-up audit
    # (reports-public/drought_followups_20260821/REPORT.md) established
    # that mask/latch/fork contributed exactly zero suppression to the
    # 42-run afternoon drought cohort while retaining a 3-tier admit
    # ladder (mask + subtype + latch + fork + direction-lock) whose
    # gating side-effects were opaque and doubly-punitive on
    # BB_BOUNCE / EMA_PB re-arm. The next choke — NEWS_POST_RELEASE
    # lockout — remains authoritative.
    #
    # Nothing in execute_trade reads day_posture.trend_confirmed,
    # day_posture.range_mode, day_posture.latch_direction, or
    # day_posture.day_subtype for any admit/block decision. The
    # posture module still emits its per-day summary telemetry so the
    # signal_log field and the [DAY_POSTURE] Telegram summary keep
    # working; those are label-only.
    # ------------------------------------------------------------

    # ------------------------------------------------------------
    # NEWS POST-RELEASE LOCKOUT (2026-08-07). Central choke-point
    # enforcement for the two-sided release window. Runs BEFORE any
    # other gate so no strategy can bypass it via its own gate stack.
    # See news_release_window.is_in_post_release_lockout — FAIL-CLOSED:
    # missing / stale Finnhub cache → block.
    #
    # EXEMPT: news_strategy.py (NEWS_STRATEGY_FADE / NEWS_STRATEGY_CONT /
    # NEWS_STRATEGY_REVERSAL), news_tick_strategy.py (NEWS_TICK), and
    # news_continuation.py (NEWS_CONT_LEG, added 2026-08-09) — they are
    # the machinery being auditioned to trade the release tape itself and
    # MUST continue evaluating through the window. Extension for NEWS_CONT_LEG
    # is DELIBERATE: that leg IS the vehicle for the post-release breakout
    # (founding case: NFP 2026-08-07 +55p spike, no strategy fired) and
    # therefore must be exempt from the news_release_window fail-closed
    # gate at this choke. If either is ever promoted to enforce-live mode
    # with wider mode names, this prefix list is the single seam to
    # revisit before shipping.
    # ------------------------------------------------------------
    # GBPUSD_LEVEL_BOUNCE (added 2026-08-14) — three-candle level bounce is
    # a structural setup keyed on outer pivots + BB re-entry, not on the
    # release tape. Prior to this exemption, LEVEL_BOUNCE fired its Telegram
    # alert from inside evaluate() and then got suppressed here silently,
    # producing a signal_log/broker mismatch (2026-08-14 14:00 UTC Michigan
    # Consumer Sentiment Prel incident). The Telegram send has been moved
    # post-gate; this exemption restores the strategy's own risk model as
    # the sole entry authority. Prefix "GBPUSD_LEVEL_BOUNCE" matches both
    # _L and _S mode names (see gbpusd_level_bounce.MODE_NAME_LONG/SHORT).
    _NEWS_LOCKOUT_EXEMPT_PREFIXES: Tuple[str, ...] = (
        "NEWS_TICK", "NEWS_STRATEGY", "NEWS_CONT_LEG",
        "GBPUSD_LEVEL_BOUNCE",
    )
    _dir_nl = _safe_str(getattr(decision, "signal", None)).strip().upper()
    if _dir_nl in ("BUY", "SELL") and not mode.startswith(_NEWS_LOCKOUT_EXEMPT_PREFIXES):
        from datetime import datetime as _dt_nl, timezone as _tz_nl
        try:
            from news_release_window import is_in_post_release_lockout
            _nl_blocked, _nl_reason = is_in_post_release_lockout(
                _dt_nl.now(_tz_nl.utc)
            )
        except Exception as _nl_exc:
            _nl_blocked, _nl_reason = False, ""
            logger.debug("[NEWS-LOCKOUT] gate error (fail-open on import): %s", _nl_exc)
        if _nl_blocked:
            _sym_nl = _pair_from_epic(epic)
            _ts_nl = _dt_nl.now(_tz_nl.utc).isoformat()
            logger.warning(
                "[NEWS-LOCKOUT] suppressed %s %s at %s release=%s",
                mode, _dir_nl, _ts_nl, _nl_reason,
            )
            _set_block_info("NEWS_POST_LOCKOUT", str(_nl_reason))
            # BB_BOUNCE labeller — surface the block on the ops
            # channel so the human labelling loop sees the same
            # [LABEL-BLOCKED] prompt it does for any other stand-down.
            if "BB_BOUNCE" in mode:
                try:
                    import bb_bounce_labeller as _bb_labeller
                    _entry_nl = float(getattr(decision, "entry", None) or 0.0)
                    _bb_labeller.enqueue_blocked_prompt(
                        mode=mode,
                        direction=_dir_nl,
                        entry=_entry_nl,
                        fire_ts=_dt_nl.now(_tz_nl.utc),
                        block_reason="news_post_lockout",
                    )
                except Exception as _bb_nl_exc:
                    logger.debug(
                        "[NEWS-LOCKOUT] BB labeller enqueue failed for %s: %s",
                        _sym_nl, _bb_nl_exc,
                    )
            return None

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
    if not _REGIME_MATRIX_ENABLED_TE:
        try: import legacy_call_counter as _lcc; _lcc.log_call("CROSS_BIAS_GATE_ENABLED", __file__)
        except Exception: pass
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
    # BRIEFING_PRIORTY (2026-10-06): briefing trades skip the per-pair
    # concurrency cap. Counts of OTHER routes already exclude briefing
    # positions via count_open_positions_by_pair_direction.
    _briefing_bypass_concurrency = (
        _briefing_priority_enabled() and _is_briefing_priority_mode(mode)
    )
    if (
        _direction_for_cap in ("BUY", "SELL")
        and mode not in _PAIR_CONCURRENCY_BYPASS_MODES
        and not _briefing_bypass_concurrency
    ):
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
    if (
        os.getenv("GBPUSD_ANTIHEDGE_BLOCK_ENABLED", "1") == "1"
        and not (
            _briefing_priority_enabled()
            and _is_briefing_priority_mode(mode)
        )
    ):
        try:
            _ah_pair = _pair_from_epic(epic)
            _ah_dir = _safe_str(getattr(decision, "signal", None)).strip().upper()
            # 2026-10-05 operator ruling: allow one long + one short on
            # GBPUSD (ceiling stays at 2 via the aggregate cap below).
            # Flag default "1" relaxes antihedge for GBPUSD only; set to
            # "0" to restore pre-ruling strict behaviour.
            _ah_relax_gbp = (
                _ah_pair == "GBPUSD"
                and os.getenv(
                    "ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD", "1"
                ).strip() in ("1", "true", "yes", "on")
            )
            if _ah_relax_gbp:
                pass
            elif _ah_pair == "GBPUSD" and _ah_dir in ("BUY", "SELL"):
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

    # ── V1↔V2 JOIN — fire-time snapshot (SHADOW, 2026-09-05) ─────────────
    # Single V2 state snapshot at the SAME seam as entry_hours/coherence.
    # Blocks and fires both re-use this snapshot; nothing here can gate
    # or delay execution. All calls are fail-silent (see qm_join.py).
    _qm_join_snap: Optional[Dict[str, Any]] = None
    try:
        import qm_join as _qm_join
        _qm_join_snap = _qm_join.compute_snapshot(
            epic,
            _safe_str(getattr(decision, "signal", None)).strip().upper() or None,
            mode,
            _to_float_or_none(getattr(decision, "entry", None)),
        )
    except Exception as _qmj_exc:
        logger.debug("[QM-JOIN] fire-time snapshot failed: %s", _qmj_exc)

    # ── QM_ENTRY_HOURS — hard no-new-entries window (2026-09-04 ruling) ───
    # Retires the QM_EARLY half-stake compromise. New entries permitted
    # ONLY when current UTC hour ∈ [QM_ENTRY_HOUR_START, QM_ENTRY_HOUR_END)
    # (defaults 07, 17). Applies to ALL strategy families at this choke
    # point — including the TV3 UM grind path (autobot.py:8234 routes
    # every UM fire through execute_trade). Corpus v3 hour table showed
    # 17:00+ UTC = 33% winrate and falling; two evening UM fires on
    # 2026-09-03 (19:50 / 20:50 UTC) ate 18.5p of a winning day.
    #
    # EXEMPT: NEWS_TICK / NEWS_STRATEGY / NEWS_CONT_LEG — event-driven by
    # design, their own release-window logic governs. GBPUSD_LEVEL_BOUNCE
    # is NOT exempt here (structural, not news).
    #
    # ENTRIES only. Exit/management (close_trade, apply_trailing_stop,
    # monitor_exits, close_position, close_all_positions_for_epic) never
    # routes through this function and is therefore never touched by this
    # gate — an open position past 17 UTC continues to trail/close normally.
    # Kill switch: QM_ENTRY_HOURS_ENABLED=0 (default off; env flips it on).
    # Fail-open — gate errors must never block an otherwise-clean fire.
    if os.getenv("QM_ENTRY_HOURS_ENABLED", "0").strip() in ("1", "true", "yes", "on"):
        try:
            _eh_dir = _safe_str(getattr(decision, "signal", None)).strip().upper()
            _ENTRY_HOURS_EXEMPT_PREFIXES: Tuple[str, ...] = (
                "NEWS_TICK", "NEWS_STRATEGY", "NEWS_CONT_LEG",
            )
            if _eh_dir in ("BUY", "SELL") and not mode.startswith(_ENTRY_HOURS_EXEMPT_PREFIXES):
                _eh_start = int(os.getenv("QM_ENTRY_HOUR_START", "7"))
                _eh_end = int(os.getenv("QM_ENTRY_HOUR_END", "17"))
                from datetime import datetime as _dt_eh, timezone as _tz_eh
                _eh_now = _dt_eh.now(_tz_eh.utc)
                _eh_hour = _eh_now.hour
                if not (_eh_start <= _eh_hour < _eh_end):
                    logger.info(
                        "[ENTRY-HOURS] blocked %s %s %s at %02d UTC — "
                        "window=[%02d,%02d)",
                        mode, _eh_dir, _pair_from_epic(epic), _eh_hour,
                        _eh_start, _eh_end,
                    )
                    try:
                        import json as _json_eh
                        os.makedirs("logs", exist_ok=True)
                        _eh_rec = {
                            "ts": _eh_now.isoformat(),
                            "reason": "entry_hours",
                            "strategy": mode,
                            "pair": _pair_from_epic(epic),
                            "epic": epic,
                            "direction": _eh_dir,
                            "hour_utc": _eh_hour,
                            "window_start": _eh_start,
                            "window_end": _eh_end,
                            "verdict": "BLOCKED",
                        }
                        with open(
                            "logs/entry_hours_blocks.jsonl",
                            "a", encoding="utf-8",
                        ) as _fh_eh:
                            _fh_eh.write(_json_eh.dumps(_eh_rec) + "\n")
                    except Exception as _eh_lexc:
                        logger.debug(
                            "[ENTRY-HOURS] jsonl write failed: %s", _eh_lexc
                        )
                    _set_block_info(
                        "ENTRY_HOURS",
                        (
                            f"hour={_eh_hour:02d} "
                            f"window=[{_eh_start:02d},{_eh_end:02d})"
                        ),
                    )
                    try:
                        import qm_join as _qm_join
                        _qm_join.stamp_block(
                            decision, epic, "ENTRY_HOURS",
                            extra_ctx={
                                "hour_utc": _eh_hour,
                                "window_start": _eh_start,
                                "window_end": _eh_end,
                            },
                        )
                    except Exception as _qjeh:
                        logger.debug("[QM-JOIN] block stamp failed: %s", _qjeh)
                    return None
        except Exception as _eh_exc:
            logger.debug("[ENTRY-HOURS] gate error (fail-open): %s", _eh_exc)

    # ── ONE-BOOK COHERENCE GUARD (2026-09-01 Session B) ───────────────────
    # No strategy may open a position OPPOSITE an existing open position on
    # the SAME epic. Stricter than the GBPUSD_ANTIHEDGE gate above:
    #   - all epics (not GBPUSD-only)
    #   - no PAUSE / eq-extreme requirement (any opposing position blocks)
    #   - no exemptions
    # Same-direction additions unaffected. Kill switch ONE_BOOK_GUARD=0.
    # Fail-open — guard errors must never block an otherwise-clean fire.
    # 2026-10-05 operator ruling: allow one long + one short on GBPUSD so
    # a 1L+1S book is permitted (ceiling still 2 via the aggregate
    # position cap below). Scoped to GBPUSD; all other epics stay strict.
    # Kill switch ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD=0 reverts.
    if (
        os.getenv("ONE_BOOK_GUARD", "1").strip() in ("1", "true", "yes", "on")
        and not (
            _briefing_priority_enabled()
            and _is_briefing_priority_mode(mode)
        )
    ):
        try:
            _cg_relax_gbp = (
                _pair_from_epic(epic) == "GBPUSD"
                and os.getenv(
                    "ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD", "1"
                ).strip() in ("1", "true", "yes", "on")
            )
            _cg_dir = _safe_str(getattr(decision, "signal", None)).strip().upper()
            if _cg_relax_gbp:
                _cg_dir = ""  # skip opposing scan; aggregate cap owns ceiling
            if _cg_dir in ("BUY", "SELL"):
                _cg_opp = "SELL" if _cg_dir == "BUY" else "BUY"
                _cg_hit = None
                with EPIC_STATE_LOCK:
                    _cg_items = list(EPIC_STATE.items())
                for _k, _s in _cg_items:
                    if not (_s.get("active") or _s.get("pending_open")):
                        continue
                    _ep = str(_k).split("|", 1)[0]
                    if _ep != epic:
                        continue
                    _sd = str(_s.get("direction") or "").upper()
                    if _sd != _cg_opp:
                        continue
                    _sm = str(
                        _s.get("mode")
                        or (_k.split("|", 1)[1] if "|" in _k else "")
                    ).upper()
                    _cg_hit = {
                        "mode": _sm or "?",
                        "direction": _sd,
                        "dealId": _s.get("dealId") or _s.get("deal_id") or "",
                        "pos_key": _k,
                    }
                    break
                if _cg_hit is not None:
                    logger.info(
                        "[COHERENCE] blocked %s %s — opposing %s %s open "
                        "(deal %s)",
                        mode, _cg_dir,
                        _cg_hit["mode"], _cg_hit["direction"],
                        _cg_hit["dealId"] or "?",
                    )
                    try:
                        import json as _json_cg
                        from datetime import datetime as _dt_cg, timezone as _tz_cg
                        os.makedirs("logs", exist_ok=True)
                        _cg_rec = {
                            "ts": _dt_cg.now(_tz_cg.utc).isoformat(),
                            "reason": "coherence",
                            "strategy": mode,
                            "pair": _pair_from_epic(epic),
                            "epic": epic,
                            "direction": _cg_dir,
                            "opposite_mode": _cg_hit["mode"],
                            "opposite_direction": _cg_hit["direction"],
                            "opposite_deal_id": str(_cg_hit["dealId"]),
                            "opposite_pos_key": _cg_hit["pos_key"],
                            "verdict": "BLOCKED",
                        }
                        with open(
                            "logs/coherence_blocks.jsonl",
                            "a", encoding="utf-8",
                        ) as _fh_cg:
                            _fh_cg.write(_json_cg.dumps(_cg_rec) + "\n")
                    except Exception as _cg_lexc:
                        logger.debug(
                            "[COHERENCE] jsonl write failed: %s", _cg_lexc
                        )
                    _set_block_info(
                        "COHERENCE",
                        (
                            f"opposite={_cg_hit['mode']}/{_cg_hit['direction']} "
                            f"deal={_cg_hit['dealId']}"
                        ),
                    )
                    try:
                        import qm_join as _qm_join
                        _qm_join.stamp_block(
                            decision, epic, "COHERENCE",
                            extra_ctx={
                                "opposite_mode": _cg_hit["mode"],
                                "opposite_direction": _cg_hit["direction"],
                                "opposite_deal_id": str(_cg_hit["dealId"]),
                            },
                        )
                    except Exception as _qjcg:
                        logger.debug("[QM-JOIN] block stamp failed: %s", _qjcg)
                    return None
        except Exception as _cg_exc:
            logger.debug("[COHERENCE] guard error (fail-open): %s", _cg_exc)

    # ── V1↔V2 JOIN — fire stamp (SHADOW, 2026-09-05) ─────────────────────
    # Fire has passed the fire-time gates that live at this seam. Stamp
    # the pre-computed V2 snapshot onto the join log and, if the verdict
    # is WOULD_KEEP, emit a shadow Telegram pick. Downstream failure
    # paths (invalid signal / entry / RR / sizing) may still short-circuit
    # this record; that is acceptable — the operator's grading step
    # cross-joins to signal_log for real P&L on trades that reached IG.
    try:
        import qm_join as _qm_join
        if _qm_join_snap is not None:
            _qm_join_snap["event"] = "fire"
            # Source-engine attribution (2026-09-07 exam-prep): fires are
            # V1_FIRE_JOIN by construction. Add dedup_hint so the grader
            # can detect V1+V2 multi-source overlaps against the same
            # zone within ±3 5m-buckets.
            _qm_join_snap["source_engine"] = "V1_FIRE_JOIN"
            _fire_dir = (_safe_str(getattr(decision, "signal", None))
                          .strip().upper() or None)
            _fire_zc = None
            try:
                _fire_zc = (_qm_join_snap.get("zone_context") or {}).get("zone_center")
            except Exception:
                _fire_zc = None
            _fire_hint = _qm_join._dedup_hint(  # type: ignore[attr-defined]
                _pair_from_epic(epic), _fire_zc, _fire_dir,
                _qm_join_snap.get("ts") or "",
            )
            if _fire_hint is not None:
                _qm_join_snap["dedup_hint"] = list(_fire_hint)
            _qm_join._write_join_line(_qm_join_snap)  # type: ignore[attr-defined]
            # multi-source link + ring-remember for the fire event.
            try:
                _qm_join._check_and_emit_multi_source_link(  # type: ignore[attr-defined]
                    _fire_hint, "V1_FIRE_JOIN",
                    _qm_join_snap.get("ts") or "",
                )
                _qm_join._remember_source(  # type: ignore[attr-defined]
                    _fire_hint, "V1_FIRE_JOIN",
                    _qm_join_snap.get("ts") or "",
                )
            except Exception:
                pass
            _qm_join._remember_v1_event(  # type: ignore[attr-defined]
                _pair_from_epic(epic),
                _qm_join_snap.get("ts") or "",
                "fire", mode, _fire_dir, None,
            )
            # Stash on decision.debug so signal_logger.log_open can
            # merge the join columns onto the signal_log row. Additive
            # only — no existing debug key is overwritten.
            try:
                _dbg = getattr(decision, "debug", None)
                if isinstance(_dbg, dict):
                    _dbg.setdefault("v2_join", _qm_join_snap)
            except Exception:
                pass
            try:
                _qm_join.emit_v2_keep_pick(
                    _qm_join_snap, decision, epic,
                    _to_float_or_none(getattr(decision, "entry", None)),
                )
            except Exception as _qjp:
                logger.debug("[QM-JOIN] emit pick failed: %s", _qjp)
    except Exception as _qjf:
        logger.debug("[QM-JOIN] fire stamp failed: %s", _qjf)

    pk = _pos_key(epic, mode)

    # ------------------------------------------------------------
    # ATOMIC RESERVATION SITE (Repair 8, 2026-09-29).
    #
    # Under EPIC_STATE_LOCK we perform, atomically:
    #   1. Get/create the pos_key state entry.
    #   2. Existing DUPLICATE_ACTIVE guard (BB_REVERSAL pyramid exception
    #      preserved verbatim).
    #   3. AUTOBOT_AGGREGATE_POSITION_CAP check on guarded pairs
    #      (GBPUSD/EURUSD): count active + pending EPIC_STATE entries for
    #      the pair, refuse when count + 1 would exceed cap.
    #   4. Reservation flip: pending_open = True on our pos_key.
    #
    # Holding the same RLock across (3) and (4) is what makes the cap
    # race-safe (operator §9). Any subsequent AutoBot candidate entering
    # this block will observe our pending_open in step (3)'s count and
    # be refused before it can also open.
    #
    # The rest of execute_trade (SL/TP compute, level_ladder, broker
    # call) runs OUTSIDE the lock so the seam stays fast — the
    # pending_open flip is the load-bearing atomic act.
    # ------------------------------------------------------------
    with EPIC_STATE_LOCK:
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
                # SKIP_BUSY telemetry (2026-10-07): the setup signal is
                # dropped here because this pos_key is already live or
                # has a pending_open reservation. The execute_trade
                # wrapper also writes an execution_rejections.jsonl row
                # with site=DUPLICATE_ACTIVE; this adds the pair /
                # strategy / direction context in a dedicated SKIP_BUSY
                # feed for downstream collision analysis. Fail-silent.
                try:
                    import execution_skips_log as _esl
                    _esl.write_skip(
                        pair=_pair_from_epic(epic),
                        epic=str(epic),
                        strategy=str(mode or ""),
                        direction=_safe_str(
                            getattr(decision, "signal", None)
                        ).strip().upper(),
                        reason=(
                            "position_already_open"
                            if st["active"] else "pending_deal_ledger_in_flight"
                        ),
                        file_line="trade_executor.py:3927",
                        extra={
                            "pos_key": pk,
                            "mode": str(mode or ""),
                            "active": bool(st["active"]),
                            "pending_open": bool(st["pending_open"]),
                        },
                    )
                except Exception:
                    pass
                return None

        # -- AutoBot aggregate position cap ------------------------
        # Repair 8 §4: count all AutoBot-owned open + pending positions
        # on the pair. Cap default is 2 across ONE_STRATEGY,
        # BRIEFING_EXECUTION and V2_PICK_BOUNCE combined (plus any
        # AutoBot position whose family cannot be reconstructed —
        # covered because we do not filter by mode). Pair-scoped:
        # GBPUSD and EURUSD each get their own count.
        #
        # 2026-10-06 fix: _release_stale_pending_opens runs before the
        # count so a leaked pending_open reservation (abandoned by a
        # return path that didn't clear it) can't permanently fill a
        # slot. Fresh reservations (within AUTOBOT_AGG_CAP_PENDING_
        # MAX_AGE_SECS or with a dealReference) still count.
        # BRIEFING_PRIORITY (2026-10-06): briefing trades do not count
        # against — and are not refused by — the aggregate cap. The
        # count itself already excludes briefing positions (see
        # _autobot_agg_cap_count_for_pair), so a briefing position
        # cannot push the cap, and here briefing bypasses the ceiling
        # check entirely.
        _briefing_bypass_agg_cap = (
            _briefing_priority_enabled() and _is_briefing_priority_mode(mode)
        )
        if _autobot_agg_cap_enabled() and not _briefing_bypass_agg_cap:
            _agg_pair = _pair_from_epic(epic)
            if _agg_pair in _AUTOBOT_AGG_CAP_GUARDED_PAIRS:
                _release_stale_pending_opens(_agg_pair)
                _agg_cap = _autobot_agg_cap_limit()
                _agg_current = _autobot_agg_cap_count_for_pair(
                    _agg_pair, exclude_pos_key=pk,
                )
                # 2026-10-19 post-review — ACCOUNT-WIDE EXPOSURE.
                # Add sibling-host positions on the same pair to the
                # effective count. Rationale: autobot's local EPIC_STATE
                # only sees its OWN positions, but the broker enforces
                # account-wide limits. The visibility gate guarantees
                # we have a fresh /positions snapshot at this point.
                # Owned positions are already counted by local
                # EPIC_STATE above; we add only the NET broker-side
                # delta from the fresh snapshot so we don't double-
                # count our own opens.
                _agg_sibling = 0
                try:
                    from close_sb_now import count_broker_positions_for_pair
                    _broker_total = count_broker_positions_for_pair(_agg_pair)
                    if _broker_total is not None and _broker_total > _agg_current:
                        # Difference = sibling / foreign broker opens on
                        # this pair that are NOT reflected in autobot's
                        # local EPIC_STATE. Add them to effective
                        # exposure for the cap decision only — autobot
                        # NEVER manages them (reconcile_open_positions'
                        # sibling-reference guard enforces this).
                        _agg_sibling = _broker_total - _agg_current
                        _agg_current = _broker_total
                except Exception as _agg_exc:
                    # Fail-closed is already enforced by the earlier
                    # positions-visibility gate; a failure here means
                    # the snapshot helper raised. Log and continue with
                    # the owned-only count — not catastrophic because
                    # the visibility gate already proved recent /positions
                    # succeeded.
                    logger.warning(
                        "[AUTOBOT_AGG_CAP] sibling-exposure count failed "
                        "(fallback to owned-only): %s", _agg_exc,
                    )
                if _agg_current + 1 > _agg_cap:
                    _agg_family, _agg_source, _agg_mode, _agg_cand = _exec_auth_identify(
                        decision, identity_context,
                    )
                    _agg_side = _safe_str(getattr(decision, "signal", None)).strip().upper()
                    _autobot_agg_cap_log_refusal(
                        pair=_agg_pair,
                        epic=epic,
                        family=_agg_family,
                        source_path=_agg_source,
                        mode=_agg_mode,
                        side=_agg_side,
                        candidate_id=_agg_cand,
                        current_count=_agg_current,
                        cap=_agg_cap,
                    )
                    _set_block_info(
                        "AGGREGATE_POSITION_CAP",
                        f"pair={_agg_pair} current={_agg_current} "
                        f"(owned+sibling={_agg_sibling}) cap={_agg_cap} "
                        f"mode={_agg_mode or '?'}",
                    )
                    # SKIP_BUSY telemetry (2026-10-07): the setup signal is
                    # dropped because the pair-level AutoBot aggregate cap
                    # is already full. Mirrors the DUPLICATE_ACTIVE write
                    # above; see execution_skips_log for the row schema.
                    try:
                        import execution_skips_log as _esl2
                        _esl2.write_skip(
                            pair=str(_agg_pair),
                            epic=str(epic),
                            strategy=str(_agg_mode or mode or ""),
                            direction=_agg_side,
                            reason="aggregate_position_cap",
                            file_line="trade_executor.py:3966",
                            extra={
                                "family": str(_agg_family or ""),
                                "source": str(_agg_source or ""),
                                "candidate_id": str(_agg_cand or ""),
                                "current": int(_agg_current),
                                "cap": int(_agg_cap),
                            },
                        )
                    except Exception:
                        pass
                    return None

        # Set pending_open immediately to prevent concurrent duplicate submissions.
        # Cleared on success (ACCEPTED), rejection (REJECTED), or timeout.
        # This is also the atomic reservation slot for the aggregate cap
        # above: subsequent AutoBot candidates will see this pending_open
        # in their count.
        st["pending_open"] = True
        st["pending_open_ts"] = _elm.now_epoch_ms() / 1000.0  # agg-cap freshness anchor
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

    # 2026-08-20 level_ladder — for opted-in modes, widen the broker TP so
    # the state machine can run past the strategy's native TP1. Only
    # widens when will_arm() confirms the ladder WILL accept the fire
    # (mode allowed + D1 fresh + pivots available); if the ladder would
    # refuse (e.g. D1 stale), the native TP is preserved and the existing
    # exit stack runs. Inert under the default LADDER_ENABLED=0.
    try:
        import level_ladder as _ll_widen
        from datetime import datetime as _ll_dt, timezone as _ll_tz
        _mode_for_widen = getattr(decision, "mode", None)
        if _mode_for_widen and _ll_widen.will_arm(
            _mode_for_widen, _pair_from_epic(epic), _ll_dt.now(_ll_tz.utc)
        ):
            raw_tp_pips = float(_ll_widen.LADDER_MANAGED_BROKER_TP_PIPS)
            logger.info(
                "[LADDER] tp widened to %.2fp for %s (mode=%s) — "
                "ladder will manage",
                raw_tp_pips, epic, _mode_for_widen,
            )
    except Exception as _ll_widen_exc:
        logger.warning(
            "[LADDER] tp widen check failed (%s) — using native TP", _ll_widen_exc,
        )

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

    # Step 2 (2026-10-28 event-driven redesign):
    # Pre-submit guard consults ONLY the last-known observation of IG's
    # minNormalStopOrLimitDistance for this epic.  No API call here.
    # The observation is populated AFTER a confirmed IG rejection
    # (ATTACHED_ORDER_LEVEL_ERROR) — see the REJECTED branch below.
    # When there is no observation (first boot, after expiry, after
    # operator invalidate), the strategy's stop proceeds UNCHANGED to
    # IG — IG itself is the authoritative check.
    try:
        from ig_dealing_rules import is_known_too_tight as _ig_is_known_too_tight
        _blocked, _obs = _ig_is_known_too_tight(epic, float(sl_pips))
    except Exception as _val_exc:
        _blocked, _obs = (False, None)
        logger.warning(
            "[executor] IG dealing-rules module unavailable (%s: %s) — "
            "submission proceeds without pre-submit guard",
            type(_val_exc).__name__, _val_exc,
        )
    if _blocked and _obs is not None:
        logger.warning(
            "[IG_STOP_PRE_SUBMIT_BLOCK] %s requested=%.2fp "
            "last_known_min=%.2fp observed_at=%d age_s=%.0f — "
            "submission blocked (would be rejected by broker).",
            pair, float(sl_pips), _obs.value_pips,
            int(_obs.retrieved_at), _obs.age_secs,
        )
        _set_block_info(
            epic, "IG_MIN_STOP_KNOWN_TOO_TIGHT",
            f"stop={sl_pips:.2f}p < last_known_min={_obs.value_pips:.2f}p "
            f"(observed {_obs.age_secs:.0f}s ago)",
        )
        return None

    # Step 3 (preserved as safety net for unknown pairs / module failure):
    # The static per-pair IG floor and global SL floor are kept.  For
    # every current GBPUSD strategy the stop exceeds these, so the
    # branches are no-ops.  Operator can lower these via env to permit
    # tighter stops once the live-observation path is proven in production.
    ig_min = _IG_MIN_STOP_PTS.get(pair, MIN_STOP_DISTANCE_PIPS)
    sl_pts = max(sl_pts, ig_min)
    if tp_pts is not None:
        tp_pts = max(tp_pts, ig_min)
    if tp_pts is not None and raw_tp_pts is not None and tp_pts > raw_tp_pts + 1e-6:
        logger.info(
            f"[executor] {pair} TP clamped up by broker min: "
            f"raw={raw_tp_pts / ppp:.1f}p → ig_min={ig_min / ppp:.1f}p "
            f"(strategy intent was {tp_pips:.1f}p)"
        )
    sl_pts = max(sl_pts, MIN_STOP_DISTANCE_PIPS)
    if tp_pts is not None:
        tp_pts = max(tp_pts, MIN_LIMIT_DISTANCE_PIPS)

    # Step 4 (preserved — user-configurable risk floor): per-pair SL
    # default, env-overridable via <PAIR>_MIN_SL_PIPS.  Not a broker
    # rule; a user choice.  Kept unchanged.
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

    # ── QM_CONTEXT weighted-stake bias (2026-08-26 SESSION 2) ─────────────
    # gbpusd_bb_bounce.py sets debug["qm_context_size_factor"] to e.g. 0.5
    # when the STRONG_TREND context consult fires WEIGHTED (fade against a
    # confirmed trend, extra-close confirmation satisfied). The factor is
    # multiplied here so the order actually reaches the broker at the
    # reduced size — a logged-but-unapplied factor is a stub, prohibited.
    try:
        _qm_dbg = getattr(decision, "debug", None) or {}
        _qm_factor = _qm_dbg.get("qm_context_size_factor")
        if _qm_factor is not None:
            _qm_factor_f = float(_qm_factor)
            if 0.0 < _qm_factor_f < 1.0:
                _pre_qm = trade_size
                trade_size = trade_size * _qm_factor_f
                logger.info(
                    "[QM_CONTEXT] weighted stake applied: mode=%s "
                    "factor=%.3f extra_closes=%s size %s → %s",
                    str(getattr(decision, "mode", "") or "").upper(),
                    _qm_factor_f,
                    _qm_dbg.get("qm_context_extra_closes_applied"),
                    _pre_qm, trade_size,
                )
    except Exception as _qm_exc:
        logger.warning(
            "[QM_CONTEXT] weighted-stake bias failed (proceeding at unweighted size): %s",
            _qm_exc,
        )

    # ── D6 EARLY-SESSION FADE WEIGHT (2026-09-01 Session B) ───────────────
    # Fade-book (BB_BOUNCE, LEVEL_BOUNCE) entries with entry bar BEFORE
    # 08:00 UTC join the existing context-weight chain at
    # QM_EARLY_SIZE_FACTOR (default 0.5). Same size-multiplier hook the
    # REFORM 1 chain uses — compounds if REFORM 1 already applied
    # (i.e. multiplied on top of trade_size, whether reduced or full).
    # Reason=early_session. Same defer/confirm ledger row family as
    # REFORM 1 — recorded to bb_bounce_standdown.jsonl on record via
    # the standdown_shadow module the strategies already call. Here at
    # the executor we only apply the SIZE factor; the strategies own
    # the defer decision. Kill switch QM_EARLY_WEIGHT_ENABLED=1.
    # Evidence (corpus v3 hour table, cited in commit message):
    #   07-09 UTC fade win-rate 43-52%   vs   12-14 UTC 67-71%
    try:
        if os.getenv("QM_EARLY_WEIGHT_ENABLED", "1").strip() in (
            "1", "true", "yes", "on",
        ):
            _ew_mode_up = str(getattr(decision, "mode", "") or "").upper()
            _ew_fade_markers = ("BB_BOUNCE", "LEVEL_BOUNCE")
            if any(m in _ew_mode_up for m in _ew_fade_markers):
                # Entry-bar timestamp: strategies stamp decision.debug
                # ["entry_bar_ts"] (BB_BOUNCE / LEVEL_BOUNCE do); fallback
                # to decision.entry_bar_ts, then to now (UTC).
                from datetime import datetime as _ew_dt, timezone as _ew_tz
                _ew_dbg = getattr(decision, "debug", None) or {}
                _ew_ts = (
                    _ew_dbg.get("entry_bar_ts")
                    or getattr(decision, "entry_bar_ts", None)
                )
                _ew_ts_utc = None
                if _ew_ts is not None:
                    try:
                        if hasattr(_ew_ts, "astimezone"):
                            _ew_ts_utc = _ew_ts.astimezone(_ew_tz.utc)
                        else:
                            _ew_ts_utc = _ew_dt.fromisoformat(
                                str(_ew_ts).replace("Z", "+00:00")
                            )
                            if _ew_ts_utc.tzinfo is None:
                                _ew_ts_utc = _ew_ts_utc.replace(
                                    tzinfo=_ew_tz.utc,
                                )
                            else:
                                _ew_ts_utc = _ew_ts_utc.astimezone(_ew_tz.utc)
                    except Exception:
                        _ew_ts_utc = None
                if _ew_ts_utc is None:
                    _ew_ts_utc = _ew_dt.now(_ew_tz.utc)
                if _ew_ts_utc.hour < 8:
                    _ew_factor = float(
                        os.getenv("QM_EARLY_SIZE_FACTOR", "0.5") or 0.5
                    )
                    if 0.0 < _ew_factor < 1.0:
                        _pre_ew = trade_size
                        trade_size = trade_size * _ew_factor
                        logger.info(
                            "[QM_EARLY] early-session fade weight applied: "
                            "mode=%s entry_bar_utc=%s hour=%d factor=%.3f "
                            "reason=early_session size %s → %s",
                            _ew_mode_up,
                            _ew_ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            _ew_ts_utc.hour,
                            _ew_factor, _pre_ew, trade_size,
                        )
    except Exception as _ew_exc:
        logger.warning(
            "[QM_EARLY] early-session weight failed "
            "(proceeding at unweighted size): %s",
            _ew_exc,
        )

    # ── DAY_CTX bounce half-size bias (2026-08-22) ────────────────────────
    # On BIG_NEWS days, if this fire is a bounce-family strategy AND lands
    # within ±DAY_CTX_BOUNCE_HALF_SIZE_WINDOW_MIN of a listed TIER1
    # release, size at 50%. A BIAS, never a block — the fire proceeds
    # regardless. Kill switch DAY_CTX_BOUNCE_HALF_SIZE=0 (default) leaves
    # sizing byte-identical.
    try:
        if os.getenv("DAY_CTX_BOUNCE_HALF_SIZE", "0").strip() in ("1", "true", "yes", "on"):
            _mode_up = str(getattr(decision, "mode", "") or "").upper()
            # Bounce-family = anything with BB_BOUNCE, BB_REV, LEVEL_BOUNCE,
            # REVERSAL_SWEEP, RANGE_REVERSION, or BB_REVERSAL in the mode
            # string. Kept conservative — trend-family (TREND_V3,
            # EMA_PULLBACK, STRUCTURE_BREAK) untouched.
            _bounce_markers = (
                "BB_BOUNCE", "BB_REV", "LEVEL_BOUNCE", "REVERSAL_SWEEP",
                "RANGE_REVERSION", "BB_REVERSAL",
            )
            if any(m in _mode_up for m in _bounce_markers):
                import day_context as _dc_hs
                from datetime import datetime as _dc_dt, timezone as _dc_tz
                _now = _dc_dt.now(_dc_tz.utc)
                if _dc_hs.label(_now) == _dc_hs.LABEL_BIG_NEWS:
                    _win = int(os.getenv("DAY_CTX_BOUNCE_HALF_SIZE_WINDOW_MIN", "45"))
                    if _dc_hs.within_release_window(_now, _win):
                        _pre = trade_size
                        trade_size = trade_size * 0.5
                        logger.info(
                            "[DAY_CTX] bounce half-size bias applied: mode=%s "
                            "size %s → %s (window=±%dmin)",
                            _mode_up, _pre, trade_size, _win,
                        )
    except Exception as _hs_exc:
        # Bias failure must NEVER block the fire — log and proceed.
        logger.warning(
            "[DAY_CTX] bounce half-size bias failed (proceeding at full size): %s",
            _hs_exc,
        )

    # ── Execution-latency: IG REST request boundary ───────────────────────
    _t_ig_request = _elm.now_epoch_ms()
    try:
        result = open_sb_now(
            direction=direction,
            epic=epic,
            size=trade_size,
            limit_distance=limit_distance,
            stop_distance=stop_distance,
            # Embed the strategy mode in the dealReference so reconcile
            # on this host and on any sibling bot can tell our positions
            # from theirs on a shared IG account.
            mode=str(st.get("mode") or mode or "DEFAULT"),
        )
    except Exception as _ose:
        st["pending_open"] = False
        _sync_legacy_trade_state_from(st)
        logger.exception(f"❌ Order submission failed for {epic}")
        _set_block_info("ORDER_SUBMISSION_ERROR", f"{type(_ose).__name__}: {_ose}")
        return None
    # IG REST ack — synchronous response containing dealReference.
    _t_ig_ack = _elm.now_epoch_ms()

    if not isinstance(result, dict):
        st["pending_open"] = False
        _sync_legacy_trade_state_from(st)
        logger.error(f"❌ Unexpected order result type for {epic}: {type(result).__name__}")
        _set_block_info("UNEXPECTED_ORDER_RESULT", f"result_type={type(result).__name__}")
        return None

    deal_reference = result.get("dealReference")

    if not deal_reference:
        st["pending_open"] = False
        _sync_legacy_trade_state_from(st)
        logger.error("❌ Missing dealReference from IG")
        _set_block_info("MISSING_DEAL_REFERENCE", "IG returned no dealReference")
        return None

    # ── Durable pending-confirmation record (2026-09-30 repair). ─────
    # IG has acknowledged the OTC POST with a valid dealReference.
    # Persist this BEFORE any /confirms polling so a temporary
    # confirmation failure (or a process death mid-flow) cannot lose
    # durable knowledge that IG accepted the submission. The pending
    # ledger becomes the exact-identity anchor for duplicate safety,
    # restart recovery, and the ACCEPTED / REJECTED / UNRESOLVED
    # terminals below. Fail-permissive on I/O — a disk error must
    # never block a live IG-acknowledged fill from resolving.
    try:
        import pending_deal_ledger as _pdl
        _pdl_event_id = getattr(decision, "thesis_stage9_event_id", None)
        _pdl_interaction_id = getattr(decision, "thesis_interaction_id", None)
        _pdl_proposal_id = (
            getattr(decision, "proposal_id", None)
            or getattr(identity_context, "candidate_id", None)
        )
        _pdl.record_pending(
            deal_reference=str(deal_reference),
            pair=_pair_from_epic(epic),
            epic=epic,
            side=str(direction or "").upper(),
            strategy_family=str(st.get("mode") or mode or ""),
            event_id=_pdl_event_id,
            proposal_id=_pdl_proposal_id,
            interaction_id=_pdl_interaction_id,
            size=trade_size,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
        )
    except Exception as _pdl_exc:
        logger.warning(
            "[PENDING_DEAL] record_pending failed for %s ref=%s: %s",
            epic, deal_reference, _pdl_exc,
        )

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
        _set_block_info("SESSION_ACQUIRE_FAILED", f"{type(e).__name__}: {e}")
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
                # Pending-confirmation ledger: terminal ACCEPTED (2026-09-30).
                try:
                    import pending_deal_ledger as _pdl_acc
                    _pdl_acc.mark_accepted(
                        str(deal_reference),
                        deal_id=str(conf.get("dealId") or ""),
                        resolution_source="confirms",
                    )
                except Exception as _pdl_acc_exc:
                    logger.warning(
                        "[PENDING_DEAL] mark_accepted failed for ref=%s: %s",
                        deal_reference, _pdl_acc_exc,
                    )
                # Snapshot original_size so post-scale state can distinguish
                # "ran from size N" vs "ran from size N/2 after scale-out".
                # Used by _on_trade_close to compute total_pnl_pips correctly.
                st["original_size"] = trade_size
                st["open_time"] = time.time()
                # Repair 3 (2026-09-29) — stamp ONE_STRATEGY thesis
                # identity onto EPIC_STATE so one_strategy_management
                # (Stage 12) can later read back the ORIGINAL Stage 9
                # event / interaction that authorised this position.
                # decision.thesis_* is populated by one_strategy_
                # emitter._OneStrategyDecision; other families leave
                # these attributes unset (getattr → None) so this is a
                # ONE_STRATEGY-only side effect. Metadata only — the
                # broker / firewall / gate do not consume these fields.
                if str(st.get("mode") or "").upper() == "ONE_STRATEGY":
                    _os_thesis_event_id = getattr(
                        decision, "thesis_stage9_event_id", None,
                    )
                    st["one_strategy_thesis"] = {
                        "stage9_event_id": _os_thesis_event_id,
                        "interaction_id": getattr(
                            decision, "thesis_interaction_id", None,
                        ),
                        "direction": getattr(
                            decision, "thesis_direction", None,
                        ),
                        "established_at": getattr(
                            decision, "thesis_established_at", None,
                        ),
                        "entry_price": confirmed_level,
                        "entry_ts_utc": datetime.now(timezone.utc).isoformat(),
                        # Repair 6 (2026-09-29) — the thesis originated
                        # in the current process; recovery is not
                        # required until a restart resurrects the
                        # position via reconcile_open_positions().
                        "recovery_state": "LIVE_ORIGIN",
                        # D7.1 (2026-10-05) — governing-swing identity
                        # captured at entry. Fixed thesis_identity
                        # (A17.1 hash) + mutable stored_governing_swing_*
                        # that one_strategy_management may trail forward
                        # only on later confirmed swings in the
                        # position's direction.
                        "thesis_identity": getattr(
                            decision, "thesis_identity", None,
                        ),
                        "stored_governing_swing_price": getattr(
                            decision, "thesis_governing_swing_price", None,
                        ),
                        "stored_governing_swing_ts": getattr(
                            decision, "thesis_governing_swing_ts", None,
                        ),
                    }
                    # Repair 6 (2026-09-29) — persist the deal_id → thesis
                    # linkage into one_strategy_event_ledger so a post-
                    # restart reconcile_open_positions() can rehydrate
                    # this thesis onto EPIC_STATE. Fail-permissive by
                    # design: ledger disk errors must never block a
                    # confirmed live fill from becoming active.
                    _os_dealid = conf.get("dealId")
                    if _os_thesis_event_id and _os_dealid:
                        try:
                            import one_strategy_event_ledger as _os_ledger
                            _os_ledger.update_deal_id(
                                str(_os_thesis_event_id), str(_os_dealid),
                            )
                        except Exception as _os_ledger_exc:
                            logger.warning(
                                "[ONE_STRATEGY_LEDGER] deal_id linkage failed"
                                " event_id=%s deal_id=%s: %s",
                                _os_thesis_event_id, _os_dealid,
                                _os_ledger_exc,
                            )
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

                # Phase 2B — emit POSITION_OPEN measurement row on the
                # confirmed-fill seam. Fail-silent, telemetry-only,
                # inert unless PHASE2B_MEASUREMENT_ENABLED=1. When the
                # dispatch adapter supplied a Phase2bIdentityContext,
                # the original candidate identity flows through
                # unchanged; otherwise the row is stamped
                # origin=LEGACY_EXTERNAL_BYPASS with candidate_id=null.
                #
                # Timestamp semantics (see phase2b_item3 §3.4 amendment):
                #   * confirmation_received_at_epoch_ms — LOCAL wall
                #     clock at /confirms return (_t_ig_confirm). NOT a
                #     broker open time.
                #   * broker_open_time_epoch_ms — broker-supplied deal
                #     timestamp, parsed from ``conf['date']`` if the
                #     accepted /confirms body carried one. Left null
                #     when the broker did not supply one.
                #
                # dealReference:
                #   * Client-generated, uploaded to IG.
                #   * IG's accepted /confirms body echoes the same
                #     reference. Detect equality below and record it
                #     as CLIENT_GENERATED_BROKER_CORRELATED.
                _echoed_ref = None
                try:
                    _echoed_ref = (
                        str(conf.get("dealReference") or "").strip() == str(
                            deal_reference or ""
                        ).strip()
                        and bool(deal_reference)
                    )
                except Exception:
                    _echoed_ref = None
                _broker_open_ms = None
                try:
                    from datetime import datetime as _dt_conf, timezone as _tz_conf
                    _raw_date = conf.get("date") or conf.get("dateUtc")
                    if _raw_date:
                        _dstr = str(_raw_date).replace("Z", "+00:00")
                        _parsed = _dt_conf.fromisoformat(_dstr)
                        if _parsed.tzinfo is None:
                            _parsed = _parsed.replace(tzinfo=_tz_conf.utc)
                        _broker_open_ms = int(_parsed.timestamp() * 1000)
                except Exception:
                    _broker_open_ms = None
                _emit_phase2b_position_open(
                    st=st, decision=decision, epic=epic, direction=direction,
                    trade_size=trade_size, sl_pips=sl_pips, tp_pips=tp_pips,
                    deal_id=conf.get("dealId"),
                    deal_reference=deal_reference,
                    deal_reference_broker_echoed=_echoed_ref,
                    confirmation_received_at_epoch_ms=_t_ig_confirm,
                    broker_open_time_epoch_ms=_broker_open_ms,
                    local_position_key=pk,
                    identity_context=identity_context,
                )

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

                # 2026-08-20 level_ladder — arm state machine for opted-in
                # modes. Refusal (D1 stale / pivots missing / no rungs
                # beyond entry) is loud in logs and falls back to the
                # existing exit stack. Inert under default LADDER_ENABLED=0.
                #
                # 2026-08-22 TIERED_RATCHET routing: consult exit_dress
                # BEFORE the ladder arm. If the resolved bracket is
                # TIERED_RATCHET, arm that stack instead; the ladder
                # arm is skipped for this pos_key so both stacks never
                # own the same position. For all other brackets
                # (MANAGED / LADDER_STANDARD / LADDER_PATIENT / UM_WIDE)
                # the ladder arm proceeds unchanged — dress overlays are
                # applied inside level_ladder.arm() as before.
                try:
                    import exit_dress as _ed_arm
                    _mode_arm = str(st.get("mode") or "")
                    try:
                        import day_context as _dc_arm
                        _day_ctx_arm = _dc_arm.label()
                    except Exception:
                        _day_ctx_arm = "CLEAR"
                    _bracket_arm = _ed_arm.resolve(_mode_arm, _day_ctx_arm)
                except Exception as _ed_arm_exc:
                    logger.debug(
                        "[LADDER] exit_dress read failed (fall back to "
                        "LADDER_STANDARD): %s", _ed_arm_exc,
                    )
                    _bracket_arm = "LADDER_STANDARD"

                if _bracket_arm == "TIERED_RATCHET":
                    try:
                        import tiered_ratchet as _tr_arm
                        from datetime import datetime as _tr_dt, timezone as _tr_tz
                        _tr_arm.arm(
                            pos_key=pk,
                            mode=_mode_arm,
                            direction=direction,
                            symbol=_pair_from_epic(epic),
                            entry_ts=_tr_dt.now(_tr_tz.utc),
                            entry_price=float(st.get("entry_price") or 0.0),
                            deal_id=st.get("dealId") or st.get("deal_id"),
                        )
                        logger.info(
                            "[RATCHET] armed via exit_dress pos_key=%s mode=%s "
                            "day_ctx=%s", pk, _mode_arm, _day_ctx_arm,
                        )
                        # 2026-08-22 ruling (Item 6). The ratchet arm above
                        # ONLY installs the software stop. The broker-side
                        # SL is whatever the strategy's execute_trade path
                        # set (typically the mode's decision.sl — which can
                        # be wider than RATCHET_INIT_SL_PIPS). Install a
                        # broker SL at entry ± RATCHET_INIT_SL_PIPS so a
                        # catastrophic autobot-death has protection at the
                        # ratchet's own init level. The software close-
                        # beyond-stop stays as-is on top. Fails open — if
                        # the amend raises the position keeps whatever
                        # broker SL execute_trade already set.
                        try:
                            _tr_init_sl_pips = float(
                                _tr_arm.RATCHET_INIT_SL_PIPS_DEFAULT
                            )
                            _tr_entry_arm = float(st.get("entry_price") or 0.0)
                            _tr_pip_arm   = float(st.get("pip_size") or 1.0)
                            _tr_dir_arm   = str(direction or "").upper()
                            # 2026-08-22 fix (Item 2). The original block
                            # read `float(st.get("tp") or 0.0)` and passed
                            # `current_tp_price = entry ± 0*pip = entry` to
                            # `_amend_broker_sl` when tp was absent/zero —
                            # which sets a broker limit AT entry price that
                            # triggers immediately on any fill. Refuse to
                            # amend without a real tp: software stop stays
                            # active, broker keeps the SL execute_trade set.
                            _tr_tp_pips_arm = float(st.get("tp") or 0.0)
                            _tr_existing_sl_pips = float(st.get("sl") or 0.0)
                            _tr_install, _tr_guard_reason = (
                                _ratchet_arm_should_install_broker_sl(
                                    _tr_tp_pips_arm,
                                    _tr_existing_sl_pips,
                                    _tr_init_sl_pips,
                                )
                            )
                            if not _tr_install:
                                if _tr_guard_reason == "tp_absent":
                                    logger.warning(
                                        "[RATCHET] broker SL install on arm "
                                        "SKIPPED for %s: tp absent/zero — "
                                        "cannot issue a stop-only PUT via "
                                        "_amend_broker_sl without also sending "
                                        "a limit; software stop still active, "
                                        "broker retains prior SL",
                                        pk,
                                    )
                                elif _tr_guard_reason == "already_inside":
                                    logger.info(
                                        "[RATCHET] broker SL install on arm "
                                        "SKIPPED for %s: existing broker SL "
                                        "(%.1fp) already inside "
                                        "RATCHET_INIT_SL_PIPS (%.1fp) — leave "
                                        "as-is",
                                        pk, _tr_existing_sl_pips,
                                        _tr_init_sl_pips,
                                    )
                                raise _RatchetArmSkip(_tr_guard_reason)
                            if _tr_dir_arm == "BUY":
                                _tr_sl_price = _tr_entry_arm - _tr_init_sl_pips * _tr_pip_arm
                                _tr_tp_price = _tr_entry_arm + _tr_tp_pips_arm * _tr_pip_arm
                            else:
                                _tr_sl_price = _tr_entry_arm + _tr_init_sl_pips * _tr_pip_arm
                                _tr_tp_price = _tr_entry_arm - _tr_tp_pips_arm * _tr_pip_arm
                            from trade_manager import _amend_broker_sl as _tr_amend_arm
                            _tr_amend_arm(
                                pk,
                                new_sl_price=float(_tr_sl_price),
                                current_tp_price=float(_tr_tp_price),
                            )
                            logger.info(
                                "[RATCHET] broker SL installed on arm "
                                "pos_key=%s dir=%s init_sl=%.1fp sl_price=%.5f "
                                "tp_pips=%.1f",
                                pk, _tr_dir_arm, _tr_init_sl_pips,
                                _tr_sl_price, _tr_tp_pips_arm,
                            )
                        except _RatchetArmSkip:
                            pass
                        except Exception as _tr_bsl_exc:
                            logger.warning(
                                "[RATCHET] broker SL install on arm failed "
                                "for %s: %s — software stop still active, "
                                "broker retains prior SL from execute_trade",
                                pk, _tr_bsl_exc,
                            )
                    except Exception as _tr_arm_exc:
                        logger.warning(
                            "[RATCHET] arm dispatch failed for %s: %s — "
                            "position runs the existing exit stack",
                            pk, _tr_arm_exc,
                        )
                else:
                    try:
                        import level_ladder as _ll_arm
                        from datetime import datetime as _ll_arm_dt, timezone as _ll_arm_tz
                        _ll_arm.arm(
                            pos_key=pk,
                            mode=_mode_arm,
                            direction=direction,
                            symbol=_pair_from_epic(epic),
                            entry_ts=_ll_arm_dt.now(_ll_arm_tz.utc),
                            entry_price=float(st.get("entry_price") or 0.0),
                            deal_id=st.get("dealId") or st.get("deal_id"),
                        )
                    except Exception as _ll_arm_exc:
                        logger.warning(
                            "[LADDER] arm dispatch failed for %s: %s — position "
                            "runs the existing exit stack", pk, _ll_arm_exc,
                        )

                return st

            if status == "REJECTED":
                st["pending_open"] = False
                st["close_reason"] = "trade_rejected"
                _sync_legacy_trade_state_from(st)
                detail = _extract_rejection_detail(conf)
                # 2026-10-28 event-driven refresh (brief §5-§8):
                # Only ATTACHED_ORDER_LEVEL_ERROR triggers a dealing-rules
                # fetch.  Other rejection reasons do NOT poll IG.  The
                # observer records (value, unit, retrieval_time) and uses
                # it to BLOCK subsequent submissions with stops known to
                # be too small.  No auto-widen, no auto-resubmit — the
                # strategy sees the explicit outcome below.
                if "ATTACHED_ORDER_LEVEL_ERROR" in str(detail or "").upper():
                    try:
                        from ig_dealing_rules import record_rejection as _dr_rec
                        _dr_rec(epic, _pair_from_epic(epic))
                    except Exception as _dr_exc:
                        logger.warning(
                            "[IG_MIN_STOP_RECORD] %s record_rejection failed: %s",
                            epic, _dr_exc,
                        )
                # Pending-confirmation ledger: terminal REJECTED (2026-09-30).
                try:
                    import pending_deal_ledger as _pdl_rej
                    _pdl_rej.mark_rejected(
                        str(deal_reference),
                        reason=(detail or "REJECTED"),
                        resolution_source="confirms",
                    )
                except Exception as _pdl_rej_exc:
                    logger.warning(
                        "[PENDING_DEAL] mark_rejected failed for ref=%s: %s",
                        deal_reference, _pdl_rej_exc,
                    )
                logger.error(f"❌ Trade REJECTED for {epic} {detail}".strip())
                _set_block_info("BROKER_REJECTED", (detail or "REJECTED"))
                return None

            time.sleep(CONFIRM_SLEEP_SECS)

    except Exception as e:
        st["pending_open"] = False
        st["close_reason"] = f"confirmation_flow_exception:{type(e).__name__}"
        _sync_legacy_trade_state_from(st)
        logger.error(f"❌ Unexpected confirmation-flow error for {epic}: {type(e).__name__}: {e}")
        _set_block_info("CONFIRMATION_FLOW_EXCEPTION", f"{type(e).__name__}: {e}")
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
                # 2026-09-30 repair — exact dealReference match ONLY. The
                # prior ``_p_epic == epic`` branch adopted any open on the
                # same epic (fuzzy attribution) which could inherit a
                # sibling / foreign position under the pending-confirmation
                # invariant. Ownership requires the exact broker reference
                # AutoBot uploaded; PENDING_CONFIRMATION otherwise survives
                # into restart recovery below.
                if _p_deal_ref and _p_deal_ref == deal_reference:
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
                    # Pending-confirmation ledger: exact-reference recovery
                    # via /positions read matched our dealReference. Terminal
                    # ACCEPTED with the broker dealId now known.
                    try:
                        import pending_deal_ledger as _pdl_posrec
                        _pdl_posrec.mark_accepted(
                            str(deal_reference),
                            deal_id=str(_p_deal_id or ""),
                            resolution_source="positions_after_timeout",
                        )
                    except Exception as _pdl_posrec_exc:
                        logger.warning(
                            "[PENDING_DEAL] mark_accepted (positions) failed "
                            "for ref=%s: %s",
                            deal_reference, _pdl_posrec_exc,
                        )
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
                    _p_deal_ref_r = str(_pos.get("dealReference") or "").strip()
                    # 2026-09-30 repair — exact dealReference match ONLY.
                    if _p_deal_ref_r and _p_deal_ref_r == deal_reference:
                        _t_ig_confirm = _elm.now_epoch_ms()
                        confirmed_level = _to_float_or_none(
                            _pos.get("openLevel") or _pos.get("level")
                        )
                        _p_deal_id = str(_pos.get("dealId") or "").strip()
                        # Pending-confirmation ledger: exact-reference retry
                        # recovery. Terminal ACCEPTED with broker dealId.
                        try:
                            import pending_deal_ledger as _pdl_retry
                            _pdl_retry.mark_accepted(
                                str(deal_reference),
                                deal_id=str(_p_deal_id or ""),
                                resolution_source="positions_retry_after_timeout",
                            )
                        except Exception as _pdl_retry_exc:
                            logger.warning(
                                "[PENDING_DEAL] mark_accepted (retry) failed "
                                "for ref=%s: %s",
                                deal_reference, _pdl_retry_exc,
                            )
                        st["active"] = True
                        st["pending_open"] = False
                        st["dealReference"] = deal_reference
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
    _set_block_info("CONFIRMATION_TIMEOUT", f"dealRef={deal_reference}")

    # 2026-09-30 repair — the pending_deal_ledger record persisted at the
    # IG-ack seam above is DELIBERATELY left in PENDING_CONFIRMATION
    # here. IG has acknowledged the dealReference; we have not yet
    # obtained an exact broker outcome. Restart recovery will re-check
    # the reference on next boot (autobot.py hook) and duplicate safety
    # (one_strategy_emitter) treats the reference as unresolved so the
    # same event will not resubmit. Do NOT infer a rejection here.
    logger.critical(
        f"❌ CRITICAL: Trade confirmation timeout for {epic} "
        f"dealReference={deal_reference} — no matching position found after 3 checks. "
        f"MANUAL CHECK REQUIRED on IG platform. "
        f"pending_deal_ledger retains PENDING_CONFIRMATION for exact-reference recovery."
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

    # Stamp bid / offer so amend-time preflight can validate a proposed
    # stop against the authoritative price side. See trade_manager
    # _sl_amend_preflight_min_distance (2026-09-14 review, blocker 3).
    try:
        if bid is not None:
            st["last_bid"] = float(bid)
    except Exception:
        pass
    try:
        if ask is not None:
            st["last_ask"] = float(ask)
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
        # Best-effort surface of the caller's intended reason so the
        # close-intent journal row carries useful context (path label +
        # expected_reason). See close_intent_journal.record_intent.
        _intent_reason = str(st.get("close_reason") or "").strip()
        try:
            if deal_id:
                close_resp = close_by_deal_id(
                    deal_id,
                    intent_path="close_trade",
                    intent_reason=_intent_reason,
                )
            else:
                # Epic-only fallback would close WHATEVER single position
                # happens to sit on this epic — including a sibling bot's
                # if we share the IG account. Refuse: log, Telegram-alert
                # the operator, mark the EPIC_STATE entry inactive so we
                # stop re-driving the close, and return None.
                logger.error(
                    "[OWNERSHIP] refused epic-only close pos_key=%s epic=%s "
                    "reason=%s — EPIC_STATE has no deal_id for this entry; "
                    "an epic-wide close would act on a position this process "
                    "did not open.",
                    pos_key, epic, _intent_reason or "unspecified",
                )
                try:
                    from telegram_alerts import send_telegram_message
                    send_telegram_message(
                        f"⚠️ [OWNERSHIP] refused epic-only close "
                        f"pos_key=`{pos_key}` epic=`{epic}` "
                        f"reason=`{_intent_reason or 'unspecified'}` — "
                        f"EPIC_STATE lost deal_id; close suppressed to avoid "
                        f"touching a sibling bot's position."
                    )
                except Exception as _tg_exc:
                    logger.warning(
                        "[OWNERSHIP] telegram alert for refused epic-only "
                        "close failed: %s", _tg_exc,
                    )
                with EPIC_STATE_LOCK:
                    st["active"] = False
                    st["_closing_in_flight"] = False
                    st["close_refused_reason"] = "ownership_epic_only_refused"
                    _sync_legacy_trade_state_from(st)
                return None
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

        # 2026-08-20 level_ladder — clean up ladder state on close. Idempotent;
        # no-op if the position was never ladder-managed.
        try:
            import level_ladder as _ll_close
            _ll_close.on_position_closed(
                pos_key=pos_key,
                close_reason=_close_reason_str,
                close_price=exit_p,
                pnl_pips=pnl_pips,
            )
        except Exception as _ll_close_exc:
            logger.warning("[LADDER] on_position_closed failed for %s: %s",
                           pos_key, _ll_close_exc)

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


def resolve_pending_deal_confirmations() -> Tuple[int, int, int, int]:
    """Restart-recovery hook (2026-09-30 repair; closure 2026-09-30).

    Iterate every PENDING_CONFIRMATION record in ``pending_deal_ledger``
    and try to resolve each via the exact broker reference. Uses IG's
    ``fetch_deal_by_deal_reference`` — the same authoritative endpoint
    the confirmed-fill seam uses. No fuzzy inference.

    Terminal outcomes update the ledger:
      * dealStatus == ACCEPTED with a broker dealId → mark_accepted
        (resolution_source="restart_confirms").
      * dealStatus == REJECTED                      → mark_rejected
        (resolution_source="restart_confirms").
      * /confirms unresolved AND get_open_positions() carries a
        position whose ``dealReference`` == the pending record's
        ``deal_reference`` AND that position exposes a real ``dealId``
        → mark_accepted (resolution_source="restart_positions_
        exact_reference"). This closes the gap where IG's confirmation
        endpoint stays 404 but the position itself is already visible;
        the exact-reference identity relationship is still the only
        thing that grants ownership. No fuzzy pair / direction / size /
        SL / TP / price inference — mismatched dealReference means
        FOREIGN.
      * anything else → leave PENDING for a subsequent restart to
        retry.

    Must be called BEFORE reconcile_open_positions() so a delayed
    position that appears in IG becomes ledger-attested (ACCEPTED with
    dealId) and is then recognised as own-deals by the reconciler
    through the pending_deal_ledger ownership source.

    Returns (checked, accepted, rejected, still_pending). Fail-permissive:
    any exception in the loop leaves that record's state unchanged.
    """
    try:
        import pending_deal_ledger as _pdl
    except Exception as _pdl_imp:
        logger.warning(
            "[PENDING_DEAL_RESOLVE] pending_deal_ledger import failed: %s",
            _pdl_imp,
        )
        return (0, 0, 0, 0)

    try:
        unresolved = _pdl.list_unresolved()
    except Exception as _list_exc:
        logger.warning(
            "[PENDING_DEAL_RESOLVE] list_unresolved failed: %s", _list_exc,
        )
        return (0, 0, 0, 0)

    if not unresolved:
        logger.info("[PENDING_DEAL_RESOLVE] No pending confirmations to resolve.")
        return (0, 0, 0, 0)

    # Acquire the IG session ONCE for the whole batch.
    ig = None
    try:
        session_obj = get_ig_session()
        if isinstance(session_obj, (tuple, list)) and session_obj:
            ig = session_obj[0]
    except Exception as _sess_exc:
        logger.warning(
            "[PENDING_DEAL_RESOLVE] IG session acquire failed: %s — leaving "
            "%d pending record(s) unresolved for a later restart.",
            _sess_exc, len(unresolved),
        )
        return (len(unresolved), 0, 0, len(unresolved))

    if ig is None:
        logger.warning(
            "[PENDING_DEAL_RESOLVE] IG session empty — leaving %d pending "
            "record(s) unresolved.", len(unresolved),
        )
        return (len(unresolved), 0, 0, len(unresolved))

    # Cache the open-positions payload lazily. Populated on the first
    # /confirms failure that would otherwise leave a record PENDING;
    # subsequent iterations reuse it. None sentinel = not-yet-fetched;
    # empty list / list-of-dicts = fetched. False sentinel = fetch
    # attempted and permanently failed (skip further attempts).
    _positions_cache: Any = None

    def _get_positions_cached():
        nonlocal _positions_cache
        if _positions_cache is None:
            try:
                pl = get_open_positions()
            except Exception as _pos_exc:
                logger.warning(
                    "[PENDING_DEAL_RESOLVE] get_open_positions raised: %s: %s "
                    "(exact-reference positions fallback disabled this batch)",
                    type(_pos_exc).__name__, _pos_exc,
                )
                _positions_cache = False
                return None
            if pl is None:
                # get_open_positions signals API/network failure with None;
                # position state is unknown, so we cannot claim ownership.
                logger.warning(
                    "[PENDING_DEAL_RESOLVE] get_open_positions returned None "
                    "(API failure) — exact-reference positions fallback "
                    "disabled this batch.",
                )
                _positions_cache = False
                return None
            _positions_cache = pl
        if _positions_cache is False:
            return None
        return _positions_cache

    def _find_position_by_exact_reference(ref: str) -> Optional[Dict[str, Any]]:
        """Return the IG position dict whose ``position.dealReference``
        equals ``ref`` exactly. No fuzzy fields consulted. None if the
        payload is unavailable or no exact match exists."""
        payload = _get_positions_cached()
        if not payload:
            return None
        target = str(ref).strip()
        for _p in payload:
            if not isinstance(_p, dict):
                continue
            _pos = _p.get("position") or {}
            _p_ref = str(_pos.get("dealReference") or "").strip()
            if _p_ref and _p_ref == target:
                return _pos
        return None

    def _promote_via_positions(ref: str, rec_hint: Dict[str, Any]) -> bool:
        """Positions fallback. Returns True iff the pending record was
        promoted to ACCEPTED via an exact dealReference match against
        an IG open position that also carries a real dealId."""
        _p_row = _find_position_by_exact_reference(ref)
        if _p_row is None:
            return False
        _p_deal_id = str(_p_row.get("dealId") or "").strip()
        if not _p_deal_id:
            logger.warning(
                "[PENDING_DEAL_RESOLVE] exact-reference position match "
                "for ref=%s but dealId missing — leaving PENDING (no "
                "exact broker identity available).", ref,
            )
            return False
        try:
            _pdl.mark_accepted(
                ref, deal_id=_p_deal_id,
                resolution_source="restart_positions_exact_reference",
            )
        except Exception as _ma_exc:
            logger.warning(
                "[PENDING_DEAL_RESOLVE] mark_accepted via positions failed "
                "for ref=%s: %s", ref, _ma_exc,
            )
            return False
        logger.warning(
            "[PENDING_DEAL_RESOLVE] ACCEPTED (positions_exact_reference) "
            "ref=%s dealId=%s family=%s event_id=%s — /confirms still "
            "unresolved but IG open positions carried the exact "
            "dealReference we posted; reconcile_open_positions will "
            "adopt the position via the pending_deal_ledger ownership "
            "source.",
            ref, _p_deal_id, rec_hint.get("strategy_family"),
            rec_hint.get("event_id"),
        )
        return True

    checked = 0
    accepted = 0
    rejected = 0
    still_pending = 0
    for rec in unresolved:
        checked += 1
        ref = str(rec.get("deal_reference") or "").strip()
        if not ref:
            still_pending += 1
            continue
        try:
            conf = ig.fetch_deal_by_deal_reference(ref)
        except Exception as _fetch_exc:
            logger.warning(
                "[PENDING_DEAL_RESOLVE] fetch failed for ref=%s: %s: %s "
                "(consulting positions fallback)",
                ref, type(_fetch_exc).__name__, _fetch_exc,
            )
            if _promote_via_positions(ref, rec):
                accepted += 1
            else:
                still_pending += 1
            continue
        if not isinstance(conf, dict):
            logger.warning(
                "[PENDING_DEAL_RESOLVE] non-dict confirmation for ref=%s: %s "
                "(consulting positions fallback)", ref, type(conf).__name__,
            )
            if _promote_via_positions(ref, rec):
                accepted += 1
            else:
                still_pending += 1
            continue
        status = str(conf.get("dealStatus") or "").upper()
        if status == "ACCEPTED":
            deal_id = str(conf.get("dealId") or "").strip()
            if not deal_id:
                logger.warning(
                    "[PENDING_DEAL_RESOLVE] ACCEPTED without dealId for "
                    "ref=%s — consulting positions fallback for exact "
                    "dealReference match.", ref,
                )
                if _promote_via_positions(ref, rec):
                    accepted += 1
                else:
                    still_pending += 1
                continue
            try:
                _pdl.mark_accepted(
                    ref, deal_id=deal_id,
                    resolution_source="restart_confirms",
                )
                accepted += 1
                logger.warning(
                    "[PENDING_DEAL_RESOLVE] ACCEPTED ref=%s dealId=%s "
                    "family=%s event_id=%s — recovered pending submission "
                    "into ledger; reconcile_open_positions will adopt the "
                    "IG position.",
                    ref, deal_id, rec.get("strategy_family"),
                    rec.get("event_id"),
                )
            except Exception as _ma_exc:
                still_pending += 1
                logger.warning(
                    "[PENDING_DEAL_RESOLVE] mark_accepted failed for ref=%s: %s",
                    ref, _ma_exc,
                )
        elif status == "REJECTED":
            detail = _extract_rejection_detail(conf)
            try:
                _pdl.mark_rejected(
                    ref, reason=(detail or "REJECTED"),
                    resolution_source="restart_confirms",
                )
                rejected += 1
                logger.warning(
                    "[PENDING_DEAL_RESOLVE] REJECTED ref=%s family=%s "
                    "event_id=%s reason=%s — terminal, no ownership.",
                    ref, rec.get("strategy_family"),
                    rec.get("event_id"), detail,
                )
            except Exception as _mr_exc:
                still_pending += 1
                logger.warning(
                    "[PENDING_DEAL_RESOLVE] mark_rejected failed for ref=%s: %s",
                    ref, _mr_exc,
                )
        else:
            # Unknown / transient status. Try the positions fallback in
            # case the position is already visible.
            logger.warning(
                "[PENDING_DEAL_RESOLVE] ref=%s status=%r — consulting "
                "positions fallback.", ref, status or None,
            )
            if _promote_via_positions(ref, rec):
                accepted += 1
            else:
                still_pending += 1

    logger.info(
        "[PENDING_DEAL_RESOLVE] checked=%d accepted=%d rejected=%d "
        "still_pending=%d",
        checked, accepted, rejected, still_pending,
    )
    return (checked, accepted, rejected, still_pending)


# ─────────────────────────────────────────────────────────────────────
# STARTUP-RECONCILE RETRY STATE (2026-10-19 continuation).
#
# When reconcile_open_positions runs during a startup where /positions
# is UNKNOWN, we stash the caller's args and set a one-shot pending
# flag. The next successful get_open_positions call invokes
# maybe_recover_reconcile_after_refresh(), which re-runs reconcile
# exactly ONCE with those args — in-process, without a service
# restart.
#
# Idempotency:
#   * The _COMPLETED flag is set BEFORE the retry call so recursive /
#     subsequent get_open_positions successes don't trigger a second
#     reconcile.
#   * reconcile_open_positions itself is already idempotent at the
#     per-deal level — it only inserts into EPIC_STATE for deal_ids
#     not already tracked. So even a defensive double-call would not
#     adopt the same position twice.
#   * The sibling-reference guard inside reconcile continues to skip
#     foreign-prefix (e.g. HBB-) refs. The retry does not weaken
#     ownership rules.
# ─────────────────────────────────────────────────────────────────────
_RECONCILE_RETRY_LOCK = threading.RLock()
_RECONCILE_RETRY_PENDING: bool = False
_RECONCILE_RETRY_ARGS: Optional[Tuple[Dict[str, str],
                                      Optional[Dict[str, str]]]] = None
_RECONCILE_RETRY_COMPLETED: bool = False
_RECONCILE_RETRY_MAX_AGE_S: float = 120.0  # must match the positions-
                                           # visibility gate's default


def _reconcile_retry_reset_for_tests() -> None:
    """Test-only: zero the retry state."""
    global _RECONCILE_RETRY_PENDING, _RECONCILE_RETRY_ARGS, _RECONCILE_RETRY_COMPLETED
    with _RECONCILE_RETRY_LOCK:
        _RECONCILE_RETRY_PENDING = False
        _RECONCILE_RETRY_ARGS = None
        _RECONCILE_RETRY_COMPLETED = False


def _mark_reconcile_pending_retry(
    epic_map: Dict[str, str],
    mode_map: Optional[Dict[str, str]],
) -> None:
    """Record a pending retry. Called by reconcile_open_positions when
    it detects UNKNOWN. Only sets pending if the retry hasn't already
    completed (guarantees at-most-once semantics)."""
    global _RECONCILE_RETRY_PENDING, _RECONCILE_RETRY_ARGS
    with _RECONCILE_RETRY_LOCK:
        if _RECONCILE_RETRY_COMPLETED:
            return
        _RECONCILE_RETRY_PENDING = True
        _RECONCILE_RETRY_ARGS = (
            dict(epic_map or {}),
            dict(mode_map or {}) if mode_map else None,
        )
        logger.info(
            "[RECONCILE_RETRY] startup reconcile hit UNKNOWN — queued "
            "a one-shot retry for the next successful /positions call "
            "(epic_map_keys=%s mode_map=%s)",
            sorted((epic_map or {}).keys()),
            "<set>" if mode_map else None,
        )


def reconcile_retry_status() -> Dict[str, Any]:
    """Diagnostic snapshot of the retry state."""
    with _RECONCILE_RETRY_LOCK:
        return {
            "pending": _RECONCILE_RETRY_PENDING,
            "completed": _RECONCILE_RETRY_COMPLETED,
            "has_args": _RECONCILE_RETRY_ARGS is not None,
        }


def maybe_recover_reconcile_after_refresh() -> Optional[Tuple[int, int]]:
    """If startup reconcile hit UNKNOWN and visibility has since
    returned to fresh, re-run reconcile_open_positions exactly ONCE
    with the stashed args. Returns the (restored, seen) tuple from
    reconcile if a retry fired; None if nothing was done (no retry
    pending, already completed, or visibility still absent).

    Thread-safe. Called lazily from close_sb_now.get_open_positions on
    every successful fetch — the completion flag guarantees the
    reconcile only runs once per process lifetime.

    Failure handling: if reconcile_open_positions raises during the
    retry, the retry is marked completed and NOT reattempted (a
    second retry loop would be a potential infinite-retry footgun).
    The operator can trigger adoption via a service restart.
    """
    global _RECONCILE_RETRY_PENDING, _RECONCILE_RETRY_ARGS, _RECONCILE_RETRY_COMPLETED
    with _RECONCILE_RETRY_LOCK:
        if _RECONCILE_RETRY_COMPLETED:
            return None
        if not _RECONCILE_RETRY_PENDING:
            return None
        if _RECONCILE_RETRY_ARGS is None:
            # Shouldn't happen (pending without args), but be defensive.
            _RECONCILE_RETRY_PENDING = False
            _RECONCILE_RETRY_COMPLETED = True
            return None
        # Confirm visibility is fresh. The caller (close_sb_now)
        # invokes us right after a successful fetch, so this check
        # should pass; it's belt-and-braces for direct callers.
        try:
            from close_sb_now import positions_state_visible as _pv_visible
            if not _pv_visible(max_age_s=_RECONCILE_RETRY_MAX_AGE_S):
                return None
        except Exception as _vis_exc:
            logger.debug(
                "[RECONCILE_RETRY] visibility check failed; deferring: %s",
                _vis_exc,
            )
            return None
        # Atomically claim the retry: mark completed BEFORE releasing
        # the lock so any recursive / concurrent caller sees "done".
        args = _RECONCILE_RETRY_ARGS
        _RECONCILE_RETRY_PENDING = False
        _RECONCILE_RETRY_COMPLETED = True

    # Call reconcile OUTSIDE the retry lock so it can acquire
    # EPIC_STATE_LOCK without ordering concerns.
    epic_map, mode_map = args
    try:
        logger.info(
            "[RECONCILE_RETRY] visibility recovered — retrying "
            "reconcile_open_positions"
        )
        restored, seen = reconcile_open_positions(
            epic_map, mode_map=mode_map
        )
        logger.info(
            "[RECONCILE_RETRY] completed — restored=%d seen=%d",
            restored, seen,
        )
        return (restored, seen)
    except Exception as exc:
        logger.error(
            "[RECONCILE_RETRY] retry raised — not reattempting (service "
            "restart required for adoption): %s", exc,
        )
        return None


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

        2026-10-19 three-state semantics: an UNKNOWN API state (get_open_
        positions returned None) must NEVER be interpreted as "no open
        positions". The caller is expected to check for the UNKNOWN
        condition via close_sb_now.positions_state_visible() and NOT
        remove local records. This function logs the distinction so the
        operator can tell the three cases apart in the journal.

        2026-10-19 recovery continuation: an UNKNOWN call also stashes
        the (epic_map, mode_map) args + flips the retry-pending flag.
        The next successful get_open_positions call will trigger
        maybe_recover_reconcile_after_refresh() which re-runs this
        function once (idempotent).
    """
    positions = get_open_positions()
    if positions is None:
        # 2026-10-19 repair — UNKNOWN state: /positions failed. We must
        # NOT emit "No open IG positions found" (which was previously
        # ambiguous between EMPTY and UNKNOWN). Local records are
        # preserved: this function makes NO change to EPIC_STATE in
        # the UNKNOWN branch.
        try:
            from close_sb_now import last_fetch_status as _lfs
            _diag = _lfs()
        except Exception:
            _diag = {}
        logger.error(
            "[RECONCILE] UNKNOWN — /positions API failed; local records "
            "preserved. diagnostics=%s",
            _diag,
        )
        # Queue a one-shot retry for when visibility returns.
        try:
            _mark_reconcile_pending_retry(epic_map, mode_map)
        except Exception as _retry_exc:
            logger.debug(
                "[RECONCILE_RETRY] failed to mark pending: %s", _retry_exc,
            )
        return 0, 0
    if not positions:
        logger.info("[RECONCILE] EMPTY — IG account confirmed zero open positions.")
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

        # ── Sibling-reference guard ───────────────────────────────
        # A dealReference matching our naming scheme (<host>-<mode>-
        # <epoch_ms>) with a DIFFERENT host prefix proves another
        # instance of this code opened the position. Reject without any
        # local lookup — we must never adopt a sibling's open even if
        # it happens to share an epic / direction / price with one of
        # ours.
        try:
            from ownership_identity import (
                is_our_reference as _is_our_ref,
                is_sibling_reference as _is_sibling_ref,
            )
        except Exception:
            _is_our_ref = lambda _r: False
            _is_sibling_ref = lambda _r: False
        if _own_deals_only and _is_sibling_ref(deal_reference):
            size_for_log = _to_float_or_none(
                pos.get("dealSize") or pos.get("size") or pos.get("contractSize")
            )
            logger.warning(
                "[OWNERSHIP] %s dealId=%s dealRef=%s direction=%s "
                "size=%s — SIBLING (dealReference host prefix is NOT this "
                "host's); leaving untouched.",
                epic_raw or epic, deal_id, deal_reference, direction, size_for_log,
            )
            _log_foreign_deal({
                "epic": epic_raw or epic,
                "dealId": deal_id,
                "dealReference": deal_reference,
                "direction": direction,
                "size": size_for_log,
                "foreign_reason": "sibling_deal_reference_prefix",
                "host": os.getenv("HOSTNAME") or os.uname().nodename,
            })
            continue

        # ── Own-deals-only gate (per-deal check) ──────────────────
        # Two durable ownership sources, tried in order:
        #   (A) signal_log — the legacy dispatch path recorded here.
        #   (B) candidate_corpus — orchestrator-routed families record
        #       here (Repair 9, 2026-09-29). See _scan_candidate_corpus
        #       for the ownership predicate (executed=True + non-null
        #       execution_deal_id + non-null candidate_id + non-null
        #       execution_ts). Sibling-bot deals cannot appear in this
        #       corpus because it is written by AutoBot's own
        #       orchestrator/adapter seam on this host.
        # A deal that misses BOTH sources is FOREIGN and is skipped.
        # Provenance is stamped onto the EPIC_STATE entry below so
        # downstream diagnostics can distinguish signal_log-origin vs
        # candidate_corpus_recovery-origin positions.
        _own_by_deal = False
        _own_by_ref = False
        _corpus_row: Optional[Dict[str, Any]] = None
        _pending_row: Optional[Dict[str, Any]] = None
        ownership_source: Optional[str] = None
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
            if _own_by_deal or _own_by_ref:
                ownership_source = "signal_log"
            else:
                # Repair 9 fallback — consult candidate_corpus. Exact
                # dealId or dealReference match; ownership predicate
                # enforced inside the helper.
                if deal_id:
                    _corpus_row = lookup_candidate_corpus_by_deal_id(deal_id)
                if _corpus_row is None and deal_reference:
                    _corpus_row = lookup_candidate_corpus_by_deal_reference(deal_reference)
                if _corpus_row is not None:
                    ownership_source = "candidate_corpus_recovery"
                    logger.warning(
                        "[RECONCILE] %s dealId=%s dealRef=%s direction=%s — "
                        "AutoBot ownership recovered via candidate_corpus "
                        "(family=%s source=%s candidate_id=%s "
                        "execution_ts=%s). signal_log did not carry a row "
                        "for this deal.",
                        epic_raw or epic, deal_id, deal_reference, direction,
                        _corpus_row.get("strategy_family"),
                        _corpus_row.get("source_path"),
                        _corpus_row.get("candidate_id"),
                        _corpus_row.get("execution_ts"),
                    )
            # 2026-09-30 repair — third ownership source: the durable
            # pending-confirmation ledger. When AutoBot POSTed an OTC
            # order and IG returned a valid dealReference but /confirms
            # failed (temporary 404) the process may have died before
            # signal_log / candidate_corpus were written. The pending
            # ledger persists the dealReference at the IG-ack seam and
            # is stamped with the exact dealId by the restart-recovery
            # hook (autobot boot). An IG position whose dealId or
            # dealReference matches an ACCEPTED pending record is our
            # exact-broker-identity proof of ownership. No fuzzy match.
            if ownership_source is None:
                try:
                    import pending_deal_ledger as _pdl_rec
                    if deal_id:
                        _pending_row = _pdl_rec.find_by_deal_id(deal_id)
                    if _pending_row is None and deal_reference:
                        _pending_row = _pdl_rec.get(deal_reference)
                    if isinstance(_pending_row, dict):
                        _p_state = str(_pending_row.get("state") or "")
                        # Only ACCEPTED records prove ownership. PENDING
                        # records mean the /confirms lookup has not yet
                        # resolved — treat as foreign until it does.
                        if _p_state == _pdl_rec.STATE_ACCEPTED:
                            ownership_source = "pending_deal_ledger"
                            logger.warning(
                                "[RECONCILE] %s dealId=%s dealRef=%s "
                                "direction=%s — AutoBot ownership recovered "
                                "via pending_deal_ledger (family=%s "
                                "submitted_at=%s resolution_source=%s).",
                                epic_raw or epic, deal_id, deal_reference,
                                direction,
                                _pending_row.get("strategy_family"),
                                _pending_row.get("submitted_at"),
                                _pending_row.get("resolution_source"),
                            )
                        else:
                            _pending_row = None
                except Exception as _pdl_rec_exc:
                    logger.warning(
                        "[RECONCILE] pending_deal_ledger lookup failed for "
                        "dealId=%s dealRef=%s: %s",
                        deal_id, deal_reference, _pdl_rec_exc,
                    )
            # Fourth ownership source: dealReference prefix. On a shared
            # account where open_sb_now stamps every open with
            # <host>-<mode>-<epoch_ms>, a position whose dealReference
            # starts with THIS host's prefix is ours by broker-authored
            # identity even if the signal_log / candidate_corpus /
            # pending_deal_ledger entry was lost (e.g. disk eviction).
            if ownership_source is None and _is_our_ref(deal_reference):
                ownership_source = "deal_reference_prefix"
                logger.warning(
                    "[RECONCILE] %s dealId=%s dealRef=%s direction=%s — "
                    "AutoBot ownership recovered via dealReference prefix "
                    "match (no signal_log / candidate_corpus / "
                    "pending_deal_ledger entry).",
                    epic_raw or epic, deal_id, deal_reference, direction,
                )
            if ownership_source is None:
                size_for_log = _to_float_or_none(
                    pos.get("dealSize") or pos.get("size") or pos.get("contractSize")
                )
                logger.warning(
                    "[RECONCILE] %s dealId=%s dealRef=%s direction=%s "
                    "size=%s — FOREIGN (no signal_log origin and no "
                    "candidate_corpus origin on this host); leaving "
                    "untouched. Set RECONCILE_OWN_DEALS_ONLY=0 to restore "
                    "the prior adopt-everything behaviour.",
                    epic_raw or epic, deal_id, deal_reference, direction, size_for_log,
                )
                _log_foreign_deal({
                    "epic": epic_raw or epic,
                    "dealId": deal_id,
                    "dealReference": deal_reference,
                    "direction": direction,
                    "size": size_for_log,
                    "signal_log_readable": _signal_log_readable,
                    "candidate_corpus_readable": True,
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

        # Fuzzy entry-price adoption REMOVED (ownership audit, 2026-10-07).
        # Previously the reconciler would recover a mode tag by matching
        # (epic, direction, entry_price) against signal_log — but when a
        # sibling bot on a shared IG account opened at approximately the
        # same price in the same direction, the match adopted their
        # position as ours. Ownership is now strictly broker-authored:
        # dealId / dealReference lookups, dealReference host prefix, and
        # candidate_corpus / pending_deal_ledger receipts only.

        if not mode and mode_map:
            mode = mode_map.get(epic)
            if mode:
                logger.info(
                    f"[RECONCILE] {epic} mode={mode} recovered from sweep journal "
                    f"(epic-level fallback)"
                )

        # Repair 9 (2026-09-29) — candidate_corpus family propagation.
        # When ownership was proven via candidate_corpus and none of the
        # signal_log / sweep-journal sources supplied a strategy tag,
        # use the corpus row's strategy_family. This preserves
        # ONE_STRATEGY / QM_V2 / V2_PICK_BOUNCE / BRIEFING_EXECUTION
        # identity for reconciled positions whose signal_log write was
        # lost, and is essential for Repair 6 thesis recovery which
        # gates on `mode == "ONE_STRATEGY"`. Historical QM_V2 identity
        # is preserved exactly (operator §8): reconciled QM_V2 positions
        # retain their family — they are NOT rebranded ONE_STRATEGY or
        # V2_PICK_BOUNCE and no synthetic thesis is fabricated.
        if not mode and _corpus_row is not None:
            corpus_family = str(_corpus_row.get("strategy_family") or "").strip() or None
            if corpus_family:
                mode = corpus_family
                logger.info(
                    "[RECONCILE] restored mode=%s for deal=%s from "
                    "candidate_corpus (ownership_source=candidate_corpus_recovery, "
                    "source_path=%s, candidate_id=%s)",
                    mode, deal_id,
                    _corpus_row.get("source_path"),
                    _corpus_row.get("candidate_id"),
                )

        # 2026-09-30 repair — pending_deal_ledger family propagation.
        # When ownership was proven via the pending ledger and none of
        # the earlier sources supplied a strategy tag, use the pending
        # record's strategy_family. Same rationale as the corpus block.
        if not mode and _pending_row is not None:
            pending_family = str(_pending_row.get("strategy_family") or "").strip() or None
            if pending_family:
                mode = pending_family
                logger.info(
                    "[RECONCILE] restored mode=%s for deal=%s from "
                    "pending_deal_ledger (ownership_source=pending_deal_ledger, "
                    "event_id=%s proposal_id=%s)",
                    mode, deal_id,
                    _pending_row.get("event_id"),
                    _pending_row.get("proposal_id"),
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

        # Repair 9 (2026-09-29) — prefer candidate_corpus execution_ts
        # over IG's createdDateUTC or the process-time fallback for
        # open_time on candidate-corpus-recovered positions. Repair 6's
        # correlation-based thesis lookup uses entry_ts_utc within a
        # 90s tolerance; the corpus execution_ts is the AutoBot dispatch
        # instant and matches the Stage 9 ledger's established_at within
        # a few seconds. Using IG's createdDate or time.time() here
        # would risk landing outside the tolerance window.
        if _corpus_row is not None:
            corpus_exec_ts = _corpus_row.get("execution_ts")
            if corpus_exec_ts:
                try:
                    _ce = str(corpus_exec_ts).replace("Z", "+00:00")
                    open_time = datetime.fromisoformat(_ce).timestamp()
                except Exception:
                    pass  # keep IG or process-time value

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
            # Repair 9 provenance: distinguishes signal_log-adopted
            # positions from candidate_corpus_recovery-adopted ones.
            # Downstream consumers (audits, forensic logging) MAY use
            # this field but no gate/exit/router reads it.
            "ownership_source": ownership_source or "signal_log",
        })

        # ── Repair 6 (2026-09-29) — ONE_STRATEGY thesis recovery. ────
        # A reconciled ONE_STRATEGY position needs its ORIGINAL Stage 9
        # thesis identity restored so one_strategy_management can honour
        # Repair 3's invariants (opposite-Stage9 comparison against the
        # ORIGINAL event_id, NMS-inversion cutoff against the ORIGINAL
        # established_at). Never substitute current Stage 9 state — that
        # would fabricate a new thesis and defeat the fail-closed
        # semantics of Repairs 2 and 3.
        #
        # Recovery paths (in order):
        #   (a) find_by_deal_id — direct linkage stamped by Repair 6's
        #       confirmed-fill site. Present for any position opened
        #       AFTER 2026-09-29 (i.e. every future restart).
        #   (b) find_thesis_by_correlation — heal-legacy path for pre-
        #       Repair-6 positions. Uses (pair, side, entry_ts_utc)
        #       within a small tolerance; requires an unambiguous
        #       single match. If multiple ledger rows plausibly fit
        #       we refuse to guess (RECOVERY_FAILED).
        #
        # When recovery fails, the position keeps trading under broker
        # SL/TP protection but one_strategy_management skips its
        # verdict evaluation for this position (management verdict
        # would otherwise be comparing against a synthetic identity).
        if str(mode or "").upper() == "ONE_STRATEGY":
            _os_recovered: Optional[Dict[str, Any]] = None
            _os_recovery_source: Optional[str] = None
            _os_recovery_reason: Optional[str] = None
            try:
                import one_strategy_event_ledger as _os_ledger
                if deal_id:
                    _os_recovered = _os_ledger.find_by_deal_id(str(deal_id))
                    if _os_recovered is not None:
                        _os_recovery_source = "deal_id_linkage"
                if _os_recovered is None:
                    _entry_ts_iso = ""
                    try:
                        from datetime import datetime as _dt2, timezone as _tz2
                        _entry_ts_iso = _dt2.fromtimestamp(
                            open_time, tz=_tz2.utc,
                        ).isoformat()
                    except Exception:
                        _entry_ts_iso = ""
                    if _entry_ts_iso:
                        _os_recovered = _os_ledger.find_thesis_by_correlation(
                            pair=_pair_from_epic(epic),
                            side=direction,
                            entry_ts_utc=_entry_ts_iso,
                            tolerance_s=float(
                                os.getenv(
                                    "ONE_STRATEGY_THESIS_RECOVERY_TOLERANCE_S",
                                    "90",
                                ) or "90"
                            ),
                        )
                        if _os_recovered is not None:
                            _os_recovery_source = "correlation"
                            # Heal the ledger: back-fill the deal_id so
                            # the next reconcile hits the fast path.
                            _bf_eid = _os_recovered.get("event_id")
                            if _bf_eid and deal_id:
                                try:
                                    _os_ledger.update_deal_id(
                                        str(_bf_eid), str(deal_id),
                                    )
                                except Exception:
                                    pass
                        else:
                            _os_recovery_reason = (
                                "no_correlation_match"
                                if _entry_ts_iso
                                else "no_entry_ts_for_correlation"
                            )
                    else:
                        _os_recovery_reason = "no_entry_ts_for_correlation"
            except Exception as _os_rec_exc:
                logger.warning(
                    "[ONE_STRATEGY_RECOVERY] ledger lookup raised for "
                    "deal_id=%s: %s", deal_id, _os_rec_exc,
                )
                _os_recovered = None
                _os_recovery_reason = f"ledger_exception:{type(_os_rec_exc).__name__}"

            if _os_recovered is not None:
                st["one_strategy_thesis"] = {
                    "stage9_event_id": _os_recovered.get("event_id"),
                    "interaction_id": _os_recovered.get("interaction_id"),
                    "direction": _os_recovered.get("direction"),
                    "established_at": _os_recovered.get("established_at"),
                    "entry_price": entry_price,
                    "entry_ts_utc": _os_recovered.get("recorded_at"),
                    "recovery_state": "RECOVERED",
                    "recovery_source": _os_recovery_source,
                }
                logger.warning(
                    "[ONE_STRATEGY_RECOVERY] thesis restored deal_id=%s "
                    "event_id=%s interaction_id=%s established_at=%s "
                    "source=%s",
                    deal_id,
                    _os_recovered.get("event_id"),
                    _os_recovered.get("interaction_id"),
                    _os_recovered.get("established_at"),
                    _os_recovery_source,
                )
            else:
                st["one_strategy_thesis"] = {
                    "stage9_event_id": None,
                    "interaction_id": None,
                    "direction": None,
                    "established_at": None,
                    "entry_price": entry_price,
                    "entry_ts_utc": None,
                    "recovery_state": "ONE_STRATEGY_THESIS_RECOVERY_FAILED",
                    "recovery_source": None,
                    "recovery_reason": _os_recovery_reason
                    or "no_matching_ledger_record",
                }
                logger.critical(
                    "🚨 [ONE_STRATEGY_RECOVERY] thesis RECOVERY FAILED "
                    "deal_id=%s epic=%s direction=%s entry=%s reason=%s "
                    "— position kept under broker SL/TP protection only; "
                    "one_strategy_management will skip verdict evaluation "
                    "for this position. Manual close permitted.",
                    deal_id, epic, direction, entry_price,
                    _os_recovery_reason or "no_matching_ledger_record",
                )
                try:
                    from telegram_alerts import send_telegram_message
                    send_telegram_message(
                        "⚠️ ONE_STRATEGY thesis recovery FAILED for "
                        f"{_pair_from_epic(epic)} {direction} deal_id="
                        f"{deal_id} entry={entry_price}. Position remains "
                        "under broker SL/TP only. Management verdicts "
                        "suspended for this position; manual review "
                        "required."
                    )
                except Exception as _tg_exc:
                    logger.debug(
                        "[ONE_STRATEGY_RECOVERY] telegram alert failed: %s",
                        _tg_exc,
                    )

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


# ============================================================
# Execution-rejection telemetry (Build 2, 2026-10-06)
# ============================================================
#
# Wraps ``execute_trade`` so every non-open return path writes one row
# to ``logs/execution_rejections.jsonl``. Covers every ``return None``
# site in the inner implementation; the stage/reason are supplied by
# the ``_set_block_info`` calls already in-tree (23+ sites) plus the
# nine newly-instrumented sites added in the same commit. Fail-silent:
# a telemetry failure never raises into the caller.
#
# The autobot caller still consumes the block-info slot via
# ``consume_last_block_info`` (used for forensic_fires back-annotation);
# this wrapper reads via ``peek_last_block_info`` so both consumers
# see the same row without racing.

_execute_trade_impl = execute_trade  # type: ignore[assignment]


def execute_trade(decision: Any, epic: str, **kwargs):  # type: ignore[no-redef]
    """Public ``execute_trade`` with execution-rejection telemetry.

    Delegates to ``_execute_trade_impl`` (the original implementation)
    and emits one line to ``logs/execution_rejections.jsonl`` when the
    inner call returns ``None`` (i.e. no position opened). Signature,
    kwargs, and return value are unchanged.
    """
    _epic_str = str(epic).strip() if epic else ""
    _mode = ""
    _side = ""
    try:
        if decision is not None:
            _mode = _safe_str(getattr(decision, "mode", "")).strip()
            _side = _safe_str(getattr(decision, "signal", "")).strip()
    except Exception:
        pass

    # ─── NMS V3 directional guard (v3-stabilisation-20261013 Amendment 3) ───
    # Catches every ``execute_trade`` caller — including strategy modules
    # such as bounce_engine_live.py that bypass the orchestrator path.
    # The gate itself is scoped to the three V3 families (V3_BB_*,
    # V3_EMA_*, GBPUSD_TREND_V3_UM_*); anything else short-circuits to
    # allowed=True inside nms_v3_direction_gate.check. Default DISABLED
    # (NMS_V3_DIRECTIONAL_GATE_ENABLED=0) → zero behaviour change.
    #
    # Operator ruling 2026-10-21: when DIRECTION_FROM_NMS_SESSION_
    # TREND=1 this guard is SKIPPED. The new BOUNCE/TREND rulebooks
    # (nms_session_trend_direction) replace it at the per-strategy
    # seams, so running it here would double-block.
    if os.getenv(
        "DIRECTION_FROM_NMS_SESSION_TREND", "0",
    ).strip() in ("1", "true", "yes", "on"):
        pass
    else:
      try:
        import nms_v3_direction_gate as _nms_v3_gate
        _nms_sym = ""
        try:
            _nms_sym = _pair_from_epic(_epic_str) or ""
        except Exception:
            _nms_sym = ""
        _nms_decision = _nms_v3_gate.check(
            strategy=_mode,
            side=_side,
            symbol=_nms_sym,
        )
        if not _nms_decision.allowed:
            logger.info(
                "[NMS_V3_GATE] %s %s %s %s — blocked by %s (reasons=%s)",
                _nms_sym or "?", _side or "?", _mode or "?", _epic_str,
                _nms_decision.binding or "nms_v3",
                ",".join(_nms_decision.reason_codes),
            )
            _set_block_info(
                "NMS_V3_DIRECTION_GATE",
                ",".join(_nms_decision.reason_codes),
            )
            try:
                import execution_rejection_log as _erl_block
                _erl_block.write_rejection(
                    epic=_epic_str,
                    mode=_mode,
                    side=_side,
                    site="NMS_V3_DIRECTION_GATE",
                    reason=",".join(_nms_decision.reason_codes),
                )
            except Exception:
                pass  # fail-silent — telemetry never blocks trading
            return None
      except Exception as _nms_exc:  # pragma: no cover — defensive
        logger.debug(
            "[NMS_V3_GATE] execute_trade pre-check error (fail-open): %s",
            _nms_exc,
        )

    result = _execute_trade_impl(decision, epic, **kwargs)
    if result is None:
        # Defensive release: clear any pending_open reservation we
        # might have flipped before taking the refusal path. Covers
        # paths that bypass the per-site cleanup (future refactors
        # or unhandled exceptions caught upstream). pair-scoped.
        try:
            _rel_pair = _pair_from_epic(_epic_str)
            if _rel_pair in _AUTOBOT_AGG_CAP_GUARDED_PAIRS:
                with EPIC_STATE_LOCK:
                    _release_stale_pending_opens(_rel_pair)
        except Exception:
            pass  # fail-silent
        try:
            import execution_rejection_log as _erl
            info = peek_last_block_info() or {}
            stage = str(info.get("stage") or "UNKNOWN")
            reason = str(info.get("reason") or "no_specific_site_recorded")
            _erl.write_rejection(
                epic=_epic_str,
                mode=_mode,
                side=_side,
                site=stage,
                reason=reason,
            )
        except Exception:
            pass  # fail-silent — telemetry never blocks trading
    return result
