"""
news_tick_strategy.py — Tick-based news spike detection with stall/confirmation.

State machine:
  IDLE → ARMED → PREFLIGHT → SPIKE_DETECTED → STALL_DETECTED → ENTRY_FIRED

Fast path:  Finnhub actual vs forecast → enter immediately on data surprise.
Spike path: price moves ≥ NEWS_TICK_SPIKE_MIN_PIPS within 2 min of release
            → fire directly from price action (no Finnhub needed).
Slow path:  stall-and-confirm when spike detected outside the 2-min window.

Uses tick timestamps (ts param) for all timing — enables accurate backtesting.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import te_calendar

logger = logging.getLogger("AutoBot")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NEWS_TICK_ENABLED = str(os.getenv("NEWS_TICK_ENABLED", "1")).strip() in ("1", "true", "yes")
# Per-pair allowlist. Empty = all pairs (current default). Comma-separated
# list to restrict (e.g. "GBPUSD" for the live droplet).
_NEWS_TICK_PAIRS_RAW = os.getenv("NEWS_TICK_PAIRS", "").strip()
_NEWS_TICK_PAIRS: set = {
    p.strip().upper() for p in _NEWS_TICK_PAIRS_RAW.split(",") if p.strip()
}


def _is_pair_enabled(symbol: str) -> bool:
    """True if news_tick is enabled for this symbol. Empty allowlist = all."""
    if not _NEWS_TICK_PAIRS:
        return True
    return str(symbol).upper() in _NEWS_TICK_PAIRS
NEWS_TICK_SPIKE_MIN_PIPS = float(os.getenv("NEWS_TICK_SPIKE_MIN_PIPS", os.getenv("NEWS_SPIKE_MIN_PIPS", "8")))
NEWS_TICK_STALL_TICKS = int(os.getenv("NEWS_TICK_STALL_TICKS", "10"))
NEWS_TICK_CONFIRM_PIPS = float(os.getenv("NEWS_TICK_CONFIRM_PIPS", "5"))
NEWS_TICK_TIMEOUT_SECS = float(os.getenv("NEWS_TICK_TIMEOUT_SECS", "300"))
NEWS_TICK_SL_PIPS = float(os.getenv("NEWS_TICK_SL_PIPS", "20"))
NEWS_TICK_TP_PIPS = float(os.getenv("NEWS_TICK_TP_PIPS", "80"))
NEWS_TICK_ACTUAL_POLL_SECS = float(os.getenv("NEWS_TICK_ACTUAL_POLL_SECS", "5"))
NEWS_TICK_ACTUAL_TIMEOUT_SECS = float(os.getenv("NEWS_TICK_ACTUAL_TIMEOUT_SECS", "60"))
NEWS_TICK_FINNHUB_WINDOW_SECS = float(os.getenv("NEWS_TICK_FINNHUB_WINDOW_SECS", "10"))
NEWS_TICK_CONTINUATION_ONLY = str(os.getenv("NEWS_TICK_CONTINUATION_ONLY", "0")).strip() in ("1", "true", "yes")
NEWS_TICK_MAX_CONFIRM_SECS = float(os.getenv("NEWS_TICK_MAX_CONFIRM_SECS", "1800"))  # 30 minutes
NEWS_TICK_SHOCK_THRESHOLD = float(os.getenv("NEWS_TICK_SHOCK_THRESHOLD", "0.3"))  # 30% deviation
NEWS_TICK_SHOCK_WINDOW_SECS = float(os.getenv("NEWS_TICK_SHOCK_WINDOW_SECS", "3"))  # faster Finnhub poll
NEWS_TICK_SPIKE_WINDOW_SECS = float(os.getenv("NEWS_TICK_SPIKE_WINDOW_SECS", "120"))  # 2 min post-release: spike = signal
# ARMED-state expiry window post-release. Distinct from
# NEWS_TICK_SPIKE_WINDOW_SECS — the 2-min spike window is narrow enough
# that the 2026-04-23 GBP PMI, which peaked 14.8p above anchor at
# 08:31:50 then reached 15.3p only at ~08:35, missed the ARMED spike
# check because _expire_at=max(release+120, anchor+300)=08:32:00 had
# passed. Widened to 300s to let spike detection run the full 5 min.
NEWS_TICK_ARMED_RELEASE_WINDOW_SECS = float(os.getenv("NEWS_TICK_ARMED_RELEASE_WINDOW_SECS", "300"))
# Legacy stall-and-confirm chase path (rebuild 2026-04-29). With the
# rebuild, NEWS_TICK fires only on direction_hint=CONTINUATION (|dev|>5%)
# and cedes IN_LINE / no-actuals to NEWS_STRATEGY's tick-level fade.
# Set NEWS_TICK_LEGACY_STALL_PATH=1 to re-enable the pre-rebuild chase
# behaviour (spike-without-actuals + stall-and-confirm) — kept for
# rollback safety only.
NEWS_TICK_LEGACY_STALL_PATH = str(os.getenv("NEWS_TICK_LEGACY_STALL_PATH", "0")).strip() in ("1", "true", "yes")
# Observable-only mode (rebuild 2026-04-29). With NEWS_OBSERVABLE_ONLY=1
# the strategy logs WOULD_FIRE and returns None instead of placing a
# real trade. Default observable until promotion criteria met.
NEWS_OBSERVABLE_ONLY = str(os.getenv("NEWS_OBSERVABLE_ONLY", "1")).strip() in ("1", "true", "yes")

# Minimum TP distance for TIGHT_TP late-entry guard. If price has already
# drifted toward the anchor-based TP target by fire time, the computed
# tp_pips (distance from entry to fixed anchor±20p level) can shrink to
# 2-5 pips. IG's MIN_LIMIT_DISTANCE_PIPS prevents placement below that
# floor, but once placed a 2p TP can fill near the spike top on a normal
# tick oscillation — micro-win with full SL risk. Widen to this floor at
# the strategy layer so late entries still carry meaningful reward.
MIN_TIGHT_TP_PIPS = float(os.getenv("NEWS_TICK_MIN_TIGHT_TP_PIPS", "8"))

# Pre-spike Finnhub entry: fire on data surprise BEFORE price spike
NEWS_PREFLIGHT_ENABLED = str(os.getenv("NEWS_PREFLIGHT_ENABLED", "1")).strip() in ("1", "true", "yes")
NEWS_PREFLIGHT_POLL_SECS = float(os.getenv("NEWS_PREFLIGHT_POLL_SECS", "3"))
NEWS_PREFLIGHT_FALLBACK_SL = float(os.getenv("NEWS_PREFLIGHT_FALLBACK_SL", "20"))
NEWS_PREFLIGHT_FALLBACK_TP = float(os.getenv("NEWS_PREFLIGHT_FALLBACK_TP", "60"))
NEWS_PREFLIGHT_SETTLE_SECS = float(os.getenv("NEWS_PREFLIGHT_SETTLE_SECS", "60"))
# Tight SL for PREFLIGHT entries — these fire on data surprise BEFORE the
# spike develops, so direction conviction is high but volatility may not be.
# Spike-window and stall-confirm fallbacks keep the wider 20p SL because
# they fire on less-certain signals.
NEWS_TICK_PREFLIGHT_SL_PIPS = float(os.getenv("NEWS_TICK_PREFLIGHT_SL_PIPS", "10"))
NEWS_TICK_PREFLIGHT_SL_PIPS_JPY = float(os.getenv("NEWS_TICK_PREFLIGHT_SL_PIPS_JPY", "15"))

# Levels-array entry gate (parity with BB_REVERSAL / BRIEFING_LIQUIDITY
# contract, but FAIL-OPEN on missing/empty levels array — a news spike far
# from any pre-briefed level is still a valid trade).
# Wider default than BB_REVERSAL (8p): news spikes can carry price 10-15+
# pips past the briefed level before a stall.
NEWS_TICK_LEVELS_PROXIMITY_PIPS = float(
    os.getenv("NEWS_TICK_LEVELS_PROXIMITY_PIPS", "15") or 15.0
)
_LEVELS_ACCEPTED_INTENTS   = ("BOUNCE", "FADE")
_LEVELS_ACCEPTED_STRENGTHS = ("HIGH", "MEDIUM")

# ---------------------------------------------------------------------------
# Currency → pair direction mapping for PREFLIGHT
# ---------------------------------------------------------------------------
# Key: (event_currency, beat_miss)
# Value: dict of {pair: signal} for affected pairs only
_PREFLIGHT_DIRECTION: Dict[tuple, Dict[str, str]] = {
    # USD events affect all major pairs
    ("USD", "BEAT"):  {"GBPUSD": "SELL", "EURUSD": "SELL", "USDJPY": "BUY",  "USDCAD": "BUY",  "GBPJPY": "SELL"},
    ("USD", "MISS"):  {"GBPUSD": "BUY",  "EURUSD": "BUY",  "USDJPY": "SELL", "USDCAD": "SELL", "GBPJPY": "BUY"},
    # GBP events affect GBPUSD and GBPJPY
    ("GBP", "BEAT"):  {"GBPUSD": "BUY",  "GBPJPY": "BUY"},
    ("GBP", "MISS"):  {"GBPUSD": "SELL", "GBPJPY": "SELL"},
    # EUR events affect EURUSD only
    ("EUR", "BEAT"):  {"EURUSD": "BUY"},
    ("EUR", "MISS"):  {"EURUSD": "SELL"},
    # JPY events affect USDJPY and GBPJPY
    ("JPY", "BEAT"):  {"USDJPY": "SELL", "GBPJPY": "SELL"},
    ("JPY", "MISS"):  {"USDJPY": "BUY",  "GBPJPY": "BUY"},
    # CAD events affect USDCAD only
    ("CAD", "BEAT"):  {"USDCAD": "SELL"},
    ("CAD", "MISS"):  {"USDCAD": "BUY"},
}

# Which pairs are affected by each event currency
_AFFECTED_PAIRS: Dict[str, set] = {
    "USD": {"GBPUSD", "EURUSD", "USDJPY", "USDCAD", "GBPJPY"},
    "GBP": {"GBPUSD", "GBPJPY"},
    "EUR": {"EURUSD"},
    "JPY": {"USDJPY", "GBPJPY"},
    "CAD": {"USDCAD"},
}


def get_preflight_signal(event_currency: str, beat_miss: str, symbol: str) -> Optional[str]:
    """Return BUY/SELL for a symbol given event currency and beat/miss, or None if unaffected."""
    key = (event_currency.upper(), beat_miss.upper())
    mapping = _PREFLIGHT_DIRECTION.get(key, {})
    return mapping.get(symbol.upper())


def is_pair_affected(event_currency: str, symbol: str) -> bool:
    """Return True if the symbol is affected by events in the given currency."""
    return symbol.upper() in _AFFECTED_PAIRS.get(event_currency.upper(), set())


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
_IDLE = "IDLE"
_ARMED = "ARMED"
_PREFLIGHT = "PREFLIGHT"  # polling Finnhub before spike, awaiting data
_SPIKE = "SPIKE_DETECTED"
_STALL = "STALL_DETECTED"
_FIRED = "ENTRY_FIRED"

_state: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Per-event dedup set (Fix 1) — prevents re-evaluating the same (pair, event,
# direction) once a terminal decision (fire or briefing-block) has been made.
# Cleared at UTC midnight via _reset_processed_if_new_day().
# ---------------------------------------------------------------------------
_processed_news_events: set = set()
_last_reset_day: str = ""

# LS-thread refactor (2026-05-08): per the safety audit (§1), this set is
# mutated from per-pair workers via tick_update(). CPython set.add() is
# atomic, but the day-rollover read-clear-set is not — wrap mutations in
# this small lock so two workers cannot race the midnight reset.
_NEWS_TICK_DEDUP_LOCK: threading.Lock = threading.Lock()


def _get(sym: str) -> Dict[str, Any]:
    k = sym.upper()
    if k not in _state:
        _state[k] = {"phase": _IDLE}
    return _state[k]


def _reset_processed_if_new_day(ts: float) -> None:
    """Clear _processed_news_events at the UTC day boundary."""
    global _last_reset_day
    try:
        from datetime import datetime as _dt
        today = _dt.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return
    # Lock the read-modify-write so two pair-workers can't both clear.
    with _NEWS_TICK_DEDUP_LOCK:
        if today != _last_reset_day:
            if _last_reset_day:
                logger.info(
                    "[NEWS-TICK] UTC midnight reset — clearing %d processed events (was %s)",
                    len(_processed_news_events), _last_reset_day,
                )
            _processed_news_events.clear()
            _last_reset_day = today


def _event_key(sym: str, release_epoch: float, direction: str = "") -> str:
    """Per-(pair, event) dedup key.

    Direction is intentionally ignored (kept as a positional arg for caller
    backwards-compat) so PREFLIGHT, spike-window, and stall-confirm collectively
    fire at most once per (pair, event). If PREFLIGHT misses and a later path
    detects an opposite-direction signal on the same release, it is blocked.
    """
    from datetime import datetime as _dt
    try:
        hhmm = _dt.utcfromtimestamp(release_epoch).strftime("%H:%M")
    except Exception:
        hhmm = "??:??"
    return f"{sym.upper()}_{hhmm}"


def _is_past_avoid_before(ts: float, avoid_before) -> bool:
    """True if the tick time is at or past any HH:MM avoid_before cutoff today."""
    if not avoid_before:
        return False
    from datetime import datetime as _dt, timezone as _tz
    try:
        now_dt = _dt.utcfromtimestamp(ts).replace(tzinfo=_tz.utc)
    except Exception:
        return False
    for t in avoid_before:
        try:
            parts = str(t).split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
        except Exception:
            continue
        cutoff = now_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now_dt >= cutoff:
            return True
    return False


def _match_levels_array(
    briefing: Optional[Dict[str, Any]],
    entry_price: float,
    signal_direction: str,
    ppp: float,
    max_pips: float,
) -> Optional[Dict[str, Any]]:
    """Same gating contract as BB_REVERSAL / BRIEFING_LIQUIDITY:
      - entry.trade_direction == signal_direction
      - entry.intent in {BOUNCE, FADE}
      - entry.strength in {HIGH, MEDIUM}
      - |entry.price - entry_price| / ppp <= max_pips

    Returns the matched entry with added `dist_pips`, else None. Treats
    missing/empty `levels` as None (callers decide fail-open vs fail-closed).
    """
    if briefing is None:
        return None
    arr = briefing.get("levels")
    if not isinstance(arr, list) or not arr:
        return None

    want_dir = str(signal_direction).upper()
    best: Optional[Dict[str, Any]] = None
    best_dist = float("inf")
    for lv in arr:
        if not isinstance(lv, dict):
            continue
        if str(lv.get("trade_direction", "")).upper() != want_dir:
            continue
        if str(lv.get("intent", "")).upper() not in _LEVELS_ACCEPTED_INTENTS:
            continue
        if str(lv.get("strength", "")).upper() not in _LEVELS_ACCEPTED_STRENGTHS:
            continue
        try:
            price = float(lv["price"])
        except (TypeError, ValueError, KeyError):
            continue
        dist_pips = abs(price - entry_price) / ppp
        if dist_pips <= max_pips and dist_pips < best_dist:
            best = {**lv, "dist_pips": dist_pips}
            best_dist = dist_pips
    return best


def _levels_array_gate(
    sym: str, signal: str, mid: float, ppp: float,
) -> tuple:
    """Return (reason, match) for the briefing levels-array gate.

    - (None, dict) — match found, allow entry with attached level
    - (reason_str, None) — levels array present but no qualifying match → BLOCK
    - (None, None) — briefing missing, or levels array missing/empty → FAIL-OPEN
      (NEWS_TICK fires on data surprises that may print far from any briefed level)
    """
    try:
        import morning_briefing
        briefing = morning_briefing.get_briefing(sym) or None
    except Exception:
        return None, None
    if not briefing:
        return None, None
    arr = briefing.get("levels")
    if not isinstance(arr, list) or not arr:
        return None, None

    match = _match_levels_array(
        briefing, mid, signal, ppp, NEWS_TICK_LEVELS_PROXIMITY_PIPS,
    )
    if match is None:
        return (
            f"no_levels_match_within_{NEWS_TICK_LEVELS_PROXIMITY_PIPS:.0f}p "
            f"price={mid:.1f}"
        ), None
    return None, match


def _level_line(match: Optional[Dict[str, Any]]) -> str:
    """Render a matched briefing level as a single Telegram line, or '' if none."""
    if not match:
        return ""
    try:
        price = float(match.get("price"))
        dist = match.get("dist_pips")
        dist_s = f"{float(dist):.1f}p" if dist is not None else "?"
        return (
            f"\n\U0001f4d0 Level: {price:.1f} "
            f"({match.get('type', '')} / {match.get('intent', '')} / "
            f"{match.get('strength', '')}, {dist_s} away)"
        )
    except (TypeError, ValueError):
        return ""


def _briefing_blocks_entry(sym: str, signal: str, ts: float) -> Optional[str]:
    """Return a skip reason based on the current briefing, or None.

    NEWS_TICK fires on post-release data surprises. Two briefing fields are
    consulted but only advisorily — neither blocks entry:

      avoid_before:   logged for attribution; NEWS_TICK's whole purpose is
                      the HIGH-risk post-release window.
      signal_filter:  the briefing's technical bias has no authority over
                      a direct data-surprise entry. Removed 2026-04-21.

    Fail-open: no briefing or read error → no extra gate. This function
    remains as a hook for genuinely-blocking briefing fields if any are
    added in future.
    """
    try:
        import morning_briefing
        briefing = morning_briefing.get_briefing(sym) or {}
    except Exception:
        return None
    if not briefing:
        return None
    news_risk = str(briefing.get("news_risk") or "").upper()
    if news_risk == "HIGH":
        news_ctx = briefing.get("news_context") or {}
        avoid = news_ctx.get("avoid_before") or []
        if _is_past_avoid_before(ts, avoid):
            logger.info(
                "[NEWS-TICK] %s entry past avoid_before cutoff %s — proceeding "
                "(avoid_before is advisory for NEWS_TICK)",
                sym, list(avoid),
            )
    return None


def _pre_entry_gate(
    sym: str, release_epoch: float, signal: str, ts: float,
    mid: float, ppp: float,
) -> tuple:
    """Combined dedup + briefing gate.

    Returns (skip_reason_or_None, matched_level_or_None).

    Side effect: on any block, records the (pair, event, direction) key in
    _processed_news_events so subsequent ticks short-circuit silently.

    The briefing levels-array is inspected ONLY to attach context to the
    Telegram alert — it never blocks. News spikes print far from any
    pre-briefed level by design.
    """
    key = _event_key(sym, release_epoch, signal)
    if key in _processed_news_events:
        return f"already_processed:{key}", None
    # Advisory briefing check — currently only emits the avoid_before log;
    # all blocking paths were removed 2026-04-21. Function retained as a
    # hook for future genuinely-blocking briefing fields.
    _briefing_blocks_entry(sym, signal, ts)
    # Levels-array is informational only — match is returned for Telegram
    # display but a miss no longer blocks the entry.
    _, match = _levels_array_gate(sym, signal, mid, ppp)
    return None, match


def _mark_event_processed(sym: str, release_epoch: float, signal: str) -> None:
    # set.add is CPython-atomic but use the lock for visibility consistency
    # with the day-reset path that also holds it.
    with _NEWS_TICK_DEDUP_LOCK:
        _processed_news_events.add(_event_key(sym, release_epoch, signal))


def _handle_pre_entry_block(sym: str, signal: str, reason: str) -> None:
    """Log + Telegram for a fresh block (never for `already_processed` — silent)."""
    if reason.startswith("already_processed:"):
        return
    # Levels-array rejects use the NEWS-REJECT tag to match the PIERCE-REJECT
    # convention used by BB_REVERSAL / BRIEFING_LIQUIDITY.
    if reason.startswith("no_levels_match_within_"):
        logger.info("[NEWS-TICK] NEWS-REJECT %s %s reason=%s", sym, signal, reason)
    else:
        logger.info("[NEWS-TICK] %s ENTRY BLOCKED — %s (signal=%s)", sym, reason, signal)
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(
            f"🚫 <b>NEWS_TICK entry blocked</b>\n"
            f"Pair: <code>{sym}</code> {signal}\n"
            f"Reason: {reason}"
        )
    except Exception:
        pass


def _reset(sym: str, reason: str = "") -> None:
    k = sym.upper()
    old = _state.get(k, {}).get("phase", _IDLE)
    _state[k] = {"phase": _IDLE}
    if old != _IDLE:
        logger.info("[NEWS-TICK] %s %s → IDLE (%s)", sym, old, reason)
        _persist_state()


def reset_all() -> None:
    for sym in list(_state):
        _reset(sym, "reset_all")


_STATE_FILE = "/opt/tradingbot/cache/news_tick_state.json"
# Serializable keys to persist (skip non-JSON-safe values)
_PERSIST_KEYS = {"phase", "anchor", "anchor_time", "armed_time", "release_epoch",
                 "event_currency", "event_titles", "spike_dir", "spike_extreme",
                 "spike_time", "stall_price", "stall_time", "no_new_extreme_count",
                 "_preflight_done", "_actual_timeout_logged"}


def _persist_state() -> None:
    """Write current state to disk (best-effort, non-blocking)."""
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        serializable = {}
        for sym, st in _state.items():
            serializable[sym] = {k: v for k, v in st.items() if k in _PERSIST_KEYS}
        with open(_STATE_FILE, "w") as f:
            json.dump({"ts": time.time(), "state": serializable}, f)
    except Exception as e:
        logger.debug("[NEWS-TICK] State persist failed: %s", e)


def _load_persisted_state() -> None:
    """Load state from disk on startup. Ignores stale files (>10 min old)."""
    global _state
    try:
        with open(_STATE_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > 600:
            logger.info("[NEWS-TICK] Persisted state too old (>10 min) — starting fresh")
            return
        for sym, st in data.get("state", {}).items():
            if st.get("phase", _IDLE) != _IDLE:
                _state[sym.upper()] = st
                logger.info("[NEWS-TICK] Restored %s state: phase=%s", sym, st.get("phase"))
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug("[NEWS-TICK] State load failed: %s", e)


# Load persisted state on import
_load_persisted_state()


# TIGHT_TP event keyword list (case-insensitive substring match). These
# are slow-burn economic releases that historically move 10-25p over
# 30-60 min rather than a fast spike. A fixed 20p TP from anchor
# captures the realistic reaction without hoping for a 60-120p move
# that rarely develops. GBP PMI on 2026-04-23 drifted 13488→13507 over
# 20 min with a peak single-5m-bar body of only 11.6p — classic TIGHT.
_TIGHT_TP_EVENT_KEYWORDS = (
    "pmi",                  # Manufacturing / Services / Composite / S&P / ISM
    "ism",
    "consumer confidence",
    "consumer sentiment",
    "michigan",
    "industrial production",
)


def _is_tight_tp_event(event_titles) -> bool:
    """Return True if any event title matches a TIGHT_TP keyword.
    Safe default: empty/None title list returns False (→ WIDE_TP)."""
    if not event_titles:
        return False
    for title in event_titles:
        if not title:
            continue
        lo = str(title).lower()
        for kw in _TIGHT_TP_EVENT_KEYWORDS:
            if kw in lo:
                return True
    return False


def _build_entry(signal, entry_price, spike_dir, anchor, extreme, ppp, reason_tag,
                 te_result=None, stall_price=None, move_from_stall=None,
                 briefing_level=None, sl_override=None,
                 event_titles=None, symbol=None):
    """Build the entry dict returned to autobot.

    Routing:
      - TIGHT_TP events (PMI / ISM / sentiment / industrial production):
        SL = 6 pips from entry, TP = anchor ± 20 pips (fixed absolute level).
        Late-entry guard: if the anchor-based TP would be < MIN_TIGHT_TP_PIPS
        from entry (price drifted too far before fire), TP widens to
        entry ± MIN_TIGHT_TP_PIPS. Prevents micro-wins on late fills.
        Takes priority over sl_override.
      - sl_override set (e.g. PREFLIGHT path): fixed SL via override,
        spike-proportional TP.
      - Default (WIDE): SL = 50% of spike (clamped 15-25p), TP = 1.5× spike
        (clamped 30-120p).
    """
    spike_pips = abs(extreme - anchor) / ppp
    tight_tp = _is_tight_tp_event(event_titles)

    if tight_tp:
        # TIGHT: 6-pip SL from entry, anchor-based TP. Anchor offset reduced
        # from 20 → 10 on 2026-04-28 after the early-exit diagnostic; the
        # MIN_TIGHT_TP_PIPS=8 late-entry guard still floors the effective TP.
        sl_pips = 6.0
        if signal == "BUY":
            sl_price = entry_price - sl_pips * ppp
            tp_price = anchor + 10.0 * ppp
        else:
            sl_price = entry_price + sl_pips * ppp
            tp_price = anchor - 10.0 * ppp
        tp_pips = abs(tp_price - entry_price) / ppp
        # Late-entry guard — widen TP if anchor-based level is too close.
        if tp_pips < MIN_TIGHT_TP_PIPS:
            _original_tp_pips = tp_pips
            tp_pips = MIN_TIGHT_TP_PIPS
            if signal == "BUY":
                tp_price = entry_price + tp_pips * ppp
            else:
                tp_price = entry_price - tp_pips * ppp
            logger.info(
                "[NEWS-TICK] [TIGHT-TP] %s late entry: anchor-TP would be "
                "%.1fp from entry, widened to %.1fp minimum",
                symbol or "?", _original_tp_pips, MIN_TIGHT_TP_PIPS,
            )
    else:
        # WIDE path. SL is spike-proportional; TP is env-driven (was
        # max(30, min(120, spike*1.5)) — reduced to NEWS_TICK_TP_PIPS=12 on
        # 2026-04-28 after observing median peak favourable was 6.8p over
        # the 30-min hold window for 5 REGIME_MAX_HOLD-closed trades).
        if sl_override is not None and sl_override > 0:
            sl_pips = float(sl_override)
        else:
            sl_pips = max(15.0, min(25.0, spike_pips * 0.5))
        tp_pips = float(NEWS_TICK_TP_PIPS)
        if signal == "BUY":
            sl_price = entry_price - sl_pips * ppp
            tp_price = entry_price + tp_pips * ppp
        else:
            sl_price = entry_price + sl_pips * ppp
            tp_price = entry_price - tp_pips * ppp

    debug = {
        "spike_dir": spike_dir, "anchor": anchor,
        "spike_extreme": extreme,
        "spike_pips": spike_pips,
        "reason_tag": reason_tag,
        "entry_source": f"news_tick_{reason_tag}",
        "tight_tp": tight_tp,
        "event_titles": list(event_titles) if event_titles else [],
    }
    if te_result:
        debug.update({
            "te_actual": te_result.get("actual"),
            "te_forecast": te_result.get("forecast"),
            "te_deviation": te_result.get("deviation"),
            "te_beat_miss": te_result.get("beat_miss"),
        })
    if stall_price is not None:
        debug["stall_price"] = stall_price
        debug["move_from_stall"] = move_from_stall
    if briefing_level is not None:
        debug["briefing_level"] = briefing_level

    return {
        "signal": signal, "entry": entry_price,
        "sl": sl_pips, "tp": tp_pips,
        "sl_price": sl_price, "tp_price": tp_price,
        "reason": f"news_tick_{reason_tag}_{signal.lower()}",
        "entry_source": f"news_tick_{reason_tag}",
        "debug": debug,
    }


def _send_telegram(sym, signal, entry_price, reason_tag, spike_dir, spike_pips,
                   te_result=None, stall_price=None, move_from_stall=None,
                   match=None, event_titles=None, anchor=None, ppp=None):
    try:
        from telegram_alerts import send_telegram_message
        _lvl = _level_line(match)
        _tight_tp = _is_tight_tp_event(event_titles)
        _tight_tag = " [TIGHT-TP]" if _tight_tp else ""
        # Compute display SL/TP to match _build_entry routing. For WIDE we
        # show the env display values (same as pre-fix). For TIGHT we show
        # the actual 6p SL and anchor-based TP distance.
        if _tight_tp and anchor is not None and ppp:
            _sl_p = 6.0
            _tp_p = abs((anchor + (20.0 if signal == "BUY" else -20.0) * ppp) - entry_price) / ppp
            _anchor_line = f"  anchor={anchor:.1f}"
        else:
            _sl_p = NEWS_TICK_SL_PIPS
            _tp_p = NEWS_TICK_TP_PIPS
            _anchor_line = ""
        if te_result and reason_tag == "te_continuation":
            dev_pct = (te_result.get("deviation") or 0) * 100
            send_telegram_message(
                f"⚡ NEWS_TICK{_tight_tag} {signal} {sym} @ {entry_price:.1f}\n"
                f"📊 {te_result['te_event']}: actual={te_result['actual_str']} "
                f"forecast={te_result['forecast_str']} ({dev_pct:+.1f}%)\n"
                f"📈 {te_result['beat_miss']} → CONTINUATION {spike_dir}\n"
                f"SL={_sl_p:.0f}p TP={_tp_p:.0f}p{_anchor_line}"
                f"{_lvl}"
            )
        else:
            te_info = ""
            if te_result:
                dev_pct = (te_result.get("deviation") or 0) * 100
                te_info = (f"\n📊 {te_result['te_event']}: actual={te_result['actual_str']} "
                           f"forecast={te_result['forecast_str']} ({dev_pct:+.1f}%) → {te_result['beat_miss']}")
            else:
                te_info = "\n📊 No actual available — direction from price action"
            stall_info = f", stall@{stall_price:.1f}, move={move_from_stall:+.1f}p" if stall_price else ""
            send_telegram_message(
                f"⚡ NEWS_TICK{_tight_tag} {signal} {sym} @ {entry_price:.1f}\n"
                f"📈 {reason_tag.upper()} (spike {spike_dir} {spike_pips:.0f}p{stall_info})"
                f"{te_info}\n"
                f"SL={_sl_p:.0f}p TP={_tp_p:.0f}p{_anchor_line}"
                f"{_lvl}"
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main tick handler — all timing uses ts (tick timestamp), not time.time()
# ---------------------------------------------------------------------------
def tick_update(
    symbol: str,
    mid: float,
    bid: float,
    ask: float,
    ts: float,
    ppp: float,
    is_blackout: bool,
    blackout_reason: str,
) -> Optional[Dict[str, Any]]:
    """Called on every tick. Returns a trade dict or None."""
    if not NEWS_TICK_ENABLED:
        return None
    if not _is_pair_enabled(symbol):
        return None

    _reset_processed_if_new_day(ts)

    sym = symbol.upper()
    st = _get(sym)

    # ------------------------------------------------------------------
    # IDLE → ARMED (arms from news calendar OR legacy blackout flag)
    # ------------------------------------------------------------------
    if st["phase"] == _IDLE:
        _should_arm = False
        _event_currency = "USD"
        _event_titles = []
        _release_epoch = ts + 300

        # Primary: check news calendar for high-impact event within 5 min
        try:
            import news_calendar
            from datetime import datetime, timezone
            events = news_calendar.get_todays_events()
            high_events = [e for e in events if e.get("impact") == "High"]
            if high_events:
                _now_dt = datetime.utcfromtimestamp(ts).replace(tzinfo=timezone.utc)
                for ev in high_events:
                    try:
                        _h, _mi = map(int, ev["time"].split(":"))
                        _ev_dt = _now_dt.replace(hour=_h, minute=_mi, second=0, microsecond=0)
                        _secs_until = (_ev_dt - _now_dt).total_seconds()
                        # Arm if event is within 5 min ahead or 2 min past
                        if -120 <= _secs_until <= 300:
                            _should_arm = True
                            _event_currency = ev.get("currency", "USD").upper()
                            _event_titles = [e.get("event_name", "") for e in high_events
                                             if e.get("currency", "").upper() == _event_currency]
                            _release_epoch = _ev_dt.timestamp()
                            break
                    except Exception:
                        continue
        except Exception:
            pass

        # Fallback: legacy blackout flag (if NEWS_BLACKOUT_MINUTES > 0)
        if not _should_arm and is_blackout:
            _should_arm = True
            try:
                import news_calendar
                events = news_calendar.get_todays_events()
                high_events = [e for e in events if e.get("impact") == "High"]
                _event_titles = [e.get("event_name", "") for e in high_events]
                if high_events:
                    _event_currency = high_events[0].get("currency", "USD").upper()
            except Exception:
                pass
            import re
            _m = re.search(r'news@(\d{2}):(\d{2})UTC', blackout_reason)
            if _m:
                from datetime import datetime, timezone
                _now_dt = datetime.utcfromtimestamp(ts).replace(tzinfo=timezone.utc)
                _rel_dt = _now_dt.replace(hour=int(_m.group(1)), minute=int(_m.group(2)), second=0, microsecond=0)
                _release_epoch = _rel_dt.timestamp()

        if not _should_arm:
            return None

        # Only arm if this pair is affected by the event currency
        if not is_pair_affected(_event_currency, sym):
            logger.debug(
                "[NEWS-TICK] %s skipping arm: %s event does not affect %s",
                sym, _event_currency, sym,
            )
            return None

        st["phase"] = _ARMED
        st["anchor"] = mid
        st["anchor_time"] = ts
        st["armed_time"] = ts
        st["te_result"] = None
        st["_actual_timeout_logged"] = False
        st["event_currency"] = _event_currency
        st["event_titles"] = _event_titles
        st["release_epoch"] = _release_epoch

        _persist_state()

        logger.info(
            "[NEWS-TICK] %s IDLE → ARMED  anchor=%.1f  ccy=%s  release_in=%.0fs  events=%s",
            sym, mid, _event_currency, _release_epoch - ts, _event_titles,
        )
        return None

    # ------------------------------------------------------------------
    # ARMED → PREFLIGHT (if enabled) or SPIKE_DETECTED
    # ------------------------------------------------------------------
    if st["phase"] == _ARMED:
        _expire_at = max(st.get("release_epoch", 0) + NEWS_TICK_ARMED_RELEASE_WINDOW_SECS,
                         st["anchor_time"] + NEWS_TICK_TIMEOUT_SECS)
        if not is_blackout and ts > _expire_at:
            _reset(sym, "armed_timeout")
            return None

        # Transition to PREFLIGHT once we're past the release time
        release_epoch = st.get("release_epoch", 0)
        if NEWS_PREFLIGHT_ENABLED and ts >= release_epoch and not st.get("_preflight_done"):
            st["phase"] = _PREFLIGHT
            st["preflight_start"] = ts
            st["_preflight_last_poll"] = 0
            logger.info("[NEWS-TICK] %s ARMED → PREFLIGHT  polling Finnhub every %.0fs", sym, NEWS_PREFLIGHT_POLL_SECS)
            _persist_state()
            # Fall through immediately to PREFLIGHT handler below

        # 2026-04-29 rebuild: ARMED→SPIKE price transition is the entry
        # to the legacy stall-and-confirm chase path. Default OFF — when
        # PREFLIGHT cedes IN_LINE / no-actuals to NEWS_STRATEGY, we don't
        # want a delayed price-based transition to re-engage the chase.
        if st["phase"] == _ARMED and NEWS_TICK_LEGACY_STALL_PATH:
            diff_pips = (mid - st["anchor"]) / ppp
            if abs(diff_pips) >= NEWS_TICK_SPIKE_MIN_PIPS:
                spike_dir = "UP" if diff_pips > 0 else "DOWN"
                st["phase"] = _SPIKE
                st["spike_dir"] = spike_dir
                st["spike_extreme"] = mid
                st["spike_time"] = ts
                st["no_new_extreme_count"] = 0
                logger.info(
                    "[NEWS-TICK] %s ARMED → SPIKE  dir=%s  move=%.1fp  anchor=%.1f  tick=%.1f  (legacy stall path)",
                    sym, spike_dir, abs(diff_pips), st["anchor"], mid,
                )
            return None
        if st["phase"] == _ARMED:
            return None

    # ------------------------------------------------------------------
    # PREFLIGHT — poll Finnhub before spike, fire on data surprise
    # ------------------------------------------------------------------
    if st["phase"] == _PREFLIGHT:
        _expire_at = max(st.get("release_epoch", 0) + NEWS_TICK_ARMED_RELEASE_WINDOW_SECS,
                         st["anchor_time"] + NEWS_TICK_TIMEOUT_SECS)
        if not is_blackout and ts > _expire_at:
            _reset(sym, "preflight_timeout")
            return None

        since_preflight = ts - st["preflight_start"]

        # Poll Finnhub aggressively
        te_result = st.get("te_result")
        if te_result is None and (ts - st.get("_preflight_last_poll", 0)) >= NEWS_PREFLIGHT_POLL_SECS:
            st["_preflight_last_poll"] = ts
            te_calendar.poll_for_actual(min_interval=NEWS_PREFLIGHT_POLL_SECS)
            _event_ccy = st.get("event_currency", "")
            for title in st.get("event_titles", []):
                te_data = te_calendar.get_actual_for_event(title, currency=_event_ccy)
                if te_data and te_data.get("direction_hint"):
                    st["te_result"] = te_data
                    te_result = te_data
                    _dev = abs(te_data.get("deviation") or 0)
                    logger.info(
                        "[NEWS-TICK] %s PREFLIGHT ACTUAL (%.0fs after release): "
                        "%s=%s forecast=%s dev=%.1f%% → %s (%s)",
                        sym, since_preflight,
                        te_data["te_event"], te_data["actual_str"],
                        te_data["forecast_str"], _dev * 100,
                        te_data["direction_hint"], te_data["beat_miss"],
                    )
                    break

        # Fire immediately on CONTINUATION (data surprise). 2026-04-29
        # rebuild: direction is derived from the actuals' currency-action
        # (good_for_currency × pair sign), NOT from current price move.
        # The pre-rebuild logic flipped direction to whichever way price
        # had already moved 2+ pips, which on positioning shakeouts (BoC
        # 2026-04-29 IN_LINE: USDCAD spiked +20p then full retrace) put
        # NEWS_TICK on the wrong side. By the partition, NEWS_TICK now
        # only sees CONTINUATION (|dev|>5%); IN_LINE / no-actuals are
        # ceded to NEWS_STRATEGY's fade path.
        if te_result and te_result.get("direction_hint") == "CONTINUATION":
            _dev = abs(te_result.get("deviation") or 0)
            diff_pips = (mid - st["anchor"]) / ppp
            _event_ccy = st.get("event_currency", "USD")
            _beat_miss = te_result.get("beat_miss", "BEAT")
            _event_name_for_dir = (
                te_result.get("te_event")
                or (st.get("event_titles") or [""])[0]
            )
            try:
                from news_strategy import (
                    good_for_currency as _good_for_currency,
                    trade_direction_from_currency_action as _trade_dir_from_action,
                    continuation_magnitude as _continuation_magnitude,
                )
                _action = _good_for_currency(_event_name_for_dir, _beat_miss)
                signal = _trade_dir_from_action(_event_ccy, sym, _action)
            except (ValueError, ImportError) as _dir_exc:
                logger.info(
                    "[NEWS-TICK] %s PREFLIGHT: direction lookup failed (%s); skipping",
                    sym, _dir_exc,
                )
                st["phase"] = _ARMED
                st["_preflight_done"] = True
                return None
            spike_dir = "UP" if signal == "BUY" else "DOWN"

            spike_pips = max(abs(diff_pips), 1.0)
            _tag = "PREFLIGHT_SHOCK" if _dev >= NEWS_TICK_SHOCK_THRESHOLD else "PREFLIGHT"
            # 2026-04-29 rebuild: SL/TP from CONTINUATION_MAGNITUDE lookup
            # (rate decisions 12/50; data prints 8/25; default 6/20).
            # 2026-04-30 split-rename: continuation_magnitude vs fade_caps.
            # NEWS_TICK only consumes continuation_magnitude — fade-side
            # TP geometry (mirror past anchor) lives in NEWS_STRATEGY.
            try:
                _mag = _continuation_magnitude(_event_name_for_dir)
            except Exception:
                _mag = {"sl_pips": NEWS_PREFLIGHT_FALLBACK_SL,
                        "tp_pips": NEWS_PREFLIGHT_FALLBACK_TP}
            sl_pips = float(_mag.get("sl_pips", NEWS_PREFLIGHT_FALLBACK_SL))
            tp_pips = float(_mag.get("tp_pips", NEWS_PREFLIGHT_FALLBACK_TP))
            _tight_tag = ""

            logger.info(
                "[NEWS-TICK]%s %s %s: %s %s @ %.1f  TE=%s dev=%.1f%%  price_move=%.1fp",
                _tight_tag, sym, _tag, signal, "pre-spike" if abs(diff_pips) < 2 else "early-spike",
                mid, te_result["beat_miss"], _dev * 100, diff_pips,
            )
            _gate_reason, _lv_match = _pre_entry_gate(
                sym, st.get("release_epoch", 0), signal, ts, mid, ppp,
            )
            if _gate_reason:
                _handle_pre_entry_block(sym, signal, _gate_reason)
                return None

            try:
                from telegram_alerts import send_telegram_message
                send_telegram_message(
                    f"⚡ <b>NEWS_TICK{_tight_tag} {_tag}:</b> {sym} {signal} @ {mid:.1f}\n"
                    f"TE: {te_result.get('te_event','')} actual={te_result['actual_str']} "
                    f"forecast={te_result['forecast_str']} dev={_dev*100:.1f}%\n"
                    f"SL={sl_pips:.0f}p TP={tp_pips:.0f}p  anchor={st['anchor']:.1f} "
                    f"| Price move: {diff_pips:+.1f}p"
                    f"{_level_line(_lv_match)}"
                )
            except Exception:
                pass

            _mark_event_processed(sym, st.get("release_epoch", 0), signal)
            st["phase"] = _FIRED
            _persist_state()

            if NEWS_OBSERVABLE_ONLY:
                logger.info(
                    "[NEWS-TICK] %s WOULD_FIRE %s @ %.1f  reason=preflight  "
                    "SL=%.1fp TP=%.1fp  (observable-only)",
                    sym, signal, mid, sl_pips, tp_pips,
                )
                return None

            return _build_entry(signal, mid, spike_dir, st["anchor"],
                                st.get("spike_extreme", mid), ppp,
                                "preflight", te_result, briefing_level=_lv_match,
                                sl_override=sl_pips,
                                event_titles=st.get("event_titles", []),
                                symbol=sym)

        # 2026-04-29 rebuild: IN_LINE / REVERSAL → cede to NEWS_STRATEGY.
        # No fall-back-to-ARMED-and-stall. NEWS_STRATEGY's tick-level fade
        # path picks this up via its own ARMED → SPIKE_DETECTED →
        # CONSOLIDATION_TRACKING state machine.
        if te_result and te_result.get("direction_hint") == "REVERSAL":
            _ceded_event_name = (
                te_result.get("te_event")
                or (st.get("event_titles") or [""])[0]
            )
            logger.info(
                "[NEWS-TICK] %s ceding %s to NEWS_STRATEGY  "
                "direction_hint=REVERSAL beat_miss=%s dev=%s",
                sym, _ceded_event_name,
                te_result.get("beat_miss"), te_result.get("deviation"),
            )
            _reset(sym, "ceded_to_news_strategy_inline")
            return None

        # --- Price-action spike detection (parallel to Finnhub polling) ---
        # 2026-04-29 rebuild: gated behind NEWS_TICK_LEGACY_STALL_PATH=0.
        # The pre-rebuild logic fired NEWS_TICK on price-action alone when
        # Finnhub hadn't returned yet — same wrong-direction risk as the
        # pre-rebuild diff_pips direction. Per spec: no actuals → cede.
        if not NEWS_TICK_LEGACY_STALL_PATH:
            # Stay in PREFLIGHT until actuals arrive or the ARMED window
            # expires. Eventual fall-through is handled by the existing
            # _expire_at check at the top of the PREFLIGHT block; if still
            # no actuals at expiry, we cede silently.
            return None
        release_epoch = st.get("release_epoch", 0)
        since_release = ts - release_epoch if ts >= release_epoch else 0
        diff_pips = (mid - st["anchor"]) / ppp

        # Direct fire: spike within 2-min window → entry from price action
        if abs(diff_pips) >= NEWS_TICK_SPIKE_MIN_PIPS and 0 < since_release <= NEWS_TICK_SPIKE_WINDOW_SECS:
            spike_dir = "UP" if diff_pips > 0 else "DOWN"
            signal = "BUY" if spike_dir == "UP" else "SELL"
            spike_pips = abs(diff_pips)
            _tight_tp = _is_tight_tp_event(st.get("event_titles", []))
            _tight_tag = " [TIGHT-TP]" if _tight_tp else ""
            logger.info(
                "[NEWS-TICK]%s %s SPIKE_FALLBACK: %s %s @ %.1f  move=%.1fp  "
                "%.0fs after release (no Finnhub — price action entry)",
                _tight_tag, sym, signal, spike_dir, mid, spike_pips, since_release,
            )
            _gate_reason, _lv_match = _pre_entry_gate(
                sym, st.get("release_epoch", 0), signal, ts, mid, ppp,
            )
            if _gate_reason:
                _handle_pre_entry_block(sym, signal, _gate_reason)
                return None

            try:
                from telegram_alerts import send_telegram_message
                send_telegram_message(
                    f"⚡ <b>NEWS_TICK{_tight_tag} SPIKE:</b> {sym} {signal} @ {mid:.1f}\n"
                    f"📈 {spike_dir} {spike_pips:.0f}p within {since_release:.0f}s of release\n"
                    f"anchor={st['anchor']:.1f}  (no Finnhub — price action entry)"
                    f"{_level_line(_lv_match)}"
                )
            except Exception:
                pass
            _mark_event_processed(sym, st.get("release_epoch", 0), signal)
            st["phase"] = _FIRED
            _persist_state()
            return _build_entry(signal, mid, spike_dir, st["anchor"], mid, ppp,
                                "spike_fallback", st.get("te_result"),
                                briefing_level=_lv_match,
                                event_titles=st.get("event_titles", []),
                                symbol=sym)

        # Spike window expired — fall back based on current price move
        if since_release > NEWS_TICK_SPIKE_WINDOW_SECS:
            if abs(diff_pips) >= NEWS_TICK_SPIKE_MIN_PIPS:
                # Large move but outside window → stall-and-confirm path
                spike_dir = "UP" if diff_pips > 0 else "DOWN"
                st["phase"] = _SPIKE
                st["spike_dir"] = spike_dir
                st["spike_extreme"] = mid
                st["spike_time"] = ts
                st["no_new_extreme_count"] = 0
                st["_preflight_done"] = True
                logger.info(
                    "[NEWS-TICK] %s PREFLIGHT → SPIKE  dir=%s  move=%.1fp "
                    "(spike window expired, stall-and-confirm)",
                    sym, spike_dir, abs(diff_pips),
                )
            else:
                st["phase"] = _ARMED
                st["_preflight_done"] = True
                logger.info(
                    "[NEWS-TICK] %s PREFLIGHT → ARMED: no Finnhub data, spike window "
                    "expired (%.0fs), move=%.1fp < %.1fp threshold",
                    sym, since_release, abs(diff_pips), NEWS_TICK_SPIKE_MIN_PIPS,
                )

        return None

    # ------------------------------------------------------------------
    # SPIKE_DETECTED → Finnhub fast path (10s window) then stall detection
    # ------------------------------------------------------------------
    # 2026-04-29 rebuild: this entire block + the STALL block below are
    # the legacy stall-and-confirm chase path. Default off; reachable
    # only when NEWS_TICK_LEGACY_STALL_PATH=1 and the price-based
    # ARMED→SPIKE transition above is also gated on that flag, so SPIKE
    # state is unreachable under default config. Kept for rollback.
    if st["phase"] == _SPIKE and not NEWS_TICK_LEGACY_STALL_PATH:
        # Defensive: if state somehow landed in SPIKE under default
        # config (e.g. persisted state from a previous legacy-path run),
        # cede to NEWS_STRATEGY rather than firing a chase trade.
        _reset(sym, "spike_state_under_default_config")
        return None
    if st["phase"] == _SPIKE:
        if (ts - st["spike_time"]) > NEWS_TICK_TIMEOUT_SECS:
            _reset(sym, "spike_timeout")
            return None

        spike_dir = st["spike_dir"]
        extreme = st["spike_extreme"]
        since_spike = ts - st["spike_time"]

        # --- Always track extreme ---
        if spike_dir == "UP" and mid > extreme:
            st["spike_extreme"] = mid
            st["no_new_extreme_count"] = 0
        elif spike_dir == "DOWN" and mid < extreme:
            st["spike_extreme"] = mid
            st["no_new_extreme_count"] = 0
        else:
            st["no_new_extreme_count"] = st.get("no_new_extreme_count", 0) + 1

        extreme = st["spike_extreme"]

        # --- Finnhub fast path: poll for actual ---
        te_result = st.get("te_result")
        release_epoch = st.get("release_epoch", 0)
        past_release = ts >= release_epoch
        since_release = ts - release_epoch if past_release else 0

        if te_result is None and past_release and since_release <= NEWS_TICK_ACTUAL_TIMEOUT_SECS:
            te_calendar.poll_for_actual(min_interval=NEWS_TICK_ACTUAL_POLL_SECS)
            _event_ccy = st.get("event_currency", "")
            for title in st.get("event_titles", []):
                te_data = te_calendar.get_actual_for_event(title, currency=_event_ccy)
                if te_data and te_data.get("direction_hint"):
                    st["te_result"] = te_data
                    te_result = te_data
                    logger.info(
                        "[NEWS-TICK] %s ACTUAL FOUND (%.0fs after release): "
                        "%s=%s (forecast=%s) deviation=%.1f%% → %s (%s)",
                        sym, since_release,
                        te_data["te_event"], te_data["actual_str"],
                        te_data["forecast_str"],
                        (te_data.get("deviation") or 0) * 100,
                        te_data["direction_hint"], te_data["beat_miss"],
                    )
                    break

        if te_result is None and past_release and since_release > NEWS_TICK_ACTUAL_TIMEOUT_SECS:
            if not st.get("_actual_timeout_logged"):
                logger.info("[NEWS-TICK] %s no actual after %.0fs — stall-and-confirm only", sym, since_release)
                st["_actual_timeout_logged"] = True

        # --- FAST PATH: Finnhub says CONTINUATION → enter now ---
        if te_result and te_result.get("direction_hint") == "CONTINUATION":
            _dev = abs(te_result.get("deviation") or 0)
            _is_shock = _dev >= NEWS_TICK_SHOCK_THRESHOLD
            _tag = "TE_SHOCK" if _is_shock else "TE_CONTINUATION"
            signal = "BUY" if spike_dir == "UP" else "SELL"
            spike_pips = abs(mid - st["anchor"]) / ppp
            logger.info(
                "[NEWS-TICK] %s FAST PATH: %s %s @ %.1f  TE=%s dev=%.1f%%  spike=%s %.1fp",
                sym, _tag, signal, mid,
                te_result["beat_miss"], _dev * 100,
                spike_dir, spike_pips,
            )
            _gate_reason, _lv_match = _pre_entry_gate(
                sym, st.get("release_epoch", 0), signal, ts, mid, ppp,
            )
            if _gate_reason:
                _handle_pre_entry_block(sym, signal, _gate_reason)
                return None

            _send_telegram(sym, signal, mid, "te_continuation", spike_dir, spike_pips,
                           te_result, match=_lv_match,
                           event_titles=st.get("event_titles", []),
                           anchor=st.get("anchor"), ppp=ppp)
            _mark_event_processed(sym, st.get("release_epoch", 0), signal)
            st["phase"] = _FIRED
            _persist_state()
            return _build_entry(signal, mid, spike_dir, st["anchor"], extreme, ppp,
                                "te_continuation", te_result,
                                briefing_level=_lv_match,
                                event_titles=st.get("event_titles", []),
                                symbol=sym)

        # --- SLOW PATH: stall detection — only after Finnhub window expires ---
        # Shock-sized spikes (>= spike threshold * 2) use shorter window
        _spike_pips_now = abs(mid - st["anchor"]) / ppp
        _is_large_spike = _spike_pips_now >= NEWS_TICK_SPIKE_MIN_PIPS * 2
        _fh_window = NEWS_TICK_SHOCK_WINDOW_SECS if _is_large_spike else NEWS_TICK_FINNHUB_WINDOW_SECS
        if since_spike < _fh_window:
            return None  # wait for Finnhub before allowing stall

        if te_result and te_result.get("direction_hint") == "REVERSAL":
            logger.info(
                "[NEWS-TICK] %s TE IN_LINE (dev=%.1f%%) — using stall-and-confirm for reversal",
                sym, (te_result.get("deviation") or 0) * 100,
            )

        if st["no_new_extreme_count"] >= NEWS_TICK_STALL_TICKS:
            st["phase"] = _STALL
            st["stall_price"] = mid
            st["stall_time"] = ts
            spike_pips = abs(extreme - st["anchor"]) / ppp
            logger.info(
                "[NEWS-TICK] %s SPIKE → STALL  extreme=%.1f  stall=%.1f  spike=%.1fp  "
                "(%.1fs after spike, %d ticks no new extreme)",
                sym, extreme, mid, spike_pips, since_spike, NEWS_TICK_STALL_TICKS,
            )
            _persist_state()
        return None

    # ------------------------------------------------------------------
    # STALL_DETECTED → directional confirmation (5p move from stall)
    # ------------------------------------------------------------------
    # 2026-04-29 rebuild: legacy chase path. Default off — STALL is
    # unreachable when NEWS_TICK_LEGACY_STALL_PATH=0.
    if st["phase"] == _STALL and not NEWS_TICK_LEGACY_STALL_PATH:
        _reset(sym, "stall_state_under_default_config")
        return None
    if st["phase"] == _STALL:
        if (ts - st["spike_time"]) > NEWS_TICK_TIMEOUT_SECS:
            _reset(sym, "stall_timeout")
            return None

        # 30-minute max: reject if confirmation is too late after event
        _armed_ts = st.get("armed_time", st["spike_time"])
        if (ts - _armed_ts) > NEWS_TICK_MAX_CONFIRM_SECS:
            _reset(sym, "confirmation_too_late")
            return None

        stall = st["stall_price"]
        spike_dir = st["spike_dir"]
        move = (mid - stall) / ppp

        signal = None
        reason_tag = None

        if spike_dir == "DOWN":
            if move <= -NEWS_TICK_CONFIRM_PIPS:
                signal = "SELL"; reason_tag = "continuation"
            elif not NEWS_TICK_CONTINUATION_ONLY and move >= NEWS_TICK_CONFIRM_PIPS:
                signal = "BUY"; reason_tag = "reversal"
        else:
            if move >= NEWS_TICK_CONFIRM_PIPS:
                signal = "BUY"; reason_tag = "continuation"
            elif not NEWS_TICK_CONTINUATION_ONLY and move <= -NEWS_TICK_CONFIRM_PIPS:
                signal = "SELL"; reason_tag = "reversal"

        if signal is None:
            return None

        extreme = st["spike_extreme"]
        anchor = st["anchor"]
        spike_pips = abs(extreme - anchor) / ppp
        te_result = st.get("te_result")

        logger.info(
            "[NEWS-TICK] %s STALL → ENTRY  %s %s @ %.1f  spike=%s %.1fp  stall=%.1f  move=%+.1fp",
            sym, reason_tag, signal, mid, spike_dir, spike_pips, stall, move,
        )
        _gate_reason, _lv_match = _pre_entry_gate(
            sym, st.get("release_epoch", 0), signal, ts, mid, ppp,
        )
        if _gate_reason:
            _handle_pre_entry_block(sym, signal, _gate_reason)
            return None

        _send_telegram(sym, signal, mid, reason_tag, spike_dir, spike_pips,
                       te_result, stall, move, match=_lv_match,
                       event_titles=st.get("event_titles", []),
                       anchor=anchor, ppp=ppp)
        _mark_event_processed(sym, st.get("release_epoch", 0), signal)
        st["phase"] = _FIRED
        _persist_state()
        return _build_entry(signal, mid, spike_dir, anchor, extreme, ppp,
                            reason_tag, te_result, stall, move,
                            briefing_level=_lv_match,
                            event_titles=st.get("event_titles", []),
                            symbol=sym)

    # ------------------------------------------------------------------
    # FIRED → reset when blackout ends
    # ------------------------------------------------------------------
    if st["phase"] == _FIRED:
        if not is_blackout:
            _reset(sym, "post_entry_blackout_ended")
        return None

    return None
