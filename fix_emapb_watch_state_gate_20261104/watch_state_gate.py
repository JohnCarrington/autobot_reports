"""NMS WATCH_AND_WAIT directional-permission gate for EMA Pullback.

A read-only consumer of the authoritative WATCH_AND_WAIT lifecycle
published by the AutoBot proper at
``/opt/tradingbot/cache/nms_watch_state_<SYM>.json``. The state machine
itself lives in ``/opt/tradingbot/nms_watch_state_machine.py`` and is
driven on every M5 close by ``/opt/tradingbot/nms_watch_state_driver.py``.
EMA Pullback does NOT re-classify exhaustion — it reads the verdict and
applies the admission rule.

Design:
    * Mirrors the deployed admission contract already used by the
      standalone Bollinger Bounce service (see
      ``/opt/bb_bounce/open_sb_now.py:_phase2b_block_order``).
    * Pure module. Reads the snapshot file read-only via
      ``WatchStateProvider``. Never mutates NMS state. Never writes to
      ``/opt/tradingbot``.
    * Default-disabled. Flipping ``EMAPB_WATCH_STATE_GATE_ENABLED=1``
      activates the gate for a staged rollout; default behaviour is
      byte-identical to pre-patch EMA Pullback.
    * Fail-closed on snapshot failure (missing / malformed / stale /
      schema mismatch / symbol mismatch / future-dated / unknown state
      enum) when ``fail_policy='closed'``. Operators may opt in to
      ``fail_policy='open'`` for diagnostic / shadow phases.
    * Snapshot freshness is enforced via BOTH ``evaluation_ts`` age AND
      the inline ``last_bar_ts`` age (the M5 bar the driver evaluated
      against). An evaluation_ts that is fresh but points at a stale
      last_bar_ts indicates a driver that has stopped advancing bars
      and must not authorise new admissions.

Admission rules (per operator spec 2026-10-27 §4 + follow-up 2026-11-04):

    state=WATCH_AND_WAIT        → BLOCK  (both directions, regardless of
                                   watched_trend_direction — the spec is
                                   explicit: "Both BUY and SELL entries
                                   are blocked during WATCH_AND_WAIT.")
    state=REVERSAL_CONFIRMED    → BLOCK  (grants narrow permission only
                                   to the matching qm_reversal direction
                                   on QM strategies; EMA Pullback is NOT
                                   a reversal strategy and is always
                                   excluded)
    state=CONTINUATION_CONFIRMED → PASS  (operator spec: equivalent to
                                   TREND_TRADING for admission purposes)
    state=TREND_TRADING         → PASS  (default admission matrix applies)

Direction flipping is NOT performed by this gate. A SELL candidate against
an exhausted-UP trend is BLOCKED (REVERSAL_CONFIRMED path above), not
authorised. Direction authority remains with the NMS v3 gate
(``ema_pullback/nms_gate.py``) and EMA PB's own H1 qualification.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger("ema_pullback.watch_state_gate")

# Mirrors /opt/tradingbot/nms_watch_state_machine.py:149-150 and
# /opt/bb_bounce/open_sb_now.py:249-250. Any state added by the
# authority must be mirrored here.
_VALID_STATES = frozenset({
    "TREND_TRADING",
    "WATCH_AND_WAIT",
    "CONTINUATION_CONFIRMED",
    "REVERSAL_CONFIRMED",
})

# States that BLOCK new EMA Pullback admissions.
_BLOCKING_STATES = frozenset({
    "WATCH_AND_WAIT",         # operator spec §4 — both directions blocked
    "REVERSAL_CONFIRMED",     # EMA PB is not the qm_reversal strategy
})

# Schema version the authority publishes. Bumping this requires an
# intentional update to this gate — a schema drift is a hard fail.
_SUPPORTED_SCHEMAS = frozenset({"nms_watch_state.v1"})

# Default max age for both evaluation_ts and last_bar_ts. Mirrors the
# BB Bounce reader (_DEFAULT_MAX_AGE_SECONDS = 900 in open_sb_now.py).
DEFAULT_MAX_AGE_SECONDS = 900.0

_POLICY_CLOSED = "closed"
_POLICY_OPEN = "open"


@dataclass
class WatchStateDecision:
    """Result of :func:`check`. Immutable record of what was decided."""
    allowed: bool
    reason: str
    state: Optional[str] = None
    evaluation_ts: Optional[str] = None
    last_bar_ts: Optional[str] = None
    age_seconds: Optional[float] = None
    last_bar_age_seconds: Optional[float] = None
    watched_trend_direction: Optional[str] = None
    reason_codes: List[str] = field(default_factory=list)
    binding: str = ""        # "watch_state_block" | "snapshot_fail_closed" | ""


class WatchStateProvider(Protocol):
    """Returns the latest W&W snapshot dict for ``symbol``.

    Error returns are dicts with an ``__error__`` key (string reason).
    A clean miss yields ``{"__error__": "watch_state_snapshot_missing"}``.
    Returning ``None`` is equivalent to ``watch_state_snapshot_missing``.
    """
    def load(self, symbol: str) -> Optional[Dict[str, Any]]:
        ...


class FileWatchStateProvider:
    """Reads the deployed W&W snapshot JSON for a symbol.

    Written atomically by ``/opt/tradingbot/nms_watch_state_driver.py``
    on every M5 close. We only ever READ this file.
    """
    def __init__(self, snapshot_dir: Path):
        self.snapshot_dir = Path(snapshot_dir)

    def load(self, symbol: str) -> Optional[Dict[str, Any]]:
        p = self.snapshot_dir / f"nms_watch_state_{symbol.upper()}.json"
        try:
            raw = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"__error__": "watch_state_snapshot_missing"}
        except OSError as exc:
            return {"__error__": f"watch_state_snapshot_io_error:{type(exc).__name__}"}
        try:
            data = json.loads(raw)
        except Exception as exc:
            return {"__error__": f"watch_state_snapshot_malformed:{type(exc).__name__}"}
        if not isinstance(data, dict):
            return {"__error__": "watch_state_snapshot_not_object"}
        return data


def check(
    direction: str,
    symbol: str,
    now_utc: datetime,
    provider: WatchStateProvider,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    fail_policy: str = _POLICY_CLOSED,
    enabled: bool = False,
) -> WatchStateDecision:
    """Return the W&W-gate decision for a proposed arm (or recheck).

    ``direction``   ∈ ``{"BUY", "SELL"}``. Other values pass with a
                    ``watch_state_direction_not_in_scope`` reason.
    ``symbol``      is the trading symbol — upper-case internally.
    ``now_utc``     is the decision timestamp used for age arithmetic.
    ``provider``    returns the W&W snapshot dict for the symbol.
    ``max_age_seconds`` is the staleness threshold applied to BOTH
                    ``evaluation_ts`` and ``last_bar_ts``.
    ``fail_policy`` ∈ ``{"closed", "open"}``. ``closed`` (default)
                    blocks on any snapshot failure; ``open`` admits.
    ``enabled``     False (default) → trivial pass with no snapshot I/O
                    (``watch_state_gate_disabled``). Operators flip this
                    after offline validation.
    """
    direction_u = (direction or "").upper()
    if not enabled:
        return WatchStateDecision(
            allowed=True,
            reason="watch_state_gate_disabled",
            reason_codes=["watch_state_gate_disabled"],
        )
    if direction_u not in ("BUY", "SELL"):
        return WatchStateDecision(
            allowed=True,
            reason="watch_state_direction_not_in_scope",
            reason_codes=["watch_state_direction_not_in_scope"],
        )

    snap = provider.load(symbol)
    if snap is None:
        return _fail("watch_state_snapshot_missing", fail_policy)
    if isinstance(snap, dict) and snap.get("__error__"):
        return _fail(str(snap.get("__error__")), fail_policy)

    schema = str(snap.get("schema_version") or "")
    if schema not in _SUPPORTED_SCHEMAS:
        return _fail(
            f"watch_state_schema_unsupported:{schema or 'missing'}",
            fail_policy,
        )

    snap_symbol = str(snap.get("symbol") or "").upper()
    if snap_symbol != (symbol or "").upper():
        return _fail(
            f"watch_state_symbol_mismatch:expected={symbol}:got={snap_symbol}",
            fail_policy,
        )

    # ── evaluation_ts age gate ──────────────────────────────────────
    eval_ts_str = str(snap.get("evaluation_ts") or "")
    if not eval_ts_str:
        return _fail("watch_state_snapshot_missing_evaluation_ts", fail_policy)
    try:
        eval_dt = datetime.fromisoformat(eval_ts_str.replace("Z", "+00:00"))
        if eval_dt.tzinfo is None:
            eval_dt = eval_dt.replace(tzinfo=timezone.utc)
    except Exception as exc:
        return _fail(
            f"watch_state_snapshot_bad_ts:{type(exc).__name__}",
            fail_policy, eval_ts_str=eval_ts_str,
        )

    now = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    age = (now - eval_dt).total_seconds()
    if age < 0:
        return _fail(
            f"watch_state_snapshot_future_ts:age_s={age:.0f}",
            fail_policy, eval_ts_str=eval_ts_str, age=age,
        )
    if age > max_age_seconds:
        return _fail(
            f"watch_state_snapshot_stale:age_s={age:.0f}",
            fail_policy, eval_ts_str=eval_ts_str, age=age,
        )

    # ── last_bar_ts age gate ────────────────────────────────────────
    # The W&W driver records the completed M5 bar it evaluated against.
    # A fresh evaluation_ts with a stale last_bar_ts means the driver
    # is re-running the same bar — the verdict may be correct but it
    # cannot reflect developments in intervening bars. Fail-closed.
    last_bar_ts = snap.get("last_bar_ts")
    last_bar_age: Optional[float] = None
    if last_bar_ts:
        try:
            lbt = datetime.fromisoformat(str(last_bar_ts).replace("Z", "+00:00"))
            if lbt.tzinfo is None:
                lbt = lbt.replace(tzinfo=timezone.utc)
            last_bar_age = (now - lbt).total_seconds()
            if last_bar_age < 0:
                return _fail(
                    f"watch_state_last_bar_future_ts:age_s={last_bar_age:.0f}",
                    fail_policy, eval_ts_str=eval_ts_str,
                    age=age, last_bar_age=last_bar_age,
                )
            if last_bar_age > max_age_seconds:
                return _fail(
                    f"watch_state_last_bar_stale:age_s={last_bar_age:.0f}",
                    fail_policy, eval_ts_str=eval_ts_str,
                    age=age, last_bar_age=last_bar_age,
                )
        except Exception as exc:
            return _fail(
                f"watch_state_last_bar_bad_ts:{type(exc).__name__}",
                fail_policy, eval_ts_str=eval_ts_str, age=age,
            )

    # ── enum validation ─────────────────────────────────────────────
    state = str(snap.get("state") or "").upper()
    if not state:
        return _fail(
            "watch_state_missing_state",
            fail_policy, eval_ts_str=eval_ts_str, age=age,
        )
    if state not in _VALID_STATES:
        return _fail(
            f"watch_state_unknown_state:{state}",
            fail_policy, eval_ts_str=eval_ts_str, age=age,
        )

    watched_dir = snap.get("watched_trend_direction")
    dec = WatchStateDecision(
        allowed=True,
        reason="",
        state=state,
        evaluation_ts=eval_ts_str,
        last_bar_ts=str(last_bar_ts) if last_bar_ts else None,
        age_seconds=age,
        last_bar_age_seconds=last_bar_age,
        watched_trend_direction=str(watched_dir) if watched_dir else None,
    )

    if state in _BLOCKING_STATES:
        dec.allowed = False
        dec.binding = "watch_state_block"
        reason = f"watch_state_block:state={state}:side={direction_u}"
        dec.reason = reason
        dec.reason_codes = [reason]
        return dec

    # TREND_TRADING / CONTINUATION_CONFIRMED pass.
    reason = f"watch_state_pass:state={state}:side={direction_u}"
    dec.reason = reason
    dec.reason_codes = [reason]
    return dec


def _fail(
    reason: str,
    fail_policy: str,
    *,
    eval_ts_str: Optional[str] = None,
    age: Optional[float] = None,
    last_bar_age: Optional[float] = None,
) -> WatchStateDecision:
    """Apply the fail-policy to a snapshot failure."""
    policy = (fail_policy or _POLICY_CLOSED).strip().lower()
    allowed = policy == _POLICY_OPEN
    return WatchStateDecision(
        allowed=allowed,
        reason=reason,
        reason_codes=[reason],
        evaluation_ts=eval_ts_str,
        age_seconds=age,
        last_bar_age_seconds=last_bar_age,
        binding="" if allowed else "snapshot_fail_closed",
    )
