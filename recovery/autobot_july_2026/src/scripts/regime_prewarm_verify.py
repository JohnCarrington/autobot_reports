"""Verify that regime detector prewarm fixes the warmup-during-startup bug.

Three checks:
  (1) Unit:    after prewarm_buffer("GBPUSD"), classify_regime returns a
               REAL classification (not warmup-default NEUTRAL/LOW with
               debug.reason='warmup') given an empty incoming-bar list.
  (2) Replay:  simulate the bot restarting at 04:35 UTC today, then run
               classify_regime at 06:10 / 06:55 / 07:05 UTC fire times
               using only the small bar slice the strategy actually
               passes (60 bars). Verify the buffer-augmented detector
               returns a real classification at every fire time, and
               compare against what production logged today.
  (3) Counter: with reset_buffer() to simulate a *cold* restart with
               no archive, classify_regime should fall back to warmup
               (proving the gate isn't accidentally always-on).

Read-only — does not mutate any prod state. Writes to /tmp.
"""
from __future__ import annotations

import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

ROOT = Path("/opt/tradingbot")
sys.path.insert(0, str(ROOT))

# Route logs to /tmp — never touch prod state.
os.environ["GBPUSD_REGIME_LOG_PATH"] = "/tmp/regime_prewarm_verify.jsonl"

import gbpusd_regime_detector as rd  # noqa: E402

# Quiet noisy chatter — keep INFO so we see the prewarm line.
for _h in list(rd.logger.handlers):
    rd.logger.removeHandler(_h)
rd.logger.propagate = False
rd.logger.setLevel(logging.INFO)
_h = logging.StreamHandler()
_h.setFormatter(logging.Formatter("%(message)s"))
rd.logger.addHandler(_h)

CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"


def _load_csv(d: str) -> List[rd.Bar]:
    path = CANDLE_DIR / f"{d}.csv"
    if not path.exists():
        return []
    out: List[rd.Bar] = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = datetime.fromisoformat(r["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append(rd.Bar(
                timestamp=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
            ))
    return out


def _line(s=""):
    print(s)


# ─── (1) Unit ─────────────────────────────────────────────────────────────
def check_1_unit() -> bool:
    _line("=" * 78)
    _line("(1) UNIT — prewarm + classify with empty incoming list")
    _line("=" * 78)
    rd.reset_buffer("GBPUSD")
    n = rd.prewarm_buffer("GBPUSD")
    _line(f"buffer size after prewarm: {n}  (MIN_BARS={rd.MIN_BARS})")
    if n < rd.MIN_BARS:
        _line("FAIL: archive did not provide enough bars")
        return False

    # Pass empty list — classify should still return a real verdict
    # because the buffer holds prewarmed history.
    res = rd.classify_regime([], symbol="GBPUSD", log=False)
    is_warmup = (res.debug or {}).get("reason") == "warmup"
    _line(f"classify(empty) → regime={res.regime} conf={res.confidence} "
          f"warmup={is_warmup}")
    _line(f"  signals: {res.signal_breakdown}")
    if is_warmup:
        _line("FAIL: still in warmup despite prewarm")
        return False
    _line("PASS: real classification, no warmup default")
    return True


# ─── (2) Replay (simulated 04:35 UTC restart) ─────────────────────────────
def check_2_replay() -> bool:
    _line("\n" + "=" * 78)
    _line("(2) REPLAY — simulate 04:35 UTC restart; classify at fire times")
    _line("=" * 78)

    # Reset and prewarm — this represents the bot restarting at any
    # time today. prewarm reads from disk, so the post-restart buffer
    # is the same content regardless of restart wallclock.
    rd.reset_buffer("GBPUSD")
    n = rd.prewarm_buffer("GBPUSD")
    _line(f"buffer size post-prewarm: {n}")

    # Build today's bars and replay them in order. At each strategy-
    # call timestamp we pass the LAST-60-BAR slice (matching what
    # autobot's BB_BOUNCE wrapper actually passes — 60-bar cap).
    today_bars = _load_csv("2026-05-04")
    if not today_bars:
        _line("FAIL: 2026-05-04 candle file missing")
        return False

    fire_targets = {
        "06:10": "BB_BOUNCE_S SHORT (profitable)",
        "06:55": "BB_BOUNCE_L LONG (SL'd, the suspect)",
        "07:05": "BRIEFING_EXECUTION (exempt; classifier shown for context)",
    }

    # Production log readback for comparison.
    prod_log = {}
    p = Path("/opt/tradingbot/logs/gbpusd_regime.jsonl")
    if p.exists():
        import json as _j
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = _j.loads(line)
                    ts = rec.get("ts") or ""
                    if ts.startswith("2026-05-04"):
                        hhmm = ts[11:16]
                        # Production logs use bar-open time; our fire
                        # wallclock is bar-close (open + 5m). Map
                        # 06:05 → 06:10, etc.
                        try:
                            h, m = ts[11:13], ts[14:16]
                            close_min = (int(h) * 60 + int(m) + 5)
                            fire_hhmm = f"{(close_min // 60) % 24:02d}:{close_min % 60:02d}"
                            prod_log.setdefault(fire_hhmm, rec)
                        except ValueError:
                            pass
                except Exception:
                    continue

    # Walk through today's bars; at each fire wallclock, classify with
    # the 60-bar tail slice (autobot's current dispatch behavior).
    fire_results = {}
    for i, bar in enumerate(today_bars):
        # Bar at ts T closes at T+5m, fires at T+5m wallclock.
        close_dt = bar.timestamp.replace(second=0, microsecond=0)
        # Compute fire wallclock = close time = bar_ts + 5m.
        close_min = (close_dt.hour * 60 + close_dt.minute + 5)
        fire_hhmm = f"{(close_min // 60) % 24:02d}:{close_min % 60:02d}"
        if fire_hhmm not in fire_targets or fire_hhmm in fire_results:
            continue

        # Strategy passes last 60 bars (BB_BOUNCE / BB_REV_PAT cap).
        history_60 = today_bars[max(0, i - 59) : i + 1]
        res = rd.classify_regime(history_60, symbol="GBPUSD", log=False)
        is_warmup = (res.debug or {}).get("reason") == "warmup"
        fire_results[fire_hhmm] = (res, is_warmup, len(history_60))

    if not fire_results:
        _line("FAIL: no fire windows matched in today's bars")
        return False

    _line(f"\n{'fire':<6}{'desc':<48}{'incoming':>10}{'effective':>11}"
          f"{'regime':>10}{'conf':>6} warmup")
    all_ok = True
    for hhmm, desc in fire_targets.items():
        if hhmm not in fire_results:
            _line(f"  {hhmm:<6}{desc:<48}{'(no bar)':>10}")
            all_ok = False
            continue
        res, is_warmup, n_in = fire_results[hhmm]
        # The classify call above already merged into the global buffer
        # — `effective` is buffer_size which has accumulated all replay
        # bars up to this fire.
        n_eff = rd.buffer_size("GBPUSD")
        _line(f"  {hhmm:<6}{desc:<48}{n_in:>10}{n_eff:>11}"
              f"{res.regime:>10}{res.confidence:>6}  {is_warmup}")
        if is_warmup:
            all_ok = False

    _line("\nProduction-log comparison (today, before this fix):")
    _line(f"  {'fire':<6}{'prod_regime':>14}{'prod_conf':>12}{'prod_reason':>16}")
    for hhmm in fire_targets:
        rec = prod_log.get(hhmm)
        if rec is None:
            _line(f"  {hhmm:<6}{'(no log)':>14}")
            continue
        reason = (rec.get("debug") or {}).get("reason", "")
        _line(f"  {hhmm:<6}{rec.get('regime',''):>14}{rec.get('confidence',''):>12}"
              f"{str(reason):>16}")

    # 06:55 — what the classification SHOULD HAVE BEEN.
    _line("\n[06:55 LONG — what classification SHOULD have been at fire]")
    res_0655, is_w_0655, _ = fire_results.get("06:55", (None, True, 0))
    if res_0655 is not None and not is_w_0655:
        _line(f"  regime    : {res_0655.regime}")
        _line(f"  confidence: {res_0655.confidence}")
        _line(f"  signals   : {res_0655.signal_breakdown}")
        _line(f"  override  : {(res_0655.debug or {}).get('override_fired')}")
        if res_0655.regime == "TRENDING":
            _line("  GATE WOULD HAVE BLOCKED the LONG fire ✓")
        else:
            _line(f"  GATE WOULD NOT HAVE BLOCKED ({res_0655.regime} ≠ TRENDING)")
            _line("  Note: detector classifies magnitude not direction —")
            _line("  even with warmup fixed, a non-impulsive grind can read")
            _line("  RANGE/NEUTRAL. The fix removes the warmup blind spot;")
            _line("  it does NOT add a directional filter.")

    if all_ok:
        _line("\nPASS: every fire window classified without warmup")
    else:
        _line("\nFAIL: some fire windows still in warmup")
    return all_ok


# ─── (3) Counter — cold-start, no archive ────────────────────────────────
def check_3_counter() -> bool:
    _line("\n" + "=" * 78)
    _line("(3) COUNTER — point archive at empty dir; warmup must still kick in")
    _line("=" * 78)
    rd.reset_buffer("GBPUSD")
    saved = rd.CANDLE_ARCHIVE_ROOT
    try:
        rd.CANDLE_ARCHIVE_ROOT = Path("/tmp/regime_archive_empty")
        rd.CANDLE_ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
        # No GBPUSD subdir → preload returns 0 bars.
        n = rd.prewarm_buffer("GBPUSD")
        _line(f"buffer size after empty-dir prewarm: {n}")
        res = rd.classify_regime([], symbol="GBPUSD", log=False)
        is_warmup = (res.debug or {}).get("reason") == "warmup"
        _line(f"classify(empty) → regime={res.regime} warmup={is_warmup}")
        if not is_warmup or n != 0:
            _line("FAIL: cold-start fallback didn't trigger")
            return False
        _line("PASS: cold-start correctly falls back to live warmup")
    finally:
        rd.CANDLE_ARCHIVE_ROOT = saved
        rd.reset_buffer("GBPUSD")
    return True


def main() -> int:
    rc = 0
    if not check_1_unit():    rc = 1
    if not check_2_replay():  rc = 1
    if not check_3_counter(): rc = 1
    print()
    print("=" * 78)
    print("OVERALL:", "PASS" if rc == 0 else "FAIL")
    print("=" * 78)
    return rc


if __name__ == "__main__":
    sys.exit(main())
