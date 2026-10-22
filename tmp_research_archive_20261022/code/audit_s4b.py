"""Section 4 tightened: tier-1 events only."""
import os, glob, json
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict

NEWS = "/opt/tradingbot/cache"
DAY_JL = "/opt/tradingbot/reports-public/daystruct_20260821/section1_days.jsonl"

# Load all news events
events_by_day = defaultdict(list)
for f in sorted(glob.glob(f"{NEWS}/news_state_finnhub_*.json")):
    with open(f) as fh: j = json.load(fh)
    d = j.get("date")
    if not d: continue
    for e in j.get("events", []):
        events_by_day[d].append(e)
for d in events_by_day:
    seen=set(); uniq=[]
    for e in events_by_day[d]:
        k=(e.get("ts"), e.get("event"), e.get("currency"), e.get("impact"))
        if k in seen: continue
        seen.add(k); uniq.append(e)
    events_by_day[d]=uniq

# TIER1 event definition (operator-relevant top-tier moves)
TIER1_PATTERNS = [
    ("NFP",       "USD", ["Non Farm Payrolls"]),
    ("FOMC",      "USD", ["Fed Interest Rate Decision", "FOMC Economic Projections", "Fed Press Conference"]),
    ("US_CPI",    "USD", ["Inflation Rate YoY", "Inflation Rate MoM", "Core Inflation Rate YoY", "Core Inflation Rate MoM"]),
    ("US_PPI",    "USD", ["PPI MoM"]),
    ("US_RETAIL", "USD", ["Retail Sales MoM"]),
    ("US_GDP",    "USD", ["GDP Growth Rate QoQ Adv", "GDP Growth Rate QoQ 2nd Est", "GDP Growth Rate QoQ Final"]),
    ("ISM_MFG",   "USD", ["ISM Manufacturing PMI"]),
    ("ISM_SVC",   "USD", ["ISM Services PMI"]),
    ("BOE",       "GBP", ["BoE Interest Rate Decision"]),
    ("UK_CPI",    "GBP", ["Inflation Rate YoY"]),
    ("UK_GDP",    "GBP", ["GDP Growth Rate QoQ Prel", "GDP Growth Rate QoQ 2nd Est", "GDP Growth Rate QoQ Final", "GDP MoM"]),
    ("UK_UNEM",   "GBP", ["Unemployment Rate"]),
    ("UK_RETAIL", "GBP", ["Retail Sales MoM"]),
    ("US_JOBLESS","USD", []),  # not typically tier-1
]

def tier1_events_on(day):
    """Returns list of (label, event, ts) that qualify on this day."""
    hits = []
    for e in events_by_day.get(day, []):
        ts = e.get("ts","")
        if ts[:10] != day: continue
        cur = e.get("currency"); ev = e.get("event","")
        for label, want_cur, patterns in TIER1_PATTERNS:
            if cur != want_cur: continue
            if not patterns: continue
            for pat in patterns:
                if pat == ev:
                    hits.append((label, ev, ts))
                    break
    return hits

# Days with tier1
tier1_days = {}
for d in sorted(events_by_day.keys()):
    hits = tier1_events_on(d)
    if hits: tier1_days[d] = hits

# Classification: BIG_NEWS = tier1 event that day; PRE_BIG = next weekday is BIG; POST_BIG = prev weekday is BIG
def classify(day_str):
    d = date.fromisoformat(day_str)
    if day_str in tier1_days: return "BIG_NEWS"
    nxt = d + timedelta(days=1)
    while nxt.weekday()>=5: nxt += timedelta(days=1)
    if nxt.isoformat() in tier1_days: return "PRE_BIG"
    prv = d - timedelta(days=1)
    while prv.weekday()>=5: prv -= timedelta(days=1)
    if prv.isoformat() in tier1_days: return "POST_BIG"
    return "CLEAR"

# Load days
DAYS = []
with open(DAY_JL) as fh:
    for line in fh: DAYS.append(json.loads(line))
FULL = [d for d in DAYS if d['full_day']]
for d in FULL: d['news_class'] = classify(d['date'])

print(f"TIER1 event days in cache range: {len(tier1_days)}")
print(f"TIER1 in candle full-day set: {sum(1 for d in FULL if d['news_class']=='BIG_NEWS')}")

xtab = defaultdict(lambda: defaultdict(int))
for d in FULL:
    xtab[d['news_class']][d['day_class']] += 1

news_classes = ["BIG_NEWS","PRE_BIG","POST_BIG","CLEAR"]
day_classes  = ["BOUNCE_DAY","GRIND_DAY","QUIET_DAY","MULTI_DAY"]

print(f"\n(a-b tightened) Cross-tab news_class x day_class [n={len(FULL)}]:")
hdr = "news/day"
print(f"  {hdr:>10}", end="")
for dc in day_classes: print(f" {dc:>10}", end="")
print(f" {'TOTAL':>6}")
for nc in news_classes:
    print(f"  {nc:>10}", end="")
    tot=0
    for dc in day_classes:
        v=xtab[nc][dc]; tot += v
        print(f" {v:>10}", end="")
    print(f" {tot:>6}")

print(f"\n  Row % (day-class within news-class):")
print(f"  {hdr:>10}", end="")
for dc in day_classes: print(f" {dc:>10}", end="")
print()
for nc in news_classes:
    tot=sum(xtab[nc].values())
    print(f"  {nc:>10}", end="")
    for dc in day_classes:
        v=xtab[nc][dc]; pct=100*v/tot if tot else 0
        print(f" {pct:>9.1f}%", end="")
    print()

# Grind rate by news class
print(f"\nGrind rate by news class:")
for nc in news_classes:
    sub = [d for d in FULL if d['news_class']==nc]
    g = sum(1 for d in sub if d['grind'])
    print(f"  {nc}: {g}/{len(sub)} = {100*g/max(len(sub),1):.1f}%")

# Also: mean range by news class
print(f"\nMean day-range by news class:")
for nc in news_classes:
    sub = [d for d in FULL if d['news_class']==nc]
    if sub:
        m = sum(d['day_range_pips'] for d in sub)/len(sub)
        print(f"  {nc}: n={len(sub)}  mean_range={m:.1f}p")

# Per-event majors: use tier1 labels
by_label = defaultdict(list)
for day, hits in tier1_days.items():
    for label, ev, ts in hits:
        by_label[label].append(day)
day_by_date = {d['date']: d for d in FULL}
print(f"\n(c) Per-event tables (TIER1 events, days in candle full-day set):")
for label in ["NFP","FOMC","US_CPI","US_PPI","US_RETAIL","US_GDP","ISM_MFG","ISM_SVC","BOE","UK_CPI","UK_GDP","UK_UNEM","UK_RETAIL"]:
    days = sorted(set(x for x in by_label.get(label,[]) if x in day_by_date))
    if not days:
        print(f"\n  {label}: 0 days"); continue
    print(f"\n  {label} ({len(days)} days):")
    print(f"  {'date':>10} {'wd':>3} {'class':>10} {'range':>7} {'net':>7} {'nR':>3}")
    for d in days:
        row = day_by_date[d]
        print(f"  {d:>10} {row['weekday']:>3} {row['day_class']:>10} {row['day_range_pips']:>7.1f} {row['day_net_pips']:>7.1f} {row['n_runs_40p']:>3}")

# Save
with open("/opt/tradingbot/reports-public/daystruct_20260821/section4b_calendar_tier1.json","w") as fh:
    json.dump({
        "tier1_days": {d: [{"label":l,"event":e,"ts":ts} for l,e,ts in hits] for d, hits in tier1_days.items()},
        "xtab_news_day_full": {nc: dict(xtab[nc]) for nc in news_classes},
        "by_label_days": {l: sorted(set(v)) for l,v in by_label.items()},
        "news_class_by_date": {d['date']: d['news_class'] for d in FULL},
    }, fh, indent=2)
print("\nCheckpoint -> section4b_calendar_tier1.json")
