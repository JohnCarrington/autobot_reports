# Cascade accuracy — predicted-vs-actual join (2026-05-12)

Diagnostic only. Source: `scripts/cascade_outcome_join.py` run with defaults
(--since 2026-04-12, --until 2026-05-12) at 2026-05-12 18:30Z. Output CSV at
`/tmp/cascade_join_30d.csv` (302 rows). Motivating question: is the Phase 4B
`CandleRegimeClassifier` cascade label accurate enough to gate trades for the
2026-05-19 regime-gate 2-week review (see
`docs/regime_classifier_status_2026-05-12.md` Section 8 and memory item
`project_regime_gate_2week_review.md`)?

---

## 1. Method

### What the script does

For each line in `logs/signal_log.jsonl` between `--since` and `--until`:

1. **Filter non-executed outcomes.** Trades with `outcome ∈ {None,
   PHANTOM_NEVER_EXECUTED}` never reached the market and are dropped. Trades
   with `outcome ∈ {IG_RECONCILE, MANUAL, …}` are retained but flagged
   downstream — see confounds below.
2. **Resolve the cascade label.** Two-step lookup:
   - Primary: read `cascade_stable_at_fire` straight from the signal_log row.
     This field was added to `signal_logger.py` in commit `39bb4bb` (2026-05-08)
     and is observably present only on trades opened **2026-05-11 and later**
     (10 of 40 BB_BOUNCE rows; 3 of 13 TREND_CONT_L; 2 of 22 3CO).
   - Fallback: nearest `regime_shadow.jsonl` emission ≤ `timestamp_open` for
     the same pair, within a ±5 minute tolerance. This file is the Phase 4B
     classifier's per-bar audit trail covering all 4 pairs since
     **2026-04-28T18:21Z**. Marks the row `cascade_source=shadow`.
   - If both miss (i.e. fire pre-dates 2026-04-28), the row is marked
     `cascade_source=none` and `cascade_agrees=None`.
3. **Cross-check the forensic snapshot.** `logs/forensic_fires.jsonl` is read
   for the same window and matched on `(strategy, direction, timestamp ±60s)`.
   As of 2026-05-12 the snapshot does **not** persist the cascade label as a
   top-level field (snapshot keys: `schema_version`, `macd_*`, `bb_5m`,
   `ema_5m`, `rsi_5m`, `h1`, `h4`, `swing_5m`, `levels`, `volatility`,
   `session`, `structure_5m` — no `cascade_*` key). The forensic file is
   therefore used only to set a `forensic_snapshot=yes/no` flag and to lift
   H1/H4 fields for the BB_BOUNCE C2 comparison in §4.
4. **Classify agreement.** `cascade_agrees` is computed empirically against
   the actual label vocabulary in `regime_shadow.jsonl` (verified by inspection
   of all 40,047 shadow rows: stable labels are `{NEUTRAL, RANGE, TREND_UP,
   TREND_DOWN}`):
   - `TRUE` ← (BUY, TREND_UP) or (SELL, TREND_DOWN)
   - `FALSE` ← (BUY, TREND_DOWN) or (SELL, TREND_UP)
   - `NEUTRAL` ← cascade ∈ {NEUTRAL, RANGE} regardless of direction
   - `None` ← no cascade data available
5. **Emit join row.** 18 columns including `pnl_pips`, `pnl_gbp` (= pips ×
   `--lot-size`, default 1.0), `close_reason`, `mfe_pips`, `mae_pips`,
   `daily_bias`, `cascade_source`, `forensic_snapshot`.
6. **Aggregate** per strategy and per cascade-bucket; flag any bucket with
   `0 < n < 5` as small-sample.
7. **Counterfactual** (`--gate-by-cascade`): what if all `cascade_agrees=FALSE`
   trades had been blocked? Report blocked-winners, blocked-losers, net pip
   delta, false-positive rate.

### Sample

| Window | Total | With cascade | Source = signal_log | Source = shadow | Source = none |
|---|---:|---:|---:|---:|---:|
| 2026-04-12 → 2026-05-12 (30d) | **302** | 100 | 26 | 74 | 202 |
| Of which `cascade_agrees` is set | 100 | — | — | — | — |
|   TRUE / FALSE / NEUTRAL | 6 / 12 / 82 | | | | |

The 202 NO_CASCADE rows are dominated by `BRIEFING_EXECUTION` /
`BRIEFING_SWEEP` / `BB_REVERSAL` fires from **before 2026-04-28** (when shadow
logging began). The genuinely cascade-tagged sample is therefore 100 rows
across 18 days, not 302 across 30.

### Assumptions

- **£ PnL = pnl_pips × 1.0** per `.env` `TRADE_SIZE=1.0` and confirmed in
  `docs/trades_review_2026-05-11_to_2026-05-12.md` Part 1. The `--lot-size`
  CLI arg makes this overridable.
- **±5 min fallback tolerance**: shadow log writes one row per closed 5m bar
  (~5 min cadence). A trade opened mid-bar finds the prior bar's emission.
  Verified by spot-checking GBPUSD: 18:00:00, 18:05:00, 18:10:00 — exact 5m
  cadence with 1-3 s offset per bar close.
- **Direction matching for forensic**: forensic snapshot uses `LONG`/`SHORT`
  whereas signal_log uses `BUY`/`SELL`. The script maps BUY↔LONG, SELL↔SHORT.
- **Cascade-agrees `RANGE` → NEUTRAL bucket**: the cascade emits RANGE as a
  distinct non-directional verdict (low width percentile, no slope). Treated
  here as neutral. If `RANGE` were instead read as "blocks both directions",
  the FALSE bucket would unchanged and the NEUTRAL bucket would shrink — but
  RANGE is empirically a "no edge either way" signal, not a "wrong direction"
  signal, so the current bucketing is defensible.

### Confounds

The biggest single confound is **manual / IG_RECONCILE closes**: **162 of 302
rows** (53.6%) have `close_reason` indicating either an
`External/manual close detected` event, an `IG_RECONCILE` outcome, or a
software-side `Breakeven stop hit` — exit mechanism is unknown. Per
`docs/trades_review_2026-05-11_to_2026-05-12.md` Part 3, IG-API errors and
deal-key collisions cause silent server-side closes that the bot labels
"MANUAL" — analytics fidelity is degraded for ~30% of recent trades. The pip
P&L is still correct (broker confirms the close price); only the close-reason
attribution is lost. For accuracy purposes this matters less than for an
exit-quality study.

Two smaller confounds:

- **Phase 4B threading recency**: per memory item
  `project_phase4_strategy_threading_for_may23.md` (now outdated per the
  regime status doc Section 4.2), threading of `regime_state` via
  `decision.debug` has been added to 10 strategies. Strategies that thread
  see the cascade label as-it-was at decision time; strategies that don't
  thread use the bar-aligned cache fallback. For this script's purposes both
  paths land in `cascade_stable_at_fire` on signal_log, but the latter has a
  one-bar staleness risk.
- **Single dramatic day**: 2026-05-12 contributes 8 fires (3 of them BB_BOUNCE
  losers in §4) to the 100-cascade-tagged subsample. Conclusions involving
  Tuesday should be flagged as such — see §7 and §8.

---

## 2. Overall join table — representative slice

10 illustrative rows (full CSV at `/tmp/cascade_join_30d.csv`, 302 rows):

```
timestamp_open         pair    strategy                dir  cascade        agree    pnl    source
2026-04-30T06:00:02Z   GBPUSD  3CO                     SELL NEUTRAL        NEUTRAL  -12.6  shadow
2026-04-30T06:35:02Z   GBPUSD  3CO                     BUY  NEUTRAL        NEUTRAL   -3.9  shadow
2026-04-30T06:55:03Z   GBPUSD  3CO                     BUY  TREND_UP       TRUE      -0.9  shadow
2026-05-01T06:40:01Z   USDJPY  3CO                     SELL NEUTRAL        NEUTRAL   +8.1  shadow
2026-05-01T07:40:02Z   USDJPY  3CO                     BUY  NEUTRAL        NEUTRAL  -12.0  shadow
2026-05-04T06:10:05Z   GBPUSD  GBPUSD_BB_BOUNCE_S      SELL RANGE          NEUTRAL  +48.4  shadow
2026-05-04T06:55:02Z   GBPUSD  GBPUSD_BB_BOUNCE_L      BUY  NEUTRAL        NEUTRAL  -10.75 shadow
2026-05-07T06:15:04Z   GBPUSD  GBPUSD_BB_BOUNCE_L      BUY  TREND_DOWN     FALSE    +23.0  shadow
2026-05-12T06:25:03Z   GBPUSD  3CO                     SELL TREND_DOWN     TRUE      +8.2  signal_log
2026-05-12T06:35:03Z   GBPUSD  GBPUSD_BB_BOUNCE_L      BUY  TREND_DOWN     FALSE    -12.7  signal_log
```

Note the two contrasting Tuesday lines at the bottom: 3CO SELL at 06:25 — cascade
TREND_DOWN, agree TRUE, won; BB_BOUNCE_L BUY at 06:35 — cascade also TREND_DOWN,
agree FALSE, lost. Same cascade label drove opposite verdicts because the
strategies traded opposite directions on the same underlying down-trend.

---

## 3. By-strategy aggregates

| Strategy | n | Overall WR | Total pips | Agree-WR (n) | Disag-WR (n) | Neutral-WR (n) | None-n |
|---|---:|---:|---:|---|---|---|---:|
| 3CO | 22 | 59.1% | +22.95 | 50.0% (2 ⚠) | — (0) | 37.5% (8) | 12 |
| BB_REVERSAL | 57 | 29.8% | -167.01 | — (0) | — (0) | — (0) | 57 |
| BRIEFING_EXECUTION | 115 | 37.4% | -258.00 | 50.0% (2 ⚠) | 0.0% (2 ⚠) | 35.0% (20) | 91 |
| BRIEFING_SWEEP | 27 | 40.7% | -60.30 | — (0) | — (0) | — (0) | 27 |
| DAILY_DOUBLE | 2 | 100.0% | +7.10 | — (0) | — (0) | — (0) | 2 |
| **GBPUSD_BB_BOUNCE_L** | **20** | **45.0%** | **-20.15** | — (0) | **20.0% (5)** | **53.3% (15)** | **0** |
| **GBPUSD_BB_BOUNCE_S** | **20** | **35.0%** | **+22.30** | — (0) | **0.0% (5)** | **42.9% (14)** | **1** |
| GBPUSD_BB_REV_PAT_L | 1 | 100.0% | +15.75 | — (0) | — (0) | 100.0% (1 ⚠) | 0 |
| GBPUSD_BB_REV_PAT_S | 1 | 100.0% | +15.55 | — (0) | — (0) | 100.0% (1 ⚠) | 0 |
| **GBPUSD_TREND_CONT_L** | **13** | **61.5%** | **+36.90** | **0.0% (1 ⚠)** | — (0) | **60.0% (10)** | **2** |
| **GBPUSD_TREND_CONT_S** | **6** | **50.0%** | **-3.75** | — (0) | — (0) | **50.0% (6)** | **0** |
| NEWS_STRATEGY | 1 | 100.0% | +5.20 | — (0) | — (0) | 100.0% (1 ⚠) | 0 |
| NEWS_TICK | 10 | 10.0% | -68.35 | 0.0% (1 ⚠) | — (0) | 16.7% (6) | 3 |
| REVERSAL_SWEEP | 7 | 28.6% | -26.15 | — (0) | — (0) | — (0) | 7 |
| **OVERALL** | **302** | **38.4%** | **-477.97** | **33.3% (6 ⚠)** | **8.3% (12)** | **45.1% (82)** | **202** |

⚠ marks small-sample (n<5) buckets. The bolded rows are the deep-dive
strategies in §§4-6.

**Headline.** Across the 100 cascade-tagged rows the gradient is real:
**agree-WR 33.3% > disagree-WR 8.3%** in win rate and the disagreement bucket
loses **-7.84 pips/trade average** (vs neutral -0.91p/avg). That looks like a
strong signal in favour of the cascade, but the 6 / 12 / 82 / 202 split is
heavily neutral- and unknown-weighted — the cascade is "ABSTAIN-leaning" in
the current 5m structural reality (largely range / low-conviction on the recent
data). The disagreement bucket (n=12) is small but dominated by BB_BOUNCE.

---

## 4. BB_BOUNCE deep-dive (20 LONG + 20 SHORT fires)

Every fire, in chronological order. `cas=` is the cascade label at fire bar
(signal_log primary, shadow fallback); `agree` is the bucket.

### 4.1 BB_BOUNCE_L (n=20) — every fire

```
2026-05-04T06:55Z  BUY  NEUTRAL    NEUTRAL  -10.75  SL hit
2026-05-04T09:30Z  BUY  NEUTRAL    NEUTRAL   -1.55  MANUAL
2026-05-04T14:20Z  BUY  NEUTRAL    NEUTRAL  -12.10  BRIEFING_TP_SL_OPEN
2026-05-04T15:10Z  BUY  RANGE      NEUTRAL   -3.35  MANUAL
2026-05-05T09:25Z  BUY  NEUTRAL    NEUTRAL   +2.45  Breakeven stop
2026-05-05T11:25Z  BUY  RANGE      NEUTRAL   +7.05  MANUAL
2026-05-06T06:40Z  BUY  NEUTRAL    NEUTRAL   +7.35  MANUAL
2026-05-06T13:50Z  BUY  NEUTRAL    NEUTRAL   +0.40  PRE_NEWS_CLOSE
2026-05-06T14:25Z  BUY  NEUTRAL    NEUTRAL  +12.75  MANUAL
2026-05-07T06:15Z  BUY  TREND_DOWN FALSE    +23.00  BRIEFING_TP1_CLOSE  ← cascade wrong
2026-05-07T14:00Z  BUY  NEUTRAL    NEUTRAL  -12.00  BRIEFING_TP_SL_OPEN
2026-05-07T15:35Z  BUY  NEUTRAL    NEUTRAL  -12.00  BRIEFING_TP_SL_OPEN
2026-05-07T16:25Z  BUY  TREND_DOWN FALSE    -12.00  BRIEFING_TP_SL_OPEN
2026-05-08T08:10Z  BUY  NEUTRAL    NEUTRAL  +18.55  MANUAL
2026-05-08T11:10Z  BUY  NEUTRAL    NEUTRAL   +4.65  MANUAL
2026-05-11T10:50Z  BUY  TREND_DOWN FALSE    -12.10  BRIEFING_TP_SL_OPEN
2026-05-11T11:05Z  BUY  NEUTRAL    NEUTRAL  +14.15  MANUAL
2026-05-12T06:35Z  BUY  TREND_DOWN FALSE    -12.70  BRIEFING_TP_SL_OPEN  ← Tuesday #15
2026-05-12T11:10Z  BUY  NEUTRAL    NEUTRAL   -9.95  SL hit               ← Tuesday #20
2026-05-12T12:30Z  BUY  TREND_DOWN FALSE    -12.00  BRIEFING_TP_SL_OPEN  ← Tuesday #21
```

Cascade said FALSE 5 times → 1 winner (+23.0p), 4 losers (-48.8p), net -25.8p
blocked.

### 4.2 BB_BOUNCE_S (n=20) — every fire

```
2026-05-04T06:10Z  SELL RANGE      NEUTRAL  +48.40  REGIME_MAX_HOLD
2026-05-04T14:35Z  SELL n/a        -        +21.50  BRIEFING_TP1_CLOSE  (pre-shadow gap)
2026-05-05T06:16Z  SELL RANGE      NEUTRAL   -5.95  MANUAL
2026-05-05T06:45Z  SELL TREND_UP   FALSE    -12.60  BRIEFING_TP_SL_OPEN
2026-05-05T08:35Z  SELL NEUTRAL    NEUTRAL   +3.15  Breakeven stop
2026-05-05T12:35Z  SELL NEUTRAL    NEUTRAL  -12.10  BRIEFING_TP_SL_OPEN
2026-05-05T13:25Z  SELL TREND_UP   FALSE     -0.60  PRE_NEWS_CLOSE
2026-05-05T14:35Z  SELL RANGE      NEUTRAL  -12.30  BRIEFING_TP_SL_OPEN
2026-05-06T07:15Z  SELL RANGE      NEUTRAL  -12.00  BRIEFING_TP_SL_OPEN
2026-05-06T07:55Z  SELL TREND_UP   FALSE    -12.20  BRIEFING_TP_SL_OPEN
2026-05-07T09:05Z  SELL NEUTRAL    NEUTRAL   -0.60  REGIME_MAX_HOLD
2026-05-07T15:05Z  SELL NEUTRAL    NEUTRAL   +2.15  Breakeven stop
2026-05-07T15:15Z  SELL NEUTRAL    NEUTRAL  +40.90  BRIEFING_TP1_CLOSE
2026-05-08T06:10Z  SELL TREND_UP   FALSE    -12.10  BRIEFING_TP_SL_OPEN
2026-05-08T16:15Z  SELL NEUTRAL    NEUTRAL  -11.45  SL hit
2026-05-11T06:20Z  SELL RANGE      NEUTRAL  -12.10  BRIEFING_TP_SL_OPEN
2026-05-11T07:15Z  SELL TREND_UP   FALSE     -4.45  MANUAL
2026-05-11T08:40Z  SELL NEUTRAL    NEUTRAL   +1.75  Breakeven stop
2026-05-11T13:25Z  SELL RANGE      NEUTRAL   -7.20  PRE_NEWS_CLOSE
2026-05-12T10:40Z  SELL NEUTRAL    NEUTRAL  +20.10  BRIEFING_TP1_CLOSE
```

Cascade said FALSE 5 times → **0 winners, 5 losers (-41.95p)**. Clean signal.

### 4.3 BB_BOUNCE counterfactual

```
                       baseline      after gate     blocked
n                      40            30             10
WR                     40.0%         50.0%          (1 win / 9 losers)
total_pips             +2.15         +69.90         -67.75
delta vs baseline:     +67.75p (+£67.75)
false-positive rate:   10.0% (1 winner killed of 10 blocked)
```

### 4.4 Cascade vs Option C2 (H1 BEAR + H4 down) from `bb_bounce_l_audit_2026-05-12.md`

The audit Section 5 proposed **Option C2**: block LONG when `h1.stack_state ==
BEAR_ALIGNED AND h4.trend_4bar == downtrend` (mirror for SHORTs). Forensic
snapshots are required and exist only from 2026-05-05 onward, so C2 is
evaluable on a smaller (17 of 20 LONG / 18 of 20 SHORT) subsample.

| Gate | LONG blocks | LONG winners-killed | LONG losers-saved | LONG net pips saved | SHORT blocks | SHORT W-K | SHORT L-S | SHORT net pips saved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Cascade FALSE** | 5 | 1 (+23.0) | 4 (-48.8) | **+25.8p** | 5 | 0 | 5 (-41.95) | **+41.95p** |
| **Option C2 (H1+H4)** | 3 | 0 | 3 (-34.65) | **+34.65p** | 6 | 2 (+62.4) | 4 (-62.2) | **-0.20p** |

Observations:

- On **LONG**, C2 saves more pips than cascade (+34.65 vs +25.8) and kills no
  winners, but cascade catches more total trades and only loses one winner
  (2026-05-07 06:15 +23p). Both gates catch all three Tuesday losers.
- On **SHORT**, cascade is **clean** (5/5 losers, 0 winners killed) but C2 is
  catastrophic — it kills the 2026-05-04 06:10 +48.4p winner and the
  2026-05-07 15:15 +40.9p winner because they fired in BULL-aligned H1 with
  uptrend H4 against the move. The H1/H4-stack interpretation is asymmetric:
  it works for LONG-side fades (catches counter-trend buys into a strong down)
  but penalises legitimate SHORT-side fades into BULL-aligned H1 that then
  collapse.
- **Overlap**: of the 18 trades evaluable by both gates, only 3 are blocked
  by both. 7 are blocked by cascade alone (5 losers, 1 winner, 1 manual),
  6 are blocked by C2 alone (4 losers, 2 winners).

**Verdict for BB_BOUNCE**: cascade is the simpler, more symmetric gate. C2 is
LONG-biased and fails on SHORT. If only one gate could be live, cascade has
the cleaner combined-side signal: **+67.75p / 10% FPR** vs C2's
**+34.45p / 22% FPR** combined. **But: 4 of 5 BB_BOUNCE_L cascade-FALSE losers
are the same three Tuesday fires plus 2026-05-11 10:50, all in a 48-hour
window, so this is plausibly a single regime spell.** See §8.

---

## 5. TREND_CONT deep-dive (19 fires)

```
2026-05-04T13:20Z  S    NEUTRAL    NEUTRAL  -11.35  MANUAL
2026-05-04T14:45Z  S    RANGE      NEUTRAL   +5.75  TP hit
2026-05-04T15:20Z  S    RANGE      NEUTRAL  +12.20  MPP
2026-05-04T16:43Z  S    NEUTRAL    NEUTRAL  -12.65  SL hit
2026-05-04T17:40Z  S    RANGE      NEUTRAL   -6.10  REGIME_MAX_HOLD
2026-05-06T07:45Z  L    RANGE      NEUTRAL   +3.55  Breakeven stop
2026-05-06T08:25Z  L    n/a        -        +12.10  MPP                (pre-shadow gap)
2026-05-06T09:20Z  L    n/a        -        +12.45  MANUAL             (pre-shadow gap)
2026-05-07T12:05Z  L    NEUTRAL    NEUTRAL   -8.00  REGIME_MAX_HOLD
2026-05-07T14:15Z  L    RANGE      NEUTRAL  -10.65  MANUAL
2026-05-08T13:20Z  L    NEUTRAL    NEUTRAL   +8.60  MPP
2026-05-08T14:00Z  L    TREND_UP   TRUE      -9.95  SL hit             ← cascade TRUE but lost
2026-05-08T15:30Z  L    NEUTRAL    NEUTRAL   +8.10  MPP
2026-05-08T16:25Z  L    NEUTRAL    NEUTRAL   -6.50  REGIME_MAX_HOLD
2026-05-08T17:55Z  L    NEUTRAL    NEUTRAL  +11.75  TP hit
2026-05-11T13:10Z  L    NEUTRAL    NEUTRAL   +8.10  MPP
2026-05-11T15:00Z  L    NEUTRAL    NEUTRAL   +8.65  MANUAL
2026-05-11T16:35Z  L    NEUTRAL    NEUTRAL   -1.30  REGIME_MAX_HOLD
2026-05-12T11:00Z  S    NEUTRAL    NEUTRAL   +8.40  MPP
```

**Buckets**: agree TRUE = 1 (the only -9.95p loser), agree FALSE = 0, agree
NEUTRAL = 16, none = 2.

There are **zero** cascade-FALSE TREND_CONT trades over the 30-day window —
which is exactly what the strategy's own production gate
(`gbpusd_regime_detector` "block on RANGE", `gbpusd_trend_continuation.py:604`)
is supposed to enforce, but with a different vocabulary. The fact that the
cascade also never returns the opposite-trend label on a TREND_CONT fire is
either (a) confirmation that the existing production gate catches the
counter-trend case correctly or (b) reflective of the cascade's structural
shyness toward emitting a directional label at all (16 of 19 fires sat in
RANGE/NEUTRAL).

The single cascade=TRUE loss (2026-05-08 14:00 LONG, TREND_UP, -9.95p) is
worth noting in §7.

**Per the memory item `project_phase4_strategy_threading_for_may23.md`**: the
note said TREND_CONT used only "bar-aligned cache fallback, not decision.debug",
implying the cascade field on TREND_CONT fires may be a one-bar-stale shadow
read rather than a fresh decision-time read. Verified by inspection: per the
regime status doc Section 4.2, `gbpusd_trend_continuation.py:715` does in
fact thread `decision.debug["regime_state"]`, so the memory item is outdated.
Both BB_PIERCE_RUN and TREND_CONT thread decision-time cascade now. The
TREND_CONT cascade values in the table above are therefore fresh, not stale.

**Verdict for TREND_CONT**: cascade gating is inert on the current sample —
the FALSE bucket is empty by construction. Counterfactual delta is +0p. The
cascade adds zero filtering value here. Stay shadow.

---

## 6. 3CO deep-dive (22 fires)

```
2026-04-14T11:19Z  USDCAD  SELL n/a        -         +1.00  REGIME_MAX_HOLD
2026-04-24T06:40Z  USDJPY  SELL n/a        -         +0.10  PRE_NEWS_CLOSE
2026-04-27T06:05Z  GBPUSD  SELL n/a        -         -0.70  REGIME_MAX_HOLD
2026-04-27T06:50Z  USDJPY  SELL n/a        -         +9.60  MPP
2026-04-27T07:05Z  EURUSD  BUY  n/a        -         +9.70  MPP
2026-04-27T11:00Z  USDCAD  SELL n/a        -         +3.40  REGIME_MAX_HOLD
2026-04-28T06:00Z  EURUSD  SELL n/a        -        +18.70  BRIEFING_TP1_CLOSE
2026-04-30T06:00Z  GBPUSD  SELL NEUTRAL    NEUTRAL  -12.60  BRIEFING_TP_SL_OPEN
2026-04-30T06:35Z  GBPUSD  BUY  NEUTRAL    NEUTRAL   -3.90  PRE_NEWS_CLOSE
2026-04-30T06:35Z  USDJPY  SELL n/a        -         -5.30  BRIEF_INVALIDATED
2026-04-30T06:55Z  GBPUSD  BUY  TREND_UP   TRUE      -0.90  PRE_NEWS_CLOSE
2026-04-30T12:15Z  USDCAD  BUY  n/a        -         +1.20  PRE_NEWS_CLOSE
2026-05-01T06:40Z  USDJPY  SELL NEUTRAL    NEUTRAL   +8.10  MPP
2026-05-01T06:50Z  USDJPY  SELL NEUTRAL    NEUTRAL   +2.60  MPP
2026-05-01T06:55Z  USDJPY  SELL NEUTRAL    NEUTRAL   +8.00  MPP
2026-05-01T07:40Z  USDJPY  BUY  NEUTRAL    NEUTRAL  -12.00  BRIEFING_TP_SL_OPEN
2026-05-01T12:05Z  USDCAD  SELL n/a        -         +8.00  MPP
2026-05-05T06:10Z  GBPUSD  BUY  RANGE      NEUTRAL   -6.95  MANUAL
2026-05-07T06:45Z  USDJPY  SELL n/a        -        -13.80  BRIEFING_TP_SL_OPEN  ← pre-shadow gap
2026-05-07T12:20Z  USDCAD  BUY  n/a        -        +11.90  MPP                 ← USDCAD shadow gap
2026-05-12T06:25Z  GBPUSD  SELL TREND_DOWN TRUE      +8.20  MPP
2026-05-12T07:00Z  USDJPY  BUY  NEUTRAL    NEUTRAL  -11.40  BRIEFING_TP_SL_OPEN
```

**Buckets**: agree TRUE = 2 (1 win 06:25 +8.2p, 1 loss 04-30 -0.9p
PRE_NEWS_CLOSE), agree FALSE = 0, agree NEUTRAL = 8 (3 wins 5 losses, total
-28.15p), none = 12 (mostly pre-shadow-log fires before 2026-04-28 + USDJPY
gaps).

**Cascade gating would not help 3CO directly** (zero FALSE-bucket fires to
block) — but the proposed "stay in trend while cascade stays TREND_X"
re-entry concept is partially testable:

- The 2026-05-12 06:25 GBPUSD SELL cascade=TREND_DOWN/TRUE, MPP-clipped at
  +8.2p, MFE +60.4p per `trades_review`. If 3CO were allowed to re-enter
  while cascade held TREND_DOWN, it would have re-entered roughly every 5-10
  minutes until 08:10 (the cascade held TREND_DOWN continuously 06:25→08:30
  per `regime_shadow.jsonl`). That's ~10 additional re-entries on the same
  day, sized at 1.0 GBP/pip — pending broker-position-slot rules and
  spread/commission this is plausibly +20-40p of additional capture per
  re-entry, but the analysis would also need a tighter SL since each
  re-entry is at a worse price.
- **Risk**: the 2026-04-30 06:55 GBPUSD BUY cascade=TREND_UP/TRUE 3CO fire
  lost -0.9p (PRE_NEWS_CLOSE). One-sample size; the broader concern is that
  TREND_UP/TREND_DOWN is a 2-bar-hysteresis-confirmed label and may itself
  lag at the actual trend exhaustion. A re-entry-while-trending mode without
  an exhaustion overlay would over-stay.

**Verdict for 3CO**: the FALSE-bucket signal is empty (cascade never
contradicted a 3CO fire). The TRUE-bucket re-entry concept is genuinely
interesting but is **untested** on this data — only 2 fires hit the bucket.
Recommend collecting the May 19 review's 7 extra days of cascade-TRUE 3CO
fires before designing a re-entry experiment.

---

## 7. Adversarial: where cascade was wrong

The 100-cascade-tagged subsample has **1 FALSE-winner** and **4 TRUE-losers**.

### FALSE-winner (cascade said wrong direction, trade still profitable)

| Time | Pair | Strategy | Dir | Cascade | PnL | Close reason |
|---|---|---|---|---|---:|---|
| 2026-05-07T06:15Z | GBPUSD | BB_BOUNCE_L | BUY | TREND_DOWN | **+23.0p** | BRIEFING_TP1_CLOSE |

**Context**: 2026-05-07 was a NEUTRAL daily_bias day per the audit's bucket
table. The BB_BOUNCE_L fire at 06:15 caught a clean BB-lower-pierce-and-reclaim
of the early-session low. Cascade was emitting TREND_DOWN because the previous
4 hours (overnight Asian) had been a slow drift down — exactly the kind of
"intra-session reversal off a swept low" that BB_BOUNCE is designed for. The
cascade's 2-bar hysteresis can't see the reversal. **Blind spot: intraday
reversals of overnight trends.**

### TRUE-losers (cascade agreed with direction but trade still lost)

| Time | Pair | Strategy | Dir | Cascade | PnL | Close reason |
|---|---|---|---|---|---:|---|
| 2026-04-29T13:47Z | USDCAD | NEWS_TICK | BUY | TREND_UP | -14.75 | SL hit |
| 2026-04-30T06:55Z | GBPUSD | 3CO | BUY | TREND_UP | -0.90 | PRE_NEWS_CLOSE |
| 2026-05-06T19:30Z | USDJPY | BRIEFING_EXECUTION | SELL | TREND_DOWN | -4.00 | NY_CLOSE |
| 2026-05-08T14:00Z | GBPUSD | TREND_CONT_L | BUY | TREND_UP | -9.95 | SL hit |

Two of these four are forced exits unrelated to direction:
- **2026-04-30 06:55 PRE_NEWS_CLOSE** — the strategy was directionally right
  but news-window blackout closed the trade prematurely.
- **2026-05-06 19:30 NY_CLOSE** — session-end time stop, not a directional
  call.

The two real losses:
- **2026-04-29 13:47 USDCAD NEWS_TICK BUY** lost on a SL hit. NEWS_TICK is the
  PMI/ISM/sentiment tight-TP strategy; tick-level reversals on news are the
  documented failure mode (memory `project_news_tick_tight_tp_guard.md`). Not
  a cascade fault.
- **2026-05-08 14:00 TREND_CONT_L BUY** lost -9.95p (SL hit at 13619 from
  entry 13628.4). H1 was BULL_ALIGNED, H4 uptrend, cascade TREND_UP — the
  setup looked good. The loss is a clean reversal one bar after entry. Tick-
  level reversal on a session high. Same blind spot as the FALSE-winner above:
  the cascade sees structural trend persistence; it doesn't see
  micro-exhaustion at the swing top.

**Suggested blind spots for the May 19 review to investigate:**

1. **Overnight-trend → intraday-reversal pattern**: cascade holds yesterday's
   trend label too long. (BB_BOUNCE_L 05-07 06:15.)
2. **Session boundary failures**: 4 of 5 adversarial trades fire at session
   bounds (06:15, 06:55, 13:47, 14:00, 19:30) where structural inputs are
   stale or mis-aligned with the active session's price action.
3. **News-driven tick-level reversals**: the cascade has no news-event input
   and labels NEWS_TICK fires identically to range-fade fires.

---

## 8. Verdict

### Is the cascade accurate enough to gate trades for the 2026-05-19 review?

**For BB_BOUNCE_L specifically: PROVISIONAL YES.** Cascade=FALSE caught 5 of
20 fires; 4 of 5 blocks were losers (-48.8p), 1 was a winner (+23.0p). Net
+25.8p / 10% FPR / 3 of 3 Tuesday losers caught. It is slightly worse than
the H1/H4 stack gate (C2) on LONG-side only (+34.65p, 0% FPR), but the
cascade-FALSE bucket is structurally cleaner — it does not require forensic
snapshot back-fill and would work for SHORTs symmetrically. **Sample-size
caveat**: 4 of the 5 LONG losers it caught fired on 2 consecutive trading
days (2026-05-11 and 2026-05-12) — i.e. a single bear regime spell.
n_independent ≈ 2 days, not 5 fires. **Single dramatic example — needs more
days before commit.**

**For BB_BOUNCE_S specifically: YES.** Cascade=FALSE caught 5 of 20 SHORT
fires, all losers (-41.95p), zero winners killed. This is cleaner than C2,
which on SHORT-side blocks 2 winners (+103.3p combined) and 4 losers
(-62.2p) for net -0.2p — C2 is *negative* on the SHORT side. Cascade is the
only gate that works symmetrically. Same sample-size caveat: 4 of the 5
blocks fired in the 2026-05-05 → 2026-05-08 window, plus 1 on 2026-05-11.

**For TREND_CONT specifically: NO.** Zero cascade-FALSE fires in 30 days.
The existing production gate
(`gbpusd_regime_detector` "block on RANGE") apparently does its job already —
the cascade has nothing to add. The single cascade-TRUE loser (2026-05-08
14:00 -9.95p) is a tick-level reversal not visible at the cascade timescale.
Cascade gating would deliver zero additional filtering on the 30-day sample.

**For 3CO specifically: NO (as a block-gate); UNDETERMINED (as a stay-in mode).**
Zero cascade-FALSE fires — the strategy's gate-exempt design plus the
fast-trend selection bias means cascade never opposed a 3CO fire in 30 days.
The 2 cascade-TRUE fires (1 winner, 1 PRE_NEWS-clipped) are too thin to
validate a re-entry-while-trending mode. Recommend deferring the 3CO
cascade-coupling decision to the May 19 review with a larger sample.

### Is the sample big enough at all?

**No.** Three structural problems:

1. **Cascade-tagged subsample is n=100 across 18 days, not 30.** The 202
   NO_CASCADE rows pre-date 2026-04-28 (regime_shadow start) and are
   unusable for accuracy verification. The 100 usable rows skew heavily
   neutral: 82 NEUTRAL, 12 FALSE, 6 TRUE. The directional buckets are
   sub-statistical at the strategy level.
2. **The `cascade_stable_at_fire` signal_log field starts 2026-05-11.** That
   is only 2 days. For everything earlier (the shadow-fallback 74 rows), the
   classifier is read from a different code path (bar-aligned cache via
   shadow log) which has a one-bar staleness risk. The "primary" path (10
   rows BB_BOUNCE, 3 rows TREND_CONT_L, 2 rows 3CO, etc.) has reliable
   sub-second snapshotting but is too small.
3. **2026-05-12 dominates the bear-cascade evidence**: 3 of the 4
   BB_BOUNCE_L FALSE losers fired on the same day in a 6-hour window. The
   bear regime spell of 2026-05-11 → 2026-05-12 is a single statistical
   event. If you remove Tuesday from the BB_BOUNCE_L counterfactual:
   3 cascade-FALSE blocks (1 winner -7p, 2 losers +35p net), still positive
   but the margin shrinks dramatically.

### Recommendation for the May 19 review

- **Keep the join script in `scripts/` and re-run it daily** as the May 19
  date approaches. By 2026-05-19 the cascade-tagged subsample should be
  closer to n=150 with ~30 cascade-FALSE bucket rows across 3-4 independent
  regime spells.
- **Do NOT flip `REGIME_CLASSIFIER_ENTRY_FILTER_ENABLED=1` yet.** The
  cascade signal on BB_BOUNCE looks promising but is driven by one regime
  spell. Wait for 2-3 more bear spells (the natural rate suggests 1-2 per
  week) to confirm.
- **Add cascade_stable_at_fire to the forensic snapshot.** This was noted
  missing in §1. Forensic capture began 2026-05-05 but does not persist the
  cascade label. Lifting it would simplify future joins and remove the
  shadow-log fallback dependency. (Implementation deferred per task scope
  — do not change production code.)
- **Re-evaluate the TREND_CONT / 3CO cascade-coupling questions on 2026-05-19**
  with 7-9 more trading days of data.

### Adversarial honesty check

The headline "agree-WR 33.3% vs disagree-WR 8.3%" looks impressive but is
n=6 agree / n=12 disagree, both below the n<5 / n<10 stability thresholds. The
BB_BOUNCE_S "5 blocks, 5 losers, 0 winners killed" looks like a slam-dunk
but **4 of the 5 fired in 4 trading days (2026-05-05 → 2026-05-08)** when the
GBPUSD daily trend was decisively bearish and any contrarian SELL fade against
a confirmed bull (cascade TREND_UP) was structurally doomed. This is a
regime-spell finding more than a classifier finding. If GBPUSD enters a clean
range or trend reversal in late May, the disagree-bucket WR could move
materially. **The verdict above is the cleanest read on the current data; it
is not yet a robust statistical claim.**

---

## Appendix A — How to re-run

```
# Full 30-day join + CSV
python3 scripts/cascade_outcome_join.py \
    --since 2026-04-12 --until 2026-05-12 \
    --out both --csv-path /tmp/cascade_join_30d.csv

# Per-strategy counterfactual
python3 scripts/cascade_outcome_join.py \
    --strategy GBPUSD_BB_BOUNCE_L --strategy GBPUSD_BB_BOUNCE_S \
    --gate-by-cascade

python3 scripts/cascade_outcome_join.py \
    --strategy GBPUSD_TREND_CONT_L --strategy GBPUSD_TREND_CONT_S \
    --gate-by-cascade

python3 scripts/cascade_outcome_join.py --strategy 3CO --gate-by-cascade
```

CSV at `/tmp/cascade_join_30d.csv`. Script at
`/opt/tradingbot/scripts/cascade_outcome_join.py`. Re-running with identical
args is idempotent (only reads append-only log files and emits stdout/CSV).
