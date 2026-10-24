#!/usr/bin/env python3
"""
Phase 1: Trend-day census for GBPUSD.

A trend day is defined as: ≥80 pips of one-directional travel within a UTC
trading day. "One-directional" is operationalised as the maximum of:
  - max(close) - min(close) where the min occurs before the max  (long trend)
  - max(close) - min(close) where the max occurs before the min  (short trend)

We also record:
  * The complete directional swing (anchor_low, anchor_time) → (peak, peak_time)
  * UK local session (BST-aware) in which the swing started / ended
  * Pips travelled before 07:00 UK vs after
  * Whether the trend-end was followed by consolidation (defined below)
  * Whether BB(20,2) hugging occurred for ≥ 30 min during the trend
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CANDLES_EXT = Path(
    "<research_snapshot_root>/research/gbpusd_intraday_feasibility/snapshot/candles_ext_v2/GBPUSD"
)
CANDLES_26 = Path(
    "<research_snapshot_root>/research/gbpusd_intraday_feasibility/snapshot/candles/GBPUSD"
)

TREND_PIPS_MIN = 80.0


def _uk_offset_hours(ts_utc: pd.Timestamp) -> int:
    """1 during British Summer Time (last Sun March → last Sun October), else 0."""
    year = ts_utc.year
    # last Sunday of March
    march = dt.date(year, 3, 31)
    while march.weekday() != 6:
        march = march - dt.timedelta(days=1)
    bst_start = pd.Timestamp(dt.datetime.combine(march, dt.time(1, 0)), tz="UTC")
    october = dt.date(year, 10, 31)
    while october.weekday() != 6:
        october = october - dt.timedelta(days=1)
    bst_end = pd.Timestamp(dt.datetime.combine(october, dt.time(1, 0)), tz="UTC")
    return 1 if (bst_start <= ts_utc < bst_end) else 0


def _load_day_file(path: Path, basis: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Failed to read {path}: {exc}", file=sys.stderr)
        return None
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["basis"] = basis
    return df


def _directional_swing(df: pd.DataFrame) -> dict:
    """Return the dominant directional swing within the day.

    Uses the drawdown-style scan to find:
      long_swing  = max over i<=j of (close[j] - min(close[:j+1]))  ending at j
      short_swing = max over i<=j of (max(close[:j+1]) - close[j])
    These correspond to the largest sustained up / down move within the day
    without being broken by a full retrace.
    """
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    ts = df["ts"].to_list()
    n = len(df)
    if n == 0:
        return {}

    # Long swing (low-to-high, low must precede high)
    running_low = low[0]
    running_low_idx = 0
    best_long = 0.0
    best_long_lo_idx = 0
    best_long_hi_idx = 0
    for j in range(n):
        if low[j] < running_low:
            running_low = low[j]
            running_low_idx = j
        up = high[j] - running_low
        if up > best_long:
            best_long = up
            best_long_lo_idx = running_low_idx
            best_long_hi_idx = j

    # Short swing (high-to-low, high must precede low)
    running_high = high[0]
    running_high_idx = 0
    best_short = 0.0
    best_short_hi_idx = 0
    best_short_lo_idx = 0
    for j in range(n):
        if high[j] > running_high:
            running_high = high[j]
            running_high_idx = j
        down = running_high - low[j]
        if down > best_short:
            best_short = down
            best_short_hi_idx = running_high_idx
            best_short_lo_idx = j

    if best_long >= best_short:
        direction = "LONG"
        start_idx = best_long_lo_idx
        end_idx = best_long_hi_idx
        pips = best_long
        anchor_price = low[start_idx]
        peak_price = high[end_idx]
    else:
        direction = "SHORT"
        start_idx = best_short_hi_idx
        end_idx = best_short_lo_idx
        pips = best_short
        anchor_price = high[start_idx]
        peak_price = low[end_idx]

    return {
        "direction": direction,
        "pips": pips,
        "anchor_time": ts[start_idx],
        "peak_time": ts[end_idx],
        "anchor_price": anchor_price,
        "peak_price": peak_price,
        "start_idx": start_idx,
        "end_idx": end_idx,
    }


def _uk_session(ts_utc: pd.Timestamp) -> str:
    """07:00 UK boundary helper. Returns one of: ASIA | PRE_LDN | LDN | NY | LATE."""
    off = _uk_offset_hours(ts_utc)
    local_hour = (ts_utc.hour + off) % 24
    if local_hour < 7:
        return "ASIA"
    if local_hour < 8:
        return "PRE_LDN"
    if local_hour < 13:
        return "LDN"
    if local_hour < 21:
        return "NY"
    return "LATE"


def _07_uk_in_utc(day_ts_utc: pd.Timestamp) -> pd.Timestamp:
    off = _uk_offset_hours(day_ts_utc)
    return pd.Timestamp(day_ts_utc.date(), tz="UTC") + pd.Timedelta(hours=7 - off)


def _bb_hug_minutes(df: pd.DataFrame, direction: str, s: int, e: int) -> int:
    """Count minutes within [s,e] where close is within 20% of band from directional BB(20,2)."""
    if e - s < 4:
        return 0
    close = df["close"].to_numpy(dtype=float)
    mid = pd.Series(close).rolling(20, min_periods=20).mean()
    std = pd.Series(close).rolling(20, min_periods=20).std(ddof=0)
    upper = mid + 2 * std
    lower = mid - 2 * std

    hug_bars = 0
    for i in range(s, e + 1):
        if np.isnan(mid.iloc[i]):
            continue
        band_width = upper.iloc[i] - lower.iloc[i]
        if band_width <= 0:
            continue
        if direction == "LONG":
            # distance below upper band relative to width
            frac = (upper.iloc[i] - close[i]) / band_width
        else:
            frac = (close[i] - lower.iloc[i]) / band_width
        if frac <= 0.20:  # within 20% of band
            hug_bars += 1
    return hug_bars * 5  # minutes (5-min bars)


def _consolidation_after(df: pd.DataFrame, end_idx: int, direction: str, pips: float) -> dict:
    """Did the trend end in consolidation?

    Within 24 bars (2 hours) after end_idx, check:
      * max adverse travel (reversal) in pips
      * if max adverse travel < 30% of the trend magnitude → consolidation=True.
    """
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    look_end = min(n - 1, end_idx + 24)
    if look_end <= end_idx:
        return {"consolidation": None, "post_reversal_pips": None, "post_look_bars": 0}

    peak_price = df["close"].iloc[end_idx]
    if direction == "LONG":
        post_low = low[end_idx + 1 : look_end + 1].min() if look_end > end_idx else peak_price
        reversal_pips = peak_price - post_low
    else:
        post_high = high[end_idx + 1 : look_end + 1].max() if look_end > end_idx else peak_price
        reversal_pips = post_high - peak_price

    threshold = 0.30 * pips
    cons = reversal_pips < threshold
    return {
        "consolidation": bool(cons),
        "post_reversal_pips": float(reversal_pips),
        "post_look_bars": int(look_end - end_idx),
    }


def _pips_before_07(df: pd.DataFrame, direction: str, start_idx: int, end_idx: int,
                     anchor_price: float) -> dict:
    """Movement already completed by 07:00 UK."""
    if len(df) == 0:
        return {"pips_before_07": 0.0, "pips_after_07": 0.0, "trend_started_before_07": False}
    day = df["ts"].iloc[0]
    uk07 = _07_uk_in_utc(day)
    pre_mask = df["ts"] <= uk07
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    anchor_ts = df["ts"].iloc[start_idx]
    trend_started_before_07 = anchor_ts < uk07

    pre_df = df[pre_mask]
    if pre_df.empty:
        return {"pips_before_07": 0.0, "pips_after_07": 0.0,
                "trend_started_before_07": bool(trend_started_before_07)}
    last_pre_idx = pre_df.index[-1]
    # Measure how much of the directional swing was done pre-07:00.
    if direction == "LONG":
        pre_peak = high[: last_pre_idx + 1].max()
        pips_before = max(0.0, pre_peak - anchor_price)
    else:
        pre_trough = low[: last_pre_idx + 1].min()
        pips_before = max(0.0, anchor_price - pre_trough)

    full_pips = abs(df["close"].iloc[end_idx] - anchor_price)  # rough; replaced below
    # True magnitude already comes from caller; just return pre.
    return {
        "pips_before_07": float(pips_before),
        "trend_started_before_07": bool(trend_started_before_07),
    }


def census_one(path: Path, basis: str) -> dict | None:
    df = _load_day_file(path, basis)
    if df is None or len(df) < 20:
        return None
    date = df["ts"].iloc[0].date()
    if date.weekday() >= 5:
        return None  # weekends excluded
    swing = _directional_swing(df)
    if not swing:
        return None

    is_trend = swing["pips"] >= TREND_PIPS_MIN

    pips_before = _pips_before_07(df, swing["direction"], swing["start_idx"], swing["end_idx"],
                                   swing["anchor_price"])
    hug_mins = _bb_hug_minutes(df, swing["direction"], swing["start_idx"], swing["end_idx"])
    cons = _consolidation_after(df, swing["end_idx"], swing["direction"], swing["pips"])

    day_high = float(df["high"].max())
    day_low = float(df["low"].min())
    day_range = day_high - day_low

    anchor_ts = swing["anchor_time"]
    peak_ts = swing["peak_time"]
    uk07 = _07_uk_in_utc(df["ts"].iloc[0])
    pips_after_07 = swing["pips"] - pips_before["pips_before_07"]

    return {
        "date": date.isoformat(),
        "weekday": date.strftime("%a"),
        "basis": basis,
        "trend_day": bool(is_trend),
        "direction": swing["direction"],
        "pips": round(swing["pips"], 2),
        "day_range_pips": round(day_range, 2),
        "anchor_time_utc": anchor_ts.isoformat(),
        "peak_time_utc": peak_ts.isoformat(),
        "anchor_session": _uk_session(anchor_ts),
        "peak_session": _uk_session(peak_ts),
        "anchor_price": round(swing["anchor_price"] / 10000, 5),
        "peak_price": round(swing["peak_price"] / 10000, 5),
        "pips_before_07_uk": round(pips_before["pips_before_07"], 2),
        "pips_after_07_uk": round(pips_after_07, 2),
        "trend_started_before_07": pips_before["trend_started_before_07"],
        "bb_hug_minutes": int(hug_mins),
        "consolidation": cons["consolidation"],
        "post_reversal_pips": None if cons["post_reversal_pips"] is None
                               else round(cons["post_reversal_pips"], 2),
        "post_look_bars": cons["post_look_bars"],
    }


def main(out_path: Path) -> None:
    rows: list[dict] = []
    for path in sorted(CANDLES_EXT.glob("*.csv")):
        r = census_one(path, "BID")
        if r:
            rows.append(r)
    for path in sorted(CANDLES_26.glob("*.csv")):
        r = census_one(path, "MID")
        if r:
            rows.append(r)
    if not rows:
        print("No data rows produced", file=sys.stderr)
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)
    df = pd.DataFrame(rows)
    print(f"Total weekdays analysed: {len(df)}")
    print(f"Trend days (≥{TREND_PIPS_MIN} pips directional): {df.trend_day.sum()}")
    print(f"Share: {df.trend_day.mean():.1%}")
    print("Direction breakdown:")
    print(df[df.trend_day].direction.value_counts())
    print("Avg pips (trend days):", df[df.trend_day].pips.mean().round(2))
    print("Session where swing started (trend days):")
    print(df[df.trend_day].anchor_session.value_counts())


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "<research_workspace>/outputs/census.csv"
    )
    main(out)
