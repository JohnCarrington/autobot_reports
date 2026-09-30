import logging
import inspect
import importlib
import pytest

@pytest.fixture
def load_ig_auth(monkeypatch):
    monkeypatch.setenv("IG_USERNAME", "u")
    monkeypatch.setenv("IG_PASSWORD", "p")
    monkeypatch.setenv("IG_API_KEY", "k")
    monkeypatch.setenv("IG_ACC_TYPE", "DEMO")
    import ig_auth
    importlib.reload(ig_auth)
    return ig_auth

def test_ig_auth_imports_successful_and_logger(load_ig_auth):
    ig_auth = load_ig_auth
    assert isinstance(ig_auth.logger, logging.Logger)
    assert ig_auth.logger.name == "AutoBot"

def test_ig_auth_env_constants_present(load_ig_auth):
    ig_auth = load_ig_auth
    assert ig_auth.IG_USERNAME is not None
    assert ig_auth.IG_PASSWORD is not None
    assert ig_auth.IG_API_KEY is not None
    assert ig_auth.IG_ACC_TYPE in ["DEMO", "LIVE"]
    assert isinstance(ig_auth.BACKOFF_SCHEDULE, list)
    assert hasattr(ig_auth, "_CACHED")

def test_ig_auth_get_ig_session_signature_and_return_shape(monkeypatch):
    monkeypatch.setenv("IG_USERNAME", "u")
    monkeypatch.setenv("IG_PASSWORD", "p")
    monkeypatch.setenv("IG_API_KEY", "k")

    class FakeIGService:
        def __init__(self, *a, **kw): pass
        def create_session(self): pass
        def fetch_accounts(self): return {"accounts": [{"accountId": "A1", "preferred": True}]}
        def switch_account(self, *a, **kw): pass

    def fake_build_headers(ig, account_id): return {"CST": "c", "X-SECURITY-TOKEN": "x", "X-IG-ACCOUNT-ID": account_id}

    import ig_auth
    importlib.reload(ig_auth)
    monkeypatch.setattr(ig_auth, "IGService", FakeIGService)
    monkeypatch.setattr(ig_auth, "_build_headers", fake_build_headers)
    ig_auth._CACHED = None

    sig = inspect.signature(ig_auth.get_ig_session)
    assert list(sig.parameters.keys()) == []

    result = ig_auth.get_ig_session()
    assert isinstance(result, tuple)
    assert len(result) == 3
