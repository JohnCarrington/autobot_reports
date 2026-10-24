#!/usr/bin/env python3
"""Stage 2 — Document NMS V3 replay feasibility.

Produces three outputs:
  (a) nms_replay_feasibility.txt — the precise statement of what is and
      is not possible, with the evidence underlying each claim.
  (b) nms_regime_transitions.csv — the few genuine V3 states we can
      recover. Three sources are tried, in order of reliability:
        1. The current `<autobot_prod_root>/cache/session_trend_GBPUSD.json`
           snapshot (post-repair, today only).
        2. The research team's documented replay table in
           reports-public/nms_v3_replacement_20261013/report.md §3.4
           (7 named days, matched with their actual times).
        3. Backup snapshots in <autobot_prod_root>/cache/*.pre-* — these are
           NOT time series, only moment-in-time pre-cutover states.
  (c) nms_isolation_test.txt — proof that in-isolation replay produces no
      transitions, on a day production V3 is known to have fired.
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

OUT = Path("<research_workspace>/outputs/nms_corr")
OUT.mkdir(parents=True, exist_ok=True)
SNAPSHOT_PATH = Path("<autobot_prod_root>/cache/session_trend_GBPUSD.json")
PRE_CUTOVER_BACKUP = Path("<autobot_prod_root>/cache/session_trend_state.json.pre-v3-cutover.20261013T130757Z.bak")
PRE_PROVENANCE_BACKUP = Path("<autobot_prod_root>/cache/session_trend_GBPUSD.json.pre-provenance-20261012T231746Z")
REPLAY_REPORT = Path("<autobot_prod_root>/reports-public/nms_v3_replacement_20261013/report.md")
HOURLY_LOG = Path("<autobot_prod_root>/logs/session_hourly_displacement.jsonl")

# ─── (a) feasibility statement ─────────────────────────────────────
lines = ["NMS V3 Historical Replay — Feasibility",
         "=" * 72,
         "",
         "This file documents precisely what historical NMS V3 state data is",
         "and is not available, before any correlation analysis is attempted.",
         ""]

def L(s=""): lines.append(s); print(s)

L("1. CURRENT NMS V3 SNAPSHOT")
L("-" * 72)
L("Live state is persisted ONLY as a single-point-in-time snapshot:")
L(f"  path:  {SNAPSHOT_PATH}")
if SNAPSHOT_PATH.exists():
    snap = json.loads(SNAPSHOT_PATH.read_text())
    L(f"  session_date:        {snap.get('session_date')}")
    L(f"  schema_version:      {snap.get('schema_version')}")
    L(f"  v3_state:            {snap.get('v3_state')}")
    L(f"  v3_up_score:         {snap.get('v3_up_score')}")
    L(f"  v3_down_score:       {snap.get('v3_down_score')}")
    L(f"  v3_state_since_ts:   {snap.get('v3_state_since_ts')}")
    L(f"  prevailing:          {snap.get('prevailing')}")
    L(f"  prevailing_reason:   {snap.get('prevailing_reason')}")
    L(f"  previous_prevailing: {snap.get('previous_prevailing')}")
    L(f"  prev_started:        {snap.get('previous_prevailing_started_ts')}")
    L(f"  prev_ended:          {snap.get('previous_prevailing_ended_ts')}")
L("")
L("This snapshot is overwritten at every bar-close. There is no append-")
L("only time-series record of V3 regime transitions anywhere on this host.")
L("")

L("2. HISTORICAL LOG STREAMS INSPECTED")
L("-" * 72)
L(f"  {HOURLY_LOG}")
import subprocess
if HOURLY_LOG.exists():
    gbp_rows = subprocess.check_output(
        f'grep -c \'"symbol":"GBPUSD"\' {HOURLY_LOG}',
        shell=True).decode().strip()
    L(f"    GBPUSD rows: {gbp_rows}")
    L(f"    These are hourly displacement samples (price minus London-open),")
    L(f"    one row per {{symbol, hour_ts}}. Starts 2026-10-12. They are")
    L(f"    an INPUT to V3 but do NOT contain v3_state transitions.")
L("")
L("  <autobot_prod_root>/logs/v3_events.jsonl  (and rotated daily)")
L("    Despite the name, these events are from a different v3 system")
L("    (BB-pierce + rejection candidate armer, schema `v3-context-1`).")
L("    They are NOT NMS V3 regime transitions.")
L("")
L("  <autobot_prod_root>/logs/trend_v3.jsonl  (and rotated)")
L("    Also NOT NMS V3 — these are output events from the regime_engine")
L("    strong-trend gate (writes 'event': 'block', 'reason': 'range_gate_")
L("    suppress' etc.). The schema is distinct and uses regime_engine")
L("    labels (STRONG_TREND_UP / TREND_FORMING_DOWN), not NMS V3 states.")
L("")

L("3. BACKUP SNAPSHOTS (NOT TIME-SERIES)")
L("-" * 72)
for p in [PRE_CUTOVER_BACKUP, PRE_PROVENANCE_BACKUP]:
    if p.exists():
        try:
            d = json.loads(p.read_text())
            if "symbols" in d:
                # the state.json has {symbols: {GBPUSD: {...}, ...}}
                g = d["symbols"].get("GBPUSD", {})
            else:
                g = d
            L(f"  {p.name}")
            L(f"    session_date: {g.get('session_date')}")
            L(f"    v3_state:     {g.get('v3_state')}")
            L(f"    prevailing:   {g.get('prevailing')}")
            L(f"    (one moment in time; not a time series)")
        except Exception as e:
            L(f"  {p.name}: parse error: {e}")
L("")

L("4. ISOLATION REPLAY — DOES NOT FIRE")
L("-" * 72)
L("The nms_v3_classifier.py module documents itself as 'pure' and 'zero")
L("I/O'. In practice, when the state machine is run in isolation from a")
L("fresh state against the frozen candle corpus, it produces NO")
L("transitions, even on days where production V3 is documented in")
L("`reports-public/nms_v3_replacement_20261013/report.md §3.4` to have")
L("fired STRONG_DOWN or STRONG_UP.")
L("")
L("Verified on 2026-10-09 (report says STRONG_DOWN at 12:35 UTC, 335 min")
L("after London Open): isolated replay yields 0 transitions, final state")
L("RANGE, scores up/down = None.  (Both pre- and post-BST-patch to the")
L("hardcoded 2026-only BST window.)")
L("")
L("Reason: production V3 relies on pre-London state bridges that supply")
L("the state machine with:")
L("  - confirmed_swings seeded from fractal-pivot detection with lookback")
L("  - EMAs(7/13/21) primed from pre-London bars")
L("  - persisted session anchors (london_open_price, OR window)")
L("  - evidence memory (E1 OR breakout, E3 continuation, E4 confirmed HL)")
L("")
L("Rebuilding those bridges standalone is a non-trivial engineering task")
L("(outside the research-only scope). This confirms the research team's")
L("own test harness note at report.md §3.4: '175 min (test harness seeds")
L("anchor)'.")
L("")

L("5. PRE-REPAIR LIVE RECORDS ARE UNRELIABLE")
L("-" * 72)
L("Per the user brief: 'NMS V3 was repaired on 13 October 2026. Pre-repair")
L("live execution records must not be treated as reliable evidence of")
L("correctly functioning NMS.'")
L("")
L("Even if we had a time-series log of pre-repair V3 states (we don't),")
L("those states would be unreliable.")
L("")

L("6. CONCLUSION: WHAT WE CAN AND CANNOT DO")
L("-" * 72)
L("CAN:")
L(" - Catalogue the 7 named days in the research team's §3.4 replay as")
L("   the only genuine V3 timing data available.")
L(" - Record one post-repair snapshot (today's state).")
L(" - Compute the research team's aggregate claim: 20/23 correct")
L("   direction, 3 wrong, mean delay 158 min — this is the authoritative")
L("   V3-vs-truth number, as published in the report.")
L("")
L("CANNOT:")
L(" - Correlate V3 against the full 277-movement census of this study.")
L(" - Reconstruct V3 states for 2024 and 2025 — classifier doesn't fire")
L("   in isolation; no stored time series.")
L(" - Produce TP30/SL12 or TP40/SL12 trade results for individual")
L("   genuine V3 fires beyond the 7 named days in the §3.4 table.")
L("")
L("What IS reportable is the research team's own result: V3 fires with")
L("~87 % direction accuracy on the 23 directional days they tested, with")
L("a mean delay of 158 min after London Open. 158 min after a 09:00 UK")
L("open (BST) places the earliest fire time at ~11:30 UK — by which")
L("point, from our own Phase-1 corpus, 65 % of trend-day fires are")
L("already > 50 % of the way through the move.")
L("")

(OUT / "nms_replay_feasibility.txt").write_text("\n".join(lines) + "\n")


# ─── (b) nms_regime_transitions.csv — the recoverable V3 data ──────
transitions = []

# The 7 named days from the research team's replay table.
# Source: <autobot_prod_root>/reports-public/nms_v3_replacement_20261013/report.md §3.4.
TEAM_REPLAY = [
    # date, truth, first fire state, fire time UTC, delay min, note
    ("2026-10-13", "UP",   "STRONG_UP",   "08:20",  80, "partial-day truth"),
    ("2026-10-12", "DOWN", "STRONG_DOWN", "09:55", 175, "test harness seeds anchor"),
    ("2026-09-04", "DOWN", "STRONG_DOWN", "08:25",  85, ""),
    ("2026-09-15", "UP",   "STRONG_UP",   "11:35", 275, ""),
    ("2026-09-28", "UP",   "STRONG_DOWN", "10:10", 190, "WRONG DIRECTION (truth UP)"),
    ("2026-09-30", "UP",   "STRONG_DOWN", "08:15",  75, "WRONG DIRECTION (truth UP)"),
    ("2026-10-09", "DOWN", "STRONG_DOWN", "12:35", 335, ""),
]
for date, truth, state, fire_hhmm, delay, note in TEAM_REPLAY:
    transitions.append({
        "source": "research_team_replay",
        "report": "nms_v3_replacement_20261013/report.md §3.4",
        "date": date,
        "truth_direction": truth,
        "v3_state_first_fire": state,
        "v3_fire_ts_utc": f"{date}T{fire_hhmm}:00+00:00",
        "delay_min_after_london_open": delay,
        "direction_correct": "YES" if (
            (truth == "UP" and state == "STRONG_UP") or
            (truth == "DOWN" and state == "STRONG_DOWN")
        ) else "NO",
        "note": note,
    })

# One current snapshot
if SNAPSHOT_PATH.exists():
    snap = json.loads(SNAPSHOT_PATH.read_text())
    transitions.append({
        "source": "live_snapshot",
        "report": "cache/session_trend_GBPUSD.json",
        "date": snap.get("session_date"),
        "truth_direction": "unknown",
        "v3_state_first_fire": snap.get("v3_state"),
        "v3_fire_ts_utc": snap.get("v3_state_since_ts"),
        "delay_min_after_london_open": None,
        "direction_correct": "n/a",
        "note": f"up={snap.get('v3_up_score')} dn={snap.get('v3_down_score')} prevailing={snap.get('prevailing')}",
    })

if transitions:
    with (OUT / "nms_regime_transitions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(transitions[0].keys()))
        w.writeheader()
        for r in transitions:
            w.writerow(r)
    print(f"\nWrote nms_regime_transitions.csv: {len(transitions)} rows")

# ─── (c) nms_isolation_test.txt — the proof-of-non-fire ─────────────
import pandas as pd
sys.path.insert(0, '<autobot_prod_root>')
sys.path.insert(0, '<research_workspace>/scripts')
import nms_v3_patch  # noqa: F401
import nms_v3_classifier as nms  # noqa: E402

iso_lines = ["Isolation replay — proof-of-non-fire",
             "=" * 72, ""]
for date in ["2026-10-09", "2026-09-04", "2026-09-15"]:
    truth = next((t for t in TEAM_REPLAY if t[0] == date), None)
    path = Path(f"<autobot_prod_root>/data/candles/GBPUSD/{date}.csv")
    if not path.exists():
        path = Path(f"<autobot_prod_root>/data/candles_ext_v2/GBPUSD/{date}.csv")
    df = pd.read_csv(path)
    df.timestamp = pd.to_datetime(df.timestamp, utc=True)
    state = nms.fresh_state("GBPUSD", session_date=date)
    first_fire = None
    for _, r in df.iterrows():
        bar = {"ts": r.timestamp.isoformat(), "o": r.open/10000, "h": r.high/10000,
               "l": r.low/10000, "c": r.close/10000}
        state, res = nms.advance(state, bar)
        if res.get("state") in ("EMERGING_UP","EMERGING_DOWN","STRONG_UP","STRONG_DOWN") and first_fire is None:
            first_fire = (r.timestamp.isoformat(), res["state"])
    iso_lines.append(f"{date}")
    iso_lines.append(f"  Research-team replay says: {truth[2]} at {truth[3]} UTC (delay {truth[4]} min)")
    iso_lines.append(f"  Isolation replay: first fire = {first_fire}")
    iso_lines.append(f"  Final state: {state.get('state')}  up={state.get('up_score')}  dn={state.get('down_score')}")
    iso_lines.append("")

(OUT / "nms_isolation_test.txt").write_text("\n".join(iso_lines) + "\n")
print("\n" + "\n".join(iso_lines))
