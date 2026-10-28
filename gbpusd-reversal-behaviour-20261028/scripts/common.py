"""Shared helpers for the GBP/USD reversal-behaviour research."""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional


# ─────────────────────────────────────────────────────────────────────
# Data provenance (recorded in every output)
# ─────────────────────────────────────────────────────────────────────
# BID-side M5 archive (2024-01-01 → 2025-12-31).  Written by the live
# feed; one row per completed 5-minute bar; OHLC on the bid.
PATH_CANDLES_EXT = Path("/opt/tradingbot/data/candles_ext/GBPUSD")

# MID-of-bid-ask M5 archive, written live by candle_archive on this host.
# Covers 2026-01-01 → today.  Used only when BID candles are not
# available (today's two events).  Documented in each case.
PATH_CANDLES_MID = Path("/opt/tradingbot/data/candles/GBPUSD")

# Phase 2 corrected tick cache (BID + ASK, UTC-corrected).  Used only
# when a tick-level question cannot be answered from candles.
PATH_TICK_CACHE = Path(
    "/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD"
)


@dataclass(frozen=True)
class Bar:
    ts: datetime     # bar OPEN time, UTC
    open: float
    high: float
    low: float
    close: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_green(self) -> bool:
        return self.close > self.open

    @property
    def is_red(self) -> bool:
        return self.close < self.open


def _parse_ts(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    # Both "YYYY-mm-ddTHH:MM:SS+00:00" and "YYYY-mm-dd HH:MM:SS+00:00"
    s = s.replace(" ", "T", 1) if s.count("T") == 0 and " " in s else s
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_csv(path: Path) -> list[Bar]:
    out: list[Bar] = []
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                out.append(Bar(
                    ts=_parse_ts(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                ))
            except Exception:
                continue
    return out


def read_bid_m5(date_utc: datetime) -> list[Bar]:
    """Return BID M5 bars for ``date_utc.date()``.  Raises if not available."""
    p = PATH_CANDLES_EXT / f"{date_utc.strftime('%Y-%m-%d')}.csv"
    if not p.exists():
        raise FileNotFoundError(f"BID M5 not available for {date_utc.date()} ({p})")
    return _read_csv(p)


def read_mid_m5(date_utc: datetime) -> list[Bar]:
    """Return MID-of-bid-ask M5 bars for ``date_utc.date()``.  Used only
    when BID is unavailable."""
    p = PATH_CANDLES_MID / f"{date_utc.strftime('%Y-%m-%d')}.csv"
    if not p.exists():
        raise FileNotFoundError(f"MID M5 not available for {date_utc.date()} ({p})")
    return _read_csv(p)


def read_bid_m5_from_ticks(date_utc: datetime) -> list[Bar]:
    """Reconstruct BID M5 from the Phase 2 corrected tick cache.  Used
    for 2026 Q1 (no candles_ext coverage yet when the file was built)."""
    import numpy as np
    import pandas as pd
    yr = date_utc.year
    p = PATH_TICK_CACHE / f"{yr}.parquet"
    if not p.exists():
        raise FileNotFoundError(f"tick parquet not available for {yr}")
    day_start = int(datetime(date_utc.year, date_utc.month, date_utc.day,
                              tzinfo=timezone.utc).timestamp() * 1e9)
    day_end = day_start + 86_400_000_000_000
    df = pd.read_parquet(p, columns=["ts_utc_ns", "bid"])
    df = df[(df["ts_utc_ns"] >= day_start) & (df["ts_utc_ns"] < day_end)].copy()
    if df.empty:
        raise FileNotFoundError(f"no ticks found in {yr} parquet for {date_utc.date()}")
    bar_delta = 5 * 60 * 1_000_000_000
    df["bar_id"] = (df["ts_utc_ns"].values // bar_delta).astype(np.int64)
    agg = df.groupby("bar_id")["bid"].agg(["first", "max", "min", "last"]).reset_index()
    agg["bar_open_ns"] = agg["bar_id"] * bar_delta
    bars: list[Bar] = []
    for _, r in agg.iterrows():
        ts = datetime.fromtimestamp(int(r["bar_open_ns"]) / 1e9, tz=timezone.utc)
        bars.append(Bar(ts=ts,
                        open=float(r["first"]),
                        high=float(r["max"]),
                        low=float(r["min"]),
                        close=float(r["last"])))
    return bars


# ─────────────────────────────────────────────────────────────────────
# Indicator helpers (purely point-in-time; no look-ahead)
# ─────────────────────────────────────────────────────────────────────
def ema(values: list[float], period: int) -> list[float | None]:
    """Standard EMA with simple-average warm-up."""
    if period <= 0:
        return [None] * len(values)
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1.0)
    prev = seed
    for i in range(period, len(values)):
        prev = (values[i] - prev) * k + prev
        out[i] = prev
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Return (macd_line, signal_line, histogram) with None for warm-up bars."""
    ef = ema(closes, fast)
    es = ema(closes, slow)
    macd_line: list[float | None] = [
        (ef[i] - es[i]) if (ef[i] is not None and es[i] is not None) else None
        for i in range(len(closes))
    ]
    # Signal is an EMA of the macd_line's non-None region
    first_non_none = next((i for i, v in enumerate(macd_line) if v is not None), None)
    sig_series: list[float | None] = [None] * len(closes)
    hist_series: list[float | None] = [None] * len(closes)
    if first_non_none is not None:
        tail = [v for v in macd_line[first_non_none:] if v is not None]
        sig_tail = ema(tail, signal)
        for i, v in enumerate(sig_tail):
            if v is None:
                continue
            idx = first_non_none + i
            sig_series[idx] = v
            if macd_line[idx] is not None:
                hist_series[idx] = macd_line[idx] - v
    return macd_line, sig_series, hist_series


def bollinger(closes: list[float], period: int = 20,
              k: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Return (lower, middle, upper) with None warm-up.  Population stddev."""
    n = len(closes)
    low, mid, up = [None] * n, [None] * n, [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / period
        s = math.sqrt(var)
        mid[i] = m
        low[i] = m - k * s
        up[i] = m + k * s
    return low, mid, up


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
    out[period] = 100.0 if math.isinf(rs) else 100.0 - 100.0 / (1.0 + rs)
    for i in range(period + 1, n):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
        out[i] = 100.0 if math.isinf(rs) else 100.0 - 100.0 / (1.0 + rs)
    return out
