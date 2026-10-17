# Phase 3 — Mechanism B: Repeated independent interaction with
#               weakening momentum

Generated: 2026-10-17T12:27:05.437980+00:00

**Episode independence rule (pre-declared):** `gap = 6` bars (30 min) of non-penetration ends an episode; a new episode requires price to have moved ≥ 3.0p away from the attached level in between. This threshold is declared here before any outcome evaluation and will NOT be retuned.

## Q1 — Does elevated independent-episode count discriminate TRUE?

Independent-episode count today (gap=6, min_depart=3p):
- **TRUE** n=3761, median=0.0, mean=0.29, p25=0.0, p75=0.0
- **FALSE** n=5588, median=0.0, mean=0.30, p25=0.0, p75=0.0
- AUC = 0.501

Approach-net slope (linear fit of approach_net_toward across episodes):
- **TRUE** n=93, median=-3.350 p/ep, mean=-4.284, p25=-9.800, p75=+3.850
- **FALSE** n=179, median=-1.250 p/ep, mean=-1.414, p25=-5.800, p75=+3.400
- AUC = 0.433

Max-depth slope (do episodes get deeper or shallower?):
- **TRUE** n=185, median=-7.600 p/ep, mean=-9.825
- **FALSE** n=272, median=-5.500 p/ep, mean=-10.769
- AUC = 0.525

## Q2 — Does the dd27687 'weak approach ↔ TRUE' survive within strata?

Mann-Whitney AUC of `t0_prior_60m_net_toward` within each stratum.
AUC < 0.5 means FALSE candidates have HIGHER net-toward (stronger
approach) — the dd27687 finding. Confirm the sign survives across
session, interaction order, and prior-episode count.

| stratum | n(T) | n(F) | median T | median F | AUC |
|---|---:|---:|---:|---:|---:|
| ALL | 3761 | 5588 | -3.80 | +3.30 | 0.305 |
| session_6-10 | 867 | 1794 | -4.70 | +2.55 | 0.312 |
| session_10-15 | 1510 | 2061 | -4.25 | +4.40 | 0.296 |
| session_15-21 | 1384 | 1733 | -3.05 | +3.20 | 0.305 |
| first_interaction_today | 483 | 1295 | -7.90 | +8.60 | 0.274 |
| later_interaction_today | 3278 | 4293 | -3.60 | +2.10 | 0.327 |
| episodes_1 | 717 | 1054 | -4.30 | +1.60 | 0.307 |
| episodes_2_3 | 185 | 271 | +0.00 | +2.50 | 0.389 |
| episodes_4plus | 0 | 1 | — | — | — |

Same for `t0_prior_60m_eff` (approach efficiency):

| stratum | n(T) | n(F) | median T | median F | AUC |
|---|---:|---:|---:|---:|---:|
| ALL | 3761 | 5588 | -0.129 | +0.125 | 0.309 |
| session_6-10 | 867 | 1794 | -0.164 | +0.092 | 0.316 |
| session_10-15 | 1510 | 2061 | -0.132 | +0.144 | 0.293 |
| session_15-21 | 1384 | 1733 | -0.112 | +0.133 | 0.317 |
| first_interaction_today | 483 | 1295 | -0.245 | +0.293 | 0.262 |
| later_interaction_today | 3278 | 4293 | -0.123 | +0.076 | 0.333 |
| episodes_1 | 717 | 1054 | -0.165 | +0.060 | 0.319 |
| episodes_2_3 | 185 | 271 | +0.000 | +0.107 | 0.400 |
| episodes_4plus | 0 | 1 | — | — | — |

## Interpretation

- The audited independent-episode count (Phase 1 found AUC ~0.56
  with gap=1 and 0.53 with gap=12 on a subsample) is a weak
  discriminator even on the full population. Mechanism B stated
  as 'number of independent approaches' alone is NOT a strong
  distinguisher.
- The approach-net slope and max-depth slope test whether later
  episodes show weaker approaches or shallower penetrations — the
  classical exhaustion pattern. See the slope AUCs above.
- The stratified prior_60m_net_toward AUC checks whether the
  dd27687 'FALSE has stronger approach' finding survives within
  session / interaction / episode-count strata. If the AUC stays
  below 0.5 in every stratum, the effect is not an artefact of a
  single confounder.

All numeric findings in this report are descriptive. Phase 8 will
test whether any of these distinctions produces a +30/-12 positive
net expectancy on actual price movement.
