"""Pin the CONVICTION_ADX_MIN env-configurability contract for the
2026-07-24 BB_BOUNCE restore (option A).

Case 1: CONVICTION_ADX_MIN=0 → ADX 15.4 passes.
Case 2: env unset → default 20.0 → ADX 19.4 blocks.
Case 3: regime.ADX is None → fail-open PASS with ADX_unavailable_fail_open.

The gate's None fail-open, velocity blocker, RSI blocker, and sub-gate
ordering are not modified — case 3 asserts fail-open behaviour is pinned
exactly as it was, so any future change to that branch surfaces here."""
from __future__ import annotations

import importlib
import sys
import types


def _reload_conviction_gate():
    if "conviction_gate" in sys.modules:
        return importlib.reload(sys.modules["conviction_gate"])
    return importlib.import_module("conviction_gate")


def _install_fake_regime(monkeypatch, adx_value):
    fake_re = types.SimpleNamespace(
        latest_result=lambda symbol: {
            "ADX": adx_value,
            "plus_di": 25.0,
            "minus_di": 12.0,
            "confidence_final": 0.4,
            "EMA_state": "BEAR_ALIGNED",
            "winning_regime": "TREND_FORMING_DOWN",
            "directional_bias": "SHORT",
        }
    )
    monkeypatch.setitem(sys.modules, "regime_engine", fake_re)


def test_env_zero_makes_adx_15p4_pass(monkeypatch):
    monkeypatch.setenv("CONVICTION_ADX_MIN", "0")
    _install_fake_regime(monkeypatch, adx_value=15.4)
    cg = _reload_conviction_gate()
    ok, reason, details = cg.evaluate("GBPUSD", "BUY", "GBPUSD_BB_BOUNCE_L")
    adx_det = details["ADX"]
    assert adx_det["passed"] is True
    assert adx_det["threshold"] == 0.0
    assert adx_det["adx"] == 15.4
    assert adx_det["reason"] == "ADX_pass"


def test_env_unset_defaults_to_20p0_and_blocks_19p4(monkeypatch):
    monkeypatch.delenv("CONVICTION_ADX_MIN", raising=False)
    _install_fake_regime(monkeypatch, adx_value=19.4)
    cg = _reload_conviction_gate()
    ok, reason, details = cg.evaluate("GBPUSD", "BUY", "GBPUSD_BB_BOUNCE_L")
    adx_det = details["ADX"]
    assert adx_det["passed"] is False
    assert adx_det["threshold"] == 20.0
    assert adx_det["adx"] == 19.4
    assert "ADX_below_threshold" in adx_det["reason"]


def test_adx_none_fail_open_unchanged(monkeypatch):
    """Pins the fail-open branch verbatim. If a future change alters
    conviction_gate.py:227-228 this test will break — intentional."""
    monkeypatch.setenv("CONVICTION_ADX_MIN", "0")
    _install_fake_regime(monkeypatch, adx_value=None)
    cg = _reload_conviction_gate()
    ok, reason, details = cg.evaluate("GBPUSD", "SELL", "GBPUSD_BB_BOUNCE_S")
    adx_det = details["ADX"]
    assert adx_det["passed"] is True
    assert adx_det["adx"] is None
    assert adx_det["reason"] == "ADX_unavailable_fail_open"
