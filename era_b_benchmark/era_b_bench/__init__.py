"""Era B GBPUSD_BB_BOUNCE_S historical benchmark.

Implements the pierce + rejection-close entry and the 4-exit management
described in `spec_pins/gbpusd_bb_bounce_s_implementation_spec_20260929.md`
(commit 714af5b of github.com/JohnCarrington/autobot_reports).

Not a trader. IG broker submission is not imported, not callable, and
not present. This package is a benchmark: it detects signals against
recorded 5-minute candles and simulates exits from OHLC data. It is
not registered into autobot.py's module set and does not consume the
live streamer.

Public modules:
    config      pinned Era B constants and UNKNOWNS list
    entry       pierce + rejection-close signal detector
    exits       4-exit management simulator (SL / scale-out+BE / TP / max-hold)
    ledger      loads and filters the 36-row Era B deal reference CSV
    candles     loads 5m OHLC from data/candles/GBPUSD/YYYY-MM-DD.csv
"""
__version__ = "0.1.0-benchmark"
