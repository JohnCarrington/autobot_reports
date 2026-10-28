"""Full pipeline — runs level detection + event detection + response
classification + confirmation detection + SL×TP execution grid for a
specified year.

Writes six CSVs under data/:
  STRUCTURAL_LEVEL_EVENTS.csv         (per event)
  STRUCTURAL_RESPONSE_CLASSIFICATION.csv  (per event: Type 1-4 + metrics)
  CONFIRMATION_RESULTS.csv            (per event × confirmation)
  ENTRY_FEASIBILITY.csv               (per level_family × event × SL × TP × spread)
  YEAR_BY_YEAR_VALIDATION.csv         (summary roll-up)
  FEATURE_COMPARISON.csv              (per level_type × response_type)

Usage:
    python pipeline.py <YEAR>
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, load_range
from levels import all_levels, Level
from events import (
    detect_events, classify_response, Event, ResponseLabel,
    LEVEL_FAMILIES, RESPONSE_HORIZON_BARS,
)
from confirmations import CONFIRMERS, measure_reach


DATA_DIR = HERE.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SL_PIPS = (4, 6, 8, 12)
TP_PIPS = (15, 30, 50)
SPREAD_PIPS = (0, 1, 2)


def _simulate_sl_tp(bars, ci: int, entry: float, side: str,
                    sl: float, tp: float, spread: float) -> str:
    """Return 'TP', 'SL', 'AMB', or 'OUT' within RESPONSE_HORIZON_BARS."""
    end = min(ci + RESPONSE_HORIZON_BARS, len(bars) - 1)
    for i in range(ci + 1, end + 1):
        b = bars[i]
        if side == "UPPER":  # short the reversal (price moving down)
            tp_hit = b.low <= entry - tp - spread
            sl_hit = b.high >= entry + sl + spread
        else:
            tp_hit = b.high >= entry + tp + spread
            sl_hit = b.low <= entry - sl - spread
        if tp_hit and sl_hit:
            return "AMB"
        if tp_hit:
            return "TP"
        if sl_hit:
            return "SL"
    return "OUT"


def run_year(year: int) -> dict:
    print(f"\n=== Running pipeline for {year} ===")
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)
    bars = load_range(start, end)
    print(f"Loaded {len(bars)} M5 bars.")
    levels = all_levels(bars)
    print(f"Computed {len(levels)} levels.")
    events = detect_events(bars, levels)
    print(f"Detected {len(events)} events.")
    responses = [classify_response(bars, e) for e in events]

    # Write STRUCTURAL_LEVEL_EVENTS.csv
    events_rows = []
    for e in events:
        events_rows.append({
            "year": year,
            "event_id": e.event_id,
            "date": e.date,
            "event_ts_utc": e.event_ts_utc,
            "level_type": e.level_type,
            "level_family": e.level_family,
            "level_price": e.level_price,
            "approach_side": e.approach_side,
            "distance_into_level_pts": e.distance_into_level_pts,
            "distance_to_level_pts": e.distance_to_level_pts,
            "approach_speed_pts_per_5m": e.approach_speed_pts_per_5m,
            "atr14_pts": e.atr14_pts,
            "prior_tests_count": e.prior_tests_count,
            "level_age_bars": e.level_age_bars,
            "session": e.session,
            "overlap_tags": "|".join(e.overlap_tags),
        })

    # Write STRUCTURAL_RESPONSE_CLASSIFICATION.csv
    resp_rows = []
    for e, r in zip(events, responses):
        resp_rows.append({
            "year": year,
            "event_id": e.event_id,
            "event_ts_utc": e.event_ts_utc,
            "level_type": e.level_type,
            "level_family": e.level_family,
            "approach_side": e.approach_side,
            "type_label": r.type_label,
            "repeated_test_flag": r.repeated_test_flag,
            "max_pen_pts": r.max_pen_pts,
            "min_drift_pts": r.min_drift_pts,
            "acceptance_closes": r.acceptance_closes,
            "reclaim_bar_offset": r.reclaim_bar_offset,
            "net_pts_at_horizon": r.net_pts_at_h,
            "prior_tests_count": e.prior_tests_count,
            "session": e.session,
        })

    # Confirmation events per event
    conf_rows = []
    exec_counter = Counter()  # (level_family, cf_name, sl, tp, spread) → {TP, SL, AMB, OUT, N}
    for e, r in zip(events, responses):
        for cf_name, fn in CONFIRMERS:
            ci, cclose, dist, bars_from = fn(bars, e)
            produced = ci is not None
            row = {
                "year": year,
                "event_id": e.event_id,
                "level_type": e.level_type,
                "level_family": e.level_family,
                "approach_side": e.approach_side,
                "cf_event": cf_name,
                "produced": produced,
                "bars_from_event": bars_from,
                "confirm_close": cclose,
                "distance_from_level_pts": dist,
                "response_type": r.type_label,
            }
            if produced:
                reach = measure_reach(bars, ci, cclose, e.approach_side, e.level_price)
                row.update(reach)
                # Execution grid: this event × this confirmation × SL×TP×spread
                for sl in SL_PIPS:
                    for tp in TP_PIPS:
                        for sp in SPREAD_PIPS:
                            outcome = _simulate_sl_tp(bars, ci, cclose, e.approach_side,
                                                     sl, tp, sp)
                            key = (e.level_family, cf_name, sl, tp, sp)
                            exec_counter[(key, outcome)] += 1
                            exec_counter[(key, "N")] += 1
            else:
                for k in ("mfe_pts", "mae_pts", "reached_15", "reached_30",
                          "reached_50", "stopped_by_level",
                          "bars_to_15", "bars_to_30", "bars_to_50"):
                    row[k] = None
            conf_rows.append(row)

    # ENTRY_FEASIBILITY.csv — aggregate SL × TP × spread × family × cf
    exec_rows = []
    all_keys = {key for (key, outcome) in exec_counter.keys() if outcome != "N"}
    for key in sorted(all_keys):
        family, cf_name, sl, tp, sp = key
        n = exec_counter[(key, "N")]
        n_tp = exec_counter[(key, "TP")]
        n_sl = exec_counter[(key, "SL")]
        n_amb = exec_counter[(key, "AMB")]
        n_out = exec_counter[(key, "OUT")]
        decisive = n_tp + n_sl
        hit = (n_tp / decisive) if decisive else None
        # Expectancy (decisive only)
        exp_dec = ((n_tp * tp - n_sl * sl) / decisive) if decisive else None
        exp_amb = ((n_tp * tp - (n_sl + n_amb) * sl) /
                   (n_tp + n_sl + n_amb)) if (n_tp + n_sl + n_amb) else None
        exec_rows.append({
            "year": year, "level_family": family, "cf_event": cf_name,
            "sl_pts": sl, "tp_pts": tp, "spread_pts": sp,
            "n_fired": n, "n_tp": n_tp, "n_sl": n_sl, "n_amb": n_amb, "n_out": n_out,
            "hit_rate_decisive": round(hit, 4) if hit is not None else "",
            "expectancy_pts_decisive": round(exp_dec, 2) if exp_dec is not None else "",
            "expectancy_pts_amb_as_sl": round(exp_amb, 2) if exp_amb is not None else "",
        })

    # Dumps
    def _dump(rows, name):
        if not rows:
            return
        p = DATA_DIR / name
        existed = p.exists()
        mode = "a" if existed else "w"
        with p.open(mode, newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            if not existed:
                w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"  → {name}: {len(rows)} rows (appended={existed})")

    _dump(events_rows, "STRUCTURAL_LEVEL_EVENTS.csv")
    _dump(resp_rows, "STRUCTURAL_RESPONSE_CLASSIFICATION.csv")
    _dump(conf_rows, "CONFIRMATION_RESULTS.csv")
    _dump(exec_rows, "ENTRY_FEASIBILITY.csv")

    # Summary roll-up
    summary = {
        "year": year,
        "n_bars": len(bars),
        "n_levels": len(levels),
        "n_events": len(events),
        "response_distribution": dict(Counter(r.type_label for r in responses)),
        "repeated_test_share_pct": round(
            100.0 * sum(1 for r in responses if r.repeated_test_flag) / max(1, len(responses)),
            1),
        "events_by_family": dict(Counter(e.level_family for e in events)),
        "events_by_session": dict(Counter(e.session for e in events)),
    }
    return summary


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    s = run_year(year)
    print(json.dumps(s, indent=2))
