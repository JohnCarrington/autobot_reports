"""Era B exit / management simulator, independent of entry.

Rules (spec §3.2, §3.3, §3.7):
  - Hard SL at entry ± SL_PIPS
  - +10p MFE → close SCALE_OUT_FRACTION at that price, runner SL → BE
  - Broker TP at entry ± BROKER_TP_PIPS
  - Max hold MAX_HOLD_BARS bars (240 min for BB_PIERCE_RUN)

Within-bar order: ADVERSE_FIRST (config).

Reproduces the subset of Era B exits that 5m OHLC can decide:
  SL_HIT, TP_HIT, SCALE_OUT_BE (runner hit BE), SCALE_OUT_TP (runner
  hit broker TP), REGIME_MAX_HOLD (fell through).

Does NOT reproduce (see config.UNREPRODUCIBLE_CLOSE_REASONS):
  TRAIL_STOP, QM_BAND_CLOSE_INSIDE, BRIEFING_TP_SL_OPEN,
  BRIEFING_TP1_CLOSE, STRUCTURE_EXIT, BB_FLIP, BB_RANGE_TARGET,
  EXTERNAL_MANUAL, IG_RECONCILE, LABEL_K_OPERATOR, PRE_NEWS_CLOSE,
  NY_CLOSE, EXIT_PROFILE_SQUEEZE, AUTO_K_PREMISE, MANAGER_PROFIT_PROTECT,
  BE_HIT_IG (broker-side vs our within-bar approximation), etc.

IG order submission: not imported. The manager is a pure function of
(signal, downstream bar stream).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from . import config
from .candles import Bar
from .entry import Signal


# ─── result dataclasses ─────────────────────────────────────────────────

@dataclass
class PartialClose:
    ts_utc:           datetime   # bar CLOSE time of the bar that triggered the partial
    price:            float
    fraction_closed:  float
    pips_banked:      float
    reason:           str        # "SCALE_OUT"


@dataclass
class FinalClose:
    ts_utc:            datetime  # bar CLOSE time of the bar that terminated the trade
    price:             float
    reason:            str       # "SL_HIT" | "TP_HIT" | "SCALE_OUT_BE" | "SCALE_OUT_TP" | "REGIME_MAX_HOLD" | "REGIME_MAX_HOLD_SCALED"
    fraction_closed:   float
    pips:              float     # signed contribution to total (for runner)


@dataclass
class ExitReport:
    signal:            Signal
    partials:          List[PartialClose] = field(default_factory=list)
    final:             Optional[FinalClose] = None
    mfe_pips:          float = 0.0
    mae_pips:          float = 0.0
    duration_bars:     int = 0
    scaled_out:        bool = False

    @property
    def total_pips(self) -> float:
        """Weighted realised pips at the signal's stake (per pip * fraction)."""
        pips = 0.0
        for p in self.partials:
            pips += p.pips_banked * p.fraction_closed
        if self.final is not None:
            pips += self.final.pips * self.final.fraction_closed
        return round(pips, 2)

    @property
    def total_gbp_at_stake1(self) -> float:
        return round(self.total_pips * config.STAKE_GBP_PER_PIP, 2)


# ─── simulator ──────────────────────────────────────────────────────────

def _pips_from_units(units: float) -> float:
    return units / config.PIP_UNITS


def _units_from_pips(pips: float) -> float:
    return pips * config.PIP_UNITS


def simulate(signal: Signal, downstream: List[Bar]) -> ExitReport:
    """Run the 4-exit manager against a SHORT signal.

    `downstream` is the 5m bar stream starting at the rejection bar
    N+1 (the first bar AFTER the fire) OR at the rejection bar itself,
    the caller's choice. Semantic clarification for this benchmark:
    the actual code enters at cur.close of the rejection bar (N),
    so the FIRST bar of forward management is bar N+1 (the strategy
    logs the fire at bar N close then leaves management to
    trade_manager on subsequent ticks). We therefore expect the
    caller to pass bars starting at rejection.close_ts (i.e., the bar
    whose open == rejection.close_ts, which is bar N+1).

    A single-bar SL / TP / scale-out check on the entry bar (N) is
    NOT done here — the market SELL executed at N.close, and the
    remainder of N is not knowable from OHLC alone.
    """
    assert signal.direction == "SELL", "SHORT-only benchmark"
    entry = signal.entry_price

    sl_price = entry + _units_from_pips(config.SL_PIPS)
    tp_price = entry - _units_from_pips(config.BROKER_TP_PIPS)
    so_price = entry - _units_from_pips(config.SCALE_OUT_TRIGGER_PIPS)
    be_price = entry + _units_from_pips(config.RUNNER_BE_OFFSET_PIPS)

    report = ExitReport(signal=signal)
    scaled_out = False
    runner_frac = 1.0    # fraction of the position still open
    banked_pips = 0.0    # pips locked by scale-out (per unit stake)

    for idx, bar in enumerate(downstream[:config.MAX_HOLD_BARS], start=1):
        report.duration_bars = idx
        bar_high = bar.high
        bar_low  = bar.low

        # Track MFE / MAE (for a SHORT: favorable = down)
        f_pips = _pips_from_units(entry - bar_low)   # positive when price fell
        a_pips = _pips_from_units(bar_high - entry)  # positive when price rose
        if f_pips > report.mfe_pips: report.mfe_pips = round(f_pips, 2)
        if a_pips > report.mae_pips: report.mae_pips = round(a_pips, 2)

        if not scaled_out:
            # ADVERSE FIRST: SL check before scale-out / TP
            if config.ADVERSE_FIRST:
                if bar_high >= sl_price:
                    report.final = FinalClose(
                        ts_utc=bar.close_ts, price=sl_price, reason="SL_HIT",
                        fraction_closed=1.0, pips=-config.SL_PIPS,
                    )
                    return report
                if bar_low <= tp_price:
                    report.final = FinalClose(
                        ts_utc=bar.close_ts, price=tp_price, reason="TP_HIT",
                        fraction_closed=1.0, pips=config.BROKER_TP_PIPS,
                    )
                    return report
                if bar_low <= so_price:
                    # Scale-out: bank +10p on SCALE_OUT_FRACTION, runner remains
                    banked_pips = config.SCALE_OUT_TRIGGER_PIPS
                    frac = config.SCALE_OUT_FRACTION
                    report.partials.append(PartialClose(
                        ts_utc=bar.close_ts, price=so_price,
                        fraction_closed=frac, pips_banked=banked_pips,
                        reason="SCALE_OUT",
                    ))
                    scaled_out = True
                    report.scaled_out = True
                    runner_frac = 1.0 - frac
                    # Same-bar rebound test for runner BE (SL is now BE)
                    if bar_high >= be_price:
                        report.final = FinalClose(
                            ts_utc=bar.close_ts, price=be_price,
                            reason="SCALE_OUT_BE", fraction_closed=runner_frac,
                            pips=0.0,
                        )
                        return report
                    continue
            else:
                # Not used (ADVERSE_FIRST hard-coded ON), but present for
                # symmetry if a future study wants to sensitivity-test.
                raise NotImplementedError("ADVERSE_FIRST=False disabled")
            continue

        # Runner active: SL is BE, TP is broker TP (unchanged)
        if bar_high >= be_price:
            report.final = FinalClose(
                ts_utc=bar.close_ts, price=be_price,
                reason="SCALE_OUT_BE", fraction_closed=runner_frac, pips=0.0,
            )
            return report
        if bar_low <= tp_price:
            report.final = FinalClose(
                ts_utc=bar.close_ts, price=tp_price,
                reason="SCALE_OUT_TP", fraction_closed=runner_frac,
                pips=config.BROKER_TP_PIPS,
            )
            return report

    # Fell through MAX_HOLD_BARS
    last = downstream[report.duration_bars - 1] if downstream else None
    if last is None:
        return report
    exit_pips = _pips_from_units(entry - last.close)
    if scaled_out:
        report.final = FinalClose(
            ts_utc=last.close_ts, price=last.close,
            reason="REGIME_MAX_HOLD_SCALED", fraction_closed=runner_frac,
            pips=round(exit_pips, 2),
        )
    else:
        report.final = FinalClose(
            ts_utc=last.close_ts, price=last.close,
            reason="REGIME_MAX_HOLD", fraction_closed=1.0,
            pips=round(exit_pips, 2),
        )
    return report
