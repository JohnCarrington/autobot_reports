"""Honest backtest — coherent entry+stop+target setups vs deployed M1.

The previous investigation applied earlier ENTRIES but reused V2's
breakout-sized STOP. All three alternatives lost. This harness fixes
that: for each mechanism, the STOP is derived from the setup's own
invalidation structure, mechanically, from M5 bar data available at
scenario-gen time.

Mechanisms (details in EARLY_ENTRY_METHODOLOGY.md):
  M1   Deployed close-above-entry breakout + V2's own stop/target (baseline)
  A    Momentum impulse bar (entry at close) + stop below impulse low - 1p
  B    Pullback + rejection (higher-low) + stop below pullback trough - 2p
  C    Structural continuation (break of micro-pullback high) + stop below
       trough low - 2p
  Target for A/B/C: V2's structural target (preserved)
  Expiry for A/B/C: 2 h from entry (if neither target nor stop)

Metrics reported per mechanism:
  trades, fills, closed, targets, stops, win %, gross pips, net pips,
  avg win, avg loss, max drawdown, profit factor, entry delay (min),
  pips consumed at entry, mfe/mae, R:R at entry, % of anticipated
  move captured, failure modes.

Separate dev / validation samples where possible. Honest sample-size
caveat printed to stdout.

Spread: session-aware model (same as prior studies).

READ-ONLY. No broker calls. No production writes.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import statistics as st
import sys
from collections import defaultdict

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
sys.path.insert(0, str(AGENT))
import shadow_execution as sx

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "BACKTEST_RESULTS.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

UTC = dt.timezone.utc
SCEN = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl")

# Spread (session-aware), half-pips, UTC hour bands.
_SPREAD_HALF_SESSION = (
    ( 6, 11, 0.45), (11, 14, 0.70), (14, 17, 1.00),
    (17, 20, 1.50), (20, 24, 2.00), ( 0,  6, 1.80),
)


def half_spread(ts: dt.datetime) -> float:
    for lo, hi, h in _SPREAD_HALF_SESSION:
        if lo <= ts.hour < hi:
            return h
    return 1.5


# ---------------------------------------------------------------------
# Scenario-row helpers
# ---------------------------------------------------------------------

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


def _bar_at_or_before(ts, candles):
    out = None
    for c in candles:
        if c["ts_close"] <= ts:
            out = c
        else:
            break
    return out


# ---------------------------------------------------------------------
# Mechanism M1 — deployed breakout
# ---------------------------------------------------------------------

def mech_M1(gen_dt, direction, entry, stop, target, candles, now):
    post = [c for c in candles if c["ts_close"] > gen_dt and c["ts_close"] <= now]
    d = direction.upper()
    for bar in post:
        if (d == "BUY" and bar["c"] > entry) or (d == "SELL" and bar["c"] < entry):
            return _simulate_lifecycle(bar, bar["c"], d, stop, target,
                                           candles, now, expiry_bars=None)
    return {"status": "wait", "reason": "no close beyond entry"}


# ---------------------------------------------------------------------
# Mechanism A — momentum impulse
# ---------------------------------------------------------------------

def mech_A(gen_dt, direction, entry_ref, stop_v2, target, candles, now):
    """Enter at the close of the first post-gen bar that is a 'momentum
    impulse' in the predicted direction. Stop derived mechanically
    from the impulse bar's own low (BUY) or high (SELL)."""
    d = direction.upper()
    # Pre-gen context: median range of 10 bars before scen_gen
    pre = [c for c in candles if c["ts_close"] <= gen_dt]
    if len(pre) < 10:
        return {"status": "wait", "reason": "insufficient_pre_history"}
    recent = pre[-10:]
    med_range = st.median((c["h"] - c["l"]) for c in recent)
    if med_range <= 0:
        return {"status": "wait", "reason": "zero_median_range"}
    # Walk post-gen bars for a momentum bar.
    post = [c for c in candles if c["ts_close"] > gen_dt and c["ts_close"] <= now]
    buffer_pips = 1.0
    for bar in post:
        rng = bar["h"] - bar["l"]
        if rng <= 0: continue
        if d == "BUY":
            bullish_body = bar["c"] > bar["o"]
            above_med = rng >= 1.5 * med_range
            upper_body = (bar["c"] - bar["l"]) / rng >= 0.60
            if bullish_body and above_med and upper_body:
                entry = bar["c"]
                stop = bar["l"] - buffer_pips
                return _simulate_lifecycle(bar, entry, d, stop, target,
                                               candles, now,
                                               expiry_bars=None,
                                               extra={"mechanical_stop": stop,
                                                      "momentum_range": round(rng, 2),
                                                      "median_range_10": round(med_range, 2)})
        elif d == "SELL":
            bearish_body = bar["c"] < bar["o"]
            above_med = rng >= 1.5 * med_range
            lower_body = (bar["h"] - bar["c"]) / rng >= 0.60
            if bearish_body and above_med and lower_body:
                entry = bar["c"]
                stop = bar["h"] + buffer_pips
                return _simulate_lifecycle(bar, entry, d, stop, target,
                                               candles, now,
                                               expiry_bars=None,
                                               extra={"mechanical_stop": stop,
                                                      "momentum_range": round(rng, 2),
                                                      "median_range_10": round(med_range, 2)})
    return {"status": "wait", "reason": "no_momentum_impulse_within_window"}


# ---------------------------------------------------------------------
# Mechanism B — pullback + rejection
# ---------------------------------------------------------------------

def mech_B(gen_dt, direction, entry_ref, stop_v2, target, candles, now):
    """After scenario_gen, require 1-3 counter-direction bars (pullback),
    then a bar whose close is in-direction AND whose low > prior low
    (higher-low formation). Stop below the pullback trough."""
    d = direction.upper()
    post = [c for c in candles if c["ts_close"] > gen_dt and c["ts_close"] <= now]
    # Require decision price (bar at or before gen)
    decision_bar = _bar_at_or_before(gen_dt, candles)
    if decision_bar is None:
        return {"status": "wait", "reason": "no_decision_bar"}
    decision_price = decision_bar["c"]
    buffer_pips = 2.0

    pullback_bars = []
    for i, bar in enumerate(post):
        # Hard safety: pre-entry stop breach aborts the setup.
        if (d == "BUY" and bar["l"] <= stop_v2) or (d == "SELL" and bar["h"] >= stop_v2):
            return {"status": "reject", "reason": "SETUP_INVALIDATED_PRE_ENTRY",
                    "abort_bar_ts": bar["ts_open"].isoformat()}
        counter = (d == "BUY" and bar["c"] < decision_price) \
               or (d == "SELL" and bar["c"] > decision_price)
        indir = (d == "BUY" and bar["c"] > decision_price) \
             or (d == "SELL" and bar["c"] < decision_price)
        if counter:
            pullback_bars.append(bar)
            if len(pullback_bars) > 6:   # pullback too deep → setup void
                return {"status": "reject", "reason": "pullback_too_long"}
            continue
        if indir and pullback_bars:
            prev = pullback_bars[-1]
            # Higher-low (BUY) or lower-high (SELL) relative to pullback trough
            higher_low = bar["l"] > min(pb["l"] for pb in pullback_bars)
            lower_high = bar["h"] < max(pb["h"] for pb in pullback_bars)
            if (d == "BUY" and higher_low) or (d == "SELL" and lower_high):
                entry = bar["c"]
                if d == "BUY":
                    trough_low = min(pb["l"] for pb in pullback_bars)
                    stop = trough_low - buffer_pips
                else:
                    trough_high = max(pb["h"] for pb in pullback_bars)
                    stop = trough_high + buffer_pips
                return _simulate_lifecycle(bar, entry, d, stop, target,
                                               candles, now,
                                               expiry_bars=None,
                                               extra={"mechanical_stop": stop,
                                                      "pullback_bars": len(pullback_bars)})
    return {"status": "wait", "reason": "no_pullback_rejection_sequence"}


# ---------------------------------------------------------------------
# Mechanism C — early structural continuation
# ---------------------------------------------------------------------

def mech_C(gen_dt, direction, entry_ref, stop_v2, target, candles, now):
    """Objective higher-low (BUY) or lower-high (SELL) formation after
    scenario_gen, followed by a close above the micro-pullback high
    (BUY) or below the micro-pullback low (SELL)."""
    d = direction.upper()
    post = [c for c in candles if c["ts_close"] > gen_dt and c["ts_close"] <= now]
    if len(post) < 4:
        return {"status": "wait", "reason": "insufficient_post_bars"}
    buffer_pips = 2.0

    # Walk 3-bar windows looking for a structural pivot:
    #   BUY:  bar_i.high is local peak; bar_{i+1}.low is local trough;
    #         bar_{i+2}.close > bar_i.high → entry at i+2 close
    #         Stop below bar_{i+1}.low - buffer
    for i in range(len(post) - 2):
        a, b, c_ = post[i], post[i + 1], post[i + 2]
        # Hard safety abort
        if (d == "BUY" and a["l"] <= stop_v2) \
         or (d == "SELL" and a["h"] >= stop_v2):
            return {"status": "reject", "reason": "SETUP_INVALIDATED_PRE_ENTRY",
                    "abort_bar_ts": a["ts_open"].isoformat()}
        if d == "BUY":
            local_peak = a["h"] >= b["h"]
            local_trough = b["l"] < a["l"] and b["l"] < c_["l"]
            cont_break = c_["c"] > a["h"]
            if local_peak and local_trough and cont_break:
                entry = c_["c"]
                stop = b["l"] - buffer_pips
                return _simulate_lifecycle(c_, entry, d, stop, target,
                                               candles, now,
                                               expiry_bars=None,
                                               extra={"mechanical_stop": stop,
                                                      "trough_low": b["l"]})
        elif d == "SELL":
            local_trough = a["l"] <= b["l"]
            local_peak = b["h"] > a["h"] and b["h"] > c_["h"]
            cont_break = c_["c"] < a["l"]
            if local_trough and local_peak and cont_break:
                entry = c_["c"]
                stop = b["h"] + buffer_pips
                return _simulate_lifecycle(c_, entry, d, stop, target,
                                               candles, now,
                                               expiry_bars=None,
                                               extra={"mechanical_stop": stop,
                                                      "trough_high": b["h"]})
    return {"status": "wait", "reason": "no_structural_pivot_pattern"}


# ---------------------------------------------------------------------
# Lifecycle (shared)
# ---------------------------------------------------------------------

def _simulate_lifecycle(entry_bar, sim_entry, direction, stop, target,
                           candles, now, expiry_bars=None, extra=None):
    """Simulate the broker's attached stop/target lifecycle.

    2026-11-03 (operator directive): NO POST-ENTRY TIME-BASED CLOSE.
    The old `expiry_bars=24` default forced a close at bar 24; this
    is removed. The simulation monitors bars indefinitely until stop
    OR target is hit by a bar's high/low. If neither is hit by the
    end of the available candle sample, the trade is reported as
    UNRESOLVED (would still be live under real broker rules).

    The `expiry_bars` parameter is retained with a default of None
    (= no post-entry cap) for signature compatibility; passing a
    positive integer re-enables the old simulation mode only. The
    production path never passes it.
    """
    d = direction
    monitor = [c for c in candles
                 if c["ts_open"] > entry_bar["ts_open"] and c["ts_close"] <= now]
    if expiry_bars is not None:
        monitor = monitor[:expiry_bars]
    for c in monitor:
        hs = (c["h"] >= stop) if d == "SELL" else (c["l"] <= stop)
        ht = (c["l"] <= target) if d == "SELL" else (c["h"] >= target)
        if hs and ht:
            return _finalise("AMBIGUOUS", entry_bar, sim_entry, d, stop,
                              target, c["c"], c, candles, now, extra)
        if hs:
            return _finalise("STOP_HIT", entry_bar, sim_entry, d, stop,
                              target, stop, c, candles, now, extra)
        if ht:
            return _finalise("TARGET_HIT", entry_bar, sim_entry, d, stop,
                              target, target, c, candles, now, extra)
    # No stop/target hit within the available candle sample.
    # Operator directive: do NOT force-close the position. Report as
    # UNRESOLVED and let the operator see it separately.
    if expiry_bars is not None and monitor:
        # Legacy / debug path only — explicitly requested by caller.
        last = monitor[-1]
        return _finalise("EXPIRED", entry_bar, sim_entry, d, stop, target,
                          last["c"], last, candles, now, extra)
    return _finalise("UNRESOLVED", entry_bar, sim_entry, d, stop, target,
                      None, None, candles, now, extra)


def _finalise(exit_reason, entry_bar, sim_entry, direction, stop, target,
                exit_price, exit_bar, candles, now, extra):
    gross = None
    if exit_price is not None and exit_reason != "AMBIGUOUS":
        gross = round((exit_price - sim_entry) * (1 if direction == "BUY" else -1), 1)
    # MFE/MAE computed STRICTLY over the holding period: entry bar through
    # exit bar inclusive (or last monitored bar if OPEN). Previously this
    # extended past the exit, inflating MFE/MAE for closed/expired trades.
    if exit_bar is not None:
        bars_in_trade = [c for c in candles
                           if c["ts_open"] >= entry_bar["ts_open"]
                           and c["ts_open"] <= exit_bar["ts_open"]]
    else:
        # Open / OPEN case — all bars from entry forward up to now.
        bars_in_trade = [c for c in candles
                           if c["ts_open"] >= entry_bar["ts_open"]
                           and c["ts_close"] <= now]
    if bars_in_trade:
        hi = max(c["h"] for c in bars_in_trade)
        lo = min(c["l"] for c in bars_in_trade)
        if direction == "BUY":
            mfe = round(hi - sim_entry, 1); mae = round(sim_entry - lo, 1)
        else:
            mfe = round(sim_entry - lo, 1); mae = round(hi - sim_entry, 1)
    else:
        mfe = mae = 0.0
    out = {"status": "fill", "exit_reason": exit_reason,
           "entry_bar_ts": entry_bar["ts_open"].isoformat(),
           "sim_entry": sim_entry,
           "sim_exit": exit_price,
           "stop_used": stop, "target_used": target,
           "gross_pips_mid": gross,
           "mfe_pips": mfe, "mae_pips": mae}
    if exit_bar is not None:
        out["exit_bar_ts"] = exit_bar["ts_open"].isoformat()
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------

def _max_drawdown(sorted_closed):
    cum = 0.0; peak = 0.0; dd = 0.0
    for r in sorted_closed:
        g = r.get("gross_pips_mid") or 0.0
        cum += g; peak = max(peak, cum); dd = min(dd, cum - peak)
    return round(dd, 1)


def _pct_captured(sim_entry, exit_price, scen_gen_price, target, direction):
    """% of anticipated move captured = (exit - sim_entry) / (target - scen_gen_price)"""
    if sim_entry is None or exit_price is None or scen_gen_price is None:
        return None
    sign = 1 if direction == "BUY" else -1
    anticipated = (target - scen_gen_price) * sign
    realised = (exit_price - sim_entry) * sign
    if anticipated <= 0: return None
    return round(100 * realised / anticipated, 1)


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------

def main():
    candles = sorted(sx.load_candles(), key=lambda c: c["ts_open"])
    now = dt.datetime.now(UTC)
    scens = []
    for ln in SCEN.read_text().splitlines():
        if ln.strip():
            try: scens.append(json.loads(ln))
            except Exception: pass
    by_sid = defaultdict(list)
    for s in scens:
        if s.get("scenario_id"):
            by_sid[s["scenario_id"]].append(s)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda r: r.get("revision_idx") or 0)

    sample = []
    for sid, revs in by_sid.items():
        fr = _first_ready(revs)
        if not fr:
            continue
        tp = _tp(fr)
        gen_dt = _parse(fr.get("generated_at_utc"))
        sample.append({"sid": sid, "fr": fr, "tp": tp, "gen_dt": gen_dt})
    sample.sort(key=lambda s: s["gen_dt"].isoformat() if s["gen_dt"] else "")
    print(f"loaded {len(sample)} first-READY scenarios, {len(candles)} candles")

    # Dev / validation split: first 7 chronologically = DEV, last 6 = VAL
    dev_sample = sample[:7]
    val_sample = sample[7:]
    print(f"dev sample: {len(dev_sample)}; validation sample: {len(val_sample)}")

    mechs = (("M1_baseline", mech_M1),
             ("A_momentum",  mech_A),
             ("B_pullback",  mech_B),
             ("C_structural", mech_C))

    rows_out = []
    for sample_label, scens_subset in (("ALL", sample), ("DEV", dev_sample),
                                            ("VAL", val_sample)):
        for mech_name, fn in mechs:
            for s in scens_subset:
                tp = s["tp"]
                direction = (tp.get("direction") or "").upper()
                entry = tp["entry_price"]; stop = tp["stop_price"]; target = tp["target_price"]
                decision_bar = _bar_at_or_before(s["gen_dt"], candles)
                decision_price = (decision_bar or {}).get("c")
                try:
                    res = fn(s["gen_dt"], direction, entry, stop, target,
                               candles, now)
                except Exception as exc:
                    res = {"status": "error", "reason": str(exc)}
                row = {"sample": sample_label,
                       "mechanism": mech_name,
                       "scenario_id": s["sid"],
                       "revision_idx": s["fr"].get("revision_idx"),
                       "direction": direction,
                       "scen_gen_at": s["fr"].get("generated_at_utc"),
                       "decision_price": decision_price,
                       "v2_entry_proposed": entry,
                       "v2_stop_proposed": stop,
                       "v2_target_proposed": target,
                       "status": res.get("status"),
                       "reason": res.get("reason"),
                       "exit_reason": res.get("exit_reason"),
                       "sim_entry": res.get("sim_entry"),
                       "stop_used": res.get("stop_used"),
                       "sim_exit": res.get("sim_exit"),
                       "gross_pips_mid": res.get("gross_pips_mid"),
                       "mfe_pips": res.get("mfe_pips"),
                       "mae_pips": res.get("mae_pips"),
                       "entry_bar_ts": res.get("entry_bar_ts"),
                       "exit_bar_ts": res.get("exit_bar_ts"),
                       "mechanical_stop": res.get("mechanical_stop"),
                       }
                # Derived metrics
                if row["sim_entry"] is not None and row["gross_pips_mid"] is not None:
                    half = half_spread(_parse(res.get("entry_bar_ts") or ""))
                    row["net_pips"] = round(row["gross_pips_mid"] - 2 * half, 1)
                    row["half_spread_pips"] = half
                else:
                    row["net_pips"] = None
                    row["half_spread_pips"] = None
                if row["sim_entry"] is not None and row["stop_used"] is not None \
                   and row["v2_target_proposed"] is not None:
                    sign = 1 if direction == "BUY" else -1
                    row["reward_at_entry"] = round((row["v2_target_proposed"] - row["sim_entry"]) * sign, 1)
                    row["risk_at_entry"] = round((row["sim_entry"] - row["stop_used"]) * sign, 1)
                    if row["risk_at_entry"] > 0:
                        row["rr_at_entry"] = round(row["reward_at_entry"] / row["risk_at_entry"], 2)
                    else:
                        row["rr_at_entry"] = None
                else:
                    row["reward_at_entry"] = None
                    row["risk_at_entry"] = None
                    row["rr_at_entry"] = None
                row["pct_captured"] = _pct_captured(
                    row["sim_entry"], row["sim_exit"], decision_price,
                    row["v2_target_proposed"], direction)
                if row["entry_bar_ts"] and s["gen_dt"]:
                    bt = _parse(row["entry_bar_ts"])
                    row["delay_min"] = round((bt - s["gen_dt"]).total_seconds() / 60.0, 1)
                else:
                    row["delay_min"] = None
                if row["sim_entry"] is not None and decision_price is not None:
                    sign = 1 if direction == "BUY" else -1
                    row["pips_consumed_at_entry"] = round((row["sim_entry"] - decision_price) * sign, 2)
                else:
                    row["pips_consumed_at_entry"] = None
                rows_out.append(row)

    # CSV
    keys = list(rows_out[0].keys())
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    print(f"wrote {len(rows_out)} rows → {OUT}")

    # Summaries
    print()
    _print_summary(rows_out, "ALL")
    print()
    _print_summary(rows_out, "DEV")
    print()
    _print_summary(rows_out, "VAL")


def _print_summary(rows_out, sample_label):
    print(f"=== {sample_label} ===  (resolved = TARGET_HIT or STOP_HIT; unresolved = still live under real broker)")
    print(f"{'Mech':<16} {'n':>3} {'fill':>4} {'tgt':>4} {'stop':>4} "
          f"{'unres':>5} {'rej':>3} {'wait':>4} {'win%':>5} "
          f"{'gross':>7} {'net':>7} {'avgW':>5} {'avgL':>5} "
          f"{'MDD':>6} {'PF':>5} {'delay':>5} {'cons':>5} {'cap%':>5} {'R:R':>5}")
    print("-" * 170)
    import statistics as st
    for mech in ("M1_baseline", "A_momentum", "B_pullback", "C_structural"):
        rows = [r for r in rows_out if r["sample"] == sample_label and r["mechanism"] == mech]
        if not rows: continue
        n = len(rows)
        fills = [r for r in rows if r["status"] == "fill"]
        # Operator directive 2026-11-03: no post-entry time-based close.
        # Only broker-stop (STOP_HIT) and broker-target (TARGET_HIT)
        # outcomes contribute to the P&L sum. UNRESOLVED trades (would
        # still be live under real broker rules) are counted separately
        # and reported as the audit column `unresolved`.
        resolved = [r for r in fills if r.get("exit_reason") in
                     ("TARGET_HIT", "STOP_HIT")]
        targets = [r for r in resolved if r["exit_reason"] == "TARGET_HIT"]
        stops = [r for r in resolved if r["exit_reason"] == "STOP_HIT"]
        unresolved = [r for r in fills if r.get("exit_reason") == "UNRESOLVED"]
        rejected = [r for r in rows if r["status"] == "reject"]
        waiting = [r for r in rows if r["status"] in ("wait", "skip", "error")]
        if resolved:
            gross = sum((r.get("gross_pips_mid") or 0) for r in resolved)
            net = sum((r.get("net_pips") or 0) for r in resolved)
            # Classical win rate: targets / (targets + stops).
            win = round(100 * len(targets) / len(resolved), 1)
            avgW = round(st.mean(r["gross_pips_mid"] for r in targets), 1) if targets else 0
            avgL = round(st.mean(r["gross_pips_mid"] for r in stops), 1) if stops else 0
            closed_sorted = sorted(resolved, key=lambda r: r.get("exit_bar_ts") or "")
            mdd = _max_drawdown(closed_sorted)
            tot_wins = sum((r.get("gross_pips_mid") or 0) for r in targets)
            tot_losses = sum(abs(r.get("gross_pips_mid") or 0) for r in stops)
            pf = round(tot_wins / tot_losses, 2) if tot_losses else float("inf")
        else:
            win = gross = net = avgW = avgL = mdd = pf = 0
        delays = [r["delay_min"] for r in fills if r.get("delay_min") is not None]
        delay_med = round(st.median(delays), 1) if delays else 0
        cons = [r["pips_consumed_at_entry"] for r in fills if r.get("pips_consumed_at_entry") is not None]
        cons_med = round(st.median(cons), 1) if cons else 0
        caps = [r["pct_captured"] for r in resolved if r.get("pct_captured") is not None]
        cap_med = round(st.median(caps), 1) if caps else 0
        rrs = [r["rr_at_entry"] for r in fills if r.get("rr_at_entry") is not None]
        rr_med = round(st.median(rrs), 2) if rrs else 0
        print(f"{mech:<16} {n:>3} {len(fills):>4} {len(targets):>4} {len(stops):>4} "
              f"{len(unresolved):>5} {len(rejected):>3} {len(waiting):>4} {win:>5.1f} "
              f"{gross:>7.1f} {net:>7.1f} {avgW:>5.1f} {avgL:>5.1f} "
              f"{mdd:>6.1f} {pf:>5} {delay_med:>5.1f} {cons_med:>5.1f} {cap_med:>5.1f} {rr_med:>5}")


if __name__ == "__main__":
    main()
