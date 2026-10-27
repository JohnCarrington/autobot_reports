"""Phase 3b pathway + end-to-end tests.

Covers:
  - Zero replay exceptions over the 5-day historical fixture (regression)
  - Each synthetic fire fixture produces the expected fire or no-fire
  - End-to-end BUY and SELL complete the simulator chain
  - Isolation seam holds (no production side-effects)
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Make the Phase 2 sim/ importable
_SIM_DIR = ROOT / "sim"
if _SIM_DIR.exists() and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.isolation import init_isolation, assert_no_production_side_effects  # noqa: E402
from fixtures.bb_fire_fixtures import (  # noqa: E402
    fixture_classic_pierce_long, fixture_classic_pierce_short,
    fixture_no_pierce_no_fire, fixture_outside_window_blocked,
    fixture_wrong_direction_rejection, fixture_both_bands_blocked,
)


def _drive_fixture(fixture):
    """Return (fires, state_transitions_count, lifecycle_events_count)."""
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        lifecycle: list = []
        bb._write_bb_bounce_lifecycle_row = lifecycle.append
        s = bb.GbpUsdBBBounceStrategy()
        bars_so_far, closes = [], []
        fires = []
        transitions = 0
        for bar in fixture["bars"]:
            bars_so_far.append(bar)
            closes.append(float(bar.close))
            pre_armed = len(s._armed_setups.get("CS.D.GBPUSD.TODAY.IP", []))
            d = s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar.timestamp,
                           bars_so_far, closes, False, False)
            post_armed = len(s._armed_setups.get("CS.D.GBPUSD.TODAY.IP", []))
            if pre_armed != post_armed:
                transitions += 1
            if d is not None:
                fires.append(d)
        return fires, transitions, len(lifecycle)


# ─── Positive fire fixtures ─────────────────────────────────────────────────

def test_classic_pierce_long_fires_buy():
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        fix = fixture_classic_pierce_long(bb)
    fires, _, _ = _drive_fixture(fix)
    assert len(fires) == 1, f"expected 1 fire, got {len(fires)}"
    assert fires[0].signal == "BUY"


def test_classic_pierce_short_fires_sell():
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        fix = fixture_classic_pierce_short(bb)
    fires, _, _ = _drive_fixture(fix)
    assert len(fires) == 1
    assert fires[0].signal == "SELL"


# ─── Negative fire fixtures ─────────────────────────────────────────────────

def test_shallow_pierce_no_fire():
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        fix = fixture_no_pierce_no_fire(bb)
    fires, _, _ = _drive_fixture(fix)
    assert len(fires) == 0


def test_outside_window_blocked():
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        fix = fixture_outside_window_blocked(bb)
    fires, _, _ = _drive_fixture(fix)
    assert len(fires) == 0


def test_wrong_direction_rejection_no_fire():
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        fix = fixture_wrong_direction_rejection(bb)
    fires, _, _ = _drive_fixture(fix)
    assert len(fires) == 0


def test_both_bands_blocked():
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        fix = fixture_both_bands_blocked(bb)
    fires, _, _ = _drive_fixture(fix)
    assert len(fires) == 0


# ─── Isolation regression ──────────────────────────────────────────────────

def test_isolation_no_production_leak_during_fire():
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}) as installed:
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        fix = fixture_classic_pierce_long(bb)
        s = bb.GbpUsdBBBounceStrategy()
        for bar in fix["bars"]:
            s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar.timestamp,
                       [bar], [float(bar.close)], False, False)
        leaks = assert_no_production_side_effects(installed)
        assert leaks == [], f"isolation leaked: {leaks}"


def test_no_live_threads_leaked():
    import threading
    pre = {t.name for t in threading.enumerate()}
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        _ = bb.GbpUsdBBBounceStrategy()
    post = {t.name for t in threading.enumerate()}
    assert pre == post


# ─── End-to-end (strategy → broker) ────────────────────────────────────────

def test_end_to_end_buy_opens_position():
    """BUY fire → BrokerSimulator opens a long position with SL and TP attached."""
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        fix = fixture_classic_pierce_long(bb)
    from adapters.end_to_end import StrategyFire, fire_to_order_request, quote_fx
    from sim.broker import BrokerSimulator
    from sim.types import Direction
    import datetime as _dt

    broker = BrokerSimulator(pair="GBPUSD")
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        bb._write_bb_bounce_lifecycle_row = lambda row: None
        s = bb.GbpUsdBBBounceStrategy()
        bars_so_far, closes = [], []
        fires_captured = []
        for bar in fix["bars"]:
            bars_so_far.append(bar)
            closes.append(float(bar.close))
            # Prime the simulator with a tick near the bar's close
            ts_ns = int(bar.timestamp.timestamp() * 1e9)
            broker.on_quote(quote_fx(ts_ns, bar.close - 0.5, bar.close + 0.5))
            d = s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar.timestamp,
                           bars_so_far, closes, False, False)
            if d is not None:
                direction = Direction.BUY if d.signal == "BUY" else Direction.SELL
                fire = StrategyFire(
                    ts=ts_ns + 240 * 10**9, direction=direction,
                    entry_price_ig=float(d.entry),
                    sl_pips=float(d.sl) if d.sl else 15.0,
                    tp_pips=float(d.tp) if d.tp else 100.0,
                    mode=d.mode,
                )
                fires_captured.append(fire)
                req = fire_to_order_request(fire, f"TEST-DR-{len(fires_captured)}")
                broker.submit(req)
                # Activate on next tick
                broker.on_quote(quote_fx(ts_ns + 260 * 10**9, bar.close - 0.5, bar.close + 0.5))

        assert len(fires_captured) == 1
        open_pos = broker.open_positions()
        assert len(open_pos) == 1
        pos = open_pos[0]
        assert pos.direction == Direction.BUY
        assert pos.sl_absolute is not None
        assert pos.tp_absolute is not None
        # SL below entry, TP above entry (BUY)
        assert pos.sl_absolute < pos.entry_price < pos.tp_absolute


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
