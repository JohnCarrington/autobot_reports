import inspect
import streamer_api
from flask import Flask

def test_streamer_api_imports_and_app():
    assert hasattr(streamer_api, "app")
    assert isinstance(streamer_api.app, Flask)

def test_streamer_api_paths_and_flags_present():
    assert hasattr(streamer_api, "DATA_DIR")
    assert hasattr(streamer_api, "TRADE_LOG_CSV")
    assert hasattr(streamer_api, "SIGNALS_JSON")
    assert hasattr(streamer_api, "STATUS_JSON")
    assert hasattr(streamer_api, "EPIC_MAP_JSON")

def test_streamer_api_helpers_exist_with_signatures():
    assert hasattr(streamer_api, "read_json") and callable(streamer_api.read_json)
    assert hasattr(streamer_api, "epic_candles_path") and callable(streamer_api.epic_candles_path)
    assert hasattr(streamer_api, "load_epic_map") and callable(streamer_api.load_epic_map)
    assert hasattr(streamer_api, "symbol_to_epic") and callable(streamer_api.symbol_to_epic)
    assert hasattr(streamer_api, "compute_bollinger") and callable(streamer_api.compute_bollinger)

    assert len(inspect.signature(streamer_api.read_json).parameters) == 2
    assert len(inspect.signature(streamer_api.epic_candles_path).parameters) == 1
    assert len(inspect.signature(streamer_api.symbol_to_epic).parameters) == 1
    sig = inspect.signature(streamer_api.compute_bollinger)
    assert "df" in sig.parameters
    assert "window" in sig.parameters
    assert "mult" in sig.parameters

def test_streamer_api_endpoints_exist_with_signatures():
    assert hasattr(streamer_api, "status") and callable(streamer_api.status)
    assert hasattr(streamer_api, "get_sessions") and callable(streamer_api.get_sessions)
    assert hasattr(streamer_api, "positions") and callable(streamer_api.positions)
    assert hasattr(streamer_api, "get_candles") and callable(streamer_api.get_candles)
    assert hasattr(streamer_api, "trades_log") and callable(streamer_api.trades_log)
    assert hasattr(streamer_api, "get_signals") and callable(streamer_api.get_signals)

    assert len(inspect.signature(streamer_api.status).parameters) == 0
    assert len(inspect.signature(streamer_api.get_sessions).parameters) == 0
    assert len(inspect.signature(streamer_api.positions).parameters) == 0
    assert len(inspect.signature(streamer_api.get_candles).parameters) == 1
    assert len(inspect.signature(streamer_api.get_signals).parameters) == 1
