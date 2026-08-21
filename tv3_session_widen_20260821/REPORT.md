# TREND_V3 session-gate widen — 2026-08-21 (TIER 1)

**Change:** extend `TREND_V3_SESSION_END_UTC` from 16:00 to 20:00 via .env
override. Only touches the entries-only session gate at
`gbpusd_trend_v3.py:1116-1121`. `monitor_exits` / management of open
positions untouched.

**Consumer sweep — nothing else assumes the 16:00 bound.**

```
$ grep -rnE "TREND_V3_SESSION|TV3_SESSION" /opt/tradingbot/*.py
gbpusd_trend_v3.py:147:SESSION_GATE_ENABLED = _env_bool("TREND_V3_SESSION_GATE_ENABLED", "1")
gbpusd_trend_v3.py:148:SESSION_START        = _env_hhmm("TREND_V3_SESSION_START_UTC", "07:00")
gbpusd_trend_v3.py:149:SESSION_END          = _env_hhmm("TREND_V3_SESSION_END_UTC",   "16:00")
gbpusd_trend_v3.py:1118:                "[TV3_SESSION] suppressed entry at %s",
```

Downstream machinery that could conceivably assume 16:00 — verified
independent:

* **20:40 UM flatten** — `autobot._resolve_trend_v3_um_eod_close_utc`
  (autobot.py:2166-2196) resolves the UM EOD flatten as
  `NY_CLOSE_HHMM − 15 min` (NY_CLOSE default 16:55 America/New_York =
  20:40 UTC during EDT / 21:40 during EST). No reference to
  `TREND_V3_SESSION_END_UTC`. The env override
  `TREND_V3_UM_EOD_CLOSE_UTC` (unset in current `.env`) is the only
  knob for the flatten time.
* **NY_CLOSE machinery** — `autobot.py:208-210`
  `NY_CLOSE_HHMM=16:55` (America/New_York); the actual UTC firing time
  is derived at each tick via zoneinfo. Independent of session gate.

The 20:00 widen therefore leaves the 20:40 UM flatten and the NY_CLOSE
flatten with a positive gap (20:40 UM sweep ≥ 40 min after the last
admissible TREND_V3 entry). No new race.

## Retro pricing — 16:00-20:00 UTC band (2026-03-30 → 2026-08-21)

**Cohort:** 11 runs, magnitude 673.8 p, banked 0.0 p.
Source: `reports-public/daystruct_20260821/section5_runs.jsonl`.

| date | wd | start | dir | mag | day_class | label | drought category |
|:---|:--:|:--:|:--:|--:|:---|:---|:---|
| 2026-03-31 | Tue | 17:15 | up |  63.3 | MULTI_DAY  | AMBIGUOUS    | NO_EVAL[GBPUSD_dark] |
| 2026-04-01 | Wed | 17:00 | dn |  45.8 | MULTI_DAY  | BOUNCE       | NO_SIGNAL[criteria_not_met_preTelem] |
| 2026-04-12 | Sun | 19:20 | dn |  73.0 | GRIND_DAY  | AMBIGUOUS    | NO_SIGNAL[criteria_not_met_preTelem] |
| 2026-04-19 | Sun | 19:30 | dn |  40.2 | BOUNCE_DAY | AMBIGUOUS    | NO_EVAL[process_dark] |
| 2026-04-21 | Tue | 17:15 | up |  42.0 | MULTI_DAY  | BOUNCE       | NO_SIGNAL[criteria_not_met_preTelem] |
| 2026-05-18 | Mon | 16:10 | dn |  42.7 | MULTI_DAY  | BOUNCE       | NO_SIGNAL[criteria_not_met_preTelem] |
| 2026-06-10 | Wed | 18:00 | dn |  45.4 | BOUNCE_DAY | BOUNCE       | NO_SIGNAL[criteria_not_met] |
| 2026-06-11 | Thu | 17:20 | up |  72.8 | MULTI_DAY  | BOUNCE       | NO_SIGNAL[criteria_not_met] |
| 2026-06-11 | Thu | 18:00 | up |  45.4 | MULTI_DAY  | AMBIGUOUS    | NO_SIGNAL[criteria_not_met] |
| 2026-06-17 | Wed | 18:40 | dn | 101.1 | GRIND_DAY  | CONTINUATION | NO_SIGNAL[criteria_not_met] |
| 2026-07-29 | Wed | 16:35 | up | 102.1 | GRIND_DAY  | AMBIGUOUS    | NO_SIGNAL[armed_wrong_dir] |

**Direct-attribution to the session gate:** 1 run (2026-07-29 16:35 up,
102.1 p). The parent drought report §c/1 named this specifically — trend_v3
telemetry from 15:00-15:40 shows `regime_not_strong_up` blocks; from
16:00 onward the telemetry has zero trend_v3 records because the
16:00 gate suppressed evaluation entirely. Under the widen, those bars
would emit block/eval events; the run would be *evaluable*, not
guaranteed to fire (regime criterion would still apply).

**The other 10 runs are gate-independent** — they classify as
`criteria_not_met` or `criteria_not_met_preTelem` in the drought
audit; the 16:00 gate was orthogonal to their non-firing. The widen
does not "unblock" them.

### Criteria walks (post-telemetry runs)

`trend_v3.jsonl` first record is 2026-06-30. Only the 2026-07-29 16:35
run in this band has a post-telemetry criteria walk. Raw
`trend_v3.jsonl` for 2026-07-29 15:00-15:40:

```
2026-07-29 15:00:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:05:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:10:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:15:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:20:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:25:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:30:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:35:00+00:00 event=block reason=regime_not_strong_up
2026-07-29 15:40:00+00:00 event=block reason=regime_not_strong_up
```

After 15:40, zero records through 20:00 (session gate suppressed all
evaluation). Under the widen, trend_v3 would continue emitting per-bar
block records; if regime turned STRONG_TREND_UP after 16:35, TREND_V3_L
could have armed. Whether it would have banked the 102.1p is
unverifiable from this side of the gate — the criteria walk simply
gains 40 more bars of eval.

Pre-2026-06-30 runs (7 of 11) have no strategy-tier telemetry —
classification stays UNKNOWN[pre-telem] for what would have fired
under the widen.

### Bad-late-entry saves — the counterfactual

TREND_V3 LIVE fires with `timestamp_open.hour ∈ [16, 20)`:

* **Pre-gate era (before 2026-07-21 18:05 UTC):** 8 fires, all on
  2026-07-06 (n=4) and 2026-07-15 (n=4).
  * Outcomes: 4× TP1 (`+10.45 / -1.9 / +10.45 / -5.6` on 07-06;
    `+15.85 / +3.6 / +10.45 / -24.15` on 07-15).
  * Net pnl across all 8: **+19.1 p** (rough sum; two big TPs
    balance a -24 SL and a -5.6 IG reconcile).
  * No clear "the gate saved us from disaster" pattern — the sample
    is small and mixed.
* **Post-gate era (2026-07-21 onward):** 0 fires 16-20h. Gate was
  in effect and held.

TREND_V3 fires 15:00-16:00 (the last hour of the pre-widen window,
so a proxy for "late but currently admissible"): 2 fires total
(`2026-07-20T15:15 TREND_V3_S SL -11.95` + one +TP1) — net **+4.2 p**.
Also small sample, also mixed.

**No structural bad-late-entry pattern jumps out.** The retro data
neither strongly endorses nor strongly refutes the widen; it's a
"we don't know yet, and we can't know without letting the gate
open" answer. The widen adds evaluation opportunity to a band that
historically has 0 banked / 674 p missed; the recovery upside is
capped by regime/ER/other TREND_V3 criteria that still need to fire.

### Bound on widen upside

Applying the trend-family capture ratio from the daystruct audit
(0.324 = 547.6 banked / 1688.5 offered on trend-family runs):

* If ALL 11 runs were TREND_V3-eligible AND fired at family-average
  capture: `673.8 × 0.324 = 218.3 p` upper-bound recovery.
* If ONLY the 2026-07-29 direct-attribution run captured at family
  average: `102.1 × 0.324 = 33.1 p`.
* Realistic ceiling for Monday: somewhere between these — most other
  band runs classify as `criteria_not_met`, so TREND_V3 would emit
  block records, not fires.

**These are bounds, not forecasts.** The widen is a gate widen, not
a criteria relaxation.

## Files touched

* `.env` — added `TREND_V3_SESSION_END_UTC=20:00` (live host only; not
  committed per RUNBOOK §3)
* `.env.example` — template block committed with the new default
* `tests/unit/test_trend_v3_session_gate_widen.py` — 7 assertions;
  17:30 admits, 20:30 refuses, 20:00 exact refuses, 19:55 admits,
  Saturday refuses, pre-widen 16:00 semantics preserved,
  kill-switch works

## Activation

Rides the next `autobot.service` restart (LADDER activation restart
was 2026-08-21 23:35:35; the widen is added to `.env` at 2026-08-21
23:42Z, needs one more restart to go live). Boot proofs will show
both `LADDER_ENABLED=1` + `TREND_V3_SESSION_END_UTC=20:00` in
`/proc/<pid>/environ` from the same restart.
