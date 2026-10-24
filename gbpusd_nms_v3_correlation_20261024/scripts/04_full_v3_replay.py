#!/usr/bin/env python3
"""Full-corpus NMS V3 replay — RETRACTS the Stage-2 'not feasible' claim.

The classifier was being fed GBPUSD prices in standard units (1.3245) when
the production code feeds pip units (13245). With prices in pip units, the
±3-pip 'reclaim open' invalidation operates correctly and the state machine
reproduces the research team's documented replay times EXACTLY on all 7
named days:

  date         rpt_state      rpt_time  our_state      our_time   match
  2026-10-13   STRONG_UP      08:20     STRONG_UP      08:20      ✓
  2026-10-12   STRONG_DOWN    09:55     STRONG_DOWN    09:55      ✓
  2026-09-04   STRONG_DOWN    08:25     STRONG_DOWN    08:25      ✓
  2026-09-15   STRONG_UP      11:35     STRONG_UP      11:35      ✓
  2026-09-28   STRONG_DOWN    10:10     STRONG_DOWN    10:10      ✓
  2026-09-30   STRONG_DOWN    08:15     STRONG_DOWN    08:15      ✓
  2026-10-09   STRONG_DOWN    12:35     STRONG_DOWN    12:35      ✓

This script replays V3 against the full corpus and writes:
  outputs/nms_corr/v3_transitions.csv   — every state transition
  outputs/nms_corr/v3_daily_summary.csv — one row per day
"""
from __future__ import annotations
import csv
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, '<autobot_prod_root>')
sys.path.insert(0, str(Path(__file__).parent.parent))
import nms_v3_patch  # noqa: F401
import nms_v3_classifier as nms  # noqa: E402

from census import CANDLES_26, CANDLES_EXT, _load_day_file  # noqa: E402

OUT = Path("<research_workspace>/outputs/nms_corr")
OUT.mkdir(parents=True, exist_ok=True)
LIVE_CANDLES_26 = Path("<autobot_prod_root>/data/candles/GBPUSD")


def _partition(d: dt.date):
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"


def _iter_candle_files():
    """Yield (path, basis) for every weekday candle file in the full corpus,
    preferring the frozen snapshot where available and falling back to live
    for 2026 dates past the snapshot cutoff."""
    seen = set()
    for p in sorted(CANDLES_EXT.glob("*.csv")):
        seen.add(p.stem); yield p, "BID"
    for p in sorted(CANDLES_26.glob("*.csv")):
        if p.stem in seen: continue
        seen.add(p.stem); yield p, "MID"
    for p in sorted(LIVE_CANDLES_26.glob("*.csv")):
        if p.stem in seen: continue
        try:
            d = dt.date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d.weekday() >= 5: continue
        seen.add(p.stem); yield p, "MID"


transitions = []
daily = []
total_files = 0
total_fires = 0
days_with_strong = 0

for p, basis in _iter_candle_files():
    total_files += 1
    df = _load_day_file(p, basis)
    if df is None or len(df) < 20:
        continue
    date = df["ts"].iloc[0].date()
    if date.weekday() >= 5: continue
    date_s = date.isoformat()
    state = nms.fresh_state("GBPUSD", session_date=date_s)
    prev_state = "NORMAL"
    first_emerging_up = first_emerging_dn = None
    first_strong_up = first_strong_dn = None
    n_up_transitions = n_dn_transitions = 0
    n_state_changes = 0
    for _, r in df.iterrows():
        # IMPORTANT: feed pip units (do NOT divide by 10000)
        bar = {"ts": r.ts.isoformat(),
               "o": float(r.open), "h": float(r.high),
               "l": float(r.low),  "c": float(r.close)}
        state, result = nms.advance(state, bar)
        st = result.get("state")
        if st and st != prev_state:
            n_state_changes += 1
            transitions.append({
                "date": date_s,
                "partition": _partition(date),
                "basis": basis,
                "ts_utc": r.ts.isoformat(),
                "from_state": prev_state,
                "to_state": st,
                "up_score": result.get("up_score"),
                "down_score": result.get("down_score"),
                "london_open_ts": state.get("london_open_ts"),
                "london_open_price": state.get("london_open_price"),
                "fired_evidence_count": len(result.get("fired_evidence") or []),
            })
            prev_state = st
            if st in ("STRONG_UP", "STRONG_DOWN"):
                total_fires += 1
            if st == "EMERGING_UP" and first_emerging_up is None:
                first_emerging_up = r.ts.isoformat()
            if st == "EMERGING_DOWN" and first_emerging_dn is None:
                first_emerging_dn = r.ts.isoformat()
            if st == "STRONG_UP" and first_strong_up is None:
                first_strong_up = r.ts.isoformat()
            if st == "STRONG_DOWN" and first_strong_dn is None:
                first_strong_dn = r.ts.isoformat()
            if st in ("STRONG_UP", "EMERGING_UP"):
                n_up_transitions += 1
            elif st in ("STRONG_DOWN", "EMERGING_DOWN"):
                n_dn_transitions += 1
    if first_strong_up or first_strong_dn:
        days_with_strong += 1
    daily.append({
        "date": date_s,
        "partition": _partition(date),
        "basis": basis,
        "n_state_changes": n_state_changes,
        "first_emerging_up_ts":  first_emerging_up,
        "first_emerging_dn_ts":  first_emerging_dn,
        "first_strong_up_ts":    first_strong_up,
        "first_strong_dn_ts":    first_strong_dn,
        "any_strong_fire": bool(first_strong_up or first_strong_dn),
    })

print(f"Scanned {total_files} candle files; wrote {len(transitions)} transitions.")
print(f"Days with at least one STRONG fire: {days_with_strong} of {len(daily)} weekdays.")
print(f"Total STRONG transitions: {total_fires}")

with (OUT / "v3_transitions.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(transitions[0].keys()))
    w.writeheader()
    for r in transitions: w.writerow(r)

with (OUT / "v3_daily_summary.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(daily[0].keys()))
    w.writeheader()
    for r in daily: w.writerow(r)

# Partition stats
dsum = pd.DataFrame(daily)
print("\nFire incidence per partition:")
for part in ["Dev", "Holdout", "Conf2026"]:
    sub = dsum[dsum.partition == part]
    with_strong = sub.any_strong_fire.sum()
    print(f"  {part:9s}  weekdays={len(sub):3d}  with_strong_fire={with_strong:3d}  "
          f"({with_strong/max(1,len(sub))*100:.1f}%)")

# Partition stats
tsum = pd.DataFrame(transitions)
print("\nTransition breakdown per partition (first fire of each kind):")
for part in ["Dev", "Holdout", "Conf2026"]:
    sub = tsum[tsum.partition == part]
    strong_up = (sub.to_state == "STRONG_UP").sum()
    strong_dn = (sub.to_state == "STRONG_DOWN").sum()
    em_up = (sub.to_state == "EMERGING_UP").sum()
    em_dn = (sub.to_state == "EMERGING_DOWN").sum()
    print(f"  {part:9s}  STRONG_UP={strong_up}  STRONG_DOWN={strong_dn}  "
          f"EMERGING_UP={em_up}  EMERGING_DOWN={em_dn}")
