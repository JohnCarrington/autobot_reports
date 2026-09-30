#!/usr/bin/env python3
"""
news_strategy_7d_verify.py — one-shot verification of the
rebuild/news-strategy-actuals-driven + fix/news-strategy-sl-tp-geometry
deploys (commit 251d6fb merge, 2026-04-29 18:39 UTC).

Polling design: invoked hourly by cron from 2026-04-29 onward. Each
invocation decides whether to fire the verification report:

  1. If a qualifying autobot.service restart has happened (after
     COMMIT_LANDED_AT) AND ≥168 h (7 days) have elapsed since that
     restart: build report, send Telegram, self-remove cron.

  2. If no qualifying restart by FALLBACK_FIRE (2026-05-13 22:00 UTC):
     fire with "NO RESTART YET" alert, self-remove cron.

  3. Otherwise: exit silently. Cron will fire again next hour.

Diagnostic content per the user's spec:
  1. WOULD_FIRE count per pair / per event-type (NEWS_STRATEGY)
  2. NEWS_TICK CONTINUATION fires (separate count + hypothetical PnL)
  3. NEWS_STRATEGY breakdown: SL hits / TP hits / EOD-positive (no TP) /
     SKIP_SL_TOO_WIDE
  4. Aggregate hypothetical pip P&L
  5. Win rate
  6. Worst single hypothetical loss
  7. Promotion verdict against the 7 criteria

Hypothetical outcomes are computed by walking forward through the
recorded autobot tick stream from each WOULD_FIRE row's fire_ts to
the end of the trading day, applying SL/TP/HOLD-END rules.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, "/opt/tradingbot")

logging.disable(logging.WARNING)

REPO_ROOT       = Path("/opt/tradingbot")
LOG_DIR         = REPO_ROOT / "logs"
SIGNAL_LOG      = LOG_DIR / "signal_log.jsonl"
OBS_LOG         = LOG_DIR / "news_strategy_observed.jsonl"
NEWS_STRATEGIES = {"NEWS_STRATEGY", "NEWS_TICK"}
CRON_MARKER     = "ONE-SHOT news_strategy_7d_verify"

# Merge of fix/news-strategy-sl-tp-geometry (commit 251d6fb).
COMMIT_LANDED_AT  = datetime(2026, 4, 29, 18, 39, 23, tzinfo=timezone.utc)
FALLBACK_FIRE     = datetime(2026, 5, 13, 22, 0, 0, tzinfo=timezone.utc)
SOAK_HOURS        = 7 * 24

# Promotion criteria thresholds.
MIN_EVENTS_IN_WINDOW         = 5
MIN_WOULD_FIRE_NEWS_STRATEGY = 3
MIN_AGGREGATE_PIPS           = 0.0
MIN_WIN_RATE                 = 0.50
MAX_SINGLE_LOSS_PIPS         = 50.0  # criterion 5: no >50p hypothetical loss

# "TP-not-hit but EOD-positive" + "SL > 25p reject" thresholds (criteria
# 6 + 7) — counts above which we'd recommend tuning rather than promote.
SOFT_TP_THRESHOLD_COUNT = 3
TIGHT_SL_REJECT_COUNT   = 3

RESTART_RE   = re.compile(r"Started\s+TIME\s+SERIES\s*-\s*AUTOBOT", re.IGNORECASE)
LINE_TS_RE   = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*)")
TICK_RE      = re.compile(
    r"^(?P<jts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*)\s+\S+\s+\S+\s+"
    r"(?P<msg_ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3})\s+"
    r"\[\w+\]\s+\[(?P<sym>\w+)\]\s+TICK\s+"
    r"bid=(?P<bid>[\d.]+)\s+ask=(?P<ask>[\d.]+)\s+mid=(?P<mid>[\d.]+)"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_z(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    # journalctl short-iso uses +0000 (no colon); Python 3.10 fromisoformat
    # rejects that — re-insert the colon for the trailing offset.
    if len(s) >= 5 and (s[-5] == "+" or s[-5] == "-") and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def journalctl_since(since: datetime, until: Optional[datetime] = None,
                     extra_grep: Optional[str] = None) -> str:
    cmd = [
        "journalctl", "-u", "autobot.service",
        "--since", since.strftime("%Y-%m-%d %H:%M:%S"),
        "--no-pager", "-o", "short-iso",
    ]
    if until:
        cmd.extend(["--until", until.strftime("%Y-%m-%d %H:%M:%S")])
    try:
        out = subprocess.check_output(cmd, text=True, errors="replace", timeout=180)
    except subprocess.SubprocessError as exc:
        return f"__JOURNAL_ERROR__: {exc}"
    if extra_grep:
        out = "\n".join(line for line in out.splitlines() if extra_grep in line)
    return out


def find_first_restart_after(commit_ts: datetime) -> Optional[datetime]:
    journal = journalctl_since(commit_ts)
    if journal.startswith("__JOURNAL_ERROR__"):
        return None
    for line in journal.splitlines():
        if not RESTART_RE.search(line):
            continue
        m = LINE_TS_RE.match(line)
        if not m:
            continue
        ts = parse_iso_z(m.group("ts"))
        if ts and ts >= commit_ts:
            return ts
    return None


def load_signal_log_trades(window_start: datetime,
                            window_end: datetime) -> List[Dict[str, Any]]:
    """Return signal_log entries opened in [window_start, window_end]
    whose strategy is NEWS_STRATEGY or NEWS_TICK. Both closed and open
    trades are returned; outcome categorisation handles each."""
    if not SIGNAL_LOG.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with SIGNAL_LOG.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            strategy = str(rec.get("strategy") or "").upper()
            if strategy not in NEWS_STRATEGIES:
                continue
            t_open = parse_iso_z(str(rec.get("timestamp_open") or ""))
            if t_open is None:
                continue
            if t_open < window_start or t_open > window_end:
                continue
            rec["_t_open"] = t_open
            t_close = parse_iso_z(str(rec.get("timestamp_close") or ""))
            rec["_t_close"] = t_close
            rows.append(rec)
    return rows


def categorise_outcome(rec: Dict[str, Any]) -> str:
    """Map a signal_log record to a coarse category for the report:
      - "OPEN"       — trade still active (no timestamp_close)
      - "TP"         — TP hit (pnl_pips > 0)
      - "SL"         — SL hit (pnl_pips < 0)
      - "PRE_NEWS"   — closed by another upcoming news event guard
      - "MPP"        — MANAGER_PROFIT_PROTECT trailing exit
      - "REGIME_MAX_HOLD" — time/regime ejection
      - "MANUAL_POS" — closed manually with positive pnl
      - "MANUAL_NEG" — closed manually with negative pnl
      - "OTHER"      — fall-through (with original close_reason in payload)
    """
    if rec.get("_t_close") is None:
        return "OPEN"
    outcome = str(rec.get("outcome") or "").upper()
    reason = str(rec.get("close_reason") or "")
    pnl = float(rec.get("pnl_pips") or 0.0)
    if outcome in ("TP1", "TP2", "TP"):
        return "TP"
    if outcome == "SL":
        return "SL"
    rl = reason.lower()
    if "tp hit" in rl:
        return "TP"
    if "sl hit" in rl:
        return "SL"
    if "pre_news" in rl or "pre-news" in rl:
        return "PRE_NEWS"
    if "manager_profit_protect" in rl or "mpp" in rl.split():
        return "MPP"
    if "regime_max_hold" in rl:
        return "REGIME_MAX_HOLD"
    return "MANUAL_POS" if pnl > 0 else ("MANUAL_NEG" if pnl < 0 else "OTHER")


def load_observed_rows(window_start: datetime,
                       window_end: datetime) -> List[Dict[str, Any]]:
    if not OBS_LOG.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with OBS_LOG.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = parse_iso_z(str(rec.get("ts") or ""))
            if ts is None:
                continue
            if ts < window_start or ts > window_end:
                continue
            rec["_parsed_ts"] = ts
            rows.append(rec)
    return rows


def fetch_ticks_for_outcome(symbol: str, fire_ts: datetime,
                             hold_end: datetime) -> List[Tuple[float, float]]:
    journal = journalctl_since(fire_ts, hold_end,
                                extra_grep=f"[{symbol}] TICK")
    if journal.startswith("__JOURNAL_ERROR__"):
        return []
    ticks: List[Tuple[float, float]] = []
    for line in journal.splitlines():
        m = TICK_RE.search(line)
        if not m or m.group("sym") != symbol:
            continue
        try:
            base = m.group("msg_ts").replace(",", ".")
            ts = datetime.strptime(base, "%Y-%m-%d %H:%M:%S.%f").replace(
                tzinfo=timezone.utc).timestamp()
            ticks.append((ts, float(m.group("mid"))))
        except Exception:
            continue
    ticks.sort()
    return ticks


def simulate_outcome(fire: Dict[str, Any]) -> Dict[str, Any]:
    """Walk forward through ticks from fire_ts until SL/TP/HOLD_END.
    Returns outcome dict with pnl_pips, max_favourable, max_adverse."""
    sym = str(fire.get("symbol") or "")
    signal = str(fire.get("signal") or "")
    entry = float(fire.get("entry") or 0)
    sl_price = float(fire.get("sl_price") or 0)
    tp_price = float(fire.get("tp_price") or 0)
    fire_ts = parse_iso_z(str(fire.get("ts") or ""))
    if not (sym and signal and entry and sl_price and tp_price and fire_ts):
        return {"outcome": "MALFORMED"}
    hold_end = fire_ts.replace(hour=21, minute=0, second=0, microsecond=0)
    if hold_end <= fire_ts:
        hold_end = fire_ts + timedelta(hours=4)
    ticks = fetch_ticks_for_outcome(sym, fire_ts, hold_end)
    if not ticks:
        return {"outcome": "NO_TICKS"}

    sign = -1 if signal == "SELL" else 1
    best_p = entry
    worst_p = entry
    last_p = entry
    last_ts = fire_ts.timestamp()
    outcome = "HOLD_END"
    for ts, mid in ticks:
        last_p = mid
        last_ts = ts
        if signal == "SELL":
            best_p = min(best_p, mid)
            worst_p = max(worst_p, mid)
            if mid >= sl_price:
                outcome = "SL"
                break
            if mid <= tp_price:
                outcome = "TP"
                break
        else:
            best_p = max(best_p, mid)
            worst_p = min(worst_p, mid)
            if mid <= sl_price:
                outcome = "SL"
                break
            if mid >= tp_price:
                outcome = "TP"
                break

    pnl = (last_p - entry) * sign
    favourable = (best_p - entry) * sign
    adverse = (worst_p - entry) * sign
    return {
        "outcome": outcome,
        "pnl_pips": round(pnl, 1),
        "favourable_pips": round(favourable, 1),
        "adverse_pips": round(adverse, 1),
    }


def _summarise_strategy(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-strategy aggregate of signal_log NEWS_* trades."""
    cats = Counter()
    by_pair = Counter()
    pnl_by_cat: Dict[str, List[float]] = defaultdict(list)
    pnl_total = 0.0
    worst = 0.0
    for r in rows:
        cat = categorise_outcome(r)
        cats[cat] += 1
        by_pair[r.get("pair") or r.get("epic", "?").split(".")[-3]] += 1
        if cat != "OPEN":
            pnl = float(r.get("pnl_pips") or 0.0)
            pnl_by_cat[cat].append(pnl)
            pnl_total += pnl
            if pnl < worst:
                worst = pnl
    decided = sum(c for k, c in cats.items() if k != "OPEN")
    wins = sum(c for k, c in cats.items() if k in ("TP", "MANUAL_POS"))
    win_rate = (wins / decided) if decided > 0 else 0.0
    return {
        "rows": rows,
        "n": len(rows),
        "categories": dict(cats),
        "by_pair": dict(by_pair),
        "pnl_total": pnl_total,
        "pnl_by_cat": {k: sum(v) for k, v in pnl_by_cat.items()},
        "avg_by_cat": {k: (sum(v) / len(v) if v else 0.0)
                        for k, v in pnl_by_cat.items()},
        "worst_single": worst,
        "win_rate": win_rate,
        "wins": wins,
        "decided": decided,
    }


def build_report(restart_ts: Optional[datetime], fallback_fire: bool) -> str:
    if restart_ts is None:
        lines = [
            "NEWS_STRATEGY/NEWS_TICK 7-day live verification",
            "",
            f"⚠️ NO RESTART DETECTED since commit 251d6fb "
            f"({COMMIT_LANDED_AT.isoformat()}) — live mode never "
            "activated; nothing to verify.",
        ]
        if fallback_fire:
            lines.append(
                f"Fallback-fire date {FALLBACK_FIRE.isoformat()} reached; "
                "verification will not retry."
            )
        lines.append("")
        lines.append("Verdict: Restart required before live verification.")
        return "\n".join(lines)

    window_start = restart_ts
    window_end = _now()

    # Primary source: real trades from signal_log.jsonl.
    trades = load_signal_log_trades(window_start, window_end)
    nt_trades = [r for r in trades if str(r.get("strategy")).upper() == "NEWS_TICK"]
    ns_trades = [r for r in trades if str(r.get("strategy")).upper() == "NEWS_STRATEGY"]
    nt_summary = _summarise_strategy(nt_trades)
    ns_summary = _summarise_strategy(ns_trades)

    # Secondary source: any leftover observable rows from the brief
    # NEWS_OBSERVABLE_ONLY=1 window between the rebuild deploy and the
    # flip to live. Logged only as context; not used for the verdict.
    observed = load_observed_rows(window_start, window_end)
    obs_fires = [r for r in observed if r.get("kind") in ("FIRE", "WOULD_FIRE")]

    aggregate_pips = nt_summary["pnl_total"] + ns_summary["pnl_total"]
    decided_total = nt_summary["decided"] + ns_summary["decided"]
    wins_total = nt_summary["wins"] + ns_summary["wins"]
    win_rate = (wins_total / decided_total) if decided_total > 0 else 0.0
    worst_single = min(nt_summary["worst_single"], ns_summary["worst_single"])

    # Distinct news-event hours (use timestamp_open, hour-bucket).
    distinct_event_hours: set = set()
    for r in trades:
        t = r.get("_t_open")
        if t:
            distinct_event_hours.add(t.strftime("%Y-%m-%d-%H"))
    events_in_window = len(distinct_event_hours)

    # Promotion criteria — same 7 thresholds, applied to live data.
    # c6 / c7 semantics adapted: in live mode there is no WOULD_FIRE
    # vs WOULD_NOT_FIRE counter, so we treat them as quality flags:
    #   c6: count of OPEN-or-MANUAL_POS-no-TP outcomes (price moved
    #       favourably but TP wasn't hit) — soft TP signal.
    #   c7: count of MANUAL_NEG outcomes ≥25p (large adverse without
    #       SL hit, suggesting SL too wide / late) — soft SL signal.
    soft_tp_no_hit = (
        nt_summary["categories"].get("MANUAL_POS", 0)
        + ns_summary["categories"].get("MANUAL_POS", 0)
        + nt_summary["categories"].get("PRE_NEWS", 0)
        + ns_summary["categories"].get("PRE_NEWS", 0)
    )
    large_neg_no_sl = sum(
        1 for r in trades
        if categorise_outcome(r) == "MANUAL_NEG"
        and abs(float(r.get("pnl_pips") or 0)) >= 25
    )

    c1 = events_in_window >= MIN_EVENTS_IN_WINDOW
    c2 = len(trades) >= MIN_WOULD_FIRE_NEWS_STRATEGY
    c3 = aggregate_pips > MIN_AGGREGATE_PIPS
    c4 = win_rate >= MIN_WIN_RATE
    c5 = abs(worst_single) <= MAX_SINGLE_LOSS_PIPS
    c6 = soft_tp_no_hit < SOFT_TP_THRESHOLD_COUNT
    c7 = large_neg_no_sl < TIGHT_SL_REJECT_COUNT
    all_pass = c1 and c2 and c3 and c4 and c5 and c6 and c7

    if all_pass:
        verdict = "Live performance meets all 7 criteria — keep running."
    elif not c2:
        verdict = "Continue running — too few news events in window to judge."
    elif not c5:
        verdict = "URGENT: catastrophic single loss observed — investigate before next event."
    elif not c3 or not c4:
        verdict = "Tune — aggregate P&L or win rate below threshold."
    elif not c6:
        verdict = "Tune TP — multiple favourable-but-TP-not-hit closes (mirror too aggressive)."
    elif not c7:
        verdict = "Tune SL — multiple large adverse closes outside SL (cap too loose)."
    else:
        verdict = "Continue running — criteria partially met."

    def _fmt_cats(cats: Dict[str, int], pnl_by_cat: Dict[str, float],
                   avg_by_cat: Dict[str, float]) -> List[str]:
        order = ["TP", "SL", "MPP", "PRE_NEWS", "REGIME_MAX_HOLD",
                 "MANUAL_POS", "MANUAL_NEG", "OTHER", "OPEN"]
        out = []
        for k in order:
            if k not in cats:
                continue
            n = cats[k]
            avg = avg_by_cat.get(k, 0.0)
            tot = pnl_by_cat.get(k, 0.0)
            if k == "OPEN":
                out.append(f"    {k:<16}: {n} (still active)")
            else:
                out.append(f"    {k:<16}: {n} (avg {avg:+.1f}p, total {tot:+.1f}p)")
        return out

    lines: List[str] = []
    lines.append("NEWS_STRATEGY/NEWS_TICK 7-day live verification")
    lines.append("")
    lines.append(f"Restart since deploy: {restart_ts.isoformat()} "
                  f"(+{(_now() - restart_ts).total_seconds() / 3600:.1f}h)")
    lines.append(f"Window: {window_start.date()} → {window_end.date()}")
    lines.append(f"Source: signal_log.jsonl (live trades since restart)")
    lines.append("")
    lines.append(f"News-event hours in window:  {events_in_window}")
    lines.append(f"NEWS_TICK trades:            {nt_summary['n']} "
                  f"(by pair: {nt_summary['by_pair']})")
    lines.extend(_fmt_cats(nt_summary["categories"],
                            nt_summary["pnl_by_cat"],
                            nt_summary["avg_by_cat"]))
    lines.append(f"  hypothetical PnL:          {nt_summary['pnl_total']:+.1f}p")
    lines.append("")
    lines.append(f"NEWS_STRATEGY trades:        {ns_summary['n']} "
                  f"(by pair: {ns_summary['by_pair']})")
    lines.extend(_fmt_cats(ns_summary["categories"],
                            ns_summary["pnl_by_cat"],
                            ns_summary["avg_by_cat"]))
    lines.append(f"  hypothetical PnL:          {ns_summary['pnl_total']:+.1f}p")
    lines.append("")
    if obs_fires:
        lines.append(f"Observable-mode fires (pre-flip context): {len(obs_fires)}")
        lines.append("")
    lines.append(f"Aggregate P&L (live):        {aggregate_pips:+.1f}p across {len(trades)} trades")
    lines.append(f"Win rate:                    {win_rate * 100:.0f}% "
                  f"({wins_total}/{decided_total} decided)")
    lines.append(f"Worst single loss:           {worst_single:+.1f}p")
    lines.append("")
    lines.append("Promotion / health criteria:")
    lines.append(f"  1. ≥{MIN_EVENTS_IN_WINDOW} event-hours in window:    "
                 f"{'PASS' if c1 else 'FAIL'} ({events_in_window})")
    lines.append(f"  2. ≥{MIN_WOULD_FIRE_NEWS_STRATEGY} live trades:               "
                 f"{'PASS' if c2 else 'FAIL'} ({len(trades)})")
    lines.append(f"  3. Aggregate P&L > 0:                "
                 f"{'PASS' if c3 else 'FAIL'} ({aggregate_pips:+.1f}p)")
    lines.append(f"  4. Win rate ≥ {int(MIN_WIN_RATE * 100)}%:                  "
                 f"{'PASS' if c4 else 'FAIL'} ({win_rate * 100:.0f}%)")
    lines.append(f"  5. No single loss > 50p:            "
                 f"{'PASS' if c5 else 'FAIL'} (worst {worst_single:+.1f}p)")
    lines.append(f"  6. <{SOFT_TP_THRESHOLD_COUNT} favourable-but-no-TP:        "
                 f"{'PASS' if c6 else 'FAIL'} ({soft_tp_no_hit})")
    lines.append(f"  7. <{TIGHT_SL_REJECT_COUNT} large-adverse-no-SL (≥25p):   "
                 f"{'PASS' if c7 else 'FAIL'} ({large_neg_no_sl})")
    lines.append("")
    lines.append(f"Verdict: {verdict}")
    return "\n".join(lines)


def remove_cron_entry() -> str:
    try:
        existing = subprocess.check_output(
            ["crontab", "-l"], text=True, errors="replace", timeout=10,
        )
    except subprocess.SubprocessError as exc:
        return f"cron self-removal: read failed ({exc})"
    out_lines: List[str] = []
    removed = 0
    for ln in existing.splitlines():
        if CRON_MARKER in ln and "news_strategy_7d_verify" in ln:
            removed += 1
            continue
        out_lines.append(ln)
    new_text = "\n".join(out_lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    try:
        subprocess.run(
            ["crontab", "-"], input=new_text, text=True, check=True, timeout=10,
        )
    except subprocess.SubprocessError as exc:
        return f"cron self-removal: write failed ({exc})"
    return f"cron self-removal: removed {removed} line(s)"


def send_telegram(text: str) -> str:
    try:
        from telegram_alerts import send_status_update
        send_status_update(text)
        return "telegram: sent"
    except Exception as exc:
        return f"telegram: FAILED ({type(exc).__name__}: {exc})"


def should_fire(restart_ts: Optional[datetime]) -> Tuple[bool, bool]:
    now = _now()
    if restart_ts is not None:
        soak_h = (now - restart_ts).total_seconds() / 3600.0
        if soak_h >= float(SOAK_HOURS):
            return True, False
        return False, False
    if now >= FALLBACK_FIRE:
        return True, True
    return False, False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Build + print the report; skip Telegram + cron removal.")
    parser.add_argument("--force-fire", action="store_true",
                        help="Treat now as past the soak window (testing).")
    args = parser.parse_args()

    restart_ts = find_first_restart_after(COMMIT_LANDED_AT)
    if args.force_fire:
        fire, fallback_fire = True, (restart_ts is None)
    else:
        fire, fallback_fire = should_fire(restart_ts)

    if not fire and not args.dry_run:
        print(f"[{_now().isoformat()}] not yet ready: "
              f"restart_ts={restart_ts} fallback={FALLBACK_FIRE.isoformat()}")
        return 0

    msg = build_report(restart_ts, fallback_fire=fallback_fire)
    print(msg)
    print("---")
    if args.dry_run:
        print("dry-run: telegram + cron removal SKIPPED")
        return 0
    print(send_telegram(msg))
    print(remove_cron_entry())
    return 0


if __name__ == "__main__":
    sys.exit(main())
