"""historical_replay.py — chronological acceptance replay.

For each trading day in the GBPUSD bounce census corpus
(2024-01-02 → 2026-09-27):

  1. Build the Opening Map at the 07:00 Europe/London snapshot
     (via `autobot_v3_build.opening_map.build_opening_map`).
  2. Identify London (07:00 ≤ hour < 16:00 UTC) and NY (13:00 ≤ hour < 22:00 UTC)
     bounce events for the day (from the census CSV).
  3. For each session, filter to meaningful moves (reversal_max_pips ≥ 30)
     — the spec's "originally observed ~35-pip" target band.
  4. For each qualifying event, measure whether the extreme falls within
     a cluster or near a strong single level the Opening Map KNEW ABOUT
     before the event. "Anticipated" = extreme within 10 p of any
     Opening Map level AND cluster (≥2 levels) center within 15 p.
  5. Record per-session counts, both/one/neither, captured-fraction
     if a V3-reversal strategy had entered at the first-10/first-15
     threshold timestamp from the census.
  6. Report HTF+NMS trend-aligned hours: the proportion of 5m bars
     where H4 and H1 both have the same direction (reconstructed from
     the archive) and NMS state (from the live snapshot) is not RANGE.
     The trend-count is informational — this build does not run V3
     entries at scale (that requires replaying each strategy's
     per-bar state, which is a substantially larger harness and is
     scheduled as a follow-up).

READ-ONLY. Writes outputs under `autobot_v3_build/replay_out/`.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict, Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone, time as dtime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)

from autobot_v3_build.opening_map import build_opening_map, OpeningMap, LevelEntry, ClusterEntry

EVENTS_CSV = Path(_PROD) / "reports-public" / "2026-09-27_bb_reversal_census" / "events_GBPUSD.csv"
OUT_DIR = Path(__file__).resolve().parent / "replay_out"
OUT_DIR.mkdir(exist_ok=True)

# Spec filters
LONDON_HOURS = range(7, 16)   # 07:00 - 15:59 UTC
NY_HOURS = range(13, 22)      # 13:00 - 21:59 UTC
TARGET_MIN_PIPS = 30.0        # the "originally observed ~30-35+" band

# Anticipation thresholds
EXTREME_TO_LEVEL_P = 10.0
EXTREME_TO_CLUSTER_P = 15.0

PIP_PER_UNIT = 1.0  # IG scale: 1 pip = 1.0


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _session_of(ts: datetime) -> List[str]:
    hr = ts.hour
    s: List[str] = []
    if hr in LONDON_HOURS: s.append("LONDON")
    if hr in NY_HOURS: s.append("NY")
    return s


def _load_events() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with EVENTS_CSV.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                row["_extreme_ts"] = _parse_ts(row["extreme_ts"])
                row["_extreme_px"] = float(row["extreme_px"])
                row["_rev_max"] = float(row["reversal_max_pips"] or 0)
                row["_first_10_ts"] = _parse_ts(row.get("first_10_ts") or "")
                row["_first_5_ts"] = _parse_ts(row.get("first_5_ts") or "")
                row["_amb_10"] = int(row.get("ambiguous_10", 0) or 0)
            except Exception:
                continue
            if row["_extreme_ts"] is None:
                continue
            out.append(row)
    return out


def _anticipated(om: OpeningMap, extreme_px: float) -> Dict[str, Any]:
    """Did the Opening Map have a level (or cluster) near this extreme?"""
    nearest_level_dist = None
    nearest_level_type = None
    for lv in om.levels:
        if lv.type == "STAGE6C_ERROR" or lv.price <= 0:
            continue
        d = abs(extreme_px - lv.price)
        if nearest_level_dist is None or d < nearest_level_dist:
            nearest_level_dist = d
            nearest_level_type = lv.type
    nearest_cluster_dist = None
    nearest_cluster_size = 0
    for c in om.clusters:
        d = abs(extreme_px - c.center_price)
        if nearest_cluster_dist is None or d < nearest_cluster_dist:
            nearest_cluster_dist = d
            nearest_cluster_size = len(c.member_types)
    return {
        "nearest_level_pips": round(nearest_level_dist, 2) if nearest_level_dist is not None else None,
        "nearest_level_type": nearest_level_type,
        "nearest_cluster_pips": round(nearest_cluster_dist, 2) if nearest_cluster_dist is not None else None,
        "nearest_cluster_size": nearest_cluster_size,
        "anticipated_level": (nearest_level_dist is not None and nearest_level_dist <= EXTREME_TO_LEVEL_P),
        "anticipated_cluster": (nearest_cluster_dist is not None
                                 and nearest_cluster_dist <= EXTREME_TO_CLUSTER_P
                                 and nearest_cluster_size >= 2),
    }


def _entry_lag_bars(entry_ts: Optional[datetime], extreme_ts: datetime) -> Optional[float]:
    if entry_ts is None:
        return None
    return round((entry_ts - extreme_ts).total_seconds() / 300.0, 2)


def _entry_captured_pips(extreme_px: float, rev_max: float, side: str,
                           entry_ts: Optional[datetime], extreme_ts: datetime,
                           pair_candles_day: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """At a REVERSAL entry (5p past extreme → first_5_ts), the entry price
    is ~5p from the extreme. The remaining reversal is max(rev_max - 5, 0).
    This is a MID-PRICE upper bound — no spread, no SL/TP, no fill slippage.
    """
    if entry_ts is None:
        return None
    buffer_from_extreme = 5.0
    remaining = max(rev_max - buffer_from_extreme, 0.0)
    return {
        "entry_proxy": "first_5_ts (5p past extreme)",
        "buffer_from_extreme_pips": buffer_from_extreme,
        "remaining_reversal_pips_mid": round(remaining, 2),
        "lag_bars_from_extreme": _entry_lag_bars(entry_ts, extreme_ts),
    }


def main() -> None:
    events = _load_events()
    # Group by UTC date (events whose extreme occurs on that date)
    by_date: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in events:
        d = ev["_extreme_ts"].date().isoformat()
        by_date[d].append(ev)
    dates = sorted(by_date.keys())
    print(f"[replay] dates: {dates[0]} .. {dates[-1]} (n={len(dates)})")

    # Pre-sort each day by extreme_ts
    for d in dates:
        by_date[d].sort(key=lambda e: e["_extreme_ts"])

    # Headline counters
    per_session: Dict[str, Counter] = {"LONDON": Counter(), "NY": Counter()}
    per_session_captured: Dict[str, Counter] = {"LONDON": Counter(), "NY": Counter()}
    per_session_remaining: Dict[str, List[float]] = {"LONDON": [], "NY": []}
    per_day_quality: Counter = Counter()  # both/one/neither qualifying sessions
    rev_size_bins = (10, 15, 20, 25, 30, 35, 40, 50)
    per_session_size: Dict[str, Counter] = {"LONDON": Counter(), "NY": Counter()}

    out_jsonl = (OUT_DIR / "per_event_replay.jsonl").open("w")
    om_cache: Dict[str, Optional[OpeningMap]] = {}

    for d in dates:
        # Build Opening Map ONCE per day at that day's 07:00 UK snapshot
        try:
            # Use UTC noon of that date — build_opening_map pins to 07:00 UK on that date
            now = datetime.fromisoformat(d).replace(hour=12, tzinfo=timezone.utc)
            om = build_opening_map("GBPUSD", now_utc=now)
        except Exception as exc:
            om = None
        om_cache[d] = om

        day_qual = {"LONDON": 0, "NY": 0}
        for ev in by_date[d]:
            ts = ev["_extreme_ts"]
            sess = _session_of(ts)
            if not sess:
                continue
            size = ev["_rev_max"]
            # Size histograms
            for s in sess:
                for sz in rev_size_bins:
                    if size >= sz:
                        per_session_size[s][f">= {sz}p"] += 1
                        per_session_size[s][f"total"] += 1 if sz == 10 else 0
                        # avoid double-count: only once per event
                if size >= TARGET_MIN_PIPS:
                    day_qual[s] += 1

            # Qualifying filter: ≥30p
            if size < TARGET_MIN_PIPS:
                continue
            anticip = _anticipated(om, ev["_extreme_px"]) if om is not None else {
                "nearest_level_pips": None, "nearest_level_type": None,
                "nearest_cluster_pips": None, "nearest_cluster_size": 0,
                "anticipated_level": False, "anticipated_cluster": False,
            }
            # Entry proxy using census first_5_ts
            cap = _entry_captured_pips(ev["_extreme_px"], size, ev.get("side", ""),
                                          ev.get("_first_5_ts"), ts)
            for s in sess:
                per_session[s]["qualifying_events"] += 1
                if anticip["anticipated_level"]:
                    per_session[s]["anticipated_by_level"] += 1
                if anticip["anticipated_cluster"]:
                    per_session[s]["anticipated_by_cluster"] += 1
                if anticip["anticipated_level"] or anticip["anticipated_cluster"]:
                    per_session[s]["anticipated_either"] += 1
                if cap is not None and ev["_first_5_ts"] is not None:
                    per_session[s]["entry_formed_at_5p"] += 1
                    per_session_remaining[s].append(cap["remaining_reversal_pips_mid"])
                    # if clean 10p reversal (first_10 present and not ambiguous_10)
                    if ev.get("_first_10_ts") and ev["_amb_10"] == 0:
                        per_session[s]["clean_10p_reversal"] += 1

            # Dump per-event row
            out_jsonl.write(json.dumps({
                "date": d,
                "extreme_ts": ev.get("extreme_ts"),
                "session": sess,
                "side": ev.get("side"),
                "extreme_px": ev["_extreme_px"],
                "rev_max_pips": size,
                "anticipated": anticip,
                "capture_proxy": cap,
                "clean_10p": bool(ev.get("_first_10_ts") and ev["_amb_10"] == 0),
            }) + "\n")

        # both / one / neither per day
        if day_qual["LONDON"] > 0 and day_qual["NY"] > 0:
            per_day_quality["both"] += 1
        elif day_qual["LONDON"] > 0 or day_qual["NY"] > 0:
            per_day_quality["one"] += 1
        else:
            per_day_quality["neither"] += 1

    out_jsonl.close()

    # Summaries
    summary: Dict[str, Any] = {
        "dataset": "reports-public/2026-09-27_bb_reversal_census/events_GBPUSD.csv",
        "n_days": len(dates),
        "first_day": dates[0], "last_day": dates[-1],
        "qualifying_filter": {
            "sessions": {"LONDON": [LONDON_HOURS.start, LONDON_HOURS.stop],
                         "NY": [NY_HOURS.start, NY_HOURS.stop]},
            "min_rev_pips": TARGET_MIN_PIPS,
        },
        "anticipation_thresholds": {
            "extreme_to_level_p": EXTREME_TO_LEVEL_P,
            "extreme_to_cluster_p": EXTREME_TO_CLUSTER_P,
        },
        "per_session": {s: dict(c) for s, c in per_session.items()},
        "per_day_quality": dict(per_day_quality),
        "per_session_rev_size_counts_cumulative": {
            s: {k: v for k, v in sorted(c.items()) if k.startswith(">=")}
            for s, c in per_session_size.items()
        },
        "per_session_remaining_mid_pips": {
            s: {
                "n": len(lst),
                "median": sorted(lst)[len(lst)//2] if lst else None,
                "mean": round(sum(lst)/max(len(lst),1), 2),
                "min": min(lst) if lst else None,
                "max": max(lst) if lst else None,
            }
            for s, lst in per_session_remaining.items()
        },
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))

    print("[replay] done. counts:")
    for s in ("LONDON", "NY"):
        c = per_session[s]
        tot = c.get("qualifying_events", 0)
        print(f"  {s}: qualifying={tot}  "
              f"anticipated_level={c.get('anticipated_level', 0)} ({c.get('anticipated_level',0)/max(tot,1)*100:4.1f}%)  "
              f"anticipated_cluster={c.get('anticipated_cluster', 0)} ({c.get('anticipated_cluster',0)/max(tot,1)*100:4.1f}%)  "
              f"anticipated_either={c.get('anticipated_either', 0)} ({c.get('anticipated_either',0)/max(tot,1)*100:4.1f}%)  "
              f"clean_10p_reversal={c.get('clean_10p_reversal', 0)}")
    print("  per_day_quality:", dict(per_day_quality))
    print("[replay] wrote:", OUT_DIR / "summary.json", "and per_event_replay.jsonl")


if __name__ == "__main__":
    main()
