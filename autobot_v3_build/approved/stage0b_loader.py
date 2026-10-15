"""Stage 0b timestamp-corrected candle loader.

Loads the Stage 0b verified manifest and provides only CLEAN days with
their timestamp offsets APPLIED. Verified SHA-256 of the manifest:
  16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc

READ-ONLY. No new timestamp policy invented here — all offsets come
from the manifest's `expected_regime_lag_s` column, which Stage 0b
has already frozen.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

MANIFEST_PATH = Path(
    "/mnt/volume_lon1_1778405456698/research/gbpusd_intraday_feasibility/"
    "worktree/outputs/freeze/tick_correction_manifest.csv"
)
MANIFEST_SHA256 = "16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc"
CANDLE_EXT_V2 = Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD")   # bid, 2024-2025
CANDLE_LIVE = Path("/opt/tradingbot/data/candles/GBPUSD")             # mid, 2026+


def verify_manifest() -> None:
    """Compute SHA-256 and compare to the frozen value. Raises on mismatch."""
    h = hashlib.sha256()
    with MANIFEST_PATH.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != MANIFEST_SHA256:
        raise RuntimeError(
            f"Stage 0b manifest SHA mismatch: got {got} expected {MANIFEST_SHA256}"
        )


@dataclass(frozen=True)
class CleanDay:
    date_iso: str
    candle_src: str                # "candles_ext_v2" or "candles"
    offset_seconds: int            # expected_regime_lag_s (negative = archive is UTC+offset)
    regime: str                    # "fixed_minus5h" | "fixed_minus4h" | "unshifted_utc"
    n_candle_bars: int
    n_bars_matched: int


def load_clean_days() -> List[CleanDay]:
    """Return the CLEAN subset of the manifest: status=ok AND
    regime_match=True AND regime_classification in the three fixed
    classes (fixed_minus5h / fixed_minus4h / unshifted_utc)."""
    verify_manifest()
    out: List[CleanDay] = []
    with MANIFEST_PATH.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            if row.get("status") != "ok":
                continue
            if str(row.get("regime_match", "")).lower() not in ("true", "1"):
                continue
            regime = row.get("regime_classification") or ""
            if regime not in ("fixed_minus5h", "fixed_minus4h", "unshifted_utc"):
                continue
            try:
                offset = int(row.get("expected_regime_lag_s") or 0)
            except ValueError:
                continue
            out.append(CleanDay(
                date_iso=row["date"],
                candle_src=row.get("candle_src") or "",
                offset_seconds=offset,
                regime=regime,
                n_candle_bars=int(row.get("n_candle_bars") or 0),
                n_bars_matched=int(row.get("n_bars_matched") or 0),
            ))
    return out


def _archive_root_for(src: str) -> Path:
    if src == "candles_ext_v2":
        return CANDLE_EXT_V2
    if src == "candles":
        return CANDLE_LIVE
    raise ValueError(f"unknown candle_src {src!r}")


def load_day_bars(cd: CleanDay) -> List[Dict[str, float]]:
    """Load 5m bars for one clean day with the manifest's lag CORRECTED.

    The lag `expected_regime_lag_s` is the offset the archive labels
    bars with vs. true UTC. For `fixed_minus5h` the manifest value is
    -18000: archive timestamp = UTC - 5h → to convert archive→UTC we
    SUBTRACT the offset (i.e. ADD 5 hours).

    We shift timestamps by `-offset_seconds` so each returned bar's
    `ts` field is a true UTC datetime.
    """
    fp = _archive_root_for(cd.candle_src) / f"{cd.date_iso}.csv"
    out: List[Dict[str, float]] = []
    if not fp.exists():
        return out
    with fp.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                ts_raw = row["timestamp"]
                if ts_raw.endswith("Z"):
                    ts_raw = ts_raw[:-1] + "+00:00"
                archive_ts = datetime.fromisoformat(ts_raw)
                if archive_ts.tzinfo is None:
                    archive_ts = archive_ts.replace(tzinfo=timezone.utc)
                # Apply correction: archive_ts was labelled with offset,
                # true UTC = archive_ts - offset.
                true_utc = archive_ts - timedelta(seconds=cd.offset_seconds)
                out.append({
                    "ts": true_utc,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low":  float(row["low"]),
                    "close": float(row["close"]),
                    "src": cd.candle_src,
                    "regime": cd.regime,
                })
            except Exception:
                continue
    out.sort(key=lambda b: b["ts"])
    return out


# ── Partition helpers ─────────────────────────────────────────────────

def partition_of(cd: CleanDay) -> str:
    """DEV: 2024-01 → 2025-06 (bid, candles_ext_v2).
    HOLDOUT: 2025-07 → 2025-12 (bid, candles_ext_v2).
    OOS: 2026-01 → 2026-03 (mid, candles).
    """
    d = date.fromisoformat(cd.date_iso)
    if d.year == 2024 or (d.year == 2025 and d.month <= 6):
        return "DEV"
    if d.year == 2025 and d.month >= 7:
        return "HOLDOUT"
    if d.year == 2026 and d.month <= 3:
        return "OOS"
    return "OUT_OF_SCOPE"


def iter_clean_days(partition: Optional[str] = None) -> Iterator[CleanDay]:
    for cd in load_clean_days():
        if partition is not None and partition_of(cd) != partition:
            continue
        yield cd
