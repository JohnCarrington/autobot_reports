"""
validate_big_rev.py — backtest GBPUSD_BIG_REV over 2026-03-30 to
2026-04-25 weekdays. Two windows per day, single trade per window,
max two trades per day. Single exit at TP (opposite BB) or SL.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

REPO = Path("/opt/tradingbot")
sys.path.insert(0, str(REPO))

import gbpusd_big_rev as bigrev  # noqa: E402

PIP_SIZE = 1.0


def load_5m(date_str: str) -> pd.DataFrame:
    f = REPO / "data" / "candles" / "GBPUSD" / f"{date_str}.csv"
    if not f.exists():
        return pd.DataFrame()
    df = pd.read_csv(f)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def weekdays(start: str, end: str) -> List[str]:
    d0 = datetime.fromisoformat(start).date()
    d1 = datetime.fromisoformat(end).date()
    out: List[str] = []
    cur = d0
    while cur <= d1:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def to_bar(row: pd.Series) -> bigrev.Bar:
    return bigrev.Bar(
        timestamp=row["timestamp"].to_pydatetime(),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
    )


def first_hit_sl_or_tp(
    bars_after: List[pd.Series],
    direction: str, entry: float, sl: float, tp: float,
) -> Tuple[Optional[int], str, float]:
    """Walk forward bars; return (idx, reason, exit_price). SL priority on
    same-bar collision. If neither, return (None, "OPEN", last_close)."""
    for i, r in enumerate(bars_after):
        h, l = float(r["high"]), float(r["low"])
        if direction == "BUY":
            sl_hit = l <= sl
            tp_hit = h >= tp
        else:
            sl_hit = h >= sl
            tp_hit = l <= tp
        if sl_hit and tp_hit:
            return i, "SL", float(sl)
        if sl_hit:
            return i, "SL", float(sl)
        if tp_hit:
            return i, "TP", float(tp)
    if bars_after:
        last = bars_after[-1]
        return None, "OPEN", float(last["close"])
    return None, "OPEN", float(entry)


def run() -> int:
    days = weekdays("2026-03-30", "2026-04-25")
    print(f"Backtest days: {len(days)}", file=sys.stderr)

    ledger: List[Dict[str, Any]] = []

    for day in days:
        df = load_5m(day)
        if df.empty:
            continue

        # Warm BB(20,2) using prior day's last 20 closes
        prev_day = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
        prev_df = load_5m(prev_day)
        warmup_closes: List[float] = []
        if not prev_df.empty:
            warmup_closes = [float(c) for c in prev_df["close"].tail(20).tolist()]

        all_rows: List[pd.Series] = [df.iloc[i] for i in range(len(df))]

        # Per-window state
        windows = {
            "LONDON": bigrev._window_bounds_utc(
                datetime.fromisoformat(day).replace(tzinfo=timezone.utc), "LONDON",
            ),
            "NY": bigrev._window_bounds_utc(
                datetime.fromisoformat(day).replace(tzinfo=timezone.utc), "NY",
            ),
        }
        fired = {"LONDON": False, "NY": False}
        trades_today = 0

        # Sliding history: closes (for BB) and bars (for detector)
        running_closes: List[float] = list(warmup_closes)
        recent_bars: List[bigrev.Bar] = []

        # Maintain BB at the close of bar N-1 too — we need both bands at
        # bar N-1's close (to evaluate the pierce condition) and at bar N's
        # close (to evaluate the reversal-bar inside-band check + width).
        bb_at_bar_close: Dict[int, Tuple[float, float, float]] = {}

        # Skip-until-idx while a trade is open: walk-forward already handled
        # by looking up the exit bar index after a fire.
        skip_until_idx: Optional[int] = None

        for i, row in enumerate(all_rows):
            ts = row["timestamp"].to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            close_v = float(row["close"])
            running_closes.append(close_v)
            recent_bars.append(to_bar(row))
            if len(recent_bars) > 4:
                recent_bars = recent_bars[-4:]

            # Update BB at this bar's close
            if len(running_closes) >= 20:
                bb_at_bar_close[i] = bigrev.bb_20_2(running_closes)

            # Window check
            window = bigrev.current_window_label(ts)
            if window is None:
                continue
            if fired[window]:
                continue
            if trades_today >= 2:
                continue
            # Mid-trade — skip
            if skip_until_idx is not None and i < skip_until_idx:
                continue
            if skip_until_idx is not None and i >= skip_until_idx:
                skip_until_idx = None

            # Need BB at this bar's close AND at the prior bar's close
            if i not in bb_at_bar_close or (i - 1) not in bb_at_bar_close:
                continue
            if len(recent_bars) < 2:
                continue

            bb_l_n, bb_m_n, bb_u_n = bb_at_bar_close[i]
            bb_l_nm1, _bb_m_nm1, bb_u_nm1 = bb_at_bar_close[i - 1]

            match = bigrev.detect_big_rev(
                recent_bars,
                bb_u_n, bb_l_n, bb_m_n,
                bb_u_nm1, bb_l_nm1,
                PIP_SIZE,
            )
            if match is None:
                continue

            # Walk forward to SL or TP
            forward = all_rows[i + 1:]
            exit_idx, exit_reason, exit_price = first_hit_sl_or_tp(
                forward, match.direction, match.entry_price,
                match.sl_price, match.tp_price,
            )
            pnl = (
                (exit_price - match.entry_price) / PIP_SIZE if match.direction == "BUY"
                else (match.entry_price - exit_price) / PIP_SIZE
            )
            exit_bar = (
                forward[exit_idx] if exit_idx is not None
                else (forward[-1] if forward else row)
            )
            ledger.append({
                "date": day,
                "window": window,
                "fire_time": ts.strftime("%H:%M"),
                "direction": match.direction,
                "entry": round(match.entry_price, 1),
                "sl": round(match.sl_price, 1),
                "tp": round(match.tp_price, 1),
                "sl_pips": round(match.sl_pips, 1),
                "tp_pips": round(match.tp_pips, 1),
                "bb_width_pips": round(match.bb_width_pips, 1),
                "exit_time": exit_bar["timestamp"].isoformat(),
                "exit_price": round(exit_price, 1),
                "exit_reason": exit_reason,
                "pnl_pips": round(pnl, 1),
                "notes": match.notes,
            })
            fired[window] = True
            trades_today += 1
            # Skip until the trade resolves — find the next bar after exit
            if exit_idx is not None:
                skip_until_idx = i + 1 + exit_idx + 1
            else:
                skip_until_idx = len(all_rows)

    # Save CSV
    out_path = REPO / "data" / "audit_big_rev" / "ledger.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger:
        cols = list(ledger[0].keys())
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(ledger)
    print(f"Ledger saved: {out_path} ({len(ledger)} trades)", file=sys.stderr)

    # Print ledger as markdown
    print("\n## Per-trade ledger\n")
    if not ledger:
        print("(no trades fired)")
    else:
        cols = ["date", "window", "fire_time", "direction", "entry", "sl", "tp",
                "sl_pips", "tp_pips", "bb_width_pips", "exit_time", "exit_reason", "pnl_pips"]
        print("| " + " | ".join(cols) + " |")
        print("|" + "|".join("---" for _ in cols) + "|")
        for r in ledger:
            print("| " + " | ".join(
                str(r[c])[:19] if c == "exit_time" else str(r[c]) for c in cols
            ) + " |")

    # Aggregates
    n = len(ledger)
    wins = [r for r in ledger if r["pnl_pips"] > 0]
    losses = [r for r in ledger if r["pnl_pips"] <= 0]
    win_rate = (len(wins) / n) if n else 0.0
    avg_winner = (sum(r["pnl_pips"] for r in wins) / len(wins)) if wins else 0.0
    avg_loser = (sum(r["pnl_pips"] for r in losses) / len(losses)) if losses else 0.0
    median_winner = 0.0
    if wins:
        ws = sorted(r["pnl_pips"] for r in wins)
        m = len(ws)
        median_winner = ws[m // 2] if m % 2 == 1 else (ws[m // 2 - 1] + ws[m // 2]) / 2.0
    net = sum(r["pnl_pips"] for r in ledger)

    print("\n## Aggregate stats\n")
    print(f"- Trades fired: {n}")
    print(f"- Trading days: {len(days)}")
    print(f"- Trades per day average: {n/len(days):.2f}")
    print(f"- Wins / losses: {len(wins)} / {len(losses)}")
    print(f"- Win rate: {win_rate*100:.1f}%")
    print(f"- Average winner: {avg_winner:+.1f}p")
    print(f"- Average loser: {avg_loser:+.1f}p")
    print(f"- Median winner: {median_winner:+.1f}p")
    print(f"- Net P&L: {net:+.1f}p")

    # Decision (relaxed thresholds per 2026-04-25 re-run directive)
    print("\n## Ship criteria\n")
    c1 = n >= 8
    c2 = win_rate >= 0.50
    c3 = avg_winner >= 20.0    # relaxed from 25 to match relaxed entry signal
    c4 = net > 80.0            # relaxed from 100 same reasoning
    print(f"| criterion | requirement | actual | pass |")
    print(f"|---|---|---|---|")
    print(f"| trades ≥ 8 | ≥ 8 | {n} | {'✓' if c1 else '✗'} |")
    print(f"| win rate ≥ 50% | ≥ 50% | {win_rate*100:.1f}% | {'✓' if c2 else '✗'} |")
    print(f"| avg winner ≥ 20p | ≥ 20p | {avg_winner:+.1f}p | {'✓' if c3 else '✗'} |")
    print(f"| net P&L > +80p | > +80p | {net:+.1f}p | {'✓' if c4 else '✗'} |")

    print()
    if not c1:
        print(f"Decision: TOO TIGHT — only {n} trades in 20 days. STOP and report.")
        verdict = "TOO_TIGHT"
    elif not c3:
        print(f"Decision: AVG WINNER TOO SMALL ({avg_winner:.1f}p < 25p). STOP and report.")
        verdict = "WINNERS_TOO_SMALL"
    elif (not c2) and c3 and c4:
        print(f"Decision: WR<50% but expectancy strong (avg_winner {avg_winner:.1f}p, net {net:.1f}p). FLAG and ask.")
        verdict = "FLAG"
    elif c1 and c2 and c3 and c4:
        print("Decision: ALL CRITERIA MET — SHIP")
        verdict = "SHIP"
    else:
        print(f"Decision: criteria not met — STOP and report")
        verdict = "HOLD"

    if verdict != "SHIP":
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    run()
