"""
rest_allowance.py — Persistent weekly budget tracker for IG REST historical data.

IG demo accounts allow ~10,000 historical-price points per week. Every REST
price fetch (HTF preload, 5M/1M preload, 5M REST-RECONCILE) draws from the
same pool. This module is the single source of truth: every consumer calls
`consume(points)` before issuing a REST fetch. If the weekly budget would
be exceeded, the call returns False and the caller skips the fetch.

Budget: default 8,000 pts/week (20% safety margin below IG's 10k cap).
Reset:  Monday 00:00 UTC.
State:  /opt/tradingbot/cache/rest_allowance.json
Schema: {"week_start": "YYYY-MM-DD", "points_used": int, "points_budget": int}

Thread-safe via a module-level threading.Lock. Cross-process safe via
fcntl.flock on the on-disk state file.

Public API:
    consume(points)        -> bool     — atomic; True if charged, False if would exceed
    remaining()            -> int
    reset_if_new_week()    -> None     — no-op if already current; safe to call anytime
    get_state()            -> dict     — {week_start, points_used, points_budget, remaining}
    refund(points)         -> None     — give points back (e.g., call aborted before fetch)
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

logger = logging.getLogger("AutoBot")

DEFAULT_BUDGET = int(os.getenv("REST_WEEKLY_BUDGET", "8000"))
ALLOWANCE_FILE = os.getenv(
    "REST_ALLOWANCE_FILE",
    "/opt/tradingbot/cache/rest_allowance.json",
)

_THREAD_LOCK = threading.Lock()


def _current_week_start() -> str:
    """ISO date (YYYY-MM-DD) of this week's Monday 00:00 UTC."""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%Y-%m-%d")


@contextmanager
def _locked_file(mode: str):
    """Open ALLOWANCE_FILE under an exclusive fcntl lock. Creates parent dir
    and file if needed. Yields the file handle."""
    os.makedirs(os.path.dirname(ALLOWANCE_FILE), exist_ok=True)
    # Ensure file exists so we can acquire a lock on it
    try:
        fd = os.open(ALLOWANCE_FILE, os.O_RDWR | os.O_CREAT, 0o644)
        os.close(fd)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    f = open(ALLOWANCE_FILE, mode)
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield f
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()


def _read_state(f) -> Dict:
    """Read state from an already-locked file handle. Applies week rollover."""
    week = _current_week_start()
    budget = DEFAULT_BUDGET
    try:
        f.seek(0)
        raw = f.read()
        state = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError):
        state = {}

    if not isinstance(state, dict) or state.get("week_start") != week:
        state = {"week_start": week, "points_used": 0, "points_budget": budget}
    else:
        state.setdefault("points_used", 0)
        # Budget can be updated via env var at any time
        state["points_budget"] = budget
    return state


def _write_state(f, state: Dict) -> None:
    """Write state to an already-locked file handle (truncate + write)."""
    f.seek(0)
    f.truncate()
    json.dump(state, f)
    f.flush()
    try:
        os.fsync(f.fileno())
    except OSError:
        pass


def reset_if_new_week() -> None:
    """Force a state read, which rolls over the week counter if needed."""
    with _THREAD_LOCK, _locked_file("r+") as f:
        state = _read_state(f)
        _write_state(f, state)


def consume(points: int) -> bool:
    """Atomically charge `points` against this week's budget. Returns True iff
    the budget had headroom (points were deducted) and the caller may proceed
    with the REST fetch. Returns False if the caller must skip."""
    if points <= 0:
        return True
    with _THREAD_LOCK, _locked_file("r+") as f:
        state = _read_state(f)
        used = int(state["points_used"])
        budget = int(state["points_budget"])
        if used + points > budget:
            return False
        state["points_used"] = used + points
        _write_state(f, state)
        return True


def refund(points: int) -> None:
    """Return points to the budget (call aborted before fetch was issued)."""
    if points <= 0:
        return
    with _THREAD_LOCK, _locked_file("r+") as f:
        state = _read_state(f)
        state["points_used"] = max(0, int(state["points_used"]) - points)
        _write_state(f, state)


def persist_ig_allowance(
    remaining: Optional[int],
    total: Optional[int],
    expiry_s: Optional[int],
    observed_at: Optional[int] = None,
) -> bool:
    """Persist the last-seen IG-authoritative allowance figures alongside the
    local counter. Two hosts share IG account REDACTED_IG_ACCT's 10k weekly pool but
    neither can see the other's spend; capturing IG's own figure on every
    fetch is the only cross-host comparison surface we have.

    All-or-nothing: if any of the three IG fields is absent or not coercible
    to a non-negative int, nothing is written and False is returned. This
    method never raises — a malformed allowance block must NEVER fail a
    fetch. Does not touch points_used, points_budget or week_start.
    """
    try:
        r = int(remaining)
        t = int(total)
        e = int(expiry_s)
        if r < 0 or t < 0 or e < 0:
            return False
    except (TypeError, ValueError):
        return False

    ts = int(observed_at) if observed_at is not None else int(time.time())

    try:
        with _THREAD_LOCK, _locked_file("r+") as f:
            state = _read_state(f)
            state["ig_allowance_remaining"] = r
            state["ig_allowance_total"] = t
            state["ig_allowance_expiry_s"] = e
            state["ig_allowance_observed_at"] = ts
            _write_state(f, state)
        return True
    except Exception as _e:
        logger.debug(f"[REST-ALLOWANCE] persist_ig_allowance skipped ({_e})")
        return False


def remaining() -> int:
    """Points left this week."""
    with _THREAD_LOCK, _locked_file("r+") as f:
        state = _read_state(f)
    return max(0, int(state["points_budget"]) - int(state["points_used"]))


def get_state() -> Dict:
    """Full snapshot: {week_start, points_used, points_budget, remaining}."""
    with _THREAD_LOCK, _locked_file("r+") as f:
        state = _read_state(f)
    used = int(state["points_used"])
    budget = int(state["points_budget"])
    return {
        "week_start": state["week_start"],
        "points_used": used,
        "points_budget": budget,
        "remaining": max(0, budget - used),
    }
