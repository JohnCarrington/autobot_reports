"""Phase 3b Stage 2 — diagnose the 40 replay exceptions.

Re-runs the Phase 3 5-day fixture with FULL stack-trace capture per exception.
Groups by root-cause (function/line/class). Reports a decision for each:
  FIX_STUB — stub signature wrong; patch isolation.py
  FIX_SOURCE_SIGNATURE — production call signature changed; update adapter
  LEGITIMATE_FAIL_OPEN — production error path; silence after confirmation
  UNEXPLAINED — flag for operator

Writes:
  phase3_exception_trace.json  — every exception with full trace
  phase3_exception_root_causes.json  — grouped summary
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.isolation import init_isolation  # noqa: E402

CACHE_ROOT = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")
OUT = Path("/tmp/phase3b_audit/data")
OUT.mkdir(parents=True, exist_ok=True)

FIXTURE_DATES = ["2026-02-10", "2026-02-17", "2026-03-02", "2026-03-18", "2026-03-25"]


def _load_m5(date_s: str) -> pd.DataFrame:
    start_ns = pd.Timestamp(f"{date_s}T00:00:00+00:00").value
    end_ns = start_ns + 86400 * 10**9
    yr = int(date_s[:4])
    df = pd.read_parquet(CACHE_ROOT / f"{yr}.parquet",
                         columns=["ts_utc_ns", "bid", "ask"],
                         filters=[("ts_utc_ns", ">=", start_ns), ("ts_utc_ns", "<", end_ns)])
    df["ts_utc"] = pd.to_datetime(df["ts_utc_ns"], unit="ns", utc=True)
    df["mid"] = (df["bid"] + df["ask"]) / 2 * 10000.0  # FX decimal → IG points
    df["bar_ts"] = df["ts_utc"].dt.floor("5min")
    return df.groupby("bar_ts", sort=True).agg(
        open=("mid", "first"), high=("mid", "max"),
        low=("mid", "min"),    close=("mid", "last"),
    ).reset_index().rename(columns={"bar_ts": "ts"})


def _run_day(date_s: str) -> list[dict]:
    exceptions: list[dict] = []
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        bb._write_bb_bounce_lifecycle_row = lambda row: None  # silence benign writes
        if hasattr(bb, "_write_bb_bounce_standdown_row"):
            bb._write_bb_bounce_standdown_row = lambda row: None

        m5 = _load_m5(date_s)
        bars_so_far: list = []
        closes_ind: list[float] = []
        s = bb.GbpUsdBBBounceStrategy()

        for _, row in m5.iterrows():
            ts = row["ts"].to_pydatetime()
            bar = bb.Bar(ts, float(row["open"]), float(row["high"]),
                         float(row["low"]), float(row["close"]))
            bars_so_far.append(bar)
            closes_ind.append(float(row["close"]))
            try:
                s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", ts, bars_so_far, closes_ind,
                           False, False)
            except Exception as e:
                tb = traceback.format_exc()
                # Extract the deepest production frame
                stk = traceback.extract_tb(e.__traceback__)
                prod_frame = None
                for f in reversed(stk):
                    if "/opt/tradingbot" in f.filename or "gbpusd_bb_bounce" in f.filename:
                        prod_frame = f
                        break
                if prod_frame is None and stk:
                    prod_frame = stk[-1]
                exceptions.append({
                    "date": date_s,
                    "bar_ts": ts.isoformat(),
                    "exc_type": type(e).__name__,
                    "err": str(e),
                    "prod_filename": prod_frame.filename if prod_frame else None,
                    "prod_lineno": prod_frame.lineno if prod_frame else None,
                    "prod_name": prod_frame.name if prod_frame else None,
                    "prod_line": prod_frame.line if prod_frame else None,
                    "traceback_tail": tb.splitlines()[-10:],
                })
    return exceptions


def main():
    all_exc: list[dict] = []
    for d in FIXTURE_DATES:
        print(f"[{d}] diagnosing...", flush=True)
        exc = _run_day(d)
        print(f"  → {len(exc)} exceptions", flush=True)
        all_exc.extend(exc)

    (OUT / "phase3_exception_trace.json").write_text(json.dumps(all_exc, indent=2))

    # Group by (prod_filename, prod_lineno, prod_name) + exception type + error message pattern
    groups: dict = {}
    for e in all_exc:
        key = (e["prod_filename"], e["prod_lineno"], e["prod_name"], e["exc_type"], e["err"][:120])
        groups.setdefault(key, []).append(e)
    root_causes = []
    for (fn, lineno, name, exc_type, err), examples in groups.items():
        root_causes.append({
            "prod_filename": fn,
            "prod_lineno": lineno,
            "prod_name": name,
            "exc_type": exc_type,
            "err_prefix": err,
            "count": len(examples),
            "example_bars": [e["bar_ts"] for e in examples[:5]],
            "example_line": examples[0]["prod_line"],
            "example_traceback_tail": examples[0]["traceback_tail"],
        })
    root_causes.sort(key=lambda r: r["count"], reverse=True)
    (OUT / "phase3_exception_root_causes.json").write_text(json.dumps(root_causes, indent=2))

    print(f"\nTotal exceptions: {len(all_exc)}, unique root causes: {len(root_causes)}")
    for rc in root_causes:
        print(f"  {rc['count']:4d}× {rc['prod_filename']}:{rc['prod_lineno']} {rc['prod_name']} "
              f"[{rc['exc_type']}] {rc['err_prefix'][:80]}")


if __name__ == "__main__":
    main()
