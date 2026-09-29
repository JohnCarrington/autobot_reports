# AutoBot Production Repair 4 — Sunday / NY_CLOSE / Session Semantics

Date: 2026-09-29
Author: Claude Opus 4.7 (autobot session, operator-directed)
Follows:
* Repair 1 execution firewall — `bcd245286c43ea56237b6b796fec00374b5de7b2`
* Repair 2 current-interaction ownership + freshness — `477bd4582c452a2355e3a95f0abe22e9a3d81b3f`
* Repair 3 ONE_STRATEGY position ownership + thesis management — `f70f8a7e1b3a007c636d9604a35859bdbce7dd71`

---

## 1. HEAD BEFORE

```
f70f8a7e1b3a007c636d9604a35859bdbce7dd71
feat(stage12): ONE_STRATEGY position ownership + thesis-invalidation management
```

Branch: `feat/trend-stretch-brake-adx-floor`.

---

## 2. SUNDAY INCIDENT ROOT CAUSE

`DIAAAAYJSBKY9BL` — GBPUSD ONE_STRATEGY **SELL** opened
2026-09-27T20:55:03Z @ 13235.3, closed 2026-09-27T20:55:08Z @ 13242.3
(reason=`NY_CLOSE`, ~-7p, lifetime ≈5s). Confirmed from
`logs/close_intent.jsonl`:

```
{"deal_id":"DIAAAAYJSBKY9BL","expected_reason":"NY_CLOSE","kind":"intent",
 "partial":false,"path":"close_trade","ts_epoch_ms":1790542508527,
 "ts_utc":"2026-09-27T20:55:08.527Z"}
```

Chain of events reconstructed from source read (autobot.py:3379–3397,
:2581–2586, :290–292, :4684–4705) and env (`.env` line 479 —
`BRIEFING_EXEC_SKIP_NY_CLOSE=1`; `NY_CLOSE_HHMM` not overridden, defaults
to `"16:55"` in NY-local time; `NY_CLOSE_ENABLED` default 1;
`NY_CLOSE_WINDOW_MINUTES` default 10):

1. Sunday 2026-09-27 20:55:03 UTC is inside broker Sunday-reopen window
   (broker resumes ~20:00 UTC Sun per `_is_fx_session_closed` docstring
   at autobot.py:1852–1855).
2. `_should_close_for_ny_end` was invoked; `_ny_now()` returned
   `2026-09-27 16:55:03 EDT` (America/New_York, still EDT until
   2026-11-01). `weekday()==6` (Sunday).
3. Window check `16:55 ≤ 16:55:03 < 17:05` passed.
4. Dedup check `last_done_date_by_epic.get(epic) != "2026-09-27"` passed
   (fresh Sunday).
5. Predicate returned `True`.
6. Dispatch loop at autobot.py:4690–4699 iterated positions for the
   epic. The BRIEFING_EXEC skip at :4692 did not match
   (`_is_briefing_exec_mode("ONE_STRATEGY") == False` — prefix set is
   `("BRIEFING_EXECUTION", "BRIEFING_PIA_FIRST", "GBPUSD_TREND")`).
7. `close_position(pos_key=_ny_pk, reason="NY_CLOSE",
   exit_hint_price=mid_f)` fired against the 5-second-old SELL.
8. Broker DELETE completed at 20:55:08 UTC → -7p realised.

Two defects compound:

* **(A) Session-identity defect.** `_should_close_for_ny_end` uses a
  clock predicate (NY-local HH:MM window) with no NY-weekday guard. The
  NY session (which NY_CLOSE marks the end of) exists Mon-Fri; Sat/Sun
  have no session end. The predicate fired on Sunday because
  `weekday()` was never consulted.
* **(B) ONE_STRATEGY inheritance defect.** ONE_STRATEGY was not in the
  NY_CLOSE dispatch exemption list. Per Repair 3
  (`one_strategy_management.py:1–38`) the only authorised exits for
  ONE_STRATEGY are Stage-12 thesis-invalidation and the broker
  mechanical SL/TP. The same class of legacy-inheritance defect Repair
  3 §5 closed for the +10p scale-out was still present at NY_CLOSE.

Defect A alone is sufficient to explain the Sunday incident. Defect B
is defence-in-depth: without B, a legitimate Mon-Fri NY_CLOSE fire
would still legacy-flatten ONE_STRATEGY on any weekday. Both are
repaired here.

---

## 3. NY_CLOSE INTENDED SEMANTICS

Determined from code and env, not narrative:

* **Daily NY-session flatten**, not Friday-only. `_should_close_for_ny_end`
  has no weekday branch (pre-repair) — it fires every day the window
  is entered. `BRIEFING_EXEC_SKIP_NY_CLOSE=1` (default) explicitly
  routes BRIEFING_EXECUTION to a separate EOD close at 21:00 UTC daily
  (autobot.py:2610–2717).
* **Strategy families that intentionally use it:** every non-BE family
  (`GBPUSD_BB_BOUNCE`, `GBPUSD_EMA_PULLBACK`, `NEWS_STRATEGY`,
  `V2_PICK_BOUNCE`, `LEVEL_BOUNCE`, plain `GBPUSD_TREND`, `BB_REVERSAL`,
  etc.) is subject to NY_CLOSE at NY 16:55. BE variants (matched by
  `_is_briefing_exec_mode`) are exempted at the dispatch site.
  `GBPUSD_TREND_V3_UM_L/S` positions do not typically survive to
  NY_CLOSE because `_apply_trend_v3_um_eod_close` fires 15 min earlier
  (autobot.py:2791–2885).
* **`GBPUSD_TREND` prefix** is matched by `_is_briefing_exec_mode` as
  well (see autobot.py:363–385 naming-note comment: the function name is
  historical; the members set is a broader "EOD-swept modes" superset).
  So `GBPUSD_TREND_L/S` are also skipped by the same BE exemption and
  ride their software trail to broker SL/TP or the 21:00 UTC EOD sweep.
* **ONE_STRATEGY** was never explicitly enumerated by any design
  decision as an NY_CLOSE participant. Repair 3
  (`one_strategy_management.py:1–38`) is the authoritative statement
  that ONE_STRATEGY is managed only by Stage 12 thesis-invalidation +
  broker mechanical SL/TP. Prior to this repair it silently inherited
  NY_CLOSE by default because it wasn't in the exemption list —
  identical mechanism to the +10p scale-out defect Repair 3 §5 closed.

Env inputs (from `.env` and defaults):

| Key | Value | Notes |
|---|---|---|
| `NY_CLOSE_ENABLED` | `1` (default; not overridden) | Kill switch |
| `NY_CLOSE_HHMM` | `16:55` (default; not overridden) | NY-local HH:MM |
| `NY_CLOSE_WINDOW_MINUTES` | `10` (default; not overridden) | 16:55–17:05 |
| `BRIEFING_EXEC_SKIP_NY_CLOSE` | `1` (`.env:479`) | BE positions skip |
| `BRIEFING_EXEC_EOD_CLOSE_ENABLED` | `1` (`.env`) | Own EOD path |
| `BRIEFING_EXEC_EOD_CLOSE_UTC` | `21:00` (`.env`) | 21:00 UTC |
| `ONE_STRATEGY_MANAGEMENT_ENABLED` | `1` (default; Repair 3) | Stage 12 wire |

---

## 4. TIMEZONE USED

**America/New_York** (via `zoneinfo.ZoneInfo("America/New_York")` in
`_ny_now()` at autobot.py:2581–2586). This is DST-safe — the window
tracks the NY wall clock through EDT/EST transitions automatically. UTC
offset varies:

* EDT (Mar 8 → Nov 1): NY 16:55 == 20:55 UTC → window 20:55–21:05 UTC
* EST (Nov 1 → Mar 8): NY 16:55 == 21:55 UTC → window 21:55–22:05 UTC

The 20:55 UTC that appeared in the Sunday incident is a direct
consequence of NY 16:55 EDT — not naive UTC arithmetic. Repair 4 uses
the same `_ny_now()` handle, so DST invariance is preserved. The DST
boundary is asserted by `TestInvariant_06_DstBoundary` (weekday still
fires post-DST-end at 16:55 EST; Sunday still suppressed post-DST-end).

Other timed-close authorities and their clocks:

| Authority | Clock read | Fires |
|---|---|---|
| NY_CLOSE | `_ny_now()` (NY-local, DST-safe) | Daily 16:55–17:05 NY (pre-repair) |
| BRIEFING_EXEC EOD | `datetime.now(timezone.utc)` | Daily 21:00 UTC |
| TREND_V3_UM EOD | `datetime.now(timezone.utc)` or NY_CLOSE-15min | Daily 20:40 UTC (default) |
| RATCHET_FLAT_2040 | `datetime.now(timezone.utc)` | Daily 20:40 UTC |
| PRE_NEWS_CLOSE | `datetime.now(timezone.utc)` | 5-min pre HIGH event (default OFF) |
| NEWS_BLACKOUT_CLOSE | `is_news_blackout(datetime.now(timezone.utc))` | During blackout (`CLOSE_ON_BLACKOUT=0` in `.env`) |
| WEEKEND_SHUTDOWN | `time.monotonic()` deadline | Shutdown handler only, `CLOSE_POSITIONS_ON_SHUTDOWN=0` default |

Only NY_CLOSE is affected by Repair 4. All others use their own clocks
and mode filters and are not touched.

---

## 5. SESSION MODEL

* **FX session** (`_is_fx_session_closed`, autobot.py:1851–1866):
  broker-observed IG rolling-spot CFD hours. CLOSED: Sat all day, Fri
  ≥ 21 UTC, Sun < 20 UTC. OPEN otherwise. This helper is a UTC-clock
  predicate — it correctly identifies that Sun 20:55 UTC is a *live*
  FX session (returns False). Using it at the NY_CLOSE seam would NOT
  suppress the Sunday incident, because the incident happened during
  live-session hours from a broker perspective. So `_is_fx_session_
  closed` is *not* the right predicate here; it was investigated per
  operator §11 and correctly not used.
* **NY session** (implicit in the NY_CLOSE design): NY equity/FX
  session exists Mon-Fri NY-local. Sat/Sun have no NY session end.
  The predicate operator §5 asked for — "session identity dominates
  clock coincidence" — is `ny.weekday() in (0..4)`. That is the exact
  guard Repair 4 adds.

---

## 6. ALL TIMED CLOSE AUTHORITIES FOUND

Complete enumeration per operator §3, produced by grepping autobot.py
for `close_position` call sites and cross-referencing each with its
clock/mode gate. All rows are pre-repair state; Repair 4 modifies only
row 1's clock and mode filters.

| # | Authority | Applicable modes | Pairs | Clock | Weekday | Session gate | Caller | close_position path |
|---|---|---|---|---|---|---|---|---|
| 1 | **NY_CLOSE** | All non-BE, non-GBPUSD_TREND\* | All | NY 16:55–17:05 (`_ny_now`) | None (pre-repair) → Mon-Fri (post-repair) | None | `AutoBot._on_ls_tick`, autobot.py:4684 | `close_position(reason="NY_CLOSE", exit_hint_price=mid_f)` at :4699 |
| 2 | **BRIEFING_EXEC EOD** | `_is_briefing_exec_mode(mode)` (BRIEFING_EXECUTION, BRIEFING_PIA_FIRST, GBPUSD_TREND) | All | 21:00 UTC (`BRIEFING_EXEC_EOD_CLOSE_UTC`) | None | None | `_apply_briefing_exec_eod_close`, autobot.py:2610 | `close_position(reason="EOD_CLOSE", exit_hint_price=…)` at :2696 |
| 3 | **TREND_V3_UM EOD** | GBPUSD_TREND_V3_UM_L/S | GBPUSD | 20:40 UTC or NY_CLOSE-15min (`TREND_V3_UM_EOD_CLOSE_UTC`) | None | None | `_apply_trend_v3_um_eod_close`, autobot.py:2791 | `close_position(reason="TREND_V3_UM_EOD", exit_hint_price=…)` at :2862 |
| 4 | **RATCHET_FLAT_2040** | tiered-ratchet managed | Whatever ratchet-managed | 20:40 UTC (`RATCHET_FLAT_HHMM`) | None | None | `_apply_ratchet_eod_close`, autobot.py:2903 | `close_position(reason="RATCHET_FLAT_2040", exit_hint_price=…)` at :2989 |
| 5 | **PRE_NEWS_CLOSE** | All (per-position PnL check) | All | 5-min pre HIGH event | None | None | `AutoBot._on_ls_tick`, autobot.py:4788 (gated `PRE_NEWS_CLOSE_ENABLED`; default OFF) | `close_position(reason="PRE_NEWS_CLOSE", exit_hint_price=mid_f)` at :4818 |
| 6 | **NEWS_BLACKOUT_CLOSE** | All except LEVEL_BOUNCE + TREND_V3_UM | All | During blackout window | None | None | `AutoBot._on_ls_tick`, autobot.py:5325 (gated `CLOSE_ON_BLACKOUT`; `.env: CLOSE_ON_BLACKOUT=0`) | `close_position(reason="NEWS_BLACKOUT_CLOSE", exit_hint_price=mid_f)` at :5352 |
| 7 | **WEEKEND_SHUTDOWN** | All tracked | All | Shutdown deadline (bounded) | None | None | `_shutdown_close_positions`, autobot.py:9414 (gated `CLOSE_POSITIONS_ON_SHUTDOWN`; default OFF) | `close_position(reason="WEEKEND_SHUTDOWN")` at :9444 |

**Is fixing `_should_close_for_ny_end` alone sufficient?**

For the Sunday incident, yes — only row 1 fired at 20:55 UTC on Sun.
Rows 2–4 fire at ≥20:40 UTC daily; row 2 was skipped (ONE_STRATEGY is
not `_is_briefing_exec_mode`); row 3 was skipped (mode mismatch); row
4 was skipped (position not ratchet-managed). Row 5 was gated OFF (env
`PRE_NEWS_CLOSE_ENABLED=0`). Row 6 was gated OFF
(`CLOSE_ON_BLACKOUT=0`). Row 7 fires only during shutdown and is
gated OFF (`CLOSE_POSITIONS_ON_SHUTDOWN=0`).

**But** ONE_STRATEGY inheritance is a *separate* defect from Sunday-
identity. Fixing only the weekday guard would leave a live Mon-Fri
NY_CLOSE still capable of flattening ONE_STRATEGY runners against the
Repair 3 design intent. So Repair 4 addresses BOTH defects with two
independent gates in the same seam, mirroring the two-defence pattern
Repair 3 §6 used for the scale-out orphan.

---

## 7. ONE_STRATEGY TIMED CLOSE POLICY

Per Repair 3 (`one_strategy_management.py:1–38`, HEAD f70f8a7):
**"only authorised exit paths for ONE_STRATEGY are
one_strategy_management (thesis) and the broker mechanical SL."**
Broker TP (100p) and SL (12p) are mechanical and always retained.

Applied to the seven timed-close authorities above:

| # | Authority | ONE_STRATEGY policy (post-repair) | Enforcement site |
|---|---|---|---|
| 1 | NY_CLOSE | **EXEMPT** (Repair 4) | autobot.py:4707 skip block |
| 2 | BRIEFING_EXEC EOD | Never fires — `_is_briefing_exec_mode("ONE_STRATEGY")==False` (prefix set does not include it) | autobot.py:2673 filter |
| 3 | TREND_V3_UM EOD | Never fires — mode not in `("GBPUSD_TREND_V3_UM_L","GBPUSD_TREND_V3_UM_S")` | autobot.py:2839 filter |
| 4 | RATCHET_FLAT_2040 | Never fires — position not ratchet-managed | autobot.py:2955 filter (`_pk not in active_ratchet_keys`) |
| 5 | PRE_NEWS_CLOSE | Gate default OFF (`PRE_NEWS_CLOSE_ENABLED=0`); when enabled, applies per-position PnL rule — no ONE_STRATEGY carve-out yet, but currently inert | Not addressed by this repair (out of scope) |
| 6 | NEWS_BLACKOUT_CLOSE | Gate default OFF (`.env: CLOSE_ON_BLACKOUT=0`); when enabled, exempts only LEVEL_BOUNCE + TREND_V3_UM — no ONE_STRATEGY carve-out yet, but currently inert | Not addressed by this repair (out of scope) |
| 7 | WEEKEND_SHUTDOWN | Gate default OFF (`CLOSE_POSITIONS_ON_SHUTDOWN=0`); currently inert | Not addressed by this repair (out of scope) |

No new flattening policy invented. No existing design decision
authorises rows 5/6/7 to touch ONE_STRATEGY; they are currently inert
by env gate. If any is later enabled, the same class of defect will
need the analogous ONE_STRATEGY carve-out at that seam — flagged for
a future ticket but explicitly out of Repair 4 scope per operator §6.

---

## 8. BRIEFING_EXECUTION POLICY PRESERVED

**YES — untouched by Repair 4.** Per operator §7:

* `_BE_SKIP_NY_CLOSE` env `BRIEFING_EXEC_SKIP_NY_CLOSE=1` still routes
  BE modes to their own 21:00 UTC EOD close.
* `_is_briefing_exec_mode` prefix set unchanged
  (`BRIEFING_EXECUTION`, `BRIEFING_PIA_FIRST`, `GBPUSD_TREND`).
* `_apply_briefing_exec_eod_close` (autobot.py:2610) untouched.
* `_apply_briefing_exec_ny_evaluation` (12:30 UTC plan eval)
  untouched.

The Repair-4 ONE_STRATEGY skip at :4707 sits **after** the BE skip so
the BE branch continues to trip first for BE modes and never falls
through to the new block. Asserted by
`TestBriefingEodPreserved.test_briefing_skip_ny_close_flag_still_default_on`
and `TestOneStrategyExemptedAtDispatch.test_briefing_exemption_still_present`.

144 workstream and BE crash-loop recovery: **untouched**.

---

## 9. V2_PICK_BOUNCE POLICY

**Unchanged by Repair 4** (operator §8).

Applicable timed closes for a V2_PICK_BOUNCE position, pre and post
Repair 4:

* **NY_CLOSE** — applies Mon-Fri NY 16:55–17:05 (was: daily; now:
  Mon-Fri). Sunday incident *would have* also affected V2_PICK_BOUNCE
  positions had one been open at the Sunday reopen — Repair 4's
  weekday guard equally protects V2 from the Sunday defect.
* **PRE_NEWS_CLOSE**, **NEWS_BLACKOUT_CLOSE**, **WEEKEND_SHUTDOWN** —
  same env-gate state as any other mode (currently inert per §7).
* **BRIEFING_EXEC EOD / TREND_V3_UM EOD / RATCHET_FLAT_2040** —
  never fire on V2_PICK_BOUNCE (mode filters exclude).

Asserted by `TestV2PickBounceUnchanged`
(v2 still in firewall allowlist; no v2-specific branch added at NY_CLOSE
dispatch). The separate confidence-12 V2 Picks forensic is deferred per
operator §8.

---

## 10. SUNDAY BEFORE

**Predicate returned `True`.** Trace at incident timestamp:

```
utc               = 2026-09-27T20:55:03Z
NY_CLOSE_ENABLED  = True
ny                = 2026-09-27 16:55:03 EDT (weekday=6 Sunday)
window            = 16:55:00 EDT ≤ 16:55:03 EDT < 17:05:00 EDT  → INSIDE
today_key         = "2026-09-27"
dedup             = last_done_date_by_epic.get(EPIC) != "2026-09-27" → FRESH
return True
→ close_position(reason="NY_CLOSE") → -7p at 20:55:08 UTC
```

## 11. SUNDAY AFTER

**Predicate returns `False`.** Trace with Repair 4 applied:

```
utc               = 2026-09-27T20:55:03Z
NY_CLOSE_ENABLED  = True
ny                = 2026-09-27 16:55:03 EDT (weekday=6 Sunday)
window            = INSIDE
weekday guard     = ny.weekday()==6 >= 5 → SUPPRESS
log (once/day)    = "[NY_CLOSE] suppressed epic=CS.D.GBPUSD.TODAY.IP
                     ny_local=2026-09-27 16:55 EDT weekday=6
                     utc=2026-09-27T20:55:03.…Z
                     reason=NY_CLOSE_NOT_APPLICABLE_SUNDAY_REOPEN"
return False
→ NY_CLOSE dispatch skipped entirely
→ position subject to ONE_STRATEGY thesis-invalidation (Repair 3)
  + broker mechanical SL/TP only.
```

Proven by `TestSundayIncidentCounterfactual.test_incident_clock_no_longer_triggers`
and `TestInvariant_01_SundayReopenNoNyClose` (5 sub-tests including
end-of-window edge, dedup, log emission, Saturday).

## 12. FRIDAY BEFORE

Friday 2026-09-25 16:55:03 EDT (weekday=4) → predicate returned `True`;
dispatch closed every non-BE position at NY_CLOSE (verified in
close_intent.jsonl: `DIAAAAYHQRXWWB3` 2026-09-22T20:55:01Z was the
prior Tuesday's NY_CLOSE — proves the daily cadence pre-repair).

## 13. FRIDAY AFTER

**Predicate still returns `True`.** Trace:

```
utc               = 2026-09-25T20:55:03Z
NY_CLOSE_ENABLED  = True
ny                = 2026-09-25 16:55:03 EDT (weekday=4 Friday)
window            = INSIDE
weekday guard     = ny.weekday()==4 < 5 → PASS
today_key         = "2026-09-25"
dedup             = FRESH
return True
→ NY_CLOSE dispatch fires. BE modes skipped. ONE_STRATEGY skipped
  (Repair 4 dispatch exemption). All other non-BE, non-ONE_STRATEGY
  modes closed with reason=NY_CLOSE.
```

Proven by `TestInvariant_02_FridayNyCloseStillFires`.

Legitimate Friday weekly-close protection is intact.

## 14. MON-THU BEHAVIOUR CHANGED: YES/NO

**No — behaviour unchanged** for the predicate itself (Mon-Thu 16:55
NY still fires). Proven by `TestInvariant_03_MonThuUnchanged`
(parametrised Mon/Tue/Wed + explicit Thu).

The only weekday-facing change is at the **dispatch site**:
ONE_STRATEGY positions are skipped on any weekday NY_CLOSE fire (they
now ride to Stage-12 thesis-invalidation + broker mechanical SL/TP,
per Repair 3 intent). Every other mode is closed exactly as before.
Proven by source-level assertion `TestOneStrategyExemptedAtDispatch`.

---

## 15. REPAIR 1 INTACT

**YES.** `trade_executor._EXEC_AUTH_ALLOWED_FAMILIES` still equals
`{"ONE_STRATEGY", "BRIEFING_EXECUTION", "V2_PICK_BOUNCE"}` — asserted
by `TestRepair1Intact`. Full `test_execution_authority_firewall.py`
suite still passes (77/77).

## 16. REPAIR 2 INTACT

**YES.** `interaction_resolution.OWNERSHIP_REJECT_PREDATES`,
`OWNERSHIP_REJECT_POSTDATES`, `OWNERSHIP_REJECT_MISSING_TS` unchanged;
`_ownership_enabled()` default-True; `continuation_evidence._DEFAULT_
FRESHNESS_SECONDS` present and >0. Asserted by `TestRepair2Intact`.
Full `test_stage8_ownership_freshness_repair.py` suite still passes
(15/15).

## 17. REPAIR 3 INTACT

**YES.** `one_strategy_management.manage_one_strategy_position` still
wired at `autobot._on_5m_close_log` (source-level check via
`inspect.getsource(autobot)`); `EXIT_DIRECTION_FAILED` close-reason
still present. Repair 4's `_should_close_for_ny_end` intentionally
contains no ONE_STRATEGY branch (weekday guard is mode-generic) and
no `EXIT_DIRECTION_FAILED` reference — asserted by
`TestRepair3Intact.test_repair4_does_not_intercept_exit_direction_failed`.
Management close and timed-session close remain distinguishable in
telemetry (different reason strings: `EXIT_DIRECTION_FAILED:*` vs
`NY_CLOSE`). Full `test_one_strategy_management_thesis_repair.py` suite
still passes (28/28).

## 18. PRODUCTION RESTARTED

**NO.**

## 19. .env MODIFIED

**NO.** Repair 4 adds no new env keys. All new behaviour defaults ON
(the NY-weekday guard is unconditional; the ONE_STRATEGY dispatch
skip is unconditional). Existing `NY_CLOSE_ENABLED=1` kill switch
still cuts the whole predicate.

## 20. REAL BROKER CALL

**NO.** Tests exercise `_should_close_for_ny_end` as a pure function
via `monkeypatch.setattr(autobot, "_ny_now", …)`. Dispatch-site
assertions are source-level (`inspect.getsource`), no `close_position`
invocation.

---

## 21. FILES CHANGED

| File | Purpose | Lines |
|---|---|---|
| `autobot.py` | (1) Import `field` from dataclasses. (2) `NYCloseState` gains `last_suppress_logged_by_epic: Dict[str, str] = field(default_factory=dict)` for per-epic dedup of suppression logs. (3) `_should_close_for_ny_end` gains NY-weekday guard (Sat/Sun return False) with dedup log emitting `reason=NY_CLOSE_NOT_APPLICABLE_SUNDAY_REOPEN\|SATURDAY`. (4) NY_CLOSE dispatch site (:4707) gains ONE_STRATEGY skip block mirroring the BRIEFING_EXEC skip pattern above it. | +49 |
| `tests/unit/test_ny_close_session_repair.py` (new) | 34 focused invariant tests: Sunday reopen (5) + Friday still-fires (2) + Mon-Thu unchanged (4) + outside-window (2) + kill-switch (1) + DST boundary (2) + Sunday incident counterfactual (1) + ONE_STRATEGY exemption at dispatch (2) + BRIEFING preserved (3) + Repair 1/2/3 intact (6) + V2_PICK_BOUNCE unchanged (2) + broker SL/TP unaffected (2) + observability (2). | +376 |
| `.gitignore` | Allowlist the new test file. | +1 |

**Not touched:**

* All entry logic (Stage 5–10 pipeline, sensors, NMS, HTF, LOI, QM_V2)
* `one_strategy_management.py` (Repair 3 — frozen)
* `interaction_resolution.py`, `continuation_evidence.py`,
  `demonstrated_direction.py` (Repair 2 — frozen)
* `trade_executor.py` execution-firewall block (Repair 1 — frozen)
* `_ny_now`, `_is_fx_session_closed`, `_is_weekend_gap`,
  `_is_weekend_utc` helpers (investigated per §11; not the right
  predicate for this seam)
* `_apply_briefing_exec_eod_close` (BRIEFING EOD — operator §7)
* `_apply_trend_v3_um_eod_close`, `_apply_ratchet_eod_close`
* `_amend_broker_sl`, `_apply_software_break_even` (broker SL/TP
  path — asserted unaffected by `TestBrokerSlTpUnaffected`)
* `PRE_NEWS_CLOSE`, `NEWS_BLACKOUT_CLOSE`, `WEEKEND_SHUTDOWN`
  (all env-gated OFF; carve-outs deferred per §7)
* V2_PICK_BOUNCE (operator §8), 144 workstream (operator §7), EURUSD
  architecture, day types, news strategy calculations, .env

---

## 22. HARD BLOCKERS

**None encountered.**

* NY_CLOSE intended semantics established from code — daily NY-session
  flatten Mon-Fri (with BE exempted). No contradictory session clocks.
* Sunday reopen semantics reconciled: `_is_fx_session_closed`
  correctly identifies Sun 20:55 UTC as live-session (open), so it
  isn't the right predicate at this seam; the correct predicate is
  `ny.weekday() in (0..4)` computed from `_ny_now()` (DST-safe).
* Fixing Sunday did NOT require changing BRIEFING_EXECUTION behaviour.
* Fixing Sunday did NOT require weakening Repair 1/2/3.
* Friday behaviour preserved (weekday guard passes for Fri; dispatch
  still closes non-BE, non-ONE_STRATEGY positions).
* No real broker call.

---

## 23. FOCUSED PROOF

**`tests/unit/test_ny_close_session_repair.py` — 34/34 pass:**

```
TestInvariant_01_SundayReopenNoNyClose (×5) ................................. PASSED
TestInvariant_02_FridayNyCloseStillFires (×2) ............................... PASSED
TestInvariant_03_MonThuUnchanged (×4, parametrised) ......................... PASSED
TestInvariant_04_OutsideWindow (×2) ......................................... PASSED
TestInvariant_05_KillSwitch (×1) ............................................ PASSED
TestInvariant_06_DstBoundary (×2) ........................................... PASSED
TestSundayIncidentCounterfactual (×1) ....................................... PASSED
TestOneStrategyExemptedAtDispatch (×2) ...................................... PASSED
TestBriefingEodPreserved (×3) ............................................... PASSED
TestRepair1Intact (×1) ...................................................... PASSED
TestRepair2Intact (×2) ...................................................... PASSED
TestRepair3Intact (×3) ...................................................... PASSED
TestV2PickBounceUnchanged (×2) .............................................. PASSED
TestBrokerSlTpUnaffected (×2) ............................................... PASSED
TestObservability (×2) ...................................................... PASSED
==================== 34 passed in 1.71s ====================
```

**Regression across Repair 1/2/3/4 suites — 154/154 pass:**

```
test_execution_authority_firewall.py:            77 pass  (Repair 1)
test_stage8_ownership_freshness_repair.py:       15 pass  (Repair 2)
test_one_strategy_management_thesis_repair.py:   28 pass  (Repair 3)
test_ny_close_session_repair.py:                 34 pass  (Repair 4)
------------------------------------------------
Total: 154 pass
```

**Supporting suites (Stage 12 hold, Stage 10 one_strategy, autobot import) — 83/83 pass:**

```
test_stage12_hold_management.py:                 20 pass
test_stage10_one_strategy.py:                    43 pass
test_autobot.py:                                 20 pass
------------------------------------------------
Total: 83 pass
```

---

## 24. WHAT THIS REPAIR DOES NOT DO

* Does not touch V2_PICK_BOUNCE strategy logic (operator §8; separate
  active forensic on contradictory confidence-12 V2 Picks is deferred).
* Does not change BRIEFING_EXECUTION EOD semantics (operator §7).
* Does not touch the 144 / crash-loop-recovery workstream (operator §7).
* Does not weaken Repair 1's execution-authority firewall.
* Does not weaken Repair 2's current-interaction ownership /
  evidence freshness.
* Does not weaken Repair 3's ONE_STRATEGY thesis-invalidation.
* Does not introduce a minimum-hold timer or five-second grace (operator
  §14). Broker SL and emergency exits remain capable of closing
  immediately. Session identity dominates clock coincidence — that is
  the invariant, not an arbitrary age gate.
* Does not add ONE_STRATEGY carve-outs to PRE_NEWS_CLOSE,
  NEWS_BLACKOUT_CLOSE, or WEEKEND_SHUTDOWN (all env-gated OFF; flagged
  as future tickets in §7 if any is later enabled).
* Does not require a service restart, `.env` change, or real broker
  call.
* Does not change entry logic, Stage 5–10 pipeline, Stage 9 freshness,
  NMS, ONE_STRATEGY thesis-invalidation definition, V2 thresholds, V2
  confidence, V2 arming, SL/TP distances, BRIEFING strategy, EURUSD
  architecture, day types, or news strategy calculations (operator §19).

---

## 25. COMMIT

`709ea9d0971c75d9c068feba9769b45d295f2256` — "feat(session): NY_CLOSE
weekday guard + ONE_STRATEGY exemption (Repair 4)"

Branch: `feat/trend-stretch-brake-adx-floor`.

Diff summary (autobot.py, +49 lines):

```
--- a/autobot.py
+++ b/autobot.py
@@ import from dataclasses:  dataclass, field
@@ NYCloseState (line 2589+):
     +  last_suppress_logged_by_epic: Dict[str, str] = field(default_factory=dict)
@@ _should_close_for_ny_end (line 3379+):
     +  NY-weekday guard (weekday >= 5 → return False, dedup-log once/epic/day)
     +  reason=NY_CLOSE_NOT_APPLICABLE_SUNDAY_REOPEN | _SATURDAY
@@ NY_CLOSE dispatch site (line 4707+):
     +  if _ny_mode == "ONE_STRATEGY": continue (with info log)
```

Repair chain now:

* Repair 1 — `bcd245286c…` execution-authority firewall
* Repair 2 — `477bd4582c…` current-interaction ownership + freshness
* Repair 3 — `f70f8a7e1b…` ONE_STRATEGY thesis management
* Repair 4 — `709ea9d097…` NY_CLOSE session-identity + ONE_STRATEGY exemption

