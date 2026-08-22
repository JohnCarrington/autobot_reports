"""Q1 — EMA_PULLBACK arm outcomes on grind days.
Approach:
 - Rerun the arm walk (5 gates: session/stack/fan/entry/regime) per bar.
 - Compare per-day arm count to per-day actual EMA_PB fires from signal_log.
 - Downstream-kill count = arms - fires (aggregate; per-gate breakdown noted as
   limitation because per-bar downstream-decision logs are not persistent
   for the legacy _detect path when EMA_PB_PULLBACK_FIX_ENABLED=0).
 - For each actual fire: banked pnl vs day's grind close-excursion magnitude.
 - No-arm holes: contiguous hourly windows in [06:00,17:00) with 0 arms;
   quote pips of directional close move during each hole.
"""
import json, csv, datetime as dt
from collections import defaultdict, Counter
import pandas as pd
import numpy as np

TARGETS = ['2026-08-10','2026-08-14','2026-06-17','2026-06-18','2026-07-15','2026-07-29']

# reuse walk output
walk = json.load(open('/tmp/q2_arm_walk.json'))
walk_by_day = {r['day']: r for r in walk}
# but our walk_by_day was only for a subset — need to add 07-29. Rerun.

import subprocess, os
# fresh arm walk with 07-29 added
import sys
sys.path.insert(0, '/tmp')

# just reuse the modules directly
from q2_walk import (evaluate_day, would_tv3_arm, would_emapb_arm, load_day)

per_day_arms = {}
per_day_holes = {}

for d in TARGETS:
    ed = evaluate_day(d)
    if ed is None: continue
    prior_dir = ed['prior_dir']
    ema_arms = []
    for r in ed['bars']:
        armed, reasons, direction = would_emapb_arm(r)
        if armed:
            ema_arms.append(dict(
                ts=r['ts'], dir=direction,
                close=r['close'], regime=r['regime'],
                fan_p = (r['e8']-r['e50']) if r['e8']>r['e50'] else (r['e50']-r['e8']),
            ))
    per_day_arms[d] = ema_arms
    # no-arm holes at hourly resolution within EMA_PB session 06:00-17:00
    # only consider EMA_PB session bars
    session_hours = list(range(6, 17))
    arm_hours = set()
    for a in ema_arms:
        t = dt.datetime.fromisoformat(a['ts'].replace(' ','T'))
        arm_hours.add(t.hour)
    zero_hours = [h for h in session_hours if h not in arm_hours]
    # compute pips of move during each contiguous zero-hour stretch
    bars_by_hour = defaultdict(list)
    for r in ed['bars']:
        t = dt.datetime.fromisoformat(r['ts'].replace(' ','T'))
        if t.hour in session_hours:
            bars_by_hour[t.hour].append(r)
    holes = []
    if zero_hours:
        # group contiguous
        cur = [zero_hours[0]]
        for h in zero_hours[1:]:
            if h == cur[-1]+1:
                cur.append(h)
            else:
                holes.append(cur); cur=[h]
        holes.append(cur)
    hole_details = []
    for hs in holes:
        # first_close of first bar to last_close of last bar in these hours
        rows = []
        for h in hs:
            rows.extend(bars_by_hour[h])
        if not rows: continue
        first_c = rows[0]['close']; last_c = rows[-1]['close']
        move = last_c - first_c
        hole_details.append(dict(hours=hs, first_ts=rows[0]['ts'],
                                 last_ts=rows[-1]['ts'],
                                 first_close=first_c, last_close=last_c,
                                 move_pips=move, n_bars=len(rows)))
    per_day_holes[d] = hole_details

# actual EMA_PB fires from signal_log
by_day_fires = {d: [] for d in TARGETS}
with open('/opt/tradingbot/logs/signal_log.jsonl') as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('pair') != 'GBPUSD': continue
        strat = r.get('strategy','')
        if 'EMA_PULLBACK' not in strat: continue
        d = r.get('timestamp_open','')[:10]
        if d in by_day_fires:
            by_day_fires[d].append(dict(
                ts=r['timestamp_open'], strat=strat, dir=r['direction'],
                entry=r['entry'], pnl=r.get('pnl_pips'), outcome=r.get('close_reason'),
                sl=r.get('sl'), tp1=r.get('tp1'),
            ))

# grind magnitude per day: dominant close-excursion from q1_metrics
metrics = json.load(open('/tmp/q1_metrics.json'))

# print per-day results
print("=" * 80)
print("Q1 — EMA_PULLBACK on grind days")
print("=" * 80)
for d in TARGETS:
    m = metrics.get(d, {})
    dom_mag = m.get('dom_mag', 0)
    dom_dir = m.get('dom_dir', '?')
    arms = per_day_arms.get(d, [])
    fires = by_day_fires.get(d, [])
    print(f"\n--- {d}  dom_move={dom_dir} {dom_mag:.1f}p ---")
    print(f"  arms (5-gate walk): {len(arms)}")
    print(f"  actual EMA_PB fires (signal_log): {len(fires)}")
    print(f"  downstream-killed = arms - fires = {max(0,len(arms)-len(fires))} "
          f"({'kill rate {:.0%}'.format((len(arms)-len(fires))/max(1,len(arms))) if arms else ''})")
    if fires:
        total_pnl = sum(f['pnl'] or 0 for f in fires)
        print(f"  fires (banked pnl):")
        for f in fires:
            print(f"    {f['ts'][11:19]} {f['strat']:26s} {f['dir']:5s} entry={f['entry']} pnl={f['pnl']} outcome={f['outcome']}")
        print(f"  total banked: {total_pnl:+.1f}p vs dom_move {dom_mag:.1f}p  → capture ratio {total_pnl/dom_mag*100:+.1f}%")
    else:
        print(f"  total banked: 0p vs dom_move {dom_mag:.1f}p  → capture ratio 0.0%")
    holes = per_day_holes.get(d, [])
    if holes:
        print(f"  no-arm holes in 06:00-17:00 (per hour):")
        for h in holes:
            hr_span = f"{h['hours'][0]:02d}-{h['hours'][-1]+1:02d}"
            print(f"    {hr_span}  ({len(h['hours'])}h)  {h['first_ts'][11:16]}→{h['last_ts'][11:16]}  first={h['first_close']:.2f} last={h['last_close']:.2f}  move={h['move_pips']:+.1f}p")
    else:
        print(f"  no-arm holes: none (arms present in every session hour)")

# save
out = {"per_day": {}, "meta":{"note":"downstream-kill is aggregate (arms−fires); per-gate breakdown not feasible without persistent decision log for legacy detect path"}}
for d in TARGETS:
    out["per_day"][d] = dict(
        arms=per_day_arms.get(d, []),
        fires=by_day_fires.get(d, []),
        holes=per_day_holes.get(d, []),
        dom_move=metrics.get(d, {}).get('dom_mag'),
        dom_dir=metrics.get(d, {}).get('dom_dir'),
    )
json.dump(out, open('/tmp/q1_ema_pb_result.json','w'), indent=1, default=str)
