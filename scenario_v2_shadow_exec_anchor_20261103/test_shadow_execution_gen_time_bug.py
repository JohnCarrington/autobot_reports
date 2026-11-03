"""Regression test for the Scenario V2 shadow-execution ``generated_at_utc``
anchoring bug (2026-11-03 investigation).

Deployed bug (reproduces as `test_bug_reproduces_waiting_for_entry`):
    scenario_recommendation.build_trade_recommendation sets the recommendation's
    top-level ``generated_at_utc`` to the CURRENT wall-clock time, not to the
    scenario revision's own ``generated_at_utc``. shadow_execution.process_proposal
    then uses that top-level value as the lookahead-safety anchor and filters
    candles with ``ts_close > gen_dt``. Because gen_dt is wall-clock-now, no
    completed candle is eligible and every READY proposal stays
    ``WAITING_FOR_ENTRY`` forever.

Proposed-fix smoke test (passes once the executor reads
``recommendation.scenario.generated_at_utc`` instead of top-level, or once
build_trade_recommendation stops overwriting the top-level with ``now``):
    `test_fix_scenario_anchor_opens_position`

Run (python 3.10+):
    AGENT=/mnt/volume_lon1_1778405456698/research/live_obs/agent \\
        python3 -m pytest -xvs test_shadow_execution_gen_time_bug.py
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import tempfile
import unittest

AGENT = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/agent"
)
sys.path.insert(0, str(AGENT))
import shadow_execution as se  # noqa: E402
from scenario_recommendation import READY  # noqa: E402

UTC = dt.timezone.utc


def _bars(start: dt.datetime, closes: list[float], span: float = 2.0) -> list[dict]:
    """Build consecutive M5 OHLC bars from a close series. High/low wrap close
    by ±span/2 so stop/target geometry is predictable."""
    out = []
    for i, c in enumerate(closes):
        ts_open = start + dt.timedelta(minutes=5 * i)
        o = c
        out.append(
            {
                "ts_open": ts_open,
                "ts_close": ts_open + dt.timedelta(minutes=5),
                "o": o,
                "h": c + span / 2,
                "l": c - span / 2,
                "c": c,
                "arrival_at_utc": None,
                "source": "test",
            }
        )
    return out


def _recommendation(
    *,
    scenario_id: str,
    revision_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    scenario_generated_at_utc: str,
    recommendation_generated_at_utc: str,
) -> dict:
    """Build a minimal recommendation dict shaped like the output of
    ``build_trade_recommendation``."""
    return {
        "recommendation": direction,
        "readiness": READY,
        "reason": "test",
        "scenario": {
            "scenario_id": scenario_id,
            "revision_idx": revision_idx,
            "state": "ACTIVE",
            "bar_ts_utc": None,
            "generated_at_utc": scenario_generated_at_utc,
        },
        "direction": direction,
        "entry": {"price": entry, "trigger": "", "provenance": "test"},
        "stop": {"price": stop, "provenance": "test"},
        "target": {"label": "T", "price": target, "provenance": "test"},
        "subsequent_reversal": {},
        "publication": {"decision": "VALID", "publishable": True, "flag_codes": [], "reason": ""},
        "market_data_status": "FRESH",
        # DEPLOYED BUG: this field is sweep-time "now", not the scenario's gen time.
        "generated_at_utc": recommendation_generated_at_utc,
    }


class ShadowExecutionAnchorBug(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)
        # Scenario was generated two hours ago, at 10:00 UTC on the fixture day.
        self.scen_gen_at = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        # The sweep is running "now" at 13:50 UTC — simulates the real
        # observed sweep time on 2026-11-03.
        self.sweep_now = dt.datetime(2026, 11, 3, 13, 50, tzinfo=UTC)
        # Candles span 10:05..13:30: price grinds down below entry, then
        # breaks above at 13:25.
        self.candles = _bars(
            start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
            closes=[
                # 10:05..13:20 — 41 bars never above entry 13425.
                *([13418.0] * 20),
                *([13415.0] * 21),
                # 13:30 — close breaks above 13425 trigger (ENTRY).
                13426.5,
                # 13:35 — c=13426 + span/2=1.0 => h=13427.0 ≥ target 13427.
                13426.0,
            ],
        )

    def tearDown(self):
        self.tmp.cleanup()

    # -------- 1. REGRESSION: deployed bug reproduces WAITING_FOR_ENTRY ---

    def test_bug_reproduces_waiting_for_entry(self):
        """Deployed shadow executor + sweep-anchored gen time =
        WAITING_FOR_ENTRY even though the market has crossed the trigger."""
        rec = _recommendation(
            scenario_id="SBUG1",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13427.0,
            scenario_generated_at_utc=self.scen_gen_at.isoformat(),
            recommendation_generated_at_utc=self.sweep_now.isoformat(),  # buggy anchor
        )
        res = se.process_proposal(
            recommendation=rec,
            shadow_dir=self.shadow_dir,
            candles=self.candles,
            now_utc=self.sweep_now,
        )
        self.assertEqual(res["action"], "PROPOSAL_CREATED")
        self.assertEqual(res["position"], "WAITING_FOR_ENTRY")
        self.assertIn("no post-proposal bar", res["reason"])
        # No open position journaled.
        self.assertFalse((self.shadow_dir / "shadow_positions.jsonl").exists())

    # -------- 2. FIX SMOKE: scenario-anchored gen time opens + closes ----

    def test_fix_scenario_anchor_opens_position(self):
        """Simulate the proposed fix: pass the scenario's own
        ``generated_at_utc`` as the executor anchor. The 13:30 bar must
        OPEN the position, 13:35 bar must CLOSE on TARGET_HIT."""
        rec = _recommendation(
            scenario_id="SFIX1",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13427.0,
            scenario_generated_at_utc=self.scen_gen_at.isoformat(),
            # Fix: point top-level gen at the scenario's gen, not sweep-now.
            recommendation_generated_at_utc=self.scen_gen_at.isoformat(),
        )
        res = se.process_proposal(
            recommendation=rec,
            shadow_dir=self.shadow_dir,
            candles=self.candles,
            now_utc=self.sweep_now,
        )
        self.assertEqual(res["action"], "PROPOSAL_CREATED")
        self.assertEqual(res["position"], "CLOSED")
        self.assertEqual(res["exit_reason"], "TARGET_HIT")
        self.assertGreater(res["gross_pips"], 0.0)
        self.assertTrue((self.shadow_dir / "shadow_positions.jsonl").exists())
        self.assertTrue((self.shadow_dir / "shadow_closed.jsonl").exists())

    # -------- 3. REVISION CHURN: new revision must NOT reopen a scenario -

    def test_revision_churn_dedup_prevents_reentry(self):
        """Once a scenario opens under revision 0, a later revision with
        a different entry MUST NOT open a second position for the same
        scenario_id."""
        rec0 = _recommendation(
            scenario_id="SDUP",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13427.0,
            scenario_generated_at_utc=self.scen_gen_at.isoformat(),
            recommendation_generated_at_utc=self.scen_gen_at.isoformat(),
        )
        rec1 = _recommendation(
            scenario_id="SDUP",
            revision_idx=1,
            direction="BUY",
            entry=13420.0,  # revised entry
            stop=13410.0,
            target=13427.0,
            scenario_generated_at_utc=(self.scen_gen_at + dt.timedelta(minutes=10)).isoformat(),
            recommendation_generated_at_utc=(self.scen_gen_at + dt.timedelta(minutes=10)).isoformat(),
        )
        se.process_proposal(
            recommendation=rec0,
            shadow_dir=self.shadow_dir,
            candles=self.candles,
            now_utc=self.sweep_now,
        )
        res = se.process_proposal(
            recommendation=rec1,
            shadow_dir=self.shadow_dir,
            candles=self.candles,
            now_utc=self.sweep_now,
        )
        # Either ALREADY_CLOSED (if rec0 ran to target) or ALREADY_OPEN.
        self.assertIn(res.get("position"), ("ALREADY_OPEN", "ALREADY_CLOSED"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
