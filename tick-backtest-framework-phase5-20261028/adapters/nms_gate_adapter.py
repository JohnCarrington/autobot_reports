"""Phase 3C — real NMS + central_execution_gate integration adapter.

Replaces the Phase 3b bypass of these two modules with isolated invocations
of the actual deployed production code.

Design:
  - Imports production `nms_directional_authority.evaluate` and
    `central_execution_gate.evaluate` under the Phase 3C isolation seam.
  - Builds a production `candidate.Candidate` from a BB Bounce fire.
  - Returns both decisions plus a derived verdict.

Isolation guarantees (preserved from Phase 3b):
  - The gate reads env flags; the caller sets them per scenario.
  - The gate's `install_state_provider` seam is NOT touched here; the gate
    runs against whatever in-process state the isolation seam has primed.
  - For NMS, the authority reads session_trend + exhaustion caches; absent
    those, state is UNKNOWN → matrix returns BLOCK. That is the correct
    deployed-policy answer for a candidate with no NMS evidence.

What this adapter does NOT do:
  - Does NOT invent NMS state. UNKNOWN remains UNKNOWN.
  - Does NOT fabricate exhaustion freshness. The real detector cache files
    at /opt/tradingbot/cache/nms_exhaustion_<SYM>.json are read by the real
    code; a test wanting ALLOW must either place a fixture file in a
    pointed-at cache dir or inject via `install_state_provider`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Phase 3C: assume we're inside init_isolation(..., deployed_policy=True).
# Production modules are imported lazily inside call_* so a caller importing
# this adapter outside an isolation context does not accidentally pull live
# modules.


@dataclass
class ChainVerdict:
    """Aggregate decision after NMS + central_execution_gate."""
    nms_applicable: bool
    nms_allowed: bool
    nms_reason: str
    nms_v3_state: str
    gate_allowed: bool
    gate_reason_codes: list
    gate_binding_delegate: Optional[str]
    final_allowed: bool
    final_block_source: Optional[str]


def build_candidate(
    *,
    pair: str,
    epic: str,
    strategy: str,
    strategy_family: str,
    side: str,
    opportunity_type: str,
    candidate_price: float,
    proposed_stop: Optional[float] = None,
    proposed_target: Optional[float] = None,
    candidate_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
):
    """Build a production Candidate from a BB Bounce fire. Returns Candidate.

    Caller must be inside init_isolation(). The real `candidate.Candidate`
    is imported here so this adapter is safely importable outside isolation.
    """
    import candidate as _c  # production module
    import uuid as _uuid
    ts = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    cid = candidate_id or f"P3C-{_uuid.uuid4().hex[:12]}"
    # Candidate's internal convention is LONG/SHORT, not BUY/SELL (production source).
    side_u = str(side or "").strip().upper()
    cand_side = "LONG" if side_u in ("BUY", "LONG") else ("SHORT" if side_u in ("SELL", "SHORT") else side_u)
    return _c.Candidate(
        candidate_id=cid,
        timestamp=ts,
        epic=epic,
        pair=pair.upper(),
        strategy=strategy,
        strategy_family=strategy_family,
        side=cand_side,
        opportunity_type=opportunity_type,
        candidate_price=float(candidate_price),
        proposed_stop=proposed_stop,
        proposed_target=proposed_target,
        source_path="PHASE3C_RESEARCH_ADAPTER",
    )


def call_nms_authority(cand) -> dict:
    """Invoke the real production NMS directional authority. Returns the
    `.to_dict()` form of a `DirectionalDecision`.

    NMS authority uses BUY/SELL for its `side` arg; translate from the
    Candidate's internal LONG/SHORT convention.
    """
    import nms_directional_authority as _nms
    cand_side_u = str(cand.side or "").strip().upper()
    nms_side = "BUY" if cand_side_u == "LONG" else ("SELL" if cand_side_u == "SHORT" else cand_side_u)
    decision = _nms.evaluate(
        symbol=cand.pair,
        strategy_id=cand.strategy,
        strategy_family=cand.strategy_family,
        side=nms_side,
    )
    return decision.to_dict()


def call_central_execution_gate(cand) -> dict:
    """Invoke the real production central execution gate. Returns a plain
    dict form of GateDecision."""
    import central_execution_gate as _ceg
    decision = _ceg.evaluate(cand)
    return {
        "allowed": decision.allowed,
        "reason_codes": list(decision.reason_codes),
        "reservation_id": decision.reservation_id,
        "candidate_id": decision.candidate_id,
        "timestamp": decision.timestamp,
        "live": decision.live,
        "verdict": decision.verdict,
        "binding_delegate": decision.binding_delegate,
    }


def run_chain(cand) -> ChainVerdict:
    """Full chain: NMS authority → central_execution_gate → verdict.

    The chain BLOCKS a signal if either NMS blocks it (and it's applicable),
    OR the gate rejects it. A blocked signal must never be forwarded to the
    broker simulator — callers consume `.final_allowed` to decide.
    """
    nms = call_nms_authority(cand)
    gate = call_central_execution_gate(cand)

    nms_applicable = bool(nms.get("applicable"))
    nms_allowed = bool(nms.get("allowed"))
    nms_blocks = nms_applicable and not nms_allowed

    gate_allowed = bool(gate.get("allowed"))

    final_allowed = (not nms_blocks) and gate_allowed
    final_block_source = None
    if nms_blocks and not gate_allowed:
        final_block_source = "both"
    elif nms_blocks:
        final_block_source = "nms_directional_authority"
    elif not gate_allowed:
        final_block_source = "central_execution_gate"

    return ChainVerdict(
        nms_applicable=nms_applicable,
        nms_allowed=nms_allowed,
        nms_reason=nms.get("reason_code") or "",
        nms_v3_state=nms.get("nms_v3_state") or "",
        gate_allowed=gate_allowed,
        gate_reason_codes=gate["reason_codes"],
        gate_binding_delegate=gate.get("binding_delegate"),
        final_allowed=final_allowed,
        final_block_source=final_block_source,
    )
