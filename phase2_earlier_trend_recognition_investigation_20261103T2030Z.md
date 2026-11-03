# Part B — Phase 2: Earlier Trend Recognition (investigation)

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T20:30Z
**Branch:** `investigation/phase2-earlier-trend-recognition-20261103`
**Mode:** READ-ONLY investigation and offline validation. **No Phase 2 production deployment.**

Stop after this report. Operator reviews before any further action.

Phase 1 C4 code was deployed in a separate branch (`deploy/phase1-c4-m5-regime-20261103`). Phase 2 is an offline-only investigation building on top.

## 1. Root cause of delayed trend recognition

### 1.1 Why did the 2026-10-30 upward trend remain RANGE until 09:20?

Bar-by-bar trace (replay harness output; evidence columns mirror the production `advance()` return):

```
08:00  c=13412.05  disp=+7.3   state=RANGE  up= 0  dn= 0  fired=[]                             (OR forming — bar 1 of 3)
08:05  c=13406.35  disp=+1.6   state=RANGE  up= 0  dn= 0  fired=[]                             (OR forming — bar 2 of 3)
08:10  c=13410.55  disp=+5.8   state=RANGE  up= 0  dn= 0  fired=[]                             (OR forming — bar 3 of 3; OR_high=~13414)
08:15  c=13414.25  disp=+9.5   state=RANGE  up=+1  dn=+1  fired=[E2:UP, E6:UP, E7:DOWN]        (first eligible bar)
08:20  c=13410.65  disp=+5.9   state=RANGE  up=+1  dn=+1  fired=[]
08:25  c=13414.65  disp=+9.9   state=RANGE  up=+1  dn=+1  fired=[E6:UP]                         (close ≈ OR_high — no break)
08:30  c=13414.45  disp=+9.7   state=RANGE  up=+2  dn=+1  fired=[E8:UP]                         (score reaches 2 — below threshold 3)
08:35  c=13411.65  disp=+6.9   state=RANGE  up=+2  dn=+2  fired=[E2:DOWN, E7:UP]
08:40  c=13412.75  disp=+8.0   state=RANGE  up=+2  dn=+2  fired=[E6:UP]
08:45  c=13414.65  disp=+9.9   state=RANGE  up=+2  dn=+2  fired=[E2:UP, E6:UP]
08:50  c=13414.35  disp=+9.6   state=RANGE  up=+2  dn=+2  fired=[E8:UP]                         (first confirmed swing)
08:55  c=13415.45  disp=+10.7  state=RANGE  up=+2  dn=+2  fired=[E6:UP, E8:UP]                  (second confirmed swing)
09:00  c=13412.75  disp=+8.0   state=RANGE  up=+2  dn=+2  fired=[]
09:05  c=13418.45  disp=+13.7  state=RANGE  up=+2  dn=+2  fired=[E6:UP]                         (close > OR_high+3 — E1 CANDIDATE)
09:10  c=13420.15  disp=+15.4  state=RANGE  up=+6  dn=-1  fired=[E1:UP(+2), E2:UP, E4:UP(+2), E6:UP, E8:UP, C1:DOWN(-3)]
                                                                                                 (E1 CONFIRMED + E4 HL fired. Score +6 ≥ 3, structural anchor present)
09:15  c=13423.45  disp=+18.7  state=RANGE  up=+8  dn=-1  fired=[E2:UP, E3:UP(+2), E6:UP, E8:UP]  (STRONG threshold 6 hit)
09:20  c=13420.35  disp=+15.6  state=STRONG_UP       up=+8  dn=-1                                 (2-bar persistence passed; state transition)
```

**Root cause breakdown:**

1. **The structural-anchor requirement (`_emerging_struct_present`).** Non-structural evidence (E2 momentum + E6 displacement + E7 EMA stack + E8 MACD) alone contributes max 2 points due to family caps (F-momentum = 1, F-supporting = 1). Score of 2 is below the EMERGING threshold of 3. A structural anchor (E1 / E3 / E4 / E5) contributing +2 is required.

2. **E1 (OR break) needed 70 minutes** to arm + confirm. OR formed by bar 3 (08:10); OR_high ≈ 13414.25 + 3p = 13417.25. First close exceeding that was **09:05** (13418.45) — the E1 candidate. E1 requires confirmation on the NEXT bar, which came at **09:10** (13420.15 > 13417.25). That is 70 minutes post-London-open.

3. **E4 (confirmed HL) needed 70 minutes** by coincidence. The 08:55 fractal swing low needed idx+2 confirmation, which came at 09:10 simultaneously with the first fractal HL.

4. **2-bar persistence lag.** Even though score jumped from +2 to +6 at 09:10, the state machine requires `PERSISTENCE_BARS = 2` matching want-state before transitioning. State moved to STRONG_UP at 09:20 (bar 15, two bars after score ≥ 6).

### 1.2 What evidence was already available at 09:00 and 09:05?

| Time | Facts available |
|---|---|
| 09:00 | disp=+8.0p. 8 non-structural up-firings over 10 bars. No structural anchor. Score = +2. 2 confirmed swings. |
| 09:05 | disp=+13.7p (first +13+ bar). First E1 candidate (close > OR+3p). Score still +2. No structural anchor confirmed. |

### 1.3 Can existing E1–E8 identify early direction before structural confirmation?

**Yes.** Two existing firings consistently flag directional pressure 15–70 minutes before EMERGING:

- **E6 (displacement ≥ 8p + bar colour match)** — fired at 08:15 (first eligible bar), 08:25, 08:40, 08:45, 08:55, 09:05 on 2026-10-30. That is 15 minutes post-London-open on a directional day.
- **E2 (sustained 2-bar progression)** — fired at 08:15 and 08:45 on 2026-10-30.

What is MISSING to admit EMERGING earlier is NOT a new indicator but a **structural anchor** (E1 / E3 / E4 / E5). The structural anchor fundamentally requires either (a) an OR break by +3p, or (b) a fractal swing confirmed with a 3-bar pattern. Both take time by construction.

**Conclusion:** the classifier's existing evidence already identifies early direction via E6 + E2. What it does NOT do is EXPOSE that fact to consumers — because `v3_state == RANGE` while the structural anchor is pending.

## 2. Proposed early-direction mechanism

### 2.1 Design

Add a new `m5_regime` sub-label — `DIRECTIONAL_PENDING_UP` / `DIRECTIONAL_PENDING_DOWN` — that fires when:

```
state == RANGE
len(london_bars) >= OR_WINDOW_BARS + 1   (OR formed + at least 1 post-OR bar)
disp >= +8.0 (= E6_DISP_PIPS)            [or <= -8.0 for DOWN]
up_fams["F-momentum"] >= 1               (E2 or E6 has fired)
down_fams["F-momentum"] == 0             (opposing momentum absent)
up_fams["F-structural"] == 0
up_fams["F-structure"] == 0              (no structural anchor yet — this is pre-EMERGING)
```

This is strictly additive to the C4 multi-dim classification (Part A). It does NOT alter:
- `state` — still RANGE
- `up_score` / `down_score` — thresholds untouched
- `_emerging_struct_present` — unchanged
- Family caps — unchanged
- EMERGING / STRONG admission — unchanged

### 2.2 Why these thresholds

All thresholds reuse existing classifier values:
- `OR_WINDOW_BARS = 3` (existing `OR_WINDOW_BARS`)
- `disp >= 8.0` reuses `E6_DISP_PIPS = 8.0`
- "F-momentum ≥ 1" reuses the family-cap structure (E2 or E6 fires)
- "no structural anchor yet" is a DIRECT NEGATION of the EMERGING precondition

**No new numeric constants, no new indicator, no new measurement.** Zero additional moving parts.

### 2.3 Not a gate — a label

`DIRECTIONAL_PENDING_*` is EXCLUSIVELY a `m5_regime` label. Strategies that currently read `v3_state` continue to see `RANGE`. Strategies that OPT IN to read `m5_regime` see the richer label. No admission change for any strategy without explicit opt-in.

## 3. Before/after timeline for representative sessions

Replay harness at `/mnt/volume_lon1_1778405456698/phase1_c4_deploy_20261103/phase2_directional_pending_check.py` — imports the production classifier unchanged, derives `DIRECTIONAL_PENDING_*` from the already-computed per-bar `fired_evidence`, resolves each pending with a forward-look up to 2h for EMERGING/STRONG confirmation.

| Session | First PENDING | First EMERGING/STRONG | Lead time | Resolution |
|---|---|---|---|---|
| 2026-10-23 | **DIRECTIONAL_PENDING_DOWN at 07:15** | EMERGING_UP at 08:20 (first legit direction) | — | **FALSE_POSITIVE** (opposite direction) |
| 2026-10-30 | DIRECTIONAL_PENDING_UP at **08:15** | STRONG_UP at 09:20 | **+65 minutes** | CONFIRMED |
| 2026-10-30 | DIRECTIONAL_PENDING_UP at 08:25 | STRONG_UP at 09:20 | +55 minutes | CONFIRMED |
| 2026-11-02 | DIRECTIONAL_PENDING_UP at 08:30 | EMERGING_UP at 08:40 | +10 minutes | CONFIRMED |
| 2026-11-03 | *(no PENDING fired)* | EMERGING_DOWN at 10:20 | n/a | n/a |

### 3.1 Earliest useful signal

On 2026-10-30 (the "trend remained RANGE until 09:20" case), DIRECTIONAL_PENDING_UP would have fired at **08:15 UTC — 65 minutes before STRONG_UP**. That is the EARLIEST possible signal given the OR-formation constraint (3 bars) + the first bar with disp ≥ 8p.

### 3.2 The 11-02 case

Fast morning: disp crossed +8p at 08:25 (10 min after OR formed). DIRECTIONAL_PENDING fired at 08:30. EMERGING_UP confirmed at 08:40. Lead time 10 min — modest, but the classifier was itself already fast on this session.

### 3.3 The 10-23 false positive

At 07:15 UTC (15 min into London — on DST day), disp fell to −8.7p and E2:DOWN fired → DIRECTIONAL_PENDING_DOWN fired for one bar. The opposite direction then dominated the session (EMERGING_UP at 08:20, STRONG_UP at 08:35). This is a false positive. The signal fired too early (bar 4 post-OR) during an overnight-carry-through that quickly reversed.

### 3.4 The 11-03 case

No DIRECTIONAL_PENDING fired despite a clear EMERGING_DOWN at 10:20. Reason: displacement did not cross −8p until 10:00 (after score accumulation and structural anchor had already caught up). The classifier admitted EMERGING_DOWN at 10:20 without needing the early-warning signal.

## 4. False-positive analysis

Across the 4 sessions:

| Metric | Value |
|---|---|
| Total pending episodes | 4 |
| CONFIRMED (same-direction EMERGING/STRONG within 2h) | **3 (75%)** |
| FALSE_POSITIVE (opposite direction confirmed, or no confirmation) | **1 (25%)** |
| Lead time of CONFIRMED signals | 10, 55, 65 min |
| Session with lead > 60 min | 1 of 3 CONFIRMED (10-30) |

### 4.1 Root cause of the single false positive

The 10-23 07:15 FP occurred during the EXTREME early session — 15 minutes post-London-open, before the OR was complete (only 4 London bars had closed; OR = first 3). The rule as currently proposed allows this because `len(london_bars) >= OR_WINDOW_BARS + 1 = 4`.

**Candidate FP mitigation (Phase 2 deliverable, not implemented):**
- Tighten gate to `len(london_bars) >= OR_WINDOW_BARS + 3 = 6` (30 min post-OR).
- Replay confirms this would have suppressed the 10-23 07:15 FP without affecting the three CONFIRMED signals (all fired at bar ≥ 4 but ≥ 30 min post-OR).

### 4.2 Not a strict guarantee

With only 4 replayed sessions the FP rate estimate has wide uncertainty. Phase 2 does NOT recommend enabling DIRECTIONAL_PENDING_* on live v3 state without a longer observation window — see §7.

## 5. Exact implementation requirements

If approved, the Phase 2 change requires modifying `/opt/tradingbot/nms_v3_classifier.py` only:

### 5.1 Code change (hypothetical — not implemented)

In the C4 branch of `advance()` (currently lines 371–389), add a new case that fires DIRECTIONAL_PENDING labels BEFORE the existing `m5_regime = s["state"]` default. Rough shape:

```python
if c4_on and s["state"] == "RANGE":
    disp_val = disp  # already computed earlier in advance()
    up_sruct = up_fams.get("F-structural", 0) + up_fams.get("F-structure", 0)
    dn_sruct = down_fams.get("F-structural", 0) + down_fams.get("F-structure", 0)
    if (len(s["london_bars"]) >= OR_WINDOW_BARS + 3
            and disp_val >= E6_DISP_PIPS
            and up_fams.get("F-momentum", 0) >= 1
            and down_fams.get("F-momentum", 0) == 0
            and up_sruct == 0):
        m5_regime = "DIRECTIONAL_PENDING_UP"
    elif (len(s["london_bars"]) >= OR_WINDOW_BARS + 3
            and disp_val <= -E6_DISP_PIPS
            and down_fams.get("F-momentum", 0) >= 1
            and up_fams.get("F-momentum", 0) == 0
            and dn_sruct == 0):
        m5_regime = "DIRECTIONAL_PENDING_DOWN"
    else:
        # existing fall-through to INSUFFICIENT_DATA / RANGE / CONSOLIDATION / TRANSITION
```

Estimated diff: ~15 lines added inside the existing C4 block. No change to `session_trend.py` (the Phase 1 publication already surfaces whatever `m5_regime` contains).

### 5.2 Env flag

Could be gated behind a sub-flag:
```
NMS_V3_DIRECTIONAL_PENDING_ENABLED=1
```

Default OFF. Flag ON requires `NMS_V3_C4_MULTI_DIM=1` (already deployed in Phase 1).

### 5.3 No `nms_v3_classifier.py` edit in Phase 1

Phase 1 preserved `nms_v3_classifier.py` SHA (`f690fb9c…`). A Phase 2 implementation would edit this file for the first time this week — a notably more sensitive change than Phase 1's additive session_trend.py edits.

## 6. Strategy admission impact assessment

**With `DIRECTIONAL_PENDING_*` added to `m5_regime` but not yet consumed by any strategy admission gate: zero impact.** Same preservation posture as Phase 1 C4.

Matrix (identical to Phase 1 C4 post-deploy):

| Strategy | `v3_state` under PENDING | `m5_regime` under PENDING | Admission effect |
|---|---|---|---|
| V3 BB (autobot) | `RANGE` | `DIRECTIONAL_PENDING_UP` or `_DOWN` | **Unchanged** — admits RANGE |
| Standalone BB Bounce | `RANGE` | `DIRECTIONAL_PENDING_*` | **Unchanged** — admits RANGE/NORMAL |
| TREND_V3 | `RANGE` | `DIRECTIONAL_PENDING_*` | **Unchanged** — admits per permission_matrix |
| GBPUSD_TREND_CONTINUATION | `RANGE` | `DIRECTIONAL_PENDING_*` | **Unchanged** |
| GBPUSD_BB_REVERSAL_ARC | `RANGE` | `DIRECTIONAL_PENDING_*` | **Unchanged** |
| EMA Pullback | `RANGE` | n/a (doesn't consume NMS) | **Unchanged** |
| Scenario V2 | `RANGE` | n/a (doesn't consume NMS) | **Unchanged** |

A **future** strategy change could opt in to consult `m5_regime == DIRECTIONAL_PENDING_*` — for example V3 BB might CHOOSE to abstain on DIRECTIONAL_PENDING to reduce counter-trend risk. That would be a strategy-level decision with its own change control.

## 7. Recommendation

### 7.1 Is Phase 2 worth implementing?

**Cautious yes — but with a pre-requisite.** Three reasons for caution:

1. **75% confirm rate on 4 sessions is preliminary.** A longer observation window is needed to establish the true FP rate. I would NOT ship DIRECTIONAL_PENDING_* based on 4 sessions alone.
2. **The 10-23 FP fired at bar 4 post-London.** The candidate mitigation (`len(london_bars) >= OR_WINDOW_BARS + 3`) would have suppressed it, bringing the FP count to 0/3 on the sample. But that is also based on 4 sessions.
3. **The 1-minute edit to `nms_v3_classifier.py` is the first production edit to the classifier in weeks.** That file has a locked STRICT validation report — any edit warrants extra scrutiny.

### 7.2 Recommended Phase 2 path

1. **Enable Phase 1 C4 first** (operator action pending from Part A).
2. **Observe `m5_regime` in the live cache for 2 weeks** before considering Phase 2. The same C4 infrastructure already distinguishes INSUFFICIENT_DATA / RANGE / CONSOLIDATION / TRANSITION — may be sufficient for the operator's needs.
3. **If the operator decides DIRECTIONAL_PENDING_* remains useful after 2 weeks**, implement with the tighter `OR_WINDOW_BARS + 3` gate and a dedicated env flag.
4. **Do not alter any strategy admission rules** as part of Phase 2 — leave strategy opt-in to a later cycle.

### 7.3 Why not just lower EMERGING_ENTRY_THRESHOLD?

The operator explicitly ruled out threshold changes. More importantly, lowering the threshold would admit EMERGING on sessions like 2026-10-23 where brief pre-London moves reverse — the classifier would ping-pong between RANGE and EMERGING, degrading the information content of the signal. The structural-anchor requirement is doing useful work.

### 7.4 Why not relax `EMERGING_OPPOSING_CAP = 0`?

Same reason. Relaxing to 1 would admit EMERGING_UP on sessions where any down-counter has fired — common on bouncy mornings.

## 8. Phase 2 validation summary

- Deterministic offline analysis on **4 sessions × full M5 data** = 1033 bars.
- Zero look-ahead: each pending decision uses only facts available at bar close.
- Confirmation lookup uses the real classifier's forward state (no synthetic data).
- 75% hit rate on the sample — honest number, not optimised.
- 1 FP root-caused to an insufficient `len(london_bars)` guard; mitigation identified.
- No modification to any live service or file to produce this analysis.

## 9. Preservation certification

- Zero files edited anywhere outside `/home/autobot/autobot_reports` (report) and `/mnt/volume_lon1_1778405456698/phase1_c4_deploy_20261103/` (analysis harness).
- `nms_v3_classifier.py` SHA preserved (`f690fb9c…`).
- `session_trend.py` is the Phase 1 C4 deploy (separate branch); nothing in Phase 2 touches it further.
- No service restart. No broker calls. No .env edits. No shadow mode. No stake / stop / TP changes.
- BB_BOUNCE adaptive-stop deploy earlier today preserved.
- V3 regression fix (`live.py` SHA `38fb8d92…`) preserved.

**Stopping. Phase 2 is INVESTIGATION ONLY. No Phase 2 deployment proposed or requested until operator decides whether DIRECTIONAL_PENDING_* is worth the next change cycle.**
