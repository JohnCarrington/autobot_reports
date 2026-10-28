"""Build WAIT_RECOMMENDATION_CLASSIFICATION.csv — every V2 shadow
proposal 2026-10-23 → 2026-10-28, classified by exact WAIT cause."""
import csv
import json
import pathlib
import re
from collections import Counter

PROP = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/shadow_proposals.jsonl")

ROWS = []
with PROP.open() as fh:
    for line in fh:
        r = json.loads(line)
        if "2026-10-2" in (r.get("generated_at_utc") or ""):
            ROWS.append(r)


def classify(r):
    """Map (recommendation, readiness, reason) → one of A-K from brief."""
    reco = r.get("recommendation")
    rdy = r.get("readiness") or ""
    reason = r.get("reason") or ""
    pub_decision = (r.get("publication") or {}).get("decision") or ""
    flags = (r.get("publication") or {}).get("flag_codes") or []

    # BUY/SELL (not WAIT)
    if reco in ("BUY", "SELL"):
        return "PUBLISHED", f"recommendation={reco} readiness={rdy}"

    # Hard classes
    if "scenario state is INVALIDATED" in reason:
        return "H", "primary scenario state INVALIDATED"
    if "scenario state is COMPLETED" in reason:
        return "A", "scenario COMPLETED — no opportunity"
    if "market-data stale" in reason:
        return "G", "stale market data"
    if "ENTRY EXPIRED" in reason:
        return "B", "trigger-expiry gate"

    # publication_decision=INVALID → news/quality block
    if pub_decision == "INVALID":
        if "UNVERIFIED_EVENT_AS_CATALYST" in flags:
            return "E", "news-validation UNVERIFIED_EVENT_AS_CATALYST"
        if "FABRICATED_BAR_COUNT_RULE" in flags:
            return "I", "AI-generated fabricated bar-count rule"
        if "PREMATURE_CONFIRMATION" in flags:
            return "I", "AI premature confirmation"
        if "WRONG_SIDED_STOP" in flags or "CONTRADICTORY_TARGET" in flags:
            return "I", "AI geometry defect (quality gate)"
        return "I", f"other HIGH flag: {','.join(sorted(set(flags)))[:50]}"

    # publication_decision=UNVALIDATED
    if pub_decision == "UNVALIDATED":
        return "A", "historical scenario without validated publication"

    # publication_decision=CAUTION  → CAUTION→WAIT trap
    if pub_decision == "CAUTION":
        return "J", "scenario is CAUTION — publishable but recommendation=WAIT by design (recommendation builder treats CAUTION as WAIT)"

    # publication_decision=VALID but still WAIT: dig into readiness
    if rdy == "INCOMPLETE":
        if "geometry violated" in reason:
            return "I", "AI geometry defect: stop/entry/target wrong-sided"
        if "unresolved fields" in reason:
            missing = re.search(r"unresolved fields: ([^;]+)", reason)
            if missing:
                return "I", f"AI missing fields: {missing.group(1)}"
            return "I", "AI missing fields"
        if "invalidated pre-entry" in reason:
            return "A", "price already past stop by publish time"
        return "I", f"INCOMPLETE: {reason[:60]}"

    if rdy == "STALE":
        return "G", "stale market data"

    if rdy == "SUPPRESSED":
        return "E", f"suppressed; flags={','.join(sorted(set(flags)))[:50]}"

    if rdy == "HISTORICAL":
        return "A", "historical scenario revision"

    if rdy == "CONDITIONAL":
        return "J", "CAUTION readiness"

    if rdy == "EXPIRED_ENTRY":
        return "B", "temporal validity expired"

    if "no directional opportunity" in reason:
        return "A", "no directional opp in latest revision"

    return "K", f"unmatched: readiness={rdy} reason={reason[:60]}"


out_rows = []
for r in ROWS:
    cls, detail = classify(r)
    out_rows.append({
        "generated_at_utc": r.get("generated_at_utc"),
        "scenario_id": r.get("scenario_id"),
        "revision_idx": r.get("revision_idx"),
        "direction": r.get("direction"),
        "entry": (r.get("entry") or {}).get("price"),
        "stop": (r.get("stop") or {}).get("price"),
        "target": (r.get("target") or {}).get("price"),
        "recommendation": r.get("recommendation"),
        "readiness": r.get("readiness"),
        "publication_decision": (r.get("publication") or {}).get("decision"),
        "flag_codes": ",".join(sorted(set((r.get("publication") or {}).get("flag_codes") or []))),
        "wait_class": cls,
        "wait_detail": detail,
    })

out_path = pathlib.Path("/tmp/WAIT_RECOMMENDATION_CLASSIFICATION.csv")
with out_path.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
    w.writeheader()
    for r in out_rows:
        w.writerow(r)
print(f"Wrote {out_path} ({len(out_rows)} rows)")

# Summary
cls_counter = Counter(r["wait_class"] for r in out_rows)
print()
print("Classification distribution (A-K):")
labels = {
    "PUBLISHED": "BUY/SELL published (not WAIT)",
    "A": "A — No valid opportunity identified",
    "B": "B — Valid opp but trigger not met / expired",
    "C": "C — Trigger met but observer failed to recognise",
    "D": "D — Trigger met but AI publication delayed",
    "E": "E — News-validation suppression",
    "F": "F — NMS direction veto (not seen in V2 pipeline)",
    "G": "G — Stale market data",
    "H": "H — Unresolved WATCH/rejection state",
    "I": "I — AI generation failure/defect",
    "J": "J — Dashboard/display: CAUTION→WAIT",
    "K": "K — Other (unmatched)",
}
for cls, n in sorted(cls_counter.items(), key=lambda x: -x[1]):
    print(f"  {cls}  {labels.get(cls,'?'):60} {n:>4}")

# Detail counter for class I (AI defects)
print()
i_rows = [r for r in out_rows if r["wait_class"] == "I"]
i_detail = Counter(r["wait_detail"] for r in i_rows)
print("Class I breakdown:")
for d, n in i_detail.most_common(10):
    print(f"  {n:>4}  {d}")
