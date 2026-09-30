#!/usr/bin/env python3
"""
premarket_health.py — Pre-market health check (05:45 UTC daily).

Validates infrastructure on this box before London open and sends a Telegram
alert if anything is wrong. Silent on success (no spam).

Briefing/execution checks (briefing files, session_bias, armed levels) are
flag-gated OFF by default: those responsibilities live on the FXi (144) box
where briefing health and briefing-driven execution were consolidated. Set
BRIEFING_HEALTH_CHECKS_ENABLED=1 to re-enable them.

Infrastructure checks (always on):
  - autobot.service is running and ticks flowing in last 5 min
  - No NameError / SyntaxError / ImportError in last hour of logs
  - Finnhub API key valid and calendar endpoint returning data
  - Weekly IG REST historical-data budget has headroom

Usage:
  python3 premarket_health.py          # run all checks, alert on failure
  python3 premarket_health.py --force  # always send result (even if healthy)

Cron (add via crontab -e):
  45 5 * * 1-5 /opt/tradingbot/venv/bin/python /opt/tradingbot/premarket_health.py
"""

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

LOG_DIR = Path("/opt/tradingbot/logs")
PAIRS = ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Briefing-related checks (files / session_bias / armed levels) belong with
# the briefing-home box (FXi 144). Default OFF on this box; flip via env.
BRIEFING_HEALTH_CHECKS_ENABLED = (
    (os.getenv("BRIEFING_HEALTH_CHECKS_ENABLED", "0") or "0").strip() == "1"
)


def check_autobot_running() -> list[str]:
    """Check autobot.service is active."""
    failures = []
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "autobot.service"],
            capture_output=True, text=True, timeout=10,
        )
        status = r.stdout.strip()
        if status != "active":
            failures.append(f"autobot.service is {status} (not active)")
    except Exception as e:
        failures.append(f"Cannot check autobot.service: {e}")
    return failures


def check_ticks_flowing() -> list[str]:
    """Check that tick logs appeared in the last 5 minutes via journalctl."""
    failures = []
    try:
        r = subprocess.run(
            ["journalctl", "-u", "autobot.service", "--no-pager",
             "--since", "5 min ago", "--grep", "TICK bid="],
            capture_output=True, text=True, timeout=15,
        )
        lines = [l for l in r.stdout.strip().splitlines() if "TICK bid=" in l]
        if not lines:
            failures.append("No ticks in last 5 minutes — streaming may be down")
    except Exception as e:
        failures.append(f"Cannot check tick flow: {e}")
    return failures


def check_briefing_files() -> list[str]:
    """Check today's London briefing exists for all 4 pairs."""
    failures = []
    for pair in PAIRS:
        f = LOG_DIR / f"briefing_{pair}_{TODAY}_London.json"
        if not f.exists():
            failures.append(f"Missing briefing: {f.name}")
    return failures


def check_briefing_bias() -> list[str]:
    """Check session_bias is present and confident in each briefing."""
    failures = []
    for pair in PAIRS:
        f = LOG_DIR / f"briefing_{pair}_{TODAY}_London.json"
        if not f.exists():
            continue  # already caught by check_briefing_files
        try:
            data = json.loads(f.read_text())
            bias = str(data.get("session_bias", "")).upper()
            conf = data.get("bias_confidence")
            if not bias:
                failures.append(
                    f"{pair} London: session_bias=MISSING — briefing incomplete"
                )
            elif conf is not None and float(conf) < 0.45:
                failures.append(
                    f"{pair} London: session_bias={bias} conf={conf} — below 0.45 threshold"
                )
        except Exception as e:
            failures.append(f"{pair} London: cannot parse briefing — {e}")
    return failures


def check_armed_levels() -> list[str]:
    """Check all 4 pairs have levels loaded (briefing has key_levels with entries)."""
    failures = []
    for pair in PAIRS:
        f = LOG_DIR / f"briefing_{pair}_{TODAY}_London.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
            kl = data.get("key_levels", {})
            resistance = kl.get("resistance", [])
            support = kl.get("support", [])
            total = len(resistance) + len(support)
            if total == 0:
                failures.append(f"{pair}: no key_levels in briefing (0 resistance + 0 support)")
            elif total < 3:
                failures.append(f"{pair}: only {total} levels (want >= 3)")
        except Exception as e:
            failures.append(f"{pair}: cannot check levels — {e}")
    return failures


def check_log_errors() -> list[str]:
    """Check for NameError/SyntaxError/ImportError in last hour of autobot logs."""
    failures = []
    error_patterns = re.compile(r"(NameError|SyntaxError|ImportError|AttributeError)")
    try:
        r = subprocess.run(
            ["journalctl", "-u", "autobot.service", "--no-pager",
             "--since", "1 hour ago"],
            capture_output=True, text=True, timeout=30,
        )
        hits = []
        for line in r.stdout.splitlines():
            m = error_patterns.search(line)
            if m:
                # Truncate to keep alert readable
                short = line.strip()[-120:]
                hits.append(f"  {m.group(1)}: ...{short}")
        if hits:
            # Deduplicate and cap at 5
            unique = list(dict.fromkeys(hits))[:5]
            failures.append(
                f"{len(hits)} code errors in last hour:\n" + "\n".join(unique)
            )
    except Exception as e:
        failures.append(f"Cannot scan logs: {e}")
    return failures


def check_finnhub_api() -> list[str]:
    """Check Finnhub economic calendar API is reachable and returns valid data."""
    failures = []
    api_key = os.getenv("FINNHUB_API_KEY", "")

    if not api_key:
        failures.append("FINNHUB_API_KEY not set in .env — news actual/forecast unavailable")
        return failures

    try:
        import requests
        url = (
            f"https://finnhub.io/api/v1/calendar/economic"
            f"?from={TODAY}&to={TODAY}&token={api_key}"
        )
        resp = requests.get(url, timeout=10)

        if resp.status_code == 401:
            failures.append("Finnhub API key invalid (401 Unauthorized)")
            return failures
        if resp.status_code == 429:
            failures.append("Finnhub rate limited (429) — may need to wait or check plan")
            return failures
        if resp.status_code != 200:
            failures.append(f"Finnhub returned HTTP {resp.status_code}: {resp.text[:100]}")
            return failures

        data = resp.json()
        events = data.get("economicCalendar")
        if events is None:
            failures.append(f"Finnhub response missing 'economicCalendar' key: {list(data.keys())}")
            return failures

        if not isinstance(events, list):
            failures.append(f"Finnhub economicCalendar is {type(events).__name__}, expected list")
            return failures

        # Verify field schema on first event (if any events today)
        if events:
            sample = events[0]
            required = {"event", "country", "impact"}
            expected = {"actual", "estimate", "prev", "time", "unit"}
            missing_required = required - set(sample.keys())
            missing_expected = expected - set(sample.keys())
            if missing_required:
                failures.append(f"Finnhub event missing required fields: {missing_required}")
            if missing_expected:
                failures.append(f"Finnhub event missing expected fields: {missing_expected}")

        # Count today's US/GB high-impact events
        us_gb_high = [e for e in events
                      if e.get("country") in ("US", "GB") and e.get("impact") == "high"]
        # Log is informational — not a failure if no events today
        if not us_gb_high:
            pass  # weekends / no-event days are fine

    except requests.exceptions.Timeout:
        failures.append("Finnhub connection timed out after 10s")
    except requests.exceptions.ConnectionError as e:
        failures.append(f"Finnhub connection failed: {e}")
    except Exception as e:
        failures.append(f"Finnhub check error: {type(e).__name__}: {e}")

    return failures


def check_rest_budget() -> list[str]:
    """Check IG REST historical-data budget counter has headroom.

    Counter is Monday-anchored (rest_allowance._current_week_start); IG's
    actual REST quota resets nightly, so the counter is conservative — the
    label reflects that (see 2026-07-21 rewording)."""
    failures = []
    try:
        from rest_allowance import get_state
        st = get_state()
        used = st["points_used"]
        budget = st["points_budget"]
        remaining = st["remaining"]
        pct = (used / budget * 100.0) if budget else 0.0
        print(
            f"        REST budget: {used}/{budget} used ({pct:.1f}%), "
            f"{remaining} remaining (counter since {st['week_start']}; "
            f"IG resets nightly)"
        )
        if remaining < 500:
            failures.append(
                f"REST budget nearly exhausted: {used}/{budget} ({remaining} remaining)"
            )
    except Exception as e:
        failures.append(f"Cannot read REST budget: {type(e).__name__}: {e}")
    return failures


def run_all_checks(force_send: bool = False) -> None:
    checks = [
        ("Bot running", check_autobot_running),
        ("Ticks flowing", check_ticks_flowing),
        ("Log errors", check_log_errors),
        ("Finnhub API", check_finnhub_api),
        ("REST budget", check_rest_budget),
    ]
    if BRIEFING_HEALTH_CHECKS_ENABLED:
        checks.extend([
            ("Briefing files", check_briefing_files),
            ("Session bias", check_briefing_bias),
            ("Armed levels", check_armed_levels),
        ])

    all_failures: list[tuple[str, list[str]]] = []
    results: list[str] = []

    for name, fn in checks:
        try:
            fails = fn()
        except Exception as e:
            fails = [f"Check crashed: {e}"]
        if fails:
            all_failures.append((name, fails))
            results.append(f"FAIL  {name}")
        else:
            results.append(f"  OK  {name}")

    # Print to stdout (visible in cron logs)
    header = f"Pre-market health check — {TODAY} 05:45 UTC"
    print(header)
    print("-" * len(header))
    for r in results:
        print(r)

    if all_failures:
        # Build Telegram alert
        lines = [f"<b>Pre-Market Health Check FAILED</b>", f"<code>{TODAY}</code>", ""]
        for name, fails in all_failures:
            lines.append(f"<b>{name}:</b>")
            for f in fails:
                lines.append(f"  {f}")
            lines.append("")
        lines.append("Fix before London open (06:00 UTC)")
        msg = "\n".join(lines)
        print(f"\nSending Telegram alert ({len(all_failures)} failed checks)...")
        send_telegram_message(msg)
        print("Alert sent.")
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        send_telegram_message(
            f"<b>Pre-Market Health Check OK</b>\n<code>{TODAY}</code>\nAll {len(checks)} checks passed."
        )
        print("Status sent.")
        sys.exit(0)


if __name__ == "__main__":
    force = "--force" in sys.argv
    run_all_checks(force_send=force)
