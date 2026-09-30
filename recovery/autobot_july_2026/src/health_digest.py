#!/usr/bin/env python3
"""health_digest.py — hourly Telegram digest of the last 12 health cycles.

Runs at HH:00 UTC via health-digest.timer. Reads the tail of
logs/health_cycles.jsonl, aggregates the last 12 entries (= last hour at
5-min cadence), and POSTs a single Telegram message via
telegram_alerts.send_telegram_message.

Format:
    🤖 health digest — AutoBotV1 — HH:00→HH:00 UTC — session=OPEN
    overall: AMBER (RED=0 AMBER=4 GREEN=8 SUPPR=0 UNK=0)
    buffer_depth_GBPUSD : 12G               value=244
    buffer_depth_EURUSD : 12G               value=243
    close_cadence_GBPUSD: 12G               value=92s
    close_cadence_EURUSD: 12G               value=92s
    tick_age_GBPUSD     : 12G               value=2s
    tick_age_EURUSD     : 12G               value=4s
    indicator_sanity_GBPUSD: 8G 4A          adx=16.8 [breach 17:25→17:40]
    indicator_sanity_EURUSD: 8G 4A          adx=20.8 [breach 17:25→17:40]
    rest_allowance     : 12G                remaining=5166
    crash_loop         : 12G                nrestarts=0

Knobs:
    HEALTH_DIGEST_SKIP_CLOSED  default 1 — suppress digest when session
                                            is CLOSED (weekend / Fri eve
                                            / Sun pre-open).
    HEALTH_DIGEST_DRY_RUN      default 0 — print to stdout instead of
                                            posting to Telegram. Useful
                                            for manual validation.

No new listening port: reads logs + outbound HTTPS (Telegram) only.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/tradingbot")
CYCLES_LOG = ROOT / "logs" / "health_cycles.jsonl"

DIGEST_WINDOW_CYCLES = 12  # last hour at 5-min cadence


def _is_fx_session_closed(ts: datetime) -> bool:
    try:
        wd = ts.weekday()
        if wd == 5:
            return True
        if wd == 4 and ts.hour >= 21:
            return True
        if wd == 6 and ts.hour < 20:
            return True
        return False
    except Exception:
        return False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_last_cycles(n: int) -> list:
    if not CYCLES_LOG.exists():
        return []
    try:
        with CYCLES_LOG.open("rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            # Each cycle ~1.5KB; read enough trailing bytes for ~2x headroom
            f.seek(max(0, sz - 60 * 1024))
            data = f.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in data.splitlines() if ln.strip()]
        cycles: list = []
        for ln in lines[-n:]:
            try:
                cycles.append(json.loads(ln))
            except Exception:
                continue
        return cycles
    except Exception:
        return []


def _parse_iso(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _short_hm(s):
    ts = _parse_iso(s)
    return ts.strftime("%H:%M") if ts else "??:??"


def _format_value(latest_signal: dict) -> str:
    """Single-line `key=value` summary for the rightmost column."""
    if latest_signal is None:
        return "value=?"
    parts: list = []
    for k in ("value", "value_secs", "adx", "remaining", "nrestarts"):
        if k in latest_signal and latest_signal[k] is not None:
            v = latest_signal[k]
            if k == "value_secs":
                parts.append(f"value={int(round(v))}s")
            elif k == "adx":
                parts.append(f"adx={v:.1f}")
            elif k == "remaining":
                parts.append(f"remaining={v}")
            elif k == "nrestarts":
                parts.append(f"nrestarts={v}")
            else:
                parts.append(f"value={v}")
            break
    if not parts:
        # fallback to a flags summary if available
        flags = latest_signal.get("flags") or []
        if flags:
            parts.append(",".join(flags))
        else:
            parts.append("value=?")
    return " ".join(parts)


def _breach_window(cycles: list, sig_name: str) -> str:
    """Time-window of any non-GREEN state in the cycle list."""
    breach_ts = [
        _parse_iso(c["ts"])
        for c in cycles
        if c["signals"].get(sig_name, {}).get("state") in ("RED", "AMBER")
    ]
    breach_ts = [t for t in breach_ts if t is not None]
    if not breach_ts:
        return ""
    lo, hi = min(breach_ts), max(breach_ts)
    if lo == hi:
        return f" [breach {lo.strftime('%H:%M')}]"
    return f" [breach {lo.strftime('%H:%M')}→{hi.strftime('%H:%M')}]"


def build_digest(cycles: list) -> str:
    host = socket.gethostname()
    now = _now_utc()

    if not cycles:
        return (f"🤖 health digest — {host} — no cycles in "
                f"{CYCLES_LOG} yet (window={DIGEST_WINDOW_CYCLES} cycles)")

    first_ts = _parse_iso(cycles[0]["ts"])
    last_ts = _parse_iso(cycles[-1]["ts"])
    window_str = f"{_short_hm(cycles[0]['ts'])}→{_short_hm(cycles[-1]['ts'])} UTC"
    session = cycles[-1].get("session_state", "?")

    # Overall counts across the window
    counts = {"RED": 0, "AMBER": 0, "GREEN": 0, "SUPPRESSED": 0, "UNKNOWN": 0}
    for c in cycles:
        s = c.get("overall", "UNKNOWN")
        counts[s] = counts.get(s, 0) + 1
    if counts["RED"] > 0:
        overall = "RED"
    elif counts["AMBER"] > 0:
        overall = "AMBER"
    elif counts["SUPPRESSED"] == len(cycles):
        overall = "SUPPRESSED"
    else:
        overall = "GREEN"

    n = len(cycles)
    header = (
        f"🤖 health digest — {host} — {window_str} "
        f"— session={session} — cycles={n}/{DIGEST_WINDOW_CYCLES}"
    )
    overall_line = (
        f"overall: {overall} "
        f"(RED={counts['RED']} AMBER={counts['AMBER']} "
        f"GREEN={counts['GREEN']} SUPPR={counts['SUPPRESSED']} "
        f"UNK={counts['UNKNOWN']})"
    )

    # Collect every signal name in cycle order seen
    sig_names: list = []
    seen: set = set()
    for c in cycles:
        for k in c.get("signals", {}).keys():
            if k not in seen:
                seen.add(k)
                sig_names.append(k)

    rows: list = []
    for sig in sig_names:
        per_state = {"RED": 0, "AMBER": 0, "GREEN": 0, "SUPPRESSED": 0, "UNKNOWN": 0}
        latest = None
        for c in cycles:
            s = c.get("signals", {}).get(sig)
            if s is None:
                per_state["UNKNOWN"] += 1
                continue
            per_state[s.get("state", "UNKNOWN")] = per_state.get(s.get("state", "UNKNOWN"), 0) + 1
            latest = s
        # short count format e.g. "8G 4A" — drop zeros
        order = [("RED", "R"), ("AMBER", "A"), ("SUPPRESSED", "S"),
                 ("UNKNOWN", "U"), ("GREEN", "G")]
        count_bits = [f"{per_state[k]}{tag}" for k, tag in order if per_state[k] > 0]
        breach = _breach_window(cycles, sig)
        rows.append(f"{sig}: {' '.join(count_bits)}  {_format_value(latest)}{breach}")

    # Pierce-alert failure counter (daily rolling, from autobot's send-guard).
    # Non-zero indicates the pierce-alert Telegram path is broken; zero is the
    # steady state on a healthy day.
    try:
        sys.path.insert(0, str(ROOT))
        from pierce_alert_counter import read_count as _pa_read  # type: ignore
        _pa_date, _pa_ct = _pa_read()
        rows.append(f"pierce_alert_errors: {_pa_ct} (date={_pa_date})")
    except Exception as _pa_exc:
        rows.append(f"pierce_alert_errors: ? ({type(_pa_exc).__name__})")

    body = "\n".join(rows)
    return header + "\n" + overall_line + "\n" + body


def _send_telegram(text: str) -> tuple:
    """Returns (ok: bool, info: str)."""
    if (os.getenv("HEALTH_DIGEST_DRY_RUN", "0") or "0").strip().lower() in ("1", "true", "yes"):
        print(text)
        return True, "dry_run_printed"
    try:
        sys.path.insert(0, str(ROOT))
        from telegram_alerts import send_telegram_message  # type: ignore
        # wait=True so this oneshot blocks until delivery (or timeout)
        send_telegram_message(text, wait=True)
        return True, "sent"
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"


def main() -> int:
    skip_closed = (os.getenv("HEALTH_DIGEST_SKIP_CLOSED", "1") or "1").strip().lower() in ("1", "true", "yes")
    now = _now_utc()
    closed = _is_fx_session_closed(now)
    if skip_closed and closed:
        print(f"[health_digest] session=CLOSED and HEALTH_DIGEST_SKIP_CLOSED=1 — skipping")
        return 0
    cycles = _read_last_cycles(DIGEST_WINDOW_CYCLES)
    text = build_digest(cycles)
    ok, info = _send_telegram(text)
    print(f"[health_digest] send ok={ok} info={info} cycles_used={len(cycles)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
