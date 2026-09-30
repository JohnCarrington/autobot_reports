"""bb_pierce_recorder.py: verify the h1_stack_* keys read from
indicators.h1_ema_direction match its actual return schema.

Regression: the recorder previously read _h1.get("strength"), a key
h1_ema_direction never emits (it emits "separation_strength" — see
indicators.py:1630). Every recorded h1_stack_strength was null as a
result (0/328 fires populated across 07-17..07-24).
"""
from __future__ import annotations

import importlib
import sys
import types


def _reload_recorder():
    if "bb_pierce_recorder" in sys.modules:
        return importlib.reload(sys.modules["bb_pierce_recorder"])
    return importlib.import_module("bb_pierce_recorder")


def test_h1_stack_strength_reads_separation_strength(monkeypatch):
    recorder = _reload_recorder()

    fake_indicators = types.SimpleNamespace(
        h1_ema_direction=lambda symbol, pip_size=1.0: {
            "direction": "BEARISH",
            "separation_strength": 0.42,
            "separation_pips": 6.3,
        }
    )
    monkeypatch.setitem(sys.modules, "indicators", fake_indicators)

    out = recorder._enrich_at_pierce(
        df_5m=None,
        ts_utc=None,
        side="UPPER",
        virtual_direction="SELL",
        entry_price_at_pierce_close=13500.0,
        is_backfill=False,  # h1 block only runs on live path
    )
    assert out["h1_stack_direction"] == "BEARISH"
    assert out["h1_stack_strength"] == 0.42


def test_h1_stack_strength_missing_key_is_null_not_raise(monkeypatch):
    recorder = _reload_recorder()

    fake_indicators = types.SimpleNamespace(
        h1_ema_direction=lambda symbol, pip_size=1.0: {
            "direction": "FLAT",
        }
    )
    monkeypatch.setitem(sys.modules, "indicators", fake_indicators)

    out = recorder._enrich_at_pierce(
        df_5m=None,
        ts_utc=None,
        side="LOWER",
        virtual_direction="BUY",
        entry_price_at_pierce_close=13500.0,
        is_backfill=False,  # h1 block only runs on live path
    )
    assert out["h1_stack_direction"] == "FLAT"
    assert out["h1_stack_strength"] is None
