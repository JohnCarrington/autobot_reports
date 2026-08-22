"""Q3 — For each Q2 winning trigger-day per variant:
     BANDWALK counterfactual PnL
     minus what actual signal_log fires already captured of the same move.
   Net-of-overlap = counterfactual - existing_capture, per day per variant.
"""
import json
from collections import defaultdict

result = json.load(open('/tmp/q2_bandwalk_result.json'))

# aggregate actual GBPUSD fires per date (any strategy)
day_actual = defaultdict(list)
with open('/opt/tradingbot/logs/signal_log.jsonl') as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('pair') != 'GBPUSD': continue
        d = r.get('timestamp_open','')[:10]
        day_actual[d].append(dict(
            ts=r['timestamp_open'], strat=r['strategy'],
            dir=r['direction'], entry=r['entry'],
            pnl=(r.get('pnl_pips') or 0)
        ))

# per-variant × per-day, compute:
#   trades pnl (counterfactual)
#   actual same-direction pnl (existing capture, all strategies)
#   net-of-overlap
print(f"{'variant':<18s} {'total_ctr':>10s} {'total_actual':>13s} {'net_of_overlap':>15s}  ({'trade_days':>10s})")
overlap = {}
for v, r in result['variants'].items():
    total_ctr = r['total_pnl']
    total_actual = 0.0
    per_day = {}
    for d, info in r['daily'].items():
        fires = day_actual.get(d, [])
        # direction of counterfactual: majority direction of trades on this day
        directions = defaultdict(int)
        for t in r['trades']:
            if t.get('date') == d: directions[t['direction']] += 1
        # take the same-direction actual fires only
        same_dir_pnl = 0.0
        # convert 'BUY'/'SELL' to signal_log's format (already BUY/SELL)
        for f in fires:
            if directions.get(f['dir'],0) > 0:
                same_dir_pnl += (f['pnl'] or 0)
        total_actual += same_dir_pnl
        per_day[d] = dict(ctr=info['pnl'], actual=same_dir_pnl,
                          net=info['pnl'] - same_dir_pnl)
    overlap[v] = dict(total_ctr=total_ctr, total_actual=total_actual,
                      net_of_overlap=total_ctr - total_actual, per_day=per_day)
    print(f"{v:<18s} {total_ctr:>+10.1f} {total_actual:>+13.1f} {total_ctr-total_actual:>+15.1f}  {r['trade_days']:>10d}")

# per-day detail for target days
target_days = ['2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29']
print("\n=== target-day overlap detail ===")
for d in target_days:
    print(f"\n{d}:")
    for v, r in overlap.items():
        if d in r['per_day']:
            info = r['per_day'][d]
            print(f"  {v:<18s} ctr={info['ctr']:+7.1f}  actual={info['actual']:+7.1f}  net={info['net']:+7.1f}")

# on winning trigger-days per variant, average net
print("\n=== winning-trigger-day averages ===")
for v, r in overlap.items():
    wins = [(d,x['net']) for d,x in r['per_day'].items() if x['ctr'] > 0]
    if wins:
        avg = sum(x[1] for x in wins)/len(wins)
        print(f"  {v}: {len(wins)} winning ctr-days, avg net-of-overlap {avg:+.1f}")
    else:
        print(f"  {v}: no winning days")

json.dump(overlap, open('/tmp/q3_overlap_result.json','w'), indent=1, default=str)
