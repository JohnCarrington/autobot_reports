# SPEC vs RUNNING — Day-Context Exit Management

**Report date:** 2026-08-23 (walk performed at 2026-08-22 20:15 UTC boot + walk at
2026-08-22 evening).
**Host:** `161.35.168.61`, `/opt/tradingbot`.
**Running process:** `MainPID=2131608`, started
`ActiveEnterTimestamp=Sat 2026-08-22 20:15:42 UTC`
(`systemctl show autobot.service -p MainPID,ActiveEnterTimestamp`).
**Loaded code (HEAD at process start):**
`54fc3590318119c87d8b0162f26939abd5aa1bcd 2026-08-22 19:56:26 UTC`
(`git log -1`; process cwd is `/opt/tradingbot`, so this is the loaded commit —
no diverged worktree).
**Mode:** investigate-only, no changes.

---

## 0. Spec (quoted back before diffing)

1. **Day type never admits/blocks fires.**
2. **Calendar classified at boot + daily.**
3. **Exit dress per (mode, day_ctx) — patient on news-adjacent, standard on CLEAR.**
4. **BIG_NEWS bounce half-size bias, never a block.**
5. **day_ctx + dress stamped per fire.**
6. **Wrong calendar read can only cost exit-efficiency, never a trade.**

---

## 1. Guard test + admission-side reads

### SPEC
No admission-side code path may import or read the four-label day-context output.
A pytest guard enforces the allowlist.

### RUNNING
Loaded-commit test result:

```
$ venv/bin/python -m pytest tests/unit/test_day_context.py::test_no_admission_import_guard -x -q
.                                                                        [100%]
1 passed in 0.17s
```

Allowlist in the test at `tests/unit/test_day_context.py:150-158`:

```
allowlist = {
    "day_context.py", "exit_dress.py", "level_ladder.py",
    "trade_executor.py", "signal_logger.py", "autobot.py",
    "daily_journal.py",
}
```

Manual re-scan of every top-level `*.py` for `import day_context`:

```
$ grep -n -E 'from\s+day_context|import\s+day_context' /opt/tradingbot/*.py
autobot.py:9049:        import day_context as _day_ctx
daily_journal.py:2061:        import day_context as _dcj
level_ladder.py:615:        import day_context as _dc
signal_logger.py:1161:            import day_context as _dcx
trade_executor.py:2040:                import day_context as _dc_hs
trade_executor.py:2259:                        import day_context as _dc_arm
```

Every consumer is on the allowlist. All six use-sites are exit-management,
half-size sizing, or telemetry — none of them admit or block a fire:

- `autobot.py:9049` — boot classify (no decision).
- `daily_journal.py:2061` — EOD summary lead field.
- `level_ladder.py:615` — dress applied at ladder arm.
- `signal_logger.py:1161` — telemetry stamp only.
- `trade_executor.py:2040` — half-size bias (a *bias*).
- `trade_executor.py:2259` — dress read at arm-time to pick TIERED_RATCHET vs LADDER.

### VERDICT
**CONFORMANT.** Guard exists, passes at loaded commit, and static grep confirms
no rogue import. Principle #1 has a mechanical enforcement point, not just
docstring text.

---

## 2. DAY_CTX enable state; what classification runs; today's label

### SPEC
Calendar is classified at boot + daily. DAY_CTX behind a kill-switch;
default off. When off, every consumer reads CLEAR (no admission read exists,
so this can only affect exit-side and telemetry).

### RUNNING (raw, from `/proc/2131608/environ`)

```
DAY_CTX_ENABLED           = <unset>   (default '0' → False)
DAY_CTX_BOUNCE_HALF_SIZE  = <unset>   (default '0' → False)
CALENDAR_DAY_TYPE_ENABLED = 1
DAY_TYPE_CLASSIFIER_ENABLED = 1
POSTURE_BIG_NEWS_ENABLED  = 1
POSTURE_NORMAL_ENABLED    = 1
LADDER_ENABLED            = 1
LADDER_MANAGED_MODES      = GBPUSD_EMA_PULLBACK_L,GBPUSD_EMA_PULLBACK_S,GBPUSD_TREND_V3_L,GBPUSD_TREND_V3_S
EXIT_STACK_GBPUSD_EMA_PULLBACK_L = TIERED_RATCHET
EXIT_STACK_GBPUSD_EMA_PULLBACK_S = TIERED_RATCHET
EXIT_STACK_GBPUSD_TREND_V3_L     = TIERED_RATCHET
EXIT_STACK_GBPUSD_TREND_V3_S     = TIERED_RATCHET
DRESS_MAP_*   (all four)  = <unset>
DRESS_DEFAULT_* (all four) = <unset>
```

Journal since process start (`journalctl -u autobot.service --since '2026-08-22 20:15:00'`):

```
2026-08-22 20:15:44,917 [INFO] [DAY_CTX] boot enabled=False state_path=/opt/tradingbot/cache/day_context_state.json
2026-08-22 20:15:45,214 [INFO] [DAY_CTX] classify_today date=2026-08-22 label=CLEAR big_today=0 big_prev=0 big_next=0
2026-08-22 20:15:45,214 [INFO] [AUTOBOT] day_context boot classify complete label=CLEAR
2026-08-22 20:15:45,215 [INFO] [AUTOBOT] day_context 00:05 UTC scheduler started
```

**Boot classification DOES run unconditionally**, even with `DAY_CTX_ENABLED=0`
(see `day_context.py:207-233` — `classify_today()` executes
`_classify_from_events()` and writes state regardless of ENABLED; the flag only
gates what `current()`/`label()` returns; per module docstring lines 42–58).
State written to `/opt/tradingbot/cache/day_context_state.json`:

```
{"date":"2026-08-22","enabled":false,"label":"CLEAR",
 "big_today":[],"big_prev":[],"big_next":[],
 "written_at":"2026-08-22T20:15:44.917420+00:00"}
```

**The 00:05 UTC scheduler thread is installed and running** —
`autobot.py:9058-9077`, `threading.Thread(target=_day_ctx_daily_loop,
daemon=True, name='day_ctx_daily').start()`. Sleeps to next 00:05 UTC,
calls `_dc.classify_today()`, loops.

**Every fire today gets `day_ctx = "CLEAR"`**, because `day_context.label()`
short-circuits when ENABLED is False:

```python
# day_context.py:245-252
if not ENABLED:
    return {
        "date": ...,
        "label": LABEL_CLEAR,
        "big_today": [], "big_prev": [], "big_next": [],
        "enabled": False,
    }
```

Note: today's Finnhub cache
`/opt/tradingbot/cache/news_state_finnhub_2026-08-22.json` **does not exist**
(latest cached file is `_2026-08-21.json`). The boot classify still produced
label=CLEAR because `big_events_for(2026-08-22)` returned `[]` — no BIG events
matched from the older snapshots for today's date. This is the failure mode
that principle #6 protects against.

### VERDICT
- Boot + 00:05 refresh: **CONFORMANT** (both wired and running).
- Kill switch state today: **DARK** (`DAY_CTX_ENABLED=0`).
- Runtime label for every fire today: `CLEAR` (from `day_context.label()`,
  not from the calendar snapshot).

---

## 3. Dress-resolution table

### SPEC
Exit dress per `(mode, day_ctx)` — patient on news-adjacent (BIG_NEWS /
PRE_BIG / POST_BIG), standard on CLEAR. Ladder-managed modes only.

### RUNNING — walk of `exit_dress.resolve()` at the loaded commit (`exit_dress.py:152-219`)

Resolution order is (1) `EXIT_STACK_<MODE>` per-mode override, (2)
`DRESS_MAP_<LABEL>` env / built-in trend defaults, (3) `DRESS_DEFAULT_<LABEL>`,
(4) ambient per-mode default (LADDER_STANDARD for ladder-managed, MANAGED
otherwise). Full walk under the running process's env:

**(i) Current env (running process, `DAY_CTX_ENABLED` unset)**

| MODE                     | CLEAR          | BIG_NEWS       | PRE_BIG        | POST_BIG       |
|:-------------------------|:---------------|:---------------|:---------------|:---------------|
| GBPUSD_TREND_V3_L        | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_TREND_V3_S        | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_EMA_PULLBACK_L    | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_EMA_PULLBACK_S    | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_BB_BOUNCE_L       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_BB_BOUNCE_S       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_NEWS_FADE_L       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_NEWS_FADE_S       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |

**(ii) Hypothetical `DAY_CTX_ENABLED=1`, no other change**

| MODE                     | CLEAR          | BIG_NEWS       | PRE_BIG        | POST_BIG       |
|:-------------------------|:---------------|:---------------|:---------------|:---------------|
| GBPUSD_TREND_V3_L        | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_TREND_V3_S        | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_EMA_PULLBACK_L    | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_EMA_PULLBACK_S    | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_BB_BOUNCE_L       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_BB_BOUNCE_S       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_NEWS_FADE_L       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_NEWS_FADE_S       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |

**(iii) Hypothetical `DAY_CTX_ENABLED=1` + `DRESS_MAP_<ALL>=<current dresses>`**

| MODE                     | CLEAR          | BIG_NEWS       | PRE_BIG        | POST_BIG       |
|:-------------------------|:---------------|:---------------|:---------------|:---------------|
| GBPUSD_TREND_V3_L        | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_TREND_V3_S        | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_EMA_PULLBACK_L    | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_EMA_PULLBACK_S    | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET | TIERED_RATCHET |
| GBPUSD_BB_BOUNCE_L       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_BB_BOUNCE_S       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_NEWS_FADE_L       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |
| GBPUSD_NEWS_FADE_S       | MANAGED        | MANAGED        | MANAGED        | MANAGED        |

### Cells foreclosed by `EXIT_STACK_<MODE>`

`EXIT_STACK_GBPUSD_TREND_V3_{L,S} = TIERED_RATCHET` and
`EXIT_STACK_GBPUSD_EMA_PULLBACK_{L,S} = TIERED_RATCHET` are read at
`exit_dress.py:190-202` **before** any label consultation. That means, for
those four modes, **every one of the {CLEAR × BIG_NEWS × PRE_BIG × POST_BIG}
cells collapses to TIERED_RATCHET**, and LADDER_PATIENT / LADDER_STANDARD /
DRESS_MAP / DRESS_DEFAULT can never win — the 16 "trend cells" above are
foreclosed by step 1.

This is the operator-ratified state per the 2026-08-22 Ruling (Item 6 in
`trade_executor.py:2288-2296` and Item 6 rulings referenced by
`day_ctx_build_20260822/REPORT.md`). LADDER_PATIENT is dead code under the
current env; it will remain dead unless (a) an `EXIT_STACK_<MODE>` is
unset/overridden AND (b) DAY_CTX flips on AND (c) day_ctx yields
BIG_NEWS/PRE_BIG/POST_BIG AND (d) no DRESS_MAP override redirects it.

### VERDICT
- Spec item #3 as *built*: **CONFORMANT** — mechanism exists; the LADDER_PATIENT
  overlay path (assess_bars+1, stop_buffer+1p, exhaustion=session_end) is
  installed in `level_ladder.py:603-628` and `exit_dress.patient_overlay_params`.
- Spec item #3 as *running*: **OVERRIDDEN** — by design, per the 2026-08-22
  ruling. TIERED_RATCHET is applied to every trend fire regardless of day_ctx.

---

## 4. Half-size bias (BIG_NEWS bounce)

### SPEC
BIG_NEWS bounce half-size bias — never a block.

### RUNNING — code path

`trade_executor.py:2022-2058` (quoted verbatim):

```python
# ── DAY_CTX bounce half-size bias (2026-08-22) ────────────────────────
# On BIG_NEWS days, if this fire is a bounce-family strategy AND lands
# within ±DAY_CTX_BOUNCE_HALF_SIZE_WINDOW_MIN of a listed TIER1
# release, size at 50%. A BIAS, never a block — the fire proceeds
# regardless. Kill switch DAY_CTX_BOUNCE_HALF_SIZE=0 (default) leaves
# sizing byte-identical.
try:
    if os.getenv("DAY_CTX_BOUNCE_HALF_SIZE", "0").strip() in ("1", "true", "yes", "on"):
        _mode_up = str(getattr(decision, "mode", "") or "").upper()
        _bounce_markers = (
            "BB_BOUNCE", "BB_REV", "LEVEL_BOUNCE", "REVERSAL_SWEEP",
            "RANGE_REVERSION", "BB_REVERSAL",
        )
        if any(m in _mode_up for m in _bounce_markers):
            import day_context as _dc_hs
            from datetime import datetime as _dc_dt, timezone as _dc_tz
            _now = _dc_dt.now(_dc_tz.utc)
            if _dc_hs.label(_now) == _dc_hs.LABEL_BIG_NEWS:
                _win = int(os.getenv("DAY_CTX_BOUNCE_HALF_SIZE_WINDOW_MIN", "45"))
                if _dc_hs.within_release_window(_now, _win):
                    _pre = trade_size
                    trade_size = trade_size * 0.5   # ← bias, not a return
                    logger.info(
                        "[DAY_CTX] bounce half-size bias applied: mode=%s "
                        "size %s → %s (window=±%dmin)",
                        _mode_up, _pre, trade_size, _win,
                    )
except Exception as _hs_exc:
    # Bias failure must NEVER block the fire — log and proceed.
    logger.warning(
        "[DAY_CTX] bounce half-size bias failed (proceeding at full size): %s",
        _hs_exc,
    )
```

Bias-not-block proof:
- Only mutation is `trade_size = trade_size * 0.5`. There is no `return`, no
  `raise`, no state change that vetoes the trade.
- Exception handler catches everything and continues (`# Bias failure must
  NEVER block the fire`).
- Enclosing function proceeds to `open_sb_now(...)` at line 2063
  unconditionally.

### Flag state today
`DAY_CTX_BOUNCE_HALF_SIZE = <unset>` (default `'0'` → False). The whole block
short-circuits at line 2029, `trade_size` untouched.

Additionally: even if `DAY_CTX_BOUNCE_HALF_SIZE=1` were set today,
`DAY_CTX_ENABLED=0` means `_dc_hs.label(_now)` returns `"CLEAR"` — never
`LABEL_BIG_NEWS` — so the bias would still not trigger. Double-locked.

### If flipped today (hypothetical)
- `DAY_CTX_BOUNCE_HALF_SIZE=1` alone: no effect (label always CLEAR).
- `DAY_CTX_BOUNCE_HALF_SIZE=1` **and** `DAY_CTX_ENABLED=1`: BB_BOUNCE /
  BB_REVERSAL / LEVEL_BOUNCE / REVERSAL_SWEEP / RANGE_REVERSION fires within
  ±45 min of a TIER1 release would size at 50%. Nothing else changes. Not a
  gate on entry or arm.

### VERDICT
- Bias-not-block guarantee: **CONFORMANT** in code.
- Live effect today: **DARK** (both `DAY_CTX_BOUNCE_HALF_SIZE=0` and
  `DAY_CTX_ENABLED=0` — either alone is enough to inert this path).

Note: `POSTURE_BIG_NEWS_ENABLED=1` in env is a *separate* observer in
`posture.py:122-172` that only emits `[POSTURE-BIG-NEWS]` log lines; it takes
no action on any fire (`posture.py:158-171` — logs only). Consumers looking
for a stand-down effect will find none.

---

## 5. signal_log stamping (today's fires)

### SPEC
`day_ctx` + dress stamped per fire.

### RUNNING — stamping code (`signal_logger.py:1150-1178, 1383-1393`)

```python
# DAY_CTX + EXIT_DRESS stamp (2026-08-22, OBSERVABLE-ONLY).
# Pure telemetry. day_ctx is the four-label classification from
# day_context.py (BIG_NEWS / PRE_BIG / POST_BIG / CLEAR).
# dress is the resolved bracket the exit_dress selector would
# return for (mode, day_ctx) — stamped even when the ladder
# doesn't take over the position (e.g. non-ladder-managed modes
# or D1-stale), so downstream analysis can bucket by dress.
# Both null-safe.
_day_ctx_label: Optional[str] = None
_exit_dress_bracket: Optional[str] = None
try:
    import day_context as _dcx
    _day_ctx_label = _dcx.label(now_utc)
except Exception as _dcx_exc:
    _log.debug("[signal_logger] day_context stamp failed (null preserved): %s", _dcx_exc)
try:
    import exit_dress as _edx
    _mode_for_dress = str(getattr(decision, "mode", "") or "")
    _exit_dress_bracket = _edx.resolve(_mode_for_dress, _day_ctx_label or "CLEAR")
except Exception as _edx_exc:
    _log.debug("[signal_logger] exit_dress stamp failed (null preserved): %s", _edx_exc)
...
record = {
    ...
    "day_ctx":     _day_ctx_label,     # signal_logger.py:1383
    "exit_dress":  _exit_dress_bracket, # signal_logger.py:1384
    "exit_stack":  _exit_dress_bracket, # signal_logger.py:1393  (mirror)
    ...
}
```

### Value per field on the *next* fire, as configured

- `day_ctx`: `"CLEAR"` (string, not null, not absent). `day_context.label()`
  short-circuits to CLEAR when ENABLED=False; import cannot fail because it
  already loaded at boot.
- `exit_dress` / `exit_stack`: bracket string per §3 above:
  `TIERED_RATCHET` for TREND_V3 / EMA_PULLBACK long+short; `MANAGED` for
  everything else. Not null.
- `trend_subtype`: **NOT a top-level signal_log field**. It exists as
  `dbg["trend_subtype"]` in the strategy debug bag
  (`gbpusd_trend_v3.py:594-596`), populated from
  `regime_engine._compute_trend_subtype()`. It reaches signal_log only via the
  `debug` sub-dict (mode-specific) and via the flattened `engine_regime_*`
  fields when the regime engine's snapshot exposes it. The top-level
  `regime_at_fire`, `engine_regime_at_fire`, `regime_signals` fields are
  stamped at `signal_logger.py:1235-1261`. There is no
  `record["trend_subtype"] = ...` in `signal_logger.py`.
- `calendar_day_type` + `calendar_dual_labels` + `calendar_cycle_position`:
  stamped independently at `signal_logger.py:1131-1142` from
  `calendar_day_type.classify_date(now_utc.strftime('%Y-%m-%d'))`. This
  path is **not gated on DAY_CTX_ENABLED** and yields the real neighbour
  resolution.

### October cohort analysis — collecting or starving?

- **Via `day_ctx`: STARVING.** Every fire while DAY_CTX is dark stamps `"CLEAR"`.
  The four-label {BIG_NEWS / PRE_BIG / POST_BIG / CLEAR} distinction that
  October cohorts need is not being emitted; a downstream bucketer keyed on
  `day_ctx` will see 100% CLEAR.
- **Via `calendar_day_type`: COLLECTING.** The independent stamp at line 1138
  gives BIG_NEWS / PRE_NEWS / POST_NEWS / NORMAL from
  `calendar_day_type.classify_date` regardless of DAY_CTX_ENABLED. A cohort
  analysis that reads `calendar_day_type` / `calendar_dual_labels` /
  `calendar_cycle_position` will bucket correctly.

Confirmation from the most-recent signal_log row (`signal_log.jsonl` last
line, `2026-08-21T13:10:02Z`, `mode=GBPUSD_EMA_PULLBACK_S`):

```
day_ctx: None
exit_dress: None
exit_stack: None
calendar_day_type: NORMAL
calendar_dual_labels: ['NORMAL']
day_news_tier: MIDDLE
day_type_at_fire: NORMAL
```

The `None`s in `day_ctx`/`exit_dress`/`exit_stack` are because this row
predates the 2026-08-22 build; those fields did not exist as stamped fields
in the loaded module at the time. On the *next* fire under the currently
loaded commit (54fc359), `day_ctx`/`exit_dress`/`exit_stack` will be
non-null and equal to `CLEAR` / `TIERED_RATCHET|MANAGED` /
`TIERED_RATCHET|MANAGED` respectively.

### Minimal env change for telemetry-only labels

The operator's stated combination is `DAY_CTX_ENABLED=1` **plus**
`DRESS_MAP_<LABEL>` pinned to today's dresses. It is expressible and
behaviour-identical, as follows:

1. **Expressible.** All four `DRESS_MAP_<LABEL>` vars accept the
   `MODE1:BRACKET,MODE2:BRACKET,...` schema (`exit_dress.py:104-127`);
   `EXIT_STACK_<MODE>` is a per-mode override; nothing forbids setting both.

2. **Behaviour-identical, walked at the loaded commit.**
   - For the four trend modes, `EXIT_STACK_<MODE>=TIERED_RATCHET` fires at
     step 1 and **overrides the DRESS_MAP entirely**, so any `DRESS_MAP_*` pin
     is redundant for them. Result: TIERED_RATCHET, unchanged.
   - For everything else (BB_BOUNCE, NEWS_FADE, etc.), the trend-only
     `_DEFAULT_TREND_MAP` never contains those modes, so `_load_map_for_label`
     returns `{}`; DRESS_MAP being pinned or empty makes no difference for
     them; step 3 sees no `DRESS_DEFAULT_<LABEL>`; step 4 returns MANAGED.
     Result: MANAGED, unchanged.
   - Table (iii) in §3 is byte-identical to table (i).

3. **Effect this actually buys.** With `DAY_CTX_ENABLED=1`,
   `signal_logger.py:1162` no longer short-circuits to `"CLEAR"`. It resolves
   the true label from the on-disk snapshot / cache, so October cohorts get
   BIG_NEWS / PRE_BIG / POST_BIG / CLEAR variation on `day_ctx`. Fire
   outcomes are unaffected because dress resolution is dominated by
   `EXIT_STACK_<MODE>`.

**Not applied.** Reported for review only. Do not enable without operator
ruling.

### VERDICT
- Stamping code present: **CONFORMANT**.
- Actual values under running env: **DARK** for `day_ctx` (constant CLEAR),
  **LIVE + OVERRIDDEN** for `exit_dress`/`exit_stack` (TIERED_RATCHET for
  trend modes, MANAGED elsewhere).
- `trend_subtype` at top level of signal_log record: **DARK** — not a
  top-level field in the loaded stamping code; only reaches signal_log via
  strategy `debug` dict or engine snapshot.

---

## 6. Failure-bound — wrong calendar today, what can it break?

### SPEC
A wrong calendar label can only cost exit-efficiency, never cost a trade.

### Path enumeration (running process, DAY_CTX dark)

For every code site that reads a calendar-derived label (day_context OR
calendar_day_type), what would a bad label do today?

| # | Site | Reads | Today's effect of wrong label |
|:-:|:-----|:------|:------------------------------|
| 1 | `signal_logger.py:1131-1142` | `calendar_day_type.classify_date` | Stamps `calendar_day_type` / `calendar_dual_labels` / `calendar_cycle_position` on the fire row — **telemetry only**. No trade effect. |
| 2 | `signal_logger.py:1158-1178` | `day_context.label` + `exit_dress.resolve` | `day_context.label()` is constant `CLEAR` (dark). Stamps `day_ctx`/`exit_dress`/`exit_stack` — **telemetry only**. No trade effect. |
| 3 | `trade_executor.py:2022-2058` (half-size) | `day_context.label` + `within_release_window` | `DAY_CTX_BOUNCE_HALF_SIZE=0` and `label()==CLEAR`; block is dead. **No effect.** |
| 4 | `trade_executor.py:2255-2288` (dress at arm) | `day_context.label` + `exit_dress.resolve` | Dominated by `EXIT_STACK_<MODE>=TIERED_RATCHET`; TREND_V3 / EMA_PULLBACK always route to ratchet. **Bracket choice unchanged by label.** |
| 5 | `level_ladder.py:603-628` (dress inside arm) | `day_context.label` + `exit_dress.resolve` | Reached only if `_bracket_arm != TIERED_RATCHET` (i.e. non-trend modes here — but non-trend modes are not in LADDER_MANAGED_MODES, so `level_ladder.arm()` refuses at line 564). **Dead path today.** |
| 6 | `daily_journal.py:2061-2077` | `day_context.current` | EOD summary lead field — **telemetry only**. |
| 7 | `posture.py:122-171` (`POSTURE_BIG_NEWS_ENABLED=1`) | `calendar_day_type.classify_date` | Log-only observer (`[POSTURE-BIG-NEWS] proximate fire — ...`). **No stand-down.** |
| 8 | `gbpusd_level_bounce.py:157-165` | `calendar_day_type.classify_date` | Stamps `calendar_day_type` on internal `_log_c2_row`s — **telemetry only**. Also passes into signal_log via the standard dispatcher stamp. **No trade effect.** |
| 9 | `day_planner.py:296-302` | `news_state.news_state_snapshot` (not calendar_day_type) | Builds the day-plan Telegram / summary text; **operator-facing telemetry**. Not consulted by executor. |
| 10 | `day_posture.py:170-195` | `calendar_day_type.classify_date` | Resolves `day_subtype` for the telemetry-only posture dict; not read by admission code (see day_posture.py docstring: "day_posture_latch.json" is no longer written; the machinery that fed DAY_TIER_MASK admission was deleted 2026-08-21). **Telemetry only.** |

### Would-be effects if DAY_CTX were LIT and calendar were wrong

- Path #2 (signal_log stamp): telemetry mislabel — same net effect, but now
  the mislabel is visible on the fire row.
- Path #3 (half-size): if `DAY_CTX_BOUNCE_HALF_SIZE=1` **and** the label were
  a false BIG_NEWS within a ±45m window, a bounce-family fire could size at
  50% instead of 100%. **Bias, not a block** — the trade still fires.
- Path #4/#5 (dress at arm): with `EXIT_STACK_<MODE>` still set, no change.
  If `EXIT_STACK_<MODE>` were also removed and the label were wrong, a trend
  fire could be routed to LADDER_PATIENT instead of LADDER_STANDARD (or vice
  versa) — a wider `stop_buffer_pips` and later exhaustion — again, an
  exit-management difference, not a trade admission difference.
- Paths #1, #6, #7, #8, #9, #10: strictly telemetry.

### VERDICT
- Failure-bound principle in code (dark): **CONFORMANT**. Every path enumerated
  is telemetry, dead, or an exit/sizing bias — none are admission gates.
- Failure-bound principle if lit: **CONFORMANT** — the only escalations open
  the door to exit-management or 50% sizing changes; there is no path from
  a wrong label to a suppressed fire.

---

## 7. Summary diff

| # | Spec principle | Built? | Live? | Overridden? | Evidence |
|:-:|:---------------|:------:|:-----:|:-----------:|:---------|
| 1 | Day type never admits/blocks | ✔ | ✔ | — | `test_no_admission_import_guard` passes at 54fc359; no admission-side `import day_context`; §1 above. |
| 2 | Calendar classified boot+daily | ✔ | ✔ | — | `[DAY_CTX] classify_today` at 20:15:45; `day_ctx_daily` thread started; `day_context.py:207`; `autobot.py:9049-9077`. |
| 3 | Exit dress per (mode, day_ctx) | ✔ | partial | ✔ (by design) | `exit_dress.resolve` present; but `EXIT_STACK_<MODE>=TIERED_RATCHET` (env) forecloses all 16 trend cells → LADDER_PATIENT dead code today. Operator-ratified state (2026-08-22 ruling Item 6). |
| 4 | BIG_NEWS bounce half-size bias, never a block | ✔ | ✗ (dark) | — | Code at `trade_executor.py:2022-2058`, bias-not-block confirmed; `DAY_CTX_BOUNCE_HALF_SIZE=0` **and** `DAY_CTX_ENABLED=0` → double-locked. |
| 5 | day_ctx + dress stamped per fire | ✔ | partial | — | Stamping code at `signal_logger.py:1150-1178, 1383-1393`. `day_ctx` will be constant `"CLEAR"` on live fires (dark); `exit_dress`/`exit_stack` real (TIERED_RATCHET / MANAGED). October cohorts starve on `day_ctx`, collect on `calendar_day_type`. `trend_subtype` **not** stamped as a top-level signal_log field. |
| 6 | Wrong calendar can only cost exit-efficiency, never a trade | ✔ | ✔ | — | All 10 enumerated read sites (§6) are exit-side, telemetry, or dead-under-current-env. No admission path takes calendar as input. |

**Overall:** the spec is *built* on every principle. Principle 3 is
overridden by the operator's own `EXIT_STACK_<MODE>=TIERED_RATCHET` per the
2026-08-22 ruling — LADDER_PATIENT overlay code exists but never fires;
review-worthy only if the ruling is revisited. Principle 4's half-size hook
is dark (both switches off); principle 5's `day_ctx` field is dark (constant
CLEAR) while `exit_dress`/`exit_stack` are live. Principles 1, 2, 6 are
conformant and demonstrably enforced in code.

---

## 8. Contradictions with prior reports

- `reports-public/day_ctx_build_20260822/REPORT.md` describes the *built*
  spec (LADDER_PATIENT default overlay when DAY_CTX enabled). **This report
  is consistent** with that build description; the "OVERRIDDEN" verdict on
  principle #3 is not a contradiction of the build report — it is the
  consequence of the operator-ratified 2026-08-22 ruling (Item 6) documented
  in memory (`project_ratchet_enable_option_a.md`: "EXIT_STACK_ step-1 wins
  over BIG_NEWS/day_ctx by design; LADDER_PATIENT dead unless DAY_CTX
  enabled + telemetry proves it").

- No contradictions with prior reports found. The 2026-08-22 build report,
  the ratchet enable Option A memory, and this spec-vs-running walk are
  internally consistent.

---

## 9. How each RUNNING claim was verified

- **Loaded PID/timestamps:** `systemctl show autobot.service -p MainPID,ActiveEnterTimestamp` (2131608, `Sat 2026-08-22 20:15:42 UTC`).
- **Loaded commit:** process cwd `/proc/2131608/cwd → /opt/tradingbot`; `git log -1` gave `54fc359 2026-08-22 19:56:26 UTC test(grind): pin baseline …`. Process started ~19 minutes after that commit landed; no diverged worktree evidence.
- **Env values:** `cat /proc/2131608/environ | tr '\\0' '\\n'`.
- **Boot classify & scheduler:** `journalctl -u autobot.service --since '2026-08-22 20:15:00'`.
- **State snapshot:** `cat /opt/tradingbot/cache/day_context_state.json`.
- **Guard test at loaded commit:** `venv/bin/python -m pytest tests/unit/test_day_context.py::test_no_admission_import_guard -q`.
- **Dress-resolution tables:** in-process walk under the exact env vars from `/proc/2131608/environ`, importing `exit_dress` / `level_ladder` / `day_context` fresh. Same code the running process loaded (54fc359).
- **Half-size code & stamping code:** direct Read of `trade_executor.py`, `signal_logger.py`, `day_context.py`, `exit_dress.py`, `level_ladder.py` at HEAD.
- **Signal_log field observation:** parsed last row of `logs/signal_log.jsonl` for schema check; the `None`s are pre-build rows (the new fields land on the next post-2026-08-22 fire).

No recommendations. The operator rules on the diff.
