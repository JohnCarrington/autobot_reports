# Stage 7B amendment A1 — structural-level attention (2026-10-22)

## User-directed addition — REQUIRED observational context
The H1 Bollinger(20,2) pierce → M5 observation research must pay particular attention to **PDH, PDL, swing high, swing low, R1, R2, R3, Pivot (P), S1, S2, S3**. Preserve all eleven named types; these are observation features **not entry filters, execution gates, stops, targets or authority to trade**. Existing Stage 7B pierce mechanics, standalone M5 BB Bounce and production AutoBot remain unchanged.

## Observation states
The observer should record a level map as of every queued H1-band-pierce watch and at subsequent completed M5 observations. It must distinguish:
- **approaching / nearby** a known level, using an explicit distance in pips rather than an undocumented closeness threshold;
- **piercing / rejecting** a known level, based on already-closed M5 price action;
- **break / retest / failure to reclaim** a known level, timestamped only when each element has been observed;
- **space to next opposing level** in the putative bounce direction, without treating that distance as a predetermined target.
Track level identity, level price, distance in pips, side of price, timestamp that each level became knowable, M5 touch/pierce/rejection, and the nearest several confluences. Do not suppress observations if no level is nearby.

## Anti-lookahead rules and authority to settle BEFORE results
- **PDH / PDL**: prior **completed** trading-session day's extrema, according to a declared FX trading-day cutover and holiday/Sunday handling. Never use today's unfinished daily high/low as *previous day*. Record timezone and session boundary. Compare with existing AutoBot structural authority; do not silently invent a different PDH/PDL convention.
- **Pivot P, R1–R3, S1–S3**: use only the prior fully completed session/day OHLC. Confirm and freeze **which pivot family/formula and daily cutover the existing AutoBot briefing/structural module uses** before calculating levels; do not silently mix Classic, Fibonacci, Woodie, Camarilla or broker pivot types. Persist the exact formulas and reference session.
- **Swing high / swing low**: explicit timeframe, lookback and confirmation/latency rule. A pivot requiring right-hand bars becomes known **only after those M5 bars close**. Record first-known timestamp; never plot hindsight swings as live-known.
- **H1 range**: previous completed H1 high–low, not the developing hour.
- A level's timestamp must be <= the observation timestamp. Missing data produces UNKNOWN, not a fabricated level.

## Testable research comparisons
A. H1 band-pierce watches near and far from each structural level, with distance reported continuously and via **prespecified** buckets. B. Times of day × completed H1 range × distance/confluence, including the original nine UK anchor times and 09/15 controls. C. M5 structural behaviour following pierce at PDH, PDL, swing high/low or pivot zones. D. Continuation vs failed bounce using independently preregistered first-hit +20/+30 and adverse threshold, OHLC both-hit ambiguity and measured costs (separate Stage 7B.2; NOT yet implemented). Also stratify by side and avoid treating repeated watches on the same event as independent trade samples.

## Deliverables and safety
1. Locate existing AutoBot PDH/PDL/pivot/swing source definitions in GitHub/server **read-only**. Record exact file, method, formulas, timestamps and gaps. Raise unresolved conventions as blockers rather than guessing.
2. Build a causal research-only level-map calculator with tests covering weekend, DST, completed-day boundary, pivot mathematics and delayed swing confirmation.
3. Add level proximity, level interaction and room-to-next-level columns to H1-band watch events and subsequent M5 observations; measure all baseline watches, not just promising ones.
4. Run an independent integrity audit before historical inference. Never change production, systemd, NMS V3, standalone BB Bounce or place trades.
