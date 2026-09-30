"""fifty_pip_breakout — 8:00 UTC anchor-candle 50-pip breakout strategy.

Pilot configuration (live-demo, single config — Prompt-1 USDCAD V4 cell):

    FIFTY_PIP_BREAKOUT_USDCAD_V4
        pair = USDCAD
        anchor_hour_utc = 7      (07:00–08:00 UTC 1H anchor bar)
        entry_buffer_pips = 2
        sl_distance_pips = 10    (V4 = 10p beyond opposite side of anchor)
        tp_distance_pips = 50
        eod_hour_utc = 22
        eod_policy = 'be_hold'   (V4: at 22:00 UTC move SL→entry, ride overnight)

Reference: data/analysis/fifty_pip/extended/matrix_extended.json (28-month
backtest 2024-01 → 2026-04-10). USDCAD V4: +1409p gross, +11.8 p/wk, TP
1.12/wk, all three years positive, worst 30-day −346p. See
reports/50pip_strategy_beginner_evaluation_20260510.md §3 for the full
deployability case.

State machine (per mode, per pair):

    IDLE     — waiting for next anchor close (08:00 UTC).
    ARMED    — anchor read, virtual orders placed; watching ticks for trigger.
                ask >= buy_stop  → FIRED long
                bid <= sell_stop → FIRED short
                22:00 UTC reached without trigger → DAY_DONE
    FIRED    — position open, monitored by trade_manager (SL/TP). Strategy
                tracks the 22:00 UTC BE-amend transition and exposes
                apply_eod_be_hold() for the autobot tick loop to call.
    DAY_DONE — terminal for the trading day; resets to ARMED at next 08:00 UTC.

Tick-driven (parallels news_tick_strategy.tick_update). Anchor-bar high/low
is read from the 5m DataFrame supplied by the caller (12 closed 5m bars in
[anchor_hour:00, anchor_hour+1:00) UTC; high = max(high), low = min(low)).
That matches the analysis simulator's mid-OHLC 1H aggregation to within the
spread/2 — sufficient for the 0.1p detector validation tolerance.

Gating posture: this module performs no additional gates. Universal
blackouts (news, briefing invalidation, concurrent-position cap, pair caps)
are honoured downstream by the autobot tick block / trade_executor. The
28-month backtest assumed unrestricted firing.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("fifty_pip_breakout")


# ---------------------------------------------------------------------------
# Env helpers + module-wide gate
# ---------------------------------------------------------------------------
def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes")


FIFTY_PIP_BREAKOUT_ENABLED = _env_bool("FIFTY_PIP_BREAKOUT_ENABLED", "1")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FiftyPipConfig:
    mode_name: str
    pair: str
    anchor_hour_utc: int        # 7 = 07:00-08:00 UTC anchor
    entry_buffer_pips: float    # 2.0
    sl_distance_pips: float     # 10.0 (V4) — beyond opposite side of anchor
    tp_distance_pips: float     # 50.0
    eod_hour_utc: int           # 22 = 22:00 UTC BE-amend cut-off
    eod_policy: str             # "be_hold" (V4) | "close" (V1/V2/V3 variants)


DEFAULT_CONFIGS: Tuple[FiftyPipConfig, ...] = (
    FiftyPipConfig(
        mode_name="FIFTY_PIP_BREAKOUT_USDCAD_V4",
        pair="USDCAD",
        anchor_hour_utc=7,
        entry_buffer_pips=2.0,
        sl_distance_pips=10.0,
        tp_distance_pips=50.0,
        eod_hour_utc=22,
        eod_policy="be_hold",
    ),
)


def _active_configs() -> Tuple[FiftyPipConfig, ...]:
    keep = []
    for c in DEFAULT_CONFIGS:
        if _env_bool(f"{c.mode_name}_ENABLED", "1"):
            keep.append(c)
    return tuple(keep)


def _allowed_pairs() -> Tuple[str, ...]:
    return tuple(sorted({c.pair for c in _active_configs()}))


ALLOWED_PAIRS = frozenset(_allowed_pairs())

# 12 closed 5m bars in the anchor hour + a few of warmup. Min bars before
# anchor reading is meaningful: 14 (covers the whole anchor hour + 1 prior
# bar so the boundary is well-defined under jitter).
MIN_BARS_FOR_ANCHOR = 14


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
_IDLE = "IDLE"
_ARMED = "ARMED"
_FIRED = "FIRED"
_DAY_DONE = "DAY_DONE"


# ---------------------------------------------------------------------------
# Per-mode state (singletons keyed by mode_name)
# ---------------------------------------------------------------------------
@dataclass
class _ModeState:
    phase: str = _IDLE
    # Anchor (set in ARMED)
    anchor_date_utc: Optional[str] = None     # "YYYY-MM-DD" — UTC date of the anchor bar
    anchor_high: float = float("nan")
    anchor_low: float = float("nan")
    buy_stop: float = float("nan")
    sell_stop: float = float("nan")
    # Fire (set in FIRED)
    fire_date_utc: Optional[str] = None
    fire_ts_epoch: Optional[float] = None
    fire_side: Optional[str] = None           # "BUY" | "SELL"
    fire_entry: float = float("nan")
    fire_sl: float = float("nan")             # absolute SL price (not pip distance)
    fire_tp: float = float("nan")
    # EOD transitions (set when applied)
    be_amend_applied: bool = False
    last_anchor_read_attempt_date: Optional[str] = None  # rate-limit anchor read retries
    last_log_phase: Optional[str] = None      # so phase-change logs fire once


_state: Dict[str, _ModeState] = {}
_state_lock = threading.Lock()


def _get_state(mode_name: str) -> _ModeState:
    s = _state.get(mode_name)
    if s is None:
        s = _ModeState()
        _state[mode_name] = s
    return s


# ---------------------------------------------------------------------------
# Anchor extraction
# ---------------------------------------------------------------------------
def _read_anchor_from_df(df: pd.DataFrame, anchor_date_utc: str, anchor_hour: int
                         ) -> Optional[Tuple[float, float]]:
    """Aggregate closed 5m bars in [anchor_hour:00, anchor_hour+1:00) UTC on
    ``anchor_date_utc`` (a YYYY-MM-DD string).

    Returns (anchor_high, anchor_low) or None if the window has zero bars
    (e.g. weekend, holiday, or feed gap). Tolerant of either a 'time'
    column or a DatetimeIndex.
    """
    if df is None or len(df) == 0:
        return None
    try:
        if "time" in df.columns:
            times = pd.to_datetime(df["time"], utc=True, errors="coerce")
        else:
            times = pd.to_datetime(df.index, utc=True, errors="coerce")
    except Exception:
        return None

    try:
        target_start = pd.Timestamp(f"{anchor_date_utc} {anchor_hour:02d}:00:00",
                                    tz="UTC")
    except Exception:
        return None
    target_end = target_start + pd.Timedelta(hours=1)

    mask = (times >= target_start) & (times < target_end)
    if not mask.any():
        return None

    try:
        highs = df.loc[mask, "high"].astype(float)
        lows = df.loc[mask, "low"].astype(float)
    except Exception:
        return None
    if highs.empty or lows.empty:
        return None
    return float(highs.max()), float(lows.min())


# ---------------------------------------------------------------------------
# UTC helpers
# ---------------------------------------------------------------------------
def _utc_dt(ts_epoch: float) -> datetime:
    return datetime.fromtimestamp(float(ts_epoch), tz=timezone.utc)


def _utc_date_str(ts_epoch: float) -> str:
    return _utc_dt(ts_epoch).strftime("%Y-%m-%d")


def _utc_time_at(ts_epoch: float, hour: int, minute: int = 0) -> datetime:
    d = _utc_dt(ts_epoch)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Translation log (first-5-fires-per-mode, mirrors PR #16 / bb_pattern2 pattern)
# ---------------------------------------------------------------------------
_TRANSLATION_LOG_PATH = "logs/fifty_pip_breakout_translation.jsonl"
_TRANSLATION_MAX_PER_MODE = 5
_translation_counts: Dict[str, int] = {}
_translation_lock = threading.Lock()


def _maybe_log_translation(cfg: FiftyPipConfig, st: _ModeState, mid: float,
                           bid: float, ask: float, ts_epoch: float, epic: str
                           ) -> None:
    with _translation_lock:
        c = _translation_counts.get(cfg.mode_name, 0)
        if c >= _TRANSLATION_MAX_PER_MODE:
            return
        _translation_counts[cfg.mode_name] = c + 1
    try:
        os.makedirs(os.path.dirname(_TRANSLATION_LOG_PATH), exist_ok=True)
    except Exception:
        pass
    payload = {
        "logged_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": cfg.mode_name,
        "pair": cfg.pair,
        "epic": epic,
        "anchor_date_utc": st.anchor_date_utc,
        "anchor_high": st.anchor_high,
        "anchor_low": st.anchor_low,
        "anchor_range": st.anchor_high - st.anchor_low,
        "buy_stop": st.buy_stop,
        "sell_stop": st.sell_stop,
        "fire_side": st.fire_side,
        "fire_entry": st.fire_entry,
        "fire_sl": st.fire_sl,
        "fire_tp": st.fire_tp,
        "fire_ts_utc": (datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat()
                        if ts_epoch else None),
        "tick_bid": bid,
        "tick_ask": ask,
        "tick_mid": mid,
        "config": {
            "anchor_hour_utc": cfg.anchor_hour_utc,
            "entry_buffer_pips": cfg.entry_buffer_pips,
            "sl_distance_pips": cfg.sl_distance_pips,
            "tp_distance_pips": cfg.tp_distance_pips,
            "eod_hour_utc": cfg.eod_hour_utc,
            "eod_policy": cfg.eod_policy,
        },
    }
    try:
        with open(_TRANSLATION_LOG_PATH, "a") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception as e:
        logger.warning("[%s] translation log write failed: %s", cfg.mode_name, e)


# ---------------------------------------------------------------------------
# Phase logging
# ---------------------------------------------------------------------------
def _log_phase_change(cfg: FiftyPipConfig, st: _ModeState, new_phase: str,
                      extra: str = "") -> None:
    if st.last_log_phase == new_phase:
        return
    st.last_log_phase = new_phase
    logger.info("[%s] phase %s → %s %s",
                cfg.mode_name, st.phase, new_phase, extra)


# ---------------------------------------------------------------------------
# Core: tick_update
# ---------------------------------------------------------------------------
def tick_update(*, symbol: str, epic: str, mid: float, bid: float, ask: float,
                ts: float, ppp: float, df_5m: Optional[pd.DataFrame],
                has_open_for_mode_fn=None) -> Optional[Dict[str, Any]]:
    """Per-tick state advance for all active configs that match ``symbol``.

    Returns a fire dict (signal/entry/sl/tp/reason/debug/mode) when this
    tick triggers an entry, else None.

    ``has_open_for_mode_fn(epic, mode_name) -> bool`` lets the caller report
    whether a position is currently open for the FIFTY_PIP mode (used to
    keep ARMED suppressed while a prior-day position is still riding).
    """
    if not FIFTY_PIP_BREAKOUT_ENABLED:
        return None
    sym = str(symbol or "").upper()
    if sym not in ALLOWED_PAIRS:
        return None

    matches = [c for c in _active_configs() if c.pair == sym]
    if not matches:
        return None

    with _state_lock:
        for cfg in matches:
            fire = _advance_one(cfg, epic, mid, bid, ask, ts, ppp, df_5m,
                                has_open_for_mode_fn)
            if fire is not None:
                return fire
    return None


def _advance_one(cfg: FiftyPipConfig, epic: str, mid: float, bid: float,
                 ask: float, ts: float, ppp: float,
                 df_5m: Optional[pd.DataFrame],
                 has_open_for_mode_fn) -> Optional[Dict[str, Any]]:
    st = _get_state(cfg.mode_name)
    if bid is None or ask is None:
        return None
    try:
        bid_f = float(bid); ask_f = float(ask)
    except (TypeError, ValueError):
        return None
    try:
        ts_f = float(ts)
    except (TypeError, ValueError):
        return None

    now = _utc_dt(ts_f)
    today_str = now.strftime("%Y-%m-%d")
    anchor_close = _utc_time_at(ts_f, cfg.anchor_hour_utc + 1, 0)
    eod = _utc_time_at(ts_f, cfg.eod_hour_utc, 0)

    # ----- DAY_DONE → reset at next 08:00 UTC -----
    if st.phase == _DAY_DONE:
        if now >= anchor_close and st.anchor_date_utc != today_str:
            # New trading day has begun; allow re-entry to IDLE → ARMED below.
            st.phase = _IDLE
            st.last_log_phase = None
        else:
            return None

    # ----- FIRED → manage 22:00 UTC BE-amend transition -----
    if st.phase == _FIRED:
        # Position lifecycle is tracked externally (trade_manager). If the
        # caller signals the position has been closed, return to DAY_DONE.
        if has_open_for_mode_fn is not None:
            try:
                still_open = bool(has_open_for_mode_fn(epic, cfg.mode_name))
            except Exception:
                still_open = True
            if not still_open:
                _log_phase_change(cfg, st, _DAY_DONE,
                                  "position closed by trade_manager")
                st.phase = _DAY_DONE
                return None
        # Otherwise stay in FIRED. The BE amend itself is applied via
        # apply_eod_be_hold(), called separately by the autobot tick loop.
        return None

    # ----- IDLE → ARMED at 08:00 UTC -----
    if st.phase == _IDLE:
        # Only arm once the anchor bar has closed (now >= 08:00 UTC of
        # today). Before that, do nothing.
        if now < anchor_close:
            return None
        # And only arm if we haven't already done DAY_DONE for this date.
        if st.anchor_date_utc == today_str:
            return None
        # Suppress arming if a prior-day position is still open for this
        # mode (concurrent positions in same mode are blocked downstream
        # anyway, but skipping ARM avoids stale anchor reads).
        if has_open_for_mode_fn is not None:
            try:
                if has_open_for_mode_fn(epic, cfg.mode_name):
                    return None
            except Exception:
                pass
        # Rate-limit anchor read retries to once per minute per (mode, date)
        # — feed-gap recovery rebuilds 5m bars over a few seconds.
        if st.last_anchor_read_attempt_date != today_str:
            st.last_anchor_read_attempt_date = today_str
        anchor = _read_anchor_from_df(df_5m, today_str, cfg.anchor_hour_utc)
        if anchor is None:
            return None
        st.anchor_high, st.anchor_low = anchor
        st.anchor_date_utc = today_str
        st.buy_stop = st.anchor_high + cfg.entry_buffer_pips * ppp
        st.sell_stop = st.anchor_low - cfg.entry_buffer_pips * ppp
        _log_phase_change(
            cfg, st, _ARMED,
            f"anchor={today_str} {cfg.anchor_hour_utc:02d}:00 high={st.anchor_high:.2f} "
            f"low={st.anchor_low:.2f} buy_stop={st.buy_stop:.2f} sell_stop={st.sell_stop:.2f}",
        )
        st.phase = _ARMED
        # fall through to ARMED handling so we can fire on this same tick

    # ----- ARMED → FIRED / DAY_DONE -----
    if st.phase == _ARMED:
        if now >= eod:
            # 22:00 UTC reached without entry.
            _log_phase_change(cfg, st, _DAY_DONE, "no_entry_by_eod")
            st.phase = _DAY_DONE
            return None

        # Long trigger: ask >= buy_stop. Short trigger: bid <= sell_stop.
        # If both ticks are triggered on the same tick, prefer long (the
        # analysis simulator picked the side whose first-trigger index was
        # earliest — at single-tick resolution we deterministically pick
        # long; the analysis only had this happen on truly simultaneous
        # ticks).
        long_trig = ask_f >= st.buy_stop
        short_trig = bid_f <= st.sell_stop
        if not (long_trig or short_trig):
            return None

        side = "BUY" if long_trig else "SELL"
        entry_price = st.buy_stop if side == "BUY" else st.sell_stop
        if side == "BUY":
            # V4: SL = anchor_low − sl_distance_pips, TP = entry + 50p.
            sl_abs = st.anchor_low - cfg.sl_distance_pips * ppp
            tp_abs = entry_price + cfg.tp_distance_pips * ppp
        else:
            sl_abs = st.anchor_high + cfg.sl_distance_pips * ppp
            tp_abs = entry_price - cfg.tp_distance_pips * ppp
        sl_pips = abs(entry_price - sl_abs) / ppp
        tp_pips = abs(tp_abs - entry_price) / ppp

        st.fire_date_utc = today_str
        st.fire_ts_epoch = ts_f
        st.fire_side = side
        st.fire_entry = entry_price
        st.fire_sl = sl_abs
        st.fire_tp = tp_abs
        st.phase = _FIRED
        st.be_amend_applied = False
        _log_phase_change(
            cfg, st, _FIRED,
            f"side={side} entry={entry_price:.2f} sl={sl_abs:.2f} tp={tp_abs:.2f} "
            f"sl_pips={sl_pips:.1f} tp_pips={tp_pips:.1f}",
        )

        try:
            _maybe_log_translation(cfg, st, mid, bid_f, ask_f, ts_f, epic)
        except Exception as e:
            logger.warning("[%s] translation log raise: %s", cfg.mode_name, e)

        return {
            "mode": cfg.mode_name,
            "signal": side,
            "entry": entry_price,
            "sl": sl_pips,
            "tp": tp_pips,
            "reason": f"fifty_pip_{cfg.eod_policy}_{side.lower()}",
            "debug": {
                "entry_source": "fifty_pip_breakout",
                "config_mode": cfg.mode_name,
                "pair": cfg.pair,
                "variant": _variant_name(cfg),
                "anchor_date_utc": st.anchor_date_utc,
                "anchor_hour_utc": cfg.anchor_hour_utc,
                "anchor_high": float(st.anchor_high),
                "anchor_low": float(st.anchor_low),
                "anchor_range": float(st.anchor_high - st.anchor_low),
                "buy_stop": float(st.buy_stop),
                "sell_stop": float(st.sell_stop),
                "entry_buffer_pips": cfg.entry_buffer_pips,
                "sl_abs_price": float(sl_abs),
                "tp_abs_price": float(tp_abs),
                "sl_distance_pips": cfg.sl_distance_pips,
                "tp_distance_pips": cfg.tp_distance_pips,
                "eod_hour_utc": cfg.eod_hour_utc,
                "eod_policy": cfg.eod_policy,
                "fire_tick_bid": bid_f,
                "fire_tick_ask": ask_f,
                "fire_tick_mid": mid,
                "fire_ts_utc": datetime.fromtimestamp(ts_f, tz=timezone.utc).isoformat(),
                "search_provenance": (
                    "reports/50pip_strategy_beginner_evaluation_20260510.md "
                    "USDCAD V4 — the only deployable cell across 28-month 4×5 matrix"
                ),
            },
        }

    return None


def _variant_name(cfg: FiftyPipConfig) -> str:
    if (cfg.eod_policy == "be_hold" and abs(cfg.sl_distance_pips - 10.0) < 1e-9):
        return "V4"
    if (cfg.eod_policy == "close" and abs(cfg.sl_distance_pips - 10.0) < 1e-9):
        return "V2"
    if (cfg.eod_policy == "close" and abs(cfg.sl_distance_pips - 5.0) < 1e-9):
        return "V1"
    if (cfg.eod_policy == "close" and abs(cfg.sl_distance_pips - 12.0) < 1e-9):
        return "V5"
    return "custom"


# ---------------------------------------------------------------------------
# 22:00 UTC BE-amend hook — called every tick by the autobot loop.
# ---------------------------------------------------------------------------
def apply_eod_be_hold(*, epic: str, ts: float,
                      get_open_position_for_mode_fn=None,
                      amend_stop_fn=None) -> None:
    """Walk active configs; for each FIRED position past 22:00 UTC with the
    'be_hold' policy and no BE amend yet, ask the caller to move the SL to
    the strategy-recorded entry price.

    Indirection via callables keeps the strategy module free of trade_executor /
    IG-session imports and allows unit testing the state machine in isolation.

    Callable contracts (set by autobot.py wiring):
      get_open_position_for_mode_fn(epic, mode) -> Optional[dict]
          Must return None if no active position; else a dict with at least
          'deal_id', 'entry_price', 'direction'.
      amend_stop_fn(deal_id, new_stop_price, limit_price) -> bool
          Apply broker-side SL amend. Return truthy on success.
    """
    if not FIFTY_PIP_BREAKOUT_ENABLED:
        return
    try:
        ts_f = float(ts)
    except (TypeError, ValueError):
        return
    now = _utc_dt(ts_f)

    with _state_lock:
        for cfg in _active_configs():
            if cfg.eod_policy != "be_hold":
                continue
            st = _state.get(cfg.mode_name)
            if st is None or st.phase != _FIRED:
                continue
            if st.be_amend_applied:
                continue
            if st.fire_ts_epoch is None:
                continue
            # Trigger when the wall clock has crossed today's 22:00 UTC of
            # the FIRE date.
            try:
                fire_dt = _utc_dt(st.fire_ts_epoch)
            except Exception:
                continue
            eod_of_fire_day = fire_dt.replace(hour=cfg.eod_hour_utc,
                                              minute=0, second=0, microsecond=0)
            # If the position was opened after 22:00 (rare; only if anchor
            # hour pushed late), still trigger when 'now' crosses the next
            # midnight after fire — fall back to 22:00 of the fire-day.
            if now < eod_of_fire_day:
                continue

            if get_open_position_for_mode_fn is None or amend_stop_fn is None:
                logger.debug("[%s] EOD BE-hold: no amend callables wired; skipping",
                             cfg.mode_name)
                return
            try:
                pos = get_open_position_for_mode_fn(epic, cfg.mode_name)
            except Exception as e:
                logger.warning("[%s] EOD BE-hold: get_open_position raised: %s",
                               cfg.mode_name, e)
                continue
            if not pos:
                # Position closed before BE-amend could run (TP/SL hit
                # naturally). Move to DAY_DONE.
                _log_phase_change(cfg, st, _DAY_DONE,
                                  "position closed before BE-amend")
                st.phase = _DAY_DONE
                continue
            deal_id = pos.get("deal_id") or pos.get("dealId")
            entry_price = pos.get("entry_price")
            limit_price = pos.get("limit_price")  # optional, preserve TP
            if not deal_id or entry_price is None:
                logger.debug("[%s] EOD BE-hold: missing deal_id or entry_price (%r)",
                             cfg.mode_name, pos)
                continue
            try:
                ok = bool(amend_stop_fn(deal_id, float(entry_price), limit_price))
            except Exception as e:
                logger.warning("[%s] EOD BE-hold amend raised: %s",
                               cfg.mode_name, e)
                ok = False
            if ok:
                st.be_amend_applied = True
                logger.info(
                    "[%s] EOD BE-hold applied at %s: SL → entry %.2f (deal=%s)",
                    cfg.mode_name, now.isoformat(), float(entry_price), deal_id,
                )
            else:
                logger.warning(
                    "[%s] EOD BE-hold amend FAILED at %s (deal=%s); will retry next tick",
                    cfg.mode_name, now.isoformat(), deal_id,
                )


# ---------------------------------------------------------------------------
# Diagnostic / startup banner
# ---------------------------------------------------------------------------
def configs_summary() -> list:
    return [
        {
            "mode_name": c.mode_name,
            "pair": c.pair,
            "variant": _variant_name(c),
            "anchor_hour_utc": c.anchor_hour_utc,
            "entry_buffer_pips": c.entry_buffer_pips,
            "sl_distance_pips": c.sl_distance_pips,
            "tp_distance_pips": c.tp_distance_pips,
            "eod_hour_utc": c.eod_hour_utc,
            "eod_policy": c.eod_policy,
            "enabled": _env_bool(f"{c.mode_name}_ENABLED", "1"),
        }
        for c in DEFAULT_CONFIGS
    ]


def reset_state_for_test() -> None:
    """Wipe in-memory state. Test-only — do not call from production code."""
    with _state_lock:
        _state.clear()
        _translation_counts.clear()


__all__ = [
    "FiftyPipConfig",
    "DEFAULT_CONFIGS",
    "ALLOWED_PAIRS",
    "FIFTY_PIP_BREAKOUT_ENABLED",
    "MIN_BARS_FOR_ANCHOR",
    "tick_update",
    "apply_eod_be_hold",
    "configs_summary",
    "reset_state_for_test",
]
