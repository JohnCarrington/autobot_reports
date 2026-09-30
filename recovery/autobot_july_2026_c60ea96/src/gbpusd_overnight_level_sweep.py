"""
gbpusd_overnight_level_sweep.py — Overnight liquidity sweep + reversal
on GBPUSD 5m. Bidirectional (LONG + SHORT mirrors) as of 2026-04-28.

Identifies up to 5 swing-low levels and 5 swing-high levels in the
22:00-06:45 UTC overnight session (deduplicated to >=8p separation
between levels of each side), then watches the London open
(06:45-10:00 UTC) for a sweep of any level followed by a directional
reversal candle within 90 minutes:

  LONG  — sweep BELOW a low by >=1p, then bullish reversal candle.
          TP: next higher level, else overnight high.
  SHORT — sweep ABOVE a high by >=1p, then bearish reversal candle.
          TP: next lower level, else overnight low.

LONG and SHORT fire independently. Each side caps at one trade per day.

Mode tags differ by direction so executor dedup is per-side:
  LONG  → GBPUSD_OVERNIGHT_LEVEL_SWEEP
  SHORT → GBPUSD_OVERNIGHT_LEVEL_SWEEP_S

Coexists with REV_L, BIG_REV. No briefing/regime/news dependency —
the pattern is the filter.
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

logger = logging.getLogger("gbpusd_overnight_level_sweep")

MODE_NAME       = "GBPUSD_OVERNIGHT_LEVEL_SWEEP"     # LONG (sweep below low)
MODE_NAME_SHORT = "GBPUSD_OVERNIGHT_LEVEL_SWEEP_S"   # SHORT (sweep above high)
PIP_SIZE = 1.0  # GBPUSD: 1 IG point = 1 pip


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _parse_hhmm(spec: str, default: dtime) -> dtime:
    try:
        h, m = spec.strip().split(":")
        return dtime(int(h), int(m))
    except Exception:
        return default


# ─── Config ──────────────────────────────────────────────────────────────
ENABLED      = _env_bool("OVERNIGHT_SWEEP_ENABLED", "1")
ENABLE_LONG  = _env_bool("OVERNIGHT_SWEEP_ENABLE_LONG",  "1")
ENABLE_SHORT = _env_bool("OVERNIGHT_SWEEP_ENABLE_SHORT", "1")

RISK_GBP                  = float(os.getenv("OVERNIGHT_SWEEP_RISK_GBP", "5.0") or 5.0)
MIN_BODY_RATIO            = float(os.getenv("OVERNIGHT_SWEEP_MIN_BODY_RATIO", "0.40") or 0.40)
MIN_BAR_RANGE_PIPS        = float(os.getenv("OVERNIGHT_SWEEP_MIN_BAR_RANGE_PIPS", "4") or 4.0)
MAX_SL_PIPS               = float(os.getenv("OVERNIGHT_SWEEP_MAX_SL_PIPS", "25") or 25.0)
MIN_TP_PIPS               = float(os.getenv("OVERNIGHT_SWEEP_MIN_TP_PIPS", "8") or 8.0)
PIERCE_PIPS               = float(os.getenv("OVERNIGHT_SWEEP_PIERCE_PIPS", "1.0") or 1.0)
CONFIRM_TIMEOUT_MIN       = int(os.getenv("OVERNIGHT_SWEEP_CONFIRM_TIMEOUT_MIN", "90") or 90)
LEVEL_MIN_SEPARATION_PIPS = float(os.getenv("OVERNIGHT_SWEEP_LEVEL_MIN_SEPARATION_PIPS", "8") or 8.0)
MAX_LEVELS                = int(os.getenv("OVERNIGHT_SWEEP_MAX_LEVELS", "5") or 5)

WINDOW_START = _parse_hhmm(os.getenv("OVERNIGHT_SWEEP_WINDOW_START_UTC", "06:45"), dtime(6, 45))
WINDOW_END   = _parse_hhmm(os.getenv("OVERNIGHT_SWEEP_WINDOW_END_UTC",   "10:00"), dtime(10, 0))

OVERNIGHT_START = dtime(22, 0)  # prev-day 22:00 UTC
SL_BUFFER_PIPS  = 3.0

DEFAULT_CANDLE_ARCHIVE = Path(
    os.getenv("OVERNIGHT_SWEEP_CANDLE_DIR", "/opt/tradingbot/data/candles/GBPUSD")
)


# ─── Bar abstraction ─────────────────────────────────────────────────────
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


# ─── Level identification (pure function) ───────────────────────────────
def identify_overnight_lows(
    bars: List[Bar],
    min_separation_pips: float = LEVEL_MIN_SEPARATION_PIPS,
    max_levels: int = MAX_LEVELS,
    pip_size: float = PIP_SIZE,
) -> List[float]:
    """Return prices of significant swing lows in `bars`, ascending.

    A bar's low is a candidate iff it is the minimum within ±3 bars
    (truncated near boundaries — so the absolute low always qualifies).
    Candidates are deduplicated by walking ascending in price and
    accepting only those at least `min_separation_pips` away from
    anything already accepted; this guarantees the absolute low is
    always included and that no two retained levels are within the
    separation. The result is sorted ascending and capped at
    `max_levels` (the lowest-priced are kept).
    """
    if not bars:
        return []
    n = len(bars)
    candidates: List[float] = []
    for i in range(n):
        lo = max(0, i - 3)
        hi = min(n, i + 4)  # ±3 inclusive
        window_min = min(b.low for b in bars[lo:hi])
        if bars[i].low <= window_min:
            candidates.append(bars[i].low)
    if not candidates:
        # Defensive — the absolute low is always a local min within ±3,
        # so we should never reach here when bars is non-empty.
        return [min(b.low for b in bars)]

    sep = min_separation_pips * pip_size
    kept: List[float] = []
    # Process ascending in price so the lowest in any cluster always wins.
    for price in sorted(set(candidates)):
        if all(abs(k - price) >= sep for k in kept):
            kept.append(price)

    kept.sort()
    if len(kept) > max_levels:
        kept = kept[:max_levels]
    return kept


def identify_overnight_highs(
    bars: List[Bar],
    min_separation_pips: float = LEVEL_MIN_SEPARATION_PIPS,
    max_levels: int = MAX_LEVELS,
    pip_size: float = PIP_SIZE,
) -> List[float]:
    """Mirror of identify_overnight_lows — returns prices of significant
    swing highs in `bars`, descending. A bar's high is a candidate iff
    it is the maximum within ±3 bars. Deduplicates by walking
    descending in price and keeping the highest of each cluster.
    Result is descending; capped at max_levels (the highest-priced
    are kept).
    """
    if not bars:
        return []
    n = len(bars)
    candidates: List[float] = []
    for i in range(n):
        lo = max(0, i - 3)
        hi = min(n, i + 4)
        window_max = max(b.high for b in bars[lo:hi])
        if bars[i].high >= window_max:
            candidates.append(bars[i].high)
    if not candidates:
        return [max(b.high for b in bars)]

    sep = min_separation_pips * pip_size
    kept: List[float] = []
    # Process descending in price so the highest in any cluster always wins.
    for price in sorted(set(candidates), reverse=True):
        if all(abs(k - price) >= sep for k in kept):
            kept.append(price)

    kept.sort(reverse=True)
    if len(kept) > max_levels:
        kept = kept[:max_levels]
    return kept


def compute_overnight_session(
    target_date_utc: date,
    candle_archive_path: Optional[Path] = None,
) -> Tuple[List[Bar], List[float], List[float], Optional[float], Optional[float]]:
    """Read 22:00 prev-day to 06:45 today bars; return
    (bars, lows, highs, overnight_high, overnight_low)."""
    base = Path(candle_archive_path) if candle_archive_path else DEFAULT_CANDLE_ARCHIVE
    prev_day = target_date_utc - timedelta(days=1)
    start = datetime.combine(prev_day, OVERNIGHT_START, tzinfo=timezone.utc)
    end = datetime.combine(target_date_utc, WINDOW_START, tzinfo=timezone.utc)
    bars = (
        _read_csv_bars(base / f"{prev_day.isoformat()}.csv")
        + _read_csv_bars(base / f"{target_date_utc.isoformat()}.csv")
    )
    bars = [b for b in bars if start <= b.timestamp < end]
    if not bars:
        return [], [], [], None, None
    lows = identify_overnight_lows(bars, LEVEL_MIN_SEPARATION_PIPS, MAX_LEVELS, PIP_SIZE)
    highs = identify_overnight_highs(bars, LEVEL_MIN_SEPARATION_PIPS, MAX_LEVELS, PIP_SIZE)
    overnight_high = max(b.high for b in bars)
    overnight_low  = min(b.low for b in bars)
    return bars, lows, highs, overnight_high, overnight_low


# ─── Per-level / per-day state ──────────────────────────────────────────
PHASE_WAITING = "WAITING"
PHASE_SWEPT   = "SWEPT"
PHASE_DONE    = "DONE"


@dataclass
class LevelState:
    price: float
    phase: str = PHASE_WAITING
    sweep_extreme: Optional[float] = None
    sweep_time: Optional[datetime] = None


@dataclass
class DayState:
    date_key: str
    initialized: bool = False
    armed: bool = False
    overnight_high: Optional[float] = None
    overnight_low:  Optional[float] = None
    # LONG side — sweep below lows
    levels: List[float] = field(default_factory=list)
    level_states: List[LevelState] = field(default_factory=list)
    entered: bool = False
    # SHORT side — sweep above highs
    levels_high: List[float] = field(default_factory=list)
    level_states_high: List[LevelState] = field(default_factory=list)
    entered_short: bool = False


# ─── Strategy class ─────────────────────────────────────────────────────
class GbpUsdOvernightLevelSweepStrategy:
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
        return WINDOW_START <= t < WINDOW_END

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
        bars, lows, highs, oh, ol = compute_overnight_session(target_date, archive)
        if not bars or oh is None or ol is None or (not lows and not highs):
            logger.info(
                "[OVERNIGHT_SWEEP] %s — no overnight data / no levels; disarming.",
                st.date_key,
            )
            return
        st.overnight_high = oh
        st.overnight_low  = ol
        st.levels = lows
        st.level_states = [LevelState(price=p) for p in lows]
        st.levels_high = highs
        st.level_states_high = [LevelState(price=p) for p in highs]
        st.armed = bool(lows or highs)
        logger.info(
            "[OVERNIGHT_SWEEP] %s armed: %d lows=[%s] %d highs=[%s] "
            "overnight_high=%.1f overnight_low=%.1f window=%s-%s UTC",
            st.date_key,
            len(lows), ", ".join(f"{p:.1f}" for p in lows),
            len(highs), ", ".join(f"{p:.1f}" for p in highs),
            oh, ol,
            WINDOW_START.strftime("%H:%M"), WINDOW_END.strftime("%H:%M"),
        )

    def identify_overnight_levels(
        self,
        target_date_utc: date,
        candle_archive_path: Optional[Path] = None,
    ) -> List[float]:
        """Return identified swing-low levels for `target_date_utc`, ascending."""
        _, lows, _, _, _ = compute_overnight_session(target_date_utc, candle_archive_path)
        return lows

    def identify_overnight_highs_for(
        self,
        target_date_utc: date,
        candle_archive_path: Optional[Path] = None,
    ) -> List[float]:
        """Return identified swing-high levels for `target_date_utc`, descending."""
        _, _, highs, _, _ = compute_overnight_session(target_date_utc, candle_archive_path)
        return highs

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
        """Called on each new closed 5m bar. `bars[-1]` is the just-closed
        bar. Runs LONG and SHORT detectors independently. One trade per
        direction per day; ``has_open_long``/``has_open_short`` block
        only their own side."""
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
            if not st.armed:
                return None

        bN = bars[-1]
        bar_close_ts = bN.timestamp + timedelta(minutes=5)
        if bar_close_ts.astimezone(timezone.utc).date() != target_date:
            return None

        pip = pip_size or PIP_SIZE

        # Try LONG first (preserves prior behaviour when both fire on
        # the same bar — historically the LONG side was always tried).
        if ENABLE_LONG and not has_open_long and not st.entered:
            dec = self._evaluate_long(st, bN, bar_close_ts, pip, date_key)
            if dec is not None:
                return dec
        if ENABLE_SHORT and not has_open_short and not st.entered_short:
            dec = self._evaluate_short(st, bN, bar_close_ts, pip, date_key)
            if dec is not None:
                return dec
        return None

    def _evaluate_long(
        self,
        st: DayState,
        bN: Bar,
        bar_close_ts: datetime,
        pip: float,
        date_key: str,
    ) -> Optional["StrategyDecision"]:
        with self._lock:
            # Phase 1: detect sweeps below any WAITING low on this bar.
            for ls in st.level_states:
                if ls.phase != PHASE_WAITING:
                    continue
                if bN.low <= ls.price - PIERCE_PIPS * pip:
                    ls.phase = PHASE_SWEPT
                    ls.sweep_extreme = bN.low
                    ls.sweep_time = bN.timestamp
                    logger.info(
                        "[OVERNIGHT_SWEEP] %s SWEPT_LOW level=%.1f bar=%s low=%.1f (-%.1fp)",
                        date_key, ls.price, bN.timestamp.strftime("%H:%M"),
                        bN.low, ls.price - bN.low,
                    )

            # Phase 2: evaluate confirmation for each SWEPT level.
            swept = [ls for ls in st.level_states if ls.phase == PHASE_SWEPT]
            swept.sort(key=lambda ls: (ls.sweep_time or bar_close_ts, ls.price))

            for ls in swept:
                if ls.sweep_time is not None and (bar_close_ts - ls.sweep_time) > timedelta(minutes=CONFIRM_TIMEOUT_MIN):
                    logger.info(
                        "[OVERNIGHT_SWEEP] %s LONG level=%.1f confirmation timeout — done.",
                        date_key, ls.price,
                    )
                    ls.phase = PHASE_DONE
                    continue

                cond_after = ls.sweep_time is not None and bar_close_ts > ls.sweep_time
                cond_inside = bN.close > ls.price
                cond_dir = bN.is_bullish
                cond_body = bN.body_ratio >= MIN_BODY_RATIO
                cond_range = bN.range >= MIN_BAR_RANGE_PIPS * pip
                if not (cond_after and cond_inside and cond_dir and cond_body and cond_range):
                    continue

                sl_price = ls.sweep_extreme - SL_BUFFER_PIPS * pip
                sl_pips = (bN.close - sl_price) / pip
                if sl_pips <= 0 or sl_pips > MAX_SL_PIPS:
                    continue

                entry_price = bN.close
                tp_price: Optional[float] = None
                for lvl in st.levels:  # ascending
                    if lvl > entry_price:
                        tp_price = lvl
                        break
                if tp_price is None:
                    tp_price = st.overnight_high
                if tp_price is None:
                    continue
                tp_pips = (tp_price - entry_price) / pip
                if tp_pips < MIN_TP_PIPS:
                    continue

                # Fixed size per .env TRADE_SIZE; risk varies by SL distance.
                try:
                    from strategy_logic import StrategyDecision
                except Exception as e:
                    logger.error("[OVERNIGHT_SWEEP] StrategyDecision import failed: %s", e)
                    return None

                notes = (
                    f"lows=[{', '.join(f'{p:.1f}' for p in st.levels)}] "
                    f"swept_low={ls.price:.1f}@{ls.sweep_time.strftime('%H:%M') if ls.sweep_time else '?'} "
                    f"sweep_extreme={ls.sweep_extreme:.1f} entry={entry_price:.1f} "
                    f"tp_target={tp_price:.1f} body_ratio={bN.body_ratio:.2f} range={bN.range:.1f}p"
                )
                decision = StrategyDecision(
                    symbol="GBPUSD",
                    regime="OVERNIGHT_LEVEL_SWEEP",
                    signal="BUY",
                    mode=MODE_NAME,
                    entry=entry_price,
                    sl=round(float(sl_pips), 2),
                    tp=round(float(tp_pips), 2),
                    use_trailing_stop=False,
                    reason=f"overnight_level_sweep_long: {notes}",
                    debug={
                        "side": "LONG",
                        "levels_low": list(st.levels),
                        "swept_level": ls.price,
                        "sweep_extreme": ls.sweep_extreme,
                        "sweep_time": ls.sweep_time.isoformat() if ls.sweep_time else None,
                        "tp_price_abs": tp_price,
                        "sl_price_abs": sl_price,
                        "overnight_high": st.overnight_high,
                        "bar_ts": bN.timestamp.isoformat(),
                    },
                    pip_size=pip,
                )

                # One LONG per day: lock LONG-side levels DONE.
                for other in st.level_states:
                    other.phase = PHASE_DONE
                st.entered = True
                logger.info(
                    "[OVERNIGHT_SWEEP] %s ENTRY BUY @ %.1f | SL=%.1fp TP=%.1fp | %s",
                    date_key, entry_price, sl_pips, tp_pips, notes,
                )
                return decision
            return None

    def _evaluate_short(
        self,
        st: DayState,
        bN: Bar,
        bar_close_ts: datetime,
        pip: float,
        date_key: str,
    ) -> Optional["StrategyDecision"]:
        with self._lock:
            # Phase 1: detect sweeps above any WAITING high on this bar.
            for ls in st.level_states_high:
                if ls.phase != PHASE_WAITING:
                    continue
                if bN.high >= ls.price + PIERCE_PIPS * pip:
                    ls.phase = PHASE_SWEPT
                    ls.sweep_extreme = bN.high
                    ls.sweep_time = bN.timestamp
                    logger.info(
                        "[OVERNIGHT_SWEEP] %s SWEPT_HIGH level=%.1f bar=%s high=%.1f (+%.1fp)",
                        date_key, ls.price, bN.timestamp.strftime("%H:%M"),
                        bN.high, bN.high - ls.price,
                    )

            # Phase 2: evaluate confirmation for each SWEPT level.
            swept = [ls for ls in st.level_states_high if ls.phase == PHASE_SWEPT]
            # Iterate by sweep_time ascending; tie-break on level price descending (deepest sweep wins).
            swept.sort(key=lambda ls: (ls.sweep_time or bar_close_ts, -ls.price))

            for ls in swept:
                if ls.sweep_time is not None and (bar_close_ts - ls.sweep_time) > timedelta(minutes=CONFIRM_TIMEOUT_MIN):
                    logger.info(
                        "[OVERNIGHT_SWEEP] %s SHORT level=%.1f confirmation timeout — done.",
                        date_key, ls.price,
                    )
                    ls.phase = PHASE_DONE
                    continue

                cond_after = ls.sweep_time is not None and bar_close_ts > ls.sweep_time
                cond_inside = bN.close < ls.price
                cond_dir = bN.is_bearish
                cond_body = bN.body_ratio >= MIN_BODY_RATIO
                cond_range = bN.range >= MIN_BAR_RANGE_PIPS * pip
                if not (cond_after and cond_inside and cond_dir and cond_body and cond_range):
                    continue

                sl_price = ls.sweep_extreme + SL_BUFFER_PIPS * pip
                sl_pips = (sl_price - bN.close) / pip
                if sl_pips <= 0 or sl_pips > MAX_SL_PIPS:
                    continue

                entry_price = bN.close
                tp_price: Optional[float] = None
                for lvl in st.levels_high:  # descending
                    if lvl < entry_price:
                        tp_price = lvl
                        break
                if tp_price is None:
                    tp_price = st.overnight_low
                if tp_price is None:
                    continue
                tp_pips = (entry_price - tp_price) / pip
                if tp_pips < MIN_TP_PIPS:
                    continue

                # Fixed size per .env TRADE_SIZE; risk varies by SL distance.
                try:
                    from strategy_logic import StrategyDecision
                except Exception as e:
                    logger.error("[OVERNIGHT_SWEEP] StrategyDecision import failed: %s", e)
                    return None

                notes = (
                    f"highs=[{', '.join(f'{p:.1f}' for p in st.levels_high)}] "
                    f"swept_high={ls.price:.1f}@{ls.sweep_time.strftime('%H:%M') if ls.sweep_time else '?'} "
                    f"sweep_extreme={ls.sweep_extreme:.1f} entry={entry_price:.1f} "
                    f"tp_target={tp_price:.1f} body_ratio={bN.body_ratio:.2f} range={bN.range:.1f}p"
                )
                decision = StrategyDecision(
                    symbol="GBPUSD",
                    regime="OVERNIGHT_LEVEL_SWEEP",
                    signal="SELL",
                    mode=MODE_NAME_SHORT,
                    entry=entry_price,
                    sl=round(float(sl_pips), 2),
                    tp=round(float(tp_pips), 2),
                    use_trailing_stop=False,
                    reason=f"overnight_level_sweep_short: {notes}",
                    debug={
                        "side": "SHORT",
                        "levels_high": list(st.levels_high),
                        "swept_level": ls.price,
                        "sweep_extreme": ls.sweep_extreme,
                        "sweep_time": ls.sweep_time.isoformat() if ls.sweep_time else None,
                        "tp_price_abs": tp_price,
                        "sl_price_abs": sl_price,
                        "overnight_low": st.overnight_low,
                        "bar_ts": bN.timestamp.isoformat(),
                    },
                    pip_size=pip,
                )

                # One SHORT per day: lock SHORT-side levels DONE.
                for other in st.level_states_high:
                    other.phase = PHASE_DONE
                st.entered_short = True
                logger.info(
                    "[OVERNIGHT_SWEEP] %s ENTRY SELL @ %.1f | SL=%.1fp TP=%.1fp | %s",
                    date_key, entry_price, sl_pips, tp_pips, notes,
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
        """Mark the relevant side DONE on close. One trade per direction
        per day; never re-arm. LONG and SHORT close states are independent."""
        mode_u = str(mode).upper() if mode else ""
        if mode_u and mode_u not in (MODE_NAME, MODE_NAME_SHORT):
            return
        now = ts or datetime.now(timezone.utc)
        date_key = self._date_key(self._utc(now))
        with self._lock:
            st = self._states.get(date_key)
            if st is None:
                return
            if mode_u in ("", MODE_NAME):
                for ls in st.level_states:
                    ls.phase = PHASE_DONE
                st.entered = True
            if mode_u in ("", MODE_NAME_SHORT):
                for ls in st.level_states_high:
                    ls.phase = PHASE_DONE
                st.entered_short = True


# Singleton
strategy = GbpUsdOvernightLevelSweepStrategy()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
