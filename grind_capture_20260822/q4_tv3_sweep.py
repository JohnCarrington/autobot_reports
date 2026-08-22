"""Q4 — TV3 ER-floor + ER-window sweep.

Variants:
  baseline:  ER≥0.5, window=20 (current live)
  floor_30:  ER≥0.30, window=20
  floor_35:  ER≥0.35, window=20
  floor_40:  ER≥0.40, window=20
  window_40: ER≥0.5, window=40
  window_60: ER≥0.5, window=60
  window_80: ER≥0.5, window=80

Full arm walk: session + spine + regime STRONG_TREND + ADX≥25 + ER_variant.
Report arms on target grind days and false-arms on non-grind days.
"""
import csv, glob, json, os, datetime as dt
import pandas as pd
import numpy as np
from collections import defaultdict, Counter

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REGIME_LOG = "/opt/tradingbot/logs/regime_engine.jsonl"

TARGET_GRIND = {'2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29'}

# regime coverage days
regime_by_day = defaultdict(list)
with open(REGIME_LOG) as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('symbol') != 'GBPUSD': continue
        d = r.get('timestamp','')[:10]
        regime_by_day[d].append((r['timestamp'][:19], r['winning_regime']))
all_dates = sorted(regime_by_day)

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

def load_prev_bars(target, n_needed=200):
    tgt = dt.date.fromisoformat(target)
    bars = []
    for back in range(1, 8):
        pd_ = (tgt - dt.timedelta(days=back)).isoformat()
        p = f'{CANDLES}/{pd_}.csv'
        if not os.path.exists(p): continue
        rows = load_day(pd_)
        bars = rows + bars
        if len(bars) >= n_needed: break
    return bars

def load_prior_dir(target):
    tgt = dt.date.fromisoformat(target)
    for back in range(1,8):
        pd_ = (tgt - dt.timedelta(days=back)).isoformat()
        p = f'{CANDLES}/{pd_}.csv'
        if os.path.exists(p):
            rows = load_day(pd_)
            if len(rows) >= 200:
                return ('UP' if rows[-1]['close'] > rows[0]['close'] else 'DOWN')
    return None

def adx_wilder(highs, lows, closes, n=14):
    highs = pd.Series(highs).astype(float); lows=pd.Series(lows).astype(float); closes=pd.Series(closes).astype(float)
    tr = pd.concat([highs-lows, (highs-closes.shift(1)).abs(), (lows-closes.shift(1)).abs()], axis=1).max(axis=1)
    up_move = highs.diff(); dn_move = -lows.diff()
    plus_dm = ((up_move>dn_move) & (up_move>0)) * up_move
    minus_dm = ((dn_move>up_move) & (dn_move>0)) * dn_move
    atr = tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    plus_di = 100*(plus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr)
    minus_di = 100*(minus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr)
    dx = 100*(plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean().values

def kaufman_er(closes, n):
    c = pd.Series(closes).astype(float)
    net = (c - c.shift(n)).abs()
    vol = c.diff().abs().rolling(n).sum()
    er = net / vol.replace(0, np.nan)
    return er.values

# variants
variants = {
    'baseline':  dict(floor=0.5,  window=20),
    'floor_30':  dict(floor=0.30, window=20),
    'floor_35':  dict(floor=0.35, window=20),
    'floor_40':  dict(floor=0.40, window=20),
    'window_40': dict(floor=0.5,  window=40),
    'window_60': dict(floor=0.5,  window=60),
    'window_80': dict(floor=0.5,  window=80),
}

results = {v: {'grind_arms': defaultdict(list), 'nongrind_arms': defaultdict(list),
                'arms_by_day': defaultdict(list)} for v in variants}

# regime_dates provides scope
for d in all_dates:
    rows = load_day(d)
    if not rows or len(rows) < 40: continue
    prior_dir = load_prior_dir(d)
    prev_bars = load_prev_bars(d, 100)
    combined = prev_bars + rows
    highs = [b['high'] for b in combined]
    lows = [b['low'] for b in combined]
    closes = [b['close'] for b in combined]
    n_prev = len(prev_bars)
    adx_full = adx_wilder(highs, lows, closes)
    adx = adx_full[n_prev:]
    # per-variant ER
    er_by_variant = {v: kaufman_er(closes, cfg['window'])[n_prev:] for v, cfg in variants.items()}
    # regime for the day
    reg_by_ts = {t:r for t,r in regime_by_day[d]}
    # per bar
    for i, b in enumerate(rows):
        t_dt = dt.datetime.fromisoformat(b['ts'].replace(' ','T'))
        # session 07:00 - 20:00 UTC
        if not (dt.time(7,0) <= t_dt.time() < dt.time(20,0)): continue
        if prior_dir not in ('UP','DOWN'): continue
        direction = 'BUY' if prior_dir == 'UP' else 'SELL'
        # regime
        ts_k = b['ts'][:19].replace(' ','T')
        reg = reg_by_ts.get(ts_k)
        if reg is None: continue
        if direction == 'BUY' and reg != 'STRONG_TREND_UP': continue
        if direction == 'SELL' and reg != 'STRONG_TREND_DOWN': continue
        # ADX
        if np.isnan(adx[i]) or adx[i] < 25.0: continue
        # ER varies per variant
        for v, er_arr in er_by_variant.items():
            if not np.isnan(er_arr[i]) and er_arr[i] >= variants[v]['floor']:
                arm_rec = dict(ts=b['ts'], dir=direction, close=b['close'], adx=float(adx[i]), er=float(er_arr[i]))
                results[v]['arms_by_day'][d].append(arm_rec)

# tally per day category
for v in variants:
    arms = results[v]['arms_by_day']
    for d, ll in arms.items():
        if d in TARGET_GRIND:
            results[v]['grind_arms'][d] = ll
        else:
            results[v]['nongrind_arms'][d] = ll

# print summary
print(f"{'variant':<14s} {'floor':>6s} {'window':>6s} "
      f"{'grind_days':>10s} {'grind_arms':>10s} "
      f"{'nongrind_days':>13s} {'nongrind_arms':>13s}")
for v, cfg in variants.items():
    r = results[v]
    g_days = len(r['grind_arms']); g_arms = sum(len(a) for a in r['grind_arms'].values())
    ng_days = len(r['nongrind_arms']); ng_arms = sum(len(a) for a in r['nongrind_arms'].values())
    print(f"{v:<14s} {cfg['floor']:>6.2f} {cfg['window']:>6d} "
          f"{g_days:>10d} {g_arms:>10d} {ng_days:>13d} {ng_arms:>13d}")

# per-target-day per-variant first-arm timing
print("\n=== first-arm times per target grind day ===")
print(f"{'day':<12s} {'dom':<3s} " + "  ".join(f"{v:>12s}" for v in variants))
metrics = json.load(open('/tmp/q1_metrics.json'))
for d in sorted(TARGET_GRIND):
    m = metrics.get(d, {})
    dom_dir = m.get('dom_dir','?'); dom_mag = m.get('dom_mag',0); dom_end = m.get('dom_end_ts','')
    print(f"{d}  {dom_dir:<3s}", end='')
    for v in variants:
        arms = results[v]['arms_by_day'].get(d, [])
        if arms:
            first_arm = arms[0]['ts'][11:16]
            print(f"  {first_arm:>12s}", end='')
        else:
            print(f"  {'—':>12s}", end='')
    print(f"  |  dom_end={dom_end[11:16] if dom_end else '?'}  mag={dom_mag:.0f}p")

# non-grind days: sample of biggest false-arm days
print("\n=== top-5 non-grind days by false-arm count per variant ===")
for v in variants:
    print(f"\n{v}:")
    top = sorted(results[v]['nongrind_arms'].items(), key=lambda kv: -len(kv[1]))[:5]
    for d, arms in top:
        first = arms[0]['ts'][11:16] if arms else '?'
        last = arms[-1]['ts'][11:16] if arms else '?'
        print(f"  {d}  arms={len(arms):3d}  first={first}  last={last}  dir={arms[0]['dir'] if arms else '?'}")

# save
out = {v: {'floor': variants[v]['floor'], 'window': variants[v]['window'],
           'grind_arms': {d: results[v]['grind_arms'][d] for d in results[v]['grind_arms']},
           'nongrind_arms': {d: results[v]['nongrind_arms'][d] for d in results[v]['nongrind_arms']},
           'grind_arms_total': sum(len(a) for a in results[v]['grind_arms'].values()),
           'nongrind_arms_total': sum(len(a) for a in results[v]['nongrind_arms'].values()),
           'grind_days_touched': len(results[v]['grind_arms']),
           'nongrind_days_touched': len(results[v]['nongrind_arms'])}
       for v in variants}
json.dump(out, open('/tmp/q4_tv3_sweep_result.json','w'), indent=1, default=str)
