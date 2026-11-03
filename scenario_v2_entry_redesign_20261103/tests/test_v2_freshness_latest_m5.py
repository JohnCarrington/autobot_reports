"""Regression suite for the 2026-11-03 Mechanism A freshness correction.

Each test maps 1:1 to one of the ten brief-mandated validation cases:

  C1  Fresh qualifying impulse → eligible for execution.
  C2  Previous-candle impulse → rejected.
  C3  Thirty-minute-old impulse → rejected.
  C4  Impulse preceding scenario publication → rejected.
  C5  Missing latest candle → no trade.
  C6  Delayed scheduler execution → no stale entry.
  C7  Duplicate sweep → no second order.
  C8  NMS restriction → no broker call.
  C9  Valid IG DEMO order → correct entry/stop/target.
  C10 Existing open position → no duplicate order.

READ-ONLY. Tempdir only. No broker call. All against the installed
production copies at /mnt/.../live_obs/agent/.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import pathlib
import sys
import unittest
from importlib.machinery import SourceFileLoader

# Module search path:
#   - BRANCH impl dir first (so the patched v2_early_setup.py is loaded)
#   - INSTALLED agent dir second (so v2_demo_executor.py resolves)
# This exercises the patched derivation against the deployed executor
# without touching production until FX5.
HERE = pathlib.Path(__file__).resolve().parent
BRANCH_IMPL = (HERE.parent / "impl").resolve()
INSTALLED_AGENT = pathlib.Path(
    os.environ.get("SV2_AGENT_DIR",
                     "/mnt/volume_lon1_1778405456698/research/live_obs/agent"))
sys.path.insert(0, str(INSTALLED_AGENT))
sys.path.insert(0, str(BRANCH_IMPL))

os.environ.setdefault("V2_SV2_DEMO_SKIP_IMPORT_GUARD", "1")
os.environ.setdefault("IG_ACC_TYPE", "DEMO")

import v2_early_setup as es  # noqa: E402

# Sanity: confirm we loaded the branch copy (the one with the latest-M5
# correction) and that v2_demo_executor is importable from the installed
# location.
assert str(BRANCH_IMPL) in es.__file__, \
    f"loaded v2_early_setup from {es.__file__}, expected branch impl"

UTC = dt.timezone.utc


def _bar(ts_open, close, span=2.0):
    return {"ts_open": ts_open,
            "ts_close": ts_open + dt.timedelta(minutes=5),
            "o": close, "h": close + span / 2, "l": close - span / 2, "c": close,
            "arrival_at_utc": None, "source": "test"}


def _flat_bars(start, n, close=13410.0, span=1.0):
    return [_bar(start + dt.timedelta(minutes=5 * i), close, span) for i in range(n)]


def _impulse(ts_open, direction, decision_price):
    """One wide bar meeting MOMENTUM_MIN_RANGE_MULT (1.5× median) +
    MOMENTUM_MIN_BODY_FRAC (0.60) against a flat-10-bar context with
    span=1.0 (median range 1.0, so impulse range must be ≥ 1.5)."""
    if direction == "BUY":
        return {"ts_open": ts_open,
                "ts_close": ts_open + dt.timedelta(minutes=5),
                "o": decision_price - 1.0,
                "h": decision_price + 9.0,
                "l": decision_price - 1.5,
                "c": decision_price + 8.0,
                "arrival_at_utc": None, "source": "test"}
    return {"ts_open": ts_open,
            "ts_close": ts_open + dt.timedelta(minutes=5),
            "o": decision_price + 1.0,
            "h": decision_price + 1.5,
            "l": decision_price - 9.0,
            "c": decision_price - 8.0,
            "arrival_at_utc": None, "source": "test"}


def _dull(ts_open, close=13410.0):
    """One bar well under MOMENTUM_MIN_RANGE_MULT (span 0.5 vs median 1.0)."""
    return _bar(ts_open, close, span=0.5)


def _scen(sid, direction, entry, stop, target, gen_dt):
    return {
        "scenario_id": sid, "revision_idx": 0,
        "generated_at_utc": gen_dt.isoformat(),
        "state": "ACTIVE",
        "opportunities": [{"direction": direction,
                            "trade_proposal": {"direction": direction,
                                                 "entry_price": entry,
                                                 "stop_price": stop,
                                                 "target_price": target}}],
        "trade_proposal": {"direction": direction, "entry_price": entry,
                             "stop_price": stop, "target_price": target},
        "publication_decision": {"decision": "VALID"},
    }


# =====================================================================
# C1 Fresh qualifying impulse → eligible for execution
# =====================================================================

class C1_FreshQualifyingImpulse(unittest.TestCase):
    def test_fires(self):
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        boundary = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)   # just-closed bar
        now = boundary + dt.timedelta(seconds=20)
        pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
        impulse = _impulse(boundary - dt.timedelta(minutes=5), "BUY", 13410.0)
        self.assertEqual(impulse["ts_close"], boundary)
        res = es.derive(
            _scen("C1", "BUY", 13425.0, 13405.0, 13440.0, gen),
            pre + [impulse], mode="A", now_utc=now, lookback_seconds=0)
        self.assertEqual(res.status, "fill")
        self.assertEqual(res.entry_bar_ts,
                           (boundary - dt.timedelta(minutes=5)).isoformat())
        # Audit field confirms it fired on the just-closed boundary
        self.assertEqual(res.extras.get("latest_m5_close"), boundary.isoformat())


# =====================================================================
# C2 Previous-candle impulse → rejected
# =====================================================================

class C2_PreviousCandleImpulseRejected(unittest.TestCase):
    def test_prior_m5_impulse_not_filled(self):
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        # Impulse on the bar closing at 10:05
        boundary_impulse = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)
        # Latest completed bar at now is the NEXT one (closes at 10:10)
        boundary_latest = dt.datetime(2026, 11, 3, 10, 10, tzinfo=UTC)
        now = boundary_latest + dt.timedelta(seconds=20)
        pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
        impulse = _impulse(boundary_impulse - dt.timedelta(minutes=5),
                             "BUY", 13410.0)
        # Dull bar at the latest boundary (10:05 → 10:10)
        dull = _dull(boundary_latest - dt.timedelta(minutes=5),
                      close=impulse["c"])  # continuation but with tiny range
        res = es.derive(
            _scen("C2", "BUY", 13425.0, 13405.0, 13440.0, gen),
            pre + [impulse, dull], mode="A", now_utc=now, lookback_seconds=0)
        self.assertEqual(res.status, "wait")
        self.assertEqual(res.reason,
                           "latest_bar_did_not_meet_momentum_criteria")


# =====================================================================
# C3 Thirty-minute-old impulse → rejected
# =====================================================================

class C3_ThirtyMinuteOldImpulseRejected(unittest.TestCase):
    def test_impulse_in_prior_m5_rejected(self):
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        # Impulse 30 min before latest boundary
        boundary_impulse = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)
        boundary_latest = dt.datetime(2026, 11, 3, 10, 35, tzinfo=UTC)
        now = boundary_latest + dt.timedelta(seconds=20)
        pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
        impulse = _impulse(boundary_impulse - dt.timedelta(minutes=5),
                             "BUY", 13410.0)
        # Fill in dull bars between the impulse and the latest boundary
        fillers = []
        t = boundary_impulse
        while t < boundary_latest:
            fillers.append(_dull(t, close=impulse["c"]))
            t += dt.timedelta(minutes=5)
        # The latest bar at 10:30→10:35 is a dull bar — not an impulse
        res = es.derive(
            _scen("C3", "BUY", 13425.0, 13405.0, 13440.0, gen),
            pre + [impulse] + fillers, mode="A", now_utc=now, lookback_seconds=0)
        self.assertEqual(res.status, "wait")
        # Specifically because the LATEST bar did not meet the criteria
        self.assertEqual(res.reason,
                           "latest_bar_did_not_meet_momentum_criteria")


# =====================================================================
# C4 Impulse preceding scenario publication → rejected
# =====================================================================

class C4_PreGenImpulseRejected(unittest.TestCase):
    def test_latest_bar_closed_before_scen_gen(self):
        # Scenario published at 10:10. Latest bar at now=10:05:20 closes
        # at 10:05 (before gen) → reject.
        gen = dt.datetime(2026, 11, 3, 10, 10, tzinfo=UTC)
        boundary = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)
        now = boundary + dt.timedelta(seconds=20)
        pre = _flat_bars(gen - dt.timedelta(minutes=60), 10)
        # An impulse that pre-dates the scenario
        impulse = _impulse(boundary - dt.timedelta(minutes=5), "BUY", 13410.0)
        res = es.derive(
            _scen("C4", "BUY", 13425.0, 13405.0, 13440.0, gen),
            pre + [impulse], mode="A", now_utc=now, lookback_seconds=0)
        self.assertEqual(res.status, "wait")
        self.assertEqual(res.reason,
                           "latest_bar_closed_before_scenario_actionable")


# =====================================================================
# C5 Missing latest candle → no trade
# =====================================================================

class C5_MissingLatestCandle(unittest.TestCase):
    def test_observer_lag_blocks_fill(self):
        # The expected latest boundary is 10:10, but the candle stream
        # has only up to 10:05. Observer lag → wait.
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        boundary = dt.datetime(2026, 11, 3, 10, 10, tzinfo=UTC)
        now = boundary + dt.timedelta(seconds=20)
        pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
        # Impulse at 10:00→10:05, but no 10:05→10:10 bar in the stream
        impulse = _impulse(gen, "BUY", 13410.0)
        self.assertEqual(impulse["ts_close"],
                           dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC))
        res = es.derive(
            _scen("C5", "BUY", 13425.0, 13405.0, 13440.0, gen),
            pre + [impulse], mode="A", now_utc=now, lookback_seconds=0)
        self.assertEqual(res.status, "wait")
        self.assertEqual(res.reason, "latest_completed_m5_not_available")


# =====================================================================
# C6 Delayed scheduler execution → no stale entry
# =====================================================================

class C6_DelayedSchedulerExecution(unittest.TestCase):
    def test_delayed_sweep_with_stale_data_blocks_fill(self):
        """V2 sweep delayed by 20 min + observer ALSO behind one tick.
        Stream's latest bar is NOT the expected just-closed bar → wait."""
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        # Sweep expected at 10:05 but ran 20 min late at 10:25:30
        now = dt.datetime(2026, 11, 3, 10, 25, 30, tzinfo=UTC)
        # Expected boundary at now = 10:25. Stream has bars only up to 10:20.
        pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
        trailing = _flat_bars(gen, 4)   # bars closing at 10:05, :10, :15, :20
        self.assertEqual(trailing[-1]["ts_close"],
                           dt.datetime(2026, 11, 3, 10, 20, tzinfo=UTC))
        res = es.derive(
            _scen("C6", "BUY", 13425.0, 13405.0, 13440.0, gen),
            pre + trailing, mode="A", now_utc=now, lookback_seconds=0)
        self.assertEqual(res.status, "wait")
        self.assertEqual(res.reason, "latest_completed_m5_not_available")

    def test_delayed_sweep_with_fresh_data_fires_on_latest(self):
        """V2 sweep delayed by 20 min BUT observer is caught up.
        Stream HAS the 10:25 bar. If it is a valid impulse → fire.
        This is correct behaviour: fresh impulse detected on the
        just-closed bar is NOT stale."""
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        now = dt.datetime(2026, 11, 3, 10, 25, 30, tzinfo=UTC)
        boundary = dt.datetime(2026, 11, 3, 10, 25, tzinfo=UTC)
        pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
        trailing = _flat_bars(gen, 4)   # :05 :10 :15 :20 (dull)
        # Fresh impulse at 10:20→10:25 (closed at 10:25)
        impulse = _impulse(boundary - dt.timedelta(minutes=5), "BUY", 13410.0)
        res = es.derive(
            _scen("C6b", "BUY", 13425.0, 13405.0, 13440.0, gen),
            pre + trailing + [impulse], mode="A", now_utc=now,
            lookback_seconds=0)
        self.assertEqual(res.status, "fill")
        self.assertEqual(res.extras["latest_m5_close"], boundary.isoformat())


# =====================================================================
# C7 Duplicate sweep → no second order
# =====================================================================

class C7_DuplicateSweepNoSecondOrder(unittest.TestCase):
    def test_second_sweep_same_bar_dedup_blocks_broker(self):
        os.environ["V2_SV2_DEMO_SKIP_IMPORT_GUARD"] = "1"
        os.environ["V2_SV2_DEMO_ENABLED"] = "1"
        try:
            import importlib
            if "v2_demo_executor" in sys.modules:
                del sys.modules["v2_demo_executor"]
            ex = importlib.import_module("v2_demo_executor")
            gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
            boundary = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)
            now1 = boundary + dt.timedelta(seconds=20)
            # Second sweep 5 min later. Latest boundary at now2 is 10:10;
            # stream must have a 10:10 bar for a fill to be considered.
            now2 = dt.datetime(2026, 11, 3, 10, 10, 20, tzinfo=UTC)
            pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
            impulse = _impulse(boundary - dt.timedelta(minutes=5), "BUY", 13410.0)
            # Dull bar at 10:05→10:10 to allow the second-sweep latest-M5
            # check to succeed; the latest will not be an impulse so the
            # second sweep returns wait (no new broker call attempted).
            dull_follow = _dull(boundary, close=impulse["c"])
            scen = _scen("C7", "BUY", 13425.0, 13405.0, 13440.0, gen)
            calls = []
            open_positions = set()
            def _mock(decision, epic, **kw):
                pos_key = f"{epic}|{decision.strategy}"
                if pos_key in open_positions:
                    return None
                open_positions.add(pos_key)
                calls.append(pos_key)
                return {"dealReference": f"H0-{decision.strategy[:5]}-1"}

            # Sweep 1 fires on the 10:05 impulse
            r1 = ex.evaluate_scenario(
                scenario_row=scen, candles=pre + [impulse],
                now_utc=now1, _dispatcher=_mock,
                _nms=lambda **k: self._nms_ok(),
                _rules=lambda e, p: (False, None))
            self.assertEqual(r1["status"], "DISPATCHED")
            # Sweep 2 — latest is a dull bar; no new impulse detected
            r2 = ex.evaluate_scenario(
                scenario_row=scen, candles=pre + [impulse, dull_follow],
                now_utc=now2, _dispatcher=_mock,
                _nms=lambda **k: self._nms_ok(),
                _rules=lambda e, p: (False, None))
            self.assertEqual(r2["status"], "WAIT")
            self.assertEqual(len(calls), 1,
                               f"expected 1 dispatch, got {len(calls)}")
        finally:
            del os.environ["V2_SV2_DEMO_ENABLED"]

    def _nms_ok(self):
        class D: pass
        d = D(); d.applicable = True; d.allowed = True; d.reason_code = "OK"
        return d


# =====================================================================
# C8 NMS restriction → no broker call
# =====================================================================

class C8_NMSBlocksBroker(unittest.TestCase):
    def test_nms_block_prevents_dispatcher(self):
        os.environ["V2_SV2_DEMO_SKIP_IMPORT_GUARD"] = "1"
        os.environ["V2_SV2_DEMO_ENABLED"] = "1"
        try:
            import importlib
            if "v2_demo_executor" in sys.modules:
                del sys.modules["v2_demo_executor"]
            ex = importlib.import_module("v2_demo_executor")
            gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
            boundary = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)
            now = boundary + dt.timedelta(seconds=20)
            pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
            impulse = _impulse(boundary - dt.timedelta(minutes=5), "BUY", 13410.0)
            def _nms_blocks(**kw):
                class D: pass
                d = D(); d.applicable = True; d.allowed = False
                d.reason_code = "BLOCK_TREND_WRONG_DIRECTION"
                return d
            called = []
            def _dispatcher(dec, epic, **kw):
                called.append(1)
                return {}
            scen = _scen("C8", "BUY", 13425.0, 13405.0, 13440.0, gen)
            r = ex.evaluate_scenario(
                scenario_row=scen, candles=pre + [impulse], now_utc=now,
                _dispatcher=_dispatcher, _nms=_nms_blocks,
                _rules=lambda e, p: (False, None))
            self.assertEqual(len(called), 0)
            self.assertEqual(r["status"], "SKIPPED")
            self.assertIn("NMS_BLOCKED", r["reason"])
        finally:
            del os.environ["V2_SV2_DEMO_ENABLED"]


# =====================================================================
# C9 Valid IG DEMO order → correct entry/stop/target
# =====================================================================

class C9_ValidIGDemoOrder(unittest.TestCase):
    def test_decision_object_has_mechanical_stop_and_v2_target(self):
        os.environ["V2_SV2_DEMO_SKIP_IMPORT_GUARD"] = "1"
        os.environ["V2_SV2_DEMO_ENABLED"] = "1"
        try:
            import importlib
            if "v2_demo_executor" in sys.modules:
                del sys.modules["v2_demo_executor"]
            ex = importlib.import_module("v2_demo_executor")
            gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
            boundary = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)
            now = boundary + dt.timedelta(seconds=20)
            pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
            impulse = _impulse(boundary - dt.timedelta(minutes=5), "BUY", 13410.0)
            scen = _scen("C9", "BUY", 13425.0, 13405.0, 13440.0, gen)
            calls = []
            def _dispatcher(dec, epic, **kw):
                calls.append(dec)
                return {"dealReference": "H0-SV2_L-1"}
            r = ex.evaluate_scenario(
                scenario_row=scen, candles=pre + [impulse], now_utc=now,
                _dispatcher=_dispatcher,
                _nms=lambda **k: self._nms_ok(),
                _rules=lambda e, p: (False, None))
            self.assertEqual(r["status"], "DISPATCHED")
            self.assertEqual(len(calls), 1)
            dec = calls[0]
            # Entry = impulse bar's close
            self.assertEqual(dec.entry, impulse["c"])
            # Stop = impulse low - 1 pip buffer (mechanical, NOT V2's 13405)
            self.assertEqual(dec.stop, impulse["l"] - 1.0)
            # Target = V2's structural target, preserved
            self.assertEqual(dec.target, 13440.0)
            # Direction preserved
            self.assertEqual(dec.direction, "BUY")
            self.assertEqual(dec.strategy, "SCENARIO_V2_L")
            # BUY geometry
            self.assertLess(dec.stop, dec.entry)
            self.assertLess(dec.entry, dec.target)
        finally:
            del os.environ["V2_SV2_DEMO_ENABLED"]

    def _nms_ok(self):
        class D: pass
        d = D(); d.applicable = True; d.allowed = True; d.reason_code = "OK"
        return d


# =====================================================================
# C10 Existing open position → no duplicate order
# =====================================================================

class C10_ExistingOpenPositionDedup(unittest.TestCase):
    def test_dispatcher_dedup_models_epic_state(self):
        """Simulates trade_executor.EPIC_STATE central dedup: if a V2
        position is already open for the same epic|mode, the dispatcher
        returns None and no second broker call fires."""
        os.environ["V2_SV2_DEMO_SKIP_IMPORT_GUARD"] = "1"
        os.environ["V2_SV2_DEMO_ENABLED"] = "1"
        try:
            import importlib
            if "v2_demo_executor" in sys.modules:
                del sys.modules["v2_demo_executor"]
            ex = importlib.import_module("v2_demo_executor")
            gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
            boundary = dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC)
            now = boundary + dt.timedelta(seconds=20)
            pre = _flat_bars(gen - dt.timedelta(minutes=50), 10)
            impulse = _impulse(boundary - dt.timedelta(minutes=5), "BUY", 13410.0)
            scen = _scen("C10", "BUY", 13425.0, 13405.0, 13440.0, gen)
            dispatch_calls = []
            open_already = {("CS.D.GBPUSD.TODAY.IP", "SCENARIO_V2_L")}
            def _mock(decision, epic, **kw):
                key = (epic, decision.strategy)
                if key in open_already:
                    # trade_executor's dedup returns None on duplicate
                    dispatch_calls.append(("DEDUP", key))
                    return None
                open_already.add(key)
                dispatch_calls.append(("OPEN", key))
                return {"dealReference": "H0-SV2_L-1"}
            r = ex.evaluate_scenario(
                scenario_row=scen, candles=pre + [impulse], now_utc=now,
                _dispatcher=_mock,
                _nms=lambda **k: self._nms_ok(),
                _rules=lambda e, p: (False, None))
            self.assertEqual(len(dispatch_calls), 1)
            self.assertEqual(dispatch_calls[0][0], "DEDUP")
            # V2's own return is DISPATCHED (we did call the dispatcher)
            # but broker_result.result is None — audit shows no new fill.
            self.assertEqual(r["status"], "DISPATCHED")
            self.assertIsNone(r["broker_result"]["result"])
        finally:
            del os.environ["V2_SV2_DEMO_ENABLED"]

    def _nms_ok(self):
        class D: pass
        d = D(); d.applicable = True; d.allowed = True; d.reason_code = "OK"
        return d


if __name__ == "__main__":
    unittest.main(verbosity=2)
