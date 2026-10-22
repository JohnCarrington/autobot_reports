# Stage 7B.1 structural-level authority audit and enrichment handoff

Research-only. Existing Stage 7B BB-pierce watch records and Stage 5/6/7A findings remain frozen. **No trading or production edits.**

## Discovered authority conflict
- `daily_snapshot.py` declares a daily-fixed set **PIVOT, PDH, PDL, R1–R3, S1–S3**, all derived from one authoritative **previous completed D1** selected by `htf_cache.select_prior_completed_d1`. `daily_structural_context.py` wraps the snapshot for consumers; its feature flag defaults OFF.
- `ig_daily_pivots.py` separately describes classic-floor pivots derived from the **ASK side of IG daily bars**, with IG ordering including possible Sunday bars; its module documentation says the initial implementation was not wired.
- `qm_swing_levels.py` describes a V2 **three-close cluster and next-bar rejection** swing algorithm, rather than a generic right-confirmed fractal swing. `level_computation.py` also has separate H1/H4 swing candidates.
- **Therefore it is unsafe to synthesize a supposedly canonical historical structural-level map from BID/MID M5 candles without first reconciling the reference source, pivot formula, calendar-day cutover, swing definitions, and what was active as-of each historical timestamp.** Do not merge these competing semantics or silently fall back to a different formula.

## Implemented safe bridge
`scripts/research/reversal_shadow_stage7b_levels.py` enriches each existing H1 band-pierce watch using **verified point-in-time structural snapshots** in JSONL format. Snapshot record needs:
```json
{"known_at_utc":"2026-10-21T23:00:00+00:00",
 "valid_until_utc":"2026-10-22T23:00:00+00:00",
 "source":"EXPLICIT_VERIFIED_AUTHORITY",
 "reference_period":"EXACT_COMPLETED_D1_IDENTITY",
 "method":"EXACT_PIVOT_AND_SWING_FORMULAS",
 "levels":{"PDH":13500.0,"PDL":13300.0,"PIVOT":13400.0,"R1":13450.0,"R2":13550.0,"R3":13600.0,"S1":13350.0,"S2":13250.0,"S3":13200.0,"SWING_HIGH":13525.0,"SWING_LOW":13325.0}}
```
**Above values are syntactic examples only, not market observations; never supply them to an actual study.** Missing or expired snapshots yield `UNKNOWN`, and missing individual level types yield `PARTIAL`. Overlapping snapshots fail. The bridge reports nearest level, signed candidate-direction room to the next level, all distances and explicit provenance. No threshold-based filters or decisions are applied.

## Stage 7B.1 next host task
1. Fetch research branch read-only and run `test_reversal_shadow_*.py` suite.
2. Read `daily_snapshot.py`, `daily_structural_context.py`, `htf_cache.py`, `bb_pd_gate.py`, `ig_daily_pivots.py`, `qm_swing_levels.py`, `level_computation.py` **without importing production modules that cause side effects**.
3. Determine from **actual historical artefacts and execution configuration**, separately by DEV BID, VAL BID, OOS MID, which D1/IG source was authoritative, its daily cutoff, exact classic-floor formula and whether swing levels can be reconstructed as of observation without hindsight. Log conflicts rather than choose the easiest definition.
4. Create validated point-in-time JSONL level snapshots covering permitted historical watches only from verified source records. Hash both inputs and snapshots, assert reference candle completes before `known_at_utc`, and independently sample at least 20 cases covering DST/weekends and missing days. If verified historical levels do not exist, report BLOCKED FOR STRUCTURAL ENRICHMENT—no synthetic pivots.
5. Run:
```bash
python -m scripts.research.reversal_shadow_stage7b_levels \
 --watches /VERIFIED/stage7b/dev/h1_bb_pierce_m5_watches.jsonl \
 --verified-level-snapshots /VERIFIED/dev/structural_levels.jsonl \
 --pip-size 1 \
 --output /VERIFIED/stage7b/dev/h1_bb_watches_enriched.jsonl
```
Repeat separately for validation and OOS with verified source conventions; no mixed-price-basis inference.
6. Validate all PDH/PDL, Pivot R1–R3 S1–S3 and swing timestamps and provenance. Then produce distance-to-level, side, confluence and time-of-day distributions. Do **not** claim trade profitability; rejection and first-hit continuation/failure outcomes remain unimplemented.

## Safety
Never change live AutoBot, NMS V3, standalone BB Bounce, or systemd. Never fetch broker credentials or place orders. This bridge is descriptive and offline.
