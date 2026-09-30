"""USD strength proxy via a multi-pair basket.

Bug 2 of docs/briefing_producer_audit_2026-05-11.md: the old proxy at
morning_briefing.py:767-786 used USDJPY H1 momentum only, meaning every
GBPUSD and EURUSD briefing saw the same number — contaminated by JPY-
specific moves (BoJ, JGB, intervention).

This module computes USD strength as a normalized average across all
USD-bearing pairs the runtime has H1 buffers for, excluding the pair
being briefed (to avoid circular self-reference). Each pair's lookback
move is normalized by its own typical H1 range so a 200-pip USDJPY
intervention day does not swamp a 20-pip EURUSD drift.

Sign convention:
  * USDJPY / USDCAD / USDCHF  — USD is the BASE. Up = USD stronger.
  * EURUSD / GBPUSD / AUDUSD / NZDUSD — USD is the QUOTE. Up = USD weaker.

After Bug 1 the briefing's daily_bias is bound deterministically by
compute_d1_direction. This proxy is now narrative-side only; downstream
code reads it only for the prompt block.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Sign mapping: +1 = pair-up means USD-up, -1 = pair-up means USD-down.
USD_BASE_PAIRS  = ("USDJPY", "USDCAD", "USDCHF")
USD_QUOTE_PAIRS = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD")
ALL_USD_PAIRS   = USD_BASE_PAIRS + USD_QUOTE_PAIRS

# Threshold on the normalized-pip output for the textual bias label.
STRONG_THRESHOLD = 5.0  # |normalized_pips| > 5 → STRONG/WEAK
NEUTRAL_BAND     = "USD_NEUTRAL"
STRONG_LABEL     = "USD_STRONG"
WEAK_LABEL       = "USD_WEAK"

# How recent the last candle must be (hours). Older = stale → exclude pair.
STALE_HOURS = 24.0


def _sign(pair: str) -> int:
    return +1 if pair in USD_BASE_PAIRS else -1


def _last_ts(buf: List[Dict[str, Any]]) -> Optional[datetime]:
    if not buf:
        return None
    ts = buf[-1].get("timestamp")
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        try:
            d = datetime.fromisoformat(ts)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _label(usd_proxy_pips: float) -> str:
    if usd_proxy_pips > STRONG_THRESHOLD:
        return STRONG_LABEL
    if usd_proxy_pips < -STRONG_THRESHOLD:
        return WEAK_LABEL
    return NEUTRAL_BAND


def compute_usd_strength(
    pair: str,
    candle_buffers: Dict[str, List[Dict[str, Any]]],
    lookback_bars: int = 6,
    atr_lookback_bars: int = 20,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Per-pair USD strength signal using a multi-pair basket.

    Parameters
    ----------
    pair : the pair being briefed. Excluded from its own basket.
    candle_buffers : dict {SYMBOL: [{timestamp, open, high, low, close}, ...]}.
        Typically the runtime's ``_TF_CTX._h1_closed``.
    lookback_bars : number of bars over which to measure the directional move.
    atr_lookback_bars : window for the typical-range normalisation denominator.
    now_utc : staleness reference; defaults to ``datetime.now(timezone.utc)``.
    """
    pair = pair.upper()
    now_utc = now_utc or datetime.now(timezone.utc)

    contributing: List[str] = []
    per_pair: List[Dict[str, Any]] = []
    skipped: Dict[str, str] = {}

    for other in ALL_USD_PAIRS:
        if other == pair:
            continue
        buf = candle_buffers.get(other) or candle_buffers.get(other.upper())
        if not buf:
            skipped[other] = "no_buffer"
            continue
        if len(buf) < max(lookback_bars + 1, atr_lookback_bars):
            skipped[other] = f"insufficient_history(n={len(buf)})"
            continue

        # Staleness: last candle must be within STALE_HOURS of now.
        last_ts = _last_ts(buf)
        if last_ts is not None:
            age_h = (now_utc - last_ts).total_seconds() / 3600.0
            if age_h > STALE_HOURS:
                skipped[other] = f"stale({age_h:.1f}h)"
                continue

        try:
            closes = [float(c.get("close")) for c in buf if c.get("close") is not None]
            highs  = [float(c.get("high"))  for c in buf if c.get("high")  is not None]
            lows   = [float(c.get("low"))   for c in buf if c.get("low")   is not None]
        except (TypeError, ValueError):
            skipped[other] = "bad_data"
            continue

        if len(closes) < lookback_bars + 1 or len(highs) < atr_lookback_bars or len(lows) < atr_lookback_bars:
            skipped[other] = "insufficient_after_clean"
            continue

        move = closes[-1] - closes[-1 - lookback_bars]

        # Typical range over the recent atr_lookback_bars (in raw price units).
        ranges = [
            h - l for h, l in zip(highs[-atr_lookback_bars:], lows[-atr_lookback_bars:])
            if h is not None and l is not None and h >= l
        ]
        if not ranges:
            skipped[other] = "no_range_data"
            continue
        typical_range = sum(ranges) / len(ranges)
        if typical_range <= 0:
            skipped[other] = "zero_range"
            continue

        normalized = move / typical_range  # unitless, ≈ #typical-bars moved
        sign = _sign(other)
        per_pair.append({
            "pair": other,
            "move_raw": round(move, 4),
            "typical_range": round(typical_range, 4),
            "normalized": round(normalized, 4),
            "sign": sign,
            "usd_contribution": round(sign * normalized, 4),
        })
        contributing.append(other)

    n = len(contributing)
    if n == 0:
        return {
            "usd_proxy_pips":    None,
            "usd_proxy_bias":    None,
            "contributing_pairs": [],
            "skipped":           skipped,
            "method":            "unavailable",
            "reason":            "no pairs in basket",
            "per_pair":          [],
        }

    method = "basket" if n >= 3 else "degraded_single"

    avg_contribution = sum(p["usd_contribution"] for p in per_pair) / n
    # Scale unitless → "normalized pips" for prompt readability. 10× keeps
    # the magnitude in the same ballpark as the old usd_proxy_pips numbers
    # (the old proxy showed values like +26.2 for a strong USDJPY move).
    usd_proxy_pips = round(avg_contribution * 10.0, 1)
    bias = _label(usd_proxy_pips)

    reason_parts = [f"basket of {n} ({', '.join(contributing)})"]
    reason_parts.append(f"avg USD contribution {avg_contribution:+.3f} → {bias}")
    if method == "degraded_single":
        reason_parts.append("degraded — fewer than 3 pairs available")

    return {
        "usd_proxy_pips":     usd_proxy_pips,
        "usd_proxy_bias":     bias,
        "contributing_pairs": contributing,
        "skipped":            skipped,
        "method":             method,
        "reason":             "; ".join(reason_parts),
        "per_pair":           per_pair,
    }
