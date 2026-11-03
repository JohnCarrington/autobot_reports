"""Threshold-sensitivity + overfitting audit for the Scenario V2
opportunity-quality gate.

For each (MIN_NET_RR, MIN_NET_REWARD, MAX_EXHAUSTION, spread_rt) point
in a grid, replay the 13 first-READY scenarios through M1 (deployed
breakout entry) + gate, and record:

  * fills
  * win rate
  * gross pips, net pips
  * profit factor
  * mean + median pip outcome
  * MDD

Then flag whether the DEFAULT thresholds (0.75 / 3.0 / 0.70 / 2.8 rt)
sit near a local maximum (likely overfit) or on a broad plateau.

Also sweeps *individual* thresholds separately with the other two at
their defaults, so single-parameter sensitivity is visible.

Writes:
  * data/threshold_sensitivity_grid.csv
  * data/threshold_sensitivity_1d.csv
  * stdout: summary of the overfitting assessment

READ-ONLY research; no broker calls, no production writes.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import sys
import statistics as st
from collections import defaultdict
from itertools import product

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
sys.path.insert(0, str(AGENT))
import shadow_execution as sx

HERE = pathlib.Path(__file__).resolve().parent
OUT_GRID = HERE.parent / "data" / "threshold_sensitivity_grid.csv"
OUT_1D = HERE.parent / "data" / "threshold_sensitivity_1d.csv"
OUT_GRID.parent.mkdir(parents=True, exist_ok=True)

UTC = dt.timezone.utc
SCEN = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl")

# Default thresholds from EARLY_ENTRY_DESIGN.md
DEFAULT = {"MIN_NET_RR": 0.75, "MIN_NET_REWARD_PIPS": 3.0,
            "MAX_EXHAUSTION": 0.70, "SPREAD_RT_PIPS": 2.8}


def _parse(s):
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception: return None


def _primary(row):
    for o in (row.get("opportunities") or []):
        if isinstance(o, dict) and (o.get("direction") or "").upper() in ("BUY", "SELL"):
            return o
    return None


def _tp(row):
    tp = row.get("trade_proposal") or {}
    if tp: return tp
    return (_primary(row) or {}).get("trade_proposal") or {}


def _close_at_or_before(ts, candles):
    out = None
    for c in candles:
        if c["ts_close"] <= ts: out = c
        else: break
    return (out or {}).get("c")


def _first_ready(revs):
    for r in revs:
        if (r.get("publication_decision") or {}).get("decision", "").upper() != "VALID":
            continue
        tp = _tp(r)
        if not tp: continue
        if any(tp.get(k) is None for k in ("entry_price", "stop_price", "target_price")):
            continue
        d = (tp.get("direction") or "").upper()
        if d not in ("BUY", "SELL"): continue
        e, s, t = tp["entry_price"], tp["stop_price"], tp["target_price"]
        if d == "BUY" and not (s < e < t): continue
        if d == "SELL" and not (t < e < s): continue
        return r
    return None


def _simulate_M1(gen_dt, direction, entry, stop, target, candles, now):
    """Deployed-executor-equivalent: first bar close beyond entry."""
    post = [c for c in candles if c["ts_close"] > gen_dt and c["ts_close"] <= now]
    d = direction.upper()
    for bar in post:
        if (d == "BUY" and bar["c"] > entry) or (d == "SELL" and bar["c"] < entry):
            # Lifecycle
            monitor = [c for c in candles
                        if c["ts_open"] > bar["ts_open"] and c["ts_close"] <= now]
            sim_entry = bar["c"]
            for c in monitor:
                hs = (c["h"] >= stop) if d == "SELL" else (c["l"] <= stop)
                ht = (c["l"] <= target) if d == "SELL" else (c["h"] >= target)
                if hs and ht:
                    return {"status": "closed", "exit": "AMBIGUOUS",
                             "sim_entry": sim_entry, "gross": 0.0}
                if hs:
                    g = round((stop - sim_entry) * (1 if d == "BUY" else -1), 1)
                    return {"status": "closed", "exit": "STOP",
                             "sim_entry": sim_entry, "gross": g}
                if ht:
                    g = round((target - sim_entry) * (1 if d == "BUY" else -1), 1)
                    return {"status": "closed", "exit": "TARGET",
                             "sim_entry": sim_entry, "gross": g}
            return {"status": "open", "sim_entry": sim_entry}
    return {"status": "wait"}


def _gate(exec_price, stop, target, direction, half_spread,
            decision_price, min_net_rr, min_net_reward, max_exhaustion):
    d = direction.upper()
    sign = 1 if d == "BUY" else -1
    remaining = (target - exec_price) * sign
    risk = (exec_price - stop) * sign
    if remaining <= 0 or risk <= 0:
        return False
    net_reward = remaining - 2 * half_spread
    if net_reward < min_net_reward: return False
    net_rr = net_reward / (risk + 2 * half_spread)
    if net_rr < min_net_rr: return False
    full_range = (target - decision_price) * sign
    if full_range <= 0: return False
    consumed = (exec_price - decision_price) * sign
    if (consumed / full_range) > max_exhaustion: return False
    return True


def _profit_factor(wins, losses):
    if not losses: return float("inf") if wins else 0.0
    return round(sum(wins) / abs(sum(losses)), 3)


def _max_drawdown(gains):
    cum = 0.0; peak = 0.0; dd = 0.0
    for g in gains:
        cum += g
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return round(dd, 1)


def _evaluate(scenarios, candles, now, min_net_rr, min_net_reward,
                 max_exhaustion, spread_rt_pips):
    half = spread_rt_pips / 2.0
    stats = {"fills": 0, "targets": 0, "stops": 0, "ambiguous": 0,
             "open": 0, "rejected": 0, "wait": 0,
             "gross": 0.0, "net": 0.0, "wins_pips": [], "losses_pips": [],
             "gains_order": []}
    for scen in scenarios:
        fr = scen["first_ready"]
        gen_dt = _parse(fr.get("generated_at_utc"))
        tp = _tp(fr)
        direction = (tp.get("direction") or "").upper()
        entry = tp["entry_price"]; stop = tp["stop_price"]; target = tp["target_price"]
        decision_price = _close_at_or_before(gen_dt, candles) if gen_dt else None

        m1 = _simulate_M1(gen_dt, direction, entry, stop, target, candles, now)
        if m1["status"] == "wait":
            stats["wait"] += 1; continue
        if m1["status"] == "open":
            stats["open"] += 1; continue

        # Gate uses the actual sim_entry (post-breakout bar close)
        gate_ok = _gate(m1["sim_entry"], stop, target, direction, half,
                           decision_price, min_net_rr, min_net_reward,
                           max_exhaustion)
        if not gate_ok:
            stats["rejected"] += 1
            continue

        stats["fills"] += 1
        gross = m1["gross"]
        exit_reason = m1["exit"]
        if exit_reason == "TARGET":
            stats["targets"] += 1
            stats["wins_pips"].append(gross)
        elif exit_reason == "STOP":
            stats["stops"] += 1
            stats["losses_pips"].append(gross)
        else:
            stats["ambiguous"] += 1
            gross = 0.0

        stats["gross"] += gross
        stats["net"] += gross - spread_rt_pips
        stats["gains_order"].append(gross)
    stats["win_rate"] = round(100 * stats["targets"] / stats["fills"], 1) if stats["fills"] else 0
    stats["pf"] = _profit_factor(stats["wins_pips"], stats["losses_pips"])
    stats["mean_pips"] = round(st.mean(stats["gains_order"]), 2) if stats["gains_order"] else 0
    stats["median_pips"] = round(st.median(stats["gains_order"]), 2) if stats["gains_order"] else 0
    stats["mdd"] = _max_drawdown(stats["gains_order"])
    return stats


def _write_csv(path, rows):
    if not rows: return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows: w.writerow(r)


def main():
    candles = sorted(sx.load_candles(), key=lambda c: c["ts_open"])
    now = dt.datetime.now(UTC)
    all_revs = []
    for ln in SCEN.read_text().splitlines():
        if ln.strip():
            try: all_revs.append(json.loads(ln))
            except Exception: pass
    by_sid = defaultdict(list)
    for s in all_revs:
        if s.get("scenario_id"):
            by_sid[s["scenario_id"]].append(s)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda r: r.get("revision_idx") or 0)
    scenarios = []
    for sid, revs in by_sid.items():
        fr = _first_ready(revs)
        if fr:
            scenarios.append({"sid": sid, "first_ready": fr})
    print(f"loaded {len(scenarios)} first-READY scenarios, {len(candles)} candles")

    # ------------------------------------------------------------------
    # Full grid
    # ------------------------------------------------------------------
    rr_grid       = [0.00, 0.25, 0.50, 0.60, 0.75, 0.85, 1.00, 1.25]  # 8
    reward_grid   = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]                # 7
    exhaustion_g  = [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]              # 6
    spread_grid   = [0.5, 1.0, 1.4, 2.0, 2.8, 4.0]                     # 6

    grid_rows = []
    for rr, rew, ex, sp in product(rr_grid, reward_grid, exhaustion_g, spread_grid):
        s = _evaluate(scenarios, candles, now, rr, rew, ex, sp)
        row = {"min_net_rr": rr, "min_net_reward": rew,
               "max_exhaustion": ex, "spread_rt": sp,
               "fills": s["fills"], "targets": s["targets"], "stops": s["stops"],
               "rejected": s["rejected"], "waiting": s["wait"] + s["open"],
               "win_rate_pct": s["win_rate"], "gross_pips": round(s["gross"], 1),
               "net_pips": round(s["net"], 1), "pf": s["pf"],
               "mean_pips": s["mean_pips"], "mdd_pips": s["mdd"]}
        grid_rows.append(row)
    _write_csv(OUT_GRID, grid_rows)
    print(f"wrote {len(grid_rows)} grid rows → {OUT_GRID}")

    # ------------------------------------------------------------------
    # 1-D sweeps (other 2 thresholds fixed at defaults)
    # ------------------------------------------------------------------
    one_d_rows = []
    for name, values, key in (
        ("MIN_NET_RR",        rr_grid,       "min_net_rr"),
        ("MIN_NET_REWARD",    reward_grid,   "min_net_reward"),
        ("MAX_EXHAUSTION",    exhaustion_g,  "max_exhaustion"),
        ("SPREAD_RT_PIPS",    spread_grid,   "spread_rt"),
    ):
        for v in values:
            kw = {"min_net_rr": DEFAULT["MIN_NET_RR"],
                  "min_net_reward": DEFAULT["MIN_NET_REWARD_PIPS"],
                  "max_exhaustion": DEFAULT["MAX_EXHAUSTION"],
                  "spread_rt_pips": DEFAULT["SPREAD_RT_PIPS"]}
            kw[key] = v
            s = _evaluate(scenarios, candles, now, kw["min_net_rr"],
                            kw["min_net_reward"], kw["max_exhaustion"],
                            kw["spread_rt_pips"])
            one_d_rows.append({
                "parameter": name, "value": v,
                "fills": s["fills"], "win_rate_pct": s["win_rate"],
                "gross_pips": round(s["gross"], 1),
                "net_pips": round(s["net"], 1), "pf": s["pf"],
                "mdd_pips": s["mdd"], "rejected": s["rejected"]})
    _write_csv(OUT_1D, one_d_rows)
    print(f"wrote {len(one_d_rows)} 1-D rows → {OUT_1D}")

    # ------------------------------------------------------------------
    # Overfitting assessment
    # ------------------------------------------------------------------
    # Is the default on a sharp peak?
    default_s = _evaluate(scenarios, candles, now,
                             DEFAULT["MIN_NET_RR"], DEFAULT["MIN_NET_REWARD_PIPS"],
                             DEFAULT["MAX_EXHAUSTION"], DEFAULT["SPREAD_RT_PIPS"])
    print()
    print("Default thresholds (0.75 / 3.0 / 0.70 / spread 2.8):")
    print(f"  fills={default_s['fills']} win%={default_s['win_rate']} "
           f"gross={round(default_s['gross'],1)} net={round(default_s['net'],1)} "
           f"pf={default_s['pf']} mdd={default_s['mdd']}")
    # Compare to grid: how many parameter combinations produce STRICTLY
    # BETTER net pips?
    better = [r for r in grid_rows if r["net_pips"] > round(default_s["net"], 1)]
    print(f"  grid cells with higher net than default: {len(better)}/{len(grid_rows)}")
    if better:
        best = max(grid_rows, key=lambda r: r["net_pips"])
        print(f"  best grid cell: net={best['net_pips']} at "
               f"rr={best['min_net_rr']} rew={best['min_net_reward']} "
               f"ex={best['max_exhaustion']} spread={best['spread_rt']}  "
               f"fills={best['fills']} win%={best['win_rate_pct']}")

    # Plateau check — look at the 1-D sweep around defaults
    print()
    print("1-D sensitivity around defaults:")
    for name in ("MIN_NET_RR", "MIN_NET_REWARD", "MAX_EXHAUSTION", "SPREAD_RT_PIPS"):
        pts = [r for r in one_d_rows if r["parameter"] == name]
        print(f"  {name}:")
        for p in pts:
            marker = "  *" if (
                (name == "MIN_NET_RR" and p["value"] == DEFAULT["MIN_NET_RR"]) or
                (name == "MIN_NET_REWARD" and p["value"] == DEFAULT["MIN_NET_REWARD_PIPS"]) or
                (name == "MAX_EXHAUSTION" and p["value"] == DEFAULT["MAX_EXHAUSTION"]) or
                (name == "SPREAD_RT_PIPS" and p["value"] == DEFAULT["SPREAD_RT_PIPS"])
            ) else "   "
            print(f"    {marker} value={p['value']:<5} fills={p['fills']:>2} "
                   f"win%={p['win_rate_pct']:>5} net={p['net_pips']:>6.1f} pf={p['pf']}")


if __name__ == "__main__":
    main()
