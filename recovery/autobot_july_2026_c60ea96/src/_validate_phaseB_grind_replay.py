"""Phase-B grind replay: data-pick the loosened DECISIVE_PIPS default.

Walks the most recent N GBPUSD trading days in data/candles/GBPUSD/,
mirrors the bars-replicate fresh-break detector that runs in gbpusd_
structure_break._detect, computes break_pips per candidate threshold,
and simulates fixed TP/SL forward outcomes to assess the QUALITY of
the extra entries each loosened threshold would enable.

We intentionally DO NOT emulate htf_authority._structure_dir or
regime_engine state — those need the live process. Instead we use a
purely-structural fresh-break test (close breaks prior-N high/low by
> 0p) which captures the SAME thrust events the live detector targets.
This isolates the DECISIVE_PIPS gate effect cleanly: the relative
ordering of candidate thresholds (which thresholds produce GOOD extras
vs noise) is what we care about, not absolute fire counts.

Exit rule (simulated, doc'd here so reviewers can audit):
  TP = +12 pips from entry (close_at_flip)
  SL =  -6 pips from entry
  Walk forward bar-by-bar; first touched wins; MFE/MAE tracked
  across the next 10 bars regardless. If neither touched within the
  forward window (we cap at 30 bars to keep runtime tractable), exit
  at the close of the 30th bar.

Run:
    cd /opt/tradingbot && python _validate_phaseB_grind_replay.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Optional, Tuple

import pandas as pd

CANDLES_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")

# Mirror the strategy defaults — read as if the live module loaded them.
STRUCT_N = int(os.getenv("STRUCT_LEADS_N", "5"))
STRUCT_MIN_BREAK_PIPS = float(os.getenv("STRUCT_LEADS_MIN_BREAK_PIPS", "0.0"))
PIP_SIZE = 1.0  # GBPUSD on the IG TODAY epic: 1 raw point = 1 pip
WARMUP_BARS = 24  # gbpusd_structure_break uses similar warmup

# Forward-simulation parameters.
TP_PIPS = 12.0
SL_PIPS = 6.0
MFE_MAE_WINDOW = 10
MAX_FORWARD_BARS = 30

# Candidate thresholds to evaluate.
CANDIDATES = [3.0, 2.75, 2.5, 2.25, 2.0, 1.75, 1.5]

# Replay window — last N trading days from CANDLES_DIR (newest first).
WINDOW_DAYS = 5


def load_recent_days(n: int = WINDOW_DAYS) -> Tuple[pd.DataFrame, List[str]]:
    """Return (concat_df, dates_list)."""
    files = sorted([f for f in CANDLES_DIR.glob("*.csv") if f.is_file()])
    if not files:
        raise RuntimeError(f"No candle files under {CANDLES_DIR}")
    chosen = files[-n:]
    dfs = []
    dates = []
    for f in chosen:
        df = pd.read_csv(f)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        dfs.append(df)
        dates.append(f.stem)
    big = pd.concat(dfs, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return big, dates


def detect_break(bars: pd.DataFrame, i: int) -> Optional[Dict]:
    """Pure structural break detector mirroring gbpusd_structure_break._detect
    bars-replicate path. Returns dict {dir, break_pips, prior_swing,
    close_at_flip, entry_ts} or None.

    Inputs:
      bars: full df with columns timestamp/open/high/low/close
      i:    index of the candidate bar
    """
    if i < STRUCT_N + 1:
        return None
    if i < WARMUP_BARS:
        return None
    window = bars.iloc[i - STRUCT_N: i]  # the N bars BEFORE current
    prior_high = float(window["high"].max())
    prior_low = float(window["low"].min())
    cur = bars.iloc[i]
    cur_close = float(cur["close"])
    break_pad = STRUCT_MIN_BREAK_PIPS * PIP_SIZE
    # UP break
    if cur_close > (prior_high + break_pad):
        break_px = cur_close - prior_high
        return {
            "direction": "UP",
            "break_pips": break_px / PIP_SIZE,
            "prior_swing": prior_high,
            "close_at_flip": cur_close,
            "entry_ts": cur["timestamp"],
            "entry_idx": i,
        }
    # DOWN break
    if cur_close < (prior_low - break_pad):
        break_px = prior_low - cur_close
        return {
            "direction": "DOWN",
            "break_pips": break_px / PIP_SIZE,
            "prior_swing": prior_low,
            "close_at_flip": cur_close,
            "entry_ts": cur["timestamp"],
            "entry_idx": i,
        }
    return None


def simulate_forward(bars: pd.DataFrame, entry_idx: int, direction: str,
                     entry_px: float) -> Dict:
    """Walk forward up to MAX_FORWARD_BARS, return outcome dict."""
    is_long = (direction == "UP")
    tp = entry_px + (TP_PIPS * PIP_SIZE if is_long else -TP_PIPS * PIP_SIZE)
    sl = entry_px - (SL_PIPS * PIP_SIZE if is_long else -SL_PIPS * PIP_SIZE)
    mfe_pips = 0.0
    mae_pips = 0.0
    pip_at_1 = pip_at_2 = pip_at_5 = pip_at_10 = None
    outcome = "TIMEOUT"
    exit_idx = None
    exit_pips = 0.0
    for k in range(1, MAX_FORWARD_BARS + 1):
        idx = entry_idx + k
        if idx >= len(bars):
            break
        row = bars.iloc[idx]
        hi = float(row["high"]); lo = float(row["low"]); cl = float(row["close"])
        # MFE/MAE
        if is_long:
            bar_mfe = (hi - entry_px) / PIP_SIZE
            bar_mae = (lo - entry_px) / PIP_SIZE
        else:
            bar_mfe = (entry_px - lo) / PIP_SIZE
            bar_mae = (entry_px - hi) / PIP_SIZE
        if k <= MFE_MAE_WINDOW:
            if bar_mfe > mfe_pips:
                mfe_pips = bar_mfe
            if bar_mae < mae_pips:
                mae_pips = bar_mae
        # Mark close-pnl at +1/+2/+5/+10
        cl_pips = (cl - entry_px) / PIP_SIZE if is_long else (entry_px - cl) / PIP_SIZE
        if k == 1: pip_at_1 = cl_pips
        if k == 2: pip_at_2 = cl_pips
        if k == 5: pip_at_5 = cl_pips
        if k == 10: pip_at_10 = cl_pips
        # Exit checks: SL first (pessimistic — both touched same bar resolves to SL)
        if is_long:
            if lo <= sl:
                outcome = "SL"
                exit_idx = idx
                exit_pips = -SL_PIPS
                break
            if hi >= tp:
                outcome = "TP"
                exit_idx = idx
                exit_pips = TP_PIPS
                break
        else:
            if hi >= sl:
                outcome = "SL"
                exit_idx = idx
                exit_pips = -SL_PIPS
                break
            if lo <= tp:
                outcome = "TP"
                exit_idx = idx
                exit_pips = TP_PIPS
                break
    if outcome == "TIMEOUT" and exit_idx is None:
        # Exit at last reached bar's close
        last_idx = min(entry_idx + MAX_FORWARD_BARS, len(bars) - 1)
        if last_idx > entry_idx:
            row = bars.iloc[last_idx]
            cl = float(row["close"])
            exit_pips = (cl - entry_px) / PIP_SIZE if is_long else (entry_px - cl) / PIP_SIZE
            exit_idx = last_idx
    return {
        "outcome": outcome,
        "exit_pips": exit_pips,
        "mfe_pips": mfe_pips,
        "mae_pips": mae_pips,
        "pip_at_1": pip_at_1,
        "pip_at_2": pip_at_2,
        "pip_at_5": pip_at_5,
        "pip_at_10": pip_at_10,
    }


def percentile(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return s[k]


def main() -> int:
    bars, dates = load_recent_days(WINDOW_DAYS)
    print(f"[Phase-B replay] Loaded {len(bars)} 5M bars across {len(dates)} days:")
    print(f"  dates: {dates}")
    print(f"  span:  {bars.iloc[0]['timestamp']} → {bars.iloc[-1]['timestamp']}")
    print()

    # Pass 1: detect all candidate breaks (no DECISIVE_PIPS gate, just the
    # structural fresh-break check). Then we filter per-threshold later.
    all_breaks = []
    for i in range(WARMUP_BARS, len(bars)):
        b = detect_break(bars, i)
        if b is None:
            continue
        # In live the strategy has a session window (06-17 UTC) and a
        # 12-bar cooldown — model both lightly here so the replay tracks
        # what would actually have fired.
        ts = b["entry_ts"]
        hr = ts.hour
        if hr < 6 or hr >= 17:
            continue
        all_breaks.append(b)

    # Cooldown sweep — 12 bars (60min) between fires of the same direction.
    # The live cooldown is per-epic regardless of direction (60min).
    cooldown_filtered = []
    last_fire_idx: Optional[int] = None
    for b in all_breaks:
        if last_fire_idx is not None and (b["entry_idx"] - last_fire_idx) < 12:
            continue
        cooldown_filtered.append(b)
        last_fire_idx = b["entry_idx"]
    print(f"Detected {len(all_breaks)} raw fresh breaks within session window.")
    print(f"After 12-bar cooldown: {len(cooldown_filtered)} candidates.")
    print()

    # Simulate forward for each candidate once (same forward path regardless
    # of which threshold passes).
    enriched = []
    for b in cooldown_filtered:
        out = simulate_forward(bars, b["entry_idx"], b["direction"], b["close_at_flip"])
        enriched.append({**b, **out})

    # Special: find today's 08:55 GBPUSD entry (if it was a fresh break).
    target_ts_prefix = "2026-06-16 08:55"
    target = None
    for e in enriched:
        if str(e["entry_ts"]).startswith(target_ts_prefix):
            target = e
            break

    print("=== Per-threshold table ===")
    print(f"{'thr(p)':>7} | {'fires':>6} | {'L':>4} | {'S':>4} | "
          f"{'extras':>7} | {'avg_pnl_extras':>13} | {'win_rate_extras':>15} | "
          f"{'mfe_med_extras':>13} | {'mae_med_extras':>13}")
    print("-" * 110)
    baseline_set = None
    rows = []
    for thr in CANDIDATES:
        fires = [e for e in enriched if e["break_pips"] >= thr]
        if thr == 3.0:
            baseline_set = {e["entry_ts"] for e in fires}
            extras = []
        else:
            extras = [e for e in fires if e["entry_ts"] not in baseline_set]
        longs = sum(1 for e in fires if e["direction"] == "UP")
        shorts = len(fires) - longs
        if extras:
            avg_pnl = mean(e["exit_pips"] for e in extras)
            wins = sum(1 for e in extras if e["exit_pips"] > 0)
            win_rate = wins / len(extras)
            mfe_med = median(e["mfe_pips"] for e in extras)
            mae_med = median(e["mae_pips"] for e in extras)
        else:
            avg_pnl = float("nan")
            win_rate = float("nan")
            mfe_med = float("nan")
            mae_med = float("nan")
        rows.append({
            "thr": thr, "fires": len(fires), "L": longs, "S": shorts,
            "extras": len(extras), "avg_pnl_extras": avg_pnl,
            "win_rate_extras": win_rate,
            "mfe_med_extras": mfe_med, "mae_med_extras": mae_med,
            "extras_list": extras,
        })
        print(f"{thr:>7.2f} | {len(fires):>6} | {longs:>4} | {shorts:>4} | "
              f"{len(extras):>7} | {avg_pnl:>13.2f} | {win_rate:>15.2%} | "
              f"{mfe_med:>13.2f} | {mae_med:>13.2f}")
    print()

    # 08:55 entry outcome (independent of threshold).
    print("=== Today 08:55 GBPUSD entry simulated outcome ===")
    if target is None:
        print("  (no fresh structural break detected at 2026-06-16 08:55 — "
              "the morning leg may have fired earlier or the break was "
              "below 0p structural pad)")
    else:
        print(f"  ts: {target['entry_ts']}  dir={target['direction']}")
        print(f"  break_pips={target['break_pips']:.2f}  "
              f"close_at_flip={target['close_at_flip']:.2f}")
        print(f"  outcome={target['outcome']}  exit_pips={target['exit_pips']:.2f}")
        print(f"  MFE={target['mfe_pips']:.2f}p  MAE={target['mae_pips']:.2f}p")
        print(f"  pip@1={target['pip_at_1']}  @2={target['pip_at_2']}  "
              f"@5={target['pip_at_5']}  @10={target['pip_at_10']}")
        # Which thresholds would fire it?
        passing = [thr for thr in CANDIDATES if target["break_pips"] >= thr]
        print(f"  passes threshold(s): {passing}")
    print()

    # Recommendation logic.
    # Pick the deepest threshold whose extras are net-positive avg_pnl AND
    # win_rate >= 0.45 AND median MFE >= TP_PIPS * 0.5 (extras at least
    # touch the TP-side of the trade meaningfully).
    print("=== Recommendation ===")
    qualifying = [r for r in rows[1:] if r["extras"] > 0
                  and r["avg_pnl_extras"] == r["avg_pnl_extras"]  # not NaN
                  and r["avg_pnl_extras"] > 0
                  and r["win_rate_extras"] >= 0.45
                  and r["mfe_med_extras"] >= TP_PIPS * 0.5]
    if qualifying:
        best = qualifying[-1]  # deepest loosening that still qualifies
        print(f"  Recommended loosened default: {best['thr']:.2f}p")
        print(f"    extras={best['extras']} avg_pnl={best['avg_pnl_extras']:.2f}p "
              f"win_rate={best['win_rate_extras']:.2%} "
              f"mfe_med={best['mfe_med_extras']:.2f}p "
              f"mae_med={best['mae_med_extras']:.2f}p")
    else:
        # Conservative fallback per brief.
        print("  Data ambiguous — recommending conservative one-step loosening: 2.5p")
        print("  Reasoning: no threshold produced extras meeting the joint")
        print("  bar (avg_pnl>0 + win_rate>=45% + median MFE>=6p). 2.5p is")
        print("  a defensive single-step move; under STRUCTURE_BREAK_GRIND_ENABLED=0")
        print("  the original 3.0p hard-coded fallback is restored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
