"""Phase 2 Step 5 — tick-to-M5 reconciliation (uses corrected cache).

Loads per-day tick slices from the corrected cache
(/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD/{YYYY}.parquet)
via a ts_utc_ns range filter.

Builds M5 OHLC candles from ticks in three ways:
  (a) BID-only, (b) ASK-only, (c) MID-of-bid-ask.

Compares each against the matching candle archive:
  - 2024-2025: /opt/tradingbot/data/candles_ext/GBPUSD/
  - 2026+:     /opt/tradingbot/data/candles/GBPUSD/

Produces:
  tick_vs_candle_reconciliation_summary.json
  tick_vs_candle_per_day_pips.csv
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_ROOT = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")
OUT = Path("/tmp/phase2_audit")
OUT.mkdir(parents=True, exist_ok=True)

CANDLES_EXT = Path("/opt/tradingbot/data/candles_ext/GBPUSD")
CANDLES_LIVE = Path("/opt/tradingbot/data/candles/GBPUSD")

TARGET_DATES = [
    "2024-01-10", "2024-02-14", "2024-03-19", "2024-04-15",
    "2024-05-13", "2024-06-14", "2024-07-15", "2024-08-16",
    "2024-09-18", "2024-10-23", "2024-11-07", "2024-12-19",
    "2025-01-15", "2025-02-14", "2025-03-19", "2025-04-15",
    "2025-05-13", "2025-06-18", "2025-07-15", "2025-08-18",
    "2025-09-15", "2025-10-14", "2025-11-10", "2025-12-15",
    "2026-01-13", "2026-02-10", "2026-03-04",
    "2026-03-18", "2026-03-25", "2026-03-30",
]


def _session_of_hour(h: int) -> str:
    if h >= 22 or h < 0: return "late_ny_asia_prep"
    if h < 7: return "asia"
    if h < 11: return "london_open"
    if h < 13: return "london_ny_overlap"
    if h < 17: return "ny_open"
    return "ny_pm_sydney_early"


def _candle_archive_for(date_s: str) -> Path:
    year = int(date_s[:4])
    return (CANDLES_EXT if year < 2026 else CANDLES_LIVE) / f"{date_s}.csv"


def _load_ticks_for_day(date_s: str) -> pd.DataFrame:
    start_ns = pd.Timestamp(f"{date_s}T00:00:00+00:00").value
    end_ns = start_ns + 86400 * 10**9
    # The relevant parquet(s) — only 2 at year boundary; cheap filter
    years = {int(date_s[:4])}
    if date_s[5:10] in ("01-01",):
        years.add(int(date_s[:4]) - 1)
    frames = []
    for yr in sorted(years):
        p = CACHE_ROOT / f"{yr}.parquet"
        if not p.exists(): continue
        df = pd.read_parquet(
            p, columns=["ts_utc_ns", "bid", "ask", "source_row"],
            filters=[("ts_utc_ns", ">=", start_ns), ("ts_utc_ns", "<", end_ns)],
        )
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["ts_utc_ns", "bid", "ask", "source_row"])
    return pd.concat(frames, ignore_index=True).sort_values(["ts_utc_ns", "source_row"]).reset_index(drop=True)


def _build_m5(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts_utc"] = pd.to_datetime(df["ts_utc_ns"], unit="ns", utc=True)
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["bar_ts"] = df["ts_utc"].dt.floor("5min")
    agg = df.groupby("bar_ts", sort=True).agg(
        bid_open=("bid", "first"), bid_high=("bid", "max"),
        bid_low=("bid", "min"),    bid_close=("bid", "last"),
        ask_open=("ask", "first"), ask_high=("ask", "max"),
        ask_low=("ask", "min"),    ask_close=("ask", "last"),
        mid_open=("mid", "first"), mid_high=("mid", "max"),
        mid_low=("mid", "min"),    mid_close=("mid", "last"),
        n_ticks=("bid", "size"),
    ).reset_index()
    return agg


def _load_archive(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float) / 10000.0  # IG points → FX decimal
    return df.sort_values("ts").reset_index(drop=True)


PIP = 0.0001


def reconcile_day(date_s: str) -> dict:
    archive_path = _candle_archive_for(date_s)
    if not archive_path.exists():
        return {"date": date_s, "status": "archive_missing", "path": str(archive_path)}
    ticks = _load_ticks_for_day(date_s)
    if ticks.empty:
        return {"date": date_s, "status": "no_ticks"}
    tick_m5 = _build_m5(ticks)
    arch = _load_archive(archive_path)
    merged = tick_m5.merge(arch.rename(columns={"ts": "bar_ts"}), on="bar_ts", how="inner", suffixes=("", "_arch"))
    if merged.empty:
        return {"date": date_s, "status": "no_overlap",
                "n_tick_m5": int(len(tick_m5)), "n_arch": int(len(arch))}

    def deltas(tick_col: str, arch_col: str) -> dict:
        d = (merged[tick_col] - merged[arch_col]) / PIP
        return {
            "mean_pips": float(d.mean()), "median_pips": float(d.median()),
            "p05_pips": float(np.quantile(d, 0.05)), "p95_pips": float(np.quantile(d, 0.95)),
            "max_abs_pips": float(d.abs().max()),
        }

    out: dict = {
        "date": date_s, "status": "ok",
        "n_overlap_m5_bars": int(len(merged)),
        "n_tick_m5_bars_in_day": int(len(tick_m5)),
        "n_arch_bars_in_day": int(len(arch)),
    }
    for build in ("bid", "ask", "mid"):
        row = {}
        for f in ("open", "high", "low", "close"):
            row[f] = deltas(f"{build}_{f}", f)
        out[f"delta_{build}"] = row

    merged["bar_hour"] = merged["bar_ts"].dt.hour
    merged["session"] = merged["bar_hour"].apply(_session_of_hour)
    merged["mid_close_abs_pips"] = (merged["mid_close"] - merged["close"]).abs() / PIP
    sess = merged.groupby("session")["mid_close_abs_pips"].agg(["median", "max", "count"]).round(3).to_dict(orient="index")
    out["mid_close_abs_pips_by_session"] = sess
    return out


def main():
    t0 = time.time()
    rows = []
    sample = []
    for date_s in TARGET_DATES:
        print(f"[{date_s}] reconciling", flush=True)
        row = reconcile_day(date_s)
        rows.append(row)
        if row.get("status") == "ok":
            sample.append({
                "date": date_s,
                "n_overlap": row["n_overlap_m5_bars"],
                "mid_close_max_abs_pips": row["delta_mid"]["close"]["max_abs_pips"],
                "mid_close_median_pips": row["delta_mid"]["close"]["median_pips"],
                "bid_close_max_abs_pips": row["delta_bid"]["close"]["max_abs_pips"],
                "ask_close_max_abs_pips": row["delta_ask"]["close"]["max_abs_pips"],
                "mid_high_max_abs_pips": row["delta_mid"]["high"]["max_abs_pips"],
                "mid_low_max_abs_pips": row["delta_mid"]["low"]["max_abs_pips"],
                "bid_high_max_abs_pips": row["delta_bid"]["high"]["max_abs_pips"],
                "bid_low_max_abs_pips": row["delta_bid"]["low"]["max_abs_pips"],
            })

    (OUT / "tick_vs_candle_reconciliation_summary.json").write_text(json.dumps(rows, indent=2, default=str))
    pd.DataFrame(sample).to_csv(OUT / "tick_vs_candle_per_day_pips.csv", index=False)
    print(f"[done] elapsed {time.time()-t0:.1f}s", flush=True)
    print(json.dumps(sample, indent=2, default=str))


if __name__ == "__main__":
    main()
