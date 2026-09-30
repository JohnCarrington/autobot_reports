"""
gbpusd_big_rev.py — extended-Bollinger-pierce + strong-reversal pattern
on GBPUSD 5m, designed to catch 30-40 pip reversal moves twice per day.

Single setup. Tight definition. Two windows: 06:45-11:00 UTC (London),
12:30-15:00 UTC (NY). One trade per window, max two per day.

Detection on each closed 5m bar inside an active window:

LOWER BAND (LONG):
  1. Bar N-1 closes below the BB lower band (committed beyond, not just wick):
       bar_{N-1}.close < BB_lower(N-1)
  2. Bar N-1 has body ratio >= 0.50 (committed bearish move down)
  3. Bar N is a strong bullish reversal:
       bar_N.close > bar_N.open
       bar_N.body / bar_N.range >= 0.60
       bar_N.close > BB_lower(N)               (closes back inside)
       bar_N.close > bar_{N-1}.close           (closes above prior)
  4. Bar N's range >= MIN_REVERSAL_RANGE_PIPS  (real reversal candle)
  5. (BB_mid - BB_lower) at bar N >= MIN_BB_WIDTH_PIPS
       — the "extended" filter: only fire when the geometry has room
         to run to the opposite band

  Entry: bar N close
  SL: bar N-1 low - 3 pips
  TP: BB_upper at bar N (the opposite band)

UPPER BAND (SHORT) — mirror everything.

Common rules:
  - One trade per window. Max 2 trades per day. One position open at a time.
  - Window strictly enforced for ENTRY; the position can run past window
    close (SL/TP work normally).
  - No briefing dependency, no regime filter, no news filter.
  - Position size: RISK_GBP / SL_pips, minimum 0.5.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # forward-reference target for return-type annotations
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_big_rev")

MODE_NAME = "GBPUSD_BIG_REV"
PIP_SIZE = 1.0  # GBPUSD: 1 IG point = 1 pip


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _parse_window(spec: str, default: Tuple[dtime, dtime]) -> Tuple[dtime, dtime]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", spec or "")
    if not m:
        return default
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    return dtime(h1, m1), dtime(h2, m2)


# ─── Config (env-tunable) ─────────────────────────────────────────────────
ENABLED = _env_bool("BIG_REV_ENABLED", "1")
RISK_GBP = float(os.getenv("BIG_REV_RISK_GBP", "5.0") or 5.0)

MIN_BB_WIDTH_PIPS = float(os.getenv("BIG_REV_MIN_BB_WIDTH_PIPS", "15") or 15.0)
MIN_REVERSAL_RANGE_PIPS = float(os.getenv("BIG_REV_MIN_REVERSAL_RANGE_PIPS", "6") or 6.0)

BAR_NM1_BODY_RATIO = 0.50      # bar N-1 body / range >= 0.50
# Bar N body_ratio relaxed 2026-04-25 from 0.60 → 0.50 after the prior
# validation funnel showed this gate was binding (87% of direction-
# matching reversal candidates dropped here on a wickier pair like GBPUSD).
BAR_N_BODY_RATIO   = float(os.getenv("BIG_REV_MIN_BAR_N_BODY_RATIO", "0.50") or 0.50)
SL_BUFFER_PIPS     = 3.0       # SL = pierce-extreme ± 3 pips

W_LONDON_START, W_LONDON_END = _parse_window(
    os.getenv("BIG_REV_W_LONDON", "06:45-11:00"), (dtime(6, 45), dtime(11, 0)),
)
W_NY_START, W_NY_END = _parse_window(
    os.getenv("BIG_REV_W_NY", "12:30-15:00"), (dtime(12, 30), dtime(15, 0)),
)


# ─── Bar ─────────────────────────────────────────────────────────────────
@dataclass
class Bar:
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
        return self.close - self.open

    @property
    def body_ratio(self) -> float:
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
    direction: str           # "BUY" or "SELL"
    entry_price: float
    sl_price: float
    tp_price: float
    sl_pips: float
    tp_pips: float
    detect_bar_ts: datetime
    bb_width_pips: float
    notes: str = ""


# ─── Detector (pure function over bars + BBs at bar N close) ─────────────
def detect_big_rev(
    bars: Sequence[Bar],
    bb_upper_n: float, bb_lower_n: float, bb_mid_n: float,
    bb_upper_nm1: float, bb_lower_nm1: float,
    pip_size: float = PIP_SIZE,
) -> Optional[PatternMatch]:
    """Run the extended-pierce + reversal detector.

    Args:
        bars: at minimum bars[-2] and bars[-1] (= bar N-1 and bar N).
        bb_*_n: Bollinger bands at the close of bar N (entry bar).
        bb_*_nm1: Bollinger lower/upper at the close of bar N-1 (the
            piercing bar). Required because the band moves with each
            close and we evaluate the pierce against the band at that
            bar's own close, not the entry bar's.

    Returns PatternMatch or None.
    """
    if len(bars) < 2:
        return None
    bN = bars[-1]
    bNm1 = bars[-2]

    # ---- LOWER BAND → LONG ----
    if (
        bNm1.close < bb_lower_nm1                                 # 1. closed beyond lower
        and bNm1.body_ratio >= BAR_NM1_BODY_RATIO                 # 2. committed bearish
        and bN.is_bullish                                         # 3a. bullish reversal
        and bN.body_ratio >= BAR_N_BODY_RATIO                     # 3b. strong body
        and bN.close > bb_lower_n                                 # 3c. closes inside bands
        and bN.close > bNm1.close                                 # 3d. closes above prior
        and bN.range >= MIN_REVERSAL_RANGE_PIPS * pip_size        # 4. real reversal candle
        and (bb_mid_n - bb_lower_n) >= MIN_BB_WIDTH_PIPS * pip_size  # 5. extended geometry
    ):
        sl_price = bNm1.low - SL_BUFFER_PIPS * pip_size
        entry = bN.close
        tp_price = bb_upper_n
        sl_pips = (entry - sl_price) / pip_size
        tp_pips = (tp_price - entry) / pip_size
        if sl_pips <= 0 or tp_pips <= 0:
            return None
        return PatternMatch(
            direction="BUY",
            entry_price=entry,
            sl_price=sl_price,
            tp_price=tp_price,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            detect_bar_ts=bN.timestamp,
            bb_width_pips=(bb_mid_n - bb_lower_n) / pip_size,
            notes=(
                f"lower_pierce: bNm1.close={bNm1.close:.1f} < BBl(N-1)={bb_lower_nm1:.1f} "
                f"body_ratio={bNm1.body_ratio:.2f}; bN bullish reversal "
                f"close={bN.close:.1f} body_ratio={bN.body_ratio:.2f} "
                f"range={bN.range:.1f}p; mid-lower={bb_mid_n - bb_lower_n:.1f}p"
            ),
        )

    # ---- UPPER BAND → SHORT (mirror) ----
    if (
        bNm1.close > bb_upper_nm1                                 # 1. closed beyond upper
        and bNm1.body_ratio >= BAR_NM1_BODY_RATIO                 # 2. committed bullish
        and bN.is_bearish                                         # 3a. bearish reversal
        and bN.body_ratio >= BAR_N_BODY_RATIO                     # 3b. strong body
        and bN.close < bb_upper_n                                 # 3c. closes inside
        and bN.close < bNm1.close                                 # 3d. closes below prior
        and bN.range >= MIN_REVERSAL_RANGE_PIPS * pip_size        # 4. real reversal candle
        and (bb_upper_n - bb_mid_n) >= MIN_BB_WIDTH_PIPS * pip_size  # 5. extended geometry
    ):
        sl_price = bNm1.high + SL_BUFFER_PIPS * pip_size
        entry = bN.close
        tp_price = bb_lower_n
        sl_pips = (sl_price - entry) / pip_size
        tp_pips = (entry - tp_price) / pip_size
        if sl_pips <= 0 or tp_pips <= 0:
            return None
        return PatternMatch(
            direction="SELL",
            entry_price=entry,
            sl_price=sl_price,
            tp_price=tp_price,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            detect_bar_ts=bN.timestamp,
            bb_width_pips=(bb_upper_n - bb_mid_n) / pip_size,
            notes=(
                f"upper_pierce: bNm1.close={bNm1.close:.1f} > BBu(N-1)={bb_upper_nm1:.1f} "
                f"body_ratio={bNm1.body_ratio:.2f}; bN bearish reversal "
                f"close={bN.close:.1f} body_ratio={bN.body_ratio:.2f} "
                f"range={bN.range:.1f}p; upper-mid={bb_upper_n - bb_mid_n:.1f}p"
            ),
        )

    return None


# ─── Window helpers ──────────────────────────────────────────────────────
def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def current_window_label(ts: datetime) -> Optional[str]:
    ts = _utc(ts)
    if ts.weekday() >= 5:
        return None
    t = ts.time()
    if W_LONDON_START <= t < W_LONDON_END:
        return "LONDON"
    if W_NY_START <= t < W_NY_END:
        return "NY"
    return None


def is_window_active(ts: datetime) -> bool:
    return current_window_label(ts) is not None


def _window_bounds_utc(date_utc: datetime, window: str) -> Tuple[datetime, datetime]:
    base = _utc(date_utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "LONDON":
        return (
            base.replace(hour=W_LONDON_START.hour, minute=W_LONDON_START.minute),
            base.replace(hour=W_LONDON_END.hour, minute=W_LONDON_END.minute),
        )
    if window == "NY":
        return (
            base.replace(hour=W_NY_START.hour, minute=W_NY_START.minute),
            base.replace(hour=W_NY_END.hour, minute=W_NY_END.minute),
        )
    raise ValueError(f"unknown window {window!r}")


# ─── BB(20, 2) helper ────────────────────────────────────────────────────
def bb_20_2(closes: Sequence[float]) -> Tuple[float, float, float]:
    """Return (lower, mid, upper). Need 20+ closes."""
    if len(closes) < 20:
        raise ValueError("need at least 20 closes for BB(20,2)")
    window = list(closes[-20:])
    mid = sum(window) / 20.0
    var = sum((c - mid) ** 2 for c in window) / 20.0
    std = var ** 0.5
    return mid - 2 * std, mid, mid + 2 * std


# ─── Strategy class ──────────────────────────────────────────────────────
class GbpUsdBigRevStrategy:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (date, window) -> True once a trade has been fired in that window
        self._fired: Dict[Tuple[str, str], bool] = {}
        # (date, window) -> last-seen 5m bar timestamp (dedup)
        self._last_seen_bar: Dict[Tuple[str, str], datetime] = {}

    @staticmethod
    def _date_key(ts: datetime) -> str:
        return _utc(ts).strftime("%Y-%m-%d")

    def evaluate(
        self,
        symbol: str,
        epic: str,
        ts: datetime,
        bars: Sequence[Bar],
        bb_upper_n: float, bb_lower_n: float, bb_mid_n: float,
        bb_upper_nm1: float, bb_lower_nm1: float,
        pip_size: float = PIP_SIZE,
        has_open_position: bool = False,
    ) -> Optional["StrategyDecision"]:  # type: ignore[name-defined]
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if has_open_position:
            return None

        ts = _utc(ts)
        window = current_window_label(ts)
        if window is None:
            return None

        date = self._date_key(ts)
        with self._lock:
            if self._fired.get((date, window)):
                return None
            # Dedup: only evaluate each closed 5m bar once per window
            last_seen = self._last_seen_bar.get((date, window))

        if not bars:
            return None
        bN_ts = bars[-1].timestamp
        if last_seen is not None and bN_ts <= last_seen:
            return None
        with self._lock:
            self._last_seen_bar[(date, window)] = bN_ts

        match = detect_big_rev(
            bars,
            bb_upper_n, bb_lower_n, bb_mid_n,
            bb_upper_nm1, bb_lower_nm1,
            pip_size,
        )
        if match is None:
            return None

        # Fixed size per .env TRADE_SIZE; risk varies by SL distance.

        try:
            from strategy_logic import StrategyDecision
        except Exception as e:
            logger.error("[BIG_REV] StrategyDecision import failed: %s", e)
            return None

        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="BIG_REV",
            signal=match.direction,
            mode=MODE_NAME,
            entry=match.entry_price,
            sl=round(float(match.sl_pips), 2),
            tp=round(float(match.tp_pips), 2),
            use_trailing_stop=False,
            reason=f"big_rev_{window.lower()}: {match.notes}",
            debug={
                "window": window,
                "bar_ts": match.detect_bar_ts.isoformat(),
                "bb_upper": bb_upper_n,
                "bb_lower": bb_lower_n,
                "bb_mid": bb_mid_n,
                "bb_width_pips": match.bb_width_pips,
                "sl_price_abs": match.sl_price,
                "tp_price_abs": match.tp_price,
            },
            pip_size=pip_size,
        )
        with self._lock:
            self._fired[(date, window)] = True
        logger.info(
            "[BIG_REV] %s %s ENTRY @ %.1f | SL=%.1fp TP=%.1fp bb_width=%.1fp | %s",
            window, match.direction, match.entry_price,
            match.sl_pips, match.tp_pips, match.bb_width_pips, match.notes,
        )
        return decision

    def on_position_closed(self, *args, **kwargs) -> None:
        """No-op for now — single-shot per window means the window can't
        re-arm even after a position closes within the window. Kept for
        the autobot close-callback contract symmetry."""
        return


strategy = GbpUsdBigRevStrategy()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
