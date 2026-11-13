# H1 trend compliance — pointer

The H1 trend compliance findings for Friday 2026-10-23 are the subject
of the companion audit at:

* Local path: `reports/h1_trend_compliance_20261025/`
* Published at: `https://github.com/JohnCarrington/autobot_reports/tree/research/h1-trend-compliance-20261025/h1_trend_compliance_audit_20261025`

That audit covers in detail:

* The H1 classifier's exact logic (strict EMA ordering + 1-step slope
  sign only; no magnitude, no separation, no persistence).
* Per-hour H1 state for the trading day and the whole week preceding it.
* 23 setups × H1 state × visual class × outcome.
* Timestamp authority (no lookahead, no stale state).
* 6-fill H1-lens review.
* Root cause summary.
* Annotated chart pack (5 PNGs).

The present audit (`h1_intrabar_compliance_20261025`) extends that
work by:

* Tracing the H1 data-source chain end to end
  (`H1_DATA_SOURCE_AUDIT.md`).
* Auditing M5 intrabar execution — the second half of the brief's
  two-defect hypothesis (`M5_INTRABAR_EXECUTION_AUDIT.md`).
* Cataloguing available tick/sub-M5 data (`TICK_DATA_AVAILABILITY.md`).
* Reconstructing the 23 setups through the intrabar lens
  (`FRIDAY_SETUP_RECONSTRUCTION.csv`, `SIX_FILL_INTRABAR_FORENSIC.csv`,
  `SIX_TRADE_FORENSIC_REVIEW.md`).
* Answering brief §FINAL (A/B/C/D) with evidence
  (`EXECUTIVE_FINDINGS.md`, `ROOT_CAUSE_AND_RECOMMENDATIONS.md`).

A copy of the authoritative H1 timeline for Fri 2026-10-23
(`H1_TREND_TIMELINE.csv`) is included in this directory for
convenience; it is byte-identical to the version in the companion
audit.
