"""Phase 6 Stage 8 — structural-stop sensitivity.

Structural stop: BUY → stop at min(C1.low, C2.low) − buffer; SELL →
stop at max(C1.high, C2.high) + buffer.  Buffer ∈ {0.5, 1, 2, 3} pips.

For each buffer:
  * compute distance from executable entry fill (not from mid-close) —
    this incorporates spread paid at entry;
  * flag INELIGIBLE when distance < 4.0 (deployed GBP/USD IG minimum);
  * never silently widen; INELIGIBLE trades do not open.

Admissible trades are simulated through the Stage 7 tick-level
BID/ASK engine against the production TARGET_PIPS=30.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
TICK_DIR = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")

HORIZON_NS = 24 * 60 * 60 * 1_000_000_000
DEC_PIP = 0.0001
TARGET = 30.0
IG_MIN = 4.0  # pips, GBPUSD DFB per 2026-09-27 dealing_rules.json

BUFFERS = [0.5, 1.0, 2.0, 3.0]


def _end_of_week_ns(ts_ns: int) -> int:
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _simulate_abs(ts_arr, bid_arr, ask_arr, start_idx, end_idx,
                  entry_dec, direction, stop_level_dec, target_level_dec):
    is_buy = direction == "BUY"
    if start_idx >= end_idx:
        return (0.0, "NO_TICKS")
    if is_buy:
        exit_side = bid_arr[start_idx:end_idx]
        stop_hits = np.where(exit_side <= stop_level_dec)[0]
        tgt_hits = np.where(exit_side >= target_level_dec)[0]
    else:
        exit_side = ask_arr[start_idx:end_idx]
        stop_hits = np.where(exit_side >= stop_level_dec)[0]
        tgt_hits = np.where(exit_side <= target_level_dec)[0]
    stop_idx = int(stop_hits[0]) if len(stop_hits) else None
    tgt_idx = int(tgt_hits[0]) if len(tgt_hits) else None
    if stop_idx is None and tgt_idx is None:
        price = float(exit_side[-1])
        pnl = (price - entry_dec) / DEC_PIP if is_buy else (entry_dec - price) / DEC_PIP
        return (pnl, "TIMEOUT")
    if stop_idx is None:
        return (TARGET, "TARGET")
    if tgt_idx is None:
        pnl = (stop_level_dec - entry_dec) / DEC_PIP if is_buy else (entry_dec - stop_level_dec) / DEC_PIP
        return (pnl, "STOP")
    if stop_idx <= tgt_idx:
        pnl = (stop_level_dec - entry_dec) / DEC_PIP if is_buy else (entry_dec - stop_level_dec) / DEC_PIP
        return (pnl, "STOP")
    else:
        return (TARGET, "TARGET")


def main() -> int:
    entries = pd.read_parquet(DATA / "stage4_entries.parquet")
    entries["fill_year"] = pd.to_datetime(entries["fill_ts_ns"], unit="ns",
                                          utc=True).dt.year
    # Rejection-extreme (points scale → decimal)
    entries["c1_low_dec"] = entries["c1_low"] / 10000.0
    entries["c1_high_dec"] = entries["c1_high"] / 10000.0
    entries["c2_low_dec"] = entries["c2_low"] / 10000.0
    entries["c2_high_dec"] = entries["c2_high"] / 10000.0
    # Rejection extreme: min(C1,C2) low for BUY, max(C1,C2) high for SELL
    entries["struct_level_dec"] = np.where(
        entries["direction"] == "BUY",
        np.minimum(entries["c1_low_dec"], entries["c2_low_dec"]),
        np.maximum(entries["c1_high_dec"], entries["c2_high_dec"]),
    )

    # For each buffer compute stop_level and distance_pips_from_fill
    rows_out = entries[["c3_ts", "direction", "fill_ts_ns",
                        "fill_price_decimal", "fill_price_points",
                        "spread_pips", "struct_level_dec"]].copy()

    summary = {"target_pips": TARGET, "ig_min_pips": IG_MIN,
               "n_entries": len(entries), "by_buffer": {}}

    for buf in BUFFERS:
        buf_dec = buf * DEC_PIP
        # BUY: stop below struct_level by buf → distance = fill - (struct - buf)
        # SELL: stop above struct_level by buf → distance = (struct + buf) - fill
        is_buy = (entries["direction"] == "BUY")
        stop_dec = np.where(is_buy,
                            entries["struct_level_dec"] - buf_dec,
                            entries["struct_level_dec"] + buf_dec)
        dist_pips = np.where(is_buy,
                             (entries["fill_price_decimal"] - stop_dec) / DEC_PIP,
                             (stop_dec - entries["fill_price_decimal"]) / DEC_PIP)
        rows_out[f"stop_dec_b{buf}"] = stop_dec
        rows_out[f"stop_dist_pips_b{buf}"] = dist_pips.round(2)
        rows_out[f"inelig_b{buf}"] = (dist_pips < IG_MIN) | (dist_pips <= 0)

    # Now simulate each buffer where eligible, year-by-year
    for buf in BUFFERS:
        pnl_col = np.zeros(len(entries), dtype=np.float32)
        reason_col = np.array(["INELIGIBLE"] * len(entries), dtype=object)
        rows_out[f"pnl_b{buf}"] = pnl_col
        rows_out[f"reason_b{buf}"] = reason_col

    # Pre-group by year
    for year in sorted(entries["fill_year"].unique()):
        print(f"  processing year {year} ...", flush=True)
        sub = entries[entries["fill_year"] == year].sort_values("fill_ts_ns")
        tp = TICK_DIR / f"{year}.parquet"
        if not tp.exists():
            continue
        ticks = pd.read_parquet(tp, columns=["ts_utc_ns", "bid", "ask"])
        last_horizon = int(sub["fill_ts_ns"].max()) + HORIZON_NS
        np_path = TICK_DIR / f"{year + 1}.parquet"
        if last_horizon > int(ticks["ts_utc_ns"].iloc[-1]) and np_path.exists():
            tn = pd.read_parquet(np_path, columns=["ts_utc_ns", "bid", "ask"])
            ticks = pd.concat([ticks, tn], ignore_index=True)
            del tn
        ts_arr = ticks["ts_utc_ns"].values.astype(np.int64)
        bid_arr = ticks["bid"].values.astype(np.float32)
        ask_arr = ticks["ask"].values.astype(np.float32)
        for _, r in sub.iterrows():
            fill_ns = int(r["fill_ts_ns"])
            entry_dec = float(r["fill_price_decimal"])
            direction = r["direction"]
            horizon_end_ns = fill_ns + HORIZON_NS
            eow_ns = _end_of_week_ns(fill_ns)
            stop_ns = min(horizon_end_ns, eow_ns)
            start_i = int(np.searchsorted(ts_arr, fill_ns, side="left"))
            end_i = int(np.searchsorted(ts_arr, stop_ns, side="right"))
            if end_i > len(ts_arr):
                end_i = len(ts_arr)
            orig_pos = int(entries.index.get_loc(r.name))
            target_level_dec = (entry_dec + TARGET * DEC_PIP) if direction == "BUY" \
                else (entry_dec - TARGET * DEC_PIP)
            for buf in BUFFERS:
                if rows_out.loc[r.name, f"inelig_b{buf}"]:
                    continue
                stop_level = float(rows_out.loc[r.name, f"stop_dec_b{buf}"])
                pnl, reason = _simulate_abs(
                    ts_arr, bid_arr, ask_arr, start_i, end_i,
                    entry_dec, direction, stop_level, target_level_dec,
                )
                rows_out.at[r.name, f"pnl_b{buf}"] = pnl
                rows_out.at[r.name, f"reason_b{buf}"] = reason
        del ticks, ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    rows_out.to_parquet(DATA / "stage8_structural_stop_trades.parquet", index=False)

    for buf in BUFFERS:
        pnl = rows_out[f"pnl_b{buf}"].astype(float)
        reason = rows_out[f"reason_b{buf}"].astype(str)
        dist = rows_out[f"stop_dist_pips_b{buf}"].astype(float)
        inelig = int((reason == "INELIGIBLE").sum())
        active = pnl[reason != "INELIGIBLE"]
        active_dist = dist[reason != "INELIGIBLE"]
        winners = active[active > 0]
        losers = active[active < 0]
        gross_win = float(winners.sum())
        gross_loss = float(abs(losers.sum()))
        summary["by_buffer"][f"b{buf}"] = {
            "ineligible_lt_ig_min": inelig,
            "eligible": int(len(active)),
            "mean_stop_distance_pips": round(float(active_dist.mean()) if len(active_dist) else 0.0, 2),
            "median_stop_distance_pips": round(float(active_dist.median()) if len(active_dist) else 0.0, 2),
            "max_stop_distance_pips": round(float(active_dist.max()) if len(active_dist) else 0.0, 2),
            "winners": int((active > 0).sum()),
            "losers": int((active < 0).sum()),
            "win_rate_pct": round(100.0 * (active > 0).mean(), 2) if len(active) else 0.0,
            "avg_win_pips": round(float(winners.mean()) if len(winners) else 0.0, 2),
            "avg_loss_pips": round(float(losers.mean()) if len(losers) else 0.0, 2),
            "net_pips": round(float(active.sum()), 1),
            "expectancy_pips": round(float(active.mean()) if len(active) else 0.0, 3),
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        }
    (DATA / "stage8_structural_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
