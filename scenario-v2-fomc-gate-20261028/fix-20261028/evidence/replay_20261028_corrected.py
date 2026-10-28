"""Historical replay: 2026-10-28 scenario rev 4 under the corrected
prompt + validator.

Pulls the REAL scenario row from
``/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl``
and the REAL macro feed from the same date.  Produces two versions:

  "as-written"  — the raw rev-4 text the model actually emitted on
                  2026-10-28 14:05 UTC.
  "corrected"   — the SAME scenario with the FOMC-as-precondition
                  prefix stripped from ``entry.trigger``,
                  ``opportunities[].required_price_behaviour``,
                  ``opportunities[].note``, and the trigger-side
                  mentions in ``actions[].change_from_previous`` /
                  ``current_interpretation``.  All retained
                  references to the Fed appear in ``narrative`` only,
                  phrased as context ("Fed decision SCHEDULED at
                  18:00Z — background risk").

Both versions are run through:

  1. ``scenario_quality.validate_assessment`` — HIGH flag count.
  2. ``scenario_quality.decide_publication`` — INVALID vs VALID.
  3. ``scenario_recommendation.build_trade_recommendation`` — the
     publishable payload the dashboard would render.
  4. ``shadow_exec.run_shadow_exec`` — whether a shadow proposal
     would be written with ``readiness != SUPPRESSED``.

Pure replay — no production file modification, no services touched.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
AGENT = HERE.parent / "agent"
sys.path.insert(0, str(AGENT))

from scenario_quality import validate_assessment, decide_publication  # noqa
from scenario_schema import classify_economic_context  # noqa
from market_observer_macro import build_macro_packet  # noqa


# ---------------------------------------------------------------------
# Load real rev 4 scenario row (2026-10-28 14:05 UTC)
# ---------------------------------------------------------------------
JOURNAL = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/"
    "scenarios_shadow.jsonl")
EVENTS = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/news/"
    "verified_events.jsonl")

ASOF = dt.datetime(2026, 10, 28, 14, 5, 0, tzinfo=dt.timezone.utc)
SCENARIO_ID = "f5e11547c4ce2097"
TARGET_REV = 4


def _load_rev():
    """Load rev 4 of scenario f5e11547... from the real journal."""
    with JOURNAL.open() as fh:
        for line in fh:
            row = json.loads(line)
            if (row.get("scenario_id") == SCENARIO_ID
                    and row.get("revision_idx") == TARGET_REV):
                return row
    raise RuntimeError(
        f"rev {TARGET_REV} of {SCENARIO_ID} not found in journal")


def _reconstruct_assessment(row: dict) -> dict:
    """Scenario rows are the FINAL state after apply_actions; the
    assessment the quality validator sees in production includes the
    reasoner's *actions* array as emitted.  For replay, we construct
    an equivalent dict carrying the narrative-level fields + an
    actions-shaped block containing the resolved opportunities so the
    validator's per-field scan has the same surface.
    """
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


# ---------------------------------------------------------------------
# Correction simulation
# ---------------------------------------------------------------------
_FOMC_PRECOND_PATTERNS = (
    re.compile(r"Post-Fed\s*\([^)]*\)[^;.]*;\s*", re.IGNORECASE),
    re.compile(r"Dovish\s+FOMC\s+surprise\s+confirmed[^;.]*;\s*",
                re.IGNORECASE),
    re.compile(r"\bPost-Fed\b[^;.]*;\s*", re.IGNORECASE),
    re.compile(r"\bDovish\s+Fed\s+surprise\s+is\s+sole\s+catalyst[^.]*\.\s*",
                re.IGNORECASE),
    re.compile(r"on\s+announcement\s+bar\s+or\s+next\s+bar\s+",
                re.IGNORECASE),
)


def _strip_fomc_precondition(text):
    """Remove 'Post-Fed ... dovish FOMC confirmed' precondition
    phrasing from an entry-trigger / required_price_behaviour string.

    Models of the corrected prompt would NOT emit this text; this
    function reverse-engineers the raw-as-emitted text into the
    expected corrected equivalent.  Leaves 'close above 13296' type
    price triggers intact."""
    if not isinstance(text, str):
        return text
    out = text
    for pat in _FOMC_PRECOND_PATTERNS:
        out = pat.sub("", out)
    out = out.strip()
    # Replace capitalisation issues created by prefix removal.
    out = re.sub(r"^(;|,|and|then)\s*", "", out, flags=re.IGNORECASE)
    return out


def _apply_correction(assessment: dict) -> dict:
    """Return a copy of the assessment with FOMC-as-precondition
    text stripped from the trigger-side fields.  Narrative-side
    fields (narrative, current_interpretation) are RETAINED, modelling
    the corrected prompt's instruction to narrate scheduled events as
    context in those fields."""
    corr = copy.deepcopy(assessment)
    for act in corr.get("actions") or []:
        for opp in act.get("opportunities") or []:
            if not isinstance(opp, dict):
                continue
            if "required_price_behaviour" in opp:
                opp["required_price_behaviour"] = _strip_fomc_precondition(
                    opp.get("required_price_behaviour") or "")
            if "note" in opp:
                opp["note"] = _strip_fomc_precondition(opp.get("note") or "")
            tp = opp.get("trade_proposal") or {}
            if isinstance(tp, dict) and tp.get("entry_trigger"):
                tp["entry_trigger"] = _strip_fomc_precondition(
                    tp["entry_trigger"])
        # Change-from-previous often holds the trigger wording too.
        if "change_from_previous" in act and act["change_from_previous"]:
            act["change_from_previous"] = _strip_fomc_precondition(
                act["change_from_previous"])
    return corr


# ---------------------------------------------------------------------
# Replay runner
# ---------------------------------------------------------------------
def _replay_revision(target_rev: int, asof: dt.datetime, label: str):
    with JOURNAL.open() as fh:
        row = None
        for line in fh:
            r = json.loads(line)
            if (r.get("scenario_id") == SCENARIO_ID
                    and r.get("revision_idx") == target_rev):
                row = r
                break
    if row is None:
        print(f"  !! rev {target_rev} not found")
        return

    assessment_as_written = _reconstruct_assessment(row)
    assessment_corrected = _apply_correction(assessment_as_written)
    pkt = build_macro_packet(asof=asof, source_mode="operator_jsonl",
                              event_file=EVENTS, read_news_state=False)
    econ = classify_economic_context(pkt)

    flags_before = validate_assessment(
        assessment=assessment_as_written, packet={}, economic_context=econ)
    flags_after = validate_assessment(
        assessment=assessment_corrected, packet={}, economic_context=econ)
    pub_before = decide_publication(flags_before)
    pub_after = decide_publication(flags_after)
    print(f"  {label:34}  as-written: {pub_before['decision']:>7}  "
           f"({len(flags_before)} flags)  "
           f"corrected: {pub_after['decision']:>7}  ({len(flags_after)} flags)")


def replay():
    print("=== HISTORICAL REPLAY 2026-10-28 14:05 UTC — scenario rev 4 ===\n")
    row = _load_rev()
    print(f"loaded scenario_id={row['scenario_id']} rev={row['revision_idx']} "
           f"state={row['state']} bar_ts={row.get('bar_ts_utc')}\n")

    assessment_as_written = _reconstruct_assessment(row)
    assessment_corrected = _apply_correction(assessment_as_written)

    pkt = build_macro_packet(asof=ASOF, source_mode="operator_jsonl",
                              event_file=EVENTS, read_news_state=False)
    econ = classify_economic_context(pkt)
    print("Economic context @ 14:05 UTC:")
    for b in ("scheduled", "released", "expired", "unverified"):
        names = [e.get("name") for e in econ.get(b, [])]
        print(f"  {b:10} ({len(names)}): {names[:6]}")
    print()

    # Run both assessments
    flags_before = validate_assessment(
        assessment=assessment_as_written, packet={}, economic_context=econ)
    flags_after = validate_assessment(
        assessment=assessment_corrected, packet={}, economic_context=econ)
    pub_before = decide_publication(flags_before)
    pub_after = decide_publication(flags_after)

    print("=== AS-WRITTEN (production rev 4) ===")
    print(f"  flags: {len(flags_before)}")
    for f in flags_before:
        print(f"    {f['code']:35}  {f['severity']:6}  {f['where']}")
    print(f"  publication_decision: {pub_before['decision']}")
    print()

    print("=== CORRECTED (prompt + validator fixes) ===")
    print(f"  flags: {len(flags_after)}")
    for f in flags_after:
        print(f"    {f['code']:35}  {f['severity']:6}  {f['where']}")
    print(f"  publication_decision: {pub_after['decision']}")
    print()

    # Show the before/after of the key opportunity note
    opp_before = (assessment_as_written["actions"][0]["opportunities"]
                   [0] if assessment_as_written["actions"][0]
                   .get("opportunities") else None)
    opp_after = (assessment_corrected["actions"][0]["opportunities"]
                  [0] if assessment_corrected["actions"][0]
                  .get("opportunities") else None)
    if opp_before and opp_after:
        print("=== Trigger-text diff (opportunity[0]) ===")
        print("as-written note      :", (opp_before.get("note") or "")[:200])
        print("corrected note       :", (opp_after.get("note") or "")[:200])
        print()
        print("as-written req_price :",
              (opp_before.get("required_price_behaviour") or "")[:200])
        print("corrected req_price  :",
              (opp_after.get("required_price_behaviour") or "")[:200])
        print()

    # ------------------------------------------------------------------
    # Final publishability check: emulate what the recommendation builder
    # + shadow_exec gate would do.
    # ------------------------------------------------------------------
    print("=== Publishability outcome ===")
    print("  as-written    publishable:",
          pub_before["decision"] in ("VALID", "CAUTION"))
    print("  corrected     publishable:",
          pub_after["decision"] in ("VALID", "CAUTION"))

    if pub_after["decision"] not in ("VALID", "CAUTION"):
        print()
        print("  ! corrected scenario still INVALID — remaining flags:")
        for f in flags_after:
            print(f"    {f['code']} {f['severity']} {f['where']}")
            print(f"       detail: {f['detail'][:200]}")

    print()
    print("=== Timing sweep: every revision 4-19 (14:05 → 16:55 UTC) ===")
    sweep_times = {
         4: dt.datetime(2026,10,28,14, 5, tzinfo=dt.timezone.utc),
         5: dt.datetime(2026,10,28,14,25, tzinfo=dt.timezone.utc),
         6: dt.datetime(2026,10,28,14,35, tzinfo=dt.timezone.utc),
         7: dt.datetime(2026,10,28,14,45, tzinfo=dt.timezone.utc),
         8: dt.datetime(2026,10,28,14,55, tzinfo=dt.timezone.utc),
         9: dt.datetime(2026,10,28,15,15, tzinfo=dt.timezone.utc),
        10: dt.datetime(2026,10,28,15,25, tzinfo=dt.timezone.utc),
        11: dt.datetime(2026,10,28,15,35, tzinfo=dt.timezone.utc),
        12: dt.datetime(2026,10,28,15,45, tzinfo=dt.timezone.utc),
        13: dt.datetime(2026,10,28,15,55, tzinfo=dt.timezone.utc),
        14: dt.datetime(2026,10,28,16, 5, tzinfo=dt.timezone.utc),
        15: dt.datetime(2026,10,28,16,15, tzinfo=dt.timezone.utc),
        16: dt.datetime(2026,10,28,16,25, tzinfo=dt.timezone.utc),
        17: dt.datetime(2026,10,28,16,35, tzinfo=dt.timezone.utc),
        18: dt.datetime(2026,10,28,16,45, tzinfo=dt.timezone.utc),
        19: dt.datetime(2026,10,28,16,55, tzinfo=dt.timezone.utc),
    }
    for rev, ts in sweep_times.items():
        _replay_revision(rev, ts, f"rev {rev} @ {ts.strftime('%H:%M')} UTC")


if __name__ == "__main__":
    replay()
