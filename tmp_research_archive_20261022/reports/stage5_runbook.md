# Stage 5 — Production-host historical study handoff (READ ONLY)

**Do not run this inside the live AutoBot process. Do not restart any services, merge this branch, install packages in the production venv, or contact IG.**

## Purpose

Run the candidate engine on the approved historical archive, not on a five-day fixture. Existing GitHub CI validates the code but **cannot reach server 161's private candle/archive data**.

## Claude Code / operator instructions

1. On server 161, first record `hostname`, `date -u`, `git -C /opt/tradingbot rev-parse HEAD`, the active systemd units, and *paths and sizes only* of the correction manifest and historical candle roots. Do not output credentials, .env files or customer/account identifiers.
2. Locate `outputs/freeze/tick_correction_manifest.csv` and verify its SHA-256 matches:
   `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc`.
   If missing or mismatched: STOP. Do not silently substitute a different manifest.
3. Inspect and document manifest column names and a redacted example row. Identify how CLEAN days and per-day timestamp transformations map to the actual historical M5 source. Check the source provenance (BID vs MID), numeric price units (IG index vs decimal), timeframe labelling (start vs end) and market-day boundary.
4. Materialise a **separate read-only research copy** of authorised CLEAN days, with timestamp corrections applied exactly once and a day-level transformation audit. Exclude the frozen exclusions, all `ohlc/`, the identified regime gap, and any unapproved dates. Never mix BID with MID observations.
5. Independently verify date coverage, duplicates, monotonic timestamps, 5-minute regularity, corrected day boundary and sampled tick-to-candle prices. STOP if any authority mismatch remains. A simple UTC-date allowlist in the current research script is only a *secondary gate*, not a replacement for this verification.
6. In a separate research worktree at branch `research/reversal-shadow-agent-20261022`, run:
   `python -m unittest discover -s tests/unit -p 'test_reversal_shadow_*.py' -v`.
   No service restart or trading dependencies are necessary.
7. After the data audit passes, export a newline-separated ISO-8601 UTC date allowlist into a local temporary file. Run:
   ```bash
   python -m scripts.research.reversal_shadow_study \\
     --archive-root /path/to/research/corrected/m5 \\
     --approved-clean-days /path/to/research/approved_utc_dates.txt \\
     --source-side BID \\
     --pip-size 1 \\
     --symbol GBPUSD \\
     --output-dir /path/to/research/reversal-shadow-results
   ```
   **BID and pip-size 1 above are examples only.** Substitute *measured* source-side and price unit. Stop instead of guessing. The script reads `<archive-root>/GBPUSD/*.csv`, with the canonical `timestamp,open,high,low,close` layout.
8. Report all candidate counts (including missing/censored), every horizon's observation denominator, hit rates for 20/30 pip excursions, MFE, MAE and end-of-window movement. Never call target-reaching events winning trades: intrabar ordering, bid/ask execution costs and realistic stops are **not modelled** yet.
9. Keep DEV, temporal validation and untouched OOS separated; do not tune the detection specification on OOS. Save manifests, dataset hashes, exact code commit and intermediate results for repeatability.
10. Return a concise evidence report: what ran; code SHA; input paths/hashes; manifest verdict; trading-date coverage; excluded counts; source/units; output locations; regression-test results; and any blockers. **Do not deploy a live agent or change production.**

## Release gate

If accurate, provenance-verified CLEAN historical data cannot be obtained, conclude **BLOCKED — NO RELIABLE HISTORICAL RESULTS** rather than improvising data or performance figures.
