"""Event detection + response classification.

An EVENT = the first M5 bar whose high (upward approach) or low
(downward approach) comes within TOUCH_TOL_PIPS of an eligible level
that was established at least AGE_MIN_BARS ago and not currently
"on cool-down" for that level (dedup window).

The response classifier walks the next ``RESPONSE_HORIZON_BARS``
M5 bars and labels the response as one of Type 1-4:

    * TYPE_1_DIRECT_REJECT  — penetration ≤ MAX_WICK_PENETRATION
      AND close drifted ≥ REJECT_MIN_DRIFT away from the level on
      the ORIGINAL side within horizon.
    * TYPE_2_SWEEP_RECLAIM  — penetration > MAX_WICK_PENETRATION
      AND close returned to the ORIGINAL side within RECLAIM_WINDOW
      bars after the first pierce.
    * TYPE_3_ACCEPTED_BREAKOUT — penetration > MAX_WICK_PENETRATION
      AND at least ACCEPTANCE_CLOSES consecutive bar CLOSES on the
      FAR side within horizon.
    * TYPE_4_REPEATED_TEST    — within horizon, price touches the
      level within TOUCH_TOL_PIPS AGAIN (independent, in-session,
      not merely a continuation of the first approach).  Can co-exist
      with Type 1/2/3 (as a label) but we also classify the DOMINANT
      type with Type 4 only if nothing else fits.

Both-hit-same-bar ambiguity: when a single M5 bar both pierces AND
returns inside the level, the bar is treated as AMBIGUOUS for the
pierce classification; dominant type falls to the subsequent bars.

All frozen parameters live in Phase-1 preregistration.
"""
from __future__ import annotations

import bisect
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, uk_session_label, fx_trading_day_label
from levels import Level, all_levels


# ─── Frozen parameters ───────────────────────────────────────────────
TOUCH_TOL_PIPS = 3.0              # bar high/low must come within this of level
AGE_MIN_BARS = 1                  # level must be at least this old (M5 bars)
EVENT_DEDUP_WINDOW_BARS = 30      # same level, same side → one event every 150 min
SESSION_START_UK = 7              # events only during UK 07:00 - 20:00
SESSION_END_UK = 20               # (exclusive)

RESPONSE_HORIZON_BARS = 30        # 150 min
MAX_WICK_PENETRATION = 3.0        # pips past level to still be "no break"
REJECT_MIN_DRIFT = 10.0           # min pip movement BACK on original side
RECLAIM_WINDOW = 3                # bars within which a sweep must reclaim
ACCEPTANCE_CLOSES = 3             # consecutive closes on far side → acceptance

# Categorical bucket used to pool related level types for Q4
LEVEL_FAMILIES = {
    "PDH": "PREV_DAY", "PDL": "PREV_DAY",
    "SESS_H_ASIAN": "PREV_SESSION", "SESS_L_ASIAN": "PREV_SESSION",
    "SESS_H_LONDON": "PREV_SESSION", "SESS_L_LONDON": "PREV_SESSION",
    "SESS_H_NY": "PREV_SESSION", "SESS_L_NY": "PREV_SESSION",
    "SWING_H": "SWING", "SWING_L": "SWING",
    "DEFENDED_H": "DEFENDED", "DEFENDED_L": "DEFENDED",
    "PIVOT_P": "PIVOT", "PIVOT_R1": "PIVOT", "PIVOT_R2": "PIVOT",
    "PIVOT_R3": "PIVOT", "PIVOT_S1": "PIVOT",
    "PIVOT_S2": "PIVOT", "PIVOT_S3": "PIVOT",
    "ROUND_00": "ROUND", "ROUND_50": "ROUND",
}

LEVEL_SIDE = {   # upper (resistance-like) vs lower (support-like)
    "PDH": "UPPER", "PDL": "LOWER",
    "SESS_H_ASIAN": "UPPER", "SESS_L_ASIAN": "LOWER",
    "SESS_H_LONDON": "UPPER", "SESS_L_LONDON": "LOWER",
    "SESS_H_NY": "UPPER", "SESS_L_NY": "LOWER",
    "SWING_H": "UPPER", "SWING_L": "LOWER",
    "DEFENDED_H": "UPPER", "DEFENDED_L": "LOWER",
    # Pivots don't have a fixed side; "approach from below" = UPPER,
    # "approach from above" = LOWER.  Treated as BOTH.
    "PIVOT_P": "BOTH", "PIVOT_R1": "BOTH", "PIVOT_R2": "BOTH",
    "PIVOT_R3": "BOTH", "PIVOT_S1": "BOTH",
    "PIVOT_S2": "BOTH", "PIVOT_S3": "BOTH",
    "ROUND_00": "BOTH", "ROUND_50": "BOTH",
}


@dataclass
class Event:
    event_id: str
    date: str
    event_ts_utc: str
    event_bar_idx: int           # within the full bars list of the pipeline
    level_type: str
    level_family: str
    level_price: float
    approach_side: str           # 'UPPER' = approach from below (test resistance)
                                 # 'LOWER' = approach from above (test support)
    distance_into_level_pts: float    # bar's deepest penetration past level (0 if did not pierce)
    distance_to_level_pts: float      # extremum distance to level at the touch bar
    approach_speed_pts_per_5m: float  # avg abs close-to-close move last 6 bars
    volatility_pts: float             # BB-width 20-bar (if computed by caller)
    atr14_pts: float                  # ATR(14) if computed by caller
    prior_tests_count: int            # within the same FX day prior to this event
    level_age_bars: int               # bars since established
    session: str
    overlap_tags: list[str]           # other level types the bar also touches
    meta: dict = field(default_factory=dict)


# ─── Approach-speed / ATR helpers ───────────────────────────────────
def _approach_speed(bars: list[Bar], i: int) -> float:
    if i < 6:
        return 0.0
    return sum(abs(bars[j].close - bars[j - 1].close) for j in range(i - 5, i + 1)) / 6.0


def _atr14(bars: list[Bar]) -> list[float | None]:
    n = len(bars)
    out: list[float | None] = [None] * n
    if n < 15:
        return out
    trs = []
    for i in range(1, n):
        prev = bars[i - 1]
        cur = bars[i]
        tr = max(cur.high - cur.low,
                 abs(cur.high - prev.close),
                 abs(cur.low - prev.close))
        trs.append(tr)
    # Wilder ATR (14)
    if len(trs) < 14:
        return out
    atr = sum(trs[:14]) / 14.0
    out[14] = atr
    for i in range(15, n):
        atr = (atr * 13 + trs[i - 1]) / 14.0
        out[i] = atr
    return out


# ─── Event detection ─────────────────────────────────────────────────
def detect_events(bars: list[Bar], levels: list[Level]) -> list[Event]:
    """One pass over bars with a price-sorted observable-level index
    for O(log n) nearest-level lookup via bisect.

    Scope filter: only emit events during UK session (07:00-20:00).
    """
    if not bars:
        return []

    from common import UK
    bar_ts = [b.ts for b in bars]
    atr = _atr14(bars)

    # Build an age lookup: for every level, which bar index was the
    # first bar at or after its ``established_at``?
    # Levels established mid-bar (e.g., pivots at exact NY close) are
    # observable from the next bar onward.
    def bar_idx_for_ts(ts: datetime) -> int:
        # bisect_left on bar_ts for ts; returns the index of the first
        # bar whose ts >= target.  Clamp to [0, len-1].
        idx = bisect.bisect_left(bar_ts, ts)
        return min(idx, len(bars) - 1)

    # Pre-compute each level's "visible from bar" index + prepare
    # sorted-by-price lists updated as time progresses.
    sorted_levels = sorted(levels, key=lambda L: L.established_at)
    level_visible_from = [bar_idx_for_ts(L.established_at) for L in sorted_levels]
    level_cursor = 0

    # Price-sorted observable index.  Stores (price, level_type_idx) pairs
    # — we keep level objects in a parallel list.
    obs_prices: list[float] = []   # sorted
    obs_levels: list[Level] = []   # same order as obs_prices
    obs_visible_bar: list[int] = []  # bar idx when the level became visible

    last_touch_bar: dict[tuple[str, float, str], int] = {}
    tests_this_day: dict[tuple[str, float, str, str], int] = {}

    events: list[Event] = []
    event_counter = 0

    for i, b in enumerate(bars):
        # Advance observable index for levels now visible
        while level_cursor < len(sorted_levels) and level_visible_from[level_cursor] <= i:
            L = sorted_levels[level_cursor]
            # Insert into sorted-by-price lists
            pos = bisect.bisect_left(obs_prices, L.price)
            obs_prices.insert(pos, L.price)
            obs_levels.insert(pos, L)
            obs_visible_bar.insert(pos, level_visible_from[level_cursor])
            level_cursor += 1

        # Session filter
        uk_h = b.ts.astimezone(UK).hour
        if not (SESSION_START_UK <= uk_h < SESSION_END_UK):
            continue

        # Candidate range on sorted price list
        lo_search = b.low - TOUCH_TOL_PIPS
        hi_search = b.high + TOUCH_TOL_PIPS
        lo_i = bisect.bisect_left(obs_prices, lo_search)
        hi_i = bisect.bisect_right(obs_prices, hi_search)

        if lo_i >= hi_i:
            continue

        prev_close = bars[i - 1].close if i > 0 else b.open
        candidates = []
        for k in range(lo_i, hi_i):
            L = obs_levels[k]
            if (i - obs_visible_bar[k]) < AGE_MIN_BARS:
                continue
            dist_to = min(abs(b.high - L.price), abs(b.low - L.price))
            if dist_to > TOUCH_TOL_PIPS:
                continue
            natural = LEVEL_SIDE[L.level_type]
            if natural == "UPPER":
                side = "UPPER"
                if prev_close >= L.price:
                    continue
            elif natural == "LOWER":
                side = "LOWER"
                if prev_close <= L.price:
                    continue
            else:
                side = "UPPER" if prev_close < L.price else "LOWER"
            candidates.append((L, side, i - obs_visible_bar[k], dist_to))

        if not candidates:
            continue

        candidates.sort(key=lambda tup: tup[3])
        dom_L, dom_side, dom_age, dom_dist = candidates[0]
        overlap_tags = [c[0].level_type for c in candidates[1:]]

        # Dedup
        key = (dom_L.level_type, round(dom_L.price, 2), dom_side)
        last_i = last_touch_bar.get(key)
        if last_i is not None and (i - last_i) < EVENT_DEDUP_WINDOW_BARS:
            continue
        last_touch_bar[key] = i

        # Test count within same FX day (approach only)
        fx = fx_trading_day_label(b.ts)
        tkey = (dom_L.level_type, round(dom_L.price, 2), dom_side, fx)
        tests_this_day[tkey] = tests_this_day.get(tkey, 0) + 1
        prior_tests = tests_this_day[tkey] - 1

        # Penetration past level
        if dom_side == "UPPER":
            # approach from below testing resistance; penetration = max(0, high - level)
            pen = max(0.0, b.high - dom_L.price)
        else:
            pen = max(0.0, dom_L.price - b.low)

        events.append(Event(
            event_id=f"E{event_counter:06d}",
            date=b.ts.strftime("%Y-%m-%d"),
            event_ts_utc=b.ts.isoformat(),
            event_bar_idx=i,
            level_type=dom_L.level_type,
            level_family=LEVEL_FAMILIES[dom_L.level_type],
            level_price=round(dom_L.price, 2),
            approach_side=dom_side,
            distance_into_level_pts=round(pen, 2),
            distance_to_level_pts=round(dom_dist, 2),
            approach_speed_pts_per_5m=round(_approach_speed(bars, i), 3),
            volatility_pts=round(atr[i] if atr[i] is not None else 0.0, 2),
            atr14_pts=round(atr[i] if atr[i] is not None else 0.0, 2),
            prior_tests_count=prior_tests,
            level_age_bars=dom_age,
            session=uk_session_label(b.ts),
            overlap_tags=overlap_tags,
        ))
        event_counter += 1

    return events


# ─── Response classification ────────────────────────────────────────
@dataclass
class ResponseLabel:
    event_id: str
    type_label: str           # TYPE_1_DIRECT_REJECT / … / UNCLASSIFIED
    repeated_test_flag: bool  # separate tag; co-exists with primary
    max_pen_pts: float
    min_drift_pts: float      # min distance of close from level on reversal side
    acceptance_closes: int    # consecutive bar closes on FAR side
    reclaim_bar_offset: int   # bars until close returned to original side (−1 if never)
    net_pts_at_h: float       # close @ event+H minus event close, signed +ve on reversal side
    bars_to_resolution: int


def classify_response(bars: list[Bar], ev: Event) -> ResponseLabel:
    i0 = ev.event_bar_idx
    level = ev.level_price
    side = ev.approach_side        # UPPER = tested resistance (approach from below)
    end = min(i0 + RESPONSE_HORIZON_BARS, len(bars) - 1)
    event_close = bars[i0].close

    max_pen = 0.0
    reclaim_bar = -1
    pierced = False
    acceptance_run = 0
    best_acceptance = 0
    best_drift = 0.0

    # Walk from i0 (inclusive) to end
    for i in range(i0, end + 1):
        b = bars[i]
        if side == "UPPER":  # resistance test; pierce = above level
            bar_pen = max(0.0, b.high - level)
            close_far = b.close > level + MAX_WICK_PENETRATION
            close_orig = b.close < level - 0.0  # close back on original side (below)
            drift_now = max(0.0, level - b.close)  # how far below level the close is
        else:
            bar_pen = max(0.0, level - b.low)
            close_far = b.close < level - MAX_WICK_PENETRATION
            close_orig = b.close > level + 0.0
            drift_now = max(0.0, b.close - level)

        if bar_pen > max_pen:
            max_pen = bar_pen
        if bar_pen > MAX_WICK_PENETRATION:
            pierced = True

        # Acceptance run tracking
        if close_far:
            acceptance_run += 1
            if acceptance_run > best_acceptance:
                best_acceptance = acceptance_run
        else:
            acceptance_run = 0

        # Reclaim: a pierce has happened in a prior bar and we now close orig
        if reclaim_bar < 0 and pierced and close_orig and i > i0:
            reclaim_bar = i - i0

        if drift_now > best_drift:
            best_drift = drift_now

    # Net pts at horizon
    net = (bars[end].close - event_close) if side == "UPPER" else (event_close - bars[end].close)
    # NB: 'reversal direction' from an UPPER approach = DOWN (price falls),
    # so the reversal is PROFITABLE when close drops from the touch.  We
    # want net > 0 in reversal direction; for UPPER that means event_close
    # - bars[end].close.  Fix sign:
    if side == "UPPER":
        net = event_close - bars[end].close
    else:
        net = bars[end].close - event_close

    # Classification
    if pierced and best_acceptance >= ACCEPTANCE_CLOSES:
        label = "TYPE_3_ACCEPTED_BREAKOUT"
    elif pierced and 0 < reclaim_bar <= RECLAIM_WINDOW:
        label = "TYPE_2_SWEEP_RECLAIM"
    elif (not pierced) and best_drift >= REJECT_MIN_DRIFT:
        label = "TYPE_1_DIRECT_REJECT"
    elif pierced and reclaim_bar > RECLAIM_WINDOW:
        # pierced + reclaimed late — treat as sweep but tagged slow
        label = "TYPE_2_SWEEP_RECLAIM"
    elif pierced:  # pierced but neither reclaimed nor accepted → nowhere went
        label = "UNCLASSIFIED_PIERCE"
    else:
        label = "UNCLASSIFIED_NO_REJECTION"

    # Repeated-test flag — any additional touch within tolerance in the
    # horizon window, on the same side, more than EVENT_DEDUP_WINDOW/5
    # bars later (to not count the original bar).
    repeated = False
    orig_bar = bars[i0]
    for i in range(i0 + 2, end + 1):
        b = bars[i]
        dist_i = min(abs(b.high - level), abs(b.low - level))
        if dist_i <= TOUCH_TOL_PIPS:
            # Natural approach side matches
            prev_close = bars[i - 1].close
            if side == "UPPER" and prev_close < level:
                repeated = True; break
            if side == "LOWER" and prev_close > level:
                repeated = True; break

    return ResponseLabel(
        event_id=ev.event_id,
        type_label=label,
        repeated_test_flag=repeated,
        max_pen_pts=round(max_pen, 2),
        min_drift_pts=round(best_drift, 2),
        acceptance_closes=best_acceptance,
        reclaim_bar_offset=reclaim_bar,
        net_pts_at_h=round(net, 2),
        bars_to_resolution=end - i0,
    )


if __name__ == "__main__":
    # Smoke-test on 2 weeks of 2024 Jan
    from common import load_range
    start = datetime(2024, 1, 15, tzinfo=timezone.utc)
    end = datetime(2024, 1, 26, 23, 59, tzinfo=timezone.utc)
    bars = load_range(start, end)
    print(f"Loaded {len(bars)} bars.")
    levels = all_levels(bars)
    print(f"Computed {len(levels)} levels.")
    events = detect_events(bars, levels)
    print(f"Detected {len(events)} events.")
    responses = [classify_response(bars, e) for e in events]
    from collections import Counter
    c = Counter(r.type_label for r in responses)
    print("Response distribution:")
    for lbl, n in sorted(c.items(), key=lambda x: -x[1]):
        print(f"  {lbl:30}  {n}")
    rep = sum(1 for r in responses if r.repeated_test_flag)
    print(f"Repeated-test flag share: {rep}/{len(responses)} = {100*rep/len(responses):.1f}%")
