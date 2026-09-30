#!/usr/bin/env python3
"""
backfill_signal_log.py — Parse trade_log.csv into signal_log_backfill.jsonl
Pairs OPEN/CLOSE rows by deal_id, derives session/strategy, outputs JSONL.
"""

import csv
import json
import uuid
import sys
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

INPUT = Path("/opt/tradingbot/trades/trade_log.csv")
OUTPUT = Path("/opt/tradingbot/data/signal_log_backfill.jsonl")


def parse_timestamp(ts_str: str) -> datetime:
    ts_str = ts_str.strip()
    # Handle both +00:00 and Z suffixes
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def derive_session(dt: datetime) -> str:
    h = dt.astimezone(timezone.utc).hour
    if 22 <= h or h < 6:
        return "Asian"
    elif 6 <= h < 12:
        return "London"
    elif 12 <= h < 17:
        return "New York"
    else:
        return "London"


def extract_pair(epic: str) -> str:
    """Extract pair name from IG epic like CS.D.GBPUSD.TODAY.IP"""
    parts = epic.split(".")
    for p in parts:
        if len(p) == 6 and p.isalpha() and p.isupper():
            return p
    # Fallback: try 3rd segment
    if len(parts) >= 3:
        return parts[2]
    return epic


def classify_strategy(reason: str) -> str:
    r = reason.lower()
    # Order matters — more specific patterns first
    if "briefing" in r and ("liq" in r or "liquidity" in r):
        return "BRIEFING_LIQUIDITY"
    if "briefing" in r and "sweep" in r:
        return "BRIEFING_SWEEP"
    if "briefing" in r:
        return "BRIEFING_LIQUIDITY"
    if "window_sweep" in r:
        return "WINDOW_SWEEP"
    if "liq_sweep" in r or "liquidity_sweep" in r or "liq sweep" in r:
        return "LIQUIDITY_SWEEP"
    if "3co" in r or "three_co" in r:
        return "3CO"
    if "news" in r:
        return "NEWS_STRATEGY"
    if "range" in r or "intra_touch" in r:
        return "RANGE_REVERSION"
    if "trend" in r or "ema_pullback" in r or "pullback" in r:
        return "TREND_FOLLOW"
    if "sweep" in r:
        return "WINDOW_SWEEP"
    # Legacy patterns from early bot
    if "band_touch" in r or "fade" in r or "reject" in r:
        return "RANGE_REVERSION"
    if "breakout" in r or "run_down" in r or "run_up" in r:
        return "LIQUIDITY_SWEEP"
    if "confirm_momentum" in r or "entry_after_confirm" in r:
        return "LIQUIDITY_SWEEP"
    return "UNKNOWN"


def parse_row(fields: list) -> dict:
    """Parse a CSV row, handling both old format (no OPEN/CLOSE) and new format."""
    # New format: timestamp, event, epic, direction, size, open_price, close_price, ...
    # Old format: timestamp, epic, direction, size, open_price, close_price, ...
    # Detect by checking if field[1] is OPEN or CLOSE
    if len(fields) < 10:
        return None

    if fields[1].strip() in ("OPEN", "CLOSE"):
        # New format
        return {
            "timestamp": fields[0].strip(),
            "event": fields[1].strip(),
            "epic": fields[2].strip(),
            "direction": fields[3].strip(),
            "size": fields[4].strip(),
            "open_price": fields[5].strip(),
            "close_price": fields[6].strip(),
            "pnl_pips": fields[7].strip(),
            "deal_id": fields[10].strip() if len(fields) > 10 else "",
            "account_id": fields[12].strip() if len(fields) > 12 else "",
            "reason": fields[13].strip() if len(fields) > 13 else "",
            "hold_time": fields[14].strip() if len(fields) > 14 else "",
        }
    else:
        # Old format (close-only rows) — no OPEN/CLOSE column
        return {
            "timestamp": fields[0].strip(),
            "event": "CLOSE",  # These are close records
            "epic": fields[1].strip(),
            "direction": fields[2].strip(),
            "size": fields[3].strip(),
            "open_price": fields[4].strip(),
            "close_price": fields[5].strip(),
            "pnl_pips": fields[6].strip(),
            "deal_id": fields[9].strip() if len(fields) > 9 else "",
            "account_id": fields[11].strip() if len(fields) > 11 else "",
            "reason": fields[12].strip() if len(fields) > 12 else "",
            "hold_time": fields[13].strip() if len(fields) > 13 else "",
        }


def main():
    if not INPUT.exists():
        print(f"ERROR: {INPUT} not found", file=sys.stderr)
        sys.exit(1)

    # Parse all rows
    opens = {}   # deal_id -> row
    closes = {}  # deal_id -> row
    orphan_closes = []  # close rows without matching opens

    with open(INPUT, "r") as f:
        reader = csv.reader(f)
        for line_no, fields in enumerate(reader, 1):
            row = parse_row(fields)
            if row is None:
                continue
            deal_id = row["deal_id"]
            if not deal_id:
                continue

            if row["event"] == "OPEN":
                opens[deal_id] = row
            elif row["event"] == "CLOSE":
                closes[deal_id] = row

    # Pair trades
    trades = []
    paired_deals = set()

    for deal_id, close_row in closes.items():
        open_row = opens.get(deal_id)
        if open_row:
            paired_deals.add(deal_id)
            try:
                ts_open = parse_timestamp(open_row["timestamp"])
                ts_close = parse_timestamp(close_row["timestamp"])
                entry_price = float(open_row["open_price"])
                close_price = float(close_row["close_price"])
                pnl = float(close_row["pnl_pips"])
                hold_secs = float(close_row["hold_time"]) if close_row["hold_time"] else (ts_close - ts_open).total_seconds()
                reason_open = open_row["reason"]
                reason_close = close_row["reason"]
                epic = open_row["epic"]
                direction = open_row["direction"]
            except (ValueError, KeyError) as e:
                print(f"  SKIP deal {deal_id}: {e}", file=sys.stderr)
                continue
        else:
            # Orphan close — old format, no OPEN row. Reconstruct from close row.
            try:
                ts_close = parse_timestamp(close_row["timestamp"])
                entry_price = float(close_row["open_price"])
                close_price = float(close_row["close_price"])
                pnl = float(close_row["pnl_pips"])
                hold_secs = float(close_row["hold_time"]) if close_row["hold_time"] else 0
                ts_open = datetime.fromtimestamp(
                    ts_close.timestamp() - hold_secs, tz=timezone.utc
                ) if hold_secs > 0 else ts_close
                reason_open = close_row["reason"]  # Only have close reason
                reason_close = close_row["reason"]
                epic = close_row["epic"]
                direction = close_row["direction"]
            except (ValueError, KeyError) as e:
                print(f"  SKIP orphan deal {deal_id}: {e}", file=sys.stderr)
                continue

        pair = extract_pair(epic)
        session = derive_session(ts_open)
        strategy = classify_strategy(reason_open)
        duration_min = round(hold_secs / 60, 1)

        # Sanity filter: reject trades with physically impossible PnL.
        # IG quotes all pairs as integers (e.g. GBPUSD 13490 = 1.3490).
        # Max realistic move is ~200 pips per trade. Corrupt rows from
        # cross-epic price contamination produce 1000+ pip swings.
        if abs(pnl) > 200:
            print(f"  SKIP corrupt {pair} pnl={pnl:.1f} entry={entry_price} close={close_price} deal={deal_id}", file=sys.stderr)
            continue

        trade = {
            "id": str(uuid.uuid4()),
            "source": "backfill",
            "timestamp_open": ts_open.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timestamp_close": ts_close.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "epic": epic,
            "pair": pair,
            "direction": direction,
            "strategy": strategy,
            "strategy_raw": reason_open,
            "session": session,
            "entry": entry_price,
            "close_price": close_price,
            "pnl_pips": round(pnl, 2),
            "duration_minutes": duration_min,
            "close_reason": reason_close,
            # Schema-compatible null fields
            "bb_width_pips": None,
            "atr_pips": None,
            "bias_confidence": None,
            "session_bias": None,
            "daily_bias": None,
            "ema_aligned": None,
            "macd_direction": None,
            "sl_pips": None,
            "tp1_pips": None,
        }
        trades.append(trade)

    # Sort by open timestamp
    trades.sort(key=lambda t: t["timestamp_open"])

    # Write output
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")

    # Summary
    wins = [t for t in trades if t["pnl_pips"] > 0]
    losses = [t for t in trades if t["pnl_pips"] <= 0]
    total_pnl = sum(t["pnl_pips"] for t in trades)

    print(f"\n{'='*60}")
    print(f"  BACKFILL SUMMARY")
    print(f"{'='*60}")
    print(f"  Input rows:       {len(opens) + len(closes)}")
    print(f"  Completed trades: {len(trades)}")
    print(f"  Corrupt skipped:  {len(paired_deals) + (len(closes) - len(paired_deals)) - len(trades)}")
    print(f"  Total trades:     {len(trades)}")
    print(f"  Wins:             {len(wins)}")
    print(f"  Losses:           {len(losses)}")
    print(f"  Total PnL:        {total_pnl:+.1f} pips")
    print(f"  Date range:       {trades[0]['timestamp_open'][:10]} → {trades[-1]['timestamp_close'][:10]}")

    # By strategy
    by_strat = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        s = by_strat[t["strategy"]]
        s["count"] += 1
        s["pnl"] += t["pnl_pips"]
        if t["pnl_pips"] > 0:
            s["wins"] += 1

    print(f"\n  {'Strategy':<22} {'Trades':>6} {'Wins':>6} {'WR':>6} {'PnL':>10}")
    print(f"  {'-'*52}")
    for strat in sorted(by_strat, key=lambda k: by_strat[k]["count"], reverse=True):
        s = by_strat[strat]
        wr = (s["wins"] / s["count"] * 100) if s["count"] else 0
        print(f"  {strat:<22} {s['count']:>6} {s['wins']:>6} {wr:>5.0f}% {s['pnl']:>+9.1f}")

    # By session
    by_sess = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        s = by_sess[t["session"]]
        s["count"] += 1
        s["pnl"] += t["pnl_pips"]
        if t["pnl_pips"] > 0:
            s["wins"] += 1

    print(f"\n  {'Session':<22} {'Trades':>6} {'Wins':>6} {'WR':>6} {'PnL':>10}")
    print(f"  {'-'*52}")
    for sess in ["Asian", "London", "New York"]:
        s = by_sess[sess]
        if s["count"] == 0:
            continue
        wr = (s["wins"] / s["count"] * 100) if s["count"] else 0
        print(f"  {sess:<22} {s['count']:>6} {s['wins']:>6} {wr:>5.0f}% {s['pnl']:>+9.1f}")

    print(f"\n  Output: {OUTPUT}")
    print(f"  Lines:  {len(trades)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
