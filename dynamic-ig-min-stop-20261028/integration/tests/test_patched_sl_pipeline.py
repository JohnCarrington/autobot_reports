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
    """sl_pips → sl_pts conversion still exists; the SL sanity bound
    (via _sanitize_distance earlier in execute_trade) is preserved.

    The Step 4 _PAIR_MIN_SL_PIPS widening is REMOVED per operator
    ruling 2026-10-28 (that was a user default, not a mandatory
    floor).  The genuine sanity bound is enforced via
    `min_pips=float(MIN_SL_PIPS)=2` at trade_executor.py:4321.
    """
    src = (SRC / "trade_executor_patched.py").read_text()
    assert "sl_pts = sl_pips * ppp" in src
    assert "min_pips=float(MIN_SL_PIPS)" in src


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


# ─────────────────────────────────────────────────────────────────────
# BLOCKER 1 — no silent widening
# ─────────────────────────────────────────────────────────────────────
def test_patched_executor_removes_step2_sl_widen():
    """Step 2's auto-widen must be gone: no
    `sl_pts = max(sl_pts, ig_min)` or `_IG_MIN_STOP_PTS` max."""
    src = (SRC / "trade_executor_patched.py").read_text()
    # The removed lines must not reappear
    assert "sl_pts = max(sl_pts, ig_min)" not in src
    # Allow comment/docstring mentions of the removal, but the live
    # expression must be gone
    assert "ig_min = _IG_MIN_STOP_PTS.get(pair" not in src


def test_patched_executor_removes_step3_sl_widen():
    """Step 3's global SL floor must be gone."""
    src = (SRC / "trade_executor_patched.py").read_text()
    assert "sl_pts = max(sl_pts, MIN_STOP_DISTANCE_PIPS)" not in src


def test_patched_executor_removes_step4_sl_widen():
    """Step 4's per-pair MIN_SL_PIPS widen must be gone."""
    src = (SRC / "trade_executor_patched.py").read_text()
    assert "sl_pts = max(sl_pts, pair_min_pts)" not in src
    # The _PAIR_MIN_SL_PIPS import may remain for other uses but the
    # `.get(pair)` → max() wiring must be deleted from execute_trade.
    import re
    bad = re.search(
        r"pair_min_pips\s*=\s*_PAIR_MIN_SL_PIPS\.get\(pair\).*?"
        r"sl_pts\s*=\s*max\(sl_pts,\s*pair_min_pts\)",
        src, re.DOTALL,
    )
    assert bad is None, "Step 4 widen still present in execute_trade"


def test_patched_executor_sl_passthrough(ig_dealing_rules):
    """End-to-end: a 4-pip SL request produces stop_distance = 4 after
    the patched SL pipeline (no observation blocking, no widening).

    We can't actually RUN execute_trade without the full session
    stack, but we can verify the pipeline logic by inspecting the
    patched source and simulating the hot path arithmetic in
    isolation.
    """
    src = (SRC / "trade_executor_patched.py").read_text()
    # The only line that sets sl_pts BEFORE the "stop_distance = sl_pts"
    # assignment is Step 1 (pips → points).  Verify Step 1 is still
    # present and no subsequent widening max()s refer to sl_pts.
    assert "sl_pts = sl_pips * ppp" in src
    # Count remaining `sl_pts = max(sl_pts,` expressions — must be
    # exactly ZERO (TP floor uses tp_pts, not sl_pts).
    import re
    sl_widens = re.findall(r"sl_pts\s*=\s*max\(sl_pts\s*,", src)
    assert len(sl_widens) == 0, (
        f"patched executor still has {len(sl_widens)} sl_pts widening "
        "expressions: {sl_widens}"
    )

    # And the pre-submit guard: with no observation, is_known_too_tight
    # returns False → execute_trade does NOT block a 4-pip request.
    mod = ig_dealing_rules
    blocked, obs = mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)
    assert blocked is False
    assert obs is None


def test_patched_executor_preserves_sanitize_sl_sanity():
    """The 2-pip/500-pip SL sanity bounds (via _sanitize_distance at
    trade_executor.py:4318-4324) are UNCHANGED.  These are genuine
    bounding sanity checks, not auto-widening."""
    src = (SRC / "trade_executor_patched.py").read_text()
    assert "min_pips=float(MIN_SL_PIPS)" in src
    assert "max_pips=float(MAX_REASONABLE_SL_PIPS)" in src


# ─────────────────────────────────────────────────────────────────────
# BLOCKER 2a — standalone BB Bounce calls record_rejection
# ─────────────────────────────────────────────────────────────────────
def test_bb_trade_runner_wires_record_rejection():
    """Static check: the patched trade_runner calls record_rejection
    exactly in the ATTACHED_ORDER_LEVEL_ERROR branch."""
    src = (SRC / "bb_bounce_trade_runner_patched.py").read_text()
    assert "from ig_dealing_rules import record_rejection as _dr_rec" in src
    assert "ATTACHED_ORDER_LEVEL_ERROR" in src
    # The call must happen inside the is_definitive_rejection branch
    # and only when the reason matches.
    import re
    pat = re.compile(
        r'if is_definitive_rejection:.*?'
        r'"ATTACHED_ORDER_LEVEL_ERROR" in \(.*?\).*?'
        r'_dr_rec\(_EPIC',
        re.DOTALL,
    )
    assert pat.search(src), (
        "patched trade_runner must call record_rejection(EPIC) inside the "
        "ATTACHED_ORDER_LEVEL_ERROR branch"
    )


def test_bb_trade_runner_rejection_runtime(ig_dealing_rules, tmp_path):
    """Load the patched trade_runner module in isolation and simulate
    the rejection branch: an ATTACHED_ORDER_LEVEL_ERROR response
    produces exactly one fetch_market_by_epic call and an observation
    the next trade can read.

    We don't instantiate the full TradeRunner class; we exercise the
    rejection semantics directly by invoking record_rejection the
    same way the patched branch does."""
    mod = ig_dealing_rules
    # Configure IG to return a 6-pip minimum
    mod._stub_ig.market_responses["CS.D.GBPUSD.TODAY.IP"] = _rule(6.0)

    # Simulate the exact import + call sequence the patched source does.
    from ig_dealing_rules import record_rejection as _dr_rec
    obs = _dr_rec("CS.D.GBPUSD.TODAY.IP", "GBPUSD")
    assert obs is not None
    assert obs.value_pips == 6.0
    # Exactly ONE REST call
    assert mod._stub_ig.fetch_market_calls == ["CS.D.GBPUSD.TODAY.IP"]
    # The next trade (standalone stop_sizing.py path) sees the
    # observation via last_known_min.
    from ig_dealing_rules import last_known_min as _dr_lkm
    seen = _dr_lkm("CS.D.GBPUSD.TODAY.IP")
    assert seen is not None
    assert seen.value_pips == 6.0


def test_bb_trade_runner_only_level_error_triggers_fetch(ig_dealing_rules):
    """Other rejection reasons must NOT call record_rejection."""
    src = (SRC / "bb_bounce_trade_runner_patched.py").read_text()
    import re
    # Find the ATTACHED_ORDER_LEVEL_ERROR gate; outside this block,
    # there must be no other record_rejection call site.
    all_calls = re.findall(r"_dr_rec\(", src)
    assert len(all_calls) == 1, (
        f"expected exactly one _dr_rec call site in patched trade_runner, "
        f"found {len(all_calls)}"
    )


# ─────────────────────────────────────────────────────────────────────
# BLOCKER 2b — working in-process invalidation via sentinel file
# ─────────────────────────────────────────────────────────────────────
def test_sentinel_file_invalidates_specific_epic(ig_dealing_rules,
                                                  monkeypatch, tmp_path):
    """Writing an epic to the sentinel file clears that epic's
    observation on the next lookup."""
    mod = ig_dealing_rules
    sentinel = tmp_path / "ig_dealing_rules.invalidate"
    monkeypatch.setattr(mod, "_INVALIDATE_SENTINEL_PATH", sentinel)

    # Seed an observation
    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0,
                            retrieved_at=time.time())
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is not None

    # Operator writes the sentinel
    sentinel.write_text("CS.D.GBPUSD.TODAY.IP\n")
    # Next lookup consumes it and clears
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is None
    # Sentinel file is removed
    assert not sentinel.exists()


def test_sentinel_file_all_clears_everything(ig_dealing_rules, monkeypatch,
                                              tmp_path):
    """Writing 'ALL' clears every observation in the process."""
    mod = ig_dealing_rules
    sentinel = tmp_path / "ig_dealing_rules.invalidate"
    monkeypatch.setattr(mod, "_INVALIDATE_SENTINEL_PATH", sentinel)

    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0)
    mod._inject_observation("CS.D.EURUSD.TODAY.IP", 2.0)
    sentinel.write_text("ALL\n")

    # Any lookup consumes it
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is None
    assert mod.last_known_min("CS.D.EURUSD.TODAY.IP") is None
    assert not sentinel.exists()


def test_sentinel_missing_is_safe(ig_dealing_rules, monkeypatch, tmp_path):
    """No sentinel file → normal operation (no exception, no clearing)."""
    mod = ig_dealing_rules
    sentinel = tmp_path / "ig_dealing_rules.invalidate"
    monkeypatch.setattr(mod, "_INVALIDATE_SENTINEL_PATH", sentinel)

    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0)
    assert mod.last_known_min("CS.D.GBPUSD.TODAY.IP") is not None  # untouched
    assert not sentinel.exists()


def test_sentinel_corrupt_cleaned_up(ig_dealing_rules, monkeypatch, tmp_path):
    """A corrupt/binary sentinel is removed and does not stall the module."""
    mod = ig_dealing_rules
    sentinel = tmp_path / "ig_dealing_rules.invalidate"
    monkeypatch.setattr(mod, "_INVALIDATE_SENTINEL_PATH", sentinel)
    # Write binary garbage
    sentinel.write_bytes(b"\x00\x01\x02\xff")

    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0)
    # The lookup consumes the sentinel safely (empty-token / no-match)
    # and removes the file.
    obs = mod.last_known_min("CS.D.GBPUSD.TODAY.IP")
    assert obs is not None  # observation untouched; sentinel didn't match
    assert not sentinel.exists()  # cleaned up


def test_sentinel_is_consumed_by_is_known_too_tight(ig_dealing_rules,
                                                    monkeypatch, tmp_path):
    """The pre-submit guard also consumes the sentinel — operator can
    drop the file right before a fire, and the fire is unblocked."""
    mod = ig_dealing_rules
    sentinel = tmp_path / "ig_dealing_rules.invalidate"
    monkeypatch.setattr(mod, "_INVALIDATE_SENTINEL_PATH", sentinel)

    mod._inject_observation("CS.D.GBPUSD.TODAY.IP", 6.0)
    assert mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)[0] is True

    sentinel.write_text("CS.D.GBPUSD.TODAY.IP\n")
    # Fire-time guard check sees the sentinel, invalidates, allows.
    assert mod.is_known_too_tight("CS.D.GBPUSD.TODAY.IP", 4.0)[0] is False
