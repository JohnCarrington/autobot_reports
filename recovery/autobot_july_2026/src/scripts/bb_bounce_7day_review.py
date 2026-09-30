#!/usr/bin/env python3
"""
bb_bounce_7day_review.py — one-shot 7-day verification of the
GBPUSD_BB_BOUNCE deploy (commit 556d0c8 merged + autobot.service restarted
at 2026-04-30T14:31:27Z).

Polling design: invoked hourly by cron from 2026-04-30 onward. Each
invocation decides whether to fire the verification report:

  1. If ≥168 h (7 days) have elapsed since the deploy anchor:
     build report, send Telegram, self-remove cron.
  2. If now >= FALLBACK_FIRE (2026-05-08 12:00 UTC):
     fire anyway (covers cases where the anchor file went missing),
     self-remove cron.
  3. Otherwise: exit silently. Cron will fire again next hour.

Diagnostic content per the deploy spec:
  1. BB_BOUNCE fires in window — total, per-direction, per-day.
  2. Outcome distribution — wins/losses, P&L, close-reason breakdown.
  3. Trigger geometry — prev-bar pierce vs intra-bar pierce, fires + wins by form.
  4. TP-floor rejection count (tp_below_floor — degenerate V-recoveries).
  5. SL-ceiling rejection count (sl_exceeds_ceiling — too-large trigger bars).
  6. Comparison to RAW_REVERSAL prior 7 days on GBPUSD.
  7. Recommendation tag.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, "/opt/tradingbot")

REPO_ROOT       = Path("/opt/tradingbot")
LOG_DIR         = REPO_ROOT / "logs"
CANDLE_DIR      = REPO_ROOT / "data" / "candles" / "GBPUSD"
ANCHOR_FILE     = REPO_ROOT / "cache" / "bb_bounce_review_anchor.txt"
CRON_MARKER     = "ONE-SHOT bb_bounce_7day_review"

# Deploy anchor (commit 556d0c8 merge + autobot restart).
COMMIT_LANDED_AT  = datetime(2026, 4, 30, 14, 31, 27, tzinfo=timezone.utc)
FALLBACK_FIRE     = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
SOAK_HOURS        = 7 * 24  # 168 h

BB_BOUNCE_MODES   = {"GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S"}
RAW_REV_MODES     = {"GBPUSD_RAW_REVERSAL_L", "GBPUSD_RAW_REVERSAL_S"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_anchor() -> datetime:
    """Anchor file overrides COMMIT_LANDED_AT if present (for re-runs after
    a re-deploy). Falls back to the constant if missing or unparseable."""
    if not ANCHOR_FILE.exists():
        return COMMIT_LANDED_AT
    try:
        text = ANCHOR_FILE.read_text(encoding="utf-8").strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        ts = datetime.fromisoformat(text)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return COMMIT_LANDED_AT


def _journalctl_grep(since: datetime, until: datetime, *, pattern: str) -> List[str]:
    cmd = [
        "journalctl", "-u", "autobot.service",
        "--since", since.strftime("%Y-%m-%d %H:%M:%S"),
        "--until", until.strftime("%Y-%m-%d %H:%M:%S"),
        "--no-pager",
    ]
    try:
        out = subprocess.check_output(cmd, text=True, errors="replace", timeout=180)
    except subprocess.SubprocessError as exc:
        return [f"__JOURNAL_ERROR__: {exc}"]
    rx = re.compile(pattern)
    return [line for line in out.splitlines() if rx.search(line)]


def _iter_dates(start: datetime, end: datetime):
    d = start.date()
    while d <= end.date():
        yield d
        d = d + timedelta(days=1)


def _load_sweep_journal(d) -> List[Dict[str, Any]]:
    p = LOG_DIR / f"sweep_journal_{d.isoformat()}.csv"
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            out.append(row)
    return out


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect_fires(window_start: datetime,
                  window_end: datetime,
                  modes: set) -> List[Dict[str, Any]]:
    """Pull `taken=True` rows from sweep_journal CSVs for matching modes
    in the window."""
    out: List[Dict[str, Any]] = []
    for d in _iter_dates(window_start, window_end):
        for row in _load_sweep_journal(d):
            mode = (row.get("mode") or "").upper()
            if mode not in modes:
                continue
            if (row.get("taken") or "").strip() not in ("True", "true", "1"):
                continue
            ts_str = (row.get("timestamp") or "").replace("Z", "+00:00")
            try:
                ts = datetime.fromisoformat(ts_str)
            except Exception:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < window_start or ts > window_end:
                continue
            row["_ts"] = ts
            row["_pnl"] = _to_float(row.get("pnl_pips"))
            row["_entry"] = _to_float(row.get("entry_price"))
            row["_exit"] = _to_float(row.get("exit_price"))
            row["_sl_p"] = _to_float(row.get("sl_pips"))
            row["_tp_p"] = _to_float(row.get("tp_pips"))
            out.append(row)
    out.sort(key=lambda r: r["_ts"])
    return out


def classify_close_reason(reason: str) -> str:
    rl = (reason or "").lower()
    if "tp" in rl and "hit" in rl:
        return "TP_HIT"
    if "sl" in rl and "hit" in rl:
        return "SL_HIT"
    if "pre_news" in rl or "pre-news" in rl:
        return "PRE_NEWS"
    if "regime_max_hold" in rl:
        return "REGIME_MAX_HOLD"
    if "manager_profit_protect" in rl or "manual" in rl or "external" in rl:
        return "MANUAL"
    if "tp" in rl:
        return "TP_HIT"
    if "sl" in rl:
        return "SL_HIT"
    return "OTHER"


def _load_candles_for_date(d) -> List[Dict[str, Any]]:
    p = CANDLE_DIR / f"{d.isoformat()}.csv"
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            ts_str = (row.get("timestamp") or "").replace("Z", "+00:00")
            try:
                ts = datetime.fromisoformat(ts_str)
            except Exception:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            try:
                out.append({
                    "ts": ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                })
            except (KeyError, ValueError):
                continue
    out.sort(key=lambda r: r["ts"])
    return out


def _bb20_lower(closes: List[float]) -> Optional[float]:
    if len(closes) < 20:
        return None
    win = closes[-20:]
    mid = sum(win) / 20.0
    var = sum((c - mid) ** 2 for c in win) / 20.0
    return mid - 2.0 * math.sqrt(var)


def classify_geometry(fire_ts: datetime) -> str:
    """For a fire at fire_ts, determine if the trigger was a prev-bar
    pierce (legacy form: prev.low <= BBL but cur.low > BBL) or an
    intra-bar pierce (new form: cur.low <= BBL).

    Reads the 5m candle CSV for the fire's date and the day before
    (for early-morning fires that need the prior day's tail in the
    20-close BB window). Locates the bar matching fire_ts (5m floor),
    computes BBL on the 20 closes ending at that bar, and tests both
    bars."""
    bar_open = fire_ts - timedelta(minutes=fire_ts.minute % 5,
                                    seconds=fire_ts.second,
                                    microseconds=fire_ts.microsecond)
    # Trigger fires *just after* a 5M close. The bar that just closed
    # has timestamp (bar_open - 5min) and represents [bar_open-5, bar_open).
    # Practically: sweep_journal timestamps come from execute_trade, which
    # runs ~1-3s after the close. The relevant bar in candle data has
    # timestamp = bar_open - 5min if fire_ts is XX:XX:0X-XX:XX:0n, else
    # bar_open. Try both windows.
    candidates_ts = [bar_open - timedelta(minutes=5), bar_open]
    # Pull candles for fire date and day before.
    candles = _load_candles_for_date((fire_ts - timedelta(days=1)).date()) + \
              _load_candles_for_date(fire_ts.date())
    if len(candles) < 21:
        return "unknown"
    for cand_ts in candidates_ts:
        idx = next(
            (i for i, c in enumerate(candles)
             if c["ts"] == cand_ts.astimezone(timezone.utc)),
            None,
        )
        if idx is None or idx < 19:
            continue
        closes = [c["close"] for c in candles[: idx + 1]]
        bbl = _bb20_lower(closes)
        if bbl is None:
            continue
        cur = candles[idx]
        prev = candles[idx - 1]
        cur_pierce = cur["low"] <= bbl
        prev_pierce = prev["low"] <= bbl
        if cur_pierce and not prev_pierce:
            return "intra-bar"
        if prev_pierce:
            return "prev-bar"
        # If neither pierces here, try the other candidate bar.
    return "unknown"


def count_rejections(window_start: datetime,
                     window_end: datetime) -> Dict[str, int]:
    """Count BB_BOUNCE rejection log lines in the window."""
    tp_floor_lines = _journalctl_grep(
        window_start, window_end,
        pattern=r"\[BB_BOUNCE\].*rejected: tp_below_floor",
    )
    sl_ceiling_lines = _journalctl_grep(
        window_start, window_end,
        pattern=r"\[BB_BOUNCE\].*rejected: sl_exceeds_ceiling",
    )
    if tp_floor_lines and tp_floor_lines[0].startswith("__JOURNAL_ERROR__"):
        tp_floor_lines = []
    if sl_ceiling_lines and sl_ceiling_lines[0].startswith("__JOURNAL_ERROR__"):
        sl_ceiling_lines = []
    return {
        "tp_floor": len(tp_floor_lines),
        "sl_ceiling": len(sl_ceiling_lines),
    }


def summarise_outcomes(fires: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [r for r in fires if r["_pnl"] is not None]
    open_ = [r for r in fires if r["_pnl"] is None]
    wins = [r for r in closed if r["_pnl"] > 0]
    losses = [r for r in closed if r["_pnl"] < 0]
    flats = [r for r in closed if r["_pnl"] == 0]
    avg_w = sum(r["_pnl"] for r in wins) / len(wins) if wins else 0.0
    avg_l = sum(r["_pnl"] for r in losses) / len(losses) if losses else 0.0
    net = sum(r["_pnl"] for r in closed)
    reasons = Counter(classify_close_reason(r.get("close_reason") or "")
                       for r in closed)
    return {
        "total_fires": len(fires),
        "closed": len(closed),
        "open": len(open_),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "avg_winner": avg_w,
        "avg_loser": avg_l,
        "net_pips": net,
        "reasons": dict(reasons),
    }


def per_direction(fires: List[Dict[str, Any]]) -> Tuple[int, int]:
    longs = sum(1 for r in fires if (r.get("signal") or "").upper() == "BUY")
    shorts = sum(1 for r in fires if (r.get("signal") or "").upper() == "SELL")
    return longs, shorts


def per_day(fires: List[Dict[str, Any]],
            window_start: datetime, window_end: datetime) -> Dict[str, int]:
    by = defaultdict(int)
    for d in _iter_dates(window_start, window_end):
        # Skip weekends.
        if d.weekday() < 5:
            by[d.isoformat()] = 0
    for r in fires:
        d = r["_ts"].date().isoformat()
        by[d] += 1
    return dict(sorted(by.items()))


def geometry_breakdown(fires: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    out = {"prev-bar": {"fires": 0, "wins": 0},
           "intra-bar": {"fires": 0, "wins": 0},
           "unknown": {"fires": 0, "wins": 0}}
    for r in fires:
        form = classify_geometry(r["_ts"])
        out[form]["fires"] += 1
        if r["_pnl"] is not None and r["_pnl"] > 0:
            out[form]["wins"] += 1
    return out


def make_recommendation(summary: Dict[str, Any],
                         per_day_counts: Dict[str, int],
                         rejections: Dict[str, int]) -> Tuple[str, str]:
    trading_days = sum(1 for c in per_day_counts.values() if c is not None)
    avg_per_day = (summary["total_fires"] / trading_days) if trading_days else 0.0
    decided = summary["wins"] + summary["losses"]
    win_rate = (summary["wins"] / decided) if decided else 0.0
    net = summary["net_pips"]

    if 0.5 <= avg_per_day <= 4.0 and net > 0 and (decided == 0 or win_rate >= 0.45):
        return ("as_designed",
                f"Avg {avg_per_day:.1f} fires/day, net {net:+.1f}p, "
                f"win rate {win_rate*100:.0f}%.")
    if avg_per_day < 0.5 and rejections.get("tp_floor", 0) >= max(3, summary["total_fires"]):
        return ("loosen",
                f"Only {avg_per_day:.1f} fires/day with {rejections['tp_floor']} "
                f"TP-floor rejections — recovery candles overshooting BBM "
                f"are blocking fires.")
    if avg_per_day > 4.0 and net < 0:
        return ("tighten",
                f"{avg_per_day:.1f} fires/day with net {net:+.1f}p — "
                f"firing too freely with poor outcomes.")
    if rejections.get("sl_ceiling", 0) > 5:
        return ("specific_change_suggested",
                f"{rejections['sl_ceiling']} SL-ceiling rejections — "
                f"raising max SL above 25p may catch more setups.")
    if rejections.get("tp_floor", 0) > 5 and avg_per_day < 1.0:
        return ("specific_change_suggested",
                f"{rejections['tp_floor']} TP-floor rejections vs {summary['total_fires']} "
                f"fires — consider fixed-pip TP fallback when BBM is unreachable.")
    return ("as_designed",
            f"Inconclusive but within tolerance: {avg_per_day:.1f}/day, "
            f"net {net:+.1f}p, win rate {win_rate*100:.0f}%.")


def build_report(deploy_anchor: datetime, fallback_fire_only: bool) -> str:
    now = _now()
    window_start = deploy_anchor
    window_end = now

    bb_fires = collect_fires(window_start, window_end, BB_BOUNCE_MODES)
    summary = summarise_outcomes(bb_fires)
    longs, shorts = per_direction(bb_fires)
    pd = per_day(bb_fires, window_start, window_end)
    geom = geometry_breakdown(bb_fires)
    rejections = count_rejections(window_start, window_end)

    # Prior-week RAW_REVERSAL comparison.
    prior_start = window_start - timedelta(days=7)
    prior_end = window_start
    prior_fires = collect_fires(prior_start, prior_end, RAW_REV_MODES)
    prior_closed = [r for r in prior_fires if r["_pnl"] is not None]
    prior_net = sum(r["_pnl"] for r in prior_closed)

    rec_tag, rec_reason = make_recommendation(summary, pd, rejections)

    trading_days = sum(1 for d in pd if datetime.fromisoformat(d).weekday() < 5)
    avg_per_day = (summary["total_fires"] / trading_days) if trading_days else 0.0

    reasons = summary["reasons"]
    def _r(k): return reasons.get(k, 0)
    reasons_line = (
        f"TP_HIT={_r('TP_HIT')}, SL_HIT={_r('SL_HIT')}, "
        f"PRE_NEWS={_r('PRE_NEWS')}, REGIME_MAX_HOLD={_r('REGIME_MAX_HOLD')}, "
        f"manual={_r('MANUAL')}"
    )

    days_breakdown = ", ".join(f"{d}={c}" for d, c in pd.items())

    lines: List[str] = []
    lines.append("GBPUSD_BB_BOUNCE 7-day review")
    lines.append("")
    if fallback_fire_only:
        lines.append(
            f"⚠ Fired on fallback date ({FALLBACK_FIRE.isoformat()}); "
            f"deploy soak window may be incomplete."
        )
        lines.append("")
    lines.append(
        f"Fires: {summary['total_fires']} total ({longs} LONG / {shorts} SHORT) "
        f"over {trading_days} trading days"
    )
    lines.append(f"Avg per day: {avg_per_day:.1f}")
    if days_breakdown:
        lines.append(f"Per day: {days_breakdown}")
    lines.append("")
    lines.append("Outcomes:")
    lines.append(f"  Wins: {summary['wins']} (avg {summary['avg_winner']:+.1f}p)")
    lines.append(f"  Losses: {summary['losses']} (avg {summary['avg_loser']:+.1f}p)")
    if summary["flats"]:
        lines.append(f"  Flat: {summary['flats']}")
    if summary["open"]:
        lines.append(f"  Still open: {summary['open']}")
    lines.append(f"  Net: {summary['net_pips']:+.1f} pips")
    lines.append(f"  Close reasons: {reasons_line}")
    lines.append("")
    lines.append("Geometry:")
    lines.append(
        f"  Prev-bar pierce: {geom['prev-bar']['fires']} fires "
        f"({geom['prev-bar']['wins']} wins)"
    )
    lines.append(
        f"  Intra-bar pierce: {geom['intra-bar']['fires']} fires "
        f"({geom['intra-bar']['wins']} wins)"
    )
    if geom["unknown"]["fires"]:
        lines.append(
            f"  Unclassified: {geom['unknown']['fires']} fires "
            f"({geom['unknown']['wins']} wins)"
        )
    lines.append("")
    lines.append("Rejections:")
    lines.append(f"  TP-floor (overshoot): {rejections.get('tp_floor', 0)}")
    lines.append(f"  SL-ceiling (large bar): {rejections.get('sl_ceiling', 0)}")
    lines.append("")
    lines.append(
        f"Comparison: RAW_REVERSAL prior week fired {len(prior_fires)} times, "
        f"net {prior_net:+.1f} pips"
    )
    lines.append("")
    lines.append(f"Recommendation: {rec_tag}")
    lines.append(f"Reasoning: {rec_reason}")
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
        if CRON_MARKER in ln and "bb_bounce_7day_review" in ln:
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


def should_fire(deploy_anchor: datetime) -> Tuple[bool, bool]:
    """(fire, fallback_only) — fire if soak elapsed OR fallback date passed."""
    now = _now()
    soak_h = (now - deploy_anchor).total_seconds() / 3600.0
    if soak_h >= float(SOAK_HOURS):
        return True, False
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

    deploy_anchor = _read_anchor()
    if args.force_fire:
        fire, fallback_only = True, False
    else:
        fire, fallback_only = should_fire(deploy_anchor)

    if not fire and not args.dry_run:
        print(f"[{_now().isoformat()}] not yet ready: "
              f"anchor={deploy_anchor.isoformat()} "
              f"fallback={FALLBACK_FIRE.isoformat()}")
        return 0

    msg = build_report(deploy_anchor, fallback_fire_only=fallback_only)
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
