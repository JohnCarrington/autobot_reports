"""Price LADDER_PATIENT vs LADDER_STANDARD on regime_entry winning days.

Reuses the regime_entry simulator with two variants of the exhaust/assess
policy:
  STANDARD: ASSESS_BARS=3, STOP_BUFFER=3p, exhaustion=r3_close
  PATIENT:  ASSESS_BARS=4, STOP_BUFFER=4p, exhaustion=session_end

Runs both across all trigger days per N ∈ {1,2,6} of regime_entry.
Reports gross PnL per (N, dress) and per-target-day breakdown.
"""
import json, csv, os, datetime as dt
import pandas as pd
import numpy as np
from collections import defaultdict

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REGIME_LOG = "/opt/tradingbot/logs/regime_engine.jsonl"
FLAT_HHMM = dt.time(20, 40)
TRIG_CAP  = dt.time(18, 0)
MAX_REENTRIES = 4
INIT_SL_PIPS = 12.0
AT_LEVEL_PIPS = 5.0
BROKER_MIN_PIPS = 12.0

TARGET_GRIND = {'2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29'}

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

def find_prior_d1(target):
    tgt = dt.date.fromisoformat(target)
    for back in range(1, 8):
        pd_ = (tgt - dt.timedelta(days=back)).isoformat()
        p = f'{CANDLES}/{pd_}.csv'
        if not os.path.exists(p): continue
        rows = load_day(pd_)
        if not rows or len(rows) < 100: continue
        return dict(high=max(b['high'] for b in rows),
                    low=min(b['low'] for b in rows),
                    close=rows[-1]['close'])
    return None

def compute_pivots(pd_):
    H, L, C = pd_['high'], pd_['low'], pd_['close']
    P = (H + L + C) / 3.0
    return dict(P=P, R1=2*P-L, R2=P+(H-L), R3=H+2*(P-L),
                S1=2*P-H, S2=P-(H-L), S3=L-2*(H-P))

def build_rungs(direction, entry_price, pivots, pdh, pdl):
    all_rungs = []
    for name in ('P','R1','R2','R3','S1','S2','S3'):
        if name in pivots:
            all_rungs.append(dict(name=name, price=pivots[name],
                                  cohort='P' if name == 'P' else 'OUTER'))
    if pdh is not None: all_rungs.append(dict(name='PDH', price=pdh, cohort='PDH'))
    if pdl is not None: all_rungs.append(dict(name='PDL', price=pdl, cohort='PDL'))
    if direction == 'BUY':
        seq = [r for r in all_rungs if r['price'] > entry_price]
        seq.sort(key=lambda r: r['price'])
    else:
        seq = [r for r in all_rungs if r['price'] < entry_price]
        seq.sort(key=lambda r: -r['price'])
    return seq

def macd_hist_rising(closes, direction, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal + 5: return None
    s = pd.Series(closes)
    e_fast = s.ewm(span=fast, adjust=False).mean()
    e_slow = s.ewm(span=slow, adjust=False).mean()
    line = e_fast - e_slow
    sig  = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    h_v = hist.iloc[-1]; h_prev = hist.iloc[-2]
    if np.isnan(h_v) or np.isnan(h_prev): return None
    hist_rising = h_v > h_prev
    if direction == 'BUY':
        return bool(hist_rising and h_v > 0)
    else:
        return bool((not hist_rising) and h_v < 0)

def is_rejection_at_rung(direction, o, h, l, c, rung_price):
    rng = h - l
    if rng <= 0: return False
    if direction == 'BUY':
        if not (h > rung_price): return False
        if not (c < rung_price): return False
        return (c - l) <= rng / 3.0
    else:
        if not (l < rung_price): return False
        if not (c > rung_price): return False
        return (h - c) <= rng / 3.0

def simulate_ladder(rows, entry_bar_idx, direction, rungs,
                    assess_bars, stop_buffer_pips, exhaustion,
                    init_sl_pips=INIT_SL_PIPS):
    if entry_bar_idx >= len(rows): return None
    entry = rows[entry_bar_idx]['close']
    is_buy = direction == 'BUY'
    initial_sl = entry - init_sl_pips if is_buy else entry + init_sl_pips
    intended_stop = None
    broker_stop = initial_sl
    rung_idx = 0
    state = 'RUNNING'
    assess_seen = 0
    events = []
    max_price = entry; min_price = entry
    for j in range(entry_bar_idx + 1, len(rows)):
        b = rows[j]
        ts = parse_ts(b['ts'])
        bo, bh, bl, bc = b['open'], b['high'], b['low'], b['close']
        if is_buy and bh > max_price: max_price = bh
        if (not is_buy) and bl < min_price: min_price = bl
        if ts.time() >= FLAT_HHMM:
            pnl = (bo - entry) if is_buy else (entry - bo)
            return dict(exit_bar=j, exit_ts=b['ts'], pnl=pnl, reason='FLAT_2040',
                        events=events, final_rung_idx=rung_idx, final_state=state)
        # intended-stop preemption — with LADDER_PATIENT overlay, skip in EXHAUSTED+session_end
        skip_preempt = (state == 'EXHAUSTED' and exhaustion == 'session_end')
        if intended_stop is not None and not skip_preempt:
            breached = (is_buy and bc < intended_stop) or (not is_buy and bc > intended_stop)
            if breached:
                pnl = (bc - entry) if is_buy else (entry - bc)
                events.append(dict(bar=j, ts=b['ts'], action='LADDER_RATCHET_STOP'))
                return dict(exit_bar=j, exit_ts=b['ts'], pnl=pnl, reason='LADDER_RATCHET_STOP',
                            events=events, final_rung_idx=rung_idx, final_state=state)
        # init 12p SL
        if intended_stop is None:
            hit_sl = (is_buy and bl <= initial_sl) or (not is_buy and bh >= initial_sl)
            if hit_sl:
                pnl = (initial_sl - entry) if is_buy else (entry - initial_sl)
                events.append(dict(bar=j, ts=b['ts'], action='INIT_SL'))
                return dict(exit_bar=j, exit_ts=b['ts'], pnl=pnl, reason='INIT_SL',
                            events=events, final_rung_idx=rung_idx, final_state=state)
        if state == 'EXHAUSTED': continue
        if rung_idx >= len(rungs):
            state = 'EXHAUSTED'; continue
        rung = rungs[rung_idx]
        rung_price = rung['price']
        if is_buy:
            reached = (rung_price - bh) <= AT_LEVEL_PIPS
        else:
            reached = (bl - rung_price) <= AT_LEVEL_PIPS
        if state == 'RUNNING' and not reached: continue
        state_in = state
        if state_in == 'RUNNING':
            state = 'ASSESS'; assess_seen = 1
        else:
            assess_seen += 1
        closes_upto = [rows[k]['close'] for k in range(0, j+1)]
        macd_rise = macd_hist_rising(closes_upto, direction)
        close_beyond = (is_buy and bc > rung_price) or (not is_buy and bc < rung_price)
        rng = bh - bl
        close_top = rng > 0 and (bc - bl) >= (2/3)*rng
        close_bot = rng > 0 and (bh - bc) >= (2/3)*rng
        mom_ext = macd_rise and ((is_buy and close_top) or (not is_buy and close_bot))
        rej = is_rejection_at_rung(direction, bo, bh, bl, bc, rung_price)
        mom_allowed = (state_in != 'RUNNING')
        if close_beyond or (mom_ext and mom_allowed):
            intended_target = rung_price - stop_buffer_pips if is_buy else rung_price + stop_buffer_pips
            if intended_stop is not None:
                if is_buy and intended_stop > intended_target: intended_target = intended_stop
                if not is_buy and intended_stop < intended_target: intended_target = intended_stop
            intended_stop = intended_target
            broker_target = bc - BROKER_MIN_PIPS if is_buy else bc + BROKER_MIN_PIPS
            if broker_stop is not None:
                if is_buy and broker_stop > broker_target: broker_target = broker_stop
                if not is_buy and broker_stop < broker_target: broker_target = broker_stop
            broker_stop = broker_target
            rung_idx += 1
            if rung_idx >= len(rungs):
                state = 'EXHAUSTED'
            else:
                state = 'RUNNING'
                assess_seen = 0
            events.append(dict(bar=j, ts=b['ts'], action='EXTEND',
                               rung_cleared=rung['name']))
            continue
        if rej:
            pnl = (bc - entry) if is_buy else (entry - bc)
            events.append(dict(bar=j, ts=b['ts'], action='LADDER_REJECTION'))
            return dict(exit_bar=j, exit_ts=b['ts'], pnl=pnl, reason='LADDER_REJECTION',
                        events=events, final_rung_idx=rung_idx, final_state=state)
        if assess_seen >= assess_bars:
            pnl = (bc - entry) if is_buy else (entry - bc)
            events.append(dict(bar=j, ts=b['ts'], action='LADDER_ASSESS_EXPIRED'))
            return dict(exit_bar=j, exit_ts=b['ts'], pnl=pnl, reason='LADDER_ASSESS_EXPIRED',
                        events=events, final_rung_idx=rung_idx, final_state=state)
    b = rows[-1]
    pnl = (b['close']-entry) if is_buy else (entry-b['close'])
    return dict(exit_bar=len(rows)-1, exit_ts=b['ts'], pnl=pnl, reason='EOD_TAIL',
                events=events, final_rung_idx=rung_idx, final_state=state)

def find_strong_onsets(rows, reg_events, N):
    reg_by_ts = {t:r for t,r in reg_events}
    bar_regs = []
    last = None
    for b in rows:
        k = b['ts'][:19].replace(' ','T')
        if k in reg_by_ts: last = reg_by_ts[k]
        bar_regs.append(last)
    consec_up = [0]*len(rows); consec_dn = [0]*len(rows)
    for i, r in enumerate(bar_regs):
        consec_up[i] = (consec_up[i-1]+1) if (i>0 and r=='STRONG_TREND_UP') else (1 if r=='STRONG_TREND_UP' else 0)
        consec_dn[i] = (consec_dn[i-1]+1) if (i>0 and r=='STRONG_TREND_DOWN') else (1 if r=='STRONG_TREND_DOWN' else 0)
    onsets = []
    fired_up = False; fired_dn = False
    for i in range(len(rows)):
        if consec_up[i] == N and not fired_up:
            onsets.append((i, 'BUY')); fired_up = True
        elif consec_up[i] < N: fired_up = False
        if consec_dn[i] == N and not fired_dn:
            onsets.append((i, 'SELL')); fired_dn = True
        elif consec_dn[i] < N: fired_dn = False
    return onsets

def walk_day(d, N, reg_events, dress):
    """dress ∈ {'STANDARD', 'PATIENT'}."""
    if dress == 'STANDARD':
        assess_bars = 3; stop_buffer = 3.0; exhaustion = 'r3_close'
    else:
        assess_bars = 4; stop_buffer = 4.0; exhaustion = 'session_end'
    rows = load_day(d)
    if not rows: return None
    onsets = find_strong_onsets(rows, reg_events, N)
    if not onsets: return None
    pd_ = find_prior_d1(d)
    if pd_ is None: return None
    pivots = compute_pivots(pd_)
    pdh, pdl = pd_['high'], pd_['low']
    trades = []
    reentries = defaultdict(int)
    last_exit_bar = -1
    for onset_bar, direction in onsets:
        entry_bar = onset_bar + 1
        if entry_bar >= len(rows): continue
        if entry_bar <= last_exit_bar: continue
        if parse_ts(rows[entry_bar]['ts']).time() >= TRIG_CAP: continue
        if reentries[direction] >= MAX_REENTRIES + 1: continue
        entry_price = rows[entry_bar]['close']
        rungs = build_rungs(direction, entry_price, pivots, pdh, pdl)
        if not rungs:
            trades.append(dict(direction=direction, entry_ts=rows[entry_bar]['ts'],
                              entry_price=entry_price, pnl=0.0, reason='NO_RUNGS'))
            last_exit_bar = entry_bar
            continue
        res = simulate_ladder(rows, entry_bar, direction, rungs,
                              assess_bars, stop_buffer, exhaustion)
        if res is None: continue
        trades.append(dict(direction=direction, entry_ts=rows[entry_bar]['ts'],
                          entry_price=entry_price, **res))
        last_exit_bar = res['exit_bar']
        reentries[direction] += 1
    return dict(date=d, N=N, dress=dress, n_trades=len(trades),
                pnl=sum(t['pnl'] for t in trades), trades=trades)

# regime coverage
regime_by_day = defaultdict(list)
with open(REGIME_LOG) as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('symbol') != 'GBPUSD': continue
        d = r.get('timestamp','')[:10]
        regime_by_day[d].append((r['timestamp'][:19], r['winning_regime']))
all_dates = sorted(regime_by_day)

# run both dresses for each N
results = {(N, dress): {'days': {}, 'total_pnl': 0.0, 'total_trades': 0}
           for N in (1,2,6) for dress in ('STANDARD','PATIENT')}
for d in all_dates:
    for N in (1,2,6):
        for dress in ('STANDARD','PATIENT'):
            r = walk_day(d, N, regime_by_day[d], dress)
            if r is None or not r['trades']: continue
            results[(N,dress)]['days'][d] = r
            results[(N,dress)]['total_pnl'] += r['pnl']
            results[(N,dress)]['total_trades'] += r['n_trades']

# summary
print("=" * 80)
print("LADDER_PATIENT vs LADDER_STANDARD on regime_entry trigger days")
print("=" * 80)
print(f"\n{'N':>2s} {'dress':<9s} {'days':>5s} {'trades':>7s} {'total_pnl':>10s} {'avg/day':>8s}")
for N in (1,2,6):
    for dress in ('STANDARD','PATIENT'):
        r = results[(N, dress)]
        n_days = len(r['days'])
        avg = r['total_pnl']/max(1,n_days)
        print(f"{N:>2d} {dress:<9s} {n_days:>5d} {r['total_trades']:>7d} "
              f"{r['total_pnl']:>+10.1f} {avg:>+8.1f}")

# delta patient - standard
print(f"\n{'N':>2s} {'STANDARD':>10s} {'PATIENT':>10s} {'delta':>10s}")
for N in (1,2,6):
    s = results[(N,'STANDARD')]['total_pnl']
    p = results[(N,'PATIENT')]['total_pnl']
    print(f"{N:>2d} {s:>+10.1f} {p:>+10.1f} {p-s:>+10.1f}")

# grind vs other split, per N per dress
print("\n=== grind vs other (per N per dress) ===")
for N in (1,2,6):
    for dress in ('STANDARD','PATIENT'):
        r = results[(N,dress)]
        g_pnl = sum(r['days'][d]['pnl'] for d in r['days'] if d in TARGET_GRIND)
        o_pnl = sum(r['days'][d]['pnl'] for d in r['days'] if d not in TARGET_GRIND)
        g_n = sum(1 for d in r['days'] if d in TARGET_GRIND)
        o_n = sum(1 for d in r['days'] if d not in TARGET_GRIND)
        print(f"  N={N} {dress:<8s} grind={g_pnl:+7.1f} ({g_n} days)  other={o_pnl:+7.1f} ({o_n} days)")

# per-target-day
print("\n=== per-target-day (patient − standard) ===")
for d in sorted(TARGET_GRIND):
    print(f"\n{d}:")
    for N in (1,2,6):
        s_r = results[(N,'STANDARD')]['days'].get(d)
        p_r = results[(N,'PATIENT')]['days'].get(d)
        s_pnl = s_r['pnl'] if s_r else 0.0
        p_pnl = p_r['pnl'] if p_r else 0.0
        s_n = s_r['n_trades'] if s_r else 0
        p_n = p_r['n_trades'] if p_r else 0
        print(f"  N={N}: STANDARD={s_pnl:+7.1f} ({s_n})  PATIENT={p_pnl:+7.1f} ({p_n})  delta={p_pnl-s_pnl:+7.1f}")

# save
save = {}
for (N, dress), r in results.items():
    save[f"{N}_{dress}"] = dict(total_pnl=r['total_pnl'],
                                total_trades=r['total_trades'],
                                days={d: dict(pnl=x['pnl'], n_trades=x['n_trades'])
                                      for d,x in r['days'].items()})
json.dump(save, open('/tmp/patient_vs_standard.json','w'), indent=1, default=str)
