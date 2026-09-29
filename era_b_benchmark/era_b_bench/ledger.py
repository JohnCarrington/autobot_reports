"""Loader for the pinned Era B deal reference CSV.

Reads spec_pins/host_161_bb_bounce_s_deal_reference_20260929.csv,
filters to `era == B_20p_SL_no_regime_arm` (36 rows).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import config


LEDGER_PATH = Path(__file__).resolve().parent.parent / "spec_pins" / "host_161_bb_bounce_s_deal_reference_20260929.csv"
ERA_B_TAG = "B_20p_SL_no_regime_arm"


def _parse_ts(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _f(v: str) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


@dataclass
class LedgerRow:
    deal_id:                  str
    direction:                str
    entry_price:              float
    sl_pips_applied:          float
    tp1_pips:                 float
    timestamp_open:           datetime
    timestamp_close:          Optional[datetime]
    pnl_pips:                 Optional[float]
    total_pnl_pips:           Optional[float]
    effective_pnl_pips:       Optional[float]
    runner_pnl_pips:          Optional[float]
    partial_bank_pips:        Optional[float]
    close_reason_canonical:   str
    close_reason_raw:         str
    mfe_pips:                 Optional[float]
    mae_pips:                 Optional[float]
    duration_minutes:         Optional[float]
    scaled_out:               Optional[bool]
    era:                      str

    @property
    def rejection_bar_open_ts(self) -> datetime:
        """The 5m bar whose CLOSE time equals floor_5m(timestamp_open),
        i.e., the rejection bar; its OPEN time is 5 minutes earlier
        than the fire timestamp."""
        # Fire is at bar close + tiny latency; bar OPEN = floor_5m(ts) - 5min
        epoch = int(self.timestamp_open.timestamp())
        floor_close = (epoch // 300) * 300
        bar_open_epoch = floor_close - 300
        return datetime.fromtimestamp(bar_open_epoch, tz=timezone.utc)

    @property
    def close_reproducible(self) -> bool:
        """True iff the close_reason is one that the 4-exit simulator
        can produce (SL / TP / scale-out+BE / max-hold)."""
        r = self.close_reason_canonical.upper()
        if r in config.UNREPRODUCIBLE_CLOSE_REASONS:
            return False
        if r in config.REPRODUCIBLE_CLOSE_REASONS:
            return True
        return False


def load_era_b_rows() -> List[LedgerRow]:
    rows: List[LedgerRow] = []
    with open(LEDGER_PATH) as f:
        for r in csv.DictReader(f):
            if r["era"] != ERA_B_TAG:
                continue
            rows.append(LedgerRow(
                deal_id                = r["deal_id"],
                direction              = r["direction"],
                entry_price            = float(r["entry_price"]),
                sl_pips_applied        = float(r["sl_pips_applied"]),
                tp1_pips               = float(r["tp1_pips"]),
                timestamp_open         = _parse_ts(r["timestamp_open"]),
                timestamp_close        = _parse_ts(r["timestamp_close"]) if r["timestamp_close"] else None,
                pnl_pips               = _f(r["pnl_pips"]),
                total_pnl_pips         = _f(r["total_pnl_pips"]),
                effective_pnl_pips     = _f(r["effective_pnl_pips"]),
                runner_pnl_pips        = _f(r["runner_pnl_pips"]),
                partial_bank_pips      = _f(r["partial_bank_pips"]),
                close_reason_canonical = r["close_reason_canonical"] or "",
                close_reason_raw       = r["close_reason_raw"] or "",
                mfe_pips               = _f(r["mfe_pips"]),
                mae_pips               = _f(r["mae_pips"]),
                duration_minutes       = _f(r["duration_minutes"]),
                scaled_out             = (r["scaled_out"] == "True") if r["scaled_out"] else None,
                era                    = r["era"],
            ))
    return rows
