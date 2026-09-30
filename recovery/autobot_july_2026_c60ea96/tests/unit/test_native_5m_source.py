"""
Unit tests for native_5m_source.py — the CHART:{epic}:5MINUTE ingest
path that replaces tick-aggregation in candle_builder.

Covers:
  1. NativeFiveMinListener emits exactly once per CONS_END=="1" update,
     with the correct payload shape fired through the 5m-close callback
     chain.
  2. seed_builder_from_cache populates candle_builder._BUILDER.candles
     from per-pair CSVs under /opt/tradingbot/cache.
  3. Indicator enrichment produces non-NaN output on the first native
     bar when seed-from-cache is present.
  4. Stub behaviour: candle_builder.update_candles / update_tick /
     update_from_tick raise NotImplementedError with a pointed message.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Fake item_update mirroring Lightstreamer's ItemUpdate surface
# ---------------------------------------------------------------------------

class FakeItemUpdate:
    def __init__(self, item_name: str, values: Dict[str, Any], changed: Dict[str, bool] = None):
        self._item_name = item_name
        self._values = values
        self._changed = changed or {k: True for k in values}

    def getItemName(self) -> str:
        return self._item_name

    def isValueChanged(self, field: str) -> bool:
        return self._changed.get(field, False)

    def getValue(self, field: str) -> Any:
        return self._values.get(field)


# ---------------------------------------------------------------------------
# 1. Listener emits once per CONS_END=="1"
# ---------------------------------------------------------------------------

def test_listener_emits_on_cons_end():
    import native_5m_source
    items = {"CHART:CS.D.GBPUSD.TODAY.IP:5MINUTE": ("GBPUSD", "CS.D.GBPUSD.TODAY.IP")}

    captured: List[tuple] = []

    def on_close(sym: str, epic: str, candle_row: Dict[str, Any]):
        captured.append((sym, epic, candle_row))

    listener = native_5m_source.NativeFiveMinListener(items, on_close)

    # UTM = epoch-ms for 2026-04-23 08:30 UTC
    utm = int(datetime(2026, 4, 23, 8, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)

    # Intermediate update: no CONS_END. Should NOT emit.
    listener.onItemUpdate(FakeItemUpdate(
        list(items.keys())[0],
        {
            "UTM": str(utm),
            "CONS_END": "0",
            "BID_OPEN": "13500.0", "BID_HIGH": "13500.0",
            "BID_LOW": "13499.0", "BID_CLOSE": "13499.5",
            "OFR_OPEN": "13501.0", "OFR_HIGH": "13501.0",
            "OFR_LOW": "13500.0", "OFR_CLOSE": "13500.5",
            "CONS_TICK_COUNT": "100",
        },
    ))
    assert len(captured) == 0, f"emitted on non-close update: {captured}"

    # Close update: CONS_END=1. Should emit exactly once.
    listener.onItemUpdate(FakeItemUpdate(
        list(items.keys())[0],
        {
            "UTM": str(utm),
            "CONS_END": "1",
            "BID_OPEN": "13500.0", "BID_HIGH": "13502.0",
            "BID_LOW": "13498.0", "BID_CLOSE": "13501.0",
            "OFR_OPEN": "13501.0", "OFR_HIGH": "13503.0",
            "OFR_LOW": "13499.0", "OFR_CLOSE": "13502.0",
            "CONS_TICK_COUNT": "441",
        },
    ))
    assert len(captured) == 1, f"expected 1 emission, got {len(captured)}"

    sym, epic, row = captured[0]
    assert sym == "GBPUSD"
    assert epic == "CS.D.GBPUSD.TODAY.IP"
    # Mid-price: (bid+ofr)/2 per field
    assert row["open"] == pytest.approx(13500.5)
    assert row["high"] == pytest.approx(13502.5)
    assert row["low"] == pytest.approx(13498.5)
    assert row["close"] == pytest.approx(13501.5)
    assert row["time"] == datetime(2026, 4, 23, 8, 30, 0, tzinfo=timezone.utc)

    # Dedup: a repeat CONS_END=1 with same UTM must not re-emit.
    listener.onItemUpdate(FakeItemUpdate(
        list(items.keys())[0],
        {
            "UTM": str(utm),
            "CONS_END": "1",
            "BID_OPEN": "13500.0", "BID_HIGH": "13502.0",
            "BID_LOW": "13498.0", "BID_CLOSE": "13501.0",
            "OFR_OPEN": "13501.0", "OFR_HIGH": "13503.0",
            "OFR_LOW": "13499.0", "OFR_CLOSE": "13502.0",
            "CONS_TICK_COUNT": "441",
        },
    ))
    assert len(captured) == 1, (
        f"dedup failed: second CONS_END=1 for same UTM re-emitted; captured={len(captured)}"
    )


def test_listener_fires_registered_callback_chain():
    """_emit_native_close plumbing — a close event must reach every
    callback registered via candle_builder.register_5m_close_callback."""
    import native_5m_source
    import candle_builder

    # Snapshot and restore, so other tests' registrations (candle_archive
    # etc.) survive this test.
    _original_callbacks = list(candle_builder._5M_CLOSE_CALLBACKS)
    received: List[Dict[str, Any]] = []
    probe = lambda payload: received.append(payload)  # noqa: E731
    candle_builder.register_5m_close_callback(probe)

    items = {"CHART:CS.D.EURUSD.TODAY.IP:5MINUTE": ("EURUSD", "CS.D.EURUSD.TODAY.IP")}
    listener = native_5m_source.NativeFiveMinListener(items, native_5m_source._emit_native_close)

    utm = int(datetime(2026, 4, 23, 7, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
    listener.onItemUpdate(FakeItemUpdate(
        list(items.keys())[0],
        {
            "UTM": str(utm), "CONS_END": "1",
            "BID_OPEN": "11700.0", "BID_HIGH": "11702.0",
            "BID_LOW": "11695.0", "BID_CLOSE": "11697.0",
            "OFR_OPEN": "11700.6", "OFR_HIGH": "11702.6",
            "OFR_LOW": "11695.6", "OFR_CLOSE": "11697.6",
            "CONS_TICK_COUNT": "241",
        },
    ))

    assert len(received) == 1
    payload = received[0]
    assert payload["symbol"] == "EURUSD"
    assert payload["epic"] == "CS.D.EURUSD.TODAY.IP"
    assert payload["timeframe"] == "5m"
    assert payload["source"] == "LS_NATIVE_5M"
    assert payload["candle"]["open"] == pytest.approx(11700.3)
    assert payload["candle"]["high"] == pytest.approx(11702.3)
    assert payload["candle"]["low"] == pytest.approx(11695.3)
    assert payload["candle"]["close"] == pytest.approx(11697.3)
    assert payload["candle"]["timestamp"] == datetime(2026, 4, 23, 7, 30, tzinfo=timezone.utc)
    assert payload["bucket_epoch"] == int(utm / 1000)

    # df_5m should be present (the builder re-ran indicators after append)
    assert "candles_5m_closed_df" in payload
    assert isinstance(payload["candles_5m_closed_df"], pd.DataFrame)

    # Cleanup: remove just our probe callback + restore original list if
    # tests_order clobbered something. Then clear the test bar from the
    # builder buffer.
    candle_builder.unregister_5m_close_callback(probe)
    for cb in _original_callbacks:
        if cb not in candle_builder._5M_CLOSE_CALLBACKS:
            candle_builder._5M_CLOSE_CALLBACKS.append(cb)
    candle_builder._BUILDER.candles.pop("EURUSD", None)
    candle_builder._BUILDER._df_raw.pop("EURUSD", None)
    candle_builder._BUILDER._df_ind.pop("EURUSD", None)


# ---------------------------------------------------------------------------
# 2. seed_builder_from_cache
# ---------------------------------------------------------------------------

def test_seed_builder_from_cache(monkeypatch, tmp_path):
    import native_5m_source
    import candle_builder

    # Point CACHE_DIR at a temp dir and write a synthetic GBPUSD CSV.
    fake_cache = tmp_path / "cache"
    fake_cache.mkdir()
    rows = []
    base_ts = datetime(2026, 4, 23, 6, 0, 0, tzinfo=timezone.utc)
    for i in range(30):
        ts = base_ts + timedelta(minutes=5 * i)
        rows.append({
            "timestamp": ts.isoformat(),
            "open": 13500.0 + i * 0.1,
            "high": 13500.5 + i * 0.1,
            "low": 13499.5 + i * 0.1,
            "close": 13500.0 + i * 0.1,
        })
    pd.DataFrame(rows).to_csv(fake_cache / "GBPUSD_candles.csv", index=False)

    monkeypatch.setattr(native_5m_source, "CACHE_DIR", str(fake_cache))

    # Make sure builder is empty for this symbol
    candle_builder._BUILDER.candles.pop("GBPUSD", None)
    candle_builder._BUILDER._df_raw.pop("GBPUSD", None)
    candle_builder._BUILDER._df_ind.pop("GBPUSD", None)

    counts = native_5m_source.seed_builder_from_cache({"GBPUSD": "CS.D.GBPUSD.TODAY.IP"})
    assert counts["GBPUSD"] == 30, f"expected 30 rows seeded, got {counts}"
    assert len(candle_builder._BUILDER.candles["GBPUSD"]) == 30

    # Cleanup
    candle_builder._BUILDER.candles.pop("GBPUSD", None)
    candle_builder._BUILDER._df_raw.pop("GBPUSD", None)
    candle_builder._BUILDER._df_ind.pop("GBPUSD", None)


def test_seed_from_missing_cache_is_nonfatal(monkeypatch, tmp_path):
    """Absent cache file: seed returns 0, no exception, buffer stays empty."""
    import native_5m_source
    import candle_builder

    fake_cache = tmp_path / "empty_cache"
    fake_cache.mkdir()
    monkeypatch.setattr(native_5m_source, "CACHE_DIR", str(fake_cache))

    # Preemptively clear any existing state
    candle_builder._BUILDER.candles.pop("USDJPY", None)

    counts = native_5m_source.seed_builder_from_cache({"USDJPY": "CS.D.USDJPY.TODAY.IP"})
    assert counts["USDJPY"] == 0
    assert candle_builder._BUILDER.candles.get("USDJPY") in (None, [])


# ---------------------------------------------------------------------------
# 3. Indicator enrichment non-NaN after seed + first native bar
# ---------------------------------------------------------------------------

def test_indicator_enrichment_post_seed_and_first_bar(monkeypatch, tmp_path):
    """With 30 seeded bars + 1 native bar, indicators should be non-NaN
    on the latest row (BB warmup period = 20)."""
    import native_5m_source
    import candle_builder

    # Seed
    fake_cache = tmp_path / "cache"
    fake_cache.mkdir()
    base_ts = datetime(2026, 4, 23, 6, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(30):
        ts = base_ts + timedelta(minutes=5 * i)
        # Slight drift so BB isn't degenerate
        import math
        drift = math.sin(i / 4.0) * 2.0
        o = 13500.0 + drift
        rows.append({
            "timestamp": ts.isoformat(),
            "open": o, "high": o + 0.5, "low": o - 0.5, "close": o + 0.2,
        })
    pd.DataFrame(rows).to_csv(fake_cache / "EURUSD_candles.csv", index=False)
    monkeypatch.setattr(native_5m_source, "CACHE_DIR", str(fake_cache))

    candle_builder._BUILDER.candles.pop("EURUSD", None)
    native_5m_source.seed_builder_from_cache({"EURUSD": "CS.D.EURUSD.TODAY.IP"})

    # Inject one native bar via the emit function
    native_bar = {
        "time": base_ts + timedelta(minutes=5 * 30),
        "open": 13500.0, "high": 13500.8, "low": 13499.2, "close": 13500.5,
    }
    native_5m_source._emit_native_close("EURUSD", "CS.D.EURUSD.TODAY.IP", native_bar)

    df = candle_builder.get_df("EURUSD")
    assert len(df) >= 30, f"expected ≥30 bars, got {len(df)}"
    # Check indicator presence on the latest row
    last = df.iloc[-1]
    # BB_20 should be populated past warmup
    bb_cols = [c for c in df.columns if c.startswith("BB_UPPER")]
    assert bb_cols, f"no BB_UPPER_* column in {list(df.columns)}"
    bb_upper = last[bb_cols[0]]
    assert pd.notna(bb_upper), f"BB_UPPER NaN on last row; df columns={list(df.columns)}"

    # EMA_50 should also be populated
    assert "EMA_50" in df.columns
    assert pd.notna(last["EMA_50"]), f"EMA_50 NaN on last row"

    # Cleanup
    candle_builder._BUILDER.candles.pop("EURUSD", None)
    candle_builder._BUILDER._df_raw.pop("EURUSD", None)
    candle_builder._BUILDER._df_ind.pop("EURUSD", None)


# ---------------------------------------------------------------------------
# 4. Stub behaviour — import succeeds, call raises
# ---------------------------------------------------------------------------

def test_update_candles_stub_raises_with_pointed_message():
    import candle_builder
    with pytest.raises(NotImplementedError) as exc_info:
        candle_builder.update_candles("GBPUSD", 13500.0, 13501.0, None, 0)
    msg = str(exc_info.value)
    assert "native-5m migration" in msg
    assert "native_5m_source.py" in msg
    assert "migrate/native-5m-candle-feed" in msg


def test_update_tick_stub_is_alias():
    import candle_builder
    with pytest.raises(NotImplementedError):
        candle_builder.update_tick("GBPUSD", 13500.0, 13501.0)


def test_update_from_tick_stub_is_alias():
    import candle_builder
    with pytest.raises(NotImplementedError):
        candle_builder.update_from_tick("GBPUSD", 13500.0, 13501.0)


def test_sentinel_style_import_still_succeeds():
    """sentinel.py:46 imports these names. The import must not fail —
    only the call site does."""
    from candle_builder import update_candles, update_tick, update_from_tick  # noqa: F401


# ---------------------------------------------------------------------------
# 5. candle_archive still wired on 5m-close (regression sanity)
# ---------------------------------------------------------------------------

def test_candle_archive_callback_registered_after_import():
    """candle_archive registers its archive_candle function via a side-
    effect import at module load (candle_archive.py:190-191 calls
    register_5m_close_callback). This test asserts that registration
    landed in _5M_CLOSE_CALLBACKS — nothing in the codebase clears the
    list (grep confirmed), so the first import is sufficient and we
    don't re-register defensively. If a future test DOES clear the
    list, that test is the bug."""
    import candle_builder
    import candle_archive

    archive_cb = getattr(candle_archive, "archive_candle", None)
    assert archive_cb is not None, "candle_archive.archive_candle missing"
    assert archive_cb in candle_builder._5M_CLOSE_CALLBACKS, (
        "candle_archive.archive_candle was not registered on import — "
        "candle_archive.py:190-191 should have added it"
    )


# ---------------------------------------------------------------------------
# 4. subscribe_native_5m — symmetry with streamer_ls MARKET subscribe path
# ---------------------------------------------------------------------------

class _FakeSubscription:
    """Drop-in replacement for lightstreamer.client.Subscription that
    records construction args + listener attachment so tests can inspect
    what subscribe_native_5m built without instantiating a real LS
    client."""
    def __init__(self, mode, items, fields):
        self.mode = mode
        self.items = list(items)
        self.fields = list(fields)
        self.listener = None

    def addListener(self, listener):
        self.listener = listener


def test_subscribe_native_5m_rewrites_input_epic_to_today(monkeypatch):
    """CFD.IP epics in EPICS_JSON must be rewritten to TODAY.IP before
    CHART items are built — the CHART:5MINUTE adapter rejects CFD on
    demo ("Invalid account type"). Symmetric with the rewrite
    streamer_ls._split_today_cfd applies on the MARKET tick path. This
    is the May 2026 outage that motivated the fix."""
    import native_5m_source

    monkeypatch.setattr(native_5m_source, "Subscription", _FakeSubscription)

    captured = {}

    def fake_subscribe(sub):
        # Simulate IG confirming the subscription immediately so the
        # wait_for_subscription_outcome path returns cleanly.
        captured["sub"] = sub
        sub.listener.onSubscription()

    fake_client = MagicMock()
    fake_client.subscribe.side_effect = fake_subscribe

    epic_map = {
        "GBPUSD": "CS.D.GBPUSD.CFD.IP",
        "EURUSD": "CS.D.EURUSD.CFD.IP",
        "USDJPY": "CS.D.USDJPY.CFD.IP",
        "USDCAD": "CS.D.USDCAD.CFD.IP",
    }
    sub, listener = native_5m_source.subscribe_native_5m(fake_client, epic_map)

    assert sorted(captured["sub"].items) == [
        "CHART:CS.D.EURUSD.TODAY.IP:5MINUTE",
        "CHART:CS.D.GBPUSD.TODAY.IP:5MINUTE",
        "CHART:CS.D.USDCAD.TODAY.IP:5MINUTE",
        "CHART:CS.D.USDJPY.TODAY.IP:5MINUTE",
    ]
    assert not any("CFD.IP" in item for item in captured["sub"].items)
    # Listener's tuple should also carry the TODAY epic so downstream
    # _emit_close_payload sees the same epic that was subscribed (matches
    # MARKET PriceListener which stores the chosen-candidate epic, not
    # the raw EPICS_JSON value).
    assert listener.items_by_name["CHART:CS.D.GBPUSD.TODAY.IP:5MINUTE"] == (
        "GBPUSD", "CS.D.GBPUSD.TODAY.IP"
    )


def test_subscribe_native_5m_raises_on_subscription_error(monkeypatch):
    """A subscription error from IG must surface as a RuntimeError.
    Pre-fix behaviour (log and continue with no bar source) let the
    2026-05-14 outage go undetected for hours — silent partial failure
    is what we are explicitly eliminating."""
    import native_5m_source

    monkeypatch.setattr(native_5m_source, "Subscription", _FakeSubscription)
    # Keep the timeout tight so a hypothetical regression that hangs
    # doesn't slow the suite.
    monkeypatch.setattr(native_5m_source, "SUBSCRIBE_WAIT_SECS", 0.5)

    def fake_subscribe(sub):
        sub.listener.onSubscriptionError(24, "Invalid account type")

    fake_client = MagicMock()
    fake_client.subscribe.side_effect = fake_subscribe

    with pytest.raises(RuntimeError) as exc_info:
        native_5m_source.subscribe_native_5m(
            fake_client, {"GBPUSD": "CS.D.GBPUSD.CFD.IP"}
        )
    msg = str(exc_info.value)
    assert "24" in msg
    assert "Invalid account type" in msg


def test_subscribe_native_5m_raises_on_subscription_timeout(monkeypatch):
    """If IG never confirms and never errors, wait_for_subscription_outcome
    must return a ("timeout", ...) tuple and subscribe_native_5m must
    raise. Pins the timeout-as-failure semantics — a future regression
    where the wait returns None on timeout would silently let callers
    proceed with an un-confirmed subscription."""
    import native_5m_source

    monkeypatch.setattr(native_5m_source, "Subscription", _FakeSubscription)
    monkeypatch.setattr(native_5m_source, "SUBSCRIBE_WAIT_SECS", 0.2)

    # fake_client.subscribe is a no-op — neither onSubscription nor
    # onSubscriptionError fires.
    fake_client = MagicMock()
    fake_client.subscribe.return_value = None

    with pytest.raises(RuntimeError) as exc_info:
        native_5m_source.subscribe_native_5m(
            fake_client, {"GBPUSD": "CS.D.GBPUSD.CFD.IP"}
        )
    assert "timeout" in str(exc_info.value).lower()


def test_subscribe_native_5m_returns_on_success(monkeypatch):
    """Happy path: onSubscription fires before timeout -> returns
    (Subscription, NativeFiveMinListener) cleanly. Listener returned is
    the one attached to the subscription."""
    import native_5m_source

    monkeypatch.setattr(native_5m_source, "Subscription", _FakeSubscription)

    def fake_subscribe(sub):
        sub.listener.onSubscription()

    fake_client = MagicMock()
    fake_client.subscribe.side_effect = fake_subscribe

    sub, listener = native_5m_source.subscribe_native_5m(
        fake_client, {"GBPUSD": "CS.D.GBPUSD.CFD.IP"}
    )
    assert isinstance(sub, _FakeSubscription)
    assert isinstance(listener, native_5m_source.NativeFiveMinListener)
    assert sub.listener is listener
