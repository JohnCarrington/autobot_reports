#!/usr/bin/env python3
"""premarket_health_pia.py — PIA_FIRST premarket healthcheck.

Runs at 05:45 UTC Mon-Fri (after the 05:30 PIA_FIRST producer). Validates
service, today's briefings, IG session, recent error log, REST budget.
Sends one Telegram message — PASS or FAIL — every run.

Layout differs from the legacy v4/v5 premarket_health.py:
  - briefings at briefings/pia_first/<DATE>/<PAIR>.json (not logs/briefing_*)
  - schema uses LONG/SHORT, entry/stop/target, confidence, rationale
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
try:
    from dotenv import load_dotenv
    load_dotenv("/opt/tradingbot/.env")
except Exception:
    pass

from telegram_alerts import send_telegram_message
import pair_config

PAIRS = ["GBPUSD", "EURUSD", "USDCAD", "USDJPY"]
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
BRIEF_DIR = Path("/opt/tradingbot/briefings/pia_first") / TODAY
BENIGN_ERR_PATTERNS = [
    r"Subscription error 26",  # IG user-frequency rate-limit, auto-retried
]


def _check_service():
    try:
        active = subprocess.run(
            ["systemctl", "is-active", "autobot.service"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if active != "active":
            return False, f"autobot.service is {active}"
        show = subprocess.run(
            ["systemctl", "show", "autobot.service",
             "-p", "MainPID", "-p", "ActiveEnterTimestampMonotonic"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        pid = re.search(r"MainPID=(\d+)", show).group(1)
        # Compute uptime from ActiveEnterTimestamp (wall-clock).
        ts = subprocess.run(
            ["systemctl", "show", "autobot.service",
             "-p", "ActiveEnterTimestamp", "--value"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        uptime = ""
        if ts:
            try:
                started = datetime.strptime(ts.rsplit(" ", 1)[0], "%a %Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - started
                hrs, rem = divmod(int(delta.total_seconds()), 3600)
                mins = rem // 60
                uptime = f"{hrs}h {mins}m"
            except Exception:
                uptime = "?"
        return True, f"active (PID {pid}, uptime {uptime})"
    except Exception as e:
        return False, f"check failed: {e}"


def _check_briefings():
    results, fails = {}, []
    for pair in PAIRS:
        f = BRIEF_DIR / f"{pair}.json"
        if not f.exists():
            fails.append(f"{pair}: missing ({f})")
            continue
        try:
            plan = json.loads(f.read_text())
        except Exception as e:
            fails.append(f"{pair}: JSON parse: {e}")
            continue

        direction = plan.get("direction")
        entry, stop, target = plan.get("entry"), plan.get("stop"), plan.get("target")
        conf, rat = plan.get("confidence"), plan.get("rationale")

        if direction not in ("LONG", "SHORT"):
            fails.append(f"{pair}: direction={direction!r} not LONG/SHORT")
            continue
        for name, v in (("entry", entry), ("stop", stop), ("target", target)):
            if not isinstance(v, (int, float)) or v is None:
                fails.append(f"{pair}: {name}={v!r} not numeric")
                break
        else:
            if not isinstance(conf, int) or not (0 <= conf <= 100):
                fails.append(f"{pair}: confidence={conf!r} not int 0-100")
                continue
            if not isinstance(rat, str) or not rat.strip():
                fails.append(f"{pair}: rationale empty")
                continue
            if direction == "LONG" and not (stop < entry < target):
                fails.append(f"{pair}: LONG geometry stop({stop})<entry({entry})<target({target}) violated")
                continue
            if direction == "SHORT" and not (target < entry < stop):
                fails.append(f"{pair}: SHORT geometry target({target})<entry({entry})<stop({stop}) violated")
                continue
            min_stop = pair_config.MIN_SL_PIPS.get(pair, 12.0)
            stop_pips = abs(entry - stop)  # pip_size=1.0 in raw cache scale
            if stop_pips < min_stop:
                fails.append(f"{pair}: stop_dist={stop_pips:.1f}p < min={min_stop:.1f}p")
                continue
            results[pair] = f"{direction} conf={conf}"
    return fails, results


def _check_ig_session():
    try:
        from ig_auth import get_ig_session
        ig, _h, _a = get_ig_session()
        ig.fetch_accounts()
        return True, "authenticated"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _check_recent_errors():
    try:
        out = subprocess.run(
            ["journalctl", "-u", "autobot.service", "--no-pager",
             "--since", "30 minutes ago"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception as e:
        return False, [f"journalctl failed: {e}"], 0
    hits = [
        ln for ln in out.splitlines()
        if re.search(r"\b(ERROR|CRITICAL|api-key-disabled)\b", ln)
        and not any(re.search(p, ln) for p in BENIGN_ERR_PATTERNS)
    ]
    return (len(hits) == 0), hits[:3], len(hits)


def _check_rest_budget():
    try:
        import rest_allowance
        st = rest_allowance.get_state()
        rem = int(st.get("remaining", 0))
        if rem < 100:
            return False, f"FAIL: {rem} remaining"
        if rem < 500:
            return False, f"WARN: {rem} remaining (low)"
        return True, f"{rem} remaining"
    except Exception as e:
        return True, f"skipped ({type(e).__name__}: {e})"


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    svc_ok, svc_msg = _check_service()
    brief_fails, brief_ok = _check_briefings()
    ig_ok, ig_msg = _check_ig_session()
    err_ok, err_sample, err_count = _check_recent_errors()
    budget_ok, budget_msg = _check_rest_budget()

    all_ok = svc_ok and not brief_fails and ig_ok and err_ok and budget_ok

    lines = [f"[PIA-HEALTHCHECK] {now}"]
    if all_ok:
        lines[0] += " ✅ ALL CHECKS PASSED"
        lines.append(f"- Service: {svc_msg}")
        summary = ", ".join(f"{p}: {brief_ok[p]}" for p in PAIRS if p in brief_ok)
        lines.append(f"- Briefings: {len(brief_ok)}/4 valid ({summary})")
        lines.append(f"- IG session: {ig_msg}")
        lines.append(f"- Errors: 0 unfiltered in last 30min")
        lines.append(f"- REST allowance: {budget_msg}")
    else:
        lines[0] += " ❌ FAILED"
        lines.append(f"- Service: {'OK — ' + svc_msg if svc_ok else 'FAIL — ' + svc_msg}")
        if brief_fails:
            lines.append(f"- Briefings: FAIL — {len(brief_fails)} issue(s)")
            for f in brief_fails:
                lines.append(f"    • {f}")
        else:
            lines.append(f"- Briefings: 4/4 valid")
        lines.append(f"- IG session: {'OK' if ig_ok else 'FAIL — ' + ig_msg}")
        if err_count:
            lines.append(f"- Errors: {err_count} unfiltered in last 30min")
            for h in err_sample:
                lines.append(f"    • {h[:200]}")
        else:
            lines.append(f"- Errors: 0 unfiltered")
        lines.append(f"- REST allowance: {budget_msg}")
        lines.append("- ACTION REQUIRED")

    msg = "\n".join(lines)
    print(msg)
    try:
        send_telegram_message(msg, wait=True)
    except Exception as e:
        print(f"telegram send failed: {e}", file=sys.stderr)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
