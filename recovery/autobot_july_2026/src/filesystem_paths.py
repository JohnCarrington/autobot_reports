"""Canonical output-directory list for autobot.

Single source of truth for every directory the bot writes to during
normal operation. Both autobot.py (boot-time create + probe) and
scripts/init_filesystem.sh read this list, so adding a new output
directory is a one-line change here.

Two helpers run at startup, in order:

  1. ensure_output_directories() — create missing dirs (mode 0o775),
     chown to autobot:autobot if running as root, WARN on existing
     dirs with wrong owner.

  2. verify_output_directories_writable() — write/read/delete a
     sentinel file in each dir. On failure: ERROR + Telegram +
     sys.exit(1). Service refuses to start with broken filesystem.

Why two passes: ensure_* is best-effort and never crashes (a chown
failure on a non-root run is fine, ownership might already be right).
verify_* is the load-bearing check — it exercises the actual write
path autobot will use seconds later.
"""
from __future__ import annotations

import grp
import logging
import os
import pwd
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger("AutoBot")

BASE_DIR = Path(__file__).resolve().parent

# Directories the bot writes to during normal operation.
# Parents must come before children — mkdir(parents=True) is set, but
# the WARNING-on-wrong-owner check inspects each entry independently.
OUTPUT_DIRECTORIES: List[Path] = [
    BASE_DIR / "briefings",
    BASE_DIR / "briefings" / "v5_pia",
    BASE_DIR / "cache",
    BASE_DIR / "logs",
]

DIR_MODE = 0o775
AUTOBOT_USER = "autobot"
AUTOBOT_GROUP = "autobot"


def _resolve_target_uid_gid() -> tuple[Optional[int], Optional[int]]:
    try:
        uid = pwd.getpwnam(AUTOBOT_USER).pw_uid
        gid = grp.getgrnam(AUTOBOT_GROUP).gr_gid
        return uid, gid
    except KeyError:
        return None, None


def _name_for_uid(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _name_for_gid(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def ensure_output_directories(dirs: Optional[Iterable[Path]] = None) -> None:
    """Create output directories with correct ownership at startup.

    - Missing dirs: created (mode 0o775). If running as root, chowned
      to autobot:autobot.
    - Existing dirs with wrong owner: WARNING only — no auto-fix.
      Auto-chown of an existing dir could mask a real issue (e.g. a
      sibling tool depositing files as root). Operator runs
      scripts/init_filesystem.sh as root to fix.
    - Stat / chown failures are logged at WARNING and never crash
      startup; verify_output_directories_writable() is the gate that
      decides whether the bot can actually run.
    """
    dirs = list(dirs) if dirs is not None else OUTPUT_DIRECTORIES
    target_uid, target_gid = _resolve_target_uid_gid()
    running_as_root = (os.geteuid() == 0)

    for d in dirs:
        existed = d.exists()
        try:
            d.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("[boot-fs] mkdir %s failed: %s", d, exc)
            continue

        if existed:
            if target_uid is None:
                continue
            try:
                st = d.stat()
            except OSError as exc:
                logger.warning("[boot-fs] could not stat %s: %s", d, exc)
                continue
            if st.st_uid != target_uid or st.st_gid != target_gid:
                logger.warning(
                    "[boot-fs] %s exists with owner %s:%s (expected %s:%s) — "
                    "run scripts/init_filesystem.sh as root to fix",
                    d,
                    _name_for_uid(st.st_uid),
                    _name_for_gid(st.st_gid),
                    AUTOBOT_USER,
                    AUTOBOT_GROUP,
                )
            continue

        # Newly-created dir: chown only if we're root and the target
        # account exists. Non-root run already created the dir as
        # ourselves, which is the right owner if the service runs as
        # autobot.
        if running_as_root and target_uid is not None:
            try:
                os.chown(d, target_uid, target_gid)
            except OSError as exc:
                logger.warning("[boot-fs] chown %s failed: %s", d, exc)


def verify_output_directories_writable(
    dirs: Optional[Iterable[Path]] = None,
    *,
    telegram_send: Optional[Callable[[str], None]] = None,
    exit_fn: Optional[Callable[[int], None]] = None,
) -> int:
    """Boot-time write probe. Sentinel write → read → unlink in each dir.

    On any failure: ERROR log, Telegram alert, exit(1). The bot refuses
    to start with broken filesystem — caught at deploy time means we
    don't lose another session to ops-hygiene errors.

    telegram_send / exit_fn are injectable for tests. In production
    they default to telegram_alerts.send_telegram_message and sys.exit.
    """
    dirs = list(dirs) if dirs is not None else list(OUTPUT_DIRECTORIES)

    if telegram_send is None:
        def _default_send(msg: str) -> None:
            from telegram_alerts import send_telegram_message
            send_telegram_message(msg, parse_mode="HTML")
        telegram_send = _default_send
    if exit_fn is None:
        exit_fn = sys.exit

    sentinel_name = f".boot_probe_{os.getpid()}_{int(time.time())}"
    for d in dirs:
        probe = d / sentinel_name
        try:
            probe.write_text("ok")
            if probe.read_text() != "ok":
                raise IOError("sentinel readback mismatch")
            probe.unlink()
        except Exception as exc:
            msg = f"{d} not writable: {type(exc).__name__}: {exc}"
            logger.error("[boot-probe] %s", msg)
            try:
                telegram_send(f"🚨 <b>AutoBot boot failure</b>\n[boot-probe] {msg}")
            except Exception as tg_exc:
                logger.error("[boot-probe] telegram alert failed: %s", tg_exc)
            exit_fn(1)
            # In tests, exit_fn is a mock that doesn't terminate; bail
            # out of the loop so subsequent dirs don't keep failing.
            return -1

    logger.info(
        "[boot-probe] all output directories writable: %d dirs verified",
        len(dirs),
    )
    return len(dirs)
