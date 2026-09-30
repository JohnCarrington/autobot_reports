#!/usr/bin/env python3
"""
Indicator analysis for GBPUSD trades on 2026-03-26 and 2026-03-30
"""

import json
import glob
import os
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np

# ─── helpers ──────────────────────────────────────────────────────────────────

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def compute_macd(series, fast=35, slow=45, signal=30):
    e_fast = ema(series, fast)
    e_slow = ema(series, slow)
    macd_line = e_fast - e_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def bb(series, period=20, std=2):
    mid = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    return upper, mid, lower

def bb_pct(close, upper, lower):
    rng = upper - lower
    return ((close - lower) / rng * 100).where(rng > 0, 50)

def ema_alignment(e8, e13, e21):
    if e8 > e13 > e21:
        return "BULLISH"
    elif e8 < e13 < e21:
        return "BEARISH"
    else:
        return "MIXED"

def macd_direction(hist_now, hist_prev):
    if hist_now > hist_prev:
        return "RISING"
    elif hist_now < hist_prev:
        return "FALLING"
    else:
        return "FLAT"

def load_candles(date_str):
    path = f"/opt/tradingbot/data/candles/GBPUSD/{date_str}.csv"
    df = pd.read_csv(path, parse_dates=['timestamp'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.sort_values('timestamp').reset_index(drop=True)
    return df

def load_briefings(date_str):
    pattern = f"/opt/tradingbot/logs/briefing_GBPUSD_{date_str}_*.json"
    files = glob.glob(pattern)
    briefings = []
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        bt = pd.to_datetime(data['briefing_time'], utc=True)
        bias = data.get('daily_bias') or data.get('session_bias', 'UNKNOWN')
        # prefer signal_filter bias direction
        sf = data.get('signal_filter', {})
        allow_buys = sf.get('allow_buys', True)
        allow_sells = sf.get('allow_sells', True)
        if allow_buys and not allow_sells:
            sf_bias = 'BULLISH'
        elif allow_sells and not allow_buys:
            sf_bias = 'BEARISH'
        else:
            sf_bias = 'NEUTRAL'
        briefings.append({
            'briefing_time': bt,
            'session': data.get('session', ''),
            'daily_bias': bias,
            'signal_filter_bias': sf_bias,
        })
    briefings = sorted(briefings, key=lambda x: x['briefing_time'])
    return briefings

def active_briefing(briefings, trade_time_str, date_str):
    """Find most recent briefing before trade time."""
    trade_dt = pd.to_datetime(f"{date_str} {trade_time_str}", utc=True)
    active = None
    for b in briefings:
        if b['briefing_time'] <= trade_dt:
            active = b
        else:
            break
    return active

def prior_12_stats(df, idx):
    """Stats on prior 12 closed candles before index idx."""
    start = max(0, idx - 12)
    prior = df.iloc[start:idx]
    bearish_count = int((prior['close'] < prior['open']).sum())
    net_change = round(prior['close'].iloc[-1] - prior['open'].iloc[0], 1) if len(prior) > 0 else 0
    return bearish_count, net_change

def find_candle_index(df, trade_time_str, date_str):
    """Find index of candle at or just before trade time."""
    trade_dt = pd.to_datetime(f"{date_str} {trade_time_str}", utc=True)
    # find latest candle whose timestamp <= trade_dt
    candidates = df[df['timestamp'] <= trade_dt]
    if len(candidates) == 0:
        return None
    return candidates.index[-1]

# ─── indicator computation ─────────────────────────────────────────────────────

def build_indicators(df):
    # We need history for warm-up — use the whole day plus need enough data
    # Load extra history by stacking previous days
    c = df['close']

    df['ema8']  = ema(c, 8)
    df['ema13'] = ema(c, 13)
    df['ema21'] = ema(c, 21)
    df['ema50'] = ema(c, 50)

    bb_up, bb_mid, bb_lo = bb(c, 20, 2)
    df['bb_upper'] = bb_up
    df['bb_lower'] = bb_lo
    df['bb_pct']   = bb_pct(c, bb_up, bb_lo)

    _, _, df['macd_hist'] = compute_macd(c, 35, 45, 30)

    df['vwap_proxy'] = c.rolling(60).mean()
    return df

# ─── analysis ─────────────────────────────────────────────────────────────────

TRADES = {
    '2026-03-26': [
        (1,  '00:39', 'BRIEFING_SWEEP',     'SELL', +23.7, 'WIN'),
        (2,  '05:49', 'WINDOW_SWEEP',        'BUY',  -15.0, 'LOSS'),
        (3,  '10:09', 'WINDOW_SWEEP',        'SELL', +20.0, 'WIN'),
        (4,  '10:29', 'EMA_PULLBACK',        'BUY',  -12.0, 'LOSS'),
        (5,  '11:24', 'BRIEFING_EXECUTION',  'BUY',  -19.6, 'LOSS'),
        (6,  '13:14', 'WINDOW_SWEEP',        'SELL', -20.0, 'LOSS'),
    ],
    '2026-03-30': [
        (7,  '10:49', 'BRIEFING_SWEEP',      'BUY',  -21.4, 'LOSS'),
        (8,  '13:14', 'BRIEFING_EXECUTION',  'BUY',   -8.3, 'LOSS'),
        (9,  '14:04', 'EMA_PULLBACK',        'SELL',  +3.8, 'WIN'),
    ],
}

def analyse_day(date_str, trades):
    print(f"\n{'='*110}")
    print(f"  GBPUSD  {date_str}")
    print(f"{'='*110}")

    df = load_candles(date_str)
    df = build_indicators(df)
    briefings = load_briefings(date_str)

    # Print briefing times for reference
    print("\n  Briefings loaded:")
    for b in briefings:
        print(f"    {b['session']:15s}  {str(b['briefing_time'])[:19]}  daily_bias={b['daily_bias']}  sf_bias={b['signal_filter_bias']}")

    rows = []
    filter_rows = []

    for (num, time_str, strategy, direction, pnl, outcome) in trades:
        idx = find_candle_index(df, time_str, date_str)
        if idx is None:
            print(f"  [WARN] No candle found for {time_str}")
            continue

        row = df.iloc[idx]
        prev_row = df.iloc[idx - 1] if idx > 0 else row

        # EMA
        e8  = round(row['ema8'],  1)
        e13 = round(row['ema13'], 1)
        e21 = round(row['ema21'], 1)
        e50 = round(row['ema50'], 1)
        stack = ema_alignment(e8, e13, e21)

        # BB%
        bbp = round(row['bb_pct'], 1)

        # MACD
        hist_now  = row['macd_hist']
        hist_prev = prev_row['macd_hist']
        hist_val  = round(hist_now, 3)
        mdir = macd_direction(hist_now, hist_prev)

        # VWAP proxy
        vwap = row['vwap_proxy']
        close = row['close']
        if not np.isnan(vwap):
            vwap_dist = round(close - vwap, 1)
            vwap_rel = f"{'ABOVE' if vwap_dist >= 0 else 'BELOW'} {abs(vwap_dist):.1f}p"
        else:
            vwap_rel = "N/A (warmup)"

        # Prior 12 stats
        p12_bear, p12_net = prior_12_stats(df, idx)

        # Briefing
        ab = active_briefing(briefings, time_str, date_str)
        if ab:
            bias_str = f"{ab['session'][:3].upper()} {ab['signal_filter_bias']}"
        else:
            bias_str = "NONE"

        rows.append({
            '#': num,
            'Time': time_str,
            'Strategy': strategy[:16],
            'Dir': direction,
            'PnL': f"{'+' if pnl > 0 else ''}{pnl}p",
            'EMA Stack': stack,
            'BB%': f"{bbp}%",
            'MACD Hist': hist_val,
            'MACD Dir': mdir,
            'vs VWAP': vwap_rel,
            'Briefing Bias': bias_str,
            'P12 Bear': p12_bear,
            'P12 Net': f"{'+' if p12_net >= 0 else ''}{p12_net}p",
            # internals for filter
            '_direction': direction,
            '_outcome': outcome,
            '_pnl': pnl,
            '_sf_bias': ab['signal_filter_bias'] if ab else 'UNKNOWN',
            '_p12_bear': p12_bear,
            '_mdir': mdir,
        })

    # Print table
    hdr = f"{'#':>2}  {'Time':5}  {'Strategy':16}  {'Dir':4}  {'PnL':8}  {'EMA Stack':8}  {'BB%':6}  {'MACD Hist':10}  {'MACD Dir':8}  {'vs VWAP':14}  {'Briefing Bias':18}  {'P12 Bear':8}  {'P12 Net':8}"
    print(f"\n{hdr}")
    print("-" * len(hdr))
    for r in rows:
        line = (
            f"{r['#']:>2}  {r['Time']:5}  {r['Strategy']:16}  {r['Dir']:4}  {r['PnL']:8}  "
            f"{r['EMA Stack']:8}  {r['BB%']:6}  {r['MACD Hist']:>10}  {r['MACD Dir']:8}  "
            f"{r['vs VWAP']:14}  {r['Briefing Bias']:18}  {r['P12 Bear']:>8}  {r['P12 Net']:>8}"
        )
        print(line)

    # Filter evaluation
    print(f"\n  FILTER EVALUATION")
    print(f"  Filter A = briefing alignment (SELL+BEARISH or BUY+BULLISH)")
    print(f"  Filter B = ≥7/12 prior candles closing in trade direction")
    print(f"  Filter C = MACD histogram moving WITH trade (rising for BUY, falling for SELL)")
    print()
    fhdr = f"  {'#':>2}  {'Time':5}  {'Dir':4}  {'Outcome':4}  {'PnL':8}  {'Filter A':10}  {'Filter B':10}  {'Filter C':10}  {'ALL 3':8}"
    print(fhdr)
    print("  " + "-" * (len(fhdr) - 2))

    wins_kept = 0
    losses_blocked = 0
    total_wins = 0
    total_losses = 0

    for r in rows:
        direction = r['_direction']
        outcome = r['_outcome']
        sf_bias = r['_sf_bias']
        p12_bear = r['_p12_bear']
        mdir = r['_mdir']
        pnl = r['_pnl']

        # Filter A
        if direction == 'SELL' and sf_bias == 'BEARISH':
            fa = 'PASS'
        elif direction == 'BUY' and sf_bias == 'BULLISH':
            fa = 'PASS'
        else:
            fa = 'FAIL'

        # Filter B
        if direction == 'SELL':
            # bearish candles = at least 7
            fb = 'PASS' if p12_bear >= 7 else 'FAIL'
        else:
            # bullish = at least 7 of 12 are bullish = bear count <= 5
            fb = 'PASS' if (12 - p12_bear) >= 7 else 'FAIL'

        # Filter C
        if direction == 'SELL' and mdir == 'FALLING':
            fc = 'PASS'
        elif direction == 'BUY' and mdir == 'RISING':
            fc = 'PASS'
        else:
            fc = 'FAIL'

        all3 = 'PASS' if (fa == 'PASS' and fb == 'PASS' and fc == 'PASS') else 'FAIL'

        if outcome == 'WIN':
            total_wins += 1
            if all3 == 'PASS':
                wins_kept += 1
        else:
            total_losses += 1
            if all3 == 'FAIL':
                losses_blocked += 1

        print(f"  {r['#']:>2}  {r['Time']:5}  {direction:4}  {outcome:4}  {r['PnL']:8}  {fa:10}  {fb:10}  {fc:10}  {all3:8}")

    filter_rows.append((total_wins, wins_kept, total_losses, losses_blocked))
    return total_wins, wins_kept, total_losses, losses_blocked

# ─── main ─────────────────────────────────────────────────────────────────────

totals = {'wins': 0, 'wins_kept': 0, 'losses': 0, 'losses_blocked': 0}

for date_str, trades in TRADES.items():
    tw, wk, tl, lb = analyse_day(date_str, trades)
    totals['wins'] += tw
    totals['wins_kept'] += wk
    totals['losses'] += tl
    totals['losses_blocked'] += lb

print(f"\n{'='*60}")
print(f"  COMBINED SUMMARY (both days, 9 trades)")
print(f"{'='*60}")
print(f"  Total wins : {totals['wins']}")
print(f"  Total losses: {totals['losses']}")
print(f"  Wins kept by all-3 filter  : {totals['wins_kept']} / {totals['wins']}")
print(f"  Losses blocked by all-3    : {totals['losses_blocked']} / {totals['losses']}")
print()
