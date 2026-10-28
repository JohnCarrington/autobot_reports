"""Characterise the first +1, +2, +3 M5 bars after each reversal candidate.

For every episode in FULL_POPULATION_RESULTS, pull the next 3 M5 bars
and record:

* ``disp_from_extreme_pts_k`` — distance of bar close from the reversal
  extreme on the correct side.  BULL: close − bar[event].low.  BEAR:
  bar[event].high − close.  Positive = moved away in the reversal direction.
* ``extend_past_extreme_pts_k`` — how far the bar still pushed PAST the
  extreme (penetration deeper into the original run).  BULL: max(0,
  bar[event].low − bar[event+k].low).  BEAR: max(0, bar[event+k].high −
  bar[event].high).  Zero = extreme respected.
* ``body_sign_k`` — +1 for countertrend body (BULL=green, BEAR=red), −1
  for pro-trend body, 0 for doji.
* ``mfe_pts_k`` / ``mae_pts_k`` — running MFE/MAE through +k bars,
  measured from event-bar close in the reversal direction.

Then aggregate medians (and quartiles) grouped by (year, kind,
outcome_label) and (kind, outcome_label).  Writes
``EARLY_DEVELOPMENT_RESULTS.csv`` and prints a formatted summary.
"""
from __future__ import annotations

import csv
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, read_bid_m5


def _bar_metrics(event: Bar, bar: Bar, kind: str,
                 mfe_so_far: float, mae_so_far: float
                 ) -> tuple[float, float, int, float, float]:
    if kind == "BULL":
        disp = bar.close - event.low
        extend_past = max(0.0, event.low - bar.low)
        body_sign = 1 if bar.is_green else (-1 if bar.is_red else 0)
        mfe = max(mfe_so_far, bar.high - event.close)
        mae = max(mae_so_far, event.close - bar.low)
    else:
        disp = event.high - bar.close
        extend_past = max(0.0, bar.high - event.high)
        body_sign = 1 if bar.is_red else (-1 if bar.is_green else 0)
        mfe = max(mfe_so_far, event.close - bar.low)
        mae = max(mae_so_far, bar.high - event.close)
    return disp, extend_past, body_sign, mfe, mae


def _summarise(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p25": None, "p50": None, "p75": None, "mean": None}
    vs = sorted(values)
    return {
        "n": len(vs),
        "p25": round(statistics.quantiles(vs, n=4)[0], 2) if len(vs) >= 4 else round(vs[0], 2),
        "p50": round(statistics.median(vs), 2),
        "p75": round(statistics.quantiles(vs, n=4)[2], 2) if len(vs) >= 4 else round(vs[-1], 2),
        "mean": round(statistics.mean(vs), 2),
    }


def main() -> int:
    in_csv = HERE.parent / "data" / "FULL_POPULATION_RESULTS.csv"
    rows = list(csv.DictReader(in_csv.open()))

    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)

    out_rows: list[dict] = []
    for date_str in sorted(by_date):
        date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        try:
            bars = read_bid_m5(date)
        except FileNotFoundError:
            continue
        ts_to_idx = {b.ts.isoformat(): i for i, b in enumerate(bars)}
        for r in by_date[date_str]:
            idx = ts_to_idx.get(r["event_ts_utc"])
            if idx is None:
                continue
            event = bars[idx]
            k_cols: dict[str, float | int | None] = {}
            mfe = mae = 0.0
            for k in (1, 2, 3):
                if idx + k >= len(bars):
                    for key in ("disp_from_extreme_pts",
                                "extend_past_extreme_pts",
                                "body_sign", "mfe_pts", "mae_pts"):
                        k_cols[f"{key}_{k}"] = None
                    continue
                disp, extend_past, body_sign, mfe, mae = _bar_metrics(
                    event, bars[idx + k], r["kind"], mfe, mae
                )
                k_cols[f"disp_from_extreme_pts_{k}"] = round(disp, 2)
                k_cols[f"extend_past_extreme_pts_{k}"] = round(extend_past, 2)
                k_cols[f"body_sign_{k}"] = body_sign
                k_cols[f"mfe_pts_{k}"] = round(mfe, 2)
                k_cols[f"mae_pts_{k}"] = round(mae, 2)
            out_rows.append({
                "year": r["year"],
                "date": r["date"],
                "event_ts_utc": r["event_ts_utc"],
                "kind": r["kind"],
                "outcome_label": r["outcome_label"],
                **k_cols,
            })

    out_path = HERE.parent / "data" / "EARLY_DEVELOPMENT_RESULTS.csv"
    fieldnames = list(out_rows[0].keys())
    with out_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"✓ wrote {out_path} ({len(out_rows)} rows)")

    # Aggregate by (kind, outcome_label) across both years and by year
    print("\n============================================================")
    print("EARLY DEVELOPMENT — medians of per-episode +1/+2/+3 metrics")
    print("============================================================")

    def _grouped(predicate, label):
        print(f"\n--- {label} (n={sum(1 for r in out_rows if predicate(r))}) ---")
        for metric in ("disp_from_extreme_pts", "extend_past_extreme_pts", "mfe_pts", "mae_pts"):
            parts = []
            for k in (1, 2, 3):
                vals = [float(r[f"{metric}_{k}"]) for r in out_rows
                        if predicate(r) and r[f"{metric}_{k}"] not in (None, "", "None")]
                summary = _summarise(vals)
                parts.append(f"+{k}: p50={summary['p50']}")
            print(f"  {metric:28}  " + "   ".join(parts))
        # body sign — share with body on reversal side (sign=+1)
        for k in (1, 2, 3):
            vals = [r[f"body_sign_{k}"] for r in out_rows
                    if predicate(r) and r[f"body_sign_{k}"] not in (None, "", "None")]
            total = len(vals)
            counter = sum(1 for v in vals if int(v) == 1)
            pct = round(100.0 * counter / total, 1) if total else 0.0
            print(f"  body_sign=+1 (countertrend)  +{k}: {pct}% ({counter}/{total})")

    def is_(year, kind, out_prefix):
        return lambda r: r["year"] == year and r["kind"] == kind and r["outcome_label"].startswith(out_prefix)

    for year in ("2024", "2025"):
        for kind in ("BULL", "BEAR"):
            for out_prefix in ("SUCCESS", "FAIL", "AMBIGUOUS"):
                _grouped(is_(year, kind, out_prefix), f"{year} {kind} {out_prefix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
