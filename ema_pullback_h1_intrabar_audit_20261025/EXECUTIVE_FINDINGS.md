# Executive findings — EMA Pullback H1/intrabar compliance audit

Date: 2026-10-25
Mode: **read-only forensic — no code, parameter, service, or order change**
Day under review: **Friday 2026-10-23 (23 setups, 6 fills, −37.25 Method B pips)**

## 1. Final-question answer (brief §FINAL)

> Determine whether the standalone EMA Pullback strategy is failing because:
> A. H1 is admitting weak or insufficiently established trends.
> B. M5 execution is delayed because EMA8 touches are detected only after candle completion.
> C. Both defects are present.
> D. Neither explanation is supported by the evidence.

**Answer: C. Both defects are present. Their empirical impact on Fri
2026-10-23 is UNEQUAL.**

| defect | present? | impact on Fri 2026-10-23 |
| ------ | -------- | ------------------------ |
| A — weak-H1 admission | **Yes** | **High.** 19 of 23 setups (83%) fired during H1 hours an operator would not call clearly established; 2-3 of the 4 Method-B losses are cleanly attributable. |
| B — intrabar detection missing | **Yes** | **Low.** Only 1 of 23 setups had its entry level inside the trigger bar; the other 22 had entry stops below (SELL) / above (BUY) the trigger-bar range, so intrabar detection would not have changed fill timing or fill price. Of the 6 fills, 5 had delays of 10-30 min that are 100% price-action-driven. |

Additional implementation defects observed, not caused by (A) or (B):

* **Multi-touch inflation.** The trigger evaluates every completed M5
  bar whose low (BUY) or high (SELL) touches EMA 8, regardless of
  whether the previous setup within the same pullback has resolved.
  23 raw triggers compress to 11 distinct pullback movements (30-min
  grouping) or 4 contiguous H1 trend episodes. See
  `H1_TREND_COMPLIANCE_AUDIT.md` §6 and `FRIDAY_SETUP_RECONSTRUCTION.csv`.

## 2. The 11:20 fill — special focus

The brief singles out the 11:20 setup that "reportedly filled 30
minutes later" (brief §SECOND MESSAGE).

* Trigger bar 11:20 range: L 13373.05, H 13376.85.
* Entry stop (SELL): 13368.35 (= 5-bar min 13371.35 − 3 p).
* Entry stop is **4.7 pips BELOW the trigger bar's low**.
* First subsequent bar whose low reaches 13368.35: 11:50 (low 13367.35).
* Decomposition of the 30-minute delay:
  - ~5 min = waiting for the 11:20 bar to CLOSE (implementation).
  - ~25 min = waiting for price to come DOWN to 13368.35 (price action).
* Intrabar detection would have saved at most ~5 min on the FRONT of
  the delay. The fill PRICE and the fill BAR would be unchanged. The
  broker SL at 11:50+12p = 13380.35 would still have been hit at
  12:45.

**The 11:20 fill delay is NOT caused by the missing intrabar
detection. It is a geometric consequence of the entry-level formula
on a tight trigger bar whose 5-bar lookback min was far below the
trigger low.**

See `M5_INTRABAR_EXECUTION_AUDIT.md` §4.3 for the bar-by-bar
reconstruction, and `SIX_TRADE_FORENSIC_REVIEW.md` §2.3 for the
causal breakdown.

## 3. Data limitations (brief §5-§7)

* **No tick-level data for Fri 2026-10-23.** The AutoBot tick cache
  (`/opt/tradingbot/data/tick_cache_daily/GBPUSD/`) terminates at
  2026-04-10. See `TICK_DATA_AVAILABILITY.md`.
* **No direct IG H1 for Fri 2026-10-23.** The AutoBot OHLC H1 archive
  (`/opt/tradingbot/data/ohlc/GBPUSD/1H/`) also terminates at
  2026-04-10. The audit relies on H1 reconstructed from the M5 archive —
  which is the same path the strategy itself uses, so no new
  divergence is introduced.
* Within-bar event timing (exact moment of EMA-8 touch, exact moment
  of entry-stop crossing) is **UNDETERMINED** everywhere in the
  reconstruction. The audit does not invent intrabar event sequences
  from M5 OHLC.

## 4. Confirmed implementation defects

| # | defect | location | compliant? |
| - | ------ | -------- | ---------- |
| 1 | H1 trend classifier gates on strict EMA ordering + 1-step slope sign only; no magnitude, no separation, no persistence | `ema_pullback/trend.py:51-104` | **NO** (docstring itself admits: "No minimum separation. No slope magnitude threshold.") |
| 2 | M5 EMA-8 touch detected on completed-bar close only; no intrabar detection | `ema_pullback/pullback.py:11, 72-85`; `service.py:88-170` | **NO** |
| 3 | Fill check (observation mode) runs on next completed M5 bar's OHLC; no live-price fill monitor | `service.py:441-480` | **NO** (observation path); the live-execution path exists but is intentionally guarded off (`price_source.py:144-168`) |
| 4 | Trigger re-arms immediately after cancellation on the next qualifying M5 bar; multiple triggers can fire within the same unresolved pullback | `service.py:88-170` + `pullback.py:72-85` | Faithful to BUILD-SPEC but weaker than the owner's "one setup per pullback" intent in `research/ema_pullback_frequency_20261024/strategy_specification.md` §3-4 |

## 5. Confirmed compliant behaviour

* H1 bars built from exactly 12 completed M5 bars, forming hour never
  emitted, UTC-aligned, mid-price throughout. See
  `H1_DATA_SOURCE_AUDIT.md`.
* 5-bar entry lookback window selects the correct 5 bars under both
  the current and the intended intrabar scheme.
* Completed-M5-close-vs-EMA-21 cancellation (A) correctly enforced; a
  wick cannot cancel.
* H1 trend-flip cancellation (B) correctly enforced.
* EMA calculation is causal (`pandas.ewm(span, adjust=False)`), no
  look-ahead.
* No stale H1 across steps; trend recomputed every poll.
* Only one active setup at a time (slot rule).
* `EXECUTION_ENABLED=false` throughout observation runs.

## 6. Setup-multiplicity classification (brief §9)

From `FRIDAY_SETUP_RECONSTRUCTION.csv` + prior audit
`H1_TREND_COMPLIANCE_AUDIT.md` §6.

| grouping                                              | count on 2026-10-23 | aligns with owner's "3-5 per day"? |
| ----------------------------------------------------- | ------------------: | ----------------------------------- |
| Raw M5 triggers (current implementation)              | 23                  | ~6× too many                        |
| Distinct pullback movements (30-min gap rule)         | 11                  | ~2-3× too many                      |
| Contiguous H1 trend episodes                          | 4                   | within range                        |
| Episodes in A-class (clearly established) H1 hours    | 2                   | within range                        |

The 23 triggers are composed of:

* 1 BUY setup in the 22:00 10-22 → 00:00 10-23 BUY tail.
* 2 BUY setups in the 00:00 10-23 BUY continuation.
* 11 SELL setups in the London AM SELL episode (06:00-11:00).
* 1 SELL setup during H1@12 NONE bounce (via H1@11's SELL state in the
  moment the trigger evaluated — see audit §4).
* 3 SELL setups during the H1@13 one-hour "flash" SELL (all cancelled).
* 5 SELL setups during the afternoon SELL episode (15:00-19:00).

11 of 23 (48%) are repeated EMA-8 touches within the same unresolved
or recently-resolved pullback (see §6 of
`H1_TREND_COMPLIANCE_AUDIT.md`). Four H1 hours produced three setups
each inside a single hour: H1@07 (3), H1@13 (3 — all cancelled on
the one-hour SELL flash), H1@15 (3, two filled, both lost).

## 7. Recommendation surface (brief §12 — forbidden to implement)

The brief explicitly forbids implementing any corrections. The audit
describes the correction surface so the owner can direct next steps:

* **To address defect (A) — H1 selectivity.** Either introduce
  magnitude / separation / persistence thresholds (owner-defined), or
  amend the build-spec to accept the current faithful-but-permissive
  H1 definition and tighten elsewhere. No specific threshold is
  proposed by this audit.
* **To address defect (B) — intrabar detection.** Replace the
  completed-bar `evaluate_trigger` with a live-price touch detector
  that fires at the moment price crosses M5 EMA-8. The entry-level
  lookback window logic can be reused unchanged. The fill-check path
  needs a live-price monitor (either the IG REST source currently
  guarded off, or an IG streaming subscription — the brief disallows
  implementing or wiring either).
* **To address defect (4) — multi-touch inflation.** Replace the
  single-bar trigger with the arm→reject→trigger multi-bar sequence
  from `research/ema_pullback_frequency_20261024/code/detector.py`,
  OR add a "same-pullback" grouping rule, OR require a confirmed
  cancellation + N-bar cooldown before re-arming. Any of these is an
  owner-level decision.

## 8. Deliverables index

| file | contents |
| ---- | -------- |
| `EXECUTIVE_FINDINGS.md`                | this document |
| `H1_DATA_SOURCE_AUDIT.md`              | M5→H1 construction chain, timing, EMA warm-up, staleness |
| `H1_TREND_COMPLIANCE.md`               | pointer to the H1 trend audit published separately |
| `H1_TREND_TIMELINE.csv`                | per-hour H1 state Fri 2026-10-23 (copied from prior audit) |
| `M5_INTRABAR_EXECUTION_AUDIT.md`       | the primary new deliverable — code trace + per-setup intrabar impact |
| `TICK_DATA_AVAILABILITY.md`            | tick / sub-M5 inventory |
| `FRIDAY_SETUP_RECONSTRUCTION.csv`      | per-setup reconstruction with intrabar flags |
| `SIX_FILL_INTRABAR_FORENSIC.csv`       | 6-fill forensic in CSV form |
| `SIX_TRADE_FORENSIC_REVIEW.md`         | 6-fill forensic in prose with per-trade intrabar lens |
| `ROOT_CAUSE_AND_RECOMMENDATIONS.md`    | final answer + correction surface |
| `scripts/intrabar_audit.py`            | reproduction script |
