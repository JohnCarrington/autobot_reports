"""
briefing_narrative.py — Persistent daily session narrative for AutoBot briefings.

Maintains a chronological log of session briefings per pair per day,
so later sessions can build on earlier context instead of starting fresh.

Log files live at: data/session_narrative/{YYYY-MM-DD}.json
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AutoBot")

_DIR = Path(__file__).resolve().parent / "data" / "session_narrative"
_LOCK = threading.Lock()


def _ensure_dir() -> None:
    """Create the narrative directory if it doesn't exist."""
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug(f"[briefing_narrative] mkdir error: {exc}")


def _today_path() -> Path:
    """Return path to today's narrative file."""
    return _DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"


def _load_file(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Load a narrative JSON file. Returns dict keyed by pair."""
    try:
        if path.exists() and path.stat().st_size > 0:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug(f"[briefing_narrative] load error {path.name}: {exc}")
    return {}


def _save_file(path: Path, data: Dict[str, List[Dict[str, Any]]]) -> None:
    """Atomically save narrative data to disk."""
    try:
        _ensure_dir()
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        tmp.replace(path)
    except Exception as exc:
        logger.debug(f"[briefing_narrative] save error {path.name}: {exc}")


def log_session(
    pair: str,
    session: str,
    bias: str,
    confidence: float,
    reasoning_summary: str,
    key_levels: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a session entry to today's narrative log."""
    try:
        entry = {
            "session": session,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pair": pair.upper(),
            "bias": str(bias).upper(),
            "confidence": float(confidence) if confidence else 0.0,
            "narrative_summary": str(reasoning_summary or "")[:300],
            "key_levels": key_levels if isinstance(key_levels, dict) else None,
        }
        with _LOCK:
            path = _today_path()
            data = _load_file(path)
            pair_key = pair.upper()
            if pair_key not in data:
                data[pair_key] = []
            # Avoid duplicate entries for same pair+session
            data[pair_key] = [
                e for e in data[pair_key] if e.get("session") != session
            ]
            data[pair_key].append(entry)
            _save_file(path, data)
        logger.debug(f"[briefing_narrative] logged {pair}/{session} bias={bias}")
    except Exception as exc:
        logger.debug(f"[briefing_narrative] log_session error: {exc}")


def get_today_narrative(pair: str) -> List[Dict[str, Any]]:
    """Return chronological list of today's sessions for a pair."""
    try:
        with _LOCK:
            data = _load_file(_today_path())
        return data.get(pair.upper(), [])
    except Exception as exc:
        logger.debug(f"[briefing_narrative] get_today_narrative error: {exc}")
        return []


def get_today_narrative_text(pair: str) -> str:
    """Return formatted text block suitable for injecting into the API prompt."""
    try:
        entries = get_today_narrative(pair)
        if not entries:
            return ""
        lines = []
        for e in entries:
            ts = e.get("timestamp", "?")
            sess = e.get("session", "?")
            bias = e.get("bias", "?")
            conf = e.get("confidence", "?")
            summary = e.get("narrative_summary", "")
            kl = e.get("key_levels")
            line = f"- {sess} ({ts}): {bias} (conf={conf})"
            if summary:
                line += f" — {summary}"
            if isinstance(kl, dict):
                res = kl.get("resistance", [])
                sup = kl.get("support", [])
                if res:
                    line += f" | R: {', '.join(str(v) for v in res[:3])}"
                if sup:
                    line += f" | S: {', '.join(str(v) for v in sup[:3])}"
            lines.append(line)
        return "\n".join(lines)
    except Exception as exc:
        logger.debug(f"[briefing_narrative] get_today_narrative_text error: {exc}")
        return ""
