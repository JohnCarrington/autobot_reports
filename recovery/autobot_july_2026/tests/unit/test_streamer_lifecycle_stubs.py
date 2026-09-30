"""FIX-B (2026-07-10): streamer-listener lifecycle coverage.

Incident context: on 2026-07-10 09:28:00 UTC the Lightstreamer Haxe
dispatcher raised

    Exception: 'PriceListener' object has no attribute 'onUnsubscription'

three times during graceful shutdown. The library's dispatchToOne guard
(ls_python_client_haxe.py:1182-1187) caught each one and logged
"Uncaught exception"; the process still exited cleanly (0). That guard
is *the* containment layer — but the missing attribute is what pumped
noise through it. Adding lifecycle stubs on both listeners is the
correct containment: the LS callback path never has to fall into the
uncaught-exception branch for these events.

Tests here:

  (e1) Every method the LS Subscription/Client dispatchers probe is
       present on our listener classes.
  (e2) Invoking those callbacks does not raise, even with sentinel args.
  (e3) A simulated Lightstreamer/haxe fault path (attribute miss on ONE
       listener method) is contained by the reconnect layer's exception
       guard rather than propagating to the LS event thread — i.e. the
       controller's status-listener path invokes the controller's
       reconnect routine, not sys.exit.
"""
from __future__ import annotations

import sys
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

import streamer_ls  # noqa: E402
import native_5m_source  # noqa: E402


# The set of methods the Haxe SubscriptionEventDispatcher probes. See
# ls_python_client_haxe.py around line 1440-1544. Missing any of these
# fires "Uncaught exception" in the LS ERROR log at unsub time.
SUBSCRIPTION_LIFECYCLE_METHODS = (
    "onSubscription",
    "onUnsubscription",
    "onSubscriptionError",
    "onEndOfSnapshot",
    "onClearSnapshot",
    "onItemLostUpdates",
    "onItemUpdate",
    "onRealMaxFrequency",
    "onCommandSecondLevelSubscriptionError",
    "onCommandSecondLevelItemLostUpdates",
)

# ClientEventDispatcher's expected methods.
CLIENT_LIFECYCLE_METHODS = (
    "onServerError",
    "onStatusChange",
    "onPropertyChange",
    "onListenStart",
    "onListenEnd",
)


def _make_price_listener():
    return streamer_ls.PriceListener(
        symbol="GBPUSD",
        epic="CS.D.GBPUSD.TODAY.IP",
        callback=lambda *a, **kw: None,
        first_event=Event(),
        error_event=Event(),
        error_store={},
    )


def _make_five_min_listener():
    items = {"CHART:CS.D.GBPUSD.TODAY.IP:5MINUTE": ("GBPUSD", "CS.D.GBPUSD.TODAY.IP")}
    return native_5m_source.NativeFiveMinListener(
        items_by_name=items,
        on_close_payload=lambda *a, **kw: None,
    )


@pytest.mark.parametrize("method", SUBSCRIPTION_LIFECYCLE_METHODS)
def test_price_listener_has_lifecycle_method(method):
    listener = _make_price_listener()
    assert callable(getattr(listener, method, None)), (
        f"PriceListener missing {method} — LS dispatcher would raise "
        f"AttributeError inside dispatchToOne on this event"
    )


@pytest.mark.parametrize("method", SUBSCRIPTION_LIFECYCLE_METHODS)
def test_five_min_listener_has_lifecycle_method(method):
    listener = _make_five_min_listener()
    assert callable(getattr(listener, method, None)), (
        f"NativeFiveMinListener missing {method}"
    )


@pytest.mark.parametrize("method", CLIENT_LIFECYCLE_METHODS)
def test_status_listener_has_lifecycle_method(method):
    controller = MagicMock()
    listener = streamer_ls._LSStatusListener(controller)
    assert callable(getattr(listener, method, None)), (
        f"_LSStatusListener missing {method}"
    )


def test_lifecycle_stubs_do_not_raise():
    """Invoking each stub with sentinel args must not raise. This is the
    property the LS Haxe dispatcher relies on — if any of these throw,
    the ERROR path 'Uncaught exception' fires again."""
    p = _make_price_listener()
    p.onUnsubscription()
    p.onClearSnapshot("CS.D.GBPUSD.TODAY.IP", 1)
    p.onItemLostUpdates("CS.D.GBPUSD.TODAY.IP", 1, 3)
    p.onRealMaxFrequency("unlimited")
    p.onCommandSecondLevelSubscriptionError(23, "no 2L", "key1")
    p.onCommandSecondLevelItemLostUpdates(2, "key1")

    f = _make_five_min_listener()
    f.onUnsubscription()
    f.onRealMaxFrequency(1.0)
    f.onCommandSecondLevelSubscriptionError(1, "x", "k")
    f.onCommandSecondLevelItemLostUpdates(1, "k")

    controller = MagicMock()
    s = streamer_ls._LSStatusListener(controller)
    s.onListenStart()
    s.onListenEnd()
    # And a benign onStatusChange must not touch the controller reconnect
    # path (only DISCONNECTED without WILL-RETRY does).
    s.onStatusChange("CONNECTED:HTTP-STREAMING")
    assert controller._trigger_recovery.call_count == 0


def test_terminal_disconnect_triggers_reconnect_not_exit():
    """FIX-B (e3): a terminal DISCONNECTED status must be handled by
    LSController._trigger_recovery — the reconnect layer — not by
    propagating out of the LS callback and killing the process."""
    controller = MagicMock()
    listener = streamer_ls._LSStatusListener(controller)

    listener.onStatusChange("DISCONNECTED")

    controller._trigger_recovery.assert_called_once()
    reason = controller._trigger_recovery.call_args.kwargs.get("reason", "")
    assert "DISCONNECTED" in reason


def test_will_retry_disconnect_does_not_reconnect():
    """WILL-RETRY is the library's own auto-reconnect state; the
    controller must NOT double-drive recovery on that (defensive
    regression on the existing branch in _LSStatusListener.onStatusChange)."""
    controller = MagicMock()
    listener = streamer_ls._LSStatusListener(controller)
    listener.onStatusChange("DISCONNECTED:WILL-RETRY")
    assert controller._trigger_recovery.call_count == 0


def test_onserver_error_routes_to_reconnect_layer():
    """FIX-B: any onServerError must be caught by the reconnect layer, not
    escape the streamer's supervision."""
    controller = MagicMock()
    listener = streamer_ls._LSStatusListener(controller)
    listener.onServerError(21, "boom")
    controller._trigger_recovery.assert_called_once()
    reason = controller._trigger_recovery.call_args.kwargs.get("reason", "")
    assert "server_error" in reason and "21" in reason
