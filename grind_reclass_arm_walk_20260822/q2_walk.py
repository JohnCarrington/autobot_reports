"""Q2 — TREND_V3 and EMA_PULLBACK arm walk across target days.

For each 5m bar in-window on target days, evaluate:
  TREND_V3:
    - session gate (07:00 ≤ ts < 20:00 UTC per env override)
    - daily spine direction (from prior D1 close vs open)
    - regime = STRONG_TREND_UP/DOWN
    - ADX(14) >= 25
    - Kaufman ER(20) >= 0.5
  EMA_PB:
    - session (06:00 ≤ ts < 17:00 UTC default)
    - stack ordered
    - fan (e8-e50) >= 3p
    - entry-bar geometry (bullish/bearish body + close past e8)
    - regime WIDE (STRONG_TREND_UP | TREND_FORMING_UP for LONG)

For each day, per criterion: track "closest approach" (best value observed
during in-session) and per-bar arm/no-arm verdict.
"""
import csv, glob, json, os, datetime as dt
from collections import defaultdict
import pandas as pd
import numpy as np

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REGIME_LOG = "/opt/tradingbot/logs/regime_engine.jsonl"

TARGET_DAYS = ['2026-08-10','2026-08-14',
               '2026-01-05','2026-01-23','2026-04-07','2026-04-13','2026-04-30',
               '2026-06-17','2026-06-18','2026-07-15']

def load_day(d):
    rows = []
    with open(f'{CANDLES}/{d}.csv') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(dict(ts=row['timestamp'], open=float(row['open']),
                             high=float(row['high']), low=float(row['low']),
                             close=float(row['close'])))
    return rows

def load_day_partial(d, start_bar_utc=None):
    return load_day(d)

def load_prior_day(target):
    tgt = dt.date.fromisoformat(target)
    for back in range(1, 8):
        pd_ = tgt - dt.timedelta(days=back)
        p = f'{CANDLES}/{pd_.isoformat()}.csv'
        if os.path.exists(p):
            rows = load_day(pd_.isoformat())
            if len(rows) >= 200:
                # prior daily direction = last close - first close
                d = "UP" if rows[-1]['close'] > rows[0]['close'] else "DOWN"
                return d, pd_.isoformat()
    return None, None

def load_prev_bars(target, n_needed=100):
    """Get bars from previous day(s) so we have warmup for indicators."""
    tgt = dt.date.fromisoformat(target)
    bars = []
    for back in range(1, 6):
        pd_ = (tgt - dt.timedelta(days=back)).isoformat()
        p = f'{CANDLES}/{pd_}.csv'
        if not os.path.exists(p): continue
        rows = load_day(pd_)
        bars = rows + bars
        if len(bars) >= n_needed:
            break
    return bars

def ema(series, n):
    return series.ewm(span=n, adjust=False, min_periods=n).mean()

def adx_wilder(highs, lows, closes, n=14):
    """Wilder ADX (standard). Returns series aligned to input."""
    highs = pd.Series(highs).astype(float)
    lows  = pd.Series(lows).astype(float)
    closes = pd.Series(closes).astype(float)
    tr = pd.concat([
        highs - lows,
        (highs - closes.shift(1)).abs(),
        (lows  - closes.shift(1)).abs(),
    ], axis=1).max(axis=1)
    up_move = highs.diff()
    dn_move = -lows.diff()
    plus_dm = ((up_move > dn_move) & (up_move > 0)) * up_move
    minus_dm = ((dn_move > up_move) & (dn_move > 0)) * dn_move
    # Wilder smoothing (alpha=1/n)
    atr = tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return adx.values, plus_di.values, minus_di.values

def kaufman_er(closes, n=20):
    """Kaufman efficiency ratio = |close-close_n_ago| / sum(|close diffs|) over n."""
    c = pd.Series(closes).astype(float)
    net = (c - c.shift(n)).abs()
    vol = c.diff().abs().rolling(n).sum()
    er = net / vol.replace(0, np.nan)
    return er.values

def load_regime_events(day):
    """Return list of (ts, winning_regime, bias, adx_engine, adx_slope) for day."""
    out = []
    with open(REGIME_LOG) as f:
        for l in f:
            try: r = json.loads(l)
            except: continue
            if r.get('symbol') != 'GBPUSD': continue
            if r.get('timestamp','')[:10] != day: continue
            out.append(dict(ts=r['timestamp'], regime=r['winning_regime'],
                            bias=r.get('directional_bias'),
                            adx_engine=r.get('ADX'),
                            adx_slope=r.get('adx_slope')))
    return out

def evaluate_day(day, tv3_start=dt.time(7,0), tv3_end=dt.time(20,0),
                 emapb_start=dt.time(6,0), emapb_end=dt.time(17,0)):
    prior_dir, prior_date = load_prior_day(day)
    # combine prev-day bars + today's for indicator warmup
    prev_bars = load_prev_bars(day, n_needed=200)
    today = load_day(day)
    if not today: return None
    combined = prev_bars + today
    highs  = [b['high']  for b in combined]
    lows   = [b['low']   for b in combined]
    closes = [b['close'] for b in combined]
    n_prev = len(prev_bars)
    # indicators
    adx_full, pdi_full, ndi_full = adx_wilder(highs, lows, closes)
    er_full = kaufman_er(closes, 20)
    close_s = pd.Series(closes)
    e8_full  = ema(close_s, 8).values
    e13_full = ema(close_s, 13).values
    e21_full = ema(close_s, 21).values
    e50_full = ema(close_s, 50).values
    # slice to today
    adx = adx_full[n_prev:]
    pdi = pdi_full[n_prev:]
    ndi = ndi_full[n_prev:]
    er  = er_full[n_prev:]
    e8  = e8_full[n_prev:]
    e13 = e13_full[n_prev:]
    e21 = e21_full[n_prev:]
    e50 = e50_full[n_prev:]
    # regime by timestamp
    reg_events = load_regime_events(day)
    reg_by_ts = {ev['ts'][:19]: ev for ev in reg_events}
    # walk today's bars
    results = []
    for i, b in enumerate(today):
        ts_full = b['ts']
        # parse to datetime
        t_dt = dt.datetime.fromisoformat(ts_full.replace(" ", "T"))
        t_utc = t_dt.time()
        # timestamp used for regime match (5m bar boundaries)
        ts_key = t_dt.strftime("%Y-%m-%dT%H:%M:%S")
        reg = reg_by_ts.get(ts_key)
        results.append(dict(
            i=i, ts=ts_full,
            t_utc=t_utc,
            close=b['close'], high=b['high'], low=b['low'], open=b['open'],
            adx=float(adx[i]) if not np.isnan(adx[i]) else None,
            pdi=float(pdi[i]) if not np.isnan(pdi[i]) else None,
            ndi=float(ndi[i]) if not np.isnan(ndi[i]) else None,
            er=float(er[i]) if not np.isnan(er[i]) else None,
            e8=float(e8[i]) if not np.isnan(e8[i]) else None,
            e13=float(e13[i]) if not np.isnan(e13[i]) else None,
            e21=float(e21[i]) if not np.isnan(e21[i]) else None,
            e50=float(e50[i]) if not np.isnan(e50[i]) else None,
            regime=(reg['regime'] if reg else None),
            reg_bias=(reg['bias'] if reg else None),
        ))
    return dict(day=day, prior_dir=prior_dir, prior_date=prior_date,
                bars=results, has_regime=(len(reg_events) > 0))

def would_tv3_arm(row, prior_dir, session_end):
    """Return (armed, reasons_failed, direction)."""
    reasons = []
    # session
    session_ok = dt.time(7,0) <= row['t_utc'] < session_end
    if not session_ok: reasons.append("session_gate")
    if prior_dir not in ("UP","DOWN"): reasons.append("no_spine")
    direction = "LONG" if prior_dir == "UP" else "SHORT" if prior_dir == "DOWN" else None
    # regime
    if row['regime'] is None:
        reasons.append("no_regime_data")
    elif direction == "LONG" and row['regime'] != "STRONG_TREND_UP":
        reasons.append(f"regime={row['regime']}!=STRONG_TREND_UP")
    elif direction == "SHORT" and row['regime'] != "STRONG_TREND_DOWN":
        reasons.append(f"regime={row['regime']}!=STRONG_TREND_DOWN")
    # ADX
    if row['adx'] is None or row['adx'] < 25.0:
        reasons.append(f"adx={row['adx']}")
    # ER
    if row['er'] is None or row['er'] < 0.5:
        reasons.append(f"er={row['er']}")
    return len(reasons) == 0, reasons, direction

def would_emapb_arm(row):
    reasons = []
    session_ok = dt.time(6,0) <= row['t_utc'] < dt.time(17,0)
    if not session_ok: reasons.append("session_gate")
    e8,e13,e21,e50 = row['e8'], row['e13'], row['e21'], row['e50']
    if any(x is None for x in (e8,e13,e21,e50)):
        reasons.append("ema_nan")
        return False, reasons, None
    is_bull = e8 > e13 > e21 > e50
    is_bear = e8 < e13 < e21 < e50
    if not (is_bull or is_bear):
        reasons.append("stack_not_ordered")
        return False, reasons, None
    direction = "LONG" if is_bull else "SHORT"
    fan = (e8-e50) if is_bull else (e50-e8)
    if fan < 3.0:
        reasons.append(f"fan={fan:.2f}p<3p")
    # entry bar geometry
    body = row['close'] - row['open']
    if is_bull:
        if body <= 0: reasons.append("entry_not_bullish")
        if row['close'] <= e8: reasons.append("close<=ema8")
    else:
        if body >= 0: reasons.append("entry_not_bearish")
        if row['close'] >= e8: reasons.append("close>=ema8")
    # regime WIDE
    if row['regime'] is None:
        reasons.append("no_regime_data")
    else:
        allowed_long = row['regime'] in ("STRONG_TREND_UP","TREND_FORMING_UP")
        allowed_short = row['regime'] in ("STRONG_TREND_DOWN","TREND_FORMING_DOWN")
        if is_bull and not allowed_long:
            reasons.append(f"regime={row['regime']}!=UP-family")
        if is_bear and not allowed_short:
            reasons.append(f"regime={row['regime']}!=DOWN-family")
    return len(reasons) == 0, reasons, direction

def summarize(day, session_end_tv3=dt.time(20,0)):
    ed = evaluate_day(day, tv3_end=session_end_tv3)
    if ed is None:
        print(f"{day}: NO DATA"); return None
    prior_dir = ed['prior_dir']
    print(f"\n=== {day}  prior_dir={prior_dir} (from {ed['prior_date']}) has_regime={ed['has_regime']} ===")
    # closest approach per criterion, and arm hits
    best_adx = 0; best_adx_ts = None
    best_er = 0;  best_er_ts = None
    tv3_arms = []
    emapb_arms = []
    strong_bars = 0
    # collect per-bar for the in-session windows (only interesting)
    for r in ed['bars']:
        # TV3 session
        in_tv3_sess = dt.time(7,0) <= r['t_utc'] < session_end_tv3
        if in_tv3_sess:
            if r['adx'] and r['adx'] > best_adx:
                best_adx = r['adx']; best_adx_ts = r['ts']
            if r['er']  and r['er']  > best_er:
                best_er  = r['er'];  best_er_ts  = r['ts']
            if r['regime'] and 'STRONG_TREND' in r['regime']:
                strong_bars += 1
        armed_tv3, _, dir_tv3 = would_tv3_arm(r, prior_dir, session_end_tv3)
        if armed_tv3:
            tv3_arms.append(r)
        armed_pb, _, dir_pb = would_emapb_arm(r)
        if armed_pb:
            emapb_arms.append(r)
    print(f"  Session windows: TV3=07:00-{session_end_tv3.strftime('%H:%M')}  EMA_PB=06:00-17:00")
    print(f"  Best in-window ADX(14): {best_adx:.1f} @ {best_adx_ts}  (≥25 needed)")
    print(f"  Best in-window ER(20):  {best_er:.3f} @ {best_er_ts}  (≥0.50 needed)")
    print(f"  In-window STRONG_TREND_* bars: {strong_bars}")
    # regime label summary during TV3 window
    reg_ct = defaultdict(int)
    for r in ed['bars']:
        if dt.time(7,0) <= r['t_utc'] < session_end_tv3 and r['regime']:
            reg_ct[r['regime']] += 1
    if reg_ct:
        print(f"  Regime label distribution in TV3 window: {dict(reg_ct)}")

    # TV3 arms
    print(f"  TV3 arms fired (all criteria met): {len(tv3_arms)}")
    for r in tv3_arms[:6]:
        print(f"     ARM {r['ts']}  dir={'LONG' if prior_dir=='UP' else 'SHORT'}  adx={r['adx']:.1f}  er={r['er']:.3f}  regime={r['regime']}  close={r['close']}")
    # EMA_PB arms
    print(f"  EMA_PB arms fired (all criteria met): {len(emapb_arms)}")
    for r in emapb_arms[:6]:
        e8=r['e8']; e50=r['e50']
        fan = (e8-e50) if e8>e50 else (e50-e8)
        print(f"     ARM {r['ts']}  dir={'LONG' if r['e8']>r['e50'] else 'SHORT'}  fan={fan:.2f}p  close={r['close']}  regime={r['regime']}")
    # Failure diagnostics for TV3: within TV3 window, what fraction of bars
    # failed each criterion?
    print(f"  TV3 per-criterion failure count (over in-session bars):")
    fc = defaultdict(int); tot=0
    for r in ed['bars']:
        if not (dt.time(7,0) <= r['t_utc'] < session_end_tv3): continue
        tot += 1
        armed, reasons, _ = would_tv3_arm(r, prior_dir, session_end_tv3)
        for reason in reasons:
            key = reason.split('=')[0]
            fc[key] += 1
    for k,v in sorted(fc.items(), key=lambda x: -x[1]):
        print(f"     {k:20s}  {v:>3d}/{tot} ({v/max(tot,1)*100:.0f}%)")
    return dict(day=day, prior_dir=prior_dir, has_regime=ed['has_regime'],
                best_adx=best_adx, best_adx_ts=best_adx_ts,
                best_er=best_er, best_er_ts=best_er_ts,
                strong_bars=strong_bars,
                tv3_arms=[(r['ts'], r['adx'], r['er'], r['regime']) for r in tv3_arms],
                emapb_arms=[(r['ts'],) for r in emapb_arms])

all_results = []
for d in TARGET_DAYS:
    r = summarize(d)
    if r: all_results.append(r)

# print a summary table
print("\n\n=== summary matrix ===")
print(f"{'day':<12} {'prior':<5} {'has_reg':<7} {'best_ADX':<10} {'best_ER':<8} {'strong_bars':<12} {'tv3_arms':<9} {'emapb_arms':<10}")
for r in all_results:
    print(f"{r['day']:<12} {str(r['prior_dir'] or '?'):<5} {str(r['has_regime']):<7} {r['best_adx']:<10.1f} {r['best_er']:<8.3f} {r['strong_bars']:<12} {len(r['tv3_arms']):<9} {len(r['emapb_arms']):<10}")

open("/tmp/q2_arm_walk.json","w").write(json.dumps(all_results, indent=1, default=str))
