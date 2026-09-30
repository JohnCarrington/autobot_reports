#!/usr/bin/env python3
"""
One-shot cleanup: mark every CONTINUATION_SWEEP signal_log entry whose
outcome is still null as PHANTOM_NEVER_EXECUTED. These are the rows left
behind by the now-fixed autobot bookkeeping gap where execute_trade
returned None but signal_logger.log_open still fired.

Creates a timestamped backup of signal_log.jsonl before rewriting.
Safe to re-run — only touches rows where outcome is currently null AND
strategy == CONTINUATION_SWEEP.

Usage:  ./scripts/mark_phantom_continuation_sweep.py
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path("/opt/tradingbot/logs/signal_log.jsonl")
TARGET_STRATEGY = "CONTINUATION_SWEEP"
OUTCOME_LABEL = "PHANTOM_NEVER_EXECUTED"


def main() -> int:
    if not LOG.exists():
        print(f"signal_log not found at {LOG}", file=sys.stderr)
        return 1

    ts_close = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    backup = LOG.with_suffix(f".jsonl.bak.{ts_close.replace(':', '').replace('-', '')}")
    shutil.copy2(LOG, backup)
    print(f"backup → {backup}")

    raw = LOG.read_text(encoding="utf-8")
    lines = raw.splitlines()
    out_lines = []
    patched = 0
    scanned = 0
    for line in lines:
        s = line.strip()
        if not s:
            out_lines.append(s)
            continue
        try:
            rec = json.loads(s)
        except Exception:
            out_lines.append(s)
            continue

        scanned += 1
        needs_patch = (
            rec.get("strategy") == TARGET_STRATEGY
            and rec.get("outcome") is None
        )
        if not needs_patch:
            out_lines.append(s)
            continue

        rec["outcome"] = OUTCOME_LABEL
        rec["close_reason"] = OUTCOME_LABEL
        rec["close_type"] = OUTCOME_LABEL
        rec["timestamp_close"] = ts_close
        rec["pnl_pips"] = 0.0
        rec["close_price"] = rec.get("entry")
        rec["duration_minutes"] = 0
        out_lines.append(json.dumps(rec))
        patched += 1

    if patched == 0:
        print(f"scanned {scanned} rows — 0 CONTINUATION_SWEEP orphans to patch.")
        return 0

    LOG.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"scanned {scanned} rows — patched {patched} CONTINUATION_SWEEP orphans to "
          f"{OUTCOME_LABEL}. backup at {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
