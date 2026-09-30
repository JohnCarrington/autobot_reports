"""orchestrator_v2.py — Phase 1 StrategyOrchestrator.

Per Phase 1 §4.

Owns:
    * Receiving candidate detections (via `submit()` — the seam that
      legacy dispatch sites call from during migration).
    * Normalising them into canonical Candidate objects.
    * Stamping the source, day-type snapshot, and lineage timestamps.
    * Deterministically resolving simultaneous candidates.
    * Sending each to CentralExecutionGate.
    * Recording permitted and rejected candidates via candidate_corpus_writer.

Does NOT (spec §4):
    * Submit broker orders.
    * Amend stops.
    * Manage open positions.
    * Decide TradeManager states.
    * Run ML or LLM.
    * Create permissions from QM confidence.

**Live behaviour rule**: while CENTRAL_STRATEGY_ORCHESTRATOR=0 (Phase 1
default) this module is SHADOW-ONLY: submit() logs candidates + gate
verdicts to the corpus but does NOT call execute_trade. The existing
autobot dispatch sites remain the live path.

When CENTRAL_STRATEGY_ORCHESTRATOR=1 (Phase 1 acceptance), submit()
becomes authoritative for migrated paths — but this is out of scope for
Batch 1 (see Phase 1 §5 detector-migration matrix).

Deterministic tie-breaking (spec §4 "resolving simultaneous candidates
deterministically"):
    When two candidates for the same (epic, side) window arrive within
    the same 5-minute bucket:
        1. Prefer LIVE detector-family precedence: news-family >
           briefing-family > qm-v2 > structure/trend > bb-family.
           (Rationale: match the legacy tick-cascade priority order
           observed in Phase 0.)
        2. Ties within a family: earliest FIRST_DETECTED_TS wins.
        3. Further ties: lexicographic candidate_id.
    All losers are still corpus-logged with reason
    'orchestrator_tie_loss:<winner_candidate_id>'.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import candidate as _cand
import central_execution_gate as _gate
import candidate_corpus_writer as _corpus
import day_type_adapter as _dta
import candidate_emission_recorder_v6 as _emrec

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Ownership persistence fault (Repair 9, 2026-09-29)
#
# When notify_executed() cannot persist the executed=True row to
# candidate_corpus, a real AutoBot broker position at IG has been
# opened but no durable ownership evidence exists. On the next restart
# reconcile will classify that position as FOREIGN.
#
# Per operator ruling §5:
#   * emit a critical persistence fault
#   * retain all available broker identity
#   * do NOT resubmit the trade
#   * do NOT create a duplicate
#   * preserve broker SL/TP
#   * make the condition operationally visible
#
# We satisfy this by:
#   (a) a logger.critical WARN line so journald + operator alerts see it,
#   (b) an append-only JSONL row to
#       logs/ownership_persistence_faults.jsonl with the full broker
#       identity (dealId, dealRef, execution_ts, execution_price,
#       candidate_id, strategy_family, source_path, exception).
#
# The caller (strategy_dispatch_adapter) already returned success; the
# broker position is live. No further action (retry, cancel, or close)
# is taken by this seam. Operator must intervene manually.
# ─────────────────────────────────────────────────────────────

_PERSISTENCE_FAULT_LOG_PATH = os.getenv(
    "OWNERSHIP_PERSISTENCE_FAULT_LOG_PATH",
    "/opt/tradingbot/logs/ownership_persistence_faults.jsonl",
)


def _persistence_fault_notify_executed(
    *,
    submit_result: "SubmitResult",
    deal_id: Optional[str],
    deal_ref: Optional[str],
    execution_ts: Optional[str],
    execution_price: Optional[float],
    exception: BaseException,
) -> None:
    """Never raises. Writes JSONL row + critical log line."""
    cand = getattr(submit_result, "canonical_candidate", None)
    candidate_id = str(getattr(cand, "candidate_id", "") or "") or None
    strategy_family = str(getattr(cand, "strategy_family", "") or "") or None
    source_path = str(getattr(cand, "source_path", "") or "") or None
    pair = str(getattr(cand, "pair", "") or "") or None
    epic = str(getattr(cand, "epic", "") or "") or None
    side = str(getattr(cand, "side", "") or "") or None
    ts_utc = datetime.now(timezone.utc).isoformat()

    logger.critical(
        "[PERSISTENCE_FAULT] notify_executed candidate_corpus write FAILED for "
        "real broker-open — dealId=%s dealRef=%s epic=%s side=%s "
        "family=%s source=%s candidate_id=%s execution_ts=%s "
        "exception=%s. Real AutoBot position at IG lacks durable ownership "
        "evidence. Do NOT resubmit. Do NOT duplicate. Broker SL/TP "
        "remains active. Manual reconciliation required.",
        deal_id, deal_ref, epic, side, strategy_family, source_path,
        candidate_id, execution_ts, exception,
        exc_info=True,
    )

    row = {
        "ts_utc": ts_utc,
        "kind": "ownership_persistence_fault",
        "seam": "orchestrator_v2.notify_executed",
        "deal_id": deal_id,
        "deal_reference": deal_ref,
        "epic": epic,
        "pair": pair,
        "side": side,
        "strategy_family": strategy_family,
        "source_path": source_path,
        "candidate_id": candidate_id,
        "execution_ts": execution_ts,
        "execution_price": execution_price,
        "exception_type": type(exception).__name__,
        "exception_msg": str(exception),
        "host": os.getenv("HOSTNAME") or os.uname().nodename,
        "operator_note": (
            "candidate_corpus.log_candidate raised; real broker position "
            "exists but AutoBot's durable ownership record does not. Reconcile "
            "will classify this deal as FOREIGN on the next restart unless "
            "it is backfilled or the corpus write is retried offline."
        ),
    }
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path(_PERSISTENCE_FAULT_LOG_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(row, default=str, separators=(",", ":")) + "\n")
    except Exception as write_exc:
        try:
            logger.error(
                "[PERSISTENCE_FAULT] follow-up JSONL write also failed: %s",
                write_exc,
            )
        except Exception:
            pass


def _env_bool(name: str, default: str) -> bool:
    return (os.getenv(name, default) or default).strip().lower() in (
        "1", "true", "yes", "on",
    )


def orchestrator_active() -> bool:
    """True iff CENTRAL_STRATEGY_ORCHESTRATOR=1 — this module is the
    LIVE dispatch authority for migrated paths."""
    return _env_bool("CENTRAL_STRATEGY_ORCHESTRATOR", "0")


def shadow_enabled() -> bool:
    """True iff shadow-mode logging is enabled (default ON so corpus
    accumulates data before the live flag flips)."""
    return _env_bool("ORCHESTRATOR_V2_SHADOW", "1")


# ── Family precedence for tie-breaking ─────────────────────────────────────
_FAMILY_PRECEDENCE = {
    # Higher = higher priority
    _cand.FAMILY_NEWS_STRATEGY: 90,
    _cand.FAMILY_NEWS_TICK: 90,
    _cand.FAMILY_NEWS_CONTINUATION: 85,
    _cand.FAMILY_BRIEFING_EXECUTION: 80,
    _cand.FAMILY_BRIEFING_V5: 78,
    _cand.FAMILY_BRIEFING_LIQUIDITY: 75,
    _cand.FAMILY_BRIEFING_SWEEP: 72,
    _cand.FAMILY_BRIEFING_HUNT: 70,
    _cand.FAMILY_PIA_FIRST: 68,
    _cand.FAMILY_QM_V2: 60,
    _cand.FAMILY_V2_PICK_BOUNCE: 58,   # SDE pick-bounce — below QM_V2 velocity, above trend/structure
    _cand.FAMILY_TREND_V3: 55,
    _cand.FAMILY_STRUCTURE_BREAK: 50,
    _cand.FAMILY_CONFIRMATION_FALLBACK: 45,
    _cand.FAMILY_PIVOT_BREAK: 42,
    _cand.FAMILY_LEVEL_BOUNCE: 40,
    _cand.FAMILY_BB_BOUNCE: 35,
    _cand.FAMILY_BB_REVERSAL_PATTERNS: 32,
    _cand.FAMILY_EMA_PULLBACK: 30,
    _cand.FAMILY_H1_PIERCE: 25,
    _cand.FAMILY_LIQUIDITY_SWEEP: 20,
    _cand.FAMILY_WINDOW_SWEEP: 18,
    _cand.FAMILY_UNKNOWN: 0,
}


@dataclass
class SubmitResult:
    """Return value from submit(). Whether the orchestrator would have
    fired (in live mode) plus the full audit trail."""
    canonical_candidate: Any  # Candidate
    gate_decision: _gate.GateDecision
    tie_winner: bool
    tie_loser: bool
    tie_winner_id: Optional[str]
    live_mode: bool


# ── In-flight bucket for tie resolution ────────────────────────────────────
# Per (epic, side, 5m-bucket) we hold submitted candidates for a short
# window then resolve. Bucket TTL matches the 5m boundary; entries age
# out lazily.
_BUCKET_LOCK = threading.RLock()
_BUCKET_INFLIGHT: Dict[Tuple[str, str, int], List[Any]] = {}


def _bucket_5m(ts_epoch: float) -> int:
    return int(ts_epoch) // 300


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _make_candidate_id() -> str:
    return uuid.uuid4().hex


def _resolve_tie(candidates: List[Any]) -> Tuple[Any, List[Any]]:
    """Pick the highest-precedence candidate; return (winner, losers).

    Precedence: family precedence desc, then first_detected_ts asc,
    then candidate_id lexicographic asc.
    """
    def key(c: Any) -> Tuple[int, str, str]:
        fam = getattr(c, "strategy_family", _cand.FAMILY_UNKNOWN)
        prec = _FAMILY_PRECEDENCE.get(fam, 0)
        ts = getattr(c, "first_detected_ts", None) or getattr(c, "timestamp", "")
        cid = getattr(c, "candidate_id", "")
        return (-prec, str(ts), str(cid))
    sorted_c = sorted(candidates, key=key)
    return sorted_c[0], sorted_c[1:]


# ── Public API ─────────────────────────────────────────────────────────────
def build_candidate(
    *,
    epic: str,
    pair: str,
    strategy: str,
    strategy_family: str,
    side: str,
    opportunity_type: str,
    candidate_price: float,
    source_path: str,
    proposed_stop: Optional[float] = None,
    proposed_target: Optional[float] = None,
    market_state_snapshot: Optional[Dict[str, Any]] = None,
    reason_codes: Optional[List[str]] = None,
    mechanical_valid: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
    detected_ts: Optional[str] = None,
) -> Any:
    """Convenience factory that fills lineage timestamps and captures
    the raw day_type snapshot. Returns a Candidate. Never raises for
    optional-field misuse — will raise only on the hard invariants
    Candidate itself enforces."""
    now_iso = (_now_utc()).isoformat()
    day_snap = {}
    try:
        day_snap = {
            k: v for k, v in _dta.resolve().items()
            if k in ("raw_calendar_day_type", "raw_day_context")
        }
    except Exception as exc:
        logger.debug("[orchestrator_v2] day_type resolve failed: %s", exc)

    return _cand.Candidate(
        candidate_id=_make_candidate_id(),
        timestamp=detected_ts or now_iso,
        epic=epic,
        pair=str(pair).upper(),
        strategy=strategy,
        strategy_family=strategy_family,
        side=str(side).upper(),
        opportunity_type=opportunity_type,
        candidate_price=float(candidate_price),
        proposed_stop=proposed_stop,
        proposed_target=proposed_target,
        source_path=source_path,
        day_type_raw=day_snap,
        market_state_snapshot=dict(market_state_snapshot or {}),
        reason_codes=list(reason_codes or []),
        mechanical_valid=mechanical_valid,
        metadata=dict(metadata or {}),
        event_id=event_id,
        first_detected_ts=detected_ts or now_iso,
        first_actionable_ts=None,
    )


def submit(candidate: Any, *, actionable_ts: Optional[str] = None) -> SubmitResult:
    """Submit a Candidate for evaluation.

    Behaviour:
        * Stamp FIRST_ACTIONABLE_TS if not already set.
        * Resolve simultaneous candidates for the same (epic, side)
          bucket deterministically.
        * Call CentralExecutionGate.evaluate().
        * Log the (candidate, gate_decision) to the candidate corpus.
        * Return a SubmitResult with the outcome.

    Never raises. In shadow mode (default) the caller MUST NOT stop
    calling the legacy dispatch path — the SubmitResult is telemetry.

    In live mode (CENTRAL_STRATEGY_ORCHESTRATOR=1), when
    gate_decision.allowed is True the caller may proceed to
    execute_trade(); on reject the caller must not fire. This flip is
    NOT wired in Batch 1.
    """
    live = orchestrator_active()
    try:
        # Stamp actionable ts.
        stamped = candidate
        if actionable_ts and getattr(candidate, "first_actionable_ts", None) is None:
            stamped = candidate.with_actionable(actionable_ts)

        # Stage 6G prospective emission recorder (default OFF via
        # CANDIDATE_EMISSION_RECORDER_V6_ENABLED=0). Observes the emission
        # AFTER canonical-form arrival (Candidate normalised + actionable
        # stamped) but BEFORE bucket admission, tie resolution, and gate
        # evaluation — the earliest point at which a canonical Candidate
        # exists in this seam. Fail-silent per Stage 6G §16; a recorder
        # exception never alters caller flow (no admit/reject, no field
        # mutation, no ordering effect on downstream tie/gate logic).
        try:
            _emrec.observe_emission(stamped)
        except Exception as _emrec_exc:  # noqa: BLE001
            logger.debug(
                "[orchestrator_v2] emission recorder skipped for %s: %s",
                str(getattr(stamped, "candidate_id", "") or ""),
                _emrec_exc,
            )

        # Tie resolution against in-flight bucket entries.
        epic = str(getattr(stamped, "epic", "") or "")
        side = str(getattr(stamped, "side", "") or "").upper()
        ts_raw = str(getattr(stamped, "first_detected_ts", "") or getattr(stamped, "timestamp", ""))
        try:
            ts_epoch = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            ts_epoch = _now_utc().timestamp()
        bucket_key = (epic, side, _bucket_5m(ts_epoch))

        tie_winner_id: Optional[str] = None
        tie_winner = True
        tie_loser = False

        with _BUCKET_LOCK:
            bucket = _BUCKET_INFLIGHT.setdefault(bucket_key, [])
            bucket.append(stamped)
            # Age-out: keep only entries within the bucket.
            # (Bucket key already contains the bucket id, so bucket only
            # holds this bucket's submissions.) We still prune stale
            # buckets opportunistically.
            _prune_stale_buckets(ts_epoch)
            if len(bucket) > 1:
                winner, losers = _resolve_tie(bucket)
                tie_winner_id = str(getattr(winner, "candidate_id", "") or "")
                if getattr(stamped, "candidate_id", "") != tie_winner_id:
                    tie_winner = False
                    tie_loser = True
                    stamped = stamped.with_reason(
                        f"orchestrator_tie_loss:{tie_winner_id}"
                    )

        # Gate evaluation (always runs — shadow mode uses it for parity).
        gate_dec = _gate.evaluate(stamped)

        # If this candidate is a tie-loser, downgrade allowed to False
        # in the ORCHESTRATOR's reported outcome. The gate itself still
        # produced its own verdict; the tie-loss is a higher-order
        # orchestrator decision.
        if tie_loser and gate_dec.allowed:
            # We synthesise a "would-have-been-allowed-but-tie" decision
            # by copying with allowed=False and merging reason_codes.
            # (GateDecision is frozen so we replace via dataclasses.)
            from dataclasses import replace as _replace
            gate_dec = _replace(
                gate_dec,
                allowed=False,
                reason_codes=list(gate_dec.reason_codes) + [
                    f"orchestrator_tie_loss:{tie_winner_id}"
                ],
            )
            # Release the reservation the gate created.
            _gate.release_on_failure(
                gate_dec.reservation_id,
                reason="orchestrator_tie_loss",
            )
            gate_dec = _replace(gate_dec, reservation_id=None)

        # Corpus write (permit + reject alike).
        try:
            canon_day = _dta.resolve().get("canonical")
        except Exception:
            canon_day = None
        try:
            obs_snap = _gate.observation_snapshot(
                str(getattr(stamped, "pair", "") or "")
            )
        except Exception:
            obs_snap = None
        try:
            nt_snap = _gate.news_trend_snapshot(
                str(getattr(stamped, "pair", "") or "")
            )
        except Exception:
            nt_snap = None
        try:
            _corpus.log_candidate(
                stamped,
                day_type_canonical=canon_day,
                gate_decision=gate_dec,
                executed=False,
                observation_snapshot=obs_snap,
                news_trend_snapshot=nt_snap,
            )
        except Exception as exc:
            logger.debug("[orchestrator_v2] corpus log failed: %s", exc)

        # Core five-family selector — records the submission so the
        # per-(pair, bucket) selector can surface an explicit winner
        # or NO_TRADE. Fail-silent; the selector never influences the
        # gate verdict.
        try:
            import core_strategy_selector as _sel
            _sel.record_submission(stamped, gate_dec)
        except Exception as exc:
            logger.debug("[orchestrator_v2] core_selector record failed: %s", exc)

        return SubmitResult(
            canonical_candidate=stamped,
            gate_decision=gate_dec,
            tie_winner=tie_winner,
            tie_loser=tie_loser,
            tie_winner_id=tie_winner_id,
            live_mode=live,
        )
    except Exception as exc:
        # Absolute fail-safe: return a permissive-but-not-reserved
        # result so no shadow path can inadvertently block live behaviour.
        logger.warning("[orchestrator_v2] submit() raised: %s", exc, exc_info=True)
        return SubmitResult(
            canonical_candidate=candidate,
            gate_decision=_gate.GateDecision(
                allowed=False,
                reason_codes=[f"orchestrator_exception:{type(exc).__name__}"],
                reservation_id=None,
                capacity_snapshot={},
                candidate_id=str(getattr(candidate, "candidate_id", "") or ""),
                timestamp=_now_utc().isoformat(),
                live=False,
            ),
            tie_winner=False,
            tie_loser=False,
            tie_winner_id=None,
            live_mode=live,
        )


def notify_executed(
    submit_result: SubmitResult,
    *,
    deal_ref: Optional[str] = None,
    deal_id: Optional[str] = None,
    execution_ts: Optional[str] = None,
    execution_price: Optional[float] = None,
) -> None:
    """Called by the caller AFTER execute_trade returns success.

    Converts the reservation to occupied and updates the corpus row
    with execution outcome. In Phase 1 shadow mode this is called with
    execution data from the legacy path so the corpus reflects live
    reality.
    """
    try:
        _gate.confirm_execution(
            submit_result.gate_decision.reservation_id,
            deal_id=deal_id,
            deal_ref=deal_ref,
        )
    except Exception as exc:
        logger.debug("[orchestrator_v2] confirm_execution failed: %s", exc)

    try:
        canon_day = _dta.resolve().get("canonical")
    except Exception:
        canon_day = None
    try:
        obs_snap = _gate.observation_snapshot(
            str(getattr(submit_result.canonical_candidate, "pair", "") or "")
        )
    except Exception:
        obs_snap = None
    try:
        nt_snap = _gate.news_trend_snapshot(
            str(getattr(submit_result.canonical_candidate, "pair", "") or "")
        )
    except Exception:
        nt_snap = None
    try:
        _corpus.log_candidate(
            submit_result.canonical_candidate,
            day_type_canonical=canon_day,
            gate_decision=submit_result.gate_decision,
            executed=True,
            execution_deal_ref=deal_ref,
            execution_deal_id=deal_id,
            execution_ts=execution_ts,
            execution_price=execution_price,
            observation_snapshot=obs_snap,
            news_trend_snapshot=nt_snap,
        )
    except Exception as exc:
        # Repair 9 (2026-09-29). candidate_corpus is the sole durable
        # ownership evidence for orchestrator-routed families (see
        # trade_executor lookup_candidate_corpus_by_deal_id and the
        # RECONCILE own-deals-only gate). If this write fails after a
        # confirmed broker-open, the real AutoBot position at IG will
        # be reconciled as FOREIGN on the next restart. Operator §5
        # requires: emit critical persistence fault, retain all
        # available broker identity, do NOT resubmit / duplicate,
        # preserve broker SL/TP, make the condition operationally
        # visible.
        _persistence_fault_notify_executed(
            submit_result=submit_result,
            deal_id=deal_id,
            deal_ref=deal_ref,
            execution_ts=execution_ts,
            execution_price=execution_price,
            exception=exc,
        )


def notify_execution_failed(
    submit_result: SubmitResult,
    *,
    reason: str,
) -> None:
    """Called when execute_trade rejected or crashed post-gate approval.

    Releases the reservation and logs the failure to the corpus.
    """
    try:
        _gate.release_on_failure(
            submit_result.gate_decision.reservation_id,
            reason=reason,
        )
    except Exception as exc:
        logger.debug("[orchestrator_v2] release_on_failure raised: %s", exc)

    try:
        canon_day = _dta.resolve().get("canonical")
    except Exception:
        canon_day = None
    try:
        obs_snap = _gate.observation_snapshot(
            str(getattr(submit_result.canonical_candidate, "pair", "") or "")
        )
    except Exception:
        obs_snap = None
    try:
        nt_snap = _gate.news_trend_snapshot(
            str(getattr(submit_result.canonical_candidate, "pair", "") or "")
        )
    except Exception:
        nt_snap = None
    try:
        # Downgrade the cached gate decision to reflect release.
        from dataclasses import replace as _replace
        gd = _replace(
            submit_result.gate_decision,
            allowed=False,
            reason_codes=list(submit_result.gate_decision.reason_codes) + [
                f"execution_failed:{reason}",
            ],
            reservation_id=None,
        )
        _corpus.log_candidate(
            submit_result.canonical_candidate,
            day_type_canonical=canon_day,
            gate_decision=gd,
            executed=False,
            observation_snapshot=obs_snap,
            news_trend_snapshot=nt_snap,
        )
    except Exception as exc:
        logger.debug("[orchestrator_v2] failed corpus log raised: %s", exc)


# ── Housekeeping ───────────────────────────────────────────────────────────
def _prune_stale_buckets(now_ts_epoch: float, ttl_buckets: int = 2) -> None:
    """Drop bucket entries whose bucket_id is older than TTL. Called under
    _BUCKET_LOCK by the caller."""
    now_bucket = int(now_ts_epoch) // 300
    stale = [k for k in _BUCKET_INFLIGHT if now_bucket - k[2] > ttl_buckets]
    for k in stale:
        _BUCKET_INFLIGHT.pop(k, None)


# Test hook.
def _reset_for_tests() -> None:
    with _BUCKET_LOCK:
        _BUCKET_INFLIGHT.clear()
