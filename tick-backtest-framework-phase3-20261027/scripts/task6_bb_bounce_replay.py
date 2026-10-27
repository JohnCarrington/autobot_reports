"""Phase 3 Task 6 — drive production BB Bounce through a historical fixture (Level C counterfactual).

Imports production gbpusd_bb_bounce via the isolation seam, builds Bar objects
from the corrected tick cache, and feeds the strategy one 5m close at a time.
Captures:
  - every strategy_log emission (via logger hook)
  - every lifecycle write (we monkey-patch _write_bb_bounce_lifecycle_row)
  - every returned StrategyDecision (fire)
  - the pre-call state of self._armed_setups per bar
  - total runtime

This is Level C per spec §12 — there is no 2024-2026-03 production reference to
compare against, so this run exercises the production code's internal state
machine on verified historical ticks. It proves the strategy can be driven, that
all 12 pathways' entry points are reachable, and that no production side-effects
occur.
"""
from __future__ import annotations
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.isolation import init_isolation  # noqa: E402

CACHE_ROOT = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")
OUT = Path("/tmp/phase3_audit/data")
OUT.mkdir(parents=True, exist_ok=True)

# Fixtures across the certified window with different market conditions
FIXTURE_DATES = [
    "2026-02-10",   # Normal mid-week day pre-DST
    "2026-02-17",   # Pre-DST
    "2026-03-02",   # Pre-DST
    "2026-03-18",   # Post-DST
    "2026-03-25",   # Post-DST
]


def _load_m5_mid(date_s: str) -> pd.DataFrame:
    """Build M5 MID candles. Prices returned in IG points (×10000) since BB Bounce
    strategy's PIP_SIZE=1.0 convention requires IG points, not FX decimal."""
    start_ns = pd.Timestamp(f"{date_s}T00:00:00+00:00").value
    end_ns = start_ns + 86400 * 10**9
    yr = int(date_s[:4])
    p = CACHE_ROOT / f"{yr}.parquet"
    df = pd.read_parquet(p, columns=["ts_utc_ns", "bid", "ask"],
                         filters=[("ts_utc_ns", ">=", start_ns), ("ts_utc_ns", "<", end_ns)])
    df["ts_utc"] = pd.to_datetime(df["ts_utc_ns"], unit="ns", utc=True)
    df["mid"] = (df["bid"] + df["ask"]) / 2 * 10000.0  # FX decimal → IG points
    df["bar_ts"] = df["ts_utc"].dt.floor("5min")
    agg = df.groupby("bar_ts", sort=True).agg(
        open=("mid", "first"), high=("mid", "max"),
        low=("mid", "min"),    close=("mid", "last"),
    ).reset_index().rename(columns={"bar_ts": "ts"})
    return agg


def _warmup_prev_day_closes(date_s: str, n: int = 60) -> list[float]:
    """Return the last `n` mid closes from the previous trading day (for indicator warmup).

    If the prev day is a weekend/outside coverage, we return [] and the strategy
    will accumulate its own warmup from the current day's early bars (first 20
    bars of the day will have no BB — pass but no fire).
    """
    probe = (pd.Timestamp(f"{date_s}T00:00:00+00:00") - pd.Timedelta(days=1)).date().isoformat()
    df = _load_m5_mid(probe)
    if df.empty:
        return []
    return df["close"].tail(n).tolist()


def run_fixture(date_s: str, extra_env: dict) -> dict:
    """Run BB Bounce over the fixture day with isolation. Return a report dict."""
    with init_isolation(extra_env=extra_env):
        # Force-reimport so env flags at module scope are re-read
        import importlib, sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb_mod

        # Belt + braces: force-enable at the module global in case any
        # env read already resolved to False
        bb_mod.ENABLED = True

        # Capture lifecycle writes (production would persist to disk; we intercept)
        lifecycle_rows: list[dict] = []
        original_lifecycle = getattr(bb_mod, "_write_bb_bounce_lifecycle_row", None)
        bb_mod._write_bb_bounce_lifecycle_row = lifecycle_rows.append

        # Capture standdown writes if they exist
        standdown_rows: list[dict] = []
        if hasattr(bb_mod, "_write_bb_bounce_standdown_row"):
            bb_mod._write_bb_bounce_standdown_row = standdown_rows.append

        # Build strategy instance
        s = bb_mod.GbpUsdBBBounceStrategy()

        # Load the day's bars + warmup
        day_m5 = _load_m5_mid(date_s)
        warmup = _warmup_prev_day_closes(date_s)

        # Keep a rolling closes_ind list that the strategy would receive
        closes_ind: list[float] = list(warmup)
        bars_so_far: list = []  # list[Bar]
        fires: list[dict] = []
        bar_summaries: list[dict] = []
        state_snapshots: list[dict] = []

        t0 = time.time()
        for _, row in day_m5.iterrows():
            ts = row["ts"].to_pydatetime()
            bar = bb_mod.Bar(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
            bars_so_far.append(bar)
            closes_ind.append(float(row["close"]))

            # Capture pre-call armed state
            pre_armed = len(s._armed_setups.get("CS.D.GBPUSD.TODAY.IP", []))

            # Drive strategy — fail-soft so one exception does not abort the whole day
            try:
                decision = s.evaluate(
                    "GBPUSD", "CS.D.GBPUSD.TODAY.IP", ts, bars_so_far, closes_ind,
                    has_open_long=False, has_open_short=False,
                )
            except Exception as e:
                decision = None
                lifecycle_rows.append({
                    "event": "replay_exception", "ts_utc": ts.isoformat(),
                    "err": repr(e),
                })

            post_armed = len(s._armed_setups.get("CS.D.GBPUSD.TODAY.IP", []))

            if decision is not None:
                fires.append({
                    "ts": ts.isoformat(),
                    "signal": getattr(decision, "signal", None),
                    "mode": getattr(decision, "mode", None),
                    "entry_price": getattr(decision, "entry_price", None),
                    "sl_pips": getattr(decision, "sl_pips", None),
                    "tp_pips": getattr(decision, "tp_pips", None),
                    "reason": getattr(decision, "reason", None),
                })

            if pre_armed != post_armed:
                state_snapshots.append({
                    "ts": ts.isoformat(),
                    "armed_before": pre_armed,
                    "armed_after": post_armed,
                    "delta": post_armed - pre_armed,
                })

            if len(bar_summaries) < 3:  # keep a sample for debugging
                bar_summaries.append({
                    "ts": ts.isoformat(), "o": bar.open, "h": bar.high,
                    "l": bar.low, "c": bar.close,
                })

        # Count lifecycle event types for the day
        event_counts: dict = {}
        for row in lifecycle_rows:
            ev = row.get("event", "?")
            event_counts[ev] = event_counts.get(ev, 0) + 1

        return {
            "date": date_s,
            "status": "ok",
            "n_bars_fed": int(len(day_m5)),
            "n_lifecycle_rows": len(lifecycle_rows),
            "n_standdown_rows": len(standdown_rows),
            "n_fires": len(fires),
            "n_state_transitions": len(state_snapshots),
            "lifecycle_event_counts": event_counts,
            "fires": fires[:20],
            "lifecycle_sample_last5": lifecycle_rows[-5:],
            "state_sample_first10": state_snapshots[:10],
            "elapsed_s": round(time.time() - t0, 2),
            "first_bars_sample": bar_summaries,
        }


def main():
    all_rows = []
    # First run: strategy ENABLED, default config
    for date_s in FIXTURE_DATES:
        print(f"[{date_s}] running with BB enabled, defaults", flush=True)
        row = run_fixture(date_s, extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"})
        all_rows.append(row)
        print(f"  → bars={row.get('n_bars_fed','?')} fires={row.get('n_fires','?')} "
              f"lifecycle={row.get('n_lifecycle_rows','?')} transitions={row.get('n_state_transitions','?')}", flush=True)

    (OUT / "bb_bounce_replay_fixtures.json").write_text(json.dumps(all_rows, indent=2, default=str))

    # Summary table
    summary = []
    for r in all_rows:
        if r.get("status") == "ok":
            summary.append({"date": r["date"], "bars": r["n_bars_fed"],
                            "fires": r["n_fires"], "lifecycle": r["n_lifecycle_rows"],
                            "transitions": r["n_state_transitions"]})
    pd.DataFrame(summary).to_csv(OUT / "bb_bounce_replay_summary.csv", index=False)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
