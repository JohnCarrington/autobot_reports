#!/usr/bin/env python3
"""Fetch IG DEMO historical bid/ask OHLC for GBPUSD + EURUSD.

Reuses ig_auth for the authenticated IGService client. Writes one CSV per
(epic, day, resolution) under ./data/, and appends an entry to
allowance_log.jsonl on every REST call (remainingAllowance from IG's own
response — the true weekly cap, not our local safety budget).

Read-only: no orders, no session mutation, no config writes. Never prints
credentials or the IG session tokens.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, "/opt/tradingbot")

from ig_auth import get_ig_session  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
ALLOWANCE_LOG = HERE / "allowance_log.jsonl"

EPICS = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
}


def _log_allowance(epic: str, resolution: str, start: str, end: str,
                   rows: int, allowance: dict, note: str = "") -> None:
    payload = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "epic": epic,
        "resolution": resolution,
        "from": start,
        "to": end,
        "rows": rows,
        "remainingAllowance": allowance.get("remainingAllowance"),
        "totalAllowance": allowance.get("totalAllowance"),
        "allowanceExpiry": allowance.get("allowanceExpiry"),
        "note": note,
    }
    with open(ALLOWANCE_LOG, "a") as fh:
        fh.write(json.dumps(payload) + "\n")


def _extract_allowance(hist) -> dict:
    """Pull allowance dict from a trading_ig response."""
    if isinstance(hist, dict):
        alw = hist.get("allowance") or {}
        if isinstance(alw, dict):
            return alw
    return {}


def _extract_prices_df(hist):
    """Return the DataFrame carried by hist['prices']."""
    import pandas as pd  # local import — the fetcher script requires pandas

    if isinstance(hist, tuple) and len(hist) == 2:
        hist = hist[1]
    if not isinstance(hist, dict):
        return None
    prices = hist.get("prices")
    if prices is None:
        return None
    if hasattr(prices, "columns") and hasattr(prices, "iterrows"):
        return prices
    if isinstance(prices, list):
        return pd.DataFrame(prices)
    return None


def _df_to_bidask_rows(df):
    """Yield rows keyed on snapshotTimeUTC.

    We pass format=ig.flat_prices so the DataFrame is FLAT, index is
    'DateTime' (from snapshotTimeUTC) and columns are 'open.bid',
    'open.ask', 'high.bid', 'high.ask', 'low.bid', 'low.ask',
    'close.bid', 'close.ask', 'volume'.
    """
    import pandas as pd

    if df is None or df.empty:
        return

    df2 = df.reset_index()
    ts_col = df2.columns[0]
    for _, row in df2.iterrows():
        ts = row[ts_col]
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if isinstance(ts, dt.datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        out = {"timestamp": ts.isoformat() if isinstance(ts, dt.datetime) else str(ts)}
        for side in ("bid", "ask"):
            for f in ("open", "high", "low", "close"):
                key = f"{f}.{side}"
                val = row.get(key)
                out[f"{side}_{f}"] = float(val) if val is not None and val == val else None
        vol = row.get("volume") if "volume" in df2.columns else None
        out["volume"] = float(vol) if vol is not None and vol == vol else None
        yield out


def _fetch_one(ig, epic: str, resolution: str,
               start: dt.datetime, end: dt.datetime, note: str = "") -> Dict:
    """Fetch one date range via IG v3 /prices/{epic}. Returns rows + allowance."""
    start_s = start.strftime("%Y-%m-%dT%H:%M:%S")
    end_s = end.strftime("%Y-%m-%dT%H:%M:%S")
    hist = ig.fetch_historical_prices_by_epic(
        epic,
        resolution=resolution,
        start_date=start_s,
        end_date=end_s,
        pagesize=1000,
        wait=0,
        format=ig.flat_prices,
    )
    df = _extract_prices_df(hist)
    rows = list(_df_to_bidask_rows(df)) if df is not None else []
    alw = {}
    if isinstance(hist, dict):
        meta = hist.get("metadata") or {}
        alw = meta.get("allowance") or {}
    _log_allowance(epic, resolution, start_s, end_s, len(rows), alw, note=note)
    return {"rows": rows, "allowance": alw}


def _write_csv(rows: List[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out.write_text("timestamp,bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,volume\n")
        return
    fields = ["timestamp",
              "bid_open", "bid_high", "bid_low", "bid_close",
              "ask_open", "ask_high", "ask_low", "ask_close",
              "volume"]
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _day_range_utc(day: dt.date):
    start = dt.datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1) - dt.timedelta(seconds=1)
    return start, end


def cmd_probe(args):
    """Cheap 1-bar probe to read the current allowance headers."""
    ig, _, _ = get_ig_session()
    epic = EPICS.get(args.symbol.upper(), args.symbol)
    fn = getattr(ig, "fetch_historical_prices_by_epic_and_num_points", None)
    if fn is None:
        raise SystemExit("IGService missing fetch_historical_prices_by_epic_and_num_points")
    hist = fn(epic, "MINUTE", 1, format=ig.flat_prices)
    alw = _extract_allowance(hist)
    df = _extract_prices_df(hist)
    rows = list(_df_to_bidask_rows(df)) if df is not None else []
    _log_allowance(epic, "MINUTE", "probe-1bar", "probe-1bar", len(rows), alw, note="probe")
    print(json.dumps({
        "epic": epic,
        "rows_returned": len(rows),
        "remainingAllowance": alw.get("remainingAllowance"),
        "totalAllowance": alw.get("totalAllowance"),
        "allowanceExpiry": alw.get("allowanceExpiry"),
        "sample": rows[:1],
    }, indent=2, default=str))


def cmd_day(args):
    """Fetch one specific UTC day at a given resolution for both epics (or one)."""
    day = dt.date.fromisoformat(args.date)
    start, end = _day_range_utc(day)
    resolution = args.resolution.upper()
    symbols = [args.symbol.upper()] if args.symbol else ["GBPUSD", "EURUSD"]
    ig, _, _ = get_ig_session()
    for sym in symbols:
        epic = EPICS[sym]
        out = DATA_DIR / sym / f"{day.isoformat()}_{resolution.lower()}_bidask.csv"
        if out.exists() and not args.force:
            print(f"SKIP existing {out}")
            continue
        print(f"FETCH {sym} {resolution} {day.isoformat()}")
        result = _fetch_one(ig, epic, resolution, start, end, note=f"day={day.isoformat()}")
        _write_csv(result["rows"], out)
        alw = result["allowance"]
        print(f"  rows={len(result['rows'])}  remaining={alw.get('remainingAllowance')}"
              f"  total={alw.get('totalAllowance')}  -> {out}")
        time.sleep(0.4)


def cmd_range(args):
    """Fetch a date range weekday-by-weekday at a given resolution."""
    start_d = dt.date.fromisoformat(args.start)
    end_d = dt.date.fromisoformat(args.end)
    resolution = args.resolution.upper()
    symbols = [args.symbol.upper()] if args.symbol else ["GBPUSD", "EURUSD"]
    ig, _, _ = get_ig_session()
    days = []
    d = start_d
    while d <= end_d:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += dt.timedelta(days=1)
    for day in days:
        start, end = _day_range_utc(day)
        for sym in symbols:
            epic = EPICS[sym]
            out = DATA_DIR / sym / f"{day.isoformat()}_{resolution.lower()}_bidask.csv"
            if out.exists() and not args.force:
                print(f"SKIP existing {out}")
                continue
            print(f"FETCH {sym} {resolution} {day.isoformat()}")
            result = _fetch_one(ig, epic, resolution, start, end,
                                note=f"range {start_d}..{end_d} day={day.isoformat()}")
            _write_csv(result["rows"], out)
            alw = result["allowance"]
            print(f"  rows={len(result['rows'])}  remaining={alw.get('remainingAllowance')}"
                  f"  total={alw.get('totalAllowance')}  -> {out}")
            remaining = alw.get("remainingAllowance")
            try:
                if remaining is not None and int(remaining) < args.stop_below:
                    print(f"STOP — remainingAllowance={remaining} < {args.stop_below}")
                    return
            except (TypeError, ValueError):
                pass
            time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_probe = sub.add_parser("probe", help="1-bar probe to read allowance")
    p_probe.add_argument("--symbol", default="GBPUSD")
    p_probe.set_defaults(func=cmd_probe)

    p_day = sub.add_parser("day", help="fetch one UTC day")
    p_day.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_day.add_argument("--resolution", default="MINUTE",
                       help="MINUTE, MINUTE_5, MINUTE_15, HOUR, etc")
    p_day.add_argument("--symbol", help="GBPUSD or EURUSD (default: both)")
    p_day.add_argument("--force", action="store_true")
    p_day.set_defaults(func=cmd_day)

    p_range = sub.add_parser("range", help="fetch a weekday range")
    p_range.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_range.add_argument("--end", required=True, help="YYYY-MM-DD")
    p_range.add_argument("--resolution", default="MINUTE_5")
    p_range.add_argument("--symbol", help="GBPUSD or EURUSD (default: both)")
    p_range.add_argument("--stop-below", type=int, default=500,
                         help="stop if remainingAllowance drops below")
    p_range.add_argument("--force", action="store_true")
    p_range.set_defaults(func=cmd_range)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
