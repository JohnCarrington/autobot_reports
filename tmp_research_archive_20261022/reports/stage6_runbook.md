# Stage 6 — reversal ML research (no trading)

Source results: read-only historical outputs in
`/mnt/volume_lon1_1778405456698/research/reversal_shadow_20261022/`.
Keep historical candidate definitions exactly as Stage 5; do not tune events.

## Safety and data authority
- Research worktree only. Never change /opt/tradingbot, systemd, NMS,
  broker connectivity or production permissions.
- Verify Stage 5 event file hashes from the signed-off report first, and
  verify underlying candle archives and CLEAN allowlists independently.
- Confirm date boundary, BID vs MID, pip scaling, duplicate handling and
  lookahead-free H1/M5 features.
- DEV = 2024-01-01 through 2025-06-30 (BID); VAL = 2025-07-01 through
  2025-12-31 (BID); OOS = 2026-01-01 through 2026-10-07 (MID).
- Only learn/fit on DEV and choose a model or threshold using VAL.
  **Do not inspect OOS labels until all definitions and settings are frozen.**
  OOS MID differs from BID, so flag basis shift prominently.

## Export features (one independent run per partition)
```bash
python -m unittest discover -s tests/unit -p 'test_reversal_shadow_*.py' -v
python -m scripts.research.reversal_shadow_ml_dataset \
  --archive-root /path/to/validated/dev/CANDLES_ROOT \
  --approved-clean-days /path/to/validated/dev.txt \
  --source-side BID --symbol GBPUSD --pip-size 1 \
  --output-dir /path/to/research/stage6/dev
```
Repeat for VAL and, only after freeze, OOS, with correct partition paths.
No inferred or invented source roots: confirm actual copied paths on host.

## Label/feature specification

Research label is whether the price is at least +10 pips in the candidate
direction at the **close** of the 24th M5 bar after next-open entry. It is a
reversal-strength proxy, not trading profit, because execution costs and
intrabar path are ignored.

Whitelist for ML features (never infer features from all CSV columns):
`side`, `utc_hour`, `h1_range_pips`, `h1_body_signed_pips`,
`h1_close_location`, `rejection_overshoot_pips`,
`prior_three_h1_net_signed_pips`, `confirm_delay_m5`,
`confirm_body_signed_pips`.

Never train on `event_at_utc`,
`outcome_future_24bar_end_pips_DO_NOT_USE_AS_FEATURE`, or
`label_end_plus_10_pips` as a feature. Labels are evaluated after all
24 future M5 bars are present; missing data is censored, never counted
as a negative label.

## Model evaluation plan

1. Before training, audit Stage 6 rows against 20 randomly selected
   candle windows across BUY/SELL, sessions, and missing data.
2. Within DEV, use chronological train/evaluation folds with an event
   horizon embargo (minimum 24 bars, including overlapping events).
3. Compare intercept-only base rate, a simple pre-specified logistic
   regression (standardisation fitted on training folds only), and a
   shallow tree model (if dependencies already exist in research env).
   Small model search budgets only; do not retune after OOS.
4. Fit preprocessing only on DEV. Select once using VAL. Record
   model, complete feature list, preprocessing, random seeds and threshold.
5. Report eligible N, label prevalence, precision/recall, Brier score,
   calibration and uplift over base rate at pre-registered alert volumes.
   Stratify by session and BUY/SELL only as descriptive analysis.
6. Freeze every setting and hash the model artefacts BEFORE opening OOS.
   Evaluate OOS once; show its MID-vs-BID basis caveat.
7. If OOS has no stable improvement, declare NO SUPPORTED ML EDGE.
   Do not deploy or silently iterate on OOS.
8. Return factual numerical report with reproducible paths, code/data hashes,
   censored counts and failure modes. No automatic trade execution or
   live service deployment is authorised.

This stage creates research evidence, **not a running AI agent**.
