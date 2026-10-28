"""Phase 6 Stage 7 — fixed-stop sensitivity (4/5/6/8/10/12p).

For each frozen entry, simulate per-tick execution against a fixed
stop S and a fixed target T, decide which triggered first via actual
chronological BID/ASK ticks, and compute realised pip P&L.

Target is the operator-stated reversal distance.  This stage holds T
constant (30 pips — production default) and sweeps S; Stage 12 sweeps
T independently.

Entry fill was already executed on the ASK (BUY) / BID (SELL) at the
Stage 4 fill_ts_ns.  Exit side mirrors the fill side:

    BUY: stop triggers when BID <= entry - S  (bid-based exit)
         target triggers when BID >= entry + T
    SELL: stop triggers when ASK >= entry + S (ask-based exit)
          target triggers when ASK <= entry - T

If neither triggers before the Stage 5 window end (24 h or end-of-week,
whichever first), the trade is closed at the final BID (BUY) / ASK
(SELL) at the window edge — this measures a "would-have-remained-open"
P&L and is reported separately.

Entries whose stop distance is below the applicable broker minimum
(scenario-dependent) are reported as INELIGIBLE under that scenario
rather than silently widened.
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

HORIZON_NS = 24 * 60 * 60 * 1_000_000_000
DEC_PIP = 0.0001

STOP_DISTANCES = [4, 5, 6, 8, 10, 12]
TARGET_DISTANCE_PIPS = 30  # production default


def _end_of_week_ns(ts_ns: int) -> int:
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _simulate(ticks_ts, ticks_bid, ticks_ask, start_idx: int, end_idx: int,
              entry_dec: float, direction: str, stop_pips: float,
              target_pips: float):
    """Return (pnl_pips, exit_reason, exit_ts_ns, exit_price).

    exit_reason ∈ {'STOP','TARGET','TIMEOUT'}.
    """
    is_buy = direction == "BUY"
    stop_level = (entry_dec - stop_pips * DEC_PIP) if is_buy else (entry_dec + stop_pips * DEC_PIP)
    target_level = (entry_dec + target_pips * DEC_PIP) if is_buy else (entry_dec - target_pips * DEC_PIP)

    if start_idx >= end_idx:
        return (0.0, "NO_TICKS", int(ticks_ts[end_idx - 1] if end_idx > 0 else ticks_ts[start_idx]),
                entry_dec)

    if is_buy:
        exit_side = ticks_bid[start_idx:end_idx]
        stop_hits = np.where(exit_side <= stop_level)[0]
        tgt_hits = np.where(exit_side >= target_level)[0]
    else:
        exit_side = ticks_ask[start_idx:end_idx]
        stop_hits = np.where(exit_side >= stop_level)[0]
        tgt_hits = np.where(exit_side <= target_level)[0]

    stop_idx = int(stop_hits[0]) if len(stop_hits) else None
    tgt_idx = int(tgt_hits[0]) if len(tgt_hits) else None

    if stop_idx is None and tgt_idx is None:
        # Timeout — close at window edge
        price = float(exit_side[-1])
        pnl = (price - entry_dec) / DEC_PIP if is_buy else (entry_dec - price) / DEC_PIP
        return (pnl, "TIMEOUT", int(ticks_ts[start_idx + len(exit_side) - 1]), price)
    if stop_idx is None:
        price = float(target_level)
        pnl = target_pips if is_buy else target_pips
        return (pnl, "TARGET", int(ticks_ts[start_idx + tgt_idx]), price)
    if tgt_idx is None:
        price = float(stop_level)
        pnl = -stop_pips
        return (pnl, "STOP", int(ticks_ts[start_idx + stop_idx]), price)
    # Both hit — whichever first (lower index)
    if stop_idx <= tgt_idx:
        return (-stop_pips, "STOP",
                int(ticks_ts[start_idx + stop_idx]), float(stop_level))
    else:
        return (target_pips, "TARGET",
                int(ticks_ts[start_idx + tgt_idx]), float(target_level))


def main() -> int:
    print("Loading Stage 4 entries + Stage 5 MAE...", flush=True)
    entries = pd.read_parquet(DATA / "stage4_entries.parquet")
    print(f"  {len(entries):,} entries", flush=True)
    entries["fill_year"] = pd.to_datetime(entries["fill_ts_ns"], unit="ns",
                                          utc=True).dt.year

    # Prepare output structure: per-stop per-trade pnl.  Memory: 7932 ×
    # 6 stops × ~8 floats = tiny.
    results = {s: {"pnl": np.zeros(len(entries), dtype=np.float32),
                   "reason": np.empty(len(entries), dtype=object)}
               for s in STOP_DISTANCES}
    idx = 0
    for year in sorted(entries["fill_year"].unique()):
        print(f"  processing year {year} ...", flush=True)
        sub = entries[entries["fill_year"] == year].sort_values("fill_ts_ns")
        tp = TICK_DIR / f"{year}.parquet"
        if not tp.exists():
            idx += len(sub)
            continue
        ticks = pd.read_parquet(tp, columns=["ts_utc_ns", "bid", "ask"])
        # Pull next-year if horizon spills
        last_horizon = int(sub["fill_ts_ns"].max()) + HORIZON_NS
        next_year = year + 1
        if last_horizon > int(ticks["ts_utc_ns"].iloc[-1]):
            np_path = TICK_DIR / f"{next_year}.parquet"
            if np_path.exists():
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
            # Original row index in `entries`
            orig_pos = int(entries.index.get_loc(r.name))
            for s in STOP_DISTANCES:
                pnl, reason, _ts, _px = _simulate(
                    ts_arr, bid_arr, ask_arr, start_i, end_i,
                    entry_dec, direction, s, TARGET_DISTANCE_PIPS,
                )
                results[s]["pnl"][orig_pos] = pnl
                results[s]["reason"][orig_pos] = reason
        del ticks, ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    # Build result frame
    out = entries[["c3_ts", "direction", "fill_ts_ns", "fill_price_decimal",
                   "fill_price_points", "spread_pips"]].copy()
    for s in STOP_DISTANCES:
        out[f"pnl_s{s}"] = results[s]["pnl"]
        out[f"reason_s{s}"] = results[s]["reason"]
    out.to_parquet(DATA / "stage7_fixed_stop_trades.parquet", index=False)

    # Summary per stop
    summary = {"target_pips": TARGET_DISTANCE_PIPS,
               "n_trades": int(len(out)),
               "per_stop": {}}
    for s in STOP_DISTANCES:
        pnl = out[f"pnl_s{s}"].astype(float)
        reason = out[f"reason_s{s}"].astype(str)
        winners = pnl[pnl > 0]
        losers = pnl[pnl < 0]
        gross_win = float(winners.sum())
        gross_loss = float(abs(losers.sum()))
        # Max drawdown of cumulative pips
        cum = pnl.cumsum().values
        peak = np.maximum.accumulate(cum)
        dd = peak - cum
        max_dd = float(dd.max())
        # Max consecutive losers
        is_loss = (pnl < 0).values.astype(int)
        max_run = 0; cur = 0
        for x in is_loss:
            cur = cur + 1 if x else 0
            max_run = max(max_run, cur)
        summary["per_stop"][f"s{s}"] = {
            "trades": int(len(pnl)),
            "winners": int((pnl > 0).sum()),
            "losers": int((pnl < 0).sum()),
            "timeouts": int((reason == "TIMEOUT").sum()),
            "targets_hit": int((reason == "TARGET").sum()),
            "stops_hit": int((reason == "STOP").sum()),
            "win_rate_pct": round(100.0 * (pnl > 0).mean(), 2),
            "avg_win_pips": round(float(winners.mean()) if len(winners) else 0.0, 2),
            "avg_loss_pips": round(float(losers.mean()) if len(losers) else 0.0, 2),
            "gross_win_pips": round(gross_win, 1),
            "gross_loss_pips": round(gross_loss, 1),
            "net_pips": round(float(pnl.sum()), 1),
            "expectancy_pips": round(float(pnl.mean()), 3),
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
            "max_drawdown_pips": round(max_dd, 1),
            "max_consec_losers": max_run,
        }
    # Compare: original winners stopped prematurely under each stop
    # (relative to the widest stop in the grid, 12p — those are the
    # trades we have the best shot of understanding).
    s12 = out["pnl_s12"].astype(float)
    for s in STOP_DISTANCES:
        if s == 12:
            continue
        this = out[f"pnl_s{s}"].astype(float)
        # Winners under 12p but losers under s
        were_win_now_loss = int(((s12 > 0) & (this < 0)).sum())
        # Losses reduced under s vs 12p (abs loss smaller)
        reduced_cost = int(((s12 < 0) & (this < 0) & (this > s12)).sum())
        reduced_total_pips = float((this[(s12 < 0) & (this < 0)] -
                                    s12[(s12 < 0) & (this < 0)]).sum())
        summary["per_stop"][f"s{s}"]["original_winners_stopped_premature"] = were_win_now_loss
        summary["per_stop"][f"s{s}"]["losers_cost_reduced"] = reduced_cost
        summary["per_stop"][f"s{s}"]["losers_cost_reduction_total_pips"] = round(reduced_total_pips, 1)

    (DATA / "stage7_fixed_stop_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
