#!/usr/bin/env python3
"""env_drift_check.py — boot-time .env drift alert (ITEM 1).

Compares the two most recent snapshots in /opt/tradingbot/env-history/
(populated by autobot.service.d/env-history.conf ExecStartPre). On any
drift, emits ONE Telegram containing variable NAMES only (never values).

Design rules:
- ExecStartPre step. Runs as `autobot`, before autobot.py starts.
- Entire body wrapped: any exception -> log to env_drift.log, exit 0.
  MUST NOT block boot.
- No prior snapshot -> INFO log, no alert.
- No drift -> silence.
- Names capped at 15 per category with "+N more" suffix.
- Telegram token/chat read directly from /opt/tradingbot/.env, not from
  environment (this runs pre-app; systemd EnvironmentFile is present at
  ExecStartPre but we do not rely on it — parsing the file is more
  robust to future unit changes).
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

ENV_HISTORY_DIR = Path("/opt/tradingbot/env-history")
ENV_FILE = Path("/opt/tradingbot/.env")
LOG_FILE = Path("/opt/tradingbot/logs/env_drift.log")
MAX_NAMES_PER_CATEGORY = 15


def _configure_logger() -> logging.Logger:
    log = logging.getLogger("env_drift_check")
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(LOG_FILE)
    except Exception:
        fh = logging.StreamHandler(sys.stderr)
    fh.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
    log.addHandler(fh)
    return log


def _parse_env(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n").rstrip("\r")
            s = line.lstrip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("export "):
                s = s[len("export "):]
            eq = s.find("=")
            if eq <= 0:
                continue
            k = s[:eq].strip()
            v = s[eq + 1:]
            if (len(v) >= 2) and (
                (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")
            ):
                v = v[1:-1]
            out[k] = v
    return out


def _two_latest_snapshots(dirpath: Path) -> Tuple[Path, Path] | None:
    try:
        files = sorted(dirpath.glob("env.*"))
    except Exception:
        return None
    if len(files) < 2:
        return None
    return files[-2], files[-1]


def _diff(
    prev: Dict[str, str], curr: Dict[str, str]
) -> Tuple[List[str], List[str], List[str]]:
    prev_keys = set(prev.keys())
    curr_keys = set(curr.keys())
    added = sorted(curr_keys - prev_keys)
    removed = sorted(prev_keys - curr_keys)
    changed = sorted(k for k in (prev_keys & curr_keys) if prev[k] != curr[k])
    return changed, added, removed


def _fmt_name_list(names: List[str]) -> str:
    if not names:
        return "-"
    if len(names) <= MAX_NAMES_PER_CATEGORY:
        return ", ".join(names)
    shown = ", ".join(names[:MAX_NAMES_PER_CATEGORY])
    return f"{shown}, +{len(names) - MAX_NAMES_PER_CATEGORY} more"


def _build_message(
    host_label: str,
    changed: List[str],
    added: List[str],
    removed: List[str],
) -> str:
    prefix = f"[{host_label}] " if host_label else ""
    return (
        f"{prefix}CONFIG DRIFT at boot: "
        f"{len(changed)} changed ({_fmt_name_list(changed)}), "
        f"{len(removed)} removed ({_fmt_name_list(removed)}), "
        f"{len(added)} added ({_fmt_name_list(added)})"
    )


def _send_telegram(env: Dict[str, str], text: str, log: logging.Logger) -> None:
    token = (env.get("TELEGRAM_TOKEN") or "").strip()
    chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        log.warning(
            "drift detected but TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing "
            "from %s; not sending",
            ENV_FILE,
        )
        return
    try:
        import requests  # local import; avoids failing script on stripped venvs
    except Exception as e:
        log.warning("requests import failed: %s: %s", type(e).__name__, e)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code != 200:
            log.warning("telegram returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("telegram send raised %s: %s", type(e).__name__, e)


def _run() -> None:
    log = _configure_logger()
    pair = _two_latest_snapshots(ENV_HISTORY_DIR)
    if pair is None:
        log.info("no prior snapshot available; skipping drift check")
        return
    prev_path, curr_path = pair
    prev = _parse_env(prev_path)
    curr = _parse_env(curr_path)
    changed, added, removed = _diff(prev, curr)
    if not (changed or added or removed):
        log.info(
            "no drift between %s and %s", prev_path.name, curr_path.name
        )
        return
    log.warning(
        "drift between %s and %s: changed=%d added=%d removed=%d",
        prev_path.name, curr_path.name, len(changed), len(added), len(removed),
    )
    live_env = _parse_env(ENV_FILE) if ENV_FILE.exists() else {}
    host_label = (live_env.get("ALERT_HOST_LABEL") or "").strip()
    msg = _build_message(host_label, changed, added, removed)
    _send_telegram(live_env, msg, log)


def main() -> int:
    try:
        _run()
    except Exception:
        try:
            log = _configure_logger()
            log.error("env_drift_check crashed: %s", traceback.format_exc())
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
