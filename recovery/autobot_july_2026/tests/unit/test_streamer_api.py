import pytest
import streamer_api
import json
import pandas as pd

@pytest.fixture
def client():
    with streamer_api.app.test_client() as client:
        yield client

def test_status_endpoint(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    assert "uptime" in resp.json

def test_get_sessions_live(client, monkeypatch):
    monkeypatch.setattr(streamer_api, "HAS_IG", True)
    monkeypatch.setattr(streamer_api, "get_ig_session", lambda: ("ig", {"CST": "X"}, "A1"))
    class FakeResp: status_code = 200; text = '{"accountId": "A1"}'
    monkeypatch.setattr(streamer_api.requests, "get", lambda url, headers=None: FakeResp())
    resp = client.get("/sessions")
    assert resp.status_code == 200
    assert "accountId" in resp.json

def test_get_sessions_demo_when_no_ig(monkeypatch, client):
    monkeypatch.setattr(streamer_api, "HAS_IG", False)
    resp = client.get("/sessions")
    assert resp.status_code == 200
    assert resp.json["accountId"] == "DEMO123"

def test_positions_endpoint(monkeypatch, client):
    monkeypatch.setattr(streamer_api, "HAS_IG", False)
    resp = client.get("/positions")
    assert resp.status_code == 200
    assert isinstance(resp.json, list)

def test_read_json_reads(monkeypatch, tmp_path):
    f = tmp_path / "test.json"
    f.write_text(json.dumps({"foo": 1}))
    out = streamer_api.read_json(f, default={})
    assert out == {"foo": 1}

def test_read_json_returns_default(monkeypatch, tmp_path):
    f = tmp_path / "missing.json"
    out = streamer_api.read_json(f, default={"fallback": True})
    assert out == {"fallback": True}

def test_epic_candles_path_returns_correct(tmp_path):
    p = streamer_api.epic_candles_path("CS.D.EURUSD.CFD.IP")
    assert p.name.endswith("CS.D.EURUSD.CFD.IP.csv")

def test_load_epic_map(monkeypatch, tmp_path):
    f = tmp_path / "epics.json"
    f.write_text(json.dumps({"EURUSD": "CS.D.EURUSD.CFD.IP"}))
    monkeypatch.setattr(streamer_api, "EPIC_MAP_JSON", f)
    out = streamer_api.load_epic_map()
    assert out["EURUSD"].endswith("CS.D.EURUSD.CFD.IP")

def test_symbol_to_epic(monkeypatch):
    monkeypatch.setattr(streamer_api, "load_epic_map", lambda: {"EURUSD": "CS.D.EURUSD.CFD.IP"})
    epic = streamer_api.symbol_to_epic("EURUSD")
    assert epic.endswith("CS.D.EURUSD.CFD.IP")

def test_get_candles_returns_latest(monkeypatch, tmp_path, client):
    csv = tmp_path / "CS.D.EURUSD.CFD.IP.csv"
    df = pd.DataFrame({
        "timestamp": ["2023-01-01T00:00:00Z", "2023-01-01T00:05:00Z"],
        "close": [1.1, 1.2]
    })
    df.to_csv(csv, index=False)
    monkeypatch.setattr(streamer_api, "epic_candles_path", lambda epic: csv)
    resp = client.get("/candles/EURUSD")
    assert resp.status_code == 200
    assert len(resp.json) == 2
    assert resp.json[-1]["close"] == 1.2

def test_compute_bollinger_adds_columns():
    df = pd.DataFrame({"close": [1.0 + i for i in range(20)]})
    out = streamer_api.compute_bollinger(df, window=5, mult=2)
    assert "bb_upper" in out.columns
    assert "bb_lower" in out.columns
    assert pd.notna(out["bb_upper"].iloc[-1])
    assert pd.notna(out["bb_lower"].iloc[-1])

def test_trades_log_reads_csv(monkeypatch, tmp_path, client):
    csv = tmp_path / "log.csv"
    df = pd.DataFrame({"symbol": ["EURUSD"], "pnl": [12.5]})
    df.to_csv(csv, index=False)
    monkeypatch.setattr(streamer_api, "TRADE_LOG_CSV", csv)
    resp = client.get("/trades")
    assert resp.status_code == 200
    assert resp.json[0]["symbol"] == "EURUSD"

def test_get_signals(monkeypatch, tmp_path, client):
    f = tmp_path / "signals.json"
    f.write_text(json.dumps({"EURUSD": {"signal": "BUY"}}))
    monkeypatch.setattr(streamer_api, "SIGNALS_JSON", f)
    resp = client.get("/signals/EURUSD")
    assert resp.status_code == 200
    assert resp.json["signal"] == "BUY"
