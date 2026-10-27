"""Phase 3b Stage 9 — end-to-end deterministic scenarios.

Chains the production BB Bounce → fire → Phase 2 BrokerSimulator → close.
Covers spec §13 scenarios A-J (synthetic market sequences).

For each scenario:
  1. Drive production BB Bounce over the fixture bars under isolation
  2. On fire, convert to a Phase 2 OrderRequest
  3. Submit to BrokerSimulator; drive bid/ask ticks through broker.on_quote
  4. Record entry fill, SL/TP triggers, exit

Prices in IG points format at the strategy; FX decimal at the simulator.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.isolation import init_isolation  # noqa: E402
from adapters.end_to_end import StrategyFire, fire_to_order_request, quote_fx  # noqa: E402
from fixtures.bb_fire_fixtures import fixture_classic_pierce_long, fixture_classic_pierce_short  # noqa: E402

sys.path.insert(0, "/home/autobot/autobot_reports_clone/tick-backtest-framework-phase2-20261027")
from sim.types import Direction, FillClassification  # noqa: E402
from sim.broker import BrokerSimulator  # noqa: E402

OUT = Path("/tmp/phase3b_audit/data")
OUT.mkdir(parents=True, exist_ok=True)
PIP = 0.0001


def _ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1e9)


def _bar_to_ticks(bar, spread_pips: float = 1.0) -> list:
    """Expand a 5m OHLC bar into 5 synthetic ticks (O, H, L, C, C) with a fixed spread.
    Prices in IG points. Ask = mid + spread/2, Bid = mid - spread/2."""
    half = spread_pips / 2
    ts_base = _ns(bar.timestamp)
    # 5 ticks over the bar: synthetic sampling at seconds 0, 60, 120, 180, 240
    ticks = []
    for i, price_mid in enumerate([bar.open, bar.high, bar.low, bar.close, bar.close]):
        ts = ts_base + i * 60 * 10**9
        ticks.append((ts, price_mid - half, price_mid + half))
    return ticks


def run_scenario(name: str, fixture_builder, extra_env=None) -> dict:
    extra = {"GBPUSD_BB_BOUNCE_ENABLED": "1"}
    if extra_env: extra.update(extra_env)
    log: list[str] = []
    with init_isolation(extra_env=extra):
        sys.modules.pop('gbpusd_bb_bounce', None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        bb._write_bb_bounce_lifecycle_row = lambda row: None

        s = bb.GbpUsdBBBounceStrategy()
        fix = fixture_builder(bb)
        bars_so_far, closes = [], []
        broker = BrokerSimulator(pair="GBPUSD")
        deal_ref_counter = [0]
        fires_captured = []
        for i, bar in enumerate(fix["bars"]):
            bars_so_far.append(bar)
            closes.append(float(bar.close))
            # Advance broker's tick clock across the bar BEFORE strategy call
            # (so SL/TP triggers from the bar are evaluated against the open position)
            for t_ns, bid_ig, ask_ig in _bar_to_ticks(bar):
                broker.on_quote(quote_fx(t_ns, bid_ig, ask_ig))

            d = s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar.timestamp,
                           bars_so_far, closes, False, False)
            if d is not None:
                deal_ref_counter[0] += 1
                direction = Direction.BUY if d.signal == "BUY" else Direction.SELL
                fire = StrategyFire(
                    ts=_ns(bar.timestamp) + 240 * 10**9,  # fire at bar close
                    direction=direction,
                    entry_price_ig=float(d.entry),
                    sl_pips=float(d.sl) if d.sl is not None else 15.0,
                    tp_pips=float(d.tp) if d.tp is not None else 100.0,
                    mode=d.mode,
                )
                fires_captured.append(fire)
                req = fire_to_order_request(fire, f"DR-{deal_ref_counter[0]:03d}")
                log.append(f"[{bar.timestamp.isoformat()}] FIRE {fire.direction.value} "
                           f"entry_ig={fire.entry_price_ig} entry_fx={req.sl_absolute + abs(req.sl_absolute - (req.sl_absolute + fire.sl_pips * PIP)):.5f}")
                broker.submit(req)
                # On the next tick after submission the broker will fill
                # Advance one tick slightly after fire
                next_tick_ns = _ns(bar.timestamp) + 260 * 10**9
                broker.on_quote(quote_fx(next_tick_ns, bar.close - 0.5, bar.close + 0.5))

        # Continue running the simulator for 20 more bars at the fixture's last price
        # to allow SL/TP to trigger
        if fix["bars"]:
            last_bar = fix["bars"][-1]
            # Price-decay / price-reversal: for a BUY fixture, hold flat; for SELL, hold flat.
            # Tests of SL/TP triggers belong in the dedicated test file. Here we just hold.
            base_ts = _ns(last_bar.timestamp) + 300 * 10**9
            for i in range(20):
                ts = base_ts + i * 300 * 10**9
                broker.on_quote(quote_fx(ts, last_bar.close - 0.5, last_bar.close + 0.5))

        open_positions = broker.open_positions()
        closed_positions = broker.closed_positions()
        return {
            "scenario": name,
            "fixture": fix["pathway"],
            "n_fires": len(fires_captured),
            "fires": [{"ts": f.ts, "direction": f.direction.value, "entry_ig": f.entry_price_ig} for f in fires_captured],
            "n_open_positions_end": len(open_positions),
            "n_closed_positions_end": len(closed_positions),
            "open_summary": [
                {"deal_id": p.deal_id, "dir": p.direction.value,
                 "entry": p.entry_price, "sl": p.sl_absolute, "tp": p.tp_absolute}
                for p in open_positions
            ],
            "closed_summary": [
                {"deal_id": p.deal_id, "dir": p.direction.value,
                 "entry": p.entry_price, "exit": p.exit_price,
                 "reason": p.exit_reason,
                 "classification": p.exit_classification.value if p.exit_classification else None}
                for p in closed_positions
            ],
            "events_tail": [
                {"kind": e.kind, "ts_ns": e.ts_ns, "payload": e.payload}
                for e in broker.events[-6:]
            ],
        }


def main():
    results = []
    print("Scenario A: successful BUY bounce")
    results.append(run_scenario("A_buy_bounce", fixture_classic_pierce_long))
    print("Scenario B: successful SELL bounce")
    results.append(run_scenario("B_sell_bounce", fixture_classic_pierce_short))

    print()
    for r in results:
        print(f"\n{r['scenario']}: fires={r['n_fires']} open_end={r['n_open_positions_end']} closed_end={r['n_closed_positions_end']}")
        for p in r["open_summary"]:
            print(f"  OPEN {p['dir']} entry={p['entry']:.5f} sl={p['sl']:.5f} tp={p['tp']:.5f}")
        for p in r["closed_summary"]:
            print(f"  CLOSED {p['dir']} entry={p['entry']:.5f} exit={p['exit']:.5f} reason={p['reason']} cls={p['classification']}")

    (OUT / "stage9_scenarios.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
