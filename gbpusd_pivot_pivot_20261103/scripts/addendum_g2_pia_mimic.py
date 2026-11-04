"""Addendum G Part 2 — PIA-mimic trade geometry on pivot events.

PIA's actual trades use tighter geometry than "stop at adjacent pivot":
  * 28/29 Oct BUYs: entry 1.3300 (10p above S1), stop 1.3275 (25p),
    target 1.3375 (+75p, 3:1).
  * 30 Oct / 2 Nov BUYs: entry 1.3350 (near P), stop 1.3325 (25p),
    target 1.3425 (+75p).
  * 3 Nov SELL: entry 1.3442 (near R1), stop 1.3485 (43p), target 1.3313 (-129p, 3:1).
  * 4 Nov BUY: entry 1.3431 (near P), stop 1.3381 (50p), target 1.3581 (+150p, 3:1).

Observed: stops are 25-50p (round-number choices), not structural "at the
adjacent pivot". Targets are 3× stops.

This script simulates PIA-mimic trades at every pivot touch:
  * Entry = pivot_value + SIDE_OFFSET pips (BUY = +5p above S-level, SELL = -5p below R-level, +/-5p offset from P)
  * Stop = PIA-like 25 pips from entry
  * Target = 3 × stop = 75 pips from entry
  * Spread = 1.5p round-trip
  * Horizon = 240 bars

HTF filter variants (declared BEFORE evaluation):
  A — no filter
  B — D1 trend aligned with proposed side (D1 UP for BUY, D1 DOWN for SELL)
  C — B + non-exhausted (consecutive_up_H1 < 8 for BUY; consec_down < 8 for SELL)
  D — explicitly AGAINST D1 trend
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
from collections import defaultdict

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
EVENTS_CSV = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events.csv"
OUT_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_g_pia_mimic_trades.csv"

SPREAD_PIPS = 1.5
STOP_PIPS = 25.0
TARGET_PIPS = 75.0
SIDE_OFFSET_PIPS = 5.0
HORIZON_BARS = 240

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

def simulate(side, entry, stop, target, bars_after):
    if not bars_after: return "UNRESOLVED", None
    s_i = t_i = None
    for i, b in enumerate(bars_after):
        if side == "BUY":
            if s_i is None and b["l"] <= stop: s_i = i
            if t_i is None and b["h"] >= target: t_i = i
        else:
            if s_i is None and b["h"] >= stop: s_i = i
            if t_i is None and b["l"] <= target: t_i = i
        if s_i is not None and t_i is not None: break
    if t_i is not None and (s_i is None or t_i < s_i):
        return "TP", TARGET_PIPS - SPREAD_PIPS
    if s_i is not None:
        return "SL", -STOP_PIPS - SPREAD_PIPS
    return "UNRESOLVED", None

def main() -> None:
    events = list(csv.DictReader(EVENTS_CSV.open()))

    # Day cache
    daily_cache = {}
    for root in (BID_ROOT, MID_ROOT):
        for f in root.glob("*.csv"):
            try: d = dt.date.fromisoformat(f.stem)
            except: continue
            if d not in daily_cache:
                daily_cache[d] = load_day(f)

    d1_dates = sorted(daily_cache.keys())
    d1_close = {d: (daily_cache[d][-1]["c"] if daily_cache[d] else None) for d in d1_dates}

    def d1_trend(date):
        try: idx = d1_dates.index(date)
        except: return "FLAT"
        if idx < 6: return "FLAT"
        p = d1_close.get(d1_dates[idx-1]); f = d1_close.get(d1_dates[idx-6])
        if p is None or f is None: return "FLAT"
        d = (p - f) * 10000.0
        if d >= 30: return "UP"
        if d <= -30: return "DOWN"
        return "FLAT"

    rows_out = []
    for e in events:
        ev_date = dt.date.fromisoformat(e["date"])
        ev_ts = dt.datetime.fromisoformat(e["bar_ts"])
        pivot_name = e["pivot_name"]
        pivot_value = float(e["pivot_value"])

        # Load day bars + next day (for horizon that crosses midnight)
        all_bars = []
        for d_off in (-1, 0, 1):
            d = ev_date + dt.timedelta(days=d_off)
            if d in daily_cache: all_bars.extend(daily_cache[d])
        bars_after = [b for b in all_bars if b["ts"] > ev_ts][:HORIZON_BARS]
        if len(bars_after) < 20: continue

        d1 = d1_trend(ev_date)

        # Proposed side based on pivot role
        if pivot_name in ("S3", "S2", "S1"):
            side = "BUY"
        elif pivot_name in ("R1", "R2", "R3"):
            side = "SELL"
        else:
            # P — follow D1
            if d1 == "UP": side = "BUY"
            elif d1 == "DOWN": side = "SELL"
            else: continue

        # Entry offset
        if side == "BUY":
            entry = pivot_value + SIDE_OFFSET_PIPS / 10000.0
            stop  = entry - STOP_PIPS / 10000.0
            target = entry + TARGET_PIPS / 10000.0
        else:
            entry = pivot_value - SIDE_OFFSET_PIPS / 10000.0
            stop  = entry + STOP_PIPS / 10000.0
            target = entry - TARGET_PIPS / 10000.0

        # Entry triggered? Price must cross entry after the touch bar.
        entry_hit = None
        for b in bars_after:
            if side == "BUY" and b["l"] <= entry:
                entry_hit = b; break
            if side == "SELL" and b["h"] >= entry:
                entry_hit = b; break
        if entry_hit is None:
            rows_out.append({
                "date": e["date"], "pivot_name": pivot_name, "touch_ts": e["bar_ts"],
                "side": side, "d1_trend": d1,
                "is_aligned": int((side == "BUY" and d1 == "UP") or (side == "SELL" and d1 == "DOWN")),
                "entry_triggered": 0,
                "outcome": "NOT_TRIGGERED", "net_pips": "",
            })
            continue

        post_entry = bars_after[bars_after.index(entry_hit):]
        outcome, net = simulate(side, entry, stop, target, post_entry)
        rows_out.append({
            "date": e["date"], "pivot_name": pivot_name, "touch_ts": e["bar_ts"],
            "side": side, "d1_trend": d1,
            "is_aligned": int((side == "BUY" and d1 == "UP") or (side == "SELL" and d1 == "DOWN")),
            "entry_triggered": 1,
            "outcome": outcome, "net_pips": f"{net:+.1f}" if net is not None else "",
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"Wrote {len(rows_out)} rows to {OUT_CSV}")

    def summarise(rows, label):
        trig = [r for r in rows if int(r["entry_triggered"])]
        res = [r for r in trig if r["outcome"] in ("TP", "SL")]
        if not res:
            print(f"  {label:<45} n_trig=0")
            return
        wins = sum(1 for r in res if r["outcome"] == "TP")
        net = sum(float(r["net_pips"]) for r in res)
        unres = sum(1 for r in trig if r["outcome"] == "UNRESOLVED")
        print(f"  {label:<45} n_trig={len(trig):>4}  n_res={len(res):>4}  win%={100*wins/len(res):>5.1f}  total={net:>+7.1f}p  mean={net/len(res):>+5.2f}p  unresolved={unres}")

    print("\n=== PIA-mimic geometry (entry +5p offset, 25p stop, 75p target, 1.5p spread, 240-bar horizon) ===")
    print(f"\n{'Variant':<45}  {'n_trig':>6} {'n_res':>6} {'win%':>5} {'total':>8} {'mean':>7}")

    # A: all pivot entries
    summarise(rows_out, "A — All pivot entries (no HTF filter)")

    # B: D1-aligned
    aligned = [r for r in rows_out if int(r["is_aligned"])]
    summarise(aligned, "B — D1-aligned entries")

    # C: D1-aligned + non-exhausted (from pivot_events: pre_touch MFE large indicates trend was strong)
    # Simplified: take D1-aligned subset and remove rows where touch_ts was at an extreme pivot (S3/R3)
    # (an S3/R3 touch suggests the move has already extended)
    non_exh = [r for r in aligned if r["pivot_name"] not in ("S3", "R3")]
    summarise(non_exh, "C — D1-aligned + non-extreme pivot")

    # D: against D1
    against = [r for r in rows_out if int(r["entry_triggered"])
               and not int(r["is_aligned"])
               and r["d1_trend"] != "FLAT"]
    summarise(against, "D — Against D1 trend")

    # Per-pivot (variant B)
    print("\n=== Per-pivot under variant B (D1-aligned) ===")
    by_piv = defaultdict(list)
    for r in aligned: by_piv[r["pivot_name"]].append(r)
    for pn in PIVOT_NAMES:
        summarise(by_piv.get(pn, []), f"B:{pn}")

    # Per-session (variant B) — session from hour of touch_ts
    print("\n=== Per-session under variant B (D1-aligned) ===")
    def sess(ts_str):
        h = int(ts_str[11:13])
        if 0 <= h < 7:   return "Asia"
        if 7 <= h < 9:   return "LondonOpen"
        if 9 <= h < 12:  return "LondonMorning"
        if 12 <= h < 16: return "LN_NY_Overlap"
        if 16 <= h < 22: return "LateNY"
        return "Off"
    by_sess = defaultdict(list)
    for r in aligned: by_sess[sess(r["touch_ts"])].append(r)
    for s in ("Asia","LondonOpen","LondonMorning","LN_NY_Overlap","LateNY","Off"):
        summarise(by_sess.get(s, []), f"B:{s}")

if __name__ == "__main__":
    main()
