"""Raw 5m bar sequences for 5 spot-check fires."""
import json, csv, os, datetime as dt

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"

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

def bar_floor(ts_dt):
    m = ts_dt.minute - (ts_dt.minute % 5)
    return ts_dt.replace(minute=m, second=0, microsecond=0)

# 5 chosen fires
CHOSEN = [
    dict(label='(1) BIGGEST LADDER WIN vs ACTUAL',
         ts='2026-07-15T12:05:04Z', strategy='GBPUSD_TREND_V3_L',
         until='2026-07-15T14:00:00Z'),
    dict(label='(2) BIGGEST LADDER LOSS vs ACTUAL',
         ts='2026-07-02T06:30:01Z', strategy='GBPUSD_EMA_PULLBACK_L',
         until='2026-07-02T09:00:00Z'),
    dict(label='(3) ASSESS_EXPIRED = RIGHT (price reversed)',
         ts='2026-06-09T16:40:25Z', strategy='GBPUSD_EMA_PULLBACK_S',
         until='2026-06-09T19:00:00Z'),
    dict(label='(4) ASSESS_EXPIRED = ROBBED (price extended)',
         ts='2026-07-15T11:55:01Z', strategy='GBPUSD_TREND_V3_L',
         until='2026-07-15T14:30:00Z'),
    dict(label='(5) RATCHET OUTLIER (LADDER assessed early)',
         ts='2026-07-15T13:00:05Z', strategy='GBPUSD_TREND_V3_L',
         until='2026-07-15T18:30:00Z'),
]

# load real fire records
by_ts = {}
with open('/tmp/ladder_fires.jsonl') as f:
    for l in f:
        r = json.loads(l)
        by_ts[r['timestamp_open']] = r
walk_by_ts = {}
for r in json.load(open('/tmp/ladder_real_walk.json')):
    walk_by_ts[r['fire']['ts']] = r

for pick in CHOSEN:
    print("=" * 80)
    print(pick['label'])
    print("=" * 80)
    ts_open = pick['ts']
    fire = by_ts.get(ts_open)
    walk = walk_by_ts.get(ts_open)
    if fire is None:
        print("  fire not found")
        continue
    print(f"  timestamp_open: {ts_open}")
    print(f"  strategy      : {fire['strategy']}")
    print(f"  direction     : {fire['direction']}")
    print(f"  entry         : {fire['entry']}")
    print(f"  sl_at_entry   : {fire['sl']}  (sl_pips={fire['sl_pips']})")
    print(f"  tp1_at_entry  : {fire['tp1']} (tp1_pips={fire['tp1_pips']})")
    print(f"  ACTUAL pnl    : {fire['pnl_pips']:+.1f}p  reason={fire['close_reason']}")
    print(f"  ACTUAL exit_ts: {fire['timestamp_close']}  close_price={fire['close_price']}")
    if walk:
        L = walk['LADDER']; R = walk['RATCHET']
        print(f"  LADDER pnl    : {L['pnl']:+.1f}p  reason={L['reason']}  exit_ts={L['exit_ts']}  exit_price={L['exit_price']}")
        print(f"    ladder rungs: {walk['rungs']}")
        print(f"    pivots      : {walk['pivots']}  PDH={walk['pdh']}  PDL={walk['pdl']}  D-1={walk['pd_date']}")
        print(f"    LADDER state transitions:")
        for ev in L['events']:
            print(f"      {ev}")
        print(f"  RATCHET pnl   : {R['pnl']:+.1f}p  reason={R['reason']}  exit_ts={R['exit_ts']}  exit_price={R['exit_price']}")
    # bar sequence
    d = ts_open[:10]
    rows = load_day(d)
    if rows is None:
        print("  candles missing"); continue
    t_start = parse_ts(ts_open)
    t_end = parse_ts(pick['until'])
    print(f"\n  RAW 5m BARS from {t_start.strftime('%H:%M:%S')} → {t_end.strftime('%H:%M:%S')}:")
    print(f"    {'ts_utc':<20s} {'open':>8s} {'high':>8s} {'low':>8s} {'close':>8s}")
    for b in rows:
        bt = parse_ts(b['ts'])
        if bt < bar_floor(t_start) or bt > t_end: continue
        print(f"    {b['ts'][:19]:<20s} {b['open']:>8.2f} {b['high']:>8.2f} {b['low']:>8.2f} {b['close']:>8.2f}")
    print()
