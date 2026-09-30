#!/usr/bin/env python3
"""
fetch_histdata_ticks.py — Download tick data from HistData.com

Downloads Generic ASCII tick data ZIPs for a given pair/year/months,
extracts the CSVs, converts to a unified format, and writes a single
output file.

HistData Generic ASCII tick format:
    DateTime (YYYYMMDD HHmmssSSS), Bid, Ask, Volume
    Prices are in decimal forex format (e.g. 1.34250)

Output format (default, decimal — matches existing GBPUSD_ticks_2026.csv):
    timestamp,bid,ask,mid
    2026-03-23 00:00:00.123,1.34250,1.34258,1.34254

Pass --ig-points to emit 3-column IG spread-bet points instead.

Usage:
    python3 fetch_histdata_ticks.py
    python3 fetch_histdata_ticks.py --pair GBPUSD --year 2026 --months 3 4
"""
import argparse
import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/tick-data-quotes"
OUT_DIR = Path("/opt/tradingbot/data/ticks")

# IG spread-bet multiplier: GBPUSD 1.34250 → 13425.0
PAIR_MULTIPLIERS = {
    "GBPUSD": 10000,
    "EURUSD": 10000,
    "USDCAD": 10000,
    "EURGBP": 10000,
    "AUDUSD": 10000,
    "USDJPY": 100,
    "GBPJPY": 100,
}


def download_month(session: requests.Session, pair: str, year: int, month: int) -> bytes:
    """Download a single month's tick ZIP from HistData.com."""
    page_url = f"{BASE_URL}/{pair}/{year}/{month}"
    print(f"  GET  {page_url}")
    resp = session.get(page_url, timeout=30)
    resp.raise_for_status()

    # Parse form to find hidden token field
    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form", id="file_down")
    if not form:
        raise RuntimeError(f"Could not find download form on {page_url}")

    # Collect all hidden inputs
    payload = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name:
            payload[name] = inp.get("value", "")

    action = form.get("action", page_url)
    if not action.startswith("http"):
        # Relative URL
        from urllib.parse import urljoin
        action = urljoin(page_url, action)

    print(f"  POST {action}  fields={list(payload.keys())}")
    dl_resp = session.post(action, data=payload, timeout=60)
    dl_resp.raise_for_status()

    if b"PK" not in dl_resp.content[:4]:
        # Not a ZIP — might be a redirect or error page
        # Try alternate: the form might post to the same page and
        # return a redirect header
        if dl_resp.headers.get("Content-Type", "").startswith("text/html"):
            raise RuntimeError(
                f"Download returned HTML, not ZIP. Status={dl_resp.status_code}, "
                f"len={len(dl_resp.content)}"
            )
    print(f"  Downloaded {len(dl_resp.content):,} bytes")
    return dl_resp.content


def extract_ticks_from_zip(zip_bytes: bytes, multiplier: float,
                           round_to: int = 2) -> list:
    """Extract tick rows from a HistData ZIP archive.

    Returns list of (timestamp_str, bid, ask) tuples with prices scaled by
    `multiplier` and rounded to `round_to` decimal places. In decimal mode
    (multiplier=1.0) rounding to 2dp destroys sub-pip precision, so callers
    should pass round_to=6 for decimal or round_to=2 for IG points.
    """
    rows = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            print(f"  Parsing {name}")
            with zf.open(name) as f:
                for line in f:
                    line = line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith("DateTime"):
                        continue
                    # Format: YYYYMMDD HHmmssSSS,bid,ask,volume
                    # or semicolon-delimited
                    parts = re.split(r"[,;]", line)
                    if len(parts) < 3:
                        continue
                    dt_raw = parts[0].strip()
                    bid_raw = parts[1].strip()
                    ask_raw = parts[2].strip()
                    try:
                        bid = round(float(bid_raw) * multiplier, round_to)
                        ask = round(float(ask_raw) * multiplier, round_to)
                    except ValueError:
                        continue
                    # Parse datetime: "YYYYMMDD HHmmssSSS" → "YYYY-MM-DD HH:MM:SS.sss"
                    if len(dt_raw) >= 17:
                        ts = (
                            f"{dt_raw[0:4]}-{dt_raw[4:6]}-{dt_raw[6:8]} "
                            f"{dt_raw[9:11]}:{dt_raw[11:13]}:{dt_raw[13:15]}.{dt_raw[15:18]}"
                        )
                    elif len(dt_raw) >= 15:
                        ts = (
                            f"{dt_raw[0:4]}-{dt_raw[4:6]}-{dt_raw[6:8]} "
                            f"{dt_raw[9:11]}:{dt_raw[11:13]}:{dt_raw[13:15]}"
                        )
                    else:
                        ts = dt_raw  # fallback
                    rows.append((ts, bid, ask))
    return rows


def main():
    parser = argparse.ArgumentParser(description="Download HistData tick data")
    parser.add_argument("--pair", default="GBPUSD", help="Currency pair")
    parser.add_argument("--year", type=int, default=2026, help="Year")
    parser.add_argument("--months", type=int, nargs="+", default=[3, 4], help="Months to download")
    parser.add_argument("--output", default=None, help="Output CSV path (auto-generated if omitted)")
    parser.add_argument("--ig-points", action="store_true",
                        help="Emit 3-column IG point prices instead of 4-column decimal+mid")
    args = parser.parse_args()

    pair = args.pair.upper()
    multiplier = PAIR_MULTIPLIERS.get(pair, 10000) if args.ig_points else 1.0
    # Match existing GBPUSD_ticks_2026.csv filename pattern
    default_name = f"{pair}_ticks_{args.year}.csv" if not args.ig_points else f"{pair}_{args.year}_ticks.csv"
    out_path = Path(args.output) if args.output else OUT_DIR / default_name
    out_path.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0",
        "Referer": "https://www.histdata.com/",
    })

    all_rows = []
    for month in args.months:
        print(f"\n=== {pair} {args.year}/{month:02d} ===")
        try:
            zip_bytes = download_month(session, pair, args.year, month)
            # Decimal mode keeps sub-pip precision (6dp); IG-point mode
            # keeps 0.1-pip precision (2dp after *10000 scale).
            round_to = 2 if args.ig_points else 6
            rows = extract_ticks_from_zip(zip_bytes, multiplier, round_to)
            print(f"  Extracted {len(rows):,} ticks")
            all_rows.extend(rows)
        except Exception as e:
            print(f"  ERROR: {e}")
            print(f"  Skipping {pair} {args.year}/{month:02d}")
        time.sleep(2)  # polite delay between months

    if not all_rows:
        print("\nNo tick data downloaded.")
        sys.exit(1)

    # Sort by timestamp
    all_rows.sort(key=lambda r: r[0])

    # Write output
    print(f"\nWriting {len(all_rows):,} ticks to {out_path}")
    with open(out_path, "w") as f:
        if args.ig_points:
            f.write("timestamp,bid,ask\n")
            for ts, bid, ask in all_rows:
                f.write(f"{ts},{bid},{ask}\n")
        else:
            f.write("timestamp,bid,ask,mid\n")
            for ts, bid, ask in all_rows:
                mid = (bid + ask) / 2
                f.write(f"{ts},{bid},{ask},{mid}\n")

    # Summary
    print(f"Done. Date range: {all_rows[0][0]} → {all_rows[-1][0]}")
    print(f"File size: {out_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
