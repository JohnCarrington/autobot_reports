"""Probe the regime-gated BB_PIERCE_RUN evaluate() against real candles
for 2026-04-30 (the bleed) and 2026-05-01 (the user setups).

Read-only: passes a fresh strategy instance so no live state is touched.
"""
from __future__ import annotations

import csv
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

# Force the strategy ON for the probe; restore caller env on exit.
os.environ.setdefault("GBPUSD_BB_BOUNCE_ENABLED", "1")
os.environ.setdefault("GBPUSD_BB_BOUNCE_REGIME_FILTER_ENABLED", "true")
# Detector log path — keep probe-runs separate from the live JSONL.
os.environ["GBPUSD_REGIME_LOG_PATH"] = "/tmp/regime_probe.jsonl"

import gbpusd_bb_bounce as bb  # noqa: E402

# Strip any default StreamHandler so logger output doesn't drown the
# probe's stdout. Capture handler is added inside _evaluate_at.
for _h in list(bb.logger.handlers):
    bb.logger.removeHandler(_h)
bb.logger.propagate = False

CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"
EPIC_GBPUSD = "CS.D.GBPUSD.TODAY.IP"


def _load_day(d: str) -> List[bb.Bar]:
    path = CANDLE_DIR / f"{d}.csv"
    if not path.exists():
        return []
    out: List[bb.Bar] = []
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(bb.Bar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return out


def _load_history(end_date: str, lookback_days: int = 4) -> List[bb.Bar]:
    end = datetime.fromisoformat(end_date).date()
    bars: List[bb.Bar] = []
    cur = end - timedelta(days=lookback_days)
    while cur <= end:
        bars.extend(_load_day(cur.isoformat()))
        cur += timedelta(days=1)
    bars.sort(key=lambda b: b.timestamp)
    return bars


def _fresh_strategy() -> bb.GbpUsdBBBounceStrategy:
    """Bypass the singleton so each probe run starts state-clean."""
    bb.GbpUsdBBBounceStrategy._instance = None
    return bb.GbpUsdBBBounceStrategy.instance()


def _replay_until(strategy: bb.GbpUsdBBBounceStrategy,
                  bars: List[bb.Bar],
                  target_ts: datetime) -> List[Tuple[datetime, str, str]]:
    """Replay bars chronologically up to AND including `target_ts`,
    feeding evaluate() at each closed bar. Returns a list of
    (bar_ts, decision_kind, reason) for any non-None decisions or
    explicit suppressions in journalctl-style logs."""
    fires: List[Tuple[datetime, str, str]] = []
    for i, bar in enumerate(bars):
        if bar.timestamp > target_ts:
            break
        history = bars[: i + 1]
        if len(history) < bb.BB_PERIOD + 1:
            continue
        closes = [b.close for b in history]
        try:
            decision = strategy.evaluate(
                symbol="GBPUSD",
                epic=EPIC_GBPUSD,
                ts=bar.timestamp,
                bars=history,
                closes_ind=closes,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! evaluate raised at {bar.timestamp}: {exc}")
            continue
        if decision is not None:
            fires.append((bar.timestamp, getattr(decision, "side", "?"),
                          getattr(decision, "mode", "?")))
    return fires


def _evaluate_at(target_day: str, hh: int, mm: int) -> Dict:
    """Return dict with bar_ts, fired (bool), reason classifier verdict."""
    target_ts = datetime.fromisoformat(target_day).replace(
        hour=hh, minute=mm, second=0, microsecond=0, tzinfo=timezone.utc,
    )
    bars = _load_history(target_day, lookback_days=4)

    # Capture INFO-level log lines from the bb logger for THIS evaluate.
    captured: List[str] = []
    handler = _CaptureHandler(captured)
    bb.logger.addHandler(handler)
    bb.logger.setLevel(logging.INFO)
    try:
        strat = _fresh_strategy()
        fires = _replay_until(strat, bars, target_ts)
    finally:
        bb.logger.removeHandler(handler)

    target_fires = [f for f in fires if f[0] == target_ts]
    matched_logs = [
        line for line in captured if line.startswith("[BB_PIERCE_RUN]") and (
            "fire candidate" in line or "fire suppressed" in line
        )
    ]
    return {
        "ts": target_ts,
        "fired": bool(target_fires),
        "fire_decision": target_fires,
        "all_fires_today_up_to_ts": fires,
        "logs": matched_logs[-6:],  # last few lines around the target
    }


class _CaptureHandler(logging.Handler):
    def __init__(self, sink: List[str]) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.append(self.format(record))
        except Exception:  # noqa: BLE001
            pass


def _print_eval(label: str, day: str, hh: int, mm: int) -> None:
    res = _evaluate_at(day, hh, mm)
    fired = res["fired"]
    icon = "FIRED" if fired else "BLOCKED/NONE"
    print(f"\n--- {label}  {day} {hh:02d}:{mm:02d}Z  -> {icon} ---")
    if res["fire_decision"]:
        for f in res["fire_decision"]:
            print(f"  decision: ts={f[0].time()}  side={f[1]}  mode={f[2]}")
    for line in res["logs"]:
        # Truncate to keep the table tight.
        if len(line) > 220:
            line = line[:215] + "..."
        print(f"  log: {line}")
    if fires_today := [f for f in res["all_fires_today_up_to_ts"]
                       if f[0].date() == res["ts"].date()
                       and f[0] != res["ts"]]:
        print(f"  same-day-prior fires: {len(fires_today)}")
        for f in fires_today:
            print(f"    ts={f[0].time()} side={f[1]} mode={f[2]}")


def main() -> None:
    print("=" * 78)
    print("BB_PIERCE_RUN regime-gate probe — branch feat/bb-pierce-run-regime-gate")
    print(f"REGIME_FILTER_ENABLED = {bb.REGIME_FILTER_ENABLED}")
    print("=" * 78)

    print("\nThursday 2026-04-30 — 6 historical SHORT fire times (the bleed)")
    for hh, mm in [(8, 10), (9, 55), (11, 0), (14, 30), (15, 0), (15, 10)]:
        _print_eval(f"04-30 fire {hh:02d}:{mm:02d}", "2026-04-30", hh, mm)

    print("\n\nFriday 2026-05-01 — user setups + winners")
    _print_eval("05-01 06:05 BUY",                  "2026-05-01",  6,  5)
    _print_eval("05-01 09:25 LONG setup 3",         "2026-05-01",  9, 25)
    _print_eval("05-01 14:00 pre-+60p winner",      "2026-05-01", 14,  0)
    _print_eval("05-01 14:05 +60p fire candidate",  "2026-05-01", 14,  5)
    _print_eval("05-01 15:30 sustained move",       "2026-05-01", 15, 30)


if __name__ == "__main__":
    main()
