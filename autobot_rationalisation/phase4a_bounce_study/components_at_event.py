"""For each bounce event:

  * HTF: derive D1-trend at extreme_ts using the SAME prior-D1 approach the
    production htf_authority uses (sign of close_{d-1} − close_{d-2}, plus
    the magnitude in pips). This is a RECONSTRUCTION — the production
    htf_authority.jsonl rolling log only covers ~9 recent days and does
    not overlap the census window.
  * QM: match against logs/qm_level_interactions.jsonl terminal records.
    Coverage window ≈ 2026-09-21 → today (~23 days). For each event,
    find any terminal interaction on the SAME day where the level was
    within 10p of the extreme and the terminal state was emitted.
  * PAA: paa.assessment did not exist until 2026-10-14 and emits no
    historical records. Reported as NO_COVERAGE.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import importlib.util
_h = importlib.util.spec_from_file_location("lh", Path(__file__).parent / "level_distance_harness.py")
lh = importlib.util.module_from_spec(_h); _h.loader.exec_module(lh)  # type: ignore

ROOT = Path("/opt/tradingbot")
EVENTS_CSV = ROOT / "reports-public" / "2026-09-27_bb_reversal_census" / "events_GBPUSD.csv"
QLI_LOGS = sorted(ROOT.glob("logs/qm_level_interactions.jsonl*"))
OUT_DIR = Path(__file__).resolve().parent


def _parse_ts(s): return lh._parse_ts(s)


def _d1_trend(for_date):
    """Return (direction, magnitude_pips, close_prev, close_prev2) using
    _prior_d1 twice to walk back two D1 anchors."""
    prev = lh._prior_d1(for_date)
    if prev is None:
        return "UNKNOWN", 0.0, None, None
    prev2_date = (datetime.fromisoformat(prev["date"]).date() if isinstance(prev.get("date"), str) else None)
    if prev2_date is None:
        return "UNKNOWN", 0.0, prev["close"], None
    prev2 = lh._prior_d1(prev2_date)
    if prev2 is None:
        return "UNKNOWN", 0.0, prev["close"], None
    delta = prev["close"] - prev2["close"]
    direction = "UP" if delta > 0 else ("DOWN" if delta < 0 else "FLAT")
    return direction, round(abs(delta), 2), prev["close"], prev2["close"]


# ── QM terminal records loader ──────────────────────────────────────

_QLI_BY_DAY: Dict[str, List[Dict[str, Any]]] = {}


def _load_qli() -> None:
    for p in QLI_LOGS:
        opener = (lambda f=p: gzip.open(f, "rt")) if p.name.endswith(".gz") else (lambda f=p: f.open("r"))
        with opener() as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not r.get("final_state"):
                    continue
                final_ts = _parse_ts(r.get("final_ts") or "")
                if final_ts is None:
                    continue
                day = final_ts.date().isoformat()
                r["_final_ts"] = final_ts
                _QLI_BY_DAY.setdefault(day, []).append(r)


def _qli_at_event(ts, px, pair="GBPUSD", pip_tol=10.0, hour_tol=6.0):
    """Return per-level_type terminal states that resolved within hour_tol
    hours of extreme_ts AND whose level was within pip_tol of extreme_px.
    """
    day = ts.date().isoformat()
    rows = _QLI_BY_DAY.get(day, [])
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("symbol") != pair:
            continue
        try:
            lv = float(r.get("level_price"))
        except Exception:
            continue
        if abs(lv - px) > pip_tol:
            continue
        delta_h = abs((r["_final_ts"] - ts).total_seconds()) / 3600.0
        if delta_h > hour_tol:
            continue
        out.append({
            "level_type": r.get("level_type"),
            "level_price": lv,
            "final_state": r.get("final_state"),
            "approach_side": r.get("approach_side"),
            "final_ts": r.get("final_ts"),
            "distance_pips": round(abs(lv - px), 2),
            "delta_h": round(delta_h, 2),
        })
    return out


def main() -> None:
    _load_qli()
    qli_days = sorted(_QLI_BY_DAY.keys())
    qli_first = qli_days[0] if qli_days else "-"
    qli_last = qli_days[-1] if qli_days else "-"
    print(f"QM log coverage: {qli_first} to {qli_last} ({len(qli_days)} days)")

    events_in_qli_window: int = 0
    qli_match_count = 0
    htf_direction_counts: Counter = Counter()
    htf_vs_outcome: Dict[str, Counter] = defaultdict(Counter)
    out_path = OUT_DIR / "per_event_components.jsonl"
    with out_path.open("w") as fh, EVENTS_CSV.open() as efh:
        r = csv.DictReader(efh)
        for row in r:
            ts = _parse_ts(row.get("extreme_ts") or "")
            if ts is None:
                continue
            px = float(row.get("extreme_px") or 0)
            # HTF
            direction, mag, c1, c2 = _d1_trend(ts.date())
            htf_direction_counts[direction] += 1
            side = row.get("side", "")
            outcome = ("REVERSED_10" if (row.get("first_10_ts") and not int(row.get("ambiguous_10", 0) or 0))
                       else "REVERSED_5" if (row.get("first_5_ts") and not int(row.get("ambiguous_5", 0) or 0))
                       else "FAILED")
            # htf_alignment: upper-side bounce = short direction. HTF UP + upper-side = countertrend fade. HTF DOWN + upper-side = aligned trend-fade.
            if direction in ("UP", "DOWN"):
                aligned = ((side == "upper" and direction == "DOWN")  # fading an uptrend into resistance → countertrend
                           or (side == "lower" and direction == "UP"))
                # Note: "aligned" here means HTF is going AWAY from the bounce direction (bounce reverses with HTF)
                tag = "WITH_HTF" if aligned else "AGAINST_HTF"
            else:
                tag = "UNKNOWN_HTF"
            htf_vs_outcome[tag][outcome] += 1

            # QM
            qli_rows = _qli_at_event(ts, px) if qli_days and (qli_first <= ts.date().isoformat() <= qli_last) else []
            if qli_days and qli_first <= ts.date().isoformat() <= qli_last:
                events_in_qli_window += 1
                if qli_rows:
                    qli_match_count += 1

            fh.write(json.dumps({
                "extreme_ts": row.get("extreme_ts"),
                "extreme_px": px,
                "side": side,
                "outcome": outcome,
                "htf_direction": direction,
                "htf_prior_delta_pips": mag,
                "htf_tag": tag,
                "qm_terminals": qli_rows,
                "paa_coverage": "NO_COVERAGE",  # paa did not exist for census window
            }) + "\n")

    summary = {
        "htf_direction_counts": dict(htf_direction_counts),
        "htf_vs_outcome": {k: dict(v) for k, v in htf_vs_outcome.items()},
        "qm_coverage_window": {"first_day": qli_first, "last_day": qli_last, "days": len(qli_days)},
        "qm_events_in_window": events_in_qli_window,
        "qm_match_count": qli_match_count,
        "paa_coverage": "NO_COVERAGE_FOR_CENSUS_WINDOW",
    }
    (OUT_DIR / "components_summary.json").write_text(json.dumps(summary, indent=2))

    print(f"HTF direction counts: {dict(htf_direction_counts)}")
    print(f"HTF-vs-outcome:")
    for tag in sorted(htf_vs_outcome):
        o = htf_vs_outcome[tag]
        tot = sum(o.values())
        if tot == 0:
            continue
        rev_10 = o.get("REVERSED_10", 0)
        rev_5 = o.get("REVERSED_5", 0)
        fail = o.get("FAILED", 0)
        print(f"  {tag:>14s}  n={tot:5d}  REV_10={rev_10/tot*100:4.1f}%  REV_5={rev_5/tot*100:4.1f}%  FAIL={fail/tot*100:4.1f}%")
    print(f"\nQM: events in log window: {events_in_qli_window}, matched: {qli_match_count}")


if __name__ == "__main__":
    main()
