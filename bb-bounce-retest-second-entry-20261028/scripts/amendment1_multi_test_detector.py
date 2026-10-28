"""Phase 7 AMENDMENT — multi-test sequence detector.

For every opportunity (= test 1), identify up to K=5 subsequent
*confirmed* tests of the same reversal area.  Each new test requires:

    (a) retest trigger: exit-side quote touches the C1 extreme
        within the max window (60 min from the previous confirmation);
    (b) completed 5-min confirmation candle (same rule as Stage 1);
    (c) between the previous test's confirmation close and the new
        retest trigger, price must have moved MIN_SEP_PIPS = 10 away
        from the level — prevents one continuous visit counting as
        multiple tests;
    (d) the trigger tick must be strictly after the previous test's
        confirmation close.

Writes `data/amendment1_test_sequences.parquet` with one row per
opportunity carrying all identified test fills.

Also records, for each opportunity, the MFE achieved AFTER each test
number so we can measure the operator's "3rd test = big move"
hypothesis without look-ahead at entry time.
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

MAX_K = 5
MAX_SEQUENCE_WINDOW_NS = 8 * 60 * 60 * 1_000_000_000  # 8 h total window — captures same-session multi-tests without excessive memory
PER_TEST_WINDOW_NS = 60 * 60 * 1_000_000_000  # 60 min between consecutive tests
MIN_SEP_PIPS = 10.0  # price must move at least 10 p away from the level between tests
BAR_NS = 5 * 60 * 1_000_000_000
EXECUTION_GAP_NS = 60 * 1_000_000_000
DEC_PIP = 0.0001
MIN_SEP_DEC = MIN_SEP_PIPS * DEC_PIP


def _year_candles(ticks: pd.DataFrame) -> pd.DataFrame:
    bar_id = (ticks["ts_utc_ns"].values // BAR_NS).astype(np.int64)
    mid = (ticks["bid"].astype(np.float64) + ticks["ask"].astype(np.float64)) / 2.0
    mid_pts = (mid * 10000.0).round(2)
    tmp = pd.DataFrame({"bar_id": bar_id, "mid_pts": mid_pts.values})
    agg = tmp.groupby("bar_id", sort=True)["mid_pts"].agg(["first", "max", "min", "last"])
    agg.columns = ["open", "high", "low", "close"]
    agg = agg.round(2).reset_index()
    agg["bar_open_ns"] = agg["bar_id"] * BAR_NS
    return agg


def _find_test_after(
    ts_arr, bid_arr, ask_arr,
    bar_ids, bar_open, bar_high, bar_low, bar_close, bar_opn,
    start_ns: int, level_pts: float, direction: str,
    c1_low_dec: float, c1_high_dec: float,
    max_end_ns: int,
) -> dict | None:
    """Find the next confirmed test strictly after start_ns.

    * Retest trigger: BUY → bid <= C1 low; SELL → ask >= C1 high.
    * Separation check is done by caller.
    * Confirmation: as per Stage 1 rules.
    * Returns None if no confirmed test within max_end_ns.
    """
    sidx = int(np.searchsorted(ts_arr, start_ns, side="right"))
    eidx = int(np.searchsorted(ts_arr, max_end_ns, side="right"))
    if sidx >= eidx:
        return None
    seg_bid = bid_arr[sidx:eidx]
    seg_ask = ask_arr[sidx:eidx]
    if direction == "BUY":
        hits = np.where(seg_bid <= c1_low_dec)[0]
    else:
        hits = np.where(seg_ask >= c1_high_dec)[0]
    if len(hits) == 0:
        return None
    trig_rel = int(hits[0])
    trig_abs = sidx + trig_rel
    trig_ts = int(ts_arr[trig_abs])
    trig_bid = float(bid_arr[trig_abs])
    trig_ask = float(ask_arr[trig_abs])

    # Find confirmation candle
    bar_id_at_trig = trig_ts // BAR_NS
    cand_mask = (bar_ids > bar_id_at_trig) & ((bar_open + BAR_NS) <= max_end_ns)
    cand_idx = np.where(cand_mask)[0]
    confirm_bar_pos = None
    for i in cand_idx:
        hi = bar_high[i]; lo = bar_low[i]
        op = bar_opn[i]; cl = bar_close[i]
        if direction == "BUY":
            if cl > op and lo <= level_pts and (cl / 10000.0) > trig_bid:
                confirm_bar_pos = int(i); break
        else:
            if cl < op and hi >= level_pts and (cl / 10000.0) < trig_ask:
                confirm_bar_pos = int(i); break
    if confirm_bar_pos is None:
        return None
    confirm_close_ns = int(bar_open[confirm_bar_pos]) + BAR_NS
    fill_rel = int(np.searchsorted(ts_arr, confirm_close_ns, side="right"))
    if fill_rel >= len(ts_arr):
        return None
    if int(ts_arr[fill_rel]) - confirm_close_ns > EXECUTION_GAP_NS:
        return None
    fb = float(bid_arr[fill_rel]); fa = float(ask_arr[fill_rel])
    fill_price = fa if direction == "BUY" else fb
    return {
        "trigger_ts_ns": trig_ts,
        "trigger_bid": trig_bid,
        "trigger_ask": trig_ask,
        "confirm_bar_open_ns": int(bar_open[confirm_bar_pos]),
        "confirm_close_ns": confirm_close_ns,
        "confirm_high_pts": float(bar_high[confirm_bar_pos]),
        "confirm_low_pts": float(bar_low[confirm_bar_pos]),
        "confirm_close_pts": float(bar_close[confirm_bar_pos]),
        "fill_ts_ns": int(ts_arr[fill_rel]),
        "fill_price_decimal": fill_price,
        "spread_pips": round((fa - fb) * 10000.0, 2),
    }


def _separation_satisfied(
    ts_arr, bid_arr, ask_arr,
    prev_confirm_close_ns: int, level_dec: float, direction: str,
) -> bool | int:
    """Return the ts_ns at which price has moved MIN_SEP_PIPS away from
    level on the executable exit side. Returns False if not satisfied
    within MAX_SEQUENCE_WINDOW_NS."""
    sidx = int(np.searchsorted(ts_arr, prev_confirm_close_ns, side="left"))
    eidx = int(np.searchsorted(ts_arr, prev_confirm_close_ns + MAX_SEQUENCE_WINDOW_NS, side="right"))
    if sidx >= eidx:
        return False
    if direction == "BUY":
        # Price must move UP from level: bid >= level_dec + MIN_SEP
        thresh = level_dec + MIN_SEP_DEC
        hits = np.where(bid_arr[sidx:eidx] >= thresh)[0]
    else:
        thresh = level_dec - MIN_SEP_DEC
        hits = np.where(ask_arr[sidx:eidx] <= thresh)[0]
    if len(hits) == 0:
        return False
    return int(ts_arr[sidx + int(hits[0])])


def _mfe_after(
    ts_arr, bid_arr, ask_arr,
    start_ns: int, entry_dec: float, direction: str,
    horizon_end_ns: int,
) -> dict:
    """Return MFE / MAE and time-to-+N pips, from start_ns to horizon_end_ns."""
    sidx = int(np.searchsorted(ts_arr, start_ns, side="left"))
    eidx = int(np.searchsorted(ts_arr, horizon_end_ns, side="right"))
    if sidx >= eidx:
        return {"mfe": 0.0, "mae": 0.0}
    if direction == "BUY":
        seg = bid_arr[sidx:eidx]
        fav = (seg - entry_dec) / DEC_PIP
        adv = (entry_dec - seg) / DEC_PIP
    else:
        seg = ask_arr[sidx:eidx]
        fav = (entry_dec - seg) / DEC_PIP
        adv = (seg - entry_dec) / DEC_PIP
    def _t_to(th):
        h = np.where(fav >= th)[0]
        if len(h) == 0:
            return None
        return (int(ts_arr[sidx + int(h[0])]) - start_ns) / 1e9
    return {
        "mfe": float(fav.max()),
        "mae_clip_40": float(adv[:(np.where(fav >= 40.0)[0][0] if (fav >= 40.0).any() else len(fav))].max()),
        "t5": _t_to(5), "t10": _t_to(10), "t20": _t_to(20), "t40": _t_to(40), "t60": _t_to(60),
    }


def main() -> int:
    opps = pd.read_parquet(DATA / "opportunities.parquet")
    opps["fill_year"] = pd.to_datetime(opps["fill_ts_ns"], unit="ns", utc=True).dt.year
    print(f"opportunities: {len(opps):,}", flush=True)

    rows_out = []
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
        # Build candles from the loaded ticks BEFORE releasing them.
        candles = _year_candles(ticks)
        del ticks
        import gc; gc.collect()
        bar_ids = candles["bar_id"].values.astype(np.int64)
        bar_open = candles["bar_open_ns"].values.astype(np.int64)
        bar_high = candles["high"].values.astype(np.float32)
        bar_low = candles["low"].values.astype(np.float32)
        bar_close = candles["close"].values.astype(np.float32)
        bar_opn = candles["open"].values.astype(np.float32)

        for _, r in sub.iterrows():
            direction = r["direction"]
            fill_ns_1 = int(r["fill_ts_ns"])
            c1_low_dec = float(r["c1_low"]) / 10000.0
            c1_high_dec = float(r["c1_high"]) / 10000.0
            level_pts = r["c1_low"] if direction == "BUY" else r["c1_high"]
            level_dec = c1_low_dec if direction == "BUY" else c1_high_dec

            # Sequence outcome
            tests = [{
                "test_num": 1,
                "trigger_ts_ns": fill_ns_1,  # test 1's "trigger" is the original fire
                "confirm_close_ns": fill_ns_1,
                "fill_ts_ns": fill_ns_1,
                "fill_price_decimal": float(r["fill_price_decimal"]),
                "spread_pips": float(r["spread_pips"]),
            }]
            opp_window_end = fill_ns_1 + MAX_SEQUENCE_WINDOW_NS

            prev_confirm_close_ns = fill_ns_1
            for k in range(2, MAX_K + 1):
                # Separation gate
                sep_ts = _separation_satisfied(
                    ts_arr, bid_arr, ask_arr,
                    prev_confirm_close_ns, level_dec, direction,
                )
                if sep_ts is False:
                    break
                # Find next test strictly after separation
                nxt = _find_test_after(
                    ts_arr, bid_arr, ask_arr,
                    bar_ids, bar_open, bar_high, bar_low, bar_close, bar_opn,
                    start_ns=sep_ts, level_pts=float(level_pts), direction=direction,
                    c1_low_dec=c1_low_dec, c1_high_dec=c1_high_dec,
                    max_end_ns=min(prev_confirm_close_ns + PER_TEST_WINDOW_NS, opp_window_end),
                )
                if nxt is None:
                    break
                nxt["test_num"] = k
                tests.append(nxt)
                prev_confirm_close_ns = nxt["confirm_close_ns"]

            # Compute MFE / MAE after each test fill
            per_test_metrics = []
            for t in tests:
                m = _mfe_after(ts_arr, bid_arr, ask_arr,
                               int(t["fill_ts_ns"]), float(t["fill_price_decimal"]),
                               direction, opp_window_end)
                per_test_metrics.append({"test_num": t["test_num"], **m})

            rows_out.append({
                "c3_ts": r["c3_ts"],
                "direction": direction,
                "fill_ts_ns": fill_ns_1,
                "c1_low": float(r["c1_low"]),
                "c1_high": float(r["c1_high"]),
                "n_tests": len(tests),
                "tests": tests,
                "metrics": per_test_metrics,
            })
        del ts_arr, bid_arr, ask_arr, candles
        import gc; gc.collect()

    # Flatten
    flat_rows = []
    for row in rows_out:
        for t, m in zip(row["tests"], row["metrics"]):
            flat_rows.append({
                "c3_ts": row["c3_ts"],
                "direction": row["direction"],
                "opp_fill_ts_ns": row["fill_ts_ns"],
                "test_num": t["test_num"],
                "test_fill_ts_ns": t["fill_ts_ns"],
                "test_fill_price_decimal": t["fill_price_decimal"],
                "test_spread_pips": t.get("spread_pips"),
                "test_trigger_ts_ns": t.get("trigger_ts_ns"),
                "test_mfe_after": m["mfe"],
                "test_mae_clip_40": m.get("mae_clip_40"),
                "test_t_to_20": m["t20"],
                "test_t_to_40": m["t40"],
                "test_t_to_60": m["t60"],
            })
    df = pd.DataFrame(flat_rows)
    df.to_parquet(DATA / "amendment1_test_sequences.parquet", index=False)

    # Summary stats
    opp_df = pd.DataFrame([
        {
            "c3_ts": row["c3_ts"],
            "direction": row["direction"],
            "n_tests": row["n_tests"],
        }
        for row in rows_out
    ])
    summary = {
        "n_opportunities": int(len(opp_df)),
        "n_test_rows_total": int(len(df)),
        "n_tests_distribution": opp_df["n_tests"].value_counts().sort_index().to_dict(),
    }

    # Reversal probability by test number
    rev_prob = {}
    for k in range(1, MAX_K + 1):
        sub = df[df["test_num"] == k]
        if len(sub) == 0:
            rev_prob[f"test{k}"] = {"n": 0}
            continue
        rev_prob[f"test{k}"] = {
            "n": int(len(sub)),
            "pct_reach_20p": round(100.0 * (sub["test_mfe_after"] >= 20.0).mean(), 2),
            "pct_reach_30p": round(100.0 * (sub["test_mfe_after"] >= 30.0).mean(), 2),
            "pct_reach_40p": round(100.0 * (sub["test_mfe_after"] >= 40.0).mean(), 2),
            "pct_reach_50p": round(100.0 * (sub["test_mfe_after"] >= 50.0).mean(), 2),
            "pct_reach_60p": round(100.0 * (sub["test_mfe_after"] >= 60.0).mean(), 2),
            "mae_clip_40_median_p": round(float(sub["test_mae_clip_40"].median()), 2),
            "mae_clip_40_p90": round(float(sub["test_mae_clip_40"].quantile(0.9)), 2),
        }
    summary["reversal_probability_by_test"] = rev_prob

    # BUY / SELL split for the big question
    for d in ["BUY", "SELL"]:
        sub = df[df["direction"] == d]
        for k in range(1, MAX_K + 1):
            s = sub[sub["test_num"] == k]
            if len(s) == 0:
                continue
            summary.setdefault("by_direction", {}).setdefault(d, {})[f"test{k}"] = {
                "n": int(len(s)),
                "pct_reach_40p": round(100.0 * (s["test_mfe_after"] >= 40.0).mean(), 2),
                "pct_reach_60p": round(100.0 * (s["test_mfe_after"] >= 60.0).mean(), 2),
            }

    (DATA / "amendment1_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
