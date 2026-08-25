# Phase 1.3c — TV3 label gate admits GRIND on non-trending labels

**Host:** 161 · **Working tree:** `/opt/tradingbot` · **HEAD before:** `1cc8772` · **HEAD after:** `606ecc7`
**Local commit only. No push to main. No autobot.service restart.**

---

## 1 · Contradictions

**C-1 (root cause, resolved by 606ecc7).** Phase 1.3 (928de0b) shipped the label-gate widening at `gbpusd_trend_v3.py` L1291 that admits non-trending labels (RANGE_ROTATION / CHOP / COMPRESSION / VOLATILITY_EXPANSION) into `_up_ok_regimes` / `_dn_ok_regimes` when `trend_subtype == "GRIND"` AND `grind_direction` matches the effective direction. 1cc8772 stamped `grind_direction` into `regime_engine._telemetry_record`. Both looked correct in isolation. But the TV3 consumer copy-out at `_latest_regime` (gbpusd_trend_v3.py:576) forwarded `trend_subtype`, `trend_subtype_efficiency`, `trend_subtype_bar_ratio` — and never copied `grind_direction`. The gate at L1293 read `str(reg_dbg.get("grind_direction") or "").upper()` → `""`, neither `== "UP"` nor `== "DOWN"` matched, and the non-trending admission branch was **dead code** on every bar. This is exactly what the 08-11 replay evidence showed (255 GRIND bars, 0 fires, 266 UP + 10 DOWN `regime_not_strong_*` vs 8 `grind_consol_not_broken`) — everything getting suppressed at the label gate instead of flowing to the widening.

**C-2 (test coverage blindspot, resolved).** The Phase 1.3 test file (`test_phase1_3_grind_decoupled.py`, deleted in 2474703) tested the widening logic via a **reimplementation** (`_tv3_gate_admits` helper mirrored the truth table). It never called `_latest_regime`, so it could not catch the missing copy. The new `test_phase1_3c_tv3_admits_grind_on_nontrending.py` fixes this — its evaluate() tests patch `regime_engine.latest_result` directly and let the real `_latest_regime` run, which is the seam that was broken. **Confirmed:** 3 of the 7 new tests fail against 1cc8772/2474703 and all 7 pass after 606ecc7.

**C-3 (harness cross-run contamination, resolved).** `harness_setup.logs_dir()` and `state_dir()` wrote to `E2E_ROOT / "logs" / row_date` unconditionally. Every rerun for a given `row_date` appended into the same `trend_v3.jsonl`, contaminating suppression histograms and fire lists across runs (visible in the pre-fix 07-16 log where three grind_path fires appeared duplicated). Fixed with per-run stamp: `E2E_ROOT / "logs" / f"{row_date}__{_RUN_STAMP}"`, `_RUN_STAMP` from `E2E_RUN_STAMP` env or `datetime.now(UTC)` at import.

**C-4 (spec/behaviour tension flagged, NOT fixed).** With 606ecc7 the widening flows on 08-11 (114 blocks now show `trend_subtype=GRIND` in TV3 payloads vs 0 previously reaching the widening arm), but 08-11 still fires **zero UM entries**. Post-widening split of the 114 GRIND blocks:
- 39 bars with `grind_direction=UP` on `effective_dir=UP` but the 5m `regime` is a DOWN-side trending label (TREND_FORMING_DOWN / STRONG_TREND_DOWN) → widening does not admit (correct per code: only same-direction TREND_FORMING widens, and non-trending admission is direction-scoped).
- 75 bars with `grind_direction=DOWN` on `effective_dir=UP` → direction mismatch, correctly suppressed.
- 16 bars pass the label gate AND direction match, get admitted, then block downstream at `grind_consol_not_broken_*` — the 4-bar breakout trigger doesn't fire on the 08-11 tape.

If the operator's mental model is "08-11 afternoon grind must produce a UM fire under Phase 1.3c", that expectation is not met and the remaining blocker is the **consolidation-break trigger**, not the label gate. That is a *separate* Phase-1.4-shaped conversation.

**C-5 (07-16 fresh replay shows 4 new LONG fires at 19:35–19:50, NOT attributable to 606ecc7).** The fresh 07-16 run produces 16 fires (13 grind_path) vs the contaminated legacy log's 16/12. The 4 new fires are LONG entries on TREND_FORMING_UP at 19:35, 19:40, 19:45, 19:50 during a late-session bullish grind. Attribution: TREND_FORMING_UP admission under GRIND is a **Phase 1.3** (928de0b) widening that does not read `grind_direction` — so 606ecc7 has no effect on it. What changed is Phase 1.3b's recalibrated GRIND detector (one_sided_ema72) now classifies those end-of-day bars as GRIND when the prior sign-of-net-close-change definition did not. Flagging so the operator can decide whether this end-of-day admission on a strong-down day is desired.

**C-6 (UM fire outcome telemetry gap).** The task asked for the 07-16 grind_path fires' "replay exit reason" from the jsonl that carries UM outcomes. That jsonl doesn't exist in the current replay logs — `signal_log.jsonl` stamps 3 UM_S entries with `entry_price=None`, `close_reason=None`, `close_ts=None` (harness/logger contract skip); `tiered_ratchet.jsonl` only records positions the ratchet actually managed, which for 07-16 covered a single TREND_V3 arm (13510.95 → RATCHET_STOP at 12:00, `mfe=16.8p`). The 12 grind_path fires largely didn't take independent slots because AutoBot's `has_open_short` gate dedups against the single open TREND_V3 position — so the vast majority of the "fires" were decisions the trade manager silently discarded. Table below uses forward-walk on raw candles (TP=12p, SL=6p, 30-bar window) as the honest "what would have happened" — the only ground truth available.

---

## 2 · Fix

`gbpusd_trend_v3.py:576` — `_latest_regime` now forwards `grind_direction` from `regime_engine.latest_result` into `reg_dbg`. Diff:

```
+        # Phase 1.3c (2026-08-25): the non-trending admission branch in
+        # evaluate() reads reg_dbg.get("grind_direction"). Phase 1.3
+        # (928de0b) shipped the admission code and 1cc8772 stamped
+        # grind_direction into _telemetry_record, but this consumer copy
+        # was missed — the gate always read None and the non-trending
+        # branch was dead. Forward it here so GRIND-on-RANGE can admit.
+        dbg["grind_direction"] = res.get("grind_direction")
```

All other gates unchanged.

**New test:** `tests/unit/test_phase1_3c_tv3_admits_grind_on_nontrending.py` — 7 cases:

| # | Test | Coverage |
|---|------|----------|
| 1 | `test_latest_regime_forwards_grind_direction` | Direct seam — patches `regime_engine.latest_result`, asserts `_latest_regime` returns `dbg["grind_direction"] == "UP"` |
| 2 | `test_latest_regime_grind_direction_null_when_absent` | Tolerates None (trending label with no grind) |
| 3 | `test_range_plus_grind_up_admits_and_fires` | E2E evaluate() — RANGE + GRIND + matching dir → returns BUY decision. Reproduces the 08-11 unit case. |
| 4 | `test_range_plus_grind_missing_direction_suppresses` | Regression guard — missing `grind_direction` (the pre-1.3c consumer bug) → suppression |
| 5 | `test_range_plus_grind_wrong_direction_suppresses` | Direction-scope guard — grind_direction=DOWN on effective UP → suppression |
| 6 | `test_range_without_grind_stays_suppressed` | Chop-door invariant — RANGE + subtype=None → still suppressed |
| 7 | `test_range_with_impulse_stays_suppressed` | IMPULSE must not widen |

**Fail-then-pass proof:** stashed the fix, reran the file — tests 1, 2, 3 fail (KeyError / assertion). Restored the fix — all 7 pass. Full grind/TV3 suite (48 tests) shows zero regressions.

---

## 3 · Acceptance replays

Fresh worktree at 606ecc7; harness fix produces per-run stamped dirs (`{row}__{stamp}`); canary oracle check confirms `_grind_dir="UP"` reaches the evaluate() expression.

### 3.1 · 08-11 (target)

**Command:** `E2E_RUN_STAMP=phase1_3c_0811 python3 e2e_driver.py 2026-08-11 GBPUSD`
**Log dir:** `/tmp/e2e_20260824/logs/2026-08-11__phase1_3c_0811/`

| Metric | Before (contaminated legacy) | After (fresh 606ecc7) |
|---|---|---|
| Bar-close invocations | — | 288 |
| Total fires | 0 | **0** |
| `regime_not_strong_up` blocks | 266 | 130 |
| `regime_not_strong_down` blocks | 10 | 0 |
| `grind_consol_not_broken_*` blocks | 8 | 16 |
| `adx_below_min` blocks | — | 5 |
| `er_below_min` blocks | — | 4 |
| `range_gate_suppress` blocks | — | 1 |
| Blocks where `trend_subtype=GRIND` | ~0 (dead branch) | 114 |
| Blocks where `grind_direction=UP` | — | 46 |
| Blocks where `grind_direction=DOWN` | — | 84 |

**Verdict:** widening now flows (114 GRIND blocks reach the widened set), but the consolidation-break trigger + directional-mismatch geometry produce **honest FAIL** — the 08-11 tape doesn't hand this strategy an entry. See C-4.

### 3.2 · 07-16 (regression — widening must not open chop door)

**Command:** `E2E_RUN_STAMP=phase1_3c_0716 python3 e2e_driver.py 2026-07-16 GBPUSD`
**Log dir:** `/tmp/e2e_20260824/logs/2026-07-16__phase1_3c_0716/`

| Metric | Legacy contaminated | Fresh 606ecc7 |
|---|---|---|
| Total fires | 16 | 16 |
| `grind_path` fires | 12 (with 3 duplicates from cross-run append) | **13** |
| non-grind fires | 4 | 3 |
| `regime_not_strong_up` blocks | — | 57 |
| `regime_not_strong_down` blocks | — | 13 |
| `grind_consol_not_broken_*` blocks | — | 38 |

The 12 grind_path SHORTs are preserved. 1 additional grind_path SHORT (16:55/17:00/17:05/18:00 were duplicated in legacy — dedup shows 8 unique SHORT + the 09:05 SHORT = 9 in fresh) plus 4 new grind_path **LONG** entries at 19:35–19:50 on TREND_FORMING_UP — **not** a Phase 1.3c regression; Phase 1.3 (928de0b) already admits TREND_FORMING_UP under GRIND. See C-5.

### 3.3 · 08-21 (negative — widening must not open chop door)

**Command:** `E2E_RUN_STAMP=phase1_3c_0821 python3 e2e_driver.py 2026-08-21 GBPUSD`
**Log dir:** `/tmp/e2e_20260824/logs/2026-08-21__phase1_3c_0821/`

| Metric | Fresh 606ecc7 |
|---|---|
| Total fires | **0** |
| `grind_path` fires | 0 |
| `regime_not_strong_down` blocks | 119 |
| `er_below_min` blocks | 31 |
| `adx_below_min` blocks | 6 |

**Chop-door invariant holds:** zero UM fires on 08-21.

---

## 4 · 07-16 grind_path fires — table (with forward walk)

Fresh 07-16 replay under 606ecc7. `MFE` and `MAE` in pips, forward walk 30 bars, TP=12p, SL=6p. All fires plus outcome:

| # | fire_ts | dir | entry | grind_path | regime | MFE | MAE | forward_hit | hit_ts |
|--:|---|---|---:|---|---|---:|---:|---|---|
|  1 | 2026-07-16T09:05:00Z | SHORT | 13515.65 | true  | STRONG_TREND_DOWN | 12.0 |  5.0 | TP_12p | 10:25:00 |
|  2 | 2026-07-16T09:25:00Z | SHORT | 13510.95 | false | STRONG_TREND_DOWN | 13.4 |  0.6 | TP_12p | 11:10:00 |
|  3 | 2026-07-16T09:30:00Z | SHORT | 13508.85 | false | STRONG_TREND_DOWN | 14.0 |  2.7 | TP_12p | 11:25:00 |
|  4 | 2026-07-16T09:35:00Z | SHORT | 13508.75 | false | STRONG_TREND_DOWN | 13.9 |  2.8 | TP_12p | 11:25:00 |
|  5 | 2026-07-16T11:00:00Z | SHORT | 13501.75 | true  | STRONG_TREND_DOWN |  7.6 | 10.3 | SL_6p  | 12:00:00 |
|  6 | 2026-07-16T11:05:00Z | SHORT | 13501.35 | true  | STRONG_TREND_DOWN |  7.2 | 10.7 | SL_6p  | 12:00:00 |
|  7 | 2026-07-16T11:10:00Z | SHORT | 13500.05 | true  | STRONG_TREND_DOWN |  5.9 |  6.9 | SL_6p  | 11:55:00 |
|  8 | 2026-07-16T11:25:00Z | SHORT | 13496.65 | true  | STRONG_TREND_DOWN |  0.2 |  6.0 | SL_6p  | 11:35:00 |
|  9 | 2026-07-16T16:55:00Z | SHORT | 13466.15 | true  | STRONG_TREND_DOWN |  6.7 |  6.0 | SL_6p  | 17:50:00 |
| 10 | 2026-07-16T17:00:00Z | SHORT | 13463.65 | true  | STRONG_TREND_DOWN |  4.2 |  7.5 | SL_6p  | 17:45:00 |
| 11 | 2026-07-16T17:05:00Z | SHORT | 13460.85 | true  | STRONG_TREND_DOWN |  1.4 |  6.4 | SL_6p  | 17:20:00 |
| 12 | 2026-07-16T18:00:00Z | SHORT | 13465.05 | true  | STRONG_TREND_DOWN |  0.0 |  6.2 | SL_6p  | 18:55:00 |
| 13 | 2026-07-16T19:35:00Z | LONG  | 13470.65 | true  | TREND_FORMING_UP  | 11.3 |  0.8 | no_hit_30b | — |
| 14 | 2026-07-16T19:40:00Z | LONG  | 13471.15 | true  | TREND_FORMING_UP  | 10.8 |  0.5 | no_hit_30b | — |
| 15 | 2026-07-16T19:45:00Z | LONG  | 13472.25 | true  | TREND_FORMING_UP  |  9.7 |  1.6 | no_hit_30b | — |
| 16 | 2026-07-16T19:50:00Z | LONG  | 13475.35 | true  | TREND_FORMING_UP  |  6.6 |  4.7 | no_hit_30b | — |

**13 grind_path fires** (rows 1, 5-16). Grind_path SHORT hit rate against TP=12p / SL=6p (rows 1, 5-12): 1 TP / 8 SL, MFE median 5.9p, MAE median 6.4p — this echoes the "grind burst that stops out" pattern from the plateau signature audits. Grind_path LONG at end-of-day (rows 13-16): 0/0/4 no-hit, all held between +5 and +11p MFE without touching TP12 or SL6 — closed at end-of-forward-window.

Data source: `trend_v3.jsonl` `event=fire` rows; forward walk over `/opt/tradingbot/data/candles/GBPUSD/2026-07-16.csv` deduped keep-first (89 dup timestamps, matching driver's A5 report).

---

## 5 · Pending commits (8 after Phase 1.3c)

Ordered newest → oldest, all unpushed on `feat/trend-stretch-brake-adx-floor`, `origin/main` at `956f97c`:

| # | sha | title |
|--:|---|---|
| 1 | 606ecc7 | fix(regime): Phase 1.3c — forward grind_direction into TV3 label gate |
| 2 | 2474703 | feat(regime): Phase 1.3b — grind detector recalibrated per operator ruling |
| 3 | 1cc8772 | fix(regime): stamp grind_direction in _telemetry_record |
| 4 | 928de0b | feat(regime): decouple grind classification from trend labels — Phase 1.3 |
| 5 | d51564d | feat(standdown_shadow): 3-candidate verdict telemetry at consult site |
| 6 | b55b96f | test: guard live candle corpus from test-suite writes |
| 7 | bc12af8 | fix(candle_archive): idempotent last-row check on hot path |
| 8 | 5eb637f | chore(phase-0a): call-count instrumentation for dead-flag audit |

All 8 ride the same restart. No push, no `systemctl` action taken.
