"""Regression test for 2026-07-28 fix: BB_BOUNCE armed-setup dict must
carry a real h1_dir/h1_strength snapshot even when the H1 counter-gate
is DISABLED. Before the fix, the compute lived inside
`if H1_COUNTER_GATE_ENABLED:`; with the gate off (.env prod default from
2026-05-28), every BB_BOUNCE fill's `bb_h1_*_at_arm` telemetry was null.
Gate off must mean "don't block", never "don't measure".
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

sys.path.insert(0, "/opt/tradingbot")

import gbpusd_bb_bounce as bb  # noqa: E402
import indicators as _ind  # noqa: E402
from gbpusd_bb_bounce import Bar  # noqa: E402


SYMBOL = "GBPUSD"
EPIC = "CS.D.GBPUSD.TODAY.IP"


def _ts(start: datetime, i: int) -> datetime:
    return start + timedelta(minutes=5 * i)


def _bar(ts, o, h, l, c) -> Bar:
    return Bar(timestamp=ts, open=o, high=h, low=l, close=c)


def _build_pierce_scenario():
    """20 baseline closes + a prev-bar LONG pierce (BBL ≈ 13340, low 13330)."""
    baseline = [13342.0 + ((-1) ** i) * 1.0 for i in range(19)]
    baseline.append(13340.0)
    start = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    bars: List[Bar] = []
    for i, c in enumerate(baseline):
        bars.append(_bar(_ts(start, i), c, c + 0.3, c - 0.3, c))
    # Overwrite last bar to force a clear LONG pierce shape.
    prev_ts = _ts(start, 19)
    bars[-1] = _bar(prev_ts, 13340.0, 13340.5, 13330.0, 13337.0)
    baseline[-1] = 13337.0
    return bars, baseline, start


@pytest.fixture
def _isolate_bb(tmp_path, monkeypatch):
    """Force BB strategy on, disable side machines, keep lifecycle log inert."""
    p = tmp_path / "bb_bounce_lifecycle.jsonl"
    monkeypatch.setattr(bb, "_BB_BOUNCE_LIFECYCLE_LOG_PATH", str(p))
    monkeypatch.setattr(bb, "_BB_BOUNCE_LIFECYCLE_LOG_ENABLED", False)
    monkeypatch.setattr(bb, "ENABLED", True)
    monkeypatch.setattr(bb, "BB_BOUNCE_ARM_AND_WAIT_ENABLED", False)
    monkeypatch.setattr(bb, "GBPUSD_BB_NEARTOUCH_ENABLED", False)
    monkeypatch.setattr(bb, "BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED", False)


def _stub_h1(payload: Dict[str, Any]):
    def _f(symbol, pip_size=None, **_):
        return payload
    return _f


def test_armed_setup_carries_real_h1_when_gate_disabled(_isolate_bb, monkeypatch):
    """Prime-suspect scenario: GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=0
    (as it has been since 2026-05-28). The fix computes the H1 snapshot
    unconditionally for telemetry; the armed dict must carry real values."""
    monkeypatch.setattr(bb, "H1_COUNTER_GATE_ENABLED", False)
    monkeypatch.setattr(
        _ind, "h1_ema_direction",
        _stub_h1({"direction": "BULLISH", "separation_strength": 0.35}),
    )

    bars, closes, start = _build_pierce_scenario()
    # Feed a cur bar that will NOT fire a rejection (bearish body) — pierce
    # arms on prev, no fire, we can inspect _armed_setups directly.
    cur = _bar(_ts(start, 20), 13337.0, 13337.5, 13335.0, 13335.5)
    bars2 = bars + [cur]
    closes2 = closes + [13335.5]

    s = bb.GbpUsdBBBounceStrategy()
    s.evaluate(symbol=SYMBOL, epic=EPIC, ts=cur.timestamp,
               bars=bars2, closes_ind=closes2)

    armed = s._armed_setups.get(EPIC) or []
    long_arms = [a for a in armed if a.get("direction") == "LONG"
                 and not a.get("near_touch")]
    assert long_arms, f"expected at least one armed LONG pierce, got {armed!r}"
    a = long_arms[0]
    assert a["h1_dir_at_arm"] == "BULLISH", (
        f"telemetry-only compute skipped when gate disabled — a={a!r}"
    )
    assert a["h1_strength_at_arm"] == pytest.approx(0.35), (
        f"h1_strength must be threaded when gate off — a={a!r}"
    )


def test_armed_setup_carries_real_h1_when_gate_enabled(_isolate_bb, monkeypatch):
    """Behaviour parity: gate on + eligible H1 → arms with real values."""
    monkeypatch.setattr(bb, "H1_COUNTER_GATE_ENABLED", True)
    monkeypatch.setattr(bb, "H1_COUNTER_STRENGTH_FLOOR", 0.0)
    monkeypatch.setattr(bb, "H1_COUNTER_STRENGTH_CEILING", 0.9)
    # LONG pierce requires H1 BEARISH for the counter-gate to pass.
    monkeypatch.setattr(
        _ind, "h1_ema_direction",
        _stub_h1({"direction": "BEARISH", "separation_strength": 0.22}),
    )

    bars, closes, start = _build_pierce_scenario()
    cur = _bar(_ts(start, 20), 13337.0, 13337.5, 13335.0, 13335.5)
    bars2 = bars + [cur]
    closes2 = closes + [13335.5]

    s = bb.GbpUsdBBBounceStrategy()
    s.evaluate(symbol=SYMBOL, epic=EPIC, ts=cur.timestamp,
               bars=bars2, closes_ind=closes2)

    armed = s._armed_setups.get(EPIC) or []
    long_arms = [a for a in armed if a.get("direction") == "LONG"
                 and not a.get("near_touch")]
    assert long_arms, f"expected armed LONG (counter-H1), got {armed!r}"
    a = long_arms[0]
    assert a["h1_dir_at_arm"] == "BEARISH"
    assert a["h1_strength_at_arm"] == pytest.approx(0.22)


def test_h1_warmup_leaves_none_without_raising(_isolate_bb, monkeypatch):
    """Indicator returns None (warmup / not enough H1 candles) → armed dict
    carries None for both fields; no exception escapes; setup still arms
    when the gate is DISABLED (gate-off is fail-open for telemetry)."""
    monkeypatch.setattr(bb, "H1_COUNTER_GATE_ENABLED", False)
    monkeypatch.setattr(_ind, "h1_ema_direction", _stub_h1(None))

    bars, closes, start = _build_pierce_scenario()
    cur = _bar(_ts(start, 20), 13337.0, 13337.5, 13335.0, 13335.5)
    bars2 = bars + [cur]
    closes2 = closes + [13335.5]

    s = bb.GbpUsdBBBounceStrategy()
    s.evaluate(symbol=SYMBOL, epic=EPIC, ts=cur.timestamp,
               bars=bars2, closes_ind=closes2)

    armed = s._armed_setups.get(EPIC) or []
    long_arms = [a for a in armed if a.get("direction") == "LONG"
                 and not a.get("near_touch")]
    assert long_arms, f"gate off + h1 warmup must still arm, got {armed!r}"
    a = long_arms[0]
    assert a["h1_dir_at_arm"] is None
    assert a["h1_strength_at_arm"] is None


def test_h1_raise_gate_off_still_arms_with_none(_isolate_bb, monkeypatch):
    """h1_ema_direction raises + gate DISABLED → telemetry stays None,
    setup still arms (fail-open for telemetry). Gate ON would fail-closed;
    that is covered by the pre-existing warning path."""
    monkeypatch.setattr(bb, "H1_COUNTER_GATE_ENABLED", False)

    def _boom(*a, **kw):
        raise RuntimeError("h1 indicator boom")
    monkeypatch.setattr(_ind, "h1_ema_direction", _boom)

    bars, closes, start = _build_pierce_scenario()
    cur = _bar(_ts(start, 20), 13337.0, 13337.5, 13335.0, 13335.5)
    bars2 = bars + [cur]
    closes2 = closes + [13335.5]

    s = bb.GbpUsdBBBounceStrategy()
    s.evaluate(symbol=SYMBOL, epic=EPIC, ts=cur.timestamp,
               bars=bars2, closes_ind=closes2)

    armed = s._armed_setups.get(EPIC) or []
    long_arms = [a for a in armed if a.get("direction") == "LONG"
                 and not a.get("near_touch")]
    assert long_arms, f"raise + gate off must still arm, got {armed!r}"
    a = long_arms[0]
    assert a["h1_dir_at_arm"] is None
    assert a["h1_strength_at_arm"] is None


def test_h1_raise_gate_on_fails_closed(_isolate_bb, monkeypatch):
    """Parity check: h1_ema_direction raises + gate ENABLED → setup NOT
    armed. Preserves pre-2026-07-28 fail-closed semantics."""
    monkeypatch.setattr(bb, "H1_COUNTER_GATE_ENABLED", True)

    def _boom(*a, **kw):
        raise RuntimeError("h1 indicator boom")
    monkeypatch.setattr(_ind, "h1_ema_direction", _boom)

    bars, closes, start = _build_pierce_scenario()
    cur = _bar(_ts(start, 20), 13337.0, 13337.5, 13335.0, 13335.5)
    bars2 = bars + [cur]
    closes2 = closes + [13335.5]

    s = bb.GbpUsdBBBounceStrategy()
    s.evaluate(symbol=SYMBOL, epic=EPIC, ts=cur.timestamp,
               bars=bars2, closes_ind=closes2)

    armed = s._armed_setups.get(EPIC) or []
    long_arms = [a for a in armed if a.get("direction") == "LONG"
                 and not a.get("near_touch")]
    assert not long_arms, (
        f"raise + gate on must fail closed (no arm), got {armed!r}"
    )
