"""Phase 2 Step 2b — independent timezone verification (memory-safe).

Processes one year at a time, releases memory between years.

Three independent signals:
  1. Sunday-market-open hour (naive) — expected around 17:00 EST (= 22:00 UTC)
  2. 2026 DST-boundary shift in Sunday-open label (should jump 17→16 at 2026-03-08)
  3. Candle vs tick cross-check — tick-at-candle-time should match candle close within ~5 pips

Writes:
  tz_verification_report.json
  tz_sunday_open_hours.csv
  tz_candle_anchor_cross_check.csv
"""
from __future__ import annotations
import gc
import json
from pathlib import Path

import numpy as np
import pandas as pd

TICK_ROOT = Path("/mnt/volume_lon1_1778405456698/ticks")
CANDLES_EXT = Path("/opt/tradingbot/data/candles_ext/GBPUSD")
CANDLES_LIVE = Path("/opt/tradingbot/data/candles/GBPUSD")
OUT = Path("/tmp/phase2_audit")
OUT.mkdir(parents=True, exist_ok=True)

PAIR = "GBPUSD"


def _load_year_naive_minimal(year: int, columns=("timestamp", "bid", "ask")):
    """Load full-year CSV; caller is responsible for freeing before next load."""
    return pd.read_csv(
        TICK_ROOT / f"{PAIR}_ticks_{year}.csv",
        usecols=list(columns),
        parse_dates=["timestamp"],
    )


def _candle_archive_for(year: int) -> Path:
    return CANDLES_EXT if year < 2026 else CANDLES_LIVE


def sunday_open_rows(df: pd.DataFrame, year: int) -> list[dict]:
    sun_mask = df["timestamp"].dt.dayofweek == 6
    sun_df = df.loc[sun_mask, ["timestamp"]].copy()
    sun_df["day"] = sun_df["timestamp"].dt.floor("D")
    first_per_day = sun_df.groupby("day", sort=True)["timestamp"].min()
    rows = []
    for day, first in first_per_day.items():
        rows.append({
            "year": year,
            "sunday": day.date().isoformat(),
            "first_tick_naive": first.isoformat(),
            "first_tick_hour_naive": int(first.hour),
            "first_tick_minute_naive": int(first.minute),
        })
    return rows


def candle_cross_check(df: pd.DataFrame, year: int, shift_hours: int, probe_dates: list[str]) -> list[dict]:
    """Verify tick at (candle_ts_utc - shift_hours) matches candle close within tolerance."""
    archive_dir = _candle_archive_for(year)
    rows = []
    for date_s in probe_dates:
        cp = archive_dir / f"{date_s}.csv"
        if not cp.exists():
            rows.append({"date": date_s, "status": "candle_missing", "candle_path": str(cp)})
            continue
        cdf = pd.read_csv(cp)
        if cdf.empty:
            rows.append({"date": date_s, "status": "candle_empty"})
            continue
        cdf["ts"] = pd.to_datetime(cdf["timestamp"], utc=True)
        for col in ("open", "high", "low", "close"):
            cdf[col] = cdf[col].astype(float) / 10000.0  # IG spread-bet notation → FX decimal
        # Pick candles at 01:00 UTC and 09:00 UTC (if present) for cross-check
        for probe_hour in (1, 9, 13):
            probe_ts_utc = pd.Timestamp(f"{date_s} {probe_hour:02d}:00:00+00:00")
            cand = cdf[(cdf["ts"] >= probe_ts_utc) & (cdf["ts"] < probe_ts_utc + pd.Timedelta(minutes=5))]
            if cand.empty:
                continue
            crow = cand.iloc[0]
            candle_close = float(crow["close"])

            # Equivalent naive tick window: naive = utc - shift
            tick_naive_lo = probe_ts_utc.tz_localize(None) - pd.Timedelta(hours=shift_hours)
            tick_naive_hi = tick_naive_lo + pd.Timedelta(minutes=5)
            sub = df[(df["timestamp"] >= tick_naive_lo) & (df["timestamp"] < tick_naive_hi)]
            if sub.empty:
                rows.append({
                    "date": date_s, "probe_hour_utc": probe_hour, "status": "no_ticks_in_shifted_window",
                    "candle_ts_utc": probe_ts_utc.isoformat(), "shift_h": shift_hours,
                    "tick_naive_window": [tick_naive_lo.isoformat(), tick_naive_hi.isoformat()],
                })
                continue
            last = sub.iloc[-1]
            first = sub.iloc[0]
            tick_mid = (float(last["bid"]) + float(last["ask"])) / 2
            rows.append({
                "date": date_s, "probe_hour_utc": probe_hour, "status": "ok", "shift_h": shift_hours,
                "candle_ts_utc": probe_ts_utc.isoformat(),
                "candle_open": float(crow["open"]), "candle_close": candle_close,
                "tick_first_bid": float(first["bid"]), "tick_last_bid": float(last["bid"]),
                "tick_last_ask": float(last["ask"]), "tick_last_mid": tick_mid,
                "n_ticks_in_window": int(len(sub)),
                "delta_close_mid_pips": round((tick_mid - candle_close) * 10000, 3),
                "delta_close_bid_pips": round((float(last["bid"]) - candle_close) * 10000, 3),
            })
    return rows


def main():
    all_sun: list[dict] = []
    all_cc: list[dict] = []

    # --- 2024 ---
    print("[2024] loading", flush=True)
    df = _load_year_naive_minimal(2024)
    print(f"[2024] loaded rows={len(df):,}", flush=True)
    all_sun.extend(sunday_open_rows(df, 2024))
    probe = ["2024-01-10", "2024-03-14", "2024-06-14", "2024-09-13", "2024-11-07", "2024-12-05"]
    all_cc.extend(candle_cross_check(df, 2024, 5, probe))
    del df; gc.collect()

    # --- 2025 ---
    print("[2025] loading", flush=True)
    df = _load_year_naive_minimal(2025)
    print(f"[2025] loaded rows={len(df):,}", flush=True)
    all_sun.extend(sunday_open_rows(df, 2025))
    probe = ["2025-01-15", "2025-03-14", "2025-06-13", "2025-09-12", "2025-11-07", "2025-12-05"]
    all_cc.extend(candle_cross_check(df, 2025, 5, probe))
    del df; gc.collect()

    # --- 2026 ---
    print("[2026] loading", flush=True)
    df = _load_year_naive_minimal(2026)
    print(f"[2026] loaded rows={len(df):,}", flush=True)
    all_sun.extend(sunday_open_rows(df, 2026))
    pre_probe = ["2026-01-13", "2026-02-10", "2026-03-02"]
    post_probe = ["2026-03-18", "2026-03-25", "2026-03-30"]
    pre_rows = candle_cross_check(df, 2026, 0, pre_probe)
    for r in pre_rows: r["period_declared"] = "2026-01→2026-03-07 (shift=0h)"
    post_rows = candle_cross_check(df, 2026, 5, post_probe)
    for r in post_rows: r["period_declared"] = "2026-03-08→2026-03-31 (shift=5h)"
    all_cc.extend(pre_rows)
    all_cc.extend(post_rows)
    del df; gc.collect()

    sun_df = pd.DataFrame(all_sun)
    cc_df = pd.DataFrame(all_cc)
    sun_df.to_csv(OUT / "tz_sunday_open_hours.csv", index=False)
    cc_df.to_csv(OUT / "tz_candle_anchor_cross_check.csv", index=False)

    # Build report
    report = {}
    report["sunday_open_hour_naive_by_year"] = {}
    for yr, g in sun_df.groupby("year"):
        hist = g["first_tick_hour_naive"].value_counts().sort_index().to_dict()
        report["sunday_open_hour_naive_by_year"][str(int(yr))] = {int(k): int(v) for k, v in hist.items()}

    # 2026 Sunday-open sequence — look for 17→16 at DST
    sun_2026 = sun_df[sun_df["year"] == 2026].sort_values("sunday")
    report["2026_sunday_open_sequence"] = sun_2026.to_dict(orient="records")

    # Per-period cross-check verdict
    verdicts = {}
    cc_ok = cc_df[cc_df["status"] == "ok"]
    for group_desc, mask in [
        ("2024 (shift=5h)", (cc_df["date"].str.startswith("2024")) & (cc_df["status"] == "ok")),
        ("2025 (shift=5h)", (cc_df["date"].str.startswith("2025")) & (cc_df["status"] == "ok")),
        ("2026-01→2026-03-07 (shift=0h)", (cc_df.get("period_declared") == "2026-01→2026-03-07 (shift=0h)") & (cc_df["status"] == "ok")),
        ("2026-03-08→2026-03-31 (shift=5h)", (cc_df.get("period_declared") == "2026-03-08→2026-03-31 (shift=5h)") & (cc_df["status"] == "ok")),
    ]:
        sub = cc_df[mask]
        if sub.empty:
            verdicts[group_desc] = {"status": "no_data"}
            continue
        max_mid_abs = float(sub["delta_close_mid_pips"].abs().max())
        median_mid_abs = float(sub["delta_close_mid_pips"].abs().median())
        verdicts[group_desc] = {
            "n_anchors": int(len(sub)),
            "max_abs_delta_close_mid_pips": max_mid_abs,
            "median_abs_delta_close_mid_pips": median_mid_abs,
            "verdict": "SHIFT_CONFIRMED" if max_mid_abs <= 5 else f"SHIFT_SUSPECT (max abs {max_mid_abs:.1f}p)",
        }
    report["candle_anchor_verdicts"] = verdicts

    (OUT / "tz_verification_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
