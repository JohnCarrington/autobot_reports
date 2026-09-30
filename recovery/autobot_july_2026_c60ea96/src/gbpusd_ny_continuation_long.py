"""
gbpusd_ny_continuation_long.py — NY-open momentum continuation on
GBPUSD 5m. Bidirectional (LONG + SHORT mirrors) as of 2026-04-28.

At 12:30 UTC, classify the London session (06:45-12:25 UTC):

  DIRECTIONAL UP   — range >= 25p AND close in upper 30% AND net up
  DIRECTIONAL DOWN — range >= 25p AND close in lower 30% AND net down
  Otherwise        — disarmed for the day

If UP, arm a LONG continuation: wait for a >=20% pullback from the
London close, then a bullish reversal candle that recovers >=5p from
the pullback low. Enter at the reversal candle's close. SL: pullback
low - 3p. TP: london_high + 0.5 * london_range.

If DOWN, arm a SHORT continuation (geometric mirror): wait for a
>=20% rally from the London close, then a bearish reversal candle
that drops >=5p from the rally high. SL: rally high + 3p. TP:
london_low - 0.5 * london_range.

LONG and SHORT are mutually exclusive within a day (London is one or
the other) — one directional arming per day, one trade per day.

Mode tags differ by direction so the executor's dedup is per-side:
  LONG  → GBPUSD_NY_CONTINUATION_L
  SHORT → GBPUSD_NY_CONTINUATION_L_S

Reads London bars directly from the 5m candle archive at
data/candles/GBPUSD/<date>.csv (same source as
GBPUSD_OVERNIGHT_LEVEL_SWEEP).
"""
from __future__ import annotations

import csv
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_ny_continuation_l")

MODE_NAME       = "GBPUSD_NY_CONTINUATION_L"     # LONG (continuation of UP London)
MODE_NAME_SHORT = "GBPUSD_NY_CONTINUATION_L_S"   # SHORT (continuation of DOWN London)
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
ENABLED = _env_bool("NY_CONTINUATION_L_ENABLED", "1")
RISK_GBP = float(os.getenv("NY_CONTINUATION_L_RISK_GBP", "5.0") or 5.0)

LONDON_MIN_RANGE_PIPS    = float(os.getenv("NY_CONTINUATION_L_LONDON_MIN_RANGE_PIPS", "25") or 25.0)
LONDON_DIRECTIONAL_FRAC  = float(os.getenv("NY_CONTINUATION_L_LONDON_DIRECTIONAL_FRAC", "0.70") or 0.70)
PULLBACK_FRAC            = float(os.getenv("NY_CONTINUATION_L_PULLBACK_FRAC", "0.20") or 0.20)
RECOVERY_PIPS            = float(os.getenv("NY_CONTINUATION_L_RECOVERY_PIPS", "5") or 5.0)
MIN_BODY_RATIO           = float(os.getenv("NY_CONTINUATION_L_MIN_BODY_RATIO", "0.50") or 0.50)
MIN_BAR_RANGE_PIPS       = float(os.getenv("NY_CONTINUATION_L_MIN_BAR_RANGE_PIPS", "5") or 5.0)
MAX_SL_PIPS              = float(os.getenv("NY_CONTINUATION_L_MAX_SL_PIPS", "25") or 25.0)
TP_EXTENSION_FRAC        = float(os.getenv("NY_CONTINUATION_L_TP_EXTENSION_FRAC", "0.50") or 0.50)
PULLBACK_TIMEOUT_UTC     = _parse_hhmm(os.getenv("NY_CONTINUATION_L_PULLBACK_TIMEOUT_UTC", "14:00"), dtime(14, 0))
CONFIRMATION_TIMEOUT_MIN = int(os.getenv("NY_CONTINUATION_L_CONFIRMATION_TIMEOUT_MIN", "60") or 60)

WIN_START = _parse_hhmm(os.getenv("NY_CONTINUATION_L_WINDOW_START_UTC", "12:30"), dtime(12, 30))
WIN_END   = _parse_hhmm(os.getenv("NY_CONTINUATION_L_WINDOW_END_UTC",   "15:30"), dtime(15, 30))

# London session window — fixed by the strategy definition (not env).
LONDON_START = dtime(6, 45)
LONDON_END   = dtime(12, 25)  # last bar at 12:25 (5m bar covers 12:25-12:30)

SL_BUFFER_PIPS = 3.0

DEFAULT_CANDLE_ARCHIVE = Path(
    os.getenv("NY_CONTINUATION_L_CANDLE_DIR", "/opt/tradingbot/data/candles/GBPUSD")
)


# ─── Bar / Classification ────────────────────────────────────────────────
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
    def body_ratio(self) -> float:
        r = self.range
        return abs(self.close - self.open) / r if r > 0 else 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class LondonClassification:
    london_open: float
    london_high: float
    london_low: float
    london_close: float
    london_range_pips: float
    is_directional_up: bool
    is_directional_down: bool = False
    reason: str = ""  # human-readable disqualification reason if not directional


# ─── CSV reader ─────────────────────────────────────────────────────────
def _read_csv_bars(path: Path) -> List[Bar]:
    bars: List[Bar] = []
    if not path.exists():
        return bars
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                ts_s = (row.get("timestamp") or row.get("time") or "").strip()
                if not ts_s:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
                try:
                    bars.append(Bar(
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return bars
    bars.sort(key=lambda b: b.timestamp)
    return bars


# ─── Pure helper: classify London ────────────────────────────────────────
def classify_london_session(
    london_bars: Sequence[Bar],
    pip_size: float = PIP_SIZE,
    *,
    min_range_pips: float = LONDON_MIN_RANGE_PIPS,
    directional_frac: float = LONDON_DIRECTIONAL_FRAC,
) -> Optional[LondonClassification]:
    """Classify the 06:45-12:25 UTC London session.

    Returns LondonClassification with is_directional_up=True iff:
      london_range >= min_range_pips
      london_close - london_low >= directional_frac * london_range
      london_close > london_open
    Otherwise the classification is returned with is_directional_up=False
    and a human-readable `reason`.

    Returns None if `london_bars` is empty (caller can't proceed).
    """
    if not london_bars:
        return None
    london_open = london_bars[0].open
    london_high = max(b.high for b in london_bars)
    london_low = min(b.low for b in london_bars)
    london_close = london_bars[-1].close
    london_range = london_high - london_low
    range_pips = london_range / pip_size

    if range_pips < min_range_pips:
        return LondonClassification(
            london_open=london_open, london_high=london_high,
            london_low=london_low, london_close=london_close,
            london_range_pips=range_pips,
            is_directional_up=False, is_directional_down=False,
            reason=f"range_too_tight_{range_pips:.1f}p",
        )
    upper_zone_floor = london_low + directional_frac * london_range
    lower_zone_ceil  = london_low + (1.0 - directional_frac) * london_range

    is_up   = (london_close >= upper_zone_floor) and (london_close > london_open)
    is_down = (london_close <= lower_zone_ceil)  and (london_close < london_open)

    if is_up:
        return LondonClassification(
            london_open=london_open, london_high=london_high,
            london_low=london_low, london_close=london_close,
            london_range_pips=range_pips,
            is_directional_up=True, is_directional_down=False,
            reason="",
        )
    if is_down:
        return LondonClassification(
            london_open=london_open, london_high=london_high,
            london_low=london_low, london_close=london_close,
            london_range_pips=range_pips,
            is_directional_up=False, is_directional_down=True,
            reason="",
        )
    return LondonClassification(
        london_open=london_open, london_high=london_high,
        london_low=london_low, london_close=london_close,
        london_range_pips=range_pips,
        is_directional_up=False, is_directional_down=False,
        reason="not_directional",
    )


def load_london_session_bars(
    target_date_utc: date,
    candle_archive_path: Optional[Path] = None,
) -> List[Bar]:
    """Read 5m bars from 06:45 UTC up to (but not including) 12:30 UTC of
    `target_date_utc`. The 12:25 bar is included; the 12:30 bar (which
    starts the NY window) is not.
    """
    base = Path(candle_archive_path) if candle_archive_path else DEFAULT_CANDLE_ARCHIVE
    bars = _read_csv_bars(base / f"{target_date_utc.isoformat()}.csv")
    start = datetime.combine(target_date_utc, LONDON_START, tzinfo=timezone.utc)
    end = datetime.combine(target_date_utc, WIN_START, tzinfo=timezone.utc)
    return [b for b in bars if start <= b.timestamp < end]


# ─── Per-day state ──────────────────────────────────────────────────────
PHASE_UNARMED      = "UNARMED"   # before init at 12:30
PHASE_ARMED        = "ARMED"
PHASE_PULLED_BACK  = "PULLED_BACK"
PHASE_ENTERED      = "ENTERED"
PHASE_DONE         = "DONE"


@dataclass
class DayState:
    date_key: str
    initialized: bool = False
    phase: str = PHASE_UNARMED
    direction: str = ""                          # "BUY" or "SELL" once armed
    london: Optional[LondonClassification] = None
    # Stored extreme of the pullback (LONG) / rally (SHORT) — name kept for compat.
    pullback_low: Optional[float] = None
    pullback_time: Optional[datetime] = None
    entered: bool = False


# ─── Strategy class ─────────────────────────────────────────────────────
class GbpUsdNyContinuationLongStrategy:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, DayState] = {}

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

    def _ensure_state(self, date_key: str) -> DayState:
        st = self._states.get(date_key)
        if st is None:
            st = DayState(date_key=date_key)
            self._states[date_key] = st
        return st

    def _ensure_init(
        self,
        st: DayState,
        target_date: date,
        archive: Optional[Path],
    ) -> None:
        if st.initialized:
            return
        st.initialized = True
        london_bars = load_london_session_bars(target_date, archive)
        cls = classify_london_session(london_bars)
        if cls is None:
            logger.info("[NY_CONTINUATION_L] %s — no London bars; disarming.", st.date_key)
            st.phase = PHASE_DONE
            return
        st.london = cls
        if cls.is_directional_up:
            st.direction = "BUY"
        elif cls.is_directional_down:
            st.direction = "SELL"
        else:
            logger.info(
                "[NY_CONTINUATION_L] %s London not directional (%s) "
                "[range=%.1fp open=%.1f close=%.1f] — disarming.",
                st.date_key, cls.reason, cls.london_range_pips,
                cls.london_open, cls.london_close,
            )
            st.phase = PHASE_DONE
            return
        st.phase = PHASE_ARMED
        logger.info(
            "[NY_CONTINUATION_L] %s ARMED %s [range=%.1fp open=%.1f high=%.1f "
            "low=%.1f close=%.1f] window=%s-%s UTC",
            st.date_key, st.direction, cls.london_range_pips,
            cls.london_open, cls.london_high, cls.london_low, cls.london_close,
            WIN_START.strftime("%H:%M"), WIN_END.strftime("%H:%M"),
        )

    def evaluate(
        self,
        symbol: str,
        epic: str,
        ts: datetime,
        bars: Sequence[Bar],
        pip_size: float = PIP_SIZE,
        has_open_long: bool = False,
        has_open_short: bool = False,
        candle_archive_path: Optional[Path] = None,
    ) -> Optional["StrategyDecision"]:  # type: ignore[name-defined]
        """London is either UP or DOWN, so a day's arming is one direction
        only. The matching ``has_open_*`` flag blocks re-entry for that
        side."""
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if not bars:
            return None
        ts = self._utc(ts)
        if not self._in_window(ts):
            return None
        date_key = self._date_key(ts)
        target_date = ts.date()

        with self._lock:
            st = self._ensure_state(date_key)
            self._ensure_init(st, target_date, candle_archive_path)
            if st.phase in (PHASE_DONE, PHASE_ENTERED) or st.entered:
                return None
            if st.london is None or st.direction not in ("BUY", "SELL"):
                return None
            # Direction-specific open-position gate.
            if st.direction == "BUY" and has_open_long:
                return None
            if st.direction == "SELL" and has_open_short:
                return None

        bN = bars[-1]
        bar_close_ts = bN.timestamp + timedelta(minutes=5)
        if bar_close_ts.astimezone(timezone.utc).date() != target_date:
            return None

        pip = pip_size or PIP_SIZE
        cls = st.london
        london_range = cls.london_high - cls.london_low
        is_long = st.direction == "BUY"

        with self._lock:
            # ARMED → PULLED_BACK / RALLIED
            if st.phase == PHASE_ARMED:
                if bN.timestamp.astimezone(timezone.utc).time() >= PULLBACK_TIMEOUT_UTC:
                    logger.info(
                        "[NY_CONTINUATION_L] %s %s pullback/rally timeout (%s) — done.",
                        date_key, st.direction, PULLBACK_TIMEOUT_UTC.strftime("%H:%M"),
                    )
                    st.phase = PHASE_DONE
                    return None
                if is_long:
                    threshold = cls.london_close - PULLBACK_FRAC * london_range
                    if bN.low <= threshold:
                        st.phase = PHASE_PULLED_BACK
                        st.pullback_low = bN.low
                        st.pullback_time = bN.timestamp
                        logger.info(
                            "[NY_CONTINUATION_L] %s PULLED_BACK bar=%s low=%.1f "
                            "(threshold=%.1f, %.1fp from close)",
                            date_key, bN.timestamp.strftime("%H:%M"),
                            bN.low, threshold,
                            (cls.london_close - bN.low) / pip,
                        )
                else:
                    threshold = cls.london_close + PULLBACK_FRAC * london_range
                    if bN.high >= threshold:
                        st.phase = PHASE_PULLED_BACK  # phase tag reused — "rallied"
                        st.pullback_low = bN.high     # name kept; stores rally extreme
                        st.pullback_time = bN.timestamp
                        logger.info(
                            "[NY_CONTINUATION_L] %s RALLIED bar=%s high=%.1f "
                            "(threshold=%.1f, %.1fp from close)",
                            date_key, bN.timestamp.strftime("%H:%M"),
                            bN.high, threshold,
                            (bN.high - cls.london_close) / pip,
                        )
                return None

            # PULLED_BACK / RALLIED → ENTERED (or DONE on confirm timeout)
            if st.phase == PHASE_PULLED_BACK:
                if st.pullback_time is not None and (
                    bar_close_ts - st.pullback_time
                ) > timedelta(minutes=CONFIRMATION_TIMEOUT_MIN):
                    logger.info(
                        "[NY_CONTINUATION_L] %s %s confirmation timeout (>%dmin) — done.",
                        date_key, st.direction, CONFIRMATION_TIMEOUT_MIN,
                    )
                    st.phase = PHASE_DONE
                    return None

                cond_after = (
                    st.pullback_time is not None
                    and bar_close_ts > st.pullback_time
                )
                cond_body = bN.body_ratio >= MIN_BODY_RATIO
                cond_range = bN.range >= MIN_BAR_RANGE_PIPS * pip
                if is_long:
                    cond_recover = bN.close >= st.pullback_low + RECOVERY_PIPS * pip
                    cond_dir = bN.is_bullish
                else:
                    cond_recover = bN.close <= st.pullback_low - RECOVERY_PIPS * pip
                    cond_dir = bN.is_bearish
                if not (cond_after and cond_recover and cond_dir and cond_body and cond_range):
                    return None

                entry = bN.close
                if is_long:
                    sl_price = st.pullback_low - SL_BUFFER_PIPS * pip
                    sl_pips = (entry - sl_price) / pip
                    tp_price = cls.london_high + TP_EXTENSION_FRAC * london_range
                    tp_pips = (tp_price - entry) / pip
                else:
                    sl_price = st.pullback_low + SL_BUFFER_PIPS * pip
                    sl_pips = (sl_price - entry) / pip
                    tp_price = cls.london_low - TP_EXTENSION_FRAC * london_range
                    tp_pips = (entry - tp_price) / pip

                if sl_pips <= 0 or tp_pips <= 0:
                    return None
                if sl_pips > MAX_SL_PIPS:
                    logger.info(
                        "[NY_CONTINUATION_L] %s %s confirmation rejected — SL %.1fp > MAX %.1fp",
                        date_key, st.direction, sl_pips, MAX_SL_PIPS,
                    )
                    return None

                # Fixed size per .env TRADE_SIZE; risk varies by SL distance.
                try:
                    from strategy_logic import StrategyDecision
                except Exception as e:
                    logger.error("[NY_CONTINUATION_L] StrategyDecision import failed: %s", e)
                    return None

                anchor_label = "pullback" if is_long else "rally"
                notes = (
                    f"london=[{cls.london_open:.1f}→{cls.london_close:.1f} "
                    f"range={cls.london_range_pips:.1f}p hi={cls.london_high:.1f} lo={cls.london_low:.1f}]; "
                    f"{anchor_label}={st.pullback_low:.1f}@"
                    f"{st.pullback_time.strftime('%H:%M') if st.pullback_time else '?'}; "
                    f"reversal close={entry:.1f} body_ratio={bN.body_ratio:.2f} "
                    f"range={bN.range:.1f}p"
                )
                decision_mode = MODE_NAME if is_long else MODE_NAME_SHORT
                decision = StrategyDecision(
                    symbol="GBPUSD",
                    regime="NY_CONTINUATION_L",
                    signal=st.direction,
                    mode=decision_mode,
                    entry=entry,
                    sl=round(float(sl_pips), 2),
                    tp=round(float(tp_pips), 2),
                    use_trailing_stop=False,
                    reason=f"ny_continuation_{'long' if is_long else 'short'}: {notes}",
                    debug={
                        "side": st.direction,
                        "london_open": cls.london_open,
                        "london_high": cls.london_high,
                        "london_low": cls.london_low,
                        "london_close": cls.london_close,
                        "london_range_pips": cls.london_range_pips,
                        "anchor_extreme": st.pullback_low,
                        "anchor_time": st.pullback_time.isoformat() if st.pullback_time else None,
                        "sl_price_abs": sl_price,
                        "tp_price_abs": tp_price,
                        "bar_ts": bN.timestamp.isoformat(),
                    },
                    pip_size=pip,
                )
                st.phase = PHASE_ENTERED
                st.entered = True
                logger.info(
                    "[NY_CONTINUATION_L] %s ENTRY %s @ %.1f | SL=%.1fp TP=%.1fp | %s",
                    date_key, st.direction, entry, sl_pips, tp_pips, notes,
                )
                return decision

            return None

    def on_position_closed(
        self,
        pos_key_or_epic: str = "",
        exit_price: Any = None,
        pnl_pips: Any = None,
        close_reason: str = "",
        mode: str = "",
        ts: Optional[datetime] = None,
    ) -> None:
        """Mark today DONE on close. One trade per day; never re-arm."""
        if mode and str(mode).upper() not in (MODE_NAME, MODE_NAME_SHORT):
            return
        now = ts or datetime.now(timezone.utc)
        date_key = self._date_key(self._utc(now))
        with self._lock:
            st = self._states.get(date_key)
            if st is None:
                return
            st.phase = PHASE_DONE


# Singleton
strategy = GbpUsdNyContinuationLongStrategy()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
