"""Replay 2026-10-29 scenario revisions through 4 validator configurations.

A. Production baseline (unchanged)                 — pre-C4 both validators
B. Event-name fix only                             — pre-C4 confidence, post-C4 event-name
C. Confidence-percent fix only                     — post-C4 confidence prompt (validator unchanged), pre-C4 event-name
D. Both C4 corrections                             — both fixes together

The confidence-percent "fix" is a PROMPT-level change (the reasoner is
instructed not to emit percentages). The validator rule is unchanged.
For historical replay against already-generated rows, config B and D are
NOT distinguishable from config A and C respectively UNLESS we also
simulate what the reasoner would have emitted had it followed the new
rule. We approximate by stripping percentage sentences from the stored
assessment text before re-validating.

Output CSV: GBPUSD_20261029_VALIDATION_REPLAY.csv
"""
from __future__ import annotations

import csv
import json
import re
import sys
import importlib
import pathlib

STAGING = pathlib.Path(__file__).resolve().parent.parent / "staging" / "agent"
PRODUCTION = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")

JOURNAL = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl")
QFLAGS  = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenario_quality_flags.jsonl")
CANDLES = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD/2026-10-29.csv")
OUT_CSV = pathlib.Path(__file__).resolve().parent.parent / "replay" / "GBPUSD_20261029_VALIDATION_REPLAY.csv"


def _reset_mod(name):
    if name in sys.modules:
        del sys.modules[name]


def _load_validator(path: pathlib.Path):
    """Import scenario_quality from `path`, isolated."""
    for n in ("scenario_quality",):
        _reset_mod(n)
    # Replace sys.path head
    while sys.path and sys.path[0].endswith("/agent"):
        sys.path.pop(0)
    sys.path.insert(0, str(path))
    return importlib.import_module("scenario_quality")


def _strip_percentages(assessment: dict) -> dict:
    """Simulate the AI following the C4 prompt directive — remove
    sentences that contain `N% probability|confidence|likelihood|
    conviction|certainty` wording."""
    import copy
    pat = re.compile(
        r"[^.;]*?\b\d{1,3}\s?%\s*(confidence|probability|likelihood|"
        r"conviction|certainty)\b[^.;]*[.;]?",
        flags=re.IGNORECASE,
    )
    pat2 = re.compile(
        r"[^.;]*?(confidence|probability|likelihood|conviction|certainty)"
        r"\s+(?:of\s+)?(?:approximately\s+)?\d{1,3}\s?%[^.;]*[.;]?",
        flags=re.IGNORECASE,
    )

    def _clean(x):
        if isinstance(x, str):
            # Strip whole sentences containing the pattern.
            y = pat.sub("", x)
            y = pat2.sub("", y)
            return y
        if isinstance(x, dict):
            return {k: _clean(v) for k, v in x.items()}
        if isinstance(x, list):
            return [_clean(v) for v in x]
        return x

    return _clean(copy.deepcopy(assessment))


def _validate_once(validator, row: dict, strip_pct: bool) -> list[dict]:
    """Return the publication-decision + flag codes we would have emitted
    for `row` under the given validator and (optional) pct-strip."""
    # The sweeper assembles an `assessment` dict matching the shape the
    # validators expect. Build it from the row.
    opp_direction = (row.get("primary_direction") or "SELL").upper()
    assessment = {
        "current_interpretation": row.get("current_interpretation", ""),
        "change_from_previous": row.get("change_from_previous", ""),
        "narrative": row.get("narrative", ""),
        "initial_interpretation": row.get("initial_interpretation", ""),
        "evidence": row.get("evidence", {}),
        "actions": [{
            "kind": row.get("state", "WATCHING"),
            "change_from_previous": row.get("change_from_previous", ""),
            "current_interpretation": row.get("current_interpretation", ""),
            "macro_context_note": "",
            "anticipated_sequence": row.get("anticipated_sequence", []),
            "opportunities": row.get("opportunities", []),
        }],
    }
    tp = row.get("trade_proposal") or {}
    opps = assessment["actions"][0]["opportunities"]
    # Ensure the primary opp carries category=A (as the live rows do)
    # and the structured trade_proposal.
    if opps and isinstance(opps[0], dict):
        opps[0].setdefault("category", "A")
        opps[0].setdefault("direction", opp_direction)
        if tp:
            opps[0].setdefault("trade_proposal", tp)
            opps[0].setdefault("required_price_behaviour",
                                 opps[0].get("required_price_behaviour") or
                                 tp.get("entry_trigger", ""))
    if strip_pct:
        assessment = _strip_percentages(assessment)

    econ = row.get("economic_context") or {}

    flags = []
    validator._validate_confidence_claims(assessment, flags)
    validator._validate_opportunity_category(assessment, econ, flags)
    # Also mimic any other validator checks that fire on this payload.
    # (We only check these two — the others are not affected by C4.)
    pub = validator.decide_publication([f.to_dict() if hasattr(f, 'to_dict') else f for f in flags])
    return pub, [f.code for f in flags], [f.severity for f in flags]


def main():
    # Load 2026-10-29 rows (excluding the unrelated f5e11547 scenario).
    rows = []
    for line in JOURNAL.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if (r.get("bar_ts_utc") or "").startswith("2026-10-29") and \
           r.get("scenario_id") != "f5e11547c4ce2097":
            rows.append(r)
    rows.sort(key=lambda r: (r.get("bar_ts_utc"), r.get("revision_idx") or 0))

    # Load candles for entry-condition-met check
    candles = {}
    for ln in CANDLES.read_text().splitlines()[1:]:
        ts, o, h, l, c = ln.split(",")
        candles[ts[:16]] = (float(o), float(h), float(l), float(c))

    # Four validator configurations
    v_prod = _load_validator(PRODUCTION)
    v_c4   = _load_validator(STAGING)

    out_rows = []
    for r in rows:
        bar_ts = r.get("bar_ts_utc")
        tp = r.get("trade_proposal") or {}
        entry = tp.get("entry_price")
        stop = tp.get("stop_price")
        target = tp.get("target_price")
        direction = (tp.get("direction") or "").upper()

        # A: production baseline (no change)
        pubA, codesA, _ = _validate_once(v_prod, r, strip_pct=False)
        # B: event-name fix only
        pubB, codesB, _ = _validate_once(v_c4, r, strip_pct=False)
        # C: confidence-percent fix only (pct stripped at generation,
        # pre-C4 validator)
        pubC, codesC, _ = _validate_once(v_prod, r, strip_pct=True)
        # D: both
        pubD, codesD, _ = _validate_once(v_c4, r, strip_pct=True)

        # Was entry trigger subsequently satisfied? For SELL entry
        # 13300 we need a close <= 13300 within the proposal's validity
        # window (next 30 min per the 09:40 rev; we treat the whole
        # morning as the window).
        trigger_met = "NO"
        if entry is not None and direction == "SELL":
            # Need 2 consecutive closes <= entry
            closes = sorted(((k, v[3]) for k, v in candles.items()
                             if k >= bar_ts[:16]))
            prev_below = False
            for ts, c in closes:
                is_below = c <= entry
                if is_below and prev_below:
                    trigger_met = f"YES (at {ts}Z after prev)"
                    break
                prev_below = is_below
        technically_complete = all(v is not None for v in (entry, stop, target))

        out_rows.append({
            "scenario_id": r.get("scenario_id"),
            "revision_idx": r.get("revision_idx"),
            "bar_ts_utc": bar_ts,
            "state": r.get("state"),
            "direction": direction,
            "entry_price": entry,
            "stop_price": stop,
            "target_price": target,
            "technically_complete": technically_complete,
            "entry_trigger_met_subsequently": trigger_met,
            "A_prod_flag_codes": ";".join(codesA),
            "A_prod_decision": pubA.get("decision", ""),
            "A_prod_recommendation": "WAIT" if pubA.get("decision") == "INVALID" else ("CONDITIONAL/CAUTION" if pubA.get("decision") == "CAUTION" else "READY"),
            "B_event_fix_only_flag_codes": ";".join(codesB),
            "B_event_fix_only_decision": pubB.get("decision", ""),
            "B_event_fix_only_recommendation": "WAIT" if pubB.get("decision") == "INVALID" else ("CONDITIONAL/CAUTION" if pubB.get("decision") == "CAUTION" else "READY"),
            "C_conf_fix_only_flag_codes": ";".join(codesC),
            "C_conf_fix_only_decision": pubC.get("decision", ""),
            "C_conf_fix_only_recommendation": "WAIT" if pubC.get("decision") == "INVALID" else ("CONDITIONAL/CAUTION" if pubC.get("decision") == "CAUTION" else "READY"),
            "D_both_fixes_flag_codes": ";".join(codesD),
            "D_both_fixes_decision": pubD.get("decision", ""),
            "D_both_fixes_recommendation": "WAIT" if pubD.get("decision") == "INVALID" else ("CONDITIONAL/CAUTION" if pubD.get("decision") == "CAUTION" else "READY"),
        })

    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for row in out_rows:
            w.writerow(row)

    # Summary
    print(f"Wrote {len(out_rows)} rows to {OUT_CSV}")

    from collections import Counter
    for label in ("A_prod", "B_event_fix_only", "C_conf_fix_only", "D_both_fixes"):
        c = Counter(r[f"{label}_decision"] for r in out_rows)
        print(f"{label}: {dict(c)}")

    # Count unique scenarios
    unique_scen = set(r["scenario_id"] for r in out_rows)
    print(f"Distinct scenarios: {len(unique_scen)}")
    print(f"Distinct scenarios where D recovers to CAUTION: "
          f"{len(set(r['scenario_id'] for r in out_rows if r['D_both_fixes_decision'] == 'CAUTION'))}")

    # How many D rows have entry trigger met?
    d_cautions_trigger_met = [r for r in out_rows
                                if r["D_both_fixes_decision"] == "CAUTION"
                                and r["entry_trigger_met_subsequently"].startswith("YES")]
    print(f"D rows that are CAUTION AND entry trigger met: {len(d_cautions_trigger_met)}")


if __name__ == "__main__":
    main()
