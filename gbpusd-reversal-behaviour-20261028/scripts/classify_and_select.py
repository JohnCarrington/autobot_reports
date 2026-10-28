"""Classify outcomes + select the 20-event research sample.

Outcome labels (research-only; never used in point-in-time features):

For a BULL candidate at bar `b` with low L:
    SUCCESS_BULL   = within +60 min of b, bid rose by ≥ 30 pips above
                     b.close AND did NOT trade through L - 5 pips.
    FAIL_BULL      = within +60 min, bid traded through L - 5 pips.
    AMBIGUOUS_BULL = neither target nor stop hit; price drifted.

Mirror for BEAR.

Sample selection:
    * 5 SUCCESS_BULL
    * 5 FAIL_BULL
    * 5 SUCCESS_BEAR
    * 5 FAIL_BEAR

Choices are made by chronological order (first N from the archive)
to avoid cherry-picking.  If a category has fewer than 5, we take all
and record the shortfall.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, read_bid_m5


HORIZON_MIN = 60
HORIZON_BARS = HORIZON_MIN // 5
TARGET_PIPS = 30.0
STOP_PIPS = 5.0  # pips beyond the test extreme


def _classify(bars: list[Bar], event_idx: int, kind: str) -> str:
    """Return the outcome label for a candidate at bars[event_idx]."""
    end = min(event_idx + HORIZON_BARS, len(bars) - 1)
    extreme = bars[event_idx].low if kind == "BULL" else bars[event_idx].high
    close = bars[event_idx].close
    broke_stop = False
    hit_target = False
    for i in range(event_idx + 1, end + 1):
        if kind == "BULL":
            if bars[i].low <= extreme - STOP_PIPS:
                broke_stop = True
            if bars[i].high >= close + TARGET_PIPS:
                hit_target = True
        else:
            if bars[i].high >= extreme + STOP_PIPS:
                broke_stop = True
            if bars[i].low <= close - TARGET_PIPS:
                hit_target = True
        # Resolve on first decisive event
        if broke_stop and not hit_target:
            return f"FAIL_{kind}"
        if hit_target and not broke_stop:
            return f"SUCCESS_{kind}"
        if hit_target and broke_stop:
            # Both within window — need bar-level resolution; conservative call: FAIL
            return f"FAIL_{kind}"
    return f"AMBIGUOUS_{kind}"


def main() -> int:
    in_csv = HERE.parent / "data" / "reversal_candidates.csv"
    cands = list(csv.DictReader(in_csv.open()))
    print(f"Loaded {len(cands)} candidates")

    # Group candidates by date; classify by loading each day's bars once.
    by_date: dict[str, list[dict]] = {}
    for c in cands:
        by_date.setdefault(c["date"], []).append(c)

    labelled: list[dict] = []
    for date_str, day_cands in sorted(by_date.items()):
        try:
            bars = read_bid_m5(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc))
        except Exception:
            continue
        ts_to_idx = {b.ts.isoformat(): i for i, b in enumerate(bars)}
        for c in day_cands:
            ts = c["event_ts_utc"]
            idx = ts_to_idx.get(ts)
            if idx is None:
                continue
            label = _classify(bars, idx, c["kind"])
            labelled.append({**c, "outcome_label": label})

    # Dump the labelled candidates
    out_lab = HERE.parent / "data" / "reversal_candidates_labelled.csv"
    with out_lab.open("w", newline="") as fh:
        if labelled:
            w = csv.DictWriter(fh, fieldnames=list(labelled[0].keys()))
            w.writeheader()
            for row in labelled:
                w.writerow(row)
    from collections import Counter
    outcome_counts = Counter(x["outcome_label"] for x in labelled)
    print(f"Labelled {len(labelled)} candidates:")
    for k, v in sorted(outcome_counts.items()):
        print(f"  {k:20s}: {v}")

    # Deduplicate: keep only ONE candidate per reversal episode
    # (two consecutive candidates within 60 min of the same date and
    # same kind are the same episode).  Keep the earliest.
    EPISODE_GAP = timedelta(minutes=60)
    deduped: list[dict] = []
    last_by_kind: dict[str, datetime] = {}
    for row in labelled:
        ts = datetime.fromisoformat(row["event_ts_utc"])
        prev = last_by_kind.get(row["kind"])
        if prev is None or (ts - prev) >= EPISODE_GAP:
            deduped.append(row)
            last_by_kind[row["kind"]] = ts
    print(f"\nAfter episode de-duplication: {len(deduped)} independent episodes")
    from collections import Counter
    print("  by outcome: " + ", ".join(
        f"{k}={v}" for k, v in sorted(Counter(x['outcome_label'] for x in deduped).items())
    ))

    # Select 5 of each — chronological order from the de-duplicated set
    def _pick(label: str, n: int = 5) -> list[dict]:
        return [x for x in deduped if x["outcome_label"] == label][:n]

    sample = (
        _pick("SUCCESS_BULL") + _pick("FAIL_BULL") +
        _pick("SUCCESS_BEAR") + _pick("FAIL_BEAR")
    )
    out_sample = HERE.parent / "data" / "reversal_event_population.csv"
    with out_sample.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sample[0].keys()))
        w.writeheader()
        for row in sample:
            w.writerow(row)
    print(f"\n20-event research sample written to: {out_sample}")
    for row in sample:
        print(f"  {row['event_ts_utc']}  {row['kind']:4}  "
              f"{row['outcome_label']:16}  extreme={row['extreme_pts']} "
              f"run={row['run_move_pips']}p depth={row['run_depth_pips']}p")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
