"""Shared helpers — structural-reversal research (Phase 1).

Independent of all prior reversal pipelines.  Only reused primitives
are the BID M5 reader and standard indicators (EMA / Bollinger / RSI)
because these are specification-level utilities, not strategy logic.

Design principles:

* ALL look-up uses only data available at the observation time.
  Swing confirmation happens N bars after the swing bar; swings older
  than N bars from "now" are eligible, newer are not.
* FX trading-day boundary: NY 17:00 close.  DST-aware (EDT in BST
  window = UTC-4; EST in GMT window = UTC-5).  Hence UTC 21:00 (BST)
  or UTC 22:00 (GMT).
* UK session boundaries use UK local wall time (Europe/London), so
  BST/GMT transitions are automatic via zoneinfo.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo


PATH_CANDLES_EXT = Path("/opt/tradingbot/data/candles_ext/GBPUSD")
PATH_CANDLES_MID = Path("/opt/tradingbot/data/candles/GBPUSD")

UK = ZoneInfo("Europe/London")
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Bar:
    ts: datetime        # bar OPEN time, UTC
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
    def is_green(self) -> bool:
        return self.close > self.open

    @property
    def is_red(self) -> bool:
        return self.close < self.open


def _parse_ts(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    s = s.replace(" ", "T", 1) if ("T" not in s and " " in s) else s
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_csv_bars(path: Path) -> list[Bar]:
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


def read_day(date_utc: datetime, prefer: str = "bid") -> list[Bar]:
    """Return M5 bars for the UTC calendar day of ``date_utc``.
    ``prefer='bid'`` → candles_ext (2024-2025 BID side).  Falls back
    to MID (candles/GBPUSD) if BID unavailable (used only for 2026
    case study).  Raises if neither available."""
    stem = f"{date_utc.strftime('%Y-%m-%d')}.csv"
    if prefer == "bid":
        p = PATH_CANDLES_EXT / stem
        if p.exists():
            return _read_csv_bars(p)
        p = PATH_CANDLES_MID / stem
        if p.exists():
            return _read_csv_bars(p)
    else:
        p = PATH_CANDLES_MID / stem
        if p.exists():
            return _read_csv_bars(p)
        p = PATH_CANDLES_EXT / stem
        if p.exists():
            return _read_csv_bars(p)
    raise FileNotFoundError(f"No M5 candles found for {date_utc.date()}")


def load_range(start: datetime, end: datetime, prefer: str = "bid") -> list[Bar]:
    """Return all M5 bars from start to end (both UTC)."""
    out: list[Bar] = []
    d = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_d = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    while d <= end_d:
        try:
            out.extend(read_day(d, prefer=prefer))
        except FileNotFoundError:
            pass
        d += timedelta(days=1)
    out = [b for b in out if start <= b.ts <= end]
    return out


# ─── Trading-day / session helpers ──────────────────────────────────
def ny_close_boundary_utc(ts_utc: datetime) -> datetime:
    """Return the UTC datetime of the NY 17:00 close that CLOSES the FX
    trading day ``ts_utc`` falls inside.

    FX day runs (NY 17:00 of day D-1) ≤ t < (NY 17:00 of day D) — day
    D is the LABEL of the trading day.  So a bar at 10:00 UTC on
    Monday falls into the Monday FX day (closes Monday 21:00 UTC in
    BST or 22:00 UTC in GMT).  A bar at 23:00 UTC on Monday falls
    into the Tuesday FX day (closes Tuesday 21:00/22:00 UTC)."""
    ny_dt = ts_utc.astimezone(NY)
    close_date = ny_dt.date()
    if ny_dt.hour >= 17:
        # Already past 17:00 NY — belongs to NEXT trading day
        from datetime import date, timedelta as _td
        close_date = close_date + _td(days=1)
    close_ny = datetime(close_date.year, close_date.month, close_date.day,
                        17, 0, tzinfo=NY)
    return close_ny.astimezone(timezone.utc)


def fx_trading_day_label(ts_utc: datetime) -> str:
    """Return 'YYYY-MM-DD' for the FX trading day containing ``ts_utc``.
    Label = date of the NY 17:00 close that terminates the day."""
    return ny_close_boundary_utc(ts_utc).astimezone(NY).strftime("%Y-%m-%d")


def uk_session_label(ts_utc: datetime) -> str:
    """Return one of ASIAN / LONDON / NY / OFF based on UK local wall
    time.  Boundaries (UK local, inclusive-start exclusive-end):
        00:00 - 07:59  ASIAN
        08:00 - 12:59  LONDON
        13:00 - 20:59  NY        (London/NY overlap + NY afternoon)
        else           OFF
    """
    uk_dt = ts_utc.astimezone(UK)
    h = uk_dt.hour
    if 0 <= h < 8:
        return "ASIAN"
    if 8 <= h < 13:
        return "LONDON"
    if 13 <= h < 21:
        return "NY"
    return "OFF"


# ─── Indicator helpers (purely point-in-time; no look-ahead) ────────
def ema(values: list[float], period: int) -> list[float | None]:
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


def bollinger(closes: list[float], period: int = 20,
              k: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
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
