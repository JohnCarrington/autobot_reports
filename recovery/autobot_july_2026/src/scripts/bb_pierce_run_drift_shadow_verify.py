"""Verify BB_PIERCE_RUN drift_ratio shadow logging:
  1. Schema: drift_ratio_6 + drift_ratio_8 present in every emitted
     record.
  2. Pre-existing fields preserved (no schema break).
  3. Math: each record's drift_ratio matches an independent reference
     (path-efficiency convention: net_disp / total_movement over last N
     transitions, range [0,1]).
  4. Today's two BB_BOUNCE fires reproduce the diagnostic numbers:
       06:10 SHORT (bar 06:05): drift_6 ≈ 0.639
       06:55 LONG  (bar 06:50): drift_6 ≈ 0.743
     (07:05 BRIEFING_EXEC fire is a different strategy and does NOT
     appear in this log — its 0.837 was computed independently from
     candles. Verified separately, not via this probe.)

Read-only — writes shadow log to /tmp.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

SHADOW_LOG = "/tmp/drift_shadow_probe.jsonl"
if os.path.exists(SHADOW_LOG):
    os.remove(SHADOW_LOG)
os.environ["GBPUSD_BB_BOUNCE_ENABLED"] = "1"
os.environ["GBPUSD_BB_EXHAUSTION_LOG_PATH"] = SHADOW_LOG
os.environ["GBPUSD_REGIME_LOG_PATH"] = "/tmp/drift_shadow_regime.jsonl"

import gbpusd_bb_bounce as bb  # noqa: E402

for _h in list(bb.logger.handlers):
    bb.logger.removeHandler(_h)
bb.logger.propagate = False
bb.logger.setLevel(logging.WARNING)

CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"
EPIC_GBPUSD = "CS.D.GBPUSD.TODAY.IP"


def ref_drift_ratio(closes: List[float], n: int) -> float:
    """Independent reference computation."""
    if len(closes) < n + 1 or n <= 0:
        return float("nan")
    end = len(closes) - 1
    start = end - n
    net = abs(closes[end] - closes[start])
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(start + 1, end + 1))
    return net / path if path > 0 else float("nan")


def load_day(d: str) -> List[bb.Bar]:
    p = CANDLE_DIR / f"{d}.csv"
    out: List[bb.Bar] = []
    if not p.exists():
        return out
    with open(p) as f:
        for r in csv.DictReader(f):
            out.append(bb.Bar(
                timestamp=datetime.fromisoformat(r["timestamp"]),
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]),  close=float(r["close"]),
            ))
    return out


def load_history(end_date: str, lookback_days: int = 4) -> List[bb.Bar]:
    end = datetime.fromisoformat(end_date).date()
    bars: List[bb.Bar] = []
    cur = end - timedelta(days=lookback_days)
    while cur <= end:
        bars.extend(load_day(cur.isoformat()))
        cur += timedelta(days=1)
    bars.sort(key=lambda b: b.timestamp)
    return bars


def replay_today() -> List[Dict]:
    bars = load_history("2026-05-04", lookback_days=4)
    bb.GbpUsdBBBounceStrategy._instance = None
    strat = bb.GbpUsdBBBounceStrategy.instance()
    target_date = datetime.fromisoformat("2026-05-04").date()
    end_target = datetime.fromisoformat("2026-05-04").replace(
        hour=23, tzinfo=timezone.utc,
    )
    for i, bar in enumerate(bars):
        if bar.timestamp > end_target:
            break
        history = bars[: i + 1]
        if len(history) < bb.BB_PERIOD + 1:
            continue
        try:
            strat.evaluate(
                symbol="GBPUSD", epic=EPIC_GBPUSD,
                ts=bar.timestamp, bars=history,
                closes_ind=[b.close for b in history],
            )
        except Exception:
            continue
    if not os.path.exists(SHADOW_LOG):
        return []
    records: List[Dict] = []
    with open(SHADOW_LOG, "r") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if str(rec.get("ts", "")).startswith("2026-05-04"):
                    records.append(rec)
            except Exception:
                continue
    return records


NEW_FIELDS = ("drift_ratio_6", "drift_ratio_8")
PRESERVED_FIELDS = (
    "ts", "symbol", "direction", "setup_ts", "setup_age_bars",
    "regime", "regime_confidence", "regime_signals", "regime_gate_blocks",
    # MACD shadow added in prior commit — must still be present.
    "macd_line", "macd_signal", "macd_histogram",
    "macd_aligned_with_trade", "macd_diverging_from_trade",
)


def check_schema(records: List[Dict]) -> bool:
    print("\n(1) SCHEMA — drift fields present, all preserved fields intact")
    if not records:
        print("  FAIL: no records emitted")
        return False
    ok = True
    for rec in records:
        missing_new = [f for f in NEW_FIELDS if f not in rec]
        missing_old = [f for f in PRESERVED_FIELDS if f not in rec]
        if missing_new:
            print(f"  FAIL: ts={rec.get('ts')} missing new: {missing_new}")
            ok = False
        if missing_old:
            print(f"  FAIL: ts={rec.get('ts')} missing pre-existing: {missing_old}")
            ok = False
    if ok:
        print(f"  PASS: {len(records)} records, "
              f"2 new + {len(PRESERVED_FIELDS)} pre-existing fields all present")
    return ok


def check_math(records: List[Dict]) -> bool:
    print("\n(2) MATH — drift_ratio matches independent reference")
    bars = load_history("2026-05-04", lookback_days=4)
    closes = [b.close for b in bars]
    closes_by_ts = {b.timestamp.isoformat(): i for i, b in enumerate(bars)}
    ok = True
    for rec in records:
        idx = closes_by_ts.get(rec["ts"])
        if idx is None:
            print(f"  WARN: ts={rec['ts']} not in archive — skipping")
            continue
        for n, key in ((6, "drift_ratio_6"), (8, "drift_ratio_8")):
            ref = ref_drift_ratio(closes[: idx + 1], n)
            got = rec.get(key)
            if got is None:
                if not math.isnan(ref):
                    print(f"  FAIL: ts={rec['ts']} {key} is None but ref={ref:.4f}")
                    ok = False
                continue
            if math.isnan(ref):
                print(f"  FAIL: ts={rec['ts']} {key}={got} but ref is NaN")
                ok = False
                continue
            if abs(got - ref) > 0.001:
                print(f"  FAIL: ts={rec['ts']} {key}: got={got:.4f} ref={ref:.4f} "
                      f"diff={abs(got - ref):.4f}")
                ok = False
    if ok:
        print(f"  PASS: {len(records)} records × 2 lookbacks all within 0.001 of ref")
    return ok


def check_known_fires(records: List[Dict]) -> bool:
    print("\n(3) KNOWN FIRES — today's 06:10 SHORT and 06:55 LONG match diagnostic")
    by_ts = {r["ts"]: r for r in records}
    expected = {
        "2026-05-04T06:05:00+00:00": {
            "label": "BB_BOUNCE_S 06:10 fire (winner)",
            "direction": "SELL",
            "drift_6_approx": 0.639,
            "drift_8_approx": 0.655,
        },
        "2026-05-04T06:50:00+00:00": {
            "label": "BB_BOUNCE_L 06:55 fire (SL'd)",
            "direction": "BUY",
            "drift_6_approx": 0.743,
            "drift_8_approx": 0.653,
        },
    }
    ok = True
    for ts_key, exp in expected.items():
        rec = by_ts.get(ts_key)
        if rec is None:
            print(f"  FAIL: no record for ts={ts_key}")
            ok = False
            continue
        d6, d8 = rec.get("drift_ratio_6"), rec.get("drift_ratio_8")
        if d6 is None or d8 is None:
            print(f"  FAIL: {exp['label']}: drift fields are None")
            ok = False
            continue
        d6_match = abs(d6 - exp["drift_6_approx"]) < 0.005
        d8_match = abs(d8 - exp["drift_8_approx"]) < 0.005
        dir_match = rec["direction"] == exp["direction"]
        print(f"  {exp['label']}")
        print(f"    direction={rec['direction']} (expected {exp['direction']})")
        print(f"    drift_6={d6:.4f} (diagnostic ≈ {exp['drift_6_approx']:.3f}) — "
              f"{'OK' if d6_match else 'FAIL'}")
        print(f"    drift_8={d8:.4f} (diagnostic ≈ {exp['drift_8_approx']:.3f}) — "
              f"{'OK' if d8_match else 'FAIL'}")
        if not (d6_match and d8_match and dir_match):
            ok = False
    return ok


def check_full_distribution(records: List[Dict]) -> bool:
    print("\n(4) FULL DISTRIBUTION — all 5 BB_BOUNCE fires today")
    if not records:
        return True
    print(f"  {'ts':<32}{'dir':<6}{'drift_6':>10}{'drift_8':>10}")
    for rec in records:
        d6 = rec.get("drift_ratio_6")
        d8 = rec.get("drift_ratio_8")
        d6s = f"{d6:.4f}" if d6 is not None else "None"
        d8s = f"{d8:.4f}" if d8 is not None else "None"
        print(f"  {rec['ts']:<32}{rec['direction']:<6}{d6s:>10}{d8s:>10}")
    return True


def main() -> int:
    print("=" * 78)
    print("BB_PIERCE_RUN drift_ratio shadow logging — verification probe")
    print(f"Shadow log → {SHADOW_LOG}")
    print("=" * 78)
    records = replay_today()
    print(f"\nReplay produced {len(records)} shadow-log records on 2026-05-04")
    rc = 0
    if not check_schema(records):       rc = 1
    if not check_math(records):         rc = 1
    if not check_known_fires(records):  rc = 1
    check_full_distribution(records)
    print()
    print("=" * 78)
    print("OVERALL:", "PASS" if rc == 0 else "FAIL")
    print("=" * 78)
    return rc


if __name__ == "__main__":
    sys.exit(main())
