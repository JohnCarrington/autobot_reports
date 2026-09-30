"""eod_review_narrative.py — Stage 3: plain-prose EOD review + email.

Reads:
  * reports/eod/metrics_<date>.json (best-effort — if absent, degrades)
  * logs/signal_log.jsonl (today's rows)
  * logs/daily_journal.jsonl (best-effort — today's entry)
  * a handful of gate/shadow jsonl logs for today's counts

Writes:
  * reports/eod/review_<date>.md

Then emails the markdown via SendGrid using the credentials proven at
runtime by daily_journal.py (EMAIL_FROM / EMAIL_TO / SENDGRID_API_KEY;
JOURNAL_EMAIL_TO override honoured for consistency). Email is gated by
EOD_REVIEW_EMAIL_ENABLED (default "1" — the operator confirmed live
send on 2026-07-27; the flag can be set to "0" to silence).

End-to-end try/except → logs/eod_review.log, exits 0. Any failure
downstream of the initial file writes (metric read, gate counts, send)
degrades gracefully — a partial review beats silence.
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
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

# Reuse daily_journal helpers: JSONL parsing, timestamp parsing, and
# the SendGrid config accessors. The actual POST is inlined below (the
# journal's send is subject/payload-locked to the journal, so we mirror
# its shape rather than trying to reuse the whole function).
import daily_journal as _dj  # noqa: E402

LOG_DIR = ROOT / "logs"
REPORTS_DIR = ROOT / "reports" / "eod"
SIGNAL_LOG = LOG_DIR / "signal_log.jsonl"
JOURNAL_LOG = LOG_DIR / "daily_journal.jsonl"
ERROR_LOG = LOG_DIR / "eod_review.log"

logger = logging.getLogger("eod_review_narrative")

SENDGRID_URL = _dj.SENDGRID_URL

# Log files scanned for gate/shadow activity. Each entry is
# (label_for_report, filename_under_logs/, ts_field_name).
# Missing files degrade to "0" silently — the corpus is heterogeneous.
GATE_LOGS: List[Tuple[str, str, str]] = [
    ("SB-ENTRY (paths logged)", "sb_entry_path.jsonl", "ts_utc"),
    ("BB block shadow", "bb_block_shadow.jsonl", "ts"),
    ("EMA-PB momentum shadow", "ema_pullback_momentum_shadow.jsonl", "ts_utc"),
    ("BB-BOUNCE cascade shadow", "bb_bounce_l_cascade_shadow.jsonl", "ts_utc"),
    ("Direction router shadow", "direction_router_shadow.jsonl", "ts_utc"),
    ("Regime shadow", "regime_shadow.jsonl", "ts"),
    ("Trend guard shadow", "trend_guard_shadow.jsonl", "ts_utc"),
    ("Range gate", "range_gate.jsonl", "ts_utc"),
    ("SB grind shadow", "structure_break_grind_shadow.jsonl", "ts_utc"),
    ("Cross-bias gate", "cross_bias_gate.jsonl", "ts_utc"),
]

# Strategies that (by operator convention) should fire ≥3/day. Falling
# below flags a "silent-strategy" anomaly in the narrative. Kept small
# and hand-picked — a heuristic, not authoritative.
EXPECTED_DAILY_STRATEGIES = {
    "GBPUSD_BB_BOUNCE_L",
    "GBPUSD_BB_BOUNCE_S",
    "BRIEFING_EXECUTION",
}
EXPECTED_MIN_FIRES = 3


def _target_date(arg: Optional[str]) -> _date_t:
    if arg:
        return datetime.strptime(arg, "%Y-%m-%d").date()
    return datetime.now(timezone.utc).date()


def _read_metrics(day: _date_t) -> Optional[Dict[str, Any]]:
    path = REPORTS_DIR / f"metrics_{day.isoformat()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _rows_for_day(day: _date_t) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in _dj._iter_jsonl(SIGNAL_LOG):
        ts = _dj._parse_ts(row.get("timestamp_open"))
        if ts is None or ts.date() != day:
            continue
        out.append(row)
    return out


def _read_journal_entry(day: _date_t) -> Optional[Dict[str, Any]]:
    if not JOURNAL_LOG.exists():
        return None
    target = day.isoformat()
    for row in _dj._iter_jsonl(JOURNAL_LOG):
        if str(row.get("date")) == target:
            return row
    return None


def _count_events_for_day(
    path: Path, day: _date_t, ts_field: str
) -> int:
    """Count rows in a JSONL log whose ts_field matches the given date
    (UTC). Missing file → 0. Malformed lines are skipped."""
    if not path.exists():
        return 0
    day_iso = day.isoformat()
    count = 0
    for row in _dj._iter_jsonl(path):
        raw = row.get(ts_field)
        if raw is None:
            # Some logs use "ts_utc" instead of "ts" or vice-versa;
            # try the other common one.
            raw = row.get("ts") if ts_field != "ts" else row.get("ts_utc")
        if raw is None:
            continue
        # Cheap prefix match — every ts we emit is ISO-8601 with a
        # leading YYYY-MM-DD. Avoids the per-row datetime parse cost.
        if str(raw).startswith(day_iso):
            count += 1
    return count


def _pnl(row: Dict[str, Any]) -> float:
    val = row.get("total_pnl_pips")
    if val is None:
        val = row.get("pnl_pips")
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _classify_close(reason: Optional[str]) -> str:
    if not reason:
        return "unknown"
    r = str(reason).lower()
    if "sl" in r and "hit" in r:
        return "SL hit"
    if "tp" in r and "hit" in r:
        return "TP hit"
    if "trail" in r:
        return "trailed"
    if "be_stop" in r or "breakeven" in r:
        return "BE stop"
    if "regime_max_hold" in r:
        return "REGIME_MAX_HOLD"
    if "manual" in r or "manager_profit_protect" in r:
        return "closed manually / by manager"
    if "phantom_never_executed" in r:
        return "phantom (never filled)"
    if "reconcile" in r:
        return "IG reconcile"
    if "pre_news" in r:
        return "pre-news close"
    return reason


def _build_narrative(
    day: _date_t,
    metrics: Optional[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    journal: Optional[Dict[str, Any]],
    gate_counts: Dict[str, int],
) -> str:
    lines: List[str] = []
    lines.append(f"# AutoBot EOD Review — {day.isoformat()}")
    lines.append("")
    lines.append(
        f"_Generated {datetime.now(timezone.utc).isoformat()} — "
        f"Stage 3 (narrative) reading Stage 1 metrics + signal_log._"
    )
    lines.append("")

    # ------------------------------------------------------------------
    # Metrics summary block (or "unavailable")
    # ------------------------------------------------------------------
    lines.append("## Session summary")
    lines.append("")
    if metrics is None:
        lines.append(
            "**Metrics unavailable** — `reports/eod/metrics_"
            f"{day.isoformat()}.json` was not present at review time. "
            "Stage 1 either failed or ran with no data. Narrative below "
            "is built from signal_log alone."
        )
    else:
        t = metrics.get("totals", {})
        lines.append(
            f"- **{t.get('fills', 0)} fills** — "
            f"{t.get('wins', 0)} wins / {t.get('losses', 0)} losses "
            f"(scratches: {t.get('scratches', 0)})."
        )
        lines.append(
            f"- **Net: {t.get('net_pips', 0.0):+.2f} pips / "
            f"£{t.get('net_cash_gbp', 0.0):+.2f}** "
            f"(TRADE_SIZE {metrics.get('trade_size_used')} £/pt)."
        )
        lines.append(
            f"- Scale-outs: {metrics.get('scale_out_count', 0)}. "
            f"Open at review: {len(metrics.get('open_positions', []))}."
        )
    lines.append("")

    # ------------------------------------------------------------------
    # Per-trade narrative
    # ------------------------------------------------------------------
    lines.append("## What traded")
    lines.append("")
    if not rows:
        lines.append("No fires today.")
    else:
        # Sort by open timestamp.
        rows_sorted = sorted(
            rows, key=lambda r: r.get("timestamp_open") or ""
        )
        for r in rows_sorted:
            strat = r.get("strategy") or "UNKNOWN"
            direction = r.get("direction") or "?"
            open_ts = r.get("timestamp_open") or "?"
            pnl = _pnl(r)
            reason = _classify_close(r.get("close_reason"))
            entry = r.get("entry")
            close = r.get("close_price")
            outcome = "OPEN"
            if r.get("timestamp_close") or r.get("close_reason") or \
                    r.get("pnl_pips") is not None:
                outcome = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "SCRATCH")
            scaled = " (scaled out)" if r.get("scaled_out") else ""
            lines.append(
                f"- **{open_ts}** — `{strat}` {direction} "
                f"entry {entry} → {close if close is not None else '(open)'}: "
                f"**{outcome}** {pnl:+.2f}p — {reason}{scaled}"
            )
    lines.append("")

    # ------------------------------------------------------------------
    # Gate / shadow activity
    # ------------------------------------------------------------------
    lines.append("## Gate / shadow activity")
    lines.append("")
    any_nonzero = any(v > 0 for v in gate_counts.values())
    if not any_nonzero:
        lines.append("_All monitored gates recorded 0 events for the day._")
    else:
        lines.append("| Category | Events today |")
        lines.append("|---|---:|")
        for label, count in gate_counts.items():
            lines.append(f"| {label} | {count} |")
    lines.append("")

    # ------------------------------------------------------------------
    # Anomalies
    # ------------------------------------------------------------------
    anomalies: List[str] = []
    strat_fires: Counter = Counter(
        r.get("strategy") for r in rows if r.get("strategy")
    )
    for s in sorted(EXPECTED_DAILY_STRATEGIES):
        n = strat_fires.get(s, 0)
        if n < EXPECTED_MIN_FIRES:
            anomalies.append(
                f"Strategy `{s}` fired only {n} time(s); expected "
                f">= {EXPECTED_MIN_FIRES}/day. Investigate silent-strategy risk."
            )

    # Cash / pips divergence heuristic: with TRADE_SIZE=2 and no
    # scale-outs, cash should be ~2× pips. If total_pips ≠ 0 and
    # cash/pips ratio deviates far from expected (>50% off after
    # normalising by trade_size), flag for review.
    if metrics is not None:
        t = metrics.get("totals", {})
        pips = t.get("net_pips") or 0.0
        cash = t.get("net_cash_gbp") or 0.0
        ts = metrics.get("trade_size_used") or 0.0
        if abs(pips) > 0.5 and ts > 0:
            # Rough expected cash = pips × trade_size (per-trade halving
            # for scale-outs is a within-fire effect that already
            # produces a smaller ratio; we only flag when it's absurd).
            expected = pips * ts
            if expected != 0 and abs(cash / expected) < 0.4:
                anomalies.append(
                    f"Cash / pips divergence: {cash:+.2f} £ vs "
                    f"{pips:+.2f} p × TRADE_SIZE {ts}. Ratio "
                    f"{cash / expected:.2f}. Check scale-out attribution."
                )

    lines.append("## Anomalies")
    lines.append("")
    if anomalies:
        for a in anomalies:
            lines.append(f"- {a}")
    else:
        lines.append("_None flagged._")
    lines.append("")

    # ------------------------------------------------------------------
    # Journal cross-link
    # ------------------------------------------------------------------
    lines.append("## Journal cross-link")
    lines.append("")
    if journal is None:
        lines.append(
            "_No daily_journal entry found for this date "
            "(logs/daily_journal.jsonl) — journal may not have run yet._"
        )
    else:
        flags = journal.get("flags") or []
        sugg = journal.get("suggestions") or []
        lines.append(
            f"Daily journal recorded **{len(flags)} flag(s)** and "
            f"**{len(sugg)} suggestion(s)** for {day.isoformat()}."
        )
        if flags:
            lines.append("")
            lines.append("Flags:")
            for f in flags[:10]:
                if isinstance(f, dict):
                    lines.append(f"- {f.get('title') or f.get('name') or str(f)[:120]}")
                else:
                    lines.append(f"- {str(f)[:200]}")
    lines.append("")

    return "\n".join(lines) + "\n"


def _send_review_email(subject: str, body_md: str) -> Tuple[bool, str]:
    """Send the review markdown via SendGrid.

    Mirrors daily_journal.send_journal_email's shape: same URL, same
    payload keys, same credential accessors. Returns (ok, message).
    Never raises — all failures reported via the message string.
    """
    ok, missing = _dj._mail_configured()
    if not ok:
        return (False, f"not configured (missing: {missing})")

    try:
        import requests  # already a project dep
    except Exception as ex:  # noqa: BLE001
        return (False, f"requests import failed: {ex}")

    from_addr = _dj._mail_cfg("EMAIL_FROM")
    to_raw = _dj._mail_cfg("JOURNAL_EMAIL_TO") or _dj._mail_cfg("EMAIL_TO")
    to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]
    api_key = _dj._mail_cfg("SENDGRID_API_KEY")

    payload = {
        "personalizations": [{"to": [{"email": a} for a in to_addrs]}],
        "from": {"email": from_addr},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body_md}],
    }
    try:
        resp = requests.post(
            SENDGRID_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
    except Exception as ex:  # noqa: BLE001
        return (False, f"request failed: {ex}")

    body_snip = (resp.text or "")[:200]
    if 200 <= resp.status_code < 300:
        msg_id = resp.headers.get("X-Message-Id", "n/a")
        return (True, f"status={resp.status_code} sendgrid_msg_id={msg_id} to={to_addrs}")
    return (False, f"SendGrid {resp.status_code}: {body_snip}")


def _email_enabled() -> bool:
    """Gate flag. Default '1' — operator confirmed live send on
    2026-07-27; flip to '0' in .env to silence."""
    raw = os.getenv("EOD_REVIEW_EMAIL_ENABLED", "1")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _log_error(exc: BaseException) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                f"{datetime.now(timezone.utc).isoformat()} eod_review_narrative: "
                f"{type(exc).__name__}: {exc}\n"
            )
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="EOD narrative + email")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (defaults to UTC today)")
    ap.add_argument("--no-email", action="store_true",
                    help="Skip the email send (write MD only). Overrides "
                         "EOD_REVIEW_EMAIL_ENABLED for this run.")
    args = ap.parse_args(argv)

    try:
        day = _target_date(args.date)

        # --- read inputs (each guarded so one missing input doesn't
        #     torpedo the whole review) ---
        try:
            metrics = _read_metrics(day)
        except Exception as ex:  # noqa: BLE001
            _log_error(ex)
            metrics = None
        try:
            rows = _rows_for_day(day)
        except Exception as ex:  # noqa: BLE001
            _log_error(ex)
            rows = []
        try:
            journal = _read_journal_entry(day)
        except Exception as ex:  # noqa: BLE001
            _log_error(ex)
            journal = None

        gate_counts: Dict[str, int] = {}
        for label, fname, ts_field in GATE_LOGS:
            try:
                gate_counts[label] = _count_events_for_day(
                    LOG_DIR / fname, day, ts_field
                )
            except Exception as ex:  # noqa: BLE001
                _log_error(ex)
                gate_counts[label] = 0

        md = _build_narrative(day, metrics, rows, journal, gate_counts)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        md_path = REPORTS_DIR / f"review_{day.isoformat()}.md"
        md_path.write_text(md, encoding="utf-8")

        # --- email ---
        subject = f"AutoBot EOD Review — {day.isoformat()}"
        if args.no_email:
            print(f"eod_review_narrative: wrote {md_path} — email skipped (--no-email)")
            return 0
        if not _email_enabled():
            print(f"eod_review_narrative: wrote {md_path} — email gated "
                  f"(EOD_REVIEW_EMAIL_ENABLED != 1)")
            return 0
        ok, msg = _send_review_email(subject, md)
        if ok:
            print(f"eod_review_narrative: wrote {md_path} — email {msg}")
        else:
            print(f"eod_review_narrative: wrote {md_path} — email FAILED: {msg}",
                  file=sys.stderr)
        return 0
    except Exception as ex:  # noqa: BLE001
        _log_error(ex)
        print(f"eod_review_narrative: FAILED ({type(ex).__name__}: {ex}) — "
              f"see {ERROR_LOG}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
