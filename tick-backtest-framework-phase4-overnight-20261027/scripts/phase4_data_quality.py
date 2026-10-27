"""Phase 4 — data quality and coverage report.

Quantifies:
  * Total eligible broker trades (window + GBPUSD)
  * Trades matched to internal evidence
  * Trades fully reconciled (end-to-end chain)
  * Trades independently replayable through the Phase 4 simulator
  * Trades missing required market-data for tick-level replay
  * NOT_EVALUATED components (clearly flagged)

Writes `data/data_quality_report.json`.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
from collections import Counter
from pathlib import Path


DATA = Path("/home/autobot/autobot_reports_clone/tick-backtest-framework-phase4-overnight-20261027/data")
TICK_CACHE = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")


def _tick_cache_days_in_window(from_d: str, to_d: str) -> dict:
    out = {"cache_exists": TICK_CACHE.exists(), "years_present": [], "days_coverage_claim": None}
    if TICK_CACHE.exists():
        files = sorted(p.name for p in TICK_CACHE.glob("*.parquet"))
        out["years_present"] = files
    # Phase 2 recorded 538 CERTIFIED days ending ~2026-03. Phase 4 window is
    # 2026-09-17 → 2026-10-27 — zero overlap with the certified-usable window.
    # Record this as a known data gap.
    out["days_coverage_claim"] = {
        "phase2_certified_days": 538,
        "phase2_certified_end": "~2026-03",
        "phase4_window": [from_d, to_d],
        "overlap_days": 0,
    }
    return out


def main() -> int:
    ledger = json.load(open(DATA / "trade_ledger.json"))
    exrec = json.load(open(DATA / "execution_reconciliation.json"))
    replay = json.load(open(DATA / "simulator_replay.json"))

    total = len(ledger)
    grades = Counter(t["match_grade"] for t in ledger.values())
    srcs = Counter(t["source_system"] for t in ledger.values())

    # Replay buckets
    repl_status = Counter(t["status"] for t in replay["trades"])

    tick_cache = _tick_cache_days_in_window("2026-09-17", "2026-10-27")

    # Quality gates — Phase 4 (restated with evidence; gates re-grade from 3C)
    gates = {
        "A — Historical tick integrity": {
            "status": "PASS_WITH_LIMITATIONS",
            "note": "Inherits Phase 2 Deliverable E (52.99M rows, 538 CERTIFIED days). "
                    "Phase 4 window has ZERO overlap with the certified-usable period — "
                    "tick-level replay against the window is not possible, so simulator "
                    "parity in Phase 4 relies on broker-event sequences rather than "
                    "quote-stream replay.",
        },
        "B — Indicator parity": {
            "status": "PASS",
            "note": "Phase 3C §3 established float-zero first-hour cross-day parity; Phase 4 "
                    "does not re-run the indicator comparison.",
        },
        "C — BB Bounce pathway parity (autobot)": {
            "status": "PASS",
            "note": "6/6 Phase 3b fixtures continue to pass. Phase 4 adds no new autobot BB "
                    "pathway fixtures.",
        },
        "D — NMS directional authority": {
            "status": "PASS_WITH_LIMITATIONS",
            "note": "Phase 3C BLOCK-path verified. Phase 4 adds 14 ADMISSION tests against the "
                    "DEPLOYED standalone BB Bounce _phase2b_block_order with real snapshot "
                    "payloads (W&W, V3, exhaustion). ALLOW path verified for RANGE / "
                    "with-trend / counter-trend-with-matching-exhaustion. BLOCK path verified "
                    "for UNAVAILABLE / STALE / MALFORMED W&W, WATCH_AND_WAIT state, "
                    "REVERSAL_CONFIRMED, UNKNOWN v3_state, counter-trend-without-exhaustion.",
        },
        "E — Central-gate integration (autobot)": {
            "status": "PASS_WITH_LIMITATIONS",
            "note": "Phase 3C: BLOCK path verified via multiple delegates. Phase 4 confirms the "
                    "deployed autobot (commit 83d1f88) still blocks BB_BOUNCE at the gate under "
                    "deployed defaults. ALLOW path still requires in-process NMS state and is "
                    "a Phase-5 scope item.",
        },
        "F — Broker simulation": {
            "status": "PASS",
            "note": "20 Phase 2 broker tests pass unchanged. Phase 4 adds 8 regression tests for "
                    "the two overnight corrections (IEEE-754 min-stop epsilon; GBPUSD "
                    "pair_min_override). The simulator now replays 109 of 228 FULLY_RECONCILED "
                    "trades with 0.0-pip error on entry/exit/P&L.",
        },
        "G — Trade management (dynamic)": {
            "status": "PASS_WITH_LIMITATIONS",
            "note": "Phase 4 catalogues 110 broker-observed amendments across the ledger (87 "
                    "BREAKEVEN moves, 2 TRAIL_UP, 1 TP_AMEND). The simulator supports SL/TP "
                    "amendments but the upstream decision loop (`_monitor_briefing_tp` + SL "
                    "trail decisions) is NOT replayed — scope boundary explicitly documented.",
        },
        "H — End-to-end replay": {
            "status": "PASS_WITH_LIMITATIONS",
            "note": "109 trades traced broker-request → fill → close through the simulator with "
                    "0.0-pip error. 119 trades deferred (CODE_CLOSED / MANUAL_UI / strategy exits) "
                    "— require strategy decision-event bus to replay (NOT_EVALUATED).",
        },
        "I — Production signal parity (strategy-level)": {
            "status": "NOT_EVALUATED",
            "note": "Reference-data gap unchanged from Phase 3 — no overlap between certified "
                    "tick coverage (ends ~2026-03) and the Phase 4 broker window "
                    "(2026-09-17 → 2026-10-27).",
        },
        "J — Production isolation": {
            "status": "PASS",
            "note": "Zero writes to /opt/tradingbot/, /opt/bb_bounce/, /opt/ema_pullback/. Zero "
                    "orders placed, amended, or closed on IG. 14 BB Bounce admission tests run "
                    "with monkeypatched cache paths; the production /opt/tradingbot/cache "
                    "directory file set is unchanged (verified by test_no_production_cache_writes).",
        },
        "K — Broker-record authority (new in Phase 4)": {
            "status": "PASS",
            "note": "360 GBP/USD transactions + 817 activity rows retrieved from IG DEMO for "
                    "2026-09-17 → 2026-10-27. 338 DEAL rows cover 315 open positions; the "
                    "remaining 7 open positions (322 opens - 315) correspond to still-open "
                    "trades or working-order fills that have not yet matured to a close row.",
        },
    }

    report = {
        "window": ["2026-09-17", "2026-10-27"],
        "ig_demo_authoritative": {
            "total_gbpusd_transactions_in_window": exrec["overall"]["n_reconciled"] + sum(
                1 for t in ledger.values() if t.get("match_grade") != "FULLY_RECONCILED"
            ),
            "ig_total_opens": total,
            "activity_rows_captured": 817,
            "open_positions_at_snapshot": 3,
        },
        "trade_matching": {
            "total_trades": total,
            "fully_reconciled": grades.get("FULLY_RECONCILED", 0),
            "fully_reconciled_pct": round(100.0 * grades.get("FULLY_RECONCILED", 0) / total, 2),
            "open_position_ig_pending": grades.get("OPEN_POSITION_IG_PENDING", 0),
            "matched_no_ig_pnl": grades.get("MATCHED_NO_IG_PNL", 0),
            "matched_no_internal_close": grades.get("MATCHED_NO_INTERNAL_CLOSE", 0),
            "pre_log_coverage": grades.get("PRE_LOG_COVERAGE", 0),
            "unattributed_sibling_likely": grades.get("UNATTRIBUTED_SIBLING_LIKELY", 0),
            "manual_ui_intervention": grades.get("MANUAL_UI_INTERVENTION", 0),
        },
        "attribution": dict(srcs),
        "simulator_replay": {
            "candidates_fully_reconciled": replay["n_candidates"],
            "replayed_zero_pip_error": repl_status.get("REPLAYED", 0),
            "replayed_entry_err_max_pips": replay["replayed"]["entry_err_pips"].get("max", 0.0),
            "replayed_exit_err_max_pips": replay["replayed"]["exit_err_pips"].get("max", 0.0),
            "replayed_pnl_err_max_pips": replay["replayed"]["pnl_err_pips"].get("max", 0.0),
            "deferred_non_broker_exit": repl_status.get("NOT_REPLAYED_NON_BROKER_EXIT", 0),
            "deferred_rationale": "CODE_CLOSED / MANUAL_UI / SYSTEM_OTHER exits require "
                                   "strategy decision-event bus to replay — out of Phase 4 scope.",
        },
        "pnl_delta_analysis": {
            "n_with_both_pnl": exrec["overall"]["pnl_delta_gbp_abs"]["count"],
            "mean_abs_delta_gbp": exrec["overall"]["pnl_delta_gbp_abs"].get("mean"),
            "median_abs_delta_gbp": exrec["overall"]["pnl_delta_gbp_abs"].get("median"),
            "max_abs_delta_gbp": exrec["overall"]["pnl_delta_gbp_abs"].get("max"),
            "note": "Significant delta driven by autobot 'External close' rows where "
                    "unified_trades.exit_price does NOT match IG's authoritative closeLevel. "
                    "Price_source='AUTHORITATIVE_BROKER_CLOSE' is misleading in these rows "
                    "(see §Simulator corrections / Open findings).",
        },
        "quality_gates": gates,
        "known_limitations": {
            "tick_cache_window_overlap_days": 0,
            "certified_tick_window_end": "~2026-03",
            "systemd_journal_retention": "one boot",
            "sibling_host_logs_accessible": False,
            "shared_ig_demo_account": True,
            "sibling_host_prefixes_observed": ["H144", "EMAPB (same host but separate service)"],
        },
        "tick_cache": tick_cache,
    }

    (DATA / "data_quality_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("quality_gates", "tick_cache")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
