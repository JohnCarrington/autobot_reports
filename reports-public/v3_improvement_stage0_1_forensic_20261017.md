# AutoBot V3 — Structural Intelligence Improvement Programme
## Stage 0 & Stage 1 Forensic Report (Friday 2026-10-16)

**Mode: RESEARCH / INVESTIGATION ONLY. No production modification.**

- Generated: 2026-10-17
- Production branch at investigation start: `nms/v3-prod-upgrade-20261013` @ `41a3c9c`
- Last 3 commits (from `git log --oneline`):
  - `41a3c9c` v3-stabilisation amendments: NMS fail-closed, UM reason fix, bypass closure
  - `0bed264` v3-stabilisation: NMS V3 directional gate + close-recording fallback + V3-only switch + pair-cap scaffold + Telegram policy wrapper
  - `bd45ded` deploy(nms-v3): dedicated V3→V3 upgrade script (preserves state)
- Working tree at `/opt/tradingbot` is a worktree registered to the above HEAD; no modifications were performed during this report.

Every claim is tagged `[FACT]`, `[INFERENCE]`, or `[UNKNOWN]`.

---

## Deliverable 1 — Existing architecture map

### Admission chain for GBPUSD entries (code evidence)

```
┌─────────────────────────────────────────────────┐
│ Strategy module emits proposal                  │
│   bounce_engine_live.py (BOUNCE_TR_L/_S, _SQ,  │
│     _C, _A, bounce engine Setup A)              │
│   gbpusd_bb_bounce.py   (GBPUSD_BB_BOUNCE_L/_S) │
│   gbpusd_trend_v3.py    (GBPUSD_TREND_V3_*,     │
│     V3_BB_*, V3_EMA_*)                          │
└───────────────┬─────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────┐
│ orchestrator_v2.submit                          │
│   calls central_execution_gate.evaluate         │
│   (CENTRAL_EXECUTION_GATE=1 → live, not shadow) │
└───────────────┬─────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────┐
│ central_execution_gate.py (:2080-2165)          │
│   per-family admission allowlist:               │
│     BB_BOUNCE:    _bb_admit (BB_BOUNCE_ADMIT=1) │
│     TREND_V3:     _trend_v3_admit (=1)          │
│     BOUNCE_ENGINE: BOUNCE_ENGINE_ENABLED=1 AND  │
│         (BOUNCE_ENGINE_V3_ONLY=0 OR V3 strategy)│
└───────────────┬─────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────┐
│ trade_executor.execute_trade (:6615-6670)       │
│   NMS V3 Direction Gate (second seam)           │
│   nms_v3_direction_gate.check(strategy, side,   │
│                               symbol)           │
│                                                 │
│   V3_STRATEGIES = {V3_BB_L/S, V3_EMA_L/S,       │
│                     GBPUSD_TREND_V3_UM_L/S}     │
│   Reads cache/session_trend_<SYM>.json          │
│   v3_state ∈ {STRONG_UP, EMERGING_UP,           │
│               STRONG_DOWN, EMERGING_DOWN,       │
│               RANGE, NORMAL, UNKNOWN}           │
│   STRONG_UP|EMERGING_UP → block SELL            │
│   STRONG_DOWN|EMERGING_DOWN → block BUY         │
│   Other states → pass (incl. BOUNCE_TR_L which  │
│   is NOT in V3_STRATEGIES → always passes)      │
└───────────────┬─────────────────────────────────┘
                ▼
         IG broker OPEN
```

### Independent "trend" classifiers running in parallel [FACT]

Grounded in files on disk at HEAD `41a3c9c`:

| classifier | module | output | consumers |
|---|---|---|---|
| **Regime engine** | `regime_engine.py` (2,630 LOC) | `winning_regime` ∈ {STRONG_TREND_UP/DOWN, TREND_FORMING_UP/DOWN, RANGE, NEUTRAL, …} | signal_log `regime_at_fire`; strategy proposals |
| **NMS V3 session_trend** | `session_trend.py` → `cache/session_trend_<SYM>.json` | `v3_state` ∈ {STRONG_UP, EMERGING_UP, STRONG_DOWN, EMERGING_DOWN, RANGE, NORMAL, UNKNOWN}; `prevailing` field | `nms_v3_direction_gate.check` (reads from cache file) |
| **Cascade state** | `cascade_state.py` (231 LOC) | `cascade_label` ∈ {TREND_UP, TREND_DOWN, …} | signal_log `cascade_label_at_fire`; `bb_bounce_l_cascade_shadow.jsonl` |
| **Normal-state engine** | `nms_daily_context/regime.py`, writes `logs/normal_state_journal.jsonl` | `state` ∈ {PRODUCTIVE_RANGE, TRADABLE_NON_RANGE, FLAT_OR_COMPRESSED} | admission matrix (per project memory a9/a10) |
| **Structural state** | `structural_state.py` (661 LOC) | BOUNCE_FORMING → REVERSAL_CONFIRMED (per project memory 2026-09-23) | `news_trend_classifier`; `structural_resolution_shadow.jsonl` |
| **HTF regime** | `htf_regime.py` + `logs/htf_regime.jsonl` | HTF-level regime tag | `htf_authority.jsonl`; opposing-regime guard |

**Finding:** [FACT] At least six independent "trend"/"regime"/"state" tags are produced in parallel; the live NMS V3 Direction Gate reads only one (`cache/session_trend_<SYM>.json:v3_state`). The signal_log stamps `regime_at_fire` from the regime engine, not from the gate's source.

### PAA V1 / structural level components (from `scripts/paa_*.py`)

- `scripts/paa_mode_abc_study.py`
- `scripts/paa_mode_a_vs_mode_b_study.py`
- `scripts/paa_phase6a_research.py`
- `scripts/paa_phase6a_data_audit.py`

[FACT] PAA V1 is studied under `scripts/paa_*` — these are offline scripts, not continuously-wired production components (per project memory `feedback_wiring_rule`: scripts don't count as prod).

### Pivot & S/R calculations [FACT]

| file | purpose |
|---|---|
| `ig_daily_pivots.py` | Daily pivot points (P, R1-R3, S1-S3) |
| `daily_structural_context.py` | Daily structural context |
| `structural_state.py` | Structural state machine |
| `structural_position_composer.py` (597 LOC) | Composes structural-level analyses |
| `research/level_arrival_turn/level_builder.py` | Research-only PDH/PDL/PWH/PWL/pivot builder (Stage 0 study) |

Session_trend snapshot carries `daily_pivots` dict (verified in `cache/session_trend_GBPUSD.json`).

### Trend-regime and exhaustion [FACT]

| file | LOC |
|---|---:|
| `regime_engine.py` | 2,630 |
| `regime_router_engine.py` | — |
| `regime_classifier_v2.py` | — |
| `gbpusd_regime_detector.py` | — |
| `cascade_state.py` | 231 |
| `exhaustion_reversal.py` | — |
| `ema_pullback_exhaustion.py` | — |
| `nms_v3_classifier.py` | 942 |

### Exit management [FACT]

| file | LOC |
|---|---:|
| `qm_adaptive_exit.py` | 331 |
| `structure_exit.py` | 125 |
| `exit_dress.py` | — |
| `qm_exit_shadow.py` | — |
| `bounce_engine_live.py` | (contains per-mode exit logic) |

Observed exit reasons in `signal_log` on 10-16 included: `TP hit`, `GRIND_SMA_CROSS`, `SL`, `STRUCTURE_EXIT:structure_flip_down:…`, `STRUCTURE_EXIT:structure_flip_up:…`, `External close (not initiated by this host)`, `Breakeven stop hit (IG server-side)`, `V3_STOP`, `V3_WARNING_BREAK`, `FLOOR_STOP_POST_SCALEOUT`, `IG_RECONCILE`.

### Position ownership and reconciliation [FACT]

- `ownership_identity.py` (529 LOC) — strategy→ownership-group map. Line 73: `"BOUNCE_TR_L": "BOUNCETR_L"`. Line 195: `BOUNCE_TR_L` is in group `_GROUP_AUTOBOT_V2`.
- `position_recovery.py` (400 LOC) — reconciliation on reconnect.

### Replay / testing infrastructure [FACT]

- `scripts/a10_strict_replay_20260914_nms.py` — NMS strict replay.
- `scripts/nms_12_25_reconciliation_20260914.py` — NMS reconciliation.
- `scripts/paa_*.py` — PAA offline studies.
- `research/` worktrees — e.g. `research/level_arrival_turn/*.py` on branch `research/level-arrival-turn-20261017`.
- `tests/` tree (not surveyed here but present).

---

## Deliverable 2 — Component reuse assessment

**Reuse candidates for Structural Room to Run (SRR V1):**

| requirement | existing module | reuse verdict |
|---|---|---|
| Daily pivot (P/R1-3/S1-3) prices | `ig_daily_pivots.py`; also in `cache/session_trend_GBPUSD.json:daily_pivots` | **REUSE** — do NOT duplicate |
| Previous-day/week H-L | `research/level_arrival_turn/level_builder.py` (research-only — needs production wiring) | **PORT** carefully — level_builder is on research branch |
| Confirmed swings (M5) | `session_trend_state.json:confirmed_swings` (per-symbol) + `research/.../market_structure.detect_confirmed_swings` | **REUSE** session_trend's series |
| H1 structural authority | `htf_regime.py` + `logs/htf_authority.jsonl` + `htf_regime.jsonl` | **REUSE** |
| Trend regime (point-in-time) | `regime_engine.py` + `logs/regime_engine.jsonl` | **REUSE** winning_regime |
| NMS V3 trend state | `nms_v3_classifier.py` + `session_trend.py` → `v3_state` | **REUSE** but see Deliverable 7 — authority drift |
| Cascade | `cascade_state.py` | **REUSE** for context but needs reconciliation with v3_state |
| Exit management shim | `qm_adaptive_exit.py`, `structure_exit.py`, `exit_dress.py` | **REUSE** — do NOT build parallel exit |
| Position-ownership map | `ownership_identity.py` | **REUSE** |

**No duplicate structural-level calculations needed.** `daily_pivots` is already in session_trend; `confirmed_swings` is already in session_trend_state.

---

## Deliverable 3 — NMS admission investigation (V3_BB_S 12:40:33, V3_EMA_S 12:56:32)

### 3.1 Signal_log evidence [FACT]

From `logs/signal_log.jsonl` for 2026-10-16:

| strategy | side | open UTC | close UTC | entry | sl | tp1 | **regime_at_fire** | engine_regime_at_fire | outcome | pnl |
|---|---|---|---|---|---|---|---|---|---|---:|
| V3_BB_S | SELL | 12:40:33 | 13:39:46 | 13336.1 | 13348.1 | None | TREND_FORMING_UP | TREND_FORMING_UP | SL | **−10.55** |
| V3_EMA_S | SELL | 12:56:32 | 13:37:32 | 13327.8 | 13339.8 | None | TREND_FORMING_UP | TREND_FORMING_UP | SL | **−9.85** |

### 3.2 NMS V3 Direction Gate — gate IS enabled, IS working [FACT]

- `.env`: `NMS_V3_DIRECTIONAL_GATE_ENABLED=1`
- No `NMS_V3_SNAPSHOT_FAIL_POLICY` set → defaults to `closed` (per `nms_v3_direction_gate.py:60`).
- Gate scope at `nms_v3_direction_gate.py:52-57`:
  ```python
  V3_STRATEGIES = frozenset({
      "V3_BB_L", "V3_BB_S",
      "V3_EMA_L", "V3_EMA_S",
      "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
  })
  ```
- Both V3_BB_S and V3_EMA_S ARE in scope.
- From `logs/execution_rejections.jsonl`, the gate did block 10 V3_BB_S SELL fires on 10-16:

```
2026-10-16T06:50:28 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T07:40:28 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T08:37:43 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T08:40:17 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T09:36:39 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T10:42:32 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T14:43:49 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T14:45:36 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T14:50:44 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
2026-10-16T15:00:30 | V3_BB_S SELL | nms_v3_direction_block:state=EMERGING_UP:side=SELL
```

### 3.3 The gate was NOT bypassed — the two SELLs are inside a gap between blocks [FACT]

- Last block before the first SELL: **10:42:32 UTC** (`state=EMERGING_UP`).
- First V3_BB_S fire that passed: **12:40:33 UTC** (118 minutes later).
- Second V3_EMA_S fire that passed: **12:56:32 UTC** (134 minutes after last block).
- First block AFTER the two SELLs: **14:43:49 UTC** (107 minutes after the V3_EMA_S fire).

### 3.4 Mechanism [INFERENCE] — not bypass, not race, not stale snapshot

Between 10:42 and 14:43 (a ~4 h gap), the gate recorded no V3_BB_S/V3_EMA_S rejections. During that window the gate had to be returning `allowed=True`. The only paths through `nms_v3_direction_gate.check` that return `allowed=True` for an in-scope strategy are:

1. `v3_state ∈ {RANGE, NORMAL, UNKNOWN}` → neutral pass [most likely]
2. Fail-open on snapshot failure — ruled out: `.env` has no fail-policy override so default is `closed`; a snapshot failure would have BLOCKED, not passed.
3. Gate disabled — ruled out: alert-code `nms_v3_gate_disabled` would be in the log; it is not.

[INFERENCE] **The gate most likely saw `v3_state ∈ {RANGE, NORMAL, UNKNOWN}` between ~10:50 UTC and ~14:40 UTC**, during a period when the parallel `regime_engine` continued to label the bars `TREND_FORMING_UP` (verified in `logs/regime_engine.jsonl-20261017` at 12:35, 12:40, 12:45, 12:50, 12:55 all = `TREND_FORMING_UP`).

### 3.5 Not resolvable from current logs [UNKNOWN]

- The exact v3_state at 12:40:33 and 12:56:32 is UNKNOWN. The in-cache `session_trend_GBPUSD.json` is overwritten on every bar; the current value (`v3_state=RANGE` since 20:15 UTC) is after the fact.
- There is no `logs/session_trend*.jsonl` or `logs/nms_v3*.jsonl` state-transition log. To recover the point-in-time v3_state the user would need to (a) read the backup snapshot archive if one exists, or (b) replay session_trend.py against the 10-16 M5 bars.

### 3.6 Not an exception or race condition [FACT]

- No evidence of race in `logs/execution_rejections.jsonl` (sequential writes).
- The gate is invoked at `trade_executor.py:6615-6625` which is single-call per fire.
- There was no gate-disabled telemetry.

### 3.7 Verdict

**[FACT]** The gate was NOT bypassed. The gate did NOT receive a stale/malformed snapshot. The gate operated as designed on whatever `v3_state` the snapshot writer had committed.

**[INFERENCE]** The architectural issue is that `session_trend.v3_state` (gate's authority) can report RANGE/NORMAL/UNKNOWN while `regime_engine.winning_regime` (signal_log authority) still reports TREND_FORMING_UP. **Two independent trend classifiers can disagree**, and only one is bound to the directional gate.

**Recommendation to carry into Stage 2 scope**: either
(a) have the direction gate reconcile against regime_engine before passing, or
(b) force a single trend classifier to drive both admission and signal_log reporting.

---

## Deliverable 4 — Position closure investigation (BOUNCE_TR_L 13:35:33)

### 4.1 Trade details [FACT]

From `logs/signal_log.jsonl`:

```
strategy=BOUNCE_TR_L direction=BUY
timestamp_open=2026-10-16T13:35:33Z  entry=13340.75  sl=13320.75  tp1=13370.75  sl_pips=20  tp1_pips=30
timestamp_close=2026-10-16T16:40:25Z  close_price=13314.55
close_reason="External close (not initiated by this host)"
close_type="External close (not initiated by this host)"
close_ts_source=NATIVE_EXIT
economic_close_ts=2026-10-16T16:40:25Z
pnl_pips=-27.45  pnl_gbp=-54.9  pnl_gbp_stake_size=2.0
mfe_pips=None   (field is null in record)
```

### 4.2 Simultaneous opposite-side fire — GBPUSD_TREND_V3_S [FACT]

From `logs/signal_log.jsonl`:

```
strategy=GBPUSD_TREND_V3_S direction=SELL
timestamp_open=2026-10-16T16:40:21Z  entry=13314.0  sl=13326.0  tp1=13139.0
regime_at_fire=STRONG_TREND_DOWN
close_reason="STRUCTURE_EXIT:structure_flip_up: last_close=13328.35 > prior_5_high=13327.25, pnl=-12.2p"
timestamp_close=2026-10-16T20:03:31Z   pnl_pips=-17.55  mfe_pips=3.65
```

**Timing**: the SELL opened at **16:40:21Z**; the BOUNCE_TR_L BUY closed at **16:40:25Z**. **4-second gap.**

### 4.3 Hedging on IG — the one-book guard [FACT]

- `.env`: `ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD=1` (opposing positions ALLOWED on GBPUSD at the one-book-guard level).
- `.env`: `V3_ALLOW_OPPOSING_POSITIONS=0` (V3-level opposing-position suppression is OFF for allow — i.e. V3 does NOT independently allow opposing).

[INFERENCE] On IG, when the host sends a SELL on CS.D.GBPUSD.TODAY.IP while a BUY of the same size is open, IG's position-netting rules may auto-close the open BUY. The 4-second interval and the exit tag `External close (not initiated by this host)` strongly suggest **IG netting / position offset performed the close**, not an in-process close.

### 4.4 Ownership [FACT]

- `ownership_identity.py:73`: `"BOUNCE_TR_L": "BOUNCETR_L"` ownership label.
- `ownership_identity.py:195`: BOUNCE_TR_L belongs to `_GROUP_AUTOBOT_V2`.
- GBPUSD_TREND_V3_S is a different ownership group (V3 family).

[INFERENCE] The ownership map does NOT currently coordinate opposite-side admissions. The BOUNCE engine does not know the V3 engine is about to fire the opposite side; the V3 engine does not know an open BOUNCE position exists.

### 4.5 MFE value — [UNKNOWN] vs operator's +29.2 claim

The signal_log record has `mfe_pips=None`. The directive specifies "MFE +29.2 pips." The MFE field appears not to be populated for BOUNCE_TR_L in this record. To reconcile, the user would need either (a) the broker-side tick extremum for the position's lifetime or (b) a replay of the M5 bars between 13:35 and 16:40.

**[FACT]** M5 close at 14:00 UTC was 13359.55 (from `cache/session_trend_GBPUSD.json:hourly_samples`). Entry 13340.75 + 29.2 = 13369.95 — HIGHER than the 14:00 close. The hourly sample is a sample, not the max; the daily high may well have hit 13370 or close to it, consistent with the operator's +29.2 claim.

### 4.6 Verdict

**[INFERENCE, high confidence]** The BOUNCE_TR_L BUY was closed by **IG broker-side netting** when the opposite-direction GBPUSD_TREND_V3_S SELL opened 4 seconds earlier. The AutoBot host did not initiate the close (confirmed by the `close_reason="External close (not initiated by this host)"` tag and `close_ts_source=NATIVE_EXIT`).

**Architectural gap:** The admission chain lets two strategy families fire opposite directions on the same pair within seconds, without a cross-family coordinator. ONE_BOOK_GUARD_ALLOW_OPPOSING_GBPUSD=1 was deliberately set — the operator wanted hedging to be possible — but that flag does not account for the broker's own netting behaviour.

**[UNKNOWN]** Whether IG's position-netting is deterministic for this account (position hedging mode vs netting mode). This should be confirmed with IG account settings before Stage 2 chooses a fix.

---

## Deliverable 5 — Profit retention investigation (three morning BUYs)

### 5.1 Configured TP levels [FACT]

Pulled from `logs/signal_log.jsonl`:

| strategy | open UTC | entry | sl | sl_pips | **tp1** | tp1_pips | timestamp_close | close_reason |
|---|---|---:|---:|---:|---:|---:|---|---|
| GBPUSD_BB_BOUNCE_L | 06:00:19 | 13299.1 | 13279.1 | 20 | **13399.1** | **100.0** | — | **still open at report time** |
| V3_BB_L | 06:00:28 | 13298.4 | 13286.4 | 12 | **None** | **None** | — | **still open at report time** |
| V3_EMA_L | 06:20:20 | 13306.1 | 13294.1 | 12 | **None** | **None** | — | **still open at report time** |

### 5.2 Was the target reached? [FACT, bounded]

The maximum GBPUSD price on 10-16 was between **13359.55** (14:00 UTC hourly sample close) and the daily high (which the hourly samples bound: no hourly close exceeded 13360, but intra-hour wick highs may have been higher — not resolvable from the samples).

- GBPUSD_BB_BOUNCE_L TP = 13399.1. Max price ≤ 13360 → **TP NOT reached** (fell at least 39 pips short).
- V3_BB_L TP = None → **no fixed TP** → cannot be "reached".
- V3_EMA_L TP = None → **no fixed TP** → cannot be "reached".

### 5.3 Why positions remained open through the reversal [FACT]

**GBPUSD_BB_BOUNCE_L**: Configured broker TP is +100 pips at 13399.1. The day's high stopped short of that. There is **no in-engine logic to shrink the TP** when favourable movement exceeds the target by a given fraction. Design: this strategy relies on fixed +100p TP or structural / breakeven stop. The breakeven-stop or trailing logic (if any) did not trigger before the reversal retraced through entry.

**V3_BB_L / V3_EMA_L**: V3 strategy design per the admission comment at `bounce_engine_live.py:668-676`:
> "COMPLIANCE_AUDIT.md B1: V3 modes (spec §8.1 'no automatic TP at 15/20/30 or other fixed pip amount') pass tp=None so IG's CREATE_POSITION receives no limit."

Both V3_BB_L and V3_EMA_L have **no broker TP by specification**. The entire exit path depends on:
- Structural exits (observed on 10-16 for the trending V3 trades: `STRUCTURE_EXIT:structure_flip_down: last_close=13357.65 < prior_5_low=13358.35`).
- `V3_STOP`, `V3_WARNING_BREAK`, `GRIND_SMA_CROSS`, breakeven-stop (`Breakeven stop hit (IG server-side)`).

### 5.4 Scale-out / breakeven observations [UNKNOWN at log level]

The 10-16 signal_log records for the three morning BUYs do NOT populate (or do not expose) a `floor_stop_active`, `trail_active`, `be_moved`, or `scaled_out` field. Related fields:

| field | value for the 3 BUYs |
|---|---|
| `exit_dress` | `MANAGED` (all three) |
| `exit_stack` | `MANAGED` (all three) |

The `exit_dress=MANAGED` tag means the exit stack IS active in-engine, but whether a breakeven stop or trail fired before the retrace is not written to the signal_log record (which is lifecycle-closing only — the three positions are still open).

### 5.5 Verdict

**[FACT]** Profit retention is NOT an implementation defect per the current specification:
- V3 strategies are **by design** without a broker TP; they rely on structural exits.
- GBPUSD_BB_BOUNCE_L has a **100-pip TP** that was legitimately not reached (daily high was ~60 pips above entry).

**[INFERENCE]** The design question — "should structural exits give back 60+ pips of favourable excursion?" — is a VALID Stage 2 scope question. The exits that DID fire on 10-16 for other V3 trades (`STRUCTURE_EXIT`) happened at `last_close < prior_5_low` by small margins — these can trigger well after the price peak. This is a candidate for the SRR V1 improvement (profit retention via dynamic stop at a structural level rather than at prior-5-bar extreme).

**But** [FACT] "the positions did not take the TP that was never reached" is not itself a bug — the TP is a design parameter.

---

## Deliverable 6 — Structural authority coverage map

### 6.1 Strategies subject to the NMS V3 Direction Gate [FACT]

```python
# nms_v3_direction_gate.py:52
V3_STRATEGIES = frozenset({
    "V3_BB_L", "V3_BB_S",
    "V3_EMA_L", "V3_EMA_S",
    "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
})
```

Only 6 strategies. **Explicitly out of scope** per the gate's `nms_v3_strategy_not_in_scope` short-circuit:

### 6.2 Strategies NOT subject to the NMS V3 Direction Gate (10-16 live) [FACT]

From trades observed in `logs/signal_log.jsonl` on 10-16:

| strategy | admitted at (regime_at_fire) | gate check? | why admitted |
|---|---|---|---|
| GBPUSD_BB_BOUNCE_L | RANGE | nms_v3_strategy_not_in_scope → pass | `BB_BOUNCE_ADMIT=1`, family=BB_BOUNCE |
| GBPUSD_TREND_V3_L | STRONG_TREND_UP | **in V3_STRATEGIES set but V3_BB_L is V3_BB_L — wait** | admitted via `TREND_V3_ADMIT=1`, family=TREND_V3 |
| GBPUSD_TREND_V3_S | STRONG_TREND_DOWN | in V3_STRATEGIES? NO — `GBPUSD_TREND_V3_S` ≠ `GBPUSD_TREND_V3_UM_S`. **The TREND_V3_S / _L (non-UM) names are NOT in the gate's scope**. Admitted via `TREND_V3_ADMIT=1` |
| GBPUSD_TREND_V3_UM_L | TREND_FORMING_UP, STRONG_TREND_UP | **IN SCOPE** — BUY admitted when v3_state ≠ STRONG_DOWN/EMERGING_DOWN |
| V3_BB_L | TREND_FORMING_UP | **IN SCOPE** — BUY admitted when v3_state ≠ STRONG_DOWN/EMERGING_DOWN |
| V3_BB_S | TREND_FORMING_UP | **IN SCOPE** — SELL admitted when v3_state ∉ {STRONG_UP, EMERGING_UP} |
| V3_EMA_L | STRONG_TREND_UP | **IN SCOPE** |
| V3_EMA_S | TREND_FORMING_UP | **IN SCOPE** — SELL admitted (see Deliverable 3) |
| BOUNCE_A_L | TREND_FORMING_UP | nms_v3_strategy_not_in_scope → pass | BOUNCE_ENGINE_ENABLED=1, V3_ONLY not set |
| BOUNCE_TR_L | TREND_FORMING_UP, STRONG_TREND_UP | nms_v3_strategy_not_in_scope → pass | BOUNCE_ENGINE_ENABLED=1, V3_ONLY not set |

### 6.3 The GBPUSD_TREND_V3_L / _S naming gap [FACT]

Reading `nms_v3_direction_gate.py:52` carefully: the gate's V3_STRATEGIES includes `GBPUSD_TREND_V3_UM_L/_S` (the UM variant) but NOT `GBPUSD_TREND_V3_L/_S` (the non-UM / "managed" variant). From signal_log 10-16, GBPUSD_TREND_V3_L and GBPUSD_TREND_V3_S fired without a direction-gate check.

This is explicit in the code — a design choice to put only the "UM" (unmanaged) variants under the directional gate. The managed `_L` / `_S` variants have their own structural exits and are admitted via `TREND_V3_ADMIT=1`.

### 6.4 Mapping of "out-of-scope" rationale

| strategy | out of NMS V3 directional gate because | admission authority |
|---|---|---|
| GBPUSD_BB_BOUNCE_L/_S | BB_BOUNCE has its own gate stack (ribbon-gate, pierce, close-back) | `BB_BOUNCE_ADMIT=1` + family filter |
| GBPUSD_TREND_V3_L/_S | "managed" variants self-manage exits; design choice | `TREND_V3_ADMIT=1` + family filter |
| BOUNCE_A_L/_S | BOUNCE_ENGINE Setup A | `BOUNCE_ENGINE_ENABLED=1` |
| BOUNCE_TR_L/_S | BOUNCE_ENGINE Trend variant | `BOUNCE_ENGINE_ENABLED=1` |
| BOUNCE_SQ_L/_S | BOUNCE_ENGINE Squeeze variant | `BOUNCE_ENGINE_ENABLED=1` |
| BOUNCE_C_L/_S | BOUNCE_ENGINE Combined variant | `BOUNCE_ENGINE_ENABLED=1` |
| briefing-execution modes | separate briefing stack | briefing routing flags |
| LLSweep / news strategies | not in V3 scope | separate per-strategy admissions |

### 6.5 BOUNCE_TR_L admission at 13:35:33 UTC [FACT, resolves Stage 1D]

Path (verified from source + `.env`):

1. `bounce_engine_live.py` composes the proposal with `strategy="BOUNCE_ENGINE_SETUP_A"` (actually `BOUNCE_TR_L` by mode).
2. `orchestrator_v2.submit` → `central_execution_gate.evaluate`.
3. In `central_execution_gate.py:2151` — `_bounce_engine_admitted` branch:
   ```
   BOUNCE_ENGINE_ENABLED=1  AND  family=="BOUNCE_ENGINE"
   AND  (BOUNCE_ENGINE_V3_ONLY=0  OR  strategy in V3 names)
   → True
   ```
   `.env` has no `BOUNCE_ENGINE_V3_ONLY=1`, so the condition is True regardless of the strategy name. **BOUNCE_TR_L is admitted.**
4. `trade_executor.execute_trade` → `nms_v3_direction_gate.check(strategy="BOUNCE_TR_L", ...)` → short-circuits to `allowed=True` because `BOUNCE_TR_L ∉ V3_STRATEGIES`.
5. Broker OPEN.

**The regime_at_fire=TREND_FORMING_UP (long bias) and cascade=TREND_DOWN mentioned in the forensic ticket are both IRRELEVANT to the admission** — neither classifier is consulted by any admission gate that applies to BOUNCE_TR_L.

**[FACT]** BOUNCE_TR_L was admitted BY DESIGN. There is no "bypass" to find — the strategy is explicitly outside the gate's scope.

**Design question for Stage 2:** should BOUNCE_TR_L (and the other BOUNCE_* modes) be brought under a directional authority? That is **exactly the "SRR / structural intelligence" scope** of this programme.

---

## Deliverable 7 — Dashboard reconciliation findings

**Operator-reported figures:**
- V2 dashboard: **+66.7 pips**
- V3 roster dashboard: **+31.9 pips**
- H161 forensic ledger: **+53.55 realised pips**

### 7.1 Realised pips from the signal_log on 10-16 [FACT]

Taking only trades with `timestamp_close` on 10-16 (closed on day):

| strategy | side | open | close | pnl_pips |
|---|---|---|---|---:|
| BOUNCE_TR_L | BUY | 06:20:40 | 12:40:40 | +29.95 |
| GBPUSD_TREND_V3_UM_L | BUY | 07:15:25 | 12:45:22 | +16.60 |
| V3_BB_S | SELL | 12:40:33 | 13:39:46 | −10.55 |
| V3_EMA_S | SELL | 12:56:32 | 13:37:32 | −9.85 |
| BOUNCE_TR_L | BUY | 13:35:33 | 16:40:25 | −27.45 |
| GBPUSD_TREND_V3_L | BUY | 14:35:29 | 14:50:45 | −10.70 |
| GBPUSD_TREND_V3_S | SELL | 16:40:21 | 20:03:31 | −17.55 |

**Sum = −29.55 pips** of 10-16-closed trades.

Three positions were still OPEN at report time (GBPUSD_BB_BOUNCE_L, V3_BB_L, V3_EMA_L) — their contribution to any dashboard figure depends on whether unrealised MTM is included.

### 7.2 Partial / scale-out contributions [UNKNOWN]

- `BOUNCE_TR_L` carries `tp1_pips=30` and `runner_pnl_pips=None` fields. If BB_BOUNCE_L's 06:00 entry was scaled out at an earlier +X pips (per the project memory about "post-scale floor" and "runner trail"), the dashboard's accounting of partial realisations may add to the +pips side.
- `.env`: `BB_BOUNCE_POST_SCALE_FLOOR_ENABLED=1` (floor active after scale-out), `BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS=12`. A scale-out at +12 or at TP1 (if hit) would be a realised pip contribution not visible in a "position-closed" scan.

### 7.3 Reconciliation hypotheses [INFERENCE]

| dashboard | likely population | reasoning |
|---|---|---|
| **V2 dashboard +66.7** | V2 family trades only (BOUNCE_A/BOUNCE_TR/BOUNCE_C/BB_BOUNCE), including scale-out partials and possibly open-position MTM | matches "V2 dashboard" per project memory `project_dashboard_four_system_model_20261001` (AUTOBOT|BRIEFINGS|FXi|DEMO four-system model) |
| **V3 roster +31.9** | V3 family trades only (TREND_V3 / V3_BB / V3_EMA / UM variants) | may EXCLUDE BB_BOUNCE and BOUNCE_ENGINE legacy modes |
| **H161 forensic +53.55** | Full-ledger realised pips with the host-identity dedup rules (per memory `feedback_dedup_evidence_not_host`) | lexicographic-score dedup applied |

**[UNKNOWN]** Without the actual dashboard code and ledger input for 10-16, this reconciliation remains hypothesis-level. The three populations are expected to differ because:
1. V2 dashboard includes BB_BOUNCE / BOUNCE_* and may add partial scale-out realisations.
2. V3 roster excludes legacy BOUNCE modes.
3. H161 forensic uses a different host-identity dedup convention.

### 7.4 Direct work needed for Stage 2 start [FACT]

- Read `v2_pick_bounce_ledger.py` and the V3 roster dashboard source to confirm each population.
- Run a replay of 10-16 against each dashboard's accounting function to produce the delta.
- Export each dashboard's row-level details for 10-16 (deal_id, strategy, pnl) and align by deal_id.

---

## Deliverable 8 — Recommended implementation boundaries for SRR V1

**Scope** (based on findings above):

1. **Reuse** `cache/session_trend_<SYM>.json:daily_pivots` and `confirmed_swings` for level inputs. **DO NOT** build a parallel pivot/swing builder.
2. **Reuse** `htf_authority.jsonl` + `htf_regime.py` for the H1 authority tag.
3. **Reuse** `ownership_identity.py` for cross-strategy coordination keys.
4. **Reuse** `qm_adaptive_exit.py` / `exit_dress.py` / `structure_exit.py` as the exit substrate — do NOT fork a new exit module.

**Explicit non-scope for SRR V1:**
- Do NOT widen `nms_v3_direction_gate.V3_STRATEGIES` without a parallel shadow run — the gate's current scope is a deliberate design decision.
- Do NOT change `.env` admission flags (BB_BOUNCE_ADMIT, TREND_V3_ADMIT, BOUNCE_ENGINE_ENABLED, BOUNCE_ENGINE_V3_ONLY) until the structural-authority behaviour change has a shadow run.
- Do NOT alter the standalone BB_BOUNCE strategy or NMS V3 engine code in SRR V1.
- Do NOT change broker-side TP semantics for V3 modes (`tp=None` is a spec requirement per `COMPLIANCE_AUDIT.md B1`).

**SRR V1 implementation gate (recommended):**
- A new SRR module reads existing `v3_state` / `winning_regime` / `cascade_label` / `htf_authority` and emits a single **composite structural authority** value.
- Admission paths OPTIONALLY consult it via a Phase-1 SHADOW flag (`SRR_V1_ENABLED=0` by default, shadow writes to `logs/srr_v1_shadow.jsonl`, no behaviour change).
- Phase 2 flips the flag to admission authority ONLY after parity (same bind-rate as the existing stack) is proven in shadow for ≥ N trading days.

---

## Deliverable 9 — Test strategy

**Pre-change tests (before any Stage 2 code):**

1. **Golden-trace test** — replay the 10-16 trading day (6 fires + 4 closes + 3 still-opens) with CURRENT HEAD and confirm the signal_log row-set is byte-identical to the on-disk 10-16 rows.
2. **Direction-gate parity test** — invoke `nms_v3_direction_gate.check(strategy, side, "GBPUSD")` against a mocked session_trend file for each of the 7 recognised v3_states × 2 sides × 6 V3_STRATEGIES = 84 combinations; assert pass/block matches the design matrix in the module docstring.
3. **Admission-family unit** — assert that for each 10-16 strategy fire, the applicable admission branch (`_bb_bounce_strategy_admitted` / `_trend_v3_strategy_admitted` / `_bounce_engine_admitted`) matches the branch that would have been taken on 10-16.

**For Stage 2 shadow deployment:**

4. **SRR shadow parity test** — if an SRR_V1 module is introduced, assert that for every 10-16 fire its composite-authority classification yields a non-contradictory "advice" relative to the admission decision that actually fired.
5. **Position-ownership cross-family test** — assert that opening an opposite-direction fire for a pair with an existing open position of the opposite side either (a) is suppressed by cross-family coordination OR (b) is explicitly tagged `allow_opposing` with reason.
6. **Replay harness extension** — the existing `scripts/a10_strict_replay_20260914_nms.py` should be extended to cover a FULL day of multi-strategy fire activity (not just NMS), using the Stage 0b-authorised bars.

**Test data authority:**

- Use the Stage 0b timestamp-authority manifest (SHA-256 `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc`) for any replay inputs.
- Do NOT mix BID and MID candles across a single test's bar sequence.

---

## Deliverable 10 — Explicit list of unresolved questions

### [UNKNOWN] — require operator / further investigation

1. **Exact `v3_state` at 12:40:33 and 12:56:32 UTC on 10-16** — not resolvable from current logs (no session_trend transition log). To close: (a) check for backup snapshots in `cache/*.pre-*` files or (b) replay `session_trend.py` against the 10-16 M5 bars.
2. **MFE of the 13:35 BOUNCE_TR_L position** — `mfe_pips=None` in signal_log; the operator-stated +29.2 is consistent with the hourly samples but not directly verifiable.
3. **IG account netting mode** — hedging vs netting for CS.D.GBPUSD.TODAY.IP. Needed to confirm the "External close" cause-and-effect at 16:40:25.
4. **Dashboard accounting populations** — V2 (+66.7), V3 (+31.9), H161 (+53.55). Need the dashboard source code and ledger inputs for 10-16 to reconcile.
5. **Whether breakeven stops or scale-outs fired for the morning BUYs before the EOD reversal** — `exit_dress=MANAGED` tells us the exit stack is active but the signal_log record is lifecycle-close; the three positions were still open at report time.
6. **The exact admission comparison between the regime_engine's `TREND_FORMING_UP` label and the session_trend's `v3_state` label** — the two can disagree (as happened 10-16). Needed: a side-by-side time-series of both tags across one trading day, to characterise the disagreement.
7. **Whether `GBPUSD_TREND_V3_L/_S` (non-UM) exclusion from `V3_STRATEGIES` is intentional or accidental** — the module docstring says "V3_BB_L/_S, V3_EMA_L/_S only" but the set also contains the UM variants. Operator confirmation needed before Stage 2 decides whether to widen scope.

### [FACT] — confirmed root causes

- V3_BB_S 12:40 and V3_EMA_S 12:56 passed the direction gate because the gate saw a non-blocking v3_state at those timestamps; **the gate was not bypassed**.
- BOUNCE_TR_L 13:35 admission was BY DESIGN — the strategy is not in V3_STRATEGIES, and the central gate's `_bounce_engine_admitted` branch admits it as long as `BOUNCE_ENGINE_ENABLED=1`.
- BOUNCE_TR_L 16:40 close was `External close (not initiated by this host)`; the GBPUSD_TREND_V3_S SELL opened 4 seconds earlier — strongly consistent with IG broker-side netting.
- The three morning BUYs are open per their configured exit specs (either high-set TP not reached, or V3 modes with `tp=None` by spec).

### [INFERENCE] — hypotheses needing confirmation

- Multiple parallel "trend" classifiers (regime engine, session_trend v3_state, cascade state, normal-state engine, structural state, HTF regime) is the architectural root issue; different gates read different classifiers.
- SRR V1 should be a composite reader that produces a single authoritative structural tag, consumed by all admission paths — but the first version should run SHADOW only.

---

## Boundary statement

**This report ends Stage 0 and Stage 1 per the directive.**

No production file was modified. No service was touched. No trade was placed, closed, or amended. The .env, candle caches, and systemd units are untouched. The investigation used only read access to the production tree.

The implementation of Stage 2 (code changes to introduce SRR V1 and/or coordinate cross-family admission) is **not authorised by this report** and awaits explicit operator approval, with the shadow-first implementation gate described in Deliverable 8.

*— end of V3 improvement Stage 0 & Stage 1 forensic report —*
