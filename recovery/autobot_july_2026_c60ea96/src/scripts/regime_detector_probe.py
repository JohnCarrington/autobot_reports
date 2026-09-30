"""Regime detector probe — replays historical CSVs and classifies regime
at specific UTC timestamps for 2026-04-30 and 2026-05-01.

Read-only. Does not write the live JSONL log (passes log=False).
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

from gbpusd_regime_detector import Bar, MIN_BARS, classify_regime  # noqa: E402

CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"


def _load_day(d: str) -> List[Bar]:
    path = CANDLE_DIR / f"{d}.csv"
    if not path.exists():
        return []
    out: List[Bar] = []
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(Bar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return out


def _load_history(end_date: str, lookback_days: int = 3) -> List[Bar]:
    """Load `lookback_days` of trading days ending with `end_date`."""
    end = datetime.fromisoformat(end_date).date()
    bars: List[Bar] = []
    cur = end - timedelta(days=lookback_days)
    while cur <= end:
        bars.extend(_load_day(cur.isoformat()))
        cur = cur + timedelta(days=1)
    return bars


def _bars_up_to(bars: List[Bar], probe_ts: datetime) -> List[Bar]:
    """Return bars whose timestamp < probe_ts (i.e. closed by probe_ts)."""
    return [b for b in bars if b.timestamp < probe_ts]


def _probe(label: str, day: str, hh: int, mm: int = 0) -> None:
    bars = _load_history(day, lookback_days=4)
    probe_ts = datetime.fromisoformat(day).replace(
        hour=hh, minute=mm, tzinfo=timezone.utc,
    )
    sliced = _bars_up_to(bars, probe_ts)
    r = classify_regime(sliced, log=False)
    sb = r.signal_breakdown
    db = r.debug

    atr_dbg = db.get("atr") if isinstance(db.get("atr"), dict) else None
    if atr_dbg and "cur_atr_pips" in atr_dbg:
        atr_d = (f"cur={atr_dbg.get('cur_atr_pips','?')}p "
                 f"mean={atr_dbg.get('mean_atr_pips','?')}p "
                 f"ratio={atr_dbg.get('ratio','?')}")
        bbw_d = (f"cur={db['bb_width'].get('cur_width_pips','?')}p "
                 f"mean={db['bb_width'].get('mean_width_pips','?')}p "
                 f"ratio={db['bb_width'].get('ratio','?')}")
        rng_d = (f"range={db['range_atr'].get('range_pips','?')}p "
                 f"atr={db['range_atr'].get('atr_pips','?')}p "
                 f"ratio={db['range_atr'].get('ratio','?')}")
        prc_d = (f"upper={db['pierce_alt'].get('upper','?')} "
                 f"lower={db['pierce_alt'].get('lower','?')} "
                 f"total={db['pierce_alt'].get('total','?')}")
    else:
        atr_d = bbw_d = rng_d = prc_d = "(warmup)"

    override = " (OVERRIDE)" if db.get("override_fired") else ""
    print(f"\n{label}  {day} {hh:02d}:{mm:02d}Z  bars={len(sliced)}")
    print(f"  REGIME = {r.regime:<8s}  conf={r.confidence}{override}")
    print(f"    atr        : {sb['atr']:<8s}  {atr_d}")
    print(f"    bb_width   : {sb['bb_width']:<8s}  {bbw_d}")
    print(f"    range_atr  : {sb['range_atr']:<8s}  {rng_d}")
    print(f"    pierce_alt : {sb['pierce_alt']:<8s}  {prc_d}")


def _day_distribution(day: str) -> None:
    """Walk every 5m close on `day` from 06:00 to 22:00 UTC, classify."""
    bars = _load_history(day, lookback_days=4)
    counts: Counter = Counter()
    confs: Counter = Counter()
    n = 0
    start = datetime.fromisoformat(day).replace(hour=6, tzinfo=timezone.utc)
    end   = datetime.fromisoformat(day).replace(hour=22, tzinfo=timezone.utc)
    t = start
    while t <= end:
        sliced = _bars_up_to(bars, t)
        if len(sliced) >= MIN_BARS:
            r = classify_regime(sliced, log=False)
            counts[r.regime] += 1
            confs[r.confidence] += 1
            n += 1
        t = t + timedelta(minutes=5)
    print(f"\n  Day {day} distribution (06:00–22:00 UTC, n={n} closes):")
    for k in ("TRENDING", "RANGE", "NEUTRAL"):
        v = counts.get(k, 0)
        pct = 100.0 * v / n if n else 0.0
        print(f"    {k:<8s}  {v:>3d}  ({pct:5.1f}%)")
    print(f"    confidence:  HIGH={confs.get('HIGH',0)}  MEDIUM={confs.get('MEDIUM',0)}  LOW={confs.get('LOW',0)}")


def main() -> None:
    print("=" * 72)
    print("Thursday 2026-04-30 — 6 actual SHORT fire times (was the bleed)")
    print("=" * 72)
    fire_times_0430 = [(8, 10), (9, 55), (11, 0), (14, 30), (15, 0), (15, 10)]
    blocked = 0
    for hh, mm in fire_times_0430:
        _probe(f"04-30 fire {hh:02d}:{mm:02d}", "2026-04-30", hh, mm)
        # We re-classify just for the count summary below.
    # Tally TRENDING blocks (a separate, silent pass for accuracy).
    bars = _load_history("2026-04-30", lookback_days=4)
    for hh, mm in fire_times_0430:
        ts = datetime.fromisoformat("2026-04-30").replace(
            hour=hh, minute=mm, tzinfo=timezone.utc,
        )
        sliced = _bars_up_to(bars, ts)
        if classify_regime(sliced, log=False).regime == "TRENDING":
            blocked += 1
    print(f"\n  >>> Thursday block tally: {blocked} of {len(fire_times_0430)} "
          f"SHORT fires would be gated by regime==TRENDING <<<")

    _day_distribution("2026-04-30")

    print()
    print("=" * 72)
    print("Friday 2026-05-01 — key timestamps (winners must NOT be TRENDING)")
    print("=" * 72)
    _probe("06:00 (overnight quiet)",          "2026-05-01",  6, 0)
    _probe("09:25 (user setup 3 LONG)",        "2026-05-01",  9, 25)
    _probe("14:00 (just before +60p winner)",  "2026-05-01", 14, 0)
    _probe("15:30 (sustained afternoon move)", "2026-05-01", 15, 30)
    _day_distribution("2026-05-01")


if __name__ == "__main__":
    main()
