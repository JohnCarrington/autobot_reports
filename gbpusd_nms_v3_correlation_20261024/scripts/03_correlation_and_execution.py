#!/usr/bin/env python3
"""Stages 3-7 — correlate the 7 genuine V3 fires with directional movements,
then run the immediate-NMS-entry execution test on those fires.

Because historical V3 state is only available for 7 days (research team's
replay table, documented in §2's feasibility file), this correlation is a
7-row sample, not the full 277-movement census.
"""
from __future__ import annotations
import csv
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa: E402

OUT = Path("<research_workspace>/outputs/nms_corr")
MOV = pd.read_csv(OUT / "directional_movements.csv")

TEAM_REPLAY = [
    # date, truth, fire state, fire ts (UTC), delay min after London open
    ("2026-10-13", "UP",   "STRONG_UP",   "08:20", 80),
    ("2026-10-12", "DOWN", "STRONG_DOWN", "09:55", 175),
    ("2026-09-04", "DOWN", "STRONG_DOWN", "08:25", 85),
    ("2026-09-15", "UP",   "STRONG_UP",   "11:35", 275),
    ("2026-09-28", "UP",   "STRONG_DOWN", "10:10", 190),  # wrong direction
    ("2026-09-30", "UP",   "STRONG_DOWN", "08:15", 75),   # wrong direction
    ("2026-10-09", "DOWN", "STRONG_DOWN", "12:35", 335),
]

SPREAD = 0.8
TP_LEVELS = [30, 40]
SL_PIPS = 12

LIVE_CANDLES_26 = Path("<autobot_prod_root>/data/candles/GBPUSD")
candle_cache: dict[str, pd.DataFrame] = {}
def load(date_str):
    if date_str in candle_cache:
        return candle_cache[date_str]
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "BID"); candle_cache[date_str] = df; return df
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[date_str] = df; return df
    # Fallback to live corpus for 2026 dates after the frozen snapshot
    for p in LIVE_CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[date_str] = df; return df
    return None


def _uk22_utc(date_str):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=22 - off)


corr_rows = []
exec_rows_30 = []
exec_rows_40 = []
for date, truth, state, fire_hhmm, delay in TEAM_REPLAY:
    df = load(date)
    if df is None:
        continue
    fire_ts = pd.Timestamp(f"{date}T{fire_hhmm}:00+00:00")

    # Find the day's movements
    movs = MOV[MOV.date == date].to_dict("records")
    movs_sorted = sorted(movs, key=lambda r: r["start_ts_utc"])

    pred_dir = "LONG" if state == "STRONG_UP" else "SHORT"
    truth_dir_map = {"UP": "LONG", "DOWN": "SHORT"}
    truth_dir = truth_dir_map[truth]

    # For each movement, compute how V3 relates to it
    for i, m in enumerate(movs_sorted):
        mov_start = pd.Timestamp(m["start_ts_utc"])
        mov_end = pd.Timestamp(m["end_ts_utc"])
        mov_dir = "LONG" if m["direction"] == "UP" else "SHORT"
        pips_total = m["pips"]
        # Progress at fire time
        if fire_ts < mov_start:
            relation = "FIRE_BEFORE_MOVEMENT_STARTS"
            pips_already = None
            pips_remaining = None
        elif fire_ts > mov_end:
            relation = "FIRE_AFTER_MOVEMENT_ENDS"
            pips_already = pips_total
            pips_remaining = 0
        else:
            # Price at fire_ts (first bar at or after)
            after = df[df.ts >= fire_ts]
            if after.empty:
                relation = "NO_DATA"; pips_already = None; pips_remaining = None
            else:
                price_at_fire = float(after.open.iloc[0]) / 10000
                if mov_dir == "LONG":
                    pips_already = (price_at_fire - m["start_price"]) * 10000
                else:
                    pips_already = (m["start_price"] - price_at_fire) * 10000
                pips_remaining = pips_total - pips_already
                relation = "FIRE_DURING_MOVEMENT"
        dir_match = "YES" if pred_dir == mov_dir else "NO"
        corr_rows.append({
            "date": date, "truth": truth,
            "v3_state": state, "v3_fire_ts": fire_ts.isoformat(),
            "v3_delay_min": delay,
            "v3_pred_dir": pred_dir,
            "movement_idx": m["movement_idx"],
            "movement_direction": mov_dir,
            "movement_pips": pips_total,
            "movement_start_ts": m["start_ts_utc"],
            "movement_end_ts": m["end_ts_utc"],
            "fire_vs_movement_relation": relation,
            "pips_already_moved_at_fire":
                round(pips_already, 1) if pips_already is not None else None,
            "pips_remaining_at_fire":
                round(pips_remaining, 1) if pips_remaining is not None else None,
            "direction_match_v3_vs_movement": dir_match,
        })

    # Execution test: immediate entry at fire_ts close, 22:00 UK session end
    # (For wrong-direction fires we still execute per the user's spec —
    # the point is to measure what V3 actually produces.)
    end_22 = _uk22_utc(date)
    after = df[(df.ts >= fire_ts) & (df.ts <= end_22)].reset_index(drop=True)
    if after.empty:
        continue
    entry_px = float(after.open.iloc[0]) / 10000

    for tp in TP_LEVELS:
        tp_px = entry_px + tp/10000 if pred_dir == "LONG" else entry_px - tp/10000
        sl_px = entry_px - SL_PIPS/10000 if pred_dir == "LONG" else entry_px + SL_PIPS/10000
        status = None; exit_px = None; exit_ts = None; ambiguous = False
        for _, bar in after.iterrows():
            high = float(bar.high)/10000
            low  = float(bar.low)/10000
            if pred_dir == "LONG":
                hit_tp = high >= tp_px; hit_sl = low <= sl_px
            else:
                hit_tp = low <= tp_px; hit_sl = high >= sl_px
            if hit_tp and hit_sl:
                status = "SL_ambiguous"; exit_px = sl_px; exit_ts = bar.ts
                ambiguous = True
                break
            if hit_tp:
                status = "TP"; exit_px = tp_px; exit_ts = bar.ts; break
            if hit_sl:
                status = "SL"; exit_px = sl_px; exit_ts = bar.ts; break
        if status is None:
            status = "SESSION_END"
            exit_px = float(after.close.iloc[-1]) / 10000
            exit_ts = after.ts.iloc[-1]
        gross = ((exit_px - entry_px) if pred_dir == "LONG"
                 else (entry_px - exit_px)) * 10000
        net = gross - SPREAD
        row = {
            "date": date, "signal_source": "v3_team_replay",
            "v3_state": state, "v3_pred_dir": pred_dir,
            "fire_ts_utc": fire_ts.isoformat(),
            "entry_price": round(entry_px, 5),
            "tp_pips": tp, "sl_pips": SL_PIPS,
            "exit_status": status,
            "exit_ts": exit_ts.isoformat() if hasattr(exit_ts, "isoformat") else str(exit_ts),
            "exit_price": round(exit_px, 5),
            "gross_pips": round(gross, 2),
            "net_pips": round(net, 2),
            "duration_min": int((pd.Timestamp(exit_ts) - fire_ts).total_seconds()/60),
            "ambiguous": ambiguous,
        }
        if tp == 30:
            exec_rows_30.append(row)
        else:
            exec_rows_40.append(row)

# Write outputs
if corr_rows:
    with (OUT / "nms_movement_correlation.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(corr_rows[0].keys()))
        w.writeheader()
        for r in corr_rows: w.writerow(r)
pd.DataFrame(exec_rows_30).to_csv(OUT / "nms_tp30_sl12.csv", index=False)
pd.DataFrame(exec_rows_40).to_csv(OUT / "nms_tp40_sl12.csv", index=False)

print("═══ Movement correlation (7-day V3 sample) ═══")
cdf = pd.DataFrame(corr_rows)
print(cdf[["date", "v3_pred_dir", "movement_direction", "movement_pips",
           "fire_vs_movement_relation",
           "pips_already_moved_at_fire", "pips_remaining_at_fire",
           "direction_match_v3_vs_movement"]].to_string(index=False))

print("\n═══ Execution — TP30/SL12 immediate NMS entry (7-day sample) ═══")
e30 = pd.DataFrame(exec_rows_30)
print(e30[["date", "v3_pred_dir", "entry_price", "exit_status", "net_pips",
           "duration_min"]].to_string(index=False))
print(f"\nTotal trades: {len(e30)}  "
      f"Wins (net>0): {(e30.net_pips > 0).sum()}  "
      f"TP hits: {(e30.exit_status=='TP').sum()}  "
      f"SL hits: {e30.exit_status.isin(['SL','SL_ambiguous']).sum()}  "
      f"SE: {(e30.exit_status=='SESSION_END').sum()}")
print(f"Total net pips: {e30.net_pips.sum():.1f}  "
      f"Avg per trade: {e30.net_pips.mean():+.2f}")

print("\n═══ Execution — TP40/SL12 (7-day sample) ═══")
e40 = pd.DataFrame(exec_rows_40)
print(e40[["date", "v3_pred_dir", "entry_price", "exit_status", "net_pips",
           "duration_min"]].to_string(index=False))
print(f"\nTotal trades: {len(e40)}  "
      f"Wins: {(e40.net_pips > 0).sum()}  "
      f"TP hits: {(e40.exit_status=='TP').sum()}  "
      f"SL hits: {e40.exit_status.isin(['SL','SL_ambiguous']).sum()}  "
      f"SE: {(e40.exit_status=='SESSION_END').sum()}")
print(f"Total net pips: {e40.net_pips.sum():.1f}  "
      f"Avg per trade: {e40.net_pips.mean():+.2f}")

# False-signals detection: V3 fires on these 7 days that didn't match any
# movement in their predicted direction?
false_sig = cdf[cdf.direction_match_v3_vs_movement == "NO"].drop_duplicates("date")
pd.DataFrame(false_sig).to_csv(OUT / "nms_false_signals.csv", index=False)
print(f"\n═══ 'False signals' (V3 direction didn't match any ≥80-pip movement on that day) ═══")
if len(false_sig):
    print(false_sig[["date", "v3_pred_dir", "movement_direction",
                     "movement_pips"]].to_string(index=False))
else:
    print("None in the 7-day sample.")

# Monthly P&L (small sample but for completeness)
monthly = []
for e, tag in [(e30, "tp30_sl12"), (e40, "tp40_sl12")]:
    e["ym"] = pd.to_datetime(e["date"]).dt.to_period("M").astype(str)
    for ym, grp in e.groupby("ym"):
        monthly.append({
            "scenario": tag, "ym": ym, "trades": len(grp),
            "net_pips": round(grp.net_pips.sum(), 1),
            "tp_hit": int((grp.exit_status == "TP").sum()),
            "sl_hit": int(grp.exit_status.isin(["SL","SL_ambiguous"]).sum()),
        })
pd.DataFrame(monthly).to_csv(OUT / "nms_monthly_pnl.csv", index=False)
print(f"\n═══ Monthly P&L (small sample) ═══")
print(pd.DataFrame(monthly).to_string(index=False))
