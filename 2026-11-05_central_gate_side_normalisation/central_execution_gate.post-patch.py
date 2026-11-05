"""central_execution_gate.py — Phase 1 single admission authority.

Per Phase 1 §6, §7, §8.

**Live behaviour rule**: this module MUST NOT change live behaviour while
CENTRAL_EXECUTION_GATE=0 (Phase 1 default). In that state:
    * evaluate() STILL runs — it returns a GateDecision that callers
      may either honor (when the flag flips to 1) or ignore.
    * No guard is REPLACED yet. Existing guards inside
      trade_executor.execute_trade / strategy_logic._apply_exec_entry /
      autobot._entry_attempt_allowed_this_bucket remain the live
      authority. This module SHADOWS them.

This module owns:
    * A GateDecision result contract.
    * An atomic reservation ledger with candidate identity + TTL.
    * Delegation stubs to the existing production guard functions so
      the SHADOW comparison can measure parity.

It does NOT (Phase 1):
    * Amend broker stops.
    * Manage open positions.
    * Decide TradeManager states.
    * Delete or replace existing guards — that comes only after parity
      is proven and the flag flips.
    * Introduce new admission rules beyond what production already runs.

Reservation semantics:
    * A reservation is created when the gate would ALLOW execution.
    * It carries the candidate_id, epic, side, family, TTL, created_at.
    * Concurrent reservations against the same capacity slot are
      serialised via a module RLock so a race cannot double-book.
    * Reservations expire automatically after
      GATE_RESERVATION_TTL_SECONDS (default 30) — cleaned lazily on
      any evaluate() or release call. This survives broker call latency.
    * release_on_failure() drops a reservation without occupying its
      slot (broker refusal, execution failure).
    * confirm_execution() converts a reservation to an "occupied"
      marker with the deal_id/deal_ref attached.

The delegation stubs (below) are the SEAM into the current codebase.
Each returns a (bool_allowed, reason_str) pair without importing heavy
modules until needed. They fail SAFE — on exception, they treat the
guard as PERMITTING the trade (so a bug in the shadow doesn't create a
new block that the live path wouldn't have). Shadow parity metrics
detect any such fail-safe drift.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Flag reads ─────────────────────────────────────────────────────────────
def _env_bool(name: str, default: str) -> bool:
    return (os.getenv(name, default) or default).strip().lower() in (
        "1", "true", "yes", "on",
    )


def gate_active() -> bool:
    """True iff CENTRAL_EXECUTION_GATE=1 — the gate is the LIVE authority.

    Phase 1 default is 0. When 0, gate.evaluate() still runs (for
    shadow) but callers must NOT swap out the existing guards. See
    module docstring.
    """
    return _env_bool("CENTRAL_EXECUTION_GATE", "0")


def shadow_enabled() -> bool:
    """True iff the gate should evaluate in shadow mode (defaults ON so
    the parity harness has data even while the live flag is off)."""
    return _env_bool("CENTRAL_EXECUTION_GATE_SHADOW", "1")


def observation_gate_active() -> bool:
    """True iff OBSERVATION_GATE_ENABLED=1 — the observation delegate
    ENFORCES rather than only stamping.

    Spec §12 (Mandatory Observation). Phase 3 default is 0. When 0, the
    delegate ALWAYS returns ok=True but still stamps
    `observation:observation_ok` or `observation:insufficient_observation:...`
    on every candidate. When 1, an UNKNOWN observation state rejects
    the candidate outright.
    """
    return _env_bool("OBSERVATION_GATE_ENABLED", "0")


def news_trend_router_active() -> bool:
    """True iff NEWS_TREND_ROUTER=1 — the news_direction delegate
    ENFORCES on news-family days rather than only stamping.

    Spec §13, §17 (Phase 4). Phase 4 default is 0. When 0, the
    delegate ALWAYS returns ok=True but still stamps
    `news_direction:direction_agree:*` / `direction_counter_trend:*` /
    `no_primary_direction` / `news_direction_off_route`. When 1, a
    counter-trend candidate on a news-family day rejects.

    Enforcement of counter-trend blocking is Phase 6's slot machinery;
    Phase 4 landing this flag OFF is deliberate.
    """
    return _env_bool("NEWS_TREND_ROUTER", "0")


def normal_market_router_active() -> bool:
    """True iff NORMAL_MARKET_ROUTER=1 — the normal_routing delegate
    ENFORCES on canonical NORMAL days rather than only stamping.

    Spec §32/§41 (Phase 7/8). Default 0 (stamp-only). When 1, the
    permission matrix (permission_matrix.py) rejects candidates whose
    family is not permitted by (day_type, market_state).
    """
    return _env_bool("NORMAL_MARKET_ROUTER", "0")


def chop_standdown_active() -> bool:
    """True iff CHOP_STANDDOWN=1 — the normal_routing delegate
    ENFORCES the §42 CHOP_COMPRESSION stand-down. Independent of
    NORMAL_MARKET_ROUTER so operators can enable stand-down first as
    the highest-confidence rejection rule.

    Spec §42/§43. Default 0.
    """
    return _env_bool("CHOP_STANDDOWN", "0")


def range_quality_classifier_active() -> bool:
    """True iff RANGE_QUALITY_CLASSIFIER=1 — the normal_routing
    delegate consults range_quality_classifier.snapshot() to
    subclassify FLAT_OR_COMPRESSED. Under =0 the delegate treats
    FLAT_OR_COMPRESSED as an off-route stamp (NORMAL_FLAT_PENDING_
    SUBCLASS)."""
    return _env_bool("RANGE_QUALITY_CLASSIFIER", "0")


def countertrend_continuation_veto_enabled() -> bool:
    """True iff COUNTERTREND_CONTINUATION_VETO_ENABLED=1 (default 0) —
    the normal_routing delegate blocks BB_BOUNCE / LEVEL_BOUNCE
    candidates counter to `demonstrated_direction` when a fresh LOI
    record shows `continuation_demonstrated=True` in the demonstrated
    direction AND no candidate-direction BOUNCE_CONFIRMED /
    REVERSAL_CONFIRMED is currently active.

    Operator ruling 2026-09-24 (post-exit thesis audit): admission-only
    narrow veto. No new state machine, no new indicator; reads existing
    `level_interaction_observer_v6.get_latest_states(pair)`.

    Default is 0 (OFF) — operator must explicitly opt in with
    ``COUNTERTREND_CONTINUATION_VETO_ENABLED=1`` in ``.env`` (followed
    by a service restart to load the new env into the running process).
    Enforcement is additionally gated by ``normal_market_router_active()``
    (shadow-stamp when router=0; reject when router=1).
    """
    return _env_bool("COUNTERTREND_CONTINUATION_VETO_ENABLED", "0")


def _countertrend_veto_freshness_seconds() -> int:
    """Freshness ceiling in seconds for LOI evidence consumed by the
    countertrend continuation veto.

    Default 900s (15 min = 3 x 5m bars) is an INITIAL choice, not a
    canonical LOI constant — a repo-wide search for the observer's
    freshness concept turned up none (`level_interaction_observer_v6`
    exposes `raw.bar_ts` and delegates freshness to the caller, see the
    docstring on `get_latest_states` at
    `level_interaction_observer_v6.py:1531-1539`). Override with
    ``COUNTERTREND_VETO_FRESHNESS_SEC``; awaiting operator ruling on
    the final value.
    """
    try:
        return max(60, int(os.getenv("COUNTERTREND_VETO_FRESHNESS_SEC", "900")))
    except (TypeError, ValueError):
        return 900


# A10 (2026-09-14, operator ruling A.2): MID_NEWS_ROUTER was deleted.
# Its former enforcement role ("only V2_BOUNCE admits; BB rejects on
# MID_NEWS days") was already abolished by A9.5 — the mid_news delegate
# routes every family to _delegate_normal_routing regardless of the
# flag value. Removing the dead flag from the gate + .env.example +
# tests. MID_NEWS observation and search emphasis remain intact via
# the mid_news_search_emphasis stamp.


_RESERVATION_TTL_S = int(os.getenv("GATE_RESERVATION_TTL_SECONDS", "30") or 30)


# ── A10 delegate + gate outcome constants (2026-09-14) ─────────────────────
# Delegates return one of two semantic verdicts encoded as the bool
# half of their (ok, reason) tuple:
#
#   DELEGATE_NO_OBJECTION = True   → this delegate has no objection;
#                                    the gate must continue evaluating
#                                    every remaining delegate.
#   DELEGATE_REJECT       = False  → this delegate rejects; the gate
#                                    records the binding delegate name
#                                    but STILL evaluates every remaining
#                                    delegate so the receipt captures
#                                    the full reason set.
#
# Only the CentralExecutionGate emits APPROVE_FINAL — and only after
# every required delegate has returned DELEGATE_NO_OBJECTION. No
# individual delegate may short-circuit any downstream check.
DELEGATE_NO_OBJECTION = True
DELEGATE_REJECT = False

VERDICT_APPROVE_FINAL = "APPROVE_FINAL"
VERDICT_REJECT = "REJECT"

# A10 news-direction stamps (emitted alongside the raw delegate reason).
A10_NO_ACTIVE_TREND = "NO_ACTIVE_TREND"
A10_WITH_TREND = "WITH_TREND"
A10_COUNTER_TREND_DURING_ACTIVE_TREND = "COUNTER_TREND_DURING_ACTIVE_TREND"


# ── Result contract ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GateDecision:
    """The gate's verdict on a single candidate.

    allowed: True → caller may (in live mode) proceed to execute_trade.
    reservation_id: present iff allowed=True; None on reject.
    reason_codes: machine-readable justifications. Multi-code when
                  multiple guards weighed in; ordered by evaluation
                  order so parity diffs are stable.
    capacity_snapshot: what the capacity ledger looked like at decision
                  time — {open, reserved, cap} per (pair, family).
    candidate_id: mirror of the input candidate id for join safety.
    timestamp: ISO-8601 UTC of decision.
    """
    allowed: bool
    reason_codes: List[str]
    reservation_id: Optional[str]
    capacity_snapshot: Dict[str, Any]
    candidate_id: str
    timestamp: str
    live: bool = False   # True iff CENTRAL_EXECUTION_GATE=1 at decision
    # A10 (2026-09-14): explicit final-verdict fields. `verdict` is
    # emitted by the gate itself — no delegate may set it. `binding_delegate`
    # names the first delegate to return DELEGATE_REJECT when
    # verdict=VERDICT_REJECT; None when verdict=VERDICT_APPROVE_FINAL.
    verdict: str = VERDICT_REJECT
    binding_delegate: Optional[str] = None


# ── Reservation ledger ─────────────────────────────────────────────────────
@dataclass
class _Reservation:
    reservation_id: str
    candidate_id: str
    epic: str
    pair: str
    side: str
    strategy_family: str
    created_at: datetime
    expires_at: datetime
    occupied: bool = False
    deal_id: Optional[str] = None
    deal_ref: Optional[str] = None
    # Phase 6 news-slot context (§19/§26/§28). Set by the news_direction
    # delegate when it approves a news-family candidate; consumed by
    # confirm_execution() to record capacity into the NewsSlotLedger.
    # None on non-news-family days / non-router mode.
    news_slot_kind: Optional[str] = None    # "primary" | "bounce"
    news_direction: Optional[str] = None    # "BUY" | "SELL"
    bounce_event_id: Optional[str] = None
    # QM SAFETY WIRING Item 1 (2026-09-14) — the 5m bucket integer for
    # the candidate that produced this reservation, so `_delegate_bucket_dedup`
    # can reject a SECOND same-(pair, epic, bucket) candidate that arrives
    # after this reservation is approved but before `_mark_bucket_used`
    # runs. Prevents a within-process race where a duplicate arm event
    # produces two APPROVE_FINAL rows one second apart (14:25 QM_V2
    # double-fire, corpus rows for candidate 1d869d3ba6d84c... on
    # 2026-09-14).
    bucket: Optional[int] = None


_LOCK = threading.RLock()
_RESERVATIONS: Dict[str, _Reservation] = {}
# Phase 6 — per-candidate news slot evaluation context. Populated by
# _delegate_news_direction on approval; consumed by _make_reservation
# immediately after guard evaluation. Same-thread hand-off inside
# evaluate(); protected by _LOCK for cross-thread safety. Cleared after
# reservation creation, or on any release/confirm.
_NEWS_EVAL_CTX: Dict[str, Dict[str, Any]] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _prune_expired() -> None:
    """Drop expired non-occupied reservations. Called under _LOCK."""
    now = _now_utc()
    stale = [
        rid for rid, r in _RESERVATIONS.items()
        if (not r.occupied) and r.expires_at <= now
    ]
    for rid in stale:
        _RESERVATIONS.pop(rid, None)
        logger.debug("[GATE] reservation %s expired", rid)


def _snapshot_capacity() -> Dict[str, Any]:
    """Return per-(pair, family) reserved counts + cap.

    Cap is not yet enforced by the gate itself in Phase 1 — the existing
    per-strategy concurrent cap in strategy_logic._resolve_concurrent_cap
    remains authoritative. The snapshot is for parity telemetry.
    """
    with _LOCK:
        _prune_expired()
        counts: Dict[str, int] = {}
        for r in _RESERVATIONS.values():
            key = f"{r.pair}|{r.strategy_family}"
            counts[key] = counts.get(key, 0) + (1 if not r.occupied else 0)
        occupied = {}
        for r in _RESERVATIONS.values():
            if r.occupied:
                key = f"{r.pair}|{r.strategy_family}"
                occupied[key] = occupied.get(key, 0) + 1
        return {
            "reserved_by_pair_family": counts,
            "occupied_by_pair_family": occupied,
            "total_reservations": len(_RESERVATIONS),
        }


# ── Guard delegation stubs ─────────────────────────────────────────────────
# Each delegate wraps the CURRENT production guard so the gate can
# observe the same decision. They fail SAFE: on exception, return
# (True, "delegate_exception:<...>") so the shadow decision is
# permissive — this avoids the gate inventing new blocks in shadow.
#
# When CENTRAL_EXECUTION_GATE flips to 1 (Phase 1 acceptance), each
# delegate becomes the AUTHORITY and the corresponding old guard is
# removed under the staged-migration rule in spec §8.

def _delegate_kill_switch() -> Tuple[bool, str]:
    """TRADE_ENABLED master + auth-suspension guard.

    Reads TRADE_ENABLED and the presence of an ig_auth halt marker.
    Never raises.
    """
    try:
        # TRADE_ENABLED is the process-wide kill-switch consumed by
        # orchestrator.py; treat unset/empty as True to match current
        # behaviour.
        enabled = os.getenv("TRADE_ENABLED", "1").strip().lower() not in (
            "0", "false", "no", "off",
        )
        if not enabled:
            return False, "trade_disabled"
        return True, "kill_switch_pass"
    except Exception as exc:
        return True, f"delegate_exception:kill_switch:{type(exc).__name__}"


def _delegate_entry_hours(now_utc: Optional[datetime] = None) -> Tuple[bool, str]:
    """QM_ENTRY_HOURS_ENABLED + start/end hour window."""
    try:
        if not _env_bool("QM_ENTRY_HOURS_ENABLED", "1"):
            return True, "entry_hours_disabled"
        h_start = int(os.getenv("QM_ENTRY_HOUR_START", "7") or 7)
        h_end = int(os.getenv("QM_ENTRY_HOUR_END", "17") or 17)
        now = now_utc or _now_utc()
        h = now.hour
        if h_start <= h < h_end:
            return True, "entry_hours_ok"
        return False, f"entry_hours_blocked:hour={h}:window=[{h_start},{h_end})"
    except Exception as exc:
        return True, f"delegate_exception:entry_hours:{type(exc).__name__}"


def _delegate_one_book_coherence(pair: str, side: str) -> Tuple[bool, str]:
    """ONE_BOOK_GUARD / COHERENCE — block opposing same-pair fires.

    2026-10-05 operator ruling (second pass): GBPUSD may hold one long +
    one short (ceiling still 2 via the aggregate position cap enforced
    in trade_executor.execute_trade). The relaxation is scoped to
    GBPUSD; other pairs stay strict. Kill switch
    ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD=0 reverts to prior behaviour.

    The continue-or-reverse path (continue_or_reverse.decide →
    close_position → execute_trade) still works unchanged: it closes
    the existing position FIRST, so the submission sees no opposing
    position regardless of the flag.
    """
    try:
        if not _env_bool("ONE_BOOK_GUARD", "1"):
            return True, "one_book_disabled"
        if (
            pair.upper() == "GBPUSD"
            and _env_bool("ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD", "1")
        ):
            return True, "one_book_relaxed_gbpusd"
        # Import inside function so this module is importable in tests
        # without pulling trade_executor and its heavy chain.
        import trade_executor as _te
        opposite = "SELL" if side.upper() in ("LONG", "BUY") else "BUY"
        n = _te.count_open_positions_by_pair_direction(pair.upper(), opposite)
        if int(n or 0) > 0:
            return False, f"coherence_block:opposing_open_count={n}"
        return True, "coherence_ok"
    except Exception as exc:
        return True, f"delegate_exception:one_book:{type(exc).__name__}"


def _delegate_system_grind(
    pair: str,
    side: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """SYSTEM_GRIND — Phase 2 (operator-system build 2026-10-06).

    Admits a ONE_STRATEGY candidate only when:
      * SYSTEM_DAY_MODE_ENABLED resolves to GRIND for today
        (BIG_NEWS / PRE_NEWS / POST_NEWS calendar label), AND
      * the view direction is established (V1 pressure + yesterday's
        dollar direction agree — carried as ``view.direction.agree``
        + ``view.direction.v1_pressure_direction``), AND
      * Stage 9's demonstrated_direction maps to the SAME UP/DOWN as
        the view, AND
      * the candidate's SIDE matches that direction (BUY ↔ UP,
        SELL ↔ DOWN).

    In REVERSAL mode (NORMAL / MID_NEWS) ONE_STRATEGY is uniformly
    refused.

    In UNKNOWN mode (classify failure or SYSTEM_DAY_MODE_ENABLED off
    — the caller should not have reached us in that case, but the
    delegate stays conservative) the delegate is a pass-through.
    """
    try:
        import system_day_mode as _sdm
        mode_block = _sdm.current_mode(
            now_utc or datetime.now(timezone.utc), emit_log=False,
        )
    except Exception as exc:  # noqa: BLE001
        return True, f"system_day_mode_exception:{type(exc).__name__}"
    mode = (mode_block or {}).get("mode")
    if mode == "REVERSAL":
        return False, "mode=REVERSAL:one_strategy_blocked"
    if mode != "GRIND":
        return True, f"mode={mode}:pass_through"
    # Mode = GRIND. Resolve the view's established direction.
    try:
        import view_builder as _vb
        today = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
        view = _vb.read_view(today)
    except Exception as exc:  # noqa: BLE001
        return True, f"view_read_exception:{type(exc).__name__}"
    direction = (view or {}).get("direction") or {}
    if not direction.get("agree"):
        return False, "view_direction_not_agreed:v1_vs_dollar"
    v1_dir = direction.get("v1_pressure_direction")
    if v1_dir not in ("UP", "DOWN"):
        return False, f"view_direction_unresolved:{v1_dir}"
    # Stage 9 demonstrated_direction.
    try:
        stage9 = _demonstrated_direction(pair)
    except Exception as exc:  # noqa: BLE001
        return True, f"demonstrated_direction_exception:{type(exc).__name__}"
    if stage9 not in ("BUY", "SELL"):
        return False, f"stage9_direction_unresolved:{stage9}"
    stage9_up_down = "UP" if stage9 == "BUY" else "DOWN"
    if stage9_up_down != v1_dir:
        return False, f"stage9_vs_view_mismatch:stage9={stage9_up_down}:view={v1_dir}"
    side_up_down = "UP" if str(side).upper() == "BUY" else "DOWN"
    if side_up_down != v1_dir:
        return False, f"side_vs_view_mismatch:side={side_up_down}:view={v1_dir}"
    return True, f"grind_aligned:v1={v1_dir}:stage9={stage9_up_down}"


def _delegate_daily_loss_stop(
    now_utc: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """DAILY_LOSS_STOP — operator-configurable daily loss cap.

    Default: UNSET → disabled → always allow (pass-through). The
    operator sets ``DAILY_LOSS_STOP_GBP`` to the magnitude of the cap
    in GBP (e.g. ``50`` or ``-50`` for £50). When today's realised PnL
    (summed from ``logs/unified_trades.jsonl`` CLOSE rows) reaches
    ``-cap``, every new entry is refused for the rest of the FX
    trading day.

    Fail-closed when enabled (Session 4 §0, 2026-10-05): if the cap is
    configured but ``should_block`` cannot verify realised PnL,
    ``daily_loss_stop`` already returns ``(True, "fail_closed:<Exc>")``
    and sends one Telegram alert per FX day. The outer except here
    only catches harness-level faults (import failure etc.) and
    remains permissive for them — if the module itself is missing,
    the cap cannot have been active in the first place.
    """
    try:
        import daily_loss_stop as _dls
        blocked, reason = _dls.should_block(now_utc)
        if blocked:
            return False, reason
        return True, reason
    except Exception as exc:
        return True, f"delegate_exception:daily_loss_stop:{type(exc).__name__}"


def _delegate_news_post_lockout(pair: str, strategy: str = "") -> Tuple[bool, str]:
    """NEWS_POST_LOCKOUT — post-release chokepoint.

    Delegates to news_release_window.is_in_post_release_lockout — the
    same call trade_executor.execute_trade makes internally
    (trade_executor.py:1389). Respects the same exempt-strategy prefixes
    as the live path.
    """
    try:
        # Exemption list mirrors trade_executor._NEWS_LOCKOUT_EXEMPT_PREFIXES
        # (trade_executor.py:1381-1384). Kept in sync via unit test.
        exempt_prefixes = (
            "NEWS_TICK", "NEWS_STRATEGY", "NEWS_CONT_LEG",
            "GBPUSD_LEVEL_BOUNCE",
        )
        strat_up = str(strategy or "").upper()
        if any(strat_up.startswith(p) for p in exempt_prefixes):
            return True, f"news_post_lockout_exempt:{strat_up}"
        from datetime import datetime as _dt_nl, timezone as _tz_nl
        try:
            from news_release_window import is_in_post_release_lockout
            blocked, reason = is_in_post_release_lockout(
                _dt_nl.now(_tz_nl.utc)
            )
        except Exception as exc:
            # Live path also fails-open on import — mirror exactly.
            return True, f"news_post_lockout_import_failed:{type(exc).__name__}"
        if blocked:
            return False, f"news_post_lockout_active:{reason}"
        return True, "news_post_lockout_ok"
    except Exception as exc:
        return True, f"delegate_exception:news_lockout:{type(exc).__name__}"


def _delegate_concurrent_cap(strategy: str, epic: str) -> Tuple[bool, str]:
    """Per-strategy concurrent cap check.

    Delegates to strategy_logic._resolve_concurrent_cap +
    strategy_logic._count_open_positions to mirror the current live
    check exactly.
    """
    try:
        import strategy_logic as _sl
        cap = _sl._resolve_concurrent_cap(strategy)
        if cap is None:
            return True, "concurrent_cap_exempt"
        cur = _sl._count_open_positions(epic, strategy)
        if cur >= cap:
            return False, f"concurrent_cap_reached_{cur}_{cap}"
        return True, f"concurrent_cap_ok_{cur}_{cap}"
    except Exception as exc:
        return True, f"delegate_exception:cap:{type(exc).__name__}"


def _candidate_bucket(candidate: Any) -> int:
    """Compute the 5-minute bucket integer for a candidate.

    Extracted so `_delegate_bucket_dedup` and `_make_reservation` share
    one definition — QM SAFETY WIRING Item 1 (2026-09-14) uses the
    reservation's bucket to reject a same-bucket concurrent candidate.
    Falls back to now-UTC if the candidate has no parseable ts.
    """
    from datetime import datetime as _dt_bd
    ts_raw = str(
        getattr(candidate, "first_detected_ts", "")
        or getattr(candidate, "timestamp", "")
    )
    try:
        return int(_dt_bd.fromisoformat(
            ts_raw.replace("Z", "+00:00")
        ).timestamp()) // 300
    except Exception:
        return int(_now_utc().timestamp()) // 300


def _find_bucket_reservation(
    pair: str, epic: str, bucket: int, exclude_cid: str,
) -> Optional["_Reservation"]:
    """Return any live reservation (occupied or not, non-expired) for
    the same (pair, epic, bucket), excluding one matching `exclude_cid`.

    QM SAFETY WIRING Item 1 (2026-09-14). Called under `_LOCK`."""
    for r in _RESERVATIONS.values():
        if r.candidate_id == exclude_cid:
            continue
        if r.pair != pair or r.epic != epic:
            continue
        if r.bucket is None or int(r.bucket) != int(bucket):
            continue
        return r
    return None


def _delegate_bucket_dedup(candidate: Any, provider: Optional[Any] = None) -> Tuple[bool, str]:
    """ONE_ENTRY_PER_BUCKET check.

    Delegates to an installed state provider (typically the AutoBot
    instance registered at boot via install_state_provider). Without a
    provider, this reports 'no_state_provider' — permissive so the
    shadow can never invent a block.

    Provider contract:
        provider.bucket_key(symbol, epic) -> str
        provider.last_entry_attempt_bucket_for(key) -> Optional[int]
        provider.one_entry_per_bucket_enabled() -> bool

    QM SAFETY WIRING Item 1 (2026-09-14) — the provider's
    `last_entry_attempt_bucket_for` marker is set only AFTER
    `execute_trade` returns a confirmed-open (autobot.py:6263). Between
    gate approval and that mark, a SECOND arm event on the same bucket
    would find `last_entry_attempt_bucket_for = None` and slip through
    (the "duplicate arm" defect that produced two IG deals at 2026-09-14
    14:25:00/01 for candidate 1d869d3ba6d84c...). To close that race
    this delegate additionally consults the reservation ledger: if a
    live reservation exists for the same (pair, epic, bucket) — even if
    the trade has not yet been confirmed open — the incoming candidate
    is rejected with `bucket_dedup_reservation_active`.
    """
    try:
        p = provider or _state_provider()
        pair = str(getattr(candidate, "pair", "") or "").upper()
        epic = str(getattr(candidate, "epic", "") or "")
        cid = str(getattr(candidate, "candidate_id", "") or "")
        cand_bucket = _candidate_bucket(candidate)

        # QM SAFETY WIRING Item 1 — reservation-ledger check runs FIRST,
        # since it catches the within-process concurrent-emit race the
        # provider-marker check cannot see (marker is post-fill).
        with _LOCK:
            _prune_expired()
            active = _find_bucket_reservation(pair, epic, cand_bucket, cid)
        if active is not None:
            return False, (
                f"bucket_dedup_reservation_active:bucket={cand_bucket}"
                f":rid={active.reservation_id[:12]}"
            )

        if p is None:
            return True, "bucket_dedup_no_state_provider"
        try:
            enabled = bool(p.one_entry_per_bucket_enabled())
        except Exception:
            enabled = True
        if not enabled:
            return True, "bucket_dedup_disabled"

        try:
            key = p.bucket_key(pair, epic)
        except Exception:
            key = f"{pair}|{epic}"

        try:
            last_bucket = p.last_entry_attempt_bucket_for(key)
        except Exception:
            last_bucket = None

        if last_bucket is not None and int(last_bucket) == cand_bucket:
            return False, f"bucket_dedup_repeat:bucket={cand_bucket}"
        return True, f"bucket_dedup_ok:bucket={cand_bucket}"
    except Exception as exc:
        return True, f"delegate_exception:bucket_dedup:{type(exc).__name__}"


def _delegate_cooldown(candidate: Any, provider: Optional[Any] = None) -> Tuple[bool, str]:
    """Per-strategy cooldown.

    Delegates to the state provider when available. Falls back to
    reading `cache/last_trade_times.json` directly (persisted state)
    when no provider is installed. Never returns False on missing data
    — that would invent a block the live path wouldn't produce.
    """
    try:
        p = provider or _state_provider()
        pair = str(getattr(candidate, "pair", "") or "").upper()
        epic = str(getattr(candidate, "epic", "") or "")
        key = f"{pair}|{epic}"
        try:
            if p is not None:
                key = p.bucket_key(pair, epic)
        except Exception:
            pass

        cooldown_s = int(os.getenv("COOLDOWN_SECONDS", "0") or 0)
        if cooldown_s <= 0:
            return True, "cooldown_disabled"

        last_ts: Optional[float] = None
        try:
            if p is not None:
                last_ts = p.last_trade_ts_for(key)
        except Exception:
            last_ts = None

        if last_ts is None:
            # Fall back to reading the persistent cache file.
            try:
                import json as _json
                cache_path = os.getenv(
                    "LAST_TRADE_TIMES_PATH",
                    "/opt/tradingbot/cache/last_trade_times.json",
                )
                with open(cache_path, "r") as fh:
                    raw = _json.load(fh)
                if isinstance(raw, dict):
                    v = raw.get(key)
                    if v is not None:
                        last_ts = float(v)
            except Exception:
                last_ts = None

        if last_ts is None:
            return True, "cooldown_no_prior_trade"

        import time as _time
        elapsed = _time.time() - float(last_ts)
        if elapsed < cooldown_s:
            return False, (
                f"cooldown_active:remaining_s={cooldown_s - int(elapsed)}"
            )
        return True, f"cooldown_ok:elapsed_s={int(elapsed)}"
    except Exception as exc:
        return True, f"delegate_exception:cooldown:{type(exc).__name__}"


# ── State-provider registration hook ───────────────────────────────────────
# AutoBot installs itself as the state provider at boot. Gate delegates
# then read bucket/cooldown state without imposing a hard import cycle.
_STATE_PROVIDER: Optional[Any] = None


def install_state_provider(provider: Any) -> None:
    """Register a state provider for bucket_dedup + cooldown delegates.

    The provider must expose:
        one_entry_per_bucket_enabled() -> bool
        bucket_key(pair: str, epic: str) -> str
        last_entry_attempt_bucket_for(key: str) -> Optional[int]
        last_trade_ts_for(key: str) -> Optional[float]

    Never raises. Repeated installs replace the previous provider.
    """
    global _STATE_PROVIDER
    _STATE_PROVIDER = provider
    logger.info("[GATE] state provider installed: %s", type(provider).__name__)


def _state_provider() -> Optional[Any]:
    return _STATE_PROVIDER


def clear_state_provider() -> None:
    """Test hook — remove any installed provider."""
    global _STATE_PROVIDER
    _STATE_PROVIDER = None


# ── Opposing-level gate delegate ─────────────────────────────────────
# QM SAFETY WIRING Item 3 (2026-09-14). With the bounce overlay wired
# live (Item 2), the classifier stamps `bounce_state` /
# `bounce_direction` on every 5m close. This delegate rejects a
# candidate whose direction opposes an active level-rejection signal.
# TWO strictness modes are both implemented; operator selects at
# runtime via `OPPOSING_LEVEL_GATE_MODE`:
#
#   * "OFF" (default) — delegate returns True with
#     "opposing_level_off"; no reason stamp for downstream analysis.
#   * "SHADOW" — evaluate but never reject; when the walk would have
#     blocked, stamp "opposing_level_shadow_would_block:<MODE>:<code>:<state>".
#     The operator uses this to gather report-only evidence.
#   * "STRICT" — reject when the classifier's active bounce state is
#     any of `_OPPOSING_STRICT_STATES` AND the bounce direction opposes
#     the candidate direction. Reason:
#     "OPPOSING_LEVEL_TEST:<state>:<level_id>" (or the stronger
#     "OPPOSING_BOUNCE_CONFIRMED:..." when the state is
#     BOUNCE_CONFIRMED / REVERSAL_CONFIRMED).
#   * "PERMISSIVE" — reject only when state is BOUNCE_CONFIRMED or
#     REVERSAL_CONFIRMED. Reason:
#     "OPPOSING_BOUNCE_CONFIRMED:<state>:<level_id>".
#
# The two reason-code families ("OPPOSING_LEVEL_TEST",
# "OPPOSING_BOUNCE_CONFIRMED") are distinct so replays can be
# classified without parsing the trailing state suffix.

_OPPOSING_STRICT_STATES = frozenset({
    "MAJOR_LEVEL_TEST",
    "LEVEL_HOVER",
    "BOUNCE_FORMING",
    "BOUNCE_CONFIRMED",
    "REVERSAL_FORMING",
    "REVERSAL_CONFIRMED",
})
_OPPOSING_PERMISSIVE_STATES = frozenset({
    "BOUNCE_CONFIRMED",
    "REVERSAL_CONFIRMED",
})


def _delegate_opposing_level(candidate: Any) -> Tuple[bool, str]:
    """QM SAFETY Item 3 — reject a candidate whose direction opposes an
    active level bounce/rejection. Two strictness modes, one delegate.

    Behaviour is off by default (mode=OFF). Operator flips
    `OPPOSING_LEVEL_GATE_MODE` to SHADOW/STRICT/PERMISSIVE to activate.

    Fails permissive on any exception.
    """
    try:
        mode = str(os.getenv("OPPOSING_LEVEL_GATE_MODE", "OFF") or "OFF").upper()
        if mode not in ("SHADOW", "STRICT", "PERMISSIVE"):
            return True, "opposing_level_off"

        # Pre-authorised direction authorities (2026-10-03 amendment).
        # ONE_STRATEGY takes direction from Stage 9 natively;
        # V2_PICK_BOUNCE from the Stage 9 alignment check at
        # qm_v2_executor._fire_route. Neither should be re-vetoed on
        # direction by the opposing-level check (whose job is to catch
        # legacy families fighting a confirmed bounce).
        _fam_ol = _resolve_family(candidate)
        if _fam_ol == "ONE_STRATEGY":
            return True, "one_strategy_pre_authorised_direction"
        if _fam_ol == "V2_PICK_BOUNCE":
            return True, "v2_pick_pre_authorised_direction"

        pair = str(getattr(candidate, "pair", "") or "").upper()
        side = str(getattr(candidate, "side", "") or "").upper()
        cand_dir = _map_side_to_direction(side)
        if cand_dir is None:
            return True, f"opposing_level_side_unknown:{side or 'empty'}"

        import news_trend_classifier as _ntc
        snap = _ntc.snapshot(pair)
        bstate = snap.get("bounce_state")
        bdir = snap.get("bounce_direction")
        blvl = snap.get("bounce_level_id") or "unknown"
        if bstate is None or bstate == "BOUNCE_NONE" or bdir is None:
            return True, "opposing_level_no_active_bounce"

        # Opposing = candidate direction differs from bounce direction.
        # A BUY bounce (support test rejecting price up) opposes a SELL
        # candidate; a SELL bounce opposes a BUY candidate.
        if str(cand_dir).upper() == str(bdir).upper():
            return True, f"opposing_level_aligned:{bstate}"

        strict_hit = bstate in _OPPOSING_STRICT_STATES
        permissive_hit = bstate in _OPPOSING_PERMISSIVE_STATES

        if not strict_hit and not permissive_hit:
            # State is e.g. TREND_PULLBACK_ONLY — not an active opposing
            # signal even under STRICT.
            return True, f"opposing_level_state_not_gated:{bstate}"

        if mode == "STRICT" and strict_hit:
            code = ("OPPOSING_BOUNCE_CONFIRMED"
                    if permissive_hit else "OPPOSING_LEVEL_TEST")
            return False, f"{code}:{bstate}:{blvl}"

        if mode == "PERMISSIVE" and permissive_hit:
            return False, f"OPPOSING_BOUNCE_CONFIRMED:{bstate}:{blvl}"

        # SHADOW or mode-mismatched (STRICT with only permissive_hit is
        # not possible since permissive⊆strict; PERMISSIVE with strict_hit
        # but not permissive_hit → the strict-only states like
        # BOUNCE_FORMING that don't warrant a permissive-mode block).
        if mode == "SHADOW":
            if permissive_hit:
                return True, (
                    "opposing_level_shadow_would_block:PERMISSIVE:"
                    f"OPPOSING_BOUNCE_CONFIRMED:{bstate}:{blvl}"
                )
            if strict_hit:
                return True, (
                    "opposing_level_shadow_would_block:STRICT:"
                    f"OPPOSING_LEVEL_TEST:{bstate}:{blvl}"
                )
        return True, f"opposing_level_pass:{bstate}:{blvl}"
    except Exception as exc:
        return True, (
            f"delegate_exception:opposing_level:{type(exc).__name__}"
        )


def _delegate_sl_block(candidate: Any) -> Tuple[bool, str]:
    """SL block state — reads cache/sl_blocks.json. Best-effort."""
    try:
        pair = str(getattr(candidate, "pair", "") or "").upper()
        epic = str(getattr(candidate, "epic", "") or "")
        side = str(getattr(candidate, "side", "") or "")
        direction = "BUY" if side.upper() in ("LONG", "BUY") else "SELL"
        import autobot as _ab
        rem = _ab._sl_block_remaining(pair, epic, direction)
        if rem and float(rem) > 0:
            return False, f"sl_block_active:remaining_s={float(rem):.0f}"
        return True, "sl_block_ok"
    except Exception as exc:
        return True, f"delegate_exception:sl_block:{type(exc).__name__}"


def _delegate_mechanical(candidate: Any) -> Tuple[bool, str]:
    """Mechanical validity — Candidate self-reports.

    A detector-side mechanical failure (bad price, missing snapshot)
    sets Candidate.mechanical_valid=False. The gate rejects those but
    still logs them for corpus completeness.
    """
    try:
        if bool(getattr(candidate, "mechanical_valid", True)):
            return True, "mechanical_ok"
        return False, "mechanical_invalid"
    except Exception as exc:
        return True, f"delegate_exception:mechanical:{type(exc).__name__}"


def _delegate_ml_veto(candidate: Any) -> Tuple[bool, str]:
    """Phase 14 ML-veto delegate — shadow by default, live per ML_VETO_LIVE.

    Wraps ml_veto.veto_delegate so the gate can consult the setup-quality
    LightGBM model. Contract mirrors ml_veto.veto_delegate:

      * ML_VETO_LIVE=0 or missing model → returns
        (True, 'ml_veto:disabled:no_model' | 'ml_veto:shadow_ok:...' |
              'ml_veto:shadow:p_loss=...'). Never blocks. Byte-identical
        `allowed` outcome vs pre-wiring — only a new reason-code stamp.
      * ML_VETO_LIVE=1 → evaluates. Returns
        (False, 'ml_veto:live_block:p_loss>=thresh=...') when the
        prediction exceeds threshold; else (True, 'ml_veto:live_ok:...').

    Features plumbing (candidate → feature dict matching the trained
    schema) is deferred to a follow-up; for now the candidate carries
    no bundle, so ml_veto stamps `ml_veto:shadow_ok:no_features` at
    flag=0 — a legitimate NO_OBJECTION with a visible reason. This
    keeps the delegate present + inspectable without changing live
    behaviour, per the wiring rule.
    """
    try:
        import ml_veto as _mlv
    except Exception as exc:
        return True, f"delegate_exception:ml_veto_import:{type(exc).__name__}"
    try:
        features_bundle = getattr(candidate, "ml_veto_features", None)
        features: Optional[Dict[str, float]] = None
        if isinstance(features_bundle, dict):
            features = {str(k): float(v) for k, v in features_bundle.items()
                         if isinstance(v, (int, float))}
        return _mlv.veto_delegate(features)
    except Exception as exc:
        return True, f"delegate_exception:ml_veto:{type(exc).__name__}"


def _delegate_observation(
    pair: str, now_utc: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """Mandatory-observation delegate (spec §12, Phase 3).

    Reads observation_tracker.resolve(pair). Emits:
      * ok=True,  reason='observation_ok'                 (OBSERVED)
      * ok=(not gate active), reason='insufficient_observation:...' (UNKNOWN)

    The reason string is stamped on the candidate row regardless of
    the flag — shadow-mode telemetry always. Only ENFORCEMENT is
    flag-gated by OBSERVATION_GATE_ENABLED.

    Fails permissive: any exception yields ok=True with a
    `delegate_exception:observation:<Type>` reason so the shadow
    cannot invent a new block.
    """
    try:
        import observation_tracker as _obs
        snap = _obs.resolve(pair, now_utc)
        state = snap.get("state") or _obs.STATE_UNKNOWN
        reason = str(snap.get("reason") or "observation_unresolved")
        if state == _obs.STATE_OBSERVED:
            return True, "observation_ok"
        # UNKNOWN — enforce only if the gate flag is on.
        if observation_gate_active():
            return False, reason
        return True, reason
    except Exception as exc:
        return True, f"delegate_exception:observation:{type(exc).__name__}"


def observation_snapshot(
    pair: str, now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pass-through of observation_tracker.resolve — used by the
    orchestrator to plumb the three telemetric fields into the corpus
    row without importing observation_tracker there directly.

    Never raises. On error returns a UNKNOWN-shaped stub.
    """
    try:
        import observation_tracker as _obs
        return _obs.resolve(pair, now_utc)
    except Exception as exc:
        return {
            "symbol": str(pair or "").upper(),
            "state": "UNKNOWN",
            "bars_observed": 0,
            "elapsed_observation_s": 0,
            "min_time_s": None,
            "min_bars": None,
            "session_origin_ts": None,
            "process_start_ts": None,
            "reason": f"delegate_exception:observation:{type(exc).__name__}",
        }


_NEWS_FAMILY_CANONICALS = frozenset({
    "BIG_NEWS", "BIG_NEWS_MINUS_1", "BIG_NEWS_PLUS_1",
})

# A9 (2026-09-13): only these two states constitute an active,
# price-confirmed trend for counter-trend exclusion. TREND_FORMING /
# TREND_EXTENDED / TREND_WEAKENING / NO_CLEAR_TREND all restore
# ordinary permissions (A9.2 exhaustion / decay clause).
_ACTIVE_TREND_STATES = frozenset({"TREND_UP", "TREND_DOWN"})

# A9 binding slot interpretation (2026-09-13): the primary news-trend
# slot is consumed only by the news-trend route's accepted trade —
# the news-family strategies below. Aligned candidates from other
# families remain governed by the total cap, ordinary family limits,
# and entry-quality controls, but do NOT consume the primary slot.
#
# 2026-09-14 (Item 3 correction): NEWS_TREND is the specialist
# news-trend emitter (news_trend_entry.py; candidate.py:56
# FAMILY_NEWS_TREND) whose whole purpose is to compete for the §19
# primary slot. Its absence from this set was a wiring gap: the
# emitter's candidates were being stamped
# direction_agree_non_news_family and passing through without
# reserving primary. Added here so §19 slot arithmetic covers the
# specialist route end-to-end.
_NEWS_TREND_ROUTE_FAMILIES = frozenset({
    "NEWS_STRATEGY", "NEWS_TICK", "NEWS_CONTINUATION", "NEWS_TREND",
})


def _canonical_day_type_now() -> Optional[str]:
    """Best-effort read of the canonical day-type. Never raises."""
    try:
        import day_type_adapter as _dta
        return _dta.resolve().get("canonical")
    except Exception:
        return None


def _map_side_to_direction(side: str) -> Optional[str]:
    """LONG/BUY → BUY, SHORT/SELL → SELL, else None."""
    s = str(side or "").upper()
    if s in ("LONG", "BUY"):
        return "BUY"
    if s in ("SHORT", "SELL"):
        return "SELL"
    return None


def _classify_news_direction_a10_stamp(reason: str) -> Optional[str]:
    """A10 (2026-09-14) — map the raw news_direction delegate reason
    to one of the three A10 stamps for the final gate receipt:

      * A10_NO_ACTIVE_TREND                     news day, no active trend
      * A10_WITH_TREND                          aligned or §26 admission
      * A10_COUNTER_TREND_DURING_ACTIVE_TREND   counter-trend rejected

    Returns None for mechanical / off-route stamps that carry no
    trend verdict (blackout, off-route, side unknown, delegate
    exceptions). The gate still records these under the standard
    `news_direction:<reason>` code — only the A10 verdict stamp is
    routed through this classifier.
    """
    r = str(reason or "")
    if not r:
        return None
    if r.startswith("news_direction_off_route"):
        return None
    if r.startswith("news_direction_side_unknown"):
        return None
    if r.startswith("delegate_exception"):
        return None
    if r.startswith("NEWS_RELEASE_BLACKOUT") or r.startswith("news_release_blackout"):
        return None
    if r.startswith("news_no_active_trend"):
        return A10_NO_ACTIVE_TREND
    if r.startswith("direction_agree"):
        return A10_WITH_TREND
    if r.startswith("direction_counter_trend_with_bounce_event"):
        # §26 confirmed-exhaustion admission — the counter-trend
        # candidate is admitted under the exhaustion exception.
        return A10_WITH_TREND
    if r.startswith("direction_counter_trend"):
        return A10_COUNTER_TREND_DURING_ACTIVE_TREND
    if r.startswith("NEWS_BOUNCE_EVENT_ALREADY_CONSUMED"):
        return A10_COUNTER_TREND_DURING_ACTIVE_TREND
    if r.startswith("NEWS_BOUNCE_SLOT_USED"):
        return A10_COUNTER_TREND_DURING_ACTIVE_TREND
    if r.startswith("NEWS_STATE_RECLASSIFIED_SINCE_CANDIDATE"):
        return A10_COUNTER_TREND_DURING_ACTIVE_TREND
    if r.startswith("NEWS_PRIMARY_TRADE_USED") or r.startswith("NEWS_TOTAL_CAP_REACHED"):
        # Slot exhaustion after direction alignment — the candidate WAS
        # aligned with the trend but exhausted its slot capacity.
        return A10_WITH_TREND
    return None


def _demonstrated_direction(pair: str) -> Optional[str]:
    """Build-1 A1 (2026-10-04) — direction supply is the Layer-2
    ``direction_state`` state machine. Returns the trading-side
    demonstrated price-derived direction that governs
    TRADABLE_NON_RANGE alignment for ``pair``, or None when not
    explicitly established.

    Wiring (production caller: ``_delegate_normal_routing`` at line
    1284, on the positive matrix-lookup branch for the four
    TRADABLE_NON_RANGE-admitted families — TREND_V3, EMA_PULLBACK,
    STRUCTURE_BREAK, CONFIRMATION_FALLBACK):

      * Source of truth: ``direction_state.update_from_production(pair)``
        — Build-1 single direction producer (Reference B §2, design-note
        A1). Internally advances the Layer-2 state machine from the
        persisted 5m tail and returns a snapshot with
        ``pair_direction`` in {UP, DOWN, NONE} and ``knowledge`` in
        {VALID, UNKNOWN}.
      * UP → BUY, DOWN → SELL under VALID knowledge. ``UNKNOWN`` or
        ``NONE`` → return None.

    Semantics (STRICT):
      * ``BUY`` / ``SELL`` — explicit demonstrated direction.
      * ``None`` — missing, unknown, neutral, unavailable, or unmapped.
        Callers MUST NOT treat None as permissive alignment; the
        TRADABLE_NON_RANGE-admitted families reject with
        ``DIRECTION_NOT_ESTABLISHED`` when direction is None.

    Any exception is treated as "not established" — a downstream bug
    in direction_state fails closed (REJECT / DIRECTION_NOT_ESTABLISHED)
    rather than inventing a new admission.

    Stage-3 (2026-10-12) belt-and-suspenders: while an NMS replay is
    running for this pair, treat direction as not-yet-authoritative.
    The replay path is read-only to NMS but the live gate must not
    treat replay-updated state as production truth. This is
    defence-in-depth — the primary isolation is that replay_warmup_
    bars does not route through live callbacks — but the gate's own
    check closes the window where a stale snapshot could leak into
    an admission decision mid-replay.
    """
    try:
        import normal_market_state as _nms_rip
        if _nms_rip.is_replay_in_progress(pair):
            return None
    except Exception:
        # NMS not importable (worktree without the module) — fall
        # through to direction_state. The invariant is only violable
        # if NMS is importable AND a replay is running; in all other
        # cases the pre-Stage-3 behaviour is preserved.
        pass
    try:
        import direction_state as _ds
        snap = _ds.update_from_production(pair)
        if getattr(snap, "knowledge", "UNKNOWN") != "VALID":
            return None
        d = getattr(snap, "pair_direction", None)
        if d == "UP":
            return "BUY"
        if d == "DOWN":
            return "SELL"
        return None
    except Exception:
        return None


def _delegate_news_direction(
    pair: str,
    side: str,
    now_utc: Optional[datetime] = None,
    *,
    candidate: Any = None,
) -> Tuple[bool, str]:
    """News-family direction + slot delegate — Amendment A9 (2026-09-13).

    A9 permission model:
      * Day-type biases search; only price-confirmed active trends
        (state in {TREND_UP, TREND_DOWN}) exclude counter-trend
        candidates.
      * NEWS_NO_CLEAR_TREND is no longer a rejection reason. Absence
        of a confirmed trend on a news-family day routes candidates
        to ordinary market-state × family × entry-quality evaluation.
      * Only news-trend route families (NEWS_STRATEGY / NEWS_TICK /
        NEWS_CONTINUATION / NEWS_TREND) consume the primary news-trend
        slot.
        Aligned candidates from other families remain governed by the
        total cap, family limits and downstream delegates but do not
        consume that primary slot.
      * The ±30-minute mechanical release blackout is preserved and
        precedes the direction check.
      * §26/§28/§30 bounce admission (with release-bar quarantine)
        remains for counter-trend candidates during an active trend.

    Emits (allowed=True unless noted):

    Off-route / no-op stamps:
      * `news_direction_off_route`               non-news day
      * `news_no_active_trend:<state>`           news day, no active trend (A9.1/A9.2)
      * `news_direction_side_unknown:<state>`    unmapped side
      * `delegate_exception:news_direction:<Type>`

    Active-trend approval stamps:
      * `direction_agree:<state>`                news-trend family, shadow
      * `direction_agree_non_news_family:<state>` non-news family, shadow
      * `direction_agree_primary_slot_ok:<state>` news-trend family, router-on
      * `direction_counter_trend_with_bounce_event:<bstate>:<event_id>`

    Router-active reject codes (NEWS_TREND_ROUTER=1, active trend only):
      * `direction_counter_trend:<state>`         counter-trend rejected
      * `NEWS_STATE_RECLASSIFIED_SINCE_CANDIDATE:<from>-><to>`
      * `NEWS_PRIMARY_TRADE_USED:<state>`         §19 primary consumed
      * `NEWS_TOTAL_CAP_REACHED:<state>`          §27 total cap reached
      * `NEWS_BOUNCE_EVENT_ALREADY_CONSUMED:<event_id>`
      * `NEWS_BOUNCE_SLOT_USED:<state>`
      * mechanical release blackout reason string, always.

    Slot consumption is NOT performed here — the reservation carries
    the news_slot_kind/bounce_event_id so `confirm_execution()` records
    to the ledger only when the broker actually fills.

    Fails permissive on any exception.
    """
    try:
        # Stage 11 (2026-09-26, amended 2026-10-03): FAMILY_ONE_STRATEGY
        # and FAMILY_V2_PICK_BOUNCE both carry direction resolved by
        # Stages 8-9 (ONE_STRATEGY natively; V2_PICK via the Stage-9
        # alignment check at qm_v2_executor._fire_route). The
        # news-direction router must not re-veto either on direction.
        # News-side rationing (slot consumption / release blackout /
        # post-lockout) is enforced by the OTHER delegates
        # (news_post_lockout, capacity, bucket_dedup) which run unchanged.
        if candidate is not None:
            _fam = _resolve_family(candidate)
            if _fam == "ONE_STRATEGY":
                return True, "one_strategy_pre_authorised_direction"
            if _fam == "V2_PICK_BOUNCE":
                return True, "v2_pick_pre_authorised_direction"
        canon = _canonical_day_type_now()
        if canon not in _NEWS_FAMILY_CANONICALS:
            return True, "news_direction_off_route"
        import news_trend_classifier as _ntc
        import news_slot_ledger as _slots

        snap = _ntc.snapshot(pair)
        primary = snap.get("primary_direction")
        # A9 (2026-09-13): the counter-trend exclusion is driven by
        # the underlying trend-half state (TREND_UP / TREND_DOWN), not
        # by the Phase 5 overlay state (MAJOR_LEVEL_TEST /
        # BOUNCE_FORMING / etc.). When the overlay is active,
        # `state` reflects the overlay but `trend_state` preserves the
        # trend-half state — that is what A9.2 governs. Fall back to
        # `state` for shadow-only stamp text.
        trend_state = (
            snap.get("trend_state")
            or snap.get("state")
            or _ntc.NO_CLEAR_TREND
        )
        state = snap.get("state") or _ntc.NO_CLEAR_TREND
        cand_dir = _map_side_to_direction(side)
        router_on = news_trend_router_active()
        epic = str(getattr(candidate, "epic", "") or "")
        cid = str(getattr(candidate, "candidate_id", "") or "")
        family = _resolve_family(candidate)
        _ts = now_utc

        # §50 stale-direction detection metadata.
        old_state = None
        try:
            mss = getattr(candidate, "market_state_snapshot", {}) or {}
            old_state = mss.get("news_trend_state")
        except Exception:
            old_state = None

        # ── Mechanical release blackout (A9 MECHANICAL_RELEASE_BLACKOUT). ─
        try:
            import news_release_blackout as _blk
            in_blk, blk_reason = _blk.is_in_blackout(now_utc)
        except Exception:
            in_blk, blk_reason = False, ""
        if in_blk:
            if router_on:
                return False, blk_reason
            return True, blk_reason

        # ── A9.1/A9.2: no active price-confirmed trend → ordinary
        # NORMAL-day evaluation applies (normal_routing delegate). No
        # rejection, no slot consumption. Includes NO_CLEAR_TREND,
        # TREND_FORMING, and the TREND_EXTENDED / TREND_WEAKENING
        # decay states — A9.2 exhaustion clause. The check is on the
        # trend-half state (`trend_state`) so the Phase 5 overlay
        # (MAJOR_LEVEL_TEST etc.) does not spuriously mask an active
        # underlying trend.
        active_trend = (
            trend_state in _ACTIVE_TREND_STATES and primary is not None
        )
        if not active_trend:
            return True, f"news_no_active_trend:{trend_state}"

        # Guard: side unknown.
        if cand_dir is None:
            return True, f"news_direction_side_unknown:{state}"

        # ── Counter-trend during active trend. ──────────────────────
        if cand_dir != primary:
            bstate = snap.get("bounce_state")
            bdir = snap.get("bounce_direction")
            bevent = snap.get("bounce_event_id")
            has_live_bounce = (
                bstate in ("BOUNCE_CONFIRMED", "REVERSAL_CONFIRMED")
                and bdir == cand_dir
                and isinstance(bevent, str) and bevent
            )
            if has_live_bounce:
                try:
                    ev_ts = _blk.event_start_ts_from_bounce_id(bevent)
                    q_hit, q_reason = _blk.is_event_quarantined(
                        ev_ts, now_utc,
                    )
                except Exception:
                    q_hit, q_reason = False, ""
                if q_hit:
                    if router_on:
                        return False, q_reason
                    return True, q_reason
                if not router_on:
                    return True, (
                        "direction_counter_trend_with_bounce_event:"
                        f"{bstate}:{bevent}"
                    )
                if _slots.is_bounce_event_consumed(epic, bevent, _ts):
                    return False, (
                        f"NEWS_BOUNCE_EVENT_ALREADY_CONSUMED:{bevent}"
                    )
                if not _slots.is_bounce_available(epic, _ts):
                    return False, f"NEWS_BOUNCE_SLOT_USED:{bstate}"
                if _slots.is_total_cap_reached(epic, _ts):
                    return False, f"NEWS_TOTAL_CAP_REACHED:{state}"
                with _LOCK:
                    _NEWS_EVAL_CTX[cid] = {
                        "kind": "bounce",
                        "direction": cand_dir,
                        "bounce_event_id": bevent,
                    }
                return True, (
                    "direction_counter_trend_with_bounce_event:"
                    f"{bstate}:{bevent}"
                )

            # No live bounce → counter-trend rejection.
            if old_state and old_state != state:
                reason = (
                    f"NEWS_STATE_RECLASSIFIED_SINCE_CANDIDATE:"
                    f"{old_state}->{state}"
                )
                if router_on:
                    return False, reason
                return True, reason
            if router_on:
                return False, f"direction_counter_trend:{state}"
            return True, f"direction_counter_trend:{state}"

        # ── With-trend during active trend. ─────────────────────────
        # A9 binding: only news-trend route families consume the
        # primary slot. Others pass through subject to the total cap.
        is_news_trend_family = family in _NEWS_TREND_ROUTE_FAMILIES
        if not router_on:
            if is_news_trend_family:
                return True, f"direction_agree:{state}"
            return True, f"direction_agree_non_news_family:{state}"

        if is_news_trend_family:
            # §19 primary slot check (only for news-trend family) —
            # ordered ahead of the §27 total-cap check so the reason
            # code identifies the specific slot semantic when both
            # would trip.
            if not _slots.is_primary_available(epic, _ts):
                return False, f"NEWS_PRIMARY_TRADE_USED:{state}"
            if _slots.is_total_cap_reached(epic, _ts):
                return False, f"NEWS_TOTAL_CAP_REACHED:{state}"
            with _LOCK:
                _NEWS_EVAL_CTX[cid] = {
                    "kind": "primary",
                    "direction": cand_dir,
                    "bounce_event_id": None,
                }
            return True, f"direction_agree_primary_slot_ok:{state}"

        # A9 binding: non-news family with-trend candidates remain
        # governed by the total trade cap but do not consume the
        # primary slot. On cap saturation stamp the same
        # NEWS_TOTAL_CAP_REACHED code so the audit trail is uniform.
        if _slots.is_total_cap_reached(epic, _ts):
            return False, f"NEWS_TOTAL_CAP_REACHED:{state}"
        return True, f"direction_agree_non_news_family:{state}"
    except Exception as exc:
        return True, (
            f"delegate_exception:news_direction:{type(exc).__name__}"
        )


# ── Family classification for the MID_NEWS delegate ─────────────────────
# Reads Candidate.strategy_family when present, else infers from
# Candidate.strategy via prefix. Bounded vocabulary from candidate.py
# (FAMILY_* constants). Falls back to FAMILY_UNKNOWN for unrecognised
# names so a bug in a new strategy cannot silently pass MID_NEWS gating.

_MID_NEWS_V2_FAMILIES = frozenset({"QM_V2", "LEVEL_BOUNCE"})
_MID_NEWS_BB_FAMILIES = frozenset({"BB_BOUNCE"})

_STRATEGY_PREFIX_TO_FAMILY = (
    # Order matters — longest prefix first.
    ("GBPUSD_LEVEL_BOUNCE",    "LEVEL_BOUNCE"),
    ("GBPUSD_BB_BOUNCE",       "BB_BOUNCE"),
    ("GBPUSD_TREND_V3",        "TREND_V3"),
    ("GBPUSD_CONFIRMATION_FALLBACK", "CONFIRMATION_FALLBACK"),
    ("GBPUSD_STRUCTURE_BREAK", "STRUCTURE_BREAK"),
    ("GBPUSD_EMA_PULLBACK",    "EMA_PULLBACK"),
    ("GBPUSD_NEWS_TREND",      "NEWS_TREND"),
    ("EMA_PULLBACK",           "EMA_PULLBACK"),
    ("V2_PICK_BOUNCE",         "V2_PICK_BOUNCE"),
    ("QM_REVERSAL",            "QM_REVERSAL"),
    ("QM_V2",                  "QM_V2"),
    ("NEWS_STRATEGY",          "NEWS_STRATEGY"),
    ("NEWS_TICK",              "NEWS_TICK"),
    ("NEWS_TREND",             "NEWS_TREND"),
    ("NEWS_CONTINUATION",      "NEWS_CONTINUATION"),
    ("NEWS_CONT",              "NEWS_CONTINUATION"),
    ("BRIEFING_V5",            "BRIEFING_V5"),
    ("BRIEFING",               "BRIEFING_EXECUTION"),
    ("BB_REV",                 "BB_REVERSAL_PATTERNS"),
    ("H1_PIERCE",              "H1_PIERCE"),
    ("LIQUIDITY_SWEEP",        "LIQUIDITY_SWEEP"),
    ("WINDOW_SWEEP",           "WINDOW_SWEEP"),
    ("PIVOT_BREAK",            "PIVOT_BREAK"),
    ("PIA_FIRST",              "PIA_FIRST"),
)


# Phase 2B (2026-10-27) — AutoBot family → NMS authority family map.
# Authority families are the 5 labels from nms_directional_authority
# (TREND_CONTINUATION / TREND_PULLBACK / BOUNCE_MEAN_REVERSION /
# STRUCTURAL_REVERSAL / SPECIALISED). Families mapped to
# STRUCTURAL_REVERSAL or SPECIALISED fall through with
# applicable=False and preserve their existing admission logic — the
# operator decision is tracked explicitly in Phase 2B §5.
#
# QM_REVERSAL: per Phase 2B audit, this is ALWAYS a reversal (role-
# reversal confirmation = counter-trend by construction) →
# BOUNCE_MEAN_REVERSION (needs CONFIRMED exhaustion against STRONG
# trend; allowed in RANGE/NORMAL/EMERGING).
#
# PIVOT_BREAK: per Phase 2B audit, this is ALWAYS a continuation
# (D1-bias filter aligns direction with D1 trend) →
# TREND_CONTINUATION (needs matching EMERGING/STRONG trend).
_AUTOBOT_FAMILY_TO_AUTHORITY_FAMILY: Dict[str, str] = {
    # TREND_CONTINUATION
    "TREND_V3":                "TREND_CONTINUATION",
    "GBPUSD_TREND_CONT":       "TREND_CONTINUATION",
    "NEWS_TREND":              "TREND_CONTINUATION",
    "NEWS_CONTINUATION":       "TREND_CONTINUATION",
    "BRIEFING_EXECUTION":      "TREND_CONTINUATION",
    "BRIEFING_V5":             "TREND_CONTINUATION",
    "PIVOT_BREAK":             "TREND_CONTINUATION",
    # TREND_PULLBACK
    "EMA_PULLBACK":            "TREND_PULLBACK",
    # BOUNCE_MEAN_REVERSION
    "BB_BOUNCE":               "BOUNCE_MEAN_REVERSION",
    "LEVEL_BOUNCE":            "BOUNCE_MEAN_REVERSION",
    "NEWS_STRATEGY":           "BOUNCE_MEAN_REVERSION",
    "NEWS_TICK":               "BOUNCE_MEAN_REVERSION",
    "QM_REVERSAL":             "BOUNCE_MEAN_REVERSION",
    "LIQUIDITY_SWEEP":         "BOUNCE_MEAN_REVERSION",
    # STRUCTURAL_REVERSAL — operator decision outstanding; the authority
    # returns applicable=False and the existing family admission logic
    # continues unchanged.
    "STRUCTURE_BREAK":         "STRUCTURAL_REVERSAL",
    "CONFIRMATION_FALLBACK":   "STRUCTURAL_REVERSAL",
    "H1_PIERCE":               "STRUCTURAL_REVERSAL",
    "BB_REVERSAL_PATTERNS":    "STRUCTURAL_REVERSAL",
    "WINDOW_SWEEP":            "STRUCTURAL_REVERSAL",
    "PIA_FIRST":               "STRUCTURAL_REVERSAL",
    # SPECIALISED — bypass or opportunity-driven; handled separately.
    "ONE_STRATEGY":            "SPECIALISED",
    "V2_PICK_BOUNCE":          "SPECIALISED",
    "QM_V2":                   "SPECIALISED",
}


# 2026-11-05 — trader-side ↔ directional-side vocabulary.
# BB_PIERCE_RUN, EMA_PULLBACK, V3 and most autobot strategies emit
# candidate.side in trader-side vocabulary ("LONG" / "SHORT").
# nms_directional_authority.enforce() accepts only directional
# vocabulary ("BUY" / "SELL") and returns BLOCK_BAD_SIDE for anything
# else. Normalise at the gate boundary so the enforcer's downstream
# conditions (watch-and-wait, exhaustion, trend-wrong-direction) run
# instead of short-circuiting on a vocabulary mismatch.
# This is purely a vocabulary normalisation — BUY/SELL inputs pass
# through unchanged; malformed/empty values remain malformed so the
# enforcer's BAD_SIDE guard continues to protect against them.
def _normalise_candidate_side(side: str) -> str:
    s = str(side or "").upper().strip()
    if s == "LONG":
        return "BUY"
    if s == "SHORT":
        return "SELL"
    return s


def _apply_unified_directional_authority(
    pair: str, candidate: Any, family: str,
) -> Optional[str]:
    """Phase 2B — central NMS directional authority gate.

    Returns a reason string to BLOCK, or ``None`` to ALLOW/continue.
    Only runs when ``NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1``.
    When OFF, returns None unconditionally (byte-identical to pre-
    Phase-2B behaviour).

    Fail-closed per operator §11:
      * Unknown family → BLOCK with family-unresolved reason.
      * Authority exception → BLOCK with authority-unavailable reason.
      * Authority stale/unknown NMS → BLOCK via authority's own fail-
        closed semantics (returned as reason_code).
      * Authority IMPORT exception → BLOCK with
        authority-unavailable reason when the operator flag is set
        at the OS level, regardless of whether the module loaded.
        (Deployment-readiness review 2026-10-27: previous
        implementation returned None here, which fail-OPENED the
        gate when the flag was ON but the module failed to import.
        The flag is now checked via os.getenv directly as a safety
        belt independent of the module.)

    ONE_STRATEGY and V2_PICK_BOUNCE are handled by their dedicated
    blocks downstream — this function skips them so the dedicated
    opportunity-type mapping runs. STRUCTURAL_REVERSAL families return
    applicable=False from the authority and this function returns
    None so the existing admission logic continues.
    """
    # 2026-10-27 pm: read the flag from os.environ FIRST, independent
    # of the authority module. Determines whether a subsequent import
    # or evaluation failure is fail-closed (flag on) or fail-open
    # (flag off, legacy routing continues untouched).
    _flag_on = str(os.getenv(
        "NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED", "0"
    ) or "").strip().lower() in ("1", "true", "yes", "on")
    try:
        import nms_directional_authority as _nda  # type: ignore
    except Exception as _imp_exc:
        if _flag_on:
            # Operator intends enforcement but authority is
            # unreachable — BLOCK applicable submissions.
            return (f"unified_authority_block:"
                    f"BLOCK_AUTHORITY_UNAVAILABLE:import_failed:"
                    f"{type(_imp_exc).__name__}")
        return None
    try:
        if not _nda.is_enforcement_enabled():
            return None
    except Exception as _flag_exc:
        if _flag_on:
            return (f"unified_authority_block:"
                    f"BLOCK_AUTHORITY_UNAVAILABLE:flag_check_exc:"
                    f"{type(_flag_exc).__name__}")
        return None
    # Dedicated downstream handlers.
    if family in ("ONE_STRATEGY", "V2_PICK_BOUNCE", "UNKNOWN", ""):
        return None
    auth_family = _AUTOBOT_FAMILY_TO_AUTHORITY_FAMILY.get(family)
    if auth_family is None:
        # Unknown family → fail-closed per operator §11.
        return (f"unified_authority_block:"
                f"BLOCK_FAMILY_UNRESOLVED:family={family}")
    side = _normalise_candidate_side(
        getattr(candidate, "side", "")
        or getattr(candidate, "signal", "")
    )
    strategy_id = str(getattr(candidate, "strategy", "")
                       or "").upper()
    # 2026-10-27 pm — Stage 3 final safety: extract QM fingerprint
    # metadata from the Candidate so the authority can bind
    # REVERSAL_CONFIRMED permission to the specific qualifying
    # signal. qm_reversal_detector.signal_to_candidate populates
    # candidate.detected_ts = signal.ts (bar close) and
    # candidate.metadata["level_type"]/["level_price"] verbatim —
    # see qm_reversal_detector.py:1252-1255. For non-QM candidates
    # these are None/absent and the authority ignores them.
    _cand_bar_ts = getattr(candidate, "detected_ts", None)
    _cand_meta = getattr(candidate, "metadata", None) or {}
    try:
        if hasattr(_cand_meta, "get"):
            _cand_level_type = _cand_meta.get("level_type")
            _cand_level_price = _cand_meta.get("level_price")
        else:
            _cand_level_type = None
            _cand_level_price = None
    except Exception:
        _cand_level_type = None
        _cand_level_price = None
    # Normalise detected_ts to an ISO string if it's a datetime —
    # the authority compares the string against the recorded bar_ts.
    if _cand_bar_ts is not None and not isinstance(_cand_bar_ts, str):
        try:
            _cand_bar_ts = _cand_bar_ts.isoformat()
        except Exception:
            _cand_bar_ts = str(_cand_bar_ts)
    try:
        dec = _nda.enforce(
            symbol=pair, side=side,
            strategy_id=strategy_id, strategy_family=auth_family,
            candidate_signal_bar_ts=_cand_bar_ts,
            candidate_level_type=_cand_level_type,
            candidate_level_price=_cand_level_price,
        )
    except Exception as exc:
        return (f"unified_authority_block:"
                f"BLOCK_AUTHORITY_UNAVAILABLE:enforce_exc:"
                f"{type(exc).__name__}")
    if not dec.applicable:
        # STRUCTURAL_REVERSAL / SPECIALISED — preserve existing logic.
        return None
    if dec.allowed:
        return None
    return (f"unified_authority_block:{dec.reason_code}:"
             f"{dec.reason_detail}")


def _resolve_family(candidate: Any) -> str:
    """Return the FAMILY_* string for a Candidate. Preserves an explicit
    strategy_family field if the caller has populated it; otherwise
    resolves from Candidate.strategy via longest-prefix match. UNKNOWN
    on empty/unrecognised input — the MID_NEWS delegate treats UNKNOWN
    as not-V2 (rejects under enforcement)."""
    fam = str(getattr(candidate, "strategy_family", "") or "").strip().upper()
    if fam:
        return fam
    strat = str(getattr(candidate, "strategy", "") or "").strip().upper()
    if not strat:
        return "UNKNOWN"
    for prefix, family in _STRATEGY_PREFIX_TO_FAMILY:
        if strat.startswith(prefix):
            return family
    return "UNKNOWN"


def _delegate_mid_news(candidate: Any) -> Tuple[bool, str]:
    """MID_NEWS delegate — Amendments A9 (2026-09-13), A10 (2026-09-14).

    A9.5 / A10: MID_NEWS emphasises observation of level-bounce
    opportunities but does not disable BB or any other strategy
    family. Candidates are routed to `_delegate_normal_routing` which
    applies price-derived market-state × family × entry-quality
    rules. Retained: family-scoped autonomous routes (BRIEFING_V5)
    and named suppressions (BRIEFING_V4 pending migration).

    A10 (2026-09-14, operator ruling A.2): the legacy MID_NEWS_ROUTER
    flag was deleted. Suppressed-family enforcement now follows the
    general `NORMAL_MARKET_ROUTER` — one router, one authority.

    Emits:
      * `mid_news_off_route`               canonical != MID_NEWS
      * `BRIEFING_V5_AUTONOMOUS_ROUTE`     A8 autonomous carve-out
      * `BRIEFING_V4_PENDING_MIGRATION`    A8 named suppression
      * `mid_news_search_emphasis:<family>` A9 pass-through — routed
                                            to normal_routing for the
                                            price-derived permission
                                            decision
      * `delegate_exception:mid_news:<Type>`
    """
    try:
        canon = _canonical_day_type_now()
        if canon != "MID_NEWS":
            return True, "mid_news_off_route"
        family = _resolve_family(candidate)
        # Stage 11 (2026-09-26, amended 2026-10-03): FAMILY_ONE_STRATEGY
        # and FAMILY_V2_PICK_BOUNCE carry direction resolved by Stages 8-9
        # (V2_PICK via the alignment check at qm_v2_executor._fire_route).
        # The MID_NEWS V2-only carve-out must not force either back
        # through V2 directional selection.
        if family == "ONE_STRATEGY":
            return True, "one_strategy_pre_authorised_direction"
        if family == "V2_PICK_BOUNCE":
            return True, "v2_pick_pre_authorised_direction"
        import permission_matrix as _pm
        auto = _pm.is_autonomous_route("MID_NEWS", family)
        if auto is not None:
            return True, auto.approval_reason
        suppressed = _pm.is_suppressed_family(family)
        if suppressed is not None:
            # A10: enforcement follows the general market router; MID_NEWS
            # no longer carries its own enforcement flag.
            return (not normal_market_router_active()), suppressed

        # Core-live 2026-09-18 (reviewer ruling): "MID_NEWS cannot
        # select ordinary BB Bounce or News Strategy." Enforce a
        # level-reversal-only carve-out on MID_NEWS days when
        # MID_NEWS_V2PB_ONLY_ENFORCE=1 (default OFF — policy blocker
        # awaiting operator sign-off).
        #
        # Backwards compatibility: when the enforcement flag is OFF
        # this delegate emits the historical A9.5 reason string
        # unchanged so the shadow journal / A9 test corpus is not
        # perturbed. Only when the flag is ON does the new
        # NOT_PERMITTED reason string surface AND admission is
        # actually rejected.
        _v2pb_only = _MID_NEWS_V2PB_ONLY_FAMILIES
        _enforce = _env_bool("MID_NEWS_V2PB_ONLY_ENFORCE", "0")
        if _enforce:
            if family in _v2pb_only:
                return True, f"mid_news_v2pb_admitted:{family}"
            if family in _NEWS_TREND_ROUTE_FAMILIES:
                # NEWS_STRATEGY / NEWS_TREND / NEWS_TICK / NEWS_CONTINUATION
                # are never armed on MID_NEWS days at the emitter
                # (armed_day set is BIG_NEWS/PRE/POST); this branch
                # enforces the same invariant at admission time in case
                # an operator manually engages a legacy path.
                return False, f"MID_NEWS_NEWS_STRATEGY_NOT_PERMITTED:{family}"
            if family == "BB_BOUNCE":
                return False, f"MID_NEWS_BB_NOT_PERMITTED:{family}"
        # A9.5 / A10: historical routing — price-derived market-state ×
        # family × entry-quality evaluation via `_delegate_normal_routing`.
        return True, f"mid_news_search_emphasis:{family}"
    except Exception as exc:
        return True, f"delegate_exception:mid_news:{type(exc).__name__}"


# MID_NEWS "level-reversal only" admitted set: V2 family (QM_V2,
# LEVEL_BOUNCE, V2_PICK_BOUNCE). Kept as a module-level tuple so
# tests can inspect the exact vocabulary.
_MID_NEWS_V2PB_ONLY_FAMILIES = frozenset({
    "QM_V2", "LEVEL_BOUNCE", "V2_PICK_BOUNCE",
})


def _apply_countertrend_continuation_veto(
    pair: str, family: str, cand_dir: Optional[str],
    demonstrated_dir: Optional[str],
) -> Optional[str]:
    """Countertrend continuation veto — operator rulings 2026-09-24 (§0
    LOI route) + 2026-09-25 (Repair Path 1: NMS CHoCH route).

    Admission-only rejection for BB_BOUNCE / LEVEL_BOUNCE candidates
    on TRADABLE_NON_RANGE that oppose the demonstrated price-derived
    direction, when EITHER of two continuation-in-thesis primitives is
    satisfied AND no candidate-side bounce / reversal has yet fired:

      * **LOI route** (existing) — a fresh
        `level_interaction_observer_v6` record with
        `structural_interpretation.continuation_demonstrated=True` on a
        level whose `raw.close_side` maps to `demonstrated_dir`.
      * **NMS CHoCH route** (Repair Path 1) — the current
        `normal_market_state.snapshot(pair)` reports
        `demonstrated_reason` starting with `"choch_up"` /
        `"choch_down"`, whose direction matches `demonstrated_dir`, and
        whose `bar_ts` is fresh within
        `_countertrend_veto_freshness_seconds()`. The CHoCH channel is
        distinct from "merely having demonstrated_direction=UP/DOWN" —
        it requires the direction to have been established by an
        identifiable CHoCH event (reason prefix). Once
        `classify_structure` catches up and the reason transitions to
        `"structure_bearish:lh_ll"` / `"structure_bullish:hh_hl"`, the
        CHoCH channel stops firing even though the direction persists;
        the LOI channel remains available.

    Reads existing state only:
      * `normal_market_state.snapshot(pair)` — for the CHoCH primitive
        and its evidence timestamp / reason.
      * `level_interaction_observer_v6.get_latest_states(pair)` — for
        the existing LOI primitive AND for the reversal exception
        (candidate-direction BOUNCE_CONFIRMED / REVERSAL_CONFIRMED).

    Reversal exception is authoritative across both routes: a fresh
    LOI bounce_state in `cand_dir` releases the candidate regardless of
    which continuation channel armed the veto. This preserves the
    §26-style earned-reversal admission for genuine counter-thesis
    reversals.

    Return codes:
      * `"COUNTERTREND_CONTINUATION_VETO"` — LOI route fired.
      * `"COUNTERTREND_CONTINUATION_VETO:NMS_CHOCH"` — CHoCH route
        fired (LOI did not fire OR LOI checked first and passed).
      * `None` — veto does not apply / does not fire.

    Fail-open on any exception — a bug in the veto MUST NOT tighten
    beyond the existing admission surface.
    """
    if not countertrend_continuation_veto_enabled():
        return None
    if family not in ("BB_BOUNCE", "LEVEL_BOUNCE"):
        return None
    if cand_dir is None or demonstrated_dir is None:
        return None
    if cand_dir == demonstrated_dir:
        return None   # same-direction candidate — veto does not apply

    now = datetime.now(timezone.utc)
    fresh_cutoff = now - timedelta(seconds=_countertrend_veto_freshness_seconds())

    def _parse_bar_ts(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except Exception:
            return None

    # ── LOI state read (needed for LOI continuation AND for the
    #    reversal exception applied to both routes) ─────────────────
    try:
        import level_interaction_observer_v6 as _loi
        states = _loi.get_latest_states(pair)
    except Exception:
        states = {}
    if not isinstance(states, dict):
        states = {}

    # (1a) LOI continuation route — fresh continuation_demonstrated=True
    #      whose close_side maps to demonstrated_dir. Unchanged from
    #      the 2026-09-24 ruling.
    loi_hit = False
    for _key, payload in states.items():
        raw = payload.get("raw") or {}
        bts = _parse_bar_ts(raw.get("bar_ts"))
        if bts is None or bts < fresh_cutoff:
            continue
        si = payload.get("structural_interpretation") or {}
        if not si.get("continuation_demonstrated"):
            continue
        close_side = raw.get("close_side")
        break_dir: Optional[str] = None
        if close_side == "below":
            break_dir = "SELL"
        elif close_side == "above":
            break_dir = "BUY"
        if break_dir == demonstrated_dir:
            loi_hit = True
            break

    # (1b) NMS CHoCH route — fresh CHoCH-derived evidence of a
    #      direction establishment. NMS is retained ONLY as the CHoCH-
    #      event primitive owner (reason prefix + bar_ts). The DIRECTION
    #      reconcile that proves the thesis has not flipped since the
    #      caller fetched ``demonstrated_dir`` now reads
    #      ``direction_state`` (Build-1 A1 single-direction authority).
    choch_hit = False
    choch_reason: Optional[str] = None
    choch_bar_ts: Optional[datetime] = None
    if not loi_hit:
        # Build-1 A1: reconcile direction via direction_state (sole
        # trading-direction source). NMS is read below for CHoCH-event
        # context only (reason prefix + bar_ts).
        try:
            import direction_state as _ds
            ds_snap = _ds.update_from_production(pair)
        except Exception:
            ds_snap = None
        if ds_snap is not None and getattr(ds_snap, "knowledge", "") == "VALID":
            ds_dir = getattr(ds_snap, "pair_direction", None)
        else:
            ds_dir = None
        _mapped = "BUY" if ds_dir == "UP" else ("SELL" if ds_dir == "DOWN" else None)
        # NMS CHoCH-event context — reason prefix and bar timestamp.
        # The NMS ``demonstrated_direction`` field is NOT read here;
        # under A1 that field is observability-only.
        try:
            import normal_market_state as _nms
            nms_choch_ctx = _nms.snapshot(pair) or {}
        except Exception:
            nms_choch_ctx = {}
        reason = str(nms_choch_ctx.get("demonstrated_reason") or "")
        bts = _parse_bar_ts(nms_choch_ctx.get("bar_ts"))
        if _mapped == demonstrated_dir and bts is not None and bts >= fresh_cutoff:
            if reason.startswith("choch_down") and demonstrated_dir == "SELL":
                choch_hit = True
            elif reason.startswith("choch_up") and demonstrated_dir == "BUY":
                choch_hit = True
            if choch_hit:
                choch_reason = reason
                choch_bar_ts = bts

    if not (loi_hit or choch_hit):
        return None

    # (2) Reversal exception — allow the candidate through if a fresh
    #     LOI bounce_state confirms a genuine reversal in the
    #     candidate's direction. Applies to BOTH continuation channels
    #     — the operator ruling preserves earned-reversal admission
    #     regardless of which primitive armed the veto.
    for _key, payload in states.items():
        raw = payload.get("raw") or {}
        bts = _parse_bar_ts(raw.get("bar_ts"))
        if bts is None or bts < fresh_cutoff:
            continue
        bi = payload.get("bounce_interpretation") or {}
        bstate = bi.get("state")
        bdir = bi.get("direction")
        if (bstate in ("BOUNCE_CONFIRMED", "REVERSAL_CONFIRMED")
                and bdir == cand_dir):
            return None   # reversal permission granted

    if loi_hit:
        return "COUNTERTREND_CONTINUATION_VETO"
    # NMS CHoCH route fired — emit source-tagged reason + telemetry.
    try:
        age_s = int((now - choch_bar_ts).total_seconds()) if choch_bar_ts else -1
        logger.info(
            "[CT_VETO] source=NMS_CHOCH pair=%s family=%s cand=%s "
            "demonstrated=%s choch_bar_ts=%s choch_reason=%s age_s=%d",
            pair, family, cand_dir, demonstrated_dir,
            choch_bar_ts.isoformat() if choch_bar_ts else None,
            choch_reason, age_s,
        )
    except Exception:
        pass
    return "COUNTERTREND_CONTINUATION_VETO:NMS_CHOCH"


def _delegate_normal_routing(
    pair: str, candidate: Any,
) -> Tuple[bool, str]:
    """Price-derived market-state × family admission — Amendment A9.

    A9 governing principle: DAY TYPE biases search; PRICE-DERIVED
    MARKET STATE grants strategy-family permissions. This delegate
    therefore runs on every day_type — not only NORMAL — so
    news-family and MID_NEWS candidates are evaluated by the same
    market-state × family × entry-quality rules as NORMAL candidates.

    On news-family days, `_delegate_news_direction` still handles the
    §17 counter-trend exclusion during an active TREND_UP/TREND_DOWN
    trend and the primary news-trend slot allocation. This delegate
    is the general market-state × family gate downstream of that.

    Emits (shadow-mode: allowed=True; router-active: enforced):
      * `NORMAL_STATE_UNKNOWN:<family>`
            classifier has not yet observed enough bars.
      * `NORMAL_PRODUCTIVE_BB_ONLY:<family>`
      * `NORMAL_STATE_NOT_PERMITTED:<family>`
      * `NORMAL_TRADABLE_V2_ONLY:<family>`
      * `NORMAL_CHOP_STANDDOWN:<family>` / `NORMAL_STANDDOWN:<family>`
      * `NORMAL_FLAT_PENDING:<family>`
      * `NORMAL_STATE_RECLASSIFIED_SINCE_CANDIDATE:<from>-><to>`
      * `DIRECTION_MISMATCH:<family>:<demonstrated_direction>`
            A10 STRICT — TRADABLE_NON_RANGE-admitted family whose
            candidate side maps to the opposite of the demonstrated
            direction.
      * `DIRECTION_NOT_ESTABLISHED:<family>`
            A10 STRICT — TRADABLE_NON_RANGE-admitted family with no
            explicit demonstrated direction (missing / neutral /
            unknown / unmapped). Fails closed under router-active.
      * `delegate_exception:normal_routing:<Type>`

    Router flag: NORMAL_MARKET_ROUTER=0 stamps only; =1 enforces the
    matrix rejects. CHOP_STANDDOWN=1 additionally enforces the §42
    stand-down independently.
    """
    try:
        canon = _canonical_day_type_now()
        # A9 (2026-09-13): no day_type-based early-out. The matrix
        # lookup below is market-state × family; day_type is only
        # consulted for family-scoped autonomous / suppressed carve-outs.

        import normal_market_state as _nms
        import permission_matrix as _pm

        family = _resolve_family(candidate)
        # Phase 2B (2026-10-27) — Unified NMS directional authority.
        # When NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1 the central
        # authority is the sole directional judge for applicable
        # families (TREND_V3, EMA_PULLBACK, BB_BOUNCE, LEVEL_BOUNCE,
        # QM_REVERSAL, PIVOT_BREAK, BRIEFING_*, NEWS_* when
        # applicable, GBPUSD_TREND_CONT). Runs BEFORE the ONE_STRATEGY
        # / V2_PICK bypass so ONE_STRATEGY's bypass is handled by the
        # authority-aware block below. Families outside the Phase 2
        # matrix (STRUCTURAL_REVERSAL / SPECIALISED by default) fall
        # through with applicable=False and preserve their existing
        # admission logic. See nms_directional_authority.enforce() for
        # the exact fail-closed semantics.
        _authority_block = _apply_unified_directional_authority(
            pair, candidate, family,
        )
        if _authority_block is not None:
            return False, _authority_block
        # Stage 11 (2026-09-26, amended 2026-10-03): FAMILY_ONE_STRATEGY
        # and FAMILY_V2_PICK_BOUNCE carry direction already resolved
        # upstream by Stages 8-9 (V2_PICK via qm_v2_executor._fire_route's
        # Stage 9 alignment check). The gate is the mechanical safety
        # boundary — it MUST NOT rerun directional admission for either
        # (would recreate a second directional authority downstream of
        # Stage 9, violating the frozen roadmap). Mechanical / capacity /
        # duplicate / hours / SL / one_book / blackout / risk checks
        # still run through the other delegates.
        if family == "ONE_STRATEGY":
            # Phase 2B (2026-10-27): when the unified directional
            # authority is enabled, ONE_STRATEGY's pre-authorised
            # bypass is REPLACED with authority-aware routing based
            # on the LLM's declared opportunity_type. Unknown /
            # missing opportunity_type fails closed per operator §7
            # (no silent bypass of NMS). When the unified flag is
            # off, the pre-authorised bypass remains byte-identical.
            #
            # Deployment-readiness review (2026-10-27 pm): read the
            # flag directly from os.environ FIRST as a safety belt so
            # a subsequent import or exception failure is correctly
            # fail-closed when the operator has set the flag,
            # independent of whether the authority module loaded.
            _ones_flag_on = str(os.getenv(
                "NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED", "0"
            ) or "").strip().lower() in ("1", "true", "yes", "on")
            try:
                import nms_directional_authority as _nda  # type: ignore
            except Exception as _nda_imp_exc:
                if _ones_flag_on:
                    return (False,
                            f"one_strategy_unified_authority_error:"
                            f"import_failed:"
                            f"{type(_nda_imp_exc).__name__}")
                return (DELEGATE_NO_OBJECTION,
                        "one_strategy_pre_authorised_direction")
            try:
                if _nda.is_enforcement_enabled():
                    _opp = str(
                        getattr(candidate, "opportunity_type", "")
                        or ""
                    ).upper().strip()
                    _side = _normalise_candidate_side(
                        getattr(candidate, "side", "")
                        or getattr(candidate, "signal", "")
                    )
                    _sym = str(getattr(candidate, "pair", "")
                                or getattr(candidate, "symbol", "")
                                or "").upper()
                    _dec = _nda.enforce(
                        symbol=_sym, side=_side,
                        strategy_id="ONE_STRATEGY",
                        opportunity_type=_opp if _opp else None,
                    )
                    if not _dec.applicable:
                        # STRUCTURAL_REVERSAL / SPECIALISED mapping —
                        # preserve the pre-authorised bypass since no
                        # Phase 2 matrix applies.
                        return (DELEGATE_NO_OBJECTION,
                                f"one_strategy_not_applicable:"
                                f"{_dec.reason_code}")
                    if _dec.allowed:
                        return (DELEGATE_NO_OBJECTION,
                                f"one_strategy_unified_authority:"
                                f"{_dec.reason_code}")
                    return (False,
                            f"one_strategy_unified_authority_block:"
                            f"{_dec.reason_code}:{_dec.reason_detail}")
            except Exception as _nda_exc:
                # Fail-closed when the operator intends enforcement.
                # When the flag is off we must preserve the legacy
                # byte-identical path, so only block when _ones_flag_on.
                if _ones_flag_on:
                    return (False,
                            f"one_strategy_unified_authority_error:"
                            f"{type(_nda_exc).__name__}")
            return DELEGATE_NO_OBJECTION, "one_strategy_pre_authorised_direction"
        if family == "V2_PICK_BOUNCE":
            return DELEGATE_NO_OBJECTION, "v2_pick_pre_authorised_direction"
        auto = _pm.is_autonomous_route(canon or "NORMAL", family)
        if auto is not None:
            return True, auto.approval_reason
        suppressed = _pm.is_suppressed_family(family)
        if suppressed is not None:
            return (not normal_market_router_active()), suppressed

        # A9.4 row-2 precedence (2026-09-13 defect fix): on news-family
        # days with an active price-confirmed trend (TREND_UP /
        # TREND_DOWN), A9.4 row 2 governs: with-trend candidates from
        # any family are admitted under their own family / entry-quality
        # / risk rules; counter-trend is excluded by news_direction.
        # `_delegate_normal_routing`'s market-state × family matrix
        # does NOT apply here — that matrix is A9.4 rows 1/3/4/5.
        # Rows 1 (no active trend) and 3 (decay / cleared) still route
        # to normal_routing exactly as before.
        if canon in _NEWS_FAMILY_CANONICALS:
            try:
                import news_trend_classifier as _ntc
                _snap = _ntc.snapshot(pair)
                _trend_state = (
                    _snap.get("trend_state")
                    or _snap.get("state")
                    or _ntc.NO_CLEAR_TREND
                )
                if (_trend_state in _ACTIVE_TREND_STATES
                        and _snap.get("primary_direction") is not None):
                    return True, (
                        f"normal_routing_deferred_active_trend:"
                        f"{_trend_state}"
                    )
            except Exception:
                pass

        # 2026-10-22 — Second-NMS gate takeover (operator ruling). When
        # NMS_SECOND_GATE_ENABLED=1, the new strategy-seam gate
        # (``nms_second_gate.check``) is the SOLE market-state
        # permission check for TREND_V3 and BB_BOUNCE. The central
        # matrix's market-state admission (CHOP_COMPRESSION stand-down,
        # UNKNOWN / FLAT_OR_COMPRESSED deny, PRODUCTIVE_RANGE /
        # TRADABLE_NON_RANGE row.permits + A10 direction alignment)
        # must NOT re-run for these two — the strategies have already
        # resolved admission at their own seams via the second gate,
        # and running the matrix a second time would (a) refuse
        # TREND_V3 on PRODUCTIVE_RANGE (admitted by the new gate) and
        # (b) duplicate the gate decision. Every other delegate
        # (mechanical / capacity / hours / SL / blackout / risk /
        # news-direction) still runs. Pass-through only applies to
        # the market-state admission portion of this delegate.
        if (family in ("TREND_V3", "BB_BOUNCE")
                and os.getenv("NMS_SECOND_GATE_ENABLED", "0").strip().lower()
                in ("1", "true", "yes", "on")):
            return DELEGATE_NO_OBJECTION, (
                f"normal_routing_deferred_to_nms_second_gate:{family}"
            )

        market_snap = _nms.snapshot(pair)
        market_state = str(market_snap.get("state") or "UNKNOWN")

        # §34 subclassification.
        if (market_state == _nms.FLAT_OR_COMPRESSED
                and range_quality_classifier_active()):
            import range_quality_classifier as _rqc
            rq_snap = _rqc.snapshot(pair)
            rq_state = str(rq_snap.get("state") or "PENDING")
            if rq_state == _rqc.PRODUCTIVE_RANGE:
                market_state = "PRODUCTIVE_RANGE"
            elif rq_state == _rqc.CHOP_COMPRESSION:
                market_state = "CHOP_COMPRESSION"
            # PENDING / RECOVERY_CANDIDATE stay as FLAT_OR_COMPRESSED
            # so the matrix returns the NORMAL_FLAT_PENDING row.

        # §50 reclassification-before-entry.
        try:
            mss = getattr(candidate, "market_state_snapshot", {}) or {}
            captured = mss.get("normal_market_state")
        except Exception:
            captured = None
        if captured and captured != market_state:
            # If the current state no longer permits this family AND
            # the captured state DID permit it, this is a §50 stale
            # candidate.
            if (_pm.is_permitted("NORMAL", captured, family)
                    and not _pm.is_permitted("NORMAL", market_state, family)):
                reason = (
                    f"NORMAL_STATE_RECLASSIFIED_SINCE_CANDIDATE:"
                    f"{captured}->{market_state}"
                )
                if normal_market_router_active():
                    return False, reason
                return True, reason

        row = _pm.lookup("NORMAL", market_state)

        # R4.1 (2026-09-23, operator ruling): permission_matrix now
        # admits BB_BOUNCE on TRADABLE_NON_RANGE without direction
        # alignment to unblock NORMAL-day structural bounce trading.
        # The matrix ignores day_type per A9, so this admission also
        # applies to every non-NORMAL day_type. Preserve pre-R4.1
        # BIG_NEWS / BIG_NEWS_MINUS_1 / BIG_NEWS_PLUS_1 / MID_NEWS
        # behaviour by rejecting BB_BOUNCE on any non-NORMAL day when
        # the market_state is the one R4.1 newly broadened:
        # TRADABLE_NON_RANGE. Other market_states (PRODUCTIVE_RANGE,
        # CHOP, FLAT, UNKNOWN) keep their pre-R4.1 semantics on those
        # days. MID_NEWS BB_BOUNCE is ALSO rejected upstream by
        # `_delegate_mid_news` (line 1335) under
        # `MID_NEWS_V2PB_ONLY_ENFORCE=1`; this check is the
        # belt-and-braces guard for the operator's "do not allow BB
        # Bounce on MID_NEWS or BIG_NEWS" constraint.
        if (family == "BB_BOUNCE"
                and market_state == "TRADABLE_NON_RANGE"
                and canon != "NORMAL"):
            reason = f"BB_BOUNCE_NOT_PERMITTED_ON_{canon}"
            if normal_market_router_active():
                return False, reason
            return True, reason

        # Stand-down enforcement (independent flag).
        if market_state == "CHOP_COMPRESSION":
            reason = f"NORMAL_STANDDOWN:{family}"
            if chop_standdown_active():
                return False, reason
            return True, reason

        # UNKNOWN / FLAT_OR_COMPRESSED unresolved — deny under
        # router=1, stamp otherwise.
        if market_state in ("UNKNOWN", "FLAT_OR_COMPRESSED"):
            template = row.reject_reason_template
            reason = template.format(family=family)
            if normal_market_router_active():
                return False, reason
            return True, reason

        # Positive matrix lookup.
        if row.permits(family):
            # A10 STRICT (2026-09-14, operator follow-up ruling) — for
            # the four families admitted into TRADABLE_NON_RANGE, the
            # candidate must align with an EXPLICIT demonstrated
            # price-derived direction. There are three outcomes:
            #
            #   (1) demonstrated direction is BUY/SELL AND candidate
            #       side maps to the same direction → matrix admits.
            #   (2) demonstrated direction is BUY/SELL AND candidate
            #       side maps to the opposite direction → REJECT with
            #       DIRECTION_MISMATCH.
            #   (3) demonstrated direction is missing / neutral /
            #       unknown / unmapped → REJECT with
            #       DIRECTION_NOT_ESTABLISHED. Absence of a usable
            #       direction is NOT permissive fall-through.
            #
            # BB_REVERSAL_PATTERNS in PRODUCTIVE_RANGE is exempt (fade
            # toward value — its identity is not a directional
            # continuation).
            # Operator ruling 2026-10-21: when DIRECTION_FROM_NMS_
            # SESSION_TREND=1, A10 direction-alignment is REMOVED for
            # TREND_V3 (and remains for the other three families — the
            # new rulebook is scoped to the keep-list only, and the
            # new rule's authority for TREND_V3 is permit_trend at
            # the strategy seam, so A10 here would double-block).
            _nms_rule_on_ceg = os.getenv(
                "DIRECTION_FROM_NMS_SESSION_TREND", "0",
            ).strip() in ("1", "true", "yes", "on")
            if _pm.requires_direction_alignment(market_state, family) and not (
                _nms_rule_on_ceg and family == "TREND_V3"
            ):
                cand_side = str(getattr(candidate, "side", "") or "")
                cand_dir = _map_side_to_direction(cand_side)
                demonstrated_dir = _demonstrated_direction(pair)
                if demonstrated_dir is None:
                    reason = f"DIRECTION_NOT_ESTABLISHED:{family}"
                    if normal_market_router_active():
                        return False, reason
                    return True, reason
                if cand_dir is None or cand_dir != demonstrated_dir:
                    reason = (
                        f"DIRECTION_MISMATCH:"
                        f"{family}:{demonstrated_dir}"
                    )
                    if normal_market_router_active():
                        return False, reason
                    return True, reason

            # Countertrend continuation veto (operator ruling 2026-09-24).
            # Runs only for BB_BOUNCE / LEVEL_BOUNCE on TRADABLE_NON_RANGE
            # (see `_apply_countertrend_continuation_veto` for the guard
            # matrix). Same enforcement gating as A10 STRICT: reject
            # under router-active; shadow-stamp otherwise.
            # Operator ruling 2026-10-21: when DIRECTION_FROM_NMS_
            # SESSION_TREND=1 AND family == BB_BOUNCE, the countertrend-
            # continuation veto is REMOVED. The new BOUNCE rulebook
            # (permit_bounce + MACD-tiring) replaces it. LEVEL_BOUNCE is
            # NOT in the keep-list — it is already dead under the Stage-
            # 11 cutover guard — but the veto for LEVEL_BOUNCE stays
            # active in case the operator ever flips LEVEL_BOUNCE_
            # ENABLED back on.
            if market_state == "TRADABLE_NON_RANGE" and not (
                _nms_rule_on_ceg and family == "BB_BOUNCE"
            ):
                cand_side = str(getattr(candidate, "side", "") or "")
                cand_dir = _map_side_to_direction(cand_side)
                demonstrated_dir = _demonstrated_direction(pair)
                veto = _apply_countertrend_continuation_veto(
                    pair=pair, family=family,
                    cand_dir=cand_dir,
                    demonstrated_dir=demonstrated_dir,
                )
                if veto is not None:
                    if normal_market_router_active():
                        return False, veto
                    return True, veto

            return True, f"{row.routing_reason}:{family}"

        reason = row.reject_reason(family)
        if normal_market_router_active():
            return False, reason
        return True, reason
    except Exception as exc:
        return True, (
            f"delegate_exception:normal_routing:{type(exc).__name__}"
        )


def news_trend_snapshot(pair: str) -> Dict[str, Any]:
    """Pass-through of news_trend_classifier.snapshot — used by the
    orchestrator to plumb three telemetric fields (news_trend_state,
    primary_direction, structure_evidence) into the corpus row.

    Never raises. On error returns a NO_CLEAR_TREND stub.
    """
    try:
        import news_trend_classifier as _ntc
        return _ntc.snapshot(pair)
    except Exception as exc:
        return {
            "symbol": str(pair or "").upper(),
            "state": "NO_CLEAR_TREND",
            "primary_direction": None,
            "reason": f"delegate_exception:news_direction:{type(exc).__name__}",
            "bars_available": 0,
            "structure_evidence": {},
        }


# ── Main entrypoint ────────────────────────────────────────────────────────
def evaluate(candidate: Any, *, now_utc: Optional[datetime] = None) -> GateDecision:
    """Evaluate a Candidate. Returns a GateDecision.

    In Phase 1 shadow mode (CENTRAL_EXECUTION_GATE=0), the caller MUST
    still consult the existing production guards — this function's
    output is telemetry until the flag flips.

    Never raises. Any internal exception yields a permissive decision
    with reason_codes=['gate_exception:<...>'] so the shadow cannot
    invent a new block.
    """
    ts = (now_utc or _now_utc()).astimezone(timezone.utc).isoformat()
    cid = str(getattr(candidate, "candidate_id", "") or "")
    codes: List[str] = []
    allowed = True
    binding_delegate: Optional[str] = None

    try:
        pair = str(getattr(candidate, "pair", "") or "").upper()
        side = str(getattr(candidate, "side", "") or "").upper()
        epic = str(getattr(candidate, "epic", "") or "")
        strategy = str(getattr(candidate, "strategy", "") or "")
        family = str(getattr(candidate, "strategy_family", "") or "")

        # ─── Phase 1: NMS V3 directional check (v3-stabilisation-20261013) ───
        # Applies to V3_BB_L/_S, V3_EMA_L/_S, GBPUSD_TREND_V3_UM_L/_S only.
        # Reads session_trend.v3_state and blocks counter-direction fires:
        #   STRONG_UP / EMERGING_UP     → block SELL
        #   STRONG_DOWN / EMERGING_DOWN → block BUY
        #   RANGE / NORMAL / UNKNOWN    → neutral (pass)
        # Fails open on missing/malformed/stale snapshot. Default DISABLED
        # (NMS_V3_DIRECTIONAL_GATE_ENABLED=0). Placed FIRST so no admission
        # path can bypass the directional check.
        try:
            import nms_v3_direction_gate as _nms_v3_gate  # noqa: F401
            _nms_decision = _nms_v3_gate.check(
                strategy=strategy,
                side=side,
                symbol=pair,
                now_utc=now_utc,
            )
            if not _nms_decision.allowed:
                codes_nms: List[str] = list(_nms_decision.reason_codes) + [
                    f"gate:{VERDICT_REJECT}:binding=nms_v3_direction",
                ]
                return GateDecision(
                    allowed=False,
                    reason_codes=codes_nms,
                    reservation_id=None,
                    capacity_snapshot=_snapshot_capacity(),
                    candidate_id=cid,
                    timestamp=ts,
                    live=gate_active(),
                    verdict=VERDICT_REJECT,
                    binding_delegate="nms_v3_direction",
                )
        except Exception as _nms_exc:  # pragma: no cover — defensive
            logger.debug(
                "[NMS_V3_GATE] import/check error (fail-open): %s", _nms_exc,
            )

        # Stage 11 CUTOVER GUARD (2026-09-26, amended 2026-10-03).
        # When ONE_STRATEGY_ENABLED=1, GBPUSD is restricted to the single
        # entry-authority set: ONE_STRATEGY and V2_PICK_BOUNCE. Every other
        # family's emission is blocked centrally so no independent
        # directional authority can bypass Stage 9's demonstrated
        # direction. The 2026-10-03 operator amendment makes V2_PICK_BOUNCE
        # a permitted firer under Stage 9 alignment (checked at
        # qm_v2_executor._fire_route before this gate); nothing else is
        # relaxed — QM_V2, BB_BOUNCE, etc. stay blocked on GBPUSD. Scope
        # stays narrow (GBPUSD only). Legacy sensor CALCULATIONS remain
        # untouched. See Stage 11 report §16-§17 + docs/v2_precedence_
        # ruling_20261003.md AMENDMENT 2026-10-03.
        if os.getenv("ONE_STRATEGY_ENABLED", "0") == "1":
            # Session 4 §1 (2026-10-05): BB_BOUNCE_ADMIT=1 admits
            # GBPUSD_BB_BOUNCE_L / _S only — the two modes of
            # gbpusd_bb_bounce.py — while every other legacy family
            # (QM_V2, LEVEL_BOUNCE, TREND_V3, etc.) stays blocked. The
            # flag defaults OFF so the production cutover behaviour is
            # byte-identical when it is not set.
            _bb_admit = os.getenv("BB_BOUNCE_ADMIT", "0") == "1"
            _bb_bounce_strategy_admitted = (
                _bb_admit
                and family == "BB_BOUNCE"
                and strategy.upper() in (
                    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
                )
            )
            # Session 5 (2026-10-08): TREND_V3_ADMIT=1 admits the four
            # GBPUSD TREND_V3 modes — _L, _S, _UM_L, _UM_S — through the
            # Stage 11 cutover. Mirrors the BB_BOUNCE_ADMIT shape: family
            # match plus exact strategy allowlist. Flag defaults OFF so
            # the cutover-guard behaviour is byte-identical when it is
            # not set.
            _trend_v3_admit = os.getenv("TREND_V3_ADMIT", "0") == "1"
            _trend_v3_strategy_admitted = (
                _trend_v3_admit
                and family == "TREND_V3"
                and strategy.upper() in (
                    "GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S",
                    "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
                )
            )
            # Phase 2 (2026-10-06): HYPOTHESIS trade route — admit only
            # when HYPOTHESIS_TRADE_ENABLED=1. family="HYPOTHESIS" is
            # the single accepted family tag; the strategy string is
            # free-form (hypothesis_trade.evaluate uses GBPUSD_HYPOTHESIS_
            # L/S). Flag defaults OFF so the cutover guard behaviour is
            # byte-identical when it is not set.
            _hyp_admit = (
                os.getenv("HYPOTHESIS_TRADE_ENABLED", "0") == "1"
                or os.getenv("STRETCH_REVERSAL_ENABLED", "0") == "1"
            )
            _hypothesis_route_admitted = (
                _hyp_admit and family == "HYPOTHESIS"
            )
            # Phase 3 (2026-10-06, operator-system): SYSTEM_REVERSAL
            # family admitted when SYSTEM_REVERSAL_ENABLED=1.
            _system_reversal_admitted = (
                os.getenv("SYSTEM_REVERSAL_ENABLED", "0") == "1"
                and family == "SYSTEM_REVERSAL"
            )
            # Phase 4 (2026-10-06, operator-system): briefing execution
            # route admitted alongside the system — logic unchanged,
            # only the cutover-guard pass-through is new. Covers both
            # BRIEFING_EXECUTION and BRIEFING_V5 (the V5 PIA executor
            # which arrives tagged BRIEFING_V5).
            _briefing_admitted = (
                os.getenv("BRIEFING_EXEC_ADMIT", "0") == "1"
                and family in ("BRIEFING_EXECUTION", "BRIEFING_V5")
            )
            # BOUNCE_ENGINE (bounce_engine/BUILD_NOTES.md step 3): the
            # bounce engine owns its own position allowance and its own
            # dispatch; the Stage 11 cutover admits family=BOUNCE_ENGINE
            # only when the master flag is on. Default OFF.
            #
            # Phase 3 (v3-stabilisation-20261013): when
            # BOUNCE_ENGINE_V3_ONLY=1, admit only the V3 strategy names
            # (V3_BB_L/_S, V3_EMA_L/_S) and reject the V2 legacy modes
            # (BOUNCE_A_L/_S, BOUNCE_TR_L/_S). TREND_V3_UM admission is
            # unaffected (routed via TREND_V3_ADMIT). Default OFF →
            # identical to pre-flag behaviour.
            _v3_only_mode = os.getenv("BOUNCE_ENGINE_V3_ONLY", "0") == "1"
            _bounce_engine_v3_strategy = strategy.upper() in (
                "V3_BB_L", "V3_BB_S", "V3_EMA_L", "V3_EMA_S",
            )
            _bounce_engine_admitted = (
                os.getenv("BOUNCE_ENGINE_ENABLED", "0") == "1"
                and family == "BOUNCE_ENGINE"
                and (not _v3_only_mode or _bounce_engine_v3_strategy)
            )
            if (pair == "GBPUSD"
                    and family not in ("ONE_STRATEGY", "V2_PICK_BOUNCE")
                    and not _bb_bounce_strategy_admitted
                    and not _trend_v3_strategy_admitted
                    and not _hypothesis_route_admitted
                    and not _system_reversal_admitted
                    and not _briefing_admitted
                    and not _bounce_engine_admitted):
                codes: List[str] = [
                    "one_strategy_cutover_guard:"
                    f"blocked_legacy_family={family or 'unset'}",
                    f"gate:{VERDICT_REJECT}:binding=one_strategy_cutover_guard",
                ]
                return GateDecision(
                    allowed=False,
                    reason_codes=codes,
                    reservation_id=None,
                    capacity_snapshot=_snapshot_capacity(),
                    candidate_id=cid,
                    timestamp=ts,
                    live=gate_active(),
                    verdict=VERDICT_REJECT,
                    binding_delegate="one_strategy_cutover_guard",
                )

        # Belt-and-braces V2_PICK_BOUNCE flag gate (2026-10-06). The
        # top-level qm_v2_executor.maybe_fire_from_candidate already
        # consults V2_PICK_BOUNCE_ENABLED (line 488), but if ANY
        # other path builds a V2_PICK_BOUNCE candidate — direct
        # trade_executor caller, or a future dispatch site — the
        # flag must still gate it before submission. Refuse here
        # when family=V2_PICK_BOUNCE and the env is "0". Applies to
        # every pair.
        if (family == "V2_PICK_BOUNCE"
                and os.getenv("V2_PICK_BOUNCE_ENABLED", "0").strip().lower()
                    not in ("1", "true", "yes", "on")):
            codes = [
                "v2_pick_bounce_disabled:V2_PICK_BOUNCE_ENABLED=0",
                f"gate:{VERDICT_REJECT}:binding=v2_pick_bounce_flag",
            ]
            return GateDecision(
                allowed=False,
                reason_codes=codes,
                reservation_id=None,
                capacity_snapshot=_snapshot_capacity(),
                candidate_id=cid,
                timestamp=ts,
                live=gate_active(),
                verdict=VERDICT_REJECT,
                binding_delegate="v2_pick_bounce_flag",
            )

        # Phase 2 (2026-10-06): SYSTEM_GRIND gate for ONE_STRATEGY on
        # GBPUSD. In GRIND mode (BIG/PRE/POST_NEWS day) ONE_STRATEGY
        # fires only when the view direction (V1 pressure + yesterday
        # dollar agree) and the Stage-9 demonstrated direction all
        # point the same way as the candidate side. In REVERSAL mode
        # (NORMAL / MID_NEWS) ONE_STRATEGY does not open at all. Flag
        # default OFF → gate is a pass-through. UNKNOWN mode → fail-
        # open (preserves existing behaviour).
        if (os.getenv("SYSTEM_GRIND_ENABLED", "0") == "1"
                and pair == "GBPUSD"
                and family == "ONE_STRATEGY"):
            try:
                allowed_grind, reason_grind = _delegate_system_grind(
                    pair, side, now_utc,
                )
            except Exception as _grind_exc:  # noqa: BLE001
                logger.debug("[SYSTEM_GRIND] gate error (fail-open): %s",
                             _grind_exc)
                allowed_grind, reason_grind = True, (
                    f"system_grind_exception:{type(_grind_exc).__name__}"
                )
            if not allowed_grind:
                codes = [
                    f"system_grind:{reason_grind}",
                    f"gate:{VERDICT_REJECT}:binding=system_grind",
                ]
                return GateDecision(
                    allowed=False,
                    reason_codes=codes,
                    reservation_id=None,
                    capacity_snapshot=_snapshot_capacity(),
                    candidate_id=cid,
                    timestamp=ts,
                    live=gate_active(),
                    verdict=VERDICT_REJECT,
                    binding_delegate="system_grind",
                )

        # Ordered guard evaluation. Order matches the current live order
        # in trade_executor.execute_trade / strategy_logic as closely as
        # observed in Phase 0.
        # observation (spec §12, Phase 3) sits right after kill_switch —
        # ahead of the strategy-specific guards — because it is a
        # session-scoped precondition, not a per-trade check.
        guards: List[Tuple[str, Tuple[bool, str]]] = [
            ("kill_switch",       _delegate_kill_switch()),
            ("observation",       _delegate_observation(pair, now_utc)),
            ("news_direction",    _delegate_news_direction(
                pair, side, now_utc, candidate=candidate,
            )),
            ("mid_news",          _delegate_mid_news(candidate)),
            ("normal_routing",    _delegate_normal_routing(pair, candidate)),
            # QM SAFETY WIRING Item 3 (2026-09-14) — reject a candidate
            # whose direction opposes an active level-rejection bounce.
            # Runs after the news/normal routing decisions (which set
            # the family/state context) and before the mechanical /
            # cap / cooldown checks. Off by default; operator flips
            # `OPPOSING_LEVEL_GATE_MODE=SHADOW|STRICT|PERMISSIVE`.
            ("opposing_level",    _delegate_opposing_level(candidate)),
            ("mechanical",        _delegate_mechanical(candidate)),
            ("entry_hours",       _delegate_entry_hours(now_utc)),
            ("sl_block",          _delegate_sl_block(candidate)),
            ("one_book",          _delegate_one_book_coherence(pair, side)),
            # DAILY_LOSS_STOP (operator ruling 2026-10-05) — disabled by
            # default (DAILY_LOSS_STOP_GBP unset); blocks new entries
            # for the rest of the FX day once the configured GBP cap is
            # breached. Placed after one_book / entry_hours so a flip
            # that would REDUCE exposure still falls under the cap.
            ("daily_loss_stop",   _delegate_daily_loss_stop(now_utc)),
            ("news_post_lockout", _delegate_news_post_lockout(pair, strategy)),
            ("concurrent_cap",    _delegate_concurrent_cap(strategy, epic)),
            ("bucket_dedup",      _delegate_bucket_dedup(candidate)),
            ("cooldown",          _delegate_cooldown(candidate)),
            # Phase 14 ML setup-quality veto (2026-09-14 wiring).
            # Shadow by default via ML_VETO_LIVE=0 — never blocks,
            # only stamps the model's shadow reason. Live path is
            # exercised only when the operator flips ML_VETO_LIVE=1.
            ("ml_veto",           _delegate_ml_veto(candidate)),
        ]

        for name, (ok, reason) in guards:
            codes.append(f"{name}:{reason}")
            # A10 (2026-09-14) — attach the news-direction verdict stamp
            # alongside the raw reason so the final receipt identifies
            # NO_ACTIVE_TREND / WITH_TREND / COUNTER_TREND_DURING_ACTIVE_TREND
            # without callers having to grep the raw reason strings.
            if name == "news_direction":
                _a10_stamp = _classify_news_direction_a10_stamp(reason)
                if _a10_stamp is not None:
                    codes.append(f"news_direction:A10:{_a10_stamp}")
            if ok == DELEGATE_REJECT:
                if allowed:  # capture the FIRST rejecting delegate
                    binding_delegate = name
                allowed = False
                # Do NOT short-circuit — evaluate every guard so the
                # corpus row captures the full reason set (spec §7's
                # "capacity_snapshot" concept applied to all guards).
    except Exception as exc:
        # Fail-safe: gate exception → permissive shadow verdict.
        codes.append(f"gate_exception:{type(exc).__name__}")
        allowed = True
        binding_delegate = None

    reservation_id: Optional[str] = None
    if allowed:
        try:
            reservation_id = _make_reservation(candidate)
        except Exception as exc:
            codes.append(f"reservation_exception:{type(exc).__name__}")
            reservation_id = None

    # A10 (2026-09-14): the gate — and only the gate — emits the final
    # verdict. APPROVE_FINAL is stamped only after every required
    # delegate has returned DELEGATE_NO_OBJECTION.
    if allowed:
        verdict = VERDICT_APPROVE_FINAL
        codes.append(f"gate:{VERDICT_APPROVE_FINAL}")
    else:
        verdict = VERDICT_REJECT
        _bd = binding_delegate or "unknown"
        codes.append(f"gate:{VERDICT_REJECT}:binding={_bd}")

    snap = _snapshot_capacity()
    return GateDecision(
        allowed=allowed,
        reason_codes=codes,
        reservation_id=reservation_id,
        capacity_snapshot=snap,
        candidate_id=cid,
        timestamp=ts,
        live=gate_active(),
        verdict=verdict,
        binding_delegate=binding_delegate,
    )


# ── Reservation API ────────────────────────────────────────────────────────
def _make_reservation(candidate: Any) -> str:
    """Create a reservation atomically under _LOCK. Returns
    reservation_id. Caller has already decided allowed=True.

    Phase 6: consume any news-slot context stashed by
    _delegate_news_direction (news_slot_kind / news_direction /
    bounce_event_id). The stashed entry is REMOVED from _NEWS_EVAL_CTX
    once transferred so a subsequent evaluate() cannot re-read it.
    """
    rid = uuid.uuid4().hex
    now = _now_utc()
    cid = str(getattr(candidate, "candidate_id", "") or "")
    ctx: Dict[str, Any] = {}
    with _LOCK:
        ctx = _NEWS_EVAL_CTX.pop(cid, None) or {}
    r = _Reservation(
        reservation_id=rid,
        candidate_id=cid,
        epic=str(getattr(candidate, "epic", "") or ""),
        pair=str(getattr(candidate, "pair", "") or "").upper(),
        side=str(getattr(candidate, "side", "") or "").upper(),
        strategy_family=str(getattr(candidate, "strategy_family", "") or ""),
        created_at=now,
        expires_at=now + timedelta(seconds=_RESERVATION_TTL_S),
        news_slot_kind=ctx.get("kind"),
        news_direction=ctx.get("direction"),
        bounce_event_id=ctx.get("bounce_event_id"),
        bucket=_candidate_bucket(candidate),
    )
    with _LOCK:
        _RESERVATIONS[rid] = r
    logger.debug(
        "[GATE] reservation %s created for %s %s/%s ttl=%ds "
        "news_slot=%s dir=%s bevent=%s",
        rid, r.pair, r.side, r.strategy_family, _RESERVATION_TTL_S,
        r.news_slot_kind, r.news_direction, r.bounce_event_id,
    )
    return rid


def release_on_failure(reservation_id: Optional[str], reason: str = "") -> bool:
    """Drop a reservation without occupying its slot. Idempotent.

    Called on broker refusal or any execution failure. Returns True iff
    a reservation was actually removed.

    Phase 6: since slot consumption is only recorded on confirm_execution
    (not at reservation creation), release_on_failure does NOT touch the
    NewsSlotLedger — nothing was consumed. This matches the prompt's
    "consumption recorded at execution" discipline.
    """
    if not reservation_id:
        return False
    with _LOCK:
        r = _RESERVATIONS.pop(reservation_id, None)
        # Best-effort: clean up any lingering _NEWS_EVAL_CTX entry
        # keyed by the same candidate_id (defensive — normally the
        # entry was already popped by _make_reservation).
        if r is not None:
            _NEWS_EVAL_CTX.pop(r.candidate_id, None)
    if r is None:
        return False
    logger.info(
        "[GATE] reservation %s released: reason=%s",
        reservation_id, reason or "no_reason",
    )
    return True


def confirm_execution(
    reservation_id: Optional[str],
    *,
    deal_id: Optional[str] = None,
    deal_ref: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> bool:
    """Convert a reservation to an OCCUPIED slot after successful broker
    fill. Returns True iff the reservation existed and was converted.

    Idempotent: repeated calls with the same reservation_id are safe.

    Phase 6 side-effect: when the reservation carries a news_slot_kind
    (set by the news_direction delegate under NEWS_TREND_ROUTER=1),
    record consumption into the NewsSlotLedger:
      * kind='primary'  → ledger.record_primary(epic, direction, ts)
      * kind='bounce'   → ledger.record_bounce(epic, event_id, dir, ts)
    Ledger writes are idempotent; a repeated confirm_execution is a
    no-op at both the reservation and the ledger layer.
    """
    if not reservation_id:
        return False
    with _LOCK:
        r = _RESERVATIONS.get(reservation_id)
        if r is None:
            return False
        already_occupied = r.occupied
        r.occupied = True
        r.deal_id = deal_id or r.deal_id
        r.deal_ref = deal_ref or r.deal_ref
        news_kind = r.news_slot_kind
        news_dir = r.news_direction
        news_bevent = r.bounce_event_id
        news_epic = r.epic
    if not already_occupied and news_kind:
        try:
            import news_slot_ledger as _slots
            ts = _now_utc() if now_utc is None else now_utc
            if news_kind == "primary" and news_dir:
                _slots.record_primary(news_epic, news_dir, ts)
            elif news_kind == "bounce" and news_bevent and news_dir:
                _slots.record_bounce(
                    news_epic, news_bevent, news_dir, ts,
                )
        except Exception as exc:
            logger.warning(
                "[GATE] ledger record failed for reservation %s "
                "kind=%s epic=%s: %s",
                reservation_id, news_kind, news_epic, exc,
            )
    logger.info(
        "[GATE] reservation %s confirmed deal_id=%s deal_ref=%s "
        "news_slot=%s",
        reservation_id, deal_id, deal_ref, news_kind,
    )
    return True


def notify_confirmed_reversal(
    epic: str,
    new_direction: str,
    now_utc: Optional[datetime] = None,
) -> bool:
    """Spec §30 — REVERSAL_CONFIRMED updates active_direction on the
    slot ledger WITHOUT consuming a slot. Returns True iff the ledger
    was updated.

    This is the hook the news_trend_classifier state machine (or the
    orchestrator that watches it) should call when its bounce overlay
    transitions to REVERSAL_CONFIRMED. Idempotent: repeated calls with
    the same direction are no-ops.

    Fails permissive: any exception is logged and swallowed.
    """
    try:
        import news_slot_ledger as _slots
        ts = _now_utc() if now_utc is None else now_utc
        _slots.update_active_direction(epic, new_direction, ts)
        return True
    except Exception as exc:
        logger.warning(
            "[GATE] notify_confirmed_reversal failed epic=%s dir=%s: %s",
            epic, new_direction, exc,
        )
        return False


def snapshot_reservations() -> List[Dict[str, Any]]:
    """Read-only view of current reservations (test + telemetry helper)."""
    with _LOCK:
        return [
            {
                "reservation_id": r.reservation_id,
                "candidate_id": r.candidate_id,
                "epic": r.epic,
                "pair": r.pair,
                "side": r.side,
                "strategy_family": r.strategy_family,
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "occupied": r.occupied,
                "deal_id": r.deal_id,
                "deal_ref": r.deal_ref,
            }
            for r in _RESERVATIONS.values()
        ]


# Test hook.
def _reset_for_tests() -> None:
    with _LOCK:
        _RESERVATIONS.clear()
        _NEWS_EVAL_CTX.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Occupancy lifecycle repair (DEFECT-2026-09-18-A)
#
# Prior state: `_RESERVATIONS` was written on _make_reservation and had its
# `occupied` flag flipped on confirm_execution, but no path removed a
# reservation when its backing broker position closed. Over a multi-day
# PID lifetime the dict grew monotonically; `_snapshot_capacity` reported
# an ever-inflating `occupied_by_pair_family`. See
# reports-public/sep17_autonomous_trade_count_audit_amendment_20260918.md.
#
# Repair:
#   * release_reservation_by_deal_id(deal_id)  — remove a reservation whose
#     backing position closed. Idempotent; no-op if not present.
#   * release_reservation_by_pos_key(pos_key)  — same, keyed by pos_key.
#   * reconcile_reservations_with_broker(open_deal_ids) — repair local
#     ledger from an authoritative snapshot: drop occupied reservations
#     whose deal_id is not present in the broker set. Returns receipts.
#   * on_trade_close_callback(pos_key, exit_price, pnl_pips, close_reason,
#     deal_id=None) — signature-compatible with
#     trade_executor.register_trade_close_callback. Wiring below.
#
# Wiring (initializer / driver / consumer, per repo standing rule):
#   * initializer: `_wire_close_callback()` at end of this module — runs
#     at first import; self-registers via trade_executor.register_trade_close_callback.
#   * driver: `trade_executor.close_trade()` fires `_CLOSE_CALLBACKS` on
#     successful close (trade_executor.py ~3236).
#   * consumer: `on_trade_close_callback` here, which calls
#     `release_reservation_by_pos_key(pos_key)` and (if deal_id present)
#     `release_reservation_by_deal_id(deal_id)`.
#
# Reconciliation is exposed as a callable that a rest_sweeps.py or
# trade_manager.py caller can invoke on the periodic broker-poll cycle.
# It is intentionally not self-wired here — the poll cadence and error
# semantics are the caller's decision.
# ─────────────────────────────────────────────────────────────────────────────


def release_reservation_by_deal_id(deal_id: Optional[str]) -> bool:
    """Remove any reservation whose deal_id matches. Idempotent.

    Returns True iff at least one reservation was removed.
    Used by the trade-close callback and by reconciliation.
    """
    if not deal_id:
        return False
    did = str(deal_id).strip()
    if not did:
        return False
    removed_ids: List[str] = []
    with _LOCK:
        for rid, r in list(_RESERVATIONS.items()):
            if (r.deal_id or "").strip() == did:
                _RESERVATIONS.pop(rid, None)
                removed_ids.append(rid)
    if removed_ids:
        logger.info(
            "[GATE] released %d reservation(s) on close: deal_id=%s ids=%s",
            len(removed_ids), did, [x[:12] for x in removed_ids],
        )
    return bool(removed_ids)


def release_reservation_by_pos_key(pos_key: Optional[str]) -> bool:
    """Remove any reservation matching pos_key={epic}|{strategy_family_or_mode}.

    Used when the caller has pos_key but no deal_id (e.g. some close
    callback paths).
    """
    if not pos_key:
        return False
    pk = str(pos_key).strip()
    if "|" not in pk:
        return False
    epic_pk, _, family_pk = pk.partition("|")
    removed_ids: List[str] = []
    with _LOCK:
        for rid, r in list(_RESERVATIONS.items()):
            # Match on epic + strategy_family; be lenient (family_pk is
            # often a strategy name like GBPUSD_BB_BOUNCE_S, not the
            # family taxonomy string — accept either exact or startswith).
            if r.epic != epic_pk:
                continue
            family_match = (
                r.strategy_family == family_pk
                or family_pk.startswith(r.strategy_family or "")
                or (r.strategy_family or "") in family_pk
            )
            if family_match and r.occupied:
                _RESERVATIONS.pop(rid, None)
                removed_ids.append(rid)
    if removed_ids:
        logger.info(
            "[GATE] released %d reservation(s) on close by pos_key=%s ids=%s",
            len(removed_ids), pk, [x[:12] for x in removed_ids],
        )
    return bool(removed_ids)


def snapshot_occupied_reservation_deal_ids() -> "set":
    """Rev.3 §1 — capture the set of deal_ids on currently-occupied
    reservations. Held under `_LOCK` for a point-in-time snapshot.

    Used as `eligible_deal_ids` for snapshot-safe reservation
    reconciliation: a reservation confirmed AFTER this call cannot
    appear in the returned set and is therefore ineligible for removal
    by the reconciliation that consumes this snapshot.
    """
    with _LOCK:
        eligible = set()
        for r in _RESERVATIONS.values():
            if not r.occupied:
                continue
            did = (r.deal_id or "").strip()
            if did:
                eligible.add(did)
    return eligible


def reconcile_reservations_with_broker(
    open_deal_ids: Optional[Any],
    *,
    eligible_deal_ids: Optional["set"] = None,
) -> Dict[str, Any]:
    """Repair `_RESERVATIONS` against an authoritative broker snapshot.

    Args:
      open_deal_ids: iterable of deal_id strings for positions currently
        open at the broker. When None, treat broker state as unknown and
        return without touching local state (bounded conservative
        fallback — the caller decides how long to tolerate unknown-state).
      eligible_deal_ids: set of deal_ids captured BEFORE the broker
        snapshot request was sent. When provided, ONLY reservations
        whose deal_id is in this set are candidates for removal;
        reservations confirmed after the pre-snapshot moment are
        preserved regardless of the broker response. Rev.3 §1
        snapshot-safety. When None, retains rev.2 back-compat
        behaviour (no eligibility filter).

    Semantics:
      * A reservation with occupied=True and deal_id present, in
        eligible set (or eligibility unset), but NOT in broker set →
        drop (broker closed it, we missed the close callback).
      * A reservation with occupied=False (still awaiting confirmation)
        → left alone; TTL / release_on_failure handle those.
      * A broker-open deal_id with no matching reservation → NOT invented
        (broker-side manual opens are external, not gate-tracked).
      * With eligible_deal_ids provided: an occupied reservation whose
        deal_id is NOT in the eligible set (confirmed post-snapshot) is
        preserved regardless of the broker response.

    Returns a receipt dict:
      {
        "receipt": "OK" | "SKIP_BROKER_UNKNOWN",
        "local_occupied_before": int,
        "broker_open_count": int,
        "removed_reservation_ids": [str],
        "removed_deal_ids": [str],
        "preserved_post_snapshot_deal_ids": [str],
        "local_occupied_after": int,
      }

    Never logs credentials or full broker payloads — only deal_ids.
    """
    if open_deal_ids is None:
        with _LOCK:
            local_occ = sum(1 for r in _RESERVATIONS.values() if r.occupied)
        return {
            "receipt": "SKIP_BROKER_UNKNOWN",
            "local_occupied_before": local_occ,
            "broker_open_count": -1,
            "removed_reservation_ids": [],
            "removed_deal_ids": [],
            "preserved_post_snapshot_deal_ids": [],
            "local_occupied_after": local_occ,
        }
    broker_set = {str(x).strip() for x in open_deal_ids if str(x).strip()}
    elig = None
    if eligible_deal_ids is not None:
        elig = {str(x).strip() for x in eligible_deal_ids if str(x).strip()}
    removed_rids: List[str] = []
    removed_dids: List[str] = []
    preserved_post_snapshot: List[str] = []
    with _LOCK:
        local_occ_before = sum(1 for r in _RESERVATIONS.values() if r.occupied)
        for rid, r in list(_RESERVATIONS.items()):
            if not r.occupied:
                continue
            did = (r.deal_id or "").strip()
            if not did:
                # occupied reservation without a deal_id — cannot
                # authoritatively reconcile; leave for release_on_failure
                # or TTL. Real bug elsewhere if this persists.
                continue
            if elig is not None and did not in elig:
                # Post-snapshot occupancy — preserve. Rev.3 §1.
                preserved_post_snapshot.append(did)
                continue
            if did not in broker_set:
                _RESERVATIONS.pop(rid, None)
                removed_rids.append(rid)
                removed_dids.append(did)
        local_occ_after = sum(1 for r in _RESERVATIONS.values() if r.occupied)
    if removed_rids or preserved_post_snapshot:
        logger.info(
            "[GATE-RECONCILE] pruned %d stale reservation(s), "
            "preserved %d post-snapshot; "
            "local_occupied %d→%d broker_open=%d "
            "removed_ids=%s removed_deals=%s",
            len(removed_rids), len(preserved_post_snapshot),
            local_occ_before, local_occ_after,
            len(broker_set),
            [x[:12] for x in removed_rids],
            removed_dids,
        )
    return {
        "receipt": "OK",
        "local_occupied_before": local_occ_before,
        "broker_open_count": len(broker_set),
        "removed_reservation_ids": removed_rids,
        "removed_deal_ids": removed_dids,
        "preserved_post_snapshot_deal_ids": preserved_post_snapshot,
        "local_occupied_after": local_occ_after,
    }


def on_trade_close_callback(
    pos_key: str,
    exit_price: Optional[float] = None,
    pnl_pips: Optional[float] = None,
    close_reason: str = "",
    *,
    deal_id: Optional[str] = None,
) -> None:
    """Trade-close callback → release matching reservation.

    Signature matches trade_executor.register_trade_close_callback's
    (pos_key, exit_price, pnl_pips, close_reason, deal_id=...) contract.
    Idempotent; safe on already-removed reservations.
    """
    try:
        did = deal_id or ""
        removed_by_did = False
        if did:
            removed_by_did = release_reservation_by_deal_id(did)
        # Fall back to pos_key match when deal_id linkage missed the reservation.
        if not removed_by_did and pos_key:
            release_reservation_by_pos_key(pos_key)
    except Exception as exc:  # never propagate into trade_executor's callback chain
        logger.warning(
            "[GATE] on_trade_close_callback swallowed exception "
            "pos_key=%s deal_id=%s: %s",
            pos_key, deal_id, exc,
        )


def _wire_close_callback() -> bool:
    """Self-register with trade_executor's close-callback chain.

    Fires at first import of this module. Idempotent: if
    `on_trade_close_callback` is already in the chain (repeated
    reload_module in tests), skip.
    """
    try:
        import trade_executor as _te
    except Exception as exc:
        logger.debug(
            "[GATE] trade_executor unavailable at wire-time (skipping "
            "close-callback registration): %s", exc,
        )
        return False
    try:
        cbs = getattr(_te, "_CLOSE_CALLBACKS", None)
        if cbs is None:
            return False
        for existing in cbs:
            if getattr(existing, "__name__", "") == "on_trade_close_callback":
                # already wired (test reload path). Nothing to do.
                return False
        _te.register_trade_close_callback(on_trade_close_callback)
        logger.info(
            "[GATE] wired on_trade_close_callback into "
            "trade_executor._CLOSE_CALLBACKS (occupancy lifecycle repair)"
        )
        return True
    except Exception as exc:
        logger.warning(
            "[GATE] wire_close_callback failed: %s", exc,
        )
        return False


# Fire the wiring at import. Best-effort — never raises. Gate module
# is imported at autobot startup (autobot.py imports central_execution_gate),
# so this hook installs during the same boot that registers strategies
# and their own close callbacks. Position closes after this boot flow
# through this consumer.
_wire_close_callback()
