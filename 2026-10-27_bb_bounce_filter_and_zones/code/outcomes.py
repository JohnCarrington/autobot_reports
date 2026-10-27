"""
Outcome measurement for BB Bounce signals.

Entry convention: fill at the fire bar's CLOSE (same convention as the
production pierce-trade log). SL distance and TP distances in pips are
knobs; we compute multiple (SL, TP) pairs per signal so sensitivity to the
exit rule is explicit.

For each (SL, TP) pair we track:
  - outcome ∈ {WIN, LOSS, AMBIG, OPEN}
  - pnl_pips (TP if WIN, -SL if LOSS, 0 if AMBIG, mark-to-market if OPEN)
  - bars_to_outcome (M5 bars from fire → outcome)
  - time_to_outcome_mins

Window: max_bars M5 after entry (default 48 bars = 4 h) OR end of UTC day
(whichever is sooner).

Spread handling: entry fills at the fire bar close, same reference price
regardless of direction. SL and TP are measured against the entry price in
pip-scale units (direction-adjusted). No slippage.

Ambiguous same-bar resolution: if a single M5 bar's range covers BOTH the
TP distance and the SL distance, outcome = AMBIG with pnl = 0. This mirrors
the Fib study's convention.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def measure_outcomes(signals: pd.DataFrame, m5: pd.DataFrame,
                     sl_pips: float, tp_pips: float,
                     max_bars: int = 48) -> pd.DataFrame:
    """Return a copy of `signals` with outcome / pnl / timing columns added."""
    assert sl_pips > 0 and tp_pips > 0
    out = signals.copy().reset_index(drop=True)
    ts = pd.to_datetime(m5["timestamp"], utc=True).values.astype("datetime64[ns]")
    high = m5["high"].values.astype(np.float64)
    low = m5["low"].values.astype(np.float64)

    outcomes: list[str] = []
    pnls: list[float] = []
    bars_to: list[int] = []
    close_idxs: list[int] = []

    for _, sig in out.iterrows():
        entry = float(sig["fire_bar_close"])
        direction = sig["direction"]
        fire_ts = np.datetime64(pd.Timestamp(sig["fire_time"]).to_datetime64())
        start_idx = int(np.searchsorted(ts, fire_ts, side="right"))
        if start_idx >= len(ts):
            outcomes.append("OPEN"); pnls.append(0.0); bars_to.append(-1); close_idxs.append(-1); continue
        end_idx = min(start_idx + max_bars, len(ts))

        res_idx = -1; res = "OPEN"; res_pnl = 0.0
        for k in range(start_idx, end_idx):
            if direction == "LONG":
                fav_hit = high[k] - entry >= tp_pips
                adv_hit = entry - low[k] >= sl_pips
            else:  # SHORT
                fav_hit = entry - low[k] >= tp_pips
                adv_hit = high[k] - entry >= sl_pips
            if fav_hit and adv_hit:
                res = "AMBIG"; res_pnl = 0.0; res_idx = k; break
            if fav_hit:
                res = "WIN"; res_pnl = tp_pips; res_idx = k; break
            if adv_hit:
                res = "LOSS"; res_pnl = -sl_pips; res_idx = k; break
        if res == "OPEN":
            # Mark-to-market at the window close
            last = end_idx - 1
            if last >= start_idx:
                if direction == "LONG":
                    res_pnl = (high[last] + low[last]) / 2 - entry
                else:
                    res_pnl = entry - (high[last] + low[last]) / 2
            res_idx = end_idx - 1
        outcomes.append(res); pnls.append(res_pnl)
        bars_to.append(res_idx - start_idx + 1 if res_idx >= 0 else -1)
        close_idxs.append(res_idx)

    tag = f"sl{int(sl_pips)}_tp{int(tp_pips)}"
    out[f"outcome_{tag}"] = outcomes
    out[f"pnl_pips_{tag}"] = pnls
    out[f"bars_to_{tag}"] = bars_to
    return out
