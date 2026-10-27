"""Phase 3C — cross-day indicator warmup regression test.

Phase 3 observed EMA cold-start artefacts up to ~22 pips at the start of
each UTC day because the per-day replay instantiated fresh indicator state
at midnight. Production carries state continuously across day boundaries.

This test loads two consecutive certified-usable days, computes BB(20,2)
and EMA(8/13/21/50) continuously, and asserts the first-hour-of-day-B
parity is float-zero against the pre-computed enriched archive.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

from adapters.isolation import init_isolation  # noqa: E402

CACHE = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")
ENRICHED = Path("/opt/tradingbot/data/candles_enriched/GBPUSD")


def _load_m5_mid_range(start_ns, end_ns):
    frames = []
    for yr in sorted({pd.Timestamp(start_ns, unit="ns", tz="UTC").year,
                       pd.Timestamp(end_ns, unit="ns", tz="UTC").year}):
        p = CACHE / f"{yr}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(
            p, columns=["ts_utc_ns", "bid", "ask"],
            filters=[("ts_utc_ns", ">=", start_ns), ("ts_utc_ns", "<", end_ns)],
        )
        if not df.empty:
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts_utc_ns"], unit="ns", utc=True)
    df["mid"] = (df["bid"] + df["ask"]) / 2 * 10000.0
    df["bar"] = df["ts"].dt.floor("5min")
    return df.groupby("bar", sort=True).agg(
        open=("mid", "first"), high=("mid", "max"),
        low=("mid", "min"), close=("mid", "last"),
    ).reset_index().rename(columns={"bar": "ts"})


def test_crossday_warmup_no_cold_start_artefact():
    day_a = "2026-02-09"
    day_b = "2026-02-10"
    start_ns = pd.Timestamp(f"{day_a}T00:00:00+00:00").value
    end_ns = pd.Timestamp(f"{day_b}T23:55:00+00:00").value + 300 * 10**9

    m5 = _load_m5_mid_range(start_ns, end_ns)
    assert len(m5) > 0

    enr = pd.read_csv(ENRICHED / f"{day_b}.csv")
    enr["ts"] = pd.to_datetime(enr["timestamp"], utc=True)
    for c in ("BB_UPPER_20_2", "BB_LOWER_20_2", "EMA_8", "EMA_21"):
        enr[c] = enr[c].astype(float) / 10000.0

    m5["close_fx"] = m5["close"] / 10000.0
    closes = m5["close_fx"].tolist()

    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb

        bb_upper = []
        for i in range(len(closes)):
            if i + 1 < 20:
                bb_upper.append(None)
                continue
            _, _, up = bb._bb_20_2(closes[: i + 1], period=20, std_mult=2.0)
            bb_upper.append(up)

    # Simple EMA
    def _ema(series, period):
        out, s, k = [], None, 2 / (period + 1)
        for i, c in enumerate(series):
            if s is None:
                if i + 1 >= period:
                    s = sum(series[:period]) / period
                    out = [None] * (period - 1) + [s]
                else:
                    out.append(None); continue
            else:
                s = c * k + s * (1 - k); out.append(s)
        while len(out) < len(series): out.append(None)
        return out

    m5["calc_bb_upper"] = bb_upper
    m5["calc_ema_8"] = _ema(closes, 8)
    m5["calc_ema_21"] = _ema(closes, 21)

    merged = m5.merge(enr, on="ts", how="inner")
    day_b_start = pd.Timestamp(f"{day_b}T00:00:00+00:00")
    first_hour = merged[(merged["ts"] >= day_b_start) &
                        (merged["ts"] < day_b_start + pd.Timedelta(hours=1))]
    assert len(first_hour) > 0

    bb_err = float((first_hour["BB_UPPER_20_2"] - first_hour["calc_bb_upper"]).abs().max() * 10000)
    ema8_err = float((first_hour["EMA_8"] - first_hour["calc_ema_8"]).abs().max() * 10000)
    ema21_err = float((first_hour["EMA_21"] - first_hour["calc_ema_21"]).abs().max() * 10000)

    # Phase 3's cold-start first-hour errors were ~17p (EMA_8) and ~22p (EMA_21).
    # With cross-day warmup, both must be float-zero (<= 0.001 pip).
    assert bb_err < 0.001, f"BB upper first-hour err {bb_err} pips (expected float-zero)"
    assert ema8_err < 0.001, f"EMA_8 first-hour err {ema8_err} pips (regression!)"
    assert ema21_err < 0.001, f"EMA_21 first-hour err {ema21_err} pips (regression!)"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
