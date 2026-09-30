#!/usr/bin/env python3
"""
Rewrite tp1_hit / tp2_hit in /opt/tradingbot/data/briefing_outcomes.jsonl
using the direction-aware semantics introduced alongside this script:

  A target counts as HIT only when:
    (a) session_high/low actually reached it, AND
    (b) the target is on the correct side of entry for the plan bias.

For rows lacking plan_bias, preserve the legacy "price reached level"
semantics but within the session range (low ≤ tp ≤ high).

All other fields in each row are preserved untouched. Creates a
timestamped backup before rewriting.

Usage: scripts/rebuild_tp_hits.py
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTCOMES = Path("/opt/tradingbot/data/briefing_outcomes.jsonl")


def _entry_mid(zone) -> float | None:
    if not zone:
        return None
    try:
        return (float(zone[0]) + float(zone[-1])) / 2.0
    except Exception:
        return None


def _correct_side(tp, entry_price, plan_bias) -> bool:
    if entry_price is None or plan_bias not in ("LONG", "SHORT"):
        return True
    try:
        tp_f = float(tp)
    except Exception:
        return False
    if plan_bias == "LONG":
        return tp_f > entry_price
    return tp_f < entry_price


def _compute_hits(rec: dict) -> tuple[bool, bool]:
    targets = rec.get("plan_targets") or []
    plan_bias = str(rec.get("plan_bias") or "").upper()
    session_high = rec.get("session_high")
    session_low = rec.get("session_low")
    if session_high is None or session_low is None or not targets:
        return False, False

    entry_price = _entry_mid(rec.get("plan_entry_zone"))

    tp1 = tp2 = False
    if plan_bias == "SHORT":
        if len(targets) >= 1 and session_low <= targets[0] and _correct_side(targets[0], entry_price, plan_bias):
            tp1 = True
        if len(targets) >= 2 and session_low <= targets[1] and _correct_side(targets[1], entry_price, plan_bias):
            tp2 = True
    elif plan_bias == "LONG":
        if len(targets) >= 1 and session_high >= targets[0] and _correct_side(targets[0], entry_price, plan_bias):
            tp1 = True
        if len(targets) >= 2 and session_high >= targets[1] and _correct_side(targets[1], entry_price, plan_bias):
            tp2 = True
    else:
        # NEUTRAL / unknown bias — legacy "price traded through level" check.
        if len(targets) >= 1 and session_low <= targets[0] <= session_high:
            tp1 = True
        if len(targets) >= 2 and session_low <= targets[1] <= session_high:
            tp2 = True
    return tp1, tp2


def main() -> int:
    if not OUTCOMES.exists():
        print(f"{OUTCOMES} not found", file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = OUTCOMES.with_suffix(f".jsonl.bak.{ts}")
    shutil.copy2(OUTCOMES, backup)
    print(f"backup → {backup}")

    lines_in = OUTCOMES.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    changed = tp1_flipped = tp2_flipped = scanned = 0
    for line in lines_in:
        s = line.strip()
        if not s:
            out.append(s)
            continue
        try:
            rec = json.loads(s)
        except Exception:
            out.append(s)
            continue
        scanned += 1

        new_tp1, new_tp2 = _compute_hits(rec)
        old_tp1 = rec.get("tp1_hit")
        old_tp2 = rec.get("tp2_hit")
        if new_tp1 != old_tp1:
            tp1_flipped += 1
        if new_tp2 != old_tp2:
            tp2_flipped += 1
        if new_tp1 != old_tp1 or new_tp2 != old_tp2:
            changed += 1
        rec["tp1_hit"] = new_tp1
        rec["tp2_hit"] = new_tp2
        out.append(json.dumps(rec, default=str))

    OUTCOMES.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"scanned:       {scanned}")
    print(f"rows changed:  {changed}")
    print(f"tp1 flipped:   {tp1_flipped}")
    print(f"tp2 flipped:   {tp2_flipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
