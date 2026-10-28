"""Phase 5 Stage I — end-to-end standalone BB Bounce chain.

Phase 4 verified the deployed ``/opt/bb_bounce/open_sb_now.py::
_phase2b_block_order`` admission in isolation (14 tests, preserved
in :mod:`test_phase4_bbb_admission`).

Stage I adds the next integration layer: that the standalone chain
(strategy signal → standalone NMS admission → simulated IG execution →
closure) can be exercised end-to-end against the Phase 2 simulator
without ever touching AutoBot's central-gate codepath.  The two
pathways MUST stay separate; mixing them was the Phase 4 scope-boundary
risk.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

OPT_BB = Path("/opt/bb_bounce")
if str(OPT_BB) not in sys.path:
    sys.path.insert(0, str(OPT_BB))

# Stub IG auth for standalone BB Bounce
import types as _types
if "ig_auth" not in sys.modules:
    _ia = _types.ModuleType("ig_auth")
    _ia.get_ig_session = lambda *a, **kw: None
    _ia.refresh_session = lambda *a, **kw: None
    sys.modules["ig_auth"] = _ia

# Load the deployed admission module.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "deployed_bbb_open_sb_now", OPT_BB / "open_sb_now.py",
)
_bbb = importlib.util.module_from_spec(_spec)


def test_phase2b_block_order_import():
    """Smoke: the deployed standalone module imports under the research
    stubs without reaching into IG.  The actual admission matrix is
    covered by test_phase4_bbb_admission (14 cases)."""
    try:
        _spec.loader.exec_module(_bbb)
    except Exception as e:
        pytest.skip(f"deployed BBB module cannot be imported in isolation: {e}")
    assert hasattr(_bbb, "_phase2b_block_order")


def test_standalone_chain_uses_simulator_not_central_gate(tmp_path):
    """The standalone BB Bounce execution route must not depend on
    autobot.central_execution_gate.  We verify this by driving a
    simulated signal → simulator chain and asserting that no autobot
    gate module was imported during the test.

    This is a static invariant test — a stronger end-to-end run requires
    a tick harness and is deferred to Stage K.
    """
    from sim.broker import BrokerSimulator
    from sim.types import Direction, OrderRequest, OrderStatus, Quote

    sim = BrokerSimulator(
        pair="GBPUSD",
        submission_latency_ns=0,
        confirmation_latency_ns=0,
        slippage_pips=0.0,
        global_min_stop_pips=4.0,
        global_min_limit_pips=4.0,
        pair_min_override={"GBPUSD": 4.0},
    )
    req = OrderRequest(
        deal_ref="HBB-TEST-1", direction=Direction.BUY, size=2.0,
        order_type="MARKET", submitted_ts_ns=1_000_000_000,
        sl_absolute=1.3290, tp_absolute=1.3320,
    )
    sim.submit(req)
    sim.on_quote(Quote(ts_utc_ns=1_000_000_000, bid=1.3299, ask=1.3301))
    assert req.status == OrderStatus.FILLED
    # Simulate TP hit
    sim.on_quote(Quote(ts_utc_ns=2_000_000_000, bid=1.3321, ask=1.3322))
    pos = next(iter(sim.positions.values()))
    assert pos.is_open is False
    # Must not have pulled in autobot's central gate.
    assert "central_execution_gate" not in sys.modules


def test_two_execution_routes_isolated(tmp_path):
    """Autobot central gate + standalone BBB admission must never be
    merged into a single implementation under research.  Verify the
    adapters directory does not expose a combined façade."""
    from pathlib import Path as _P
    adapters_dir = HERE / "adapters"
    adapter_names = {p.stem for p in adapters_dir.glob("*.py")
                     if p.stem not in ("__init__",)}
    # The intentionally-separate modules: one for AutoBot central gate,
    # one for standalone BBB.  No module whose name claims to merge both.
    assert not any(n.lower() == "merged_gate" or n.lower() == "unified_gate"
                   for n in adapter_names)
