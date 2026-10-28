"""Phase 7 Stage 1 — detect retest trigger + confirmation candle.

For every Phase 6 opportunity:

  1. Scan ticks starting at (fill_ts_ns + 1) through
     (fill_ts_ns + MAX_RETEST_WINDOW_NS).
  2. Find RETEST TRIGGER = first tick whose exit-side quote touches
     the C1 extreme:
         BUY  : bid <= C1 low
         SELL : ask >= C1 high
  3. From the retest trigger onward, scan completed 5-min MID candles
     (reconstructed from the same tick parquet) up to the window end.
  4. Find CONFIRMATION CANDLE = first candle meeting:
         BUY  : green AND low <= C1_low AND close > trigger_bid
         SELL : red   AND high >= C1_high AND close < trigger_ask
     (All metrics on points-scale MID candles, same convention as the
     deployed strategy.)
  5. SECOND-ENTRY FILL = first tick strictly after confirmation
     candle's close_time (bar_open + 5 min).  BUY = ASK, SELL = BID.
     If no tick within 60 s → EXECUTION_GAP.

Writes `data/stage1_retest_events.parquet`.

NO look-ahead: everything uses data strictly before or at the current
tick.  Window end is pre-registered (60 min max per PROGRESS.md 1.6).
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

MAX_RETEST_WINDOW_NS = 60 * 60 * 1_000_000_000  # 60 min — the longest window on the pre-registered grid
BAR_NS = 5 * 60 * 1_000_000_000
EXECUTION_GAP_NS = 60 * 1_000_000_000
DEC_PIP = 0.0001


def _year_candles(ticks: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct 5-min MID candles (points-scale, 2 dp)."""
    bar_id = (ticks["ts_utc_ns"].values // BAR_NS).astype(np.int64)
    mid = (ticks["bid"].astype(np.float64) + ticks["ask"].astype(np.float64)) / 2.0
    mid_pts = (mid * 10000.0).round(2)
    tmp = pd.DataFrame({"bar_id": bar_id, "mid_pts": mid_pts.values})
    agg = tmp.groupby("bar_id", sort=True)["mid_pts"].agg(
        ["first", "max", "min", "last"]
    )
    agg.columns = ["open", "high", "low", "close"]
    agg = agg.round(2).reset_index()
    agg["bar_open_ns"] = agg["bar_id"] * BAR_NS
    return agg


def _detect_for_opportunity(
    opp,
    ts_arr: np.ndarray, bid_arr: np.ndarray, ask_arr: np.ndarray,
    bar_ids: np.ndarray, bar_open: np.ndarray, bar_high_pts: np.ndarray,
    bar_low_pts: np.ndarray, bar_close_pts: np.ndarray, bar_opn_pts: np.ndarray,
) -> dict:
    """Return retest + confirmation metadata for one opportunity."""
    fill_ns = int(opp["fill_ts_ns"])
    direction = opp["direction"]
    c1_low_dec = float(opp["c1_low"]) / 10000.0
    c1_high_dec = float(opp["c1_high"]) / 10000.0

    window_end_ns = fill_ns + MAX_RETEST_WINDOW_NS
    start_idx = int(np.searchsorted(ts_arr, fill_ns + 1, side="left"))
    end_idx = int(np.searchsorted(ts_arr, window_end_ns, side="right"))
    if end_idx > len(ts_arr):
        end_idx = len(ts_arr)
    if start_idx >= end_idx:
        return _nores("NO_TICKS_IN_WINDOW")

    # 1. Retest trigger
    seg_bid = bid_arr[start_idx:end_idx]
    seg_ask = ask_arr[start_idx:end_idx]
    if direction == "BUY":
        hits = np.where(seg_bid <= c1_low_dec)[0]
    else:
        hits = np.where(seg_ask >= c1_high_dec)[0]
    if len(hits) == 0:
        return _nores("NO_RETEST")
    trig_rel = int(hits[0])
    trig_abs = start_idx + trig_rel
    trig_ts = int(ts_arr[trig_abs])
    trig_bid = float(bid_arr[trig_abs])
    trig_ask = float(ask_arr[trig_abs])
    retest_delay_s = (trig_ts - fill_ns) / 1e9

    # 2. Confirmation candle — scan completed 5m bars starting at the
    #    bar that CONTAINS trig_ts (we require that bar's close has
    #    occurred, so the first candidate is the bar whose bar_open is
    #    >= trig_ts).  We only inspect bars whose close_time (bar_open
    #    + 5 min) is <= window_end_ns.
    bar_id_at_trig = trig_ts // BAR_NS
    # First bar to check: next bar after the one containing trig (so
    # the whole bar's life is after the trigger — needed for the
    # "bar interacted with retest zone during life" check only if we
    # use the trigger bar; we take the next complete bar to be
    # conservative, i.e. we don't allow the bar that WAS the trigger
    # to also be its own confirmation).
    # Candidate bars have bar_id > bar_id_at_trig AND close_time <= window_end_ns.
    cand_mask = (bar_ids > bar_id_at_trig) & \
                ((bar_open + BAR_NS) <= window_end_ns)
    cand_idx = np.where(cand_mask)[0]
    if len(cand_idx) == 0:
        return _nores("NO_CONFIRM_CANDLES_IN_WINDOW")

    confirm_bar_pos = None
    for i in cand_idx:
        hi = bar_high_pts[i]; lo = bar_low_pts[i]
        op = bar_opn_pts[i]; cl = bar_close_pts[i]
        if direction == "BUY":
            green = cl > op
            touched = lo <= opp["c1_low"]  # points scale
            above = (cl / 10000.0) > trig_bid
            if green and touched and above:
                confirm_bar_pos = int(i)
                break
        else:
            red = cl < op
            touched = hi >= opp["c1_high"]
            below = (cl / 10000.0) < trig_ask
            if red and touched and below:
                confirm_bar_pos = int(i)
                break

    if confirm_bar_pos is None:
        return _nores("NO_CONFIRM")

    confirm_close_ns = int(bar_open[confirm_bar_pos]) + BAR_NS

    # 3. Second entry fill — first tick strictly after confirm_close_ns
    fill_rel = int(np.searchsorted(ts_arr, confirm_close_ns, side="right"))
    if fill_rel >= len(ts_arr):
        return _nores("CONFIRM_FILL_PAST_TICK_WINDOW")
    if int(ts_arr[fill_rel]) - confirm_close_ns > EXECUTION_GAP_NS:
        return _nores("EXECUTION_GAP")
    fb = float(bid_arr[fill_rel]); fa = float(ask_arr[fill_rel])
    second_entry = fa if direction == "BUY" else fb
    spread_pips = round((fa - fb) * 10000.0, 2)

    confirm_delay_s = (confirm_close_ns - fill_ns) / 1e9
    second_fill_delay_s = (int(ts_arr[fill_rel]) - fill_ns) / 1e9

    return {
        "retest_trigger_ts_ns": trig_ts,
        "retest_trigger_bid": trig_bid,
        "retest_trigger_ask": trig_ask,
        "retest_delay_s": retest_delay_s,
        "confirm_bar_open_ns": int(bar_open[confirm_bar_pos]),
        "confirm_bar_high_pts": float(bar_high_pts[confirm_bar_pos]),
        "confirm_bar_low_pts": float(bar_low_pts[confirm_bar_pos]),
        "confirm_bar_close_pts": float(bar_close_pts[confirm_bar_pos]),
        "confirm_close_ns": confirm_close_ns,
        "second_fill_ts_ns": int(ts_arr[fill_rel]),
        "second_fill_price_decimal": second_entry,
        "second_fill_price_points": round(second_entry * 10000.0, 2),
        "second_fill_bid": fb,
        "second_fill_ask": fa,
        "second_spread_pips": spread_pips,
        "second_fill_delay_s": second_fill_delay_s,
        "confirm_delay_s": confirm_delay_s,
        "outcome": "VALID",
    }


def _nores(code: str) -> dict:
    return {
        "retest_trigger_ts_ns": None,
        "retest_trigger_bid": None,
        "retest_trigger_ask": None,
        "retest_delay_s": None,
        "confirm_bar_open_ns": None,
        "confirm_bar_high_pts": None,
        "confirm_bar_low_pts": None,
        "confirm_bar_close_pts": None,
        "confirm_close_ns": None,
        "second_fill_ts_ns": None,
        "second_fill_price_decimal": None,
        "second_fill_price_points": None,
        "second_fill_bid": None,
        "second_fill_ask": None,
        "second_spread_pips": None,
        "second_fill_delay_s": None,
        "confirm_delay_s": None,
        "outcome": code,
    }


def main() -> int:
    opps = pd.read_parquet(DATA / "opportunities.parquet")
    opps["fill_year"] = pd.to_datetime(opps["fill_ts_ns"], unit="ns",
                                        utc=True).dt.year
    print(f"opportunities: {len(opps):,}", flush=True)

    out_rows = []
    for year in sorted(opps["fill_year"].unique()):
        print(f"  year {year} ...", flush=True)
        sub = opps[opps["fill_year"] == year].sort_values("fill_ts_ns")
        tp = TICK_DIR / f"{year}.parquet"
        if not tp.exists():
            continue
        ticks = pd.read_parquet(tp, columns=["ts_utc_ns", "bid", "ask"])
        # Need next-year ticks if last window spills
        last_window_end = int(sub["fill_ts_ns"].max()) + MAX_RETEST_WINDOW_NS
        np_path = TICK_DIR / f"{year + 1}.parquet"
        if last_window_end > int(ticks["ts_utc_ns"].iloc[-1]) and np_path.exists():
            tn = pd.read_parquet(np_path, columns=["ts_utc_ns", "bid", "ask"])
            ticks = pd.concat([ticks, tn], ignore_index=True)
            del tn
        ts_arr = ticks["ts_utc_ns"].values.astype(np.int64)
        bid_arr = ticks["bid"].values.astype(np.float32)
        ask_arr = ticks["ask"].values.astype(np.float32)

        candles = _year_candles(ticks)
        bar_ids = candles["bar_id"].values.astype(np.int64)
        bar_open = candles["bar_open_ns"].values.astype(np.int64)
        bar_high = candles["high"].values.astype(np.float32)
        bar_low = candles["low"].values.astype(np.float32)
        bar_close = candles["close"].values.astype(np.float32)
        bar_opn = candles["open"].values.astype(np.float32)

        for _, r in sub.iterrows():
            info = _detect_for_opportunity(
                r, ts_arr, bid_arr, ask_arr,
                bar_ids, bar_open, bar_high, bar_low, bar_close, bar_opn,
            )
            info["c3_ts"] = r["c3_ts"]
            info["direction"] = r["direction"]
            info["fill_ts_ns"] = int(r["fill_ts_ns"])
            info["fill_price_decimal"] = float(r["fill_price_decimal"])
            info["c1_low"] = float(r["c1_low"])
            info["c1_high"] = float(r["c1_high"])
            info["spread_pips"] = float(r["spread_pips"])
            out_rows.append(info)
        del ticks, ts_arr, bid_arr, ask_arr, candles, bar_ids, bar_open
        import gc; gc.collect()

    df = pd.DataFrame(out_rows)
    df.to_parquet(DATA / "stage1_retest_events.parquet", index=False)

    from collections import Counter
    cnt = Counter(df["outcome"])
    summary = {
        "n_opportunities": int(len(df)),
        "outcome_counts": dict(cnt),
        "pct_valid": round(100.0 * (df["outcome"] == "VALID").mean(), 2),
        "pct_no_retest": round(100.0 * (df["outcome"] == "NO_RETEST").mean(), 2),
        "pct_no_confirm": round(100.0 * (df["outcome"] == "NO_CONFIRM").mean(), 2),
    }
    valid = df[df["outcome"] == "VALID"]
    if len(valid):
        summary["retest_delay_s_median"] = float(valid["retest_delay_s"].median())
        summary["retest_delay_s_p90"] = float(valid["retest_delay_s"].quantile(0.9))
        summary["confirm_delay_s_median"] = float(valid["confirm_delay_s"].median())
        summary["confirm_delay_s_p90"] = float(valid["confirm_delay_s"].quantile(0.9))
    (DATA / "stage1_retest_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
