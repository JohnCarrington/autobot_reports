"""
Section 6: 60% ladder-ride bound.

DEFINITION:
* Restrict to signal_log-covered window: 2026-03-30 .. 2026-08-21.
* "Qualifying-run pip inventory" = sum of run magnitudes on each date.
* 60% ladder bound = 0.60 * sum(magnitudes).
* Actual banked = sum(pnl_pips) over ALL GBPUSD signals whose
  timestamp_close falls in the month AND pnl_pips is not null.
  (This is the true book P&L, not restricted to in-run signals.)
* Per-month table: month, days, qualifying-run pips, 60% bound,
  actual banked GBPUSD pips, gap = bound - actual.
"""
import os, json
from collections import defaultdict
from datetime import datetime

DAY_JL = "/opt/tradingbot/reports-public/daystruct_20260821/section1_days.jsonl"
SL_MAIN = "/opt/tradingbot/logs/signal_log.jsonl"
SL_BACK = "/opt/tradingbot/data/signal_log_backfill.jsonl"

# Load days
DAYS = []
with open(DAY_JL) as fh:
    for line in fh: DAYS.append(json.loads(line))
DAY_MIN = "2026-03-30"; DAY_MAX = "2026-08-21"
DAYS_W = [d for d in DAYS if DAY_MIN <= d['date'] <= DAY_MAX]

# Load signals (GBPUSD only, deduped by ts_open+strategy+dir+entry)
signals = []; seen = set()
for src in (SL_MAIN, SL_BACK):
    if not os.path.exists(src): continue
    with open(src) as fh:
        for line in fh:
            try: r = json.loads(line)
            except: continue
            pair = r.get("pair") or r.get("epic","")
            if "GBPUSD" not in pair: continue
            k = (r.get("timestamp_open"), r.get("strategy"), r.get("direction"), r.get("entry"))
            if k in seen: continue
            seen.add(k); signals.append(r)

# Per-month agg
month_offered = defaultdict(float)  # sum of run magnitudes
month_bank    = defaultdict(float)  # sum of pnl_pips actual
month_days    = defaultdict(int)
month_bank_by_close = defaultdict(float)

for d in DAYS_W:
    m = d['date'][:7]
    month_days[m] += 1
    for r in d['runs']:
        month_offered[m] += r['magnitude_pips']

# Actual bank: use timestamp_close if present, else timestamp_open (for open trades ignore null pnl)
for s in signals:
    p = s.get("pnl_pips")
    if p is None: continue
    t = s.get("timestamp_close") or s.get("timestamp_open")
    if not t: continue
    m = t[:7]
    # only count if within window
    if not (DAY_MIN <= t[:10] <= DAY_MAX): continue
    month_bank[m] += p

# Table
print(f"Signal_log GBPUSD-covered window: {DAY_MIN} .. {DAY_MAX}\n")
print(f"{'Month':>8} {'Days':>4} {'Runs':>4} {'Offered_p':>10} {'Bound60%':>10} {'Banked':>8} {'Gap_60%_vs_actual':>18}")
months = sorted(month_days.keys())
tot_off = tot_bank = tot_bound = 0.0
tot_runs = 0
for m in months:
    days = month_days[m]
    n_runs = sum(len(d['runs']) for d in DAYS_W if d['date'][:7]==m)
    off = month_offered[m]
    bound = 0.60 * off
    bank = month_bank[m]
    gap = bound - bank
    print(f"{m:>8} {days:>4} {n_runs:>4} {off:>10.1f} {bound:>10.1f} {bank:>8.1f} {gap:>18.1f}")
    tot_off += off; tot_bank += bank; tot_bound += bound; tot_runs += n_runs
print(f"{'TOTAL':>8} {sum(month_days.values()):>4} {tot_runs:>4} {tot_off:>10.1f} {tot_bound:>10.1f} {tot_bank:>8.1f} {tot_bound-tot_bank:>18.1f}")

# Save
with open("/opt/tradingbot/reports-public/daystruct_20260821/section6_bound.json","w") as fh:
    json.dump({
        "window": [DAY_MIN, DAY_MAX],
        "months": {m: {
            "days": month_days[m],
            "runs": sum(len(d['runs']) for d in DAYS_W if d['date'][:7]==m),
            "offered_pips": round(month_offered[m],1),
            "bound_60pct": round(0.60*month_offered[m],1),
            "banked_pips": round(month_bank[m],1),
            "gap": round(0.60*month_offered[m]-month_bank[m],1),
        } for m in months},
        "totals": {
            "offered_pips": round(tot_off,1),
            "bound_60pct": round(tot_bound,1),
            "banked_pips": round(tot_bank,1),
            "gap": round(tot_bound-tot_bank,1),
        }
    }, fh, indent=2)
print("\nCheckpoint -> section6_bound.json")
