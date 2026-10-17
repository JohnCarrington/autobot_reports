"""Attach D1 / H4 / H1 bias metadata to the episode ledger.

HTF is TAG-ONLY per amendment A1 — never gates or filters events.  These
columns are attached post-scan for use in Deliverables H and I.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
sys.path.insert(0, str(Path(__file__).parent.parent))

from d1_direction import compute_d1_direction_from_candles  # noqa: E402

from scripts.data_io import (
    D1Bar, M5Bar, load_d1_history, load_m5_fx_day,
)

HTF_FAST_PERIOD = 21
HTF_SLOW_PERIOD = 50
H1_SECONDS = 3600
H4_SECONDS = 4 * 3600


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average with alpha = 2/(N+1).  First `period-1`
    outputs are NaN."""
    if len(values) == 0:
        return np.array([])
    alpha = 2.0 / (period + 1.0)
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return out
    seed = values[:period].mean()
    out[period - 1] = seed
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _bias_from_ema(ema_fast: float, ema_slow: float) -> str:
    if np.isnan(ema_fast) or np.isnan(ema_slow):
        return "NEUTRAL"
    if ema_fast > ema_slow:
        return "BULL"
    if ema_fast < ema_slow:
        return "BEAR"
    return "NEUTRAL"


def _resample_m5_to_htf(bars: List[M5Bar], bucket_seconds: int
                        ) -> Tuple[List[datetime], np.ndarray]:
    """Aggregate M5 → HTF bar closes.  Returns list of (bucket_end_ts, close)."""
    buckets: Dict[int, List[M5Bar]] = {}
    for b in bars:
        epoch = int(b.ts.timestamp())
        key = (epoch // bucket_seconds) * bucket_seconds
        buckets.setdefault(key, []).append(b)
    sorted_keys = sorted(buckets.keys())
    ts_list: List[datetime] = []
    closes: List[float] = []
    for k in sorted_keys:
        bucket = buckets[k]
        if len(bucket) < bucket_seconds // 300 // 2:   # <50% complete
            continue
        bucket_end = datetime.fromtimestamp(k + bucket_seconds, tz=timezone.utc)
        ts_list.append(bucket_end)
        closes.append(bucket[-1].close)
    return ts_list, np.array(closes)


def _htf_bias_at(start_ts: datetime, ts_list: List[datetime],
                 ema_fast: np.ndarray, ema_slow: np.ndarray) -> str:
    """Return bias of the most recent CLOSED HTF bar strictly before start_ts."""
    if not ts_list:
        return "NEUTRAL"
    # Find rightmost index with ts <= start_ts
    i = -1
    for idx, t in enumerate(ts_list):
        if t <= start_ts:
            i = idx
        else:
            break
    if i < 0:
        return "NEUTRAL"
    return _bias_from_ema(ema_fast[i], ema_slow[i])


def compute_htf_for_day(
    fx_date: date, candle_src: str, episodes_df: pd.DataFrame,
    history_days: int = 60,
) -> pd.DataFrame:
    """Attach d1_bias, h4_bias, h1_bias, d1_h4_aligned columns to episodes_df
    for a single FX day.  Mutates nothing — returns a new DataFrame.
    """
    if episodes_df.empty:
        return episodes_df.assign(
            d1_bias="NEUTRAL", h4_bias="NEUTRAL", h1_bias="NEUTRAL",
            d1_h4_aligned=False, trade_vs_d1="d1_neutral",
        )

    # ---- D1 bias ----
    d1_hist = load_d1_history(up_to=fx_date, lookback_days=history_days)
    d1_dicts = [
        {
            "open": b.open, "high": b.high, "low": b.low, "close": b.close,
            "timestamp": b.date.isoformat(),
            "bucket_epoch": int(datetime(b.date.year, b.date.month, b.date.day,
                                         22, tzinfo=timezone.utc).timestamp()),
        }
        for b in d1_hist
    ]
    try:
        d1_res = compute_d1_direction_from_candles("GBPUSD", d1_dicts)
        d1_bias = d1_res.get("direction", "NEUTRAL")
    except Exception:
        d1_bias = "NEUTRAL"

    # ---- H4 and H1 series ----
    bars: List[M5Bar] = []
    for d_before in range(history_days, 0, -1):
        d = fx_date - timedelta(days=d_before)
        src = "candles" if d >= date(2026, 1, 1) else "candles_ext_v2"
        bars.extend(load_m5_fx_day(d, src))
    bars.extend(load_m5_fx_day(fx_date, candle_src))

    h4_ts, h4_closes = _resample_m5_to_htf(bars, H4_SECONDS)
    h1_ts, h1_closes = _resample_m5_to_htf(bars, H1_SECONDS)
    h4_fast = _ema(h4_closes, HTF_FAST_PERIOD)
    h4_slow = _ema(h4_closes, HTF_SLOW_PERIOD)
    h1_fast = _ema(h1_closes, HTF_FAST_PERIOD)
    h1_slow = _ema(h1_closes, HTF_SLOW_PERIOD)

    out = episodes_df.copy()
    out["d1_bias"] = d1_bias
    out["h4_bias"] = out["start_ts"].apply(
        lambda t: _htf_bias_at(pd.Timestamp(t).to_pydatetime(), h4_ts, h4_fast, h4_slow)
    )
    out["h1_bias"] = out["start_ts"].apply(
        lambda t: _htf_bias_at(pd.Timestamp(t).to_pydatetime(), h1_ts, h1_fast, h1_slow)
    )
    out["d1_h4_aligned"] = out["h4_bias"] == d1_bias
    # trade direction vs D1
    def _trade_vs_d1(row: pd.Series) -> str:
        if d1_bias == "NEUTRAL":
            return "d1_neutral"
        if row["rejection_direction"] == "BUY" and d1_bias == "BULL":
            return "aligned"
        if row["rejection_direction"] == "SELL" and d1_bias == "BEAR":
            return "aligned"
        return "countertrend"
    out["trade_vs_d1"] = out.apply(_trade_vs_d1, axis=1)
    return out


def attach_htf_bulk(ledger: pd.DataFrame) -> pd.DataFrame:
    """Attach HTF metadata to every row in the ledger, grouped by fx_date."""
    out_chunks = []
    for (fx, src), group in ledger.groupby(["fx_date", "candle_src"]):
        enriched = compute_htf_for_day(fx, src, group)
        out_chunks.append(enriched)
    return pd.concat(out_chunks, ignore_index=True)
