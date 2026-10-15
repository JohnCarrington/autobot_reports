"""Match V3 fires in signal_log.jsonl to bounce events in the census.

For each V3-family signal_log row (GBPUSD), find the bounce event
whose [start_ts, end_ts] contains the firing time, OR whose extreme_ts
is within N minutes of the firing time. Measure:

  * timing_lag_bars: 5m bars between extreme_ts and timestamp_open
    (negative = fired BEFORE the extreme — leading the turn;
     positive = fired AFTER the extreme — missed some of the move).
  * capture_ratio: entry's pips captured vs event.reversal_max_pips.
    Entry pips captured = min(reversal_max_pips − |entry − extreme_px|, 0)
    computed on the mid-price axis — not SL/TP-aware.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path("/opt/tradingbot")
EVENTS_CSV = ROOT / "reports-public" / "2026-09-27_bb_reversal_census" / "events_GBPUSD.csv"
SIGNAL_LOG = ROOT / "logs" / "signal_log.jsonl"
OUT_DIR = Path(__file__).resolve().parent

V3_STRATEGIES = {
    "GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S",
    "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
    "V3_BB_L", "V3_BB_S",
    "V3_EMA_L", "V3_EMA_S",
    "BOUNCE_A_L", "BOUNCE_A_S",
    "BOUNCE_C_L", "BOUNCE_C_S",
    "BOUNCE_TR_L", "BOUNCE_TR_S",
    "BOUNCE_SQ_L", "BOUNCE_SQ_S",
}


def _parse_ts(s: str):
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


def _load_events() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with EVENTS_CSV.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            s = _parse_ts(row.get("start_ts") or "")
            e = _parse_ts(row.get("end_ts") or "")
            x = _parse_ts(row.get("extreme_ts") or "")
            if s is None or e is None or x is None:
                continue
            try:
                row["_start"] = s
                row["_end"] = e
                row["_extreme_ts"] = x
                row["_extreme_px"] = float(row.get("extreme_px") or 0)
                row["_rev_max"] = float(row.get("reversal_max_pips") or 0)
                row["_counter_px"] = float(row.get("counter_ext_px") or 0)
            except Exception:
                continue
            out.append(row)
    return out


def _load_signals() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with SIGNAL_LOG.open() as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("pair") != "GBPUSD":
                continue
            strat = str(r.get("strategy") or "")
            if strat not in V3_STRATEGIES:
                continue
            ts = _parse_ts(r.get("timestamp_open") or "")
            if ts is None:
                continue
            r["_ts"] = ts
            r["_entry"] = float(r.get("entry") or 0)
            out.append(r)
    return out


def _find_event(sig: Dict[str, Any], events: List[Dict[str, Any]], tol_min: int = 60) -> Optional[Dict[str, Any]]:
    """Return the closest event (by |timestamp_open − extreme_ts|) within
    tol_min, OR any event whose [start, end] interval contains the fire ts."""
    ts = sig["_ts"]
    best: Tuple[float, Optional[Dict[str, Any]]] = (float("inf"), None)
    for ev in events:
        if ev["_start"] <= ts <= ev["_end"]:
            return ev
        d = abs((ts - ev["_extreme_ts"]).total_seconds()) / 60.0
        if d < best[0]:
            best = (d, ev)
    if best[1] is not None and best[0] <= tol_min:
        return best[1]
    return None


def main() -> None:
    events = _load_events()
    signals = _load_signals()
    print(f"V3-family GBPUSD signals in log: {len(signals)}")
    rows: List[Dict[str, Any]] = []
    for sig in signals:
        ev = _find_event(sig, events)
        rec = {
            "ts": sig.get("timestamp_open"),
            "strategy": sig.get("strategy"),
            "direction": sig.get("direction"),
            "entry": sig["_entry"],
            "sl_pips": sig.get("sl_pips"),
            "tp1_pips": sig.get("tp1_pips"),
            "deal_id": sig.get("deal_id"),
            "event_matched": None,
            "lag_bars": None,
            "entry_vs_extreme_pips": None,
            "potential_capture_pips": None,
            "capture_ratio": None,
        }
        if ev is not None:
            rec["event_matched"] = {
                "extreme_ts": ev.get("extreme_ts"),
                "extreme_px": ev["_extreme_px"],
                "side": ev.get("side"),
                "reversal_max_pips": ev["_rev_max"],
                "first_5_ts": ev.get("first_5_ts"),
                "first_10_ts": ev.get("first_10_ts"),
                "ambiguous_5": ev.get("ambiguous_5"),
            }
            lag_s = (sig["_ts"] - ev["_extreme_ts"]).total_seconds()
            rec["lag_bars"] = round(lag_s / 300.0, 2)  # negative = fired before extreme
            # Distance between entry and extreme (mid)
            rec["entry_vs_extreme_pips"] = round(abs(sig["_entry"] - ev["_extreme_px"]), 2)
            # Potential capture: how much of the reversal was still ahead when V3 fired
            rec["potential_capture_pips"] = round(max(ev["_rev_max"] - rec["entry_vs_extreme_pips"], 0.0), 2)
            if ev["_rev_max"] > 0:
                rec["capture_ratio"] = round(rec["potential_capture_pips"] / ev["_rev_max"], 3)
        rows.append(rec)

    out_path = OUT_DIR / "v3_entry_capture.jsonl"
    with out_path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    matched = [r for r in rows if r["event_matched"]]
    unmatched = [r for r in rows if not r["event_matched"]]
    # Summarise capture distribution
    def _summ(lst, key):
        xs = sorted(x[key] for x in lst if x[key] is not None)
        if not xs:
            return None
        n = len(xs)
        return {
            "n": n,
            "min": xs[0], "max": xs[-1],
            "median": xs[n//2],
            "mean": round(sum(xs)/n, 2),
        }
    summary = {
        "n_signals_total": len(signals),
        "n_matched": len(matched),
        "n_unmatched": len(unmatched),
        "by_strategy_matched": {},
        "lag_bars_summary": _summ(matched, "lag_bars"),
        "capture_ratio_summary": _summ(matched, "capture_ratio"),
        "potential_capture_summary": _summ(matched, "potential_capture_pips"),
        "n_lag_le_0_leading": sum(1 for r in matched if r["lag_bars"] is not None and r["lag_bars"] <= 0),
        "n_lag_in_1_to_3_bars": sum(1 for r in matched if r["lag_bars"] is not None and 0 < r["lag_bars"] <= 3),
        "n_lag_gt_3_bars": sum(1 for r in matched if r["lag_bars"] is not None and r["lag_bars"] > 3),
    }
    by_strat: Dict[str, Dict[str, Any]] = {}
    for r in matched:
        s = r["strategy"]
        d = by_strat.setdefault(s, {"n": 0, "lag_bars": [], "capture_ratio": []})
        d["n"] += 1
        if r["lag_bars"] is not None: d["lag_bars"].append(r["lag_bars"])
        if r["capture_ratio"] is not None: d["capture_ratio"].append(r["capture_ratio"])
    for s, d in by_strat.items():
        d["mean_lag_bars"] = round(sum(d["lag_bars"]) / max(len(d["lag_bars"]), 1), 2) if d["lag_bars"] else None
        d["mean_capture_ratio"] = round(sum(d["capture_ratio"]) / max(len(d["capture_ratio"]), 1), 3) if d["capture_ratio"] else None
        del d["lag_bars"]; del d["capture_ratio"]
    summary["by_strategy_matched"] = by_strat
    (OUT_DIR / "v3_entry_capture_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
