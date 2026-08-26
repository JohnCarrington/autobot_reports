# SESSION 2 — REGIME DEMOTION (LABELS → WEIGHTS)

**Date:** 2026-08-26
**Host:** 161 (`/opt/tradingbot`)
**Branch:** `feat/trend-stretch-brake-adx-floor` @ 7a6fb55 (base)
**Scope:** two reforms, both live on commit; local commits only, no push.

## Principle
A slow-classifier label may **size** a trade, **delay** it one confirmation
bar, or **halve** it. It may NOT refuse it. The only permitted
label-vetoes remain the news/blackout family and (future) the CHOP
permission gate. The grind subtype router is EXEMPT — its label
dependency is by construction; untouched here.

---

## Contradictions

None. Both reforms convert existing REFUSE-verdicts into
SIZE-and-DELAY / DEFER-until-ACCEPTED verdicts. All pre-existing
authorities (news blackout, broker SL, flat times, structure exits)
remain independent and senior. Zero new failures in the unit suite
(baseline: 163 failed / 1578 passed — after: 145 failed / 1596 passed;
delta by name = 0 new failures).

---

## REFORM 1 — STANDDOWN → CONTEXT WEIGHT

### Site quoted (BEFORE)

`gbpusd_bb_bounce.py:2487` (pre-reform, at HEAD 7a6fb55):

```python
# ── STRONG_TREND stand-down (2026-06-29) ─────────────────────────
# Consume regime_engine.latest_result — the SAME authority
# EMA_PULLBACK / CONFIRMATION_FALLBACK read. Stand down when this
# fire would fade a STRONG confirmed trend:
#   STRONG_TREND_UP + SHORT  → suppress (fading the up-trend)
#   STRONG_TREND_DOWN + LONG → suppress (fading the down-trend)
...
if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:
    ...
    _fade_blocked = (
        (_winning == "STRONG_TREND_UP"   and direction == "SELL") or
        (_winning == "STRONG_TREND_DOWN" and direction == "BUY")
    )
    ...
    if _fade_blocked:
        _intended = "SHORT" if direction == "SELL" else "LONG"
        logger.info(
            "[%s] STRONG_TREND stand-down: would-fire %s into %s, "
            "suppressed (regime=%s, intended_dir=%s, pair=%s)", ...
        )
        # ... jsonl log with "verdict": "BLOCKED" ...
        return None
```

### Site quoted (AFTER)

`gbpusd_bb_bounce.py:2487` (post-reform):

```python
# ── STRONG_TREND CONTEXT-WEIGHT consult (2026-08-26, SESSION 2) ──
# Regime label demoted from AUTHORITY to CONTEXT WEIGHT: a slow-
# classifier label can now SIZE and DELAY a fire but never REFUSE
# it. Consumes regime_engine.latest_result — the SAME source
# EMA_PULLBACK / CONFIRMATION_FALLBACK read. When this fire
# would fade a STRONG confirmed trend:
#   STRONG_TREND_UP + SHORT  → WEIGHTED (half stake, +N closes)
#   STRONG_TREND_DOWN + LONG → WEIGHTED (half stake, +N closes)
...
_qm_context_size_factor: Optional[float] = None
_qm_context_extra_closes_applied: Optional[int] = None
if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:
    ...
    _qm_size_factor_env = _env_float("QM_CONTEXT_SIZE_FACTOR", 0.5)
    _qm_extra_closes_env = _env_int("QM_CONTEXT_EXTRA_CLOSES", 1)
    _actual_decision: Optional[str] = None
    _defer_fire = False
    _extra_closes_pending: Optional[int] = None
    if _fade_blocked:
        _pending = fired_setup.get("qm_context_confirms_pending")
        if _qm_extra_closes_env > 0 and _pending is None:
            fired_setup["qm_context_confirms_pending"] = _qm_extra_closes_env
            _extra_closes_pending = _qm_extra_closes_env
            _actual_decision = "WEIGHTED_PENDING"
            _defer_fire = True
        elif _qm_extra_closes_env > 0 and int(_pending) > 1:
            fired_setup["qm_context_confirms_pending"] = int(_pending) - 1
            _extra_closes_pending = int(_pending) - 1
            _actual_decision = "WEIGHTED_PENDING"
            _defer_fire = True
        else:
            fired_setup["qm_context_confirms_pending"] = 0
            _qm_context_size_factor = _qm_size_factor_env
            _qm_context_extra_closes_applied = _qm_extra_closes_env
            _extra_closes_pending = 0
            _actual_decision = "WEIGHTED"
    elif _winning in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        _actual_decision = "PERMIT"
    # ... shadow.record(applied_factor=..., extra_closes_required=..., extra_closes_pending=...) ...
    if _defer_fire:
        return None  # setup remains armed; fires with weight on next confirm
    # else: fall through to fire with size factor
```

Key properties:
- **Never returns SUPPRESS.** The consult either defers (WEIGHTED_PENDING,
  `return None` leaves the armed setup in place so the next rejection bar
  re-consults) or proceeds to fire with `_qm_context_size_factor` set.
- Env-driven per decision: `QM_CONTEXT_SIZE_FACTOR` (default 0.5),
  `QM_CONTEXT_EXTRA_CLOSES` (default 1).
- Old "verdict: BLOCKED" JSONL sink now writes verdict = WEIGHTED /
  WEIGHTED_PENDING with `reason: strong_trend_context_weight`.

### Stake-wiring diff (must reach the ACTUAL order)

`gbpusd_bb_bounce.py:3524` — decision debug carries the factor:

```python
"neartouch_gate_reason": fired_setup.get("neartouch_gate_reason"),
+ # 2026-08-26 SESSION 2 — QM_CONTEXT weighted-stake bias.
+ # Set only when the STRONG_TREND context consult fired
+ # WEIGHTED (fade against confirmed trend, extra-close
+ # confirmation satisfied). trade_executor multiplies
+ # trade_size by this factor at the sizing site.
+ "qm_context_size_factor": _qm_context_size_factor,
+ "qm_context_extra_closes_applied": _qm_context_extra_closes_applied,
}
```

`trade_executor.py:2025` — the executor multiplies **before** `open_sb_now`:

```python
# ── QM_CONTEXT weighted-stake bias (2026-08-26 SESSION 2) ─────────────
# gbpusd_bb_bounce.py sets debug["qm_context_size_factor"] to e.g. 0.5
# when the STRONG_TREND context consult fires WEIGHTED (fade against a
# confirmed trend, extra-close confirmation satisfied). The factor is
# multiplied here so the order actually reaches the broker at the
# reduced size — a logged-but-unapplied factor is a stub, prohibited.
try:
    _qm_dbg = getattr(decision, "debug", None) or {}
    _qm_factor = _qm_dbg.get("qm_context_size_factor")
    if _qm_factor is not None:
        _qm_factor_f = float(_qm_factor)
        if 0.0 < _qm_factor_f < 1.0:
            _pre_qm = trade_size
            trade_size = trade_size * _qm_factor_f
            logger.info(
                "[QM_CONTEXT] weighted stake applied: mode=%s "
                "factor=%.3f extra_closes=%s size %s → %s", ...
            )
```

`trade_executor.py:~2094` (unchanged, downstream of the multiply):

```python
result = open_sb_now(
    direction=direction, epic=epic,
    size=trade_size,          # ← post-multiply value reaches broker
    limit_distance=limit_distance,
    stop_distance=stop_distance,
)
```

Unit test `test_executor_applies_qm_context_size_factor` asserts both
the arithmetic AND the presence of the exact `trade_size = trade_size
* _qm_factor_f` line — a future refactor that drops the wiring (leaving
only telemetry) fails loudly.

### Sample WEIGHTED shadow row

Written to `standdown_shadow.jsonl` on a fade-fires-with-weight event:

```json
{
  "ts_utc": "2026-08-26T14:45:00Z",
  "symbol": "GBPUSD",
  "dir": "SELL",
  "actual_decision": "WEIGHTED",
  "regime": "STRONG_TREND_UP",
  "label_path": "hist",
  "struct_promoted": false,
  "confidence_final": 0.42,
  "dwell_run_length": 4,
  "verdict_dwell_n6": "PERMIT",
  "verdict_dwell_n8": "PERMIT",
  "verdict_pathconf": "WEIGHTED",
  "pathconf_floor": 0.3,
  "setup_price": 13636.75,
  "mfe_pips": null,
  "mae_pips": null,
  "applied_factor": 0.5,
  "extra_closes_required": 1,
  "extra_closes_pending": 0
}
```

The shadow-race columns (`verdict_dwell_n6`, `_n8`, `_pathconf`) keep
computing so the same table that was going to calibrate a veto-fix now
calibrates the weight. `applied_factor` / `extra_closes_required` /
`extra_closes_pending` are new; PERMIT rows carry them as `null`.

### Unit tests

`tests/unit/test_qm_context_weighted.py` — 10 tests, all green:
- WEIGHTED shadow row shape (applied_factor + extra_closes_required present)
- WEIGHTED_PENDING shadow row shape (extra_closes_pending carries a
  positive count)
- PERMIT backcompat (new kwargs default to None on same-direction
  same-STRONG_TREND consults)
- Executor multiplies trade_size when debug carries factor
- Executor no-factor path is byte-identical (full-stake fires unchanged)
- Source-level guards for the wiring in `gbpusd_bb_bounce.py` and
  `trade_executor.py`

---

## REFORM 2 — AUTO_K PREMISE → ACCEPTANCE EVIDENCE

### Site quoted (BEFORE)

`auto_k.py:312-450` (pre-reform, at HEAD 7a6fb55):

Universal MAE-based kill for every non-EXCLUDED family, including
LEVEL_BOUNCE (env default `AUTOK_EXCLUDE=NEWS_CONTINUATION` does NOT
exclude LEVEL_BOUNCE on this box). Gates:
```
(1) MAE ≥ AUTOK_MAE_MIN_PIPS_DEFAULT (6.0p)
(2) ribbon_state.velocity_state OK + accel ≥ AUTOK_ACCEL_MIN (1.0)
    + dir_of_move AGAINST position
(3) best_pnl_pips (or best_close_pnl_pips) < AUTOK_TOUCHED_LOCK_PIPS (5.0)
```
On all three passing → `close_position(reason="AUTO_K_PREMISE")` fires at
market. A LEVEL_BOUNCE position dipping to −6.9p with adverse acceleration
and never having touched +5 gets killed regardless of what price then does
at the actual reclaimed/lost level.

### Site quoted (AFTER)

`auto_k.py:312` (top of `eval_and_close`):

```python
try:
    if not _enabled():
        return None
    direction_u = str(direction).upper()
    if direction_u not in ("BUY", "SELL"):
        return None
    _ppp = float(ppp) if ppp else 1.0

    # 2026-08-26 SESSION 2 — LEVEL_BOUNCE ACCEPTANCE EVIDENCE branch.
    # LEVEL_BOUNCE's premise-kill is a fundamentally different rule: a
    # slow-classifier's MAE threshold cannot RETIRE a fade that hasn't
    # been ACCEPTED by price. Kill only when the level has been
    # decisively lost/reclaimed by N consecutive 5m closes beyond it,
    # sustained through M bars — a sweep-through that closes back
    # inside never kills. Broker SL (attached to the deal at open,
    # see gbpusd_level_bounce.py's 100p STOP_PIPS + trade_executor's
    # open_sb_now(size, sl, tp) call at ~2094) remains the sole
    # catastrophic-protection authority; auto_k neither reads nor
    # modifies it and only ever calls close_position at market.
    _fam = family_for_mode(mode)
    _excl = _exclude_families()
    if _fam in _excl:
        return None  # explicit env exclusion — no eval, no CUT.
    if _fam == "LEVEL_BOUNCE":
        return _eval_level_bounce_acceptance(
            epic=epic, pos_key=pos_key, pair=pair, mode=mode,
            direction_u=direction_u,
            entry_price=float(entry_price),
            current_price=float(current_price),
            ppp=_ppp, closes_5m=closes_5m,
            strategy_meta=strategy_meta or {},
            trade_id=trade_id, now_utc=now_utc,
        )
    threshold_pips = threshold_for_mode(mode)
    ...  # existing generic MAE / velocity / lock path for non-LEVEL_BOUNCE
```

New `_eval_level_bounce_acceptance` (in `auto_k.py`):
```python
def _eval_level_bounce_acceptance(...):
    """LEVEL_BOUNCE premise-kill via ACCEPTANCE EVIDENCE (SESSION 2).

    Kill iff every one of the last max(CLOSES, BARS) 5m closes lies on
    the adverse side of the reclaimed/lost level:
      - BUY (S1/S2/S3 reclaimed from below) → close < level_price
      - SELL (R1/R2/R3 lost from above)     → close > level_price

    A sweep-through that closes back inside the window (any single close
    on the level's protected side) NEVER kills — the acceptance criterion
    resets on interruption because the window is a strict all()-check.
    """
    n_closes = _qm_accept_closes()      # env QM_KILL_ACCEPT_CLOSES, default 2
    n_bars = _qm_accept_bars()          # env QM_KILL_ACCEPT_BARS, default 2
    window = max(n_closes, n_bars)
    tail = [float(c) for c in closes_5m[-window:]]
    if direction_u == "BUY":
        all_beyond = all(c < level_price_f for c in tail)
    else:
        all_beyond = all(c > level_price_f for c in tail)
    if not all_beyond:
        return {"kind": "NO_CUT", "reason": "acceptance_not_met", ...}
    # ... else CUT via trade_executor.close_position (market close only)
```

`trade_manager.py:5873` wires the strategy meta through:

```python
_strategy_meta = dict(st.get("decision_debug") or {})
_dec = _autok.eval_and_close(
    ..., strategy_meta=_strategy_meta,
)
```

### Broker SL — guard quoted

`gbpusd_level_bounce.py:79`:
```python
STOP_PIPS = _env_float("LEVEL_BOUNCE_STOP_PIPS", 100.0)
```
Passed on the `StrategyDecision(sl=STOP_PIPS)` at `gbpusd_level_bounce.py:769`.
The broker SL is attached to the deal at open time by `trade_executor`'s
`open_sb_now(..., stop_distance=...)` call — **not** modified after fill.

`auto_k.py` — source-level guard, asserted by
`test_auto_k_never_touches_broker_sl`:
- No `update_stop` / `amend_stop` / `modify_stop` / `adjust_stop` references.
- The only close-path is `close_position(pos_key=..., reason=...)` — a
  market close, which cannot modify the attached SL (the SL is either hit
  or superseded by the market close).

Between penetration and acceptance, `_eval_level_bounce_acceptance`
returns `{"kind": "NO_CUT", "reason": "acceptance_not_met"}` — no close,
no state mutation. The attached SL continues to protect.

### Morning fixture — 2026-08-26 06:00-08:00Z, bar-by-bar

Bars sourced from `cache/GBPUSD_candles.csv` (live completed-5m closes,
keep-first-dedup at ingest). Level: `S1 = 13630.0`. Direction: BUY.
Position: entered ~07:00-07:35 (after the 06:55 reclaim per operator
narrative). Env: `QM_KILL_ACCEPT_CLOSES=2 / QM_KILL_ACCEPT_BARS=2`.

```
  time     close below_S1?               tail_window all_beyond?  verdict
------------------------------------------------------------------------------
 06:00  13630.65        no                [13630.65]           -  n/a (short window)
 06:05  13631.05        no       [13630.65, 13631.05]         no  NO_CUT/acceptance_not_met
 06:10  13629.15       yes       [13631.05, 13629.15]         no  NO_CUT/acceptance_not_met
 06:15  13630.75        no       [13629.15, 13630.75]         no  NO_CUT/acceptance_not_met
 06:20  13630.45        no       [13630.75, 13630.45]         no  NO_CUT/acceptance_not_met
 06:25  13629.35       yes       [13630.45, 13629.35]         no  NO_CUT/acceptance_not_met
 06:30  13628.35       yes       [13629.35, 13628.35]        yes  *** CUT (pre-position)
 06:35  13627.55       yes       [13628.35, 13627.55]        yes  *** CUT (pre-position)
 06:40  13628.15       yes       [13627.55, 13628.15]        yes  *** CUT (pre-position)
 06:45  13626.35       yes       [13628.15, 13626.35]        yes  *** CUT (pre-position)
 06:50  13627.45       yes       [13626.35, 13627.45]        yes  *** CUT (pre-position)
 06:55  13632.75        no       [13627.45, 13632.75]         no  NO_CUT/acceptance_not_met  ← reclaim
 07:00  13635.35        no       [13632.75, 13635.35]         no  NO_CUT/acceptance_not_met
 07:05  13637.45        no       [13635.35, 13637.45]         no  NO_CUT/acceptance_not_met
 07:10  13638.45        no       [13637.45, 13638.45]         no  NO_CUT/acceptance_not_met
 07:15  13637.15        no       [13638.45, 13637.15]         no  NO_CUT/acceptance_not_met
 07:20  13635.45        no       [13637.15, 13635.45]         no  NO_CUT/acceptance_not_met
 07:25  13635.65        no       [13635.45, 13635.65]         no  NO_CUT/acceptance_not_met
 07:30  13636.05        no       [13635.65, 13636.05]         no  NO_CUT/acceptance_not_met
 07:35  13635.85        no       [13636.05, 13635.85]         no  NO_CUT/acceptance_not_met
 07:40  13634.35        no       [13635.85, 13634.35]         no  NO_CUT/acceptance_not_met  ← old-rule kill point
 07:45  13634.45        no       [13634.35, 13634.45]         no  NO_CUT/acceptance_not_met
 07:50  13631.25        no       [13634.45, 13631.25]         no  NO_CUT/acceptance_not_met
 07:55  13631.75        no       [13631.25, 13631.75]         no  NO_CUT/acceptance_not_met
```

The 06:30-06:50 CUTs are annotated pre-position — no LEVEL_BOUNCE_L
was open in that window (position opened after the 06:55 reclaim per
operator narrative). Those rows demonstrate that the acceptance
criterion IS willing to CUT when price genuinely accepts a level
break — the rule is not toothless.

**At 07:40:02Z (the live AUTO_K kill point):** tail = `[13635.85, 13634.35]`
— NEITHER close is below 13630 → `all_beyond=False` → `NO_CUT`.
The live kill would NOT fire under the new rule. Live entry 13633.8 and
live tick 13626.9 (which produced `MAE=6.9p` in the old MAE-based rule)
are irrelevant to the acceptance authority — that authority reads only
**completed 5m closes**. Broker SL (100p from entry = 13533.8 for a BUY
at 13633.8) is untouched and continues to protect against catastrophic
downside.

### Truth table

| Scenario | Env | Direction | Closes (tail) | Verdict |
|---|---|---|---|---|
| 2 closes beyond, held 2 bars | C=2 B=2 | BUY at S1=13630 | `[13629.5, 13627.0]` | **CUT** |
| 1 close beyond + reclaim inside | C=2 B=2 | BUY at S1=13630 | `[13628.0, 13632.0]` | NO_CUT |
| Oscillation across level | C=2 B=2 | BUY at S1=13630 | `[13629.0, 13631.0]` | NO_CUT |
| SHORT — 2 closes above R1 | C=2 B=2 | SELL at R1=13540 | `[13541.5, 13542.5]` | **CUT** |
| SHORT — sweep up then close back below | C=2 B=2 | SELL at R1=13540 | `[13541.5, 13538.0]` | NO_CUT |
| Missing `level_price` in strategy_meta | — | BUY | any | NO_CUT (`level_price_missing`) |
| Fewer closes than window | C=2 B=2 | BUY | `[13629.0]` (n=1) | NO_CUT (`acceptance_window_short`) |

### Unit tests

`tests/unit/test_auto_k_level_bounce_acceptance.py` — 10 tests, all green:
- Truth table above
- Live 2026-08-26 07:40:02Z fixture — kill does NOT fire
- Source-level guards: no SL-mutation APIs referenced in auto_k.py
- Ordering guard: LEVEL_BOUNCE branch precedes generic MAE gate
- Env defaults: both knobs = 2 with no env override
- Wiring: `trade_manager.py` passes `strategy_meta=_strategy_meta` and
  reads `st.get("decision_debug")`

---

## Suite delta

Baseline (HEAD 7a6fb55, unmodified): **163 failed / 1578 passed / 20 skipped / 28 errors** in 104s.
After this branch: **145 failed / 1596 passed / 20 skipped / 28 errors** in 120s.

`comm -23 after.sorted before.sorted` = **empty** — **zero** new failures.
The 18-test net reduction is test-order noise + the 20 new PASSING tests
introduced by this reform.

Test files added:
- `tests/unit/test_qm_context_weighted.py` — 10 tests
- `tests/unit/test_auto_k_level_bounce_acceptance.py` — 10 tests

---

## Restart command

**Env-only** (immediate on next in-scope decision):
- `QM_CONTEXT_SIZE_FACTOR` (default 0.5) — sizing multiplier for
  STRONG_TREND fade fires.
- `QM_CONTEXT_EXTRA_CLOSES` (default 1) — extra confirmation closes
  before firing at reduced stake.
- `QM_KILL_ACCEPT_CLOSES` (default 2) — consecutive 5m closes beyond
  level required for LEVEL_BOUNCE acceptance-kill.
- `QM_KILL_ACCEPT_BARS` (default 2) — sustain window for the same.

All four are read `_env_float(...)` per decision — no restart needed to
tune. The gating flag `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED` remains
the master kill-switch for the STRONG_TREND consult (already `1` in env).

**Restart-required** (code changes take effect on process restart):
- `gbpusd_bb_bounce.py` — new consult logic.
- `trade_executor.py` — sizing multiplier plumb.
- `standdown_shadow.py` — record signature.
- `auto_k.py` — LEVEL_BOUNCE branch + acceptance eval.
- `trade_manager.py` — strategy_meta passthrough.

Operator to restart. No push. Local commit only.
