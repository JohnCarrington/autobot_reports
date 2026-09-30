"""bb_pattern2_fade — Pattern 2 (BB wick-only pierce) fade strategy.

Three live-demo configurations from Phase 6 of
reports/bb_three_pattern_analysis_20260510.md:

    P2_USDJPY_B   Variant B (loose)   USDJPY  SL=12  TP=30
    P2_USDCAD_A   Variant A (strict)  USDCAD  SL=12  TP=30
    P2_EURUSD_A   Variant A (strict)  EURUSD  SL=12  TP=30

Variant definitions (preserved here byte-for-byte against the analysis-time
detectors in scripts/analysis/bb_three_pattern/detectors.py):

    A — strict:  pierce by wick only (close back inside band) on bar N
                 + N+1 opposite-coloured to N (genuine colour flip)
                 + isolated (≤ 1 same-band pierce in last 5 bars)
                 + wick:body ≥ wick_ratio on N
    B — loose:   as A but N+1 closes in reversal direction relative to N's
                 close (regardless of colour) — same-coloured continuation
                 of an internal rejection (e.g. hammer) is allowed.
    C — hammer:  pierce by wick only on N AND N is itself the rejection
                 candle (bullish hammer on lower-band, bearish star on
                 upper-band) + N+1 same-coloured continuation. Not deployed
                 here; included for parity with the analysis detectors.

Geometry: SL/TP in pips; 8-bar / 40-min horizon is enforced downstream by
the standard timeout exit. Fire on the close of bar N+1 (the firing bar);
pattern N is always the previous closed 5m bar.

BB parameters: period=20, std_mult=2.0, population stdev — identical to
gbpusd_bb_bounce._bb_20_2 (and to scripts/analysis/bb_three_pattern/
features.compute_bb). Production drift here invalidates the Phase 6 EV
estimates so this is the single source of truth.

Fire rule: one fire per pattern detection. Re-arm only when the next bar
N is again an isolated wick-only pierce — i.e. the same trigger conditions
must recur. No additional gates are applied here. Universal blackouts
(news, briefing invalidation, concurrent-position cap, pair-concurrency
caps) are honoured downstream by strategy_logic._apply_exec_entry /
trade_executor.

Reference verification (2026-05-08 08:00 UTC GBPUSD, Phase 6 §Phase 6):
    Variant A: must NOT fire (both bars bullish, no colour flip)
    Variant B: must     fire (bullish follow-through after hammer)
    Variant C: must     fire (hammer N + bullish N+1)
The verification suite scripts/test_bb_pattern2_fade.py asserts this on
every smoke-test run.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("bb_pattern2_fade")


# ---------------------------------------------------------------------------
# Env helpers + module-wide gate
# ---------------------------------------------------------------------------
def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes")


BB_PATTERN2_FADE_ENABLED = _env_bool("BB_PATTERN2_FADE_ENABLED", "1")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BBPattern2Config:
    mode_name: str
    pair: str                  # "EURUSD", "USDJPY", "USDCAD"
    variant: str               # "A" (strict) | "B" (loose) | "C" (hammer)
    sl_pips: float
    tp_pips: float
    horizon_bars: int          # informational; timeout is set downstream
    wick_ratio: float          # min wick:body on the pierce side
    isolation_window: int      # pierce-isolation lookback in bars (5 for Phase 6)


DEFAULT_CONFIGS: Tuple[BBPattern2Config, ...] = (
    BBPattern2Config(
        mode_name="P2_EURUSD_A",
        pair="EURUSD",
        variant="A",
        sl_pips=12.0,
        tp_pips=30.0,
        horizon_bars=8,
        wick_ratio=1.5,
        isolation_window=5,
    ),
    BBPattern2Config(
        mode_name="P2_USDJPY_B",
        pair="USDJPY",
        variant="B",
        sl_pips=12.0,
        tp_pips=30.0,
        horizon_bars=8,
        wick_ratio=1.5,
        isolation_window=5,
    ),
    BBPattern2Config(
        mode_name="P2_USDCAD_A",
        pair="USDCAD",
        variant="A",
        sl_pips=12.0,
        tp_pips=30.0,
        horizon_bars=8,
        wick_ratio=1.5,
        isolation_window=5,
    ),
)


def _active_configs() -> Tuple[BBPattern2Config, ...]:
    keep = []
    for c in DEFAULT_CONFIGS:
        if _env_bool(f"{c.mode_name}_ENABLED", "1"):
            keep.append(c)
    return tuple(keep)


def _allowed_pairs() -> Tuple[str, ...]:
    return tuple(sorted({c.pair for c in _active_configs()}))


ALLOWED_PAIRS = frozenset(_allowed_pairs())

# Min bars required before the detector can run: 20 BB warmup + 1 prior bar
# (N-1 for the "isolated" lookback to be well-defined) + bar N + bar N+1.
# In practice Phase 6 used 20+ extra bars of warmup before the first window
# index; require 25 here as a conservative lower bound.
MIN_BARS = 25


# ---------------------------------------------------------------------------
# Indicator math (must match scripts/analysis/bb_three_pattern/features.py)
# ---------------------------------------------------------------------------
def _bb_20_2(window_closes: List[float], period: int = 20, std_mult: float = 2.0
             ) -> Tuple[float, float, float]:
    """Population-stdev BB on the trailing `period` closes (inclusive of
    the current bar). Identical to gbpusd_bb_bounce._bb_20_2 and to
    scripts/analysis/bb_three_pattern/features.compute_bb.

    Returns (lower, mid, upper).
    """
    w = window_closes[-period:]
    mid = sum(w) / period
    var = sum((c - mid) ** 2 for c in w) / period
    sd = math.sqrt(var)
    return mid - std_mult * sd, mid, mid + std_mult * sd


@dataclass
class _BarFeatures:
    """Features for a single bar — what the detector needs from N or N+1."""
    ts: Any
    open: float
    high: float
    low: float
    close: float
    bb_lower: float
    bb_mid: float
    bb_upper: float
    body_size: float
    is_bullish: bool
    is_bearish: bool
    upper_wick: float
    lower_wick: float
    upper_wick_to_body: float
    lower_wick_to_body: float
    pierce_upper: bool
    pierce_lower: bool
    body_close_above_upper: bool
    body_close_below_lower: bool
    wick_only_pierce_upper: bool
    wick_only_pierce_lower: bool


_EPS_BODY = 0.5  # cap denominator for wick:body — matches features.py eps


def _bar_features(o: float, h: float, l: float, c: float,
                  bbl: float, bbm: float, bbu: float, ts: Any) -> _BarFeatures:
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_for_ratio = body if body >= _EPS_BODY else _EPS_BODY
    pu = h > bbu
    pl = l < bbl
    bc_above = c > bbu
    bc_below = c < bbl
    return _BarFeatures(
        ts=ts, open=o, high=h, low=l, close=c,
        bb_lower=bbl, bb_mid=bbm, bb_upper=bbu,
        body_size=body,
        is_bullish=(c > o),
        is_bearish=(c < o),
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        upper_wick_to_body=upper_wick / body_for_ratio,
        lower_wick_to_body=lower_wick / body_for_ratio,
        pierce_upper=pu,
        pierce_lower=pl,
        body_close_above_upper=bc_above,
        body_close_below_lower=bc_below,
        wick_only_pierce_upper=pu and not bc_above,
        wick_only_pierce_lower=pl and not bc_below,
    )


def _compute_pierce_history(closes: List[float], highs: List[float], lows: List[float],
                            up_to_idx: int, period: int = 20):
    """Return ``(upper_pierce_flags, lower_pierce_flags)`` for bars
    ``[up_to_idx - period - 5 .. up_to_idx]`` so the detector can compute
    the prior-pierce isolation count. We keep this tight to bound work.

    Each flag list is aligned 1-to-1 with the index range and contains
    booleans (pierce_upper / pierce_lower).
    """
    # We just compute pierces on every bar from (up_to_idx - lookback) to
    # up_to_idx inclusive, against that bar's own BB (period closes ending
    # at the bar).
    # Caller passes the index range it cares about by slicing flags.
    n = up_to_idx + 1
    pu = [False] * n
    pl = [False] * n
    # Need at least `period` closes preceding (and including) bar i.
    for i in range(period - 1, n):
        bbl, _, bbu = _bb_20_2(closes[: i + 1], period=period)
        pu[i] = highs[i] > bbu
        pl[i] = lows[i] < bbl
    return pu, pl


# ---------------------------------------------------------------------------
# Detector — variant-aware fire decision for the LATEST closed bar (N+1)
# ---------------------------------------------------------------------------
@dataclass
class _DetectorResult:
    fire: bool
    direction: Optional[str]      # "BUY" | "SELL"
    pierce_side: Optional[str]    # "LOWER" | "UPPER"
    feat_n: Optional[_BarFeatures]
    feat_np1: Optional[_BarFeatures]
    prior_lower_pierces: int
    prior_upper_pierces: int
    reason: str                   # short fire-or-skip rationale


def _detect(closes: List[float], highs: List[float], lows: List[float],
            opens: List[float], timestamps: List[Any],
            cfg: BBPattern2Config) -> _DetectorResult:
    """Mirrors detect_p2 / detect_p2_strict / detect_p2_hammer in the
    analysis detectors — applied to the most recent closed bar (N+1).
    """
    n = len(closes)
    # Need bar N (idx n-2), bar N+1 (idx n-1), and full BB warmup at N.
    if n < 22:
        return _DetectorResult(False, None, None, None, None, 0, 0,
                               "insufficient_bars")

    idx_n = n - 2
    idx_np1 = n - 1

    # BB at N (uses closes[: idx_n + 1] = first idx_n+1 closes inclusive).
    bbl_n, bbm_n, bbu_n = _bb_20_2(closes[: idx_n + 1])
    bbl_np1, bbm_np1, bbu_np1 = _bb_20_2(closes[: idx_np1 + 1])

    feat_n = _bar_features(opens[idx_n], highs[idx_n], lows[idx_n], closes[idx_n],
                           bbl_n, bbm_n, bbu_n, timestamps[idx_n])
    feat_np1 = _bar_features(opens[idx_np1], highs[idx_np1], lows[idx_np1], closes[idx_np1],
                             bbl_np1, bbm_np1, bbu_np1, timestamps[idx_np1])

    # Pierce history needs `prior_*_pierces_5` evaluated at N+1: that is the
    # number of pierces in bars [idx_n-4, idx_n-3, idx_n-2, idx_n-1, idx_n].
    # The features module shifts(1) and rolls(5), so the resulting count at
    # N+1 includes bar N itself but excludes N+1.
    win = cfg.isolation_window
    earliest = idx_np1 - win
    if earliest < 0:
        return _DetectorResult(False, None, None, feat_n, feat_np1, 0, 0,
                               "iso_window_underflow")
    pu_hist, pl_hist = _compute_pierce_history(closes, highs, lows, up_to_idx=idx_n)
    prior_lower = sum(pl_hist[earliest: idx_np1])  # bars earliest..idx_n inclusive
    prior_upper = sum(pu_hist[earliest: idx_np1])

    iso_lower_at_np1 = (prior_lower == 1)  # exactly bar N itself
    iso_upper_at_np1 = (prior_upper == 1)

    # --- Common pierce gate on bar N -------------------------------------
    woc_lo = feat_n.wick_only_pierce_lower
    woc_up = feat_n.wick_only_pierce_upper
    wb_lo = feat_n.lower_wick_to_body
    wb_up = feat_n.upper_wick_to_body

    # --- Variant gates ---------------------------------------------------
    fire_lower = False
    fire_upper = False
    if cfg.variant == "A":
        # Strict: N+1 opposite-coloured to N (and N is bearish-or-doji on
        # lower side / bullish-or-doji on upper side).
        fire_lower = (
            woc_lo and (wb_lo >= cfg.wick_ratio) and iso_lower_at_np1
            and (not feat_n.is_bullish)         # N bearish or doji
            and feat_np1.is_bullish              # N+1 bullish
        )
        fire_upper = (
            woc_up and (wb_up >= cfg.wick_ratio) and iso_upper_at_np1
            and (not feat_n.is_bearish)
            and feat_np1.is_bearish
        )
    elif cfg.variant == "B":
        # Loose: follow-through close in reversal direction.
        ft_up = feat_np1.close > feat_n.close
        ft_dn = feat_np1.close < feat_n.close
        fire_lower = (
            woc_lo and (wb_lo >= cfg.wick_ratio) and iso_lower_at_np1 and ft_up
        )
        fire_upper = (
            woc_up and (wb_up >= cfg.wick_ratio) and iso_upper_at_np1 and ft_dn
        )
    elif cfg.variant == "C":
        # Hammer / shooting-star: N is the rejection candle, same-colour N+1.
        fire_lower = (
            woc_lo and (wb_lo >= cfg.wick_ratio) and iso_lower_at_np1
            and feat_n.is_bullish and feat_np1.is_bullish
        )
        fire_upper = (
            woc_up and (wb_up >= cfg.wick_ratio) and iso_upper_at_np1
            and feat_n.is_bearish and feat_np1.is_bearish
        )
    else:
        return _DetectorResult(False, None, None, feat_n, feat_np1,
                               prior_lower, prior_upper,
                               f"unknown_variant_{cfg.variant}")

    if fire_lower:
        return _DetectorResult(True, "BUY", "LOWER", feat_n, feat_np1,
                               prior_lower, prior_upper, f"variant_{cfg.variant}_lower")
    if fire_upper:
        return _DetectorResult(True, "SELL", "UPPER", feat_n, feat_np1,
                               prior_lower, prior_upper, f"variant_{cfg.variant}_upper")
    return _DetectorResult(False, None, None, feat_n, feat_np1,
                           prior_lower, prior_upper, "no_fire")


# ---------------------------------------------------------------------------
# Translation logging — first 5 fires per mode (matches PR #16 pattern).
# ---------------------------------------------------------------------------
_TRANSLATION_LOG_PATH = "logs/bb_pattern2_fade_translation.jsonl"
_TRANSLATION_MAX_PER_MODE = 5
_translation_counts: Dict[str, int] = {}
_translation_lock = threading.Lock()


def _maybe_log_translation(cfg: BBPattern2Config, det: _DetectorResult,
                           mid_price: float, epic: str, n_bars: int) -> None:
    """Emit a JSONL entry for the first N fires of each mode for offline
    forensic replay. Failures here MUST NOT block firing."""
    import json
    from datetime import datetime, timezone
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
        "variant": cfg.variant,
        "direction": det.direction,
        "pierce_side": det.pierce_side,
        "sl_pips": cfg.sl_pips,
        "tp_pips": cfg.tp_pips,
        "wick_ratio_threshold": cfg.wick_ratio,
        "isolation_window": cfg.isolation_window,
        "decision_entry": float(mid_price),
        "epic": epic,
        "n_bars_in_df": int(n_bars),
        "bar_n": _bar_payload(det.feat_n),
        "bar_np1": _bar_payload(det.feat_np1),
        "prior_lower_pierces_5": det.prior_lower_pierces,
        "prior_upper_pierces_5": det.prior_upper_pierces,
    }
    try:
        with open(_TRANSLATION_LOG_PATH, "a") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception as e:
        logger.warning("[%s] translation log write failed: %s", cfg.mode_name, e)


def _bar_payload(f: Optional[_BarFeatures]) -> Optional[Dict[str, Any]]:
    if f is None:
        return None
    return {
        "ts": str(f.ts),
        "open": f.open, "high": f.high, "low": f.low, "close": f.close,
        "bb_lower": f.bb_lower, "bb_mid": f.bb_mid, "bb_upper": f.bb_upper,
        "body_size": f.body_size,
        "is_bullish": bool(f.is_bullish), "is_bearish": bool(f.is_bearish),
        "upper_wick": f.upper_wick, "lower_wick": f.lower_wick,
        "upper_wick_to_body": f.upper_wick_to_body,
        "lower_wick_to_body": f.lower_wick_to_body,
        "pierce_upper": bool(f.pierce_upper), "pierce_lower": bool(f.pierce_lower),
        "wick_only_pierce_upper": bool(f.wick_only_pierce_upper),
        "wick_only_pierce_lower": bool(f.wick_only_pierce_lower),
    }


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
@dataclass
class _ConfigState:
    last_bar_ts: Optional[Any] = None  # within-bar dedup


class BBPattern2FadeStrategy:
    """Singleton strategy object — one instance per process."""

    _instance: "Optional[BBPattern2FadeStrategy]" = None

    def __init__(self) -> None:
        self._state: Dict[str, _ConfigState] = {
            c.mode_name: _ConfigState() for c in DEFAULT_CONFIGS
        }
        self._lock = threading.Lock()

    # ---- helpers ----
    @staticmethod
    def _none(sym: str, mode: str, reason: str) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym, regime="DISPATCH", signal="NONE", mode=mode,
            entry=None, sl=None, tp=None, use_trailing_stop=False,
            reason=reason,
        )

    # ---- main entry ----
    def evaluate(
        self,
        symbol: str,
        epic: str,
        df_in: pd.DataFrame,
        pip_size: float,
        mid_price: float,
        briefing: Dict,
    ) -> "StrategyDecision":
        sym = str(symbol or "").upper()

        if df_in is None or "close" not in df_in.columns:
            return self._none(sym, "BB_PATTERN2_FADE", "p2_no_df")
        if len(df_in) < MIN_BARS:
            return self._none(sym, "BB_PATTERN2_FADE", "p2_insufficient_bars")

        active = [c for c in _active_configs() if c.pair == sym]
        if not active:
            return self._none(sym, "BB_PATTERN2_FADE", "p2_pair_not_in_scope")

        # Build aligned float arrays once. Tolerate either a 'timestamp' col
        # or a DatetimeIndex.
        try:
            opens = [float(x) for x in df_in["open"].tolist()]
            highs = [float(x) for x in df_in["high"].tolist()]
            lows = [float(x) for x in df_in["low"].tolist()]
            closes = [float(x) for x in df_in["close"].tolist()]
        except Exception as e:
            logger.warning("[BB_PATTERN2_FADE] OHLC extraction failed: %s", e)
            return self._none(sym, "BB_PATTERN2_FADE", "p2_ohlc_extract_fail")
        if "timestamp" in df_in.columns:
            timestamps = list(df_in["timestamp"])
        else:
            timestamps = list(df_in.index)
        try:
            last_bar_ts = timestamps[-1]
        except Exception:
            last_bar_ts = None

        fired_decision: Optional["StrategyDecision"] = None

        with self._lock:
            for cfg in active:
                state = self._state[cfg.mode_name]

                # Within-bar dedup.
                if (state.last_bar_ts is not None and last_bar_ts is not None
                        and state.last_bar_ts == last_bar_ts):
                    continue

                det = _detect(closes, highs, lows, opens, timestamps, cfg)
                state.last_bar_ts = last_bar_ts

                if not det.fire or fired_decision is not None:
                    continue

                # We have a fire — translation log + signal_log debug payload.
                try:
                    _maybe_log_translation(cfg, det, float(mid_price), epic,
                                           len(df_in))
                except Exception as e:
                    logger.warning("[%s] translation log raise: %s",
                                   cfg.mode_name, e)

                logger.info(
                    "[%s] FIRE %s | bar_np1=%s side=%s wb=%.2f iso_lower=%d "
                    "iso_upper=%d SL=%.1fp TP=%.1fp mid=%.5f",
                    cfg.mode_name, det.direction, last_bar_ts, det.pierce_side,
                    (det.feat_n.lower_wick_to_body if det.pierce_side == "LOWER"
                     else det.feat_n.upper_wick_to_body),
                    det.prior_lower_pierces, det.prior_upper_pierces,
                    cfg.sl_pips, cfg.tp_pips, float(mid_price),
                )
                fired_decision = self._build_decision(
                    cfg, sym, mid_price, det, last_bar_ts,
                )

        if fired_decision is not None:
            return fired_decision
        return self._none(sym, "BB_PATTERN2_FADE", "p2_no_signal")

    def _build_decision(
        self,
        cfg: BBPattern2Config,
        sym: str,
        mid_price: float,
        det: _DetectorResult,
        bar_ts: Any,
    ) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        # Pull the wick:body actually used by the detector (the relevant side).
        wb_used = (det.feat_n.lower_wick_to_body if det.pierce_side == "LOWER"
                   else det.feat_n.upper_wick_to_body)
        return StrategyDecision(
            symbol=sym,
            regime="BB_PATTERN2_FADE",
            signal=det.direction,
            mode=cfg.mode_name,
            entry=float(mid_price),
            sl=float(cfg.sl_pips),
            tp=float(cfg.tp_pips),
            use_trailing_stop=False,
            reason=f"bb_pattern2_fade_{det.direction.lower() if det.direction else 'none'}",
            debug={
                "entry_source": "bb_pattern2_fade",
                "config_mode": cfg.mode_name,
                "variant": cfg.variant,
                "pair": cfg.pair,
                "pierce_side": det.pierce_side,
                "wick_ratio_threshold": cfg.wick_ratio,
                "wick_to_body_at_fire": float(wb_used),
                "isolation_window": cfg.isolation_window,
                "prior_lower_pierces_in_window": int(det.prior_lower_pierces),
                "prior_upper_pierces_in_window": int(det.prior_upper_pierces),
                "bar_n_open": float(det.feat_n.open),
                "bar_n_high": float(det.feat_n.high),
                "bar_n_low": float(det.feat_n.low),
                "bar_n_close": float(det.feat_n.close),
                "bar_n_bb_lower": float(det.feat_n.bb_lower),
                "bar_n_bb_upper": float(det.feat_n.bb_upper),
                "bar_n_is_bullish": bool(det.feat_n.is_bullish),
                "bar_np1_is_bullish": bool(det.feat_np1.is_bullish),
                "bar_np1_close": float(det.feat_np1.close),
                "sl_pips": cfg.sl_pips,
                "tp_pips": cfg.tp_pips,
                "horizon_bars": cfg.horizon_bars,
                "bar_ts": str(bar_ts),
                "search_provenance": (
                    "reports/bb_three_pattern_analysis_20260510.md "
                    "Phase 6 — strict/loose/hammer variants"
                ),
            },
        )


# ---------------------------------------------------------------------------
# Convenience for autobot startup logging.
# ---------------------------------------------------------------------------
def configs_summary() -> List[Dict[str, Any]]:
    return [
        {
            "mode_name": c.mode_name,
            "pair": c.pair,
            "variant": c.variant,
            "sl_pips": c.sl_pips,
            "tp_pips": c.tp_pips,
            "horizon_bars": c.horizon_bars,
            "wick_ratio": c.wick_ratio,
            "isolation_window": c.isolation_window,
            "enabled": _env_bool(f"{c.mode_name}_ENABLED", "1"),
        }
        for c in DEFAULT_CONFIGS
    ]


__all__ = [
    "BBPattern2FadeStrategy",
    "BBPattern2Config",
    "DEFAULT_CONFIGS",
    "ALLOWED_PAIRS",
    "BB_PATTERN2_FADE_ENABLED",
    "MIN_BARS",
    "configs_summary",
]
