# central_execution_gate side-vocabulary normalisation — 2026-11-05 deployment

## Summary

**Defect fixed**: BB_PIERCE_RUN, EMA_PULLBACK and other dispatch-adapter
routed strategies emit `candidate.side` as `"LONG"` / `"SHORT"` (trader-
side vocabulary). `nms_directional_authority.enforce()` accepts only
`"BUY"` / `"SELL"` (directional vocabulary) and otherwise returns
`BLOCK_BAD_SIDE` — short-circuiting the entire authority before W&W,
exhaustion and trend-matrix conditions ever run.

**Live evidence** (2026-11-05 autobot journal):

```
Nov 05 14:40:11  dispatch_adapter LIVE gate rejected: strategy_family=BB_BOUNCE
                 reasons=[... "normal_routing:unified_authority_block:
                 BLOCK_BAD_SIDE:side='SHORT'" ...]
Nov 05 15:00:14  same block, same reason, side='SHORT'
Nov 05 15:35:12  same block, same reason, side='SHORT'
```

Same symptom Nov 4 10:50 (side='LONG'), confirming the defect dates
from the `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED` deployment, not
from the 2026-11-05 Bounce Family activation.

## Patch

- Worktree branch: `fix/central-gate-side-normalisation-20261105`
- Commit: `637d2d1 fix(nms-authority): normalise LONG/SHORT → BUY/SELL
  at the central-gate seam`
- Files changed: 3 (central_execution_gate.py, new test file, .gitignore allowlist)
- Diff: `+387 / −6`

Core change in `central_execution_gate.py`:

```python
# New module-level helper (near line 1502)
def _normalise_candidate_side(side: str) -> str:
    s = str(side or "").upper().strip()
    if s == "LONG":
        return "BUY"
    if s == "SHORT":
        return "SELL"
    return s
```

Applied at both `_nda.enforce()` call sites:
- `_apply_unified_directional_authority` (line ~1566) — the primary
  dispatch-adapter path covering BB_BOUNCE, TREND_V3, EMA_PULLBACK
  and every other dispatch-adapter-routed family.
- ONE_STRATEGY delegate's inner `enforce()` seam (line ~2017).

BUY/SELL inputs pass through unchanged. Malformed/empty values are
preserved so the enforcer's own `BLOCK_BAD_SIDE` guard still catches
genuinely broken candidates.

## Regression tests

New file: `tests/unit/test_central_gate_side_normalisation.py` —
**43 test cases**, all pass:

1. **Pure normaliser contract (21 cases)** — directional passthrough,
   trader-side translation, case-insensitive, whitespace trim, None
   handling, non-string handling, malformed preserved.
2. **Dispatch-adapter × every family × both vocabularies (8 cases)** —
   BB_BOUNCE / TREND_V3 / EMA_PULLBACK with LONG/SHORT must not
   surface `BLOCK_BAD_SIDE`.
3. **Malformed-side still blocks (7 cases)** — "", "UP", "DOWN",
   "FOO", "BUYER", "SHORTS", whitespace-only all still produce
   `BLOCK_BAD_SIDE` so the defensive guard is unweakened.
4. **Vocabulary equivalence (2 cases)** — LONG and BUY (and SHORT
   and SELL) produce bit-identical authority decisions.
5. **Live-evidence replay (2 cases)** — Nov 5 14:40 SELL candidate
   routes to the real matrix; `BLOCK_WATCH_AND_WAIT` still surfaces
   when W&W is active.
6. **ONE_STRATEGY seam (1 case)** — second call site uses the same
   normaliser contract.
7. **Flag-off byte-identical (6 cases)** — when
   `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=0` the function returns
   `None` for every side regardless of vocabulary.

Related suites unchanged (182 tests pass in the worktree):
- `tests/unit/test_nms_directional_authority.py`
- `tests/unit/test_central_gate_second_gate_takeover.py`
- `tests/unit/test_phase2b_enforce.py`
- `tests/unit/test_phase2b_ceg_integration.py`
- `tests/unit/test_nms_session_trend_direction_unified.py`

*(Those same suites show pre-existing drift failures when run directly
against `/opt/tradingbot` because the live tree has uncommitted
modifications to other files. The drift is unrelated to this patch —
verified by re-running against the backed-up unpatched file.)*

## Live replay — Nov 5 blocked candidates

Replay against `/opt/tradingbot` post-patch (deterministic authority
readers pinned to RANGE / NO_EXHAUSTION):

| Candidate | Side | Pre-patch reason | Post-patch reason |
|---|---|---|---|
| 14:40 BB_PIERCE_RUN | SHORT | `BLOCK_BAD_SIDE:side='SHORT'` | `None` (matrix admitted) |
| 15:00 BB_PIERCE_RUN | SHORT | `BLOCK_BAD_SIDE:side='SHORT'` | `None` (matrix admitted) |
| 15:35 BB_PIERCE_RUN | SHORT | `BLOCK_BAD_SIDE:side='SHORT'` | `None` (matrix admitted) |
| 11:20 BB_PIERCE_RUN | LONG  | `BLOCK_BAD_SIDE:side='LONG'`  | `None` (matrix admitted) |

In real runtime the authority may still return a legitimate `None`
(ALLOW) or a specific BLOCK reason (`BLOCK_WATCH_AND_WAIT`,
`BLOCK_TREND_WRONG_DIRECTION`, `BLOCK_BOUNCE_STRONG_TREND_NO_EXHAUSTION`,
etc.) based on the live NMS state at each fire. The point of the fix
is that those conditions are now *reachable* instead of being
short-circuited by vocabulary.

## Deployment to /opt/tradingbot

1. Backup: `/opt/tradingbot/_backups/pre-side-norm-20261105T161507Z/central_execution_gate.py`
   - pre-patch sha256: `e4dd1735da528dc7a196a791b55f28fd5815728f07c68728888a5aa0b15d533a`
2. Patch applied via Edit (3 hunks). Post-patch sha256:
   `30021ddfce8918c7d82e7253da8af73cf1982af0d78d23cce189407f91340264`
3. Test file copied: `/opt/tradingbot/tests/unit/test_central_gate_side_normalisation.py`
4. Verification against live tree: **43/43 tests PASS**, module imports
   cleanly, normaliser returns correct values on smoke test.

## Operator restart required

Autobot service is currently running on **PID 3955499** (started
2026-11-05 08:55:08 UTC, uptime ~7h). The patch is on disk but **will
not take effect until the service restarts** because the Python
process has `central_execution_gate` already imported in memory.

Standing rule forbids me from `systemctl restart`. Operator action
required:

```
sudo systemctl restart autobot.service
```

**Position safety**: autobot restart does not affect open broker
positions. On startup, `[restore] reconciliation complete` re-reads
positions from IG; stops and limits remain attached broker-side.
The 12:35 SELL (DIAAAAYSZ98ATAJ) and 15:21 BUY (DIAAAAYS2W9U3BQ) BB
Bounce trades opened via the standalone bb-bounce service — unaffected
by autobot restart.

## Rollback

Zero-downtime rollback:

```
cp /opt/tradingbot/_backups/pre-side-norm-20261105T161507Z/central_execution_gate.py \
   /opt/tradingbot/central_execution_gate.py
sudo systemctl restart autobot.service
```

## Expected post-restart behaviour

- BB_PIERCE_RUN fires that currently show `BLOCK_BAD_SIDE` in the
  dispatch_adapter reject log will now show the real downstream reason
  (ALLOW through to broker, or a specific NMS block).
- EMA_PULLBACK (autobot side — not the /opt/ema_pullback standalone)
  and TREND_V3 route through the same dispatch adapter; they benefit
  identically.
- The NMS WATCH_AND_WAIT, exhaustion, trend-matrix and news-window
  gates remain fully in force. No legitimate restriction is relaxed.
