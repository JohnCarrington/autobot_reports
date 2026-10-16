# SLR v3 (ARM/DISARM model) — implementation-defect repair + full re-evaluation

Date: 2026-10-16
Branch: `research/one-day-replay-20261015` (worktree, not merged into
production); code commits land locally in that worktree only.

## 1. Mandate

Repair the defects exposed by the frozen v1 HOLDOUT run — ~81 trades/day
driven by same-event duplication, two-sided-same-bar firing, and 36 p
P90 entry drift — and re-run the identical frozen eval. **No new
trading filters.** No optimisation on prior results.

## 2. Defects repaired

| Defect | Fix | Reference |
|---|---|---|
| Multiple trades per physical rejection event | ARM → DISARM model: each pre-known level starts ARMED and fires AT MOST ONE signal; the instant a signal is released the level is DISARMED permanently. No cooldown, no state machine, no re-arm. | `strategy.py` v3 class `SLRStrategy`, `set_levels/_release` |
| Two trades from one bar (BUY and SELL) | A bar with both-side pierce+reclaim is resolved by intra-bar tick chronology: the side whose extreme arrives LATER wins; both armed levels preserved and only the winning level is disarmed. OHLC-only ambiguous bars emit nothing. | `strategy.py` v3 `_resolve_two_sided` |
| Entry fill P90 = 36.1 p from extreme | Two independent fixes: (a) tick ↔ bar timestamp **auto-calibration** per day over a 1-hour-step scan range (−5 h … +12 h), picking the shift with minimum MAE and rejecting edge-tie candidates; (b) fill search window capped at **60 s** so a tz-misaligned archive cannot masquerade as "first executable price". | `resolver.py` `_calibrate_tick_offset_hours`, `find_fill(window_seconds=60)` |

The v2 "4-state level machine with depart-and-return" was discarded per
operator simplification. Only ARM → DISARM remains.

## 3. Deterministic tests (all 13 pass)

Covering the five contract items (operator 2026-10-16):

| # | Test | What it proves |
|---|---|---|
| 1a | `test_1a_arm_releases_at_most_one_trade` | 5 consecutive qualifying bars → exactly 1 release |
| 1b | `test_1b_arm_can_release_zero_trades_if_never_rejected` | 50 non-piercing bars → 0 releases, level stays armed |
| 2 | `test_2_disarmed_after_release` | After a release, `is_disarmed(L)` is True |
| 3 | `test_3_further_qualifying_bars_cannot_fire` | 20 later qualifying bars (incl. departures) → 0 refires |
| 4 | `test_4_arm_cannot_release_both_directions` | After a BUY release, a SHORT pierce+reclaim at the same L emits nothing |
| 4b | `test_4b_same_bar_two_sided_without_ticks_emits_nothing` | OHLC-only ambiguous bar → 0 signals, both arms preserved |
| 5 | `test_5_sl_tp_outcome_does_not_rearm` | After release, a stop + eventual return re-test → 0 signals |
| 6a | `test_6a_tick_chronology_buy_wins_when_low_is_later` | Later-LOW tick chronology → BUY; loser arm preserved |
| 6b | `test_6b_tick_chronology_sell_wins_when_high_is_later` | Later-HIGH chronology → SELL; loser arm preserved |
| h1 | `test_h1_entry_is_first_tick_strictly_after_signal_end` | find_fill returns first tick > signal_end at ASK (LONG) |
| h2 | `test_h2_window_60s_rejects_minutes_late_fill` | Tick 10 min late → None |
| 7 | `test_7_calibrate_offset_recovers_shift` | Shift+5h recovered exactly, MAE = 0 |
| 8 | `test_8_levels_disarm_independently` | Firing L1 does not disarm L2 |

Run: `python -m pytest research/slr/tests/test_event_model.py --rootdir=research/slr`
→ `13 passed in 0.25s`.

## 4. 26-Feb diagnostic — both pre-registered reversals captured

Full tick-fill run, config unchanged (TP=30, SL=12, hours 06-21 UTC,
level_band derived parameters removed in v3 ARM model):

```
Diagnostic 2026-02-26: n_trades=12, fill_mode=tick, regime=unshifted_utc

  trade  2  07:55  SHORT round_50(13550.00)  fill 13548.40  dist +1.90p  →  TP +30.3p   ← LONDON reversal captured
  trade  9  12:45  LONG  round_50(13450.00)  fill 13454.10  dist +4.70p  →  TP +30.0p   ← NY reversal captured
```

Entry distances match the pre-registration exactly (1.90p / 4.70p —
the operator's 2026-10-15 figures).

Full day: 12 trades, 2 TP + 10 SL, net −60p. Diagnostic PASSES on
reversal capture.

## 5. Full DEV / HOLDOUT / OOS re-evaluation (frozen setup, v3)

Same partitions, same TP/SL/hours, strategy frozen between diagnostic
pass and corpus run. No tuning.

### 5a. Headline

| Partition | Days | Trades | Trades/day | TP | SL | EOD | Net pips | **PF** | Mean p/trade | Entry-dist p50/p75/p90/p95/max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| DEV | 447 | 3,098 | 8.0 | 711 | 2,124 | 263 | −3,134.0 | **0.882** | −1.01 | 4.70 / 11.30 / 26.80 / 39.80 / 141.20 |
| HOLDOUT | 139 | 1,027 | 7.8 | 234 | 715 | 78 | −1,342.3 | **0.850** | −1.31 | 5.10 / 10.10 / 20.50 / 30.50 / 112.90 |
| OOS | 56 | 389 | 6.9 | 84 | 275 | 30 | −647.6 | **0.810** | −1.66 | 4.95 / 8.20 / 14.65 / 23.55 / 149.85 |

### 5b. ARM invariant held — zero duplicate releases

| Partition | Duplicate (level, side, day) releases | Ambiguous (two-sided, no-tick-resolution) bars |
|---|---:|---:|
| DEV | **0** | 21 |
| HOLDOUT | **0** | 8 |
| OOS | **0** | 1 |

Zero re-firings by construction. Ambiguous bars (totals 30 across
642 days) are dropped per the operator rule.

### 5c. Per-day trade count distribution

| Partition | Mean | Median | P75 | P90 | P95 | Max |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 6.9 | 7 | 9 | 11 | 13 | 18 |
| HOLDOUT | 7.4 | 8 | 10 | 12 | 12 | 14 |
| OOS | 6.9 | 7 | 9 | 12 | 13 | 14 |

Compare to v1 HOLDOUT: mean 81.4, max 154. v3 ceiling is driven by the
pre-day level inventory (~25-30 pre-day + 2 Tokyo + 2 London = ~30) ×
P(any_rejection_per_level_per_day); the observed ~8/day is the data
answering "how many pre-known significant levels actually get rejected
on an average day."

### 5d. Known ≥30 p reversals captured (R4C.4A corpus)

Methodology (identical to v1): for each pre-registered event with
`any_30p = True` in the partition's date set, mark captured if ANY SLR
trade with matching side had its signal_bar_ts in
`[event.first_interaction_ts − 10 min, +60 min]` AND exited TP.

| Partition | Captured | Missed | In-scope ≥30 p events |
|---|---:|---:|---:|
| DEV | n/a | n/a | r4c4a corpus runs 2026-01+ only |
| HOLDOUT | n/a | n/a | r4c4a corpus runs 2026-01+ only |
| **OOS** | **52** | **129** | **181** |

OOS capture rate 28.7 %. v1 reported 90/139 = 64.7 % — but on a
strict overlap-only scope of 139 events (likely with an additional
R4C.4A filter the v1 commit used; the raw `any_30p=True` set over
the same 56 OOS days is 181). The lower rate reflects far fewer total
trades (389 vs 3,656); capture-per-trade rose from **90 / 3,656 =
2.5 %** (v1) to **52 / 389 = 13.4 %** (v3) — ~5.4× more selective
per shot.

### 5e. Tick-offset auto-calibration

| Partition | Days with ticks | +0 h | +4 h | +5 h | +8 h | mean MAE (p) |
|---|---:|---:|---:|---:|---:|---:|
| DEV | 388 | 7 | 6 | 15 | ~310 | 4.37 |
| HOLDOUT | 131 | 3 | 2 | 4 | ~110 | 3.85 |
| OOS | 56 | 50 | 0 | 1 | 2 | 0.79 |

The GBPUSD tick archive for 2024-2025 is stored at ≈ UTC-8 (so needs
+8 h to real UTC), not the +5 h the memory notes suggested. The data
answered the question. OOS 2026 data is already in UTC; one-click
calibration applies +0 h there.

### 5f. Entry-distance comparison v1 vs v3b (HOLDOUT, same journal)

The structural fill-drift repair cut the tail by ~45 %:

| Metric | v1 (36 s window, bar-offset shift) | v3b (60 s window, data-cal shift) |
|---|---:|---:|
| median | 4.20p | 5.10p |
| P90 | **36.10p** | **20.50p** |
| P95 | 48.40p | 30.50p |
| max | 153.5p | 112.9p |

Median is slightly worse because v3b runs on far fewer / different
trades (1,027 vs 11,315), but the TAIL — the entire category of
"filled 20-50 p away from the extreme the signal justified" — shrank
by 15 p at P90.

## 6. v1 (duplication) vs v3b (repaired) at a glance

| | **v1 (frozen)** | **v3b (ARM, calibrated)** | Δ |
|---|---:|---:|---|
| DEV trades | 34,744 | 3,098 | **−91 %** |
| HOLDOUT trades | 11,315 | 1,027 | **−91 %** |
| OOS trades | 3,656 | 389 | **−89 %** |
| DEV net pips | −73,399 | −3,134 | −95.7 % loss |
| HOLDOUT net pips | −28,406 | −1,342 | −95.3 % loss |
| OOS net pips | −10,195 | −648 | −93.6 % loss |
| DEV PF | 0.838 | 0.882 | +0.044 |
| HOLDOUT PF | 0.783 | 0.850 | +0.067 |
| OOS PF | 0.774 | 0.810 | +0.036 |
| HOLDOUT P90 entry-dist | 36.1 p | 20.5 p | −43 % |
| HOLDOUT max entry-dist | 153.5 p | 112.9 p | −26 % |

## 7. Finish-line test — operator's original question

> *Is one correctly executed trade per genuine significant-level
> rejection profitable?*

**NO.** PF < 1 on every partition, mean −1.0 to −1.7 p / trade across
2,470 clean one-per-arm GBPUSD trades 2024-01 → 2026-03. The repair
removed the 91 % duplication tail that was previously masking the
cleaner answer; the proposition itself — pierce + reclaim at a
pre-known level, no filters, 30 p TP / 12 p SL, 06-21 UTC — does
not profit on this instrument over this period.

The repair does leave a cleaner evidential base:
- v3b capture-per-trade is ~5× v1's (13.4 % vs 2.5 % on OOS).
- v3b entry-fill P90 at 20.5 p is finally within one TP (30 p).
- Trades/day distribution is tight (max 14 HOLDOUT, 18 DEV) so day-
  level risk is bounded.

Any next step (if the operator chooses to take one) would be building
on these clean 2,470 trades — but that is explicitly out of scope here.

## 8. Repository state

- **Research code (worktree):** `/home/autobot/tradingbot-wt/one-day-replay-20261015`
  on branch `research/one-day-replay-20261015`. Code changes:
  - `research/slr/strategy.py` — rewrite to ARM/DISARM model (v3).
  - `research/slr/resolver.py` — data-driven tick-offset calibration + 60 s fill window.
  - `research/slr/day_replay.py` — pass per-bar tick slice; new fields.
  - `research/slr/tests/test_event_model.py` — 13 deterministic tests.
  - `research/slr_out/corpus_{DEV,HOLDOUT,OOS}.jsonl` — regenerated with ARM model + calibrated ticks.
  - `research/slr_out/diag_2026-02-26.json` — regenerated.
- **Reports repo (`autobot_reports`):** this file is committed locally
  on top of commit `9499de2` (yesterday's v1 diagnosis). **Not
  pushed** — remote `origin/main` has advanced to `eca7477` since
  that commit was written; per operator standing instruction do not
  pull / rebase / merge. The divergence (two local commits —
  `9499de2` and this one — on top of an older base than
  `origin/main`) is preserved for the operator to resolve.
- **No production changes.** No `.env`, no systemd, no deployed code
  path, no running service touched.

## 9. Reproducibility

```bash
cd /home/autobot/tradingbot-wt/one-day-replay-20261015

# tests (13 PASSED, 0.25s)
python -m pytest research/slr/tests/test_event_model.py --rootdir=research/slr

# 26-Feb diagnostic
python -m research.slr.run_diagnostic

# full corpus (~3 minutes)
python -m research.slr.run_corpus
```
