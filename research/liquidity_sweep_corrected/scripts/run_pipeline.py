"""Full post-scan pipeline: taxonomy → HTF → simulation.  Writes:
  - approaches_classified.parquet (approaches + sweep_type + sequence)
  - approaches_htf.parquet (adds d1/h4/h1 bias)
  - trades_30_12.parquet (per-entry fixed-TP/SL outcomes under Model 1)
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.data_io import load_m5_fx_day
from scripts.htf_metadata import attach_htf_bulk
from scripts.simulate import (
    MODEL1_SL_PIPS, MODEL1_TP_PIPS, OBSERVATION_BARS, simulate_trade,
)
from scripts.taxonomy import classify

DATA_DIR = Path(__file__).parent.parent / "data"
APPROACHES = DATA_DIR / "approaches.parquet"
CLASSIFIED = DATA_DIR / "approaches_classified.parquet"
HTF = DATA_DIR / "approaches_htf.parquet"
TRADES_30_12 = DATA_DIR / "trades_30_12.parquet"

# Partition labels — frozen by brief §12 chronological OOS
def partition_of(d: date) -> str:
    if d < date(2025, 7, 1):
        return "DEV"
    if d < date(2026, 1, 1):
        return "HOLDOUT"
    return "OOS"


def _bars_from(fx_date: date, candle_src: str, days_after: int = 1) -> List:
    bars = load_m5_fx_day(fx_date, candle_src)
    d = fx_date
    for _ in range(days_after):
        d = d + timedelta(days=1)
        src = "candles" if d >= date(2026, 1, 1) else "candles_ext_v2"
        try:
            bars.extend(load_m5_fx_day(d, src))
        except Exception:
            break
    return bars


def simulate_bulk(df_classified: pd.DataFrame) -> pd.DataFrame:
    """One trade per entry per rule.  Produces one row per (episode_id, entry_rule)
    with simulate_trade outputs."""
    rows = []
    # Pre-group by (fx_date, candle_src) so we only load bars once per day
    bars_cache: Dict = {}
    for (fx, src), g in df_classified.groupby(["fx_date", "candle_src"]):
        bars = _bars_from(fx, src, days_after=1)
        bars_cache[(fx, src)] = bars

        for _, row in g.iterrows():
            if not row.get("entry_wick_fires") and not row.get("entry_close_fires"):
                continue
            # Primary (wick)
            if row["entry_wick_fires"] and pd.notna(row["first_confirm_wick_price"]):
                entry_ts = pd.Timestamp(row["first_confirm_wick_ts"]).to_pydatetime()
                entry_price = float(row["first_confirm_wick_price"])
                bars_after = [b for b in bars if b.ts >= entry_ts]
                if bars_after:
                    outcome = simulate_trade(
                        entry_ts=entry_ts,
                        entry_price=entry_price,
                        direction=row["rejection_direction"],
                        bars_after=bars_after,
                        tp_pips=MODEL1_TP_PIPS, sl_pips=MODEL1_SL_PIPS,
                    )
                    rows.append({
                        "entry_rule": "wick",
                        "episode_level_id": row["level_id"],
                        "fx_date": row["fx_date"],
                        "candle_src": row["candle_src"],
                        "basis": row["basis"],
                        "level_family": row["level_family"],
                        "level_price": row["level_price"],
                        "sweep_type": row["sweep_type"],
                        "sequence_class": row["sequence_class"],
                        "sequence_role": row["sequence_role"],
                        "test_number_db": row["test_number_db"],
                        "rejection_direction": row["rejection_direction"],
                        "entry_ts": entry_ts,
                        "entry_price": entry_price,
                        **outcome.__dict__,
                    })

            # Secondary (close)
            if row["entry_close_fires"] and pd.notna(row["first_confirm_close_price"]):
                entry_ts = pd.Timestamp(row["first_confirm_close_ts"]).to_pydatetime()
                entry_price = float(row["first_confirm_close_price"])
                bars_after = [b for b in bars if b.ts >= entry_ts]
                if bars_after:
                    outcome = simulate_trade(
                        entry_ts=entry_ts,
                        entry_price=entry_price,
                        direction=row["rejection_direction"],
                        bars_after=bars_after,
                        tp_pips=MODEL1_TP_PIPS, sl_pips=MODEL1_SL_PIPS,
                    )
                    rows.append({
                        "entry_rule": "close",
                        "episode_level_id": row["level_id"],
                        "fx_date": row["fx_date"],
                        "candle_src": row["candle_src"],
                        "basis": row["basis"],
                        "level_family": row["level_family"],
                        "level_price": row["level_price"],
                        "sweep_type": row["sweep_type"],
                        "sequence_class": row["sequence_class"],
                        "sequence_role": row["sequence_role"],
                        "test_number_db": row["test_number_db"],
                        "rejection_direction": row["rejection_direction"],
                        "entry_ts": entry_ts,
                        "entry_price": entry_price,
                        **outcome.__dict__,
                    })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["partition"] = df["fx_date"].apply(partition_of)
    return df


def main() -> int:
    df = pd.read_parquet(APPROACHES)
    print(f"loaded approaches: {len(df):,}")
    df["partition"] = df["fx_date"].apply(partition_of)

    print("classifying...")
    df_cls = classify(df)
    df_cls.to_parquet(CLASSIFIED, index=False)
    print(f"wrote {CLASSIFIED}")
    print(df_cls["sweep_type"].value_counts().to_string())
    print(df_cls["sequence_class"].value_counts().to_string())

    print("\nattaching HTF metadata (per-day)...")
    t = time.perf_counter()
    df_htf = attach_htf_bulk(df_cls)
    df_htf.to_parquet(HTF, index=False)
    print(f"wrote {HTF}  ({time.perf_counter() - t:.1f}s)")
    print(df_htf["d1_bias"].value_counts().to_string())
    print(df_htf["trade_vs_d1"].value_counts().to_string())

    print("\nsimulating 30/12 trades...")
    t = time.perf_counter()
    df_trades = simulate_bulk(df_htf)
    df_trades.to_parquet(TRADES_30_12, index=False)
    print(f"wrote {TRADES_30_12}  ({time.perf_counter() - t:.1f}s)")
    if not df_trades.empty:
        print(f"total simulated trades: {len(df_trades):,}")
        print(df_trades.groupby("entry_rule")["exit_reason"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
