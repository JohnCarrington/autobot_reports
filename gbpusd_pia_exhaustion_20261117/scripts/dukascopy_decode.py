"""dukascopy_decode.py — turn the PowerShell-fetched .bi5 archive into M5 CSVs.

Reads the archive dropped at /tmp/dukascopy_gbpusd_2026-11-09_17.zip (or an
override), decompresses each hourly .bi5 file, parses the 20-byte tick
records (Dukascopy's long-standing JForex format), aggregates to M5 OHLC
on the MID of (bid, ask), and writes one CSV per trading day with the same
layout as /opt/tradingbot/data/candles/GBPUSD/*.csv:

    timestamp,open,high,low,close
    2026-11-10T07:00:00+00:00,13482.3,13485.1,13480.7,13483.9

Prices are stored on the × 10000 scale (so 13482.3 means decimal 1.34823).
MID = (bid + ask) / 2, in line with /opt/tradingbot/data/candles/GBPUSD/
which is MID-of-bid-ask in the 2026 archive era (see
project_tick_backtest_framework_phase2_20261027 memory).

Read-only. No production changes. Outputs land under
../data/candles_recovered/GBPUSD/ in the research worktree.
"""
from __future__ import annotations

import csv
import io
import lzma
import pathlib
import struct
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "candles_recovered" / "GBPUSD"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Dukascopy tick record: 20 bytes big-endian
#   uint32 msec_from_hour_start
#   uint32 ask_price_e5       (GBPUSD: 5 decimals -> divide by 100000)
#   uint32 bid_price_e5
#   float32 ask_volume_millions
#   float32 bid_volume_millions
TICK_STRUCT = struct.Struct(">IIIff")
TICK_SIZE = TICK_STRUCT.size  # 20

# GBPUSD convention: 5-decimal prices; multiply by 10000 to get the archive's
# × 10000 scale so the CSV prices line up with /opt/tradingbot/data/candles.
PRICE_SCALE_IN = 100_000.0       # raw -> decimal
PRICE_SCALE_OUT = 10_000.0       # decimal -> archive points

DEFAULT_ARCHIVE = pathlib.Path("/tmp/dukascopy_gbpusd_2026-11-09_17.zip")


def decompress_bi5(raw: bytes) -> bytes:
    """Dukascopy .bi5 is raw LZMA (not LZMA2, not xz). Build a one-shot decompressor
    with a permissive filter chain so varied vintages decode."""
    if not raw:
        return b""
    # Standard raw LZMA (alone format) decoder:
    try:
        return lzma.decompress(raw, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError:
        pass
    # Some mirrors ship the data as LZMA1 raw with explicit properties header.
    # Fall back to a filter chain matching JForex's preset.
    try:
        decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
            {"id": lzma.FILTER_LZMA1, "preset": 6}
        ])
        return decompressor.decompress(raw)
    except lzma.LZMAError as e:
        raise RuntimeError(f"bi5 decompression failed: {e}")


def parse_hour(bi5: bytes, hour_start: datetime) -> list[tuple[datetime, float, float]]:
    """Return list of (ts_utc, mid, spread_pips). mid is in decimal price."""
    data = decompress_bi5(bi5)
    out: list[tuple[datetime, float, float]] = []
    for offset in range(0, len(data), TICK_SIZE):
        chunk = data[offset:offset + TICK_SIZE]
        if len(chunk) < TICK_SIZE:
            break
        ms, ask_e5, bid_e5, av, bv = TICK_STRUCT.unpack(chunk)
        ts = hour_start + timedelta(milliseconds=ms)
        ask = ask_e5 / PRICE_SCALE_IN
        bid = bid_e5 / PRICE_SCALE_IN
        mid = (bid + ask) / 2.0
        spread_pips = (ask - bid) * PRICE_SCALE_OUT
        out.append((ts, mid, spread_pips))
    return out


def aggregate_m5(ticks: list[tuple[datetime, float, float]]) -> dict[datetime, tuple[float, float, float, float, int]]:
    """Return {bucket_start: (open, high, low, close, tick_count)} on 5-minute boundaries."""
    bucket_s = 5 * 60
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for ts, mid, _spread in ticks:
        bucket_epoch = (int(ts.timestamp()) // bucket_s) * bucket_s
        bucket_start = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
        buckets[bucket_start].append(mid)
    out = {}
    for bucket_start, prices in buckets.items():
        out[bucket_start] = (prices[0], max(prices), min(prices), prices[-1], len(prices))
    return out


def process_archive(archive_path: pathlib.Path) -> None:
    if not archive_path.exists():
        print(f"ERROR: archive not found at {archive_path}", file=sys.stderr)
        print("Transfer the dukascopy_fetch.ps1 output zip first, then rerun.", file=sys.stderr)
        sys.exit(1)

    per_day: dict[str, list[tuple[datetime, float, float, float, float, int]]] = defaultdict(list)

    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(n for n in zf.namelist() if n.endswith(".bi5"))
        print(f"Found {len(names)} .bi5 files in archive.")
        for name in names:
            # Expected path: dukascopy_gbpusd_2026-11-09_17/2026-11-09/07h_ticks.bi5
            parts = name.replace("\\", "/").split("/")
            try:
                date_part = next(p for p in parts if len(p) == 10 and p[4] == "-" and p[7] == "-")
                hour_part = next(p for p in parts if p.endswith("h_ticks.bi5"))
            except StopIteration:
                print(f"  skip {name} (unexpected path)")
                continue
            hh = int(hour_part[:2])
            day = datetime.fromisoformat(date_part).replace(tzinfo=timezone.utc)
            hour_start = day + timedelta(hours=hh)
            with zf.open(name) as fh:
                raw = fh.read()
            if not raw:
                continue  # expected during FX-closed hours
            try:
                ticks = parse_hour(raw, hour_start)
            except RuntimeError as e:
                print(f"  {name}: {e}")
                continue
            if not ticks:
                continue
            m5 = aggregate_m5(ticks)
            for bucket, (o, h, lo, c, n) in sorted(m5.items()):
                per_day[date_part].append((bucket, o, h, lo, c, n))

    total_bars = 0
    for date_part, rows in sorted(per_day.items()):
        rows.sort()
        out_path = OUT_DIR / f"{date_part}.csv"
        with out_path.open("w") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "open", "high", "low", "close"])
            for bucket, o, h, lo, c, _n in rows:
                w.writerow([
                    bucket.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    f"{round(o * PRICE_SCALE_OUT, 2):g}",
                    f"{round(h * PRICE_SCALE_OUT, 2):g}",
                    f"{round(lo * PRICE_SCALE_OUT, 2):g}",
                    f"{round(c * PRICE_SCALE_OUT, 2):g}",
                ])
        print(f"  wrote {len(rows):4d} M5 bars -> {out_path}")
        total_bars += len(rows)

    print(f"\nTotal: {total_bars} M5 bars across {len(per_day)} day CSVs")
    print(f"Output dir: {OUT_DIR}")

    # Validation summary
    print("\nValidation:")
    expected_dates = [
        "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13",
        "2026-11-16", "2026-11-17",
    ]
    for d in expected_dates:
        rows = per_day.get(d, [])
        if not rows:
            print(f"  {d}: MISSING")
        else:
            first = rows[0][0].strftime("%H:%M")
            last = rows[-1][0].strftime("%H:%M")
            print(f"  {d}: {len(rows):4d} bars, {first} -> {last}")


if __name__ == "__main__":
    archive = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ARCHIVE
    process_archive(archive)
