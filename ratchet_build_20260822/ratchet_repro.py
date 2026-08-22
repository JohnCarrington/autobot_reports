"""FRESH-WALKER reproduction — re-price the ladder_real_fires_20260822
column (c) on the same 131 real fires using the SHIPPED tiered_ratchet
module (not the pricing sim from the report). Independent walker.

Method: for each real fire, load the day's 5m bars from
/opt/tradingbot/data/candles/GBPUSD/{DATE}.csv, arm tiered_ratchet at
the ACTUAL entry price + timestamp, walk on_bar_close bar-by-bar from
the entry bar's next 5m boundary until the ratchet returns close=True
or the session flat time (RATCHET_FLAT_HHMM=20:40 UTC) triggers, or
the day's bars run out.

Bar-window rule matches the pricing sim (report column c):
  * entry_bar_index = first bar whose ts >= bar_floor(timestamp_open)+5min
  * walk each subsequent bar through on_bar_close(bar_ts, O, H, L, C, [])
  * session flat: at the first bar whose ts >= 20:40 UTC, close at that
    bar's open price with reason RATCHET_FLAT_2040
  * closes_series is not needed by the ratchet (empty list is fine)

Then aggregate:
  * total pnl vs report's +318.3p
  * per-fire pnl vs the report's per-fire values (from
    ladder_real_walk.json.RATCHET.pnl)
  * list any divergence > 2p
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Isolate state paths so this run doesn't touch prod caches
tmp = tempfile.mkdtemp(prefix="ratchet_repro_")
os.environ["RATCHET_STATE_PATH"] = f"{tmp}/state.json"
os.environ["RATCHET_TELEMETRY_PATH"] = f"{tmp}/tele.jsonl"
os.environ["RATCHET_TIERS"] = "10:0,30:15,60:40,100:75"
os.environ["RATCHET_INIT_SL_PIPS"] = "12"
os.environ["RATCHET_EXHAUST_BARS"] = "6"
os.environ["RATCHET_FLAT_HHMM"] = "20:40"

# Silence the RATCHET boot line — noisy in a 131-fire run
import logging
logging.getLogger("AutoBot").setLevel(logging.WARNING)

import tiered_ratchet


CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
FIRES_PATH = "/opt/tradingbot/reports-public/ladder_real_fires_20260822/ladder_fires.jsonl"
REPORT_WALK = "/opt/tradingbot/reports-public/ladder_real_fires_20260822/ladder_real_walk.json"

FLAT_HH = tiered_ratchet.RATCHET_FLAT_HH
FLAT_MM = tiered_ratchet.RATCHET_FLAT_MM


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
            return i - 1   # entry AT this bar close; walk starts at i
    return None


def _walk_fire(fire: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (result dict, reason-if-unpriceable)."""
    ts_open = fire["timestamp_open"]
    d_iso = ts_open[:10]
    rows = _load_day(d_iso)
    if rows is None or len(rows) < 5:
        return None, "candles_missing"
    idx = _entry_bar_idx(rows, ts_open)
    if idx is None or idx + 1 >= len(rows):
        return None, "entry_bar_not_locatable"
    direction = str(fire["direction"]).upper()
    entry_price = float(fire["entry"])
    pk = f"REPRO|{fire['id']}"
    # arm at the actual entry ts + price
    tiered_ratchet.arm(
        pos_key=pk, mode=str(fire.get("strategy") or "").upper(),
        direction=direction, symbol="GBPUSD",
        entry_ts=_parse_ts(ts_open), entry_price=entry_price,
    )
    # walk
    exit_reason = None
    exit_price = None
    exit_ts = None
    exit_bar = None
    for j in range(idx + 1, len(rows)):
        b = rows[j]
        bt = _parse_ts(b["ts"])
        # session-flat at RATCHET_FLAT_HHMM UTC — exit at THIS bar's open
        if bt.time() >= _flat_time():
            exit_reason = "RATCHET_FLAT_2040"
            exit_price = float(b["open"])
            exit_ts = b["ts"]
            exit_bar = j
            # tell the state machine
            try:
                tiered_ratchet.force_close_for_session_flat(pk)
            except Exception:
                pass
            break
        act = tiered_ratchet.on_bar_close(
            pos_key=pk, bar_ts=bt,
            bar_open=float(b["open"]), bar_high=float(b["high"]),
            bar_low=float(b["low"]), bar_close=float(b["close"]),
            closes_series=[],
        )
        if act is None:
            continue
        if act.close:
            exit_reason = act.close_reason
            if act.close_reason == "RATCHET_STOP":
                # exit price = the software stop level (the pricing sim
                # in ladder_real_fires_20260822 uses bar_close as the
                # RATCHET_STOP exit price; match that so numbers are
                # comparable). See ladder_real_walk.py sim_ratchet:
                # `return dict(exit_price=sl, pnl=(sl-entry), reason='SL')`.
                # We match the shipped semantics: intended-stop preemption
                # closes at bar_close, RATCHET_STOP treated the same way.
                exit_price = float(b["close"])
            elif act.close_reason == "RATCHET_EXHAUSTION":
                exit_price = float(b["close"])
            else:
                exit_price = float(b["close"])
            exit_ts = b["ts"]
            exit_bar = j
            break
    if exit_reason is None:
        # ran off end of day without a close
        b = rows[-1]
        exit_price = float(b["close"])
        exit_reason = "EOD_TAIL"
        exit_ts = b["ts"]
        exit_bar = len(rows) - 1
    # pnl (pips, native units)
    is_buy = direction == "BUY"
    pnl = (exit_price - entry_price) if is_buy else (entry_price - exit_price)
    # cleanup — drop this pos_key from state so the next fire starts clean
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
    }, ""


def _flat_time():
    from datetime import time as _t
    return _t(FLAT_HH, FLAT_MM)


def main() -> None:
    fires: List[Dict[str, Any]] = []
    with open(FIRES_PATH) as f:
        for line in f:
            fires.append(json.loads(line))
    print(f"Loaded {len(fires)} real fires from {FIRES_PATH}")

    report_walk = None
    if os.path.exists(REPORT_WALK):
        report_walk = json.load(open(REPORT_WALK))
        report_by_ts = {r["fire"]["ts"]: r for r in report_walk}
    else:
        report_by_ts = {}

    results: List[Dict[str, Any]] = []
    unpriceable: List[Tuple[str, str]] = []
    for fire in fires:
        r, err = _walk_fire(fire)
        if r is None:
            unpriceable.append((fire["timestamp_open"], err))
            continue
        # report expected pnl for comparison
        if fire["timestamp_open"] in report_by_ts:
            rrec = report_by_ts[fire["timestamp_open"]]
            r["report_ratchet_pnl"] = (
                (rrec.get("RATCHET") or {}).get("pnl")
                if rrec.get("RATCHET") is not None else None
            )
            r["report_ratchet_reason"] = (
                (rrec.get("RATCHET") or {}).get("reason")
                if rrec.get("RATCHET") is not None else None
            )
        results.append(r)

    # ── aggregate
    total_repro = sum(r["pnl_pips"] for r in results)
    total_report = sum(r["report_ratchet_pnl"] or 0.0 for r in results
                       if r.get("report_ratchet_pnl") is not None)
    print()
    print("=" * 72)
    print("  AGGREGATE")
    print("=" * 72)
    print(f"  Priceable fires:     {len(results)} / {len(fires)}")
    print(f"  Unpriceable:         {len(unpriceable)}")
    for ts, why in unpriceable[:5]:
        print(f"    {ts}  {why}")
    print(f"  FRESH walker total:  {total_repro:+.1f} p")
    print(f"  Report column (c):   +318.3 p  (reports-public/ladder_real_fires_20260822/REPORT.md §2)")
    print(f"  Report per-fire sum: {total_report:+.1f} p  (from ladder_real_walk.json.RATCHET.pnl)")
    delta_c = total_repro - 318.3
    delta_per_fire = total_repro - total_report
    print(f"  Δ vs report §2:      {delta_c:+.2f} p  ({100*delta_c/max(0.1,abs(318.3)):+.2f}%)")
    print(f"  Δ vs per-fire sum:   {delta_per_fire:+.2f} p")

    # per-mode
    from collections import defaultdict
    per_mode = defaultdict(lambda: dict(n=0, repro=0.0, report=0.0))
    for r in results:
        pm = per_mode[r["strategy"]]
        pm["n"] += 1
        pm["repro"] += r["pnl_pips"]
        pm["report"] += r.get("report_ratchet_pnl") or 0.0
    print()
    print(f"  {'mode':<26s} {'n':>4s} {'FRESH':>12s} {'REPORT':>12s} {'delta':>10s}")
    for m in sorted(per_mode):
        pm = per_mode[m]
        print(f"  {m:<26s} {pm['n']:>4d} {pm['repro']:>+12.1f} {pm['report']:>+12.1f} "
              f"{pm['repro']-pm['report']:>+10.1f}")

    # per-fire divergences > 2p
    print()
    print("=" * 72)
    print("  PER-FIRE DIVERGENCES > 2 p (FRESH vs report per-fire)")
    print("=" * 72)
    divs = []
    for r in results:
        rp = r.get("report_ratchet_pnl")
        if rp is None:
            continue
        d = r["pnl_pips"] - rp
        if abs(d) > 2.0:
            divs.append(r)
    divs.sort(key=lambda x: -abs(x["pnl_pips"] - x["report_ratchet_pnl"]))
    if not divs:
        print("  None — every priced fire agrees with the report within 2 p.")
    else:
        print(f"  n = {len(divs)}")
        print(f"  {'entry_ts':<19s} {'mode':<26s} {'dir':>4s} "
              f"{'FRESH':>8s} {'REPORT':>8s} {'delta':>7s}  "
              f"{'FRESH_reason':<24s} {'REPORT_reason':<24s}")
        for r in divs:
            d = r["pnl_pips"] - r["report_ratchet_pnl"]
            print(f"  {r['entry_ts'][:19]:<19s} {r['strategy']:<26s} "
                  f"{r['direction']:>4s} "
                  f"{r['pnl_pips']:>+8.1f} {r['report_ratchet_pnl']:>+8.1f} "
                  f"{d:>+7.1f}  "
                  f"{r['exit_reason']:<24s} "
                  f"{(r.get('report_ratchet_reason') or ''):<24s}")

    # save the fresh table for future joins
    out_dir = "/opt/tradingbot/reports-public/ratchet_build_20260822"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "fresh_walker_per_fire.jsonl"), "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"\nfresh per-fire → {out_dir}/fresh_walker_per_fire.jsonl")


if __name__ == "__main__":
    main()
