"""
signal_log_integrity.py — daily 00:00 UTC reconciliation of orphaned
signal_log.jsonl entries against the IG activity / transactions API.

Runs as a daemon thread started from AutoBot boot. Every day at ~00:05
UTC (buffer so pending close events can settle) it:

  1. Scans signal_log.jsonl for entries from the previous UTC day with
     outcome=null  (the bookkeeping-gap leftovers).
  2. Pulls yesterday's closed deals from IG (/history/transactions).
  3. Matches each orphan by epic + direction + open_level (±3.0) +
     open_time (±240s) — same heuristic used in the forensic analysis.
  4. For each match: computes pnl_pips from openLevel/closeLevel ×
     direction and calls signal_logger.log_close to patch the open
     record in-place with reason "IG_RECONCILE".
  5. For each unmatched orphan: builds a single Telegram alert listing
     id / pair / direction / entry / open-time so the operator can
     investigate.

The scheduler only runs once per UTC date (tracked in-process). A
mid-day restart re-runs the check if yesterday hasn't been processed
yet this boot — idempotent because log_close only patches when
outcome is still null.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("signal_log_integrity")

SIGNAL_LOG_PATH = Path("/opt/tradingbot/logs/signal_log.jsonl")
SCHEDULE_HOUR_UTC = 0      # 00:00 UTC
SCHEDULE_MIN_UTC = 5       # 00:05 — small buffer for settlement
MATCH_PRICE_TOLERANCE = 3.0
MATCH_TIME_TOLERANCE_SECS = 240

_INSTR_TO_EPIC = {
    "GBP/USD": "CS.D.GBPUSD.TODAY.IP",
    "EUR/USD": "CS.D.EURUSD.TODAY.IP",
    "USD/JPY": "CS.D.USDJPY.TODAY.IP",
    "USD/CAD": "CS.D.USDCAD.TODAY.IP",
    "GBP/JPY": "CS.D.GBPJPY.TODAY.IP",
}

_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_last_run_date: Optional[str] = None
_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _parse_iso(ts: str) -> Optional[float]:
    """Return epoch seconds (UTC) for an ISO timestamp string, or None."""
    try:
        s = ts.replace("Z", "+00:00") if ts and ts.endswith("Z") else ts
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _read_orphans_for_date(date_str: str) -> List[Dict[str, Any]]:
    """Return signal_log entries whose timestamp_open starts with date_str
    and outcome is null / missing."""
    if not SIGNAL_LOG_PATH.exists():
        return []
    out: List[Dict[str, Any]] = []
    with SIGNAL_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except Exception:
                continue
            ts = str(rec.get("timestamp_open") or "")
            if not ts.startswith(date_str):
                continue
            if rec.get("outcome") is not None:
                continue
            out.append(rec)
    return out


def _fetch_ig_transactions(date_str: str) -> List[Dict[str, Any]]:
    """Pull yesterday's ALL_DEAL transactions from IG."""
    try:
        import ig_auth
        import requests
        _, headers, _ = ig_auth.get_ig_session()
        h = dict(headers)
        h["Version"] = "2"
        h["Accept"] = "application/json; charset=UTF-8"
        url = (
            "https://demo-api.ig.com/gateway/deal/history/transactions"
            f"?type=ALL_DEAL&from={date_str}T00:00:00&to={date_str}T23:59:59"
            "&pageSize=500"
        )
        r = requests.get(url, headers=h, timeout=20)
        if r.status_code != 200:
            logger.warning("[sli] IG tx fetch HTTP %d", r.status_code)
            return []
        return r.json().get("transactions", []) or []
    except Exception as e:
        logger.warning("[sli] IG tx fetch failed: %s", e)
        return []


def _match_one(orphan: Dict[str, Any], txs: List[Dict[str, Any]], used: set) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Find best IG tx matching an orphan by epic + dir + level + time.
    Returns (index, tx) or None."""
    ep_target = str(orphan.get("epic") or "")
    dir_target = str(orphan.get("direction") or "").upper()
    try:
        entry_target = float(orphan.get("entry") or 0)
        t_open_target = _parse_iso(str(orphan.get("timestamp_open") or ""))
    except Exception:
        return None
    if t_open_target is None:
        return None

    best: Optional[Tuple[int, Dict[str, Any]]] = None
    best_score = float("inf")
    for i, t in enumerate(txs):
        if i in used:
            continue
        instr = t.get("instrumentName") or ""
        if _INSTR_TO_EPIC.get(instr) != ep_target:
            continue
        size = str(t.get("size") or "")
        tdir = "BUY" if size.startswith("+") else "SELL"
        if tdir != dir_target:
            continue
        try:
            lvl = float(t.get("openLevel"))
            t_open = _parse_iso(str(t.get("openDateUtc") or ""))
        except Exception:
            continue
        if t_open is None:
            continue
        dp = abs(lvl - entry_target)
        dt = abs(t_open - t_open_target)
        if dp > MATCH_PRICE_TOLERANCE or dt > MATCH_TIME_TOLERANCE_SECS:
            continue
        score = dp + dt * 0.01
        if score < best_score:
            best_score = score
            best = (i, t)
    return best


def _patch_match(orphan: Dict[str, Any], tx: Dict[str, Any]) -> bool:
    """Use signal_logger.log_close to patch the orphan record in-place."""
    try:
        from signal_logger import log_close
        open_lvl = float(tx.get("openLevel"))
        close_lvl = float(tx.get("closeLevel"))
        direction = str(orphan.get("direction") or "").upper()
        sign = 1.0 if direction == "BUY" else -1.0
        pnl_pips = (close_lvl - open_lvl) * sign
        log_close(
            trade_id=str(orphan.get("id")),
            close_price=close_lvl,
            pnl_pips=round(pnl_pips, 2),
            reason="IG_RECONCILE",
            df_5m=None,
        )
        return True
    except Exception as e:
        logger.warning("[sli] patch failed for id=%s: %s", orphan.get("id"), e)
        return False


def _send_telegram(text: str) -> None:
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(text)
    except Exception as e:
        logger.warning("[sli] telegram send failed: %s", e)


# ──────────────────────────────────────────────────────────────────────────
# Public entry point — callable ad-hoc or from the scheduler
# ──────────────────────────────────────────────────────────────────────────

def reconcile_for_date(date_str: str) -> Dict[str, Any]:
    """Scan orphans for date_str, match against IG, patch or alert. Idempotent."""
    orphans = _read_orphans_for_date(date_str)
    if not orphans:
        logger.info("[sli] %s: no orphaned signal_log entries — nothing to do.", date_str)
        return {"date": date_str, "orphans": 0, "matched": 0, "unmatched": 0}

    logger.info("[sli] %s: %d orphaned entries found", date_str, len(orphans))
    txs = _fetch_ig_transactions(date_str)
    logger.info("[sli] %s: %d IG transactions fetched", date_str, len(txs))

    matched = 0
    unmatched: List[Dict[str, Any]] = []
    used: set = set()
    for o in orphans:
        m = _match_one(o, txs, used)
        if m is None:
            unmatched.append(o)
            continue
        idx, tx = m
        if _patch_match(o, tx):
            used.add(idx)
            matched += 1
        else:
            unmatched.append(o)

    logger.info("[sli] %s: matched=%d unmatched=%d", date_str, matched, len(unmatched))

    if unmatched:
        # Single Telegram alert listing each orphaned trade.
        lines = [f"⚠️ <b>Signal log orphans for {date_str}</b>",
                 f"{len(unmatched)} open record(s) could not be matched against IG:"]
        for o in unmatched[:25]:  # cap to keep inside Telegram's 4096-char limit
            lines.append(
                f"• <code>{o.get('id','?')[:8]}</code>  {o.get('pair','?')} "
                f"{o.get('direction','?')} {o.get('strategy','?')} @ {o.get('entry','?')} "
                f"opened {o.get('timestamp_open','?')[-9:-1] if o.get('timestamp_open') else '?'}"
            )
        if len(unmatched) > 25:
            lines.append(f"…and {len(unmatched) - 25} more")
        _send_telegram("\n".join(lines))
    else:
        if matched > 0:
            _send_telegram(
                f"✅ Signal log integrity for {date_str}: "
                f"{matched} orphan(s) matched + patched from IG"
            )

    return {"date": date_str, "orphans": len(orphans), "matched": matched, "unmatched": len(unmatched)}


# ──────────────────────────────────────────────────────────────────────────
# Scheduler
# ──────────────────────────────────────────────────────────────────────────

def _yesterday_str(now_utc: datetime) -> str:
    return (now_utc.date() - timedelta(days=1)).isoformat()


def _scheduler_loop() -> None:
    global _last_run_date
    logger.info("[sli] scheduler loop started")
    while not _stop.is_set():
        try:
            _stop.wait(timeout=60.0)
            if _stop.is_set():
                break
            now = datetime.now(timezone.utc)
            # Run once per day, after SCHEDULE_HOUR_UTC:SCHEDULE_MIN_UTC.
            target_date = _yesterday_str(now)
            with _lock:
                last = _last_run_date
            past_schedule = (
                now.hour > SCHEDULE_HOUR_UTC
                or (now.hour == SCHEDULE_HOUR_UTC and now.minute >= SCHEDULE_MIN_UTC)
            )
            if past_schedule and last != target_date:
                try:
                    reconcile_for_date(target_date)
                except Exception as e:
                    logger.warning("[sli] scheduled run failed: %s", e)
                with _lock:
                    _last_run_date = target_date
        except Exception as e:
            logger.warning("[sli] scheduler tick failed: %s", e)


def start() -> None:
    """Start the background daemon. Idempotent."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_scheduler_loop, name="signal_log_integrity", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
