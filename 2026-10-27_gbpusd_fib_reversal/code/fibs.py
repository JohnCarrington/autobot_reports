"""
Compute Fibonacci retracement levels and non-Fibonacci control levels for
each confirmed swing.

For an UP swing (price moved from `start_price` low to `end_price` high),
the retracement levels are candidate BUY zones below the high:
    level_price = end_price - pct * (end_price - start_price)
A trader anticipates price retracing from `end_price` back DOWN by `pct` of
the swing before resuming up — hence a "buy on dip" at the level.

For a DOWN swing (high → low), levels are candidate SELL zones above the
low:
    level_price = end_price + pct * (start_price - end_price)
"""

from __future__ import annotations

import pandas as pd

FIB_PCTS: dict[str, float] = {
    "fib_23_6": 0.236,
    "fib_38_2": 0.382,
    "fib_50_0": 0.500,
    "fib_61_8": 0.618,
    "fib_78_6": 0.786,
}

CONTROL_PCTS: dict[str, float] = {
    "ctrl_30_0": 0.300,
    "ctrl_40_0": 0.400,
    "ctrl_45_0": 0.450,
    "ctrl_55_0": 0.550,
    "ctrl_70_0": 0.700,
}


def compute_levels(swings: pd.DataFrame) -> pd.DataFrame:
    """One row per (swing × level). Level is live from `conf_time` onward.

    expected_bounce_dir: direction the trader anticipates after a touch.
      UP swing retrace → expect price to BUY (go up) off the level.
      DOWN swing retrace → expect price to SELL (go down) off the level.
    """
    if len(swings) == 0:
        return pd.DataFrame(columns=["swing_id","level_name","pct","level_price","expected_bounce_dir","is_fib","live_from","swing_pips"])
    rows = []
    all_pcts = {**FIB_PCTS, **CONTROL_PCTS}
    for _, s in swings.iterrows():
        for name, pct in all_pcts.items():
            if s["direction"] == "UP":
                lp = s["end_price"] - pct * (s["end_price"] - s["start_price"])
                exp = "BUY"
            else:
                lp = s["end_price"] + pct * (s["start_price"] - s["end_price"])
                exp = "SELL"
            rows.append({
                "swing_id": s["swing_id"],
                "swing_direction": s["direction"],
                "swing_pips": s["pips"],
                "swing_start_time": s["start_time"],
                "swing_end_time": s["end_time"],
                "swing_start_price": s["start_price"],
                "swing_end_price": s["end_price"],
                "level_name": name,
                "pct": pct,
                "level_price": lp,
                "expected_bounce_dir": exp,
                "is_fib": name.startswith("fib_"),
                "live_from": s["conf_time"],
            })
    return pd.DataFrame(rows)
