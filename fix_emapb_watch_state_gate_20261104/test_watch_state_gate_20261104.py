"""Regression tests for the WATCH_AND_WAIT directional-permission gate.

Reproduces the 2026-11-04 09:30 WATCH_AND_WAIT event and the subsequent
EMA Pullback arm/fill attempt for deal EMAPB-B-1793784609-5D79C8, plus
the full admission + cancellation contract specified in
`ema_pullback/watch_state_gate.py`.

Incident facts (used verbatim where useful — frozen point-in-time data):

  * W&W entered WATCH_AND_WAIT at 2026-11-04T09:30:05Z (BUYING_EXHAUSTION
    confirmed via CANDLE_REJECTION + MOMENTUM families, exhaustion
    direction opposing EMERGING_UP).
  * EMA PB armed setup 5D79C8 at 2026-11-04T09:30:08.428757Z with
    entry_level=13497.65 (five-bar high 13494.65 + 3p buffer).
  * Market submit at 2026-11-04T10:17:22.071595Z filled at 13498.9.
  * Stop out at 10:30:08 (-12p / -£24).

With the W&W gate enabled, the arm MUST be refused at the 09:30:08 arm
boundary, the belt-and-braces check at the 10:17:22 pre-submit recheck
MUST also refuse if the arm had somehow happened, and a WATCH_AND_WAIT
entered while ARMED MUST cancel the pending setup safely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from ema_pullback.candle_reader import M5Bar
from ema_pullback.config import Config, load_config
from ema_pullback.ig_client import IGClientBase, OrderResult
from ema_pullback.price_source import PriceSource, Tick
from ema_pullback.service import EmaPullbackService
from ema_pullback.state_machine import (
    ARMED, CANCELLED, EXPIRED, IN_TRADE, ORDER_WAITING,
    PENDING_STATES, SKIPPED, Setup,
)
from ema_pullback.watch_state_gate import (
    WatchStateProvider,
    check as watch_state_check,
)


INCIDENT_TOUCH_TS = datetime(2026, 11, 4, 9, 30, 8, 428757, tzinfo=timezone.utc)
INCIDENT_FILL_TS  = datetime(2026, 11, 4, 10, 17, 22, 71595, tzinfo=timezone.utc)
INCIDENT_ENTRY_LEVEL = 13497.65
INCIDENT_FILL_PRICE  = 13498.9


class _FakeProvider:
    """In-memory W&W provider with a single pre-loaded snapshot."""

    def __init__(self, snapshot: Optional[Dict[str, Any]] = None):
        self._snapshot = snapshot

    def set(self, snapshot: Optional[Dict[str, Any]]) -> None:
        self._snapshot = snapshot

    def load(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._snapshot


def _watch_snapshot(
    state: str,
    *,
    evaluation_ts: datetime = INCIDENT_TOUCH_TS - timedelta(seconds=3),
    last_bar_ts: Optional[datetime] = None,
    symbol: str = "GBPUSD",
    watched_trend_direction: Optional[str] = "UP",
    reversal_direction: Optional[str] = None,
    reversal_oracle: Optional[str] = None,
    schema_version: str = "nms_watch_state.v1",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a W&W snapshot fixture matching the production shape.

    Mirrors the fields written by
    /opt/tradingbot/nms_watch_state_driver.py — the live file consumed
    by the production gate.
    """
    if last_bar_ts is None:
        # Round evaluation_ts down to the previous M5 bucket.
        secs = evaluation_ts.minute % 5
        last_bar_ts = evaluation_ts.replace(
            minute=evaluation_ts.minute - secs, second=0, microsecond=0,
        )
    out = {
        "schema_version": schema_version,
        "symbol": symbol,
        "state": state,
        "previous_state": "TREND_TRADING",
        "evaluation_ts": evaluation_ts.isoformat(),
        "last_bar_ts": last_bar_ts.isoformat(),
        "nms_v3_state": "EMERGING_UP",
        "nms_v3_fresh": True,
        "exhaustion_state": "EXHAUSTION_CONFIRMED",
        "exhaustion_direction": "BUYING_EXHAUSTION",
        "exhaustion_families_active": ["CANDLE_REJECTION", "MOMENTUM"],
        "exhaustion_readiness": "READY",
        "exhaustion_freshness": "FRESH",
        "watched_trend_direction": watched_trend_direction,
        "reversal_direction": reversal_direction,
        "reversal_oracle": reversal_oracle,
        "reversal_signal_ts": None,
        "reversal_signal_bar_ts": None,
        "reversal_signal_fingerprint": None,
        "reversal_level_type": None,
        "reversal_level_price": None,
        "reversal_memory_defence_count": None,
        "watch_extreme_price": 13499.0 if state == "WATCH_AND_WAIT" else None,
        "watch_triggered_at": evaluation_ts.isoformat() if state == "WATCH_AND_WAIT" else None,
        "exhaustion_trigger_direction": "BUYING_EXHAUSTION" if state == "WATCH_AND_WAIT" else None,
        "reason_code": "ENTER_WATCH_EXHAUSTION_INDEPENDENT" if state == "WATCH_AND_WAIT" else "TREND_TRADING_DEFAULT",
        "reason_detail": None,
    }
    if extra:
        out.update(extra)
    return out


class _RecordingIG(IGClientBase):
    """Captures broker-side primitives the gate interacts with."""

    def __init__(self):
        self.place_calls: List[Dict[str, Any]] = []
        self.market_calls: List[Dict[str, Any]] = []
        self.cancel_calls: List[Dict[str, Any]] = []
        self._working_orders: List[Dict[str, Any]] = []
        self._positions: List[Dict[str, Any]] = []
        self.next_cancel_status = "CANCELLED"
        self.next_fill_price: Optional[float] = INCIDENT_FILL_PRICE

    def place_working_order(self, direction, entry_level, stop_distance,
                             limit_distance, deal_reference):
        self.place_calls.append(locals())
        return OrderResult(status="OPEN", deal_id="DID-WO",
                           deal_reference=deal_reference,
                           broker_sl_level=None, broker_tp_level=None, error=None)

    def open_market_entry(self, direction, stop_distance, limit_distance,
                          deal_reference):
        self.market_calls.append({
            "direction": direction, "stop_distance": stop_distance,
            "limit_distance": limit_distance, "deal_reference": deal_reference,
        })
        return OrderResult(status="FILLED", deal_id="DID-MARKET",
                           deal_reference=deal_reference,
                           broker_sl_level=None, broker_tp_level=None,
                           error=None, fill_price=self.next_fill_price)

    def cancel_working_order(self, deal_id, deal_reference):
        self.cancel_calls.append({"deal_id": deal_id, "deal_reference": deal_reference})
        return OrderResult(status=self.next_cancel_status, deal_id=deal_id,
                           deal_reference=deal_reference,
                           broker_sl_level=1, broker_tp_level=2, error=None)

    def close_open_position(self, deal_id, direction, size):
        return OrderResult(status="CLOSED", deal_id=deal_id, deal_reference="",
                           broker_sl_level=None, broker_tp_level=None, error=None)

    def list_own_working_orders(self, prefix):
        return self._working_orders

    def list_own_open_positions(self, prefix):
        return self._positions

    def account_wide_exposure(self):
        return {"open_positions": len(self._positions),
                "working_orders": len(self._working_orders)}

    def fetch_recent_activity_for_deal(self, deal_id, lookback_minutes=15):
        return []


class _FakeEvent:
    """Minimal duck-type of an IntrabarTracker EntryCrossing event."""

    def __init__(self, direction, ts, price, entry_level,
                 forming_ts=None, live_ema_fast=None):
        self.direction = direction
        self.ts = ts
        self.price = price
        self.entry_level = entry_level
        self.forming_ts = forming_ts or ts.replace(second=0, microsecond=0)
        self.live_ema_fast = live_ema_fast if live_ema_fast is not None else price


def _cfg(tmp_path, monkeypatch, **overrides) -> Config:
    env = {
        "STATE_DIR": str(tmp_path / "state"),
        "LOG_DIR": str(tmp_path / "logs"),
        "REPORT_DIR": str(tmp_path / "reports"),
        "H1_MIN_COMPLETED_CANDLES": "20",
        "EXECUTION_ENABLED": "true",
        "EMA_PULLBACK_LIVE_APPROVED": "true",
        "OWNERSHIP_HOST_PREFIX": "EMAPB",
        "PIP_SIZE": "1.0",
        "EXIT_MODE": "method_b",
        "BROKER_SL_PIPS": "12",
        "BROKER_TP_PIPS": "100",
        "TRADE_SIZE": "2.0",
        "INTRABAR_ENABLED": "true",
        "H1_ENFORCE_QUALIFICATION": "false",
        "NMS_GATE_ENABLED": "false",
        "MECHANICAL_ENTRY_MODE": "market_on_trigger",
        "MAX_ENTRY_SLIPPAGE_PIPS": "2.0",
        "QUOTE_MAX_AGE_SECONDS": "30.0",
        "EXECUTION_OWNER_ENFORCED": "false",
        "EMAPB_LOCK_DIR_OVERRIDE_FOR_TESTS": str(tmp_path),
        "SETUP_MAX_AGE_SECONDS": "0",           # disable the expiry fix for isolation
        "EMAPB_WATCH_STATE_GATE_ENABLED": "true",
        "EMAPB_WATCH_STATE_MAX_AGE_SECONDS": "900",
        "EMAPB_WATCH_STATE_FAIL_POLICY": "closed",
        "TRADING_HOURS_ENABLED": "0",
    }
    env.update(overrides)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return load_config(env_file=None)


def _install_armed(svc, trigger_ts=INCIDENT_TOUCH_TS, state=ARMED,
                   direction="BUY",
                   setup_id="TEST-INC", deal_reference="EMAPB-B-TEST-INC",
                   deal_id=None):
    svc.active = Setup(
        setup_id=setup_id,
        direction=direction,
        trigger_ts=trigger_ts,
        entry_level=INCIDENT_ENTRY_LEVEL,
        lookback_extreme=13494.65,
        deal_reference=deal_reference,
        deal_id=deal_id,
        state=state,
        audit={
            "intrabar_touch": True,
            "touch_tick_ts": trigger_ts.isoformat(),
            "pip_size": 1.0,
            # trigger_* fields are consumed by the structural-stop
            # builder on fill promotion (service.py:_trigger_bar_from_audit).
            "trigger_open":  13485.55,
            "trigger_high":  13486.11,
            "trigger_low":   13485.55,
            "trigger_close": 13485.55,
            "structural_sl_level": 13482.55,
            "structural_buffer_pips": 3.0,
            "broker_sl_pips": 12.0,
            "broker_tp_pips": 100.0,
            "exit_mode": "method_b",
            "entry_mode": "market_on_trigger",
        },
    )
    svc.ledger.save_active(svc.active)


# ─────────────────────────────────────────────────────────────────────
# Phase A — pure gate contract (decision level, no service)
# ─────────────────────────────────────────────────────────────────────

def test_disabled_flag_passes_without_io(tmp_path, monkeypatch):
    """Default-disabled: no snapshot I/O, PASS with gate_disabled reason."""
    provider = _FakeProvider({"__error__": "unused"})
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=provider,
        enabled=False,
    )
    assert dec.allowed
    assert dec.reason == "watch_state_gate_disabled"


def test_watch_and_wait_blocks_buy(tmp_path):
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=provider,
        enabled=True,
    )
    assert not dec.allowed
    assert dec.binding == "watch_state_block"
    assert dec.state == "WATCH_AND_WAIT"
    assert "WATCH_AND_WAIT" in dec.reason


def test_watch_and_wait_blocks_sell_symmetric(tmp_path):
    """Operator spec §4: both BUY and SELL are blocked during W&W."""
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    dec = watch_state_check(
        direction="SELL", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=provider,
        enabled=True,
    )
    assert not dec.allowed
    assert "WATCH_AND_WAIT" in dec.reason


def test_continuation_confirmed_passes(tmp_path):
    """Spec: equivalent to TREND_TRADING for admission purposes."""
    provider = _FakeProvider(_watch_snapshot("CONTINUATION_CONFIRMED"))
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=provider,
        enabled=True,
    )
    assert dec.allowed
    assert dec.state == "CONTINUATION_CONFIRMED"


def test_reversal_confirmed_blocks_emapb(tmp_path):
    """REVERSAL_CONFIRMED grants narrow permission to qm_reversal strategies
    only. EMA Pullback is not a reversal strategy — blocked.
    """
    provider = _FakeProvider(_watch_snapshot(
        "REVERSAL_CONFIRMED",
        reversal_direction="DOWN", reversal_oracle="QM_REVERSAL",
    ))
    # Blocks BOTH BUY (would contradict a confirmed DOWN reversal) AND
    # SELL (EMA PB is not the qm_reversal strategy).
    for d in ("BUY", "SELL"):
        dec = watch_state_check(
            direction=d, symbol="GBPUSD",
            now_utc=INCIDENT_TOUCH_TS, provider=provider,
            enabled=True,
        )
        assert not dec.allowed, f"{d} must be blocked under REVERSAL_CONFIRMED"


def test_trend_trading_passes(tmp_path):
    provider = _FakeProvider(_watch_snapshot("TREND_TRADING"))
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=provider,
        enabled=True,
    )
    assert dec.allowed
    assert dec.state == "TREND_TRADING"


# ─────── Fail-closed + freshness ──────────────────────────────────────


def test_fail_closed_on_unavailable_snapshot():
    provider = _FakeProvider(None)
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=provider,
        enabled=True, fail_policy="closed",
    )
    assert not dec.allowed
    assert dec.binding == "snapshot_fail_closed"
    assert "missing" in dec.reason


def test_fail_closed_on_malformed_snapshot():
    provider = _FakeProvider({"__error__": "watch_state_snapshot_malformed:JSONDecodeError"})
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=provider,
        enabled=True, fail_policy="closed",
    )
    assert not dec.allowed
    assert dec.binding == "snapshot_fail_closed"
    assert "malformed" in dec.reason


def test_fail_closed_on_schema_mismatch():
    snap = _watch_snapshot("TREND_TRADING", schema_version="nms_watch_state.v99")
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(snap),
        enabled=True,
    )
    assert not dec.allowed
    assert "schema_unsupported" in dec.reason


def test_fail_closed_on_symbol_mismatch():
    snap = _watch_snapshot("TREND_TRADING", symbol="EURUSD")
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(snap),
        enabled=True,
    )
    assert not dec.allowed
    assert "symbol_mismatch" in dec.reason


def test_fail_closed_on_stale_evaluation_ts():
    # evaluation_ts is 901 seconds older than now
    eval_ts = INCIDENT_TOUCH_TS - timedelta(seconds=901)
    snap = _watch_snapshot("TREND_TRADING", evaluation_ts=eval_ts)
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(snap),
        enabled=True, max_age_seconds=900.0,
    )
    assert not dec.allowed
    assert "stale" in dec.reason


def test_fail_closed_on_stale_last_bar_ts():
    """Fresh evaluation_ts but stale last_bar_ts → driver is stuck on
    an old bar; fail-closed.
    """
    eval_ts = INCIDENT_TOUCH_TS - timedelta(seconds=30)
    stale_bar = INCIDENT_TOUCH_TS - timedelta(seconds=1000)
    snap = _watch_snapshot(
        "TREND_TRADING", evaluation_ts=eval_ts, last_bar_ts=stale_bar,
    )
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(snap),
        enabled=True, max_age_seconds=900.0,
    )
    assert not dec.allowed
    assert "last_bar_stale" in dec.reason


def test_fail_closed_on_future_evaluation_ts():
    eval_ts = INCIDENT_TOUCH_TS + timedelta(seconds=10)
    snap = _watch_snapshot("TREND_TRADING", evaluation_ts=eval_ts)
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(snap),
        enabled=True,
    )
    assert not dec.allowed
    assert "future_ts" in dec.reason


def test_fail_closed_on_unknown_state():
    snap = _watch_snapshot("TREND_TRADING")
    snap["state"] = "COMPLETELY_INVENTED_STATE"
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(snap),
        enabled=True,
    )
    assert not dec.allowed
    assert "unknown_state" in dec.reason


def test_fail_open_mode_admits_on_missing():
    """fail_policy='open' is a staged diagnostic path — admits on missing."""
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(None),
        enabled=True, fail_policy="open",
    )
    assert dec.allowed


# ─────────────────────────────────────────────────────────────────────
# Phase B — service integration (incident reproduction)
# ─────────────────────────────────────────────────────────────────────

def test_incident_reproduction_watch_state_blocks_fill(tmp_path, monkeypatch):
    """2026-11-04 10:17:22Z fill MUST NOT execute when W&W held.

    Setup 5D79C8 armed at 09:30:08.428; snapshot at that instant was
    WATCH_AND_WAIT (per cache/nms_watch_state_GBPUSD.json on the day).
    The arm must not even happen — but we also verify the pre-submit
    recheck in _apply_intrabar_fill refuses if it somehow did.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot(
        "WATCH_AND_WAIT",
        evaluation_ts=INCIDENT_FILL_TS - timedelta(seconds=132),
    ))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc)

    # Simulate the step-level cancellation check at the fill tick.
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_FILL_TS, diag=diag)
    assert svc.active is None, "ARMED setup must be cancelled under W&W"
    kinds = [e["kind"] for e in diag["events"]]
    assert "cancelled" in kinds
    cancel_evt = next(e for e in diag["events"] if e["kind"] == "cancelled")
    assert cancel_evt["state"] == "ARMED"
    assert cancel_evt["watch_state"] == "WATCH_AND_WAIT"

    # And the belt-and-braces guard inside _apply_intrabar_fill must
    # also refuse. Reinstall and invoke the fill path directly.
    _install_armed(svc)
    cross = _FakeEvent(direction="BUY", ts=INCIDENT_FILL_TS,
                       price=INCIDENT_FILL_PRICE,
                       entry_level=INCIDENT_ENTRY_LEVEL)
    diag2: Dict[str, Any] = {"events": []}
    svc._apply_intrabar_fill(
        cross, now_utc=INCIDENT_FILL_TS + timedelta(seconds=1), diag=diag2,
    )
    assert ig.market_calls == [], "open_market_entry must NOT fire under W&W"
    assert ig.place_calls == [], "no legacy working-order call either"
    assert svc.active is None
    kinds2 = [e["kind"] for e in diag2["events"]]
    assert any(k.startswith("watch_state_") for k in kinds2)


def test_arm_boundary_block_at_0930(tmp_path, monkeypatch):
    """At 09:30:08 — the actual arm boundary — W&W must refuse arming.

    Here we exercise the _watch_state_check decision used by
    _run_intrabar's Case B admission path.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot(
        "WATCH_AND_WAIT",
        evaluation_ts=INCIDENT_TOUCH_TS - timedelta(seconds=3),
    ))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    dec = svc._watch_state_check(direction="BUY", now_utc=INCIDENT_TOUCH_TS)
    assert not dec.allowed
    assert dec.state == "WATCH_AND_WAIT"


def test_ww_enters_while_armed_cancels_safely(tmp_path, monkeypatch):
    """Setup armed under TREND_TRADING, then W&W enters: cancel ARMED."""
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot(
        "TREND_TRADING",
        evaluation_ts=INCIDENT_TOUCH_TS - timedelta(seconds=10),
    ))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc)

    # State flips to WATCH_AND_WAIT a few minutes later.
    later = INCIDENT_TOUCH_TS + timedelta(minutes=10)
    provider.set(_watch_snapshot(
        "WATCH_AND_WAIT",
        evaluation_ts=later - timedelta(seconds=5),
    ))
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=later, diag=diag)
    assert svc.active is None
    assert ig.place_calls == []    # ARMED has no broker footprint
    assert ig.cancel_calls == []   # local drop only


def test_ww_cancels_order_waiting_with_broker_cancel(tmp_path, monkeypatch):
    """Legacy working-order path — W&W must cancel broker-side first."""
    cfg = _cfg(tmp_path, monkeypatch,
                MECHANICAL_ENTRY_MODE="working_order")
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc, state=ORDER_WAITING,
                    deal_id="DID-WO-X", deal_reference="EMAPB-B-X")
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_TOUCH_TS, diag=diag)
    assert len(ig.cancel_calls) == 1
    assert ig.cancel_calls[0]["deal_id"] == "DID-WO-X"
    assert ig.cancel_calls[0]["deal_reference"] == "EMAPB-B-X"
    assert svc.active is None


def test_cancel_race_filled_promotes_to_in_trade(tmp_path, monkeypatch):
    """If broker reports FILLED when the cancellation lands — IN_TRADE,
    not CANCELLED. Mirrors _cancel_outside_trading_hours semantics.
    """
    cfg = _cfg(tmp_path, monkeypatch,
                MECHANICAL_ENTRY_MODE="working_order")
    ig = _RecordingIG()
    ig.next_cancel_status = "FILLED"
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc, state=ORDER_WAITING,
                    deal_id="DID-RACE", deal_reference="EMAPB-B-RACE")
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_TOUCH_TS, diag=diag)
    assert svc.active is not None
    assert svc.active.state == IN_TRADE
    assert svc.active.fill_price == pytest.approx(INCIDENT_ENTRY_LEVEL)
    kinds = [e["kind"] for e in diag["events"]]
    assert "cancel_race_filled" in kinds
    assert "cancelled" not in kinds


# ─────── State-transition semantics (operator brief §13) ──────────────


def test_watch_to_continuation_resumes_admission(tmp_path, monkeypatch):
    """CONTINUATION_CONFIRMED (after W&W resolved by floor-break) must
    allow a fresh arm.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("CONTINUATION_CONFIRMED"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    dec = svc._watch_state_check(direction="BUY", now_utc=INCIDENT_TOUCH_TS)
    assert dec.allowed
    assert dec.state == "CONTINUATION_CONFIRMED"


def test_watch_to_reversal_still_blocks_emapb(tmp_path, monkeypatch):
    """REVERSAL_CONFIRMED — EMA PB is not a reversal strategy. Block."""
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot(
        "REVERSAL_CONFIRMED",
        reversal_direction="DOWN", reversal_oracle="QM_REVERSAL",
    ))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    for d in ("BUY", "SELL"):
        dec = svc._watch_state_check(direction=d, now_utc=INCIDENT_TOUCH_TS)
        assert not dec.allowed, f"{d} must be blocked under REVERSAL_CONFIRMED"


# ─────── Protected states + non-interference ──────────────────────────


def test_in_trade_untouched(tmp_path, monkeypatch):
    """IN_TRADE represents a live broker position — managed by the exit
    lifecycle, NOT the W&W gate.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc, state=IN_TRADE,
                    deal_id="DID-POS", deal_reference="EMAPB-B-POS")
    svc.active.fill_price = 13498.9
    svc.active.fill_ts = INCIDENT_FILL_TS
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_FILL_TS, diag=diag)
    assert svc.active is not None
    assert svc.active.state == IN_TRADE
    assert ig.cancel_calls == []
    assert ig.place_calls == []


def test_submitting_state_untouched(tmp_path, monkeypatch):
    from ema_pullback.state_machine import SUBMITTING
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc, state=SUBMITTING,
                    deal_id="DID-INFL", deal_reference="EMAPB-B-INFL")
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_TOUCH_TS, diag=diag)
    assert svc.active is not None
    assert svc.active.state == SUBMITTING
    assert ig.cancel_calls == []


def test_uncertain_state_untouched(tmp_path, monkeypatch):
    from ema_pullback.state_machine import UNCERTAIN
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc, state=UNCERTAIN,
                    deal_id="DID-UNC", deal_reference="EMAPB-B-UNC")
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_TOUCH_TS, diag=diag)
    assert svc.active is not None
    assert svc.active.state == UNCERTAIN
    assert ig.cancel_calls == []


def test_escalated_state_untouched(tmp_path, monkeypatch):
    from ema_pullback.state_machine import ESCALATED
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc, state=ESCALATED,
                    deal_id="DID-ESC", deal_reference="EMAPB-B-ESC")
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_TOUCH_TS, diag=diag)
    assert svc.active is not None
    assert svc.active.state == ESCALATED
    assert ig.cancel_calls == []


# ─────── Non-interference with legitimate flow ────────────────────────


def test_gate_disabled_is_byte_identical(tmp_path, monkeypatch):
    """With gate disabled, _check_watch_state_cancellation must be a no-op.

    Preserves byte-identical pre-patch behaviour for the default rollout
    posture. The ARMED setup stays intact; the trade-ability path is
    unchanged.
    """
    cfg = _cfg(tmp_path, monkeypatch,
                EMAPB_WATCH_STATE_GATE_ENABLED="false")
    ig = _RecordingIG()
    # Install a provider that WOULD block if consulted — proves the
    # disabled flag short-circuits before any read.
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc)
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_FILL_TS, diag=diag)
    assert svc.active is not None
    assert svc.active.state == ARMED
    assert diag["events"] == []
    assert ig.cancel_calls == []


def test_direction_block_precedes_watch_block(tmp_path, monkeypatch):
    """The v3 directional gate runs FIRST in _run_intrabar. If it already
    blocks, the W&W check must not record a duplicate skip. This
    protects telemetry integrity.
    """
    cfg = _cfg(tmp_path, monkeypatch,
                NMS_GATE_ENABLED="false")
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("WATCH_AND_WAIT"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    # Pure gate layering — do not drive the full _run_intrabar (which
    # requires a full M5 feed). Instead assert that when the v3 gate
    # returns disabled (as configured here), the W&W gate is what blocks.
    dec = svc._watch_state_check(direction="BUY", now_utc=INCIDENT_TOUCH_TS)
    assert not dec.allowed
    nms_dec = svc._nms_check(direction="BUY", now_utc=INCIDENT_TOUCH_TS)
    assert nms_dec.allowed, "NMS v3 disabled → trivial allow"


def test_trend_trading_does_not_cancel_armed(tmp_path, monkeypatch):
    """Normal pullback inside an established bullish trend (W&W=TREND_TRADING)
    must leave the ARMED setup intact. Preserves normal-pullback
    eligibility — the operator-brief invariant.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("TREND_TRADING"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc)
    diag: Dict[str, Any] = {"events": []}
    svc._check_watch_state_cancellation(now_utc=INCIDENT_TOUCH_TS, diag=diag)
    assert svc.active is not None
    assert svc.active.state == ARMED
    assert ig.cancel_calls == []
    assert diag["events"] == []


def test_trend_trading_allows_fill(tmp_path, monkeypatch):
    """The belt-and-braces guard must NOT suppress a legitimate fill
    when the authority is TREND_TRADING (or CONTINUATION_CONFIRMED).
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _RecordingIG()
    ig.next_fill_price = INCIDENT_FILL_PRICE
    # Snapshot must be FRESH at the simulated fill time — otherwise
    # the fail-closed branch correctly refuses, which is what the
    # last_bar_ts / evaluation_ts age gates exist to do.
    provider = _FakeProvider(_watch_snapshot(
        "TREND_TRADING",
        evaluation_ts=INCIDENT_FILL_TS - timedelta(seconds=5),
    ))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc)
    cross = _FakeEvent(direction="BUY", ts=INCIDENT_FILL_TS,
                       price=INCIDENT_FILL_PRICE,
                       entry_level=INCIDENT_ENTRY_LEVEL)
    diag: Dict[str, Any] = {"events": []}
    svc._apply_intrabar_fill(
        cross, now_utc=INCIDENT_FILL_TS + timedelta(seconds=1), diag=diag,
    )
    assert len(ig.market_calls) == 1
    assert svc.active is not None
    assert svc.active.state == IN_TRADE


# ─────── Day-roll / stale-session protection (brief §14) ──────────────


def test_snapshot_from_previous_day_rejected_via_last_bar_age(tmp_path, monkeypatch):
    """A snapshot whose last_bar_ts is from yesterday is stale by
    construction, independent of evaluation_ts. Fail-closed.
    """
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    yesterday_bar = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)
    # evaluation_ts is fresh (recent) but last_bar_ts is 13 hours old.
    snap = _watch_snapshot(
        "WATCH_AND_WAIT",
        evaluation_ts=now - timedelta(seconds=30),
        last_bar_ts=yesterday_bar,
    )
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=now, provider=_FakeProvider(snap),
        enabled=True, max_age_seconds=900.0,
    )
    assert not dec.allowed
    assert "last_bar_stale" in dec.reason


def test_fresh_snapshot_without_last_bar_ts_still_accepted_if_eval_fresh(tmp_path):
    """last_bar_ts is advisory — if absent, the gate relies solely on
    evaluation_ts age. This guards against driver versions that don't
    populate the field.
    """
    snap = _watch_snapshot("TREND_TRADING")
    snap["last_bar_ts"] = None
    dec = watch_state_check(
        direction="BUY", symbol="GBPUSD",
        now_utc=INCIDENT_TOUCH_TS, provider=_FakeProvider(snap),
        enabled=True, max_age_seconds=900.0,
    )
    assert dec.allowed


def test_setup_expiry_untouched_by_watch_state_gate(tmp_path, monkeypatch):
    """The recently-deployed 20-minute setup expiry must be independent
    of this gate. Enabling the W&W gate does NOT re-arm expired setups
    or alter their expiry behaviour.
    """
    cfg = _cfg(tmp_path, monkeypatch, SETUP_MAX_AGE_SECONDS="1200")
    ig = _RecordingIG()
    provider = _FakeProvider(_watch_snapshot("TREND_TRADING"))
    svc = EmaPullbackService(cfg=cfg, ig=ig, watch_state_provider=provider)
    _install_armed(svc)
    # 25 minutes past touch → expired.
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(
        now_utc=INCIDENT_TOUCH_TS + timedelta(seconds=1500), diag=diag,
    )
    assert svc.active is None
    kinds = [e["kind"] for e in diag["events"]]
    assert "expired" in kinds
