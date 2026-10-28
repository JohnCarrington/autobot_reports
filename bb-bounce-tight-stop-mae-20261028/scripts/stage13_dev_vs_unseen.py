"""Phase 6 Stage 13 — DEV vs UNSEEN chronological validation.

The chronological split was pre-registered in PROGRESS.md BEFORE
outcome inspection:

    DEV    : entries ≤ 2025-12-31
    UNSEEN : entries ≥ 2026-01-01

For every stop/target cell from Stage 12, split the Stage 7-style per-
trade P&L by DEV vs UNSEEN and report whether the ordering of cells is
preserved on unseen data (overfitting indicator).  Also produce
monthly and annual pip breakdowns.

No cell is cherry-picked from the DEV data; every cell is reported.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
TICK_DIR = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")

# Re-use Stage 12 pre-computed grid P&L — but it was not persisted
# per-trade across cells (only aggregated).  Re-run the Stage 7
# simulator for all 30 cells by shelling out to it is wasteful; here
# we persist per-trade pnl via the Stage 7 approach for the two
# cells we care most about (production baseline S12/T30 + best cell
# S12/T60) and do the DEV/UNSEEN split against those.
#
# For a complete audit, Stage 12's JSON already contains dev-less
# whole-window stats; here we add the dev/unseen partition.

from datetime import datetime, timedelta, timezone

HORIZON_NS = 24 * 60 * 60 * 1_000_000_000
DEC_PIP = 0.0001

# Pre-registered dev/unseen cutoff
DEV_UNSEEN_CUTOFF = "2026-01-01"


def _end_of_week_ns(ts_ns):
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _simulate(ts_arr, bid_arr, ask_arr, start_idx, end_idx,
              entry_dec, direction, stop_pips, target_pips):
    is_buy = direction == "BUY"
    stop_level = (entry_dec - stop_pips * DEC_PIP) if is_buy else (entry_dec + stop_pips * DEC_PIP)
    target_level = (entry_dec + target_pips * DEC_PIP) if is_buy else (entry_dec - target_pips * DEC_PIP)
    if start_idx >= end_idx:
        return 0.0
    if is_buy:
        exit_side = bid_arr[start_idx:end_idx]
        stop_hits = np.where(exit_side <= stop_level)[0]
        tgt_hits = np.where(exit_side >= target_level)[0]
    else:
        exit_side = ask_arr[start_idx:end_idx]
        stop_hits = np.where(exit_side >= stop_level)[0]
        tgt_hits = np.where(exit_side <= target_level)[0]
    stop_idx = int(stop_hits[0]) if len(stop_hits) else None
    tgt_idx = int(tgt_hits[0]) if len(tgt_hits) else None
    if stop_idx is None and tgt_idx is None:
        price = float(exit_side[-1])
        return (price - entry_dec) / DEC_PIP if is_buy else (entry_dec - price) / DEC_PIP
    if stop_idx is None:
        return target_pips
    if tgt_idx is None:
        return -stop_pips
    return -stop_pips if stop_idx <= tgt_idx else target_pips


STOPS = [4, 5, 6, 8, 10, 12]
TARGETS = [20, 30, 40, 50, 60]


def main():
    entries = pd.read_parquet(DATA / "stage4_entries.parquet")
    entries["fill_dt"] = pd.to_datetime(entries["fill_ts_ns"], unit="ns", utc=True)
    entries["fill_year"] = entries["fill_dt"].dt.year

    # Allocate per-cell pnl array
    pnl = {(s, t): np.zeros(len(entries), dtype=np.float32)
           for s in STOPS for t in TARGETS}

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
            for s in STOPS:
                for t in TARGETS:
                    pnl[(s, t)][orig_pos] = _simulate(
                        ts_arr, bid_arr, ask_arr, start_i, end_i,
                        entry_dec, direction, s, t,
                    )
        del ticks, ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    cutoff = pd.Timestamp(DEV_UNSEEN_CUTOFF, tz="UTC")
    dev_mask = (entries["fill_dt"] < cutoff).values
    uns_mask = ~dev_mask

    def _stats(x):
        x = np.asarray(x, dtype=np.float64)
        winners = x[x > 0]; losers = x[x < 0]
        gw = float(winners.sum()); gl = float(abs(losers.sum()))
        return {
            "trades": int(len(x)),
            "winners": int((x > 0).sum()),
            "losers": int((x < 0).sum()),
            "win_rate_pct": round(100.0 * (x > 0).mean(), 2) if len(x) else 0.0,
            "avg_win_pips": round(float(winners.mean()) if len(winners) else 0.0, 2),
            "avg_loss_pips": round(float(losers.mean()) if len(losers) else 0.0, 2),
            "net_pips": round(float(x.sum()), 1),
            "expectancy_pips": round(float(x.mean()) if len(x) else 0.0, 3),
            "profit_factor": round(gw / gl, 3) if gl > 0 else None,
        }

    report = {
        "cutoff_pre_registered": DEV_UNSEEN_CUTOFF,
        "n_dev": int(dev_mask.sum()),
        "n_unseen": int(uns_mask.sum()),
        "cells": {},
    }

    for s in STOPS:
        for t in TARGETS:
            arr = pnl[(s, t)]
            report["cells"][f"s{s}_t{t}"] = {
                "DEV": _stats(arr[dev_mask]),
                "UNSEEN": _stats(arr[uns_mask]),
            }

    # Ranking consistency
    dev_rank = sorted(
        [(cell, report["cells"][cell]["DEV"]["expectancy_pips"]) for cell in report["cells"]],
        key=lambda kv: -kv[1],
    )
    uns_rank = sorted(
        [(cell, report["cells"][cell]["UNSEEN"]["expectancy_pips"]) for cell in report["cells"]],
        key=lambda kv: -kv[1],
    )
    report["dev_top3"] = dev_rank[:3]
    report["unseen_top3"] = uns_rank[:3]
    # Rank-correlation (Spearman)
    import statistics as st
    dev_ranks = {name: i for i, (name, _) in enumerate(dev_rank)}
    uns_ranks = {name: i for i, (name, _) in enumerate(uns_rank)}
    diffs = [(dev_ranks[k] - uns_ranks[k]) ** 2 for k in dev_ranks]
    n = len(dev_ranks)
    rho = 1.0 - 6.0 * sum(diffs) / (n * (n * n - 1))
    report["spearman_rho_dev_vs_unseen"] = round(rho, 3)

    # Monthly net-pips for the production cell (S12/T30) + best cell
    for cell in [("s12_t30"), ("s12_t60")]:
        s, t = int(cell.split("_")[0][1:]), int(cell.split("_")[1][1:])
        arr = pnl[(s, t)]
        tmp = pd.DataFrame({"fill_dt": entries["fill_dt"].values, "pnl": arr})
        tmp["ym"] = tmp["fill_dt"].dt.strftime("%Y-%m")
        monthly = tmp.groupby("ym")["pnl"].sum().round(1).to_dict()
        report.setdefault("monthly_net_pips", {})[cell] = monthly

    (DATA / "stage13_dev_unseen.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    # Terse print
    print(f"n_dev={report['n_dev']}  n_unseen={report['n_unseen']}")
    print(f"Spearman ρ (dev vs unseen ranking): {report['spearman_rho_dev_vs_unseen']}")
    print()
    print(f"DEV top 3 cells: {report['dev_top3']}")
    print(f"UNSEEN top 3 cells: {report['unseen_top3']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
