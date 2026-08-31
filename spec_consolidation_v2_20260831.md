# V2 spec consolidation — 2026-08-31

**Docs-only work.** Zero code, zero restarts. Local commits to `/opt/tradingbot/docs/`. This report is the public summary of what changed.

## What's on the box

Three verbatim source docs (unchanged by this session):
- `docs/total_spec_v1.md` — SDE spec, 45 sections, 28,542 bytes
- `docs/master_spec_addition_v1.md` — day-type intelligence + Balanced Rotation + two-session reversal, 55 sections, 32,743 bytes
- `docs/market_calendar_spec_v1.md` — holiday/session participation, 34 sections, 19,867 bytes

Two new consolidation docs written this session:
- `docs/v2_master_spec.md` — canonical index + reconciliation layer over the three sources
- `docs/v2_roadmap.md` — 9 existing milestones + 4 new (M-CAL, M-RESEARCH, M-BDT, M-ROT-MEM)

**Post-restart snapshot (2026-08-31 16:59Z)**: verified via disk state — `qm_level_interactions.jsonl` at 1.75 MB still writing; `qm_level_memory.py` defaults `QM_LEVEL_MEMORY_ENABLED=1` and is not overridden in `.env`; **level memory + cohort scoping are LIVE (shadow), not dormant**. M2's collection clock is running from 16:59Z.

---

## Terminology table (canonical name × source citations)

| Canonical name | Total Spec | Addition | Calendar | Code |
|---|---|---|---|---|
| Market Calendar / Participation | — | — | §1-3, §9-13, §26, §33 | (not built; M-CAL) |
| MarketDayContext | — | — | §9 | (not built) |
| Fundamental Day Context | §27 (as "Day Type") | §4-8 (Layer A) | §2 (Layer 2) | news_state_finnhub_*, tier |
| Behavioural Day Type | — | §9-13, §15 (Layer B) | §33 | (not built; M-BDT) |
| Balanced Rotation | — | §10, §17, §54 | §17 | (not built) |
| Current Regime | §3 (11 states) | §14 (8 states) | §2 (7 states) | regime_engine (canonical set = Total's 11) |
| Structural Level Engine / Map | §4 | §18, §22 | §22 | levels_engine, bb_pd_gate, qm_liquidity_level_mapper |
| Confluence Zone | §5 (scored) | §20 | (implicit) | qm_decision_zones.jsonl (telemetry only) |
| Decision Zone | §6-11 | §21 | (implicit) | qm_level_interactions, qm_hooks (LIVE) |
| Rejection score | §9 (int, banded) | §24 (float 0-1) | ref | qm_decision_shadow._REJECTION_WEIGHTS |
| Acceptance score | §10 | §25 (float 0-1) | ref | qm_decision_shadow (PARTIAL — no weights table) |
| Sweep detection | §8 | §17.4 | ref | qm_level_interactions |
| Rejection vs Acceptance competition | §11 | §26 | — | (both scored; competition not explicit) |
| Confidence model | §29 (0-100) | §39 (strategy scores) | §9 (confidence_modifier) | qm_decision_shadow.score_confidence |
| Strategy preference matrix | §26 | §28 (matrix) | §18 (matrix) | (not built as service) |
| Adaptive exit | §19-22 | §32-33 | — | qm_adaptive_exit, qm_exit_shadow |
| Fast trend / exit promotion | §17 (entry) | §34-35 (exit) | — | trend_v3 flags (PARTIAL) |
| Failed reversal / breakout | §23-24 | §40 | — | qm_level_interactions FAIL states |
| Band walking | §18 | §17, §19 | — | bb_bounce band-walk suppression |
| Time-of-day prior | §30 | §27 | — | day_planner (PARTIAL) |
| Two-session rotation memory | — | §16, §30-31, §38 | — | (not built; M-ROT-MEM) |
| Level memory (per-identity) | — | §16 (session-scope) | — | qm_level_memory (LIVE shadow) |
| Level memory cohort scoping | — | (implicit) | — | qm_level_memory cohort_of + DYNAMIC exemption (LIVE shadow) |
| Shadow mode | §40 | §45-46 | — | qm_decision_shadow, qm_exit_shadow, qm_level_memory |
| Telemetry / explainability | §36-37 | §36, §46-47 | §21, §30 | signal_log, qm_*.jsonl |
| Fail-safe | §39 | §50 | §20 | (existing risk controls; calendar not present) |
| Configuration | §38 | (implicit) | §26 | .env + env vars |

Full table with more detail is in `docs/v2_master_spec.md §2`.

---

## Conflict / overlap register (15 items)

Resolved rulings and OPEN items — no silent resolutions.

| # | Topic | Resolution |
|---|---|---|
| **3.1** | Rejection score: integer (Total §9) vs float (Addition §24) | **RULED**: canonical = both. Raw integer + band label; float derivable as raw/10. Existing code (qm_decision_shadow) is reference. |
| **3.2** | Acceptance parity with rejection scoring | **OPEN RULING**: `_ACCEPTANCE_WEIGHTS` table + banding to define. |
| **3.3** | "Day Type" terminology collision (Total §27 vs Addition §4-8) | **RULED (operator, binding)**: Addition's naming wins. NORMAL/PRE/BIG/POST = Fundamental Day Context; BR/GRIND/TREND/CHOP = Behavioural Day Type. |
| **3.4** | Regime state-set size (Total 11 / Addition 8 / Calendar 7) | **RULED**: canonical = Total's 11-state superset (matches existing regime_engine output). |
| **3.5** | Phase-2 research before classifiers vs live gate calibration | **RULED (operator, binding)**: **both streams run in parallel and must AGREE before any gate ships live.** Offline research (M-RESEARCH) must agree in direction and magnitude with live shadow labels (M-BDT). Disagreement holds shadow. |
| **3.6** | Holiday exclusion from NORMAL statistics (Calendar §17) | **RULED (operator, binding)**: **binding on ALL research work.** Every NORMAL-day statistic filters holidays by default; explicit override only for holiday-specific research. |
| **3.7** | Fast trend promotion (Total §17 entry-side) vs fast exit override (Addition §34 exit-side) | **RULED**: same mechanic, two modes. Canonical = unified FastPromotion service (entry + exit); not yet built. |
| **3.8** | BB pierce optionality (Total §12 vs Addition §19) | **NOT A CONFLICT**: consistent. BB is a confidence input, not a gate. |
| **3.9** | Two-session rotation memory: evidence-only or size-scaling? | **OPEN RULING**: does a validated London rotation modify only the BR prior, or also size the NY-side candidate? |
| **3.10** | Confidence FLOOR ruling (M8) | **RULED (operator re-ruling)**: yes/no gate, not scaled sizing. Total §29's `>=70 eligible / >=80 countertrend` compatible; above-floor scores do NOT change size. |
| **3.11** | Session-level participation as first-class permission (Calendar §11-12, §19, §29) | **RULED**: canonical. StrategySelector must be built to receive per-session permissions from MarketCalendarService (M-CAL-P2). Hard-coded strategy holiday logic is architecturally non-conformant. |
| **3.12** | 11-September falsifiable line | **RULED (operator)**: fixed. No milestone re-scheduling moves it. |
| **3.13** | Strategy preference matrices (Addition §28, Calendar §18) — normative or advisory? | **RULED**: **advisory prior**. Starting weights for StrategySelector; empirical evidence (M-RESEARCH + live shadow) overrides cells post-calibration. |
| **3.14** | Weekly high/low levels (Addition §18) | **OPEN RULING**: no evidence-gate defined. NOT-STARTED; gated on M-RESEARCH producing a positive signal. |
| **3.15** | Calendar §17's "characteristic two significant BB reversal" wording | **OPEN RULING**: falsified as literally stated (`reports-public/two_bounce_days_20260831.md`: 87% of weekday days show ≥2 qualifying bounces; monthly mean 18.6 vs hypothesised ~10). Does the Calendar spec need re-wording, or is the definition of "significant BB reversal" what needs tightening? |

---

## Roadmap diff vs the prior 9-milestone plan

The prior plan was implicit in Total Spec §44's Phases 1-9. The consolidation adds four milestones and adjusts M1/M2/M8 status:

| Change | What | Why |
|---|---|---|
| **M-CAL inserted upstream of everything else** | Two-phase Market Calendar Service (deterministic stamping, then session permissions) | Every downstream research step depends on `calendar_classification` being stamped. Was invisible in Total Spec. |
| **M-RESEARCH gates M-BDT and M-ROT-MEM** | Balanced Rotation historical investigation (Addition §42-44 + Calendar §22) | Addition §55 explicit: "do not implement arbitrary probability thresholds or scoring weights yet". Neither downstream milestone can advance on hand-tuned weights. |
| **M-BDT dual-agreement gate** | New AGREEMENT requirement (offline research × live shadow) before Layer B influences live | From conflict #3.5 ruling. |
| **M8 simplified to yes/no floor** | Confidence FLOOR ruling replaces continuous sizing curve | Operator re-ruling #3.10. Simplifies M8 delivery; pushes weight calibration into M-RESEARCH. |
| **M2 status: "clock running"** | Post-2026-08-31 16:59Z restart, live interaction tape accrues | Restart activated collection; 11 days by 11-Sep for interim snapshot. |
| **M1 status: level memory + cohort scoping LIVE (shadow)** | Not dormant | Same restart activated the on_final dispatch chain. |

**Dependency graph**:

```
M-CAL-P1 ──► all research
    │           │
    └──► M-CAL-P2         │
                          ▼
                    M-RESEARCH ──► M-BDT ──► M-ROT-MEM
                                     │
                                     ▼
                          weight recalibration ──► M8 ──► M9

M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 → M9
           │
           └── feeds M-RESEARCH's live-tape stream
```

**Critical path to M8**: M-CAL-P1 → M-RESEARCH → M-BDT (dual agreement) → weight recalibration → M8. If any step slips past 11-Sep, the 11-Sep evaluation is against the pre-line codebase; M8 becomes a post-line delivery. **The 11-Sep line does not move.**

---

## Status audit — top of the table

Full status audit is in `docs/v2_master_spec.md §4`. Roll-up:

| Category | BUILT | PARTIAL | SHADOW | NOT-STARTED | OPEN-RULING |
|---|:---:|:---:|:---:|:---:|:---:|
| Total Spec (§1-§45) | 12 | 11 | 8 | 10 | 4 |
| Addition (§1-§55) | 4 | 8 | 6 | 33 | 4 |
| Calendar (§1-§34) | 0 | 0 | 0 | 33 | 1 |

**Notable BUILTs (already in production)**: regime engine (Total §3); daily pivots (Total §4.1); BB levels (Total §4.4); EMAs (Total §4.5); interaction state machine (Total §6, Addition §21); sweep detection (Total §8); rejection scoring (Total §9); reversal state machine (Total §13); M5 confirmation (Total §14); countertrend model (Total §15); continuation sequence (Total §16); band walking (Total §18); failed reversal/breakout (Total §23-24); state priority (Total §35); logging (Total §36); shadow mode (Total §40); scenarios A/B/C/F (Total §41); no future leakage (Addition §44); no regime loyalty (Addition §41); strategy-doesn't-classify rule (Addition §37).

**Notable SHADOWs (live but no gate wiring)**: qm_decision_shadow (rejection scoring); qm_exit_shadow (exit races); qm_level_memory (level memory + cohort scoping — LIVE post-restart); qm_adaptive_exit.

**Notable PARTIALs (code exists but incomplete)**: confluence scoring (Total §5); approach behaviour (Total §7); acceptance scoring (Total §10); rejection-vs-acceptance competition (Total §11); fast trend promotion (Total §17); adaptive exit engine (Total §19-22); structural target service (Total §25); time-of-day (Total §30); acceleration detection (Addition §23); 00/50 weighting (Addition §22).

**Calendar has zero BUILT items** — this is the biggest gap. All of Calendar §1-§34 is NOT-STARTED; M-CAL-P1 is the highest-leverage next-step because every downstream research query filtered by calendar (Calendar §17 binding ruling) needs it stamped on records.

---

## What did NOT change

- Live trading behaviour: unchanged. Zero code touched.
- The three source docs: byte-identical to what the operator scp'd.
- Restart state: none required by this consolidation.
- The 11-September falsifiable line.
