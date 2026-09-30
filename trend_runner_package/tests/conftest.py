"""Shared test fixtures and helpers."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the package root is importable without installation.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc


def make_m5_bar(minute_offset, o, h, l, c, base=None):
    from trend_runner.candle_source import M5Bar
    if base is None:
        base = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)
    ts = base + timedelta(minutes=5 * minute_offset)
    return M5Bar(ts=ts, o=o, h=h, l=l, c=c)


def make_bars(closes, base=None):
    """Build a bar sequence from a list of closes; H=C+0.5, L=C-0.5, O=prev C."""
    bars = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        bars.append(make_m5_bar(i, o, h, l, c, base=base))
        prev = c
    return bars
