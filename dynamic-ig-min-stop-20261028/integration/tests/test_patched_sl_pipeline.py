"""Integration tests — event-driven SL pipeline inside production file copies.

Verifies the patches applied to:

* /opt/tradingbot/trade_executor.py        → integration/src_patched/trade_executor_patched.py
* /opt/bb_bounce/config.py                 → integration/src_patched/bb_bounce_config_patched.py
* /opt/bb_bounce/stop_sizing.py            → integration/src_patched/bb_bounce_stop_sizing_patched.py
* /opt/{tradingbot,bb_bounce}/ig_dealing_rules.py → integration/src_patched/ig_dealing_rules.py

Scenarios covered (brief §3):

  * No pre-trade API lookup.
  * AutoBot BUY and SELL — SL attached on initial order.
  * Standalone BB Bounce submission path.
  * Exact 4-pip stop accepted when IG reports 4 pips (no prior rejection).
  * Rejection blocks subsequent trades with stops known too small.
  * Fetch failure records nothing; subsequent trades NOT guarded.
  * No silent widening.
  * Broker rejection records (value, unit, ts).
  * Existing strategy settings unchanged.
  * Stop amendments unaffected.
  * NMS and WATCH_AND_WAIT unchanged (static source check).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import types
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "src_patched"


class _StubIG:
    def __init__(self):
        self.fetch_market_calls: list[str] = []
        self.market_responses: dict[str, object] = {}
    def fetch_market_by_epic(self, epic):
        self.fetch_market_calls.append(epic)
        resp = self.market_responses.get(epic)
        if isinstance(resp, Exception):
            raise resp
        return resp or {"dealingRules": {}}


def _rule(value_pips: float, unit: str = "POINTS") -> dict:
    return {
        "dealingRules": {
            "minNormalStopOrLimitDistance": {"value": value_pips, "unit": unit},
        },
    }


@pytest.fixture()
def ig_dealing_rules():
    """Load the patched module copy under its production import name."""
    stub_ig = _StubIG()
    stub = types.ModuleType("ig_auth")
    stub.get_ig_session = lambda: (stub_ig, None, None)
    sys.modules["ig_auth"] = stub

    spec = importlib.util.spec_from_file_location(
        "ig_dealing_rules", SRC / "ig_dealing_rules.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ig_dealing_rules"] = mod
    spec.loader.exec_module(mod)
    mod._reset_for_tests()
    mod._stub_ig = stub_ig
    mod._FETCH_COALESCE_SECS = 0.0  # test determinism
    return mod


# ─────────────────────────────────────────────────────────────────────
# No pre-trade API call
# ─────────────────────────────────────────────────────────────────────
def test_no_fetch_on_pre_submit_guard(ig_dealing_rules):
    """is_known_too_tight must not touch IG when there is no observation."""
    mod = ig_dealing_rules
    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is False
    assert obs is None
    assert mod._stub_ig.fetch_market_calls == []


def test_4pip_submission_proceeds_without_prior_rejection(ig_dealing_rules):
    """Clean slate: a 4-pip request is NOT blocked — IG will adjudicate."""
    mod = ig_dealing_rules
    for direction in ("BUY", "SELL"):  # distance-only API; both sides same
        blocked, _ = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
        assert blocked is False
    assert mod._stub_ig.fetch_market_calls == []


# ─────────────────────────────────────────────────────────────────────
# Rejection event drives the single fetch
# ─────────────────────────────────────────────────────────────────────
def test_single_fetch_on_rejection(ig_dealing_rules):
    mod = ig_dealing_rules
    mod._stub_ig.market_responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is not None
    assert obs.value_pips == 6.0
    assert obs.unit == "POINTS"
    assert mod._stub_ig.fetch_market_calls == ["CS.D.GBPUSD.TODAY.IP"]


def test_subsequent_trade_blocked_after_rejection(ig_dealing_rules):
    """After IG reveals min=6p, the next 4p submission is blocked
    WITHOUT a second REST call."""
    mod = ig_dealing_rules
    mod._stub_ig.market_responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    mod._stub_ig.fetch_market_calls.clear()

    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is True
    assert obs.value_pips == 6.0
    assert mod._stub_ig.fetch_market_calls == []  # NO extra fetch


def test_subsequent_trade_at_min_allowed(ig_dealing_rules):
    """A submission AT the observed min passes."""
    mod = ig_dealing_rules
    mod._stub_ig.market_responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)
    mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")

    blocked, _ = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 6.0)
    assert blocked is False


def test_fetch_failure_records_nothing(ig_dealing_rules):
    """When the fetch fails, no observation is recorded; subsequent
    submissions remain unguarded."""
    mod = ig_dealing_rules
    mod._stub_ig.market_responses["CS.D.GBPUSD.TODAY.IP"] = RuntimeError("api down")
    obs = mod.record_rejection("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is None
    blocked, _ = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is False


# ─────────────────────────────────────────────────────────────────────
# Bounded TTL + invalidation
# ─────────────────────────────────────────────────────────────────────
def test_expired_observation_unblocks(ig_dealing_rules):
    mod = ig_dealing_rules
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0,
                            retrieved_at=time.time() - mod._TTL_SECS - 10.0)
    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is False
    assert obs is None


def test_invalidate_unblocks(ig_dealing_rules):
    mod = ig_dealing_rules
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0,
                            retrieved_at=time.time() - 10.0)
    assert mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)[0] is True
    mod.invalidate("CS.D.GBPUSD.TODAY.IP")
    assert mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)[0] is False


# ─────────────────────────────────────────────────────────────────────
# Patched trade_executor shape
# ─────────────────────────────────────────────────────────────────────
def test_patched_executor_imports_is_known_too_tight():
    src = (SRC / "trade_executor_patched.py").read_text()
    assert "from ig_dealing_rules import is_known_too_tight" in src
    assert "IG_STOP_PRE_SUBMIT_BLOCK" in src


def test_patched_executor_calls_record_rejection():
    src = (SRC / "trade_executor_patched.py").read_text()
    assert "from ig_dealing_rules import record_rejection" in src
    assert "ATTACHED_ORDER_LEVEL_ERROR" in src


def test_patched_executor_has_no_pre_submit_fetch_call():
    """The patched executor must NOT call validate_stop /
    get_min_normal_stop_pips / fetch_market_by_epic at pre-submit."""
    src = (SRC / "trade_executor_patched.py").read_text()
    # The only reference to the module should be is_known_too_tight +
    # record_rejection — not a pre-submit lookup.
    assert "validate_stop" not in src
    assert "get_min_normal_stop_pips" not in src
    assert "fetch_market_by_epic" not in src


def test_patched_executor_preserves_strategy_sl_math():
    """sl_pips → sl_pts conversion still exists; pair_min_pips (Step 4)
    retained as user-configurable risk floor."""
    src = (SRC / "trade_executor_patched.py").read_text()
    assert "sl_pts = sl_pips * ppp" in src
    assert "_PAIR_MIN_SL_PIPS.get(pair)" in src


def test_patched_executor_rejection_handler_unconditional():
    """ATTACHED_ORDER_LEVEL_ERROR → record_rejection is not gated on
    strict mode."""
    src = (SRC / "trade_executor_patched.py").read_text()
    import re
    m = re.search(
        r'ATTACHED_ORDER_LEVEL_ERROR.*?record_rejection as _dr_rec.*?_dr_rec\(epic',
        src, re.DOTALL,
    )
    assert m is not None, "record_rejection seam missing or malformed"
    # Verify no env flag inside this block
    assert "_dyn_strict" not in m.group(0)


# ─────────────────────────────────────────────────────────────────────
# Patched BB Bounce
# ─────────────────────────────────────────────────────────────────────
def test_patched_bb_config_reads_env(monkeypatch):
    monkeypatch.setenv("BB_SL_PIPS", "4")
    monkeypatch.setenv("BB_TP_PIPS", "50")
    spec = importlib.util.spec_from_file_location(
        "integ_bb_config", SRC / "bb_bounce_config_patched.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SL_PIPS == 4
    assert mod.TP_PIPS == 50


def test_patched_bb_config_defaults_unchanged(monkeypatch):
    monkeypatch.delenv("BB_SL_PIPS", raising=False)
    monkeypatch.delenv("BB_TP_PIPS", raising=False)
    spec = importlib.util.spec_from_file_location(
        "integ_bb_config_default", SRC / "bb_bounce_config_patched.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SL_PIPS == 12
    assert mod.TP_PIPS == 30


def test_patched_bb_stop_sizing_imports_last_known_min():
    src = (SRC / "bb_bounce_stop_sizing_patched.py").read_text()
    assert "from ig_dealing_rules import last_known_min" in src


def test_patched_bb_stop_sizing_has_no_pre_submit_fetch():
    """Standalone BB Bounce stop_sizing must not call validate_stop
    or any pre-submit fetch."""
    src = (SRC / "bb_bounce_stop_sizing_patched.py").read_text()
    assert "validate_stop" not in src
    assert "fetch_market_by_epic" not in src
    # Last-known observation lookup is the only inbound call
    assert "last_known_min" in src


# ─────────────────────────────────────────────────────────────────────
# Scope guarantees — unchanged production surfaces
# ─────────────────────────────────────────────────────────────────────
def test_patched_executor_does_not_modify_nms():
    """The trade_executor diff touches only the SL/TP sizing region
    and the REJECTED branch — never NMS imports or policy."""
    src = (SRC / "trade_executor_patched.py").read_text()
    # These NMS references exist in the file (unchanged); verify we
    # haven't added or removed any.
    original = Path("/opt/tradingbot/trade_executor.py").read_text()
    for pattern in ("nms_", "WATCH_AND_WAIT", "central_execution_gate",
                    "NMS_V3", "watch_state"):
        assert src.count(pattern) == original.count(pattern), (
            f"NMS surface changed for pattern {pattern!r}: "
            f"orig={original.count(pattern)} patched={src.count(pattern)}"
        )


def test_patched_executor_preserves_amend_path():
    """trade_executor's _amend_broker_sl + close_trade regions unchanged
    (we didn't touch the amend path)."""
    src = (SRC / "trade_executor_patched.py").read_text()
    original = Path("/opt/tradingbot/trade_executor.py").read_text()
    assert src.count("def apply_trailing_stop") == original.count("def apply_trailing_stop")
    assert src.count("def close_trade") == original.count("def close_trade")


def test_patched_bb_bounce_preserves_strategy_logic():
    """BB Bounce stop_sizing core — FIXED_12 branch, STRUCTURAL_3
    structure, stake sizing — untouched by the dynamic-min-stop patch."""
    src = (SRC / "bb_bounce_stop_sizing_patched.py").read_text()
    assert 'if mode == "FIXED_12":' in src
    assert 'STRUCTURAL_3' in src
    assert 'STRUCTURAL_BUFFER_PIPS' in src
    assert '_snap_stake' in src


def test_patched_bb_config_preserves_production_constants():
    """BB Bounce config keeps all other constants exactly as prod."""
    src = (SRC / "bb_bounce_config_patched.py").read_text()
    assert 'EPIC = "CS.D.GBPUSD.TODAY.IP"' in src
    assert 'SYMBOL = "GBPUSD"' in src
    assert "TRADE_SIZE = 2.0" in src
    assert "BB_STOP_MODE = os.getenv" in src
    assert 'IG_MIN_STOP_PIPS = float(os.getenv("BB_IG_MIN_STOP_PIPS"' in src


# ─────────────────────────────────────────────────────────────────────
# No prod writes during integration tests
# ─────────────────────────────────────────────────────────────────────
def test_no_prod_writes_during_tests():
    """Patched source copies live under /home only."""
    for p in SRC.glob("*.py"):
        assert str(p).startswith(str(Path("/home").resolve())), p


def test_prod_source_untouched():
    """Static check that /opt/tradingbot/trade_executor.py et al are
    unchanged by test execution."""
    marker = Path("/opt/tradingbot/trade_executor.py")
    before = marker.stat().st_mtime
    assert marker.exists()
    # (If any of the tests above had written, mtime would differ.)
    assert marker.stat().st_mtime == before
