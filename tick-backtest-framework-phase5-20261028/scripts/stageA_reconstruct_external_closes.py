"""Phase 5 Stage A — reconstruct the external-close trades.

For every ``close_reason="External close (not initiated by this host)"``
row in `/opt/tradingbot/logs/unified_trades.jsonl`, pull the authoritative
IG open+close level from the Phase 4 broker ledger and compute the delta
the production repair patch MUST close.

Writes `data/stageA_external_close_reconstruction.json`.

NO production code is modified. NO IG mutations. Read-only.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path


# Phase 5 output
HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"

# Phase 4 broker ledger (copied into Phase 5 /data at setup).
LEDGER_PATH = DATA / "trade_ledger.json"

# Production unified_trades.jsonl — read-only. If the path is unavailable
# (e.g. running under isolation / CI) we fall back to any snapshot copied
# into Phase 5 /data.
UNIFIED_PATH_LIVE = Path("/opt/tradingbot/logs/unified_trades.jsonl")
UNIFIED_PATH_SNAPSHOT = DATA / "unified_trades_snapshot.jsonl"


def _load_unified() -> list[dict]:
    path = UNIFIED_PATH_LIVE if UNIFIED_PATH_LIVE.exists() else UNIFIED_PATH_SNAPSHOT
    if not path.exists():
        raise FileNotFoundError(
            f"Neither {UNIFIED_PATH_LIVE} nor {UNIFIED_PATH_SNAPSHOT} is available"
        )
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _f(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def reconstruct() -> dict:
    ledger = json.load(open(LEDGER_PATH))
    unified = _load_unified()

    opens_by_did: dict[str, dict] = {}
    closes_by_did: dict[str, list[dict]] = {}
    for r in unified:
        did = r.get("deal_id")
        if not did:
            continue
        if r.get("event") == "OPEN":
            opens_by_did[did] = r
        elif r.get("event") == "CLOSE":
            closes_by_did.setdefault(did, []).append(r)

    # Candidate population = External-close CLOSE rows.
    reconstruction = []
    diffs_price = []
    diffs_pnl = []

    for did, closes in closes_by_did.items():
        for c in closes:
            if c.get("close_reason") != "External close (not initiated by this host)":
                continue
            o = opens_by_did.get(did)
            l = ledger.get(did)
            if l is None:
                # Trade missing from Phase 4 ledger (e.g. pre-window).
                reconstruction.append({
                    "deal_id": did,
                    "ledger_present": False,
                    "unified_exit_price": c.get("exit_price"),
                    "unified_pnl_gbp": c.get("pnl_gbp"),
                    "price_source": c.get("price_source"),
                })
                continue

            ig_open = _f(l.get("ig_open_level"))
            ig_close = _f(l.get("ig_close_level"))
            ig_pnl_gbp = _f(l.get("ig_pnl_gbp_sum"))
            direction = str(l.get("ig_direction") or "").upper()

            u_entry = _f(o.get("entry_price")) if o else None
            u_exit = _f(c.get("exit_price"))
            u_pnl_pips = _f(c.get("pnl_pips"))
            u_pnl_gbp = _f(c.get("pnl_gbp"))

            # Expected pnl_pips using IG close level + unified entry.
            # Internal prices are POINTS for GBPUSD (e.g., 13310).  pip_size
            # in state is 1.0 for points-based ratio arithmetic.
            expected_pnl_pips = None
            if u_entry is not None and ig_close is not None and direction in ("BUY", "SELL"):
                if direction == "BUY":
                    expected_pnl_pips = round(ig_close - u_entry, 2)
                else:
                    expected_pnl_pips = round(u_entry - ig_close, 2)

            # Direct ledger authority on pips using IG open+close.
            ig_pnl_pips = None
            if ig_open is not None and ig_close is not None and direction in ("BUY", "SELL"):
                if direction == "BUY":
                    ig_pnl_pips = round(ig_close - ig_open, 2)
                else:
                    ig_pnl_pips = round(ig_open - ig_close, 2)

            price_delta_pts = None
            if ig_close is not None and u_exit is not None:
                price_delta_pts = round(u_exit - ig_close, 2)
                diffs_price.append(abs(price_delta_pts))

            pnl_delta_gbp = None
            if ig_pnl_gbp is not None and u_pnl_gbp is not None:
                pnl_delta_gbp = round(u_pnl_gbp - ig_pnl_gbp, 2)
                diffs_pnl.append(abs(pnl_delta_gbp))

            # Root cause label: on the broker-side-close path, exit_price
            # should match last_mid (recorded as entry/exit hint set by the
            # external-close sweep).  Pips derived from last_mid vs IG's
            # actual stop/manual-close fill therefore understates loss on
            # fast adverse moves (SL hits during spread expansion).
            root_cause = "LAST_MID_INSTEAD_OF_IG_CLOSE_LEVEL"

            reconstruction.append({
                "deal_id": did,
                "ledger_present": True,
                "direction": direction,
                "unified_open_utc": o.get("ts_utc") if o else None,
                "ig_open_utc": l.get("ig_open_date_utc"),
                "unified_close_utc": c.get("ts_utc"),
                "ig_close_utc": (l.get("ig_closes") or [{}])[0].get("date"),
                "ig_open_level": ig_open,
                "unified_entry_price": u_entry,
                "ig_close_level": ig_close,
                "unified_exit_price": u_exit,
                "price_delta_pts (unified-ig)": price_delta_pts,
                "ig_pnl_pips": ig_pnl_pips,
                "unified_pnl_pips": u_pnl_pips,
                "ig_pnl_gbp": ig_pnl_gbp,
                "unified_pnl_gbp": u_pnl_gbp,
                "pnl_delta_gbp (unified-ig)": pnl_delta_gbp,
                "expected_pnl_pips_from_ig_close": expected_pnl_pips,
                "price_source": c.get("price_source"),
                "ig_close_channel": l.get("ig_channel"),
                "n_amendments": len(l.get("ig_amendments") or []),
                "root_cause": root_cause,
            })

    def _stats(xs):
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "min": round(min(xs), 2),
            "max": round(max(xs), 2),
            "mean": round(statistics.mean(xs), 2),
            "median": round(statistics.median(xs), 2),
            "p90": round(sorted(xs)[int(0.9 * (len(xs) - 1))], 2),
        }

    return {
        "window_source": "Phase 4 broker ledger (df8bf63) × live unified_trades.jsonl snapshot",
        "n_external_close_rows": len(reconstruction),
        "n_ledger_matched": sum(1 for r in reconstruction if r.get("ledger_present")),
        "price_delta_pts_abs": _stats(diffs_price),
        "pnl_delta_gbp_abs": _stats(diffs_pnl),
        "root_cause_summary": "External-close sweep sets state.exit_price=last_mid "
                              "then invokes close_trade. close_by_deal_id fails (position "
                              "already gone), broker_side_close=True, no IG confirmation "
                              "is attempted, so exit_p = last_mid is written with "
                              "price_source=AUTHORITATIVE_BROKER_CLOSE (default). "
                              "Site: trade_executor.py:5538-5547 broker_side_close branch; "
                              "callback dispatch 5665-5675 passes no price_source kwarg.",
        "trades": reconstruction,
    }


def main() -> int:
    out = reconstruct()
    (DATA / "stageA_external_close_reconstruction.json").write_text(
        json.dumps(out, indent=2, default=str)
    )
    # Terse console summary.
    summary = {
        "n_external_close_rows": out["n_external_close_rows"],
        "n_ledger_matched": out["n_ledger_matched"],
        "price_delta_pts_abs": out["price_delta_pts_abs"],
        "pnl_delta_gbp_abs": out["pnl_delta_gbp_abs"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
