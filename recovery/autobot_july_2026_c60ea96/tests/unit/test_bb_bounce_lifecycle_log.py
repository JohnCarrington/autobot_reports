"""
Regression test for the BB_BOUNCE setup-lifecycle JSONL audit
(added 2026-07-24 after the operator reported 3 days of BB_BOUNCE
silence with no observable reason).

Covers the three silent early-returns in
gbpusd_bb_bounce.GbpUsdBBBounceStrategy.evaluate():

    1. `_in_window(ts) == False` while armed setups exist
       → event="outside_window_deferred"
    2. Expiry sweep removes setups whose age exceeds
       REJECTION_WINDOW_BARS
       → event="expired"
    3. `fired_setup is None` while armed setups exist (no bar
       matched the direction/body/tolerance criteria)
       → event="no_rejection"

Each hook is telemetry-only: the tests assert the JSONL row appears
AND that the strategy still returns None (behaviour unchanged).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

sys.path.insert(0, "/opt/tradingbot")

import gbpusd_bb_bounce as bb  # noqa: E402
from gbpusd_bb_bounce import Bar  # noqa: E402


SYMBOL = "GBPUSD"
EPIC = "CS.D.GBPUSD.TODAY.IP"


def _ts(start: datetime, i: int) -> datetime:
    return start + timedelta(minutes=5 * i)


def _bar(ts, o, h, l, c) -> Bar:
    return Bar(timestamp=ts, open=o, high=h, low=l, close=c)


@pytest.fixture
def lifecycle_path(tmp_path, monkeypatch):
    """Redirect the lifecycle log to a per-test temp file so multiple
    tests don't cross-contaminate. Also disables the H1_COUNTER_GATE
    (which fails-closed without an H1 candle cache) and the arm-and-
    wait state machine, so tests focus on the vanilla arm→rejection
    path where the lifecycle hooks live."""
    p = tmp_path / "bb_bounce_lifecycle.jsonl"
    monkeypatch.setattr(bb, "_BB_BOUNCE_LIFECYCLE_LOG_PATH", str(p))
    monkeypatch.setattr(bb, "_BB_BOUNCE_LIFECYCLE_LOG_ENABLED", True)
    # GBPUSD_BB_BOUNCE_ENABLED defaults to 0 in the test env; force it
    # on so evaluate() doesn't short-circuit at line 1155.
    monkeypatch.setattr(bb, "ENABLED", True)
    monkeypatch.setattr(bb, "H1_COUNTER_GATE_ENABLED", False)
    monkeypatch.setattr(bb, "BB_BOUNCE_ARM_AND_WAIT_ENABLED", False)
    monkeypatch.setattr(bb, "GBPUSD_BB_NEARTOUCH_ENABLED", False)
    # BB_BOUNCE_STRONG_TREND_STANDDOWN reads regime_engine which isn't
    # populated in unit-test env; disable so its fail-open path doesn't
    # mask an actual bug.
    monkeypatch.setattr(bb, "BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED", False)
    return p


def _read_events(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _build_pierce_scenario():
    """Build a 20-bar closes-history producing BBL ≈ 13337 (the exact
    16:40 arm from 2026-07-24 PID 2033476 armed at BBl=13337.35), then
    two bars that arm a LONG pierce.
    """
    # 20 tight closes near 13342 so BB centre stays there and BB lower
    # sits close enough that a wick under 13337 pierces by ~0.5p+.
    baseline = [13342.0 + ((-1) ** i) * 1.0 for i in range(19)]
    prev_close = 13340.0
    baseline.append(prev_close)
    # prev bar (bars[-2]): pierces BBL with wick, open inside band.
    #   open 13340 (inside — BBL is roughly 13340), low 13335 (5p pierce),
    #   close 13337 (inside/near BBL).
    start = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    bars: List[Bar] = []
    for i, c in enumerate(baseline):
        bars.append(_bar(_ts(start, i), c, c + 0.3, c - 0.3, c))
    return bars, baseline, start


def test_no_rejection_row_written_when_armed_and_bar_bearish(lifecycle_path):
    """Arm a LONG pierce, then feed a bearish cur bar with body >=1.5p.
    Verify a no_rejection lifecycle row appears with reason and body pips.
    """
    bars, closes, start = _build_pierce_scenario()
    # Force previous bar into a LONG pierce shape.
    prev_ts = _ts(start, 19)
    bars[-1] = _bar(prev_ts, 13340.0, 13340.5, 13330.0, 13337.0)
    closes[-1] = 13337.0

    s = bb.GbpUsdBBBounceStrategy()

    # First call: bars[-2] = prev arm bar (13340→13337 low-pierce),
    # bars[-1] = an evaluation bar with bearish body (won't fire, will arm).
    cur1 = _bar(_ts(start, 20), 13337.0, 13337.5, 13335.0, 13335.5)
    bars2 = bars + [cur1]
    closes2 = closes + [13335.5]
    dec = s.evaluate(symbol=SYMBOL, epic=EPIC, ts=cur1.timestamp,
                     bars=bars2, closes_ind=closes2)
    assert dec is None, "bearish cur → strategy must not fire on this bar"

    events = _read_events(lifecycle_path)
    no_rej = [e for e in events if e["event"] == "no_rejection"]
    assert no_rej, (
        "expected a no_rejection lifecycle row after arm+bearish-bar. "
        f"events={events!r}"
    )
    row = no_rej[-1]
    assert row["symbol"] == "GBPUSD"
    assert row["epic"] == EPIC
    assert row["armed_count"] >= 1
    assert row["cur_bar"]["bullish"] is False
    assert row["reason"] in {"bearish_body_only_LONG_armed", "body_too_small"}


def test_expired_row_written_when_setup_ages_past_window(lifecycle_path):
    """Arm a LONG pierce, then step forward REJECTION_WINDOW_BARS+1 bars of
    bearish micro-bars so expiry drops the setup. Verify expired row."""
    bars, closes, start = _build_pierce_scenario()
    prev_ts = _ts(start, 19)
    bars[-1] = _bar(prev_ts, 13340.0, 13340.5, 13330.0, 13337.0)
    closes[-1] = 13337.0

    s = bb.GbpUsdBBBounceStrategy()
    # Feed REJECTION_WINDOW_BARS+1 bearish micro-bars; body <1.5p so no
    # rejection but not-yet-expired-then-expired.
    seq_bars = list(bars)
    seq_closes = list(closes)
    for step in range(1, bb.REJECTION_WINDOW_BARS + 2):
        cur = _bar(
            _ts(start, 19 + step),
            13337.0, 13337.2, 13336.7, 13336.8,  # tiny bearish body 0.20p
        )
        seq_bars.append(cur)
        seq_closes.append(cur.close)
        s.evaluate(symbol=SYMBOL, epic=EPIC, ts=cur.timestamp,
                   bars=seq_bars, closes_ind=seq_closes)

    events = _read_events(lifecycle_path)
    exp = [e for e in events if e["event"] == "expired"]
    assert exp, (
        f"expected expired row after {bb.REJECTION_WINDOW_BARS+1} bars. "
        f"events={[e['event'] for e in events]!r}"
    )
    row = exp[-1]
    assert row["expired_count"] >= 1
    assert row["window_bars"] == bb.REJECTION_WINDOW_BARS
    dirs = {e["direction"] for e in row["expired"]}
    assert "LONG" in dirs


def test_outside_window_deferred_row_when_armed_and_after_close(lifecycle_path):
    """Directly seed an armed setup, then call evaluate with ts >= WIN_END.
    Confirms the guard at the top of evaluate fires the lifecycle row
    before the silent return."""
    s = bb.GbpUsdBBBounceStrategy()
    # Seed one armed LONG setup pretending we armed it at 16:45 UTC.
    armed_ts = datetime(2026, 7, 24, 16, 45, tzinfo=timezone.utc)
    s._armed_setups[EPIC] = [{
        "setup_ts": armed_ts,
        "direction": "LONG",
        "bbl_setup": 13336.11,
        "bbu_setup": 13346.47,
        "setup_bar": _bar(armed_ts, 13336.25, 13336.45, 13332.55, 13333.95),
        "h1_dir_at_arm": None,
        "h1_strength_at_arm": None,
    }]

    # Call evaluate at 17:00 UTC — exactly the boundary that silenced
    # the operator's 16:45 arm today (WIN_END defaults to 17:00, strict <).
    out_of_win = datetime(2026, 7, 24, 17, 0, tzinfo=timezone.utc)
    dec = s.evaluate(
        symbol=SYMBOL, epic=EPIC, ts=out_of_win,
        bars=[], closes_ind=[],
    )
    assert dec is None, "outside window must return None"

    events = _read_events(lifecycle_path)
    win = [e for e in events if e["event"] == "outside_window_deferred"]
    assert win, f"expected outside_window_deferred row; got events={events!r}"
    row = win[-1]
    assert row["armed_count"] == 1
    assert row["armed"][0]["direction"] == "LONG"
    assert row["win_end_h"] == 17


def test_outside_window_no_row_when_no_armed_setups(lifecycle_path):
    """Sanity check: an out-of-window call with no armed setups must NOT
    emit a lifecycle row (would flood the log with heartbeat spam)."""
    s = bb.GbpUsdBBBounceStrategy()
    out_of_win = datetime(2026, 7, 24, 22, 0, tzinfo=timezone.utc)
    dec = s.evaluate(
        symbol=SYMBOL, epic=EPIC, ts=out_of_win,
        bars=[], closes_ind=[],
    )
    assert dec is None
    events = _read_events(lifecycle_path)
    assert not events, (
        f"no armed setups → no lifecycle rows expected; got {events!r}"
    )


def test_lifecycle_disabled_writes_nothing(tmp_path, monkeypatch):
    """When BB_BOUNCE_LIFECYCLE_LOG_ENABLED=0, no JSONL file is created
    even in scenarios that would otherwise emit rows."""
    p = tmp_path / "should_not_exist.jsonl"
    monkeypatch.setattr(bb, "_BB_BOUNCE_LIFECYCLE_LOG_PATH", str(p))
    monkeypatch.setattr(bb, "_BB_BOUNCE_LIFECYCLE_LOG_ENABLED", False)

    s = bb.GbpUsdBBBounceStrategy()
    s._armed_setups[EPIC] = [{
        "setup_ts": datetime(2026, 7, 24, 16, 45, tzinfo=timezone.utc),
        "direction": "LONG",
        "bbl_setup": 13336.11,
        "bbu_setup": 13346.47,
        "setup_bar": _bar(
            datetime(2026, 7, 24, 16, 45, tzinfo=timezone.utc),
            13336.25, 13336.45, 13332.55, 13333.95,
        ),
        "h1_dir_at_arm": None,
        "h1_strength_at_arm": None,
    }]
    s.evaluate(
        symbol=SYMBOL, epic=EPIC,
        ts=datetime(2026, 7, 24, 17, 0, tzinfo=timezone.utc),
        bars=[], closes_ind=[],
    )
    assert not p.exists(), "kill-switch must prevent file creation"
