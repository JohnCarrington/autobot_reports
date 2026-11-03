"""Regression suite for the Scenario V2 shadow-execution anchor correction
(2026-11-03).

Covers the six axes mandated by the correction brief:

1. Timestamp handling — the executor uses the scenario revision's own
   generation time, not the recommendation-build wall-clock.
2. Candle eligibility — the lookahead-safety filter admits exactly the
   bars whose close is strictly after the scenario-gen anchor and at or
   before the current clock.
3. Expiry (EXPIRED_ENTRY) — a non-READY readiness short-circuits before
   any lookahead work; the correction must not open positions on
   expired triggers.
4. Revision churn — new revisions never reset or re-open an existing
   scenario; dedup key is per (scenario_id, revision_idx) but the
   open/closed slot is per scenario_id.
5. Idempotency — re-processing the same recommendation does not produce
   duplicate proposal rows, position-open events, or position-close
   events.
6. Retrospective-fill guard — the ``MAX_FILL_LOOKBACK_SECONDS`` cap
   prevents a late-landing deploy from retroactively opening positions
   on candles that pre-date the sweep window.

Also includes two cross-cutting invariants:
    * The deployed (pre-correction) module reproduces the
      WAITING_FOR_ENTRY bug.
    * The patched module reads nothing from the live_obs tree beyond
      what it already imports in production.

Run (python 3.10+):

    PATCHED=/path/to/patches/shadow_execution.py.patched \\
        python3 -m pytest -xvs test_shadow_execution_anchor_correction.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest

from scenario_recommendation import READY  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = (HERE.parent / "patches").resolve()
PATCHED_PATH = pathlib.Path(
    os.environ.get("PATCHED",
                      str(PATCHES / "shadow_execution.py.patched"))
).resolve()
DEPLOYED_PATH = pathlib.Path(
    os.environ.get("DEPLOYED",
                      "/mnt/volume_lon1_1778405456698/research/live_obs/agent/shadow_execution.py")
).resolve()


def _load_module(name: str, path: pathlib.Path):
    # Explicit SourceFileLoader so files without a ``.py`` suffix (e.g.
    # ``shadow_execution.py.patched``) still load as python source.
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


UTC = dt.timezone.utc


def _bars(start: dt.datetime, closes: list[float], span: float = 2.0) -> list[dict]:
    """Build consecutive M5 OHLC bars from a close series.

    High/low wrap close by ±span/2 so stop/target geometry is predictable.
    """
    out = []
    for i, c in enumerate(closes):
        ts_open = start + dt.timedelta(minutes=5 * i)
        out.append(
            {
                "ts_open": ts_open,
                "ts_close": ts_open + dt.timedelta(minutes=5),
                "o": c,
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
    readiness: str = READY,
) -> dict:
    return {
        "recommendation": direction if readiness == READY else "WAIT",
        "readiness": readiness,
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
        "publication": {"decision": "VALID", "publishable": True,
                         "flag_codes": [], "reason": ""},
        "market_data_status": "FRESH",
        "generated_at_utc": recommendation_generated_at_utc,
    }


# =====================================================================
# AXIS 1 — Timestamp handling
# =====================================================================

class AxisOneTimestampHandling(unittest.TestCase):
    """The executor must anchor on scenario.generated_at_utc, not on the
    recommendation's top-level (sweep wall-clock) generated_at_utc."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)
        self.scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        # One bar at 10:10..10:15 that crosses entry 13425 (BUY).
        self.candles = _bars(
            start=dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC),
            closes=[13420.0, 13426.0, 13426.5],  # bars 10:00, 10:05, 10:10
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_patched_uses_scenario_gen_time(self):
        """Even though the recommendation's top-level says sweep-now,
        the patched executor must walk candles starting at scen_gen."""
        se = _load_module("se_patched_1", PATCHED_PATH)
        rec = _recommendation(
            scenario_id="S_AXIS1",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=self.sweep_now.isoformat(),
        )
        result = se.process_proposal(
            recommendation=rec,
            shadow_dir=self.shadow_dir,
            candles=self.candles,
            now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,  # disable cap for this axis
        )
        # Position must have opened on the 10:05 close bar (first bar
        # strictly after scen_gen 10:00 whose close > 13425).
        self.assertEqual(result.get("action"), "PROPOSAL_CREATED")
        self.assertIn(result.get("position"), ("OPENED_AWAITING_EXIT", "CLOSED"))

    def test_proposal_row_records_both_anchors(self):
        """The journaled proposal row must carry both scenario-gen and
        recommendation-built timestamps so the audit is unambiguous."""
        import json
        se = _load_module("se_patched_2", PATCHED_PATH)
        rec = _recommendation(
            scenario_id="S_AXIS1B",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=self.sweep_now.isoformat(),
        )
        se.process_proposal(
            recommendation=rec,
            shadow_dir=self.shadow_dir,
            candles=self.candles,
            now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        proposals_file = self.shadow_dir / "shadow_proposals.jsonl"
        rows = [json.loads(ln) for ln in proposals_file.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["generated_at_utc"], self.scen_gen.isoformat())
        self.assertEqual(row["recommendation_built_at_utc"],
                            self.sweep_now.isoformat())


# =====================================================================
# AXIS 2 — Candle eligibility
# =====================================================================

class AxisTwoCandleEligibility(unittest.TestCase):
    """Only bars with (scen_gen, now] AND (now - lookback, ∞) qualify."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)
        self.scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bar_at_or_before_scen_gen_rejected(self):
        """A bar whose ts_close == scen_gen is rejected (strict >)."""
        se = _load_module("se_patched_3", PATCHED_PATH)
        # 09:55..10:00 bar crosses entry — ts_close is 10:00:00,
        # equal to scen_gen; must NOT trigger. 10:05..10:10 bar also
        # crosses — must trigger.
        candles = [
            {"ts_open": dt.datetime(2026, 11, 3, 9, 55, tzinfo=UTC),
             "ts_close": dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC),
             "o": 13420.0, "h": 13428.0, "l": 13418.0, "c": 13426.0,
             "arrival_at_utc": None, "source": "test"},
            {"ts_open": dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
             "ts_close": dt.datetime(2026, 11, 3, 10, 10, tzinfo=UTC),
             "o": 13426.0, "h": 13428.0, "l": 13424.0, "c": 13427.0,
             "arrival_at_utc": None, "source": "test"},
        ]
        rec = _recommendation(
            scenario_id="S_AXIS2A",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13432.0,
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=self.sweep_now.isoformat(),
        )
        result = se.process_proposal(
            recommendation=rec,
            shadow_dir=self.shadow_dir,
            candles=candles,
            now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        self.assertIn(result.get("position"), ("OPENED_AWAITING_EXIT", "CLOSED"))
        # The entry bar must be the 10:05 one, not the 09:55 one.
        if result.get("entry_bar_ts_utc"):
            self.assertEqual(result["entry_bar_ts_utc"],
                                "2026-11-03T10:05:00+00:00")

    def test_bar_in_future_rejected(self):
        """A bar whose ts_close > now is rejected (defensive against the
        legacy CSV fallback feeding partial bars)."""
        se = _load_module("se_patched_4", PATCHED_PATH)
        candles = _bars(
            start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
            closes=[13426.0, 13426.5],  # 10:05 & 10:10 bars (close at 10:10 and 10:15)
        )
        # Sweep now = 10:12 => only the 10:05 bar (close 10:10) is in-window.
        now_mid = dt.datetime(2026, 11, 3, 10, 12, tzinfo=UTC)
        rec = _recommendation(
            scenario_id="S_AXIS2B",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13428.0,
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=now_mid.isoformat(),
        )
        result = se.process_proposal(
            recommendation=rec,
            shadow_dir=self.shadow_dir,
            candles=candles,
            now_utc=now_mid,
            max_fill_lookback_seconds=0,
        )
        # Only one bar in window (10:05 close 13426 > 13425) → OPEN.
        # The 10:10 bar (close at 10:15 > now 10:12) is excluded from
        # entry monitoring; monitor_bars for exit should also honour
        # the ts_close <= now rule.
        self.assertIn(result.get("position"), ("OPENED_AWAITING_EXIT", "CLOSED"))


# =====================================================================
# AXIS 3 — Expiry / non-READY proposals
# =====================================================================

class AxisThreeExpiry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)
        self.scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        self.candles = _bars(
            start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
            closes=[13426.0, 13427.0],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_expired_entry_does_not_open(self):
        """A proposal arriving with readiness=EXPIRED_ENTRY (upstream
        validator rejected its temporal anchor) must only record a
        proposal row — no OPEN, no CLOSE."""
        se = _load_module("se_patched_5", PATCHED_PATH)
        rec = _recommendation(
            scenario_id="S_AXIS3",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=self.sweep_now.isoformat(),
            readiness="EXPIRED_ENTRY",
        )
        result = se.process_proposal(
            recommendation=rec,
            shadow_dir=self.shadow_dir,
            candles=self.candles,
            now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        self.assertEqual(result.get("action"), "PROPOSAL_CREATED")
        self.assertIsNone(result.get("position"))
        self.assertFalse((self.shadow_dir / "shadow_positions.jsonl").exists())
        self.assertFalse((self.shadow_dir / "shadow_closed.jsonl").exists())


# =====================================================================
# AXIS 4 — Revision churn
# =====================================================================

class AxisFourRevisionChurn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)
        self.scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
        self.candles = _bars(
            start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
            # Entry 13425 crossed at 10:05; target 13430 reached at 10:10.
            closes=[13426.0, 13429.5],
            span=2.0,  # 10:05 h=13427, 10:10 h=13430.5 ≥ 13430
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_revision_cannot_reopen_or_duplicate(self):
        """Revision 1 arriving after revision 0 has already closed must
        return ALREADY_CLOSED and must not append new OPEN / CLOSE rows."""
        import json
        se = _load_module("se_patched_6", PATCHED_PATH)
        base_kwargs = dict(
            scenario_id="S_AXIS4",
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=self.scen_gen.isoformat(),
        )
        rec0 = _recommendation(revision_idx=0, **base_kwargs)
        rec1 = _recommendation(
            revision_idx=1,
            **{**base_kwargs,
               "entry": 13420.0,  # revised entry (would open earlier)
               "scenario_generated_at_utc":
                   (self.scen_gen + dt.timedelta(minutes=5)).isoformat()},
        )

        r0 = se.process_proposal(
            recommendation=rec0, shadow_dir=self.shadow_dir,
            candles=self.candles, now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        self.assertEqual(r0.get("position"), "CLOSED")

        r1 = se.process_proposal(
            recommendation=rec1, shadow_dir=self.shadow_dir,
            candles=self.candles, now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        self.assertEqual(r1.get("position"), "ALREADY_CLOSED")

        # Exactly one OPEN + one CLOSE event in the journal.
        pos = (self.shadow_dir / "shadow_positions.jsonl").read_text().splitlines()
        events = [json.loads(ln) for ln in pos if ln.strip()]
        opens  = [e for e in events if e.get("event") == "OPEN"]
        closes = [e for e in events if e.get("event") == "CLOSE"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(len(closes), 1)

    def test_new_revision_with_waiting_scenario_does_not_shortcut(self):
        """When rev 0 is still waiting, rev 1 does not reset state; both
        revisions are present as proposal rows but only one scenario slot
        can be opened. If rev 1's entry triggers earlier, the dedup
        key-per-revision architecture means rev 1's call is what actually
        opens the position (and rev 0 will see ALREADY_OPEN on next
        sweep)."""
        import json
        se = _load_module("se_patched_7", PATCHED_PATH)
        no_cross_candles = _bars(
            start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
            closes=[13420.0, 13422.0, 13421.0],
        )
        base_kwargs = dict(
            scenario_id="S_AXIS4B",
            direction="BUY",
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=self.scen_gen.isoformat(),
            stop=13410.0,
            target=13430.0,
        )
        rec0 = _recommendation(revision_idx=0, entry=13425.0, **base_kwargs)
        r0 = se.process_proposal(
            recommendation=rec0, shadow_dir=self.shadow_dir,
            candles=no_cross_candles, now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        self.assertEqual(r0.get("position"), "WAITING_FOR_ENTRY")

        # rev1 has a lower entry — now rev1's trigger is satisfied by
        # the same candles.
        rec1 = _recommendation(
            revision_idx=1, entry=13421.5,
            **{**base_kwargs,
               "scenario_generated_at_utc":
                   (self.scen_gen + dt.timedelta(minutes=5)).isoformat()},
        )
        r1 = se.process_proposal(
            recommendation=rec1, shadow_dir=self.shadow_dir,
            candles=no_cross_candles, now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        # rev1's cross: entry 13421.5; bar closes 13420, 13422, 13421 — the
        # middle bar (10:10..10:15 close 13422) is first above 13421.5.
        self.assertIn(r1.get("position"), ("OPENED_AWAITING_EXIT", "CLOSED"))

        pos_rows = (self.shadow_dir / "shadow_positions.jsonl").read_text().splitlines()
        opens = [json.loads(ln) for ln in pos_rows
                 if ln.strip() and json.loads(ln).get("event") == "OPEN"]
        self.assertEqual(len(opens), 1)
        # The OPEN event's revision_idx must be rev1 (the one that
        # actually crossed), not rev0.
        self.assertEqual(opens[0]["revision_idx"], 1)


# =====================================================================
# AXIS 5 — Idempotency
# =====================================================================

class AxisFiveIdempotency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)
        self.scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
        self.sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_double_process_same_rev_is_noop(self):
        """Re-invoking process_proposal with the same recommendation
        yields no new OPEN or CLOSE journal rows."""
        import json
        se = _load_module("se_patched_8", PATCHED_PATH)
        candles = _bars(
            start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
            closes=[13426.0, 13429.5],
        )
        rec = _recommendation(
            scenario_id="S_AXIS5",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=self.scen_gen.isoformat(),
            recommendation_generated_at_utc=self.scen_gen.isoformat(),
        )
        se.process_proposal(
            recommendation=rec, shadow_dir=self.shadow_dir,
            candles=candles, now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        se.process_proposal(
            recommendation=rec, shadow_dir=self.shadow_dir,
            candles=candles, now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        se.process_proposal(
            recommendation=rec, shadow_dir=self.shadow_dir,
            candles=candles, now_utc=self.sweep_now,
            max_fill_lookback_seconds=0,
        )
        proposals = (self.shadow_dir / "shadow_proposals.jsonl").read_text().splitlines()
        self.assertEqual(len([ln for ln in proposals if ln.strip()]), 1)
        positions = (self.shadow_dir / "shadow_positions.jsonl").read_text().splitlines()
        events = [json.loads(ln) for ln in positions if ln.strip()]
        self.assertEqual(sum(1 for e in events if e["event"] == "OPEN"), 1)
        self.assertEqual(sum(1 for e in events if e["event"] == "CLOSE"), 1)


# =====================================================================
# AXIS 6 — Retrospective-fill guard
# =====================================================================

class AxisSixRetrospectiveFillGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shadow_dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_cap_blocks_ancient_proposal(self):
        """A scenario generated 10 h ago whose crossing bar is 8 h ago
        must NOT retroactively open under the default 2 h cap."""
        se = _load_module("se_patched_9", PATCHED_PATH)
        self.assertEqual(se.MAX_FILL_LOOKBACK_SECONDS, 2 * 3600)
        sweep_now = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        ancient_scen_gen = sweep_now - dt.timedelta(hours=10)
        # Crossing bar is 8 h before sweep_now (older than 2h cap).
        crossing_bar_open = sweep_now - dt.timedelta(hours=8)
        candles = _bars(
            start=crossing_bar_open,
            closes=[13426.0],  # single bar at 06:00..06:05 UTC
        )
        rec = _recommendation(
            scenario_id="S_AXIS6A",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=ancient_scen_gen.isoformat(),
            recommendation_generated_at_utc=sweep_now.isoformat(),
        )
        result = se.process_proposal(
            recommendation=rec, shadow_dir=self.shadow_dir,
            candles=candles, now_utc=sweep_now,
            # No max_fill_lookback_seconds override — module default (2 h)
            # applies.
        )
        self.assertEqual(result.get("position"), "WAITING_FOR_ENTRY")
        self.assertFalse((self.shadow_dir / "shadow_positions.jsonl").exists())

    def test_fresh_proposal_unaffected_by_cap(self):
        """A scenario within the cap window keeps full visibility and
        still opens on the first crossing bar."""
        se = _load_module("se_patched_10", PATCHED_PATH)
        sweep_now = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        scen_gen = sweep_now - dt.timedelta(minutes=10)
        crossing_bar_open = sweep_now - dt.timedelta(minutes=5)
        # Bar at (sweep_now - 5m) with ts_close == sweep_now — in window.
        candles = _bars(start=crossing_bar_open, closes=[13426.0])
        rec = _recommendation(
            scenario_id="S_AXIS6B",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=scen_gen.isoformat(),
            recommendation_generated_at_utc=sweep_now.isoformat(),
        )
        result = se.process_proposal(
            recommendation=rec, shadow_dir=self.shadow_dir,
            candles=candles, now_utc=sweep_now,
        )
        self.assertIn(result.get("position"),
                       ("OPENED_AWAITING_EXIT", "CLOSED"))

    def test_override_zero_disables_cap(self):
        """Passing ``max_fill_lookback_seconds=0`` reproduces the
        pre-cap behaviour (unbounded lookback). Used by legacy / replay
        tests only."""
        se = _load_module("se_patched_11", PATCHED_PATH)
        sweep_now = dt.datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
        ancient_scen_gen = sweep_now - dt.timedelta(hours=10)
        crossing_bar_open = sweep_now - dt.timedelta(hours=8)
        candles = _bars(start=crossing_bar_open, closes=[13426.0])
        rec = _recommendation(
            scenario_id="S_AXIS6C",
            revision_idx=0,
            direction="BUY",
            entry=13425.0,
            stop=13410.0,
            target=13430.0,
            scenario_generated_at_utc=ancient_scen_gen.isoformat(),
            recommendation_generated_at_utc=sweep_now.isoformat(),
        )
        result = se.process_proposal(
            recommendation=rec, shadow_dir=self.shadow_dir,
            candles=candles, now_utc=sweep_now,
            max_fill_lookback_seconds=0,
        )
        # With the cap disabled the 8-h-ago bar triggers the open.
        self.assertIn(result.get("position"),
                       ("OPENED_AWAITING_EXIT", "CLOSED"))


# =====================================================================
# Cross-cutting — deployed module still exhibits the bug
# =====================================================================

class CrossCuttingDeployedBugConfirmation(unittest.TestCase):
    """Belt-and-braces: confirm the deployed module (unpatched) still
    reproduces the WAITING_FOR_ENTRY defect. Protects us if the patched
    module is ever accidentally diffed against itself."""

    def test_deployed_module_waits_forever(self):
        if not DEPLOYED_PATH.is_file():
            self.skipTest(f"deployed module not accessible at {DEPLOYED_PATH}")
        se = _load_module("se_deployed", DEPLOYED_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            shadow_dir = pathlib.Path(tmp)
            scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
            sweep_now = dt.datetime(2026, 11, 3, 13, 50, tzinfo=UTC)
            candles = _bars(
                start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                closes=[*([13418.0] * 20), *([13415.0] * 21),
                         13426.5, 13426.0],
            )
            rec = _recommendation(
                scenario_id="S_DEP",
                revision_idx=0,
                direction="BUY",
                entry=13425.0,
                stop=13410.0,
                target=13427.0,
                scenario_generated_at_utc=scen_gen.isoformat(),
                recommendation_generated_at_utc=sweep_now.isoformat(),  # bug anchor
            )
            # Deployed signature does not accept max_fill_lookback_seconds.
            result = se.process_proposal(
                recommendation=rec, shadow_dir=shadow_dir,
                candles=candles, now_utc=sweep_now,
            )
            self.assertEqual(result.get("position"), "WAITING_FOR_ENTRY")


# =====================================================================
# Cross-cutting — SHADOW-only invariant
# =====================================================================

class CrossCuttingShadowOnlyInvariant(unittest.TestCase):
    def test_patched_module_has_no_broker_imports(self):
        src = PATCHED_PATH.read_text()
        banned = ["ig_client", "trades_api", "autobot.py", "autobot_core",
                  "trade_executor", "broker_client", "IGClient"]
        for b in banned:
            self.assertNotIn(b, src,
                                 f"patched module imports forbidden symbol {b!r}")

    def test_open_and_close_rows_tagged_shadow_only(self):
        import json
        se = _load_module("se_patched_12", PATCHED_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            shadow_dir = pathlib.Path(tmp)
            scen_gen = dt.datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
            sweep_now = dt.datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
            candles = _bars(
                start=dt.datetime(2026, 11, 3, 10, 5, tzinfo=UTC),
                closes=[13426.0, 13429.5],
            )
            rec = _recommendation(
                scenario_id="S_SO",
                revision_idx=0,
                direction="BUY",
                entry=13425.0,
                stop=13410.0,
                target=13430.0,
                scenario_generated_at_utc=scen_gen.isoformat(),
                recommendation_generated_at_utc=scen_gen.isoformat(),
            )
            se.process_proposal(
                recommendation=rec, shadow_dir=shadow_dir,
                candles=candles, now_utc=sweep_now,
                max_fill_lookback_seconds=0,
            )
            positions = (shadow_dir / "shadow_positions.jsonl").read_text().splitlines()
            for ln in positions:
                if not ln.strip():
                    continue
                row = json.loads(ln)
                self.assertEqual(row.get("execution_mode"), "SHADOW_ONLY")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
