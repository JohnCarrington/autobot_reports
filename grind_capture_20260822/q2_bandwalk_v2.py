"""Q2 v2 — fix trigger time-cap; add K/M sensitivity."""
import csv, json, os, datetime as dt
import pandas as pd
import numpy as np
from collections import Counter, defaultdict

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REGIME_LOG = "/opt/tradingbot/logs/regime_engine.jsonl"
FLAT_HHMM = dt.time(20, 40)
TRIG_CAP  = dt.time(18, 0)  # no new entry after 18:00 UTC (need room to work)

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
    return dt.datetime.fromisoformat(s.replace(" ", "T"))

# regime coverage
regime_dates = set()
regime_by_day = defaultdict(list)
with open(REGIME_LOG) as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('symbol') != 'GBPUSD': continue
        d = r.get('timestamp','')[:10]
        regime_dates.add(d)
        regime_by_day[d].append((r['timestamp'][:19], r['winning_regime']))
all_dates = sorted(regime_dates)

def bb_bands(closes, n=20, k=2):
    c = pd.Series(closes)
    ma = c.rolling(n).mean()
    sd = c.rolling(n).std(ddof=0)
    return (ma + k*sd).values, ma.values, (ma - k*sd).values

def simulate_entry(rows, entry_bar_idx, direction, sl_p=12.0):
    if entry_bar_idx >= len(rows): return None
    entry = rows[entry_bar_idx]['close']
    is_long = direction == 'BUY'
    sl = entry - sl_p if is_long else entry + sl_p
    max_price = entry; min_price = entry
    no_new = 0
    for j in range(entry_bar_idx+1, len(rows)):
        b = rows[j]
        ts = parse_ts(b['ts'])
        if ts.time() >= FLAT_HHMM:
            exit_px = b['open']
            pnl = (exit_px - entry) if is_long else (entry - exit_px)
            return dict(exit_ts=b['ts'], exit_price=exit_px, pnl=pnl, reason='FLAT_2040', j=j)
        if is_long:
            if b['low'] <= sl:
                return dict(exit_ts=b['ts'], exit_price=sl, pnl=(sl-entry), reason='SL', j=j)
            fav = b['high'] - entry
        else:
            if b['high'] >= sl:
                return dict(exit_ts=b['ts'], exit_price=sl, pnl=(entry-sl), reason='SL', j=j)
            fav = entry - b['low']
        # ratchet
        if fav >= 100 and abs(sl-entry) < 75:
            sl = entry + 75 if is_long else entry - 75
        elif fav >= 60 and abs(sl-entry) < 40:
            sl = entry + 40 if is_long else entry - 40
        elif fav >= 30 and abs(sl-entry) < 15:
            sl = entry + 15 if is_long else entry - 15
        elif fav >= 10 and (sl < entry if is_long else sl > entry):
            sl = entry
        # exhaustion
        cur_ext = b['high'] if is_long else b['low']
        if (is_long and cur_ext > max_price) or (not is_long and cur_ext < min_price):
            if is_long: max_price = cur_ext
            else: min_price = cur_ext
            no_new = 0
        else:
            no_new += 1
        beyond_be = (sl > entry) if is_long else (sl < entry)
        if no_new >= 6 and beyond_be:
            exit_px = b['close']
            pnl = (exit_px - entry) if is_long else (entry - exit_px)
            return dict(exit_ts=b['ts'], exit_price=exit_px, pnl=pnl, reason='EXHAUSTION', j=j)
    b = rows[-1]
    pnl = (b['close']-entry) if is_long else (entry-b['close'])
    return dict(exit_ts=b['ts'], exit_price=b['close'], pnl=pnl, reason='EOD', j=len(rows)-1)

def scan_persistence(rows, reg_events, hours_min):
    bars_needed = int(hours_min * 60 / 5)
    reg_by_ts = {t:r for t,r in reg_events}
    bar_regs = []
    last_reg = None
    for b in rows:
        ts_k = b['ts'][:19].replace(' ','T')
        if ts_k in reg_by_ts:
            last_reg = reg_by_ts[ts_k]
        bar_regs.append(last_reg)
    consec_up = [0]*len(rows); consec_dn = [0]*len(rows)
    for i in range(len(rows)):
        consec_up[i] = (consec_up[i-1]+1) if (i>0 and bar_regs[i]=='STRONG_TREND_UP') else (1 if bar_regs[i]=='STRONG_TREND_UP' else 0)
        consec_dn[i] = (consec_dn[i-1]+1) if (i>0 and bar_regs[i]=='STRONG_TREND_DOWN') else (1 if bar_regs[i]=='STRONG_TREND_DOWN' else 0)
    trigs = []
    for i in range(bars_needed-1, len(rows)):
        # cap: don't fire triggers after TRIG_CAP
        if parse_ts(rows[i]['ts']).time() >= TRIG_CAP: continue
        if consec_up[i] >= bars_needed:
            trigs.append((i, 'BUY'))
        if consec_dn[i] >= bars_needed:
            trigs.append((i, 'SELL'))
    return trigs

def scan_bandwalk(rows, K, M):
    closes = [b['close'] for b in rows]
    up, ma, dn = bb_bands(closes, 20, 2)
    trigs = []
    for i in range(M-1, len(rows)):
        if parse_ts(rows[i]['ts']).time() >= TRIG_CAP: continue
        window_closes = closes[i-M+1:i+1]
        window_up = up[i-M+1:i+1]; window_dn = dn[i-M+1:i+1]
        buy_count = sum(1 for j in range(M) if not np.isnan(window_up[j]) and window_closes[j] >= window_up[j])
        sell_count = sum(1 for j in range(M) if not np.isnan(window_dn[j]) and window_closes[j] <= window_dn[j])
        if buy_count >= K:
            trigs.append((i, 'BUY'))
        elif sell_count >= K:
            trigs.append((i, 'SELL'))
    return trigs

def walk_day(rows, trigs):
    trades = []
    if not rows or not trigs: return trades
    cur_exit = -1
    for bar_idx, direction in trigs:
        if bar_idx + 1 <= cur_exit: continue
        if bar_idx + 1 >= len(rows): continue
        # entry time also capped
        entry_bar = bar_idx + 1
        if parse_ts(rows[entry_bar]['ts']).time() >= TRIG_CAP: continue
        res = simulate_entry(rows, entry_bar, direction)
        if res is None: continue
        trades.append(dict(entry_bar=entry_bar, entry_ts=rows[entry_bar]['ts'],
                           entry_price=rows[entry_bar]['close'], direction=direction, **res))
        cur_exit = res['j']
    return trades

variants = {
    'persist_2h':      ('persistence', 2),
    'persist_3h':      ('persistence', 3),
    'bandwalk_8_10':   ('bandwalk', 8, 10),
    'bandwalk_10_12':  ('bandwalk', 10, 12),
    # sensitivity extras
    'bandwalk_6_10':   ('bandwalk', 6, 10),
    'bandwalk_5_8':    ('bandwalk', 5, 8),
}

results = {v: dict(trade_days=0, trades=[], daily={}, total_pnl=0.0) for v in variants}
n_processed = 0
for d in all_dates:
    rows = load_day(d)
    if not rows or len(rows) < 40: continue
    n_processed += 1
    reg_events = regime_by_day[d]
    for vname, cfg in variants.items():
        if cfg[0] == 'persistence':
            trigs = scan_persistence(rows, reg_events, cfg[1])
        else:
            trigs = scan_bandwalk(rows, cfg[1], cfg[2])
        trades = walk_day(rows, trigs)
        if not trades: continue
        day_pnl = sum(t['pnl'] for t in trades)
        results[vname]['trade_days'] += 1
        results[vname]['trades'].extend([{**t, 'date':d} for t in trades])
        results[vname]['daily'][d] = dict(n_trades=len(trades), pnl=day_pnl)
        results[vname]['total_pnl'] += day_pnl

print(f"processed {n_processed} full days")
print(f"\n{'variant':<20s} {'days':>6s} {'trds':>5s} {'total_pnl':>10s} {'avg/day':>8s} {'win_days':>8s} {'wr%':>5s}")
for v, r in results.items():
    trades = r['trades']; n = len(trades)
    wins = sum(1 for t in trades if t['pnl'] > 0)
    win_rate = wins/n*100 if n else 0
    win_days = sum(1 for k,v2 in r['daily'].items() if v2['pnl'] > 0)
    print(f"{v:<20s} {r['trade_days']:>6d} {n:>5d} {r['total_pnl']:>+10.1f} {r['total_pnl']/max(1,r['trade_days']):>+8.1f} {win_days:>8d} {win_rate:>5.1f}")

# overlaps
sets = {v: set(r['daily'].keys()) for v, r in results.items()}
print(f"\ntrigger-day set sizes:")
for k,s in sets.items(): print(f"  {k}: {len(s)}")
print(f"persist_2h ∩ bandwalk_8_10 : {len(sets['persist_2h'] & sets['bandwalk_8_10'])}")
print(f"persist_2h ∪ bandwalk_8_10 : {len(sets['persist_2h'] | sets['bandwalk_8_10'])}")
print(f"persist_3h ∩ bandwalk_10_12: {len(sets['persist_3h'] & sets['bandwalk_10_12'])}")
print(f"persist_2h ∩ bandwalk_6_10 : {len(sets['persist_2h'] & sets['bandwalk_6_10'])}")

# 08-10 test
print(f"\n=== 08-10 flicker test ===")
for v in variants:
    hit = '2026-08-10' in sets[v]
    detail = ''
    if hit:
        info = results[v]['daily']['2026-08-10']
        detail = f" — {info['n_trades']} trades, pnl {info['pnl']:+.1f}"
    print(f"  {v}: {'triggered' if hit else 'no'}{detail}")

# target days per-variant
target_days = ['2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29']
print("\n=== target-day per-variant ===")
for d in target_days:
    print(f"\n{d}:")
    for v, r in results.items():
        if d in r['daily']:
            info = r['daily'][d]
            print(f"  {v}: n_trades={info['n_trades']} pnl={info['pnl']:+.1f}")
            for t in r['trades']:
                if t['date'] == d:
                    print(f"    {t['entry_ts'][11:19]} {t['direction']:5s}@{t['entry_price']:.2f} → {t['exit_ts'][11:19]}@{t['exit_price']:.2f} {t['reason']} pnl={t['pnl']:+.1f}")
        else:
            print(f"  {v}: no trigger")

json.dump({'variants':{v:{'trade_days':r['trade_days'],'total_pnl':r['total_pnl'],
                          'trades':r['trades'], 'daily':r['daily']}
                       for v,r in results.items()},
          'meta':{'n_processed':n_processed,'date_range':[all_dates[0], all_dates[-1]]}},
          open('/tmp/q2_bandwalk_result.json','w'), indent=1, default=str)
