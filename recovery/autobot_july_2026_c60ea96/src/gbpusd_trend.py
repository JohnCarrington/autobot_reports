"""
gbpusd_trend.py — H1-LEADS trend-continuation (rebuilt 2026-05-23).

Replaces the cascade-driven design (commit d7e7c82). The cascade keyed off
the Phase-4B regime_classifier's stable trend label, which committed too
late — winners on real data fired while cascade was still NEUTRAL.

NEW design:

  CONTEXT GATE (permissive, H1-LEADS):
    - indicators.h1_ema_direction(symbol) must agree with candidate
      direction with separation_strength >= H1_STRENGTH_FLOOR.
      (Catches early trend while it's still forming.)
    - Regime-not-opposing veto is a deferred follow-up — see TODO below.

  ENTRY TRIGGER (rebuilt 2026-05-28 — light confirm + structural dip-resume):
    LIGHT (replaces old gates 1-5 is_clean_trend chain):
         H1 MACD(12,26,9) line agrees with side — LONG → line > signal,
         SHORT → line < signal. The other four is_clean_trend conditions
         (close vs EMA50, EMA21 stack, MACD-hist sign, N-of-10 directional)
         are NOT gates anymore. Kill: GBPUSD_TREND_MACD_CONFIRM_ENABLED=0
         falls back to CONTEXT direction alone.
    6.   H1 freshness MIN floor: at least FRESHNESS_MIN H1 bars of clean-
         trend label in side direction (default 1 — fluke filter only).
         NO maximum ceiling (the old max=6 was removed 2026-05-28).
         _update_h1_streak still calls is_clean_trend to label H1 bars
         for the streak counter — but is_clean_trend's LABEL is not a
         direct entry gate anymore.
    DIP-RESUME (replaces old gates 7-8, the 5m pierce + momentum-third):
         Shallow pullback to 5m EMA8 then break of dip window extreme.
         LONG fires when:
             * dip window = last DIP_MAX_BARS closed 5m bars before cur
               (default 3)
             * dip touched 5m_EMA8: min(low over window) <= 5m_ema8
             * shallow: NO dip-window bar closed beyond 5m_EMA21
               (any bar.close < ema21 → DISQUALIFY, dip too deep)
             * trigger: cur.high > max(high over window) AND cur closes UP
         SHORT mirrors with sign flips.
    9.   Per-H1-bucket dedup: at most one fire per direction per H1 bar.

  RISK:
    - SL = 12p (IG minimum; GBPUSD_TREND_SL_PIPS, was 20).
    - Broker TP = 80p (preserved).
    - +10p scale-out (universal, in trade_manager) banks half + moves SL to BE.
    - Runner trail = trade_manager._apply_trend_runner_trail (centralised).
      3-step ratchet at peak MFE = 15/25/40p; lock = peak − offset (8p).
      Mode tag GBPUSD_TREND_L/_S is in _TREND_RUNNER_STYLE_MODES.

Realised history (Feb-May 2026): predecessor GBPUSD_TREND_CONT_L = 13 trades,
62% WR, +36.9p net, +2.84p/trade. The 9-gate trigger fired ~1/day in production
— not a fire-never AND-chain.

Module surface (preserved for autobot.py compatibility):
    ENABLED, MODE_NAME_LONG, MODE_NAME_SHORT, SL_PIPS, TREND_BROKER_TP_PIPS,
    TREND_INITIAL_SL_PIPS, PIP_SIZE, Bar, GbpUsdTrendStrategy,
    strategy (instance), evaluate_5m_close, mark_position_opened,
    mark_position_closed. update_trailing_stop/commit_trail_step removed —
    trail is centralised; module-level no-op stubs kept for defensive caller
    compatibility but they do nothing.

TODO: add regime-engine-not-opposing veto. Requires either autobot wiring
to pass the latest regime emission into evaluate_5m_close, or reading the
last line of logs/regime_engine.jsonl. H1 vote alone provides directional
context for now; the 9-gate entry provides selectivity.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────────────────────
# Public module surface
# ─────────────────────────────────────────────────────────────────────────────
LOG_TAG = "TREND"
MODE_NAME_LONG = "GBPUSD_TREND_L"
MODE_NAME_SHORT = "GBPUSD_TREND_S"

# Persistence (only for dedup state across restarts).
STATE_FILE = "/opt/tradingbot/cache/gbpusd_trend_state.json"

PIP_SIZE = 1.0  # GBPUSD on IG TODAY epic: 1 raw point = 1 pip

def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


ENABLED = _env_bool("GBPUSD_TREND_ENABLED", "true")
TRADE_SIZE = _env_float("TRADE_SIZE", 1.0)

# Risk geometry.
# SL = 12 pips (IG minimum stop distance for GBPUSD). Was 20p ("Fix 1") —
# rebuilt 2026-05-28 to ride dip-resume entries closer to risk so the
# universal +10p scale-out (in trade_manager) banks half at +10 with
# runner-to-BE. Tunable via GBPUSD_TREND_SL_PIPS.
SL_PIPS = _env_float("GBPUSD_TREND_SL_PIPS", 12.0)
TREND_INITIAL_SL_PIPS = SL_PIPS         # alias for back-compat
TREND_BROKER_TP_PIPS = 80.0             # broker TP distance

# ── CONTEXT gate (H1-LEADS, permissive) ──────────────────────────────────
# Minimum H1 EMA8-vs-EMA21 separation strength (0..1, 1.0 = 15p separation
# per indicators.h1_ema_direction's full_strength_separation_pips). 0.3 ≈
# 4.5p separation — "EMAs clearly apart, not crossing."
H1_STRENGTH_FLOOR = _env_float("GBPUSD_TREND_H1_STRENGTH_FLOOR", 0.3)

# ── ENTRY trigger (rebuilt 2026-05-28) ───────────────────────────────────
# LIGHT confirmation — H1 MACD(12,26,9) line vs signal, side-agreeing.
# Replaces the full 5-condition is_clean_trend label-match. Set to 0 to
# skip MACD confirmation entirely (direction from CONTEXT alone).
MACD_CONFIRM_ENABLED = _env_bool("GBPUSD_TREND_MACD_CONFIRM_ENABLED", "1")

# is_clean_trend's directional-close-count parameter — used ONLY for the
# H1 streak label that drives the Gate-6 MIN-floor fluke filter, NOT
# for a direct entry gate anymore.
TREND_MIN_DIRECTIONAL = _env_int("GBPUSD_TREND_MIN_DIRECTIONAL", 8)

# Gate 6 — H1 freshness MIN floor (fluke filter only). The trend must
# have been "clean" for at least MIN H1 bars so a single-bar fluke can't
# fire. There is NO maximum — a long-running trend is more tradeable,
# not less. The old max=6 ceiling blocked the accelerating leg of every
# sustained trend (see 2026-05-27/28 overnight: blocked 11 of 16 H1
# buckets including every accelerating bar) and is removed.
FRESHNESS_MIN_H1_BARS = _env_int("GBPUSD_TREND_FRESHNESS_MIN", 1)

# Dip-resume trigger — replaces old gates 7 (5m pierce) + 8 (momentum
# third). Window of closed 5m bars to scan for the shallow dip-to-EMA8
# pullback before the current bar's resume break. Larger = looks back
# further for the dip; smaller = requires tighter / more recent dip.
DIP_MAX_BARS = _env_int("GBPUSD_TREND_DIP_MAX_BARS", 3)

# Version C fast-context kill-switch.
# When TRUE, is_clean_trend uses price-vs-EMA21 in place of the slow
# EMA21<EMA50 / EMA21>EMA50 stack-cross gate. Measurement showed this
# flips trend-DOWN ~3 H1 bars earlier than Version A without firing
# in flat / chop sessions. Scoped to this strategy only — bb_reversal
# and bb_reversal_long callers continue to use Version A (default).
# Default OFF: flip the env to "1"/"true"/"yes" to enable.
TREND_FAST_CONTEXT_ENABLED = _env_bool("GBPUSD_TREND_FAST_CONTEXT_ENABLED", "0")


@dataclass
class Bar:
    timestamp: Any  # datetime tz-aware UTC
    open: float
    high: float
    low: float
    close: float


def _ema_seq(values: Sequence[float], period: int) -> List[float]:
    """5m EMA computed inline so the dip-resume trigger doesn't have to
    cross the trend_detection / indicators boundary. Mirrors the seed
    convention used by trend_detection._ema (period-mean seed)."""
    if not values:
        return []
    if period <= 1:
        return list(values)
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period if len(values) >= period else values[0]
    out: List[float] = []
    for i, v in enumerate(values):
        out.append(seed if i == 0 else out[-1] + k * (v - out[-1]))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# State persistence (dedup + clean-streak tracking)
# ─────────────────────────────────────────────────────────────────────────────
_STATE_LOCK = threading.Lock()


def _empty_pair_state() -> Dict[str, Any]:
    return {
        # Per-direction last-fired H1 bucket (ISO-format hour timestamp) —
        # gate 9 dedup. Max one fire per direction per H1 bar.
        "last_fired_h1_long": None,
        "last_fired_h1_short": None,
        # Clean-trend streak counter — gate 6 freshness.
        # Each H1 bar: if is_clean_trend label matches the current streak's
        # direction, increment; if direction flips or goes NONE, reset.
        # Tracked per direction so we have UP and DOWN streaks independently.
        "h1_clean_up_streak": 0,
        "h1_clean_down_streak": 0,
        "last_h1_streak_bar": None,  # ISO-format H1 bar timestamp processed
    }


def _load_state() -> Dict[str, Dict[str, Any]]:
    p = Path(STATE_FILE)
    if not p.exists():
        return {}
    try:
        with p.open("r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:
        logger.warning("[%s] state load failed: %s", LOG_TAG, exc)
        return {}


def _save_state(state: Dict[str, Dict[str, Any]]) -> None:
    p = Path(STATE_FILE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=str(p.parent), prefix=".gbpusd_trend_state_",
            suffix=".tmp", delete=False,
        )
        try:
            json.dump(state, tmp, indent=2, default=str)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.replace(tmp.name, str(p))
    except Exception as exc:
        logger.warning("[%s] state save failed: %s", LOG_TAG, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy class
# ─────────────────────────────────────────────────────────────────────────────
class GbpUsdTrendStrategy:
    def __init__(self) -> None:
        with _STATE_LOCK:
            self._state: Dict[str, Dict[str, Any]] = _load_state()

    def _pair_state(self, pair: str) -> Dict[str, Any]:
        with _STATE_LOCK:
            if pair not in self._state:
                self._state[pair] = _empty_pair_state()
            return self._state[pair]

    def _persist(self) -> None:
        with _STATE_LOCK:
            _save_state(self._state)

    # ── Public API ──────────────────────────────────────────────────────

    def evaluate_5m_close(self,
                          pair: str,
                          bars: Sequence[Bar],
                          has_active_position: bool = False,
                          ) -> Optional["StrategyDecision"]:
        """Called on each new 5m close. Returns a fire-decision or None.

        Bars are CLOSED 5m bars, oldest first, last bar = most recent close.
        """
        if not ENABLED:
            return None
        if str(pair).upper() != "GBPUSD":
            return None
        if has_active_position:
            return None
        if not bars or len(bars) < 21:
            return None

        # Update H1 clean-trend streak from latest H1 candles (gate 6 input).
        self._update_h1_streak(pair)

        # CONTEXT — H1 EMA-stack direction (the permissive lead).
        h1 = self._h1_direction()
        if h1 is None:
            return None
        h1_dir = h1.get("direction")
        h1_strength = float(h1.get("separation_strength") or 0.0)
        if h1_dir not in ("BULLISH", "BEARISH") or h1_strength < H1_STRENGTH_FLOOR:
            # H1 flat or too weak — no directional lead, no fire.
            logger.debug(
                "[%s] %s context skip: h1=%s strength=%.2f (floor %.2f)",
                LOG_TAG, pair, h1_dir, h1_strength, H1_STRENGTH_FLOOR,
            )
            return None
        side = "LONG" if h1_dir == "BULLISH" else "SHORT"
        direction = "BUY" if side == "LONG" else "SELL"

        # LIGHT confirm (replaces old gates 1-5 is_clean_trend label match):
        # H1 MACD(12,26,9) line vs signal must agree with side. The other
        # is_clean_trend conditions (close/EMA50, EMA21 stack, hist sign,
        # N-of-10 directional) are NOT entry gates anymore — but is_clean_trend
        # still runs inside _update_h1_streak to label H1 bars for the
        # Gate-6 fluke-filter streak.
        if MACD_CONFIRM_ENABLED:
            if not self._h1_macd_agrees(side):
                logger.debug(
                    "[%s] %s entry skip MACD confirm (side=%s)",
                    LOG_TAG, pair, side,
                )
                return None

        # Gate 6: H1 freshness MIN floor — fluke filter only. NO maximum:
        # a long-running trend is more tradeable, not less. The old max=6
        # ceiling was removed 2026-05-28 (blocked the accelerating leg of
        # the 2026-05-27/28 overnight downtrend — 11 of 16 H1 buckets,
        # including every bar where the move accelerated).
        ps = self._pair_state(pair)
        streak = (ps["h1_clean_up_streak"] if side == "LONG"
                  else ps["h1_clean_down_streak"])
        if streak < FRESHNESS_MIN_H1_BARS:
            logger.debug(
                "[%s] %s entry skip g6 freshness: streak=%d < min=%d",
                LOG_TAG, pair, streak, FRESHNESS_MIN_H1_BARS,
            )
            return None

        # DIP-RESUME trigger (replaces old gates 7-8 pierce + momentum-third).
        # Need DIP_MAX_BARS dip-window bars BEFORE the current bar.
        if len(bars) < DIP_MAX_BARS + 2:
            return None
        cur_bar = bars[-1]
        dip_window = list(bars[-1 - DIP_MAX_BARS:-1])

        closes_5m = [float(b.close) for b in bars]
        ema8_seq = _ema_seq(closes_5m, 8)
        ema21_seq = _ema_seq(closes_5m, 21)
        ema8 = ema8_seq[-1]
        ema21 = ema21_seq[-1]

        dip_low = min(b.low for b in dip_window)
        dip_high = max(b.high for b in dip_window)

        if side == "LONG":
            touched_ema8 = (dip_low <= ema8)
            shallow = all(b.close >= ema21 for b in dip_window)
            broke_level = (cur_bar.high > dip_high)
            closed_with_dir = (cur_bar.close > cur_bar.open)
            break_level = dip_high
        else:  # SHORT
            touched_ema8 = (dip_high >= ema8)
            shallow = all(b.close <= ema21 for b in dip_window)
            broke_level = (cur_bar.low < dip_low)
            closed_with_dir = (cur_bar.close < cur_bar.open)
            break_level = dip_low

        if not (touched_ema8 and shallow):
            logger.debug(
                "[%s] %s entry skip dip (touched_ema8=%s shallow=%s "
                "ema8=%.5f ema21=%.5f dip_low=%.5f dip_high=%.5f)",
                LOG_TAG, pair, touched_ema8, shallow,
                ema8, ema21, dip_low, dip_high,
            )
            return None
        if not (broke_level and closed_with_dir):
            logger.debug(
                "[%s] %s entry skip break (broke=%s closed_dir=%s "
                "cur=O%.5f H%.5f L%.5f C%.5f break_lvl=%.5f)",
                LOG_TAG, pair, broke_level, closed_with_dir,
                cur_bar.open, cur_bar.high, cur_bar.low, cur_bar.close,
                break_level,
            )
            return None

        # Gate 9: per-H1-bucket dedup.
        cur_ts = cur_bar.timestamp
        if not isinstance(cur_ts, datetime):
            return None
        h1_bucket = cur_ts.replace(minute=0, second=0, microsecond=0).isoformat()
        last_key = ("last_fired_h1_long" if side == "LONG"
                    else "last_fired_h1_short")
        if ps.get(last_key) == h1_bucket:
            logger.debug(
                "[%s] %s entry skip g9 dedup: already fired %s this H1 bucket %s",
                LOG_TAG, pair, side, h1_bucket,
            )
            return None

        # All gates passed → fire.
        entry_price = float(cur_bar.close)
        if side == "LONG":
            sl_price = entry_price - SL_PIPS * PIP_SIZE
            tp_price = entry_price + TREND_BROKER_TP_PIPS * PIP_SIZE
            mode = MODE_NAME_LONG
        else:
            sl_price = entry_price + SL_PIPS * PIP_SIZE
            tp_price = entry_price - TREND_BROKER_TP_PIPS * PIP_SIZE
            mode = MODE_NAME_SHORT

        # Mark dedup.
        ps[last_key] = h1_bucket
        self._persist()

        from strategy_logic import StrategyDecision  # local import to avoid cycle
        logger.info(
            "[%s] %s %s FIRE @ %.5f SL=%.5f TP=%.5f | h1=%s strength=%.2f "
            "macd_confirm=%s streak=%d ema8=%.5f ema21=%.5f "
            "dip_low=%.5f dip_high=%.5f break_lvl=%.5f h1_bucket=%s",
            LOG_TAG, pair, side, entry_price, sl_price, tp_price,
            h1_dir, h1_strength, MACD_CONFIRM_ENABLED, streak,
            ema8, ema21, dip_low, dip_high, break_level, h1_bucket,
        )
        return StrategyDecision(
            symbol=pair,
            regime="TREND",
            signal=direction,
            mode=mode,
            entry=entry_price,
            sl=round(sl_price, 5),
            tp=round(tp_price, 5),
            use_trailing_stop=False,  # broker SL/TP; runner trail in trade_manager
            reason=(f"h1_{h1_dir.lower()}_s{h1_strength:.2f} "
                    f"macd_confirm streak{streak} "
                    f"dip_to_ema8_then_break"),
            debug={
                "runner_style": "TREND",  # mirror for any consumer that reads decision.debug
                "h1_direction": h1_dir,
                "h1_separation_strength": h1_strength,
                "h1_separation_pips": h1.get("separation_pips"),
                "macd_confirm_enabled": MACD_CONFIRM_ENABLED,
                "h1_freshness_streak": streak,
                "h1_bucket": h1_bucket,
                "entry_5m_close": entry_price,
                "ema8_5m": ema8,
                "ema21_5m": ema21,
                "dip_window_bars": DIP_MAX_BARS,
                "dip_low": dip_low,
                "dip_high": dip_high,
                "break_level": break_level,
                "cur_open": cur_bar.open,
                "cur_high": cur_bar.high,
                "cur_low": cur_bar.low,
                "cur_close": cur_bar.close,
            },
            size=TRADE_SIZE,
            pip_size=PIP_SIZE,
        )

    def mark_position_opened(self, pair: str, **kwargs) -> None:
        """Called by autobot after a successful execute_trade. No-op now —
        state-machine arming was removed in the H1-LEADS rebuild. Kept for
        signature compatibility."""
        logger.debug("[%s] mark_position_opened(%s) (no-op)", LOG_TAG, pair)

    def mark_position_closed(self, pair: str, reason: str = "",
                             **kwargs) -> None:
        """Called by autobot when a position closes. No-op — dedup is per-H1-
        bucket and self-clearing on the next bucket; no streak reset needed."""
        logger.debug(
            "[%s] mark_position_closed(%s, reason=%s) (no-op)",
            LOG_TAG, pair, reason,
        )

    # ── Internal helpers ────────────────────────────────────────────────

    def _h1_direction(self) -> Optional[Dict[str, Any]]:
        """Wrapper around indicators.h1_ema_direction(GBPUSD)."""
        try:
            import indicators
            return indicators.h1_ema_direction("GBPUSD", pip_size=PIP_SIZE)
        except Exception as exc:
            logger.warning("[%s] h1_ema_direction failed: %s", LOG_TAG, exc)
            return None

    def _h1_macd_agrees(self, side: str) -> bool:
        """H1 MACD(12,26,9) line-vs-signal agreement check (light confirmation).
        LONG → macd_line > signal_line; SHORT → macd_line < signal_line.

        Returns False on insufficient data or cache failure (fail-closed —
        cheaper than a wrong fire, and the strategy already has CONTEXT to
        confirm direction).
        """
        try:
            from trend_detection import h1_macd_agreement
        except Exception as exc:
            logger.warning(
                "[%s] h1_macd_agreement import failed: %s", LOG_TAG, exc,
            )
            return False
        agreement = h1_macd_agreement("GBPUSD")
        if agreement is None:
            return False
        if side == "LONG":
            return agreement == "BULLISH"
        return agreement == "BEARISH"

    def _is_clean_trend(self):
        """trend_detection.is_clean_trend on cached H1 candles. Returns
        ("UP" | "DOWN" | "NONE", details).

        Passes fast_context=TREND_FAST_CONTEXT_ENABLED so the env-flag
        toggles between Version A (slow EMA21<EMA50 cross) and Version
        C (price-vs-EMA21). Other strategies that call is_clean_trend
        directly do NOT pass this kwarg and keep Version A by default.
        """
        try:
            from trend_detection import is_clean_trend, load_h1_candles_from_cache
        except Exception as exc:
            logger.warning("[%s] trend_detection import failed: %s", LOG_TAG, exc)
            return "NONE", {"reason": "import_failed"}
        candles = load_h1_candles_from_cache("GBPUSD")
        return is_clean_trend("GBPUSD", candles,
                              min_directional=TREND_MIN_DIRECTIONAL,
                              fast_context=TREND_FAST_CONTEXT_ENABLED)

    def _update_h1_streak(self, pair: str) -> None:
        """Update the H1 clean-trend streak counters from the latest H1 bar.
        Idempotent per H1 bar — only advances when a NEW H1 bar has closed
        since the last update.
        """
        try:
            from trend_detection import load_h1_candles_from_cache
        except Exception:
            return
        candles = load_h1_candles_from_cache(pair)
        if not candles:
            return
        last = candles[-1]
        last_ts = last.get("timestamp") or last.get("bucket_epoch")
        last_ts_str = str(last_ts) if last_ts is not None else None
        ps = self._pair_state(pair)
        if last_ts_str is None or ps.get("last_h1_streak_bar") == last_ts_str:
            return
        # New H1 bar — evaluate clean-trend label and advance/reset streak.
        try:
            from trend_detection import is_clean_trend
            label, _ = is_clean_trend(pair, candles,
                                       min_directional=TREND_MIN_DIRECTIONAL,
                                       fast_context=TREND_FAST_CONTEXT_ENABLED)
        except Exception:
            label = "NONE"
        if label == "UP":
            ps["h1_clean_up_streak"] = int(ps.get("h1_clean_up_streak") or 0) + 1
            ps["h1_clean_down_streak"] = 0
        elif label == "DOWN":
            ps["h1_clean_down_streak"] = int(ps.get("h1_clean_down_streak") or 0) + 1
            ps["h1_clean_up_streak"] = 0
        else:
            ps["h1_clean_up_streak"] = 0
            ps["h1_clean_down_streak"] = 0
        ps["last_h1_streak_bar"] = last_ts_str
        self._persist()


# ─────────────────────────────────────────────────────────────────────────────
# Module-level instance + thin wrappers (preserves autobot import surface)
# ─────────────────────────────────────────────────────────────────────────────
strategy = GbpUsdTrendStrategy()


def evaluate_5m_close(*args, **kwargs):
    return strategy.evaluate_5m_close(*args, **kwargs)


def mark_position_opened(*args, **kwargs):
    return strategy.mark_position_opened(*args, **kwargs)


def mark_position_closed(*args, **kwargs):
    return strategy.mark_position_closed(*args, **kwargs)


# Defensive no-op stubs — the old per-strategy trail API was removed in the
# 2026-05-23 rebuild; trade_manager._apply_trend_runner_trail is the trail
# now. Any straggler caller gets a no-op rather than AttributeError.
def update_trailing_stop(*args, **kwargs):
    """REMOVED — see trade_manager._apply_trend_runner_trail."""
    return None


def commit_trail_step(*args, **kwargs):
    """REMOVED — see trade_manager._apply_trend_runner_trail."""
    return None
