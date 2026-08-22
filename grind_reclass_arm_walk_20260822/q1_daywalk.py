"""Hourly path shape for named days."""
import csv, datetime as dt
from collections import defaultdict

def load_day(d):
    rows = []
    with open(f'/opt/tradingbot/data/candles/GBPUSD/{d}.csv') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append((row['timestamp'], float(row['open']), float(row['high']),
                         float(row['low']), float(row['close'])))
    return rows

def hourly(rows, d):
    by_h = defaultdict(list)
    for ts, o, h, l, c in rows:
        hour = ts[11:13]
        by_h[hour].append((ts, o, h, l, c))
    print(f"\n=== {d}  {len(rows)} bars ===")
    print(f"{'hh':>3s}  n  open   high    low     close   net_h   ranghi_h")
    first_close = rows[0][4]
    for h in sorted(by_h):
        bars = by_h[h]
        h_open = bars[0][1]
        h_high = max(b[2] for b in bars)
        h_low  = min(b[3] for b in bars)
        h_close = bars[-1][4]
        h_net = h_close - h_open
        h_range = h_high - h_low
        cum = h_close - first_close
        print(f"{h:>3s} {len(bars):>2d} {h_open:>7.2f} {h_high:>7.2f} {h_low:>7.2f} {h_close:>7.2f}  {h_net:+6.1f}  r={h_range:5.1f}  cum_from_open={cum:+.1f}")
    # summary
    closes = [b[4] for b in rows]
    highs  = [b[2] for b in rows]
    lows   = [b[3] for b in rows]
    day_range = max(highs) - min(lows)
    day_net = closes[-1] - closes[0]
    close_max_i = max(range(len(closes)), key=lambda i: closes[i])
    close_min_i = min(range(len(closes)), key=lambda i: closes[i])
    close_max = closes[close_max_i]; close_min = closes[close_min_i]
    close_range = close_max - close_min
    excursion_up = closes[close_max_i] - closes[0] if close_max_i > 0 else 0
    excursion_dn = closes[0] - closes[close_min_i] if close_min_i > 0 else 0
    print(f"  day_range={day_range:.1f}  day_net={day_net:+.1f}  net/range={day_net/day_range:+.3f}")
    print(f"  close_max={close_max}@bar {close_max_i} ({rows[close_max_i][0][11:16]})  close_min={close_min}@bar {close_min_i} ({rows[close_min_i][0][11:16]})  close_range={close_range:.1f}")
    print(f"  excursion up from open = {excursion_up:+.1f}  dn from open = {excursion_dn:+.1f}")
    # audit grind test
    grind = (day_range >= 60) and (abs(day_net) >= 0.70*day_range)
    print(f"  audit grind test: range>=60 ({day_range>=60}), |net|/range={abs(day_net)/day_range:.3f} >= 0.70 ({abs(day_net)/day_range>=0.70}) → grind={grind}")

for d in ('2026-08-10','2026-08-14'):
    hourly(load_day(d), d)
