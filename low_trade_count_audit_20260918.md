# Low-Trade-Count Audit — 2026-09-18 (diagnosis only)

**Status:** DIAGNOSIS ONLY. No fix, restart, configuration, or trading-policy change proposed.
**Author:** autobot session, 2026-09-18 ~06:30 UTC
**Question posed:** Did the Phase 2B measurement apparatus (or any code deployed today) interfere with AutoBot trading?

---

## Executive verdict

**Measurement interference verdict: `NO_EVIDENCE_OF_MEASUREMENT_INTERFERENCE`.**

**Low-trade-count classification: `no qualifying setups` (with a component of `configuration suppression` from the [07:00, 17:00) UTC entry-hours gate; the audit window this morning was almost entirely pre-market).**

**Key qualifier — premise correction.** The audit statement "only one trade executed" does not match the log evidence. Under the current measurement-enabled process (PID 467277, started 2026-09-17 20:28:32 UTC, ~10 hours before this audit), **zero broker opens have occurred**. The only "one" the phrase can refer to is either:

- the sole *candidate emission* since the restart (2026-09-18 01:10:04 UTC, `GBPUSD_PIVOT_BREAK_S` SELL, **rejected by the gate**, `executed:false`), or
- the last *executed* trade before the restart — 2026-09-17 13:10:00 UTC, deal `S7VYWKG3VZLTYRZ`, GBPUSD SELL, **profitable** (target_first=True, mfe=15.2p, mae=10.6p) — which was placed under the *previous* PID with measurement OFF.

Neither maps to "one trade executed today with a realised loss." I inspect both candidates for completeness and report them explicitly.

---

## §1 — Production scope

| Item | Value |
|---|---|
| Production HEAD (git) | `221b378` (`feat/trend-stretch-brake-adx-floor`) |
| Service | `autobot.service` (systemd) |
| Loaded PID | `467277` |
| Process start | `Thu 2026-09-17 20:28:32 UTC` (`ExecMainStartTimestamp`, `MainPID=467277`, `SubState=running`, `NRestarts=0`) |
| Uptime at audit | ~10 h |
| Threads | 34 (`/proc/467277/task`) |
| .env `PHASE2B_MEASUREMENT_ENABLED` | `1` (in-process env matches file; file mtime `2026-09-17 20:26`, 2 min before PID start) |
| Other measurement flags | `EMA_PB_ARMED_MACHINE_SHADOW=0`, `CONFIRMATION_FALLBACK_SHADOW=0`, `RUNNER_MOMENTUM_CHECK_MODE=shadow`, `BB_BOUNCE_LEVEL_GATE_MODE=shadow` (unchanged since previous session) |

### Commits loaded since the previous known-good trading session

The previous session under HEAD `afaa796` (2026-09-16 10:39) ran continuously until the 2026-09-17 20:17:18 stop. Between then and PID 467277's start, HEAD advanced through the Phase 2B increment sequence to `221b378`.

Production-source files touched (excluding tests/reports/scripts/spec):

```
bb_pierce_recorder.py
candle_builder.py
gbpusd_level_bounce.py
measurement_writer.py                          (new)
native_5m_source.py
phase2b_inc2_counterfactual_predicates.py      (new, no wired reader — shadow only)
phase2b_inc2_ownership_adapter.py              (new)
phase2b_inc3_level_bounce_adapter.py           (new)
trade_manager.py
.gitignore
```

Total: 49 files, +14,440 / −6 lines (majority is reports-public/tests/scripts, not production).

### Replay / comparator / report commits are outside the trading path

- The Phase 2B increment commits either add strictly-additive measurement hooks (`bb_pierce_recorder`, `candle_builder`, `gbpusd_level_bounce`, `native_5m_source`, `trade_manager`) or add new observer modules that log to `phase2b_measurement.jsonl` without mutating trading state.
- The `measurement_writer` module writes on a separate daemon thread via `put_nowait`; on queue-full the producer *drops and returns False* rather than blocking (design ref: `phase2b_async_writer_architecture_20260917.md`; code ref: `measurement_writer.py:16, :140, :157, :167`).
- No changes to strategy detectors' emit/suppress logic, gate binding, execution path, or management path were merged in this window.

### Service restarts, disconnects, subscription gaps, reconciliation

Journal window `2026-09-18 00:00:00 → now` (audit time):

- `NRestarts=0`, no `systemd[1] Stopping|Started` lines
- No `Lightstreamer DISCONNECTED|reconnect|resubscribe` events
- No worker `stopped`, no dropped-tick spikes (background counters healthy — `dropped_ticks=0` since restart per REST-SWEEP heartbeats)
- REST-sweep loop reported `errors=0` continuously (`external-close invocations` monotonically climbing 1270→2480+, `avg_dur=~0.05s`)

No service or data interruption identified in the audit window.

---

## §2 — Opportunity funnel for 2026-09-18 (UTC)

### 2.1 Bar-close delivery — GBPUSD and EURUSD

From journalctl (`[5M CLOSE]` markers):

- **Zero missed 5-minute bars** for either symbol between `2026-09-18 00:00:00` and `2026-09-18 06:25:00` UTC (78 unique `bar_ts_utc` values in `phase2b_measurement.jsonl`, expected 78, missing 0).
- Callback delivery latency (from `bar_ts + 5min` to observation `event_ts`):
  - `gbpusd_level_bounce`: n=121 min=1.21s p50=2.88s avg=3.78s max=16.00s
  - `bb_pierce_recorder`: n=121 min=1.28s p50=3.11s avg=3.93s max=16.06s
- Both are well within the 300-second (5-min) bar boundary; no late callbacks caused a subsequent bar to be dropped.

### 2.2 Detector evaluations — measurement ledger (`phase2b_measurement.jsonl`)

Every 5-minute bar since restart produced **exactly two** `DETECTOR_EVAL` rows (one from each measurement source). 158 rows for 2026-09-18.

| source_module   | rows | family        |
|-----------------|------|---------------|
| gbpusd_level_bounce | 79 | LEVEL_BOUNCE |
| bb_pierce_recorder  | 79 | BB_BOUNCE    |

*(2 sources × 12 bars/hour × ~6.6 h = ~158, matches exactly.)*

| detector_state | count |
|---|---|
| NO_SETUP_NO_PIERCE_OR_NO_CONFLUENCE (LEVEL_BOUNCE) | 79 |
| NO_PIERCE (BB_BOUNCE)   | 64 |
| PIERCE_UPPER (BB_BOUNCE) | 9 |
| PIERCE_LOWER (BB_BOUNCE) | 6 |

**Emitted = false for all 158 measurement rows.** All rows carry `source_class:"PRODUCTION_OBSERVED"` and `write_flush_visible:true`. Non-emission reasons are the expected `no_setup:no_pierce_or_no_confluence` (LEVEL_BOUNCE, all bars) and `no_setup:no_pierce_this_bar` (BB_BOUNCE, when no pierce occurred).

Hourly cadence (rows/hour):
```
00: 24    01: 24    02: 24    03: 24    04: 24    05: 24    06: 14 (partial)
```
Perfectly uniform, consistent with 2 evaluations × 12 bars.

### 2.3 SETUP_FORMING / SUPPRESSED / EMITTED (any source)

- **SETUP_FORMING**: none observed across any log for GBPUSD or EURUSD today
- **SUPPRESSED**: none observed
- **EMITTED**: 1 candidate (see 2.4)
- **SETUP by measurement observer**: 15 BB_BOUNCE `PIERCE_UPPER/LOWER` rows (setup-like) — none emitted because pierce alone is not sufficient (production detector requires confluence + rejection)

### 2.4 Candidate corpus (`candidate_corpus.jsonl`)

**One candidate row for 2026-09-18:**

| field | value |
|---|---|
| ts | `2026-09-18T01:10:04.559774+00:00` |
| candidate_id | `3ac4af2aac4b48e6a1b451c1c7741a6a` |
| strategy | `GBPUSD_PIVOT_BREAK_S` |
| strategy_family | `PIVOT_BREAK` |
| side | `SHORT` |
| candidate_price | `13358.45` |
| gate_allowed | `False` |
| executed | `False` |
| source_path | `5M_CLOSE_PIVOT_BREAK` |

### 2.5 Gate approvals / rejections (binding reason)

The one candidate was rejected with:
```
gate:REJECT:binding=normal_routing
```
and additional non-binding blocks recorded:
```
entry_hours:entry_hours_blocked:hour=1:window=[7,17)
news_direction:news_no_active_trend:TREND_FORMING
normal_routing:NORMAL_FLAT_PENDING:PIVOT_BREAK
```

The trading-window gate (`entry_hours [07:00, 17:00) UTC`) alone would have blocked this candidate; the current audit falls almost entirely inside that pre-window band.

### 2.6 Execution attempts / broker ACKs / executed positions

- **Execution attempts**: 0 (no `🟢 Opening`, no `IGService.create_open_position()` calls in journal since `2026-09-17 20:28:32`)
- **Broker ACKs**: 0
- **Executed positions**: 0
- Cross-reference: `bb_pierce_trades.jsonl` shows `live_bot_fired=false` on all 2026-09-18 rows

### 2.7 Ledger reconciliation

| Metric | Detector logs / measurement | Candidate corpus | Signal log | Broker |
|---|---|---|---|---|
| 5m bars processed | 78 (2026-09-18 UTC) | n/a | n/a | n/a |
| Detector evals | 158 | 1 (emitted) | 0 | 0 |
| Gate rejections | n/a | 1 (binding=`normal_routing`) | 0 | 0 |
| Execution attempts | n/a | 0 | 0 | 0 |
| Broker OPENED | n/a | 0 | 0 | 0 |

Counts are internally consistent. `signal_log.jsonl` last mtime is 2026-09-17 16:40 UTC — no rows since restart; consistent with zero emissions taking that specific code path.

---

## §3 — The "one" trade / candidate

Two possible referents for "the one trade":

### 3a) The one candidate emitted under the current measurement-enabled PID

- **candidate_id:** `3ac4af2aac4b48e6a1b451c1c7741a6a`
- **ts:** `2026-09-18T01:10:04.559774+00:00`
- **strategy_family:** PIVOT_BREAK
- **direction:** SHORT (metadata.decision_signal=SELL; primary_direction=BUY refers to structural trend)
- **detector evidence:** `pivot_break_sell`, structure=BULLISH (HH/HL swings), news_trend_state=`TREND_FORMING`, normal_market_state=`FLAT_OR_COMPRESSED`
- **gate walk (17 reason codes):**
  ```
  kill_switch:kill_switch_pass
  observation:observation_ok
  news_direction:news_no_active_trend:TREND_FORMING
  news_direction:A10:NO_ACTIVE_TREND
  mid_news:mid_news_off_route
  normal_routing:NORMAL_FLAT_PENDING:PIVOT_BREAK   ← binding
  opposing_level:opposing_level_off
  mechanical:mechanical_ok
  entry_hours:entry_hours_blocked:hour=1:window=[7,17)
  sl_block:sl_block_ok
  one_book:coherence_ok
  news_post_lockout:news_post_lockout_ok
  concurrent_cap:concurrent_cap_ok_0_1
  bucket_dedup:bucket_dedup_ok:bucket=5965646
  cooldown:cooldown_ok:elapsed_s=30545
  ml_veto:ml_veto:shadow_ok:no_features
  gate:REJECT:binding=normal_routing
  ```
- **Entry / exit / P&L:** N/A — candidate was rejected before execution. `entry_instrumentation.jsonl` row confirms `fired:false`, no `EXECUTION_PRICE`, no `EXECUTION_TS`.
- **Measurement-hook effect on this candidate:** none. Measurement adapters (BB_BOUNCE, LEVEL_BOUNCE) are shadow observers that write rows and return; they do not touch PIVOT_BREAK, do not participate in the gate walk, and do not mutate candidate fields. The measurement rows corresponding to bar `01:05:00+00:00` show `emitted:false, source_class:PRODUCTION_OBSERVED`, and their evaluation timestamps (`01:10:04.748`, `01:10:04.861`) sit *after* the candidate's `first_detected_ts` (`01:10:01.484566`), so ordering rules them out as antecedents of the candidate decision.

### 3b) The last actual executed trade (occurred before measurement was activated)

Most-recent qm-graded execution (only executed trade in the graded log for the recent window):

- **deal_ref:** `S7VYWKG3VZLTYRZ`
- **opened_at:** `2026-09-17T12:35:00+00:00`
- **broker OPEN ACK date (from IG response):** `2026-09-17T13:10:00.95`
- **symbol:** GBPUSD, side SHORT, size 2.0
- **entry / stop / target:** 13377.25 / 13388.55 / 13362.25 (11.3p SL, 15p TP)
- **outcome:** `target_first=True`, mfe=15.2p, mae=10.6p — **profitable** exit, not a loss
- **gate at fire:** `gate:APPROVE_FINAL`, `entry_hours_ok`, `news_direction:direction_agree_non_news_family:MAJOR_LEVEL_TEST`
- **confidence:** band=very_strong, total_score=12/12

**Measurement-hook effect on this trade:** none. Trade fired at 13:10 UTC on 2026-09-17 under **the previous PID**. The measurement ledger (`phase2b_measurement.jsonl`) contains **0 rows before 2026-09-17 20:28** (`first Sep 17 row event_ts: 2026-09-17T20:30:03.412812+00:00`). The writer was not active when this trade fired.

Neither referent matches "realised loss." No other executed trade appears in the graded log for the recent window.

---

## §4 — Direct measurement-interference tests (production evidence)

| Test | Evidence | Result |
|---|---|---|
| Escaped exceptions / tracebacks at measurement call sites | `journalctl -u autobot.service --since '2026-09-17 20:28:00' -o cat \| grep -iE 'traceback\|exception\|error'` (filtered for signal) shows only the pre-existing `[QM-MEM] state save failed` (DEBUG, unrelated to phase2b), the pre-existing `morning_briefing EURUSD/London` levels-validation warnings (unrelated to phase2b), and `[dispatch_adapter] LIVE gate rejected` for the 01:10 candidate. **No `measurement_writer`, `phase2b`, `MW-QUEUE`, `FSYNC_FAIL` lines at any log level.** | PASS |
| Writer queue depth | Writer stats not surfaced to the journal by the running code (`grep -iE 'measurement_writer\|MW-QUEUE\|PHASE2B'` returns 0 hits). Indirect evidence: expected 158 rows for the period, observed 158 rows, all with `write_flush_visible:true`. | PASS (indirect) |
| `dropped_queue_full` | No `[measurement_writer:...]` DEBUG lines emitted (`_warn_ratelimited` at DEBUG level — DEBUG is enabled globally per `[REST-SWEEP]` / `[QM-MEM]` DEBUG output visible in journal). | PASS (no drops) |
| `dropped_invalid` | Same — no writer DEBUG lines. | PASS |
| `write_failures` | Same, plus every observed row has `write_flush_visible:true`. | PASS |
| `fsync_failures` | Same. | PASS |
| Worker restarts | Writer worker uses `threading.daemon=True`; no observable restart events (indirect: uniform cadence with zero missed rows). | PASS (indirect) |
| Callback duration before vs after measurement activation | Same PID from the start — no "before" available in this PID. Cross-run: p50 lag from `bar_ts+5min` to observation event is ~3 s across all 121 measured bars, uniformly distributed; no visible ramp/degradation over time. | No degradation observed |
| Late or missed 5-minute callbacks | 78/78 expected bars accounted for; max lag 16 s (well under 300 s bar boundary). | PASS |
| Detector or management state mutations attributable to observation | Static reading of `measurement_writer.py` (producer path lines 660-745): pipeline is `redact → json.dumps → put_nowait → return bool`. No mutation of caller state. Similarly for `phase2b_inc3_level_bounce_adapter`, `phase2b_inc2_ownership_adapter`: they *read* from adapter snapshots and *write* to the queue. No `return`, `raise`, or mutation of decision structures. | No mutations found |
| Malformed candle payloads or consumer unpacking errors | Zero unpack tracebacks in the journal. All 78 `[5M CLOSE]` events show numeric OHLC + tick count. `[dispatch_adapter]` accepted the one candidate for gate evaluation without complaint. | PASS |
| Change in broker open/amend/close call count | Broker calls since restart: 0 open, 0 amend, 0 close. Prior PID (last ~24 h before restart): 3 opens visible in earlier journal window. Change is consistent with an entry-hours-blocked overnight audit window, not with instrumentation. | Consistent with market hours |
| Measurement records misclassified as production decisions | All 158 rows have `source_class:"PRODUCTION_OBSERVED"` (this field is defined in the ledger to mean "the production detector saw this bar and made this evaluation"; it is not routed through the emit path — `emitted:false` for all). The candidate at 01:10 is a *separate* PIVOT_BREAK strategy row in `candidate_corpus.jsonl` written by the emit path, not by measurement. No cross-contamination. | PASS |

---

## §5 — Counterfactual OFF-path replay

**Not run. Uncovered path stated per audit protocol.**

An offline, network-blocked replay of today's captured inputs with `PHASE2B_MEASUREMENT_ENABLED=0` versus `=1`, producing byte-diff evidence over detector outputs / candidate IDs / gate dispositions / execution intents / management decisions / close reasons / broker payloads, was **not** executed for this audit because:

1. No pre-built replay harness capable of driving `autobot.py` with today's actual tick + 5m-close inputs and toggling `PHASE2B_MEASUREMENT_ENABLED` between runs is present in the tree (`scripts/` contains per-module test scripts and a bar-replay for isolated detectors, but not a full production-pipeline replay of a session's live inputs).
2. Building such a harness would itself require handling wall-clock timing, live-only side effects (LS subscription, IG session, calendar refresh), and deterministic seed control across ~10 h of session data — a substantial engineering effort outside the scope of a diagnostic audit.

**Uncovered path:**

- No byte-for-byte proof that `phase2b_measurement.jsonl` emit sites are non-mutating under adversarial timing (only static-read and log-evidence proof).
- No proof-by-experiment that the writer's `put_nowait` never returned False for any evaluation today (only "159 rows expected, 158 rows observed, no DEBUG queue-full lines" — indirect).
- No demonstration that the daemon writer thread has not been blocked/preempted long enough to distort producer p99 latency in a way that shifted any decision (never observed one being made under measurement, so no counterfactual anyway).

**Static-code and log-evidence substitutes** for these paths:

- `measurement_writer.py:16, :140, :157, :167` — non-blocking put_nowait; drop-on-full; single daemon consumer.
- `phase2b_inc3_level_bounce_adapter.py`, `phase2b_inc2_ownership_adapter.py` — adapters read snapshot values and enqueue; no return path back into detector state.
- `journalctl` under DEBUG level shows no `measurement_writer` warnings across 10 h uptime.
- All 158 expected measurement rows drained to disk (`write_flush_visible:true`), 0 gaps.

If the operator wants a full ON-vs-OFF replay under captured inputs, that is a stand-alone follow-up work item (build tick-and-5m-close replay driver, mocked IG/LS layers, deterministic clock injection). It is not part of this audit.

---

## §6 — Verdicts

- **Measurement interference: `NO_EVIDENCE_OF_MEASUREMENT_INTERFERENCE`**
  - No exceptions, no writer failures, no missed callbacks, no queue-drops observed
  - No mutation path from measurement to production decisions in static reading
  - Ordering evidence for the one candidate rules out any observer-influence
- **Low-trade-count classification: `no qualifying setups`, with contributory `configuration suppression`**
  - Audit window (00:00–06:26 UTC) was mostly pre-`entry_hours` window `[07:00, 17:00)` UTC
  - Only one candidate emerged (PIVOT_BREAK) and was rejected by the `normal_routing` binding (independent of measurement)
  - The morning-briefing failure for EURUSD/London (levels-validation errors from Anthropic call) will keep EURUSD blocked at London open — this is a *separate*, pre-existing failure surface and is orthogonal to Phase 2B

## §7 — Non-issues surfaced during the audit (unrelated, for the record)

Two independent DEBUG-level issues were observed. Neither is Phase 2B related; both pre-date this session. **Reported here for transparency, no action taken.**

1. `[QM-MEM] state save failed: [Errno 2] No such file or directory: '/opt/tradingbot/logs/qm_level_memory_state.json.tmp' -> '/opt/tradingbot/logs/qm_level_memory_state.json'` — recurring at DEBUG. Filesystem rename failure in QM level-memory persister. Non-fatal for trading; also periodic `dictionary changed size during iteration` DEBUG. Not new; not phase2b.
2. `[morning_briefing] EURUSD/London: Anthropic call failed — unknown` after 3 retries — Anthropic-generated levels failing validation (rank spacing constraints). EURUSD London session is blocked for trades this morning. Not phase2b.

---

## Appendix A — Commands executed for evidence

```bash
# HEAD, service, environment
git rev-parse HEAD; git log --oneline -30
systemctl show autobot.service --property=ActiveEnterTimestamp,MainPID,NRestarts,SubState,ExecMainStartTimestamp
tr '\0' '\n' < /proc/467277/environ | grep -iE "phase2b|measure|shadow"

# Journal — service lifecycle, errors, broker calls
journalctl -u autobot.service --since '2026-09-18 00:00:00' -o cat | grep -iE "systemd|traceback|exception"
journalctl -u autobot.service --since '2026-09-16 00:00:00' -o cat | grep -E "🟢 Opening|dealReference|OPENED"

# Funnel logs
python3 /tmp/audit_funnel.py                    # (reproducible; parses jsonl files listed inside)

# Measurement writer
grep -n "put_nowait\|_STATS\|dropped_queue\|write_failures" /opt/tradingbot/measurement_writer.py
journalctl -u autobot.service --since '2026-09-17 20:28:00' -o cat | grep -iE "measurement_writer|phase2b"
```

## Appendix B — Reproducibility

- Every count in this report is derivable by re-running the commands in Appendix A against the same log snapshots (log files listed and their mtimes captured in §1 and §2).
- `phase2b_measurement.jsonl` byte-count at audit time: `484312 bytes, 240 total rows (158 for 2026-09-18)`.
- No log files were mutated, rotated, or purged during this audit.
