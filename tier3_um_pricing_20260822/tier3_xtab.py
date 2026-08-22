"""Rebuild the news-class × day-class cross-tab from scratch."""
import json, datetime as dt
from collections import Counter, defaultdict

# my day classifications
days = json.load(open("/tmp/tier3_days_class.json"))
# my TIER1 events
tier = json.load(open("/tmp/tier3_tier1_dates.json"))
per_date_labels = tier["per_date_labels"]  # date -> list of [label,event,ts,impact]

# filter my TIER1 to audit window (2026-01-01 .. 2026-08-21)
tier1_dates = {d for d in per_date_labels if d <= "2026-08-21"}
print(f"[X0] mine TIER1 dates in audit window: {len(tier1_dates)}")

# assign news class per date using weekday sequence
# BIG_NEWS: contains a TIER1 event (and is itself a weekday)
# PRE_BIG:  next weekday is BIG_NEWS
# POST_BIG: prev weekday was BIG_NEWS
# CLEAR:    neither (and no TIER1)
full_days = sorted(d for d,v in days.items() if v["full_day"])

def prev_wd(d):
    d = dt.date.fromisoformat(d)
    while True:
        d = d - dt.timedelta(days=1)
        if d.weekday() < 5:
            return d.isoformat()
def next_wd(d):
    d = dt.date.fromisoformat(d)
    while True:
        d = d + dt.timedelta(days=1)
        if d.weekday() < 5:
            return d.isoformat()

news_class = {}
for d in full_days:
    if d in tier1_dates:
        news_class[d] = "BIG_NEWS"
        continue
    # only weekdays are eligible for PRE/POST
    wd = dt.date.fromisoformat(d).weekday()
    if wd >= 5:
        news_class[d] = "CLEAR"
        continue
    nxt = next_wd(d)
    prv = prev_wd(d)
    if nxt in tier1_dates:
        news_class[d] = "PRE_BIG"
    elif prv in tier1_dates:
        news_class[d] = "POST_BIG"
    else:
        news_class[d] = "CLEAR"

# my xtab
xtab = defaultdict(Counter)
for d in full_days:
    cls = days[d]["cls"]
    nc  = news_class[d]
    xtab[nc][cls] += 1
row_totals = {nc: sum(xtab[nc].values()) for nc in xtab}
print("[X1] mine — news × day (full days, n={}):".format(len(full_days)))
print(f"     {'':<10}  BOUNCE  GRIND  QUIET  MULTI  TOTAL")
for nc in ("BIG_NEWS","PRE_BIG","POST_BIG","CLEAR"):
    b = xtab[nc]["BOUNCE_DAY"]; g = xtab[nc]["GRIND_DAY"]
    q = xtab[nc]["QUIET_DAY"];  m = xtab[nc]["MULTI_DAY"]
    t = row_totals.get(nc, 0)
    print(f"     {nc:<10}  {b:6d} {g:6d} {q:6d} {m:6d}  {t:5d}")
print("[X1] row %:")
for nc in ("BIG_NEWS","PRE_BIG","POST_BIG","CLEAR"):
    t = max(1, row_totals.get(nc, 0))
    b = xtab[nc]["BOUNCE_DAY"]/t*100; g = xtab[nc]["GRIND_DAY"]/t*100
    q = xtab[nc]["QUIET_DAY"]/t*100;  m = xtab[nc]["MULTI_DAY"]/t*100
    print(f"     {nc:<10}  {b:6.1f}% {g:6.1f}% {q:6.1f}% {m:6.1f}%")

# audit's xtab (from REPORT.md table)
audit_xtab = {
    "BIG_NEWS": {"BOUNCE_DAY":30,"GRIND_DAY":17,"QUIET_DAY":10,"MULTI_DAY":16},
    "PRE_BIG":  {"BOUNCE_DAY":22,"GRIND_DAY": 3,"QUIET_DAY":10,"MULTI_DAY": 5},
    "POST_BIG": {"BOUNCE_DAY": 9,"GRIND_DAY": 3,"QUIET_DAY": 4,"MULTI_DAY": 1},
    "CLEAR":    {"BOUNCE_DAY": 6,"GRIND_DAY": 1,"QUIET_DAY": 0,"MULTI_DAY": 2},
}
print("[X2] audit — news × day (from REPORT.md, n=139):")
for nc in ("BIG_NEWS","PRE_BIG","POST_BIG","CLEAR"):
    r = audit_xtab[nc]
    t = sum(r.values())
    print(f"     {nc:<10}  {r['BOUNCE_DAY']:6d} {r['GRIND_DAY']:6d} {r['QUIET_DAY']:6d} {r['MULTI_DAY']:6d}  {t:5d}")

# per-major event tables — mine
lbl_to_dates = defaultdict(list)
for d, labels in per_date_labels.items():
    if d > "2026-08-21": continue
    if d not in full_days: continue
    ls = set(x[0] for x in labels)
    for L in ls:
        lbl_to_dates[L].append(d)
print("\n[X3] Per-major event day-class breakdown (full-days in candle set):")
majors = ["NFP","FOMC","US_CPI","BOE","UK_CPI","UK_GDP","US_GDP","ISM_MFG","ISM_SVC","US_PPI","UK_UNEM","UK_RETAIL","US_RETAIL"]
for L in majors:
    ds = sorted(lbl_to_dates.get(L, []))
    if not ds:
        print(f"     {L:9s} n=0")
        continue
    ct = Counter([days[d]["cls"] for d in ds])
    ranges = [days[d]["range"] for d in ds]
    nets   = [days[d]["net"]   for d in ds]
    print(f"     {L:9s} n={len(ds):2d}  B={ct.get('BOUNCE_DAY',0)} G={ct.get('GRIND_DAY',0)} "
          f"Q={ct.get('QUIET_DAY',0)} M={ct.get('MULTI_DAY',0)}  "
          f"range_mean={sum(ranges)/len(ranges):.0f} net_mean={sum(nets)/len(nets):+.0f}"
          f"{'  ⚠thin(n<10)' if len(ds)<10 else ''}")

# save
open("/tmp/tier3_xtab.json","w").write(json.dumps({
    "mine_xtab": {nc: dict(xtab[nc]) for nc in xtab},
    "audit_xtab": audit_xtab,
    "news_class": news_class,
    "lbl_to_dates": {k: sorted(v) for k,v in lbl_to_dates.items()},
    "tier1_dates_in_window_in_full_days": sorted(tier1_dates & set(full_days)),
}, indent=1))

# print FOMC + BOE table detail
print("\n[X4] FOMC (mine, full-day set only):")
for d in sorted(lbl_to_dates.get("FOMC", [])):
    v = days[d]
    print(f"     {d}  {v['cls']:11s}  range={v['range']:6.1f}  net={v['net']:+7.1f}  n_runs={v['n_runs']}")
print("[X4] BOE (mine, full-day set only):")
for d in sorted(lbl_to_dates.get("BOE", [])):
    v = days[d]
    print(f"     {d}  {v['cls']:11s}  range={v['range']:6.1f}  net={v['net']:+7.1f}  n_runs={v['n_runs']}")
print("[X4] NFP (mine, full-day set only):")
for d in sorted(lbl_to_dates.get("NFP", [])):
    v = days[d]
    print(f"     {d}  {v['cls']:11s}  range={v['range']:6.1f}  net={v['net']:+7.1f}  n_runs={v['n_runs']}")

# BIG_NEWS grind rate
bn_dates = sorted([d for d,c in news_class.items() if c == "BIG_NEWS"])
grind_rate = sum(1 for d in bn_dates if days[d]["cls"]=="GRIND_DAY")/max(1,len(bn_dates))
print(f"\n[X5] mine BIG_NEWS n={len(bn_dates)}, grind={sum(1 for d in bn_dates if days[d]['cls']=='GRIND_DAY')} "
      f"= {grind_rate*100:.1f}%    (audit: 17/73 = 23.3%)")
