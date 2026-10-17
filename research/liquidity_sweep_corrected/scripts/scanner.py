"""Independent structural-level approach scanner for the corrected liquidity-
sweep research.  Deliverable B.

For each M5 bar on each authorised FX day, maintains per-level approach
state and emits one record per approach episode when the episode closes.
Walks forward only; honours Stage 0 defaults and amendment A2 approvals.

The output ledger covers every eligible approach — successful sweeps,
failed sweeps, touches without penetration, rejections without follow-
through, breakout continuations — unfiltered by HTF direction.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, "/opt/tradingbot")
sys.path.insert(0, str(Path(__file__).parent.parent))

from level_ladder import _is_rejection_at_rung  # noqa: E402

from scripts.data_io import (
    D1Bar, M5Bar, load_d1_history, load_m5_fx_day,
)
from scripts.levels import (
    APPROACH_BAND_PIPS, PIPS_PER_POINT, Level,
    enumerate_levels_at,
)


# Constants from Stage 0 operator-approved defaults
DEPARTURE_PIPS_DB = 12.0   # AMB-3 primary D-B
DEPARTURE_PIPS_DA = 0.0    # AMB-3 sensitivity D-A: any exit (any distance > band)
# D-C uses confirmed opposite swing — tracked separately, not with a distance threshold
CONFIRMATION_WINDOW_BARS = 10   # window after a rejection to look for confirmation


# ------------------------------------------------------------------------
# Approach-episode state
# ------------------------------------------------------------------------
@dataclass
class ApproachEpisode:
    """One contiguous approach to one level, from one side.

    An episode spans the time price stays within DEPARTURE_PIPS_DB (12 p) of the
    level.  The 8-p approach band is tracked as a sub-counter (`in_band_bars`).
    """
    level_id: str
    level_price: float
    level_family: str
    level_side: str
    level_confluence: Tuple[str, ...]
    approach_side: str
    rejection_direction: str
    test_number_db: int = 0
    test_number_da: int = 0
    test_number_dc: int = 0
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    bars_in_episode: int = 0
    in_band_bars: int = 0                   # subset of bars within 8 p
    min_abs_distance: float = float("inf")
    max_penetration: float = 0.0
    close_beyond_count: int = 0
    max_consec_closes_beyond: int = 0
    _curr_run_closes_beyond: int = 0
    first_rejection_ts: Optional[datetime] = None
    rejection_bar: Optional[M5Bar] = None
    first_confirm_wick_ts: Optional[datetime] = None
    first_confirm_wick_price: Optional[float] = None
    first_confirm_close_ts: Optional[datetime] = None
    first_confirm_close_price: Optional[float] = None

    def as_record(self) -> Dict:
        return {
            "level_id": self.level_id,
            "level_price": self.level_price,
            "level_family": self.level_family,
            "level_side": self.level_side,
            "level_confluence": ",".join(self.level_confluence),
            "approach_side": self.approach_side,
            "rejection_direction": self.rejection_direction,
            "test_number_db": self.test_number_db,
            "test_number_da": self.test_number_da,
            "test_number_dc": self.test_number_dc,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "bars_in_episode": self.bars_in_episode,
            "in_band_bars": self.in_band_bars,
            "min_abs_distance_pips": self.min_abs_distance,
            "max_penetration_pips": self.max_penetration,
            "close_beyond_count": self.close_beyond_count,
            "max_consec_closes_beyond": self.max_consec_closes_beyond,
            "first_rejection_ts": self.first_rejection_ts,
            "first_confirm_wick_ts": self.first_confirm_wick_ts,
            "first_confirm_wick_price": self.first_confirm_wick_price,
            "first_confirm_close_ts": self.first_confirm_close_ts,
            "first_confirm_close_price": self.first_confirm_close_price,
        }


@dataclass
class LevelTracker:
    """Per-level, per-side approach-episode tracker.  Also stores D-A/D-C counters."""
    level: Level
    approach_side: str          # "from_above" | "from_below"
    rejection_direction: str    # "BUY" | "SELL"
    test_count_db: int = 0      # number of D-B approaches recorded
    test_count_da: int = 0
    test_count_dc: int = 0
    db_departed: bool = True    # True ⇒ next band entry starts a new D-B test
    da_departed: bool = True    # True ⇒ next band entry starts a new D-A test
    dc_departed: bool = True    # True ⇒ next band entry starts a new D-C test
    active_episode: Optional[ApproachEpisode] = None
    rejection_search_tail_bars: int = 0    # if >0, scan forthcoming bars for confirmation

    def level_id(self) -> str:
        return f"{self.level.family}:{round(self.level.price, 1)}:{self.approach_side}"


# ------------------------------------------------------------------------
# Scanner
# ------------------------------------------------------------------------
def _signed_distance(level_price: float, bar_close: float, approach_side: str) -> float:
    """Return signed distance to level in pips.
    Positive = price hasn't reached level yet.
    Negative = price has crossed to the other side (penetrated).
    `approach_side` is "from_below" (level is a resistance for this episode)
    or "from_above" (level is support).
    """
    if approach_side == "from_below":
        return (level_price - bar_close) / PIPS_PER_POINT
    else:  # from_above
        return (bar_close - level_price) / PIPS_PER_POINT


def _signed_depth(level_price: float, bar_high: float, bar_low: float,
                  approach_side: str) -> float:
    """Return the furthest penetration during the bar in pips.
    Positive = did not reach; 0 = touched; negative = penetrated beyond.
    """
    if approach_side == "from_below":
        return (level_price - bar_high) / PIPS_PER_POINT
    else:
        return (bar_low - level_price) / PIPS_PER_POINT


def _bar_distance_to_level(level_price: float, bar_close: float) -> float:
    """Absolute pip distance to level from close."""
    return abs(bar_close - level_price) / PIPS_PER_POINT


def _end_episode(ep: ApproachEpisode, end_ts: datetime) -> ApproachEpisode:
    ep.end_ts = end_ts
    return ep


def scan_fx_day(
    fx_date: date,
    candle_src: str,
    history_days: int = 10,
    verbose: bool = False,
) -> List[Dict]:
    """Scan one FX day; emit approach-episode records.

    `history_days` controls the M5 lookback used for M5 swing detection.  Prior
    D1 bars are loaded independently via load_d1_history.
    """
    # Load prior D1 for pivots
    hist = load_d1_history(up_to=fx_date, lookback_days=60)
    if not hist:
        return []
    prior_d1 = hist[-1]

    # Load M5 history + today
    all_bars: List[M5Bar] = []
    for d_before in range(history_days, 0, -1):
        d = fx_date - timedelta(days=d_before)
        src_d = "candles" if d >= date(2026, 1, 1) else "candles_ext_v2"
        all_bars.extend(load_m5_fx_day(d, src_d))
    today_bars = load_m5_fx_day(fx_date, candle_src)
    all_bars.extend(today_bars)
    if not today_bars:
        return []

    # Precompute arrays for swing detection
    highs = np.array([b.high for b in all_bars])
    lows = np.array([b.low for b in all_bars])

    # Index of first "today" bar in `all_bars`
    today_start_idx = next(
        i for i, b in enumerate(all_bars) if b.ts >= today_bars[0].ts
    )

    # Per-level trackers, keyed by level_id (family:price:approach_side)
    trackers: Dict[str, LevelTracker] = {}
    emitted: List[Dict] = []

    # Scan today's bars in order
    for i_today, bar in enumerate(today_bars):
        i_all = today_start_idx + i_today
        current_price = bar.close

        # Enumerate levels valid at this bar (asof the previous closed bar for
        # swing confirmation; use i_all for everything else)
        levels = enumerate_levels_at(
            current_price=current_price,
            prior_d1_hlc=(prior_d1.high, prior_d1.low, prior_d1.close),
            m5_highs=highs,
            m5_lows=lows,
            m5_asof_idx=i_all,
        )

        # Register trackers for new levels (both sides for pivot/round; single
        # side for resistance / support).
        for L in levels:
            for approach_side in _applicable_sides(L):
                rej_dir = "BUY" if approach_side == "from_above" else "SELL"
                tid = f"{L.family}:{round(L.price, 1)}:{approach_side}"
                if tid not in trackers:
                    trackers[tid] = LevelTracker(
                        level=L,
                        approach_side=approach_side,
                        rejection_direction=rej_dir,
                    )

        # Process every active tracker — update state based on this bar
        for tid, tr in list(trackers.items()):
            _process_bar(tr, bar, i_today, today_bars, emitted)

    # Close any still-open episodes at end of day
    for tr in trackers.values():
        if tr.active_episode:
            _end_episode(tr.active_episode, today_bars[-1].ts)
            emitted.append(tr.active_episode.as_record())
            tr.active_episode = None

    # Tag day on every record
    for rec in emitted:
        rec["fx_date"] = fx_date
        rec["candle_src"] = candle_src

    return emitted


def _applicable_sides(L: Level) -> List[str]:
    if L.side == "resistance":
        return ["from_below"]
    if L.side == "support":
        return ["from_above"]
    # pivot (D_PIVOT_P and ROUND_*) can be approached from either side
    return ["from_above", "from_below"]


def _process_bar(
    tr: LevelTracker,
    bar: M5Bar,
    i_today: int,
    today_bars: List[M5Bar],
    emitted: List[Dict],
) -> None:
    """Advance the tracker state by one bar; emit episode records as they close."""
    level_price = tr.level.price
    approach_side = tr.approach_side

    # Distances
    signed_close_dist = _signed_distance(level_price, bar.close, approach_side)
    abs_dist = abs(signed_close_dist)
    signed_bar_depth = _signed_depth(level_price, bar.high, bar.low, approach_side)
    in_band = abs_dist <= APPROACH_BAND_PIPS
    in_tracking = abs_dist <= DEPARTURE_PIPS_DB   # within D-B 12-p window

    # ----- Episode-start logic -----
    if tr.active_episode is None:
        if in_band:
            # Entered the band — start a new episode.
            tr.active_episode = ApproachEpisode(
                level_id=tr.level_id(),
                level_price=level_price,
                level_family=tr.level.family,
                level_side=tr.level.side,
                level_confluence=tr.level.confluence,
                approach_side=approach_side,
                rejection_direction=tr.rejection_direction,
                start_ts=bar.ts,
            )
            # Test counters: increment under each policy if "departed" since last.
            if tr.db_departed:
                tr.test_count_db += 1
                tr.db_departed = False
            if tr.da_departed:
                tr.test_count_da += 1
                tr.da_departed = False
            if tr.dc_departed:
                tr.test_count_dc += 1
                tr.dc_departed = False
            tr.active_episode.test_number_db = tr.test_count_db
            tr.active_episode.test_number_da = tr.test_count_da
            tr.active_episode.test_number_dc = tr.test_count_dc
        else:
            # Still outside band — arm the next entry's test counter
            if abs_dist >= DEPARTURE_PIPS_DB:
                tr.db_departed = True
            if abs_dist > 0:
                tr.da_departed = True
            tr.dc_departed = True
        return

    # ----- Episode in progress -----
    ep = tr.active_episode
    ep.bars_in_episode += 1
    if in_band:
        ep.in_band_bars += 1

    # Penetration
    if signed_bar_depth <= 0:
        pen = abs(signed_bar_depth)
        if pen > ep.max_penetration:
            ep.max_penetration = pen
    if abs_dist < ep.min_abs_distance:
        ep.min_abs_distance = abs_dist

    # Close beyond level
    if signed_close_dist < 0:
        ep.close_beyond_count += 1
        ep._curr_run_closes_beyond += 1
        if ep._curr_run_closes_beyond > ep.max_consec_closes_beyond:
            ep.max_consec_closes_beyond = ep._curr_run_closes_beyond
    else:
        ep._curr_run_closes_beyond = 0

    # Rejection detection (first bar only).  level_ladder._is_rejection_at_rung
    # uses the LADDER convention: `direction="BUY"` means "a long position
    # approaching its target resistance", which detects the bearish-rejection
    # pattern (high > rung, close < rung, close in bottom third).  Our trade
    # direction is the OPPOSITE of the ladder direction: a bearish rejection
    # at resistance produces a SELL entry, not a BUY.  Invert when calling.
    ladder_dir = "SELL" if ep.rejection_direction == "BUY" else "BUY"
    if ep.first_rejection_ts is None and (in_band or signed_bar_depth <= 0):
        is_rej = _is_rejection_at_rung(
            direction=ladder_dir,
            bar_open=bar.open,
            bar_high=bar.high,
            bar_low=bar.low,
            bar_close=bar.close,
            rung_price=level_price,
        )
        if is_rej:
            ep.first_rejection_ts = bar.ts
            ep.rejection_bar = bar
            tr.rejection_search_tail_bars = CONFIRMATION_WINDOW_BARS

    # Confirmation — only after a rejection, strictly later bars
    if ep.rejection_bar is not None and bar.ts > ep.rejection_bar.ts:
        if tr.rejection_search_tail_bars > 0:
            if ep.first_confirm_wick_ts is None:
                if ep.rejection_direction == "BUY" and bar.high > ep.rejection_bar.high:
                    ep.first_confirm_wick_ts = bar.ts
                    ep.first_confirm_wick_price = ep.rejection_bar.high
                elif ep.rejection_direction == "SELL" and bar.low < ep.rejection_bar.low:
                    ep.first_confirm_wick_ts = bar.ts
                    ep.first_confirm_wick_price = ep.rejection_bar.low
            if ep.first_confirm_close_ts is None:
                if ep.rejection_direction == "BUY" and bar.close > ep.rejection_bar.high:
                    ep.first_confirm_close_ts = bar.ts
                    ep.first_confirm_close_price = bar.close
                elif ep.rejection_direction == "SELL" and bar.close < ep.rejection_bar.low:
                    ep.first_confirm_close_ts = bar.ts
                    ep.first_confirm_close_price = bar.close
            tr.rejection_search_tail_bars -= 1

    # ----- End of episode?  Price leaves the 12-p tracking window.
    if not in_tracking:
        emitted.append(_end_episode(ep, bar.ts).as_record())
        tr.active_episode = None
        tr.db_departed = True
        tr.da_departed = True
        tr.dc_departed = True
