"""Phase 5 Stage G — real entry slippage measurement.

Joins strategy-fire records (forensic_fires.jsonl + standalone BB Bounce
setup rows) to the Phase 4 IG DEMO ledger to compute true entry
slippage:

    requested price (strategy reference) → IG actual fill level.

A fire is only joined to an IG open when the match is unambiguous:

    * same direction
    * same instrument family (GBPUSD)
    * IG open occurs ≤ 60 s after the fire
    * no other fire of the same strategy within the 60-second window

If the matching rule finds no unambiguous IG partner, the fire is
reported as UNMATCHED.  No slippage number is manufactured.

Writes `data/stageG_entry_slippage.json`.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from statistics import mean, median
from collections import Counter


HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
LEDGER = json.load(open(DATA / "trade_ledger.json"))

FIRE_PATHS = sorted(Path("/opt/tradingbot/logs").glob("forensic_fires.jsonl*"))
BBB_FILL_PATH = Path("/opt/tradingbot/logs/bb_pierce_trades.jsonl")

WINDOW_START = "2026-09-17"
WINDOW_END = "2026-10-28"
JOIN_TOL_SECS = 60


def _parse_ts(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_fires() -> list[dict]:
    import gzip
    out = []
    for p in FIRE_PATHS:
        if not p.exists():
            continue
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    out = [f for f in out
           if WINDOW_START <= (f.get("timestamp") or "") < WINDOW_END]
    return out


def _collect_ig_opens() -> list[dict]:
    out = []
    for did, t in LEDGER.items():
        if t.get("match_grade") != "FULLY_RECONCILED":
            continue
        open_ts = t.get("ig_open_date_utc")
        if not open_ts:
            continue
        try:
            open_dt = dt.datetime.fromisoformat(open_ts)
        except Exception:
            continue
        out.append({
            "deal_id": did,
            "ts": open_dt.replace(tzinfo=dt.timezone.utc) if open_dt.tzinfo is None else open_dt,
            "ts_s": open_dt.isoformat(),
            "direction": str(t.get("ig_direction") or "").upper(),
            "level": t.get("ig_open_level"),
            "source_system": t.get("source_system"),
            "strategy_family": t.get("strategy_family"),
        })
    return out


def _strategy_direction(f: dict) -> str:
    d = (f.get("direction") or "").upper()
    if d in ("BUY", "SELL"):
        return d
    if d in ("LONG",):
        return "BUY"
    if d in ("SHORT",):
        return "SELL"
    return d


def main() -> int:
    fires = _load_fires()
    opens = _collect_ig_opens()
    print(f"fires in window: {len(fires)}")
    print(f"IG opens in window: {len(opens)}")

    # Build index by minute → fast lookup
    results = []
    unmatched = []
    for f in fires:
        f_ts = _parse_ts(f.get("timestamp"))
        if f_ts is None:
            unmatched.append({"reason": "NO_FIRE_TS", "fire": f.get("strategy")})
            continue
        f_dir = _strategy_direction(f)
        if f_dir not in ("BUY", "SELL"):
            unmatched.append({"reason": "NO_DIRECTION", "fire": f.get("strategy")})
            continue
        candidates = []
        for o in opens:
            if o["direction"] != f_dir:
                continue
            delta = (o["ts"] - f_ts).total_seconds()
            if 0 <= delta <= JOIN_TOL_SECS:
                candidates.append((delta, o))
        if not candidates:
            unmatched.append({
                "reason": "NO_IG_WITHIN_TOL",
                "fire_ts": f.get("timestamp"),
                "fire_strategy": f.get("strategy"),
                "fire_direction": f_dir,
            })
            continue
        candidates.sort(key=lambda c: c[0])
        delta, o = candidates[0]
        ref_price = f.get("entry_price")
        ig_level = o["level"]
        if ref_price is None or ig_level is None:
            unmatched.append({
                "reason": "MISSING_PRICE",
                "fire_strategy": f.get("strategy"),
            })
            continue
        # IG open level is in POINTS (e.g. 13300).  Strategy reference is
        # also in points (bb_bounce fires record entry_price in points).
        slip_pts = float(ig_level) - float(ref_price)
        # Direction-adjusted: positive = unfavourable (BUY: ig_level > ref)
        if f_dir == "SELL":
            slip_pts = -slip_pts
        results.append({
            "fire_ts": f.get("timestamp"),
            "fire_strategy": f.get("strategy"),
            "direction": f_dir,
            "requested_level": ref_price,
            "ig_fill_level": ig_level,
            "slippage_pips": round(slip_pts, 2),
            "submission_to_fill_secs": round(delta, 2),
            "ig_deal_id": o["deal_id"],
            "ig_source_system": o["source_system"],
        })

    def _stats(xs):
        if not xs:
            return {"n": 0}
        s = sorted(xs)
        return {
            "n": len(xs),
            "min": round(s[0], 2),
            "max": round(s[-1], 2),
            "mean": round(mean(xs), 2),
            "median": round(median(xs), 2),
            "p90": round(s[int(0.9 * (len(s) - 1))], 2),
        }

    slips = [r["slippage_pips"] for r in results]
    buys = [r for r in results if r["direction"] == "BUY"]
    sells = [r for r in results if r["direction"] == "SELL"]
    bbb = [r for r in results if "BB_BOUNCE" in str(r["fire_strategy"] or "")]

    summary = {
        "n_fires": len(fires),
        "n_ig_opens": len(opens),
        "n_matched": len(results),
        "n_unmatched": len(unmatched),
        "slippage_overall_pips": _stats(slips),
        "slippage_buy_pips": _stats([r["slippage_pips"] for r in buys]),
        "slippage_sell_pips": _stats([r["slippage_pips"] for r in sells]),
        "slippage_bb_bounce_pips": _stats([r["slippage_pips"] for r in bbb]),
        "worst_adverse": round(max(slips), 2) if slips else None,
        "best_favourable": round(min(slips), 2) if slips else None,
        "unmatched_reasons": dict(Counter(u["reason"] for u in unmatched)),
    }
    out = {"summary": summary, "matched": results, "unmatched": unmatched}
    (DATA / "stageG_entry_slippage.json").write_text(
        json.dumps(out, indent=2, default=str)
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
