"""Phase 5 Stage E — strategy decision-event bus regression tests."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import pytest

from sim.event_bus import EventBus, Event, PositionState


def test_chronological_order():
    bus = EventBus()
    seen = []
    bus.subscribe("MARKET_TICK", lambda ev, _b: seen.append(ev.ts_utc_ns))
    bus.emit("MARKET_TICK", 2_000_000, {"bid": 1.33})
    bus.emit("MARKET_TICK", 1_000_000, {"bid": 1.33})
    bus.emit("MARKET_TICK", 3_000_000, {"bid": 1.33})
    bus.run()
    assert seen == [1_000_000, 2_000_000, 3_000_000]


def test_insertion_order_same_ns():
    bus = EventBus()
    seen = []
    for ev_type in ["M5_CANDLE_COMPLETED", "H1_CANDLE_COMPLETED"]:
        bus.subscribe(ev_type, lambda ev, _b: seen.append(ev.type))
    bus.emit("M5_CANDLE_COMPLETED", 1_000, {})
    bus.emit("H1_CANDLE_COMPLETED", 1_000, {})
    bus.run()
    assert seen == ["M5_CANDLE_COMPLETED", "H1_CANDLE_COMPLETED"]


def test_handler_can_enqueue():
    bus = EventBus()
    seen = []

    def on_signal(ev, b):
        seen.append(("sig", ev.ts_utc_ns))
        b.emit("BROKER_ORDER_REQUEST", ev.ts_utc_ns + 100, {"side": "BUY"})

    def on_req(ev, _b):
        seen.append(("req", ev.ts_utc_ns))

    bus.subscribe("STRATEGY_SIGNAL", on_signal)
    bus.subscribe("BROKER_ORDER_REQUEST", on_req)
    bus.emit("STRATEGY_SIGNAL", 5_000, {})
    bus.run()
    assert seen == [("sig", 5_000), ("req", 5_100)]


def test_position_registry_round_trip():
    bus = EventBus()
    p = PositionState(
        pos_key="GBPUSD|BB_BOUNCE_L", deal_id="DIAAAAA_1", strategy="BB_BOUNCE_L",
        pair="GBPUSD", direction="BUY", size=2.0, entry_price=13300.0,
        opened_ts_ns=1_000_000, stop_level=13290.0, limit_level=13320.0,
    )
    bus.register_position(p)
    assert bus.position("GBPUSD|BB_BOUNCE_L") is p
    assert "GBPUSD|BB_BOUNCE_L" in bus.positions()


def test_checkpoint_restore_round_trip(tmp_path):
    bus = EventBus()
    bus.subscribe("MARKET_TICK", lambda ev, _b: None)
    for i in range(5):
        bus.emit("MARKET_TICK", 1_000 + i, {"bid": 1.33 + i * 0.0001})
    bus.run()
    ck = tmp_path / "ck.jsonl"
    bus.checkpoint(ck)
    assert ck.exists()
    bus2 = EventBus.from_jsonl(ck)
    seen = []
    bus2.subscribe("MARKET_TICK", lambda ev, _b: seen.append(ev.payload["bid"]))
    bus2.run()
    assert len(seen) == 5


def test_unknown_event_type_rejected():
    bus = EventBus()
    with pytest.raises(ValueError):
        bus.subscribe("NOT_A_REAL_EVENT", lambda e, _b: None)
    with pytest.raises(ValueError):
        bus.emit("NOT_A_REAL_EVENT", 1_000)


def test_multi_strategy_isolation():
    """Two position-keys with distinct handlers do not cross-fire."""
    bus = EventBus()
    seen_a: list[int] = []
    seen_b: list[int] = []

    def on_update_a(ev, _b):
        if ev.payload.get("pos_key") == "A":
            seen_a.append(ev.ts_utc_ns)

    def on_update_b(ev, _b):
        if ev.payload.get("pos_key") == "B":
            seen_b.append(ev.ts_utc_ns)

    bus.subscribe("POSITION_UPDATE", on_update_a)
    bus.subscribe("POSITION_UPDATE", on_update_b)
    bus.emit("POSITION_UPDATE", 1, {"pos_key": "A"})
    bus.emit("POSITION_UPDATE", 2, {"pos_key": "B"})
    bus.run()
    assert seen_a == [1] and seen_b == [2]


def test_backward_timestamp_is_clamped():
    """Attempting to emit an event in the past clamps to current clock
    so the chronological invariant holds."""
    bus = EventBus()
    seen: list[int] = []
    bus.subscribe("MARKET_TICK", lambda ev, _b: seen.append(ev.ts_utc_ns))
    bus.emit("MARKET_TICK", 10_000)
    bus.run()  # drains to ts=10_000
    bus.emit("MARKET_TICK", 1_000)  # clamped
    bus.run()
    assert seen == [10_000, 10_000]
