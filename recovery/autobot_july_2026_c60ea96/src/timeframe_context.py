# timeframe_context.py
"""
timeframe_context.py (HTF BUILDER)

Roadmap item #2:
- Input: CLOSED 5m candle callback payload (canonical contracts)
- Maintains aggregated H1 + D1 candles (built only from closed 5m candles)
- Computes explicit directional bias:
    Prefer D1 bias; if D1 is NEUTRAL, use H1
- Output: Timeframe snapshot dict (bias + last H1/D1 candle + debug)

Non-negotiables:
- No bot imports
- No I/O
- No globals / caching
- Deterministic behavior given the sequence of closed 5m payloads
- Prices remain native IG units (points). No normalization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


Bias = str  # "BULL" | "BEAR" | "NEUTRAL"


@dataclass
class _PartialCandle:
    """
    Internal partial aggregate candle for a given bucket.
    """
    timeframe: str  # "H1" or "D1"
    bucket_epoch: int
    timestamp: datetime  # UTC-aware
    open: float
    high: float
    low: float
    close: float

    def update_from_5m(self, candle_5m: Dict[str, Any]) -> None:
        h = float(candle_5m["high"])
        l = float(candle_5m["low"])
        c = float(candle_5m["close"])
        self.high = max(self.high, h)
        self.low = min(self.low, l)
        self.close = c


def _floor_bucket(epoch: int, seconds: int) -> int:
    if seconds <= 0:
        raise ValueError("seconds must be > 0")
    return (int(epoch) // seconds) * seconds


def _epoch_to_utc_dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc)


def _safe_iso_utc(dt: datetime) -> str:
    if not isinstance(dt, datetime):
        raise TypeError("dt must be datetime")
    if dt.tzinfo is None:
        # contract requires tz-aware internally; enforce
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _candle_to_contract_dict(timeframe: str, partial: _PartialCandle) -> Dict[str, Any]:
    return {
        "timeframe": timeframe,
        "timestamp": _safe_iso_utc(partial.timestamp),
        "bucket_epoch": int(partial.bucket_epoch),
        "open": float(partial.open),
        "high": float(partial.high),
        "low": float(partial.low),
        "close": float(partial.close),
    }


def _compute_ema(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("EMA period must be > 0")
    s = pd.to_numeric(series, errors="coerce").astype(float)
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def _compute_bias_from_candles(
    candles: List[Dict[str, Any]],
    ema_fast: int,
    ema_slow: int,
    neutral_buffer_points: float,
) -> Tuple[Bias, Dict[str, Any]]:
    """
    Bias = sign(EMA_fast - EMA_slow), with neutral buffer around 0.

    neutral_buffer_points: threshold in native IG points.
      - if abs(spread) <= neutral_buffer_points => NEUTRAL
      - else spread > 0 => BULL, spread < 0 => BEAR
    """
    debug: Dict[str, Any] = {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "neutral_buffer_points": float(neutral_buffer_points),
        "reason": None,
        "spread": None,
        "ema_fast_last": None,
        "ema_slow_last": None,
        "candles_count": len(candles),
    }

    if len(candles) < ema_slow:
        debug["reason"] = "not_enough_candles"
        return "NEUTRAL", debug

    closes = pd.Series([float(c["close"]) for c in candles], dtype="float64")
    ema_f = _compute_ema(closes, ema_fast)
    ema_s = _compute_ema(closes, ema_slow)

    ef = float(ema_f.iloc[-1])
    es = float(ema_s.iloc[-1])
    spread = ef - es

    debug["ema_fast_last"] = ef
    debug["ema_slow_last"] = es
    debug["spread"] = float(spread)

    if abs(spread) <= float(neutral_buffer_points):
        debug["reason"] = "inside_neutral_buffer"
        return "NEUTRAL", debug

    debug["reason"] = "ema_spread"
    return ("BULL" if spread > 0 else "BEAR"), debug


class TimeframeContext:
    """
    Builds higher timeframe candles (H1, H4, D1) from CLOSED 5m candles only,
    and computes HTF bias snapshots.

    Contract-consumer: closed 5m payload shape defined in contracts.md.
    """

    def __init__(
        self,
        ema_fast: int = 21,
        ema_slow: int = 50,
        neutral_buffer_points: float = 0.0,
        max_h1_candles: int = 800,
        max_h4_candles: int = 200,
        max_d1_candles: int = 400,
    ) -> None:
        if ema_fast <= 0 or ema_slow <= 0:
            raise ValueError("EMA periods must be > 0")
        if ema_fast >= ema_slow:
            raise ValueError("ema_fast must be < ema_slow")
        if neutral_buffer_points < 0:
            raise ValueError("neutral_buffer_points must be >= 0")
        if max_h1_candles <= 0 or max_h4_candles <= 0 or max_d1_candles <= 0:
            raise ValueError("max candle limits must be > 0")

        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.neutral_buffer_points = float(neutral_buffer_points)

        self.max_h1_candles = int(max_h1_candles)
        self.max_h4_candles = int(max_h4_candles)
        self.max_d1_candles = int(max_d1_candles)

        # Per-symbol state
        self._h1_closed:  Dict[str, List[Dict[str, Any]]] = {}
        self._h4_closed:  Dict[str, List[Dict[str, Any]]] = {}
        self._d1_closed:  Dict[str, List[Dict[str, Any]]] = {}
        self._h1_partial: Dict[str, Optional[_PartialCandle]] = {}
        self._h4_partial: Dict[str, Optional[_PartialCandle]] = {}
        self._d1_partial: Dict[str, Optional[_PartialCandle]] = {}

    def on_5m_close(self, symbol: str, epic: str, closed_5m: Dict[str, Any]) -> Dict[str, Any]:
        """
        Contract signature (per contracts.md):
            TimeframeContext.on_5m_close(symbol, epic, closed_5m) -> ContextSnapshot (dict)

        closed_5m is the full closed-5m callback payload dict, including:
          - symbol, epic, timeframe="5m"
          - candle: {timestamp(datetime UTC-aware), open, high, low, close}
          - candle_ts_utc, bucket_epoch, source, optional debug keys

        Returns snapshot dict:
          {
            "bias": ...,
            "d1_bias": ...,
            "h4_bias": ...,
            "h1_bias": ...,
            "h1_ema8": ...,
            "h1_ema21": ...,
            "h1_price": ...,
            "last_d1_candle": {...} | None,
            "last_h4_candle": {...} | None,
            "last_h1_candle": {...} | None,
            "debug": {...}
          }
        """
        # Minimal contract validation (no assumptions beyond contract keys)
        if not isinstance(closed_5m, dict):
            raise TypeError("closed_5m must be a dict payload")
        if closed_5m.get("timeframe") != "5m":
            raise ValueError("closed_5m.timeframe must be '5m'")

        candle = closed_5m.get("candle")
        if not isinstance(candle, dict):
            raise ValueError("closed_5m.candle must be a dict")

        bucket_epoch = closed_5m.get("bucket_epoch")
        if not isinstance(bucket_epoch, int):
            raise ValueError("closed_5m.bucket_epoch must be int")

        ts = candle.get("timestamp")
        if not isinstance(ts, datetime):
            raise ValueError("candle.timestamp must be datetime (tz-aware UTC)")
        if ts.tzinfo is None:
            raise ValueError("candle.timestamp must be tz-aware (UTC)")

        # Initialize per-symbol storage
        self._h1_closed.setdefault(symbol, [])
        self._h4_closed.setdefault(symbol, [])
        self._d1_closed.setdefault(symbol, [])
        if symbol not in self._h1_partial:
            self._h1_partial[symbol] = None
        if symbol not in self._h4_partial:
            self._h4_partial[symbol] = None
        if symbol not in self._d1_partial:
            self._d1_partial[symbol] = None

        # Update aggregates
        h1_closed_event = self._update_timeframe(symbol, candle, bucket_epoch, tf="H1", seconds=3600)
        h4_closed_event = self._update_timeframe(symbol, candle, bucket_epoch, tf="H4", seconds=14400)
        d1_closed_event = self._update_timeframe(symbol, candle, bucket_epoch, tf="D1", seconds=86400)

        # Compute biases from closed candle lists
        h1_bias, h1_dbg = _compute_bias_from_candles(
            self._h1_closed[symbol],
            ema_fast=self.ema_fast,
            ema_slow=self.ema_slow,
            neutral_buffer_points=self.neutral_buffer_points,
        )
        h4_bias, h4_dbg = _compute_bias_from_candles(
            self._h4_closed[symbol],
            ema_fast=self.ema_fast,
            ema_slow=self.ema_slow,
            neutral_buffer_points=self.neutral_buffer_points,
        )
        d1_bias, d1_dbg = _compute_bias_from_candles(
            self._d1_closed[symbol],
            ema_fast=self.ema_fast,
            ema_slow=self.ema_slow,
            neutral_buffer_points=self.neutral_buffer_points,
        )

        # Prefer D1; if D1 neutral -> use H1
        if d1_bias != "NEUTRAL":
            chosen_bias = d1_bias
            source = "D1"
        elif h1_bias != "NEUTRAL":
            chosen_bias = h1_bias
            source = "H1"
        else:
            chosen_bias = "NEUTRAL"
            source = "NONE"

        last_h1 = self._h1_closed[symbol][-1] if self._h1_closed[symbol] else None
        last_h4 = self._h4_closed[symbol][-1] if self._h4_closed[symbol] else None
        last_d1 = self._d1_closed[symbol][-1] if self._d1_closed[symbol] else None

        # Minimal additions for EMA pullback H1 anchor:
        # expose literal H1 EMA8 / EMA21 / H1 price location without changing existing bias logic.
        h1_ema8: Optional[float] = None
        h1_ema21: Optional[float] = None
        h1_price: Optional[float] = None
        h1_anchor_ready = False
        h1_anchor_buy_ok = False
        h1_anchor_sell_ok = False

        try:
            if len(self._h1_closed[symbol]) >= 21:
                h1_closes = pd.Series(
                    [float(c["close"]) for c in self._h1_closed[symbol]],
                    dtype="float64",
                )
                ema8_series = _compute_ema(h1_closes, 8)
                ema21_series = _compute_ema(h1_closes, 21)

                h1_ema8 = float(ema8_series.iloc[-1])
                h1_ema21 = float(ema21_series.iloc[-1])
                h1_price = float(h1_closes.iloc[-1])

                h1_anchor_ready = True
                h1_anchor_buy_ok = bool(
                    h1_ema8 > h1_ema21
                    and h1_price > h1_ema8
                    and h1_price > h1_ema21
                )
                h1_anchor_sell_ok = bool(
                    h1_ema8 < h1_ema21
                    and h1_price < h1_ema8
                    and h1_price < h1_ema21
                )
        except Exception:
            h1_ema8 = None
            h1_ema21 = None
            h1_price = None
            h1_anchor_ready = False
            h1_anchor_buy_ok = False
            h1_anchor_sell_ok = False

        snapshot: Dict[str, Any] = {
            "bias": chosen_bias,
            "d1_bias": d1_bias,
            "h4_bias": h4_bias,
            "h1_bias": h1_bias,
            "h1_ema8": h1_ema8,
            "h1_ema21": h1_ema21,
            "h1_price": h1_price,
            "h1_anchor_ready": h1_anchor_ready,
            "h1_anchor_buy_ok": h1_anchor_buy_ok,
            "h1_anchor_sell_ok": h1_anchor_sell_ok,
            "last_d1_candle": last_d1,
            "last_h4_candle": last_h4,
            "last_h1_candle": last_h1,
            "debug": {
                "source": source,
                "symbol": symbol,
                "epic": epic,
                "event": {
                    "h1_closed": h1_closed_event,
                    "h4_closed": h4_closed_event,
                    "d1_closed": d1_closed_event,
                },
                "h1": h1_dbg,
                "h4": h4_dbg,
                "d1": d1_dbg,
                "counts": {
                    "h1_closed": len(self._h1_closed[symbol]),
                    "h4_closed": len(self._h4_closed[symbol]),
                    "d1_closed": len(self._d1_closed[symbol]),
                },
                "h1_anchor": {
                    "ready": h1_anchor_ready,
                    "ema8": h1_ema8,
                    "ema21": h1_ema21,
                    "price": h1_price,
                    "buy_ok": h1_anchor_buy_ok,
                    "sell_ok": h1_anchor_sell_ok,
                },
            },
        }
        return snapshot

    def _update_timeframe(
        self,
        symbol: str,
        candle_5m: Dict[str, Any],
        candle_5m_bucket_epoch: int,
        tf: str,
        seconds: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Update partial candle for timeframe (H1, H4, or D1) and close previous bucket if changed.
        Returns an event dict when a candle is closed, else None.
        """
        bucket = _floor_bucket(candle_5m_bucket_epoch, seconds)
        ts = _epoch_to_utc_dt(bucket)

        if tf == "H1":
            partial_map = self._h1_partial
            closed_map  = self._h1_closed
            max_keep    = self.max_h1_candles
        elif tf == "H4":
            partial_map = self._h4_partial
            closed_map  = self._h4_closed
            max_keep    = self.max_h4_candles
        else:
            partial_map = self._d1_partial
            closed_map  = self._d1_closed
            max_keep    = self.max_d1_candles

        current = partial_map.get(symbol)

        # Start a new partial if none exists
        if current is None:
            partial_map[symbol] = _PartialCandle(
                timeframe=tf,
                bucket_epoch=bucket,
                timestamp=ts,
                open=float(candle_5m["open"]),
                high=float(candle_5m["high"]),
                low=float(candle_5m["low"]),
                close=float(candle_5m["close"]),
            )
            return None

        # Same bucket -> update partial
        if current.bucket_epoch == bucket:
            current.update_from_5m(candle_5m)
            return None

        # Bucket changed -> close previous candle, append, then start new partial
        closed_candle = _candle_to_contract_dict(tf, current)
        # Dedup guard: replace if the last entry has the same bucket_epoch.
        # Defends against a duplicate close for a bucket already populated
        # by preload_h4_from_5m_cache at startup.
        if closed_map[symbol] and closed_map[symbol][-1].get("bucket_epoch") == closed_candle.get("bucket_epoch"):
            closed_map[symbol][-1] = closed_candle
        else:
            closed_map[symbol].append(closed_candle)

        # Trim
        if len(closed_map[symbol]) > max_keep:
            closed_map[symbol] = closed_map[symbol][-max_keep:]

        # Start new partial from current 5m
        partial_map[symbol] = _PartialCandle(
            timeframe=tf,
            bucket_epoch=bucket,
            timestamp=ts,
            open=float(candle_5m["open"]),
            high=float(candle_5m["high"]),
            low=float(candle_5m["low"]),
            close=float(candle_5m["close"]),
        )

        return {
            "timeframe": tf,
            "closed_bucket_epoch": int(closed_candle["bucket_epoch"]),
            "closed_timestamp": closed_candle["timestamp"],
            "closed_ohlc": {
                "open": closed_candle["open"],
                "high": closed_candle["high"],
                "low": closed_candle["low"],
                "close": closed_candle["close"],
            },
        }

    def get_state(self, symbol: str) -> Dict[str, Any]:
        """
        Pure-ish introspection (no I/O): returns internal state summary for diagnostics.
        """
        h1_closed  = self._h1_closed.get(symbol, [])
        h4_closed  = self._h4_closed.get(symbol, [])
        d1_closed  = self._d1_closed.get(symbol, [])
        h1_partial = self._h1_partial.get(symbol)
        h4_partial = self._h4_partial.get(symbol)
        d1_partial = self._d1_partial.get(symbol)

        # Include the same minimal H1 anchor fields for diagnostics.
        h1_ema8: Optional[float] = None
        h1_ema21: Optional[float] = None
        h1_price: Optional[float] = None
        h1_anchor_ready = False
        h1_anchor_buy_ok = False
        h1_anchor_sell_ok = False

        try:
            if len(h1_closed) >= 21:
                h1_closes = pd.Series([float(c["close"]) for c in h1_closed], dtype="float64")
                ema8_series = _compute_ema(h1_closes, 8)
                ema21_series = _compute_ema(h1_closes, 21)

                h1_ema8 = float(ema8_series.iloc[-1])
                h1_ema21 = float(ema21_series.iloc[-1])
                h1_price = float(h1_closes.iloc[-1])

                h1_anchor_ready = True
                h1_anchor_buy_ok = bool(
                    h1_ema8 > h1_ema21
                    and h1_price > h1_ema8
                    and h1_price > h1_ema21
                )
                h1_anchor_sell_ok = bool(
                    h1_ema8 < h1_ema21
                    and h1_price < h1_ema8
                    and h1_price < h1_ema21
                )
        except Exception:
            pass

        return {
            "symbol": symbol,
            "h1_closed_count": len(h1_closed),
            "h4_closed_count": len(h4_closed),
            "d1_closed_count": len(d1_closed),
            "last_h1_closed": h1_closed[-1] if h1_closed else None,
            "last_h4_closed": h4_closed[-1] if h4_closed else None,
            "last_d1_closed": d1_closed[-1] if d1_closed else None,
            "h1_partial": _candle_to_contract_dict("H1", h1_partial) if h1_partial else None,
            "h4_partial": _candle_to_contract_dict("H4", h4_partial) if h4_partial else None,
            "d1_partial": _candle_to_contract_dict("D1", d1_partial) if d1_partial else None,
            "h1_ema8": h1_ema8,
            "h1_ema21": h1_ema21,
            "h1_price": h1_price,
            "h1_anchor_ready": h1_anchor_ready,
            "h1_anchor_buy_ok": h1_anchor_buy_ok,
            "h1_anchor_sell_ok": h1_anchor_sell_ok,
            "config": {
                "ema_fast": self.ema_fast,
                "ema_slow": self.ema_slow,
                "neutral_buffer_points": self.neutral_buffer_points,
                "max_h1_candles": self.max_h1_candles,
                "max_h4_candles": self.max_h4_candles,
                "max_d1_candles": self.max_d1_candles,
            },
        }

    def preload_from_5m_cache(self, symbol: str, epic: str, df) -> Dict[str, Any]:
        """
        Replay historical 5M candles from cache DataFrame to pre-populate
        H1, H4, D1 closed candle lists.  Called once at startup before streaming.

        Returns summary dict with counts of H1/H4/D1 candles built.
        Never raises — logs warning on failure and returns zeroed summary.
        """
        import logging as _logging
        _log = _logging.getLogger("AutoBot")

        sym = str(symbol).upper()
        empty = {"symbol": sym, "h1_candles": 0, "h4_candles": 0, "d1_candles": 0}

        try:
            if df is None or len(df) == 0:
                return empty

            # Initialise per-symbol storage
            self._h1_closed.setdefault(sym, [])
            self._h4_closed.setdefault(sym, [])
            self._d1_closed.setdefault(sym, [])
            if sym not in self._h1_partial:
                self._h1_partial[sym] = None
            if sym not in self._h4_partial:
                self._h4_partial[sym] = None
            if sym not in self._d1_partial:
                self._d1_partial[sym] = None

            # Determine timestamp column name
            _ts_col = "timestamp" if "timestamp" in df.columns else "time"

            # Sort ascending by timestamp
            df_sorted = df.sort_values(_ts_col).reset_index(drop=True)

            for _, row in df_sorted.iterrows():
                try:
                    ts_raw = row[_ts_col]
                    # Parse timestamp to epoch int
                    ts_epoch: int
                    if isinstance(ts_raw, (int, float)):
                        ts_epoch = int(ts_raw)
                    else:
                        ts_epoch = int(pd.Timestamp(str(ts_raw)).timestamp())

                    # 5M bucket floor
                    bucket_epoch = (ts_epoch // 300) * 300

                    candle_5m = {
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                    }

                    self._update_timeframe(sym, candle_5m, bucket_epoch, tf="H1", seconds=3600)
                    self._update_timeframe(sym, candle_5m, bucket_epoch, tf="H4", seconds=14400)
                    self._update_timeframe(sym, candle_5m, bucket_epoch, tf="D1", seconds=86400)
                except Exception:
                    continue

            # Compute initial bias for all three timeframes (populates internal state)
            h1_bias, _ = _compute_bias_from_candles(
                self._h1_closed[sym],
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                neutral_buffer_points=self.neutral_buffer_points,
            )
            h4_bias, _ = _compute_bias_from_candles(
                self._h4_closed[sym],
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                neutral_buffer_points=self.neutral_buffer_points,
            )
            d1_bias, _ = _compute_bias_from_candles(
                self._d1_closed[sym],
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                neutral_buffer_points=self.neutral_buffer_points,
            )

            summary = {
                "symbol": sym,
                "h1_candles": len(self._h1_closed[sym]),
                "h4_candles": len(self._h4_closed[sym]),
                "d1_candles": len(self._d1_closed[sym]),
                "h1_bias": h1_bias,
                "h4_bias": h4_bias,
                "d1_bias": d1_bias,
            }
            return summary

        except Exception as e:
            _log.warning(f"[HTF-PRELOAD] {sym} preload failed: {type(e).__name__}: {e}")
            return empty

    def preload_h4_from_5m_cache(
        self, symbol: str, epic: str, df,
        *, expected_bars_per_h4: int = 48, max_h4_bars: int = 40,
    ) -> Dict[str, Any]:
        """Aggregate ONLY H4 bars from a cached 5M DataFrame, with a strict
        completeness check. Used at startup when H1+D1 are restored from the
        HTF JSON cache (skipping the existing all-TF preload_from_5m_cache).

        Stricter than the live aggregator: emits an H4 only when all
        `expected_bars_per_h4` 5M bars are present. This silently skips
        weekend-truncated periods (Friday 20:00-24:00 UTC, Sunday 20:00-24:00
        UTC), in-progress periods, and any periods affected by gaps in the
        5M cache. Replaces (does not append to) the existing _h4_closed[sym]
        list.

        Returns dict with keys: symbol, h4_candles_loaded, h4_periods_skipped.
        Never raises; logs warning on failure and returns zeroed counts.
        """
        import logging as _logging
        from collections import OrderedDict
        _log = _logging.getLogger("AutoBot")

        sym = str(symbol).upper()
        empty = {"symbol": sym, "h4_candles_loaded": 0, "h4_periods_skipped": 0}

        try:
            if df is None or len(df) == 0:
                return empty

            self._h4_closed.setdefault(sym, [])
            if sym not in self._h4_partial:
                self._h4_partial[sym] = None

            ts_col = "timestamp" if "timestamp" in df.columns else "time"
            df_sorted = df.sort_values(ts_col).reset_index(drop=True)

            # Group 5M rows by H4 bucket_epoch, preserving chronological order.
            buckets: "OrderedDict[int, list]" = OrderedDict()
            for _, row in df_sorted.iterrows():
                ts_raw = row[ts_col]
                if isinstance(ts_raw, (int, float)):
                    ts_epoch = int(ts_raw)
                else:
                    ts_epoch = int(pd.Timestamp(str(ts_raw)).timestamp())
                bucket_epoch = (ts_epoch // 14400) * 14400
                buckets.setdefault(bucket_epoch, []).append(row)

            built: List[Dict[str, Any]] = []
            skipped = 0
            for bucket_epoch, rows in buckets.items():
                if len(rows) < expected_bars_per_h4:
                    # Weekend boundary, gap, or in-progress period — skip.
                    skipped += 1
                    continue
                ts_dt = _epoch_to_utc_dt(bucket_epoch)
                built.append({
                    "timeframe": "H4",
                    "timestamp": _safe_iso_utc(ts_dt),
                    "bucket_epoch": int(bucket_epoch),
                    "open":  float(rows[0]["open"]),
                    "high":  float(max(float(r["high"]) for r in rows)),
                    "low":   float(min(float(r["low"])  for r in rows)),
                    "close": float(rows[-1]["close"]),
                })

            built = built[-max_h4_bars:]
            self._h4_closed[sym] = built
            return {
                "symbol": sym,
                "h4_candles_loaded": len(built),
                "h4_periods_skipped": skipped,
            }

        except Exception as e:
            _log.warning(
                f"[HTF-PRELOAD] {sym} H4-only preload failed: {type(e).__name__}: {e}"
            )
            return empty

    def preload_from_d1_cache(self, symbol: str, epic: str, df) -> Dict[str, Any]:
        """
        Load pre-built D1 candles directly into _d1_closed without aggregating
        from 5M data.  Called at startup when a D1 cache CSV exists.

        Returns summary dict with D1 candle count and bias.
        """
        import logging as _logging
        _log = _logging.getLogger("AutoBot")

        sym = str(symbol).upper()
        empty: Dict[str, Any] = {"symbol": sym, "d1_candles": 0, "d1_bias": "NEUTRAL"}

        try:
            if df is None or len(df) == 0:
                return empty

            # Clear any D1 candles aggregated from 5M data — native D1 replaces them
            self._d1_closed[sym] = []

            ts_col = "timestamp" if "timestamp" in df.columns else "time"
            df_sorted = df.sort_values(ts_col).reset_index(drop=True)

            for _, row in df_sorted.iterrows():
                ts_raw = row[ts_col]
                if isinstance(ts_raw, (int, float)):
                    ts_epoch = int(ts_raw)
                else:
                    ts_epoch = int(pd.Timestamp(str(ts_raw)).timestamp())
                bucket_epoch = (ts_epoch // 86400) * 86400

                candle: Dict[str, Any] = {
                    "timeframe": "D1",
                    "timestamp": _safe_iso_utc(_epoch_to_utc_dt(bucket_epoch)),
                    "bucket_epoch": bucket_epoch,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
                self._d1_closed[sym].append(candle)

            # Trim to max
            if len(self._d1_closed[sym]) > self.max_d1_candles:
                self._d1_closed[sym] = self._d1_closed[sym][-self.max_d1_candles:]

            d1_bias, _ = _compute_bias_from_candles(
                self._d1_closed[sym],
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                neutral_buffer_points=self.neutral_buffer_points,
            )

            return {"symbol": sym, "d1_candles": len(self._d1_closed[sym]), "d1_bias": d1_bias}

        except Exception as e:
            _log.warning(f"[HTF-PRELOAD] {sym} D1 cache preload failed: {type(e).__name__}: {e}")
            return empty

    def inject_htf_candles(
        self,
        symbol: str,
        tf: str,
        candles: List[Dict[str, Any]],
    ) -> int:
        """
        Inject pre-built HTF candle dicts directly into _closed lists.
        Used by htf_cache to restore cached candles without replaying 5M data.

        No I/O — caller is responsible for reading from disk.

        Returns number of candles injected.
        """
        sym = str(symbol).upper()
        if tf == "H1":
            self._h1_closed.setdefault(sym, [])
            self._h1_closed[sym] = list(candles)[-self.max_h1_candles:]
            if sym not in self._h1_partial:
                self._h1_partial[sym] = None
            return len(self._h1_closed[sym])
        elif tf == "H4":
            self._h4_closed.setdefault(sym, [])
            self._h4_closed[sym] = list(candles)[-self.max_h4_candles:]
            if sym not in self._h4_partial:
                self._h4_partial[sym] = None
            return len(self._h4_closed[sym])
        elif tf == "D1":
            self._d1_closed.setdefault(sym, [])
            self._d1_closed[sym] = list(candles)[-self.max_d1_candles:]
            if sym not in self._d1_partial:
                self._d1_partial[sym] = None
            return len(self._d1_closed[sym])
        else:
            raise ValueError(f"Unknown timeframe: {tf}")

    def get_closed_candles(self, symbol: str, tf: str) -> List[Dict[str, Any]]:
        """
        Return a copy of the closed candle list for a given symbol/timeframe.
        No I/O — caller can persist the result.
        """
        sym = str(symbol).upper()
        if tf == "H1":
            return list(self._h1_closed.get(sym, []))
        elif tf == "H4":
            return list(self._h4_closed.get(sym, []))
        elif tf == "D1":
            return list(self._d1_closed.get(sym, []))
        else:
            raise ValueError(f"Unknown timeframe: {tf}")
