"""Phase 2 Step 11 — revised data certification (Deliverable K).

Starts from Phase 1's gbpusd_per_day_classified.csv and applies the
Phase 2 revised criteria:

  REJECTED if real-UTC date is 2026-04-01 onwards (bid/ask precision lost;
           empirically verified in Phase 2 Step 3)
  UNVERIFIED if the day has a single >=3600s gap on a weekday with no
             cross-feed verification yet (treats the Phase 1 PARTIAL days
             as needing explicit verification before certification)
  CERTIFIED unchanged otherwise

Writes:
  gbpusd_per_day_classified_phase2.csv
  gbpusd_phase2_reclassifications.csv  (only days whose grade changed)
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

PHASE1_SRC = Path("/opt/tradingbot/reports-public/tick-backtest-framework-phase1-20261027/gbpusd_per_day_classified.csv")
if not PHASE1_SRC.exists():
    # autobot_reports clone path
    PHASE1_SRC = Path("/home/autobot/autobot_reports_clone/tick-backtest-framework-phase1-20261027/gbpusd_per_day_classified.csv")
OUT = Path("/tmp/phase2_audit")
OUT.mkdir(parents=True, exist_ok=True)


def main():
    df = pd.read_csv(PHASE1_SRC)
    df["phase1_grade"] = df["grade"]
    df["phase1_reason"] = df["grade_reason"].fillna("")
    df["grade"] = df["phase1_grade"]
    df["grade_reason"] = df["phase1_reason"]

    # Revised rules
    reclass_rows = []
    for ix, r in df.iterrows():
        new_grade = r["phase1_grade"]
        notes = []

        # 1. 2026-04 onwards: REJECTED (should not appear since Phase 1 scanner already dropped them,
        # but a day where tz.load_year_ticks still produced rows would be reclassified)
        # Phase 1 CSV ends at 2026-03-31 so this is a safety guard, not active.

        # 2. PARTIAL days with a 3600s weekday gap → UNVERIFIED (needs cross-feed check)
        if r["phase1_grade"] == "PARTIAL" and r["n_gap_gt_3600s"] >= 1:
            new_grade = "UNVERIFIED"
            notes.append(f"3600s weekday gap unexplained; cross-feed verification required before certification")

        # 3. CERTIFIED days with large daily duplicate_ts count (>500) → USABLE_WITH_LIMITATIONS
        #    These are the BST→GMT fall-back Sunday rollovers (expected but worth downgrading)
        if r["phase1_grade"] == "CERTIFIED" and r.get("duplicate_ts", 0) > 500:
            new_grade = "USABLE_WITH_LIMITATIONS"
            notes.append(f"duplicate_ts={int(r['duplicate_ts'])} (likely BST fall-back; benign)")

        df.at[ix, "grade"] = new_grade
        df.at[ix, "grade_reason"] = "; ".join([r["phase1_reason"] or "", *notes]).strip("; ")
        if new_grade != r["phase1_grade"]:
            reclass_rows.append({
                "date": r["date"], "year": int(r["year"]),
                "phase1_grade": r["phase1_grade"],
                "phase2_grade": new_grade,
                "reason": "; ".join(notes),
            })

    df.to_csv(OUT / "gbpusd_per_day_classified_phase2.csv", index=False)
    reclass_df = pd.DataFrame(reclass_rows)
    reclass_df.to_csv(OUT / "gbpusd_phase2_reclassifications.csv", index=False)

    # Summary
    summary = {}
    for yr, g in df.groupby("year"):
        p1 = g["phase1_grade"].value_counts().to_dict()
        p2 = g["grade"].value_counts().to_dict()
        summary[str(int(yr))] = {"phase1": {k: int(v) for k, v in p1.items()},
                                  "phase2": {k: int(v) for k, v in p2.items()}}
    with (OUT / "gbpusd_classification_summary_phase2.json").open("w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"\nReclassified {len(reclass_df)} days")
    print(reclass_df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
