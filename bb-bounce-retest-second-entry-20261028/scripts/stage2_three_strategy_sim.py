"""Phase 7 Stage 2 — Strategy A / B / C per-opportunity tick simulation.

For every opportunity:
    A — first-entry only (= Phase 6 behaviour).
    B — wait-for-retest only: no first entry; enter on confirmation
        fill if the retest was VALID within the retest window.
    C — first entry; if first stop hits, take second entry on
        confirmation fill (if VALID within window AND second-entry
        fill_ts strictly after the first stop ts).

All stops / targets are per the pre-registered grid.  Chronological
BID/ASK execution identical to Phase 6: BUY stop/target against BID;
SELL against ASK.  Horizon per entry: min(24h after fill_ts, Friday
21:00 UTC).

For the full grid:
    s1 ∈ {4, 6, 8, 12}  — Strategy A + first leg of C
    s2 ∈ {4, 6, 8, 12}  — Strategy B stop + second leg of C
                          (six pre-registered (s1,s2) combos for C)
    T  ∈ {30, 40, 50, 60}
    retest_window ∈ {5, 10, 15, 30, 60} min

Produces `data/stage2_abc_trades.parquet` with per-opportunity P&L for
each pre-registered cell combination.
"""
from __future__ import annotations

import json
import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
TICK_DIR = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")

DEC_PIP = 0.0001
HORIZON_NS = 24 * 60 * 60 * 1_000_000_000

STOPS_S1 = [4, 6, 8, 12]
STOPS_S2 = [4, 6, 8, 12]
TARGETS = [30, 40, 50, 60]
WINDOWS_MIN = [5, 10, 15, 30, 60]

# Pre-registered (s1,s2) combos for Strategy C (brief §11)
C_COMBOS = [(4, 4), (4, 6), (4, 8), (4, 12), (6, 6), (12, 12)]


def _end_of_week_ns(ts_ns):
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _simulate_fill(ts_arr, exit_side_arr, start_idx, end_idx,
                   entry_dec, stop_level_dec, target_level_dec,
                   is_buy: bool, stop_pips: float, target_pips: float):
    """Return (pnl_pips, exit_reason, exit_idx) for a single fill."""
    if start_idx >= end_idx:
        return (0.0, "NO_TICKS", start_idx)
    seg = exit_side_arr[start_idx:end_idx]
    if is_buy:
        stop_hits = np.where(seg <= stop_level_dec)[0]
        tgt_hits = np.where(seg >= target_level_dec)[0]
    else:
        stop_hits = np.where(seg >= stop_level_dec)[0]
        tgt_hits = np.where(seg <= target_level_dec)[0]
    s = int(stop_hits[0]) if len(stop_hits) else None
    tg = int(tgt_hits[0]) if len(tgt_hits) else None
    if s is None and tg is None:
        price = float(seg[-1])
        pnl = (price - entry_dec) / DEC_PIP if is_buy else (entry_dec - price) / DEC_PIP
        return (pnl, "TIMEOUT", start_idx + len(seg) - 1)
    if s is None:
        return (target_pips, "TARGET", start_idx + tg)
    if tg is None:
        return (-stop_pips, "STOP", start_idx + s)
    if s <= tg:
        return (-stop_pips, "STOP", start_idx + s)
    return (target_pips, "TARGET", start_idx + tg)


def main() -> int:
    opps = pd.read_parquet(DATA / "opportunities.parquet")
    rt = pd.read_parquet(DATA / "stage1_retest_events.parquet")
    # Merge
    df = opps.merge(
        rt[["c3_ts", "direction", "fill_ts_ns", "outcome",
            "retest_delay_s", "confirm_delay_s",
            "second_fill_ts_ns", "second_fill_price_decimal"]],
        on=["c3_ts", "direction", "fill_ts_ns"], how="left",
    )
    df["fill_year"] = pd.to_datetime(df["fill_ts_ns"], unit="ns", utc=True).dt.year
    print(f"opportunities merged: {len(df):,}", flush=True)

    # Preallocate per-cell result arrays
    # Strategy A: s1 × T
    # Strategy B: s2 × T × window
    # Strategy C: (s1,s2) × T × window

    A_cells = [(s, t) for s in STOPS_S1 for t in TARGETS]
    B_cells = [(s, t, w) for s in STOPS_S2 for t in TARGETS for w in WINDOWS_MIN]
    C_cells = [(c, t, w) for c in C_COMBOS for t in TARGETS for w in WINDOWS_MIN]

    N = len(df)
    A_pnl = {cell: np.zeros(N, dtype=np.float32) for cell in A_cells}
    A_rsn = {cell: np.empty(N, dtype=object) for cell in A_cells}
    B_pnl = {cell: np.zeros(N, dtype=np.float32) for cell in B_cells}
    B_rsn = {cell: np.empty(N, dtype=object) for cell in B_cells}
    C_pnl = {cell: np.zeros(N, dtype=np.float32) for cell in C_cells}
    C_cat = {cell: np.empty(N, dtype=object) for cell in C_cells}

    for year in sorted(df["fill_year"].unique()):
        print(f"  year {year} ...", flush=True)
        sub = df[df["fill_year"] == year].sort_values("fill_ts_ns")
        tp = TICK_DIR / f"{year}.parquet"
        if not tp.exists():
            continue
        ticks = pd.read_parquet(tp, columns=["ts_utc_ns", "bid", "ask"])
        last_horizon = int(sub["fill_ts_ns"].max()) + HORIZON_NS + 60*60*1_000_000_000
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
            entry1 = float(r["fill_price_decimal"])
            direction = r["direction"]
            is_buy = direction == "BUY"
            exit_side = bid_arr if is_buy else ask_arr

            eow_ns = _end_of_week_ns(fill_ns)
            horizon1_end = min(fill_ns + HORIZON_NS, eow_ns)
            start1 = int(np.searchsorted(ts_arr, fill_ns, side="left"))
            end1 = int(np.searchsorted(ts_arr, horizon1_end, side="right"))

            orig = int(df.index.get_loc(r.name))

            # ---------- Strategy A ----------
            for s1, t in A_cells:
                sign_s1 = -1 if is_buy else 1
                sign_t = 1 if is_buy else -1
                stop_level = entry1 + sign_s1 * s1 * DEC_PIP
                target_level = entry1 + sign_t * t * DEC_PIP
                pnl, reason, _ = _simulate_fill(
                    ts_arr, exit_side, start1, end1,
                    entry1, stop_level, target_level,
                    is_buy, s1, t,
                )
                A_pnl[(s1, t)][orig] = pnl
                A_rsn[(s1, t)][orig] = reason

            # ---------- Prepare second-entry data ----------
            # second entry only valid when stage1 produced VALID AND within window
            has_second_candidate = r["outcome"] == "VALID"
            if has_second_candidate:
                second_fill_ns = int(r["second_fill_ts_ns"])
                entry2 = float(r["second_fill_price_decimal"])
                confirm_delay_min = float(r["confirm_delay_s"]) / 60.0
                second_horizon_end = min(second_fill_ns + HORIZON_NS, _end_of_week_ns(second_fill_ns))
                start2 = int(np.searchsorted(ts_arr, second_fill_ns, side="left"))
                end2 = int(np.searchsorted(ts_arr, second_horizon_end, side="right"))
            else:
                confirm_delay_min = None
                second_fill_ns = None
                entry2 = None

            # ---------- Strategy B ----------
            for s2, t, w in B_cells:
                if (not has_second_candidate) or (confirm_delay_min is None) or (confirm_delay_min > w):
                    B_pnl[(s2, t, w)][orig] = 0.0
                    B_rsn[(s2, t, w)][orig] = "NO_TRADE"
                    continue
                sign_s2 = -1 if is_buy else 1
                sign_t = 1 if is_buy else -1
                stop_level2 = entry2 + sign_s2 * s2 * DEC_PIP
                target_level2 = entry2 + sign_t * t * DEC_PIP
                pnl2, reason2, _ = _simulate_fill(
                    ts_arr, exit_side, start2, end2,
                    entry2, stop_level2, target_level2,
                    is_buy, s2, t,
                )
                B_pnl[(s2, t, w)][orig] = pnl2
                B_rsn[(s2, t, w)][orig] = reason2

            # ---------- Strategy C ----------
            # First we need: did s1 stop occur before any target?
            # We'll compute per s1 (reuse A results per s1 at T=INF effectively — but
            # here T matters because target may hit before stop).
            for (s1c, s2c), t, w in [(combo, tt, ww) for combo in C_COMBOS
                                      for tt in TARGETS for ww in WINDOWS_MIN]:
                # First leg under this stop/target
                sign_s1 = -1 if is_buy else 1
                sign_t = 1 if is_buy else -1
                stop_level1 = entry1 + sign_s1 * s1c * DEC_PIP
                target_level1 = entry1 + sign_t * t * DEC_PIP
                pnl1, rsn1, exit_i1 = _simulate_fill(
                    ts_arr, exit_side, start1, end1,
                    entry1, stop_level1, target_level1,
                    is_buy, s1c, t,
                )
                # If first leg won (TARGET) → combined = pnl1, category A
                # If first leg timed out → combined = pnl1, category A (treat timeout as A — win or small loss)
                # If first leg stopped → consider second entry
                if rsn1 != "STOP":
                    C_pnl[((s1c, s2c), t, w)][orig] = pnl1
                    C_cat[((s1c, s2c), t, w)][orig] = (
                        "A_FIRST_WIN" if rsn1 == "TARGET" else
                        ("A_FIRST_TIMEOUT_PROFIT" if pnl1 >= 0 else "A_FIRST_TIMEOUT_LOSS")
                    )
                    continue
                # First leg stopped out.  Can we take a second?
                if (not has_second_candidate) or (confirm_delay_min is None) or \
                   (confirm_delay_min > w):
                    C_pnl[((s1c, s2c), t, w)][orig] = pnl1
                    C_cat[((s1c, s2c), t, w)][orig] = "D_FIRST_STOP_NO_SECOND"
                    continue
                # Second-entry fill must be AFTER the first stop ts
                first_stop_ts = int(ts_arr[exit_i1])
                if second_fill_ns is None or second_fill_ns <= first_stop_ts:
                    C_pnl[((s1c, s2c), t, w)][orig] = pnl1
                    C_cat[((s1c, s2c), t, w)][orig] = "D_SECOND_BEFORE_STOP"
                    continue
                stop_level2 = entry2 + sign_s2 * s2c * DEC_PIP
                target_level2 = entry2 + sign_t * t * DEC_PIP
                sign_s2 = -1 if is_buy else 1
                pnl2, rsn2, _ = _simulate_fill(
                    ts_arr, exit_side, start2, end2,
                    entry2, stop_level2, target_level2,
                    is_buy, s2c, t,
                )
                total = pnl1 + pnl2
                if pnl2 > 0:
                    C_cat[((s1c, s2c), t, w)][orig] = "B_SECOND_WIN"
                elif pnl2 < 0:
                    C_cat[((s1c, s2c), t, w)][orig] = "C_SECOND_LOSS"
                else:
                    C_cat[((s1c, s2c), t, w)][orig] = "C_SECOND_FLAT"
                C_pnl[((s1c, s2c), t, w)][orig] = total

        del ticks, ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    # Materialise
    out = df[["c3_ts", "direction", "fill_ts_ns", "fill_price_decimal",
              "spread_pips", "outcome",
              "retest_delay_s", "confirm_delay_s"]].copy()
    for cell, pnl in A_pnl.items():
        s, t = cell
        out[f"A_s{s}_t{t}_pnl"] = pnl
        out[f"A_s{s}_t{t}_rsn"] = A_rsn[cell]
    for cell, pnl in B_pnl.items():
        s, t, w = cell
        out[f"B_s{s}_t{t}_w{w}_pnl"] = pnl
        out[f"B_s{s}_t{t}_w{w}_rsn"] = B_rsn[cell]
    for cell, pnl in C_pnl.items():
        (s1, s2), t, w = cell
        out[f"C_s{s1}_{s2}_t{t}_w{w}_pnl"] = pnl
        out[f"C_s{s1}_{s2}_t{t}_w{w}_cat"] = C_cat[cell]

    out.to_parquet(DATA / "stage2_abc_trades.parquet", index=False)

    # Summary — focus on key cells
    def _stats(x: np.ndarray) -> dict:
        x = np.asarray(x, dtype=np.float64)
        active = x[~np.isnan(x) & (x != 0.0)]
        # For B strategy, zero-pnl rows mean NO_TRADE — exclude from win/loss stats
        # but include in trades count ONLY if we want "trades taken".  Use active for
        # win-rate purposes.
        winners = x[x > 0]; losers = x[x < 0]
        gw = float(winners.sum()); gl = float(abs(losers.sum()))
        return {
            "opportunities": int(len(x)),
            "winners": int((x > 0).sum()),
            "losers": int((x < 0).sum()),
            "net_pips": round(float(x.sum()), 1),
            "expectancy_per_opp_pips": round(float(x.mean()), 3),
            "profit_factor": round(gw / gl, 3) if gl > 0 else None,
        }

    summary = {"A": {}, "B": {}, "C": {}}
    for cell, pnl in A_pnl.items():
        s, t = cell
        summary["A"][f"s{s}_t{t}"] = _stats(pnl)
    for cell, pnl in B_pnl.items():
        s, t, w = cell
        row = _stats(pnl)
        row["trades_taken"] = int((B_rsn[cell] != "NO_TRADE").sum())
        row["skipped"] = int((B_rsn[cell] == "NO_TRADE").sum())
        summary["B"][f"s{s}_t{t}_w{w}"] = row
    for cell, pnl in C_pnl.items():
        (s1, s2), t, w = cell
        row = _stats(pnl)
        cats = pd.Series(C_cat[cell]).value_counts().to_dict()
        row["categories"] = cats
        summary["C"][f"s{s1}_{s2}_t{t}_w{w}"] = row

    (DATA / "stage2_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # Terse console output: key cells
    print("\n=== Strategy A (first-entry only) ===")
    for s in STOPS_S1:
        for t in TARGETS:
            s_cell = summary["A"][f"s{s}_t{t}"]
            print(f"  s{s}/t{t}: net={s_cell['net_pips']} expy={s_cell['expectancy_per_opp_pips']} "
                  f"pf={s_cell['profit_factor']}")

    print("\n=== Strategy B (wait-for-retest only, window=60min) ===")
    for s in STOPS_S2:
        for t in TARGETS:
            key = f"s{s}_t{t}_w60"
            c = summary["B"][key]
            print(f"  s{s}/t{t}/w60: trades={c['trades_taken']} skipped={c['skipped']} "
                  f"net={c['net_pips']} expy={c['expectancy_per_opp_pips']} pf={c['profit_factor']}")

    print("\n=== Strategy C (first + second entry, window=60min) ===")
    for (s1, s2) in C_COMBOS:
        for t in TARGETS:
            key = f"s{s1}_{s2}_t{t}_w60"
            c = summary["C"][key]
            print(f"  C({s1},{s2})/t{t}/w60: net={c['net_pips']} expy={c['expectancy_per_opp_pips']} "
                  f"pf={c['profit_factor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
