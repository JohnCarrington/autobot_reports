"""Phase 5 Stage F — reconcile real management decisions.

For every FULLY_RECONCILED trade in the Phase 4 ledger:

    1. Reconstruct the close-time state object from the ledger:
       entry_price, direction, pip_size, final SL/TP distances.
    2. Invoke `TradeManagerAdapter.classify_close_reason` with the
       authoritative IG close level as the `exit_hint`.
    3. Compare the result against the unified-log close_reason.

This exercises the real production classifier logic in isolation
(trade_manager._detect_ig_close_reason) and records three parity
tiers separately:

    DECISION_PARITY     — classifier produces the same label as production
    BROKER_EVENT_PARITY — the broker close level matches final SL/TP
                          within tolerance (as per Phase 4 recon)
    ACCOUNTING_PARITY   — pnl_pips computed off (ig_close - ig_open)
                          matches unified_pnl_pips within tolerance

The three tiers are reported separately: a trade can have broker-event
parity (IG closed deterministically) without decision parity (classifier
disagrees with production's label) without accounting parity (unified
pnl drift from the Phase 4 Stage A defect).

Writes `data/stageF_management_decision_reconciliation.json`.
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from adapters.trade_manager_adapter import TradeManagerAdapter


DATA = HERE / "data"
LEDGER = json.load(open(DATA / "trade_ledger.json"))

unified = []
with open(DATA / "unified_trades_snapshot.jsonl") as fh:
    for line in fh:
        if line.strip():
            unified.append(json.loads(line))

closes_by_did = {
    r["deal_id"]: r for r in unified
    if r.get("event") == "CLOSE" and r.get("deal_id")
}


def _f(x):
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def _reconstruct_state(t: dict) -> dict:
    """Reconstruct the close-time state object the production classifier
    needs."""
    direction = str(t.get("ig_direction") or "").upper()
    ig_open = _f(t.get("ig_open_level"))
    ig_initial_sl = _f(t.get("ig_initial_stop_level"))
    ig_initial_tp = _f(t.get("ig_initial_limit_level"))
    amends = t.get("ig_amendments") or []
    final_sl = _f(amends[-1].get("stop")) if amends else ig_initial_sl
    final_tp = _f(amends[-1].get("limit")) if amends else ig_initial_tp

    # SL/TP distances in points (display units) — classifier uses the
    # same unit as entry_price when pip_size=1.
    sl_pips = None
    tp_pips = None
    if ig_open is not None and final_sl is not None and direction in ("BUY", "SELL"):
        if direction == "BUY":
            sl_pips = round(ig_open - final_sl, 2)
        else:
            sl_pips = round(final_sl - ig_open, 2)
    if ig_open is not None and final_tp is not None and direction in ("BUY", "SELL"):
        if direction == "BUY":
            tp_pips = round(final_tp - ig_open, 2)
        else:
            tp_pips = round(ig_open - final_tp, 2)

    return {
        "entry_price": ig_open,
        "direction": direction,
        "pip_size": 1.0,
        "sl": sl_pips if sl_pips is not None else 0.0,
        "tp": tp_pips if tp_pips is not None else 0.0,
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        adapter = TradeManagerAdapter(scratch_log_dir=Path(td))

        results = []
        for did, t in LEDGER.items():
            if t.get("match_grade") != "FULLY_RECONCILED":
                continue
            state = _reconstruct_state(t)
            close_evt = (t.get("ig_closes") or [None])[0]
            close_level = _f((close_evt or {}).get("level"))
            if state["entry_price"] is None or close_level is None:
                results.append({
                    "deal_id": did, "status": "SKIP_INSUFFICIENT_STATE",
                })
                continue

            # Decision parity: run the real classifier
            try:
                adapter_label = adapter.classify_close_reason(
                    state=state, exit_hint=close_level,
                    pos_key=f"GBPUSD|{t.get('strategy_family') or 'UNK'}",
                )
            except Exception as e:
                adapter_label = f"ERROR:{type(e).__name__}:{e}"

            u = closes_by_did.get(did)
            u_reason = (u or {}).get("close_reason") or ""

            # Broker-event parity: did IG close at final SL/TP?
            ig_initial_sl = _f(t.get("ig_initial_stop_level"))
            ig_initial_tp = _f(t.get("ig_initial_limit_level"))
            amends = t.get("ig_amendments") or []
            final_sl = _f(amends[-1].get("stop")) if amends else ig_initial_sl
            final_tp = _f(amends[-1].get("limit")) if amends else ig_initial_tp
            tol = 0.3
            broker_event = None
            if final_sl is not None and abs(close_level - final_sl) <= tol:
                broker_event = "SL_HIT_AT_FINAL"
            elif final_tp is not None and abs(close_level - final_tp) <= tol:
                broker_event = "TP_HIT_AT_FINAL"

            # Accounting parity: pnl_pips off IG levels
            ig_open = state["entry_price"]
            direction = state["direction"]
            if direction == "BUY":
                ig_pnl_pips = round(close_level - ig_open, 2)
            else:
                ig_pnl_pips = round(ig_open - close_level, 2)
            u_pnl_pips = _f((u or {}).get("pnl_pips"))
            accounting_delta = (
                round(abs(u_pnl_pips - ig_pnl_pips), 2)
                if u_pnl_pips is not None else None
            )

            results.append({
                "deal_id": did,
                "status": "RECONCILED",
                "direction": direction,
                "ig_open": ig_open,
                "ig_close": close_level,
                "final_sl": final_sl,
                "final_tp": final_tp,
                "adapter_classification": adapter_label,
                "unified_close_reason": u_reason,
                "decision_parity": adapter_label == u_reason,
                "broker_event_parity": broker_event,
                "ig_pnl_pips": ig_pnl_pips,
                "unified_pnl_pips": u_pnl_pips,
                "accounting_delta_pips": accounting_delta,
            })

        # ---- Summary ----
        rec = [r for r in results if r["status"] == "RECONCILED"]
        dec_pass = [r for r in rec if r["decision_parity"]]
        bev_pass = [r for r in rec if r["broker_event_parity"] is not None]
        acc = [r["accounting_delta_pips"] for r in rec
               if r.get("accounting_delta_pips") is not None]
        acc_lt1 = sum(1 for x in acc if x < 1.0)

        summary = {
            "n_trades": len(rec),
            "DECISION_PARITY": len(dec_pass),
            "DECISION_PARITY_pct": round(100 * len(dec_pass) / max(1, len(rec)), 1),
            "BROKER_EVENT_PARITY": len(bev_pass),
            "BROKER_EVENT_PARITY_pct": round(100 * len(bev_pass) / max(1, len(rec)), 1),
            "ACCOUNTING_PARITY_lt_1pip": acc_lt1,
            "ACCOUNTING_PARITY_lt_1pip_pct": round(100 * acc_lt1 / max(1, len(acc)), 1),
            "by_adapter_classification": dict(Counter(r["adapter_classification"] for r in rec)),
            "by_production_reason": dict(Counter(r["unified_close_reason"] for r in rec)),
            "disagreements_top": [],
        }
        # List top disagreements
        for r in rec:
            if not r["decision_parity"]:
                summary["disagreements_top"].append({
                    "deal_id": r["deal_id"],
                    "adapter": r["adapter_classification"],
                    "production": r["unified_close_reason"],
                })
        summary["disagreements_top"] = summary["disagreements_top"][:30]

        out = {"summary": summary, "trades": results}
        (DATA / "stageF_management_decision_reconciliation.json").write_text(
            json.dumps(out, indent=2, default=str)
        )
        print(json.dumps({k: v for k, v in summary.items()
                          if k not in ("disagreements_top",)},
                         indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
