# Phase 1B rerun — independent-episode counter on authorised data

Generated: 2026-10-17T12:49:51.667503+00:00

## Coverage reconciliation

- Total candidates (frozen pool): 9349
- In Stage 0b manifest:           7499
- Excluded by manifest rules:     1850
- In-manifest DEV days:           5165
- In-manifest HOLDOUT days:       1771
- In-manifest OOS days:           563
- Unique dates with missing bars (post-filter): 0

## `attached_touches_today` AUC on authorised coverage

- n TRUE = 3077, n FALSE = 4422
- AUC = 0.686  CI95 = [0.663, 0.712]

Comparison: original Stage 0 report (full 9,349 pool, no manifest
filter) reported AUC = 0.696 CI95 [0.673, 0.718]. The in-manifest
subset uses only frozen features embedded on the candidate record,
so AUC is expected to track closely except for sample-composition
effects of removing the 1,850 unauthorised candidates.

## Independent-episode counter (gap sweep, no min-depart) on authorised
    coverage

Compared with the Phase 1 subsample result (2026-only, n_T=984, n_F=1516).

| gap_bars | n_T | n_F | median T | median F | mean T | mean F | AUC | CI95 |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 3077 | 4422 | 1.0 | 1.0 | 1.87 | 1.38 | 0.593 | [0.574, 0.612] |
| 2 | 3077 | 4422 | 1.0 | 1.0 | 1.57 | 1.16 | 0.594 | [0.576, 0.614] |
| 3 | 3077 | 4422 | 1.0 | 1.0 | 1.40 | 1.06 | 0.590 | [0.572, 0.609] |
| 6 | 3077 | 4422 | 1.0 | 1.0 | 1.17 | 0.90 | 0.589 | [0.572, 0.608] |
| 12 | 3077 | 4422 | 1.0 | 1.0 | 1.01 | 0.79 | 0.586 | [0.567, 0.603] |

## Verdict

The independent-episode counter AUC on authorised coverage is
the authoritative Phase 1B measurement. The earlier 2026-only
subsample result is preserved in `phase1_audit_report.md`
(commit 0857de2) for traceability but is NOT the finding.
