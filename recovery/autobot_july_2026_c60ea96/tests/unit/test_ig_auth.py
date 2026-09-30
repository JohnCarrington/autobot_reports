"""
Unit tests for ig_auth.py

Production API:
- get_ig_session() returns (ig_service, cst, x_security_token) — actually (ig_service, headers_dict, account_id)
- Reads IG_USERNAME, IG_PASSWORD, IG_API_KEY, IG_ACCOUNT_ID, IG_ACC_TYPE from env
- Raises EnvironmentError if required vars missing
- Has _normalize_accounts, _headers_from_requests_session, _extract_tokens, _build_headers helpers
- Singleton caching via _CACHED
"""
import pytest
import importlib
import types
import time
import sys


@pytest.fixture(autouse=True)
def ig_auth_env(monkeypatch):
    monkeypatch.setenv("IG_USERNAME", "user")
    monkeypatch.setenv("IG_PASSWORD", "pass")
    monkeypatch.setenv("IG_API_KEY", "api")
    monkeypatch.setenv("IG_ACC_TYPE", "DEMO")
    import ig_auth
    importlib.reload(ig_auth)
    return ig_auth


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("IG_USERNAME", raising=False)
    monkeypatch.delenv("IG_PASSWORD", raising=False)
    monkeypatch.delenv("IG_API_KEY", raising=False)
    # Prevent load_dotenv from re-reading the .env file
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    sys.modules.pop("ig_auth", None)
    with pytest.raises(EnvironmentError):
        import ig_auth  # noqa: F401


def test_normalize_accounts_tuple(ig_auth_env):
    result = (200, {"accounts": [{"accountId": "A1"}, {"accountId": "A2"}]})
    out = ig_auth_env._normalize_accounts(result)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0]["accountId"] == "A1"


def test_headers_from_requests_session_valid():
    class FakeSession:
        headers = {"cst": "C1", "x-security-token": "S1"}

    class FakeIG:
        crud_session = types.SimpleNamespace(session=FakeSession())

    import ig_auth
    out = ig_auth._headers_from_requests_session(FakeIG())
    assert out == {"CST": "C1", "X-SECURITY-TOKEN": "S1"}


def test_extract_tokens_prefers_headers(monkeypatch):
    class FakeIG:
        crud_session = types.SimpleNamespace(
            session=types.SimpleNamespace(
                headers={"CST": "H1", "X-SECURITY-TOKEN": "H2"}
            )
        )
        session = types.SimpleNamespace(
            auth_data={"client_token": "S1", "security_token": "S2"}
        )

    import ig_auth
    out = ig_auth._extract_tokens(FakeIG())
    assert out == {"CST": "H1", "X-SECURITY-TOKEN": "H2"}


def test_extract_tokens_fallback_to_auth_data():
    class FakeIG:
        crud_session = None
        session = types.SimpleNamespace(
            auth_data={"client_token": "C2", "security_token": "S2"}
        )

    import ig_auth
    out = ig_auth._extract_tokens(FakeIG())
    assert out == {"CST": "C2", "X-SECURITY-TOKEN": "S2"}


def test_build_headers_success(monkeypatch):
    import ig_auth
    monkeypatch.setattr(ig_auth, "IG_API_KEY", "testkey", raising=False)
    monkeypatch.setattr(
        ig_auth,
        "_extract_tokens",
        lambda ig: {"CST": "C123", "X-SECURITY-TOKEN": "X123"},
    )

    out = ig_auth._build_headers("fake_ig", "ACC1")
    assert out["CST"] == "C123"
    assert out["X-SECURITY-TOKEN"] == "X123"
    assert out["X-IG-ACCOUNT-ID"] == "ACC1"
    assert out["X-IG-API-KEY"] == "testkey"
    assert "Content-Type" in out
    assert "Accept" in out


def test_build_headers_raises_if_tokens_missing(monkeypatch):
    import ig_auth
    monkeypatch.setattr(ig_auth, "_extract_tokens", lambda ig: {})
    monkeypatch.setattr(ig_auth, "_headers_from_requests_session", lambda ig: {})

    with pytest.raises(RuntimeError):
        ig_auth._build_headers("ig", "acc")


def test_get_ig_session_singleton(monkeypatch, ig_auth_env):
    class FakeIGService:
        def __init__(self, *a, **kw):
            self.calls = []
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            self.calls.append("create")

        def fetch_accounts(self):
            return {"accounts": [{"accountId": "A1", "preferred": True}]}

        def switch_account(self, *a, **kw):
            pass

    monkeypatch.setattr(ig_auth_env, "IGService", FakeIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_build_headers",
        lambda ig, acc: {"CST": "X", "X-SECURITY-TOKEN": "Y", "X-IG-ACCOUNT-ID": acc},
    )

    ig_auth_env._CACHED = None

    i1, h1, a1 = ig_auth_env.get_ig_session()
    i2, h2, a2 = ig_auth_env.get_ig_session()

    assert i1 is i2
    assert h1 == h2
    assert a1 == a2
    assert i1.calls == ["create"]


def test_get_ig_session_backoff(monkeypatch, ig_auth_env):
    class FakeIGService:
        def __init__(self, *a, **kw):
            self.count = 0
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            self.count += 1
            if self.count < 3:
                raise ig_auth_env.IGException(
                    "error.public-api.exceeded-api-key-allowance"
                )

        def fetch_accounts(self):
            return {"accounts": [{"accountId": "A1"}]}

        def switch_account(self, *a, **kw):
            pass

    monkeypatch.setattr(ig_auth_env, "IGService", FakeIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_build_headers",
        lambda ig, acc: {"CST": "x", "X-SECURITY-TOKEN": "y", "X-IG-ACCOUNT-ID": acc},
    )

    monkeypatch.setattr(time, "sleep", lambda x: None)
    ig_auth_env._CACHED = None

    ig, headers, acc = ig_auth_env.get_ig_session()
    assert acc == "A1"
    assert ig.count == 3


# ---------------------------------------------------------------------------
# 2026-07-10 Auth-suspension guard: classification + backoff + fatal exit.
# ---------------------------------------------------------------------------

def _mk_ig_exc(ig_auth_env, body):
    """Build an IGException matching the shape trading_ig raises on 401."""
    return ig_auth_env.IGException(f"HTTP error: 401 {body}")


def test_extract_ig_error_code_suspended(ig_auth_env):
    body = '{"errorCode":"error.security.client-suspended"}'
    assert (
        ig_auth_env._extract_ig_error_code(f"HTTP error: 401 {body}")
        == "error.security.client-suspended"
    )


def test_extract_ig_error_code_other(ig_auth_env):
    body = '{"errorCode":"error.security.invalid-details"}'
    assert (
        ig_auth_env._extract_ig_error_code(f"HTTP error: 401 {body}")
        == "error.security.invalid-details"
    )


def test_extract_ig_error_code_empty_when_no_json(ig_auth_env):
    assert ig_auth_env._extract_ig_error_code("HTTP error: 500 boom") == ""
    assert ig_auth_env._extract_ig_error_code("") == ""


def test_client_suspended_raises_fatal_and_alerts(monkeypatch, ig_auth_env):
    """FIX-A (a): a `client-suspended` 401 → FatalAuthError on first attempt,
    Telegram alert fired exactly once, no retries."""
    calls = {"create": 0}

    class FakeIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            calls["create"] += 1
            raise _mk_ig_exc(
                ig_auth_env,
                '{"errorCode":"error.security.client-suspended"}',
            )

    tg = []
    monkeypatch.setattr(ig_auth_env, "IGService", FakeIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_send_fatal_auth_telegram",
        lambda code, attempt: tg.append((code, attempt)),
    )
    monkeypatch.setattr(time, "sleep", lambda x: None)
    ig_auth_env._CACHED = None

    with pytest.raises(ig_auth_env.FatalAuthError) as excinfo:
        ig_auth_env.get_ig_session()

    assert excinfo.value.error_code == "error.security.client-suspended"
    assert excinfo.value.attempts == 1
    # Suspended = do NOT retry. Exactly one call.
    assert calls["create"] == 1
    assert tg == [("error.security.client-suspended", 1)]


def test_non_suspended_auth_backoff_sequence(monkeypatch, ig_auth_env):
    """FIX-A (b): non-suspended 401 → sleeps follow the exact schedule
    30, 60, 120, 240 before each retry attempt (5 attempts total).

    We only capture positive-duration sleeps here — the pytest runner and
    other imported modules do sub-second heartbeat sleeps that would
    otherwise swamp the record.
    """
    slept = []

    def _capture(s):
        # Only the backoff schedule uses whole-second delays >= 30. Anything
        # sub-second is unrelated poll/heartbeat noise.
        if s and s >= 1:
            slept.append(int(s))

    monkeypatch.setattr(ig_auth_env.time, "sleep", _capture)

    calls = {"n": 0}

    class FakeIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            calls["n"] += 1
            raise _mk_ig_exc(
                ig_auth_env,
                '{"errorCode":"error.security.invalid-details"}',
            )

    monkeypatch.setattr(ig_auth_env, "IGService", FakeIGService)
    monkeypatch.setattr(
        ig_auth_env, "_send_fatal_auth_telegram", lambda code, attempt: None
    )
    ig_auth_env._CACHED = None

    with pytest.raises(ig_auth_env.FatalAuthError):
        ig_auth_env.get_ig_session()

    # Exactly the published schedule: attempt 1 has no sleep, attempts 2-5
    # sleep for 30, 60, 120, 240 respectively. Attempt 5 exhausts the cap
    # without a further sleep.
    assert slept == [30, 60, 120, 240]


def test_attempt_cap_stops_at_five(monkeypatch, ig_auth_env):
    """FIX-A (c): after AUTH_MAX_ATTEMPTS (5) failures the loop gives up."""
    monkeypatch.setattr(time, "sleep", lambda s: None)

    calls = {"n": 0}

    class FakeIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            calls["n"] += 1
            raise _mk_ig_exc(
                ig_auth_env,
                '{"errorCode":"error.security.oauth-token-invalid"}',
            )

    tg = []
    monkeypatch.setattr(ig_auth_env, "IGService", FakeIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_send_fatal_auth_telegram",
        lambda code, attempt: tg.append((code, attempt)),
    )
    ig_auth_env._CACHED = None

    with pytest.raises(ig_auth_env.FatalAuthError) as excinfo:
        ig_auth_env.get_ig_session()

    assert calls["n"] == ig_auth_env.AUTH_MAX_ATTEMPTS == 5
    assert excinfo.value.attempts == 5
    assert excinfo.value.error_code == "error.security.oauth-token-invalid"
    # Telegram alert fires exactly once at the cap.
    assert tg == [("error.security.oauth-token-invalid", 5)]


def test_fatal_exit_code_matches_unit(ig_auth_env):
    """FIX-A (d): The FATAL_AUTH_EXIT_CODE constant must match the value
    the unit-file drop-in wires into RestartPreventExitStatus. If either
    side is renumbered without the other, systemd would ignore the fatal
    exit and re-enter the crash loop — the bug this fix exists to close.
    """
    import re
    from pathlib import Path

    drop_in = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "systemd"
        / "autobot.service.d-auth-suspension-guard.conf"
    )
    text = drop_in.read_text()
    m = re.search(r"^RestartPreventExitStatus\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    assert m, "RestartPreventExitStatus missing from drop-in"
    assert int(m.group(1)) == ig_auth_env.FATAL_AUTH_EXIT_CODE


def test_first_success_no_backoff(monkeypatch, ig_auth_env):
    """Sanity: a first-shot login must NOT sleep the backoff floor —
    otherwise every clean boot pays 30s.
    """
    slept = []

    def _capture(s):
        if s and s >= 1:
            slept.append(int(s))

    monkeypatch.setattr(ig_auth_env.time, "sleep", _capture)

    class FakeIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            pass

        def fetch_accounts(self):
            return {"accounts": [{"accountId": "A1", "preferred": True}]}

        def switch_account(self, *a, **kw):
            pass

    monkeypatch.setattr(ig_auth_env, "IGService", FakeIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_build_headers",
        lambda ig, acc: {"CST": "x", "X-SECURITY-TOKEN": "y", "X-IG-ACCOUNT-ID": acc},
    )
    ig_auth_env._CACHED = None

    ig, headers, acc = ig_auth_env.get_ig_session()
    assert acc == "A1"
    assert slept == []


# ---------------------------------------------------------------------------
# 2026-07-23 refresh_session() throttle + cache-preservation guard.
# Fixes the auth-flood defect where a failing refresh cleared _CACHED and
# every subsequent caller (get_open_positions, SL-amend, LS recovery) fired
# a fresh create_session() cascade against IG (~68 failed logins/30min).
# ---------------------------------------------------------------------------

def _reset_refresh_state(ig_auth_env):
    """Zero refresh-throttle state so each test starts clean."""
    ig_auth_env._CACHED = None
    ig_auth_env._LAST_REFRESH_ATTEMPT = 0.0
    ig_auth_env._REFRESH_INFLIGHT_PRIOR = None
    ig_auth_env._REFRESH_INFLIGHT = False


def test_refresh_session_failure_restores_prior_cache(monkeypatch, ig_auth_env):
    """A failing refresh_session leaves _CACHED holding the PRIOR session
    object (assert by identity) and the original exception propagates."""
    _reset_refresh_state(ig_auth_env)

    prior = ("prior_ig", {"CST": "P", "X-SECURITY-TOKEN": "Q"}, "PriorAcc")
    ig_auth_env._CACHED = prior

    class BoomIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            raise ig_auth_env.IGException("network exploded")

    monkeypatch.setattr(ig_auth_env, "IGService", BoomIGService)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    with pytest.raises(ig_auth_env.IGException) as excinfo:
        ig_auth_env.refresh_session()

    assert "network exploded" in str(excinfo.value)
    assert ig_auth_env._CACHED is prior  # identity, not equality
    assert ig_auth_env._REFRESH_INFLIGHT_PRIOR is None


def test_refresh_session_success_replaces_cache(monkeypatch, ig_auth_env):
    """A successful refresh_session replaces _CACHED with the new session."""
    _reset_refresh_state(ig_auth_env)

    prior = ("prior_ig", {"CST": "P"}, "PriorAcc")
    ig_auth_env._CACHED = prior

    class FreshIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            pass

        def fetch_accounts(self):
            return {"accounts": [{"accountId": "NEW", "preferred": True}]}

        def switch_account(self, *a, **kw):
            pass

    monkeypatch.setattr(ig_auth_env, "IGService", FreshIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_build_headers",
        lambda ig, acc: {"CST": "n", "X-SECURITY-TOKEN": "m", "X-IG-ACCOUNT-ID": acc},
    )

    result = ig_auth_env.refresh_session()
    assert result[2] == "NEW"
    assert ig_auth_env._CACHED is result
    assert ig_auth_env._CACHED is not prior
    assert ig_auth_env._REFRESH_INFLIGHT_PRIOR is None


def test_refresh_session_throttle_returns_existing_cache(monkeypatch, ig_auth_env):
    """Repeat calls inside AUTH_REFRESH_MIN_INTERVAL_S return the existing
    cache and construct no IGService."""
    _reset_refresh_state(ig_auth_env)

    prior = ("prior_ig", {"CST": "P"}, "PriorAcc")
    ig_auth_env._CACHED = prior

    ctor_calls = {"n": 0}

    class ShouldNotBeConstructed:
        def __init__(self, *a, **kw):
            ctor_calls["n"] += 1

    monkeypatch.setattr(ig_auth_env, "IGService", ShouldNotBeConstructed)

    # Force throttle window active: slot consumed "just now".
    ig_auth_env._LAST_REFRESH_ATTEMPT = time.monotonic()

    for _ in range(3):
        result = ig_auth_env.refresh_session()
        assert result is prior

    assert ctor_calls["n"] == 0


def test_refresh_session_throttle_no_cache_raises_runtime(monkeypatch, ig_auth_env):
    """Inside the throttle window with no cache present: RuntimeError,
    and no IGService construction."""
    _reset_refresh_state(ig_auth_env)

    ctor_calls = {"n": 0}

    class ShouldNotBeConstructed:
        def __init__(self, *a, **kw):
            ctor_calls["n"] += 1

    monkeypatch.setattr(ig_auth_env, "IGService", ShouldNotBeConstructed)

    # Throttle active, _CACHED is None (via _reset_refresh_state).
    ig_auth_env._LAST_REFRESH_ATTEMPT = time.monotonic()

    with pytest.raises(RuntimeError) as excinfo:
        ig_auth_env.refresh_session()

    assert "throttled" in str(excinfo.value).lower()
    assert ctor_calls["n"] == 0


def test_refresh_session_concurrent_second_returns_from_cache(monkeypatch, ig_auth_env):
    """Deadlock guard: while thread 1 is inside get_ig_session (blocking on
    a slow create_session), thread 2 calling refresh_session must not wait
    for thread 1's ~12min backoff ladder. It returns from cache via the
    in-flight side channel."""
    import threading as _th

    _reset_refresh_state(ig_auth_env)
    prior = ("prior_ig", {"CST": "P"}, "PriorAcc")
    ig_auth_env._CACHED = prior

    started = _th.Event()
    unblock = _th.Event()

    class BlockingIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            started.set()
            unblock.wait(timeout=5.0)
            # After unblock, succeed (thread 1 completes cleanly).

        def fetch_accounts(self):
            return {"accounts": [{"accountId": "T1", "preferred": True}]}

        def switch_account(self, *a, **kw):
            pass

    monkeypatch.setattr(ig_auth_env, "IGService", BlockingIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_build_headers",
        lambda ig, acc: {"CST": "x", "X-SECURITY-TOKEN": "y", "X-IG-ACCOUNT-ID": acc},
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    t1_result = {}

    def _t1():
        try:
            t1_result["v"] = ig_auth_env.refresh_session()
        except Exception as e:  # pragma: no cover — defensive
            t1_result["e"] = e

    t1 = _th.Thread(target=_t1)
    t1.start()
    assert started.wait(timeout=2.0), "thread 1 did not enter create_session"

    # Thread 2 runs in the main test thread. It must return quickly (cache
    # hit via the side channel), NOT wait for thread 1's blocked call.
    t2_start = time.monotonic()
    t2_result = ig_auth_env.refresh_session()
    t2_elapsed = time.monotonic() - t2_start

    assert t2_elapsed < 0.5, f"thread 2 blocked for {t2_elapsed:.3f}s (deadlock)"
    assert t2_result is prior

    # Cleanup: let thread 1 complete.
    unblock.set()
    t1.join(timeout=2.0)
    assert not t1.is_alive(), "thread 1 did not finish after unblock"


def test_refresh_session_does_not_write_or_exit(tmp_path, monkeypatch, ig_auth_env):
    """These tests must not write anything under /opt/tradingbot and must
    not call os._exit. Verified structurally: refresh_session has no
    filesystem or process-exit side effects on the failure path."""
    import os as _os

    _reset_refresh_state(ig_auth_env)
    prior = ("prior_ig", {"CST": "P"}, "PriorAcc")
    ig_auth_env._CACHED = prior

    class BoomIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            raise ig_auth_env.IGException("boom")

    monkeypatch.setattr(ig_auth_env, "IGService", BoomIGService)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    exit_calls = []
    monkeypatch.setattr(_os, "_exit", lambda code: exit_calls.append(code))

    with pytest.raises(ig_auth_env.IGException):
        ig_auth_env.refresh_session()

    assert exit_calls == []
    assert ig_auth_env._CACHED is prior


# ---------------------------------------------------------------------------
# 2026-07-23 concurrency guard: the time throttle limits ENTRY RATE only.
# A non-fatal 401 sends the in-flight caller through the 30/60/120/240/300
# backoff ladder (~12.5min), during which the 60s time throttle expires and
# would otherwise let a second caller stack its own ladder. The in-flight
# flag prevents that.
# ---------------------------------------------------------------------------

def test_refresh_session_inflight_blocks_second_regardless_of_time_throttle(
    monkeypatch, ig_auth_env
):
    """Thread 1 is inside a blocking create_session. The TIME throttle is
    intentionally set far in the past so it would not stop thread 2 — the
    in-flight flag must be the thing that does. Thread 2 must return from
    cache in under 0.5s and the IGService ctor count must stay at 1."""
    import threading as _th

    _reset_refresh_state(ig_auth_env)
    prior = ("prior_ig", {"CST": "P"}, "PriorAcc")
    ig_auth_env._CACHED = prior

    # Time throttle would NOT stop thread 2: pretend the last attempt was
    # a full hour ago.
    ig_auth_env._LAST_REFRESH_ATTEMPT = time.monotonic() - 3600.0

    started = _th.Event()
    unblock = _th.Event()
    ctor_calls = {"n": 0}

    class BlockingIGService:
        def __init__(self, *a, **kw):
            ctor_calls["n"] += 1
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            started.set()
            unblock.wait(timeout=5.0)

        def fetch_accounts(self):
            return {"accounts": [{"accountId": "T1", "preferred": True}]}

        def switch_account(self, *a, **kw):
            pass

    monkeypatch.setattr(ig_auth_env, "IGService", BlockingIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_build_headers",
        lambda ig, acc: {"CST": "x", "X-SECURITY-TOKEN": "y", "X-IG-ACCOUNT-ID": acc},
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def _t1():
        try:
            ig_auth_env.refresh_session()
        except Exception:
            pass

    t1 = _th.Thread(target=_t1)
    t1.start()
    assert started.wait(timeout=2.0), "thread 1 did not enter create_session"

    # At this point ctor should be exactly 1 (thread 1). Thread 2 must NOT
    # construct another IGService — the in-flight flag must short-circuit.
    t2_start = time.monotonic()
    result = ig_auth_env.refresh_session()
    t2_elapsed = time.monotonic() - t2_start

    assert t2_elapsed < 0.5, f"thread 2 blocked for {t2_elapsed:.3f}s"
    assert result is prior
    assert ctor_calls["n"] == 1, (
        f"expected exactly 1 IGService ctor (thread 1 only), "
        f"got {ctor_calls['n']} — concurrency guard failed"
    )

    unblock.set()
    t1.join(timeout=2.0)
    assert not t1.is_alive(), "thread 1 did not finish after unblock"
    # Ctor count still 1 even after thread 1 completes.
    assert ctor_calls["n"] == 1


def test_refresh_session_inflight_cleared_after_success(monkeypatch, ig_auth_env):
    """_REFRESH_INFLIGHT is False after a successful refresh."""
    _reset_refresh_state(ig_auth_env)

    class OkIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            pass

        def fetch_accounts(self):
            return {"accounts": [{"accountId": "OK", "preferred": True}]}

        def switch_account(self, *a, **kw):
            pass

    monkeypatch.setattr(ig_auth_env, "IGService", OkIGService)
    monkeypatch.setattr(
        ig_auth_env,
        "_build_headers",
        lambda ig, acc: {"CST": "x", "X-SECURITY-TOKEN": "y", "X-IG-ACCOUNT-ID": acc},
    )

    ig_auth_env.refresh_session()
    assert ig_auth_env._REFRESH_INFLIGHT is False
    assert ig_auth_env._REFRESH_INFLIGHT_PRIOR is None


def test_refresh_session_inflight_cleared_after_failure(monkeypatch, ig_auth_env):
    """_REFRESH_INFLIGHT is False after a failing refresh; the exception
    propagates and the prior cache is restored."""
    _reset_refresh_state(ig_auth_env)
    prior = ("prior_ig", {"CST": "P"}, "PriorAcc")
    ig_auth_env._CACHED = prior

    class BoomIGService:
        def __init__(self, *a, **kw):
            self.session = types.SimpleNamespace(auth_data={})

        def create_session(self):
            raise ig_auth_env.IGException("kaboom")

    monkeypatch.setattr(ig_auth_env, "IGService", BoomIGService)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    with pytest.raises(ig_auth_env.IGException):
        ig_auth_env.refresh_session()

    assert ig_auth_env._REFRESH_INFLIGHT is False
    assert ig_auth_env._REFRESH_INFLIGHT_PRIOR is None
    assert ig_auth_env._CACHED is prior
