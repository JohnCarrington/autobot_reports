#!/usr/bin/env python3
"""Stage 8 — explain why original EOD exit captured only +1.4..+3.3 pips/trade
despite 32–40 pip average MFE.

For every FIRED signal (p_trend >= 0.5 & dir_conf >= 0.5):
  * mfe_in_pred_dir_pips    — captured in audit CSV; measured until 22:00 UK
  * orig_realised_net_pips  — hold-to-21:00-UK exit from audit CSV
  * Classify shortfall into:
      a) STOP_WOULD_HIT_FIRST(_15p/_20p/_25p) — adverse travel exceeded a
         protective stop before the MFE was reached
      b) MFE_REACHED_LATE  — MFE occurred >=240 min after entry (so a short
         session horizon or news-time window would have missed it)
      c) ROUNDTRIPPED       — MFE existed but price returned past entry
         before the EOD exit; MFE > 20 pips AND orig_realised_net_pips < 5
      d) WRONG_DIR_SMALL_MFE — MFE in pred-dir < 15 pips, so there was no
         significant opportunity
      e) CAPTURED_PARTIAL   — orig exit captured >= 50 % of MFE
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path("<research_workspace>/outputs/nextres")
audit = pd.read_csv(ROOT / "ai_signal_audit.csv")
fired = audit[audit["would_fire_at_0.5"]].copy()
print(f"Fired signals (p_trend>=0.5 & dir_conf>=0.5): {len(fired)}")

def classify(r):
    mfe = r.mfe_in_pred_dir_pips
    mae = r.mae_in_pred_dir_pips
    orig = r.orig_realised_net_pips
    if mfe < 15:
        return "WRONG_DIR_OR_SMALL_MFE"
    if mae >= 15 and mae < 20:
        # a 15-pip stop would have been hit; check: is MFE after the MAE?
        # Approximate: assume MAE comes first if MAE large enough.
        return "STOP_15_WOULD_HIT_FIRST"
    if mae >= 20 and mae < 25:
        return "STOP_20_WOULD_HIT_FIRST"
    if mae >= 25:
        return "STOP_25+_WOULD_HIT_FIRST"
    if r.minutes_to_mfe > 240:
        return "MFE_REACHED_LATE"
    if mfe >= 20 and orig < 5:
        return "ROUNDTRIPPED"
    if orig >= 0.5 * mfe:
        return "CAPTURED_PARTIAL"
    return "OTHER_SHORTFALL"

fired["shortfall_class"] = fired.apply(classify, axis=1)
fired["mfe_realised_gap"] = fired.mfe_in_pred_dir_pips - fired.orig_realised_net_pips

fired.to_csv(ROOT / "mfe_capture_analysis.csv", index=False)

# Summary
print("\n═══ Shortfall classification (OOS: Holdout + Conf2026) ═══")
oos = fired[fired.partition.isin(["Holdout", "Conf2026"])]
tbl = oos.groupby(["partition", "shortfall_class"]).size().unstack("shortfall_class").fillna(0).astype(int)
tbl.loc["COMBINED"] = tbl.sum()
print(tbl.to_string())
print("\nPercentages:")
pct = (tbl.div(tbl.sum(axis=1), axis=0) * 100).round(1)
print(pct.to_string())

print("\n═══ Mean MFE, mean MAE, mean orig-realised by shortfall class ═══")
mt = oos.groupby("shortfall_class").agg(
    n=("date", "count"),
    mean_mfe=("mfe_in_pred_dir_pips", "mean"),
    mean_mae=("mae_in_pred_dir_pips", "mean"),
    mean_orig_net=("orig_realised_net_pips", "mean"),
    mean_minutes_to_mfe=("minutes_to_mfe", "mean"),
    mean_gap=("mfe_realised_gap", "mean"),
).round(1)
print(mt.to_string())

# Headline:
mean_mfe = oos.mfe_in_pred_dir_pips.mean()
mean_orig = oos.orig_realised_net_pips.mean()
print(f"\nOOS mean MFE in pred-dir: {mean_mfe:.1f} pips")
print(f"OOS mean orig-realised net: {mean_orig:+.2f} pips")
print(f"OOS mean capture gap: {mean_mfe - mean_orig:.1f} pips")
print(f"OOS trade count: {len(oos)}")
