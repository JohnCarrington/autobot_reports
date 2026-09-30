"""Tests for ITEM 4 — subscription-mode assert in streamer_ls."""

from __future__ import annotations

import json
import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # streamer_ls imports ig_auth which checks env credentials at import
    # time. If ig_auth is already loaded from a prior test run, reuse it;
    # otherwise stub with something safe.
    if "ig_auth" not in sys.modules:
        import types
        fake = types.ModuleType("ig_auth")
        fake.get_ig_session = lambda: (None, {"CST": "x", "X-SECURITY-TOKEN": "y"}, "acc")
        sys.modules["ig_auth"] = fake
    monkeypatch.setenv("EPICS_JSON", json.dumps({
        "GBPUSD": "CS.D.GBPUSD.CFD.IP",
        "EURUSD": "CS.D.EURUSD.CFD.IP",
    }))
    monkeypatch.setenv("ALERT_HOST_LABEL", "TESTHOST")
    import streamer_ls
    streamer_ls._reset_subscription_assert_state_for_tests()
    return streamer_ls


def test_confirmed_set_equals_expected_no_alert(_isolate, monkeypatch):
    sl = _isolate
    sent = []
    monkeypatch.setattr(sl, "_try_send_subscription_alert",
                        lambda m: sent.append(m))
    sl._record_market_confirm("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              "MARKET:CS.D.GBPUSD.TODAY.IP",
                              granted_mode="MERGE", requested_mode="MERGE",
                              max_freq="unfiltered")
    sl._record_market_confirm("EURUSD", "CS.D.EURUSD.TODAY.IP",
                              "MARKET:CS.D.EURUSD.TODAY.IP",
                              granted_mode="MERGE", requested_mode="MERGE",
                              max_freq="unfiltered")
    assert sent == []


def test_superset_alerts_immediately(_isolate, monkeypatch):
    """Confirm four pairs when EPICS_JSON has only two — the incident
    class. Uses the real _try_send_subscription_alert (telegram stubbed)
    so the once-per-process latch is exercised end-to-end."""
    sl = _isolate
    calls = []
    class _tg:
        send_telegram_message = staticmethod(
            lambda text, parse_mode="": calls.append(text)
        )
    monkeypatch.setitem(sys.modules, "telegram_alerts", _tg)
    for pair in ("GBPUSD", "EURUSD", "USDJPY", "USDCAD"):
        sl._record_market_confirm(pair, f"CS.D.{pair}.TODAY.IP",
                                  f"MARKET:CS.D.{pair}.TODAY.IP",
                                  granted_mode="MERGE",
                                  requested_mode="MERGE",
                                  max_freq="unfiltered")
    assert len(calls) == 1, calls
    msg = calls[0]
    assert "SUBSCRIPTION MISMATCH" in msg
    assert "configured 2 pairs" in msg
    assert "USDJPY" in msg


def test_second_mismatch_latched_by_real_alert_helper(_isolate, monkeypatch):
    """End-to-end: use the REAL _try_send_subscription_alert (with the
    Telegram send stubbed) so the latch state is exercised."""
    sl = _isolate
    calls = []
    class _tg:
        send_telegram_message = staticmethod(
            lambda text, parse_mode="": calls.append(text)
        )
    monkeypatch.setitem(sys.modules, "telegram_alerts", _tg)
    sl._record_market_confirm("USDJPY", "CS.D.USDJPY.TODAY.IP",
                              "MARKET:CS.D.USDJPY.TODAY.IP",
                              granted_mode="MERGE", requested_mode="MERGE",
                              max_freq="unfiltered")
    sl._record_market_confirm("USDCHF", "CS.D.USDCHF.TODAY.IP",
                              "MARKET:CS.D.USDCHF.TODAY.IP",
                              granted_mode="MERGE", requested_mode="MERGE",
                              max_freq="unfiltered")
    assert len(calls) == 1, calls
    assert calls[0].startswith("[TESTHOST] ")


def test_mode_mismatch_alerts(_isolate, monkeypatch):
    sl = _isolate
    sent = []
    monkeypatch.setattr(sl, "_try_send_subscription_alert",
                        lambda m: sent.append(m))
    sl._record_market_confirm("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              "MARKET:CS.D.GBPUSD.TODAY.IP",
                              granted_mode="DISTINCT",
                              requested_mode="MERGE",
                              max_freq="unfiltered")
    assert len(sent) == 1
    assert "MODE MISMATCH" in sent[0]
    assert "requested=MERGE" in sent[0]
    assert "granted=DISTINCT" in sent[0]


def test_settled_undercount_alerts(_isolate, monkeypatch):
    sl = _isolate
    sent = []
    monkeypatch.setattr(sl, "_try_send_subscription_alert",
                        lambda m: sent.append(m))
    # Only one pair confirmed even though EPICS_JSON has two.
    sl._record_market_confirm("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              "MARKET:CS.D.GBPUSD.TODAY.IP",
                              granted_mode="MERGE", requested_mode="MERGE",
                              max_freq="unfiltered")
    # No alert yet (subset with correct-so-far membership).
    assert sent == []
    # Caller signals startup done → settled check fires.
    sl.check_subscription_mismatch_settled()
    assert len(sent) == 1
    assert "configured 2 pairs" in sent[0]
    assert "confirmed 1" in sent[0]


def test_alerter_raise_does_not_break_confirm(_isolate, monkeypatch):
    sl = _isolate
    def _boom(m):
        raise RuntimeError("simulated telegram outage")
    monkeypatch.setattr(sl, "_try_send_subscription_alert", _boom)
    # Should NOT raise even though the alerter is broken
    sl._record_market_confirm("USDJPY", "CS.D.USDJPY.TODAY.IP",
                              "MARKET:CS.D.USDJPY.TODAY.IP",
                              granted_mode="MERGE", requested_mode="MERGE",
                              max_freq="unfiltered")


def test_empty_epics_json_is_silent(_isolate, monkeypatch):
    sl = _isolate
    monkeypatch.setenv("EPICS_JSON", "")
    sent = []
    monkeypatch.setattr(sl, "_try_send_subscription_alert",
                        lambda m: sent.append(m))
    # Any confirm — no alert because expected set is empty.
    sl._record_market_confirm("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              "MARKET:CS.D.GBPUSD.TODAY.IP",
                              granted_mode="MERGE", requested_mode="MERGE",
                              max_freq="unfiltered")
    sl.check_subscription_mismatch_settled()
    assert sent == []
