"""Phase 6 Stage 12 — target sensitivity (20/30/40/50/60p).

Full grid: 6 stop distances × 5 target distances = 30 cells.

Reuses the Stage 7 simulator (fixed stop + fixed target, tick-level
BID/ASK execution over 24h / end-of-week).  No re-entry; frozen entry
population from Stage 4.
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

STOPS = [4, 5, 6, 8, 10, 12]
TARGETS = [20, 30, 40, 50, 60]


def _end_of_week_ns(ts_ns):
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _grid_simulate(ts_arr, bid_arr, ask_arr, start_idx, end_idx,
                   entry_dec, direction, stop_pips_list, tgt_pips_list):
    """Return dict (stop, target) → (pnl_pips, reason)."""
    is_buy = direction == "BUY"
    if start_idx >= end_idx:
        return {(s, t): (0.0, "NO_TICKS") for s in stop_pips_list for t in tgt_pips_list}
    if is_buy:
        exit_side = bid_arr[start_idx:end_idx]
    else:
        exit_side = ask_arr[start_idx:end_idx]
    results = {}
    for s in stop_pips_list:
        stop_level = (entry_dec - s * DEC_PIP) if is_buy else (entry_dec + s * DEC_PIP)
        if is_buy:
            stop_hits = np.where(exit_side <= stop_level)[0]
        else:
            stop_hits = np.where(exit_side >= stop_level)[0]
        stop_idx = int(stop_hits[0]) if len(stop_hits) else None
        for t in tgt_pips_list:
            tgt_level = (entry_dec + t * DEC_PIP) if is_buy else (entry_dec - t * DEC_PIP)
            if is_buy:
                tgt_hits = np.where(exit_side >= tgt_level)[0]
            else:
                tgt_hits = np.where(exit_side <= tgt_level)[0]
            tgt_idx = int(tgt_hits[0]) if len(tgt_hits) else None
            if stop_idx is None and tgt_idx is None:
                price = float(exit_side[-1])
                pnl = (price - entry_dec) / DEC_PIP if is_buy else (entry_dec - price) / DEC_PIP
                results[(s, t)] = (pnl, "TIMEOUT")
            elif stop_idx is None:
                results[(s, t)] = (t, "TARGET")
            elif tgt_idx is None:
                results[(s, t)] = (-s, "STOP")
            elif stop_idx <= tgt_idx:
                results[(s, t)] = (-s, "STOP")
            else:
                results[(s, t)] = (t, "TARGET")
    return results


def main():
    entries = pd.read_parquet(DATA / "stage4_entries.parquet")
    entries["fill_year"] = pd.to_datetime(entries["fill_ts_ns"], unit="ns",
                                          utc=True).dt.year

    # Pre-allocate pnl matrix
    pnl_mat = {(s, t): np.zeros(len(entries), dtype=np.float32)
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
            cell = _grid_simulate(ts_arr, bid_arr, ask_arr, start_i, end_i,
                                  entry_dec, direction, STOPS, TARGETS)
            for (s, t), (pnl, _reason) in cell.items():
                pnl_mat[(s, t)][orig_pos] = pnl
        del ticks, ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    # Summarise grid
    grid = {}
    best_cell = None
    best_expy = -1e9
    for s in STOPS:
        row = {}
        for t in TARGETS:
            pnl = pnl_mat[(s, t)]
            winners = pnl[pnl > 0]
            losers = pnl[pnl < 0]
            gross_w = float(winners.sum())
            gross_l = float(abs(losers.sum()))
            cell = {
                "trades": int(len(pnl)),
                "winners": int((pnl > 0).sum()),
                "losers": int((pnl < 0).sum()),
                "win_rate_pct": round(100.0 * (pnl > 0).mean(), 2),
                "avg_win_pips": round(float(winners.mean()) if len(winners) else 0.0, 2),
                "avg_loss_pips": round(float(losers.mean()) if len(losers) else 0.0, 2),
                "net_pips": round(float(pnl.sum()), 1),
                "expectancy_pips": round(float(pnl.mean()), 3),
                "profit_factor": round(gross_w / gross_l, 3) if gross_l > 0 else None,
            }
            row[f"t{t}"] = cell
            if cell["expectancy_pips"] > best_expy:
                best_expy = cell["expectancy_pips"]
                best_cell = (s, t, cell)
        grid[f"s{s}"] = row

    summary = {
        "n_trades": int(len(entries)),
        "best_cell": {"stop": best_cell[0], "target": best_cell[1], **best_cell[2]} if best_cell else None,
        "grid": grid,
    }
    (DATA / "stage12_target_sensitivity.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    print(json.dumps(summary["best_cell"], indent=2))
    # Pretty net-pips table
    print("\nNET PIPS GRID (rows=stop, cols=target):")
    print("        " + " ".join(f"T={t:3}" for t in TARGETS))
    for s in STOPS:
        row = grid[f"s{s}"]
        cells = " ".join(f"{row[f't{t}']['net_pips']:>6.0f}" for t in TARGETS)
        print(f"  S={s:3}: {cells}")
    print("\nEXPECTANCY GRID (pips/trade):")
    print("        " + " ".join(f"T={t:3}" for t in TARGETS))
    for s in STOPS:
        row = grid[f"s{s}"]
        cells = " ".join(f"{row[f't{t}']['expectancy_pips']:>6.3f}" for t in TARGETS)
        print(f"  S={s:3}: {cells}")
    print("\nPROFIT FACTOR GRID:")
    print("        " + " ".join(f"T={t:3}" for t in TARGETS))
    for s in STOPS:
        row = grid[f"s{s}"]
        cells = " ".join(f"{(row[f't{t}']['profit_factor'] or 0):>6.3f}" for t in TARGETS)
        print(f"  S={s:3}: {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
