# =========================
# FILE: strategy_logic.py
# =========================
# (UPDATED: expects enriched candles from candle_builder, but allows soft indicator fallback when required columns are missing)
#
# Sweep philosophy (critical):
# - Sweep DETECTOR always runs first (observe/arm/watch end-of-run reversals).
# - Sweep ENTRY is only allowed at trigger time if an exhaustion filter passes.
# - Sweep state must NOT starve EMA pullback / range routing unless a trade is actually taken.
#
# FIXES INCLUDED (requested):
# 1) ✅ SWEEP WINDOWS robustness:
#    - If SWEEP_WINDOWS_LONDON is "0"/"1"/garbage or parses empty, we fall back safely (never silently disables sweeps).
#    - If london_dt is None or windows list empty, we FAIL SAFE (allow sweeps).
# 2) ✅ RANGE now includes true intra-Bollinger touch/reject entries (inside-band touch playbook).
# 3) ✅ “Obvious sweep” capture improvement:
#    - V-sweep “new extreme + reclaim” handled via FAST_RECLAIM.
#    - Exhaustion bypass for fast-reclaim-tagged sweep signals is hardened:
#      reads from decision.reason/debug (not fragile internal state), but also checks state as fallback.
# 4) ✅ SAME-CANDLE pierce+reclaim fast path can jump directly from idle -> Stage 2
#    when a clear sweep/reclaim happens in one closed candle.
#
# CONTRACTS GUARDED:
# - No price normalization (#24/#104)
# - StrategyDecision.sl/tp are pip distances (#106)
# - No extra candle demands; only requires indicator presence (#97)

from __future__ import annotations

import os
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Tuple

import numpy as np
import pandas as pd

import morning_briefing
from indicators import add_indicators, IndicatorsConfig
from signal_logger import _session_from_utc_hour
from exception_monitor import record_exception

# ── Per-strategy concurrent open-position cap (2026-04-30) ─────────────────
# Replaces the per-pair session entry cap. Cap is read fresh from live
# position state (trade_executor.EPIC_STATE) on every dispatch. When a
# position closes, the slot frees immediately on the next dispatch — no
# cumulative counter, no rehydration concern.

# Strategies with cap = CONCURRENT_CAP_REVERSAL_DEFAULT (default 2).
REVERSAL_STRATEGIES = {"BB_REVERSAL", "BB_BOUNCE"}

# Strategies with no cap. Event-driven by design — a HIGH-impact day can
# legitimately produce 3+ events in one session, and the strategy itself
# decides when to fire.
EXEMPT_STRATEGIES = {"NEWS_TICK", "NEWS_STRATEGY"}


def _router_manages(strategy_name: str, sym: str) -> bool:
    """True iff `strategy_name` is currently dispatched by regime_router_engine
    for `sym` — meaning the cascade block in evaluate_signals() should SKIP to
    avoid a double-fire. Kill-switch: REGIME_ROUTER_ENGINE_ENABLED=0 → always
    False (cascade resumes normal flow with no code revert).
    """
    if str(os.getenv("REGIME_ROUTER_ENGINE_ENABLED", "0")).strip().lower() not in (
        "1", "true", "yes",
    ):
        return False
    managed = os.getenv("REGIME_ROUTER_MANAGED_STRATEGIES", "BB_REVERSAL,EMA_PULLBACK")
    managed_set = {s.strip().upper() for s in str(managed).split(",") if s.strip()}
    return str(strategy_name).strip().upper() in managed_set


def _strategy_family(pos_key_mode: str) -> str:
    """Canonicalise a mode string (raw decision.mode OR an EPIC_STATE
    pos_key suffix) to a strategy-family name.

    BB_REVERSAL pyramid legs are stored with timestamp-suffixed keys
    (e.g. ``BB_REVERSAL_1714410123456``) — these still belong to the
    BB_REVERSAL family for cap purposes.

    Direction-suffixed modes (``GBPUSD_BB_BOUNCE_L`` / ``_S``,
    ``GBPUSD_TREND_L`` / ``_S``, ``GBPUSD_RAW_REVERSAL_L`` / ``_S``)
    are collapsed to a single family — both directions share the cap.
    """
    if not pos_key_mode:
        return ""
    m = str(pos_key_mode).upper()
    if m == "BB_REVERSAL" or m.startswith("BB_REVERSAL_"):
        return "BB_REVERSAL"
    if m in ("GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S"):
        return "BB_BOUNCE"
    if m in ("GBPUSD_TREND_L", "GBPUSD_TREND_S"):
        return "GBPUSD_TREND"
    if m in ("GBPUSD_RAW_REVERSAL_L", "GBPUSD_RAW_REVERSAL_S"):
        return "GBPUSD_RAW_REVERSAL"
    return m


def _resolve_concurrent_cap(strategy_name: str) -> Optional[int]:
    """Return the open-position cap for ``strategy_name`` or None for
    exempt strategies.

    Resolution order:
      1. EXEMPT_STRATEGIES → None (no cap)
      2. ``CONCURRENT_CAP_<STRATEGY>`` env override
      3. ``CONCURRENT_CAP_REVERSAL_DEFAULT`` (default 2) for REVERSAL_STRATEGIES
      4. ``CONCURRENT_CAP_DEFAULT`` (default 1) for everything else
    """
    if strategy_name in EXEMPT_STRATEGIES:
        return None
    override = os.getenv(f"CONCURRENT_CAP_{strategy_name}")
    if override is not None and override.strip():
        try:
            return int(override)
        except (TypeError, ValueError):
            pass
    if strategy_name in REVERSAL_STRATEGIES:
        try:
            return int(os.getenv("CONCURRENT_CAP_REVERSAL_DEFAULT", "2"))
        except (TypeError, ValueError):
            return 2
    try:
        return int(os.getenv("CONCURRENT_CAP_DEFAULT", "1"))
    except (TypeError, ValueError):
        return 1


def _count_open_positions(epic: str, strategy_name: str) -> int:
    """Count open (or pending-open) positions on ``epic`` whose
    pos_key mode canonicalises to ``strategy_name``.

    Reads from ``trade_executor.EPIC_STATE``.
    BB_REVERSAL pyramid legs are counted separately (each has its own
    EPIC_STATE entry with a timestamp-suffixed pos_key).
    """
    try:
        from trade_executor import EPIC_STATE, _mode_from_pos_key
    except Exception:
        return 0
    epic_s = str(epic).strip()
    prefix = epic_s + "|"
    n = 0
    for pk, st in list(EPIC_STATE.items()):
        if not isinstance(pk, str) or not pk.startswith(prefix):
            continue
        if not (st.get("active") or st.get("pending_open")):
            continue
        try:
            mode_raw = _mode_from_pos_key(pk)
        except Exception:
            mode_raw = pk.split("|", 1)[-1] if "|" in pk else pk
        if _strategy_family(mode_raw) == strategy_name:
            n += 1
    return n


logger = logging.getLogger("AutoBot")


def _warn_deprecated_dispatcher_envs() -> None:
    """One-shot WARNING at module load if any deprecated dispatcher env
    var is set. Caller should remove from .env after verification.

    Deprecated 2026-04-30 by feat/dispatcher-decoupling:
      - MAX_ENTRIES_PER_PAIR_PER_SESSION  (replaced by CONCURRENT_CAP_*)
      - {PAIR}_MAX_ENTRIES                (replaced by CONCURRENT_CAP_*)
      - MIN_RR_THRESHOLD                  (R:R is strategy-owned)
      - NEWS_AVOID_LEAD_MIN / TRAIL_MIN   (briefing avoid_before gate gone)
    """
    legacy: List[str] = []
    for key in (
        "MAX_ENTRIES_PER_PAIR_PER_SESSION",
        "GBPUSD_MAX_ENTRIES",
        "EURUSD_MAX_ENTRIES",
        "USDJPY_MAX_ENTRIES",
        "USDCAD_MAX_ENTRIES",
        "GBPJPY_MAX_ENTRIES",
        "MIN_RR_THRESHOLD",
        "NEWS_AVOID_LEAD_MIN",
        "NEWS_AVOID_TRAIL_MIN",
    ):
        v = os.getenv(key)
        if v is not None and v.strip():
            legacy.append(f"{key}={v}")
    if legacy:
        logger.warning(
            "[DISPATCH] DEPRECATED env vars set (no longer read by "
            "dispatcher): %s. Use CONCURRENT_CAP_<STRATEGY> for "
            "per-strategy caps; R:R is strategy-owned; news blackout "
            "fresh-entry gate stripped. Will be silently ignored; "
            "remove from .env after verification.",
            ", ".join(legacy),
        )


_warn_deprecated_dispatcher_envs()

LIQUIDITY_SWEEP_MODE = "LIQUIDITY_SWEEP"
DISPATCH_MODE = "DISPATCH"
WINDOW_SWEEP_MODE = "WINDOW_SWEEP"

try:
    from regime_classifier import CandleRegimeClassifier  # type: ignore
except Exception:
    CandleRegimeClassifier = None  # type: ignore

_CANDLE_REGIME_ENGINES: Dict[str, Any] = {}
# symbol → last-built regime_state dict (populated by _get_candle_regime,
# read by get_latest_regime_state for strategies that don't call the
# classifier directly). Best-effort, never raises.
_LAST_REGIME_STATE: Dict[str, Dict[str, Any]] = {}


def _get_candle_regime(symbol: str, df_closed: Optional[pd.DataFrame], pip_size: float):
    if CandleRegimeClassifier is None:
        return None, None
    if df_closed is None or not isinstance(df_closed, pd.DataFrame) or df_closed.empty:
        return None, None
    sym = str(symbol).upper()
    eng = _CANDLE_REGIME_ENGINES.get(sym)
    if eng is None:
        try:
            eng = CandleRegimeClassifier(symbol=sym, pip_size=float(pip_size))
        except TypeError:
            eng = CandleRegimeClassifier(sym, float(pip_size))
        _CANDLE_REGIME_ENGINES[sym] = eng
    try:
        stable, out = eng.update_from_df(df_closed, pip_size=float(pip_size))
        # Cache the regime_state dict so signal_logger.log_open can
        # fall back to it when a strategy didn't thread it through
        # decision.debug["regime_state"]. Sub-bar staleness still
        # exists vs the in-decision path; this is the documented
        # fallback contract for incremental strategy migration.
        try:
            from regime_classifier import build_regime_state_for_debug
            _LAST_REGIME_STATE[sym] = build_regime_state_for_debug(stable, out)
        except Exception:
            pass
        return stable, out
    except Exception:
        return None, None


def get_latest_regime_state(symbol: str) -> Optional[Dict[str, Any]]:
    """Return the last regime_state dict captured for `symbol`, or None.

    Strategies that thread regime_state through their StrategyDecision.debug
    bypass this fallback. Used by signal_logger.log_open as the second
    lookup tier when decision.debug["regime_state"] is absent.
    """
    return _LAST_REGIME_STATE.get(str(symbol).upper())


def get_last_regime_label(symbol: str) -> Optional[str]:
    """Return the magnitude-axis projection of the last shadow label for symbol.

    "TRENDING_BULL"/"TRENDING_BEAR" → "TRENDING"
    "RANGE" → "RANGE"
    "NEUTRAL" → "NEUTRAL"
    None (no engine, warmup, or no successful classify yet) → None

    Consumers should treat None as NEUTRAL (no signal yet).
    """
    sym = str(symbol).upper()
    eng = _CANDLE_REGIME_ENGINES.get(sym)
    if eng is None:
        return None
    raw = getattr(eng, "_last_shadow_label", None)
    if not isinstance(raw, str):
        return None
    if raw in ("TRENDING_BULL", "TRENDING_BEAR"):
        return "TRENDING"
    if raw in ("RANGE", "NEUTRAL"):
        return raw
    return None


def _canonicalize_stable_regime(stable_regime: Optional[str]) -> Optional[str]:
    if stable_regime is None:
        return None
    s = str(stable_regime).upper().strip()
    if s in ("TREND_UP", "STRONG_TREND_UP", "TREND_DOWN", "STRONG_TREND_DOWN", "RANGE", "NEUTRAL", "UNKNOWN", "TRANSITION", "CHOP"):
        return s
    if s.startswith("RANGE"):
        return "RANGE"
    if s.startswith("NEUTRAL"):
        return "NEUTRAL"
    if s.startswith("TREND_UP"):
        return "TREND_UP"
    if s.startswith("TREND_DOWN"):
        return "TREND_DOWN"
    return s


@dataclass
class StrategyDecision:
    symbol: str
    regime: str
    signal: str
    mode: str
    entry: Optional[float]
    sl: Optional[float]
    tp: Optional[float]
    use_trailing_stop: bool
    reason: str
    debug: Dict[str, Any] = field(default_factory=dict)
    size: Optional[float] = None
    pip_size: Optional[float] = None


Snapshot5m = Dict[str, Any]

DEFAULT_SL_PIPS = float(os.getenv("DEFAULT_SL_PIPS", "20") or 20.0)
DEFAULT_TP_PIPS = float(os.getenv("DEFAULT_TP_PIPS", "30") or 30.0)
SWEEP_SL_PIPS = float(os.getenv("SWEEP_SL_PIPS", "12") or 12.0)
SWEEP_TP_PIPS = float(os.getenv("SWEEP_TP_PIPS", "100") or 100.0)


# Tolerance in pips — converted to points (multiplied by pip_size) before use.
BRIEFING_LEVEL_TOLERANCE_PIPS = float(os.getenv("BRIEFING_LEVEL_TOLERANCE_PIPS", "15") or 15.0)
BRIEFING_NO_TRADE_ZONE_ENABLED = os.getenv("BRIEFING_NO_TRADE_ZONE_ENABLED", "1").strip().lower() in ("1", "true", "yes")

CANON_PIP_SIZES = {
    "EURGBP": 1.0,
    "GBPUSD": 1.0,
    "EURUSD": 1.0,
    "AUDUSD": 1.0,
    "USDCAD": 1.0,
    "USDJPY": 1.0,
    "GBPJPY": 1.0,
}


def _pip_size_for_symbol(symbol: str, epic: str) -> float:
    s = str(symbol or "").upper()
    e = str(epic or "").upper()

    def _extract_base(x: str) -> str:
        for k in CANON_PIP_SIZES.keys():
            if k in x:
                return k
        if "." in x:
            return x.split(".")[0][:6]
        return x[:6]

    base = _extract_base(s)
    ps = CANON_PIP_SIZES.get(base)
    if ps is None and e:
        ps = CANON_PIP_SIZES.get(_extract_base(e))

    try:
        v = float(ps) if ps is not None else 1.0
        return v if np.isfinite(v) and v > 0 else 1.0
    except Exception:
        return 1.0


BB_PERIOD = int(os.getenv("BB_PERIOD", "20") or 20)
BB_STD = float(os.getenv("BB_STD", "2") or 2.0)
TREND_EMA_PULLBACK_PERIOD = int(os.getenv("TREND_EMA_PULLBACK_PERIOD", "50") or 50)

MACD_FAST = int(os.getenv("MACD_FAST", "35") or 35)
MACD_SLOW = int(os.getenv("MACD_SLOW", "45") or 45)
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL", "30") or 30)
MACD_DIRECTION_FILTER_ENABLED = os.getenv("MACD_DIRECTION_FILTER_ENABLED", "1") == "1"

AROON_PERIOD = int(os.getenv("AROON_PERIOD", "14") or 14)

_CTX_REASON_MAXLEN = int(float(os.getenv("CTX_REASON_MAXLEN", "220") or 220))
_CTX_REASON_INCLUDE_CTXDEBUG = (os.getenv("CTX_REASON_INCLUDE_CTXDEBUG", "0") or "0").strip() == "1"



def _short(s: Any, n: int = 32) -> str:
    try:
        t = str(s)
    except Exception:
        return ""
    t = t.replace("\n", " ").replace("\r", " ").strip()
    if len(t) <= n:
        return t
    return t[: max(0, n - 1)] + "…"


def _ctx_reason_suffix(ctx_dbg: Dict[str, Any]) -> str:
    if not isinstance(ctx_dbg, dict) or not ctx_dbg:
        return ""

    ctx_regime = ctx_dbg.get("ctx_regime")
    ctx_loc = ctx_dbg.get("ctx_location")
    ctx_vol = ctx_dbg.get("ctx_volatility_state")
    vrr = ctx_dbg.get("ctx_veto_rr")
    vrr_r = ctx_dbg.get("ctx_veto_rr_reason")
    vema = ctx_dbg.get("ctx_veto_ema")
    vema_r = ctx_dbg.get("ctx_veto_ema_reason")

    parts = []
    if ctx_regime is not None:
        parts.append(f"ctx={_short(ctx_regime, 18)}")
    if ctx_loc is not None:
        parts.append(f"loc={_short(ctx_loc, 18)}")
    if ctx_vol is not None:
        parts.append(f"vol={_short(ctx_vol, 18)}")
    try:
        if vrr is not None:
            parts.append(f"vrr={'1' if bool(vrr) else '0'}:{_short(vrr_r, 20)}")
    except Exception:
        pass
    try:
        if vema is not None:
            parts.append(f"vema={'1' if bool(vema) else '0'}:{_short(vema_r, 20)}")
    except Exception:
        pass

    if _CTX_REASON_INCLUDE_CTXDEBUG:
        try:
            cd = ctx_dbg.get("ctx_debug")
            if isinstance(cd, dict):
                w = cd.get("vol", {}) if isinstance(cd.get("vol"), dict) else None
                wr = w.get("width_ratio_now") if isinstance(w, dict) else None
                if wr is not None:
                    parts.append(f"wr={_short(wr, 10)}")
        except Exception:
            pass

    if not parts:
        return ""

    s = "|ctx(" + ",".join(parts) + ")"
    if len(s) > int(_CTX_REASON_MAXLEN):
        s = s[: int(_CTX_REASON_MAXLEN) - 1] + "…"
    return s


def _append_ctx_to_reason(reason: str, ctx_dbg: Dict[str, Any]) -> str:
    base = str(reason or "")
    suf = _ctx_reason_suffix(ctx_dbg)
    if not suf:
        return base
    out = base + suf
    if len(out) > int(_CTX_REASON_MAXLEN):
        out = out[: int(_CTX_REASON_MAXLEN) - 1] + "…"
    return out


def _bb_key_candidates(period: int, std: float):
    p = int(period)
    std_vals = [f"{float(std):g}", f"{float(std):.1f}", f"{float(std):.2f}"]
    std_strs: List[str] = []
    for s in std_vals:
        if s not in std_strs:
            std_strs.append(s)

    upper_keys = [f"BB_UPPER_{p}_{s}" for s in std_strs] + ["BB_UPPER"]
    lower_keys = [f"BB_LOWER_{p}_{s}" for s in std_strs] + ["BB_LOWER"]
    mid_keys = [f"BB_MID_{p}_{s}" for s in std_strs] + [f"BB_MID_{p}", "BB_MID"]
    return lower_keys, upper_keys, mid_keys


def _get_indicator(ind: Dict[str, Any], keys: List[str]) -> Optional[float]:
    if not isinstance(ind, dict):
        return None
    for k in keys:
        if k in ind:
            try:
                v = float(ind.get(k))
                if np.isfinite(v):
                    return float(v)
            except Exception:
                continue
    return None


def _pick_ema_value(indicators_dict: Dict[str, Any], prefer_period: int) -> Optional[float]:
    if not isinstance(indicators_dict, dict):
        return None
    key_exact = f"EMA_{int(prefer_period)}"
    v = indicators_dict.get(key_exact)
    try:
        if v is not None and np.isfinite(float(v)):
            return float(v)
    except Exception:
        pass

    best_p = None
    best_v = None
    for k, val in indicators_dict.items():
        if isinstance(k, str) and k.startswith("EMA_"):
            try:
                p = int(k.split("_")[1])
                fv = float(val)
                if np.isfinite(fv) and (best_p is None or p > best_p):
                    best_p = p
                    best_v = fv
            except Exception:
                continue
    return float(best_v) if best_v is not None else None


def _pick_ema_exact(indicators_dict: Dict[str, Any], period: int) -> Optional[float]:
    if not isinstance(indicators_dict, dict):
        return None
    key = f"EMA_{int(period)}"
    v = indicators_dict.get(key)
    try:
        if v is not None and np.isfinite(float(v)):
            return float(v)
    except Exception:
        pass
    return None


def _pick_macd_hist(ind: Dict[str, Any]) -> Optional[float]:
    from pair_config import pick_macd_hist
    return pick_macd_hist(ind)


def _pick_aroon(ind: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    if not isinstance(ind, dict):
        return None, None
    up_key = f"AROON_UP_{int(AROON_PERIOD)}"
    dn_key = f"AROON_DOWN_{int(AROON_PERIOD)}"
    up = ind.get(up_key)
    dn = ind.get(dn_key)
    try:
        upv = float(up) if up is not None and np.isfinite(float(up)) else None
    except Exception:
        upv = None
    try:
        dnv = float(dn) if dn is not None and np.isfinite(float(dn)) else None
    except Exception:
        dnv = None
    if upv is not None or dnv is not None:
        return upv, dnv

    upv2 = None
    dnv2 = None
    for k, val in ind.items():
        if not isinstance(k, str):
            continue
        if k.startswith("AROON_UP_"):
            try:
                fv = float(val)
                if np.isfinite(fv):
                    upv2 = fv
            except Exception:
                pass
        if k.startswith("AROON_DOWN_"):
            try:
                fv = float(val)
                if np.isfinite(fv):
                    dnv2 = fv
            except Exception:
                pass
    return upv2, dnv2


def _df_row_to_candle(row: pd.Series) -> Dict[str, Any]:
    return {
        "timestamp": row.get("time") if "time" in row else row.get("timestamp"),
        "open": float(row.get("open")),
        "high": float(row.get("high")),
        "low": float(row.get("low")),
        "close": float(row.get("close")),
    }


def _df_row_to_indicators(row: pd.Series) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if k in ("time", "timestamp", "open", "high", "low", "close", "volume"):
            continue
        out[str(k)] = v
    return out


def _build_snapshot_from_df(df: pd.DataFrame) -> Snapshot5m:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError("df empty")

    d = df.copy()

    if "time" in d.columns:
        d["time"] = pd.to_datetime(d["time"], errors="coerce", utc=True)
        d = d.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    elif "timestamp" in d.columns:
        d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce", utc=True)
        d = d.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    else:
        raise ValueError("df missing time/timestamp column")

    if len(d) < 3:
        raise ValueError("df too short")

    try:
        lower_keys, upper_keys, mid_keys = _bb_key_candidates(BB_PERIOD, BB_STD)
        ema_key = f"EMA_{int(TREND_EMA_PULLBACK_PERIOD)}"
        macd_hist_key = f"MACD_HIST_{int(MACD_FAST)}_{int(MACD_SLOW)}_{int(MACD_SIGNAL)}"
        need_cols = [ema_key, macd_hist_key, *lower_keys, *upper_keys, *mid_keys]
        if not all(str(c) in d.columns for c in need_cols):
            d = add_indicators(
                d,
                IndicatorsConfig(
                    ema_period=int(TREND_EMA_PULLBACK_PERIOD),
                    bb_period=int(BB_PERIOD),
                    bb_std=float(BB_STD),
                    macd_fast=int(MACD_FAST),
                    macd_slow=int(MACD_SLOW),
                    macd_signal=int(MACD_SIGNAL),
                    aroon_period=int(AROON_PERIOD),
                ),
            )

        if "close" in d.columns:
            close_s = pd.to_numeric(d["close"], errors="coerce").astype(float)
            for _p in (8, 13, 21):
                _k = f"EMA_{_p}"
                if _k not in d.columns:
                    try:
                        d[_k] = close_s.ewm(span=int(_p), adjust=False, min_periods=int(_p)).mean()
                    except Exception:
                        pass
    except Exception:
        pass

    r0 = d.iloc[-1]
    r1 = d.iloc[-2]
    r2 = d.iloc[-3]

    recent_rows = d.tail(6).copy()
    recent_closed = []
    for _, _row in recent_rows.iterrows():
        recent_closed.append({
            "candle": _df_row_to_candle(_row),
            "indicators": _df_row_to_indicators(_row),
        })

    return {
        "candle": _df_row_to_candle(r0),
        "indicators": _df_row_to_indicators(r0),
        "prev_candle": _df_row_to_candle(r1),
        "prev_indicators": _df_row_to_indicators(r1),
        "prev2_candle": _df_row_to_candle(r2),
        "prev2_indicators": _df_row_to_indicators(r2),
        "recent_closed": recent_closed,
    }


def _require_snapshot_5m(snapshot_5m: Snapshot5m) -> None:
    if not isinstance(snapshot_5m, dict):
        raise TypeError("snapshot_5m must be a dict")
    for k in ["candle", "indicators", "prev_candle", "prev_indicators", "prev2_candle", "prev2_indicators"]:
        if k not in snapshot_5m:
            raise ValueError(f"snapshot_5m missing required key: {k}")


def _safe_epoch_from_any_ts(ts: Any) -> Optional[float]:
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            v = float(ts)
            if np.isfinite(v) and v > 0:
                return v
            return None
    except Exception:
        pass
    try:
        dt = pd.to_datetime(ts, errors="coerce", utc=True)
        if pd.isna(dt):
            return None
        return float(dt.timestamp())
    except Exception:
        return None


def _london_dt_from_epoch(epoch: float) -> Optional[pd.Timestamp]:
    try:
        ts = pd.to_datetime(float(epoch), unit="s", utc=True)
        return ts.tz_convert("Europe/London")
    except Exception:
        return None


def _htf_compact(htf_snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(htf_snapshot, dict):
        return {}
    return {
        "h1_bias": htf_snapshot.get("h1_bias"),
        "h4_bias": htf_snapshot.get("h4_bias"),
        "d1_bias": htf_snapshot.get("d1_bias"),
        "h1_levels": htf_snapshot.get("h1_levels") if isinstance(htf_snapshot.get("h1_levels"), dict) else None,
    }


def _bias_str_to_udn(bias: Any) -> Optional[str]:
    if bias is None:
        return None
    if isinstance(bias, dict):
        bias = bias.get("bias")
    if not isinstance(bias, str):
        return None
    b = bias.strip().upper()
    if b in ("BULL", "UP", "LONG"):
        return "UP"
    if b in ("BEAR", "DOWN", "SHORT"):
        return "DOWN"
    if b in ("NEUTRAL", "FLAT", "NONE"):
        return "NEUTRAL"
    return None


def _extract_htf_bias_udn(htf_snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(htf_snapshot, dict):
        return None
    d1 = _bias_str_to_udn(htf_snapshot.get("d1_bias"))
    h1 = _bias_str_to_udn(htf_snapshot.get("h1_bias"))
    if d1 and d1 != "NEUTRAL":
        return d1
    if h1:
        return h1
    if d1:
        return d1
    return None


def _attach_htf_debug(dec: StrategyDecision, htf_snapshot: Optional[Dict[str, Any]]) -> None:
    d = dec.debug or {}
    compact = _htf_compact(htf_snapshot)
    d.setdefault("htf_snapshot", compact)
    d.setdefault("htf", compact)
    bias_udn = _extract_htf_bias_udn(htf_snapshot)
    if bias_udn is not None:
        d.setdefault("htf_bias_udn", bias_udn)
    dec.debug = d



def _levels_no_trade(levels_snapshot: Optional[Dict[str, Any]], mid_price: Optional[float] = None) -> Tuple[bool, Dict[str, Any]]:
    if not isinstance(levels_snapshot, dict):
        return False, {}

    for k in ("no_trade", "no_trade_zone", "no_trade_now"):
        v = levels_snapshot.get(k)
        if isinstance(v, bool):
            return v, {"source": "bool", "key": k, "value": v}

    if mid_price is None or not np.isfinite(float(mid_price)):
        return False, {}

    mp = float(mid_price)
    for k in ("no_trade", "no_trade_zone"):
        zones = levels_snapshot.get(k)
        if isinstance(zones, list):
            for z in zones:
                if not isinstance(z, dict):
                    continue
                low = z.get("low", z.get("min"))
                high = z.get("high", z.get("max"))
                try:
                    lo = float(low)
                    hi = float(high)
                    if np.isfinite(lo) and np.isfinite(hi):
                        lo2, hi2 = (lo, hi) if lo <= hi else (hi, lo)
                        if lo2 <= mp <= hi2:
                            return True, {"source": "zone", "key": k, "low": lo2, "high": hi2, "mid": mp}
                except Exception:
                    continue

    return False, {}


def _bb_ready(snapshot_5m: Snapshot5m) -> Tuple[bool, Dict[str, Any]]:
    ind0 = snapshot_5m.get("indicators") or {}
    lower_keys, upper_keys, mid_keys = _bb_key_candidates(BB_PERIOD, BB_STD)

    bb_u0 = _get_indicator(ind0, upper_keys)
    bb_l0 = _get_indicator(ind0, lower_keys)
    bb_m0 = _get_indicator(ind0, mid_keys)

    ok = all(v is not None and np.isfinite(float(v)) for v in [bb_u0, bb_l0, bb_m0])
    meta = {
        "bb_upper_cur": bb_u0,
        "bb_lower_cur": bb_l0,
        "bb_mid_cur": bb_m0,
        "bb_period": int(BB_PERIOD),
        "bb_std": float(BB_STD),
    }
    return ok, meta


def _ema_ready(snapshot_5m: Snapshot5m) -> Tuple[bool, Dict[str, Any]]:
    ind = snapshot_5m.get("indicators") or {}
    prev_ind = snapshot_5m.get("prev_indicators") or {}
    prev2_ind = snapshot_5m.get("prev2_indicators") or {}

    keys = [f"EMA_{8}", f"EMA_{13}", f"EMA_{21}"]
    vals = {
        "cur": {k: ind.get(k) for k in keys},
        "prev": {k: prev_ind.get(k) for k in keys},
        "prev2": {k: prev2_ind.get(k) for k in keys},
    }

    def _present(x: Any) -> bool:
        try:
            return x is not None and np.isfinite(float(x))
        except Exception:
            return False

    ok = all(_present(vals[b][k]) for b in ("cur", "prev", "prev2") for k in keys)
    return bool(ok), vals


EDGE_BUFFER_PIPS = float(os.getenv("EDGE_BUFFER_PIPS", "1.5") or 1.5)
FAIL_NO_NEW_EXTREME_BUFFER_PIPS = float(os.getenv("FAIL_NO_NEW_EXTREME_BUFFER_PIPS", "0.0") or 0.0)
TRIGGER_BUFFER_PIPS = float(os.getenv("TRIGGER_BUFFER_PIPS", "1.5") or 1.5)
EDGE_FAIL_TTL_CANDLES = int(float(os.getenv("EDGE_FAIL_TTL_CANDLES", "3") or 3))
SWEEP_MAX_TRADES_PER_DAY = int(float(os.getenv("SWEEP_MAX_TRADES_PER_DAY", "999") or 999))

SWEEP_SL_BUFFER_PIPS = float(os.getenv("SWEEP_SL_BUFFER_PIPS", "2.0") or 2.0)
SWEEP_SL_MIN_PIPS = float(os.getenv("SWEEP_SL_MIN_PIPS", "8.0") or 8.0)
SWEEP_SL_MAX_PIPS = float(os.getenv("SWEEP_SL_MAX_PIPS", "20.0") or 20.0)

SWEEP_RECLAIM_BUFFER_PIPS = float(os.getenv("SWEEP_RECLAIM_BUFFER_PIPS", "1.0") or 1.0)
SWEEP_STRONG_REVERSAL_OVERSHOOT_PIPS = float(os.getenv("SWEEP_STRONG_REVERSAL_OVERSHOOT_PIPS", "3.0") or 3.0)
SWEEP_STRONG_REVERSAL_REJECTION_PIPS = float(os.getenv("SWEEP_STRONG_REVERSAL_REJECTION_PIPS", "4.0") or 4.0)

_DEFAULT_SWEEP_WINDOWS_FALLBACK = "08:00-17:00"
DEFAULT_SWEEP_WINDOWS = os.getenv("SWEEP_WINDOWS_LONDON", _DEFAULT_SWEEP_WINDOWS_FALLBACK)
SWEEP_ACTIVE_DAILY = (os.getenv("SWEEP_ACTIVE_DAILY", "1") or "1").strip() == "1"

FAST_RECLAIM_ENABLED = (os.getenv("FAST_RECLAIM_ENABLED", "1") or "1").strip() == "1"
FAST_RECLAIM_CLOSE_POS = float(os.getenv("FAST_RECLAIM_CLOSE_POS", "0.60") or 0.60)
FAST_RECLAIM_BODY_FRAC = float(os.getenv("FAST_RECLAIM_BODY_FRAC", "0.50") or 0.50)

FAST_RECLAIM_BYPASS_EXHAUSTION = (os.getenv("FAST_RECLAIM_BYPASS_EXHAUSTION", "1") or "1").strip() == "1"

# --- Sweep quality filter (three-phase gate) ---
# Minimum pips the sweep extreme must exceed the EMA cluster midpoint (Phase 1).
SWEEP_MIN_DEPTH_PIPS = float(os.getenv("SWEEP_MIN_DEPTH_PIPS", "20") or 20.0)
SWEEP_MIN_DEPTH_PIPS_BY_SYMBOL: Dict[str, float] = {
    sym.upper(): float(os.getenv(f'SWEEP_MIN_DEPTH_PIPS_{sym.upper()}', str(SWEEP_MIN_DEPTH_PIPS)))
    for sym in ['GBPUSD', 'EURUSD', 'USDCAD', 'USDJPY', 'AUDUSD', 'USDCHF', 'NZDUSD']
}
# Minimum reversal candle body as a fraction of its total range (Phase 3).
SWEEP_MIN_BODY_PCT = float(os.getenv("SWEEP_MIN_BODY_PCT", "0.50") or 0.50)
# Minimum RSI 3-period move from its lookback extreme in the reversal direction (Phase 3).
SWEEP_RSI_MIN_MOVE = float(os.getenv("SWEEP_RSI_MIN_MOVE", "15") or 15.0)
NEWS_SWEEP_MIN_DEPTH_PIPS = float(os.getenv("NEWS_SWEEP_MIN_DEPTH_PIPS", "50.0") or 50.0)

_EDGE_SWEEP_STATE: Dict[str, Dict[str, Any]] = {}
_LAST_SWEEP_EXTREME: Dict[str, Optional[float]] = {}
_TREND_DURATION_STATE: Dict[str, int] = {}

_SWEEP_STATE_DIR = os.path.join(os.getenv("LOG_DIR", "/opt/tradingbot/logs"), "")


def _sweep_state_path(day_key: str) -> str:
    return os.path.join(_SWEEP_STATE_DIR, f"sweep_state_{day_key}.json")


def _load_sweep_state_from_disk() -> None:
    """Load today's persisted sweep daily counters on startup."""
    import datetime as _dt
    day_key = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    path = _sweep_state_path(day_key)
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        existing = _EDGE_SWEEP_STATE.get(k)
                        if not isinstance(existing, dict):
                            existing = {}
                            _EDGE_SWEEP_STATE[k] = existing
                        existing["day_key"] = day_key
                        existing["trades_today"] = int(v.get("trades_today", 0) or 0)
                logger.info(f"[sweep_state] Loaded daily counters from {path}")
    except Exception as exc:
        logger.warning(f"[sweep_state] Failed to load {path}: {exc}")


def _save_sweep_state_to_disk() -> None:
    """Persist current sweep daily counters to disk."""
    import datetime as _dt
    day_key = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    path = _sweep_state_path(day_key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data: Dict[str, Any] = {}
        for k, v in _EDGE_SWEEP_STATE.items():
            if isinstance(v, dict) and v.get("day_key") == day_key:
                data[k] = {"trades_today": int(v.get("trades_today", 0) or 0)}
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        logger.warning(f"[sweep_state] Failed to save {path}: {exc}")


# Load persisted sweep state on module import
_load_sweep_state_from_disk()


def _state_key(symbol: str, epic: str) -> str:
    return f"{str(symbol).upper()}|{str(epic).strip()}"


def get_last_sweep_extreme(symbol: str, epic: str) -> Optional[float]:
    """
    Returns the failure_high (for a SELL sweep) or failure_low (for a BUY sweep)
    from the most recently fired sweep signal for this symbol/epic.
    Stored just before _clear_sweep_state is called in evaluate_signals.
    """
    return _LAST_SWEEP_EXTREME.get(_state_key(symbol, epic))


def _parse_windows(spec: str) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    if not isinstance(spec, str) or not spec.strip():
        return out
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    for p in parts:
        try:
            a, b = p.split("-")
            ah, am = a.split(":")
            bh, bm = b.split(":")
            s = int(ah) * 60 + int(am)
            e = int(bh) * 60 + int(bm)
            if 0 <= s < 1440 and 0 <= e <= 1440 and e > s:
                out.append((s, e))
        except Exception:
            continue
    return out


def _sanitize_windows_spec(spec: str) -> Tuple[str, Dict[str, Any]]:
    raw = str(spec or "").strip()
    meta: Dict[str, Any] = {"raw": raw}

    if raw.upper() in ("0", "1", "TRUE", "FALSE", "YES", "NO"):
        meta["sanitized"] = _DEFAULT_SWEEP_WINDOWS_FALLBACK
        meta["reason"] = "flag_value_detected"
        return _DEFAULT_SWEEP_WINDOWS_FALLBACK, meta

    if ":" not in raw:
        meta["sanitized"] = _DEFAULT_SWEEP_WINDOWS_FALLBACK
        meta["reason"] = "no_colon_in_spec"
        return _DEFAULT_SWEEP_WINDOWS_FALLBACK, meta

    parsed = _parse_windows(raw)
    if not parsed:
        meta["sanitized"] = _DEFAULT_SWEEP_WINDOWS_FALLBACK
        meta["reason"] = "parse_empty_fallback"
        return _DEFAULT_SWEEP_WINDOWS_FALLBACK, meta

    meta["sanitized"] = raw
    meta["reason"] = "ok"
    return raw, meta


_SWEEP_WINDOWS_SPEC, _SWEEP_WINDOWS_META = _sanitize_windows_spec(DEFAULT_SWEEP_WINDOWS)
_SWEEP_WINDOWS = _parse_windows(_SWEEP_WINDOWS_SPEC)


def _is_in_sweep_window(london_dt: Optional[pd.Timestamp]) -> Tuple[bool, Dict[str, Any]]:
    if not SWEEP_ACTIVE_DAILY:
        return False, {"enabled": False, "windows_meta": _SWEEP_WINDOWS_META}

    if london_dt is None:
        return True, {"enabled": True, "fallback": "no_london_dt", "windows_meta": _SWEEP_WINDOWS_META}

    if not _SWEEP_WINDOWS:
        return True, {"enabled": True, "fallback": "windows_empty_allow_all_day", "windows_meta": _SWEEP_WINDOWS_META}

    minute = int(london_dt.hour) * 60 + int(london_dt.minute)
    for s, e in _SWEEP_WINDOWS:
        if s <= minute < e:
            return True, {"enabled": True, "minute": minute, "window": f"{s}-{e}", "windows": list(_SWEEP_WINDOWS), "windows_meta": _SWEEP_WINDOWS_META}
    return False, {"enabled": True, "minute": minute, "windows": list(_SWEEP_WINDOWS), "windows_meta": _SWEEP_WINDOWS_META}


def _peek_sweep_stage(symbol: str, epic: str) -> int:
    """Legacy compat — the simplified engine has no stages, always returns 0."""
    return 0


SWEEP_PIERCE_LOOKBACK = int(float(os.getenv("SWEEP_PIERCE_LOOKBACK", "5") or 5))
SWEEP_HUG_BUFFER_PIPS = float(os.getenv("SWEEP_HUG_BUFFER_PIPS", "8.0") or 8.0)
SWEEP_HUG_MIN_CANDLES = int(os.getenv("SWEEP_HUG_MIN_CANDLES", "3"))


def _check_briefing_levels(
    symbol: str,
    sweep_extreme: float,
    mid_price: float,
    signal_direction: str,
    pip_size: float,
) -> Dict[str, Any]:
    """
    Check if sweep extreme is near a briefing key level or liquidity pool.

    Returns dict with keys:
        confirmed    : bool — sweep extreme matched a briefing level
        no_trade_zone: bool — mid_price falls inside a briefing no-trade zone
        matched_level: float|None — the level that matched
        plan         : dict|None — best matching trading plan (with sl_pips/tp_pips converted)
        reason       : str
    """
    result: Dict[str, Any] = {
        "confirmed": False,
        "no_trade_zone": False,
        "matched_level": None,
        "plan": None,
        "reason": "",
    }

    briefing = morning_briefing.get_briefing(symbol)
    if not briefing or not isinstance(briefing, dict):
        result["reason"] = "no_briefing"
        return result

    # --- Stale briefing guard: reject briefings older than current session start ---
    # After a restart the bot may load yesterday's briefing from disk.  Trading on
    # stale levels/bias is worse than waiting for a fresh briefing.
    try:
        from datetime import datetime as _dt, timezone as _tz
        _bt_raw = briefing.get("briefing_time") or briefing.get("briefing_time_utc") or ""
        if _bt_raw:
            _bt = _dt.fromisoformat(str(_bt_raw).replace("Z", "+00:00")).replace(tzinfo=_tz.utc)
            _now_utc = _dt.now(_tz.utc)
            # Session start times (hour, minute) in UTC — matches morning_briefing.SESSIONS
            _session_starts = [(0, 0), (6, 30), (10, 45), (13, 0)]
            # Find the most recent session start before now
            _today = _now_utc.date()
            _candidates = [
                _dt(_today.year, _today.month, _today.day, h, m, tzinfo=_tz.utc)
                for h, m in _session_starts
            ]
            # Include yesterday's last session (NY 13:00) for early-morning edge case
            _yesterday = _today - __import__("datetime").timedelta(days=1)
            _candidates.append(
                _dt(_yesterday.year, _yesterday.month, _yesterday.day, 13, 0, tzinfo=_tz.utc)
            )
            _current_session_start = max(c for c in _candidates if c <= _now_utc)
            if _bt < _current_session_start:
                logger.warning(
                    "⚠️ [STALE BRIEFING] %s briefing_time=%s is older than current "
                    "session start %s — treating as absent",
                    symbol, _bt.isoformat(), _current_session_start.isoformat(),
                )
                result["reason"] = "stale_briefing"
                return result
    except Exception as _stale_exc:
        logger.debug("Stale-briefing check skipped for %s: %s", symbol, _stale_exc)

    tol = BRIEFING_LEVEL_TOLERANCE_PIPS * pip_size  # convert pips → points

    # --- Directional alignment (session_bias only) ---
    # Composite session+daily veto removed — daily_bias is the D1 multi-day
    # trend and intentionally allowed to disagree with session_bias.
    bias = str(briefing.get("session_bias", "")).upper()
    if bias not in ("BULLISH", "BEARISH"):
        bias = "NEUTRAL"
    # Confidence gate removed — handled by strategy-level _get_bias() with per-pair thresholds
    if bias == "BULLISH" and signal_direction == "SELL":
        result["reason"] = "briefing_bias_mismatch"
        return result
    if bias == "BEARISH" and signal_direction == "BUY":
        result["reason"] = "briefing_bias_mismatch"
        return result

    # --- Collect all key levels + liquidity pools ---
    levels: List[float] = []
    kl = briefing.get("key_levels") or {}
    for side in ("resistance", "support"):
        for lv in kl.get(side) or []:
            try:
                levels.append(float(lv))
            except (TypeError, ValueError):
                pass

    lp = briefing.get("liquidity_pools") or {}
    for side in ("buy_side", "sell_side"):
        for lv in lp.get(side) or []:
            try:
                levels.append(float(lv))
            except (TypeError, ValueError):
                pass

    if not levels:
        result["reason"] = "no_levels_in_briefing"
        return result

    # --- Find nearest level within tolerance ---
    best_dist = float("inf")
    best_level: Optional[float] = None
    for lv in levels:
        dist = abs(sweep_extreme - lv)
        if dist <= tol and dist < best_dist:
            best_dist = dist
            best_level = lv

    if best_level is None:
        # No key level matched — check NTZ before rejecting
        # (NTZ only blocks if there's no key-level confirmation)
        if BRIEFING_NO_TRADE_ZONE_ENABLED:
            for zone in briefing.get("no_trade_zones") or []:
                if isinstance(zone, (list, tuple)) and len(zone) >= 2:
                    lo, hi = float(zone[0]), float(zone[1])
                    if lo > hi:
                        lo, hi = hi, lo
                    if lo - tol <= mid_price <= hi + tol:
                        result["no_trade_zone"] = True
                        result["reason"] = f"no_trade_zone [{lo}-{hi}]"
                        return result
        result["reason"] = "no_level_match"
        return result

    # Key level matched — NTZ does NOT block confirmed level trades
    result["confirmed"] = True
    result["matched_level"] = best_level
    result["reason"] = f"level_match {best_level} (dist {best_dist / pip_size:.1f} pips)"

    # --- Find best matching trading plan ---
    plans = briefing.get("trading_plans") or []
    expected_bias = "LONG" if signal_direction == "BUY" else "SHORT"

    best_plan: Optional[Dict[str, Any]] = None
    best_rank = 999
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        if plan.get("bias") != expected_bias:
            continue
        rank = plan.get("rank", 999)
        if rank < best_rank:
            best_rank = rank
            best_plan = plan

    if best_plan:
        converted: Dict[str, Any] = dict(best_plan)

        # Check if mid_price is within the plan's entry_zone.
        # If outside, use default SL/TP instead of plan's price-derived values.
        # If no entry_zone specified, still convert from plan prices.
        entry_zone = best_plan.get("entry_zone")
        in_zone = True  # default: trust plan if no entry_zone given
        if isinstance(entry_zone, (list, tuple)) and len(entry_zone) >= 2:
            ez_lo = float(entry_zone[0])
            ez_hi = float(entry_zone[1])
            if ez_lo > ez_hi:
                ez_lo, ez_hi = ez_hi, ez_lo
            in_zone = ez_lo <= mid_price <= ez_hi

        if in_zone:
            # Convert absolute prices to pip distances from mid_price.
            # Direction matters: BUY SL is below entry, TP above; SELL opposite.
            sl_price = best_plan.get("stop_loss")
            targets = best_plan.get("targets") or []
            if sl_price is not None and pip_size > 0:
                if signal_direction == "BUY":
                    converted["sl_pips"] = (mid_price - float(sl_price)) / pip_size
                else:
                    converted["sl_pips"] = (float(sl_price) - mid_price) / pip_size
            if targets and pip_size > 0:
                if signal_direction == "BUY":
                    converted["tp_pips"] = (float(targets[0]) - mid_price) / pip_size
                else:
                    converted["tp_pips"] = (mid_price - float(targets[0])) / pip_size
        else:
            # Outside entry zone — use default SL/TP so trade isn't blocked
            converted["entry_zone_miss"] = True
            converted["sl_pips"] = float(SWEEP_SL_PIPS)
            converted["tp_pips"] = float(SWEEP_TP_PIPS)

        result["plan"] = converted

    return result


def _edge_rejection_engine(
    *,
    symbol: str,
    epic: str,
    mid_price: float,
    snapshot_5m: Snapshot5m,
    london_dt: Optional[pd.Timestamp],
) -> StrategyDecision:
    """Simplified BB-pierce + reversal-candle sweep detector.

    Condition 1 — BB Pierce: any of the last SWEEP_PIERCE_LOOKBACK candles
                  pierced the Bollinger Band (low <= bb_lower or high >= bb_upper).
    Condition 2 — Reversal candle: the most recent closed candle has a body in the
                  reversal direction and closed back inside the band.

    If both conditions met → emit BUY or SELL signal for downstream filters.
    """
    sym = str(symbol).upper()
    ep = str(epic or "").strip()
    _require_snapshot_5m(snapshot_5m)

    in_window, window_meta = _is_in_sweep_window(london_dt)
    if not in_window:
        return StrategyDecision(sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE, None, None, None, True, "sweep_outside_time_window", {"window": window_meta})

    bb_ok, bb_meta = _bb_ready(snapshot_5m)
    if not bb_ok:
        return StrategyDecision(sym, "WARMUP", "NONE", LIQUIDITY_SWEEP_MODE, None, None, None, True, "sweep_warmup_missing_bollinger", {"bb": bb_meta, "window": window_meta})

    pip_size = float(_pip_size_for_symbol(sym, ep) or 1.0)

    i0 = snapshot_5m.get("indicators") or {}
    lower_keys, upper_keys, mid_keys = _bb_key_candidates(BB_PERIOD, BB_STD)
    bb_u = _get_indicator(i0, upper_keys)
    bb_l = _get_indicator(i0, lower_keys)

    if bb_u is None or bb_l is None:
        return StrategyDecision(sym, "WARMUP", "NONE", LIQUIDITY_SWEEP_MODE, None, None, None, True, "sweep_warmup_missing_bollinger_edges", {"bb": bb_meta, "window": window_meta})

    bb_u_f = float(bb_u)
    bb_l_f = float(bb_l)

    # --- Gather recent candles (most recent last) ---
    rc_all = list(snapshot_5m.get("recent_closed") or [])
    if len(rc_all) < 2:
        return StrategyDecision(sym, "WARMUP", "NONE", LIQUIDITY_SWEEP_MODE, None, None, None, True, "sweep_warmup_insufficient_candles", {"recent_closed_count": len(rc_all), "window": window_meta})

    # --- MACD direction filter values (used later to gate signals) ---
    _macd_dir_cur: Optional[float] = None
    _macd_dir_prev: Optional[float] = None
    if MACD_DIRECTION_FILTER_ENABLED and len(rc_all) >= 3:
        _macd_dir_cur = _pick_macd_hist((rc_all[-2].get("indicators") or {}))
        _macd_dir_prev = _pick_macd_hist((rc_all[-3].get("indicators") or {}))

    # The last entry in recent_closed is the current (possibly still open) candle.
    # The reversal candle is the most recent *closed* candle = rc_all[-2].
    reversal_entry = rc_all[-2]
    rev_c = reversal_entry.get("candle") or {}
    try:
        rev_open = float(rev_c["open"])
        rev_close = float(rev_c["close"])
        rev_high = float(rev_c["high"])
        rev_low = float(rev_c["low"])
    except (KeyError, TypeError, ValueError):
        return StrategyDecision(sym, "WARMUP", "NONE", LIQUIDITY_SWEEP_MODE, None, None, None, True, "sweep_warmup_bad_candle_values", {"window": window_meta})

    # BB values at the reversal candle (use its own indicators if available, else current)
    rev_ind = reversal_entry.get("indicators") or {}
    rev_bb_u = _get_indicator(rev_ind, upper_keys)
    rev_bb_l = _get_indicator(rev_ind, lower_keys)
    rev_bb_u_f = float(rev_bb_u) if rev_bb_u is not None else bb_u_f
    rev_bb_l_f = float(rev_bb_l) if rev_bb_l is not None else bb_l_f

    # --- Daily trade cap (lightweight, uses _EDGE_SWEEP_STATE for counter only) ---
    day_key = None
    try:
        if london_dt is not None:
            day_key = london_dt.strftime("%Y-%m-%d")
    except Exception:
        day_key = None

    st_key = _state_key(sym, ep)
    st = _EDGE_SWEEP_STATE.get(st_key)
    if not isinstance(st, dict):
        st = {}
        _EDGE_SWEEP_STATE[st_key] = st
    if day_key is not None and st.get("day_key") != day_key:
        st.clear()
        st["day_key"] = day_key
        st["trades_today"] = 0

    trades_today = int(st.get("trades_today", 0) or 0)
    if trades_today >= int(SWEEP_MAX_TRADES_PER_DAY):
        return StrategyDecision(
            sym,
            "SWEEP",
            "NONE",
            LIQUIDITY_SWEEP_MODE,
            None,
            None,
            None,
            True,
            "sweep_daily_limit_reached",
            {"trades_today": trades_today, "max": int(SWEEP_MAX_TRADES_PER_DAY), "window": window_meta, "day_key": day_key},
        )

    # --- Pattern 0: Single-candle spike (BB pierce + reversal in one candle) ---
    # On extreme news spikes a single 5M candle can pierce the band and reverse.
    _spike_range = float(rev_high - rev_low)
    _spike_body = float(abs(rev_close - rev_open))
    if _spike_range > 0:
        _spike_body_pct = _spike_body / _spike_range
        _spike_lower_wick = float(min(rev_open, rev_close) - rev_low)
        _spike_upper_wick = float(rev_high - max(rev_open, rev_close))
        _spike_lower_wick_pct = _spike_lower_wick / _spike_range
        _spike_upper_wick_pct = _spike_upper_wick / _spike_range

        spike_buy = (
            rev_low <= rev_bb_l_f
            and rev_close > rev_open
            and rev_close > rev_bb_l_f
            and _spike_body_pct >= 0.50
        )
        spike_sell = (
            rev_high >= rev_bb_u_f
            and rev_close < rev_open
            and rev_close < rev_bb_u_f
            and _spike_body_pct >= 0.50
        )

        if spike_buy or spike_sell:
            if spike_buy and spike_sell:
                _spike_sig = "BUY" if _spike_lower_wick_pct >= _spike_upper_wick_pct else "SELL"
            elif spike_buy:
                _spike_sig = "BUY"
            else:
                _spike_sig = "SELL"

            _spike_extreme = rev_low if _spike_sig == "BUY" else rev_high
            _spike_sl = float(SWEEP_SL_PIPS)
            try:
                if pip_size > 0:
                    if _spike_sig == "SELL":
                        _spike_sl_raw = (float(_spike_extreme) - float(mid_price)) / float(pip_size) + float(SWEEP_SL_BUFFER_PIPS)
                    else:
                        _spike_sl_raw = (float(mid_price) - float(_spike_extreme)) / float(pip_size) + float(SWEEP_SL_BUFFER_PIPS)
                    if np.isfinite(_spike_sl_raw) and _spike_sl_raw > 0:
                        _spike_sl = float(max(float(SWEEP_SL_MIN_PIPS), min(float(SWEEP_SL_MAX_PIPS), _spike_sl_raw)))
            except Exception:
                pass

            _spike_reason = f"sweep_single_candle_spike_{_spike_sig.lower()}"
            _spike_dbg: Dict[str, Any] = {
                "pip_size": float(pip_size),
                "bb_upper": bb_u_f,
                "bb_lower": bb_l_f,
                "rev_open": rev_open,
                "rev_high": rev_high,
                "rev_low": rev_low,
                "rev_close": rev_close,
                "rev_bb_upper": rev_bb_u_f,
                "rev_bb_lower": rev_bb_l_f,
                "spike_range": _spike_range,
                "spike_body_pct": _spike_body_pct,
                "spike_lower_wick_pct": _spike_lower_wick_pct,
                "spike_upper_wick_pct": _spike_upper_wick_pct,
                "spike_buy": spike_buy,
                "spike_sell": spike_sell,
                "adaptive_sl_pips": _spike_sl,
                "pierce_extreme": float(_spike_extreme),
                "pattern": "single_candle_spike",
                "trades_today": trades_today,
                "day_key": day_key,
                "window": window_meta,
            }

            # Briefing level gate (required for all patterns)
            _spike_final_sl = _spike_sl
            _spike_final_tp = float(SWEEP_TP_PIPS)
            try:
                if pip_size > 0:
                    _spike_bc = _check_briefing_levels(sym, float(_spike_extreme), mid_price, _spike_sig, pip_size)
                    if _spike_bc.get("no_trade_zone"):
                        _spike_dbg["briefing_no_trade_zone"] = True
                        _spike_dbg["briefing_reason"] = _spike_bc.get("reason", "")
                        return StrategyDecision(
                            sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                            None, None, None, True,
                            "sweep_briefing_no_trade_zone", _spike_dbg,
                        )
                    _spike_bc_reason = _spike_bc.get("reason", "")
                    _spike_dbg["briefing_confirmed"] = _spike_bc.get("confirmed", False)
                    _spike_dbg["briefing_reason"] = _spike_bc_reason
                    if _spike_bc_reason == "no_briefing":
                        # No briefing for today — block trade
                        return StrategyDecision(
                            sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                            None, None, None, True,
                            "sweep_no_briefing_available", _spike_dbg,
                        )
                    if not _spike_bc.get("confirmed"):
                        # Briefing exists but sweep extreme not near any level → reject
                        return StrategyDecision(
                            sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                            None, None, None, True,
                            "sweep_no_briefing_level", _spike_dbg,
                        )
                    if _spike_bc.get("confirmed"):
                        _spike_dbg["briefing_level"] = _spike_bc.get("matched_level")
                        _spike_reason = f"sweep_briefing_confirmed_{_spike_sig.lower()}"
                        plan = _spike_bc.get("plan")
                        if plan:
                            plan_sl = plan.get("sl_pips")
                            plan_tp = plan.get("tp_pips")
                            if plan_sl is not None and float(plan_sl) > 0:
                                _spike_final_sl = float(plan_sl)
                                _spike_dbg["briefing_sl_pips"] = _spike_final_sl
                            if plan_tp is not None and float(plan_tp) > 0:
                                _spike_final_tp = float(plan_tp)
                                _spike_dbg["briefing_tp_pips"] = _spike_final_tp
                            _spike_dbg["briefing_plan_label"] = plan.get("label", "")
            except Exception:
                pass

            # --- MACD direction filter (pattern 0) ---
            if MACD_DIRECTION_FILTER_ENABLED and _macd_dir_cur is not None and _macd_dir_prev is not None:
                _spike_dbg["macd_dir_cur"] = _macd_dir_cur
                _spike_dbg["macd_dir_prev"] = _macd_dir_prev
                if _spike_sig == "SELL" and _macd_dir_cur >= _macd_dir_prev:
                    return StrategyDecision(
                        sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                        None, None, None, True,
                        "macd_still_rising_sell_blocked", _spike_dbg,
                    )
                if _spike_sig == "BUY" and _macd_dir_cur <= _macd_dir_prev:
                    return StrategyDecision(
                        sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                        None, None, None, True,
                        "macd_still_falling_buy_blocked", _spike_dbg,
                    )

            st["failure_high"] = rev_high if _spike_sig == "SELL" else None
            st["failure_low"] = rev_low if _spike_sig == "BUY" else None

            return StrategyDecision(
                sym,
                "SWEEP",
                _spike_sig,
                LIQUIDITY_SWEEP_MODE,
                float(mid_price),
                _spike_final_sl,
                _spike_final_tp,
                True,
                _spike_reason,
                _spike_dbg,
            )

    # --- Condition 1: BB pierce within last N candles ---
    # Walk recent_closed backwards (skip last entry = current open candle).
    # For each candle, get its BB values from its own indicators snapshot so that
    # the comparison uses the band position at the time of the candle, not now.
    lookback = min(int(SWEEP_PIERCE_LOOKBACK), len(rc_all) - 1)
    # rc_all[-1] is current (open) candle; candidates are rc_all[-(lookback+1):-1]
    pierce_candidates = rc_all[-(lookback + 1):-1] if lookback > 0 else []

    buy_pierce_extreme: Optional[float] = None   # lowest low that pierced bb_lower
    sell_pierce_extreme: Optional[float] = None   # highest high that pierced bb_upper
    buy_pierce_idx: Optional[int] = None          # recency (0 = most recent closed)
    sell_pierce_idx: Optional[int] = None

    for offset_from_end, entry in enumerate(reversed(pierce_candidates)):
        ec = entry.get("candle") or {}
        ei = entry.get("indicators") or {}
        try:
            e_high = float(ec["high"])
            e_low = float(ec["low"])
        except (KeyError, TypeError, ValueError):
            continue
        e_bb_u = _get_indicator(ei, upper_keys)
        e_bb_l = _get_indicator(ei, lower_keys)
        e_bb_u_f = float(e_bb_u) if e_bb_u is not None else bb_u_f
        e_bb_l_f = float(e_bb_l) if e_bb_l is not None else bb_l_f

        # BUY pierce: low touched or went through lower band
        if e_low <= e_bb_l_f:
            if buy_pierce_extreme is None or e_low < buy_pierce_extreme:
                buy_pierce_extreme = e_low
            if buy_pierce_idx is None:
                buy_pierce_idx = offset_from_end
        # SELL pierce: high touched or went through upper band
        if e_high >= e_bb_u_f:
            if sell_pierce_extreme is None or e_high > sell_pierce_extreme:
                sell_pierce_extreme = e_high
            if sell_pierce_idx is None:
                sell_pierce_idx = offset_from_end

    # --- Condition 2: Reversal candle (most recent closed) ---
    # Body must be >= 50% of total range
    rev_range = float(rev_high - rev_low)
    rev_body = float(abs(rev_close - rev_open))
    rev_body_pct = (rev_body / rev_range) if rev_range > 0 else 0.0
    rev_body_ok = bool(rev_body_pct >= 0.50)

    buy_reversal = bool(rev_close > rev_open and rev_close > rev_bb_l_f and rev_body_ok)
    sell_reversal = bool(rev_close < rev_open and rev_close < rev_bb_u_f and rev_body_ok)

    buy_setup = buy_pierce_extreme is not None and buy_reversal
    sell_setup = sell_pierce_extreme is not None and sell_reversal

    dbg_base: Dict[str, Any] = {
        "pip_size": float(pip_size),
        "bb_upper": bb_u_f,
        "bb_lower": bb_l_f,
        "rev_open": rev_open,
        "rev_high": rev_high,
        "rev_low": rev_low,
        "rev_close": rev_close,
        "rev_bb_upper": rev_bb_u_f,
        "rev_bb_lower": rev_bb_l_f,
        "buy_pierce_extreme": buy_pierce_extreme,
        "sell_pierce_extreme": sell_pierce_extreme,
        "buy_pierce_idx": buy_pierce_idx,
        "sell_pierce_idx": sell_pierce_idx,
        "rev_body_pct": float(rev_body_pct),
        "rev_body_ok": rev_body_ok,
        "buy_reversal": buy_reversal,
        "sell_reversal": sell_reversal,
        "buy_setup": buy_setup,
        "sell_setup": sell_setup,
        "lookback": lookback,
        "trades_today": trades_today,
        "day_key": day_key,
        "window": window_meta,
        "sweep_windows_meta": _SWEEP_WINDOWS_META,
        "sweep_windows_spec": _SWEEP_WINDOWS_SPEC,
    }

    if not buy_setup and not sell_setup:
        # --- Pattern 2: Curve Top/Bottom (hug + reversal) ---
        hug_lookback = min(6, len(rc_all) - 1)
        hug_candidates = rc_all[-(hug_lookback + 1):-2] if hug_lookback > 0 else []
        hug_buffer = float(SWEEP_HUG_BUFFER_PIPS) * float(pip_size)
        hug_upper_count = 0
        hug_lower_count = 0
        hug_highest_high: Optional[float] = None  # track extreme for SELL
        hug_lowest_low: Optional[float] = None     # track extreme for BUY
        for hc_entry in hug_candidates:
            hc_c = hc_entry.get("candle") or {}
            hc_i = hc_entry.get("indicators") or {}
            try:
                hc_high = float(hc_c["high"])
                hc_low = float(hc_c["low"])
            except (KeyError, TypeError, ValueError):
                continue
            hc_bb_u = _get_indicator(hc_i, upper_keys)
            hc_bb_l = _get_indicator(hc_i, lower_keys)
            hc_bb_u_f = float(hc_bb_u) if hc_bb_u is not None else bb_u_f
            hc_bb_l_f = float(hc_bb_l) if hc_bb_l is not None else bb_l_f
            # Hug = within buffer below band OR piercing through (above/below)
            if hc_high >= hc_bb_u_f - hug_buffer:
                hug_upper_count += 1
                if hug_highest_high is None or hc_high > hug_highest_high:
                    hug_highest_high = hc_high
            if hc_low <= hc_bb_l_f + hug_buffer:
                hug_lower_count += 1
                if hug_lowest_low is None or hc_low < hug_lowest_low:
                    hug_lowest_low = hc_low

        # Reversal candle confirmation for curve pattern
        # The close-away-from-band candle IS the entry signal — no prior candle check needed.
        curve_sell = (
            hug_upper_count >= int(SWEEP_HUG_MIN_CANDLES)
            and rev_close < rev_open
            and rev_body_ok
            and rev_close < rev_bb_u_f
        )
        curve_buy = (
            hug_lower_count >= int(SWEEP_HUG_MIN_CANDLES)
            and rev_close > rev_open
            and rev_body_ok
            and rev_close > rev_bb_l_f
        )

        dbg_base["hug_upper_count"] = hug_upper_count
        dbg_base["hug_lower_count"] = hug_lower_count
        dbg_base["hug_highest_high"] = hug_highest_high
        dbg_base["hug_lowest_low"] = hug_lowest_low
        dbg_base["hug_buffer"] = hug_buffer
        dbg_base["curve_sell"] = curve_sell
        dbg_base["curve_buy"] = curve_buy

        if not curve_sell and not curve_buy:
            return StrategyDecision(sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE, None, None, None, True, "sweep_idle_no_edge", dbg_base)

        # Pattern 2 signal — use fixed SL (no pierce extreme for adaptive calc)
        if curve_sell and curve_buy:
            p2_sig = "SELL" if hug_upper_count >= hug_lower_count else "BUY"
        elif curve_sell:
            p2_sig = "SELL"
        else:
            p2_sig = "BUY"

        # Use hug extreme as sweep_extreme for briefing level check
        p2_sweep_extreme = hug_highest_high if p2_sig == "SELL" else hug_lowest_low
        if p2_sweep_extreme is None:
            p2_sweep_extreme = mid_price  # fallback (shouldn't happen)

        p2_reason = "sweep_curve_top_sell" if p2_sig == "SELL" else "sweep_curve_bottom_buy"
        dbg_base["pattern"] = "curve"
        dbg_base["adaptive_sl_pips"] = float(SWEEP_SL_PIPS)
        dbg_base["pierce_extreme"] = float(p2_sweep_extreme)

        # Briefing level gate (required for all patterns)
        p2_final_sl = float(SWEEP_SL_PIPS)
        p2_final_tp = float(SWEEP_TP_PIPS)
        try:
            if pip_size > 0:
                _p2_bc = _check_briefing_levels(sym, p2_sweep_extreme, mid_price, p2_sig, pip_size)
                if _p2_bc.get("no_trade_zone"):
                    dbg_base["briefing_no_trade_zone"] = True
                    dbg_base["briefing_reason"] = _p2_bc.get("reason", "")
                    return StrategyDecision(
                        sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                        None, None, None, True,
                        "sweep_briefing_no_trade_zone", dbg_base,
                    )
                _p2_bc_reason = _p2_bc.get("reason", "")
                dbg_base["briefing_confirmed"] = _p2_bc.get("confirmed", False)
                dbg_base["briefing_reason"] = _p2_bc_reason
                if _p2_bc_reason == "no_briefing":
                    return StrategyDecision(
                        sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                        None, None, None, True,
                        "sweep_no_briefing_available", dbg_base,
                    )
                if not _p2_bc.get("confirmed"):
                    return StrategyDecision(
                        sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                        None, None, None, True,
                        "sweep_no_briefing_level", dbg_base,
                    )
                if _p2_bc.get("confirmed"):
                    dbg_base["briefing_level"] = _p2_bc.get("matched_level")
                    p2_reason = f"sweep_briefing_confirmed_{p2_sig.lower()}"
                    plan = _p2_bc.get("plan")
                    if plan:
                        plan_sl = plan.get("sl_pips")
                        plan_tp = plan.get("tp_pips")
                        if plan_sl is not None and float(plan_sl) > 0:
                            p2_final_sl = float(plan_sl)
                            dbg_base["briefing_sl_pips"] = p2_final_sl
                        if plan_tp is not None and float(plan_tp) > 0:
                            p2_final_tp = float(plan_tp)
                            dbg_base["briefing_tp_pips"] = p2_final_tp
                        dbg_base["briefing_plan_label"] = plan.get("label", "")
        except Exception:
            pass

        # --- MACD direction filter (pattern 2) ---
        if MACD_DIRECTION_FILTER_ENABLED and _macd_dir_cur is not None and _macd_dir_prev is not None:
            dbg_base["macd_dir_cur"] = _macd_dir_cur
            dbg_base["macd_dir_prev"] = _macd_dir_prev
            if p2_sig == "SELL" and _macd_dir_cur >= _macd_dir_prev:
                return StrategyDecision(
                    sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                    None, None, None, True,
                    "macd_still_rising_sell_blocked", dbg_base,
                )
            if p2_sig == "BUY" and _macd_dir_cur <= _macd_dir_prev:
                return StrategyDecision(
                    sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                    None, None, None, True,
                    "macd_still_falling_buy_blocked", dbg_base,
                )

        st["failure_high"] = None
        st["failure_low"] = None

        return StrategyDecision(
            sym,
            "SWEEP",
            p2_sig,
            LIQUIDITY_SWEEP_MODE,
            float(mid_price),
            p2_final_sl,
            p2_final_tp,
            True,
            p2_reason,
            dbg_base,
        )

    # --- Direction priority: if both, prefer the most recent pierce ---
    if buy_setup and sell_setup:
        # Lower idx = more recent (0 = last closed candle)
        if (buy_pierce_idx or 999) <= (sell_pierce_idx or 999):
            sig = "BUY"
        else:
            sig = "SELL"
    elif buy_setup:
        sig = "BUY"
    else:
        sig = "SELL"

    pierce_extreme = buy_pierce_extreme if sig == "BUY" else sell_pierce_extreme

    # --- Adaptive stop loss: distance from entry to the pierce extreme + buffer ---
    adaptive_sl = float(SWEEP_SL_PIPS)
    try:
        if pip_size > 0 and pierce_extreme is not None:
            if sig == "SELL":
                sl_raw = (float(pierce_extreme) - float(mid_price)) / float(pip_size) + float(SWEEP_SL_BUFFER_PIPS)
            else:
                sl_raw = (float(mid_price) - float(pierce_extreme)) / float(pip_size) + float(SWEEP_SL_BUFFER_PIPS)
            if np.isfinite(sl_raw) and sl_raw > 0:
                adaptive_sl = float(max(float(SWEEP_SL_MIN_PIPS), min(float(SWEEP_SL_MAX_PIPS), sl_raw)))
    except Exception:
        pass

    reason = f"sweep_bb_pierce_{sig.lower()}"
    dbg_base["adaptive_sl_pips"] = adaptive_sl
    dbg_base["pierce_extreme"] = float(pierce_extreme) if pierce_extreme is not None else None

    # Store pierce extreme in state for _LAST_SWEEP_EXTREME tracking by evaluate_signals
    st["failure_high"] = float(sell_pierce_extreme) if sell_pierce_extreme is not None else None
    st["failure_low"] = float(buy_pierce_extreme) if buy_pierce_extreme is not None else None

    # --- Briefing level gate (required for all patterns) ---
    final_sl = adaptive_sl
    final_tp = float(SWEEP_TP_PIPS)
    try:
        if pierce_extreme is not None and pip_size > 0:
            briefing_check = _check_briefing_levels(sym, pierce_extreme, mid_price, sig, pip_size)

            if briefing_check.get("no_trade_zone"):
                dbg_base["briefing_no_trade_zone"] = True
                dbg_base["briefing_reason"] = briefing_check.get("reason", "")
                return StrategyDecision(
                    sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                    None, None, None, True,
                    "sweep_briefing_no_trade_zone", dbg_base,
                )

            bc_reason = briefing_check.get("reason", "")
            dbg_base["briefing_confirmed"] = briefing_check.get("confirmed", False)
            dbg_base["briefing_reason"] = bc_reason
            if bc_reason == "no_briefing":
                # No briefing for today — block trade
                return StrategyDecision(
                    sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                    None, None, None, True,
                    "sweep_no_briefing_available", dbg_base,
                )
            if not briefing_check.get("confirmed"):
                # Briefing exists but sweep extreme not near any level → reject
                return StrategyDecision(
                    sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                    None, None, None, True,
                    "sweep_no_briefing_level", dbg_base,
                )

            if briefing_check.get("confirmed"):
                dbg_base["briefing_level"] = briefing_check.get("matched_level")
                reason = f"sweep_briefing_confirmed_{sig.lower()}"

                plan = briefing_check.get("plan")
                if plan:
                    plan_sl = plan.get("sl_pips")
                    plan_tp = plan.get("tp_pips")
                    if plan_sl is not None and float(plan_sl) > 0:
                        final_sl = float(plan_sl)
                        dbg_base["briefing_sl_pips"] = final_sl
                    if plan_tp is not None and float(plan_tp) > 0:
                        final_tp = float(plan_tp)
                        dbg_base["briefing_tp_pips"] = final_tp
                    dbg_base["briefing_plan_label"] = plan.get("label", "")
    except Exception:
        pass

    # --- MACD direction filter (pattern 1) ---
    if MACD_DIRECTION_FILTER_ENABLED and _macd_dir_cur is not None and _macd_dir_prev is not None:
        dbg_base["macd_dir_cur"] = _macd_dir_cur
        dbg_base["macd_dir_prev"] = _macd_dir_prev
        if sig == "SELL" and _macd_dir_cur >= _macd_dir_prev:
            return StrategyDecision(
                sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                None, None, None, True,
                "macd_still_rising_sell_blocked", dbg_base,
            )
        if sig == "BUY" and _macd_dir_cur <= _macd_dir_prev:
            return StrategyDecision(
                sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE,
                None, None, None, True,
                "macd_still_falling_buy_blocked", dbg_base,
            )

    return StrategyDecision(
        sym,
        "SWEEP",
        sig,
        LIQUIDITY_SWEEP_MODE,
        float(mid_price),
        final_sl,
        final_tp,
        True,
        reason,
        dbg_base,
    )


def _clear_sweep_state(symbol: str, epic: str, keep_day: bool = True) -> None:
    k = _state_key(symbol, epic)
    st = _EDGE_SWEEP_STATE.get(k)
    if not isinstance(st, dict):
        return
    day_key = st.get("day_key") if keep_day else None
    trades_today = st.get("trades_today") if keep_day else None
    st.clear()
    if keep_day:
        if day_key is not None:
            st["day_key"] = day_key
        if trades_today is not None:
            st["trades_today"] = trades_today


# EMA_PULLBACK, TREND_FOLLOW, and RANGE_REVERSION strategies removed 2026-04-07.

def evaluate_signals(
    symbol: str,
    epic: str,
    bid: float,
    ask: float,
    update_time: Any = None,
    update_micro: Any = None,
    htf_snapshot: Optional[Dict[str, Any]] = None,
    levels_snapshot: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> StrategyDecision:
    sym = str(symbol).upper()
    ep = str(epic or "")

    try:
        bid_f = float(bid)
        ask_f = float(ask)
        mid_price = (bid_f + ask_f) / 2.0
        if not np.isfinite(mid_price):
            raise ValueError("mid_price not finite")
    except Exception:
        dec = StrategyDecision(sym, "WARMUP", "NONE", DISPATCH_MODE, None, None, None, True, "warmup_missing_mid_price", {"have_bid": bid is not None, "have_ask": ask is not None})
        _attach_htf_debug(dec, htf_snapshot)
        return dec

    pip_size = float(_pip_size_for_symbol(sym, ep) or 1.0)

    def _apply_exec_entry(decision: StrategyDecision) -> StrategyDecision:
        try:
            sig = str(decision.signal or "").upper()
        except Exception:
            sig = "NONE"
        if sig not in ("BUY", "SELL"):
            return decision

        # ── Per-strategy concurrent open-position cap (2026-04-30) ─────────
        # Replaces the prior per-pair session entry cap. Live count read
        # from trade_executor.EPIC_STATE on every dispatch — when a position
        # closes, the slot frees on the next dispatch. NO counter to
        # increment.
        #
        # Bypass via:
        #   - EXEMPT_STRATEGIES (NEWS_TICK, NEWS_STRATEGY) — _resolve_*
        #     returns None
        #   - BYPASS_CONCURRENT_CAP=1 env var (process-wide kill switch)
        #   - decision.debug["bypass_concurrent_cap"] = True (per-call)
        try:
            _strategy_name = _strategy_family(str(getattr(decision, "mode", "") or ""))
            cap = _resolve_concurrent_cap(_strategy_name)
            if cap is not None:
                _bypass_env = os.getenv("BYPASS_CONCURRENT_CAP", "0").strip() in ("1", "true", "yes")
                _bypass_call = bool((decision.debug or {}).get("bypass_concurrent_cap"))
                cur = _count_open_positions(ep, _strategy_name)
                if _bypass_env or _bypass_call:
                    if cur >= cap:
                        logger.info(
                            "[DISPATCH] %s %s %s would-block at %d/%d, "
                            "bypassed via %s",
                            ep, sig, _strategy_name, cur, cap,
                            "BYPASS_CONCURRENT_CAP" if _bypass_env else "decision.debug",
                        )
                elif cur >= cap:
                    logger.info(
                        "[DISPATCH] %s %s %s blocked — concurrent cap reached (%d/%d)",
                        ep, sig, _strategy_name, cur, cap,
                    )
                    return StrategyDecision(
                        symbol=sym, regime="DISPATCH", signal="NONE",
                        mode=decision.mode, entry=None, sl=None, tp=None,
                        use_trailing_stop=False,
                        reason=f"concurrent_cap_reached_{cur}_{cap}",
                        debug={"strategy": _strategy_name, "cap": cap, "current": cur},
                    )
                else:
                    logger.info(
                        "[DISPATCH] %s %s %s entry accepted (%d/%d open before)",
                        ep, sig, _strategy_name, cur, cap,
                    )
            else:
                logger.info(
                    "[DISPATCH] %s %s %s exempt from concurrent cap",
                    ep, sig, _strategy_name,
                )
        except Exception as _cap_exc:
            logger.debug("[DISPATCH] concurrent cap check failed: %s", _cap_exc)

        exec_price = float(ask_f) if sig == "BUY" else float(bid_f)
        try:
            decision.debug = {
                **(decision.debug or {}),
                "bid": float(bid_f),
                "ask": float(ask_f),
                "mid": float(mid_price),
                "spread": float(ask_f - bid_f),
                "entry_mid": float(decision.entry) if decision.entry is not None else None,
                "entry_exec": float(exec_price),
                "pip_size": float(pip_size),
            }
        except Exception:
            pass
        decision.entry = float(exec_price)
        decision.pip_size = float(pip_size)
        return decision

    df_in = kwargs.get("df") if isinstance(kwargs.get("df"), pd.DataFrame) else None
    snapshot_5m: Optional[Snapshot5m] = None

    if df_in is not None and len(df_in) < 3:
        dec = StrategyDecision(sym, "WARMUP", "NONE", DISPATCH_MODE, None, None, None, True, f"warmup_closed_bars_{len(df_in)}_need_3", {"closed_bars": len(df_in), "required_bars": 3})
        _attach_htf_debug(dec, htf_snapshot)
        return dec

    if isinstance(kwargs.get("snapshot_5m"), dict):
        snapshot_5m = kwargs.get("snapshot_5m")
    elif df_in is not None:
        try:
            snapshot_5m = _build_snapshot_from_df(df_in)
        except Exception as e:
            dec = StrategyDecision(sym, "WARMUP", "NONE", DISPATCH_MODE, None, None, None, True, "warmup_snapshot_build_failed", {"error": f"{type(e).__name__}: {e}"})
            _attach_htf_debug(dec, htf_snapshot)
            return dec

    if snapshot_5m is None:
        dec = StrategyDecision(sym, "WARMUP", "NONE", DISPATCH_MODE, None, None, None, True, "warmup_missing_snapshot", {"expected": "kwargs['snapshot_5m'] or kwargs['df']"})
        _attach_htf_debug(dec, htf_snapshot)
        return dec

    _require_snapshot_5m(snapshot_5m)

    ts_epoch = _safe_epoch_from_any_ts(kwargs.get("ts"))
    if ts_epoch is None:
        c_ts_any = (snapshot_5m.get("candle") or {}).get("timestamp")
        ts_epoch = _safe_epoch_from_any_ts(c_ts_any)
    if ts_epoch is None:
        ts_epoch = float(pd.Timestamp.utcnow().timestamp())

    london_dt = _london_dt_from_epoch(float(ts_epoch))

    # Gate: sweep strategies only run on new 5M candle closes
    _is_new_5m = bool(kwargs.get("is_new_5m_close", False))

    # Phase 4B shadow classifier — runs on every 5m close so the operator
    # has a labelled regime stream to review before deciding to gate any
    # strategy on it. Best-effort; never propagates.
    if _is_new_5m and df_in is not None:
        try:
            _get_candle_regime(sym, df_in, pip_size)
        except Exception as _rgm_exc:
            logger.debug("[REGIME-SHADOW] %s classifier raised: %s", sym, _rgm_exc)

    # ── Regime router: load once per evaluation ──────────────────────
    try:
        import regime_router as _rr
    except Exception:
        _rr = None

    def _regime_allows(strategy_name: str) -> bool:
        # Regime gating disabled — observation only, no strategy blocking
        return True

    def _regime_min_prob(strategy_name: str) -> float:
        # Regime gating disabled — no min probability threshold
        return 0.0

    # ----------------------------------------------------------------
    # 0) BRIEFING_EXECUTION — trade directly from briefing trading_plans[0]
    #    (runs EVERY tick — highest priority strategy)
    # ----------------------------------------------------------------
    try:
        from briefing_execution import BriefingExecutionStrategy, BRIEFING_EXECUTION_ENABLED as _BE_ENABLED
        if _BE_ENABLED and _regime_allows("BRIEFING_EXECUTION"):
            _be_briefing = None
            try:
                _be_briefing = morning_briefing.get_briefing(sym)
            except Exception:
                pass
            if not hasattr(evaluate_signals, "_be_strat"):
                evaluate_signals._be_strat = BriefingExecutionStrategy()
            _be_candle_close = None
            if _is_new_5m and df_in is not None and len(df_in) > 0:
                try:
                    _be_candle_close = float(df_in.iloc[-1]["close"])
                except Exception:
                    pass
            _be_dec = evaluate_signals._be_strat.evaluate_tick(
                sym, ep, float(mid_price), pip_size, _be_briefing,
                is_new_5m=_is_new_5m,
                candle_close=_be_candle_close,
                df_5m=df_in,
            )
            if _be_dec and str(_be_dec.signal or "").upper() in ("BUY", "SELL"):
                _attach_htf_debug(_be_dec, htf_snapshot)
                return _apply_exec_entry(_be_dec)
    except Exception as _be_exc:
        record_exception("BRIEFING-EXEC", _be_exc)
        logger.warning("[BRIEFING-EXEC] evaluate error: %s", _be_exc)

    # ----------------------------------------------------------------
    # 0.4) BRIEFING_V5_EXECUTION — Phase 3 PIA executor.
    #     Reads briefings/v5_pia/*.json, fires when price approaches the
    #     committed entry. Runs in PARALLEL with v4 above when env
    #     BRIEFING_V5_PARALLEL_MODE=1; both can fire within the
    #     BRIEFING_MAX_CONCURRENT_LEGS cap. When the env is 0 the
    #     executor is fully inert and v4 keeps current semantics.
    #     Wires via per-pair-worker thread (PRs #8/#9/#10) — same
    #     thread that ran the v4 block above.
    # ----------------------------------------------------------------
    try:
        from briefing.v5_pia.executor import V5_EXECUTOR as _V5_EXEC
        _v5_dec = _V5_EXEC.evaluate_tick(
            sym, ep, float(mid_price), pip_size,
            df_5m=df_in,
        )
        if _v5_dec and str(_v5_dec.signal or "").upper() in ("BUY", "SELL"):
            _attach_htf_debug(_v5_dec, htf_snapshot)
            return _apply_exec_entry(_v5_dec)
    except Exception as _v5_exc:
        record_exception("BRIEFING-V5", _v5_exc)
        logger.warning("[v5-exec] evaluate error: %s", _v5_exc)

    # ----------------------------------------------------------------
    # 0.45) BRIEFING_PIA_FIRST — daily LLM-authored plans (one per pair).
    #     Reads briefings/pia_first/<DATE>/<PAIR>.json, fires MARKET at
    #     current price with SL/TP from plan.stop/plan.target. Gated by
    #     PIA_FIRST_ENABLED env. Per-pair-per-day dedup is internal to
    #     the executor (cache/pia_first_state.json).
    # ----------------------------------------------------------------
    try:
        import pia_first_executor as _PF_EXEC
        _pf_dec = _PF_EXEC.evaluate_tick(
            sym, ep, float(mid_price), pip_size, df_5m=df_in,
        )
        if _pf_dec and str(_pf_dec.signal or "").upper() in ("BUY", "SELL"):
            _attach_htf_debug(_pf_dec, htf_snapshot)
            return _apply_exec_entry(_pf_dec)
    except Exception as _pf_exc:
        record_exception("PIA-FIRST", _pf_exc)
        logger.warning("[pia_first_exec] evaluate error: %s", _pf_exc)

    # ----------------------------------------------------------------
    # 0.5) BB_REVERSAL — standalone BB pierce+reject (GBPUSD only).
    # Evaluated BEFORE all other entry strategies so it cannot be
    # preempted by BRIEFING_LIQUIDITY / BRIEFING_SWEEP / BRIEFING_HUNT /
    # sweep variants firing on the same 5M close.
    # Independent of briefing/regime/news. Bypasses session cap.
    # ----------------------------------------------------------------
    if _is_new_5m and not _router_manages("BB_REVERSAL", sym):
        try:
            from bb_reversal import (
                BBReversalStrategy,
                BB_REVERSAL_ENABLED as _BBR_ENABLED,
                ALLOWED_PAIRS as _BBR_PAIRS,
            )
            if _BBR_ENABLED and sym.upper() in _BBR_PAIRS and df_in is not None:
                if not hasattr(BBReversalStrategy, "_instance"):
                    BBReversalStrategy._instance = BBReversalStrategy()
                _bbr_dec = BBReversalStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price),
                )
                if str(_bbr_dec.signal or "").upper() in ("BUY", "SELL"):
                    _attach_htf_debug(_bbr_dec, htf_snapshot)
                    return _apply_exec_entry(_bbr_dec)
        except Exception as _bbr_exc:
            record_exception("BB-REVERSAL", _bbr_exc)
            logger.warning("[BB-REVERSAL] evaluate error: %s", _bbr_exc)

    # ----------------------------------------------------------------
    # 0a) BRIEFING_LIQUIDITY — three-layer briefing-gated liquidity sweep
    #     (5M close only — replaces BRIEFING_SWEEP as primary strategy)
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from briefing_liquidity import BriefingLiquidityStrategy, BRIEFING_LIQUIDITY_ENABLED as _BL_ENABLED
            if _BL_ENABLED:
                _bl_briefing = None
                try:
                    _bl_briefing = morning_briefing.get_briefing(sym)
                except Exception as _bl_get_exc:
                    logger.warning("[BRIEFING-LIQ] %s get_briefing() raised %s — skipping", sym, _bl_get_exc)
                if _bl_briefing and isinstance(_bl_briefing, dict) and _bl_briefing.get("symbol"):
                    logger.debug("[BRIEFING-LIQ] %s briefing loaded: daily_bias=%s session_bias=%s conf=%s",
                                 sym, _bl_briefing.get('daily_bias'), _bl_briefing.get('session_bias'),
                                 _bl_briefing.get('bias_confidence'))
                    if not hasattr(evaluate_signals, "_bl_strat"):
                        evaluate_signals._bl_strat = BriefingLiquidityStrategy()
                    _bl_dec = evaluate_signals._bl_strat.evaluate(
                        sym, ep, df_in, pip_size, float(mid_price), _bl_briefing,
                    )
                    if str(_bl_dec.signal or "").upper() in ("BUY", "SELL"):
                        _attach_htf_debug(_bl_dec, htf_snapshot)
                        return _apply_exec_entry(_bl_dec)
                else:
                    logger.warning(
                        "⚠️ [BRIEFING-LIQ] %s NO BRIEFING — strategy disabled until briefing is generated. "
                        "Trades that depend on briefing levels will not fire.", sym
                    )
        except Exception as _bl_exc:
            record_exception("BRIEFING-LIQ", _bl_exc)
            logger.warning("[BRIEFING-LIQ] evaluate error: %s", _bl_exc)

    # ----------------------------------------------------------------
    # 0a-tick) BRIEFING_LIQUIDITY tick-level early arm
    #          (runs every tick, NOT gated by 5M close)
    # ----------------------------------------------------------------
    if not _is_new_5m:
        try:
            from briefing_liquidity import BRIEFING_LIQUIDITY_TICK_ARM_ENABLED as _BL_TICK_ENABLED
            if _BL_TICK_ENABLED and hasattr(evaluate_signals, "_bl_strat"):
                _bl_briefing_tick = None
                try:
                    _bl_briefing_tick = morning_briefing.get_briefing(sym)
                except Exception:
                    pass
                if _bl_briefing_tick and isinstance(_bl_briefing_tick, dict) and _bl_briefing_tick.get("symbol"):
                    _bl_tick_dec = evaluate_signals._bl_strat.tick_check_early_arm(
                        symbol=sym,
                        epic=ep,
                        mid_price=float(mid_price),
                        bid=float(bid_f),
                        ask=float(ask_f),
                        tick_ts=float(ts_epoch),
                        df_5m=df_in,
                        briefing=_bl_briefing_tick,
                    )
                    if _bl_tick_dec and str(_bl_tick_dec.signal or "").upper() in ("BUY", "SELL"):
                        _attach_htf_debug(_bl_tick_dec, htf_snapshot)
                        return _apply_exec_entry(_bl_tick_dec)
        except Exception as _blt_exc:
            record_exception("BRIEFING-LIQ-TICK", _blt_exc)
            logger.debug("[BRIEFING-LIQ-TICK] evaluate error: %s", _blt_exc)


    # ----------------------------------------------------------------
    # 0a3) WINDOW_SWEEP — BB touch + MACD histogram reducing → immediate entry
    # ----------------------------------------------------------------
    if _is_new_5m and _regime_allows("WINDOW_SWEEP"):
        try:
            from trade_manager import (
                WINDOW_SWEEP_ENABLED as _WS_ENABLED,
                BRIEFING_TP_SL_PIPS,
                BRIEFING_TP_SL_DEFAULT, select_tp_levels,
                check_window_sweep as _ws_check,
            )
            if _WS_ENABLED and df_in is not None and len(df_in) >= 20:
                _ws_briefing = None
                try:
                    _ws_briefing = morning_briefing.get_briefing(sym)
                except Exception:
                    pass

                _ws_last = df_in.iloc[-1]

                # Extract BB bands
                _ws_bb_up = None
                _ws_bb_lo = None
                for _k in ("BB_UPPER_20_2", "BB_UPPER"):
                    if _k in _ws_last.index:
                        _v = _ws_last[_k]
                        if _v is not None and _v == _v:
                            _ws_bb_up = float(_v); break
                for _k in ("BB_LOWER_20_2", "BB_LOWER"):
                    if _k in _ws_last.index:
                        _v = _ws_last[_k]
                        if _v is not None and _v == _v:
                            _ws_bb_lo = float(_v); break

                # Extract MACD histogram (3 candles BEFORE the pierce candle)
                _hist_key = f"MACD_HIST_{int(MACD_FAST)}_{int(MACD_SLOW)}_{int(MACD_SIGNAL)}"
                _ws_hist_vals = None
                if _hist_key in df_in.columns and len(df_in) >= 4:
                    try:
                        _ws_hist_vals = [float(df_in.iloc[i][_hist_key]) for i in range(-4, -1)]
                    except Exception:
                        pass

                _ws_ts = _ws_last.get("timestamp") or _ws_last.get("time")

                _ws_result = _ws_check(
                    sym=sym,
                    candle_ts=_ws_ts,
                    candle_high=float(_ws_last.get("high", 0)),
                    candle_low=float(_ws_last.get("low", 0)),
                    candle_close=float(_ws_last.get("close", 0)),
                    bb_upper=_ws_bb_up,
                    bb_lower=_ws_bb_lo,
                    macd_hist_vals=_ws_hist_vals,
                    briefing=_ws_briefing,
                )

                if _ws_result:
                    _ws_dir = _ws_result["direction"]
                    _ws_window = _ws_result["window"]
                    _ws_close = _ws_result["close"]
                    _ws_pair = sym.upper()
                    # Morning = scalp (TP+20/SL-15), Afternoon = runner (trail)
                    if _ws_window == "MORNING":
                        _ws_sl = 15.0
                    else:
                        _ws_sl = BRIEFING_TP_SL_PIPS.get(_ws_pair, BRIEFING_TP_SL_DEFAULT)

                    # Allow multiple entries per window: block if WS position open or cooldown active
                    import trade_executor as _te_ws
                    _ws_pos_open = any(
                        st.get("active") and st.get("mode") == "WINDOW_SWEEP"
                        for st in _te_ws.EPIC_STATE.values()
                    )
                    if not hasattr(evaluate_signals, "_ws_last_close"):
                        evaluate_signals._ws_last_close = {}
                    _ws_cooldown_key = sym.upper()
                    _ws_cooldown_elapsed = time.time() - evaluate_signals._ws_last_close.get(_ws_cooldown_key, 0)
                    _ws_blocked = _ws_pos_open or _ws_cooldown_elapsed < 3600
                    if _ws_blocked:
                        pass  # WS position open or within 60-min cooldown
                    else:

                        # Build briefing levels for TP selection
                        _ws_levels = []
                        if _ws_briefing and isinstance(_ws_briefing, dict):
                            for _src in ("key_levels", "major_levels"):
                                _d = _ws_briefing.get(_src, {})
                                _maj = _src == "major_levels"
                                for _v in _d.get("resistance", []):
                                    if _v is not None: _ws_levels.append({"price": float(_v), "level_type": "resistance", "source": _src, "major": _maj})
                                for _v in _d.get("support", []):
                                    if _v is not None: _ws_levels.append({"price": float(_v), "level_type": "support", "source": _src, "major": _maj})
                            _lp = _ws_briefing.get("liquidity_pools", {})
                            for _v in _lp.get("buy_side", []):
                                if _v is not None: _ws_levels.append({"price": float(_v), "level_type": "resistance", "source": "liq", "major": False})
                            for _v in _lp.get("sell_side", []):
                                if _v is not None: _ws_levels.append({"price": float(_v), "level_type": "support", "source": "liq", "major": False})

                        _ws_tp = select_tp_levels(_ws_close, _ws_dir, _ws_levels, _ws_pair)

                        logger.info(
                            "[WINDOW_SWEEP] %s %s %s ENTRY @ %.5f (BB=%.5f) "
                            "TP1=%.1fp TP2=%.1fp TP3=%.1fp SL=%.1fp",
                            sym, _ws_window, _ws_dir, _ws_close,
                            _ws_result["bb_band"],
                            _ws_tp["tp1_pips"], _ws_tp["tp2_pips"], _ws_tp["tp3_pips"], _ws_sl,
                        )

                        # Morning scalp: fixed TP 20p; Afternoon runner: briefing TP
                        _ws_tp_final = 20.0 if _ws_window == "MORNING" else _ws_tp["tp1_pips"]

                        _ws_dec = StrategyDecision(
                            symbol=sym,
                            regime="SWEEP",
                            signal=_ws_dir,
                            mode=WINDOW_SWEEP_MODE,
                            entry=_ws_close,
                            sl=_ws_sl,
                            tp=_ws_tp_final,
                            use_trailing_stop=False,
                            reason=f"window_sweep_{_ws_window.lower()}_{_ws_dir.lower()}",
                            debug={
                                "window": _ws_window,
                                "pierce_price": _ws_result["pierce_price"],
                                "bb_band": _ws_result["bb_band"],
                                "tp_plan": [
                                    {"pips": _ws_tp["tp1_pips"], "price": _ws_tp["tp1"], "source": "briefing_tp1"},
                                    {"pips": _ws_tp["tp2_pips"], "price": _ws_tp["tp2"], "source": "briefing_tp2"},
                                    {"pips": _ws_tp["tp3_pips"], "price": _ws_tp["tp3"], "source": "briefing_tp3"},
                                ],
                                "briefing_levels": _ws_levels,
                                "entry_source": f"window_sweep_{_ws_window.lower()}",
                            },
                        )
                        _attach_htf_debug(_ws_dec, htf_snapshot)
                        return _apply_exec_entry(_ws_dec)
        except Exception as _ws_exc:
            record_exception("WINDOW_SWEEP", _ws_exc)
            logger.warning("[WINDOW_SWEEP] evaluate error: %s", _ws_exc)

    # ----------------------------------------------------------------
    # 0b) BRIEFING_SWEEP — briefing-level sweep + rejection + confirmation
    #     (5M close only — evaluates closed candles from rc_all)
    # ----------------------------------------------------------------
    if _is_new_5m and _regime_allows("BRIEFING_SWEEP"):
        try:
            from briefing_sweep import BriefingSweepStrategy, BRIEFING_SWEEP_ENABLED as _BS_ENABLED
            _bs_pairs_raw = os.getenv("BRIEFING_SWEEP_PAIRS", "").strip()
            _bs_allowed_pairs = set(p.strip().upper() for p in _bs_pairs_raw.split(",") if p.strip()) if _bs_pairs_raw else None
            if _BS_ENABLED and (_bs_allowed_pairs is None or sym.upper() in _bs_allowed_pairs):
                _bs_briefing = None
                try:
                    _bs_briefing = morning_briefing.get_briefing(sym)
                except Exception as _bs_get_exc:
                    logger.warning("[BRIEFING-SWEEP] %s get_briefing() raised %s — skipping", sym, _bs_get_exc)
                if _bs_briefing and isinstance(_bs_briefing, dict) and _bs_briefing.get("symbol"):
                    _bs_session = str(_bs_briefing.get("session_bias", "")).upper()
                    _bs_daily = str(_bs_briefing.get("daily_bias", "")).upper()
                    _bs_eff = _bs_session if _bs_session in ("BULLISH", "BEARISH") else _bs_daily
                    logger.debug("[BRIEFING-SWEEP] %s briefing loaded: session_bias=%s daily_bias=%s effective=%s", sym, _bs_session or "N/A", _bs_daily or "N/A", _bs_eff or "NEUTRAL")
                else:
                    logger.warning(
                        "⚠️ [BRIEFING-SWEEP] %s NO BRIEFING — strategy disabled until briefing is generated.", sym
                    )
                if _bs_briefing and isinstance(_bs_briefing, dict) and _bs_briefing.get("symbol"):
                    _rc_all = list((snapshot_5m.get("recent_closed") or []))
                    if not hasattr(BriefingSweepStrategy, '_instance'):
                        BriefingSweepStrategy._instance = BriefingSweepStrategy()
                    _bs_dec = BriefingSweepStrategy._instance.evaluate(sym, ep, _rc_all, pip_size, float(mid_price), _bs_briefing)
                    if str(_bs_dec.signal or "").upper() in ("BUY", "SELL"):
                        # Build briefing levels + tp_plan so setup_briefing_tp() is invoked
                        _bs_levels = []
                        for _src in ("key_levels", "major_levels"):
                            _d = _bs_briefing.get(_src, {})
                            _maj = _src == "major_levels"
                            for _v in _d.get("resistance", []):
                                if _v is not None: _bs_levels.append({"price": float(_v), "level_type": "resistance", "source": _src, "major": _maj})
                            for _v in _d.get("support", []):
                                if _v is not None: _bs_levels.append({"price": float(_v), "level_type": "support", "source": _src, "major": _maj})
                        _lp = _bs_briefing.get("liquidity_pools", {})
                        for _v in _lp.get("buy_side", []):
                            if _v is not None: _bs_levels.append({"price": float(_v), "level_type": "resistance", "source": "liq", "major": False})
                        for _v in _lp.get("sell_side", []):
                            if _v is not None: _bs_levels.append({"price": float(_v), "level_type": "support", "source": "liq", "major": False})
                        _bs_tp = select_tp_levels(float(mid_price), _bs_dec.signal, _bs_levels, sym.upper())
                        if _bs_dec.debug is None:
                            _bs_dec.debug = {}
                        _bs_dec.debug["briefing_levels"] = _bs_levels
                        _bs_dec.debug["tp_plan"] = [
                            {"pips": _bs_tp["tp1_pips"], "price": _bs_tp["tp1"], "source": "briefing_tp1"},
                            {"pips": _bs_tp["tp2_pips"], "price": _bs_tp["tp2"], "source": "briefing_tp2"},
                            {"pips": _bs_tp["tp3_pips"], "price": _bs_tp["tp3"], "source": "briefing_tp3"},
                        ]
                        _bs_dec.tp = _bs_tp["tp1_pips"]
                        _attach_htf_debug(_bs_dec, htf_snapshot)
                        return _apply_exec_entry(_bs_dec)
        except Exception as _bs_exc:
            record_exception("BRIEFING-SWEEP", _bs_exc)
            logger.warning("[BRIEFING-SWEEP] evaluate error: %s", _bs_exc)

    # ----------------------------------------------------------------
    # 1) LIQUIDITY_SWEEP — BB pierce + reversal candle, no filters
    #    (5M close only)
    # ----------------------------------------------------------------
    _LIQUIDITY_SWEEP_ENABLED = str(os.getenv("LIQUIDITY_SWEEP_ENABLED", "1")).strip() in ("1", "true", "yes")
    if not _is_new_5m or not _LIQUIDITY_SWEEP_ENABLED or not _regime_allows("LIQUIDITY_SWEEP"):
        sweep_dec = StrategyDecision(sym, "SWEEP", "NONE", LIQUIDITY_SWEEP_MODE, None, None, None, True,
                                     "liquidity_sweep_disabled" if not _LIQUIDITY_SWEEP_ENABLED else "sweep_not_5m_close")
    else:
        sweep_dec = _edge_rejection_engine(symbol=sym, epic=ep, mid_price=float(mid_price), snapshot_5m=snapshot_5m, london_dt=london_dt)
    sweep_dec.debug = {
        **(sweep_dec.debug or {}),
        "london_time": london_dt.isoformat() if london_dt is not None else None,
        "bucket_ts_epoch": float(ts_epoch),
    }
    _attach_htf_debug(sweep_dec, htf_snapshot)

    if str(sweep_dec.signal or "").upper() in ("BUY", "SELL"):
        # Increment daily trade counter and persist to disk
        try:
            st2 = _EDGE_SWEEP_STATE.get(_state_key(sym, ep))
            if isinstance(st2, dict):
                st2["trades_today"] = int(st2.get("trades_today", 0) or 0) + 1
            _save_sweep_state_to_disk()
        except Exception:
            pass
        # Store pierce extreme for downstream
        try:
            _pre_clear_st = _EDGE_SWEEP_STATE.get(_state_key(sym, ep))
            if isinstance(_pre_clear_st, dict):
                _sx_sig = str(sweep_dec.signal or "").upper()
                _sx_val = _pre_clear_st.get("failure_high") if _sx_sig == "SELL" else _pre_clear_st.get("failure_low")
                if _sx_val is not None:
                    _LAST_SWEEP_EXTREME[_state_key(sym, ep)] = float(_sx_val)
        except Exception:
            pass
        _clear_sweep_state(sym, ep, keep_day=True)
        return _apply_exec_entry(sweep_dec)

    # NEWS_STRATEGY dispatch was hoisted to autobot._on_ls_tick so it
    # sits above the universal `if _in_blackout: return` gate — this
    # strategy is designed to trade DURING high-impact releases, which
    # is exactly when the gate would otherwise silence it. See
    # autobot.py around the NEWS_TICK block for the symmetric pattern.
    # DO NOT re-add a NEWS_STRATEGY dispatch here.

    # ----------------------------------------------------------------
    # 2) BRIEFING_HUNT — enter after briefing-predicted liquidity sweep
    #    (tick-level arm + 5M confirmation — 06:45-17:00 BST)
    # ----------------------------------------------------------------
    try:
        from briefing_hunt import (
            BriefingHuntStrategy,
            BRIEFING_HUNT_ENABLED as _BH_ENABLED,
            ALLOWED_PAIRS as _BH_PAIRS,
        )
        if _BH_ENABLED and sym.upper() in _BH_PAIRS:
            _bh_briefing = None
            try:
                _bh_briefing = morning_briefing.get_briefing(sym)
            except Exception:
                pass
            if _bh_briefing and isinstance(_bh_briefing, dict) and _bh_briefing.get("symbol"):
                if not hasattr(BriefingHuntStrategy, '_instance'):
                    BriefingHuntStrategy._instance = BriefingHuntStrategy()
                BriefingHuntStrategy._instance.tick_update_sweep_extreme(ep, float(mid_price))
                _bh_rc_all = list((snapshot_5m.get("recent_closed") or []))
                _bh_dec = BriefingHuntStrategy._instance.evaluate(
                    sym, ep, float(mid_price), pip_size, _bh_briefing,
                    is_new_5m=_is_new_5m, rc_all=_bh_rc_all,
                )
                if str(_bh_dec.signal or "").upper() in ("BUY", "SELL"):
                    _bh_levels = []
                    for _src in ("key_levels", "major_levels"):
                        _d = _bh_briefing.get(_src, {})
                        _maj = _src == "major_levels"
                        for _v in _d.get("resistance", []):
                            if _v is not None: _bh_levels.append({"price": float(_v), "level_type": "resistance", "source": _src, "major": _maj})
                        for _v in _d.get("support", []):
                            if _v is not None: _bh_levels.append({"price": float(_v), "level_type": "support", "source": _src, "major": _maj})
                    _bh_liq = _bh_briefing.get("liquidity_pools", {})
                    for _v in _bh_liq.get("buy_side", []):
                        if _v is not None: _bh_levels.append({"price": float(_v), "level_type": "resistance", "source": "liq", "major": False})
                    for _v in _bh_liq.get("sell_side", []):
                        if _v is not None: _bh_levels.append({"price": float(_v), "level_type": "support", "source": "liq", "major": False})
                    _bh_tp = select_tp_levels(float(mid_price), _bh_dec.signal, _bh_levels, sym.upper())
                    if _bh_dec.debug is None:
                        _bh_dec.debug = {}
                    _bh_dec.debug["briefing_levels"] = _bh_levels
                    _bh_dec.debug["tp_plan"] = [
                        {"pips": _bh_tp["tp1_pips"], "price": _bh_tp["tp1"], "source": "briefing_tp1"},
                        {"pips": _bh_tp["tp2_pips"], "price": _bh_tp["tp2"], "source": "briefing_tp2"},
                        {"pips": _bh_tp["tp3_pips"], "price": _bh_tp["tp3"], "source": "briefing_tp3"},
                    ]
                    _bh_dec.tp = _bh_tp["tp1_pips"]
                    _attach_htf_debug(_bh_dec, htf_snapshot)
                    return _apply_exec_entry(_bh_dec)
    except Exception as _bh_exc:
        record_exception("BRIEFING-HUNT", _bh_exc)
        logger.warning("[BRIEFING-HUNT] evaluate error: %s", _bh_exc)

    # ----------------------------------------------------------------
    # 2b) REVERSAL_SWEEP — BB extreme reversal (5M close only)
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from reversal_sweep import (
                ReversalSweepStrategy,
                REVERSAL_SWEEP_ENABLED as _RSWE_ENABLED,
                ALLOWED_PAIRS as _RSWE_PAIRS,
            )
            if _RSWE_ENABLED and sym.upper() in _RSWE_PAIRS and df_in is not None and len(df_in) >= 25:
                _rswe_briefing = None
                try:
                    _rswe_briefing = morning_briefing.get_briefing(sym)
                except Exception:
                    pass
                if not hasattr(ReversalSweepStrategy, '_instance'):
                    ReversalSweepStrategy._instance = ReversalSweepStrategy()
                _rswe_dec = ReversalSweepStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price),
                    _rswe_briefing if _rswe_briefing and isinstance(_rswe_briefing, dict) else {},
                )
                if str(_rswe_dec.signal or "").upper() in ("BUY", "SELL"):
                    _rswe_levels = []
                    if _rswe_briefing and isinstance(_rswe_briefing, dict):
                        for _src in ("key_levels", "major_levels"):
                            _d = _rswe_briefing.get(_src, {})
                            _maj = _src == "major_levels"
                            for _v in _d.get("resistance", []):
                                if _v is not None: _rswe_levels.append({"price": float(_v), "level_type": "resistance", "source": _src, "major": _maj})
                            for _v in _d.get("support", []):
                                if _v is not None: _rswe_levels.append({"price": float(_v), "level_type": "support", "source": _src, "major": _maj})
                        _rswe_liq = _rswe_briefing.get("liquidity_pools", {})
                        for _v in _rswe_liq.get("buy_side", []):
                            if _v is not None: _rswe_levels.append({"price": float(_v), "level_type": "resistance", "source": "liq", "major": False})
                        for _v in _rswe_liq.get("sell_side", []):
                            if _v is not None: _rswe_levels.append({"price": float(_v), "level_type": "support", "source": "liq", "major": False})
                    _rswe_tp = select_tp_levels(float(mid_price), _rswe_dec.signal, _rswe_levels, sym.upper())
                    if _rswe_dec.debug is None:
                        _rswe_dec.debug = {}
                    _rswe_dec.debug["briefing_levels"] = _rswe_levels
                    _rswe_dec.debug["tp_plan"] = [
                        {"pips": _rswe_tp["tp1_pips"], "price": _rswe_tp["tp1"], "source": "briefing_tp1"},
                        {"pips": _rswe_tp["tp2_pips"], "price": _rswe_tp["tp2"], "source": "briefing_tp2"},
                        {"pips": _rswe_tp["tp3_pips"], "price": _rswe_tp["tp3"], "source": "briefing_tp3"},
                    ]
                    _rswe_dec.tp = _rswe_tp["tp1_pips"]
                    _attach_htf_debug(_rswe_dec, htf_snapshot)
                    return _apply_exec_entry(_rswe_dec)
        except Exception as _rswe_exc:
            record_exception("REVERSAL-SWEEP", _rswe_exc)
            logger.warning("[REVERSAL-SWEEP] evaluate error: %s", _rswe_exc)

    # ----------------------------------------------------------------
    # 2c) CONTINUATION_SWEEP — BB extreme trend continuation (5M close only)
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from continuation_sweep import (
                ContinuationSweepStrategy,
                CONTINUATION_SWEEP_ENABLED as _CSWE_ENABLED,
                ALLOWED_PAIRS as _CSWE_PAIRS,
            )
            if _CSWE_ENABLED and sym.upper() in _CSWE_PAIRS and df_in is not None and len(df_in) >= 25:
                # Skip if a CONTINUATION_SWEEP position for this epic is
                # already open — re-evaluating produces repeat decisions
                # that execute_trade blocks at pos_key level, and used to
                # leak phantom signal_log rows via the ambiguous "opened"
                # check in autobot.py (fixed above). Short-circuiting here
                # is belt-and-braces: silences the re-eval noise and keeps
                # the dispatch fast while a position is live.
                try:
                    from trade_executor import has_active_trade_for_mode as _cswe_active
                    if _cswe_active(ep, "CONTINUATION_SWEEP"):
                        return StrategyDecision(
                            symbol=sym, regime="DISPATCH", signal="NONE",
                            mode="CONTINUATION_SWEEP", entry=None, sl=None, tp=None,
                            use_trailing_stop=False,
                            reason="continuation_sweep_position_active",
                        )
                except Exception:
                    pass
                _cswe_briefing = None
                try:
                    _cswe_briefing = morning_briefing.get_briefing(sym)
                except Exception:
                    pass
                if not hasattr(ContinuationSweepStrategy, '_instance'):
                    ContinuationSweepStrategy._instance = ContinuationSweepStrategy()
                _cswe_dec = ContinuationSweepStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price),
                    _cswe_briefing if _cswe_briefing and isinstance(_cswe_briefing, dict) else {},
                )
                if str(_cswe_dec.signal or "").upper() in ("BUY", "SELL"):
                    _cswe_levels = []
                    if _cswe_briefing and isinstance(_cswe_briefing, dict):
                        for _src in ("key_levels", "major_levels"):
                            _d = _cswe_briefing.get(_src, {})
                            _maj = _src == "major_levels"
                            for _v in _d.get("resistance", []):
                                if _v is not None: _cswe_levels.append({"price": float(_v), "level_type": "resistance", "source": _src, "major": _maj})
                            for _v in _d.get("support", []):
                                if _v is not None: _cswe_levels.append({"price": float(_v), "level_type": "support", "source": _src, "major": _maj})
                        _cswe_liq = _cswe_briefing.get("liquidity_pools", {})
                        for _v in _cswe_liq.get("buy_side", []):
                            if _v is not None: _cswe_levels.append({"price": float(_v), "level_type": "resistance", "source": "liq", "major": False})
                        for _v in _cswe_liq.get("sell_side", []):
                            if _v is not None: _cswe_levels.append({"price": float(_v), "level_type": "support", "source": "liq", "major": False})
                    _cswe_tp = select_tp_levels(float(mid_price), _cswe_dec.signal, _cswe_levels, sym.upper())
                    if _cswe_dec.debug is None:
                        _cswe_dec.debug = {}
                    _cswe_dec.debug["briefing_levels"] = _cswe_levels
                    _cswe_dec.debug["tp_plan"] = [
                        {"pips": _cswe_tp["tp1_pips"], "price": _cswe_tp["tp1"], "source": "briefing_tp1"},
                        {"pips": _cswe_tp["tp2_pips"], "price": _cswe_tp["tp2"], "source": "briefing_tp2"},
                        {"pips": _cswe_tp["tp3_pips"], "price": _cswe_tp["tp3"], "source": "briefing_tp3"},
                    ]
                    _cswe_dec.tp = _cswe_tp["tp1_pips"]
                    _attach_htf_debug(_cswe_dec, htf_snapshot)
                    return _apply_exec_entry(_cswe_dec)
        except Exception as _cswe_exc:
            record_exception("CONTINUATION-SWEEP", _cswe_exc)
            logger.warning("[CONTINUATION-SWEEP] evaluate error: %s", _cswe_exc)

    # ----------------------------------------------------------------
    # 2d) EXHAUSTION_REVERSAL — BB lower + RSI3 capitulation in uptrend
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from exhaustion_reversal import (
                ExhaustionReversalStrategy,
                EXHAUSTION_REVERSAL_ENABLED as _EXR_ENABLED,
                ALLOWED_PAIRS as _EXR_PAIRS,
            )
            if _EXR_ENABLED and sym.upper() in _EXR_PAIRS and df_in is not None and len(df_in) >= 55:
                _exr_briefing = None
                try:
                    _exr_briefing = morning_briefing.get_briefing(sym)
                except Exception:
                    pass
                if not hasattr(ExhaustionReversalStrategy, '_instance'):
                    ExhaustionReversalStrategy._instance = ExhaustionReversalStrategy()
                _exr_dec = ExhaustionReversalStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price),
                    _exr_briefing if _exr_briefing and isinstance(_exr_briefing, dict) else {},
                )
                if str(_exr_dec.signal or "").upper() in ("BUY", "SELL"):
                    _attach_htf_debug(_exr_dec, htf_snapshot)
                    return _apply_exec_entry(_exr_dec)
        except Exception as _exr_exc:
            record_exception("EXHAUSTION-REVERSAL", _exr_exc)
            logger.warning("[EXHAUSTION-REVERSAL] evaluate error: %s", _exr_exc)

    # ----------------------------------------------------------------
    # 2e) SESSION_IMPULSE_BREAKOUT — BB breach with EMA stack flip in ≤2 bars
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from session_impulse_breakout import (
                SessionImpulseBreakoutStrategy,
                SESSION_IMPULSE_BREAKOUT_ENABLED as _SIB_ENABLED,
                ALLOWED_PAIRS as _SIB_PAIRS,
            )
            if _SIB_ENABLED and sym.upper() in _SIB_PAIRS and df_in is not None and len(df_in) >= 25:
                _sib_briefing = None
                try:
                    _sib_briefing = morning_briefing.get_briefing(sym)
                except Exception:
                    pass
                if not hasattr(SessionImpulseBreakoutStrategy, '_instance'):
                    SessionImpulseBreakoutStrategy._instance = SessionImpulseBreakoutStrategy()
                _sib_dec = SessionImpulseBreakoutStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price),
                    _sib_briefing if _sib_briefing and isinstance(_sib_briefing, dict) else {},
                )
                if str(_sib_dec.signal or "").upper() in ("BUY", "SELL"):
                    _attach_htf_debug(_sib_dec, htf_snapshot)
                    return _apply_exec_entry(_sib_dec)
        except Exception as _sib_exc:
            record_exception("SESSION-IMPULSE-BREAKOUT", _sib_exc)
            logger.warning("[SESSION-IMPULSE-BREAKOUT] evaluate error: %s", _sib_exc)

    # ----------------------------------------------------------------
    # 2f) RSI_EXTREME_FADE — full-search portfolio pilot
    #     RSI(14) breach → fade. Configs: RSI_FADE_GBPUSD_SHORT,
    #     RSI_FADE_USDJPY_LONG. Universal blackouts (news, briefing
    #     invalidation, concurrent caps) are honoured downstream by
    #     _apply_exec_entry / trade_executor — NO additional gates here
    #     (search EV estimates assumed unrestricted firing).
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from rsi_extreme_fade import (
                RsiExtremeFadeStrategy,
                RSI_EXTREME_FADE_ENABLED as _REF_ENABLED,
                ALLOWED_PAIRS as _REF_PAIRS,
            )
            if _REF_ENABLED and sym.upper() in _REF_PAIRS and df_in is not None and len(df_in) >= 16:
                if not hasattr(RsiExtremeFadeStrategy, "_instance") or RsiExtremeFadeStrategy._instance is None:
                    RsiExtremeFadeStrategy._instance = RsiExtremeFadeStrategy()
                _ref_dec = RsiExtremeFadeStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price), {},
                )
                if str(_ref_dec.signal or "").upper() in ("BUY", "SELL"):
                    _attach_htf_debug(_ref_dec, htf_snapshot)
                    return _apply_exec_entry(_ref_dec)
        except Exception as _ref_exc:
            record_exception("RSI-EXTREME-FADE", _ref_exc)
            logger.warning("[RSI-EXTREME-FADE] evaluate error: %s", _ref_exc)

    # ----------------------------------------------------------------
    # 2g) MACD_EXTREME_FADE — full-search portfolio pilot
    #     MACD line(12,26) breach → fade. Config: MACD_EXTREME_GBPUSD_LONG.
    #     Same gating posture as 2f (universal blackouts only).
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from macd_extreme_fade import (
                MacdExtremeFadeStrategy,
                MACD_EXTREME_FADE_ENABLED as _MEF_ENABLED,
                ALLOWED_PAIRS as _MEF_PAIRS,
            )
            if _MEF_ENABLED and sym.upper() in _MEF_PAIRS and df_in is not None and len(df_in) >= 30:
                if not hasattr(MacdExtremeFadeStrategy, "_instance") or MacdExtremeFadeStrategy._instance is None:
                    MacdExtremeFadeStrategy._instance = MacdExtremeFadeStrategy()
                _mef_dec = MacdExtremeFadeStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price), {},
                )
                if str(_mef_dec.signal or "").upper() in ("BUY", "SELL"):
                    _attach_htf_debug(_mef_dec, htf_snapshot)
                    return _apply_exec_entry(_mef_dec)
        except Exception as _mef_exc:
            record_exception("MACD-EXTREME-FADE", _mef_exc)
            logger.warning("[MACD-EXTREME-FADE] evaluate error: %s", _mef_exc)

    # ----------------------------------------------------------------
    # 2h) BB_PATTERN2_FADE — Phase-6 P2 strict/loose pilot
    #     BB pierce (wick-only) + N+1 confirmation. Configs:
    #         P2_EURUSD_A (strict, paper-trade-equivalent fwd-walk),
    #         P2_USDJPY_B (loose), P2_USDCAD_A (strict).
    #     SL=12 TP=30 8-bar horizon. Same gating posture as 2f/2g
    #     (universal blackouts only — Phase 6 EV estimates assumed
    #     unrestricted firing).
    # ----------------------------------------------------------------
    if _is_new_5m:
        try:
            from bb_pattern2_fade import (
                BBPattern2FadeStrategy,
                BB_PATTERN2_FADE_ENABLED as _BBP2_ENABLED,
                ALLOWED_PAIRS as _BBP2_PAIRS,
                MIN_BARS as _BBP2_MIN_BARS,
            )
            if (_BBP2_ENABLED and sym.upper() in _BBP2_PAIRS
                    and df_in is not None and len(df_in) >= _BBP2_MIN_BARS):
                if (not hasattr(BBPattern2FadeStrategy, "_instance")
                        or BBPattern2FadeStrategy._instance is None):
                    BBPattern2FadeStrategy._instance = BBPattern2FadeStrategy()
                _bbp2_dec = BBPattern2FadeStrategy._instance.evaluate(
                    sym, ep, df_in, pip_size, float(mid_price), {},
                )
                if str(_bbp2_dec.signal or "").upper() in ("BUY", "SELL"):
                    _attach_htf_debug(_bbp2_dec, htf_snapshot)
                    return _apply_exec_entry(_bbp2_dec)
        except Exception as _bbp2_exc:
            record_exception("BB-PATTERN2-FADE", _bbp2_exc)
            logger.warning("[BB-PATTERN2-FADE] evaluate error: %s", _bbp2_exc)

    # ----------------------------------------------------------------
    # 3) LONDON_PULLBACK — EMA pullback after London open thrust
    #    (5M close only — 07:00-10:00 BST)
    # ----------------------------------------------------------------
    if _is_new_5m and _regime_allows("LONDON_PULLBACK"):
        try:
            from london_open_pullback import (
                LondonOpenPullbackStrategy,
                LONDON_PULLBACK_ENABLED as _LP_ENABLED,
                ALLOWED_PAIRS as _LP_PAIRS,
            )
            if _LP_ENABLED and sym.upper() in _LP_PAIRS and df_in is not None and len(df_in) >= 20:
                _lp_briefing = None
                try:
                    _lp_briefing = morning_briefing.get_briefing(sym)
                except Exception:
                    pass
                if _lp_briefing and isinstance(_lp_briefing, dict) and _lp_briefing.get("symbol"):
                    if not hasattr(LondonOpenPullbackStrategy, '_instance'):
                        LondonOpenPullbackStrategy._instance = LondonOpenPullbackStrategy()
                    _lp_dec = LondonOpenPullbackStrategy._instance.evaluate(
                        sym, ep, df_in, pip_size, float(mid_price), _lp_briefing,
                    )
                    if str(_lp_dec.signal or "").upper() in ("BUY", "SELL"):
                        _lp_levels = []
                        for _src in ("key_levels", "major_levels"):
                            _d = _lp_briefing.get(_src, {})
                            _maj = _src == "major_levels"
                            for _v in _d.get("resistance", []):
                                if _v is not None: _lp_levels.append({"price": float(_v), "level_type": "resistance", "source": _src, "major": _maj})
                            for _v in _d.get("support", []):
                                if _v is not None: _lp_levels.append({"price": float(_v), "level_type": "support", "source": _src, "major": _maj})
                        _lp_liq = _lp_briefing.get("liquidity_pools", {})
                        for _v in _lp_liq.get("buy_side", []):
                            if _v is not None: _lp_levels.append({"price": float(_v), "level_type": "resistance", "source": "liq", "major": False})
                        for _v in _lp_liq.get("sell_side", []):
                            if _v is not None: _lp_levels.append({"price": float(_v), "level_type": "support", "source": "liq", "major": False})
                        _lp_tp = select_tp_levels(float(mid_price), _lp_dec.signal, _lp_levels, sym.upper())
                        if _lp_dec.debug is None:
                            _lp_dec.debug = {}
                        _lp_dec.debug["briefing_levels"] = _lp_levels
                        _lp_dec.debug["tp_plan"] = [
                            {"pips": _lp_tp["tp1_pips"], "price": _lp_tp["tp1"], "source": "briefing_tp1"},
                            {"pips": _lp_tp["tp2_pips"], "price": _lp_tp["tp2"], "source": "briefing_tp2"},
                            {"pips": _lp_tp["tp3_pips"], "price": _lp_tp["tp3"], "source": "briefing_tp3"},
                        ]
                        _lp_dec.tp = _lp_tp["tp1_pips"]
                        _attach_htf_debug(_lp_dec, htf_snapshot)
                        return _apply_exec_entry(_lp_dec)
        except Exception as _lp_exc:
            record_exception("LONDON-PULLBACK", _lp_exc)
            logger.warning("[LONDON-PULLBACK] evaluate error: %s", _lp_exc)

    # ----------------------------------------------------------------
    # 4) EMA_PULLBACK — EMA_8 pullback continuation in established trends
    #    (5M close only — London + NY sessions)
    # ----------------------------------------------------------------
    if _is_new_5m and _regime_allows("EMA_PULLBACK") and not _router_manages("EMA_PULLBACK", sym):
        try:
            from ema_pullback import EmaPullbackStrategy, EMA_PULLBACK_ENABLED as _EP_ENABLED
            if _EP_ENABLED and df_in is not None and len(df_in) >= 50:
                _ep_briefing = None
                try:
                    _ep_briefing = morning_briefing.get_briefing(sym)
                except Exception:
                    pass
                if _ep_briefing and isinstance(_ep_briefing, dict) and _ep_briefing.get("symbol"):
                    if not hasattr(EmaPullbackStrategy, '_instance'):
                        EmaPullbackStrategy._instance = EmaPullbackStrategy()
                    _ep_dec = EmaPullbackStrategy._instance.evaluate(
                        sym, ep, df_in, pip_size, float(mid_price), _ep_briefing,
                    )
                    if str(_ep_dec.signal or "").upper() in ("BUY", "SELL"):
                        _ep_levels = []
                        for _src in ("key_levels", "major_levels"):
                            _d = _ep_briefing.get(_src, {})
                            _maj = _src == "major_levels"
                            for _v in _d.get("resistance", []):
                                if _v is not None: _ep_levels.append({"price": float(_v), "level_type": "resistance", "source": _src, "major": _maj})
                            for _v in _d.get("support", []):
                                if _v is not None: _ep_levels.append({"price": float(_v), "level_type": "support", "source": _src, "major": _maj})
                        _ep_liq = _ep_briefing.get("liquidity_pools", {})
                        for _v in _ep_liq.get("buy_side", []):
                            if _v is not None: _ep_levels.append({"price": float(_v), "level_type": "resistance", "source": "liq", "major": False})
                        for _v in _ep_liq.get("sell_side", []):
                            if _v is not None: _ep_levels.append({"price": float(_v), "level_type": "support", "source": "liq", "major": False})
                        _ep_tp = select_tp_levels(float(mid_price), _ep_dec.signal, _ep_levels, sym.upper())
                        if _ep_dec.debug is None:
                            _ep_dec.debug = {}
                        _ep_dec.debug["briefing_levels"] = _ep_levels
                        _ep_dec.debug["tp_plan"] = [
                            {"pips": _ep_tp["tp1_pips"], "price": _ep_tp["tp1"], "source": "briefing_tp1"},
                            {"pips": _ep_tp["tp2_pips"], "price": _ep_tp["tp2"], "source": "briefing_tp2"},
                            {"pips": _ep_tp["tp3_pips"], "price": _ep_tp["tp3"], "source": "briefing_tp3"},
                        ]
                        _ep_dec.tp = _ep_tp["tp1_pips"]
                        _attach_htf_debug(_ep_dec, htf_snapshot)
                        return _apply_exec_entry(_ep_dec)
        except Exception as _ep_exc:
            record_exception("EMA-PULLBACK", _ep_exc)
            logger.warning("[EMA-PULLBACK] evaluate error: %s", _ep_exc)

    # No signal from any strategy
    dec = StrategyDecision(sym, "DISPATCH", "NONE", DISPATCH_MODE, None, None, None, True, "no_signal", {
        "london_time": london_dt.isoformat() if london_dt is not None else None,
        "sweep_reason": str(sweep_dec.reason or ""),
    })
    _attach_htf_debug(dec, htf_snapshot)
    return dec


def detect_regime(symbol: str, *_args: Any, **_kwargs: Any) -> str:
    return "DISPATCH"
