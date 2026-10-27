"""Phase 2 execution simulator — chronological event engine.

Reads ticks from the Phase 2 corrected cache (per-year parquet, int64
nanoseconds, bid/ask preserved). Drives the BrokerSimulator and emits
EngineEvents to a strategy adapter.

Design intent: NO LOOK-AHEAD. A strategy, at tick N, only sees quotes
≤ ts_utc_ns of tick N. Orders submitted at tick N cannot execute against
quote prices from earlier ticks (enforced by submission_latency_ns in
the broker). The engine is deterministic given (ticks, strategy, config).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd

from .broker import BrokerSimulator
from .types import EngineEvent, Quote


CACHE_ROOT_DEFAULT = Path("/mnt/volume_lon1_1778405456698/research/tick_cache_v2_utc_corrected/GBPUSD")


class CorrectedTickReader:
    """Lazy, chronological reader for the corrected per-year parquet cache."""

    def __init__(self, cache_root: Path = CACHE_ROOT_DEFAULT, years: Iterable[int] = (2024, 2025, 2026)):
        self.cache_root = Path(cache_root)
        self.years = tuple(years)

    def iter_range(self, start_utc_ns: int, end_utc_ns: int) -> Iterable[Quote]:
        """Yield Quote in chronological order, spanning year parquet files as needed."""
        # Determine which year files are relevant
        for yr in self.years:
            p = self.cache_root / f"{yr}.parquet"
            if not p.exists():
                continue
            # Use pyarrow filter pushdown to read only the needed slice
            df = pd.read_parquet(
                p, columns=["ts_utc_ns", "bid", "ask", "source_row"],
                filters=[("ts_utc_ns", ">=", start_utc_ns), ("ts_utc_ns", "<", end_utc_ns)],
            )
            if df.empty:
                continue
            # Stable sort — the file is already sorted but defensive.
            df = df.sort_values(["ts_utc_ns", "source_row"], kind="mergesort")
            for ts, bid, ask in zip(df["ts_utc_ns"].to_numpy(), df["bid"].to_numpy(), df["ask"].to_numpy()):
                yield Quote(int(ts), float(bid), float(ask))


class ReplayEngine:
    """Minimal chronological replay driver.

    Strategy is a callable:
        strategy(event: EngineEvent, broker: BrokerSimulator) -> None

    It is called:
      - After each tick's broker.on_quote with event kind='TICK' (payload: ts, bid, ask)
      - After each broker-generated event (ORDER_FILLED, POSITION_CLOSED, etc.)
      - At the completion of each 5-minute UTC bucket with kind='BAR_CLOSE_5M'
        and payload={'ts': bar_close_ns, 'ohlc_bid': (o,h,l,c), 'ohlc_ask': (o,h,l,c)}

    The strategy MAY submit orders in response to any event. It cannot
    inspect any ticks or candles beyond the one being delivered.
    """

    FIVE_MIN_NS = 5 * 60 * 10**9

    def __init__(
        self,
        broker: BrokerSimulator,
        strategy: Callable[[EngineEvent, BrokerSimulator], None],
        reader: Optional[CorrectedTickReader] = None,
    ):
        self.broker = broker
        self.strategy = strategy
        self.reader = reader or CorrectedTickReader()
        # 5m bar state
        self._bar_start_ns: Optional[int] = None
        self._bar_bid: list[float] = []
        self._bar_ask: list[float] = []
        self.event_log: list[EngineEvent] = []

    def _flush_bar(self, bar_close_ns: int) -> None:
        if not self._bar_bid:
            self._bar_start_ns = None
            return
        bid_arr = np.array(self._bar_bid)
        ask_arr = np.array(self._bar_ask)
        payload = {
            "ts": bar_close_ns,
            "ohlc_bid": (float(bid_arr[0]), float(bid_arr.max()), float(bid_arr.min()), float(bid_arr[-1])),
            "ohlc_ask": (float(ask_arr[0]), float(ask_arr.max()), float(ask_arr.min()), float(ask_arr[-1])),
            "ohlc_mid": tuple(float(x) for x in [
                (bid_arr[0] + ask_arr[0]) / 2,
                ((bid_arr + ask_arr) / 2).max(),
                ((bid_arr + ask_arr) / 2).min(),
                (bid_arr[-1] + ask_arr[-1]) / 2,
            ]),
            "n_ticks_in_bar": int(len(bid_arr)),
        }
        evt = EngineEvent("BAR_CLOSE_5M", bar_close_ns, payload)
        self.event_log.append(evt)
        self.strategy(evt, self.broker)
        self._bar_bid.clear()
        self._bar_ask.clear()
        self._bar_start_ns = None

    def _bucket(self, ts_ns: int) -> int:
        return (ts_ns // self.FIVE_MIN_NS) * self.FIVE_MIN_NS

    def run(self, start_utc_ns: int, end_utc_ns: int) -> None:
        for q in self.reader.iter_range(start_utc_ns, end_utc_ns):
            # Bar boundary — flush closed bar(s) BEFORE processing this tick's broker events,
            # since indicator state must settle on the completed bar before the strategy decides.
            cur_bucket = self._bucket(q.ts_utc_ns)
            if self._bar_start_ns is None:
                self._bar_start_ns = cur_bucket
            while self._bar_start_ns is not None and cur_bucket > self._bar_start_ns:
                bar_close_ns = self._bar_start_ns + self.FIVE_MIN_NS
                self._flush_bar(bar_close_ns)
                self._bar_start_ns = cur_bucket

            # Accumulate into current bar
            self._bar_bid.append(q.bid)
            self._bar_ask.append(q.ask)

            # Advance the broker's tick clock → may generate ORDER_* events
            new_events = self.broker.on_quote(q)
            # Deliver TICK first, then broker-generated events
            tick_evt = EngineEvent("TICK", q.ts_utc_ns, {"bid": q.bid, "ask": q.ask})
            self.event_log.append(tick_evt)
            self.strategy(tick_evt, self.broker)
            for evt in new_events:
                self.event_log.append(evt)
                self.strategy(evt, self.broker)

        # Flush final bar if partially filled
        if self._bar_start_ns is not None and self._bar_bid:
            self._flush_bar(self._bar_start_ns + self.FIVE_MIN_NS)
