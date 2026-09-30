"""eod_review_indicators.py — Stage 2 stub.

The eod-review-metrics.service unit runs three ExecStart lines in
sequence: this indicators script, then eod_review_metrics.py. Under
systemd Type=oneshot, a non-zero exit from the first ExecStart aborts
the sequence, which would prevent metrics.py from running at all.

This file exists solely to make that sequence pass. The original Stage 2
indicators timeline (per the unit's ExecStart comment: "Stage 2 first
(indicators.json) so Stage 1 can inline entry/exit snapshots into the
trade ledger") was never committed to git and its scripts are absent
from disk. Rebuilding it is out of scope for tonight's rebuild task.

Removing the ExecStart line from the unit is the correct long-term fix,
but that requires operator sign-off since it edits /etc/systemd/system/.
Until then, this stub keeps the pipeline moving.
"""
from __future__ import annotations

import sys


def main() -> int:
    print(
        "eod_review_indicators: stub — indicators pipeline not yet reimplemented. "
        "Exiting 0 so eod_review_metrics.py can run.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
