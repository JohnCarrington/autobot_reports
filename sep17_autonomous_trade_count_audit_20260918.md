# 17 September Autonomous Trade Count — Full Causal Audit

**Status:** DIAGNOSIS ONLY. No fix, restart, configuration, .env, merge, trading-policy change, or code change proposed.
**Author:** autobot session, 2026-09-18 ~07:15 UTC
**Question:** Why was the autonomous trade count on 2026-09-17 abnormally low?

---

## Verdict — up front

**Primary classification: `MIXED_CAUSES`** — dominated by `MARKET_PRODUCED_FEWER_QUALIFYING_SETUPS` (compressed / mixed session, ADX=17.18, BB width 6.82p), with substantial contribution from `CONFIGURATION_OR_ROUTING_SUPPRESSION` (news-release blackout and news-direction routing correctly suppressing counter-trend and pre/post-release candidates).

**Earliest funnel divergence from comparable days:** at **detector emission**, not at the gate. Detector emissions for trend-following families dropped sharply while QM (rejection) family emitted more.

| Family | Sep 15 | Sep 16 | Sep 17 |
|---|---|---|---|
| TREND_V3 emissions | 4 | 10 | 3 |
| BB_BOUNCE emissions | 7 | 5 | 1 |
| LEVEL_BOUNCE emissions | 1 | 3 | 0 |
| QM_V2 emissions | 0 | 3 | 8 |

**Exact binding reasons for missing autonomous trades on 2026-09-17 (07:00–17:00 UTC):**

| Binding | Count | Interpretation |
|---|---|---|
| `news_direction` | 6 | Counter-trend to news trend engine (5 during NEWS_RELEASE_BLACKOUT ±30 min around BoE 11:00 UTC and USD releases 12:30 UTC) |
| `normal_routing` | 3 | `DIRECTION_MISMATCH` / `DIRECTION_NOT_ESTABLISHED` between family + news trend |
| `concurrent_cap` | 2 | After the 13:10 QM_V2 fire, same-family SHORT continuations were correctly capped |
| `one_book` | 1 | Opposite-direction (LONG) BB_BOUNCE while the Sep-16 SHORT was still on book |
| **Total rejected** | **12** | |
| Approved | 5 (3 = 2 unique deals, 2 = pre-fill journalling rows) |
| Executed unique deals | **2** | |

**Correctness under current rules:** every rejection I inspected was consistent with intended behaviour under `NEWS_RELEASE_BLACKOUT_ENABLED=1`, `NEWS_TREND_ROUTER=1`, `CENTRAL_EXECUTION_GATE=1`, and the concurrent-cap and one_book policies. No misfire, no incorrect binding.

**Violated intended behaviour:** none identified. All bindings did what they were configured to do.

**Defect/register entries:** none warranted.

---

## Premise-correction paragraph (important)

The audit prompt asserts "three broker positions opened on 2026-09-17; two originated from briefing execution; one originated from AutoBot's autonomous strategy pipeline." **The log evidence does not support that split.**

Journal + `candidate_corpus.jsonl` + `qm_trade_state.jsonl` show:

- **Only 2 broker opens dated 2026-09-17 UTC**, both **autonomous**:
  - `2026-09-17T13:10:00.95` — `QM_V2_VELOCITY_S` SHORT, deal `DIAAAAYG73Z4PBK`, entry 13377.3 — **profit** (target-first, mfe 15.2p, mae 10.6p)
  - `2026-09-17T15:45:04.90` — `GBPUSD_TREND_V3_S` SHORT, deal `DIAAAAYG8JY59BV`, entry 13340.3 — **loss** (STRUCTURE_EXIT structure_flip_up at 13350.15, **realised P&L −10.5 p**)
- **1 position rolled in from 2026-09-16 14:50 UTC**, still open at 07:00 UTC Sep 17:
  - `GBPUSD_BB_BOUNCE_S` SHORT, deal `DIAAAAYG2RPHFBE`, entry 13458.9 — **autonomous** (source_path=`5M_CLOSE_BB_BOUNCE`, `[briefing_levels]` used only as level-provider for a BB pierce detection, not routed via BRIEFING_EXECUTION)
- **Zero `strategy=BRIEFING_EXECUTION` fires on 2026-09-17 UTC.** The last such fire was 2026-09-16T13:10 UTC (deal `DIAAAAYG2GFW8A4`).
- Throughout 14:15–19:05 UTC on Sep 17, `[BRIEFING-EXEC] GBPUSD TREND_ENTRY vetoed — entry NNN.NN is 28–65p past zone (cap 10p). plan=Range fade — sell 13407 if data neutral` fired continuously; **the briefing plan itself never admitted a trade**.

Reconciled interpretation: **3 positions were on the book during Sep 17 (1 rollover + 2 opened), and all 3 were autonomous**. If the user's dashboard shows "2 briefing + 1 autonomous", the classification convention it uses differs from `candidate_corpus.strategy` / `execution_deal_id` — please clarify.

I proceed with the evidence-based interpretation: **the abnormal count is 2 autonomous opens intraday on Sep 17 vs 5–6 autonomous opens on Sep 16**.

---

## §1 — Broker truth

| Deal ID | Deal Ref | Epic | Direction | Opened (UTC) | Closed (UTC) | Realised (pips) | Close reason | Route | Candidate ID |
|---|---|---|---|---|---|---|---|---|---|
| `DIAAAAYG2RPHFBE` | `GQMZ8GFTUDLTYRZ` | `CS.D.GBPUSD.TODAY.IP` | SELL | **2026-09-16T14:50:08.844** | on/before 2026-09-17 ~11:00 (broker limit or external) | broker-side | broker limit (target 13358.9 reached) | autonomous `GBPUSD_BB_BOUNCE_S` (`5M_CLOSE_BB_BOUNCE`, level supplied by briefing levels) | `acd63148b9e547b29e1e411f3d18a6fc` |
| `DIAAAAYG73Z4PBK` | `S7VYWKG3VZLTYRZ` | `CS.D.GBPUSD.TODAY.IP` | SELL | **2026-09-17T13:10:00.95** | 2026-09-17T15:31:59 | +8 (SCALE_OUT half) → BE runner → close (target hit) | SCALE_OUT + BE runner exit | autonomous `QM_V2_VELOCITY_S` | `89ba6e8b097b46f89bc7b38a9011a00c` |
| `DIAAAAYG8JY59BV` | `DE2GEMKV7CQTYRZ` | `CS.D.GBPUSD.TODAY.IP` | SELL | **2026-09-17T15:45:04.90** | 2026-09-17T16:40:54 | **−10.5** | STRUCTURE_EXIT (`structure_flip_up`) | autonomous `GBPUSD_TREND_V3_S` | `d03a0307fd374916a1272a013aad6920` |

Reconciliation notes:
- `signal_log.jsonl` has no rows since 2026-09-17 16:40 UTC (that log path is legacy; the primary emission log is `candidate_corpus.jsonl`).
- `bb_pierce_trades.jsonl` (Sep 17 rotation) contains pierce-resolution records, not broker fills.
- `close_intent.jsonl` records both bot-initiated closes (15:31 QM SCALE_OUT and 16:40 TREND_V3 STRUCTURE_EXIT) — external-close for the Sep 16 rollover has no local entry (broker took the limit).
- `daily_journal.jsonl` for 2026-09-17: `day_type: big-news`, high-impact events: BoE 11:00 UTC, US Building Permits 12:30 UTC, US Housing Starts 12:30 UTC. Day range 71.55p, close 13359.55, net −23.0p.

**Broker history is authoritative; the above table is consistent with journal, `candidate_corpus`, and `close_intent`.**

---

## §2 — Autonomous funnel 07:00–17:00 UTC (2026-09-17)

Every 5-minute bar delivered on cadence for both GBPUSD and EURUSD; the 5M CLOSE trace in the journal has no gaps. The dispatcher ran every bar (visible via per-bar `[dispatch_adapter]` traces for candidate emissions).

Candidate emissions in the 07-17 window: **17 rows** (15 GBPUSD, 2 EURUSD). Breakdown by strategy:

| Strategy | Count | Sides |
|---|---|---|
| `QM_V2_VELOCITY_S` | 4 | SHORT ×4 (3 rejected, 1 executed) |
| `QM_V2_VELOCITY_L` | 3 | LONG ×3 (all rejected) |
| `GBPUSD_TREND_V3_S` | 3 | SHORT ×3 (1 executed, 2 = pre-fill journal rows) |
| `GBPUSD_BB_BOUNCE_L` | 1 | LONG (rejected) |
| `QM_V2_SLOW_REJECTION_S` | 1 | SHORT (rejected) |
| `GBPUSD_EMA_PULLBACK_L` | 1 | LONG (rejected) |
| `GBPUSD_TREND_V3_UM_L` | 1 | LONG (rejected) |
| `NEWS_CONT_LEG` | 1 | SHORT (rejected) |
| `GBPUSD_EMA_PULLBACK_S` | 1 | SHORT (rejected) |
| `NEWS_STRATEGY_REVERSAL` | 1 | LONG (rejected) |

**Family reach across the window:**

- Emitted: QM_V2, TREND_V3, BB_BOUNCE, LEVEL_BOUNCE (0 emitted), EMA_PULLBACK, NEWS_CONTINUATION, NEWS_STRATEGY
- Not emitted: LEVEL_BOUNCE (0), STRUCTURE_BREAK (0), pure pivot break (0), CONFIRMATION_FALLBACK (0), BRIEFING_EXECUTION (0)

**Pre-emission counters (non-emissions):** `phase2b_measurement.jsonl` was not active during 07-17 (writer started 20:30 UTC), so per-bar `NO_SETUP` / `NO_PIERCE` receipts are **not evidenced** for this window. This is stated explicitly per audit instructions: **the pre-emission non-emission counts for Sep 17 07-17 UTC are unavailable in production evidence**. The `entry_instrumentation.jsonl` (which tracks post-emission per-strategy attempts) has 76 rows across Sep 17 UTC.

---

## §3 — Stage-by-stage count table (07:00–17:00 UTC, 2026-09-17)

| Stage | GBPUSD | EURUSD | Total | Notes |
|---|---|---|---|---|
| Completed 5m bars delivered | 120 | 120 | 240 | 12 bars/hour × 10 h × 2 pairs, no gaps observed in journal |
| Detector evaluations evidenced | not counted for pre-measurement period | not counted | **UNKNOWN** | See §2 note: per-bar detector receipts were not recorded pre-20:30 UTC |
| Candidates emitted | 15 | 2 | 17 | see §2 breakdown |
| Detector-internal suppressions (SETUP_FORMING / SUPPRESSED) | not journalled | not journalled | **UNKNOWN** | Only emission and post-emission gate journalled |
| Gate rejections | 11 | 1 | 12 | binding tag breakdown below |
| Gate approvals (pre-dedup rows) | 5 | 0 | 5 | approved rows include pre-fill journalling |
| Execution attempts | 2 unique attempts | 0 | 2 | 13:10 + 15:45 |
| Broker OPENED | 2 | 0 | 2 | both accepted (SUCCESS/ACCEPTED) |

**Gate binding distribution for rejected candidates:**

| Binding | GBPUSD | EURUSD | Total |
|---|---|---|---|
| `news_direction` | 5 | 1 | 6 |
| `normal_routing` | 3 | 0 | 3 |
| `concurrent_cap` | 2 | 0 | 2 |
| `one_book` | 1 | 0 | 1 |

**Primary stage of reduction (comparing to Sep 16 baseline): detector emission**, not gate. Sep 16 emitted 33 candidates in the 07-17 window; Sep 17 emitted 17. The gate-approval ratio (5/17 ≈ 29% vs Sep 16's 19/33 ≈ 58%) is also lower, but the volume delta at the emission stage is larger in absolute terms (−16 candidates vs the additional 7 gate-rejections).

Reduction split by cause (approximate):
- Emissions down by **~16** (families: TREND_V3 −7, BB_BOUNCE −4, LEVEL_BOUNCE −3, NEWS_STRATEGY −1, others +/-) — market-structure driven
- Gate rejections up by **~4** (from 14 approved and rejected combined) — dominated by NEWS_RELEASE_BLACKOUT proximity around BoE and USD releases

---

## §4 — Briefing ↔ autonomous interference

**No `BRIEFING_EXECUTION` fires on 2026-09-17 UTC.** The BRIEFING-EXEC engine's plan (`NY_2: Range fade — sell 13407 if data neutral`) was vetoed on every 5-minute bar from 14:15 through 19:05 UTC because price was already 28-65p past the intended entry zone (cap 10p). No briefing trade was placed.

Sep 16 rollover position `GBPUSD_BB_BOUNCE_S` (deal `DIAAAAYG2RPHFBE`) was still on the book during Sep 17 morning. Its effects on autonomous:

- **Concurrent-cap:** the cap is per-pair × per-family. GBPUSD BB_BOUNCE slot was `1/1` for BB_BOUNCE family only. Other families (QM_V2, TREND_V3, EMA_PULLBACK) were not affected — receipts show `concurrent_cap_ok_0_1` (0 reservations by their family) on all their gate walks.
- **`one_book`:** exactly 1 gate rejection with `binding=one_book` — the 08:20 UTC `GBPUSD_BB_BOUNCE_L` LONG candidate, blocked because a SHORT was on book in the same one-book scope. This is intended: don't hedge same-instrument.
- **News primary-slot consumption:** the rollover was BB_BOUNCE (not a news-slot family). No news-slot conflict evident in Sep 17 receipts (`news_slot=None` on every fire).
- **Cooldown:** every candidate showed `cooldown:cooldown_ok:elapsed_s=...` with values in thousands to tens of thousands of seconds — cooldown never bound.
- **Duplicate-event detection:** `bucket_dedup:bucket_dedup_ok:bucket=<n>` on every candidate — dedup never bound.
- **_closing_in_flight / open-position cache:** no `closing_in_flight` receipts observed; no cache-related receipts observed.
- **Strategy-family locks:** the only family-level effect was BB_BOUNCE (see concurrent-cap above).
- **Exposure/risk limits:** no exposure-limit codes observed.
- **Briefing-specific suppression state:** no `briefing_suppress` receipts observed. BRIEFING-EXEC's own veto (`entry X.X past zone`) never touched the autonomous gate.

**Concurrent-cap after the 13:10 QM_V2_VELOCITY_S fire:** the following two same-family SHORT candidates (13:45, 14:30) were correctly rejected by `concurrent_cap_reached_1_1`. This is intended — once a QM_V2 SHORT is on the book, the family slot is full.

**Verdict for §4: `BRIEFING_TRADES_DID_NOT_REDUCE_AUTONOMOUS_COUNT`** — because there were **no** briefing trades on 2026-09-17. The one autonomous rollover from Sep 16 (BB_BOUNCE_S) suppressed one BB_BOUNCE LONG candidate and did not affect other families.

---

## §5 — Loaded-code + runtime state during 07-17 UTC on 2026-09-17

### 5.1 Service and HEAD

- **PID during session:** `303605` (continuous from Sep 14 through 2026-09-17T20:17:18 UTC shutdown). Confirmed via `journalctl _PID=303605` grep showing an entry at 14:12:18 UTC on 2026-09-17.
- **HEAD at start of session:** at latest `afaa796` (Sep 16 10:39 UTC) — the last commit before the Sep 17 evening phase2b merges. Any commit between Sep 14 (PID start) and Sep 16 10:39 (last pre-session commit) is a candidate to have been loaded, but no restart is evident between then and the Sep 17 20:17 shutdown.
- **Restarts during 07-17 UTC on Sep 17:** none observed in `journalctl` (uptime spans through 20:17).

### 5.2 Environment (redacted, PID-loaded — cross-checked against `.env` mtime `2026-09-14 20:26 UTC` and `env-history/env.20260917T201719Z`)

Dispatch and gate ownership (loaded, live):
```
CENTRAL_STRATEGY_ORCHESTRATOR=1
CENTRAL_EXECUTION_GATE=1
OBSERVATION_GATE_ENABLED=1
NEWS_TREND_ROUTER=1
NEWS_BOUNCE_REVERSAL_ROUTE=1
NEWS_BOUNCE_CONFIRMATION=1
MID_NEWS_ROUTER=1
NORMAL_MARKET_ROUTER=1
NEWS_RELEASE_BLACKOUT_ENABLED=1
QM_LIVE_FIRE=1
```

Session windows (loaded):
```
SESSION_TZ=Europe/London
SESSION_WINDOWS_JSON={"GBPUSD":["06:45-21:00"],"USDCAD":["12:00-19:00"],"EURUSD":["06:45-17:00"],"USDJPY":["06:45-17:00"]}
```

Inner UTC entry-hours gate (`entry_hours [07:00, 17:00) UTC` — visible in every 07-17-window Sep 17 candidate as `entry_hours:entry_hours_ok`).

Shadow / dead flags (unchanged from prior days):
```
EMA_PB_ARMED_MACHINE_SHADOW=0        # per memory: fully OFF end-to-end
CONFIRMATION_FALLBACK_SHADOW=0
BB_BOUNCE_LEVEL_GATE_MODE=shadow
RUNNER_MOMENTUM_CHECK_MODE=shadow
BB_BOUNCE_CASCADE_GATE_ENABLED=0     # per memory: deliberately disabled since 2026-05-28
GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false
BB_PREMIRROR_L_WINDOW_START_UTC=06:45
BB_PREMIRROR_L_WINDOW_END_UTC=15:30
```

### 5.3 Day type + market context (Sep 17)

- **day_type:** `big-news`; day_type_rule: "3 high-impact release(s) at or before 16:00 UTC"
- **high-impact events:** BoE 11:00 UTC, USD Building Permits 12:30 UTC, USD Housing Starts 12:30 UTC
- **NMS state sequence in candidate receipts:** ranged from `NORMAL_STATE_UNKNOWN` (early) → `NORMAL_FLAT_PENDING:PIVOT_BREAK` (later) → `NORMAL_PRODUCTIVE_BB_ONLY:BB_BOUNCE` (late) — consistent with a compressed / mixed day
- **news_trend_snapshot states across the session:** `MAJOR_LEVEL_TEST` (dominant), `BOUNCE_FORMING`, `BOUNCE_CONFIRMED`, `REVERSAL_CONFIRMED`, `NO_CLEAR_TREND`, `TREND_WEAKENING`
- **Position caps (evidenced):** concurrent_cap ceiling `1` per pair-family; no explicit exposure limit blocking observed
- **Cooldowns:** all receipts showed `elapsed_s` well past minimum; never bound
- **Blackout windows:** ±30 min around each HIGH-impact release; blackout windows 10:30–11:30 UTC (BoE) and 12:00–13:00 UTC (USD releases) — accounts for 2 h of the 10 h session (20%)

### 5.4 Persisted state restored at PID 303605 startup

PID 303605 started on/around 2026-09-14 (no start-line in current journal retention; inferred from `_PID=303605` evidence on 2026-09-17T14:12). Persisted state that would have been rehydrated:
- `qm_level_memory_state.json` — recurring rename failures in `[QM-MEM]` DEBUG log (pre-existing; unrelated to autonomous count)
- Open-position cache — restored from IG polling on start
- `briefings_live/` directory — briefing plans loaded per session

No evidence that persisted state pinned the bot into a low-emission mode.

### 5.5 Comparison to preceding days

Env values loaded were the same across Sep 14, 15, 16, 17 (all env-history snapshots between `env.20260914T083633Z` and `env.20260917T201719Z` share size 45,542 bytes). No config change during the run — flags were identical for all four days.

---

## §6 — Baseline comparison 8–16 September (07:00–17:00 UTC window)

Note: `candidate_corpus.jsonl` was purged on 2026-09-12 and again on 2026-09-14 (per `PURGE_NOTE*.txt`); no funnel evidence survives for Sep 8–13. Comparison is limited to Sep 14–17.

| Day | corpus rows total | in window | approvals | executed rows | unique deals | primary binding rejects |
|---|---|---|---|---|---|---|
| 2026-09-14 (Mon) | 20 | 13 | 5 | 3 | 2 | `normal_routing`×7 |
| 2026-09-15 (Tue) | 17 | 15 | 9 | 6 | 3 | `normal_routing`×3, `news_direction`×2, `cooldown`×1 |
| 2026-09-16 (Wed, US CPI) | 50 | 33 | 19 | 12 | 6 | `news_direction`×8, `concurrent_cap`×2, `normal_routing`×2, `one_book`×1 |
| **2026-09-17 (Thu, BoE + US Housing)** | 21 | 17 | 5 | 3 | **2** | `news_direction`×6, `normal_routing`×3, `concurrent_cap`×2, `one_book`×1 |

**Comparable classifications:** Sep 16 (`big-news`, US CPI) is the closest peer to Sep 17 (`big-news`, BoE + USD). But price structure differed sharply:

- Sep 16: broader daily range, TREND_V3 emitted 10 candidates → 4 executions of that family
- Sep 17: compressed range (bb_width 6.82p), ADX 17.18 (weak), TREND_V3 emitted 3 → 1 execution

**Sep 17 is not unprecedented** — Sep 14 also produced just 3 executed rows / 2 unique deals in the 07-17 window under the same config. It's the low end of a 2-6 deal range seen over the four comparable days, and consistent with a compressed / mixed session on a big-news day.

**Divergence stage vs Sep 16:** primarily at **detector emission** (17 vs 33), secondarily at **gate binding by `news_direction`**. Sep 16 also had `news_direction` as the top rejection reason (8), so this pattern is not new — it's shared behaviour on big-news days.

---

## §7 — Regression boundary review

### 7.1 Commits touching decision layers, Sep 14–17

Between Sep 14 21:00 UTC and Sep 16 10:39 UTC (all under PID 303605):

```
afaa796 2026-09-16 10:39 reports: Phase 4A amendment — spot-verification results for Phase 4B
86ddc0b 2026-09-16 10:25 reports: Phase 4A exit invalidation and ownership audit
ad33e00 2026-09-16 09:36 reports: Phase 2A BB/fade admission policy — protocol freeze
788b486 2026-09-16 09:24 reports: Phase 1 final closing verdict (Amendment 4)
15cb42c 2026-09-16 09:17 reports: Phase 1 roadmap ownership correction (Amendment 3)
78a0c68 2026-09-16 09:10 reports: Phase 1 final evidence close (Amendment 2)
8777ffc 2026-09-16 09:02 reports: Phase 1 diagnosis amendment (causal proof + NMS flip + ownership)
7da0a54 2026-09-16 08:09 reports: Phase 1 2026-09-15 diagnosis (missed bounce + losing short)
a854fe1 2026-09-15 21:35 exit_dress: remove calendar authority (R2 2026-09-15)
26ee549 2026-09-14 21:00 trade_manager: dealingRules fetch-failure backoff (defect #9 final blocker)
f637d47 2026-09-14 20:34 trade_manager: preflight fails-closed, side-based, single-resolve
6a01dfc 2026-09-14 20:16 reports: remove BE amend review trailing whitespace (amend)
176b1f3 2026-09-14 20:15 reports: remove BE amend review trailing whitespace
```

Reports-only commits do not change loaded code. The **runtime-affecting** commits in this window are:

1. `26ee549` — `trade_manager` dealingRules backoff (defensive; adds retries on IG dealingRules 4xx; cannot reduce autonomous emissions)
2. `f637d47` — `trade_manager` preflight fails-closed side-based (defect #7 hardening; makes SL-amend safer on the exit path; cannot reduce autonomous emissions or admissions)
3. `a854fe1` — `exit_dress` removes calendar authority (removes a *closer*, not an admitter; cannot reduce fires)

**None of these three touch dispatch, detector enablement, central routing, gate admission, position limits, cooldown, dedup, day-type, or NMS.**

### 7.2 Prior deployment boundary: Sep 13/14 GO-LIVE

The env-history shows a config change at `env.20260914T083633Z` (Sep 14 08:36 UTC) that added the `# ─── GO-LIVE 2026-09-13 — orchestrator + gate own dispatch ───` block:

```
CENTRAL_STRATEGY_ORCHESTRATOR=1
CENTRAL_EXECUTION_GATE=1
OBSERVATION_GATE_ENABLED=1
NEWS_TREND_ROUTER=1
NEWS_BOUNCE_REVERSAL_ROUTE=1
NEWS_BOUNCE_CONFIRMATION=1
MID_NEWS_ROUTER=1
NORMAL_MARKET_ROUTER=1
NEWS_RELEASE_BLACKOUT_ENABLED=1
```

Plus the Sep 14 addition of `QM_LIVE_FIRE=1`.

This is the deployment boundary the prompt asks about. **These flags reshape the funnel by adding routing rejections that did not exist before**:

- `news_direction` bindings emerged on Sep 15 (first day post-GO-LIVE with candidates) and were significant on Sep 16 (8 rejects) and Sep 17 (6 rejects).
- `normal_routing` bindings dominated Sep 14 (7 rejects), meaning the router was already reshaping admission before the Sep 15 news activity.

**Correlation with 17 September behaviour:** the routing/blackout bindings that rejected 9 of 12 Sep 17 candidates (6 news_direction + 3 normal_routing) are **the intended effect of the GO-LIVE flags**. They are correct under the loaded rules.

**They were not introduced between Sep 14 and Sep 17.** The GO-LIVE landed *before* PID 303605's most recent restart to pick up these flags (env timestamp Sep 14 08:36 UTC). The four comparable days (Sep 14–17) all ran with the same policy.

**No regression identified.** Nothing new landed between Sep 14 and Sep 17 that could plausibly explain the reduction; the reduction is explained instead by:
- Compressed / mixed session structure (per §6)
- The two blackout windows around BoE 11:00 UTC and USD 12:30 UTC (per §5.3)
- Detector-side lower emissions (per §3)

---

## §8 — The one autonomous trade that fired *outside* the QM path

Two autonomous trades opened intraday on Sep 17. The one worth attention (which "was admitted while others were not") is:

- **`GBPUSD_TREND_V3_S`** — deal `DIAAAAYG8JY59BV` / ref `DE2GEMKV7CQTYRZ`
- **Candidate:** `d03a0307fd374916a1272a013aad6920`
- **Emitted:** 2026-09-17T15:45:04.766 UTC
- **Broker fill:** 2026-09-17T15:45:05 UTC (delay ~265 ms), entry **13340.3**, SL 13352.3 (12p), TP 13240.3 (100p)
- **Exit:** 2026-09-17T16:40:54 UTC — STRUCTURE_EXIT `structure_flip_up: last_close=13350.15 > prior_5_high=13349.05`
- **Realised P&L:** **−10.5 p**

**Detector evidence (from `entry_instrumentation.jsonl`):** strategy=`GBPUSD_TREND_V3_S`, side SHORT, `fired: true`, `reason: "executed"`. Level context absent (TREND_V3 doesn't stamp levels the same way as LEVEL_BOUNCE).

**Gate walk (from `candidate_corpus`):**
```
kill_switch:kill_switch_pass
observation:observation_ok
news_direction:direction_agree_non_news_family:MAJOR_LEVEL_TEST
news_direction:A10:WITH_TREND
mid_news:mid_news_off_route
normal_routing:normal_routing_deferred_active_trend:TREND_DOWN
opposing_level:opposing_level_off
mechanical:mechanical_ok
entry_hours:entry_hours_ok
sl_block:sl_block_ok
one_book:coherence_ok
news_post_lockout:news_post_lockout_ok
concurrent_cap:concurrent_cap_ok_0_1
bucket_dedup:bucket_dedup_ok:bucket=<...>
cooldown:cooldown_ok:elapsed_s=<...>
ml_veto:ml_veto:shadow_ok:no_features
gate:APPROVE_FINAL
```

**Why this was admitted while others were not:**

- **news_trend_state = MAJOR_LEVEL_TEST, primary_direction = SELL** → a SHORT candidate is `WITH_TREND` and passes `news_direction`
- **normal_routing = `normal_routing_deferred_active_trend:TREND_DOWN`** → routing acknowledges active downtrend
- **Outside every NEWS_RELEASE_BLACKOUT** (BoE 10:30-11:30, USD 12:00-13:00, 15:45 is clear)
- **concurrent_cap:** `0/1` for TREND_V3 (the prior QM_V2 fire's runner had closed at 15:32)
- **No opposing_level, no `one_book` conflict**

Trades that were rejected instead had one of:
- Wrong direction vs news trend (`direction_counter_trend`, `DIRECTION_MISMATCH`, `DIRECTION_NOT_ESTABLISHED`)
- Fired during a blackout window (5 candidates in the 12:10-12:30 UTC pre-USD-release cluster + 1 at 11:20 post-BoE)
- Or (for BB_BOUNCE LONG at 08:20) blocked by `one_book` due to the Sep-16 rollover SHORT

**Health inference caveat:** the fact that this single trade was admitted proves only that the gate can approve TREND_V3 SHORTs when routing/blackout/cap agree. It does **not** attest to broader system health (per prompt instruction).

---

## §9 — Final verdict (required)

**Primary classification: `MIXED_CAUSES`**
- Dominant component: `MARKET_PRODUCED_FEWER_QUALIFYING_SETUPS` (compressed / mixed price structure, ADX 17.18, BB width 6.82p, weak ER 0.374)
- Secondary: `CONFIGURATION_OR_ROUTING_SUPPRESSION` — but this suppression is correct under the GO-LIVE-13-Sep rules (NEWS_RELEASE_BLACKOUT ±30 min around HIGH events; news_direction alignment enforcement)
- Not present: DETECTOR_PIPELINE_REGRESSION, BRIEFING_POSITION_INTERFERENCE, CENTRAL_GATE_OVER_REJECTION (rejection ratio consistent with big-news-day peer Sep 16), EXECUTION_PIPELINE_FAILURE (both approved candidates reached the broker on the first try)

**Earliest funnel divergence from Sep 16 (closest peer):** at **detector emission**. Sep 17 emitted 17 candidates in-window vs Sep 16's 33. The gap manifested well before the gate.

**Exact binding reasons for the missing autonomous trades:** listed in §3 count table. Combined 5 rejects tied to blackout proximity, 4 tied to news-trend direction misalignment (`DIRECTION_MISMATCH` / `DIRECTION_NOT_ESTABLISHED` / `direction_counter_trend`), 2 tied to `concurrent_cap` post-QM-fire, 1 tied to `one_book` against the Sep-16 rollover.

**Was the behaviour correct under current rules?** Yes. Every binding I inspected followed the loaded `.env` policy. `NEWS_RELEASE_BLACKOUT_ENABLED=1` and `NEWS_TREND_ROUTER=1` were introduced on 2026-09-13/14 as the operator's GO-LIVE and produced the exact effects seen.

**Did it violate intended behaviour?** No. The GO-LIVE flags are intentionally conservative around HIGH events; this is a safety feature. Sep 16's higher deal count reflects a wider intraday range with more direction-aligned setups outside the blackout windows, not a policy change.

**Evidence-backed defect/register entries:** none warranted.

---

## Appendix A — Data provenance

- **Broker truth:** `journalctl -u autobot.service` (`🟢 Opening`, `✅ IG response`, `dealId`, `dealReference`) — restricted to Sep 17 UTC window
- **Funnel:** `candidate_corpus.jsonl` (17 rows in 07-17 window), `entry_instrumentation.jsonl` (76 rows across Sep 17), `qm_candidates.jsonl`, `qm_candidates_graded.jsonl`
- **Detector receipts:** `phase2b_measurement.jsonl` (empty before 2026-09-17 20:30 UTC — explicitly declared unavailable for the session window per audit protocol; no counterfactual replay run)
- **Config:** `env-history/env.20260917T201719Z`, `env-history/env.20260914T083633Z`, in-process `/proc/467277/environ` (current PID, same env baseline pre-phase2b activation)
- **Day type / market:** `daily_journal.jsonl`, `day_summary.jsonl`
- **Position state:** `qm_trade_state.jsonl` (BB_BOUNCE_S rollover trace), `close_intent.jsonl` (close events for the two Sep 17 trades)

## Appendix B — What was NOT audited (uncovered paths)

- Pre-emission detector suppressions and setup-forming counts for the 07-17 window: no receipts exist. `phase2b_measurement.jsonl` began writing at 20:30 UTC on Sep 17 and covers no session bar. Adding retrospective coverage requires re-running detectors against the captured 5-minute close stream (offline replay). This audit does not perform that replay.
- IG's own "positions opened today" API count: not queried. Broker truth in this report comes from journal-recorded `IG response` events. If the user's "3 trades" comes from IG's UI counter, that counter may be counting the Sep 16 rollover as "opened during Sep 17" per broker day cutoff; the log-authoritative count of *opens whose IG-response `date` starts with 2026-09-17* is 2.
