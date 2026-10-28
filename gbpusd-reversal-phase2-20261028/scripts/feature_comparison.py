"""Compare point-in-time features across SUCCESS / FAIL / AMBIGUOUS,
split by BULL / BEAR and by year.  Also break down success rate by
session (LONDON_AM / LONDON_MIDDAY / NY_OVERLAP / NY_PM / OTHER) and
by volatility bucket (BB-width quintile).

Writes FEATURE_COMPARISON.csv and prints a formatted summary used by
the Phase 2 report.
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _as_float(v):
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _summ(xs: list[float]):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None, None, None
    xs_s = sorted(xs)
    return (round(statistics.quantiles(xs_s, n=4)[0], 2) if len(xs) >= 4 else round(xs_s[0], 2),
            round(statistics.median(xs_s), 2),
            round(statistics.quantiles(xs_s, n=4)[2], 2) if len(xs) >= 4 else round(xs_s[-1], 2),
            round(statistics.mean(xs_s), 2))


def _share(xs: list[bool | str]) -> float | None:
    xs = [x for x in xs if x not in (None, "", "None")]
    if not xs:
        return None
    truthy = sum(1 for x in xs if x in (True, "True", 1, "1"))
    return round(100.0 * truthy / len(xs), 1)


def main() -> int:
    in_csv = HERE.parent / "data" / "FULL_POPULATION_RESULTS.csv"
    rows = list(csv.DictReader(in_csv.open()))

    print("\n============================================================")
    print("FEATURE COMPARISON — SUCCESS vs FAIL vs AMBIGUOUS × year × kind")
    print("============================================================")
    out_rows = []
    numeric_feats = [
        ("bb_width_pts", "BB width"),
        ("rsi", "RSI"),
        ("macd_hist", "MACD hist"),
        ("extreme_pts", "extreme (p)"),
        ("run_move_pips", "run move (p)"),
        ("run_depth_pips", "run depth (p)"),
    ]
    bool_feats = [
        ("bb_breach_low", "BB breach lower"),
        ("bb_breach_up", "BB breach upper"),
        ("near_round_level", "near 50-point round"),
        ("near_session_extreme", "near session extreme"),
    ]
    for year in ("2024", "2025"):
        for kind in ("BULL", "BEAR"):
            print(f"\n--- {year} {kind} ---")
            for outcome_prefix in ("SUCCESS", "FAIL", "AMBIGUOUS"):
                subset = [r for r in rows if r["year"] == year and r["kind"] == kind
                          and r["outcome_label"].startswith(outcome_prefix)]
                n = len(subset)
                row = {"year": year, "kind": kind, "outcome": outcome_prefix, "n": n}
                print(f"  {outcome_prefix:10} n={n}")
                for col, lbl in numeric_feats:
                    xs = [_as_float(r[col]) for r in subset]
                    p25, p50, p75, mean = _summ(xs)
                    row[f"{col}_p25"] = p25
                    row[f"{col}_p50"] = p50
                    row[f"{col}_p75"] = p75
                    row[f"{col}_mean"] = mean
                    print(f"    {lbl:25}  p25={p25}  p50={p50}  p75={p75}  mean={mean}")
                for col, lbl in bool_feats:
                    xs = [r[col] for r in subset]
                    share = _share(xs)
                    row[f"{col}_share_pct"] = share
                    print(f"    {lbl:25}  share%={share}")
                out_rows.append(row)

    # Session success rates (decisive)
    print("\n============================================================")
    print("SUCCESS RATE (DECISIVE) BY SESSION × year × kind")
    print("============================================================")
    sess_order = ("LONDON_AM", "LONDON_MIDDAY", "NY_OVERLAP", "NY_PM", "OTHER")
    for year in ("2024", "2025"):
        for kind in ("BULL", "BEAR"):
            print(f"\n--- {year} {kind} ---")
            for sess in sess_order:
                subset = [r for r in rows if r["year"] == year and r["kind"] == kind
                          and r["session"] == sess]
                n_total = len(subset)
                n_s = sum(1 for r in subset if r["outcome_label"].startswith("SUCCESS"))
                n_f = sum(1 for r in subset if r["outcome_label"].startswith("FAIL"))
                dec = n_s + n_f
                sr = round(100.0 * n_s / dec, 1) if dec else None
                lo, hi = _wilson(n_s, dec)
                print(f"  {sess:14}  n={n_total:4}  SUCCESS={n_s:3}  FAIL={n_f:3}  "
                      f"rate_decisive={sr}%  CI95 [{lo*100:.1f},{hi*100:.1f}]")

    # Volatility (BB-width) quintiles — split within (year, kind), then
    # measure success rate per quintile
    print("\n============================================================")
    print("SUCCESS RATE BY BB-WIDTH QUINTILE × year × kind")
    print("============================================================")
    for year in ("2024", "2025"):
        for kind in ("BULL", "BEAR"):
            subset = [r for r in rows if r["year"] == year and r["kind"] == kind]
            widths = sorted(
                (_as_float(r["bb_width_pts"]) for r in subset
                 if _as_float(r["bb_width_pts"]) is not None)
            )
            if len(widths) < 5:
                continue
            # Quintile boundaries
            q = statistics.quantiles(widths, n=5)
            bounds = [-math.inf] + q + [math.inf]
            print(f"\n--- {year} {kind} (quintile bounds: {[round(x, 1) for x in q]}) ---")
            for i in range(5):
                lo, hi = bounds[i], bounds[i + 1]
                bucket = [r for r in subset
                          if _as_float(r["bb_width_pts"]) is not None
                          and lo < _as_float(r["bb_width_pts"]) <= hi]
                n_total = len(bucket)
                n_s = sum(1 for r in bucket if r["outcome_label"].startswith("SUCCESS"))
                n_f = sum(1 for r in bucket if r["outcome_label"].startswith("FAIL"))
                dec = n_s + n_f
                sr = round(100.0 * n_s / dec, 1) if dec else None
                lw, hw = _wilson(n_s, dec)
                print(f"  Q{i+1}  width ({'-∞' if i==0 else round(lo,1)}, "
                      f"{round(hi,1) if i<4 else '+∞'}]  "
                      f"n={n_total:3}  S={n_s:2}  F={n_f:3}  "
                      f"rate_decisive={sr}%  CI95 [{lw*100:.1f},{hw*100:.1f}]")

    out_path = HERE.parent / "data" / "FEATURE_COMPARISON.csv"
    if out_rows:
        fieldnames = list(out_rows[0].keys())
        with out_path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            for r in out_rows:
                w.writerow(r)
        print(f"\n✓ wrote {out_path} ({len(out_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
