"""[CONVICTION-ADX] observation log — must emit on every evaluate()
regardless of whether the gate PASSes or BLOCKs, with all six fields
populated. Behaviour unchanged (this is instrumentation only)."""
from __future__ import annotations

import importlib
import logging
import sys
import types


def _reload_conviction_gate():
    if "conviction_gate" in sys.modules:
        return importlib.reload(sys.modules["conviction_gate"])
    return importlib.import_module("conviction_gate")


def _install_fake_regime(monkeypatch, adx_value):
    """Point conviction_gate at a stubbed regime_engine.latest_result
    that yields a known regime dict — bypasses live cache warmup."""
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


def _capture_conviction_lines(caplog, level=logging.INFO):
    """Grab the [CONVICTION-ADX] lines emitted during the caplog window."""
    return [
        r for r in caplog.records
        if "[CONVICTION-ADX]" in r.getMessage()
    ]


def test_adx_pass_emits_log_line(monkeypatch, caplog):
    # Pin the threshold — .env may set CONVICTION_ADX_MIN via load_dotenv
    # before pytest is imported (see tests/unit/conftest.py note on
    # load_dotenv-leaks-into-os.environ). Hermetic tests must set it.
    monkeypatch.setenv("CONVICTION_ADX_MIN", "20")
    _install_fake_regime(monkeypatch, adx_value=25.7)
    cg = _reload_conviction_gate()
    with caplog.at_level(logging.INFO, logger=cg.logger.name):
        ok, reason, details = cg.evaluate("GBPUSD", "BUY", "GBPUSD_BB_BOUNCE_L")
    # Behaviour unchanged: 25.7 > 20 → PASS.
    assert details["ADX"]["passed"] is True
    lines = _capture_conviction_lines(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    assert "pair=GBPUSD" in msg
    assert "strategy=GBPUSD_BB_BOUNCE_L" in msg
    assert "adx=25.70" in msg
    assert "floor=20.00" in msg
    assert "verdict=PASS" in msg
    assert "source=regime_engine.latest_result.ADX" in msg


def test_adx_block_emits_log_line(monkeypatch, caplog):
    monkeypatch.setenv("CONVICTION_ADX_MIN", "20")
    _install_fake_regime(monkeypatch, adx_value=19.37)
    cg = _reload_conviction_gate()
    with caplog.at_level(logging.INFO, logger=cg.logger.name):
        ok, reason, details = cg.evaluate("GBPUSD", "BUY", "GBPUSD_BB_BOUNCE_L")
    # Behaviour unchanged: 19.37 < 20 → BLOCK.
    assert details["ADX"]["passed"] is False
    lines = _capture_conviction_lines(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    assert "pair=GBPUSD" in msg
    assert "strategy=GBPUSD_BB_BOUNCE_L" in msg
    assert "adx=19.37" in msg
    assert "floor=20.00" in msg
    assert "verdict=BLOCK" in msg
    assert "source=regime_engine.latest_result.ADX" in msg


def test_adx_none_still_emits_line(monkeypatch, caplog):
    """When regime.get('ADX') is None the gate fail-opens. The log line
    must still fire with adx=None so we can see the fail-open path."""
    monkeypatch.setenv("CONVICTION_ADX_MIN", "20")
    _install_fake_regime(monkeypatch, adx_value=None)
    cg = _reload_conviction_gate()
    with caplog.at_level(logging.INFO, logger=cg.logger.name):
        cg.evaluate("GBPUSD", "SELL", "GBPUSD_BB_BOUNCE_S")
    lines = _capture_conviction_lines(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    assert "adx=None" in msg
    # verdict=PASS because fail_open, per _gate_adx return.
    assert "verdict=PASS" in msg
