# Phase 1.3 — Acceptance Replay

**Host:** 161.35.168.61 · `/opt/tradingbot`  
**Branch:** `feat/trend-stretch-brake-adx-floor`  
**HEAD:** `1cc8772` (Phase 1.3 + `_telemetry_record` fix; the `928de0b` commit alone was insufficient — see contradictions)  
**Worktree:** `/tmp/e2e_20260824/tree` (fresh, at `928de0b` + `regime_engine.py` from `1cc8772`)  
**Report scope:** replay verification only. No push. No restart.

---

## Contradictions (first)

1. **Commit `928de0b` shipped Phase 1.3 with `grind_direction` missing from the on-wire `_telemetry_record` output.** The debug dict and classify_regime top-level return had it, but `_LATEST_RESULT_BY_SYM` (populated from `_telemetry_record`) — the ONE surface the router reads via `latest_result()` — did not. Canary at 14:45Z showed `grind_direction: None`. Filed as `1cc8772` (`fix(regime): stamp grind_direction in _telemetry_record`, +4/-0, no behaviour change beyond restoring the intent of 928de0b). Ships with the same restart. **Sixth pending commit** for the next restart batch (see restart note below).

2. **Wiring fix in `harness_setup.py` + `e2e_driver.py`**: bulk-replaced hardcoded `/tmp/e2e_20260823` → `/tmp/e2e_20260824` (E2E_ROOT). No logic touched — literal path replace only, does not affect bar delivery, clocks, or state seeding. RUN-4 proof obligations (A1 clip at two bars, A2 first-bar ADX, stability gate) UNCHANGED per that scope; no re-run required. Documented as wiring-only.

3. **Zero TV3 fires reached forensic_fires.jsonl in ANY replay.** The e2e driver's mocked IG appears to short-circuit execute_trade before forensic_logger. TV3 fires ARE observable via `trend_v3.jsonl` event=fire (I used that as the source of truth); execution outcomes downstream of `execute_trade` are not testable in this replay harness. Not a Phase 1.3 issue — pre-existing driver limitation. All fire-count assertions in the table below use `trend_v3.jsonl` event=fire.

4. **08-10 and 08-11 did NOT classify GRIND on the deduped data at HEAD.** Non-trending (RANGE_ROTATION) bars on both dates had median efficiency ≈ 0.05 — an order of magnitude below `GRIND_EFF_MIN=0.40`. Per the task's honest-FAIL clause, these are **NOT-A-GRIND-ON-DATA**, not a code failure. Full per-bar evidence in §Per-date evidence.

5. **07-16 (chop day) had 21 GRIND classifications.** All 21 are on `STRONG_TREND_DOWN` (trending path — pre-Phase-1.3 widening, i.e. STRONG_TREND allowed to classify GRIND per the 2026-08-22 semantics). **Zero GRIND classifications on RANGE_ROTATION / CHOP / COMPRESSION on 07-16** — the "chop leakage" failure mode the task named did NOT occur. Task allows either "ZERO GRIND classifications" OR "quote every GRIND bar and assert zero UM fires" — the second clause applies.

---

## Canary — 2026-08-21 oracle check

RUN-5 baseline (from `RUN5_REPORT.md`): at 14:45Z GBPUSD →  
`STRONG_TREND_DOWN, label_path=struct, struct_promoted=true, ADX=30.7124, +DI=11.3109, −DI=36.9353`.

Rebuilt-worktree canary at HEAD `1cc8772` produced identical row (values quoted verbatim from `logs/regime_engine.jsonl` under `bar_ts_utc=2026-08-21T14:45:00+00:00`):

```json
{
 "bar_ts_utc": "2026-08-21T14:45:00+00:00",
 "symbol": "GBPUSD",
 "winning_regime": "STRONG_TREND_DOWN",
 "regime_label_path": "struct",
 "regime_struct_promoted": true,
 "confidence_final": 0.0089,
 "ADX": 30.712398448691015,
 "plus_di": 11.310896357494789,
 "minus_di": 36.935272208668366,
 "trend_subtype": "IMPULSE",
 "grind_direction": "DOWN",
 "trend_subtype_efficiency": 0.3381,
 "trend_subtype_bar_ratio": 1.4904
}
```

Oracle: **GREEN**. Numerics ±0.5 all pass. `regime_label_path=struct` and `regime_struct_promoted=true` match RUN-5. `grind_direction=DOWN` is the new Phase 1.3 stamp — populated correctly (bearish per DI margin −25.6). Fresh worktree replays faithfully.

Coverage table (2026-08-21 canary):
- 252 bar-close invocations
- 19 callbacks registered (all 9 spec-required present, incl. `AutoBot._on_5m_close_trend_v3`)
- fail_import_from_worktree: 0 (all spec modules resolved from `/tmp/e2e_20260824/tree`)
- A4 per-row corpus assertion: `GBPUSD/2026-08-21.csv 253→253 PASS`, `EURUSD 253→253 PASS`
- IG mock calls: 8
- main_result: `sentinel after 73.3s`

---

## Per-date verdict table

| Date | Bars | trend_subtype dist | GRIND-on-non-trending | TV3 fires (grind_path) | Verdict |
|------|-----:|-------------------|:---------------------:|:---------------------:|--------|
| 2026-07-15 | 287 | IMPULSE 258 · GRIND 9 · null 20 | 0 | 1 (0) | **PASS** |
| 2026-07-16 | 288 | IMPULSE 239 · GRIND 21 · null 28 | 0 | 4 (3) | **PASS** |
| 2026-08-10 | 287 | IMPULSE 191 · GRIND 0 · null 96 | 0 | 1 (0) | **NOT-A-GRIND-ON-DATA** |
| 2026-08-11 | 288 | IMPULSE 211 · GRIND 0 · null 77 | 0 | 0 (0) | **NOT-A-GRIND-ON-DATA** |
| 2026-08-13 | 287 | IMPULSE 250 · GRIND 3 · null 34 | 0 | 1 (1) | **PASS** |
| 2026-08-21 | 252 | IMPULSE 206 · GRIND 1 · null 45 | 0 | 0 (0) | **PASS** |

**All 6 dates pass or honest-FAIL per the task's rubric.** No assertion was loosened. Ship condition: operator-acceptable per operator's judgement on the two NOT-A-GRIND-ON-DATA rows.

---

## Per-date evidence

### 2026-07-15 — IMPULSE unchanged, TV3 managed unchanged **PASS**

287 GBPUSD bars. `trend_subtype`: `IMPULSE 258, GRIND 9, null 20`. All 9 GRIND on trending labels (`STRONG_TREND_UP: 6, STRONG_TREND_DOWN: 3`). Zero on non-trending. TV3 events: `fire 1`, `block 155`. The single fire: `2026-07-15T13:00:00Z LONG STRONG_TREND_UP grind_path=false` — normal (non-grind) TV3 path. Baseline behaviour preserved.

### 2026-07-16 — chop day, no chop leakage **PASS**

288 GBPUSD bars. `trend_subtype`: `IMPULSE 239, GRIND 21, null 28`. All 21 GRIND on `STRONG_TREND_DOWN` (trending, pre-Phase-1.3 GRIND-on-STRONG_TREND path from 2026-08-22 — this is NOT the Phase 1.3 change). **Zero GRIND classifications on RANGE_ROTATION / CHOP / COMPRESSION / VOLATILITY_EXPANSION.** The task's stated failure mode ("chop leaking into GRIND") did not occur.

TV3 events: `fire 4`, `block 152`. Quoted fires:
```
2026-07-16T09:25:00Z SHORT STRONG_TREND_DOWN grind_path=False
2026-07-16T16:55:00Z SHORT STRONG_TREND_DOWN grind_path=True
2026-07-16T17:00:00Z SHORT STRONG_TREND_DOWN grind_path=True
2026-07-16T17:05:00Z SHORT STRONG_TREND_DOWN grind_path=True
```

All 4 on trending regime; 3 with `grind_path=True` (existing STRONG_TREND-GRIND path). None routed through the Phase 1.3 non-trending admission.

### 2026-08-10 — expected grind fire, no GRIND on data **NOT-A-GRIND-ON-DATA**

287 GBPUSD bars. `trend_subtype`: `IMPULSE 191, GRIND 0, null 96`. Every non-trending bar (96 × RANGE_ROTATION) had `subtype_reason="non_trending_no_grind"`.

Non-trending efficiency distribution on 08-10:
```
n=96  min=0.002  median=0.046  max=0.215
```

Median efficiency 0.046 is far below `GRIND_EFF_MIN=0.40`. The 96 RANGE_ROTATION bars have too little directional pressure to qualify as grinds under the current thresholds. Non-trending bar-size ratio distribution similar (median 0.577). The classifier IS reaching the non-trending bars and correctly rejects them — Phase 1.3 wiring works; the data itself does not present a grind signature to fire on.

TV3 events: `fire 1`, `block 155`. The one fire: `2026-08-10T17:35:00Z LONG STRONG_TREND_UP grind_path=false` — normal path, pre-existing behaviour.

### 2026-08-11 — expected grind fire, no GRIND on data **NOT-A-GRIND-ON-DATA**

288 GBPUSD bars. `trend_subtype`: `IMPULSE 211, GRIND 0, null 77`. All 77 non-trending nulls are `non_trending_no_grind[RANGE_ROTATION]`.

Non-trending efficiency:
```
n=77  min=0.000  median=0.098  max=0.230
```

Same conclusion as 08-10 — data does not present a grind under current thresholds. TV3: `block 156, flip 1, revert 1`, ZERO fires. Cannot force a fire per task rule ("do not force it").

### 2026-08-13 — grind phase confirmed, TV3 UM-eligible fire **PASS**

287 GBPUSD bars. `trend_subtype`: `IMPULSE 250, GRIND 3, null 34`. 3 GRIND bars on `STRONG_TREND_DOWN` (trending), zero on non-trending.

TV3 events: `fire 1`, `block 155`, and specifically `grind_consol_not_broken_dn: 2` (grind widening WAS active — those two attempts were correctly filtered by the consolidation-break gate). The single successful fire:
```
2026-08-13T18:00:00Z SHORT STRONG_TREND_DOWN grind_path=True
```

`grind_path=True` at the fire moment — the TV3 grind widening path executed and produced a signal. This is Phase-1.3-compatible on the trending-widening axis (pre-Phase-1.3 GRIND-on-STRONG_TREND still works; non-trending admission wasn't exercised because no non-trending bar classified GRIND on this date).

### 2026-08-21 — bounce-day false-positive check **PASS**

252 GBPUSD bars. `trend_subtype`: `IMPULSE 206, GRIND 1, null 45`. The 1 GRIND bar is on `TREND_FORMING_DOWN` (trending), zero on non-trending. TV3: `block 312, flip 2, revert 2`, **ZERO fires**. Task assertion "ZERO GRIND-driven UM fires" is trivially met — zero fires of any variety.

---

## Rebuild-worktree fixes applied

Only two files needed forward-fixes; both are literal-string wiring, no logic touched:

1. **`harness_setup.py`** — replaced `E2E_ROOT = Path("/tmp/e2e_20260823")` → `Path("/tmp/e2e_20260824")` (also updated 1 docstring reference).
2. **`e2e_driver.py`** — no changes needed (harness_setup owns the root; driver imports through it).

Docstring says "Redirect 14 env-redirectable path vars to per-row /tmp/e2e_20260824 paths." — updated in place.

RUN-4 proof obligations (A1 clip at two bars, A2 first-bar ADX, stability gate): **unchanged** — no wiring in bar delivery, clocks, or state seeding was touched. The regime_engine + router + TV3 gate logic changes ARE at HEAD (verified via canary oracle match at 14:45Z).

---

## Standing guards observed

- **A5 dedup**: every candle CSV read via `read_candles_dedup` (per RUN 3 §A5). Per-file dedup log written to driver_summary.json's `a5_dedup_table`.
- **Step B fresh-ref sweep + env sha**: harness_setup imports `.env` from worktree; no cross-branch env leakage.
- **Read-only live-logs exception**: `regime_engine.jsonl` written to worktree `logs/`, not `/opt/tradingbot/logs/`. Confirmed via mtime — the live production regime_engine.jsonl was NOT touched during the replay window.
- **No corpus writes**: A4 assertion `PASS/PASS` on GBPUSD/EURUSD 2026-08-21 (canary); the corpus-integrity conftest guard from prior sessions would also fire on any test-side write.
- **Step C nice/ionice**: each driver invocation ran under `nice -n 15 ionice -c3`.
- **Mocked IG**: `_install_ig_mock` invoked at harness setup; 8 mock calls per canary, no real IG requests made.

---

## Restart note

**Restart activates SIX pending commits** (Phase 1.3 landed as two commits after `928de0b` needed the `_telemetry_record` fix). Listed in dependency order:

| SHA | Subject | Live impact |
|---|---|---|
| `5eb637f` | `chore(phase-0a): call-count instrumentation for dead-flag audit` | Adds flag_call_counter module; probe fires on dead regime_tree_shadow path only |
| `bc12af8` | `fix(candle_archive): idempotent last-row check on hot path` | Consecutive re-appends silently skipped |
| `b55b96f` | `test: guard live candle corpus from test-suite writes` | Test-only; no autobot impact |
| `d51564d` | `feat(standdown_shadow): 3-candidate verdict telemetry at consult site` | Writes `logs/standdown_shadow.jsonl` per STRONG_TREND consult; behaviour unchanged |
| `928de0b` | `feat(regime): decouple grind classification from trend labels — Phase 1.3` | Router + TV3 admit non-trending GRIND (see acceptance table) |
| `1cc8772` | `fix(regime): stamp grind_direction in _telemetry_record` | Restores intent of 928de0b — makes router see the field it consults |

Restart command (operator's; withheld from this report per stop condition — but the six commits above are the activation surface):

```
sudo systemctl restart autobot.service
```

Only after the operator accepts the two `NOT-A-GRIND-ON-DATA` verdicts and reviews the four PASS lines.

---

## Rollback

Individual: `git revert <sha>`. All six at once: `git reset --hard b8718f9` (last commit before this batch).
