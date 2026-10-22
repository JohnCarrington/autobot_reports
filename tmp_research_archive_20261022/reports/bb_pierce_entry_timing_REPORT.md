# H1 BB pierce — when to enter?

**Corpus:** Same 90 trading days (2026-04-24 → 2026-08-13) and same H1 synthesis as `bb_pierce_REPORT.md`. The 337-pierce set is **A's** eligible universe (pierces where H1 j+1 closes back inside). For **B/C/D** the corpus is expanded to **all 542 H1 pierces** (high>BB_UPPER or low<BB_LOWER at bar j, no filter on the next bar) so invalidation can be measured. Confirmation rate across the full 542-pierce set: **62.2% confirmed / 37.8% invalidated** (next H1 closed back outside).

**Entries assume fills at bar closes. No spread, no slippage.**

Walk: 5m bars forward from entry, cap 24 hours (288 bars), terminate on re-touch of the pierce extreme. Excursion = max run in reversal direction from entry. Adverse = max against, first-touch not required. Time-to-peak = 5m bars × 5 min.

Preceding-move quartiles (24h H1 lookback into the pierce), from the full 542-pierce set: Q1 ≤ 45.1 p, Q2 ≤ 61.8 p, Q3 ≤ 80.0 p, Q4 > 80.0 p (max 213.7 p).

---

## Per-variant summary

| Variant | Definition | n eligible | Median entry offset from pierce extreme | Median excursion | p25 / p75 excursion | Median adverse | %≥10p | %≥25p | Median time to peak |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **A** | Close of H1 j+1, only if closed back inside | 335 / 542 | **12.2 p** | 12.1 p | 3.3 / 35.3 | 11.4 p | 54.6% | 33.7% | 105 min |
| **B** | First 5m close inside H1(j) band during the confirming hour | 394 / 542 | 10.3 p | 8.6 p | 2.7 / 29.3 | 9.7 p | 47.0% | 28.9% | 60 min |
| **C** | B, but no earlier than 15 min into confirming hour | 362 / 542 | 10.5 p | 10.1 p | 3.4 / 31.8 | 10.1 p | 50.0% | 29.3% | 75 min |
| **D** | Close of the piercing H1 bar itself | 542 / 542 | **6.7 p** | 6.6 p | 1.9 / 22.3 | 7.4 p | 41.0% | 22.3% | 22 min |

**A** fires on the 335 pierces that ultimately confirmed (2 lost to warm-up timing edge). **D** fires on every pierce. **B** misses 148 pierces where no 5m closed back inside the H1 band during the confirming hour; **C** misses 32 more that would have qualified only in the first 15 min.

## B and D — split by whether the H1 subsequently confirmed

Both B and D commit before the confirmation is known. Splitting the entries by whether the H1 j+1 later closed inside (confirming) or outside (invalidating) shows what the pre-commit variants are actually swimming in:

| Split | n | Median exc | Median adverse | %≥10p | %≥25p | Median time to peak |
|---|--:|--:|--:|--:|--:|--:|
| B — H1 confirmed | 307 | **14.0 p** | 9.5 p | 58.3% | 36.2% | 120 min |
| B — H1 invalidated | 87 | **1.7 p** | 10.1 p | 6.9% | 3.4% | 5 min |
| D — H1 confirmed | 337 | **12.1 p** | 7.4 p | 55.5% | 32.0% | 90 min |
| D — H1 invalidated | 205 | **2.6 p** | 7.7 p | 17.1% | 6.3% | 5 min |

On the confirmed subset, B and D deliver essentially A-class outcomes. On the invalidated subset, they collapse: median excursion 1.7–2.6 p, adverse 8–10 p — a straight loser. **The 38% invalidation rate is what pre-commitment costs.** Neither B nor D has any way to filter it out at the moment of entry.

## Cost of waiting

Matched-pierce medians (only pierces where both variants fire, so the same underlying reversal is being measured from two different entry timings):

| Comparison | n matched | Median entry give-up in reversal direction | Median excursion diff from own entry |
|---|--:|--:|--:|
| **D vs A** (all confirmed pierces) | 335 | D enters ~4 p earlier in reversal direction | A captures 2.6 p less than D |
| **B vs A** (confirmed pierces where B fires) | 307 | B enters ~2 p earlier | A captures 2.1 p less than B |
| **D vs B** | 394 | D enters ~1–2 p earlier | B captures 1.2 p less than D |

Waiting for the H1 close costs a **median ~3–5 p of entry price** and a **median ~2–3 p of measured excursion from your own entry**. That's the debit side for A.

## Cost of not waiting — invalidation

Full pierces universe **542**. Broken down:

- **A**: never enters an invalidated pierce, by definition. 0 losers from this bucket.
- **B**: **87** invalidated entries (22% of B's 394 fills). Median excursion 1.7 p, median adverse 10.1 p → these are near-pure losers.
- **C**: same shape — the 15-min floor filters ~5 of the very worst same-hour re-entries but does not change the invalidation-rate exposure meaningfully.
- **D**: **205** invalidated entries (38% of D's 542 fills). Median excursion 2.6 p, median adverse 7.7 p.

## Expectancy per trade — fixed TP, adverse-median stop

For each variant, simulate the trade set as: hit → +TP, miss → −(median adverse across the losing subset). Pips per trade × n = total pips. This isn't a real trading simulation — no per-trade stop, no trail — but it is a fair like-for-like across variants.

| Variant | n | TP=10p hit% | Exp/trade | Total | TP=25p hit% | Exp/trade | Total |
|---|--:|--:|--:|--:|--:|--:|--:|
| **A** | 335 | 54.6% | **+1.27 p** | **+424 p** | 33.7% | **+0.85 p** | **+283 p** |
| B | 394 | 47.0% | −0.50 p | −198 p | 28.9% | −0.26 p | −104 p |
| C | 362 | 50.0% | +0.25 p | +90 p | 29.3% | −0.46 p | −166 p |
| D | 542 | 41.0% | +0.02 p | +12 p | 22.3% | −0.48 p | −259 p |

**A is the only variant with positive expectancy at both TPs, and it wins on both per-trade AND on total pips despite firing on 40% fewer pierces.** The confirmation filter is what earns the money.

## Does the answer differ by stretch? Quartile split

| Variant | Q1 (≤45p) | Q2 (≤62p) | Q3 (≤80p) | Q4 (>80p) |
|---|---|---|---|---|
| A n / med_exc / %≥10 / %≥25 | 91 / 6.3p / 41% / 22% | 78 / 12.5p / 53% / 33% | 89 / 13.7p / 60% / 32% | **77 / 26.1p / 68% / 51%** |
| B n / med_exc / %≥10 / %≥25 | 115 / 6.4p / 36% / 18% | 100 / 8.8p / 46% / 28% | 102 / 6.9p / 45% / 27% | **77 / 24.6p / 68% / 49%** |
| C n / med_exc / %≥10 / %≥25 | 109 / 6.3p / 38% / 18% | 87 / 9.8p / 49% / 29% | 96 / 10.2p / 50% / 28% | **70 / 24.7p / 70% / 49%** |
| D n / med_exc / %≥10 / %≥25 | 136 / 5.7p / 39% / 16% | 135 / 5.6p / 36% / 22% | 135 / 6.4p / 37% / 20% | **136 / 11.3p / 52% / 32%** |
| D-confirmed n / med_exc / %≥10 / %≥25 | 92 / 9.9p / 50% / 21% | 78 / 11.4p / 58% / 35% | 89 / 9.1p / 47% / 29% | **78 / 24.0p / 69% / 46%** |

Matched-pair A-vs-D entry-price give-up (median), by quartile:

| Q | Q1 | Q2 | Q3 | Q4 |
|---|--:|--:|--:|--:|
| A gives up in entry (p) | +3.0 | +4.6 | +3.6 | +4.2 |
| A extra excursion loss from own entry (p) | −2.7 | −2.9 | −2.0 | −2.9 |

**On Q4 (big-stretch) pierces, A, B, C and D-confirmed converge — all deliver 68–70% ≥10p and 46–51% ≥25p with 24–26 p median excursion.** The extra 4 p of entry price D captures does not change the win rate at 10p or 25p, because on a 26 p median move losing the first 4 p is noise. Early entry does **not** matter more on big-stretch pierces — if anything, waiting is *cheapest* on Q4 because the reversal has room to keep giving.

On Q1–Q3 (smaller stretch), A pulls further ahead of the pre-commit variants: A's 60% ≥10p in Q3 vs B's 45% and D-all's 37%. Smaller moves are exactly where the invalidated pierces cluster (see D's Q1–Q3 median exc dropping to 5.7–6.4 p), and the confirmation filter's value is largest there.

## Verdict

**Enter at the close of the confirming H1 bar (variant A).**

- Only variant with positive expectancy at both 10p and 25p TP.
- The 38% invalidation rate is the entire game. A is the only variant that doesn't trade it.
- The cost of waiting is small — median 3–5 p of entry price, median 2–3 p of excursion from own entry — and disappears entirely on Q4 pierces where the move is big enough to swallow it.
- On matched confirmed pierces, D and A produce statistically indistinguishable outcomes; the only reason D's headline numbers are worse is the 205 invalidated pierces it has to trade blind.

**If a 60-minute delay is genuinely blocking (e.g. session-cutoff), C is the fallback.** C fires ~30 min earlier than A on median, gives up ~2 p of extra invalidation exposure and posts +0.25 p/trade at 10p (versus A's +1.27). It is worse than A but is the least-bad of the pre-commit variants.

**Do not use B or D unbaked.** Both carry a 22%/38% dud rate that pulls the aggregate below break-even at any TP.

## Thin cells flagged / caveats

- B invalidated subset n=87, D invalidated n=205 — sample sizes are healthy. B-Q4 confirmed subset would be worth splitting out but wasn't; would need larger corpus.
- The "median adverse" for A (11.4 p) is nearly equal to its median excursion (12.1 p). A stop tighter than ~12 p will get chopped out even on trades that ultimately reach 10 p+. This is a stop-design constraint, not an entry-timing one.
- Expectancy simulation assumes losers are stopped at median-adverse of the *losing subset*, a rough proxy. A more realistic per-trade stop simulation would tighten (or loosen) the losses but is unlikely to reorder the four variants.
- The 542 unfiltered pierces include 12 days at the boundaries where the D1 pivot cache or 5m coverage may be incomplete; the H1 BB series was built from the same resample used in the prior report and matches the 337 confirmed count exactly.
- Bars-to-peak is a lower bound on hold time — the actual peak may occur mid-bar; 5m granularity puts a ±2.5 min band around each figure.

**Scripts in /tmp for cleanup:** `bb_pierce_entry_timing.py`, `bb_pierce_entry_timing_rows.csv`, `bb_pierce_entry_timing_REPORT.md`. Source data `/tmp/bb_pierces_full.csv` untouched.
