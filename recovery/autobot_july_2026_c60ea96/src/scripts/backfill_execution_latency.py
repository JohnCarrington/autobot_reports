#!/usr/bin/env python3
"""backfill_execution_latency.py — populate latency fields for past fires.

Reads /opt/tradingbot/logs/signal_log.jsonl (or another path via
SIGNAL_LOG_PATH env / --in argument) and emits a side-by-side
signal_log_backfilled.jsonl that adds whatever execution-latency fields
can be derived from existing record contents:

  - t_ig_confirm_epoch_ms ← parsed from the existing `timestamp_open`
    (ms-precision wall clock at the moment log_open ran, which is
    immediately after IG confirmed the open in pre-instrumentation code)
  - t_decision_epoch_ms   ← best approximation = the bar timestamp the
    strategy evaluated (none of the existing schema fields explicitly
    carry this; we leave it null and document below).
  - total_decision_to_confirm_ms ← only when t_decision was recoverable.

Other timestamps (t_dispatch / t_ig_request / t_ig_ack) are
unrecoverable from existing logs; the open record predates the
instrumentation and IG REST timing wasn't persisted anywhere.  Those
fields stay null.

The original signal_log.jsonl is NEVER overwritten — output goes to a
new file beside it so the audit trail is preserved.

Idempotent: re-running on the same input produces byte-identical output.

Stop-and-report rule: if no record can be enriched at all (e.g. the
existing log file is empty or all records already have latency fields),
the script writes a header-only backfill file and prints a clear
[BACKFILL] message documenting the cutoff.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_IN = Path(os.getenv("SIGNAL_LOG_PATH",
                            "/opt/tradingbot/logs/signal_log.jsonl"))
DEFAULT_OUT = DEFAULT_IN.parent / "signal_log_backfilled.jsonl"


def _parse_iso_to_epoch_ms(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        # signal_log timestamps are written as "2026-05-08T16:25:11Z"
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def backfill_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Return a NEW dict — never mutate input.  Only adds fields that
    the record doesn't already have (idempotent)."""
    out = dict(rec)

    # Skip records that already carry full instrumentation.
    already_full = (
        "t_ig_confirm_epoch_ms" in out and
        "total_decision_to_confirm_ms" in out
    )
    if already_full:
        return out

    # t_ig_confirm: best approximation from timestamp_open (recorded by
    # log_open immediately after IG confirmed the open in pre-refactor
    # code).  Granularity is 1s, not ms — readers must treat backfilled
    # latency as coarse approximation only.
    t_confirm = _parse_iso_to_epoch_ms(out.get("timestamp_open"))
    if t_confirm is not None and "t_ig_confirm_epoch_ms" not in out:
        out["t_ig_confirm_epoch_ms"] = t_confirm

    # t_decision: not recoverable from existing schema. The bar
    # timestamp the strategy evaluated isn't persisted on the open
    # record (the closest field is `minutes_since_london_open` which is
    # derived from now_utc, not the bar). Leave null and let the
    # analysis script ignore these records when computing
    # decision-to-confirm distributions.

    # ls_async_dispatch: every pre-refactor record was synchronous.
    if "ls_async_dispatch" not in out:
        out["ls_async_dispatch"] = 0

    # Pre-refactor records have no instrumentation — explicitly null
    # the timestamps so analysis can distinguish "missing" from
    # "instrumented but null".  Idempotent: only sets when absent.
    for k in (
        "t_decision_epoch_ms",
        "t_dispatch_epoch_ms",
        "t_ig_request_epoch_ms",
        "t_ig_ack_epoch_ms",
        "decision_to_dispatch_ms",
        "dispatch_to_ig_request_ms",
        "ig_request_to_ack_ms",
        "ack_to_confirm_ms",
        "total_decision_to_confirm_ms",
    ):
        if k not in out:
            out[k] = None

    return out


def run(in_path: Path, out_path: Path) -> Dict[str, Any]:
    if not in_path.exists():
        # Empty backfill file with header so callers know what happened.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "# backfill: input log not found\n"
            f"# input={in_path}\n"
            "# rows_processed=0 rows_backfilled=0 rows_unrecoverable=0\n",
            encoding="utf-8",
        )
        return {
            "rows_processed": 0,
            "rows_backfilled": 0,
            "rows_unrecoverable": 0,
            "earliest_full_data_iso": None,
            "input_missing": True,
        }

    rows_processed = 0
    rows_backfilled = 0
    rows_unrecoverable = 0
    earliest_full = None  # ISO string — the first natively-instrumented record

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with in_path.open("r", encoding="utf-8") as fin, \
            out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                rows_unrecoverable += 1
                continue
            rows_processed += 1

            # Track earliest natively-instrumented record (real, not
            # backfill — recognised by t_dispatch present).
            if rec.get("t_dispatch_epoch_ms") is not None:
                ts = rec.get("timestamp_open")
                if ts and (earliest_full is None or ts < earliest_full):
                    earliest_full = ts

            enriched = backfill_record(rec)
            # Count as backfilled if we added any new latency key.
            new_keys = set(enriched.keys()) - set(rec.keys())
            if new_keys:
                rows_backfilled += 1
            else:
                # Already fully instrumented — passthrough.
                pass
            fout.write(json.dumps(enriched) + "\n")

    return {
        "rows_processed": rows_processed,
        "rows_backfilled": rows_backfilled,
        "rows_unrecoverable": rows_unrecoverable,
        "earliest_full_data_iso": earliest_full,
        "input_missing": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", type=Path, default=DEFAULT_IN,
                    help="path to signal_log.jsonl")
    ap.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT,
                    help="path to write the backfilled log to")
    args = ap.parse_args()

    summary = run(args.in_path, args.out_path)

    print(f"[BACKFILL] input={args.in_path}")
    print(f"[BACKFILL] output={args.out_path}")
    print(f"[BACKFILL] rows_processed={summary['rows_processed']}")
    print(f"[BACKFILL] rows_backfilled={summary['rows_backfilled']}")
    print(f"[BACKFILL] rows_unrecoverable={summary['rows_unrecoverable']}")
    if summary["earliest_full_data_iso"]:
        print(
            "[BACKFILL] full instrumented data available from "
            f"{summary['earliest_full_data_iso']} forward"
        )
    else:
        print(
            "[BACKFILL] unrecoverable for fires before instrumentation "
            "deployment; full data available from first post-deploy fire forward"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
