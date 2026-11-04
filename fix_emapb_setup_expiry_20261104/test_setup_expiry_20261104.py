"""Regression tests for the 2026-11-04 10:17:22Z delayed BUY — setup validity window.

Incident summary (reconstructed from /opt/ema_pullback/state/setup_history.jsonl
entry setup_id=5D79C8 and journald ema-pullback.service):

  * 09:30:08Z — intrabar EMA8 touch; setup ARMED @ entry_level=13497.65
                (5-bar preceding high 13494.65 + 3p buffer).
  * 09:30:08Z → 10:17:22Z — 47 minutes elapsed with state=ARMED.
  * 10:17:22Z — ask crossed 13497.65; MARKET order submitted; fill 13498.9
                (+1.67p above M5 upper BB, +11.6p above daily R3,
                 −1.1p below 1.35000, +24.55p from London session low).
  * 10:30:08Z — broker-side SL hit at 13486.9, −12.0p / −£24.00.

Spec (2026-11-04): a setup must EXPIRE when more than
``cfg.setup_max_age_seconds`` (default 1200 = 20 min) have elapsed between
the original EMA8 touch (``trigger_ts``) and the entry-level crossing.
Expired setups MUST NOT fire a broker entry, and any outstanding working
order MUST be cancelled before local state transitions to EXPIRED. A
subsequent EMA8 touch creates a NEW setup with a freshly computed entry.
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
    ARMED,
    CANCELLED,
    EXPIRED,
    IN_TRADE,
    ORDER_WAITING,
    PENDING_STATES,
    TERMINAL_STATES,
    Setup,
)


# Anchor at the incident's touch time so test timestamps match the
# production evidence verbatim where useful.
INCIDENT_TOUCH_TS = datetime(2026, 11, 4, 9, 30, 8, 428757, tzinfo=timezone.utc)
INCIDENT_FILL_TS  = datetime(2026, 11, 4, 10, 17, 22, 71595, tzinfo=timezone.utc)
INCIDENT_ENTRY_LEVEL = 13497.65
INCIDENT_FILL_PRICE  = 13498.9


class _IGRecorder(IGClientBase):
    """Captures which IG primitives are invoked + what they return."""

    def __init__(self):
        self.place_calls: List[Dict[str, Any]] = []
        self.market_calls: List[Dict[str, Any]] = []
        self.cancel_calls: List[Dict[str, Any]] = []
        self._working_orders: List[Dict[str, Any]] = []
        self._positions: List[Dict[str, Any]] = []
        self.next_cancel_status = "CANCELLED"      # or "FILLED" for race test
        self.next_fill_price: Optional[float] = INCIDENT_FILL_PRICE

    def place_working_order(self, direction, entry_level, stop_distance,
                             limit_distance, deal_reference):
        self.place_calls.append({
            "direction": direction, "entry_level": entry_level,
            "stop_distance": stop_distance, "limit_distance": limit_distance,
            "deal_reference": deal_reference,
        })
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
                           broker_sl_level=1,       # arbitrary; used in FILLED race
                           broker_tp_level=2, error=None)

    def close_open_position(self, deal_id, direction, size):
        return OrderResult(status="CLOSED", deal_id=deal_id,
                           deal_reference="", broker_sl_level=None,
                           broker_tp_level=None, error=None)

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
    """Minimal shape of an IntrabarTracker EntryCrossing / TouchEvent."""
    def __init__(self, direction, ts, price, entry_level, forming_ts=None,
                 live_ema_fast=None):
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
        "QUOTE_MAX_AGE_SECONDS": "30.0",         # don't let staleness fire first
        "EXECUTION_OWNER_ENFORCED": "false",
        "EMAPB_LOCK_DIR_OVERRIDE_FOR_TESTS": str(tmp_path),
        "SETUP_MAX_AGE_SECONDS": "1200",          # 20 minutes, spec default
    }
    env.update(overrides)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return load_config(env_file=None)


def _install_armed(svc, trigger_ts=INCIDENT_TOUCH_TS, state=ARMED,
                   setup_id="TEST-INC", deal_reference="EMAPB-B-TEST-INC",
                   deal_id=None):
    """Install an ARMED (or ORDER_WAITING) setup identical in shape to the
    incident's 5D79C8 record, so the regression tests exercise the exact
    trigger_ts arithmetic.
    """
    svc.active = Setup(
        setup_id=setup_id,
        direction="BUY",
        trigger_ts=trigger_ts,
        entry_level=INCIDENT_ENTRY_LEVEL,
        lookback_extreme=13494.65,
        deal_reference=deal_reference,
        deal_id=deal_id,
        state=state,
        audit={
            "intrabar_touch": True,
            "touch_tick_ts": trigger_ts.isoformat(),
            "touch_tick_price": 13485.55,
            "touch_live_ema_fast": 13486.106657233082,
            "forming_m5_ts": "2026-11-04T09:30:00+00:00",
            "trigger_open": 13485.55,
            "trigger_high": 13486.11,
            "trigger_low": 13485.55,
            "trigger_close": 13485.55,
            "pip_size": 1.0,
            "entry_buffer_pips": 3.0,
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
# Core regression — reproduces the 2026-11-04 10:17:22Z chain
# ─────────────────────────────────────────────────────────────────────

def test_incident_reproduction_delayed_market_entry_is_blocked(tmp_path, monkeypatch):
    """The 47-minute-late MARKET entry MUST NOT fire after expiry.

    Historical reality (setup 5D79C8):
      * ARMED  09:30:08Z @ entry_level=13497.65
      * FILL   10:17:22Z @ 13498.9 — this test asserts the fill path refuses.

    With cfg.setup_max_age_seconds=1200, the setup is stale by 47*60-1200
    = 1620s at the fill tick. _check_setup_expiry must transition ARMED
    → EXPIRED BEFORE _apply_intrabar_fill is reachable.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)

    # Simulate the service's step-level expiry check at the exact fill tick.
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=INCIDENT_FILL_TS, diag=diag)

    # State must have transitioned to EXPIRED; active cleared.
    assert svc.active is None
    kinds = [e["kind"] for e in diag["events"]]
    assert kinds == ["expired"]
    evt = diag["events"][0]
    assert evt["reason"] == "setup_max_age_exceeded"
    assert evt["state"] == "ARMED"
    assert evt["setup_id"] == "TEST-INC"
    assert evt["budget_seconds"] == pytest.approx(1200.0)
    # 10:17:22.071595 - 09:30:08.428757 = 2833.642838 seconds
    assert evt["age_seconds"] == pytest.approx(2833.64, abs=0.5)

    # A subsequent _apply_intrabar_fill call (what the live path would
    # do next) MUST NOT invoke open_market_entry — the active has
    # already been cleared. We simulate the invariant by re-installing
    # the ARMED setup then calling _apply_intrabar_fill directly at the
    # stale ts: the defence-in-depth guard must also refuse.
    _install_armed(svc)
    diag2: Dict[str, Any] = {"events": []}
    cross = _FakeEvent(direction="BUY", ts=INCIDENT_FILL_TS,
                       price=INCIDENT_FILL_PRICE,
                       entry_level=INCIDENT_ENTRY_LEVEL)
    svc._apply_intrabar_fill(cross,
                              now_utc=INCIDENT_FILL_TS + timedelta(seconds=1),
                              diag=diag2)
    assert ig.market_calls == [], "open_market_entry MUST NOT fire on expired setup"
    assert ig.place_calls == [], "no legacy working-order call either"
    assert svc.active is None, "defence-in-depth must also expire"
    assert any(e["kind"] == "expired" for e in diag2["events"])


def test_exactly_at_boundary_still_armed(tmp_path, monkeypatch):
    """Age equal to the budget must still be valid — strict >, not ≥.

    Guards against an off-by-one that would prematurely cancel a
    setup whose breakout is firing at exactly the 20-minute mark.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)

    now = INCIDENT_TOUCH_TS + timedelta(seconds=1200)      # exactly 20 min
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == ARMED
    assert diag["events"] == []


def test_one_second_past_boundary_expires(tmp_path, monkeypatch):
    """1201 s past the touch must expire."""
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)

    now = INCIDENT_TOUCH_TS + timedelta(seconds=1201)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is None
    assert diag["events"][0]["kind"] == "expired"
    assert svc.ledger.load_active() is None


def test_well_inside_window_does_not_expire(tmp_path, monkeypatch):
    """At +600 s (10 min) the setup must still be ARMED."""
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)
    now = INCIDENT_TOUCH_TS + timedelta(seconds=600)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == ARMED
    assert diag["events"] == []


def test_fill_at_t_plus_1199_still_executes(tmp_path, monkeypatch):
    """Breakout firing 19 minutes 59 seconds after touch must still fill.

    Also asserts that the defence-in-depth guard in _apply_intrabar_fill
    does not spuriously reject when inside the window.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    ig.next_fill_price = INCIDENT_FILL_PRICE
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)
    now = INCIDENT_TOUCH_TS + timedelta(seconds=1199)
    cross = _FakeEvent(direction="BUY", ts=now,
                       price=INCIDENT_FILL_PRICE,
                       entry_level=INCIDENT_ENTRY_LEVEL)
    diag: Dict[str, Any] = {"events": []}
    svc._apply_intrabar_fill(cross, now_utc=now + timedelta(seconds=1), diag=diag)
    # Inside the window + slippage within budget → market entry fires.
    # (Slippage = 13498.9 - 13497.65 = 1.25p < 2p budget.)
    assert len(ig.market_calls) == 1
    assert svc.active is not None
    assert svc.active.state == IN_TRADE


# ─────────────────────────────────────────────────────────────────────
# Spec #3 and #6 — outstanding broker order is cancelled before expiry
# ─────────────────────────────────────────────────────────────────────

def test_order_waiting_cancels_broker_order_on_expiry(tmp_path, monkeypatch):
    """A live ORDER_WAITING (legacy mode) must call cancel_working_order
    BEFORE the setup transitions to EXPIRED. An outstanding broker
    working order cannot be allowed to survive local expiry.
    """
    cfg = _cfg(tmp_path, monkeypatch,
                MECHANICAL_ENTRY_MODE="working_order")
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc, state=ORDER_WAITING,
                    deal_id="DID-WO-STALE",
                    deal_reference="EMAPB-B-STALE-ORDER")

    now = INCIDENT_TOUCH_TS + timedelta(seconds=1800)      # 30 min — stale
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)

    assert len(ig.cancel_calls) == 1, "broker cancel_working_order must fire"
    assert ig.cancel_calls[0]["deal_id"] == "DID-WO-STALE"
    assert ig.cancel_calls[0]["deal_reference"] == "EMAPB-B-STALE-ORDER"
    assert svc.active is None
    expired_evts = [e for e in diag["events"] if e["kind"] == "expired"]
    assert len(expired_evts) == 1
    assert expired_evts[0]["state"] == "ORDER_WAITING"


def test_cancel_race_filled_promotes_to_in_trade(tmp_path, monkeypatch):
    """If the broker reports FILLED when the expiry cancellation lands,
    the setup must be promoted to IN_TRADE rather than forced EXPIRED.
    Mirrors _cancel_outside_trading_hours semantics and the
    _check_cancellations contract.
    """
    cfg = _cfg(tmp_path, monkeypatch,
                MECHANICAL_ENTRY_MODE="working_order")
    ig = _IGRecorder()
    ig.next_cancel_status = "FILLED"
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc, state=ORDER_WAITING,
                    deal_id="DID-WO-RACE",
                    deal_reference="EMAPB-B-RACE")

    now = INCIDENT_TOUCH_TS + timedelta(seconds=1800)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == IN_TRADE
    assert svc.active.fill_price == pytest.approx(INCIDENT_ENTRY_LEVEL)
    kinds = [e["kind"] for e in diag["events"]]
    assert "cancel_race_filled" in kinds
    assert "expired" not in kinds


def test_order_waiting_observation_mode_local_drop(tmp_path, monkeypatch):
    """In observation mode an ORDER_WAITING expiry must NOT touch the IG
    client — it's a simulated order with no broker footprint.
    """
    cfg = _cfg(tmp_path, monkeypatch,
                EXECUTION_ENABLED="false",
                EMA_PULLBACK_LIVE_APPROVED="false",
                MECHANICAL_ENTRY_MODE="working_order")
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc, state=ORDER_WAITING,
                    deal_id="SIM-X", deal_reference="SIM-EMAPB-X")
    now = INCIDENT_TOUCH_TS + timedelta(seconds=1800)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert ig.cancel_calls == []
    assert svc.active is None


# ─────────────────────────────────────────────────────────────────────
# Spec #4 — fresh touch after expiry creates a new setup
# ─────────────────────────────────────────────────────────────────────

def test_fresh_touch_after_expiry_creates_new_setup_not_extended(tmp_path, monkeypatch):
    """After expiry, a subsequent EMA8 touch must create a new setup
    with a newly computed entry_level and setup_id (not an extension
    of the expired one).

    We simulate the flow directly via _open_setup_intrabar to isolate
    arming from the bar-source machinery. The first setup expires;
    the second arms at a later touch with a different entry_level.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)

    # Build 25 M5 bars so both touches (09:30 and 10:05) have a
    # well-formed 5-preceding lookback window with DISTINCT highs,
    # ensuring the second setup's entry_level cannot accidentally
    # coincide with the first.
    base = datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc)
    m5s = []
    for i in range(25):
        # Bars from 09:00 climb 0.3 per bar; from 10:00 onwards climb 1.0
        # per bar so the second preceding window (ending at 10:00) has
        # highs well above the first preceding window (ending at 09:25).
        if i < 12:
            close = 13480.0 + i * 0.3
        else:
            close = 13483.6 + (i - 12) * 1.0
        m5s.append(M5Bar(
            ts=base + timedelta(minutes=5 * i),
            open=close - 0.3, high=close + 0.7, low=close - 0.5, close=close,
        ))

    # Minimal H1 snapshot stub via SimpleNamespace — _open_setup_intrabar
    # only reads a few fields.
    from types import SimpleNamespace
    trend1 = SimpleNamespace(
        direction="BUY",
        h1_ts=base - timedelta(hours=1),
        h1_close=13479.0,
        ema_fast_now=13470.0, ema_mid_now=13465.0, ema_slow_now=13460.0,
        ema_fast_prev=13469.0, ema_mid_prev=13464.0, ema_slow_prev=13459.0,
        ordering_ok=True, slope_ok=True,
        h4_context=None,
        qualification=SimpleNamespace(
            enabled=True,
            ema8_slope_pips_per_hr=5.0, ema13_slope_pips_per_hr=4.0,
            ema20_slope_pips_per_hr=3.0,
            sep_8_13_pips=9.0, sep_13_20_pips=9.0,
            ema8_slope_gate=True, ema13_slope_gate=True, ema20_slope_gate=True,
            sep_8_13_pips_gate=True, sep_13_20_pips_gate=True,
            admission_allowed=True, admission_blocked_reasons=[],
            ema8_slope=5.0, ema13_slope=4.0, ema20_slope=3.0,
            sep_8_13=9.0, sep_13_20=9.0, sep_8_20=18.0,
        ),
    )

    # First EMA8 touch at 09:30:08.
    touch1_ts = base + timedelta(minutes=30, seconds=8, microseconds=428757)
    evt1 = _FakeEvent(direction="BUY", ts=touch1_ts,
                      price=13485.55,
                      entry_level=None,
                      forming_ts=base + timedelta(minutes=30),
                      live_ema_fast=13486.106657233082)
    diag1: Dict[str, Any] = {"events": []}
    svc._open_setup_intrabar(evt1, trend1, m5s, now_utc=touch1_ts, diag=diag1)
    assert svc.active is not None
    first_setup_id = svc.active.setup_id
    first_entry_level = svc.active.entry_level
    first_deal_ref = svc.active.deal_reference

    # Expire it.
    diag_exp: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(
        now_utc=touch1_ts + timedelta(seconds=1800), diag=diag_exp,
    )
    assert svc.active is None
    assert any(e["kind"] == "expired" for e in diag_exp["events"])

    # Second EMA8 touch 35 minutes later. Preceding window = bars
    # 09:35, 09:40, 09:45, 09:50, 09:55 — these bars have highs from
    # a different regime (10:00+ in the builder, or equivalent), so
    # the new entry_level is distinct from the first.
    touch2_ts = touch1_ts + timedelta(minutes=35)
    forming2 = touch2_ts.replace(second=0, microsecond=0)
    evt2 = _FakeEvent(direction="BUY", ts=touch2_ts,
                      price=13492.0,
                      entry_level=None,
                      forming_ts=forming2,
                      live_ema_fast=13493.0)
    diag2: Dict[str, Any] = {"events": []}
    svc._open_setup_intrabar(evt2, trend1, m5s, now_utc=touch2_ts, diag=diag2)
    assert svc.active is not None
    second_setup_id = svc.active.setup_id
    second_entry_level = svc.active.entry_level
    second_deal_ref = svc.active.deal_reference

    assert second_setup_id != first_setup_id, "fresh setup must have a new id"
    assert second_deal_ref != first_deal_ref, "fresh dealReference"
    assert second_entry_level != pytest.approx(first_entry_level), \
        "entry_level recomputed from new preceding window"


# ─────────────────────────────────────────────────────────────────────
# Spec #5 — EMA21-close cancellation is unchanged
# ─────────────────────────────────────────────────────────────────────

def test_ema21_close_cancellation_still_fires_before_expiry_window(tmp_path, monkeypatch):
    """A completed M5 close below EMA21 while ARMED and INSIDE the
    validity window must still cancel with reason m5_close_below_ema21,
    NOT setup_max_age_exceeded.
    """
    from ema_pullback.pullback import M5Context
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)

    # Inside window: 5 min after the touch.
    now = INCIDENT_TOUCH_TS + timedelta(minutes=5)
    bar = M5Bar(
        ts=now.replace(second=0, microsecond=0),
        open=13485.0, high=13486.0, low=13480.0, close=13479.0,
    )
    ctx = M5Context(bar=bar, ema_fast=13484.0, ema_mid=13483.0, ema_slow=13485.0)
    # BUY + close(13479) < ema_slow(13485) → EMA21 cancels.
    diag: Dict[str, Any] = {"events": []}
    svc._check_cancellations(ctx, trend=None, now_utc=now, diag=diag)
    assert svc.active is None
    kinds = [e["kind"] for e in diag["events"]]
    assert "cancelled" in kinds
    cancel_evt = next(e for e in diag["events"] if e["kind"] == "cancelled")
    assert cancel_evt["reason"] == "m5_close_below_ema21"


# ─────────────────────────────────────────────────────────────────────
# Spec #2 — exempt states + disabled-via-config
# ─────────────────────────────────────────────────────────────────────

def test_submitting_state_is_not_expired(tmp_path, monkeypatch):
    """SUBMITTING is broker-in-flight; the reconciler is the sole owner.
    _check_setup_expiry must leave it alone no matter how old.
    """
    from ema_pullback.state_machine import SUBMITTING
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc, state=SUBMITTING, deal_id="DID-INFL",
                    deal_reference="EMAPB-B-INFL")
    now = INCIDENT_TOUCH_TS + timedelta(hours=4)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == SUBMITTING
    assert diag["events"] == []
    assert ig.cancel_calls == []


def test_uncertain_state_is_not_expired(tmp_path, monkeypatch):
    from ema_pullback.state_machine import UNCERTAIN
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc, state=UNCERTAIN, deal_id="DID-UNC",
                    deal_reference="EMAPB-B-UNC")
    now = INCIDENT_TOUCH_TS + timedelta(hours=4)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == UNCERTAIN
    assert ig.cancel_calls == []


def test_escalated_state_is_not_expired(tmp_path, monkeypatch):
    from ema_pullback.state_machine import ESCALATED
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc, state=ESCALATED, deal_id="DID-ESC",
                    deal_reference="EMAPB-B-ESC")
    now = INCIDENT_TOUCH_TS + timedelta(hours=4)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == ESCALATED
    assert ig.cancel_calls == []


def test_in_trade_is_not_expired(tmp_path, monkeypatch):
    """IN_TRADE represents a live broker position — this method must
    never touch it. Exit lifecycle is the owner."""
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc, state=IN_TRADE,
                    deal_id="DID-POS", deal_reference="EMAPB-B-POS")
    svc.active.fill_price = 13498.9
    svc.active.fill_ts = INCIDENT_FILL_TS
    now = INCIDENT_TOUCH_TS + timedelta(hours=4)
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == IN_TRADE
    assert ig.cancel_calls == []


def test_disabled_via_non_positive_budget(tmp_path, monkeypatch):
    """A non-positive SETUP_MAX_AGE_SECONDS must disable the check
    entirely, preserving pre-patch behaviour for replay fixtures.
    """
    cfg = _cfg(tmp_path, monkeypatch, SETUP_MAX_AGE_SECONDS="0")
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)
    now = INCIDENT_FILL_TS           # 47 min past touch
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    assert svc.active is not None
    assert svc.active.state == ARMED
    assert diag["events"] == []


def test_terminal_states_untouched(tmp_path, monkeypatch):
    """CLOSED/CANCELLED/EXPIRED/SKIPPED/REJECTED are terminal; the
    expiry check must be a no-op if invoked against one by mistake.
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    # Install then flip to EXPIRED (simulating a leftover terminal state
    # accidentally re-entering the check path).
    _install_armed(svc, state=EXPIRED)
    now = INCIDENT_FILL_TS
    diag: Dict[str, Any] = {"events": []}
    svc._check_setup_expiry(now_utc=now, diag=diag)
    # No ledger side-effect, no IG side-effect.
    assert ig.cancel_calls == []
    assert diag["events"] == []
    # active still points to the EXPIRED setup — no cleanup side-effect either.
    assert svc.active is not None
    assert svc.active.state == EXPIRED


# ─────────────────────────────────────────────────────────────────────
# Spec #6 — invariant: no broker call after expiry under any route
# ─────────────────────────────────────────────────────────────────────

def test_apply_intrabar_fill_refuses_stale_setup_belt_and_braces(tmp_path, monkeypatch):
    """Even if step()'s top-level expiry check is somehow bypassed,
    _apply_intrabar_fill itself must refuse a stale setup. The 2026-11-04
    report explicitly requires expiry enforcement BEFORE any broker
    execution (spec #6).
    """
    cfg = _cfg(tmp_path, monkeypatch)
    ig = _IGRecorder()
    svc = EmaPullbackService(cfg=cfg, ig=ig)
    _install_armed(svc)

    # Stale by 1620s past the 20-minute budget.
    stale_fill_ts = INCIDENT_TOUCH_TS + timedelta(seconds=1800)
    cross = _FakeEvent(direction="BUY", ts=stale_fill_ts,
                       price=INCIDENT_FILL_PRICE,
                       entry_level=INCIDENT_ENTRY_LEVEL)
    diag: Dict[str, Any] = {"events": []}
    svc._apply_intrabar_fill(cross,
                              now_utc=stale_fill_ts + timedelta(seconds=1),
                              diag=diag)
    assert ig.market_calls == []
    assert ig.place_calls == []
    assert svc.active is None
    assert any(e["kind"] == "expired" for e in diag["events"])
