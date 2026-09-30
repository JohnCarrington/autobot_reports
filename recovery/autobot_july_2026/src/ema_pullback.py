"""
EmaPullbackStrategy — EMA-stack pullback continuation in established trends.

Setup (arm conditions, all required):
  - 4-EMA fanned: 8>13>21>50 (LONG) or 8<13<21<50 (SHORT) with each
    adjacent pair separated by ≥ MIN_FAN_PIPS (per-pair via env)
  - Price touched BB upper (SHORT) or lower (LONG) within last
    BB_LOOKBACK_BARS bars
  - Current bar wicks into the inclusive band between EMA-8 and EMA-13

Trigger (fire):
  - Within BB_LOOKBACK_BARS bars of arming, a bar closes back past the
    prior bar's high (LONG) or low (SHORT)
  - If no fire within window, arm dies (can re-arm later)

SL: |entry - EMA_21| / pip_size + SL_BUFFER_PIPS, floored at pair
MIN_SL_PIPS. Per-bar in-trade EMA-21-cross invalidation is a follow-up
workstream — see docs/followups.md.

TP: returned as DEFAULT_TP_PIPS placeholder; the strategy_logic dispatch
wrapper's select_tp_levels overrides with briefing-level resolution.

Window: London (07-12 BST) or NY (12-17 BST) only.
Dedup: one fire per {symbol}_{date}_{session}.

Pre-fire news blackout (added 2026-05-03):
  After fire detection, before returning the decision, check
  news_calendar for high-impact events on the pair's base/quote
  currencies in the next NEWS_PRE_MIN minutes. If blocked, the armed
  setup is consumed (don't retry across the blackout). Default
  NEWS_PRE_MIN=30. Toggle via EMA_PULLBACK_NEWS_BLACKOUT_ENABLED
  (default true) and EMA_PULLBACK_NEWS_BLACKOUT_PRE_MINUTES (default 30).

Regime gate (added 2026-05-03 — GBPUSD only, INVERSE of BB_PIERCE_RUN):
  After fire detection, before returning, classify the GBPUSD 5m
  regime via gbpusd_regime_detector.classify_regime(log=False). Suppress
  the fire when regime == "RANGE" (don't pull back in a range; that's
  BB_PIERCE_RUN territory). Allow on TRENDING (ideal) and NEUTRAL
  (benefit of doubt). Setup is consumed on block. Toggle via
  EMA_PULLBACK_REGIME_FILTER_ENABLED (default true).
  Non-GBPUSD pairs skip this gate entirely.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from strategy_logic import StrategyDecision

from pair_config import MIN_SL_PIPS as _PAIR_MIN_SL_PIPS

logger = logging.getLogger("AutoBot")

# ---------------------------------------------------------------------------
# ENV-configurable parameters
# ---------------------------------------------------------------------------
EMA_PULLBACK_ENABLED = str(os.getenv("EMA_PULLBACK_ENABLED", "0")).strip() in ("1", "true", "yes")
EMA_PULLBACK_MODE = "EMA_PULLBACK"

SL_BUFFER_PIPS = float(os.getenv("EMA_PULLBACK_SL_BUFFER", "3"))
DEFAULT_TP_PIPS = float(os.getenv("EMA_PULLBACK_DEFAULT_TP", "40"))


def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes")


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# Pre-fire news blackout — block fresh fires in the N-minute window
# BEFORE any high-impact event on the pair's base/quote currencies.
# Mirrors the gbpusd_bb_bounce pattern. Setup consumed on block.
NEWS_BLACKOUT_ENABLED = _env_bool("EMA_PULLBACK_NEWS_BLACKOUT_ENABLED", "true")
NEWS_PRE_MIN = _env_int("EMA_PULLBACK_NEWS_BLACKOUT_PRE_MINUTES", 30)

# Regime gate — INVERSE of BB_PIERCE_RUN. GBPUSD only. Block on RANGE.
REGIME_FILTER_ENABLED = _env_bool("EMA_PULLBACK_REGIME_FILTER_ENABLED", "true")

# Redesign parameters (used by new arm/fire logic in commit b).
# Per-pair MIN_FAN_PIPS defaults — EUR/GBP pairs are more volatile so a
# 3-pip stack separation is meaningful; USDJPY/USDCAD are tighter and
# would never arm at 3, so they default to 2.
_PAIR_DEFAULT_MIN_FAN = {
    "GBPUSD": 3.0,
    "EURUSD": 3.0,
    "USDJPY": 2.0,
    "USDCAD": 2.0,
}
BB_LOOKBACK_BARS = int(os.getenv("EMA_PULLBACK_BB_LOOKBACK_BARS", "10"))

# ─── EMA_PULLBACK velocity gate (router path, 2026-06-26, LIVE ENFORCE) ─
# Same env keys as gbpusd_ema_pullback.py — single source of truth for the
# threshold; both paths read the same EMA_PB_VELO_* vars. Scope: GBPUSD
# only (mirrors the existing GBPUSD-only regime-gate scope on this router).
# Mirrors the BB_BOUNCE velocity guard sign convention:
#   velo_10 = (close[-1] - close[-11]) / 10
#   faded_sign = -1 for BUY/L, +1 for SELL/S
#   velo_in_faded = velo_10 * faded_sign  → +ve = rushing into stack
# Require velo_in_faded <= EMA_PB_VELO_MAX (default −0.5).
EMA_PB_VELOCITY_GATE_ENABLED = _env_bool("EMA_PB_VELOCITY_GATE_ENABLED", "1")
EMA_PB_VELO_MAX = float(os.getenv("EMA_PB_VELO_MAX", "-0.5"))
EMA_PB_VELO_BARS = _env_int("EMA_PB_VELO_BARS", 10)
EMA_PB_VELO_LOG_PATH = os.getenv(
    "EMA_PB_VELO_LOG_PATH",
    "/opt/tradingbot/logs/ema_pb_velocity_gate.jsonl",
)
import threading as _threading_mod  # local alias — module didn't import threading
_ema_pb_velo_log_lock = _threading_mod.Lock()


def _ema_pb_velo_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the EMA_PULLBACK velocity gate audit log.
    Never raises — log-write failures must not affect the gate verdict."""
    import json as _json
    try:
        d = os.path.dirname(EMA_PB_VELO_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _ema_pb_velo_log_lock:
            with open(EMA_PB_VELO_LOG_PATH, "a") as fh:
                fh.write(_json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def _min_fan_for_pair(pair: str) -> float:
    """Return the EMA-stack minimum-adjacent-separation in IG points for
    pair. Resolution order:

      1. EMA_PULLBACK_MIN_FAN_PIPS_<PAIR> env override
      2. _PAIR_DEFAULT_MIN_FAN[pair] hardcoded default
      3. EMA_PULLBACK_MIN_FAN_PIPS env (default 3) for unmapped pairs
    """
    p = str(pair or "").upper()
    override = os.getenv(f"EMA_PULLBACK_MIN_FAN_PIPS_{p}")
    if override is not None and override.strip():
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    if p in _PAIR_DEFAULT_MIN_FAN:
        return _PAIR_DEFAULT_MIN_FAN[p]
    try:
        return float(os.getenv("EMA_PULLBACK_MIN_FAN_PIPS", "3"))
    except (TypeError, ValueError):
        return 3.0


def _pair_from_epic(epic: str) -> str:
    parts = epic.split(".")
    return parts[2] if len(parts) >= 3 else epic.upper()


def _is_bst(ts) -> bool:
    month = ts.month if hasattr(ts, "month") else 1
    day = ts.day if hasattr(ts, "day") else 1
    return month >= 4 or (month == 3 and day >= 29)


def _to_bst_hour(ts) -> int:
    utc_h = ts.hour if hasattr(ts, "hour") else 0
    return utc_h + (1 if _is_bst(ts) else 0)


def _ts_to_utc_dt(ts) -> Optional[datetime]:
    """Coerce a pandas/Python timestamp to a tz-aware UTC datetime.
    Returns None if conversion fails."""
    try:
        if hasattr(ts, "to_pydatetime"):
            dt = ts.to_pydatetime()
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = pd.to_datetime(ts).to_pydatetime()
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _affecting_currencies_for_pair(pair: str) -> Tuple[str, str]:
    """Return (base, quote) currency codes for a 6-letter pair string.
    Falls back to ("", "") on malformed input."""
    p = str(pair or "").upper()
    if len(p) >= 6:
        return p[:3], p[3:6]
    return "", ""


def _is_pre_news_blackout(now_utc: datetime,
                          currencies: Sequence[str],
                          ) -> Tuple[bool, str]:
    """Return (True, reason) if `now_utc` falls in the NEWS_PRE_MIN-minute
    window before any high-impact event for any of `currencies`.

    Mirrors gbpusd_bb_bounce._is_pre_news_blackout. Soft on errors —
    any exception returns (False, "") so a calendar-fetch failure can
    never block trading entirely.
    """
    if not NEWS_BLACKOUT_ENABLED or NEWS_PRE_MIN <= 0:
        return False, ""
    if not currencies:
        return False, ""
    try:
        import news_calendar  # local import — keep hot path light
        events = news_calendar.get_todays_events(currencies=list(currencies))
    except Exception:
        return False, ""
    if not events:
        return False, ""
    target_set = {str(c).upper() for c in currencies}
    pre_seconds = float(NEWS_PRE_MIN) * 60.0
    for ev in events:
        if str(ev.get("impact") or "").strip() != "High":
            continue
        ccy = str(ev.get("currency") or "").upper()
        if ccy not in target_set:
            continue
        try:
            h, mi = map(int, str(ev.get("time") or "").split(":"))
        except (ValueError, AttributeError):
            continue
        ev_dt = now_utc.replace(hour=h, minute=mi, second=0, microsecond=0)
        secs_until = (ev_dt - now_utc).total_seconds()
        if 0 < secs_until <= pre_seconds:
            return True, (
                f"news_blackout_pre: {ccy} {ev.get('event_name', '')}"
                f" @ {ev.get('time')}UTC (in {secs_until/60.0:.1f}m)"
            )
    return False, ""


def _classify_gbpusd_regime(df_in: Any) -> Optional[Any]:
    """Run gbpusd_regime_detector.classify_regime on the DataFrame.

    Returns the RegimeResult or None if the detector fails / dataframe
    is unusable. log=False so we don't double-log alongside the
    BB_PIERCE_RUN call site that already writes the regime jsonl.
    """
    try:
        from gbpusd_regime_detector import classify_regime, Bar as RegimeBar
    except Exception as exc:
        logger.warning("[EMA_PULLBACK] regime import failed: %s", exc)
        return None
    try:
        bars: List[Any] = []
        for _, row in df_in.iterrows():
            ts = _ts_to_utc_dt(row.get("timestamp"))
            if ts is None:
                continue
            try:
                bars.append(RegimeBar(
                    timestamp=ts,
                    open=float(row.get("open")),
                    high=float(row.get("high")),
                    low=float(row.get("low")),
                    close=float(row.get("close")),
                ))
            except (TypeError, ValueError):
                continue
        if len(bars) < 80:  # MIN_BARS in regime detector
            return None
        return classify_regime(bars, symbol="GBPUSD", log=False)
    except Exception as exc:
        logger.warning("[EMA_PULLBACK] regime classify failed: %s", exc)
        return None


class EmaPullbackStrategy:
    """EMA-stack pullback continuation in established trends.

    Setup (arm):
      - 4-EMA fanned: 8>13>21>50 (LONG) or 8<13<21<50 (SHORT) with each
        adjacent pair separated by ≥ MIN_FAN_PIPS (per-pair via env)
      - Price touched BB upper (SHORT) / lower (LONG) within last
        BB_LOOKBACK_BARS bars
      - Current bar wicks into the inclusive band between EMA-8 and
        EMA-13

    Fire (entry):
      - Within BB_LOOKBACK_BARS bars of arming, a bar closes back beyond
        the prior bar's high (LONG) or low (SHORT)
      - If no fire within the window, arm dies (can re-arm later)

    SL anchor: distance from entry to EMA-21 + SL_BUFFER_PIPS, floored
    at pair MIN_SL_PIPS. Per-bar in-trade EMA-21 cross invalidation is
    a follow-up workstream (see docs/followups.md).
    """

    def __init__(self) -> None:
        # Armed state: {epic: {direction, armed_idx, armed_ts, armed_close}}
        self._armed: Dict[str, Dict[str, Any]] = {}
        # One fire per session per epic
        self._fired: Dict[str, bool] = {}

    def evaluate(
        self,
        symbol: str,
        epic: str,
        df_in: Any,
        pip_size: float,
        mid_price: float,
        briefing: Optional[Dict[str, Any]],
        router_direction: Optional[str] = None,
    ) -> StrategyDecision:
        sym = str(symbol).upper()

        if df_in is None or len(df_in) < 50:
            return self._none(sym, "ema_pb_insufficient_data")

        last_row = df_in.iloc[-1]
        ts = last_row.get("timestamp")
        if ts is None:
            return self._none(sym, "ema_pb_no_timestamp")

        bst_h = _to_bst_hour(ts)
        # Session window: London 07-12 BST, NY 12-17 BST.
        if bst_h < 7 or bst_h >= 17:
            return self._none(sym, "ema_pb_outside_session")

        day_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        session_label = "London" if bst_h < 12 else "NY"
        session_key = f"{sym}_{day_str}_{session_label}"
        if session_key in self._fired:
            return self._none(sym, "ema_pb_already_fired")

        # --- Read precomputed indicator columns (from candle_builder) ---
        try:
            ema8 = float(last_row["EMA_8"])
            ema13 = float(last_row["EMA_13"])
            ema21 = float(last_row["EMA_21"])
            ema50 = float(last_row["EMA_50"])
        except (KeyError, TypeError, ValueError):
            return self._none(sym, "ema_pb_indicators_missing")

        if not all(np.isfinite(v) for v in (ema8, ema13, ema21, ema50)):
            return self._none(sym, "ema_pb_indicators_warmup")

        # --- Direction from EMA-stack fan with per-pair min separation ---
        pair = _pair_from_epic(epic)
        min_fan_pts = _min_fan_for_pair(pair) * pip_size

        direction: Optional[str] = None
        if (ema8 - ema13) >= min_fan_pts and (ema13 - ema21) >= min_fan_pts and (ema21 - ema50) >= min_fan_pts:
            direction = "BUY"
        elif (ema13 - ema8) >= min_fan_pts and (ema21 - ema13) >= min_fan_pts and (ema50 - ema21) >= min_fan_pts:
            direction = "SELL"

        # --- Existing armed state — fire / expire / drop on direction loss ---
        armed = self._armed.get(epic)

        # ── Router mode: constrain to the router-given direction ──────────
        # The regime engine is the single regime authority; in router mode
        # EMA_PULLBACK only arms/fires the direction the router selected. A
        # self-derived fan in the opposite direction is suppressed — the
        # entry pattern itself (fan/BB/wick/confirmation) is untouched.
        if router_direction is not None and direction is not None:
            _want_dir = "BUY" if str(router_direction).strip().upper() in ("LONG", "BUY") else "SELL"
            if direction != _want_dir:
                if armed is not None and armed.get("direction") != _want_dir:
                    self._armed.pop(epic, None)
                    logger.info(
                        "[EMA_PULLBACK] %s router-suppressed %s setup "
                        "(router_direction=%s) — armed cleared",
                        sym, direction, _want_dir,
                    )
                return self._none(sym, "ema_pb_router_dir_suppressed")

        if direction is None:
            if armed is not None:
                self._armed.pop(epic, None)
                logger.info("[EMA_PULLBACK] %s INVALIDATED — fan lost", sym)
            return self._none(sym, "ema_pb_not_fanned")

        if armed is not None and armed.get("direction") != direction:
            self._armed.pop(epic, None)
            armed = None

        c_high = float(last_row.get("high", 0))
        c_low = float(last_row.get("low", 0))
        c_close = float(last_row.get("close", 0))

        if armed is not None:
            bar_idx = len(df_in) - 1
            bars_since_arm = bar_idx - int(armed["armed_idx"])

            if len(df_in) < 2:
                return self._none(sym, "ema_pb_no_prev")
            prev = df_in.iloc[-2]
            prev_high = float(prev.get("high", 0))
            prev_low = float(prev.get("low", 0))

            fired = False
            if direction == "BUY" and c_close > prev_high:
                fired = True
            elif direction == "SELL" and c_close < prev_low:
                fired = True

            if fired:
                # ── Pre-fire gates: news blackout + regime gate ────────────
                # Run BEFORE consuming the armed setup so we can
                # consume-on-block (don't retry across the blackout/regime
                # block within this session).
                ts_utc = _ts_to_utc_dt(ts)
                if ts_utc is not None:
                    base_ccy, quote_ccy = _affecting_currencies_for_pair(
                        _pair_from_epic(epic),
                    )
                    blocked, blackout_reason = _is_pre_news_blackout(
                        ts_utc, (base_ccy, quote_ccy),
                    )
                    if blocked:
                        self._armed.pop(epic, None)
                        self._fired[session_key] = True
                        logger.info(
                            "[EMA_PULLBACK] %s %s fire suppressed: %s "
                            "— setup cleared",
                            sym, direction, blackout_reason,
                        )
                        return self._none(sym, "ema_pb_news_blackout")

                    # News release window — symmetric [-PRE,+POST] gate on
                    # HIGH GBP/USD. Consume-on-block mirrors the pre-event
                    # branch above (don't retry across the blackout).
                    try:
                        from news_release_window import is_in_release_window
                        _nrw_blocked, _nrw_reason = is_in_release_window(ts_utc)
                        if _nrw_blocked:
                            self._armed.pop(epic, None)
                            self._fired[session_key] = True
                            logger.info(
                                "[NEWS_WINDOW_BLOCK] strategy=EMA_PULLBACK %s %s "
                                "reason=%s — setup cleared",
                                sym, direction, _nrw_reason,
                            )
                            return self._none(sym, "ema_pb_news_release_window")
                    except Exception:
                        pass  # fail-open on suppressor error

                # Regime gate — GBPUSD only, INVERSE of BB_PIERCE_RUN.
                # Block on RANGE; allow TRENDING (ideal) and NEUTRAL.
                # Router mode (router_direction set): SKIPPED — the regime
                # engine is the single regime authority; EMA_PULLBACK must
                # not stack its own regime veto on top (the AND-trap).
                if REGIME_FILTER_ENABLED and sym == "GBPUSD" and router_direction is None:
                    regime_result = _classify_gbpusd_regime(df_in)
                    if regime_result is not None:
                        logger.info(
                            "[EMA_PULLBACK] %s %s fire candidate "
                            "regime=%s conf=%s signals=%s",
                            sym, direction,
                            regime_result.regime, regime_result.confidence,
                            regime_result.signal_breakdown,
                        )
                        if regime_result.regime == "RANGE":
                            self._armed.pop(epic, None)
                            self._fired[session_key] = True
                            logger.info(
                                "[EMA_PULLBACK] %s %s fire suppressed: "
                                "regime_filter_range (conf=%s) — setup cleared",
                                sym, direction, regime_result.confidence,
                            )
                            return self._none(sym, "ema_pb_regime_filter_range")

                # ── Router velocity gate (2026-06-26, LIVE ENFORCE) ─────
                # GBPUSD-only (matches regime-gate scope). Block when the
                # bounce hasn't committed yet (velo_in_faded > MAX).
                # Consume the armed setup on block — mirror the news /
                # regime block semantics on this path. Fail-open on error.
                if EMA_PB_VELOCITY_GATE_ENABLED and sym == "GBPUSD":
                    try:
                        _closes_series = pd.to_numeric(
                            df_in["close"], errors="coerce"
                        ).dropna().to_numpy()
                        if len(_closes_series) >= EMA_PB_VELO_BARS + 1:
                            _vc = float(_closes_series[-1])
                            _vp = float(_closes_series[-1 - EMA_PB_VELO_BARS])
                            _velo_10 = (_vc - _vp) / float(EMA_PB_VELO_BARS) / float(pip_size)
                            _faded_sign = -1.0 if direction == "BUY" else 1.0
                            _velo_in_faded = _velo_10 * _faded_sign
                            _verdict = (
                                "PASS" if _velo_in_faded <= EMA_PB_VELO_MAX
                                else "BLOCK"
                            )
                            _ema_pb_velo_log({
                                "ts_utc": (
                                    ts.strftime("%Y-%m-%dT%H:%M:%SZ")
                                    if hasattr(ts, "strftime") else str(ts)
                                ),
                                "pair": sym,
                                "epic": epic,
                                "strategy": "EMA_PULLBACK",  # router mode
                                "direction": ("LONG" if direction == "BUY"
                                              else "SHORT"),
                                "entry_px": round(c_close, 5),
                                "fired_live": (_verdict == "PASS"),
                                "enforced_block": (_verdict == "BLOCK"),
                                "velo_10": round(_velo_10, 4),
                                "velo_in_faded": round(_velo_in_faded, 4),
                                "threshold_max": EMA_PB_VELO_MAX,
                                "bars": EMA_PB_VELO_BARS,
                                "verdict": _verdict,
                            })
                            if _verdict == "BLOCK":
                                self._armed.pop(epic, None)
                                self._fired[session_key] = True
                                logger.info(
                                    "[EMA_PB_VELO_BLOCK] %s %s velo_10=%+.3fp/bar "
                                    "velo_in_faded=%+.3fp/bar thr_max=%.3f "
                                    "(bounce not committed) — setup cleared",
                                    sym, direction, _velo_10, _velo_in_faded,
                                    EMA_PB_VELO_MAX,
                                )
                                return self._none(
                                    sym, "ema_pb_velocity_blocked",
                                )
                        else:
                            _ema_pb_velo_log({
                                "ts_utc": (
                                    ts.strftime("%Y-%m-%dT%H:%M:%SZ")
                                    if hasattr(ts, "strftime") else str(ts)
                                ),
                                "pair": sym,
                                "epic": epic,
                                "strategy": "EMA_PULLBACK",
                                "direction": ("LONG" if direction == "BUY"
                                              else "SHORT"),
                                "verdict": "INSUFFICIENT_BARS",
                                "have_closes": int(len(_closes_series)),
                                "need_closes": EMA_PB_VELO_BARS + 1,
                            })
                    except Exception as _velo_exc:
                        logger.warning(
                            "[EMA_PB_VELO_ERROR] %s %s velocity gate compute "
                            "failed: %s — fail-open, fire proceeds",
                            sym, direction, _velo_exc,
                        )

                self._armed.pop(epic, None)
                self._fired[session_key] = True
                return self._build_decision(
                    sym, epic, direction, c_close, ema21, pip_size,
                    bars_since_arm, ema8, ema13, ema50, session_label,
                )

            if bars_since_arm >= BB_LOOKBACK_BARS:
                self._armed.pop(epic, None)
                logger.info(
                    "[EMA_PULLBACK] %s INVALIDATED — window expired (%d bars)",
                    sym, bars_since_arm,
                )
                # Fall through to potentially re-arm this same bar.
            else:
                return self._none(sym, f"ema_pb_armed_waiting_{bars_since_arm}b")

        # --- Setup conditions for new arm ---
        # 1. BB-extension within last BB_LOOKBACK_BARS bars.
        try:
            lookback = df_in.iloc[-BB_LOOKBACK_BARS:]
            if direction == "BUY":
                lows = pd.to_numeric(lookback["low"], errors="coerce")
                bbl = pd.to_numeric(lookback["BB_LOWER_20_2"], errors="coerce")
                bb_extreme_touched = bool((lows <= bbl).any())
            else:
                highs = pd.to_numeric(lookback["high"], errors="coerce")
                bbu = pd.to_numeric(lookback["BB_UPPER_20_2"], errors="coerce")
                bb_extreme_touched = bool((highs >= bbu).any())
        except Exception:
            return self._none(sym, "ema_pb_bb_lookback_failed")

        if not bb_extreme_touched:
            return self._none(sym, "ema_pb_no_recent_bb_extreme")

        # 2. Wick into inclusive EMA-8/EMA-13 zone on this bar.
        if direction == "BUY":
            zone_lo, zone_hi = ema13, ema8  # LONG: 13 < 8
        else:
            zone_lo, zone_hi = ema8, ema13  # SHORT: 8 < 13
        wick_in_zone = (c_low <= zone_hi) and (c_high >= zone_lo)

        if not wick_in_zone:
            return self._none(sym, "ema_pb_no_wick_in_zone")

        # ARM
        self._armed[epic] = {
            "direction": direction,
            "armed_idx": len(df_in) - 1,
            "armed_ts": ts,
            "armed_close": c_close,
        }
        if direction == "BUY":
            fan_pips = min(ema8 - ema13, ema13 - ema21, ema21 - ema50) / pip_size
        else:
            fan_pips = min(ema13 - ema8, ema21 - ema13, ema50 - ema21) / pip_size
        logger.info(
            "[EMA_PULLBACK] %s ARMED %s — fan_pips=%.2f, BB-extreme within %db, "
            "wick into EMA-8/13 zone (close=%.5f, low=%.5f, high=%.5f, "
            "ema8=%.5f, ema13=%.5f)",
            sym, direction, fan_pips, BB_LOOKBACK_BARS,
            c_close, c_low, c_high, ema8, ema13,
        )
        return self._none(sym, "ema_pb_armed")

    # ------------------------------------------------------------------
    def _build_decision(
        self,
        sym: str,
        epic: str,
        direction: str,
        entry_close: float,
        ema21: float,
        pip_size: float,
        bars_since_arm: int,
        ema8: float,
        ema13: float,
        ema50: float,
        session_label: str,
    ) -> StrategyDecision:
        pair = _pair_from_epic(epic)
        min_sl = _PAIR_MIN_SL_PIPS.get(pair, 0)

        # SL anchor: |entry - EMA_21| + SL_BUFFER_PIPS, floored at pair MIN_SL_PIPS.
        # The fanned-stack invariant guarantees entry is on the correct
        # side of EMA_21 (above for LONG, below for SHORT).
        if direction == "BUY":
            sl_distance_pips = (entry_close - ema21) / pip_size + SL_BUFFER_PIPS
        else:
            sl_distance_pips = (ema21 - entry_close) / pip_size + SL_BUFFER_PIPS
        sl_pips = max(float(min_sl), float(sl_distance_pips))

        # TP placeholder — dispatch wrapper's select_tp_levels (in
        # strategy_logic) overrides this with briefing-level resolution.
        tp_pips = float(DEFAULT_TP_PIPS)

        logger.info(
            "[EMA_PULLBACK] %s FIRED %s @ %.5f — confirmation close past "
            "prior extreme (bars_since_arm=%d, sl=%.1fp, ema21=%.5f)",
            sym, direction, entry_close, bars_since_arm, sl_pips, ema21,
        )

        return StrategyDecision(
            symbol=sym,
            regime="EMA_PULLBACK",
            signal=direction,
            mode=EMA_PULLBACK_MODE,
            entry=float(entry_close),
            sl=float(round(sl_pips, 2)),
            tp=float(round(tp_pips, 2)),
            use_trailing_stop=True,
            reason=f"ema_pullback_{direction.lower()}",
            debug={
                "ema8": round(ema8, 5),
                "ema13": round(ema13, 5),
                "ema21": round(ema21, 5),
                "ema50": round(ema50, 5),
                "bars_since_arm": bars_since_arm,
                "session": session_label,
                "sl_pips": round(sl_pips, 2),
                "sl_anchor": "ema21_distance",
            },
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _none(sym: str, reason: str) -> StrategyDecision:
        return StrategyDecision(
            symbol=sym,
            regime="EMA_PULLBACK",
            signal="NONE",
            mode=EMA_PULLBACK_MODE,
            entry=None,
            sl=None,
            tp=None,
            use_trailing_stop=False,
            reason=reason,
        )
