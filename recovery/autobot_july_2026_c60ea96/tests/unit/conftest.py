"""Unit-test env hermeticity for regime_engine.

Root cause background: several unit fixtures (e.g. test_regime_mgmt's
mgmt_on/mgmt_off) import trade_executor / trade_manager, whose module-load
side effects include a load_dotenv() call. load_dotenv writes directly
into os.environ, bypassing pytest's monkeypatch, so REGIME_* keys from
/opt/tradingbot/.env leak into the process and persist across test files.

The specific regression that motivated this file: REGIME_NEWS_AWARE_ENABLED=1
in .env → once leaked, regime_engine.emit() dampens confidence by
_NEWS_CONFIDENCE_FACTORS[news_state] before the decay pass, invalidating
test_regime_decay_ladder::test_c's math (expected 0.517 * 0.85**10 ≈ 0.1018,
got 0.517 * 0.70 * 0.85**10 ≈ 0.0712).

This autouse fixture pins the regime_engine env inputs to known values
via monkeypatch (which reverts at test end), so every unit test sees a
deterministic env regardless of what upstream imports have leaked in.
"""
from __future__ import annotations

import pytest


# regime_engine reads these at module load. Any test that reload()s
# regime_engine (or transitively imports something that does) must see
# consistent values, so pin them here for every unit test. Values chosen
# to match the module-level defaults in regime_engine.py.
_REGIME_ENGINE_ENV_DEFAULTS = {
    "REGIME_NEWS_AWARE_ENABLED": "0",
    "MOD_NEWS_DAY_DAMPEN": "0.70",
    "MOD_NEWS_PRE_DAMPEN": "0.85",
    "REGIME_DECAY_LADDER_ENABLED": "0",
    "REGIME_DECAY_M2": "5",
    "REGIME_DECAY_CONF_FACTOR": "0.85",
    "REGIME_CONF_FLOOR": "0.20",
    "REGIME_HIST_FRESHNESS_ENABLED": "1",
    "REGIME_HIST_FRESHNESS_HYST_N": "3",
    "REGIME_HIST_FRESHNESS_ADX_MAX": "25",
    "REGIME_HIST_FRESHNESS_DI_SIG_MAX": "3",
    "REGIME_STRUCT_TREND_ENABLED": "1",
    "REGIME_STRUCT_ADX_MIN": "20",
    "REGIME_STRUCT_DI_MARGIN": "6",
    "REGIME_STRUCT_HIST_DECLAMP_ENABLED": "1",
    "REGIME_STRUCT_SLOPE_ALIGN_ENABLED": "1",
    "REGIME_STRUCT_SLOPE_ALIGN_TOL": "0.0",
}


@pytest.fixture(autouse=True)
def _pin_regime_engine_env(monkeypatch):
    """Pin regime_engine env inputs so tests are hermetic against any
    .env values leaked via upstream load_dotenv() calls. Individual
    tests are free to override with their own monkeypatch.setenv."""
    for k, v in _REGIME_ENGINE_ENV_DEFAULTS.items():
        monkeypatch.setenv(k, v)
    yield
