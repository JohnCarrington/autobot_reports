"""
gbpusd_bb_reversal_patterns.py — GBPUSD Bollinger-Band reversal patterns
on 5-minute candles. Two distinct entry patterns under one strategy
module:

  V — V-SHAPED REVERSAL (2 bars)
      Touch bar (N): high >= BBU (SHORT V) or low <= BBL (LONG V).
      Wicking the band counts; no minimum pierce, no open-inside check.
      BB width at touch >= V_BB_WIDTH_FLOOR_PIPS (default 8p).
      Reversal bar (N+1): closes opposite direction, body >= V_MIN_BODY_PIPS,
      body >= touch-bar body. Fire on N+1 close.

  ARC — CURVING REJECTION (4-8 bars)
      3..7 consecutive bars all touching/wicking past the band (each
      bar's high >= BBU for SHORT, low <= BBL for LONG).
      Highs/lows hug within ARC_HUG_PIPS across the arc.
      Body compression: avg body of last 2 arc bars < avg body of first 2.
      BB width during arc >= ARC_BB_WIDTH_FLOOR_PIPS (default 8p).
      Reversal bar (after the arc): body in opposite direction,
      body >= ARC_MIN_REVERSAL_BODY_PIPS. Fire on reversal-bar close.

Shared infrastructure (mirrors gbpusd_bb_bounce / BB_PIERCE_RUN):
  - SL: 12p hard
  - TP: trade_manager.select_tp_levels (briefing TP1/TP2/TP3) with
        BROKER_TP_PIPS (100p) sentinel as broker-side stop. The
        multi-tier state machine in trade_manager._monitor_briefing_tp
        drives early exits.
  - Time stop: 240m via REGIME_MAX_HOLD override (BB_PIERCE_RUN_MODES
        in trade_manager.py is extended to include this strategy's
        modes).
  - Window: 06:00-17:00 UTC, weekdays.
  - News blackout: 30-min window pre-fire for high-impact GBP/USD events.
  - Regime gate: TRENDING blocks (BB_PIERCE_RUN's mirror — these are
        also fade strategies).
  - Per-direction slots: 1 LONG + 1 SHORT max via has_open_long /
        has_open_short.
  - Pyramiding: not enabled.
  - Co-fire suppression: if gbpusd_bb_bounce (BB_PIERCE_RUN) has any
        same-direction armed setup at evaluate time, OR an active
        position opened within last CO_FIRE_WINDOW_BARS (default 3),
        suppress this strategy's fire. Reason logged as
        "bb_pierce_run_active".

Mode tags:
  GBPUSD_BB_REV_PAT_L (LONG)
  GBPUSD_BB_REV_PAT_S (SHORT)

Pattern sub-flags (env):
  GBPUSD_BB_REVERSAL_PATTERNS_ENABLED — master (default 0)
  GBPUSD_BB_REVERSAL_V_ENABLED        — Pattern V (default 1)
  GBPUSD_BB_REVERSAL_ARC_ENABLED      — Pattern ARC (default 1)
  GBPUSD_BB_REVERSAL_REGIME_FILTER_ENABLED — regime gate (default true)

Designed to catch reversals that BB_PIERCE_RUN's strict pierce+
rejection misses (no-pierce wicks, multi-bar curving stalls). The
co-fire suppression keeps the two strategies non-overlapping.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_bb_rev_pat")

LOG_TAG = "BB_REV_PAT"

MODE_NAME_LONG  = "GBPUSD_BB_REV_PAT_L"
MODE_NAME_SHORT = "GBPUSD_BB_REV_PAT_S"

PIP_SIZE = 1.0  # GBPUSD on IG TODAY epic: 1 raw point = 1 pip


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# ─── Configuration ────────────────────────────────────────────────────────
ENABLED = _env_bool("GBPUSD_BB_REVERSAL_PATTERNS_ENABLED", "0")
V_ENABLED   = _env_bool("GBPUSD_BB_REVERSAL_V_ENABLED",   "1")
ARC_ENABLED = _env_bool("GBPUSD_BB_REVERSAL_ARC_ENABLED", "1")

# Active session window (UTC, weekdays only). Mirrors BB_PIERCE_RUN.
WIN_START = dtime(_env_int("GBPUSD_BB_REVERSAL_WIN_START_H", 6), 0)
WIN_END   = dtime(_env_int("GBPUSD_BB_REVERSAL_WIN_END_H", 17), 0)

# Bollinger Bands.
BB_PERIOD = _env_int("GBPUSD_BB_REVERSAL_BB_PERIOD", 20)
BB_STD    = _env_float("GBPUSD_BB_REVERSAL_BB_STD", 2.0)

# Pattern V parameters.
V_BB_WIDTH_FLOOR_PIPS = _env_float("GBPUSD_BB_REVERSAL_V_BB_WIDTH_FLOOR_PIPS", 8.0)
V_MIN_BODY_PIPS       = _env_float("GBPUSD_BB_REVERSAL_V_MIN_BODY_PIPS", 5.0)

# Pattern ARC parameters.
ARC_MIN_BARS               = _env_int("GBPUSD_BB_REVERSAL_ARC_MIN_BARS", 3)
ARC_MAX_BARS               = _env_int("GBPUSD_BB_REVERSAL_ARC_MAX_BARS", 7)
ARC_HUG_PIPS               = _env_float("GBPUSD_BB_REVERSAL_ARC_HUG_PIPS", 3.0)
ARC_BB_WIDTH_FLOOR_PIPS    = _env_float("GBPUSD_BB_REVERSAL_ARC_BB_WIDTH_FLOOR_PIPS", 8.0)
ARC_MIN_REVERSAL_BODY_PIPS = _env_float("GBPUSD_BB_REVERSAL_ARC_MIN_REVERSAL_BODY_PIPS", 5.0)

# Risk geometry — mirrors BB_PIERCE_RUN.
SL_PIPS           = _env_float("GBPUSD_BB_REVERSAL_SL_PIPS", 12.0)
BROKER_TP_PIPS    = _env_float("GBPUSD_BB_REVERSAL_BROKER_TP_PIPS", 100.0)
TP1_FALLBACK_PIPS = _env_float("GBPUSD_BB_REVERSAL_TP1_FALLBACK_PIPS", 30.0)

# Regime filter (TRENDING blocks).
REGIME_FILTER_ENABLED = _env_bool("GBPUSD_BB_REVERSAL_REGIME_FILTER_ENABLED", "true")

# News blackout (mirrors BB_PIERCE_RUN).
NEWS_BLACKOUT_ENABLED = _env_bool("GBPUSD_BB_REVERSAL_NEWS_BLACKOUT_ENABLED", "1")
NEWS_PRE_MIN          = _env_int("GBPUSD_BB_REVERSAL_NEWS_PRE_MIN", 30)
_NEWS_AFFECTING_CCYS = ("GBP", "USD")

# Co-fire suppression vs BB_PIERCE_RUN.
CO_FIRE_WINDOW_BARS = _env_int("GBPUSD_BB_REVERSAL_CO_FIRE_WINDOW_BARS", 3)


# ─── Bar dataclass ────────────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. Times are tz-aware UTC."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


# ─── Indicators ───────────────────────────────────────────────────────────
def _bb_20_2(closes: Sequence[float],
             period: int = BB_PERIOD,
             std_mult: float = BB_STD,
             ) -> Tuple[float, float, float]:
    """Return (lower, mid, upper). Population stdev — matches every other
    BB call site in this codebase."""
    if len(closes) < period:
        raise ValueError(f"need {period}+ closes for BB")
    window = list(closes[-period:])
    mid = sum(window) / period
    var = sum((c - mid) ** 2 for c in window) / period
    std = math.sqrt(var)
    return mid - std_mult * std, mid, mid + std_mult * std


def _body_pips(bar: Bar, pip_size: float = PIP_SIZE) -> float:
    return abs(bar.close - bar.open) / pip_size


# ─── News blackout ────────────────────────────────────────────────────────
def _is_pre_news_blackout(now_utc: datetime) -> Tuple[bool, str]:
    """Return (True, reason) if `now_utc` falls in the NEWS_PRE_MIN-minute
    window before any high-impact GBP/USD event today.

    Mirrors gbpusd_bb_bounce._is_pre_news_blackout — soft on errors."""
    if not NEWS_BLACKOUT_ENABLED or NEWS_PRE_MIN <= 0:
        return False, ""
    try:
        import news_calendar
        events = news_calendar.get_todays_events(currencies=list(_NEWS_AFFECTING_CCYS))
    except Exception:
        return False, ""
    if not events:
        return False, ""
    pre_seconds = float(NEWS_PRE_MIN) * 60.0
    for ev in events:
        if str(ev.get("impact") or "").strip() != "High":
            continue
        ccy = str(ev.get("currency") or "").upper()
        if ccy not in _NEWS_AFFECTING_CCYS:
            continue
        try:
            h, mi = map(int, str(ev.get("time") or "").split(":"))
        except (ValueError, AttributeError):
            continue
        ev_dt = now_utc.replace(hour=h, minute=mi, second=0, microsecond=0)
        secs_until = (ev_dt - now_utc).total_seconds()
        if 0 < secs_until <= pre_seconds:
            return True, (
                f"news_blackout_pre: {ccy} {ev.get('event_name', '')}"
                f" @ {ev.get('time')}UTC (in {secs_until/60.0:.1f}m)"
            )
    return False, ""


# ─── Co-fire suppression vs BB_PIERCE_RUN ────────────────────────────────
def _bb_pierce_run_active(direction: str,
                          epic: str,
                          cur_ts: datetime,
                          ) -> Tuple[bool, str]:
    """Return (True, reason) if BB_PIERCE_RUN has a same-direction
    armed setup, or fired (opened a position) within the last
    CO_FIRE_WINDOW_BARS bars (5m each). Read from gbpusd_bb_bounce's
    in-memory armed-setups state and from trade_executor.EPIC_STATE.

    Soft on errors — never block a fire just because the lookup
    failed."""
    pierce_dir = "LONG" if direction == "BUY" else "SHORT"
    try:
        from gbpusd_bb_bounce import strategy as _bbb_strat
        armed_for_epic = (_bbb_strat._armed_setups.get(epic) or [])
        for s in armed_for_epic:
            if s.get("direction") == pierce_dir:
                return True, f"bb_pierce_run_active: armed_setup_{pierce_dir}"
    except Exception:
        pass

    # Recent open position check — bb_bounce mode positions opened in
    # the last CO_FIRE_WINDOW_BARS * 5 minutes count as active fire.
    try:
        from trade_executor import EPIC_STATE
        cutoff_seconds = float(CO_FIRE_WINDOW_BARS) * 300.0
        bbb_mode = "GBPUSD_BB_BOUNCE_L" if direction == "BUY" else "GBPUSD_BB_BOUNCE_S"
        for _pk, st in list(EPIC_STATE.items()):
            try:
                if str(st.get("mode") or "").upper() != bbb_mode:
                    continue
                if not (st.get("active") or st.get("pending_open")):
                    continue
                opened_at = st.get("entry_ts") or st.get("opened_at")
                if opened_at is None:
                    return True, f"bb_pierce_run_active: open_{bbb_mode}"
                try:
                    if isinstance(opened_at, (int, float)):
                        opened_dt = datetime.fromtimestamp(float(opened_at), tz=timezone.utc)
                    else:
                        opened_dt = opened_at
                    if opened_dt.tzinfo is None:
                        opened_dt = opened_dt.replace(tzinfo=timezone.utc)
                    age = (cur_ts - opened_dt).total_seconds()
                    if 0 <= age <= cutoff_seconds:
                        return True, f"bb_pierce_run_active: recent_{bbb_mode}_age={age:.0f}s"
                except Exception:
                    return True, f"bb_pierce_run_active: open_{bbb_mode}_unparseable_ts"
            except Exception:
                continue
    except Exception:
        pass
    return False, ""


# ─── Pattern V detector ───────────────────────────────────────────────────
@dataclass
class _VEvidence:
    direction: str          # "LONG" | "SHORT"
    touch_bar: Bar
    reversal_bar: Bar
    touch_body_pips: float
    reversal_body_pips: float
    bb_width_pips: float


def _detect_v(prev: Bar,
              cur: Bar,
              bb_lower_at_prev: float,
              bb_upper_at_prev: float,
              bb_width_at_prev_pips: float,
              pip_size: float = PIP_SIZE,
              ) -> Tuple[Optional[_VEvidence], str]:
    """Two-bar V-shaped reversal.
      Touch bar (prev): wicks the band — high >= BBU (SHORT V) or
                        low <= BBL (LONG V). No pierce minimum.
      BB width at touch >= V_BB_WIDTH_FLOOR_PIPS.
      Reversal bar (cur): body opposite direction, >= V_MIN_BODY_PIPS,
                          body >= touch-bar body.
    Returns (_VEvidence, "") on match, (None, reject_reason) otherwise."""
    if bb_width_at_prev_pips < V_BB_WIDTH_FLOOR_PIPS:
        return None, f"bb_width_at_touch={bb_width_at_prev_pips:.1f}p<{V_BB_WIDTH_FLOOR_PIPS:.0f}p"

    upper_touch = prev.high >= bb_upper_at_prev
    lower_touch = prev.low  <= bb_lower_at_prev
    if upper_touch and lower_touch:
        return None, "both_bands_touched"
    if not (upper_touch or lower_touch):
        return None, ""

    direction = "SHORT" if upper_touch else "LONG"
    rev_body = _body_pips(cur, pip_size)
    touch_body = _body_pips(prev, pip_size)

    # Reversal bar must close in the opposite direction with min body
    # AND body >= touch-bar body.
    if direction == "SHORT":
        if not (cur.close < cur.open):
            return None, "rev_bar_not_bearish"
    else:
        if not (cur.close > cur.open):
            return None, "rev_bar_not_bullish"

    if rev_body < V_MIN_BODY_PIPS:
        return None, f"rev_body={rev_body:.1f}p<{V_MIN_BODY_PIPS:.0f}p"
    if rev_body < touch_body:
        return None, f"rev_body={rev_body:.1f}p<touch_body={touch_body:.1f}p"

    return _VEvidence(
        direction=direction,
        touch_bar=prev,
        reversal_bar=cur,
        touch_body_pips=touch_body,
        reversal_body_pips=rev_body,
        bb_width_pips=bb_width_at_prev_pips,
    ), ""


# ─── Pattern ARC detector ─────────────────────────────────────────────────
@dataclass
class _ArcEvidence:
    direction: str          # "LONG" | "SHORT"
    arc_len: int
    arc_bars: List[Bar]
    reversal_bar: Bar
    hug_spread_pips: float
    early_avg_body_pips: float
    late_avg_body_pips: float
    bb_width_pips: float


def _detect_arc(bars: Sequence[Bar],
                bb_lower_n: float,
                bb_upper_n: float,
                bb_width_n_pips: float,
                pip_size: float = PIP_SIZE,
                ) -> Tuple[Optional[_ArcEvidence], str]:
    """Detect a 3-7 bar arc + reversal candle.

    bars[-1] is the reversal candidate. bars[-1-k:-1] for k in
    [ARC_MIN_BARS..ARC_MAX_BARS] is the candidate arc. Returns the
    LONGEST matching arc (most evidence). The arc is evaluated against
    the CURRENT BB (bb_lower_n / bb_upper_n) — bands move slowly enough
    on 5m that this is a reasonable approximation.

    Reversal bar (bars[-1]):
      LONG arc → reversal must be bullish (close > open), body >= ARC_MIN_REVERSAL_BODY_PIPS.
      SHORT arc → reversal must be bearish, same body floor.
    """
    if len(bars) < ARC_MIN_BARS + 1:
        return None, "insufficient_bars"
    if bb_width_n_pips < ARC_BB_WIDTH_FLOOR_PIPS:
        return None, f"bb_width={bb_width_n_pips:.1f}p<{ARC_BB_WIDTH_FLOOR_PIPS:.0f}p"

    rev = bars[-1]
    rev_body = _body_pips(rev, pip_size)
    rev_bullish = rev.close > rev.open
    rev_bearish = rev.close < rev.open
    if rev_body < ARC_MIN_REVERSAL_BODY_PIPS:
        return None, f"rev_body={rev_body:.1f}p<{ARC_MIN_REVERSAL_BODY_PIPS:.0f}p"
    if not (rev_bullish or rev_bearish):
        return None, "rev_doji"

    best: Optional[_ArcEvidence] = None
    best_reason = "no_match"

    # Try arc lengths from MAX → MIN, prefer the longest match.
    max_k = min(ARC_MAX_BARS, len(bars) - 1)
    for k in range(max_k, ARC_MIN_BARS - 1, -1):
        arc_slice = list(bars[-1 - k : -1])  # k bars, in chronological order
        if len(arc_slice) != k:
            continue

        # All arc bars must touch/wick the band (one direction only).
        all_upper = all(b.high >= bb_upper_n for b in arc_slice)
        all_lower = all(b.low  <= bb_lower_n for b in arc_slice)
        if not (all_upper or all_lower):
            best_reason = f"k={k}_no_consistent_touch"
            continue
        if all_upper and all_lower:
            best_reason = f"k={k}_both_bands"
            continue

        arc_dir = "SHORT" if all_upper else "LONG"

        # Reversal must oppose the arc direction.
        if arc_dir == "SHORT" and not rev_bearish:
            best_reason = f"k={k}_rev_not_bearish"
            continue
        if arc_dir == "LONG" and not rev_bullish:
            best_reason = f"k={k}_rev_not_bullish"
            continue

        # Hug check — extremes (highs for SHORT, lows for LONG) within
        # ARC_HUG_PIPS of each other across the arc.
        if arc_dir == "SHORT":
            extremes = [b.high for b in arc_slice]
        else:
            extremes = [b.low for b in arc_slice]
        spread_pips = (max(extremes) - min(extremes)) / pip_size
        if spread_pips > ARC_HUG_PIPS:
            best_reason = f"k={k}_hug_spread={spread_pips:.1f}p>{ARC_HUG_PIPS:.0f}p"
            continue

        # Body compression — avg body of last 2 < avg body of first 2.
        early_avg = (_body_pips(arc_slice[0], pip_size) + _body_pips(arc_slice[1], pip_size)) / 2.0
        late_avg  = (_body_pips(arc_slice[-2], pip_size) + _body_pips(arc_slice[-1], pip_size)) / 2.0
        if not (late_avg < early_avg):
            best_reason = f"k={k}_no_compression early={early_avg:.1f}p late={late_avg:.1f}p"
            continue

        return _ArcEvidence(
            direction=arc_dir,
            arc_len=k,
            arc_bars=arc_slice,
            reversal_bar=rev,
            hug_spread_pips=spread_pips,
            early_avg_body_pips=early_avg,
            late_avg_body_pips=late_avg,
            bb_width_pips=bb_width_n_pips,
        ), ""

    return best, best_reason


# ─── Strategy class ───────────────────────────────────────────────────────
class GbpUsdBBReversalPatternsStrategy:
    """Singleton. Stateless across days — slot enforcement comes from
    the autobot via has_open_long/has_open_short."""

    _instance: Optional["GbpUsdBBReversalPatternsStrategy"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_eval_bar: Dict[str, datetime] = {}

    @classmethod
    def instance(cls) -> "GbpUsdBBReversalPatternsStrategy":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _in_window(self, ts_utc: datetime) -> bool:
        ts = ts_utc.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return WIN_START <= t < WIN_END

    def evaluate(self,
                 symbol: str,
                 epic: str,
                 ts: datetime,
                 bars: Sequence[Bar],
                 closes_ind: Sequence[float],
                 has_open_long: bool = False,
                 has_open_short: bool = False,
                 ) -> Optional["StrategyDecision"]:
        """Called on each new 5m close for GBPUSD."""
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if not self._in_window(ts):
            return None

        # Need at least 2 bars (V) and BB_PERIOD+1 closes (BB at N AND
        # at N-1). For ARC we need up to ARC_MAX_BARS+1 bars.
        min_bars = max(2, ARC_MIN_BARS + 1)
        if not bars or len(bars) < min_bars:
            return None
        if len(closes_ind) < BB_PERIOD + 1:
            return None

        last_seen = self._last_eval_bar.get(epic)
        if last_seen is not None and bars[-1].timestamp <= last_seen:
            return None
        self._last_eval_bar[epic] = bars[-1].timestamp

        try:
            bb_lower_n,    bb_mid_n,    bb_upper_n    = _bb_20_2(closes_ind)
            bb_lower_prev, _bb_mid_prev, bb_upper_prev = _bb_20_2(closes_ind[:-1])
        except ValueError:
            return None

        bb_width_n_pips    = (bb_upper_n    - bb_lower_n)    / PIP_SIZE
        bb_width_prev_pips = (bb_upper_prev - bb_lower_prev) / PIP_SIZE

        prev = bars[-2]
        cur  = bars[-1]

        # ── Pattern V ───────────────────────────────────────────────────
        v_evidence: Optional[_VEvidence] = None
        v_reject: str = ""
        if V_ENABLED:
            v_evidence, v_reject = _detect_v(
                prev, cur,
                bb_lower_prev, bb_upper_prev, bb_width_prev_pips,
            )
            if v_evidence is None and v_reject:
                logger.debug("[%s] %s V skip: %s", LOG_TAG, symbol, v_reject)

        # ── Pattern ARC ─────────────────────────────────────────────────
        arc_evidence: Optional[_ArcEvidence] = None
        arc_reject: str = ""
        if ARC_ENABLED:
            arc_evidence, arc_reject = _detect_arc(
                bars, bb_lower_n, bb_upper_n, bb_width_n_pips,
            )
            if arc_evidence is None and arc_reject:
                logger.debug("[%s] %s ARC skip: %s", LOG_TAG, symbol, arc_reject)

        # Pattern selection — prefer V over ARC when both fire on the
        # same bar (V is the simpler 2-bar pattern; if both fire, the
        # market just produced a clean V at the end of an arc, which is
        # already captured by V).
        pattern: Optional[str] = None
        direction: Optional[str] = None
        evidence: Any = None
        if v_evidence is not None:
            pattern = "V"
            direction = "BUY" if v_evidence.direction == "LONG" else "SELL"
            evidence = v_evidence
        elif arc_evidence is not None:
            pattern = "ARC"
            direction = "BUY" if arc_evidence.direction == "LONG" else "SELL"
            evidence = arc_evidence

        if pattern is None:
            return None

        # Pre-news blackout — suppress (stateless: the pattern needs to
        # re-form on a later bar anyway, no state to retain).
        is_blackout, blackout_reason = _is_pre_news_blackout(ts)
        if is_blackout:
            logger.info(
                "[%s] %s %s %s fire suppressed: %s",
                LOG_TAG, symbol, pattern, direction, blackout_reason,
            )
            return None

        # Position-slot enforcement (1 LONG + 1 SHORT max).
        if direction == "BUY" and has_open_long:
            logger.debug(
                "[%s] %s %s LONG fire suppressed: position slot taken",
                LOG_TAG, symbol, pattern,
            )
            return None
        if direction == "SELL" and has_open_short:
            logger.debug(
                "[%s] %s %s SHORT fire suppressed: position slot taken",
                LOG_TAG, symbol, pattern,
            )
            return None

        # Co-fire suppression vs BB_PIERCE_RUN.
        cofire, cofire_reason = _bb_pierce_run_active(direction, epic, ts)
        if cofire:
            logger.info(
                "[%s] %s %s %s fire suppressed: %s",
                LOG_TAG, symbol, pattern, direction, cofire_reason,
            )
            return None

        # Regime gate — TRENDING blocks (mirror BB_PIERCE_RUN; these
        # are also fade strategies).
        regime_result = None
        try:
            from gbpusd_regime_detector import classify_regime
            regime_result = classify_regime(list(bars), symbol="GBPUSD", log=True)
        except Exception as _re_exc:
            logger.warning(
                "[%s] %s regime classify failed: %s (continuing without filter)",
                LOG_TAG, symbol, _re_exc,
            )

        if regime_result is not None:
            logger.info(
                "[%s] %s %s %s fire candidate regime=%s conf=%s signals=%s",
                LOG_TAG, symbol, pattern, direction,
                regime_result.regime, regime_result.confidence,
                regime_result.signal_breakdown,
            )
            if REGIME_FILTER_ENABLED and regime_result.regime == "TRENDING":
                logger.info(
                    "[%s] %s %s %s fire suppressed: regime_filter_trending "
                    "(conf=%s)",
                    LOG_TAG, symbol, pattern, direction,
                    regime_result.confidence,
                )
                return None

        # Build the multi-tier briefing-TP plan (same as BB_PIERCE_RUN).
        entry = float(cur.close)
        sl_pips = float(SL_PIPS)

        briefing_levels: list = []
        try:
            from morning_briefing import get_briefing
            _brief = get_briefing("GBPUSD") or {}
            for _src in ("key_levels", "major_levels"):
                _d = _brief.get(_src) or {}
                _maj = (_src == "major_levels")
                for _v in (_d.get("resistance") or []):
                    if _v is not None:
                        briefing_levels.append({
                            "price": float(_v), "level_type": "resistance",
                            "source": _src, "major": _maj,
                        })
                for _v in (_d.get("support") or []):
                    if _v is not None:
                        briefing_levels.append({
                            "price": float(_v), "level_type": "support",
                            "source": _src, "major": _maj,
                        })
            _lp = _brief.get("liquidity_pools") or {}
            for _v in (_lp.get("buy_side") or []):
                if _v is not None:
                    briefing_levels.append({
                        "price": float(_v), "level_type": "resistance",
                        "source": "liquidity_pools", "major": False,
                    })
            for _v in (_lp.get("sell_side") or []):
                if _v is not None:
                    briefing_levels.append({
                        "price": float(_v), "level_type": "support",
                        "source": "liquidity_pools", "major": False,
                    })
        except Exception as _brief_exc:
            logger.warning(
                "[%s] briefing pull failed (continuing with empty pool): %s",
                LOG_TAG, _brief_exc,
            )
            briefing_levels = []

        try:
            from trade_manager import select_tp_levels
            tp_plan_dict = select_tp_levels(
                entry, direction, briefing_levels, "GBPUSD",
            )
        except Exception as _tp_exc:
            logger.error(
                "[%s] select_tp_levels failed: %s — emitting TP1=%dp fallback",
                LOG_TAG, _tp_exc, int(TP1_FALLBACK_PIPS),
            )
            tp_plan_dict = None

        if tp_plan_dict is not None:
            tp1_pips_internal = float(tp_plan_dict["tp1_pips"])
            tp_plan_for_debug = [
                {"pips": tp_plan_dict["tp1_pips"], "price": tp_plan_dict["tp1"], "source": "briefing_tp1"},
                {"pips": tp_plan_dict["tp2_pips"], "price": tp_plan_dict["tp2"], "source": "briefing_tp2"},
                {"pips": tp_plan_dict["tp3_pips"], "price": tp_plan_dict["tp3"], "source": "briefing_tp3"},
            ]
            tp_fallback_used = bool(tp_plan_dict.get("fallback"))
        else:
            tp1_pips_internal = float(TP1_FALLBACK_PIPS)
            tp_plan_for_debug = None
            tp_fallback_used = True

        tp_pips = float(BROKER_TP_PIPS)
        mode = MODE_NAME_LONG if direction == "BUY" else MODE_NAME_SHORT

        # Reason string + debug dict — pattern-specific.
        if pattern == "V":
            v_ev: _VEvidence = evidence
            reason = (
                f"bb_rev_v_{direction.lower()}: "
                f"touch_bar high={v_ev.touch_bar.high:.2f} low={v_ev.touch_bar.low:.2f} "
                f"body={v_ev.touch_body_pips:.1f}p | "
                f"rev_bar open={v_ev.reversal_bar.open:.2f} close={v_ev.reversal_bar.close:.2f} "
                f"body={v_ev.reversal_body_pips:.1f}p | "
                f"BBl_prev={bb_lower_prev:.2f} BBu_prev={bb_upper_prev:.2f} "
                f"width_at_touch={v_ev.bb_width_pips:.1f}p | "
                f"SL={sl_pips:.0f}p broker_TP={tp_pips:.0f}p TP1_internal={tp1_pips_internal:.0f}p"
                + (" [briefing_fallback]" if tp_fallback_used else " [briefing_levels]")
            )
            debug_extra: Dict[str, Any] = {
                "pattern": "V",
                "touch_bar_high": v_ev.touch_bar.high,
                "touch_bar_low": v_ev.touch_bar.low,
                "touch_bar_open": v_ev.touch_bar.open,
                "touch_bar_close": v_ev.touch_bar.close,
                "touch_body_pips": round(v_ev.touch_body_pips, 2),
                "reversal_bar_open": v_ev.reversal_bar.open,
                "reversal_bar_close": v_ev.reversal_bar.close,
                "reversal_body_pips": round(v_ev.reversal_body_pips, 2),
                "bb_width_at_touch_pips": round(v_ev.bb_width_pips, 2),
            }
        else:
            arc_ev: _ArcEvidence = evidence
            reason = (
                f"bb_rev_arc_{direction.lower()} ({arc_ev.arc_len}b arc): "
                f"hug_spread={arc_ev.hug_spread_pips:.1f}p, "
                f"early_avg_body={arc_ev.early_avg_body_pips:.1f}p, "
                f"late_avg_body={arc_ev.late_avg_body_pips:.1f}p | "
                f"rev_bar open={arc_ev.reversal_bar.open:.2f} close={arc_ev.reversal_bar.close:.2f} "
                f"body={_body_pips(arc_ev.reversal_bar):.1f}p | "
                f"BBl_n={bb_lower_n:.2f} BBu_n={bb_upper_n:.2f} width={arc_ev.bb_width_pips:.1f}p | "
                f"SL={sl_pips:.0f}p broker_TP={tp_pips:.0f}p TP1_internal={tp1_pips_internal:.0f}p"
                + (" [briefing_fallback]" if tp_fallback_used else " [briefing_levels]")
            )
            debug_extra = {
                "pattern": "ARC",
                "arc_len": arc_ev.arc_len,
                "arc_first_ts": arc_ev.arc_bars[0].timestamp.isoformat(),
                "arc_last_ts":  arc_ev.arc_bars[-1].timestamp.isoformat(),
                "hug_spread_pips": round(arc_ev.hug_spread_pips, 2),
                "early_avg_body_pips": round(arc_ev.early_avg_body_pips, 2),
                "late_avg_body_pips": round(arc_ev.late_avg_body_pips, 2),
                "reversal_bar_open": arc_ev.reversal_bar.open,
                "reversal_bar_close": arc_ev.reversal_bar.close,
                "reversal_body_pips": round(_body_pips(arc_ev.reversal_bar), 2),
            }

        try:
            from strategy_logic import StrategyDecision
        except Exception as exc:
            logger.error("[%s] StrategyDecision import failed: %s", LOG_TAG, exc)
            return None

        # ── Forensic fire snapshot — diagnostic only, NOT a gate ──────────
        # Captures multi-axis context at fire-confirmed point (all gates
        # passed: window, BB-width, V/ARC pattern detection, slot,
        # blackout, regime, co-fire suppression). Writes to
        # forensic_fires.jsonl for the May 19 review. Soft-fail: any
        # error logged WARNING; the fire path proceeds normally.
        #
        # Phase 2d minimal wiring: 5m bars only. Phase 2f will plumb HTF,
        # briefing levels, session, and news state from the autobot main
        # loop. `strategy=mode` writes the directional variant
        # (GBPUSD_BB_REV_PAT_L / _S) so the backfill join key matches
        # signal_log's existing convention with no normalization layer.
        # Pattern type (V vs ARC) is already preserved in debug_dict;
        # the forensic snapshot is direction-keyed only.
        try:
            import pandas as _ff_pd
            from indicators import forensic_fire_snapshot as _ff_snapshot_fn
            from forensic_logger import write_forensic_fire as _ff_write
            from forensic_context import (
                load_htf_series as _ff_load_htf,
                briefing_levels_for_sym as _ff_briefing_levels,
                session_state_now as _ff_session_state,
                news_state_now as _ff_news_state,
            )

            _ff_closes = _ff_pd.Series([b.close for b in bars])
            _ff_highs = _ff_pd.Series([b.high for b in bars])
            _ff_lows = _ff_pd.Series([b.low for b in bars])
            (_h1c, _h1h, _h1l, _h4c, _h4h, _h4l) = _ff_load_htf("GBPUSD")
            _ff_snap = _ff_snapshot_fn(
                closes_5m=_ff_closes, highs_5m=_ff_highs, lows_5m=_ff_lows,
                closes_h1=_h1c, highs_h1=_h1h, lows_h1=_h1l,
                closes_h4=_h4c, highs_h4=_h4h, lows_h4=_h4l,
                briefing_levels=_ff_briefing_levels("GBPUSD"),
                session_state=_ff_session_state(),
                news_state=_ff_news_state(["GBP", "USD"]),
                pip_size=PIP_SIZE,
            )
            _ff_write(
                strategy=mode,
                direction=("LONG" if direction == "BUY" else "SHORT"),
                entry_price=float(entry),
                fire_bar_ts=cur.timestamp.isoformat(),
                snapshot_dict=_ff_snap,
                pair="GBPUSD",
            )
        except Exception as _ff_exc:  # noqa: BLE001 — never block fire
            logger.warning(
                "[%s] forensic capture failed: %s", LOG_TAG, _ff_exc,
            )

        debug_dict: Dict[str, object] = {
            "bb_lower": round(bb_lower_n, 4),
            "bb_mid": round(bb_mid_n, 4),
            "bb_upper": round(bb_upper_n, 4),
            "bb_width_pips": round(bb_width_n_pips, 2),
            "bb_lower_prev": round(bb_lower_prev, 4),
            "bb_upper_prev": round(bb_upper_prev, 4),
            "bb_width_prev_pips": round(bb_width_prev_pips, 2),
            "briefing_levels": briefing_levels,
            "briefing_fallback_used": tp_fallback_used,
            **debug_extra,
        }
        if tp_plan_for_debug is not None:
            debug_dict["tp_plan"] = tp_plan_for_debug

        # Pin regime classifier state at decision-construction time so
        # signal_log carries it with zero log-open staleness.
        try:
            from strategy_logic import get_latest_regime_state as _gls
            _rs = _gls("GBPUSD")
            if isinstance(_rs, dict):
                debug_dict["regime_state"] = _rs
        except Exception:
            pass

        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="BB_REV_PAT",
            signal=direction,
            mode=mode,
            entry=entry,
            sl=round(sl_pips, 2),
            tp=round(tp_pips, 2),
            use_trailing_stop=False,
            reason=reason,
            debug=debug_dict,
            pip_size=PIP_SIZE,
        )

        logger.info(
            "[%s] %s %s ENTRY @ %.2f | SL=%.0fp TP=%.0fp%s | %s",
            LOG_TAG, pattern, direction, entry, sl_pips, tp_pips,
            " (briefing_fallback)" if tp_fallback_used else "",
            reason,
        )
        return decision


# Module-level singleton + dispatch helpers.
strategy = GbpUsdBBReversalPatternsStrategy.instance()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
