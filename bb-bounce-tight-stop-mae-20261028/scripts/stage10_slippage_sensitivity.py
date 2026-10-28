"""Phase 6 Stage 10 — spread + slippage sensitivity.

Shifts the executable entry fill by an adverse-slippage grid in
{0, 0.5, 1, 2, 3.5} pips.  The tick-level simulator then re-runs the
S/T grid against the shifted entry; stop and target levels move with
the entry (constant distances), so a worse fill produces worse
realised P&L on every trade.

Spread is already paid in the base model (BUY fills on ASK, SELL fills
on BID, exits on the opposite side) — the slippage is an extra adverse
pip count on top.
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

STOPS = [4, 6, 8, 12]
TARGETS = [30, 60]
SLIPPAGES = [0.0, 0.5, 1.0, 2.0, 3.5]


def _end_of_week_ns(ts_ns):
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _sim(ts_arr, bid_arr, ask_arr, start_idx, end_idx, entry_dec, direction,
         stop_pips, target_pips):
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
    s = int(stop_hits[0]) if len(stop_hits) else None
    tg = int(tgt_hits[0]) if len(tgt_hits) else None
    if s is None and tg is None:
        price = float(exit_side[-1])
        return (price - entry_dec) / DEC_PIP if is_buy else (entry_dec - price) / DEC_PIP
    if s is None:
        return target_pips
    if tg is None:
        return -stop_pips
    return -stop_pips if s <= tg else target_pips


def main():
    entries = pd.read_parquet(DATA / "stage4_entries.parquet")
    entries["fill_year"] = pd.to_datetime(entries["fill_ts_ns"], unit="ns",
                                          utc=True).dt.year
    pnl = {(slip, s, t): np.zeros(len(entries), dtype=np.float32)
           for slip in SLIPPAGES for s in STOPS for t in TARGETS}

    for year in sorted(entries["fill_year"].unique()):
        print(f"  year {year} ...", flush=True)
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
            base_entry = float(r["fill_price_decimal"])
            direction = r["direction"]
            horizon_end_ns = fill_ns + HORIZON_NS
            eow_ns = _end_of_week_ns(fill_ns)
            stop_ns = min(horizon_end_ns, eow_ns)
            start_i = int(np.searchsorted(ts_arr, fill_ns, side="left"))
            end_i = int(np.searchsorted(ts_arr, stop_ns, side="right"))
            if end_i > len(ts_arr):
                end_i = len(ts_arr)
            orig_pos = int(entries.index.get_loc(r.name))
            for slip in SLIPPAGES:
                # Adverse: BUY fill moved up; SELL fill moved down
                adj = slip * DEC_PIP
                entry_adj = base_entry + adj if direction == "BUY" else base_entry - adj
                for s in STOPS:
                    for t in TARGETS:
                        pnl[(slip, s, t)][orig_pos] = _sim(
                            ts_arr, bid_arr, ask_arr, start_i, end_i,
                            entry_adj, direction, s, t,
                        )
        del ticks, ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    grid = {}
    for slip in SLIPPAGES:
        for s in STOPS:
            for t in TARGETS:
                arr = pnl[(slip, s, t)]
                winners = arr[arr > 0]
                losers = arr[arr < 0]
                gw = float(winners.sum()); gl = float(abs(losers.sum()))
                grid.setdefault(f"slip{slip}", {})[f"s{s}_t{t}"] = {
                    "net_pips": round(float(arr.sum()), 1),
                    "expectancy_pips": round(float(arr.mean()), 3),
                    "profit_factor": round(gw / gl, 3) if gl > 0 else None,
                    "win_rate_pct": round(100.0 * (arr > 0).mean(), 2),
                }
    (DATA / "stage10_slippage_sensitivity.json").write_text(
        json.dumps({"grid": grid}, indent=2, default=str)
    )
    # Print
    print(f"\n{'Slip':>6} {'Cell':>10} {'Net':>9} {'Expy':>7} {'PF':>6} {'Win%':>6}")
    print('-' * 50)
    for slip in SLIPPAGES:
        for cell_key in [f"s{s}_t{t}" for s in STOPS for t in TARGETS]:
            c = grid[f"slip{slip}"][cell_key]
            print(f"{slip:>6.1f} {cell_key:>10} {c['net_pips']:>9.0f} "
                  f"{c['expectancy_pips']:>7.3f} "
                  f"{(c['profit_factor'] or 0):>6.3f} {c['win_rate_pct']:>6.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
