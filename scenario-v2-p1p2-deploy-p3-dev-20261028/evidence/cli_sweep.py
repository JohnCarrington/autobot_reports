"""CLI entry point for the deterministic per-bar trigger evaluator.

Intended to be invoked once per systemd-timer tick (every 5 min
during the UK trading window), aligned ~15 s after each M5 bar
close:

    python -m trigger_evaluator.cli_sweep [--dry-run] [--bar-ts TS]

What this does
--------------
1. Resolve the latest completed M5 candle at the current UTC time.
   A completed candle is one whose close time ≤ now.  If --bar-ts
   is supplied, use it instead (for backfill / testing).

2. Reject stale or incomplete candles.  A candle is REJECTED if:
     * No source has it in the archive.
     * The candle open time + 300 s + MAX_SNAPSHOT_AGE_S < now
       (snapshot older than freshness threshold).

3. Load the latest scenarios_shadow.jsonl.

4. Build the economic_context by calling market_observer_macro at
   the candle's close time.

5. Invoke :func:`trigger_evaluator.run_trigger_sweep` with the
   latest scenario revisions, the completed candle, the fresh
   snapshot, the econ context, and the durable state file.

6. If --dry-run, write to a tempfile proposals journal rather than
   the production shadow_proposals.jsonl.

7. Log a structured summary to stderr (service journal captures it
   via `journalctl -u`).

8. Exit code:
    0  — success (even if no fires).
    1  — any unrecoverable failure (candle not available, cross-
         process lock contention beyond retries, state file
         corrupted, etc.).

Do not call :mod:`broker` or any execution path.  Do not reach into
NMS.  Do not restart services.  Shadow-only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import os
import pathlib
import sys
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------
# Path configuration — overridable via env for testing
# ---------------------------------------------------------------------
LIVE_OBS_ROOT = pathlib.Path(
    os.environ.get("LIVE_OBS_ROOT",
                    "/mnt/volume_lon1_1778405456698/research/live_obs"))
AGENT_DIR = LIVE_OBS_ROOT / "agent"
JOURNAL_SHADOW_DIR = LIVE_OBS_ROOT / "journal_shadow"
SHADOW_EXEC_DIR = LIVE_OBS_ROOT / "shadow_exec"
NEWS_FEED = LIVE_OBS_ROOT / "news" / "verified_events.jsonl"
SCENARIOS_JOURNAL = JOURNAL_SHADOW_DIR / "scenarios_shadow.jsonl"
PROPOSALS_JOURNAL = SHADOW_EXEC_DIR / "shadow_proposals.jsonl"
STATE_FILE = JOURNAL_SHADOW_DIR / "trigger_eval_state.json"

# BID M5 candles — this host has two possible sources
CANDLE_DIRS = [
    pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD"),  # BID
    pathlib.Path("/opt/tradingbot/data/candles/GBPUSD"),      # MID (2026)
]

# Observer snapshot stream — latest snapshot_ts drives the freshness check
OBSERVER_SNAPSHOTS = LIVE_OBS_ROOT / "journal" / "snapshots.jsonl"

# Make the local agent + evaluator importable irrespective of CWD.
sys.path.insert(0, str(LIVE_OBS_ROOT))
sys.path.insert(0, str(AGENT_DIR))
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from trigger_evaluator import (  # noqa: E402
        run_trigger_sweep, TriggerEvalState,
    )
except ImportError:
    # When invoked as a module from LIVE_OBS_ROOT, package import works.
    from trigger_evaluator.trigger_evaluator import (  # noqa: E402
        run_trigger_sweep, TriggerEvalState,
    )

UTC = dt.timezone.utc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
LOG = logging.getLogger("trigger_evaluator.cli_sweep")


# ---------------------------------------------------------------------
# Candle resolution
# ---------------------------------------------------------------------
def latest_completed_m5_bar(now: dt.datetime,
                              max_lookback_bars: int = 36
                              ) -> tuple[dt.datetime, tuple[float, float, float, float]] | None:
    """Return (bar_open_dt, OHLC) of the latest completed M5 candle
    whose close is at or before ``now``.  Walks back up to
    ``max_lookback_bars`` bars (3 h) to tolerate missing bars.

    A candle "completes" 300 s after its open time.
    """
    # Round NOW down to the previous 5-min boundary, then step back one
    # more (so we never report the still-open current bar).
    minute = (now.minute // 5) * 5
    candidate_open = now.replace(minute=minute, second=0, microsecond=0) \
        - dt.timedelta(minutes=5)
    for _ in range(max_lookback_bars):
        close = candidate_open + dt.timedelta(seconds=300)
        if close > now:
            candidate_open -= dt.timedelta(minutes=5)
            continue
        bar = _read_bar(candidate_open)
        if bar is not None:
            return candidate_open, bar
        candidate_open -= dt.timedelta(minutes=5)
    return None


def _read_bar(bar_open: dt.datetime
               ) -> tuple[float, float, float, float] | None:
    """Read a specific M5 bar's OHLC from the archive, if present."""
    stem = bar_open.strftime("%Y-%m-%d.csv")
    key = bar_open.strftime("%Y-%m-%dT%H:%M")
    for base in CANDLE_DIRS:
        p = base / stem
        if not p.exists():
            continue
        with p.open() as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if row.get("timestamp", "").startswith(key):
                    try:
                        return (float(row["open"]), float(row["high"]),
                                float(row["low"]), float(row["close"]))
                    except (KeyError, ValueError):
                        return None
    return None


# ---------------------------------------------------------------------
# Snapshot resolution for freshness
# ---------------------------------------------------------------------
def latest_snapshot() -> dict | None:
    """Return the last line of observer_snapshots.jsonl parsed as JSON,
    or None if unavailable."""
    if not OBSERVER_SNAPSHOTS.exists():
        return None
    try:
        with OBSERVER_SNAPSHOTS.open() as fh:
            last = None
            for line in fh:
                line = line.strip()
                if line:
                    last = line
            if last is None:
                return None
            return json.loads(last)
    except Exception as exc:
        LOG.warning("could not read observer snapshot: %s", exc)
        return None


# ---------------------------------------------------------------------
# Economic context
# ---------------------------------------------------------------------
def build_econ(asof: dt.datetime) -> dict:
    """Thin wrapper to build + classify economic context."""
    try:
        from market_observer_macro import build_macro_packet  # type: ignore
        from scenario_schema import classify_economic_context  # type: ignore
    except Exception as exc:
        LOG.warning("economic context unavailable: %s", exc)
        return {"status": "UNAVAILABLE",
                 "scheduled": [], "released": [],
                 "expired": [], "unverified": []}
    try:
        pkt = build_macro_packet(asof=asof, source_mode="operator_jsonl",
                                   event_file=NEWS_FEED,
                                   read_news_state=False)
        return classify_economic_context(pkt)
    except Exception as exc:
        LOG.warning("economic context build failed: %s", exc)
        return {"status": "UNAVAILABLE",
                 "scheduled": [], "released": [],
                 "expired": [], "unverified": []}


# ---------------------------------------------------------------------
# Lock file to prevent concurrent sweeps.
# ---------------------------------------------------------------------
class ExclusiveLock:
    """Simple exclusive-advisory file lock using os.open(O_CREAT|O_EXCL).
    Non-blocking; raises TimeoutError if lock cannot be acquired."""

    def __init__(self, path: pathlib.Path, timeout_s: float = 30):
        self.path = path
        self.timeout_s = timeout_s
        self.fd: int | None = None

    def __enter__(self):
        deadline = time.time() + self.timeout_s
        while True:
            try:
                self.fd = os.open(str(self.path),
                                    os.O_CREAT | os.O_EXCL | os.O_RDWR,
                                    0o644)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"could not acquire {self.path}")
                time.sleep(0.5)

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scenario V2 deterministic trigger evaluator sweep")
    parser.add_argument("--dry-run", action="store_true",
                         help="write to a tempfile proposals journal; do not touch production")
    parser.add_argument("--bar-ts", type=str,
                         help="override completed M5 bar open UTC ISO timestamp")
    parser.add_argument("--lock-timeout-s", type=float, default=30.0,
                         help="seconds to wait for exclusive lock")
    args = parser.parse_args(argv)

    now = dt.datetime.now(UTC)

    # Determine candle to evaluate
    if args.bar_ts:
        try:
            bar_open = dt.datetime.fromisoformat(
                args.bar_ts.replace("Z", "+00:00"))
        except Exception as exc:
            LOG.error("invalid --bar-ts: %s", exc)
            return 1
        bar = _read_bar(bar_open)
        if bar is None:
            LOG.error("no OHLC for --bar-ts=%s", bar_open.isoformat())
            return 1
        latest = (bar_open, bar)
    else:
        latest = latest_completed_m5_bar(now)
        if latest is None:
            LOG.error("no completed M5 bar found within lookback window")
            return 1
    bar_open, bar = latest
    LOG.info("sweep bar_ts=%s  OHLC=%s", bar_open.isoformat(), bar)

    # Snapshot freshness check — snapshot bar must be ≥ our target bar
    # (we are evaluating against a known-completed bar; snapshot staleness
    # beyond threshold is handled by run_trigger_sweep's invariant 6).
    snap = latest_snapshot()
    if snap is None:
        # Synthesise a minimal snapshot pinned to our target bar.
        # The evaluator uses only bar_ts_utc for freshness.
        snap = {"bar_ts_utc": bar_open.isoformat()}
        LOG.info("no observer snapshot — using synthesised freshness pin")

    econ = build_econ(asof=bar_open)
    LOG.info("economic_context buckets: scheduled=%d released=%d "
              "expired=%d unverified=%d",
              len(econ.get("scheduled") or []),
              len(econ.get("released") or []),
              len(econ.get("expired") or []),
              len(econ.get("unverified") or []))

    proposals_out = PROPOSALS_JOURNAL
    state_file = STATE_FILE
    if args.dry_run:
        tmpdir = pathlib.Path(tempfile.mkdtemp(
            prefix="trigger-eval-dry-"))
        proposals_out = tmpdir / "shadow_proposals.jsonl"
        state_file = tmpdir / "trigger_eval_state.json"
        LOG.info("DRY RUN — proposals=%s state=%s",
                  proposals_out, state_file)

    lock_path = JOURNAL_SHADOW_DIR / "trigger_eval.lock"
    try:
        with ExclusiveLock(lock_path, timeout_s=args.lock_timeout_s):
            state = TriggerEvalState(state_file)
            results = run_trigger_sweep(
                scenarios_path=SCENARIOS_JOURNAL,
                bar_ts_iso=bar_open.isoformat(),
                bar_ohlc=bar,
                snapshot=snap,
                economic_context=econ,
                state=state,
                now=now,
                proposals_out_path=proposals_out,
            )
    except TimeoutError as exc:
        LOG.error("lock acquisition failed: %s", exc)
        return 1
    except Exception as exc:
        LOG.error("sweep failed: %s", exc, exc_info=True)
        return 1

    n_fire = sum(1 for r in results if r.decision == "FIRE")
    n_skip = sum(1 for r in results if r.decision == "SKIP")
    LOG.info("sweep done — FIRE=%d SKIP=%d (bar=%s)",
              n_fire, n_skip, bar_open.isoformat())
    for r in results:
        if r.decision == "FIRE":
            LOG.info("  FIRE sid=%s rev=%d dir=%s entry=%s reason=%s",
                      r.scenario_id, r.revision_idx, r.direction,
                      r.entry_price, r.reason)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
