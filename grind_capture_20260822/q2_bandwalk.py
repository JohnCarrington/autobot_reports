"""Q2 — Price TREND_BANDWALK variants across regime-log window.

Two triggers × parameter grid:
 (a) Label-persistence: STRONG_TREND_* held ≥ N hours continuously.
     Params: N ∈ {2h, 3h}
 (b) Band-walk: K of last M 5m closes ≥ upper BB (BUY) / ≤ lower BB (SELL).
     Params: K/M ∈ {8/10, 10/12}

Common entry/exit:
 - Entry at next 5m close after trigger fires; direction = trend direction
 - Stop-loss = 12 p from entry
 - Ladder surrogate:
    * SL moves to BE (entry) when +10 p reached
    * SL moves to +15 p when +30 p reached
    * SL moves to +40 p when +60 p reached
    * SL moves to +75 p when +100 p reached
 - Exhaustion: if 6 consecutive bars fail to make new favourable extreme
   AND we're beyond BE → flat at that bar's close
 - Hard flat 20:40 UTC
 - One position at a time; re-entry allowed only if trigger fires anew
"""
import csv, glob, json, os, datetime as dt
import pandas as pd
import numpy as np
from collections import Counter, defaultdict

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REGIME_LOG = "/opt/tradingbot/logs/regime_engine.jsonl"
FLAT_HHMM = dt.time(20, 40)

def load_day(d):
    rows = []
    p = f'{CANDLES}/{d}.csv'
    if not os.path.exists(p): return None
    with open(p) as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(dict(ts=row['timestamp'], open=float(row['open']),
                             high=float(row['high']), low=float(row['low']),
                             close=float(row['close'])))
    return rows

def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace(" ", "T"))

# ── enumerate available regime-log days ─────────────────────────────────
regime_dates = set()
with open(REGIME_LOG) as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('symbol') != 'GBPUSD': continue
        regime_dates.add(r.get('timestamp','')[:10])
all_dates = sorted(regime_dates)
print(f"regime-log days: {len(all_dates)}  {all_dates[0]} .. {all_dates[-1]}")

# ── load per-day regime events (winning_regime by 5m bar) ───────────────
regime_by_day = defaultdict(list)  # date -> [(ts_key, winning_regime)]
with open(REGIME_LOG) as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('symbol') != 'GBPUSD': continue
        d = r.get('timestamp','')[:10]
        ts = r['timestamp'][:19]
        regime_by_day[d].append((ts, r['winning_regime']))

# ── Bollinger 20,2 on 5m closes ─────────────────────────────────────────
def bb_bands(closes, n=20, k=2):
    c = pd.Series(closes)
    ma = c.rolling(n).mean()
    sd = c.rolling(n).std(ddof=0)
    return (ma + k*sd).values, ma.values, (ma - k*sd).values

# ── Simulator ───────────────────────────────────────────────────────────
def simulate_entry(rows, entry_bar_idx, direction, sl_p=12.0):
    """Walk bars from entry_bar_idx (position opens at that bar's close).
    Returns dict(exit_ts, exit_price, pnl, reason)."""
    if entry_bar_idx >= len(rows): return None
    entry = rows[entry_bar_idx]['close']
    is_long = direction == 'BUY'
    sl = entry - sl_p if is_long else entry + sl_p
    # tiered ratchet
    max_fav = 0.0
    # exhaustion: consecutive bars no new fav extreme
    no_new_ext_bars = 0
    max_price = entry if is_long else entry
    min_price = entry if is_long else entry
    for j in range(entry_bar_idx + 1, len(rows)):
        b = rows[j]
        ts = parse_ts(b['ts'])
        # flat at 20:40
        if ts.time() >= FLAT_HHMM:
            exit_px = b['open']
            pnl = (exit_px - entry) if is_long else (entry - exit_px)
            return dict(exit_ts=b['ts'], exit_price=exit_px, pnl=pnl, reason='FLAT_2040', j=j)
        # SL / BE check (using bar's H/L)
        if is_long:
            if b['low'] <= sl:
                return dict(exit_ts=b['ts'], exit_price=sl, pnl=(sl-entry), reason='SL', j=j)
            fav = b['high'] - entry
        else:
            if b['high'] >= sl:
                return dict(exit_ts=b['ts'], exit_price=sl, pnl=(entry-sl), reason='SL', j=j)
            fav = entry - b['low']
        # ratchet SL
        if fav >= 100 and (sl - entry if is_long else entry - sl) < 75:
            sl = entry + 75 if is_long else entry - 75
        elif fav >= 60 and (sl - entry if is_long else entry - sl) < 40:
            sl = entry + 40 if is_long else entry - 40
        elif fav >= 30 and (sl - entry if is_long else entry - sl) < 15:
            sl = entry + 15 if is_long else entry - 15
        elif fav >= 10 and (sl - entry if is_long else entry - sl) < 0:
            sl = entry
        # exhaustion check
        cur_ext = b['high'] if is_long else b['low']
        max_ext = max_price if is_long else min_price
        if (is_long and cur_ext > max_ext) or (not is_long and cur_ext < max_ext):
            if is_long: max_price = cur_ext
            else: min_price = cur_ext
            no_new_ext_bars = 0
        else:
            no_new_ext_bars += 1
        # exhaustion trigger: 6 bars no new extreme AND position beyond BE
        beyond_be = (sl > entry) if is_long else (sl < entry)
        if no_new_ext_bars >= 6 and beyond_be:
            exit_px = b['close']
            pnl = (exit_px - entry) if is_long else (entry - exit_px)
            return dict(exit_ts=b['ts'], exit_price=exit_px, pnl=pnl, reason='EXHAUSTION', j=j)
    # walked past end of file: flat at last close
    b = rows[-1]
    exit_px = b['close']
    pnl = (exit_px - entry) if is_long else (entry - exit_px)
    return dict(exit_ts=b['ts'], exit_price=exit_px, pnl=pnl, reason='EOD', j=len(rows)-1)

# ── Trigger scanners ─────────────────────────────────────────────────────
def scan_persistence(rows, regime_events, hours_min):
    """Find first bar-idx where regime has been STRONG_TREND continuously for ≥ hours_min.
    Returns list of (trigger_bar_idx, direction) events (allows re-entry after SL).
    """
    bars_needed = int(hours_min * 60 / 5)
    # map ts→regime for this day; interpolate missing bars as previous regime
    reg_by_ts = {t: r for t, r in regime_events}
    # build per-bar regime series
    bar_regs = []
    last_reg = None
    for b in rows:
        ts = b['ts'][:19].replace(' ', 'T')
        if ts in reg_by_ts:
            last_reg = reg_by_ts[ts]
        bar_regs.append(last_reg)
    # sliding: how many consecutive STRONG_TREND_UP bars up to bar i
    consec_up = [0]*len(rows); consec_dn = [0]*len(rows)
    for i, r in enumerate(bar_regs):
        consec_up[i] = (consec_up[i-1]+1) if (i>0 and r == 'STRONG_TREND_UP') else (1 if r == 'STRONG_TREND_UP' else 0)
        consec_dn[i] = (consec_dn[i-1]+1) if (i>0 and r == 'STRONG_TREND_DOWN') else (1 if r == 'STRONG_TREND_DOWN' else 0)
    trigs = []
    for i in range(bars_needed, len(rows)):
        if consec_up[i] >= bars_needed:
            trigs.append((i, 'BUY'))
        if consec_dn[i] >= bars_needed:
            trigs.append((i, 'SELL'))
    return trigs

def scan_bandwalk(rows, K, M):
    """Find bars where in the trailing M closes, K or more are beyond the
    trend-side outer band (BB(20,2)).  Direction inferred from side.
    """
    closes = [b['close'] for b in rows]
    up, ma, dn = bb_bands(closes, 20, 2)
    trigs = []
    for i in range(M-1, len(rows)):
        window_closes = closes[i-M+1:i+1]
        window_up = up[i-M+1:i+1]
        window_dn = dn[i-M+1:i+1]
        # count closes >= up (buy side) or <= dn (sell side)
        buy_count = sum(1 for j in range(M) if not np.isnan(window_up[j]) and window_closes[j] >= window_up[j])
        sell_count = sum(1 for j in range(M) if not np.isnan(window_dn[j]) and window_closes[j] <= window_dn[j])
        if buy_count >= K:
            trigs.append((i, 'BUY'))
        elif sell_count >= K:
            trigs.append((i, 'SELL'))
    return trigs

# ── Full walk with re-entry ─────────────────────────────────────────────
def walk_day(rows, trigs):
    """Given trigger events (bar_idx, direction), walk with 1-position-at-a-time.
    Re-enter when a new trigger fires AFTER the current position exits AND
    the trigger's direction is the trend direction at that point."""
    trades = []
    if not rows or not trigs: return trades
    # normalise: keep triggers sorted, allow re-entry after exit if trigger still true
    i_trig = 0
    n_trigs = len(trigs)
    cur_exit_j = -1
    for (bar_idx, direction) in trigs:
        # entry deferred to next bar close
        if bar_idx + 1 > cur_exit_j and bar_idx + 1 < len(rows):
            entry_bar = bar_idx + 1
            res = simulate_entry(rows, entry_bar, direction)
            if res is None: continue
            trade = dict(entry_bar=entry_bar, entry_ts=rows[entry_bar]['ts'],
                         entry_price=rows[entry_bar]['close'],
                         direction=direction, **res)
            trades.append(trade)
            cur_exit_j = res['j']
    return trades

# ── Run all variants ─────────────────────────────────────────────────────
variants = {
    'persist_2h':  ('persistence', 2),
    'persist_3h':  ('persistence', 3),
    'bandwalk_8_10': ('bandwalk', 8, 10),
    'bandwalk_10_12': ('bandwalk', 10, 12),
}

results = {v: {'trade_days': 0, 'trades': [], 'daily': {}, 'total_pnl': 0.0}
           for v in variants}

n_days_processed = 0
for d in all_dates:
    rows = load_day(d)
    if not rows or len(rows) < 40:
        continue
    n_days_processed += 1
    reg_events = regime_by_day[d]
    for vname, cfg in variants.items():
        if cfg[0] == 'persistence':
            trigs = scan_persistence(rows, reg_events, cfg[1])
        else:  # bandwalk
            trigs = scan_bandwalk(rows, cfg[1], cfg[2])
        if not trigs:
            continue
        trades = walk_day(rows, trigs)
        if not trades:
            continue
        day_pnl = sum(t['pnl'] for t in trades)
        results[vname]['trade_days'] += 1
        results[vname]['trades'].extend([{**t, 'date': d} for t in trades])
        results[vname]['daily'][d] = dict(n_trades=len(trades), pnl=day_pnl)
        results[vname]['total_pnl'] += day_pnl

print(f"\nprocessed {n_days_processed} full days from regime-log window")

# summary
print(f"\n{'variant':<20s} {'trade_days':>10s} {'trades':>6s} {'total_pnl':>10s} {'avg/day':>8s} {'win_days':>8s}")
for v, r in results.items():
    trades = r['trades']
    wins = sum(1 for t in trades if t['pnl'] > 0)
    n = len(trades)
    win_rate = wins/n*100 if n else 0
    n_days = r['trade_days']
    avg_day = r['total_pnl']/max(1,n_days)
    win_days = sum(1 for k,v2 in r['daily'].items() if v2['pnl'] > 0)
    print(f"{v:<20s} {n_days:>10d} {n:>6d} {r['total_pnl']:>+10.1f} {avg_day:>+8.1f} {win_days:>8d}")

# overlap between (a) and (b)
sets = {v: set(r['daily'].keys()) for v, r in results.items()}
print(f"\ntrigger-day set sizes: " + ", ".join(f"{k}={len(v)}" for k,v in sets.items()))
print(f"persist_2h ∩ bandwalk_8_10 : {len(sets['persist_2h'] & sets['bandwalk_8_10'])}")
print(f"persist_2h ∪ bandwalk_8_10 : {len(sets['persist_2h'] | sets['bandwalk_8_10'])}")
print(f"persist_3h ∩ bandwalk_10_12: {len(sets['persist_3h'] & sets['bandwalk_10_12'])}")
print(f"persist_3h ∪ bandwalk_10_12: {len(sets['persist_3h'] | sets['bandwalk_10_12'])}")

# 08-10 flicker test — did bandwalk trigger where persistence didn't?
print(f"\n=== 08-10 flicker test ===")
for v in variants:
    hit = '2026-08-10' in sets[v]
    print(f"  {v}: {'triggered' if hit else 'no'}")

# save full detail
json.dump({'variants': {v: {'trade_days': r['trade_days'],
                            'total_pnl': r['total_pnl'],
                            'trades': [{**t, 'date':t.get('date')} for t in r['trades']],
                            'daily': r['daily']}
                       for v,r in results.items()},
           'meta': {'n_days_processed': n_days_processed,
                    'date_range': [all_dates[0], all_dates[-1]]}},
          open('/tmp/q2_bandwalk_result.json','w'), indent=1, default=str)

# save target-day detail for later Q3
target_days = ['2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29']
print(f"\n=== target-day per-variant detail ===")
for d in target_days:
    print(f"\n--- {d} ---")
    for v, r in results.items():
        if d in r['daily']:
            info = r['daily'][d]
            print(f"  {v}: n_trades={info['n_trades']} pnl={info['pnl']:+.1f}")
            # per-trade
            for t in r['trades']:
                if t['date'] == d:
                    print(f"    entry {t['entry_ts'][11:19]} {t['direction']:5s} @{t['entry_price']:.2f}  exit {t['exit_ts'][11:19]} @{t['exit_price']:.2f}  reason={t['reason']} pnl={t['pnl']:+.1f}")
        else:
            print(f"  {v}: no trigger")
