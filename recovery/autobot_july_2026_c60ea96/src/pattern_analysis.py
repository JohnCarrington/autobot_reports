#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pattern_analysis.py — Analyse sweep journal CSVs by pattern type.

Usage:
    python3 pattern_analysis.py              # all data
    python3 pattern_analysis.py --days 7     # last 7 days
    python3 pattern_analysis.py --symbol GBPUSD
"""

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path("/opt/tradingbot/logs")

PATTERN_LABELS = {
    "single_candle_spike": "P0  Spike",
    "bb_pierce":           "P1  BB Pierce",
    "curve":               "P2  Curve",
    "unknown":             "??  Unknown",
}


def _classify_pattern(row: dict) -> str:
    """Derive pattern type from the 'pattern' column or reason heuristics."""
    pat = (row.get("pattern") or "").strip()
    if pat in ("single_candle_spike", "bb_pierce", "curve"):
        return pat

    # Fallback: infer from blocked_reason or other fields for older CSVs
    reason = (row.get("blocked_reason") or "").lower()
    if "spike" in reason:
        return "single_candle_spike"
    if "curve" in reason:
        return "curve"
    if "bb_pierce" in reason:
        return "bb_pierce"

    return "unknown"


def _parse_float(val: str) -> float | None:
    try:
        v = float(val)
        return v
    except (TypeError, ValueError):
        return None


ARTEFACT_THRESHOLD_PIPS = 500


def load_trades(days: int | None, symbol: str | None) -> tuple[list[dict], list[dict]]:
    """Load taken LIQUIDITY_SWEEP trades from journal CSVs.

    Returns (trades, artefacts) where artefacts have abs(pnl) > 500 pips.
    """
    cutoff = None
    if days is not None:
        cutoff = datetime.utcnow().date() - timedelta(days=days)

    files = sorted(LOG_DIR.glob("sweep_journal_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].csv"))
    trades: list[dict] = []
    artefacts: list[dict] = []

    for fpath in files:
        # Extract date from filename
        try:
            date_str = fpath.stem.replace("sweep_journal_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if cutoff and file_date < cutoff:
            continue

        try:
            with open(fpath, newline="") as fh:
                for row in csv.DictReader(fh):
                    taken = (row.get("taken") or "").strip()
                    if taken != "True":
                        continue
                    mode = (row.get("mode") or "").strip()
                    if mode != "LIQUIDITY_SWEEP":
                        continue
                    pnl = _parse_float(row.get("pnl_pips", ""))
                    if pnl is None:
                        continue  # still open or missing exit
                    if symbol and (row.get("symbol") or "").upper() != symbol.upper():
                        continue

                    row["_pnl"] = pnl
                    row["_date"] = file_date
                    row["_pattern"] = _classify_pattern(row)

                    if abs(pnl) > ARTEFACT_THRESHOLD_PIPS:
                        artefacts.append(row)
                    else:
                        trades.append(row)
        except Exception:
            continue

    return trades, artefacts


def _stats(trades: list[dict]) -> dict:
    """Compute stats for a group of trades."""
    if not trades:
        return None

    pnls = [t["_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = len(pnls)
    win_rate = len(wins) / total if total else 0.0
    loss_rate = 1.0 - win_rate
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    ev = (win_rate * avg_win) - (loss_rate * avg_loss)

    close_reasons = Counter(t.get("close_reason", "?") for t in trades)
    most_common_close = close_reasons.most_common(1)[0][0] if close_reasons else "?"

    best = max(trades, key=lambda t: t["_pnl"])
    worst = min(trades, key=lambda t: t["_pnl"])

    return {
        "total": total,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "ev": ev,
        "most_common_close": most_common_close,
        "best_pnl": best["_pnl"],
        "best_sym": best.get("symbol", "?"),
        "best_date": str(best["_date"]),
        "worst_pnl": worst["_pnl"],
        "worst_sym": worst.get("symbol", "?"),
        "worst_date": str(worst["_date"]),
        "net_pips": sum(pnls),
    }


# ── Table rendering ──────────────────────────────────────────────────

HEADER_MAIN = (
    "{:<16s} {:>6s} {:>8s} {:>9s} {:>9s} {:>8s} {:>8s}  {:<24s} {:<22s} {:<22s}"
)
ROW_MAIN = (
    "{:<16s} {:>6d} {:>7.0f}% {:>8.1f}p {:>8.1f}p {:>7.1f}p {:>7.1f}p  {:<24s} {:<22s} {:<22s}"
)


def _print_table(title: str, grouped: dict[str, list[dict]]):
    """Print a stats table for grouped trades."""
    print(f"\n{'=' * 100}")
    print(f"  {title}")
    print(f"{'=' * 100}")
    print(
        HEADER_MAIN.format(
            "Pattern", "Trades", "WinRate", "AvgWin", "AvgLoss",
            "EV", "Net", "Top Close", "Best Trade", "Worst Trade",
        )
    )
    print("-" * 100)

    order = ["single_candle_spike", "bb_pierce", "curve", "unknown"]
    for key in order:
        trades = grouped.get(key)
        if not trades:
            continue
        s = _stats(trades)
        if not s:
            continue
        label = PATTERN_LABELS.get(key, key)
        best_str = f"+{s['best_pnl']:.1f}p {s['best_sym']} {s['best_date']}"
        worst_str = f"{s['worst_pnl']:.1f}p {s['worst_sym']} {s['worst_date']}"
        print(
            ROW_MAIN.format(
                label,
                s["total"],
                s["win_rate"] * 100,
                s["avg_win"],
                s["avg_loss"],
                s["ev"],
                s["net_pips"],
                s["most_common_close"][:24],
                best_str[:22],
                worst_str[:22],
            )
        )

    # Totals
    all_trades = [t for ts in grouped.values() for t in ts]
    if all_trades:
        s = _stats(all_trades)
        if s:
            print("-" * 100)
            best_str = f"+{s['best_pnl']:.1f}p {s['best_sym']} {s['best_date']}"
            worst_str = f"{s['worst_pnl']:.1f}p {s['worst_sym']} {s['worst_date']}"
            print(
                ROW_MAIN.format(
                    "ALL",
                    s["total"],
                    s["win_rate"] * 100,
                    s["avg_win"],
                    s["avg_loss"],
                    s["ev"],
                    s["net_pips"],
                    s["most_common_close"][:24],
                    best_str[:22],
                    worst_str[:22],
                )
            )


def main():
    parser = argparse.ArgumentParser(description="Sweep pattern performance analysis")
    parser.add_argument("--days", type=int, default=None, help="Limit to last N days")
    parser.add_argument("--symbol", type=str, default=None, help="Filter to single symbol")
    args = parser.parse_args()

    trades, artefacts = load_trades(args.days, args.symbol)
    if not trades and not artefacts:
        print("No completed sweep trades found.")
        return

    if artefacts:
        print(f"\nExcluded artefacts: {len(artefacts)} trades (abs pnl > {ARTEFACT_THRESHOLD_PIPS} pips)")
        for a in artefacts:
            print(f"  {a['_date']}  {a.get('symbol','?'):<8s}  pnl={a['_pnl']:+.1f}p  close={a.get('close_reason','?')}")

    if not trades:
        print("No valid sweep trades remaining after artefact filter.")
        return

    date_range = f"{min(t['_date'] for t in trades)} to {max(t['_date'] for t in trades)}"
    sym_filter = f" | symbol={args.symbol.upper()}" if args.symbol else ""
    print(f"\nSweep Pattern Analysis  |  {len(trades)} trades  |  {date_range}{sym_filter}")

    # ── By pattern ───────────────────────────────────────────────────
    by_pattern: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_pattern[t["_pattern"]].append(t)
    _print_table("PERFORMANCE BY PATTERN", dict(by_pattern))

    # ── By symbol × pattern ──────────────────────────────────────────
    symbols = sorted(set(t.get("symbol", "?") for t in trades))
    for sym in symbols:
        sym_trades = [t for t in trades if t.get("symbol") == sym]
        by_pat: dict[str, list[dict]] = defaultdict(list)
        for t in sym_trades:
            by_pat[t["_pattern"]].append(t)
        _print_table(f"{sym}  ({len(sym_trades)} trades)", dict(by_pat))

    # ── Symbol summary ───────────────────────────────────────────────
    print(f"\n{'=' * 100}")
    print("  SYMBOL SUMMARY")
    print(f"{'=' * 100}")
    print(f"{'Symbol':<10s} {'Trades':>6s} {'WinRate':>8s} {'EV':>8s} {'Net':>8s}")
    print("-" * 44)
    for sym in symbols:
        sym_trades = [t for t in trades if t.get("symbol") == sym]
        s = _stats(sym_trades)
        if s:
            print(f"{sym:<10s} {s['total']:>6d} {s['win_rate']*100:>7.0f}% {s['ev']:>7.1f}p {s['net_pips']:>7.1f}p")
    all_s = _stats(trades)
    if all_s:
        print("-" * 44)
        print(f"{'TOTAL':<10s} {all_s['total']:>6d} {all_s['win_rate']*100:>7.0f}% {all_s['ev']:>7.1f}p {all_s['net_pips']:>7.1f}p")

    print()


if __name__ == "__main__":
    main()
