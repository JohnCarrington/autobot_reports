#!/usr/bin/env python3
"""Backfill outcomes for /opt/tradingbot/logs/forensic_fires.jsonl.

For each forensic record without an outcome, attempts to match against:
  1. signal_log.jsonl, by (fire_bar_ts, strategy, direction)
  2. journalctl SENTINEL outcome-push events (fallback for
     dispatcher-gap fires that bypass signal_logger)

Atomic in-place update of the forensic log: read all → mutate matched
→ write to temp file → os.replace() (atomic on POSIX).

Idempotent: re-running on a partially-backfilled log will only update
records that still lack an outcome.

Usage:
    python3 scripts/forensic_outcome_backfill.py [--dry-run] [--no-journal]
                                                 [--forensic-log PATH]
                                                 [--signal-log PATH]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path("/opt/tradingbot")
DEFAULT_FORENSIC_LOG = ROOT / "logs" / "forensic_fires.jsonl"
DEFAULT_SIGNAL_LOG = ROOT / "logs" / "signal_log.jsonl"

logger = logging.getLogger("forensic_outcome_backfill")


# ─── helpers ─────────────────────────────────────────────────────────────
def _bar_ts_from_open(open_iso: str) -> str:
    """Map signal_log.timestamp_open → eval-bar timestamp.

    Convention: timestamp = bar OPEN time, bar covers ts → ts+5m.
    Eval bar = (timestamp_open floored to 5-min) − 5min.
    e.g. 06:55:02 → floor 06:55 → minus 5 → 06:50.
    """
    t = datetime.fromisoformat(open_iso.replace("Z", "+00:00"))
    floored = t.replace(second=0, microsecond=0,
                        minute=(t.minute // 5) * 5)
    return (floored - timedelta(minutes=5)).isoformat()


def _normalize_direction(d: Optional[str]) -> str:
    d = (d or "").upper()
    if d == "BUY":
        return "LONG"
    if d == "SELL":
        return "SHORT"
    return d


def _load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    out: List[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _atomic_write_jsonl(path: Path, records: List[dict]) -> None:
    """Atomically rewrite path with the given records (one per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, dir=str(path.parent),
            prefix=path.name + ".tmp.",
        ) as tmp:
            tmp_path = Path(tmp.name)
            for rec in records:
                tmp.write(json.dumps(rec, separators=(",", ":")) + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(str(tmp_path), str(path))
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


# ─── validation ──────────────────────────────────────────────────────────
# Strategy family names that MUST appear in their directional-variant form
# in forensic_fires.jsonl. signal_log writes the directional variant; the
# backfill join is by exact `strategy` match, so a family-name-only record
# silently fails to match. This is purely a wiring-bug guard — it prints a
# warning, does not block execution.
_FAMILY_TO_VARIANTS: Dict[str, tuple] = {
    "GBPUSD_TREND_CONTINUATION": ("GBPUSD_TREND_CONT_L", "GBPUSD_TREND_CONT_S"),
    "GBPUSD_BB_BOUNCE":          ("GBPUSD_BB_BOUNCE_L",  "GBPUSD_BB_BOUNCE_S"),
    "GBPUSD_BB_REV_PAT":         ("GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S"),
}


def _scan_family_name_records(forensic: List[dict]) -> List[dict]:
    """Return forensic records whose `strategy` is a known family name
    (e.g. GBPUSD_TREND_CONTINUATION) instead of the directional variant
    that signal_log uses. These records will not match by signal_log
    join — flag them as a wiring bug to be fixed at the writer."""
    bad: List[dict] = []
    for rec in forensic:
        strat = rec.get("strategy") or ""
        if strat in _FAMILY_TO_VARIANTS:
            bad.append({
                "fire_bar_ts": rec.get("fire_bar_ts"),
                "strategy": strat,
                "direction": rec.get("direction"),
                "expected_variants": _FAMILY_TO_VARIANTS[strat],
            })
    return bad


# ─── matching ────────────────────────────────────────────────────────────
def _match_signal_log(
    forensic_rec: dict, signal_log: List[dict],
) -> Optional[dict]:
    """Find the signal_log entry matching this forensic record.

    Match key: (fire_bar_ts derived from timestamp_open, strategy,
    normalized direction).
    """
    target_bar = forensic_rec.get("fire_bar_ts")
    target_strat = forensic_rec.get("strategy")
    target_dir = forensic_rec.get("direction")
    if not (target_bar and target_strat and target_dir):
        return None

    for s in signal_log:
        if s.get("strategy") != target_strat:
            continue
        if _normalize_direction(s.get("direction")) != target_dir:
            continue
        ts_open = s.get("timestamp_open")
        if not ts_open:
            continue
        try:
            sl_bar = _bar_ts_from_open(ts_open)
        except Exception:
            continue
        if sl_bar == target_bar:
            return s
    return None


def _journal_outcome(forensic_rec: dict) -> Optional[dict]:
    """Recover outcome via journalctl for dispatcher-gap fires.

    Searches a 24-hour window starting at fire_bar_ts for SENTINEL
    outcome-push events paired with Trade-closed events whose pos_key
    matches the strategy (or DEFAULT after restart).
    """
    fire_bar_ts = forensic_rec.get("fire_bar_ts")
    target_strategy = forensic_rec.get("strategy", "")
    if not fire_bar_ts:
        return None
    try:
        t_start = datetime.fromisoformat(fire_bar_ts)
    except Exception:
        return None
    t_end = t_start + timedelta(hours=24)

    cmd = [
        "journalctl", "-u", "autobot.service",
        "--since", t_start.strftime("%Y-%m-%d %H:%M:%S"),
        "--until", t_end.strftime("%Y-%m-%d %H:%M:%S"),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception:
        return None

    rx_pnl = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d+:\d+:\d+),\d+ .*?\[SENTINEL\] outcome push ok: "
        r"CS\.D\.GBPUSD\.TODAY\.IP pnl=(-?\d+(?:\.\d+)?)"
    )
    rx_close = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d+:\d+:\d+),\d+ .*?Trade closed for "
        r"CS\.D\.GBPUSD\.TODAY\.IP \(pos_key=CS\.D\.GBPUSD\.TODAY\.IP\|([A-Z_0-9]+)\)"
    )

    events: List[dict] = []
    for line in proc.stdout.splitlines():
        m1 = rx_pnl.search(line)
        if m1:
            try:
                t = datetime.strptime(m1.group(1), "%Y-%m-%d %H:%M:%S")
                events.append({"kind": "pnl", "t": t, "pnl": float(m1.group(2))})
            except Exception:
                pass
        m2 = rx_close.search(line)
        if m2:
            try:
                t = datetime.strptime(m2.group(1), "%Y-%m-%d %H:%M:%S")
                events.append({"kind": "close", "t": t, "pos_key": m2.group(2)})
            except Exception:
                pass

    # For each close event matching strategy, find a paired pnl event ±5s
    for i, c in enumerate(events):
        if c["kind"] != "close":
            continue
        if c["pos_key"] != target_strategy and c["pos_key"] != "DEFAULT":
            continue
        for j in range(max(0, i - 5), min(len(events), i + 6)):
            d = events[j]
            if d["kind"] != "pnl":
                continue
            if abs((d["t"] - c["t"]).total_seconds()) <= 5.0:
                return {
                    "outcome_pips": d["pnl"],
                    "outcome_exit_reason": (
                        f"journal_recovered_pos_key={c['pos_key']}"
                    ),
                    "outcome_close_ts": c["t"].replace(
                        tzinfo=timezone.utc
                    ).isoformat(),
                }
    return None


# ─── main ────────────────────────────────────────────────────────────────
def backfill(forensic_path: Path = DEFAULT_FORENSIC_LOG,
             signal_log_path: Path = DEFAULT_SIGNAL_LOG,
             use_journal: bool = True,
             dry_run: bool = False) -> Dict[str, Any]:
    """Run one backfill pass. Returns summary dict."""
    forensic = _load_jsonl(forensic_path)
    signal_log = _load_jsonl(signal_log_path)

    family_records = _scan_family_name_records(forensic)
    if family_records:
        print(
            f"WARNING: {len(family_records)} forensic record(s) use a "
            f"family-name strategy instead of directional variant — these "
            f"will not match signal_log:",
            file=sys.stderr,
        )
        for fr in family_records[:10]:
            print(
                f"  {fr['fire_bar_ts']} {fr['strategy']} {fr['direction']}"
                f"  (expected one of {fr['expected_variants']})",
                file=sys.stderr,
            )
        if len(family_records) > 10:
            print(f"  ... and {len(family_records) - 10} more", file=sys.stderr)

    matched_sl = 0
    matched_journal = 0
    already = 0
    unmatched: List[dict] = []

    for rec in forensic:
        if rec.get("outcome_pips") is not None:
            already += 1
            continue

        sl = _match_signal_log(rec, signal_log)
        if sl is not None and sl.get("pnl_pips") is not None:
            rec["outcome_pips"] = float(sl["pnl_pips"])
            rec["outcome_exit_reason"] = (
                sl.get("close_reason") or sl.get("outcome")
            )
            rec["outcome_close_ts"] = sl.get("timestamp_close")
            rec["outcome"] = "matched_signal_log"
            matched_sl += 1
            continue

        if use_journal:
            jr = _journal_outcome(rec)
            if jr is not None:
                rec["outcome_pips"] = jr["outcome_pips"]
                rec["outcome_exit_reason"] = jr["outcome_exit_reason"]
                rec["outcome_close_ts"] = jr["outcome_close_ts"]
                rec["outcome"] = "matched_journal"
                matched_journal += 1
                continue

        unmatched.append({
            "fire_bar_ts": rec.get("fire_bar_ts"),
            "strategy": rec.get("strategy"),
            "direction": rec.get("direction"),
        })

    if not dry_run and (matched_sl > 0 or matched_journal > 0):
        _atomic_write_jsonl(forensic_path, forensic)

    return {
        "total": len(forensic),
        "already_filled": already,
        "matched_signal_log": matched_sl,
        "matched_journal": matched_journal,
        "unmatched_count": len(unmatched),
        "unmatched": unmatched,
        "family_name_records": family_records,
        "wrote_file": (not dry_run and (matched_sl > 0 or matched_journal > 0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill outcomes for forensic_fires.jsonl",
    )
    parser.add_argument("--forensic-log", default=str(DEFAULT_FORENSIC_LOG))
    parser.add_argument("--signal-log", default=str(DEFAULT_SIGNAL_LOG))
    parser.add_argument("--no-journal", action="store_true",
                        help="Skip journalctl fallback for dispatcher-gap fires")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute matches but do not write")
    args = parser.parse_args()

    result = backfill(
        forensic_path=Path(args.forensic_log),
        signal_log_path=Path(args.signal_log),
        use_journal=not args.no_journal,
        dry_run=args.dry_run,
    )

    print(f"forensic log:           {args.forensic_log}")
    print(f"signal log:             {args.signal_log}")
    print(f"dry run:                {args.dry_run}")
    print(f"journal fallback:       {not args.no_journal}")
    print()
    print(f"Total records:          {result['total']}")
    print(f"Already filled:         {result['already_filled']}")
    print(f"Matched via signal_log: {result['matched_signal_log']}")
    print(f"Matched via journal:    {result['matched_journal']}")
    print(f"Unmatched:              {result['unmatched_count']}")
    if result["unmatched"]:
        print()
        print("Unmatched records:")
        for u in result["unmatched"]:
            print(f"  {u['fire_bar_ts']:32s} {u['strategy']:28s} {u['direction']}")
    print()
    print(f"File rewritten:         {result['wrote_file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
