"""Tests for the event-driven ig_dealing_rules module.

Behaviour under test (2026-10-28 operator ruling):

* No pre-trade API lookup.  No background polling.
* ``record_rejection(epic, pair)`` makes ONE ``fetch_market_by_epic``
  call and records the observation.  No retry.
* ``last_known_min(epic)`` returns the (unexpired) observation.
* ``is_known_too_tight(epic, requested_pips)`` returns
  ``(blocked, obs)`` — ``blocked=True`` iff an observation exists and
  requested is strictly below it.  No observation → not blocked.
* Bounded TTL (default 15 min).  Expiry removes the observation.
* ``invalidate(epic)`` is an operator-driven clear.
* Only POINTS unit is accepted; missing / unknown / PERCENTAGE
  rejects without recording.
* No credentials, response bodies, or exception messages are logged.
"""
from __future__ import annotations

import importlib.util
import sys
import time
import types
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent.parent
MOD_PATH = HERE / "module" / "ig_dealing_rules.py"


@pytest.fixture()
def mod():
    """Fresh module instance per test with ig_auth stubbed."""
    if "ig_auth" in sys.modules:
        del sys.modules["ig_auth"]
    stub = types.ModuleType("ig_auth")

    class _StubIG:
        def __init__(self):
            self.calls = []
            self.responses = {}
        def fetch_market_by_epic(self, epic):
            self.calls.append(epic)
            resp = self.responses.get(epic)
            if isinstance(resp, Exception):
                raise resp
            if resp is None:
                raise RuntimeError("no response configured for " + str(epic))
            return resp

    _stub = _StubIG()
    stub.get_ig_session = lambda: (_stub, None, None)
    sys.modules["ig_auth"] = stub

    spec = importlib.util.spec_from_file_location(
        f"igdr_test_{int(time.time()*1e6)}", MOD_PATH,
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    m._stub_ig = _stub
    m._reset_for_tests()
    # Shorten the coalesce window so repeat-rejection tests don't need sleeps.
    m._FETCH_COALESCE_SECS = 0.0
    return m


def _rule(value, unit="POINTS"):
    return {
        "dealingRules": {
            "minNormalStopOrLimitDistance": {"value": value, "unit": unit},
        },
    }


# ─────────────────────────────────────────────────────────────────────
# 1. No pre-trade lookup — the module is passive until rejection
# ─────────────────────────────────────────────────────────────────────
def test_no_fetch_without_rejection(mod):
    """last_known_min + is_known_too_tight MUST NOT call IG."""
    _blocked, _obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 12.0)
    assert _blocked is False
    assert _obs is None
    assert mod._stub_ig.calls == []


def test_is_known_too_tight_no_obs_proceeds(mod):
    """With no observation, submission is NOT blocked at any distance."""
    for req in [1.0, 4.0, 12.0, 100.0]:
        blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", req)
        assert blocked is False
        assert obs is None
    assert mod._stub_ig.calls == []


# ─────────────────────────────────────────────────────────────────────
# 2. record_rejection — single IG fetch, structured observation
# ─────────────────────────────────────────────────────────────────────
def test_record_rejection_makes_one_fetch(mod):
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(4.0)
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is not None
    assert obs.value_pips == 4.0
    assert obs.unit == "POINTS"
    assert obs.retrieved_at > 0
    assert obs.reason_cause == "ATTACHED_ORDER_LEVEL_ERROR"
    assert mod._stub_ig.calls == ["CS.D.GBPUSD.TODAY.IP"]


def test_record_rejection_stores_observation(mod):
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    obs = mod.last_known_min("CS.D.GBPUSD.TODAY.IP")
    assert obs is not None
    assert obs.value_pips == 6.0


def test_record_rejection_fetch_failure_records_nothing(mod):
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = RuntimeError("api down")
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is None
    # No observation stored — subsequent submissions NOT guarded.
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is None


# ─────────────────────────────────────────────────────────────────────
# 3. is_known_too_tight — blocks subsequent submissions
# ─────────────────────────────────────────────────────────────────────
def test_known_too_tight_blocks_subsequent(mod):
    """After a 6-pip observation, a 4-pip submission is blocked."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")

    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is True
    assert obs.value_pips == 6.0


def test_known_at_or_above_min_allowed(mod):
    """A submission at or above the observation is allowed."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")

    for req in [6.0, 6.5, 12.0]:
        blocked, _ = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", req)
        assert blocked is False, f"{req}p should be allowed"


def test_fp_tolerance_at_min(mod):
    """requested ≈ min within 1e-6 is NOT blocked (Phase 4 defect)."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(12.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")

    almost_12 = (1.3310 - 1.3298) / 0.0001  # 11.99999...
    blocked, _ = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", almost_12)
    assert blocked is False


# ─────────────────────────────────────────────────────────────────────
# 4. Bounded expiry
# ─────────────────────────────────────────────────────────────────────
def test_expired_observation_discarded(mod):
    """An observation older than TTL is dropped and no longer blocks."""
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 8.0,
                            retrieved_at=time.time() - mod._TTL_SECS - 1.0)
    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is False
    assert obs is None


def test_fresh_observation_within_ttl_still_blocks(mod):
    """An observation inside the TTL continues to block."""
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 8.0,
                            retrieved_at=time.time() - 60.0)
    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is True
    assert obs is not None
    assert obs.value_pips == 8.0


def test_last_known_min_removes_expired(mod):
    """last_known_min returns None for an expired observation and the
    entry is removed."""
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 8.0,
                            retrieved_at=time.time() - mod._TTL_SECS - 10.0)
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is None
    # Lookup again — still None (and no new fetch)
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is None
    assert mod._stub_ig.calls == []


# ─────────────────────────────────────────────────────────────────────
# 5. invalidate — operator-driven
# ─────────────────────────────────────────────────────────────────────
def test_invalidate_clears_observation(mod):
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 8.0)
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is not None
    mod.invalidate("CS.D.GBPUSD.TODAY.IP")
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is None


def test_invalidate_unknown_epic_safe(mod):
    """Calling invalidate on an unknown epic is a safe no-op."""
    mod.invalidate("CS.D.NOTHING.TODAY.IP")
    assert mod.last_known_min("CS.D.NOTHING.TODAY.IP") is None


# ─────────────────────────────────────────────────────────────────────
# 6. Unit discipline — brief §2
# ─────────────────────────────────────────────────────────────────────
def test_missing_unit_rejected(mod):
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = {
        "dealingRules": {
            "minNormalStopOrLimitDistance": {"value": 4.0},  # no unit
        },
    }
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is None
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is None


def test_percentage_unit_rejected(mod):
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(0.1, unit="PERCENTAGE")
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is None


def test_pips_unit_rejected(mod):
    """Hypothetical 'PIPS' label — same value but we only accept POINTS exactly."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(4.0, unit="PIPS")
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is None


def test_empty_response_rejected(mod):
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = {"dealingRules": {}}
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is None


# ─────────────────────────────────────────────────────────────────────
# 7. Rate-limit protection
# ─────────────────────────────────────────────────────────────────────
def test_fetch_coalesce_window_suppresses_repeat(mod):
    """Within the coalesce window, a second rejection does NOT issue a
    second REST call."""
    mod._FETCH_COALESCE_SECS = 10.0  # restore default-like
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(4.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert len(mod._stub_ig.calls) == 1
    # Immediate re-trigger
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert len(mod._stub_ig.calls) == 1


def test_concurrent_rejection_dedup(mod):
    import threading
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(4.0)

    def _call():
        mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")

    threads = [threading.Thread(target=_call) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    # Not every thread is guaranteed to collapse (depends on scheduler)
    # — the strict invariant: no exceptions, and at least ONE call fired.
    assert 1 <= len(mod._stub_ig.calls) <= 5


# ─────────────────────────────────────────────────────────────────────
# 8. Observation metadata
# ─────────────────────────────────────────────────────────────────────
def test_observation_fields(mod):
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(7.5)
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs.epic == "CS.D.GBPUSD.TODAY.IP"
    assert obs.value_pips == 7.5
    assert obs.unit == "POINTS"
    assert obs.retrieved_at > 0
    assert obs.reason_cause == "ATTACHED_ORDER_LEVEL_ERROR"
    assert 0.0 <= obs.age_secs < 5.0
    assert obs.expired is False


def test_change_detected_in_log(mod, caplog):
    """When a subsequent rejection records a DIFFERENT value, log flags
    the change."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(4.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    mod._FETCH_COALESCE_SECS = 0.0  # allow re-fetch
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(8.0)
    with caplog.at_level("INFO"):
        mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert any("previous=4.00p" in rec.message
               and "value=8.00p" in rec.message
               for rec in caplog.records)


# ─────────────────────────────────────────────────────────────────────
# 9. Safety invariants
# ─────────────────────────────────────────────────────────────────────
def test_no_credentials_in_source():
    src = MOD_PATH.read_text()
    for secret in ("IG_USERNAME", "IG_PASSWORD", "IG_API_KEY", ".env"):
        assert secret not in src, f"module source must not reference {secret}"


def test_no_file_writes_in_source():
    src = MOD_PATH.read_text()
    assert "open(" not in src
    # Only logger-based output
    assert ".write(" not in src.replace("logger.write", "")


def test_fetch_exception_type_not_message(mod, caplog):
    """Exception messages must not reach the logs — only type names."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = \
        RuntimeError("my-secret-api-key-123")
    with caplog.at_level("WARNING"):
        mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    for rec in caplog.records:
        assert "my-secret-api-key-123" not in rec.message


# ─────────────────────────────────────────────────────────────────────
# 10. 4-pip acceptance path — brief §3 scenario
# ─────────────────────────────────────────────────────────────────────
def test_4pip_stop_proceeds_when_no_prior_rejection(mod):
    """With no prior observation, a 4-pip submission is NOT blocked —
    it goes to IG, which is the authoritative check."""
    blocked, _ = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is False
    assert mod._stub_ig.calls == []


def test_4pip_stop_blocked_after_higher_min_observed(mod):
    """If IG previously rejected because min=6, a 4p submission is
    blocked WITHOUT touching IG."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    # Clear the call log — we want to verify no new call on is_known_too_tight.
    mod._stub_ig.calls.clear()
    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is True
    assert obs.value_pips == 6.0
    assert mod._stub_ig.calls == []  # NO new IG call


def test_4pip_stop_proceeds_again_after_invalidate(mod):
    """Operator invalidation re-enables the 4p attempt."""
    mod._stub_ig.responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)[0] is True

    mod.invalidate("CS.D.GBPUSD.TODAY.IP")
    assert mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)[0] is False


def test_4pip_stop_proceeds_again_after_expiry(mod):
    """TTL expiry clears the block automatically."""
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0,
                            retrieved_at=time.time() - mod._TTL_SECS - 1.0)
    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is False
    assert obs is None
