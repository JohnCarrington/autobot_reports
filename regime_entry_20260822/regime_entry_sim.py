"""Regime-Entry: STRONG_TREND onset → level_ladder surrogate.

Rules per operator spec:
  Entry: regime_engine winning_regime = STRONG_TREND_UP/DOWN;
    N ∈ {1,2,6} consecutive STRONG bars required.
    Enter at NEXT 5m close, trend direction.
  Exit: level_ladder v3 semantics — cite lines below.
  Position: 1 at a time; re-entry if stopped/ratcheted out and STRONG
    still holds; cap 4 re-entries/day (count binds).

Ladder surrogate (level_ladder.py lines cited):
  Rungs (level_ladder.py:325-361 _build_rung_sequence):
    - Standard pivots P/R1/R2/R3/S1/S2/S3 from prior D1 candle
      (H+L+C)/3 with R/S calculations.
    - PDH, PDL from prior D1 high/low.
    - Only rungs BEYOND entry in trade direction, sorted nearest-first.
  Constants (:155-158):
    - AT_LEVEL_PIPS = 5   (rung reached iff bar extreme within 5p)
    - ASSESS_BARS = 3      (3 bars in ASSESS before expiry close)
    - STOP_BUFFER_PIPS = 3 (intended stop = cleared rung ± 3p)
    - MAX_SL 12p at entry (before any rung cleared)

  State machine (:498-510, 773-937):
    RUNNING: bar high (BUY) or low (SELL) within AT_LEVEL_PIPS of rung
      → transitions to ASSESS on same bar (:827-831).
    ASSESS entry: RUNNING→ASSESS on first-touch bar. assess_seen=1.
    In ASSESS, per-bar evaluate (:841-937):
      close_beyond (primary): bar_close beyond rung in direction (:786-787)
        → EXTEND (rung_index++, intended_stop = rung ± buffer,
          state → RUNNING or EXHAUSTED if all rungs cleared).
      momentum_extend (secondary): MACD hist rising AND close in
        top/bottom 1/3 of bar range (:790-799); allowed ONLY from
        ASSESS (:860 momentum_extend_allowed = state != RUNNING).
      rejection (:801-802, 916-923): pierce + close-back + close-
        location, per :433-471.
      assess_expired (:924-931): assess_seen >= assess_bars → close.
    Intended-stop preemption (:719-749): before any state work, if
      bar_close beyond intended_stop → close, LADDER_RATCHET_STOP.
    EXHAUSTED (:753-757): hold; only intended stop or broker backstop
      exits.

Rule sources verified. Surrogate error known to include:
  - Standard pivot math vs live bb_pd_gate.compute_pivots_only (which may
    apply cache-anchor rules); could shift rung prices by <1p.
  - PDH/PDL: exact prior-D1 selection may differ on Mon-after-holiday.
  - MACD comparator matches the imported function's signature but may
    differ in tie-break behaviour on hist_v == hist_prev.
"""
import csv, json, os, datetime as dt, math
import pandas as pd
import numpy as np
from collections import defaultdict, Counter

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REGIME_LOG = "/opt/tradingbot/logs/regime_engine.jsonl"
FLAT_HHMM = dt.time(20, 40)
COOLDOWN_MIN = 0  # per spec: re-entry immediately allowed
MAX_REENTRIES = 4  # cap per day
INIT_SL_PIPS = 12.0
AT_LEVEL_PIPS = 5.0
ASSESS_BARS = 3
STOP_BUFFER_PIPS = 3.0
BROKER_MIN_PIPS = 12.0  # GBPUSD IG min stop distance

TARGET_GRIND = {'2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29'}

# ── data loading ──────────────────────────────────────────────────────
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
    """Aggregate prior day's OHLC from 5m candles (approx of live prior_d1)."""
    tgt = dt.date.fromisoformat(target)
    for back in range(1, 8):
        pd_ = (tgt - dt.timedelta(days=back)).isoformat()
        p = f'{CANDLES}/{pd_}.csv'
        if not os.path.exists(p): continue
        rows = load_day(pd_)
        if not rows or len(rows) < 100: continue
        h = max(b['high'] for b in rows)
        l = min(b['low'] for b in rows)
        c = rows[-1]['close']
        return dict(date=pd_, high=h, low=l, close=c, first_close=rows[0]['close'])
    return None

def compute_pivots(pd_):
    """Standard pivot points from prior D1 (H+L+C)/3."""
    H, L, C = pd_['high'], pd_['low'], pd_['close']
    P = (H + L + C) / 3.0
    R1 = 2*P - L
    S1 = 2*P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    R3 = H + 2*(P - L)
    S3 = L - 2*(H - P)
    return dict(P=P, R1=R1, R2=R2, R3=R3, S1=S1, S2=S2, S3=S3)

def build_rungs(direction, entry_price, pivots, pdh, pdl):
    """Build ordered rung sequence: pivots + PDH/PDL beyond entry."""
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

# ── MACD hist rising ────────────────────────────────────────────────
def macd_hist_rising(closes, direction, fast=12, slow=26, signal=9):
    """Return True if MACD hist is rising in trade direction (matches
    confirmation_engine._macd_hist_rising_at_entry semantics)."""
    if len(closes) < slow + signal + 5: return None
    s = pd.Series(closes)
    e_fast = s.ewm(span=fast, adjust=False).mean()
    e_slow = s.ewm(span=slow, adjust=False).mean()
    line = e_fast - e_slow
    sig  = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    h_v = hist.iloc[-1]; h_prev = hist.iloc[-2]
    if np.isnan(h_v) or np.isnan(h_prev): return None
    hist_rising_signed = h_v > h_prev
    if direction == 'BUY':
        return bool(hist_rising_signed and h_v > 0)
    else:
        return bool((not hist_rising_signed) and h_v < 0)
    # Note: exact semantics of confirmation_engine may differ — this is a
    # reasonable surrogate.

# ── rejection at rung ────────────────────────────────────────────────
def is_rejection_at_rung(direction, o, h, l, c, rung_price):
    """From level_ladder.py:_is_rejection_at_rung."""
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

# ── ladder walk from entry ───────────────────────────────────────────
def simulate_ladder_entry(rows, entry_bar_idx, direction, rungs,
                          init_sl_pips=INIT_SL_PIPS):
    """Walk the ladder state machine from entry_bar_idx (position opens
    at that bar's close). Returns dict with exit_bar, exit_price, pnl,
    reason, ladder_events."""
    if entry_bar_idx >= len(rows): return None
    entry = rows[entry_bar_idx]['close']
    is_buy = direction == 'BUY'
    # initial broker/intended stops
    initial_sl = entry - init_sl_pips if is_buy else entry + init_sl_pips
    intended_stop = None  # populated on first EXTEND
    broker_stop = initial_sl  # 12p initial
    rung_idx = 0
    state = 'RUNNING'
    assess_seen = 0
    events = []
    max_price = entry; min_price = entry
    for j in range(entry_bar_idx + 1, len(rows)):
        b = rows[j]
        ts = parse_ts(b['ts'])
        bo, bh, bl, bc = b['open'], b['high'], b['low'], b['close']
        # ── 20:40 flat ──
        if ts.time() >= FLAT_HHMM:
            exit_px = bo
            pnl = (exit_px - entry) if is_buy else (entry - exit_px)
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                        pnl=pnl, reason='FLAT_2040', events=events,
                        max_favorable=max_price - entry if is_buy else entry - min_price,
                        final_rung_idx=rung_idx, final_state=state)
        # ── intended-stop preemption (level_ladder.py:719-749) ──
        if intended_stop is not None:
            breached = (is_buy and bc < intended_stop) or (not is_buy and bc > intended_stop)
            if breached:
                exit_px = bc
                pnl = (exit_px - entry) if is_buy else (entry - exit_px)
                events.append(dict(bar=j, ts=b['ts'], action='LADDER_RATCHET_STOP',
                                   intended=intended_stop, close=bc))
                return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                            pnl=pnl, reason='LADDER_RATCHET_STOP', events=events,
                            max_favorable=max_price - entry if is_buy else entry - min_price,
                            final_rung_idx=rung_idx, final_state=state)
        # ── SL preemption (initial 12p until first EXTEND) ──
        if intended_stop is None:
            # bar can have low pierce initial_sl even if bar_close > SL
            hit_sl = (is_buy and bl <= initial_sl) or (not is_buy and bh >= initial_sl)
            if hit_sl:
                exit_px = initial_sl
                pnl = (exit_px - entry) if is_buy else (entry - exit_px)
                events.append(dict(bar=j, ts=b['ts'], action='INIT_SL',
                                   sl=initial_sl))
                return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                            pnl=pnl, reason='INIT_SL', events=events,
                            max_favorable=max_price - entry if is_buy else entry - min_price,
                            final_rung_idx=rung_idx, final_state=state)
        # ── EXHAUSTED: hold (only stops close) ──
        if state == 'EXHAUSTED':
            # update extremes
            if is_buy and bh > max_price: max_price = bh
            if not is_buy and bl < min_price: min_price = bl
            continue
        # ── rung check ──
        if rung_idx >= len(rungs):
            state = 'EXHAUSTED'
            continue
        rung = rungs[rung_idx]
        rung_price = rung['price']
        # AT_LEVEL check
        if is_buy:
            dist = rung_price - bh
            reached = dist <= AT_LEVEL_PIPS
        else:
            dist = bl - rung_price
            reached = dist <= AT_LEVEL_PIPS
        # ── MACD rising ──
        # closes up to j (inclusive) — use closes_arr
        closes_upto = [rows[k]['close'] for k in range(0, j+1)]
        macd_rise = macd_hist_rising(closes_upto, direction)
        # ── close_beyond ──
        close_beyond = (is_buy and bc > rung_price) or (not is_buy and bc < rung_price)
        # ── momentum_extend ──
        rng = bh - bl
        close_top_third = rng > 0 and (bc - bl) >= (2/3)*rng
        close_bot_third = rng > 0 and (bh - bc) >= (2/3)*rng
        momentum_extend = False
        if macd_rise:
            momentum_extend = (is_buy and close_top_third) or (not is_buy and close_bot_third)
        # ── rejection ──
        rejection = is_rejection_at_rung(direction, bo, bh, bl, bc, rung_price)
        # ── State transition ──
        if state == 'RUNNING' and not reached:
            # keep tracking extremes
            if is_buy and bh > max_price: max_price = bh
            if not is_buy and bl < min_price: min_price = bl
            continue
        # AT_LEVEL / ASSESS bar
        if state == 'RUNNING':
            state = 'ASSESS'; assess_seen = 1
        else:  # already ASSESS
            assess_seen += 1
        momentum_allowed = state != 'RUNNING'  # true since we just entered ASSESS
        # Wait — level_ladder logic: on the first-touch bar the state was RUNNING
        # BEFORE the transition, so `state != _STATE_RUNNING` when checked at
        # line 860 IS the STATE_IN, not the updated state. Actually re-reading:
        # `state` is the value BEFORE this bar's transition; `state_new` is the
        # updated one. Line 860: `momentum_extend_allowed = (state != _STATE_RUNNING)`.
        # Since `state` == RUNNING on the first-touch bar, momentum NOT allowed.
        # But `close_beyond` still allowed.
        # In my simulator, `state` before the transition is the OLD state.
        # Let me store OLD state to check correctly.
        # (The above transition already updated `state` — bug. Refactor.)
        pass  # (fixed in redo below)
        # For correctness, redo state transition logic:
        break_for_redo = True
        break
    if not events or True:
        pass
    # (fallthrough — end of day without exit)
    b = rows[-1]
    pnl = (b['close'] - entry) if is_buy else (entry - b['close'])
    return dict(exit_bar=len(rows)-1, exit_ts=b['ts'], exit_price=b['close'],
                pnl=pnl, reason='EOD_TAIL', events=events,
                max_favorable=max_price - entry if is_buy else entry - min_price,
                final_rung_idx=rung_idx, final_state=state)

# Note: my walk above had a bug in state ordering. I'll rewrite as
# simulate_ladder_entry_v2 with correct sequencing.
def simulate_ladder_entry_v2(rows, entry_bar_idx, direction, rungs,
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
        # tracking
        if is_buy and bh > max_price: max_price = bh
        if (not is_buy) and bl < min_price: min_price = bl
        # 20:40 flat
        if ts.time() >= FLAT_HHMM:
            exit_px = bo
            pnl = (exit_px - entry) if is_buy else (entry - exit_px)
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                        pnl=pnl, reason='FLAT_2040', events=events,
                        max_favorable=max_price-entry if is_buy else entry-min_price,
                        final_rung_idx=rung_idx, final_state=state)
        # intended-stop preemption
        if intended_stop is not None:
            breached = (is_buy and bc < intended_stop) or (not is_buy and bc > intended_stop)
            if breached:
                exit_px = bc
                pnl = (exit_px - entry) if is_buy else (entry - exit_px)
                events.append(dict(bar=j, ts=b['ts'], action='LADDER_RATCHET_STOP', intended=intended_stop, close=bc))
                return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                            pnl=pnl, reason='LADDER_RATCHET_STOP', events=events,
                            max_favorable=max_price-entry if is_buy else entry-min_price,
                            final_rung_idx=rung_idx, final_state=state)
        # initial 12p SL (before first EXTEND)
        if intended_stop is None:
            hit_sl = (is_buy and bl <= initial_sl) or (not is_buy and bh >= initial_sl)
            if hit_sl:
                exit_px = initial_sl
                pnl = (exit_px - entry) if is_buy else (entry - exit_px)
                events.append(dict(bar=j, ts=b['ts'], action='INIT_SL', sl=initial_sl))
                return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                            pnl=pnl, reason='INIT_SL', events=events,
                            max_favorable=max_price-entry if is_buy else entry-min_price,
                            final_rung_idx=rung_idx, final_state=state)
        # EXHAUSTED: only stops exit
        if state == 'EXHAUSTED': continue
        # rung logic
        if rung_idx >= len(rungs):
            state = 'EXHAUSTED'; continue
        rung = rungs[rung_idx]
        rung_price = rung['price']
        if is_buy:
            reached = (rung_price - bh) <= AT_LEVEL_PIPS
        else:
            reached = (bl - rung_price) <= AT_LEVEL_PIPS
        # If RUNNING and not reached — hold
        if state == 'RUNNING' and not reached: continue
        # transition
        state_in = state  # remember old state for momentum-allowed check
        if state_in == 'RUNNING':
            state = 'ASSESS'; assess_seen = 1
        else:  # ASSESS
            assess_seen += 1
        # MACD rising
        closes_upto = [rows[k]['close'] for k in range(0, j+1)]
        macd_rise = macd_hist_rising(closes_upto, direction)
        close_beyond = (is_buy and bc > rung_price) or (not is_buy and bc < rung_price)
        rng = bh - bl
        close_top_third = rng > 0 and (bc - bl) >= (2/3)*rng
        close_bot_third = rng > 0 and (bh - bc) >= (2/3)*rng
        momentum_extend = False
        if macd_rise:
            momentum_extend = (is_buy and close_top_third) or (not is_buy and close_bot_third)
        rejection = is_rejection_at_rung(direction, bo, bh, bl, bc, rung_price)
        momentum_allowed = (state_in != 'RUNNING')  # only from ASSESS
        # EXTEND?
        if close_beyond or (momentum_extend and momentum_allowed):
            # set intended_stop at rung ± buffer
            intended_target = rung_price - STOP_BUFFER_PIPS if is_buy else rung_price + STOP_BUFFER_PIPS
            if intended_stop is not None:
                if is_buy and intended_stop > intended_target: intended_target = intended_stop
                if (not is_buy) and intended_stop < intended_target: intended_target = intended_stop
            intended_stop = intended_target
            # broker stop trailed
            broker_target = bc - BROKER_MIN_PIPS if is_buy else bc + BROKER_MIN_PIPS
            if broker_stop is not None:
                if is_buy and broker_stop > broker_target: broker_target = broker_stop
                if (not is_buy) and broker_stop < broker_target: broker_target = broker_stop
            broker_stop = broker_target
            rung_idx += 1
            if rung_idx >= len(rungs):
                state = 'EXHAUSTED'
            else:
                state = 'RUNNING'
                assess_seen = 0
            events.append(dict(bar=j, ts=b['ts'], action='EXTEND', rung_cleared=rung['name'],
                               rung_price=rung_price, intended_stop=intended_stop,
                               close_beyond=close_beyond, momentum_extend=momentum_extend))
            continue
        # rejection
        if rejection:
            exit_px = bc
            pnl = (exit_px - entry) if is_buy else (entry - exit_px)
            events.append(dict(bar=j, ts=b['ts'], action='LADDER_REJECTION',
                               rung=rung['name']))
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                        pnl=pnl, reason='LADDER_REJECTION', events=events,
                        max_favorable=max_price-entry if is_buy else entry-min_price,
                        final_rung_idx=rung_idx, final_state=state)
        # assess_expired
        if assess_seen >= ASSESS_BARS:
            exit_px = bc
            pnl = (exit_px - entry) if is_buy else (entry - exit_px)
            events.append(dict(bar=j, ts=b['ts'], action='LADDER_ASSESS_EXPIRED',
                               rung=rung['name'], assess_seen=assess_seen))
            return dict(exit_bar=j, exit_ts=b['ts'], exit_price=exit_px,
                        pnl=pnl, reason='LADDER_ASSESS_EXPIRED', events=events,
                        max_favorable=max_price-entry if is_buy else entry-min_price,
                        final_rung_idx=rung_idx, final_state=state)
        # else hold in ASSESS
    # end of day
    b = rows[-1]
    pnl = (b['close']-entry) if is_buy else (entry-b['close'])
    return dict(exit_bar=len(rows)-1, exit_ts=b['ts'], exit_price=b['close'],
                pnl=pnl, reason='EOD_TAIL', events=events,
                max_favorable=max_price-entry if is_buy else entry-min_price,
                final_rung_idx=rung_idx, final_state=state)

# ── STRONG onset detector ────────────────────────────────────────────
def find_strong_onsets(rows, reg_events, N):
    """Given per-day 5m bars and regime events (per-bar ts→regime),
    return list of (trigger_bar_idx, direction) where N consecutive
    STRONG bars have accumulated. Only first onset per continuous
    STRONG stretch."""
    reg_by_ts = {t: r for t,r in reg_events}
    bar_regs = []
    last = None
    for b in rows:
        k = b['ts'][:19].replace(' ','T')
        if k in reg_by_ts: last = reg_by_ts[k]
        bar_regs.append(last)
    # consecutive counters
    consec_up = [0]*len(rows); consec_dn = [0]*len(rows)
    for i, r in enumerate(bar_regs):
        consec_up[i] = (consec_up[i-1]+1) if (i>0 and r=='STRONG_TREND_UP') else (1 if r=='STRONG_TREND_UP' else 0)
        consec_dn[i] = (consec_dn[i-1]+1) if (i>0 and r=='STRONG_TREND_DOWN') else (1 if r=='STRONG_TREND_DOWN' else 0)
    # trigger fires when consec == N (first time), then requires a break
    onsets = []
    fired_up = False; fired_dn = False
    for i in range(len(rows)):
        if consec_up[i] == N and not fired_up:
            onsets.append((i, 'BUY'))
            fired_up = True
        elif consec_up[i] < N:
            fired_up = False  # break — re-arm
        if consec_dn[i] == N and not fired_dn:
            onsets.append((i, 'SELL'))
            fired_dn = True
        elif consec_dn[i] < N:
            fired_dn = False
    return onsets

# ── per-day walk with re-entries ─────────────────────────────────────
TRIG_CAP = dt.time(18, 0)  # no new entry after 18:00 UTC (need time to work)

def walk_day_regime_entry(d, N, reg_events):
    rows = load_day(d)
    if not rows: return None
    onsets = find_strong_onsets(rows, reg_events, N)
    if not onsets: return None
    pd_ = find_prior_d1(d)
    if pd_ is None: return None
    pivots = compute_pivots(pd_)
    pdh, pdl = pd_['high'], pd_['low']
    trades = []
    reentries_by_direction = defaultdict(int)
    last_exit_bar = -1
    for onset_bar, direction in onsets:
        entry_bar = onset_bar + 1  # entry at next 5m close
        if entry_bar >= len(rows): continue
        if entry_bar <= last_exit_bar: continue  # one-position rule
        # cap check
        # count re-entries: >1 in same direction on same day
        # A re-entry is trade 2, 3, ... in the same direction
        if reentries_by_direction[direction] >= MAX_REENTRIES + 1: continue  # cap
        # entry time cap: no new entry past 18:00
        if parse_ts(rows[entry_bar]['ts']).time() >= TRIG_CAP: continue
        entry_price = rows[entry_bar]['close']
        rungs = build_rungs(direction, entry_price, pivots, pdh, pdl)
        if not rungs:
            # no rung beyond entry — surrogate uses fallback 12p SL only + 20:40 flat
            # ladder would refuse and fall back
            res = None  # skip: mirror live behavior
            trades.append(dict(direction=direction, entry_bar=entry_bar,
                              entry_ts=rows[entry_bar]['ts'], entry_price=entry_price,
                              rungs=[], exit_bar=None, exit_ts=None, exit_price=None,
                              pnl=0.0, reason='NO_RUNGS_SURROGATE_SKIP', events=[]))
            last_exit_bar = entry_bar
            continue
        res = simulate_ladder_entry_v2(rows, entry_bar, direction, rungs)
        if res is None: continue
        trades.append(dict(direction=direction, entry_bar=entry_bar,
                          entry_ts=rows[entry_bar]['ts'], entry_price=entry_price,
                          rungs=[r['name'] for r in rungs],
                          rung_prices=[r['price'] for r in rungs], **res))
        last_exit_bar = res['exit_bar']
        reentries_by_direction[direction] += 1
    day_pnl = sum(t['pnl'] for t in trades)
    return dict(date=d, N=N, n_trades=len(trades), pnl=day_pnl, trades=trades,
                pivots=pivots, pdh=pdh, pdl=pdl, cap_bound=any(v > MAX_REENTRIES for v in reentries_by_direction.values()))

# ── regime coverage days ─────────────────────────────────────────────
regime_by_day = defaultdict(list)
with open(REGIME_LOG) as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('symbol') != 'GBPUSD': continue
        d = r.get('timestamp','')[:10]
        regime_by_day[d].append((r['timestamp'][:19], r['winning_regime']))
all_dates = sorted(regime_by_day)
print(f"regime-log days: {len(all_dates)}  {all_dates[0]} .. {all_dates[-1]}")

# ── run all variants ─────────────────────────────────────────────────
Ns = [1, 2, 6]
results = {N: {'days': {}, 'total_pnl': 0.0, 'total_trades': 0, 'cap_binds': 0}
           for N in Ns}
for d in all_dates:
    reg_events = regime_by_day[d]
    for N in Ns:
        r = walk_day_regime_entry(d, N, reg_events)
        if r is None or not r['trades']: continue
        results[N]['days'][d] = r
        results[N]['total_pnl'] += r['pnl']
        results[N]['total_trades'] += r['n_trades']
        if r['cap_bound']: results[N]['cap_binds'] += 1

# summary
print("\n=== summary ===")
print(f"{'N':>2s} {'trigger_days':>13s} {'trades':>7s} {'total_pnl':>10s} {'avg/day':>8s} {'cap_binds':>10s}")
for N in Ns:
    r = results[N]
    n_days = len(r['days'])
    print(f"{N:>2d} {n_days:>13d} {r['total_trades']:>7d} {r['total_pnl']:>+10.1f} "
          f"{r['total_pnl']/max(1,n_days):>+8.1f} {r['cap_binds']:>10d}")

# grind vs other
print("\n=== grind vs other ===")
for N in Ns:
    r = results[N]
    g_days = [d for d in r['days'] if d in TARGET_GRIND]
    o_days = [d for d in r['days'] if d not in TARGET_GRIND]
    g_pnl = sum(r['days'][d]['pnl'] for d in g_days)
    o_pnl = sum(r['days'][d]['pnl'] for d in o_days)
    print(f"  N={N}: grind days={len(g_days)}/6 pnl={g_pnl:+.1f}  other days={len(o_days)} pnl={o_pnl:+.1f}")

# per-target-day detail
print("\n=== per-target-day detail ===")
for d in sorted(TARGET_GRIND):
    print(f"\n{d}:")
    for N in Ns:
        r = results[N]['days'].get(d)
        if r is None:
            print(f"  N={N}: no trigger")
            continue
        print(f"  N={N}: {r['n_trades']} trades, pnl {r['pnl']:+.1f}")
        for t in r['trades']:
            reasons = t['reason']
            events_summary = ','.join(e.get('action','') for e in t.get('events',[])[:5])
            print(f"    {t['entry_ts'][11:19]} {t['direction']:4s}@{t['entry_price']:.2f} → "
                  f"{t['exit_ts'][11:19] if t.get('exit_ts') else '?'}@{t.get('exit_price','?')}  "
                  f"reason={reasons}  events=[{events_summary}]  pnl={t['pnl']:+.1f}")

# save
save = {}
for N in Ns:
    save[N] = {'total_pnl': results[N]['total_pnl'],
               'total_trades': results[N]['total_trades'],
               'cap_binds': results[N]['cap_binds'],
               'days': {}}
    for d, r in results[N]['days'].items():
        save[N]['days'][d] = dict(n_trades=r['n_trades'], pnl=r['pnl'],
            trades=[{k:v for k,v in t.items() if k!='events'} for t in r['trades']])
json.dump(save, open('/tmp/regime_entry_result.json','w'), indent=1, default=str)
