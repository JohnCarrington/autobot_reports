"""End-to-end proof walk: classification → dress → ladder arm → PATIENT params.

Prints:
  1. Environment variables in play (DAY_CTX + DRESS_*)
  2. Boot banner from day_context module load
  3. classify_today() output for a stubbed BIG_NEWS day
  4. exit_dress.resolve() for GBPUSD_TREND_V3_L on that day
  5. patient_overlay_params() for the standard base
  6. level_ladder.arm() called with a stubbed pivot lookup
  7. On-disk snapshot readback showing PATIENT overlay applied
  8. No-admission-import guard result
"""
from __future__ import annotations

import importlib
import io
import json
import logging
import os
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone

# Fresh sandbox for state paths
tmp = tempfile.mkdtemp(prefix="proof_")
os.environ["DAY_CTX_ENABLED"] = "1"
os.environ["DAY_CTX_STATE_PATH"] = f"{tmp}/day_ctx.json"
os.environ["LADDER_ENABLED"] = "1"
os.environ["LADDER_MANAGED_MODES"] = "GBPUSD_TREND_V3_L,GBPUSD_TREND_V3_S"
os.environ["LADDER_STATE_PATH"] = f"{tmp}/ladder_state.json"
os.environ["LADDER_TELEMETRY_PATH"] = f"{tmp}/ladder.jsonl"
# use defaults for DRESS_* → LADDER_PATIENT on BIG_NEWS + trend
# Capture the boot banner properly
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

print("========================================================================")
print("  DAY_CTX + EXIT_DRESS end-to-end proof walk")
print("========================================================================")

print("\n[1] ENVIRONMENT VARS IN PLAY")
for k in sorted(os.environ):
    if any(t in k for t in ("DAY_CTX", "DRESS", "LADDER")):
        print(f"    {k}={os.environ[k]}")

print("\n[2] BOOT BANNERS (module load)")
import day_context
importlib.reload(day_context)  # trigger banner
import exit_dress
importlib.reload(exit_dress)
import level_ladder
importlib.reload(level_ladder)

# Stub out the finnhub cache — synthesise a BIG_NEWS day with two events
def _stub_events(iso):
    if iso == "2026-08-14":
        return [
            {"ts": "2026-08-14T13:30:00+00:00", "event": "Non Farm Payrolls", "currency": "USD"},
            {"ts": "2026-08-14T14:00:00+00:00", "event": "Fed Press Conference", "currency": "USD"},
        ]
    return []
day_context._fetch_big_events = _stub_events

print("\n[3] classify_today() — synthetic BIG_NEWS day 2026-08-14")
now_utc = datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)
snap = day_context.classify_today(now_utc)
print("    snap.label       =", snap["label"])
print("    snap.date        =", snap["date"])
print("    snap.big_today.n =", len(snap["big_today"]))
for e in snap["big_today"]:
    print("      *", e["event"], "@", e["ts"])
print("    snap.big_prev.n  =", len(snap["big_prev"]))
print("    snap.big_next.n  =", len(snap["big_next"]))
print("    snap.enabled     =", snap["enabled"])

print("\n[4] exit_dress.resolve() — GBPUSD_TREND_V3_L on BIG_NEWS")
bracket = exit_dress.resolve("GBPUSD_TREND_V3_L", "BIG_NEWS")
print("    resolved bracket =", bracket)

print("\n[5] exit_dress.patient_overlay_params() — base (assess=3, buffer=3p)")
overlay = exit_dress.patient_overlay_params(3, 3.0)
print("    overlay =", overlay)

print("\n[6] level_ladder.arm() — synthetic pivots for the stubbed day")
def _fake_fetch(fire_ts, symbol):
    return (
        {"P": 1.30000, "R1": 1.30020, "R2": 1.30040, "R3": 1.30060,
         "S1": 1.29980, "S2": 1.29960, "S3": 1.29940},
        1.30060, 1.29940, "2026-08-13T00:00:00+00:00", 1,
    )
level_ladder._fetch_pivots_and_pd = _fake_fetch
# and stub day_context.label to reflect our snap consistently
day_context.label = lambda *_a, **_k: "BIG_NEWS"

ok = level_ladder.arm(
    pos_key="EPIC.CS.D.CFDGBPUSD.CFD.IP|GBPUSD_TREND_V3_L",
    mode="GBPUSD_TREND_V3_L",
    direction="BUY",
    symbol="GBPUSD",
    entry_ts=datetime(2026, 8, 14, 8, 5, tzinfo=timezone.utc),
    entry_price=1.30001,
    deal_id="TEST_DEAL_01",
)
print("    arm() returned   =", ok)

print("\n[7] snapshot_state() — verify PATIENT overlay applied on-disk")
st = level_ladder.snapshot_state("EPIC.CS.D.CFDGBPUSD.CFD.IP|GBPUSD_TREND_V3_L")
if st:
    for field in ("mode", "direction", "dress", "day_ctx", "exhaustion",
                  "at_level_pips", "assess_bars", "stop_buffer_pips",
                  "broker_min_pips"):
        print(f"    state.{field:<20s} = {st.get(field)!r}")
    print("    state.rungs             =",
          [r["name"] + "@" + str(r["price"]) for r in (st.get("rungs") or [])])

print("\n[8] on-disk state file")
print("    " + os.environ["LADDER_STATE_PATH"] + ":")
try:
    with open(os.environ["LADDER_STATE_PATH"]) as f:
        print("      " + f.read().replace("\n", "\n      ").rstrip())
except FileNotFoundError:
    print("      (missing)")

print("\n[9] telemetry: last arm event from ladder JSONL")
try:
    with open(os.environ["LADDER_TELEMETRY_PATH"]) as f:
        lines = f.readlines()
        if lines:
            last = json.loads(lines[-1])
            print("    event  =", last.get("event"))
            print("    dress  =", last.get("dress"))
            print("    day_ctx=", last.get("day_ctx"))
            print("    assess_bars      =", last.get("assess_bars"))
            print("    stop_buffer_pips =", last.get("stop_buffer_pips"))
            print("    exhaustion       =", last.get("exhaustion"))
except FileNotFoundError:
    print("    (no telemetry file yet)")

print("\n[10] No-admission-import guard test")
import subprocess
result = subprocess.run(
    ["python3", "-m", "pytest",
     "tests/unit/test_day_context.py::test_no_admission_import_guard",
     "-v", "--tb=short"],
    cwd="/opt/tradingbot", capture_output=True, text=True,
)
print(result.stdout[-500:])
print("    guard test exit code =", result.returncode)

print("\n========================================================================")
print("  END proof walk")
print("========================================================================")
