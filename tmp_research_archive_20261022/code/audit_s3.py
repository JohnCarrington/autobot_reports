"""Section 3: weekday cut."""
import json
from collections import Counter, defaultdict

DAYS = []
with open("/opt/tradingbot/reports-public/daystruct_20260821/section1_days.jsonl") as fh:
    for line in fh: DAYS.append(json.loads(line))
FULL = [d for d in DAYS if d['full_day']]

WEEK = ['Mon','Tue','Wed','Thu','Fri']
def hhmm_to_min(s): h,m = s.split(':'); return int(h)*60+int(m)

# Per weekday: n_days, n_runs_avg, mean/median day_range, day_class mix
print(f"Full weekday days breakdown (n={len([d for d in FULL if d['weekday'] in WEEK])}):\n")
print(f"{'Day':>4} {'n':>4} {'runs_mean':>10} {'runs_median':>11} {'range_mean':>10} {'range_med':>10} {'BOUNCE':>7} {'GRIND':>6} {'QUIET':>6} {'MULTI':>6}")
per_wd = {}
for wd in WEEK:
    sub = [d for d in FULL if d['weekday']==wd]
    n = len(sub)
    if n == 0: continue
    runs = sorted([d['n_runs_40p'] for d in sub])
    ranges = sorted([d['day_range_pips'] for d in sub])
    runs_mean = sum(runs)/n
    runs_med = runs[n//2]
    range_mean = sum(ranges)/n
    range_med = ranges[n//2]
    cls = Counter(d['day_class'] for d in sub)
    per_wd[wd] = {"n":n, "runs_mean":round(runs_mean,2), "runs_median":runs_med,
                  "range_mean":round(range_mean,1), "range_median":round(range_med,1),
                  "class_mix":dict(cls)}
    print(f"{wd:>4} {n:>4} {runs_mean:>10.2f} {runs_med:>11.1f} {range_mean:>10.1f} {range_med:>10.1f} {cls.get('BOUNCE_DAY',0):>7} {cls.get('GRIND_DAY',0):>6} {cls.get('QUIET_DAY',0):>6} {cls.get('MULTI_DAY',0):>6}")

# Thin cell flag: n<20
print("\nThin cells (n<20 for any cross-tab): flag on weekdays with n<20; none here since each weekday has ~28 days.")

# First-run bucket by weekday (London filter)
print(f"\nFirst-London-run bucket histogram BY WEEKDAY:")
print(f"  (columns are 30-min UTC buckets; row totals in parentheses)")
buckets = [f"{h:02d}:{m:02d}" for h in range(6,18) for m in (0,30)]
per_wd_bucket = {wd: Counter() for wd in WEEK}
per_wd_n = {wd: 0 for wd in WEEK}
for d in FULL:
    wd = d['weekday']
    if wd not in WEEK: continue
    lon = [r for r in d['runs'] if hhmm_to_min(r['start_hhmm']) >= 6*60]
    if lon:
        h,m = lon[0]['start_hhmm'].split(':'); h=int(h); m=int(m); b_lo=30 if m>=30 else 0
        per_wd_bucket[wd][f"{h:02d}:{b_lo:02d}"] += 1
        per_wd_n[wd] += 1

# Print table
print(f"  {'bucket':>6}", end="")
for wd in WEEK: print(f" {wd:>4}", end="")
print()
for b in buckets:
    row = f"  {b:>6}"
    any_nonzero = False
    for wd in WEEK:
        v = per_wd_bucket[wd][b]
        row += f" {v:>4}"
        if v: any_nonzero = True
    if any_nonzero: print(row)
print(f"  {'total':>6}", end="")
for wd in WEEK: print(f" {per_wd_n[wd]:>4}", end="")
print()

# Magnitude by weekday
print(f"\nRun magnitude (mean/median) BY WEEKDAY, using all qualifying runs (any-hour):")
for wd in WEEK:
    ms = sorted([r['magnitude_pips'] for d in FULL if d['weekday']==wd for r in d['runs']])
    if not ms: continue
    m_med = ms[len(ms)//2]
    m_mean = sum(ms)/len(ms)
    print(f"  {wd}: n_runs={len(ms):>3}  mean={m_mean:.1f}p  median={m_med:.1f}p")

# Grind rate by weekday
print(f"\nGrind rate by weekday:")
for wd in WEEK:
    sub = [d for d in FULL if d['weekday']==wd]
    g = sum(1 for d in sub if d['grind'])
    print(f"  {wd}: {g}/{len(sub)} = {100*g/max(len(sub),1):.1f}%")

# Save
with open("/opt/tradingbot/reports-public/daystruct_20260821/section3_weekday.json","w") as fh:
    json.dump({"per_weekday": per_wd,
               "first_bucket_by_weekday": {wd:dict(v) for wd,v in per_wd_bucket.items()},
               "first_bucket_n_by_weekday": per_wd_n}, fh, indent=2)
