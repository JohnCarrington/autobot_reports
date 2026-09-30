"""Smoke test for exhaustion shadow logging.

Replays the 7 known fire candidates (6 Thu 2026-04-30 SHORTs + Fri 2026-
05-01 14:05) plus the two Friday required winners through the regime-
gated evaluate(), then asserts that every fire candidate produced a
JSONL record in the exhaustion shadow sidecar.

Pure read-only — uses /tmp paths for sidecars so live logs are untouched.
The shadow logger NEVER blocks; the regime gate behaviour is unchanged.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GBPUSD_BB_BOUNCE_ENABLED", "1")
os.environ.setdefault("GBPUSD_BB_BOUNCE_REGIME_FILTER_ENABLED", "true")
os.environ.setdefault("GBPUSD_BB_BOUNCE_EXHAUSTION_SHADOW_ENABLED", "true")
os.environ["GBPUSD_REGIME_LOG_PATH"] = "/tmp/regime_smoke.jsonl"
os.environ["GBPUSD_BB_EXHAUSTION_LOG_PATH"] = "/tmp/exhaustion_shadow_smoke.jsonl"

# Fresh sidecars.
for _p in ("/tmp/regime_smoke.jsonl", "/tmp/exhaustion_shadow_smoke.jsonl"):
    try:
        os.remove(_p)
    except FileNotFoundError:
        pass

import gbpusd_bb_bounce as bb  # noqa: E402

for _h in list(bb.logger.handlers):
    bb.logger.removeHandler(_h)
bb.logger.propagate = False

CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"
EPIC = "CS.D.GBPUSD.TODAY.IP"


def _load_day(d: str) -> List[bb.Bar]:
    path = CANDLE_DIR / f"{d}.csv"
    if not path.exists():
        return []
    out: List[bb.Bar] = []
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(bb.Bar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
            ))
    return out


def _load_history(end: str, lookback_days: int = 4) -> List[bb.Bar]:
    end_d = datetime.fromisoformat(end).date()
    bars: List[bb.Bar] = []
    cur = end_d - timedelta(days=lookback_days)
    while cur <= end_d:
        bars.extend(_load_day(cur.isoformat()))
        cur += timedelta(days=1)
    bars.sort(key=lambda b: b.timestamp)
    return bars


def _replay_until(strategy: bb.GbpUsdBBBounceStrategy,
                  bars: List[bb.Bar],
                  target_ts: datetime) -> Tuple[List[Tuple[datetime, str, str]],
                                                 List[Tuple[datetime, str]]]:
    """Returns (fire_decisions, all_fire_candidates_at_or_below_target).
    A "fire candidate" is any evaluation that reached the regime/shadow
    log block — we infer this from the JSONL sidecar after the run."""
    decisions: List[Tuple[datetime, str, str]] = []
    candidates: List[Tuple[datetime, str]] = []
    for i, bar in enumerate(bars):
        if bar.timestamp > target_ts:
            break
        history = bars[: i + 1]
        if len(history) < bb.BB_PERIOD + 1:
            continue
        closes = [b.close for b in history]
        try:
            decision = strategy.evaluate(
                symbol="GBPUSD", epic=EPIC,
                ts=bar.timestamp, bars=history, closes_ind=closes,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! evaluate raised at {bar.timestamp}: {exc}")
            continue
        if decision is not None:
            decisions.append((bar.timestamp,
                              getattr(decision, "signal", "?"),
                              getattr(decision, "mode", "?")))
    return decisions, candidates


def _fresh() -> bb.GbpUsdBBBounceStrategy:
    bb.GbpUsdBBBounceStrategy._instance = None
    return bb.GbpUsdBBBounceStrategy.instance()


def _read_jsonl(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    out: List[Dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _smoke_target(label: str, day: str, hh: int, mm: int) -> Dict:
    """Replay history up through target_ts and return both whether a
    decision fired AND whether the shadow sidecar gained a record at
    that timestamp."""
    target = datetime.fromisoformat(day).replace(
        hour=hh, minute=mm, second=0, microsecond=0, tzinfo=timezone.utc,
    )
    bars = _load_history(day, 4)

    sink: List[str] = []
    h = logging.Handler()
    h.emit = lambda r: sink.append(h.format(r))  # noqa: E731
    bb.logger.addHandler(h)
    bb.logger.setLevel(logging.INFO)

    # Snapshot sidecar size before this replay so we can pick out only
    # the records produced by THIS replay.
    before_lines = _read_jsonl("/tmp/exhaustion_shadow_smoke.jsonl")
    try:
        strat = _fresh()
        decisions, _ = _replay_until(strat, bars, target)
    finally:
        bb.logger.removeHandler(h)

    after_lines = _read_jsonl("/tmp/exhaustion_shadow_smoke.jsonl")
    new_records = after_lines[len(before_lines):]
    target_records = [r for r in new_records
                      if r.get("ts") == target.isoformat()]
    target_decisions = [d for d in decisions if d[0] == target]

    return {
        "label": label, "ts": target,
        "fired": bool(target_decisions),
        "decision": target_decisions,
        "shadow_record_at_target": target_records,
        "all_target_day_records": [r for r in new_records
                                   if r.get("ts", "").startswith(day)],
    }


def main() -> int:
    print("=" * 92)
    print("BB_PIERCE_RUN exhaustion shadow-logging smoke test")
    print(f"REGIME_FILTER_ENABLED      = {bb.REGIME_FILTER_ENABLED}")
    print(f"EXHAUSTION_SHADOW_ENABLED  = {bb.EXHAUSTION_SHADOW_ENABLED}")
    print(f"sidecar = {os.environ['GBPUSD_BB_EXHAUSTION_LOG_PATH']}")
    print("=" * 92)

    # 6 Thu fires + Fri 14:05 = 7 fire candidates the user wants logged.
    targets = [
        ("Thu 08:10",  "2026-04-30",  8, 10),
        ("Thu 09:55",  "2026-04-30",  9, 55),
        ("Thu 11:00",  "2026-04-30", 11,  0),
        ("Thu 14:30",  "2026-04-30", 14, 30),
        ("Thu 15:00",  "2026-04-30", 15,  0),
        ("Thu 15:10",  "2026-04-30", 15, 10),
        ("Fri 14:05",  "2026-05-01", 14,  5),
    ]
    winners = [
        ("Fri 06:05 BUY",  "2026-05-01",  6,  5),
        ("Fri 13:50 LONG", "2026-05-01", 13, 50),
    ]

    results = []
    for label, day, hh, mm in targets + winners:
        r = _smoke_target(label, day, hh, mm)
        results.append(r)
        rec = r["shadow_record_at_target"]
        rec_summary = "(no record)"
        if rec:
            rec0 = rec[0]
            rec_summary = (
                f"setup_age={rec0.get('setup_age_bars')}b "
                f"dir={rec0.get('direction')} "
                f"regime={rec0.get('regime')} "
                f"gate_blocks={rec0.get('regime_gate_blocks')} "
                f"bear_div={rec0.get('bearish_divergence')} "
                f"ob_streak={rec0.get('rsi_ob_streak')} "
                f"bull_div={rec0.get('bullish_divergence')} "
                f"os_streak={rec0.get('rsi_os_streak')}"
            )
        fired_tag = "FIRED" if r["fired"] else "BLOCKED"
        print(f"\n  {label:<18s} {r['ts'].time()}  {fired_tag:<8s}  shadow={rec_summary}")

    print("\n" + "=" * 92)
    print("SMOKE 7/7 ASSERTIONS")
    print("=" * 92)
    fire_candidates = targets  # exclude winners from the 7/7 count
    passes = 0
    for label, day, hh, mm in fire_candidates:
        r = next(x for x in results if x["label"] == label)
        ok = bool(r["shadow_record_at_target"])
        passes += int(ok)
        print(f"  [{ 'OK' if ok else 'FAIL' }]  {label}: shadow record produced = {ok}")
    print(f"\n  TOTAL: {passes}/7 fire candidates have shadow records")

    # Also confirm the two required winners still fire (regime gate
    # behaviour unchanged — shadow logging does not interfere).
    print("\n  Required winners (must still fire):")
    winner_ok = True
    for label, day, hh, mm in winners:
        r = next(x for x in results if x["label"] == label)
        if r["fired"]:
            print(f"    [OK]    {label}: FIRES")
        else:
            print(f"    [FAIL]  {label}: did NOT fire — regression")
            winner_ok = False

    print("\n  Confirm 6 Thu SHORTs all blocked by regime gate:")
    thu_blocked = 0
    for label, day, hh, mm in fire_candidates[:6]:
        r = next(x for x in results if x["label"] == label)
        rec = r["shadow_record_at_target"]
        gate_blocks = (rec[0].get("regime_gate_blocks") if rec else None)
        if not r["fired"]:
            thu_blocked += 1
        tag = "BLOCKED" if not r["fired"] else "FIRED"
        print(f"    {label}: {tag}  (gate_blocks_in_record={gate_blocks})")
    print(f"    -> {thu_blocked}/6 Thursday fires blocked by regime")

    overall = (passes == 7) and winner_ok
    print("\n" + "=" * 92)
    print(f"VERDICT: {'PASS' if overall else 'FAIL'}")
    print("=" * 92)
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
