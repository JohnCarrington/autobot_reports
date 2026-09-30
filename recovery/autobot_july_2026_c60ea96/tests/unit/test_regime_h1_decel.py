"""H1 deceleration streak — coverage for the 2026-07-09 asymmetric-response
build. Same stubbing pattern as tests/unit/test_regime_decay_ladder.py:

  - _classify_macd_h1        — monkeypatched per-bar to inject hist/slope
  - _run_range_detector      — monkeypatched to a no-op (no range override)
  - _HIST_FRESHNESS_STATE_BY_SYM + _DECEL_STATE_BY_SYM reset per case

Cases:
  (a) H1 read dedupe — 12 identical (hist, slope) emits between two H1
      closes advance the streak by AT MOST 1 (new distinct pair). 0
      pre-first-distinct-pair is fine.
  (b1) Re-acceleration resets — |slope| holds or grows.
  (b2) Sign flip resets — hist/slope direction flips vs prior read.
  (c) Contradict-on-decel-alone — ADX healthy (>=25) AND di_sig healthy
      (>=3) BUT h1_decel_streak >= REGIME_DECEL_STREAK_MIN → freshness
      streak advances.
  (d) Full ladder STRONG→FORMING→CHOP driven PURELY by decel-fed streak
      hitting rung 1 at M1=3 and rung 2 at M1+M2=8 (defaults).
  (e) SUPERSEDED 2026-07-09 — the decel disjunct no longer flips
      permits(BB_BOUNCE_*) in a trend regime; BB_BOUNCE is table-permitted
      unconditionally in every trend regime. The replacement case asserts
      the field remains as telemetry only (exhausted / exhaust_decel_streak
      still land on state and the jsonl row).
  (f) Promotion paths byte-identical — dwell promotion + fast-lane are
      unaffected by any decel wiring.
  (g) Snap-back guard — raw re-promotes for one bar mid-decay; the
      matrix EFFECTIVE label must NOT change (dwell absorbs the flicker).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


# ─── Helpers ───────────────────────────────────────────────────────────────
def _mk_df(adx: float = 30.0, plus_di: float = 30.0, minus_di: float = 10.0,
           ema_state: str = "BULL_ALIGNED") -> pd.DataFrame:
    return pd.DataFrame([{
        "timestamp": pd.Timestamp("2026-07-09T08:05:00Z"),
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


def _load_engine(monkeypatch, *,
                 decay_ladder: bool = False,
                 decel_min: int = 2,
                 hyst_n: int = 3,
                 decay_m2: int = 5):
    """Fresh regime_engine module bound to the requested env; decel/freshness
    state cleared. Returns the module."""
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "1" if decay_ladder else "0")
    monkeypatch.setenv("REGIME_DECAY_M2", str(decay_m2))
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_HYST_N", str(hyst_n))
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_ADX_MAX", "25")
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_DI_SIG_MAX", "3")
    monkeypatch.setenv("REGIME_DECEL_STREAK_MIN", str(decel_min))
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    RE._DECEL_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    monkeypatch.setattr(RE, "resolve_briefing_bias",
                        lambda _sym, _n=3: (None, 0))
    return RE


def _drive(RE, symbol: str, df, h1_pairs: List[tuple]) -> List[Dict[str, Any]]:
    """Emit one classify_regime per (hist, slope) pair. Returns the list of
    result dicts."""
    out: List[Dict[str, Any]] = []
    for hist, slope in h1_pairs:
        # Choose a trend label consistent with hist sign; slope may or may
        # not match sign (that is the tested condition).
        if hist > 0 and slope > 0:
            reg, bias = "STRONG_TREND_UP", "LONG"
        elif hist > 0 and slope <= 0:
            reg, bias = "TREND_FORMING_UP", "LONG"
        elif hist < 0 and slope < 0:
            reg, bias = "STRONG_TREND_DOWN", "SHORT"
        elif hist < 0 and slope >= 0:
            reg, bias = "TREND_FORMING_DOWN", "SHORT"
        else:
            reg, bias = "CHOP", "NEUTRAL_BIAS"
        RE._classify_macd_h1_stub = _h1_stub(reg, bias, hist, slope)
        # bind fresh
        stub = _h1_stub(reg, bias, hist, slope)
        RE_stub = stub  # noqa
        RE._patched_h1 = stub  # noqa
        RE_module_setattr = getattr(RE, "_classify_macd_h1")  # noqa
        # Replace _classify_macd_h1 per-call.
        def _closure(_sym, _stub=stub):
            return _stub
        RE._classify_macd_h1 = _closure  # type: ignore[assignment]
        out.append(RE.classify_regime(df, symbol))
    return out


# ─── (a) H1 read dedupe — identical pair does not advance ─────────────────
def test_a_h1_read_dedupe(monkeypatch):
    RE = _load_engine(monkeypatch)
    df = _mk_df(adx=30.0, plus_di=30.0, minus_di=10.0)
    # 12 identical emits with (hist=+2.0, slope=+0.30). First updates prior,
    # subsequent 11 dedupe. Streak must remain 0 (no prior for first;
    # dedupe for the rest).
    for _ in range(12):
        RE._classify_macd_h1 = lambda _s: _h1_stub(  # type: ignore[assignment]
            "STRONG_TREND_UP", "LONG", 2.0, 0.30)
        res = RE.classify_regime(df, "GBPUSD")
        assert res["debug"]["h1_decel_streak"] == 0
    # One distinct pair with decel — streak must advance to exactly 1.
    RE._classify_macd_h1 = lambda _s: _h1_stub(  # type: ignore[assignment]
        "STRONG_TREND_UP", "LONG", 1.7, 0.20)
    res = RE.classify_regime(df, "GBPUSD")
    assert res["debug"]["h1_decel_streak"] == 1


# ─── (b1) Reset on re-acceleration ────────────────────────────────────────
def test_b1_reset_on_re_acceleration(monkeypatch):
    RE = _load_engine(monkeypatch)
    df = _mk_df(adx=30.0, plus_di=30.0, minus_di=10.0)
    seq = [
        (2.0, 0.50),   # first read — streak 0
        (1.8, 0.30),   # decel — streak 1
        (1.6, 0.15),   # decel — streak 2
        (1.5, 0.40),   # RE-ACCEL — streak 0
        (1.4, 0.20),   # decel — streak 1
    ]
    expected = [0, 1, 2, 0, 1]
    for (h, s), want in zip(seq, expected):
        RE._classify_macd_h1 = lambda _s, _h=h, _sl=s: _h1_stub(  # type: ignore[assignment]
            "STRONG_TREND_UP", "LONG", _h, _sl)
        res = RE.classify_regime(df, "GBPUSD")
        assert res["debug"]["h1_decel_streak"] == want, \
            f"h={h} slope={s} expected streak={want} got {res['debug']['h1_decel_streak']}"


# ─── (b2) Reset on sign flip ──────────────────────────────────────────────
def test_b2_reset_on_sign_flip(monkeypatch):
    RE = _load_engine(monkeypatch)
    df = _mk_df(adx=30.0, plus_di=30.0, minus_di=10.0)
    seq = [
        (2.0, 0.50),    # UP prior — streak 0
        (1.7, 0.30),    # decel while UP — streak 1
        (-1.2, -0.40),  # SIGN FLIP → DOWN — streak 0
        (-1.0, -0.20),  # decel while DOWN — streak 1
        (-0.8, -0.10),  # decel while DOWN — streak 2
        (0.4, +0.30),   # SIGN FLIP → UP — streak 0
    ]
    expected = [0, 1, 0, 1, 2, 0]
    for (h, s), want in zip(seq, expected):
        RE._classify_macd_h1 = lambda _s, _h=h, _sl=s: _h1_stub(  # type: ignore[assignment]
            "STRONG_TREND_UP" if h > 0 else "STRONG_TREND_DOWN",
            "LONG" if h > 0 else "SHORT", _h, _sl)
        res = RE.classify_regime(df, "GBPUSD")
        assert res["debug"]["h1_decel_streak"] == want, \
            f"h={h} slope={s} expected {want} got {res['debug']['h1_decel_streak']}"


def test_b3_slope_zero_or_mixed_signs_resets(monkeypatch):
    RE = _load_engine(monkeypatch)
    df = _mk_df(adx=30.0, plus_di=30.0, minus_di=10.0)
    seq = [
        (2.0, 0.50),    # UP intact — streak 0
        (1.8, 0.30),    # decel — streak 1
        (1.6, 0.0),     # slope 0 → trend not intact — streak 0
        (1.4, 0.30),    # first read after reset — streak 0
        (1.2, 0.15),    # decel — streak 1
        (1.0, -0.10),   # slope flips negative w/ hist +ve — streak 0
    ]
    expected = [0, 1, 0, 0, 1, 0]
    for (h, s), want in zip(seq, expected):
        RE._classify_macd_h1 = lambda _s, _h=h, _sl=s: _h1_stub(  # type: ignore[assignment]
            "STRONG_TREND_UP" if s > 0 else "TREND_FORMING_UP",
            "LONG", _h, _sl)
        res = RE.classify_regime(df, "GBPUSD")
        assert res["debug"]["h1_decel_streak"] == want, \
            f"h={h} slope={s} expected {want} got {res['debug']['h1_decel_streak']}"


# ─── (c) Contradict on decel alone with ADX healthy ───────────────────────
def test_c_contradict_on_decel_alone_adx_healthy(monkeypatch):
    """ADX=30 (>=25) AND di_sig=+20 (>=3) — ADX/DI contradict term FALSE.
    Yet a decel streak of >=2 must still advance the freshness fail_count.
    """
    RE = _load_engine(monkeypatch, decel_min=2)
    # Healthy 5m — ADX high, di_sig strongly toward UP.
    healthy_df = _mk_df(adx=30.0, plus_di=30.0, minus_di=10.0)
    # First read primes prior — streak 0 (no advance).
    RE._classify_macd_h1 = lambda _s: _h1_stub(  # type: ignore[assignment]
        "STRONG_TREND_UP", "LONG", 2.0, 0.50)
    RE.classify_regime(healthy_df, "GBPUSD")
    # Second read decels — streak 1. Below DECEL_MIN=2 so still not
    # contradicting. Freshness fail_count remains 0.
    RE._classify_macd_h1 = lambda _s: _h1_stub(  # type: ignore[assignment]
        "STRONG_TREND_UP", "LONG", 1.8, 0.30)
    res = RE.classify_regime(healthy_df, "GBPUSD")
    assert res["debug"]["h1_decel_streak"] == 1
    assert res["debug"]["hist_freshness_fail_count"] == 0
    # Third read decels — streak 2 == DECEL_MIN. Contradict fires on decel
    # alone. fail_count advances even though ADX/DI is HEALTHY.
    RE._classify_macd_h1 = lambda _s: _h1_stub(  # type: ignore[assignment]
        "STRONG_TREND_UP", "LONG", 1.6, 0.15)
    res = RE.classify_regime(healthy_df, "GBPUSD")
    assert res["debug"]["h1_decel_streak"] == 2
    assert res["debug"]["hist_freshness_fail_count"] == 1, \
        "decel alone should have advanced freshness streak"


# ─── (d) Full ladder driven purely by decel-fed streak ────────────────────
def test_d_full_ladder_decel_only(monkeypatch):
    """Feed 8 consecutive decel-only bars — ADX/DI kept healthy the whole
    time — and expect rung 1 to fire at bar 3 (HYST_N=3) and rung 2 to fire
    at bar 8 (HYST_N + M2 = 3 + 5).
    """
    RE = _load_engine(monkeypatch, decay_ladder=True, decel_min=2)
    # Healthy 5m — ADX/DI cannot contradict.
    healthy_df = _mk_df(adx=30.0, plus_di=30.0, minus_di=10.0)
    # Prime prior with a first read.
    RE._classify_macd_h1 = lambda _s: _h1_stub(  # type: ignore[assignment]
        "STRONG_TREND_UP", "LONG", 3.0, 0.90)
    r0 = RE.classify_regime(healthy_df, "GBPUSD")
    assert r0["regime"] == "STRONG_TREND_UP"
    assert r0["debug"]["h1_decel_streak"] == 0

    # Second read: decel — streak 1. Below DECEL_MIN → no contradict.
    RE._classify_macd_h1 = lambda _s: _h1_stub(  # type: ignore[assignment]
        "STRONG_TREND_UP", "LONG", 2.9, 0.60)
    r1 = RE.classify_regime(healthy_df, "GBPUSD")
    assert r1["debug"]["h1_decel_streak"] == 1
    assert r1["debug"]["hist_freshness_fail_count"] == 0
    assert r1["regime"] == "STRONG_TREND_UP"

    # From here on every read decels — streak grows 2,3,4,... At streak 2
    # the contradict fires; freshness fail_count advances 1,2,3,...
    # Rung 1 (STRONG→FORMING) at fail_count==3, rung 2 (FORMING→CHOP) at 8.
    labels: List[str] = []
    biases: List[str] = []
    fresh: List[int] = []
    prior_slope = 0.60
    for i in range(9):
        slope = prior_slope - 0.02  # always decel
        hist  = max(2.8 - 0.02 * i, 0.5)
        RE._classify_macd_h1 = lambda _s, _h=hist, _sl=slope: _h1_stub(  # type: ignore[assignment]
            "STRONG_TREND_UP", "LONG", _h, _sl)
        r = RE.classify_regime(healthy_df, "GBPUSD")
        labels.append(r["regime"])
        biases.append(r["directional_bias"])
        fresh.append(r["debug"]["hist_freshness_fail_count"])
        prior_slope = slope

    # Read-by-read expectations. Contradict advances fail_count from
    # streak >= 2 onward (i=0 → streak becomes 2, contradict, fail=1;
    # i=1 → streak=3, fail=2; ... i=2 → fail=3 → rung 1 fires → FORMING).
    assert fresh == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    # Rung 1 fires at fail_count==3 (i==2). Bars i=0,1 still STRONG.
    assert labels[0] == "STRONG_TREND_UP"
    assert labels[1] == "STRONG_TREND_UP"
    for i in range(2, 7):  # fail_count 3..7 → FORMING
        assert labels[i] == "TREND_FORMING_UP", \
            f"i={i} fail={fresh[i]} label={labels[i]} — rung 1 expected"
    # Rung 2 fires at fail_count==HYST_N+M2==8 (i==7). Bias flips to NEUTRAL.
    assert labels[7] == "CHOP", f"rung 2 expected at i=7, got {labels[7]}"
    assert biases[7] == "NEUTRAL_BIAS"
    assert labels[8] == "CHOP"
    assert biases[8] == "NEUTRAL_BIAS"


# ─── (e) Matrix exhaustion telemetry surfaces but does NOT gate ───────────
#
# SUPERSEDES the original 4ee95a9 case
# `test_e_matrix_exhaustion_opens_on_decel`, which asserted the decel
# disjunct flipped permits(BB_BOUNCE_*) True in a trend regime as an
# escape hatch. The 2026-07-09 operator amendment removed that entire
# escape hatch: BB_BOUNCE is now unconditionally permitted in every
# trend regime AND RANGE_ROTATION. The h1_decel_streak field still
# lands on state and telemetry — that's what this replacement asserts.
def test_e_matrix_exhaustion_decel_field_is_telemetry_only(monkeypatch):
    """h1_decel_streak reaches the exhaustion floor (2 by default) —
    exhausted=True, exhaust_decel_streak is cached — but the permitted
    set does not change relative to a healthy bar in the same regime.
    Also asserts the field lands on the jsonl row.
    """
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_EXHAUSTED_FADE_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_EXHAUST_STREAK_MIN", "1")
    monkeypatch.setenv("REGIME_MATRIX_EXHAUST_DECEL_MIN", "2")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", "/tmp/test_decel_matrix.jsonl")
    # Fresh log so we can read this test's rows in isolation.
    try:
        import os as _os
        _os.remove("/tmp/test_decel_matrix.jsonl")
    except FileNotFoundError:
        pass
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix as M
    M._reset_state_for_tests()
    for _ in range(3):
        M.update("GBPUSD", "STRONG_TREND_UP")
    assert M.effective_regime("GBPUSD") == "STRONG_TREND_UP"

    # Baseline: healthy bar. BB_BOUNCE is table-permitted (no longer a
    # function of exhaustion) — record the permitted set.
    M.update("GBPUSD", "STRONG_TREND_UP",
             hist_freshness_fail_count=0, h1_decel_streak=0)
    healthy_permits = {
        m_: M.permits("GBPUSD", m_)
        for m_ in ("GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
                   "GBPUSD_EMA_PULLBACK_L", "GBPUSD_TREND_V3_L")
    }
    assert healthy_permits["GBPUSD_BB_BOUNCE_L"] is True
    assert healthy_permits["GBPUSD_BB_BOUNCE_S"] is True
    # decel=1 (below DECEL_MIN) — still permitted (table).
    M.update("GBPUSD", "STRONG_TREND_UP",
             hist_freshness_fail_count=0, h1_decel_streak=1)
    permits_decel1 = {
        m_: M.permits("GBPUSD", m_) for m_ in healthy_permits
    }
    assert permits_decel1 == healthy_permits
    # decel=2 — exhausted flag now True, exhaust_decel_streak cached at 2
    # — permitted set MUST NOT change relative to healthy.
    M.update("GBPUSD", "STRONG_TREND_UP",
             hist_freshness_fail_count=0, h1_decel_streak=2)
    st = M._state["GBPUSD"]
    assert st["exhausted"] is True
    assert st["exhaust_decel_streak"] == 2
    permits_decel2 = {
        m_: M.permits("GBPUSD", m_) for m_ in healthy_permits
    }
    assert permits_decel2 == healthy_permits, (
        "decel disjunct must be TELEMETRY only — permitted set changed "
        f"from {healthy_permits} to {permits_decel2}"
    )
    # And the field lands on the jsonl row.
    import json as _json
    with open("/tmp/test_decel_matrix.jsonl") as fh:
        rows = [_json.loads(l) for l in fh if l.strip()]
    assert rows, "no telemetry rows written"
    last = rows[-1]
    assert last.get("exhausted") is True
    assert last.get("exhaust_decel_streak") == 2


# ─── (f) Promotion paths byte-identical — decel wiring is additive ────────
def test_f_dwell_promotion_unaffected_by_decel(monkeypatch):
    """Feeding a large decel streak into update() must not accelerate or
    interfere with the dwell counter — promotion still requires N
    consecutive bars.
    """
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", "/tmp/test_decel_promo.jsonl")
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix as M
    M._reset_state_for_tests()
    # RANGE_ROTATION → STRONG_TREND_UP dwell path. Pump decel_streak=99
    # every bar — it must not touch the dwell counter.
    for _ in range(3):
        M.update("GBPUSD", "RANGE_ROTATION", h1_decel_streak=99)
    assert M.effective_regime("GBPUSD") == "RANGE_ROTATION"
    # Two candidate bars for STRONG_TREND_UP — not enough for promotion.
    for _ in range(2):
        M.update("GBPUSD", "STRONG_TREND_UP", h1_decel_streak=99)
    assert M.effective_regime("GBPUSD") == "RANGE_ROTATION", \
        "decel input must not shortcut dwell promotion"
    # Third bar completes N=3.
    M.update("GBPUSD", "STRONG_TREND_UP", h1_decel_streak=99)
    assert M.effective_regime("GBPUSD") == "STRONG_TREND_UP"


def test_f_fast_lane_unaffected_by_decel(monkeypatch):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", "/tmp/test_decel_fast.jsonl")
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix as M
    M._reset_state_for_tests()
    for _ in range(3):
        M.update("GBPUSD", "RANGE_ROTATION", h1_decel_streak=99)
    # Fast lane must still fire regardless of decel input.
    M.update("GBPUSD", "STRONG_TREND_UP",
             range_break_promoted=True, range_exit_breakout=True,
             regime_label_path="range_break_promote",
             h1_decel_streak=99)
    assert M.effective_regime("GBPUSD") == "STRONG_TREND_UP"


# ─── (g) Snap-back guard — mid-decay raw re-promote absorbed by dwell ─────
def test_g_snapback_guard_dwell_absorbs_raw_repromote(monkeypatch):
    """During decay the raw stream flips STRONG_TREND_UP → TREND_FORMING_UP
    (via freshness rung 1). On some bar the raw briefly re-emits
    STRONG_TREND_UP (a snap-back). Dwell counter must absorb the single-bar
    flicker — effective label must NOT flip back to STRONG_TREND_UP.
    """
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", "/tmp/test_decel_snap.jsonl")
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix as M
    M._reset_state_for_tests()
    # Prime STRONG_TREND_UP as effective.
    for _ in range(3):
        M.update("GBPUSD", "STRONG_TREND_UP")
    assert M.effective_regime("GBPUSD") == "STRONG_TREND_UP"
    # Freshness downgrades to TREND_FORMING_UP — dwell 3 bars to promote.
    for _ in range(3):
        M.update("GBPUSD", "TREND_FORMING_UP", hist_freshness_fail_count=3)
    assert M.effective_regime("GBPUSD") == "TREND_FORMING_UP"
    # Now: mid-decay snap-back. Raw briefly re-emits STRONG_TREND_UP for a
    # single bar (say the H1 slope re-accelerated once).
    M.update("GBPUSD", "STRONG_TREND_UP", hist_freshness_fail_count=0)
    # Effective must NOT change — dwell has only counted 1 STRONG bar.
    assert M.effective_regime("GBPUSD") == "TREND_FORMING_UP"
    # Raw resumes FORMING — dwell resets on the STRONG candidate.
    M.update("GBPUSD", "TREND_FORMING_UP", hist_freshness_fail_count=4)
    assert M.effective_regime("GBPUSD") == "TREND_FORMING_UP"
