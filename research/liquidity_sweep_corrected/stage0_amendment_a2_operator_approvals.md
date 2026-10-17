# Stage 0 — Amendment A2 — Operator approvals, final

**Date:** 2026-10-17
**Supersedes:** Stage 0 §2 (ambiguity flags) and the entry-timing default in Stage 0 §3.
**Status:** FROZEN. These decisions are final for this research specification.
**Preceded by:** `c2dd613` (ambiguity audit) + `dc3702f` (amendment A1 — HTF tag only).

---

## 1. AMB-1 — Rejection detector  (APPROVED)

**Primary:** (b) `level_ladder._is_rejection_at_rung` — `level_ladder.py:484-510`.
Pure M5 geometry: pierce + close back + close in far third of the bar's range.

**Sensitivity:** (c) §16 retest-band and (d) §24 sweep-reclaim. Reported **separately**, not combined with the primary. State-machine replay of `qm_decision_shadow` required.

Excluded: (a) `BB_BOUNCE` rejection (spec §7 forbids BB rules).

## 2. AMB-2 — Swing confirmation  (APPROVED)

**Primary M5 swings:** (β) `market_structure.detect_confirmed_swings(highs, lows, asof, N=3)` — `market_structure.py:58-96`. Swings become known at bar k+3's close (walk-forward safe by construction).

**Supplementary HTF swings:** (γ) `level_computation._swing_points` H1 24-bar / 10 p reversal + H4 30-bar / 20 p reversal, as already included in `get_ranked_levels()`.

**Excluded from primary analysis:** (α) `qm_swing_levels` session-scoped swings.

## 3. AMB-3 — Repeated-test departure threshold  (APPROVED)

**Primary:** D-B, `TEST_DEPARTURE_PIPS = 12`. A new test registers when price has entered the 8 p approach band from outside AND has previously exited the band to ≥ 12 p before re-entering.

**Sensitivity:** D-A (any exit ≥ 1 M5 close outside band) and D-C (confirmed swing in opposite direction per AMB-2 primary). Both reported alongside D-B in Sequence B/C counts.

## 4. Entry confirmation  (APPROVED — overrides Stage 0 §3 default)

**Primary (wick-touch):** a subsequent M5 bar's extreme passes the rejection candle's extreme.
- BUY: `cand.high > rejection.high` → fire the moment the touch occurs; fill price `rejection.high + ½ spread` (BUY pays ask).
- SELL: `cand.low  < rejection.low`  → fire the moment the touch occurs; fill price `rejection.low  − ½ spread` (SELL pays bid).

**Secondary (close-above):** a subsequent M5 bar's **close** passes the rejection candle's extreme.
- BUY: `cand.close > rejection.high`, fill at `cand.close + ½ spread`.
- SELL: `cand.close < rejection.low`,  fill at `cand.close − ½ spread`.

**Hard rule — not negotiable:** the rejection candle **may never** confirm its own setup. The confirmation bar must be a strictly later M5 bar than the rejection bar.

Both primary and secondary are measured per event; results reported side-by-side.

## 5. HTF direction  (APPROVED — amendment A1 authoritative)

D1 / H4 / H1 direction is metadata only. Never gates, filters, or alters event population or entries. See [amendment A1](stage0_amendment_a1_htf_tag_only.md).

## 6. Structural sequences  (APPROVED)

Three populations, reported separately — never combined:
- **A: Single liquidity sweep.** The AMB-1 primary rejection follows a single penetration + return.
- **B: Repeated level tests.** Two or three independent tests (D-B rule) followed by rejection at a test; penetration not required.
- **C: Repeated tests + final sweep.** Two or three D-B tests then a penetration-with-rejection on the final attempt.

## 7. Exit evaluation  (APPROVED, with Model 2 deferral)

**Model 1 (approved):** fixed TP 30 p / SL 12 p. Full execution + ledger required.

**Model 2 (deferred):** structural invalidation. Operator has not yet supplied stop-buffer and target-objective definitions. **Will not be executed until operator provides them.** Spec §10 permits deferral.

## 8. All other Stage 0 §3 defaults  (APPROVED en bloc)

Approach band 8 p; D1 window 22:00 UTC FX session; H4/H1 bias via EMA21/50 spread; classical floor pivots from prior completed D1; round-numbers at 50-p multiples within ±150 p; multi-level cluster at 5 p + 15 p separation; London 07–18 / NY 13–18 Europe/London session boundaries; `load_m5()` loader from `bounce_engine/v3/eval_historical.py`; H1 resampler from `h1_pierce.py`; 0.9 p spread + 0.5 p adverse stop slippage.

## 9. Standing rule from this amendment forward

- Do not request approval again for decisions resolved above.
- Only STOP for a **genuinely new** material ambiguity or data-integrity failure.
- Commit and publish incrementally.

## 10. Starting state for Stage 2

Branch head: this commit will become the frozen "pre-execution" tag.
First Stage 2 unit: Deliverable B — independent structural-level approach population across the 643 authorised days.

End of amendment A2.
