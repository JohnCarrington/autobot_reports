"""Design + apply loosened grind definitions.
Compute per-day metrics needed for candidate definitions, then count how many
of 140 full days pass each.
"""
import csv, glob, json, os
from collections import Counter, defaultdict
import datetime as dt

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"

def load_day(p):
    rows = []
    with open(p) as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append((row['timestamp'], float(row['open']), float(row['high']),
                         float(row['low']), float(row['close'])))
    return rows

def metrics(rows):
    if len(rows) < 2:
        return None
    closes = [r[4] for r in rows]
    highs  = [r[2] for r in rows]
    lows   = [r[3] for r in rows]
    n = len(rows)
    day_range = max(highs) - min(lows)
    day_net   = closes[-1] - closes[0]
    # temporally-ordered close excursion
    # max unidirectional up-move = max_{j > i}(closes[j] - closes[i])
    # equivalent to max-subarray on close-changes
    max_up_mag = 0.0; up_i = 0; up_j = 0
    min_c = closes[0]; min_i = 0
    for j in range(1, n):
        if closes[j] - min_c > max_up_mag:
            max_up_mag = closes[j] - min_c
            up_i, up_j = min_i, j
        if closes[j] < min_c:
            min_c = closes[j]; min_i = j
    max_dn_mag = 0.0; dn_i = 0; dn_j = 0
    max_c = closes[0]; max_i = 0
    for j in range(1, n):
        if max_c - closes[j] > max_dn_mag:
            max_dn_mag = max_c - closes[j]
            dn_i, dn_j = max_i, j
        if closes[j] > max_c:
            max_c = closes[j]; max_i = j
    if max_up_mag >= max_dn_mag:
        dom_dir = "up"; dom_mag = max_up_mag; dom_i, dom_j = up_i, up_j
        counter_mag = max_dn_mag
    else:
        dom_dir = "dn"; dom_mag = max_dn_mag; dom_i, dom_j = dn_i, dn_j
        counter_mag = max_up_mag
    return dict(n=n, day_range=day_range, day_net=day_net,
                max_up_mag=max_up_mag, max_dn_mag=max_dn_mag,
                dom_dir=dom_dir, dom_mag=dom_mag, dom_i=dom_i, dom_j=dom_j,
                counter_mag=counter_mag,
                dom_start_ts=rows[dom_i][0], dom_end_ts=rows[dom_j][0],
                first_close=closes[0], last_close=closes[-1])

# gather full days
files = sorted(glob.glob(f"{CANDLES}/*.csv"))
days = {}
for f in files:
    date = os.path.basename(f).replace(".csv","")
    rows = load_day(f)
    m = metrics(rows)
    if m is None: continue
    m["full_day"] = m["n"] >= 200
    days[date] = m
full = {d:v for d,v in days.items() if v["full_day"]}
print(f"full days: {len(full)}")

# audit's classification (from earlier run)
audit = json.load(open("/tmp/tier3_days_class.json"))

# audit grind (baseline)
def audit_grind(v):
    return v["day_range"] >= 60 and abs(v["day_net"]) >= 0.70 * v["day_range"]

# candidate loosened definitions:
defs = {
 "DEF_A_audit"                         : lambda v: audit_grind(v),
 "DEF_B_ratio_0.50_range_40"           : lambda v: v["day_range"] >= 40 and abs(v["day_net"]) >= 0.50 * v["day_range"],
 "DEF_C_ratio_0.40_range_40"           : lambda v: v["day_range"] >= 40 and abs(v["day_net"]) >= 0.40 * v["day_range"],
 "DEF_D_domexc_40_counter_lt_25"       : lambda v: v["dom_mag"] >= 40 and v["counter_mag"] < 25,
 "DEF_E_domexc_50_counter_lt_25"       : lambda v: v["dom_mag"] >= 50 and v["counter_mag"] < 25,
 "DEF_F_domexc_40_counter_lt_20"       : lambda v: v["dom_mag"] >= 40 and v["counter_mag"] < 20,
 "DEF_G_domexc_60_or_audit"            : lambda v: audit_grind(v) or (v["dom_mag"] >= 60 and v["counter_mag"] < 25),
 "DEF_H_ratio_dom_to_range_0.85"       : lambda v: v["day_range"] >= 40 and v["dom_mag"] >= 0.85 * v["day_range"],
}

named = ('2026-08-10','2026-08-14')
print("\n=== named-day metrics ===")
for d in named:
    v = full[d]
    print(f"  {d}  range={v['day_range']:.1f}  net={v['day_net']:+.1f}  dom={v['dom_dir']} mag={v['dom_mag']:.1f} counter={v['counter_mag']:.1f}  ratio_net/range={v['day_net']/v['day_range']:+.3f}  dom_start={v['dom_start_ts'][11:16]}  dom_end={v['dom_end_ts'][11:16]}")

print("\n=== definition counts ===")
print(f"  {'name':<32s}  n_pass  08-10?  08-14?  grind100_covered? (of 8)")
grind100_dates = {'2026-01-05','2026-01-23','2026-04-07','2026-04-13','2026-04-30',
                  '2026-06-17','2026-06-18','2026-07-15'}
for name, fn in defs.items():
    passed = [d for d,v in full.items() if fn(v)]
    p810 = '2026-08-10' in passed
    p814 = '2026-08-14' in passed
    g100 = len(set(passed) & grind100_dates)
    print(f"  {name:<32s}  {len(passed):>6d}   {str(p810):5s}  {str(p814):5s}  {g100}/8")

# For DEF_G (audit union domexc>=60 counter<25): monthly breakdown
print("\n=== DEF_G_domexc_60_or_audit monthly count ===")
fn = defs["DEF_G_domexc_60_or_audit"]
per_month = Counter()
per_month_audit = Counter()
per_month_full = Counter()
for d,v in full.items():
    ym = d[:7]
    per_month_full[ym] += 1
    if fn(v): per_month[ym] += 1
    if audit_grind(v): per_month_audit[ym] += 1
print(f"  {'month':<8s}  full  audit  DEF_G  diff")
for ym in sorted(per_month_full):
    print(f"  {ym:<8s}  {per_month_full[ym]:4d}  {per_month_audit[ym]:5d}  {per_month[ym]:5d}  +{per_month[ym]-per_month_audit[ym]}")

# also DEF_D as alternative
print("\n=== DEF_D_domexc_40_counter_lt_25 monthly count ===")
fn = defs["DEF_D_domexc_40_counter_lt_25"]
per_month = Counter()
for d,v in full.items():
    ym = d[:7]
    if fn(v): per_month[ym] += 1
print(f"  {'month':<8s}  DEF_D  audit  diff")
for ym in sorted(per_month_full):
    print(f"  {ym:<8s}  {per_month[ym]:5d}  {per_month_audit[ym]:5d}  +{per_month[ym]-per_month_audit[ym]}")

# under each definition, show the NEW dates DEF_G captured that audit missed
print("\n=== new grind dates under DEF_G (not in audit) ===")
new_dates = sorted([d for d,v in full.items() if defs["DEF_G_domexc_60_or_audit"](v) and not audit_grind(v)])
for d in new_dates:
    v = full[d]
    print(f"  {d}  range={v['day_range']:.1f}  net={v['day_net']:+.1f}  dom={v['dom_dir']} mag={v['dom_mag']:.1f} counter={v['counter_mag']:.1f}")

print("\n=== new grind dates under DEF_D (not in audit) ===")
new_dates = sorted([d for d,v in full.items() if defs["DEF_D_domexc_40_counter_lt_25"](v) and not audit_grind(v)])
print(f"  n = {len(new_dates)}")
for d in new_dates[:30]:
    v = full[d]
    print(f"  {d}  range={v['day_range']:.1f}  net={v['day_net']:+.1f}  dom={v['dom_dir']} mag={v['dom_mag']:.1f} counter={v['counter_mag']:.1f}")

# save
json.dump({d: {k:v for k,v in x.items()} for d,x in full.items()},
          open("/tmp/q1_metrics.json","w"), indent=1, default=str)
