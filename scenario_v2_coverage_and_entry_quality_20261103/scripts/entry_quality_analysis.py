"""Scenario V2 — directional-reasoning and entry-quality audit (read-only).

For every unique scenario_id in scenarios_shadow.jsonl we compute:

  * First directional-prediction timestamp (first opp with BUY/SELL direction)
  * First READY-publishable timestamp (first revision with
    publication_decision=VALID AND structured entry/stop/target resolvable).
  * MFE / MAE 15 / 30 / 60 min after first-READY (directional accuracy
    independent of the entry mechanism).
  * Pips travelled from first-READY market close to entry-trigger level.
  * Pips remaining between entry and target when the entry mechanism
    would have fired (if ever).
  * R:R geometry of each actionable revision.
  * Revision-timing summary (how long between revisions, which direction
    they drift, how many revisions crowd one scenario).

Outputs:
  * data/entry_quality_dataframe.csv — one row per scenario, all metrics.
  * data/revision_drift.csv — rev-by-rev entry/stop/target per scenario.
  * data/directional_accuracy.csv — n/15/30/60-min MFE/MAE per scenario.

READ-ONLY. No deploy, no service touch, no production writes.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import sys
from collections import defaultdict

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
sys.path.insert(0, str(AGENT))
import shadow_execution as se

UTC = dt.timezone.utc
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SNAP = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal/snapshots.jsonl")
SCEN = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl")

candles = se.load_candles()
# Index candles by ts_open for quick lookups
cand_by_open = {c["ts_open"]: c for c in candles}
# Also list closes sorted ascending for horizon windows
candles_sorted = sorted(candles, key=lambda c: c["ts_open"])


def _parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        return t
    except Exception:
        return None


def _primary_opp(row: dict) -> dict | None:
    for o in (row.get("opportunities") or []):
        if isinstance(o, dict):
            d = (o.get("direction") or "").upper()
            if d in ("BUY", "SELL"):
                return o
    return None


def _trade_proposal(row: dict) -> dict:
    tp = row.get("trade_proposal") or {}
    if tp:
        return tp
    p = _primary_opp(row) or {}
    return p.get("trade_proposal") or {}


def _close_at_or_before(ts: dt.datetime) -> float | None:
    """Return the close of the latest bar whose ts_close <= ts."""
    out = None
    for c in candles_sorted:
        if c["ts_close"] <= ts:
            out = c
        else:
            break
    return (out or {}).get("c")


def _future_excursion(gen_ts: dt.datetime, direction: str,
                        horizon_min: int) -> tuple[float | None, float | None]:
    """Return (mfe_pips, mae_pips) from the close of the bar at gen_ts to
    `horizon_min` minutes later. Positive = favourable."""
    anchor_price = _close_at_or_before(gen_ts)
    if anchor_price is None:
        return (None, None)
    window_end = gen_ts + dt.timedelta(minutes=horizon_min)
    bars_in = [c for c in candles_sorted
                 if c["ts_open"] >= gen_ts and c["ts_close"] <= window_end]
    if not bars_in:
        return (None, None)
    hi = max(c["h"] for c in bars_in)
    lo = min(c["l"] for c in bars_in)
    d = direction.upper()
    if d == "BUY":
        mfe = round(hi - anchor_price, 1)
        mae = round(anchor_price - lo, 1)
    elif d == "SELL":
        mfe = round(anchor_price - lo, 1)
        mae = round(hi - anchor_price, 1)
    else:
        return (None, None)
    return (mfe, mae)


# =====================================================================
# Load scenarios_shadow.jsonl and index per scenario
# =====================================================================

rows: list[dict] = []
for ln in SCEN.read_text().splitlines():
    ln = ln.strip()
    if not ln:
        continue
    try:
        rows.append(json.loads(ln))
    except Exception:
        pass

by_sid: dict[str, list[dict]] = defaultdict(list)
for r in rows:
    sid = r.get("scenario_id")
    if sid:
        by_sid[sid].append(r)
for sid in by_sid:
    by_sid[sid].sort(key=lambda r: r.get("generated_at_utc") or "")

# =====================================================================
# Per-scenario summary
# =====================================================================

eq_rows: list[dict] = []
rd_rows: list[dict] = []
da_rows: list[dict] = []

for sid, revs in sorted(by_sid.items()):
    # First directional prediction (any revision whose primary opp names
    # BUY or SELL — may be CAUTION or INVALID).
    first_dir = None
    first_dir_rev = None
    for r in revs:
        p = _primary_opp(r)
        if p:
            first_dir = r
            first_dir_rev = r.get("revision_idx")
            break

    # First READY — publication VALID + resolvable structured entry/stop/target
    first_ready = None
    first_ready_rev = None
    for r in revs:
        pub = (r.get("publication_decision") or {}).get("decision", "").upper()
        if pub != "VALID":
            continue
        tp = _trade_proposal(r)
        if not tp:
            continue
        if tp.get("entry_price") is None or tp.get("stop_price") is None or tp.get("target_price") is None:
            continue
        if (tp.get("direction") or "").upper() not in ("BUY", "SELL"):
            continue
        first_ready = r
        first_ready_rev = r.get("revision_idx")
        break

    first_dir_ts = _parse_ts((first_dir or {}).get("generated_at_utc"))
    first_ready_ts = _parse_ts((first_ready or {}).get("generated_at_utc"))

    # Market price at first-dir and first-ready
    price_at_first_dir = _close_at_or_before(first_dir_ts) if first_dir_ts else None
    price_at_first_ready = _close_at_or_before(first_ready_ts) if first_ready_ts else None

    # Final (latest) revision snapshot
    last = revs[-1]
    last_tp = _trade_proposal(last)
    last_dir = (last_tp or {}).get("direction") or (_primary_opp(last) or {}).get("direction") or ""

    # If first_ready exists, record its structured proposal
    fr_tp = _trade_proposal(first_ready) if first_ready else {}
    initial_entry = fr_tp.get("entry_price") if fr_tp else None
    initial_stop = fr_tp.get("stop_price") if fr_tp else None
    initial_target = fr_tp.get("target_price") if fr_tp else None
    initial_direction = (fr_tp.get("direction") or "").upper() if fr_tp else ""

    # Directional accuracy — MFE/MAE 15/30/60 min after first-ready
    da = {"scenario_id": sid}
    for h in (15, 30, 60):
        mfe, mae = (None, None)
        if first_ready_ts and initial_direction:
            mfe, mae = _future_excursion(first_ready_ts, initial_direction, h)
        da[f"mfe_pips_{h}m"] = mfe
        da[f"mae_pips_{h}m"] = mae
    da_rows.append(da)

    # Entry mechanism counterfactuals (post-anchor, 2h cap-aware)
    def _try_fill(gen_dt, direction, entry, stop, target):
        if any(x is None for x in (gen_dt, direction, entry, stop, target)):
            return {}
        enb = max(gen_dt, dt.datetime.now(UTC) - se.MAX_FILL_LOOKBACK_SECONDS * dt.timedelta(seconds=1))
        # For this historical pass, don't apply live lookback — use scen gen.
        enb = gen_dt
        d = direction.upper()
        post = [c for c in candles_sorted if c["ts_close"] > enb]
        entry_bar = None
        for c in post:
            if (d == "BUY" and c["c"] > entry) or (d == "SELL" and c["c"] < entry):
                entry_bar = c; break
        if not entry_bar:
            return {"status": "no_fill"}
        sim_entry = entry_bar["c"]
        # Monitor exit
        monitor = [c for c in candles_sorted if c["ts_open"] > entry_bar["ts_open"]]
        exit_reason = None; exit_price = None
        for c in monitor:
            if d == "BUY":
                hs = c["l"] <= stop
                ht = c["h"] >= target
            else:
                hs = c["h"] >= stop
                ht = c["l"] <= target
            if hs and ht:
                exit_reason = "AMBIGUOUS"; exit_price = c["c"]; break
            if hs:
                exit_reason = "STOP_HIT"; exit_price = stop; break
            if ht:
                exit_reason = "TARGET_HIT"; exit_price = target; break
        g = None
        if exit_price is not None:
            g = round((exit_price - sim_entry) * (1 if d == "BUY" else -1), 1)
        return {"status": "fill",
                "entry_bar_ts": entry_bar["ts_open"].isoformat(),
                "simulated_entry": sim_entry,
                "exit_reason": exit_reason or "OPEN",
                "gross_pips": g}

    cf = _try_fill(first_ready_ts, initial_direction, initial_entry, initial_stop, initial_target)

    # Walk revisions for drift CSV
    for r in revs:
        tp = _trade_proposal(r)
        rev_dir = (tp or {}).get("direction") or (_primary_opp(r) or {}).get("direction") or ""
        rd_rows.append({
            "scenario_id": sid,
            "revision_idx": r.get("revision_idx"),
            "generated_at_utc": r.get("generated_at_utc"),
            "pub_decision": (r.get("publication_decision") or {}).get("decision"),
            "direction": rev_dir,
            "entry_price": tp.get("entry_price") if tp else None,
            "stop_price": tp.get("stop_price") if tp else None,
            "target_price": tp.get("target_price") if tp else None,
            "mkt_close_at_rev": _close_at_or_before(_parse_ts(r.get("generated_at_utc"))) if r.get("generated_at_utc") else None,
        })

    # Geometry on initial-READY proposal
    reward_pips = None
    risk_pips = None
    rr = None
    if initial_entry is not None and initial_target is not None:
        reward_pips = round(abs(initial_target - initial_entry), 1)
    if initial_entry is not None and initial_stop is not None:
        risk_pips = round(abs(initial_entry - initial_stop), 1)
    if reward_pips is not None and risk_pips is not None and risk_pips > 0:
        rr = round(reward_pips / risk_pips, 2)

    eq_rows.append({
        "scenario_id": sid,
        "n_revisions": len(revs),
        "first_directional_rev": first_dir_rev,
        "first_directional_ts": first_dir_ts.isoformat() if first_dir_ts else None,
        "first_directional_price": price_at_first_dir,
        "first_ready_rev": first_ready_rev,
        "first_ready_ts": first_ready_ts.isoformat() if first_ready_ts else None,
        "first_ready_price": price_at_first_ready,
        "initial_direction": initial_direction,
        "initial_entry": initial_entry,
        "initial_stop": initial_stop,
        "initial_target": initial_target,
        "initial_reward_pips": reward_pips,
        "initial_risk_pips": risk_pips,
        "initial_rr": rr,
        "pips_price_to_entry_at_first_ready": (
            round((initial_entry - price_at_first_ready) * (1 if initial_direction == "BUY" else -1), 1)
            if (initial_entry is not None and price_at_first_ready is not None and initial_direction) else None
        ),
        "cf_entry_bar_ts": cf.get("entry_bar_ts"),
        "cf_simulated_entry": cf.get("simulated_entry"),
        "cf_exit_reason": cf.get("exit_reason"),
        "cf_gross_pips": cf.get("gross_pips"),
        "latest_rev": last.get("revision_idx"),
        "latest_direction": last_dir,
    })

# =====================================================================
# Write outputs
# =====================================================================

def _write_csv(path: pathlib.Path, rows: list[dict]):
    if not rows:
        path.write_text("")
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


_write_csv(OUT_DIR / "entry_quality_dataframe.csv", eq_rows)
_write_csv(OUT_DIR / "revision_drift.csv", rd_rows)
_write_csv(OUT_DIR / "directional_accuracy.csv", da_rows)

print(f"wrote {len(eq_rows)} entry-quality rows → {OUT_DIR / 'entry_quality_dataframe.csv'}")
print(f"wrote {len(rd_rows)} revision rows → {OUT_DIR / 'revision_drift.csv'}")
print(f"wrote {len(da_rows)} directional-accuracy rows → {OUT_DIR / 'directional_accuracy.csv'}")

# Quick summary printed to stdout
import statistics as st
rrs = [r['initial_rr'] for r in eq_rows if r['initial_rr'] is not None]
if rrs:
    print(f"initial R:R  n={len(rrs)}  median={st.median(rrs):.2f}  mean={st.mean(rrs):.2f}  "
           f"min={min(rrs):.2f}  max={max(rrs):.2f}")
rewards = [r['initial_reward_pips'] for r in eq_rows if r['initial_reward_pips'] is not None]
if rewards:
    print(f"initial reward pips  n={len(rewards)}  median={st.median(rewards):.1f}  "
           f"mean={st.mean(rewards):.1f}  min={min(rewards):.1f}  max={max(rewards):.1f}")
pr2e = [r['pips_price_to_entry_at_first_ready'] for r in eq_rows
        if r['pips_price_to_entry_at_first_ready'] is not None]
if pr2e:
    print(f"price→entry pips at first_ready  n={len(pr2e)}  "
           f"median={st.median(pr2e):.1f}  mean={st.mean(pr2e):.1f}  "
           f"min={min(pr2e):.1f}  max={max(pr2e):.1f}")
