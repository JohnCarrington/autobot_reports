"""Backtest BB_PIERCE_RUN with the regime gate ON vs OFF for
2026-04-30 and 2026-05-01.

Approximate PnL: every fire is simulated with hard SL=12p and TP=+30p
(TP1 fallback) — the live multi-tier briefing TP is not replayable
without the original briefing snapshot. Time stop 48 bars (~240 min).
This gives a directionally-correct PnL picture for comparing the gate
on/off regimes; absolute numbers will not match production.
"""
from __future__ import annotations

import csv
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GBPUSD_BB_BOUNCE_ENABLED", "1")
os.environ["GBPUSD_REGIME_LOG_PATH"] = "/tmp/regime_backtest.jsonl"

import gbpusd_bb_bounce as bb  # noqa: E402

# Quiet the bb logger.
for _h in list(bb.logger.handlers):
    bb.logger.removeHandler(_h)
bb.logger.propagate = False
bb.logger.setLevel(logging.WARNING)

CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"
EPIC_GBPUSD = "CS.D.GBPUSD.TODAY.IP"

PIP_SIZE   = 1.0
SL_PIPS    = 12.0
TP_PIPS    = 30.0
TIME_STOP_BARS = 48  # 240 min / 5 min


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


def _simulate_trade(direction: str, entry_idx: int, bars: List[bb.Bar]
                    ) -> Tuple[float, str, datetime]:
    """Return (pip_pnl, exit_reason, exit_ts). Walk bars[entry_idx+1:] up to
    TIME_STOP_BARS forward, exit on SL or TP first; check pessimistically
    (SL before TP if both hit in the same bar)."""
    entry = bars[entry_idx].close
    if direction == "BUY":
        sl_price = entry - SL_PIPS * PIP_SIZE
        tp_price = entry + TP_PIPS * PIP_SIZE
    else:
        sl_price = entry + SL_PIPS * PIP_SIZE
        tp_price = entry - TP_PIPS * PIP_SIZE

    end = min(len(bars), entry_idx + 1 + TIME_STOP_BARS)
    for i in range(entry_idx + 1, end):
        b = bars[i]
        if direction == "BUY":
            if b.low <= sl_price:
                return -SL_PIPS, "SL", b.timestamp
            if b.high >= tp_price:
                return TP_PIPS, "TP", b.timestamp
        else:
            if b.high >= sl_price:
                return -SL_PIPS, "SL", b.timestamp
            if b.low <= tp_price:
                return TP_PIPS, "TP", b.timestamp

    # Time stop — exit at last bar's close.
    last = bars[end - 1] if end > entry_idx + 1 else bars[entry_idx]
    if direction == "BUY":
        pip_pnl = (last.close - entry) / PIP_SIZE
    else:
        pip_pnl = (entry - last.close) / PIP_SIZE
    return pip_pnl, "TIME", last.timestamp


def _replay_day(day: str, gate_enabled: bool) -> List[Dict]:
    os.environ["GBPUSD_BB_BOUNCE_REGIME_FILTER_ENABLED"] = "true" if gate_enabled else "false"
    # Re-read module-level constant.
    bb.REGIME_FILTER_ENABLED = gate_enabled

    bars = _load_history(day, lookback_days=4)
    bb.GbpUsdBBBounceStrategy._instance = None
    strat = bb.GbpUsdBBBounceStrategy.instance()

    fires: List[Dict] = []
    target_date = datetime.fromisoformat(day).date()
    end_target = datetime.fromisoformat(day).replace(
        hour=22, tzinfo=timezone.utc,
    )

    for i, bar in enumerate(bars):
        if bar.timestamp > end_target:
            break
        history = bars[: i + 1]
        if len(history) < bb.BB_PERIOD + 1:
            continue
        closes = [b.close for b in history]
        try:
            decision = strat.evaluate(
                symbol="GBPUSD",
                epic=EPIC_GBPUSD,
                ts=bar.timestamp,
                bars=history,
                closes_ind=closes,
            )
        except Exception:  # noqa: BLE001
            continue
        if decision is None:
            continue
        if bar.timestamp.date() != target_date:
            continue

        side = getattr(decision, "side", "?")
        mode = getattr(decision, "mode", "?")
        direction = "BUY" if side == "BUY" or mode.endswith("_L") else "SELL"
        pnl, reason, exit_ts = _simulate_trade(direction, i, bars)
        fires.append({
            "ts": bar.timestamp,
            "direction": direction,
            "mode": mode,
            "entry": bar.close,
            "pnl_pips": pnl,
            "exit_reason": reason,
            "exit_ts": exit_ts,
        })
    return fires


def _print_trades(label: str, day: str, fires: List[Dict]) -> None:
    if not fires:
        print(f"  [{label}]  {day}: no trades")
        return
    total = sum(f["pnl_pips"] for f in fires)
    wins  = sum(1 for f in fires if f["pnl_pips"] > 0)
    print(f"\n  [{label}]  {day}: {len(fires)} trades  total={total:+.1f}p  wins={wins}/{len(fires)}")
    print(f"    {'time':<10s}{'side':<6s}{'mode':<25s}{'entry':>10s}  {'pnl':>7s}  exit")
    for f in fires:
        print(f"    {f['ts'].strftime('%H:%M:%S'):<10s}"
              f"{f['direction']:<6s}{f['mode']:<25s}"
              f"{f['entry']:>10.2f}  {f['pnl_pips']:+7.1f}p  "
              f"{f['exit_reason']:<5s} @ {f['exit_ts'].strftime('%H:%M')}")


def main() -> None:
    print("=" * 80)
    print("BB_PIERCE_RUN backtest — gate ON vs OFF — 2026-04-30 + 2026-05-01")
    print(f"Approx PnL: SL={SL_PIPS}p  TP={TP_PIPS}p  time_stop={TIME_STOP_BARS}b")
    print("=" * 80)

    grand: Dict[str, float] = defaultdict(float)
    grand_n: Dict[str, int] = defaultdict(int)
    for day in ("2026-04-30", "2026-05-01"):
        for label, gate in (("GATE OFF", False), ("GATE ON ", True)):
            fires = _replay_day(day, gate_enabled=gate)
            _print_trades(label, day, fires)
            grand[label] += sum(f["pnl_pips"] for f in fires)
            grand_n[label] += len(fires)

    print("\n" + "=" * 80)
    print("Grand total — both days combined")
    print("=" * 80)
    for label in ("GATE OFF", "GATE ON "):
        print(f"  {label}: {grand_n[label]} trades  total={grand[label]:+.1f}p  "
              f"avg={grand[label]/max(grand_n[label],1):+.2f}p")

    print("\n" + "=" * 80)
    print("Friday 2026-05-01 — status of named user setups (gate ON)")
    print("=" * 80)
    fri = _replay_day("2026-05-01", gate_enabled=True)
    fri_by_time = {f["ts"].strftime("%H:%M"): f for f in fri}
    targets = [
        ("06:05 morning",        "06:05"),
        ("09:25 LONG setup 3",   "09:25"),
        ("13:50 +60p winner",    "13:50"),
        ("14:00 pre-+60p",       "14:00"),
        ("14:05 +60p candidate", "14:05"),
        ("15:30 sustained",      "15:30"),
    ]
    for label, hhmm in targets:
        f = fri_by_time.get(hhmm)
        if f:
            print(f"  {label:<28s}  FIRED  side={f['direction']}  "
                  f"pnl={f['pnl_pips']:+.1f}p  exit={f['exit_reason']}")
        else:
            print(f"  {label:<28s}  NOT FIRED")


if __name__ == "__main__":
    main()
