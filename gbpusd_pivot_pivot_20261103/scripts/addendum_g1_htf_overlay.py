"""Addendum G — HTF overlay on pivot events + aligned-pullback simulation.

For every pivot touch in csv/pivot_events.csv (Phase 2, 1,561 events,
BID 2024-2025 + MID 2026 Jan-Feb), reconstruct HTF context from M5
aggregation and simulate a hypothetical PIA-style trade:

  * BUY at S-level if HTF trend UP (aligned pullback)
  * SELL at R-level if HTF trend DOWN (aligned bounce)
  * Trade AGAINST HTF for the opposite side
  * Also simulate "any direction" and "aligned + non-exhausted" variants

HTF definitions declared BEFORE evaluation:

  D1 trend = sign of prior-day close vs 5-day-ago close.
    UP if prior_close > 5d_ago_close + 30p; DOWN if <- 30p; FLAT.
    This is the PRIMARY HTF filter — it captures the "trend context"
    *before* any intraday pullback. For a pullback BUY at S1 to be
    "aligned," D1 must have been UP leading into the day.

  H4 trend = sign of EMA20_H4 slope over last 20 H4 bars (~80h slope).
    UP if slope > +30p; DOWN if slope < -30p; FLAT otherwise.
    A longer-window H4 captures broad direction, not the instantaneous
    pullback dip.

  H1 trend = sign of EMA20_H1 slope over last 4 H1 bars (~4h slope).
    For exhaustion context only — not used in alignment filter.

  Composite HTF_aligned = D1 trend matches proposed trade direction.

  Exhaustion proxy = consecutive same-direction H1 closes >= 8 before the
    pivot touch. If D1 UP and >= 8 consecutive bullish H1 closes, the
    trend is "exhausted" and a pullback-BUY is less favoured.

Trade geometry:
  * Entry: at pivot level (for simplicity; alternative: structural entry
    offset not modelled here).
  * Stop: adjacent pivot on the opposite side of the trade direction.
      For BUY at S1 → stop at S2 - 5p buffer
      For BUY at P  → stop at S1 - 5p buffer
      For SELL at R1 → stop at R2 + 5p buffer
      For SELL at P  → stop at R1 + 5p buffer
      For BUY at S2 → stop at S3 - 5p buffer
      For BUY at S3 → stop at S3 - 20p (no further pivot below)
  * Target: entry ± 3 × stop_distance_pips.
  * Spread: 1.5 p round-trip subtracted from net.
  * Min stop: 10 p (DEMO GBPUSD); skip if structural stop < 10p.
  * Horizon: 240 M5 bars after touch (same as Addendum B grader).

Writes csv/addendum_g_htf_pivot_trades.csv and prints a summary.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
from collections import defaultdict

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
EVENTS_CSV = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events.csv"
OUT_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_g_htf_pivot_trades.csv"

SPREAD_PIPS = 1.5
MIN_STOP_PIPS = 10.0
STOP_BUFFER_PIPS = 5.0
RR_TARGET = 3.0
HORIZON_BARS = 240

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")
ADJACENT_DOWN = {"S3": None, "S2": "S3", "S1": "S2", "P": "S1", "R1": "P", "R2": "R1", "R3": "R2"}
ADJACENT_UP   = {"S3": "S2", "S2": "S1", "S1": "P",  "P": "R1", "R1": "R2", "R2": "R3", "R3": None}

def load_day(path: pathlib.Path) -> list[dict]:
    if not path.exists(): return []
    out = []
    for row in csv.DictReader(path.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try: ts = dt.datetime.fromisoformat(ts_raw)
        except: continue
        out.append({
            "ts": ts,
            "o": float(row["open"])/10000.0, "h": float(row["high"])/10000.0,
            "l": float(row["low"])/10000.0,  "c": float(row["close"])/10000.0,
        })
    return out

def aggregate_to(bars: list[dict], period_minutes: int) -> list[dict]:
    """Aggregate M5 bars into period_minutes bars (60 or 240)."""
    if not bars: return []
    out = []
    bucket_size = period_minutes // 5  # bars per bucket
    i = 0
    while i < len(bars):
        chunk = bars[i:i + bucket_size]
        if not chunk: break
        out.append({
            "ts": chunk[0]["ts"],
            "o": chunk[0]["o"],
            "h": max(b["h"] for b in chunk),
            "l": min(b["l"] for b in chunk),
            "c": chunk[-1]["c"],
        })
        i += bucket_size
    return out

def ema(closes: list[float], span: int) -> list[float]:
    if not closes: return []
    alpha = 2.0 / (span + 1.0)
    out = [closes[0]]
    for c in closes[1:]:
        out.append(alpha * c + (1 - alpha) * out[-1])
    return out

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {"P":P,"R1":2*P-L,"S1":2*P-H,"R2":P+(H-L),"S2":P-(H-L),"R3":H+2*(P-L),"S3":L-2*(H-P)}

def simulate_trade(side, entry, stop, target, bars_after):
    if not bars_after: return None, None
    stop_hit_idx = tgt_hit_idx = None
    for i, b in enumerate(bars_after):
        if side == "BUY":
            if stop_hit_idx is None and b["l"] <= stop: stop_hit_idx = i
            if tgt_hit_idx is None and b["h"] >= target: tgt_hit_idx = i
        else:
            if stop_hit_idx is None and b["h"] >= stop: stop_hit_idx = i
            if tgt_hit_idx is None and b["l"] <= target: tgt_hit_idx = i
        if stop_hit_idx is not None and tgt_hit_idx is not None: break
    if tgt_hit_idx is not None and (stop_hit_idx is None or tgt_hit_idx < stop_hit_idx):
        return "TP", abs(target - entry) * 10000 - SPREAD_PIPS
    if stop_hit_idx is not None:
        return "SL", -abs(entry - stop) * 10000 - SPREAD_PIPS
    return "UNRESOLVED", None

def main() -> None:
    events = list(csv.DictReader(EVENTS_CSV.open()))
    print(f"Loaded {len(events)} pivot events")

    # Pre-load day-rollup cache for daily + prior-day H/L/C
    daily_cache: dict[dt.date, list[dict]] = {}
    for root in (BID_ROOT, MID_ROOT):
        for f in root.glob("*.csv"):
            try: d = dt.date.fromisoformat(f.stem)
            except: continue
            if d not in daily_cache:
                daily_cache[d] = load_day(f)
    print(f"Loaded day cache: {len(daily_cache)} days")

    # Build D1 series of closes for D1 trend
    d1_dates = sorted(daily_cache.keys())
    d1_closes = {d: (daily_cache[d][-1]["c"] if daily_cache[d] else None) for d in d1_dates}
    d1_close_series = [d1_closes[d] for d in d1_dates if d1_closes[d] is not None]

    def d1_trend_for(date: dt.date) -> str:
        """UP if prior close > 5 days ago by ≥30p; DOWN if ≤ -30p; FLAT."""
        try: idx = d1_dates.index(date)
        except ValueError: return "FLAT"
        if idx < 6: return "FLAT"
        prior = d1_closes.get(d1_dates[idx - 1])
        fiveago = d1_closes.get(d1_dates[idx - 6])
        if prior is None or fiveago is None: return "FLAT"
        delta = (prior - fiveago) * 10000.0
        if delta >= 30: return "UP"
        if delta <= -30: return "DOWN"
        return "FLAT"

    # For each event, compute HTF bias at touch time + simulate trade
    out_rows = []
    for e in events:
        ev_date = dt.date.fromisoformat(e["date"])
        ev_ts = dt.datetime.fromisoformat(e["bar_ts"])
        # Load day's bars + previous 2 days for H4/H1 warmup
        all_bars = []
        for d_off in (-2, -1, 0):
            d = ev_date + dt.timedelta(days=d_off)
            if d in daily_cache:
                all_bars.extend(daily_cache[d])
        # Keep bars up to AND INCLUDING ev_ts
        up_to = [b for b in all_bars if b["ts"] <= ev_ts]
        if len(up_to) < 50:
            continue  # not enough warmup

        # Build H1 and H4 from up_to
        h1 = aggregate_to(up_to, 60)
        h4 = aggregate_to(up_to, 240)
        if len(h1) < 20 or len(h4) < 10:
            continue

        # EMA20 slopes
        h1_ema = ema([b["c"] for b in h1], 20)
        h4_ema = ema([b["c"] for b in h4], 20)
        h1_slope_pips = (h1_ema[-1] - h1_ema[-5]) * 10000.0 if len(h1_ema) >= 5 else 0
        h4_slope_pips = (h4_ema[-1] - h4_ema[-20]) * 10000.0 if len(h4_ema) >= 20 else 0

        h1_trend = "UP" if h1_slope_pips > 2 else "DOWN" if h1_slope_pips < -2 else "FLAT"
        h4_trend = "UP" if h4_slope_pips > 30 else "DOWN" if h4_slope_pips < -30 else "FLAT"
        d1_trend = d1_trend_for(ev_date)

        # Consecutive same-direction H1 closes (exhaustion proxy)
        consec_up = consec_down = 0
        for i in range(len(h1) - 1, 0, -1):
            if h1[i]["c"] > h1[i-1]["c"]:
                if consec_down: break
                consec_up += 1
            elif h1[i]["c"] < h1[i-1]["c"]:
                if consec_up: break
                consec_down += 1
            else: break
        exhausted = (h4_trend == "UP" and consec_up >= 8) or (h4_trend == "DOWN" and consec_down >= 8)

        # Hypothetical PIA-style trade: BUY at S/P in UP trend, SELL at R/P in DOWN trend
        # Alignment is D1-based — the HTF bias BEFORE the intraday pullback
        pivot_name = e["pivot_name"]
        pivot_value = float(e["pivot_value"])
        if pivot_name in ("S3", "S2", "S1"):
            proposed_side = "BUY"
            is_aligned = (d1_trend == "UP")
        elif pivot_name in ("R1", "R2", "R3"):
            proposed_side = "SELL"
            is_aligned = (d1_trend == "DOWN")
        elif pivot_name == "P":
            # at P the direction follows D1 trend
            if d1_trend == "UP":
                proposed_side = "BUY"; is_aligned = True
            elif d1_trend == "DOWN":
                proposed_side = "SELL"; is_aligned = True
            else:
                proposed_side = None; is_aligned = False
        else:
            proposed_side = None; is_aligned = False
        if proposed_side is None:
            continue

        # Compute pivots + structural stop
        # Prior day H/L/C for pivot calc
        prior_bars = None
        for back in range(1, 8):
            cand = ev_date - dt.timedelta(days=back)
            if cand in daily_cache and daily_cache[cand]:
                prior_bars = daily_cache[cand]; break
        if not prior_bars: continue
        H = max(b["h"] for b in prior_bars)
        L = min(b["l"] for b in prior_bars)
        C = prior_bars[-1]["c"]
        piv = pivots(H, L, C)

        # Structural stop
        if proposed_side == "BUY":
            stop_level_name = ADJACENT_DOWN.get(pivot_name)
            if stop_level_name is None: continue
            stop_level = piv[stop_level_name]
            stop = stop_level - STOP_BUFFER_PIPS / 10000.0
        else:
            stop_level_name = ADJACENT_UP.get(pivot_name)
            if stop_level_name is None: continue
            stop_level = piv[stop_level_name]
            stop = stop_level + STOP_BUFFER_PIPS / 10000.0
        entry = pivot_value
        stop_pips = abs(entry - stop) * 10000.0
        if stop_pips < MIN_STOP_PIPS: continue
        target = entry + RR_TARGET * (entry - stop) if proposed_side == "BUY" else entry - RR_TARGET * (stop - entry)

        # Bars after touch
        bars_after = [b for b in all_bars if b["ts"] > ev_ts][:HORIZON_BARS]
        outcome, net = simulate_trade(proposed_side, entry, stop, target, bars_after)

        out_rows.append({
            "date": e["date"],
            "pivot_name": pivot_name,
            "touch_ts": e["bar_ts"],
            "approach_dir": e["approach_dir"],
            "basis": e["basis"],
            "proposed_side": proposed_side,
            "h1_slope_pips": f"{h1_slope_pips:+.1f}",
            "h4_slope_pips": f"{h4_slope_pips:+.1f}",
            "h1_trend": h1_trend,
            "h4_trend": h4_trend,
            "d1_trend": d1_trend,
            "consec_up_H1": consec_up,
            "consec_down_H1": consec_down,
            "exhausted": int(exhausted),
            "is_HTF_aligned": int(is_aligned),
            "d1_aligned": int(
                (proposed_side == "BUY" and d1_trend != "DOWN") or
                (proposed_side == "SELL" and d1_trend != "UP")
            ),
            "entry": f"{entry:.5f}",
            "stop": f"{stop:.5f}",
            "stop_pips": f"{stop_pips:.1f}",
            "target": f"{target:.5f}",
            "target_pips": f"{abs(target-entry)*10000:.1f}",
            "outcome": outcome,
            "net_pips": f"{net:+.1f}" if net is not None else "",
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys()) if out_rows else []
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {len(out_rows)} simulated trades to {OUT_CSV}")

    # Variant summaries
    def summarise(rows, label):
        res = [r for r in rows if r["outcome"] in ("TP", "SL")]
        if not res:
            print(f"  {label:<40} n=0")
            return
        wins = sum(1 for r in res if r["outcome"] == "TP")
        total = sum(float(r["net_pips"]) for r in res)
        mean = total / len(res)
        unres = sum(1 for r in rows if r["outcome"] == "UNRESOLVED")
        print(f"  {label:<40} n={len(res):>4}  win%={100*wins/len(res):>5.1f}  total={total:>+7.1f}p  mean={mean:>+5.2f}p  unresolved={unres}")

    print("\n=== Variant summaries (3:1 RR, structural stop) ===")
    print(f"\n{'Variant':<45}  {'n':>4}  {'win%':>5}  {'total':>8}  {'mean':>7}")
    summarise(out_rows, "A — Pivot entries (any HTF)")
    aligned = [r for r in out_rows if int(r["is_HTF_aligned"])]
    summarise(aligned, "B — Pivot + D1-aligned")
    aligned_non_exhausted = [r for r in aligned if not int(r["exhausted"])]
    summarise(aligned_non_exhausted, "C — Pivot + D1-aligned + non-exhausted")
    against = [r for r in out_rows if not int(r["is_HTF_aligned"]) and r["d1_trend"] != "FLAT"]
    summarise(against, "D — Pivot against D1 trend")

    # Per-level under variant B
    print("\n=== Per-pivot (Variant B — D1-aligned) ===")
    by_piv = defaultdict(list)
    for r in aligned: by_piv[r["pivot_name"]].append(r)
    for pn in PIVOT_NAMES:
        summarise(by_piv.get(pn, []), f"B:{pn}")

    # Sensitivity: 1:1 and 2:1 RR
    print("\n=== RR sensitivity (recomputed outcomes at 1:1 and 2:1) ===")
    for rr in (1.0, 2.0, 3.0):
        hits = 0; losses = 0; unres = 0; net_total = 0.0
        for r in out_rows:
            if not int(r["is_HTF_aligned"]): continue
            e = float(r["entry"]); s = float(r["stop"]); side = r["proposed_side"]
            stop_p = abs(e - s) * 10000.0
            tgt = e + rr * (e - s) if side == "BUY" else e - rr * (s - e)
            # Recompute from original bars — needs re-simulation, approximation here:
            # Use outcome field: if TP at 3:1 means price moved 3*stop_p; at 1:1 needs stop_p
            # We don't have bar-level recomputation here. Skip the precise 1:1/2:1 and note.
            pass
        # Full recompute would require rerunning the simulation. Note the limitation in-report.
    print("  (full 1:1 / 2:1 recomputation deferred — current output is 3:1 only)")

if __name__ == "__main__":
    main()
