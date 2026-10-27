"""
Session-window movement measurement.

For every (date, reference-timestamp, window) we measure:
  - mfu  (max favorable up from reference close, i.e. max(high-ref) over window)
  - mfd  (max favorable down from reference close)
  - net  (close at end of window - ref close)
  - high / low timestamps
  - total range (window high - window low)
  - approach_only moves (optional)

Reference prices:
  - r06  = last completed M5 close at 06:00 UK
  - r07  = last completed M5 close at 07:00 UK

Windows (UK local; see features.uk_to_utc for conversion):
  - PRE_LONDON    05:00 - 07:00
  - EARLY_LONDON  07:00 - 10:00
  - LATE_LONDON   10:00 - 13:00
  - OVERLAP       13:00 - 17:00
  - LATE_NY       17:00 - 22:00

Session metrics are expressed in pips (price-scale units).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

import numpy as np
import pandas as pd

from features import uk_to_utc

WINDOWS = [
    ("PRE_LONDON",   5, 7),
    ("EARLY_LONDON", 7, 10),
    ("LATE_LONDON",  10, 13),
    ("OVERLAP",      13, 17),
    ("LATE_NY",      17, 22),
]


class WindowStats(NamedTuple):
    name: str
    ref_price: float
    n_bars: int
    high: float
    low: float
    high_time: pd.Timestamp
    low_time: pd.Timestamp
    net: float          # close_at_end - ref
    mfu: float          # max(high - ref) over window
    mfd: float          # max(ref - low) over window
    range_pips: float   # high - low


def _window_slice(m5: pd.DataFrame, d: date, start_uk: int, end_uk: int) -> pd.DataFrame:
    start_utc = uk_to_utc(d, start_uk).to_datetime64()
    end_utc = uk_to_utc(d, end_uk).to_datetime64()
    ts = m5["timestamp"].values.astype("datetime64[ns]")
    i0 = int(np.searchsorted(ts, start_utc, side="left"))
    i1 = int(np.searchsorted(ts, end_utc, side="left"))
    if i1 <= i0: return m5.iloc[0:0]
    return m5.iloc[i0:i1]


def _ref_price(m5: pd.DataFrame, d: date, uk_hour: int) -> float | None:
    """Last completed M5 close strictly before the UK hour."""
    as_of = uk_to_utc(d, uk_hour).to_datetime64()
    ts = m5["timestamp"].values.astype("datetime64[ns]")
    i = int(np.searchsorted(ts, as_of, side="left")) - 1
    if i < 0: return None
    return float(m5.at[i, "close"])


def measure_window(m5: pd.DataFrame, d: date,
                   window: tuple[str, int, int],
                   ref_price: float) -> WindowStats | None:
    name, uk_start, uk_end = window
    sub = _window_slice(m5, d, uk_start, uk_end)
    if len(sub) == 0: return None
    hi_idx = int(sub["high"].idxmax())
    lo_idx = int(sub["low"].idxmin())
    hi = float(sub.at[hi_idx, "high"])
    lo = float(sub.at[lo_idx, "low"])
    hi_t = sub.at[hi_idx, "timestamp"]
    lo_t = sub.at[lo_idx, "timestamp"]
    end_close = float(sub["close"].iloc[-1])
    return WindowStats(
        name=name, ref_price=ref_price, n_bars=len(sub),
        high=hi, low=lo, high_time=hi_t, low_time=lo_t,
        net=end_close - ref_price,
        mfu=hi - ref_price,
        mfd=ref_price - lo,
        range_pips=hi - lo,
    )


def measure_all_windows(m5: pd.DataFrame, d: date,
                        ref_uk_hour: int = 6) -> list[dict]:
    """Return one row per window for day `d`, ref'd to the given UK hour."""
    ref = _ref_price(m5, d, ref_uk_hour)
    if ref is None: return []
    rows = []
    for w in WINDOWS:
        ws = measure_window(m5, d, w, ref)
        if ws is None: continue
        rows.append(dict(
            date=d, ref_uk_hour=ref_uk_hour, window=ws.name, ref_price=ws.ref_price,
            n_bars=ws.n_bars, high=ws.high, low=ws.low,
            high_time=ws.high_time, low_time=ws.low_time,
            net=ws.net, mfu=ws.mfu, mfd=ws.mfd, range_pips=ws.range_pips,
        ))
    return rows


def measure_whole_day_from_ref(m5: pd.DataFrame, d: date,
                                ref_uk_hour: int, until_uk_hour: int) -> dict | None:
    """A single aggregate window from `ref_uk_hour` to `until_uk_hour` (UK)."""
    ref = _ref_price(m5, d, ref_uk_hour)
    if ref is None: return None
    sub = _window_slice(m5, d, ref_uk_hour, until_uk_hour)
    if len(sub) == 0: return None
    hi_idx = int(sub["high"].idxmax())
    lo_idx = int(sub["low"].idxmin())
    hi = float(sub.at[hi_idx, "high"])
    lo = float(sub.at[lo_idx, "low"])
    end_close = float(sub["close"].iloc[-1])
    return dict(
        date=d, ref_uk_hour=ref_uk_hour, until_uk_hour=until_uk_hour,
        ref_price=ref, high=hi, low=lo,
        high_time=sub.at[hi_idx, "timestamp"], low_time=sub.at[lo_idx, "timestamp"],
        net=end_close - ref, mfu=hi - ref, mfd=ref - lo, range_pips=hi - lo,
        n_bars=len(sub),
    )
