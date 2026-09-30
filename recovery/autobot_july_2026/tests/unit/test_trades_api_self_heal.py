"""Unit tests for trades_api.py spine session self-heal + BST datetime
hardening (Part 1 of the dashboard upgrade).

Covered behaviour:
1. `_is_session_expired_error` matches the IG error markers it should
   match and rejects everything else.
2. `_normalize_bst_tz` rewrites the trading_ig "space-instead-of-+"
   timezone bug and is idempotent on already-correct strings.
3. `_spine_call_with_self_heal` retries exactly once after a session-
   expired exception, swapping the freshly cached `ig` into the call,
   and re-raises if the second attempt also fails.
4. The retry mechanism only triggers on session-expired markers — other
   exceptions propagate immediately.
"""
from __future__ import annotations

import pytest

import trades_api


def test_session_expired_marker_detection():
    assert trades_api._is_session_expired_error(
        Exception("error.security.client-token-invalid: token expired"))
    assert trades_api._is_session_expired_error(
        Exception("Some wrapper: client-token-invalid"))
    assert trades_api._is_session_expired_error(
        Exception("error.security.oauth-token-invalid"))
    # Mixed case still matches (we lowercase).
    assert trades_api._is_session_expired_error(
        Exception("ERROR.SECURITY.CLIENT-TOKEN-INVALID"))


def test_session_expired_marker_rejects_others():
    assert not trades_api._is_session_expired_error(
        Exception("error.public-api.exceeded-api-key-allowance"))
    assert not trades_api._is_session_expired_error(
        Exception("HTTPError: 500"))
    assert not trades_api._is_session_expired_error(Exception(""))
    assert not trades_api._is_session_expired_error(ValueError("nothing here"))


def test_bst_tz_normalisation():
    # The bug shape: space instead of plus.
    assert (trades_api._normalize_bst_tz("2026-05-07T10:11:43 01:00")
            == "2026-05-07T10:11:43+01:00")
    # Already correct → unchanged.
    assert (trades_api._normalize_bst_tz("2026-05-07T10:11:43+01:00")
            == "2026-05-07T10:11:43+01:00")
    # No offset at all → unchanged.
    assert trades_api._normalize_bst_tz("2026-05-07T10:11:43") == "2026-05-07T10:11:43"
    # Z suffix → unchanged.
    assert trades_api._normalize_bst_tz("2026-05-07T10:11:43Z") == "2026-05-07T10:11:43Z"
    # Empty / falsy → unchanged.
    assert trades_api._normalize_bst_tz("") == ""
    assert trades_api._normalize_bst_tz(None) is None


def test_self_heal_retries_on_session_expired(monkeypatch):
    """First call raises client-token-invalid → helper calls
    refresh_session() then retries once with the new client."""
    calls = []
    fresh_ig = object()

    def fn(ig, x):
        calls.append((ig, x))
        if len(calls) == 1:
            raise Exception("error.security.client-token-invalid")
        return ("ok", ig, x)

    # Pretend the post-refresh cache pull returned fresh_ig.
    monkeypatch.setattr(
        trades_api, "_get_ig_session_with_self_heal",
        lambda refresh=False: fresh_ig,
    )

    result = trades_api._spine_call_with_self_heal("test", fn, "old_ig", 42)
    assert result == ("ok", fresh_ig, 42)
    # Two invocations: once with stale ig, once with fresh ig.
    assert len(calls) == 2
    assert calls[0][0] == "old_ig"
    assert calls[1][0] is fresh_ig


def test_self_heal_does_not_retry_non_session_errors(monkeypatch):
    """A non-session-expired error must NOT trigger a refresh; bubble up."""
    refreshed = {"count": 0}

    def fake_get(refresh=False):
        if refresh:
            refreshed["count"] += 1
        return object()

    monkeypatch.setattr(trades_api, "_get_ig_session_with_self_heal", fake_get)

    def fn(ig):
        raise RuntimeError("some other error")

    with pytest.raises(RuntimeError, match="some other error"):
        trades_api._spine_call_with_self_heal("test", fn, "ig")
    assert refreshed["count"] == 0, "refresh must NOT be called on unrelated errors"


def test_self_heal_reraises_when_refresh_also_fails(monkeypatch):
    """If refresh_session itself fails (None returned), the original error
    is re-raised — caller's existing try/except handles it normally."""

    def fake_get(refresh=False):
        if refresh:
            return None  # refresh failed
        return object()

    monkeypatch.setattr(trades_api, "_get_ig_session_with_self_heal", fake_get)

    err = Exception("error.security.client-token-invalid")
    def fn(ig):
        raise err

    with pytest.raises(Exception, match="client-token-invalid"):
        trades_api._spine_call_with_self_heal("test", fn, "ig")


def test_self_heal_reraises_when_second_attempt_also_fails(monkeypatch):
    """Second attempt fails (still session-expired or otherwise) → the
    helper does not loop; the second exception propagates."""
    fresh_ig = object()
    monkeypatch.setattr(
        trades_api, "_get_ig_session_with_self_heal",
        lambda refresh=False: fresh_ig,
    )
    calls = []
    def fn(ig):
        calls.append(ig)
        raise Exception("error.security.client-token-invalid attempt %d" % len(calls))

    with pytest.raises(Exception, match="attempt 2"):
        trades_api._spine_call_with_self_heal("test", fn, "old_ig")
    assert len(calls) == 2


def test_iso_z_passes_bst_form_through_normaliser():
    """_iso_z (the public datetime normaliser used everywhere in the spine)
    must hand bogus space-offset strings through `_normalize_bst_tz` so
    the slice produces a clean trailing Z."""
    out = trades_api._iso_z("2026-05-07T10:11:43 01:00")
    assert out == "2026-05-07T10:11:43Z"
