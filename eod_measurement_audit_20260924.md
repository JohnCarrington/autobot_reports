# EOD Measurement Audit — 2026-09-24

_Investigation only — no trading behaviour, gates, thresholds, permissions, models or configuration were touched. All findings are evidence-bearing._

---

## Executive answer

- **EOD_CAN_MEASURE_TRADE_MANAGEMENT_EFFECTIVENESS = NO** — every TM_OBSERVATION row emitted today (and yesterday) skipped both V1-baseline derivation and V2 evaluation with `unavailable_reason: MISSING_ENTRY_TS`.
- **EOD_CAN_COMPARE_BOUNCE_FAMILY_EFFECTIVENESS = NO** — the graded corpus resolves 0 of 601 rows for the compare-family renderer, and the three bounce families (GBPUSD_BB_BOUNCE, LEVEL_BOUNCE, V2_PICK_BOUNCE) do not co-emit onto the same physical opportunities in the corpus the report reads.
- **MEASUREMENT_DEFECT_FOUND = YES** (two independent defects — see §1 and §2).
- **TRADING_DEFECT_PROVEN = NO** — reconstruction shows the 7 fills executed as scheduled; the flagged "blocked SHORT winner" at 09:35 is a **detect-only EMA_PULLBACK candidate on a fully-disabled strategy** (memory `project_ema_pb_armed_machine_live.md`), not a suppressed live route.
- **CODE_CHANGE_REQUIRED = YES** (two localized reader/writer fixes, described but NOT implemented per operator instruction).
- **TRADING_BEHAVIOUR_CHANGE_REQUIRED = NO.**

---

## §1 — Why §7C is 100% indeterminate

### Numbers

| Field | Value |
|---|---:|
| `TM_OBSERVATIONS` (2026-09-24) | **101** (rows with `record_type=TM_OBSERVATION`, `bar_ts_utc` on 2026-09-24) |
| `TM_WITH_V2_RECOMMENDATION` | **0** |
| `TM_WITH_V1_BASELINE` (rows where `current_pnl_pips` is real) | **0** |
| `TM_WITH_FORWARD_OUTCOME` | **0** (the writer does not stamp forward outcomes; that is intentional) |
| `TM_COMPARABLE` (rows where V1 and V2 both derived) | **0** |
| `ROOT_CAUSE_100_PERCENT_INDETERMINATE` | Every observation short-circuits at `_derive_causal_position_features → unavailable_reason = MISSING_ENTRY_TS` (`tm_corpus_writer.py:352-354`), which then propagates as `tm_v2_skip_reason = MISSING_ENTRY_TS` (`tm_corpus_writer.py:693-700`). No V1 pnl/MFE/MAE, no V2 invocation. |
| `CORPUS_DEFECT / REPORT_DEFECT / EXPECTED_PENDING_STATE` | **CORPUS_DEFECT** (writer-side type mismatch, not a reader bug and not "waiting for future data"). |

### The bug (evidence)

`trade_executor._STATE_TEMPLATE` defines `"open_time": None` at `trade_executor.py:1001`. Every population site stores a **UNIX epoch float** via `time.time()` — `trade_executor.py:3254, 3617, 3704, 4369`.

The corpus writer expects an ISO-8601 string or a datetime. At `tm_corpus_writer.py:663`:

```python
entry_ts_raw = meta.get("open_time") or meta.get("entry_ts")
```

then, inside `_derive_causal_position_features` at `tm_corpus_writer.py:341-354`:

```python
if entry_ts_raw is not None:
    if hasattr(entry_ts_raw, "isoformat"):
        entry_ts = entry_ts_raw
    else:
        try:
            entry_ts = _dt.fromisoformat(str(entry_ts_raw).replace("Z","+00:00"))
        except Exception:
            entry_ts = None
if entry_ts is None:
    result["unavailable_reason"] = "MISSING_ENTRY_TS"
    return result
```

`datetime.fromisoformat("1727178307.5")` raises → `entry_ts = None` → every row skips both V1 and V2. Proof — a real row:

```
bar_ts_utc                          strategy               tm_v2_evaluated  tm_v2_skip_reason    tm_v2_recommendation  current_pnl_pips  mfe_pips_so_far  mae_pips_so_far  causal_feature_unavailable_reason
2026-09-24T12:10:00+00:00           GBPUSD_BB_BOUNCE_L     False            MISSING_ENTRY_TS     None                  None              None             None             MISSING_ENTRY_TS
```

**101 of 101 rows follow the same pattern.** Aggregate scan:

```
V2_EVALUATED_TRUE:                 0
V2_RECOMMENDATION_NOT_NULL:        0
V2_SKIP_REASONS:                   [('MISSING_ENTRY_TS', 132)]
V1_CAUSAL_FEATURE_UNAVAILABLE:     [('MISSING_ENTRY_TS', 132)]
```
(132 = 101 rows on 2026-09-24 + 31 on 2026-09-25; every row is affected.)

This is the same *class* of contract mismatch as the C7 pair-derivation fix committed to `tm_corpus_writer.py:471-490` on 2026-09-24 (that comment explicitly notes `_STATE_TEMPLATE` does not carry the fields the writer reads). C7 fixed `pair`; `open_time` was not addressed and still fails.

### Smallest correction (NOT applied)

Inside `_derive_causal_position_features`, accept a numeric `entry_ts_raw` as a UNIX epoch:

```python
try:
    if isinstance(entry_ts_raw, (int, float)):
        entry_ts = _dt.fromtimestamp(float(entry_ts_raw), tz=_tz.utc)
    elif hasattr(entry_ts_raw, "isoformat"):
        entry_ts = entry_ts_raw
    else:
        entry_ts = _dt.fromisoformat(str(entry_ts_raw).replace("Z","+00:00"))
except Exception:
    entry_ts = None
```

Two lines. Read-only fix; adds nothing to the trading path. It restores V1 baseline (`current_pnl_pips`, `mfe_pips_so_far`, `mae_pips_so_far`) AND unblocks the V2 shadow invocation — after which the §7C report can start populating V2>V1 / V1>V2 / equivalent buckets from tomorrow's rows onward.

STOPPING BEFORE IMPLEMENTATION per operator instruction.

---

## §2 — Why §7E shows 540 pending with 0 resolved (and the date offset)

### The 540 pending

`logs/qm_candidates_graded.jsonl` currently holds 601 rows. Of those:

- **571 rows** have `outcome.notes = ["insufficient_inputs"]` — set by `outcome_grader.grade_qm_candidate_row` at `outcome_grader.py:243-246` when `hypothetical_entry` is `None`.
- **30 rows** ARE fully graded (each has `mfe_pips`, `mae_pips`, `stop_first`, `target_first`, `horizon_bars_evaluated`, `time_to_mfe_min`, etc.).

Why 571 lack `hypothetical_entry`? Only `state=ENTRY_ARMED` rows in `qm_candidates.jsonl` carry `hypothetical_entry / stop / target`. Every other lifecycle state (APPROACHING_ZONE, EXTREME_REACHED, REVERSAL_CANDIDATE, LEVEL_ACCEPTED, SWEEP_DETECTED, REJECTION_CANDIDATE, REJECTION_CONFIRMED) has none. Distribution:

```
APPROACHING_ZONE:    320  (with_entry=0)
EXTREME_REACHED:     162  (with_entry=0)
REVERSAL_CANDIDATE:   33  (with_entry=0)
ENTRY_ARMED:          30  (with_entry=30)     <-- only these get graded
LEVEL_ACCEPTED:       24  (with_entry=0)
SWEEP_DETECTED:       17  (with_entry=0)
REJECTION_CANDIDATE:   8  (with_entry=0)
REJECTION_CONFIRMED:   7  (with_entry=0)
```

**But even those 30 fully-graded rows still register as "pending"** in §7E, because `r4_bounce._outcome_state` at `scripts/eod_learning/r4_bounce.py:23-47` only recognises `outcome.winner in {WIN,LOSS,SCRATCH}`, `outcome.resolution` or `outcome.pnl_pips/realised_pips`. The grader writes `stop_first: True/False` + `target_first: True/False` + `mfe_pips` / `mae_pips`. There is NO field the classifier knows about, so all 30 rows fall through the last `return "pending"`. Sample:

```
symbol=GBPUSD opened_at=2026-09-16T14:45:00+00:00 state=ENTRY_ARMED
  hypothetical_entry=13453.45  stop=13464.55  target=13438.45
  outcome={'drawdown_20bar_pips': 7.3, 'excursion_20bar_pips': 11.1,
           'graded_at_ts': '2026-09-25T00:15:02.106406+00:00',
           'grader_version': 'phase1.0', 'horizon_bars_evaluated': 240,
           'mae_pips': 9.75, 'mfe_pips': 37.15, 'notes': [],
           'stop_first': False, 'target_first': True,
           'time_to_mae_min': 195, 'time_to_mfe_min': 195}
```

`target_first=True` = a WIN; §7E displays it as PENDING. **REPORT_DEFECT + partial CORPUS_DEFECT** (571 rows are legitimately un-gradeable as trades because they are pre-fire lifecycle states — the denominator itself is misleading).

### Date discrepancy — EOD_DATE = 2026-09-24 vs BOUNCE_TODAY_DATE = 2026-09-23

`r4_bounce.render_markdown()` is called at `eod_review_narrative.py:368` with **no argument** and internally calls `compute()` which sets `today = datetime.now(timezone.utc).date()` (`r4_bounce.py:55`). Then `select_recent_dates(cand, _opened_at, 1, upto=today)` returns the most-recent-first UTC date **actually present in the file**.

Timeline:
- `reports/eod/review_2026-09-24.md` was written at **22:20:19Z** on 2026-09-24.
- `logs/qm_candidates_graded.jsonl` was last modified at **00:15:02Z on 2026-09-25** (mtime).
- At 22:20 UTC when the renderer read the corpus, the newest `opened_at` present was 2026-09-23 (73 rows). The 57 rows for `opened_at=2026-09-24` were added by the grader after the report ran.
- Additionally, §7E renders with `today = now_UTC.date()` and IGNORES the narrator's `--date` argument — so if the narrator is invoked with `--date=YYYY-MM-DD` the §7E header still says "today = wall-clock UTC date". This is a second, latent report defect.

Result: TODAY-N=69 corresponds to `opened_at=2026-09-23` and reports 4 more rows than 5D-only-N=69 would suggest, because 5D "N=388" here spans 2026-09-17…2026-09-23. The 20D window is smaller than 5D would suggest because the corpus is thin outside the last week.

### Family comparability

Can GBPUSD_BB_BOUNCE / LEVEL_BOUNCE / V2_PICK_BOUNCE be compared on the same physical opportunities from present logs? **No, not from `qm_candidates_graded.jsonl`.** That corpus tracks the QM zone-lifecycle state machine (one row per zone-state), not per-detector fires. On 2026-09-24 the sources hold:

| Source | GBPUSD_BB_BOUNCE | LEVEL_BOUNCE | V2_PICK_BOUNCE |
|---|---:|---:|---:|
| `logs/candidate_corpus.jsonl` (GBPUSD, 2026-09-24) | 24 rows (7 fired, 17 blocked) | **0** | **0** (2 rows exist but are EURUSD) |
| `logs/qm_candidates.jsonl` (GBPUSD, 2026-09-24) | n/a (different schema, states only) | 1 ENTRY_ARMED @ 12:35 | 0 |

So the "compare bounce families on the same physical opportunity" question **cannot be answered today with the existing streams** — LEVEL_BOUNCE and V2_PICK_BOUNCE did not emit GBPUSD candidates yesterday. That is a *detector-emission* wiring gap, not a report bug.

### Smallest correction (NOT applied)

1. Teach `_outcome_state` at `scripts/eod_learning/r4_bounce.py:23-47` to classify grader output:
   ```python
   if outcome.get("target_first") is True:  return "resolved_win"
   if outcome.get("stop_first")   is True:  return "resolved_loss"
   if outcome.get("horizon_bars_evaluated") and \
      outcome.get("target_first") is False and outcome.get("stop_first") is False:
       return "resolved_other"
   ```
2. Restrict the denominator to `state=ENTRY_ARMED` rows (or split the section into "gradeable ENTRY_ARMED / non-gradeable lifecycle rows") so `insufficient_inputs` doesn't dominate.
3. Pass the narrator's `--date` into `r4_bounce.render_markdown(day=…)` so the date offset matches the report header.

STOPPING BEFORE IMPLEMENTATION per operator instruction.

---

## §3 — Reconstructed 2026-09-24 bounce opportunities

Grouped by physical reversal event. `EXEC` = candidate_corpus row `executed=True`; `BLK` = `gate_allowed=False`; `SHADOW` = detector-only emission on a fully-disabled strategy.

| # | Time (UTC) | Physical event | BB_BOUNCE | LEVEL_BOUNCE | V2_PICK_BOUNCE | Other detectors | Fired | Realised | Block reason (for non-fires) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 05:15–06:05 | Asian-session drift low → bounce at ~13238 | 05:15 S BLK, 06:05 L **EXEC** (13238.7) | — | — | — | **BB_BOUNCE_L 06:05** BUY | **+8.10p** WIN, BB_FLIP exit | 05:15 S: entry_hours_blocked (session start 06:00) |
| 2 | 06:20–08:00 | Rally to 13247 → rejection | 06:20 S BLK, 08:00 S **EXEC** (13246.6) | — | — | — | **BB_BOUNCE_S 08:00** SELL | **+3.30p** WIN, QM_BAND_CLOSE_INSIDE | 06:20 S: ml_veto shadow_ok / gate reservation |
| 3 | 09:00–10:20 | Downdrift 13247→13217 | 09:00 L **EXEC** (13237.5), 10:35 L BLK (sl_block_active) | — | — | EMA_PB_S 09:15/09:35/09:40/10:05/10:20 all SHADOW (range_gate SUPPRESS, EMA_PB is off end-to-end); BRIEFING_S 10:30 BLK | **BB_BOUNCE_L 09:00** BUY | **-19.65p** LOSS, SL hit | 09:00 fired **into** the leg; 10:30 briefing shorts blocked by news_direction_off_route + one_book |
| 4 | 12:10–13:00 | Reversal off 13215 low | 12:10 L **EXEC** (13220.4, scale-out) | — | — | 12:10/12:15 BRIEFING_S BLK; 12:35 QM_V2 ENTRY_ARMED (short @13217.05, not executed by BB path — different detector) | **BB_BOUNCE_L 12:10** BUY | **+18.50p** WIN, QM_BAND_CLOSE_INSIDE | Briefing shorts blocked by news_direction_off_route + one_book cohere |
| 5 | 13:05–14:35 | Pop rejection at 13226 | 13:05 S **EXEC** (13226.0) | — | — | 13:30 QM_V2_VELOCITY_S BLK; 13:35/13:55/14:00 BRIEFING_S BLK | **BB_BOUNCE_S 13:05** SELL | **+10.60p** WIN, QM_BAND_CLOSE_INSIDE | Briefing shorts blocked (one_book cohere / ml_veto shadow) |
| 6 | 14:40–17:27 | Low bounce at ~13217 | 14:40 L **EXEC** (13217.7) | — | — | 14:40/14:55/15:00/16:25/16:30/17:35/17:40 BRIEFING_S BLK; 14:05 QM_V2_L BLK | **BB_BOUNCE_L 14:40** BUY | **+1.65p** WIN (BE hit) | Briefing shorts blocked (one_book cohere / ml_veto) |
| 7 | 18:10–19:55 | Late-session bounce at ~13213 | 18:10 L **EXEC** (13213.3, scale-out) | — | — | 18:40/18:55/19:00/19:10/19:15/19:20/19:25/19:30/20:25/20:30/20:35 BRIEFING_S BLK | **BB_BOUNCE_L 18:10** BUY | **+7.90p** WIN, QM_BAND_CLOSE_INSIDE | Briefing shorts blocked (one_book cohere / ml_veto) |

### 09:00 BB_BOUNCE BUY -19.65p — reconstruction

- Fire ts: 2026-09-24T09:00:05Z, entry 13237.5, SL 13217.5, TP1 13337.5.
- Direction context: after 08:00 BB_BOUNCE_S already won on the rejection at 13247, price kept dropping. The 09:00 fire went LONG into an active down-leg. Bar sequence: 09:00 open 13237.65 → 09:15 hit 13230.95 → 09:35 13229.55 → 09:40 13228.55 → 10:05 13224.75 → 10:20 13222.65 → SL @13217.85 filled 10:21:59. Pre-exit MFE 4.05p, MAE 15.05p (per signal_log).
- Market state at fire: `session_er` for the same detector cluster reads 0.205–0.344 (range_gate captures at 09:15/09:35/09:40/10:05/10:20 all suppress EMA_PB shorts on grounds `bb_w=27p, ER<=0.35`).
- LOI/QM state: 12:35 was the earliest ENTRY_ARMED QM zone of the day; at 09:00 no armed QM reversal existed. The 09:00 fire came from the BB pattern module (BB_BOUNCE_L cascade) not from QM/level authority.
- Gate decision on the fire: `mid_news_off_route`, `opposing_level_off`, `sl_block_ok`, `ml_veto:ml_veto:shadow_ok:no_features`, `gate:APPROVE_FINAL`. Nothing blocked it.
- Assessment: this was a false-bounce call — the pattern detector fired inside a continuing down-leg. No gate misapplication; the entry passed all live gates by design.

### 09:35 "blocked SHORT" — reconstruction

- Daily journal flag: `range_gate blocked SHORT at 2026-09-24T09:35:00+00:00 → price ran 15.3p within 60m`.
- Source: `logs/range_gate.jsonl` — the only 2026-09-24 rows are five EMA_PULLBACK shorts (09:15, 09:35, 09:40, 10:05, 10:20), all `verdict=SUPPRESS` with reason `ranging bb_w=…>=15p AND ER(10)<=0.35`.
- **Critical**: EMA_PULLBACK is fully OFF end-to-end (memory `project_ema_pb_armed_machine_live.md`, confirmed by wiring-audit §7 through 2026-09-14: master + armed ENABLED=0 + armed SHADOW=0). The range_gate is a **detect-mode-only telemetry** for a disabled strategy.
- Consequence: even if range_gate had approved, EMA_PULLBACK_S could not have fired. The daily-journal "blocked winner" flag is spurious for gating-decision purposes — no live route was suppressed. It represents a *research signal* about range_gate strictness on a shadow strategy, not a real capture opportunity foregone.

### Cross-family coverage on the same events

For every physical event above, only BB_BOUNCE has candidate emissions in `logs/candidate_corpus.jsonl` for GBPUSD 2026-09-24. LEVEL_BOUNCE produced zero rows all day. V2_PICK_BOUNCE produced two rows but both are EURUSD. QM_V2 produced one ENTRY_ARMED at 12:35 (short @13217.05) — the only cross-family emission, and it landed **between** BB events 4 and 5 with a price that would have been triggered by the subsequent BB_S fire's momentum. No apples-to-apples multi-family comparison is possible from the current corpus for 2026-09-24.

---

## §4 — Trade-management reconstruction (7 fills)

MFE/MAE derived from 5m candle archive (`data/candles/GBPUSD/2026-09-24.csv` + 09-25.csv). Post-exit excursion is measured from the exit price in the trade direction; positive = market kept going in your favour after exit, negative = it went against.

| # | Open (UTC) | Strategy | Dir | Entry | Exit | Reason (verbatim) | Realised | MFE (pre-exit) | MAE (pre-exit) | 30m post MFE/MAE | 60m post MFE/MAE | 120m post MFE/MAE | Pips left after exit | V2 state / rec |
|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 06:05:07 | GBPUSD_BB_BOUNCE_L | BUY | 13238.7 | 13246.8 | BB_FLIP | **+8.10p** | 11.95 | -5.85 | +2.15 / +7.35 | +2.15 / +7.55 | +9.40 / +7.55 | +9.40 | none — MISSING_ENTRY_TS |
| 2 | 08:00:06 | GBPUSD_BB_BOUNCE_S | SELL | 13246.6 | 13243.3 | QM_BAND_CLOSE_INSIDE | **+3.30p** | 8.45 | 8.65 | +13.05 / -0.45 | +17.05 / -0.45 | +29.05 / -0.45 | +29.05 | none — MISSING_ENTRY_TS |
| 3 | 09:00:05 | GBPUSD_BB_BOUNCE_L | BUY | 13237.5 | 13217.85 | SL hit | **-19.65p** | 4.05 | 22.95 | +11.40 / +3.60 | +13.10 / +3.60 | +14.70 / +3.60 | +14.70 (in same direction as trade, would have recovered) | none — MISSING_ENTRY_TS |
| 4 | 12:10:14 | GBPUSD_BB_BOUNCE_L | BUY | 13220.4 | 13231.2 | QM_BAND_CLOSE_INSIDE (scaled out) | **+18.50p** (partial 7.7p @12:55:55) | 13.75 | 5.35 | -0.85 / +14.95 | -0.85 / +14.95 | -0.85 / +20.65 | -0.85 (exited near peak) | none — MISSING_ENTRY_TS |
| 5 | 13:05:24 | GBPUSD_BB_BOUNCE_S | SELL | 13226.0 | 13215.4 | QM_BAND_CLOSE_INSIDE | **+10.60p** | 13.75 | 4.35 | +4.85 / +4.75 | +5.85 / +4.75 | +5.85 / +25.35 | +5.85 (short: extra continuation, then reversed) | none — MISSING_ENTRY_TS |
| 6 | 14:40:09 | GBPUSD_BB_BOUNCE_L | BUY | 13217.7 | 13219.35 | Breakeven stop hit (IG server-side) | **+1.65p** | 23.05 | 8.15 | +3.50 / +9.00 | +3.50 / +15.30 | +3.50 / +15.30 | +3.50 (bulk of the move captured pre-exit; BE gave back peak −19.55p vs MFE) | none — MISSING_ENTRY_TS |
| 7 | 18:10:05 | GBPUSD_BB_BOUNCE_L | BUY | 13213.3 | 13219.0 | QM_BAND_CLOSE_INSIDE (scaled out) | **+7.90p** (partial 2.2p @19:01:43) | 9.35 | 2.05 | +2.05 / +7.85 | +3.00 / +7.85 | +4.20 / +9.90 | +4.20 | none — MISSING_ENTRY_TS |

**V2 STATE/RECOMMENDATION** column intentionally reads "none — MISSING_ENTRY_TS" for every row. Every corresponding TM_OBSERVATION row for these deals (33+21+18+11+10+8 = 101 rows across 6 of the 7 deals; the 06:05 fill closed at 06:20 before a 5-min sweep) has `tm_v2_evaluated=False`, `tm_v2_skip_reason=MISSING_ENTRY_TS`, `tm_v2_recommendation=None`, `current_pnl_pips=None`. No hypothetical V2 recommendation has been fabricated.

Notable trade-management observations (measured, not inferred):
- Trade 3 (loss): exit at SL 13217.85 was the day's near-low; over the next 30–120m the market retraced +11.4→+14.7 pips **in the trade's direction**. i.e. the LONG was right in the medium term but was liquidated at the exact wrong bar.
- Trade 6 (BE): pre-exit MFE 23.05p vs realised 1.65p — largest give-back of the day (−21.4p vs peak). Move continued only +3.50p over the next 2h so BE was near-optimal in hindsight.
- Trade 2 (+3.3p): +29.05p continuation available in the same direction over the following 120m — largest post-exit leave-on-table of the day.
- Trades 4 and 7 exited very close to their local peaks (−0.85 and +4.20 post-exit peaks) — QM_BAND_CLOSE_INSIDE fired at a good moment.
- Trade 5 (short): after +10.6p exit, price continued only +5.85p then reversed +25.35p against the direction — exit protected against a large reversal.

---

## §5 — Final ruling

- **EOD_CAN_MEASURE_TRADE_MANAGEMENT_EFFECTIVENESS = NO** — 0/101 comparable rows. Root cause: `tm_corpus_writer._derive_causal_position_features` rejects the UNIX-epoch `open_time` stored on `trade_executor.EPIC_STATE` (`_STATE_TEMPLATE.open_time` is populated by `time.time()`, never converted to ISO). Same class of contract mismatch as the 2026-09-24 C7 pair fix; the same review pass missed `open_time`.
- **EOD_CAN_COMPARE_BOUNCE_FAMILY_EFFECTIVENESS = NO** — two independent defects: (a) `r4_bounce._outcome_state` does not read the grader's `target_first`/`stop_first`/`mfe_pips` output, so all 30 fully-graded rows fall through to `pending`; (b) 571 rows are non-ENTRY_ARMED lifecycle states that are structurally un-gradeable as trades but still counted in the denominator; (c) latent — `r4_bounce.render_markdown` ignores the narrator's `--date`, and LEVEL_BOUNCE + V2_PICK_BOUNCE detectors produced no GBPUSD candidates on 2026-09-24 so cross-family comparison isn't answerable from today's streams even after the classifier is fixed.
- **MEASUREMENT_DEFECT_FOUND = YES** (two writer/reader defects, described in §1 and §2; the smallest corrections are documented, none applied).
- **TRADING_DEFECT_PROVEN = NO** — all 7 fills executed as expected; the 09:00 loss was a false-bounce pattern call inside an active down-leg (all gates approved by design); the "blocked SHORT winner" at 09:35 is a range_gate suppression of a detect-only EMA_PULLBACK candidate on a strategy that is fully OFF end-to-end (memory `project_ema_pb_armed_machine_live.md`). No live route was suppressed and no capture opportunity was foregone.
- **CODE_CHANGE_REQUIRED = YES** — three minimal fixes localized to the reporting/instrumentation seams (writer accept-epoch, classifier + denominator, propagate `--date`). Trading modules unchanged.
- **TRADING_BEHAVIOUR_CHANGE_REQUIRED = NO.**

STOPPING before any implementation, per operator instruction.
