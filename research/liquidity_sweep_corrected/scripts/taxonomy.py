"""Sweep taxonomy + Sequence A/B/C classifier for Deliverable C.

Operates on the approaches.parquet ledger emitted by scanner.py.

Spec §6: Type A (immediate sweep) vs Type B (delayed failed breakout).
Spec §6A: Sequence A (single sweep) / B (repeated tests, no sweep required)
          / C (repeated tests + final sweep).

Classifications are mutually exclusive within each dimension (type, sequence).
Episodes that do not qualify as a sweep get type = NONE.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


# ------------------------------------------------------------------------
# Type A / Type B classification
# ------------------------------------------------------------------------
def classify_sweep_type(row: pd.Series) -> str:
    """Classify a single approach episode's sweep type.

    An episode is a sweep when:
      1. It penetrated the level: max_penetration_pips > 0.
      2. Price returned through the level during the episode — proxied by
         the presence of a `_is_rejection_at_rung` rejection (which by
         construction penetrates and closes back) OR by the mix of closes
         beyond and closes on the original side within the same episode.

    Type A — immediate sweep:
      - A rejection bar exists AND no sustained acceptance (max_consec_closes_beyond == 0).
      - Equivalently: in-bar wick penetration + close back + no subsequent
        completed close beyond.

    Type B — delayed failed breakout:
      - ≥1 completed M5 close beyond the level,
      - AND the episode subsequently has close(s) on the original side
        (close_beyond_count < bars_in_episode) OR a rejection bar.
      - "Delayed" implies the breakout bars came first, then return — our
        monotonic schema cannot prove ordering without extra fields, so we
        use the mix-of-close-sides condition as a conservative proxy.

    NONE — not a sweep (touch, breakout continuation, failed-approach, etc.).
    """
    max_pen = row["max_penetration_pips"]
    cb_count = row["close_beyond_count"]
    mcb = row["max_consec_closes_beyond"]
    bars = row["bars_in_episode"]
    had_rej = pd.notna(row["first_rejection_ts"])

    if max_pen <= 0 and cb_count == 0:
        return "NONE"                       # never reached the level

    if mcb >= 1:
        # Sustained-beyond was present at some point.  Did we return?
        # Proxy: not all bars closed beyond.
        if cb_count < bars:
            return "TYPE_B"
        else:
            # Every bar in episode closed beyond — this is a breakout
            # continuation, not a sweep.
            return "NONE"

    # No completed close beyond.  Did we have a rejection?
    if had_rej:
        return "TYPE_A"

    # Penetrated via wick but no rejection fired and no close beyond.
    # Not a sweep by spec — classify as "wicked_no_rejection".
    return "NONE"


def add_sweep_type_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sweep_type"] = df.apply(classify_sweep_type, axis=1)
    return df


# ------------------------------------------------------------------------
# Sequence A/B/C classification
# ------------------------------------------------------------------------
def classify_sequences(df: pd.DataFrame) -> pd.DataFrame:
    """Per (fx_date, level_id), classify the sequence.

    Sequence A: single sweep (test_number_db == 1 AND sweep_type != NONE).
    Sequence B: ≥2 tests, final test has a rejection+confirmation without
                requiring a sweep (final test's sweep_type can be NONE but
                had_rejection must be True).
    Sequence C: ≥2 tests, final test IS a sweep (sweep_type != NONE).

    "Final test" = the episode with the highest test_number_db for that level.
    Lower-numbered tests retain seq_role = "lead".
    """
    df = df.copy()
    df["sequence_class"] = "NONE"
    df["sequence_role"] = "none"

    group_cols = ["fx_date", "level_id"]
    for (_fx, _lid), g in df.groupby(group_cols):
        g_sorted = g.sort_values("test_number_db")
        max_tn = g_sorted["test_number_db"].max()
        final_rows = g_sorted[g_sorted["test_number_db"] == max_tn]
        lead_rows = g_sorted[g_sorted["test_number_db"] < max_tn]

        # Determine final characteristics
        final_had_rej = final_rows["first_rejection_ts"].notna().any()
        final_sweep = (final_rows["sweep_type"] != "NONE").any()

        if max_tn == 1:
            # Only one test — classify by sweep_type
            if final_sweep:
                df.loc[final_rows.index, "sequence_class"] = "A"
                df.loc[final_rows.index, "sequence_role"] = "sweep"
        else:
            # Multiple tests
            if final_sweep:
                df.loc[final_rows.index, "sequence_class"] = "C"
                df.loc[final_rows.index, "sequence_role"] = "final_sweep"
                df.loc[lead_rows.index, "sequence_class"] = "C"
                df.loc[lead_rows.index, "sequence_role"] = "lead_test"
            elif final_had_rej:
                df.loc[final_rows.index, "sequence_class"] = "B"
                df.loc[final_rows.index, "sequence_role"] = "final_rejection"
                df.loc[lead_rows.index, "sequence_class"] = "B"
                df.loc[lead_rows.index, "sequence_role"] = "lead_test"
    return df


# ------------------------------------------------------------------------
# Entry simulation (wick + close primary)
# ------------------------------------------------------------------------
def add_entry_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Attach primary (wick) and secondary (close) entry info.

    An entry fires IFF the episode had a rejection AND a corresponding
    confirmation.  Fill-price convention:
      - Primary (wick): price at the rejection extreme (bar.high for BUY,
        bar.low for SELL).  Spread cost is applied at P&L step, not here.
      - Secondary (close): close of the confirming bar.
    """
    df = df.copy()
    df["entry_wick_fires"] = df["first_confirm_wick_ts"].notna() & df["first_rejection_ts"].notna()
    df["entry_close_fires"] = df["first_confirm_close_ts"].notna() & df["first_rejection_ts"].notna()
    return df


# ------------------------------------------------------------------------
# Public pipeline
# ------------------------------------------------------------------------
def classify(df_approaches: pd.DataFrame) -> pd.DataFrame:
    df = add_sweep_type_column(df_approaches)
    df = classify_sequences(df)
    df = add_entry_columns(df)
    return df
