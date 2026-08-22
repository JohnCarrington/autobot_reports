"""ASSESS_EXPIRED audit — for every LADDER fire that exited via
LADDER_ASSESS_EXPIRED, walk the next 6 and 12 bars to see whether the
rung was cleared (ROBBED — the exit was premature) or the price
reversed (RIGHT — the exit was well-timed).

Definition:
  Take the rung at which assess_expired fired (the current rung from
  the last event before exit). Then in the 6/12 bars AFTER the exit,
  did the price close BEYOND that rung by ≥ 8p in the trade direction?
    - YES = ROBBED (position would have extended, we cut it early)
    - NO  = RIGHT  (price reversed or stayed choppy, we exited before
             bleeding to SL or worse)
"""
import json, os, csv, datetime as dt
from collections import Counter, defaultdict

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
ROBBED_PIPS = 8.0
LOOK_BARS_1 = 6
LOOK_BARS_2 = 12

def load_day(iso):
    p = f'{CANDLES}/{iso}.csv'
    if not os.path.exists(p): return None
    rows = []
    with open(p) as f:
        for r in csv.DictReader(f):
            rows.append(dict(ts=r['timestamp'], open=float(r['open']),
                             high=float(r['high']), low=float(r['low']),
                             close=float(r['close'])))
    return rows

def parse_ts(s):
    s = s.replace(' ','T')
    if s.endswith('Z'): s = s[:-1] + '+00:00'
    return dt.datetime.fromisoformat(s)

processed = json.load(open('/tmp/ladder_real_walk.json'))

# find every assess_expired
audit = []
for r in processed:
    L = r.get('LADDER')
    if not L: continue
    if L['reason'] != 'LADDER_ASSESS_EXPIRED': continue
    # what rung was it? last event where action==RUNNING→ASSESS
    rung_name = None; rung_price = None
    for ev in L.get('events') or []:
        if 'rung' in ev: rung_name = ev.get('rung')
        if 'rung_price' in ev: rung_price = ev.get('rung_price')
    # Look for LADDER_ASSESS_EXPIRED action row for canonical fields
    last_ev = (L.get('events') or [])[-1] if L.get('events') else {}
    if 'rung_price' in last_ev: rung_price = last_ev.get('rung_price')
    if 'rung' in last_ev: rung_name = last_ev.get('rung')
    if rung_price is None:
        # look up from rungs list — first rung is what assess sat on
        if r.get('rungs'):
            first = r['rungs'][0]
            rung_name = first[0]; rung_price = first[1]
    exit_ts = L['exit_ts']
    exit_day = exit_ts[:10]
    rows = load_day(exit_day)
    if rows is None:
        audit.append(dict(fire=r['fire'], exit_ts=exit_ts, rung_name=rung_name,
                          rung_price=rung_price, next6='no_bars', next12='no_bars',
                          verdict='UNKNOWN'))
        continue
    # find exit bar index
    exit_dt = parse_ts(exit_ts)
    exit_idx = None
    for i,b in enumerate(rows):
        if parse_ts(b['ts']) >= exit_dt:
            exit_idx = i; break
    if exit_idx is None:
        audit.append(dict(fire=r['fire'], exit_ts=exit_ts, rung_name=rung_name,
                          rung_price=rung_price, verdict='EOD'))
        continue
    is_buy = r['fire']['direction'] in ('BUY','LONG')
    # walk next N bars and check max/min close vs rung_price
    def check(n):
        end = min(exit_idx + n + 1, len(rows))
        window = rows[exit_idx+1:end]
        if not window: return dict(bars=0, beyond=None, max_favor=None)
        if is_buy:
            max_c = max(b['close'] for b in window)
            beyond = max_c - rung_price if rung_price else None
        else:
            min_c = min(b['close'] for b in window)
            beyond = rung_price - min_c if rung_price else None
        return dict(bars=len(window), beyond=beyond)
    n6 = check(LOOK_BARS_1)
    n12 = check(LOOK_BARS_2)
    # verdict — ROBBED if within 12 bars price cleared rung by ≥ROBBED_PIPS
    verdict = 'RIGHT'
    beyond12 = n12.get('beyond')
    if beyond12 is not None and beyond12 >= ROBBED_PIPS:
        verdict = 'ROBBED'
    audit.append(dict(fire=r['fire'], exit_ts=exit_ts, rung_name=rung_name,
                      rung_price=rung_price, next6=n6, next12=n12,
                      verdict=verdict, actual_pnl=r['fire'].get('actual_pnl'),
                      ladder_pnl=L['pnl']))

# summary
print(f"ASSESS_EXPIRED fires: {len(audit)}")
verdicts = Counter([a['verdict'] for a in audit])
for v, ct in verdicts.most_common():
    print(f"  {v}: {ct}")

# per-verdict PnL
right_ladder = sum(a['ladder_pnl'] for a in audit if a['verdict']=='RIGHT' and a.get('ladder_pnl') is not None)
robbed_ladder = sum(a['ladder_pnl'] for a in audit if a['verdict']=='ROBBED' and a.get('ladder_pnl') is not None)
print(f"\nLADDER pnl on RIGHT: {right_ladder:+.1f}p across {verdicts['RIGHT']} fires")
print(f"LADDER pnl on ROBBED: {robbed_ladder:+.1f}p across {verdicts['ROBBED']} fires")

# how much would robbed have made if extended? — the beyond figure * count
print("\n=== ROBBED detail (rung → 12-bar high beyond) ===")
robbed = [a for a in audit if a['verdict']=='ROBBED']
robbed.sort(key=lambda a: -a['next12'].get('beyond',0))
for a in robbed[:15]:
    f = a['fire']
    print(f"  {f['ts'][:19]} {f['strategy']:26s} {f['direction']:5s} entry={f['entry']} rung={a['rung_name']}@{a['rung_price']}  beyond_12bar={a['next12']['beyond']:+.1f}p  ladder_pnl={a['ladder_pnl']:+.1f}")

print("\n=== RIGHT detail (top 10 by ladder pnl, worst-case if held) ===")
right = [a for a in audit if a['verdict']=='RIGHT']
right.sort(key=lambda a: a['ladder_pnl'])
for a in right[:10]:
    f = a['fire']
    print(f"  {f['ts'][:19]} {f['strategy']:26s} {f['direction']:5s} entry={f['entry']} rung={a['rung_name']}@{a['rung_price']}  beyond_12bar={a['next12'].get('beyond','?')}  ladder_pnl={a['ladder_pnl']:+.1f}")

json.dump(audit, open('/tmp/ladder_assess_audit.json','w'), indent=1, default=str)
