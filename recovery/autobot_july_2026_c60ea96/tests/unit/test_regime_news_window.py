"""Release-window scoping for the BIG_NEWS_DAY confidence dampener.

Prior to 2026-07-10 the dampener applied to every bar on a BIG_NEWS_DAY,
which suppressed an entire session of struct-certified STRONG_TREND signals
outside the actual release windows. This suite pins the new behaviour:

    (a) Inside pre-window (0..NEWS_DAMP_PRE_MIN before HIGH release)  → damped.
    (b) Inside post-window (0..NEWS_DAMP_POST_MIN after HIGH release) → damped.
    (c) BIG_NEWS_DAY outside any window                                → factor 1.0.
    (d) Non-BIG_NEWS_DAY (NORMAL/PRE/POST/UNKNOWN)                    → byte-identical to prior behaviour.
    (e) Regression for 2026-07-10 08:30 GBPUSD: struct-agreed 0.22 outside
        a release window survives the 0.20 floor (label stays DOWN, not CHOP).

The news_state module is stubbed via monkeypatch on the imported reference
inside regime_engine.emit — same stubbing pattern the decay-ladder suite uses.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _mk_df(adx: float, plus_di: float, minus_di: float,
           ema_state: str = "BEAR_ALIGNED") -> pd.DataFrame:
    return pd.DataFrame([{
        "timestamp": pd.Timestamp("2026-07-10T08:30:00Z"),
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


def _snapshot(state: str,
              min_to_next_high: Optional[int] = None,
              min_since_last_high: Optional[int] = None) -> Dict[str, Any]:
    """Build a news_state snapshot dict with the fields regime_engine reads."""
    return {
        "news_state": state,
        "minutes_to_next_high_release": min_to_next_high,
        "minutes_since_last_high_release": min_since_last_high,
        "next_high_release_ts": None,
        "last_high_release_ts": None,
        "news_impact_today": "HIGH" if state == "BIG_NEWS_DAY" else "NONE",
        "next_release_ts": None,
        "minutes_to_next_release": None,
        "in_pre_release_window": False,
        "news_currencies_today": [],
        "news_state_source": "test",
    }


@pytest.fixture
def RE(monkeypatch, tmp_path):
    """Fresh regime_engine per test with the news-aware flag ON and
    controlled window envs so PRE_MIN/POST_MIN math is deterministic."""
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    monkeypatch.setenv("REGIME_NEWS_AWARE_ENABLED", "1")
    monkeypatch.setenv("NEWS_DAMP_PRE_MIN", "60")
    monkeypatch.setenv("NEWS_DAMP_POST_MIN", "90")
    monkeypatch.setenv("MOD_NEWS_DAY_DAMPEN", "0.70")
    # Freshness knobs pinned so the streak block doesn't interfere.
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_HYST_N", "3")
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "1")
    monkeypatch.setenv("REGIME_CONF_FLOOR", "0.20")
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    # Deterministic classify + range stubs.
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_UP",
                                              "LONG", 1.5, 0.10))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    # Silence briefing lookup — bias overlay tested elsewhere.
    monkeypatch.setattr(RE, "resolve_briefing_bias",
                        lambda _sym, n_days=3: (None, 0))
    # Route jsonl writes to a tmp path so tests don't leak state.
    return RE, tmp_path / "regime_engine.jsonl"


def _stub_news(monkeypatch, snap: Dict[str, Any]) -> None:
    """Install a fake news_state module returning `snap`."""
    fake = types.SimpleNamespace(news_state_snapshot=lambda: snap)
    monkeypatch.setitem(sys.modules, "news_state", fake)


# ─── (a) inside pre-window → damped ───────────────────────────────────────
def test_a_pre_window_dampens(RE, monkeypatch):
    engine, tel = RE
    _stub_news(monkeypatch, _snapshot("BIG_NEWS_DAY", min_to_next_high=30))
    df = _mk_df(adx=25.0, plus_di=25.0, minus_di=10.0, ema_state="BULL_ALIGNED")
    res = engine.emit("GBPUSD", df, telemetry_path=str(tel))
    dbg = res["debug"]
    # Prior to the fix this would have damped regardless. Here we assert the
    # window classification IS active (pre-window) → dampener DID apply.
    assert dbg["news_damp_window_active"] is True
    # 0.30 raw * 0.70 = 0.21 (raw = |1.5|/5.0). No agree/conflict weight —
    # briefing stubbed None. So confidence should be conf_raw * 0.70.
    assert dbg["confidence_final"] == pytest.approx(
        dbg["confidence_raw"] * 0.70, abs=1e-4)


# ─── (b) inside post-window → damped ──────────────────────────────────────
def test_b_post_window_dampens(RE, monkeypatch):
    engine, tel = RE
    _stub_news(monkeypatch, _snapshot("BIG_NEWS_DAY", min_since_last_high=45))
    df = _mk_df(adx=25.0, plus_di=25.0, minus_di=10.0, ema_state="BULL_ALIGNED")
    res = engine.emit("GBPUSD", df, telemetry_path=str(tel))
    dbg = res["debug"]
    assert dbg["news_damp_window_active"] is True
    assert dbg["confidence_final"] == pytest.approx(
        dbg["confidence_raw"] * 0.70, abs=1e-4)


# ─── (c) BIG_NEWS_DAY outside any window → undamped ──────────────────────
def test_c_outside_window_undamped(RE, monkeypatch):
    engine, tel = RE
    # HIGH release fires 180min in the future — well past PRE_MIN=60.
    _stub_news(monkeypatch, _snapshot(
        "BIG_NEWS_DAY", min_to_next_high=180, min_since_last_high=None))
    df = _mk_df(adx=25.0, plus_di=25.0, minus_di=10.0, ema_state="BULL_ALIGNED")
    res = engine.emit("GBPUSD", df, telemetry_path=str(tel))
    dbg = res["debug"]
    assert dbg["news_damp_window_active"] is False
    # Factor 1.0 → conf_final == conf_raw (no briefing overlay, no decay).
    assert dbg["confidence_final"] == pytest.approx(
        dbg["confidence_raw"], abs=1e-4)


# ─── (d) non-BIG_NEWS_DAY paths byte-identical ────────────────────────────
def test_d_normal_day_untouched(RE, monkeypatch):
    engine, tel = RE
    _stub_news(monkeypatch, _snapshot("NORMAL"))
    df = _mk_df(adx=25.0, plus_di=25.0, minus_di=10.0, ema_state="BULL_ALIGNED")
    res = engine.emit("GBPUSD", df, telemetry_path=str(tel))
    dbg = res["debug"]
    # NORMAL was never damped before and isn't now.
    assert dbg["news_damp_window_active"] is False
    assert dbg["confidence_final"] == pytest.approx(
        dbg["confidence_raw"], abs=1e-4)


def test_d_pre_and_post_big_news_untouched(RE, monkeypatch):
    """PRE_BIG_NEWS (0.85) and POST_BIG_NEWS (1.0) are NOT windowed."""
    engine, tel = RE
    _stub_news(monkeypatch, _snapshot("PRE_BIG_NEWS", min_to_next_high=180))
    df = _mk_df(adx=25.0, plus_di=25.0, minus_di=10.0, ema_state="BULL_ALIGNED")
    res = engine.emit("GBPUSD", df, telemetry_path=str(tel))
    dbg = res["debug"]
    assert dbg["news_damp_window_active"] is False
    # PRE_BIG_NEWS factor 0.85 applied unconditionally.
    assert dbg["confidence_final"] == pytest.approx(
        dbg["confidence_raw"] * 0.85, abs=1e-4)


# ─── (e) 08:30 regression: struct-agreed 0.22 survives floor outside window
def test_e_08_30_regression_struct_down_survives_floor(RE, monkeypatch):
    """The 2026-07-10 08:30 GBPUSD bar: struct-promoted STRONG_TREND_DOWN,
    briefing BEARISH agrees. Before the fix: 0.19 → briefing_agree ×1.15 →
    0.22 → BIG_NEWS_DAY dampener ×0.70 → 0.156 → floor → CHOP.
    After the fix: no release within [-60, +90] → factor 1.0 → conf_final
    stays 0.22, above the 0.20 floor, label stays STRONG_TREND_DOWN."""
    engine, tel = RE
    # Reload with a hist stub matching the 08:30 raw hist (TREND_FORMING_UP,
    # hist=+0.969, slope=-0.250) so struct promotion is the interesting path.
    engine._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(engine, "_classify_macd_h1",
                        lambda _sym: _h1_stub("TREND_FORMING_UP",
                                              "LONG", 0.969, -0.250))
    monkeypatch.setattr(engine, "resolve_briefing_bias",
                        lambda _sym, n_days=3: ("BEARISH", 0))
    _stub_news(monkeypatch, _snapshot(
        "BIG_NEWS_DAY", min_to_next_high=None, min_since_last_high=None))
    # 5m features matching the 08:30 row: adx=21.2, plus_di=12.79,
    # minus_di=29.40, ema=BEAR_ALIGNED → struct DOWN certifies.
    df = _mk_df(adx=21.2, plus_di=12.79, minus_di=29.40,
                ema_state="BEAR_ALIGNED")
    res = engine.emit("GBPUSD", df, telemetry_path=str(tel))
    dbg = res["debug"]
    assert dbg["news_damp_window_active"] is False
    assert res["regime"] == "STRONG_TREND_DOWN", (
        f"expected STRONG_TREND_DOWN, got {res['regime']} — floor was "
        f"conf_final={dbg.get('confidence_final')}")
    assert res["directional_bias"] == "SHORT"
    # conf_raw = 0.969/5.0 = 0.1938; briefing agrees → * 1.15 = 0.2229;
    # dampener skipped → conf_final ≈ 0.223, above 0.20 floor.
    assert dbg["confidence_final"] > 0.20
