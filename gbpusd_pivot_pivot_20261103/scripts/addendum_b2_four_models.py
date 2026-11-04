"""Addendum B2 — four-model comparison.

Starting from the 102 QM graded candidates (100 resolved), test whether
filters based on pivot proximity, session, and remaining capacity improve
expectancy. Chronological OOS split.

Models:
  M0  QM alone (no filter — raw baseline)
  M1  QM + pivot proximity (entry within X pips of a pivot)
  M2  QM + session (active session only: LondonOpen/LondonMorning/LN_NY_Overlap)
  M3  QM + pivot + session + capacity (dist_to_next_pivot >= target_pips)

Pivot proximity sensitivity: X ∈ {5, 10, 15, 20, 25} pips (fixed) +
one volatility-adjusted threshold (X = max(5, 0.5 * atr14)).

Chronological OOS split:
  TRAIN opened_at < 2026-10-29
  TEST  opened_at >= 2026-10-29

"Improvement" is measured by net pips/trade (mean), win rate, and
Wilson-interval 95% CI on win rate.
"""

from __future__ import annotations

import csv
import math
import pathlib
from collections import defaultdict

CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_b1_qm_graded.csv"

PROXIMITY_GRID = [5, 10, 15, 20, 25]
ACTIVE_SESSIONS = {"LondonOpen", "LondonMorning", "LN_NY_Overlap"}

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0: return (float("nan"), float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    radius = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return p, max(0.0, centre - radius), min(1.0, centre + radius)

def resolve(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["net_pips_after_spread"] != "UNRESOLVED"]

def summarise(rows: list[dict], label: str) -> dict:
    res = resolve(rows)
    n = len(res)
    if n == 0:
        print(f"  {label:<55} n=0")
        return {"n": 0}
    wins = sum(1 for r in res if float(r["net_pips_after_spread"]) > 0)
    total = sum(float(r["net_pips_after_spread"]) for r in res)
    mean = total / n
    p, lo, hi = wilson(wins, n)
    print(f"  {label:<55} n={n:>3}  win%={100*p:>5.1f} [{100*lo:4.1f}, {100*hi:4.1f}]  total={total:>+7.1f}p  mean={mean:>+6.2f}p/trade")
    return {"n": n, "wins": wins, "win_rate": p, "ci_lo": lo, "ci_hi": hi, "total": total, "mean": mean}

def filter_m1(rows, max_dist_pips):
    return [r for r in rows if float(r["nearest_pivot_dist_pips_abs"]) <= max_dist_pips]

def filter_m1_vol(rows, mult=0.5):
    """Volatility-adjusted proximity: in-zone if abs_dist <= max(5, mult*ATR14)."""
    out = []
    for r in rows:
        atr = float(r["atr14_m5_pips_at_open"])
        thresh = max(5.0, mult * atr)
        if float(r["nearest_pivot_dist_pips_abs"]) <= thresh:
            out.append(r)
    return out

def filter_m2(rows):
    return [r for r in rows if r["session"] in ACTIVE_SESSIONS]

def filter_m3(rows, max_dist_pips):
    out = []
    for r in rows:
        if r["session"] not in ACTIVE_SESSIONS:
            continue
        if float(r["nearest_pivot_dist_pips_abs"]) > max_dist_pips:
            continue
        # Capacity: distance to next pivot must be >= target_pips (room to run)
        dist_next = float(r["dist_to_next_pivot_pips"])
        target = float(r["target_pips"])
        if dist_next < target:
            continue
        out.append(r)
    return out

def main() -> None:
    rows = list(csv.DictReader(CSV.open()))
    print(f"Total rows loaded: {len(rows)}")
    train = [r for r in rows if r["opened_at"] < "2026-10-29"]
    test  = [r for r in rows if r["opened_at"] >= "2026-10-29"]
    print(f"TRAIN (opened_at < 2026-10-29): {len(train)}")
    print(f"TEST  (opened_at >= 2026-10-29): {len(test)}")

    print("\n" + "=" * 90)
    print("TRAIN — baseline and model variants")
    print("=" * 90)
    summarise(train, "M0  QM alone")
    for px in PROXIMITY_GRID:
        summarise(filter_m1(train, px), f"M1  QM + pivot proximity <= {px}p")
    summarise(filter_m1_vol(train, 0.5), "M1v QM + pivot proximity (max 5p or 0.5*ATR14)")
    summarise(filter_m2(train), "M2  QM + active session")
    for px in (10, 15, 20):
        summarise(filter_m3(train, px),
                    f"M3  QM + pivot<= {px}p + active session + capacity")

    print("\n" + "=" * 90)
    print("TEST — model variants")
    print("=" * 90)
    summarise(test, "M0  QM alone")
    for px in PROXIMITY_GRID:
        summarise(filter_m1(test, px), f"M1  QM + pivot proximity <= {px}p")
    summarise(filter_m1_vol(test, 0.5), "M1v QM + pivot proximity (max 5p or 0.5*ATR14)")
    summarise(filter_m2(test), "M2  QM + active session")
    for px in (10, 15, 20):
        summarise(filter_m3(test, px),
                    f"M3  QM + pivot<= {px}p + active session + capacity")

    # OOS-aware pick: best MEAN on TRAIN among M3 variants, then report TEST
    train_m3 = {px: summarise(filter_m3(train, px), f"_pick{px}")
                for px in (10, 15, 20)}
    train_scores = {px: s.get("mean", -1e9) for px, s in train_m3.items() if s.get("n", 0) >= 10}
    if train_scores:
        best_px = max(train_scores, key=train_scores.get)
        print(f"\nTRAIN-picked best M3 proximity = {best_px}p (mean={train_scores[best_px]:+.2f}p/trade)")
        print(f"\nTEST at that frozen choice:")
        summarise(filter_m3(test, best_px), f"M3@{best_px}p  (frozen from TRAIN)")

    # Per-pivot breakdown on all resolved rows
    print("\n" + "=" * 90)
    print("ALL — per-nearest-pivot (baseline)")
    print("=" * 90)
    by_piv = defaultdict(list)
    for r in resolve(rows):
        by_piv[r["nearest_pivot_name"]].append(r)
    for pn in ("S3","S2","S1","P","R1","R2","R3"):
        summarise(by_piv.get(pn, []), f"nearest={pn}")

    # Per-session breakdown
    print("\nALL — per-session (baseline)")
    by_sess = defaultdict(list)
    for r in resolve(rows):
        by_sess[r["session"]].append(r)
    for s in ("Asia","LondonOpen","LondonMorning","LN_NY_Overlap","LateNY","Off"):
        summarise(by_sess.get(s, []), f"session={s}")

    # Side effect
    print("\nALL — per-side (baseline)")
    by_side = defaultdict(list)
    for r in resolve(rows):
        by_side[r["side"]].append(r)
    for s in ("BUY","SELL"):
        summarise(by_side.get(s, []), f"side={s}")

if __name__ == "__main__":
    main()
