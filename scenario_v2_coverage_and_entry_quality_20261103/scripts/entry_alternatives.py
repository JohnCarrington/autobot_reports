"""Scenario V2 — alternative entry mechanisms comparison (read-only).

Simulates five entry mechanisms over the same scenarios and same market
history. Target and stop are UNCHANGED (we're not re-engineering the
strategy — only comparing fill rules). Spread is applied symmetrically.

Mechanisms:
  M1  Current — close-above-entry breakout (what the deployed executor does).
  M2  Fill at first-READY revision — buy/sell at the bar whose close is
      at or before first_ready_ts, no further confirmation.
  M3  First qualifying M5 bar in predicted direction — enter at the close
      of the first post-first-READY bar whose close is BEYOND the first-
      READY market-close in the trade direction (any pip is enough).
  M4  Pullback entry — after first-READY, wait for one bar whose close
      is COUNTER-direction (a pullback), then enter at the next
      in-direction bar's close. Prevents entering at a breakout extreme.
  M5  Current breakout + minimum-R:R eligibility — M1, but only if the
      proposal's reward:risk ≥ 1.0. (Avoids trades like R:R 0.15.)

Lookahead safety: every mechanism uses only bars whose ts_close is
strictly after first_ready_ts.

Spread: 1.4 pip half-spread per leg assumed (= 2.8 pip round-trip) —
historical mid-close fills, no live broker data. Set via SPREAD_HALF_PIP.
Reported pips are MID-based gross pips; net applies −2*half_spread.

Non-goals: methodology changes, parameter optimisation. We use fixed
rules and the deployed proposal's own stop/target.

Output: ENTRY_ALTERNATIVES_COMPARISON.csv with one row per
(scenario_id, mechanism), plus a stdout summary.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import sys
import statistics as st
from collections import defaultdict

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
sys.path.insert(0, str(AGENT))
import shadow_execution as se

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "ENTRY_ALTERNATIVES_COMPARISON.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

UTC = dt.timezone.utc
SPREAD_HALF_PIP = 1.4  # IG retail GBP/USD typical half-spread (session avg)
# NOTE: this is a general sweep assumption; the readme discloses the fact
# that contemporaneous broker data is NOT available. For spread-sensitive
# conclusions we also report per-trade with and without the spread.


SCEN = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl")
rows = []
for ln in SCEN.read_text().splitlines():
    ln = ln.strip()
    if ln:
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass

by_sid = defaultdict(list)
for r in rows:
    sid = r.get("scenario_id")
    if sid:
        by_sid[sid].append(r)
for sid in by_sid:
    by_sid[sid].sort(key=lambda r: r.get("generated_at_utc") or "")

candles = sorted(se.load_candles(), key=lambda c: c["ts_open"])


def _parse(s):
    if not s: return None
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception: return None


def _primary(row):
    for o in (row.get("opportunities") or []):
        if isinstance(o, dict):
            d = (o.get("direction") or "").upper()
            if d in ("BUY", "SELL"):
                return o
    return None


def _tp(row):
    tp = row.get("trade_proposal") or {}
    if tp:
        return tp
    p = _primary(row) or {}
    return p.get("trade_proposal") or {}


def _first_ready(revs):
    for r in revs:
        pub = (r.get("publication_decision") or {}).get("decision", "").upper()
        if pub != "VALID":
            continue
        tp = _tp(r)
        if not tp:
            continue
        if any(tp.get(k) is None for k in ("entry_price", "stop_price", "target_price")):
            continue
        if (tp.get("direction") or "").upper() not in ("BUY", "SELL"):
            continue
        # Enforce geometry — avoid replaying trades the production
        # validator would have blocked anyway.
        d = (tp.get("direction") or "").upper()
        e, s, t = tp["entry_price"], tp["stop_price"], tp["target_price"]
        if d == "BUY" and not (s < e < t):
            continue
        if d == "SELL" and not (t < e < s):
            continue
        return r
    return None


def _bar_close_at_or_before(ts: dt.datetime):
    out = None
    for c in candles:
        if c["ts_close"] <= ts:
            out = c
        else:
            break
    return out


def _simulate_from_entry(entry_bar, direction, stop, target):
    monitor = [c for c in candles if c["ts_open"] > entry_bar["ts_open"]]
    sim_entry = entry_bar["c"]
    d = direction.upper()
    for c in monitor:
        if d == "BUY":
            hs = c["l"] <= stop
            ht = c["h"] >= target
        else:
            hs = c["h"] >= stop
            ht = c["l"] <= target
        if hs and ht:
            return {"status": "CLOSED", "exit_reason": "AMBIGUOUS",
                    "entry_bar_ts": entry_bar["ts_open"].isoformat(),
                    "simulated_entry": sim_entry, "exit_price": c["c"],
                    "gross_pips_mid": 0.0}
        if hs:
            g = round((stop - sim_entry) * (1 if d == "BUY" else -1), 1)
            return {"status": "CLOSED", "exit_reason": "STOP_HIT",
                    "entry_bar_ts": entry_bar["ts_open"].isoformat(),
                    "simulated_entry": sim_entry, "exit_price": stop,
                    "gross_pips_mid": g}
        if ht:
            g = round((target - sim_entry) * (1 if d == "BUY" else -1), 1)
            return {"status": "CLOSED", "exit_reason": "TARGET_HIT",
                    "entry_bar_ts": entry_bar["ts_open"].isoformat(),
                    "simulated_entry": sim_entry, "exit_price": target,
                    "gross_pips_mid": g}
    return {"status": "OPEN",
            "entry_bar_ts": entry_bar["ts_open"].isoformat(),
            "simulated_entry": sim_entry}


def mech_M1(fr_ts, direction, entry, stop, target):
    """Close-above-entry breakout (deployed executor)."""
    d = direction.upper()
    post = [c for c in candles if c["ts_close"] > fr_ts]
    for c in post:
        if (d == "BUY" and c["c"] > entry) or (d == "SELL" and c["c"] < entry):
            return _simulate_from_entry(c, direction, stop, target)
    return {"status": "no_fill"}


def mech_M2(fr_ts, direction, entry, stop, target):
    """Immediate fill at first-READY — enter at the first bar whose
    ts_close ≥ fr_ts (i.e. the first completed bar after the AI's call)."""
    for c in candles:
        if c["ts_close"] >= fr_ts:
            return _simulate_from_entry(c, direction, stop, target)
    return {"status": "no_fill"}


def mech_M3(fr_ts, direction, entry, stop, target):
    """First qualifying M5 in-direction bar after first-READY — enter at
    the close of the first bar whose close is beyond fr_bar_close in the
    predicted direction."""
    fr_bar = _bar_close_at_or_before(fr_ts)
    if fr_bar is None:
        return {"status": "no_fill"}
    anchor = fr_bar["c"]
    d = direction.upper()
    post = [c for c in candles if c["ts_close"] > fr_ts]
    for c in post:
        if (d == "BUY" and c["c"] > anchor) or (d == "SELL" and c["c"] < anchor):
            return _simulate_from_entry(c, direction, stop, target)
    return {"status": "no_fill"}


def mech_M4(fr_ts, direction, entry, stop, target):
    """Pullback entry — wait for one bar whose close is COUNTER to the
    predicted direction (a pullback vs fr_bar_close), then enter at the
    next in-direction bar's close."""
    fr_bar = _bar_close_at_or_before(fr_ts)
    if fr_bar is None:
        return {"status": "no_fill"}
    anchor = fr_bar["c"]
    d = direction.upper()
    post = [c for c in candles if c["ts_close"] > fr_ts]
    seen_pullback = False
    for c in post:
        counter = (d == "BUY" and c["c"] < anchor) or (d == "SELL" and c["c"] > anchor)
        indir = (d == "BUY" and c["c"] > anchor) or (d == "SELL" and c["c"] < anchor)
        if counter:
            seen_pullback = True
            continue
        if seen_pullback and indir:
            return _simulate_from_entry(c, direction, stop, target)
    return {"status": "no_fill"}


def mech_M5(fr_ts, direction, entry, stop, target):
    """M1 but only taken when the proposed reward:risk ≥ 1.0."""
    reward = abs(target - entry)
    risk = abs(entry - stop)
    if risk <= 0 or (reward / risk) < 1.0:
        return {"status": "skipped_rr"}
    return mech_M1(fr_ts, direction, entry, stop, target)


MECHANISMS = {
    "M1_breakout_current":          mech_M1,
    "M2_immediate_first_ready":     mech_M2,
    "M3_first_m5_in_direction":     mech_M3,
    "M4_pullback_then_direction":   mech_M4,
    "M5_breakout_min_rr_1_0":       mech_M5,
}


out_rows = []
for sid, revs in sorted(by_sid.items()):
    fr = _first_ready(revs)
    if not fr:
        continue
    tp = _tp(fr)
    fr_ts = _parse(fr.get("generated_at_utc"))
    direction = (tp.get("direction") or "").upper()
    e = tp["entry_price"]; s = tp["stop_price"]; t = tp["target_price"]
    reward = round(abs(t - e), 1)
    risk = round(abs(e - s), 1)
    rr = round(reward / risk, 2) if risk else None

    for name, fn in MECHANISMS.items():
        r = fn(fr_ts, direction, e, s, t)
        gross = r.get("gross_pips_mid")
        net = None
        if gross is not None and r.get("exit_reason") != "AMBIGUOUS":
            net = round(gross - 2 * SPREAD_HALF_PIP, 1)
        out_rows.append({
            "scenario_id": sid,
            "mechanism": name,
            "first_ready_ts": fr.get("generated_at_utc"),
            "direction": direction,
            "entry_proposed": e,
            "stop": s,
            "target": t,
            "reward_pips": reward,
            "risk_pips": risk,
            "rr": rr,
            "status": r.get("status"),
            "simulated_entry": r.get("simulated_entry"),
            "entry_bar_ts": r.get("entry_bar_ts"),
            "exit_reason": r.get("exit_reason"),
            "gross_pips_mid": gross,
            "net_pips_ig_spread_1_4": net,
        })


# Write CSV
if out_rows:
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"wrote {len(out_rows)} rows → {OUT}")

# Stdout summary table
by_mech = defaultdict(list)
for r in out_rows:
    by_mech[r["mechanism"]].append(r)
print()
print(f"spread assumption: half-pip={SPREAD_HALF_PIP}, round-trip={2*SPREAD_HALF_PIP}p")
print()
print(f"{'Mechanism':<30}  {'trades':>6}  {'fills':>6}  {'closed':>6}  {'targets':>7}  {'stops':>6}  {'win%':>5}  {'gross':>7}  {'net':>7}  {'mean':>6}")
print("-" * 110)
for name in MECHANISMS:
    rows_m = by_mech[name]
    trades = len(rows_m)
    fills = sum(1 for r in rows_m if r["status"] in ("CLOSED", "OPEN"))
    closed = [r for r in rows_m if r["status"] == "CLOSED" and r.get("exit_reason") != "AMBIGUOUS"]
    targets = sum(1 for r in closed if r["exit_reason"] == "TARGET_HIT")
    stops = sum(1 for r in closed if r["exit_reason"] == "STOP_HIT")
    gross = sum(float(r["gross_pips_mid"] or 0) for r in closed)
    net = sum(float(r["net_pips_ig_spread_1_4"] or 0) for r in closed)
    win = round(100 * targets / (targets + stops), 1) if (targets + stops) else 0.0
    mean_pips = round(gross / len(closed), 1) if closed else 0.0
    print(f"{name:<30}  {trades:>6}  {fills:>6}  {len(closed):>6}  {targets:>7}  {stops:>6}  {win:>5.1f}  {gross:>7.1f}  {net:>7.1f}  {mean_pips:>6.1f}")
