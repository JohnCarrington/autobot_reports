"""Cascade-state reader for the Phase 4B regime classifier.

Reads the latest stable cascade label for a pair from
``/opt/tradingbot/logs/regime_shadow.jsonl`` (the Phase 4B classifier's
per-bar audit trail; one row per 5m close per pair). Strategies use this
to gate fires against the cascade and/or to record the cascade label in
forensic_fires.jsonl for the May 19 review.

The shadow log writer is `regime_classifier._write_shadow_row`. Field
contract (mirrors `scripts/cascade_outcome_join.py:load_regime_shadow`):
    ts:      ISO 8601 UTC string
    symbol:  upper-case pair, e.g. "GBPUSD"
    stable:  cascade label ∈ {TREND_UP, TREND_DOWN, RANGE, NEUTRAL} or None

Read path:
  - File opened fresh each call; no in-process cache. A stale read across
    fires is impossible — the file is append-only and the OS pagecache
    handles efficiency.
  - Tail-only scan: seek to end, read back a small chunk (~32 KiB), split
    on newlines, walk from newest to oldest, first match per pair wins.
    Append-only file → no torn writes; a half-written final line is
    skipped via try/except on json.loads.
  - Staleness threshold: cascade age > MAX_AGE_SECONDS treated as missing
    (allow the trade). Rationale: shadow writes one row per 5m bar close;
    > 10 minutes implies the classifier path is stalled (e.g. candle-lag
    incident — memory item `project_candle_lag_recurring.md`). See
    `docs/cascade_accuracy_join_2026-05-12.md` §1 for the cadence audit.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_SHADOW_PATH = "/opt/tradingbot/logs/regime_shadow.jsonl"
ENV_SHADOW_PATH = "REGIME_SHADOW_LOG_PATH"

# > 10 min → classifier path likely stalled; gate becomes inert.
MAX_AGE_SECONDS = 600.0

# Tail-read chunk: ~32 KiB covers ~50+ recent rows across 4 pairs.
_TAIL_CHUNK_BYTES = 32 * 1024

_DIRECTIONAL_BULL = {"TREND_UP"}
_DIRECTIONAL_BEAR = {"TREND_DOWN"}


def _shadow_path() -> Path:
    return Path(os.getenv(ENV_SHADOW_PATH, DEFAULT_SHADOW_PATH))


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _tail_lines(path: Path, chunk_bytes: int = _TAIL_CHUNK_BYTES) -> list[str]:
    """Return up to the last few hundred lines of `path`, newest last.

    Reads a single chunk from the end. Sufficient for shadow log lookups
    (most-recent row per pair sits within a few hundred bytes of EOF).
    """
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            read_from = max(0, size - chunk_bytes)
            fh.seek(read_from)
            blob = fh.read()
    except FileNotFoundError:
        return []
    except Exception:
        return []
    text = blob.decode("utf-8", errors="replace")
    if read_from > 0:
        # First partial line may be truncated — drop it.
        nl = text.find("\n")
        if nl == -1:
            return []
        text = text[nl + 1:]
    return [ln for ln in text.split("\n") if ln]


def read_latest_cascade(
    pair: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[Optional[str], Optional[float]]:
    """Return (cascade_label, cascade_age_seconds) for `pair`.

    `cascade_label` ∈ {TREND_UP, TREND_DOWN, RANGE, NEUTRAL} or None if
    no record is available. `cascade_age_seconds` is the age of that
    record vs `now_utc` (default: now), or None if no record.

    NB: this is a duplicate of the read path in
    `scripts/cascade_outcome_join.py:load_regime_shadow`. The script
    reads the whole file for historical aggregation; this helper reads
    only the tail for live fire-time use. If/when the two paths
    converge, dedupe to one module.
    """
    sym = (pair or "").upper()
    if not sym:
        return (None, None)
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    lines = _tail_lines(_shadow_path())
    for raw in reversed(lines):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if (d.get("symbol") or "").upper() != sym:
            continue
        dt = _parse_iso(d.get("ts"))
        if dt is None:
            continue
        label = d.get("stable")
        age = (now - dt).total_seconds()
        return (label if isinstance(label, str) else None, float(age))
    return (None, None)


def read_latest_cascade_with_confidence(
    pair: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    """Return (cascade_label, shadow_confidence, cascade_age_seconds).

    Same tail-read as :func:`read_latest_cascade` but additionally
    surfaces the shadow row's overall ``shadow_confidence`` field
    (LOW / MED / HIGH — written by regime_classifier). Used by
    confidence-gated strategies (gbpusd_trend) that need to require
    MEDIUM+ before arming.
    """
    sym = (pair or "").upper()
    if not sym:
        return (None, None, None)
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    lines = _tail_lines(_shadow_path())
    for raw in reversed(lines):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if (d.get("symbol") or "").upper() != sym:
            continue
        dt = _parse_iso(d.get("ts"))
        if dt is None:
            continue
        label = d.get("stable")
        conf = d.get("shadow_confidence")
        age = (now - dt).total_seconds()
        return (
            label if isinstance(label, str) else None,
            conf if isinstance(conf, str) else None,
            float(age),
        )
    return (None, None, None)


# Confidence ordering, used by :mod:`gbpusd_trend` to compare a strategy-
# configured minimum confidence threshold against the shadow row's
# ``shadow_confidence`` field. Mirrors ``regime_classifier._order``.
CONFIDENCE_RANK = {"LOW": 0, "MED": 1, "MEDIUM": 1, "HIGH": 2}


def confidence_meets(observed: Optional[str], required: str) -> bool:
    """Return True iff `observed` confidence ≥ `required`.

    Both arguments are case-insensitive. "MEDIUM" and "MED" are aliases
    (regime_classifier emits "MED"; strategy modules use "MEDIUM" for
    readability). Unknown labels rank as 0 (LOW) — defensive, matches
    the gate semantic "absent / unknown is not enough to arm".
    """
    if not observed:
        return False
    o = CONFIDENCE_RANK.get(str(observed).strip().upper(), 0)
    r = CONFIDENCE_RANK.get(str(required).strip().upper(), 0)
    return o >= r


def cascade_disagrees(
    direction: str,
    pair: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], Optional[float]]:
    """Return (disagrees, cascade_label, cascade_age_seconds).

    Agree/disagree rules (mirrors `cascade_outcome_join.cascade_agrees`):
      - LONG  + TREND_DOWN → disagree
      - SHORT + TREND_UP   → disagree
      - All other label values, including NEUTRAL / RANGE / None / stale,
        → not disagree (gate allows the trade).

    `direction` accepts BUY/LONG (treated as LONG) and SELL/SHORT
    (treated as SHORT). Anything else returns disagrees=False.

    Stale rule: cascade older than MAX_AGE_SECONDS is treated as missing
    (label still returned for logging; disagrees=False).
    """
    d = (direction or "").upper()
    if d in ("BUY", "LONG"):
        side = "LONG"
    elif d in ("SELL", "SHORT"):
        side = "SHORT"
    else:
        return (False, None, None)

    label, age = read_latest_cascade(pair, now_utc=now_utc)
    if label is None or age is None:
        return (False, label, age)
    if age > MAX_AGE_SECONDS:
        return (False, label, age)
    if side == "LONG" and label in _DIRECTIONAL_BEAR:
        return (True, label, age)
    if side == "SHORT" and label in _DIRECTIONAL_BULL:
        return (True, label, age)
    return (False, label, age)
