"""Phase 6 Stage 9 — dynamic broker-minimum scenarios A–E.

For every structural / fixed stop combination, count how many trades
are ADMISSIBLE under each scenario:

    A — Known accepted historical stops.  Infer feasibility only where
        broker evidence exists: the Phase 4 ledger shows the lowest
        historically accepted GBP/USD stop was 4.5 pips (standalone
        BB Bounce).  Admissible iff distance ≥ 4.5.
    B — Hypothetical 4-pip availability (= deployed `IG_MIN_STOP_PIPS`
        and `dealing_rules.json` 2026-09-27 value).
    C — Hypothetical 6-pip minimum (worst-case normal regime).
    D — 12-pip baseline (AutoBot `_ig_min_stop_pips_for_pair`
        internal floor pre-Phase 4).
    E — Observed dynamic minimums (requires continuous observations;
        see Stage 3 observer).  Not yet collected on this host → the
        best available substitute is the 2026-09-27 single-shot
        reading = 4.0 pips → equivalent to Scenario B here.
        Explicitly reported as `substituted` to avoid implying real
        time-varying coverage.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"


def main():
    structural = pd.read_parquet(DATA / "stage8_structural_stop_trades.parquet")
    report = {
        "scenarios": {
            "A_historical_accepted": {"min_pips": 4.5,
                "note": "Phase 4 ledger lowest accepted = 4.5p (standalone BBB)."},
            "B_hypothetical_4p": {"min_pips": 4.0,
                "note": "Deployed BB_IG_MIN_STOP_PIPS = 4.0 (2026-09-27 dealing_rules.json)."},
            "C_hypothetical_6p": {"min_pips": 6.0,
                "note": "Conservative wider floor to capture mild-stress regime."},
            "D_12p_baseline": {"min_pips": 12.0,
                "note": "AutoBot central-execution internal floor pre-Phase 4."},
            "E_observed_dynamic_substituted": {"min_pips": 4.0,
                "note": "No multi-sample observer run yet. Substituted = Scenario B."},
        },
        "fixed_stop_admissibility": {},
        "structural_buffer_admissibility": {},
    }

    # Fixed stop admissibility: stop ∈ {4,5,6,8,10,12} vs min pips
    for stop in [4, 5, 6, 8, 10, 12]:
        row = {}
        for name, scn in report["scenarios"].items():
            row[name] = "ADMISSIBLE" if stop >= scn["min_pips"] else "INELIGIBLE"
        report["fixed_stop_admissibility"][f"s{stop}"] = row

    # Structural buffer admissibility: per-trade distance from Stage 8
    for buf in [0.5, 1.0, 2.0, 3.0]:
        dist = structural[f"stop_dist_pips_b{buf}"].astype(float)
        row = {}
        for name, scn in report["scenarios"].items():
            n_eligible = int((dist >= scn["min_pips"]).sum())
            n_total = int(len(dist))
            row[name] = {
                "n_eligible": n_eligible,
                "n_ineligible": n_total - n_eligible,
                "pct_eligible": round(100.0 * n_eligible / max(1, n_total), 2),
            }
        report["structural_buffer_admissibility"][f"b{buf}"] = row

    (DATA / "stage9_dynamic_broker_minimums.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
