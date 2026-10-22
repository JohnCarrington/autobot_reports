"""
Section 1: Run detection per day.

DEFINITIONS (stated once, applied uniformly):

* Trading day: UTC 00:00 through 23:55 on the calendar date, using rows from
  that date's CSV file. Sunday-evening partial files kept as-is and flagged.
  Prices are given as native ×10000 (e.g. 13471.5 = 1.34715). 1 pip = 0.0001,
  so pip conversion is (price_hi - price_lo)/1.0. We report all magnitudes
  in pips = raw price units / 1 (since raw is ×10000 = pip units).

* Zigzag (swing) method: applied to 5m CLOSES only (not H/L). We walk
  chronologically from the first close of the day. Maintain running swing
  extreme (extreme close since last confirmed pivot) and the pivot that
  preceded it. When the current close reverses from the running extreme by
  >= REV_PIPS pips, we confirm the running extreme as a pivot and flip
  direction. At end of day we accept the final pivot even if not confirmed
  by a full reversal. Chosen REV_PIPS = 15 pips.

  Rationale: a 15-pip reversal on 5m closes is large enough to reject
  intraday noise but small enough that a genuine 40p run resolves into
  a single leg (its counter-swing has to be >=15p to break it).

* Leg / run: the segment from one confirmed pivot to the next. Its
  magnitude is |close_end - close_start| in pips. A LEG qualifies as a
  RUN if magnitude >= 40 pips.

* Bounce vs continuation: at the RUN's start pivot, compute the net move
  from that day's first 5m close to the pivot price. If that net move is
  >= 20p AGAINST the run direction, the run is a BOUNCE. If it is >= 20p
  in the SAME direction as the run, it is a CONTINUATION. Otherwise
  (day-open net < 20p from pivot start), label AMBIGUOUS.

* First run / second run: the first two RUNs of the day in chronological
  order. Their start times are recorded for the Section 2 histogram.

* Grind test (applied per day):
    GRIND_DAY iff:
      day_range = max(high) - min(low)  over all 5m bars   >= 60 pips
      AND
      day_net_move = |close_last - close_first|            >= 0.70 * day_range
    Additionally we flag GRIND_100 if net_move >= 100p.

* Day classification (Section 2):
    QUIET_DAY: 0 runs of >=40p
    BOUNCE_DAY: 1 or 2 runs of >=40p AND not GRIND_DAY
    MULTI_DAY: 3+ runs of >=40p (regardless of grind status)
    GRIND_DAY: passes grind test (this overrides BOUNCE if both would apply,
               reflecting the operator's model of grinds as a separate mode)

* Sensitivity: we also compute run counts at REV_PIPS = 10 and 20 and
  report per-day divergence as a diagnostic.

Prices: candles are stored as native price * 10000 (e.g. 13471.50 = 1.34715).
So raw units already ARE pips (13471.5 - 13461.5 = 10.0 pips). We use raw
directly as pip units throughout.
"""
import os, glob, csv, json
from datetime import datetime, date
from collections import defaultdict

CAND_DIR = "/opt/tradingbot/data/candles/GBPUSD"
OUT_DIR  = "/opt/tradingbot/reports-public/daystruct_20260821"
os.makedirs(OUT_DIR, exist_ok=True)

REV_PIPS_MAIN = 15.0
REV_PIPS_LOW  = 10.0
REV_PIPS_HIGH = 20.0
RUN_MIN       = 40.0
GRIND_RANGE_MIN = 60.0
GRIND_RATIO   = 0.70
GRIND_100     = 100.0
BOUNCE_DAYOPEN_THRESH = 20.0

def parse_ts(s):
    s = s.strip()
    if 'T' in s: return datetime.fromisoformat(s.replace('Z','+00:00'))
    return datetime.fromisoformat(s.replace(' ','T').replace('Z','+00:00'))

def load_day(fpath):
    """Return list of dicts {ts, o, h, l, c} for a single day file."""
    out = []
    with open(fpath) as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                out.append({
                    "ts": parse_ts(row["timestamp"]),
                    "o": float(row["open"]),
                    "h": float(row["high"]),
                    "l": float(row["low"]),
                    "c": float(row["close"]),
                })
            except Exception:
                continue
    return out

def zigzag(bars, rev):
    """
    Simple zigzag on closes. Return list of pivots [(ts, price, kind)]
    where kind in {'H','L'}. First pivot is bar 0 (kind by direction of first leg).
    """
    if len(bars) < 2: return []
    pivots = []
    # bootstrap: use first bar as initial pivot; direction will be set when
    # first close moves > threshold from it in one direction consistently.
    p0 = bars[0]
    running_ext_i = 0
    direction = None  # 'up' means seeking higher, current run is up
    for i, b in enumerate(bars):
        if direction is None:
            # look for first meaningful move
            diff = b['c'] - p0['c']
            if abs(diff) >= rev:
                direction = 'up' if diff > 0 else 'dn'
                # p0 becomes first pivot (L if up leg started, H if down)
                pivots.append((p0['ts'], p0['c'], 'L' if direction=='up' else 'H'))
                running_ext_i = i
            elif direction is None and (b['c'] < p0['c']):
                # track the more-extreme candidate
                if b['c'] < bars[running_ext_i]['c']:
                    running_ext_i = i
            elif direction is None and (b['c'] > p0['c']):
                if b['c'] > bars[running_ext_i]['c']:
                    running_ext_i = i
            continue
        cur_ext = bars[running_ext_i]
        if direction == 'up':
            if b['c'] > cur_ext['c']:
                running_ext_i = i
            elif (cur_ext['c'] - b['c']) >= rev:
                pivots.append((cur_ext['ts'], cur_ext['c'], 'H'))
                direction = 'dn'
                running_ext_i = i
        else:  # down
            if b['c'] < cur_ext['c']:
                running_ext_i = i
            elif (b['c'] - cur_ext['c']) >= rev:
                pivots.append((cur_ext['ts'], cur_ext['c'], 'L'))
                direction = 'up'
                running_ext_i = i
    # tail pivot: accept the running extreme as final pivot if not equal to last recorded
    if pivots:
        last_ts = pivots[-1][0]
        last_pr = pivots[-1][1]
        cur_ext = bars[running_ext_i]
        if cur_ext['ts'] != last_ts and abs(cur_ext['c'] - last_pr) > 0:
            # last kind opposite of pivots[-1]
            k = 'H' if pivots[-1][2] == 'L' else 'L'
            pivots.append((cur_ext['ts'], cur_ext['c'], k))
    return pivots

def analyse_day(fname, bars):
    """Return dict of day analytics."""
    if not bars: return None
    day = os.path.basename(fname).replace(".csv","")
    dt = datetime.fromisoformat(day)
    weekday = dt.strftime("%a")

    day_first_close = bars[0]['c']
    day_last_close  = bars[-1]['c']
    day_high = max(b['h'] for b in bars)
    day_low  = min(b['l'] for b in bars)
    day_range = day_high - day_low
    day_net_signed = day_last_close - day_first_close
    day_net_abs = abs(day_net_signed)
    is_full = len(bars) >= 200  # partial-day guard

    # Zigzag main
    pivots = zigzag(bars, REV_PIPS_MAIN)
    runs = []
    for i in range(len(pivots)-1):
        p_a = pivots[i]; p_b = pivots[i+1]
        magnitude = abs(p_b[1] - p_a[1])
        if magnitude < RUN_MIN: continue
        direction = 'up' if p_b[1] > p_a[1] else 'dn'
        # dayopen net at pivot start
        net_at_start = p_a[1] - day_first_close
        if direction == 'up':
            if net_at_start <= -BOUNCE_DAYOPEN_THRESH: label = 'BOUNCE'
            elif net_at_start >= BOUNCE_DAYOPEN_THRESH: label = 'CONTINUATION'
            else: label = 'AMBIGUOUS'
        else:
            if net_at_start >= BOUNCE_DAYOPEN_THRESH: label = 'BOUNCE'
            elif net_at_start <= -BOUNCE_DAYOPEN_THRESH: label = 'CONTINUATION'
            else: label = 'AMBIGUOUS'
        runs.append({
            "start_ts": p_a[0].isoformat(),
            "end_ts": p_b[0].isoformat(),
            "start_hhmm": p_a[0].strftime("%H:%M"),
            "duration_min": int((p_b[0] - p_a[0]).total_seconds()/60),
            "direction": direction,
            "magnitude_pips": round(magnitude, 1),
            "label": label,
        })

    # Grind classification
    grind = (day_range >= GRIND_RANGE_MIN) and (day_net_abs >= GRIND_RATIO * day_range)
    grind_100 = grind and (day_net_abs >= GRIND_100)

    n_runs = len(runs)
    if grind:
        day_class = "GRIND_DAY"
    elif n_runs == 0:
        day_class = "QUIET_DAY"
    elif n_runs >= 3:
        day_class = "MULTI_DAY"
    else:
        day_class = "BOUNCE_DAY"

    # Sensitivity: run counts at low/high thresholds
    p_lo = zigzag(bars, REV_PIPS_LOW)
    n_runs_lo = sum(1 for i in range(len(p_lo)-1) if abs(p_lo[i+1][1]-p_lo[i][1]) >= RUN_MIN)
    p_hi = zigzag(bars, REV_PIPS_HIGH)
    n_runs_hi = sum(1 for i in range(len(p_hi)-1) if abs(p_hi[i+1][1]-p_hi[i][1]) >= RUN_MIN)

    return {
        "date": day, "weekday": weekday, "bars": len(bars), "full_day": is_full,
        "first_close": round(day_first_close,2), "last_close": round(day_last_close,2),
        "day_high": round(day_high,2), "day_low": round(day_low,2),
        "day_range_pips": round(day_range,1),
        "day_net_pips": round(day_net_signed,1),
        "day_net_abs_pips": round(day_net_abs,1),
        "grind_ratio": round(day_net_abs/day_range if day_range>0 else 0, 3),
        "grind": grind, "grind_100": grind_100,
        "n_runs_40p": n_runs,
        "n_runs_40p_rev10": n_runs_lo,
        "n_runs_40p_rev20": n_runs_hi,
        "runs": runs,
        "day_class": day_class,
    }

files = sorted(glob.glob(f"{CAND_DIR}/2026-*.csv"))
all_days = []
for f in files:
    bars = load_day(f)
    if not bars: continue
    row = analyse_day(f, bars)
    if row: all_days.append(row)

# Save full per-day inventory
with open(f"{OUT_DIR}/section1_days.jsonl","w") as fh:
    for r in all_days:
        fh.write(json.dumps(r)+"\n")

# Summary
n_days = len(all_days)
n_full = sum(1 for d in all_days if d['full_day'])
n_partial = n_days - n_full
class_counts = defaultdict(int)
for d in all_days: class_counts[d['day_class']] += 1

run_count_hist = defaultdict(int)
for d in all_days: run_count_hist[d['n_runs_40p']] += 1

all_runs = [r for d in all_days for r in d['runs']]
mag_bins = defaultdict(int)
for r in all_runs:
    m = r['magnitude_pips']
    if m < 40: continue
    if m < 50: mag_bins['40-49'] += 1
    elif m < 60: mag_bins['50-59'] += 1
    elif m < 70: mag_bins['60-69'] += 1
    elif m < 80: mag_bins['70-79'] += 1
    elif m < 100: mag_bins['80-99'] += 1
    else: mag_bins['100+'] += 1

# Sensitivity divergence
diff_lo = sum(1 for d in all_days if d['n_runs_40p'] != d['n_runs_40p_rev10'])
diff_hi = sum(1 for d in all_days if d['n_runs_40p'] != d['n_runs_40p_rev20'])

print(f"Days analysed: {n_days} (full={n_full}, partial={n_partial})")
print(f"Day class counts: {dict(class_counts)}")
print(f"Runs-per-day histogram (>=40p @ rev=15): {dict(sorted(run_count_hist.items()))}")
print(f"Total qualifying runs: {len(all_runs)}")
print(f"Run magnitude bins: {dict(mag_bins)}")
print(f"Sensitivity — days where n_runs differs from rev=15 count:")
print(f"  rev=10 -> {diff_lo}/{n_days} days differ")
print(f"  rev=20 -> {diff_hi}/{n_days} days differ")

# Grind-100 list
g100 = [d['date']+' ('+d['weekday']+', '+str(d['day_net_pips'])+'p net, range '+str(d['day_range_pips'])+'p)'
        for d in all_days if d['grind_100']]
print(f"\nGrind-100 days ({len(g100)}):")
for x in g100: print(f"  {x}")

grinds = [d for d in all_days if d['grind']]
print(f"\nAll grinds ({len(grinds)}):")
for d in grinds:
    print(f"  {d['date']} {d['weekday']}: net={d['day_net_pips']}p range={d['day_range_pips']}p ratio={d['grind_ratio']} class={d['day_class']}")

print(f"\nQuiet days: {class_counts['QUIET_DAY']}, sample:")
for d in [x for x in all_days if x['day_class']=='QUIET_DAY'][:10]:
    print(f"  {d['date']} {d['weekday']} bars={d['bars']} range={d['day_range_pips']}p")
