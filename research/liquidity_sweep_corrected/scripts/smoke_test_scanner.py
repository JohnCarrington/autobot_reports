"""Smoke-test the scanner on a single FX day."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from scripts.scanner import scan_fx_day


def main() -> int:
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 24)

    probe = date(2024, 7, 4)
    records = scan_fx_day(probe, "candles_ext_v2", history_days=10)
    print(f"records emitted on {probe}: {len(records)}")
    if not records:
        return 0
    df = pd.DataFrame(records)
    df["start_ts"] = pd.to_datetime(df["start_ts"])
    df["end_ts"] = pd.to_datetime(df["end_ts"])
    df["dur_min"] = (df["end_ts"] - df["start_ts"]).dt.total_seconds() / 60

    # Top-level counts
    print("\nby family:")
    print(df["level_family"].value_counts().to_string())

    print("\nby approach_side:")
    print(df["approach_side"].value_counts().to_string())

    print(f"\npenetrations (max_penetration_pips > 0): {(df['max_penetration_pips'] > 0).sum()}")
    print(f"with ≥1 close-beyond: {(df['close_beyond_count'] > 0).sum()}")
    print(f"with rejection: {df['first_rejection_ts'].notna().sum()}")
    print(f"with wick confirmation: {df['first_confirm_wick_ts'].notna().sum()}")
    print(f"with close confirmation: {df['first_confirm_close_ts'].notna().sum()}")

    # Show the first few confirmed events
    confirmed = df[df["first_confirm_wick_ts"].notna()].copy()
    if not confirmed.empty:
        cols = ["level_family", "level_price", "approach_side", "test_number_db",
                "start_ts", "end_ts", "first_rejection_ts", "first_confirm_wick_ts",
                "max_penetration_pips", "close_beyond_count"]
        print("\nconfirmed episodes (wick primary):")
        print(confirmed[cols].to_string(index=False))

    # Show max-depth episodes
    deepest = df.sort_values("max_penetration_pips", ascending=False).head(5)
    cols = ["level_family", "level_price", "approach_side", "test_number_db",
            "start_ts", "end_ts", "max_penetration_pips", "close_beyond_count",
            "first_rejection_ts"]
    print("\n5 deepest-penetration episodes:")
    print(deepest[cols].to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
