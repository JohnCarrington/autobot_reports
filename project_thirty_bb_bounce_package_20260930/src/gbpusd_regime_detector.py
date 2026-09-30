"""
gbpusd_regime_detector.py — cheap 5m-close regime classifier for GBPUSD.

Gates strategies that only want to fire in a specific regime
(BB_PIERCE_RUN wants RANGE, EMA_PULLBACK wants TRENDING).

Four bar-arithmetic signals voted by majority. No API calls.

Signals:
  1. ATR(14) vs mean of trailing-14 ATRs over the last 120 bars.
       ratio > 1.25 -> TRENDING (vol expanding)
       ratio < 0.80 -> RANGE     (vol contracting)
  2. Current BB(20,2) width vs mean BB width across last 120 bars.
       ratio > 1.30 -> TRENDING
       ratio < 0.75 -> RANGE
  3. (high_12 - low_12) / ATR(14) — recent move vs typical bar.
       ratio > 4.0 -> TRENDING
       ratio < 1.5 -> RANGE
  4. Pierce alternation across last 24 bars.
       balanced (both sides hit, ratio <= 2:1)                -> RANGE
       one-sided (only one side, or ratio > 3:1) and >= 3 hits -> TRENDING

Combined verdict (majority of 4):
  >= 3 TRENDING votes -> TRENDING
  >= 3 RANGE votes    -> RANGE
  otherwise           -> NEUTRAL

Sticky-trending override (added 2026-05-03):
  If current ATR(14) >= 7 pips AND >= 1 signal voted TRENDING,
  classify as TRENDING regardless of majority. Keeps prolonged
  elevated-volatility regimes flagged when the relative-baseline
  measures decay as the trending state persists.

Confidence:
  4/4 votes match the final regime -> HIGH
  3/4 votes match the final regime -> MEDIUM
  otherwise                        -> LOW

Symmetric: every signal is direction-agnostic (no bull/bear bias).

Logging: each call appends a JSONL line to logs/gbpusd_regime.jsonl.

Env:
  GBPUSD_REGIME_DETECTOR_ENABLED=true (default)

Bars expected: closed 5m candles in chronological order. Minimum 140
bars (BB-width baseline 120 + 20-period BB lookback).

Stateful buffer (added 2026-05-04):
  Each call's incoming bars are merged into a per-symbol in-memory
  deque (deduped by timestamp). The buffer holds up to BUFFER_MAX_BARS
  rows. classify_regime always uses the buffer's contents — not just
  the caller's slice — so callers that pass only the most-recent N
  bars (e.g. BB_BOUNCE / BB_REV_PAT pass 60) still trigger a real
  classification once the buffer accumulates ≥ MIN_BARS.

Startup prewarm:
  prewarm_buffer(symbol) walks the data/candles/<SYMBOL>/*.csv archive
  newest-first and seeds the buffer with up to MIN_BARS+headroom rows.
  Called once at autobot startup so the gate is never silently in
  warmup after a restart. Idempotent. Falls back to live-warm if the
  archive is missing.
"""
from __future__ import annotations

import csv as _csv
import json
import logging
import math
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence

logger = logging.getLogger("gbpusd_regime_detector")

LOG_TAG = "REGIME"

# ─── Config ──────────────────────────────────────────────────────────────
PIP_SIZE = 1.0  # GBPUSD: 1 raw IG point = 1 pip


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


ENABLED = _env_bool("GBPUSD_REGIME_DETECTOR_ENABLED", "true")

ATR_PERIOD            = 14
ATR_BASELINE_LOOKBACK = 120   # bars to average trailing-14 ATRs over
ATR_TREND_RATIO       = 1.25
ATR_RANGE_RATIO       = 0.80

# Sticky-trending floor: if current ATR(14) >= this many pips AND any
# single signal votes TRENDING, the final regime is TRENDING. Designed
# to keep prolonged trending regimes flagged once the relative-baseline
# measures (signals 1 & 2) decay because elevated vol is now the norm.
ATR_TREND_FLOOR_PIPS  = 7.0

BB_PERIOD           = 20
BB_STD              = 2.0
BB_WIDTH_LOOKBACK   = 120
BB_TREND_RATIO      = 1.30
BB_RANGE_RATIO      = 0.75

RANGE_BARS          = 12
RANGE_TREND_RATIO   = 4.0
RANGE_RANGE_RATIO   = 1.5

PIERCE_LOOKBACK     = 24
PIERCE_BALANCED_MAX = 2.0    # ratio of larger:smaller to still be "balanced"
PIERCE_ONESIDED_MIN = 3.0
PIERCE_ONESIDED_MIN_HITS = 3

MIN_BARS = max(
    BB_PERIOD + BB_WIDTH_LOOKBACK,           # 140 — BB width baseline
    ATR_PERIOD + 1 + ATR_BASELINE_LOOKBACK,  # 135 — ATR baseline
)

LOG_PATH = os.environ.get(
    "GBPUSD_REGIME_LOG_PATH",
    "/opt/tradingbot/logs/gbpusd_regime.jsonl",
)
_LOG_LOCK = threading.Lock()

# ─── Stateful buffer ─────────────────────────────────────────────────────
# Per-symbol rolling deque of recent closed bars. Caller's bars are
# merged in (deduped by timestamp); classification is computed from
# the buffer's full contents. Headroom above MIN_BARS so a single
# classify call has stable history to compute baseline-windowed
# signals against (BB-width and ATR baselines look back 120 bars from
# the current bar).
BUFFER_MAX_BARS = max(MIN_BARS + 60, 250)

CANDLE_ARCHIVE_ROOT = Path(os.environ.get(
    "GBPUSD_CANDLE_ARCHIVE_ROOT",
    "/opt/tradingbot/data/candles",
))

_BAR_BUFFERS: Dict[str, "Deque[Bar]"] = {}
_BUFFER_LOCK = threading.Lock()
_PRELOAD_DONE: Dict[str, bool] = {}


# ─── Types ───────────────────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. Times are tz-aware UTC."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class RegimeResult:
    regime: str                       # "TRENDING" | "RANGE" | "NEUTRAL"
    confidence: str                   # "HIGH" | "MEDIUM" | "LOW"
    signal_breakdown: Dict[str, str]  # per-signal verdict
    timestamp: Optional[datetime]
    debug: Dict[str, Any] = field(default_factory=dict)


# ─── Indicators ──────────────────────────────────────────────────────────
def _true_ranges(bars: Sequence[Bar]) -> List[float]:
    """TR for bars[1:]. bars[0] has no prev close so it's skipped."""
    out: List[float] = []
    for i in range(1, len(bars)):
        h = bars[i].high
        l = bars[i].low
        pc = bars[i - 1].close
        tr = max(h - l, abs(h - pc), abs(l - pc))
        out.append(tr)
    return out


def _atr(bars: Sequence[Bar], period: int = ATR_PERIOD) -> float:
    """Simple-moving-average ATR over the most recent `period` true ranges."""
    trs = _true_ranges(bars)
    if len(trs) < period:
        raise ValueError(f"need {period}+ TRs for ATR, got {len(trs)}")
    return sum(trs[-period:]) / period


def _bb_width(closes: Sequence[float],
              period: int = BB_PERIOD,
              std_mult: float = BB_STD) -> float:
    """Upper - lower for the trailing `period` closes (population stdev)."""
    if len(closes) < period:
        raise ValueError(f"need {period}+ closes for BB width")
    window = list(closes[-period:])
    mid = sum(window) / period
    var = sum((c - mid) ** 2 for c in window) / period
    std = math.sqrt(var)
    return 2 * std_mult * std


def _bb(closes: Sequence[float],
        period: int = BB_PERIOD,
        std_mult: float = BB_STD) -> tuple:
    if len(closes) < period:
        raise ValueError(f"need {period}+ closes for BB")
    window = list(closes[-period:])
    mid = sum(window) / period
    var = sum((c - mid) ** 2 for c in window) / period
    std = math.sqrt(var)
    return mid - std_mult * std, mid, mid + std_mult * std


# ─── Signals ─────────────────────────────────────────────────────────────
def _signal_atr(bars: Sequence[Bar]) -> tuple:
    """Signal 1: current ATR(14) vs mean of trailing-14 ATRs over the
    last ATR_BASELINE_LOOKBACK bars.

    Wider baseline than the original 60-bar single point — a longer
    window is harder to wash out once an elevated-vol regime persists.
    """
    needed = ATR_PERIOD + 1 + ATR_BASELINE_LOOKBACK
    if len(bars) < needed:
        return "NEUTRAL", {"reason": "warmup", "have": len(bars), "need": needed}

    cur_atr = _atr(bars[-(ATR_PERIOD + 1):])

    # ATR(14) measured at each of the last ATR_BASELINE_LOOKBACK bar
    # positions. For the i-th sample (i in [0, lookback)), the trailing
    # 14 TRs end at bar index (len(bars) - 1 - i).
    atrs: List[float] = []
    for i in range(ATR_BASELINE_LOOKBACK):
        end = len(bars) - i  # exclusive
        atrs.append(_atr(bars[end - (ATR_PERIOD + 1):end]))
    mean_atr = sum(atrs) / len(atrs)

    if mean_atr <= 0:
        return "NEUTRAL", {"reason": "mean_atr_zero"}

    ratio = cur_atr / mean_atr
    if ratio > ATR_TREND_RATIO:
        verdict = "TRENDING"
    elif ratio < ATR_RANGE_RATIO:
        verdict = "RANGE"
    else:
        verdict = "NEUTRAL"
    return verdict, {
        "cur_atr_pips": round(cur_atr / PIP_SIZE, 2),
        "mean_atr_pips": round(mean_atr / PIP_SIZE, 2),
        "ratio": round(ratio, 3),
    }


def _signal_bb_width(bars: Sequence[Bar]) -> tuple:
    """Signal 2: current BB width vs mean BB width across last 60 bars."""
    needed = BB_PERIOD + BB_WIDTH_LOOKBACK
    if len(bars) < needed:
        return "NEUTRAL", {"reason": "warmup", "have": len(bars), "need": needed}

    closes = [b.close for b in bars]
    cur_w = _bb_width(closes)

    widths: List[float] = []
    for i in range(BB_WIDTH_LOOKBACK):
        end = len(closes) - i  # exclusive
        widths.append(_bb_width(closes[end - BB_PERIOD:end]))
    mean_w = sum(widths) / len(widths)

    if mean_w <= 0:
        return "NEUTRAL", {"reason": "mean_width_zero"}

    ratio = cur_w / mean_w
    if ratio > BB_TREND_RATIO:
        verdict = "TRENDING"
    elif ratio < BB_RANGE_RATIO:
        verdict = "RANGE"
    else:
        verdict = "NEUTRAL"
    return verdict, {
        "cur_width_pips": round(cur_w / PIP_SIZE, 2),
        "mean_width_pips": round(mean_w / PIP_SIZE, 2),
        "ratio": round(ratio, 3),
    }


def _signal_range_atr(bars: Sequence[Bar]) -> tuple:
    """Signal 3: (high_12 - low_12) / ATR(14)."""
    needed = max(RANGE_BARS, ATR_PERIOD + 1)
    if len(bars) < needed:
        return "NEUTRAL", {"reason": "warmup", "have": len(bars), "need": needed}

    recent = bars[-RANGE_BARS:]
    high_n = max(b.high for b in recent)
    low_n  = min(b.low  for b in recent)
    rng = high_n - low_n
    atr = _atr(bars[-(ATR_PERIOD + 1):])

    if atr <= 0:
        return "NEUTRAL", {"reason": "atr_zero"}

    ratio = rng / atr
    if ratio > RANGE_TREND_RATIO:
        verdict = "TRENDING"
    elif ratio < RANGE_RANGE_RATIO:
        verdict = "RANGE"
    else:
        verdict = "NEUTRAL"
    return verdict, {
        "range_pips": round(rng / PIP_SIZE, 2),
        "atr_pips": round(atr / PIP_SIZE, 2),
        "ratio": round(ratio, 3),
    }


def _signal_pierce_alt(bars: Sequence[Bar]) -> tuple:
    """Signal 4: balanced vs one-sided BB pierces over last 24 bars.

    BB at each of the 24 bars is computed from its trailing 20 closes,
    so the underlying band moves with the window — a price-based
    'are we hugging one side' read, not a static-band read.
    """
    needed = BB_PERIOD + PIERCE_LOOKBACK
    if len(bars) < needed:
        return "NEUTRAL", {"reason": "warmup", "have": len(bars), "need": needed}

    closes = [b.close for b in bars]
    upper_hits = 0
    lower_hits = 0
    for i in range(PIERCE_LOOKBACK):
        idx = len(bars) - PIERCE_LOOKBACK + i  # bar index
        bb_lower, _, bb_upper = _bb(closes[idx + 1 - BB_PERIOD:idx + 1])
        if bars[idx].high > bb_upper:
            upper_hits += 1
        if bars[idx].low < bb_lower:
            lower_hits += 1

    total = upper_hits + lower_hits
    larger = max(upper_hits, lower_hits)
    smaller = min(upper_hits, lower_hits)

    debug = {"upper": upper_hits, "lower": lower_hits, "total": total}

    # No pierces at all — undecidable.
    if total == 0:
        return "NEUTRAL", {**debug, "reason": "no_pierces"}

    # Balanced — both sides hit and ratio <= 2:1.
    if smaller > 0 and (larger / smaller) <= PIERCE_BALANCED_MAX:
        return "RANGE", {**debug, "ratio": round(larger / smaller, 2)}

    # One-sided test.
    one_sided = (smaller == 0) or ((larger / max(smaller, 1)) > PIERCE_ONESIDED_MIN)
    if one_sided and total >= PIERCE_ONESIDED_MIN_HITS:
        ratio = float("inf") if smaller == 0 else round(larger / smaller, 2)
        return "TRENDING", {**debug, "ratio": ratio}

    return "NEUTRAL", debug


# ─── CSV preload + buffer management ─────────────────────────────────────
def _load_bars_from_csv(symbol: str,
                        max_bars: int,
                        ) -> List[Bar]:
    """Walk back through data/candles/<SYMBOL>/*.csv newest-first until
    `max_bars` accumulated. Returns chronological. Soft on errors —
    a malformed file is skipped, not fatal."""
    sym_u = symbol.upper()
    candle_dir = CANDLE_ARCHIVE_ROOT / sym_u
    if not candle_dir.exists():
        logger.warning("[%s] %s csv preload: dir not found %s",
                       LOG_TAG, sym_u, candle_dir)
        return []
    # Filenames are YYYY-MM-DD.csv; lexicographic sort == chronological.
    files = sorted(candle_dir.glob("*.csv"), key=lambda p: p.name)
    bars: List[Bar] = []
    # Walk newest-first so we can stop once we have enough.
    for fp in reversed(files):
        try:
            day_rows: List[Bar] = []
            with open(fp, "r", encoding="utf-8") as f:
                for r in _csv.DictReader(f):
                    try:
                        ts_raw = r.get("timestamp") or r.get("time")
                        ts_dt = datetime.fromisoformat(str(ts_raw))
                        if ts_dt.tzinfo is None:
                            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                        else:
                            ts_dt = ts_dt.astimezone(timezone.utc)
                        day_rows.append(Bar(
                            timestamp=ts_dt,
                            open=float(r["open"]),
                            high=float(r["high"]),
                            low=float(r["low"]),
                            close=float(r["close"]),
                        ))
                    except (KeyError, TypeError, ValueError):
                        continue
        except OSError as exc:
            logger.warning("[%s] %s csv preload skip %s: %s",
                           LOG_TAG, sym_u, fp.name, exc)
            continue
        # Prepend (older file's rows precede already-collected newer rows).
        bars = day_rows + bars
        if len(bars) >= max_bars:
            break
    bars.sort(key=lambda b: b.timestamp)
    if len(bars) > max_bars:
        bars = bars[-max_bars:]
    return bars


def prewarm_buffer(symbol: str = "GBPUSD") -> int:
    """Populate the per-symbol buffer from the candle archive. Idempotent —
    repeat calls return immediately. Returns the buffer size after
    prewarm (0 if archive missing / empty)."""
    sym_u = symbol.upper()
    with _BUFFER_LOCK:
        if _PRELOAD_DONE.get(sym_u):
            return len(_BAR_BUFFERS.get(sym_u, ()))
        target = BUFFER_MAX_BARS
        bars = _load_bars_from_csv(sym_u, target)
        buf: Deque[Bar] = deque(bars, maxlen=BUFFER_MAX_BARS)
        _BAR_BUFFERS[sym_u] = buf
        _PRELOAD_DONE[sym_u] = True
    n = len(buf)
    if n >= MIN_BARS:
        last_ts = buf[-1].timestamp.isoformat() if buf else "n/a"
        logger.info(
            "[%s] %s prewarm: initialized with %d historical bars "
            "(need %d) — warmup complete (latest_ts=%s)",
            LOG_TAG, sym_u, n, MIN_BARS, last_ts,
        )
    elif n > 0:
        logger.warning(
            "[%s] %s prewarm: only %d historical bars available "
            "(need %d) — still in warmup, will fill from live ticks",
            LOG_TAG, sym_u, n, MIN_BARS,
        )
    else:
        logger.warning(
            "[%s] %s prewarm: no historical bars found in archive — "
            "warmup will fill from live ticks (~%dm wallclock)",
            LOG_TAG, sym_u, MIN_BARS * 5,
        )
    return n


def reset_buffer(symbol: Optional[str] = None) -> None:
    """Clear buffer state. Test/probe seam — production should never
    call this. If `symbol` is None, clears all symbols."""
    with _BUFFER_LOCK:
        if symbol is None:
            _BAR_BUFFERS.clear()
            _PRELOAD_DONE.clear()
        else:
            sym_u = symbol.upper()
            _BAR_BUFFERS.pop(sym_u, None)
            _PRELOAD_DONE.pop(sym_u, None)


def _merge_into_buffer(symbol: str, incoming: Sequence[Bar]) -> List[Bar]:
    """Merge incoming bars into the per-symbol buffer (dedup by ts).
    Returns the chronological buffer contents to use for this call."""
    sym_u = symbol.upper()
    with _BUFFER_LOCK:
        buf = _BAR_BUFFERS.setdefault(sym_u, deque(maxlen=BUFFER_MAX_BARS))
        if not incoming:
            return list(buf)
        seen: Dict[datetime, int] = {b.timestamp: 1 for b in buf}
        appended_in_order = True
        for b in incoming:
            if b.timestamp in seen:
                continue
            if buf and b.timestamp < buf[-1].timestamp:
                appended_in_order = False
            buf.append(b)
            seen[b.timestamp] = 1
        if not appended_in_order:
            # Out-of-order arrival — re-sort, keep tail.
            sorted_bars = sorted(buf, key=lambda x: x.timestamp)
            buf.clear()
            buf.extend(sorted_bars[-BUFFER_MAX_BARS:])
        return list(buf)


def buffer_size(symbol: str = "GBPUSD") -> int:
    """Inspect the current buffer size for a symbol. Diagnostic seam."""
    with _BUFFER_LOCK:
        return len(_BAR_BUFFERS.get(symbol.upper(), ()))


# ─── Public API ──────────────────────────────────────────────────────────
def classify_regime(bars: List[Bar],
                    symbol: str = "GBPUSD",
                    *,
                    log: bool = True) -> RegimeResult:
    """Compute the regime verdict for `symbol` at the current bar.

    Caller passes the most-recent closed bars; they're merged into the
    per-symbol stateful buffer (deduped by timestamp). Classification
    is computed from the buffer's full contents — this lets callers
    that pass only a short tail (e.g. 60 bars) still trigger real
    classifications once the buffer is prewarmed.

    First call lazily triggers prewarm_buffer() to load history from
    the candle archive. The autobot startup path SHOULD call
    prewarm_buffer() explicitly so the warmup-status line lands on
    the boot log.
    """
    sym_u = symbol.upper()
    if not _PRELOAD_DONE.get(sym_u):
        prewarm_buffer(sym_u)

    effective_bars = _merge_into_buffer(sym_u, bars or ())
    incoming_ts = bars[-1].timestamp if bars else None
    buffer_ts   = effective_bars[-1].timestamp if effective_bars else None
    ts = incoming_ts or buffer_ts

    if not effective_bars or len(effective_bars) < MIN_BARS:
        result = RegimeResult(
            regime="NEUTRAL",
            confidence="LOW",
            signal_breakdown={
                "atr": "NEUTRAL", "bb_width": "NEUTRAL",
                "range_atr": "NEUTRAL", "pierce_alt": "NEUTRAL",
            },
            timestamp=ts,
            debug={"reason": "warmup",
                   "have": len(effective_bars),
                   "need": MIN_BARS,
                   "incoming": len(bars) if bars else 0},
        )
        if log:
            _append_log(symbol, result)
        return result

    s_atr,    d_atr    = _signal_atr(effective_bars)
    s_bbw,    d_bbw    = _signal_bb_width(effective_bars)
    s_range,  d_range  = _signal_range_atr(effective_bars)
    s_pierce, d_pierce = _signal_pierce_alt(effective_bars)

    votes = [s_atr, s_bbw, s_range, s_pierce]
    n_trend   = votes.count("TRENDING")
    n_range   = votes.count("RANGE")
    n_neutral = votes.count("NEUTRAL")

    if n_trend >= 3:
        regime = "TRENDING"
    elif n_range >= 3:
        regime = "RANGE"
    else:
        regime = "NEUTRAL"

    # Sticky-trending override: a non-trivial ATR plus any single
    # TRENDING vote is enough to flag TRENDING. Without this, prolonged
    # rallies de-flag once "current vs trailing-mean" baselines catch up
    # to the elevated state.
    cur_atr_pips = d_atr.get("cur_atr_pips") if isinstance(d_atr, dict) else None
    override_fired = False
    if (regime != "TRENDING"
            and isinstance(cur_atr_pips, (int, float))
            and cur_atr_pips >= ATR_TREND_FLOOR_PIPS
            and n_trend >= 1):
        regime = "TRENDING"
        override_fired = True

    # Confidence = how many of the 4 votes agree with the final label.
    agree = {"TRENDING": n_trend, "RANGE": n_range, "NEUTRAL": n_neutral}.get(regime, 0)
    if agree == 4:
        confidence = "HIGH"
    elif agree == 3:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    result = RegimeResult(
        regime=regime,
        confidence=confidence,
        signal_breakdown={
            "atr": s_atr,
            "bb_width": s_bbw,
            "range_atr": s_range,
            "pierce_alt": s_pierce,
        },
        timestamp=ts,
        debug={
            "atr": d_atr,
            "bb_width": d_bbw,
            "range_atr": d_range,
            "pierce_alt": d_pierce,
            "votes": {"TRENDING": n_trend, "RANGE": n_range, "NEUTRAL": n_neutral},
            "override_fired": override_fired,
        },
    )
    if log:
        _append_log(symbol, result)
    return result


# ─── Logging ─────────────────────────────────────────────────────────────
def _append_log(symbol: str, result: RegimeResult) -> None:
    if not ENABLED:
        return
    line = {
        "ts": result.timestamp.isoformat() if result.timestamp else None,
        "symbol": symbol,
        "regime": result.regime,
        "confidence": result.confidence,
        "signals": result.signal_breakdown,
        "debug": result.debug,
    }
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with _LOG_LOCK:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, default=str) + "\n")
    except OSError as e:
        logger.warning("[%s] failed to append regime log: %s", LOG_TAG, e)


__all__ = [
    "Bar",
    "RegimeResult",
    "classify_regime",
    "prewarm_buffer",
    "reset_buffer",
    "buffer_size",
    "ENABLED",
    "MIN_BARS",
    "BUFFER_MAX_BARS",
]
