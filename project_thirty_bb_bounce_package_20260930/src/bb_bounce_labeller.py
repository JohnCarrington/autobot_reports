"""bb_bounce_labeller.py — fire-time convergence labeller (2026-08-05).

Sends [LABEL] / [LABEL-BLOCKED] Telegram prompts on BB_BOUNCE events,
polls Telegram getUpdates for the operator's short-code reply, and
stamps the label onto the corresponding signal_log record (fire path)
or the lifecycle jsonl (regime stand-down path).

Behaviour is entirely observability — no trading-path effect.

Master switch: BB_BOUNCE_LABEL_PROMPTS_ENABLED=1 (default off).

Inbound mechanism: no pre-existing telegram inbound listener existed in
the estate, so this module implements simple long-poll of the Bot API
getUpdates endpoint, keyed to TELEGRAM_CHAT_ID. Updates from any other
chat are ignored. Reply match is FIFO — the oldest non-expired pending
prompt is stamped by the next matching label (SE/S/E/N/X, case-insensitive).
"""

import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Optional

import requests

logger = logging.getLogger("AutoBot")

LABEL_PROMPTS_ENABLED = (os.getenv("BB_BOUNCE_LABEL_PROMPTS_ENABLED") or "0").strip() == "1"
LABEL_KILL_ENABLED = (os.getenv("BB_BOUNCE_LABEL_KILL_ENABLED") or "0").strip() == "1"
_TG_TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip()
_TG_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

_LABEL_WINDOW_MIN = 120
_LIFECYCLE_LOG_PATH = os.getenv(
    "BB_BOUNCE_LIFECYCLE_LOG_PATH",
    "/opt/tradingbot/logs/bb_bounce_lifecycle.jsonl",
)
_OFFSET_PATH = Path("/opt/tradingbot/cache/bb_bounce_labeller_offset.json")
_COUNTER_PATH = Path("/opt/tradingbot/cache/bb_bounce_labeller_seq.json")

# Reply forms accepted:
#   "<n> <code>"  — explicit seq (always accepted; disambiguates concurrent prompts)
#   "<code>"      — bare code (accepted ONLY if exactly one prompt is pending)
# Codes: SE / S / E / N / X / K   (K = operator kill — closes the prompted
# position at market when BB_BOUNCE_LABEL_KILL_ENABLED=1 and prompt is a fire).
_SEQ_LABEL_RE = re.compile(r"^\s*(\d+)\s+(SE|ES|S|E|N|X|K)\s*$", re.IGNORECASE)
_BARE_LABEL_RE = re.compile(r"^\s*(SE|ES|S|E|N|X|K)\s*$", re.IGNORECASE)
_TG_URL_TMPL = "https://api.telegram.org/bot{token}/getUpdates"

_lock = threading.Lock()
_counter_lock = threading.Lock()
_pending: Deque[Dict[str, Any]] = deque()
_poller_started = False

# ── Kill-bindings (2026-08-06) ─────────────────────────────────────────
# Separate from _pending: label codes SE/S/E/N/X expire with the
# 120-min pending-prompt window (fire-time truth discipline unchanged),
# but K binds to the position and lives until the position is confirmed
# closed. Keyed by prompt seq. Only fire prompts add a binding —
# [LABEL-BLOCKED] prompts have no position and never bind (see
# enqueue_blocked_prompt below, which does NOT touch this dict).
#
# Persistence: intentionally in-memory only. Bindings are not persisted
# alongside the seq counter file — merging a datetime-carrying dict
# into that file's read/write path is more coupling than the spec's
# "trivially cheap" bar allows. Restart clears bindings; the operator's
# manual IG close remains the documented fallback for a K reply on a
# position that was open across a bot restart.
#
# Open-state check is lazy at K-time via the existing
# _find_pos_key_for_trade helper (below) — no new subscription to
# close events is introduced.
_kill_bindings: Dict[int, Dict[str, Any]] = {}


def _next_seq() -> int:
    """Persisted monotonically-increasing prompt tag. Falls back to a
    ms-based fallback if the counter file can't be read/written — even
    the fallback stays monotonic within a process."""
    with _counter_lock:
        try:
            _COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
            cur = 0
            if _COUNTER_PATH.exists():
                try:
                    cur = int(json.loads(_COUNTER_PATH.read_text()).get("counter", 0))
                except Exception:
                    cur = 0
            nxt = cur + 1
            _COUNTER_PATH.write_text(json.dumps({"counter": nxt}))
            return nxt
        except Exception as exc:
            logger.warning("[BB_LABEL] counter read/write failed: %s", exc)
            return int(time.time() * 1000) % 10_000_000


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_ts(ts: datetime) -> str:
    """Return '<UTC hh:mm:ss> UTC (<London hh:mm> BST/GMT)'."""
    try:
        from zoneinfo import ZoneInfo
        london = ts.astimezone(ZoneInfo("Europe/London"))
        tz_abbr = london.strftime("%Z") or "London"
        return (
            f"{ts.strftime('%Y-%m-%d %H:%M:%S')} UTC "
            f"({london.strftime('%H:%M')} {tz_abbr})"
        )
    except Exception:
        return ts.strftime("%Y-%m-%d %H:%M:%S UTC")


def _read_offset() -> int:
    try:
        if _OFFSET_PATH.exists():
            return int(json.loads(_OFFSET_PATH.read_text()).get("offset", 0))
    except Exception:
        pass
    return 0


def _write_offset(offset: int) -> None:
    try:
        _OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OFFSET_PATH.write_text(json.dumps({"offset": int(offset)}))
    except Exception:
        pass


def _send_prompt(text: str) -> None:
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(text)
    except Exception as exc:
        logger.warning("[BB_LABEL] telegram send failed: %s", exc)


def _prompt_body(header: str, direction: str, entry: float,
                 fire_ts: datetime, mode: str) -> str:
    return (
        f"<b>{header}</b> {mode} {direction} @ {float(entry):.2f} {_fmt_ts(fire_ts)}\n"
        "S = structure side with trade? "
        "(price above reclaimed level for BUY / below lost level for SELL)\n"
        "E = H1 momentum event happened? (MACD cross/flip after contraction)\n"
        "Reply: '&lt;n&gt; SE' | S | E | N | X (can't assess) | "
        "K (kill: close this position at market — fires only)\n"
        "Bare code (no &lt;n&gt;) OK only when just one prompt is open."
    )


def enqueue_fire_prompt(trade_id: str, mode: str, direction: str,
                        entry: float, fire_ts: datetime) -> None:
    """Fire path — sends [LABEL #<n>] and queues the trade_id for stamping."""
    if not LABEL_PROMPTS_ENABLED:
        return
    try:
        prompt_ts = _now_utc()
        seq = _next_seq()
        side = "L" if direction == "BUY" else "S"
        header = f"[LABEL #{seq}] BB_BOUNCE_{side}"
        text = _prompt_body(header, direction, entry, fire_ts, mode)
        _send_prompt(text)
        with _lock:
            _pending.append({
                "seq": seq,
                "kind": "fire",
                "trade_id": trade_id,
                "mode": mode,
                "direction": direction,
                "fire_ts": fire_ts,
                "prompt_ts": prompt_ts,
                "expiry_ts": prompt_ts + timedelta(minutes=_LABEL_WINDOW_MIN),
            })
            # 2026-08-06: kill-binding for K path. Lives beyond
            # _LABEL_WINDOW_MIN so a late K still lands as long as the
            # position is open. Removed lazily at K-resolution time.
            _kill_bindings[seq] = {
                "seq": seq,
                "trade_id": trade_id,
                "mode": mode,
                "direction": direction,
                "issued_ts": prompt_ts,
            }
        _ensure_poller_started()
    except Exception as exc:
        logger.warning("[BB_LABEL] enqueue_fire_prompt failed: %s", exc)


def enqueue_blocked_prompt(mode: str, direction: str,
                           entry: float, fire_ts: datetime,
                           block_reason: str) -> None:
    """Regime stand-down path — sends [LABEL-BLOCKED #<n>] and queues for
    lifecycle-jsonl stamping (no signal_log record exists for a blocked fire)."""
    if not LABEL_PROMPTS_ENABLED:
        return
    try:
        prompt_ts = _now_utc()
        seq = _next_seq()
        side = "L" if direction == "BUY" else "S"
        header = f"[LABEL-BLOCKED #{seq}] BB_BOUNCE_{side}"
        text = _prompt_body(header, direction, entry, fire_ts, mode)
        _send_prompt(text)
        with _lock:
            _pending.append({
                "seq": seq,
                "kind": "blocked",
                "trade_id": None,
                "mode": mode,
                "direction": direction,
                "fire_ts": fire_ts,
                "prompt_ts": prompt_ts,
                "expiry_ts": prompt_ts + timedelta(minutes=_LABEL_WINDOW_MIN),
                "block_reason": block_reason,
            })
        _ensure_poller_started()
    except Exception as exc:
        logger.warning("[BB_LABEL] enqueue_blocked_prompt failed: %s", exc)


def _ensure_poller_started() -> None:
    global _poller_started
    with _lock:
        if _poller_started:
            return
        if not _TG_TOKEN or not _TG_CHAT_ID:
            logger.warning(
                "[BB_LABEL] TELEGRAM_TOKEN/CHAT_ID missing — poller not started"
            )
            return
        _poller_started = True
    t = threading.Thread(target=_poll_loop, name="bb-labeller", daemon=True)
    t.start()


def _sweep_expired(label_ts: datetime) -> None:
    """Drop expired entries in place. Caller must hold _lock."""
    dropped = []
    kept = deque()
    for e in _pending:
        if e["expiry_ts"] < label_ts:
            dropped.append(e)
        else:
            kept.append(e)
    if dropped:
        _pending.clear()
        _pending.extend(kept)
        for e in dropped:
            logger.info(
                "[BB_LABEL] expired unlabelled: seq=%s kind=%s fire_ts=%s",
                e.get("seq"), e.get("kind"),
                e.get("fire_ts").isoformat() if e.get("fire_ts") else "?",
            )


def _summarize_pending() -> str:
    """One-line summary of currently-pending prompts for the WARN reply."""
    items = []
    for e in _pending:
        side = "L" if e.get("direction") == "BUY" else "S"
        items.append(f"#{e['seq']} BB_BOUNCE_{side} {e.get('direction','?')}")
    return ", ".join(items) if items else "none"


def _handle_message(text: str, label_ts: datetime) -> None:
    """Route a candidate reply to seq-tagged or bare-code handling.

    K is intercepted here (2026-08-06) and dispatched to the kill-binding
    path so it works beyond the 120-min pending-prompt window. SE/S/E/N/X
    remain 100% on the pending-prompt path — no behaviour change.
    """
    seq_m = _SEQ_LABEL_RE.match(text or "")
    if seq_m:
        _seq = int(seq_m.group(1))
        _label = seq_m.group(2).upper()
        if _label == "K":
            _handle_k_seq_reply(_seq, label_ts)
        else:
            _handle_seq_reply(_seq, _label, label_ts)
        return
    bare_m = _BARE_LABEL_RE.match(text or "")
    if bare_m:
        _label = bare_m.group(1).upper()
        if _label == "K":
            _handle_bare_k_reply(label_ts)
        else:
            _handle_bare_reply(_label, label_ts)
        return
    # Not a label reply — ignore silently (chat may contain other traffic).


def _handle_seq_reply(seq: int, label: str, label_ts: datetime) -> None:
    """SE/S/E/N/X seq reply — pending-prompt path, UNCHANGED (2026-08-05
    behaviour). K is routed to _handle_k_seq_reply upstream and never
    reaches this function."""
    entry: Optional[Dict[str, Any]] = None
    with _lock:
        _sweep_expired(label_ts)
        for i, e in enumerate(_pending):
            if int(e.get("seq", -1)) == seq:
                entry = e
                del _pending[i]
                break
    if entry is None:
        logger.info(
            "[BB_LABEL] reply '#%d %s' — no matching pending prompt (expired or unknown)",
            seq, label,
        )
        return
    _stamp(entry, label, label_ts)


def _handle_bare_reply(label: str, label_ts: datetime) -> None:
    """SE/S/E/N/X bare reply — pending-prompt path, UNCHANGED (2026-08-05
    behaviour). Bare K is routed to _handle_bare_k_reply upstream."""
    entry: Optional[Dict[str, Any]] = None
    pending_summary: str = ""
    with _lock:
        _sweep_expired(label_ts)
        if len(_pending) == 1:
            entry = _pending.popleft()
        else:
            pending_summary = _summarize_pending()
    if entry is not None:
        _stamp(entry, label, label_ts)
        return
    # Ambiguous or nothing pending — WARN back to Telegram.
    if not pending_summary or pending_summary == "none":
        warn = (
            f"[BB_LABEL] bare reply '{label}' ignored — no pending prompt."
        )
    else:
        warn = (
            f"[BB_LABEL] bare reply '{label}' ambiguous — {len(pending_summary.split(','))}"
            f" prompts pending: {pending_summary}. Reply with '&lt;n&gt; {label.upper()}'."
        )
    logger.warning("%s", warn)
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(warn)
    except Exception as exc:
        logger.warning("[BB_LABEL] warn-back send failed: %s", exc)


def _stamp_k_label(binding: Dict[str, Any], label_ts: datetime) -> None:
    """Stamp K to the labels sidecar via signal_logger. Called on every
    K resolution — position-open or already-closed — because a late K is
    still the operator's verdict and the sidecar's (prompt_ts, label_ts)
    pair makes lateness auditable."""
    try:
        from signal_logger import stamp_convergence_label
        stamp_convergence_label(
            trade_id=binding.get("trade_id"),
            label="K",
            label_ts=label_ts,
            prompt_ts=binding.get("issued_ts"),
        )
    except Exception as exc:
        logger.warning("[BB_LABEL] K stamp failed: %s", exc)


def _drop_pending_seq(seq: int) -> None:
    """Remove a still-open pending prompt for this seq (if any). Called
    after K resolution so a stale SE/S/E/N/X reply for the same seq
    can't double-label after the operator has already killed."""
    with _lock:
        kept = deque()
        for e in _pending:
            if int(e.get("seq", -1)) != int(seq):
                kept.append(e)
        _pending.clear()
        _pending.extend(kept)


def _handle_k_seq_reply(seq: int, label_ts: datetime) -> None:
    """Resolve '<n> K' against the kill-binding for #n.

    Bindings survive the 120-min pending-prompt window and live until
    the bound position is confirmed closed — verified lazily at K-time
    via _find_pos_key_for_trade (see below). If the binding's position
    is still open, run the existing kill path unchanged; if not, reply
    'already closed' and drop the binding. Stamp K to the sidecar in
    either case.
    """
    with _lock:
        binding = _kill_bindings.get(seq)
    if binding is None:
        logger.info(
            "[LABEL-K] '#%d K' — no kill-binding (unknown seq or already resolved)",
            seq,
        )
        _reply_tg(
            f"[LABEL-K] no kill-binding for #{seq} — nothing to close "
            f"(unknown seq, blocked-prompt, or already resolved)."
        )
        return

    # Stamp K to the sidecar regardless of position state.
    _stamp_k_label(binding, label_ts)

    trade_id = str(binding.get("trade_id") or "")
    pk, direction = _find_pos_key_for_trade(trade_id)
    if not pk:
        logger.info(
            "[LABEL-K] position for #%d already closed — no action "
            "(binding age=%s)",
            seq,
            (label_ts - binding.get("issued_ts")).total_seconds()
            if binding.get("issued_ts") else "?",
        )
        _reply_tg(
            f"[LABEL-K] position for #{seq} already closed — no action."
        )
        with _lock:
            _kill_bindings.pop(seq, None)
        _drop_pending_seq(seq)
        return

    # Position still open — run the existing kill path unchanged.
    _handle_kill_fire(binding)
    with _lock:
        _kill_bindings.pop(seq, None)
    _drop_pending_seq(seq)


def _open_kill_bindings_snapshot() -> Dict[int, Dict[str, Any]]:
    """Return {seq: binding} for bindings whose position is currently open.
    Uses the same lazy verification as K-time resolution."""
    with _lock:
        snapshot = dict(_kill_bindings)
    open_map: Dict[int, Dict[str, Any]] = {}
    for seq, binding in snapshot.items():
        trade_id = str(binding.get("trade_id") or "")
        pk, _dir = _find_pos_key_for_trade(trade_id)
        if pk:
            open_map[seq] = binding
    return open_map


def _handle_bare_k_reply(label_ts: datetime) -> None:
    """Bare 'K' — allowed only if exactly ONE kill-binding has an open
    position. Mirrors the SE/S/E/N/X bare-code disambiguation rule but
    against open positions rather than pending prompts."""
    open_bindings = _open_kill_bindings_snapshot()
    if len(open_bindings) == 1:
        seq = next(iter(open_bindings))
        _handle_k_seq_reply(seq, label_ts)
        return
    if not open_bindings:
        warn = "[BB_LABEL] bare 'K' ignored — no open BB_BOUNCE position bound."
        logger.warning("%s", warn)
        _reply_tg(warn)
        return
    # Multiple open bindings — list numbers.
    items = []
    for seq, b in sorted(open_bindings.items()):
        side = "L" if b.get("direction") == "BUY" else "S"
        items.append(f"#{seq} BB_BOUNCE_{side} {b.get('direction','?')}")
    listing = ", ".join(items)
    warn = (
        f"[BB_LABEL] bare 'K' ambiguous — {len(open_bindings)} open positions "
        f"bound: {listing}. Reply with '&lt;n&gt; K'."
    )
    logger.warning("%s", warn)
    _reply_tg(warn)


def _stamp(entry: Dict[str, Any], label: str, label_ts: datetime) -> None:
    label_up = label.upper()
    prompt_ts = entry["prompt_ts"]
    if entry["kind"] == "fire":
        try:
            from signal_logger import stamp_convergence_label
            stamp_convergence_label(
                trade_id=entry["trade_id"],
                label=label_up,
                label_ts=label_ts,
                prompt_ts=prompt_ts,
            )
        except Exception as exc:
            logger.warning("[BB_LABEL] signal_log stamp failed: %s", exc)
        if label_up == "K":
            _handle_kill_fire(entry)
        return
    row = {
        "ts_utc": label_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": "convergence_label_blocked",
        "mode": entry.get("mode"),
        "direction": entry.get("direction"),
        "fire_ts": entry["fire_ts"].isoformat(),
        "prompt_ts": prompt_ts.isoformat(),
        "label_ts": label_ts.isoformat(),
        "convergence_label": label_up,
        "block_reason": entry.get("block_reason"),
    }
    try:
        os.makedirs(os.path.dirname(_LIFECYCLE_LOG_PATH), exist_ok=True)
        with open(_LIFECYCLE_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as exc:
        logger.warning("[BB_LABEL] lifecycle write failed: %s", exc)
    if label_up == "K":
        _reply_tg(
            f"[LABEL-K] #{entry.get('seq')} — no position exists "
            f"(blocked prompt); label stamped only."
        )


def _reply_tg(text: str) -> None:
    """Convenience wrapper — never raises."""
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(text)
    except Exception as exc:
        logger.warning("[BB_LABEL] telegram reply failed: %s", exc)


def _find_pos_key_for_trade(trade_id: str):
    """Reverse-lookup EPIC_STATE for the pos_key whose signal_log_id
    matches this fire's trade_id. Returns (pos_key, direction) or (None, None).
    Only returns pos_keys with an active (or pending_open) position.
    """
    try:
        from trade_executor import EPIC_STATE, EPIC_STATE_LOCK
    except Exception as exc:  # noqa: BLE001
        logger.warning("[BB_LABEL] trade_executor import failed: %s", exc)
        return None, None
    try:
        with EPIC_STATE_LOCK:
            for pk, st in list(EPIC_STATE.items()):
                if not isinstance(st, dict):
                    continue
                if st.get("signal_log_id") != trade_id:
                    continue
                if not (st.get("active") or st.get("pending_open")):
                    continue
                return pk, str(st.get("direction") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[BB_LABEL] EPIC_STATE scan failed: %s", exc)
    return None, None


def _handle_kill_fire(entry: Dict[str, Any]) -> None:
    """Operator kill on a FIRE prompt. Single close attempt on the SAME
    close path STRUCTURE_EXIT / scale-out use — trade_executor.close_position
    (trade_executor.py:2881) → close_trade (trade_executor.py:2285) →
    close_by_deal_id (close_sb_now.py:217).

    Never opens, never modifies stops or size, never touches any other
    position. Single attempt (no retry-loop) — the IG-auth do-not-hammer
    rule applies.
    """
    seq = entry.get("seq")
    trade_id = entry.get("trade_id")
    if not LABEL_KILL_ENABLED:
        logger.info(
            "[LABEL-K] K received for #%s but BB_BOUNCE_LABEL_KILL_ENABLED=0 "
            "— label stamped, no close attempted",
            seq,
        )
        _reply_tg(f"[LABEL-K] #{seq} — kill disabled; label stamped only.")
        return

    pk, direction = _find_pos_key_for_trade(str(trade_id))
    if not pk:
        logger.info("[LABEL-K] no open position for #%s", seq)
        _reply_tg(f"[LABEL-K] no open position for #{seq}")
        return

    try:
        from trade_executor import close_position
    except Exception as exc:  # noqa: BLE001
        logger.warning("[LABEL-K] close_position import failed: %s", exc)
        _reply_tg(f"[LABEL-K] close attempt failed for #{seq}: import error")
        return

    _reply_tg(f"[LABEL-K] closing {direction or entry.get('direction','?')} #{seq} @ market.")
    try:
        result = close_position(pos_key=pk, reason="LABEL_K_OPERATOR")
    except Exception as exc:  # noqa: BLE001
        logger.error("[LABEL-K] close_position raised for #%s: %s", seq, exc)
        _reply_tg(f"[LABEL-K] close FAILED for #{seq}: {type(exc).__name__}: {exc}")
        return
    if result is None:
        logger.warning("[LABEL-K] close returned None for #%s (pk=%s)", seq, pk)
        _reply_tg(
            f"[LABEL-K] close returned no result for #{seq} — check position status."
        )
    else:
        logger.info("[LABEL-K] close dispatched for #%s pk=%s", seq, pk)


def _poll_loop() -> None:
    """Telegram long-poll loop. Never raises out."""
    url = _TG_URL_TMPL.format(token=_TG_TOKEN)
    offset = _read_offset()
    logger.info("[BB_LABEL] poller started (offset=%d)", offset)
    while True:
        try:
            resp = requests.get(
                url,
                params={
                    "timeout": 25,
                    "offset": offset,
                    "allowed_updates": json.dumps(["message"]),
                },
                timeout=35,
            )
            if resp.status_code != 200:
                logger.warning("[BB_LABEL] getUpdates HTTP %s", resp.status_code)
                time.sleep(5)
                continue
            data = resp.json()
            if not data.get("ok"):
                logger.warning("[BB_LABEL] getUpdates not-ok: %s", data)
                time.sleep(5)
                continue
            for upd in data.get("result", []):
                try:
                    upd_id = int(upd.get("update_id", 0))
                except (TypeError, ValueError):
                    upd_id = 0
                if upd_id + 1 > offset:
                    offset = upd_id + 1
                    _write_offset(offset)
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id") or "").strip()
                if chat_id != _TG_CHAT_ID:
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                _handle_message(text, _now_utc())
        except Exception as exc:
            logger.warning("[BB_LABEL] poll error: %s", exc)
            time.sleep(5)
