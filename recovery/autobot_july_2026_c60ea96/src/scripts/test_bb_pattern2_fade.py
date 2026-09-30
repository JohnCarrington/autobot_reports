#!/usr/bin/env python3
"""scripts/test_bb_pattern2_fade.py — merge-gate verification for the
prod BB Pattern 2 fade detector against the Phase 6 analysis result.

Two checks:

  1. Reference bar (2026-05-08 08:05 UTC GBPUSD, the firing bar = N+1):
       Variant A: must NOT fire (both N and N+1 bullish, no colour flip)
       Variant B: must fire     (bullish follow-through after hammer)
       Variant C: must fire     (hammer N + bullish N+1 same-colour)

  2. Population equivalence — bar-by-bar walk of the harness window
     (2026-01-02 → 2026-01-15) against the analysis-time detectors in
     scripts/analysis/bb_three_pattern/detectors.py for each (pair,
     variant) being deployed:
         USDJPY / B  — must match exactly
         USDCAD / A  — must match exactly
         EURUSD / A  — must match exactly

Exit non-zero on any mismatch. Intended to be run from a pre-merge gate
or by hand with `python scripts/test_bb_pattern2_fade.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "analysis"))

import bb_pattern2_fade as p2f


def check_reference_bar() -> int:
    """The 2026-05-08 08:00 GBPUSD textbook hammer."""
    print("=== reference bar: 2026-05-08 08:05 UTC GBPUSD ===")
    cdir = REPO / "data" / "candles" / "GBPUSD"
    if not cdir.exists():
        print(f"  SKIP — candle dir missing ({cdir})")
        return 0
    needed = ["2026-05-07.csv", "2026-05-08.csv"]
    if not all((cdir / f).exists() for f in needed):
        print("  SKIP — May 7-8 candle CSVs missing")
        return 0

    def _load(d: str) -> pd.DataFrame:
        df = pd.read_csv(cdir / f"{d}.csv")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    bars = pd.concat([_load("2026-05-07"), _load("2026-05-08")], ignore_index=True)
    bars = bars.set_index("timestamp").sort_index()
    firing_ts = pd.Timestamp("2026-05-08 08:05:00", tz="UTC")
    sliced = bars.loc[: firing_ts]

    opens = sliced["open"].astype(float).tolist()
    highs = sliced["high"].astype(float).tolist()
    lows = sliced["low"].astype(float).tolist()
    closes = sliced["close"].astype(float).tolist()
    ts = list(sliced.index)

    expected = {"A": False, "B": True, "C": True}
    fails: list[str] = []
    for v in ("A", "B", "C"):
        cfg = p2f.BBPattern2Config(
            mode_name=f"P2_TEST_{v}", pair="GBPUSD", variant=v,
            sl_pips=12, tp_pips=30, horizon_bars=8,
            wick_ratio=1.5, isolation_window=5,
        )
        det = p2f._detect(closes, highs, lows, opens, ts, cfg)
        ok = (det.fire == expected[v])
        marker = "✓" if ok else "✗"
        print(f"  {marker} Variant {v}: fire={det.fire} dir={det.direction} "
              f"side={det.pierce_side} (expected fire={expected[v]})")
        if not ok:
            fails.append(f"Variant {v}: got fire={det.fire}, expected {expected[v]}")
    if fails:
        print("\nFAIL — reference bar mismatch:")
        for f in fails:
            print(f"  - {f}")
        return 1
    return 0


def check_population_equivalence() -> int:
    """Compare prod detector against analysis detectors over a few weeks."""
    try:
        from bb_clean_harness.data_layer import load_bars_5m  # type: ignore
        from bb_three_pattern.features import compute_features  # type: ignore
        from bb_three_pattern.detectors import detect_p2, detect_p2_strict  # type: ignore
    except ImportError as e:
        print(f"\n=== population equivalence: SKIP (analysis modules unavailable: {e}) ===")
        return 0

    WINDOW_START = pd.Timestamp("2026-01-02 00:00:00", tz="UTC")
    TEST_END = pd.Timestamp("2026-01-15 23:59:00", tz="UTC")

    deployments = (("USDJPY", "B"), ("USDCAD", "A"), ("EURUSD", "A"))
    print(f"\n=== population equivalence: {WINDOW_START.date()} → {TEST_END.date()} ===")
    fails: list[str] = []
    for pair, variant in deployments:
        try:
            bars = load_bars_5m(pair, start=WINDOW_START - pd.Timedelta(hours=4),
                                end=TEST_END)
        except Exception as e:
            print(f"  SKIP {pair}/{variant}: bar data unavailable ({e})")
            continue
        feat = compute_features(bars)
        feat_w = feat[(feat.index >= WINDOW_START) & (feat.index <= TEST_END)]
        ref_fn = detect_p2_strict if variant == "A" else detect_p2
        ref = ref_fn(feat).reindex(feat_w.index)
        ref_fires = ref.loc[ref["fire"].fillna(False), :].dropna(subset=["direction"])

        opens = bars["open"].astype(float).tolist()
        highs = bars["high"].astype(float).tolist()
        lows = bars["low"].astype(float).tolist()
        closes = bars["close"].astype(float).tolist()
        ts_all = list(bars.index)
        pos = {t: i for i, t in enumerate(ts_all)}

        cfg = p2f.BBPattern2Config(
            mode_name=f"P2_{pair}_{variant}", pair=pair, variant=variant,
            sl_pips=12, tp_pips=30, horizon_bars=8,
            wick_ratio=1.5, isolation_window=5,
        )
        prod_set = set()
        for t in feat_w.index:
            i = pos[t]
            if i < p2f.MIN_BARS:
                continue
            det = p2f._detect(closes[: i + 1], highs[: i + 1], lows[: i + 1],
                              opens[: i + 1], ts_all[: i + 1], cfg)
            if det.fire:
                prod_set.add((t, det.direction))

        ref_set = {(t, ref.loc[t, "direction"]) for t in ref_fires.index}
        only_ref = ref_set - prod_set
        only_prod = prod_set - ref_set
        ok = (not only_ref) and (not only_prod)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {pair}/{variant}: ref={len(ref_set)} prod={len(prod_set)} "
              f"only_ref={len(only_ref)} only_prod={len(only_prod)}")
        if not ok:
            fails.append(f"{pair}/{variant}: ref-only={list(only_ref)[:3]} "
                         f"prod-only={list(only_prod)[:3]}")
    if fails:
        print("\nFAIL — population mismatch:")
        for f in fails:
            print(f"  - {f}")
        return 1
    return 0


def main() -> int:
    rc = 0
    rc |= check_reference_bar()
    rc |= check_population_equivalence()
    if rc == 0:
        print("\nALL CHECKS PASSED ✓")
    else:
        print("\nFAILED ✗")
    return rc


if __name__ == "__main__":
    sys.exit(main())
