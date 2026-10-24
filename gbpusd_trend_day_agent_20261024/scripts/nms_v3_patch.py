"""Monkey-patch NMS V3's _london_open_for to use proper per-year UK BST
rules instead of the production module's 2026-only hardcoded window.

Do NOT import this in production — research only.
"""
from __future__ import annotations
import datetime as _dt
import sys
sys.path.insert(0, '<autobot_prod_root>')
import nms_v3_classifier as nms  # noqa: E402


def _last_sunday(year: int, month: int) -> _dt.date:
    d = _dt.date(year, month, 31)
    if month == 3:
        # last day of March
        pass
    else:
        d = _dt.date(year, month, 31)
    while d.weekday() != 6:
        d -= _dt.timedelta(days=1)
    return d


def _patched_london_open_for(session_date: str):
    """London open UTC: 07:00 during BST (last Sun Mar → last Sun Oct),
    08:00 otherwise."""
    d = _dt.datetime.fromisoformat(session_date + "T00:00:00+00:00").date()
    bst_start = _last_sunday(d.year, 3)
    bst_end = _last_sunday(d.year, 10)
    hour = 7 if (bst_start <= d < bst_end) else 8
    return _dt.datetime.fromisoformat(
        f"{session_date}T{hour:02d}:00:00+00:00"
    )


nms._london_open_for = _patched_london_open_for
