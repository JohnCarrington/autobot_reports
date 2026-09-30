# -*- coding: utf-8 -*-
"""
regime_classifier.py — Market Regime Engine (Production, Adaptive)

Implements:
1) RegimeClassifier (tick-based) — legacy support (kept compatible)
2) CandleRegimeClassifier (5m-close, OHLC) — USED by strategy_logic dispatcher

Stable regimes returned to consumers (stable/hysteresis output):
    "TREND_UP", "TREND_DOWN", "RANGE", "NEUTRAL"

Note on STRONG_*:
- The classifier may compute RAW regimes like "STRONG_TREND_UP" / "STRONG_TREND_DOWN" for diagnostics.
- The *stable* regime returned is canonicalized to the 4 labels above (STRONG_* -> TREND_*).

PRE-CHECK (House rules / Continual Errors / Contracts):
- #24/#104: NO price normalization; all prices remain IG native units (points).
- #106: StrategyDecision.sl/tp are pip distances (not used here, but preserved as invariant).
- #111: Pip size = points per pip; conversions happen exactly once (points->pips = points/pip_size).
- #97: Warmup must stay within IG limits (TODAY ~20, CFD ~50) — this classifier adapts to short histories.
- No pandas MINUTE offsets (#13/#22): no resampling / to_offset usage.
Scope: rewrite regime classification behavior to be effective (no unrelated refactors).
"""

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

# Phase 4B shadow classifier persistence (added 2026-04-28). Append-only,
# best-effort, no behavioural impact on strategies — failures are swallowed.
# TODO: add daily rotation if file size becomes a concern (~5 MB/day across
# 4 pairs at 5m cadence).
_REGIME_SHADOW_LOG = Path("/opt/tradingbot/logs/regime_shadow.jsonl")

# Provenance tagging for shadow rows (Stage 1.5, 2026-05-21). Every row carries
# a `source` field so offline analysis/replay/backtest writes can never again
# be mistaken for live production output — the root cause of the 2026-05-09
# GBPUSD contamination block. The live service sets REGIME_SHADOW_SOURCE=live
# in its environment (via .env, loaded by systemd EnvironmentFile) BEFORE this
# module is imported; any process that imports the classifier without setting
# it is tagged "analysis" automatically. The value is resolved at write-time,
# so import ordering cannot defeat it.
_VALID_SHADOW_SOURCES = ("live", "replay", "analysis")
_DEFAULT_SHADOW_SOURCE = "analysis"


def _resolve_shadow_source() -> str:
    """Return the provenance tag for shadow rows: 'live', 'replay' or
    'analysis'. Reads REGIME_SHADOW_SOURCE from the environment; any unset or
    unrecognised value falls back to 'analysis' so offline contamination is
    self-labelling rather than silent."""
    val = (os.environ.get("REGIME_SHADOW_SOURCE") or "").strip().lower()
    if val in _VALID_SHADOW_SOURCES:
        return val
    return _DEFAULT_SHADOW_SOURCE


def build_regime_state_for_debug(stable: Optional[str],
                                  out: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the dict that strategies stash in StrategyDecision.debug["regime_state"].

    This is the SINGLE source of truth for what regime fields end up in
    signal_log.jsonl at fire-time. signal_logger.log_open reads exactly
    these keys (with None fallback for any missing field), so adding a
    field here means widening the SL schema; renaming a field means a
    SL-schema break.

    Five fields, each pulled from the (stable, out) tuple returned by
    CandleRegimeClassifier.update_from_df:
      cascade_stable_at_fire        — the cascade-hysteresis label
      shadow_vote_label_at_fire     — the vote-count classifier label
      shadow_vote_confidence_at_fire — overall confidence (HIGH/MED/LOW)
      axis_confidence_direction     — direction-axis confidence
      axis_confidence_structure     — structure-axis confidence

    Returns an empty dict if `out` is unusable; caller should still
    attach it (signal_logger handles missing keys → null fields).
    """
    state: Dict[str, Any] = {
        "cascade_stable_at_fire": stable,
        "shadow_vote_label_at_fire": None,
        "shadow_vote_confidence_at_fire": None,
        "axis_confidence_direction": None,
        "axis_confidence_structure": None,
    }
    if isinstance(out, dict):
        shadow = out.get("shadow") or {}
        if isinstance(shadow, dict):
            state["shadow_vote_label_at_fire"] = shadow.get("label")
            state["shadow_vote_confidence_at_fire"] = shadow.get("confidence")
            cb = shadow.get("confidence_breakdown") or {}
            if isinstance(cb, dict):
                state["axis_confidence_direction"] = cb.get("direction")
                state["axis_confidence_structure"] = cb.get("structure")
    return state


def _write_shadow_row(symbol: str, stable: Optional[str],
                       out: Optional[Dict[str, Any]],
                       bar_ts: Optional[str] = None) -> None:
    """Append one classifier output row to regime_shadow.jsonl.
    Captures stable label + the full shadow vote/feature breakdown so the
    operator can review the classifier qualitatively before deciding
    whether to gate strategies on its calls.

    `bar_ts` is the timestamp of the candle being classified, distinct from
    the wall-clock `ts` write time. Together with the `source` provenance tag
    it makes replay/backtest writes trivially separable from live output: a
    replay run shows a recent `ts` against a much older `bar_ts`."""
    try:
        if not isinstance(out, dict):
            return
        shadow = out.get("shadow") or {}
        features = shadow.get("features") if isinstance(shadow, dict) else None
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "bar_ts": bar_ts,
            "source": _resolve_shadow_source(),
            "symbol": str(symbol or "").upper(),
            "stable": stable,
            "shadow_label": shadow.get("label") if isinstance(shadow, dict) else None,
            "shadow_confidence": shadow.get("confidence") if isinstance(shadow, dict) else None,
            "confidence_breakdown": shadow.get("confidence_breakdown") if isinstance(shadow, dict) else None,
            "votes": shadow.get("votes") if isinstance(shadow, dict) else None,
            "features": features,
            "transition_reasons": out.get("transition_reasons"),
            "transition_watch": out.get("transition_watch"),
        }
        _REGIME_SHADOW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _REGIME_SHADOW_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        # Phase 4 invariant probe — flag mid-enrichment races between the
        # classifier's in-memory dataframe view and what the candle
        # buffer file persisted for the same bar. Documented benign in
        # reports/phase4_data_capture_audit_20260508.md (§ Anomaly 1);
        # this catches the divergence WHEN it next happens so we have
        # current evidence rather than re-investigating from cold logs.
        # Soft: WARNING only, never blocks the write or raises.
        try:
            _check_ema_stack_invariant(symbol, features)
        except Exception:
            pass
    except Exception:
        # Never propagate — classifier output is the primary product, the
        # log is a best-effort side channel.
        pass


def _check_ema_stack_invariant(symbol: str,
                                features: Optional[Dict[str, Any]]) -> None:
    """Compare shadow features.ema_stack_state to the latest CSV row's
    EMA_STACK_STATE for the same pair. Log WARNING on divergence."""
    if not isinstance(features, dict):
        return
    shadow_ess = features.get("ema_stack_state")
    if shadow_ess is None:
        return
    sym_u = str(symbol or "").upper()
    if not sym_u:
        return
    csv_path = Path(f"/opt/tradingbot/cache/{sym_u}_candles.csv")
    if not csv_path.exists():
        return
    try:
        # Read just the last line's EMA_STACK_STATE column. Use a small
        # buffered tail rather than loading the whole 600-row file.
        with csv_path.open("rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            chunk = min(4096, file_size)
            f.seek(file_size - chunk)
            tail = f.read().decode("utf-8", errors="replace")
        last_line = tail.rstrip("\n").rsplit("\n", 1)[-1]
        if "," not in last_line:
            return
        # EMA_STACK_STATE is column 40 (1-indexed) per
        # candle_builder.py; defensive split in case schema shifts.
        cols = last_line.split(",")
        if len(cols) < 40:
            return
        csv_ess = cols[39].strip().strip('"')
        if not csv_ess:
            return
        if csv_ess != str(shadow_ess):
            import logging as _logging
            _logger = _logging.getLogger("AutoBot")
            _logger.warning(
                "[regime_classifier] EMA_STACK_STATE divergence on %s: "
                "shadow=%r CSV=%r — mid-enrichment race (audit §5 anomaly 1). "
                "Shadow log is authoritative; CSV is sparse-by-design.",
                sym_u, shadow_ess, csv_ess,
            )
    except Exception:
        # Never propagate — diagnostic check only.
        return

# ============================================================
# TICK CLASSIFIER CONFIG (legacy, kept compatible)
# ============================================================

VOL_WIN = 20
VOL_HIST_WIN = 500

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 100

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BB_TICKS = 100
NUM_STD = 2

# Hysteresis (tick engine)
REGIME_CONFIRM = 3
TREND_EXIT_CONFIRM = 4


def _ema(prev, x, span):
    if prev is None:
        return x
    alpha = 2.0 / (span + 1.0)
    return prev + alpha * (x - prev)


class RegimeClassifier:
    """
    Tick regime classifier (legacy compatibility).
    Signature:
      - __init__(epic: str, pip_size: float = 1.0)
      - update(mid: float, ts: Optional[float] = None) -> (stable_regime: str, components: dict)
      - classify() -> (stable_regime: str, components: dict)

    Notes:
    - This engine is NOT the dispatcher’s primary source in your current strategy flow.
    - It is retained for compatibility, but now uses adaptive width/slope gates
      (instead of brittle absolute WIDTH_* constants).
    """

    def __init__(self, epic: str, pip_size: float = 1.0):
        self.epic = epic
        self.pip_size = float(pip_size) if pip_size else 1.0

        self.window = deque(maxlen=BB_TICKS)
        self.vol_window = deque(maxlen=VOL_WIN)
        self.vol_history = deque(maxlen=VOL_HIST_WIN)

        self.ema_fast = None
        self.ema_mid = None
        self.ema_slow = None

        self.ema_price_fast = None
        self.ema_price_slow = None
        self.macd = None
        self.macd_signal = None
        self.macd_hist = None

        self.last_ts = None
        self.dt_window = deque(maxlen=VOL_WIN)

        self.bb_mid_hist = deque(maxlen=25)
        self.slope_hist = deque(maxlen=60)
        self.width_hist = deque(maxlen=60)

        self.regime = "NEUTRAL"
        self.regime_candidate = None
        self.regime_streak = 0

    def update(self, mid: float, ts: float = None):
        try:
            mid = float(mid)
        except Exception:
            return self.regime, {"warmup": True, "reason": "mid_not_float"}

        if ts is None:
            ts = time.time()

        if self.last_ts is not None:
            dt = ts - self.last_ts
            if dt > 0:
                self.dt_window.append(dt)
        self.last_ts = ts

        if len(self.window) > 0:
            diff = abs(mid - self.window[-1])
            self.vol_window.append(diff)
            self.vol_history.append(diff)

        self.window.append(mid)

        self.ema_fast = _ema(self.ema_fast, mid, EMA_FAST)
        self.ema_mid = _ema(self.ema_mid, mid, EMA_MID)
        self.ema_slow = _ema(self.ema_slow, mid, EMA_SLOW)

        self.ema_price_fast = _ema(self.ema_price_fast, mid, MACD_FAST)
        self.ema_price_slow = _ema(self.ema_price_slow, mid, MACD_SLOW)
        macd_val = self.ema_price_fast - self.ema_price_slow
        self.macd = macd_val
        self.macd_signal = _ema(self.macd_signal, macd_val, MACD_SIGNAL)
        self.macd_hist = macd_val - self.macd_signal

        return self.classify()

    def _bbands(self):
        if len(self.window) < 10:
            return None, None, None, None, None

        arr = np.array(self.window, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std(ddof=0))

        upper = mean + NUM_STD * std
        lower = mean - NUM_STD * std
        width = upper - lower

        self.bb_mid_hist.append(mean)
        slope = 0.0
        if len(self.bb_mid_hist) >= 6:
            slope = (self.bb_mid_hist[-1] - self.bb_mid_hist[-6]) / 5.0

        slope_pips = float(slope) / float(self.pip_size)
        width_pips = float(width) / float(self.pip_size)

        self.slope_hist.append(abs(slope_pips))
        self.width_hist.append(width_pips)

        return mean, upper, lower, width_pips, slope_pips

    def _dir_regime(self):
        if self.ema_fast is None or self.ema_mid is None or self.ema_slow is None:
            return "NO_TREND"
        if self.ema_fast > self.ema_mid > self.ema_slow:
            return "TREND_UP"
        if self.ema_fast < self.ema_mid < self.ema_slow:
            return "TREND_DOWN"
        return "NO_TREND"

    def _apply_hysteresis(self, raw):
        if raw == self.regime:
            self.regime_candidate = None
            self.regime_streak = 0
            return self.regime

        if self.regime_candidate != raw:
            self.regime_candidate = raw
            self.regime_streak = 1
            return self.regime

        self.regime_streak += 1

        confirm = REGIME_CONFIRM
        if self.regime.startswith("TREND") or raw.startswith("TREND"):
            confirm = TREND_EXIT_CONFIRM

        if self.regime_streak >= confirm:
            self.regime = raw
            self.regime_candidate = None
            self.regime_streak = 0

        return self.regime

    def classify(self):
        bb_mid, bb_up, bb_lo, width_pips, slope_pips = self._bbands()
        if bb_mid is None:
            return "NEUTRAL", {"warmup": True, "reason": "bb_not_ready", "have": len(self.window)}

        dire = self._dir_regime()
        abs_slope = abs(float(slope_pips))

        # Adaptive gates (avoid absolute thresholds that break across pip_size scales)
        width_arr = np.array(self.width_hist, dtype=float) if len(self.width_hist) >= 20 else None
        slope_arr = np.array(self.slope_hist, dtype=float) if len(self.slope_hist) >= 20 else None

        raw = "NEUTRAL"
        if width_arr is not None and slope_arr is not None:
            w40, w60 = np.percentile(width_arr, [40, 60])
            s40, s60 = np.percentile(slope_arr, [40, 60])

            # RANGE = narrow + flat (relative to recent context)
            if float(width_pips) <= float(w40) and float(abs_slope) <= float(s40):
                raw = "RANGE"
            # TREND = wide + sloped + directional EMA stack
            elif dire in ("TREND_UP", "TREND_DOWN") and float(width_pips) >= float(w60) and float(abs_slope) >= float(s60):
                raw = dire
            else:
                raw = "NEUTRAL"
        else:
            # fallback: only direction stack → weak trend hint, but keep NEUTRAL unless clear
            raw = dire if dire in ("TREND_UP", "TREND_DOWN") else "NEUTRAL"

        stable = self._apply_hysteresis(raw)

        components = {
            "warmup": False,
            "dir": dire,
            "features": {
                "mean": bb_mid,
                "upper": bb_up,
                "lower": bb_lo,
                "width_pips": float(width_pips),
                "slope_pips": float(slope_pips),
                "ticks": len(self.window),
            },
        }
        return stable, components


# =====================================================================
# CANDLE-CLOSE REGIME ENGINE (USED BY strategy_logic dispatcher)
# =====================================================================

@dataclass(frozen=True)
class CandleRegimeConfig:
    bb_period: int = 20
    bb_std: float = 2.0
    ema_period: int = 21
    slope_lookback: int = 5
    confirm_bars: int = 2

    # Minimum drift gate (pips) — keep small so it works on TODAY feeds
    ema_drift_min_pips: float = 0.25
    ema_drift_strong_min_pips: float = 0.6

    # Adaptive thresholds: percentiles (0..100)
    # RANGE is defined as: width within [range_width_low_pct, range_width_high_pct] AND slope <= range_slope_pct.
    # (Targets "healthy ranging" rather than only "compressed range".)
    range_width_low_pct: float = 25.0
    range_width_high_pct: float = 75.0
    range_width_pct: float = 40.0
    range_slope_pct: float = 40.0
    trend_width_pct: float = 60.0
    trend_slope_pct: float = 60.0
    strong_width_pct: float = 80.0
    strong_slope_pct: float = 80.0
    strong_drift_pct: float = 70.0

    # Diagnostics only
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    transition_window: int = 3
    transition_min_reasons: int = 2
    macd_zero_cross_eps_pips: float = 0.05

    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0


@dataclass
class CandleRegimeState:
    stable: str = "NEUTRAL"
    candidate: Optional[str] = None
    streak: int = 0


def _strict_monotonic_decreasing(xs: List[float]) -> bool:
    if len(xs) < 2:
        return False
    for i in range(1, len(xs)):
        if not (xs[i] < xs[i - 1]):
            return False
    return True


def _strict_monotonic_increasing(xs: List[float]) -> bool:
    if len(xs) < 2:
        return False
    for i in range(1, len(xs)):
        if not (xs[i] > xs[i - 1]):
            return False
    return True


def _zero_cross_strict(a: float, b: float, eps: float) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    if abs(a) <= eps or abs(b) <= eps:
        return False
    return (a > 0 and b < 0) or (a < 0 and b > 0)


class CandleRegimeClassifier:
    """
    Signature preserved:
      - __init__(symbol: str, pip_size: Optional[float] = None, cfg: Optional[CandleRegimeConfig] = None)
      - update_from_df(df_5m_closed, pip_size=...) -> (stable_regime: str, out: dict)

    Core change:
      - Regime gates are ADAPTIVE (percentile-based) on width/slope/drift across available candles.
      - Avoids brittle absolute width thresholds that break across pip_size scales (esp. EURUSD.TODAY).

    IMPORTANT (Architecture / House Rules):
      - strategy_logic assumes df_5m_closed is already enriched by candle_builder.
      - Therefore, this classifier MUST NOT recompute indicators in production.
        It will *read* BB/EMA/MACD/RSI columns if present and return warmup
        with an explicit reason if they are missing.
    """

    _PIP_SIZES_POINTS_PER_PIP: Dict[str, float] = {
        "EURGBP": 1.0,
        "GBPUSD": 1.0,
        "EURUSD": 1.0,
        "AUDUSD": 1.0,
        "USDCAD": 1.0,
        "USDJPY": 1.0,
        "GBPJPY": 1.0,
    }

    def __init__(self, symbol: str, pip_size: Optional[float] = None, cfg: Optional[CandleRegimeConfig] = None):
        self.symbol = str(symbol).upper()
        self.cfg = cfg or CandleRegimeConfig()
        self._pip_size_instance = pip_size
        self._state = CandleRegimeState()

        tw = max(2, int(self.cfg.transition_window))
        self._width_hist: Deque[float] = deque([], maxlen=tw)
        self._slope_hist: Deque[float] = deque([], maxlen=tw)
        self._macd_hist_hist: Deque[float] = deque([], maxlen=tw)
        self._prev_macd_hist_pips: Optional[float] = None

        # Phase 4B shadow label cached for in-process consumers (regime
        # filter / TP modulation). Updated on every successful update_from_df
        # just before _write_shadow_row. None until first successful classify.
        self._last_shadow_label: Optional[str] = None

    def _symbol_base(self) -> str:
        s = self.symbol
        for sep in (".", "-", "_", "/"):
            if sep in s:
                s = s.split(sep)[0]
        return s

    def _sanitize_pip_size(self, pip_override: Any = None) -> Tuple[float, str]:
        try:
            if pip_override is not None:
                v = float(pip_override)
                if math.isfinite(v) and v > 0:
                    return float(v), "override"
        except Exception:
            pass

        try:
            if self._pip_size_instance is not None:
                v = float(self._pip_size_instance)
                if math.isfinite(v) and v > 0:
                    return float(v), "instance"
        except Exception:
            pass

        base = self._symbol_base()
        v = self._PIP_SIZES_POINTS_PER_PIP.get(base)
        try:
            if v is not None:
                vv = float(v)
                if math.isfinite(vv) and vv > 0:
                    return float(vv), "symbol_map"
        except Exception:
            pass

        return 1.0, "default"

    @staticmethod
    def _points_to_pips(points: float, pip_size: float) -> float:
        return float(points) / float(pip_size)

    @staticmethod
    def _best_match_column(cols: List[str], exact: str, prefix: str) -> Optional[str]:
        if exact in cols:
            return exact
        for c in cols:
            if c.startswith(prefix):
                return c
        return None

    @staticmethod
    def _parse_bb_std_from_col(col: str) -> Optional[float]:
        try:
            parts = col.split("_")
            if len(parts) < 4:
                return None
            return float(parts[-1])
        except Exception:
            return None

    def _pick_bb_band_column(self, cols: List[str], band: str, period: int, std: float) -> Optional[str]:
        std_str = f"{float(std):g}"
        exact = f"BB_{band}_{int(period)}_{std_str}"
        if exact in cols:
            return exact

        prefix = f"BB_{band}_{int(period)}_"
        candidates = [c for c in cols if c.startswith(prefix)]
        if not candidates:
            return None

        best = None
        best_d = None
        for c in candidates:
            s = self._parse_bb_std_from_col(c)
            if s is None or not math.isfinite(s):
                continue
            d = abs(float(s) - float(std))
            if best is None or d < float(best_d):
                best = c
                best_d = d
        return best or candidates[0]

    def _pick_bb_mid_column(self, cols: List[str], period: int) -> Optional[str]:
        exact = f"BB_MID_{int(period)}"
        if exact in cols:
            return exact
        prefix = f"BB_MID_{int(period)}"
        for c in cols:
            if c.startswith(prefix):
                return c
        return None

    def _pick_macd_hist_column(self, cols: List[str], fast: int, slow: int, signal: int) -> Optional[str]:
        exact = f"MACD_HIST_{int(fast)}_{int(slow)}_{int(signal)}"
        return self._best_match_column(cols, exact=exact, prefix="MACD_HIST_")

    def _pick_rsi_column(self, cols: List[str], period: int) -> Optional[str]:
        exact = f"RSI_{int(period)}"
        return self._best_match_column(cols, exact=exact, prefix="RSI_")

    def _pick_ema_column(self, cols: List[str], period: int) -> Optional[str]:
        exact = f"EMA_{int(period)}"
        return self._best_match_column(cols, exact=exact, prefix="EMA_")

    def _apply_hysteresis(self, raw: str) -> str:
        if raw == self._state.stable:
            self._state.candidate = None
            self._state.streak = 0
            return self._state.stable

        if self._state.candidate != raw:
            self._state.candidate = raw
            self._state.streak = 1
            return self._state.stable

        self._state.streak += 1
        if self._state.streak >= max(1, int(self.cfg.confirm_bars)):
            self._state.stable = raw
            self._state.candidate = None
            self._state.streak = 0
        return self._state.stable

    # =====================================================================
    # Shadow classifier (Phase 4B): vote-count
    # =====================================================================
    # Runs alongside the gate-cascade classification above. Produces its own
    # label/confidence/votes on each bar. Does NOT pass through hysteresis
    # and does NOT influence the production label consumed by strategy_logic
    # — 4E will be the first consumer. Deliberately uses a distinct label
    # vocabulary (TRENDING_BULL/TRENDING_BEAR vs the gate cascade's
    # TREND_UP/TREND_DOWN) so disagreements surface in the logs rather than
    # being silently harmonised.
    def _shadow_required_cols(self) -> Dict[str, str]:
        """Resolved DataFrame column names the shadow classifier needs.

        Exposed as a method so callers can introspect the contract and so
        partial-deploy failures (Phase 2 rollback, upstream indicator
        pipeline breakage) can be reported with the actual column names
        being searched for, not just semantic names.
        """
        std_key = f"{float(self.cfg.bb_std):g}"
        return {
            "ema_stack": "EMA_STACK_STATE",
            "bb_width_pctl": f"BB_WIDTH_PCTL_{int(self.cfg.bb_period)}_{std_key}",
            "bb_mid_slope": f"BB_MID_SLOPE_5_{int(self.cfg.bb_period)}",
            "atr_pctl": "ATR_PCTL_14",
        }

    def _classify_vote_count(self, df_ind: Any, pip: float) -> Dict[str, Any]:
        required = self._shadow_required_cols()
        ema_stack_col = required["ema_stack"]
        bb_width_pctl_col = required["bb_width_pctl"]
        bb_mid_slope_col = required["bb_mid_slope"]
        atr_pctl_col = required["atr_pctl"]

        cols = set(df_ind.columns)
        # 4C: partial-deploy safety. A column missing from the DataFrame
        # entirely is a structural failure (pipeline broken or rolled back),
        # distinct from "column present but NaN on latest bar" (warmup/gap).
        # Both degrade the vote to ABSTAIN, but only structural absence
        # indicates the shadow feed is offline — surface it distinctly so
        # 4E can gate on it and so deploy audits can catch it. Gate cascade
        # path above is unaffected by this check.
        missing_from_df = [k for k, c in required.items() if c not in cols]

        last = df_ind.iloc[-1]

        ema_stack_vote = "ABSTAIN"
        bb_width_vote = "ABSTAIN"
        bb_mid_slope_vote = "ABSTAIN"
        atr_pctl_vote = "ABSTAIN"

        ema_stack_raw: Optional[str] = None
        bb_width_raw: Optional[float] = None
        bb_mid_slope_pips: Optional[float] = None
        atr_pctl_raw: Optional[float] = None

        missing: List[str] = []

        # EMA_STACK_STATE → direction axis
        if ema_stack_col in cols:
            try:
                v = last[ema_stack_col]
                if v is None or (isinstance(v, float) and not math.isfinite(v)):
                    missing.append("ema_stack")
                else:
                    ema_stack_raw = str(v)
                    if ema_stack_raw in ("BULL_ALIGNED", "BULL_PARTIAL"):
                        ema_stack_vote = "BULLISH"
                    elif ema_stack_raw in ("BEAR_ALIGNED", "BEAR_PARTIAL"):
                        ema_stack_vote = "BEARISH"
                    else:
                        ema_stack_vote = "ABSTAIN"  # COMPRESSED / MIXED / unknown
            except Exception:
                missing.append("ema_stack")
        else:
            missing.append("ema_stack")

        # BB_WIDTH_PCTL_20_2 → structure axis
        if bb_width_pctl_col in cols:
            try:
                v = float(last[bb_width_pctl_col])
                if not math.isfinite(v):
                    missing.append("bb_width_pctl")
                else:
                    bb_width_raw = v
                    if v <= 20.0:
                        bb_width_vote = "RANGE"
                    elif v >= 80.0:
                        bb_width_vote = "TRENDING"
                    else:
                        bb_width_vote = "ABSTAIN"
            except Exception:
                missing.append("bb_width_pctl")
        else:
            missing.append("bb_width_pctl")

        # BB_MID_SLOPE_5_20 → direction axis (normalise raw price units to pips)
        # v1 threshold 0.1 pips per bar is a placeholder. Tune against
        # observation period by correlating shadow votes to realised bar
        # direction once data accumulates.
        if bb_mid_slope_col in cols:
            try:
                raw_slope = float(last[bb_mid_slope_col])
                if not math.isfinite(raw_slope):
                    missing.append("bb_mid_slope")
                else:
                    pip_f = float(pip) if float(pip) > 0 else 1.0
                    slope_pips = raw_slope / pip_f
                    bb_mid_slope_pips = slope_pips
                    if slope_pips > 0.1:
                        bb_mid_slope_vote = "BULLISH"
                    elif slope_pips < -0.1:
                        bb_mid_slope_vote = "BEARISH"
                    else:
                        bb_mid_slope_vote = "ABSTAIN"
            except Exception:
                missing.append("bb_mid_slope")
        else:
            missing.append("bb_mid_slope")

        # ATR_PCTL_14 → structure axis
        if atr_pctl_col in cols:
            try:
                v = float(last[atr_pctl_col])
                if not math.isfinite(v):
                    missing.append("atr_pctl")
                else:
                    atr_pctl_raw = v
                    if v <= 30.0:
                        atr_pctl_vote = "RANGE"
                    elif v >= 70.0:
                        atr_pctl_vote = "TRENDING"
                    else:
                        atr_pctl_vote = "ABSTAIN"
            except Exception:
                missing.append("atr_pctl")
        else:
            missing.append("atr_pctl")

        votes = {
            "ema_stack": ema_stack_vote,
            "bb_width_pctl": bb_width_vote,
            "bb_mid_slope": bb_mid_slope_vote,
            "atr_pctl": atr_pctl_vote,
        }
        features = {
            "ema_stack_state": ema_stack_raw,
            "bb_width_pctl": bb_width_raw,
            "bb_mid_slope_pips": bb_mid_slope_pips,
            "atr_pctl": atr_pctl_raw,
        }

        # Per-axis confidence (F1): each axis has 2 signals, so rescale
        # HIGH/MED/LOW over 2-vote agreement instead of the symmetric 3/4–4/4
        # rule used previously. The old rule structurally capped RANGE at LOW
        # (both structure signals agreeing on RANGE gave 2 consistent, never
        # clearing 3/4 → MED), which degraded the observation stream.
        #   both axis-committed votes match   → HIGH
        #   one committed + one ABSTAIN       → MED
        #   split (e.g. BULLISH + BEARISH)    → LOW
        #   both ABSTAIN                      → LOW
        def _axis_conf(votes_pair: Tuple[str, str], committed: set) -> str:
            non_abstain = [v for v in votes_pair if v in committed]
            if len(non_abstain) == 2:
                return "HIGH" if non_abstain[0] == non_abstain[1] else "LOW"
            if len(non_abstain) == 1:
                return "MED"
            return "LOW"

        direction_conf = _axis_conf(
            (ema_stack_vote, bb_mid_slope_vote), {"BULLISH", "BEARISH"}
        )
        structure_conf = _axis_conf(
            (bb_width_vote, atr_pctl_vote), {"TRENDING", "RANGE"}
        )

        # Label derivation (unchanged — structure decides outer, direction
        # decides inner). 3+ missing inputs short-circuit to NEUTRAL.
        if len(missing) >= 3:
            label = "NEUTRAL"
        else:
            struct_votes = [bb_width_vote, atr_pctl_vote]
            dir_votes = [ema_stack_vote, bb_mid_slope_vote]
            n_range = sum(1 for v in struct_votes if v == "RANGE")
            n_trending = sum(1 for v in struct_votes if v == "TRENDING")
            n_bull = sum(1 for v in dir_votes if v == "BULLISH")
            n_bear = sum(1 for v in dir_votes if v == "BEARISH")

            if n_range == 2:
                label = "RANGE"
            elif n_trending == 2 and n_bull > n_bear:
                label = "TRENDING_BULL"
            elif n_trending == 2 and n_bear > n_bull:
                label = "TRENDING_BEAR"
            else:
                # Covers: both TRENDING with direction split/abstain,
                # structure split (1 TRENDING + 1 RANGE), both structure
                # ABSTAIN.
                label = "NEUTRAL"

        # Combined confidence by label:
        #   RANGE             → structure_conf (direction is not part of the claim)
        #   TRENDING_BULL/BEAR → min(direction_conf, structure_conf)
        #   BULLISH / BEARISH → direction_conf (labels not currently emitted;
        #                       reserved for a future vocabulary extension
        #                       where direction commits but structure abstains)
        #   NEUTRAL           → LOW
        _order = {"LOW": 0, "MED": 1, "HIGH": 2}
        _by_rank = {v: k for k, v in _order.items()}

        if label == "RANGE":
            confidence = structure_conf
        elif label in ("TRENDING_BULL", "TRENDING_BEAR"):
            confidence = _by_rank[min(_order[direction_conf], _order[structure_conf])]
        elif label in ("BULLISH", "BEARISH"):
            confidence = direction_conf
        else:
            confidence = "LOW"

        result = {
            "label": label,
            "confidence": confidence,
            "confidence_breakdown": {
                "direction": direction_conf,
                "structure": structure_conf,
            },
            "votes": votes,
            "features": features,
            # 4C: always publish the required-column contract for debug
            # context. Callers can cross-reference `missing` and
            # `missing_from_df` against this to tell partial-deploy
            # breakage apart from per-bar NaN / warmup.
            "missing_cols": dict(required),
        }
        if missing:
            result["missing"] = missing
        if missing_from_df:
            result["missing_from_df"] = missing_from_df
        return result

    def update_from_df(self, df_5m_closed: Any, pip_size: Any = None) -> Tuple[str, Dict[str, Any]]:
        try:
            import pandas as pd  # local import
        except Exception as e:
            stable = self._state.stable
            return stable, {
                "symbol": self.symbol,
                "regime": stable,
                "raw": "NEUTRAL",
                "stable": stable,
                "warmup": True,
                "reason": "pandas_import_failed",
                "error": f"{type(e).__name__}: {e}",
            }

        if not isinstance(df_5m_closed, pd.DataFrame):
            stable = self._state.stable
            return stable, {
                "symbol": self.symbol,
                "regime": stable,
                "raw": "NEUTRAL",
                "stable": stable,
                "warmup": True,
                "reason": "df_not_dataframe",
            }

        pip, pip_src = self._sanitize_pip_size(pip_override=pip_size)

        df = df_5m_closed.copy()
        if "timestamp" not in df.columns and "time" in df.columns:
            df = df.rename(columns={"time": "timestamp"})

        required_ohlc = ["open", "high", "low", "close"]
        for c in required_ohlc:
            if c not in df.columns:
                stable = self._state.stable
                return stable, {
                    "symbol": self.symbol,
                    "regime": stable,
                    "raw": "NEUTRAL",
                    "stable": stable,
                    "warmup": True,
                    "reason": "missing_ohlc_cols",
                    "missing": [x for x in required_ohlc if x not in df.columns],
                    "pip_size": pip,
                    "pip_size_source": pip_src,
                }

        for c in required_ohlc:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=required_ohlc).reset_index(drop=True)
        have = int(len(df))

        lb = max(2, int(self.cfg.slope_lookback))
        need_regime = int(max(self.cfg.bb_period, self.cfg.ema_period, lb + 1))

        if have < need_regime:
            stable = self._state.stable
            return stable, {
                "symbol": self.symbol,
                "regime": stable,
                "raw": "NEUTRAL",
                "stable": stable,
                "warmup": True,
                "reason": "warmup_need_regime",
                "have": have,
                "needs": {"regime": need_regime},
                "pip_size": pip,
                "pip_size_source": pip_src,
                "features": {},
                "transition_watch": False,
                "transition_reasons": [],
            }

        # House Rules / Architecture:
        # - Prefer precomputed indicator columns from candle_builder.
        # - Do NOT recompute indicators here (prevents drift + CPU load + NaN warmup surprises).
        df_ind = df

        cols = list(df_ind.columns)

        bb_mid_col = self._pick_bb_mid_column(cols, period=int(self.cfg.bb_period))
        bb_up_col = self._pick_bb_band_column(cols, band="UPPER", period=int(self.cfg.bb_period), std=float(self.cfg.bb_std))
        bb_lo_col = self._pick_bb_band_column(cols, band="LOWER", period=int(self.cfg.bb_period), std=float(self.cfg.bb_std))
        ema_col = self._pick_ema_column(cols, period=int(self.cfg.ema_period))
        rsi_col = self._pick_rsi_column(cols, period=int(self.cfg.rsi_period))
        macd_hist_col = self._pick_macd_hist_column(cols, fast=int(self.cfg.macd_fast), slow=int(self.cfg.macd_slow), signal=int(self.cfg.macd_signal))

        core_missing = [k for k, v in (("bb_mid", bb_mid_col), ("bb_upper", bb_up_col), ("bb_lower", bb_lo_col), ("ema", ema_col)) if v is None]
        if core_missing:
            stable = self._state.stable
            return stable, {
                "symbol": self.symbol,
                "regime": stable,
                "raw": "NEUTRAL",
                "stable": stable,
                "warmup": True,
                "reason": "missing_core_indicator_cols",
                "missing": core_missing,
                "missing_cols": {
                    "bb_mid": f"BB_MID_{int(self.cfg.bb_period)}",
                    "bb_upper": f"BB_UPPER_{int(self.cfg.bb_period)}_{float(self.cfg.bb_std):g}",
                    "bb_lower": f"BB_LOWER_{int(self.cfg.bb_period)}_{float(self.cfg.bb_std):g}",
                    "ema": f"EMA_{int(self.cfg.ema_period)}",
                },
                "have": have,
                "needs": {"regime": need_regime},
                "pip_size": pip,
                "pip_size_source": pip_src,
            }

        r = df_ind.iloc[-1]
        try:
            close = float(r["close"])
            bb_mid = float(r[bb_mid_col])
            bb_up = float(r[bb_up_col])
            bb_lo = float(r[bb_lo_col])
            ema = float(r[ema_col])
        except Exception:
            stable = self._state.stable
            return stable, {
                "symbol": self.symbol,
                "regime": stable,
                "raw": "NEUTRAL",
                "stable": stable,
                "warmup": True,
                "reason": "core_indicator_read_failed",
                "have": have,
                "pip_size": pip,
                "pip_size_source": pip_src,
            }

        if not all(math.isfinite(x) for x in (close, bb_mid, bb_up, bb_lo, ema)):
            stable = self._state.stable
            return stable, {
                "symbol": self.symbol,
                "regime": stable,
                "raw": "NEUTRAL",
                "stable": stable,
                "warmup": True,
                "reason": "core_indicators_nan",
                "have": have,
                "pip_size": pip,
                "pip_size_source": pip_src,
            }

        # Core features (pips)
        width_points = float(bb_up - bb_lo)
        width_pips = self._points_to_pips(width_points, pip)

        drift_points = float(close - ema)
        drift_pips_signed = self._points_to_pips(drift_points, pip)
        drift_pips_abs = abs(float(drift_pips_signed))

        bb_mid_series = df_ind[bb_mid_col].dropna()
        slope_pips_per_bar = 0.0
        slope_ready = False
        if len(bb_mid_series) >= (lb + 1):
            v0 = float(bb_mid_series.iloc[-1])
            v1 = float(bb_mid_series.iloc[-1 - lb])
            if math.isfinite(v0) and math.isfinite(v1):
                slope_points_per_bar = (v0 - v1) / float(lb)
                slope_pips_per_bar = self._points_to_pips(slope_points_per_bar, pip)
                slope_ready = True

        # ============================================================
        # ADAPTIVE CLASSIFICATION (fixes "always NEUTRAL" / scale issues)
        # ============================================================
        raw = "NEUTRAL"  # diagnostic/raw (may include STRONG_*)
        canonical_raw = "NEUTRAL"  # what we feed into hysteresis (4 stable labels)

        # Use only what IG can provide (20-50) and adapt to the distribution.
        # We compute thresholds from the most recent window available.
        lookback_n = min(int(have), max(int(need_regime), 20))
        tail = df_ind.iloc[-lookback_n:].copy()

        # width series (pips)
        try:
            w_points = (tail[bb_up_col] - tail[bb_lo_col]).astype(float)
            w_pips_series = (w_points / float(pip)).replace([np.inf, -np.inf], np.nan).dropna().astype(float).values
        except Exception:
            w_pips_series = np.array([], dtype=float)

        # slope proxy series (CONSISTENT with decision metric):
        # abs( (mid - mid.shift(lb)) / lb ) in pips-per-bar
        try:
            mid_series = tail[bb_mid_col].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
            d_lb = (mid_series - mid_series.shift(lb)) / float(lb)
            d_lb = d_lb.replace([np.inf, -np.inf], np.nan).dropna().astype(float).values
            slope_abs_pips_series = np.abs(d_lb / float(pip)).astype(float)
        except Exception:
            slope_abs_pips_series = np.array([], dtype=float)

        # drift abs series (pips)
        try:
            drift_abs_series = np.abs((tail["close"].astype(float) - tail[ema_col].astype(float)) / float(pip))
            drift_abs_pips_series = drift_abs_series.replace([np.inf, -np.inf], np.nan).dropna().astype(float).values
        except Exception:
            drift_abs_pips_series = np.array([], dtype=float)

        # If we can't form distributions, fall back safely.
        if len(w_pips_series) >= 10 and len(slope_abs_pips_series) >= 10 and slope_ready:
            # Width band for "healthy range" detection
            w_low = float(np.percentile(w_pips_series, float(self.cfg.range_width_low_pct)))
            w_high = float(np.percentile(w_pips_series, float(self.cfg.range_width_high_pct)))

            # Legacy single-cut values kept for transparency/back-compat
            w_range = float(np.percentile(w_pips_series, float(self.cfg.range_width_pct)))
            s_range = float(np.percentile(slope_abs_pips_series, float(self.cfg.range_slope_pct)))
            w_trend = float(np.percentile(w_pips_series, float(self.cfg.trend_width_pct)))
            s_trend = float(np.percentile(slope_abs_pips_series, float(self.cfg.trend_slope_pct)))

            w_strong = float(np.percentile(w_pips_series, float(self.cfg.strong_width_pct)))
            s_strong = float(np.percentile(slope_abs_pips_series, float(self.cfg.strong_slope_pct)))

            drift_gate = max(
                float(self.cfg.ema_drift_min_pips),
                float(np.percentile(drift_abs_pips_series, 55.0)) if len(drift_abs_pips_series) >= 10 else float(self.cfg.ema_drift_min_pips),
            )
            strong_drift_gate = max(
                float(self.cfg.ema_drift_strong_min_pips),
                float(np.percentile(drift_abs_pips_series, float(self.cfg.strong_drift_pct))) if len(drift_abs_pips_series) >= 10 else float(self.cfg.ema_drift_strong_min_pips),
            )

            abs_slope_now = abs(float(slope_pips_per_bar))

            # RANGE = width within a middle band + flat slope.
            # This avoids classifying only the most compressed widths as "RANGE".
            range_gate = (float(w_low) <= float(width_pips) <= float(w_high)) and (abs_slope_now <= s_range)
            trend_gate = (float(width_pips) >= w_trend) and (abs_slope_now >= s_trend) and (drift_pips_abs >= drift_gate)
            strong_gate = (float(width_pips) >= w_strong) and (abs_slope_now >= s_strong) and (drift_pips_abs >= strong_drift_gate)

            if range_gate:
                raw = "RANGE"
            elif strong_gate:
                raw = "STRONG_TREND_UP" if drift_pips_signed > 0 else "STRONG_TREND_DOWN"
            elif trend_gate:
                raw = "TREND_UP" if drift_pips_signed > 0 else "TREND_DOWN"
            else:
                raw = "NEUTRAL"
        else:
            # fallback: if we have slope, use drift+ slope sanity
            if slope_ready and drift_pips_abs >= float(self.cfg.ema_drift_min_pips) and abs(float(slope_pips_per_bar)) > 0:
                raw = "TREND_UP" if drift_pips_signed > 0 else "TREND_DOWN"
            else:
                raw = "NEUTRAL"

        # Canonicalize RAW -> stable label set (docstring truth).
        if raw == "STRONG_TREND_UP":
            canonical_raw = "TREND_UP"
        elif raw == "STRONG_TREND_DOWN":
            canonical_raw = "TREND_DOWN"
        else:
            canonical_raw = raw

        stable = self._apply_hysteresis(canonical_raw)

        # Phase 4B shadow classifier: runs alongside gate cascade, does not
        # influence `stable` above. Deliberately uses its own label vocabulary.
        try:
            shadow = self._classify_vote_count(df_ind, float(pip))
        except Exception as e:
            shadow = {
                "label": "NEUTRAL",
                "confidence": "LOW",
                "confidence_breakdown": {
                    "direction": "LOW",
                    "structure": "LOW",
                },
                "votes": {
                    "ema_stack": "ABSTAIN",
                    "bb_width_pctl": "ABSTAIN",
                    "bb_mid_slope": "ABSTAIN",
                    "atr_pctl": "ABSTAIN",
                },
                "features": {
                    "ema_stack_state": None,
                    "bb_width_pctl": None,
                    "bb_mid_slope_pips": None,
                    "atr_pctl": None,
                },
                "missing_cols": self._shadow_required_cols(),
                "error": f"{type(e).__name__}: {e}",
            }

        # =========================
        # Diagnostics (non-blocking)
        # =========================
        transition_reasons: List[str] = []
        transition_watch = False

        self._width_hist.append(float(width_pips))
        self._slope_hist.append(float(abs(slope_pips_per_bar)))

        macd_hist_pips: Optional[float] = None
        macd_ready = False
        if macd_hist_col is not None:
            try:
                mh_points = float(r[macd_hist_col])
                if math.isfinite(mh_points):
                    macd_hist_pips = self._points_to_pips(mh_points, pip)
                    self._macd_hist_hist.append(float(macd_hist_pips))
                    macd_ready = True
            except Exception:
                macd_hist_pips = None

        if len(self._width_hist) >= self._width_hist.maxlen:
            xs = list(self._width_hist)
            if _strict_monotonic_decreasing(xs):
                transition_reasons.append("BB_WIDTH_CONTRACTING")
            elif _strict_monotonic_increasing(xs):
                transition_reasons.append("BB_WIDTH_EXPANDING")

        if len(self._slope_hist) >= self._slope_hist.maxlen:
            xs = list(self._slope_hist)
            if _strict_monotonic_decreasing(xs):
                transition_reasons.append("SLOPE_CONTRACTING")
            elif _strict_monotonic_increasing(xs):
                transition_reasons.append("SLOPE_EXPANDING")

        if macd_ready and len(self._macd_hist_hist) >= self._macd_hist_hist.maxlen:
            xs = [abs(x) for x in list(self._macd_hist_hist)]
            if _strict_monotonic_decreasing(xs):
                transition_reasons.append("MACD_HIST_CONTRACTING")
            elif _strict_monotonic_increasing(xs):
                transition_reasons.append("MACD_HIST_EXPANDING")

        if macd_ready and macd_hist_pips is not None and self._prev_macd_hist_pips is not None:
            eps = float(max(0.0, self.cfg.macd_zero_cross_eps_pips))
            if _zero_cross_strict(float(self._prev_macd_hist_pips), float(macd_hist_pips), eps=eps):
                transition_reasons.append("MACD_ZERO_CROSS")
        if macd_hist_pips is not None:
            self._prev_macd_hist_pips = float(macd_hist_pips)

        rsi_val: Optional[float] = None
        rsi_ready = False
        if rsi_col is not None:
            try:
                rv = float(r[rsi_col])
                if math.isfinite(rv):
                    rsi_val = rv
                    rsi_ready = True
            except Exception:
                rsi_val = None

        if rsi_ready and rsi_val is not None:
            if float(rsi_val) >= float(self.cfg.rsi_overbought):
                transition_reasons.append("RSI_OVERBOUGHT")
            elif float(rsi_val) <= float(self.cfg.rsi_oversold):
                transition_reasons.append("RSI_OVERSOLD")

        structural = [x for x in transition_reasons if x.startswith(("BB_WIDTH_", "SLOPE_", "MACD_"))]
        if len(transition_reasons) >= int(self.cfg.transition_min_reasons) and len(structural) >= 1:
            transition_watch = True

        out = {
            "symbol": self.symbol,
            "regime": stable,
            "raw": raw,
            "canonical_raw": canonical_raw,
            "stable": stable,
            "warmup": False,
            "have": have,
            "needs": {"regime": need_regime},
            "pip_size": float(pip),
            "pip_size_source": pip_src,
            "features": {
                "close": float(close),
                "bb_mid": float(bb_mid),
                "bb_upper": float(bb_up),
                "bb_lower": float(bb_lo),
                "width_pips": float(width_pips),
                "ema": float(ema),
                "ema_drift_pips": float(drift_pips_abs),
                "ema_drift_pips_signed": float(drift_pips_signed),
                "slope_pips_per_bar": float(slope_pips_per_bar),
                "slope_ready": bool(slope_ready),
                "macd_hist_pips": (float(macd_hist_pips) if macd_hist_pips is not None else None),
                "macd_ready": bool(macd_ready),
                "rsi": (float(rsi_val) if rsi_val is not None else None),
                "rsi_ready": bool(rsi_ready),
                # extra transparency for debugging "why neutral"
                "adaptive": {
                    "lookback_n": int(lookback_n),
                    "width_series_len": int(len(w_pips_series)),
                    "slope_series_len": int(len(slope_abs_pips_series)),
                    "drift_series_len": int(len(drift_abs_pips_series)),
                    "cfg": {
                        "range_width_low_pct": float(self.cfg.range_width_low_pct),
                        "range_width_high_pct": float(self.cfg.range_width_high_pct),
                        "range_width_pct": float(self.cfg.range_width_pct),
                        "range_slope_pct": float(self.cfg.range_slope_pct),
                        "trend_width_pct": float(self.cfg.trend_width_pct),
                        "trend_slope_pct": float(self.cfg.trend_slope_pct),
                        "strong_width_pct": float(self.cfg.strong_width_pct),
                        "strong_slope_pct": float(self.cfg.strong_slope_pct),
                        "strong_drift_pct": float(self.cfg.strong_drift_pct),
                    },
                },
            },
            "transition_watch": bool(transition_watch),
            "transition_reasons": transition_reasons,
            "cols": {
                "bb_mid": bb_mid_col,
                "bb_upper": bb_up_col,
                "bb_lower": bb_lo_col,
                "ema": ema_col,
                "rsi": rsi_col,
                "macd_hist": macd_hist_col,
            },
            "shadow": shadow,
        }

        try:
            _shadow_label = shadow.get("label") if isinstance(shadow, dict) else None
            if isinstance(_shadow_label, str):
                self._last_shadow_label = _shadow_label
        except Exception:
            pass

        # bar_ts = timestamp of the candle just classified (last closed 5m
        # bar in df_ind), distinct from the wall-clock write time recorded by
        # _write_shadow_row. None if the input frame carries no usable
        # timestamp column.
        bar_ts: Optional[str] = None
        if "timestamp" in df_ind.columns:
            try:
                _bt = r["timestamp"]
                if not pd.isna(_bt):
                    bar_ts = (_bt.isoformat() if hasattr(_bt, "isoformat")
                              else str(_bt))
            except Exception:
                bar_ts = None
        _write_shadow_row(self.symbol, stable, out, bar_ts=bar_ts)
        return stable, out
