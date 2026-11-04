"""Addendum H — Opening-above/below-P conditional pivot reach stats.

Scoped exactly to the operator's questions in the 2026-11-04 brief.
No HTF filters, no EMA, no trade simulation, no RR, no hypotheses.

Procedure (per day):
  1. Load the day's M5 bars in chronological order.
  2. The "opening price" is the open of the FIRST M5 bar of the day.
  3. Compute daily pivots from the previous-trading-day H/L/C (same
     method as Phase 2; BID basis for 2024-2025, MID for 2026 Jan-Feb).
  4. Determine open-vs-P: above or below the central pivot.
  5. Walk through the day's bars chronologically and flag the FIRST
     bar that touches each pivot level (bar.low <= pivot <= bar.high).
  6. Compute counts for the six questions.

For days opening ABOVE P (R2/R3 as upside destinations, S1/S2 as
downside pullbacks):
  Q1. % reaching R2 at any point.
  Q2. % reaching R3 at any point.
  Q3. % touching S1 BEFORE reaching R2 (strict: S1 touch index < R2 touch index, or S1 touched and R2 not reached).
  Q4. % touching S2 BEFORE reaching R2.
  Q5. % reaching R2 WITHOUT first touching S1 OR S2.
  Q6. Of days that touched S1 or S2, % that SUBSEQUENTLY reached R2.

For days opening BELOW P (mirror — S2/S3 as destinations; R1/R2 as pullbacks):
  Q1'. % reaching S2.
  Q2'. % reaching S3.
  Q3'. % touching R1 BEFORE reaching S2.
  Q4'. % touching R2 BEFORE reaching S2.
  Q5'. % reaching S2 WITHOUT first touching R1 OR R2.
  Q6'. Of days that touched R1 or R2, % that SUBSEQUENTLY reached S2.

Writes csv/addendum_h_results.csv (counts) and prints the tables.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
from collections import Counter

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
OUT_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_h_results.csv"

def load_day(path: pathlib.Path) -> list[dict]:
    if not path.exists(): return []
    out = []
    for row in csv.DictReader(path.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try: ts = dt.datetime.fromisoformat(ts_raw)
        except: continue
        out.append({"ts": ts,
                    "o": float(row["open"])/10000.0,
                    "h": float(row["high"])/10000.0,
                    "l": float(row["low"])/10000.0,
                    "c": float(row["close"])/10000.0})
    return out

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {
        "P":  P,
        "R1": 2*P - L, "S1": 2*P - H,
        "R2": P + (H-L), "S2": P - (H-L),
        "R3": H + 2*(P - L), "S3": L - 2*(H - P),
    }

def first_touch_index(bars: list[dict], level: float) -> int | None:
    for i, b in enumerate(bars):
        if b["l"] <= level <= b["h"]:
            return i
    return None

def main() -> None:
    # Build daily rollup cache
    daily_cache: dict[dt.date, list[dict]] = {}
    for root in (BID_ROOT, MID_ROOT):
        for f in root.glob("*.csv"):
            try: d = dt.date.fromisoformat(f.stem)
            except: continue
            if d.year == 2026 and d.month > 2:
                # Phase 1 excludes 2026-03+ (DST gap + mid-rounding 2026-04+)
                continue
            if d not in daily_cache:
                daily_cache[d] = load_day(f)

    sorted_dates = sorted(daily_cache.keys())
    # Get prior-day OHLC
    prior_rollup: dict[dt.date, tuple] = {}
    for d in sorted_dates:
        bars = daily_cache[d]
        if bars:
            prior_rollup[d] = (max(b["h"] for b in bars),
                               min(b["l"] for b in bars),
                               bars[-1]["c"])

    # Walk each day; classify open-vs-P; chronological first-touch for each pivot
    above_days = []  # list of dicts with the per-day outcomes
    below_days = []
    rows_out = []
    skipped = Counter()

    for d in sorted_dates:
        bars = daily_cache[d]
        if not bars:
            skipped["no_bars"] += 1
            continue
        prior = None
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            if cand in prior_rollup:
                prior = prior_rollup[cand]; break
        if prior is None:
            skipped["no_prior"] += 1
            continue
        H, L, C = prior
        piv = pivots(H, L, C)
        open_px = bars[0]["o"]

        # Which side of P?
        if open_px > piv["P"]:
            side = "ABOVE"
        elif open_px < piv["P"]:
            side = "BELOW"
        else:
            skipped["open_at_P"] += 1
            continue

        # First touch indices for each pivot
        t = {pn: first_touch_index(bars, piv[pn]) for pn in ("S3","S2","S1","P","R1","R2","R3")}

        rec = {"date": d.isoformat(), "side": side, "open": f"{open_px:.5f}",
               **{f"idx_{k}": ("" if v is None else v) for k, v in t.items()},
               "basis": "bid" if d.year < 2026 else "mid"}
        rows_out.append(rec)

        if side == "ABOVE":
            above_days.append({"date": d, "t": t})
        else:
            below_days.append({"date": d, "t": t})

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"Wrote {len(rows_out)} daily rows to {OUT_CSV}")
    print(f"Skipped: {dict(skipped)}")

    def pct(n, d):
        return (100.0 * n / d) if d else float("nan")

    # ---------- ABOVE days ----------
    N_above = len(above_days)
    print(f"\n{'='*70}")
    print(f"DAYS OPENING ABOVE P — N = {N_above}")
    print(f"{'='*70}")

    reach_r2 = [d for d in above_days if d["t"]["R2"] is not None]
    reach_r3 = [d for d in above_days if d["t"]["R3"] is not None]
    print(f"\nQ1. % reaching R2:                        {len(reach_r2)} / {N_above} = {pct(len(reach_r2), N_above):.1f}%")
    print(f"Q2. % reaching R3:                        {len(reach_r3)} / {N_above} = {pct(len(reach_r3), N_above):.1f}%")

    # Touched S1 BEFORE R2: either S1 index < R2 index, or S1 touched and R2 never touched
    def touched_before(t, pullback, destination):
        p = t[pullback]; dst = t[destination]
        if p is None: return False
        if dst is None: return True  # touched pullback, destination never reached
        return p < dst

    s1_before_r2 = [d for d in above_days if touched_before(d["t"], "S1", "R2")]
    s2_before_r2 = [d for d in above_days if touched_before(d["t"], "S2", "R2")]
    print(f"Q3. % touching S1 before reaching R2:     {len(s1_before_r2)} / {N_above} = {pct(len(s1_before_r2), N_above):.1f}%")
    print(f"Q4. % touching S2 before reaching R2:     {len(s2_before_r2)} / {N_above} = {pct(len(s2_before_r2), N_above):.1f}%")

    # Reach R2 WITHOUT touching S1 OR S2 before R2
    def reach_dest_clean(t, pullbacks, destination):
        dst = t[destination]
        if dst is None: return False
        for pb in pullbacks:
            p = t[pb]
            if p is not None and p < dst: return False
        return True

    r2_clean = [d for d in above_days if reach_dest_clean(d["t"], ("S1", "S2"), "R2")]
    print(f"Q5. % reaching R2 without first touching S1 or S2: {len(r2_clean)} / {N_above} = {pct(len(r2_clean), N_above):.1f}%")

    # Of days that touched S1 or S2, % subsequently reaching R2
    touched_s = [d for d in above_days if (d["t"]["S1"] is not None or d["t"]["S2"] is not None)]
    # "Subsequently" = R2 touched AFTER the FIRST of S1/S2 was touched
    def touched_then_reached(t, pullbacks, destination):
        first_pb = min((t[p] for p in pullbacks if t[p] is not None), default=None)
        if first_pb is None: return False
        dst = t[destination]
        return dst is not None and dst > first_pb

    subseq_r2 = [d for d in above_days if touched_then_reached(d["t"], ("S1", "S2"), "R2")]
    print(f"Q6. Of days touching S1 or S2, % subsequently reaching R2: {len(subseq_r2)} / {len(touched_s)} = {pct(len(subseq_r2), len(touched_s)):.1f}%")
    print(f"    (denominator {len(touched_s)} days touched S1 or S2; of those, {len(subseq_r2)} later touched R2)")

    # ---------- BELOW days — mirror ----------
    N_below = len(below_days)
    print(f"\n{'='*70}")
    print(f"DAYS OPENING BELOW P — N = {N_below}")
    print(f"{'='*70}")

    reach_s2 = [d for d in below_days if d["t"]["S2"] is not None]
    reach_s3 = [d for d in below_days if d["t"]["S3"] is not None]
    print(f"\nQ1'. % reaching S2:                       {len(reach_s2)} / {N_below} = {pct(len(reach_s2), N_below):.1f}%")
    print(f"Q2'. % reaching S3:                       {len(reach_s3)} / {N_below} = {pct(len(reach_s3), N_below):.1f}%")

    r1_before_s2 = [d for d in below_days if touched_before(d["t"], "R1", "S2")]
    r2_before_s2 = [d for d in below_days if touched_before(d["t"], "R2", "S2")]
    print(f"Q3'. % touching R1 before reaching S2:    {len(r1_before_s2)} / {N_below} = {pct(len(r1_before_s2), N_below):.1f}%")
    print(f"Q4'. % touching R2 before reaching S2:    {len(r2_before_s2)} / {N_below} = {pct(len(r2_before_s2), N_below):.1f}%")

    s2_clean = [d for d in below_days if reach_dest_clean(d["t"], ("R1", "R2"), "S2")]
    print(f"Q5'. % reaching S2 without first touching R1 or R2: {len(s2_clean)} / {N_below} = {pct(len(s2_clean), N_below):.1f}%")

    touched_r = [d for d in below_days if (d["t"]["R1"] is not None or d["t"]["R2"] is not None)]
    subseq_s2 = [d for d in below_days if touched_then_reached(d["t"], ("R1", "R2"), "S2")]
    print(f"Q6'. Of days touching R1 or R2, % subsequently reaching S2: {len(subseq_s2)} / {len(touched_r)} = {pct(len(subseq_s2), len(touched_r)):.1f}%")
    print(f"     (denominator {len(touched_r)} days touched R1 or R2; of those, {len(subseq_s2)} later touched S2)")

    # Basis breakdown
    print(f"\n{'='*70}")
    print("Basis breakdown (BID 2024-2025 vs MID 2026-Jan/Feb)")
    print(f"{'='*70}")
    bid_above = sum(1 for r in rows_out if r["side"] == "ABOVE" and r["basis"] == "bid")
    mid_above = sum(1 for r in rows_out if r["side"] == "ABOVE" and r["basis"] == "mid")
    bid_below = sum(1 for r in rows_out if r["side"] == "BELOW" and r["basis"] == "bid")
    mid_below = sum(1 for r in rows_out if r["side"] == "BELOW" and r["basis"] == "mid")
    print(f"  ABOVE: bid {bid_above} + mid {mid_above} = {bid_above + mid_above}")
    print(f"  BELOW: bid {bid_below} + mid {mid_below} = {bid_below + mid_below}")

if __name__ == "__main__":
    main()
