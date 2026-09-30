"""
gbpusd_bb_premirror_long.py — Pattern B (pre-pierce mirror) at the
Bollinger Bands on GBPUSD 5m. Bidirectional (LONG + SHORT mirrors).

The shape (LONG): a strong bearish candle approaches but does NOT
pierce the lower BB; the next candle mirrors it with a similar-
magnitude bullish body that closes back near (or above) bar N's open.
The two-bar structure is a tweezer-bottom just above the band.
The SHORT mirror is the geometric inverse at the upper BB.

Geometry loosened from the original three-pattern definition (Pattern
B in gbpusd_bb_reversal_long.py — kept there as dead code):
  band proximity            5p → 8p
  bar N+1 body vs bar N     0.70 → 0.60
  mirror tolerance         2p → 5p

Entry: at close of bar N+1.
SL:    bar N's low (LONG) / high (SHORT) ± 3p (rejected if SL > 25p).
TP:    opposite band at the entry bar — BB_upper for LONG, BB_lower
       for SHORT.

Window 06:45-15:30 UTC weekdays. Max 4 trades/day per direction.
£5 risk per trade.

Mode tags differ by direction so the executor's dedup is per-side:
  LONG  → GBPUSD_BB_PREMIRROR_L
  SHORT → GBPUSD_BB_PREMIRROR_L_S
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_bb_premirror_l")

MODE_NAME       = "GBPUSD_BB_PREMIRROR_L"     # LONG (lower-band mirror)
MODE_NAME_SHORT = "GBPUSD_BB_PREMIRROR_L_S"   # SHORT (upper-band mirror)
PIP_SIZE = 1.0  # GBPUSD: 1 IG point = 1 pip


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _parse_hhmm(spec: str, default: dtime) -> dtime:
    try:
        h, m = spec.strip().split(":")
        return dtime(int(h), int(m))
    except Exception:
        return default


# ─── Config (env-tunable) ────────────────────────────────────────────────
ENABLED = _env_bool("BB_PREMIRROR_L_ENABLED", "1")

RISK_GBP            = float(os.getenv("BB_PREMIRROR_L_RISK_GBP", "5.0") or 5.0)
MAX_TRADES_PER_DAY  = int(os.getenv("BB_PREMIRROR_L_MAX_TRADES_PER_DAY", "4") or 4)
MAX_SL_PIPS         = float(os.getenv("BB_PREMIRROR_L_MAX_SL_PIPS", "25") or 25.0)

BAR_N_BODY_RATIO         = float(os.getenv("BB_PREMIRROR_L_BAR_N_BODY_RATIO", "0.50") or 0.50)
BAR_NP1_BODY_RATIO_OF_N  = float(os.getenv("BB_PREMIRROR_L_BAR_NP1_BODY_RATIO_OF_N", "0.60") or 0.60)
BAND_PROXIMITY_PIPS      = float(os.getenv("BB_PREMIRROR_L_BAND_PROXIMITY_PIPS", "8") or 8.0)
MIRROR_TOLERANCE_PIPS    = float(os.getenv("BB_PREMIRROR_L_MIRROR_TOLERANCE_PIPS", "5") or 5.0)

WIN_START = _parse_hhmm(os.getenv("BB_PREMIRROR_L_WINDOW_START_UTC", "06:45"), dtime(6, 45))
WIN_END   = _parse_hhmm(os.getenv("BB_PREMIRROR_L_WINDOW_END_UTC",   "15:30"), dtime(15, 30))

SL_BUFFER_PIPS = 3.0


# ─── Bar / PatternMatch ─────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. timestamp is the bar's open time, tz-aware UTC."""
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
        """Signed body: positive bullish, negative bearish."""
        return self.close - self.open

    @property
    def body_ratio(self) -> float:
        r = self.range
        return abs(self.body) / r if r > 0 else 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class PatternMatch:
    direction: str                # always "BUY" in this module
    entry_price: float
    sl_price: float               # absolute price
    sl_pips: float
    tp_price: float               # absolute price (BB_upper at entry bar)
    tp_pips: float
    detect_bar_ts: datetime       # bar N+1's timestamp
    bar_n_low: float              # SL anchor for debug
    notes: str = ""


# ─── Pure detector ──────────────────────────────────────────────────────
def detect_premirror_long(
    bars: Sequence[Bar],
    bb_lower_at_n_close: float,
    bb_upper_at_np1_close: float,
    pip_size: float = PIP_SIZE,
    *,
    bar_n_body_ratio: float = BAR_N_BODY_RATIO,
    bar_np1_body_ratio_of_n: float = BAR_NP1_BODY_RATIO_OF_N,
    band_proximity_pips: float = BAND_PROXIMITY_PIPS,
    mirror_tolerance_pips: float = MIRROR_TOLERANCE_PIPS,
    sl_buffer_pips: float = SL_BUFFER_PIPS,
    max_sl_pips: float = MAX_SL_PIPS,
) -> Optional[PatternMatch]:
    """Pre-pierce mirror reversal (LONG) at the lower BB.

    Inputs:
      bars                    — needs at least 2; bars[-2] = bar N, bars[-1] = bar N+1
      bb_lower_at_n_close     — BB_lower computed off closes ending at bar N
                                (i.e. excluding bar N+1)
      bb_upper_at_np1_close   — BB_upper computed off closes ending at bar N+1
                                (used as TP target)

    Conditions (all must hold):
      bar N:
        - bearish (close < open)
        - low > bb_lower_at_n_close            (didn't pierce — Pattern B differentiator)
        - body_ratio >= bar_n_body_ratio       (committed move)
        - 0 <= close - bb_lower_at_n_close <= band_proximity_pips
                                               (close approach within band proximity)
      bar N+1:
        - bullish (close > open)
        - |body| >= bar_np1_body_ratio_of_n * |bar N body|
        - close >= bar N.open - mirror_tolerance_pips
                                               (closes near or above bar N's open)

    Returns PatternMatch on success, else None.
    SL: bar N.low - sl_buffer_pips. Rejects if SL > max_sl_pips.
    TP: bb_upper_at_np1_close. Rejects if TP <= entry (defensive).
    """
    if len(bars) < 2:
        return None
    bN = bars[-2]
    bNp1 = bars[-1]

    # Bar N — bearish, no pierce, committed body, close approach.
    if not bN.is_bearish:
        return None
    if bN.low <= bb_lower_at_n_close:
        return None
    if bN.body_ratio < bar_n_body_ratio:
        return None
    close_to_band = bN.close - bb_lower_at_n_close
    if close_to_band < 0 or close_to_band > band_proximity_pips * pip_size:
        return None

    # Bar N+1 — bullish, mirror body, mirror close.
    if not bNp1.is_bullish:
        return None
    bN_body_abs = abs(bN.body)
    if bN_body_abs <= 0:
        return None
    if abs(bNp1.body) < bar_np1_body_ratio_of_n * bN_body_abs:
        return None
    if bNp1.close < bN.open - mirror_tolerance_pips * pip_size:
        return None

    # Geometry / risk.
    entry = bNp1.close
    sl_price = bN.low - sl_buffer_pips * pip_size
    sl_pips = (entry - sl_price) / pip_size
    if sl_pips <= 0:
        return None
    if sl_pips > max_sl_pips:
        return None

    tp_price = bb_upper_at_np1_close
    tp_pips = (tp_price - entry) / pip_size
    if tp_pips <= 0:
        return None

    notes = (
        f"bN[bear, body_ratio={bN.body_ratio:.2f}, close-BBl={close_to_band:.1f}p, "
        f"low-BBl={bN.low - bb_lower_at_n_close:.1f}p]; "
        f"bNp1[bull, |body|/|bN|={abs(bNp1.body)/bN_body_abs:.2f}, "
        f"close-bN.open={bNp1.close - bN.open:+.1f}p]; "
        f"BBu_entry={tp_price:.1f}"
    )
    return PatternMatch(
        direction="BUY",
        entry_price=entry,
        sl_price=sl_price,
        sl_pips=sl_pips,
        tp_price=tp_price,
        tp_pips=tp_pips,
        detect_bar_ts=bNp1.timestamp,
        bar_n_low=bN.low,
        notes=notes,
    )


def detect_premirror_short(
    bars: Sequence[Bar],
    bb_upper_at_n_close: float,
    bb_lower_at_np1_close: float,
    pip_size: float = PIP_SIZE,
    *,
    bar_n_body_ratio: float = BAR_N_BODY_RATIO,
    bar_np1_body_ratio_of_n: float = BAR_NP1_BODY_RATIO_OF_N,
    band_proximity_pips: float = BAND_PROXIMITY_PIPS,
    mirror_tolerance_pips: float = MIRROR_TOLERANCE_PIPS,
    sl_buffer_pips: float = SL_BUFFER_PIPS,
    max_sl_pips: float = MAX_SL_PIPS,
) -> Optional[PatternMatch]:
    """Pre-pierce mirror reversal (SHORT) at the upper BB. Geometric
    inverse of detect_premirror_long: bar N is a strong green that
    approaches but doesn't pierce BB_upper, bar N+1 is a comparable
    red mirror that closes near or below bar N's open.

    Inputs:
      bars                    — needs at least 2; bars[-2]=bar N, bars[-1]=bar N+1
      bb_upper_at_n_close     — BB_upper computed off closes ending at bar N
      bb_lower_at_np1_close   — BB_lower computed off closes ending at bar N+1
                                (used as TP target)
    """
    if len(bars) < 2:
        return None
    bN = bars[-2]
    bNp1 = bars[-1]

    # Bar N — bullish, no pierce, committed body, close approach.
    if not bN.is_bullish:
        return None
    if bN.high >= bb_upper_at_n_close:
        return None
    if bN.body_ratio < bar_n_body_ratio:
        return None
    close_to_band = bb_upper_at_n_close - bN.close
    if close_to_band < 0 or close_to_band > band_proximity_pips * pip_size:
        return None

    # Bar N+1 — bearish, mirror body, mirror close.
    if not bNp1.is_bearish:
        return None
    bN_body_abs = abs(bN.body)
    if bN_body_abs <= 0:
        return None
    if abs(bNp1.body) < bar_np1_body_ratio_of_n * bN_body_abs:
        return None
    if bNp1.close > bN.open + mirror_tolerance_pips * pip_size:
        return None

    # Geometry / risk.
    entry = bNp1.close
    sl_price = bN.high + sl_buffer_pips * pip_size
    sl_pips = (sl_price - entry) / pip_size
    if sl_pips <= 0:
        return None
    if sl_pips > max_sl_pips:
        return None

    tp_price = bb_lower_at_np1_close
    tp_pips = (entry - tp_price) / pip_size
    if tp_pips <= 0:
        return None

    notes = (
        f"bN[bull, body_ratio={bN.body_ratio:.2f}, BBu-close={close_to_band:.1f}p, "
        f"BBu-high={bb_upper_at_n_close - bN.high:.1f}p]; "
        f"bNp1[bear, |body|/|bN|={abs(bNp1.body)/bN_body_abs:.2f}, "
        f"close-bN.open={bNp1.close - bN.open:+.1f}p]; "
        f"BBl_entry={tp_price:.1f}"
    )
    return PatternMatch(
        direction="SELL",
        entry_price=entry,
        sl_price=sl_price,
        sl_pips=sl_pips,
        tp_price=tp_price,
        tp_pips=tp_pips,
        detect_bar_ts=bNp1.timestamp,
        bar_n_low=bN.high,  # SL anchor (high for SHORT). Field name kept for compat.
        notes=notes,
    )


# ─── Strategy class ─────────────────────────────────────────────────────
class GbpUsdBbPreMirrorLongStrategy:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._trades_today: Dict[str, int] = {}

    @staticmethod
    def _utc(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    @staticmethod
    def _date_key(ts: datetime) -> str:
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _in_window(ts: datetime) -> bool:
        ts = ts.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return WIN_START <= t < WIN_END

    def evaluate(
        self,
        symbol: str,
        epic: str,
        ts: datetime,
        bars: Sequence[Bar],
        pip_size: float,
        bb_lower_at_n_close: float,
        bb_upper_at_n_close: float,
        bb_lower_at_np1_close: float,
        bb_upper_at_np1_close: float,
        has_open_long: bool = False,
        has_open_short: bool = False,
    ) -> Optional["StrategyDecision"]:  # type: ignore[name-defined]
        """Called on each new closed 5m bar; bars[-1] is the just-closed
        bar. Runs the LONG and SHORT pre-pierce-mirror detectors
        independently. Direction-specific open-position gates: a
        ``has_open_long`` only blocks LONG matches; same for SHORT."""
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        ts = self._utc(ts)
        if not self._in_window(ts):
            return None

        date_key = self._date_key(ts)
        with self._lock:
            taken = self._trades_today.get(date_key, 0)
        if taken >= MAX_TRADES_PER_DAY:
            return None

        match: Optional[PatternMatch] = None
        if not has_open_long:
            match = detect_premirror_long(
                bars,
                bb_lower_at_n_close=bb_lower_at_n_close,
                bb_upper_at_np1_close=bb_upper_at_np1_close,
                pip_size=pip_size or PIP_SIZE,
            )
        if match is None and not has_open_short:
            match = detect_premirror_short(
                bars,
                bb_upper_at_n_close=bb_upper_at_n_close,
                bb_lower_at_np1_close=bb_lower_at_np1_close,
                pip_size=pip_size or PIP_SIZE,
            )
        if match is None:
            return None

        # Fixed size per .env TRADE_SIZE; risk varies by SL distance.
        try:
            from strategy_logic import StrategyDecision
        except Exception as e:
            logger.error("[BB_PREMIRROR_L] StrategyDecision import failed: %s", e)
            return None

        decision_mode = MODE_NAME if match.direction == "BUY" else MODE_NAME_SHORT
        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="BB_PREMIRROR_L",
            signal=match.direction,
            mode=decision_mode,
            entry=match.entry_price,
            sl=round(float(match.sl_pips), 2),
            tp=round(float(match.tp_pips), 2),
            use_trailing_stop=False,
            reason=f"bb_premirror_l: {match.notes}",
            debug={
                "bar_ts": match.detect_bar_ts.isoformat(),
                "sl_anchor": match.bar_n_low,
                "sl_price_abs": match.sl_price,
                "tp_price_abs": match.tp_price,
                "bb_lower_at_n_close": bb_lower_at_n_close,
                "bb_upper_at_n_close": bb_upper_at_n_close,
                "bb_lower_at_np1_close": bb_lower_at_np1_close,
                "bb_upper_at_np1_close": bb_upper_at_np1_close,
            },
            pip_size=pip_size or PIP_SIZE,
        )

        with self._lock:
            self._trades_today[date_key] = taken + 1

        logger.info(
            "[BB_PREMIRROR_L] ENTRY %s @ %.1f | SL=%.1fp TP=%.1fp | %s",
            match.direction, match.entry_price, match.sl_pips, match.tp_pips, match.notes,
        )
        return decision

    def on_position_closed(
        self,
        pos_key_or_epic: str = "",
        exit_price: Any = None,
        pnl_pips: Any = None,
        close_reason: str = "",
        mode: str = "",
        ts: Optional[datetime] = None,
    ) -> None:
        """Defensive cleanup hook. The day cap is decremented? No — we use
        a monotonic taken counter. On close we just log; the counter
        persists for the day so the cap holds against re-entry storms.
        """
        if mode and str(mode).upper() not in (MODE_NAME, MODE_NAME_SHORT):
            return
        # Intentional no-op for state. Logged for observability.
        logger.info(
            "[BB_PREMIRROR_L] on_position_closed mode=%s reason=%s pnl=%s",
            mode, close_reason, pnl_pips,
        )


# Singleton
strategy = GbpUsdBbPreMirrorLongStrategy()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
