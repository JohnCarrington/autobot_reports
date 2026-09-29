# Observation-only pierce + rejection-close detector

**One-file, no-dependency module for Project Thirty (or any host with 5-minute
GBPUSD candles). Detects pierce → rejection-close candidates and logs them
to CSV. Does not import IG. Does not open, amend, or close positions. Cannot,
by construction.**

Not deployed on host 161 (which runs the live trader — leaving it
untouched). Ready for Project Thirty to pull, review, and deploy.

## What it does

For each 5-minute GBPUSD bar it consumes:

1. If bar N-1 was a pierce setup (high pierced BB(20,2) upper band by
   ≥ `PIERCE_THRESH_PIPS`, opened inside the band), arm it.
2. If bar N is a bearish rejection candle (body ≥ 1.5 p, close inside
   band + 1.0 p tolerance) and any armed setup is ≤ 3 bars old, emit
   a **SELL candidate**.
3. Append one row to `candidates_log.csv` with:
   candidate_ts, both bars' OHLC, BB values at both bars, pierce depth,
   rejection body, back-inside margin, which of N/N+1/N+2 caught it,
   the pierce threshold used, and whether the rejection bar was
   in-session (06:00–17:00 UTC).

That's it. No exit simulation, no orders, no state file.

## Two usage modes

### As a library (recommended for a live 5m stream)

```python
from observer import Detector, Candle

det = Detector(
    log_path="/var/log/project30/bb_pierce_candidates.csv",
    pierce_thresh_pips=0.5,   # Era B code default; tune per your study
)

# In your streamer, on every completed 5m bar:
det.on_bar(Candle(ts=bar_open_utc, open=..., high=..., low=..., close=...))
```

`on_bar` returns the candidate row dict when one fires, else `None`.
Rows are flushed to disk after every write.

### As a one-shot replay over a CSV

```
python3 observer.py --candles data/candles/GBPUSD/2026-05-27.csv \
                    --out /tmp/candidates.csv \
                    --pierce-thresh 0.5
```

Input CSV must have `timestamp,open,high,low,close` with UTC-aware
timestamps and prices in the same scale as the calibration data
(GBPUSD mid × 10000; 1 pip = 1 unit — check
`/opt/tradingbot/data/candles/GBPUSD/2026-05-27.csv` for reference).

## What it does NOT do

- Does not import `ig_service`, `open_sb_now`, `close_sb_now`, or any
  broker SDK. `grep -R 'import ig\|IGService\|open_sb\|close_sb' observer/`
  returns nothing.
- Does not touch `.env`, systemd services, or any file outside its
  configured log path.
- Does not call `regime_engine`, `cascade_state`, briefing modules, or
  H1 aggregators. Adding those in an observer would introduce hidden
  gates and defeat the point.
- No cross-strategy state, no concurrency cap, no position slot. Every
  pierce+rejection is logged; downstream comparison decides which
  ones would matter.

## Recording live?

Yes, once **you** deploy it on Project Thirty. This repo pushes the
source; no runtime is started here.

- On host 161: not running (host 161 runs the live AutoBot; this
  observer is not registered into its module set and is not started
  by systemd or any other mechanism).
- On Project Thirty: deploy per your usual candle stream. A minimal
  wrapper is one `Detector.on_bar()` call per completed 5m bar.

## Origin

Extracted from the pierce+rejection semantics documented in
`../spec_pins/gbpusd_bb_bounce_s_implementation_spec_20260929.md` §2,
verified against the AutoBot source at commits `c85481c` and `e8fc9dd`
in `../era_b_src/`. The 36 Era B live-trader fires all correspond to
candidates this detector would emit at `pierce_thresh_pips=0.5`
(confirmed in `../logs`/`confirmation_engine.jsonl-20260917`).

This detector reproduces the *entry mechanism only*. It says nothing
about exits, position size, or expected P&L. See
`../CORRECTIONS_20260929.md` on why the historical +395.4 p figure
is not a reproducible strategy result.
