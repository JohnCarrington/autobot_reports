"""Addendum G extended — Daily vs H4 vs Combined vs Exhaustion.

Re-processes the 1,561 pivot events computing BOTH D1 trend and H4
EMA20 slope SEPARATELY, so variants can be compared:

  A no filter
  B Daily-aligned only
  C H4-aligned only
  D Daily AND H4 agree
  E D1+H4 agreed + non-exhausted (consec_up_H1 < 8 for BUY,
    consec_down_H1 < 8 for SELL)

Geometry: PIA-mimic — entry = pivot ± 5p, stop 25p, target 75p (3:1)
AND a parallel 100p target (4:1). Spread 1.5p round-trip. 240-bar horizon.

Writes csv/addendum_g3_variants_extended.csv.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
from collections import defaultdict

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
EVENTS_CSV = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events.csv"
OUT_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_g3_variants_extended.csv"

SPREAD_PIPS = 1.5
STOP_PIPS = 25.0
SIDE_OFFSET_PIPS = 5.0
HORIZON_BARS = 240

def load_day(path: pathlib.Path) -> list[dict]:
    if not path.exists(): return []
    out = []
    for row in csv.DictReader(path.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try: ts = dt.datetime.fromisoformat(ts_raw)
        except: continue
        out.append({"ts": ts,
                    "o": float(row["open"])/10000.0, "h": float(row["high"])/10000.0,
                    "l": float(row["low"])/10000.0,  "c": float(row["close"])/10000.0})
    return out

def ema(vals, span):
    if not vals: return []
    a = 2.0 / (span + 1.0)
    out = [vals[0]]
    for v in vals[1:]: out.append(a*v + (1-a)*out[-1])
    return out

def aggregate_to(bars, period_minutes):
    if not bars: return []
    out, bucket = [], period_minutes // 5
    i = 0
    while i < len(bars):
        chunk = bars[i:i+bucket]
        if not chunk: break
        out.append({"c": chunk[-1]["c"]})
        i += bucket
    return out

def simulate(side, entry, stop, target_pips, bars_after):
    if not bars_after: return "UNRESOLVED", None
    target = entry + target_pips/10000.0 if side == "BUY" else entry - target_pips/10000.0
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
        return "TP", target_pips - SPREAD_PIPS
    if s_i is not None:
        return "SL", -STOP_PIPS - SPREAD_PIPS
    return "UNRESOLVED", None

def main() -> None:
    events = list(csv.DictReader(EVENTS_CSV.open()))

    daily_cache = {}
    for root in (BID_ROOT, MID_ROOT):
        for f in root.glob("*.csv"):
            try: d = dt.date.fromisoformat(f.stem)
            except: continue
            if d not in daily_cache: daily_cache[d] = load_day(f)
    d1_dates = sorted(daily_cache.keys())
    d1_close = {d: (daily_cache[d][-1]["c"] if daily_cache[d] else None) for d in d1_dates}

    def d1_trend(date):
        try: idx = d1_dates.index(date)
        except: return "FLAT"
        if idx < 6: return "FLAT"
        p = d1_close.get(d1_dates[idx-1]); f5 = d1_close.get(d1_dates[idx-6])
        if p is None or f5 is None: return "FLAT"
        delta = (p - f5) * 10000.0
        if delta >= 30: return "UP"
        if delta <= -30: return "DOWN"
        return "FLAT"

    rows_out = []
    for e in events:
        ev_date = dt.date.fromisoformat(e["date"])
        ev_ts = dt.datetime.fromisoformat(e["bar_ts"])
        pivot_name = e["pivot_name"]
        pivot_value = float(e["pivot_value"])

        # Aggregate warmup bars for H4 slope
        all_bars = []
        for d_off in (-2, -1, 0, 1):
            d = ev_date + dt.timedelta(days=d_off)
            if d in daily_cache: all_bars.extend(daily_cache[d])
        up_to = [b for b in all_bars if b["ts"] <= ev_ts]
        if len(up_to) < 100: continue
        h4 = aggregate_to(up_to, 240)
        h1 = aggregate_to(up_to, 60)
        if len(h4) < 5 or len(h1) < 10: continue
        h4_closes = [b["c"] for b in h4]
        h1_closes = [b["c"] for b in h1]
        h4_ema = ema(h4_closes, 20)
        # Use shorter window where only 5+ bars available
        h4_slope_bars = min(20, len(h4_ema) - 1)
        h4_slope = (h4_ema[-1] - h4_ema[-h4_slope_bars-1]) * 10000.0 if h4_slope_bars > 0 else 0
        h4_trend = "UP" if h4_slope > 30 else "DOWN" if h4_slope < -30 else "FLAT"

        # Exhaustion on H1 (consecutive closes)
        consec_up = consec_down = 0
        for i in range(len(h1_closes) - 1, 0, -1):
            if h1_closes[i] > h1_closes[i-1]:
                if consec_down: break
                consec_up += 1
            elif h1_closes[i] < h1_closes[i-1]:
                if consec_up: break
                consec_down += 1
            else: break

        d1 = d1_trend(ev_date)

        # Proposed side
        if pivot_name in ("S3", "S2", "S1"): side = "BUY"
        elif pivot_name in ("R1", "R2", "R3"): side = "SELL"
        elif pivot_name == "P":
            if d1 == "UP": side = "BUY"
            elif d1 == "DOWN": side = "SELL"
            else: continue
        else: continue

        d1_aligned = (side == "BUY" and d1 == "UP") or (side == "SELL" and d1 == "DOWN")
        h4_aligned = (side == "BUY" and h4_trend == "UP") or (side == "SELL" and h4_trend == "DOWN")
        both_aligned = d1_aligned and h4_aligned

        exhausted = (side == "BUY" and consec_up >= 8) or (side == "SELL" and consec_down >= 8)

        # Entry + stop
        if side == "BUY":
            entry = pivot_value + SIDE_OFFSET_PIPS / 10000.0
            stop  = entry - STOP_PIPS / 10000.0
        else:
            entry = pivot_value - SIDE_OFFSET_PIPS / 10000.0
            stop  = entry + STOP_PIPS / 10000.0

        bars_after = [b for b in all_bars if b["ts"] > ev_ts][:HORIZON_BARS]
        if len(bars_after) < 20: continue

        # Entry trigger
        entry_hit = None
        for b in bars_after:
            if side == "BUY" and b["l"] <= entry: entry_hit = b; break
            if side == "SELL" and b["h"] >= entry: entry_hit = b; break
        if entry_hit is None:
            rows_out.append({
                "date": e["date"], "pivot_name": pivot_name, "touch_ts": e["bar_ts"],
                "side": side, "d1_trend": d1, "h4_trend": h4_trend,
                "d1_aligned": int(d1_aligned), "h4_aligned": int(h4_aligned),
                "both_aligned": int(both_aligned), "exhausted": int(exhausted),
                "entry_triggered": 0,
                "outcome_3R": "NOT_TRIGGERED", "net_3R": "",
                "outcome_4R": "NOT_TRIGGERED", "net_4R": "",
            })
            continue

        post = bars_after[bars_after.index(entry_hit):]
        o3, n3 = simulate(side, entry, stop, 75.0, post)
        o4, n4 = simulate(side, entry, stop, 100.0, post)
        rows_out.append({
            "date": e["date"], "pivot_name": pivot_name, "touch_ts": e["bar_ts"],
            "side": side, "d1_trend": d1, "h4_trend": h4_trend,
            "d1_aligned": int(d1_aligned), "h4_aligned": int(h4_aligned),
            "both_aligned": int(both_aligned), "exhausted": int(exhausted),
            "entry_triggered": 1,
            "outcome_3R": o3, "net_3R": f"{n3:+.1f}" if n3 is not None else "",
            "outcome_4R": o4, "net_4R": f"{n4:+.1f}" if n4 is not None else "",
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"Wrote {len(rows_out)} rows to {OUT_CSV}")

    def summarise(rows, label, outcome_col, net_col, target_pips):
        trig = [r for r in rows if int(r["entry_triggered"])]
        res = [r for r in trig if r[outcome_col] in ("TP", "SL")]
        if not res:
            print(f"  {label:<45} n_trig=0")
            return
        wins = sum(1 for r in res if r[outcome_col] == "TP")
        net = sum(float(r[net_col]) for r in res)
        unres = sum(1 for r in trig if r[outcome_col] == "UNRESOLVED")
        not_trig = sum(1 for r in rows if not int(r["entry_triggered"]))
        be = (STOP_PIPS + SPREAD_PIPS) / (STOP_PIPS + target_pips) * 100  # break-even win%
        print(f"  {label:<45} n={len(res):>4}  win%={100*wins/len(res):>5.1f}  total={net:>+7.1f}p  mean={net/len(res):>+5.2f}p  "
              f"BE%={be:>4.1f}  unres={unres}  not_trig={not_trig}")

    print("\n=== 3:1 RR (75p target, 25p stop, 1.5p spread) — break-even ≈ 26.5% ===")
    summarise(rows_out, "A — no filter", "outcome_3R", "net_3R", 75)
    b_rows = [r for r in rows_out if int(r["d1_aligned"])]
    summarise(b_rows, "B — Daily-aligned", "outcome_3R", "net_3R", 75)
    c_rows = [r for r in rows_out if int(r["h4_aligned"])]
    summarise(c_rows, "C — H4-aligned", "outcome_3R", "net_3R", 75)
    d_rows = [r for r in rows_out if int(r["both_aligned"])]
    summarise(d_rows, "D — Daily AND H4 aligned", "outcome_3R", "net_3R", 75)
    e_rows = [r for r in d_rows if not int(r["exhausted"])]
    summarise(e_rows, "E — Both aligned + non-exhausted", "outcome_3R", "net_3R", 75)
    # Against-D1
    against = [r for r in rows_out if r["d1_trend"] != "FLAT" and not int(r["d1_aligned"])]
    summarise(against, "F — Against D1 (contrarian)", "outcome_3R", "net_3R", 75)

    print("\n=== 4:1 RR (100p target, 25p stop) — break-even ≈ 21.2% ===")
    summarise(rows_out, "A — no filter", "outcome_4R", "net_4R", 100)
    summarise(b_rows, "B — Daily-aligned", "outcome_4R", "net_4R", 100)
    summarise(c_rows, "C — H4-aligned", "outcome_4R", "net_4R", 100)
    summarise(d_rows, "D — Daily AND H4 aligned", "outcome_4R", "net_4R", 100)
    summarise(e_rows, "E — Both aligned + non-exhausted", "outcome_4R", "net_4R", 100)
    summarise(against, "F — Against D1 (contrarian)", "outcome_4R", "net_4R", 100)

    # Variant E per pivot
    print("\n=== Variant E (Both aligned + non-exhausted) per pivot ===")
    by_piv = defaultdict(list)
    for r in e_rows: by_piv[r["pivot_name"]].append(r)
    for pn in ("S3","S2","S1","P","R1","R2","R3"):
        summarise(by_piv.get(pn, []), f"E:{pn} (3R)", "outcome_3R", "net_3R", 75)

if __name__ == "__main__":
    main()
