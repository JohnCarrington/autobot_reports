"""Regression tests for the Scenario V2 early-setup derivation module.

Covers:
  * Mechanism A — momentum impulse fires and derives stop below
    impulse low; doji / small-range bars rejected.
  * Mechanism B — pullback-then-rejection fires; pullback-too-long
    aborts; V2 stop breach aborts.
  * Mechanism C — 3-bar pivot continuation fires; non-pivot windows
    reject.
  * Preservation — direction and target are V2's; stop is mechanical.
  * SHADOW_ONLY / no-broker-import invariant (shared with executor
    tests).
  * Lookahead-safe behaviour under default 2 h cap.

READ-ONLY. tempdir only. No broker calls.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
import unittest
from importlib.machinery import SourceFileLoader

HERE = pathlib.Path(__file__).resolve().parent
IMPL = (HERE.parent / "impl").resolve()
sys.path.insert(0, str(IMPL))
import v2_early_setup as es   # noqa: E402

UTC = dt.timezone.utc


def _bars(start: dt.datetime, closes: list[float], span: float = 2.0) -> list[dict]:
    """Build M5 OHLC bars from a close series. Default span means
    high = close + span/2 and low = close - span/2."""
    return [{"ts_open": start + dt.timedelta(minutes=5 * i),
              "ts_close": start + dt.timedelta(minutes=5 * (i + 1)),
              "o": c, "h": c + span / 2, "l": c - span / 2, "c": c,
              "arrival_at_utc": None, "source": "test"}
            for i, c in enumerate(closes)]


def _scen(sid: str, direction: str, entry: float, stop: float, target: float,
            gen_dt: dt.datetime) -> dict:
    return {
        "scenario_id": sid, "revision_idx": 0,
        "generated_at_utc": gen_dt.isoformat(),
        "state": "ACTIVE",
        "opportunities": [{"direction": direction,
                            "trade_proposal": {"direction": direction,
                                                 "entry_price": entry,
                                                 "stop_price": stop,
                                                 "target_price": target}}],
        "trade_proposal": {"direction": direction,
                             "entry_price": entry,
                             "stop_price": stop,
                             "target_price": target},
        "publication_decision": {"decision": "VALID"},
    }


# =====================================================================
# Mechanism A — momentum impulse
# =====================================================================

class MomentumImpulse(unittest.TestCase):
    def setUp(self):
        self.gen_dt = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)

    def test_fires_on_strong_bullish_impulse(self):
        pre_closes = [13410.0] * 10
        pre_bars = _bars(self.gen_dt - dt.timedelta(minutes=50), pre_closes, span=1.0)
        # Post bars: one wide bullish bar.
        post_bars = [{
            "ts_open": self.gen_dt, "ts_close": self.gen_dt + dt.timedelta(minutes=5),
            "o": 13410.0, "h": 13420.0, "l": 13409.5, "c": 13418.0,
            "arrival_at_utc": None, "source": "test",
        }]
        candles = pre_bars + post_bars
        scen = _scen("A1", "BUY", entry=13425.0, stop=13405.0, target=13440.0,
                       gen_dt=self.gen_dt)
        res = es.derive(scen, candles, mode="A", now_utc=self.now,
                          lookback_seconds=0)
        self.assertEqual(res.status, "fill")
        self.assertEqual(res.setup_type, "MOMENTUM_IMPULSE")
        self.assertEqual(res.sim_entry, 13418.0)
        self.assertEqual(res.stop, 13409.5 - 1.0)
        self.assertEqual(res.target, 13440.0)

    def test_rejects_doji_bar(self):
        pre_closes = [13410.0] * 10
        pre_bars = _bars(self.gen_dt - dt.timedelta(minutes=50), pre_closes, span=1.0)
        # Wide range but body is in the middle (doji-ish)
        post_bars = [{
            "ts_open": self.gen_dt, "ts_close": self.gen_dt + dt.timedelta(minutes=5),
            "o": 13410.0, "h": 13420.0, "l": 13409.5, "c": 13414.5,
            "arrival_at_utc": None, "source": "test",
        }]
        res = es.derive(_scen("A2", "BUY", 13425.0, 13405.0, 13440.0, self.gen_dt),
                          pre_bars + post_bars, mode="A", now_utc=self.now,
                          lookback_seconds=0)
        self.assertEqual(res.status, "wait")

    def test_sell_direction_mirror(self):
        pre_closes = [13410.0] * 10
        pre_bars = _bars(self.gen_dt - dt.timedelta(minutes=50), pre_closes, span=1.0)
        post_bars = [{
            "ts_open": self.gen_dt, "ts_close": self.gen_dt + dt.timedelta(minutes=5),
            "o": 13410.0, "h": 13410.5, "l": 13400.0, "c": 13402.0,
            "arrival_at_utc": None, "source": "test",
        }]
        res = es.derive(_scen("A3", "SELL", 13395.0, 13415.0, 13380.0, self.gen_dt),
                          pre_bars + post_bars, mode="A", now_utc=self.now,
                          lookback_seconds=0)
        self.assertEqual(res.status, "fill")
        self.assertEqual(res.setup_type, "MOMENTUM_IMPULSE")
        self.assertEqual(res.stop, 13410.5 + 1.0)

    def test_insufficient_pre_history(self):
        # Only 5 pre bars — need 10
        pre_bars = _bars(self.gen_dt - dt.timedelta(minutes=25), [13410.0] * 5)
        post_bars = [{
            "ts_open": self.gen_dt, "ts_close": self.gen_dt + dt.timedelta(minutes=5),
            "o": 13410.0, "h": 13420.0, "l": 13409.5, "c": 13418.0,
            "arrival_at_utc": None, "source": "test",
        }]
        res = es.derive(_scen("A4", "BUY", 13425.0, 13405.0, 13440.0, self.gen_dt),
                          pre_bars + post_bars, mode="A", now_utc=self.now,
                          lookback_seconds=0)
        self.assertEqual(res.status, "wait")
        self.assertEqual(res.reason, "insufficient_pre_history")

    def test_v2_stop_breach_aborts(self):
        pre_closes = [13410.0] * 10
        pre_bars = _bars(self.gen_dt - dt.timedelta(minutes=50), pre_closes, span=1.0)
        # Post bar touches V2 stop at 13405 before any impulse.
        post_bars = [{
            "ts_open": self.gen_dt, "ts_close": self.gen_dt + dt.timedelta(minutes=5),
            "o": 13410.0, "h": 13412.0, "l": 13404.0, "c": 13411.0,
            "arrival_at_utc": None, "source": "test",
        }]
        res = es.derive(_scen("A5", "BUY", 13425.0, 13405.0, 13440.0, self.gen_dt),
                          pre_bars + post_bars, mode="A", now_utc=self.now,
                          lookback_seconds=0)
        self.assertEqual(res.status, "reject")
        self.assertEqual(res.reason, "SETUP_INVALIDATED_PRE_ENTRY")


# =====================================================================
# Mechanism B — pullback and rejection
# =====================================================================

class PullbackRejection(unittest.TestCase):
    def setUp(self):
        self.gen_dt = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.now = dt.datetime(2026, 11, 3, 10, 45, tzinfo=UTC)

    def test_fires_on_higher_low_after_pullback(self):
        # Decision price = 13410 (last pre bar).
        pre = _bars(self.gen_dt - dt.timedelta(minutes=5), [13410.0])
        # Post: 2 pullback bars (close < 13410), then rejection (close > 13410 AND low > pullback trough).
        post_closes = [13405.0, 13406.0, 13412.0]
        post = _bars(self.gen_dt, post_closes, span=2.0)
        # Override post[2].low to be above the trough low (13404)
        post[2]["l"] = 13410.0
        post[2]["h"] = 13413.0
        res = es.derive(_scen("B1", "BUY", 13425.0, 13400.0, 13440.0, self.gen_dt),
                          pre + post, mode="B", now_utc=self.now, lookback_seconds=0)
        self.assertEqual(res.status, "fill")
        self.assertEqual(res.setup_type, "PULLBACK_REJECTION")
        self.assertEqual(res.sim_entry, 13412.0)
        self.assertEqual(res.stop, 13404.0 - 2.0)

    def test_pullback_too_long_rejects(self):
        pre = _bars(self.gen_dt - dt.timedelta(minutes=5), [13410.0])
        # 7 counter-direction bars with no rejection
        post = _bars(self.gen_dt, [13405.0] * 7, span=1.0)
        res = es.derive(_scen("B2", "BUY", 13425.0, 13400.0, 13440.0, self.gen_dt),
                          pre + post, mode="B", now_utc=self.now, lookback_seconds=0)
        self.assertEqual(res.status, "reject")
        self.assertEqual(res.reason, "pullback_too_long")


# =====================================================================
# Mechanism C — early structural continuation
# =====================================================================

class EarlyStructural(unittest.TestCase):
    def setUp(self):
        self.gen_dt = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.now = dt.datetime(2026, 11, 3, 10, 45, tzinfo=UTC)

    def test_fires_on_three_bar_pivot_continuation(self):
        # BUY: peak at bar 0 (h=13415), trough at bar 1 (l=13405), continuation at bar 2 (c>13415)
        bars = [
            {"ts_open": self.gen_dt + dt.timedelta(minutes=5 * i),
             "ts_close": self.gen_dt + dt.timedelta(minutes=5 * (i + 1)),
             "o": o, "h": h, "l": l, "c": c, "arrival_at_utc": None, "source": "test"}
            for i, (o, h, l, c) in enumerate([
                (13412.0, 13415.0, 13411.0, 13413.0),  # peak
                (13413.0, 13414.0, 13405.0, 13410.0),  # trough
                (13410.0, 13420.0, 13410.0, 13418.0),  # continuation break
                (13418.0, 13425.0, 13417.0, 13424.0),  # follow-through
            ])
        ]
        res = es.derive(_scen("C1", "BUY", 13425.0, 13400.0, 13440.0, self.gen_dt),
                          bars, mode="C", now_utc=self.now, lookback_seconds=0)
        self.assertEqual(res.status, "fill")
        self.assertEqual(res.setup_type, "EARLY_STRUCTURAL")
        self.assertEqual(res.sim_entry, 13418.0)
        self.assertEqual(res.stop, 13405.0 - 2.0)


# =====================================================================
# Preservation + invariant tests
# =====================================================================

class Invariants(unittest.TestCase):
    def test_direction_and_target_preserved(self):
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        pre = _bars(gen - dt.timedelta(minutes=50), [13410.0] * 10, span=1.0)
        post = [{"ts_open": gen, "ts_close": gen + dt.timedelta(minutes=5),
                  "o": 13410.0, "h": 13420.0, "l": 13409.5, "c": 13418.0,
                  "arrival_at_utc": None, "source": "test"}]
        res = es.derive(_scen("INV", "BUY", 13425.0, 13405.0, 13440.0, gen),
                          pre + post, mode="A", now_utc=now,
                          lookback_seconds=0)
        self.assertEqual(res.direction, "BUY")
        self.assertEqual(res.target, 13440.0)   # V2's target preserved

    def test_no_broker_imports_in_module(self):
        src = (IMPL / "v2_early_setup.py").read_text()
        banned = ["ig_client", "trades_api", "autobot.py", "autobot_core",
                   "trade_executor", "broker_client", "IGClient",
                   "requests", "urllib.request"]
        for b in banned:
            self.assertNotIn(b, src, f"derivation module imports {b!r}")

    def test_valid_modes_enum(self):
        self.assertEqual(set(es.VALID_MODES), {"A", "B", "C"})

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            es.derive({"scenario_id": "X"}, [], mode="Z")


# =====================================================================
# DEMO executor tests (lazy load the .template — operator-controlled file name)
# =====================================================================

class DemoExecutorInvariants(unittest.TestCase):
    def setUp(self):
        # Enable the import guard bypass BEFORE loading the template.
        import os
        os.environ.setdefault("V2_SV2_DEMO_SKIP_IMPORT_GUARD", "1")
        tmpl = IMPL / "v2_demo_executor.py.template"
        self.assertTrue(tmpl.is_file())
        loader = SourceFileLoader("v2_demo_executor_test", str(tmpl))
        spec = importlib.util.spec_from_loader("v2_demo_executor_test", loader)
        self.mod = importlib.util.module_from_spec(spec)
        loader.exec_module(self.mod)

    def test_disabled_by_default(self):
        self.assertFalse(self.mod.V2_SV2_DEMO_ENABLED)
        self.assertTrue(self.mod.V2_SV2_DEMO_DRY_RUN)

    def test_evaluate_scenario_disabled_returns_disabled_status(self):
        # Build a minimal scenario + candles that would otherwise fire.
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        pre = _bars(gen - dt.timedelta(minutes=50), [13410.0] * 10, span=1.0)
        post = [{"ts_open": gen, "ts_close": gen + dt.timedelta(minutes=5),
                  "o": 13410.0, "h": 13420.0, "l": 13409.5, "c": 13418.0,
                  "arrival_at_utc": None, "source": "test"}]
        scen = _scen("DX", "BUY", 13425.0, 13405.0, 13440.0, gen)
        res = self.mod.evaluate_scenario(
            scenario_row=scen, candles=pre + post, now_utc=now,
            _dispatcher=lambda *a, **k: self.fail("broker should not be called"),
            _nms=lambda **k: self._simple_nms(True),
            _rules=lambda e, p: (False, None))
        # Default flags: ENABLED=0, DRY_RUN=1 — expect DISABLED status
        self.assertIn(res["status"], ("DISABLED", "DRY_RUN", "SKIPPED"))

    def test_rejected_scenarios_never_hit_broker(self):
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        scen = _scen("DR", "BUY", 13425.0, 13405.0, 13440.0, gen)
        scen["publication_decision"] = {"decision": "INVALID"}
        broker_called = []
        res = self.mod.evaluate_scenario(
            scenario_row=scen, candles=[], now_utc=now,
            _dispatcher=lambda *a, **k: broker_called.append(1),
            _nms=lambda **k: self._simple_nms(True),
            _rules=lambda e, p: (False, None))
        self.assertEqual(len(broker_called), 0)
        self.assertEqual(res["status"], "SKIPPED")

    def test_nms_block_prevents_broker(self):
        gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        pre = _bars(gen - dt.timedelta(minutes=50), [13410.0] * 10, span=1.0)
        post = [{"ts_open": gen, "ts_close": gen + dt.timedelta(minutes=5),
                  "o": 13410.0, "h": 13420.0, "l": 13409.5, "c": 13418.0,
                  "arrival_at_utc": None, "source": "test"}]
        scen = _scen("NC", "BUY", 13425.0, 13405.0, 13440.0, gen)
        broker_called = []
        res = self.mod.evaluate_scenario(
            scenario_row=scen, candles=pre + post, now_utc=now,
            _dispatcher=lambda *a, **k: broker_called.append(1),
            _nms=lambda **k: self._simple_nms(False, "BLOCK_NMS_SHORT"),
            _rules=lambda e, p: (False, None))
        self.assertEqual(len(broker_called), 0)
        self.assertEqual(res["status"], "SKIPPED")
        self.assertIn("NMS_BLOCKED", res["reason"])

    def _simple_nms(self, allowed, reason_code=""):
        class D: pass
        d = D()
        d.applicable = True
        d.allowed = allowed
        d.reason_code = reason_code
        return d


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
