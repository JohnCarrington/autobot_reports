"""
gbpusd_bb_reversal_long.py — high-frequency lower-band BB reversal
strategy on GBPUSD 5-minute candles. Module retains the original
three-pattern detector shapes (A, B, C and their LOW mirrors) as dead
code; only A_LOW is enabled by default for live trading. Other
patterns are env-disabled per BB_REV_L_PATTERN_*_ENABLED flags.

Patterns (described for SHORT setups at the upper band; LOW mirrors swap
direction):

  A — PIERCE AND REVERSE
      Bar N pierces BB_upper; bar N+1 closes back inside and is bearish.
      Entry: bar N+1 close. SL: bar_N.high + 3p.

  B — PRE-PIERCE MIRROR
      Bar N is a strong green that approaches but doesn't reach BB_upper;
      bar N+1 mirrors with a comparable bearish body that closes near or
      below bar N's open.
      Entry: bar N+1 close. SL: bar_N.high + 3p.

  C — CREEPING REJECTION
      Bars [N-3..N-1] form a contracting compression along BB_upper;
      bar N is a strong bearish rejection that breaks the compression
      structure downward.
      Entry: bar N close. SL: max(bar_{N-3..N}.high) + 3p.

TP tiers (logged for analysis; v1 exits at TP1):
  TP1 = BB middle (20-period SMA on 5m at entry bar)
  TP2 = opposite BB at entry bar
  TP3 = max(30p from entry, opposite session extreme of the day so far)

Common rules:
  - Trade window: 06:45–15:30 UTC.
  - One position open at a time across all patterns.
  - After SL the strategy re-arms; max 3 trades/day (env-tunable).
  - No briefing dependency, no regime/news filter. The patterns are
    the filter.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

import trend_detection

if TYPE_CHECKING:  # forward-reference target for return-type annotations
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_bb_rev_l")

# 2026-04-28: bidirectional. LONG (A_LOW) and SHORT (A) both default-on.
# Patterns B/C in either direction remain dead code, env-disabled.
# Mode tags differ by direction so executor dedup is per-direction:
#   LONG  → GBPUSD_BB_REV_L
#   SHORT → GBPUSD_BB_REV_L_S
MODE_NAME       = "GBPUSD_BB_REV_L"     # LONG (A_LOW pattern)
MODE_NAME_SHORT = "GBPUSD_BB_REV_L_S"   # SHORT (A pattern)
PIP_SIZE = 1.0  # GBPUSD: 1 IG point = 1 pip


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


# ─── Config (env-tunable) ─────────────────────────────────────────────────
# Master switch.
ENABLED = _env_bool("BB_REV_L_ENABLED", "1")

# Suppression gate — skip entries against a clean H1 trend (default-on).
TREND_SUPPRESSION_ENABLED = _env_bool("BB_REV_L_TREND_SUPPRESSION_ENABLED", "1")

# Per-pattern direction flags. Default: A LOW + A SHORT both on (bidirectional).
# Patterns B/C remain dead code, env-disabled in either direction.
PATTERN_A_LOW_ENABLED  = _env_bool("BB_REV_L_PATTERN_A_LOW_ENABLED",   "1")
PATTERN_A_SHORT_ENABLED = _env_bool("BB_REV_L_PATTERN_A_SHORT_ENABLED", "1")
PATTERN_B_SHORT_ENABLED = _env_bool("BB_REV_L_PATTERN_B_SHORT_ENABLED", "0")
PATTERN_B_LOW_ENABLED   = _env_bool("BB_REV_L_PATTERN_B_LOW_ENABLED",   "0")
PATTERN_C_SHORT_ENABLED = _env_bool("BB_REV_L_PATTERN_C_SHORT_ENABLED", "0")
PATTERN_C_LOW_ENABLED   = _env_bool("BB_REV_L_PATTERN_C_LOW_ENABLED",   "0")

RISK_GBP = float(os.getenv("BB_REV_L_RISK_GBP", "5.0") or 5.0)
MAX_TRADES_PER_DAY = int(os.getenv("BB_REV_L_MAX_TRADES_PER_DAY", "6") or 6)
MAX_SL_PIPS = float(os.getenv("BB_REV_L_MAX_SL_PIPS", "25") or 25.0)


def _parse_hhmm(spec: str, default: dtime) -> dtime:
    try:
        h, m = spec.strip().split(":")
        return dtime(int(h), int(m))
    except Exception:
        return default


# Trade window — env-tunable HH:MM UTC.
WIN_START = _parse_hhmm(os.getenv("BB_REV_L_WINDOW_START_UTC", "06:45"), dtime(6, 45))
WIN_END   = _parse_hhmm(os.getenv("BB_REV_L_WINDOW_END_UTC",   "15:30"), dtime(15, 30))

# Pattern tolerances
SL_BUFFER_PIPS = 3.0           # all patterns: SL = pierce-extreme ± 3p
B_CLOSE_APPROACH_PIPS = 5.0    # B: bar_N.close within 5p of BB_upper
B_BODY_RATIO = 0.50            # B: bar_N body/range >= 0.50
B_MIRROR_BODY_RATIO = 0.70     # B: |bar_N+1 body| >= 0.70 * |bar_N body|
B_MIRROR_CLOSE_TOL = 2.0       # B: bar_N+1.close <= bar_N.open + 2p
C_NEAR_BAND_PIPS = 5.0         # C: each compression bar's high within ±5p of BB_upper (loosened 2026-04-25 from 3p)
C_REJECTION_BODY_RATIO = 0.60  # C: rejection bar body/range >= 0.60
C_MIN_COMPRESSION_BARS = 3     # C: 3-5 non-expanding bars
C_MAX_COMPRESSION_BARS = 5
TP3_FLOOR_PIPS = 30.0          # TP3 minimum reach from entry


# ─── Bar abstraction ─────────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. Times are tz-aware UTC."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        """Signed body: positive for green, negative for red."""
        return self.close - self.open

    @property
    def body_ratio(self) -> float:
        """|body| / range. 0 if range is 0."""
        r = self.range
        return (abs(self.body) / r) if r > 0 else 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class PatternMatch:
    pattern: str                  # "A" | "B" | "C" | "A_LOW" | "B_LOW" | "C_LOW"
    direction: str                # "SELL" or "BUY"
    entry_price: float
    sl_price: float               # absolute price (not pips)
    sl_pips: float                # |entry - sl| / pip_size, > 0
    detect_bar_ts: datetime       # the bar whose close fires this match
    extreme_pierce: float         # the wick high (SHORT) or low (LONG) used for SL anchor
    notes: str = ""


# ─── Pattern A — PIERCE AND REVERSE ──────────────────────────────────────
def detect_pattern_a(
    bars: Sequence[Bar],
    bb_upper: float, bb_lower: float, bb_mid: float,
    pip_size: float = PIP_SIZE,
) -> Optional[PatternMatch]:
    """Need bars[-2] and bars[-1]; bars[-1] is the most recent closed bar.

    SHORT (upper band):
      bar_N    : high > BB_upper
      bar_N+1  : close < BB_upper AND bearish (close < open)
      Entry: bars[-1].close. SL: bars[-2].high + 3p.

    LONG (lower band) is the mirror.
    """
    if len(bars) < 2:
        return None
    bN = bars[-2]
    bNp1 = bars[-1]

    # SHORT
    if bN.high > bb_upper and bNp1.close < bb_upper and bNp1.is_bearish:
        sl_price = bN.high + SL_BUFFER_PIPS * pip_size
        entry = bNp1.close
        sl_pips = (sl_price - entry) / pip_size
        if sl_pips <= 0:
            return None
        return PatternMatch(
            pattern="A",
            direction="SELL",
            entry_price=entry,
            sl_price=sl_price,
            sl_pips=sl_pips,
            detect_bar_ts=bNp1.timestamp,
            extreme_pierce=bN.high,
            notes=f"pierce h={bN.high:.1f} > BBu={bb_upper:.1f}; reversal close={bNp1.close:.1f} < BBu",
        )

    # LONG (mirror)
    if bN.low < bb_lower and bNp1.close > bb_lower and bNp1.is_bullish:
        sl_price = bN.low - SL_BUFFER_PIPS * pip_size
        entry = bNp1.close
        sl_pips = (entry - sl_price) / pip_size
        if sl_pips <= 0:
            return None
        return PatternMatch(
            pattern="A_LOW",
            direction="BUY",
            entry_price=entry,
            sl_price=sl_price,
            sl_pips=sl_pips,
            detect_bar_ts=bNp1.timestamp,
            extreme_pierce=bN.low,
            notes=f"pierce l={bN.low:.1f} < BBl={bb_lower:.1f}; reversal close={bNp1.close:.1f} > BBl",
        )

    return None


# ─── Pattern B — PRE-PIERCE MIRROR ───────────────────────────────────────
def detect_pattern_b(
    bars: Sequence[Bar],
    bb_upper: float, bb_lower: float, bb_mid: float,
    pip_size: float = PIP_SIZE,
) -> Optional[PatternMatch]:
    """Need bars[-2] and bars[-1].

    SHORT (upper band):
      bar_N    : green AND high < BB_upper AND body_ratio >= 0.50
                 AND BB_upper - close <= 5p (close approach, didn't pierce)
      bar_N+1  : bearish AND |body| >= 0.70 * bar_N's |body|
                 AND close <= bar_N.open + 2p (mirror)
      Entry: bars[-1].close. SL: bar_N.high + 3p.
    """
    if len(bars) < 2:
        return None
    bN = bars[-2]
    bNp1 = bars[-1]

    # SHORT
    if (
        bN.is_bullish
        and bN.high < bb_upper
        and bN.body_ratio >= B_BODY_RATIO
        and (bb_upper - bN.close) <= B_CLOSE_APPROACH_PIPS * pip_size
        and (bb_upper - bN.close) >= 0
    ):
        bN_body_abs = abs(bN.body)
        if (
            bNp1.is_bearish
            and abs(bNp1.body) >= B_MIRROR_BODY_RATIO * bN_body_abs
            and bNp1.close <= bN.open + B_MIRROR_CLOSE_TOL * pip_size
        ):
            sl_price = bN.high + SL_BUFFER_PIPS * pip_size
            entry = bNp1.close
            sl_pips = (sl_price - entry) / pip_size
            if sl_pips <= 0:
                return None
            return PatternMatch(
                pattern="B",
                direction="SELL",
                entry_price=entry,
                sl_price=sl_price,
                sl_pips=sl_pips,
                detect_bar_ts=bNp1.timestamp,
                extreme_pierce=bN.high,
                notes=(
                    f"approach close={bN.close:.1f} (BBu-close={bb_upper-bN.close:.1f}p, "
                    f"body_ratio={bN.body_ratio:.2f}); mirror body "
                    f"|bNp1|/|bN|={abs(bNp1.body)/bN_body_abs:.2f}, "
                    f"bNp1.close-bN.open={bNp1.close-bN.open:+.1f}p"
                ),
            )

    # LONG (mirror)
    if (
        bN.is_bearish
        and bN.low > bb_lower
        and bN.body_ratio >= B_BODY_RATIO
        and (bN.close - bb_lower) <= B_CLOSE_APPROACH_PIPS * pip_size
        and (bN.close - bb_lower) >= 0
    ):
        bN_body_abs = abs(bN.body)
        if (
            bNp1.is_bullish
            and abs(bNp1.body) >= B_MIRROR_BODY_RATIO * bN_body_abs
            and bNp1.close >= bN.open - B_MIRROR_CLOSE_TOL * pip_size
        ):
            sl_price = bN.low - SL_BUFFER_PIPS * pip_size
            entry = bNp1.close
            sl_pips = (entry - sl_price) / pip_size
            if sl_pips <= 0:
                return None
            return PatternMatch(
                pattern="B_LOW",
                direction="BUY",
                entry_price=entry,
                sl_price=sl_price,
                sl_pips=sl_pips,
                detect_bar_ts=bNp1.timestamp,
                extreme_pierce=bN.low,
                notes=(
                    f"approach close={bN.close:.1f} (close-BBl={bN.close-bb_lower:.1f}p, "
                    f"body_ratio={bN.body_ratio:.2f}); mirror body "
                    f"|bNp1|/|bN|={abs(bNp1.body)/bN_body_abs:.2f}, "
                    f"bNp1.close-bN.open={bNp1.close-bN.open:+.1f}p"
                ),
            )

    return None


# ─── Pattern C — CREEPING REJECTION ──────────────────────────────────────
def detect_pattern_c(
    bars: Sequence[Bar],
    bb_upper: float, bb_lower: float, bb_mid: float,
    pip_size: float = PIP_SIZE,
) -> Optional[PatternMatch]:
    """Need at least C_MIN_COMPRESSION_BARS + 1 bars; up to
    C_MAX_COMPRESSION_BARS + 1.

    SHORT (upper band):
      Compression: 3-5 bars before bar N, each with high within 3p of
        BB_upper AND ranges strictly contracting (range[i] < range[i-1]).
      Bar N: bearish, body_ratio >= 0.60, high within 3p of BB_upper,
        close < min(low of last 2 compression bars).
      Entry: bar_N.close. SL: max(highs over compression+rejection bars) + 3p.
    """
    if len(bars) < C_MIN_COMPRESSION_BARS + 1:
        return None
    bN = bars[-1]
    near_band_tol = C_NEAR_BAND_PIPS * pip_size

    # SHORT
    if (
        bN.is_bearish
        and bN.body_ratio >= C_REJECTION_BODY_RATIO
        and (bb_upper - bN.high) <= near_band_tol
        and (bb_upper - bN.high) >= -near_band_tol  # high is within ±3p of band
    ):
        # Try increasing compression lengths from 3 to 5
        for k in range(C_MIN_COMPRESSION_BARS, C_MAX_COMPRESSION_BARS + 1):
            if len(bars) < k + 1:
                break
            comp = bars[-(k + 1):-1]  # k bars before bN
            assert len(comp) == k
            # Each compression bar's high near BB_upper
            ok_near = all(
                (bb_upper - cb.high) <= near_band_tol
                and (bb_upper - cb.high) >= -near_band_tol
                for cb in comp
            )
            if not ok_near:
                continue
            # Non-expanding ranges (loosened 2026-04-25 from strictly contracting):
            # each subsequent bar's range must be <= the previous bar's range.
            ok_non_expanding = all(
                comp[i].range <= comp[i - 1].range
                for i in range(1, k)
            )
            if not ok_non_expanding:
                continue
            # Bar N's close breaks the compression structure: close < min of
            # last two compression bars' lows
            if k >= 2:
                comp_struct_low = min(comp[-1].low, comp[-2].low)
            else:
                comp_struct_low = comp[-1].low
            if bN.close >= comp_struct_low:
                continue
            # Build the match
            highs = [cb.high for cb in comp] + [bN.high]
            anchor = max(highs)
            sl_price = anchor + SL_BUFFER_PIPS * pip_size
            entry = bN.close
            sl_pips = (sl_price - entry) / pip_size
            if sl_pips <= 0:
                continue
            return PatternMatch(
                pattern="C",
                direction="SELL",
                entry_price=entry,
                sl_price=sl_price,
                sl_pips=sl_pips,
                detect_bar_ts=bN.timestamp,
                extreme_pierce=anchor,
                notes=(
                    f"compression k={k} bars at BBu={bb_upper:.1f}; "
                    f"rejection body_ratio={bN.body_ratio:.2f} close={bN.close:.1f} "
                    f"< struct_low={comp_struct_low:.1f}"
                ),
            )

    # LONG (mirror)
    if (
        bN.is_bullish
        and bN.body_ratio >= C_REJECTION_BODY_RATIO
        and (bN.low - bb_lower) <= near_band_tol
        and (bN.low - bb_lower) >= -near_band_tol
    ):
        for k in range(C_MIN_COMPRESSION_BARS, C_MAX_COMPRESSION_BARS + 1):
            if len(bars) < k + 1:
                break
            comp = bars[-(k + 1):-1]
            assert len(comp) == k
            ok_near = all(
                (cb.low - bb_lower) <= near_band_tol
                and (cb.low - bb_lower) >= -near_band_tol
                for cb in comp
            )
            if not ok_near:
                continue
            # Non-expanding ranges (mirror of SHORT loosening, 2026-04-25)
            ok_non_expanding = all(
                comp[i].range <= comp[i - 1].range
                for i in range(1, k)
            )
            if not ok_non_expanding:
                continue
            if k >= 2:
                comp_struct_high = max(comp[-1].high, comp[-2].high)
            else:
                comp_struct_high = comp[-1].high
            if bN.close <= comp_struct_high:
                continue
            lows = [cb.low for cb in comp] + [bN.low]
            anchor = min(lows)
            sl_price = anchor - SL_BUFFER_PIPS * pip_size
            entry = bN.close
            sl_pips = (entry - sl_price) / pip_size
            if sl_pips <= 0:
                continue
            return PatternMatch(
                pattern="C_LOW",
                direction="BUY",
                entry_price=entry,
                sl_price=sl_price,
                sl_pips=sl_pips,
                detect_bar_ts=bN.timestamp,
                extreme_pierce=anchor,
                notes=(
                    f"compression k={k} bars at BBl={bb_lower:.1f}; "
                    f"rejection body_ratio={bN.body_ratio:.2f} close={bN.close:.1f} "
                    f"> struct_high={comp_struct_high:.1f}"
                ),
            )

    return None


# ─── TP tier computation ─────────────────────────────────────────────────
def compute_tp_levels(
    match: PatternMatch,
    bb_upper_at_entry: float,
    bb_lower_at_entry: float,
    bb_mid_at_entry: float,
    session_extreme_so_far: float,
    pip_size: float = PIP_SIZE,
) -> Tuple[float, float, float]:
    """Return (TP1, TP2, TP3) prices for the match.

    TP1 = bb_mid_at_entry
    TP2 = opposite BB at entry (bb_lower for SHORT, bb_upper for LONG)
    TP3 = larger of (30p from entry, opposite session extreme of day so far)
    """
    if match.direction == "SELL":
        tp1 = bb_mid_at_entry
        tp2 = bb_lower_at_entry
        floor_30p = match.entry_price - TP3_FLOOR_PIPS * pip_size
        # session_extreme_so_far for SHORT = the session HIGH of the day
        # before entry; the implied target is the session LOW. The directive
        # says "opposite session extreme" — for a SHORT we want the session
        # low (deepest reachable target). If session_extreme_so_far is None
        # or above entry, fall back to floor_30p.
        if session_extreme_so_far is not None and session_extreme_so_far < match.entry_price:
            candidate = session_extreme_so_far
            tp3 = min(floor_30p, candidate)  # for SHORT, lower price = larger move
        else:
            tp3 = floor_30p
    else:  # BUY
        tp1 = bb_mid_at_entry
        tp2 = bb_upper_at_entry
        floor_30p = match.entry_price + TP3_FLOOR_PIPS * pip_size
        if session_extreme_so_far is not None and session_extreme_so_far > match.entry_price:
            candidate = session_extreme_so_far
            tp3 = max(floor_30p, candidate)
        else:
            tp3 = floor_30p
    return float(tp1), float(tp2), float(tp3)


# ─── Strategy class ──────────────────────────────────────────────────────
class GbpUsdBbReversalLongStrategy:
    """Per-day state: counter of trades taken, set of bar timestamps seen.

    Live behaviour: A_LOW is the only enabled detector by default
    (lower-band pierce-and-reverse). The other patterns (A SHORT, B,
    C and their mirrors) remain in this file as dead code, env-disabled.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._trades_today: Dict[str, int] = {}
        self._last_seen_bar: Optional[datetime] = None

    @staticmethod
    def _date_key(ts: datetime) -> str:
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _in_window(ts: datetime) -> bool:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return WIN_START <= t < WIN_END

    def evaluate(
        self,
        symbol: str,
        epic: str,
        mid_price: float,
        pip_size: float,
        ts: datetime,
        bars: Sequence[Bar],
        bb_upper: float, bb_lower: float, bb_mid: float,
        has_open_long: bool = False,
        has_open_short: bool = False,
        session_extreme_so_far: Optional[float] = None,
    ) -> Optional["StrategyDecision"]:  # type: ignore[name-defined]
        """Called on each new 5m close. `bars` must include at least the
        last 6 closed 5m bars in chronological order; `bars[-1]` is the
        bar that just closed.

        Direction-aware open-position handling: ``has_open_long`` blocks
        only LONG matches, ``has_open_short`` blocks only SHORT matches.
        Each direction fires independently."""
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if not self._in_window(ts):
            return None

        date_key = self._date_key(ts)
        with self._lock:
            taken = self._trades_today.get(date_key, 0)
        if taken >= MAX_TRADES_PER_DAY:
            return None

        # Run detectors. Each detector reports either a SHORT match (pattern
        # X) or a LONG match (pattern X_LOW). We filter by per-direction
        # env flag so that disabled-direction matches are dropped without
        # firing.
        def _direction_enabled(p: str) -> bool:
            return {
                "A":      PATTERN_A_SHORT_ENABLED,
                "A_LOW":  PATTERN_A_LOW_ENABLED,
                "B":      PATTERN_B_SHORT_ENABLED,
                "B_LOW":  PATTERN_B_LOW_ENABLED,
                "C":      PATTERN_C_SHORT_ENABLED,
                "C_LOW":  PATTERN_C_LOW_ENABLED,
            }.get(p, False)

        match: Optional[PatternMatch] = None
        for det in (detect_pattern_a, detect_pattern_b, detect_pattern_c):
            cand = det(bars, bb_upper, bb_lower, bb_mid, pip_size)
            if cand is None:
                continue
            if not _direction_enabled(cand.pattern):
                continue
            # Direction-specific open-position gate.
            if cand.direction == "BUY" and has_open_long:
                continue
            if cand.direction == "SELL" and has_open_short:
                continue
            match = cand
            break
        if match is None:
            return None

        # Trend-suppression gate: counter-trend reversal entries against a
        # clean H1 trend produced today's 5-LONG-into-downtrend mistake.
        # Asymmetric: only block the wrong-side combination.
        if TREND_SUPPRESSION_ENABLED:
            h1_candles = trend_detection.load_h1_candles_from_cache(symbol)
            trend_dir, trend_details = trend_detection.is_clean_trend(symbol, h1_candles)
            blocked = (
                (match.direction == "BUY"  and trend_dir == "DOWN") or
                (match.direction == "SELL" and trend_dir == "UP")
            )
            if blocked:
                logger.info(
                    "[BB_REV_L] %s %s entry suppressed — clean H1 %s trend in play "
                    "(price=%.2f ema50=%.2f ema21=%.2f macd_hist=%.4f directional=%d/%d)",
                    match.pattern, match.direction, trend_dir,
                    trend_details.get("current_price", 0.0),
                    trend_details.get("ema50", 0.0),
                    trend_details.get("ema21", 0.0),
                    trend_details.get("macd_hist", 0.0),
                    trend_details.get("directional_count", 0),
                    trend_details.get("lookback", 0),
                )
                return None

        # SL distance reject — extended moves with bad R:R skipped.
        if match.sl_pips > MAX_SL_PIPS:
            logger.info(
                "[BB_REV_L] %s %s rejected — SL %.1fp > MAX_SL_PIPS %.1f (entry=%.1f)",
                match.pattern, match.direction, match.sl_pips, MAX_SL_PIPS,
                match.entry_price,
            )
            return None

        # Compute TP tiers
        tp1, tp2, tp3 = compute_tp_levels(
            match, bb_upper, bb_lower, bb_mid,
            session_extreme_so_far if session_extreme_so_far is not None else match.entry_price,
            pip_size,
        )

        # v2 exit policy: single exit at TP2 (opposite Bollinger Band).
        # TP1 / TP3 are kept in the decision debug for retrospective
        # analysis but the executor uses TP2 as the take-profit level.
        if match.direction == "SELL":
            tp_pips = (match.entry_price - tp2) / pip_size
        else:
            tp_pips = (tp2 - match.entry_price) / pip_size
        if tp_pips <= 0:
            logger.warning(
                "[BB_REV_L] %s rejected — TP2 on wrong side (entry=%.1f tp2=%.1f)",
                match.pattern, match.entry_price, tp2,
            )
            return None

        # Fixed size per .env TRADE_SIZE; risk varies by SL distance.
        # RISK_GBP is retained as dead config (left in env for forward compat)
        # but is no longer used to derive the order size.

        try:
            from strategy_logic import StrategyDecision
        except Exception as e:
            logger.error("[BB_REV_L] StrategyDecision import failed: %s", e)
            return None

        decision_mode = MODE_NAME if match.direction == "BUY" else MODE_NAME_SHORT
        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="BB_REV_L",
            signal=match.direction,
            mode=decision_mode,
            entry=match.entry_price,
            sl=round(float(match.sl_pips), 2),
            tp=round(float(tp_pips), 2),
            use_trailing_stop=False,
            reason=f"bb_rev_l_{match.pattern.lower()}: {match.notes}",
            debug={
                "pattern": match.pattern,
                "bar_ts": match.detect_bar_ts.isoformat(),
                "extreme_pierce": match.extreme_pierce,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
                "bb_mid": bb_mid,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "sl_price_abs": match.sl_price,
            },
            pip_size=pip_size,
        )
        with self._lock:
            self._trades_today[date_key] = taken + 1

        logger.info(
            "[BB_REV_L] %s ENTRY %s @ %.1f | SL=%.1fp TP=%.1fp | %s",
            match.pattern, match.direction, match.entry_price,
            match.sl_pips, tp_pips, match.notes,
        )
        return decision


# Singleton
strategy = GbpUsdBbReversalLongStrategy()


# ─── Helpers for callers ──────────────────────────────────────────────────
def bb_20_2(closes: Sequence[float]) -> Tuple[float, float, float]:
    """Return (lower, mid, upper) for last 20 closes. SMA + 2 std."""
    if len(closes) < 20:
        raise ValueError("need at least 20 closes for BB(20,2)")
    window = list(closes[-20:])
    mid = sum(window) / 20.0
    var = sum((c - mid) ** 2 for c in window) / 20.0
    std = var ** 0.5
    return mid - 2 * std, mid, mid + 2 * std
