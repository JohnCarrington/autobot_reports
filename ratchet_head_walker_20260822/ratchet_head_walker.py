"""FRESH-WALKER v2 — HEAD (ff02fb5) semantics.

Same 131 fires as ratchet_build_20260822/fresh_walker_per_fire.jsonl, same
output shape (JSONL, one dict per fire), but priced against the HEAD
ratchet contract:

    1. STRICTLY-BEYOND-BE EXHAUSTION (88f075d).
       RATCHET_EXHAUSTION only fires when the software stop is STRICTLY
       beyond BE (sw_stop > entry for LONG, sw_stop < entry for SHORT).
       Tier-0 BE stall no longer trips exhaustion. This is a
       tiered_ratchet module change — the walker just calls
       on_bar_close() and lets the module decide. No walker-side change.

    2. BROKER INIT SL AT ENTRY ±12 (88f075d + ff02fb5).
       Modeled as a hard intra-bar backstop that fills EXACTLY at the
       ±12 level on any bar whose low/high touches it. Not a bar-close
       decision — a real broker stop fills mid-bar.

       INSTALLATION is gated by the item-2 guard
       `_ratchet_arm_should_install_broker_sl(tp_pips, existing_sl_pips,
       init_sl_pips)`. Same guard logic reused here — if the fire's
       tp1_pips is missing/zero or its sl_pips is already inside 12,
       we DON'T install the ±12 backstop.

       When the guard skips with reason `already_inside`, the broker
       still holds whatever execute_trade set — modeled here as an
       intra-bar backstop at ±sl_pips (tighter than ±12). When the
       guard skips with `tp_absent`, we still model an intra-bar
       backstop at ±sl_pips because execute_trade always sends an SL
       even when TP is absent — the fix only refuses to WIDEN it via
       the ratchet-arm PUT.

    3. TIER STOPS ON CLOSE-BEYOND (existing on_bar_close).
       Software ratchet tier locks + RATCHET_STOP fire on the 5m
       CLOSE crossing the software_stop_price. Fill priced at bar
       close (bot sends a market close after seeing the close-beyond).

Ordering per bar:
    a. Check the broker backstop against intra-bar high/low FIRST. If
       breached, fill at the backstop price and exit — the broker filled
       mid-bar, before the 5m close-beyond decision.
    b. Otherwise call on_bar_close(). If it returns close=True, exit at
       bar_close with the module's close_reason.
    c. Otherwise continue to the next bar.
    d. Session-flat at 20:40 UTC exits at the first-bar's open.

Output: ratchet_head_walker_per_fire.jsonl — one JSON per fire with the
same schema as the prior fresh_walker_per_fire.jsonl plus:
    broker_backstop_pips  — the pip distance the broker held (12 if
                            guard installed the ratchet init; else the
                            execute_trade sl_pips).
    guard_reason          — "ok" / "already_inside" / "tp_absent".
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone, time as _time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Isolate state paths — this run must not touch prod caches.
tmp = tempfile.mkdtemp(prefix="ratchet_head_walker_")
os.environ["RATCHET_STATE_PATH"] = f"{tmp}/state.json"
os.environ["RATCHET_TELEMETRY_PATH"] = f"{tmp}/tele.jsonl"
os.environ["RATCHET_TIERS"] = "10:0,30:15,60:40,100:75"
os.environ["RATCHET_INIT_SL_PIPS"] = "12"
os.environ["RATCHET_EXHAUST_BARS"] = "6"
os.environ["RATCHET_FLAT_HHMM"] = "20:40"

import logging
logging.getLogger("AutoBot").setLevel(logging.WARNING)

# Silence the standard "logging basicConfig" noise from the shipped module
logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, "/opt/tradingbot")
import tiered_ratchet
from trade_executor import _ratchet_arm_should_install_broker_sl  # HEAD guard


CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
FIRES_PATH = "/opt/tradingbot/reports-public/ladder_real_fires_20260822/ladder_fires.jsonl"
REPORT_WALK = "/opt/tradingbot/reports-public/ladder_real_fires_20260822/ladder_real_walk.json"
PRIOR_FRESH = "/opt/tradingbot/reports-public/ratchet_build_20260822/fresh_walker_per_fire.jsonl"

RATCHET_INIT_SL_PIPS = float(os.environ["RATCHET_INIT_SL_PIPS"])
FLAT_HH = tiered_ratchet.RATCHET_FLAT_HH
FLAT_MM = tiered_ratchet.RATCHET_FLAT_MM


def _flat_time() -> _time:
    return _time(FLAT_HH, FLAT_MM)


def _load_day(iso: str) -> Optional[List[Dict[str, Any]]]:
    p = os.path.join(CANDLES, f"{iso}.csv")
    if not os.path.exists(p):
        return None
    out: List[Dict[str, Any]] = []
    with open(p) as f:
        for r in csv.DictReader(f):
            try:
                out.append(dict(
                    ts=r["timestamp"],
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                ))
            except Exception:
                continue
    return out


def _parse_ts(s: str) -> datetime:
    s = s.replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _bar_floor(ts: datetime) -> datetime:
    m = ts.minute - (ts.minute % 5)
    return ts.replace(minute=m, second=0, microsecond=0)


def _entry_bar_idx(rows: List[Dict[str, Any]], ts_open: str) -> Optional[int]:
    t = _parse_ts(ts_open)
    target = _bar_floor(t) + timedelta(minutes=5)
    for i, b in enumerate(rows):
        try:
            bt = _parse_ts(b["ts"])
        except Exception:
            continue
        if bt >= target:
            return i - 1
    return None


def _resolve_broker_backstop(fire: Dict[str, Any]) -> Tuple[float, str]:
    """Reuse the HEAD guard to decide whether the ratchet-arm broker-SL
    PUT would install at ±RATCHET_INIT_SL_PIPS, and what the effective
    broker backstop distance is once execute_trade has run.

    Returns (backstop_pips, guard_reason).
      * guard_reason="ok"             → ratchet-arm installed ±12. That
        WIDENS the execute_trade SL from sl_pips>12 to 12, so backstop=12.
      * guard_reason="already_inside" → execute_trade SL already ≤12.
        Ratchet-arm skipped; broker retains the execute_trade sl_pips.
      * guard_reason="tp_absent"      → shouldn't occur here (all 131
        fires have tp1_pips>0) but keep the branch for completeness.
        Broker retains the execute_trade sl_pips.
    """
    tp_pips = float(fire.get("tp1_pips") or 0.0)
    sl_pips = float(fire.get("sl_pips") or 0.0)
    install, reason = _ratchet_arm_should_install_broker_sl(
        tp_pips=tp_pips,
        existing_sl_pips=sl_pips,
        init_sl_pips=RATCHET_INIT_SL_PIPS,
    )
    if install:
        return RATCHET_INIT_SL_PIPS, reason
    # skip → whatever execute_trade set stays
    if sl_pips > 0:
        return sl_pips, reason
    # execute_trade had no SL (unlikely) → no backstop
    return 0.0, reason


def _broker_touch_this_bar(
    is_buy: bool,
    entry_price: float,
    backstop_pips: float,
    ppp: float,
    bar_low: float,
    bar_high: float,
) -> Optional[float]:
    """If the broker backstop touches this bar (intra-bar), return the
    fill price (exactly the backstop level). Else return None.

    The broker fills at the STOP LEVEL, not at market — a stop order
    on a mainstream forex broker is executed at the level (assume no
    slippage, matching how the ladder pricing simulator treats fills).
    """
    if backstop_pips <= 0:
        return None
    if is_buy:
        stop_px = entry_price - backstop_pips * ppp
        if bar_low <= stop_px:
            return stop_px
    else:
        stop_px = entry_price + backstop_pips * ppp
        if bar_high >= stop_px:
            return stop_px
    return None


def _walk_fire(fire: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    ts_open = fire["timestamp_open"]
    d_iso = ts_open[:10]
    rows = _load_day(d_iso)
    if rows is None or len(rows) < 5:
        return None, "candles_missing"
    idx = _entry_bar_idx(rows, ts_open)
    if idx is None or idx + 1 >= len(rows):
        return None, "entry_bar_not_locatable"

    direction = str(fire["direction"]).upper()
    is_buy = direction == "BUY"
    entry_price = float(fire["entry"])
    pk = f"HEADREPRO|{fire['id']}"
    ppp = tiered_ratchet._pip_size_for_symbol("GBPUSD")

    backstop_pips, guard_reason = _resolve_broker_backstop(fire)

    tiered_ratchet.arm(
        pos_key=pk,
        mode=str(fire.get("strategy") or "").upper(),
        direction=direction,
        symbol="GBPUSD",
        entry_ts=_parse_ts(ts_open),
        entry_price=entry_price,
    )

    exit_reason = None
    exit_price = None
    exit_ts = None
    exit_bar = None
    for j in range(idx + 1, len(rows)):
        b = rows[j]
        try:
            bt = _parse_ts(b["ts"])
        except Exception:
            continue

        # Session-flat FIRST — matches the ladder pricing sim.
        if bt.time() >= _flat_time():
            exit_reason = "RATCHET_FLAT_2040"
            exit_price = float(b["open"])
            exit_ts = b["ts"]
            exit_bar = j
            try:
                tiered_ratchet.force_close_for_session_flat(pk)
            except Exception:
                pass
            break

        # NEW SEMANTIC (HEAD): broker backstop fills intra-bar. Check
        # BEFORE on_bar_close so a bar that touches ±backstop and then
        # closes above BE still exits at −backstop.
        touch_px = _broker_touch_this_bar(
            is_buy, entry_price, backstop_pips, ppp,
            float(b["low"]), float(b["high"]),
        )
        if touch_px is not None:
            exit_reason = "BROKER_INIT_SL_TOUCH"
            exit_price = float(touch_px)
            exit_ts = b["ts"]
            exit_bar = j
            break

        # Software close-beyond stop + tier ratchet (module logic).
        act = tiered_ratchet.on_bar_close(
            pos_key=pk,
            bar_ts=bt,
            bar_open=float(b["open"]),
            bar_high=float(b["high"]),
            bar_low=float(b["low"]),
            bar_close=float(b["close"]),
            closes_series=[],
        )
        if act is None or not act.close:
            continue
        exit_reason = act.close_reason
        exit_price = float(b["close"])
        exit_ts = b["ts"]
        exit_bar = j
        break

    if exit_reason is None:
        # ran off the end of the day
        b = rows[-1]
        exit_reason = "EOD_TAIL"
        exit_price = float(b["close"])
        exit_ts = b["ts"]
        exit_bar = len(rows) - 1

    pnl = (exit_price - entry_price) if is_buy else (entry_price - exit_price)

    tiered_ratchet.on_position_closed(pk)
    return {
        "id": fire["id"],
        "date": d_iso,
        "strategy": fire["strategy"],
        "direction": direction,
        "entry_ts": ts_open,
        "entry_price": entry_price,
        "exit_ts": exit_ts,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "exit_bar": exit_bar,
        "pnl_pips": round(pnl, 2),
        "actual_pnl_pips": fire.get("pnl_pips"),
        # HEAD-walker additions
        "broker_backstop_pips": backstop_pips,
        "guard_reason": guard_reason,
    }, ""


def _load_prior_fresh() -> Dict[str, Dict[str, Any]]:
    """Prior-walker rows keyed by fire id for delta printing."""
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(PRIOR_FRESH):
        return out
    with open(PRIOR_FRESH) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            out[r["id"]] = r
    return out


def main() -> None:
    fires: List[Dict[str, Any]] = []
    with open(FIRES_PATH) as f:
        for line in f:
            fires.append(json.loads(line))
    print(f"Loaded {len(fires)} real fires from {FIRES_PATH}")

    prior = _load_prior_fresh()
    print(f"Loaded {len(prior)} prior-walker rows for delta printing")

    results: List[Dict[str, Any]] = []
    unpriceable: List[Tuple[str, str]] = []
    for fire in fires:
        r, err = _walk_fire(fire)
        if r is None:
            unpriceable.append((fire["timestamp_open"], err))
            continue
        # attach prior-walker pnl + reason for the delta table
        p = prior.get(r["id"])
        if p is not None:
            r["prior_walker_pnl"] = p.get("pnl_pips")
            r["prior_walker_reason"] = p.get("exit_reason")
        results.append(r)

    total_head = sum(r["pnl_pips"] for r in results)
    total_prior = sum(
        (r.get("prior_walker_pnl") or 0.0) for r in results
        if r.get("prior_walker_pnl") is not None
    )

    print()
    print("=" * 72)
    print("  AGGREGATE  (HEAD-walker vs prior FRESH walker)")
    print("=" * 72)
    print(f"  Priceable fires:            {len(results)} / {len(fires)}")
    print(f"  Unpriceable:                {len(unpriceable)}")
    for ts, why in unpriceable[:5]:
        print(f"    {ts}  {why}")
    print(f"  HEAD-walker total:          {total_head:+.1f} p")
    print(f"  Prior fresh walker total:   {total_prior:+.1f} p"
          "  (ratchet_build_20260822 §fresh-walker)")
    delta = total_head - total_prior
    print(f"  Δ vs prior fresh walker:    {delta:+.2f} p"
          f"  ({100*delta/max(0.1,abs(total_prior)):+.2f}%)")

    from collections import defaultdict, Counter
    per_reason_head = Counter(r["exit_reason"] for r in results)
    per_reason_prior = Counter(
        r.get("prior_walker_reason") for r in results
        if r.get("prior_walker_reason") is not None
    )
    print()
    print("  Exit-reason mix (HEAD vs prior):")
    all_reasons = sorted(set(per_reason_head) | set(per_reason_prior))
    print(f"  {'reason':<26s} {'HEAD n':>7s} {'PRIOR n':>8s} {'delta':>7s}")
    for rsn in all_reasons:
        h = per_reason_head.get(rsn, 0)
        p = per_reason_prior.get(rsn, 0)
        print(f"  {rsn:<26s} {h:>7d} {p:>8d} {h-p:>+7d}")

    per_mode = defaultdict(lambda: dict(n=0, head=0.0, prior=0.0))
    for r in results:
        pm = per_mode[r["strategy"]]
        pm["n"] += 1
        pm["head"] += r["pnl_pips"]
        pm["prior"] += r.get("prior_walker_pnl") or 0.0
    print()
    print(f"  {'mode':<26s} {'n':>4s} {'HEAD':>12s} {'PRIOR':>12s} {'delta':>10s}")
    for m in sorted(per_mode):
        pm = per_mode[m]
        print(f"  {m:<26s} {pm['n']:>4d} {pm['head']:>+12.1f} "
              f"{pm['prior']:>+12.1f} {pm['head']-pm['prior']:>+10.1f}")

    # per-fire divergences > 2 p
    print()
    print("=" * 72)
    print("  PER-FIRE DIVERGENCES > 2 p (HEAD-walker vs prior FRESH walker)")
    print("=" * 72)
    divs = []
    for r in results:
        pp = r.get("prior_walker_pnl")
        if pp is None:
            continue
        d = r["pnl_pips"] - pp
        if abs(d) > 2.0:
            divs.append(r)
    divs.sort(key=lambda x: -abs(x["pnl_pips"] - x["prior_walker_pnl"]))
    if not divs:
        print("  None — HEAD semantics agree with prior FRESH within 2 p.")
    else:
        print(f"  n = {len(divs)}")
        print(f"  {'entry_ts':<19s} {'mode':<26s} {'dir':>4s} "
              f"{'HEAD':>7s} {'PRIOR':>7s} {'delta':>7s}  "
              f"{'HEAD_reason':<24s} {'PRIOR_reason':<24s}")
        for r in divs:
            d = r["pnl_pips"] - r["prior_walker_pnl"]
            print(f"  {r['entry_ts'][:19]:<19s} {r['strategy']:<26s} "
                  f"{r['direction']:>4s} "
                  f"{r['pnl_pips']:>+7.1f} {r['prior_walker_pnl']:>+7.1f} "
                  f"{d:>+7.1f}  "
                  f"{r['exit_reason']:<24s} "
                  f"{(r.get('prior_walker_reason') or ''):<24s}")

    # Guard-reason split
    from collections import Counter as _C
    gr = _C(r["guard_reason"] for r in results)
    print()
    print("  Guard-reason split (item 2 helper decisions at arm time):")
    for k, v in sorted(gr.items()):
        print(f"    {k:<20s} {v:>4d}")

    out_dir = Path(__file__).resolve().parent
    with open(out_dir / "ratchet_head_walker_per_fire.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"\nHEAD per-fire → {out_dir / 'ratchet_head_walker_per_fire.jsonl'}")


if __name__ == "__main__":
    main()
