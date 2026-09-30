"""macd_extreme_fade — MACD-line extreme fade strategy, parameterised by config.

Fires LONG when the MACD line drops below a deep negative threshold
(oversold momentum bounce) or SHORT when it rises above a high positive
threshold (overbought momentum fade). One configuration per (pair, direction)
tuple.

Discovered by the full-search pipeline (reports/full_search_strategy_discovery_
20260510.md). One config is shipped here as the first batch of the deployable
subset (reports/full_search_deployable_subset_20260510.md):

    MACD_EXTREME_GBPUSD_LONG  MACD(12,26) < -6.1434  → BUY  SL=30  TP=40

MACD configuration (locked, hard-verified vs the search):
    - MACD line = EMA(close, 12) - EMA(close, 26)
    - signal/histogram NOT consulted by the fire rule (search-time rule was
      on the LINE only)
    - fast=12, slow=26, signal=9 (signal kept for forensic completeness)
    - price series: per-field-mid 5m close (the 'close' column from prod 5m bars)
    - EMA: pd.Series.ewm(span=N, adjust=False, min_periods=N).mean()
The math is sourced from extreme_fade_indicators.macd_line, which is the
same function used by scripts/analysis/full_search/features.py:macd.

Fire rule: single fire per threshold crossing. After a fire the config is
disarmed; it re-arms only when the MACD line re-crosses back to the
non-breach side on a subsequent bar.

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

from extreme_fade_indicators import macd_line as compute_macd_line
import extreme_fade_translation as _xft

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("macd_extreme_fade")


def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes")


# Module-wide enable flag; per-config flags below.
MACD_EXTREME_FADE_ENABLED = _env_bool("MACD_EXTREME_FADE_ENABLED", "1")


@dataclass(frozen=True)
class MacdFadeConfig:
    mode_name: str
    pair: str               # "GBPUSD", ...
    direction: str          # "BUY" or "SELL"
    fast: int
    slow: int
    signal: int             # not consulted by fire rule, retained for forensic
    threshold: float
    op: str                 # ">" → fire when macd > threshold (overbought fade SHORT)
                            # "<" → fire when macd < threshold (oversold fade LONG)
    sl_pips: float
    tp_pips: float


DEFAULT_CONFIGS: Tuple[MacdFadeConfig, ...] = (
    MacdFadeConfig(
        mode_name="MACD_EXTREME_GBPUSD_LONG",
        pair="GBPUSD",
        direction="BUY",
        fast=12,
        slow=26,
        signal=9,
        threshold=-6.1434,
        op="<",
        sl_pips=30.0,
        tp_pips=40.0,
    ),
)


def _active_configs() -> Tuple[MacdFadeConfig, ...]:
    keep = []
    for c in DEFAULT_CONFIGS:
        flag = f"{c.mode_name}_ENABLED"
        if _env_bool(flag, "1"):
            keep.append(c)
    return tuple(keep)


def _allowed_pairs() -> Tuple[str, ...]:
    return tuple(sorted({c.pair for c in _active_configs()}))


ALLOWED_PAIRS = frozenset(_allowed_pairs())


@dataclass
class _ConfigState:
    armed: bool = True
    last_bar_ts: Optional[pd.Timestamp] = None


class MacdExtremeFadeStrategy:
    _instance: "Optional[MacdExtremeFadeStrategy]" = None

    def __init__(self):
        self._state: Dict[str, _ConfigState] = {
            c.mode_name: _ConfigState() for c in DEFAULT_CONFIGS
        }
        self._lock = threading.Lock()

    @staticmethod
    def _none(sym: str, mode: str, reason: str) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym, regime="DISPATCH", signal="NONE", mode=mode,
            entry=None, sl=None, tp=None, use_trailing_stop=False,
            reason=reason,
        )

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
            return self._none(sym, "MACD_EXTREME_FADE", "macd_fade_no_df")
        # MACD(12,26) needs at least 26 bars of close to even produce a
        # non-NaN line; require a small buffer beyond that.
        if len(df_in) < 30:
            return self._none(sym, "MACD_EXTREME_FADE", "macd_fade_insufficient_bars")

        active = [c for c in _active_configs() if c.pair == sym]
        if not active:
            return self._none(sym, "MACD_EXTREME_FADE", "macd_fade_pair_not_in_scope")

        closes = df_in["close"].astype(float)
        try:
            last_bar_ts = df_in.index[-1]
        except Exception:
            last_bar_ts = None

        # Cache MACD line per (fast, slow) tuple — typically just (12, 26).
        macd_by_pair_cfg: Dict[Tuple[int, int], pd.Series] = {}
        for c in active:
            key = (c.fast, c.slow)
            if key not in macd_by_pair_cfg:
                macd_by_pair_cfg[key] = compute_macd_line(closes, fast=c.fast, slow=c.slow)

        fired_decision: Optional["StrategyDecision"] = None

        with self._lock:
            for cfg in active:
                state = self._state[cfg.mode_name]

                if state.last_bar_ts is not None and last_bar_ts is not None and state.last_bar_ts == last_bar_ts:
                    continue

                line = macd_by_pair_cfg[(cfg.fast, cfg.slow)]
                val = line.iloc[-1]
                if pd.isna(val):
                    state.last_bar_ts = last_bar_ts
                    continue

                val_f = float(val)
                in_breach = (cfg.op == ">" and val_f > cfg.threshold) or \
                            (cfg.op == "<" and val_f < cfg.threshold)

                if not in_breach and not state.armed:
                    state.armed = True
                    logger.info(
                        "[%s] re-armed — MACD=%.4f back inside threshold (%s%.4f)",
                        cfg.mode_name, val_f, cfg.op, cfg.threshold,
                    )

                if in_breach and state.armed and fired_decision is None:
                    state.armed = False
                    state.last_bar_ts = last_bar_ts

                    try:
                        ref_line = compute_macd_line(closes, fast=cfg.fast, slow=cfg.slow).iloc[-1]
                    except Exception:
                        ref_line = float("nan")
                    try:
                        _xft.maybe_log_fire(
                            mode=cfg.mode_name,
                            pair=cfg.pair,
                            direction=cfg.direction,
                            bar_ts=last_bar_ts,
                            closes_tail=closes,
                            indicator_name=f"macd_line_{cfg.fast}_{cfg.slow}",
                            production_value=val_f,
                            reference_value=float(ref_line),
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
                                "macd_fast": cfg.fast,
                                "macd_slow": cfg.slow,
                                "macd_signal": cfg.signal,
                            },
                        )
                    except Exception as _xft_err:
                        logger.warning("[%s] translation log failure: %s",
                                       cfg.mode_name, _xft_err)

                    logger.info(
                        "[%s] FIRE %s | bar=%s MACD(%d,%d)=%.4f %s threshold=%.4f "
                        "SL=%.1fp TP=%.1fp mid=%.5f",
                        cfg.mode_name, cfg.direction, last_bar_ts,
                        cfg.fast, cfg.slow, val_f, cfg.op, cfg.threshold,
                        cfg.sl_pips, cfg.tp_pips, float(mid_price),
                    )
                    fired_decision = self._build_decision(cfg, sym, mid_price, val_f, last_bar_ts)
                else:
                    state.last_bar_ts = last_bar_ts

        if fired_decision is not None:
            return fired_decision
        return self._none(sym, "MACD_EXTREME_FADE", "macd_fade_no_signal")

    def _build_decision(
        self,
        cfg: MacdFadeConfig,
        sym: str,
        mid_price: float,
        macd_val: float,
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
            reason=f"macd_extreme_fade_{cfg.direction.lower()}",
            debug={
                "entry_source": "macd_extreme_fade",
                "config_mode": cfg.mode_name,
                "macd_fast": cfg.fast,
                "macd_slow": cfg.slow,
                "macd_signal": cfg.signal,
                "macd_at_fire": float(macd_val),
                "macd_threshold": cfg.threshold,
                "macd_op": cfg.op,
                "sl_pips": cfg.sl_pips,
                "tp_pips": cfg.tp_pips,
                "bar_ts": str(bar_ts),
                "search_provenance": (
                    "scripts/analysis/full_search/ranked_strategies.parquet "
                    "→ reports/full_search_deployable_subset_20260510.md"
                ),
            },
        )


def configs_summary() -> List[Dict[str, Any]]:
    return [
        {
            "mode_name": c.mode_name,
            "pair": c.pair,
            "direction": c.direction,
            "fast": c.fast,
            "slow": c.slow,
            "signal": c.signal,
            "threshold": c.threshold,
            "op": c.op,
            "sl_pips": c.sl_pips,
            "tp_pips": c.tp_pips,
            "enabled": _env_bool(f"{c.mode_name}_ENABLED", "1"),
        }
        for c in DEFAULT_CONFIGS
    ]
