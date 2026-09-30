"""Phase 3 tests — regime-keyed trade management.

Covers Phase 3 C1 (stamp + dispatch + STRONG). C2 (FORMING) and C3
(collision guards) extend this file in follow-up commits.

Run: pytest tests/unit/test_regime_mgmt.py -q
"""

from __future__ import annotations

import importlib
import os
import sys
from types import SimpleNamespace
from typing import Any, Dict

import pytest


def _reload(names):
    for n in names:
        if n in sys.modules:
            del sys.modules[n]


# ── Env fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mgmt_on(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", str(tmp_path / "matrix.jsonl"))
    monkeypatch.setenv("REGIME_MGMT_ENABLED", "1")
    monkeypatch.setenv("REGIME_MGMT_SCALE_TRIGGER_PIPS", "8")
    monkeypatch.setenv("REGIME_MGMT_STRONG_TRAIL_OFFSET_PIPS", "8")
    _reload(["regime_matrix", "trade_executor", "trade_manager"])
    import regime_matrix
    import trade_executor
    import trade_manager
    regime_matrix._reset_state_for_tests()
    trade_executor.EPIC_STATE.clear()
    return regime_matrix, trade_executor, trade_manager


@pytest.fixture
def mgmt_off(monkeypatch):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "0")
    monkeypatch.setenv("REGIME_MGMT_ENABLED", "0")
    _reload(["regime_matrix", "trade_executor", "trade_manager"])
    import regime_matrix
    import trade_executor
    import trade_manager
    trade_executor.EPIC_STATE.clear()
    return regime_matrix, trade_executor, trade_manager


# ── (a) Stamp mapping ─────────────────────────────────────────────────────

def _prime_regime(rm, label, n=3):
    for _ in range(n):
        rm.update("GBPUSD", label)


def test_stamp_maps_strong_trend_up_to_strong(mgmt_on):
    rm, te, _ = mgmt_on
    _prime_regime(rm, "STRONG_TREND_UP")
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    assert st["profile_id"] == "STRONG"
    assert st["regime_at_fire_effective"] == "STRONG_TREND_UP"


def test_stamp_maps_strong_trend_down_to_strong(mgmt_on):
    rm, te, _ = mgmt_on
    _prime_regime(rm, "STRONG_TREND_DOWN")
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    assert st["profile_id"] == "STRONG"


def test_stamp_maps_trend_forming_to_forming(mgmt_on):
    rm, te, _ = mgmt_on
    _prime_regime(rm, "TREND_FORMING_UP")
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    assert st["profile_id"] == "FORMING"
    _prime_regime(rm, "TREND_FORMING_DOWN")
    st2: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st2, "CS.D.GBPUSD.TODAY.IP")
    assert st2["profile_id"] == "FORMING"


def test_stamp_maps_range_rotation_to_range(mgmt_on):
    rm, te, _ = mgmt_on
    _prime_regime(rm, "RANGE_ROTATION")
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    assert st["profile_id"] == "RANGE"


def test_stamp_maps_chop_to_legacy(mgmt_on):
    rm, te, _ = mgmt_on
    _prime_regime(rm, "CHOP")
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    assert st["profile_id"] == "LEGACY"


def test_stamp_maps_unknown_to_legacy(mgmt_on):
    rm, te, _ = mgmt_on
    _prime_regime(rm, "MYSTERY_LABEL")
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    assert st["profile_id"] == "LEGACY"


def test_stamp_maps_no_matrix_yet_to_legacy(mgmt_on):
    rm, te, _ = mgmt_on
    # Matrix has never seen an update — effective_regime returns None.
    assert rm.effective_regime("GBPUSD") is None
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    assert st["profile_id"] == "LEGACY"
    assert st["regime_at_fire_effective"] is None


def test_stamp_no_op_when_flag_off(mgmt_off):
    _, te, _ = mgmt_off
    st: Dict[str, Any] = {}
    te._stamp_profile_at_fire(st, "CS.D.GBPUSD.TODAY.IP")
    # Flag off → helper leaves state untouched (no profile_id key set).
    assert "profile_id" not in st or st.get("profile_id") is None
    assert "regime_at_fire_effective" not in st or st.get("regime_at_fire_effective") is None


def test_orphan_restore_defaults_to_none_profile(mgmt_on):
    _, _, tm = mgmt_on
    # A restart-restored position dict never sees _stamp_profile_at_fire —
    # profile_id remains None (implicit LEGACY at dispatch time).
    st = {"active": True, "mode": "GBPUSD_STRUCTURE_BREAK_L"}
    meta: Dict[str, Any] = {"scaled_out": False}
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 5.0,
    )
    assert dispatched is False, (
        "orphan (profile_id=None) must fall through to legacy multiplex"
    )


# ── (b) Dispatch — profile trades bypass legacy, LEGACY runs legacy ───────

def test_dispatch_strong_profile_owns_tick(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    st = {"active": True, "profile_id": "STRONG", "entry_price": 13000.0,
          "direction": "BUY", "mode": "GBPUSD_STRUCTURE_BREAK_L", "tp": 30.0}
    meta: Dict[str, Any] = {"scaled_out": False}
    monkeypatch.setattr(tm, "_scale_out_50pct", lambda *a, **k: meta.__setitem__("scaled_out", True))
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0,
    )
    assert dispatched is True, "STRONG must return True (skip legacy multiplex)"
    assert meta["scaled_out"] is True


def test_dispatch_forming_profile_owns_tick(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    st = {"active": True, "profile_id": "FORMING", "entry_price": 13000.0,
          "direction": "BUY", "mode": "GBPUSD_TREND_V3_L", "tp": 30.0}
    meta: Dict[str, Any] = {"scaled_out": False}
    monkeypatch.setattr(tm, "_scale_out_50pct", lambda *a, **k: meta.__setitem__("scaled_out", True))
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0,
    )
    assert dispatched is True


def test_dispatch_range_profile_falls_through_to_legacy(mgmt_on):
    _, _, tm = mgmt_on
    st = {"active": True, "profile_id": "RANGE"}
    meta: Dict[str, Any] = {"scaled_out": False}
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0,
    )
    assert dispatched is False, (
        "RANGE must fall through so the range-scalp path and universal "
        "scale-out both fire (change no behaviour)"
    )


def test_dispatch_legacy_profile_falls_through(mgmt_on):
    _, _, tm = mgmt_on
    st = {"active": True, "profile_id": "LEGACY"}
    meta: Dict[str, Any] = {"scaled_out": False}
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0,
    )
    assert dispatched is False


def test_dispatch_no_op_when_flag_off(mgmt_off):
    _, _, tm = mgmt_off
    st = {"active": True, "profile_id": "STRONG"}
    meta: Dict[str, Any] = {"scaled_out": False}
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0,
    )
    assert dispatched is False, "flag off → legacy path everywhere"


# ── (c) STRONG trail monotonic, never against position ───────────────────

def test_strong_trail_engages_after_offset_buy(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            calls.append(new_sl_price) or True,
    )
    st = {"entry_price": 13000.0, "direction": "BUY",
          "mode": "GBPUSD_STRUCTURE_BREAK_L", "tp": 30.0,
          "profile_id": "STRONG"}
    meta = {"scaled_out": True, "be_amend_ok": True}
    # peak +7p, offset 8p → proposed_lock = max(0, 7-8) = 0 = prior → no amend
    tm._apply_strong_profile_runner_trail(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 7.0,
    )
    assert calls == []
    # peak +10p → proposed_lock = 2p → amend
    tm._apply_strong_profile_runner_trail(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0,
    )
    assert len(calls) == 1
    assert abs(calls[0] - (13000.0 + 2.0)) < 1e-6
    assert meta["profile_strong_trail_lock_pips"] == 2.0


def test_strong_trail_monotonic_never_regresses(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            calls.append(new_sl_price) or True,
    )
    st = {"entry_price": 13000.0, "direction": "BUY",
          "mode": "GBPUSD_TREND_V3_L", "tp": 30.0,
          "profile_id": "STRONG"}
    meta = {"scaled_out": True, "be_amend_ok": True,
            "profile_strong_trail_lock_pips": 15.0}
    # Peak drops back — proposed_lock (10-8=2) <= prior (15) → no amend
    tm._apply_strong_profile_runner_trail(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0,
    )
    assert calls == []
    assert meta["profile_strong_trail_lock_pips"] == 15.0


def test_strong_trail_never_moves_stop_against_sell(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            calls.append(new_sl_price) or True,
    )
    st = {"entry_price": 13000.0, "direction": "SELL",
          "mode": "GBPUSD_STRUCTURE_BREAK_S", "tp": 30.0,
          "profile_id": "STRONG"}
    meta = {"scaled_out": True, "be_amend_ok": True}
    # SELL: new SL = entry - lock. peak +20p, offset 8p → lock=12p → SL=13000-12=12988
    tm._apply_strong_profile_runner_trail(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 20.0,
    )
    assert len(calls) == 1
    assert abs(calls[0] - 12988.0) < 1e-6
    assert calls[0] < 13000.0, "SELL trail SL must be BELOW entry (in position's favour)"


def test_strong_trail_requires_scaled_out_and_be_amend_ok(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda *a, **k: calls.append(1) or True,
    )
    st = {"entry_price": 13000.0, "direction": "BUY",
          "mode": "GBPUSD_TREND_V3_L", "tp": 30.0}
    # No scaled_out → no amend
    tm._apply_strong_profile_runner_trail(
        "EPIC", "EPIC", st, {"scaled_out": False, "be_amend_ok": True},
        "GBPUSD", 1.0, 20.0,
    )
    assert calls == []
    # No be_amend_ok → no amend
    tm._apply_strong_profile_runner_trail(
        "EPIC", "EPIC", st, {"scaled_out": True, "be_amend_ok": False},
        "GBPUSD", 1.0, 20.0,
    )
    assert calls == []


# ── (d) FORMING ladder climbs rungs in order, TP never lowered, SL @ BE ──

def test_forming_ladder_init_amends_tp_to_rung_zero(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            calls.append({"sl": new_sl_price, "tp": current_tp_price}) or True,
    )
    st = {"entry_price": 13000.0, "direction": "BUY",
          "mode": "GBPUSD_TREND_V3_L", "tp": 30.0,
          "profile_id": "FORMING"}
    meta = {"scaled_out": True, "be_amend_ok": True}
    tm._apply_forming_profile_tp_ladder(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 8.5,
    )
    # First call → init: SL=BE (entry), TP=entry+30
    assert len(calls) == 1
    assert calls[0]["sl"] == 13000.0
    assert calls[0]["tp"] == 13030.0  # +30p rung 0
    assert meta["profile_forming_rung_idx"] == 0
    assert st["tp"] == 30.0


def test_forming_ladder_climbs_through_rungs_in_order(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            calls.append({"sl": new_sl_price, "tp": current_tp_price}) or True,
    )
    st = {"entry_price": 13000.0, "direction": "BUY",
          "mode": "GBPUSD_TREND_V3_L", "tp": 30.0,
          "profile_id": "FORMING"}
    meta = {"scaled_out": True, "be_amend_ok": True}
    # Init.
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0)
    # Below rung 0 → no advance.
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 25.0)
    assert meta["profile_forming_rung_idx"] == 0
    assert len(calls) == 1
    # Reach rung 0 (30p) → advance to rung 1 (50p).
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 30.0)
    assert meta["profile_forming_rung_idx"] == 1
    assert calls[1]["tp"] == 13050.0
    assert calls[1]["sl"] == 13000.0  # SL stays at BE
    # Reach rung 1 (50p) → advance to rung 2 (80p).
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 55.0)
    assert meta["profile_forming_rung_idx"] == 2
    assert calls[2]["tp"] == 13080.0
    # At top rung — no further amend.
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 90.0)
    assert meta["profile_forming_rung_idx"] == 2
    assert len(calls) == 3


def test_forming_ladder_never_lowers_tp(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            calls.append(current_tp_price) or True,
    )
    st = {"entry_price": 13000.0, "direction": "BUY", "tp": 30.0,
          "profile_id": "FORMING"}
    meta = {"scaled_out": True, "be_amend_ok": True,
            "profile_forming_rung_idx": 1}  # already at rung 1
    # Peak drops back to 25p — should NOT amend TP.
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 25.0)
    assert calls == []
    assert meta["profile_forming_rung_idx"] == 1


def test_forming_ladder_sell_direction(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            calls.append({"sl": new_sl_price, "tp": current_tp_price}) or True,
    )
    st = {"entry_price": 13000.0, "direction": "SELL", "tp": 30.0,
          "profile_id": "FORMING"}
    meta = {"scaled_out": True, "be_amend_ok": True}
    # SELL init: TP = entry - rung0 = 13000 - 30 = 12970
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 10.0)
    assert len(calls) == 1
    assert calls[0]["tp"] == 12970.0
    assert calls[0]["sl"] == 13000.0
    # SELL climb: at +30p peak → rung 1 TP = entry - 50 = 12950
    tm._apply_forming_profile_tp_ladder("EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 30.0)
    assert calls[1]["tp"] == 12950.0


def test_forming_ladder_requires_scaled_out_and_be_amend_ok(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda *a, **k: calls.append(1) or True,
    )
    st = {"entry_price": 13000.0, "direction": "BUY", "tp": 30.0,
          "profile_id": "FORMING"}
    tm._apply_forming_profile_tp_ladder(
        "EPIC", "EPIC", st, {"scaled_out": False, "be_amend_ok": True},
        "GBPUSD", 1.0, 40.0,
    )
    tm._apply_forming_profile_tp_ladder(
        "EPIC", "EPIC", st, {"scaled_out": True, "be_amend_ok": False},
        "GBPUSD", 1.0, 40.0,
    )
    assert calls == []


# ── (e/f) collision guards 5.1 / 5.2 ─────────────────────────────────────

def test_5_2_legacy_trail_helpers_skip_profile_managed(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda *a, **k: calls.append(1) or True,
    )
    st_forming = {"entry_price": 13000.0, "direction": "BUY",
                  "mode": "GBPUSD_STRUCTURE_BREAK_L", "tp": 30.0,
                  "profile_id": "FORMING"}
    st_strong = {"entry_price": 13000.0, "direction": "BUY",
                 "mode": "GBPUSD_BB_BOUNCE_L", "tp": 30.0,
                 "profile_id": "STRONG"}
    meta = {"scaled_out": True, "be_amend_ok": True}
    # Each legacy helper must early-return for profile-managed trades.
    tm._apply_trend_runner_trail("EPIC", "EPIC", st_forming, meta, "GBPUSD", 1.0, 20.0)
    tm._apply_bb_bounce_runner_trail("EPIC", "EPIC", st_strong, meta, "GBPUSD", 1.0, 20.0)
    tm._apply_bb_bounce_post_scale_floor("EPIC", "EPIC", st_strong, meta, "GBPUSD", 1.0, 20.0)
    tm._apply_structure_break_runner_trail("EPIC", "EPIC", st_forming, meta, "GBPUSD", 1.0, 20.0)
    tm._apply_news_cont_runner_trail("EPIC", "EPIC", st_forming, meta, "GBPUSD", 1.0, 20.0)
    assert calls == [], (
        f"legacy helpers must not amend for profile-managed trades: {calls}"
    )


def test_5_2_legacy_trails_still_fire_for_range_and_legacy(mgmt_on, monkeypatch):
    _, _, tm = mgmt_on
    calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda *a, **k: calls.append(1) or True,
    )
    monkeypatch.setenv("BB_BOUNCE_L_RUNNER_TRAIL_ENABLED", "1")
    st_range = {"entry_price": 13000.0, "direction": "BUY",
                "mode": "GBPUSD_BB_BOUNCE_L", "tp": 30.0,
                "profile_id": "RANGE"}
    meta = {"scaled_out": True, "be_amend_ok": True}
    tm._apply_bb_bounce_runner_trail("EPIC", "EPIC", st_range, meta, "GBPUSD", 1.0, 20.0)
    assert len(calls) == 1, "RANGE profile must still see legacy trail (change no behaviour)"

    calls.clear()
    st_legacy = dict(st_range)
    st_legacy["profile_id"] = "LEGACY"
    meta_legacy = {"scaled_out": True, "be_amend_ok": True}
    tm._apply_bb_bounce_runner_trail("EPIC", "EPIC", st_legacy, meta_legacy, "GBPUSD", 1.0, 20.0)
    assert len(calls) == 1, "LEGACY profile must still see legacy trail"

    calls.clear()
    st_none = dict(st_range)
    st_none.pop("profile_id", None)
    meta_none = {"scaled_out": True, "be_amend_ok": True}
    tm._apply_bb_bounce_runner_trail("EPIC", "EPIC", st_none, meta_none, "GBPUSD", 1.0, 20.0)
    assert len(calls) == 1, "None (orphan) profile must still see legacy trail"


def test_5_1_universal_scale_out_skips_profile_managed():
    """Universal SCALE_OUT_AT_10P must not fire on profile-managed
    trades. Verified via source introspection — the guard lives in
    the tick body of _monitor_profit_protection, not a stand-alone
    function, so a full end-to-end test would require driving the
    whole monitor loop. A regression removing the guard fails this
    test.
    """
    src = open("/opt/tradingbot/trade_manager.py").read()
    assert "_universal_scale_gated" in src, "5.1 guard variable missing"
    # The guard must be part of the scale-out conditional.
    idx = src.find("SCALE_OUT_AT_10P_ENABLED and not _universal_scale_gated")
    assert idx > 0, "5.1 guard not wired into the scale-out condition"


def test_exactly_one_scale_out_with_both_systems_live(mgmt_on, monkeypatch):
    """Profile-managed trade: scale-out fires exactly once via the
    profile dispatcher; universal path is gated off; the shared meta
    key prevents any double-scale.
    """
    _, _, tm = mgmt_on
    scale_calls = []
    monkeypatch.setattr(
        tm, "_scale_out_50pct",
        lambda pos_key, pair, ppp, meta: (
            scale_calls.append({"pos_key": pos_key}),
            meta.__setitem__("scaled_out", True),
            meta.__setitem__("be_amend_ok", True),
        ),
    )
    st = {"active": True, "profile_id": "STRONG", "entry_price": 13000.0,
          "direction": "BUY", "mode": "GBPUSD_STRUCTURE_BREAK_L", "tp": 30.0}
    meta = {"scaled_out": False}
    # Tick 1 — best_pnl at 8p (trigger). Profile dispatches scale.
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 8.0,
    )
    assert dispatched is True
    assert len(scale_calls) == 1
    # Tick 2 — best_pnl higher. Scale must NOT fire again.
    dispatched = tm._dispatch_profile_management(
        "EPIC", "EPIC", st, meta, "GBPUSD", 1.0, 15.0,
    )
    assert dispatched is True
    assert len(scale_calls) == 1, (
        "shared meta['scaled_out'] must prevent double-scale"
    )


# ── (g) 5.5 software-BE skips profile trades + kill-switch works ─────────

def test_5_5_software_be_skips_profile_managed():
    """Introspect autobot.py to confirm the software-BE exempt check
    includes profile-managed trades. Regression that removes the guard
    fails this test.
    """
    src = open("/opt/tradingbot/autobot.py").read()
    assert "_sbe_profile_managed" in src, "5.5 profile guard missing"
    # And the exemption uses the OR chain in _be_exempt.
    assert "or _sbe_profile_managed" in src


def test_5_5_kill_switch_exists():
    """SOFTWARE_BE_ENABLED already exists (pre-Phase 3); the standalone
    race for profile trades is what the profile guard addresses. This
    test confirms the kill-switch is intact.
    """
    src = open("/opt/tradingbot/autobot.py").read()
    assert 'SOFTWARE_BE_ENABLED = (os.getenv("SOFTWARE_BE_ENABLED"' in src


# ── (h) flag OFF byte-identical ──────────────────────────────────────────

def test_flag_off_dispatch_never_returns_true(mgmt_off):
    _, _, tm = mgmt_off
    for pid in ("STRONG", "FORMING", "RANGE", "LEGACY", None):
        st = {"active": True, "profile_id": pid}
        assert tm._dispatch_profile_management(
            "EPIC", "EPIC", st, {"scaled_out": False}, "GBPUSD", 1.0, 100.0,
        ) is False, f"flag-off dispatch returned True for profile={pid}"


# ── (i) Fix 2 — STRONG runner TP release ─────────────────────────────────

def _prime_scale_out(tm, monkeypatch, profile_id, entry=13000.0):
    """Prime _scale_out_50pct for a release-path unit test.

    Monkeypatches the IG-touching primitives to noop-with-ACCEPTED so
    _scale_out_50pct reaches the SL/TP amend and we can inspect what
    limit price was passed. Returns amend_calls list.
    """
    amend_calls = []
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price:
            amend_calls.append(
                {"pos_key": pos_key, "new_sl": new_sl_price,
                 "tp": current_tp_price}
            ) or True,
    )

    import close_sb_now as _cs
    monkeypatch.setattr(
        _cs, "_close_position_by_deal",
        lambda deal_id, close_dir, size: {"dealStatus": "ACCEPTED", "level": entry},
        raising=False,
    )

    # Silence the Telegram best-effort import inside _scale_out_50pct.
    import telegram_alerts
    monkeypatch.setattr(
        telegram_alerts, "send_partial_exit_alert",
        lambda **kwargs: None,
        raising=False,
    )
    return amend_calls


def _make_scale_state(profile_id, entry=13000.0, direction="BUY", tp_pips=30.0):
    return {
        "active": True,
        "dealId": "DEAL123",
        "deal_id": "DEAL123",
        "direction": direction,
        "entry_price": entry,
        "size": 2.0,
        "last_mid": entry,
        "profile_id": profile_id,
        "tp": tp_pips,
        "mode": "GBPUSD_TREND_V3_L",
    }


def test_fix2_release_amends_tp_at_sentinel_for_strong_when_knob_on(mgmt_on, monkeypatch):
    _, te, tm = mgmt_on
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE", True)
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE_PIPS", 200.0)
    st = _make_scale_state("STRONG")
    te.EPIC_STATE["EPIC|GBPUSD_TREND_V3_L"] = st
    amend_calls = _prime_scale_out(tm, monkeypatch, "STRONG")

    tm._scale_out_50pct("EPIC|GBPUSD_TREND_V3_L", "GBPUSD", 1.0, {})

    assert len(amend_calls) == 1, "single BE+release amend expected"
    call = amend_calls[0]
    # BE amend: SL at entry.
    assert abs(call["new_sl"] - 13000.0) < 1e-6
    # Release: TP at entry + 200p × ppp = 13200.0 (BUY).
    assert abs(call["tp"] - 13200.0) < 1e-6, (
        f"STRONG+knob-on must release TP to sentinel; got tp={call['tp']}"
    )
    # st["tp"] is updated to sentinel so downstream ratchets preserve it.
    assert abs(float(st["tp"]) - 200.0) < 1e-6
    assert abs(float(st["tp_at_fire"]) - 30.0) < 1e-6, (
        "tp_at_fire snapshot preserves the pre-release fire-time TP"
    )


def test_fix2_release_not_called_for_forming(mgmt_on, monkeypatch):
    _, te, tm = mgmt_on
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE", True)  # even ON
    st = _make_scale_state("FORMING")
    te.EPIC_STATE["EPIC|GBPUSD_TREND_V3_L"] = st
    amend_calls = _prime_scale_out(tm, monkeypatch, "FORMING")

    tm._scale_out_50pct("EPIC|GBPUSD_TREND_V3_L", "GBPUSD", 1.0, {})

    assert len(amend_calls) == 1
    # FORMING: TP stays at fire-time (30p from entry → 13030.0 for BUY).
    assert abs(amend_calls[0]["tp"] - 13030.0) < 1e-6
    assert abs(float(st["tp"]) - 30.0) < 1e-6  # unchanged
    assert st.get("tp_at_fire") is None


def test_fix2_release_not_called_for_legacy(mgmt_on, monkeypatch):
    _, te, tm = mgmt_on
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE", True)
    st = _make_scale_state("LEGACY")
    te.EPIC_STATE["EPIC|GBPUSD_TREND_V3_L"] = st
    amend_calls = _prime_scale_out(tm, monkeypatch, "LEGACY")

    tm._scale_out_50pct("EPIC|GBPUSD_TREND_V3_L", "GBPUSD", 1.0, {})

    assert len(amend_calls) == 1
    assert abs(amend_calls[0]["tp"] - 13030.0) < 1e-6
    assert abs(float(st["tp"]) - 30.0) < 1e-6


def test_fix2_release_not_called_when_knob_off(mgmt_on, monkeypatch):
    _, te, tm = mgmt_on
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE", False)  # OFF
    st = _make_scale_state("STRONG")
    te.EPIC_STATE["EPIC|GBPUSD_TREND_V3_L"] = st
    amend_calls = _prime_scale_out(tm, monkeypatch, "STRONG")

    tm._scale_out_50pct("EPIC|GBPUSD_TREND_V3_L", "GBPUSD", 1.0, {})

    assert len(amend_calls) == 1
    # Knob OFF: STRONG runner keeps fire-time TP → 13030.0 for BUY.
    assert abs(amend_calls[0]["tp"] - 13030.0) < 1e-6, (
        "knob-off must be byte-identical to pre-Fix-2 behaviour"
    )
    assert abs(float(st["tp"]) - 30.0) < 1e-6
    assert st.get("tp_at_fire") is None


def test_fix2_release_sell_direction_sentinel_below_entry(mgmt_on, monkeypatch):
    _, te, tm = mgmt_on
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE", True)
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE_PIPS", 200.0)
    st = _make_scale_state("STRONG", direction="SELL")
    te.EPIC_STATE["EPIC|GBPUSD_TREND_V3_S"] = st
    amend_calls = _prime_scale_out(tm, monkeypatch, "STRONG")

    tm._scale_out_50pct("EPIC|GBPUSD_TREND_V3_S", "GBPUSD", 1.0, {})

    assert len(amend_calls) == 1
    # SELL: sentinel is entry − 200 = 12800.0. Must be BELOW entry.
    assert abs(amend_calls[0]["tp"] - 12800.0) < 1e-6
    assert amend_calls[0]["tp"] < 13000.0


def test_fix2_release_amend_fail_page_line_augmented(mgmt_on, monkeypatch):
    """When BE+release amend fails twice, the operator page names the
    TP-release attempt so a silent release-fail can't hide behind the
    original BE-fail wording.
    """
    _, te, tm = mgmt_on
    monkeypatch.setattr(tm, "REGIME_MGMT_STRONG_TP_RELEASE", True)

    # Force _amend_broker_sl to reject both times.
    monkeypatch.setattr(
        tm, "_amend_broker_sl",
        lambda pos_key, new_sl_price, current_tp_price: False,
    )
    pages = []
    import telegram_alerts
    monkeypatch.setattr(
        telegram_alerts, "send_error_alert",
        lambda msg: pages.append(msg),
        raising=False,
    )
    monkeypatch.setattr(
        telegram_alerts, "send_partial_exit_alert",
        lambda **kwargs: None,
        raising=False,
    )
    import close_sb_now as _cs
    monkeypatch.setattr(
        _cs, "_close_position_by_deal",
        lambda deal_id, close_dir, size: {"dealStatus": "ACCEPTED", "level": 13000.0},
        raising=False,
    )

    st = _make_scale_state("STRONG")
    te.EPIC_STATE["EPIC|GBPUSD_TREND_V3_L"] = st
    tm._scale_out_50pct(
        "EPIC|GBPUSD_TREND_V3_L", "GBPUSD", 1.0,
        {"last_amend_reject_reason": "MARKET_CLOSED"},
    )

    assert pages, "operator must be paged on BE+release amend failure"
    assert "TP release attempted" in pages[0]
    assert "ORIGINAL TP" in pages[0]
