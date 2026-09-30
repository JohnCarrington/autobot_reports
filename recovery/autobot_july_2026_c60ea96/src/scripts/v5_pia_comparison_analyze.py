#!/usr/bin/env python3
"""Read v5_pia_comparison.jsonl and print decision-rule report.

Decision rule (pre-committed):
  After ≥10 sessions, recommend CUTOVER if EITHER:
    (a) v5 simulated total P&L > v4 actual total P&L, OR
    (b) v5 blocked more losing v4 fires than it missed winning v4 fires.

ASYMMETRY CAVEAT (printed in the report header too):
  v4 P&L is broker-confirmed close from signal_log.
  v5 P&L is simulated from 5M candles using SL-first convention when
  both SL and TP land in the same bar's range. v5 is structurally
  HANDICAPPED. If v5 wins despite the handicap, the result is strong;
  if v5 loses, factor in the handicap before drawing conclusions.
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter
from pathlib import Path

JSONL = Path("/opt/tradingbot/logs/v5_pia_comparison.jsonl")
MIN_SESSIONS = 10

def _trend_to_dir(t: str) -> str:
    return {"BULLISH": "BUY", "BEARISH": "SELL"}.get((t or "").upper(), "")

def _print_caveat() -> None:
    print("─" * 78)
    print("ASYMMETRY CAVEAT — read before interpreting P&L numbers below.")
    print("  v4 P&L: actual broker close (signal_log.timestamp_close + close_price).")
    print("  v5 P&L: simulated from 5M candles. SL-first convention when both SL")
    print("          and TP land in the same bar — biases v5 P&L DOWNWARD.")
    print("  → v5 winning is strong evidence; v5 losing needs handicap adjustment.")
    print("─" * 78)
    print()

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--path", default=str(JSONL))
    p.add_argument("--pair", help="restrict analysis to one pair")
    args = p.parse_args()

    rows = []
    if not Path(args.path).exists():
        print(f"no data at {args.path}"); return 1
    with open(args.path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if args.pair and r.get("pair") != args.pair.upper():
                continue
            rows.append(r)

    if not rows:
        print("no rows after filter"); return 1

    n = len(rows)
    print(f"=== v5_PIA vs v4 verbose briefing — {n} pair-session row(s) ===\n")
    _print_caveat()

    # 1) Direction agreement (only on rows where both briefings exist)
    cmp = [r for r in rows if r.get("v4_briefing_present") and r.get("v5_briefing_present")]
    agree_cnt = Counter(r["direction_agreement"] for r in cmp)
    print(f"Direction agreement (v4 primary vs v5 plan) — {len(cmp)} comparable rows:")
    for k, v in agree_cnt.most_common():
        pct = 100 * v / max(len(cmp), 1)
        print(f"  {k:14s} {v}/{len(cmp)} ({pct:.1f}%)")
    print()

    # 2) PnL sums
    v4_pnl = sum((r.get("v4_pnl_pips_session_total") or 0.0) for r in rows)
    v5_sim_rows = [r for r in rows if r.get("v5_state") == "TRADE"]
    v5_pnl = sum((r.get("v5_simulated_pnl_pips") or 0.0) for r in v5_sim_rows)
    n_v4_fires = sum(1 for r in rows if r.get("v4_fired"))
    print(f"v4 actual P&L total:      {v4_pnl:+.1f} pips ({n_v4_fires} fires)")
    print(f"v5 simulated P&L total:   {v5_pnl:+.1f} pips "
          f"({len(v5_sim_rows)} would-have-traded plans)")
    print()

    # 3) v5 stand-aside breakdown
    sa = [r for r in rows if r.get("v5_state") == "STAND_ASIDE"]
    sa_reasons = Counter(r.get("v5_stand_aside_reason") or "unknown" for r in sa)
    print(f"v5 STAND_ASIDE reasons ({len(sa)} total):")
    for k, v in sa_reasons.most_common():
        pct = 100 * v / max(len(sa), 1)
        print(f"  {k:32s} {v} ({pct:.1f}%)")
    print()

    # 4) Counter-trend v4 fires (per-trade granularity using v4_fires[])
    counter_trend: list = []
    for r in rows:
        if not r.get("v4_fired"):
            continue
        d1_dir = _trend_to_dir(r.get("v4_d1_trend") or "")
        if not d1_dir:
            continue  # neutral D1 → not counter-trend
        for fire in (r.get("v4_fires") or []):
            if fire.get("direction") and fire["direction"] != d1_dir:
                counter_trend.append((r, fire))
    ct_winners = [c for c in counter_trend if (c[1].get("pnl_pips") or 0) > 0]
    ct_losers  = [c for c in counter_trend if (c[1].get("pnl_pips") or 0) < 0]
    print(f"v4 counter-trend fires (v4 fired AGAINST v4_d1_trend): {len(counter_trend)}")
    print(f"  winners: {len(ct_winners)}  pnl="
          f"{sum((c[1].get('pnl_pips') or 0) for c in ct_winners):+.1f} pips")
    print(f"  losers:  {len(ct_losers)}   pnl="
          f"{sum((c[1].get('pnl_pips') or 0) for c in ct_losers):+.1f} pips")
    print()

    # 5) Decision rule
    blocked_losers = [r for r in rows
                      if r.get("v4_fired")
                      and (r.get("v4_pnl_pips_session_total") or 0) < 0
                      and r.get("v5_state") == "STAND_ASIDE"]
    missed_winners = [r for r in rows
                      if r.get("v4_fired")
                      and (r.get("v4_pnl_pips_session_total") or 0) > 0
                      and r.get("v5_state") == "STAND_ASIDE"]
    print(f"v5 blocked losing v4 fires:  {len(blocked_losers)}")
    print(f"v5 missed winning v4 fires:  {len(missed_winners)}")
    print()

    if n < MIN_SESSIONS:
        print(f"DECISION: INSUFFICIENT_DATA ({n}/{MIN_SESSIONS} pair-sessions logged)")
        return 0

    rule_a = v5_pnl > v4_pnl
    rule_b = len(blocked_losers) > len(missed_winners)
    print(f"After {n} pair-sessions:")
    print(f"  v5_PIA wins on P&L:                              "
          f"{'YES' if rule_a else 'NO'}  (v5={v5_pnl:+.1f} vs v4={v4_pnl:+.1f})")
    print(f"  v5_PIA blocks more losing counter-trend trades than it misses winning ones: "
          f"{'YES' if rule_b else 'NO'}")
    print(f"  Recommend cutover:                               "
          f"{'YES' if (rule_a or rule_b) else 'NO'}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
