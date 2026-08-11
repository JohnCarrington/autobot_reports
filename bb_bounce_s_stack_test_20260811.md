# BB_BOUNCE_S — do `pd_pct` and `regime_confidence_at_fire` stack?

**Question.** Two independent findings on the same strategy:
- `bb_bounce_pdrange_direction_20260811`: SELL fires, ρ(pd_pct, pnl) = +0.517, n=78.
- `estate_findworks_20260811`: `regime_confidence_at_fire = LOW`, n=37, WR 70.3%, sum +192 p.

Are these two independent conditions or one population?

## Corpus (all `GBPUSD_BB_BOUNCE_S`)

| slice | n |
| :--- | ---: |
| all rows | 126 |
| pnl populated | 124 |
| mfe populated | 78 |
| `regime_confidence_at_fire` populated | 86 |
| `pd_pct` populated (reconstructed) | 124 (100% of pnl-scored) |
| **stack population** (SELL, pnl, `pd_pct`, `regime_conf ∈ {LOW,MED,HIGH}`) | **86** |

The strategy is SELL-only; all 126 rows are direction=SELL. `pd_pct` is
reconstructed from `cache/htf/GBPUSD_D1.json` using the same rule as the
prior pass (100·(entry−PDL)/(PDH−PDL); prior completed D1 bar).
`regime_confidence_at_fire` values as a label are `LOW/MEDIUM/HIGH`
(count 37/33/16 in the stack population); the field is null on 40 of
126 rows and takes numeric-float values on a further handful (excluded
here — they are one-off buckets, not comparable to the label form).

## 1. Overlap

**86 SELL fires have both fields populated.**

| bucket | n |
| :--- | ---: |
| `pd_pct ≥ 75` | 36 |
| `regime_conf == LOW` | 37 |
| **both** | **16** |

Under independence, expected overlap ≈ (36 × 37) / 86 ≈ **15.5**.
Observed **16**. The two conditions co-occur no more than chance.

**Cross-tab.**

| | LOW | not-LOW | total |
| :--- | ---: | ---: | ---: |
| `pd_pct ≥ 75` | 16 | 20 | 36 |
| `pd_pct <  75` | 21 | 29 | 50 |
| **total** | 37 | 49 | 86 |

**Spearman ρ(pd_pct, regime_conf-ordinal LOW=1/MED=2/HIGH=3), n=86: −0.159.**
Weak, essentially independent.

## 2. The four cells

| cell | n | WR% | med pnl | **sum pnl** | med mfe | mfe ≥ 25 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **HI_pd + LOW**     | 16 | 81.2 | +8.25 | **+139.9** | 13.25 | 0 |
| **HI_pd + not-LOW** | 20 | 80.0 | +7.15 | **+123.9** | 13.23 | 2 |
| **LO_pd + LOW**     | 21 | 61.9 | +0.65 | **+52.1**  | 10.25 | 0 |
| **LO_pd + not-LOW** | 29 | 31.0 | −11.95 | **−229.4** | 7.30 | 1 |

- HI_pd cells (36 fires combined) sum **+263.8 p**, WR ~80% either side
  of the LOW split.
- LOW cells (37 fires combined) sum **+192.0 p**.
- The **−229.4 p bleed sits entirely in `LO_pd + not-LOW`** (n=29). That
  single cell is bigger than any one of the three positive cells.

None of the four cells is below n=8. `mfe ≥ 25` counts are so sparse
(0-2 per cell) they should not be read.

## 3. Which condition carries more?

### Within LOW-confidence SELLs (n=37) — does `pd_pct` still grade?

- ρ(pd_pct, pnl) = **+0.218** (weakly positive).
- `pd_pct ≥ 75`: n=**16**, med pnl **+8.25**, sum **+139.9 p**.
- `pd_pct <  75`: n=**21**, med pnl **+0.65**, sum **+52.1 p**.

**Yes** — pd_pct still grades outcomes inside the LOW-confidence bucket.
Even LOW-conf fires do 2.7× better on median pnl when pd_pct is high.

### Within HI-pd SELLs (`pd_pct ≥ 75`, n=36) — does confidence still matter?

- ρ(regime_conf-ordinal, pnl) = **−0.163** (weak, wrong-signed for
  "LOW is best").
- Per confidence:

| conf | n | WR% | med pnl | sum pnl |
| :--- | ---: | ---: | ---: | ---: |
| LOW | 16 | 81.2 | +8.25 | +139.9 |
| MEDIUM | 14 | 78.6 | +9.25 | +102.2 |
| HIGH | 6 | 83.3 | +6.10 | +21.7 |

**No** — inside HI_pd, all three confidence buckets are net-positive.
LOW leads by sum but that's mostly cell size; median pnl is highest
in MEDIUM. HIGH n=6 is thin.

## Live availability — last 60 days

Signal-log coverage on all fires (any strategy) written in the past 60
days (n=333):

| field | populated / 333 |
| :--- | ---: |
| `dist_to_pdh_pips` | 32 (10%) |
| `dist_to_pdl_pips` | 32 (10%) |
| `dist_to_00_pips` | 173 (52%) |
| `dist_to_0050_pips` | 173 (52%) |
| `at_level` | 56 (17%) |
| `dist_to_nearest_level_pips` | 56 (17%) |
| `regime_confidence_at_fire` | 247 (74%) |
| `engine_regime_confidence_at_fire` | 281 (84%) |

For the 72 BB_BOUNCE_S fires in the same 60-day window: **all four
inputs used above are reconstructable at 100%** — `pd_pct` from the D1
cache (prior completed bar), `regime_conf` is already in the row 72/72
of the time on BB_BOUNCE_S, `at_level` was live-logged on 28 of 86 in
the stack corpus and reconstructed via nearest-of-{round-00, round-50,
PDH, PDL, prior-session hi/lo} for the other 58.

**Can each be computed at evaluation time (not just logged after)?**

- **`pd_pct`** — yes, cheaply. Needs the last completed D1 bar's PDH/PDL,
  which lives in `cache/htf/GBPUSD_D1.json` and is refreshed by the
  existing D1 pipeline (`d1_direction.compute_d1_direction_from_cache`
  uses the same source). No dependency on any post-fire logging.
- **`regime_confidence_at_fire`** — already emitted at fire time when
  the regime engine has classified the current bar. 247/333 recent
  coverage means it's populated 74% of the time; the gap is mostly
  fires where the classifier hasn't produced a fresh call yet. It is
  not "logged after" — it's part of the fire snapshot when present.
- **`at_level`** — populated in the row only 56/333 (17%). To use it
  live it would have to be **computed at eval time**, not read from
  the row. The reconstruction here (nearest of six level types ≤ 8 p)
  is trivial arithmetic and requires only PDH/PDL + entry + a small
  set of round-number rules; no fresh feed dependency.

## Verdict — stack, overlap, or one is redundant?

**They stack, but not equally.**

- The two conditions are **statistically independent** on this corpus
  (overlap 16 vs expected 15.5; ρ = −0.16). They are not two names for
  the same population.
- **`pd_pct ≥ 75` is the more general condition.** HI_pd fires are
  net-positive at ~80% WR regardless of the confidence label
  (LOW +139.9 p; not-LOW +123.9 p).
- **LOW confidence is not redundant when pd_pct < 75.** `LO_pd + LOW`
  is +52.1 p (WR 61.9%) versus `LO_pd + not-LOW` −229.4 p (WR 31.0%) —
  LOW confidence rescues the low-pd_pct bucket from being the strategy's
  main bleed.
- **HIGH confidence at HI_pd (n=6) is positive but thin;** the LOW-vs-not
  gap inside HI_pd is small enough that adding LOW to a pd_pct ≥ 75
  cohort doesn't add meaningful information here.
- Practically, the two variables index **different bad populations**:
  low pd_pct with confident (not-LOW) regime is where the strategy
  loses; either high pd_pct or LOW confidence is enough to move the
  cell to positive-sum.

No recommendations.

---
*Sources: `logs/signal_log.jsonl`, `cache/htf/GBPUSD_D1.json`,
`cache/htf/GBPUSD_H1.json` + archive. All reconstruction done in `/tmp`
and cleaned by explicit name.*
