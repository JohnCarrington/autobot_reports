"""Unit coverage for the BB_BOUNCE near-touch fade path (2026-07-10).

The near-touch path complements the pierce path: qualifies bars where the
extreme is within BB_NEARTOUCH_PROX_PIPS of the band but does NOT reach
PIERCE_THRESH_PIPS. Fires only when the tier's touch-count / momentum
qualification is met:

    RANGE_ROTATION    — first qualifying touch may fire.
    FORMING / CHOP    — require BB_NEARTOUCH_MIN_TOUCHES prior same-zone.
    STRONG_TREND_*    — arm on first touch; fire on second ONLY if
                        momentum softened (|h1_hist| dropped OR
                        h1_decel_streak >= 1).

These tests exercise the pure helpers so behaviour is not entangled with
the full evaluate() pipeline (cascade, forensic, standdown, etc.). The
integration proof is delivered by the replay script against recorded
candles for the three missed 2026-07-09/10 tops.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import gbpusd_bb_bounce as bb  # noqa: E402


@pytest.fixture(autouse=True)
def _pin_neartouch_module_defaults(monkeypatch):
    """Pin bb module attrs to the module defaults so tests are hermetic
    against .env pollution via upstream load_dotenv() + importlib.reload
    (test_bb_bounce_cascade_gate.py reloads bb, which then reads polluted
    os.environ). Individual tests are free to override via monkeypatch.setattr."""
    monkeypatch.setattr(bb, "PIERCE_THRESH_PIPS", 2.0)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_PROX_PIPS", 1.5)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES", 2)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_S", 2)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_L", 2)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_ZONE_TOL_PIPS", 3.0)


def _bar(ts_iso: str, o: float, h: float, l: float, c: float) -> bb.Bar:
    return bb.Bar(
        timestamp=datetime.fromisoformat(ts_iso).replace(tzinfo=timezone.utc),
        open=o, high=h, low=l, close=c,
    )


# ─── (1) _detect_near_touch_setup — direction contract & thresholds ──────
def test_detect_near_touch_upper_within_prox_returns_short():
    prev = _bar("2026-07-10T06:15:00", 13433.75, 13435.15, 13427.75, 13435.15)
    # BBU=13434.79; high=13435.15 → over by 0.36p (within 1.5 prox, not
    # a >= 2.0p pierce). Expect SHORT.
    d, reason = bb._detect_near_touch_setup(
        prev, bb_lower_at_prev=13423.09, bb_upper_at_prev=13434.79,
        pip_size=1.0, prox_pips=1.5,
    )
    assert d == "SHORT" and reason == ""


def test_detect_near_touch_lower_within_prox_returns_long():
    prev = _bar("2026-07-10T07:00:00", 13425.00, 13426.00, 13421.60, 13424.00)
    # BBL=13423.00; low=13421.60 → below by 1.4p (within 1.5 prox, not
    # a >= 2.0p pierce). Expect LONG.
    d, _ = bb._detect_near_touch_setup(
        prev, bb_lower_at_prev=13423.00, bb_upper_at_prev=13440.00,
        pip_size=1.0, prox_pips=1.5,
    )
    assert d == "LONG"


def test_detect_near_touch_defers_to_pierce_when_deep_enough():
    """A bar that is ALSO a >= PIERCE_THRESH pierce must not return
    near-touch. The pierce path owns those setups."""
    prev = _bar("2026-07-10T06:15:00", 13433.75, 13437.50, 13427.75, 13435.00)
    # high=13437.50 vs BBU=13434.79 → 2.71p pierce (>= 2.0). Should defer.
    d, _ = bb._detect_near_touch_setup(
        prev, bb_lower_at_prev=13423.09, bb_upper_at_prev=13434.79,
        pip_size=1.0, prox_pips=1.5,
    )
    assert d is None


def test_detect_near_touch_far_from_band_returns_none():
    prev = _bar("2026-07-10T06:15:00", 13429.00, 13430.00, 13428.00, 13429.50)
    # No wick near either band.
    d, _ = bb._detect_near_touch_setup(
        prev, bb_lower_at_prev=13423.00, bb_upper_at_prev=13434.79,
        pip_size=1.0, prox_pips=1.5,
    )
    assert d is None


# ─── (2) _touches_in_zone — same-zone match & tolerance ─────────────────
def test_touches_in_zone_matches_within_tol():
    S = bb.GbpUsdBBBounceStrategy
    touches = [
        {"side": "UPPER", "ts": "t1", "band_price": 13435.0, "h1_hist_at_touch": 1.2},
        {"side": "UPPER", "ts": "t2", "band_price": 13434.2, "h1_hist_at_touch": 1.0},
        {"side": "LOWER", "ts": "t3", "band_price": 13423.0, "h1_hist_at_touch": -0.5},
        {"side": "UPPER", "ts": "t4", "band_price": 13432.0, "h1_hist_at_touch": 0.6},
    ]
    z = S._touches_in_zone(touches, side="UPPER", band_price=13434.5,
                           tol_pips=3.0, pip_size=1.0)
    # t1 (0.5p away), t2 (0.3p), t4 (2.5p) all within 3.0p. t3 wrong side.
    assert [t["ts"] for t in z] == ["t1", "t2", "t4"]


def test_touches_in_zone_excludes_outside_tol():
    S = bb.GbpUsdBBBounceStrategy
    touches = [
        {"side": "UPPER", "ts": "t1", "band_price": 13430.0},
        {"side": "UPPER", "ts": "t2", "band_price": 13440.0},  # 5.5p away
    ]
    z = S._touches_in_zone(touches, side="UPPER", band_price=13434.5,
                           tol_pips=3.0, pip_size=1.0)
    assert [t["ts"] for t in z] == []  # both outside 3.0p from 13434.5


# ─── (3) _resolve_neartouch_tier — regime → tier mapping ─────────────────
def test_tier_range_rotation():
    S = bb.GbpUsdBBBounceStrategy
    assert S._resolve_neartouch_tier("RANGE_ROTATION", False) == "RANGE"


def test_tier_strong_trend_becomes_strong():
    S = bb.GbpUsdBBBounceStrategy
    assert S._resolve_neartouch_tier("STRONG_TREND_UP", False) == "STRONG"
    assert S._resolve_neartouch_tier("STRONG_TREND_DOWN", False) == "STRONG"


def test_tier_strong_but_conf_floored_demotes_to_forming():
    """A STRONG label with conf_floor_applied is not actually strong."""
    S = bb.GbpUsdBBBounceStrategy
    assert S._resolve_neartouch_tier("STRONG_TREND_UP", True) == "FORMING"


def test_tier_forming_and_chop_are_forming():
    S = bb.GbpUsdBBBounceStrategy
    for lbl in ("TREND_FORMING_UP", "TREND_FORMING_DOWN", "CHOP",
                "UNKNOWN", None, ""):
        assert S._resolve_neartouch_tier(lbl, False) == "FORMING"


# ─── (4) _neartouch_qualifies — tiered gate ─────────────────────────────
def test_range_first_touch_qualifies():
    S = bb.GbpUsdBBBounceStrategy()
    ok, reason = S._neartouch_qualifies(
        tier="RANGE", direction="SHORT",
        prior_zone_touches=[],
        h1_hist_now=1.0, h1_decel_streak=0,
    )
    assert ok is True
    assert "range_first_touch" in reason


def test_forming_first_touch_never_fires():
    """Even with prior_zone_touches empty and rejection candle setup, the
    FORMING tier requires BB_NEARTOUCH_MIN_TOUCHES=2 prior."""
    S = bb.GbpUsdBBBounceStrategy()
    ok, reason = S._neartouch_qualifies(
        tier="FORMING", direction="SHORT",
        prior_zone_touches=[],
        h1_hist_now=1.0, h1_decel_streak=0,
    )
    assert ok is False
    assert "forming_needs_touches" in reason
    assert "prior_in_zone=0" in reason


def test_forming_second_touch_still_needs_more():
    S = bb.GbpUsdBBBounceStrategy()
    ok, _ = S._neartouch_qualifies(
        tier="FORMING", direction="SHORT",
        prior_zone_touches=[{"side": "UPPER", "band_price": 13435.0}],
        h1_hist_now=1.0, h1_decel_streak=0,
    )
    assert ok is False  # 1 prior < 2 required


def test_forming_third_touch_qualifies():
    S = bb.GbpUsdBBBounceStrategy()
    ok, reason = S._neartouch_qualifies(
        tier="FORMING", direction="SHORT",
        prior_zone_touches=[
            {"side": "UPPER", "band_price": 13435.0},
            {"side": "UPPER", "band_price": 13434.5},
        ],
        h1_hist_now=1.0, h1_decel_streak=0,
    )
    assert ok is True
    assert "forming_min_touches" in reason


def test_strong_first_touch_arms_only():
    """STRONG tier's arm-only: no prior => not-ok, reason='strong_needs_prior_touch'."""
    S = bb.GbpUsdBBBounceStrategy()
    ok, reason = S._neartouch_qualifies(
        tier="STRONG", direction="SHORT",
        prior_zone_touches=[],
        h1_hist_now=1.5, h1_decel_streak=0,
    )
    assert ok is False and "strong_needs_prior_touch" in reason


def test_strong_second_touch_needs_soften_hist_magnitude():
    """Second touch: |h1_hist|_now < |h1_hist|_arm → qualifies."""
    S = bb.GbpUsdBBBounceStrategy()
    prior = [{"side": "UPPER", "band_price": 13435.0,
              "h1_hist_at_touch": 1.5}]
    ok, reason = S._neartouch_qualifies(
        tier="STRONG", direction="SHORT",
        prior_zone_touches=prior,
        h1_hist_now=1.0, h1_decel_streak=0,
    )
    assert ok is True
    assert "strong_momentum_softened" in reason


def test_strong_second_touch_needs_soften_decel_streak_alt():
    """Second touch: |h1_hist| flat/growing but decel_streak >= 1 → qualifies."""
    S = bb.GbpUsdBBBounceStrategy()
    prior = [{"side": "UPPER", "band_price": 13435.0,
              "h1_hist_at_touch": 1.0}]
    ok, reason = S._neartouch_qualifies(
        tier="STRONG", direction="SHORT",
        prior_zone_touches=prior,
        h1_hist_now=1.2, h1_decel_streak=1,
    )
    assert ok is True and "strong_momentum_softened" in reason


def test_strong_second_touch_no_soften_blocks():
    """Second touch, |h1_hist| growing AND streak 0 → blocked."""
    S = bb.GbpUsdBBBounceStrategy()
    prior = [{"side": "UPPER", "band_price": 13435.0,
              "h1_hist_at_touch": 1.0}]
    ok, reason = S._neartouch_qualifies(
        tier="STRONG", direction="SHORT",
        prior_zone_touches=prior,
        h1_hist_now=1.2, h1_decel_streak=0,
    )
    assert ok is False and "strong_no_soften" in reason


def test_strong_missing_h1_hist_arms_only():
    """H1 hist unknown at touch time → cannot verify soften → do not fire."""
    S = bb.GbpUsdBBBounceStrategy()
    prior = [{"side": "UPPER", "band_price": 13435.0,
              "h1_hist_at_touch": None}]
    ok, reason = S._neartouch_qualifies(
        tier="STRONG", direction="SHORT",
        prior_zone_touches=prior,
        h1_hist_now=None, h1_decel_streak=0,
    )
    assert ok is False and "strong_missing_h1_hist" in reason


# ─── (4b) per-side touch-count split (2026-07-10) ──────────────────────
# BB_NEARTOUCH_MIN_TOUCHES_S / _L override the uniform FORMING minimum
# per direction. Scope guard: RANGE + STRONG tiers must remain untouched
# by any combination of these vars.
def test_forming_short_fires_first_touch_when_s_is_1(monkeypatch):
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_S", 1)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_L", 2)
    S = bb.GbpUsdBBBounceStrategy()
    ok, reason = S._neartouch_qualifies(
        tier="FORMING", direction="SHORT",
        prior_zone_touches=[],
        h1_hist_now=1.0, h1_decel_streak=0,
    )
    # 0 prior + need=1 → still short of 1; second touch (1 prior) fires.
    assert ok is False and "forming_needs_touches" in reason
    ok2, reason2 = S._neartouch_qualifies(
        tier="FORMING", direction="SHORT",
        prior_zone_touches=[{"side": "UPPER", "band_price": 13435.0}],
        h1_hist_now=1.0, h1_decel_streak=0,
    )
    assert ok2 is True and "forming_min_touches" in reason2
    assert ">=1" in reason2


def test_forming_long_still_needs_two_with_l_is_2(monkeypatch):
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_S", 1)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_L", 2)
    S = bb.GbpUsdBBBounceStrategy()
    ok, reason = S._neartouch_qualifies(
        tier="FORMING", direction="LONG",
        prior_zone_touches=[{"side": "LOWER", "band_price": 13423.0}],
        h1_hist_now=-1.0, h1_decel_streak=0,
    )
    assert ok is False and "forming_needs_touches" in reason
    ok2, _ = S._neartouch_qualifies(
        tier="FORMING", direction="LONG",
        prior_zone_touches=[
            {"side": "LOWER", "band_price": 13423.0},
            {"side": "LOWER", "band_price": 13423.2},
        ],
        h1_hist_now=-1.0, h1_decel_streak=0,
    )
    assert ok2 is True


def test_forming_legacy_byte_identical_when_per_side_unset(monkeypatch):
    """Env unset → per-side constants fall back to BB_NEARTOUCH_MIN_TOUCHES,
    then to the hard default 2. Exercise the same _env_int primitive the
    module uses at load time (avoids importlib.reload racing with polluted
    os.environ from upstream load_dotenv leaks), then confirm behaviour
    parity by monkeypatching attrs to the resolved fallback values."""
    # Case 1: nothing set anywhere → base default 2 → per-side 2/2
    monkeypatch.delenv("BB_NEARTOUCH_MIN_TOUCHES_S", raising=False)
    monkeypatch.delenv("BB_NEARTOUCH_MIN_TOUCHES_L", raising=False)
    monkeypatch.delenv("BB_NEARTOUCH_MIN_TOUCHES", raising=False)
    base = bb._env_int("BB_NEARTOUCH_MIN_TOUCHES", 2)
    assert base == 2
    assert bb._env_int("BB_NEARTOUCH_MIN_TOUCHES_S", base) == 2
    assert bb._env_int("BB_NEARTOUCH_MIN_TOUCHES_L", base) == 2
    # Case 2: only legacy BB_NEARTOUCH_MIN_TOUCHES=3 → both per-side 3
    monkeypatch.setenv("BB_NEARTOUCH_MIN_TOUCHES", "3")
    base = bb._env_int("BB_NEARTOUCH_MIN_TOUCHES", 2)
    assert base == 3
    assert bb._env_int("BB_NEARTOUCH_MIN_TOUCHES_S", base) == 3
    assert bb._env_int("BB_NEARTOUCH_MIN_TOUCHES_L", base) == 3
    # Case 3: L overrides base, S falls back
    monkeypatch.setenv("BB_NEARTOUCH_MIN_TOUCHES_L", "5")
    assert bb._env_int("BB_NEARTOUCH_MIN_TOUCHES_L", base) == 5
    assert bb._env_int("BB_NEARTOUCH_MIN_TOUCHES_S", base) == 3
    # Behavioural parity: with per-side pinned to 2 (the legacy value),
    # BOTH directions require 2 prior — identical to pre-split behaviour
    # (test_forming_first_touch_never_fires + test_forming_third_touch_qualifies).
    S = bb.GbpUsdBBBounceStrategy()
    for direction in ("SHORT", "LONG"):
        ok, _ = S._neartouch_qualifies(
            tier="FORMING", direction=direction,
            prior_zone_touches=[],
            h1_hist_now=1.0, h1_decel_streak=0,
        )
        assert ok is False  # 0 < 2 (pinned via autouse fixture)
        ok2, _ = S._neartouch_qualifies(
            tier="FORMING", direction=direction,
            prior_zone_touches=[
                {"side": "UPPER", "band_price": 13435.0},
                {"side": "UPPER", "band_price": 13434.5},
            ],
            h1_hist_now=1.0, h1_decel_streak=0,
        )
        assert ok2 is True  # 2 >= 2


def test_strong_tier_untouched_by_per_side_vars(monkeypatch):
    """STRONG path never reads BB_NEARTOUCH_MIN_TOUCHES_{S,L}. Regression
    fence: the accelerating-top refusal case still refuses, and the
    momentum-soften pass case still passes, with either per-side var set
    to anything."""
    for s_val, l_val in ((1, 2), (2, 1), (0, 0), (5, 5)):
        monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_S", s_val)
        monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_L", l_val)
        S = bb.GbpUsdBBBounceStrategy()
        # Accelerating: |h1|_now > |h1|_arm and no decel streak → refuse.
        prior_grow = [{"side": "UPPER", "band_price": 13435.0,
                       "h1_hist_at_touch": 1.0}]
        ok_refuse, reason_refuse = S._neartouch_qualifies(
            tier="STRONG", direction="SHORT",
            prior_zone_touches=prior_grow,
            h1_hist_now=1.2, h1_decel_streak=0,
        )
        assert ok_refuse is False and "strong_no_soften" in reason_refuse, (
            f"STRONG refuse case broke at S={s_val} L={l_val}")
        # Softened: |h1|_now < |h1|_arm → pass.
        prior_soften = [{"side": "UPPER", "band_price": 13435.0,
                         "h1_hist_at_touch": 1.5}]
        ok_pass, reason_pass = S._neartouch_qualifies(
            tier="STRONG", direction="SHORT",
            prior_zone_touches=prior_soften,
            h1_hist_now=1.0, h1_decel_streak=0,
        )
        assert ok_pass is True and "strong_momentum_softened" in reason_pass, (
            f"STRONG soften case broke at S={s_val} L={l_val}")
        # First-touch arm-only path still refuses regardless of per-side.
        ok_arm, reason_arm = S._neartouch_qualifies(
            tier="STRONG", direction="LONG",
            prior_zone_touches=[],
            h1_hist_now=-1.5, h1_decel_streak=0,
        )
        assert ok_arm is False and "strong_needs_prior_touch" in reason_arm


def test_range_tier_untouched_by_per_side_vars(monkeypatch):
    """RANGE first-touch-fires stays true even when the per-side vars are
    cranked to values that would block FORMING."""
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_S", 99)
    monkeypatch.setattr(bb, "BB_NEARTOUCH_MIN_TOUCHES_L", 99)
    S = bb.GbpUsdBBBounceStrategy()
    for direction in ("SHORT", "LONG"):
        ok, reason = S._neartouch_qualifies(
            tier="RANGE", direction=direction,
            prior_zone_touches=[],
            h1_hist_now=1.0, h1_decel_streak=0,
        )
        assert ok is True and "range_first_touch" in reason


# ─── (5) session boundary reset ────────────────────────────────────────
def test_session_touches_reset_on_new_utc_day():
    s = bb.GbpUsdBBBounceStrategy()
    ts_yday = datetime(2026, 7, 9, 15, 30, tzinfo=timezone.utc)
    s._reset_session_touches_if_new_day("EPIC.X", ts_yday)
    s._record_session_touch("EPIC.X", side="UPPER",
                             ts=ts_yday, band_price=13435.0,
                             bar_extreme=13435.2, h1_hist=1.0)
    assert len(s._session_touches["EPIC.X"]) == 1
    # Same day → no wipe.
    ts_same = datetime(2026, 7, 9, 18, 5, tzinfo=timezone.utc)
    s._reset_session_touches_if_new_day("EPIC.X", ts_same)
    assert len(s._session_touches["EPIC.X"]) == 1
    # New day → wipe.
    ts_today = datetime(2026, 7, 10, 6, 15, tzinfo=timezone.utc)
    s._reset_session_touches_if_new_day("EPIC.X", ts_today)
    assert s._session_touches["EPIC.X"] == []


# ─── (6) direction contract: near-touch never fires with-pierce direction
def test_direction_contract_upper_short_lower_long():
    """UPPER touch => SHORT direction only; LOWER => LONG only.
    A LONG can never be spawned by a bar whose HIGH pokes the upper band."""
    # High near BBU with low well inside band → must be SHORT (or None).
    prev = _bar("2026-07-10T06:15:00", 13433.0, 13434.9, 13432.0, 13433.5)
    d, _ = bb._detect_near_touch_setup(
        prev, bb_lower_at_prev=13423.0, bb_upper_at_prev=13434.5,
        pip_size=1.0, prox_pips=1.5,
    )
    assert d == "SHORT"
    # Low near BBL with high well inside band → must be LONG (or None).
    prev2 = _bar("2026-07-10T06:15:00", 13424.5, 13425.0, 13422.6, 13423.5)
    d2, _ = bb._detect_near_touch_setup(
        prev2, bb_lower_at_prev=13423.0, bb_upper_at_prev=13434.5,
        pip_size=1.0, prox_pips=1.5,
    )
    assert d2 == "LONG"
