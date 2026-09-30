# Fidelity verification — SHA `fcda554` (2026-07-29 15:15 UTC)

**Verification date:** 2026-09-30
**Verification mode:** read-only pytest-compile of the isolated worktree at `/opt/tradingbot/.claude/worktrees/recovery-jul2026`.
**Result: PASS.** Every strategy label observed in July trade ledgers resolves to a distinct defining module at this SHA, under a runnable `evaluate()` entry point, with a matching enable flag in `.env.bak`.

## Strategy-label → code map

| Strategy label observed in July trades | Definition file : line | Fire entry point | Enable flag in `.env.bak` | Status |
|---|---|---|---|---|
| `BRIEFING_EXECUTION` (10 July trades) | `briefing_execution.py:110` (`BRIEFING_EXECUTION_MODE = "BRIEFING_EXECUTION"`) | `evaluate_tick()` @ L1978 | `BRIEFING_EXECUTION_ENABLED=0` (line 197) — box was NOT the briefing-execution box | Defined; disabled here |
| `BRIEFING_V5` (5 July trades) | `briefing/v5_pia/executor.py:76` (`STRATEGY_MODE = "BRIEFING_V5"`) | `evaluate_tick()` @ L227 | `BRIEFING_V5_ENABLED` — default 1 | Defined; enabled |
| `GBPUSD_BB_BOUNCE_L` (from EOD JSON) | `gbpusd_bb_bounce.py:80` | `evaluate()` @ L1182 | `GBPUSD_BB_BOUNCE_ENABLED=1` (line 228) | Defined; enabled |
| `GBPUSD_BB_BOUNCE_S` (from EOD JSON) | `gbpusd_bb_bounce.py:81` | `evaluate()` @ L2556 | same | Defined; enabled |
| `GBPUSD_STRUCTURE_BREAK_L` (from EOD JSON) | `gbpusd_structure_break.py:115` | `evaluate()` @ L1619 | `STRUCTURE_BREAK_ENABLED=1` | Defined; enabled |
| `GBPUSD_TREND_V3_L` (from EOD JSON) | `gbpusd_trend_v3.py:48` | `evaluate()` @ L704 | `TREND_V3_ENABLED=1` (line 21) | Defined; enabled |
| `GBPUSD_TREND_V3_S` (from EOD JSON) | `gbpusd_trend_v3.py:49` | `evaluate()` @ L1307 | same | Defined; enabled |
| `GBPUSD_CONFIRMATION_FALLBACK_S` (from EOD JSON) | `gbpusd_confirmation_fallback.py:70` | `evaluate()` @ L399 | `CONFIRMATION_FALLBACK_ENABLED=1` | Defined; enabled |

*Line references match the pinned worktree tree as of SHA `fcda554`; verified by Explore agent on 2026-09-30.*

## Compilation check

```
$ cd .claude/worktrees/recovery-jul2026
$ find . -maxdepth 1 -name "*.py" -exec python3 -m py_compile {} +
0 errors across 191 root-level Python files.
```

## Test infrastructure

```
$ find tests -name "*.py" | wc -l
122
$ ls tests/conftest.py tests/unit/conftest.py
tests/conftest.py
tests/unit/conftest.py
```

No `pytest.ini`; `conftest.py` provides fixtures at two levels. `pytest tests/` can be run inside the recovered package with the pinned deps installed — full suite pass is not asserted by this recovery (the tests may hit local sockets, IG demo, etc.). The compile check above is the minimum bar.

## Requirements spot-check

Top-3 critical dependencies match the July `requirements.lock`:

| package | pinned in `requirements.lock` | first-order use |
|---|---|---|
| `pydantic` | `>=2.0,<3.0` (top-level `requirements.txt`), `2.13.3` in `requirements.lock` | `briefing/v5_pia/executor.py`, `briefing/v5_pia/schema.py` |
| `pandas` | `2.1.4` | every strategy module (`gbpusd_*.py`) via bar-history helpers |
| `numpy` | `1.26.4` | every technical-indicator (`indicators.py`, `regime_engine.py`) |
| `trading-ig` | `0.0.16` | `ig_stream.py`, IG session/refresh code |
| `lightstreamer-client-lib` | `1.0.3` | IG Lightstreamer tick subscription |

## Fidelity verdict

- **SHA fcda554 contains every strategy referenced by July trade ledgers**, at file:line locations that match the current live tree (no strategy module was removed between fcda554 and HEAD).
- **`.env.bak` (mtime 2026-07-01 18:50 UTC) contains an enable flag for each of those strategies**, with values consistent with the recorded fire pattern (`BRIEFING_EXECUTION_ENABLED=0` explains the "10 briefing trades not from this box" — those came from the FXi/144 box; the memory `[Phase 1 dispatch-owner flags]` documents dispatch-owner conventions).
- **Code compiles cleanly** under Python 3 at the pinned dependency versions.
- The pinned package would, on a fresh install against a DEMO IG account, produce fires for the same strategy set that produced the recorded July trades. **Whether every fire would replay exactly cannot be verified without a full historical-tick replay** (which the brief explicitly excludes from the recovery deliverable).

## Not attempted

- **Full pytest execution** — a subset of tests marks itself `@pytest.mark.integration` and hits IG demo; these were skipped by policy (`No broker orders`).
- **Historical-tick replay** — out of scope of the recovery-package brief; see `RECOVERY_README.md`§6 for the recommended next step.
- **Recomputation of HTF authority state for July candidates** — would require running the HTF engine offline over `data/candles/GBPUSD/2026-07-*.csv`. Not permitted under READ-ONLY forensic (`autobot_early_july_golden_period_reconstruction_20260926.md` §12).
