"""Phase 3b spec §13 scenarios C-J (synthetic, deterministic).

These exercise the simulator and strategy-adapter together. They are
SYNTHETIC MARKET SCENARIOS for functional testing — not historical
profitability evidence (per Phase 3b spec §13).

Scenarios covered here:
  E — Stop-loss trigger
  G — Spread expansion
  I — Gap through stop
  J — Session boundary (strategy declines outside window)

Scenarios C (NMS rejection), D (news rejection), F (dynamic trade mgmt),
H (conflicting positions) are NOT_EVALUATED at Phase 3b because their
production dependencies (NMS state, live news feed, trade_manager tier
state machine, open-position ledger) exceed the isolation seam's scope.
See Phase 3b §Q and the quality-gate report.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))  # for sim/

from adapters.isolation import init_isolation  # noqa: E402
from adapters.end_to_end import StrategyFire, fire_to_order_request, quote_fx  # noqa: E402
from fixtures.bb_fire_fixtures import fixture_classic_pierce_long  # noqa: E402

from sim.broker import BrokerSimulator  # noqa: E402
from sim.types import Direction, FillClassification  # noqa: E402


def _ns(dt):
    return int(dt.timestamp() * 1e9)


def _drive_fire(fixture_builder, broker, extra_env=None):
    """Drive production BB Bounce over a fixture; return (fire, bars)."""
    extra = {"GBPUSD_BB_BOUNCE_ENABLED": "1"}
    if extra_env: extra.update(extra_env)
    with init_isolation(extra_env=extra):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        bb._write_bb_bounce_lifecycle_row = lambda row: None
        fix = fixture_builder(bb)
        s = bb.GbpUsdBBBounceStrategy()
        bars_so_far, closes = [], []
        for bar in fix["bars"]:
            bars_so_far.append(bar)
            closes.append(float(bar.close))
            # feed a mid-tick to the broker so last_quote is populated
            broker.on_quote(quote_fx(_ns(bar.timestamp), bar.close - 0.5, bar.close + 0.5))
            d = s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar.timestamp,
                           bars_so_far, closes, False, False)
            if d is not None:
                return d, bars_so_far
    return None, []


# ─── Scenario E — Stop-loss trigger ──────────────────────────────────────

def test_scenario_E_stop_loss_trigger():
    """BUY fire → price falls through SL → position closes with reason=STOP."""
    broker = BrokerSimulator(pair="GBPUSD")
    fire_dec, bars = _drive_fire(fixture_classic_pierce_long, broker)
    assert fire_dec is not None, "fixture must produce a fire"
    # Submit the order
    direction = Direction.BUY if fire_dec.signal == "BUY" else Direction.SELL
    last_bar = bars[-1]
    ts_ns = _ns(last_bar.timestamp) + 240 * 10**9
    fire = StrategyFire(
        ts=ts_ns, direction=direction,
        entry_price_ig=float(fire_dec.entry),
        sl_pips=float(fire_dec.sl) if fire_dec.sl else 15.0,
        tp_pips=float(fire_dec.tp) if fire_dec.tp else 100.0,
        mode=fire_dec.mode,
    )
    req = fire_to_order_request(fire, "SCENE-E-DR")
    broker.submit(req)
    # Activate
    broker.on_quote(quote_fx(ts_ns + 60 * 10**9, last_bar.close - 0.5, last_bar.close + 0.5))
    assert len(broker.open_positions()) == 1
    pos = broker.open_positions()[0]
    # Walk prices DOWN through SL (prices in IG points → FX decimal)
    sl_fx = pos.sl_absolute
    # Push bid below SL
    broker.on_quote(quote_fx(ts_ns + 120 * 10**9,
                              (sl_fx - 0.0001) * 10000,  # bid as IG points
                              (sl_fx + 0.0001) * 10000))
    assert len(broker.closed_positions()) == 1
    closed = broker.closed_positions()[0]
    assert closed.exit_reason == "STOP"


# ─── Scenario G — Spread expansion ────────────────────────────────────────

def test_scenario_G_spread_expansion_at_entry():
    """A sudden spread expansion widens entry cost but still fills."""
    from sim.broker import BrokerSimulator
    broker = BrokerSimulator(pair="GBPUSD")
    # Normal quote
    broker.on_quote(quote_fx(1_000_000_000_000, 13650.0, 13651.0))
    # Submit market BUY
    req_ts = 1_000_000_000_000 + 1_000_000  # 1ms later
    direction = Direction.BUY
    from sim.types import OrderRequest
    req = OrderRequest(deal_ref="SCENE-G", direction=direction, size=1.0,
                       order_type="MARKET", submitted_ts_ns=req_ts,
                       sl_distance_pips=15.0, tp_distance_pips=20.0)
    broker.submit(req)
    # Spread expands dramatically at activation tick
    broker.on_quote(quote_fx(req_ts + 1_000_000, 13650.0, 13660.0))  # 10p spread
    open_pos = broker.open_positions()
    assert len(open_pos) == 1
    # Entry at ask = 1.3660 (not the pre-expansion 1.3651)
    assert abs(open_pos[0].entry_price - 1.3660) < 1e-9


# ─── Scenario I — Gap through stop ────────────────────────────────────────

def test_scenario_I_gap_through_stop_filled_at_tick_price():
    """When the next tick is far past the SL, the simulated fill is the gapped tick, not the SL."""
    broker = BrokerSimulator(pair="GBPUSD")
    # Open a BUY with SL 15p below entry
    broker.on_quote(quote_fx(1_000_000_000_000, 13650.0, 13651.0))
    from sim.types import OrderRequest
    req = OrderRequest(deal_ref="SCENE-I", direction=Direction.BUY, size=1.0,
                       order_type="MARKET", submitted_ts_ns=1_000_000_000_000 + 1,
                       sl_distance_pips=15.0, tp_distance_pips=50.0)
    broker.submit(req)
    broker.on_quote(quote_fx(1_000_000_000_000 + 1_000_000, 13650.0, 13651.0))
    pos = broker.open_positions()[0]
    assert pos.sl_absolute is not None
    # Gap: next tick bid is 10 pips BELOW SL (classic gap-through-stop)
    gap_bid_ig = pos.sl_absolute * 10000 - 10
    broker.on_quote(quote_fx(1_000_000_000_000 + 2_000_000, gap_bid_ig, gap_bid_ig + 1))
    assert len(broker.closed_positions()) == 1
    closed = broker.closed_positions()[0]
    assert closed.exit_reason == "STOP"
    # Per Phase 2 simulator: gap-through-stop (bid < SL - 1 pip) → fill at bid, not SL
    assert closed.exit_classification == FillClassification.SIMULATED_FILL
    # Exit price is the gapped bid (FX decimal) = ~pos.sl_absolute - 0.0010
    assert closed.exit_price < pos.sl_absolute - 0.0005


# ─── Scenario J — Session boundary blocks fire ────────────────────────────

def test_scenario_J_session_boundary_no_fire():
    """Setup at 03:00 UTC is outside the 06:00-17:00 BB Bounce window — must not fire."""
    from datetime import datetime, timezone
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        from fixtures.bb_fire_fixtures import fixture_outside_window_blocked
        fix = fixture_outside_window_blocked(bb)
        s = bb.GbpUsdBBBounceStrategy()
        bars_so_far, closes = [], []
        fires = []
        for bar in fix["bars"]:
            bars_so_far.append(bar)
            closes.append(float(bar.close))
            d = s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar.timestamp,
                           bars_so_far, closes, False, False)
            if d is not None:
                fires.append(d)
        assert len(fires) == 0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
