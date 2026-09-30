#!/usr/bin/env python3
"""
Sanity-check: EMA_STACK_STATE column produced by indicators.add_indicators on real 5m candles.

Loads 2 consecutive GBPUSD daily CSVs from /opt/tradingbot/data/candles/, concatenates,
runs add_indicators, and prints:
  - column presence + NaN counts
  - EMA_STACK_STATE value_counts
  - tail(20) showing close / 4 EMAs / ATR / gap-over-ATR / state
  - a summary of state transitions
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from indicators import IndicatorsConfig, add_indicators  # noqa: E402


CANDLES_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")


def _load_recent(n_days: int = 2) -> pd.DataFrame:
    files = sorted(CANDLES_DIR.glob("2026-*.csv"))
    files = [f for f in files if not f.name.endswith(".tickbuilt")]
    if not files:
        raise SystemExit(f"No candle files in {CANDLES_DIR}")
    picks = files[-n_days:]
    print(f"Loading: {[p.name for p in picks]}")
    dfs = [pd.read_csv(p, parse_dates=["timestamp"]) for p in picks]
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def main() -> None:
    df = _load_recent(n_days=2)
    print(f"Loaded {len(df)} bars  range={df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")

    cfg = IndicatorsConfig()
    print(f"Config: ema_stack_periods={cfg.ema_stack_periods} k={cfg.ema_stack_compression_k}")

    enriched = add_indicators(df, cfg)

    # Column presence
    needed = ["EMA_8", "EMA_13", "EMA_21", "EMA_50", "ATR_14", "EMA_STACK_STATE"]
    print("\n-- column presence + NaN counts --")
    for c in needed:
        present = c in enriched.columns
        nan_ct = int(enriched[c].isna().sum()) if present else -1
        print(f"  {c:20s} present={present} nans={nan_ct}/{len(enriched)}")

    if "EMA_STACK_STATE" not in enriched.columns:
        raise SystemExit("EMA_STACK_STATE missing — wiring failed")

    # Value counts
    print("\n-- EMA_STACK_STATE value_counts (NaN = warmup bars) --")
    vc = enriched["EMA_STACK_STATE"].value_counts(dropna=False)
    for label, count in vc.items():
        pct = 100.0 * count / len(enriched)
        print(f"  {str(label):15s} {count:5d}  ({pct:5.1f}%)")

    # Gap-over-ATR sanity: closer to 0 = tighter stack; compare against k threshold (0.3)
    emas = enriched[["EMA_8", "EMA_13", "EMA_21", "EMA_50"]]
    gap = emas.max(axis=1) - emas.min(axis=1)
    ratio = gap / enriched["ATR_14"].replace(0.0, float("nan"))
    enriched = enriched.assign(_gap=gap, _ratio=ratio)

    print("\n-- tail(20): timestamp / close / EMA_8 / EMA_50 / ATR_14 / gap/ATR / STATE --")
    tail = enriched.tail(20)[
        ["timestamp", "close", "EMA_8", "EMA_50", "ATR_14", "_ratio", "EMA_STACK_STATE"]
    ]
    with pd.option_context("display.width", 140, "display.max_colwidth", 40):
        print(tail.to_string(index=False))

    # Transitions — useful to see the column isn't stuck on one value
    states = enriched["EMA_STACK_STATE"].dropna().reset_index(drop=True)
    transitions = int((states != states.shift()).iloc[1:].sum())
    print(f"\n-- transitions: {transitions} state changes across {len(states)} non-warmup bars --")


if __name__ == "__main__":
    main()
