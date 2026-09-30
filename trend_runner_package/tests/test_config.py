from __future__ import annotations

import os

import pytest

from trend_runner.config import load_config


def test_default_execution_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("TREND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IG_ACCOUNT_TYPE", "DEMO")
    monkeypatch.delenv("TREND_EXECUTION_ENABLED", raising=False)
    cfg = load_config()
    assert cfg.execution_enabled is False


def test_live_account_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("TREND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IG_ACCOUNT_TYPE", "LIVE")
    with pytest.raises(RuntimeError, match="only DEMO is permitted"):
        load_config()


def test_bool_and_float_coercion(monkeypatch, tmp_path):
    monkeypatch.setenv("TREND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IG_ACCOUNT_TYPE", "DEMO")
    monkeypatch.setenv("TREND_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("TREND_STAKE_GBP_PER_PIP", "3.5")
    cfg = load_config()
    assert cfg.execution_enabled is True
    assert cfg.stake_gbp_per_pip == 3.5
