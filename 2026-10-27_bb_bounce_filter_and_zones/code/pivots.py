"""
Classic floor-pivot calculation (matches
qm_liquidity_level_mapper.py:173-186 _pivots_from_prior formula):

  P  = (prev_high + prev_low + prev_close) / 3
  R1 = 2P - prev_low
  S1 = 2P - prev_high
  R2 = P + (prev_high - prev_low)
  S2 = P - (prev_high - prev_low)
  R3 = prev_high + 2 * (P - prev_low)
  S3 = prev_low - 2 * (prev_high - P)

Session boundary: UTC day. The pivot set for date D is calculated from
day D-1's HLC. This is the convention used by qm_liquidity_level_mapper and
is what the audit confirms as the production source.
"""

from __future__ import annotations

import pandas as pd


def daily_hlc(m5: pd.DataFrame) -> pd.DataFrame:
    df = m5.copy()
    df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.date
    g = df.groupby("date").agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
    return g.reset_index()


def pivots_for_each_day(hlc: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with one row per date: date, PP, R1-R3, S1-S3, computed from prior day's HLC."""
    out = hlc.copy().sort_values("date").reset_index(drop=True)
    out["prev_h"] = out["h"].shift(1)
    out["prev_l"] = out["l"].shift(1)
    out["prev_c"] = out["c"].shift(1)
    out["PP"] = (out["prev_h"] + out["prev_l"] + out["prev_c"]) / 3.0
    out["R1"] = 2 * out["PP"] - out["prev_l"]
    out["S1"] = 2 * out["PP"] - out["prev_h"]
    out["R2"] = out["PP"] + (out["prev_h"] - out["prev_l"])
    out["S2"] = out["PP"] - (out["prev_h"] - out["prev_l"])
    out["R3"] = out["prev_h"] + 2 * (out["PP"] - out["prev_l"])
    out["S3"] = out["prev_l"] - 2 * (out["prev_h"] - out["PP"])
    return out[["date", "PP", "S1", "S2", "S3", "R1", "R2", "R3"]].dropna().reset_index(drop=True)


def attach_pivots(signals: pd.DataFrame, pivots: pd.DataFrame) -> pd.DataFrame:
    """Join each signal to the pivot set valid on its fire date."""
    out = signals.copy()
    out["fire_date"] = pd.to_datetime(out["fire_time"], utc=True).dt.date
    joined = out.merge(pivots, left_on="fire_date", right_on="date", how="left")
    return joined
