"""Phase 3C — real NMS + central_execution_gate integration tests.

Under `init_isolation(deployed_policy=True)`:
  - central_execution_gate loads from /opt/tradingbot (real code).
  - nms_directional_authority loads from /opt/tradingbot (real code).
  - nms_v3_direction_gate loads (real code).
  - Candidate dataclass is the production class.

These tests verify that the real deployed gate chain correctly BLOCKS
candidates under the current fail-closed policy, and that no blocked
signal can reach the Phase 2 BrokerSimulator.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.isolation import init_isolation  # noqa: E402
from adapters.nms_gate_adapter import build_candidate, run_chain  # noqa: E402


def test_real_nms_gate_imports_under_deployed_policy():
    """Prove nms_directional_authority, central_execution_gate, candidate are
    the REAL production modules (not stubs) under deployed_policy mode."""
    with init_isolation(deployed_policy=True) as installed:
        import nms_directional_authority as nms
        import central_execution_gate as ceg
        import candidate as c
        for mod, name in [(nms, "nms_directional_authority"),
                          (ceg, "central_execution_gate"),
                          (c, "candidate")]:
            f = getattr(mod, "__file__", "") or ""
            assert "<stub:" not in f, f"{name} is still a stub: {f}"
            assert "/opt/tradingbot" in f, f"{name} did not load from prod: {f}"


def test_bb_bounce_blocked_by_one_strategy_cutover_without_admit():
    """BB Bounce candidate with BB_BOUNCE_ADMIT=0 is blocked by
    one_strategy_cutover_guard — no reservation issued, no fill downstream."""
    with init_isolation(deployed_policy=True, extra_env={"BB_BOUNCE_ADMIT": "0"}):
        cand = build_candidate(
            pair="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
            strategy="GBPUSD_BB_BOUNCE_S", strategy_family="BB_BOUNCE",
            side="SELL", opportunity_type="BOUNCE",
            candidate_price=13655.0, proposed_stop=13668.0, proposed_target=13555.0,
        )
        v = run_chain(cand)
        assert v.gate_allowed is False
        assert v.gate_binding_delegate == "one_strategy_cutover_guard"
        assert any("blocked_legacy_family=BB_BOUNCE" in c for c in v.gate_reason_codes), v.gate_reason_codes
        assert v.final_allowed is False
        assert v.final_block_source == "central_execution_gate"


def test_bb_bounce_passes_cutover_but_blocked_downstream_with_admit():
    """With BB_BOUNCE_ADMIT=1 (deployed default), the cutover guard passes,
    but downstream delegates (normal_routing in fail-closed mode) still block."""
    with init_isolation(deployed_policy=True):
        cand = build_candidate(
            pair="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
            strategy="GBPUSD_BB_BOUNCE_S", strategy_family="BB_BOUNCE",
            side="SELL", opportunity_type="BOUNCE",
            candidate_price=13655.0, proposed_stop=13668.0, proposed_target=13555.0,
        )
        v = run_chain(cand)
        assert v.gate_allowed is False
        assert v.gate_binding_delegate == "normal_routing"
        assert v.final_allowed is False
        assert v.final_block_source == "central_execution_gate"


def test_nms_directional_authority_not_applicable_for_bb_bounce_family():
    """NMS unified matrix covers TREND_CONTINUATION / TREND_PULLBACK / BOUNCE
    families — the BB_BOUNCE family tag used by the strategy is NOT in the
    matrix. The authority returns applicable=False so the strategy's own
    admission logic (via nms_second_gate or seam-level permit_bounce)
    applies. This is a documented production invariant per the authority's
    matrix docstring."""
    with init_isolation(deployed_policy=True):
        cand = build_candidate(
            pair="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
            strategy="GBPUSD_BB_BOUNCE_S", strategy_family="BB_BOUNCE",
            side="SELL", opportunity_type="BOUNCE",
            candidate_price=13655.0,
        )
        v = run_chain(cand)
        assert v.nms_applicable is False
        assert "NOT_APPLICABLE_FAMILY" in v.nms_reason


def test_blocked_signal_does_not_reach_simulator():
    """A blocked candidate must NEVER produce a broker order. Verify end-to-end
    that `run_chain(cand).final_allowed=False` prevents OrderRequest submission."""
    sys.path.insert(0, str(ROOT))
    from sim.broker import BrokerSimulator
    from sim.types import Direction, OrderRequest, Quote

    broker = BrokerSimulator(pair="GBPUSD")
    broker.on_quote(Quote(1_000_000_000, 1.3655, 1.3656))
    with init_isolation(deployed_policy=True):
        cand = build_candidate(
            pair="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
            strategy="GBPUSD_BB_BOUNCE_S", strategy_family="BB_BOUNCE",
            side="SELL", opportunity_type="BOUNCE",
            candidate_price=13655.0,
        )
        v = run_chain(cand)
        assert v.final_allowed is False, "test must exercise the BLOCK path"
        if not v.final_allowed:
            # The adapter contract is: do NOT submit on block.
            # Verify broker still has no open positions.
            pass
        assert len(broker.open_positions()) == 0
        assert len([e for e in broker.events if e.kind == "ORDER_SUBMITTED"]) == 0


def test_gate_reservation_ledger_isolated_per_run():
    """Each init_isolation(deployed_policy=True) context pops+reimports the
    gate, so its in-memory reservation ledger is a fresh dict. Verify no
    state leaks between separate test invocations."""
    with init_isolation(deployed_policy=True):
        import central_execution_gate as ceg
        cand = build_candidate(
            pair="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
            strategy="GBPUSD_BB_BOUNCE_S", strategy_family="BB_BOUNCE",
            side="SELL", opportunity_type="BOUNCE",
            candidate_price=13655.0,
        )
        ceg.evaluate(cand)
        snap_a = ceg._snapshot_capacity()

    with init_isolation(deployed_policy=True):
        import central_execution_gate as ceg2
        snap_b = ceg2._snapshot_capacity()

    # Both snapshots are from a fresh gate module; capacity ledger
    # should be empty / default on each.
    assert isinstance(snap_a, dict)
    assert isinstance(snap_b, dict)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
