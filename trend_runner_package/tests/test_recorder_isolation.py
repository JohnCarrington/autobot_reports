from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from trend_runner.recorder_source import M5Aggregator, Tick, parse_line


UTC = timezone.utc


def test_parse_recorder_line_filters_by_epic():
    good = json.dumps({"ts": "2026-06-01T07:00:00+00:00", "epic": "CS.D.GBPUSD.MINI.IP",
                       "bid": 1.34210, "ask": 1.34216})
    other = json.dumps({"ts": "2026-06-01T07:00:00+00:00", "epic": "CS.D.EURUSD.MINI.IP",
                        "bid": 1.11000, "ask": 1.11005})
    assert parse_line(good, "CS.D.GBPUSD.MINI.IP") is not None
    assert parse_line(other, "CS.D.GBPUSD.MINI.IP") is None
    assert parse_line("not-json", "CS.D.GBPUSD.MINI.IP") is None


def test_recorder_source_never_connects_to_ig():
    """M5Aggregator + parse_line have no IG session imports."""
    import trend_runner.recorder_source as rs
    src = open(rs.__file__).read()
    # No IG or streaming client code paths in this module.
    import ast
    tree = ast.parse(src)
    imports = {name.name for node in ast.walk(tree) if isinstance(node, ast.Import)
               for name in node.names}
    from_imports = {node.module for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module}
    forbidden = {"lightstreamer", "trading_ig", "ig", "requests"}
    for mod in imports | from_imports:
        base = mod.split(".", 1)[0]
        assert base not in forbidden, f"recorder_source imports {mod}"


def test_m5_aggregator_emits_only_completed_bars():
    agg = M5Aggregator()
    base = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)
    # Ticks within one 5-minute window
    for i in range(5):
        assert agg.push(Tick(ts=base + timedelta(seconds=30 * i),
                             bid=1000.0 + i * 0.1, ask=1000.05 + i * 0.1)) is None
    # A tick after 5 minutes rolls the bar.
    bar = agg.push(Tick(ts=base + timedelta(minutes=5, seconds=1),
                        bid=1001.0, ask=1001.05))
    assert bar is not None
    assert bar.ts == base  # start of the closed bar
