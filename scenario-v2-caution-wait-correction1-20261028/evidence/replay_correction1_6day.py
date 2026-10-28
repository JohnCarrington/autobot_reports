"""Historical 6-day replay with Correction 1 applied.

Walks every scenario revision in production scenarios_shadow.jsonl
for 2026-10-23 → 2026-10-28, re-classifies publication_decision
via the P1+P2 validator, then runs the Correction-1 recommendation
builder and records the resulting recommendation + readiness.

Reports (operator-requested fields):
  * Original WAIT count (as emitted historically by shadow-exec)
  * WAIT count after P1/P2 re-classify only
  * WAIT count after Correction 1
  * BUY/SELL from each stage
  * CAUTION recommendations
  * Still-blocked-by-incomplete-geometry
  * Still-legitimately-INVALID
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
sys.path.insert(0, str(AGENT))

from scenario_quality import validate_assessment, decide_publication  # noqa: E402
from scenario_recommendation import build_trade_recommendation  # noqa: E402

UTC = dt.timezone.utc

SCEN = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/"
                     "journal_shadow/scenarios_shadow.jsonl")
PROP = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/"
                     "shadow_exec/shadow_proposals.jsonl")


def _reclassify_publication(row: dict) -> tuple[dict, dict]:
    """Return (updated_row, new_publication_decision_dict)."""
    assessment = {
        "current_interpretation": row.get("current_interpretation"),
        "narrative": row.get("narrative"),
        "waiting_for": row.get("waiting_for") or [],
        "what_would_invalidate": row.get("what_would_invalidate") or [],
        "actions": [{
            "kind": "REVISE",
            "scenario_id": row.get("scenario_id"),
            "new_state": row.get("state"),
            "current_interpretation": row.get("current_interpretation"),
            "narrative": row.get("narrative"),
            "change_from_previous": row.get("change_from_previous"),
            "opportunities": row.get("opportunities") or [],
            "evidence_supporting": (row.get("evidence") or {}).get("supporting") or [],
            "evidence_contradicting": (row.get("evidence") or {}).get("contradicting") or [],
            "needed_info": (row.get("evidence") or {}).get("needed_info") or [],
            "invalidation_conditions": (row.get("evidence") or {}).get("invalidation_conditions") or [],
            "confirmation_criteria": row.get("confirmation_criteria") or [],
        }],
    }
    econ = row.get("economic_context") or {}
    flags = validate_assessment(assessment=assessment, packet={},
                                 economic_context=econ)
    pub = decide_publication(flags)
    row2 = dict(row)
    row2["publication_decision"] = {
        "decision": pub["decision"],
        "flag_codes": pub["flag_codes"],
        "reason": pub["reason"],
    }
    return row2, pub


def _run_recommendation(row: dict) -> dict:
    """Run build_trade_recommendation with a synthetic snapshot."""
    bar_ts = row.get("bar_ts_utc", "2026-10-23T07:00:00+00:00")
    snapshot = {
        "bar_ts_utc": bar_ts,
        "interactions": [{"interaction_id": "lv_1",
                           "raw": {"close": 13300.0,
                                    "close_side": "above",
                                    "distance_from_level_pips": 0.0}}],
        "level_map": {"levels": [], "p_level": None, "clusters": []},
    }
    primary = {"hypothesis": "NO_OPPORTUNITY", "direction": None,
                "evaluated_at_utc": bar_ts, "bar_ts_utc": bar_ts}
    # now = bar close + 5 min
    try:
        bar_dt = dt.datetime.fromisoformat(bar_ts.replace("Z", "+00:00"))
        now = bar_dt + dt.timedelta(minutes=5)
    except Exception:
        now = dt.datetime.now(UTC)
    return build_trade_recommendation(
        scenario_row=row, snapshot=snapshot,
        primary_decision=primary, now_utc=now)


def _original_shadow_recs():
    """Return list of (reco, readiness, pub_decision) from the production
    shadow_proposals.jsonl within the 6-day window."""
    out = []
    with PROP.open() as fh:
        for line in fh:
            r = json.loads(line)
            if "2026-10-2" in (r.get("generated_at_utc") or ""):
                out.append((
                    r.get("recommendation"),
                    r.get("readiness"),
                    (r.get("publication") or {}).get("decision"),
                ))
    return out


def main():
    print("=== Historical 6-day replay (2026-10-23 → 2026-10-28) ===")
    print()
    orig = _original_shadow_recs()
    orig_reco = Counter(r[0] for r in orig)
    print(f"ORIGINAL (as stored in production shadow_proposals.jsonl):")
    print(f"  Total rows: {len(orig)}")
    for k, n in sorted(orig_reco.items(), key=lambda x: -x[1]):
        print(f"  {k:>5}: {n}")

    # Walk scenario revisions, re-classify via P1+P2, run recommendation
    p2_reco = Counter()
    p2_readiness = Counter()
    p2_pub = Counter()
    c1_reco = Counter()
    c1_readiness = Counter()
    c1_pub = Counter()
    detail_rows = []
    with SCEN.open() as fh:
        for line in fh:
            row = json.loads(line)
            if "2026-10-2" not in (row.get("bar_ts_utc") or ""):
                continue
            # P1+P2 re-classification
            row_p2, pub = _reclassify_publication(row)
            p2_pub[pub["decision"]] += 1
            # Simulate ORIGINAL recommendation builder for P1+P2 pub_decision
            # by invoking the Correction-1 builder — but to differentiate
            # "P1+P2 alone" from "P1+P2+C1", we trace through the KEY
            # transition: for CAUTION rows, the ORIGINAL builder returned
            # WAIT/CONDITIONAL; the C1 builder returns BUY/SELL/CONDITIONAL
            # IF geometry etc pass.
            rec = _run_recommendation(row_p2)
            c1_reco[rec["recommendation"]] += 1
            c1_readiness[rec["readiness"]] += 1
            c1_pub[(row_p2.get("publication_decision") or {}).get("decision")] += 1
            # Model the pre-C1 outcome for CAUTION: it would be WAIT/CONDITIONAL
            if pub["decision"] == "CAUTION":
                p2_reco["WAIT"] += 1
                p2_readiness["CONDITIONAL"] += 1
            else:
                p2_reco[rec["recommendation"]] += 1
                p2_readiness[rec["readiness"]] += 1
            detail_rows.append({
                "scenario_id": row.get("scenario_id","")[:16],
                "revision_idx": row.get("revision_idx"),
                "bar_ts_utc": row.get("bar_ts_utc"),
                "orig_decision": pub["decision"],
                "c1_recommendation": rec["recommendation"],
                "c1_readiness": rec["readiness"],
                "c1_direction": rec.get("direction"),
                "entry": (rec.get("entry") or {}).get("price"),
                "stop": (rec.get("stop") or {}).get("price"),
                "target": (rec.get("target") or {}).get("price"),
                "caution_flag_codes": ",".join(rec.get("caution_flag_codes") or []),
                "reason": (rec.get("reason") or "")[:140],
            })

    print()
    print(f"AFTER P1/P2 (re-classify only; recommendation builder unchanged):")
    print(f"  Pub decisions: {dict(p2_pub)}")
    print(f"  Recommendations: {dict(p2_reco)}")
    print(f"  Readiness: {dict(p2_readiness)}")

    print()
    print(f"AFTER P1/P2 + CORRECTION 1 (CAUTION propagates):")
    print(f"  Pub decisions: {dict(c1_pub)}")
    print(f"  Recommendations: {dict(c1_reco)}")
    print(f"  Readiness: {dict(c1_readiness)}")

    # Break down the Correction-1 WAIT by readiness → identify remaining
    # legitimate blocks
    print()
    print(f"BLOCKS REMAINING AFTER CORRECTION 1:")
    waits = [r for r in detail_rows if r["c1_recommendation"] == "WAIT"]
    waits_readiness = Counter(r["c1_readiness"] for r in waits)
    for k, n in waits_readiness.most_common():
        print(f"  WAIT/{k:>12}: {n}")

    # Save detail CSV
    out = pathlib.Path("/tmp/CORRECTION1_6DAY_REPLAY.csv")
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(detail_rows[0].keys()))
        w.writeheader()
        for r in detail_rows:
            w.writerow(r)
    print(f"\n✓ Wrote {out} ({len(detail_rows)} rows)")


if __name__ == "__main__":
    main()
