#!/usr/bin/env python3
"""health_check.py — one cycle of autobot functional health checks.

Runs every 5 min via health-check.timer. Reads journalctl -u autobot and
the regime_engine.jsonl log; emits ONE JSON line to
/opt/tradingbot/logs/health_cycles.jsonl. Companion health_digest.py
aggregates cycles into an hourly Telegram digest.

Session-aware: signals still log inside FX-closed windows but are never
counted as RED/AMBER (so the overall verdict goes GREEN over the weekend
without zero-ing out the underlying metrics).

Optional immediate-RED push: HEALTH_MONITOR_IMMEDIATE_RED_ENABLED=1
fires a one-line Telegram message the first cycle a signal flips to
RED, debounced once per 30 min per reason. Default OFF.

No new listening port: reads logs + outbound HTTPS (Telegram) only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/tradingbot")
CYCLES_LOG = ROOT / "logs" / "health_cycles.jsonl"
HEARTBEAT_LOG = ROOT / "logs" / "health_heartbeat.log"
DEBOUNCE_STATE = ROOT / "cache" / "health_monitor_debounce.json"
NRESTARTS_SNAP = ROOT / "cache" / "health_monitor_nrestarts.json"
REGIME_LOG = ROOT / "logs" / "regime_engine.jsonl"
REST_ALLOWANCE_FILE = ROOT / "cache" / "rest_allowance.json"

HEARTBEAT_TIMEOUT_SECS = 5.0

SYMBOLS = ["GBPUSD", "EURUSD"]

BUFFER_DEPTH_RED = 60          # closed_rows in 5M buffer
CLOSE_CADENCE_RED = 390        # secs since last [5M CLOSE]
TICK_AGE_RED = 180             # secs since last [SYM] TICK
INDICATOR_PINNED_LO = 0.5
INDICATOR_PINNED_HI = 99.0
REST_ALLOWANCE_AMBER = 1000

JOURNAL_WINDOW = "-15min"
IMMEDIATE_RED_DEBOUNCE_MINS = 30


# ─── session helper (copy of autobot._is_fx_session_closed) ──────────
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


# ─── journal helpers ─────────────────────────────────────────────────
_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _read_journal(since: str = JOURNAL_WINDOW) -> list:
    try:
        r = subprocess.run(
            ["journalctl", "-u", "autobot", "--since", since, "--no-pager"],
            capture_output=True, text=True, timeout=15
        )
        return r.stdout.splitlines()
    except Exception:
        return []


def _parse_journal_ts(line: str) -> "datetime | None":
    m = re.match(r"^(\w{3})\s+(\d+)\s+(\d{2}):(\d{2}):(\d{2})\s", line)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1))
    if not mon:
        return None
    now = _now_utc()
    try:
        ts = datetime(now.year, mon, int(m.group(2)),
                      int(m.group(3)), int(m.group(4)), int(m.group(5)),
                      tzinfo=timezone.utc)
        if ts > now + timedelta(hours=12):
            ts = ts.replace(year=now.year - 1)
        return ts
    except Exception:
        return None


# ─── checks ──────────────────────────────────────────────────────────
_PAT_CLOSED_ROWS = re.compile(r"\[5M CLOSE\]\s+(\w+)\s+.*closed_rows=(\d+)")
_PAT_PRELOAD = re.compile(r"\[PRELOAD-INJECT\]\s+\[(\w+)\]\s+builder_rows=(\d+)")


def check_buffer_depth(journal: list) -> dict:
    latest: dict = {}
    for line in journal:
        m = _PAT_CLOSED_ROWS.search(line) or _PAT_PRELOAD.search(line)
        if not m:
            continue
        sym = m.group(1)
        depth = int(m.group(2))
        ts = _parse_journal_ts(line)
        cur = latest.get(sym)
        if cur is None or (ts and (cur[0] is None or ts > cur[0])):
            latest[sym] = (ts, depth)
    return {sym: latest[sym][1] for sym in latest}


def check_close_cadence(journal: list, sym: str) -> "float | None":
    pat = re.compile(rf"\[5M CLOSE\]\s+{sym}\b")
    last_ts = None
    for line in journal:
        if pat.search(line):
            ts = _parse_journal_ts(line)
            if ts and (last_ts is None or ts > last_ts):
                last_ts = ts
    return None if last_ts is None else (_now_utc() - last_ts).total_seconds()


def check_tick_age(journal: list, sym: str) -> "float | None":
    pat = re.compile(rf"\[{sym}\]\s+TICK\s+bid=")
    last_ts = None
    for line in journal:
        if pat.search(line):
            ts = _parse_journal_ts(line)
            if ts and (last_ts is None or ts > last_ts):
                last_ts = ts
    return None if last_ts is None else (_now_utc() - last_ts).total_seconds()


def check_indicator_sanity() -> dict:
    out: dict = {}
    if not REGIME_LOG.exists():
        return out
    try:
        with REGIME_LOG.open("rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 200_000))
            data = f.read().decode("utf-8", errors="ignore")
        lines = data.splitlines()
        per: dict = {}
        for line in lines:
            try:
                d = json.loads(line)
                sym = d.get("symbol")
                if not sym:
                    continue
                per.setdefault(sym, []).append(d)
            except Exception:
                continue
        for sym, entries in per.items():
            if not entries:
                continue
            latest = entries[-1]
            adx = latest.get("ADX")
            try:
                adx = float(adx) if adx is not None else None
            except Exception:
                adx = None
            adx_pinned = (
                adx is not None
                and (adx <= INDICATOR_PINNED_LO or adx >= INDICATOR_PINNED_HI)
            )
            out[sym] = {
                "adx": adx,
                "adx_pinned": adx_pinned,
                "regime_label": latest.get("winning_regime"),
            }
    except Exception:
        pass
    return out


def check_rest_allowance() -> "int | None":
    if not REST_ALLOWANCE_FILE.exists():
        return None
    try:
        with REST_ALLOWANCE_FILE.open("r") as f:
            state = json.load(f)
        return int(state.get("points_budget", 0)) - int(state.get("points_used", 0))
    except Exception:
        return None


def check_crash_loop() -> tuple:
    cur = None
    try:
        r = subprocess.run(
            ["systemctl", "show", "autobot", "--property=NRestarts"],
            capture_output=True, text=True, timeout=5
        )
        cur = int(r.stdout.strip().split("=", 1)[1])
    except Exception:
        return None, None, False
    prev = None
    try:
        if NRESTARTS_SNAP.exists():
            with NRESTARTS_SNAP.open("r") as f:
                prev = json.load(f).get("nrestarts")
    except Exception:
        prev = None
    try:
        NRESTARTS_SNAP.parent.mkdir(parents=True, exist_ok=True)
        with NRESTARTS_SNAP.open("w") as f:
            json.dump({"nrestarts": cur, "ts": _now_utc().isoformat()}, f)
    except Exception:
        pass
    return cur, prev, bool(prev is not None and cur > prev)


# ─── alert (immediate-RED) ───────────────────────────────────────────
def _immediate_red_enabled() -> bool:
    return (os.getenv("HEALTH_MONITOR_IMMEDIATE_RED_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes")


def _load_debounce() -> dict:
    if not DEBOUNCE_STATE.exists():
        return {}
    try:
        with DEBOUNCE_STATE.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_debounce(state: dict) -> None:
    try:
        DEBOUNCE_STATE.parent.mkdir(parents=True, exist_ok=True)
        with DEBOUNCE_STATE.open("w") as f:
            json.dump(state, f)
    except Exception:
        pass


def _push_immediate_red(reason: str) -> bool:
    if not _immediate_red_enabled():
        return False
    state = _load_debounce()
    last_iso = state.get(reason)
    now = _now_utc()
    if last_iso:
        try:
            last = datetime.fromisoformat(last_iso)
            if (now - last).total_seconds() < IMMEDIATE_RED_DEBOUNCE_MINS * 60:
                return False
        except Exception:
            pass
    try:
        sys.path.insert(0, str(ROOT))
        from telegram_alerts import send_telegram_message  # type: ignore
        send_telegram_message(f"🚨 [health_check] RED: {reason}")
        state[reason] = now.isoformat()
        _save_debounce(state)
        return True
    except Exception:
        return False


# ─── verdict builder ─────────────────────────────────────────────────
def build_cycle() -> dict:
    now = _now_utc()
    closed = _is_fx_session_closed(now)
    journal = _read_journal()

    # Helper: a signal's "raw" state — what it would be ignoring session.
    # If session is CLOSED, all RED/AMBER raw states are downgraded to
    # SUPPRESSED for the cycle's effective verdict, but the raw value is
    # still logged.
    def effective(state):
        return "SUPPRESSED" if closed and state in ("RED", "AMBER") else state

    signals: dict = {}
    red_reasons: list = []  # for immediate-RED push (only effective RED)

    # 1) buffer_depth
    buf = check_buffer_depth(journal)
    for sym in SYMBOLS:
        d = buf.get(sym)
        if d is None:
            signals[f"buffer_depth_{sym}"] = {"state": "UNKNOWN", "value": None,
                                              "threshold": f"<{BUFFER_DEPTH_RED}"}
            continue
        raw = "RED" if d < BUFFER_DEPTH_RED else "GREEN"
        eff = effective(raw)
        signals[f"buffer_depth_{sym}"] = {"state": eff, "raw": raw, "value": d,
                                          "threshold": f"<{BUFFER_DEPTH_RED}"}
        if eff == "RED":
            red_reasons.append(f"buffer_depth({sym}={d}<{BUFFER_DEPTH_RED})")

    # 2) close_cadence
    for sym in SYMBOLS:
        age = check_close_cadence(journal, sym)
        if age is None:
            signals[f"close_cadence_{sym}"] = {"state": "UNKNOWN", "value": None,
                                               "threshold": f">{CLOSE_CADENCE_RED}s"}
            continue
        raw = "RED" if age > CLOSE_CADENCE_RED else "GREEN"
        eff = effective(raw)
        signals[f"close_cadence_{sym}"] = {"state": eff, "raw": raw,
                                           "value_secs": round(age, 1),
                                           "threshold": f">{CLOSE_CADENCE_RED}s"}
        if eff == "RED":
            red_reasons.append(f"close_cadence({sym}={age:.0f}s>{CLOSE_CADENCE_RED}s)")

    # 3) tick_age
    for sym in SYMBOLS:
        age = check_tick_age(journal, sym)
        if age is None:
            signals[f"tick_age_{sym}"] = {"state": "UNKNOWN", "value": None,
                                          "threshold": f">{TICK_AGE_RED}s"}
            continue
        raw = "RED" if age > TICK_AGE_RED else "GREEN"
        eff = effective(raw)
        signals[f"tick_age_{sym}"] = {"state": eff, "raw": raw,
                                      "value_secs": round(age, 1),
                                      "threshold": f">{TICK_AGE_RED}s"}
        if eff == "RED":
            red_reasons.append(f"tick_age({sym}={age:.0f}s>{TICK_AGE_RED}s)")

    # 4) indicator_sanity (AMBER only) — ADX pinned at warmup-garbage values.
    # The "regime label identical for N cycles" clause was removed
    # 2026-06-15: a stable regime is healthy trend persistence, not a
    # fault. Warmup is still covered by buffer_depth + ADX-pinned.
    sanity = check_indicator_sanity()
    for sym in SYMBOLS:
        s = sanity.get(sym)
        if not s:
            signals[f"indicator_sanity_{sym}"] = {
                "state": "UNKNOWN", "value": None,
                "threshold": f"ADX<={INDICATOR_PINNED_LO}|>={INDICATOR_PINNED_HI}",
            }
            continue
        flags: list = []
        if s["adx_pinned"]:
            flags.append(f"adx_pinned(={s['adx']:.1f})")
        raw = "AMBER" if flags else "GREEN"
        eff = effective(raw)
        signals[f"indicator_sanity_{sym}"] = {
            "state": eff, "raw": raw,
            "adx": s["adx"],
            "regime_label": s.get("regime_label"),
            "flags": flags,
            "threshold": f"ADX<={INDICATOR_PINNED_LO}|>={INDICATOR_PINNED_HI}",
        }

    # 5) rest_allowance (AMBER only)
    rem = check_rest_allowance()
    if rem is None:
        signals["rest_allowance"] = {"state": "UNKNOWN", "value": None,
                                     "threshold": f"<{REST_ALLOWANCE_AMBER}"}
    else:
        raw = "AMBER" if rem < REST_ALLOWANCE_AMBER else "GREEN"
        eff = effective(raw)
        signals["rest_allowance"] = {"state": eff, "raw": raw, "remaining": rem,
                                     "threshold": f"<{REST_ALLOWANCE_AMBER}"}

    # 6) crash_loop
    cur, prev, climbing = check_crash_loop()
    raw = "RED" if climbing else "GREEN" if cur is not None else "UNKNOWN"
    eff = effective(raw) if raw != "UNKNOWN" else "UNKNOWN"
    signals["crash_loop"] = {"state": eff, "raw": raw,
                             "nrestarts": cur, "prev": prev,
                             "threshold": "NRestarts climbing"}
    if eff == "RED":
        red_reasons.append(f"crash_loop(nrestarts:{prev}->{cur})")

    # Overall = worst effective state across all signals
    rank = {"RED": 3, "AMBER": 2, "SUPPRESSED": 1, "GREEN": 0, "UNKNOWN": 0}
    worst = "GREEN"
    for s in signals.values():
        if rank.get(s.get("state"), 0) > rank.get(worst, 0):
            worst = s["state"]
    # SUPPRESSED never becomes the headline — that just means session closed
    if worst == "SUPPRESSED":
        worst = "GREEN"

    cycle = {
        "ts": now.isoformat(),
        "session_state": "CLOSED" if closed else "OPEN",
        "overall": worst,
        "signals": signals,
    }

    # Optional immediate-RED Telegram push
    for reason in red_reasons:
        _push_immediate_red(reason)

    return cycle


def _send_heartbeat_and_log() -> None:
    """Dead-man's-switch heartbeat — fires unconditionally each cycle.

    Behaviour:
      * HEARTBEAT_PING_URL unset → one "skipped reason=no_url" line in
        HEARTBEAT_LOG, no network I/O.
      * URL set → single requests.get with HEARTBEAT_TIMEOUT_SECS
        timeout. Wrapped so ANY failure / timeout / exception is
        swallowed; cannot delay or break the cycle.
      * Either way, exactly one line is appended to HEARTBEAT_LOG so a
        silently-misconfigured monitor is visible.
    Independent of verdict (GREEN/AMBER/RED) and session (OPEN/CLOSED)."""
    now_iso = _now_utc().isoformat()
    url = (os.getenv("HEARTBEAT_PING_URL", "") or "").strip()
    if not url:
        line = f"{now_iso} heartbeat=skipped reason=no_url"
    else:
        try:
            import requests  # codebase standard (telegram_alerts, briefing_emailer)
            r = requests.get(
                url,
                timeout=HEARTBEAT_TIMEOUT_SECS,
                headers={"User-Agent": "autobot-health-monitor/1.0"},
            )
            status = "ok" if 200 <= int(r.status_code) < 300 else "failed"
            line = f"{now_iso} heartbeat={status} reason=http_{r.status_code}"
        except Exception as e:
            line = f"{now_iso} heartbeat=failed reason={type(e).__name__}:{e}"
    try:
        HEARTBEAT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with HEARTBEAT_LOG.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def main() -> int:
    cycle = build_cycle()
    CYCLES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CYCLES_LOG.open("a") as f:
        f.write(json.dumps(cycle) + "\n")
    print(json.dumps(cycle))
    # Dead-man's-switch heartbeat — runs AFTER the cycle JSONL is
    # persisted, so a ping hang/failure can never delay or break the
    # health record. Unconditional: independent of verdict and session.
    _send_heartbeat_and_log()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
