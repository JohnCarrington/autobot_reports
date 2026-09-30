#!/usr/bin/env python3
"""execution_latency_analysis.py — distribution / breakdown of fire and exit latency.

Reads signal_log.jsonl (or signal_log_backfilled.jsonl via --in) and
prints a markdown report to stdout summarising:

  - Distribution of each delta field (count, mean, median, p90, p99, max)
  - Per-strategy breakdown
  - Per-pair breakdown
  - Time-of-day breakdown (UTC hour buckets)
  - Pre-refactor (ls_async_dispatch=0) vs post-refactor (=1) split

Manual invocation only — no scheduler, no Telegram, no log persistence.

Caller redirects stdout to save:
    python3 scripts/execution_latency_analysis.py > /tmp/latency_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_IN = Path(os.getenv("SIGNAL_LOG_PATH",
                            "/opt/tradingbot/logs/signal_log.jsonl"))

FIRE_DELTA_FIELDS = (
    "decision_to_dispatch_ms",
    "dispatch_to_ig_request_ms",
    "ig_request_to_ack_ms",
    "ack_to_confirm_ms",
    "total_decision_to_confirm_ms",
)

EXIT_DELTA_FIELDS = (
    "trigger_to_dispatch_ms",
    "dispatch_to_confirm_ms",
    "total_trigger_to_confirm_ms",
)


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _percentile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    n = len(sorted_vals)
    k = max(0, min(n - 1, int(round((q / 100.0) * (n - 1)))))
    return sorted_vals[k]


def _summarise(values: Iterable[Any]) -> Dict[str, Any]:
    nums: List[float] = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN
            continue
        nums.append(f)

    if not nums:
        return {"count": 0, "mean": None, "median": None,
                "p90": None, "p99": None, "max": None}

    nums_sorted = sorted(nums)
    return {
        "count": len(nums),
        "mean": round(statistics.fmean(nums), 1),
        "median": round(statistics.median(nums_sorted), 1),
        "p90": round(_percentile(nums_sorted, 90.0), 1),
        "p99": round(_percentile(nums_sorted, 99.0), 1),
        "max": round(max(nums_sorted), 1),
    }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                out.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return out


def _open_hour_utc(rec: Dict[str, Any]) -> Optional[int]:
    ts = rec.get("timestamp_open")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).hour
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _render_dist_table(label: str, fields: Tuple[str, ...],
                        records: List[Dict[str, Any]]) -> str:
    lines = [
        f"### {label}",
        "",
        "| field | count | mean | median | p90 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in fields:
        s = _summarise(r.get(f) for r in records)
        lines.append(
            f"| `{f}` | {s['count']} | {s['mean']} | {s['median']} | "
            f"{s['p90']} | {s['p99']} | {s['max']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_groupby_total(label: str, group_key: str, total_field: str,
                           records: List[Dict[str, Any]]) -> str:
    groups: Dict[str, List[Any]] = defaultdict(list)
    for r in records:
        k = str(r.get(group_key) or "<missing>")
        groups[k].append(r.get(total_field))
    if not groups:
        return f"### {label}\n\n(no data)\n"

    lines = [
        f"### {label} — total `{total_field}` by `{group_key}`",
        "",
        f"| {group_key} | count | mean | median | p90 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for k in sorted(groups.keys()):
        s = _summarise(groups[k])
        lines.append(
            f"| {k} | {s['count']} | {s['mean']} | {s['median']} | "
            f"{s['p90']} | {s['p99']} | {s['max']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_hour_breakdown(total_field: str,
                            records: List[Dict[str, Any]]) -> str:
    buckets: Dict[int, List[Any]] = defaultdict(list)
    for r in records:
        h = _open_hour_utc(r)
        if h is None:
            continue
        buckets[h].append(r.get(total_field))
    if not buckets:
        return f"### Time-of-day (UTC hour) — `{total_field}`\n\n(no data)\n"

    lines = [
        f"### Time-of-day (UTC hour) — `{total_field}`",
        "",
        "| hour_utc | count | mean | median | p90 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for h in sorted(buckets.keys()):
        s = _summarise(buckets[h])
        lines.append(
            f"| {h:02d} | {s['count']} | {s['mean']} | {s['median']} | "
            f"{s['p90']} | {s['p99']} | {s['max']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_pre_post_split(records: List[Dict[str, Any]]) -> str:
    pre = [r for r in records if int(r.get("ls_async_dispatch") or 0) == 0]
    post = [r for r in records if int(r.get("ls_async_dispatch") or 0) == 1]

    if not post:
        return (
            "### Pre/Post-refactor split\n\n"
            f"Only pre-refactor records present (n={len(pre)}); skipping comparison.\n\n"
            "Re-run after `LS_ASYNC_DISPATCH=1` has been live for at least 1 trading day "
            "to populate post-refactor distributions.\n"
        )
    if not pre:
        return (
            "### Pre/Post-refactor split\n\n"
            f"Only post-refactor records present (n={len(post)}); skipping comparison.\n"
        )

    lines = [
        "### Pre/Post-refactor split — `total_decision_to_confirm_ms`",
        "",
        "| mode | count | mean | median | p90 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, rs in (("pre (ls_async=0)", pre), ("post (ls_async=1)", post)):
        s = _summarise(r.get("total_decision_to_confirm_ms") for r in rs)
        lines.append(
            f"| {label} | {s['count']} | {s['mean']} | {s['median']} | "
            f"{s['p90']} | {s['p99']} | {s['max']} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def render_report(records: List[Dict[str, Any]], in_path: Path) -> str:
    parts: List[str] = []
    parts.append(f"# Execution Latency Analysis\n")
    parts.append(f"**Source:** `{in_path}`  ")
    parts.append(f"**Records:** {len(records)}  ")
    parts.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n")

    # Determine instrumented vs un-instrumented split.
    instr = [r for r in records if r.get("t_dispatch_epoch_ms") is not None]
    backfilled = [r for r in records if r.get("t_ig_confirm_epoch_ms") is not None
                  and r.get("t_dispatch_epoch_ms") is None]
    raw = [r for r in records if r.get("t_ig_confirm_epoch_ms") is None]

    parts.append(
        f"- **Natively instrumented:** {len(instr)}  \n"
        f"- **Backfilled (timestamp_open → t_ig_confirm only):** {len(backfilled)}  \n"
        f"- **Pre-instrumentation, no backfill:** {len(raw)}\n"
    )

    if not instr and not backfilled:
        parts.append(
            "\n> No latency data available — instrumentation hasn't run "
            "yet and backfill hasn't been applied.  Re-run after at least "
            "one trading day with the new code, or run "
            "`scripts/backfill_execution_latency.py` first.\n"
        )
        return "\n".join(parts)

    if not instr:
        parts.append(
            "\n> Only backfilled data is present — derived deltas will all "
            "be null (only `t_ig_confirm_epoch_ms` is recoverable from "
            "pre-instrumentation logs).  Re-run once natively-instrumented "
            "data accumulates.\n"
        )

    parts.append("\n## Fire-path deltas\n")
    parts.append(_render_dist_table("Distribution", FIRE_DELTA_FIELDS, records))
    parts.append(_render_groupby_total(
        "Per-strategy", "strategy", "total_decision_to_confirm_ms", records,
    ))
    parts.append(_render_groupby_total(
        "Per-pair", "pair", "total_decision_to_confirm_ms", records,
    ))
    parts.append(_render_hour_breakdown(
        "total_decision_to_confirm_ms", records,
    ))
    parts.append(_render_pre_post_split(records))

    parts.append("\n## Exit-path deltas\n")
    parts.append(_render_dist_table("Distribution", EXIT_DELTA_FIELDS, records))
    parts.append(_render_groupby_total(
        "Per-strategy", "strategy", "total_trigger_to_confirm_ms", records,
    ))
    parts.append(_render_groupby_total(
        "Per-pair", "pair", "total_trigger_to_confirm_ms", records,
    ))

    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", type=Path, default=DEFAULT_IN,
                    help="path to signal_log.jsonl or signal_log_backfilled.jsonl")
    args = ap.parse_args()

    records = load_records(args.in_path)
    out = render_report(records, args.in_path)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
