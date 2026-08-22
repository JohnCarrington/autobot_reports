"""Add duration + refined definitions; find one that captures both named days without catching all BOUNCE."""
import csv, glob, json, os
from collections import Counter
import datetime as dt

def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace(" ", "T"))

full = json.load(open("/tmp/q1_metrics.json"))
# add duration_min
for d,v in full.items():
    ds = v["dom_start_ts"]; de = v["dom_end_ts"]
    v["dom_dur_min"] = (parse_ts(de) - parse_ts(ds)).total_seconds()/60
audit_grind = lambda v: v["day_range"] >= 60 and abs(v["day_net"]) >= 0.70 * v["day_range"]

for d in ('2026-08-10','2026-08-14'):
    v = full[d]
    print(f"  {d}  dom_mag={v['dom_mag']:.1f}  counter={v['counter_mag']:.1f}  duration_min={v['dom_dur_min']:.0f}  net_sign_same_as_dom={ (v['day_net']>0 and v['dom_dir']=='up') or (v['day_net']<0 and v['dom_dir']=='dn')}")

defs = {
 "DEF_A_audit"                                             : lambda v: audit_grind(v),
 # slow-grind: dominant excursion ≥ 40p AND duration ≥ 6h AND net_sign_matches
 "DEF_I_domexc40_dur360_signmatch"                          : lambda v: v["dom_mag"] >= 40 and v["dom_dur_min"] >= 360 and ((v['day_net']>0 and v['dom_dir']=='up') or (v['day_net']<0 and v['dom_dir']=='dn')),
 # relax duration to 4h
 "DEF_J_domexc40_dur240_signmatch"                          : lambda v: v["dom_mag"] >= 40 and v["dom_dur_min"] >= 240 and ((v['day_net']>0 and v['dom_dir']=='up') or (v['day_net']<0 and v['dom_dir']=='dn')),
 # dom mag ≥ 40 AND (dom_mag - counter_mag) ≥ 15p AND duration ≥ 4h
 "DEF_K_domexc40_leadover15_dur240"                         : lambda v: v["dom_mag"] >= 40 and (v["dom_mag"]-v["counter_mag"]) >= 15 and v["dom_dur_min"] >= 240 and ((v['day_net']>0 and v['dom_dir']=='up') or (v['day_net']<0 and v['dom_dir']=='dn')),
 # dom mag ≥ 45p AND (dom_mag - counter_mag) ≥ 15p
 "DEF_L_domexc45_leadover15"                                : lambda v: v["dom_mag"] >= 45 and (v["dom_mag"]-v["counter_mag"]) >= 15,
 # dom mag ≥ 40p AND (dom_mag/(dom_mag+counter_mag)) ≥ 0.60 AND duration_min ≥ 240
 "DEF_M_domshare60_dur240"                                  : lambda v: v["dom_mag"] >= 40 and (v["dom_mag"]/(v["dom_mag"]+v["counter_mag"]+1e-9)) >= 0.60 and v["dom_dur_min"] >= 240,
 # audit UNION slow-grind
 "DEF_N_audit_or_slowgrind"                                 : lambda v: audit_grind(v) or (v["dom_mag"] >= 45 and (v["dom_mag"]-v["counter_mag"]) >= 15 and v["dom_dur_min"] >= 240),
}

named = ('2026-08-10','2026-08-14')
print("\n=== definition summary ===")
print(f"  {'name':<45s}  n_pass  08-10?  08-14?  8grind100")
grind100_dates = {'2026-01-05','2026-01-23','2026-04-07','2026-04-13','2026-04-30',
                  '2026-06-17','2026-06-18','2026-07-15'}
for name, fn in defs.items():
    passed = [d for d,v in full.items() if fn(v)]
    p810 = '2026-08-10' in passed
    p814 = '2026-08-14' in passed
    g100 = len(set(passed) & grind100_dates)
    print(f"  {name:<45s}  {len(passed):>6d}   {str(p810):5s}  {str(p814):5s}  {g100}/8")

# best candidate: DEF_N_audit_or_slowgrind
print("\n=== DEF_N (audit UNION slow-grind) monthly counts ===")
fn = defs["DEF_N_audit_or_slowgrind"]
per_month = Counter(); per_month_audit = Counter(); per_month_full = Counter()
for d,v in full.items():
    ym = d[:7]
    per_month_full[ym] += 1
    if fn(v): per_month[ym] += 1
    if audit_grind(v): per_month_audit[ym] += 1
print(f"  {'month':<8s}  full  audit  DEF_N  new")
tot_a=tot_n=tot_f=0
for ym in sorted(per_month_full):
    tot_a += per_month_audit[ym]; tot_n += per_month[ym]; tot_f += per_month_full[ym]
    print(f"  {ym:<8s}  {per_month_full[ym]:4d}  {per_month_audit[ym]:5d}  {per_month[ym]:5d}  +{per_month[ym]-per_month_audit[ym]}")
print(f"  {'TOTAL':<8s}  {tot_f:4d}  {tot_a:5d}  {tot_n:5d}")

# per-monthly averages
mos = len(per_month_full)
print(f"  monthly average audit: {tot_a/mos:.1f} grind/mo")
print(f"  monthly average DEF_N: {tot_n/mos:.1f} grind/mo")

# new dates DEF_N captures
new_dates = sorted([d for d,v in full.items() if fn(v) and not audit_grind(v)])
print(f"\n=== new grind dates under DEF_N (n={len(new_dates)}) — all NOT audit-grind ===")
for d in new_dates:
    v = full[d]
    print(f"  {d}  range={v['day_range']:.1f}  net={v['day_net']:+.1f}  dom={v['dom_dir']} mag={v['dom_mag']:.1f} counter={v['counter_mag']:.1f} dur={v['dom_dur_min']:.0f}min")

# save
open("/tmp/q1_defN_dates.json","w").write(json.dumps({
    "def_N_dates_all": sorted([d for d,v in full.items() if fn(v)]),
    "def_N_new_beyond_audit": new_dates,
    "audit_grind_dates": sorted([d for d,v in full.items() if audit_grind(v)]),
}, indent=1))
