# =========================
# FILE: candle_archive.py
# =========================
"""
candle_archive.py — Append-only daily candle archive for the probability engine.

Registers itself as a 5m-close callback and appends each closed OHLCV candle
to a per-symbol daily file:

    /opt/tradingbot/data/candles/{SYMBOL}/YYYY-MM-DD.csv

The daily file rolls at UTC midnight automatically (candle timestamp determines
the file). The warm-up cache (/opt/tradingbot/cache/*_candles.csv) is untouched.

CSV schema: timestamp,open,high,low,close
All timestamps are ISO-8601 UTC.

Usage (import-side-effect only):
    import candle_archive   # registers callback; no further calls needed
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("AutoBot")

ARCHIVE_ROOT = Path(os.getenv("CANDLE_ARCHIVE_DIR", "/opt/tradingbot/data/candles"))
_CSV_HEADER = ("timestamp", "open", "high", "low", "close")


# ── helpers ──────────────────────────────────────────────────────────────────

def _daily_path(symbol: str, ts: datetime) -> Path:
    """Return the daily CSV path for *symbol* on the UTC date of *ts*."""
    date_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return ARCHIVE_ROOT / symbol.upper() / f"{date_str}.csv"


def _ensure_header(path: Path) -> None:
    """Write CSV header if the file is new / empty."""
    if path.stat().st_size == 0:
        with path.open("w", newline="") as fh:
            csv.writer(fh).writerow(_CSV_HEADER)


def _candle_ts(payload: Dict[str, Any]) -> datetime | None:
    """Extract a UTC-aware datetime from a 5m-close payload."""
    # Prefer the candle sub-dict first, then ISO string fallback
    candle = payload.get("candle") or {}
    ts = candle.get("timestamp")
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    iso = payload.get("candle_ts_utc")
    if iso:
        try:
            return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass

    epoch = payload.get("bucket_epoch")
    if epoch is not None:
        try:
            return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        except Exception:
            pass

    return None


# ── archive writer ────────────────────────────────────────────────────────────

def archive_candle(payload: Dict[str, Any]) -> None:
    """5m-close callback: append OHLCV row to the appropriate daily file."""
    try:
        symbol = str(payload.get("symbol") or "").upper()
        if not symbol:
            return

        candle = payload.get("candle") or {}
        try:
            o = float(candle["open"])
            h = float(candle["high"])
            l = float(candle["low"])
            c = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            return

        ts = _candle_ts(payload)
        if ts is None:
            return

        path = _daily_path(symbol, ts)
        path.parent.mkdir(parents=True, exist_ok=True)

        is_new = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(_CSV_HEADER)
            writer.writerow([ts.isoformat(), o, h, l, c])

    except Exception as e:
        logger.warning(f"[candle_archive] write failed: {e}", exc_info=True)


# ── backfill helper ───────────────────────────────────────────────────────────

def backfill_from_cache(symbol: str, cache_csv: str | Path) -> int:
    """
    Seed the daily archive from an existing warm-up cache CSV.
    Skips rows already present in the corresponding daily file.
    Returns the number of rows written.
    """
    cache_csv = Path(cache_csv)
    if not cache_csv.exists():
        return 0

    import pandas as pd

    try:
        df = pd.read_csv(cache_csv)
    except Exception as e:
        logger.warning(f"[candle_archive] backfill read failed for {cache_csv}: {e}")
        return 0

    # normalise column name
    if "timestamp" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"timestamp": "time"})
    if "time" not in df.columns:
        return 0

    df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    df = df.dropna(subset=["time"]).sort_values("time")

    written = 0
    for _, row in df.iterrows():
        ts = row["time"].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)

        try:
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
        except (KeyError, ValueError):
            continue

        path = _daily_path(symbol, ts)
        path.parent.mkdir(parents=True, exist_ok=True)

        # load existing timestamps for this day to avoid duplicates
        existing: set[str] = set()
        if path.exists() and path.stat().st_size > 0:
            try:
                with path.open() as fh:
                    reader = csv.DictReader(fh)
                    for r in reader:
                        existing.add(r.get("timestamp", ""))
            except Exception:
                pass

        ts_iso = ts.isoformat()
        if ts_iso in existing:
            continue

        is_new = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(_CSV_HEADER)
            writer.writerow([ts_iso, o, h, l, c])
        written += 1

    return written


# ── self-registration ─────────────────────────────────────────────────────────

def _register() -> None:
    try:
        from candle_builder import register_5m_close_callback
        register_5m_close_callback(archive_candle)
        logger.info("[candle_archive] registered 5m-close callback → %s", ARCHIVE_ROOT)
    except Exception as e:
        logger.error("[candle_archive] failed to register callback: %s", e, exc_info=True)


_register()
