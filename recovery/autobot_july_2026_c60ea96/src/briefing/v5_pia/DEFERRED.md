# Deferred work — briefing.v5_pia

Items raised during Phase 1 / Phase 2 development that are out-of-scope
for the current phase but must not be lost. Each entry: who raised it,
when, why deferred, and what triggers picking it up.

## Open

### requirements.lock drift audit (non-Pydantic)

**Raised:** Phase 2, 2026-05-05 (post-build review)
**Status:** open, not blocking Phase 3

**Context.** Phase 2 added `pydantic`, `pydantic-core`, `annotated-types`,
and `typing-inspection` to `requirements.lock`. While doing the
clean-venv install verification (`/tmp/v5pia_check_venv`) I observed
several other packages resolving to versions that don't match what's
in `requirements.lock`:

| package | lockfile | clean-install resolves | installed in prod venv |
|---|---|---|---|
| attrs | 25.4.0 | 26.1.0 | 25.4.0 (matches lock) |
| click | 8.3.1 | 8.3.3 | 8.3.1 |
| pytest | 9.0.2 | 9.0.3 | 9.0.2 |
| werkzeug | 3.1.5 | 3.1.8 | 3.1.5 |
| torch | 2.10.0+cpu | 2.11.0 (+ cuda-* family) | 2.10.0+cpu |

The existing prod venv installs match the lockfile (so prod is fine
right now), but a clean-rebuild from `requirements.txt` would produce a
different environment because:

1. `requirements.txt` doesn't pin most transitive deps.
2. `requirements.lock` is partial (it tracks selected packages, not
   every transitive — note no nvidia-* family, no scipy, no joblib, etc.).
3. Several pinned packages in `requirements.txt` don't constrain their
   transitives (torch unpinned, pytest unpinned).

**Why deferred.** Reconciling this during the Phase 2 Pydantic add would
have been exactly the kind of scope creep that causes outages — silently
rolling other versions while the change ostensibly was "add pydantic."

**What needs deciding.** Two reconciliation paths:

- **(A) Tighten `requirements.txt`.** Pin everything currently floating
  (torch, pytest, scikit-learn). Regenerate `requirements.lock` from a
  fresh install. Existing prod venv stays at its current versions, but
  any rebuild now produces the same environment.
- **(B) Treat `requirements.lock` as the source of truth.** Add the
  missing transitives (nvidia-*, scipy, joblib, threadpoolctl, etc.) to
  the lockfile so it actually reflects what's installed. `pip install
  -r requirements.lock` becomes the deterministic install command,
  `requirements.txt` stays human-readable.

**Trigger to pick up.** Either when prod needs a rebuild (e.g. host
migration, Python version bump) or when a clean-venv test reveals a
behavioural difference that bites a feature.

---

### Pair-list source-of-truth consolidation

**Raised:** 2026-05-06 (during EURUSD/USDJPY/USDCAD re-enable diagnosis)
**Status:** open, not blocking Phase 3

**Context.** On 2026-05-06 the 05:30 UTC London v4 fire failed for 3/4
pairs with `insufficient 5M data (0 bars)`. Root cause: the May-2 reduction
to GBPUSD-only (`2919f9a deploy(env): GBPUSD-only 3-strats activation`)
edited only the live-data env vars; the briefing scheduler and several
other modules continued iterating a different pair list. Briefer schedules
briefings for pairs the streamer never subscribed to → silent half-state.

The system has at least three independent pair-list sources of truth:

1. **Live-data layer** — env-driven, currently 1 pair:
   - `EPICS_JSON` parsed at `autobot.py:359` → consumed by
     `native_5m_source.subscribe_native_5m`
   - `CFD_EPICS_JSON` parsed at `autobot.py:377` + `build_deep_cache.py:49`
     → consumed by REST preload + deep-cache builder

2. **Briefing/audit/health layer** — `pair_config.PAIRS` hardcoded tuple
   of 4 pairs (`pair_config.py:14`). Consumed by morning_briefing.

3. **Per-strategy gating** — individual `*_PAIRS` env vars per strategy
   module. Examples: `BB_REVERSAL_PAIRS`, `EXHAUSTION_REVERSAL_PAIRS`,
   `CONTINUATION_SWEEP_PAIRS`, `REVERSAL_SWEEP_PAIRS`.

Plus several modules with their own hardcoded `SYMBOLS = [...]` /
`PAIRS = [...]` lists not reading from any of the above:
`premarket_health.py:46`, `data_feed_audit.py:47`, `sweep_replay.py:42`,
`test_full_system.py:31`, plus the bug below.

**Why deferred.** Non-trivial: requires deciding (a) which layer is
canonical, (b) whether per-strategy `ALLOWED_PAIRS` overrides global
`PAIRS` or intersects it, (c) whether `pair_config.PAIRS` should be
derived from `EPICS_JSON.keys()` or vice-versa, (d) audit pass over the
hardcoded `SYMBOLS` lists. Each consumer needs review individually.

**Trigger to pick up.** Next time we change the active-pair set.
Specifically, before the next env-driven pair reduction or expansion,
pick a canonical source and refactor the briefing scheduler /
premarket_health / data_feed_audit / read_briefing / sentinel_features
to read from it.

---

### Hardcoded SYMBOLS lists missing USDCAD

**Raised:** 2026-05-06 (alongside source-of-truth ticket)
**Status:** open, latent until USDCAD is re-enabled

**Context.** Two modules have hardcoded SYMBOLS lists that omit USDCAD:

- `read_briefing.py:25  SYMBOLS = ["GBPUSD", "EURUSD", "USDJPY"]`
- `sentinel_features.py:43  SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]`

When USDCAD is re-enabled at the env layer, these two modules will
silently exclude it. Effect on each module needs review — sentinel_features
in particular feeds downstream logic and silent exclusion may not be
visible until something else breaks.

**Why deferred.** Latent — only bites when USDCAD comes back online.
Should be fixed before that re-enable, or as part of the source-of-truth
consolidation above.

**Trigger to pick up.** Before the next env edit that re-adds USDCAD to
`EPICS_JSON`. Either fix these two files in the same commit, or replace
the hardcoded lists with a read from the canonical source.

---

## Resolved

(none yet)
