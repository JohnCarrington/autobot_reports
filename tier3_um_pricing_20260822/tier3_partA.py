"""
Part A — reproduce audit Section 4 independently.
Investigate-only. Reads Finnhub cache + candle CSVs, applies stated defs.
"""
import json, os, glob, csv, datetime as dt, statistics, math
from collections import Counter, defaultdict

# ---------- 1. Rebuild TIER1 event-day list ----------
# TIER1 mapping (label -> (currency, set of exact event strings))
# Section 4 wording: NFP, FOMC/Fed decision, US CPI, US GDP, US PPI, US Retail,
# ISM Manf, ISM Svc, BoE Decision, UK CPI, UK GDP, UK Unemployment, UK Retail
TIER1 = {
    "NFP":       ("USD", {"Non Farm Payrolls"}),
    "FOMC":      ("USD", {"Fed Interest Rate Decision", "FOMC Economic Projections", "Fed Press Conference"}),
    "US_CPI":    ("USD", {"Inflation Rate YoY", "Inflation Rate MoM",
                          "Core Inflation Rate YoY", "Core Inflation Rate MoM"}),
    "US_GDP":    ("USD", {"GDP Growth Rate QoQ Adv", "GDP Growth Rate QoQ 2nd Est",
                          "GDP Growth Rate QoQ Final"}),
    "US_PPI":    ("USD", {"PPI MoM"}),
    "US_RETAIL": ("USD", {"Retail Sales MoM"}),
    "ISM_MFG":   ("USD", {"ISM Manufacturing PMI"}),
    "ISM_SVC":   ("USD", {"ISM Services PMI"}),
    "BOE":       ("GBP", {"BoE Interest Rate Decision"}),
    "UK_CPI":    ("GBP", {"Inflation Rate YoY"}),
    "UK_GDP":    ("GBP", {"GDP MoM", "GDP Growth Rate QoQ Prel", "GDP Growth Rate QoQ Final"}),
    "UK_UNEM":   ("GBP", {"Unemployment Rate"}),
    "UK_RETAIL": ("GBP", {"Retail Sales MoM"}),
}

CACHE = "/opt/tradingbot/cache"
CANDLES = "/opt/tradingbot/data/candles/GBPUSD"

# gather all news_state_finnhub_*.json + backfill files
files = sorted(glob.glob(f"{CACHE}/news_state_finnhub_*.json"))
# label -> list of (date, ts, event) for TIER1 hits found
hits = []               # list of dict(date, label, event, ts)
per_date_labels = defaultdict(list)  # date -> [label,...] dedup by label
seen_keys = set()       # (date, currency, event, ts) dedup across duplicate cache files

for f in files:
    try:
        j = json.load(open(f))
    except Exception:
        continue
    for e in j.get("events", []):
        cur = e.get("currency", "")
        evt = e.get("event", "")
        imp = e.get("impact", "")
        ts  = e.get("ts", "")
        if not ts:
            continue
        try:
            ts_dt = dt.datetime.fromisoformat(ts)
        except Exception:
            continue
        date = ts_dt.date().isoformat()
        # scan TIER1 catalogue
        for label, (need_cur, evstrs) in TIER1.items():
            if cur == need_cur and evt in evstrs:
                key = (date, cur, evt, ts)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                hits.append(dict(date=date, label=label, event=evt, ts=ts, impact=imp,
                                 source=os.path.basename(f)))
                per_date_labels[date].append((label, evt, ts, imp))

tier1_dates = sorted(per_date_labels)
print(f"[A1] independent scan: {len(hits)} tier1 hits across {len(tier1_dates)} unique dates")

# per-label totals
by_label = Counter([h["label"] for h in hits])
for k in sorted(by_label):
    print(f"       label {k:10s}  hits={by_label[k]:3d}  distinct_dates="
          f"{len({h['date'] for h in hits if h['label']==k}):3d}")

# ---------- 2. Reconcile against audit tier1_days ----------
audit = json.load(open("/opt/tradingbot/reports-public/daystruct_20260821/section4b_calendar_tier1.json"))
audit_dates = set(audit["tier1_days"].keys())
my_dates = set(tier1_dates)
missing_in_mine = sorted(audit_dates - my_dates)
missing_in_audit = sorted(my_dates - audit_dates)
print(f"[A2] audit tier1 dates: {len(audit_dates)}  mine: {len(my_dates)}")
print(f"       in-audit-only: {missing_in_mine[:15]}{' ...' if len(missing_in_mine)>15 else ''}  n={len(missing_in_mine)}")
print(f"       in-mine-only : {missing_in_audit[:15]}{' ...' if len(missing_in_audit)>15 else ''}  n={len(missing_in_audit)}")

# label agreement per date
disagree = []
for d in sorted(audit_dates & my_dates):
    a_labels = sorted({e["label"] for e in audit["tier1_days"][d]})
    m_labels = sorted({x[0] for x in per_date_labels[d]})
    if a_labels != m_labels:
        disagree.append((d, a_labels, m_labels))
print(f"[A2] label-set disagreements on shared dates: {len(disagree)}")
for d,a,m in disagree[:20]:
    print(f"       {d}  audit={a}  mine={m}")

# ---------- 3. Five spot-checks: pick load-bearing events, quote raw ts ----------
spot = [
    ("FOMC","2026-01-28"),
    ("FOMC","2026-06-17"),
    ("BOE", "2026-06-18"),
    ("NFP", "2026-05-08"),
    ("UK_CPI","2026-01-21"),
]
print("[A3] Spot-checks (raw Finnhub rows):")
for lbl, date in spot:
    rows = [h for h in hits if h["label"]==lbl and h["date"]==date]
    for r in rows:
        print(f"    {lbl:6s} {date}  ts={r['ts']}  event='{r['event']}'  impact={r['impact']}  src={r['source']}")

# save for downstream
open("/tmp/tier3_tier1_dates.json","w").write(json.dumps({
    "hits": hits, "per_date_labels": {d: per_date_labels[d] for d in tier1_dates}
}, indent=1))
