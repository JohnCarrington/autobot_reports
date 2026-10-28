"""Phase 7 Stage 3 — slippage sensitivity for Strategy B (wait-for-retest).

Apply adverse-entry slippage in {0, 0.5, 1, 2, 3.5} pips to the retest
entry.  Report DEV / UNSEEN per-cell expectancy and PF for key cells.
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
RETEST_WINDOW_MIN = 60


def _end_of_week_ns(ts_ns):
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _sim(ts_arr, exit_side, start, end, entry_dec, is_buy, stop_pips, target_pips):
    sign_s = -1 if is_buy else 1
    sign_t = 1 if is_buy else -1
    stop_level = entry_dec + sign_s * stop_pips * DEC_PIP
    target_level = entry_dec + sign_t * target_pips * DEC_PIP
    if start >= end:
        return 0.0
    seg = exit_side[start:end]
    if is_buy:
        sh = np.where(seg <= stop_level)[0]
        th = np.where(seg >= target_level)[0]
    else:
        sh = np.where(seg >= stop_level)[0]
        th = np.where(seg <= target_level)[0]
    si = int(sh[0]) if len(sh) else None
    ti = int(th[0]) if len(th) else None
    if si is None and ti is None:
        price = float(seg[-1])
        return (price - entry_dec) / DEC_PIP if is_buy else (entry_dec - price) / DEC_PIP
    if si is None:
        return target_pips
    if ti is None:
        return -stop_pips
    return -stop_pips if si <= ti else target_pips


def main() -> int:
    opps = pd.read_parquet(DATA / "opportunities.parquet")
    rt = pd.read_parquet(DATA / "stage1_retest_events.parquet")
    df = opps.merge(
        rt[["c3_ts", "direction", "fill_ts_ns", "outcome",
            "confirm_delay_s", "second_fill_ts_ns", "second_fill_price_decimal"]],
        on=["c3_ts", "direction", "fill_ts_ns"], how="left",
    )
    df["fill_year"] = pd.to_datetime(df["fill_ts_ns"], unit="ns", utc=True).dt.year
    N = len(df)
    pnl = {(slip, s, t): np.zeros(N, dtype=np.float32)
           for slip in SLIPPAGES for s in STOPS for t in TARGETS}

    for year in sorted(df["fill_year"].unique()):
        print(f"  year {year} ...", flush=True)
        sub = df[df["fill_year"] == year].sort_values("fill_ts_ns")
        tp = TICK_DIR / f"{year}.parquet"
        if not tp.exists():
            continue
        ticks = pd.read_parquet(tp, columns=["ts_utc_ns", "bid", "ask"])
        ts_arr = ticks["ts_utc_ns"].values.astype(np.int64)
        bid_arr = ticks["bid"].values.astype(np.float32)
        ask_arr = ticks["ask"].values.astype(np.float32)
        del ticks
        import gc; gc.collect()

        for _, r in sub.iterrows():
            orig = int(df.index.get_loc(r.name))
            if r["outcome"] != "VALID":
                continue
            if pd.isna(r["confirm_delay_s"]) or r["confirm_delay_s"] > RETEST_WINDOW_MIN * 60:
                continue
            direction = r["direction"]
            is_buy = direction == "BUY"
            exit_side = bid_arr if is_buy else ask_arr
            second_fill_ns = int(r["second_fill_ts_ns"])
            base_entry = float(r["second_fill_price_decimal"])
            eow = _end_of_week_ns(second_fill_ns)
            horizon = min(second_fill_ns + HORIZON_NS, eow)
            start = int(np.searchsorted(ts_arr, second_fill_ns, side="left"))
            end = int(np.searchsorted(ts_arr, horizon, side="right"))
            for slip in SLIPPAGES:
                adj = slip * DEC_PIP
                entry_adj = base_entry + adj if is_buy else base_entry - adj
                for s in STOPS:
                    for t in TARGETS:
                        pnl[(slip, s, t)][orig] = _sim(
                            ts_arr, exit_side, start, end,
                            entry_adj, is_buy, s, t,
                        )
        del ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    cutoff_ns = int(pd.Timestamp("2026-01-01", tz="UTC").value)
    dev_mask = (df["fill_ts_ns"].values < cutoff_ns)

    def _stats(x):
        x = np.asarray(x, dtype=np.float64)
        w = x[x > 0]; l = x[x < 0]
        gw = float(w.sum()); gl = float(abs(l.sum()))
        return {
            "trades_taken": int((x != 0.0).sum()),
            "net_pips": round(float(x.sum()), 1),
            "expectancy_per_opp": round(float(x.mean()), 3),
            "profit_factor": round(gw / gl, 3) if gl > 0 else None,
        }

    report = {"grid": {}}
    for slip in SLIPPAGES:
        for s in STOPS:
            for t in TARGETS:
                arr = pnl[(slip, s, t)]
                report["grid"][f"slip{slip}_s{s}_t{t}"] = {
                    "ALL": _stats(arr),
                    "DEV": _stats(arr[dev_mask]),
                    "UNSEEN": _stats(arr[~dev_mask]),
                }
    (DATA / "stage3_slippage_sensitivity.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    # Print table
    print(f"\n{'Cell':25} {'ALL expy':>10} {'ALL PF':>8} {'DEV expy':>10} {'DEV PF':>8} {'UNSEEN expy':>12} {'UNSEEN PF':>10}")
    for slip in SLIPPAGES:
        for s in STOPS:
            for t in TARGETS:
                k = f"slip{slip}_s{s}_t{t}"
                r = report["grid"][k]
                print(f"{k:25} "
                      f"{r['ALL']['expectancy_per_opp']:>10} "
                      f"{(r['ALL']['profit_factor'] or 0):>8} "
                      f"{r['DEV']['expectancy_per_opp']:>10} "
                      f"{(r['DEV']['profit_factor'] or 0):>8} "
                      f"{r['UNSEEN']['expectancy_per_opp']:>12} "
                      f"{(r['UNSEEN']['profit_factor'] or 0):>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
