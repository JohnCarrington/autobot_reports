"""Addendum C — PIA First forecasts vs daily pivot levels (n=5).

Uses the five operator-supplied GBPUSD forecasts and the production
IG ASK D1 bars from /opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json.

Pivot formula (textbook, matches /opt/tradingbot/ig_daily_pivots.py:183).
Prior-day selection:
  * Tue 28 Oct 2026 → prev = Mon 27 Oct 2026
  * Wed 29 Oct 2026 → prev = Tue 28 Oct 2026
  * Fri 30 Oct 2026 → prev = Thu 29 Oct 2026
  * Mon 2 Nov 2026  → prev = Fri 30 Oct 2026 (NO Sunday session bar shown
    in the production ASK cache for Sun 1 Nov; falls through to Fri)
  * Tue 3 Nov 2026 → prev = Mon 2 Nov 2026

Monte-Carlo baseline: for each date, draw N=10,000 uniform prices in the
realised daily trading range; measure the min-distance to any of the 7
pivots. Compare the PIA target's actual distance to this baseline.

No modifications to production. Read-only.
"""

from __future__ import annotations

import csv
import json
import pathlib
import random
import statistics
from typing import Dict, List, Tuple

PIVOT_CACHE = pathlib.Path("/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json")
CANDLE_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
OUT_CSV     = pathlib.Path(__file__).parent.parent / "csv" / "addendum_c_pia_pivot_table.csv"

random.seed(20261104)

# Operator-supplied forecasts (verbatim — not augmented).
PIA = [
    # (forecast_date, direction, entry, primary_tgt, extended_tgt, prior_date)
    ("2026-10-28", "BUY",  1.3300, 1.3375, 1.3400, "2026-10-27"),
    ("2026-10-29", "BUY",  1.3300, 1.3375, 1.3400, "2026-10-28"),
    ("2026-10-30", "BUY",  1.3350, 1.3425, 1.3450, "2026-10-29"),
    ("2026-11-02", "BUY",  1.3350, 1.3425, 1.3450, "2026-10-30"),  # prior Fri
    ("2026-11-03", "SELL", 1.3442, 1.3313, None,    "2026-11-02"),
]

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {
        "P":  P,
        "R1": 2 * P - L, "S1": 2 * P - H,
        "R2": P + (H - L), "S2": P - (H - L),
        "R3": H + 2 * (P - L), "S3": L - 2 * (H - P),
    }

def pts(x): return x / 10000.0

def load_pivot_bars() -> Dict[str, Tuple[float, float, float]]:
    """Return dict date_str -> (H, L, C) in FX decimal (ASK side)."""
    d = json.loads(PIVOT_CACHE.read_text())
    out = {}
    for row in d["prices"]:
        date_s = row["snapshotTime"].split(" ")[0].replace("/", "-")
        out[date_s] = (
            pts(row["highPrice"]["ask"]),
            pts(row["lowPrice"]["ask"]),
            pts(row["closePrice"]["ask"]),
        )
    return out

def load_day_range(date: str) -> Tuple[float, float] | None:
    """Return (day_high, day_low) MID from live-captured candle for the trading day."""
    f = CANDLE_ROOT / f"{date}.csv"
    if not f.exists(): return None
    hi, lo = -1.0, 1e9
    for row in csv.DictReader(f.open()):
        try:
            h = float(row["high"]) / 10000.0
            l = float(row["low"])  / 10000.0
            if h > hi: hi = h
            if l < lo: lo = l
        except (ValueError, KeyError):
            continue
    return (hi, lo) if hi > 0 else None

def nearest_pivot(piv: Dict[str, float], price: float) -> Tuple[str, float, float]:
    best = min(piv.items(), key=lambda kv: abs(kv[1] - price))
    return best[0], best[1], (price - best[1]) * 10000.0

def monte_carlo_min_dist(piv: Dict[str, float], day_range: Tuple[float, float],
                          n: int = 10000) -> List[float]:
    """Return list of min-distance-to-nearest-pivot (pips) for N random prices
    drawn uniformly across the realised daily range."""
    hi, lo = day_range
    piv_values = list(piv.values())
    out = []
    for _ in range(n):
        p = random.uniform(lo, hi)
        d = min(abs(p - pv) * 10000.0 for pv in piv_values)
        out.append(d)
    return out

def quantile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals: return float("nan")
    idx = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]

def main() -> None:
    pivot_bars = load_pivot_bars()
    print(f"Loaded ASK D1 bars: {sorted(pivot_bars.keys())[:3]} ... {sorted(pivot_bars.keys())[-3:]}")

    out_rows = []
    for (fd, direction, entry, p_tgt, x_tgt, prior) in PIA:
        if prior not in pivot_bars:
            print(f"SKIP {fd}: prior {prior} not in ASK cache")
            continue
        H, L, C = pivot_bars[prior]
        piv = pivots(H, L, C)
        day_rng = load_day_range(fd)

        # Compute distances for entry, primary tgt, extended tgt
        for label, px in (("entry", entry), ("primary_tgt", p_tgt), ("extended_tgt", x_tgt)):
            if px is None: continue
            nn, nnv, d_signed = nearest_pivot(piv, px)
            d_abs = abs(d_signed)
            # Monte-Carlo baseline for this date
            baseline = monte_carlo_min_dist(piv, day_rng, n=10000) if day_rng else []
            if baseline:
                baseline.sort()
                bl_med = statistics.median(baseline)
                bl_p25 = quantile(baseline, 0.25)
                bl_p05 = quantile(baseline, 0.05)
                # Empirical percentile of PIA's distance within the baseline distribution
                pct = sum(1 for b in baseline if b < d_abs) / len(baseline)
            else:
                bl_med = bl_p25 = bl_p05 = float("nan"); pct = float("nan")

            out_rows.append({
                "forecast_date": fd,
                "direction": direction,
                "prior_day_used": prior,
                "prior_H_L_C": f"{H:.5f}/{L:.5f}/{C:.5f}",
                "level_label": label,
                "price": f"{px:.4f}",
                "nearest_pivot": nn,
                "nearest_pivot_value": f"{nnv:.5f}",
                "dist_to_nearest_pivot_pips": f"{d_signed:+.1f}",
                "dist_abs": f"{d_abs:.1f}",
                "day_range_hi_lo": f"{day_rng[0]:.5f}/{day_rng[1]:.5f}" if day_rng else "n/a",
                "baseline_median_pips": f"{bl_med:.1f}" if bl_med==bl_med else "n/a",
                "baseline_p25_pips":    f"{bl_p25:.1f}" if bl_p25==bl_p25 else "n/a",
                "baseline_p05_pips":    f"{bl_p05:.1f}" if bl_p05==bl_p05 else "n/a",
                "pct_of_baseline_dist": f"{100*pct:.1f}%" if pct==pct else "n/a",
            })

    # Save CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys())
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {len(out_rows)} rows to {OUT_CSV}")

    # Pretty print table
    print()
    print(f"{'date':<11} {'dir':<4} {'level':<13} {'price':>7} {'nearP':<4} {'nearV':>8} {'Δ pips':>8}   {'baseline_med':>12} {'pct':>6}")
    for r in out_rows:
        print(f"{r['forecast_date']:<11} {r['direction']:<4} {r['level_label']:<13} "
              f"{r['price']:>7} {r['nearest_pivot']:<4} {r['nearest_pivot_value']:>8} "
              f"{r['dist_to_nearest_pivot_pips']:>8}   {r['baseline_median_pips']:>12} {r['pct_of_baseline_dist']:>6}")

    # Also: 75/100 fixed-increment analysis
    print("\n=== 75/100 pip pattern analysis ===")
    for (fd, direction, entry, p_tgt, x_tgt, prior) in PIA:
        if direction != "BUY" or x_tgt is None: continue
        primary_pips  = (p_tgt - entry) * 10000.0
        extended_pips = (x_tgt - entry) * 10000.0
        print(f"  {fd} {direction}: entry={entry:.4f} primary=+{primary_pips:.1f}p  extended=+{extended_pips:.1f}p")
    # SELL
    for (fd, direction, entry, p_tgt, x_tgt, prior) in PIA:
        if direction != "SELL": continue
        primary_pips  = (entry - p_tgt) * 10000.0
        print(f"  {fd} {direction}: entry={entry:.4f} primary=-{primary_pips:.1f}p  extended=n/a")

    # Prior-day range and prior-day H-L ratio for measured-move test
    print("\n=== Prior-day range (ASK) for measured-move alternative ===")
    for (fd, direction, entry, p_tgt, x_tgt, prior) in PIA:
        if prior not in pivot_bars: continue
        H, L, _ = pivot_bars[prior]
        R = (H - L) * 10000.0
        print(f"  prior={prior} range={R:.1f}p  primary_tgt_from_entry={(p_tgt-entry if direction=='BUY' else entry-p_tgt)*10000.0:+.1f}p  extended={(x_tgt-entry if direction=='BUY' and x_tgt else 0)*10000.0:+.1f}p")

if __name__ == "__main__":
    main()
