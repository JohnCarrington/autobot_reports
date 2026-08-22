"""Ladder Real Fires — walk every real GBPUSD ladder-enrolled fire
through three exit columns and produce the per-fire table.

Column (a) ACTUAL: from signal_log — no simulation.
Column (b) LADDER v3: bar-walk via shipped state machine (level_ladder.py).
Column (c) TIERED RATCHET: BE+10 / +15@+30 / +40@+60 / +75@+100 /
                          exhaustion at 6 no-new-extreme bars / session flat.

Cited rules for LADDER v3 (level_ladder.py at HEAD):
  :155-158  constants (AT_LEVEL_PIPS=5, ASSESS_BARS=3, STOP_BUFFER=3p)
  :325-361  _build_rung_sequence (pivots + PDH/PDL, nearest-first)
  :433-471  _is_rejection_at_rung  (pierce + close-back + close-loc/3)
  :498-510  states RUNNING/AT_LEVEL/ASSESS/EXHAUSTED/CLOSED
  :719-749  intended-stop preemption (before state work)
  :753-757  EXHAUSTED holds
  :777-781  AT_LEVEL check
  :786-787  close_beyond EXTEND primary
  :790-799  momentum_extend (MACD rising + close in top/bot 1/3)
  :860      momentum_extend_allowed only from ASSESS (not RUNNING)
  :862-914  EXTEND: intended_stop = cleared_rung ± STOP_BUFFER
  :916-923  rejection close
  :924-931  assess_expired close
  :900-903  final rung → EXHAUSTED
Initial 12p SL from operator spec (matches TREND_V3_UM MAX_SL_PIPS=12).

Surrogate error sources:
  1. Standard pivots vs bb_pd_gate.compute_pivots_only (may cache-anchor)
  2. PDH/PDL from prior 5m aggregation vs live D1 selection (holiday cases)
  3. MACD rising helper — mine uses `hist_v > hist_prev AND hist agrees
     with direction`; live imports confirmation_engine._macd_hist_rising_
     at_entry which has richer signal-line agree checks. Boundary cases
     may differ.
  4. LADDER on_bar_close is called on committed 5m boundaries; the
     signal_log timestamp_open may not perfectly align to a 5m boundary.
     I treat the FIRST candle after timestamp_open as the "entry bar
     close" (mirrors trade_manager's next-bar hook).

Error estimate ±5 % per fire; ±1 p per rung price on non-standard pivots.
"""
import csv, json, os, datetime as dt
import pandas as pd
import numpy as np
from collections import defaultdict

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
FLAT_HHMM = dt.time(20, 40)
AT_LEVEL_PIPS = 5.0
ASSESS_BARS = 3
STOP_BUFFER_PIPS = 3.0
INIT_SL_PIPS = 12.0
BROKER_MIN_PIPS = 12.0

# --- data
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

def find_prior_d1(target):
    """Aggregate prior weekday's 5m rows to OHLC."""
    tgt = dt.date.fromisoformat(target)
    for back in range(1, 8):
        pd_ = (tgt - dt.timedelta(days=back)).isoformat()
        rows = load_day(pd_)
        if rows and len(rows) >= 100:
            return dict(date=pd_, high=max(b['high'] for b in rows),
                        low=min(b['low'] for b in rows),
                        close=rows[-1]['close'])
    return None

def compute_pivots(pd_):
    H, L, C = pd_['high'], pd_['low'], pd_['close']
    P = (H+L+C)/3.0
    return dict(P=P, R1=2*P-L, R2=P+(H-L), R3=H+2*(P-L),
                S1=2*P-H, S2=P-(H-L), S3=L-2*(H-P))

def build_rungs(direction, entry_price, pivots, pdh, pdl):
    all_rungs = []
    for name in ('P','R1','R2','R3','S1','S2','S3'):
        if name in pivots:
            all_rungs.append(dict(name=name, price=pivots[name],
                                  cohort='P' if name=='P' else 'OUTER'))
    if pdh is not None: all_rungs.append(dict(name='PDH', price=pdh, cohort='PDH'))
    if pdl is not None: all_rungs.append(dict(name='PDL', price=pdl, cohort='PDL'))
    is_buy = direction in ('BUY','LONG')
    if is_buy:
        seq = [r for r in all_rungs if r['price'] > entry_price]
        seq.sort(key=lambda r: r['price'])
    else:
        seq = [r for r in all_rungs if r['price'] < entry_price]
        seq.sort(key=lambda r: -r['price'])
    return seq

def macd_hist_rising(closes, direction, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal + 5: return None
    s = pd.Series(closes)
    e_f = s.ewm(span=fast, adjust=False).mean()
    e_s = s.ewm(span=slow, adjust=False).mean()
    line = e_f - e_s
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    h_v = hist.iloc[-1]; h_p = hist.iloc[-2]
    if np.isnan(h_v) or np.isnan(h_p): return None
    rising = h_v > h_p
    if direction in ('BUY','LONG'):
        return bool(rising and h_v > 0)
    return bool((not rising) and h_v < 0)

def is_rejection_at_rung(direction, o, h, l, c, rung_price):
    """level_ladder.py:433-471."""
    rng = h - l
    if rng <= 0: return False
    is_buy = direction in ('BUY','LONG')
    if is_buy:
        if not (h > rung_price): return False
        if not (c < rung_price): return False
        return (c - l) <= rng / 3.0
    else:
        if not (l < rung_price): return False
        if not (c > rung_price): return False
        return (h - c) <= rng / 3.0

# --- LADDER v3 sim
def sim_ladder(rows, entry_bar_idx, direction, rungs,
               init_sl_pips=INIT_SL_PIPS,
               at_level_pips=AT_LEVEL_PIPS,
               assess_bars=ASSESS_BARS,
               stop_buffer_pips=STOP_BUFFER_PIPS,
               entry_price_override=None):
    if entry_bar_idx >= len(rows): return None
    entry = entry_price_override if entry_price_override is not None else rows[entry_bar_idx]['close']
    is_buy = direction in ('BUY','LONG')
    initial_sl = entry - init_sl_pips if is_buy else entry + init_sl_pips
    intended_stop = None
    rung_idx = 0
    state = 'RUNNING'
    assess_seen = 0
    events = []
    max_p = entry; min_p = entry
    for j in range(entry_bar_idx+1, len(rows)):
        b = rows[j]
        bo, bh, bl, bc = b['open'], b['high'], b['low'], b['close']
        ts = parse_ts(b['ts'])
        if is_buy and bh > max_p: max_p = bh
        if not is_buy and bl < min_p: min_p = bl
        # 20:40 flat
        if ts.time() >= FLAT_HHMM:
            pnl = (bo - entry) if is_buy else (entry - bo)
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=bo, pnl=pnl,
                        reason='FLAT_2040', events=events,
                        final_rung_idx=rung_idx, final_state=state)
        # intended-stop preemption
        if intended_stop is not None:
            breached = (is_buy and bc < intended_stop) or (not is_buy and bc > intended_stop)
            if breached:
                pnl = (bc - entry) if is_buy else (entry - bc)
                events.append(dict(bar_ts=b['ts'], action='LADDER_RATCHET_STOP',
                                   intended=intended_stop))
                return dict(exit_bar=j, exit_ts=b['ts'], exit_price=bc, pnl=pnl,
                            reason='LADDER_RATCHET_STOP', events=events,
                            final_rung_idx=rung_idx, final_state=state)
        # initial 12p SL (before first EXTEND)
        if intended_stop is None:
            hit_sl = (is_buy and bl <= initial_sl) or (not is_buy and bh >= initial_sl)
            if hit_sl:
                pnl = -init_sl_pips
                events.append(dict(bar_ts=b['ts'], action='INIT_SL', sl=initial_sl))
                return dict(exit_bar=j, exit_ts=b['ts'], exit_price=initial_sl, pnl=pnl,
                            reason='INIT_SL', events=events,
                            final_rung_idx=rung_idx, final_state=state)
        # EXHAUSTED: hold
        if state == 'EXHAUSTED': continue
        # rung logic
        if rung_idx >= len(rungs):
            state = 'EXHAUSTED'; continue
        rung = rungs[rung_idx]
        rung_price = rung['price']
        if is_buy:
            reached = (rung_price - bh) <= at_level_pips
        else:
            reached = (bl - rung_price) <= at_level_pips
        if state == 'RUNNING' and not reached: continue
        state_in = state
        if state_in == 'RUNNING':
            state = 'ASSESS'; assess_seen = 1
            events.append(dict(bar_ts=b['ts'], action='RUNNING→ASSESS',
                               rung=rung['name'], rung_price=rung_price))
        else:
            assess_seen += 1
        # extend triggers
        close_beyond = (is_buy and bc > rung_price) or (not is_buy and bc < rung_price)
        closes_upto = [rows[k]['close'] for k in range(0, j+1)]
        macd_rise = macd_hist_rising(closes_upto, direction)
        rng = bh - bl
        close_top = rng > 0 and (bc - bl) >= (2/3)*rng
        close_bot = rng > 0 and (bh - bc) >= (2/3)*rng
        mom_ext = macd_rise and ((is_buy and close_top) or (not is_buy and close_bot))
        momentum_allowed = (state_in != 'RUNNING')
        if close_beyond or (mom_ext and momentum_allowed):
            intended_target = rung_price - stop_buffer_pips if is_buy else rung_price + stop_buffer_pips
            if intended_stop is not None:
                if is_buy and intended_stop > intended_target: intended_target = intended_stop
                if not is_buy and intended_stop < intended_target: intended_target = intended_stop
            intended_stop = intended_target
            rung_idx += 1
            if rung_idx >= len(rungs):
                state = 'EXHAUSTED'
            else:
                state = 'RUNNING'
                assess_seen = 0
            events.append(dict(bar_ts=b['ts'], action='EXTEND',
                               rung_cleared=rung['name'], rung_price=rung_price,
                               close_beyond=close_beyond, momentum_extend=mom_ext,
                               intended_stop=intended_stop, new_state=state))
            continue
        # rejection
        rej = is_rejection_at_rung(direction, bo, bh, bl, bc, rung_price)
        if rej:
            pnl = (bc - entry) if is_buy else (entry - bc)
            events.append(dict(bar_ts=b['ts'], action='LADDER_REJECTION',
                               rung=rung['name'], close=bc))
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=bc, pnl=pnl,
                        reason='LADDER_REJECTION', events=events,
                        final_rung_idx=rung_idx, final_state=state)
        # assess_expired
        if assess_seen >= assess_bars:
            pnl = (bc - entry) if is_buy else (entry - bc)
            events.append(dict(bar_ts=b['ts'], action='LADDER_ASSESS_EXPIRED',
                               rung=rung['name'], assess_seen=assess_seen, close=bc))
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=bc, pnl=pnl,
                        reason='LADDER_ASSESS_EXPIRED', events=events,
                        final_rung_idx=rung_idx, final_state=state)
    # EOD walk
    b = rows[-1]
    pnl = (b['close']-entry) if is_buy else (entry-b['close'])
    return dict(exit_bar=len(rows)-1, exit_ts=b['ts'], exit_price=b['close'], pnl=pnl,
                reason='EOD_TAIL', events=events,
                final_rung_idx=rung_idx, final_state=state)

# --- TIERED RATCHET sim (persist_2h spec)
def sim_ratchet(rows, entry_bar_idx, direction,
                init_sl_pips=INIT_SL_PIPS,
                entry_price_override=None):
    if entry_bar_idx >= len(rows): return None
    entry = entry_price_override if entry_price_override is not None else rows[entry_bar_idx]['close']
    is_buy = direction in ('BUY','LONG')
    sl = entry - init_sl_pips if is_buy else entry + init_sl_pips
    max_p = entry; min_p = entry; no_new = 0
    for j in range(entry_bar_idx+1, len(rows)):
        b = rows[j]
        ts = parse_ts(b['ts'])
        if ts.time() >= FLAT_HHMM:
            pnl = (b['open']-entry) if is_buy else (entry-b['open'])
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=b['open'], pnl=pnl, reason='FLAT_2040')
        # SL check
        if is_buy and b['low'] <= sl: return dict(exit_bar=j, exit_ts=b['ts'], exit_price=sl, pnl=(sl-entry), reason='SL')
        if not is_buy and b['high'] >= sl: return dict(exit_bar=j, exit_ts=b['ts'], exit_price=sl, pnl=(entry-sl), reason='SL')
        fav = (b['high'] - entry) if is_buy else (entry - b['low'])
        # tiered ratchet
        if fav >= 100 and (sl - entry if is_buy else entry - sl) < 75:
            sl = entry + 75 if is_buy else entry - 75
        elif fav >= 60 and (sl - entry if is_buy else entry - sl) < 40:
            sl = entry + 40 if is_buy else entry - 40
        elif fav >= 30 and (sl - entry if is_buy else entry - sl) < 15:
            sl = entry + 15 if is_buy else entry - 15
        elif fav >= 10 and (sl < entry if is_buy else sl > entry):
            sl = entry
        # exhaustion
        cur = b['high'] if is_buy else b['low']
        if (is_buy and cur > max_p) or (not is_buy and cur < min_p):
            if is_buy: max_p = cur
            else: min_p = cur
            no_new = 0
        else:
            no_new += 1
        beyond_be = (sl > entry) if is_buy else (sl < entry)
        if no_new >= 6 and beyond_be:
            pnl = (b['close']-entry) if is_buy else (entry-b['close'])
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=b['close'], pnl=pnl, reason='EXHAUSTION')
    b = rows[-1]
    pnl = (b['close']-entry) if is_buy else (entry-b['close'])
    return dict(exit_bar=len(rows)-1, exit_ts=b['ts'], exit_price=b['close'], pnl=pnl, reason='EOD_TAIL')

# --- process every fire
fires = []
with open('/tmp/ladder_fires.jsonl') as f:
    for l in f:
        fires.append(json.loads(l))

STALE_PIVOT_WINDOWS = []  # populated if I find any bb_pd_gate stale-flag logs

def entry_bar_index(rows, ts_open):
    """Find the bar containing timestamp_open; use its close as entry.
    Live trade_executor: entry_price = broker fill price; my surrogate
    approximates by 'next 5m close after timestamp_open bar close'.
    Actually for THIS study we use ACTUAL entry price from signal_log
    and place the walk starting at the bar strictly AFTER the fire.
    """
    t_open = parse_ts(ts_open)
    # find first bar whose ts >= bar_floor(t_open) + 5min
    target_start = bar_floor(t_open) + dt.timedelta(minutes=5)
    for i, b in enumerate(rows):
        try:
            bt = parse_ts(b['ts'])
        except Exception:
            continue
        if bt >= target_start:
            return i-1  # entry "at" the bar just before — walk starts at i
    return None

def walk_fire(fire):
    ts_open = fire['timestamp_open']
    d_iso = ts_open[:10]
    direction = fire['direction']
    entry = float(fire['entry'])
    rows = load_day(d_iso)
    if rows is None or len(rows) < 40:
        return dict(unpriceable_reason='candles_missing_for_day')
    idx = entry_bar_index(rows, ts_open)
    if idx is None or idx+1 >= len(rows):
        return dict(unpriceable_reason='entry_bar_not_locatable')
    # LADDER: build rungs
    pd_ = find_prior_d1(d_iso)
    if pd_ is None:
        return dict(unpriceable_reason='prior_D1_missing')
    pivots = compute_pivots(pd_)
    pdh, pdl = pd_['high'], pd_['low']
    rungs = build_rungs(direction, entry, pivots, pdh, pdl)
    # LADDER v3 walk — pass entry_price_override so LADDER simulates
    # against the actual entry price rather than the following bar's close
    lad = sim_ladder(rows, idx, direction, rungs, entry_price_override=entry)
    rat = sim_ratchet(rows, idx, direction, entry_price_override=entry)
    return dict(rungs=[(r['name'], round(r['price'],4)) for r in rungs],
                pivots={k: round(v,4) for k,v in pivots.items()},
                pdh=round(pdh,4), pdl=round(pdl,4),
                pd_date=pd_['date'],
                LADDER=lad, RATCHET=rat)

# process all
processed = []
for f in fires:
    r = walk_fire(f)
    r['fire'] = f
    processed.append(r)

# save + print summary
n_priced = sum(1 for r in processed if 'LADDER' in r)
n_unpriced = sum(1 for r in processed if r.get('unpriceable_reason'))
print(f"Total fires: {len(processed)}")
print(f"Priced: {n_priced}")
print(f"Unpriceable: {n_unpriced}")
for r in processed:
    if r.get('unpriceable_reason'):
        print(f"  {r['fire']['timestamp_open']} {r['fire']['strategy']}: {r['unpriceable_reason']}")

# aggregate
def sum_col(processed, col):
    return sum(r[col]['pnl'] for r in processed if col in r and r[col])

from collections import defaultdict
per_mode = defaultdict(lambda: dict(n=0, actual=0.0, ladder=0.0, ratchet=0.0))
for r in processed:
    if 'LADDER' not in r or 'RATCHET' not in r: continue
    m = r['fire']['strategy']
    per_mode[m]['n'] += 1
    per_mode[m]['actual'] += r['fire'].get('pnl_pips') or 0
    per_mode[m]['ladder'] += r['LADDER']['pnl']
    per_mode[m]['ratchet'] += r['RATCHET']['pnl']

print("\n=== aggregate per mode ===")
print(f"{'mode':<26s} {'n':>4s} {'ACTUAL':>10s} {'LADDER':>10s} {'RATCHET':>10s} {'L-A':>10s} {'R-A':>10s}")
for m in sorted(per_mode):
    v = per_mode[m]
    print(f"{m:<26s} {v['n']:>4d} {v['actual']:>+10.1f} {v['ladder']:>+10.1f} {v['ratchet']:>+10.1f} "
          f"{v['ladder']-v['actual']:>+10.1f} {v['ratchet']-v['actual']:>+10.1f}")

tot_a = sum(v['actual'] for v in per_mode.values())
tot_l = sum(v['ladder'] for v in per_mode.values())
tot_r = sum(v['ratchet'] for v in per_mode.values())
tot_n = sum(v['n'] for v in per_mode.values())
print(f"{'TOTAL':<26s} {tot_n:>4d} {tot_a:>+10.1f} {tot_l:>+10.1f} {tot_r:>+10.1f} "
      f"{tot_l-tot_a:>+10.1f} {tot_r-tot_a:>+10.1f}")

# LADDER exit-reason distribution
from collections import Counter
reasons = Counter([r['LADDER']['reason'] for r in processed if 'LADDER' in r])
print("\n=== LADDER exit-reason distribution ===")
for k, ct in reasons.most_common():
    pnl = sum(r['LADDER']['pnl'] for r in processed if 'LADDER' in r and r['LADDER']['reason']==k)
    print(f"  {k:<25s}  n={ct:>3d}  pnl_sum={pnl:>+8.1f}  avg={pnl/max(1,ct):+6.2f}")

# save detail
serialise = []
for r in processed:
    serialise.append(dict(
        fire=dict(ts=r['fire']['timestamp_open'], strategy=r['fire']['strategy'],
                  direction=r['fire']['direction'], entry=r['fire']['entry'],
                  actual_pnl=r['fire'].get('pnl_pips'),
                  actual_reason=r['fire'].get('close_reason')),
        rungs=r.get('rungs'), pd_date=r.get('pd_date'), pdh=r.get('pdh'), pdl=r.get('pdl'),
        pivots=r.get('pivots'),
        LADDER=(dict(pnl=r['LADDER']['pnl'], reason=r['LADDER']['reason'],
                     exit_ts=r['LADDER']['exit_ts'], exit_price=r['LADDER']['exit_price'],
                     events=r['LADDER']['events'], final_state=r['LADDER']['final_state'])
                if 'LADDER' in r else None),
        RATCHET=(dict(pnl=r['RATCHET']['pnl'], reason=r['RATCHET']['reason'],
                      exit_ts=r['RATCHET']['exit_ts'], exit_price=r['RATCHET']['exit_price'])
                 if 'RATCHET' in r else None),
        unpriceable_reason=r.get('unpriceable_reason'),
    ))
json.dump(serialise, open('/tmp/ladder_real_walk.json','w'), indent=1, default=str)
print(f"\nsaved detail: /tmp/ladder_real_walk.json (n={len(serialise)})")
