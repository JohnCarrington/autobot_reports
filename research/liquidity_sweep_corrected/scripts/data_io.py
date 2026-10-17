"""Manifest-aware GBPUSD candle loader for the corrected liquidity-sweep research.

Honours the frozen Stage 0b manifest (SHA 16701ce7...). Returns M5 bars from the
source dictated by the manifest for each date — candles_ext_v2 (BID) for
2024-2025, candles (MID) for 2026-Q1.

No live state, no mutation, no imports outside pandas / numpy / stdlib.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

MANIFEST_PATH = Path(
    "/mnt/volume_lon1_1778405456698/research/gbpusd_intraday_feasibility/"
    "worktree/outputs/freeze/tick_correction_manifest.csv"
)
MANIFEST_SHA256 = (
    "16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc"
)

CANDLE_ROOTS: Dict[str, Path] = {
    "candles_ext_v2": Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD"),
    "candles": Path("/opt/tradingbot/data/candles/GBPUSD"),
}
BASIS_FOR: Dict[str, str] = {
    "candles_ext_v2": "BID",
    "candles": "MID",
}

D1_FILE = Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD_D1.csv")
FX_DAY_OFFSET_SECONDS = 22 * 3600  # 22:00 UTC FX session boundary


@dataclass(frozen=True)
class M5Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest() -> None:
    actual = _sha256_of_file(MANIFEST_PATH)
    if actual != MANIFEST_SHA256:
        raise RuntimeError(
            f"manifest SHA drift: expected {MANIFEST_SHA256}, got {actual}"
        )


def load_manifest() -> pd.DataFrame:
    verify_manifest()
    df = pd.read_csv(MANIFEST_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["regime_match"] = df["regime_match"].astype(bool)
    return df


def authorized_dates() -> pd.DataFrame:
    """Return the manifest subset with status='ok' AND regime_match=True.

    One row per date with columns:
        date (date), candle_src (str), basis ('BID'|'MID'),
        regime_classification (str), n_candle_bars (int)
    """
    df = load_manifest()
    df = df[(df["status"] == "ok") & (df["regime_match"] == True)].copy()  # noqa
    df["basis"] = df["candle_src"].map(BASIS_FOR)
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "candle_src", "basis", "regime_classification", "n_candle_bars"]]


def _parse_m5_row(ts_str: str) -> datetime:
    # candles_ext_v2 uses ISO 'T'; candles uses space separator.  Both UTC.
    ts_str = ts_str.replace(" ", "T", 1)
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_m5_day(d: date, candle_src: str) -> List[M5Bar]:
    root = CANDLE_ROOTS[candle_src]
    fname = root / f"{d.isoformat()}.csv"
    if not fname.exists():
        return []
    out: List[M5Bar] = []
    seen = set()
    with open(fname) as f:
        header = f.readline().rstrip("\r\n").split(",")
        idx = {name: i for i, name in enumerate(header)}
        for line in f:
            parts = line.rstrip("\r\n").split(",")
            try:
                ts = _parse_m5_row(parts[idx["timestamp"]])
                row = (
                    ts,
                    float(parts[idx["open"]]),
                    float(parts[idx["high"]]),
                    float(parts[idx["low"]]),
                    float(parts[idx["close"]]),
                )
            except (KeyError, ValueError):
                continue
            if row in seen:
                continue
            seen.add(row)
            out.append(M5Bar(*row))
    out.sort(key=lambda b: b.ts)
    return out


def load_m5_window(
    center_date: date, days_before: int, days_after: int, candle_src: str
) -> List[M5Bar]:
    """Load M5 bars for [center_date - days_before, center_date + days_after]."""
    bars: List[M5Bar] = []
    d = center_date - timedelta(days=days_before)
    end = center_date + timedelta(days=days_after)
    while d <= end:
        bars.extend(load_m5_day(d, candle_src))
        d += timedelta(days=1)
    bars.sort(key=lambda b: b.ts)
    return bars


def load_m5_fx_day(d: date, candle_src: str) -> List[M5Bar]:
    """Return bars for the FX trading day labelled `d`:
    [d-1 22:00 UTC, d 22:00 UTC).

    The previous calendar day's 22:00-23:55 bars may live in a DIFFERENT
    archive than the current day (the 2025→2026 boundary crosses from
    candles_ext_v2 to candles).  Pick the right source for each half.
    """
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(hours=2)
    end = datetime(d.year, d.month, d.day, 22, tzinfo=timezone.utc)
    prev = d - timedelta(days=1)
    prev_src = "candles" if prev >= date(2026, 1, 1) else "candles_ext_v2"
    bars = load_m5_day(prev, prev_src) + load_m5_day(d, candle_src)
    return [b for b in bars if start <= b.ts < end]


# ---------- D1 aggregation ----------

@dataclass(frozen=True)
class D1Bar:
    date: date  # FX-day label (window ends at this date 22:00 UTC)
    open: float
    high: float
    low: float
    close: float


def _fx_day_label(ts: datetime) -> date:
    """FX day label: window [D-1 22:00, D 22:00) → label D.

    Bars with hour >= 22 belong to the *next* calendar day's FX session.
    """
    if ts.hour >= 22:
        return (ts + timedelta(days=1)).date()
    return ts.date()


def aggregate_m5_to_d1(bars: List[M5Bar]) -> List[D1Bar]:
    if not bars:
        return []
    buckets: Dict[date, List[M5Bar]] = {}
    for b in bars:
        label = _fx_day_label(b.ts)
        buckets.setdefault(label, []).append(b)
    out: List[D1Bar] = []
    for label in sorted(buckets):
        bucket = buckets[label]
        if len(bucket) < 50:  # defence: incomplete FX day
            continue
        out.append(D1Bar(
            date=label,
            open=bucket[0].open,
            high=max(b.high for b in bucket),
            low=min(b.low for b in bucket),
            close=bucket[-1].close,
        ))
    return out


def load_d1_history(
    up_to: date, lookback_days: int = 60
) -> List[D1Bar]:
    """Return D1 bars strictly before `up_to` built by aggregating M5 using the
    FX-day boundary (22:00 UTC previous → 22:00 UTC current, labelled by close
    date).  This matches ``timeframe_context.D1_SESSION_OFFSET_SEC`` and the
    production live convention.

    Deliberately does **not** use /opt/tradingbot/data/candles_ext_v2/GBPUSD_D1.csv
    because that archive is calendar-day aggregated and would misalign with the
    live FX-day convention used for pivots and PDH/PDL in production.  See
    research/liquidity_sweep_corrected/implementation_notes.md §1.

    Rejects weekend labels defensively (FX days labelled Sat/Sun shouldn't
    happen in a clean archive but we guard anyway).  Returned list sorted
    ascending.
    """
    d = up_to - timedelta(days=lookback_days + 7)  # extra buffer for weekends
    bars: List[M5Bar] = []
    while d < up_to:
        src = "candles" if d >= date(2026, 1, 1) else "candles_ext_v2"
        bars.extend(load_m5_fx_day(d, src))
        d += timedelta(days=1)
    agg = aggregate_m5_to_d1(bars)
    agg = [b for b in agg if b.date < up_to and b.date.weekday() < 5]
    return agg[-lookback_days:] if lookback_days else agg
