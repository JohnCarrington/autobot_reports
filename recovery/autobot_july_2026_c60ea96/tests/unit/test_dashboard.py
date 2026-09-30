"""
Unit tests for dashboard.py

Production API:
- load_json(path) — loads JSON from a Path object
- load_candles(name) — loads CSV from cache directory
- No api_get(), today_only(), color_text()
- Imports psutil and streamlit
"""
import json
import pytest
import pandas as pd
from unittest.mock import MagicMock


# Dashboard imports streamlit which calls st.set_page_config at import time.
# We need to mock streamlit before importing dashboard.
@pytest.fixture
def dashboard_module(monkeypatch, tmp_path):
    """Import dashboard with streamlit and psutil mocked."""
    import sys

    # Create mock streamlit module
    mock_st = MagicMock()
    mock_st.set_page_config = MagicMock()
    mock_st.title = MagicMock()
    mock_st.caption = MagicMock()
    mock_st.sidebar = MagicMock()
    mock_st.sidebar.header = MagicMock()
    mock_st.sidebar.slider = MagicMock(return_value=2)
    mock_st.sidebar.info = MagicMock()
    mock_st.header = MagicMock()
    def _mock_columns(n):
        return [MagicMock() for _ in range(n)]
    mock_st.columns = _mock_columns
    mock_st.warning = MagicMock()
    mock_st.info = MagicMock()
    mock_st.write = MagicMock()
    mock_st.json = MagicMock()
    mock_st.metric = MagicMock()
    mock_st.subheader = MagicMock()
    mock_st.line_chart = MagicMock()
    mock_st.code = MagicMock()
    mock_st.bar_chart = MagicMock()
    mock_st.pyplot = MagicMock()
    mock_st.rerun = MagicMock()

    # Mock seaborn and matplotlib too
    mock_sns = MagicMock()
    mock_plt = MagicMock()
    mock_mcolors = MagicMock()

    # Store originals
    orig_st = sys.modules.get("streamlit")
    orig_sns = sys.modules.get("seaborn")
    orig_plt = sys.modules.get("matplotlib.pyplot")
    orig_mcolors = sys.modules.get("matplotlib.colors")
    orig_matplotlib = sys.modules.get("matplotlib")

    # Mock psutil too (not installed in test venv)
    mock_psutil = MagicMock()
    mock_psutil.cpu_percent = MagicMock(return_value=10.0)
    mock_psutil.virtual_memory = MagicMock(return_value=MagicMock(percent=50.0))
    orig_psutil = sys.modules.get("psutil")

    sys.modules["psutil"] = mock_psutil
    sys.modules["streamlit"] = mock_st
    sys.modules["seaborn"] = mock_sns
    sys.modules["matplotlib"] = MagicMock()
    sys.modules["matplotlib.pyplot"] = mock_plt
    sys.modules["matplotlib.colors"] = mock_mcolors

    # Also mock time.sleep to avoid waiting
    monkeypatch.setattr("time.sleep", lambda x: None)

    # Mock Path.exists and open to prevent actual file reads during import

    # We need to suppress the dashboard import-time side effects
    # The dashboard reads files and calls streamlit at module level
    # Let's just import the module and extract the functions we need

    try:
        if "dashboard" in sys.modules:
            del sys.modules["dashboard"]
        import dashboard
        yield dashboard
    finally:
        # Restore
        if orig_st is not None:
            sys.modules["streamlit"] = orig_st
        elif "streamlit" in sys.modules:
            del sys.modules["streamlit"]
        if orig_sns is not None:
            sys.modules["seaborn"] = orig_sns
        if orig_plt is not None:
            sys.modules["matplotlib.pyplot"] = orig_plt
        if orig_mcolors is not None:
            sys.modules["matplotlib.colors"] = orig_mcolors
        if orig_matplotlib is not None:
            sys.modules["matplotlib"] = orig_matplotlib
        if orig_psutil is not None:
            sys.modules["psutil"] = orig_psutil
        elif "psutil" in sys.modules:
            del sys.modules["psutil"]
        sys.modules.pop("dashboard", None)


def test_load_json_existing_file(dashboard_module, tmp_path):
    """load_json returns parsed JSON for an existing file."""
    data = {"key": "value", "num": 42}
    fp = tmp_path / "test.json"
    fp.write_text(json.dumps(data))
    result = dashboard_module.load_json(fp)
    assert result == data


def test_load_json_missing_file(dashboard_module, tmp_path):
    """load_json returns None for a non-existent file."""
    fp = tmp_path / "nonexistent.json"
    result = dashboard_module.load_json(fp)
    assert result is None


def test_load_json_invalid_json(dashboard_module, tmp_path):
    """load_json returns None for invalid JSON."""
    fp = tmp_path / "bad.json"
    fp.write_text("not valid json {{{")
    result = dashboard_module.load_json(fp)
    assert result is None


def test_load_candles_existing_csv(dashboard_module, tmp_path, monkeypatch):
    """load_candles loads a CSV file from the cache directory."""
    # Create a test CSV
    df = pd.DataFrame({
        "timestamp": ["2025-01-01 12:00", "2025-01-01 12:05"],
        "open": [1.0, 1.1],
        "high": [1.05, 1.15],
        "low": [0.95, 1.05],
        "close": [1.02, 1.12],
    })
    csv_path = tmp_path / "test.csv"
    df.to_csv(csv_path, index=False)

    # Monkeypatch CACHE to tmp_path
    monkeypatch.setattr(dashboard_module, "CACHE", tmp_path)
    result = dashboard_module.load_candles("test.csv")
    assert result is not None
    assert len(result) == 2


def test_load_candles_missing_file(dashboard_module, tmp_path, monkeypatch):
    """load_candles returns None for a non-existent file."""
    monkeypatch.setattr(dashboard_module, "CACHE", tmp_path)
    result = dashboard_module.load_candles("nonexistent.csv")
    assert result is None


def test_no_api_get(dashboard_module):
    """dashboard has NO api_get function."""
    assert not hasattr(dashboard_module, "api_get")


def test_no_today_only(dashboard_module):
    """dashboard has NO today_only function."""
    assert not hasattr(dashboard_module, "today_only")


def test_no_color_text(dashboard_module):
    """dashboard has NO color_text function."""
    assert not hasattr(dashboard_module, "color_text")
