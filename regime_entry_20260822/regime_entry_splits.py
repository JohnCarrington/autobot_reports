"""Splits for regime_entry:
(a) grind vs other (done in main)
(b) net-of-overlap vs actual book (same method as Q3)
(c) time-of-day of losing entries
(d) ladder first-rung save vs flat 12p stop
"""
import json, datetime as dt
from collections import defaultdict, Counter
import csv, os
import numpy as np

result = json.load(open('/tmp/regime_entry_result.json'))
Ns = ['1','2','6']
CANDLES = '/opt/tradingbot/data/candles/GBPUSD'
TARGET_GRIND = {'2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29'}
FLAT_HHMM = dt.time(20, 40)

# ── (b) net-of-overlap vs signal_log ────────────────────────────────
day_actual = defaultdict(list)
with open('/opt/tradingbot/logs/signal_log.jsonl') as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('pair') != 'GBPUSD': continue
        d = r.get('timestamp_open','')[:10]
        day_actual[d].append(dict(dir=r['direction'], pnl=(r.get('pnl_pips') or 0)))

print("=" * 60)
print("(b) Net-of-overlap vs actual book (same method as Q3)")
print("=" * 60)
overlap = {}
for N in Ns:
    r = result[N]
    days = r['days']
    total_ctr = r['total_pnl']
    total_actual = 0.0
    per_day = {}
    for d, info in days.items():
        # direction majority in ctr trades
        dirs = Counter(t['direction'] for t in info['trades'])
        # same-direction actual fires
        same_pnl = sum(f['pnl'] for f in day_actual.get(d, []) if dirs.get(f['dir'],0) > 0)
        total_actual += same_pnl
        per_day[d] = dict(ctr=info['pnl'], actual=same_pnl, net=info['pnl']-same_pnl)
    overlap[N] = dict(total_ctr=total_ctr, total_actual=total_actual,
                      net=total_ctr-total_actual, per_day=per_day)
    print(f"  N={N}: ctr={total_ctr:+.1f}  actual_same_dir={total_actual:+.1f}  net-of-overlap={total_ctr-total_actual:+.1f}")

# per-target-day
print("\nper-target-day net-of-overlap:")
for d in sorted(TARGET_GRIND):
    print(f"  {d}:")
    for N in Ns:
        po = overlap[N]['per_day'].get(d)
        if po:
            print(f"    N={N}: ctr={po['ctr']:+6.1f}  actual={po['actual']:+6.1f}  net={po['net']:+6.1f}")

# ── (c) time-of-day of losing entries ────────────────────────────────
print("\n" + "=" * 60)
print("(c) Time-of-day distribution of LOSING entries")
print("=" * 60)
for N in Ns:
    print(f"\nN={N}:")
    loser_hours = Counter()
    winner_hours = Counter()
    all_hours = Counter()
    for d, info in result[N]['days'].items():
        for t in info['trades']:
            hr = int(t['entry_ts'][11:13])
            all_hours[hr] += 1
            if t['pnl'] < 0: loser_hours[hr] += 1
            elif t['pnl'] > 0: winner_hours[hr] += 1
    print(f"  {'hr':>3s} {'all':>4s} {'winners':>7s} {'losers':>7s} {'net_pnl':>9s}")
    per_hr_pnl = defaultdict(float)
    for d, info in result[N]['days'].items():
        for t in info['trades']:
            hr = int(t['entry_ts'][11:13])
            per_hr_pnl[hr] += t['pnl']
    for hr in range(24):
        if all_hours[hr] == 0: continue
        print(f"  {hr:>2d}:00 {all_hours[hr]:>4d} {winner_hours[hr]:>7d} {loser_hours[hr]:>7d} {per_hr_pnl[hr]:>+9.1f}")

# ── (d) ladder first-rung save vs flat 12p ───────────────────────────
print("\n" + "=" * 60)
print("(d) Ladder first-rung save vs flat 12p — INIT_SL and ratchet accounting")
print("=" * 60)
# For each trade, categorise exit reason and compute counterfactual flat-12p pnl
def load_day(d):
    p = f'{CANDLES}/{d}.csv'
    if not os.path.exists(p): return None
    rows = []
    with open(p) as f:
        for r in csv.DictReader(f):
            rows.append(dict(ts=r['timestamp'], open=float(r['open']),
                             high=float(r['high']), low=float(r['low']),
                             close=float(r['close'])))
    return rows

def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace(' ','T'))

def flat12_pnl(rows, entry_bar, direction):
    """Simulate 12p SL / no trail / hold to 20:40 flat.
    On BUY: sl = entry-12; if bar_low <= sl → exit at sl; else at 20:40 open exit."""
    if entry_bar >= len(rows): return 0.0
    entry = rows[entry_bar]['close']
    is_buy = direction == 'BUY'
    sl = entry - 12 if is_buy else entry + 12
    for j in range(entry_bar+1, len(rows)):
        b = rows[j]
        ts = parse_ts(b['ts'])
        if ts.time() >= FLAT_HHMM:
            exit_px = b['open']
            return (exit_px - entry) if is_buy else (entry - exit_px)
        if is_buy and b['low'] <= sl: return sl - entry
        if not is_buy and b['high'] >= sl: return entry - sl
    # EOD tail
    return (rows[-1]['close']-entry) if is_buy else (entry-rows[-1]['close'])

for N in Ns:
    print(f"\nN={N}:")
    reasons = Counter()
    reason_pnl = defaultdict(float)
    ladder_vs_flat_delta = 0.0
    n_init_sl = n_ratchet = n_reject = n_expired = n_flat = n_ext_exhausted = n_extended = 0
    n_days = 0
    sample_deltas = []
    for d, info in result[N]['days'].items():
        rows = load_day(d)
        if not rows: continue
        n_days += 1
        for t in info['trades']:
            reason = t['reason']
            reasons[reason] += 1
            reason_pnl[reason] += t['pnl']
            if reason == 'INIT_SL': n_init_sl += 1
            if reason == 'LADDER_RATCHET_STOP': n_ratchet += 1
            if reason == 'LADDER_REJECTION': n_reject += 1
            if reason == 'LADDER_ASSESS_EXPIRED': n_expired += 1
            if reason == 'FLAT_2040': n_flat += 1
            if reason == 'EOD_TAIL': n_ext_exhausted += 1
            # compute counterfactual flat-12 pnl
            flat_pnl = flat12_pnl(rows, t['entry_bar'], t['direction'])
            delta = t['pnl'] - flat_pnl
            ladder_vs_flat_delta += delta
            sample_deltas.append(delta)
    print(f"  exit reason counts:")
    for r, ct in reasons.most_common():
        pnl = reason_pnl[r]
        print(f"    {r:<25s}  n={ct:>3d}  pnl={pnl:+7.1f}  avg={pnl/max(1,ct):+.2f}")
    print(f"  ladder_pnl vs flat12_pnl delta: {ladder_vs_flat_delta:+.1f} across {sum(reasons.values())} trades")
    print(f"  ladder saves per trade: {ladder_vs_flat_delta/max(1,sum(reasons.values())):+.2f}")

json.dump(overlap, open('/tmp/regime_entry_overlap.json','w'), indent=1, default=str)
