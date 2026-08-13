# BB_BOUNCE — three re-timings of entry against the H1 verdict

**Date:** 2026-08-13
**Corpus:** same 243 BB_BOUNCE fires as `bb_bounce_h1_live_proxy_20260813.md`, 2026-05-04 → 2026-08-13.
**Context.** Prior pass established:
- Retrospective REJECTED cell (using signal_log `pnl_pips`): 75.5% WR / +7.45 (n=53).
- Live proxy (in-progress REJECTING at fire, band ≤ 5p): 65.5% WR / +5.25 (n=29).
- 10-pt gap between the two.
- Slot agreement crosses 80% at :30 and 90% at :45; 38% of REJECTED fires happen before the level is in the forming H1's range at the fire's own 5m close.

**Headline (first line as requested).** **No re-timing variant closes the 10-point gap; two are worse than TODAY's baseline, and the strongest variant (C) is on-par with the live proxy filter with more fires.** Under a shared reconstructed exit stack, the ceiling (retrospective REJECTED, TODAY entry) is 79.2% WR at n=53. Variant C (fire on flip within same H1) recovers **68.2% WR at n=66**, ~11 pts short of ceiling. Variant B_30 lands at 64.5% (n=62), B_45 at 61.0% (n=59), and Variant A (wait for H1 close) at **55.8% (n=52) — worse than doing nothing.** Per-fire paired deltas: every variant is net-negative on setups that also fire today (A mean −5.00, B_30 −2.63, B_45 −3.06, C −1.37 pips per fire).

---

## Reconstructed exit stack (same for every variant, including TODAY)

- **SL:** each fire's own `sl_pips` from `signal_log.jsonl` (12 or 20 in the corpus).
- **Scale-out:** 50% at +8 pips (`REGIME_MGMT_SCALE_TRIGGER_PIPS` default; corpus median `partial_bank_pips` = 8.1). Runner stop moves to break-even.
- **Runner exit:** BE-hit or 24 × 5m horizon close (2 h).
- **Same-bar SL+scale:** SL first (worst-case).
- **Fill:** the close of the 5m bar identified as the entry bar (reconstruction).

**Metric:** `sim_pnl_pips` = 0.5 × 8 + 0.5 × runner_pnl (if scaled), else full pnl. Win = `sim_pnl_pips > 0`. MFE / MAE computed over 24 × 5m from entry regardless of exit.

**Reconstruction caveats.**
- Entry assumed to fill at the 5m close price — no slippage on the fill itself, no spread. The live system's fills are dispatched from the fire bar and may cross tick boundaries; not modelled.
- H1 verdict computed from the same 5m-aggregated H1 series as the prior pass. Full context in `bb_bounce_h1_live_proxy_20260813.md`.
- Scale-out logic simplified to a single scale point; the live `trade_manager` also has structure-exit, opposite-band TP in RANGE_ROTATION, external close, etc. — not modelled here.
- Sim WR/PnL differ from signal_log figures because `pnl_pips` in the corpus is runner-only for scaled trades (not full realised). All numbers below use the sim consistently for apples-to-apples comparison.

---

## Baselines under the shared sim (before variants)

| Cohort                                 | n    | win%  | med PnL | med MFE | med MAE | mfe≥25 | med slip |
|----------------------------------------|-----:|------:|--------:|--------:|--------:|-------:|---------:|
| **TODAY** (baseline, all fires)        | 242  | 62.8  |  +4.00  |  9.65   | −6.60   |  22    | −0.62    |
| **Retrospective REJECTED ceiling** *(TODAY entry, filtered to fires that end REJECTED)* | 53 | **79.2** | +4.00 | 11.70 | −3.60 | 4 | +1.10 |
| Live proxy (in-progress REJECTING at fire, TODAY entry) | 39 | 69.2 | +4.00 | 9.40 | −5.90 | 1 | +1.00 |

Notes on baselines:
- 1 of 243 has no fire-bar in the archive (`TODAY` n=242).
- The "ceiling" is theoretical — it requires knowing the H1 verdict at fire time, which is impossible.
- The live proxy under the sim runs 69.2% at n=39 (vs 65.5% n=29 in the prior report; different exit convention).

---

## Variant results (all fires, n=243)

| Variant                              | n    | win%  | med PnL | med MFE | med MAE | mfe≥25 | med slip |
|--------------------------------------|-----:|------:|--------:|--------:|--------:|-------:|---------:|
| A — wait for H1 close                |  52  | 55.8  |  +2.10  |  7.45   | −8.55   |  2     | +3.75    |
| B_30 — hold armed, fire ≥ :30 if REJECTING |  62  | 64.5  |  +4.00  |  8.65   | −6.40   |  1     | +3.15    |
| B_45 — same, threshold :45           |  59  | 61.0  |  +4.00  |  8.20   | −8.30   |  1     | +4.45    |
| C — fire on first REJECTING flip within same H1 |  66  | 68.2  |  +4.00  |  9.35   | −5.90   |  1     | +1.80    |

Comparisons vs baselines:
- Vs TODAY (62.8%): A −7.0 pts, B_30 +1.7, B_45 −1.8, **C +5.4**.
- Vs live proxy (69.2%): A −13.4 pts, B_30 −4.7, B_45 −8.2, **C −1.0**.
- Vs REJECTED ceiling (79.2%): all variants short by ≥11 pts.
- Slippage (positive = entry worse than TODAY): C is smallest at +1.80 median; A worst at +3.75 median; **68–73% of variant fires enter worse than TODAY** across all variants.

---

## Expiry counts (setups that did not fire under each variant)

| Variant | fired | expired | expiry reason |
|---------|------:|--------:|---------------|
| A       |  52   |  191    | final H1 not REJECTED (190); no next-H1 bar in archive (1) |
| B_30    |  62   |  181    | no REJECTING slot at or after :30 within the fire's H1 |
| B_45    |  59   |  184    | no REJECTING slot at or after :45 within the fire's H1 |
| C       |  66   |  177    | no REJECTING slot at or after fire's own slot within the H1 |

Variant C expires the fewest setups; B_45 the most. All variants fire on 21–27% of the corpus.

---

## Variant C — entry delay from original signal

| Delay (5m bars) | fires |
|----------------:|------:|
| 0 (fires at same 5m as original) |  40 |
| 1               |   7   |
| 2               |   6   |
| 3               |   5   |
| 4               |   1   |
| 5               |   1   |
| 6               |   1   |
| 7               |   3   |
| 8               |   2   |

Median 0 bars, mean 1.30, max 8. 60% of variant C fires trigger at the same 5m bar as the original — for those, C is just the live proxy under a different name. The other 40% (26 fires) fire later after the level enters the H1 range; those are the fires C uniquely captures.

---

## Recall against the retrospective REJECTED cell

| Variant | fires | of which REJECTED-final | recall of the 53 REJECTED |
|---------|------:|------------------------:|--------------------------:|
| A       |  52   |  52 (100%)              |  98% (missed 1 due to archive edge) |
| B_30    |  62   |  53                     |  100%                     |
| B_45    |  59   |  53                     |  100%                     |
| C       |  66   |  53                     |  100%                     |

B_30, B_45, and C all recover every retrospective-REJECTED fire — they add false positives (9, 6, 13 non-REJECTED fires respectively). A alone drops false positives entirely by definition but pays for it in entry price.

---

## Per-fire paired delta (variant sim_pnl − TODAY sim_pnl, same setup)

Only setups that fired under BOTH TODAY and the variant.

| Variant | paired n | better | worse | flat | med Δ | mean Δ |
|---------|---------:|-------:|------:|-----:|------:|-------:|
| A       |    52    |   10   |  27   |  15  | −1.08 |  −5.00 |
| B_30    |    61    |    6   |  20   |  35  |  0.00 |  −2.63 |
| B_45    |    59    |    6   |  23   |  30  |  0.00 |  −3.06 |
| C       |    65    |    2   |  12   |  51  |  0.00 |  −1.37 |

Every variant is net-negative on the paired subset — waiting costs money on the median trade. C's delta distribution is the tightest (51 flat, mean −1.37); A's is the widest (mean −5.00). This is the direct cost of the retiming: for fires that would have taken anyway, the variant's later entry produces worse realised outcomes on average.

---

## TODAY entry restricted to the fires each variant selects (opportunity cost of waiting)

If you took the SAME set of fires each variant selects, but at TODAY's entry price:

| Variant subset                   | n    | TODAY-WR | Variant-WR | delta   |
|----------------------------------|-----:|---------:|-----------:|--------:|
| A's chosen fires (n=52)          |  52  | 80.8%    | 55.8%      | −25 pts |
| B_30's chosen fires (n=62)       |  61  | 75.4%    | 64.5%      | −11 pts |
| B_45's chosen fires (n=59)       |  59  | 76.3%    | 61.0%      | −15 pts |
| C's chosen fires (n=66)          |  65  | 72.3%    | 68.2%      | −4 pts  |

**This is the most direct measurement of the cost of waiting.** Each variant's filter picks fires that would run 72–81% WR if entered at TODAY's price, but the variant's re-timing costs 4–25 WR points. C is the cheapest; A is the most expensive.

---

## MIXED-day cross-check (n=196)

| Cohort                          | n   | win% | med PnL |
|---------------------------------|----:|-----:|--------:|
| TODAY (MIXED)                   | 195 | 65.6 | +4.00   |
| Retrospective REJECTED (MIXED)  |  45 | 80.0 | +4.00   |
| Live proxy REJECTING @ fire (MIXED) | 33 | 69.7 | +4.00 |
| A (MIXED)                       |  44 | 56.8 | +4.00   |
| B_30 (MIXED)                    |  52 | 67.3 | +4.00   |
| B_45 (MIXED)                    |  50 | 62.0 | +4.00   |
| C (MIXED)                       |  55 | 69.1 | +4.00   |

Same ordering on MIXED: C ≈ live proxy > B_30 > TODAY > B_45 > A. Ceiling gap of 10–11 pts is preserved.

---

## Slippage distribution (positive = worse entry vs original)

| Variant | n  | min    | p25   | med   | p75   | max   | mean  | % worse |
|---------|---:|-------:|------:|------:|------:|------:|------:|--------:|
| A       | 52 | −11.60 | −1.20 | +3.75 | +11.35| +38.20| +5.45 |  65%    |
| B_30    | 62 | −14.05 | −0.25 | +3.15 | +6.70 | +16.55| +3.41 |  71%    |
| B_45    | 59 | −14.05 | −0.70 | +4.45 | +9.35 | +17.65| +3.93 |  73%    |
| C       | 66 | −14.05 | −0.35 | +1.80 | +5.45 | +16.55| +2.68 |  68%    |

- **A has the widest slippage distribution** — some fires enter 11p better than TODAY (level rejected and price rolled further), others 38p worse (H1 closed, then price gapped/ran away). p75 = +11.35 means 25% of Variant A fires give up more than 11 pips of entry price.
- **C is the mildest** — median +1.80, p75 +5.45.
- Even C's "best" fires include some large slippage (max +16.55, which for a 20p SL is a chunk of the trade's edge given away at entry).

---

## Plainly

**Which variant recovers the most of the 10-point gap?**
None recovers meaningfully. Under the shared sim the gap is 79.2 (ceiling) − 62.8 (TODAY) = 16.4 pts. The best variant (C) reaches 68.2 — a 5.4-pt gain over TODAY, or ~1/3 of the possible gap. B_30 recovers 1.7 pts. B_45 loses 1.8 pts. A loses 7.0 pts. The "retrospective REJECTED at TODAY entry" ceiling requires knowing the final verdict at fire time, which is unachievable by any waiting rule because waiting itself costs entry price.

**What does each variant cost in fire count and entry price?**
- A: −78% fires (52 vs 242), +3.75p median slippage, and a full point-wise 27/52 fires worse pnl than TODAY. Not just a smaller cohort — a smaller cohort with worse individual outcomes.
- B_30: −74% fires (62 vs 242), +3.15p median slippage, 20/61 paired fires worse.
- B_45: −76% fires (59 vs 242), +4.45p median slippage, 23/59 paired fires worse.
- C: −73% fires (66 vs 242), +1.80p median slippage, 12/65 paired fires worse (51 flat).

**Does any variant beat the current live proxy (65.5% at n=29 in the prior report, 69.2% at n=39 under this sim)?**
No, on WR. Under the shared sim, the live proxy (69.2% at n=39) matches Variant C (68.2% at n=66) on WR and B_30 (64.5% at n=62) loses 4.7 pts. **The live proxy without any re-timing** already captures the achievable edge. C's contribution is +27 fires at similar WR — that's a fire-count gain, not a WR gain. The other variants degrade WR while also giving away entry price.

**Interpretation:** the 10-pt gap between live proxy and retrospective ceiling is a **structural limit** — it exists because 20 of the 53 REJECTED fires cannot be identified as REJECTED without seeing the future. B_30/B_45/C do identify them all (100% recall) but the pathological slippage on the price of finding them cancels out the WR gain from the filter.

---

## Thin cells

- Variant A: 52 fires total; only 10 "better" in paired delta.
- Variant C delays >3 bars: 7 fires total across delays 4–8; no per-delay stats reliable.
- Variant subsets on MIXED: A n=44, C n=55.
- mfe≥25 counts: TODAY has 22 (of 242), variants have 1–2 each. The variants strip out the tail.
- Cell n=39 for the live-proxy (REJECTING @ fire under sim) is smaller than the 53-fire ceiling — recall gap of 14 fires.

---

## Artefacts (write-once, /tmp)

- `/tmp/bb_retiming_enrich.py` — simulator + variant chooser.
- `/tmp/bb_retiming_report.py` — table generator.
- `/tmp/bb_retiming.json` — enriched corpus (243 records × 5 variant outcomes).
