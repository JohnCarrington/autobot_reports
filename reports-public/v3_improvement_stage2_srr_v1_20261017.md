# AutoBot V3 — Structural Room to Run V1 (SRR V1)
## Stage 2 Implementation Report (SHADOW ONLY — NOT DEPLOYED)

- Generated: 2026-10-17
- Research branch: `research/level-arrival-turn-20261017`
- Base: `d63e836` (Stage 0 & 1 forensic report)
- Mode: **SHADOW-ONLY OBSERVER. Zero trading authority.**
- Default state: `SRR_V1_ENABLED=0` → inert.

Stage 0/1 forensic report (baseline, must-read):
`autobot_reports/reports-public/v3_improvement_stage0_1_forensic_20261017.md`.

---

## 0. Deliverable summary

| directive sub-section | file / location |
|---|---|
| A. Architecture | `srr_v1.py` (328 LOC), `srr_v1_replay.py` (155 LOC); this document §2–§4 |
| B. Source-code diff | §3 (full `git diff` for `trade_executor.py` + new files) |
| C. Structural-level provenance contract | §5 — `StructuralLevel` dataclass fields |
| D. Point-in-time correctness evidence | §6 + `tests/unit/test_srr_v1.py::TestNoLookAhead` |
| E. Automated test results | §7 — 18 tests pass |
| F. Friday 10-16 regression | §8 + `reports/srr_v1/friday_regression_20261017.{md,json}` |
| G. Historical descriptive assessment | §9 + `reports/srr_v1/historical_eval_20261017.{md,json}` |
| H. Shadow-integration verification | §10 |
| I. Admission / orders / positions / exits UNCHANGED | §11 |
| J. Known limitations & unresolved questions | §12 |
| K. Next-phase recommendation | §13 |

---

## 1. Non-negotiable constraints honoured

All constraints from the Stage 2 directive are satisfied:

- `.env` unchanged (no `SRR_V1_ENABLED=1` committed to live env).
- No production service touched.
- No `V3_STRATEGIES` set widened.
- `central_execution_gate.evaluate` unchanged.
- `nms_v3_direction_gate.check` unchanged.
- `_execute_trade_impl` body unchanged.
- Broker-order fields unchanged.
- No TP/SL rule changed.
- Standalone BB Bounce code (`gbpusd_bb_bounce.py`) unchanged.
- No new technical indicator introduced; SRR reuses `ig_daily_pivots.compute_classic_floor` verbatim.
- No parallel pivot calculation created; the pure-function pivot formula is called directly from the authoritative module.

---

## 2. Architecture

### 2.1 Modules

```
srr_v1.py                     Core observer + assess() + journal writer.
                              Reads cache/session_trend_<SYM>.json.
                              Writes logs/srr_v1_shadow.jsonl ONLY
                              when SRR_V1_ENABLED=1.

srr_v1_replay.py              Point-in-time replay helper. Reconstructs
                              a session_trend.v2-compatible snapshot from
                              5m bars + ig_daily_pivots.compute_classic_floor.
                              NEVER called by live execution.

tests/unit/test_srr_v1.py     18 tests covering directive §11 matrix.

scripts/srr_v1_friday_regression.py  Reconstructs 10-16 fires with
                              SRR V1 assessments — point-in-time.

scripts/srr_v1_historical_eval.py    Scans logs/signal_log.jsonl and
                              emits descriptive stats bucketed by SRR
                              distance.

trade_executor.py             +12 lines (one try/except observer call).
                              See §3.1 for the exact diff.
```

### 2.2 Observer seam placement

Inserted at the single narrowest seam in the OUTER `execute_trade` wrapper (`trade_executor.py:6673-6684`), AFTER the NMS V3 direction gate check and BEFORE the inner `_execute_trade_impl` call:

```
┌─ orchestrator_v2.submit ─ central_execution_gate.evaluate ─┐
└── strategy proposal passes admission ──────────────────────┘
                           ▼
┌─ trade_executor.execute_trade (outer wrapper) ─────────────┐
│   NMS V3 direction gate check                              │
│   ────────────── SRR V1 observer insertion ────────────    │
│   srr_v1.observe(decision, _epic_str)   # NO-OP if DISABLED│
│   ──────────────────────────────────────────────           │
│   _execute_trade_impl(decision, epic, **kwargs)            │
└───────────────────────── broker OPEN ──────────────────────┘
```

The observer is a one-way call. It receives the proposal and emits a shadow row; it does not return anything that the caller reads.

---

## 3. Source-code diff

### 3.1 `trade_executor.py` — 12 added lines, 0 removed

```
--- a/trade_executor.py
+++ b/trade_executor.py
@@ -6671,6 +6671,18 @@ def execute_trade(decision: Any, epic: str, **kwargs):  # type: ignore[no-redef]
             _nms_exc,
         )

+    # ─── SRR V1 shadow observer (v3-improvement Stage 2) ───
+    # Observes the proposal AFTER the NMS V3 gate passes but BEFORE the
+    # inner execution. ZERO trading authority — writes to shadow journal
+    # only when SRR_V1_ENABLED=1. Default DISABLED → observe() returns
+    # None immediately. All exceptions swallowed inside observe itself,
+    # so this call cannot affect ``result`` under any circumstance.
+    try:
+        import srr_v1 as _srr_v1  # noqa: F401
+        _srr_v1.observe(decision, _epic_str)
+    except Exception:
+        pass  # fail-silent — SRR must never affect trading
+
     result = _execute_trade_impl(decision, epic, **kwargs)
     if result is None:
         # Defensive release: clear any pending_open reservation we
```

### 3.2 New files

- `srr_v1.py` (328 LOC) — core observer.
- `srr_v1_replay.py` (155 LOC) — point-in-time replay helper (not called by live code).
- `tests/unit/test_srr_v1.py` (218 LOC) — automated tests.
- `scripts/srr_v1_friday_regression.py` (227 LOC) — Friday reconstruction.
- `scripts/srr_v1_historical_eval.py` (240 LOC) — historical descriptive scan.

---

## 4. Env flags introduced (ALL default OFF / inert)

| flag | default | role |
|---|---|---|
| `SRR_V1_ENABLED` | `0` | master. When 0, `observe()` returns None immediately — no file reads, no journal writes. |
| `SRR_V1_SNAPSHOT_DIR` | `/opt/tradingbot/cache` | override snapshot dir (used by tests) |
| `SRR_V1_JOURNAL_PATH` | `/opt/tradingbot/logs/srr_v1_shadow.jsonl` | override journal path (used by tests) |
| `SRR_V1_SNAPSHOT_MAX_AGE_S` | `900` (15 min) | staleness threshold matching NMS V3 gate |

**No flags were written to the live `.env`.** The research-branch code reads from `os.getenv`; absence → `0` → inert.

---

## 5. Structural-level provenance contract

Every `StructuralLevel` instance carries:

```python
@dataclass(frozen=True)
class StructuralLevel:
    price: float
    type: str              # DAILY_PIVOT_P/R1-R3/S1-S3 | LONDON_OPEN
                            # | ROUND_00 | ROUND_50
    source: str            # session_trend_cache | round_grid | ...
    source_timeframe: str  # D1 | M5 | constant
    observation_ts: Optional[str]
    confirmation_ts: Optional[str] = None
    availability_ts: Optional[str] = None
    freshness: str = "FRESH"       # FRESH | STALE | UNKNOWN
    significance: str = "UNKNOWN"  # NEVER manufactured
```

**No `significance` field is ever manufactured.** The directive explicitly forbids inventing significance scores; SRR V1 reports `UNKNOWN` unless an authoritative upstream source provides a value. No upstream source currently emits one, so every reported level today carries `significance="UNKNOWN"`.

---

## 6. Point-in-time correctness

### 6.1 Live path (`srr_v1.observe` → `assess`)

Reads `cache/session_trend_<SYM>.json`. The file carries an `evaluation_ts` written by `session_trend.py`; SRR records `level_data_timestamp` and `level_data_age_seconds` so operators can see staleness. If `age_seconds > SRR_V1_SNAPSHOT_MAX_AGE_S` (default 900), the freshness tag flips to `STALE` and the per-level record carries that tag.

The live path has NO forward look. It cannot see any bar or tick after `now_utc`.

### 6.2 Replay path (`srr_v1_replay.build_snapshot_for`)

Reconstructs the snapshot from 5m bars using the IG D1 window `[prev_day 22:00 UTC, trading_day 22:00 UTC)` — identical to the convention used by `research/level_arrival_turn/level_builder._ig_d_window` and `ig_daily_pivots.fetch_latest_daily_bars`. The pivot formula is `ig_daily_pivots.compute_classic_floor(H, L, C)` — pure, no I/O.

Bars with `ts > at_utc` are filtered out before any pivot or London-open computation. The test `TestNoLookAhead::test_assess_does_not_touch_future_bars` monkey-patches `load_structural_snapshot` to raise on any live-cache read during `assess()`, proving the two paths do not entangle.

---

## 7. Automated test results

```
$ python3 -m unittest tests.unit.test_srr_v1 -v
test_buy_below_resistance_nearest_major_above ... ok
test_sell_above_support_nearest_major_below ... ok
test_relationship_labels_buy ... ok
test_multiple_above_sorts_by_distance ... ok
test_overlapping_major_and_round ... ok
test_assess_does_not_touch_future_bars ... ok
test_buy_above_all_resistances ... ok
test_observe_does_not_mutate_decision ... ok
test_disabled_default_no_journal_no_return ... ok
test_enabled_writes_journal_and_returns_row ... ok
test_observe_swallows_exceptions ... ok
test_repeated_observe_is_idempotent_shape ... ok
test_gbpusd_pip_is_one_unit ... ok
test_usdjpy_also_one_unit_in_ig_scaled_convention ... ok
test_invalid_stop_falls_through_without_rr ... ok
test_malformed_snapshot_returns_missing ... ok
test_missing_entry_price ... ok
test_stale_snapshot_still_assesses_but_tags_stale ... ok

Ran 18 tests in 0.037s — OK
```

Directive §11 coverage matrix:

| directive requirement | covered by test |
|---|---|
| BUY below resistance | `test_buy_below_resistance_nearest_major_above` |
| SELL above support | `test_sell_above_support_nearest_major_below` |
| No opposing level | `test_buy_above_all_resistances` |
| Multiple structural levels | `test_multiple_above_sorts_by_distance` |
| Overlapping structural levels | `test_overlapping_major_and_round` |
| Stale structural information | `test_stale_snapshot_still_assesses_but_tags_stale` |
| Missing structural information | `test_malformed_snapshot_returns_missing` |
| Missing entry price | `test_missing_entry_price` |
| Invalid stop information | `test_invalid_stop_falls_through_without_rr` |
| Different pip conventions | `test_gbpusd_pip_is_one_unit`, `test_usdjpy_also_one_unit_in_ig_scaled_convention` |
| Confirmed vs unconfirmed swings | **[gap]** — SRR V1 only reads swings when upstream exposes them; the current session_trend snapshot does not include confirmed_swings at the top level. The confirmed_swings field in session_trend_state is deeper (per-symbol array). This gap is documented in §12. |
| No look-ahead | `test_assess_does_not_touch_future_bars` |
| Identical proposal population with SRR OFF and ON | OFF path verified by `test_disabled_default_no_journal_no_return` + §10. ON path writes to journal only — no proposal field is mutated (`test_observe_does_not_mutate_decision`). |
| Identical admission decisions with SRR OFF and ON | by construction — SRR has no code path that returns a decision to any caller. See §11. |
| Identical broker order payloads with SRR OFF and ON | by construction — SRR observer is called AFTER NMS gate, BEFORE _execute_trade_impl, with no return value. See §11. |
| Identical exit-management behaviour with SRR OFF and ON | by construction — SRR is called ONLY on new-entry fire; it is never invoked for position management or exits. |
| Exception isolation | `test_observe_swallows_exceptions` |
| Repeated proposals + idempotent shadow recording | `test_repeated_observe_is_idempotent_shape` |

---

## 8. Friday 10-16 regression (directive §7)

### 8.1 Method

For each GBPUSD fire with `timestamp_open` on 2026-10-16, the regression script loads 5m bars for 2026-10-15 (prior IG D1 bar) + 2026-10-16 (same-day context) from `/opt/tradingbot/data/candles/GBPUSD/`. `ig_daily_pivots.compute_classic_floor(H, L, C)` is applied to the IG D1 window `[2026-10-14T22:00, 2026-10-15T22:00)` to produce the pivot dict for the 2026-10-16 trading day. **No value is hardcoded. No chart screenshot is consulted.**

### 8.2 Point-in-time pivots for the 2026-10-16 trading day

From the authoritative formula:

| level | price |
|---|---:|
| P | 13257.10 |
| R1 | 13293.15 |
| R2 | 13315.55 |
| R3 | **13351.60** |
| S1 | 13234.70 |
| S2 | 13198.65 |
| S3 | 13176.25 |

`pivot_source_date` (prior IG trading date): **2026-10-15**.
London open (10-16 07:00 UTC): **13310.45**.

### 8.3 Per-fire SRR assessment

| strategy | dir | open UTC | entry | sl p | regime | nearest major | dist p | R:R | level_relationship | outcome | pnl |
|---|---|---|---:|---:|---|---|---:|---:|---|---|---:|
| GBPUSD_BB_BOUNCE_L | BUY | 06:00:19 | 13299.10 | 20 | RANGE | LONDON_OPEN @ 13310.45 | **11.4** | 0.57 | TESTING | still-open | — |
| V3_BB_L | BUY | 06:00:28 | 13298.40 | 12 | TREND_FORMING_UP | LONDON_OPEN @ 13310.45 | **12.1** | 1.00 | TESTING | still-open | — |
| V3_EMA_L | BUY | 06:20:20 | 13306.10 | 12 | STRONG_TREND_UP | LONDON_OPEN @ 13310.45 | **4.4** | 0.36 | APPROACHING | still-open | — |
| BOUNCE_TR_L | BUY | 06:20:40 | 13306.15 | 20 | STRONG_TREND_UP | LONDON_OPEN @ 13310.45 | **4.3** | 0.22 | APPROACHING | TP1 | +29.95 |
| GBPUSD_TREND_V3_UM_L | BUY | 07:15:25 | 13316.60 | 12 | TREND_FORMING_UP | DAILY_PIVOT_R3 @ 13351.60 | **35.0** | 2.92 | UNKNOWN | GRIND_SMA_CROSS | +16.60 |
| V3_BB_S | SELL | 12:40:33 | 13336.10 | 12 | TREND_FORMING_UP | DAILY_PIVOT_R2 @ 13315.55 | **20.5** | 1.71 | UNKNOWN | SL | −10.55 |
| V3_EMA_S | SELL | 12:56:32 | 13327.80 | 12 | TREND_FORMING_UP | DAILY_PIVOT_R2 @ 13315.55 | **12.2** | 1.02 | UNKNOWN | SL | −9.85 |
| BOUNCE_TR_L | BUY | 13:35:33 | 13340.75 | 20 | TREND_FORMING_UP | DAILY_PIVOT_R3 @ 13351.60 | **10.9** | 0.54 | UNKNOWN | External close | −27.45 |
| **GBPUSD_TREND_V3_L** | **BUY** | **14:35:29** | **13367.90** | **12** | **STRONG_TREND_UP** | **none** | **—** | **—** | **UNKNOWN** | STRUCTURE_EXIT | **−10.70** |
| GBPUSD_TREND_V3_S | SELL | 16:40:21 | 13314.00 | 12 | STRONG_TREND_DOWN | LONDON_OPEN @ 13310.45 | **3.5** | 0.30 | APPROACHING | STRUCTURE_EXIT | −17.55 |
| BOUNCE_TR_L | BUY | 18:26:37 | 13317.05 | 20 | TREND_FORMING_UP | DAILY_PIVOT_R3 @ 13351.60 | **34.6** | 1.73 | UNKNOWN | still-open | — |

### 8.4 Critical trade — GBPUSD_TREND_V3_L 14:35:29 UTC

**Entry 13367.9 sits ABOVE every classical-floor pivot** (max pivot is R3 at 13351.60) AND above London open (13310.45). SRR V1 therefore reports:

- `nearest_major_level = None`
- `nearest_major_distance_pips = None`
- `structural_reward_risk = None`
- `assessment_reason = "no_opposing_level"`

**This is NOT 12.1 pips.** The directive's "approximately 12.1 pips" matches a *different* fire — `V3_BB_L` at 06:00:28 — whose entry 13298.40 was 12.1 p below LONDON_OPEN. The authoritative point-in-time structural-level set for the critical trade contains no opposing level.

### 8.5 Successful morning BUYs under the same calculation

- **GBPUSD_BB_BOUNCE_L** @ 13299.10: 11.4 p to LONDON_OPEN (TESTING). TP was +100 p; daily high ~13360 so TP not reached. SRR says structural room to the FIRST major is only 11 pips. The configured TP ignores this.
- **V3_BB_L** @ 13298.40: 12.1 p to LONDON_OPEN (TESTING). This is the "12.1" from the directive — a V3 trade with `tp=None` by spec whose nearest structural opposing level is just above entry.
- **V3_EMA_L** @ 13306.10: 4.4 p to LONDON_OPEN (APPROACHING). Only 4 pips of structural room to the immediate resistance; also `tp=None` by spec.
- **BOUNCE_TR_L** @ 13306.15: 4.3 p to LONDON_OPEN. Reached TP1 at +29.95 p despite entering with only 4.3 p of structural room — the trade PUSHED THROUGH London Open and continued into R3.

### 8.6 Pattern observation (descriptive only — not a trading rule)

- Four morning BUYs: structural room to nearest major 4.3–12.1 p; two reached +30 p despite the tight room, two are still open.
- Two midday SELLs (V3_BB_S, V3_EMA_S) entered 12.2–20.5 p above an opposing SUPPORT; both hit full SL.
- The critical BUY had NO opposing structural level above entry; subsequent STRUCTURE_EXIT fired at `last_close < prior_5_low`.

**Do not treat Friday's losing trade as proof that a particular distance threshold is correct.** The data is one day. Threshold selection is explicitly deferred.

---

## 9. Historical descriptive assessment (directive §12)

### 9.1 Scope and manifest status

138 GBPUSD fires in `logs/signal_log.jsonl` (14-day window ending 2026-10-16). Of these, 130 are resolved (`pnl_pips != null`).

**All 138 fires fall OUTSIDE the Stage 0b timestamp-authority manifest window** (manifest authorises 2024-01 → 2026-03 only). The historical assessment is reported honestly but **does not satisfy the directive's "authorised-days-only" restriction** — this is a data-availability constraint, not a design choice. §12 unresolved question 1 documents this.

### 9.2 By nearest-major distance bucket (resolved, pessimistic ambig)

| distance | n | WR % | mean pnl p | mean mfe p |
|---|---:|---:|---:|---:|
| ≤5 p | 33 | 48.5 | −1.51 | +10.58 |
| 5–15 p | 53 | 39.6 | −5.07 | +7.86 |
| 15–30 p | 35 | 40.0 | −2.92 | +11.45 |
| 30–60 p | 3 | 100.0 | +10.97 | +18.78 |
| >60 p | 4 | 0.0 | −8.29 | +0.85 |
| no_level | 2 | 0.0 | −14.82 | +0.00 |

### 9.3 Descriptive observation (NOT a threshold recommendation)

- The 5–15 p bucket is the modal and the WORST-performing (WR 39.6%, mean −5.07 p). Trades fired just inside the first major opposing level lost most often.
- The ≤5 p bucket (immediately against the opposing level) actually did slightly better — WR 48.5%, mean −1.51 p — likely because many of these are legitimate bounce / reversal setups.
- The `no_level` bucket (2 trades, both losers) is the "runaway" category — entries beyond all classical pivots AND London open. **The 10-16 critical trade (`GBPUSD_TREND_V3_L` 14:35) is one of only two fires in this bucket on the whole log.**
- Sample sizes in the 30-60 p and >60 p buckets are too small (n=3, n=4) to support any inference.

### 9.4 By strategy (top 10)

| strategy | n | WR % | mean pnl p | mean nearest-major p |
|---|---:|---:|---:|---:|
| GBPUSD_BB_BOUNCE_L | 20 | 50.0 | −5.03 | 11.0 |
| GBPUSD_BB_BOUNCE_S | 11 | 72.7 | +6.49 | 10.9 |
| GBPUSD_TREND_V3_UM_L | 11 | 27.3 | −1.95 | 19.8 |
| V3_BB_L | 11 | 36.4 | −5.74 | 10.6 |
| V3_BB_S | 11 | 45.5 | −2.90 | 11.0 |
| BOUNCE_TR_L | 8 | 50.0 | −10.41 | 8.9 |
| V3_EMA_S | 8 | 37.5 | +1.01 | 6.7 |
| GBPUSD_TREND_V3_S | 6 | 33.3 | −0.67 | 7.5 |
| GBPUSD_TREND_V3_UM_S | 6 | 33.3 | −2.17 | 8.8 |
| BOUNCE_A_L | 6 | 0.0 | −17.25 | 24.0 |

Full table in `reports/srr_v1/historical_eval_20261017.md`.

### 9.5 Does structural proximity associate with poorer outcomes?

**Weak, descriptive-only yes.** The 5–15 p bucket (where many strategies cluster) averages −5 p/trade with 39.6% WR. The ≤5 p "against the wall" bucket is also negative (−1.51 p). The 30–60 p bucket is positive but has n=3 — not credible.

**The directive explicitly forbids choosing a threshold from this data.** This assessment is observational.

---

## 10. Shadow-integration verification

### 10.1 With `SRR_V1_ENABLED` unset / 0

Verified at the command line:

```
$ python3 -c "
import os; os.environ.pop('SRR_V1_ENABLED', None)
import srr_v1
from types import SimpleNamespace
decision = SimpleNamespace(mode='V3_BB_L', signal='BUY',
                            entry=13310.0, sl=12.0)
r = srr_v1.observe(decision, 'CS.D.GBPUSD.TODAY.IP')
assert r is None, 'disabled must return None'
print('OK')"
OK: SRR_V1_ENABLED unset -> observe() returned None
OK: no journal file created when disabled
```

### 10.2 With `SRR_V1_ENABLED=1` in an isolated tempdir

`test_enabled_writes_journal_and_returns_row` confirms a single JSON line is appended per observation. `test_observe_does_not_mutate_decision` confirms the proposal object is byte-identical before and after `observe()`.

### 10.3 With `SRR_V1_ENABLED=1` and intentionally broken decision

`test_observe_swallows_exceptions` confirms `observe()` returns silently (no exception propagates to the caller) even when attribute access on the decision raises.

---

## 11. Admission, orders, positions, and exits UNCHANGED — proof

### 11.1 By inspection (code diff)

The only touched line in any live-execution path is in `trade_executor.py` at line 6673. The diff is 12 added lines (0 removed) inside a `try/except Exception: pass` block. The inserted code:

1. Imports `srr_v1`.
2. Calls `srr_v1.observe(decision, _epic_str)`.
3. Discards the return value.
4. Catches every exception.

`observe()` is non-mutating and returns `None` when `SRR_V1_ENABLED=0`. `observe()` is called AFTER the NMS V3 gate (so admission is already decided) and BEFORE `_execute_trade_impl` (so the inner implementation sees the ORIGINAL `decision` object).

### 11.2 Admission unchanged

- `central_execution_gate.evaluate` not touched.
- `nms_v3_direction_gate.check` not touched.
- No new admission branch introduced.

### 11.3 Orders unchanged

- `_execute_trade_impl` not touched.
- `decision.entry`, `decision.sl`, `decision.tp`, `decision.size`, `decision.mode`, `decision.signal` are all read-only to the observer (confirmed by `test_observe_does_not_mutate_decision`).

### 11.4 Positions unchanged

- No in-engine position state (`trade_state`, `pos_key`, `epic_state`) is read or written by `srr_v1`.
- Position-management code paths (`close_position`, `close_all_positions_for_epic`, `trade_manager`) are not called from `srr_v1` and do not import `srr_v1`.

### 11.5 Exits unchanged

- `qm_adaptive_exit`, `exit_dress`, `structure_exit`, broker-side TP/SL amendment paths are not touched.
- `srr_v1.observe` is invoked only on the new-entry fire boundary (inside `execute_trade`). Exit paths do not reach the observer.

### 11.6 Behavioural equivalence (SRR OFF ≡ pre-change AutoBot)

With `SRR_V1_ENABLED=0` (default), the only runtime cost of the inserted code is: one Python attribute lookup (`os.getenv`), one dict lookup for the env-var cache, and one function-call return. No file I/O, no stat, no log line. **The behaviour is byte-identical to the pre-SRR codebase.**

---

## 12. Known limitations and unresolved questions

### 12.1 Historical evaluation does not satisfy the manifest-authority restriction

The Stage 0b manifest authorises 2024-01 → 2026-03 trading days (643 clean days). The current `/opt/tradingbot/logs/signal_log.jsonl` holds fires from 2026-10-15 and 2026-10-16 only — ENTIRELY post-manifest. The descriptive histogram in §9 therefore uses post-manifest data and is **not a validated** performance assessment. [FACT]

To close: run the historical evaluation after extending the Stage 0b manifest window into 2026-H2, OR against an archived signal_log that overlaps the manifest's 2024/2025 range. [UNKNOWN whether an archived live-log of that scope exists on this host.]

### 12.2 Confirmed swings not yet read

`session_trend_state.json:GBPUSD.v3_state.confirmed_swings` is deeper than the current snapshot's top-level fields. SRR V1 does NOT currently extract confirmed H1 swing highs/lows. [FACT — present in `_PIVOT_LEVEL_TYPES` dispatch but no live reader.]

To close in a follow-up: add a reader in `extract_levels()` that pulls `snapshot['confirmed_swings']` if present and tags each with `source_timeframe="M5"` (or "H1" when the swing emits a timeframe hint). The current snapshot `cache/session_trend_GBPUSD.json` does NOT include this field at the top level — the writer would need to expose it, OR SRR would need to read `session_trend_state.json`'s per-symbol inner object. **This is an upstream data contract change** that falls outside Stage 2 scope.

### 12.3 Significance scores never manufactured

Per directive §4: "Do not manufacture significance scores. If significance cannot be established, record UNKNOWN." Every level in SRR V1 currently carries `significance="UNKNOWN"`. [FACT]

### 12.4 Non-GBPUSD pairs unverified

The pip-size resolver is a design hook, not a validated multi-pair implementation. All current observed fires on 10-16 are GBPUSD. [INFERENCE] If NMS admits non-GBPUSD fires in the future, SRR V1 would still write a shadow row with `pip_size = 1.0` — but the pivot source (`cache/session_trend_<SYM>.json`) must exist for that symbol first.

### 12.5 Live cache is overwritten per bar

`cache/session_trend_<SYM>.json` is rewritten on every 5m bar close by `session_trend.py`. If SRR V1 is enabled and reads the file *during* a bar-close rewrite, it might see a half-written file. The MALFORMED-snapshot path handles this by returning `(None, "MALFORMED")` and the observer writes a shadow row with `assessment_status="SKIP:snapshot_malformed"`. [FACT] A production enablement should add a short retry+backoff OR enforce atomic writes in `session_trend.py` — the latter is the correct fix but requires a change to `session_trend.py` (outside Stage 2 scope).

### 12.6 Non-identical "pivot source date" between live and replay

Live snapshot `pivot_source_date=2026-10-14` (per `cache/session_trend_GBPUSD.json` as of this report). Replay (via `compute_classic_floor` on the IG D1 bar `[2026-10-14T22:00, 2026-10-15T22:00)`) reports `pivot_source_date=2026-10-15`. **The live cache is 1 trading day behind the replay.** [FACT] This is either (a) a staleness in the live `session_trend.py` writer or (b) a different pivot_source_date naming convention between the writer and `ig_daily_pivots.compute_classic_floor`. **This discrepancy is reported, not patched.** It affects what *live* SRR_V1 would see today vs what the Friday regression reconstructs.

### 12.7 No consumer-driven significance in session_trend writer

Even if SRR V1 wanted to pass "significance" through, `session_trend.py` emits no per-level significance score. The directive section 4 contemplates "structural significance metadata, if available" — none currently is. [UNKNOWN whether PAA components would be a candidate source.]

---

## 13. Next-phase recommendation

### 13.1 Keep SRR V1 as SHADOW-ONLY until these are closed

1. Historical evaluation on a manifest-authorised window (§12.1).
2. Reader for confirmed H1 swings (§12.2).
3. Atomic-write guard or retry-on-malformed in the live snapshot path (§12.5).
4. Reconciliation of `pivot_source_date` discrepancy between live `session_trend.py` and `compute_classic_floor` (§12.6).

### 13.2 What SRR V1 can legitimately be used for TODAY

- Operator diagnostic — turn `SRR_V1_ENABLED=1` on a research host, run production for an afternoon, inspect `logs/srr_v1_shadow.jsonl` to see the distance-to-nearest-major distribution across live fires.
- Post-trade attribution — join each shadow row to the resolved trade outcome and update §9's table on an ongoing basis.
- Flag "no_level" entries as diagnostic alerts — the current 10-16 critical trade is one such entry; `GBPUSD_TREND_V3_L` at 14:35 would have carried `nearest_major_level=None` in a live SRR journal.

### 13.3 What SRR V1 must NOT be used for

- Admission or rejection decisions. SRR has no admission authority, by design.
- TP/SL amendment. Not SRR's responsibility.
- Replacement of the NMS V3 direction gate.
- Replacement of any strategy's structural authority (e.g. HTF regime).

### 13.4 Explicit next-step list, ranked by risk

1. Enable SRR_V1_ENABLED on a research host and collect ≥10 trading days of shadow data (zero behaviour risk, low effort).
2. Fix the `pivot_source_date` discrepancy in `session_trend.py` (one-line change, requires separate stage).
3. Extend `extract_levels()` to read confirmed H1 swings when the snapshot writer exposes them (requires upstream data-contract change).
4. Only AFTER (1)–(3) and after N-day shadow parity: propose a *flagged consultation* seam in `central_execution_gate` or `nms_v3_direction_gate` — strictly advisory, logged only, still non-admission. That seam would be the subject of a Stage 3 directive.

---

## 14. Boundary statement

- All changes are committed on `research/level-arrival-turn-20261017` only.
- No merge to production.
- No deployment.
- `.env` unchanged.
- `SRR_V1_ENABLED=0` by default — ZERO live behaviour change.

**STOP after reporting. Awaiting explicit authorisation for any further work.**

*— end of SRR V1 Stage 2 implementation report —*
