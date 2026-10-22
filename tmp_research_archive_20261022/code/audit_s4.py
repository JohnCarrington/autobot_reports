"""Section 4: calendar mapping."""
import os, glob, json
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict

NEWS = "/opt/tradingbot/cache"
DAY_JL = "/opt/tradingbot/reports-public/daystruct_20260821/section1_days.jsonl"

# Load all news; deduplicate by (date, ts, event, currency)
events_by_day = defaultdict(list)  # date -> list of events for that date
for f in sorted(glob.glob(f"{NEWS}/news_state_finnhub_*.json")):
    with open(f) as fh:
        j = json.load(fh)
    d = j.get("date")
    if not d: continue
    for e in j.get("events", []):
        events_by_day[d].append(e)

# Deduplicate within each day
for d in events_by_day:
    seen = set()
    uniq = []
    for e in events_by_day[d]:
        k = (e.get("ts"), e.get("event"), e.get("currency"), e.get("impact"))
        if k in seen: continue
        seen.add(k); uniq.append(e)
    events_by_day[d] = uniq

# For each day: is there a HIGH-impact GBP or USD event that day?
def is_big_news(day):
    """Returns list of qualifying (HIGH, GBP or USD) events for that day."""
    out = []
    for e in events_by_day.get(day, []):
        if e.get("impact") == "HIGH" and e.get("currency") in ("GBP","USD"):
            ts = e.get("ts","")
            if ts[:10] == day:
                out.append(e)
    return out

# Load days
DAYS = []
with open(DAY_JL) as fh:
    for line in fh: DAYS.append(json.loads(line))

# Build big-news set + classify
big_news_days = set()
for d in sorted(events_by_day.keys()):
    if is_big_news(d): big_news_days.add(d)

def classify(day_str):
    d = date.fromisoformat(day_str)
    if day_str in big_news_days: return "BIG_NEWS"
    # PRE_BIG = day before a big news day (searching next calendar day, then next weekday)
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:  # skip weekend
        nxt += timedelta(days=1)
    if nxt.isoformat() in big_news_days: return "PRE_BIG"
    prv = d - timedelta(days=1)
    while prv.weekday() >= 5:
        prv -= timedelta(days=1)
    if prv.isoformat() in big_news_days: return "POST_BIG"
    return "CLEAR"

# Coverage note: we assume news cache covers the day.
missing_news_days = [d['date'] for d in DAYS if d['full_day'] and d['date'] not in events_by_day]
print(f"Full days missing news cache entry: {len(missing_news_days)} -> {missing_news_days[:10]}{'...' if len(missing_news_days)>10 else ''}")
print(f"BIG_NEWS days total (any day with HIGH GBP/USD event): {len(big_news_days)}")
print(f"BIG_NEWS days in candle set: {len([d for d in DAYS if d['full_day'] and d['date'] in big_news_days])}")

FULL = [d for d in DAYS if d['full_day']]
# Attach news class
for d in FULL:
    d['news_class'] = classify(d['date'])

# (a) Cross-tab: day-class vs news-class
xtab = defaultdict(lambda: defaultdict(int))
for d in FULL:
    xtab[d['news_class']][d['day_class']] += 1

news_classes = ["BIG_NEWS","PRE_BIG","POST_BIG","CLEAR"]
day_classes = ["BOUNCE_DAY","GRIND_DAY","QUIET_DAY","MULTI_DAY"]
print(f"\n(a-b) Cross-tab news_class x day_class [full days, n={len(FULL)}]:")
hdr = "news/day"
print(f"  {hdr:>10}", end="")
for dc in day_classes: print(f" {dc:>10}", end="")
print(f" {'TOTAL':>6}")
for nc in news_classes:
    print(f"  {nc:>10}", end="")
    tot = 0
    for dc in day_classes:
        v = xtab[nc][dc]
        print(f" {v:>10}", end="")
        tot += v
    print(f" {tot:>6}")

print(f"\n  Row % (day-class within each news-class):")
print(f"  {hdr:>10}", end="")
for dc in day_classes: print(f" {dc:>10}", end="")
print()
for nc in news_classes:
    tot = sum(xtab[nc].values())
    print(f"  {nc:>10}", end="")
    for dc in day_classes:
        v = xtab[nc][dc]
        pct = 100*v/tot if tot else 0
        print(f" {pct:>9.1f}%", end="")
    print()

# (c) Recurring monthly majors
MAJORS = {
    "NFP": lambda e: e.get("currency")=="USD" and "Non-Farm Payrolls" in e.get("event",""),
    "US_CPI": lambda e: e.get("currency")=="USD" and "Inflation Rate" in e.get("event","") and "YoY" in e.get("event",""),
    "US_CPI_MoM": lambda e: e.get("currency")=="USD" and e.get("event","") == "Inflation Rate MoM",
    "FOMC": lambda e: e.get("currency")=="USD" and ("Fed Interest Rate" in e.get("event","") or "FOMC" in e.get("event","")),
    "BoE_Rate": lambda e: e.get("currency")=="GBP" and "BoE Interest Rate" in e.get("event",""),
    "UK_CPI": lambda e: e.get("currency")=="GBP" and "Inflation Rate" in e.get("event","") and "YoY" in e.get("event",""),
    "UK_GDP": lambda e: e.get("currency")=="GBP" and "GDP" in e.get("event",""),
    "US_GDP": lambda e: e.get("currency")=="USD" and "GDP Growth" in e.get("event",""),
}

# For each major, find dates when it fired (impact HIGH ideally)
major_days = {name: set() for name in MAJORS}
for day, evs in events_by_day.items():
    for e in evs:
        if e.get("ts","")[:10] != day: continue
        for name, matcher in MAJORS.items():
            if matcher(e) and e.get("impact") in ("HIGH","MED"):
                major_days[name].add(day)

# Print per-event tables
day_by_date = {d['date']: d for d in FULL}
print(f"\n(c) Per-event recurring-major table [days that appear in candle full-day set]:")
for name, dates in major_days.items():
    dates = sorted([x for x in dates if x in day_by_date])
    if not dates:
        print(f"\n  {name}: NO qualifying days in candle window")
        continue
    print(f"\n  {name} ({len(dates)} days):")
    print(f"  {'date':>10} {'wd':>3} {'class':>10} {'range':>6} {'net':>6} {'n_runs':>6} {'grind?':>6}")
    for d in dates:
        row = day_by_date[d]
        print(f"  {d:>10} {row['weekday']:>3} {row['day_class']:>10} {row['day_range_pips']:>6.1f} {row['day_net_pips']:>6.1f} {row['n_runs_40p']:>6} {'Y' if row['grind'] else '':>6}")

# Save
with open("/opt/tradingbot/reports-public/daystruct_20260821/section4_calendar.json","w") as fh:
    json.dump({
        "big_news_days": sorted(big_news_days),
        "missing_news_days_full": missing_news_days,
        "xtab_news_day": {nc: dict(xtab[nc]) for nc in news_classes},
        "majors_days": {n: sorted(v) for n,v in major_days.items()},
    }, fh, indent=2)
print("\nCheckpoint -> section4_calendar.json")
