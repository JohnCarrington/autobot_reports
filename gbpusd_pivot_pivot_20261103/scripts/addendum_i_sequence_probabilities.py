"""Addendum I — pivot sequence and next-destination conditional probabilities.

Scope: exactly the operator's 10 questions (5 per side) on the 676-day
Addendum H dataset. No new indicators, no HTF filters, no trading rules,
no stops, no RR, no simulation.

Definitions:
  * Touch = bar.low <= pivot <= bar.high (first M5 bar with this property).
  * Reclaim P via M5 close = first M5 bar whose CLOSE is on the "other side"
    of P relative to the direction being reclaimed, strictly AFTER a
    qualifying earlier event. A wick that pierces P without closing through
    does NOT count as a reclaim.
  * Rejection: not needed explicitly for the operator's 10 questions, but
    we honour the brief's definition (M5 close, not a wick) wherever
    "reclaim/rejection" would otherwise be ambiguous.

Look-ahead: for each conditional P(destination | qualifying event), the
qualifying event index MUST be < destination index.

Time-to-destination: measured in M5 bars from the qualifying event to the
destination touch; reported in minutes as bars × 5.

Same-day resolution: a destination is "reached same day" iff its touch
index is within the day's bars (automatic by construction here — all
events are indexed from the day's own bar list).

Output: csv/addendum_i_results.csv + console tables.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import statistics
from collections import defaultdict

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
OUT_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_i_results.csv"

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

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

def first_touch(bars, level, start=0):
    for i in range(start, len(bars)):
        b = bars[i]
        if b["l"] <= level <= b["h"]:
            return i
    return None

def first_close_above(bars, level, start=0):
    for i in range(start, len(bars)):
        if bars[i]["c"] > level:
            return i
    return None

def first_close_below(bars, level, start=0):
    for i in range(start, len(bars)):
        if bars[i]["c"] < level:
            return i
    return None

def main() -> None:
    daily_cache: dict[dt.date, list[dict]] = {}
    for root in (BID_ROOT, MID_ROOT):
        for f in root.glob("*.csv"):
            try: d = dt.date.fromisoformat(f.stem)
            except: continue
            if d.year == 2026 and d.month > 2: continue
            if d not in daily_cache:
                daily_cache[d] = load_day(f)
    sorted_dates = sorted(daily_cache.keys())
    prior_rollup = {}
    for d in sorted_dates:
        bars = daily_cache[d]
        if bars:
            prior_rollup[d] = (max(b["h"] for b in bars),
                               min(b["l"] for b in bars),
                               bars[-1]["c"])

    # Build per-day record for each day with first-touch indices + close-through indices
    above_days = []
    below_days = []
    for d in sorted_dates:
        bars = daily_cache[d]
        if not bars: continue
        prior = None
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            if cand in prior_rollup:
                prior = prior_rollup[cand]; break
        if prior is None: continue
        H, L, C = prior
        piv = pivots(H, L, C)
        open_px = bars[0]["o"]
        if open_px > piv["P"]: side = "ABOVE"
        elif open_px < piv["P"]: side = "BELOW"
        else: continue
        touches = {pn: first_touch(bars, piv[pn]) for pn in PIVOT_NAMES}
        rec = {"date": d.isoformat(), "side": side, "bars": bars, "piv": piv, "t": touches}
        if side == "ABOVE": above_days.append(rec)
        else: below_days.append(rec)

    out_rows = []
    def tally(name, qualifiers, reaches, times_bars):
        """qualifiers/reaches are lists of day records; times_bars = [bars from qual event to destination]."""
        q = len(qualifiers); r = len(reaches)
        p = (r / q * 100.0) if q else float("nan")
        med = statistics.median(times_bars) if times_bars else None
        row = {"question": name,
               "qualifying": q, "reached": r, "pct": f"{p:.1f}%",
               "median_time_bars": med if med is not None else "",
               "median_time_min":  (med * 5 if med is not None else "")}
        out_rows.append(row)
        return row

    # ---- ABOVE questions ----
    print("\n" + "=" * 70)
    print(f"DAYS OPENING ABOVE P — N = {len(above_days)}")
    print("=" * 70)

    # Q1. P(reach R2 | reached R1 first)
    qual, reach, times = [], [], []
    for d in above_days:
        r1_i = d["t"]["R1"]; r2_i = d["t"]["R2"]
        if r1_i is None: continue
        qual.append(d)
        if r2_i is not None and r2_i > r1_i:
            reach.append(d); times.append(r2_i - r1_i)
    tally("Q1 ABOVE: P(R2 | R1 first)", qual, reach, times)
    print(f"Q1. P(R2 | R1 first):        {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q2. P(reach R2 | touched S1 or S2 at some point before R2)
    # "After price touches S1 or S2": first-of-S1/S2 index, then R2 must come later
    qual, reach, times = [], [], []
    for d in above_days:
        s1 = d["t"]["S1"]; s2 = d["t"]["S2"]; r2 = d["t"]["R2"]
        first_s = min((i for i in (s1, s2) if i is not None), default=None)
        if first_s is None: continue
        qual.append(d)
        if r2 is not None and r2 > first_s:
            reach.append(d); times.append(r2 - first_s)
    tally("Q2 ABOVE: P(R2 | first S1/S2 touch)", qual, reach, times)
    print(f"Q2. P(R2 | touched S1 or S2): {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q3. P(reach R2 | touched S1/S2 AND then reclaimed P via M5 close)
    # Reclaim P = first M5 close ABOVE P strictly after first_s
    qual, reach, times = [], [], []
    for d in above_days:
        s1 = d["t"]["S1"]; s2 = d["t"]["S2"]; r2 = d["t"]["R2"]
        first_s = min((i for i in (s1, s2) if i is not None), default=None)
        if first_s is None: continue
        reclaim = first_close_above(d["bars"], d["piv"]["P"], start=first_s + 1)
        if reclaim is None: continue
        qual.append(d)
        if r2 is not None and r2 > reclaim:
            reach.append(d); times.append(r2 - reclaim)
    tally("Q3 ABOVE: P(R2 | S1/S2 touch + P reclaim via close)", qual, reach, times)
    print(f"Q3. P(R2 | S1/S2 touch + P close-reclaim): {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q4. P(reach R3 | reached R2 first)
    qual, reach, times = [], [], []
    for d in above_days:
        r2 = d["t"]["R2"]; r3 = d["t"]["R3"]
        if r2 is None: continue
        qual.append(d)
        if r3 is not None and r3 > r2:
            reach.append(d); times.append(r3 - r2)
    tally("Q4 ABOVE: P(R3 | R2 first)", qual, reach, times)
    print(f"Q4. P(R3 | R2 first):        {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q5. P(return to P | reached R2)
    # After reaching R2, does price come back to touch P at any later bar?
    qual, reach, times = [], [], []
    for d in above_days:
        r2 = d["t"]["R2"]
        if r2 is None: continue
        qual.append(d)
        p_ret = first_touch(d["bars"], d["piv"]["P"], start=r2 + 1)
        if p_ret is not None:
            reach.append(d); times.append(p_ret - r2)
    tally("Q5 ABOVE: P(return to P | R2 reached)", qual, reach, times)
    print(f"Q5. P(return to P | R2 reached): {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # ---- BELOW questions ----
    print("\n" + "=" * 70)
    print(f"DAYS OPENING BELOW P — N = {len(below_days)}")
    print("=" * 70)

    # Q1'. P(reach S2 | reached S1 first)
    qual, reach, times = [], [], []
    for d in below_days:
        s1 = d["t"]["S1"]; s2 = d["t"]["S2"]
        if s1 is None: continue
        qual.append(d)
        if s2 is not None and s2 > s1:
            reach.append(d); times.append(s2 - s1)
    tally("Q1 BELOW: P(S2 | S1 first)", qual, reach, times)
    print(f"Q1'. P(S2 | S1 first):        {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q2'. P(reach S2 | touched R1 or R2 at some point before S2)
    qual, reach, times = [], [], []
    for d in below_days:
        r1 = d["t"]["R1"]; r2 = d["t"]["R2"]; s2 = d["t"]["S2"]
        first_r = min((i for i in (r1, r2) if i is not None), default=None)
        if first_r is None: continue
        qual.append(d)
        if s2 is not None and s2 > first_r:
            reach.append(d); times.append(s2 - first_r)
    tally("Q2 BELOW: P(S2 | first R1/R2 touch)", qual, reach, times)
    print(f"Q2'. P(S2 | touched R1 or R2): {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q3'. P(reach S2 | touched R1/R2 + reclaimed P via M5 close BELOW P)
    qual, reach, times = [], [], []
    for d in below_days:
        r1 = d["t"]["R1"]; r2 = d["t"]["R2"]; s2 = d["t"]["S2"]
        first_r = min((i for i in (r1, r2) if i is not None), default=None)
        if first_r is None: continue
        reclaim = first_close_below(d["bars"], d["piv"]["P"], start=first_r + 1)
        if reclaim is None: continue
        qual.append(d)
        if s2 is not None and s2 > reclaim:
            reach.append(d); times.append(s2 - reclaim)
    tally("Q3 BELOW: P(S2 | R1/R2 touch + P reclaim via close)", qual, reach, times)
    print(f"Q3'. P(S2 | R1/R2 touch + P close-reclaim): {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q4'. P(reach S3 | reached S2 first)
    qual, reach, times = [], [], []
    for d in below_days:
        s2 = d["t"]["S2"]; s3 = d["t"]["S3"]
        if s2 is None: continue
        qual.append(d)
        if s3 is not None and s3 > s2:
            reach.append(d); times.append(s3 - s2)
    tally("Q4 BELOW: P(S3 | S2 first)", qual, reach, times)
    print(f"Q4'. P(S3 | S2 first):        {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Q5'. P(return to P | reached S2)
    qual, reach, times = [], [], []
    for d in below_days:
        s2 = d["t"]["S2"]
        if s2 is None: continue
        qual.append(d)
        p_ret = first_touch(d["bars"], d["piv"]["P"], start=s2 + 1)
        if p_ret is not None:
            reach.append(d); times.append(p_ret - s2)
    tally("Q5 BELOW: P(return to P | S2 reached)", qual, reach, times)
    print(f"Q5'. P(return to P | S2 reached): {len(reach)} / {len(qual)} = "
          f"{100*len(reach)/max(len(qual),1):.1f}%   median_time={statistics.median(times)*5 if times else 'n/a'} min")

    # Save CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nWrote results to {OUT_CSV}")

if __name__ == "__main__":
    main()
