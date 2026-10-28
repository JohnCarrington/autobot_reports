"""Phase 6 Stage 4 — build the frozen production-equivalent BB Bounce
entry population.

Drives the deployed ``/opt/bb_bounce/strategy.py Strategy.on_candle``
state machine over 5-minute MID candles reconstructed from the Phase 2
corrected BID/ASK tick parquet.  Every ARM / C2_PASS / OPEN_TRADE event
is logged.  The population is the deterministic set of OPEN_TRADE
events keyed by the C3 (confirmation) candle timestamp.

Entry price (frozen BEFORE outcome labelling)
---------------------------------------------
The deployed strategy fires on completed 5-min candles.  The simulated
executable fill is the first tick strictly after the C3 close_time
(C3.ts + 5 minutes).  For BUY the fill = first-after ask; for SELL the
fill = first-after bid.  If no tick arrives within 60 seconds of
close_time the trade is marked EXECUTION_GAP and dropped.

Outputs
-------
`data/stage4_entries.parquet` with columns:
    arm_ts, c1_ts, c2_ts, c3_ts, direction, c1_low, c1_high,
    c2_low, c2_high, c3_close, c1_band_lower, c1_band_upper,
    c2_band_lower, c2_band_upper, fill_ts_ns, fill_price, spread_at_fill

`data/stage4_build_report.json` with event counts and warm-up gaps.

Safety: NO production imports beyond `/opt/bb_bounce/{strategy,bands,
config,candle_reader}` which are pure python modules.  `ig_auth` is
NOT imported — the strategy's state machine does not need IG at all.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import numpy as np

# --- Load deployed BB Bounce modules in isolation --------------
BBB_DIR = Path("/opt/bb_bounce")
sys.path.insert(0, str(BBB_DIR))

# Stub `config` constants without triggering ig_auth.
import types as _types
_cfg = _types.ModuleType("config")
_cfg.BB_PERIOD = 20
_cfg.BB_STDDEV = 2.0
_cfg.BB_WARMUP_BARS = 20
_cfg.HISTORY_LOAD_BARS = 60
_cfg.BAR_SECONDS = 300
_cfg.C2_FOLLOW_SECONDS = 300
_cfg.VALIDITY_SECONDS_FROM_C2_CLOSE = 1800
_cfg.PIP = 0.0001
_cfg.PRICE_DECIMALS = 5  # ticks are in decimal, not points
_cfg.SYMBOL = "GBPUSD"
_cfg.EPIC = "CS.D.GBPUSD.TODAY.IP"
_cfg.TP_PIPS = 30
_cfg.SL_PIPS = 12
_cfg.AUTOBOT_CANDLES_DIR = Path("/opt/tradingbot/data/candles") / _cfg.SYMBOL
sys.modules["config"] = _cfg

# Load bands + candle_reader + strategy
import importlib.util

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so dataclass-generated __init__ can look the
    # module back up via sys.modules.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bands = _load("bands", BBB_DIR / "bands.py")
candle_reader = _load("candle_reader", BBB_DIR / "candle_reader.py")
strategy_mod = _load("strategy", BBB_DIR / "strategy.py")

Candle = candle_reader.Candle
Strategy = strategy_mod.Strategy
EventKind = strategy_mod.EventKind
Dir = strategy_mod.Dir


HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
TICK_DIR = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")

# One tick cache per year
YEARS = [2024, 2025, 2026]


def _year_candle_frame(year: int) -> pd.DataFrame:
    """Load one year of ticks → 5-min MID OHLC frame in POINTS scale."""
    p = TICK_DIR / f"{year}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p, columns=["ts_utc_ns", "bid", "ask"])
    df["bid"] = df["bid"].astype(np.float32)
    df["ask"] = df["ask"].astype(np.float32)
    bar_delta = 5 * 60 * 1_000_000_000
    bar_id = (df["ts_utc_ns"].values // bar_delta).astype(np.int64)
    mid_pts = ((df["bid"].astype(np.float64) + df["ask"].astype(np.float64))
               / 2.0 * 10000.0).round(2)
    tmp = pd.DataFrame({"bar_id": bar_id, "mid_pts": mid_pts.values})
    agg = tmp.groupby("bar_id", sort=True)["mid_pts"].agg(
        ["first", "max", "min", "last"]
    )
    agg.columns = ["open", "high", "low", "close"]
    agg = agg.round(2).reset_index()
    agg["bar_open_ns"] = agg["bar_id"] * bar_delta
    del df, tmp
    import gc; gc.collect()
    return agg


def _build_all_candles() -> pd.DataFrame:
    frames = []
    for y in YEARS:
        print(f"  year {y} ...", flush=True)
        f = _year_candle_frame(y)
        if len(f):
            frames.append(f)
        import gc; gc.collect()
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _bar_open_ns(ts_ns: int) -> int:
    # 5-min buckets anchored at Unix epoch (00:00 UTC on 1970-01-01).
    bar = 5 * 60 * 1_000_000_000
    return (ts_ns // bar) * bar


def _candles_from_frame(df: pd.DataFrame) -> list[Candle]:
    bar_delta = 5 * 60 * 1_000_000_000
    out: list[Candle] = []
    for _, r in df.iterrows():
        dt = datetime.fromtimestamp(int(r["bar_open_ns"]) / 1e9, tz=timezone.utc)
        out.append(Candle(
            ts=dt,
            open=float(round(r["open"], 2)),
            high=float(round(r["high"], 2)),
            low=float(round(r["low"], 2)),
            close=float(round(r["close"], 2)),
        ))
    return out


_TICK_CACHE: dict[int, pd.DataFrame] = {}


def _ticks_for_year(year: int) -> pd.DataFrame:
    if year not in _TICK_CACHE:
        # Evict any stale year to keep memory low
        _TICK_CACHE.clear()
        p = TICK_DIR / f"{year}.parquet"
        df = pd.read_parquet(p, columns=["ts_utc_ns", "bid", "ask"])
        df["bid"] = df["bid"].astype(np.float32)
        df["ask"] = df["ask"].astype(np.float32)
        _TICK_CACHE[year] = df
    return _TICK_CACHE[year]


def _find_fill(bar_close_ns: int, direction: str,
               max_wait_ns: int = 60 * 1_000_000_000) -> dict:
    """Return the first tick strictly after bar_close_ns within max_wait.
    BUY fills at ASK; SELL fills at BID.  Returns dict or {} on gap.
    Loads only the relevant year's tick parquet (cached).
    """
    year = datetime.fromtimestamp(bar_close_ns / 1e9, tz=timezone.utc).year
    ticks = _ticks_for_year(year)
    arr = ticks["ts_utc_ns"].values
    idx = int(np.searchsorted(arr, bar_close_ns, side="right"))
    # If idx overflows this year, check the next year
    if idx >= len(arr):
        try:
            next_year_ticks = _ticks_for_year(year + 1)
            arr = next_year_ticks["ts_utc_ns"].values
            idx = int(np.searchsorted(arr, bar_close_ns, side="right"))
            ticks = next_year_ticks
            if idx >= len(arr):
                return {}
        except Exception:
            return {}
    if int(arr[idx]) - bar_close_ns > max_wait_ns:
        return {}
    bid = float(ticks["bid"].iloc[idx]); ask = float(ticks["ask"].iloc[idx])
    fill = ask if direction == "BUY" else bid
    return {
        "fill_ts_ns": int(arr[idx]),
        "fill_price_decimal": fill,
        "fill_price_points": round(fill * 10000.0, 2),
        "bid": bid,
        "ask": ask,
        "spread_decimal": round(ask - bid, 6),
        "spread_pips": round((ask - bid) * 10000.0, 2),
    }


def main() -> int:
    print("Building 5m candles per year ...", flush=True)
    cdf = _build_all_candles()
    print(f"  {len(cdf):,} 5m candles", flush=True)
    import gc; gc.collect()
    print("Materialising Candle objects...", flush=True)
    candles = _candles_from_frame(cdf)
    print(f"  {len(candles):,} Candle objects", flush=True)
    del cdf; gc.collect()

    print("Running deployed Strategy state machine...", flush=True)
    strat = Strategy()
    closes: list[float] = []
    events_log = []
    entry_rows = []
    arm_count = 0
    c2_pass = 0
    confirm = 0
    expired = 0
    cancel_inv = 0
    cancel_same = 0
    c2_fail = 0
    c2_missing = 0

    # No position-tracking in this stage — Experiment 1 uses the
    # production strategy as a signal source and ignores position
    # occupancy.  Experiment 2 is Stage 11 scope.
    open_dirs: dict = {}

    # Only the last BB_PERIOD closes are needed by Strategy.on_candle →
    # bollinger().  Passing a growing list is O(N²); a 60-element
    # rolling tail is O(N).
    tail_len = _cfg.BB_PERIOD + 2
    for c in candles:
        closes.append(c.close)
        if len(closes) > tail_len:
            closes = closes[-tail_len:]
        events = strat.on_candle(c, closes, open_dirs)
        for ev in events:
            if ev.kind == EventKind.ARM:
                arm_count += 1
            elif ev.kind == EventKind.C2_PASS:
                c2_pass += 1
            elif ev.kind == EventKind.OPEN_TRADE:
                confirm += 1
                # Record the frozen entry.
                s = ev.setup
                c3 = ev.c3
                c3_close_ns = int((c3.ts + timedelta(minutes=5)).timestamp() * 1e9)
                fill = _find_fill(c3_close_ns, s.direction.value)
                row = {
                    "c1_ts": s.c1.ts.isoformat(),
                    "c2_ts": s.c2.ts.isoformat() if s.c2 else None,
                    "c3_ts": c3.ts.isoformat(),
                    "direction": s.direction.value,
                    "c1_high": s.c1.high, "c1_low": s.c1.low,
                    "c1_close": s.c1.close,
                    "c2_high": s.c2.high if s.c2 else None,
                    "c2_low": s.c2.low if s.c2 else None,
                    "c2_close": s.c2.close if s.c2 else None,
                    "c3_close": c3.close,
                    "c1_band_lower": s.c1_band.lower, "c1_band_upper": s.c1_band.upper,
                    "c2_band_lower": s.c2_band.lower if s.c2_band else None,
                    "c2_band_upper": s.c2_band.upper if s.c2_band else None,
                    "c3_close_time_ns": c3_close_ns,
                    **fill,
                }
                entry_rows.append(row)
            elif ev.kind == EventKind.C2_FAIL:
                c2_fail += 1
            elif ev.kind == EventKind.C2_MISSING:
                c2_missing += 1
            elif ev.kind == EventKind.EXPIRED:
                expired += 1
            elif ev.kind == EventKind.CANCEL_INVALIDATED:
                cancel_inv += 1
            elif ev.kind == EventKind.CANCEL_SAME_DIR_OPEN:
                cancel_same += 1

    df = pd.DataFrame(entry_rows)
    # Drop EXECUTION_GAP rows (no fill_ts_ns)
    gaps = int(df["fill_ts_ns"].isna().sum()) if len(df) else 0
    df = df[df["fill_ts_ns"].notna()].reset_index(drop=True)

    df.to_parquet(DATA / "stage4_entries.parquet", index=False)
    report = {
        "n_candles_5m": len(candles),
        "events": {
            "ARM": arm_count,
            "C2_PASS": c2_pass,
            "OPEN_TRADE": confirm,
            "EXPIRED": expired,
            "CANCEL_INVALIDATED": cancel_inv,
            "CANCEL_SAME_DIR_OPEN": cancel_same,
            "C2_FAIL": c2_fail,
            "C2_MISSING": c2_missing,
        },
        "n_entries_with_fill": len(df),
        "n_execution_gaps_dropped": gaps,
        "n_buy": int((df["direction"] == "BUY").sum()) if len(df) else 0,
        "n_sell": int((df["direction"] == "SELL").sum()) if len(df) else 0,
        "window": {
            "first_entry": df["c3_ts"].iloc[0] if len(df) else None,
            "last_entry": df["c3_ts"].iloc[-1] if len(df) else None,
        },
    }
    (DATA / "stage4_build_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
