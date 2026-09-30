"""
htf_cache.py — Persistent HTF candle cache for TimeframeContext.

Persists H1 and D1 closed candle arrays to disk so that restarts can
skip the deep API fetch and only gap-fill since the last cached candle.

Cache location: /opt/tradingbot/cache/htf/
File naming:    {SYMBOL}_{TF}.json   e.g. GBPUSD_H1.json, EURUSD_D1.json

Cache format:
{
    "cached_at": "2026-03-26T12:00:00+00:00",
    "candles": [ {candle_dict}, ... ]
}

Each candle dict matches the TimeframeContext contract:
{
    "timeframe": "H1",
    "timestamp": "2026-03-26T11:00:00+00:00",
    "bucket_epoch": 1743001200,
    "open": 1.23456,
    "high": 1.23500,
    "low":  1.23400,
    "close": 1.23480
}
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AutoBot")

HTF_CACHE_DIR = os.path.join(
    os.getenv("CACHE_DIR", "/opt/tradingbot/cache").strip() or "/opt/tradingbot/cache",
    "htf",
)

MAX_CACHED_CANDLES = 800

# Per-timeframe freshness thresholds. A cache is "fresh" if the last bar is
# younger than its TF's threshold; otherwise gap-fill is requested. Defaults
# are slightly less than 1× bar duration so a cache containing the most
# recently closed bar is always treated as fresh, even between bar closes.
#
# Mid-session restarts (operator iterating on strategies) are the dominant
# REST allowance consumer; raising H1 freshness from the legacy 5-min default
# to 1h means a typical mid-session restart finds the cache fresh and skips
# REST gap-fill on H1 entirely. Same logic for D1 with 24h.
H1_FRESH_THRESHOLD_SECS = float(os.getenv("HTF_H1_FRESH_SECS", "3600"))     # 1 hour
H4_FRESH_THRESHOLD_SECS = float(os.getenv("HTF_H4_FRESH_SECS", "14400"))    # 4 hours
D1_FRESH_THRESHOLD_SECS = float(os.getenv("HTF_D1_FRESH_SECS", "86400"))    # 24 hours
# Fallback for any tf not in the table above. Also overridable for ops
# safety so the prior 5-min behaviour can be restored via single env knob.
FRESH_THRESHOLD_SECS = float(os.getenv("HTF_FRESH_SECS", "300"))            # 5 minutes


def _ensure_cache_dir() -> None:
    os.makedirs(HTF_CACHE_DIR, exist_ok=True)


def _cache_file_path(symbol: str, tf: str) -> str:
    return os.path.join(HTF_CACHE_DIR, f"{symbol.upper()}_{tf.upper()}.json")


# ------------------------------------------------------------------
# Read
# ------------------------------------------------------------------

def _dedup_sort_candles(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedup on bucket_epoch (last occurrence wins) and sort ascending.

    Live-LS writes append after cold-start REST data, so last-wins keeps
    the live-LS version on conflict — which is the one the running
    aggregator continues from. Defends downstream MACD calculations from
    the phantom out-of-order tail produced by mixed-source writes.
    """
    by_epoch: Dict[int, Dict[str, Any]] = {}
    for c in candles:
        ep = c.get("bucket_epoch")
        if ep is None:
            continue
        by_epoch[int(ep)] = c
    return sorted(by_epoch.values(), key=lambda c: int(c.get("bucket_epoch", 0)))


def load_cached_candles(symbol: str, tf: str) -> Optional[Dict[str, Any]]:
    """
    Load cached candle data from disk.

    Returns dict with keys 'cached_at' (str) and 'candles' (list),
    or None if no cache / corrupt file.

    Dedupes on read (defence-in-depth — save-side dedup is the primary).
    """
    path = _cache_file_path(symbol, tf)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "candles" not in data:
            logger.warning(f"[HTF-CACHE] {symbol}/{tf}: corrupt cache structure, deleting")
            _safe_delete(path)
            return None
        candles = data["candles"]
        if not isinstance(candles, list):
            logger.warning(f"[HTF-CACHE] {symbol}/{tf}: candles not a list, deleting")
            _safe_delete(path)
            return None
        deduped = _dedup_sort_candles(candles)
        if len(deduped) != len(candles):
            logger.info(
                f"[HTF-CACHE] {symbol}/{tf}: on-read dedup dropped "
                f"{len(candles) - len(deduped)} duplicate-bucket bar(s)"
            )
            data["candles"] = deduped
        return data
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"[HTF-CACHE] {symbol}/{tf}: corrupt cache file ({e}), deleting")
        _safe_delete(path)
        return None
    except Exception as e:
        logger.warning(f"[HTF-CACHE] {symbol}/{tf}: cache read failed ({e})")
        return None


def _safe_delete(path: str) -> None:
    try:
        os.remove(path)
    except Exception:
        pass


def last_candle_age_secs(candles: List[Dict[str, Any]]) -> Optional[float]:
    """
    Return age in seconds of the last candle's bucket_epoch relative to now.
    Returns None if candles list is empty or has no valid timestamp.
    """
    if not candles:
        return None
    last = candles[-1]
    bucket_epoch = last.get("bucket_epoch")
    if bucket_epoch is None:
        return None
    return time.time() - float(bucket_epoch)


def _threshold_for_tf(tf: Optional[str]) -> float:
    """Select the freshness threshold for a given timeframe.

    Falls back to FRESH_THRESHOLD_SECS for unknown TFs (legacy behaviour).
    """
    t = (str(tf or "").strip().upper())
    if t == "H1":
        return H1_FRESH_THRESHOLD_SECS
    if t == "H4":
        return H4_FRESH_THRESHOLD_SECS
    if t == "D1":
        return D1_FRESH_THRESHOLD_SECS
    return FRESH_THRESHOLD_SECS


def is_cache_fresh(candles: List[Dict[str, Any]], tf: Optional[str] = None) -> bool:
    """True if the last candle is younger than the per-TF freshness threshold.

    `tf` is optional for backwards-compat with any caller still on the
    pre-per-TF API (returns the fallback FRESH_THRESHOLD_SECS in that case).
    """
    age = last_candle_age_secs(candles)
    if age is None:
        return False
    return age < _threshold_for_tf(tf)


# ------------------------------------------------------------------
# Write
# ------------------------------------------------------------------

def save_candles_to_cache(symbol: str, tf: str, candles: List[Dict[str, Any]]) -> None:
    """
    Persist candle list to disk. Trims to MAX_CACHED_CANDLES.

    Dedupes on bucket_epoch (last-wins — live LS overrides REST gap-fill)
    and sorts ascending. Prevents the cold-start bug where REST's
    partial current-bucket bar and the live LS bar for the same bucket
    both persist, producing the out-of-order tail that corrupts MACD
    downstream (see trend_detection.is_clean_trend).
    Never raises — logs warning on failure.
    """
    try:
        _ensure_cache_dir()
        n_in = len(candles)
        deduped = _dedup_sort_candles(candles)
        n_dropped = n_in - len(deduped)
        trimmed = deduped[-MAX_CACHED_CANDLES:] if len(deduped) > MAX_CACHED_CANDLES else deduped
        data = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "candles": trimmed,
        }
        path = _cache_file_path(symbol, tf)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
        if n_dropped > 0:
            logger.info(
                f"[HTF-CACHE] {symbol}/{tf}: wrote {len(trimmed)} candles "
                f"(dedup dropped {n_dropped} duplicate-bucket bar(s))"
            )
        else:
            logger.debug(f"[HTF-CACHE] {symbol}/{tf}: wrote {len(trimmed)} candles to cache")
    except Exception as e:
        logger.warning(f"[HTF-CACHE] {symbol}/{tf}: cache write failed: {e}")


# ------------------------------------------------------------------
# Merge / deduplicate
# ------------------------------------------------------------------

def merge_candles(
    cached: List[Dict[str, Any]],
    fresh: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merge cached candles with freshly-fetched gap-fill candles.
    Deduplicates on bucket_epoch, preferring the fresh version on conflict.
    Returns merged list sorted by bucket_epoch, trimmed to MAX_CACHED_CANDLES.
    """
    by_epoch: Dict[int, Dict[str, Any]] = {}
    for c in cached:
        ep = c.get("bucket_epoch")
        if ep is not None:
            by_epoch[int(ep)] = c
    # Fresh candles overwrite cached on conflict
    for c in fresh:
        ep = c.get("bucket_epoch")
        if ep is not None:
            by_epoch[int(ep)] = c

    merged = sorted(by_epoch.values(), key=lambda c: int(c.get("bucket_epoch", 0)))
    if len(merged) > MAX_CACHED_CANDLES:
        merged = merged[-MAX_CACHED_CANDLES:]
    return merged


# ------------------------------------------------------------------
# Startup helper
# ------------------------------------------------------------------

def normalize_ig_hist_to_candles(
    tf: str,
    df,
) -> List[Dict[str, Any]]:
    """
    Convert an IG historical prices DataFrame (from _rest_fetch_df) into
    the candle dict format used by TimeframeContext.

    tf: "H1" or "D1"
    df: DataFrame with columns [timestamp, open, high, low, close]
    """
    import pandas as _pd
    from datetime import datetime as _dt, timezone as _tz

    bucket_secs = 3600 if tf == "H1" else 86400
    candles: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        try:
            ts_raw = row["timestamp"]
            if isinstance(ts_raw, (int, float)):
                ts_epoch = int(ts_raw)
            else:
                ts_epoch = int(_pd.Timestamp(str(ts_raw)).timestamp())

            # IG REST snapshotTime is END-of-bucket (HOUR DateTime "13:00" =
            # the bar covering [12:00, 13:00); DAY "2026-05-29" = bar for May 28).
            # The live LS aggregator stores bucket_epoch as START-of-bucket.
            # Shift by -bucket_secs so REST bars land in the slot the live
            # aggregator uses, otherwise gap-fill overwrites correct LS bars
            # with prev-bucket content (verified bug; see investigation
            # 2026-05-29). Used by autobot:5506 only (REST HOUR / DAY paths).
            bucket_epoch = ((ts_epoch // bucket_secs) * bucket_secs) - bucket_secs
            ts_dt = _dt.fromtimestamp(bucket_epoch, tz=_tz.utc)

            candles.append({
                "timeframe": tf,
                "timestamp": ts_dt.isoformat(),
                "bucket_epoch": bucket_epoch,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        except Exception:
            continue

    return candles


def startup_load_or_flag(
    symbol: str,
    tf: str,
) -> Tuple[str, Optional[List[Dict[str, Any]]], Optional[int]]:
    """
    Called at startup to check cache state for a symbol/timeframe.

    Returns (action, candles, last_bucket_epoch) where action is one of:
        "fresh"     — cache is fresh enough, use as-is (candles populated)
        "gap_fill"  — cache exists but stale, gap-fill from last_bucket_epoch
        "cold_start" — no usable cache, do full fetch
    """
    data = load_cached_candles(symbol, tf)
    if data is None:
        logger.warning(f"[HTF-CACHE] {symbol}/{tf}: cache miss — cold start required")
        return ("cold_start", None, None)

    candles = data["candles"]
    if not candles:
        logger.warning(f"[HTF-CACHE] {symbol}/{tf}: empty cache — cold start required")
        return ("cold_start", None, None)

    age = last_candle_age_secs(candles)
    last_epoch = int(candles[-1].get("bucket_epoch", 0))

    threshold = _threshold_for_tf(tf)
    age_min = (age or 0) / 60.0
    thr_min = threshold / 60.0

    if is_cache_fresh(candles, tf):
        logger.info(
            f"[HTF] {symbol} {tf} fresh (age={age_min:.1f} min, "
            f"threshold={thr_min:.1f} min) — skipping gap-fill, "
            f"{len(candles)} candles cached"
        )
        return ("fresh", candles, last_epoch)

    logger.info(
        f"[HTF] {symbol} {tf} stale (age={age_min:.1f} min, "
        f"threshold={thr_min:.1f} min) — requesting gap-fill, "
        f"{len(candles)} candles cached"
    )
    return ("gap_fill", candles, last_epoch)
