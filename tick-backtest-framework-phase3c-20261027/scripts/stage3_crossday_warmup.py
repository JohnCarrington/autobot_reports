"""Phase 3C Stage 3 — cross-day indicator warmup.

Phase 3's indicator-parity report showed EMA max-errors up to ~22 pips at the
start of each UTC day because the replay instantiated fresh indicator state
at midnight. Production carries state across day boundaries.

This script loads two consecutive certified-usable days from the Phase 2
corrected cache, builds M5 MID candles continuously, and verifies that the
production BB(20,2) + EMA calculations match the pre-computed enriched
archive values from the start of day 2 (not just after a 20-bar warmup).

Writes:
  data/crossday_warmup_report.json
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.isolation import init_isolation  # noqa: E402

CACHE = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")
ENRICHED = Path("/opt/tradingbot/data/candles_enriched/GBPUSD")
OUT = Path("/tmp/phase3c_audit/data")
OUT.mkdir(parents=True, exist_ok=True)


def _load_m5_mid_range(start_ns: int, end_ns: int) -> pd.DataFrame:
    frames = []
    for yr in sorted({pd.Timestamp(start_ns, unit='ns', tz='UTC').year,
                      pd.Timestamp(end_ns, unit='ns', tz='UTC').year}):
        p = CACHE / f"{yr}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=["ts_utc_ns", "bid", "ask"],
                             filters=[("ts_utc_ns", ">=", start_ns),
                                      ("ts_utc_ns", "<", end_ns)])
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts_utc_ns"], unit="ns", utc=True)
    df["mid"] = (df["bid"] + df["ask"]) / 2 * 10000.0  # FX decimal → IG points
    df["bar"] = df["ts"].dt.floor("5min")
    agg = df.groupby("bar", sort=True).agg(
        open=("mid", "first"), high=("mid", "max"),
        low=("mid", "min"), close=("mid", "last"),
    ).reset_index().rename(columns={"bar": "ts"})
    return agg


def main():
    # Pick a day pair in the certified window; day_B must be an active trading day.
    # Use 2026-02-09 (Mon) and 2026-02-10 (Tue) — contiguous trading days.
    day_A = "2026-02-09"
    day_B = "2026-02-10"
    range_start = pd.Timestamp(f"{day_A}T00:00:00+00:00").value
    range_end = pd.Timestamp(f"{day_B}T23:55:00+00:00").value + 300 * 10**9

    print(f"[load] {day_A} → {day_B} tick range")
    m5 = _load_m5_mid_range(range_start, range_end)
    print(f"[load] {len(m5)} M5 bars total")
    assert len(m5) > 0, "no M5 bars in the two-day window"

    # Enriched archive for day_B (production MID-side pre-computed indicators)
    enr_b = pd.read_csv(ENRICHED / f"{day_B}.csv")
    enr_b["ts"] = pd.to_datetime(enr_b["timestamp"], utc=True)
    for c in ("open", "high", "low", "close",
              "BB_MID_20", "BB_UPPER_20_2", "BB_LOWER_20_2",
              "EMA_8", "EMA_13", "EMA_21", "EMA_50"):
        if c in enr_b.columns:
            enr_b[c] = enr_b[c].astype(float) / 10000.0

    # Convert tick-M5 to FX decimal for comparison
    m5["close_fx"] = m5["close"] / 10000.0
    all_closes_fx = m5["close_fx"].tolist()

    # Compute production BB(20,2) + EMAs continuously across the two days
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb

        bb_rows = []
        for i in range(len(all_closes_fx)):
            if i + 1 < 20:
                bb_rows.append((None, None, None))
                continue
            closes = all_closes_fx[: i + 1]
            lo, md, up = bb._bb_20_2(closes, period=20, std_mult=2.0)
            bb_rows.append((lo, md, up))

    def _ema(series, period):
        out = []
        k = 2 / (period + 1)
        s = None
        for i, c in enumerate(series):
            if s is None:
                if i + 1 >= period:
                    s = sum(series[:period]) / period
                    out = [None] * (period - 1) + [s]
                else:
                    out.append(None)
                    continue
            else:
                s = c * k + s * (1 - k)
                out.append(s)
        while len(out) < len(series):
            out.append(None)
        return out

    ema8 = _ema(all_closes_fx, 8)
    ema13 = _ema(all_closes_fx, 13)
    ema21 = _ema(all_closes_fx, 21)
    ema50 = _ema(all_closes_fx, 50)

    m5["calc_bb_lower"] = [r[0] for r in bb_rows]
    m5["calc_bb_mid"] = [r[1] for r in bb_rows]
    m5["calc_bb_upper"] = [r[2] for r in bb_rows]
    m5["calc_ema_8"] = ema8
    m5["calc_ema_13"] = ema13
    m5["calc_ema_21"] = ema21
    m5["calc_ema_50"] = ema50

    merged = m5.merge(enr_b, on="ts", how="inner", suffixes=("_tick", "_arch"))

    # Day_B first bar in merged = cold-start risk zone
    day_b_start_ts = pd.Timestamp(f"{day_B}T00:00:00+00:00")
    first_hour_mask = (merged["ts"] >= day_b_start_ts) & (merged["ts"] < day_b_start_ts + pd.Timedelta(hours=1))

    def dmax(a, b):
        return float((merged[a] - merged[b]).abs().max() * 10000)
    def dmed(a, b):
        return float((merged[a] - merged[b]).abs().median() * 10000)

    report = {
        "day_A": day_A, "day_B": day_B,
        "n_m5_bars_in_window": int(len(m5)),
        "n_overlap_with_enriched_day_B": int(len(merged)),
        "n_first_hour_day_B": int(first_hour_mask.sum()),
        "parity_full_day_B": {
            "bb_upper_max_abs_pips": dmax("BB_UPPER_20_2", "calc_bb_upper"),
            "bb_upper_median_abs_pips": dmed("BB_UPPER_20_2", "calc_bb_upper"),
            "bb_lower_max_abs_pips": dmax("BB_LOWER_20_2", "calc_bb_lower"),
            "ema_8_max_abs_pips": dmax("EMA_8", "calc_ema_8"),
            "ema_8_median_abs_pips": dmed("EMA_8", "calc_ema_8"),
            "ema_13_max_abs_pips": dmax("EMA_13", "calc_ema_13"),
            "ema_21_max_abs_pips": dmax("EMA_21", "calc_ema_21"),
            "ema_50_max_abs_pips": dmax("EMA_50", "calc_ema_50"),
        },
        "parity_first_hour_day_B": {
            "bb_upper_max_abs_pips": float((merged.loc[first_hour_mask, "BB_UPPER_20_2"]
                                             - merged.loc[first_hour_mask, "calc_bb_upper"]).abs().max() * 10000),
            "ema_8_max_abs_pips": float((merged.loc[first_hour_mask, "EMA_8"]
                                          - merged.loc[first_hour_mask, "calc_ema_8"]).abs().max() * 10000),
            "ema_21_max_abs_pips": float((merged.loc[first_hour_mask, "EMA_21"]
                                           - merged.loc[first_hour_mask, "calc_ema_21"]).abs().max() * 10000),
        },
        "note": ("First-hour comparison is the cold-start regression target. "
                 "With day-A warmup carried through, errors should NOT be the "
                 "15-22p cold-start artefacts seen in Phase 3 per-day replay."),
    }
    (OUT / "crossday_warmup_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
