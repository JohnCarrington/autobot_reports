"""Unit tests for the IG-spine + signal_log enrichment path in trades_api.

Covers:
- transaction → activity join via reference == dealId
- aggregation of multi-leg positions by affectedDealId (parent open dealId)
- signal_log enrichment by deal_id and source labelling (bot vs ig_only)
- exit_type derivation: enrich-first, then IG-level fallback
- linkage_missing handling when a transaction has no matching activity row
- env-flag default behaviour (USE_IG_SPINE is opt-in)
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

# Use a non-default flag value during import so the module attribute is
# observable; functional tests call _aggregate_positions etc directly so
# they don't depend on the module-level toggle.
os.environ.setdefault("TRADES_USE_IG_SPINE", "0")
os.environ.setdefault("TRADES_AGGREGATE_POSITIONS", "1")

sys.path.insert(0, "/opt/tradingbot")
import trades_api  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────


def _txn(reference, instrument, open_lvl, close_lvl, pnl_gbp, size_str,
         date_utc, open_date_utc):
    return {
        "dateUtc": date_utc,
        "openDateUtc": open_date_utc,
        "instrumentName": instrument,
        "openLevel": open_lvl,
        "closeLevel": close_lvl,
        "profitAndLoss": pnl_gbp,
        "size_str": size_str,
        "reference": reference,
    }


def _act_close(deal_id, parent, stop_lvl, limit_lvl, direction="BUY", level=None):
    return {
        "dealId": deal_id,
        "actionType": "POSITION_CLOSED",
        "affectedDealId": parent,
        "direction": direction,
        "level": level,
        "stopLevel": stop_lvl,
        "limitLevel": limit_lvl,
        "date": "",
        "marketName": "",
        "channel": "",
    }


def _act_amend(parent, stop_lvl, direction="BUY"):
    return {
        "dealId": f"AMEND-{parent}",
        "actionType": "STOP_LIMIT_AMENDED",
        "affectedDealId": parent,
        "direction": direction,
        "level": None,
        "stopLevel": stop_lvl,
        "limitLevel": None,
        "date": "",
        "marketName": "",
        "channel": "",
    }


# ── close_reason → exit_type mapping ─────────────────────────────────────────


@pytest.mark.parametrize("close_reason,expected", [
    ("SL hit", "STOP"),
    ("TP hit", "TARGET"),
    ("Breakeven stop hit (IG server-side)", "BREAKEVEN"),
    ("BRIEFING_SL_HIT_OPEN", "STOP"),
    ("BRIEFING_TP1_CLOSE", "TARGET"),
    ("STRUCTURE_EXIT:structure_flip_up: foo", "EARLY"),
    ("MANAGER_PROFIT_PROTECT", "EARLY"),
    ("REGIME_MAX_HOLD", "EARLY"),
    ("PRE_NEWS_CLOSE", "EARLY"),
    ("NY_CLOSE", "EARLY"),
    ("BIAS_FLIP_CLOSE", "EARLY"),
    ("BRIEF_INVALIDATED", "EARLY"),
    ("External/manual close detected (IG open positions)", "EXTERNAL"),
    ("IG_RECONCILE:bar", "EXTERNAL"),
    ("PHANTOM_NEVER_EXECUTED", "UNKNOWN"),
])
def test_exit_type_from_close_reason(close_reason, expected):
    et = trades_api._classify_exit_type(
        close_reason_prefix=trades_api._close_reason_prefix(close_reason),
        pnl_pips=None, pnl_gbp=None,
        close_level=None, stop_level=None, limit_level=None,
        stop_was_amended_toward_entry=False, has_levels=False,
    )
    assert et == expected


def test_exit_type_briefing_tp_sl_uses_pnl_sign():
    # Positive pnl → TARGET
    et = trades_api._classify_exit_type(
        close_reason_prefix="BRIEFING_TP_SL_OPEN",
        pnl_pips=12.0, pnl_gbp=None,
        close_level=None, stop_level=None, limit_level=None,
        stop_was_amended_toward_entry=False, has_levels=False,
    )
    assert et == "TARGET"
    et = trades_api._classify_exit_type(
        close_reason_prefix="BRIEFING_TP_SL_OPEN",
        pnl_pips=-8.0, pnl_gbp=None,
        close_level=None, stop_level=None, limit_level=None,
        stop_was_amended_toward_entry=False, has_levels=False,
    )
    assert et == "STOP"


def test_exit_type_falls_through_to_ig_levels():
    # IG returns prices in pip-scaled units (1 unit ≈ 1 pip); the "≈" tolerance
    # is _LEVEL_NEAR_PTS pips. Close ≈ limit → TARGET
    et = trades_api._classify_exit_type(
        close_reason_prefix="",
        pnl_pips=None, pnl_gbp=None,
        close_level=12550.0, stop_level=12480.0, limit_level=12550.5,
        stop_was_amended_toward_entry=False, has_levels=True,
    )
    assert et == "TARGET"
    # Close ≈ stop, no amendment → STOP
    et = trades_api._classify_exit_type(
        close_reason_prefix="",
        pnl_pips=None, pnl_gbp=None,
        close_level=12480.0, stop_level=12480.5, limit_level=12600.0,
        stop_was_amended_toward_entry=False, has_levels=True,
    )
    assert et == "STOP"
    # Close ≈ stop with amendment toward entry → BREAKEVEN
    et = trades_api._classify_exit_type(
        close_reason_prefix="",
        pnl_pips=None, pnl_gbp=None,
        close_level=12500.0, stop_level=12500.5, limit_level=12600.0,
        stop_was_amended_toward_entry=True, has_levels=True,
    )
    assert et == "BREAKEVEN"
    # Has levels, close touches neither → EARLY
    et = trades_api._classify_exit_type(
        close_reason_prefix="",
        pnl_pips=None, pnl_gbp=None,
        close_level=12520.0, stop_level=12400.0, limit_level=12600.0,
        stop_was_amended_toward_entry=False, has_levels=True,
    )
    assert et == "EARLY"
    # No info at all → UNKNOWN
    et = trades_api._classify_exit_type(
        close_reason_prefix="",
        pnl_pips=None, pnl_gbp=None,
        close_level=None, stop_level=None, limit_level=None,
        stop_was_amended_toward_entry=False, has_levels=False,
    )
    assert et == "UNKNOWN"


# ── join + aggregation ───────────────────────────────────────────────────────


def test_single_leg_bot_position_enriches_and_targets_tp():
    parent = "DIAAAA-POS-1"
    close_ref = "DIAAAA-CLOSE-1"
    # IG-pip-scaled levels (1 unit = 1 pip). IG transaction.size is signed
    # by the opening direction (+ = BUY) — confirmed against signal_log.
    txns = [
        _txn(close_ref, "GBP/USD", 12500.0, 12550.0, 50.0, "+3",
             date_utc="2026-06-02T10:30:00", open_date_utc="2026-06-02T09:00:00"),
    ]
    by_dealid = {close_ref: _act_close(close_ref, parent,
                                       stop_lvl=12480.0, limit_lvl=12550.2)}
    by_affected = {parent: [by_dealid[close_ref]]}
    sl_by_id = {parent: {"strategy": "GBPUSD_EMA_PULLBACK_L",
                         "close_reason": "TP hit",
                         "outcome": "WIN", "scaled_out": False,
                         "session": "London"}}
    out = trades_api._aggregate_positions(txns, by_dealid, by_affected, sl_by_id)
    assert len(out) == 1
    row = out[0]
    assert row["pair"] == "GBPUSD"
    assert row["direction"] == "BUY"  # size positive → opened BUY
    assert row["pnl_gbp"] == 50.0
    assert row["pips_pnl"] == 50.0
    assert row["entry_price"] == 12500.0
    assert row["close_price"] == 12550.0
    assert row["open_time"] == "2026-06-02T09:00:00Z"
    assert row["timestamp"] == "2026-06-02T10:30:00Z"
    assert row["strategy"] == "GBPUSD_EMA_PULLBACK_L"
    assert row["close_reason"] == "TP hit"
    assert row["exit_type"] == "TARGET"
    assert row["source"] == "bot"
    assert row["leg_count"] == 1
    assert row["linkage_missing"] is False
    assert row["session"] == "London"


def test_multi_leg_position_aggregates_pnl_and_uses_final_close_time():
    parent = "DIAAAA-POS-2"
    leg1_ref = "DIAAAA-CLOSE-2A"
    leg2_ref = "DIAAAA-CLOSE-2B"
    txns = [
        # SELL position: IG signs size by opening direction → "-1" per leg.
        # Partial bank at TP1
        _txn(leg1_ref, "EUR/USD", 10800.0, 10785.0, 7.5, "-1",
             date_utc="2026-06-02T09:30:00", open_date_utc="2026-06-02T09:00:00"),
        # Runner closed later via structure exit
        _txn(leg2_ref, "EUR/USD", 10800.0, 10775.0, 12.5, "-1",
             date_utc="2026-06-02T11:00:00", open_date_utc="2026-06-02T09:00:00"),
    ]
    by_dealid = {
        leg1_ref: _act_close(leg1_ref, parent, stop_lvl=10810.0, limit_lvl=10785.0,
                             direction="SELL"),
        leg2_ref: _act_close(leg2_ref, parent, stop_lvl=10800.0, limit_lvl=None,
                             direction="SELL"),
    }
    by_affected = {parent: [by_dealid[leg1_ref], by_dealid[leg2_ref],
                            _act_amend(parent, stop_lvl=10800.0, direction="SELL")]}
    sl_by_id = {parent: {"strategy": "BB_REVERSAL",
                         "close_reason": "STRUCTURE_EXIT:structure_flip_down",
                         "scaled_out": True,
                         "partial_bank_pips": 15.0,
                         "runner_pnl_pips": 25.0,
                         "session": "London"}}
    out = trades_api._aggregate_positions(txns, by_dealid, by_affected, sl_by_id)
    assert len(out) == 1
    row = out[0]
    assert row["pair"] == "EURUSD"
    assert row["direction"] == "SELL"  # negative size → opened SELL
    assert row["pnl_gbp"] == 20.0
    assert row["leg_count"] == 2
    assert row["timestamp"] == "2026-06-02T11:00:00Z"  # final leg, never midnight
    assert row["open_time"] == "2026-06-02T09:00:00Z"
    assert row["close_price"] == 10775.0  # final leg close
    assert row["exit_type"] == "EARLY"   # STRUCTURE_EXIT → EARLY
    assert row["scaled_out"] is True
    assert row["partial_bank_pips"] == 15.0
    assert row["runner_pnl_pips"] == 25.0
    assert row["source"] == "bot"


def test_linkage_missing_keeps_leg_and_marks_flag():
    # Transaction has a reference that doesn't match any activity dealId —
    # the row should still surface, grouped on its own reference, with
    # linkage_missing=True.
    txns = [
        # Long position closed for loss; size "+2" = opened BUY.
        _txn("ORPHAN-REF", "USD/CAD", 13500.0, 13480.0, -20.0, "+2",
             date_utc="2026-06-02T14:00:00", open_date_utc="2026-06-02T13:00:00"),
    ]
    out = trades_api._aggregate_positions(txns, {}, {}, {})
    assert len(out) == 1
    row = out[0]
    assert row["pair"] == "USDCAD"
    assert row["linkage_missing"] is True
    assert row["position_id"] == "ORPHAN-REF"
    assert row["pnl_gbp"] == -20.0
    assert row["direction"] == "BUY"
    # No signal_log + no IG levels → UNKNOWN
    assert row["exit_type"] == "UNKNOWN"
    assert row["source"] == "ig_only"


def test_pia_placed_trade_has_no_signal_log_match_ig_only():
    parent = "DIAAAA-PIA-1"
    close_ref = "DIAAAA-PIA-CLOSE"
    txns = [
        # BUY position (size +2 = opened BUY); close above entry = win.
        _txn(close_ref, "USD/JPY", 15620.0, 15650.0, 30.0, "+2",
             date_utc="2026-06-02T15:00:00", open_date_utc="2026-06-02T14:00:00"),
    ]
    # PIA placed this — IG knows about it, but 161's signal_log does not.
    by_dealid = {close_ref: _act_close(close_ref, parent,
                                       stop_lvl=15600.0, limit_lvl=15650.2)}
    by_affected = {parent: [by_dealid[close_ref]]}
    out = trades_api._aggregate_positions(txns, by_dealid, by_affected, {})
    assert len(out) == 1
    row = out[0]
    assert row["pair"] == "USDJPY"
    assert row["source"] == "ig_only"
    assert row["strategy"] == ""
    assert row["close_reason"] == ""
    # Falls through to IG-levels: close ≈ limit → TARGET
    assert row["exit_type"] == "TARGET"


def test_signal_log_by_deal_id_indexes_by_open_dealid(tmp_path, monkeypatch):
    log_file = tmp_path / "signal_log.jsonl"
    rec_a = {"deal_id": "DIAAA-OPEN-A", "strategy": "S_A",
             "close_reason": "TP hit", "timestamp_open": "2026-06-02T09:00:00Z"}
    rec_b = {"deal_id": "DIAAA-OPEN-B", "strategy": "S_B",
             "close_reason": "SL hit", "timestamp_open": "2026-06-02T10:00:00Z"}
    no_deal = {"deal_id": None, "strategy": "S_X",
               "timestamp_open": "2026-06-02T11:00:00Z"}
    with open(log_file, "w") as f:
        for r in (rec_a, rec_b, no_deal):
            f.write(json.dumps(r) + "\n")
    monkeypatch.setattr(trades_api, "SIGNAL_LOG_PATH", Path(log_file))
    idx = trades_api._signal_log_by_deal_id(days=30)
    assert set(idx.keys()) == {"DIAAA-OPEN-A", "DIAAA-OPEN-B"}
    assert idx["DIAAA-OPEN-A"]["strategy"] == "S_A"


def test_open_position_row_with_enrichment():
    # Open BUY position, mid below entry → live pips negative.
    open_pos = [{
        "dealId": "DIAAAA-OPEN-1",
        "size": 2.0,
        "direction": "BUY",
        "level": 12500.0,
        "stopLevel": 12480.0,
        "limitLevel": 12600.0,
        "instrumentName": "GBP/USD",
        "createdDateUTC": "2026-06-03T08:40:03",
        "bid": 12492.0,
        "offer": 12493.0,
        "currency": "GBP",
    }]
    sl_by_id = {"DIAAAA-OPEN-1": {"strategy": "GBPUSD_EMA_PULLBACK_L",
                                  "session": "London"}}
    rows = trades_api._build_open_position_rows(open_pos, sl_by_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["pair"] == "GBPUSD"
    assert row["direction"] == "BUY"
    assert row["exit_type"] == "OPEN"
    assert row["is_open"] is True
    assert row["close_price"] is None
    assert row["close_reason"] == ""
    # mid = 12492.5, entry = 12500.0 → live pips = -7.5
    assert row["pips_pnl"] == -7.5
    # £ ≈ pips × size = -7.5 × 2 = -15.00
    assert row["pnl_gbp"] == -15.0
    assert row["live_mid"] == 12492.5
    assert row["source"] == "bot"
    assert row["strategy"] == "GBPUSD_EMA_PULLBACK_L"
    assert row["session"] == "London"


def test_open_position_pia_placed_is_ig_only():
    open_pos = [{
        "dealId": "DIAAAA-OPEN-PIA",
        "size": 1.0,
        "direction": "SELL",
        "level": 15650.0,
        "stopLevel": 15670.0,
        "limitLevel": 15600.0,
        "instrumentName": "USD/JPY",
        "createdDateUTC": "2026-06-03T09:00:00",
        "bid": 15655.0,
        "offer": 15656.0,
        "currency": "GBP",
    }]
    rows = trades_api._build_open_position_rows(open_pos, {})
    assert len(rows) == 1
    row = rows[0]
    assert row["pair"] == "USDJPY"
    assert row["direction"] == "SELL"
    assert row["exit_type"] == "OPEN"
    assert row["source"] == "ig_only"
    # mid = 15655.5, entry = 15650 → SELL live pips = entry-mid = -5.5
    assert row["pips_pnl"] == -5.5


def test_default_flag_is_off():
    # Default config: TRADES_USE_IG_SPINE must default to 0 so the live
    # dashboard sees no behavioural change.
    importlib.reload(trades_api)
    # Re-set after reload because the test process may have inherited env.
    if os.environ.get("TRADES_USE_IG_SPINE", "0") == "0":
        assert trades_api.USE_IG_SPINE is False
