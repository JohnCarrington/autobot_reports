"""Tick-based intra-bar stop-fill resolver.

Replaces bar-close stop resolution with an actual tick scan inside each
5-minute window. For every bar [bar.ts, bar.ts + 5min), we scan the
tick stream for the first tick (bid for LONG stops, ask for SHORT
stops) that breaches the stop price. That tick's timestamp and price
become the fill.

Timezone handling obeys the operator-ratified rule in
`project_tick_tz_mixed_20260928`:

  * 2024 all year:            archive naive label → +5h to get true UTC
  * 2025 all year:            archive naive label → +5h
  * 2026-01-01 → 2026-03-07:  archive naive label = true UTC (0h)
  * 2026-03-08 → 2026-03-31:  archive naive label → +5h
  * 2026-04-01+:              mid rounded to 2 decimals → UNUSABLE

Memory: ticks are loaded per-year lazily, filtered to the set of CLEAN
days we care about, then indexed by UTC date into a dict of per-day
sorted arrays. Each day holds ~15k ticks → 450 KB → bounded by the
clean-day set (643 days ⇒ <300 MB).

Tick fields used:
  * `ts_utc`   : pandas Timestamp (UTC)
  * `bid`      : float, LONG stop closes against bid
  * `ask`      : float, SHORT stop closes against ask

For 2026 after 2026-04-01 (garbage boundary) there are NO ticks and the
resolver returns `None`; the caller falls back to bar-close resolution.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

TICK_ROOT = Path("/mnt/volume_lon1_1778405456698/ticks")
PAIR_DEFAULT = "GBPUSD"
# Candle archives and bounce_engine.core operate in IG integer-point
# units (12642.0 == 1.26420). Tick archives are stored as raw GBPUSD
# decimals (1.26420). Multiply bid/ask by this factor so the breach
# check uses the same scale the engine stores stops in.
TICK_PRICE_SCALE = 10_000.0


# ── Timezone rule ──────────────────────────────────────────────────────

DST_BOUNDARY_2026 = datetime(2026, 3, 8, tzinfo=None)  # compared to naive
GARBAGE_BOUNDARY_2026 = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _shift_naive_year(y: int, naive_ts: datetime) -> int:
    """Hours to add to a naive tick timestamp of year `y` to get true UTC."""
    if y in (2024, 2025):
        return 5
    if y == 2026:
        if naive_ts < DST_BOUNDARY_2026:
            return 0
        return 5
    raise ValueError(f"no tz rule for year {y}")


# ── Loader (per-year, filtered by CLEAN-day set) ───────────────────────

@dataclass
class DayTicks:
    """Per-day sorted tick arrays for fast window queries."""
    date_iso: str
    ts_us: np.ndarray      # int64, true-UTC microseconds since epoch
    bid:   np.ndarray      # float64
    ask:   np.ndarray      # float64


def _year_from_true_utc_date(d: date) -> List[int]:
    """Which tick-archive year file(s) might contain data for true-UTC date d?

    Because of the +5h shift, the first few hours of true-UTC day X can
    come from the previous year's tick file. We err wide: return both
    [X.year] and [X.year-1] when d.month==1 and d.day==1-2.
    Simpler: for every true-UTC date, we check at most the year of d
    and (if +5h regime) also year-1 for the very first days of January.
    """
    ys = {d.year}
    if d.month == 1 and d.day <= 2:
        ys.add(d.year - 1)
    return sorted(ys)


class TickResolver:
    """Loads and caches intra-day tick arrays, supports stop-fill lookups.

    Usage:
      r = TickResolver(pair="GBPUSD", target_dates={"2024-02-01", "2024-02-02"})
      r.prepare()                           # populates in-memory cache
      hit = r.first_breach(bar_ts, bar_ts + 5min, side="LONG", stop=1.2567)
      if hit:
          fill_ts, fill_px = hit            # fill_px is bid for LONG, ask for SHORT
    """

    def __init__(self, pair: str = PAIR_DEFAULT,
                 target_dates: Optional[Set[str]] = None,
                 verbose: bool = False):
        self.pair = pair
        self.target_dates: Set[str] = set(target_dates or [])
        self.verbose = verbose
        # Per-day arrays, keyed by true-UTC date ISO
        self._days: Dict[str, DayTicks] = {}
        # Years already loaded
        self._loaded_years: Set[int] = set()

    # ── Public interface ───────────────────────────────────────────────

    def prepare(self) -> None:
        """Load every year whose data overlaps the target_dates set."""
        if not self.target_dates:
            return
        years_needed: Set[int] = set()
        for iso in self.target_dates:
            try:
                d = date.fromisoformat(iso)
            except ValueError:
                continue
            for y in _year_from_true_utc_date(d):
                years_needed.add(y)
        for y in sorted(years_needed):
            if y in self._loaded_years:
                continue
            self._load_year(y)
            self._loaded_years.add(y)

    def has_coverage(self, iso: str) -> bool:
        return iso in self._days and self._days[iso].ts_us.size > 0

    def first_breach(self, start_ts: datetime, end_ts: datetime,
                     side: str, stop: float) -> Optional[Tuple[datetime, float]]:
        """Return the (ts, fill_price) of the first tick in [start, end)
        that breaches `stop` for `side`. None if no breach.

        LONG stop breach: bid <= stop   → fill at bid
        SHORT stop breach: ask >= stop  → fill at ask
        """
        iso = start_ts.date().isoformat()
        dt = self._days.get(iso)
        if dt is None or dt.ts_us.size == 0:
            # Try spill-over: the first ticks of the UTC day sometimes
            # arrive from the previous naive-labelled day's file.
            return None
        start_us = int(start_ts.timestamp() * 1_000_000)
        end_us = int(end_ts.timestamp() * 1_000_000)
        lo = bisect.bisect_left(dt.ts_us, start_us)
        hi = bisect.bisect_left(dt.ts_us, end_us)
        if lo >= hi:
            return None
        side = side.upper()
        if side == "LONG":
            # bid <= stop → trigger
            idx_in_window = np.where(dt.bid[lo:hi] <= stop)[0]
            if idx_in_window.size == 0:
                return None
            k = lo + int(idx_in_window[0])
            fill_ts = datetime.fromtimestamp(dt.ts_us[k] / 1_000_000, tz=timezone.utc)
            return fill_ts, float(dt.bid[k])
        elif side == "SHORT":
            idx_in_window = np.where(dt.ask[lo:hi] >= stop)[0]
            if idx_in_window.size == 0:
                return None
            k = lo + int(idx_in_window[0])
            fill_ts = datetime.fromtimestamp(dt.ts_us[k] / 1_000_000, tz=timezone.utc)
            return fill_ts, float(dt.ask[k])
        return None

    # ── Internals ──────────────────────────────────────────────────────

    def _load_year(self, year: int) -> None:
        """Stream one year's tick CSV, apply TZ shift, bucket by UTC date,
        keep only buckets whose date is in `target_dates`."""
        path = TICK_ROOT / f"{self.pair}_ticks_{year}.csv"
        if not path.exists():
            if self.verbose:
                print(f"[tick] {path} not found")
            return
        # Pandas can comfortably stream in chunks; use chunksize to bound
        # memory. We only need (timestamp, bid, ask).
        import pandas as pd  # local import keeps top of file light
        if self.verbose:
            print(f"[tick] loading {path.name} …")
        chunk_iter = pd.read_csv(
            path,
            usecols=["timestamp", "bid", "ask"],
            parse_dates=["timestamp"],
            chunksize=1_000_000,
        )
        # Accumulate per-date buffers across chunks
        buffers: Dict[str, List[np.ndarray]] = {}

        for chunk in chunk_iter:
            # Apply TZ shift element-wise
            if year == 2026:
                mask_pre = chunk["timestamp"] < DST_BOUNDARY_2026
                ts_utc = chunk["timestamp"].copy()
                ts_utc.loc[~mask_pre] = chunk.loc[~mask_pre, "timestamp"] + pd.Timedelta(hours=5)
                # Drop garbage ticks ≥ 2026-04-01 (true UTC)
                keep = ts_utc < pd.Timestamp("2026-04-01")
                chunk = chunk.loc[keep].copy()
                ts_utc = ts_utc.loc[keep]
            else:
                ts_utc = chunk["timestamp"] + pd.Timedelta(hours=5)
            if chunk.empty:
                continue
            ts_utc = ts_utc.dt.tz_localize("UTC")
            date_series = ts_utc.dt.date.astype(str)
            # Filter to target dates up-front to minimise memory
            mask = date_series.isin(self.target_dates)
            if not mask.any():
                continue
            sub = chunk.loc[mask].copy()
            sub_dates = date_series.loc[mask]
            sub_ts_us = (ts_utc.loc[mask].astype("int64") // 1000).to_numpy()  # µs since epoch
            sub_bid = sub["bid"].to_numpy(dtype=np.float64) * TICK_PRICE_SCALE
            sub_ask = sub["ask"].to_numpy(dtype=np.float64) * TICK_PRICE_SCALE
            for iso in sub_dates.unique():
                m = sub_dates.values == iso
                buffers.setdefault(iso, []).append(np.column_stack([
                    sub_ts_us[m], sub_bid[m], sub_ask[m]
                ]))
        # Collapse buffers into DayTicks
        for iso, arrs in buffers.items():
            full = np.concatenate(arrs, axis=0)
            # Sort by ts_us (should already be ordered but ensure it)
            order = np.argsort(full[:, 0], kind="mergesort")
            full = full[order]
            self._days[iso] = DayTicks(
                date_iso=iso,
                ts_us=full[:, 0].astype(np.int64),
                bid=full[:, 1],
                ask=full[:, 2],
            )
        if self.verbose:
            print(f"[tick] year={year} dates_cached={len(buffers)} "
                  f"ticks_total={sum(d.ts_us.size for d in self._days.values())}")


# ── Smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    r = TickResolver(pair="GBPUSD",
                     target_dates={"2024-02-01", "2024-02-02"},
                     verbose=True)
    r.prepare()
    for iso in ("2024-02-01", "2024-02-02"):
        dt = r._days.get(iso)
        if dt is None:
            print(f"[test] {iso}: NO DATA")
            continue
        print(f"[test] {iso}: {dt.ts_us.size} ticks, "
              f"first={datetime.fromtimestamp(dt.ts_us[0]/1e6, tz=timezone.utc).isoformat()} "
              f"last={datetime.fromtimestamp(dt.ts_us[-1]/1e6, tz=timezone.utc).isoformat()}")
    # Fake a breach check: look for a LONG stop at bid<=1.26 in a window
    start = datetime(2024, 2, 1, 8, 0, tzinfo=timezone.utc)
    end = datetime(2024, 2, 1, 9, 0, tzinfo=timezone.utc)
    hit = r.first_breach(start, end, "LONG", 1.26)
    print(f"[test] LONG@1.26 in 08-09 UTC: {hit}")
