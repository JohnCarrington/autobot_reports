"""Historical replay of P3 against the 2026-10-28 FOMC incident.

Simulates the AI's rev 4 scenario (14:05 UTC, VALID under P1+P2 fix)
with a machine-readable trigger_spec, then walks every subsequent M5
candle through the deterministic evaluator and measures when the
trigger would have published.

Compares to the production baseline:
  trigger (close ≥ 13296) met at 14:50 UTC bar close (14:55 UTC)
  production publishable rev @ 15:15 UTC (shadow_proposals)
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
EVALUATOR = HERE.parent / "trigger_evaluator"
sys.path.insert(0, str(EVALUATOR))
sys.path.insert(0, str(AGENT))

from trigger_evaluator import TriggerEvalState, run_trigger_sweep  # noqa

UTC = dt.timezone.utc
CANDLES = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD/"
                        "2026-10-28.csv")


def _load_m5(path: pathlib.Path):
    out = {}
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out[row["timestamp"][:16]] = (
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]))
    return out


def main():
    bars = _load_m5(CANDLES)
    print(f"Loaded {len(bars)} M5 bars on 2026-10-28")

    # Simulated rev 4 scenario — the one the AI emitted at 14:05 UTC.
    # Under P2 + corrected prompt, trigger_spec is machine-readable:
    sid = "f5e11547c4ce2097"
    scenario_row = {
        "scenario_id": sid,
        "revision_idx": 4,
        "state": "DEVELOPING",
        "bar_ts_utc": "2026-10-28T13:50:00+00:00",
        "generated_at_utc": "2026-10-28T14:02:17+00:00",
        "publication_decision": {"decision": "VALID", "flag_codes": [],
                                   "reason": ""},
        "opportunities": [{
            "kind": "INITIAL_DIRECTIONAL",
            "direction": "BUY",
            "category": "A",
            "required_price_behaviour":
                "GBP close above 13296 (session high, BB_U cluster)",
            "trade_proposal": {
                "entry_price": 13296.0,
                "stop_price": 13289.87,
                "target_price": 13348.55,
            },
            "trigger_spec": {
                "type": "price_break_above",
                "level_price": 13296.0,
                "require_confirmed_close": True,
                "entry_tolerance_pts": 8.0,
                "max_bars_from_proposal": 60,
                "valid_until_utc": "2026-10-28T19:00:00+00:00",
            },
            "note": "Fed decision SCHEDULED at 18:00Z — background risk",
        }],
    }
    td = pathlib.Path(tempfile.mkdtemp(prefix="p3-replay-"))
    scen = td / "scenarios.jsonl"
    scen.write_text(json.dumps(scenario_row) + "\n")
    state = TriggerEvalState(td / "state.json")
    prop = td / "proposals.jsonl"

    # Walk every M5 bar from 14:05 (rev 4 generation) through 15:30 UTC
    # Simulate the per-bar evaluator being invoked ~15 s after each
    # M5 bar's close.
    start = dt.datetime(2026, 10, 28, 14, 5, tzinfo=UTC)
    end = dt.datetime(2026, 10, 28, 15, 30, tzinfo=UTC)
    cur = start
    fires = []
    print("\nPer-bar evaluation (14:05 → 15:30 UTC):")
    while cur <= end:
        bar_key = cur.strftime("%Y-%m-%dT%H:%M")
        bar = bars.get(bar_key)
        if bar is None:
            cur += dt.timedelta(minutes=5)
            continue
        # Imagine the evaluator fires at bar close + 15 s
        eval_ts = cur + dt.timedelta(seconds=300 + 15)
        snapshot = {"bar_ts_utc": cur.isoformat()}
        results = run_trigger_sweep(
            scenarios_path=scen, bar_ts_iso=cur.isoformat(),
            bar_ohlc=bar, snapshot=snapshot, economic_context={},
            state=state, now=eval_ts, proposals_out_path=prop)
        for r in results:
            if r.decision == "FIRE":
                fires.append((cur, eval_ts, r))
                print(f"  {bar_key}  bar_close={bar[3]}  "
                      f"FIRE at eval_ts={eval_ts.strftime('%H:%M:%S')}  "
                      f"reason={r.reason}")
            else:
                print(f"  {bar_key}  bar_close={bar[3]}  "
                      f"SKIP: {r.reason}")
        cur += dt.timedelta(minutes=5)

    print(f"\nTotal fires: {len(fires)}")
    if fires:
        first = fires[0]
        trigger_met_dt = dt.datetime(2026, 10, 28, 14, 55, tzinfo=UTC)
        actual = first[1]
        latency_s = (actual - trigger_met_dt).total_seconds()
        print(f"\nFirst fire: {actual.isoformat()}")
        print(f"Trigger-met time (bar close): {trigger_met_dt.isoformat()}")
        print(f"P3 publish latency: {latency_s:.0f} s ({latency_s/60:.1f} min)")
        # Dashboard shadow_proposals showed first publishable rev at 15:15 UTC
        prod_dt = dt.datetime(2026, 10, 28, 15, 15, 15, tzinfo=UTC)
        print(f"Production publishable (observed): {prod_dt.isoformat()}")
        prod_latency = (prod_dt - trigger_met_dt).total_seconds()
        print(f"Production publish latency: {prod_latency:.0f} s "
              f"({prod_latency/60:.1f} min)")
        print(f"P3 improvement: {prod_latency - latency_s:.0f} s "
              f"({(prod_latency - latency_s)/60:.1f} min faster)")


if __name__ == "__main__":
    main()
