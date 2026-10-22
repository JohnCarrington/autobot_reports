# Live Market Observation Agent — pilot brief (2026-10-22)

**Question from operator:** Can an agent spot an opportunity **whilst observing the live market**, rather than commissioning further retrospective entry-rule backtests?

## Why the prior answer was unsatisfactory
Do not launch another Stage 7B.2 backtest or invent another mechanical rejection pattern. This supersedes the proposed new-experiment direction as a *product concept*; do not delete, rewrite or interrupt any running research process remotely. The existing Stage 7B.2 prompt may still be running, but it is **not** a prerequisite for this pilot.

Existing primary work to reuse, not rebuild:
- `reports-public/autobot_one_strategy_stage6_interaction_observation_20260926.md`: Stage 6 causal physical observation, including LOI v6 cross counts, close/acceptance and retest information.
- `reports-public/autobot_one_strategy_stage7_continuation_evidence_20260926.md`: Stage 7 continuation evidence, including false-rejection recovery.
- `reports-public/autobot_one_strategy_stage8_interaction_resolution_20260926.md`: Stage 8 reversible interpretation, CONTINUATION / REVERSAL / UNRESOLVED, no execution.
- `reports-public/autobot_phase7b_multiyear_interaction_corpus_20260926.md`: 17,804 significant-area episodes, 71.3% of continuations first gave a false rejection and 47.1% of reversals first gave a false breakout. No justified trading edge found. This is the motivation for making **WAIT / NO OPPORTUNITY** a valid judgement.

## Pilot proposal: OBSERVE → REMEMBER → INTERPRET → EXPLAIN, never trade
A limited observational agent should **subscribe to existing read-only snapshots** (production market-data observer feeds and existing LOI/interaction sensors where legitimately accessible). It must not touch strategy permission or order placement. If there is no verified read-only interface, stop and report missing data access. Never access IG credentials, use trade APIs, or make shadow orders.

At every **closed** M5 candle, present the agent with a compact structured packet for GBPUSD:
1. Latest M5 completed OHLC + recent candles and genuinely completed H1 context; H1 BB(20,2) pierces vs known prior-hour band.
2. Timestamped known-at-time structural zones: PDH/PDL, pivot P/R1–3/S1–3, known swing highs/lows, and their provenance. Do not fabricate absent swing history.
3. **Same-area interaction history** over the observation session: number and times of approaches, wick penetrations, close-through counts, rejection strengths, breakout/failed breakout, recovery attempts, lower highs/higher lows, pace and distance after each test. Prefer existing `interaction_observation`, LOI v6, interaction resolution; distinguish missing from observed zero.
4. UK local wall-clock and the operator's nine nominated hours (06,07,08,10,11,12,13,14,16) as context, not forced gating; 09 and 15 as comparison context.
5. H1 completed range, spread if already observable, significant upcoming news only if an existing reliable as-of news feed is available. Never imagine it.
6. Previously issued observations for **the same persistent level ID** — include previous hypothesis, contrary evidence, and what changed.

**Agent outputs** are hypotheses, not mechanical entry permissions:
- `NO_OPPORTUNITY`: observation insufficient or contradictory
- `WATCH_REJECTION`: repeated tests suggest a level might hold, but confirmation is incomplete
- `WATCH_BREAKOUT`: repeated tests suggest acceptance through the level
- `OPPORTUNITY_TO_REVIEW`: enough observed evidence to notify **a human** of an emerging direction, price area, nearest opposing obstacle, uncertainty and explicit invalidation conditions. Not a trade instruction.
- `INVALIDATED`: latest evidence contradicts prior hypothesis.
Each emission must contain: observation time, level identity, summary of repeated tests, strongest evidence, strongest counter-evidence, direction **if** warranted, price movement remaining to next obstacle, uncertainty, data freshness, and **what changed since the preceding candle**. Output must permit abstention and state revision; no confidence percentages unless empirically calibrated.

## One-session demonstrator, not more parameter searches
- On a separate research workstation/process, point a **read-only** adapter to an existing market-data feed, and run the agent **observationally across a live GBPUSD London or NY session**. Do not deploy to /opt/tradingbot; no service restarts. Respect data permissions and broker rate limits.
- Maintain one persistent memory per level/zone; do not restart a fresh context on every candle or flood duplicate alerts.
- Store immutable append-only decision-time snapshots and agent responses, timestamping both input freshness and receipt. The output is NOT backfilled/reinterpreted after future candles arrive.
- Show the operator only meaningful changes: NEW WATCH, strengthening/weakening repeated test, breakout versus rejection change, reviewable opportunity, and invalidation. Default to silent monitoring for unchanged conditions.
- After the session, do **manual chronological review** of alerts and observed market movement, including false alarms, late recognition and missed obvious events. Do not change prompts mid-session. This is qualitative prospective observation, not proof of trading expectancy or permission for live orders.
- Guard against LLM hallucination: require each asserted fact to point to packet fields/timestamps. An LLM can reason about a stream of structured observations but cannot literally see market movement unless data/screenshots are supplied; no feed = no claimed live observation.

## Host discovery task (READ ONLY, no deployment)
Inventory whether Stage 5/6/7/8 modules are deployed, running and emitting **live, timestamped** observation data; identify their source, cadence, freshness, and any exposed read-only interface. Identify a safe separate-process polling/subscription path with no production mutations and without IG API calls. Return exact evidence and gaps, then propose a minimal one-session demonstrator wiring existing sensors to the agent. Stop before running any live process until a read-only feed is verified.

## Boundaries
No more historical sweeps, no 20/30-pip backtests, no optimisation, no retuning. No production edits, no NMS/AutoBot/BB Bounce changes, no order APIs, no automatic trading. Do not represent the agent as profitable until audited prospective observations show something measurable.
