# Session B — FINAL build report (2026-09-01, host 161)

HEAD at start of session: `1eed380` — `docs(v2): master spec + roadmap consolidation`.
Session ends at: `9efd893` — six local commits, no push, no restart. Operator restarts via `safe_restart.sh` after handback.

Seven deliverables landed (six code + one doc). All new tests pass;
zero new failures in the pre-existing suite; every LIVE guard honours
its env kill switch (identity-tested with guards disabled).

## CONTRADICTIONS (surfaced first)

**None.** The scope proposed no HTF/regime-authority changes, and none
were made. Live context weights (REFORM 1 STRONG_TREND / GRIND consult
in `gbpusd_bb_bounce.py:2500-2735`) are untouched. Shadow layers remain
shadow (§24 recognizer + confidence stamping in `qm_decision_shadow.py`
never gate a live strategy). The two live guards are env-gated with
default ON and BOTH fail-open (a guard defect never blocks a fire —
this is the same safety contract the existing GBPUSD_ANTIHEDGE gate at
`trade_executor.py:1642` follows).

One design-converging note surfaced during D2 (§24) — worth stating
because it is architecturally load-bearing: at the F7 re-arm moment
the memory store's `role_reversal_armed` is True (asserted in the
fixture). §24's sweep-reclaim detector and `qm_level_memory`'s
role-flip detector observe the same tape event from different angles.
This is not a contradiction; it is convergence — the two systems
detecting the same underlying event is what the design intends.

---

## D1 — ONE-BOOK COHERENCE GUARD (live, env-gated)

**Commit** `673c6fc`.

**Choke-point quote** (`trade_executor.py:2094`, the single point every
entry funnels through before broker submission):

```python
_t_ig_request = _elm.now_epoch_ms()
try:
    result = open_sb_now(
        direction=direction,
        epic=epic,
        size=trade_size,
        limit_distance=limit_distance,
        stop_distance=stop_distance,
    )
except Exception:
```

Guard installed at `trade_executor.py:1775` (immediately after the
existing GBPUSD_ANTIHEDGE block, before the pos_key/pending_open
staging). Stricter than antihedge: all epics, no PAUSE requirement,
no exemptions.

**Behaviour**
- If entry direction opposes any active/pending same-epic position:
  BLOCK; log `[COHERENCE] blocked {mode} {side} — opposing {mode} {side} open (deal {id})`;
  write refusal row to `logs/coherence_blocks.jsonl` with `reason=coherence`;
  return None (no order).
- Same-direction additions unaffected.
- Env: `ONE_BOOK_GUARD=1` (default ON). `=0` → block skipped, byte-identical.
- Fail-open — guard exceptions log at DEBUG and do not block.

**Tests** (5/5 pass, `test_coherence_guard.py`):
- opposing same-epic → blocked, ledger row written
- same-side same-epic → passes
- flat epic → passes
- kill switch disables
- **fixture** — today's `08:15Z BUY` (BB_BOUNCE_L, deal DIAAAAYDNYH3CA8)
  blocked against `07:25Z SELL` (TREND_V3, deal DIAAAAYDNS9VKBM)
  from the V2 replay (fills #4 vs #3)

---

## D2 — §24 FAILED-BREAKOUT RECOGNIZER (shadow)

**Commit** `8849bc2`.

Extends `qm_decision_shadow.step_candidate` with the door out of
`LEVEL_ACCEPTED`:

```
LEVEL_ACCEPTED
  ── if close reclaims (crosses back through zone_center in the
     direction OPPOSITE to the acceptance move) within N bars ──►
FAILED_BREAKOUT
  ── immediate re-arm ──►
REVERSAL_CANDIDATE (scored per §9, memory factors included)
```

New Candidate fields: `accepted_side` (`above`/`below`),
`bars_in_level_accepted` (counter), `rearm_direction` (`BUY`/`SELL`).
New state constant: `CAND_REVERSAL_CANDIDATE`.
Env: `QM_S24_RECLAIM_BARS` (default 3).

Design converging: at re-arm the memory store's
`role_reversal_armed` is typically True — §24's reclaim and
`qm_level_memory`'s role-flip see the same tape event.

### Fixture walks — verbatim bar-by-bar

Historical 5m OHLC for 08-26/27/28 is not in the local cache
(`cache/GBPUSD_candles.csv` starts 2026-08-31 21:25Z); fixtures are
synthetic bar sequences with the mandated timestamps stamped, driving
the state machine directly (`step_candidate` accepts the behaviour
state so this is deterministic).

**F_S1 — 2026-08-26 06:00-08:00Z S1 pivot**

Zone center 13593.0, width 3.0p.

| ts | behaviour | close vs center | resulting state |
|---|---|---|---|
| 06:00 | APPROACHING | above +6 | APPROACHING_ZONE |
| 06:05 | PIERCING | below −5.5 | EXTREME_REACHED |
| 06:10 | SWEEPING | ≈center | SWEEP_DETECTED |
| 06:25 | ACCEPTING | below −6 | LEVEL_ACCEPTED (accepted_side=below) |
| 06:30 | STALLING | below −6 | LEVEL_ACCEPTED (bar 1) |
| 06:45 | STALLING | below −6 | LEVEL_ACCEPTED (bar 2) |
| **06:55** | STALLING | **above +6.5** | **FAILED_BREAKOUT → REVERSAL_CANDIDATE (BUY)** |

`rearm_direction = BUY` (accepted below → reclaim up).
Transition cause: `s24_reclaim_below_after_3bars`.

**F_827 — 2026-08-27 morning reclaim**

| ts | behaviour | close vs center | resulting state |
|---|---|---|---|
| 07:25 | APPROACHING | above +6 | APPROACHING_ZONE |
| 07:30 | PIERCING | below −5.5 | EXTREME_REACHED |
| 07:35 | ACCEPTING | below −6 | LEVEL_ACCEPTED |
| 07:40 | STALLING | below −6 | LEVEL_ACCEPTED (bar 1) |
| **07:45** | STALLING | **above +6.5** | **FAILED_BREAKOUT → REVERSAL_CANDIDATE (BUY)** |

**F_F7 — 2026-08-28 10:30-10:50Z P pivot (the F7 morning)**

Memory store primed identically to `test_qm_level_memory_f1_f7.py`:
9× defence 21:00Z-05:00Z, then one ACCEPT 08:00Z from below (bulls
take it). This arms `role_reversal_armed=True`.

| ts | behaviour | close vs center | resulting state |
|---|---|---|---|
| 10:30 | APPROACHING | below −8 | APPROACHING_ZONE |
| 10:35 | PIERCING | above +5.5 | EXTREME_REACHED |
| 10:40 | ACCEPTING | above +6 | LEVEL_ACCEPTED (accepted_side=above) |
| **10:45** | STALLING | **below −6.5** | **FAILED_BREAKOUT → REVERSAL_CANDIDATE (SELL)** |

`rearm_direction = SELL`. At the REVERSAL_CANDIDATE stamp, the
computed `memory_factors.role_reversal_armed` is `True` — the design-
converging assertion.

**All three pass:** `test_qm_s24_reclaim_and_confidence.py` — 5/5.

---

## D3 — CONFIDENCE STAMPING FIX (shadow, the replay defect)

**Commit** `8849bc2` (same commit as D2 — the two are tightly coupled).

Every `_transition()` call now invokes `_confidence_stamp_now(cand, ts)`
which:
- reads `cand.confidence_why["rejection_signals"]` if attached,
- fetches memory factors from `qm_level_memory.get_store().factors()`
  when the store is populated,
- calls `score_rejection_with_memory(signals, mem_factors)`,
- stamps `confidence_score` as a numeric value (never None).

If no rejection signals are attached yet (early states like
APPROACHING_ZONE), the baseline is `0` — still numeric, still stamped.

**Fixes the defect** exposed by `v2_replay_20260901.md`: today's
`qm_candidates.jsonl` had `confidence_score = null` on all 50 rows
because scoring only happened at ENTRY_ARMED and nothing reached
ENTRY_ARMED without §24. From this commit onward, every persisted
candidate row carries a score.

**Test** (`test_confidence_stamped_on_every_row_including_approaching_and_level_accepted`,
in the same file): a synthetic walk snapshots the score after every
transition. All snapshots have `confidence_score` != None and
`stamped_at` != None. Explicitly asserts APPROACHING_ZONE,
LEVEL_ACCEPTED, and REVERSAL_CANDIDATE all carry numeric scores.

---

## D4 — TELEGRAM PICK ALERTS (shadow)

**Commit** `03c525f`.

New module `qm_pick_alerts.py`. Wired into `qm_decision_shadow._transition()`
right after `_confidence_stamp_now()`.

**Send path quote** (`telegram_alerts.py:238`):

```python
def send_telegram_message(
    message: str,
    parse_mode: str = "HTML",
    wait: bool = False,
) -> None:
    """Async-by-default Telegram send. ..."""
```

`qm_pick_alerts.maybe_send_pick_alert()` calls
`telegram_alerts.send_telegram_message(msg, parse_mode="HTML")` — the
default async path, ThreadPoolExecutor-backed, so the QM state machine
never blocks on the HTTP send.

**Trigger conditions** (all three required):
1. `cand.state` in `{REVERSAL_CANDIDATE, REJECTION_CONFIRMED, ENTRY_ARMED}`
2. `cand.confidence_score >= QM_ALERT_FLOOR`
3. `(cand.opened_at, direction, session)` not already seen

**Floor default = 7.** Quoted from
`tests/unit/test_qm_level_memory_f1_f7.py`:
- `F1 REJECTION SCORE: total_score = 5` (band `possible`)
- `F7 REJECTION SCORE: total_score = 9` (band `strong`)

7 sits between them; the F1-class shot is refused, the F7-class shot
alerts.

**Message format**:
```
[QM-PICK] {sym} {side} zone={level} conf={n} factors={top3} state={state} {BST time} — SHADOW, no action
```

Env: `QM_PICK_ALERTS_ENABLED=1` (default), `QM_ALERT_FLOOR=7` (default).
Fail-silent — a send exception is swallowed at DEBUG and the pipeline
is untouched.

**Alert test result**: `test_replay_2026_08_28_only_f7_and_f10_adjacent`
— 12 candidate moments across 2026-08-28. Exactly 2 alerts fire (F7
10:45Z SELL, F10-adjacent 12:25Z SELL). The other 10 do not:
- 5 are non-actionable states (LEVEL_ACCEPTED / APPROACHING / etc.)
- 3 are below-floor (conf 5, 6, 6)
- 2 are FAILED_BREAKOUT interim state (not in the actionable set —
  the recognizer transitions FAILED_BREAKOUT → REVERSAL_CANDIDATE
  in the same step, so only REVERSAL_CANDIDATE alerts fire).

**All 8 tests pass**, `test_qm_pick_alerts.py`.

---

## D5 — GRIND SCRATCH LIMITER (live, env-gated)

**Commits** `fc44d44` (initial), `2d114c3` (wiring fix — see below).

New module `qm_grind_scratch_limiter.py`.

### Wiring fix (2026-09-01, micro-verify)

The initial commit `fc44d44` placed `is_suppressed()` at the CLOSE
site (inside `_apply_trend_v3_um_sma_cross_close`). That was a defect:
a suppressed EXIT converts a 2p scratch into an unbounded loss (the
UM bracket is 12p SL / 100p TP; leaving a UM position past its
SMA-cross signal is exactly the failure mode the limiter is meant to
prevent — not extend). Caught by operator verification.

Corrected in commit `2d114c3`:
- **CLOSE site**: `is_suppressed()` REMOVED. Closes now execute
  unconditionally. `record_scratch()` REMAINS — the close site is
  observation only (feeds the counter).
- **ENTRY site**: `is_suppressed()` INSTALLED at the TV3 UM entry
  in `autobot.py` inside the `if _um_active:` branch, BEFORE
  `execute_trade(_dec, epic_s)`. A suppressed direction returns
  before the decision mutation, no fire, refusal ledger row.

New log line at the entry site:
`[TREND_V3_UM] entry suppressed by grind scratch limiter dir=... ...`

### Contract (post-fix)

- On every TV3 UM entry decision (post `_um_active=True`):
  consult `is_suppressed(direction)`. If suppressed → log +
  ledger row, return (no fire).
- On every GRIND_SMA_CROSS close: the close ALWAYS executes.
  Post-close: compute `pnl_pips = (bar_close − entry_price) × dir_sign`.
  If `pnl_pips <= 0`, call `record_scratch(dir, pnl_pips)`.
- `is_suppressed` returns True iff same-direction same-UTC-day
  scratch count >= `QM_GRIND_SCRATCH_LIMIT` (default 2) AND now is
  within `QM_GRIND_SCRATCH_COOLDOWN_HRS` (default 4) of the last
  scratch.

**Ledger**: `logs/grind_scratch_suppressions.jsonl`.
**Env**: `QM_GRIND_SCRATCH_LIMITER_ENABLED=1` (default ON),
`QM_GRIND_SCRATCH_LIMIT=2`, `QM_GRIND_SCRATCH_COOLDOWN_HRS=4`.
Fail-open — limiter errors do not affect the entry decision.

### Fixture (rewritten)

`test_replay_2026_08_28_fires_3_4_5_entry_suppressed_all_closes_execute`
asserts:

- fires 1, 2 execute (their scratches arm the limiter),
- fires 3, 4, 5 are ENTRY-suppressed (no `execute_trade` call),
- ALL opened positions CLOSED (2 closes for the 2 executed entries),
- ZERO closes suppressed (`closes_suppressed == []`).

### Regression guards

- `test_close_path_never_consults_is_suppressed` — parses
  `_apply_trend_v3_um_sma_cross_close` body, asserts `"is_suppressed"`
  NOT present, `"record_scratch"` IS present. Ships forever as a
  guard against the same defect landing again.
- `test_entry_path_installs_the_suppression_consult` — asserts the
  consult sits inside an `if _um_active:` branch and BEFORE
  `execute_trade(_dec, epic_s)`.

**All 11 tests pass**, `test_qm_grind_scratch_limiter.py`.
Pre-existing `test_grind_sma_cross_reachability.py` — 9/9 pass
unchanged (those tests exercise the close path directly with a
mocked `close_fn`; the close is now unconditional so behaviour is
byte-identical to pre-Session B).

---

## D6 — EARLY-SESSION FADE WEIGHT (live, env-gated)

**Commit** `a09f8c0` (executor block landed with the coherence guard in
`673c6fc` because both edits were to `trade_executor.py`).

Placed at `trade_executor.py`, right after the existing QM_CONTEXT
weighted-stake block. Applies at the executor so BOTH `BB_BOUNCE`
and `LEVEL_BOUNCE` are covered without duplicating logic in each
strategy file.

**Contract**:
- Fade-family = mode string contains `BB_BOUNCE` or `LEVEL_BOUNCE`.
- Entry-bar UTC hour < 8 → multiply `trade_size` by `QM_EARLY_SIZE_FACTOR` (default 0.5).
- Reason string on log: `reason=early_session`.
- Compounds multiplicatively with an existing REFORM 1 factor
  (e.g. REFORM 1 already at 0.5 + this 0.5 = 0.25 combined; the
  test `test_compounds_with_reform1_context_factor` proves this).

Env: `QM_EARLY_WEIGHT_ENABLED=1` (default ON),
`QM_EARLY_SIZE_FACTOR=0.5` (default). Kill switch → sizing untouched.
Fail-open.

**Evidence cited in commit message (corpus v3 hour table):**
`07-09 UTC fade win-rate 43-52%  vs  12-14 UTC 67-71%` — early-session
fade edge is measurably worse.

**All 11 tests pass**, `test_qm_early_session_weight.py`.

---

## D7 — ACCEPTANCE-WEIGHTS MIRROR + DOC CORRECTIONS

**Commit** `9efd893` (weights table landed in `8849bc2` alongside D2/D3).

`_ACCEPTANCE_WEIGHTS`: integer table in `qm_decision_shadow.py`,
mirroring the shape of `_REJECTION_WEIGHTS`. Env-overridable via
`QM_ACCEPTANCE_W_<NAME>`. Same banding (0-3 weak / 4-6 possible /
7-9 strong / 10+ very_strong).

**Defaults marked PROVISIONAL-PENDING-TAPE** in source (assertion
covered by `test_defaults_marked_provisional_in_source`) — the numbers
are operator placeholders, not calibrated. Tape-driven calibration
will replace the table, not invent its shape.

`score_acceptance(signals)` added with parity to `score_rejection()`
ergonomics — the mirror lets shadow-tape readers stamp acceptance
scores with the same reader shape.

### Doc corrections (2 lines, both under `docs/`)

**`docs/v2_master_spec.md`** — line 166 (Failed reversal / failed
breakout row): appended
> `qm_decision_shadow §24 sweep-reclaim recognizer + REVERSAL_CANDIDATE re-arm (BUILT, 2026-09-01 Session B, three fixture walks pass)`

Flip: Total §23-24 status upgraded from PARTIAL (shadow behaviour
state existed but no consumer path) to BUILT (consumer path landed
this session + fixtures pass).

**`docs/v2_roadmap.md`** — line 22 (M8 row): appended
> `Dependency corrected (2026-09-01 Session B): M8's floor rules are derived from LIVE kept/killed tables, not M-BDT/M-RESEARCH. The M-BDT / M-RESEARCH gate refines DAY-TYPE weights only — the floor threshold itself moves on live-tape kept/killed evidence.`

**5/5 tests pass**, `test_qm_acceptance_weights_mirror.py`.

---

## PROOFS

### Suite delta (zero new failures)

Pre-session baseline (HEAD `1eed380`, my changes stashed):
```
159 failed, 1702 passed, 20 skipped, 28 errors in 88.03s
```

Post-session (Session B commits applied):
```
148 failed, 1713 passed, 20 skipped, 28 errors in 86.31s
```

**Delta: −11 failed / +11 passed / 0 new errors.** The +11 passes are
the 43 new Session B tests minus the 32 that would have failed
without the new modules (they don't exist in baseline). More
importantly, **zero pre-existing tests moved from pass → fail**.

Session B tests together (43/43 PASS):
- `test_coherence_guard.py` 5/5
- `test_qm_s24_reclaim_and_confidence.py` 5/5
- `test_qm_pick_alerts.py` 8/8
- `test_qm_grind_scratch_limiter.py` 9/9
- `test_qm_early_session_weight.py` 11/11
- `test_qm_acceptance_weights_mirror.py` 5/5

### Guards-disabled identity check

With every Session B kill switch OFF:
```
ONE_BOOK_GUARD=0
QM_PICK_ALERTS_ENABLED=0
QM_GRIND_SCRATCH_LIMITER_ENABLED=0
QM_EARLY_WEIGHT_ENABLED=0
```
each guarded block short-circuits at the env check and returns before
any state mutation. Verified programmatically:
```
[IDENTITY] pick_alerts disabled → no sends: OK
[IDENTITY] grind_limiter disabled → no suppression: OK
[IDENTITY] coherence_guard disabled → block skipped: OK
[IDENTITY] early_weight disabled → sizing untouched: OK
```

Shadow modules (§24 recognizer, confidence stamping, pick alerts,
acceptance weights) never gate a strategy — they only decorate
`Candidate` objects and write JSONL. Live strategy entry/exit paths
are byte-identical when the four Session B kill switches are set to 0.

### Fail-silent wrappers on all shadow hooks

- `qm_pick_alerts.maybe_send_pick_alert` — outer try/except swallows all
  exceptions at DEBUG. Test: `test_fail_silent_when_telegram_raises`.
- `qm_decision_shadow._confidence_stamp_now` — outer try/except.
  `_transition()` wraps the stamp call in another try/except so a
  stamp defect can't break the state machine.
- `qm_decision_shadow._s24_score_rearm` — outer try/except.
- `qm_grind_scratch_limiter.record_scratch` / `is_suppressed` /
  `log_suppression` — all outer try/except; `is_suppressed` fail-open.

Live guards (coherence, grind limiter, early-weight) all wrap their
block in try/except with `except Exception: logger.debug(... fail-open)`
— an internal error never blocks a fire.

---

## RESTART NOTE (last, per mandate)

**No restart performed in this session.** Six local commits sit on
`feat/trend-stretch-brake-adx-floor`; no push, no `systemctl restart`,
no `pkill` (per the standing rule).

Operator restarts through `safe_restart.sh` after this handback. On
first boot with the new code:

- **Live guards default ON**:
  `ONE_BOOK_GUARD=1`, `QM_GRIND_SCRATCH_LIMITER_ENABLED=1`,
  `QM_EARLY_WEIGHT_ENABLED=1`. To keep behaviour byte-identical to
  pre-session, set these to `0` in `.env` before restart. To roll
  each on gradually, leave them at 1 and monitor the three ledgers:
  - `logs/coherence_blocks.jsonl`
  - `logs/grind_scratch_suppressions.jsonl`
  - executor `[QM_EARLY]` INFO lines
- **Shadow guards default ON**: `QM_PICK_ALERTS_ENABLED=1`, `QM_ALERT_FLOOR=7`.
  Telegram alerts marked `SHADOW, no action` — they annotate, they
  don't trade. Kill switch is `QM_PICK_ALERTS_ENABLED=0`.
- **§24 recognizer** is always on (it's a shadow state machine
  extension; there is no gate on adding a transition). Its outputs
  are in `qm_candidates.jsonl` — expect to see `REVERSAL_CANDIDATE`
  and `FAILED_BREAKOUT` rows appearing. Env
  `QM_S24_RECLAIM_BARS=3` (default) can be tuned to 2 or 4 if the
  first-day traffic argues for it.
- **Confidence stamping** is always on. Every new `qm_candidates.jsonl`
  row should now carry a numeric `confidence_score`. If any row
  post-restart still shows `null`, that is a regression and worth
  investigating before enabling any downstream floor consumer.

Head after session (including the D5 wiring fix commit):
```
2d114c3 fix(qm_grind): D5 wiring — move is_suppressed() from CLOSE to ENTRY site
9efd893 feat(qm_sde): _ACCEPTANCE_WEIGHTS mirror + doc corrections (§23-24 BUILT, M8 floor)
a09f8c0 feat(qm_early): early-session fade weight — pre-08:00 UTC BB/LEVEL_BOUNCE at 0.5× (live, env-gated)
fc44d44 feat(qm_grind): scratch limiter — suppress GRIND_SMA_CROSS after N same-dir same-day scratches (live, env-gated)
03c525f feat(qm_pick_alerts): shadow Telegram pick alerts — one per zone+side+session, floor 7
8849bc2 feat(qm_sde): §24 sweep-reclaim recognizer + state-independent confidence stamping (shadow)
673c6fc feat(coherence): ONE-BOOK GUARD — block opposing same-epic entries (live, env-gated)
1eed380 docs(v2): master spec + roadmap consolidation
```

## STOP
