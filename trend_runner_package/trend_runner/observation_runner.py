"""Observation-mode entry point.

Consumes the AutoBot recorder tail file, aggregates M5 bars locally,
and runs the exact same TrendStrategy used by offline replay. Never
opens an IG session or streaming connection. Simulated trades are
journaled to the SIM namespace; broker-adapter execution is only
performed when TREND_EXECUTION_ENABLED=1 AND we have a broker adapter
wired (see :mod:`.execution`).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .candle_source import CandleArchive
from .config import TrendRunnerConfig, load_config
from .ledger import Ledger, Namespace
from .process_lock import LockHeldError, ProcessLock
from .recorder_source import M5Aggregator, RecorderTail
from .replay import ArchivePivotCache
from .strategy import TrendStrategy
from .telegram import AlertKind, TelegramOutbox, TelegramSender


UTC = timezone.utc

_running = True


def _handle_signal(signum, frame):
    global _running
    _running = False


class ObservationRunner:
    def __init__(self, config: TrendRunnerConfig, archive: CandleArchive):
        self.config = config
        self.archive = archive
        self.pivots = ArchivePivotCache(archive)
        self.ledger = Ledger(config.ledger_path)
        self.outbox = TelegramOutbox(config.outbox_path)
        self.telegram = TelegramSender(self.outbox, transport=None)
        self.strategy = TrendStrategy(
            pivot_getter=self.pivots.get,
            ledger=self.ledger,
            space=Namespace.SIM,
            stake_gbp_per_pip=config.stake_gbp_per_pip,
            min_broker_distance_pips=config.min_broker_distance_pips,
        )
        self._agg = M5Aggregator()
        self._prev_bar = None
        self._pending_next_open = False

    def run(self) -> None:
        with RecorderTail(self.config.recorder_path, epic=self.config.epic) as tail:
            for tick in tail.iter_ticks():
                if not _running:
                    break
                bar = self._agg.push(tick)
                if bar is None:
                    continue
                decision = self.strategy.on_m5_close(bar)
                if decision.exit is not None:
                    self.outbox.enqueue(AlertKind.SIM_CLOSE,
                                        f"{decision.exit.reason.value} @ {decision.exit.exit_price:.2f}")
                # Fill any pending entry using this bar's *open* -- observation only,
                # since we don't have a look-ahead of the *next* bar.
                if self._pending_next_open:
                    filled = self.strategy.on_next_bar_open(bar)
                    if filled and filled.accepted:
                        self.outbox.enqueue(AlertKind.SIM_OPEN,
                                            f"{filled.candidate.direction.value} @ {filled.entry_price:.2f}"
                                            f" stop={filled.stop_price:.2f}")
                    self._pending_next_open = False
                if self.strategy.entry_engine.state.pending is not None:
                    self._pending_next_open = True
                self.telegram.flush()
                if self._agg.is_stale():
                    self.strategy.entry_engine.state.pending = None
        self.outbox.enqueue(AlertKind.SHUTDOWN, "observation runner stopped")
        self.telegram.flush()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Trend Runner observation mode")
    p.add_argument("--archive-root", action="append", required=True,
                   help="Local candle archive root(s), used for prior-day pivots")
    args = p.parse_args(argv)
    config = load_config()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    archive = CandleArchive(args.archive_root, symbol="GBPUSD")
    try:
        with ProcessLock(config.lock_path):
            runner = ObservationRunner(config, archive)
            runner.run()
    except LockHeldError as e:
        print(f"trend-runner: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
