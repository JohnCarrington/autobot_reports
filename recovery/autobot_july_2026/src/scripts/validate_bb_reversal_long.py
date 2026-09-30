"""
validate_bb_reversal_long.py — backtest GBPUSD_BB_REV_L (A_LOW only,
v2 TP2 exit, MAX_SL_PIPS reject) over 2026-03-30 → 2026-04-25 weekdays.
Walks 5m bars in [WIN_START, WIN_END) UTC; on each new close runs
the per-direction-filtered detectors; on a match simulates entry and
walks forward to SL or TP2 (SL priority on same-bar collision).

Outputs: per-trade ledger CSV + per-pattern aggregates + ship decision.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

REPO = Path("/opt/tradingbot")
sys.path.insert(0, str(REPO))

import gbpusd_bb_reversal_long as bb3p  # alias kept for minimal-diff continuity  # noqa: E402

PIP_SIZE = 1.0
WIN_START = bb3p.WIN_START
WIN_END = bb3p.WIN_END
MAX_TRADES_PER_DAY = bb3p.MAX_TRADES_PER_DAY


def load_5m(date_str: str) -> pd.DataFrame:
    f = REPO / "data" / "candles" / "GBPUSD" / f"{date_str}.csv"
    if not f.exists():
        return pd.DataFrame()
    df = pd.read_csv(f)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def weekdays(start: str, end: str) -> List[str]:
    d0 = datetime.fromisoformat(start).date()
    d1 = datetime.fromisoformat(end).date()
    out: List[str] = []
    cur = d0
    while cur <= d1:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur = cur + timedelta(days=1)
    return out


def to_bar(row: pd.Series) -> bb3p.Bar:
    return bb3p.Bar(
        timestamp=row["timestamp"].to_pydatetime(),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
    )


def walk_to_outcome(
    bars_after: List[pd.Series],
    direction: str, entry: float,
    sl: float, tp1: float, tp2: float, tp3: float,
) -> Dict[str, Any]:
    """v2 walker: single exit at TP2 or SL, whichever first (SL priority on
    same-bar collision). On every bar, we check both SL and the live target;
    we never count a TP-reached after the trade has already closed.

    Also produces analytical-only fields:
      - tp1_pnl_if_used:  what v1 would have earned (TP1 exit) on this trade
      - tp3_pnl_if_used:  what v3 would have earned (TP3 exit) on this trade
      - tp1_reached_pre_sl, tp2_reached_pre_sl, tp3_reached_pre_sl: whether
        each target was hit before SL hit (SL-priority on same bar)

    Returns dict with v2 exit fields:
      exit_time, exit_price, exit_reason, pnl_at_exit  (this is TP2 exit)
    plus the analytical fields above.
    """
    def first_hit(stop: float, target: float) -> Tuple[Optional[int], str, float]:
        """Walk bars, return (idx, reason, exit_price) at first SL/target hit.
        SL priority on same-bar collision. If neither, return (None, "WINDOW_END", last_close)."""
        for i, r in enumerate(bars_after):
            h = float(r["high"]); l = float(r["low"])
            if direction == "SELL":
                sl_hit = h >= stop
                tp_hit = l <= target
            else:
                sl_hit = l <= stop
                tp_hit = h >= target
            if sl_hit and tp_hit:
                return i, "SL", float(stop)
            if sl_hit:
                return i, "SL", float(stop)
            if tp_hit:
                return i, "TP", float(target)
        if bars_after:
            last = bars_after[-1]
            return None, "WINDOW_END", float(last["close"])
        return None, "WINDOW_END", float(entry)

    def signed_pnl(exit_price: float) -> float:
        return (entry - exit_price) / PIP_SIZE if direction == "SELL" else (exit_price - entry) / PIP_SIZE

    # v2 — actual exit (TP2 vs SL)
    v2_idx, v2_reason, v2_price = first_hit(sl, tp2)
    v2_ts = (
        bars_after[v2_idx]["timestamp"].isoformat() if v2_idx is not None
        else (bars_after[-1]["timestamp"].isoformat() if bars_after else "")
    )
    v2_exit_reason = "TP2" if v2_reason == "TP" else v2_reason
    v2_pnl = signed_pnl(v2_price)

    # Analytical-only: TP1 exit (v1) and TP3 exit (v3). Both are independent
    # SL-vs-target walks against the SAME SL, used to fairly compare exit
    # policies on the same set of trades.
    _, t1_reason, t1_price = first_hit(sl, tp1)
    _, t3_reason, t3_price = first_hit(sl, tp3)
    tp1_pnl_if_used = signed_pnl(t1_price)
    tp3_pnl_if_used = signed_pnl(t3_price)

    # Reached-before-SL flags (analytical)
    tp1_reached_pre_sl = (t1_reason == "TP")
    tp2_reached_pre_sl = (v2_reason == "TP")
    tp3_reached_pre_sl = (t3_reason == "TP")

    return {
        "exit_time": v2_ts,
        "exit_price": v2_price,
        "exit_reason": v2_exit_reason,
        "pnl_at_exit": v2_pnl,
        "tp1_pnl_if_used": tp1_pnl_if_used,
        "tp3_pnl_if_used": tp3_pnl_if_used,
        "tp1_reached_pre_sl": tp1_reached_pre_sl,
        "tp2_reached_pre_sl": tp2_reached_pre_sl,
        "tp3_reached_pre_sl": tp3_reached_pre_sl,
    }


def session_extreme_so_far(
    bars_so_far: List[pd.Series], direction: str,
) -> Optional[float]:
    """For SHORT: return the max high seen so far in the session
    (the day's HIGH; we want the LOW as the target — the directive
    says "opposite session extreme" — the deepest level the session
    has reached on the OPPOSITE side. For SHORT that's the day's LOW
    so far; for LONG it's the day's HIGH so far)."""
    if not bars_so_far:
        return None
    if direction == "SELL":
        return float(min(r["low"] for r in bars_so_far))
    return float(max(r["high"] for r in bars_so_far))


def run() -> int:
    days = weekdays("2026-03-30", "2026-04-25")
    print(f"Backtest days: {len(days)}", file=sys.stderr)

    ledger: List[Dict[str, Any]] = []

    # We need a warmup of 20 closes for the BB. The validation walks bars
    # within the [06:45, 15:30] window but the BB is computed across all
    # bars in the day's CSV (including pre-window) so the very first
    # 06:45 bar's BB is well-defined.
    for day in days:
        df = load_5m(day)
        if df.empty:
            continue
        # Pre-load the previous day's last 20 closes to warm up BB on day open
        prev_day = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
        prev_df = load_5m(prev_day)
        warmup_closes: List[float] = []
        if not prev_df.empty:
            warmup_closes = [float(c) for c in prev_df["close"].tail(20).tolist()]

        # Window slice
        win_start = datetime.fromisoformat(day).replace(
            hour=WIN_START.hour, minute=WIN_START.minute, tzinfo=timezone.utc,
        )
        win_end = datetime.fromisoformat(day).replace(
            hour=WIN_END.hour, minute=WIN_END.minute, tzinfo=timezone.utc,
        )
        # Use ALL bars from the start of the day for BB warmup; only fire
        # patterns when bar time is in [win_start, win_end).
        all_bars: List[bb3p.Bar] = []
        all_rows: List[pd.Series] = list(df.iloc[i] for i in range(len(df)))
        running_closes: List[float] = list(warmup_closes)

        # Pattern detectors need [last 6 bars] history; trade walk-forward
        # uses subsequent bars from the same day.
        trades_today = 0
        skip_until_idx: Optional[int] = None  # while a trade is open, no new fires
        # Pre-build day's bars list of session bars seen so far (for session extremes)
        session_bars_so_far: List[pd.Series] = []

        for i, row in enumerate(all_rows):
            ts = row["timestamp"].to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            close_v = float(row["close"])
            running_closes.append(close_v)
            # Maintain a rolling list of last 6 bars (max needed by C with k=5)
            all_bars.append(to_bar(row))
            if len(all_bars) > 6:
                all_bars = all_bars[-6:]

            # In-window check
            if not (win_start <= ts < win_end):
                continue

            # Track session bars (in-window only) for session-extreme computation
            session_bars_so_far.append(row)

            # If we're inside a trade walk-forward window, skip detectors
            if skip_until_idx is not None and i < skip_until_idx:
                continue
            if skip_until_idx is not None and i >= skip_until_idx:
                skip_until_idx = None

            if trades_today >= MAX_TRADES_PER_DAY:
                continue

            # Need at least 20 closes for BB
            if len(running_closes) < 20:
                continue

            bb_lower, bb_mid, bb_upper = bb3p.bb_20_2(running_closes)

            # Detectors — mirror the live strategy's per-direction flag
            # filtering AND SL>MAX_SL_PIPS reject.
            def _direction_enabled(p: str) -> bool:
                return {
                    "A":      bb3p.PATTERN_A_SHORT_ENABLED,
                    "A_LOW":  bb3p.PATTERN_A_LOW_ENABLED,
                    "B":      bb3p.PATTERN_B_SHORT_ENABLED,
                    "B_LOW":  bb3p.PATTERN_B_LOW_ENABLED,
                    "C":      bb3p.PATTERN_C_SHORT_ENABLED,
                    "C_LOW":  bb3p.PATTERN_C_LOW_ENABLED,
                }.get(p, False)

            match: Optional[bb3p.PatternMatch] = None
            for det in (bb3p.detect_pattern_a, bb3p.detect_pattern_b, bb3p.detect_pattern_c):
                m = det(all_bars, bb_upper, bb_lower, bb_mid, PIP_SIZE)
                if m is None:
                    continue
                if not _direction_enabled(m.pattern):
                    continue
                match = m
                break
            if match is None:
                continue
            # SL distance reject (live-strategy parity)
            if match.sl_pips > bb3p.MAX_SL_PIPS:
                continue

            # Compute TP tiers using session extremes BEFORE this entry bar
            # (excluding the entry bar itself — bars_so_far up to i-1).
            extreme = session_extreme_so_far(session_bars_so_far[:-1], match.direction)
            tp1, tp2, tp3 = bb3p.compute_tp_levels(
                match, bb_upper, bb_lower, bb_mid,
                extreme if extreme is not None else match.entry_price, PIP_SIZE,
            )

            # Walk forward from bar i+1 to the end of the day's CSV.
            # The walker resolves SL vs TP2 with SL-priority on same-bar
            # collision; TP1/TP3 outcomes are independently computed against
            # the SAME SL for fair exit-policy comparison.
            forward = all_rows[i + 1:]
            outcome = walk_to_outcome(
                forward, match.direction, match.entry_price,
                match.sl_price, tp1, tp2, tp3,
            )

            ledger.append({
                "date": day,
                "time": ts.strftime("%H:%M"),
                "pattern": match.pattern,
                "direction": match.direction,
                "entry": round(match.entry_price, 1),
                "sl": round(match.sl_price, 1),
                "tp1": round(tp1, 1),
                "tp2": round(tp2, 1),
                "tp3": round(tp3, 1),
                "exit_time": str(outcome["exit_time"] or ""),
                "exit_price": round(outcome["exit_price"], 1) if outcome["exit_price"] is not None else None,
                "exit_reason": outcome["exit_reason"],
                "pnl_at_exit": round(outcome["pnl_at_exit"], 1),  # v2: TP2-or-SL exit
                "pnl_tp1_alt": round(outcome["tp1_pnl_if_used"], 1),
                "pnl_tp3_alt": round(outcome["tp3_pnl_if_used"], 1),
                "tp1_reached_pre_sl": outcome["tp1_reached_pre_sl"],
                "tp2_reached_pre_sl": outcome["tp2_reached_pre_sl"],
                "tp3_reached_pre_sl": outcome["tp3_reached_pre_sl"],
                "bb_upper_at_entry": round(bb_upper, 2),
                "bb_lower_at_entry": round(bb_lower, 2),
                "bb_mid_at_entry": round(bb_mid, 2),
                "notes": match.notes,
            })
            trades_today += 1

            # Skip new fires until trade resolves: find the bar index in
            # all_rows whose timestamp matches outcome["exit_time"].
            if outcome["exit_time"]:
                exit_dt = datetime.fromisoformat(outcome["exit_time"])
                # Find next i' where row.timestamp > exit_dt
                next_idx = None
                for j in range(i + 1, len(all_rows)):
                    bt = all_rows[j]["timestamp"]
                    if bt.to_pydatetime().replace(tzinfo=timezone.utc) > exit_dt.astimezone(timezone.utc):
                        next_idx = j
                        break
                skip_until_idx = next_idx if next_idx is not None else len(all_rows)

    # Save ledger CSV
    out_path = REPO / "data" / "audit_bb_rev_l" / "ledger.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger:
        cols = list(ledger[0].keys())
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(ledger)
    print(f"Ledger saved: {out_path} ({len(ledger)} trades)", file=sys.stderr)

    # Print ledger as a markdown table
    print("\n## Per-trade ledger\n")
    if not ledger:
        print("(no trades)")
    else:
        cols_short = [
            "date", "time", "pattern", "direction", "entry", "sl",
            "tp1", "tp2", "tp3", "exit_time", "exit_reason", "pnl_at_exit",
            "pnl_tp1_alt", "pnl_tp3_alt",
        ]
        print("| " + " | ".join(cols_short) + " |")
        print("|" + "|".join("---" for _ in cols_short) + "|")
        for r in ledger:
            print("| " + " | ".join(
                str(r[c])[:19] if c == "exit_time" else str(r[c])
                for c in cols_short
            ) + " |")

    # Aggregates per pattern (v2 = exit at TP2 or SL)
    from collections import defaultdict
    by_pat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in ledger:
        by_pat[r["pattern"]].append(r)

    print("\n## Per-pattern aggregates (v2 exit policy: TP2 or SL)\n")
    print("| pattern | trades | wins | losses | win_rate | avg_winner | avg_loser | net (v2 TP2) | net if TP1 | net if TP3 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    pattern_summary: Dict[str, Dict[str, Any]] = {}
    for pat in sorted(by_pat.keys()):
        trades = by_pat[pat]
        n = len(trades)
        wins = [t for t in trades if t["pnl_at_exit"] > 0]
        losses = [t for t in trades if t["pnl_at_exit"] <= 0]
        win_rate = (len(wins) / n) if n else 0.0
        avg_winner = (sum(t["pnl_at_exit"] for t in wins) / len(wins)) if wins else 0.0
        avg_loser = (sum(t["pnl_at_exit"] for t in losses) / len(losses)) if losses else 0.0
        net = sum(t["pnl_at_exit"] for t in trades)
        net_tp1 = sum(t["pnl_tp1_alt"] for t in trades)
        net_tp3 = sum(t["pnl_tp3_alt"] for t in trades)
        pattern_summary[pat] = {
            "trades": n, "wins": len(wins), "win_rate": win_rate,
            "avg_winner": avg_winner, "avg_loser": avg_loser,
            "net": net, "net_tp1": net_tp1, "net_tp3": net_tp3,
        }
        print(f"| {pat} | {n} | {len(wins)} | {len(losses)} | {win_rate*100:.1f}% | "
              f"{avg_winner:+.1f} | {avg_loser:+.1f} | {net:+.1f} | {net_tp1:+.1f} | {net_tp3:+.1f} |")

    # Combined
    n_total = len(ledger)
    wins_total = sum(1 for r in ledger if r["pnl_at_exit"] > 0)
    win_rate_total = (wins_total / n_total) if n_total else 0.0
    net_total = sum(r["pnl_at_exit"] for r in ledger)
    print("\n## Combined")
    print(f"- Total trades: {n_total}")
    print(f"- Win rate: {wins_total}/{n_total} = {win_rate_total*100:.1f}%")
    print(f"- Net P&L (v2, exit at TP2 or SL): {net_total:+.1f} pips")
    print(f"- Net P&L (analytical: TP1 instead): {sum(r['pnl_tp1_alt'] for r in ledger):+.1f} pips")
    print(f"- Net P&L (analytical: TP3 instead): {sum(r['pnl_tp3_alt'] for r in ledger):+.1f} pips")
    print(f"- Trading days in window: {len(days)}")
    print(f"- Trades per day average: {n_total/len(days):.2f}")

    # Per-pattern decision (≥5 fires, ≥55% WR, >+20p net)
    print("\n## Per-pattern decision\n")
    print("| pattern | criteria | trades≥5 | WR≥55% | net>+20p | DECISION |")
    print("|---|---|---|---|---|---|")
    decisions: Dict[str, str] = {}

    # Group both directions of a base pattern (A + A_LOW) into one shipping decision.
    # The ship flag controls whether the live strategy enables that base letter.
    base_patterns = {"A": ["A", "A_LOW"], "B": ["B", "B_LOW"], "C": ["C", "C_LOW"]}
    for base in ("A", "B", "C"):
        keys = base_patterns[base]
        agg_n = sum(pattern_summary.get(k, {}).get("trades", 0) for k in keys)
        agg_wins = sum(pattern_summary.get(k, {}).get("wins", 0) for k in keys)
        agg_net = sum(pattern_summary.get(k, {}).get("net", 0.0) for k in keys)
        wr = (agg_wins / agg_n) if agg_n else 0.0
        c1 = agg_n >= 5
        c2 = wr >= 0.55
        c3 = agg_net > 20.0
        decision = "SHIP" if (c1 and c2 and c3) else "HOLD"
        decisions[base] = decision
        print(f"| {base} | n={agg_n} wr={wr*100:.1f}% net={agg_net:+.1f}p | "
              f"{'✓' if c1 else '✗'} | {'✓' if c2 else '✗'} | {'✓' if c3 else '✗'} | "
              f"**{decision}** |")

    print("\n## Verdict\n")
    shipping = [base for base, d in decisions.items() if d == "SHIP"]
    if shipping:
        print(f"SHIP patterns: {', '.join(shipping)}")
        print(f"HOLD patterns: {', '.join(b for b in 'ABC' if b not in shipping) or '(none)'}")
        return 0
    print("No pattern validated. STOP and report.")
    return 2


if __name__ == "__main__":
    sys.exit(run())
