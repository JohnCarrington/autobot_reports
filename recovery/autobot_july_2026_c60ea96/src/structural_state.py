#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
structural_state.py — Phase 5 of the briefing redesign.

Pure deterministic Python computation of:

  * News context (today / yesterday / tomorrow high-impact events for a pair),
    plus a day-classification: pre_news_drift / news_day /
    post_news_consolidation / clear_day.

  * HTF structural state (D1 trend / position / ATR-state, H4 trend,
    weekly position) derived from the 5m candle CSVs at
    /opt/tradingbot/data/candles/<SYMBOL>/<YYYY-MM-DD>.csv.

The single public entry point is ``get_structural_state(symbol)`` which
returns a JSON-serialisable dict the briefing prompt (Phase 6) will read.
No LLM input is involved — every classification rule is explicit and
testable.

This module is import-side-effect-free: it does not start threads, open
sockets, or call `news_calendar.prefetch()`. Callers (the briefing path)
must already have the news calendar primed.
"""

from __future__ import annotations

import csv
import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import news_calendar  # type: ignore[import]

logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CANDLE_ROOT = Path("/opt/tradingbot/data/candles")

# Mirrors the mapping in morning_briefing.py — duplicated here so this module
# stays standalone (no morning_briefing import).
SYMBOL_CURRENCIES: Dict[str, List[str]] = {
    "GBPUSD": ["GBP", "USD"],
    "EURUSD": ["EUR", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCAD": ["USD", "CAD"],
    "GBPJPY": ["GBP", "JPY"],
}

# news_calendar uses "High" (capitalised) for HIGH-impact events.
_HIGH_IMPACT_LABEL = "High"

# Window thresholds (hours) used by the news classification rule.
_PRE_NEWS_WINDOW_HOURS  = 4.0  # event in (0, 4h] → pre_news_drift
_NEWS_DAY_WINDOW_HOURS  = 1.0  # event in (-1h, +1h] → news_day
_POST_NEWS_THRESHOLD_H  = 2.0  # event >= 2h in past → post_news_consolidation
                                # (otherwise still news_day fallout)

# HTF lookback / threshold tuning.
_D1_LOOKBACK_DAYS              = 30
_D1_TREND_LAST_N               = 5
_D1_TREND_MIN_DIRECTIONAL      = 3   # of last 5 closes
_D1_SMA_PERIOD                 = 20
_D1_RANGE_LOOKBACK             = 20
_D1_ATR_PERIOD                 = 14
_D1_ATR_MEDIAN_LOOKBACK_DAYS   = 30
_D1_ATR_EXPANDING_RATIO        = 1.20
_D1_ATR_CONTRACTING_RATIO      = 0.80
_D1_RANGE_VS_ATR_THRESHOLD     = 0.5  # |close - sma20| < 0.5*atr → range

_H4_LOOKBACK_BARS              = 60
_H4_TREND_LAST_N               = 10
_H4_TREND_MIN_DIRECTIONAL      = 6   # of last 10 closes (60% threshold)
_H4_SMA_PERIOD                 = 20

_WEEKLY_LOOKBACK_WEEKS         = 13
_POSITION_UPPER_THRESH         = 2.0 / 3.0  # > 2/3 of range = upper_third
_POSITION_LOWER_THRESH         = 1.0 / 3.0  # < 1/3 of range = lower_third


# ─────────────────────────────────────────────────────────────────────────────
# News context
# ─────────────────────────────────────────────────────────────────────────────

def _events_on_date(
    date_str: str,
    currencies: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Return all HIGH-impact events on a given UTC date for the given
    currencies. Reads from ``news_calendar._all_events`` after triggering a
    refresh. Empty list on any error / before cache populated.

    Each entry has ``time``, ``currency``, ``event_name``, ``impact``.
    """
    try:
        news_calendar._refresh_if_needed()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.debug("[structural_state] refresh skipped: %s", exc)

    try:
        with news_calendar._lock:  # type: ignore[attr-defined]
            snap = list(news_calendar._all_events)  # type: ignore[attr-defined]
    except Exception:
        snap = []

    targets = {str(c).upper() for c in (currencies or [])} or None
    out: List[Dict[str, str]] = []
    for e in snap:
        if e.get("date_utc") != date_str:
            continue
        if e.get("impact") != _HIGH_IMPACT_LABEL:
            continue
        if targets is not None and e.get("currency") not in targets:
            continue
        out.append({
            "time":       str(e.get("time") or ""),
            "currency":   str(e.get("currency") or ""),
            "event_name": str(e.get("event_name") or ""),
            "impact":     str(e.get("impact") or ""),
        })
    out.sort(key=lambda x: x["time"])
    return out


def _parse_event_dt(date_str: str, time_str: str) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD' + 'HH:MM' into a UTC datetime."""
    try:
        hh, mm = time_str.split(":")
        return datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=int(hh), minute=int(mm), second=0, microsecond=0,
            tzinfo=timezone.utc,
        )
    except (ValueError, TypeError):
        return None


def _classify_news(
    today_events: List[Dict[str, str]],
    yesterday_events: List[Dict[str, str]],
    tomorrow_events: List[Dict[str, str]],
    pair_currencies: List[str],
    now_utc: datetime,
    today_str: str,
    yesterday_str: str,
    tomorrow_str: str,
) -> Tuple[str, str]:
    """Apply the classification rules. Returns (classification, reason)."""
    pair_set = {c.upper() for c in pair_currencies}

    def affects(events: List[Dict[str, str]]) -> List[Dict[str, str]]:
        return [e for e in events if e.get("currency", "").upper() in pair_set]

    today_affecting     = affects(today_events)
    yesterday_affecting = affects(yesterday_events)
    tomorrow_affecting  = affects(tomorrow_events)

    if today_affecting:
        # Find the next, the closest-past, and the most recent event
        today_dts: List[Tuple[datetime, Dict[str, str]]] = []
        for e in today_affecting:
            dt = _parse_event_dt(today_str, e["time"])
            if dt is not None:
                today_dts.append((dt, e))
        if today_dts:
            future = [(dt, e) for dt, e in today_dts if dt >= now_utc]
            past   = [(dt, e) for dt, e in today_dts if dt <  now_utc]

            # ±1h window of any of today's events → news_day
            within_window = [
                (dt, e) for dt, e in today_dts
                if abs((dt - now_utc).total_seconds()) <= _NEWS_DAY_WINDOW_HOURS * 3600
            ]
            if within_window:
                ev = within_window[0][1]
                return "news_day", f"Within ±1h of {ev['event_name']}"

            if future:
                next_dt, next_e = min(future, key=lambda x: x[0])
                hours_to = (next_dt - now_utc).total_seconds() / 3600.0
                if 0 < hours_to <= _PRE_NEWS_WINDOW_HOURS:
                    return (
                        "pre_news_drift",
                        f"High-impact {next_e['currency']} {next_e['event_name']} in {hours_to:.1f}h"
                    )

            if past and not future:
                last_dt, last_e = max(past, key=lambda x: x[0])
                hours_since = (now_utc - last_dt).total_seconds() / 3600.0
                if hours_since >= _POST_NEWS_THRESHOLD_H:
                    return (
                        "post_news_consolidation",
                        f"Post-{last_e['event_name']}, {hours_since:.1f}h elapsed"
                    )
                return (
                    "news_day",
                    f"Within {_POST_NEWS_THRESHOLD_H:g}h of {last_e['event_name']}"
                )

            # Future event but >4h away — fall through to look at
            # yesterday/tomorrow before deciding.

    if yesterday_affecting:
        ev = yesterday_affecting[0]
        return (
            "post_news_consolidation",
            f"Yesterday's {ev['currency']} {ev['event_name']}"
        )

    if tomorrow_affecting:
        ev = tomorrow_affecting[0]
        return (
            "pre_news_drift",
            f"Tomorrow's {ev['currency']} {ev['event_name']}"
        )

    if today_affecting:
        # Reached only when today has events but neither in-window, near
        # past, nor near future (i.e. far-future). Treat as pre-news drift.
        next_e = today_affecting[0]
        return (
            "pre_news_drift",
            f"Today's later {next_e['currency']} {next_e['event_name']}"
        )

    return "clear_day", "No nearby high-impact events"


def get_news_context(
    symbol: str,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return the structured news context object for *symbol*.

    Reads today / yesterday / tomorrow's HIGH-impact events from the
    news_calendar cache (no fetch is forced beyond the calendar's own
    once-per-day refresh). Filters to events whose currency is in
    SYMBOL_CURRENCIES[symbol].
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    sym = symbol.upper()
    pair_currencies = SYMBOL_CURRENCIES.get(sym, [])

    today_d     = now_utc.date()
    yesterday_d = today_d - timedelta(days=1)
    tomorrow_d  = today_d + timedelta(days=1)
    today_str     = today_d.isoformat()
    yesterday_str = yesterday_d.isoformat()
    tomorrow_str  = tomorrow_d.isoformat()

    # Pull all HIGH events for each day (not yet pair-filtered) so the
    # output reports the full schedule plus the pair-affected flag.
    today_all     = _events_on_date(today_str)
    yesterday_all = _events_on_date(yesterday_str)
    tomorrow_all  = _events_on_date(tomorrow_str)

    pair_set = {c.upper() for c in pair_currencies}

    def _shape_day(events: List[Dict[str, str]]) -> Dict[str, Any]:
        """Build the per-day output block."""
        affecting = [e for e in events if e.get("currency", "").upper() in pair_set]
        first_event_time: Optional[str] = None
        if affecting:
            first_event_time = affecting[0]["time"]
        return {
            "has_high_impact":  bool(events),
            "events":           events,
            "affects_pair":     bool(affecting),
            "first_event_time": first_event_time,
        }

    today_block     = _shape_day(today_all)
    tomorrow_block  = _shape_day(tomorrow_all)
    yesterday_block = {
        "had_high_impact":  bool(yesterday_all),
        "events":           yesterday_all,
        "affected_pair":    any(
            e.get("currency", "").upper() in pair_set for e in yesterday_all
        ),
    }

    classification, reason = _classify_news(
        today_all, yesterday_all, tomorrow_all,
        pair_currencies, now_utc,
        today_str, yesterday_str, tomorrow_str,
    )

    return {
        "today":                 today_block,
        "yesterday":             yesterday_block,
        "tomorrow":              tomorrow_block,
        "classification":        classification,
        "classification_reason": reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTF structural analysis
# ─────────────────────────────────────────────────────────────────────────────

def _load_5m_csvs(
    symbol: str,
    cutoff_date: date,
    n_days: int,
) -> List[Dict[str, Path]]:
    """Return the most recent N CSV files for *symbol* whose date is strictly
    before *cutoff_date*. Each entry is {"date": "YYYY-MM-DD", "path": Path}.
    Excludes today's partial CSV — daily aggregates need full days only.
    """
    sym_dir = CANDLE_ROOT / symbol.upper()
    if not sym_dir.exists():
        return []
    cutoff_str = cutoff_date.isoformat()
    out: List[Dict[str, Path]] = []
    for p in sorted(sym_dir.glob("*.csv")):
        # Skip variants like "2026-04-15.csv.tickbuilt"
        if not p.name.endswith(".csv") or "." in p.stem:
            continue
        # File name is YYYY-MM-DD; lex-compare against cutoff
        if p.stem >= cutoff_str:
            continue
        out.append({"date": p.stem, "path": p})
    return out[-n_days:]


def _read_5m_bars(path: Path) -> List[Dict[str, Any]]:
    """Read a single 5m CSV. Returns rows with parsed numerics + datetime."""
    bars: List[Dict[str, Any]] = []
    try:
        with path.open() as fh:
            for row in csv.DictReader(fh):
                ts_raw = (row.get("timestamp") or "").strip()
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    bars.append({
                        "ts":    ts,
                        "open":  float(row["open"]),
                        "high":  float(row["high"]),
                        "low":   float(row["low"]),
                        "close": float(row["close"]),
                    })
                except (KeyError, ValueError, TypeError):
                    continue
    except Exception as exc:
        logger.debug("[structural_state] read failed for %s: %s", path, exc)
    return bars


def _aggregate_to_d1(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One D1 candle per CSV file (one UTC day). Returns chronological list."""
    out: List[Dict[str, Any]] = []
    for fent in files:
        bars = _read_5m_bars(fent["path"])
        if not bars:
            continue
        bars.sort(key=lambda b: b["ts"])
        out.append({
            "date":  fent["date"],
            "open":  bars[0]["open"],
            "high":  max(b["high"] for b in bars),
            "low":   min(b["low"]  for b in bars),
            "close": bars[-1]["close"],
        })
    return out


def _aggregate_to_h4(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """4-hour candles bucketed by ``timestamp.hour // 4`` per UTC day. Six
    H4 bars per day (00, 04, 08, 12, 16, 20). Returns chronological list.
    """
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for fent in files:
        for b in _read_5m_bars(fent["path"]):
            key = (fent["date"], b["ts"].hour // 4)
            buckets.setdefault(key, []).append(b)
    out: List[Dict[str, Any]] = []
    for (d_str, slot), rows in sorted(buckets.items()):
        rows.sort(key=lambda b: b["ts"])
        out.append({
            "ts_start": rows[0]["ts"],
            "open":  rows[0]["open"],
            "high":  max(r["high"] for r in rows),
            "low":   min(r["low"]  for r in rows),
            "close": rows[-1]["close"],
        })
    return out


def _aggregate_to_weekly(d1: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate D1 candles to ISO-weeks (Mon-Sun) for weekly-position math."""
    buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for bar in d1:
        try:
            d = datetime.strptime(bar["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        iso_year, iso_week, _ = d.isocalendar()
        buckets.setdefault((iso_year, iso_week), []).append(bar)
    out: List[Dict[str, Any]] = []
    for key, rows in sorted(buckets.items()):
        rows.sort(key=lambda r: r["date"])
        out.append({
            "iso_year_week": f"{key[0]}-W{key[1]:02d}",
            "open":  rows[0]["open"],
            "high":  max(r["high"] for r in rows),
            "low":   min(r["low"]  for r in rows),
            "close": rows[-1]["close"],
        })
    return out


def _sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _atr(bars: List[Dict[str, Any]], period: int) -> Optional[float]:
    """Simple-mean ATR over the last *period* bars (close enough for the
    expanding/contracting band test we use here; no Wilder smoothing).
    """
    if len(bars) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, len(bars)):
        h, l = bars[i]["high"], bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _atr_series(bars: List[Dict[str, Any]], period: int) -> List[float]:
    """ATR computed on a rolling window — one value per closing bar that
    has at least *period* TRs available. Index aligned with bars[period:].
    """
    if len(bars) < period + 1:
        return []
    trs: List[float] = []
    for i in range(1, len(bars)):
        h, l = bars[i]["high"], bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
    out: List[float] = []
    for end in range(period, len(trs) + 1):
        out.append(sum(trs[end - period:end]) / period)
    return out


# ── Classification rules ────────────────────────────────────────────────────

def _classify_d1_trend(d1: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Apply the D1 trend rule. Returns (label, reason)."""
    if len(d1) < max(_D1_SMA_PERIOD + _D1_TREND_LAST_N, 25):
        return "transitional", "insufficient D1 history"

    closes = [b["close"] for b in d1]
    # Compare each of the last N closes to the close 2 bars prior
    higher = lower = 0
    for i in range(_D1_TREND_LAST_N):
        # idx into closes for the "current" close
        cur_idx = len(closes) - _D1_TREND_LAST_N + i
        if cur_idx - 2 < 0:
            continue
        if closes[cur_idx] > closes[cur_idx - 2]:
            higher += 1
        elif closes[cur_idx] < closes[cur_idx - 2]:
            lower += 1

    sma_now    = _sma(closes,                _D1_SMA_PERIOD)
    sma_before = _sma(closes[:-_D1_TREND_LAST_N], _D1_SMA_PERIOD)
    if sma_now is None or sma_before is None:
        return "transitional", "insufficient D1 history for SMA"
    sma_slope = (sma_now - sma_before) / _D1_TREND_LAST_N

    current = closes[-1]

    if higher >= _D1_TREND_MIN_DIRECTIONAL and current > sma_now and sma_slope > 0:
        return "up", (
            f"5d closes: {higher} higher, price > SMA20, SMA rising"
        )
    if lower >= _D1_TREND_MIN_DIRECTIONAL and current < sma_now and sma_slope < 0:
        return "down", (
            f"5d closes: {lower} lower, price < SMA20, SMA falling"
        )

    atr_20 = _atr(d1[-(_D1_SMA_PERIOD + 1):], _D1_SMA_PERIOD)
    if atr_20 and abs(current - sma_now) < _D1_RANGE_VS_ATR_THRESHOLD * atr_20:
        return "range", (
            f"Price within {_D1_RANGE_VS_ATR_THRESHOLD:g}×ATR20 of SMA20"
        )
    return "transitional", "Mixed signals — neither trending nor ranging cleanly"


def _classify_d1_position(d1: List[Dict[str, Any]]) -> Tuple[str, float]:
    """Position of latest close inside the 20-day high/low range. Returns
    (label, range_pips_unscaled). Pip-scaling is left to callers (IG-scaled
    feeds are 1 point == 1 pip)."""
    if len(d1) < _D1_RANGE_LOOKBACK:
        return "middle", 0.0
    window = d1[-_D1_RANGE_LOOKBACK:]
    high_20 = max(b["high"] for b in window)
    low_20  = min(b["low"]  for b in window)
    rng     = high_20 - low_20
    if rng <= 0:
        return "middle", 0.0
    current = d1[-1]["close"]
    pos = (current - low_20) / rng
    if pos > _POSITION_UPPER_THRESH:
        return "upper_third", rng
    if pos < _POSITION_LOWER_THRESH:
        return "lower_third", rng
    return "middle", rng


def _classify_d1_atr_state(
    d1: List[Dict[str, Any]],
) -> Tuple[str, Optional[float], Optional[float]]:
    """Return (state, atr_14, atr_30d_median).
    state ∈ {"expanding","contracting","stable"}.
    """
    atr_14 = _atr(d1, _D1_ATR_PERIOD)
    if atr_14 is None or len(d1) < _D1_ATR_PERIOD + _D1_ATR_MEDIAN_LOOKBACK_DAYS:
        # Insufficient history — return stable; callers see atr_14 only.
        return "stable", atr_14, None

    series = _atr_series(d1, _D1_ATR_PERIOD)
    if len(series) < _D1_ATR_MEDIAN_LOOKBACK_DAYS:
        return "stable", atr_14, None
    median_30 = statistics.median(series[-_D1_ATR_MEDIAN_LOOKBACK_DAYS:])
    if atr_14 > _D1_ATR_EXPANDING_RATIO * median_30:
        return "expanding", atr_14, median_30
    if atr_14 < _D1_ATR_CONTRACTING_RATIO * median_30:
        return "contracting", atr_14, median_30
    return "stable", atr_14, median_30


def _classify_h4_trend(h4: List[Dict[str, Any]]) -> Tuple[str, str]:
    """H4 trend rule — same shape as D1 but on H4 bars, last 10 closes."""
    if len(h4) < _H4_SMA_PERIOD + _H4_TREND_LAST_N:
        return "range", "insufficient H4 history"
    closes = [b["close"] for b in h4]
    last_n = closes[-_H4_TREND_LAST_N:]
    higher = sum(1 for i in range(1, len(last_n)) if last_n[i] > last_n[i - 1])
    lower  = sum(1 for i in range(1, len(last_n)) if last_n[i] < last_n[i - 1])

    sma_now    = _sma(closes, _H4_SMA_PERIOD)
    sma_before = _sma(closes[:-_H4_TREND_LAST_N], _H4_SMA_PERIOD)
    if sma_now is None or sma_before is None:
        return "range", "insufficient H4 history for SMA"
    sma_slope = (sma_now - sma_before) / _H4_TREND_LAST_N

    current = closes[-1]
    if higher >= _H4_TREND_MIN_DIRECTIONAL and current > sma_now and sma_slope > 0:
        return "up",   f"10b closes: {higher} higher, price > H4 SMA20, slope rising"
    if lower  >= _H4_TREND_MIN_DIRECTIONAL and current < sma_now and sma_slope < 0:
        return "down", f"10b closes: {lower} lower, price < H4 SMA20, slope falling"
    return "range", "No directional H4 alignment"


def _classify_weekly_position(weekly: List[Dict[str, Any]]) -> Tuple[str, int]:
    """Return (label, lookback_weeks_used)."""
    if not weekly:
        return "middle", 0
    look = min(_WEEKLY_LOOKBACK_WEEKS, len(weekly))
    window = weekly[-look:]
    high = max(w["high"] for w in window)
    low  = min(w["low"]  for w in window)
    rng = high - low
    if rng <= 0:
        return "middle", look
    current = weekly[-1]["close"]
    pos = (current - low) / rng
    if pos > _POSITION_UPPER_THRESH:
        return "near_high", look
    if pos < _POSITION_LOWER_THRESH:
        return "near_low",  look
    return "middle", look


def get_htf_structure(
    symbol: str,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the HTF structural state for *symbol*. All values are
    classification labels + reasons; pip-distance values are in IG raw
    units (== pips for FX since POINTS_PER_PIP == 1).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    sym = symbol.upper()
    cutoff = now_utc.date()  # exclude today's partial CSV

    files = _load_5m_csvs(sym, cutoff, _D1_LOOKBACK_DAYS + _D1_ATR_MEDIAN_LOOKBACK_DAYS + 5)
    d1     = _aggregate_to_d1(files)
    h4     = _aggregate_to_h4(files)
    weekly = _aggregate_to_weekly(d1)

    d1_trend_label, d1_trend_reason         = _classify_d1_trend(d1)
    d1_position,    d1_recent_range          = _classify_d1_position(d1)
    d1_atr_state,   atr_14, atr_30_med       = _classify_d1_atr_state(d1)
    h4_trend_label, h4_trend_reason          = _classify_h4_trend(h4)
    weekly_position, weekly_look             = _classify_weekly_position(weekly)

    return {
        "d1_trend":              d1_trend_label,
        "d1_trend_reason":       d1_trend_reason,
        "d1_position":           d1_position,
        "d1_recent_range_pips":  round(d1_recent_range, 1),
        "d1_atr_state":          d1_atr_state,
        "d1_atr_pips":           round(atr_14, 1) if atr_14 is not None else None,
        "d1_atr_30d_median_pips": round(atr_30_med, 1) if atr_30_med is not None else None,
        "h4_trend":              h4_trend_label,
        "h4_trend_reason":       h4_trend_reason,
        "weekly_position":       weekly_position,
        "weekly_lookback_weeks": weekly_look,
        "_meta": {
            "d1_bars": len(d1),
            "h4_bars": len(h4),
            "weekly_bars": len(weekly),
            "cutoff_date": cutoff.isoformat(),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Top-level entry point
# ─────────────────────────────────────────────────────────────────────────────

def get_structural_state(
    symbol: str,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Combine news context and HTF structure into one JSON-serialisable
    object. The Phase 6 wiring will pass this into the briefing prompt.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    return {
        "symbol":       symbol.upper(),
        "computed_at":  now_utc.isoformat(),
        "news_context": get_news_context(symbol, now_utc),
        "htf_structure": get_htf_structure(symbol, now_utc),
    }


__all__ = [
    "SYMBOL_CURRENCIES",
    "get_news_context",
    "get_htf_structure",
    "get_structural_state",
]
