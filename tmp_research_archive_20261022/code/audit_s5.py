"""
Section 5: Bot capture vs offered.

DEFINITIONS:
* Only GBPUSD signals from both /opt/tradingbot/logs/signal_log.jsonl and
  /opt/tradingbot/data/signal_log_backfill.jsonl (merged, deduped by
  timestamp_open + strategy + direction).
* Only signals where timestamp_open falls within a qualifying RUN's window
  [start_ts, end_ts] AND the signal direction matches the run direction
  (BUY -> up; SELL -> dn).
* A run is CAPTURED if at least one directional signal fired inside its
  window. "Banked pips" = sum(pnl_pips) over those signals (nulls -> 0).
* Capture ratio = banked / magnitude. Bounded to [0, +inf) — reported raw.
* Mode families:
    - Bounce family : GBPUSD_BB_BOUNCE_L, GBPUSD_BB_BOUNCE_S, BB_REVERSAL
    - Trend family  : GBPUSD_EMA_PULLBACK_L, GBPUSD_EMA_PULLBACK_S,
                      EMA_PULLBACK, GBPUSD_TREND_V3_L, GBPUSD_TREND_V3_S,
                      GBPUSD_STRUCTURE_BREAK_L, GBPUSD_STRUCTURE_BREAK_S
    - Briefing/News : BRIEFING_EXECUTION, BRIEFING_SWEEP, BRIEFING_HUNT,
                      BRIEFING_LIQUIDITY, WINDOW_SWEEP, CONTINUATION_SWEEP,
                      REVERSAL_SWEEP
    - Other : anything else
* signal_log covers 2026-03-30 .. 2026-08-21. Runs outside this window
  cannot be scored for capture -> we RESTRICT this section to that date
  range.
"""
import os, json
from collections import defaultdict, Counter
from datetime import datetime

DAY_JL = "/opt/tradingbot/reports-public/daystruct_20260821/section1_days.jsonl"
SL_MAIN = "/opt/tradingbot/logs/signal_log.jsonl"
SL_BACK = "/opt/tradingbot/data/signal_log_backfill.jsonl"

def parse_iso(s):
    if not s: return None
    s = s.replace('Z','+00:00')
    if 'T' in s: return datetime.fromisoformat(s)
    return datetime.fromisoformat(s.replace(' ','T'))

# Load signals — GBPUSD only, merge + dedupe
signals = []
seen = set()
for src in (SL_MAIN, SL_BACK):
    if not os.path.exists(src): continue
    with open(src) as fh:
        for line in fh:
            try: r = json.loads(line)
            except: continue
            pair = r.get("pair") or r.get("epic","")
            if "GBPUSD" not in pair: continue
            t = r.get("timestamp_open")
            k = (t, r.get("strategy"), r.get("direction"), r.get("entry"))
            if k in seen: continue
            seen.add(k)
            signals.append(r)

print(f"GBPUSD signals (main+backfill, deduped): {len(signals)}")
# Direction counts
print(f"  Direction counts: {Counter(s.get('direction') for s in signals)}")
print(f"  Strategy top 20: {Counter(s.get('strategy') for s in signals).most_common(20)}")
# Date range
dates = sorted(set(s['timestamp_open'][:10] for s in signals if s.get('timestamp_open')))
print(f"  Date range: {dates[0]} .. {dates[-1]}   ({len(dates)} unique dates)")

# Mode family
BOUNCE = {"GBPUSD_BB_BOUNCE_L","GBPUSD_BB_BOUNCE_S","BB_REVERSAL"}
TREND  = {"GBPUSD_EMA_PULLBACK_L","GBPUSD_EMA_PULLBACK_S","EMA_PULLBACK",
          "GBPUSD_TREND_V3_L","GBPUSD_TREND_V3_S","GBPUSD_STRUCTURE_BREAK_L","GBPUSD_STRUCTURE_BREAK_S"}
NEWS   = {"BRIEFING_EXECUTION","BRIEFING_SWEEP","BRIEFING_HUNT","BRIEFING_LIQUIDITY",
          "WINDOW_SWEEP","CONTINUATION_SWEEP","REVERSAL_SWEEP"}
def family(s):
    if s in BOUNCE: return "bounce"
    if s in TREND:  return "trend"
    if s in NEWS:   return "news"
    return "other"

# Load days & filter to signal_log window
DAYS = []
with open(DAY_JL) as fh:
    for line in fh: DAYS.append(json.loads(line))
DAY_MIN = "2026-03-30"
DAY_MAX = "2026-08-21"
DAYS_W = [d for d in DAYS if DAY_MIN <= d['date'] <= DAY_MAX]
FULL_W = [d for d in DAYS_W if d['full_day']]

n_runs_window = sum(len(d['runs']) for d in DAYS_W)
print(f"\nQualifying runs in signal_log window ({DAY_MIN}..{DAY_MAX}): {n_runs_window} (all days), {sum(len(d['runs']) for d in FULL_W)} (full days only)")

# For each run: find matching signals
runs_scored = []
for d in DAYS_W:
    for r_idx, r in enumerate(d['runs']):
        rs = parse_iso(r['start_ts']); re = parse_iso(r['end_ts'])
        run_dir = r['direction']  # 'up' or 'dn'
        want_dir = "BUY" if run_dir == "up" else "SELL"
        matched = []
        for s in signals:
            t = parse_iso(s.get('timestamp_open'))
            if not t: continue
            if not (rs <= t <= re): continue
            if s.get('direction') != want_dir: continue
            matched.append(s)
        banked = sum((s.get('pnl_pips') or 0) for s in matched)
        capture = banked / r['magnitude_pips'] if r['magnitude_pips'] > 0 else 0
        runs_scored.append({
            "date": d['date'], "weekday": d['weekday'], "day_class": d['day_class'],
            "run_idx": r_idx, "start_hhmm": r['start_hhmm'], "direction": r['direction'],
            "magnitude": r['magnitude_pips'], "label": r['label'],
            "n_fires": len(matched), "banked_pips": round(banked,1),
            "capture_ratio": round(capture,3),
            "families": Counter(family(s.get('strategy')) for s in matched),
        })

# Overall
n = len(runs_scored)
captured = sum(1 for r in runs_scored if r['n_fires']>0)
print(f"\nRuns in scored window: {n}")
print(f"Runs with any directional fire: {captured} ({100*captured/n:.1f}%)")
print(f"Runs with ZERO directional fires: {n-captured} ({100*(n-captured)/n:.1f}%)")

# Capture ratio distribution
caps = [r['capture_ratio'] for r in runs_scored]
caps_pos = [c for c in caps if c>0]
banks = [r['banked_pips'] for r in runs_scored]
def pct(a,p):
    if not a: return None
    a=sorted(a); return a[int(round((len(a)-1)*p))]
print(f"\nCapture ratio (all runs)  p10={pct(caps,0.1)}  p25={pct(caps,0.25)}  p50={pct(caps,0.5)}  p75={pct(caps,0.75)}  p90={pct(caps,0.9)}  max={max(caps)}")
print(f"Capture ratio (captured runs only n={len(caps_pos)})  p25={pct(caps_pos,0.25)}  p50={pct(caps_pos,0.5)}  p75={pct(caps_pos,0.75)}  p90={pct(caps_pos,0.9)}")
print(f"Total offered magnitude: {sum(r['magnitude'] for r in runs_scored):.1f}p")
print(f"Total banked (directional in-window): {sum(banks):.1f}p")

# By family (a run may have fires from multiple families — categorize by dominant, i.e., family with most fires)
def dominant_family(r):
    if not r['families']: return None
    return r['families'].most_common(1)[0][0]
print(f"\nBy dominant family (of runs with fires):")
fam_stats = defaultdict(lambda: {"n":0, "banked":0.0, "offered":0.0})
for r in runs_scored:
    f = dominant_family(r)
    if f is None: continue
    fam_stats[f]["n"] += 1
    fam_stats[f]["banked"] += r['banked_pips']
    fam_stats[f]["offered"] += r['magnitude']
for f, s in sorted(fam_stats.items(), key=lambda x:-x[1]['banked']):
    print(f"  {f:<8} n={s['n']:>3}  banked={s['banked']:>6.1f}p  offered={s['offered']:>6.1f}p  ratio={s['banked']/s['offered'] if s['offered'] else 0:.2%}")

# By day_class
print(f"\nBy day_class:")
dc_stats = defaultdict(lambda: {"runs":0,"captured":0,"banked":0.0,"offered":0.0})
for r in runs_scored:
    dc = r['day_class']
    dc_stats[dc]['runs'] += 1
    dc_stats[dc]['offered'] += r['magnitude']
    dc_stats[dc]['banked'] += r['banked_pips']
    if r['n_fires']>0: dc_stats[dc]['captured'] += 1
for dc in ["BOUNCE_DAY","GRIND_DAY","MULTI_DAY","QUIET_DAY"]:
    s = dc_stats[dc]
    if s['runs']==0: continue
    print(f"  {dc:<11} runs={s['runs']:>3}  captured={s['captured']:>3}  banked={s['banked']:>6.1f}p  offered={s['offered']:>6.1f}p  ratio={s['banked']/s['offered'] if s['offered'] else 0:.2%}")

# By start-time bucket (30min)
print(f"\nBy first-run start-time bucket (30-min UTC):")
def bkt(h): 
    hh,mm = h.split(':'); return f"{int(hh):02d}:{'30' if int(mm)>=30 else '00'}"
bkt_stats = defaultdict(lambda: {"runs":0,"captured":0,"banked":0.0,"offered":0.0})
for r in runs_scored:
    b = bkt(r['start_hhmm'])
    bkt_stats[b]['runs'] += 1
    bkt_stats[b]['offered'] += r['magnitude']
    bkt_stats[b]['banked'] += r['banked_pips']
    if r['n_fires']>0: bkt_stats[b]['captured'] += 1
for b in sorted(bkt_stats):
    s = bkt_stats[b]
    if s['runs']<3: continue  # skip thin cells
    print(f"  {b}  runs={s['runs']:>3}  captured={s['captured']:>3}  banked={s['banked']:>6.1f}p  offered={s['offered']:>6.1f}p  ratio={s['banked']/s['offered'] if s['offered'] else 0:.2%}")

# Misses: zero-fire runs, profile
misses = [r for r in runs_scored if r['n_fires']==0]
print(f"\nZero-fire runs (misses): {len(misses)}")
print(f"  by day_class: {Counter(r['day_class'] for r in misses)}")
print(f"  by start-hour (int):")
miss_hr = Counter(int(r['start_hhmm'].split(':')[0]) for r in misses)
for h in sorted(miss_hr): print(f"    {h:02d}h: {miss_hr[h]}")
print(f"  Average missed magnitude: {sum(r['magnitude'] for r in misses)/max(len(misses),1):.1f}p")
print(f"  Total missed magnitude: {sum(r['magnitude'] for r in misses):.1f}p")

# Save
with open("/opt/tradingbot/reports-public/daystruct_20260821/section5_capture.json","w") as fh:
    json.dump({
        "runs_in_window": n, "captured_runs": captured, "missed_runs": n-captured,
        "total_offered_pips": round(sum(r['magnitude'] for r in runs_scored),1),
        "total_banked_pips": round(sum(banks),1),
        "capture_ratio_pctiles": {"p10":pct(caps,0.1),"p25":pct(caps,0.25),"p50":pct(caps,0.5),"p75":pct(caps,0.75),"p90":pct(caps,0.9)},
        "by_family": {k: {"n":v["n"],"banked":round(v["banked"],1),"offered":round(v["offered"],1)} for k,v in fam_stats.items()},
        "by_day_class": {k: {"runs":v["runs"],"captured":v["captured"],"banked":round(v["banked"],1),"offered":round(v["offered"],1)} for k,v in dc_stats.items()},
        "by_start_bucket": {k: {"runs":v["runs"],"captured":v["captured"],"banked":round(v["banked"],1),"offered":round(v["offered"],1)} for k,v in bkt_stats.items()},
        "misses_by_day_class": Counter(r['day_class'] for r in misses),
        "misses_by_hour": dict(miss_hr),
        "signal_log_window": [DAY_MIN, DAY_MAX],
    }, fh, indent=2)
# Save per-run detail too
with open("/opt/tradingbot/reports-public/daystruct_20260821/section5_runs.jsonl","w") as fh:
    for r in runs_scored:
        r['families'] = dict(r['families'])
        fh.write(json.dumps(r)+"\n")
print("\nCheckpoint -> section5_capture.json + section5_runs.jsonl")
