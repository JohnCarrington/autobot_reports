# Project Thirty — BB_BOUNCE code retrieval bundle

**From:** host 161 (`/opt/tradingbot`)
**Date:** 2026-09-30
**Author:** autobot session
**Repo state:** branch `feat/trend-stretch-brake-adx-floor`, HEAD `3df0a50`
**Task scope:** code retrieval only. No live AutoBot changes, no
restarts, no broker calls, no historical-data requests, no credentials
or `.env` secrets exported.

---

## 0. What this bundle contains

```
project_thirty_bb_bounce_package_20260930/
├── INTEGRATION_NOTE.md                         ← this file
├── SOURCE_MAP.md                               ← per-era commits + functions
├── TP20_SL12_IMPACT.md                         ← fixed-TP/SL exit analysis
├── env.current.reference                       ← 61 BB_BOUNCE-relevant .env keys, values at HEAD (no secrets)
├── host_161_bb_bounce_l_deal_reference_20260930.csv  ← 180 L-side deals + era tag
└── src/
    ├── gbpusd_bb_bounce.py                     ← the strategy proper — BOTH BB_BOUNCE_S AND _L
    ├── trade_manager.py                        ← exit machinery (multi-tier TP, scale-out,
    │                                              floor, trail, structure, regime_max_hold,
    │                                              BB_FLIP, BB_RANGE_TARGET, etc.)
    ├── orchestrator_v2.py                      ← dispatch precedence + tie resolution
    ├── open_sb_now.py                          ← IG REST /positions/otc seam
    ├── qm_adaptive_exit.py                     ← QM_BAND_CLOSE_INSIDE evaluator
    ├── auto_k.py                               ← AUTO_K_PREMISE evaluator
    ├── bb_bounce_labeller.py                   ← Telegram K-trigger + BB_LABEL prompt
    ├── bb_pd_gate.py                           ← PIVOT-GATE compute + PD% telemetry
    ├── bb_bounce_events.py                     ← BB_BOUNCE_CONFIRMED sensor emission
    ├── bb_sensor_bridge.py                     ← Stage-8 sensor pipe (forensic only)
    ├── cascade_state.py                        ← cascade_disagrees helper
    ├── ribbon_state.py                         ← FANNED_UP/DOWN state machine
    ├── standdown_shadow.py                     ← stand-down verdict logger
    ├── daily_structural_context.py             ← M5 daily-structure context (2026-09-21 dark-wired)
    ├── news_release_window.py                  ← HIGH-impact release calendar guard
    ├── pierce_alert_counter.py                 ← pierce-alert Telegram bump
    ├── level_telemetry.py                      ← level-telemetry emit
    ├── forensic_context.py                     ← forensic snap builder
    ├── forensic_logger.py                      ← forensic_fires.jsonl writer
    ├── gbpusd_regime_detector.py               ← classify_regime()
    └── HOST_MODULES_FILE_LINE_INDEX.txt        ← file:line pointers into strategy_logic.py,
                                                    trade_executor.py, regime_engine.py
                                                    (NOT copied — see §5)
```

Also referenced but not re-copied here (already on the reports-public
mirror from the 2026-09-29 spec):

- `reports-public/gbpusd_bb_bounce_s_implementation_spec_20260929.md` —
  the authoritative wiring / eras / gates document. Read this first.
- `reports-public/host_161_bb_bounce_s_deal_reference_20260929.csv` —
  174 S-side fills with per-fill era tag.
- `reports-public/host_161_trade_profitability_audit_20260927.md` —
  the profitability audit that anchors both S and L rows.
- `reports-public/host_161_deal_ledger_20260927.csv` — the raw ledger
  (180 L rows + 174 S rows in scope).

---

## 1. Strategy identity — DO NOT SUBSTITUTE

**GBPUSD_BB_BOUNCE_S** — GBPUSD only, SELL only. `MODE_NAME_SHORT =
"GBPUSD_BB_BOUNCE_S"` at `src/gbpusd_bb_bounce.py:81`.

Related but distinct strategies **NOT** included and **NOT**
substituted for BB_BOUNCE_S:

- `bb_rejection` (a different repo; different detector).
- `BB_PIERCE_RUN` (an internal `LOG_TAG` for BB_BOUNCE only — same
  strategy, not a separate one).
- `GBPUSD_BB_REVERSAL_PATTERNS` / `BB_REV_PAT` — the newer
  V-shape/Arc reversal build, unrelated file.
- `EURUSD_*` variants — do not exist for BB_BOUNCE at present.
- **`GBPUSD_BB_BOUNCE_L`** — the LONG-side sibling. Same module,
  documented in §4 below. Do not substitute it for the SHORT side —
  the two are configured asymmetrically and have very different
  realised P&L (see §4).

The 172 reconciled SELL fills producing +780.85 pips come from this
strategy and no other. The audit's file:line evidence (audit §3
line 133) chains directly to `src/gbpusd_bb_bounce.py`.

---

## 2. Entry detector — what actually fires

Full detail is in the 2026-09-29 spec §2. Boiled down:

1. **Session gate** (`src/gbpusd_bb_bounce.py:1186-1191`): UTC
   weekdays, `WIN_START ≤ t < WIN_END`. Code default 06:00→17:00 UTC
   (`:109-110`). **Current .env has 04:00→19:00** (see
   `env.current.reference:54-55`) — that expansion post-dates most of
   the fill set.
2. **Setup detector** — `_detect_pierce_setup`
   (`src/gbpusd_bb_bounce.py:1053-1091`). For SHORT: `prev.high -
   bb_upper_prev >= PIERCE_THRESH_PIPS × PIP_SIZE` **and**
   `prev.open <= bb_upper_prev` (opened inside) and NOT both bands
   simultaneously pierced. Code default `PIERCE_THRESH_PIPS=2.0`
   (`:147`); **current .env has 0.5** (`env.current.reference:50`).
3. **Alt setup** — `_detect_near_touch_setup`
   (`src/gbpusd_bb_bounce.py:1095-1135`), added 2026-07-10. Prox
   `BB_NEARTOUCH_PROX_PIPS=1.5p`.
4. **Rejection window** = 3 bars (`REJECTION_WINDOW_BARS`, `:235`).
5. **Rejection check** — `_is_rejection`
   (`src/gbpusd_bb_bounce.py:2181-2198`). For SHORT: body ≥
   `MIN_REJECTION_BODY_PIPS × PIP_SIZE`, `close < open`, `close ≤
   bb_upper_n + REJECTION_TOLERANCE_PIPS`. Adaptive body ON in
   current .env.
6. **Fire trigger** — `entry = float(cur.close)`
   (`src/gbpusd_bb_bounce.py:3174`), `sl_pips = SL_PIPS`. **Fire is
   on the close of the rejection candle**, not on a subsequent stop
   order under the rejection candle's low.
7. **Suppression gates** run *after* the rejection is recognised.
   They can still block the fire:
   - PIVOT-GATE (default OFF per env)
   - Velocity guard (`BB_VELO_L_ENFORCE=0` and `BB_VELO_S_ENFORCE=0`
     in current .env)
   - News-release blackout (`src/news_release_window.py`)
   - STRONG_TREND / TREND_FORMING stand-down
   - CHOP_MODE dispatch gate
   - Position-slot gate
   - Concurrent-cap gate
   - EXECUTION_AUTHORITY firewall (2026-09-29 build in
     `trade_executor.py:2427-2448` — see
     `src/HOST_MODULES_FILE_LINE_INDEX.txt`)

All are called for both S and L legs; the enforce flags differ (§4).

---

## 3. Exit machinery — what actually closed the fills

Full 21-way exit tree in spec §3. The functions live in
`src/trade_manager.py`:

| Exit label                       | Function / line                                        | Notes |
|----------------------------------|--------------------------------------------------------|-------|
| Scale-out at +10p (default 8 now)| `_scale_out_50pct` @ `trade_manager.py:3596-3675`      | needs size ≥ 2.0 |
| Post-scale FLOOR_STOP (arm 10 / lock 5) | `_apply_bb_bounce_post_scale_floor` @ `:2900-3010` | both L + S |
| Post-scale TRAIL_STOP (12 / 6)   | `_apply_bb_bounce_runner_trail` @ `:2633-2760`         | **L default ON, S default OFF** |
| BE_STOP_POST_SCALEOUT            | `trade_manager.py:4393`                                | fallback runner exit |
| BRIEFING_TP1_CLOSE               | `trade_manager.py:5909`                                | momentum-gated |
| BRIEFING_TP_SL_OPEN              | `trade_manager.py:5674-5676`                           | tier-machinery SL |
| STRUCTURE_EXIT                   | `trade_manager.py:5318`                                | 5m HH/LL vs prior N bars |
| REGIME_MAX_HOLD                  | `trade_manager.py:6445`                                | 240m for BB_PIERCE_RUN modes; **disabled in current .env** |
| EXIT_PROFILE_SQUEEZE             | `trade_manager.py:2080`                                | one-shot bar-close full-close |
| QM_BAND_CLOSE_INSIDE             | `qm_adaptive_exit.py:243` → `trade_manager.py:6705`    | requires QM_ENABLED + mode-lane |
| BB_FLIP                          | `autobot.py:7553` (not in bundle)                      | opposite-dir BB_BOUNCE fire flips |
| BB_RANGE_TARGET                  | `trade_manager.py:6778`                                | opposite band touched |
| AUTO_K_PREMISE                   | `auto_k.py:72`                                         | **retired 2026-09-02** — `AUTOK_PREMISE_ENABLED=0` |
| LABEL_K_OPERATOR                 | `bb_bounce_labeller.py:586`                            | manual Telegram K |
| PRE_NEWS_CLOSE                   | `autobot.py:4905` (not in bundle)                      | HIGH-impact econ imminent |
| NY_CLOSE                         | `autobot.py:4786` (not in bundle)                      | 17:00 ET close window |
| SL_HIT / TP_HIT / BE_HIT_IG      | broker-side                                            | reported by IG payload |
| EXTERNAL_MANUAL / IG_RECONCILE   | `signal_log_integrity.py:213` (not in bundle)          | shared DEMO account safeguard |

Anything living in `autobot.py` or `signal_log_integrity.py` is
NOT bundled here — those are the tick-loop and reconciliation
orchestrators, not part of the BB_BOUNCE strategy itself. They are
mentioned only because the deal_reference CSV records the exit label
they emit, and Project Thirty needs to know the label's origin.

---

## 4. BB_BOUNCE_L — the LONG-side sibling

Same module, same detector, same exit machinery — with the
following material asymmetries, none of which are simple direction
reversals.

### 4.1 Detector — shared

Functions used by both:

- `_detect_pierce_setup` at `src/gbpusd_bb_bounce.py:1053-1091` —
  the LONG branch is on lines `1064-1087`, mirror of the SHORT
  branch on `1088-1091`.
- `_detect_near_touch_setup` at `src/gbpusd_bb_bounce.py:1095-1135`.
- `_is_rejection` at `src/gbpusd_bb_bounce.py:2181-2198` — LONG
  branch line `2196-2197`.
- The fire-selection tie-break (oldest satisfied setup wins) at
  `src/gbpusd_bb_bounce.py:2211-2219`.

### 4.2 Admission gates — L-specific

| Gate | S-side | L-side |
|------|--------|--------|
| `_min_touches` fallback split | `BB_NEARTOUCH_MIN_TOUCHES_S` (`:179`) | `BB_NEARTOUCH_MIN_TOUCHES_L` (`:181`) — both default to shared value |
| Velocity guard enforce flag | `BB_VELO_S_ENFORCE=0` code default | **`BB_VELO_L_ENFORCE=1` code default** (`:693-694`) |
| Cascade-veto shadow (R1) | none | `BB_BOUNCE_L_CASCADE_GUARD_SHADOW_ENABLED=1` default; `_ENABLED=0` (enforce off). Shadow log path at `src/gbpusd_bb_bounce.py:283-296`; enforcement path at `:3606-3661` |
| H1_COUNTER_STRENGTH gate | applies both sides | applies both sides — direction-flipped at `:2520-2521` (FANNED_UP/DOWN vs BUY/SELL) |

Current .env has `BB_VELO_L_ENFORCE=0` and
`GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=0`, so at HEAD both L and
S run without the velocity guard and without the H1 counter gate.
This differs from the code defaults; per memory
`[[project_bb_bounce_gates_disabled]]` these values have been 0
since 2026-05-28 for H1 counter, and per env-history the current
values were already in place by 2026-09-12.

### 4.3 Exit machinery — L-specific

- **Runner trail default is DIFFERENT.** `trade_manager.py:1725-1726`:
  ```
  BB_BOUNCE_L_RUNNER_TRAIL_ENABLED_DEFAULT = "1"
  BB_BOUNCE_S_RUNNER_TRAIL_ENABLED_DEFAULT = "0"
  ```
  L trails post-scale by default; S rides BE + broker TP by default.
  This is the single largest exit-behaviour divergence between the
  two legs. Current .env forces
  `BB_BOUNCE_S_RUNNER_TRAIL_ENABLED=1`, so at HEAD both trail — but
  historically S did not, which is a factor in per-era P&L
  differences.
- Everything else (FLOOR_STOP, BE_STOP, BRIEFING_TP tier machinery,
  STRUCTURE_EXIT, REGIME_MAX_HOLD, EXIT_PROFILE_SQUEEZE,
  QM_BAND_CLOSE_INSIDE, BB_FLIP, BB_RANGE_TARGET, AUTO_K_PREMISE,
  LABEL_K_OPERATOR, PRE_NEWS_CLOSE, NY_CLOSE, SL/TP/BE_IG,
  EXTERNAL_MANUAL, IG_RECONCILE) applies identically to both legs.

### 4.4 Realised fills for BB_BOUNCE_L

Audit `host_161_trade_profitability_audit_20260927.md`:

- **178 fills, 77 active days across 2026-05-04 → 2026-09-24**
  (audit line 134)
- **+222.9 pips net, +2.89 p / active day**
- Positive-day rate 58 %, top-3 days = **86 % of net**
- MDD −108 p on the +223 p base
- Audit ranking (line 269): "**fragile — removing the top few days
  flips the sign**"

Ledger extract (180 rows, one .env-agnostic per-era split identical
to the S-side extract in the 2026-09-29 spec):
`host_161_bb_bounce_l_deal_reference_20260930.csv` (bundled here).

Per-era L-side realised (sum of `total_pnl_pips || pnl_pips`):

| Era | Fills | Realised pips |
|-----|------:|--------------:|
| A — 2026-05-04 → 2026-05-22 | 31  | **−85.95** |
| B — 2026-05-29 → 2026-06-24 | 39  | **+225.85** |
| C — 2026-06-25 → 2026-07-14 | 13  | **+70.85**  |
| D — 2026-07-15 → 2026-08-23 | 55  | **+65.35**  |
| E — 2026-08-24 → 2026-09-24 | 42  | **−53.20**  |
| **Total**                   | 180 | **+222.90** |

Sanity check: 31+39+13+55+42 = 180 fills (2 more than audit's 178 —
matches the S-side pattern of 2 unreconciled rows around era
boundaries; the audit counts reconciled).
+222.90 matches the audit exactly (line 134).

**Contrast with S:** S = 172 fills, +780.85 pips, top-3-day
concentration 24 % (audit line 268 — "the only strategy with all
four boxes ticked"). L's advantage over S is only in fill count
(180 vs 174 raw); everything else favours S materially.

### 4.5 Was BB_BOUNCE_L source manufactured?

No. The L-side is not a synthesised mirror. It is the SAME module
firing on the same detector; direction-branching happens naturally
via the LONG / SHORT arms of `_detect_pierce_setup` and
`_is_rejection`. The only manufactured artefact in this bundle is
the per-era CSV, which is a straight ledger extract with the
identical era boundaries used for S in the 2026-09-29 spec.

---

## 5. Effective configuration — known-historical vs current vs
   unknown

The bundle ships `env.current.reference` with the 61 BB_BOUNCE-related
keys from `.env` at HEAD. **These are the CURRENT values, not the
per-fill historical values.** Split for clarity:

### 5.1 Known-historical (from env-history + .env backups)

- `env-history/` on 161 begins **2026-09-21**. It is a rolling
  by-the-minute snapshot — 63 files at time of bundle. Every key in
  `env.current.reference` was already at its HEAD value on the first
  snapshot (2026-09-21T07:27:38Z).
- `.env.pre-golive.20260912T172928Z` — the manual backup taken
  before the 2026-09-12 golive. **Same values as HEAD** for all keys
  listed in §2.3 above.
- `.env.pre-qmlive.20260914T083629Z` — same story.

Corollary: for fills between **2026-09-12 and 2026-09-24** the
current `env.current.reference` values apply.

### 5.2 Unknown-historical (before 2026-09-12)

For the earlier 132 S fills (of 174) and 138 L fills (of 180), no
daily `.env` backup exists on 161. Historical values are inferred
from:

- **Code defaults** in `src/gbpusd_bb_bounce.py:104-810`.
- **Commit messages** and diffs on `gbpusd_bb_bounce.py` and
  `trade_manager.py` — spec §5 lists the marker commits per era.
- **`env-history/` first snapshot values** for fills between
  2026-09-12 and 2026-09-21 (the two-week gap covered by the pre-*
  backups).

Complete per-fill env attribution before 2026-09-12 **is not
recoverable** without a snapshot server that host 161 does not run.

### 5.3 Notable deltas — current vs spec §4 (spec's implied
   historical baseline)

| Key                                       | Current | Spec §4 | Notes |
|-------------------------------------------|--------:|--------:|-------|
| `GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS`      | 0.5     | 2.0     | Widened threshold reduces fire count; current-tight value fires more but is what applied 2026-09-12+ |
| `GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS`| 0.5     | 1.0     | Tighter tolerance filters visual-edge rejections |
| `GBPUSD_BB_BOUNCE_WIN_START_H`             | 4       | 6       | Window pushed earlier — captures pre-London tape (see spec on 05:45 UTC adaptive-body incident) |
| `GBPUSD_BB_BOUNCE_WIN_END_H`               | 19      | 17      | Window pushed later — captures NY afternoon tape |
| `BB_BOUNCE_ADAPTIVE_BODY`                  | 1       | 0       | Adaptive body threshold ON (2026-08-06 commit `77414d3` machinery live) |
| `SCALE_OUT_TRIGGER_PIPS`                   | 8       | 10      | Earlier scale-out — banks half at +8p |
| `BB_BOUNCE_S_RUNNER_TRAIL_ENABLED`         | 1       | 0       | S trail forced ON via env, code default 0 |
| `REGIME_MAX_HOLD_ENABLED`                  | 0       | 1       | Time stop OFF |
| `BB_VELO_L_ENFORCE`                        | 0       | 1       | L velocity guard disabled |
| `BB_VELO_S_ENFORCE`                        | 0       | 0       | matches code default |
| `AUTOK_ENABLED`                            | 1       | 0       | AUTOK master ON but `AUTOK_PREMISE_ENABLED=0` — premise cut retired 2026-09-02 |
| `CHOP_MODE_ENABLED`                        | 1       | (n/a)   | Restricts book to BB_BOUNCE_L/S in chop_mode sessions |

The spec's §4 values reflect a nominal at-fire configuration and
were compiled without full historical env attribution — the current
.env has since drifted for tuning reasons documented in commit
history.

---

## 6. Fixed TP20 / SL12 — exit behaviour changes (requested analysis)

Full detail in `TP20_SL12_IMPACT.md`. Summary: swapping the current
21-way exit tree for a fixed `TP=20p / SL=12p` breaks every one of
these behaviours:

1. **Broker TP truncates every runner above +20p.** Current
   `BROKER_TP_PIPS = 100p` (`gbpusd_bb_bounce.py:600`) is a safety
   sentinel; almost all realised P&L above +20p is delivered by
   BRIEFING_TP2/TP3, TRAIL_STOP, or BE_STOP_POST_SCALEOUT AFTER a
   scale-out at +8..10p. Fixed +20 caps the runner exactly where the
   tier machinery hands it over to the trail.
2. **SL=12 is a HARD stop identical to IG's minimum
   (`GBPUSD_IG_MIN_STOP_PTS=12`).** No BE amend, no floor, no
   trail — the runner risks a full -12 give-back until TP hit.
   Current stop path installs BE at scale-out (+8..10p) and then
   floors at +5 once peak clears +10, capping worst-case give-back
   at −0 net (BE) with the floor as a ratchet-up ceiling.
3. **BRIEFING_TP tier machinery becomes inert.** The
   `select_tp_levels` call at `gbpusd_bb_bounce.py:3330` builds a
   TP1/TP2/TP3 plan pinned to briefing levels; a fixed +20p ignores
   this. The 13 BRIEFING_TP1_CLOSE fills (spec §6.1) are labelled
   TP1_CLOSE, not TP_HIT — and TP1 was frequently below +20 on days
   with a nearby level.
4. **QM_BAND_CLOSE_INSIDE / EXIT_PROFILE_SQUEEZE / STRUCTURE_EXIT
   become inert** — none of them touch broker TP; they close early
   on signal. A fixed +20 with these off increases both winners
   above +20 (no early cut) and drawdown (structure-flip losers
   ride to -12).
5. **REGIME_MAX_HOLD becomes inert** — the 240-minute time-stop
   never fires because broker TP or SL always reaches first at the
   tight distances.
6. **AUTO_K_PREMISE (already off) and LABEL_K_OPERATOR** — no
   change; they close positions regardless of broker TP.

Net direction — the +780 pips over 172 S fills is NOT recoverable
under fixed TP20/SL12. See `TP20_SL12_IMPACT.md` for per-close_reason
counterfactual.

---

## 7. Unavailable / not exported

| Item | Reason |
|------|--------|
| `.env` (full file) | Contains IG credentials + Telegram tokens. Only BB_BOUNCE keys extracted to `env.current.reference`. |
| IG account ID / session tokens | Not required for source reproduction; sealed on host 161. |
| Per-fill env attribution before 2026-09-12 | No daily `.env` backup exists — see §5.2. |
| Full commit history diff per file | Available on the git mirror; run `git log --follow gbpusd_bb_bounce.py`. |
| `autobot.py` (tick loop) | 100KB+ orchestrator with unrelated code paths. BB_FLIP, PRE_NEWS_CLOSE, NY_CLOSE emit sites cited in §3; ask if you need extracts. |
| `strategy_logic.py` / `trade_executor.py` / `regime_engine.py` | Line-indexed in `src/HOST_MODULES_FILE_LINE_INDEX.txt`. Ask host 161 if you need the specific function bodies extracted. |
| `signal_log_integrity.py` | The IG_RECONCILE + EXTERNAL_MANUAL emitter — reconciliation only, not part of the strategy. |
| `pending_deal_ledger.py` | Durable pending-confirmation store added 2026-09-30 (commit `2fb0488`) — orthogonal to the strategy. |
| `chop_mode.py` | Cited but not required for entry-decision reproduction. |
| `posture.py` / `day_context.py` | Observation modules cited at trade_executor.py:1882/3636; label-only, non-blocking. |
| Historical GBPUSD candle archive | See spec §7 for reproduction protocol; the archive is a `/opt/tradingbot/cache/*.csv` set. |

---

## 8. Reproduction pointer

For a decision-only replay, follow the 2026-09-29 spec §7
"Independent-reproduction protocol". Nothing has changed in that
protocol — this bundle is the source it points to.

*End of note. Bundle assembled 2026-09-30 without touching AutoBot,
IG, .env, or any live service.*
