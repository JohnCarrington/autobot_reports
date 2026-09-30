"""Unit tests for the LIVE/DEMO env toggle (Part 3 of the dashboard
upgrade).

The toggle is kill-switched. With DASHBOARD_ENV_TOGGLE_ENABLED=0
(default), `?env=` is silently ignored and the response shape stays
byte-equivalent to the pre-toggle behaviour. With the kill-switch ON,
`?env=live|demo` routes through a per-env session manager + per-env
cache; `?env=live` without IG_LIVE_* creds returns source="unconfigured"
with an empty trades list rather than throwing.
"""
from __future__ import annotations

import json

import pytest

import trades_api


# ──────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────
def test_env_normalisation():
    assert trades_api._normalize_env("live") == "live"
    assert trades_api._normalize_env("DEMO") == "demo"
    assert trades_api._normalize_env("garbage") == trades_api.DEFAULT_DASHBOARD_ENV
    assert trades_api._normalize_env(None) == trades_api.DEFAULT_DASHBOARD_ENV


def test_env_creds_missing_returns_none(monkeypatch):
    for k in ("IG_LIVE_USERNAME", "IG_LIVE_PASSWORD", "IG_LIVE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert trades_api._env_creds("live") is None


def test_env_creds_present_returns_dict(monkeypatch):
    monkeypatch.setenv("IG_LIVE_USERNAME", "u")
    monkeypatch.setenv("IG_LIVE_PASSWORD", "p")
    monkeypatch.setenv("IG_LIVE_API_KEY", "k")
    creds = trades_api._env_creds("live")
    assert creds is not None
    assert creds["username"] == "u"
    assert creds["password"] == "p"
    assert creds["api_key"]  == "k"


def test_signal_log_env_filter_treats_unstamped_as_demo():
    rows = [
        {"strategy": "A", "env": "live"},
        {"strategy": "B", "env": "demo"},
        {"strategy": "C"},                # no env stamp
        {"strategy": "D", "env": "DEMO"}, # case-insensitive
    ]
    demo_rows = trades_api._filter_signal_log_rows_by_env(rows, "demo")
    live_rows = trades_api._filter_signal_log_rows_by_env(rows, "live")
    assert {r["strategy"] for r in demo_rows} == {"B", "C", "D"}, (
        "unstamped row must be treated as demo"
    )
    assert {r["strategy"] for r in live_rows} == {"A"}


# ──────────────────────────────────────────────────────────────────────
# Route: kill-switch OFF (default) ignores ?env=
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def stub_data(monkeypatch):
    """Replace data accessors with deterministic stubs so the route
    layer can be tested in isolation from IG / disk state."""
    monkeypatch.setattr(
        trades_api, "_get_trades_with_source",
        lambda: ([{"source": "bot", "x": 1}], "spine"),
    )
    monkeypatch.setattr(
        trades_api, "_get_trades_with_source_env",
        lambda env: (
            ([{"source": "bot", "x": 1, "env": env}], "spine")
            if env == "demo" else ([], "unconfigured")
        ),
    )
    trades_api.app.config["TESTING"] = True


def test_toggle_off_ignores_env_param(stub_data, monkeypatch):
    """With toggle off, ?env=live must be silently dropped — response
    matches the legacy bare list (no params) shape."""
    monkeypatch.setattr(trades_api, "DASHBOARD_ENV_TOGGLE_ENABLED", False)
    with trades_api.app.test_client() as c:
        r = c.get("/trades?env=live")
    body = json.loads(r.data)
    assert isinstance(body, list)
    assert body == [{"source": "bot", "x": 1}]


def test_toggle_off_byte_equivalent_no_params(stub_data, monkeypatch):
    monkeypatch.setattr(trades_api, "DASHBOARD_ENV_TOGGLE_ENABLED", False)
    with trades_api.app.test_client() as c:
        r = c.get("/trades")
    assert json.loads(r.data) == [{"source": "bot", "x": 1}]


# ──────────────────────────────────────────────────────────────────────
# Route: kill-switch ON honours ?env=
# ──────────────────────────────────────────────────────────────────────
def test_toggle_on_env_demo_uses_env_loader(stub_data, monkeypatch):
    monkeypatch.setattr(trades_api, "DASHBOARD_ENV_TOGGLE_ENABLED", True)
    with trades_api.app.test_client() as c:
        r = c.get("/trades?env=demo")
    body = json.loads(r.data)
    assert body["env"] == "demo"
    assert body["source"] == "spine"
    assert body["toggle_enabled"] is True
    assert body["trades"][0]["env"] == "demo"


def test_toggle_on_env_live_unconfigured(stub_data, monkeypatch):
    """env=live without IG_LIVE_* creds → source=unconfigured + empty
    trades + OTHER pill disabled."""
    monkeypatch.setattr(trades_api, "DASHBOARD_ENV_TOGGLE_ENABLED", True)
    with trades_api.app.test_client() as c:
        r = c.get("/trades?env=live")
    body = json.loads(r.data)
    assert body["env"] == "live"
    assert body["source"] == "unconfigured"
    assert body["trades"] == []
    assert "other" in body["who_disabled"]
    assert body["toggle_enabled"] is True


def test_toggle_on_who_only_defaults_to_env(stub_data, monkeypatch):
    """who without env, toggle ON → default env applied + env loader hit."""
    monkeypatch.setattr(trades_api, "DASHBOARD_ENV_TOGGLE_ENABLED", True)
    monkeypatch.setattr(trades_api, "DEFAULT_DASHBOARD_ENV", "demo")
    with trades_api.app.test_client() as c:
        r = c.get("/trades?who=mine")
    body = json.loads(r.data)
    assert body["env"] == "demo"
    assert body["source"] == "spine"


def test_toggle_on_env_garbage_normalises_to_default(stub_data, monkeypatch):
    monkeypatch.setattr(trades_api, "DASHBOARD_ENV_TOGGLE_ENABLED", True)
    monkeypatch.setattr(trades_api, "DEFAULT_DASHBOARD_ENV", "demo")
    with trades_api.app.test_client() as c:
        r = c.get("/trades?env=garbage")
    body = json.loads(r.data)
    assert body["env"] == "demo"


# ──────────────────────────────────────────────────────────────────────
# Per-env session cache isolation
# ──────────────────────────────────────────────────────────────────────
def test_env_session_cache_isolates_envs(monkeypatch):
    """Demo and live IG clients are cached separately. A refresh on
    one env must NOT invalidate the other."""
    # Pretend the host singleton is DEMO so rule 1 is taken for "demo"
    # only. live falls through to env-creds (which we make None).
    class _Stub:
        IG_ACC_TYPE = "DEMO"
        @staticmethod
        def get_ig_session():
            return ("DEMO_CLIENT", {}, "ACCID")
        @staticmethod
        def refresh_session():
            return ("DEMO_CLIENT_FRESH", {}, "ACCID")
    monkeypatch.setitem(__import__("sys").modules, "ig_auth", _Stub())

    # Reset both cache slots so the test is hermetic.
    monkeypatch.setattr(trades_api, "_env_session_cache", {"demo": None, "live": None})

    # Fetch demo → uses host singleton.
    demo_ig = trades_api._get_env_session("demo")
    assert demo_ig == "DEMO_CLIENT"

    # Live → no creds → None.
    monkeypatch.delenv("IG_LIVE_USERNAME", raising=False)
    monkeypatch.delenv("IG_LIVE_PASSWORD", raising=False)
    monkeypatch.delenv("IG_LIVE_API_KEY", raising=False)
    assert trades_api._get_env_session("live") is None

    # Refresh demo. Must NOT affect live entry.
    demo_ig_fresh = trades_api._get_env_session("demo", refresh=True)
    assert demo_ig_fresh == "DEMO_CLIENT_FRESH"
    assert trades_api._env_session_cache["live"] is None
