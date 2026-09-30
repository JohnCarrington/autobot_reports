"""eod_review_metrics.py — Stage 1: session metrics for the day.

Reads logs/signal_log.jsonl and produces two artefacts under
reports/eod/ for today's UTC date (or --date):

    reports/eod/metrics_<date>.md    (human-readable table)
    reports/eod/metrics_<date>.json  (machine-readable, consumed by
                                      eod_review_narrative.py)

Per-strategy rows: fills, wins, losses, net_pips, net_cash.
Plus: scale-out count, runner-exit breakdown by reason, and open
positions at review time. Cash math and TRADE_SIZE resolution are
delegated to daily_journal._fire_cash_gbp so the two reports stay
consistent (rows carry no per-row size — TRADE_SIZE env is the
authoritative multiplier, and the /2 correction on scaled trades is
handled inside _fire_cash_gbp).

No email, no IG calls, no writes outside reports/eod/ + logs/. Any
top-level exception logs to logs/eod_review.log and exits 0 — a broken
review must not look like a broken estate to systemd.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from collections import Counter, defaultdict
from datetime import date as _date_t, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

# Reuse daily_journal helpers so cash math and JSONL parsing stay
# byte-identical across the two reporting scripts.
import daily_journal as _dj  # noqa: E402

LOG_DIR = ROOT / "logs"
REPORTS_DIR = ROOT / "reports" / "eod"
SIGNAL_LOG = LOG_DIR / "signal_log.jsonl"
ERROR_LOG = LOG_DIR / "eod_review.log"

logger = logging.getLogger("eod_review_metrics")

# Runner-exit reason buckets. Anything not matching one of these keys is
# grouped under "other" for visibility.
RUNNER_REASON_BUCKETS = {
    "TRAIL_STOP": ("TRAIL_STOP",),
    "BE_STOP_POST_SCALEOUT": ("BE_STOP_POST_SCALEOUT",),
    "FLOOR_STOP_POST_SCALEOUT": ("FLOOR_STOP_POST_SCALEOUT",),
    "REGIME_MAX_HOLD": ("REGIME_MAX_HOLD",),
    "MANAGER_PROFIT_PROTECT": ("MANAGER_PROFIT_PROTECT",),
    "TREND_V3_FLATTEN_EXHAUSTION": ("TREND_V3_FLATTEN_EXHAUSTION",),
}


def _target_date(arg: Optional[str]) -> _date_t:
    if arg:
        return datetime.strptime(arg, "%Y-%m-%d").date()
    return datetime.now(timezone.utc).date()


def _pnl(row: Dict[str, Any]) -> float:
    """Realised pnl in pips. Prefer total (includes scale-out bank)."""
    val = row.get("total_pnl_pips")
    if val is None:
        val = row.get("pnl_pips")
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _has_close(row: Dict[str, Any]) -> bool:
    """A row is "closed" if it carries a close timestamp OR a close
    reason OR realised pnl. Rows fired but never filled or reconciled
    ('PHANTOM_NEVER_EXECUTED') still count as closed — they are
    resolved. Truly-open positions have no close_reason at all AND no
    pnl fields set."""
    if row.get("timestamp_close"):
        return True
    if row.get("close_reason"):
        return True
    if row.get("close_type"):
        return True
    if row.get("pnl_pips") is not None:
        return True
    if row.get("total_pnl_pips") is not None:
        return True
    return False


def _rows_for_day(day: _date_t) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in _dj._iter_jsonl(SIGNAL_LOG):
        ts = _dj._parse_ts(row.get("timestamp_open"))
        if ts is None or ts.date() != day:
            continue
        out.append(row)
    return out


def _runner_reason_bucket(reason: Optional[str]) -> str:
    if not reason:
        return "other"
    r = str(reason).strip()
    for bucket, needles in RUNNER_REASON_BUCKETS.items():
        for n in needles:
            if n in r:
                return bucket
    return "other"


def build_metrics(day: _date_t) -> Dict[str, Any]:
    rows = _rows_for_day(day)
    trade_size = _dj._trade_size()

    per_strategy: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "fills": 0,
            "wins": 0,
            "losses": 0,
            "scratches": 0,
            "net_pips": 0.0,
            "net_cash_gbp": 0.0,
        }
    )
    runner_reason_counts: Counter = Counter()
    scale_out_count = 0
    open_positions: List[Dict[str, Any]] = []

    for r in rows:
        strat = str(r.get("strategy") or "UNKNOWN")
        agg = per_strategy[strat]
        agg["fills"] += 1

        if _has_close(r):
            pnl = _pnl(r)
            cash = _dj._fire_cash_gbp(r, trade_size)
            cash = cash if cash is not None else 0.0
            agg["net_pips"] += pnl
            agg["net_cash_gbp"] += cash
            if pnl > 0:
                agg["wins"] += 1
            elif pnl < 0:
                agg["losses"] += 1
            else:
                agg["scratches"] += 1
            if bool(r.get("scaled_out")):
                scale_out_count += 1
                runner_reason_counts[_runner_reason_bucket(r.get("close_reason"))] += 1
        else:
            open_positions.append({
                "id": r.get("id"),
                "deal_id": r.get("deal_id"),
                "strategy": strat,
                "direction": r.get("direction"),
                "timestamp_open": r.get("timestamp_open"),
                "entry": r.get("entry"),
                "sl": r.get("sl"),
                "tp1": r.get("tp1"),
            })

    total_fills = sum(a["fills"] for a in per_strategy.values())
    total_wins = sum(a["wins"] for a in per_strategy.values())
    total_losses = sum(a["losses"] for a in per_strategy.values())
    total_scratches = sum(a["scratches"] for a in per_strategy.values())
    total_pips = round(sum(a["net_pips"] for a in per_strategy.values()), 2)
    total_cash = round(sum(a["net_cash_gbp"] for a in per_strategy.values()), 2)

    # Normalise per-strategy floats to 2dp for stable output.
    for s, agg in per_strategy.items():
        agg["net_pips"] = round(agg["net_pips"], 2)
        agg["net_cash_gbp"] = round(agg["net_cash_gbp"], 2)

    return {
        "date": day.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "trade_size_used": trade_size,
        "totals": {
            "fills": total_fills,
            "wins": total_wins,
            "losses": total_losses,
            "scratches": total_scratches,
            "net_pips": total_pips,
            "net_cash_gbp": total_cash,
        },
        "per_strategy": dict(per_strategy),
        "scale_out_count": scale_out_count,
        "runner_exit_reasons": dict(runner_reason_counts),
        "open_positions": open_positions,
        "rows_read": len(rows),
    }


def render_markdown(m: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# EOD Metrics — {m['date']}")
    lines.append("")
    lines.append(f"_Generated {m['generated_at_utc']} — TRADE_SIZE used: {m['trade_size_used']} £/pt_")
    lines.append("")

    if m["totals"]["fills"] == 0:
        lines.append("**No fills on this date.**")
        lines.append("")
        lines.append("Rows read from signal_log for this date: 0. Nothing to summarise.")
        return "\n".join(lines) + "\n"

    # Per-strategy table.
    lines.append("## Per-strategy")
    lines.append("")
    lines.append("| Strategy | Fills | W | L | Scratch | Net pips | Net £ |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for strat in sorted(m["per_strategy"].keys()):
        a = m["per_strategy"][strat]
        lines.append(
            f"| {strat} | {a['fills']} | {a['wins']} | {a['losses']} | "
            f"{a['scratches']} | {a['net_pips']:+.2f} | £{a['net_cash_gbp']:+.2f} |"
        )
    t = m["totals"]
    lines.append(
        f"| **TOTAL** | **{t['fills']}** | **{t['wins']}** | **{t['losses']}** | "
        f"**{t['scratches']}** | **{t['net_pips']:+.2f}** | **£{t['net_cash_gbp']:+.2f}** |"
    )
    lines.append("")

    # Scale-outs + runner exit reasons.
    lines.append("## Runner activity")
    lines.append("")
    lines.append(f"- Scale-outs: **{m['scale_out_count']}**")
    if m["runner_exit_reasons"]:
        lines.append("- Runner exit reasons:")
        for reason in sorted(m["runner_exit_reasons"].keys()):
            lines.append(f"    - {reason}: {m['runner_exit_reasons'][reason]}")
    else:
        lines.append("- Runner exit reasons: (none)")
    lines.append("")

    # Open positions at review time.
    lines.append("## Open positions at review")
    lines.append("")
    if not m["open_positions"]:
        lines.append("(none)")
    else:
        lines.append("| Time (UTC) | Strategy | Dir | Entry | SL | TP1 | Deal |")
        lines.append("|---|---|---|---:|---:|---:|---|")
        for p in m["open_positions"]:
            lines.append(
                f"| {p.get('timestamp_open','?')} | {p.get('strategy','?')} | "
                f"{p.get('direction','?')} | {p.get('entry','')} | {p.get('sl','')} | "
                f"{p.get('tp1','')} | {p.get('deal_id','')} |"
            )
    lines.append("")

    return "\n".join(lines) + "\n"


def write_outputs(m: Dict[str, Any]) -> Dict[str, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date = m["date"]
    md_path = REPORTS_DIR / f"metrics_{date}.md"
    json_path = REPORTS_DIR / f"metrics_{date}.json"
    md_path.write_text(render_markdown(m), encoding="utf-8")
    json_path.write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")
    return {"md": md_path, "json": json_path}


def _log_error(exc: BaseException) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                f"{datetime.now(timezone.utc).isoformat()} eod_review_metrics: "
                f"{type(exc).__name__}: {exc}\n"
            )
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        # Absolutely nothing we can do — the error-log write itself failed.
        pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="EOD metrics for the day")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (defaults to UTC today)")
    args = ap.parse_args(argv)

    try:
        day = _target_date(args.date)
        m = build_metrics(day)
        paths = write_outputs(m)
        print(
            f"eod_review_metrics: {day.isoformat()} — {m['totals']['fills']} fills, "
            f"net {m['totals']['net_pips']:+.2f}p / £{m['totals']['net_cash_gbp']:+.2f} "
            f"→ {paths['md']}"
        )
        return 0
    except Exception as ex:  # noqa: BLE001
        _log_error(ex)
        print(f"eod_review_metrics: FAILED ({type(ex).__name__}: {ex}) — "
              f"see {ERROR_LOG}", file=sys.stderr)
        # Exit 0 by design — this is a reporting artefact, not the
        # trading loop. A dead review must not colour systemd red.
        return 0


if __name__ == "__main__":
    sys.exit(main())
