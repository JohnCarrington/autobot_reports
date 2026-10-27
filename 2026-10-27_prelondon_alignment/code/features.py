"""
Point-in-time feature extraction at UK hourly snapshots.

For every (date, uk_hour) we compute:
  - spot            = last completed M5 close strictly before the snapshot time
  - h4_dir, h4_str  = classify_ema_direction on last COMPLETED H4 bar
  - h1_dir, h1_str  = classify_ema_direction on last COMPLETED H1 bar
  - m5_dir, m5_str  = MACD-hist classification on last COMPLETED M5 bar
  - alignment       = alignment_state(h4, h1, m5)
  - asian_hi, asian_lo = Asian-session H/L for the UTC day of the snapshot,
                        measured from Asian window (22-07 UTC spans two UTC
                        dates; use the window ending with today's 07 UTC)
  - prev_day_h/l/c  = prior UTC day's H/L/C
  - prev_day_net    = prior day's close - open
  - atr20_daily     = mean of (H-L) over the trailing 20 completed UTC days
  - prev_session_net= prior day's net close (same as prev_day_net; retained
                      for clarity)

UK clock conversion: BST runs from the last Sunday of March 01:00 UTC until
the last Sunday of October 01:00 UTC. Converted via a deterministic helper;
the archive timestamps are UTC so the conversion only matters for the
snapshot clock labels (06:00 UK, 07:00 UK, etc.).
"""

from __future__ import annotations

from datetime import date, timedelta, time
from typing import Iterator

import numpy as np
import pandas as pd

from data_loader import load_m5, resample_ohlc
from direction import (
    classify_ema_direction, classify_macd_m5, alignment_state,
)

UK_HOURS = [5, 6, 7, 8, 10, 12, 13, 14]


def is_bst(d: date) -> bool:
    y = d.year
    march_last = date(y, 3, 31)
    while march_last.weekday() != 6: march_last -= timedelta(days=1)
    oct_last = date(y, 10, 31)
    while oct_last.weekday() != 6: oct_last -= timedelta(days=1)
    return march_last <= d < oct_last


def uk_to_utc(d: date, uk_hour: int) -> pd.Timestamp:
    """Return the UTC timestamp for `uk_hour:00` on date `d` in Europe/London."""
    offset = 1 if is_bst(d) else 0
    hour_utc = uk_hour - offset
    if hour_utc < 0:
        return pd.Timestamp(f"{(d - timedelta(days=1)).isoformat()} {24+hour_utc:02d}:00", tz="UTC")
    if hour_utc >= 24:
        return pd.Timestamp(f"{(d + timedelta(days=1)).isoformat()} {hour_utc-24:02d}:00", tz="UTC")
    return pd.Timestamp(f"{d.isoformat()} {hour_utc:02d}:00", tz="UTC")


def _bar_before(ts_arr: np.ndarray, as_of: np.datetime64) -> int:
    """Index of the last timestamp strictly < as_of. -1 if none."""
    idx = int(np.searchsorted(ts_arr, as_of, side="left")) - 1
    return idx


def _asian_hl(m5: pd.DataFrame, as_of_utc: pd.Timestamp) -> tuple[float | None, float | None]:
    """Asian session HL ending at the as_of_utc timestamp.

    Approximation: the window [22:00 UTC yesterday .. 07:00 UTC today].
    If `as_of_utc` is before 07:00 UTC, use the window ending now; cap at
    `as_of_utc` to avoid future information.
    """
    today = as_of_utc.date()
    start = pd.Timestamp(f"{(today - timedelta(days=1)).isoformat()} 22:00", tz="UTC")
    end = min(as_of_utc, pd.Timestamp(f"{today.isoformat()} 07:00", tz="UTC"))
    if end <= start: return None, None
    ts = m5["timestamp"].values.astype("datetime64[ns]")
    i0 = int(np.searchsorted(ts, start.to_datetime64()))
    i1 = int(np.searchsorted(ts, end.to_datetime64()))
    if i1 <= i0: return None, None
    sub = m5.iloc[i0:i1]
    if len(sub) == 0: return None, None
    return float(sub["high"].max()), float(sub["low"].min())


def _prev_day_hlc(hlc_cache: dict, d: date) -> tuple[float, float, float, float] | None:
    """(prev_h, prev_l, prev_c, prev_o) from the day just before d, scanning
    back up to 4 days in case of weekends."""
    for lb in range(1, 5):
        p = d - timedelta(days=lb)
        if p in hlc_cache:
            return hlc_cache[p]
    return None


def build_hlc_cache(m5: pd.DataFrame) -> dict:
    """{date -> (H, L, C, O)}."""
    df = m5.copy()
    df["date"] = df["timestamp"].dt.date
    g = df.groupby("date").agg(h=("high","max"), l=("low","min"),
                                c=("close","last"), o=("open","first"))
    return {d: (r["h"], r["l"], r["c"], r["o"]) for d, r in g.iterrows()}


def _atr20_prior(hlc_cache: dict, d: date) -> float | None:
    prior = sorted(x for x in hlc_cache.keys() if x < d)
    if len(prior) < 5: return None
    tail = prior[-20:]
    ranges = [hlc_cache[x][0] - hlc_cache[x][1] for x in tail]
    return float(sum(ranges) / len(ranges))


def extract_features(m5: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame,
                      h1_cls: pd.DataFrame, h4_cls: pd.DataFrame,
                      m5_cls: pd.DataFrame, hlc_cache: dict,
                      d: date, uk_hour: int) -> dict | None:
    """Snapshot features at (d, uk_hour UK)."""
    as_of = uk_to_utc(d, uk_hour)
    m5_ts = m5["timestamp"].values.astype("datetime64[ns]")
    i_m5 = _bar_before(m5_ts, as_of.to_datetime64())
    if i_m5 < 0: return None
    spot = float(m5.at[i_m5, "close"])

    def _tf_dir(df_cls, as_of):
        ts = df_cls["timestamp"].values.astype("datetime64[ns]")
        i = _bar_before(ts, as_of.to_datetime64())
        if i < 0: return "NEUTRAL", float("nan")
        return df_cls.at[i, "direction"], float(df_cls.at[i, "strength"])

    h4_dir, h4_str = _tf_dir(h4_cls, as_of)
    h1_dir, h1_str = _tf_dir(h1_cls, as_of)
    m5_dir, m5_str = _tf_dir(m5_cls, as_of)

    asian_h, asian_l = _asian_hl(m5, as_of)
    prev = _prev_day_hlc(hlc_cache, d)
    prev_h = prev[0] if prev else None
    prev_l = prev[1] if prev else None
    prev_c = prev[2] if prev else None
    prev_o = prev[3] if prev else None
    prev_net = (prev_c - prev_o) if prev else None
    atr20 = _atr20_prior(hlc_cache, d)

    return dict(
        date=d, uk_hour=uk_hour, is_bst=is_bst(d),
        snapshot_utc=as_of, spot=spot,
        h4_dir=h4_dir, h4_strength=h4_str,
        h1_dir=h1_dir, h1_strength=h1_str,
        m5_dir=m5_dir, m5_strength=m5_str,
        alignment=alignment_state(h4_dir, h1_dir, m5_dir),
        asian_hi=asian_h, asian_lo=asian_l,
        prev_day_h=prev_h, prev_day_l=prev_l,
        prev_day_c=prev_c, prev_day_net=prev_net,
        atr20_daily=atr20,
    )


def iter_days(start: date, end: date, weekdays_only: bool = True) -> Iterator[date]:
    d = start
    while d <= end:
        if (not weekdays_only) or d.weekday() < 5:
            yield d
        d = d + timedelta(days=1)
