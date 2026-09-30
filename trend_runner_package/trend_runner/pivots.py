"""Daily pivot points from the previous *completed* FX day.

FX day boundary convention: 22:00 UTC roll (Sunday 22:00 UTC -> Monday
22:00 UTC = "Monday" in pivot terms). This is documented as the
current source convention; the chart_reference note in docs/architecture
explains verification against IG's daily bar close (which also uses
22:00 UTC on most weeks).

Pivot formulae (classic floor-trader):
    P  = (H + L + C) / 3
    R1 = 2P - L
    S1 = 2P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    R3 = H + 2 * (P - L)
    S3 = L - 2 * (H - P)

A pivot day is *complete* only if we have coverage of the expected
session, not simply "≥240 bars". We require both endpoints to be
present (a bar starting within 5 minutes of the day open and a bar
within 5 minutes of the day close) and enforce a minimum sample
count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from .time_utils import UTC, PIVOT_DAY_ROLL_UTC, pivot_day_bounds


MIN_BARS_PER_DAY = 240  # 20h * 12 M5 bars is our floor; weekends filtered separately.


@dataclass(frozen=True)
class DailyOHLC:
    day_start_utc: datetime
    day_end_utc: datetime
    o: float
    h: float
    l: float
    c: float
    bar_count: int


@dataclass(frozen=True)
class PivotSet:
    day_start_utc: datetime
    day_end_utc: datetime
    P: float
    R1: float
    R2: float
    R3: float
    S1: float
    S2: float
    S3: float


def compute_pivots(daily: DailyOHLC) -> PivotSet:
    P = (daily.h + daily.l + daily.c) / 3.0
    hl = daily.h - daily.l
    return PivotSet(
        day_start_utc=daily.day_start_utc,
        day_end_utc=daily.day_end_utc,
        P=P,
        R1=2 * P - daily.l,
        S1=2 * P - daily.h,
        R2=P + hl,
        S2=P - hl,
        R3=daily.h + 2 * (P - daily.l),
        S3=daily.l - 2 * (daily.h - P),
    )


def aggregate_fx_day(
    bars: Iterable[tuple[datetime, float, float, float, float]],
    day_start: datetime,
    day_end: datetime,
) -> Optional[DailyOHLC]:
    """Aggregate M5 bars whose *start* time falls within [day_start, day_end).

    Requires at least MIN_BARS_PER_DAY samples and coverage of both ends
    (start and close within 60 minutes of the boundary). Returns None
    if any check fails.
    """
    accepted: List[tuple[datetime, float, float, float, float]] = []
    for ts, o, h, l, c in bars:
        if day_start <= ts < day_end:
            accepted.append((ts, o, h, l, c))
    if len(accepted) < MIN_BARS_PER_DAY:
        return None
    accepted.sort(key=lambda r: r[0])
    first_ts = accepted[0][0]
    last_ts = accepted[-1][0]
    if (first_ts - day_start) > timedelta(minutes=60):
        return None
    if (day_end - (last_ts + timedelta(minutes=5))) > timedelta(minutes=60):
        return None
    o = accepted[0][1]
    c = accepted[-1][4]
    h = max(r[2] for r in accepted)
    l = min(r[3] for r in accepted)
    return DailyOHLC(day_start, day_end, o, h, l, c, len(accepted))


def pivots_for_bar(
    bar_time_utc: datetime,
    bars_getter,
) -> Optional[PivotSet]:
    """Return the pivots for the FX day preceding the bar at *bar_time_utc*.

    `bars_getter(day_start, day_end) -> Iterable[(ts, o, h, l, c)]`
    """
    day_start, day_end = pivot_day_bounds(bar_time_utc)
    ohlc = aggregate_fx_day(bars_getter(day_start, day_end), day_start, day_end)
    if ohlc is None:
        return None
    return compute_pivots(ohlc)
