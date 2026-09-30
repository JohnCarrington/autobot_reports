"""
gbpusd_trend_v3.py — GBPUSD daily-spine trend strategy (v3 rebuild).

Built backwards from the exit (v1 died of exit-choke, v2 of chop-fires +
anchorless TP). The spine is the prior completed daily candle direction;
the strategy never fires against it. Entry stacks STRONG_TREND regime +
ADX + ER. Target is structural (H4 high/low or 5m swing). Exit is
flatten/exhaustion (6 bars no new extreme AND momentum fade) with
backstops (structural reversal close, or regime leaves STRONG_TREND).

INVARIANTS (STEP 5):
  - Daily-spine: only LONG when prior daily UP; only SHORT when prior daily DOWN
  - Entry: daily-aligned + STRONG_TREND_* + ADX>=ADX_MIN + ER>=ER_MIN
  - Target: structural (H4 high/low above/below current close; fallback 5m swing;
            fallback measured-move = 2.5 * ATR(14) in pips when no clean level)
  - Exit primary: (no new extreme N bars) AND (ER dropped below entry_ER
                  OR MACD_HIST contracting)
  - Exit backstop: close past structural (entry-side reversal), OR
                   regime leaves STRONG_TREND family
  - No 2h time-choke; trade_manager._on_position_management gets a wide
    safety override (TREND_V3_MAX_HOLD_MIN, default 1440min = 24h)
  - No MPP — removed codebase-wide 2026-05-23
  - Scale-out: universal +10p/50% (trade_manager auto-runs); SL→BE auto
  - Live full size: decision.size=None → trade_executor uses TRADE_SIZE (.env)
  - Daily candle is the LAST CLOSED D1 from TimeframeContext._d1_closed
    (no lookahead — D1 list contains only completed bars by construction)
  - BB_BOUNCE / stand-down / trails / scale-out: untouched (additive module)

Default disabled in code. Set TREND_V3_ENABLED=1 in .env on host to enable.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_trend_v3")

LOG_TAG = "TREND_V3"
MODE_NAME_LONG  = "GBPUSD_TREND_V3_L"
MODE_NAME_SHORT = "GBPUSD_TREND_V3_S"

PIP_SIZE = 1.0  # GBPUSD on IG: 1 raw point = 1 pip


def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


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


# ─── Configuration ───────────────────────────────────────────────────────
ENABLED = _env_bool("TREND_V3_ENABLED", "0")
_REGIME_MATRIX_ENABLED = _env_bool("REGIME_MATRIX_ENABLED", "0")

ADX_MIN              = _env_float("TREND_V3_ADX_MIN", 25.0)
ER_MIN               = _env_float("TREND_V3_ER_MIN", 0.5)
ER_BARS              = _env_int("TREND_V3_ER_BARS", 20)         # Kaufman window
FLATTEN_BARS         = _env_int("TREND_V3_FLATTEN_BARS", 6)
SL_FALLBACK_PIPS     = _env_float("TREND_V3_SL_FALLBACK_PIPS", 15.0)
SL_BUFFER_PIPS       = _env_float("TREND_V3_SL_BUFFER_PIPS", 2.0)  # below swing low / above swing high
# 2026-07-15: hard cap on the final structural SL distance. Motivation —
# 96 real TREND-family fills: only 3/96 winners ever exceeded 12p MAE.
# Applied AFTER swing/fallback resolution in _resolve_target_and_sl so the
# swing selection itself is untouched. Kill switch: set TREND_V3_MAX_SL_PIPS=0
# (or empty) to disable the cap and restore full structural stops.
def _resolve_max_sl_pips() -> float:
    raw = os.getenv("TREND_V3_MAX_SL_PIPS", "12")
    if raw is None or str(raw).strip() in ("", "0"):
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0
MAX_SL_PIPS          = _resolve_max_sl_pips()
TP_FALLBACK_ATR_MULT = _env_float("TREND_V3_TP_FALLBACK_ATR_MULT", 2.5)
TP_FALLBACK_PIPS     = _env_float("TREND_V3_TP_FALLBACK_PIPS", 30.0)
H4_LOOKBACK_BARS     = _env_int("TREND_V3_H4_LOOKBACK_BARS", 12)
MIN_TARGET_PIPS      = _env_float("TREND_V3_MIN_TARGET_PIPS", 10.0)
MAX_TARGET_PIPS      = _env_float("TREND_V3_MAX_TARGET_PIPS", 200.0)

JSONL_PATH = os.getenv("TREND_V3_LOG_PATH", "/opt/tradingbot/logs/trend_v3.jsonl")

# Safety time-stop honored in trade_manager — wide by design (24h).
SAFETY_MAX_HOLD_MIN  = _env_int("TREND_V3_MAX_HOLD_MIN", 1440)

# 2026-07-15: INTRADAY DIRECTION FLIP. The daily spine locks the evaluable
# direction all day; on reversal days (e.g. Tue 07-14, struct STRONG_TREND_DOWN
# committed 09:05 and held ~4h) the primary strategy sat wrong-way and could
# not evaluate shorts. Behaviour: when the regime engine holds a struct-path
# STRONG_TREND label opposing the spine for FLIP_CONFIRM_BARS consecutive
# committed 5m closes, the evaluable direction flips to follow the engine;
# it reverts on the same N-bar persistence of the engine agreeing with the
# spine or going non-STRONG. The spine value itself is NEVER mutated (SB
# and trend_stretch_brake read _prior_daily_direction directly). Kill switch
# TREND_V3_INTRADAY_FLIP_ENABLED=0 → counters never increment, byte-identical.
INTRADAY_FLIP_ENABLED = _env_bool("TREND_V3_INTRADAY_FLIP_ENABLED", "1")
FLIP_CONFIRM_BARS     = _env_int("TREND_V3_FLIP_CONFIRM_BARS", 6)

# 2026-07-21: Session gate. TREND_V3 previously had no active-hours guard
# and fired 02:20–18:50 UTC (14/35 out-of-London-NY fires observed). Mirrors
# the BB_BOUNCE / EMA_PULLBACK _in_window mechanism (module-level start/end
# + method check) — HH:MM env format for minute-granularity. Kill-switch
# SESSION_GATE_ENABLED=0 = byte-identical prior behaviour.
def _env_hhmm(name: str, default_hhmm: str) -> dtime:
    raw = os.getenv(name, default_hhmm).strip()
    try:
        h, m = raw.split(":")
        return dtime(int(h), int(m))
    except Exception:
        dh, dm = default_hhmm.split(":")
        return dtime(int(dh), int(dm))

SESSION_GATE_ENABLED = _env_bool("TREND_V3_SESSION_GATE_ENABLED", "1")
SESSION_START        = _env_hhmm("TREND_V3_SESSION_START_UTC", "07:00")
SESSION_END          = _env_hhmm("TREND_V3_SESSION_END_UTC",   "16:00")


# ─── Bar dataclass ───────────────────────────────────────────────────────
@dataclass
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


# ─── JSONL writer (telemetry — must never raise into the fire path) ─────
def _write_jsonl(row: Dict[str, Any]) -> None:
    try:
        d = os.path.dirname(JSONL_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(JSONL_PATH, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception as exc:
        logger.debug("[%s] jsonl write failed: %s", LOG_TAG, exc)


# ─── Inputs — sourced live (STEP 0 confirmed) ───────────────────────────
def _prior_daily_direction(symbol: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Return ('UP'|'DOWN'|'FLAT', debug) from the LAST CLOSED D1 candle.

    No lookahead: TimeframeContext._d1_closed only contains completed days
    (the in-progress day sits in _d1_partial and is NEVER read here).
    """
    dbg: Dict[str, Any] = {"source": "tf_ctx.D1"}
    try:
        import autobot as _ab
        tf = getattr(_ab, "_TF_CTX", None)
        if tf is None:
            dbg["err"] = "tf_ctx_none"
            return None, dbg
        d1_list = tf.get_closed_candles(str(symbol).upper(), "D1") or []
        dbg["n_d1"] = len(d1_list)
        if not d1_list:
            dbg["err"] = "no_d1_candles"
            return None, dbg
        last = d1_list[-1]
        o = float(last.get("open"))
        c = float(last.get("close"))
        dbg["d1_open"] = o
        dbg["d1_close"] = c
        dbg["d1_ts"] = str(last.get("timestamp") or last.get("time") or "")
        if c > o:
            return "UP", dbg
        if c < o:
            return "DOWN", dbg
        return "FLAT", dbg
    except Exception as exc:
        dbg["err"] = f"exc:{exc}"
        return None, dbg


# Public alias — other strategies (e.g. STRUCTURE_BREAK's daily-alignment
# filter, 2026-06-30) reuse this exact function so there is ONE
# no-lookahead daily-direction source for the fleet, not two.
prior_daily_direction = _prior_daily_direction


def _latest_regime(symbol: str) -> Tuple[Optional[str], Dict[str, Any]]:
    dbg: Dict[str, Any] = {"source": "regime_engine.latest_result"}
    try:
        import regime_engine as _re
        res = _re.latest_result(str(symbol).upper())
        if not res:
            dbg["err"] = "no_result"
            return None, dbg
        reg = str(res.get("winning_regime") or "")
        dbg["regime"] = reg
        dbg["confidence"] = res.get("confidence_final")
        dbg["bias"] = res.get("directional_bias")
        # label_path surfaces STRONG_TREND provenance: "hist" | "struct" |
        # "range" | "range_break_promote". Consumed by the intraday-flip
        # counter, which keys strictly on struct-path STRONG_TREND to trigger.
        dbg["label_path"] = res.get("regime_label_path")
        return reg, dbg
    except Exception as exc:
        dbg["err"] = f"exc:{exc}"
        return None, dbg


def _kaufman_er(closes: Sequence[float], n: int = 20) -> Optional[float]:
    """|net|/sum(|bar-to-bar|) over the last n bars. 1=pure trend, 0=chop.

    Mirrors regime_tree_shadow._efficiency_ratio (PROD path on every 5M close).
    """
    if closes is None or len(closes) < n + 1:
        return None
    w = list(closes[-(n + 1):])
    net = abs(w[-1] - w[0])
    path = sum(abs(w[i] - w[i - 1]) for i in range(1, len(w)))
    if path <= 0:
        return None
    return net / path


def _macd_hist_last_and_contracting(df_5m: Any) -> Tuple[Optional[float], Optional[bool]]:
    """Read MACD_HIST_35_45_30 from the enriched 5m frame. Returns (last, contracting_bool).

    contracting = |hist[-1]| < |hist[-2]| (magnitude shrinking).

    2026-07-27: delegates to runner_momentum.macd_hist_last_and_contracting
    (shared with the universal trade_manager check). Byte-identical — locked
    by tests/unit/test_runner_momentum.py.
    """
    from runner_momentum import macd_hist_last_and_contracting as _mh
    return _mh(df_5m, col="MACD_HIST_35_45_30")


def _adx_last(df_5m: Any) -> Optional[float]:
    try:
        if df_5m is None or "ADX_14" not in df_5m.columns or len(df_5m) < 1:
            return None
        v = float(df_5m["ADX_14"].iloc[-1])
        if math.isnan(v):
            return None
        return v
    except Exception:
        return None


def _atr_last(df_5m: Any) -> Optional[float]:
    try:
        if df_5m is None or "ATR_14" not in df_5m.columns or len(df_5m) < 1:
            return None
        v = float(df_5m["ATR_14"].iloc[-1])
        if math.isnan(v):
            return None
        return v
    except Exception:
        return None


# ─── Structural levels ──────────────────────────────────────────────────
def _h4_structural_target(symbol: str, direction: str, current_close: float,
                          lookback: int = H4_LOOKBACK_BARS,
                          ) -> Tuple[Optional[float], Dict[str, Any]]:
    """LONG: highest H4 high above current_close in last `lookback` bars.
    SHORT: lowest H4 low below current_close in last `lookback` bars.
    Returns (target_price, debug). target_price None when no qualifying level.
    """
    dbg: Dict[str, Any] = {"source": "h4_highs_lows", "lookback": lookback}
    try:
        import autobot as _ab
        tf = getattr(_ab, "_TF_CTX", None)
        if tf is None:
            dbg["err"] = "tf_ctx_none"
            return None, dbg
        h4 = tf.get_closed_candles(str(symbol).upper(), "H4") or []
        if not h4:
            dbg["err"] = "no_h4"
            return None, dbg
        window = h4[-lookback:]
        dbg["n"] = len(window)
        if direction == "LONG":
            highs = [float(c.get("high")) for c in window if c.get("high") is not None]
            cand = [h for h in highs if h > current_close]
            if not cand:
                dbg["err"] = "no_high_above"
                return None, dbg
            tgt = max(cand)
            dbg["picked"] = tgt
            return tgt, dbg
        else:
            lows = [float(c.get("low")) for c in window if c.get("low") is not None]
            cand = [l for l in lows if l < current_close]
            if not cand:
                dbg["err"] = "no_low_below"
                return None, dbg
            tgt = min(cand)
            dbg["picked"] = tgt
            return tgt, dbg
    except Exception as exc:
        dbg["err"] = f"exc:{exc}"
        return None, dbg


def _swing_5m(df_5m: Any) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
    """Return (last_swing_high, last_swing_low, debug) from market_structure.analyze
    on the closed 5m frame. NaNs/missing → (None, None)."""
    dbg: Dict[str, Any] = {"source": "market_structure.analyze"}
    try:
        import numpy as np
        import market_structure as _ms
        if df_5m is None or len(df_5m) < 30:
            dbg["err"] = "insufficient_5m"
            return None, None, dbg
        highs = df_5m["high"].to_numpy(dtype="float64")
        lows  = df_5m["low"].to_numpy(dtype="float64")
        closes = df_5m["close"].to_numpy(dtype="float64")
        snap = _ms.analyze(highs, lows, closes, asof=len(df_5m) - 1)
        sh = snap.last_swing_high.price if snap.last_swing_high else None
        sl = snap.last_swing_low.price  if snap.last_swing_low  else None
        dbg["swing_high"] = sh
        dbg["swing_low"]  = sl
        return sh, sl, dbg
    except Exception as exc:
        dbg["err"] = f"exc:{exc}"
        return None, None, dbg


def _resolve_target_and_sl(symbol: str, direction: str, entry_price: float,
                            df_5m: Any) -> Tuple[float, float, str, Dict[str, Any]]:
    """Resolve (target_price, sl_price, source_tag, debug).

    Target preference:
      1. H4 highest-high above (LONG) / lowest-low below (SHORT) — last 12 bars
      2. 5m last_swing_high above (LONG) / last_swing_low below (SHORT)
      3. ATR fallback: entry +/- TP_FALLBACK_ATR_MULT * ATR(14) (or fixed pips)
    SL preference:
      1. 5m last_swing_low - buffer (LONG) / last_swing_high + buffer (SHORT)
      2. Fixed SL_FALLBACK_PIPS
    Target is clamped to [MIN_TARGET_PIPS, MAX_TARGET_PIPS] distance.
    """
    dbg: Dict[str, Any] = {}
    # Target
    tgt, t_dbg = _h4_structural_target(symbol, direction, entry_price)
    dbg["h4"] = t_dbg
    target_source = "h4"
    sh, sl_swing, sw_dbg = _swing_5m(df_5m)
    dbg["swing5m"] = sw_dbg

    if tgt is None:
        if direction == "LONG" and sh is not None and sh > entry_price:
            tgt = sh
            target_source = "5m_swing_high"
        elif direction == "SHORT" and sl_swing is not None and sl_swing < entry_price:
            tgt = sl_swing
            target_source = "5m_swing_low"

    if tgt is None:
        atr = _atr_last(df_5m)
        if atr is not None and atr > 0:
            dist = TP_FALLBACK_ATR_MULT * (atr / PIP_SIZE)
        else:
            dist = TP_FALLBACK_PIPS
        tgt = entry_price + dist * PIP_SIZE if direction == "LONG" \
            else entry_price - dist * PIP_SIZE
        target_source = "atr_fallback"

    # Clamp target distance
    tgt_dist_pips = (tgt - entry_price) / PIP_SIZE if direction == "LONG" \
        else (entry_price - tgt) / PIP_SIZE
    if tgt_dist_pips < MIN_TARGET_PIPS:
        tgt = entry_price + MIN_TARGET_PIPS * PIP_SIZE if direction == "LONG" \
            else entry_price - MIN_TARGET_PIPS * PIP_SIZE
        dbg["tgt_clamp"] = "min"
    elif tgt_dist_pips > MAX_TARGET_PIPS:
        tgt = entry_price + MAX_TARGET_PIPS * PIP_SIZE if direction == "LONG" \
            else entry_price - MAX_TARGET_PIPS * PIP_SIZE
        dbg["tgt_clamp"] = "max"

    # SL
    sl_source = "fixed"
    if direction == "LONG" and sl_swing is not None and sl_swing < entry_price:
        sl_px = sl_swing - SL_BUFFER_PIPS * PIP_SIZE
        sl_source = "5m_swing_low"
    elif direction == "SHORT" and sh is not None and sh > entry_price:
        sl_px = sh + SL_BUFFER_PIPS * PIP_SIZE
        sl_source = "5m_swing_high"
    else:
        sl_px = entry_price - SL_FALLBACK_PIPS * PIP_SIZE if direction == "LONG" \
            else entry_price + SL_FALLBACK_PIPS * PIP_SIZE

    # 2026-07-15: MAX_SL_PIPS hard cap (default 12p, IG broker minimum).
    # Applied AFTER the structural resolution above; kill-switch via
    # TREND_V3_MAX_SL_PIPS=0 or empty (MAX_SL_PIPS resolves to 0.0).
    if MAX_SL_PIPS > 0:
        sl_dist_pips = (entry_price - sl_px) / PIP_SIZE if direction == "LONG" \
            else (sl_px - entry_price) / PIP_SIZE
        if sl_dist_pips > MAX_SL_PIPS:
            logger.info(
                "[%s] SL clamped structural=%.1fp -> %.0fp.",
                LOG_TAG, sl_dist_pips, MAX_SL_PIPS,
            )
            dbg["sl_clamp"] = {
                "from_pips": round(sl_dist_pips, 3),
                "to_pips":   round(MAX_SL_PIPS, 3),
                "orig_source": sl_source,
            }
            sl_px = entry_price - MAX_SL_PIPS * PIP_SIZE if direction == "LONG" \
                else entry_price + MAX_SL_PIPS * PIP_SIZE
            sl_source = f"{sl_source}_capped"

    dbg["target_source"] = target_source
    dbg["sl_source"]     = sl_source
    return tgt, sl_px, target_source, dbg


# ─── Open-position bookkeeping (per-mode in-memory) ─────────────────────
# Tracks entry conditions for the exit machine. Cleared on position close
# via _on_trade_close hook (best-effort — the exit machine also self-cleans
# when EPIC_STATE no longer has the position active).
@dataclass
class _OpenPos:
    epic: str
    pos_key: str
    direction: str               # "LONG" / "SHORT"
    entry_price: float
    entry_ts: datetime
    entry_er: float
    entry_regime: str
    target_price: float
    sl_price: float
    target_source: str
    # rolling exit-machine state
    best_extreme_close: float    # highest close seen so far (LONG) / lowest (SHORT)
    last_extreme_bar_ts: datetime
    bars_since_new_extreme: int
    # Fix 1 (2026-07-16): consecutive off-regime bar counter. Increments
    # on each monitor_exits tick where regime_now != STRONG_TREND_<dir>;
    # resets to 0 the moment the regime returns. REGIME_LEFT fires only
    # when this reaches REGIME_LEFT_PERSIST_BARS. Default 0 keeps old
    # behaviour byte-identical when kill-switch is set.
    bars_off_regime: int = 0
    # 2026-07-21 exhaustion-gated momentum check consumption flags.
    # Set True on HOLD; cleared when the event's re-arm condition trips
    # (new extreme for exh_check_held; regime returns for
    # regime_left_held). Only read when EXH_MOMENTUM_CHECK_ENABLED=1.
    exh_check_held: bool = False
    regime_left_held: bool = False


_OPEN_POS: Dict[str, _OpenPos] = {}   # keyed by pos_key
_OPEN_POS_LOCK = threading.Lock()

# Re-entry cooldown (Fix 3, 2026-07-16). Records the close_ts of every
# exit-machine-driven close, keyed by (epic, direction). evaluate() reads
# this to block immediate same-direction re-fire within
# REENTRY_COOLDOWN_BARS × 5m. Kill-switch: REENTRY_COOLDOWN_BARS=0 makes
# the check short-circuit (byte-identical to pre-fix behaviour).
REENTRY_COOLDOWN_BARS = _env_int("TREND_V3_REENTRY_COOLDOWN_BARS", 2)
_LAST_CLOSE_TS: Dict[Tuple[str, str], datetime] = {}
_LAST_CLOSE_TS_LOCK = threading.Lock()


def _m1_aligned(direction: str, macd_hist: Optional[float]) -> Optional[bool]:
    """M1 = sign(MACD-hist) aligned with trade direction.
    Returns True/False, or None if macd_hist is None (undecidable).
    LONG -> aligned when hist > 0; SHORT -> aligned when hist < 0.
    Zero counts as NOT aligned (no directional push).

    2026-07-27: delegates to runner_momentum.m1_aligned (shared with the
    universal trade_manager check). Byte-identical for LONG/SHORT inputs —
    locked by tests/unit/test_runner_momentum.py.
    """
    from runner_momentum import m1_aligned as _m1
    return _m1(direction, macd_hist)


def _record_close_for_cooldown(epic: str, direction: str, ts: datetime) -> None:
    """Called from monitor_exits after any exit-machine close. Populates
    the cooldown map even when REENTRY_COOLDOWN_BARS=0 so telemetry is
    consistent; the actual block is gated by the env value."""
    try:
        with _LAST_CLOSE_TS_LOCK:
            _LAST_CLOSE_TS[(epic, direction)] = ts
    except Exception:
        pass


def _cooldown_bars_remaining(epic: str, direction: str, now: datetime) -> Optional[int]:
    """Return the number of 5m bars still on cooldown, or None if the
    slot is free. When REENTRY_COOLDOWN_BARS <= 0 the check short-circuits
    and returns None (kill-switch)."""
    try:
        if REENTRY_COOLDOWN_BARS <= 0:
            return None
        with _LAST_CLOSE_TS_LOCK:
            last = _LAST_CLOSE_TS.get((epic, direction))
        if last is None:
            return None
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed_s = (now - last).total_seconds()
        remaining_s = (REENTRY_COOLDOWN_BARS * 300) - elapsed_s
        if remaining_s <= 0:
            return None
        return max(1, int(remaining_s // 300) + 1)
    except Exception:
        return None


# REGIME_LEFT persistence (Fix 1, 2026-07-16). Instead of a single-bar
# off-regime read tripping REGIME_LEFT immediately, require N consecutive
# off-regime bars in monitor_exits. Reset the streak the moment the
# regime returns. Kill-switch: PERSIST_BARS<=0 restores single-bar exit
# (byte-identical to pre-fix).
REGIME_LEFT_PERSIST_BARS = _env_int("TREND_V3_REGIME_LEFT_PERSIST_BARS", 2)

# Exhaustion-gated momentum check (2026-07-21). Instead of flattening on
# the exhaustion trigger (bars_since_new_extreme >= FLATTEN_BARS AND
# macd contracting) or on the persistent REGIME_LEFT trigger, first probe
# whether MACD-hist is still signed with the trade direction (M1). If
# aligned -> HOLD the runner and consume the event (re-arm only after a
# new extreme resets bars_since_new_extreme, or the regime returns for
# REGIME_LEFT). If against -> exit as before. Sim: +612p vs actual -98p
# across 34 fills (2026-07 audit). Kill switch: ENABLED=0 restores the
# current flatten-on-trigger behaviour byte-identical.
EXH_MOMENTUM_CHECK_ENABLED = _env_bool("EXH_MOMENTUM_CHECK_ENABLED", "1")
EXH_MOMENTUM_FLATTEN_BARS  = _env_int("EXH_MOMENTUM_FLATTEN_BARS", FLATTEN_BARS)


def _set_open_pos(pos: _OpenPos) -> None:
    with _OPEN_POS_LOCK:
        _OPEN_POS[pos.pos_key] = pos


def _get_open_pos(pos_key: str) -> Optional[_OpenPos]:
    with _OPEN_POS_LOCK:
        return _OPEN_POS.get(pos_key)


def _drop_open_pos(pos_key: str) -> None:
    with _OPEN_POS_LOCK:
        _OPEN_POS.pop(pos_key, None)


# ─── Strategy: ENTRY evaluate() ─────────────────────────────────────────
class GbpUsdTrendV3Strategy:
    _instance: Optional["GbpUsdTrendV3Strategy"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_eval_bar: Dict[str, datetime] = {}
        # Fix 3 (2026-07-16): per-(epic,direction) slot-occupancy latch.
        # evaluate() sees has_open_long / has_open_short from EPIC_STATE.
        # If a slot was occupied at t-1 and empty at t, someone else closed
        # the position (broker TP/SL, IG_RECONCILE, external) — the
        # exit-machine's own _record_close_for_cooldown never fired.
        # Synthesize a cooldown record so re-entry is gated the same way.
        self._prev_open: Dict[Tuple[str, str], bool] = {}
        # Intraday-flip state, per epic. Updated once per committed 5m close
        # from the same seam that owns _last_eval_bar dedup, so no intra-bar
        # flapping. Keys: opposing_count (int), revert_count (int),
        # flipped (bool). All start zeroed on first evaluation.
        self._flip_state: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def instance(cls) -> "GbpUsdTrendV3Strategy":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _update_flip_state(self, epic: str, spine_dir: str,
                            regime: Optional[str], label_path: Optional[str],
                            bar_ts: datetime) -> Tuple[str, bool]:
        """Advance the intraday-flip counters for `epic` on ONE committed 5m
        close. Returns (effective_dir, flipped_bool).

        - Trigger: struct-path STRONG_TREND opposing spine for N bars.
        - Revert: engine agreeing-with-spine or non-STRONG for N bars.
        - Anything not-strictly-opposing-struct-STRONG resets the opposing
          counter; anything not-agreeing-or-non-STRONG resets the revert
          counter. Hist-path STRONG_TREND does NOT count as opposing.
        - Never mutates the spine value passed in.

        Flag=0 short-circuits: counters cleared, spine returned unchanged.
        """
        st = self._flip_state.setdefault(epic, {
            "opposing_count": 0,
            "revert_count":   0,
            "flipped":        False,
        })
        if not INTRADAY_FLIP_ENABLED:
            st["opposing_count"] = 0
            st["revert_count"]   = 0
            st["flipped"]        = False
            return spine_dir, False

        reg = str(regime or "")
        path = str(label_path or "")
        is_struct_strong_up   = (reg == "STRONG_TREND_UP"   and path == "struct")
        is_struct_strong_down = (reg == "STRONG_TREND_DOWN" and path == "struct")
        struct_dir: Optional[str] = None
        if is_struct_strong_up:
            struct_dir = "UP"
        elif is_struct_strong_down:
            struct_dir = "DOWN"

        opposing = (struct_dir is not None and struct_dir != spine_dir)
        # For reversion: agreeing with spine, OR non-STRONG. Struct-path is
        # NOT required for agreement — any label matching the spine direction
        # is enough to pull the effective dir back to spine.
        agreeing_or_non_strong = (
            reg not in ("STRONG_TREND_UP", "STRONG_TREND_DOWN")
            or (reg == "STRONG_TREND_UP"   and spine_dir == "UP")
            or (reg == "STRONG_TREND_DOWN" and spine_dir == "DOWN")
        )

        if not st["flipped"]:
            if opposing:
                st["opposing_count"] += 1
                if st["opposing_count"] >= FLIP_CONFIRM_BARS:
                    st["flipped"] = True
                    st["revert_count"] = 0
                    effective = "DOWN" if spine_dir == "UP" else "UP"
                    logger.info(
                        "[%s] DIRECTION FLIP spine=%s -> effective=%s after "
                        "%d bars struct STRONG_TREND_%s bar_ts=%s",
                        LOG_TAG, spine_dir, effective,
                        FLIP_CONFIRM_BARS, effective, bar_ts.isoformat(),
                    )
                    _write_jsonl({
                        "event":     "flip",
                        "ts":        bar_ts.isoformat(),
                        "epic":      epic,
                        "spine":     spine_dir,
                        "effective": effective,
                        "bars":      int(FLIP_CONFIRM_BARS),
                        "regime":    reg,
                        "label_path": path,
                    })
            else:
                st["opposing_count"] = 0
        else:
            if agreeing_or_non_strong:
                st["revert_count"] += 1
                if st["revert_count"] >= FLIP_CONFIRM_BARS:
                    st["flipped"] = False
                    st["opposing_count"] = 0
                    logger.info(
                        "[%s] DIRECTION REVERT effective=%s -> spine=%s "
                        "after %d bars agreeing_or_non_strong regime=%s "
                        "bar_ts=%s",
                        LOG_TAG,
                        ("DOWN" if spine_dir == "UP" else "UP"),
                        spine_dir, FLIP_CONFIRM_BARS, reg, bar_ts.isoformat(),
                    )
                    _write_jsonl({
                        "event":     "revert",
                        "ts":        bar_ts.isoformat(),
                        "epic":      epic,
                        "spine":     spine_dir,
                        "effective": spine_dir,
                        "bars":      int(FLIP_CONFIRM_BARS),
                        "regime":    reg,
                        "label_path": path,
                    })
            else:
                st["revert_count"] = 0

        if st["flipped"]:
            effective = "DOWN" if spine_dir == "UP" else "UP"
            return effective, True
        return spine_dir, False

    def _in_session(self, ts_utc: datetime) -> bool:
        """Session-window gate for ENTRIES. Mirrors gbpusd_bb_bounce._in_window
        (weekend skip + [START, END) time compare) — same mechanism, HH:MM
        env format. Not called from monitor_exits(); exits/management of an
        open position are untouched."""
        ts = ts_utc.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return SESSION_START <= t < SESSION_END

    def evaluate(self,
                 symbol: str,
                 epic: str,
                 ts: datetime,
                 bars: Sequence[Bar],
                 closes_ind: Sequence[float],
                 df_5m: Any,
                 has_open_long: bool = False,
                 has_open_short: bool = False,
                 ) -> Optional["StrategyDecision"]:
        """Return a StrategyDecision when all entry gates hold; None otherwise.

        df_5m is the enriched 5m frame (has ADX_14, MACD_HIST_35_45_30, ATR_14, etc).
        bars / closes_ind are passed for parity with the rest of the fleet; the
        decision reads from df_5m for indicator values, bars[-1] for last price.
        """
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if not bars or len(bars) < 2:
            return None

        # 2026-07-21: session gate (entries only; monitor_exits unaffected).
        if SESSION_GATE_ENABLED and not self._in_session(ts):
            logger.info(
                "[TV3_SESSION] suppressed entry at %s",
                ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            return None

        # Dedup per epic per bar
        with self._lock:
            last_seen = self._last_eval_bar.get(epic)
            if last_seen is not None and bars[-1].timestamp <= last_seen:
                return None
            self._last_eval_bar[epic] = bars[-1].timestamp

        cur = bars[-1]
        current_close = float(cur.close)

        # ── Slot-occupancy latch (Fix 3, 2026-07-16) ──
        # If a slot was active last tick and is empty now, someone else
        # closed the position (broker TP/SL, IG_RECONCILE, external).
        # Synthesize a cooldown record so re-entry is gated the same way
        # exit-machine closes are.
        try:
            for _dir, _occ_now in (("LONG", has_open_long), ("SHORT", has_open_short)):
                _key = (epic, _dir)
                _occ_prev = self._prev_open.get(_key, False)
                if _occ_prev and not _occ_now:
                    # Only record if the exit machine hasn't already logged
                    # this close on this bar (both would use cur.timestamp).
                    with _LAST_CLOSE_TS_LOCK:
                        _existing = _LAST_CLOSE_TS.get(_key)
                    if _existing is None or _existing < cur.timestamp:
                        _record_close_for_cooldown(epic, _dir, cur.timestamp)
                self._prev_open[_key] = _occ_now
        except Exception:
            pass

        # ── Daily spine ──
        daily_dir, daily_dbg = _prior_daily_direction(symbol)
        if daily_dir not in ("UP", "DOWN"):
            self._log_block("daily_unavailable_or_flat", daily=daily_dbg,
                            bar_ts=cur.timestamp)
            return None

        # ── Regime read (needed here for the intraday-flip counter) ──
        regime, reg_dbg = _latest_regime(symbol)

        # ── Intraday direction flip ──
        # Runs once per committed 5m close (this seam is past the
        # _last_eval_bar dedup). Reads engine label + label_path from
        # regime_engine.latest_result; advances opposing / revert counters;
        # returns the effective direction TREND_V3 evaluates on THIS bar.
        # The spine value (daily_dir) is NEVER mutated — SB and
        # trend_stretch_brake continue reading raw spine.
        effective_dir, is_flipped = self._update_flip_state(
            epic, daily_dir, regime, reg_dbg.get("label_path"), cur.timestamp,
        )
        direction_source = "intraday_flip" if is_flipped else "spine"

        # ── Regime gate ──
        # Under REGIME_MATRIX_ENABLED=1 the effective_regime → permitted-set
        # decision is owned by regime_matrix; the strict-STRONG_TREND check
        # here is bypassed. Slot / direction assignment is unaffected.
        if effective_dir == "UP":
            if regime != "STRONG_TREND_UP" and not _REGIME_MATRIX_ENABLED:
                self._log_block("regime_not_strong_up", daily=daily_dbg,
                                regime_dbg=reg_dbg, bar_ts=cur.timestamp,
                                direction_source=direction_source,
                                spine=daily_dir, effective=effective_dir)
                return None
            direction = "LONG"
            signal = "BUY"
            mode = MODE_NAME_LONG
            if has_open_long:
                self._log_block("slot_taken_long", bar_ts=cur.timestamp)
                return None
        else:  # DOWN
            if regime != "STRONG_TREND_DOWN" and not _REGIME_MATRIX_ENABLED:
                self._log_block("regime_not_strong_down", daily=daily_dbg,
                                regime_dbg=reg_dbg, bar_ts=cur.timestamp,
                                direction_source=direction_source,
                                spine=daily_dir, effective=effective_dir)
                return None
            direction = "SHORT"
            signal = "SELL"
            mode = MODE_NAME_SHORT
            if has_open_short:
                self._log_block("slot_taken_short", bar_ts=cur.timestamp)
                return None

        # ── Re-entry cooldown (Fix 3, 2026-07-16) ──
        # Block same-direction re-fire for REENTRY_COOLDOWN_BARS × 5m
        # after any exit-machine close. Kill-switch: env=0 short-circuits.
        _cd_remain = _cooldown_bars_remaining(epic, direction, cur.timestamp)
        if _cd_remain is not None:
            self._log_block("reentry_cooldown",
                            direction=direction,
                            cooldown_bars=REENTRY_COOLDOWN_BARS,
                            remaining_bars=_cd_remain,
                            bar_ts=cur.timestamp)
            return None

        # ── ADX gate ──
        adx = _adx_last(df_5m)
        if adx is None or adx < ADX_MIN:
            self._log_block("adx_below_min", adx=adx, adx_min=ADX_MIN,
                            bar_ts=cur.timestamp, direction=direction)
            return None

        # ── ER gate ──
        er = _kaufman_er(closes_ind, ER_BARS)
        if er is None or er < ER_MIN:
            self._log_block("er_below_min", er=er, er_min=ER_MIN,
                            bar_ts=cur.timestamp, direction=direction)
            return None

        # ── RANGE GATE (2026-06-30, LIVE) ──────────────────────────────
        # Belt-and-suspenders. TREND_V3 already requires STRONG_TREND_*
        # + ADX>=ADX_MIN + ER>=ER_MIN (default 0.5), so in a low-ER range
        # (ER<=0.35) it cannot fire by construction — making this gate
        # nominally redundant. Wired anyway for symmetry with SB and
        # EMA_PULLBACK: any future relaxation of TREND_V3's ER floor
        # leaves the range-gate suppression in place automatically.
        # Direction-agnostic. Fail-open.
        _range_rec: Optional[Dict[str, Any]] = None
        try:
            from guards.range_gate import evaluate as _range_gate
            _r_blocked, _r_reason, _range_rec = _range_gate(
                strategy="TREND_V3",
                mode=mode,
                direction=direction,
                bars=bars,
                last_price=float(current_close),
                pip_size=PIP_SIZE,
                symbol=symbol,
                ts_utc=ts,
            )
            if _r_blocked:
                self._log_block("range_gate_suppress",
                                reason_msg=_r_reason,
                                bar_ts=cur.timestamp,
                                direction=direction)
                return None
        except Exception as _range_exc:
            logger.warning(
                "[%s] range_gate raised (fail-open): %s",
                LOG_TAG, _range_exc,
            )
            _range_rec = {"fail_open": True, "compute_error": str(_range_exc)}

        # ── Target + SL ──
        target_px, sl_px, target_source, tdbg = _resolve_target_and_sl(
            symbol, direction, current_close, df_5m,
        )
        tp_pips = (target_px - current_close) / PIP_SIZE if direction == "LONG" \
            else (current_close - target_px) / PIP_SIZE
        sl_pips = (current_close - sl_px) / PIP_SIZE if direction == "LONG" \
            else (sl_px - current_close) / PIP_SIZE
        if tp_pips <= 0 or sl_pips <= 0:
            self._log_block("non_positive_tp_or_sl", tp=tp_pips, sl=sl_pips,
                            bar_ts=cur.timestamp, direction=direction)
            return None

        # ── Build decision ──
        from strategy_logic import StrategyDecision
        debug = {
            "strategy": "TREND_V3",
            "direction": direction,
            "daily_dir": daily_dir,
            "daily_dbg": daily_dbg,
            "effective_dir":    effective_dir,
            "direction_source": direction_source,
            "regime": regime,
            "regime_dbg": reg_dbg,
            "adx": adx,
            "er": er,
            "target_price": float(target_px),
            "target_source": target_source,
            "target_dbg": tdbg,
            "sl_price": float(sl_px),
            "tp_pips": float(tp_pips),
            "sl_pips": float(sl_pips),
            "entry_price": float(current_close),
            "bar_ts": cur.timestamp.isoformat(),
            "range_gate": (
                dict(_range_rec) if isinstance(_range_rec, dict) else None
            ),
        }
        reason = (
            f"TREND_V3 {direction} daily={daily_dir} effective={effective_dir} "
            f"src={direction_source} regime={regime} "
            f"ADX={adx:.1f}>={ADX_MIN:.1f} ER={er:.2f}>={ER_MIN:.2f} "
            f"target={target_source}({target_px:.2f}) sl={sl_pips:.0f}p tp={tp_pips:.0f}p"
        )
        decision = StrategyDecision(
            symbol=str(symbol).upper(),
            regime=regime,
            signal=signal,
            mode=mode,
            entry=float(current_close),
            sl=float(sl_pips),       # pips distance (fleet convention)
            tp=float(tp_pips),       # pips distance (fleet convention)
            use_trailing_stop=False,
            reason=reason,
            debug=debug,
            size=None,               # inherit TRADE_SIZE from .env (full fleet size)
            pip_size=PIP_SIZE,
        )

        # Record the fire for the exit machine; the autobot dispatch
        # confirms execution and registers _OPEN_POS via on_open().
        logger.info("[%s] FIRE %s | %s", LOG_TAG, direction, reason)
        _write_jsonl({
            "event":         "fire",
            "ts":            cur.timestamp.isoformat(),
            "symbol":        str(symbol).upper(),
            "epic":          epic,
            "direction":     direction,
            "daily_dir":     daily_dir,
            "effective_dir": effective_dir,
            "direction_source": direction_source,
            "regime":        regime,
            "adx":           adx,
            "er":            er,
            "entry_price":   float(current_close),
            "target_price":  float(target_px),
            "target_source": target_source,
            "sl_price":      float(sl_px),
            "tp_pips":       float(tp_pips),
            "sl_pips":       float(sl_pips),
        })
        return decision

    def _log_block(self, reason: str, **kw) -> None:
        rec = {"event": "block", "reason": reason}
        rec.update({k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in kw.items()})
        _write_jsonl(rec)


# ─── Open / exit hooks ─────────────────────────────────────────────────
def on_open(epic: str, pos_key: str, decision_debug: Dict[str, Any],
            confirmed_entry: Optional[float], bar_ts: datetime) -> None:
    """Called by autobot dispatch after a successful execute_trade. Records
    the open-position state needed by the exit machine."""
    try:
        dbg = decision_debug or {}
        direction = str(dbg.get("direction") or "")
        entry_px = float(confirmed_entry if confirmed_entry is not None else
                         dbg.get("entry_price") or 0.0)
        if direction not in ("LONG", "SHORT") or entry_px <= 0:
            return
        pos = _OpenPos(
            epic=epic,
            pos_key=pos_key,
            direction=direction,
            entry_price=entry_px,
            entry_ts=bar_ts,
            entry_er=float(dbg.get("er") or 0.0),
            entry_regime=str(dbg.get("regime") or ""),
            target_price=float(dbg.get("target_price") or 0.0),
            sl_price=float(dbg.get("sl_price") or 0.0),
            target_source=str(dbg.get("target_source") or ""),
            best_extreme_close=entry_px,
            last_extreme_bar_ts=bar_ts,
            bars_since_new_extreme=0,
        )
        _set_open_pos(pos)
        _write_jsonl({
            "event":        "open",
            "ts":           bar_ts.isoformat(),
            "epic":         epic,
            "pos_key":      pos_key,
            "direction":    direction,
            "entry_price":  entry_px,
            "entry_er":     pos.entry_er,
            "regime":       pos.entry_regime,
            "target_price": pos.target_price,
            "sl_price":     pos.sl_price,
        })
    except Exception as exc:
        logger.warning("[%s] on_open raised: %s", LOG_TAG, exc)


def on_trade_close(pos_key: str) -> None:
    """Best-effort cleanup. The exit machine also self-cleans when EPIC_STATE
    flips inactive — this is just the prompt path on close-callback."""
    try:
        _drop_open_pos(pos_key)
    except Exception:
        pass


# ─── Exit machine — called on every 5M close per active position ───────
def monitor_exits(symbol: str, epic: str, ts: datetime,
                  bars: Sequence[Bar], closes_ind: Sequence[float],
                  df_5m: Any) -> Optional[Dict[str, Any]]:
    """Inspect open TREND_V3 positions for `epic`. Close any that meet:
      1) Flatten/exhaustion: bars_since_new_extreme >= FLATTEN_BARS
         AND (current ER < entry_ER OR MACD_HIST contracting)
      2) Structural break: close past entry-side level the other way
      3) Regime leaves STRONG_TREND family
    Returns the close dict (or None if nothing closed). Best-effort; never
    raises into the callback.
    """
    if not ENABLED or str(symbol).upper() != "GBPUSD":
        return None
    try:
        from trade_executor import EPIC_STATE, close_position, _pos_key
        results: List[Dict[str, Any]] = []
        # Inspect both modes
        for mode in (MODE_NAME_LONG, MODE_NAME_SHORT):
            pk = _pos_key(epic, mode)
            st = EPIC_STATE.get(pk)
            if not st or not st.get("active"):
                # Position not active — clean any stale state
                if _get_open_pos(pk) is not None:
                    _drop_open_pos(pk)
                continue
            pos = _get_open_pos(pk)
            if pos is None:
                # We didn't record open state for this position — likely
                # opened pre-restart. Skip: the safety time-stop will catch.
                continue
            close_now = float(bars[-1].close) if bars else None
            if close_now is None:
                continue

            # Update best-extreme + bars_since_new_extreme.
            # 2026-07-21: clearing exh_check_held on a new extreme is the
            # "re-arm" that lets the exhaustion-gated momentum check fire
            # again on the next 6-bar plateau.
            if pos.direction == "LONG":
                if close_now > pos.best_extreme_close:
                    pos.best_extreme_close = close_now
                    pos.last_extreme_bar_ts = ts
                    pos.bars_since_new_extreme = 0
                    pos.exh_check_held = False
                else:
                    pos.bars_since_new_extreme += 1
            else:  # SHORT
                if close_now < pos.best_extreme_close:
                    pos.best_extreme_close = close_now
                    pos.last_extreme_bar_ts = ts
                    pos.bars_since_new_extreme = 0
                    pos.exh_check_held = False
                else:
                    pos.bars_since_new_extreme += 1

            # Current momentum signals
            er_now = _kaufman_er(closes_ind, ER_BARS)
            macd_last, macd_contracting = _macd_hist_last_and_contracting(df_5m)
            regime_now, _ = _latest_regime(symbol)

            momentum_fade = False
            momentum_dbg: Dict[str, Any] = {}
            if er_now is not None:
                if er_now < pos.entry_er:
                    momentum_fade = True
                momentum_dbg["er_now"] = er_now
                momentum_dbg["entry_er"] = pos.entry_er
            if macd_contracting:
                momentum_fade = True
            momentum_dbg["macd_last"] = macd_last
            momentum_dbg["macd_contracting"] = macd_contracting

            close_reason: Optional[str] = None
            # (1) Flatten + momentum fade
            # 2026-07-21: exhaustion-gated momentum check. When
            # EXH_MOMENTUM_CHECK_ENABLED=1 (default) the raw trigger no
            # longer flattens; instead M1 (sign of MACD-hist) decides
            # HOLD vs EXIT. HOLD sets exh_check_held; the next event fires
            # only after a new extreme resets bars_since_new_extreme
            # (handled at the extreme update above). Kill-switch OFF
            # restores the previous unconditional flatten.
            if (
                pos.bars_since_new_extreme >= EXH_MOMENTUM_FLATTEN_BARS
                and momentum_fade
            ):
                if not EXH_MOMENTUM_CHECK_ENABLED:
                    close_reason = "FLATTEN_EXHAUSTION"
                elif not pos.exh_check_held:
                    _m1 = _m1_aligned(pos.direction, macd_last)
                    _deal_id = st.get("dealId") or st.get("deal_id") or pk
                    if _m1 is True:
                        logger.info(
                            "[EXH_MCHECK] HOLD deal=%s mode=%s hist=%s dir=%s bars_since_extreme=%d",
                            _deal_id, mode, macd_last, pos.direction,
                            pos.bars_since_new_extreme,
                        )
                        _write_jsonl({
                            "event":     "exh_mcheck",
                            "decision":  "HOLD",
                            "trigger":   "FLATTEN_EXHAUSTION",
                            "ts":        ts.isoformat(),
                            "epic":      epic,
                            "pos_key":   pk,
                            "deal_id":   str(_deal_id),
                            "direction": pos.direction,
                            "mode":      mode,
                            "macd_last": macd_last,
                            "bars_since_extreme": pos.bars_since_new_extreme,
                            "close":     close_now,
                        })
                        pos.exh_check_held = True
                    else:
                        logger.info(
                            "[EXH_MCHECK] EXIT deal=%s mode=%s hist=%s dir=%s bars_since_extreme=%d",
                            _deal_id, mode, macd_last, pos.direction,
                            pos.bars_since_new_extreme,
                        )
                        _write_jsonl({
                            "event":     "exh_mcheck",
                            "decision":  "EXIT",
                            "trigger":   "FLATTEN_EXHAUSTION",
                            "ts":        ts.isoformat(),
                            "epic":      epic,
                            "pos_key":   pk,
                            "deal_id":   str(_deal_id),
                            "direction": pos.direction,
                            "mode":      mode,
                            "macd_last": macd_last,
                            "bars_since_extreme": pos.bars_since_new_extreme,
                            "close":     close_now,
                        })
                        close_reason = "FLATTEN_EXHAUSTION"
            # (2) Structural backstop — close past sl_price the other way
            #     (entry-side reversal: LONG close < sl_price → already SL-side;
            #      we want close past the OPPOSITE structural — which for a LONG
            #      means below entry's swing-low; SL is broker-side so this is
            #      belt-and-braces). Use sl_price as the structural floor.
            if close_reason is None:
                if pos.direction == "LONG" and close_now < pos.sl_price:
                    close_reason = "STRUCTURAL_BREAK"
                elif pos.direction == "SHORT" and close_now > pos.sl_price:
                    close_reason = "STRUCTURAL_BREAK"
            # (3) Regime leaves STRONG_TREND family
            # Fix 1 (2026-07-16): require REGIME_LEFT_PERSIST_BARS
            # consecutive off-regime bars before closing. Streak resets
            # the moment the regime returns. PERSIST<=0 restores the
            # single-bar exit (byte-identical to pre-fix).
            if close_reason is None and regime_now is not None:
                _off = False
                if pos.direction == "LONG" and regime_now != "STRONG_TREND_UP":
                    _off = True
                elif pos.direction == "SHORT" and regime_now != "STRONG_TREND_DOWN":
                    _off = True

                if _off:
                    pos.bars_off_regime += 1
                    if REGIME_LEFT_PERSIST_BARS <= 0 \
                            or pos.bars_off_regime >= REGIME_LEFT_PERSIST_BARS:
                        # 2026-07-21: gate REGIME_LEFT with the same M1
                        # check as FLATTEN_EXHAUSTION. Aligned MACD-hist
                        # -> HOLD (regime_left_held consumed until regime
                        # returns); against -> exit as before.
                        if not EXH_MOMENTUM_CHECK_ENABLED:
                            close_reason = "REGIME_LEFT"
                        elif not pos.regime_left_held:
                            _m1 = _m1_aligned(pos.direction, macd_last)
                            _deal_id = st.get("dealId") or st.get("deal_id") or pk
                            if _m1 is True:
                                logger.info(
                                    "[EXH_MCHECK] HOLD deal=%s mode=%s hist=%s dir=%s bars_since_extreme=%d",
                                    _deal_id, mode, macd_last, pos.direction,
                                    pos.bars_since_new_extreme,
                                )
                                _write_jsonl({
                                    "event":     "exh_mcheck",
                                    "decision":  "HOLD",
                                    "trigger":   "REGIME_LEFT",
                                    "ts":        ts.isoformat(),
                                    "epic":      epic,
                                    "pos_key":   pk,
                                    "deal_id":   str(_deal_id),
                                    "direction": pos.direction,
                                    "mode":      mode,
                                    "macd_last": macd_last,
                                    "bars_since_extreme": pos.bars_since_new_extreme,
                                    "bars_off_regime": pos.bars_off_regime,
                                    "regime_now": regime_now,
                                    "close":     close_now,
                                })
                                pos.regime_left_held = True
                            else:
                                logger.info(
                                    "[EXH_MCHECK] EXIT deal=%s mode=%s hist=%s dir=%s bars_since_extreme=%d",
                                    _deal_id, mode, macd_last, pos.direction,
                                    pos.bars_since_new_extreme,
                                )
                                _write_jsonl({
                                    "event":     "exh_mcheck",
                                    "decision":  "EXIT",
                                    "trigger":   "REGIME_LEFT",
                                    "ts":        ts.isoformat(),
                                    "epic":      epic,
                                    "pos_key":   pk,
                                    "deal_id":   str(_deal_id),
                                    "direction": pos.direction,
                                    "mode":      mode,
                                    "macd_last": macd_last,
                                    "bars_since_extreme": pos.bars_since_new_extreme,
                                    "bars_off_regime": pos.bars_off_regime,
                                    "regime_now": regime_now,
                                    "close":     close_now,
                                })
                                close_reason = "REGIME_LEFT"
                    else:
                        # Telemetry: streak advanced but not yet at threshold.
                        _write_jsonl({
                            "event":     "regime_off_streak",
                            "ts":        ts.isoformat(),
                            "epic":      epic,
                            "pos_key":   pk,
                            "direction": pos.direction,
                            "regime_now": regime_now,
                            "streak":    pos.bars_off_regime,
                            "threshold": REGIME_LEFT_PERSIST_BARS,
                        })
                else:
                    if pos.bars_off_regime > 0:
                        _write_jsonl({
                            "event":     "regime_off_streak_reset",
                            "ts":        ts.isoformat(),
                            "epic":      epic,
                            "pos_key":   pk,
                            "direction": pos.direction,
                            "regime_now": regime_now,
                            "streak_was": pos.bars_off_regime,
                        })
                    pos.bars_off_regime = 0
                    # 2026-07-21: regime returned; re-arm the M1 gate so
                    # a future REGIME_LEFT trigger can fire again.
                    pos.regime_left_held = False

            if close_reason is not None:
                logger.info(
                    "[%s] EXIT %s rule=%s bars_no_ext=%d er_now=%s macd_contract=%s regime=%s",
                    LOG_TAG, pos.direction, close_reason,
                    pos.bars_since_new_extreme, er_now, macd_contracting, regime_now,
                )
                _write_jsonl({
                    "event":     "exit",
                    "ts":        ts.isoformat(),
                    "epic":      epic,
                    "pos_key":   pk,
                    "direction": pos.direction,
                    "rule":      close_reason,
                    "bars_no_ext": pos.bars_since_new_extreme,
                    "entry_er":  pos.entry_er,
                    "er_now":    er_now,
                    "macd_last": macd_last,
                    "macd_contracting": macd_contracting,
                    "regime_now": regime_now,
                    "close":     close_now,
                    "best_extreme": pos.best_extreme_close,
                })
                try:
                    close_position(epic="", pos_key=pk, reason=f"TREND_V3_{close_reason}",
                                   exit_hint_price=close_now)
                except Exception as ce:
                    logger.warning("[%s] close_position raised: %s", LOG_TAG, ce)
                # Fix 3 (2026-07-16): record close_ts for re-entry cooldown.
                # Always populated (even when the cooldown is off) so a
                # subsequent env flip picks up state without a restart.
                _record_close_for_cooldown(epic, pos.direction, ts)
                _drop_open_pos(pk)
                results.append({"pos_key": pk, "rule": close_reason})
        return results[0] if results else None
    except Exception as exc:
        logger.warning("[%s] monitor_exits raised: %s", LOG_TAG, exc)
        return None


# ─── Module-level singleton + dispatch helpers ─────────────────────────
strategy = GbpUsdTrendV3Strategy.instance()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)


def startup_banner() -> str:
    return (
        f"[AUTOBOT] {LOG_TAG} ENABLED={ENABLED} "
        f"ADX_MIN={ADX_MIN} ER_MIN={ER_MIN} ER_BARS={ER_BARS} "
        f"FLATTEN_BARS={FLATTEN_BARS} SAFETY_MAX_HOLD_MIN={SAFETY_MAX_HOLD_MIN} "
        f"INTRADAY_FLIP={'ON' if INTRADAY_FLIP_ENABLED else 'OFF'}"
        f"(N={FLIP_CONFIRM_BARS}) "
        f"REENTRY_COOLDOWN_BARS={REENTRY_COOLDOWN_BARS} "
        f"REGIME_LEFT_PERSIST_BARS={REGIME_LEFT_PERSIST_BARS} "
        f"EXH_MOMENTUM_CHECK={'ON' if EXH_MOMENTUM_CHECK_ENABLED else 'OFF'}"
        f"(N={EXH_MOMENTUM_FLATTEN_BARS}) "
        f"jsonl={JSONL_PATH}"
    )
