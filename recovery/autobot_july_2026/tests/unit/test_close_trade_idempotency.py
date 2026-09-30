"""
Unit tests for trade_executor.close_trade per-position idempotency guard
(2026-06-12). Covers the two requirements:

  1. Concurrent double-invocation on the same pos_key — exactly ONE side
     reaches the callback chain (Telegram alert, _CLOSE_CALLBACKS); the
     other returns None.

  2. Body raises mid-close — the _closing_in_flight flag is cleared on
     the exception path so a subsequent close_trade call can enter.
"""
import threading
import time
import importlib

import pytest


@pytest.fixture
def fresh_executor():
    """Reload trade_executor so each test gets a clean module-level state."""
    import trade_executor
    importlib.reload(trade_executor)
    yield trade_executor
    # Clean up callbacks registered by this test.
    trade_executor._CLOSE_CALLBACKS.clear()


def _install_active_position(te, pos_key="CS.D.GBPUSD.TODAY.IP|TEST_MODE",
                              deal_id="DI_TEST_1", entry=13000.0):
    """Seed EPIC_STATE with a single active position so close_trade enters
    the body."""
    te.EPIC_STATE[pos_key] = dict(te._STATE_TEMPLATE)
    st = te.EPIC_STATE[pos_key]
    st["epic"] = pos_key.split("|", 1)[0]
    st["mode"] = pos_key.split("|", 1)[1]
    st["active"] = True
    st["deal_id"] = deal_id
    st["dealId"] = deal_id
    st["direction"] = "BUY"
    st["entry_price"] = entry
    st["exit_price"] = entry + 10.0  # use as both exit hint and pnl basis
    st["last_mid"] = entry + 10.0
    st["pip_size"] = 1.0
    return pos_key, st


def _patch_ig_paths(te, monkeypatch, *, slow_close_ms=200):
    """Stub out every IG REST + telegram + execution-latency side effect so
    close_trade runs end-to-end in-process. Telegram alert + close-callback
    counters live on the module so both threads share them."""
    te._test_alert_count = 0
    te._test_callback_count = 0
    te._test_close_called = 0

    def _fake_close_by_deal_id(deal_id):
        # Slight delay so concurrent invocations actually overlap.
        te._test_close_called += 1
        time.sleep(slow_close_ms / 1000.0)
        return {"dealReference": f"REF_{deal_id}"}

    def _fake_position_still_open(epic=None, deal_id=None):
        return False  # broker has already closed it

    def _fake_send_alert(*a, **kw):
        te._test_alert_count += 1

    def _counting_callback(pos_key, exit_p, pnl_pips, reason, deal_id=None):
        te._test_callback_count += 1

    monkeypatch.setattr(te, "close_by_deal_id", _fake_close_by_deal_id)
    monkeypatch.setattr(te, "_position_still_open", _fake_position_still_open)
    monkeypatch.setattr(te, "send_trade_close_alert", _fake_send_alert)
    monkeypatch.setattr(te, "CLOSE_VERIFY_RETRIES", 1)
    monkeypatch.setattr(te, "CLOSE_VERIFY_SLEEP_SECS", 0.0)
    monkeypatch.setattr(te, "CLOSE_CONFIRM_RETRIES", 0)
    # Drop the fill-confirmation fetch — it tries a real IG session otherwise.
    monkeypatch.setattr(te, "get_ig_session", lambda: (None, None, None))
    # Register one counting close callback.
    te._CLOSE_CALLBACKS.clear()
    te._CLOSE_CALLBACKS.append(_counting_callback)


# -------------------------------------------------------------------------
# 1. Concurrent double-invocation: exactly one alert / one callback fired.
# -------------------------------------------------------------------------
def test_concurrent_double_invocation_only_one_side_completes(fresh_executor, monkeypatch):
    te = fresh_executor
    pos_key, _st = _install_active_position(te)
    _patch_ig_paths(te, monkeypatch, slow_close_ms=200)

    results = {}

    def _runner(idx):
        results[idx] = te.close_trade(pos_key)

    t1 = threading.Thread(target=_runner, args=(0,))
    t2 = threading.Thread(target=_runner, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not t1.is_alive(), "thread 1 hung"
    assert not t2.is_alive(), "thread 2 hung"

    # Exactly one True and one None.
    truthy = sum(1 for v in results.values() if v is True)
    falsy = sum(1 for v in results.values() if v is None)
    assert truthy == 1, f"expected exactly 1 successful close, got truthy={truthy} falsy={falsy} results={results}"
    assert falsy == 1, f"expected exactly 1 None return, got truthy={truthy} falsy={falsy} results={results}"

    # Telegram and callback fired exactly once.
    assert te._test_alert_count == 1, f"expected exactly 1 close alert, got {te._test_alert_count}"
    assert te._test_callback_count == 1, f"expected exactly 1 _CLOSE_CALLBACKS fire, got {te._test_callback_count}"
    # The IG close REST call must also have happened only once.
    assert te._test_close_called == 1, f"expected exactly 1 close_by_deal_id call, got {te._test_close_called}"


# -------------------------------------------------------------------------
# 2. Body raises mid-close → flag cleared → subsequent call enters body.
# -------------------------------------------------------------------------
def test_body_exception_clears_flag_and_retry_enters(fresh_executor, monkeypatch):
    te = fresh_executor
    pos_key, st = _install_active_position(te)
    _patch_ig_paths(te, monkeypatch, slow_close_ms=0)

    # Force the first close_by_deal_id to raise a non-Exception that the
    # body's narrow `except Exception` won't catch — BaseException-derived
    # exceptions bubble to the outer BaseException handler.
    class _Boom(BaseException):
        pass

    raised_once = {"done": False}

    def _explode_then_succeed(deal_id):
        if not raised_once["done"]:
            raised_once["done"] = True
            raise _Boom("simulated mid-close crash")
        # Subsequent call returns a normal response.
        te._test_close_called += 1
        return {"dealReference": f"REF_{deal_id}"}

    monkeypatch.setattr(te, "close_by_deal_id", _explode_then_succeed)

    # First call must propagate the BaseException AND clear the flag.
    with pytest.raises(_Boom):
        te.close_trade(pos_key)

    # The in-flight flag must be cleared so a retry can enter.
    assert te.EPIC_STATE[pos_key].get("_closing_in_flight") in (False, None), (
        f"_closing_in_flight not cleared after BaseException: "
        f"{te.EPIC_STATE[pos_key].get('_closing_in_flight')!r}"
    )
    # Trade is still active — broker close never went through.
    assert te.EPIC_STATE[pos_key]["active"] is True

    # Second invocation enters the body and completes successfully.
    result = te.close_trade(pos_key)
    assert result is True, f"retry close failed: {result}"
    # The fake close_by_deal_id was invoked once on the retry (the first
    # raise didn't increment the counter).
    assert te._test_close_called == 1, f"expected 1 IG close on retry, got {te._test_close_called}"
    # And the callback chain fired exactly once on the retry.
    assert te._test_callback_count == 1, f"expected 1 callback fire, got {te._test_callback_count}"


# -------------------------------------------------------------------------
# 3. Early-return clears: broker-still-open after failed close_by_deal_id.
# -------------------------------------------------------------------------
def test_broker_still_open_early_return_clears_flag(fresh_executor, monkeypatch):
    te = fresh_executor
    pos_key, st = _install_active_position(te)
    _patch_ig_paths(te, monkeypatch, slow_close_ms=0)

    def _fail_close(deal_id):
        raise RuntimeError("simulated IG REST failure")

    def _broker_still_has_position(epic=None, deal_id=None):
        return True  # _position_still_open returns True after the failure

    monkeypatch.setattr(te, "close_by_deal_id", _fail_close)
    monkeypatch.setattr(te, "_position_still_open", _broker_still_has_position)

    result = te.close_trade(pos_key)
    assert result is None, f"expected None when broker still has position, got {result}"
    # Flag cleared so retry can enter.
    assert te.EPIC_STATE[pos_key].get("_closing_in_flight") in (False, None)
    # Position remains active.
    assert te.EPIC_STATE[pos_key]["active"] is True


# -------------------------------------------------------------------------
# 4. Early-return clears: close-verify loop says still open.
# -------------------------------------------------------------------------
def test_close_verify_still_open_early_return_clears_flag(fresh_executor, monkeypatch):
    te = fresh_executor
    pos_key, st = _install_active_position(te)
    _patch_ig_paths(te, monkeypatch, slow_close_ms=0)

    # close_by_deal_id succeeds, but _position_still_open keeps reporting True.
    def _still_open(epic=None, deal_id=None):
        return True

    monkeypatch.setattr(te, "_position_still_open", _still_open)

    result = te.close_trade(pos_key)
    assert result is None
    assert te.EPIC_STATE[pos_key].get("_closing_in_flight") in (False, None)
    assert te.EPIC_STATE[pos_key]["active"] is True


# -------------------------------------------------------------------------
# 5. Sanity: success path leaves no in-flight flag on the new state dict.
# -------------------------------------------------------------------------
def test_success_path_implicit_clear(fresh_executor, monkeypatch):
    te = fresh_executor
    pos_key, _st = _install_active_position(te)
    _patch_ig_paths(te, monkeypatch, slow_close_ms=0)

    result = te.close_trade(pos_key)
    assert result is True
    # _reset_trade_state replaced EPIC_STATE[pos_key] with a fresh template
    # which has no _closing_in_flight. Equivalent to falsy.
    assert te.EPIC_STATE[pos_key].get("_closing_in_flight") in (False, None)
    # Active should be False on the fresh template.
    assert te.EPIC_STATE[pos_key]["active"] is False
