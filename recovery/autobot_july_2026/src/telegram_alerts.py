#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
telegram_alerts.py — Telegram notifications for AutoBot

Pre-check:
- House rules: #83 (self-contained fallback .env load; canonical TELEGRAM_TOKEN/TELEGRAM_CHAT_ID)
- Continual errors ledger: no Telegram-specific fix IDs; keep this module formatting-only (no price normalization).
- Scope lock: add timestamps to OPEN/CLOSE alerts only; no trading behavior changes.

This module is intentionally small and import-light.

LS-thread refactor (stage 1, 2026-05-08):
    `send_telegram_message` is async-by-default — the HTTP send runs on a
    small `ThreadPoolExecutor` instead of inline on the LS event-dispatch
    thread. Worst-case dispatch path was 3 × (5s timeout + 1s sleep) = 18s
    per call (telegram_alerts.py pre-refactor at line 100); now sub-ms.

    Callers needing pre-refactor synchronous semantics can pass
    `wait=True`. Per `reports/ls_refactor_safety_audit_20260508.md` §4 the
    only callsite that requires this is the LEG-ORPHAN-DETECTED alert in
    `trade_executor.py`. All other callsites are observability or run on
    process boundaries (sys.exit) where the atexit drain handles
    delivery.
"""

import atexit
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html import escape
from typing import Any, Optional, Tuple

import requests

logger = logging.getLogger("AutoBot")


# ------------------------------------------------------------
# Async dispatch executor (lazy-init on first send)
# ------------------------------------------------------------
# Pool sizing: 4 workers keeps memory cost trivial while absorbing
# multi-alert bursts (e.g. SLIPPAGE_REJECT close + Telegram + close
# callback within a couple ms). Single worker would queue them up and
# the second alert's dispatch latency would spike past the 5ms warning
# threshold during an 18s Telegram timeout window.
_TG_EXECUTOR_MAX_WORKERS = 4

# 5ms regression threshold for the dispatch-latency warning. Submit-to-
# executor is normally microseconds; >5ms means the executor is stuck.
_TG_DISPATCH_LATENCY_WARN_MS = 5.0

# Default `wait=True` timeout. The underlying _do_send_blocking can spend
# up to 3 × (5s timeout + 1s sleep) = 18s on a stuck Telegram API; allow
# a small margin so a `wait=True` caller sees the same effective ceiling
# as the pre-refactor synchronous path.
_TG_WAIT_TIMEOUT_S = 20.0

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()
_executor_submitted_count: int = 0
_executor_drained: bool = False


def _get_executor() -> Optional[ThreadPoolExecutor]:
    """Lazy-init the module-level Telegram-send executor.

    Returns None after `atexit` drain has run, so late-shutdown calls
    fall back to inline blocking sends instead of submitting to a
    shut-down pool (which would raise RuntimeError).
    """
    global _executor
    if _executor_drained:
        return None
    if _executor is not None:
        return _executor
    with _executor_lock:
        if _executor is None and not _executor_drained:
            _executor = ThreadPoolExecutor(
                max_workers=_TG_EXECUTOR_MAX_WORKERS,
                thread_name_prefix="tg-async",
            )
    return _executor


def _drain_executor_atexit() -> None:
    """atexit hook — drain in-flight Telegram sends on shutdown.

    Without this, fire-and-forget messages submitted just before
    sys.exit() (e.g. premarket_health.py's failure alert) would be
    dropped when the daemon worker threads die with the process.
    """
    global _executor, _executor_drained
    with _executor_lock:
        ex = _executor
        # Mark drained even if the executor was never lazy-instantiated;
        # otherwise a never-used module would happily resurrect the pool
        # after `atexit` fired and fail to drain it on real shutdown.
        _executor_drained = True
        _executor = None
    if ex is None:
        return
    pending = _executor_submitted_count
    try:
        # Python 3.9+ supports cancel_futures=False (drain) by default.
        ex.shutdown(wait=True)
        logger.info(
            "[TELEGRAM] atexit drain complete — %d messages submitted "
            "during process lifetime",
            pending,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[TELEGRAM] atexit drain raised %s: %s — some messages may "
            "have been dropped",
            type(e).__name__, e,
        )


atexit.register(_drain_executor_atexit)


# ------------------------------------------------------------
# Env loading (House Rule #83)
# ------------------------------------------------------------
def _ensure_env_loaded() -> None:
    if ("TELEGRAM_TOKEN" in os.environ) and ("TELEGRAM_CHAT_ID" in os.environ):
        return
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass


_ensure_env_loaded()

TELEGRAM_TOKEN = (os.getenv("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
BOT_ID = (os.getenv("BOT_ID") or os.getenv("AUTOBOT_ID") or "AUTOBOT").strip()

# Per-host label prepended to every outbound message so the operator can
# tell which droplet sent it (both hosts trade the same IG account with
# separate bots). Escaped once at module load so HTML parse_mode is safe.
_raw_host_label = (os.getenv("ALERT_HOST_LABEL") or "").strip()
ALERT_HOST_LABEL = escape(_raw_host_label) if _raw_host_label else ""

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError(
        "Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID (check /opt/tradingbot/.env and systemd EnvironmentFile)."
    )

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


# ------------------------------------------------------------
# Formatting helpers (HTML-safe)
# ------------------------------------------------------------
def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _trim_number_str(s: str) -> str:
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_price(value: Any, decimals: int = 5) -> str:
    fv = _to_float(value)
    if fv is None:
        return "—"
    return _trim_number_str(f"{fv:.{decimals}f}")


def fmt_pips(value: Any, decimals: int = 1) -> str:
    fv = _to_float(value)
    if fv is None:
        return "—"
    sign = "+" if fv > 0 else ""
    return sign + _trim_number_str(f"{fv:.{decimals}f}")


def _fmt_utc_now() -> str:
    """
    Consistent timestamp for alerts.
    Using UTC so it's stable across droplets and matches trade logs (if any).
    """
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    except Exception:
        return "UTC_TIME_UNKNOWN"


# ------------------------------------------------------------
# Core sender
# ------------------------------------------------------------
def _do_send_blocking(message: str, parse_mode: str = "HTML") -> None:
    """Synchronous Telegram send with up to 3 attempts.

    Pre-refactor body of `send_telegram_message`; preserved verbatim so
    behavior is unchanged when invoked from the worker thread or from
    the `wait=True` path.

    Errors are logged at ERROR/WARNING and never re-raised.
    """
    text = message if message is not None else ""
    if ALERT_HOST_LABEL:
        text = f"[{ALERT_HOST_LABEL}] {text}"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    for _attempt in range(3):
        try:
            resp = requests.post(TELEGRAM_URL, json=payload, timeout=5)
            if resp.status_code == 200:
                return
            logger.error(f"Telegram API error [{resp.status_code}]: {resp.text}")
        except Exception as e:
            logger.warning(f"Telegram send error: {e}", exc_info=True)
        time.sleep(1)

    logger.error("Telegram send failed after 3 attempts.")


def send_telegram_message(
    message: str,
    parse_mode: str = "HTML",
    wait: bool = False,
) -> None:
    """Async-by-default Telegram send.

    Default (`wait=False`): submit the HTTP send to a module-level
    ThreadPoolExecutor and return immediately. The LS event-dispatch
    thread no longer blocks for up to 18s per send.

    Use `wait=True` only when downstream logic depends on the alert
    being delivered before the next decision (currently:
    LEG-ORPHAN-DETECTED in trade_executor.py — see
    `reports/ls_refactor_safety_audit_20260508.md` §4).

    Errors in the underlying send are logged and never re-raised, in
    either mode.
    """
    global _executor_submitted_count

    t0 = time.perf_counter()

    ex = _get_executor()
    if ex is None:
        # atexit drain has already run; fall back to inline send so a
        # late shutdown alert isn't dropped.
        _do_send_blocking(message, parse_mode)
        return

    try:
        fut = ex.submit(_do_send_blocking, message, parse_mode)
        _executor_submitted_count += 1
    except RuntimeError:
        # Executor shut down between _get_executor and submit (extremely
        # unlikely race, but cheap to handle).
        _do_send_blocking(message, parse_mode)
        return

    dispatch_ms = (time.perf_counter() - t0) * 1000.0
    if dispatch_ms > _TG_DISPATCH_LATENCY_WARN_MS:
        logger.warning(
            "[TELEGRAM] dispatch latency %.2fms exceeded %.1fms threshold — "
            "executor saturated?",
            dispatch_ms, _TG_DISPATCH_LATENCY_WARN_MS,
        )

    if wait:
        try:
            fut.result(timeout=_TG_WAIT_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            # Errors in the actual send are already logged by
            # _do_send_blocking; this catches the timeout case (Future
            # never completed within 20s).
            logger.warning(
                "[TELEGRAM] wait=True dispatch did not complete: %s: %s",
                type(e).__name__, e,
            )


def send(message: str) -> None:
    send_telegram_message(escape(message) if message is not None else "")


# ------------------------------------------------------------
# Alert helpers
# ------------------------------------------------------------
def send_trade_open_alert(
    epic: str,
    direction: str,
    size: Any,
    entry: Any,
    sl: Any,
    tp: Any,
    reason: str = "",
    mode: str = "",
    debug: dict | None = None,
    regime: dict | None = None,
) -> None:
    ts = _fmt_utc_now()
    lines = [
        f"🎯 <b>TRADE OPENED</b> <code>[{escape(BOT_ID)}]</code>",
        f"<b>Time:</b> {escape(ts)}",
        f"<b>Epic:</b> {escape(str(epic))}",
    ]
    if mode:
        lines.append(f"<b>Strategy:</b> {escape(str(mode))}")
    lines += [
        f"<b>Dir:</b> {escape(str(direction))}  |  <b>Size:</b> {escape(str(size))}",
        f"<b>Entry:</b> {fmt_price(entry)}",
    ]

    # Regime line — display-only, fail-soft. `regime` is expected to be a
    # small dict already assembled by the caller from values already in
    # scope (e.g. regime_engine.latest_result(pair) at fire time). No
    # engine calls or disk reads here. If anything is missing or the
    # format fails, emit "Regime: n/a" and continue — alert MUST send.
    try:
        _r = regime if isinstance(regime, dict) else {}
        _winner = _r.get("winning_regime")
        _winner_s = str(_winner).strip() if _winner else ""
        if not _winner_s:
            lines.append("<b>Regime:</b> n/a")
        else:
            _extras = []
            _path = _r.get("regime_label_path") or _r.get("label_path")
            if _path:
                _extras.append(str(_path).strip())
            _conf = _r.get("confidence_final")
            try:
                if _conf is not None:
                    _extras.append(f"conf {float(_conf):.2f}")
            except (TypeError, ValueError):
                pass
            if _extras:
                lines.append(
                    f"<b>Regime:</b> {escape(_winner_s)} "
                    f"({escape(', '.join(_extras))})"
                )
            else:
                lines.append(f"<b>Regime:</b> {escape(_winner_s)}")
    except Exception:
        lines.append("<b>Regime:</b> n/a")

    # Multi-level TP plan (from briefing_liquidity debug)
    if debug and debug.get("tp_plan"):
        def _or_na(v: Any) -> str:
            if v is None:
                return "n/a"
            s = str(v).strip()
            return s if s else "n/a"
        sl_price = _or_na(debug.get("sl_price"))
        sl_src = _or_na(debug.get("sl_source"))
        level_price = _or_na(debug.get("level_price"))
        level_src = _or_na(debug.get("level_source"))
        lines.append(f"<b>SL:</b> {fmt_pips(sl)} pips @ {escape(sl_price)} ({escape(sl_src)})")
        lines.append(f"<b>Level:</b> {escape(level_price)} ({escape(level_src)})")
        for i, t in enumerate(debug["tp_plan"], 1):
            lines.append(
                f"<b>TP{i}:</b> {fmt_pips(t['pips'])} pips @ {t['price']} ({escape(str(t['source']))})"
            )
    else:
        lines.append(f"<b>SL:</b> {fmt_pips(sl)} pips  |  <b>TP:</b> {fmt_pips(tp)} pips")

    # Matched briefing-levels-array entry (BB_REVERSAL and future levels-aware strategies)
    if debug and debug.get("briefing_level"):
        _bl = debug["briefing_level"]
        try:
            _bl_price = float(_bl.get("price"))
            _bl_type = str(_bl.get("type") or "").strip()
            _bl_intent = str(_bl.get("intent") or "").strip()
            _bl_strength = str(_bl.get("strength") or "").strip()
            if _bl_type and _bl_intent and _bl_strength:
                _dist = _bl.get("dist_pips")
                _dist_s = f"{float(_dist):.1f}p" if _dist is not None else "?"
                lines.append(
                    f"<b>\U0001f4d0 Level:</b> {_bl_price:.1f} "
                    f"({escape(_bl_type)} / {escape(_bl_intent)} / "
                    f"{escape(_bl_strength)}, {_dist_s} away)"
                )
        except (TypeError, ValueError):
            pass

    send_telegram_message("\n".join(lines))


def _normalize_close_args(args: Tuple[Any, ...], kwargs: dict) -> Tuple[str, Any, Any, Any, Any, str, str]:
    """
    Back-compat normalizer for send_trade_close_alert.

    Supports:
      New: (epic, direction, entry, exit_price, pnl_pips, pnl_cash=None, reason="")
      Old: (epic, exit_price, pnl_pips, pnl_cash=None, reason="")
      Kw variants: exit_price=..., pnl_pips=..., reason=...

    Returns:
      (direction, entry, exit_price, pnl_pips, pnl_cash, reason, mode)
      direction/entry/mode may be ""/None if not supplied.
    """
    reason = kwargs.get("reason", "")
    pnl_cash = kwargs.get("pnl_cash", None)
    mode = str(kwargs.get("mode", "") or "")

    if "exit_price" in kwargs and "pnl_pips" in kwargs:
        direction = str(kwargs.get("direction", "") or "")
        entry = kwargs.get("entry", None)
        exit_price = kwargs.get("exit_price", None)
        pnl_pips = kwargs.get("pnl_pips", None)
        return direction, entry, exit_price, pnl_pips, pnl_cash, str(reason), mode

    if len(args) >= 4:
        direction = str(args[0] or "")
        entry = args[1]
        exit_price = args[2]
        pnl_pips = args[3]
        if len(args) >= 5 and pnl_cash is None:
            pnl_cash = args[4]
        if len(args) >= 6 and (not reason):
            reason = args[5]
        return direction, entry, exit_price, pnl_pips, pnl_cash, str(reason), mode

    if len(args) >= 2:
        direction = ""
        entry = None
        exit_price = args[0]
        pnl_pips = args[1]
        if len(args) >= 3 and pnl_cash is None:
            pnl_cash = args[2]
        if len(args) >= 4 and (not reason):
            reason = args[3]
        return direction, entry, exit_price, pnl_pips, pnl_cash, str(reason), mode

    direction = str(kwargs.get("direction", "") or "")
    entry = kwargs.get("entry", None)
    exit_price = kwargs.get("exit_price", None)
    pnl_pips = kwargs.get("pnl_pips", None)
    return direction, entry, exit_price, pnl_pips, pnl_cash, str(reason), mode


def send_trade_close_alert(epic: str, *args: Any, **kwargs: Any) -> None:
    """
    Backwards compatible trade-close alert.

    Accepts both:
      send_trade_close_alert(epic, direction, entry, exit_price, pnl_pips, pnl_cash=None, reason="")
      send_trade_close_alert(epic, exit_price, pnl_pips, pnl_cash=None, reason="")
    Also accepts mode=, deal_id= as kwargs (silently ignored if not used).
    """
    direction, entry, exit_price, pnl_pips, pnl_cash, reason, mode = _normalize_close_args(args, kwargs)

    pnl_val = _to_float(pnl_pips)
    if pnl_val is None:
        emoji = "⚪️"
    elif pnl_val > 0:
        emoji = "🟢"
    elif pnl_val < 0:
        emoji = "🔴"
    else:
        emoji = "⚪️"

    ts = _fmt_utc_now()

    cash_part = ""
    if pnl_cash is not None and str(pnl_cash).strip() != "":
        cash_part = f"  |  <b>Cash:</b> {escape(str(pnl_cash))}"

    lines = [
        f"{emoji} <b>TRADE CLOSED</b> <code>[{escape(BOT_ID)}]</code>",
        f"<b>Time:</b> {escape(ts)}",
        f"<b>Epic:</b> {escape(str(epic))}",
    ]

    if mode:
        lines.append(f"<b>Strategy:</b> {escape(str(mode))}")

    if direction:
        lines.append(f"<b>Dir:</b> {escape(str(direction))}")

    if entry is not None and exit_price is not None:
        lines.append(f"<b>Entry:</b> {fmt_price(entry)}  →  <b>Exit:</b> {fmt_price(exit_price)}")
    elif exit_price is not None:
        lines.append(f"<b>Exit:</b> {fmt_price(exit_price)}")

    lines.append(f"<b>PnL:</b> {fmt_pips(pnl_pips)} pips{cash_part}")
    if reason:
        lines.append(f"<b>Reason:</b> {escape(str(reason))}")

    send_telegram_message("\n".join(lines))


def send_partial_exit_alert(epic: str, pct: Any, pnl_pips: Any, reason: str = "") -> None:
    ts = _fmt_utc_now()
    msg = (
        f"⚠️ <b>PARTIAL EXIT</b> <code>[{escape(BOT_ID)}]</code>\n"
        f"<b>Time:</b> {escape(ts)}\n"
        f"<b>Epic:</b> {escape(str(epic))}\n"
        f"<b>Closed:</b> {escape(str(pct))}%  |  <b>PnL:</b> {fmt_pips(pnl_pips)} pips\n"
        f"<b>Reason:</b> {escape(str(reason))}"
    )
    send_telegram_message(msg)


def send_status_update(text: str) -> None:
    ts = _fmt_utc_now()
    msg = f"📣 <b>Status</b> <code>[{escape(BOT_ID)}]</code>\n<b>Time:</b> {escape(ts)}\n{escape(str(text))}"
    send_telegram_message(msg)


def send_error_alert(text: str) -> None:
    ts = _fmt_utc_now()
    msg = f"🧯 <b>Error</b> <code>[{escape(BOT_ID)}]</code>\n<b>Time:</b> {escape(ts)}\n<pre>{escape(str(text))}</pre>"
    send_telegram_message(msg)


def send_daily_summary(text: str) -> None:
    ts = _fmt_utc_now()
    msg = f"📊 <b>Daily Summary</b> <code>[{escape(BOT_ID)}]</code>\n<b>Time:</b> {escape(ts)}\n{escape(str(text))}"
    send_telegram_message(msg)


def send_heartbeat(text: str = "AutoBot online ✅") -> None:
    ts = _fmt_utc_now()
    msg = f"💓 <b>Heartbeat</b> <code>[{escape(BOT_ID)}]</code>\n<b>Time:</b> {escape(ts)}\n{escape(str(text))}"
    send_telegram_message(msg)


def send_bot_online_alert() -> None:
    ts = _fmt_utc_now()
    send_telegram_message(f"✅ <b>AutoBot online</b> <code>[{escape(BOT_ID)}]</code>\n<b>Time:</b> {escape(ts)}")
