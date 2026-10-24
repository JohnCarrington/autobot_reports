#!/usr/bin/env python3
"""Correlate V3 transitions with every ≥80-pip directional movement.

For each movement in the census, examine:
  * Was V3 pointing in the correct direction when the movement began?
  * If not, when did V3 FIRST fire STRONG in the correct direction?
  * How many pips had already moved before V3 identified?
  * How many pips remained after V3 identified?
  * Did V3 reverse incorrectly during an ordinary pullback (false-reverse)?

Separately, catalogue every V3 STRONG fire that was NOT associated with any
≥80-pip qualifying movement in its direction on that day — these are the
"false signals".
"""
from __future__ import annotations
import csv
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file  # noqa: E402

OUT = Path("<research_workspace>/outputs/nms_corr")
LIVE_CANDLES_26 = Path("<autobot_prod_root>/data/candles/GBPUSD")

mv = pd.read_csv(OUT / "directional_movements.csv")
tr = pd.read_csv(OUT / "v3_transitions.csv")

mv["start_ts_utc"] = pd.to_datetime(mv["start_ts_utc"])
mv["end_ts_utc"] = pd.to_datetime(mv["end_ts_utc"])
tr["ts_utc"] = pd.to_datetime(tr["ts_utc"])

# For each movement, compute correlation
correlation = []
for _, m in mv.iterrows():
    date = m.date
    mov_dir = "UP" if m.direction == "UP" else "DOWN"
    required_strong = "STRONG_UP" if mov_dir == "UP" else "STRONG_DOWN"
    required_emerging = "EMERGING_UP" if mov_dir == "UP" else "EMERGING_DOWN"

    # All V3 transitions on this date
    daytr = tr[tr.date == date].sort_values("ts_utc")

    # Was V3 pointing in the correct direction at move start?
    pre_mv = daytr[daytr.ts_utc < m.start_ts_utc]
    if pre_mv.empty:
        v3_at_start = "NORMAL"
    else:
        v3_at_start = pre_mv.iloc[-1].to_state
    v3_right_at_start = v3_at_start == required_strong

    # First STRONG in correct direction, at or after move start
    cand = daytr[(daytr.to_state == required_strong) &
                 (daytr.ts_utc >= m.start_ts_utc)]
    if cand.empty:
        v3_first_strong_ts = None
        v3_identified_during_movement = False
    else:
        v3_first_strong_ts = cand.iloc[0].ts_utc
        v3_identified_during_movement = (v3_first_strong_ts <= m.end_ts_utc)

    # First EMERGING in correct direction, at or after move start
    cand_em = daytr[(daytr.to_state == required_emerging) &
                    (daytr.ts_utc >= m.start_ts_utc)]
    v3_first_emerging_ts = cand_em.iloc[0].ts_utc if not cand_em.empty else None

    # Pips before V3 fire — need the candle data for the price at fire time
    price_at_fire = None
    pips_before = None
    pips_remaining = None
    if v3_first_strong_ts is not None:
        # Load day's candles
        d_iso = date
        for p in list(CANDLES_EXT.glob(f"{d_iso}.csv")) + \
                 list(CANDLES_26.glob(f"{d_iso}.csv")) + \
                 list(LIVE_CANDLES_26.glob(f"{d_iso}.csv")):
            df = _load_day_file(p, m.basis if m.basis in ("BID","MID") else "MID")
            if df is None: continue
            after = df[df.ts >= v3_first_strong_ts]
            if after.empty: continue
            price_at_fire = float(after.open.iloc[0]) / 10000
            break
        if price_at_fire is not None:
            if mov_dir == "UP":
                pips_before = max(0.0, (price_at_fire - m.start_price) * 10000)
                pips_remaining = max(0.0, (m.end_price - price_at_fire) * 10000)
            else:
                pips_before = max(0.0, (m.start_price - price_at_fire) * 10000)
                pips_remaining = max(0.0, (price_at_fire - m.end_price) * 10000)

    # Did V3 reverse into the WRONG direction during the movement (pullback false-reverse)?
    opposite_strong = "STRONG_DOWN" if mov_dir == "UP" else "STRONG_UP"
    reverses_during = daytr[(daytr.to_state == opposite_strong) &
                            (daytr.ts_utc >= m.start_ts_utc) &
                            (daytr.ts_utc <= m.end_ts_utc)]
    v3_wrong_reverse_during = len(reverses_during) > 0

    correlation.append({
        "date": date, "partition": m.partition, "basis": m.basis,
        "movement_idx": m.movement_idx,
        "movement_direction": mov_dir,
        "movement_pips": m.pips,
        "movement_start_ts": m.start_ts_utc.isoformat(),
        "movement_end_ts":   m.end_ts_utc.isoformat(),
        "movement_duration_min": int((m.end_ts_utc - m.start_ts_utc).total_seconds()/60),
        "v3_state_at_move_start": v3_at_start,
        "v3_right_direction_at_start": v3_right_at_start,
        "v3_first_strong_ts":
            v3_first_strong_ts.isoformat() if v3_first_strong_ts is not None else None,
        "v3_first_emerging_ts":
            v3_first_emerging_ts.isoformat() if v3_first_emerging_ts is not None else None,
        "v3_identified_during_movement": v3_identified_during_movement,
        "price_at_v3_fire": price_at_fire,
        "pips_before_v3_fire":
            round(pips_before, 1) if pips_before is not None else None,
        "pips_remaining_after_v3_fire":
            round(pips_remaining, 1) if pips_remaining is not None else None,
        "pct_moved_before_v3":
            round(pips_before/m.pips*100, 1) if (pips_before is not None and m.pips > 0) else None,
        "v3_wrong_reverse_during_movement": v3_wrong_reverse_during,
        "v3_delay_min_from_move_start":
            int((v3_first_strong_ts - m.start_ts_utc).total_seconds()/60)
            if v3_first_strong_ts is not None else None,
    })

cdf = pd.DataFrame(correlation)
cdf.to_csv(OUT / "nms_movement_correlation.csv", index=False)
print(f"Correlation rows: {len(cdf)}")

# Partition metrics
print("\n═══ Movement identification rates ═══")
for part in ["Dev", "Holdout", "Conf2026", "ALL"]:
    sub = cdf if part == "ALL" else cdf[cdf.partition == part]
    if sub.empty: continue
    n = len(sub)
    identified = sub.v3_identified_during_movement.sum()
    right_at_start = sub.v3_right_direction_at_start.sum()
    delay = sub[sub.v3_identified_during_movement].v3_delay_min_from_move_start
    pb = sub[sub.v3_identified_during_movement].pips_before_v3_fire
    pr = sub[sub.v3_identified_during_movement].pips_remaining_after_v3_fire
    pct = sub[sub.v3_identified_during_movement].pct_moved_before_v3
    print(f"\n{part} (n={n})")
    print(f"  V3 right-direction at move start:    "
          f"{right_at_start}/{n} ({right_at_start/n*100:.1f}%)")
    print(f"  V3 identified during movement:       "
          f"{identified}/{n} ({identified/n*100:.1f}%)")
    print(f"  Median delay (min after move start): "
          f"{delay.median():.0f}  mean: {delay.mean():.0f}")
    print(f"  Median pips before V3 fire:          "
          f"{pb.median():.1f}  mean: {pb.mean():.1f}")
    print(f"  Median pips remaining after V3 fire: "
          f"{pr.median():.1f}  mean: {pr.mean():.1f}")
    print(f"  Median % of move already done at V3: "
          f"{pct.median():.1f}%  mean: {pct.mean():.1f}%")
    print(f"  V3 wrong-reverse during movement:    "
          f"{sub.v3_wrong_reverse_during_movement.sum()}/{n} "
          f"({sub.v3_wrong_reverse_during_movement.sum()/n*100:.1f}%)")

# Early-identification bucket metrics
print("\n═══ Early-identification bucket (all 277 movements) ═══")
for pct_cutoff, label in [(10, "within first 10%"),
                          (20, "within first 20%"),
                          (30, "within first 30%"),
                          (50, "within first 50%")]:
    hit = (cdf.pct_moved_before_v3 <= pct_cutoff) & cdf.v3_identified_during_movement
    print(f"  {label}: {hit.sum()}/{len(cdf)} ({hit.sum()/len(cdf)*100:.1f}%)")

# ─── Also catalogue the "false signals" ─────────────────────────
# A false signal = V3 STRONG fire on a date where no ≥80-pip qualifying
# movement in the fired direction existed.
all_strong = tr[tr.to_state.isin(["STRONG_UP", "STRONG_DOWN"])].copy()
all_strong["ts_utc"] = pd.to_datetime(all_strong["ts_utc"])
# Also first-of-day only to avoid counting re-fires
all_strong = all_strong.sort_values("ts_utc").drop_duplicates(["date", "to_state"], keep="first")

# For each strong fire, check if the corresponding direction had a ≥80-pip
# qualifying movement that day
mv["dir_normalized"] = mv.direction.map({"UP": "STRONG_UP", "DOWN": "STRONG_DOWN"})
mv_by_date_dir = set(zip(mv.date, mv.dir_normalized))

false_rows = []
for _, s in all_strong.iterrows():
    if (s.date, s.to_state) not in mv_by_date_dir:
        false_rows.append({
            "date": s.date, "partition": s.partition, "basis": s.basis,
            "v3_fire_ts": s.ts_utc.isoformat(),
            "v3_fire_state": s.to_state,
            "up_score_at_fire": s.up_score, "down_score_at_fire": s.down_score,
            "note": "no ≥80-pip movement in V3-fired direction on this date",
        })
pd.DataFrame(false_rows).to_csv(OUT / "nms_false_signals.csv", index=False)
print(f"\n═══ False-signal statistics ═══")
print(f"Total first-of-day STRONG fires: {len(all_strong)}")
print(f"False signals (no ≥80-pip movement in fired direction): "
      f"{len(false_rows)} ({len(false_rows)/max(1,len(all_strong))*100:.1f}%)")
# By partition
for part in ["Dev", "Holdout", "Conf2026"]:
    fs = sum(1 for r in false_rows if r["partition"] == part)
    total = (all_strong.partition == part).sum()
    if total == 0: continue
    print(f"  {part:9s}  false={fs}  of {total}  ({fs/total*100:.1f}%)")
