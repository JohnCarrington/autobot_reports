"""2026-10-28 case study — Events A (07:15 UTC) and B (11:00 UTC).

Reconstruct the structural levels observable at those two timestamps
using the preregistered pipeline, and determine whether the pipeline
would have flagged either event.

Note: 2026 candles come from the MID archive (`data/candles/GBPUSD/`)
NOT the BID archive — this is the only data available in 2026.  MID
differs from BID by half the GBP/USD spread (~0.5 p).  Flagged in the
case-study report; results use MID.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, load_range
from levels import all_levels, Level
from events import (
    detect_events, classify_response,
    TOUCH_TOL_PIPS, LEVEL_FAMILIES, LEVEL_SIDE,
)
from confirmations import CONFIRMERS, measure_reach


OCT28 = datetime(2026, 10, 28, tzinfo=timezone.utc)


def main():
    # 7 days of history + today for level computation
    start = OCT28 - timedelta(days=7)
    end = OCT28 + timedelta(hours=23, minutes=59)
    bars = load_range(start, end)
    print(f"Loaded {len(bars)} MID M5 bars from {start.date()} to {end.date()}")

    levels = all_levels(bars)
    print(f"Computed {len(levels)} levels.")

    # Candidate event times
    anchor_a = datetime(2026, 10, 28, 7, 15, tzinfo=timezone.utc)
    anchor_b = datetime(2026, 10, 28, 11, 0, tzinfo=timezone.utc)

    # List all levels within ±25 pts of 13273 observable before anchor_a
    print("\n=== Observable levels near 13273 as of Event A (07:15 UTC) ===")
    nearby_a = sorted(
        [L for L in levels
         if L.established_at <= anchor_a
         and abs(L.price - 13273) <= 25
         and L.level_type != "ROUND_00" or True],  # include all
        key=lambda L: L.price,
    )
    for L in nearby_a:
        print(f"  {L.level_type:15} {L.price:10.2f}  established {L.established_at}  "
              f"family={LEVEL_FAMILIES[L.level_type]}  meta={L.meta}")

    print(f"\n=== Observable levels near 13273 as of Event B (11:00 UTC) ===")
    nearby_b = sorted(
        [L for L in levels
         if L.established_at <= anchor_b
         and abs(L.price - 13273) <= 25],
        key=lambda L: L.price,
    )
    for L in nearby_b:
        print(f"  {L.level_type:15} {L.price:10.2f}  established {L.established_at}  "
              f"family={LEVEL_FAMILIES[L.level_type]}  meta={L.meta}")

    # Full event detection + classification, filter to Oct 28 only
    events = detect_events(bars, levels)
    oct28_events = [e for e in events if e.date == "2026-10-28"]
    print(f"\n=== Pipeline-detected events on 2026-10-28 ===")
    print(f"total events = {len(oct28_events)}")
    for e in oct28_events:
        r = classify_response(bars, e)
        print(f"  {e.event_ts_utc}  {e.level_type:14} @ {e.level_price:9.2f}  "
              f"side={e.approach_side:5}  dist={e.distance_to_level_pts:5.2f}  "
              f"pen={e.distance_into_level_pts:5.2f}  "
              f"response={r.type_label}  repeated_test={r.repeated_test_flag}")

    # Also build a bar-by-bar reconstruction around Event A and B
    print(f"\n=== M5 bar-by-bar around Event A (07:00–08:00 UTC) ===")
    for b in bars:
        if datetime(2026, 10, 28, 7, 0, tzinfo=timezone.utc) <= b.ts <= datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc):
            print(f"  {b.ts.strftime('%H:%M')}  O={b.open:9.2f}  H={b.high:9.2f}  "
                  f"L={b.low:9.2f}  C={b.close:9.2f}")

    print(f"\n=== M5 bar-by-bar around Event B (10:30–11:30 UTC) ===")
    for b in bars:
        if datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc) <= b.ts <= datetime(2026, 10, 28, 11, 30, tzinfo=timezone.utc):
            print(f"  {b.ts.strftime('%H:%M')}  O={b.open:9.2f}  H={b.high:9.2f}  "
                  f"L={b.low:9.2f}  C={b.close:9.2f}")

    # Dump JSON summary
    summary = {
        "events_on_oct28": len(oct28_events),
        "levels_near_1_3273_at_eventA": [
            {"type": L.level_type, "price": L.price,
             "established_at": L.established_at.isoformat()}
            for L in nearby_a if abs(L.price - 13273) <= 15
        ],
        "levels_near_1_3273_at_eventB": [
            {"type": L.level_type, "price": L.price,
             "established_at": L.established_at.isoformat()}
            for L in nearby_b if abs(L.price - 13273) <= 15
        ],
        "pipeline_events_oct28": [
            {"ts": e.event_ts_utc, "level": e.level_type, "price": e.level_price,
             "side": e.approach_side, "distance": e.distance_to_level_pts,
             "penetration": e.distance_into_level_pts}
            for e in oct28_events
        ],
    }
    out = Path(__file__).parent.parent / "data" / "OCT28_CASE_STUDY_SUMMARY.json"
    with out.open("w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\n✓ Wrote {out}")


if __name__ == "__main__":
    main()
