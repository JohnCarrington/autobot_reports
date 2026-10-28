"""Phase 5 Stage C — classify the 119 non-broker-event exits.

Phase 4's simulator_replay deliberately deferred 119 of the 228
FULLY_RECONCILED trades because their IG close level did not match the
*initial* SL or TP within 0.3 display units.  That boundary is correct
for a bare simulator replay, but it hides what actually caused each
close.

This stage pulls together:

    * IG activity close level (authoritative fill)
    * final (amended) IG SL / TP levels
    * IG close channel (SYSTEM / PUBLIC_WEB_API / WEB / MOBILE)
    * unified_trades.jsonl close_reason string (production label)
    * standalone BB Bounce / EMA Pullback CSV outcome labels where
      available

and produces a per-trade classification plus reproducibility assessment:

    STRATEGY_DIRECTED_CLOSE
    TRADE_MANAGER_SL_AMENDED_HIT       (SL moved by profit-mgmt, then hit)
    TRADE_MANAGER_TP_AMENDED_HIT
    TRADE_MANAGER_BE_FLAT_EXIT         (BE flat-out at scale-out boundary)
    MANUAL_UI_CLOSE
    EXTERNAL_PROCESS_CLOSE             (sibling-host-looking, no provenance)
    BROKER_CLOSE_RECLASSIFIED_BY_AMEND (SL/TP hit against amended level)
    UNKNOWN_INSUFFICIENT_EVIDENCE

Writes `data/stageC_non_broker_exits_classification.json`.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"

LEDGER = json.load(open(DATA / "trade_ledger.json"))
RECON = json.load(open(DATA / "execution_reconciliation.json"))

unified = []
with open(DATA / "unified_trades_snapshot.jsonl") as fh:
    for line in fh:
        if not line.strip():
            continue
        unified.append(json.loads(line))

closes_by_did: dict[str, dict] = {}
for r in unified:
    if r.get("event") == "CLOSE" and r.get("deal_id"):
        closes_by_did[r["deal_id"]] = r

TOL_PTS = 0.3  # same tolerance the production trade_manager uses


def _match_level(close_level: float | None, level: float | None) -> bool:
    if close_level is None or level is None:
        return False
    return abs(close_level - level) <= TOL_PTS


def classify(t: dict, exec_row: dict) -> dict:
    """Return a classification dict for one trade."""
    did = t["ig_open_deal_id"]
    close_channels = {c.get("channel") for c in (t.get("ig_closes") or [])}
    close_level = (t.get("ig_closes") or [{}])[0].get("level")
    close_level_f = float(close_level) if close_level is not None else None

    direction = str(t.get("ig_direction") or "").upper()
    initial_sl = t.get("ig_initial_stop_level")
    initial_tp = t.get("ig_initial_limit_level")
    amends = t.get("ig_amendments") or []
    final_sl = amends[-1].get("stop") if amends else initial_sl
    final_tp = amends[-1].get("limit") if amends else initial_tp
    final_sl_f = float(final_sl) if final_sl is not None else None
    final_tp_f = float(final_tp) if final_tp is not None else None

    # Unified-log close_reason, if we have it.
    u_close = closes_by_did.get(did)
    u_reason = (u_close or {}).get("close_reason")

    # --- Classify ----------------------------------------------------
    # If any amendment moved SL/TP AND the close matches that amended
    # level → broker exit against the ADJUSTED SL/TP.  This is Phase 4's
    # "SL hit after amendment" case.
    if amends and _match_level(close_level_f, final_sl_f):
        return {
            "deal_id": did,
            "classification": "BROKER_CLOSE_RECLASSIFIED_BY_AMEND",
            "sub_class": "SL_AMENDED_HIT",
            "channel": sorted(c or "" for c in close_channels),
            "ig_close_level": close_level_f,
            "ig_final_sl": final_sl_f,
            "ig_initial_sl": initial_sl,
            "ig_initial_tp": initial_tp,
            "n_amendments": len(amends),
            "unified_close_reason": u_reason,
            "reproducible_with_decision_bus": True,
            "notes": "Trade manager amended SL; broker fired against the "
                     "amended level.  Independently reproducible once the "
                     "decision-event bus can replay the amendment chain.",
        }
    if amends and _match_level(close_level_f, final_tp_f):
        return {
            "deal_id": did,
            "classification": "BROKER_CLOSE_RECLASSIFIED_BY_AMEND",
            "sub_class": "TP_AMENDED_HIT",
            "channel": sorted(c or "" for c in close_channels),
            "ig_close_level": close_level_f,
            "ig_final_tp": final_tp_f,
            "ig_initial_tp": initial_tp,
            "n_amendments": len(amends),
            "unified_close_reason": u_reason,
            "reproducible_with_decision_bus": True,
            "notes": "Trade manager amended TP; broker fired against the "
                     "amended level.",
        }

    # PUBLIC_WEB_API = autobot/standalone close REST call.
    if "PUBLIC_WEB_API" in close_channels:
        if u_reason:
            return {
                "deal_id": did,
                "classification": "STRATEGY_DIRECTED_CLOSE",
                "sub_class": _strategy_subclass(u_reason),
                "channel": sorted(c or "" for c in close_channels),
                "ig_close_level": close_level_f,
                "unified_close_reason": u_reason,
                "reproducible_with_decision_bus": True,
                "notes": "Trade-manager / strategy-driven close via "
                         "/positions/otc.  The decision rule is in "
                         "trade_manager.py or the owning strategy.",
            }
        return {
            "deal_id": did,
            "classification": "STRATEGY_DIRECTED_CLOSE",
            "sub_class": "NO_UNIFIED_PROVENANCE",
            "channel": sorted(c or "" for c in close_channels),
            "ig_close_level": close_level_f,
            "unified_close_reason": None,
            "reproducible_with_decision_bus": False,
            "notes": "PUBLIC_WEB_API close but no unified-log row.  Likely "
                     "a sibling host or pre-unified-log coverage.",
        }

    # WEB channel = manual UI intervention from a browser.
    if "WEB" in close_channels:
        return {
            "deal_id": did,
            "classification": "MANUAL_UI_CLOSE",
            "sub_class": "WEB",
            "channel": sorted(c or "" for c in close_channels),
            "ig_close_level": close_level_f,
            "unified_close_reason": u_reason,
            "reproducible_with_decision_bus": False,
            "notes": "Human closed the position via the IG web UI.  Not "
                     "reproducible from recorded state.",
        }
    if "MOBILE" in close_channels:
        return {
            "deal_id": did,
            "classification": "MANUAL_UI_CLOSE",
            "sub_class": "MOBILE",
            "channel": sorted(c or "" for c in close_channels),
            "ig_close_level": close_level_f,
            "unified_close_reason": u_reason,
            "reproducible_with_decision_bus": False,
            "notes": "Human closed the position via the IG mobile app.  "
                     "Not reproducible.",
        }

    # SYSTEM channel but close didn't match SL/TP — IG's own management
    # (e.g. margin-driven liquidation, FX session rollover, out-of-hours).
    if "SYSTEM" in close_channels:
        return {
            "deal_id": did,
            "classification": "EXTERNAL_PROCESS_CLOSE",
            "sub_class": "SYSTEM_NON_SLTP",
            "channel": sorted(c or "" for c in close_channels),
            "ig_close_level": close_level_f,
            "unified_close_reason": u_reason,
            "reproducible_with_decision_bus": False,
            "notes": "IG system-side close that is not a plain SL/TP hit.  "
                     "Candidate causes: margin close-out, FX cutover, "
                     "corporate-action close.",
        }

    return {
        "deal_id": did,
        "classification": "UNKNOWN_INSUFFICIENT_EVIDENCE",
        "sub_class": "UNKNOWN_CHANNEL",
        "channel": sorted(c or "" for c in close_channels),
        "ig_close_level": close_level_f,
        "unified_close_reason": u_reason,
        "reproducible_with_decision_bus": False,
        "notes": "No recognised close channel.  Unable to attribute.",
    }


def _strategy_subclass(reason: str) -> str:
    if not reason:
        return "UNLABELED"
    r = reason.upper()
    if "QM_BAND_CLOSE_INSIDE" in r:
        return "QM_INSIDE_BAND"
    if "GRIND_SMA_CROSS" in r:
        return "GRIND_SMA_CROSS"
    if "STRUCTURE_EXIT" in r:
        return "STRUCTURE_EXIT"
    if "V3_WARNING_BREAK" in r:
        return "V3_WARNING_BREAK"
    if "V3_STOP" in r:
        return "V3_STOP"
    if "FLOOR_STOP_POST_SCALEOUT" in r:
        return "SCALEOUT_FLOOR"
    if "BE_STOP_POST_SCALEOUT" in r:
        return "SCALEOUT_BE"
    if "AMENDED_SL_HIT" in r:
        return "AMENDED_SL_HIT"
    if "WEEKEND_FLATTEN" in r:
        return "WEEKEND_FLATTEN"
    if "EOD" in r:
        return "EOD"
    if "BOUNCE_ENGINE" in r:
        return "BOUNCE_ENGINE"
    if "IG_RECONCILE" in r:
        return "IG_RECONCILE_FALLBACK"
    if "EXIT_GOVERNING_SWING_BROKEN" in r:
        return "SWING_BROKEN"
    if "EXTERNAL CLOSE" in r:
        return "EXTERNAL_FALLBACK"
    return "OTHER"


def main() -> int:
    # Index exec rows by deal_id.
    exec_by_did = {r["deal_id"]: r for r in RECON["trades"]}

    classifications = []
    for did, t in LEDGER.items():
        if t.get("match_grade") != "FULLY_RECONCILED":
            continue
        # Only process the 119 that Phase 4 deferred (non-SL/TP initial hits).
        er = exec_by_did.get(did, {})
        close_level = (t.get("ig_closes") or [{}])[0].get("level")
        initial_sl = t.get("ig_initial_stop_level")
        initial_tp = t.get("ig_initial_limit_level")
        is_initial_broker = (
            _match_level(float(close_level) if close_level is not None else None,
                         float(initial_sl) if initial_sl is not None else None)
            or
            _match_level(float(close_level) if close_level is not None else None,
                         float(initial_tp) if initial_tp is not None else None)
        )
        if is_initial_broker:
            continue
        classifications.append(classify(t, er))

    summary = {
        "n_non_broker_exits": len(classifications),
        "by_classification": dict(Counter(c["classification"] for c in classifications)),
        "by_sub_class": dict(Counter(f"{c['classification']}/{c['sub_class']}" for c in classifications)),
        "reproducible_count": sum(1 for c in classifications if c.get("reproducible_with_decision_bus")),
        "not_reproducible_count": sum(1 for c in classifications if not c.get("reproducible_with_decision_bus")),
    }
    out = {"summary": summary, "trades": classifications}
    (DATA / "stageC_non_broker_exits_classification.json").write_text(
        json.dumps(out, indent=2, default=str)
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
