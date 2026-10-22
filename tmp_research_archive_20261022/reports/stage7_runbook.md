# Stage 7 — Scheduled observation of reversal onset AND continuation
**Frozen hypothesis record: 2026-10-22. Research-only. No live trading or production integration.**

## User observations (preserve exactly)
The user observes that **some portion of significant reversal movement happens near these UK-local clock times**:
**06:00, 07:00, 08:00, 10:00, 11:00, 12:00, 13:00, 14:00, 16:00**.
The user also identifies **H1 candle range** as important.
A reversal may **begin before** an observed time, **start around** it, or **continue/accelerate across** it. These are separate questions, not interchangeable signals. Do not require a reversal to start precisely on an anchor or silently change the listed times.

## Research question and two independently reported modes
**Mode D — DETECTION:** When a nominated clock-hour begins, what completed-candle evidence of an emerging reversal already exists, and what new events are observed during that hour? Measure the timing of candidate onset, first observable structural evidence, and first confirmed reversal **as separately timestamped events**. *Do not label historical turning points as if known live.*

**Mode C — CONTINUATION:** For a reversal that is *already under way* and observable by an anchor, is there evidence that its next 20 or 30 pips occur, or that it fails? Track active events entering the hour as well as new events arising during it. Give each event a stable ID so it is not counted as a fresh independent trade at every clock hour.

**Mode B — BOTH:** At each anchor the observer checks simultaneously for new onset evidence and already-active developing reversals. A candidate may transition from DETECTED to DEVELOPING to CONFIRMED to FOLLOWING; these are **research states**, not execution permissions, and must be strictly point-in-time.

## Time convention — essential
- Anchors are at UK local wall-clock time in `Europe/London`, converted to UTC per historical calendar day, including BST/GMT and the periods when US DST differs.
- Evaluate at the anchor with **only candles closed by that instant**, and then evaluate every following *closed* M5 candle within that UK-local clock-hour. The anchor is a checkpoint, not necessarily the start of the move.
- Report separate timing distributions for: reversal evidence first seen **before anchor**, **at/after anchor**, confirmed **within hour**, and movement continuing **across anchor**. Also report the 24-hour baseline to avoid mistaking busy hours for predictive edge.
- H1 feature: most recent **fully completed** H1 candle at decision timestamp (requiring twelve contiguous M5 bars). Report both absolute H1 range (pips) and H1 range relative to a trailing completed-H1 distribution, with parameters prespecified before outcome inspection; partial H1 range may be logged observationally but cannot masquerade as completed H1.
- Price units: IG-scale GBPUSD uses 1 unit = 1 pip; validate rather than assume for each source.

## Two-stage design to avoid altering prior experiments
### Stage 7A — Observational hour/range audit using FROZEN Stage 5 events
Use the existing `reversal_shadow_baseline.detect` candidate and confirmed events without changing its geometry. For each original candidate, reconstruct its as-of lifecycle from closed M5 candles. At anchor snapshots report whether the event was not-yet-observed, candidate-only, confirmed, active or complete. A confirmation only becomes known at the confirming M5 **close**. A rejection H1 only becomes known at its H1 **close**. No future information may affect state.
For each unique confirmed event and after-confirmation entry proxy, examine the next 6/12/24 contiguous M5 bars: directional close, MFE, MAE, reaching +20/+30 pips (not a win, no costs/stop ordering). Record hour-of-day and H1 range at the confirmation time **and** at each anchor, with no future leakage. Do not independently count the same event in multiple anchor snapshots in denominators of unique opportunities.
This is a descriptive test of user observations; it does not establish a continuation-vs-failure trade label.
### Stage 7B — A NEW observable market-structure event
In a separate preregistration, define structural break, recovery failure, and developing reversal states using only completed candles and a no-future-lookahead pivot/swing definition. Then specify continuation target (+20/+30), adverse invalidation/stop, time horizon, entry proxy and OHLC both-hit ambiguity policy. No extra entry filters invented ad hoc. Freeze definitions using DEV only, then use VAL and untouched OOS exactly once. A pending event **may span several nominated checkpoints**.
Stage 7A must not be used to optimise Stage 7B rules on OOS.

## Data and evaluation gates
- Re-verify Stage 5 hashes and CLEAN allowlists before reading the 2024–26 dataset. DEV: 2024-01-01..2025-06-30 BID. VAL: 2025-07-01..2025-12-31 BID. OOS: 2026-01-01..2026-10-07 MID; note BID/MID shift. Do not mix sources or use excluded `ohlc/` data.
- Audit at least 20 event/anchor examples manually against raw completed M5 source, covering clock changes, BUY/SELL, and active carry-over.
- Baselines: nine nominated hours vs other hours, all 24 UK-local hours, and H1-range-conditioned observations. Compare **incidence per observation opportunity** separately from **subsequent directional performance conditional on a candidate**.
- Report event count, repeated snapshots per event, sample size, censored/missing, uncertainty, target-reaching rates, MFE, MAE, next-close directional movement, and by-hour H1 range distributions. No claim of profits without execution costs/stop ordering.
- No automated model learning or live shadow deployment until the event/label validity and baseline are established.

## Operational constraints
Read-only research worktree on server 161. **Never** restart services, change live AutoBot/NMS, fetch IG credentials, execute trades, or edit frozen Stage 5/6 files. Save an independent evidence report and hash all outputs. If an input is unavailable, stop at the actual blocker; do not manufacture data, claims, or a new reversal strategy.
