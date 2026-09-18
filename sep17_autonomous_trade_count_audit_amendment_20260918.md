# 17 September Audit — Broker Reconciliation and Verdict Correction

**Additive amendment to** `sep17_autonomous_trade_count_audit_20260918.md`.
**Scope:** diagnosis only. No code, configuration, .env, restart, merge, policy change or fix. Retracts specific claims from the parent report and adds new findings from authoritative broker data.

---

## Summary of corrections vs parent report

| # | Parent claim | Amendment |
|---|---|---|
| 1 | "3 positions active during Sep 17, one Sep-16 rollover" | **Retracted.** IG activity via trades_api shows the Sep-16 14:50 open closed **2026-09-16T17:59:35Z** (same day). No rollover into Sep 17. |
| 2 | "MARKET_PRODUCED_FEWER_QUALIFYING_SETUPS" dominant cause | **Retracted.** Detector-stage cause is `INSUFFICIENT_PRODUCTION_EVIDENCE` — no pre-emission receipts exist. |
| 3 | "12 gate rejections" implied 12 missed opportunities | **Refined.** 12 raw rows dedupe to **9 unique rejected opportunities**. |
| 4 | "No defect warranted" | **Retracted.** New defect found: stale open-positions accumulator in the gate. One rejection on Sep 17 (08:20 UTC `GBPUSD_BB_BOUNCE_L`) was based on phantom positions — IG had 0 opposing at that moment, gate reported 2. |
| 5 | Verdict on the operator's "3 opens" premise | **Amended.** IG history contradicts all three offered outcomes. See §1. |

Verdict on measurement interference (Phase 2B) is **unchanged**: `NO_EVIDENCE_OF_MEASUREMENT_INTERFERENCE`.

---

## §1 — Authoritative broker truth (from IG activity via `/trades` on `127.0.0.1:8080`, `TRADES_API_HISTORY_DAYS=30`)

### Strict UTC calendar day 2026-09-17 (00:00 → 23:59:59 UTC): **2 opens**

| Position ID | Pair | Dir | Open UTC | Open BST | Close UTC | Close BST | Entry | Exit | pnl pips | source | provenance | strategy (bot) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `DIAAAAYG73Z4PBK` | GBPUSD | SELL | 2026-09-17 13:10:00 | 2026-09-17 14:10:00 | 2026-09-17 15:31:50 | 2026-09-17 16:31:50 | 13377.3 | 13347.3 | **+19.0** | `ig_only` | EXTERNAL | (unlinked; but `candidate_corpus` shows `QM_V2_VELOCITY_S`) |
| `DIAAAAYG8JY59BV` | GBPUSD | SELL | 2026-09-17 15:45:04 | 2026-09-17 16:45:04 | 2026-09-17 16:40:54 | 2026-09-17 17:40:54 | 13340.3 | 13351.3 | **−11.0** | `bot` | BOT | `GBPUSD_TREND_V3_S` |

**IG deal-close events (raw view) for 2026-09-17: 3 close-deal rows**
(2 for the 13:10 SCALE_OUT + final close of the QM_V2 position, 1 for the 15:45 TREND_V3 close). If the operator's dashboard counts deal-close events rather than distinct positions opened, the "3" figure matches the *close* count, not the *open* count.

### UK-local calendar day 17 September (BST offset +01:00 = UTC 2026-09-16 23:00:00 → 2026-09-17 22:59:59): **2 opens, same set**

No IG opens exist between 2026-09-16 23:00:00 UTC and 2026-09-17 00:00:00 UTC. The BST-adjusted window contains exactly the same two positions.

### Rollover analysis

The most recent close before the BST window was `DIAAAAYG2RPHFBE` (Sep-16 14:50 GBPUSD_BB_BOUNCE_S SELL, entry 13458.9, partial close 15:04:54, final close **2026-09-16T17:59:35Z**). This is **within Sep 16 UTC AND within BST 16 Sep**. **No rollover into BST 17 Sep or UTC 17 Sep.**

The parent report's claim that this position was still on book on Sep 17 morning was based on `qm_trade_state.jsonl` observations at Sep 17 00:00 UTC and onwards — those are trade_manager virtual observations that continue for some period after close. They are NOT authoritative for "position still open." IG is authoritative.

### Requested verdict resolution

The audit prompt asks for exactly one of:

- `OPERATOR_THREE_OPENS_CONFIRMED` — **NOT SUPPORTED.** IG shows 2 opens on Sep 17 UTC and 2 opens on BST 17 Sep.
- `TWO_OPENS_PLUS_ONE_ROLLOVER_CONFIRMED` — **NOT SUPPORTED.** IG shows no rollover into Sep 17 UTC or BST 17 Sep; the Sep-16 14:50 position closed 2026-09-16T17:59:35Z, four hours before BST 17 Sep began.
- `BROKER_HISTORY_INSUFFICIENT` — **NOT SUPPORTED.** IG activity is complete for the window (trades_api pulls 30 days, contains every deal-open and deal-close event with position IDs).

**None of the three offered verdicts match the evidence.** The evidence-grounded outcome is **TWO_OPENS_ONLY_NO_ROLLOVER** on both UTC and BST calendar days for 17 September 2026.

If the operator wishes to force one of the three, the closest is `BROKER_HISTORY_INSUFFICIENT` *only* if we consider that trades_api mis-labels the 13:10 QM_V2 trade as `source=ig_only, provenance=EXTERNAL, strategy=""` due to a linkage gap between the bot's fire records and IG's deal ID stream — meaning trades_api's "bot vs external" classification is not fully reliable. But the *count* of opens (2) is reliable, and neither of the other verdicts can be defended.

### Route classification for the two Sep-17 opens

| Position | Route classification (evidence) |
|---|---|
| `DIAAAAYG73Z4PBK` (13:10) | **Autonomous** per `candidate_corpus.jsonl` row `89ba6e8b097b46f89bc7b38a9011a00c` (strategy `QM_V2_VELOCITY_S`, `metadata.decision_mode=QM_V2_VELOCITY_S`, `source_path=QM_V2`, `executed=True`). trades_api labels it `EXTERNAL` due to an unresolved linkage between QM_V2 fires and IG dealIDs — this is a data-classification inconsistency, not a "manual trade" event. |
| `DIAAAAYG8JY59BV` (15:45) | **Autonomous** per `candidate_corpus.jsonl` row `d03a0307fd374916a1272a013aad6920` (strategy `GBPUSD_TREND_V3_S`) AND trades_api (`source=bot`, `strategy=GBPUSD_TREND_V3_S`). |

**No `BRIEFING_EXECUTION` position on Sep 17 UTC or BST 17 Sep.**

---

## §2 — Detector-stage cause: correction

**Retract:** `MARKET_PRODUCED_FEWER_QUALIFYING_SETUPS`.

**Corrected:** `DETECTOR_STAGE_CAUSE = INSUFFICIENT_PRODUCTION_EVIDENCE`.

Justification (unchanged reasoning, corrected framing):
- `phase2b_measurement.jsonl` was not writing during the 07:00–17:00 UTC session window (writer started 2026-09-17 20:30:03 UTC). Per-bar `NO_SETUP` / `SETUP_FORMING` / `SUPPRESSED` receipts are absent for the session.
- No offline causal replay of the complete production detector paths (LEVEL_BOUNCE session/major-level, BB near-touch, TREND_V3 emission, EMA_PULLBACK gate) has been performed for this audit.
- Market-context evidence (ADX 17.18, BB width 6.82p, ER 0.374, "mixed" per session) is *suggestive* of a compressed / low-signal day but does not prove where in the detector pipeline setups were consumed or dropped.

To upgrade this to a factual detector-stage cause, an offline replay of every production detector against the captured 5m close stream (all pairs, all families) would be required. Not performed here.

---

## §3 — Unique-opportunity deduplication

Raw candidate rows in `candidate_corpus.jsonl` for 2026-09-17 07:00–17:00 UTC: **17**.

Dedup keys applied:
- Same `execution_deal_id` groups pre-fill journal rows with the executed row (2 pairs merged).
- Same `(candidate_id_stem, family, side, setup/rejection bar bucket)` collapses re-emissions of a continuation setup.
- QM_V2_VELOCITY_L re-emissions in the 12:15/12:20/12:30 blackout cluster: one *market opportunity* (a long-signal into the USD 12:30 release cluster), re-fired on 3 successive bars while the blackout window held.
- QM_V2_VELOCITY_S at 13:45 and 14:30 (both `concurrent_cap`): same continuation of the trend that fired 13:10; one opportunity, re-fired.

Deduplicated opportunities: **9 rejected + 2 executed = 11 unique opportunities in-window**.

### §3 count table (deduplicated)

| Binding outcome | Raw rows | Unique opportunities | Would otherwise reach execution? |
|---|---|---|---|
| Release blackout (news_direction ∩ `NEWS_RELEASE_BLACKOUT` tag) | 4 (11:20, 12:10, 12:15, 12:20, 12:30 — actually **5 rows**) | **3** (NEWS_CONT_LEG 11:20 post-BoE; NEWS_STRATEGY_REVERSAL 12:10 pre-USD; QM_V2_VELOCITY_L 12:15/12:20/12:30 collapsed to 1) | **Uncertain.** Even if blackout were disabled, `news_direction` upstream would likely bind (NEWS_CONT_LEG is a news-family strategy inside the release window; QM_V2_VELOCITY_L LONG at 12:30 sits at MAJOR_LEVEL_TEST with no primary_direction). |
| Other news_direction (counter-trend, no blackout) | 1 (08:30 QM_V2_SLOW_REJECTION_S SHORT) | **1** | **No.** `direction_counter_trend` during active `TREND_UP` — the strategy fired in the wrong direction relative to news trend. |
| Normal_routing (DIRECTION_MISMATCH / DIRECTION_NOT_ESTABLISHED) | 3 (09:10 EMA_PB_L; 10:20 TREND_V3_UM_L; 11:50 EMA_PB_S) | **3** | **No.** Two hit `DIRECTION_NOT_ESTABLISHED` (news trend not defined); one hit `DIRECTION_MISMATCH` (family said opposite direction to news). |
| Concurrent_cap | 2 (13:45, 14:30 QM_V2_VELOCITY_S SHORT) | **1** | **No.** The 13:10 QM_V2_VELOCITY_S was still on book (closed 15:31); this is a correct binding on the actual same-family position. |
| One_book | 1 (08:20 GBPUSD_BB_BOUNCE_L LONG) | **1** | **YES — if the stale-cache defect (§4.1) is present. NO — if that defect were absent (i.e., if the gate saw IG's true 0-opposing position count).** |

**Rejected unique opportunities: 9. Of these, one (08:20 BB_BOUNCE_L) would have proceeded to `APPROVE_FINAL` if the gate's opposing-position count had reflected IG truth.**

---

## §4 — Connected suppression, per-opportunity

### 4.0 Common context

- **day_type_canonical:** BIG_NEWS (BoE Interest Rate 2026-09-17 11:00Z, USD Building Permits + Housing Starts 12:30Z)
- **NEWS_RELEASE_BLACKOUT window:** ±30 min around each HIGH release (10:30-11:30 UTC + 12:00-13:00 UTC = 2 hours of the 10-hour session, 20%)
- **Position caps configured:** per-pair × per-family concurrent_cap ceiling `1`
- **one_book:** `ONE_BOOK_GUARD=1` (default), delegates to `trade_executor.count_open_positions_by_pair_direction(pair, opposite_direction)`
- **Loaded env for the session:** `CENTRAL_STRATEGY_ORCHESTRATOR=1`, `CENTRAL_EXECUTION_GATE=1`, `NEWS_TREND_ROUTER=1`, `NEWS_RELEASE_BLACKOUT_ENABLED=1`, `QM_LIVE_FIRE=1` (unchanged Sep 14–17)

### 4.1 THE DEFECT — stale open-positions accumulator

**Evidence trace of `occupied_by_pair_family` in gate snapshot across PID 303605's lifetime (from `candidate_corpus.jsonl`):**

| First observed | occupied_by_pair_family |
|---|---|
| Sep 14 (all rows) | `{}` (empty) |
| Sep 15 (early) | `{}` |
| Sep 15 16:00:02+ | `{'GBPUSD\|BB_BOUNCE': 2, 'GBPUSD\|TREND_V3': 1}` = 3 |
| Sep 16 (early through 09:40) | same = 3 |
| Sep 16 late (19:25+) | `{'GBPUSD\|BB_BOUNCE': 4, 'GBPUSD\|TREND_V3': 4, 'GBPUSD\|UNKNOWN': 1}` = 9 |
| Sep 17 (all session bars 08:20–15:45) | same 9 (+ transient QM_V2=1 while 13:10 trade live) |

**IG-authoritative open-position count on Sep 17 morning: 0.** (The Sep-16 14:50 BB_BOUNCE_S closed 2026-09-16T17:59:35Z. No positions remained open until 2026-09-17T13:10:00Z.)

**The gate's occupancy accumulator increases when fires occur and NEVER decreases when positions close.** Between Sep 14 and Sep 17 morning, the accumulator grew from 0 → 3 → 9, tracking cumulative Sep 14-16 fires, while IG's live count returned to 0.

**Code sources:**
- `central_execution_gate.py:280–294` — builds `occupied_by_pair_family` from `_RESERVATIONS` where `r.occupied=True`
- `trade_executor.py:1022–1044` — `count_open_positions_by_pair_direction(pair, direction)` counts `EPIC_STATE` entries with `active=True or pending_open=True`
- Neither structure appears to be decremented on position-close events over the multi-day lifetime of PID 303605

### 4.2 Per-opportunity table

For each rejected unique opportunity:

| # | ts UTC | family | side | market state | news_trend_state | day type / release | opposing IG opens (truth) | opposing per gate | binding | binding rule spec | conformant? | would pass if bug fixed? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 08:20:03 | BB_BOUNCE | LONG | TRADABLE_NON_RANGE (bb_w 19.8p, ER 0.608) | MAJOR_LEVEL_TEST (BUY) | BIG_NEWS pre-BoE (release ~2h40) | **0** | **2 (STALE)** | `one_book:coherence_block:opposing_open_count=2` | block if any opposing-direction pair position open | **No — used stale cache** | **YES** |
| 2 | 08:30:00 | QM_V2 | SHORT | (not captured) | MAJOR_LEVEL_TEST (BUY) | BIG_NEWS pre-BoE | 0 | 9 | `news_direction:direction_counter_trend` | block if direction opposite to active news trend | Yes | No |
| 3 | 09:10:05 | EMA_PULLBACK | LONG | (LEVEL_HOVER) | MAJOR_LEVEL_TEST (no primary) | BIG_NEWS | 0 | 9 | `normal_routing:DIRECTION_MISMATCH:EMA_PULLBACK:SELL` | block if strategy direction disagrees with routed direction | Yes | No |
| 4 | 10:20:04 | TREND_V3_UM | LONG | (MAJOR_LEVEL_TEST) | MAJOR_LEVEL_TEST (no primary) | BIG_NEWS pre-BoE (release ~40 min) | 0 | 9 | `normal_routing:DIRECTION_NOT_ESTABLISHED:TREND_V3` | block if news trend direction unresolved for a trend-family | Yes | No |
| 5 | 11:20:07 | NEWS_CONTINUATION | SHORT | (BOUNCE_FORMING) | BOUNCE_FORMING (BUY) | BIG_NEWS post-BoE 20m | 0 | 9 | `news_direction:NEWS_RELEASE_BLACKOUT:post:20m` | ±30 min around HIGH release | Yes | No |
| 6 | 11:50:02 | EMA_PULLBACK | SHORT | (REVERSAL_CONFIRMED) | REVERSAL_CONFIRMED (SELL, disp 20.4p) | BIG_NEWS | 0 | 9 | `normal_routing:DIRECTION_NOT_ESTABLISHED:EMA_PULLBACK` | (news trend transient, not established for this family) | Yes | No |
| 7 | 12:10:05 | NEWS_STRATEGY | LONG | (MAJOR_LEVEL_TEST) | MAJOR_LEVEL_TEST (no primary) | BIG_NEWS pre-USD 19m | 0 | 9 | `news_direction:NEWS_RELEASE_BLACKOUT:pre:19m` | ±30 min | Yes | No |
| 8 | 12:15:01 / 12:20:04 / 12:30:11 (cluster) | QM_V2 | LONG | (MAJOR_LEVEL_TEST) | MAJOR_LEVEL_TEST | BIG_NEWS pre/post-USD (14m, 9m, 0m) | 0 (no opposing LONG) | — | `news_direction:NEWS_RELEASE_BLACKOUT` × 3 | ±30 min | Yes | No |
| 9 | 13:45:00 / 14:30:00 | QM_V2 | SHORT | (MAJOR_LEVEL_TEST / BOUNCE_CONFIRMED) | with-trend (SELL) | BIG_NEWS post-USD | 1 (the 13:10 QM_V2 SHORT is live) | 1 (QM_V2 reservation) | `concurrent_cap:concurrent_cap_reached_1_1` | 1 per pair × family | **Yes — correct binding** (actual position live) | No |

**Row 1 is the only defective binding.** Rows 2-9 are correct under specification even if the accumulator is stale — because their upstream binding (news_direction/normal_routing/blackout) fires before one_book/concurrent_cap and is based on independent state (news trend engine, blackout timing calendar).

Concurrent_cap in row 9 uses a different accumulator path (RESERVATIONS occupied for QM_V2 = 1), and the 1 is real (the 13:10 fire).

### 4.3 Impact estimate

**If the stale-cache defect were absent:** 08:20 GBPUSD_BB_BOUNCE_L would have been APPROVED. Its `candidate_price` was 13380.85 (LONG, BUY). GBPUSD 08:20-14:00 UTC went 13380 → 13340 (SELL momentum). A LONG entry at 13380.85 with default BB_BOUNCE_L SL/TP would likely have **lost** (SL first, then price moved down 45p by 14:00). So the *count* would have been 3 fires instead of 2, but the P&L outcome for this opportunity would probably have added another loss.

The defect nonetheless remains a legitimate issue because the rejection was based on incorrect state, not on the intended policy.

---

## §5 — Historical population comparison

`candidate_corpus.jsonl` was purged on 2026-09-12 and again on 2026-09-14; funnel evidence is limited. But `trades_api` (30-day HISTORY_DAYS) provides authoritative broker open counts:

| Date | Total IG opens | bot-tagged (auton + brief) | ig_only-tagged | day type / notes |
|---|---|---|---|---|
| 2026-09-04 (Fri) | 6 | 6 (6 auton, 0 brief) | 0 | |
| 2026-09-07 (Mon) | 7 | 5 (5 auton) | 2 | |
| 2026-09-08 (Tue) | 7 | 5 (5 auton) | 2 | |
| 2026-09-09 (Wed) | 13 | 9 (9 auton) | 4 | |
| 2026-09-10 (Thu) | 9 | 7 (7 auton) | 2 | |
| 2026-09-11 (Fri) | 6 | 5 (5 auton) | 1 | |
| 2026-09-14 (Mon) | 3 | 1 (1 auton) | 2 | GO-LIVE flags loaded on Sep 14 (env timestamp 08:36 UTC) |
| 2026-09-15 (Tue) | 6 | 3 (3 auton) | 3 | |
| 2026-09-16 (Wed) | 6 | 6 (5 auton, 1 brief) | 0 | US CPI 12:30Z |
| **2026-09-17 (Thu)** | **2** | **1 (1 auton, 0 brief)** | **1** (the QM_V2 mis-linked) | BoE 11:00Z + USD 12:30Z |
| 2026-09-18 (Fri, partial) | 1 | 0 | 1 (USDJPY external) | audit day |

Autonomous opens median for Sep 4-16 (excluding weekends and partial days): **5 per day** (range 1-9).

**Sep 17 autonomous open count of 1 (per trades_api) or 2 (per candidate_corpus if we treat the mis-linked QM_V2 as autonomous) is at the low end of the observed range but not unprecedented — Sep 14 also had 1.**

**HISTORICAL_COMPARISON_GRADEABLE for the broker-open dimension** (trades_api supports it back to Sep 4). Detector-stage historical comparison is not gradeable due to the corpus purges.

---

## Corrected verdict structure

| Dimension | Verdict | Justification |
|---|---|---|
| **Phase 2B interference** | `NO_EVIDENCE_OF_MEASUREMENT_INTERFERENCE` | Unchanged from parent report. Measurement writer was not active during Sep 17 07-17 UTC. |
| **Broker/open-count reconciliation** | **None of the 3 offered verdicts fit; evidence-grounded outcome is TWO_OPENS_ONLY_NO_ROLLOVER.** If forced to pick, `BROKER_HISTORY_INSUFFICIENT` misrepresents the situation — IG history is complete; it is the operator's premise that is not supported. | IG activity via trades_api shows 2 opens on both UTC and BST calendar days for 17 Sep; no rollover; last Sep-16 close 17:59:35 UTC on Sep 16. |
| **Detector-stage cause** | `INSUFFICIENT_PRODUCTION_EVIDENCE` | Per-bar detector receipts absent for the session (phase2b writer inactive). Offline replay not performed. |
| **Post-emission suppression** | 9 unique rejected opportunities; **8 conformant, 1 defective**. See §4 table. | Correct-under-spec: 2 news_direction (blackout family) + 3 normal_routing (direction) + 3 news_direction (blackout window itself) + 1 concurrent_cap. Defective: 1 one_book based on stale cache. |
| **Execution failure** | **Absent.** Both approved candidates (13:10 QM_V2_VELOCITY_S, 15:45 GBPUSD_TREND_V3_S) reached the broker on the first attempt and received `dealStatus:ACCEPTED`. | Journal + trades_api both agree. |
| **Intended-behaviour conformity** | Split: (a) news_direction / normal_routing / blackout bindings — **conformant** to intended behaviour under the loaded policy. (b) `one_book:coherence_block:opposing_open_count=2` at 08:20 UTC — **non-conformant** to intended behaviour because `opposing_open_count` was based on a stale accumulator that did not reflect IG truth (0 opposing positions). | See §4.1 stale-accumulator evidence. |
| **Current-spec legality** | The one_book rejection *is* legal per the current spec (the spec says: block if `count_open_positions_by_pair_direction(pair, opposite) > 0`). The spec was followed. The **inputs** to the spec were stale. This is an implementation defect below the spec layer. | Distinction preserved per audit protocol. |

---

## Defect entry

**DEFECT-2026-09-18-A** — Gate/executor open-positions accumulator monotonically increasing without decrement on position close.

- **Symptom:** `gate_capacity_snapshot.occupied_by_pair_family` grew 0 → 3 → 9 over PID 303605's lifetime (Sep 14 → Sep 17) despite IG's live count returning to 0 multiple times.
- **Concrete impact on 2026-09-17:** 1 unique opportunity (08:20 UTC `GBPUSD_BB_BOUNCE_L` LONG, candidate `96f542e1bb594385a7a31ea18a15ed75`) was rejected by `one_book:coherence_block:opposing_open_count=2` when IG had 0 opposing positions. Without the defect, the candidate would have proceeded to `gate:APPROVE_FINAL`.
- **Code locations (for reference, not for fixing in this audit):**
  - `central_execution_gate.py:280–294` builds `occupied_by_pair_family` from `_RESERVATIONS[r].occupied=True`
  - `trade_executor.py:1022–1044` `count_open_positions_by_pair_direction()` iterates `EPIC_STATE` for `active=True or pending_open=True`
  - Neither accumulator appears to be decremented on the position-close code path over multi-day PID uptime
- **Wider question:** the mismatch has been growing since at least Sep 15 (occupied first became non-empty at Sep 15 16:00 UTC and never subsequently reset), so any prior fire day where one_book or concurrent_cap depended on a fresh count may also have been affected. This needs separate historical review.
- **Not fixing here per audit scope.**

---

## What remains open

- **Full detector-pipeline offline replay** for Sep 17 07-17 UTC to fill in the `NO_SETUP` / `SETUP_FORMING` / `SUPPRESSED` counts and confirm or refute the "compressed-day fewer-signals" hypothesis. Not performed here; would need a bar-replay harness that runs every enabled detector against the 5m stream.
- **Historical scan of one_book / concurrent_cap rejects** for the entire PID 303605 lifetime (Sep 14 onwards) to quantify how many prior autonomous opportunities were suppressed by this stale-cache defect on days other than Sep 17.
- **Reconciliation of the trades_api bot-fire linkage** for QM_V2 fires (the 13:10 QM_V2 was correctly the autonomous QM path per candidate_corpus, but trades_api tagged it EXTERNAL). This is a data-classification issue in the dashboard-facing API, not in the trading path.
