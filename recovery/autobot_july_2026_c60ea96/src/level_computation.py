#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
level_computation.py — Phase 7 of the briefing redesign.

Deterministic, rule-based computation of ranked price levels. Replaces the
model-invented `levels` array with a Python module that:

  1. Gathers raw candidate levels from explicit categories:
       mechanical extremes (prev day/week/5d/20d high/low/close),
       session highs/lows (Asian, London),
       swing points (H1 24h pivots ≥10p, H4 5d pivots ≥20p),
       round numbers (multiples of 50p within ±150p of current),
       indicator levels (D1 EMA 20, H4 EMA 50/200, weekly mid).

  2. Coalesces candidates within ``LEVEL_CONFLUENCE_TOLERANCE_PIPS`` (5p)
     into clusters; the cluster price is the higher-priority category's
     value.

  3. Ranks clusters by ``(-confluence_count, category_priority)`` and
     enforces Phase 1's 15p min-separation.

  4. Emits ``ComputedLevel`` objects matching the Phase 1 schema:
     rank / price / type / role / confluence / confluence_count /
     justification / strength.

Public API:
  get_ranked_levels(symbol, now_utc=None) -> Tuple[List[ComputedLevel], dict]

The dict is a ``meta`` audit object (counts of categories gathered, files
read, undercount flag, etc.) — useful for logging and the Phase 8 prompt.

This module imports ``structural_state`` for its 5m-CSV loading and
D1/H4/weekly aggregation helpers so Phase 5 and Phase 7 stay consistent.
No live consumer imports this yet; Phase 8 will wire it in.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import structural_state as ss  # type: ignore[import]

logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────────────

LEVEL_CONFLUENCE_TOLERANCE_PIPS  = 5.0
MIN_SEPARATION_PIPS              = 15.0
ROUND_NUMBER_RANGE_PIPS          = 150.0
ROUND_NUMBER_STEP_PIPS           = 50.0    # x.xx00 / x.xx50 boundary
LEVELS_MIN_COUNT                 = 4
LEVELS_MAX_COUNT                 = 6
TYPE_PIVOT_TOLERANCE_PIPS        = 5.0    # |price - current| ≤ 5p → PIVOT

# Defensive outlier filter for corrupt-feed glitches. Real FX moves over a
# 30-day window rarely exceed 5% of price; 10% is a generous cap that
# rejects the kind of cross-symbol contamination we've seen on the box
# (e.g. a stray 13500-scale bar appearing in EURUSD H4 aggregates).
# Filtered candidates are reported in meta["outliers_dropped"].
OUTLIER_MAX_DEVIATION_RATIO      = 0.10

# Lookbacks
SWING_H1_LOOKBACK_BARS           = 24
SWING_H1_REVERSAL_PIPS           = 10.0
SWING_H4_LOOKBACK_BARS           = 30
SWING_H4_REVERSAL_PIPS           = 20.0

# Daily/weekly windows
LOOKBACK_DAYS_FOR_D1             = 30   # for 20D high/low + EMA20 etc.

# Asian session window: 22:00 prev day → 06:45 today (UTC). When the
# CSV doesn't extend to 22:00 on the prior day, we use whatever bars
# we have inside the window.
ASIAN_START_HOUR_PREV            = 22
ASIAN_END_HOUR                   = 6
ASIAN_END_MIN                    = 45

# London session window: 06:45 → 12:25 UTC today
LONDON_START_HOUR                = 6
LONDON_START_MIN                 = 45
LONDON_END_HOUR                  = 12
LONDON_END_MIN                   = 25


# Category importance for tie-breaking. Lower index == higher priority.
# This list also drives anchor-price selection inside a cluster: when
# multiple categories cluster together, the cluster's reported price is
# the highest-priority member's value.
_CATEGORY_PRIORITY: List[str] = [
    "PREV_DAY_HIGH",  "PREV_DAY_LOW",
    "20D_HIGH",       "20D_LOW",
    "5D_HIGH",        "5D_LOW",
    "H4_SWING_HIGH",  "H4_SWING_LOW",
    "PREV_DAY_CLOSE",
    "PREV_WEEK_HIGH", "PREV_WEEK_LOW",
    "WEEK_HIGH",      "WEEK_LOW",
    "ASIAN_HIGH",     "ASIAN_LOW",
    "LONDON_HIGH",    "LONDON_LOW",
    "H1_SWING_HIGH",  "H1_SWING_LOW",
    "ROUND_NUMBER",
    "WEEKLY_MID",
    "D1_EMA_20", "H4_EMA_50", "H4_EMA_200",
]
_CATEGORY_RANK: Dict[str, int] = {c: i for i, c in enumerate(_CATEGORY_PRIORITY)}

# Phase 1 confluence vocabulary that consumers/validator will accept.
# All emitted confluence tags are restricted to this set; non-vocab
# categories are dropped from the per-level confluence list (they still
# count toward confluence_count for clustering, but aren't reported).
_PHASE1_VOCAB: set = {
    "PREV_DAY_HIGH", "PREV_DAY_LOW", "PREV_DAY_CLOSE",
    "WEEK_HIGH", "WEEK_LOW", "PREV_WEEK_HIGH", "PREV_WEEK_LOW",
    "ASIAN_HIGH", "ASIAN_LOW",
    "SWING_HIGH", "SWING_LOW",
    "BB_UPPER", "BB_LOWER",
    "EMA_50", "EMA_200",
    "ROUND_NUMBER", "DAILY_PIVOT", "VWAP",
}

# Internal-category → Phase-1-vocab tag mapping (for the emitted
# `confluence` list). Categories that don't have a Phase-1-vocab match
# are mapped to None and excluded from the emitted list.
_CATEGORY_TO_VOCAB_TAG: Dict[str, Optional[str]] = {
    "PREV_DAY_HIGH":   "PREV_DAY_HIGH",
    "PREV_DAY_LOW":    "PREV_DAY_LOW",
    "PREV_DAY_CLOSE":  "PREV_DAY_CLOSE",
    "PREV_WEEK_HIGH":  "PREV_WEEK_HIGH",
    "PREV_WEEK_LOW":   "PREV_WEEK_LOW",
    "WEEK_HIGH":       "WEEK_HIGH",
    "WEEK_LOW":        "WEEK_LOW",
    "5D_HIGH":         "SWING_HIGH",  # bucket as swing high
    "5D_LOW":          "SWING_LOW",
    "20D_HIGH":        "SWING_HIGH",
    "20D_LOW":         "SWING_LOW",
    "ASIAN_HIGH":      "ASIAN_HIGH",
    "ASIAN_LOW":       "ASIAN_LOW",
    "LONDON_HIGH":     "SWING_HIGH",
    "LONDON_LOW":      "SWING_LOW",
    "H1_SWING_HIGH":   "SWING_HIGH",
    "H1_SWING_LOW":    "SWING_LOW",
    "H4_SWING_HIGH":   "SWING_HIGH",
    "H4_SWING_LOW":    "SWING_LOW",
    "ROUND_NUMBER":    "ROUND_NUMBER",
    "WEEKLY_MID":      "DAILY_PIVOT",  # bucket as pivot
    "D1_EMA_20":       "EMA_50",       # closest vocab anchor
    "H4_EMA_50":       "EMA_50",
    "H4_EMA_200":      "EMA_200",
}

# Human labels for justification text.
_CATEGORY_LABEL: Dict[str, str] = {
    "PREV_DAY_HIGH":   "yesterday's high",
    "PREV_DAY_LOW":    "yesterday's low",
    "PREV_DAY_CLOSE":  "yesterday's close",
    "PREV_WEEK_HIGH":  "last week's high",
    "PREV_WEEK_LOW":   "last week's low",
    "WEEK_HIGH":       "this week's high",
    "WEEK_LOW":        "this week's low",
    "5D_HIGH":         "5-day high",
    "5D_LOW":          "5-day low",
    "20D_HIGH":        "20-day high",
    "20D_LOW":         "20-day low",
    "ASIAN_HIGH":      "Asian high",
    "ASIAN_LOW":       "Asian low",
    "LONDON_HIGH":     "London high",
    "LONDON_LOW":      "London low",
    "H1_SWING_HIGH":   "H1 swing high",
    "H1_SWING_LOW":    "H1 swing low",
    "H4_SWING_HIGH":   "H4 swing high",
    "H4_SWING_LOW":    "H4 swing low",
    "ROUND_NUMBER":    "round number",
    "WEEKLY_MID":      "weekly mid",
    "D1_EMA_20":       "D1 EMA 20",
    "H4_EMA_50":       "H4 EMA 50",
    "H4_EMA_200":      "H4 EMA 200",
}


# ─────────────────────────────────────────────────────────────────────────────
# Output dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ComputedLevel:
    rank:             int
    price:            float
    type:             str        # RESISTANCE | SUPPORT | PIVOT
    role:             str        # primary | secondary | extension
    confluence:       List[str]  # Phase-1-vocab tags only (deduped)
    confluence_count: int        # raw count of categories in the cluster
    justification:    str        # ≤ 30 words
    strength:         str        # HIGH | MEDIUM | LOW

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rank":             self.rank,
            "price":            self.price,
            "type":             self.type,
            "role":             self.role,
            "confluence":       list(self.confluence),
            "confluence_count": self.confluence_count,
            "justification":    self.justification,
            "strength":         self.strength,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Indicator / swing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ema(values: List[float], period: int) -> Optional[float]:
    """Standard EMA. Seeds with SMA over the first `period` values; then
    applies (price * k + prev * (1-k)) where k = 2/(period+1). Returns
    the latest value, or None when there's not enough history.
    """
    if not values or len(values) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e


def _swing_points(
    bars: List[Dict[str, Any]],
    lookback_n: int,
    min_reversal_pips: float,
) -> Tuple[List[float], List[float]]:
    """Return (swing_highs, swing_lows) detected over the last `lookback_n`
    bars. A pivot is bar i with bars[i].high strictly greater than
    bars[i±1].high AND bars[i±2].high (mirror for lows). Pivots within
    ±2 of the array edges are skipped.

    The reversal filter requires that after a swing high prints, price
    must drop by at least `min_reversal_pips` (vs the swing's high)
    before another swing high is accepted. This filters micro-pivots in
    a slow grind.
    """
    if len(bars) < 5:
        return [], []
    window = bars[-lookback_n:]
    highs: List[float] = []
    lows:  List[float] = []
    last_swing_high_price: Optional[float] = None
    last_swing_low_price:  Optional[float] = None
    for i in range(2, len(window) - 2):
        h = float(window[i]["high"])
        l = float(window[i]["low"])
        is_high = (
            h > float(window[i - 1]["high"])
            and h > float(window[i - 2]["high"])
            and h > float(window[i + 1]["high"])
            and h > float(window[i + 2]["high"])
        )
        is_low = (
            l < float(window[i - 1]["low"])
            and l < float(window[i - 2]["low"])
            and l < float(window[i + 1]["low"])
            and l < float(window[i + 2]["low"])
        )
        if is_high:
            if last_swing_high_price is None or (h - last_swing_high_price) > min_reversal_pips or (last_swing_high_price - h) > min_reversal_pips:
                # Need the intervening reversal: price must have dropped
                # by min_reversal_pips between this and the last accepted
                # swing high. Use min low between them.
                if last_swing_high_price is None:
                    highs.append(h)
                    last_swing_high_price = h
                else:
                    # find min low between previous swing high index
                    # and current — but we don't track index. Approximate
                    # by checking that current high differs from last by
                    # >= min_reversal_pips OR there's an intervening swing
                    # low whose low is at least min_reversal_pips below.
                    intervening_lows = [float(b["low"]) for b in window[max(0, i - lookback_n):i]]
                    if intervening_lows and last_swing_high_price - min(intervening_lows) >= min_reversal_pips:
                        highs.append(h)
                        last_swing_high_price = h
                    elif abs(h - last_swing_high_price) >= min_reversal_pips:
                        highs.append(h)
                        last_swing_high_price = h
        if is_low:
            if last_swing_low_price is None:
                lows.append(l)
                last_swing_low_price = l
            else:
                intervening_highs = [float(b["high"]) for b in window[max(0, i - lookback_n):i]]
                if intervening_highs and max(intervening_highs) - last_swing_low_price >= min_reversal_pips:
                    lows.append(l)
                    last_swing_low_price = l
                elif abs(l - last_swing_low_price) >= min_reversal_pips:
                    lows.append(l)
                    last_swing_low_price = l
    return highs, lows


def _round_numbers_near(
    current: float,
    range_pips: float,
    step_pips: float,
) -> List[float]:
    """All multiples of `step_pips` within ±`range_pips` of `current`,
    rounded to the step grid. Inclusive endpoints."""
    if step_pips <= 0:
        return []
    lo = current - range_pips
    hi = current + range_pips
    first = math.ceil(lo / step_pips) * step_pips
    out: List[float] = []
    x = first
    while x <= hi:
        out.append(round(x, 5))
        x += step_pips
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Session window readers (Asian, London)
# ─────────────────────────────────────────────────────────────────────────────

def _read_5m_window(
    symbol: str,
    start_utc: datetime,
    end_utc:   datetime,
) -> List[Dict[str, Any]]:
    """Read 5m bars from /opt/tradingbot/data/candles/<sym>/<date>.csv
    files spanning the given UTC window. Returns chronological list."""
    sym_dir = ss.CANDLE_ROOT / symbol.upper()
    if not sym_dir.exists():
        return []
    out: List[Dict[str, Any]] = []
    d = start_utc.date()
    end_d = end_utc.date()
    while d <= end_d:
        f = sym_dir / f"{d.isoformat()}.csv"
        if f.exists():
            for b in ss._read_5m_bars(f):  # type: ignore[attr-defined]
                if start_utc <= b["ts"] <= end_utc:
                    out.append(b)
        d += timedelta(days=1)
    out.sort(key=lambda b: b["ts"])
    return out


def _asian_high_low(symbol: str, now_utc: datetime) -> Tuple[Optional[float], Optional[float]]:
    """22:00 prev-day → 06:45 today. Returns (high, low) or (None, None)
    when no bars are available (e.g. CSVs only cover 00:00–21:00)."""
    today  = now_utc.date()
    yest   = today - timedelta(days=1)
    start  = datetime.combine(yest,  dt_time(ASIAN_START_HOUR_PREV, 0), tzinfo=timezone.utc)
    end    = datetime.combine(today, dt_time(ASIAN_END_HOUR, ASIAN_END_MIN), tzinfo=timezone.utc)
    bars   = _read_5m_window(symbol, start, end)
    if not bars:
        return None, None
    return max(b["high"] for b in bars), min(b["low"] for b in bars)


def _london_high_low(symbol: str, now_utc: datetime) -> Tuple[Optional[float], Optional[float]]:
    """06:45 → 12:25 UTC today. Returns (high, low) or (None, None) when
    today's session bars aren't yet available."""
    today  = now_utc.date()
    start  = datetime.combine(today, dt_time(LONDON_START_HOUR, LONDON_START_MIN), tzinfo=timezone.utc)
    end    = datetime.combine(today, dt_time(LONDON_END_HOUR,   LONDON_END_MIN),   tzinfo=timezone.utc)
    bars   = _read_5m_window(symbol, start, end)
    if not bars:
        return None, None
    return max(b["high"] for b in bars), min(b["low"] for b in bars)


# ─────────────────────────────────────────────────────────────────────────────
# H1 aggregation (we need a 1h view; structural_state stops at H4)
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_to_h1(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """1-hour candles bucketed by (date, hour) UTC. Returns chronological list."""
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for fent in files:
        for b in ss._read_5m_bars(fent["path"]):  # type: ignore[attr-defined]
            buckets.setdefault((fent["date"], b["ts"].hour), []).append(b)
    out: List[Dict[str, Any]] = []
    for (_, _), rows in sorted(buckets.items()):
        rows.sort(key=lambda b: b["ts"])
        out.append({
            "ts_start": rows[0]["ts"],
            "open":     rows[0]["open"],
            "high":     max(r["high"] for r in rows),
            "low":      min(r["low"]  for r in rows),
            "close":    rows[-1]["close"],
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Category gathering
# ─────────────────────────────────────────────────────────────────────────────

def _gather_categories(
    symbol: str,
    now_utc: datetime,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Compute every {category: price} we can. Returns (categories, meta).

    Categories with insufficient data are simply absent from the dict.
    Multi-value categories like swing highs/lows produce multiple entries
    suffixed with #1/#2/...
    """
    sym = symbol.upper()
    today = now_utc.date()
    cats: Dict[str, float] = {}
    meta: Dict[str, Any]  = {"missing": []}

    # Daily file load — exclude today (partial day)
    files = ss._load_5m_csvs(sym, today, LOOKBACK_DAYS_FOR_D1 + 5)  # type: ignore[attr-defined]
    d1     = ss._aggregate_to_d1(files)      # type: ignore[attr-defined]
    h4     = ss._aggregate_to_h4(files)      # type: ignore[attr-defined]
    weekly = ss._aggregate_to_weekly(d1)     # type: ignore[attr-defined]
    h1     = _aggregate_to_h1(files)
    meta["d1_bars"]     = len(d1)
    meta["h4_bars"]     = len(h4)
    meta["h1_bars"]     = len(h1)
    meta["weekly_bars"] = len(weekly)

    # Current price: latest closed 5m close from today's CSV if it exists,
    # else latest closed D1 close.
    today_csv = ss.CANDLE_ROOT / sym / f"{today.isoformat()}.csv"
    current_price: Optional[float] = None
    if today_csv.exists():
        bars_today = ss._read_5m_bars(today_csv)  # type: ignore[attr-defined]
        bars_today = [b for b in bars_today if b["ts"] <= now_utc]
        if bars_today:
            current_price = bars_today[-1]["close"]
    if current_price is None and d1:
        current_price = d1[-1]["close"]
    meta["current_price"] = current_price

    # Mechanical extremes
    if d1:
        cats["PREV_DAY_HIGH"]  = d1[-1]["high"]
        cats["PREV_DAY_LOW"]   = d1[-1]["low"]
        cats["PREV_DAY_CLOSE"] = d1[-1]["close"]
    if len(d1) >= 5:
        last5 = d1[-5:]
        cats["5D_HIGH"]  = max(b["high"] for b in last5)
        cats["5D_LOW"]   = min(b["low"]  for b in last5)
    if len(d1) >= 20:
        last20 = d1[-20:]
        cats["20D_HIGH"] = max(b["high"] for b in last20)
        cats["20D_LOW"]  = min(b["low"]  for b in last20)
    if len(weekly) >= 1:
        cw = weekly[-1]
        cats["WEEK_HIGH"] = cw["high"]
        cats["WEEK_LOW"]  = cw["low"]
        cats["WEEKLY_MID"] = (cw["high"] + cw["low"]) / 2.0
    if len(weekly) >= 2:
        pw = weekly[-2]
        cats["PREV_WEEK_HIGH"] = pw["high"]
        cats["PREV_WEEK_LOW"]  = pw["low"]

    # Session highs/lows
    asian_h, asian_l = _asian_high_low(sym, now_utc)
    if asian_h is not None and asian_l is not None:
        cats["ASIAN_HIGH"] = asian_h
        cats["ASIAN_LOW"]  = asian_l
    london_h, london_l = _london_high_low(sym, now_utc)
    if london_h is not None and london_l is not None:
        cats["LONDON_HIGH"] = london_h
        cats["LONDON_LOW"]  = london_l

    # Swing points (multi-value: emit numbered keys so each price is its
    # own candidate, but they share the H1_SWING_HIGH/LOW base label for
    # confluence vocab purposes).
    if h1:
        h1_highs, h1_lows = _swing_points(h1, SWING_H1_LOOKBACK_BARS, SWING_H1_REVERSAL_PIPS)
        for i, p in enumerate(h1_highs[-5:]):
            cats[f"H1_SWING_HIGH#{i}"] = p
        for i, p in enumerate(h1_lows[-5:]):
            cats[f"H1_SWING_LOW#{i}"] = p
    if h4:
        h4_highs, h4_lows = _swing_points(h4, SWING_H4_LOOKBACK_BARS, SWING_H4_REVERSAL_PIPS)
        for i, p in enumerate(h4_highs[-5:]):
            cats[f"H4_SWING_HIGH#{i}"] = p
        for i, p in enumerate(h4_lows[-5:]):
            cats[f"H4_SWING_LOW#{i}"] = p

    # Round numbers
    if current_price is not None:
        for rn in _round_numbers_near(
            current_price, ROUND_NUMBER_RANGE_PIPS, ROUND_NUMBER_STEP_PIPS,
        ):
            cats[f"ROUND_NUMBER@{rn:g}"] = rn

    # Indicator levels
    if d1:
        d1_closes = [b["close"] for b in d1]
        v = _ema(d1_closes, 20)
        if v is not None:
            cats["D1_EMA_20"] = v
    if h4:
        h4_closes = [b["close"] for b in h4]
        v50  = _ema(h4_closes, 50)
        v200 = _ema(h4_closes, 200)
        if v50  is not None:
            cats["H4_EMA_50"]  = v50
        if v200 is not None:
            cats["H4_EMA_200"] = v200

    return cats, meta


# ─────────────────────────────────────────────────────────────────────────────
# Confluence clustering + ranking
# ─────────────────────────────────────────────────────────────────────────────

def _category_base_name(key: str) -> str:
    """Strip the #N or @value suffix used to keep multi-value keys unique."""
    for sep in ("#", "@"):
        if sep in key:
            return key.split(sep, 1)[0]
    return key


def _cluster_candidates(
    cats: Dict[str, float],
    tol_pips: float,
) -> List[Dict[str, Any]]:
    """Coalesce candidate prices that are within ±tol_pips of each other
    into a cluster. Greedy: walks candidates sorted by price, opens a new
    cluster when the next candidate is more than tol_pips above the
    cluster's anchor. Cluster anchor = the highest-priority member.
    """
    items = sorted(cats.items(), key=lambda kv: kv[1])
    clusters: List[Dict[str, Any]] = []
    for key, price in items:
        base = _category_base_name(key)
        # Open a new cluster when the price exceeds the most recent
        # cluster's anchor by more than tol_pips, or there's no cluster yet.
        if not clusters or (price - clusters[-1]["anchor_price"]) > tol_pips:
            clusters.append({
                "members":      [(key, price)],
                "anchor_key":   key,
                "anchor_price": price,
            })
            continue
        current = clusters[-1]
        current["members"].append((key, price))
        # If this member's category outranks the current anchor, switch
        cur_base = _category_base_name(current["anchor_key"])
        if _CATEGORY_RANK.get(base, 999) < _CATEGORY_RANK.get(cur_base, 999):
            current["anchor_key"]   = key
            current["anchor_price"] = price
    # Compute confluence_count = number of distinct base categories
    for c in clusters:
        bases = {_category_base_name(m[0]) for m in c["members"]}
        c["distinct_categories"] = sorted(bases, key=lambda b: _CATEGORY_RANK.get(b, 999))
        c["confluence_count"]    = len(bases)
    return clusters


def _rank_clusters(clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort clusters by (-confluence_count, anchor's category priority)."""
    return sorted(
        clusters,
        key=lambda c: (
            -c["confluence_count"],
            _CATEGORY_RANK.get(_category_base_name(c["anchor_key"]), 999),
        ),
    )


def _enforce_separation(
    ranked: List[Dict[str, Any]],
    min_sep: float,
    max_count: int,
) -> List[Dict[str, Any]]:
    """Walk ranked clusters; keep one only if it's at least `min_sep`
    pips away from every already-kept cluster. Stops at `max_count`.
    """
    kept: List[Dict[str, Any]] = []
    for c in ranked:
        if any(abs(c["anchor_price"] - k["anchor_price"]) < min_sep for k in kept):
            continue
        kept.append(c)
        if len(kept) >= max_count:
            break
    return kept


# ─────────────────────────────────────────────────────────────────────────────
# Emit ComputedLevel
# ─────────────────────────────────────────────────────────────────────────────

def _build_justification(cluster: Dict[str, Any]) -> str:
    """Build a ≤30-word justification from the anchor + other categories."""
    anchor_base = _category_base_name(cluster["anchor_key"])
    anchor_label = _CATEGORY_LABEL.get(anchor_base, anchor_base)
    price = cluster["anchor_price"]
    other_bases = [
        b for b in cluster["distinct_categories"] if b != anchor_base
    ]
    if not other_bases:
        text = f"{anchor_label.capitalize()} at {price:g}"
    else:
        others = ", ".join(_CATEGORY_LABEL.get(b, b) for b in other_bases[:4])
        text = f"{anchor_label.capitalize()} at {price:g}, confluence with {others}"
    # 30-word cap
    words = text.split()
    if len(words) > 30:
        text = " ".join(words[:30])
    return text


def _confluence_tags(cluster: Dict[str, Any]) -> List[str]:
    """Phase-1-vocab tags for the emitted level. Deduplicated, ordered by
    category priority. Tags whose internal category has no vocab mapping
    are dropped from the list (but still counted internally).
    """
    out: List[str] = []
    seen: set = set()
    for base in cluster["distinct_categories"]:
        tag = _CATEGORY_TO_VOCAB_TAG.get(base)
        if tag is None or tag not in _PHASE1_VOCAB:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _level_type(price: float, current_price: Optional[float]) -> str:
    if current_price is None:
        return "PIVOT"
    if abs(price - current_price) <= TYPE_PIVOT_TOLERANCE_PIPS:
        return "PIVOT"
    return "RESISTANCE" if price > current_price else "SUPPORT"


def _level_role(rank: int) -> str:
    if rank <= 2:
        return "primary"
    if rank <= 4:
        return "secondary"
    return "extension"


def _strength(confluence_count: int) -> str:
    if confluence_count >= 3:
        return "HIGH"
    if confluence_count == 2:
        return "MEDIUM"
    return "LOW"


def _make_computed_levels(
    selected: List[Dict[str, Any]],
    current_price: Optional[float],
) -> List[ComputedLevel]:
    """Convert the selected clusters into rank-ordered ComputedLevel objects.
    Re-orders by ascending rank so output is sorted as the consumer expects.
    """
    out: List[ComputedLevel] = []
    for i, cluster in enumerate(selected, start=1):
        confluence_tags = _confluence_tags(cluster)
        # Keep at least one tag — fall back to the anchor's vocab mapping
        # even if the dedup loop dropped it (shouldn't happen, but safe).
        if not confluence_tags:
            anchor_base = _category_base_name(cluster["anchor_key"])
            tag = _CATEGORY_TO_VOCAB_TAG.get(anchor_base)
            if tag and tag in _PHASE1_VOCAB:
                confluence_tags = [tag]
            else:
                confluence_tags = ["ROUND_NUMBER"]  # ultimate fallback
        out.append(ComputedLevel(
            rank=i,
            price=round(cluster["anchor_price"], 5),
            type=_level_type(cluster["anchor_price"], current_price),
            role=_level_role(i),
            confluence=confluence_tags,
            confluence_count=cluster["confluence_count"],
            justification=_build_justification(cluster),
            strength=_strength(cluster["confluence_count"]),
        ))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_ranked_levels(
    symbol: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[List[ComputedLevel], Dict[str, Any]]:
    """Compute 4-6 ranked levels for *symbol*. Returns (levels, meta).

    The meta dict reports counts of bars/categories used, the resolved
    current price, and an `undercount` flag set when fewer than
    ``LEVELS_MIN_COUNT`` levels survive the separation pass — useful for
    logging and the Phase 8 prompt.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    sym = symbol.upper()

    cats, meta = _gather_categories(sym, now_utc)
    meta["categories_gathered"] = len(cats)

    if not cats:
        meta["undercount"] = True
        meta["reason"] = "no candidate categories computable"
        return [], meta

    # Defensive outlier drop: reject candidates whose price is more than
    # OUTLIER_MAX_DEVIATION_RATIO away from current_price. Catches bad
    # bars from feed glitches that would otherwise poison aggregates.
    cp = meta.get("current_price")
    if cp:
        lo = cp * (1.0 - OUTLIER_MAX_DEVIATION_RATIO)
        hi = cp * (1.0 + OUTLIER_MAX_DEVIATION_RATIO)
        dropped: List[Tuple[str, float]] = []
        kept: Dict[str, float] = {}
        for k, v in cats.items():
            if lo <= v <= hi:
                kept[k] = v
            else:
                dropped.append((k, v))
        if dropped:
            logger.warning(
                "[level_computation] %s: dropped %d outlier candidate(s) "
                "outside ±%.0f%% of current=%g: %s",
                sym, len(dropped), OUTLIER_MAX_DEVIATION_RATIO * 100, cp,
                ", ".join(f"{k}={v:g}" for k, v in dropped[:5]),
            )
        meta["outliers_dropped"] = [{"category": k, "price": v} for k, v in dropped]
        cats = kept

    clusters = _cluster_candidates(cats, LEVEL_CONFLUENCE_TOLERANCE_PIPS)
    ranked   = _rank_clusters(clusters)
    selected = _enforce_separation(ranked, MIN_SEPARATION_PIPS, LEVELS_MAX_COUNT)
    levels   = _make_computed_levels(selected, meta.get("current_price"))

    meta["clusters_total"]    = len(clusters)
    meta["clusters_selected"] = len(levels)
    meta["undercount"]        = len(levels) < LEVELS_MIN_COUNT
    return levels, meta


__all__ = [
    "ComputedLevel",
    "get_ranked_levels",
    "LEVEL_CONFLUENCE_TOLERANCE_PIPS",
    "MIN_SEPARATION_PIPS",
    "LEVELS_MIN_COUNT",
    "LEVELS_MAX_COUNT",
]
