"""Full 6-day replay — run every suppressed scenario revision through
the P1-corrected validator and report before/after publication_decision.

Inputs:
  * /mnt/.../journal_shadow/scenarios_shadow.jsonl — scenario revisions
  * /mnt/.../news/verified_events.jsonl — macro feed
  * /tmp/incident_catalogue.csv — 122-row expected-suppression table

Output:
  * Per-row result table (CSV)
  * Summary: before→after flag reduction
"""
from __future__ import annotations
import csv
import json
import pathlib
import sys
from datetime import datetime, timezone
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
sys.path.insert(0, str(AGENT))

from scenario_quality import validate_assessment, decide_publication
from scenario_schema import classify_economic_context
from market_observer_macro import build_macro_packet

SCEN = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/"
                     "journal_shadow/scenarios_shadow.jsonl")
EVENTS = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/"
                      "news/verified_events.jsonl")

# Load catalogue of 122 rows (one per INVALID+UNVERIFIED proposal)
cat = list(csv.DictReader(open("/tmp/incident_catalogue.csv")))
# Build (bar_ts_utc, scenario_id, revision_idx) → row
want = set()
for r in cat:
    want.add((r["bar_ts_utc"], r["scenario_id"], int(r["revision_idx"])))

# Load scenario revisions
scenarios_by_key = {}
with SCEN.open() as fh:
    for line in fh:
        r = json.loads(line)
        key = (r.get("bar_ts_utc"), r.get("scenario_id"), r.get("revision_idx"))
        scenarios_by_key[key] = r

print(f"Catalogue rows: {len(want)}; scenario revs loaded: {len(scenarios_by_key)}")

matched = 0
unmatched = []
for key in want:
    if key in scenarios_by_key:
        matched += 1
    else:
        unmatched.append(key)
print(f"Matched to scenario rows: {matched}")
if unmatched:
    print(f"Unmatched {len(unmatched)}: first 3: {unmatched[:3]}")


def _econ_at(bar_ts_iso: str):
    """Build classified economic context as of bar_ts (floored to minute)."""
    try:
        asof = datetime.fromisoformat(bar_ts_iso.replace("Z", "+00:00"))
    except Exception:
        return {}
    pkt = build_macro_packet(asof=asof, source_mode="operator_jsonl",
                              event_file=EVENTS, read_news_state=False)
    return classify_economic_context(pkt)


def _assessment_from_row(row: dict) -> dict:
    """Reconstruct an assessment dict that mirrors what the validator
    saw at scenario emission time."""
    opps = row.get("opportunities") or []
    actions = [{
        "kind": "REVISE",
        "scenario_id": row.get("scenario_id"),
        "new_state": row.get("state"),
        "current_interpretation": row.get("current_interpretation"),
        "narrative": row.get("narrative"),
        "change_from_previous": row.get("change_from_previous"),
        "opportunities": opps,
        "evidence_supporting": row.get("evidence_supporting") or [],
        "evidence_contradicting": row.get("evidence_contradicting") or [],
        "needed_info": row.get("needed_info") or [],
        "invalidation_conditions": row.get("invalidation_conditions") or [],
        "confirmation_criteria": row.get("confirmation_criteria") or [],
    }]
    return {
        "current_interpretation": row.get("current_interpretation"),
        "narrative": row.get("narrative"),
        "waiting_for": row.get("waiting_for") or [],
        "what_would_invalidate": row.get("what_would_invalidate") or [],
        "actions": actions,
    }


# Cache econ context per bar_ts to amortise macro-packet rebuild
econ_cache = {}

results = []
for cat_row in cat:
    key = (cat_row["bar_ts_utc"], cat_row["scenario_id"], int(cat_row["revision_idx"]))
    r = scenarios_by_key.get(key)
    if r is None:
        results.append({**cat_row, "after_decision": "NO_SCENARIO_ROW",
                         "after_flag_count": None, "after_flag_codes": ""})
        continue
    bar_ts = r.get("bar_ts_utc")
    if bar_ts not in econ_cache:
        econ_cache[bar_ts] = _econ_at(bar_ts)
    econ = econ_cache[bar_ts]
    a = _assessment_from_row(r)
    flags = validate_assessment(assessment=a, packet={}, economic_context=econ)
    dec = decide_publication(flags)
    results.append({
        **cat_row,
        "after_decision": dec.get("decision"),
        "after_flag_count": len(flags),
        "after_flag_codes": ",".join(sorted(set(f["code"] for f in flags))),
    })

# Dump
out_path = pathlib.Path("/tmp/replay_p1_outcome.csv")
with out_path.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
    w.writeheader()
    for r in results:
        w.writerow(r)
print(f"wrote {out_path}")

print()
print("=== Before/After publication_decision for 122 suppressed rows ===")
before_after = Counter((r.get("result"), r.get("after_decision")) for r in results)
after_counter = Counter(r.get("after_decision") for r in results)
print("After decision distribution:")
for d, n in after_counter.most_common():
    print(f"  {d:20} {n:>4}")

print()
print("Transition by original outcome:")
by_result = defaultdict(Counter)
for r in results:
    by_result[r.get("result")][r.get("after_decision")] += 1
for res, dist in by_result.items():
    print(f"  {res:28} {dict(dist)}")

# Specifically: of the 52 fed-only rows, how many now pass?
fed_names = {"atlanta fed gdpnow", "chicago fed national activity index",
             "dallas fed manufacturing index"}
cbi_names = {"cbi distributive trades", "cbi business optimism index"}
fed_only_rows = []
cbi_only_rows = []
mixed_rows = []
for r in results:
    events = set(r["quarantined_events"].split(";")) - {""}
    if events & fed_names and not events & cbi_names:
        fed_only_rows.append(r)
    elif events & cbi_names and not events & fed_names:
        cbi_only_rows.append(r)
    elif events & fed_names and events & cbi_names:
        mixed_rows.append(r)
print()
print(f"Fed-only rows (n={len(fed_only_rows)}): "
      f"{dict(Counter(r['after_decision'] for r in fed_only_rows))}")
print(f"CBI-only rows (n={len(cbi_only_rows)}): "
      f"{dict(Counter(r['after_decision'] for r in cbi_only_rows))}")
print(f"Mixed rows (n={len(mixed_rows)}): "
      f"{dict(Counter(r['after_decision'] for r in mixed_rows))}")
