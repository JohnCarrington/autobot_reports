"""
Contract tests for candle_builder.py AFTER the 2026-04-23 migration to
native IG 5m subscription.

What the module is now:
  - A closed-bar buffer + indicator enrichment cache.
  - Source of bars is `native_5m_source._emit_native_close`, NOT tick
    aggregation.

What the module exposes:
  - Public façade: get_df, get_df_raw, get_candles, seed_from_df,
    preload_from_df, build_candles, set_epic_mapping, set_symbol_epic,
    register_5m_close_callback, unregister_5m_close_callback,
    set_on_5m_close_callback, get_builder, _emit_close_payload,
    _5M_CLOSE_CALLBACKS, _BUILDER, CandleBuilder5M, TIMEFRAME.
  - Stubs that import cleanly but raise on call: update_candles,
    update_tick, update_from_tick.

What it no longer has:
  - `update` / `_active` / `_send_heartbeat` / `_last_heartbeat_minute`
    / `_check_force_close` / `_finalize_closed_candle`: tick-ingest
    machinery, deleted.
  - `_REST_RECONCILE_ENABLED` and related REST allowance machinery,
    deleted — proven unfixable via streaming.
"""
from __future__ import annotations

import logging
import pandas as pd
import pytest

import candle_builder


# ---------------------------------------------------------------------------
# Module-level surface
# ---------------------------------------------------------------------------

def test_candle_builder_imports_successful():
    assert candle_builder is not None


def test_timeframe_constant_is_5m():
    assert candle_builder.TIMEFRAME == "5m"


def test_public_facade_present():
    """Every name callers rely on. Anything added to this list is a
    breaking API change that needs a migration for downstream callers
    (sentinel, autobot, morning_briefing, candle_archive, streamer_api)."""
    expected = {
        "CandleBuilder5M",
        "TIMEFRAME",
        "register_5m_close_callback",
        "unregister_5m_close_callback",
        "set_on_5m_close_callback",
        "get_df",
        "get_df_raw",
        "get_candles",
        "seed_from_df",
        "preload_from_df",
        "build_candles",
        "set_epic_mapping",
        "set_symbol_epic",
        "get_builder",
        "_emit_close_payload",
        "_5M_CLOSE_CALLBACKS",
        "_BUILDER",
        "update_candles",
        "update_tick",
        "update_from_tick",
    }
    actual = set(dir(candle_builder))
    missing = expected - actual
    assert not missing, f"candle_builder public surface missing: {sorted(missing)}"


def test_candle_builder_logger_exists():
    assert hasattr(candle_builder, "logger")
    assert isinstance(candle_builder.logger, logging.Logger)
    assert candle_builder.logger.name == "AutoBot"


# ---------------------------------------------------------------------------
# CandleBuilder5M instance surface
# ---------------------------------------------------------------------------

def test_builder_constructor_shapes():
    assert hasattr(candle_builder, "CandleBuilder5M")
    b1 = candle_builder.CandleBuilder5M()
    b2 = candle_builder.CandleBuilder5M(max_candles=100, send_alerts=False, debug_mode=True)
    assert b1.max_candles >= 20
    assert b2.max_candles == 100


def test_builder_has_store_attributes():
    b = candle_builder.CandleBuilder5M()
    assert hasattr(b, "max_candles")
    assert hasattr(b, "candles") and isinstance(b.candles, dict)
    assert hasattr(b, "_df_raw") and isinstance(b._df_raw, dict)
    assert hasattr(b, "_df_ind") and isinstance(b._df_ind, dict)
    assert hasattr(b, "_symbol_to_epic") and isinstance(b._symbol_to_epic, dict)


def test_builder_tick_ingest_attributes_are_gone():
    """Tick-aggregation internals were deleted in the migration. These
    attributes must NOT reappear — if they do, some test or stale code
    is trying to reintroduce tick ingest."""
    b = candle_builder.CandleBuilder5M()
    assert not hasattr(b, "_active"), (
        "_active is tick-aggregation state; should have been removed"
    )
    assert not hasattr(b, "_latest_closed_bucket"), (
        "_latest_closed_bucket is tick-aggregation state; should have been removed"
    )
    assert not hasattr(b, "_last_heartbeat_minute"), (
        "_last_heartbeat_minute belonged to the tick-ingest heartbeat; deleted"
    )
    assert not hasattr(b, "update"), (
        "CandleBuilder5M.update() was the tick-ingest entry; deleted. "
        "Bars now arrive via native_5m_source._emit_native_close."
    )
    assert not hasattr(b, "_send_heartbeat")
    assert not hasattr(b, "_check_force_close")
    assert not hasattr(b, "_finalize_closed_candle")


def test_builder_read_api_contract():
    b = candle_builder.CandleBuilder5M()
    # Empty state: get_df returns an empty DataFrame with the OHLC schema
    df = b.get_df("GBPUSD")
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert set(df.columns) >= {"time", "open", "high", "low", "close"}

    # seed_from_df returns int count of rows loaded
    n = b.seed_from_df("GBPUSD", pd.DataFrame(columns=["time", "open", "high", "low", "close"]))
    assert n == 0


def test_builder_seed_and_epic_mapping():
    b = candle_builder.CandleBuilder5M()
    b.set_epic_mapping("GBPUSD", "CS.D.GBPUSD.TODAY.IP")
    assert b._symbol_to_epic["GBPUSD"] == "CS.D.GBPUSD.TODAY.IP"
    # set_symbol_epic is an alias
    b.set_symbol_epic("EURUSD", "CS.D.EURUSD.TODAY.IP")
    assert b._symbol_to_epic["EURUSD"] == "CS.D.EURUSD.TODAY.IP"


# ---------------------------------------------------------------------------
# REST-RECONCILE surface — explicit assertion that it is gone
# ---------------------------------------------------------------------------

def test_rest_reconcile_machinery_removed():
    """The REST-RECONCILE code path was deleted as part of the migration
    (proven unfixable via streaming per the 2026-04-23 native-vs-tick
    comparison). Every REST-RECONCILE name must be absent from the module."""
    removed_names = [
        "_REST_RECONCILE_ENABLED",
        "_REST_RECONCILE_LOCK",
        "_REST_RECONCILE_WARN_PIPS",
        "_REST_RECONCILE_CADENCE",
        "_REST_RECONCILE_POINTS_PER_CALL",
        "_REST_RECONCILE_CLOSE_COUNTS",
        "_reconcile_high_low_with_rest",
        "_read_rest_block",
        "_write_rest_block",
        "_rest_blocked_now",
        "_is_allowance_error",
        "_pip_size_for",
        "_send_forced_close_telegram",
        "_parse_ls_update_time",
        "_FALLBACK_TS_SYMBOLS",
        "FORCE_CLOSE_GRACE_SECS",
    ]
    present = [n for n in removed_names if hasattr(candle_builder, n)]
    assert not present, (
        f"candle_builder still exposes removed REST-RECONCILE / force-close names: {present}"
    )


# ---------------------------------------------------------------------------
# Stub behaviour for back-compat imports
# ---------------------------------------------------------------------------

def test_tick_ingest_stubs_raise_not_implemented():
    """sentinel.py:46 imports update_candles/update_tick/update_from_tick.
    The import must succeed (dormant code, verified in prod). Calling
    them must raise with a pointed message."""
    from candle_builder import update_candles, update_tick, update_from_tick  # noqa: F401
    for stub in (
        candle_builder.update_candles,
        candle_builder.update_tick,
        candle_builder.update_from_tick,
    ):
        with pytest.raises(NotImplementedError) as exc_info:
            stub("SYM", 1.0, 1.0)
        msg = str(exc_info.value)
        assert "native_5m_source.py" in msg
        assert "migrate/native-5m-candle-feed" in msg


# ---------------------------------------------------------------------------
# Callback registry
# ---------------------------------------------------------------------------

def test_callback_registry_is_list():
    assert isinstance(candle_builder._5M_CLOSE_CALLBACKS, list)


def test_register_and_unregister_callback_round_trip():
    captured = []

    def cb(payload):
        captured.append(payload)

    assert cb not in candle_builder._5M_CLOSE_CALLBACKS
    candle_builder.register_5m_close_callback(cb)
    assert cb in candle_builder._5M_CLOSE_CALLBACKS
    # Idempotent registration
    candle_builder.register_5m_close_callback(cb)
    assert candle_builder._5M_CLOSE_CALLBACKS.count(cb) == 1

    candle_builder.unregister_5m_close_callback(cb)
    assert cb not in candle_builder._5M_CLOSE_CALLBACKS
