"""Parallel shadow comparison — run the deployed executor and the
proposed early-entry executor on the SAME incoming scenario stream,
record both lifecycles in SEPARATE journals, and emit a differential
report.

READ-ONLY research driver. No broker submission paths. Can be invoked
manually with a dry-run flag to replay historical scenarios through
BOTH executors into isolated sandbox directories.

Diff categories (reported for every scenario that fired in either
executor):

  * EARLIER_PROFITABLE   — new mech opened sooner than deployed and
                            closed profitable
  * EARLIER_FALSE        — new mech opened sooner but closed loss
  * REJECTED_EXHAUSTED   — new mech rejected on quality gate; deployed
                            fired (we see whether deployed won or lost)
  * NEW_FIRED_DEPLOYED_WAITING — new mech opened, deployed still
                            WAITING_FOR_ENTRY in the same sample
  * MISSED_BY_NEW        — deployed fired, new mech never did
  * SAME_OUTCOME         — both opened and closed the same direction
                            with identical exit_reason
  * DIVERGENT            — any other mismatch

HARD CONTRACTS:
  * Cannot touch /mnt/.../shadow_exec/ (deployed journals).
  * Cannot touch /mnt/.../shadow_exec_early/ (live early journals,
    reserved for a future deploy).
  * Writes only to the directory passed via --out.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
IMPL = HERE.parent / "impl"
sys.path.insert(0, str(IMPL))
import early_entry as ee  # noqa: E402

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
sys.path.insert(0, str(AGENT))
import shadow_execution as sx
from scenario_recommendation import build_trade_recommendation

UTC = dt.timezone.utc


def _parse(s):
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception: return None


def _primary(row):
    for o in (row.get("opportunities") or []):
        if isinstance(o, dict) and (o.get("direction") or "").upper() in ("BUY", "SELL"):
            return o
    return None


def _close_at_or_before(ts, candles):
    out = None
    for c in candles:
        if c["ts_close"] <= ts: out = c
        else: break
    return (out or {}).get("c")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=pathlib.Path, required=True,
                     help="output sandbox dir (will be created; MUST NOT be "
                          "the deployed shadow_exec dir)")
    ap.add_argument("--mode", default="M1_WITH_GATE",
                     choices=["M1_WITH_GATE", "A", "B", "C"],
                     help="early-entry mechanism to compare against deployed")
    ap.add_argument("--max-scenarios", type=int, default=200)
    args = ap.parse_args(argv)

    out = args.out.resolve()
    # Safety — refuse to touch production journal dirs
    for forbidden in (
        pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec"),
        pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec_early"),
    ):
        if out == forbidden or forbidden in out.parents:
            raise SystemExit(f"refusing to write to production path: {out}")
    out.mkdir(parents=True, exist_ok=True)
    deployed_dir = out / "deployed"
    early_dir    = out / "early"
    deployed_dir.mkdir(exist_ok=True)
    early_dir.mkdir(exist_ok=True)

    scen_path = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl")
    dec_path  = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal/decisions.jsonl")
    snap_path = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal/snapshots.jsonl")

    scens = []
    for ln in scen_path.read_text().splitlines():
        ln = ln.strip()
        if ln:
            try: scens.append(json.loads(ln))
            except Exception: pass

    decisions = []
    for ln in dec_path.read_text().splitlines():
        ln = ln.strip()
        if ln:
            try: decisions.append(json.loads(ln))
            except Exception: pass

    snapshots = []
    for ln in snap_path.read_text().splitlines():
        ln = ln.strip()
        if ln:
            try: snapshots.append(json.loads(ln))
            except Exception: pass

    candles = sorted(sx.load_candles(), key=lambda c: c["ts_open"])
    now = dt.datetime.now(UTC)

    # One row per scenario — pick first-READY (same identity logic as
    # the backtest).
    by_sid = defaultdict(list)
    for s in scens:
        if s.get("scenario_id"):
            by_sid[s["scenario_id"]].append(s)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda r: r.get("revision_idx") or 0)

    def _first_ready(revs):
        for r in revs:
            if (r.get("publication_decision") or {}).get("decision", "").upper() != "VALID":
                continue
            tp = r.get("trade_proposal") or {}
            if not tp:
                p = _primary(r) or {}
                tp = p.get("trade_proposal") or {}
            if not tp or any(tp.get(k) is None for k in ("entry_price", "stop_price", "target_price")):
                continue
            d = (tp.get("direction") or "").upper()
            if d not in ("BUY", "SELL"): continue
            e, s, t = tp["entry_price"], tp["stop_price"], tp["target_price"]
            if d == "BUY" and not (s < e < t): continue
            if d == "SELL" and not (t < e < s): continue
            return r
        return None

    comparison_rows = []
    for sid in sorted(by_sid)[:args.max_scenarios]:
        fr = _first_ready(by_sid[sid])
        if not fr:
            continue
        gen_dt = _parse(fr.get("generated_at_utc"))
        snap_at_gen = next((s for s in snapshots
                              if _parse(s.get("bar_ts_utc") or "")
                                 and _parse(s.get("bar_ts_utc"))
                                 >= (gen_dt - dt.timedelta(minutes=10))), snapshots[0] if snapshots else {})
        primary = next((d for d in decisions
                          if _parse(d.get("evaluated_at_utc") or "")
                             and _parse(d.get("evaluated_at_utc"))
                             <= (gen_dt + dt.timedelta(minutes=1))), decisions[-1] if decisions else {})
        rec = build_trade_recommendation(scenario_row=fr, snapshot=snap_at_gen,
                                            primary_decision=primary)
        decision_price = _close_at_or_before(gen_dt, candles)

        # --- Deployed executor replay (into sandbox deployed_dir) ---
        dep_res = sx.process_proposal(
            recommendation=rec, shadow_dir=deployed_dir,
            candles=candles, now_utc=now, max_fill_lookback_seconds=0)

        # --- Early executor replay (into sandbox early_dir) ---
        if args.mode == "M1_WITH_GATE":
            # Simulate M1+gate inline: use deployed fill, then quality-gate
            if dep_res.get("position") in ("CLOSED", "OPENED_AWAITING_EXIT"):
                sim_entry = dep_res.get("entry_price") or dep_res.get("simulated_entry")
                # Deployed exposes entry via positions journal only; re-read
                # the just-written OPEN row to recover simulated_entry.
                pos_rows = [json.loads(ln) for ln in
                              (deployed_dir / "shadow_positions.jsonl").read_text().splitlines()
                              if ln.strip()]
                open_row = next((r for r in reversed(pos_rows)
                                   if r.get("scenario_id") == sid and r.get("event") == "OPEN"), {})
                sim_entry = open_row.get("simulated_entry_price")
                entry_bar_ts = _parse(open_row.get("entry_bar_ts_utc") or "")
                half = ee.spread_half_pips((entry_bar_ts or now)
                                              + dt.timedelta(minutes=5))
                tp = fr["trade_proposal"]
                ok, reason, metrics = ee.opp_quality(
                    sim_entry, tp["stop_price"], tp["target_price"],
                    (_primary(fr) or {}).get("direction") or tp.get("direction"),
                    half, decision_price)
                early_res = {"gate": "ok" if ok else reason,
                              "mimics": "M1" if ok else "GATE_REJECT",
                              "simulated_entry": sim_entry if ok else None,
                              "metrics": metrics}
            else:
                early_res = {"gate": "n/a (deployed WAIT)", "mimics": "WAIT"}
        else:
            early_res = ee.process_proposal(
                scenario_row=fr, primary_decision=primary,
                decision_price=decision_price,
                candles=candles, mode=args.mode, shadow_dir=early_dir,
                now_utc=now, max_fill_lookback_seconds=0)

        # --- Classify diff ---
        comparison_rows.append(_classify(sid, fr, dep_res, early_res, args.mode))

    # Emit CSV
    out_csv = out / "comparison.csv"
    if comparison_rows:
        keys = list(comparison_rows[0].keys())
        with out_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in comparison_rows:
                w.writerow(r)

    # Summary
    cats = defaultdict(int)
    for r in comparison_rows:
        cats[r["category"]] += 1
    print(f"shadow-compare mode={args.mode} out={out}")
    print(f"scenarios compared: {len(comparison_rows)}")
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {v:>3}  {k}")
    print(f"csv: {out_csv}")


def _classify(sid, fr, dep_res, early_res, mode):
    dep_pos = dep_res.get("position")
    row = {
        "scenario_id": sid, "revision_idx": fr.get("revision_idx"),
        "first_ready_ts": fr.get("generated_at_utc"),
        "deployed_position": dep_pos,
        "deployed_exit_reason": dep_res.get("exit_reason"),
        "deployed_gross_pips": dep_res.get("gross_pips"),
        "deployed_entry_bar": dep_res.get("entry_bar_ts_utc"),
    }
    if mode == "M1_WITH_GATE":
        gate = early_res.get("gate")
        row["early_mode"] = mode
        row["early_gate"] = gate
        if dep_pos == "WAITING_FOR_ENTRY":
            cat = "DEPLOYED_WAITING"
        elif dep_pos is None or (dep_res.get("readiness") not in (None, "READY")):
            cat = "DEPLOYED_SKIPPED"
        elif gate == "ok":
            # Same fill under gate — classify by outcome
            if dep_res.get("exit_reason") == "TARGET_HIT":
                cat = "SAME_OUTCOME_TARGET"
            elif dep_res.get("exit_reason") == "STOP_HIT":
                cat = "SAME_OUTCOME_STOP"
            else:
                cat = "SAME_OUTCOME_OPEN"
        else:
            # Gate rejected what deployed took — differentiate outcome
            if dep_res.get("exit_reason") == "TARGET_HIT":
                cat = "GATE_REJECTED_WINNER"
            elif dep_res.get("exit_reason") == "STOP_HIT":
                cat = "GATE_REJECTED_LOSER_AVOIDED"
            else:
                cat = "GATE_REJECTED_UNFINISHED"
    else:
        # A/B/C mechanisms
        early_pos = early_res.get("position")
        row["early_mode"] = mode
        row["early_position"] = early_pos
        row["early_exit_reason"] = early_res.get("exit_reason")
        row["early_gross_pips"] = early_res.get("gross_pips")
        row["early_entry_bar"] = early_res.get("entry_bar_ts_utc")

        def _bar_lt(a, b):
            if a and b: return a < b
            return False

        if early_pos == "CLOSED" and dep_pos == "WAITING_FOR_ENTRY":
            cat = "NEW_FIRED_DEPLOYED_WAITING"
        elif early_pos in ("CLOSED", "OPENED_AWAITING_EXIT") and dep_pos in ("CLOSED", "OPENED_AWAITING_EXIT"):
            if _bar_lt(early_res.get("entry_bar_ts_utc"), dep_res.get("entry_bar_ts_utc")):
                if (early_res.get("gross_pips") or 0) > 0:
                    cat = "EARLIER_PROFITABLE"
                else:
                    cat = "EARLIER_FALSE"
            else:
                cat = "SAME_OR_LATER_ENTRY"
        elif early_pos == "REJECTED":
            cat = "REJECTED_EXHAUSTED" if "EXHAUSTION" in (early_res.get("reason") or "") else "REJECTED_QUALITY"
        elif dep_pos in ("CLOSED", "OPENED_AWAITING_EXIT") and early_pos not in ("CLOSED", "OPENED_AWAITING_EXIT"):
            cat = "MISSED_BY_NEW"
        else:
            cat = "DIVERGENT"
    row["category"] = cat
    return row


if __name__ == "__main__":
    main()
