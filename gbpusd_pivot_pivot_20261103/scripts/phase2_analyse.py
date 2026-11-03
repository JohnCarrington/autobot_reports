"""Phase 2 analysis — statistics from pivot_events.csv.

Computes:
  * Event counts per level
  * Reversal vs breakout rates (fixed 10p / 15-bar thresholds from the detection script)
  * Outcome distributions at 15 / 30 / 60 / 120 bars
  * Next-pivot-reached rates
  * Reach-rate matrix: P[next pivot = X | this pivot = Y, approach_dir = D]
  * Chronological OOS split: train 2024-01-01 → 2025-06-30, test 2025-07-01 → 2026-02-28
  * Shortfall + overshoot distributions (pre-touch MFE/MAE)
"""

from __future__ import annotations

import csv
import pathlib
import statistics
from collections import Counter, defaultdict

CSV_PATH = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events.csv"
OUT_DIR  = pathlib.Path(__file__).parent.parent / "csv"

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

def pctl(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
    return s[k]

def summarise(events: list[dict], label: str) -> dict:
    N = len(events)
    counts = Counter(e["pivot_name"] for e in events)
    # Reversal vs breakout rate per level
    reversals = defaultdict(int)
    breakouts = defaultdict(int)
    neither   = defaultdict(int)
    both      = defaultdict(int)
    for e in events:
        rj = int(e["reject_flag"])
        bk = int(e["breakout_flag"])
        p = e["pivot_name"]
        if rj and bk:
            both[p] += 1
        elif rj:
            reversals[p] += 1
        elif bk:
            breakouts[p] += 1
        else:
            neither[p] += 1
    # Outcome distribution at each horizon
    outcomes = defaultdict(lambda: defaultdict(list))
    for e in events:
        for h in (15, 30, 60, 120):
            outcomes[h][e["pivot_name"]].append(float(e[f"outcome_{h}b_pips"]))
    # Next-pivot reach rate
    next_reached = defaultdict(lambda: [0, 0])  # [reached, total]
    next_hist = defaultdict(Counter)            # pivot -> Counter(next_pivot_name)
    for e in events:
        pv = e["pivot_name"]
        next_reached[pv][1] += 1
        if e["next_pivot_reached"]:
            next_reached[pv][0] += 1
            next_hist[pv][e["next_pivot_reached"]] += 1
    # Pre-touch MFE/MAE
    mfe = defaultdict(list)
    mae = defaultdict(list)
    for e in events:
        mfe[e["pivot_name"]].append(float(e["pre_touch_mfe_pips"]))
        mae[e["pivot_name"]].append(float(e["pre_touch_mae_pips"]))

    print(f"\n=== {label} — N = {N} events ===")
    print(f"{'Lvl':4} {'N':>5} {'Rej%':>6} {'Brk%':>6} {'Both%':>6} {'Neit%':>6} "
          f"{'15b_med':>8} {'30b_med':>8} {'60b_med':>8} {'120b_med':>8} "
          f"{'NextReach%':>11}  NextReach->")
    for p in PIVOT_NAMES:
        n = counts.get(p, 0)
        if n == 0:
            print(f"{p:4} 0")
            continue
        rj_pct = 100 * reversals[p] / n
        bk_pct = 100 * breakouts[p] / n
        bo_pct = 100 * both[p]      / n
        ne_pct = 100 * neither[p]   / n
        row = (f"{p:4} {n:>5} "
               f"{rj_pct:>5.1f}% {bk_pct:>5.1f}% {bo_pct:>5.1f}% {ne_pct:>5.1f}% "
               f"{statistics.median(outcomes[15][p]):>+8.1f} "
               f"{statistics.median(outcomes[30][p]):>+8.1f} "
               f"{statistics.median(outcomes[60][p]):>+8.1f} "
               f"{statistics.median(outcomes[120][p]):>+8.1f} "
               f"{100 * next_reached[p][0] / max(next_reached[p][1], 1):>10.1f}%  ")
        row += "  ".join(f"{k}:{v}" for k, v in next_hist[p].most_common(3))
        print(row)

    return {
        "N": N,
        "counts": dict(counts),
        "reversals": dict(reversals),
        "breakouts": dict(breakouts),
        "both": dict(both),
        "neither": dict(neither),
        "outcomes_median": {h: {p: statistics.median(outcomes[h][p])
                                for p in PIVOT_NAMES if outcomes[h][p]}
                            for h in (15, 30, 60, 120)},
        "next_reach_rate": {p: next_reached[p][0] / next_reached[p][1]
                            for p in PIVOT_NAMES if next_reached[p][1] > 0},
        "next_pivot_distribution": {p: dict(next_hist[p]) for p in PIVOT_NAMES if next_hist[p]},
        "pre_touch_mfe_p25_p75": {p: (pctl(mfe[p], 0.25), pctl(mfe[p], 0.75))
                                  for p in PIVOT_NAMES if mfe[p]},
        "pre_touch_mae_p25_p75": {p: (pctl(mae[p], 0.25), pctl(mae[p], 0.75))
                                  for p in PIVOT_NAMES if mae[p]},
    }

def reach_matrix(events: list[dict], label: str) -> None:
    """Conditional reach matrix: P[next pivot = X | this = Y, dir = D]."""
    print(f"\n=== {label} — reach matrix (reached-next given this-pivot + dir) ===")
    bucket = defaultdict(lambda: defaultdict(int))  # (this, dir) -> next -> count
    total = defaultdict(int)
    for e in events:
        key = (e["pivot_name"], e["approach_dir"])
        total[key] += 1
        nxt = e["next_pivot_reached"] or "(none)"
        bucket[key][nxt] += 1
    hdr = f"{'this_dir':<9} {'n':>5}  " + " ".join(f"{p:>5}" for p in PIVOT_NAMES) + f"  {'none':>5}"
    print(hdr)
    for p in PIVOT_NAMES:
        for d in ("UP", "DOWN"):
            key = (p, d)
            n = total[key]
            if n == 0:
                continue
            row = f"{p:>3} {d:<5} {n:>5}  "
            for nxt in PIVOT_NAMES:
                pct = 100 * bucket[key][nxt] / n
                row += f"{pct:>4.0f}% "
            none_pct = 100 * bucket[key]["(none)"] / n
            row += f" {none_pct:>4.0f}%"
            print(row)

def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open()))
    print(f"Loaded {len(rows)} events from {CSV_PATH.name}")

    # Chronological OOS split
    train = [r for r in rows if r["date"] < "2025-07-01"]
    test  = [r for r in rows if r["date"] >= "2025-07-01"]
    print(f"Train (2024-01 -> 2025-06-30, bid): {len(train)}   "
          f"Test (2025-07 -> 2026-02-28):    {len(test)}")

    summarise(rows,  "ALL (2024-01 -> 2026-02-28)")
    summarise(train, "TRAIN (2024-01 -> 2025-06-30)")
    summarise(test,  "TEST  (2025-07 -> 2026-02-28)")
    reach_matrix(rows, "ALL")
    reach_matrix(train, "TRAIN")
    reach_matrix(test,  "TEST")

if __name__ == "__main__":
    main()
