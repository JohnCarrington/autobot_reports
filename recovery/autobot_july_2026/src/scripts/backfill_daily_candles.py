#!/usr/bin/env python3
"""
One-shot: backfill /opt/tradingbot/data/candles/{PAIR}/{DATE}.csv from IG
/prices 5M history for the given date range (UTC). Writes the same schema
used by candle_archive (timestamp,open,high,low,close). Appends into
existing files without producing duplicates (matches on timestamp).

Usage:
  scripts/backfill_daily_candles.py FROM_DATE TO_DATE
  scripts/backfill_daily_candles.py 2026-04-11 2026-04-14
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Load .env so IG creds are available when run manually
from dotenv import load_dotenv
load_dotenv(REPO / ".env")

ARCHIVE_ROOT = Path(os.getenv("CANDLE_ARCHIVE_DIR", "/opt/tradingbot/data/candles"))
HEADER = ("timestamp", "open", "high", "low", "close")

# Epics for the CFD feed (history endpoint prefers CFD over SPREADBET).
EPICS = {
    "GBPUSD": "CS.D.GBPUSD.CFD.IP",
    "EURUSD": "CS.D.EURUSD.CFD.IP",
    "USDJPY": "CS.D.USDJPY.CFD.IP",
    "USDCAD": "CS.D.USDCAD.CFD.IP",
    "GBPJPY": "CS.D.GBPJPY.CFD.IP",
}


def _existing_timestamps(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open() as fh:
        return {row.get("timestamp", "") for row in csv.DictReader(fh) if row}


def _append_candle(path: Path, ts_iso: str, o: float, h: float, l: float, c: float) -> None:
    is_new = not path.exists() or path.stat().st_size == 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as fh:
        w = csv.writer(fh)
        if is_new:
            w.writerow(HEADER)
        w.writerow([ts_iso, o, h, l, c])


def backfill(pair: str, date_str: str, ig) -> int:
    """Fetch one UTC day of 5M prices via IG /prices and append to daily file."""
    epic = EPICS.get(pair)
    if not epic:
        print(f"  [skip] no epic mapping for {pair}")
        return 0
    start = f"{date_str} 00:00:00"
    end = f"{date_str} 23:55:00"
    try:
        resp = ig.fetch_historical_prices_by_epic_and_date_range(
            epic=epic, resolution="MINUTE_5", start_date=start, end_date=end,
        )
    except Exception as e:
        print(f"  [err]  {pair} {date_str}: {e}")
        return 0

    prices = resp.get("prices") if isinstance(resp, dict) else None
    if prices is None:
        # trading-ig lib shape: dataframe under "prices"
        prices = getattr(resp, "prices", None)
    if prices is None or len(prices) == 0:
        print(f"  [empty] {pair} {date_str}: no prices returned")
        return 0

    path = ARCHIVE_ROOT / pair.upper() / f"{date_str}.csv"
    existing = _existing_timestamps(path)

    written = 0
    try:
        rows_iter = prices.iterrows()
    except AttributeError:
        rows_iter = enumerate(prices)
    for _, row in rows_iter:
        try:
            ts = row.get("DateTime") or row.get("snapshotTime") or row.name
            if hasattr(ts, "isoformat"):
                ts_iso = ts.tz_localize(timezone.utc).isoformat() if ts.tzinfo is None else ts.astimezone(timezone.utc).isoformat()
            else:
                ts_iso = str(ts)
            # Prices are dict with bid/ask/last — use mid of bid/ask open/high/low/close
            def _mid(field):
                bid = row.get(("bid", field)) if isinstance(row, dict) else row["bid", field]
                ask = row.get(("ask", field)) if isinstance(row, dict) else row["ask", field]
                try: bid = float(bid)
                except: bid = None
                try: ask = float(ask)
                except: ask = None
                if bid is not None and ask is not None:
                    return (bid + ask) / 2
                return bid if bid is not None else ask
            o = _mid("Open")
            h = _mid("High")
            l = _mid("Low")
            c = _mid("Close")
            if None in (o, h, l, c):
                continue
        except Exception:
            continue

        if ts_iso in existing:
            continue
        _append_candle(path, ts_iso, o, h, l, c)
        existing.add(ts_iso)
        written += 1

    print(f"  {pair} {date_str}: +{written} rows (file has {len(existing)} total)")
    return written


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    from_s, to_s = sys.argv[1], sys.argv[2]
    d0 = datetime.strptime(from_s, "%Y-%m-%d").date()
    d1 = datetime.strptime(to_s, "%Y-%m-%d").date()
    if d1 < d0:
        print("FROM must be ≤ TO", file=sys.stderr)
        return 2

    import ig_auth
    ig, _, _ = ig_auth.get_ig_session()

    total = 0
    d = d0
    while d <= d1:
        date_str = d.isoformat()
        print(f"[{date_str}]")
        for pair in sorted(EPICS.keys()):
            total += backfill(pair, date_str, ig)
        d += timedelta(days=1)
    print(f"\nTotal rows written: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
