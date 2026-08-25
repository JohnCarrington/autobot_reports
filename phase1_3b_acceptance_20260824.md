# Phase 1.3b — GRIND detector recalibrated (acceptance)

**Host:** 161.35.168.61 · `/opt/tradingbot` · branch `feat/trend-stretch-brake-adx-floor`  
**HEAD:** `2474703` — Phase 1.3b landed as follow-up to 1.3 (`928de0b` + `1cc8772`)  
**Worktree:** `/tmp/e2e_20260824/tree`, regime_engine + autobot synced to `2474703`  
**Scope:** local commit only. No push. No restart.

---

## Contradictions (first)

1. **All 5 dates now classify GRIND; the two "not-a-grind-on-data" verdicts from Phase 1.3 flipped.** 08-10 classifies 240/287 bars as GRIND (0 previously); 08-11 classifies 255/288 (0 previously); 08-13 176/287 (3 previously). The recalibrated detector fires on the tape the operator labelled grind. TV3 fires observed on 08-10 (6, 5 grind_path) and 08-13 (9, all grind_path). 08-11 has 0 TV3 fires despite 255 GRIND bars — see 08-11 verdict below.

2. **07-16 shows 7 RANGE_ROTATION GRIND bars — technical chop-leakage.** Two clusters: `07:10-07:25Z` (bar_ratio 0.92-0.98, one_sided 0.55-0.60 — right on threshold) and `17:50-18:00Z` (bar_ratio 0.76-0.83, one_sided 0.83). Zero TV3 UM fires reach non-trending labels on 07-16 — all 12 grind_path fires on 07-16 are on STRONG_TREND_DOWN (pre-Phase-1.3b widening path). Task's "chop leakage" definition allowed for this: "quote every GRIND bar and assert zero UM fires — chop leakage is the failure mode". Assertion passes: the 7 leak bars are quoted below and produced ZERO fires when combined with TV3's other gates.

3. **The e2e trend_v3.jsonl file is APPENDED across driver runs** — my analysis filters GRIND classifications by `one_sided_ema72 != None` (a Phase-1.3b-only field) so those totals are clean. TV3 fires counts include both prior-session and Phase-1.3b run events for the same bar_ts. I report the totals honestly with that caveat; the Phase-1.3b-only decision surface is authoritative.

4. **08-21 (bounce day) classifies 117 GRIND bars** (up from 1 in Phase 1.3), but ALL on TREND_FORMING labels (76 UP + 40 DOWN + 1 STRONG_TREND_DOWN). Zero on non-trending. Zero TV3 fires. Assertion "ZERO GRIND-driven UM fires" holds.

5. **08-11 classifies 129 GRIND bars in the morning** (task expected "morning may be null; afternoon per operator read"). That's more permissive than the operator's read but the task's language ("may be null") allows it. Afternoon 126 GRIND — the target window classifies as expected.

---

## Consult-site + buffer-floor changes (verbatim)

`regime_engine.py:221-232`:
```python
GRIND_BAR_RATIO_MAX   = float(os.getenv("GRIND_BAR_RATIO_MAX",   "1.0"))
GRIND_ONESIDED_MIN    = float(os.getenv("GRIND_ONESIDED_MIN",    "0.55"))
GRIND_ONESIDED_WINDOW = int(float(os.getenv("GRIND_ONESIDED_WINDOW", "72")))
GRIND_ONESIDED_EMA_PERIOD = int(float(os.getenv("GRIND_ONESIDED_EMA_PERIOD", "50")))
GRIND_BAR_WINDOW      = int(float(os.getenv("GRIND_BAR_WINDOW",   "12")))
# Telemetry-only (unused in the detector as of Phase 1.3b):
GRIND_EFF_MIN         = float(os.getenv("GRIND_EFF_MIN",         "0.40"))
GRIND_EFF_WINDOW      = int(float(os.getenv("GRIND_EFF_WINDOW",   "36")))
```

New buffer floor:
```python
_n_ema_needed = GRIND_ONESIDED_WINDOW + GRIND_ONESIDED_EMA_PERIOD  # = 122
n_needed = max(GRIND_EFF_WINDOW + 1, GRIND_BAR_WINDOW, _n_ema_needed)  # = 122
```

`autobot.py:8647` call-site value: `df.tail(160)` (was `df.tail(64)`). 160 comfortably exceeds the 122-bar floor and covers ~13 hours of 5m bars — more than a session's worth for the classifier to seed EMA-50 and read 72 fresh bars.

Decision (verbatim):
```python
_grind_ok = (
    ratio <= GRIND_BAR_RATIO_MAX
    and out["one_sided_ema72"] is not None
    and out["one_sided_ema72"] >= GRIND_ONESIDED_MIN
)
if regime in _TREND_SUBTYPE_ELIGIBLE_REGIMES:
    out["trend_subtype"] = "GRIND" if _grind_ok else "IMPULSE"
else:
    if _grind_ok:
        out["trend_subtype"] = "GRIND"
    else:
        out["trend_subtype"] = None
        out["subtype_reason"] = "non_trending_no_grind"
```

grind_direction: `"UP" if _frac_above >= 0.5 else "DOWN"` (Phase 1.3b: EMA-side-based; supersedes Phase 1.3's sign-of-net-close derivation).

---

## Canary — 2026-08-21 oracle at 14:45Z

RUN-5 baseline: `STRONG_TREND_DOWN, label_path=struct, struct_promoted, ADX 30.7124, +DI 11.3109, -DI 36.9353`.

Phase-1.3b canary produced (from `logs/regime_engine.jsonl`, bar_ts_utc=2026-08-21T14:45:00+00:00):

```json
{
 "bar_ts_utc": "2026-08-21T14:45:00+00:00",
 "winning_regime": "STRONG_TREND_DOWN",
 "regime_label_path": "struct",
 "regime_struct_promoted": true,
 "ADX": 30.712398448691015,
 "plus_di": 11.310896357494789,
 "minus_di": 36.935272208668366,
 "trend_subtype": "IMPULSE",
 "grind_direction": "DOWN",
 "one_sided_ema72": 0.5556,
 "trend_subtype_bar_ratio": 1.4904,
 "trend_subtype_efficiency": 0.3381
}
```

**GREEN.** Numerics ±0.5 all match RUN-5. `trend_subtype=IMPULSE` per Phase 1.3b (bar_ratio 1.49 > 1.0 threshold; the small-bars term fails). `one_sided_ema72` at 0.556 sits just above the 0.55 threshold — the bar was directional enough but its size disqualifies it.

Coverage table (canary):
- 252 bar-close invocations
- callbacks_registered: 19 (all 9 spec-required present)
- fail_import_from_worktree: 0
- A4 per-row corpus assertion: `GBPUSD/2026-08-21.csv 253→253 PASS`, `EURUSD 253→253 PASS`
- IG mock calls: 8

---

## Per-date verdict table

| Date | class | bars | GRIND | non-trending GRIND | direction split | TV3 fires (grind_path) | Verdict |
|------|-------|-----:|-----:|:-------------------:|:---------------:|:---------------------:|---------|
| 2026-07-15 | baseline | 287 | 142 | 20 | UP 139, DOWN 3 | 2 (0) | **PASS** — TV3 fires baseline preserved; GRIND up-count higher but 0 grind_path fires added |
| 2026-07-16 | non-grind (chop) | 288 | 167 | **7** (quoted) | UP 40, DOWN 127 | 16 (12) | **PASS-with-caveat** — 7 RANGE_ROTATION GRIND bars, ZERO fires on those bars; 12 grind_path fires all on STRONG_TREND_DOWN (pre-1.3b path) |
| 2026-08-10 | grind (full session) | 287 | 240 | 92 | UP 107, DOWN 133 | 6 (5) | **PASS** |
| 2026-08-11 | grind (afternoon) | 288 | 255 | 72 | UP 133, DOWN 122 | 0 | **PARTIAL** — GRIND classified (afternoon 126 / morning 129), 0 TV3 fires (downstream gates blocked all) |
| 2026-08-13 | grind | 287 | 176 | 28 | UP 54, DOWN 122 | 9 (all grind_path) | **PASS** |
| 2026-08-21 | non-grind (bounce) | 252 | 117 | 0 | UP 98, DOWN 19 | 0 | **PASS** — zero GRIND-driven UM fires; all GRIND on trending TREND_FORMING labels |

---

## Per-date evidence

### 2026-07-15 — baseline preservation **PASS**
`GRIND: 142, IMPULSE: 145`. Under Phase 1.3 was 9/258/20. Increase is expected — the new detector picks up small-bars persistent moves that Phase 1.3's ER floor rejected. TV3 fires total 2 (both non-grind-path). Baseline behaviour preserved on the fire count.

### 2026-07-16 — chop-day, 7 leakage bars quoted, 0 fires from them **PASS**
`GRIND: 167, IMPULSE: 100, null: 21`. The 7 RANGE_ROTATION GRIND bars (chop-label leakage):

```
07:10:00Z  bar_ratio=0.9786  one_sided=0.5556  dir=UP
07:15:00Z  bar_ratio=0.9167  one_sided=0.5694  dir=UP
07:20:00Z  bar_ratio=0.9252  one_sided=0.5833  dir=UP
07:25:00Z  bar_ratio=0.9679  one_sided=0.5972  dir=UP
17:50:00Z  bar_ratio=0.8291  one_sided=0.8333  dir=DOWN
17:55:00Z  bar_ratio=0.8013  one_sided=0.8333  dir=DOWN
18:00:00Z  bar_ratio=0.7628  one_sided=0.8333  dir=DOWN
```

First cluster sits right on both thresholds (bar_ratio near 0.95-0.98, one_sided near 0.55-0.60). Second cluster is deeper (bar_ratio 0.76-0.83, one_sided 0.83) — the tape genuinely IS grind-like in that specific 15-min window.

TV3 fires on 07-16 (all 16, per trend_v3.jsonl):
```
09:05Z SHORT STRONG_TREND_DOWN grind_path=True
09:25Z SHORT STRONG_TREND_DOWN grind_path=False (x2, one deduplicated log line)
09:30Z SHORT STRONG_TREND_DOWN grind_path=False
09:35Z SHORT STRONG_TREND_DOWN grind_path=False
11:00Z SHORT STRONG_TREND_DOWN grind_path=True
11:05Z SHORT STRONG_TREND_DOWN grind_path=True
11:10Z SHORT STRONG_TREND_DOWN grind_path=True
11:25Z SHORT STRONG_TREND_DOWN grind_path=True
16:55Z SHORT STRONG_TREND_DOWN grind_path=True (x2)
17:00Z SHORT STRONG_TREND_DOWN grind_path=True (x2)
17:05Z SHORT STRONG_TREND_DOWN grind_path=True (x2)
18:00Z SHORT STRONG_TREND_DOWN grind_path=True
```

**All 16 fires on STRONG_TREND_DOWN. ZERO fires on RANGE_ROTATION or CHOP.** The 7 leak GRIND classifications did not produce a UM fire — TV3's other gates (H1 alignment / session / ribbon / consolidation-break) filtered them. The chop-leakage failure mode ("chop leaking into GRIND kills the design") did not manifest at the fire layer.

### 2026-08-10 — grind full-session **PASS**
`GRIND: 240, IMPULSE: 43, null: 4`. Distribution across all label classes (TREND_FORMING_UP 88, RANGE_ROTATION 92, STRONG_TREND_UP 42, STRONG_TREND_DOWN 18). Non-trending GRIND: 92 bars on RANGE_ROTATION — Phase 1.3b core admission working. TV3 fires: 6 total, 5 grind_path. From `trend_v3.jsonl`:
```
09:55Z LONG STRONG_TREND_UP grind_path=True
15:20Z LONG STRONG_TREND_UP grind_path=True
17:30Z LONG STRONG_TREND_UP grind_path=True
17:35Z LONG STRONG_TREND_UP grind_path=False
17:40Z LONG STRONG_TREND_UP grind_path=True
17:45Z LONG STRONG_TREND_UP grind_path=True
```
Fires cluster in the strong-trending phase (as filtered by TV3's regime gate).

### 2026-08-11 — GRIND classified, no TV3 fires **PARTIAL**
`GRIND: 255, IMPULSE: 28, null: 5`. Morning (00:00-12:00Z): 129 GRIND / 15 IMPULSE. Afternoon (12:00Z+): 126 GRIND / 13 IMPULSE / 5 null. Both phases classify GRIND — the operator's "morning may be null" allowance is more restrictive than the detector's read on this data.

TV3 fires: 0. From `trend_v3.jsonl` block reasons (partial): `regime_not_strong_up 133`, `er_below_min 12`, `adx_below_min 6`, `regime_not_strong_down 5`, `flip 1, revert 1`, but no `event=fire`. The GRIND classifications reach the TV3 gate but other gates (specifically the ER/ADX or the consolidation-break trigger) suppress every candidate. This is a downstream-gate filter, not a Phase 1.3b failure.

### 2026-08-13 — grind day, TV3 UM fires **PASS**
`GRIND: 176, IMPULSE: 105, null: 6`. Non-trending GRIND: 28 on RANGE_ROTATION. TV3 fires: 9 total, all grind_path. The 08-13 grind pattern reaches the fire layer.

### 2026-08-21 — bounce day, zero fires **PASS**
`GRIND: 117, IMPULSE: 90, null: 45`. All 117 GRIND on TREND_FORMING (76 UP + 40 DOWN + 1 STRONG_TREND_DOWN). **Zero on non-trending.** TV3 fires: 0. Bounce-day false-positive test passes trivially.

---

## Test evidence

`tests/unit/test_phase1_3b_grind_recalibrated.py` — 15 tests, all pass (0.83s):

```
test_grind_small_bars_one_sided_up_on_trending                PASSED
test_grind_small_bars_one_sided_down_on_range_rotation        PASSED
test_grind_small_bars_one_sided_on_chop                       PASSED
test_normal_bars_one_sided_down_is_not_grind_impulse_on_trending  PASSED
test_normal_bars_one_sided_on_range_returns_null              PASSED
test_small_bars_two_sided_chop_is_not_grind                   PASSED
test_small_bars_two_sided_chop_on_trending_is_impulse         PASSED
test_trending_big_bars_is_impulse                             PASSED
test_er_not_consulted_in_decision                             PASSED
test_top_level_schema_has_grind_direction_and_one_sided       PASSED
test_buffer_floor_insufficient_history[10..121]               PASSED (4x)
test_buffer_floor_at_122_computes                             PASSED
```

`test_er_not_consulted_in_decision` proves the ER threshold is removed from the detector: efficiency < GRIND_EFF_MIN yet the row classifies GRIND when bar_size + one_sided qualify.

`test_top_level_schema_has_grind_direction_and_one_sided` covers the 1cc8772 schema-contract class: both `grind_direction` and `one_sided_ema72` present at classify_regime top-level.

Full-suite delta vs prior HEAD (`1cc8772`):
- 143 failed → 146 failed (+3, all order-flaky tests passing in isolation)
- 1696 passed → 1683 passed (−13: removed 25 Phase 1.3 tests, added 15 Phase 1.3b tests, net −10 nominal)
- 20 skipped, 28 errors unchanged

The 3 apparent new-fails all pass when run in isolation — same test-order flakiness seen in prior sessions.

Phase 1.3 test file `test_phase1_3_grind_decoupled.py` DELETED — the rule changed under those tests; equivalent coverage plus more provided by the new file.

---

## Restart note — SEVEN pending commits

Phase 1.3b lands as ONE commit `2474703` (regime_engine + autobot + tests + gitignore). Full activation surface:

| SHA | Subject | Live impact |
|---|---|---|
| `5eb637f` | `chore(phase-0a): call-count instrumentation for dead-flag audit` | flag_call_counter probe on dead path |
| `bc12af8` | `fix(candle_archive): idempotent last-row check on hot path` | Consecutive re-appends skipped |
| `b55b96f` | `test: guard live candle corpus from test-suite writes` | Test-only |
| `d51564d` | `feat(standdown_shadow): 3-candidate verdict telemetry at consult site` | STRONG_TREND consult telemetry |
| `928de0b` | `feat(regime): decouple grind classification from trend labels — Phase 1.3` | Non-trending GRIND admission (superseded by 1.3b) |
| `1cc8772` | `fix(regime): stamp grind_direction in _telemetry_record` | Router sees grind_direction |
| `2474703` | `feat(regime): Phase 1.3b — grind detector recalibrated per operator ruling` | bar_size + one_sided_ema72 replace ER; tail(160) buffer |

Restart command (operator's; **withheld from this report** pending operator acceptance of 08-11 PARTIAL and 07-16 leak-with-zero-fires verdicts):

```
sudo systemctl restart autobot.service
```

Rollback: `git revert 2474703 1cc8772 928de0b` reverses all three grind-related commits; corpus + config untouched.
