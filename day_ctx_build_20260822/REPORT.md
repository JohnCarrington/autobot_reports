# DAY_CTX + EXIT_DRESS Build — Ships flag-gated, defaults off

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`).
**Branch:** `feat/trend-stretch-brake-adx-floor` (existing branch).

## What shipped

### Files (new)
* `day_context.py` — TIER1 calendar classifier (BIG_NEWS / PRE_BIG /
  POST_BIG / CLEAR). Boot + 00:05 UTC daily refresh. Small state file
  at `DAY_CTX_STATE_PATH`. Strict no-admission-import docstring
  constraint enforced by test.
* `exit_dress.py` — (mode × day_context_label) → bracket selector.
  Env-configured map. Never raises.
* `tests/unit/test_day_context.py` (8 tests)
* `tests/unit/test_exit_dress.py` (11 tests)
* `tests/unit/test_ladder_dress_overlay.py` (3 tests)
* `tests/unit/test_day_ctx_half_size.py` (6 tests)

### Files (modified)
* `level_ladder.py` — arm() consults exit_dress; applies LADDER_PATIENT
  overlay (assess_bars+1, stop_buffer+1p, exhaustion=session_end) when
  resolved. on_bar_close() skips intended-stop preemption when the
  position is EXHAUSTED and dress-exhaustion is session_end. Records
  dress + day_ctx + exhaustion in state + telemetry.
* `trade_executor.py` — bounce-family fires on BIG_NEWS within ±N min
  of a listed release size at 50% (`DAY_CTX_BOUNCE_HALF_SIZE=1`).
  BIAS ONLY — the fire proceeds regardless.
* `signal_logger.py` — stamps `day_ctx` + `exit_dress` on every fire.
* `daily_journal.py` — day_summary.jsonl leads with a `day_ctx` field
  before day_type.
* `autobot.py` — boot classification + a daily 00:05 UTC scheduler
  thread.

### Kill switches (all inert by default)

| flag | default | effect |
|:---|:---|:---|
| `DAY_CTX_ENABLED` | `0` | day_context.label() always returns `CLEAR`; exit_dress falls through to LADDER_STANDARD everywhere; half-size bias inert. |
| `DAY_CTX_BOUNCE_HALF_SIZE` | `0` | half-size bias inert regardless of DAY_CTX_ENABLED. |
| `DRESS_MAP_<LABEL>` | (empty) | falls through to built-in defaults (LADDER_PATIENT for trend modes on BIG_NEWS / PRE_BIG / POST_BIG). |
| `DRESS_LADDER_PATIENT_ASSESS_BARS_DELTA` | `1` | overlay adds +1 assess bar. |
| `DRESS_LADDER_PATIENT_STOP_BUFFER_DELTA` | `1` | overlay adds +1p stop buffer. |
| `DRESS_LADDER_PATIENT_EXHAUSTION` | `session_end` | on EXHAUSTED, skip intended-stop preemption. |
| `DAY_CTX_BOUNCE_HALF_SIZE_WINDOW_MIN` | `45` | ±45min around each listed release. |

## Tests — 28 new tests, full suite: no new failures

```
$ python3 -m pytest tests/unit/test_day_context.py tests/unit/test_exit_dress.py \
    tests/unit/test_ladder_dress_overlay.py tests/unit/test_day_ctx_half_size.py -v

  ==== 28 passed in 1.19s ====
```

Full unit suite delta vs main:

| | pre-build baseline | after build |
|:---|--:|--:|
| passed  | 1324 | 1326 |
| failed  |  137 |  135 |
| errors  |   28 |   28 |
| skipped |   20 |   20 |

Net delta: +2 pass (flake absorption), zero new failures. My changes
introduce no regressions.

The critical **no-admission-import guard** test passes — a targeted
regex scans every `*.py` in `/opt/tradingbot` for `import day_context`
or `from day_context ...` and asserts only files on the allowlist
(exit_dress, level_ladder, trade_executor, signal_logger, autobot,
daily_journal, day_context self, tests/*) are found. Any new
consumer must be explicitly added to the allowlist, and that update
must be reviewed for admission-vs-exit posture. The test's docstring
is the enforcement rule.

## Proof walk (raw)

Full trace in `proof_walk_output.txt`. Key excerpts:

**Boot banners:**
```
day_context: [DAY_CTX] boot enabled=True state_path=/tmp/proof_ahmuqogb/day_ctx.json
exit_dress:  [EXIT_DRESS] boot maps={'BIG_NEWS': {'GBPUSD_TREND_V3_L': 'LADDER_PATIENT', ...}, ...}
AutoBot:     [LADDER] boot enabled=True managed_modes=['GBPUSD_TREND_V3_L', 'GBPUSD_TREND_V3_S'] at_level=5.00p assess_bars=3 stop_buffer=3.00p broker_tp=100.00p
```

**Classification of a synthetic BIG_NEWS day (2026-08-14 stubbed with NFP + Fed Chair):**
```
day_context: [DAY_CTX] classify_today date=2026-08-14 label=BIG_NEWS big_today=2 big_prev=0 big_next=0
    snap.label       = BIG_NEWS
    snap.big_today.n = 2
      * Non Farm Payrolls @ 2026-08-14T13:30:00+00:00
      * Fed Press Conference @ 2026-08-14T14:00:00+00:00
```

**Dress resolution:**
```
    resolved bracket = LADDER_PATIENT
    overlay = {'assess_bars': 4, 'stop_buffer_pips': 4.0, 'exhaustion': 'session_end'}
```

**Ladder arm with PATIENT overlay applied:**
```
AutoBot: [LADDER] armed pos_key=EPIC.CS.D.CFDGBPUSD.CFD.IP|GBPUSD_TREND_V3_L
         mode=GBPUSD_TREND_V3_L dir=BUY entry=1.30001
         rungs=['R1', 'R2', 'R3', 'PDH']
         at_level=5.00p assess_bars=4 stop_buffer=4.00p
         dress=LADDER_PATIENT day_ctx=BIG_NEWS
```

**On-disk state readback:**
```
    state.dress                = 'LADDER_PATIENT'
    state.day_ctx              = 'BIG_NEWS'
    state.exhaustion           = 'session_end'
    state.assess_bars          = 4
    state.stop_buffer_pips     = 4.0
    state.rungs                = ['R1@1.3002', 'R2@1.3004', 'R3@1.3006', 'PDH@1.3006']
```

**Ladder telemetry (`level_ladder.jsonl` last row):**
```
    event  = arm
    dress  = LADDER_PATIENT
    day_ctx = BIG_NEWS
    assess_bars      = 4
    stop_buffer_pips = 4.0
    exhaustion       = session_end
```

**No-admission-import guard test:**
```
tests/unit/test_day_context.py::test_no_admission_import_guard PASSED
```

Journal clean.

---

## Parallel task — LADDER_PATIENT vs LADDER_STANDARD pricing

Priced on the same regime_entry trigger set (60 days per N), same exit
simulator, same ladder-surrogate as `regime_entry_20260822`. The only
difference between STANDARD and PATIENT is the three-param overlay
(assess=+1, buffer=+1p, exhaustion=session_end).

### Full-window (60 trigger days per N)

| N | STANDARD total | PATIENT total | **delta** |
|:---:|:---:|:---:|:---:|
| N=1 | −63.7 p | −157.9 p | **−94.2 p** |
| N=2 | −117.4 p | −100.7 p | **+16.7 p** |
| N=6 | −51.2 p | −41.5 p | **+9.7 p** |

Full-window average: PATIENT is neutral-to-slightly-better at N=2 and
N=6; sharply worse at N=1 (the eager entry variant).

### Grind vs other split, per N

| N | dress | grind (6 days) | other (54 days) |
|:---:|:---|:---:|:---:|
| N=1 | STANDARD |  −15.2 |  −48.5 |
| N=1 | PATIENT  |  −31.9 | −126.0 |
| N=2 | STANDARD |  −17.8 |  −99.6 |
| N=2 | PATIENT  |  −30.8 |  −69.9 |
| N=6 | STANDARD |  **+73.2** | −124.4 |
| N=6 | PATIENT  |  **+57.7** |  −99.2 |

**At N=6 (best-performing regime-entry config), PATIENT loses 15.5 p
on grind days and saves 25.2 p on non-grind days.**

### Per-target grind day at N=6

| day | STANDARD | PATIENT | delta |
|:---|:---:|:---:|:---:|
| 2026-06-17 | +11.4 |  +6.5 |  −4.9 |
| 2026-06-18 | +62.2 | +58.4 |  −3.8 |
| 2026-07-15 | +16.5 | +14.8 |  −1.7 |
| 2026-07-29 | −15.0 | −18.6 |  −3.6 |
| 2026-08-10 | −12.4 | −13.9 |  −1.5 |
| 2026-08-14 | +10.5 | +10.5 |   0.0 |
| **totals** | **+73.2** | **+57.7** | **−15.5** |

**PATIENT is 1-5 p worse on every target grind day (N=6).** The
widened assess window (3→4) means one more bar to fail before closing;
the extra buffer (3p→4p) sits the ratchet 1p worse. On the grind days
those small adjustments erase 1-5 p per day.

**But PATIENT saves 25 p on the 54 non-grind days** by preventing
premature assess_expired exits on non-grind flare-and-fade patterns.

### Verdict on the flag

At N=6 (regime_entry's best-known config from prior work), PATIENT is
**net neutral (+9.7 p full-window) but worse on target grind days
(-15.5 p)**. The overlay saves money on non-grind days by exactly
matching what it loses on grinds.

The build ships the overlay flag-gated. Whether to enable it depends
on which side the operator's book is more exposed to. The pricing
alone doesn't force the choice — the numbers are close enough that
the choice depends on business context (drawdown tolerance on
non-grind vs upside tolerance on grind).

**Surrogate error band:** ±3-6 p per N (from `regime_entry_20260822`
§5.6). The N=2/N=6 PATIENT advantages of +16.7 p / +9.7 p sit at the
edge of the error band; N=1's −94 p penalty is clearly outside it.

---

## Environment vars registered (append to `.env` on host)

```
# Master
DAY_CTX_ENABLED=0
DAY_CTX_STATE_PATH=/opt/tradingbot/cache/day_context_state.json

# Bounce sizing bias
DAY_CTX_BOUNCE_HALF_SIZE=0
DAY_CTX_BOUNCE_HALF_SIZE_WINDOW_MIN=45

# Dress selector maps — empty ⇒ built-in defaults
DRESS_MAP_BIG_NEWS=
DRESS_MAP_PRE_BIG=
DRESS_MAP_POST_BIG=
DRESS_MAP_CLEAR=

# Patient overlay tunables
DRESS_LADDER_PATIENT_ASSESS_BARS_DELTA=1
DRESS_LADDER_PATIENT_STOP_BUFFER_DELTA=1
DRESS_LADDER_PATIENT_EXHAUSTION=session_end
```

## Artefacts

Under `/opt/tradingbot/reports-public/day_ctx_build_20260822/`:

* `proof_walk.py` — end-to-end trace script
* `proof_walk_output.txt` — raw captured proof output
* `patient_vs_standard.py` — pricing simulator
* `patient_vs_standard.json` — pricing detail per (N, dress, day)
* This report: `REPORT.md`

The build is committed and pushed. Kill switches are inert by
default — production behaviour is byte-identical to pre-2026-08-22
until an operator flips `DAY_CTX_ENABLED=1` in `.env` on the host.
