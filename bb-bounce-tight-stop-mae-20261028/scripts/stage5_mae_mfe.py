"""Phase 6 Stage 5 — tick-level MAE/MFE for every frozen entry.

For each frozen entry from Stage 4, iterate the actual chronological
BID/ASK ticks starting at fill_ts_ns and record:

    - MAE on the executable *exit* side (BUY exits on bid → adverse
      bid-low; SELL exits on ask → adverse ask-high).
    - MFE on the same executable exit side.
    - Time (in seconds) to first favourable movement of +5, +10, +20,
      +40, +60 pips.
    - Spread at entry.
    - Whether price revisited the rejection extreme (C1 low for BUY,
      C1 high for SELL).

MAE and MFE are measured over the "pre-success" window:

    * clipped at FIRST +40-pip touch (whichever direction's threshold
      the hypothesis cares about most), OR
    * clipped at the Phase 6 horizon of 24 hours after entry (whichever
      comes first), OR
    * clipped at end-of-week (Friday 21:00 UTC) to avoid weekend-gap
      inclusion.

An additional pair of columns records "full-window" MAE/MFE over
exactly the 24-hour horizon so the stop-sensitivity grid in Stage 7
can distinguish the two.

Memory discipline
-----------------
Processes ticks year-at-a-time to stay within the 7.8 GB VM budget.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
TICK_DIR = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")

HORIZON_NS = 24 * 60 * 60 * 1_000_000_000  # 24 hours
MAE_CLIP_PIPS = 40.0  # clip MAE window at first +40p success
PIP_IN_POINTS = 1.0  # on IG DFB GBPUSD, 1 pip = 1 price-point display unit

# Pip = 0.0001 in decimal space.  bid/ask are stored as decimal (1.3310 etc).
DEC_PIP = 0.0001


def _end_of_week_ns(ts_ns: int) -> int:
    """Return Friday 21:00 UTC of the week containing ts_ns.  Beyond
    this ts the market is closed."""
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    # weekday(): Monday=0 ... Sunday=6; Friday=4
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    # If dt is already past Fri 21:00, roll to next week (shouldn't happen
    # for our fills but be defensive).
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _mae_mfe_for_entry(ticks: pd.DataFrame, start_idx: int,
                       entry_price_dec: float, direction: str,
                       stop_ns: int, c1_low_dec: float, c1_high_dec: float):
    """Scan ticks[start_idx:] until ts >= stop_ns.
    Returns (mae_pips, mfe_pips, t5, t10, t20, t40, t60, revisit).

    BUY: exit on BID; adverse = minimum bid below entry.
    SELL: exit on ASK; adverse = maximum ask above entry.

    Favourable thresholds measured on the executable exit side as well.
    """
    ts_arr = ticks["ts_utc_ns"].values
    bid_arr = ticks["bid"].values
    ask_arr = ticks["ask"].values
    n = len(ts_arr)
    end_idx = int(np.searchsorted(ts_arr, stop_ns, side="right"))
    if end_idx > n:
        end_idx = n
    if start_idx >= end_idx:
        return (0.0, 0.0, None, None, None, None, None, False, 0.0, 0.0, None)

    is_buy = direction == "BUY"

    if is_buy:
        exit_side = bid_arr[start_idx:end_idx]
        # Favourable = bid rises above entry.
        adv_arr = entry_price_dec - exit_side  # pips adverse (decimal)
        fav_arr = exit_side - entry_price_dec
        # Revisit of C1 LOW: any bid <= C1 low
        revisit = bool((bid_arr[start_idx:end_idx] <= c1_low_dec).any())
    else:
        exit_side = ask_arr[start_idx:end_idx]
        adv_arr = exit_side - entry_price_dec
        fav_arr = entry_price_dec - exit_side
        revisit = bool((ask_arr[start_idx:end_idx] >= c1_high_dec).any())

    # Pips
    adv_pips = (adv_arr / DEC_PIP).astype(np.float32)
    fav_pips = (fav_arr / DEC_PIP).astype(np.float32)

    # Full-window MAE/MFE
    mae_full = float(adv_pips.max()) if len(adv_pips) else 0.0
    mfe_full = float(fav_pips.max()) if len(fav_pips) else 0.0

    # Time to +N pips (on executable exit side)
    def _first_time_to(thresh: float):
        hits = np.where(fav_pips >= thresh)[0]
        if len(hits) == 0:
            return None
        idx = int(hits[0])
        return (int(ts_arr[start_idx + idx]) - int(ts_arr[start_idx])) / 1e9

    t5 = _first_time_to(5.0)
    t10 = _first_time_to(10.0)
    t20 = _first_time_to(20.0)
    t40 = _first_time_to(40.0)
    t60 = _first_time_to(60.0)

    # Pre-success window: clip at first +40-pip touch
    hits40 = np.where(fav_pips >= MAE_CLIP_PIPS)[0]
    clip = int(hits40[0]) if len(hits40) else len(fav_pips)
    if clip > 0:
        mae_clip = float(adv_pips[:clip].max())
    else:
        mae_clip = 0.0

    # Time to first favourable movement (any pip > 0)
    pos_hits = np.where(fav_pips > 0.0)[0]
    t_first_fav = (
        (int(ts_arr[start_idx + int(pos_hits[0])]) - int(ts_arr[start_idx])) / 1e9
        if len(pos_hits) else None
    )

    return (mae_clip, mfe_full, t5, t10, t20, t40, t60, revisit,
            mae_full, mfe_full, t_first_fav)


def main() -> int:
    print("Loading Stage 4 entries...", flush=True)
    entries = pd.read_parquet(DATA / "stage4_entries.parquet")
    print(f"  {len(entries):,} entries", flush=True)

    # Group entries by year of fill
    entries["fill_year"] = pd.to_datetime(entries["fill_ts_ns"], unit="ns",
                                          utc=True).dt.year
    out_rows: list[dict] = []
    for year in sorted(entries["fill_year"].unique()):
        print(f"  processing year {year} ...", flush=True)
        sub = entries[entries["fill_year"] == year].sort_values("fill_ts_ns")
        tp = TICK_DIR / f"{year}.parquet"
        if not tp.exists():
            print(f"  no tick file for {year}, skipping", flush=True)
            continue
        ticks = pd.read_parquet(tp, columns=["ts_utc_ns", "bid", "ask"])
        ticks["bid"] = ticks["bid"].astype(np.float32)
        ticks["ask"] = ticks["ask"].astype(np.float32)
        ts_arr = ticks["ts_utc_ns"].values

        # Determine if we need next-year ticks for horizon spill-over
        last_horizon_end = int(sub["fill_ts_ns"].max()) + HORIZON_NS
        next_year = year + 1
        if last_horizon_end > int(ts_arr[-1]):
            np_path = TICK_DIR / f"{next_year}.parquet"
            if np_path.exists():
                tn = pd.read_parquet(np_path, columns=["ts_utc_ns", "bid", "ask"])
                tn["bid"] = tn["bid"].astype(np.float32)
                tn["ask"] = tn["ask"].astype(np.float32)
                ticks = pd.concat([ticks, tn], ignore_index=True)
                ts_arr = ticks["ts_utc_ns"].values
                del tn

        for _, r in sub.iterrows():
            fill_ns = int(r["fill_ts_ns"])
            entry_dec = float(r["fill_price_decimal"])
            direction = r["direction"]
            c1_low_dec = float(r["c1_low"]) / 10000.0
            c1_high_dec = float(r["c1_high"]) / 10000.0
            # Horizon
            horizon_end_ns = fill_ns + HORIZON_NS
            eow_ns = _end_of_week_ns(fill_ns)
            stop_ns = min(horizon_end_ns, eow_ns)

            start_idx = int(np.searchsorted(ts_arr, fill_ns, side="left"))
            res = _mae_mfe_for_entry(
                ticks, start_idx, entry_dec, direction, stop_ns,
                c1_low_dec, c1_high_dec,
            )
            out_rows.append({
                "c3_ts": r["c3_ts"],
                "direction": direction,
                "fill_ts_ns": fill_ns,
                "fill_price_decimal": entry_dec,
                "fill_price_points": r["fill_price_points"],
                "spread_pips": r["spread_pips"],
                "mae_pips_clip40": res[0],
                "mfe_pips_full": res[1],
                "t_to_5p": res[2],
                "t_to_10p": res[3],
                "t_to_20p": res[4],
                "t_to_40p": res[5],
                "t_to_60p": res[6],
                "revisited_rejection_extreme": res[7],
                "mae_pips_full": res[8],
                "t_first_fav": res[10],
                "stop_window_ns": stop_ns - fill_ns,
                "c1_low_points": r["c1_low"],
                "c1_high_points": r["c1_high"],
            })
        del ticks, ts_arr
        import gc; gc.collect()

    df = pd.DataFrame(out_rows)
    df.to_parquet(DATA / "stage5_mae_mfe.parquet", index=False)
    # Save summary
    summary = {
        "n_entries": len(df),
        "n_buy": int((df["direction"] == "BUY").sum()),
        "n_sell": int((df["direction"] == "SELL").sum()),
        "mae_pips_clip40_summary": {
            "min": float(df["mae_pips_clip40"].min()),
            "p10": float(df["mae_pips_clip40"].quantile(0.1)),
            "median": float(df["mae_pips_clip40"].quantile(0.5)),
            "p90": float(df["mae_pips_clip40"].quantile(0.9)),
            "max": float(df["mae_pips_clip40"].max()),
        },
        "mfe_pips_full_summary": {
            "min": float(df["mfe_pips_full"].min()),
            "p10": float(df["mfe_pips_full"].quantile(0.1)),
            "median": float(df["mfe_pips_full"].quantile(0.5)),
            "p90": float(df["mfe_pips_full"].quantile(0.9)),
            "max": float(df["mfe_pips_full"].max()),
        },
        "pct_reach_20p": float((df["t_to_20p"].notna()).mean() * 100.0),
        "pct_reach_30p": float((df["mfe_pips_full"] >= 30.0).mean() * 100.0),
        "pct_reach_40p": float((df["t_to_40p"].notna()).mean() * 100.0),
        "pct_reach_50p": float((df["mfe_pips_full"] >= 50.0).mean() * 100.0),
        "pct_reach_60p": float((df["t_to_60p"].notna()).mean() * 100.0),
    }
    (DATA / "stage5_mae_mfe_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
