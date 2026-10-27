"""Phase 4 — simulator replay reconciliation.

For every FULLY_RECONCILED trade whose close is SL_HIT or TP_HIT (deterministic
broker-driven exits), replay a synthetic quote sequence through the Phase 2
BrokerSimulator and verify:

  * The simulator fills the market entry at the IG open level.
  * The simulator exits via SL or TP at the correct level.
  * The simulator-reported pnl_pips agrees with IG's authoritative close level
    (converted to pips).

For CODE_CLOSED, MANUAL_UI, SYSTEM_OTHER (strategy / external closes), the
simulator cannot replicate the decision without the full strategy-event
sequence — those are deliberately NOT asserted here, and are reported as
NOT_REPLAYED. This is the Phase 4 scope boundary: broker-event parity vs
strategy-decision parity.

The script does NOT touch production code or logs.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path("/home/autobot/autobot_reports_clone/tick-backtest-framework-phase4-overnight-20261027")
sys.path.insert(0, str(ROOT))

from sim.broker import BrokerSimulator  # noqa: E402
from sim.types import Direction, OrderRequest, OrderStatus, PIP  # noqa: E402


DATA = ROOT / "data"


def _parse_ig_ts(s: str) -> int:
    """IG dates are either `YYYY-MM-DDTHH:MM:SS` (activity) or
    `YYYY-MM-DDTHH:MM:SS.ffffff+00:00` (unified). Return nanoseconds UTC."""
    if not s:
        return 0
    if "+" in s or s.endswith("Z"):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return 0
    else:
        try:
            d = dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        except Exception:
            return 0
    return int(d.timestamp() * 1_000_000_000)


def _to_decimal(ig_level: float | None) -> float | None:
    """IG GBP/USD spread-bet uses display units like 13300 for 1.3300.
    The simulator's PIP = 0.0001 — convert by dividing by 10000."""
    if ig_level is None:
        return None
    return float(ig_level) / 10000.0


def replay_trade(t: dict) -> dict:
    did = t["ig_open_deal_id"]
    direction = t.get("ig_direction")
    if direction not in ("BUY", "SELL"):
        return {"deal_id": did, "status": "SKIP_NO_DIRECTION"}

    ig_open = _to_decimal(t.get("ig_open_level"))
    ig_close = _to_decimal(t.get("ig_close_level"))
    sl = _to_decimal(t.get("ig_initial_stop_level"))
    tp = _to_decimal(t.get("ig_initial_limit_level"))
    if ig_open is None:
        return {"deal_id": did, "status": "SKIP_NO_OPEN"}

    # Build a two-tick quote sequence: tick 0 at open level, tick 1 at close level.
    open_ts = _parse_ig_ts(t.get("ig_open_date_utc", ""))
    close_evt = (t.get("ig_closes") or [None])[0]
    close_ts = _parse_ig_ts((close_evt or {}).get("date", "")) if close_evt else open_ts + 1

    # Half-spread: IG DEMO GBPUSD spread is typically 0.6-1.5 pips. For replay
    # we assume a 1-pip spread centred on the fill level.
    HALF_SPREAD = 0.5 * PIP

    # IG DEMO accepts stops closer than autobot's 12-pip local floor
    # (BB Bounce standalone places 6-11-pip structural stops that IG honours).
    # For broker-event parity against raw IG DEMO we drop the pair-min to 4.0.
    sim = BrokerSimulator(pair="GBPUSD",
                          submission_latency_ns=0,
                          confirmation_latency_ns=0,
                          slippage_pips=0.0,
                          global_min_stop_pips=4.0,
                          global_min_limit_pips=4.0,
                          pair_min_override={"GBPUSD": 4.0})

    direction_enum = Direction.BUY if direction == "BUY" else Direction.SELL
    size_sb = 2.0  # IG DEMO strategy uses size=2 for all; actual values preserved
                   # in ledger but not needed for pips-based parity.
    size_val = abs(float((t.get("ig_tx_rows") or [{}])[0].get("size") or 2.0)) or 2.0

    # Opening quote: bid/ask so a market BUY fills at ig_open.
    # BUY fills at ask → set ask = ig_open; bid = ask - 2*half_spread
    # SELL fills at bid → set bid = ig_open; ask = bid + 2*half_spread
    if direction_enum == Direction.BUY:
        q0_ask = ig_open
        q0_bid = ig_open - 2 * HALF_SPREAD
    else:
        q0_bid = ig_open
        q0_ask = ig_open + 2 * HALF_SPREAD

    # Submit market order with SL/TP
    req = OrderRequest(
        deal_ref=f"PHASE4-{did}", direction=direction_enum,
        size=size_val, order_type="MARKET", submitted_ts_ns=open_ts,
        sl_absolute=sl, tp_absolute=tp,
    )
    try:
        sim.submit(req)
    except Exception as e:
        return {"deal_id": did, "status": "SIM_SUBMIT_ERROR", "err": repr(e)}

    from sim.types import Quote
    sim.on_quote(Quote(ts_utc_ns=open_ts, bid=q0_bid, ask=q0_ask))

    if req.status == OrderStatus.REJECTED:
        return {"deal_id": did, "status": "SIM_REJECTED",
                "reason": (req.rejected_reason.value if req.rejected_reason else None)}

    # Only replay deterministic broker exits (SL_HIT or TP_HIT).
    close_reason = None
    close_level = ig_close
    if close_evt and close_level is not None:
        if sl is not None and abs(close_level - sl) <= 0.3 / 10000.0:
            close_reason = "SL_HIT"
        elif tp is not None and abs(close_level - tp) <= 0.3 / 10000.0:
            close_reason = "TP_HIT"

    if close_reason is None:
        # Not a broker-deterministic exit — we cannot assert parity here.
        pos = sim.open_positions()[0] if sim.open_positions() else None
        return {"deal_id": did, "status": "NOT_REPLAYED_NON_BROKER_EXIT",
                "sim_entry": pos.entry_price if pos else None,
                "ig_open_decimal": ig_open}

    # Second tick: cross the SL (for SL hit) or TP (for TP hit)
    if close_reason == "SL_HIT":
        # BUY SL triggers when bid <= sl. SELL SL triggers when ask >= sl.
        if direction_enum == Direction.BUY:
            q1_bid = sl
            q1_ask = sl + 2 * HALF_SPREAD
        else:
            q1_ask = sl
            q1_bid = sl - 2 * HALF_SPREAD
    else:  # TP_HIT
        if direction_enum == Direction.BUY:
            q1_bid = tp
            q1_ask = tp + 2 * HALF_SPREAD
        else:
            q1_ask = tp
            q1_bid = tp - 2 * HALF_SPREAD

    sim.on_quote(Quote(ts_utc_ns=close_ts, bid=q1_bid, ask=q1_ask))

    pos = next(iter(sim.positions.values()), None)
    if pos is None or pos.is_open:
        return {"deal_id": did, "status": "SIM_DID_NOT_CLOSE",
                "sim_entry": pos.entry_price if pos else None,
                "exit_target_level": close_level}

    # Compare simulator fill levels vs IG
    sim_entry = pos.entry_price
    sim_exit = pos.exit_price
    entry_err_pips = abs(sim_entry - ig_open) / PIP
    exit_err_pips = abs(sim_exit - close_level) / PIP
    sim_pnl_pips = (sim_exit - sim_entry) / PIP * (1 if direction_enum == Direction.BUY else -1)
    ig_pnl_pips = (close_level - ig_open) / PIP * (1 if direction_enum == Direction.BUY else -1)
    pnl_err_pips = abs(sim_pnl_pips - ig_pnl_pips)

    return {
        "deal_id": did,
        "status": "REPLAYED",
        "close_reason": close_reason,
        "entry_err_pips": entry_err_pips,
        "exit_err_pips": exit_err_pips,
        "sim_pnl_pips": sim_pnl_pips,
        "ig_pnl_pips": ig_pnl_pips,
        "pnl_err_pips": pnl_err_pips,
        "sim_exit_reason": pos.exit_reason,
    }


def main() -> int:
    ledger = json.load(open(DATA / "trade_ledger.json"))
    results = []
    for did, t in ledger.items():
        if t.get("match_grade") != "FULLY_RECONCILED":
            continue
        r = replay_trade(t)
        r["strategy_family"] = t.get("strategy_family")
        r["source_system"] = t.get("source_system")
        results.append(r)
    # Summarise
    from collections import Counter
    status_counts = Counter(r["status"] for r in results)
    replayed = [r for r in results if r["status"] == "REPLAYED"]
    def _stats(xs):
        xs = [x for x in xs if x is not None]
        if not xs:
            return {"n": 0}
        xs = sorted(xs)
        return {"n": len(xs), "min": xs[0], "max": xs[-1], "mean": sum(xs)/len(xs),
                "median": xs[len(xs)//2]}
    out = {
        "n_candidates": len(results),
        "status_counts": dict(status_counts),
        "replayed": {
            "n": len(replayed),
            "entry_err_pips": _stats([r["entry_err_pips"] for r in replayed]),
            "exit_err_pips": _stats([r["exit_err_pips"] for r in replayed]),
            "pnl_err_pips": _stats([r["pnl_err_pips"] for r in replayed]),
            "close_reasons": dict(Counter(r["close_reason"] for r in replayed)),
        },
        "trades": results,
    }
    (DATA / "simulator_replay.json").write_text(json.dumps(out, indent=2, default=str))
    # Print condensed summary
    summary = dict(out)
    summary.pop("trades")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
