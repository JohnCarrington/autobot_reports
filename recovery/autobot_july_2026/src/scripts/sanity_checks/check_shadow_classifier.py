"""Sanity check for Phase 4B shadow classifier.

Loads recent raw OHLC, enriches via indicators.add_indicators, runs
CandleRegimeClassifier.update_from_df bar-by-bar, then reports:
  - last 10 bars: ts, gate-cascade label, shadow label, confidence, votes
  - shadow label distribution
  - shadow confidence distribution
  - gate ↔ shadow directional agreement count
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from indicators import add_indicators, IndicatorsConfig
from regime_classifier import CandleRegimeClassifier


SYMBOL = "GBPUSD"
PIP_SIZE = 1.0
CANDLE_DIR = Path("data/candles") / SYMBOL
DAYS_TO_LOAD = 8


def load_raw_ohlc(symbol: str, days: int) -> pd.DataFrame:
    files = sorted(CANDLE_DIR.glob("2026-*.csv"))
    files = files[-days:]
    frames = []
    for f in files:
        frames.append(pd.read_csv(f))
    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def agree_directionally(gate: str, shadow: str) -> bool:
    return (
        (gate == "TREND_UP" and shadow == "TRENDING_BULL")
        or (gate == "TREND_DOWN" and shadow == "TRENDING_BEAR")
        or (gate == "RANGE" and shadow == "RANGE")
        or (gate == "NEUTRAL" and shadow == "NEUTRAL")
    )


def main():
    raw = load_raw_ohlc(SYMBOL, DAYS_TO_LOAD)
    print(f"Loaded {len(raw)} raw bars across {DAYS_TO_LOAD} days")

    enriched = add_indicators(raw, IndicatorsConfig(), pip_size=PIP_SIZE, caller="check_shadow")
    print(f"Enriched columns: {len(enriched.columns)}")
    for c in ("EMA_STACK_STATE", "BB_WIDTH_PCTL_20_2", "BB_MID_SLOPE_5_20", "ATR_PCTL_14"):
        present = c in enriched.columns
        non_null = int(enriched[c].notna().sum()) if present else 0
        print(f"  {c}: present={present}, non_null={non_null}/{len(enriched)}")
    print()

    clf = CandleRegimeClassifier(SYMBOL, pip_size=PIP_SIZE)

    rows = []
    need = max(clf.cfg.bb_period, clf.cfg.ema_period, clf.cfg.slope_lookback + 1)
    for i in range(need, len(enriched) + 1):
        sub = enriched.iloc[:i].copy()
        stable, out = clf.update_from_df(sub, pip_size=PIP_SIZE)
        shadow = out.get("shadow", {}) or {}
        rows.append(
            {
                "ts": enriched.iloc[i - 1]["timestamp"],
                "gate": stable,
                "shadow_label": shadow.get("label"),
                "shadow_conf": shadow.get("confidence"),
                "votes": shadow.get("votes"),
                "warmup": out.get("warmup", False),
                "missing": shadow.get("missing"),
            }
        )

    df_out = pd.DataFrame(rows)
    print(f"Classified {len(df_out)} bars")
    print()

    print("=== Last 10 bars ===")
    for _, r in df_out.tail(10).iterrows():
        print(
            f"{r['ts']} | gate={r['gate']:<11} | shadow={str(r['shadow_label']):<14} "
            f"| conf={r['shadow_conf']:<4} | votes={r['votes']}"
        )
    print()

    def report(df_scope: pd.DataFrame, tag: str) -> None:
        print(f"=== [{tag}] n={len(df_scope)} ===")
        print("Shadow label distribution:")
        lbl = df_scope["shadow_label"].value_counts(dropna=False)
        for k, v in lbl.items():
            print(f"  {str(k):<14} {v:>5}  ({100.0*v/len(df_scope):.1f}%)")
        print("Shadow confidence distribution:")
        cf = df_scope["shadow_conf"].value_counts(dropna=False)
        for k, v in cf.items():
            print(f"  {str(k):<6} {v:>5}  ({100.0*v/len(df_scope):.1f}%)")
        print("Gate distribution:")
        g = df_scope["gate"].value_counts(dropna=False)
        for k, v in g.items():
            print(f"  {str(k):<12} {v:>5}  ({100.0*v/len(df_scope):.1f}%)")
        agree = sum(
            1
            for _, r in df_scope.iterrows()
            if r["shadow_label"] is not None
            and agree_directionally(r["gate"], r["shadow_label"])
        )
        print(
            f"Gate ↔ Shadow directional agreement: "
            f"{agree}/{len(df_scope)} ({100.0*agree/len(df_scope):.1f}%)"
        )
        print()

    report(df_out, "full sample")

    # ATR_PCTL_14 needs 576 bars to produce non-NaN. Strip bars where it was
    # the warmup-dominant degrader and re-report, so we can tell whether the
    # NEUTRAL/LOW skew is warmup-driven or threshold-driven.
    WARMUP_BARS = 576
    if len(df_out) > WARMUP_BARS:
        report(df_out.iloc[WARMUP_BARS:].reset_index(drop=True), f"post-warmup (skip first {WARMUP_BARS})")


if __name__ == "__main__":
    main()
