"""Time / session utilities.

Bars are labelled by START time. A bar starting at 12:15 UTC completes
at 12:20 UTC and its indicators become available at 12:20 UTC.

Trading session (initial policy):
    London weekdays 07:00-15:00 Europe/London for entry, session close
    at 17:00 Europe/London.

Pivot day boundary: previous completed FX day = last-completed 22:00
UTC to 22:00 UTC window. This matches typical broker daily aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

try:  # pragma: no cover - runtime path
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9
    from backports.zoneinfo import ZoneInfo  # type: ignore

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")

BAR_SECONDS_M5 = 300
BAR_SECONDS_H1 = 3600

# Session policy (all times Europe/London wall clock).
LONDON_ENTRY_START = time(7, 0)
LONDON_ENTRY_END = time(15, 0)  # last-entry cutoff (exclusive of :00 minute end)
LONDON_SESSION_CLOSE = time(17, 0)

# Pivot day boundary: 22:00 UTC previous day -> 22:00 UTC current day.
PIVOT_DAY_ROLL_UTC = time(22, 0)


def bar_completion_time(start: datetime, bar_seconds: int) -> datetime:
    """Return the UTC completion instant of a bar starting at `start`."""
    return start + timedelta(seconds=bar_seconds)


def is_weekday_london(dt_utc: datetime) -> bool:
    return dt_utc.astimezone(LONDON).weekday() < 5


def london_now(dt_utc: datetime) -> datetime:
    return dt_utc.astimezone(LONDON)


def in_entry_window(dt_utc: datetime) -> bool:
    """True when *dt_utc* falls in the London weekday entry window."""
    ldn = dt_utc.astimezone(LONDON)
    if ldn.weekday() >= 5:
        return False
    t = ldn.timetz().replace(tzinfo=None)
    return LONDON_ENTRY_START <= t < LONDON_ENTRY_END


def is_session_close(dt_utc: datetime) -> bool:
    """True at or after the London session-close threshold on a weekday."""
    ldn = dt_utc.astimezone(LONDON)
    if ldn.weekday() >= 5:
        return True
    t = ldn.timetz().replace(tzinfo=None)
    return t >= LONDON_SESSION_CLOSE


def pivot_day_bounds(dt_utc: datetime) -> tuple[datetime, datetime]:
    """Return [prev-fx-day-start, prev-fx-day-end) in UTC for a bar time.

    A bar timestamped 07:00 UTC on Tuesday looks up pivots computed
    from the FX day 22:00 UTC Sunday .. 22:00 UTC Monday.
    """
    anchor = dt_utc.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    day_end = datetime.combine(anchor.date(), PIVOT_DAY_ROLL_UTC, tzinfo=UTC)
    if anchor < day_end:
        # We are before today's roll; the *last completed* day ends yesterday 22:00 UTC.
        day_end = day_end - timedelta(days=1)
    day_start = day_end - timedelta(days=1)
    return day_start, day_end


def previous_fx_calendar_date(dt_utc: datetime) -> date:
    """Return the ISO calendar date the previous FX day is *filed under*.

    We file a day by the calendar date of its 22:00 UTC roll. The FX
    day ending 22:00 UTC Monday is filed as ``Monday`` for pivot use on
    Tuesday's London session.
    """
    _, day_end = pivot_day_bounds(dt_utc)
    return (day_end - timedelta(minutes=1)).date()


@dataclass(frozen=True)
class BarWindow:
    start: datetime
    end: datetime  # completion instant

    @property
    def midpoint(self) -> datetime:
        return self.start + (self.end - self.start) / 2


def iter_m5_starts(day_utc: date) -> Iterable[datetime]:
    """Iterate the 288 nominal M5 bar starts for *day_utc* (UTC midnight-anchored)."""
    day_start = datetime.combine(day_utc, time(0, 0), tzinfo=UTC)
    for i in range(288):
        yield day_start + timedelta(minutes=5 * i)
