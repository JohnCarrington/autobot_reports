# NEWS_STRATEGY build spec (2026-07-25)

Author: telemetry-first pass following STEP 0 inventory + STEP 1 telemetry
build (`news_strategy._snapshot_news_telemetry` +
`logs/news_strategy_evals.jsonl`).

## Evidence base — honest sample-size disclosure

- 13 NEWS_STRATEGY* fills in `logs/signal_log.jsonl`, 2026-04-06 → 2026-07-22.
- Distribution: NEWS_STRATEGY_CONT n=7 (net +77.1p, mean +11.0p, 5W/2L);
  NEWS_STRATEGY_FADE n=3 (net -22.0p, mean -7.3p, 1W/2L);
  NEWS_STRATEGY_REVERSAL n=1 (+17.6p, single-fire); legacy NEWS_STRATEGY n=2
  (one closed +5.2p, one open at cutoff).
- The strategy was **OFF** from the 07-23 env overwrite until 07-24; it
  fired **once** in the Mon-Wed window (2026-07-22 REVERSAL, before the
  overwrite). The post-restore Mon-Wed sample carries **zero** fills.
- Non-fill decision volume in `logs/news_strategy_observed.jsonl`: 1621 rows;
  SKIP_NO_ACTUALS dominates (1454). FIRE rows carry rich context (spike_dir,
  spike_extreme, anchor, since_spike, actuals dict, cons_low/high,
  spike_size_pips) that never reached `signal_log` — the STEP 1 telemetry
  now bridges that.

**Read**: the calibration corpus is too thin to evidence rates/thresholds
per event type or per leg with statistical weight. Most numbers below are
therefore ASSUMED and calibrated only after the new eval-log accumulates.

## 1. Triggers

### 1.1 Arming (IDLE → ARMED)
- Fire when a HIGH-impact event whose currency affects `symbol` sits inside
  ±`_PRE_NEWS_WINDOW_SECS=300s` of `now`.
- **EVIDENCED** by the existing implementation (`_arming_event_for`,
  news_strategy.py:547) with 1454+ SKIP_NO_ACTUALS observations proving the
  ARMED → poll path runs end-to-end.
- Sizing / gate on `impact != "high"`: EVIDENCED (upstream filter, existing
  behaviour).

### 1.2 Spike detection
Range OR directional (news_strategy.py:692-693, verbatim):
```
range_fired = range_pips >= NEWS_SPIKE_RANGE_PIPS       # 15p default
directional_fired = abs(directional_pips) >= NEWS_SPIKE_DIRECTIONAL_PIPS  # 10p
```
- **ASSUMED**: 15p / 10p as-set. No calibration corpus large enough to
  validate. New telemetry field `pre_release_range_pips` will let us
  compare quiet pre-release ranges to post-release spike magnitude and
  right-size the trigger.
- **EVIDENCED**: `_SPIKE_DIR_LOCK_PIPS=5.0` chronological-first crossing —
  survives all 13 fills without a direction-flip bug reported.

### 1.3 Leg assignment (actuals → FADE / CONT / REVERSAL)
`|dev| > 5%` → CONT via NEWS_TICK; `|dev| ≤ 5%` → FADE via NEWS_STRATEGY.
- **PARTIALLY EVIDENCED**: 7/13 fills are CONT (5W/2L, +77.1p net); the
  CONT partition earns its slot. FADE 1W/2L (-22.0p net) — n=3 is not
  enough to condemn but it is the leg that lost money.
- **ASSUMED**: 5% deviation cutoff. Field to instrument:
  `surprise_deviation` now stamped on every eval — needed to falsify or
  refine the cutoff. Recommend the operator hold the cutoff until we have
  ≥20 additional post-restore fires per leg.

### 1.4 REVERSAL_WATCH
Two triggers on 5m bar close post-cons (news_strategy.py:1414-1425): SWEEP_RECLAIM,
RANGE_BREAK. Fires against `spike_dir`. Floor 40 min, ceiling 90 min.
- **ASSUMED**: floor 40 min. Only 1 REVERSAL fill (+17.6p), can't
  discriminate. Instrument
  `REVERSAL_WOULD_FIRE_EARLY` (already logged) — count fires in
  [30, 40) min vs [40, 60] min via the new eval-log and adjust the floor
  by outcome later.

## 2. Gates

### 2.1 NEWS_RELEASE_WINDOW blackout
Gate on `is_in_release_window(now)` for FADE only (autobot.py:3337). CONT +
REVERSAL bypass by design.
- **EVIDENCED**: intentional per code comment
  ("NEWS_STRATEGY_CONT — +34.6p winning leg — bypasses"). 07-22 REVERSAL
  fire (+17.6p) confirms REVERSAL-bypass matters at least once.

### 2.2 Position-conflict rule
No new NEWS_STRATEGY* fire when an active NEWS_STRATEGY_* position exists
on the epic (autobot.py:3304-3307 + news_strategy._news_position_open at
line 452).
- **EVIDENCED**: 1 REVERSAL_WOULD_FIRE_POSITION_OPEN row exists in the
  observed-log; the rule fired at least once and preserved capital.

### 2.3 Pair allowlist
`NEWS_STRATEGY_PAIRS` env; empty = all pairs. Currently empty.
- **ASSUMED**: all pairs. GBPUSD dominates the fill sample (13/13 are
  GBPUSD). Recommendation: gate on GBPUSD-only until per-pair spike
  behaviour is measured (new `pre_release_range_pips` + `spike_magnitude_pips`
  by pair from the eval-log answers this).

## 3. Entry geometry

### 3.1 FADE
Fire on break AGAINST spike by `NEWS_BREAK_PIPS=1.5` past the exclude-30s
cons envelope. Entry at `cur_mid`. SL at cons_water_mark + 5p buffer
(clamped `NEWS_FADE_MAX_SL_PIPS=25`). TP = 100% mirror of spike (clamped
`NEWS_FADE_MAX_TP_PIPS=50`).
- **PARTIALLY EVIDENCED**: geometry documented, ran on 3 fills. Losers
  (-10.6p, -12.9p) both closed via REGIME_MAX_HOLD / STRUCTURE_EXIT before
  either SL or TP; suggests exit orchestration, not entry geometry, dictated
  the losses. `entry_side_vs_spike=fade` + `spike_magnitude_pips` on the
  new eval-log will let us test whether fade-legs of ≥15p spikes fare
  worse than smaller spikes — the current single loser sits at
  `spike_magnitude_pips ≈ 22p` (from observed-log).

### 3.2 CONT
Break WITH spike; SL/TP from per-event `CONTINUATION_MAGNITUDE` table
(range 12/50 for rate decisions). Runner-trail TP extension when
`NEWS_STRATEGY_CONT_RUNNER_TRAIL_ENABLED=1`.
- **EVIDENCED**: 5/7 CONT fills won, mean +11.0p including one +34.35p
  (2026-06-05 rate decision) and one +17.75p (2026-07-02). Runner-trail
  has fired 3 times (per observed-log).

### 3.3 REVERSAL
Entry at `cur_mid` on trigger bar close. SL = `spike_extreme ± NEWS_REVERSAL_SL_BUFFER_PIPS(3)`
clamped to fade caps. TP = anchor clamped to fade caps.
- **ASSUMED**: n=1 (+17.6p, closed via BE_STOP_POST_SCALEOUT). Insufficient
  to validate. Needs the eval-log to count REVERSAL_WATCH_EXPIRED vs
  REVERSAL_FIRE per week.

## 4. Sizing

Currently uses the global position-sizing pathway (not covered here).
- **ASSUMED**: same size as other strategies. Because CONT/FADE win-rate
  and per-trade outcome differ (CONT +11.0p mean, FADE -7.3p mean), a
  legged size split is defensible but requires the new
  `entry_side_vs_spike` field to instrument.

## 5. Exits

Current exits are strategy-agnostic (`REGIME_MAX_HOLD`, `STRUCTURE_EXIT`,
`SL/TP hit`, `BE_STOP_POST_SCALEOUT`). Observed close_reasons on the 13
fills: 5× REGIME_MAX_HOLD, 2× TP hit, 1× SL hit, 1× STRUCTURE_EXIT,
1× PRE_NEWS_CLOSE, 1× External/manual, 1× BE_STOP_POST_SCALEOUT, 1× open.
- **NOT EVIDENCED (observation-only)**: REGIME_MAX_HOLD closing 5 of 13
  fills means the exit is being driven by a non-news mechanism on ~40% of
  news trades. Whether that helps or hurts is unclear at n=5. The eval-log
  now stamps `seconds_from_release`, `since_spike_secs`, and
  `entry_side_vs_spike` so we can join `signal_log.close_reason` and see
  whether REGIME_MAX_HOLD closes disproportionately hit FADE vs CONT and
  at what time-from-release.

## 6. Telemetry needed vs telemetry now stamped

| Field | Spec role | Now stamped |
|-------|-----------|-------------|
| `release_key` (`{name}|{epoch}`) | Join key across fills / evals | ✔ |
| `release_name` | Human-readable event | ✔ |
| `release_currency` | Pair-side polarity | ✔ |
| `scheduled_time_iso` | Absolute release time | ✔ |
| `seconds_from_release` | Trigger latency | ✔ |
| `surprise_direction` | CONT/FADE partition | ✔ |
| `surprise_deviation` / `beat_miss` | 5%-cutoff falsification | ✔ |
| `surprise_actual` / `forecast` | Deep audit | ✔ |
| `pre_release_range_pips` | Quiet-tape baseline | ✔ |
| `spike_magnitude_pips` | Spike size vs entry outcome | ✔ |
| `spike_direction` | Fade/follow direction check | ✔ |
| `entry_side_vs_spike` | Leg semantic in one field | ✔ |
| `atr_at_trigger_pips` | Vol context (5m rolling range proxy) | ✔ (`atr_at_trigger_source=range_5m_pips_proxy`) |
| `phase`, `leg`, `kind`, `signal`, `decision_reason` | Full decision context | ✔ |

All fields land in `news_telemetry` on FIRE/WOULD_FIRE/REVERSAL_FIRE
`signal_log` records AND in `logs/news_strategy_evals.jsonl` on every
decline / phase-transition / fire path.

## 7. Recommended next-step operator actions (informed, not committed)

1. Run for ~4 weeks with `NEWS_STRATEGY_ENABLED=1` (unchanged) and
   let `news_strategy_evals.jsonl` accumulate. Target ≥20 CONT + ≥20
   FADE + ≥5 REVERSAL fires before revising any parameter.
2. First calibration target once corpus grows: the FADE partition. It
   has lost money on n=3; the eval-log lets us test whether FADE loses
   preferentially at `spike_magnitude_pips ≥ 20` — if so, cap FADE to
   smaller spikes.
3. Second calibration target: REVERSAL_MIN_MIN floor of 40. The
   `REVERSAL_WOULD_FIRE_EARLY` kind is already logged (early band 30–40
   min); a month of data will show whether the [30, 40) window carries
   real signal or noise.

## 8. Assumptions unresolved by this doc

- What "surprise direction" means for events with `direction_hint`
  categorical variants beyond CONTINUATION / REVERSAL / IN_LINE — the
  current te_calendar mapping was not enumerated here.
- Whether `atr_at_trigger` should be tick-derived (as this build does) or
  bar-derived from `df_5m`. The tick-derived 5m-range proxy is what's
  cheaply available at tick-level; bar-derived ATR would require a
  df_5m hand-off from autobot's dispatcher and adds coupling. Leaving as
  proxy, labelled honestly via `atr_at_trigger_source`.
- Per-event overrides for FADE (currently empty per `news_strategy.py:290-302`
  comment) — populate only after the calibrated corpus arrives.
