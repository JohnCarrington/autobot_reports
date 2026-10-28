"""Build the six structural-level sets (A-F from the brief).

Every level is tagged with:
  * level_type  — 'PDH' / 'PDL' / 'SESS_H_ASIAN' / 'SESS_L_ASIAN' /
                  'SESS_H_LONDON' / 'SESS_L_LONDON' /
                  'SESS_H_NY'     / 'SESS_L_NY'     /
                  'SWING_H' / 'SWING_L' / 'DEFENDED_H' / 'DEFENDED_L' /
                  'PIVOT_P' / 'PIVOT_R1' / 'PIVOT_R2' / 'PIVOT_R3' /
                  'PIVOT_S1' / 'PIVOT_S2' / 'PIVOT_S3' /
                  'ROUND_00' / 'ROUND_50'
  * price       — the level price in GBPUSD points (1.2727 → 12727.0)
  * established_at (UTC)  — the earliest moment it is OBSERVABLE (no
                            look-ahead).  For swings, that is the
                            close of the Nth right-bar.  For session
                            and daily values, the moment the session
                            closes.  For round numbers and pivots
                            (derivable), the start of the trading day
                            they anchor.
  * meta        — level-type-specific extras (prior tests, side, …)

Nothing here uses outcomes.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import (
    Bar, UK, NY,
    fx_trading_day_label, ny_close_boundary_utc, uk_session_label,
)


# ─── Frozen parameters (preregistered — change in PREREGISTERED_HYPOTHESES.md) ─
SWING_CONFIRM_BARS = 3          # 3 bars left, 3 bars right (7-bar fractal)
DEFENDED_CLUSTER_PIPS = 10.0    # cluster swing pivots within this radius
DEFENDED_MIN_TESTS = 2          # ≥ 2 pivots → "defended"
DEFENDED_MIN_SPACING_BARS = 6   # pivots must be at least this far apart
DEFENDED_WINDOW_BARS = 288      # 1-day memory for defended-area clusters
ROUND_TICK_INTERVAL = 50.0      # points (0.0050 of FX) between round levels


# ─── Data types ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Level:
    level_type: str
    price: float
    established_at: datetime     # earliest observable timestamp (UTC)
    anchor_label: str = ""       # FX-day or session label for grouping
    meta: dict = field(default_factory=dict)


# ─── A, B.  Previous-day / previous-session H/L ─────────────────────
def previous_day_and_session_levels(bars: list[Bar]) -> list[Level]:
    """Compute PDH/PDL and ASIAN/LONDON/NY session H/L.  Each level is
    emitted at the END of the completed day / session so there is no
    look-ahead."""
    out: list[Level] = []

    # Group bars by FX trading day label
    by_day: dict[str, list[Bar]] = defaultdict(list)
    for b in bars:
        by_day[fx_trading_day_label(b.ts)].append(b)

    # PDH / PDL — emitted at FX day close; usable from the moment
    # NY 17:00 ticks over.  So previous day's levels are "known" from
    # that day's close onward.
    for day_label, day_bars in sorted(by_day.items()):
        if not day_bars:
            continue
        dh = max(b.high for b in day_bars)
        dl = min(b.low for b in day_bars)
        close_ts = ny_close_boundary_utc(day_bars[0].ts)
        out.append(Level("PDH", dh, close_ts, day_label))
        out.append(Level("PDL", dl, close_ts, day_label))

    # Session H/L — group by (FX-day, uk_session_label) and emit at
    # the LAST bar within the session for that day.  Note: session
    # labels can span midnight UTC (e.g., ASIAN at 23:00 UTC on day
    # D-1 is same session as 03:00 UTC on day D).  Group by UK local
    # date instead, pinned to the day the session STARTS (so a bar
    # at UK 23:30 that is "ASIAN" uses that calendar date; ASIAN
    # also includes 00-07 UK = UK calendar date rolled back is wrong;
    # easier: group by (UK local date of first bar in run, session)).

    # Simpler approach: walk the sorted bars and track session runs.
    cur_session = None
    cur_bars: list[Bar] = []
    runs: list[tuple[str, list[Bar]]] = []
    for b in sorted(bars, key=lambda x: x.ts):
        s = uk_session_label(b.ts)
        if s == "OFF":
            if cur_session is not None:
                runs.append((cur_session, cur_bars))
                cur_session, cur_bars = None, []
            continue
        if s != cur_session:
            if cur_session is not None:
                runs.append((cur_session, cur_bars))
            cur_session, cur_bars = s, [b]
        else:
            cur_bars.append(b)
    if cur_session is not None and cur_bars:
        runs.append((cur_session, cur_bars))

    for sess, run in runs:
        if not run:
            continue
        hi = max(b.high for b in run)
        lo = min(b.low for b in run)
        close_ts = run[-1].ts + timedelta(minutes=5)   # end of 5-min bar
        day_label = run[0].ts.astimezone(UK).strftime("%Y-%m-%d")
        out.append(Level(f"SESS_H_{sess}", hi, close_ts, f"{day_label}:{sess}"))
        out.append(Level(f"SESS_L_{sess}", lo, close_ts, f"{day_label}:{sess}"))

    return out


# ─── C.  Confirmed intraday swing H/L ────────────────────────────────
def swing_levels(bars: list[Bar]) -> list[Level]:
    """Fractal swings: swing high at bar b iff bars[b-K..b-1].high
    all < bars[b].high AND bars[b+1..b+K].high all < bars[b].high
    (strict).  Available from close of bar b+K."""
    K = SWING_CONFIRM_BARS
    out: list[Level] = []
    for i in range(K, len(bars) - K):
        is_sh = all(bars[j].high < bars[i].high for j in range(i - K, i)) \
            and all(bars[j].high < bars[i].high for j in range(i + 1, i + K + 1))
        is_sl = all(bars[j].low > bars[i].low for j in range(i - K, i)) \
            and all(bars[j].low > bars[i].low for j in range(i + 1, i + K + 1))
        confirm_ts = bars[i + K].ts + timedelta(minutes=5)  # close of right-K-th bar
        if is_sh:
            out.append(Level("SWING_H", bars[i].high, confirm_ts,
                             anchor_label=bars[i].ts.isoformat(),
                             meta={"origin_bar_ts": bars[i].ts.isoformat()}))
        if is_sl:
            out.append(Level("SWING_L", bars[i].low, confirm_ts,
                             anchor_label=bars[i].ts.isoformat(),
                             meta={"origin_bar_ts": bars[i].ts.isoformat()}))
    return out


# ─── D.  Previously-defended areas (clusters of swings) ──────────────
def defended_area_levels(bars: list[Bar], swings: list[Level]) -> list[Level]:
    """A 'defended area' is a price band of width ``DEFENDED_CLUSTER_PIPS``
    centred on the median of ≥ ``DEFENDED_MIN_TESTS`` same-side swings
    that are at least ``DEFENDED_MIN_SPACING_BARS`` apart and within
    ``DEFENDED_WINDOW_BARS`` M5 bars of each other.  The level is
    'established' at the moment the Nth swing (first time ≥ N) in
    the cluster confirms.  Subsequent swings in the same cluster do
    NOT emit new levels — the running test-count is tracked at event
    time via ``prior_tests_count`` on the EVENT, not here."""
    ts_to_i = {b.ts: i for i, b in enumerate(bars)}
    out: list[Level] = []

    for side in ("H", "L"):
        pool = sorted(
            [s for s in swings if s.level_type == f"SWING_{side}"],
            key=lambda s: s.established_at,
        )
        pool_bar_i = []
        for s in pool:
            bi = ts_to_i.get(datetime.fromisoformat(s.meta["origin_bar_ts"]))
            pool_bar_i.append(bi if bi is not None else -1)

        # Sliding-window lookback: for each new swing, look back only
        # through the window (DEFENDED_WINDOW_BARS back).  Also prune
        # by binary search on price band for speed.
        # Active defended areas (so we don't re-emit): list of (price, est_ts).
        active_areas: list[tuple[float, datetime]] = []
        ACTIVE_PRUNE_BARS = DEFENDED_WINDOW_BARS

        for i_now in range(len(pool)):
            now_bar_i = pool_bar_i[i_now]
            if now_bar_i < 0:
                continue
            s_now = pool[i_now]

            # Prune active_areas older than window
            active_areas = [
                (p, t) for p, t in active_areas
                if (now_bar_i - ts_to_i.get(t.replace(microsecond=0),
                                            -ACTIVE_PRUNE_BARS - 1)
                    if t in ts_to_i else now_bar_i - ACTIVE_PRUNE_BARS
                   ) < ACTIVE_PRUNE_BARS
            ] if False else active_areas  # keep it simple — don't bother pruning this list

            # If this swing is within tolerance of an active area, SKIP
            # (would re-emit the same level).
            if any(abs(ap - s_now.price) <= DEFENDED_CLUSTER_PIPS
                   for ap, _ in active_areas[-100:]):   # cap scan
                continue

            # Count qualifying prior swings (walk back through pool from
            # i_now-1, break out early once bar-index drop exceeds window)
            earlier_prices = []
            for j in range(i_now - 1, -1, -1):
                prior_bar_i = pool_bar_i[j]
                if prior_bar_i < 0:
                    continue
                dbar = now_bar_i - prior_bar_i
                if dbar >= DEFENDED_WINDOW_BARS:
                    break
                if dbar < DEFENDED_MIN_SPACING_BARS:
                    continue
                if abs(pool[j].price - s_now.price) > DEFENDED_CLUSTER_PIPS:
                    continue
                earlier_prices.append(pool[j].price)

            if len(earlier_prices) + 1 >= DEFENDED_MIN_TESTS:
                prices = earlier_prices + [s_now.price]
                px = sum(prices) / len(prices)
                out.append(Level(
                    f"DEFENDED_{side}", round(px, 2), s_now.established_at,
                    anchor_label=s_now.anchor_label,
                    meta={"n_tests": len(prices)},
                ))
                active_areas.append((px, s_now.established_at))

    return out


# ─── E.  Classical daily pivots ──────────────────────────────────────
def pivot_levels(bars: list[Bar]) -> list[Level]:
    """Classical pivots from prior FX-day H/L/C.  Observable from the
    FX day close that TERMINATES the prior day (NY 17:00)."""
    by_day: dict[str, list[Bar]] = defaultdict(list)
    for b in bars:
        by_day[fx_trading_day_label(b.ts)].append(b)
    sorted_days = sorted(by_day.items())
    out: list[Level] = []
    for prev, nxt in zip(sorted_days[:-1], sorted_days[1:]):
        prev_label, prev_bars = prev
        next_label, next_bars = nxt
        if not prev_bars or not next_bars:
            continue
        H = max(b.high for b in prev_bars)
        L = min(b.low for b in prev_bars)
        C = prev_bars[-1].close  # last bar of prior FX day
        P = (H + L + C) / 3.0
        R1 = 2 * P - L
        S1 = 2 * P - H
        R2 = P + (H - L)
        S2 = P - (H - L)
        R3 = H + 2 * (P - L)
        S3 = L - 2 * (H - P)
        # Observable at: close of prior FX day (= start of next FX day)
        ts = ny_close_boundary_utc(prev_bars[0].ts)
        for name, px in (("PIVOT_P", P),
                         ("PIVOT_R1", R1), ("PIVOT_R2", R2), ("PIVOT_R3", R3),
                         ("PIVOT_S1", S1), ("PIVOT_S2", S2), ("PIVOT_S3", S3)):
            out.append(Level(name, round(px, 2), ts, next_label))
    return out


# ─── F.  Round-number levels (00 / 50 points) ─────────────────────────
def round_number_levels(bars: list[Bar]) -> list[Level]:
    """Enumerate every round level (ending in .00 or .50 at the FX
    pip-point) across the price span the bars touch.  Established at
    'epoch' (every round level has always existed)."""
    if not bars:
        return []
    px_min = min(b.low for b in bars)
    px_max = max(b.high for b in bars)
    # 50-point grid.  12345 → floor(12345/50)*50 = 12300
    k_lo = int(px_min // ROUND_TICK_INTERVAL) - 1
    k_hi = int(px_max // ROUND_TICK_INTERVAL) + 2
    epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out: list[Level] = []
    for k in range(k_lo, k_hi):
        price = k * ROUND_TICK_INTERVAL
        tag = "ROUND_00" if (int(price) % 100 == 0) else "ROUND_50"
        out.append(Level(tag, round(price, 2), epoch, f"grid:{int(price)}"))
    return out


def all_levels(bars: list[Bar]) -> list[Level]:
    """Compute the full set of levels for a date range of M5 bars."""
    pdh_pdl_sess = previous_day_and_session_levels(bars)
    swings = swing_levels(bars)
    defended = defended_area_levels(bars, swings)
    pivots = pivot_levels(bars)
    rounds = round_number_levels(bars)
    return pdh_pdl_sess + swings + defended + pivots + rounds


if __name__ == "__main__":
    # Smoke test with one day of data
    from common import read_day, load_range
    import pprint
    start = datetime(2024, 1, 15, tzinfo=timezone.utc)
    end = datetime(2024, 1, 19, 23, 59, tzinfo=timezone.utc)
    bars = load_range(start, end)
    print(f"Loaded {len(bars)} bars from {start.date()} to {end.date()}")
    levels = all_levels(bars)
    from collections import Counter
    counts = Counter(l.level_type for l in levels)
    print("Level counts:")
    for lt, n in sorted(counts.items()):
        print(f"  {lt:16} {n}")
