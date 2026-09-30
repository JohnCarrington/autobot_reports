#!/usr/bin/env python3
"""
Backfill briefing_training_corpus.jsonl from briefing JSON files on disk.

Historical briefings only persist the LLM *output* (bias, plans, levels,
reasoning) — the input feature vector that morning_briefing assembled
before calling the LLM was never saved. So backfilled rows carry:

  metadata          — symbol, session, date, briefing_time, prompt_hash (null)
  briefing_output   — the full stored briefing JSON
  input_features    — null (flagged via metadata.partial=true)

Future briefings produced by the live bot (now that the
data/briefing_training permission gap is fixed) will be complete
records with input_features populated.

Usage:
  scripts/backfill_training_corpus.py [briefings_dir]

Default briefings_dir: /opt/tradingbot/logs
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path("/opt/tradingbot/data/briefing_training_corpus.jsonl")
TRAINING_DIR = Path("/opt/tradingbot/data/briefing_training")


def _already_captured() -> set:
    """Return set of (symbol, date, session) tuples already in the corpus."""
    captured: set = set()
    if not CORPUS.exists():
        return captured
    with CORPUS.open() as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except Exception:
                continue
            m = rec.get("metadata") or {}
            key = (m.get("symbol"), m.get("date"), m.get("session"))
            if all(key):
                captured.add(key)
    return captured


def main() -> int:
    briefings_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/tradingbot/logs")
    if not briefings_dir.is_dir():
        print(f"briefings dir not found: {briefings_dir}", file=sys.stderr)
        return 2

    already = _already_captured()
    print(f"corpus currently has {len(already)} (symbol, date, session) records")

    paths = sorted(briefings_dir.glob("briefing_*.json"))
    print(f"scanning {len(paths)} briefing file(s) in {briefings_dir}")

    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_existing = 0
    skipped_malformed = 0

    with CORPUS.open("a") as corpus_fh:
        for p in paths:
            try:
                briefing = json.loads(p.read_text())
            except Exception:
                skipped_malformed += 1
                continue

            symbol = str(briefing.get("symbol", "")).upper()
            session = str(briefing.get("session", ""))
            bt = str(briefing.get("briefing_time", ""))
            date_str = bt[:10] if bt else ""

            if not (symbol and session and date_str):
                skipped_malformed += 1
                continue

            key = (symbol, date_str, session)
            if key in already:
                skipped_existing += 1
                continue

            record = {
                "metadata": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "session": session,
                    "date": date_str,
                    "briefing_time": bt,
                    "model": "",
                    "prompt_version_hash": "",
                    "partial": True,   # input_features not recoverable from disk
                    "source_file": str(p),
                },
                "input_features": None,
                "briefing_output": briefing,
            }

            individual = TRAINING_DIR / f"{symbol}_{date_str}_{session}.json"
            try:
                individual.write_text(json.dumps(record, indent=2, default=str))
            except Exception:
                pass
            corpus_fh.write(json.dumps(record, default=str) + "\n")
            already.add(key)
            written += 1

    print(f"written: {written}")
    print(f"skipped (already in corpus): {skipped_existing}")
    print(f"skipped (malformed / missing metadata): {skipped_malformed}")
    print(f"corpus file: {CORPUS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
