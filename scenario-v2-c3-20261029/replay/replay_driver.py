"""C3 replay driver — evaluate deterministic reassessment-trigger
against recorded bars from decisions.jsonl + snapshots.jsonl.

Approach:
  * decisions.jsonl holds the recorded AI output per bar.
  * snapshots.jsonl holds the packet that was sent to the AI (so we have
    the exact interactions[].raw, nms_row, and prior that the AI saw).
  * For each bar in the sequence under test, reconstruct the C3 inputs:
      - current interactions row for the subject level
      - current NMS row
      - prior assessment (previous bar's recorded decision for the same level)
      - history up to and including the prior bar (for age tracking)
  * Call compute_reassessment_trigger() to get trigger_fired + reasons.
  * Emit per-bar replay rows for the markdown report + CSV.

The AI output is NOT re-run (budget, determinism) unless --rerun-ai is
set. The recorded AI output is treated as the baseline.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
STAGING = HERE.parent / "staging" / "agent"
sys.path.insert(0, str(STAGING))
import live_market_observer_agent_news as obs  # noqa: E402


def load_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def reconstruct_snapshot_for_bar(snapshots: list[dict], bar_ts: str,
                                   level_id: str) -> tuple[dict, dict | None]:
    """Return (interactions_row, nms_row) for a given bar and level."""
    for s in snapshots:
        if s.get("bar_ts_utc") != bar_ts:
            continue
        for inter in s.get("interactions", []):
            if inter.get("interaction_id") == level_id:
                return inter, s.get("nms")
    return None, None


def run_replay(subject_hypothesis: str, subject_direction: str,
                subject_level_id: str, start_bar: str, end_bar: str,
                decisions_path: pathlib.Path,
                snapshots_path: pathlib.Path,
                out_md: pathlib.Path, out_csv: pathlib.Path):
    decisions = load_jsonl(decisions_path)
    snapshots = load_jsonl(snapshots_path)
    decisions.sort(key=lambda r: r.get("bar_ts_utc", ""))

    # Filter to the subject streak
    streak = [r for r in decisions
              if start_bar <= r.get("bar_ts_utc", "") <= end_bar
              and r.get("hypothesis") == subject_hypothesis
              and r.get("direction") == subject_direction
              and r.get("level_id") == subject_level_id]
    if not streak:
        print(f"No bars matched streak criteria for {subject_level_id}")
        return

    rows_out = []
    for idx, dec in enumerate(streak):
        bar_ts = dec.get("bar_ts_utc")
        # Build the C3 "prior" using the previous bar's decision + compact_prior
        prior_decision = streak[idx - 1] if idx > 0 else None
        prior = obs.compact_prior(prior_decision) if prior_decision else None

        inter, nms_row = reconstruct_snapshot_for_bar(
            snapshots, bar_ts, subject_level_id)

        # Build history: all previous bars in the full decisions log
        # (not just the streak — the age counter should know about
        # pre-streak decisions on this level too)
        prior_history = [d for d in decisions
                          if d.get("bar_ts_utc", "") < bar_ts]

        if inter is None or prior is None:
            trig = {"trigger_fired": False, "reasons": [], "age_bars": 0,
                    "prior_invalidation_delta": {}}
        else:
            trig = obs.compute_reassessment_trigger(
                interactions_row=inter, nms_row=nms_row,
                prior=prior, history=prior_history)

        raw = (inter or {}).get("raw") or {}

        rows_out.append({
            "idx": idx,
            "bar_ts_utc": bar_ts,
            "closes_above": raw.get("closes_above") or 0,
            "closes_below": raw.get("closes_below") or 0,
            "consecutive_closes_beyond": raw.get("consecutive_closes_beyond") or 0,
            "distance_from_level_pips": raw.get("distance_from_level_pips") or 0,
            "max_excursion_above_pips": raw.get("max_excursion_above_pips") or 0,
            "max_excursion_below_pips": raw.get("max_excursion_below_pips") or 0,
            "close_side": raw.get("close_side") or "",
            "nms_demonstrated_direction": (nms_row or {}).get("demonstrated_direction") or "",
            "nms_hh_hl": f"{'1' if (nms_row or {}).get('hh') else '0'}/{'1' if (nms_row or {}).get('hl') else '0'}",
            "nms_lh_ll": f"{'1' if (nms_row or {}).get('lh') else '0'}/{'1' if (nms_row or {}).get('ll') else '0'}",
            "age_bars": trig.get("age_bars"),
            "trigger_fired": "YES" if trig.get("trigger_fired") else "no",
            "n_reasons": len(trig.get("reasons") or []),
            "reasons": " | ".join(trig.get("reasons") or [])[:300],
            "inv_delta_fired": sum(1 for v in (trig.get("prior_invalidation_delta") or {}).values() if v == "FIRED"),
            "inv_delta_partial": sum(1 for v in (trig.get("prior_invalidation_delta") or {}).values() if v == "PARTIAL"),
            "baseline_hypothesis": dec.get("hypothesis"),
            "baseline_direction": dec.get("direction"),
            "baseline_n_counter_evidence": len(dec.get("counter_evidence") or []),
        })

    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        for r in rows_out:
            w.writerow(r)

    # Summary + first-trigger-fire + aggregate stats
    first_trigger = next((r for r in rows_out if r["trigger_fired"] == "YES"), None)
    n_total = len(rows_out)
    n_triggered = sum(1 for r in rows_out if r["trigger_fired"] == "YES")

    print(f"Wrote {out_csv} with {n_total} rows.")
    print(f"  First trigger fire: {first_trigger['bar_ts_utc'] if first_trigger else '(never)'} "
          f"(idx={first_trigger['idx'] if first_trigger else -1})")
    print(f"  Bars triggered: {n_triggered} / {n_total}")

    return rows_out, first_trigger


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", required=True,
                     help="e.g. '2026-10-27:WATCH_REJECTION:SELL:b30a32a8d645a176'")
    ap.add_argument("--decisions", default="/mnt/volume_lon1_1778405456698/research/live_obs/journal/decisions.jsonl")
    ap.add_argument("--snapshots", default="/mnt/volume_lon1_1778405456698/research/live_obs/journal/snapshots.jsonl")
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    day, hyp, direction, level_id = args.subject.split(":")
    run_replay(hyp, direction, level_id,
                 start_bar=f"{day}T00:00:00+00:00",
                 end_bar=f"{day}T23:59:59+00:00",
                 decisions_path=pathlib.Path(args.decisions),
                 snapshots_path=pathlib.Path(args.snapshots),
                 out_md=pathlib.Path(args.out_md),
                 out_csv=pathlib.Path(args.out_csv))


if __name__ == "__main__":
    main()
