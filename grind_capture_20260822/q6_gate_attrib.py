"""Q6 — Per-gate counterfactual for the 222 killed EMA_PB arms on 6 grind days.
For each gate G in {news_blackout, h1_direction, ribbon_state, velocity_gate,
cooldown, pullback_shape}:
  - Simulation "G disabled, all others active"
  - Fires gained per grind day, PnL per fire (ladder-surrogate exit)
  - Same G disabled on 67 non-grind days: fires gained, PnL
Table: gate × grind-day-counterfactual × normal-day-role.
Thin-flagged.
"""
import csv, json, os, datetime as dt, math
import pandas as pd
import numpy as np
from collections import defaultdict, Counter

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REGIME_LOG = "/opt/tradingbot/logs/regime_engine.jsonl"
FLAT_HHMM = dt.time(20, 40)
COOLDOWN_MIN = 60  # 12 bars of 5m
NEWS_PRE_MIN = 30
NEWS_POST_MIN = 30

TARGET_GRIND = {'2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29'}

# ─── Data ─────────────────────────────────────────────────────────────────

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

# TIER1 event list — for news blackout
tier1 = json.load(open('/tmp/tier3_tier1_dates.json'))
tier1_events = {}
for d, evs in tier1['per_date_labels'].items():
    tier1_events[d] = [dt.datetime.fromisoformat(e[2]) for e in evs]  # ts is idx 2

def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace(' ','T'))

# ─── Indicators ──────────────────────────────────────────────────────────

def ema(s, n):
    return pd.Series(s).ewm(span=n, adjust=False, min_periods=n).mean().values

def _atr14(highs, lows, closes, n=14):
    h = pd.Series(highs); l = pd.Series(lows); c = pd.Series(closes)
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean().values

# ─── Ribbon state approximation (from ribbon_state.py logic) ─────────────
def ribbon_state_at(i, closes, highs, lows, atr_arr):
    """Return one of 'FANNED_UP', 'FANNED_DOWN', 'BRAIDED', 'TRANSITIONAL', 'UNKNOWN'"""
    if i < 60: return 'UNKNOWN'
    e8 = ema(closes[:i+1], 8)[-1]
    e13 = ema(closes[:i+1], 13)[-1]
    e21 = ema(closes[:i+1], 21)[-1]
    e50 = ema(closes[:i+1], 50)[-1]
    if any(np.isnan(x) for x in (e8,e13,e21,e50)): return 'UNKNOWN'
    atr = atr_arr[i]
    if np.isnan(atr) or atr <= 0: return 'UNKNOWN'
    spread = max(e8,e13,e21,e50) - min(e8,e13,e21,e50)
    spread_norm = spread / atr
    # cross count in trailing 12 bars: number of times EMA8 and EMA13 cross
    # approximation: count sign changes of (ema8 - ema13) in trailing 12
    if i < 12+8: cross_count = 0
    else:
        e8s = ema(closes[:i+1], 8)[-12:]
        e13s = ema(closes[:i+1], 13)[-12:]
        diffs = np.sign(np.array(e8s) - np.array(e13s))
        cross_count = int(np.sum(np.abs(np.diff(diffs)) > 0))
    # pitch50 = (e50[t] - e50[t-7]) / atr
    if i < 8: pitch50 = 0
    else:
        e50_now = ema(closes[:i+1], 50)[-1]
        e50_7 = ema(closes[:i-7+1], 50)[-1] if len(closes[:i-7+1]) >= 50 else e50_now
        pitch50 = (e50_now - e50_7) / atr
    # thresholds (ribbon_state defaults)
    FANNED_SPREAD_MIN = 0.35
    FANNED_CROSS_MAX = 3
    PITCH_MIN = 0.05
    BRAIDED_SPREAD_MAX = 0.20
    BRAIDED_CROSS_MIN = 6
    if spread_norm >= FANNED_SPREAD_MIN and cross_count <= FANNED_CROSS_MAX and pitch50 >= PITCH_MIN:
        return 'FANNED_UP'
    if spread_norm >= FANNED_SPREAD_MIN and cross_count <= FANNED_CROSS_MAX and pitch50 <= -PITCH_MIN:
        return 'FANNED_DOWN'
    if spread_norm <= BRAIDED_SPREAD_MAX or cross_count >= BRAIDED_CROSS_MIN:
        return 'BRAIDED'
    return 'TRANSITIONAL'

# ─── Velocity state (JOIN spent-spike detector) ─────────────────────────
def velocity_join_kill(i, closes, highs, lows, atr_arr, direction):
    """Returns True if velocity-gate would SUPPRESS this JOIN entry."""
    if i < 20: return False
    if atr_arr[i] is None or np.isnan(atr_arr[i]) or atr_arr[i] <= 0: return False
    # vel_3 = (close[i] - close[i-3]) / 3
    if i-13 < 0: return False
    vel_3  = (closes[i] - closes[i-3]) / 3.0
    vel_12 = (closes[i] - closes[i-12]) / 12.0
    if abs(vel_12) < 0.15: return False  # DEAD_TAPE
    accel = vel_3 / vel_12 if vel_12 != 0 else 0
    atr_mult = abs(vel_3) / (atr_arr[i] / 5.0)
    dir_of_move = 1 if closes[i] > closes[i-12] else -1
    trade_sign = 1 if direction == 'BUY' else -1
    is_join = (dir_of_move == trade_sign)
    if not is_join: return False
    # gate: atr_mult >= 2.5 AND accel < 0.9 → suppress
    return atr_mult >= 2.5 and accel < 0.9

# ─── News blackout ──────────────────────────────────────────────────────
def news_blackout_kill(ts_dt):
    d = ts_dt.date().isoformat()
    for evt in tier1_events.get(d, []):
        if evt - dt.timedelta(minutes=NEWS_PRE_MIN) <= ts_dt <= evt + dt.timedelta(minutes=NEWS_POST_MIN):
            return True
    return False

# ─── H1 direction ──────────────────────────────────────────────────────
def h1_direction_kill(rows_h1_closes, direction, at_hour_idx):
    """rows_h1_closes: list of H1 close values up to and including current H1 bar.
       direction: 'BUY' or 'SELL'. Returns True if H1 EMA_8 vs EMA_21 opposes direction."""
    if at_hour_idx < 21: return False  # insufficient H1 data — fail open
    e8  = ema(rows_h1_closes[:at_hour_idx+1], 8)[-1]
    e21 = ema(rows_h1_closes[:at_hour_idx+1], 21)[-1]
    if np.isnan(e8) or np.isnan(e21): return False
    sep = e8 - e21
    if abs(sep) < 0.5: return True  # FLAT → kill (no directional signal)
    h1_dir = 'BUY' if sep > 0 else 'SELL'
    return h1_dir != direction

# ─── Pullback-shape approximation ──────────────────────────────────────
def pullback_shape_kill(i, closes, highs, lows, direction, e8, e13, e21):
    """Approximate Gate 5-6: is there a pullback START in the last 5 bars?
    Pullback START (LONG) = a high touching or near ema8 walking back from i-1.
    Also Gate 6: pullback WHOLE hasn't been invalidated (close through ema21)."""
    # look back up to 5 bars
    look_back = 5
    if i < look_back + 5: return False  # insufficient warmup — fail open
    found_start = False
    for j in range(i-1, max(i-look_back-1, 0), -1):
        # pullback start: high >= ema8 (for LONG); low <= ema8 (for SHORT)
        e8_j = e8[j]
        if np.isnan(e8_j): continue
        if direction == 'BUY':
            if highs[j] >= e8_j:
                found_start = True; break
        else:
            if lows[j] <= e8_j:
                found_start = True; break
    if not found_start:
        return True  # no pullback → kill
    # Gate 6: check no invalidation — no close beyond ema21 in the pullback span
    for j in range(i-look_back, i):
        e21_j = e21[j]
        if np.isnan(e21_j): continue
        if direction == 'BUY' and closes[j] < e21_j: return True
        if direction == 'SELL' and closes[j] > e21_j: return True
    return False

# ─── Cooldown ──────────────────────────────────────────────────────────
# handled via last_fire_ts state during simulation loop

# ─── Ladder-surrogate exit simulator (from q2) ─────────────────────────
def simulate_entry(rows, entry_bar_idx, direction, sl_p=12.0):
    if entry_bar_idx >= len(rows): return None
    entry = rows[entry_bar_idx]['close']
    is_long = direction == 'BUY'
    sl = entry - sl_p if is_long else entry + sl_p
    max_price = entry; min_price = entry; no_new = 0
    for j in range(entry_bar_idx+1, len(rows)):
        b = rows[j]
        ts = parse_ts(b['ts'])
        if ts.time() >= FLAT_HHMM:
            exit_px = b['open']
            pnl = (exit_px - entry) if is_long else (entry - exit_px)
            return dict(exit_ts=b['ts'], pnl=pnl, reason='FLAT_2040', j=j)
        if is_long:
            if b['low'] <= sl: return dict(exit_ts=b['ts'], pnl=(sl-entry), reason='SL', j=j)
            fav = b['high'] - entry
        else:
            if b['high'] >= sl: return dict(exit_ts=b['ts'], pnl=(entry-sl), reason='SL', j=j)
            fav = entry - b['low']
        if fav >= 100 and abs(sl-entry) < 75: sl = entry + 75 if is_long else entry - 75
        elif fav >= 60 and abs(sl-entry) < 40: sl = entry + 40 if is_long else entry - 40
        elif fav >= 30 and abs(sl-entry) < 15: sl = entry + 15 if is_long else entry - 15
        elif fav >= 10 and (sl < entry if is_long else sl > entry): sl = entry
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
            return dict(exit_ts=b['ts'], pnl=pnl, reason='EXHAUSTION', j=j)
    b = rows[-1]
    pnl = (b['close']-entry) if is_long else (entry-b['close'])
    return dict(exit_ts=b['ts'], pnl=pnl, reason='EOD', j=len(rows)-1)

# ─── Arm walker with gate attribution ──────────────────────────────────
def walk_day(d, gate_disabled=None):
    rows = load_day(d)
    if not rows: return None, None
    prev_bars = load_prev_bars(d, 200)
    combined = prev_bars + rows
    highs_c  = [b['high']  for b in combined]
    lows_c   = [b['low']   for b in combined]
    closes_c = [b['close'] for b in combined]
    n_prev   = len(prev_bars)
    # 5m ATR
    atr_full = _atr14(highs_c, lows_c, closes_c)
    atr = atr_full[n_prev:]
    # 5m EMAs
    e8_full  = ema(closes_c, 8)
    e13_full = ema(closes_c, 13)
    e21_full = ema(closes_c, 21)
    e50_full = ema(closes_c, 50)
    # slice to today
    e8, e13, e21, e50 = e8_full[n_prev:], e13_full[n_prev:], e21_full[n_prev:], e50_full[n_prev:]
    highs = [b['high'] for b in rows]
    lows  = [b['low']  for b in rows]
    closes = [b['close'] for b in rows]
    # H1 closes: aggregate rows by hour
    h1_closes = []
    h1_last_hour = None
    h1_carry_close = None
    hour_of_bar = []
    for r in combined:
        t = parse_ts(r['ts'])
        if h1_last_hour is None or t.hour != h1_last_hour or t.date() != (h1_last_hour is None and t.date() or None):
            # new hour
            if h1_carry_close is not None:
                h1_closes.append(h1_carry_close)
            h1_last_hour = t.hour
        h1_carry_close = r['close']
    if h1_carry_close is not None:
        h1_closes.append(h1_carry_close)
    # regime for the day
    reg_by_ts = {t:r for t,r in regime_by_day.get(d, [])}
    # arm walk
    arms = []
    for i, b in enumerate(rows):
        t = parse_ts(b['ts'])
        if not (dt.time(6,0) <= t.time() < dt.time(17,0)): continue
        if any(np.isnan(x[i]) for x in (e8,e13,e21,e50)): continue
        # stack
        is_bull = e8[i] > e13[i] > e21[i] > e50[i]
        is_bear = e8[i] < e13[i] < e21[i] < e50[i]
        if not (is_bull or is_bear): continue
        direction = 'BUY' if is_bull else 'SELL'
        # fan gate
        fan = (e8[i]-e50[i]) if is_bull else (e50[i]-e8[i])
        if fan < 3.0: continue
        # entry-bar geometry
        body = b['close'] - b['open']
        if is_bull:
            if body <= 0 or b['close'] <= e8[i]: continue
        else:
            if body >= 0 or b['close'] >= e8[i]: continue
        # regime WIDE
        ts_k = b['ts'][:19].replace(' ','T')
        reg = reg_by_ts.get(ts_k)
        if reg is None: continue
        wide_up = reg in ('STRONG_TREND_UP','TREND_FORMING_UP')
        wide_dn = reg in ('STRONG_TREND_DOWN','TREND_FORMING_DOWN')
        if is_bull and not wide_up: continue
        if is_bear and not wide_dn: continue
        arms.append(dict(i=i, ts=b['ts'], t_utc=t, dir=direction, close=b['close'],
                         high=b['high'], low=b['low'], open=b['open']))
    if not arms: return None, None

    # eval each gate per arm
    # H1 close index of each arm — floor(hour)
    combined_h1 = []
    running_h_close = None
    running_h = None
    combined_h1_hour_of_bar = {}
    for k, r in enumerate(combined):
        t = parse_ts(r['ts'])
        key = (t.year, t.month, t.day, t.hour)
        if running_h != key:
            if running_h is not None:
                combined_h1.append(running_h_close)
            running_h = key
        running_h_close = r['close']
        combined_h1_hour_of_bar[k] = len(combined_h1)  # index of the H1 close for this bar
    combined_h1.append(running_h_close)
    # per arm, look up hourly index — using original index in combined = n_prev + i
    for a in arms:
        combined_idx = n_prev + a['i']
        h1_idx = combined_h1_hour_of_bar.get(combined_idx, 0)
        a['h1_idx'] = h1_idx
    # gate-eval loop
    for a in arms:
        i = a['i']
        # news blackout
        a['news_kill'] = news_blackout_kill(a['t_utc'])
        # H1 direction
        a['h1_kill'] = h1_direction_kill(combined_h1, a['dir'], a['h1_idx'])
        # ribbon
        rb_state = ribbon_state_at(n_prev + i, closes_c, highs_c, lows_c, atr_full)
        a['ribbon_state'] = rb_state
        if rb_state == 'BRAIDED':
            a['ribbon_kill'] = True
        elif rb_state == 'FANNED_UP' and a['dir'] == 'SELL':
            a['ribbon_kill'] = True
        elif rb_state == 'FANNED_DOWN' and a['dir'] == 'BUY':
            a['ribbon_kill'] = True
        else:
            a['ribbon_kill'] = False
        # velocity
        a['velo_kill'] = velocity_join_kill(n_prev + i, closes_c, highs_c, lows_c, atr_full, a['dir'])
        # pullback shape
        a['pb_kill'] = pullback_shape_kill(i, closes, highs, lows, a['dir'], e8, e13, e21)

    return rows, arms

# ─── Counterfactual sim with single-gate-disabled ──────────────────────
GATES = ['news', 'h1', 'ribbon', 'velo', 'pb', 'cooldown']

def sim_with_gates(rows, arms, disabled_gate=None):
    """Return list of fires (with pnl) that survive gates (except disabled).
    Cooldown enforced via 60min inter-fire gap. One-position enforced."""
    fires = []
    last_fire_ts = None
    last_exit_j = -1
    for a in arms:
        # cooldown check
        if disabled_gate != 'cooldown':
            if last_fire_ts is not None and (a['t_utc'] - last_fire_ts).total_seconds() < COOLDOWN_MIN*60:
                continue
        # one-position: last exit must be before entry
        if a['i'] <= last_exit_j: continue
        # gates
        if disabled_gate != 'news' and a['news_kill']: continue
        if disabled_gate != 'h1' and a['h1_kill']: continue
        if disabled_gate != 'ribbon' and a['ribbon_kill']: continue
        if disabled_gate != 'velo' and a['velo_kill']: continue
        if disabled_gate != 'pb' and a['pb_kill']: continue
        # fire on next bar close
        entry_bar = a['i'] + 1
        if entry_bar >= len(rows): continue
        res = simulate_entry(rows, entry_bar, a['dir'])
        if res is None: continue
        fires.append(dict(ts=a['ts'], dir=a['dir'], entry_bar=entry_bar,
                          entry=rows[entry_bar]['close'], **res))
        last_fire_ts = a['t_utc']
        last_exit_j = res['j']
    return fires

# ─── Run ──────────────────────────────────────────────────────────────
print("Building arm attribution across regime-log window...")
results = {}
for d in all_dates:
    rows, arms = walk_day(d)
    if arms is None: continue
    baseline = sim_with_gates(rows, arms, disabled_gate=None)
    per_gate = {}
    for g in GATES:
        per_gate[g] = sim_with_gates(rows, arms, disabled_gate=g)
    results[d] = dict(rows_ct=len(rows), n_arms=len(arms), baseline=baseline, per_gate=per_gate,
                      arms=arms)

# aggregate
def aggregate(gate, days_set):
    total_fires_baseline = 0; total_fires_gate_off = 0
    pnl_baseline = 0.0; pnl_gate_off = 0.0
    n_days = 0
    for d, r in results.items():
        if d not in days_set: continue
        n_days += 1
        total_fires_baseline += len(r['baseline'])
        total_fires_gate_off += len(r['per_gate'][gate])
        pnl_baseline += sum(f['pnl'] for f in r['baseline'])
        pnl_gate_off += sum(f['pnl'] for f in r['per_gate'][gate])
    return dict(n_days=n_days, fires_baseline=total_fires_baseline,
                fires_gate_off=total_fires_gate_off,
                additional_fires=total_fires_gate_off - total_fires_baseline,
                pnl_baseline=pnl_baseline, pnl_gate_off=pnl_gate_off,
                pnl_delta=pnl_gate_off - pnl_baseline)

# grind days summary
print("\n=== per-gate counterfactual: 6 GRIND days ===")
print(f"{'gate':<10s} {'days':>5s} {'fires_base':>10s} {'fires_off':>10s} {'add_fires':>10s} {'pnl_base':>10s} {'pnl_off':>10s} {'pnl_delta':>10s}")
for g in GATES:
    a = aggregate(g, TARGET_GRIND)
    print(f"{g:<10s} {a['n_days']:>5d} {a['fires_baseline']:>10d} {a['fires_gate_off']:>10d} "
          f"{a['additional_fires']:>+10d} {a['pnl_baseline']:>+10.1f} {a['pnl_gate_off']:>+10.1f} {a['pnl_delta']:>+10.1f}")

nongrind_days = set(all_dates) - TARGET_GRIND
print("\n=== per-gate counterfactual: NON-grind days (67 days) ===")
print(f"{'gate':<10s} {'days':>5s} {'fires_base':>10s} {'fires_off':>10s} {'add_fires':>10s} {'pnl_base':>10s} {'pnl_off':>10s} {'pnl_delta':>10s}")
for g in GATES:
    a = aggregate(g, nongrind_days)
    print(f"{g:<10s} {a['n_days']:>5d} {a['fires_baseline']:>10d} {a['fires_gate_off']:>10d} "
          f"{a['additional_fires']:>+10d} {a['pnl_baseline']:>+10.1f} {a['pnl_gate_off']:>+10.1f} {a['pnl_delta']:>+10.1f}")

# per-target-day gate detail
print("\n=== per-grind-day per-gate additional fires + pnl ===")
for d in sorted(TARGET_GRIND):
    r = results.get(d)
    if r is None:
        print(f"  {d}: no data")
        continue
    print(f"\n  {d}  n_arms={r['n_arms']}  baseline_fires={len(r['baseline'])}  baseline_pnl={sum(f['pnl'] for f in r['baseline']):+.1f}")
    for g in GATES:
        fires = r['per_gate'][g]
        pnl = sum(f['pnl'] for f in fires)
        add_fires = len(fires) - len(r['baseline'])
        add_pnl = pnl - sum(f['pnl'] for f in r['baseline'])
        print(f"    gate={g:<10s}  fires={len(fires):>3d} (add {add_fires:+3d})  pnl={pnl:+7.1f} (delta {add_pnl:+7.1f})")

# per-arm gate attribution (kill counts on grind days)
print("\n=== per-gate kill-count on grind days (each arm may trigger multiple gates) ===")
kill_counts = {g: 0 for g in GATES if g != 'cooldown'}
for d in TARGET_GRIND:
    r = results.get(d)
    if r is None: continue
    for a in r['arms']:
        for g, k in [('news','news_kill'),('h1','h1_kill'),('ribbon','ribbon_kill'),
                     ('velo','velo_kill'),('pb','pb_kill')]:
            if a[k]: kill_counts[g] += 1
tot_arms = sum(len(r['arms']) for d,r in results.items() if d in TARGET_GRIND)
print(f"total grind-day arms: {tot_arms}")
for g, ct in kill_counts.items():
    print(f"  {g:<10s} kills {ct:>3d} arms ({ct/max(1,tot_arms)*100:>5.1f}%)")

# save
json.dump({'per_day': {d: dict(n_arms=r['n_arms'],
                               baseline_fires=[{k:v for k,v in f.items() if k!='j'} for f in r['baseline']],
                               per_gate={g:[{k:v for k,v in f.items() if k!='j'} for f in r['per_gate'][g]] for g in GATES},
                               kill_counts_arms=dict(
                                   news=sum(1 for a in r['arms'] if a['news_kill']),
                                   h1=sum(1 for a in r['arms'] if a['h1_kill']),
                                   ribbon=sum(1 for a in r['arms'] if a['ribbon_kill']),
                                   velo=sum(1 for a in r['arms'] if a['velo_kill']),
                                   pb=sum(1 for a in r['arms'] if a['pb_kill']),
                               ))
                        for d,r in results.items()},
           'gates': GATES},
          open('/tmp/q6_gate_attrib.json','w'), indent=1, default=str)
