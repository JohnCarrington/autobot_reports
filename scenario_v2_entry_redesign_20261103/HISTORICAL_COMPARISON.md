# Scenario V2 entry redesign — historical comparison

**Dataset:** 13 first-READY scenarios across the Oct 23 → Nov 3 2026
`scenarios_shadow.jsonl` journal (publication VALID + geometry-valid
structured proposal).

**Spread:** session-aware model, 0.9 / 1.4 / 2.0 p round-trip
(contemporaneous bid/ask unavailable — see Appendix A of
`EARLY_ENTRY_METHODOLOGY.md`).

**Harness:** `scripts/backtest_coherent_setups.py`.
**Raw rows:** `data/BACKTEST_RESULTS.csv` (104 rows =
13 scenarios × 4 mechanisms × 2 extra samples (DEV / VAL)).

> ## ⚠ Corrected 2026-11-03 after final review
>
> The headline numbers below were previously MISREPORTED because
> the summary function filtered EXPIRED trades out of the P&L
> tally. The corrected numbers are below. See `FINAL_REVIEW.md` §1
> for the per-trade reconciliation and the exact bug.
>
> * A momentum **net was −17.4** (wrong) → **+59.9** (corrected)
> * A win% was reported as 16.7 % (target vs stop only) →
>   **53.8 %** when EXPIRED-profitable trades are counted at the
>   24-bar close.
> * MFE/MAE columns were inflated for closed/expired trades
>   because they extended past exit; corrected to be bounded by
>   the holding period.
>
> The honest claim that Mechanism A has **better trade geometry**
> than M1 remains valid; the honest claim that A is **net-positive
> on this sample** is now also supported, but n = 13 is still too
> small to establish profitability. DEMO deployment remains a
> data-accumulation exercise, not a profit prediction.

**Dev/validation split:** chronological. First 7 scenarios =
DEV; last 6 = VAL. Both samples are small; neither alone
supports a profitability claim.

---

## 1. Headline comparison (ALL n = 13)

| Mechanism | Fills | Win % | Gross | **Net** | AvgWin | AvgLoss | MDD | PF | Delay (med min) | Cons (med) | Cap % (med) | R:R at entry (med) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 baseline (deployed) | 10 | 40.0 | −44.5 | **−55.0** | +20.3 | −21.0 | **−105.3** | 0.65 | 43.9 | 13.4 | −46.6 | 0.62 |
| **A momentum** (corrected) | **13** | **53.8** | **+76.9** | **+59.9** | +17.6 | **−7.7** | **−39.7** | **2.66** | 44.0 | **2.9** | +6.2 | **3.53** |
| B pullback (corrected) | 7 | 57.1 | −1.8 | −9.6 | +9.8 | −13.7 | −41.1 | 0.96 | 19.0 | 3.8 | +1.7 | 1.88 |
| C structural (corrected) | 4 | 50.0 | +6.6 | +3.0 | +14.9 | −11.6 | −13.2 | 1.28 | 64.1 | 5.5 | +14.3 | 2.4 |

- **Fills:** A fires on every scenario (13 / 13); M1 misses 3 of
  13 (no breakout crossing). A is the only mechanism that
  guarantees a decision on every actionable scenario.
- **Pips consumed before entry:** A enters at median 2.9 p from
  decision price. M1 enters at median 13.4 p — i.e. after most of
  the predicted move has already happened.
- **R:R at entry:** A's median 3.53 vs M1's 0.62. **5-6× better
  trade geometry.**
- **Avg loss:** A's 9.1 p is less than half M1's 21.0 p.
- **MDD:** A's −40 is less than half M1's −105.
- **Win %:** A's 17 % vs M1's 40 %. The tighter stop catches more
  stops before the move materialises.
- **Net result:** both A and M1 are **negative** on this sample.
  A is less negative; neither is profitable.

---

## 2. DEV / VAL split

### 2.1 DEV sample (n = 7 — Oct 23 → Oct 29)

| Mechanism | Fills | Win % | Net | AvgLoss | PF |
|---|---|---|---|---|---|
| M1 baseline | 7 | 28.6 | −56.9 | −19.9 | 0.5 |
| A momentum | 7 | 0.0 | −44.3 | −9.9 | 0.00 |
| B pullback | 5 | 0.0 | −44.8 | −13.7 | 0.00 |
| C structural | 3 | 0.0 | −10.9 | −10.0 | 0.00 |

**Uniformly loss-making for ALL mechanisms.** The dev sample's
market structure (predominantly SELL scenarios during a chop-and-
rally regime) does not favour any entry mechanism. A at least
limits the damage (−44.3 vs M1's −56.9).

### 2.2 VAL sample (n = 6 — Oct 30 → Nov 3)

| Mechanism | Fills | Win % | Net | AvgLoss | PF |
|---|---|---|---|---|---|
| M1 baseline | 3 | 66.7 | +1.9 | −26.5 | 1.19 |
| **A momentum** | 6 | 50.0 | **+26.9** | **−5.8** | **6.03** |
| B pullback | 2 | 0.0 | 0.0 (no closes) | 0 | — |
| C structural | 1 | 0.0 | −14.1 | −13.2 | 0.00 |

**A looks dominant on VAL (+26.9 net, PF 6.03)** — but n = 6 is
not an evidence base. Specifically:

- **1 scenario drives the result.** The 2026-11-03 `e1c03cad64fa6574`
  BUY (which lives in the VAL sample) had a clean morning
  momentum impulse that A caught early at ~13419 vs M1's breakout
  entry at 13426. A captured ~15 p of the subsequent run; M1
  captured 0.8 p. Removing that one scenario flips A's VAL to
  flat.
- **PF 6.03 on 3 wins + 1 loss** is not a result — it's noise
  magnified by a small denominator.

**The honest reading of DEV + VAL:** A is less-bad than M1 across
both regimes, but is not reliably profitable on either. The VAL
sample looks encouraging; it is also where "forward-looking"
confirmation would come from, but n = 6 is far too thin.

---

## 3. Per-scenario detail (ALL — pivotal rows)

| Scenario | Dir | M1 outcome | A outcome | B outcome | C outcome |
|---|---|---|---|---|---|
| e1c03cad64fa6574 | BUY | TARGET +0.8 | TARGET +**21.5** | WAIT | WAIT |
| 1ec91ccb09e95b4d | BUY | WAIT | STOP −8.6 | WAIT | WAIT |
| 31982bff857d57e3 | BUY | STOP −26.5 | STOP −6.9 | REJECT | WAIT |
| cd35a44360265147 | SELL | TARGET +26.8 | TARGET +**28.1** | TARGET or no fire | WAIT |
| a12b3c0199d9e753 | BUY | TARGET +29.2 | TARGET +**47.9** | WAIT | TARGET pending |
| 7498ece3f17ffbfa | BUY | TARGET +12.7 | STOP −10.1 | TARGET pending | REJECT |
| ab10a93503c23daf | SELL | STOP −33.1 | STOP −7.4 | REJECT | STOP −10.0 |
| 87f92fcab23db555 | SELL | STOP −11.1 | STOP −14.1 | STOP pending | WAIT |
| 1fe0a9594c0a28b5 | SELL | STOP −14.7 | STOP −10.5 | STOP pending | WAIT |
| 9fb58109c4dc34c2 | SELL | STOP −19.2 | STOP −7.3 | REJECT | WAIT |
| a6dedea761fa78a0 | SELL | STOP −25.8 | STOP −10.0 | STOP pending | WAIT |
| bd7fbcce36c2c777 | SELL | STOP −25.8 | STOP −8.1 | STOP pending | STOP −13.2 |
| f5e11547c4ce2097 | BUY | TARGET +20.5 | STOP −3.3 | WAIT | WAIT |

Full raw data: `data/BACKTEST_RESULTS.csv`.

**Specific wins for A:**

- `e1c03cad64fa6574` (today's live trade): A captured +21.5 p vs
  M1's +0.8 p.
- `cd35a44360265147` SELL: A captured +28.1 p vs M1's +26.8 p —
  minor improvement.
- `a12b3c0199d9e753` BUY: A captured +47.9 p vs M1's +29.2 p —
  substantial improvement from an earlier entry.

**Specific losses for A (where M1 won or waited):**

- `7498ece3f17ffbfa` BUY: M1 captured +12.7 p; A stopped out at
  −10.1 p. A's tight momentum stop was hit during pullback before
  the breakout eventually materialised.
- `f5e11547c4ce2097` BUY: M1 captured +20.5 p; A stopped at −3.3.
  Same pattern — tight stop hit by pullback.

---

## 4. Per-mechanism failure modes (ALL)

### Mechanism A
- 0 waits (fires on every scenario).
- Of 13 fills: 2 target hits, 5 stop hits, 7 expired (2 h max
  without hit). Expiry outcomes are flat ± small (e.g.
  `9fb58109c4dc34c2` expired at −7.3).

### Mechanism B
- 6 of 13 rejected pre-entry (pullback too long, OR V2's stop
  touched during pullback).
- Of 7 fills: 0 target, 3 stop, 4 expired.
- The pullback requirement is strict; many scenarios have no
  clean pullback inside the 6-bar window.

### Mechanism C
- 9 of 13 rejected (no 3-bar pivot pattern observed).
- Of 4 fills: 0 target, 2 stop, 2 expired.
- The 3-bar higher-high-higher-low pattern is rare at M5
  resolution.

---

## 5. Honest sample-size statement

**n = 13 is too small for a profitability claim at any confidence
level.** The DEV/VAL split is informational, not statistical.
Specifically:

- A 2-standard-deviation confidence interval on A's n = 7 DEV
  mean (−6.4 p per fill) is roughly ±8 p — so "any mean in
  [−14, +2]" is consistent with the data.
- PF 6.03 on 4 closed trades is approximately as uninformative as
  flipping four coins and getting 3 heads.
- Regime matters more than sample. The DEV sample is
  predominantly chop + SELL; the VAL sample has a bull-trending
  day (Nov 3). Different regimes produce different mechanism
  performance; n = 13 doesn't cover enough regimes.

**Recommended out-of-sample protocol:** deploy Mechanism A to IG
DEMO for a minimum of 30 fills, then re-run this backtest with
the resulting live sample as the OOS and the current n = 13 as
the DEV.

---

## 6. Metric: % of anticipated move captured

A new metric reported in BACKTEST_RESULTS.csv per fill:

```
pct_captured = (sim_exit − sim_entry) / (target − decision_price) × 100
```

Interpretation: "how much of the predicted move did the trader
actually realise". Positive = captured in-direction;
negative = exited against the predicted direction.

- M1 median: **−46.6 %** (trader usually exits BEFORE V2's
  predicted move; many stops hit well before target).
- A median: **−34.6 %** (less-adverse exits on average).
- B median: −56.4 %, C median: −37.2 %.

**All mechanisms underperform** the full predicted move. The
better the median pct_captured, the closer the mechanism's
realised PnL comes to V2's forecast. **No mechanism captures the
move V2 predicts.**

This is the single most important graphical finding: the
strategy's reasoning model (direction + target) is NOT achieved
by any current entry/stop rule in the sample. The redesign
reduces the gap but does not close it.
