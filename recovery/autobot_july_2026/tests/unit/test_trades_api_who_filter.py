"""Unit tests for the /trades who-filter (Part 2 of the dashboard upgrade).

Contract under test:
- No params  → bare flat list (byte-equivalent legacy shape).
- ?who=mine  → payload with trades whose source == "bot".
- ?who=other → payload with trades whose source == "ig_only", UNLESS
               the underlying source is signal_log_fallback in which
               case the trades list is empty and who_disabled includes
               "other" so the frontend can grey out the pill.
- ?who=all   → payload with the full list.
- ?who=garbage → normalised to "all".
- Payload always carries source + who + who_disabled when params present.
"""
from __future__ import annotations

import json

import pytest

import trades_api


SAMPLE = [
    {"timestamp": "2026-06-12T08:00:00Z", "pair": "GBPUSD", "direction": "BUY",
     "source": "bot",     "strategy": "GBPUSD_BB_BOUNCE_L"},
    {"timestamp": "2026-06-12T09:00:00Z", "pair": "GBPUSD", "direction": "SELL",
     "source": "ig_only", "strategy": ""},
    {"timestamp": "2026-06-12T10:00:00Z", "pair": "EURUSD", "direction": "BUY",
     "source": "bot",     "strategy": "GBPUSD_EMA_PULLBACK_L"},
]


@pytest.fixture
def client(monkeypatch):
    """Flask test client with a synthetic trades cache."""
    monkeypatch.setattr(trades_api, "_get_trades_with_source",
                        lambda: (list(SAMPLE), "spine"))
    trades_api.app.config["TESTING"] = True
    with trades_api.app.test_client() as c:
        yield c


# ──────────────────────────────────────────────────────────────────────
# No-param: byte-equivalent legacy shape (list, not object)
# ──────────────────────────────────────────────────────────────────────
def test_no_params_returns_bare_list(client):
    r = client.get("/trades")
    assert r.status_code == 200
    body = json.loads(r.data)
    assert isinstance(body, list), (
        "No query params must return a bare list — the legacy shape "
        "the dashboard ships today."
    )
    assert len(body) == 3
    assert body == SAMPLE


# ──────────────────────────────────────────────────────────────────────
# who=all
# ──────────────────────────────────────────────────────────────────────
def test_who_all_returns_full_list_in_payload(client):
    r = client.get("/trades?who=all")
    assert r.status_code == 200
    body = json.loads(r.data)
    assert isinstance(body, dict)
    assert body["who"] == "all"
    assert body["source"] == "spine"
    assert body["who_disabled"] == []
    assert len(body["trades"]) == 3


# ──────────────────────────────────────────────────────────────────────
# who=mine
# ──────────────────────────────────────────────────────────────────────
def test_who_mine_filters_to_bot_source(client):
    r = client.get("/trades?who=mine")
    body = json.loads(r.data)
    assert body["who"] == "mine"
    assert all(t["source"] == "bot" for t in body["trades"])
    assert len(body["trades"]) == 2


# ──────────────────────────────────────────────────────────────────────
# who=other
# ──────────────────────────────────────────────────────────────────────
def test_who_other_filters_to_ig_only(client):
    r = client.get("/trades?who=other")
    body = json.loads(r.data)
    assert body["who"] == "other"
    assert body["source"] == "spine"
    assert body["who_disabled"] == []
    assert len(body["trades"]) == 1
    assert body["trades"][0]["source"] == "ig_only"


# ──────────────────────────────────────────────────────────────────────
# who=other under fallback source: empty + disabled flag
# ──────────────────────────────────────────────────────────────────────
def test_who_other_under_fallback_returns_empty_and_marks_disabled(monkeypatch):
    monkeypatch.setattr(trades_api, "_get_trades_with_source",
                        lambda: (list(SAMPLE), "signal_log_fallback"))
    trades_api.app.config["TESTING"] = True
    with trades_api.app.test_client() as c:
        r = c.get("/trades?who=other")
    body = json.loads(r.data)
    assert body["source"] == "signal_log_fallback"
    assert body["who"] == "other"
    assert "other" in body["who_disabled"], (
        "When source is signal_log_fallback, OTHER must be flagged "
        "disabled so the dashboard can grey out the pill."
    )
    assert body["trades"] == [], (
        "OTHER on a fallback source must return an empty list — never "
        "the silently-wrong full set."
    )


# ──────────────────────────────────────────────────────────────────────
# who=mine under fallback: still works (signal_log = this host's fires)
# ──────────────────────────────────────────────────────────────────────
def test_who_mine_under_fallback_still_returns_bot_trades(monkeypatch):
    monkeypatch.setattr(trades_api, "_get_trades_with_source",
                        lambda: (list(SAMPLE), "signal_log_fallback"))
    trades_api.app.config["TESTING"] = True
    with trades_api.app.test_client() as c:
        r = c.get("/trades?who=mine")
    body = json.loads(r.data)
    assert body["source"] == "signal_log_fallback"
    assert "other" in body["who_disabled"]
    # mine itself remains usable.
    assert all(t["source"] == "bot" for t in body["trades"])
    assert len(body["trades"]) == 2


# ──────────────────────────────────────────────────────────────────────
# Unknown who values normalise to "all"
# ──────────────────────────────────────────────────────────────────────
def test_unknown_who_normalises_to_all(client):
    r = client.get("/trades?who=bogus")
    body = json.loads(r.data)
    assert body["who"] == "all"
    assert len(body["trades"]) == 3


# ──────────────────────────────────────────────────────────────────────
# Empty who string normalises to "all"
# ──────────────────────────────────────────────────────────────────────
def test_empty_who_normalises_to_all_and_still_emits_payload(client):
    # ?who= (empty string) — recognised param but garbage value.
    r = client.get("/trades?who=")
    body = json.loads(r.data)
    assert isinstance(body, dict), (
        "Empty who= is STILL a recognised param — must return payload "
        "shape so the frontend gets source/who back."
    )
    assert body["who"] == "all"
