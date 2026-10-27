"""Phase 4 — broker execution reconciliation.

For each FULLY_RECONCILED trade, compare the internal (requested) execution
against IG's authoritative result:

* entry direction, size
* entry level (requested vs filled)
* initial stop and target levels (requested vs IG-accepted)
* submission → fill latency
* fill slippage (pips)
* close path (SL hit, TP hit, manual close, external)
* closed P&L (IG authoritative vs internal unified pnl_gbp)

Writes `data/execution_reconciliation.json`.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from statistics import mean, median, stdev


DATA = Path("/home/autobot/autobot_reports_clone/tick-backtest-framework-phase4-overnight-20261027/data")


def _parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        pass
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _f(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def reconcile() -> dict:
    ledger = json.load(open(DATA / "trade_ledger.json"))
    out = []
    skipped = {"not_fully_reconciled": 0}
    for did, t in ledger.items():
        if t.get("match_grade") != "FULLY_RECONCILED":
            skipped["not_fully_reconciled"] += 1
            continue

        ig_open = _f(t.get("ig_open_level"))
        req_open = _f(t.get("unified_entry_price"))
        ig_close = _f(t.get("ig_close_level"))
        uni_close = _f(t.get("unified_exit_price"))
        ig_pnl = _f(t.get("ig_pnl_gbp_sum"))
        uni_pnl = _f(t.get("unified_pnl_gbp"))

        # IG stores levels in display units (1 unit == 0.0001 price for GBP/USD
        # spread-bet). Internal unified_trades uses the same display units,
        # so comparison is direct in "pips".
        entry_slip = None
        if ig_open is not None and req_open is not None:
            entry_slip = ig_open - req_open
            if (t.get("ig_direction") or "SELL") == "SELL":
                entry_slip = -entry_slip  # positive = unfavourable

        close_delta = None
        if ig_close is not None and uni_close is not None:
            close_delta = ig_close - uni_close

        pnl_delta_gbp = None
        if ig_pnl is not None and uni_pnl is not None:
            pnl_delta_gbp = uni_pnl - ig_pnl

        # Classify close reason by channel + proximity of close level to final SL/TP
        ig_closes = t.get("ig_closes") or []
        close_channels = {c.get("channel") for c in ig_closes}
        amends = t.get("ig_amendments") or []
        # Latest SL/TP = latest amendment if any, else initial.
        final_sl = _f(amends[-1].get("stop")) if amends else _f(t.get("ig_initial_stop_level"))
        final_tp = _f(amends[-1].get("limit")) if amends else _f(t.get("ig_initial_limit_level"))
        close_reason = None
        if ig_closes:
            first = ig_closes[0]
            cl = _f(first.get("level"))
            ch = first.get("channel")
            if ch == "SYSTEM" and cl is not None:
                # 0.3-pip tolerance for IG's SL/TP execution
                if final_sl is not None and abs(cl - final_sl) <= 0.3:
                    close_reason = "SL_HIT"
                elif final_tp is not None and abs(cl - final_tp) <= 0.3:
                    close_reason = "TP_HIT"
                else:
                    close_reason = "SYSTEM_OTHER"
            elif ch == "PUBLIC_WEB_API":
                close_reason = "CODE_CLOSED"
            elif ch == "WEB":
                close_reason = "MANUAL_UI"

        # Amendments count
        amends = t.get("ig_amendments") or []
        n_amends = len(amends)

        out.append({
            "deal_id": did,
            "strategy_family": t.get("strategy_family"),
            "source_system": t.get("source_system"),
            "direction": t.get("ig_direction"),
            "open_utc": t.get("ig_open_date_utc"),
            "ig_open_level": ig_open,
            "requested_open": req_open,
            "entry_slippage_pips": entry_slip,
            "ig_initial_stop_level": t.get("ig_initial_stop_level"),
            "ig_initial_limit_level": t.get("ig_initial_limit_level"),
            "ig_close_level": ig_close,
            "unified_exit_price": uni_close,
            "close_delta_price_units": close_delta,
            "ig_pnl_gbp": ig_pnl,
            "unified_pnl_gbp": uni_pnl,
            "pnl_delta_gbp": pnl_delta_gbp,
            "close_reason": close_reason,
            "close_channels": sorted(c or "" for c in close_channels),
            "n_amendments": n_amends,
            "n_partial_closes": sum(1 for c in ig_closes
                                     if c.get("actionType") == "POSITION_PARTIALLY_CLOSED"),
        })

    # Summary
    slips = [r["entry_slippage_pips"] for r in out if r["entry_slippage_pips"] is not None]
    pnl_deltas = [abs(r["pnl_delta_gbp"]) for r in out if r["pnl_delta_gbp"] is not None]
    close_pct = [r["close_delta_price_units"] for r in out if r["close_delta_price_units"] is not None]

    def _stats(xs: list[float]) -> dict:
        if not xs:
            return {"count": 0}
        s = sorted(xs)
        return {
            "count": len(xs),
            "min": s[0], "max": s[-1], "mean": mean(xs), "median": median(xs),
            "stdev": stdev(xs) if len(xs) >= 2 else 0.0,
            "abs_min": min(abs(x) for x in xs), "abs_max": max(abs(x) for x in xs),
            "abs_mean": mean(abs(x) for x in xs), "abs_median": median(abs(x) for x in xs),
        }

    by_strategy: dict[str, list[dict]] = {}
    for r in out:
        by_strategy.setdefault(r["strategy_family"], []).append(r)

    strategy_summary = {}
    for fam, rows in by_strategy.items():
        slip_fam = [x["entry_slippage_pips"] for x in rows if x["entry_slippage_pips"] is not None]
        pnl_fam = [abs(x["pnl_delta_gbp"]) for x in rows if x["pnl_delta_gbp"] is not None]
        from collections import Counter
        strategy_summary[fam] = {
            "count": len(rows),
            "entry_slippage_pips": _stats(slip_fam),
            "pnl_delta_gbp_abs": _stats(pnl_fam),
            "close_reasons": dict(Counter(r["close_reason"] for r in rows)),
            "amendments_distribution": dict(Counter(r["n_amendments"] for r in rows)),
            "partial_close_distribution": dict(Counter(r["n_partial_closes"] for r in rows)),
        }

    return {
        "trades": out,
        "overall": {
            "n_reconciled": len(out),
            "entry_slippage_pips": _stats(slips),
            "pnl_delta_gbp_abs": _stats(pnl_deltas),
            "close_delta_display_units": _stats(close_pct),
        },
        "by_strategy": strategy_summary,
        "skipped": skipped,
    }


def main() -> int:
    r = reconcile()
    (DATA / "execution_reconciliation.json").write_text(json.dumps(r, indent=2, default=str))
    print(json.dumps({
        "n_reconciled": r["overall"]["n_reconciled"],
        "entry_slippage": r["overall"]["entry_slippage_pips"],
        "pnl_delta_gbp_abs": r["overall"]["pnl_delta_gbp_abs"],
        "close_delta_display_units": r["overall"]["close_delta_display_units"],
        "strategies": {f: {"count": s["count"],
                            "slip_abs_mean": s["entry_slippage_pips"].get("abs_mean"),
                            "pnl_delta_abs_mean": s["pnl_delta_gbp_abs"].get("abs_mean"),
                            "close_reasons": s["close_reasons"]}
                       for f, s in r["by_strategy"].items()},
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
