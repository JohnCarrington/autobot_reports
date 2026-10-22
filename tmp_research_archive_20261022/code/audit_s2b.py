"""Section 2 refinement: first LONDON-session run, anchor test."""
import json
from collections import Counter, defaultdict

DAYS = []
with open("/opt/tradingbot/reports-public/daystruct_20260821/section1_days.jsonl") as fh:
    for line in fh: DAYS.append(json.loads(line))
FULL = [d for d in DAYS if d['full_day']]

def hhmm_to_min(s): h,m = s.split(':'); return int(h)*60+int(m)
def bucket(hhmm): 
    h,m = hhmm.split(':'); h=int(h); m=int(m)
    b = 30 if m>=30 else 0
    return f"{h:02d}:{b:02d}"

# First run whose start >= 06:00 UTC = "first London run"
first_lo = Counter()
first_lo_bucket = Counter()
second_lo_bucket = Counter()
n_days_with_london_first = 0
n_days_with_second_pm = 0

for d in FULL:
    lon = [r for r in d['runs'] if hhmm_to_min(r['start_hhmm']) >= 6*60]
    if lon:
        first_lo[lon[0]['start_hhmm']] += 1
        first_lo_bucket[bucket(lon[0]['start_hhmm'])] += 1
        n_days_with_london_first += 1
        # second run = next after first_lo that starts >= first_lo end
        # simplify: any run that starts after first_lo[0] and start >= 13:00
        pm = [r for r in d['runs'] if hhmm_to_min(r['start_hhmm']) >= 13*60 and r['start_hhmm'] > lon[0]['start_hhmm']]
        if pm:
            second_lo_bucket[bucket(pm[0]['start_hhmm'])] += 1
            n_days_with_second_pm += 1

print(f"Days with first-run start >= 06:00 UTC: {n_days_with_london_first}/{len(FULL)}")
print(f"\nFirst-run bucket histogram (30min UTC, >=06:00 only):")
for b in sorted(first_lo_bucket):
    print(f"  {b}   {first_lo_bucket[b]:>4}")

# Anchor hits with widened window
def in_anchor(hhmm, anchors, halfwin_min=45):
    mm = hhmm_to_min(hhmm)
    return any(abs(mm - a*60) <= halfwin_min for a in anchors)

first_anchor = sum(1 for d in FULL for r in d['runs'][:1] if hhmm_to_min(r['start_hhmm'])>=6*60 and in_anchor(r['start_hhmm'],[8,10,11,12], 45))
# but that's iterating wrong; redo
first_anchor = 0
first_anchor_15 = 0
for d in FULL:
    lon = [r for r in d['runs'] if hhmm_to_min(r['start_hhmm']) >= 6*60]
    if not lon: continue
    if in_anchor(lon[0]['start_hhmm'],[8,10,11,12], 45): first_anchor += 1
    if in_anchor(lon[0]['start_hhmm'],[8,10,11,12], 15): first_anchor_15 += 1

second_anchor = 0
second_anchor_15 = 0
for d in FULL:
    lon = [r for r in d['runs'] if hhmm_to_min(r['start_hhmm']) >= 6*60]
    if not lon: continue
    pm = [r for r in d['runs'] if hhmm_to_min(r['start_hhmm']) >= 13*60 and r['start_hhmm'] > lon[0]['start_hhmm']]
    if not pm: continue
    if in_anchor(pm[0]['start_hhmm'],[14,15,16], 45): second_anchor += 1
    if in_anchor(pm[0]['start_hhmm'],[14,15,16], 15): second_anchor_15 += 1

print(f"\nFIRST-London-run within ±45min of {{08,10,11,12}} UTC: {first_anchor}/{n_days_with_london_first} = {100*first_anchor/max(n_days_with_london_first,1):.1f}%")
print(f"FIRST-London-run within ±15min of {{08,10,11,12}} UTC: {first_anchor_15}/{n_days_with_london_first} = {100*first_anchor_15/max(n_days_with_london_first,1):.1f}%")
print(f"SECOND-PM-run within ±45min of {{14,15,16}} UTC: {second_anchor}/{n_days_with_second_pm} = {100*second_anchor/max(n_days_with_second_pm,1):.1f}%")
print(f"SECOND-PM-run within ±15min of {{14,15,16}} UTC: {second_anchor_15}/{n_days_with_second_pm} = {100*second_anchor_15/max(n_days_with_second_pm,1):.1f}%")

# Second run bucket
print(f"\nSECOND-PM-run bucket histogram (30min UTC, >=13:00 only):")
for b in sorted(second_lo_bucket):
    print(f"  {b}   {second_lo_bucket[b]:>4}")

# Save
with open("/opt/tradingbot/reports-public/daystruct_20260821/section2b_london_anchors.json","w") as fh:
    json.dump({
        "n_days_with_london_first": n_days_with_london_first,
        "first_bucket_hist": dict(first_lo_bucket),
        "second_bucket_hist": dict(second_lo_bucket),
        "first_anchor_pct_45min": round(100*first_anchor/max(n_days_with_london_first,1),1),
        "first_anchor_pct_15min": round(100*first_anchor_15/max(n_days_with_london_first,1),1),
        "second_anchor_pct_45min": round(100*second_anchor/max(n_days_with_second_pm,1),1),
        "second_anchor_pct_15min": round(100*second_anchor_15/max(n_days_with_second_pm,1),1),
    }, fh, indent=2)
