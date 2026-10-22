"""Section 2: Model fit."""
import json, os
from collections import defaultdict, Counter

DAYS = []
with open("/opt/tradingbot/reports-public/daystruct_20260821/section1_days.jsonl") as fh:
    for line in fh: DAYS.append(json.loads(line))

# Filter: use full days only for headline percentages
FULL = [d for d in DAYS if d['full_day']]
PART = [d for d in DAYS if not d['full_day']]
print(f"Full days: {len(FULL)}   Partial days (excluded from headline %): {len(PART)}")
print("  Partial days breakdown by weekday:", Counter(d['weekday'] for d in PART))

# (a) Runs-per-day distribution — full days
runs_hist = Counter(d['n_runs_40p'] for d in FULL)
tot = sum(runs_hist.values())
print("\n(a) Runs-per-day distribution [full days only, n={}]:".format(tot))
print(f"{'n_runs':>7} {'count':>6} {'pct':>6}")
for k in sorted(runs_hist):
    print(f"{k:>7} {runs_hist[k]:>6} {100*runs_hist[k]/tot:>5.1f}%")
mode_12 = runs_hist[1] + runs_hist[2]
print(f"  Model mode (1-2 runs): {mode_12}/{tot} = {100*mode_12/tot:.1f}%")

# (b) start-time histogram — first-run and second-run — 30min buckets
def bucket(hhmm):
    h,m = hhmm.split(':')
    m = int(m); h = int(h)
    b = 30 if m>=30 else 0
    return f"{h:02d}:{b:02d}"

first_hist = Counter()
second_hist = Counter()
for d in FULL:
    if len(d['runs']) >= 1: first_hist[bucket(d['runs'][0]['start_hhmm'])] += 1
    if len(d['runs']) >= 2: second_hist[bucket(d['runs'][1]['start_hhmm'])] += 1

# Print buckets in chronological order
all_buckets = sorted(set(list(first_hist.keys())+list(second_hist.keys())))
print(f"\n(b) Start-time histogram — first & second runs [full days, 30min UTC buckets]")
print(f"    n_days_with_first_run = {sum(first_hist.values())}  n_days_with_second = {sum(second_hist.values())}")
print(f"{'bucket':>6} {'1st':>6} {'2nd':>6}")
for b in all_buckets:
    if first_hist[b] or second_hist[b]:
        print(f"{b:>6} {first_hist[b]:>6} {second_hist[b]:>6}")

# Anchor evaluation: model predicts London 08/10/11/12, PM 14/15/16
# Widen to +/-30min around each anchor
def in_anchor(hhmm, anchors, halfwin_min=30):
    h,m = hhmm.split(':'); h=int(h); m=int(m); mins = h*60+m
    for a in anchors:
        if abs(mins - a*60) <= halfwin_min: return True
    return False

first_anchor_hits = sum(1 for d in FULL if d['runs'] and in_anchor(d['runs'][0]['start_hhmm'], [8,10,11,12]))
first_total = sum(1 for d in FULL if d['runs'])
second_anchor_hits = sum(1 for d in FULL if len(d['runs'])>=2 and in_anchor(d['runs'][1]['start_hhmm'], [14,15,16]))
second_total = sum(1 for d in FULL if len(d['runs'])>=2)
print(f"\nFirst-run within ±30min of {{08,10,11,12}} UTC: {first_anchor_hits}/{first_total} = {100*first_anchor_hits/max(first_total,1):.1f}%")
print(f"Second-run within ±30min of {{14,15,16}} UTC: {second_anchor_hits}/{second_total} = {100*second_anchor_hits/max(second_total,1):.1f}%")

# (c) Magnitude distribution
all_runs = [r for d in DAYS for r in d['runs']]  # count all runs regardless of full/partial (partial days still have runs)
mag_bins = [(40,50),(50,60),(60,70),(70,80),(80,100),(100,150),(150,999)]
print(f"\n(c) Magnitude distribution [all {len(all_runs)} runs]")
for lo,hi in mag_bins:
    c = sum(1 for r in all_runs if lo <= r['magnitude_pips'] < hi)
    print(f"  [{lo:>3}-{hi if hi<999 else '  +'}): {c:>4}  ({100*c/len(all_runs):.1f}%)")
mags = [r['magnitude_pips'] for r in all_runs]
mags.sort()
def pct(p): 
    i = int(round((len(mags)-1)*p))
    return mags[i]
print(f"  p25={pct(0.25)}p  median={pct(0.5)}p  p75={pct(0.75)}p  p90={pct(0.9)}p  max={mags[-1]}p")

# Bounce vs Continuation labels
lbl_ct = Counter(r['label'] for r in all_runs)
print(f"\n  Bounce/Continuation labels: {dict(lbl_ct)}")

# (d) Day classification — full days
cls_full = Counter(d['day_class'] for d in FULL)
tot_f = sum(cls_full.values())
print(f"\n(d) Day classification [full days only, n={tot_f}]:")
for k,v in sorted(cls_full.items(), key=lambda x:-x[1]):
    print(f"  {k:<12} {v:>4}  {100*v/tot_f:.1f}%")
# BOUNCE_DAY is 1-2 non-grind runs => the operator model prediction cell
bounce_or_grind = cls_full['BOUNCE_DAY'] + cls_full['GRIND_DAY']  # both are 'expected' shapes
print(f"  Sum(BOUNCE + GRIND): {bounce_or_grind}/{tot_f} = {100*bounce_or_grind/tot_f:.1f}%  (model's 'normal' shape)")

# checkpoint save
with open("/opt/tradingbot/reports-public/daystruct_20260821/section2_modelfit.json","w") as fh:
    json.dump({
        "n_full_days": len(FULL), "n_partial_days": len(PART),
        "runs_per_day_hist": dict(runs_hist),
        "first_run_bucket_hist": dict(first_hist),
        "second_run_bucket_hist": dict(second_hist),
        "first_anchor_hit_pct": round(100*first_anchor_hits/max(first_total,1),1),
        "second_anchor_hit_pct": round(100*second_anchor_hits/max(second_total,1),1),
        "magnitude_percentiles": {"p25":pct(0.25),"p50":pct(0.5),"p75":pct(0.75),"p90":pct(0.9),"max":mags[-1]},
        "bounce_cont_labels": dict(lbl_ct),
        "day_class_full": dict(cls_full),
    }, fh, indent=2)
print("\nCheckpoint -> section2_modelfit.json")
