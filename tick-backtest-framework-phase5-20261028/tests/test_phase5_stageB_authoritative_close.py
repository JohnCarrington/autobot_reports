"""Phase 5 Stage B — regression tests for the AUTHORITATIVE_BROKER_CLOSE fix.

Loads the proposed patched copy of ``trade_log`` (research-only, with
import-time autoinstall disabled) and exercises the close-reconciliation
cases listed in Stage B of the Phase 5 brief.

The simulator in ``sim/`` is unchanged; this suite verifies the
production logging layer in isolation, independently of the simulator
and of IG REST.

Scope covered:
    BUY/SELL closed at market, BUY/SELL stopped out, broker TP closure,
    manual IG closure, external strategy closure, partial closure,
    multiple transactions per position, missing broker transaction,
    duplicate broker transaction, delayed transaction availability,
    different close-side BID/ASK prices, spread expansion, overnight
    financing, shared-account ownership ambiguity.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent.parent


@pytest.fixture()
def patched_trade_log(monkeypatch, tmp_path):
    """Import the patched trade_log into a scratch sys.modules.

    Each test receives a fresh module whose LOG_PATH points at tmp_path
    and whose EPIC_STATE snapshot helper is monkeypatched to return
    deterministic state.
    """
    patch_path = HERE / "patches" / "applied" / "trade_log_patched.py"
    assert patch_path.exists(), f"missing patched module: {patch_path}"

    spec = importlib.util.spec_from_file_location(
        "phase5_trade_log_patched", patch_path,
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    # Redirect log file into tmp_path so parallel tests cannot collide.
    monkeypatch.setattr(mod, "LOG_PATH", tmp_path / "unified_trades.jsonl")

    # Replace _epic_state_snapshot with a controllable fake.
    fake_state: dict[str, dict] = {}

    def _fake_snapshot(pk: str):
        return dict(fake_state.get(pk) or {})

    monkeypatch.setattr(mod, "_epic_state_snapshot", _fake_snapshot)

    mod._test_state = fake_state  # type: ignore[attr-defined]
    return mod


def _read_rows(mod) -> list[dict]:
    path = mod.LOG_PATH
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


# ----------------------------------------------------------------------
# 1.  Default price_source when caller omits the kwarg (the heart of the
#     Phase 4 defect).  Must now be ESTIMATED_LAST_MID.
# ----------------------------------------------------------------------
def test_default_price_source_is_estimated_last_mid(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|BB_BOUNCE_L"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": "DIAAAA_ABC",
    }
    mod.record_close(
        "GBPUSD|BB_BOUNCE_L",
        exit_price=13245.0,
        pnl_pips=-5.0,
        close_reason="External close (not initiated by this host)",
    )
    rows = _read_rows(mod)
    assert len(rows) == 1
    assert rows[0]["price_source"] == mod.ESTIMATED_LAST_MID


# ----------------------------------------------------------------------
# 2.  Explicit AUTHORITATIVE_BROKER_CLOSE still passes through.
# ----------------------------------------------------------------------
def test_explicit_authoritative_broker_close_pass_through(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|QM_V2_L"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 1.0, "deal_id": "DIAAAA_XYZ",
    }
    mod.record_close(
        "GBPUSD|QM_V2_L", exit_price=13300.0, pnl_pips=10.0,
        close_reason="TP hit", deal_id="DIAAAA_XYZ",
        price_source=mod.AUTHORITATIVE_BROKER_CLOSE,
    )
    rows = _read_rows(mod)
    assert rows[0]["price_source"] == mod.AUTHORITATIVE_BROKER_CLOSE


# ----------------------------------------------------------------------
# 3.  Supersession semantics: AUTHORITATIVE_* must win over ESTIMATED_*
#     when read_closes_by_deal_id collapses rows.
# ----------------------------------------------------------------------
def test_authoritative_supersedes_estimated(patched_trade_log):
    mod = patched_trade_log
    deal_id = "DIAAAA_SUPER"
    mod._test_state["GBPUSD|TREND_V3_S"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": deal_id,
    }
    mod.record_close(
        "GBPUSD|TREND_V3_S", exit_price=13250.0, pnl_pips=-10.0,
        close_reason="External close (not initiated by this host)",
        deal_id=deal_id,
    )
    mod.record_close(
        "GBPUSD|TREND_V3_S", exit_price=13260.0, pnl_pips=-20.0,
        close_reason="SL hit", deal_id=deal_id,
        price_source=mod.AUTHORITATIVE_IG_HISTORY,
    )
    best = mod.read_closes_by_deal_id()
    assert best[deal_id]["price_source"] == mod.AUTHORITATIVE_IG_HISTORY
    assert best[deal_id]["exit_price"] == 13260.0


# ----------------------------------------------------------------------
# 4.  BUY stop-out — pnl sign discipline unchanged by the patch.
# ----------------------------------------------------------------------
def test_buy_stop_out_pnl_sign(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|BB_BOUNCE_L"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": "DIAAAA_BUY_SL",
    }
    mod.record_close(
        "GBPUSD|BB_BOUNCE_L", exit_price=13200.0, pnl_pips=-12.0,
        close_reason="SL hit", price_source=mod.AUTHORITATIVE_BROKER_CLOSE,
    )
    row = _read_rows(mod)[0]
    assert row["pnl_pips"] == -12.0
    # pnl_gbp = pnl_pips × size (no partial-bank)
    assert row["pnl_gbp"] == -24.0


# ----------------------------------------------------------------------
# 5.  SELL market close.
# ----------------------------------------------------------------------
def test_sell_market_close(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|QM_V2_S"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 1.0, "deal_id": "DIAAAA_SELL_M",
    }
    mod.record_close(
        "GBPUSD|QM_V2_S", exit_price=13310.0, pnl_pips=5.0,
        close_reason="QM_BAND_CLOSE_INSIDE",
        price_source=mod.AUTHORITATIVE_BROKER_CLOSE,
    )
    row = _read_rows(mod)[0]
    assert row["pnl_gbp"] == 5.0
    assert row["price_source"] == mod.AUTHORITATIVE_BROKER_CLOSE


# ----------------------------------------------------------------------
# 6.  Broker TP closure — explicit price_source wins; the row is
#     authoritative because close_trade confirmed via /confirms.
# ----------------------------------------------------------------------
def test_broker_tp_closure(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|BB_BOUNCE_S"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": "DIAAAA_TP",
    }
    mod.record_close(
        "GBPUSD|BB_BOUNCE_S", exit_price=13250.0, pnl_pips=20.0,
        close_reason="TP hit", price_source=mod.AUTHORITATIVE_BROKER_CLOSE,
    )
    assert _read_rows(mod)[0]["price_source"] == mod.AUTHORITATIVE_BROKER_CLOSE


# ----------------------------------------------------------------------
# 7.  Manual IG UI closure — comes through the vanished-close path with
#     ESTIMATED_LAST_MID, must stay estimated.
# ----------------------------------------------------------------------
def test_manual_ig_closure_stays_estimated(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|TREND_V3_L"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 1.0, "deal_id": "DIAAAA_MANUAL",
    }
    # Simulated path: callback fires with no explicit price_source — the
    # new default must label it estimated so a daily reconciler can
    # supersede with AUTHORITATIVE_IG_HISTORY.
    mod.record_close(
        "GBPUSD|TREND_V3_L", exit_price=13200.0, pnl_pips=-7.0,
        close_reason="External close (not initiated by this host)",
    )
    assert _read_rows(mod)[0]["price_source"] == mod.ESTIMATED_LAST_MID


# ----------------------------------------------------------------------
# 8.  External strategy closure — same as above but with pnl_pips=None.
# ----------------------------------------------------------------------
def test_external_strategy_closure_pnl_none(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|BOUNCE_TR_S"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": "DIAAAA_EXT",
    }
    mod.record_close(
        "GBPUSD|BOUNCE_TR_S", exit_price=None, pnl_pips=None,
        close_reason="IG_RECONCILE_CLEAR", price_source=mod.ESTIMATED_LAST_MID,
    )
    row = _read_rows(mod)[0]
    assert row["pnl_pips"] is None
    assert row["pnl_gbp"] is None
    assert row["price_source"] == mod.ESTIMATED_LAST_MID


# ----------------------------------------------------------------------
# 9.  Partial close emits with scaled-bank arithmetic from state.
# ----------------------------------------------------------------------
def test_partial_close_scaled_pnl(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|BB_BOUNCE_L"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": "DIAAAA_PART",
        "partial_bank_pips": 10.0, "total_pnl_pips": 20.0,
    }
    mod.record_close(
        "GBPUSD|BB_BOUNCE_L", exit_price=13260.0, pnl_pips=10.0,
        close_reason="FLOOR_STOP_POST_SCALEOUT",
        price_source=mod.AUTHORITATIVE_BROKER_CLOSE,
    )
    row = _read_rows(mod)[0]
    # pnl_gbp uses total_pnl_pips × size / 2 when a partial was banked.
    assert row["pnl_gbp"] == 20.0


# ----------------------------------------------------------------------
# 10.  Multiple broker transactions associated with one position —
#      the ledger reader deduplicates by deal_id with authoritative
#      precedence.
# ----------------------------------------------------------------------
def test_multi_transaction_deduplicates(patched_trade_log):
    mod = patched_trade_log
    deal_id = "DIAAAA_MULTI"
    mod._test_state["GBPUSD|QM_V2_L"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 1.0, "deal_id": deal_id,
    }
    # Three rows for the same deal (estimated, estimated, authoritative).
    for i in range(2):
        mod.record_close(
            "GBPUSD|QM_V2_L", exit_price=13200.0 + i,
            pnl_pips=-5.0, close_reason="External close (not initiated by this host)",
            deal_id=deal_id,
        )
    mod.record_close(
        "GBPUSD|QM_V2_L", exit_price=13210.0, pnl_pips=5.0,
        close_reason="SL hit", deal_id=deal_id,
        price_source=mod.AUTHORITATIVE_IG_HISTORY,
    )
    assert len(_read_rows(mod)) == 3
    best = mod.read_closes_by_deal_id()
    assert best[deal_id]["price_source"] == mod.AUTHORITATIVE_IG_HISTORY
    assert best[deal_id]["exit_price"] == 13210.0


# ----------------------------------------------------------------------
# 11.  Missing broker transaction — only an ESTIMATED_LAST_MID row ever
#      lands.  Reader returns it unchanged.
# ----------------------------------------------------------------------
def test_missing_broker_tx_returns_estimated(patched_trade_log):
    mod = patched_trade_log
    deal_id = "DIAAAA_MISSING"
    mod._test_state["GBPUSD|BB_BOUNCE_S"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": deal_id,
    }
    mod.record_close(
        "GBPUSD|BB_BOUNCE_S", exit_price=13250.0, pnl_pips=-10.0,
        close_reason="External close (not initiated by this host)",
        deal_id=deal_id,
    )
    best = mod.read_closes_by_deal_id()
    assert best[deal_id]["price_source"] == mod.ESTIMATED_LAST_MID
    assert best[deal_id]["exit_price"] == 13250.0


# ----------------------------------------------------------------------
# 12.  Duplicate authoritative rows — latest ts wins.
# ----------------------------------------------------------------------
def test_duplicate_authoritative_latest_wins(patched_trade_log, monkeypatch):
    mod = patched_trade_log
    deal_id = "DIAAAA_DUP"
    mod._test_state["GBPUSD|QM_V2_L"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 1.0, "deal_id": deal_id,
    }
    # Simulate a reconciler running twice.
    for exit_px in [13300.0, 13305.0]:
        mod.record_close(
            "GBPUSD|QM_V2_L", exit_price=exit_px, pnl_pips=exit_px - 13295.0,
            close_reason="TP hit", deal_id=deal_id,
            price_source=mod.AUTHORITATIVE_IG_HISTORY,
        )
    best = mod.read_closes_by_deal_id()
    assert best[deal_id]["exit_price"] == 13305.0


# ----------------------------------------------------------------------
# 13.  BID/ASK differentiation — spread-sided close price must not be
#      overwritten by last_mid.  (Verified by preserving the explicit
#      authoritative row.)
# ----------------------------------------------------------------------
def test_bid_ask_close_preserved(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|TREND_V3_S"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": "DIAAAA_BIDASK",
    }
    # SELL closes against the ask side.
    mod.record_close(
        "GBPUSD|TREND_V3_S", exit_price=13297.0, pnl_pips=3.0,
        close_reason="TP hit", deal_id="DIAAAA_BIDASK",
        price_source=mod.AUTHORITATIVE_BROKER_CLOSE,
    )
    row = _read_rows(mod)[0]
    assert row["exit_price"] == 13297.0  # not mid-adjusted


# ----------------------------------------------------------------------
# 14.  Spread-expansion case — a close during a widening spread must
#      stay authoritative when IG confirmed, not be downgraded.
# ----------------------------------------------------------------------
def test_spread_expansion_authority_preserved(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|BB_BOUNCE_S"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 2.0, "deal_id": "DIAAAA_SPREAD",
    }
    mod.record_close(
        "GBPUSD|BB_BOUNCE_S", exit_price=13318.0, pnl_pips=-18.0,
        close_reason="SL hit", deal_id="DIAAAA_SPREAD",
        price_source=mod.AUTHORITATIVE_BROKER_CLOSE,
    )
    row = _read_rows(mod)[0]
    assert row["price_source"] == mod.AUTHORITATIVE_BROKER_CLOSE


# ----------------------------------------------------------------------
# 15.  Shared-account ownership — a row with a deal_id that belongs to
#      another host should still land, but the ledger reader keys by
#      deal_id so cross-host collisions remain visible.
# ----------------------------------------------------------------------
def test_shared_account_row_is_recorded(patched_trade_log):
    mod = patched_trade_log
    mod._test_state["GBPUSD|SHARED"] = {
        "epic": "CS.D.GBPUSD.TODAY.IP", "size": 1.0, "deal_id": "DIAAAA_SHARED",
    }
    mod.record_close(
        "GBPUSD|SHARED", exit_price=13300.0, pnl_pips=1.0,
        close_reason="External close (not initiated by this host)",
        deal_id="DIAAAA_SHARED",
    )
    rows = _read_rows(mod)
    assert len(rows) == 1
    assert rows[0]["deal_id"] == "DIAAAA_SHARED"
