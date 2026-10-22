#!/usr/bin/env python3
"""Read-only three-leg convergence audit for BB_BOUNCE GBPUSD fires.
MACD and H1 legs RECONSTRUCTED from candle archives, not fire-time stamps.
"""
import json, os, csv, sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter

CANDLE_DIR = '/opt/tradingbot/data/candles/GBPUSD'
SIG_LOG    = '/opt/tradingbot/logs/signal_log.jsonl'

# ---------------------------------------------------------------------------
# Load fires -----------------------------------------------------------------
def load_fires():
    fires = []
    with open(SIG_LOG) as f:
        for ln in f:
            try: d = json.loads(ln)
            except: continue
            if 'BB_BOUNCE' not in d.get('strategy',''):    continue
            if d.get('pair') != 'GBPUSD':                  continue
            ts = d.get('timestamp_open','')
            if ts < '2026-06-01' or ts >= '2026-08-05':    continue
            if d.get('total_pnl_pips') is None:            continue
            fires.append(d)
    fires.sort(key=lambda x: x['timestamp_open'])
    return fires

# ---------------------------------------------------------------------------
# 5m candle loader (bar_open UTC datetime -> (o,h,l,c) as pip*10 floats)
def load_day(dstr):
    p = f'{CANDLE_DIR}/{dstr}.csv'
    if not os.path.exists(p): return []
    out = []
    with open(p) as f:
        r = csv.DictReader(f)
        for row in r:
            ts = row['timestamp']
            # normalise "2026-06-01T00:00:00+00:00"
            if ts.endswith('+00:00'):
                dt = datetime.fromisoformat(ts)
            else:
                dt = datetime.fromisoformat(ts.replace('Z','+00:00'))
            out.append((dt,
                        float(row['open']), float(row['high']),
                        float(row['low']),  float(row['close'])))
    return out

# get 5m bars covering [start,end) UTC, spanning as many day files as needed
def load_5m_range(start_dt, end_dt):
    bars, seen_days = [], set()
    d = start_dt.date()
    while d <= end_dt.date():
        ds = d.strftime('%Y-%m-%d')
        if ds not in seen_days:
            bars.extend(load_day(ds))
            seen_days.add(ds)
        d += timedelta(days=1)
    return [b for b in bars if start_dt <= b[0] < end_dt]

# get last N completed 5m bars strictly BEFORE fire_ts
def prior_5m(fire_ts, n):
    # walk back day-by-day until we have >=n bars
    end_dt = fire_ts.replace(second=0, microsecond=0)
    # fire happens inside a 5m bar; the 5m bar open of that bar is:
    minute_floor = (end_dt.minute // 5) * 5
    entry_bar_open = end_dt.replace(minute=minute_floor)
    bars = []
    d = fire_ts.date()
    while len(bars) < n + 20 and (fire_ts.date() - d).days < 8:
        ds = d.strftime('%Y-%m-%d')
        day_bars = load_day(ds)
        bars = day_bars + bars   # prepend older
        # keep only strictly before entry_bar_open
        bars = [b for b in bars if b[0] < entry_bar_open]
        d -= timedelta(days=1)
    return bars[-n:] if len(bars) >= n else bars

# ---------------------------------------------------------------------------
# EMA helpers
def ema(values, period):
    if len(values) < period: return []
    k = 2.0 / (period + 1)
    out = [None]*(period-1)
    seed = sum(values[:period]) / period
    out.append(seed)
    for v in values[period:]:
        out.append(out[-1] + k*(v - out[-1]))
    return out

def macd_hist(closes):
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    macd = [(a-b) if a is not None and b is not None else None
            for a,b in zip(e12, e26)]
    macd_defined = [m for m in macd if m is not None]
    sig = ema(macd_defined, 9)
    # align: sig[i] corresponds to macd_defined[i]; place back
    hist = [None]*len(macd)
    offset = len(macd) - len(macd_defined)
    for i, s in enumerate(sig):
        if s is None: continue
        hist[offset+i] = macd_defined[i] - s
    return hist

# ---------------------------------------------------------------------------
# H1 resampling from 5m: build completed H1 bars from 5m bars strictly before
# the fire's H1 hour (i.e. last completed H1 = the H1 whose end <= fire_ts and
# whose end is the top of an hour <= fire_ts's top of hour).
def h1_bars_before(fire_ts, n=40):
    fire_hour = fire_ts.replace(minute=0, second=0, microsecond=0)
    # need n H1 bars strictly before fire_hour (i.e. last H1 bar covers
    # [fire_hour-1h, fire_hour) and is COMPLETE only if fire_ts > fire_hour).
    # Whether the H1 containing fire_ts counts: it is NOT complete before the
    # fire, so we use H1 bars with start < fire_hour.
    end_dt = fire_hour     # exclusive upper end
    days_needed = (n * 60 // (60*24)) + 4    # generous
    start_dt = end_dt - timedelta(days=days_needed+2)
    m5 = load_5m_range(start_dt, end_dt)
    # bucket by hour open
    buckets = defaultdict(list)
    for (t,o,h,l,c) in m5:
        hopen = t.replace(minute=0, second=0, microsecond=0)
        if hopen >= end_dt: continue
        buckets[hopen].append((t,o,h,l,c))
    h1 = []
    for hopen in sorted(buckets):
        bs = buckets[hopen]
        bs.sort()
        o = bs[0][1]; c = bs[-1][4]
        hi = max(b[2] for b in bs); lo = min(b[3] for b in bs)
        h1.append((hopen, o, hi, lo, c))
    return h1[-n:]

# ---------------------------------------------------------------------------
# Leg computations
def macd_leg(fire, prior_closes):
    if len(prior_closes) < 40:
        return ('INSUFFICIENT', None, None)
    hist = macd_hist(prior_closes)
    # last completed bar = index -1 (prior_5m returned bars strictly before entry)
    h_last = hist[-1]      # hist[t-1]
    h_prev = hist[-2]      # hist[t-2]
    if h_last is None or h_prev is None:
        return ('INSUFFICIENT', h_prev, h_last)
    direction = fire['direction']
    if direction == 'BUY':
        ok = (h_last > h_prev)
    else:
        ok = (h_last < h_prev)
    return ('PASS' if ok else 'FAIL', h_prev, h_last)

def h1_leg(fire, h1):
    if len(h1) < 25:
        return ('INSUFFICIENT', None, None, None)
    closes = [b[4] for b in h1]
    e7 = ema(closes, 7)
    e13 = ema(closes, 13)
    e21 = ema(closes, 21)
    if e7[-1] is None or e13[-1] is None or e21[-1] is None:
        return ('INSUFFICIENT', None, None, None)
    a,b,c = e7[-1], e13[-1], e21[-1]
    direction = fire['direction']
    # FAIL if cleanly opposed
    if direction == 'BUY' and (a < b < c):
        res = 'FAIL'
    elif direction == 'SELL' and (a > b > c):
        res = 'FAIL'
    else:
        res = 'PASS'
    return (res, a, b, c)

VALID_HOURS = {6,7,8,10,11,12,14,15,16,18}
def time_leg(fire_ts):
    return 'PASS' if fire_ts.hour in VALID_HOURS else 'FAIL'

# ---------------------------------------------------------------------------
def classify(pnl_total):
    if pnl_total >= 25: return 'BIG25'
    if pnl_total > 0:   return 'W'
    return 'L'

def parse_ts(s):
    return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)

# ---------------------------------------------------------------------------
def main():
    fires = load_fires()
    print(f"# BB_BOUNCE GBPUSD three-leg audit — n={len(fires)} scored fires "
          f"2026-06-01 → 2026-08-04", file=sys.stderr)

    rows = []
    flags = []
    for f in fires:
        fts = parse_ts(f['timestamp_open'])
        prior = prior_5m(fts, 120)
        if len(prior) < 40:
            flags.append(('macd_short', f['timestamp_open'], len(prior)))
        closes = [b[4] for b in prior]
        m_res, h_prev, h_last = macd_leg(f, closes)
        h1 = h1_bars_before(fts, 40)
        if len(h1) < 25:
            flags.append(('h1_short', f['timestamp_open'], len(h1)))
        e_res, e7, e13, e21 = h1_leg(f, h1)
        t_res = time_leg(fts)
        # legs_passed
        passes = sum(1 for r in (m_res, e_res, t_res) if r == 'PASS')
        cls = classify(f['total_pnl_pips'])
        rows.append(dict(
            id       = f['id'][:8],
            ts       = f['timestamp_open'],
            date     = f['timestamp_open'][:10],
            hour     = fts.hour,
            hhmm     = f['timestamp_open'][11:16],
            dir      = f['direction'][0],
            realised = f['total_pnl_pips'],
            cls      = cls,
            macd     = m_res,
            h_prev   = h_prev,
            h_last   = h_last,
            h1       = e_res,
            e7       = e7, e13 = e13, e21 = e21,
            time     = t_res,
            hour_ok  = t_res,
            passes   = passes,
        ))

    # ---------------------------------------------------------------- Output
    def emit(*a):    # simple printer
        print(*a)

    emit("NOTE: MACD and H1 legs are RECONSTRUCTED from 5m candle archives")
    emit("      (not fire-time stamps). 1H archive stops 2026-04-10, so H1")
    emit("      bars are built by resampling 5m daily files.")
    emit("")

    # --- Per-fire table -----------------------------------------------------
    emit("=" * 118)
    emit("PER-FIRE TABLE (all fires)")
    emit("=" * 118)
    hdr = ("date       time  dir realised class  MACD  hist[t-2]  hist[t-1] "
           " H1   e7        e13       e21       TIME  legs")
    emit(hdr)
    emit("-" * len(hdr))
    def fmt_f(x, w=8, p=4):
        if x is None: return " " * w
        return f"{x:>{w}.{p}f}"
    for r in rows:
        emit(f"{r['date']} {r['hhmm']} {r['dir']:>3} "
             f"{r['realised']:>8.2f} {r['cls']:>5} "
             f"{r['macd']:>4} {fmt_f(r['h_prev'],9,5)} {fmt_f(r['h_last'],9,5)}  "
             f"{r['h1']:>4} {fmt_f(r['e7'])} {fmt_f(r['e13'])} {fmt_f(r['e21'])}  "
             f"{r['time']:>4}  {r['passes']}")

    # --- Count tables -------------------------------------------------------
    def bucket_stats(subset, label):
        n = len(subset)
        big = sum(1 for r in subset if r['cls'] == 'BIG25')
        w   = sum(1 for r in subset if r['cls'] == 'W')
        l   = sum(1 for r in subset if r['cls'] == 'L')
        wins = big + w
        wr = 100.0*wins/n if n else 0
        net = sum(r['realised'] for r in subset)
        emit(f"{label:>28}  n={n:>3}  BIG25={big:>2}  W={w:>3}  L={l:>3}  "
             f"WR={wr:>5.1f}%  net={net:+7.1f}p")

    emit("")
    emit("=" * 118)
    emit("BY legs_passed")
    emit("=" * 118)
    for k in (0,1,2,3):
        bucket_stats([r for r in rows if r['passes']==k], f"legs_passed={k}")

    emit("")
    emit("=" * 118)
    emit("3-OF-3 vs everything else")
    emit("=" * 118)
    bucket_stats([r for r in rows if r['passes']==3],  "3-of-3")
    bucket_stats([r for r in rows if r['passes']<3],   "<3 (rest)")

    emit("")
    emit("=" * 118)
    emit("EACH LEG ALONE (PASS vs FAIL)")
    emit("=" * 118)
    for leg_key, name in (('macd','MACD'), ('h1','H1'), ('time','TIME')):
        for v in ('PASS','FAIL','INSUFFICIENT'):
            sub = [r for r in rows if r[leg_key] == v]
            if sub:
                bucket_stats(sub, f"{name}={v}")

    # --- The 15 BIG25 -------------------------------------------------------
    emit("")
    emit("=" * 118)
    emit("THE 15 BIG25 INDIVIDUALLY")
    emit("=" * 118)
    emit(f"{'date':<10} {'time':<5} {'dir':<3} {'realised':<8} "
         f"{'MACD':<5} {'H1':<5} {'TIME':<5} {'legs':<4}")
    for r in sorted([r for r in rows if r['cls']=='BIG25'],
                    key=lambda x: -x['realised']):
        emit(f"{r['date']} {r['hhmm']} {r['dir']:<3} {r['realised']:<8.2f} "
             f"{r['macd']:<5} {r['h1']:<5} {r['time']:<5} {r['passes']}")

    # --- The 10 worst losers -----------------------------------------------
    worst = sorted(rows, key=lambda r: r['realised'])[:10]
    emit("")
    emit("=" * 118)
    emit("THE 10 WORST LOSERS")
    emit("=" * 118)
    emit(f"{'date':<10} {'time':<5} {'dir':<3} {'realised':<8} "
         f"{'MACD':<5} {'H1':<5} {'TIME':<5} {'legs':<4}")
    for r in worst:
        emit(f"{r['date']} {r['hhmm']} {r['dir']:<3} {r['realised']:<8.2f} "
             f"{r['macd']:<5} {r['h1']:<5} {r['time']:<5} {r['passes']}")

    # --- Flags --------------------------------------------------------------
    emit("")
    emit("=" * 118)
    emit("FLAGS")
    emit("=" * 118)
    if flags:
        for kind, ts, n in flags:
            emit(f"  {kind:<12} {ts}  bars_found={n}")
    else:
        emit("  none")

    # --- Worked examples ---------------------------------------------------
    emit("")
    emit("=" * 118)
    emit("WORKED EXAMPLES (hand-checkable arithmetic)")
    emit("=" * 118)
    # pick first fire for MACD example
    ex_fire = fires[0]
    ex_ts   = parse_ts(ex_fire['timestamp_open'])
    ex_prior = prior_5m(ex_ts, 120)
    ex_closes = [b[4] for b in ex_prior]
    emit(f"\nMACD example — fire {ex_fire['timestamp_open']} dir={ex_fire['direction']}")
    emit(f"  entry 5m bar open: {ex_ts.replace(second=0,microsecond=0).replace(minute=(ex_ts.minute//5)*5)}")
    emit(f"  used last {len(ex_closes)} prior 5m closes (values ×10000). "
         f"Last 6 closes:")
    emit(f"    {ex_closes[-6:]}")
    e12 = ema(ex_closes, 12); e26 = ema(ex_closes, 26)
    emit(f"  EMA12[t-1]={e12[-1]:.5f}   EMA26[t-1]={e26[-1]:.5f}   "
         f"macd_line[t-1]={e12[-1]-e26[-1]:.5f}")
    emit(f"  EMA12[t-2]={e12[-2]:.5f}   EMA26[t-2]={e26[-2]:.5f}   "
         f"macd_line[t-2]={e12[-2]-e26[-2]:.5f}")
    hist = macd_hist(ex_closes)
    emit(f"  hist[t-2]={hist[-2]:.5f}   hist[t-1]={hist[-1]:.5f}   "
         f"direction={ex_fire['direction']}   "
         f"pass={'BUY: h[t-1]>h[t-2]' if ex_fire['direction']=='BUY' else 'SELL: h[t-1]<h[t-2]'}")
    m_res, _, _ = macd_leg(ex_fire, ex_closes)
    emit(f"  => MACD leg = {m_res}")

    # H1 example — same fire
    emit(f"\nH1 example — fire {ex_fire['timestamp_open']} dir={ex_fire['direction']}")
    h1 = h1_bars_before(ex_ts, 40)
    emit(f"  built {len(h1)} completed H1 bars by resampling 5m; last 3 H1 closes:")
    for b in h1[-3:]:
        emit(f"    {b[0]}  O={b[1]:.4f}  H={b[2]:.4f}  L={b[3]:.4f}  C={b[4]:.4f}")
    closes_h1 = [b[4] for b in h1]
    e7  = ema(closes_h1, 7)
    e13 = ema(closes_h1, 13)
    e21 = ema(closes_h1, 21)
    emit(f"  EMA7[last]={e7[-1]:.4f}  EMA13[last]={e13[-1]:.4f}  "
         f"EMA21[last]={e21[-1]:.4f}")
    direction = ex_fire['direction']
    if direction=='BUY':
        cond = f"opposed if e7<e13<e21 → {e7[-1]<e13[-1]<e21[-1]}"
    else:
        cond = f"opposed if e7>e13>e21 → {e7[-1]>e13[-1]>e21[-1]}"
    emit(f"  {cond}   (FAIL if opposed, PASS otherwise)")
    e_res, _, _, _ = h1_leg(ex_fire, h1)
    emit(f"  => H1 leg = {e_res}")

    # write structured data for follow-up
    with open('/tmp/bb_three_legs_rows.json','w') as w:
        json.dump(rows, w, default=str, indent=2)
    print(f"\nrows saved to /tmp/bb_three_legs_rows.json", file=sys.stderr)

if __name__ == '__main__':
    main()
