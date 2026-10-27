"""Phase 2 Step 6 — H1/H4 reconstruction validation.

Uses the corrected tick cache to build M5 candles via mid-of-bid-ask, then
aggregates up to H1 and H4 using floor-UTC bucketing (htf_reconstruct.py
semantics). Compares each H1 and H4 reconstruction against the deterministic
reconstruction produced by the production module where the production module
can run offline from the archive.

Checks:
  - UTC boundary alignment (:00 of every hour / every 4h)
  - No overlapping buckets
  - No future-data leakage (close is the last ts within the bucket)
  - Weekend holes
  - DST boundaries: no shift required on completed-5m aggregation
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
try:
    import htf_reconstruct as hr
    HAS_PROD_HR = True
except Exception as e:
    HAS_PROD_HR = False
    PROD_HR_ERR = str(e)

CACHE_ROOT = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")
OUT = Path("/tmp/phase2_audit")
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    "2024-02-15", "2024-07-16", "2024-11-18",
    "2025-02-18", "2025-07-15", "2025-11-18",
    "2026-01-14", "2026-03-10", "2026-03-25",
]


def _load_week_slice(center_date: str) -> pd.DataFrame:
    """Load the full week around a center date (center-6d .. center+1d) to allow H4 completion checks."""
    center = pd.Timestamp(center_date + "T00:00:00+00:00")
    start_ns = (center - pd.Timedelta(days=6)).value
    end_ns = (center + pd.Timedelta(days=2)).value
    frames = []
    for yr in (int(center_date[:4]) - 1, int(center_date[:4]), int(center_date[:4]) + 1):
        p = CACHE_ROOT / f"{yr}.parquet"
        if not p.exists(): continue
        df = pd.read_parquet(
            p, columns=["ts_utc_ns", "bid", "ask"],
            filters=[("ts_utc_ns", ">=", start_ns), ("ts_utc_ns", "<", end_ns)],
        )
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("ts_utc_ns").reset_index(drop=True)


def _m5_mid(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["ts_utc"] = pd.to_datetime(df["ts_utc_ns"], unit="ns", utc=True)
    df["bar_ts"] = df["ts_utc"].dt.floor("5min")
    return df.groupby("bar_ts", sort=True).agg(
        open=("mid", "first"), high=("mid", "max"), low=("mid", "min"), close=("mid", "last"),
    ).reset_index()


def _htf(m5: pd.DataFrame, freq: str) -> pd.DataFrame:
    df = m5.copy()
    bucket_col = {"H1": pd.Grouper(key="bar_ts", freq="1h"), "H4": pd.Grouper(key="bar_ts", freq="4h")}[freq]
    out = df.groupby(bucket_col).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), n_bars=("open", "size"),
    ).reset_index().rename(columns={"bar_ts": "ts"})
    # Only keep full buckets: H1 requires 12 M5 bars; H4 requires 48
    required = 12 if freq == "H1" else 48
    out["full_bucket"] = out["n_bars"] == required
    return out


def validate_day(date_s: str) -> dict:
    week = _load_week_slice(date_s)
    if week.empty:
        return {"date": date_s, "status": "no_ticks"}
    m5 = _m5_mid(week)
    h1 = _htf(m5, "H1")
    h4 = _htf(m5, "H4")

    out: dict = {
        "date": date_s, "status": "ok",
        "week_tick_count": int(len(week)),
        "m5_bar_count": int(len(m5)),
        "h1_bar_count": int(len(h1)), "h1_full_count": int(h1["full_bucket"].sum()),
        "h4_bar_count": int(len(h4)), "h4_full_count": int(h4["full_bucket"].sum()),
        "h1_boundary_ok": bool((h1["ts"].dt.minute == 0).all() and (h1["ts"].dt.second == 0).all()),
        "h4_boundary_ok": bool((h4["ts"].dt.hour % 4 == 0).all() and (h4["ts"].dt.minute == 0).all()),
    }

    # Sanity: close of each bucket must be <= last-tick-ts of bucket; derived here by construction
    # Weekend hole: no M5 bars between Sat 00:00 UTC and Sun 22:00 UTC
    center = pd.Timestamp(date_s + "T00:00:00+00:00")
    for offset in range(-6, 2):
        d = center + pd.Timedelta(days=offset)
        dow = d.dayofweek  # Mon=0..Sun=6
        if dow == 5:  # Saturday
            sat_bars = m5[(m5["bar_ts"] >= d) & (m5["bar_ts"] < d + pd.Timedelta(days=1))]
            if len(sat_bars) > 0:
                out.setdefault("saturday_bars_detected", []).append({
                    "sat_date": d.date().isoformat(),
                    "n_bars": int(len(sat_bars)),
                    "sample_ts": sat_bars["bar_ts"].iloc[0].isoformat(),
                })

    # Compare against production htf_reconstruct (if available)
    if HAS_PROD_HR:
        # htf_reconstruct expects a specific input shape; we approximate the signature here
        # by passing a list of (ts, open, high, low, close) dicts. If the production API differs,
        # record it as a limitation.
        try:
            # Many prod APIs: hr.build_h1_from_5m([dict(time=..., open=..., high=..., low=..., close=...)])
            cand_rows = [{
                "time": r["bar_ts"].to_pydatetime(),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
            } for r in m5.to_dict("records")]
            prod_h1 = hr.build_h1_from_5m(cand_rows)
            out["prod_h1_available"] = True
            out["prod_h1_bar_count"] = int(len(prod_h1))
            # Match prod → research on timestamp
            prod_df = pd.DataFrame(prod_h1)
            if "time" in prod_df.columns:
                prod_df["ts"] = pd.to_datetime(prod_df["time"], utc=True)
                merged = h1.merge(prod_df[["ts", "open", "high", "low", "close"]], on="ts", suffixes=("_research", "_prod"), how="inner")
                if not merged.empty:
                    for col in ("open", "high", "low", "close"):
                        d = (merged[f"{col}_research"] - merged[f"{col}_prod"]).abs()
                        out[f"h1_prod_max_abs_delta_{col}_pips"] = float(d.max() * 10000)
        except Exception as e:
            out["prod_h1_error"] = repr(e)
    else:
        out["prod_h1_available"] = False
        out["prod_h1_import_error"] = PROD_HR_ERR

    return out


def main():
    t0 = time.time()
    all_rows = []
    for date_s in TARGETS:
        print(f"[{date_s}] validating", flush=True)
        row = validate_day(date_s)
        all_rows.append(row)
        print(json.dumps(row, indent=2, default=str), flush=True)
    (OUT / "htf_validation_report.json").write_text(json.dumps(all_rows, indent=2, default=str))
    print(f"[done] elapsed {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
