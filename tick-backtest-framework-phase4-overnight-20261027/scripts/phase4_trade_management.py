"""Phase 4 — dynamic trade-management evidence.

For each FULLY_RECONCILED trade, catalogue the broker-observed management
events:

  * number of SL amendments
  * number of TP amendments
  * trailing-stop adjustments
  * partial closures
  * break-even moves (SL amendment to open level ±2 pips)

Separates broker-event reconciliation (observable, replayable through the
sim) from independent strategy-decision replay (requires full event bus,
NOT performed in this phase).

Writes `data/trade_management_summary.json`.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path


DATA = Path("/home/autobot/autobot_reports_clone/tick-backtest-framework-phase4-overnight-20261027/data")


def _f(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def classify_amendment(prev_sl: float | None, new_sl: float | None,
                       open_level: float | None, direction: str) -> str:
    if prev_sl is None or new_sl is None or open_level is None:
        return "UNKNOWN"
    delta = new_sl - prev_sl
    # Breakeven: new SL within 2 pips of open level (toward favourable side)
    if abs(new_sl - open_level) <= 2.0:
        return "BREAKEVEN"
    # Trailing: SL moved in favourable direction (BUY → up, SELL → down)
    if direction == "BUY" and delta > 0:
        return "TRAIL_UP"
    if direction == "SELL" and delta < 0:
        return "TRAIL_DOWN"
    # Widen (defensive move backward): not usually seen
    if direction == "BUY" and delta < 0:
        return "WIDEN"
    if direction == "SELL" and delta > 0:
        return "WIDEN"
    return "FLAT"


def main() -> int:
    ledger = json.load(open(DATA / "trade_ledger.json"))
    out = []
    for did, t in ledger.items():
        if t.get("match_grade") != "FULLY_RECONCILED":
            continue
        direction = t.get("ig_direction") or ""
        open_level = _f(t.get("ig_open_level"))
        initial_sl = _f(t.get("ig_initial_stop_level"))
        initial_tp = _f(t.get("ig_initial_limit_level"))
        amendments = t.get("ig_amendments") or []
        n_amends = len(amendments)
        n_partials = sum(1 for c in (t.get("ig_closes") or [])
                          if c.get("actionType") == "POSITION_PARTIALLY_CLOSED")

        # Classify each amendment
        prev_sl = initial_sl
        prev_tp = initial_tp
        amend_classes: list[str] = []
        for a in amendments:
            new_sl = _f(a.get("stop"))
            new_tp = _f(a.get("limit"))
            if new_sl is not None and new_sl != prev_sl:
                amend_classes.append(classify_amendment(prev_sl, new_sl, open_level, direction))
                prev_sl = new_sl
            if new_tp is not None and new_tp != prev_tp:
                amend_classes.append("TP_AMEND")
                prev_tp = new_tp

        out.append({
            "deal_id": did,
            "strategy_family": t.get("strategy_family"),
            "source_system": t.get("source_system"),
            "direction": direction,
            "n_amendments": n_amends,
            "n_partial_closes": n_partials,
            "amendment_classifications": amend_classes,
        })

    def _bucketize(xs: list[int]) -> dict[str, int]:
        buckets = {"0": 0, "1": 0, "2-5": 0, "6-10": 0, "11+": 0}
        for x in xs:
            if x == 0: buckets["0"] += 1
            elif x == 1: buckets["1"] += 1
            elif 2 <= x <= 5: buckets["2-5"] += 1
            elif 6 <= x <= 10: buckets["6-10"] += 1
            else: buckets["11+"] += 1
        return buckets

    by_strat: dict[str, list[dict]] = {}
    for r in out:
        by_strat.setdefault(r["strategy_family"], []).append(r)

    per_strat = {}
    for fam, rows in by_strat.items():
        all_amends: list[str] = []
        for r in rows:
            all_amends.extend(r["amendment_classifications"])
        per_strat[fam] = {
            "n_trades": len(rows),
            "amendments_distribution": _bucketize([r["n_amendments"] for r in rows]),
            "partial_closes_distribution": _bucketize([r["n_partial_closes"] for r in rows]),
            "amendment_classifications": dict(Counter(all_amends)),
        }

    summary = {
        "n_fully_reconciled": len(out),
        "per_strategy": per_strat,
        "overall_amendments": _bucketize([r["n_amendments"] for r in out]),
        "overall_partials": _bucketize([r["n_partial_closes"] for r in out]),
        "overall_amend_classes": dict(Counter(
            c for r in out for c in r["amendment_classifications"])),
        "trades": out,
    }
    (DATA / "trade_management_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    # Print condensed
    cond = dict(summary)
    cond.pop("trades")
    print(json.dumps(cond, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
