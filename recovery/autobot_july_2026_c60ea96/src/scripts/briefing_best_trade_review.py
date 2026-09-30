#!/usr/bin/env python3
"""
briefing_best_trade_review.py — review tool for the Phase A best_trade
emission. Loads the last N briefings on disk, prints plan_summary
side-by-side with the new structured best_trade pointer, runs the same
validator the live pipeline runs, and surfaces mismatches.

Use cases:
  - Pre-deploy verification against existing briefings (best_trade absent
    in all of them — exercises the "null is valid" path)
  - Post-deploy daily review of LLM emit quality (CONDITIONAL vs
    UNCONDITIONAL distribution, plan_rank resolution failures, mode
    mis-translations versus the prose in plan_summary)

Output:
  - For each briefing: file, plan_summary (truncated), best_trade
    structured form, validation outcome
  - Summary counts: UNCONDITIONAL / CONDITIONAL / null / validation_failed
  - Heuristic flags for likely LLM mis-translations:
      * plan_summary contains "if ... else" / "if ... ; if" / "depending"
        but best_trade.mode == UNCONDITIONAL
      * plan_summary commits to one direction with no alternatives but
        best_trade.mode == CONDITIONAL

Run:
  /opt/tradingbot/venv/bin/python3 scripts/briefing_best_trade_review.py
  /opt/tradingbot/venv/bin/python3 scripts/briefing_best_trade_review.py --n 25
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from glob import glob
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, "/opt/tradingbot")

import morning_briefing as mb  # noqa: E402  — uses _validate_best_trade


LOG_DIR = "/opt/tradingbot/logs"

CONDITIONAL_HINT_RE = re.compile(
    r"\b(if|else|depending|when\s+\w+\s+(then|,)|either|or\s+if|"
    r"hawkish|dovish|breaks\s+(higher|lower)\s*,)\b",
    re.IGNORECASE,
)


def _load_recent_briefings(n: int) -> List[Tuple[str, Dict[str, Any]]]:
    """Return the most recent n briefings on disk (across all pairs/sessions),
    sorted by modification time descending."""
    files = sorted(
        glob(os.path.join(LOG_DIR, "briefing_*_*.json")),
        key=os.path.getmtime,
        reverse=True,
    )[:n]
    out: List[Tuple[str, Dict[str, Any]]] = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            out.append((f, d))
        except Exception as exc:
            print(f"  ! skipping {os.path.basename(f)}: {exc}")
    return out


def _format_best_trade(bt: Optional[Dict[str, Any]]) -> str:
    if bt is None:
        return "null"
    mode = bt.get("mode")
    if mode == "UNCONDITIONAL":
        return (
            f"UNCONDITIONAL → ({bt.get('plan_session')}, rank={bt.get('plan_rank')}) "
            f"— {bt.get('reasoning', '')[:100]}"
        )
    if mode == "CONDITIONAL":
        branches = bt.get("conditional_branches") or []
        rendered = " | ".join(
            f"[{b.get('condition_text', '?')[:30]}] → ({b.get('plan_session')}, rank={b.get('plan_rank')})"
            for b in branches
        )
        return f"CONDITIONAL → {rendered}\n      reasoning: {bt.get('reasoning', '')[:100]}"
    return f"<unknown mode={mode}>"


def _classify_prose(plan_summary: str) -> str:
    """Heuristic: 'CONDITIONAL_LIKELY' / 'UNCONDITIONAL_LIKELY' / 'UNCERTAIN'."""
    if not plan_summary or not plan_summary.strip():
        return "UNCERTAIN"
    if CONDITIONAL_HINT_RE.search(plan_summary):
        return "CONDITIONAL_LIKELY"
    if re.search(r"^(primary setup|wait for|setup:)", plan_summary, re.IGNORECASE):
        return "UNCONDITIONAL_LIKELY"
    if re.search(r"\b(then|after)\b", plan_summary, re.IGNORECASE) and \
       re.search(r"\b(or|either)\b", plan_summary, re.IGNORECASE):
        return "CONDITIONAL_LIKELY"
    return "UNCONDITIONAL_LIKELY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10, help="briefings to review")
    parser.add_argument("--pair", type=str, default=None,
                        help="filter to one pair (e.g. GBPUSD)")
    args = parser.parse_args()

    briefings = _load_recent_briefings(args.n * 4 if args.pair else args.n)
    if args.pair:
        briefings = [
            (f, d) for (f, d) in briefings
            if d.get("symbol", "").upper() == args.pair.upper()
        ][: args.n]

    if not briefings:
        print("No briefings found.")
        return 1

    counts = {
        "UNCONDITIONAL": 0,
        "CONDITIONAL": 0,
        "null": 0,
        "validation_cleared": 0,
    }
    mistranslation_flags: List[str] = []

    print(f"Reviewing {len(briefings)} most recent briefings\n")

    for path, briefing in briefings:
        sym = briefing.get("symbol", "?")
        sess = briefing.get("session", "?")
        plan_summary = briefing.get("plan_summary", "") or ""
        bt_raw_before = briefing.get("best_trade")
        omit_reason = briefing.get("best_trade_omission_reason")

        # Run the live validator. It mutates the briefing dict in place.
        # Snapshot BEFORE so we can detect "validator cleared it."
        before_present = bt_raw_before is not None
        try:
            mb._validate_best_trade(briefing, sym, sess)
        except Exception as exc:
            print(f"  ! validator raised on {os.path.basename(path)}: {exc}")
            continue
        bt_raw_after = briefing.get("best_trade")
        if before_present and bt_raw_after is None:
            counts["validation_cleared"] += 1
            verdict = "CLEARED_BY_VALIDATOR"
        elif bt_raw_after is None:
            counts["null"] += 1
            verdict = "null"
        else:
            mode = bt_raw_after.get("mode")
            if mode in counts:
                counts[mode] += 1
            verdict = mode or "<unknown>"

        prose_class = _classify_prose(plan_summary)
        if (prose_class == "CONDITIONAL_LIKELY"
                and bt_raw_after is not None
                and bt_raw_after.get("mode") == "UNCONDITIONAL"):
            mistranslation_flags.append(
                f"  ! prose looks CONDITIONAL but mode=UNCONDITIONAL — "
                f"{os.path.basename(path)}"
            )
        elif (prose_class == "UNCONDITIONAL_LIKELY"
              and bt_raw_after is not None
              and bt_raw_after.get("mode") == "CONDITIONAL"):
            mistranslation_flags.append(
                f"  ! prose looks UNCONDITIONAL but mode=CONDITIONAL — "
                f"{os.path.basename(path)}"
            )

        print(f"  {os.path.basename(path)}")
        print(f"    plan_summary: {plan_summary[:160]}")
        print(f"    best_trade  : {_format_best_trade(bt_raw_after)}")
        if omit_reason:
            print(f"    omission    : {omit_reason}")
        if verdict == "CLEARED_BY_VALIDATOR":
            print(f"    ⚠ best_trade was present in JSON but validator cleared it")
        print(f"    prose_class : {prose_class}  mode_verdict : {verdict}")
        print()

    print("=== Summary ===")
    total = sum(counts.values())
    for k, v in counts.items():
        pct = (100 * v / total) if total else 0
        print(f"  {k:22s} {v:3d}  ({pct:.0f}%)")
    print()
    if mistranslation_flags:
        print("Mistranslation flags (plan_summary class vs best_trade.mode):")
        for f in mistranslation_flags:
            print(f)
    else:
        print("(no mistranslation flags raised)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
