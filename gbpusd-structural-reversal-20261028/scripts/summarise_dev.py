"""Summarise the 2024 development year — response rates per family,
best SL×TP cells per (family, confirmation), opportunity frequency,
TYPE_4 repeated-test subset analysis.
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"


def _wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def main(year=2024):
    # Load response classification
    resp = [r for r in csv.DictReader((DATA / "STRUCTURAL_RESPONSE_CLASSIFICATION.csv").open())
            if r["year"] == str(year)]
    print(f"\n### Year {year}: {len(resp)} events\n")

    # 1. Response-type share per family
    print("### Response type share by level_family (%)")
    print(f"{'family':15} {'TYPE_1':>8} {'TYPE_2':>8} {'TYPE_3':>8} {'TYPE_4 flag':>11} {'n':>7}")
    for fam in ("PREV_DAY", "PREV_SESSION", "SWING", "DEFENDED", "PIVOT", "ROUND"):
        sub = [r for r in resp if r["level_family"] == fam]
        n = len(sub)
        if n == 0:
            continue
        c1 = sum(1 for r in sub if r["type_label"] == "TYPE_1_DIRECT_REJECT")
        c2 = sum(1 for r in sub if r["type_label"] == "TYPE_2_SWEEP_RECLAIM")
        c3 = sum(1 for r in sub if r["type_label"] == "TYPE_3_ACCEPTED_BREAKOUT")
        c4 = sum(1 for r in sub if r["repeated_test_flag"].lower() in ("true", "1"))
        print(f"{fam:15} {100*c1/n:8.1f} {100*c2/n:8.1f} {100*c3/n:8.1f} {100*c4/n:11.1f} {n:7d}")

    # 2. Opportunity rate per family per trading week (52 weeks)
    print("\n### Events per trading week by family")
    for fam in ("PREV_DAY", "PREV_SESSION", "SWING", "DEFENDED", "PIVOT", "ROUND"):
        n = sum(1 for r in resp if r["level_family"] == fam)
        print(f"  {fam:15} {n/52:7.1f}")

    # 3. Prior-tests effect on Type-1 reject rate
    print("\n### TYPE_1 reject rate by prior_tests_count")
    for ptc in ("0", "1", "2", "3"):
        sub = [r for r in resp if r["prior_tests_count"] == ptc]
        n = len(sub)
        c1 = sum(1 for r in sub if r["type_label"] == "TYPE_1_DIRECT_REJECT")
        if n > 0:
            lo, hi = _wilson(c1, n)
            print(f"  prior_tests={ptc}  n={n:5}  type1_pct={100*c1/n:5.1f}%  CI95 [{lo*100:4.1f},{hi*100:4.1f}]")

    # 4. SL×TP grid — best cells
    print("\n### ENTRY_FEASIBILITY — best cells by family × confirmation (worst-case expectancy, 1 p spread)")
    feas = [r for r in csv.DictReader((DATA / "ENTRY_FEASIBILITY.csv").open())
            if r["year"] == str(year) and r["spread_pts"] == "1" and r["expectancy_pts_amb_as_sl"]]
    for fam in ("PREV_DAY", "PREV_SESSION", "SWING", "DEFENDED", "PIVOT", "ROUND"):
        for cf in ("CF1_first_touch", "CF2_rejection_close", "CF3_sweep_reclaim",
                   "CF4_countertrend_body", "CF5_minor_swing_break", "CF6_retest_after_reject"):
            cells = [r for r in feas if r["level_family"] == fam and r["cf_event"] == cf]
            if not cells:
                continue
            cells.sort(key=lambda r: _f(r["expectancy_pts_amb_as_sl"]) or 0.0, reverse=True)
            best = cells[0]
            if _f(best["expectancy_pts_amb_as_sl"]) is None:
                continue
            print(f"  {fam:14} {cf:28} SL={best['sl_pts']:>3} TP={best['tp_pts']:>3}  "
                  f"n={best['n_fired']:>5}  "
                  f"hit={best['hit_rate_decisive']:>6}  "
                  f"exp={best['expectancy_pts_amb_as_sl']:>6}p")

    # 5. Best overall cells with n ≥ 100
    print("\n### Top 15 cells overall (n ≥ 100, 1 p spread, expectancy_amb_as_sl)")
    big = [r for r in feas if int(r["n_fired"]) >= 100]
    big.sort(key=lambda r: _f(r["expectancy_pts_amb_as_sl"]) or 0.0, reverse=True)
    for r in big[:15]:
        print(f"  {r['level_family']:14} {r['cf_event']:28} SL={r['sl_pts']:>3} TP={r['tp_pts']:>3}  "
              f"n={r['n_fired']:>5}  "
              f"TP/SL/AMB={r['n_tp']}/{r['n_sl']}/{r['n_amb']}  "
              f"hit={r['hit_rate_decisive']:>6}  "
              f"exp={r['expectancy_pts_amb_as_sl']:>6}p")


if __name__ == "__main__":
    import sys
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    main(year)
