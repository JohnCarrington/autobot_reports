"""rsi_extreme_fade — RSI-extreme fade strategy, parameterised by config.

Fires SHORT when RSI breaches an upper threshold (overbought fade) or LONG
when RSI breaches a lower threshold (oversold fade). One configuration per
(pair, direction) tuple.

Discovered by the full-search pipeline (reports/full_search_strategy_discovery_
20260510.md). Two configs are shipped here as the first batch of the
deployable subset (reports/full_search_deployable_subset_20260510.md):

    RSI_FADE_GBPUSD_SHORT  RSI(14) > 69.4319  → SELL  SL=30  TP=20
    RSI_FADE_USDJPY_LONG   RSI(14) < 35.7358  → BUY   SL=20  TP=20

Indicator math is identical to scripts/analysis/full_search/features.py:rsi
(re-exported via extreme_fade_indicators.py) so production matches the
search byte-for-byte. Production discrepancy invalidates the EV estimates,
so any non-trivial divergence is surfaced by extreme_fade_translation.py.

Fire rule: single fire per threshold crossing. After a fire, the config is
disarmed; it re-arms only when the indicator re-crosses back to the
non-breach side (i.e. RSI < threshold for SHORT-overbought, RSI > threshold
for LONG-oversold) on a subsequent bar.

No additional gates are applied here. Universal blackouts (news, briefing
invalidation, concurrent-position cap, pair-concurrency caps) are honoured
by strategy_logic._apply_exec_entry / trade_executor downstream.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import pandas as pd

from extreme_fade_indicators import rsi as compute_rsi
import extreme_fade_translation as _xft

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("rsi_extreme_fade")


def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes")


# Module-wide enable flag; per-config flags below.
RSI_EXTREME_FADE_ENABLED = _env_bool("RSI_EXTREME_FADE_ENABLED", "1")


@dataclass(frozen=True)
class RsiFadeConfig:
    mode_name: str
    pair: str               # "GBPUSD", "EURUSD", "USDJPY", "USDCAD"
    direction: str          # "BUY" (LONG) or "SELL" (SHORT)
    rsi_period: int
    threshold: float
    op: str                 # ">" → fire when rsi > threshold (overbought fade SHORT)
                            # "<" → fire when rsi < threshold (oversold fade LONG)
    sl_pips: float
    tp_pips: float


# Default configurations — exact thresholds from
# data/analysis/full_search/ranked_strategies.parquet (top-deployable subset
# picks #1 and #5).
DEFAULT_CONFIGS: Tuple[RsiFadeConfig, ...] = (
    RsiFadeConfig(
        mode_name="RSI_FADE_GBPUSD_SHORT",
        pair="GBPUSD",
        direction="SELL",
        rsi_period=14,
        threshold=69.4319,
        op=">",
        sl_pips=30.0,
        tp_pips=20.0,
    ),
    RsiFadeConfig(
        mode_name="RSI_FADE_USDJPY_LONG",
        pair="USDJPY",
        direction="BUY",
        rsi_period=14,
        threshold=35.7358,
        op="<",
        sl_pips=20.0,
        tp_pips=20.0,
    ),
)


def _active_configs() -> Tuple[RsiFadeConfig, ...]:
    """Return configs honouring per-mode env disable flags.
    Per-mode flag name: <MODE_NAME>_ENABLED (default 1).
    """
    keep = []
    for c in DEFAULT_CONFIGS:
        flag = f"{c.mode_name}_ENABLED"
        if _env_bool(flag, "1"):
            keep.append(c)
    return tuple(keep)


# Pair-allow-list for log/diagnostic output. Computed from active configs.
def _allowed_pairs() -> Tuple[str, ...]:
    return tuple(sorted({c.pair for c in _active_configs()}))


# Module attribute name 'ALLOWED_PAIRS' is conventional in production
# (mirrors exhaustion_reversal.py) — used by autobot startup logging to
# surface scope.
ALLOWED_PAIRS = frozenset(_allowed_pairs())


@dataclass
class _ConfigState:
    """Per-config in-memory state — armed/disarmed + last-bar timestamp.

    armed=True means the next breach fires.
    armed=False means the indicator is currently in the breach zone OR a
    fire has just happened; we wait for the indicator to leave the zone
    before re-arming.
    """
    armed: bool = True
    last_bar_ts: Optional[pd.Timestamp] = None


class RsiExtremeFadeStrategy:
    """Singleton strategy object — instantiated once per process by
    strategy_logic.evaluate_signals dispatch."""

    _instance: "Optional[RsiExtremeFadeStrategy]" = None

    def __init__(self):
        # Per-config state, keyed by mode_name.
        self._state: Dict[str, _ConfigState] = {
            c.mode_name: _ConfigState() for c in DEFAULT_CONFIGS
        }
        self._lock = threading.Lock()

    # ---------------- helpers ----------------

    @staticmethod
    def _none(sym: str, mode: str, reason: str) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym, regime="DISPATCH", signal="NONE", mode=mode,
            entry=None, sl=None, tp=None, use_trailing_stop=False,
            reason=reason,
        )

    # ---------------- evaluate ----------------

    def evaluate(
        self,
        symbol: str,
        epic: str,
        df_in: pd.DataFrame,
        pip_size: float,
        mid_price: float,
        briefing: Dict,
    ) -> "StrategyDecision":
        """Dispatch entrypoint — called once per closed 5m bar.

        Iterates all active configs whose pair matches `symbol`. The first
        config that fires returns a BUY/SELL StrategyDecision; the rest are
        evaluated for state-update purposes (re-arm on non-breach) but
        cannot fire on the same call.
        """
        sym = str(symbol or "").upper()

        # --- min warmup ---
        if df_in is None or "close" not in df_in.columns:
            return self._none(sym, "RSI_EXTREME_FADE", "rsi_fade_no_df")
        if len(df_in) < 16:    # RSI(14) needs at least 14 + 2 for stable smoothing
            return self._none(sym, "RSI_EXTREME_FADE", "rsi_fade_insufficient_bars")

        active = [c for c in _active_configs() if c.pair == sym]
        if not active:
            return self._none(sym, "RSI_EXTREME_FADE", "rsi_fade_pair_not_in_scope")

        closes = df_in["close"].astype(float)
        # Identify the latest closed bar — index of df_in is the bar bucket
        # start timestamp in production (5m candle DataFrames). Use the last
        # row's index for state-bookkeeping to dedupe re-evaluations within
        # the same bar.
        try:
            last_bar_ts = df_in.index[-1]
        except Exception:
            last_bar_ts = None

        # Pre-compute RSI for all configured periods that any active config
        # uses (almost always {14}; futureproofs different periods).
        periods = sorted({c.rsi_period for c in active})
        rsi_by_period: Dict[int, pd.Series] = {
            n: compute_rsi(closes, n=n) for n in periods
        }

        fired_decision: Optional["StrategyDecision"] = None

        with self._lock:
            for cfg in active:
                state = self._state[cfg.mode_name]

                # Within-bar dedup: if we already processed this exact bar
                # for this config, do not re-evaluate (prevents accidental
                # multi-fire from upstream callers).
                if state.last_bar_ts is not None and last_bar_ts is not None and state.last_bar_ts == last_bar_ts:
                    continue

                rsi_series = rsi_by_period[cfg.rsi_period]
                rsi_val = rsi_series.iloc[-1]
                # Warm-up — RSI is NaN until period bars have closed.
                if pd.isna(rsi_val):
                    state.last_bar_ts = last_bar_ts
                    continue

                rsi_val_f = float(rsi_val)
                in_breach = (cfg.op == ">" and rsi_val_f > cfg.threshold) or \
                            (cfg.op == "<" and rsi_val_f < cfg.threshold)

                # Re-arm: when indicator returns to the non-breach side, the
                # next breach is a fresh signal.
                if not in_breach and not state.armed:
                    state.armed = True
                    logger.info(
                        "[%s] re-armed — RSI=%.2f back inside threshold (%s%.4f)",
                        cfg.mode_name, rsi_val_f, cfg.op, cfg.threshold,
                    )

                if in_breach and state.armed and fired_decision is None:
                    # Build the fire decision. Production fires at bar-close
                    # mid; trade_executor down-stream injects realistic
                    # bid/ask exec via _apply_exec_entry (matches the harness
                    # convention: LONG entry @ ask, SHORT entry @ bid).
                    state.armed = False
                    state.last_bar_ts = last_bar_ts

                    # Translation validation — first 5 fires per mode get
                    # logged with reference indicator recompute. Reference
                    # indicator IS the production indicator here (same
                    # function), so this hook also serves as a tripwire for
                    # any future code drift between this module and the
                    # shared indicators module.
                    try:
                        ref_rsi = compute_rsi(closes, n=cfg.rsi_period).iloc[-1]
                    except Exception:
                        ref_rsi = float("nan")
                    try:
                        _xft.maybe_log_fire(
                            mode=cfg.mode_name,
                            pair=cfg.pair,
                            direction=cfg.direction,
                            bar_ts=last_bar_ts,
                            closes_tail=closes,
                            indicator_name="rsi_14",
                            production_value=rsi_val_f,
                            reference_value=float(ref_rsi),
                            threshold=cfg.threshold,
                            op=cfg.op,
                            sl_pips_actual=cfg.sl_pips,
                            tp_pips_actual=cfg.tp_pips,
                            sl_pips_configured=cfg.sl_pips,
                            tp_pips_configured=cfg.tp_pips,
                            decision_entry=float(mid_price),
                            extras={
                                "epic": epic,
                                "pip_size": float(pip_size),
                                "n_bars_in_df": int(len(df_in)),
                            },
                        )
                    except Exception as _xft_err:
                        logger.warning("[%s] translation log failure: %s",
                                       cfg.mode_name, _xft_err)

                    logger.info(
                        "[%s] FIRE %s | bar=%s RSI%d=%.2f %s threshold=%.4f "
                        "SL=%.1fp TP=%.1fp mid=%.5f",
                        cfg.mode_name, cfg.direction, last_bar_ts,
                        cfg.rsi_period, rsi_val_f, cfg.op, cfg.threshold,
                        cfg.sl_pips, cfg.tp_pips, float(mid_price),
                    )
                    fired_decision = self._build_decision(cfg, sym, mid_price, rsi_val_f, last_bar_ts)
                else:
                    if in_breach and not state.armed:
                        # Already fired on a previous bar in this breach;
                        # silent — wait for re-arm.
                        pass
                    state.last_bar_ts = last_bar_ts

        if fired_decision is not None:
            return fired_decision
        return self._none(sym, "RSI_EXTREME_FADE", "rsi_fade_no_signal")

    def _build_decision(
        self,
        cfg: RsiFadeConfig,
        sym: str,
        mid_price: float,
        rsi_val: float,
        bar_ts: Any,
    ) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym,
            regime="EXTREME_FADE",
            signal=cfg.direction,
            mode=cfg.mode_name,
            entry=float(mid_price),
            sl=float(cfg.sl_pips),
            tp=float(cfg.tp_pips),
            use_trailing_stop=False,
            reason=f"rsi_extreme_fade_{cfg.direction.lower()}",
            debug={
                "entry_source": "rsi_extreme_fade",
                "config_mode": cfg.mode_name,
                "rsi_period": cfg.rsi_period,
                "rsi_at_fire": float(rsi_val),
                "rsi_threshold": cfg.threshold,
                "rsi_op": cfg.op,
                "sl_pips": cfg.sl_pips,
                "tp_pips": cfg.tp_pips,
                "bar_ts": str(bar_ts),
                "search_provenance": (
                    "scripts/analysis/full_search/ranked_strategies.parquet "
                    "→ reports/full_search_deployable_subset_20260510.md"
                ),
            },
        )


# Convenience re-exports for autobot startup logging.
def configs_summary() -> List[Dict[str, Any]]:
    return [
        {
            "mode_name": c.mode_name,
            "pair": c.pair,
            "direction": c.direction,
            "rsi_period": c.rsi_period,
            "threshold": c.threshold,
            "op": c.op,
            "sl_pips": c.sl_pips,
            "tp_pips": c.tp_pips,
            "enabled": _env_bool(f"{c.mode_name}_ENABLED", "1"),
        }
        for c in DEFAULT_CONFIGS
    ]
