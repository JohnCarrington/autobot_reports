"""Real-data probe for gbpusd_bb_reversal_patterns over 2026-04-27..05-01.

For each day:
  - V-shaped fires + simulated PnL + hit rate
  - Arc fires + simulated PnL + hit rate
  - Combined daily total
  - Co-fire suppression count (BB_PIERCE_RUN's _bb_pierce_run_active)

Friday 2026-05-01 specifically:
  - Did either pattern catch the +60p afternoon SHORT move (~14:00-14:30)?

PnL approximation: SL=12p hard, TP=+30p (TP1 fallback), 240m time stop.
The live multi-tier briefing TP is not replayable without the original
briefing snapshot; this gives a directionally-correct PnL picture.
"""
from __future__ import annotations

import csv
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

# Force-enable strategy + both patterns. Disable regime gate for the
# probe — we want to see the un-gated fire surface; the gate is shipped
# as a separate signal in production logs.
os.environ.setdefault("GBPUSD_BB_REVERSAL_PATTERNS_ENABLED", "1")
os.environ.setdefault("GBPUSD_BB_REVERSAL_V_ENABLED", "1")
os.environ.setdefault("GBPUSD_BB_REVERSAL_ARC_ENABLED", "1")
os.environ.setdefault("GBPUSD_BB_REVERSAL_NEWS_BLACKOUT_ENABLED", "0")
os.environ["GBPUSD_REGIME_LOG_PATH"] = "/tmp/regime_brp_probe.jsonl"

import gbpusd_bb_reversal_patterns as brp  # noqa: E402

# Quiet logger.
for _h in list(brp.logger.handlers):
    brp.logger.removeHandler(_h)
brp.logger.propagate = False
brp.logger.setLevel(logging.WARNING)

CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"
EPIC_GBPUSD = "CS.D.GBPUSD.TODAY.IP"

PIP_SIZE = 1.0
SL_PIPS = 12.0
TP_PIPS = 30.0
TIME_STOP_BARS = 48  # 240 min / 5 min


def _load_day(d: str) -> List[brp.Bar]:
    path = CANDLE_DIR / f"{d}.csv"
    if not path.exists():
        return []
    out: List[brp.Bar] = []
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(brp.Bar(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            ))
    return out


def _load_history(end_date: str, lookback_days: int = 4) -> List[brp.Bar]:
    end = datetime.fromisoformat(end_date).date()
    bars: List[brp.Bar] = []
    cur = end - timedelta(days=lookback_days)
    while cur <= end:
        bars.extend(_load_day(cur.isoformat()))
        cur += timedelta(days=1)
    bars.sort(key=lambda b: b.timestamp)
    return bars


def _simulate_trade(direction: str, entry_idx: int, bars: List[brp.Bar]
                    ) -> Tuple[float, str, datetime]:
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

    last = bars[end - 1] if end > entry_idx + 1 else bars[entry_idx]
    if direction == "BUY":
        pip_pnl = (last.close - entry) / PIP_SIZE
    else:
        pip_pnl = (entry - last.close) / PIP_SIZE
    return pip_pnl, "TIME", last.timestamp


def _replay_day(day: str,
                regime_gate: bool,
                ) -> Tuple[List[Dict], int]:
    """Returns (fires, cofire_blocked_count). Co-fire suppression
    is naturally evaluated since BB_PIERCE_RUN strategy state is
    populated by the parallel simulation below — we re-run BB_PIERCE_RUN
    in lockstep so that _bb_pierce_run_active sees authentic armed-
    setup state.

    Approach: maintain a local BB_PIERCE_RUN strategy instance that
    we feed with the same bars and check what it "would" do at each
    bar. We then mirror that into bb_bounce.strategy._armed_setups so
    brp's co-fire check finds the same state production would.
    """
    os.environ["GBPUSD_BB_REVERSAL_REGIME_FILTER_ENABLED"] = "true" if regime_gate else "false"
    brp.REGIME_FILTER_ENABLED = regime_gate

    # Run BB_PIERCE_RUN in lockstep so co-fire suppression has real
    # armed-setup state to consult.
    os.environ.setdefault("GBPUSD_BB_BOUNCE_ENABLED", "1")
    import gbpusd_bb_bounce as bbb  # noqa: E402
    for _h in list(bbb.logger.handlers):
        bbb.logger.removeHandler(_h)
    bbb.logger.propagate = False
    bbb.logger.setLevel(logging.WARNING)
    bbb.GbpUsdBBBounceStrategy._instance = None
    bbb_strat = bbb.GbpUsdBBBounceStrategy.instance()

    # Reset BRP strategy for this day.
    brp.GbpUsdBBReversalPatternsStrategy._instance = None
    strat = brp.GbpUsdBBReversalPatternsStrategy.instance()

    bars = _load_history(day, lookback_days=4)
    fires: List[Dict] = []
    cofire_blocks = 0
    target_date = datetime.fromisoformat(day).date()

    for i, bar in enumerate(bars):
        if bar.timestamp.date() > target_date:
            break
        history = bars[: i + 1]
        if len(history) < brp.BB_PERIOD + 1:
            continue
        closes = [b.close for b in history]

        # 1) Step BB_PIERCE_RUN forward — populates its armed setups.
        try:
            bbb_strat.evaluate(
                symbol="GBPUSD",
                epic=EPIC_GBPUSD,
                ts=bar.timestamp,
                bars=history,
                closes_ind=closes,
            )
        except Exception:
            pass

        # 2) Detect what the patterns *would* fire on (pre-cofire) so
        #    we can count cofire blocks separately. We do this by
        #    inspecting the pattern detectors directly.
        if i < 2:
            continue
        try:
            bb_lower_n,    _bbm_n,   bb_upper_n    = brp._bb_20_2(closes)
            bb_lower_prev, _bbm_p,   bb_upper_prev = brp._bb_20_2(closes[:-1])
        except ValueError:
            continue

        bb_width_n_pips    = (bb_upper_n - bb_lower_n) / PIP_SIZE
        bb_width_prev_pips = (bb_upper_prev - bb_lower_prev) / PIP_SIZE
        prev = history[-2]
        cur = history[-1]

        v_ev, _ = brp._detect_v(prev, cur, bb_lower_prev, bb_upper_prev,
                                bb_width_prev_pips)
        arc_ev, _ = brp._detect_arc(history, bb_lower_n, bb_upper_n,
                                    bb_width_n_pips)
        candidate = v_ev or arc_ev
        if candidate is not None:
            cand_dir = "BUY" if candidate.direction == "LONG" else "SELL"
            cofire, _r = brp._bb_pierce_run_active(cand_dir, EPIC_GBPUSD, bar.timestamp)
            if cofire and bar.timestamp.date() == target_date:
                cofire_blocks += 1

        # 3) Run the actual evaluate (with all gates) for the fire log.
        try:
            decision = strat.evaluate(
                symbol="GBPUSD", epic=EPIC_GBPUSD,
                ts=bar.timestamp, bars=history, closes_ind=closes,
            )
        except Exception:
            continue
        if decision is None:
            continue
        if bar.timestamp.date() != target_date:
            continue
        if not (brp.WIN_START <= bar.timestamp.time() < brp.WIN_END):
            continue

        sig = str(getattr(decision, "signal", "")).upper()
        mode = getattr(decision, "mode", "?")
        pattern = (getattr(decision, "debug", None) or {}).get("pattern", "?")
        direction = "BUY" if sig == "BUY" else "SELL"
        pnl, exit_reason, exit_ts = _simulate_trade(direction, i, bars)
        fires.append({
            "ts": bar.timestamp,
            "pattern": pattern,
            "direction": direction,
            "mode": mode,
            "entry": bar.close,
            "pnl_pips": pnl,
            "exit_reason": exit_reason,
            "exit_ts": exit_ts,
        })
    return fires, cofire_blocks


def _print_day(day: str, fires: List[Dict], cofire_blocks: int) -> None:
    v = [f for f in fires if f["pattern"] == "V"]
    arc = [f for f in fires if f["pattern"] == "ARC"]
    if not fires:
        print(f"  {day}: 0 fires (cofire_suppressed={cofire_blocks})")
        return
    total = sum(f["pnl_pips"] for f in fires)
    wins = sum(1 for f in fires if f["pnl_pips"] > 0)
    print(f"\n  {day}: {len(fires)} fires (V={len(v)}, ARC={len(arc)}, "
          f"cofire_suppressed={cofire_blocks})  total={total:+.1f}p  "
          f"hit={wins}/{len(fires)} ({100*wins/len(fires):.0f}%)")
    print(f"    {'time':<9s}{'pat':<5s}{'dir':<5s}{'mode':<23s}{'entry':>10s}  {'pnl':>7s}  exit")
    for f in fires:
        print(f"    {f['ts'].strftime('%H:%M:%S'):<9s}"
              f"{f['pattern']:<5s}{f['direction']:<5s}{f['mode']:<23s}"
              f"{f['entry']:>10.2f}  {f['pnl_pips']:+7.1f}p  "
              f"{f['exit_reason']:<5s} @ {f['exit_ts'].strftime('%H:%M')}")


def main() -> None:
    days = ["2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30", "2026-05-01"]

    print("=" * 80)
    print("GBPUSD_BB_REV_PAT (V + Arc) — 5-day real-data probe")
    print(f"PnL approx: SL={SL_PIPS}p  TP={TP_PIPS}p  time_stop={TIME_STOP_BARS}b (240m)")
    print(f"Window: {brp.WIN_START.strftime('%H:%M')}-{brp.WIN_END.strftime('%H:%M')} UTC")
    print(f"Regime gate: ON (TRENDING blocks)  News blackout: OFF for probe")
    print("=" * 80)

    grand_fires: List[Dict] = []
    grand_cofire = 0
    daily_counts: List[int] = []
    for day in days:
        fires, cofire_blocks = _replay_day(day, regime_gate=True)
        _print_day(day, fires, cofire_blocks)
        grand_fires.extend(fires)
        grand_cofire += cofire_blocks
        daily_counts.append(len(fires))

    print("\n" + "=" * 80)
    print("Grand totals — 5 days")
    print("=" * 80)
    n = len(grand_fires)
    if n:
        v_n   = sum(1 for f in grand_fires if f["pattern"] == "V")
        a_n   = sum(1 for f in grand_fires if f["pattern"] == "ARC")
        v_pnl = sum(f["pnl_pips"] for f in grand_fires if f["pattern"] == "V")
        a_pnl = sum(f["pnl_pips"] for f in grand_fires if f["pattern"] == "ARC")
        wins  = sum(1 for f in grand_fires if f["pnl_pips"] > 0)
        v_wins = sum(1 for f in grand_fires if f["pattern"] == "V" and f["pnl_pips"] > 0)
        a_wins = sum(1 for f in grand_fires if f["pattern"] == "ARC" and f["pnl_pips"] > 0)
        total = sum(f["pnl_pips"] for f in grand_fires)
        print(f"  V    : {v_n:3d} fires  total={v_pnl:+7.1f}p  "
              f"hit={v_wins}/{v_n} ({100*v_wins/max(v_n,1):.0f}%)")
        print(f"  ARC  : {a_n:3d} fires  total={a_pnl:+7.1f}p  "
              f"hit={a_wins}/{a_n} ({100*a_wins/max(a_n,1):.0f}%)")
        print(f"  TOTAL: {n:3d} fires  total={total:+7.1f}p  "
              f"hit={wins}/{n} ({100*wins/n:.0f}%)")
        print(f"  Co-fire suppressed (BB_PIERCE_RUN active): {grand_cofire}")
        print(f"  Daily counts: {daily_counts}  avg={sum(daily_counts)/len(daily_counts):.1f}/day  max={max(daily_counts)}")
    else:
        print(f"  0 fires across 5 days  (cofire_suppressed={grand_cofire})")
        print(f"  Daily counts: {daily_counts}")

    # Friday afternoon target window check.
    print("\n" + "=" * 80)
    print("Friday 2026-05-01 — afternoon SHORT around 14:00-14:30 (the +60p user-flagged move)")
    print("=" * 80)
    fri_fires = [f for f in grand_fires if f["ts"].date() == datetime.fromisoformat("2026-05-01").date()]
    afternoon = [f for f in fri_fires if 13 <= f["ts"].hour <= 15]
    if not afternoon:
        print("  No fires in 13:00-15:59 on Friday.")
    else:
        for f in afternoon:
            print(f"  {f['ts'].strftime('%H:%M:%S')}  {f['pattern']}  {f['direction']}  "
                  f"entry={f['entry']:.2f}  pnl={f['pnl_pips']:+.1f}p  "
                  f"exit={f['exit_reason']} @ {f['exit_ts'].strftime('%H:%M')}")


if __name__ == "__main__":
    main()
