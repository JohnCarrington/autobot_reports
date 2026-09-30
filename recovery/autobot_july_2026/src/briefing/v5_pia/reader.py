"""briefing.v5_pia.reader — Phase 3 reader.

Loads v5_pia briefing JSON from `BRIEFINGS_V5_DIR`, validates against the
`BriefingV5` Pydantic model, answers staleness against `valid_until_utc`,
and provides convenience predicates the executor uses to decide whether
to act on a briefing.

Independent from v4's `read_briefing.py` per the explicit instruction in
`briefing/v5_pia/PHASE1_README.md`:

    > v5 will need its own reader in Phase 3 — do not extend
    > read_briefing.py.

This module is import-light and pure aside from filesystem reads — no
runtime context required. Callers (executor, tests) can use it from any
thread without locks.

Public API:

  load_v5_briefing(pair, session, date=None, briefings_dir=None)
      Load a single named briefing file. Returns BriefingV5 or None.

  load_active_v5_briefing(pair, now_utc=None, briefings_dir=None)
      Resolve which session's briefing should be active at `now_utc`
      (London <12:30Z, NY otherwise) and load it. Convenience wrapper.

  active_session_for(now_utc)
      Pure: which session is the executor expected to consume right now?

  is_briefing_active(briefing, now_utc=None)
      True when now_utc < briefing.valid_until_utc.

  is_briefing_armed(briefing)
      True when state == 'ARMED' and direction in {BUY, SELL}.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from briefing.v5_pia.config import BRIEFINGS_DIR
from briefing.v5_pia.schema import BriefingV5

logger = logging.getLogger(__name__)


_SessionT = Literal["London", "NY"]


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution
# ─────────────────────────────────────────────────────────────────────────────

def _briefing_path(
    pair: str,
    session: str,
    date: datetime,
    briefings_dir: Optional[Path] = None,
) -> Path:
    """Resolve the canonical filename for a v5 briefing.

    Mirrors `orchestrator._briefing_path` exactly so writer/reader cannot
    drift. Module-level so tests can override the dir without monkey-
    patching the orchestrator.
    """
    base = briefings_dir or BRIEFINGS_DIR
    date_str = date.strftime("%Y-%m-%d")
    return base / f"briefing_{pair.upper()}_{date_str}_{session}.json"


# ─────────────────────────────────────────────────────────────────────────────
# Time-of-day → session resolver
# ─────────────────────────────────────────────────────────────────────────────

def active_session_for(now_utc: Optional[datetime] = None) -> _SessionT:
    """Return the session whose briefing the executor should currently
    be consuming.

    Schedule (mirrors orchestrator + scheduler):
      - London: 05:30Z to 12:30Z
      - NY:     12:30Z to 21:00Z (post-NY-close the briefing is stale)
      - Outside both: returns "London" (caller will load + find it
        stale, then abstain). Choosing a session unambiguously here
        keeps the resolver pure and avoids None-handling in callers.

    The 12:30Z boundary is exclusive on the London side and inclusive on
    the NY side, matching `morning_briefing._SESSIONS_V5` which
    schedules NY to fire AT 12:30Z.
    """
    now_utc = now_utc or datetime.now(tz=timezone.utc)
    h = now_utc.hour
    m = now_utc.minute
    minutes = h * 60 + m
    LONDON_OPEN = 5 * 60 + 30   # 05:30Z
    NY_OPEN     = 12 * 60 + 30  # 12:30Z
    if LONDON_OPEN <= minutes < NY_OPEN:
        return "London"
    return "NY"


# ─────────────────────────────────────────────────────────────────────────────
# Load + validate
# ─────────────────────────────────────────────────────────────────────────────

def load_v5_briefing(
    pair: str,
    session: _SessionT,
    date: Optional[datetime] = None,
    briefings_dir: Optional[Path] = None,
) -> Optional[BriefingV5]:
    """Load + validate a single (pair, session, date) briefing.

    Returns the validated `BriefingV5` instance on success.

    Returns None on:
      - file does not exist
      - file unparseable as JSON
      - JSON does not satisfy the BriefingV5 Pydantic schema (extras
        forbidden, type/enum/cross-field constraints)

    Every failure path emits a single WARNING — the executor must NEVER
    silently consume a malformed briefing, but it must also NEVER raise
    out of the live tick path.

    The default for `date` is `datetime.now(timezone.utc)` so the most
    common executor call (today's London/NY briefing) needs only the
    pair + session.
    """
    when = date or datetime.now(tz=timezone.utc)
    path = _briefing_path(pair, session, when, briefings_dir)

    if not path.exists():
        logger.debug(
            "[v5-reader] %s %s briefing not found at %s", pair, session, path,
        )
        return None

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "[v5-reader] %s %s briefing unreadable %s: %s: %s",
            pair, session, path, type(exc).__name__, exc,
        )
        return None

    try:
        return BriefingV5(**raw)
    except Exception as exc:  # Pydantic ValidationError + any unexpected
        logger.warning(
            "[v5-reader] %s %s briefing failed schema validation %s: %s: %s",
            pair, session, path, type(exc).__name__, exc,
        )
        return None


def load_active_v5_briefing(
    pair: str,
    now_utc: Optional[datetime] = None,
    briefings_dir: Optional[Path] = None,
) -> Optional[BriefingV5]:
    """Convenience: load the briefing for the session active right now.

    Returns the briefing (validated) or None when no usable briefing
    exists for `pair` at `now_utc`.
    """
    when = now_utc or datetime.now(tz=timezone.utc)
    session = active_session_for(when)
    return load_v5_briefing(pair, session, when, briefings_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Predicates
# ─────────────────────────────────────────────────────────────────────────────

def _parse_iso_utc(s: str) -> Optional[datetime]:
    """Parse `BriefingV5.valid_until_utc` shape. The producer writes
    ISO 8601 with explicit 'Z' suffix (`%Y-%m-%dT%H:%M:%SZ`); accept that
    plus standard ISO with offset for forward compatibility."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        # 'Z' suffix is not parsed by fromisoformat in Python <3.11 — coerce.
        normalized = s.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def is_briefing_active(
    briefing: BriefingV5, now_utc: Optional[datetime] = None,
) -> bool:
    """True when `now_utc` is strictly before the briefing's `valid_until_utc`.

    A briefing whose `valid_until_utc` cannot be parsed is treated as
    inactive (refuse to fire on a malformed timestamp rather than
    interpret silently). The Pydantic schema doesn't enforce a parseable
    timestamp shape today — the producer always writes the canonical
    'Z'-suffixed format, but treat external shape as untrusted.
    """
    when = now_utc or datetime.now(tz=timezone.utc)
    valid_until = _parse_iso_utc(briefing.valid_until_utc)
    if valid_until is None:
        logger.warning(
            "[v5-reader] %s %s valid_until_utc=%r unparseable — treating as inactive",
            briefing.pair, briefing.session, briefing.valid_until_utc,
        )
        return False
    return when < valid_until


def is_briefing_armed(briefing: BriefingV5) -> bool:
    """True when the briefing represents a tradeable, committed signal.

    Both gates required:
      - state == 'ARMED' (the producer's state-machine transition from
        bucket; STAND_ASIDE briefings are never tradeable)
      - direction in {'BUY', 'SELL'} (defensive; orchestrator forces
        STAND_ASIDE direction whenever state != ARMED but check both
        independently in case of future producer changes)
    """
    return briefing.state == "ARMED" and briefing.direction in ("BUY", "SELL")
