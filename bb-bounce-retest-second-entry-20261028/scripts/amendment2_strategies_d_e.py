"""Phase 7 Amendment — Strategies D (3rd test only) and E (sequential up to 3).

Strategy D — enter only on the 3rd confirmed test of a reversal area.  No earlier
entries are taken.

Strategy E — enter on the 1st confirmed test (= Phase 6 fire).  If stopped out,
enter on the 2nd confirmed test when it occurs AFTER the 1st-leg stop.  If that
also stops out, enter on the 3rd confirmed test when it occurs AFTER the 2nd-leg
stop.  Combined P&L includes ALL prior losses.  Each entry must respect the
previous leg's exit timing — no overlapping positions.

Grid: (s1, s2, s3) ∈ {(4,4,4), (4,6,6), (6,6,6), (12,12,12), (4,4,12)}
      T ∈ {30, 40, 50, 60}

Outputs per-opportunity combined P&L for D and E, plus DEV/UNSEEN split.
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

HORIZON_NS = 24 * 60 * 60 * 1_000_000_000
DEC_PIP = 0.0001

STOP_COMBOS_E = [(4, 4, 4), (4, 6, 6), (6, 6, 6), (12, 12, 12), (4, 4, 12)]
STOPS_D = [4, 6, 8, 12]
TARGETS = [30, 40, 50, 60]


def _end_of_week_ns(ts_ns):
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    days_to_fri = (4 - dt.weekday()) % 7
    fri = (dt + timedelta(days=days_to_fri)).replace(hour=21, minute=0, second=0, microsecond=0)
    if fri <= dt:
        fri += timedelta(days=7)
    return int(fri.timestamp() * 1e9)


def _sim_leg(ts_arr, exit_side_arr, start_idx, end_idx, entry_dec, is_buy,
             stop_pips, target_pips):
    sign_s = -1 if is_buy else 1
    sign_t = 1 if is_buy else -1
    stop_level = entry_dec + sign_s * stop_pips * DEC_PIP
    target_level = entry_dec + sign_t * target_pips * DEC_PIP
    if start_idx >= end_idx:
        return (0.0, "NO_TICKS", start_idx)
    seg = exit_side_arr[start_idx:end_idx]
    if is_buy:
        stop_hits = np.where(seg <= stop_level)[0]
        tgt_hits = np.where(seg >= target_level)[0]
    else:
        stop_hits = np.where(seg >= stop_level)[0]
        tgt_hits = np.where(seg <= target_level)[0]
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
    return (-stop_pips, "STOP", start_idx + s) if s <= tg else (target_pips, "TARGET", start_idx + tg)


def main() -> int:
    opps = pd.read_parquet(DATA / "opportunities.parquet")
    opps["fill_year"] = pd.to_datetime(opps["fill_ts_ns"], unit="ns",
                                        utc=True).dt.year
    seq = pd.read_parquet(DATA / "amendment1_test_sequences.parquet")

    # Build a per-opportunity dict: fill_ts_ns -> ordered list of tests (test_num, fill_ts_ns, fill_price_decimal)
    tests_by_opp: dict = {}
    for _, r in seq.sort_values(["opp_fill_ts_ns", "test_num"]).iterrows():
        tests_by_opp.setdefault(int(r["opp_fill_ts_ns"]), []).append({
            "test_num": int(r["test_num"]),
            "fill_ts_ns": int(r["test_fill_ts_ns"]),
            "fill_price_decimal": float(r["test_fill_price_decimal"]),
        })

    N = len(opps)
    D_cells = [(s, t) for s in STOPS_D for t in TARGETS]
    E_cells = [(c, t) for c in STOP_COMBOS_E for t in TARGETS]
    D_pnl = {cell: np.zeros(N, dtype=np.float32) for cell in D_cells}
    D_rsn = {cell: np.empty(N, dtype=object) for cell in D_cells}
    E_pnl = {cell: np.zeros(N, dtype=np.float32) for cell in E_cells}
    E_cat = {cell: np.empty(N, dtype=object) for cell in E_cells}

    for year in sorted(opps["fill_year"].unique()):
        print(f"  year {year} ...", flush=True)
        sub = opps[opps["fill_year"] == year].sort_values("fill_ts_ns")
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
            direction = r["direction"]
            is_buy = direction == "BUY"
            exit_side = bid_arr if is_buy else ask_arr
            fill_ns_1 = int(r["fill_ts_ns"])
            orig = int(opps.index.get_loc(r.name))

            tests_list = tests_by_opp.get(fill_ns_1, [])
            # Test 1 is always present (it's the opportunity fill itself)
            # Test 2 present only if valid retest found.  Test 3 similarly.
            def _test_for(n):
                for t in tests_list:
                    if t["test_num"] == n:
                        return t
                return None

            t1 = _test_for(1)
            t2 = _test_for(2)
            t3 = _test_for(3)

            # ----- Strategy D (3rd test only) -----
            for (s, t) in D_cells:
                if t3 is None:
                    D_pnl[(s, t)][orig] = 0.0
                    D_rsn[(s, t)][orig] = "NO_3RD_TEST"
                    continue
                start = int(np.searchsorted(ts_arr, t3["fill_ts_ns"], side="left"))
                eow = _end_of_week_ns(t3["fill_ts_ns"])
                horizon = min(t3["fill_ts_ns"] + HORIZON_NS, eow)
                end = int(np.searchsorted(ts_arr, horizon, side="right"))
                pnl, reason, _ = _sim_leg(ts_arr, exit_side, start, end,
                                           t3["fill_price_decimal"], is_buy, s, t)
                D_pnl[(s, t)][orig] = pnl
                D_rsn[(s, t)][orig] = reason

            # ----- Strategy E (sequential up to 3 confirmed entries) -----
            for (s1, s2, s3), t in E_cells:
                total_pnl = 0.0
                cat = ""
                # Leg 1
                start1 = int(np.searchsorted(ts_arr, t1["fill_ts_ns"], side="left"))
                eow1 = _end_of_week_ns(t1["fill_ts_ns"])
                horizon1 = min(t1["fill_ts_ns"] + HORIZON_NS, eow1)
                end1 = int(np.searchsorted(ts_arr, horizon1, side="right"))
                pnl1, rsn1, exit_i1 = _sim_leg(
                    ts_arr, exit_side, start1, end1,
                    t1["fill_price_decimal"], is_buy, s1, t,
                )
                total_pnl += pnl1
                if rsn1 != "STOP":
                    cat = "A_LEG1_WIN" if rsn1 == "TARGET" else "A_LEG1_TIMEOUT"
                    E_pnl[((s1, s2, s3), t)][orig] = total_pnl
                    E_cat[((s1, s2, s3), t)][orig] = cat
                    continue
                # Leg 2 — only if t2 exists and fill is AFTER leg1 exit
                if t2 is None or t2["fill_ts_ns"] <= int(ts_arr[exit_i1]):
                    cat = "D_LEG1_STOP_NO_LEG2"
                    E_pnl[((s1, s2, s3), t)][orig] = total_pnl
                    E_cat[((s1, s2, s3), t)][orig] = cat
                    continue
                start2 = int(np.searchsorted(ts_arr, t2["fill_ts_ns"], side="left"))
                eow2 = _end_of_week_ns(t2["fill_ts_ns"])
                horizon2 = min(t2["fill_ts_ns"] + HORIZON_NS, eow2)
                end2 = int(np.searchsorted(ts_arr, horizon2, side="right"))
                pnl2, rsn2, exit_i2 = _sim_leg(
                    ts_arr, exit_side, start2, end2,
                    t2["fill_price_decimal"], is_buy, s2, t,
                )
                total_pnl += pnl2
                if rsn2 != "STOP":
                    cat = "B_LEG2_WIN" if rsn2 == "TARGET" else "B_LEG2_TIMEOUT"
                    E_pnl[((s1, s2, s3), t)][orig] = total_pnl
                    E_cat[((s1, s2, s3), t)][orig] = cat
                    continue
                # Leg 3 — only if t3 exists and fill is AFTER leg2 exit
                if t3 is None or t3["fill_ts_ns"] <= int(ts_arr[exit_i2]):
                    cat = "D_LEG2_STOP_NO_LEG3"
                    E_pnl[((s1, s2, s3), t)][orig] = total_pnl
                    E_cat[((s1, s2, s3), t)][orig] = cat
                    continue
                start3 = int(np.searchsorted(ts_arr, t3["fill_ts_ns"], side="left"))
                eow3 = _end_of_week_ns(t3["fill_ts_ns"])
                horizon3 = min(t3["fill_ts_ns"] + HORIZON_NS, eow3)
                end3 = int(np.searchsorted(ts_arr, horizon3, side="right"))
                pnl3, rsn3, _ = _sim_leg(
                    ts_arr, exit_side, start3, end3,
                    t3["fill_price_decimal"], is_buy, s3, t,
                )
                total_pnl += pnl3
                if pnl3 > 0:
                    cat = "C_LEG3_WIN"
                elif pnl3 < 0:
                    cat = "C_LEG3_LOSS"
                else:
                    cat = "C_LEG3_FLAT"
                E_pnl[((s1, s2, s3), t)][orig] = total_pnl
                E_cat[((s1, s2, s3), t)][orig] = cat

        del ts_arr, bid_arr, ask_arr
        import gc; gc.collect()

    def _stats(x: np.ndarray) -> dict:
        x = np.asarray(x, dtype=np.float64)
        taken = x[x != 0.0]
        winners = x[x > 0]; losers = x[x < 0]
        gw = float(winners.sum()); gl = float(abs(losers.sum()))
        return {
            "opportunities": int(len(x)),
            "trades_taken": int(len(taken)),
            "winners": int((x > 0).sum()),
            "losers": int((x < 0).sum()),
            "net_pips": round(float(x.sum()), 1),
            "expectancy_per_opp_pips": round(float(x.mean()) if len(x) else 0.0, 3),
            "profit_factor": round(gw / gl, 3) if gl > 0 else None,
        }

    cutoff_ns = int(pd.Timestamp("2026-01-01", tz="UTC").value)
    dev_mask = (opps["fill_ts_ns"].values < cutoff_ns)
    uns_mask = ~dev_mask

    report = {
        "n_dev": int(dev_mask.sum()),
        "n_unseen": int(uns_mask.sum()),
        "D": {}, "E": {},
    }
    for (s, t), arr in D_pnl.items():
        row = {"ALL": _stats(arr),
               "DEV": _stats(arr[dev_mask]),
               "UNSEEN": _stats(arr[uns_mask])}
        cats = pd.Series(D_rsn[(s, t)]).value_counts().to_dict()
        row["categories"] = cats
        report["D"][f"s{s}_t{t}"] = row
    for ((s1, s2, s3), t), arr in E_pnl.items():
        row = {"ALL": _stats(arr),
               "DEV": _stats(arr[dev_mask]),
               "UNSEEN": _stats(arr[uns_mask])}
        cats = pd.Series(E_cat[((s1, s2, s3), t)]).value_counts().to_dict()
        row["categories"] = cats
        report["E"][f"s{s1}_{s2}_{s3}_t{t}"] = row

    # Save per-opp trade ledger
    out = opps[["c3_ts", "direction", "fill_ts_ns"]].copy()
    for (s, t), arr in D_pnl.items():
        out[f"D_s{s}_t{t}_pnl"] = arr
    for ((s1, s2, s3), t), arr in E_pnl.items():
        out[f"E_s{s1}_{s2}_{s3}_t{t}_pnl"] = arr
    out.to_parquet(DATA / "amendment2_de_trades.parquet", index=False)
    (DATA / "amendment2_summary.json").write_text(
        json.dumps(report, indent=2, default=str)
    )

    print("\n=== Strategy D (3rd test only) ===")
    for s in STOPS_D:
        for t in TARGETS:
            k = f"s{s}_t{t}"
            row = report["D"][k]
            print(f"  {k}: n_taken={row['ALL']['trades_taken']} "
                  f"net={row['ALL']['net_pips']} expy={row['ALL']['expectancy_per_opp_pips']} "
                  f"PF={row['ALL']['profit_factor']} | "
                  f"DEV expy={row['DEV']['expectancy_per_opp_pips']}, "
                  f"UNSEEN expy={row['UNSEEN']['expectancy_per_opp_pips']}")

    print("\n=== Strategy E (up to 3 sequential confirmed entries) ===")
    for (s1, s2, s3) in STOP_COMBOS_E:
        for t in TARGETS:
            k = f"s{s1}_{s2}_{s3}_t{t}"
            row = report["E"][k]
            print(f"  {k}: net={row['ALL']['net_pips']} "
                  f"expy={row['ALL']['expectancy_per_opp_pips']} "
                  f"PF={row['ALL']['profit_factor']} | "
                  f"DEV expy={row['DEV']['expectancy_per_opp_pips']}, "
                  f"UNSEEN expy={row['UNSEEN']['expectancy_per_opp_pips']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
