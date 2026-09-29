#!/usr/bin/env python3
"""Multi-variant Era B benchmark with env-history-aware gates.

Runs the same pierce+rejection detector at three pierce thresholds
observed in Era B env history (0.5, 1.0, 2.0), applying:
  - counter-H1 gate (H1 EMA 8/21) — controlled by env-history at fire ts
  - position-slot gate (block if a benchmark position is still open)
  - post-scale-out runner trail (env-controlled from 2026-06-05)

For each false-positive fire (fire without a matching ledger row), the
runner classifies the reason: env pierce threshold at that ts, counter-
H1 direction, position-slot conflict, or UNRESOLVED.

Outputs (in outputs_multi/):
  entry_parity_by_variant.csv    — per variant: matched / FP / FN counts
  false_positives_classified.csv — one row per FP with classification
  exit_parity_blind.csv          — per matched deal: benchmark's blind
                                    exit prediction vs ledger actual
  daily_pnl_comparison.csv       — per-day matched-only totals
  provenance_manifest.json       — commit + snapshot SHAs
  unresolved_differences.md      — plain-English summary

Broker submission: hard-disabled.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from era_b_bench import config
from era_b_bench.candles import Bar, load_range, get_bar_by_open, stream_from
from era_b_bench.entry import (
    EraBEntryDetector, Signal, bb_20_2, detect_pierce_setup, is_rejection,
)
from era_b_bench.env_history import ERA_B_HISTORY, env_at, DISTINCT_PIERCE_THRESHOLDS
from era_b_bench.exits import simulate as run_exits, ExitReport
from era_b_bench.h1 import h1_ema_direction_at, counter_h1_ok_for_short, H1Direction
from era_b_bench.ledger import load_era_b_rows, LedgerRow


OUT = HERE / "outputs_multi"


# ─── position-slot tracker ──────────────────────────────────────────────

class SlotTracker:
    """Track when a benchmark SHORT position is 'open' according to the
    4-exit simulator. A new fire at ts is BLOCKED if any prior fire's
    predicted final-close ts is > ts."""

    def __init__(self):
        self._open_until: List[datetime] = []

    def is_open_at(self, ts: datetime) -> bool:
        # keep only exits still in the future relative to ts
        self._open_until = [t for t in self._open_until if t > ts]
        return len(self._open_until) > 0

    def mark_open(self, exit_ts: datetime) -> None:
        self._open_until.append(exit_ts)


# ─── FP classifier ──────────────────────────────────────────────────────

def _fire_pierce_depth(sig: Signal) -> float:
    """The setup bar's high minus the setup-bar BBU (pips)."""
    return (sig.setup_bar.high - sig.bbu_setup) / config.PIP_UNITS


def classify_fp(sig: Signal, h1: Optional[H1Direction],
                open_slot: bool) -> Tuple[str, Dict[str, Any]]:
    """Return (reason, evidence) for why this fire would have been
    rejected by an Era B admission gate.

    Order: env-threshold > counter-H1 > slot > unresolved.
    """
    env = env_at(sig.ts_utc)
    pierce = _fire_pierce_depth(sig)
    evidence: Dict[str, Any] = {
        "fire_ts": sig.ts_utc.isoformat(),
        "pierce_depth_pips": round(pierce, 3),
        "env_pierce_threshold_pips": env.pierce_thresh_pips,
        "env_h1_counter_gate": env.h1_counter_gate_enabled,
        "h1_direction": h1.direction if h1 else None,
        "h1_separation_pips": round(h1.separation_pips, 3) if h1 else None,
        "h1_separation_strength": round(h1.separation_strength, 3) if h1 else None,
        "slot_open": open_slot,
    }
    if pierce < env.pierce_thresh_pips:
        return "REJECTED_BY_ENV_PIERCE_THRESHOLD", evidence
    if env.h1_counter_gate_enabled and not counter_h1_ok_for_short(h1):
        return "REJECTED_BY_COUNTER_H1", evidence
    if open_slot:
        return "REJECTED_BY_POSITION_SLOT", evidence
    return "UNRESOLVED", evidence


# ─── exit sim with env-history trail ────────────────────────────────────

def simulate_with_env_trail(sig: Signal, downstream: List[Bar]) -> ExitReport:
    """Wrap the base 4-exit simulator; if the env at fire time has
    runner_trail enabled, we don't have a full trail sim in the base
    exits module — we approximate by narrowing the runner's BE stop
    upward from BE toward peak-OFFSET whenever MFE ≥ ACTIVATE.

    Approximation is deliberate: for parity purposes the trail only
    affects OPEN_END_SCALED outcomes and it moves the runner exit
    earlier. We shim it here without touching the base simulator
    (which the unit tests exercise verbatim).
    """
    # Base sim first — that gives us MFE and the sequence.
    base = run_exits(sig, downstream)
    env = env_at(sig.ts_utc)
    if not env.runner_trail_enabled:
        return base
    if base.final is None:
        return base

    # Only apply trail if the position actually scaled out
    if not base.scaled_out:
        return base

    # Walk bars again to detect trail-armed runner exit
    entry = sig.entry_price
    activate = env.runner_trail_activate_pips
    offset   = env.runner_trail_offset_pips
    peak_mfe = 0.0
    trail_armed = False
    trail_sl_price: Optional[float] = None

    # Find the scale-out bar in downstream
    scale_bar_idx = None
    if base.partials:
        scale_ts = base.partials[0].ts_utc
        for i, b in enumerate(downstream):
            if b.close_ts == scale_ts:
                scale_bar_idx = i
                break

    if scale_bar_idx is None:
        return base

    # After scale-out, track peak favourable move (for SHORT = price falling)
    # If trail_sl_price crossed above by a rebound, close at trail_sl_price
    for i, bar in enumerate(downstream[scale_bar_idx:], start=scale_bar_idx + 1):
        f_pips = (entry - bar.low) / config.PIP_UNITS  # positive when favourable
        if f_pips > peak_mfe:
            peak_mfe = f_pips
        if peak_mfe >= activate:
            new_sl = entry - (peak_mfe - offset) * config.PIP_UNITS
            if trail_sl_price is None or new_sl < trail_sl_price:  # for SHORT, lower SL = tighter
                trail_sl_price = new_sl
                trail_armed = True
        if trail_armed and trail_sl_price is not None and bar.high >= trail_sl_price:
            # Trail-stop hit — replace the base final with a trail exit
            from era_b_bench.exits import FinalClose
            trail_pips = (entry - trail_sl_price) / config.PIP_UNITS  # positive (locked profit)
            base.final = FinalClose(
                ts_utc=bar.close_ts, price=trail_sl_price,
                reason="TRAIL_STOP", fraction_closed=base.final.fraction_closed,
                pips=round(trail_pips, 2),
            )
            return base
    return base


# ─── runner ─────────────────────────────────────────────────────────────

def _pierce_threshold_for_bar(setup_ts: datetime) -> float:
    return env_at(setup_ts).pierce_thresh_pips


def run_variant(threshold_mode: str, bars: List[Bar],
                use_counter_h1: bool = True,
                use_slot_gate: bool = True) -> Dict[str, Any]:
    """threshold_mode:
       'env'        → use env-history pierce threshold at each fire time
       '0.5'/'1.0'/'2.0' → fixed threshold across all bars
    """
    fires: List[Signal] = []
    slot = SlotTracker() if use_slot_gate else None
    exits: Dict[str, ExitReport] = {}

    # Snapshot decisions applied to each candidate — needed for FP classification
    diagnostics: Dict[str, Dict[str, Any]] = {}

    # We can't reuse EraBEntryDetector's single fixed threshold when
    # threshold_mode == "env" — reimplement the loop here for that mode.
    if threshold_mode == "env":
        det = _EnvThresholdDetector()
    else:
        det = EraBEntryDetector(pierce_thresh_pips=float(threshold_mode))

    for i, bar in enumerate(bars):
        sig = det.on_bar(bar)
        if sig is None:
            continue
        # Counter-H1 gate at fire time
        h1 = None
        blocked_h1 = False
        env = env_at(sig.ts_utc)
        if use_counter_h1 and env.h1_counter_gate_enabled:
            # Compute H1 direction from bars up to and including cur
            h1 = h1_ema_direction_at(bars[:i+1], pip_units=config.PIP_UNITS)
            if not counter_h1_ok_for_short(h1):
                blocked_h1 = True
        if blocked_h1:
            diagnostics[sig.ts_utc.isoformat()] = {
                "blocked_by": "COUNTER_H1",
                "h1_direction": h1.direction if h1 else None,
                "h1_separation_pips": round(h1.separation_pips, 3) if h1 else None,
            }
            continue
        # Position-slot gate
        if slot is not None and slot.is_open_at(sig.ts_utc):
            diagnostics[sig.ts_utc.isoformat()] = {
                "blocked_by": "POSITION_SLOT",
                "h1_direction": h1.direction if h1 else None,
            }
            continue
        # Fire admitted — run exits
        downstream = stream_from(sig.rejection_bar.close_ts, config.MAX_HOLD_BARS)
        rep = simulate_with_env_trail(sig, downstream)
        exits[sig.ts_utc.isoformat()] = rep
        if slot is not None and rep.final is not None:
            slot.mark_open(rep.final.ts_utc)
        fires.append(sig)

    return {"fires": fires, "exits": exits, "diagnostics": diagnostics}


class _EnvThresholdDetector(EraBEntryDetector):
    """Variant of the detector whose pierce threshold varies by bar
    per env_at(bar.ts)."""

    def __init__(self):
        super().__init__(pierce_thresh_pips=0.5)  # placeholder

    def on_bar(self, cur: Bar) -> Optional[Signal]:
        # Override the fixed pierce threshold for the setup check by
        # temporarily substituting self.pierce_thresh_pips before the
        # base class runs its arm test.
        # Setup bar is bar N-1 = self._bars_seen[-1] AFTER we push cur.
        # For env-lookup purposes, use the SETUP bar's ts (== ts of the
        # previous bar), not cur's ts.
        if len(self._bars_seen) >= 1:
            setup_ts = self._bars_seen[-1].ts
        else:
            setup_ts = cur.ts
        self.pierce_thresh_pips = env_at(setup_ts).pierce_thresh_pips
        return super().on_bar(cur)


# ─── matching + tables ──────────────────────────────────────────────────

def match_ledger(fires: List[Signal], ledger: List[LedgerRow]
                 ) -> Tuple[Dict[str, Signal], List[LedgerRow], List[Signal]]:
    """Return (matched_by_deal, false_negatives, false_positives)."""
    fires_by_key = {(s.rejection_bar.ts.isoformat(), s.direction): s for s in fires}
    matched: Dict[str, Signal] = {}
    fn: List[LedgerRow] = []
    matched_sig_ids: Set[int] = set()
    for row in ledger:
        key = (row.rejection_bar_open_ts.isoformat(), row.direction)
        sig = fires_by_key.get(key)
        if sig is None:
            fn.append(row)
        else:
            matched[row.deal_id] = sig
            matched_sig_ids.add(id(sig))
    fp = [s for s in fires if id(s) not in matched_sig_ids]
    return matched, fn, fp


# ─── outputs ────────────────────────────────────────────────────────────

def write_entry_parity(rows: List[Dict[str, Any]]) -> None:
    with open(OUT / "entry_parity_by_variant.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows: w.writerow(r)


def write_fp_classified(all_fp_rows: List[Dict[str, Any]]) -> None:
    if not all_fp_rows:
        return
    with open(OUT / "false_positives_classified.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_fp_rows[0].keys()))
        w.writeheader()
        for r in all_fp_rows: w.writerow(r)


def write_exit_parity(rows: List[Dict[str, Any]]) -> None:
    with open(OUT / "exit_parity_blind.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows: w.writerow(r)


def write_daily(matched: Dict[str, Signal], exits: Dict[str, ExitReport],
                ledger: List[LedgerRow]) -> None:
    by_day = defaultdict(lambda: {"nL": 0, "nB": 0, "Lp": 0.0, "Bp": 0.0})
    lookup = {row.deal_id: row for row in ledger}
    for row in ledger:
        d = row.timestamp_open.strftime("%Y-%m-%d")
        by_day[d]["nL"] += 1
        by_day[d]["Lp"] += (row.effective_pnl_pips or 0.0)
        sig = matched.get(row.deal_id)
        if sig is not None:
            rep = exits.get(sig.ts_utc.isoformat())
            if rep is not None:
                by_day[d]["nB"] += 1
                by_day[d]["Bp"] += rep.total_pips
    with open(OUT / "daily_pnl_comparison.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "n_ledger", "n_bench", "ledger_pips",
                    "bench_pips", "delta_pips"])
        tot = {"nL":0, "nB":0, "Lp":0.0, "Bp":0.0}
        for d in sorted(by_day):
            v = by_day[d]
            w.writerow([d, v["nL"], v["nB"], round(v["Lp"],2),
                        round(v["Bp"],2), round(v["Bp"]-v["Lp"],2)])
            for k, val in v.items(): tot[k] += val
        w.writerow(["TOTAL", tot["nL"], tot["nB"], round(tot["Lp"],2),
                    round(tot["Bp"],2), round(tot["Bp"]-tot["Lp"],2)])


# ─── main ───────────────────────────────────────────────────────────────

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = load_era_b_rows()
    assert len(ledger) == 36

    bars = load_range("2026-05-23", "2026-06-25")

    # 1. Variant runs — all pierce thresholds + env-history
    variants = ["0.5", "1.0", "2.0", "env"]
    variant_results = {}
    entry_rows: List[Dict[str, Any]] = []

    for v in variants:
        result = run_variant(v, bars, use_counter_h1=True, use_slot_gate=True)
        fires = result["fires"]
        matched, fn, fp = match_ledger(fires, ledger)
        # Also run without gates to get "raw pierce count"
        raw = run_variant(v, bars, use_counter_h1=False, use_slot_gate=False)
        variant_results[v] = {
            "result_gated": result, "matched": matched,
            "fn": fn, "fp": fp,
            "result_raw": raw,
        }
        entry_rows.append({
            "variant": v,
            "raw_fires": len(raw["fires"]),
            "after_counter_h1_and_slot_fires": len(fires),
            "matched_ledger": len(matched),
            "false_positives": len(fp),
            "false_negatives": len(fn),
            "match_rate_pct": round(len(matched)/36*100, 1),
            "counter_h1_blocks": sum(1 for d in raw["diagnostics"].values() if d.get("blocked_by") == "COUNTER_H1"),
            "slot_blocks":       sum(1 for d in raw["diagnostics"].values() if d.get("blocked_by") == "POSITION_SLOT"),
        })
    write_entry_parity(entry_rows)

    # 2. FP classification for the env-history variant (the best single-run truth)
    fp_rows: List[Dict[str, Any]] = []
    # Use RAW fires (no gates applied) as the FP candidate set — so we can
    # attribute each raw pierce+rejection to the specific gate that would
    # reject it. Compare against the ledger.
    for v in variants:
        raw = variant_results[v]["result_raw"]
        raw_fires = raw["fires"]
        # Bug fix (2026-09-29): the gated and raw runs create separate
        # Signal instances, so id() comparison always failed and marked
        # matched signals as FP. Use (rejection_bar_ts, direction) — the
        # same key match_ledger uses.
        matched_keys = {
            (variant_results[v]["matched"][d].rejection_bar.ts.isoformat(),
             variant_results[v]["matched"][d].direction)
            for d in variant_results[v]["matched"]
        }
        for sig in raw_fires:
            key = (sig.rejection_bar.ts.isoformat(), sig.direction)
            if key in matched_keys:
                continue
            # Compute H1 direction at fire ts
            idx = next((i for i, b in enumerate(bars) if b.ts == sig.rejection_bar.ts), None)
            h1 = None
            if idx is not None:
                h1 = h1_ema_direction_at(bars[:idx+1], pip_units=config.PIP_UNITS)
            slot = SlotTracker()  # use fresh slot per variant per fire — approximate
            # We can't reconstruct slot state perfectly here without replaying
            # in order; slot classification only makes sense within a single
            # ordered run, so use the gated diagnostics.
            gated_diag = variant_results[v]["result_gated"]["diagnostics"].get(sig.ts_utc.isoformat())
            reason, evidence = classify_fp(sig, h1, open_slot=False)
            if gated_diag and gated_diag.get("blocked_by") == "POSITION_SLOT":
                reason = "REJECTED_BY_POSITION_SLOT"
                evidence["slot_open"] = True
            fp_rows.append({
                "variant": v,
                "fire_ts": sig.ts_utc.isoformat(),
                "rejection_bar_open": sig.rejection_bar.ts.isoformat(),
                "setup_bar_open": sig.setup_bar.ts.isoformat(),
                "entry_price": sig.entry_price,
                "reason": reason,
                **evidence,
            })
    write_fp_classified(fp_rows)

    # 3. Exit parity (blind) — using env variant, no lookup of ledger close_reason
    env_run = variant_results["env"]
    exit_rows: List[Dict[str, Any]] = []
    for row in ledger:
        sig = env_run["matched"].get(row.deal_id)
        rep = env_run["result_gated"]["exits"].get(sig.ts_utc.isoformat()) if sig else None
        # Ledger close classification — replayable vs not
        cr = (row.close_reason_canonical or "").upper()
        NON_REPLAYABLE = {"EXTERNAL_MANUAL", "IG_RECONCILE", "LABEL_K_OPERATOR",
                         "PRE_NEWS_CLOSE", "NY_CLOSE", "MANAGER_PROFIT_PROTECT",
                         "AUTO_K_PREMISE", "QM_BAND_CLOSE_INSIDE",
                         "EXIT_PROFILE_SQUEEZE", "BB_FLIP", "BB_RANGE_TARGET",
                         "STRUCTURE_EXIT",  # requires structure module not in scope
                         "BRIEFING_TP1_CLOSE", "BRIEFING_TP_SL_OPEN",  # env=0 but ledger has them; unexplained
                         "GBPUSD_BB_BOUNCE_S_TIER_SL_OPEN",
                         "BE_HIT_IG"}
        replayable = cr not in NON_REPLAYABLE
        partials_str = ""
        final_str = ""
        bench_pips = ""
        if rep is not None:
            partials_str = ";".join(
                f"{p.ts_utc.isoformat()}@{round(p.price,3)}:pips={round(p.pips_banked,2)}:frac={p.fraction_closed}"
                for p in rep.partials
            )
            if rep.final:
                final_str = (f"{rep.final.ts_utc.isoformat()}@{round(rep.final.price,3)}:"
                             f"{rep.final.reason}:pips={round(rep.final.pips,2)}:frac={rep.final.fraction_closed}")
            bench_pips = round(rep.total_pips, 2)
        exit_rows.append({
            "deal_id": row.deal_id,
            "matched": sig is not None,
            "trade_date": row.timestamp_open.strftime("%Y-%m-%d"),
            "ledger_close_reason": row.close_reason_canonical,
            "ledger_replayable": replayable,
            "ledger_partial_bank_pips": row.partial_bank_pips if row.partial_bank_pips is not None else "",
            "ledger_runner_pnl_pips": row.runner_pnl_pips if row.runner_pnl_pips is not None else "",
            "ledger_effective_pnl_pips": row.effective_pnl_pips,
            "ledger_scaled_out": row.scaled_out,
            "bench_partials": partials_str,
            "bench_final": final_str,
            "bench_total_pips": bench_pips,
            "bench_scaled_out": rep.scaled_out if rep else "",
            "bench_mfe_pips": rep.mfe_pips if rep else "",
            "bench_mae_pips": rep.mae_pips if rep else "",
            "delta_pips": (round(rep.total_pips - (row.effective_pnl_pips or 0), 2)
                           if rep is not None and row.effective_pnl_pips is not None else ""),
        })
    write_exit_parity(exit_rows)

    # 4. Daily P&L
    write_daily(env_run["matched"], env_run["result_gated"]["exits"], ledger)

    # 5. Provenance
    _write_provenance()

    # ─── summary to stdout ─────────────────────────────────────────
    summary = {
        "broker_submission_enabled": config.IG_SUBMISSION_ENABLED,
        "variants": entry_rows,
        "env_variant_totals": {
            "matched": len(env_run["matched"]),
            "false_positives": len(env_run["fp"]),
            "ledger_replayable_closes": sum(1 for r in exit_rows if r["ledger_replayable"]),
            "ledger_non_replayable_closes": sum(1 for r in exit_rows if not r["ledger_replayable"]),
            "bench_total_pips": round(sum(r["bench_total_pips"] for r in exit_rows if isinstance(r["bench_total_pips"], (int, float))), 2),
            "ledger_total_pips": round(sum(r["ledger_effective_pnl_pips"] or 0.0 for r in exit_rows), 2),
        },
        "fp_reason_distribution_env_variant": _fp_dist(fp_rows, "env"),
        "fp_reason_distribution_0.5_variant": _fp_dist(fp_rows, "0.5"),
        "fp_reason_distribution_1.0_variant": _fp_dist(fp_rows, "1.0"),
        "fp_reason_distribution_2.0_variant": _fp_dist(fp_rows, "2.0"),
    }
    with open(OUT / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


def _fp_dist(fp_rows: List[Dict[str, Any]], variant: str) -> Dict[str, int]:
    c = Counter(r["reason"] for r in fp_rows if r["variant"] == variant)
    return dict(c)


def _write_provenance() -> None:
    pins = HERE / "spec_pins"
    src  = HERE / "era_b_src"
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "spec_pin_commit": "714af5b (github.com/JohnCarrington/autobot_reports)",
        "source_pin_commit": "c85481c (github.com/JohnCarrington/AutoBot, plus e8fc9dd within-day; both dated 2026-05-23)",
        "pinned_spec_files": {p.name: sha(p) for p in pins.rglob("*") if p.is_file()},
        "pinned_source_files": {p.name: sha(p) for p in src.rglob("*.py")},
        "env_snapshots_count": len(list((pins / "env_history").rglob("*"))) if (pins / "env_history").exists() else 0,
    }
    with open(OUT / "provenance_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    assert not config.IG_SUBMISSION_ENABLED, "Broker submission must be disabled"
    main()
