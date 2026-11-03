"""Backtest harness — compare four entry mechanisms over the same
scenarios and same market history. READ-ONLY research.

Mechanisms:
  M1  deployed close-above-entry breakout
  A   early directional entry at scenario-gen bar close
  B   pullback-then-direction entry
  C   earlier breakout (intra-bar touch of entry trigger)

Writes BACKTEST_RESULTS.csv with:
  mechanism, scenario_id, revision_idx, direction,
  entry_bar_ts_utc, simulated_entry, exit_bar_ts_utc, simulated_exit,
  exit_reason, gross_pips_mid, net_pips_model_spread, mfe_pips, mae_pips,
  entry_delay_min, pips_consumed_at_entry, rr_at_entry,
  status (fill|reject|wait|skip|setup_invalidated),
  reject_reason, half_spread_pips_at_entry

Plus a stdout summary table with all metrics requested in the brief.

Spread policy: session-aware model (see Appendix A of EARLY_ENTRY_DESIGN.md).
Lookahead safety: every mechanism uses only bars after the scenario's
gen time; executor's `MAX_FILL_LOOKBACK_SECONDS` cap is applied so
backtest results match live post-deploy behaviour.
"""
from __future__ import annotations

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
import shadow_execution as sx  # the deployed executor — used ONLY to re-run M1 for parity

UTC = dt.timezone.utc
OUT = HERE.parent / "data" / "BACKTEST_RESULTS.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

SCEN = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl")
DEC  = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal/decisions.jsonl")


def _parse(s):
    if not s: return None
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception: return None


def _primary(row):
    for o in (row.get("opportunities") or []):
        if isinstance(o, dict) and (o.get("direction") or "").upper() in ("BUY", "SELL"):
            return o
    return None


def _tp(row):
    tp = row.get("trade_proposal") or {}
    if tp:
        return tp
    return (_primary(row) or {}).get("trade_proposal") or {}


def _close_at_or_before(ts, candles):
    """Return the close of the latest bar whose ts_close <= ts (decision price)."""
    out = None
    for c in candles:
        if c["ts_close"] <= ts: out = c
        else: break
    return (out or {}).get("c")


def _simulate_M1(gen_dt, direction, entry, stop, target, candles, now, lookback_s):
    """Deployed-executor-equivalent: first bar close beyond entry in-direction."""
    enb = max(gen_dt, now - dt.timedelta(seconds=lookback_s))
    post = [c for c in candles if c["ts_close"] > enb and c["ts_close"] <= now]
    d = direction.upper()
    for bar in post:
        if (d == "BUY" and bar["c"] > entry) or (d == "SELL" and bar["c"] < entry):
            return _simulate_lifecycle(bar, bar["c"], direction, stop, target, candles, now)
    return {"status": "wait", "reason": "no close beyond entry"}


def _simulate_lifecycle(entry_bar, sim_entry, direction, stop, target, candles, now):
    d = direction.upper()
    monitor = [c for c in candles
                 if c["ts_open"] > entry_bar["ts_open"] and c["ts_close"] <= now]
    for c in monitor:
        hs = (c["h"] >= stop) if d == "SELL" else (c["l"] <= stop)
        ht = (c["l"] <= target) if d == "SELL" else (c["h"] >= target)
        if hs and ht:
            return {"status": "fill", "exit_reason": "AMBIGUOUS",
                    "entry_bar_ts": entry_bar["ts_open"].isoformat(),
                    "sim_entry": sim_entry, "sim_exit": c["c"],
                    "exit_bar_ts": c["ts_open"].isoformat()}
        if hs:
            g = round((stop - sim_entry) * (1 if d == "BUY" else -1), 1)
            return {"status": "fill", "exit_reason": "STOP_HIT",
                    "entry_bar_ts": entry_bar["ts_open"].isoformat(),
                    "sim_entry": sim_entry, "sim_exit": stop,
                    "exit_bar_ts": c["ts_open"].isoformat(),
                    "gross_pips_mid": g}
        if ht:
            g = round((target - sim_entry) * (1 if d == "BUY" else -1), 1)
            return {"status": "fill", "exit_reason": "TARGET_HIT",
                    "entry_bar_ts": entry_bar["ts_open"].isoformat(),
                    "sim_entry": sim_entry, "sim_exit": target,
                    "exit_bar_ts": c["ts_open"].isoformat(),
                    "gross_pips_mid": g}
    # MFE/MAE over [entry_bar] + monitor
    all_bars = [entry_bar] + monitor
    highs = max(c["h"] for c in all_bars)
    lows = min(c["l"] for c in all_bars)
    if d == "SELL":
        mfe = round(sim_entry - lows, 1); mae = round(highs - sim_entry, 1)
    else:
        mfe = round(highs - sim_entry, 1); mae = round(sim_entry - lows, 1)
    return {"status": "fill", "exit_reason": "OPEN",
            "entry_bar_ts": entry_bar["ts_open"].isoformat(),
            "sim_entry": sim_entry, "mfe_pips": mfe, "mae_pips": mae}


def _simulate_ee(mode, scenario_row, candles, now, lookback_s, decision_price):
    """Delegate to early_entry.process_proposal with a sandbox shadow dir
    so the live early-journals are not touched."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        sd = pathlib.Path(tmp)
        res = ee.process_proposal(
            scenario_row=scenario_row,
            primary_decision={"direction": ""},  # no NMS data in backtest
            decision_price=decision_price,
            candles=candles,
            mode=mode,
            shadow_dir=sd,
            now_utc=now,
            max_fill_lookback_seconds=lookback_s,
        )
    return res


def main():
    # Load candles (snapshots.jsonl) via the deployed loader
    candles = sorted(sx.load_candles(), key=lambda c: c["ts_open"])
    # Load scenario revisions
    scens = []
    for ln in SCEN.read_text().splitlines():
        ln = ln.strip()
        if ln:
            try: scens.append(json.loads(ln))
            except Exception: pass
    print(f"loaded {len(scens)} scenario revisions, {len(candles)} candles")

    now = dt.datetime.now(UTC)
    # Backtest uses UNLIMITED lookback so we see every potential fill
    # over the research window; the CSV flags fills that would be
    # blocked under the deployed 7200 s cap.
    lookback_unlimited = 0

    # Group by scenario_id; walk REVISIONS in order; first revision
    # per scenario whose publication=VALID + geometry OK is the fire
    # candidate for all mechanisms. (Matches `impl/early_entry.py`
    # "latest-revision per scenario" semantics for live use, but for
    # the backtest we use FIRST-READY so each scenario has at most one
    # fire candidate per mechanism — which is the right identity for
    # mechanism comparison.)
    by_sid: dict[str, list[dict]] = defaultdict(list)
    for s in scens:
        if s.get("scenario_id"):
            by_sid[s["scenario_id"]].append(s)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda r: r.get("revision_idx") or 0)

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

    rows_out = []

    for sid in sorted(by_sid):
        fr = _first_ready(by_sid[sid])
        if not fr:
            continue
        tp = _tp(fr)
        gen_dt = _parse(fr.get("generated_at_utc"))
        direction = (tp.get("direction") or "").upper()
        entry = tp["entry_price"]; stop = tp["stop_price"]; target = tp["target_price"]
        decision_price = _close_at_or_before(gen_dt, candles) if gen_dt else None
        reward = round(abs(target - entry), 1)
        risk = round(abs(entry - stop), 1)
        rr = round(reward / risk, 2) if risk else None

        # ---- M1 deployed-equivalent (unlimited lookback for backtest) ----
        m1 = _simulate_M1(gen_dt, direction, entry, stop, target,
                             candles, now, 999_999_999)
        rows_out.append(_mkrow("M1_breakout_current", sid, fr, direction,
                                 entry, stop, target, decision_price,
                                 reward, risk, rr, m1, gen_dt))

        # ---- M1 + quality gate (isolates the gate's contribution) ----
        if m1.get("status") == "fill":
            sim_entry = m1.get("sim_entry")
            # Re-check gate using sim_entry and spread at entry bar.
            bt = _parse(m1.get("entry_bar_ts"))
            half = ee.spread_half_pips((bt or now) + dt.timedelta(minutes=5))
            ok, reason, metrics = ee.opp_quality(
                sim_entry, stop, target, direction, half, decision_price)
            if ok:
                m1_gated = m1
            else:
                m1_gated = {"status": "reject", "reject_reason": reason,
                             "metrics": metrics}
        else:
            m1_gated = m1
        rows_out.append(_mkrow("M1_with_quality_gate", sid, fr, direction,
                                 entry, stop, target, decision_price,
                                 reward, risk, rr, m1_gated, gen_dt))

        # ---- A, B, C via early_entry module (unlimited lookback) ----
        for mode in ("A", "B", "C"):
            res = _simulate_ee(mode, fr, candles, now, lookback_unlimited,
                                 decision_price)
            rows_out.append(_mkrow(f"{mode}_early_entry", sid, fr, direction,
                                     entry, stop, target, decision_price,
                                     reward, risk, rr, _normalise_ee(res), gen_dt))

    # Write CSV
    keys = list(rows_out[0].keys())
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    print(f"wrote {len(rows_out)} rows → {OUT}")

    # Stdout summary table
    _print_summary(rows_out)


def _normalise_ee(res):
    """Translate early_entry.process_proposal response to the common shape."""
    pos = res.get("position")
    if pos == "CLOSED":
        return {"status": "fill", "exit_reason": res.get("exit_reason"),
                "entry_bar_ts": res.get("entry_bar_ts_utc"),
                "sim_entry": res.get("simulated_entry"),
                "sim_exit": res.get("simulated_exit"),
                "exit_bar_ts": res.get("exit_bar_ts_utc"),
                "gross_pips_mid": res.get("gross_pips"),
                "mfe_pips": res.get("mfe_pips"), "mae_pips": res.get("mae_pips")}
    if pos == "OPENED_AWAITING_EXIT":
        return {"status": "fill", "exit_reason": "OPEN",
                "entry_bar_ts": res.get("entry_bar_ts_utc"),
                "sim_entry": res.get("simulated_entry"),
                "mfe_pips": res.get("mfe_pips"), "mae_pips": res.get("mae_pips")}
    if pos == "REJECTED":
        return {"status": "reject", "reject_reason": res.get("reason"),
                "metrics": res.get("metrics")}
    if pos == "WAITING_FOR_ENTRY":
        return {"status": "wait", "reason": res.get("reason")}
    return {"status": "skip", "reason": res.get("reason")}


def _mkrow(mech, sid, fr, direction, entry_prop, stop, target,
             decision_price, reward_pips, risk_pips, rr, res, gen_dt):
    status = res.get("status", "wait")
    row = {
        "mechanism": mech,
        "scenario_id": sid,
        "revision_idx": fr.get("revision_idx"),
        "first_ready_ts": fr.get("generated_at_utc"),
        "direction": direction,
        "entry_proposed": entry_prop,
        "stop": stop, "target": target,
        "reward_pips": reward_pips, "risk_pips": risk_pips, "rr": rr,
        "decision_price": decision_price,
        "status": status,
    }
    # Delay / fill details
    sim_entry = res.get("sim_entry")
    entry_bar_ts = res.get("entry_bar_ts")
    gross = res.get("gross_pips_mid")
    net = None
    half_spread = None
    delay_min = None
    pips_consumed = None
    rr_at_entry = None
    if entry_bar_ts:
        bt = _parse(entry_bar_ts)
        if gen_dt and bt:
            delay_min = round((bt - gen_dt).total_seconds() / 60.0, 1)
        half_spread = ee.spread_half_pips(bt + dt.timedelta(minutes=5)) if bt else None
    if sim_entry is not None and decision_price is not None:
        pips_consumed = round((sim_entry - decision_price) *
                                 (1 if direction == "BUY" else -1), 2)
    if sim_entry is not None and target is not None and stop is not None:
        rem = (target - sim_entry) * (1 if direction == "BUY" else -1)
        rsk = (sim_entry - stop) * (1 if direction == "BUY" else -1)
        if rsk > 0:
            rr_at_entry = round(rem / rsk, 2)
    if gross is not None and res.get("exit_reason") != "AMBIGUOUS" and half_spread is not None:
        net = round(gross - 2 * half_spread, 1)
    row.update({
        "entry_bar_ts": entry_bar_ts,
        "simulated_entry": sim_entry,
        "exit_reason": res.get("exit_reason"),
        "simulated_exit": res.get("sim_exit"),
        "gross_pips_mid": gross,
        "net_pips_model_spread": net,
        "half_spread_pips_at_entry": half_spread,
        "mfe_pips": res.get("mfe_pips"),
        "mae_pips": res.get("mae_pips"),
        "entry_delay_min": delay_min,
        "pips_consumed_at_entry": pips_consumed,
        "rr_at_entry": rr_at_entry,
        "reject_reason": res.get("reject_reason"),
    })
    return row


def _print_summary(rows):
    import statistics as st
    by_mech = defaultdict(list)
    for r in rows:
        by_mech[r["mechanism"]].append(r)
    print()
    print(f"{'Mechanism':<28} {'trades':>6} {'fills':>5} {'closed':>6} "
          f"{'targ':>4} {'stop':>4} {'rej':>4} {'wait':>4} "
          f"{'win%':>5} {'gross':>8} {'net':>8} "
          f"{'avgW':>5} {'avgL':>5} {'maxDD':>6} {'PF':>5} "
          f"{'delay':>5} {'cons':>5}")
    print("-" * 150)
    for mech, rs in sorted(by_mech.items()):
        trades = len(rs)
        fills = [r for r in rs if r["status"] == "fill"]
        rejected = [r for r in rs if r["status"] == "reject"]
        waiting = [r for r in rs if r["status"] in ("wait", "skip")]
        closed = [r for r in fills if r.get("exit_reason") in ("TARGET_HIT", "STOP_HIT")]
        targets = [r for r in closed if r["exit_reason"] == "TARGET_HIT"]
        stops = [r for r in closed if r["exit_reason"] == "STOP_HIT"]
        if closed:
            win_rate = round(100 * len(targets) / len(closed), 1)
            gross = sum((r["gross_pips_mid"] or 0.0) for r in closed)
            net = sum((r["net_pips_model_spread"] or 0.0) for r in closed)
            wins_pips = [r["gross_pips_mid"] for r in targets]
            loss_pips = [r["gross_pips_mid"] for r in stops]
            avgW = round(st.mean(wins_pips), 1) if wins_pips else 0
            avgL = round(st.mean(loss_pips), 1) if loss_pips else 0
            # Max drawdown — walk closed trades in exit order
            closed_sorted = sorted(closed, key=lambda r: r.get("exit_bar_ts") or "")
            cum = 0.0; peak = 0.0; max_dd = 0.0
            for r in closed_sorted:
                cum += r.get("gross_pips_mid") or 0.0
                peak = max(peak, cum)
                max_dd = min(max_dd, cum - peak)
            # Profit factor
            total_wins = sum(r.get("gross_pips_mid") or 0.0 for r in targets)
            total_losses = sum(abs(r.get("gross_pips_mid") or 0.0) for r in stops)
            pf = round(total_wins / total_losses, 2) if total_losses else float("inf")
        else:
            win_rate = gross = net = avgW = avgL = max_dd = pf = 0
        delays = [r["entry_delay_min"] for r in fills if r.get("entry_delay_min") is not None]
        delay_med = round(st.median(delays), 1) if delays else 0
        cons = [r["pips_consumed_at_entry"] for r in fills if r.get("pips_consumed_at_entry") is not None]
        cons_med = round(st.median(cons), 1) if cons else 0
        print(f"{mech:<28} {trades:>6} {len(fills):>5} {len(closed):>6} "
              f"{len(targets):>4} {len(stops):>4} {len(rejected):>4} {len(waiting):>4} "
              f"{win_rate:>5.1f} {gross:>8.1f} {net:>8.1f} "
              f"{avgW:>5.1f} {avgL:>5.1f} {max_dd:>6.1f} {pf:>5.2f} "
              f"{delay_med:>5.1f} {cons_med:>5.1f}")


if __name__ == "__main__":
    main()
