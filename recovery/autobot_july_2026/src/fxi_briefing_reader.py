"""
fxi_briefing_reader — cache-first per-pair reader for today's FXi plan.

OBSERVABLE-ONLY. Consumed by signal_logger for telemetry stamps. No gate,
no veto, no sizing. Fail-open: any Neon/parse failure logs one warning
per UTC day, caches the failure so subsequent fires don't re-attempt, and
returns None so the fleet trades byte-identically to a plan-less world.

One SELECT per process per UTC day (or per cache miss). No retry loops.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parent / "logs" / "fxi_plan_cache.json"
_CONNECT_TIMEOUT_S = 3
_LOCK = threading.Lock()
_MEM: Dict[str, Any] = {}


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_disk_cache() -> Dict[str, Any]:
    try:
        if _CACHE_PATH.exists():
            with _CACHE_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    return data
    except Exception as exc:
        _log.warning("[fxi_reader] cache read failed: %s", exc)
    return {}


def _write_disk_cache(payload: Dict[str, Any]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        tmp.replace(_CACHE_PATH)
    except Exception as exc:
        _log.warning("[fxi_reader] cache write failed: %s", exc)


def _coerce_float_list(raw: Any) -> List[float]:
    out: List[float] = []
    if not raw:
        return out
    try:
        for item in raw:
            try:
                out.append(float(item))
            except (TypeError, ValueError):
                continue
    except TypeError:
        pass
    return out


def _fetch_from_neon(url: str, date_key: str) -> Dict[str, Any]:
    """Return {pair_upper: plan_dict} for the given UTC date. Raises on
    transport or query error; the caller catches and caches the failure."""
    import psycopg  # local import: missing driver mustn't crash the fleet at boot.

    plans: Dict[str, Any] = {}
    with psycopg.connect(url, connect_timeout=_CONNECT_TIMEOUT_S) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pp.pair,
                       pp.direction,
                       pp.confidence,
                       pp.plan_active,
                       pp.status,
                       pp.plan,
                       pp.key_levels
                  FROM briefings b
                  JOIN pair_plans pp ON pp.briefing_id = b.id
                 WHERE b.date = %s
                   AND b.id = (
                       SELECT id FROM briefings
                        WHERE date = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                   )
                """,
                (date_key, date_key),
            )
            for pair, direction, confidence, plan_active, status, plan_json, key_levels in cur.fetchall():
                # plan.state (v5_fxi schema) takes precedence over pp.status.
                plan_state = None
                if isinstance(plan_json, dict):
                    ps = plan_json.get("state")
                    if isinstance(ps, str):
                        plan_state = ps
                if plan_state is None and isinstance(status, str):
                    plan_state = status

                # v5_fxi plan verbatim floats: single-float entry (no zone),
                # stop, target, rr. None when the plan omits the key or the
                # value fails float coercion (STAND_ASIDE plans typically
                # carry None for entry/stop/target).
                def _pj_num(key: str) -> Optional[float]:
                    if not isinstance(plan_json, dict):
                        return None
                    v = plan_json.get(key)
                    if v is None:
                        return None
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return None
                plan_entry_val = _pj_num("entry")
                plan_stop_val = _pj_num("stop")
                plan_target_val = _pj_num("target")
                plan_rr_val = _pj_num("rr")

                support: List[float] = []
                resistance: List[float] = []
                support_detail = None
                resistance_detail = None
                levels_source = None
                if isinstance(key_levels, dict):
                    support = _coerce_float_list(key_levels.get("support"))
                    resistance = _coerce_float_list(key_levels.get("resistance"))
                    # These sibling keys are optional in the current schema;
                    # pass through when the briefer emits them, else null.
                    support_detail = key_levels.get("support_detail")
                    resistance_detail = key_levels.get("resistance_detail")
                    levels_source = key_levels.get("levels_source")

                plans[str(pair).upper()] = {
                    "direction": direction,
                    "confidence": confidence,
                    "state": plan_state,
                    "plan_active": bool(plan_active) if plan_active is not None else None,
                    "support_levels": support,
                    "resistance_levels": resistance,
                    "support_detail": support_detail,
                    "resistance_detail": resistance_detail,
                    "levels_source": levels_source,
                    "plan_entry": plan_entry_val,
                    "plan_stop": plan_stop_val,
                    "plan_target": plan_target_val,
                    "plan_rr": plan_rr_val,
                }
    return plans


def _ensure_today_loaded(url: str) -> Dict[str, Any]:
    """Populate `_MEM` for today. Returns the pair→plan map ({} on failure
    or empty-day). A cached failure short-circuits — no re-attempt this UTC
    day."""
    global _MEM

    date_key = _today_utc()
    with _LOCK:
        if _MEM.get("date") == date_key:
            return _MEM.get("plans") or {}

        disk = _load_disk_cache()
        if disk.get("date") == date_key:
            _MEM = disk
            return disk.get("plans") or {}

        try:
            plans = _fetch_from_neon(url, date_key)
            _MEM = {"date": date_key, "plans": plans, "failed": False}
            _write_disk_cache(_MEM)
            _log.info(
                "[fxi_reader] cache primed for %s: %d pair-plan(s)",
                date_key, len(plans),
            )
            return plans
        except Exception as exc:
            _MEM = {"date": date_key, "plans": {}, "failed": True, "error": repr(exc)[:200]}
            _write_disk_cache(_MEM)
            _log.warning(
                "[fxi_reader] Neon fetch failed for %s (cached, retry tomorrow): %s",
                date_key, exc,
            )
            return {}


def get_today_plan(pair: str) -> Optional[Dict[str, Any]]:
    """Return today's plan dict for `pair`, or None when unavailable.

    Silent no-op when FXI_NEON_READ_URL is unset. Fail-open on any
    exception: one warning per day, cached failure, no retries.
    """
    url = os.environ.get("FXI_NEON_READ_URL")
    if not url:
        return None
    if not pair:
        return None
    plans = _ensure_today_loaded(url)
    return plans.get(str(pair).upper())


def _reset_cache_for_tests() -> None:
    """Test helper — clear both in-memory and on-disk cache."""
    global _MEM
    with _LOCK:
        _MEM = {}
        try:
            if _CACHE_PATH.exists():
                _CACHE_PATH.unlink()
        except Exception:
            pass
