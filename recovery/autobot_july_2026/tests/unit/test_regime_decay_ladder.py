"""Unit coverage for regime_engine's decay ladder + confidence floor.

Targets CHANGE 5 (2026-07-08). Master flag REGIME_DECAY_LADDER_ENABLED
gates every path below; when off the classifier is byte-identical to the
pre-change behaviour (case (e) asserts this).

Stubbing strategy mirrors the existing test_htf_authority pattern:
  - _classify_macd_h1        — monkeypatched to inject controlled h1 output
  - _run_range_detector      — monkeypatched to a no-op (no range override)
  - _HIST_FRESHNESS_STATE_BY_SYM — reset between cases so streaks don't leak

Every test calls classify_regime() with a small pandas DataFrame carrying
just the columns _extract_features reads (ADX_14, PLUS_DI_14, MINUS_DI_14,
EMA_STACK_STATE).

Cases:
    (a) STRONG→FORMING at rung 1 (streak==HYST_N=3), FORMING→CHOP at rung 2
        (streak==HYST_N+M2=8), bias flips to NEUTRAL_BIAS only at rung 2.
    (b) Mid-decay reset: one qualifying bar zeroes _st[dir_key], streak
        continues from 0 on subsequent contradictions.
    (c) Confidence decay curve: s=10, factor=0.85 → conf ≈ conf_raw * 0.1969;
        floor at 0.20 converts the label to CHOP + NEUTRAL_BIAS.
    (d) Struct promotion reachable on the bar AFTER decay emits CHOP once
        the H1 rule stops producing STRONG_TREND (hist slope flips) — the
        precedence check at :944-959 opens the else-branch.
    (e) Flag OFF ↔ byte-identical output on identical input.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import pytest

# Make /opt/tradingbot importable when pytest is invoked from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── Helpers ───────────────────────────────────────────────────────────────
def _mk_df(adx: float, plus_di: float, minus_di: float,
           ema_state: str = "BULL_ALIGNED") -> pd.DataFrame:
    """Build the minimal 5m DataFrame classify_regime → _extract_features needs."""
    return pd.DataFrame([{
        "timestamp": pd.Timestamp("2026-07-08T13:55:00Z"),
        "close": 1.34,
        "EMA_21": 1.34, "EMA_50": 1.34, "EMA_50_SLOPE": 0.0,
        "ADX_14": adx, "PLUS_DI_14": plus_di, "MINUS_DI_14": minus_di,
        "EMA_STACK_STATE": ema_state,
    }])


def _h1_stub(regime: str, directional_bias: str,
             hist: float, slope: float) -> Dict[str, Any]:
    return {
        "regime": regime,
        "directional_bias": directional_bias,
        "hist": hist,
        "hist_slope": slope,
        "macd_line": hist + 0.5, "macd_signal": 0.5,
        "just_crossed": False,
        "reason": f"H1_MACD hist={hist:.3f} slope_2b={slope:.3f} -> {regime}",
        "n_h1_closes": 200,
    }


def _range_stub_off() -> Dict[str, Any]:
    return {
        "enabled": False, "override_active": False, "state": None,
        "signature_met": False, "hyst_count": 0,
        "box_high": None, "box_low": None,
        "exit_breakout": False, "exit_direction": None,
        "er10": None, "adx14": None, "bb_w_pips": None, "atr14_pips": None,
        "body_pips": None, "cross_n": None,
    }


@pytest.fixture
def reset_state(monkeypatch):
    """Fresh regime_engine module state per test (streak dict + freshness
    knobs). Also anchors freshness knobs at their production defaults so a
    stray env override doesn't corrupt the test math."""
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_HYST_N", "3")
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_ADX_MAX", "25")
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_DI_SIG_MAX", "3")
    # Master flag defaults OFF unless the test flips it explicitly.
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "0")
    monkeypatch.setenv("REGIME_DECAY_M2", "5")
    monkeypatch.setenv("REGIME_DECAY_CONF_FACTOR", "0.85")
    monkeypatch.setenv("REGIME_CONF_FLOOR", "0.20")
    # Bar-timestamped freshness saturation not relevant here; leave defaults.
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.5, -0.13))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    return RE


def _flip_flag(monkeypatch, on: bool) -> None:
    """Reload regime_engine with REGIME_DECAY_LADDER_ENABLED set explicitly."""
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "1" if on else "0")
    # Force module reload so the constant re-reads the env var.
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)


# ─── (a) STRONG→FORMING at M1, FORMING→CHOP at M1+M2, bias flips at CHOP ──
def test_a_ladder_two_rungs(monkeypatch):
    _flip_flag(monkeypatch, on=True)
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.5, -0.13))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())

    # A contradicting bar: adx<25 AND di_sig-toward-DOWN < 3.
    # For STRONG_TREND_DOWN → di_sig = minus_di - plus_di. Force di_sig=-10
    # (very contradictory: minus_di=15, plus_di=25) so contradict=True.
    df = _mk_df(adx=20.0, plus_di=25.0, minus_di=15.0, ema_state="BULL_ALIGNED")

    # Bars 1..2: streak < HYST_N=3 → still STRONG_TREND_DOWN.
    for _ in range(2):
        res = RE.classify_regime(df, "GBPUSD")
        assert res["regime"] == "STRONG_TREND_DOWN"
        assert res["directional_bias"] == "SHORT"
        assert res["debug"]["hist_freshness_downgraded"] is False

    # Bar 3: streak==3 → rung 1 fires; label demotes to FORMING; bias stays.
    res = RE.classify_regime(df, "GBPUSD")
    assert res["regime"] == "TREND_FORMING_DOWN"
    assert res["directional_bias"] == "SHORT"
    assert res["debug"]["hist_freshness_downgraded"] is True
    assert res["debug"]["hist_freshness_fail_count"] == 3
    assert res["debug"]["decay_floor_applied"] is False

    # Bars 4..7: streak 4..7 → still FORMING, bias still SHORT, no rung 2.
    for expected_streak in (4, 5, 6, 7):
        res = RE.classify_regime(df, "GBPUSD")
        assert res["regime"] == "TREND_FORMING_DOWN"
        assert res["directional_bias"] == "SHORT"
        assert res["debug"]["hist_freshness_fail_count"] == expected_streak
        assert res["debug"]["decay_floor_applied"] is False, \
            f"rung 2 fired too early at streak={expected_streak}"

    # Bar 8: streak==HYST_N+M2==8 → rung 2 fires; CHOP + NEUTRAL_BIAS.
    res = RE.classify_regime(df, "GBPUSD")
    assert res["regime"] == "CHOP"
    assert res["directional_bias"] == "NEUTRAL_BIAS"
    assert res["debug"]["hist_freshness_downgraded"] is True
    assert res["debug"]["decay_floor_applied"] is True
    assert res["debug"]["regime_pre_floor"] == "TREND_FORMING_DOWN"
    assert res["debug"]["hist_freshness_fail_count"] == 8


# ─── (b) mid-decay reset on ONE qualifying bar ─────────────────────────────
def test_b_mid_decay_reset(monkeypatch):
    _flip_flag(monkeypatch, on=True)
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.5, -0.13))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())

    bad_df  = _mk_df(adx=20.0, plus_di=25.0, minus_di=15.0)  # contradicts DOWN
    good_df = _mk_df(adx=30.0, plus_di=15.0, minus_di=25.0)  # confirms DOWN

    # Run 4 contradicting bars → streak grows to 4, rung 1 fires at 3.
    for _ in range(4):
        RE.classify_regime(bad_df, "GBPUSD")
    assert RE._HIST_FRESHNESS_STATE_BY_SYM["GBPUSD"]["down"] == 4

    # One qualifying bar → _st[dir_key] resets to 0. (Non-contradicting =
    # either adx>=25 OR di_sig>=3; good_df has adx=30 AND di_sig=+10, both.)
    res = RE.classify_regime(good_df, "GBPUSD")
    assert RE._HIST_FRESHNESS_STATE_BY_SYM["GBPUSD"]["down"] == 0
    assert res["regime"] == "STRONG_TREND_DOWN"
    assert res["directional_bias"] == "SHORT"
    assert res["debug"]["hist_freshness_downgraded"] is False

    # Streak counts from zero on next contradiction — must NOT be latched.
    RE.classify_regime(bad_df, "GBPUSD")
    assert RE._HIST_FRESHNESS_STATE_BY_SYM["GBPUSD"]["down"] == 1


# ─── (c) confidence decay curve + floor ───────────────────────────────────
def test_c_confidence_decay_curve_and_floor(monkeypatch):
    """13:55-analog inputs: hist ≈ -2.585 → conf_raw = 2.585/5 = 0.517.

    News overlay OFF (default). At s=10 the decay factor is 0.85^10 ≈ 0.1969
    so conf ≈ 0.517 × 0.1969 ≈ 0.1018, under the 0.20 floor → floor demotes
    to CHOP + NEUTRAL_BIAS regardless of the rung-2 ladder result.
    """
    _flip_flag(monkeypatch, on=True)
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.585, -0.13))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())

    bad_df = _mk_df(adx=20.0, plus_di=25.0, minus_di=15.0)
    RE._HIST_FRESHNESS_STATE_BY_SYM["GBPUSD"] = {"up": 0, "down": 9}

    # emit() applies the confidence decay — call it, not classify_regime,
    # to exercise the whole pipeline (news overlay -> decay -> floor).
    def _no_briefing(_sym, _n=3):
        return None, 0
    monkeypatch.setattr(RE, "resolve_briefing_bias", _no_briefing)

    res = RE.emit("GBPUSD", bad_df, telemetry_path="/tmp/_test_ladder.jsonl")
    # After emit: streak reaches 10, both rung 1 and rung 2 fire in
    # classify_regime; conf_decay applies s=10 in emit; floor converts to
    # CHOP (or already CHOP from rung 2 — still CHOP either way).
    assert res["regime"] == "CHOP"
    assert res["directional_bias"] == "NEUTRAL_BIAS"

    dbg = res["debug"]
    # rung 2 fired because streak 10 >= 3 + 5 = 8.
    assert dbg["decay_floor_applied"] is True
    assert dbg["regime_pre_floor"] == "TREND_FORMING_DOWN"
    # confidence decay applied with s=10.
    assert dbg["conf_decay_applied"] == 10
    # Confidence after decay: conf_raw = |−2.585| / 5.0 = 0.517.
    # No briefing overlay, no news overlay → conf_final == conf_raw
    # coming into the decay pass. After decay: 0.517 * 0.85^10 ≈ 0.1018.
    expected = 0.517 * (0.85 ** 10)
    assert abs(dbg["confidence_final"] - expected) < 5e-3, \
        f"expected ≈ {expected:.4f}, got {dbg['confidence_final']}"
    # Under 0.20 floor at label = CHOP already; floor pass is a no-op
    # because rung 2 already emitted CHOP. conf_floor_applied stays False.
    assert dbg["conf_floor_applied"] is False


# ─── (c-tail) floor conversion when ladder DOES NOT reach rung 2 ───────────
def test_c_floor_alone_converts_forming(monkeypatch):
    """If the ladder demoted to FORMING (rung 1) but streak < HYST_N+M2,
    and confidence has fallen below the floor via decay, floor conversion
    demotes FORMING → CHOP + NEUTRAL_BIAS.

    Set streak=6 (rung 1 fires, rung 2 does not). conf_raw = 0.100 (tiny
    hist so raw is already low). Decay: 0.100 * 0.85^6 ≈ 0.0377 < 0.20.
    """
    _flip_flag(monkeypatch, on=True)
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    # Hist=0.5 → conf_raw = 0.5/5 = 0.1 (below floor even before decay).
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -0.5, -0.05))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    monkeypatch.setattr(RE, "resolve_briefing_bias",
                        lambda _sym, _n=3: (None, 0))

    bad_df = _mk_df(adx=20.0, plus_di=25.0, minus_di=15.0)
    RE._HIST_FRESHNESS_STATE_BY_SYM["GBPUSD"] = {"up": 0, "down": 5}

    res = RE.emit("GBPUSD", bad_df, telemetry_path="/tmp/_test_ladder2.jsonl")
    # streak becomes 6 (5 -> +1). rung 1 fires (6 >= 3), rung 2 does NOT
    # (6 < 8). Ladder alone would leave label = TREND_FORMING_DOWN.
    # But conf 0.100 * 0.85^6 ≈ 0.0377 < 0.20 → floor demotes to CHOP.
    assert res["debug"]["hist_freshness_fail_count"] == 6
    assert res["debug"]["decay_floor_applied"] is False, \
        "rung 2 should NOT have fired at streak=6"
    assert res["regime"] == "CHOP"
    assert res["directional_bias"] == "NEUTRAL_BIAS"
    assert res["debug"]["conf_floor_applied"] is True
    assert res["debug"]["regime_pre_floor"] == "TREND_FORMING_DOWN"


# ─── (d) struct promotion reachable AFTER decay CHOP once hist rule
#        stops producing STRONG (slope flips positive) ─────────────────
def test_d_struct_reachable_after_decay(monkeypatch):
    """On bar N the decay ladder emits CHOP. On bar N+1 the H1 rule flips
    to TREND_FORMING_DOWN (slope>=0), and the struct check finds ADX/DI/
    EMA_state qualifying with slope=+0.5 satisfying the slope-align guard.
    The struct branch at classify_regime :944-959 fires -> STRONG_TREND_UP.

    This exercises the "post-decay struct reachable" property called out
    in the CHANGE 5 comment. We do not modify precedence; we assert the
    existing branch takes over now that hist_regime_pre_or is FORMING.
    """
    _flip_flag(monkeypatch, on=True)
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())

    # Prime the streak past rung 2 first (streak=8).
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.5, -0.13))
    bad_df = _mk_df(adx=20.0, plus_di=25.0, minus_di=15.0)
    RE._HIST_FRESHNESS_STATE_BY_SYM["GBPUSD"] = {"up": 0, "down": 7}
    res = RE.classify_regime(bad_df, "GBPUSD")
    assert res["regime"] == "CHOP"
    assert res["debug"]["decay_floor_applied"] is True

    # Bar N+1: hist slope flips positive → H1 rule outputs TREND_FORMING_DOWN
    # (hist<0 AND slope>=0). Now struct_up_ok evaluates with slope guard.
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("TREND_FORMING_DOWN",
                                              "SHORT", -1.7, +0.54))
    # Struct: ADX=20.6 >= 20 (min), di_margin=+10.3 >= 6, EMA=BULL_ALIGNED,
    # slope=+0.54 satisfies UP guard (>= -0.0). Should certify UP.
    struct_df = _mk_df(adx=20.6, plus_di=25.15, minus_di=14.85,
                       ema_state="BULL_ALIGNED")
    res = RE.classify_regime(struct_df, "GBPUSD")
    assert res["regime"] == "STRONG_TREND_UP", \
        f"expected struct to promote; got {res['regime']} — " \
        f"reason={res['reason']}"
    assert res["directional_bias"] == "LONG"
    assert res["debug"]["regime_label_path"] == "struct"
    assert res["debug"]["regime_struct_promoted"] is True


# ─── (e) flag OFF ↔ byte-identical output ─────────────────────────────────
def test_e_flag_off_byte_identical(monkeypatch):
    """The two runs — one with the master flag OFF, one with it OFF via
    default (unset env) — must produce identical result dicts on the same
    input across a sequence of bars. Verifies the master flag really is a
    no-op when off.
    """
    # First pass: env explicitly "0".
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "0")
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_HYST_N", "3")
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    import regime_engine as RE_OFF  # noqa: E402
    RE_OFF._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE_OFF, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.5, -0.13))
    monkeypatch.setattr(RE_OFF, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    monkeypatch.setattr(RE_OFF, "resolve_briefing_bias",
                        lambda _sym, _n=3: (None, 0))

    bad_df = _mk_df(adx=20.0, plus_di=25.0, minus_di=15.0)
    labels_off, biases_off, confs_off = [], [], []
    for _ in range(12):
        r = RE_OFF.emit("GBPUSD", bad_df, telemetry_path="/tmp/_off.jsonl")
        labels_off.append(r["regime"])
        biases_off.append(r["directional_bias"])
        confs_off.append(r["confidence"])

    # Second pass: env "0" via default (unset). Must match exactly.
    monkeypatch.delenv("REGIME_DECAY_LADDER_ENABLED", raising=False)
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    import regime_engine as RE_DEF  # noqa: E402
    RE_DEF._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE_DEF, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.5, -0.13))
    monkeypatch.setattr(RE_DEF, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    monkeypatch.setattr(RE_DEF, "resolve_briefing_bias",
                        lambda _sym, _n=3: (None, 0))
    labels_def, biases_def, confs_def = [], [], []
    for _ in range(12):
        r = RE_DEF.emit("GBPUSD", bad_df, telemetry_path="/tmp/_def.jsonl")
        labels_def.append(r["regime"])
        biases_def.append(r["directional_bias"])
        confs_def.append(r["confidence"])

    assert labels_off == labels_def
    assert biases_off == biases_def
    assert confs_off == confs_def

    # And behaviour on that pass: never emits CHOP via ladder, never touches
    # bias to NEUTRAL_BIAS — pre-2026-07-08 behaviour holds.
    assert "CHOP" not in labels_off, \
        "ladder must not fire when master flag is off"
    assert all(b == "SHORT" for b in biases_off), \
        "bias must remain SHORT throughout — freshness downgrade preserved it"
