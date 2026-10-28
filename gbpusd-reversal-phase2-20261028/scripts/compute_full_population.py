"""Compute point-in-time features for every de-duplicated episode
(all 1,025) and write FULL_POPULATION_RESULTS.csv.

Features are a strict subset of Phase 1's set — the ones the Phase 1
report found separate (or were explicitly tested for) SUCCESS from
FAIL — plus the inputs to the six preregistered confirmation events.

No feature is allowed to use outcome information.  All look-up windows
end at the event bar.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, bollinger, ema, macd, read_bid_m5, rsi


def _features(bars: list[Bar], event_idx: int, kind: str) -> dict:
    b = bars[event_idx]
    closes = [x.close for x in bars[:event_idx + 1]]
    bb_low, bb_mid, bb_up = bollinger(closes, 20, 2.0)
    _, _, hist = macd(closes, 12, 26, 9)
    rsi_s = rsi(closes, 14)

    bbw = (bb_up[event_idx] - bb_low[event_idx]) \
        if (bb_up[event_idx] is not None and bb_low[event_idx] is not None) else None
    bb_breach_low = (bb_low[event_idx] is not None and b.low <= bb_low[event_idx])
    bb_breach_up  = (bb_up[event_idx]  is not None and b.high >= bb_up[event_idx])
    rsi_v = rsi_s[event_idx]

    # Momentum-exhaustion extras
    macd_hist = hist[event_idx] if hist[event_idx] is not None else None

    # Session proximity
    session_bars = [x for x in bars[:event_idx] if x.ts.hour >= 6]
    session_high = max((x.high for x in session_bars), default=None)
    session_low = min((x.low for x in session_bars), default=None)
    near_session_extreme = False
    if kind == "BULL" and session_low is not None:
        near_session_extreme = abs(b.low - session_low) <= 10.0
    elif kind == "BEAR" and session_high is not None:
        near_session_extreme = abs(b.high - session_high) <= 10.0

    # Round-level proximity (50 pts)
    base_px = b.low if kind == "BULL" else b.high
    nearest = round(base_px / 50.0) * 50.0
    near_round = abs(base_px - nearest) <= 10.0

    # Session (London/NY labels for Q8 reporting)
    hr = b.ts.hour
    if 6 <= hr < 11:
        session = "LONDON_AM"
    elif 11 <= hr < 13:
        session = "LONDON_MIDDAY"
    elif 13 <= hr < 17:
        session = "NY_OVERLAP"
    elif 17 <= hr < 20:
        session = "NY_PM"
    else:
        session = "OTHER"

    return {
        "bb_width_pts": round(bbw, 2) if bbw is not None else None,
        "bb_breach_low": bool(bb_breach_low),
        "bb_breach_up": bool(bb_breach_up),
        "rsi": round(rsi_v, 2) if rsi_v is not None else None,
        "macd_hist": round(macd_hist, 3) if macd_hist is not None else None,
        "near_round_level": bool(near_round),
        "near_session_extreme": bool(near_session_extreme),
        "session": session,
    }


def _outcome(bars: list[Bar], event_idx: int, kind: str) -> dict:
    """Repeat the Phase 1 outcome rule.  SUCCESS = +30 p MFE within +60
    min AND did not break −5 p past extreme; FAIL = −5 p past extreme;
    AMBIGUOUS = neither.  Both-hit-in-one-bar = AMBIGUOUS."""
    HORIZON = 12
    end = min(event_idx + HORIZON, len(bars) - 1)
    extreme = bars[event_idx].low if kind == "BULL" else bars[event_idx].high
    close = bars[event_idx].close
    hit_target = False
    broke_extreme = False
    first_hit = None  # 'TARGET' or 'STOP' or 'BOTH'
    resolution_bar = None
    mfe = 0.0
    mae = 0.0
    for i in range(event_idx + 1, end + 1):
        bar_hits_target = bar_breaks_stop = False
        if kind == "BULL":
            bar_hits_target = bars[i].high >= close + 30.0
            bar_breaks_stop = bars[i].low <= extreme - 5.0
            mfe = max(mfe, bars[i].high - close)
            mae = max(mae, close - bars[i].low)
        else:
            bar_hits_target = bars[i].low <= close - 30.0
            bar_breaks_stop = bars[i].high >= extreme + 5.0
            mfe = max(mfe, close - bars[i].low)
            mae = max(mae, bars[i].high - close)
        if bar_hits_target and bar_breaks_stop:
            first_hit = "BOTH"
            resolution_bar = i
            break
        if bar_hits_target:
            hit_target = True
            first_hit = "TARGET"
            resolution_bar = i
            break
        if bar_breaks_stop:
            broke_extreme = True
            first_hit = "STOP"
            resolution_bar = i
            break
    # Translate
    if first_hit == "TARGET":
        label = f"SUCCESS_{kind}"
    elif first_hit == "STOP":
        label = f"FAIL_{kind}"
    elif first_hit == "BOTH":
        label = f"AMBIGUOUS_{kind}"
    else:
        label = f"AMBIGUOUS_{kind}"
    return {
        "outcome_label": label,
        "mfe_60min_pts": round(mfe, 2),
        "mae_60min_pts": round(mae, 2),
        "resolution_bar_offset": (resolution_bar - event_idx) if resolution_bar else None,
        "first_hit": first_hit,
    }


def main() -> int:
    cands_path = HERE.parent / "data" / "reversal_candidates.csv"
    rows = list(csv.DictReader(cands_path.open()))

    # Episode dedup inline (identical to Phase 1)
    EPISODE_GAP = timedelta(minutes=60)
    deduped: list[dict] = []
    last_by_kind: dict[str, datetime] = {}
    for r in rows:
        ts = datetime.fromisoformat(r["event_ts_utc"])
        prev = last_by_kind.get(r["kind"])
        if prev is None or (ts - prev) >= EPISODE_GAP:
            deduped.append(r)
            last_by_kind[r["kind"]] = ts

    # Load each day's bars once
    by_date: dict[str, list[dict]] = {}
    for r in deduped:
        by_date.setdefault(r["date"], []).append(r)

    out_rows = []
    for date_str in sorted(by_date):
        date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        try:
            bars = read_bid_m5(date)
        except FileNotFoundError:
            continue
        ts_to_idx = {b.ts.isoformat(): i for i, b in enumerate(bars)}
        for r in by_date[date_str]:
            idx = ts_to_idx.get(r["event_ts_utc"])
            if idx is None:
                continue
            feats = _features(bars, idx, r["kind"])
            outcome = _outcome(bars, idx, r["kind"])
            out_rows.append({
                "year": date_str[:4],
                "date": r["date"],
                "event_ts_utc": r["event_ts_utc"],
                "kind": r["kind"],
                "extreme_pts": r["extreme_pts"],
                "run_move_pips": r["run_move_pips"],
                "run_depth_pips": r["run_depth_pips"],
                **feats, **outcome,
            })

    out_path = HERE.parent / "data" / "FULL_POPULATION_RESULTS.csv"
    fieldnames = list(out_rows[0].keys())
    with out_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"✓ wrote {out_path} ({len(out_rows)} rows)")

    from collections import Counter
    by_outcome = Counter((r["year"], r["kind"], r["outcome_label"]) for r in out_rows)
    print("\nYear × kind × outcome:")
    for (y, k, lbl), n in sorted(by_outcome.items()):
        print(f"  {y}  {k}  {lbl:18}  {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
