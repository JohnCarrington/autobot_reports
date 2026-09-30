# Step 2 Commit B — multi-slot executor design (read-only, 2026-05-12)

Design map for Commit 2B. Builds on Step 2A (`f4d3284`), which landed
plan_id plumbing without behavioural change. This commit introduces the
multi-slot `_plans[sym]` and the per-plan trigger evaluation that makes
plan_id load-bearing. No code changes in this document — design only.

---

## 1. The 5 plan-scoped state dicts

Current shapes (all `Dict[str, X]` keyed by symbol):

| Dict | Current shape | Lifecycle |
|---|---|---|
| `_plans` | `Dict[str, Dict[str, Any]]` — one active plan per pair | reset on `on_briefing`; assigned by arming; popped by `_drop_active_plan` |
| `_sweep_seen` | `Dict[str, bool]` — Phase 1 latch | reset on arming; flipped True when price tags sweep level |
| `_armed_at` | `Dict[str, float]` — epoch seconds since arm | set on arming; read by TREND_ENTRY 30-min gate |
| `_trend_closes` | `Dict[str, int]` — consecutive through-zone close counter | reset on arming; incremented per qualifying 5M close |
| `_entered` | `Dict[str, bool]` — fire-once latch | reset on arming; set True on `on_broker_confirmed` |

**Two viable multi-slot shapes:**

- **Shape A — dict-of-dicts**: `Dict[str, Dict[str, X]]` keyed by `[sym][plan_id]`. Access pattern: `self._sweep_seen.setdefault(sym, {})[plan_id] = True`.
- **Shape B — embedded on plan dict**: `_plans: Dict[str, List[Dict[str, Any]]]` and each plan carries its own latches: `plan["_sweep_seen"] = True`, `plan["_armed_at"] = …`, `plan["_trend_closes"] = …`. The four sibling dicts disappear.

**Recommendation: Shape B for all five.** Justification:

1. **Atomicity**: state-and-plan travel together. Today's reset pattern
   (`on_briefing` resets all four latches in one block at lines 1325-1329)
   becomes a single per-plan dict initialisation — no four-line block to
   keep synchronised. Adding a new latch later is one field on the plan
   dict, not a new instance attribute + reset block.
2. **Disk persistence comes for free**: `_save_plans_state` already
   serialises `self._plans[sym]` via `default=str` to JSON. Per-plan
   latches living on the plan dict are saved automatically. Today the
   five dicts are NOT all persisted (only `_plans` is in
   `_save_plans_state`); Shape A would need to add four extra
   serialisation lines.
3. **Iteration is the natural pattern**: `for plan in self._plans[sym]:`
   reads each plan's state directly. Shape A needs `self._sweep_seen.get(sym, {}).get(plan_id, False)` for every read — verbose and easy to misspell.
4. **`_entered` is the only dict that needs distinct handling** (see §5).
   It can stay per-`(sym, session)` (NOT per-plan) because it's the
   session-lockout latch, not a plan-eval latch. Keeping it separate
   from the plan dict matches its different lifecycle (session-scoped,
   not plan-scoped).

Single carve-out: `_entered` stays as a separate dict (per-session
shape detailed in §5). The other four (`_sweep_seen`, `_armed_at`,
`_trend_closes`, plus a new `_dormant` flag for "plan ineligible until
something changes") become per-plan fields on the plan dict.

After 2B, the `__init__` block (`briefing_execution.py:1272-1289`)
goes from 5 plan-scoped dicts to 1 (`_plans`) + 1 session-lockout
(`_entered`):

```python
self._plans: Dict[str, List[Dict[str, Any]]] = {}      # was Dict[str, Dict[str, Any]]
self._entered: Dict[str, Dict[str, bool]] = {}         # was Dict[str, bool] — see §5
# _sweep_seen, _armed_at, _trend_closes removed — fields on plan dict now
self._briefing_id: Dict[str, str] = {}                 # pair-scoped, unchanged
# … all 7 pair-scoped dicts (_london_plans, _ny_pending, _ny_armed,
# _ny_discarded, _ny_eval_date, _invalidated_plans) unchanged
```

---

## 2. `evaluate_tick` line-by-line walkthrough

`briefing_execution.py:1823-2400`. Today's flow, with single-plan
assumption points called out:

| Line(s) | Purpose | Single-plan assumption? |
|---|---|---|
| 1845-1849 | `sym = symbol.upper()`; ingest briefing if supplied | No — symbol-level work |
| 1853 | `check_expires_at(sym)` | **Yes** — drops THE active plan (line 1738 `self._plans.pop`). Needs to drop ANY expired plan in multi-slot. |
| 1855-1857 | `plan = self._plans.get(sym); if not plan: return None` | **Yes** — singular `plan`. **Natural per-plan loop wraps from line 1856 to the return statements.** |
| 1858-1859 | `if self._entered.get(sym): return None` | **Yes** — pair-scoped lockout. Becomes per-session check (§5). |
| 1861-1863 | `zone_lo, zone_hi, direction = plan[…]` | Per-plan-bound. |
| 1867-1889 | 6-bar HH/HL trend override | Per-plan-bound (`direction` is plan's). |
| 1895-1932 | Phase 1 sweep detection — sets `_sweep_seen[sym]` | **Yes** — `_sweep_seen[sym]` is the pair latch. Becomes `plan["_sweep_seen"]` in Shape B. |
| 1937-2200 | TREND_ENTRY fallback — `_trend_closes[sym]`, `_armed_at[sym]` | **Yes** — both pair-scoped today; per-plan fields in Shape B. The whole fire block (~260 lines) wraps inside the per-plan loop. |
| 2210-2400 | Phase 2 confirmation + D1 veto + levels advisory + TP select + v2 gate + guards + forensic + emit | **Yes** — single `plan` throughout. |

**Single natural insertion point for the loop:**

```python
# (after the briefing ingest + check_expires_at)
plans = self._plans.get(sym) or []
if not plans:
    return None

# Sort by rank ascending so rank-1 gets first crack at firing on a tick
plans = sorted(plans, key=lambda p: int(p.get("rank") or 999))

for plan in plans:
    if self._entered.get(sym, {}).get(plan["session"], False):
        continue                               # session locked → skip
    if plan.get("_dormant"):                   # explicit per-plan dormancy
        continue
    # ... existing single-plan body (lines 1861-2400), with:
    #   self._sweep_seen[sym]    → plan["_sweep_seen"]
    #   self._armed_at[sym]      → plan["_armed_at"]
    #   self._trend_closes[sym]  → plan["_trend_closes"]
    # On fire (TREND_ENTRY or Phase 2):
    #   stamp decision.debug["plan_id"] (already done in 2A)
    #   return StrategyDecision(...)           # FIRST plan to satisfy wins

return None
```

The contract — `evaluate_tick` returns `Optional[StrategyDecision]` — is
preserved. Only one decision per tick. Multiple plans evaluated; first
to satisfy fires; rest queried again next tick.

---

## 3. `on_bar_close` + invalidation — already plan-scoped

Confirmed: `_plan_expired(plan, now_utc)` (`briefing_execution.py:1043`)
and `_bar_invalidates_plan(plan, bar_close, ...)`
(`briefing_execution.py:1087`) BOTH take `plan` as their first argument
and access only that plan's fields. Neither touches instance state.

Today's `on_bar_close` (`briefing_execution.py:1761-1817`) has one
single-plan call site: `plan = self._plans.get(sym)` (line 1779), then
two helper calls. The multi-slot version wraps in a `for plan in
plans:` loop — the helpers themselves need no change:

```python
def on_bar_close(self, symbol, bar_close, timeframe="5m", now_utc=None, pip_size=1.0):
    sym = symbol.upper()
    plans = list(self._plans.get(sym) or [])   # copy: _drop_active_plan mutates
    if not plans:
        return
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    for plan in plans:
        # Per-plan _entered check (session locked → still let the bar
        # close run; an entered plan is the broker's problem, not the
        # strategy's)
        if self._entered.get(sym, {}).get(plan["session"], False):
            continue
        if timeframe == "5m" and _plan_expired(plan, now_utc):
            self._drop_plan(sym, plan, f"expired:{plan.get('expires_at')}")
            continue
        if _bar_invalidates_plan(plan, bar_close, timeframe=timeframe, pip_size=pip_size):
            self._drop_plan(sym, plan, f"invalidated@{bar_close:g}")
            continue
```

The only API change here is `_drop_active_plan(sym, reason)` →
`_drop_plan(sym, plan, reason)` (or similar) so we can remove a
specific plan from the list rather than `self._plans.pop(sym)`.

---

## 4. `_resolve_active_plan` return shape

Current: returns `Optional[Dict[str, Any]]` — one plan, top-scored by
`(confidence_rank, probability)` (lines 1160-1202).

**Recommendation: Option X — change return to `List[Dict[str, Any]]`.**

Caller at `on_briefing:1415-1429` becomes:

```python
resolved_plans = _resolve_active_plans(briefing)   # renamed
if resolved_plans:
    plans = resolved_plans
    # log: "ARMED N plans via best_trade.<mode>: ..."
else:
    # Fallback: arm all London plans, ranked
    plans = london_plans                            # all of them, not just [0]
    # log: "ARMED N plans via fallback ..."
```

Resolution rules per `best_trade.mode`:

- **UNCONDITIONAL**: still returns one plan (the named `(plan_session, plan_rank)`), wrapped in a list. Backwards-compatible — UNCONDITIONAL briefings behave identically to today.
- **CONDITIONAL**: returns ALL branch-referenced plans (today returns only the top-scored). Each plan is independently armed. This is the actual unlock.
- **null / unresolvable**: caller falls back to "all London plans" instead of "rank-1 of London."

Justification for Option X over Option Y (executor keeps its own list):

- Single source of truth — the resolver knows the best_trade semantics; the executor shouldn't re-derive it.
- The plan-arming code in `on_briefing` becomes a single `for plan in plans:` loop that builds active dicts and appends — no branching between "best_trade picked X" and "we tracked some siblings ourselves."
- `_resolve_active_plan` already enumerates branches; returning the list is one-line change to the function body.

---

## 5. Per-session `_entered` lockout (Commit 2C territory, design-relevant now)

**Call-site inventory** (`grep self._entered briefing_execution.py`):

| Line | Op | Function | What it does |
|---|---|---|---|
| 1275 | declaration | `__init__` | `_entered: Dict[str, bool] = {}` |
| 1325 | write `False` | `on_briefing` | Reset on new briefing |
| 1338 | write `True` | `on_briefing` | Cross-restart hydration when prior process fired |
| 1748 | read | `check_expires_at` | Skip drop if entered |
| 1782 | read | `on_bar_close` | Skip drop if entered |
| 1858 | read | `evaluate_tick` | Short-circuit: no fire if entered |
| 2411 | read | `has_entered(sym)` (public) | Used by `autobot.py:2670, 2691` for post-entry monitoring |
| 2490 | read | `on_broker_confirmed` | Idempotent no-op check |
| 2497 | write `True` | `on_broker_confirmed` | The pessimistic commit |

**Proposed new shape**: `_entered: Dict[str, Dict[str, bool]]` keyed by
`[sym][session]` where `session in {"London", "NY"}`. The composite
key tracks "has any plan in this session fired for this pair under
this briefing arm."

**Why session-scoped, not per-plan?**

Per-plan (`_entered[sym][plan_id]`) would let two London plans both
fire on the same day — e.g. SHORT-fade-at-13630 fires at 09:00, then
LONG-bounce-at-13580 fires at 11:00. Operationally this is two
simultaneous trades on the same pair in opposite directions inside
the same session. Not a behaviour we want as the default for 2B —
and the existing `_PAIR_CONCURRENCY_BYPASS_MODES` plumbing in
`trade_executor.py` doesn't include BRIEFING_EXECUTION, so the
pair-concurrency cap would block the second fire anyway. Per-plan
lockout would lie about what's achievable.

Per-session lockout matches operational intuition: "we already have
a London trade open; don't open another." NY plans remain firable
because the London position should be closed by 12:00 UTC under the
existing `news_context.avoid_before` plumbing.

**Cleanest migration without breaking call sites:**

1. Replace declaration: `self._entered: Dict[str, Dict[str, bool]] = {}`.
2. Add internal helper `def _is_entered(self, sym, session) -> bool: return self._entered.get(sym, {}).get(session, False)`.
3. Add `def _mark_entered(self, sym, session) -> None: self._entered.setdefault(sym, {})[session] = True`.
4. Read sites (1748, 1782, 1858) need a session value. The simplest pattern: each call is already inside a per-plan loop in 2B, so the loop variable `plan` provides `plan["session"]`. Update each read to `self._is_entered(sym, plan["session"])`.
5. Write sites:
   - Line 1325 (`on_briefing` reset): clear `self._entered[sym] = {}` — empty dict instead of False.
   - Line 1338 (hydration): set `self._entered[sym] = dict(rec.get("entered_by_session") or {})` — reads the new disk format.
   - Line 2497 (`on_broker_confirmed`): needs to know which session fired. plan_id from 2A is `"<session>_<rank>"` — split on `_` to recover session.
6. `has_entered(sym)` (public, `autobot.py:2670, 2691`): becomes `return any(self._entered.get(sym, {}).values())` — "is any session locked?" That preserves the pair-level question the autobot is asking.

The migration is 6 small edits; no call site is left guessing about
session because either (a) it's inside a per-plan loop with `plan["session"]` in scope or (b) it's pair-level aggregation.

**Disk schema** for the dedup cache (`briefing_execution_entered.json`):

```json
{
  "GBPUSD": {
    "briefing_time": "2026-05-12T05:30:23Z",
    "fired_at": 1778573412.55,
    "entered_by_plan": {"London_1": true, "NY_2": true},
    "entered_by_session": {"London": true, "NY": true}
  }
}
```

`entered_by_plan` (from 2A) stays for forensic visibility. New field
`entered_by_session` is what 2C reads back for hydration. 2A's
additive contract holds — old caches missing both fields are treated
as "no sessions entered" and the next fire populates them.

---

## 6. `evaluate_ny_plans` multi-slot semantics

Today (`briefing_execution.py:1538-1634`): at 12:30 UTC, evaluates
each queued NY plan's `london_condition` against `LondonSummary`;
top-ranked survivor is promoted to the single active plan slot via
`_promote_to_active`; rest are stored in `_ny_armed` / `_ny_discarded`
for audit but inert.

**Proposed multi-slot behaviour:**

1. The condition loop (lines 1583-1607) stays as-is — it's already a
   per-plan iteration that just builds `armed` and `discarded` lists.
2. The promotion step (lines 1617-1620) changes from "promote top of
   `armed`" to "promote ALL of `armed`":
   ```python
   if armed:
       armed.sort(key=lambda p: int(p.get("rank") or 999))
       for ny_plan in armed:
           self._promote_to_active(sym, ny_plan)   # appends, doesn't replace
   ```
3. `_promote_to_active` becomes an **append** operation, not a replace.
   Current line 1704 `self._plans[sym] = active` becomes
   `self._plans.setdefault(sym, []).append(active)`. The arming-state
   reset (lines 1705-1707, sweep/trend_closes/armed_at) is now part of
   the per-plan dict init.
4. **Lock London at 12:30?** No — DECISION REVISED 2026-05-12 (user
   signoff). `_entered[sym][session]` tracks **actual fired trades**,
   not clock boundaries. Do NOT auto-set `_entered[sym]["London"] = True`
   inside `evaluate_ny_plans`. A London plan that is still
   waiting on Phase 2 confirmation at 12:30 can in principle fire
   after the NY swap, provided its `expires_at` has not passed AND its
   conditions trigger AND `_entered[sym]["London"]` is still False
   (i.e. no other London plan has fired). In practice rare — most
   London plans set `expires_at = '12:00Z'` and are dropped by
   `check_expires_at` well before 12:30. Plans with
   `expires_at = 'end_of_day'` retain firing potential post-12:30 as
   long as the London session has not already burned its lockout.
   This is semantically cleaner: the session lockout reflects what
   the bot actually did, not what time it is.
5. **`london_condition`-failed plans**: today they go into
   `_ny_discarded[sym]` and never fire. Keep that — drop them from
   `_plans[sym]` (never appended in the first place). They stay in
   the audit record. Reverse decision noted: keeping them dormant
   instead of dropping introduces a re-arm path with no clear
   business semantics. The condition already failed — re-firing is
   wishful thinking.

---

## 7. Trigger ordering — deterministic rule

The race: two plans both have their per-plan latches in the right
state (e.g. `_sweep_seen=True`), and on a single 5M close, BOTH
their Phase 2 confirmation conditions evaluate True.

**Can this actually happen?** Yes — concrete example:

- Plan A (SELL, zone [13625, 13632]): Phase 1 sweep_seen set when
  mid >= 13632 earlier in the day. Phase 2 confirms when 5M close
  < 13625.
- Plan B (BUY, zone [13580, 13585]): Phase 1 sweep_seen set when
  mid <= 13580 earlier. Phase 2 confirms when 5M close > 13585.
- A single 5M close at, say, 13600 satisfies BOTH (< 13625 AND >
  13585). Both want to fire on the same tick.

**Recommendation: rank-ascending iteration order.**

```python
plans = sorted(plans, key=lambda p: int(p.get("rank") or 999))
for plan in plans:
    # ... evaluate plan ...
    if (fires):
        return StrategyDecision(...)   # rank-1 wins
```

- Deterministic — same inputs always produce same fire.
- Audit-friendly — the LLM's own ranking is the priority.
- Symmetric with today's UNCONDITIONAL behaviour (rank-1 is the
  selected plan).
- Easy to test (synthetic two-plan-both-trigger scenario).

Tie-break beyond rank (e.g. two plans both rank 1 — happens because
rank is unique only within session, so London-1 and NY-1 can coexist
in the active list when both arrive via `_resolve_active_plan` with
CONDITIONAL): order by `(rank, session_priority, plan_id)`. Session
priority: London=0, NY=1 (London earlier in the day). Plan_id is the
final lexicographic tie-break — deterministic even on unexpected
duplicates.

Alternatives rejected:
- **Highest probability**: deterministic but doesn't match how the
  LLM thinks about plans. The LLM explicitly authored rank for
  priority.
- **First-by-timestamp** (timestamp of when the plan was last
  updated): non-deterministic across restarts when hydration
  re-stamps `_armed_at`.
- **Random**: rejected for obvious reasons.

**Same-tick collision**: the function returns ONE
`StrategyDecision` per call. After rank-1 fires and the per-session
lock is set, rank-2 is skipped on the same tick (loop continues but
the `_entered` check at the top of each iteration short-circuits).
Rank-2 has no chance to fire under the chosen session-lockout
semantics. This is correct: the operator's intent is "one trade per
session per pair."

---

## 8. State persistence — `cache/briefing_plans_<SYM>.json`

Current schema (`_save_plans_state` at `briefing_execution.py:2546`):

```json
{
  "symbol": "GBPUSD",
  "briefing_time": "2026-05-12T05:30:23Z",
  "saved_at": "2026-05-12T05:32:06.262+00:00",
  "active_plan": {"label": "Sweep Asian low ...", "direction": "BUY", ...},
  "london_plans": [{...}, {...}, {...}],
  "ny_pending": [...],
  "ny_armed": [...],
  "ny_discarded": [...],
  "ny_eval_date": "",
  "invalidated_plans": []
}
```

`active_plan` is a single dict.

**Proposed multi-slot schema (additive):**

```json
{
  "symbol": "GBPUSD",
  "briefing_time": "...",
  "saved_at": "...",
  "active_plans": [{plan_dict_with_per_plan_latches}, {...}, {...}],
  "london_plans": [...],
  "ny_pending": [...],
  "ny_armed": [...],
  "ny_discarded": [...],
  "ny_eval_date": "",
  "invalidated_plans": []
}
```

The new field is `active_plans` (plural) — a list. The old
`active_plan` (singular) field is dropped from new writes.

**Hydration migration** (`_hydrate_plans_state_from_disk` at
`briefing_execution.py:2638`):

```python
ap_list = payload.get("active_plans")
if isinstance(ap_list, list):
    # New format
    self._plans[sym] = ap_list
elif isinstance(payload.get("active_plan"), dict):
    # Old format — wrap singleton into list
    self._plans[sym] = [payload["active_plan"]]
else:
    self._plans[sym] = []
```

Old files on disk during the deploy window (mid-session restart with
2B code on a 2A-written cache) load cleanly as singleton lists. Once
all caches are written by 2B code, the old field stops appearing.

Per-plan latches (`_sweep_seen`, `_armed_at`, `_trend_closes`) being
fields on the plan dict means they're automatically serialised —
zero extra work in `_save_plans_state`. Hydration restores them
without explicit handling.

**Backfill concern**: pre-2A plans persisted without `plan_id` (an
inherent feature only since 2A's `_plan_id_for` stamp). On hydration,
if a plan dict lacks `plan_id`, call `_plan_id_for(plan)` to derive
it on the fly — same deterministic scheme. No cache invalidation
needed.

---

## 9. Honest scope estimate for Commit 2B

**LOC range**: 250-350 lines net in `briefing_execution.py`, plus
~150-250 LOC of tests. Roughly:

- `__init__` shape change + helpers (`_drop_plan`, `_is_entered`,
  `_mark_entered`, `_per_plan_latch_init`): ~30 LOC
- `on_briefing` arming loop (was singular, becomes per-plan):
  ~40 LOC of restructure
- `_resolve_active_plan` return-list rewrite: ~15 LOC
- `evaluate_tick` per-plan loop wrap + latch references change
  (`self._sweep_seen[sym]` → `plan["_sweep_seen"]` etc.): ~30 LOC
  net (mostly substitutions; the loop wrapper itself is ~10 LOC)
- `on_bar_close` per-plan loop wrap: ~15 LOC
- `_promote_to_active` append instead of replace: ~5 LOC
- `evaluate_ny_plans` "promote all, lock London": ~15 LOC
- `has_entered` / `should_invalidation_close` / `should_time_exit`
  internal iteration: ~25 LOC
- Disk schema migration in `_save_plans_state` +
  `_hydrate_plans_state_from_disk`: ~25 LOC (additive — keeps old
  field reader for one-restart compat)
- `on_broker_confirmed` per-session `_entered` write: ~10 LOC
- Misc — `_drop_active_plan` rename, log line updates, comments: ~30
  LOC

Total: ~240 source LOC. Plus tests:

**Test cases needed** (target 15-25 new):

1. `_plans[sym]` accepts multiple plans on UNCONDITIONAL (singleton list).
2. `_plans[sym]` accepts multiple plans on CONDITIONAL with 2 branches → 2-item list.
3. Per-plan `_sweep_seen` independent — plan A's latch flipping does not affect plan B.
4. Per-plan `_armed_at` independent.
5. Per-plan `_trend_closes` independent.
6. `evaluate_tick` rank-ascending iteration — rank-1 fires when both rank-1 and rank-2 satisfy on the same tick.
7. `evaluate_tick` skips plan whose session is `_entered`.
8. `evaluate_tick` skips plan that is dormant.
9. `on_bar_close` invalidates one plan; other plans on same pair survive.
10. `on_bar_close` expires one plan; other plans on same pair survive.
11. `evaluate_ny_plans` promotes all `armed` plans, not just top.
12. `evaluate_ny_plans` locks London session after promotion.
13. `evaluate_ny_plans` plans with failed `london_condition` are not promoted.
14. `_resolve_active_plan` UNCONDITIONAL → singleton list.
15. `_resolve_active_plan` CONDITIONAL with 3 branches → 3-item list.
16. `_resolve_active_plan` unresolvable → None → caller falls back to all London plans.
17. `_save_plans_state` round-trip with multiple plans (write + hydrate).
18. `_hydrate_plans_state_from_disk` old format (singleton `active_plan`) → list of one.
19. `_hydrate_plans_state_from_disk` new format (list `active_plans`) → list preserved.
20. `on_broker_confirmed` with plan_id sets `_entered[sym][session]`.
21. `has_entered(sym)` returns True when any session is entered.
22. `has_entered(sym)` returns False when no session has fired.
23. Trigger-ordering tie-break: same-rank cross-session → London before NY.
24. Trigger-ordering tie-break: same-rank same-session edge case → plan_id lexicographic.
25. Multi-plan dispatch end-to-end (mock evaluate_tick → mock on_broker_confirmed → confirm right session locked).
26. Late-London survives NY swap: London plan with `expires_at='end_of_day'` stays in `_plans[sym]` after `evaluate_ny_plans` runs. `_entered[sym]['London']` is still False post-swap (no auto-lock by clock).
27. CONDITIONAL branch with expired plan: resolver skips the expired branch with DEBUG log; remaining branches arm normally.

**Highest-risk areas:**

1. **The `evaluate_tick` per-plan loop wrap** — this is ~260 lines of
   single-plan body that needs to wrap correctly while keeping
   ordering (Phase 1 detection happens on every tick; Phase 2 /
   TREND_ENTRY happen only on `is_new_5m`). Risk: an early `return`
   inside the loop (e.g. trend override veto) silently skips later
   plans that should still get a fair tick. **Mitigation**: every
   "return None" inside the loop becomes "continue"; only the fire
   path returns. Audit every existing `return None` site.

2. **Session-lockout semantics around 12:30 UTC**. Per the modified
   decision 4: `_entered[sym][session]` is fire-triggered, not
   clock-triggered. So a London plan with `expires_at='end_of_day'`
   that has not fired by 12:30 stays armed and continues to be
   watched alongside the promoted NY plans. The risk is NOT
   "London-plan-fires-while-NY-swap-runs" (the swap doesn't lock
   anything) but rather "an unfired London plan that survived
   12:30 might later fire on the same pair as a fired NY plan,
   producing cross-session double-fire on a pair." Today this is
   rare — `expires_at='12:00Z'` is the convention for London plans
   per the prompt at `morning_briefing.py:1731-1735`. The
   `check_expires_at` running at the top of every `evaluate_tick`
   handles cleanup for properly-set expires_at. **Mitigation**: no
   special clock-based lock; rely on `check_expires_at` + the
   producer's expires_at convention. Add a test that a London plan
   with `expires_at='end_of_day'` survives the NY swap and the
   session lockout for London engages only on actual London fire.

3. **Disk-schema migration during mid-session restart**. If the
   live process restarts between 2A and 2B, the cache file has
   `active_plan` (singular) but `entered_by_plan` (from 2A).
   `_hydrate_plans_state_from_disk` must wrap-the-singleton AND
   preserve the dedup record's plan-aware fields. **Mitigation**:
   covered by the dual-read path in §8. Need a test for "2A cache
   loaded by 2B code."

4. **`autobot.py` post-entry monitor**. `has_entered(sym)` is called
   from `autobot.py:2670, 2691` to decide whether to monitor for
   force-close. In multi-slot, "the open plan" is unique once
   per-session lockout fires, but the autobot helpers
   (`should_invalidation_close`, `should_time_exit`) need to find
   that specific plan. Today they read `_plans[sym]` (singular). The
   strategy needs an internal "which plan is the one that fired"
   marker so these helpers consult the right plan. Plan dict can
   carry an `_entered=True` field alongside the latches; the helpers
   iterate and find it.

5. **`_PAIR_CONCURRENCY_BYPASS_MODES` interaction — decision 4
   modified is partially gated on a separate decision.**
   Today this set (`trade_executor.py:764-769`) does NOT include
   BRIEFING_EXECUTION. Post-2B, the cross-session second fire
   (London fires AM, NY fires PM on the same pair) is
   **structurally permitted** by the fire-triggered session lockout
   semantics but **operationally blocked** at
   `trade_executor.py:773` because the pair-concurrency cap rejects
   the NY dispatch while a London position is still open.

   What actually happens in live trading under 2B alone:
   - London + NY plans both arm and are watched concurrently. ✓ (new behaviour)
   - First London plan to trigger fires, locks `_entered[sym]["London"]`. ✓ (new behaviour)
   - If the London position closes (TP/SL/timed-exit) BEFORE an NY
     plan triggers later in the day, the NY dispatch is unblocked
     and the NY plan fires normally. ✓ (new behaviour)
   - If the London position is STILL OPEN when an NY plan
     triggers, the NY dispatch is sent to the broker, the pair
     -concurrency cap rejects it (`pair_concurrency_check` returns
     False), and the NY plan stays armed for a later tick. The
     dispatch never reaches IG. ✗ (gated)

   The "catch both moves on the same pair within the same day"
   behaviour the user mentioned in the Step 2 motivation requires
   2B **and** a future addition of BRIEFING_EXECUTION to
   `_PAIR_CONCURRENCY_BYPASS_MODES` (or a per-mode bypass for
   cross-session legs). That's a separate scope: it involves
   concurrent margin sizing on a single pair (two BRIEFING_EXECUTION
   positions doubles the pair's notional exposure), which is a
   real-money risk decision, not a refactor concern.

   **Document this dependency in the 2B commit body** so future-you
   knows the cross-session-both-fires payoff is gated on a separate
   margin-sizing decision. **Do not fix in 2B.**

**Architecture decisions to flag before implementation:**

1. **Confirm per-session vs per-plan lockout**. Recommendation:
   per-session for 2B (matches operator intuition + pair-concurrency
   cap). Per-plan is a Commit 2D concern, not blocking 2B.
2. **Confirm rank-ascending iteration order**. Recommendation: yes,
   for the reasons in §7.
3. **Confirm `_promote_to_active` becomes append, not replace**.
   RESOLVED (signoff 2026-05-12): yes, append. Late London plans that
   survive 12:30 (e.g. `expires_at='end_of_day'`) coexist with promoted
   NY plans. Both sessions remain firable until each session burns
   its lockout via an actual fire. Operator-intuition fit: "if a
   London plan was authored that's still valid this afternoon, the
   bot should still be willing to fire it." Per-session lockout
   prevents same-session double-fire; cross-session both-fire is
   rare-but-permitted and bounded by the pair-concurrency cap in
   `trade_executor.py:773`.
4. **What does `_drop_active_plan` become?** Recommendation:
   `_drop_plan(sym, plan, reason)` removes ONE plan from
   `_plans[sym]` (the list), audits it under `_invalidated_plans`.
   The old name is misleading post-2B (multiple plans can be
   "active"); rename to `_drop_plan` and update the few internal
   callers.
5. **Backwards-compat one-restart-deep**: 2A-cache + 2B-code must
   round-trip. 2B-cache + 2A-code is one-way (downgrade-incompatible
   but rollback-safe: 2A reads the singular `active_plan` field
   which 2B no longer writes, so 2A sees `active_plan=None` and
   waits for the next briefing). This is the same risk profile as
   2A's `_persist_entered` schema change — accepted.

**Pre-implementation flagged items — RESOLVED 2026-05-12 (user signoff):**

1. Per-session lockout granularity → **per-session** (§5).
2. Rank-ascending iteration with same-tick first-to-satisfy fires → **agreed** (§7).
3. `_promote_to_active` becomes append-not-replace → **agreed** (§6).
4. Late-London + post-12:30-NY coexistence → **MODIFIED**: do NOT
   auto-lock London at 12:30. `_entered[sym][session]` is
   fire-triggered. London plans with surviving `expires_at` and
   matching conditions can still fire post-12:30. See §6 step 4 +
   §9 risk #2 above.
5. CONDITIONAL branches gate on `expires_at` at resolver time →
   **agreed**. `_resolve_active_plan` adds an `expires_at` check
   before scoring; expired branches are skipped silently (with a
   DEBUG log).

---

## Index of evidence cited

- 5 plan-scoped dict declarations: `briefing_execution.py:1273-1289`
- All `_plans` references: §3 of `multi_slot_refactor_surface_2026-05-12.md` (covers reads + writes)
- All `_entered` references: §5 table above
- `evaluate_tick`: `briefing_execution.py:1823-2400`
- `on_bar_close`: `briefing_execution.py:1761-1817`
- `_plan_expired`, `_bar_invalidates_plan` helpers: `briefing_execution.py:1043-1136`
- `_resolve_active_plan`: `briefing_execution.py:1160-1202` (still-current post-2A)
- `_resolve_active_plan` caller: `briefing_execution.py:1415-1429`
- `evaluate_ny_plans`: `briefing_execution.py:1538-1634`
- `_promote_to_active`: `briefing_execution.py:1636-1715`
- `_save_plans_state` payload: `briefing_execution.py:2546-2573`
- `_hydrate_plans_state_from_disk`: `briefing_execution.py:2638-2688`
- `on_broker_confirmed` (post-2A): `briefing_execution.py:2456-2503`
- autobot consumers: `autobot.py:1994, 2670, 2691, 2698`
- Pair-concurrency bypass list: `trade_executor.py:764-769`
- Step 2A prior commit: `f4d3284`
- Prior surface map: `docs/multi_slot_refactor_surface_2026-05-12.md`
- Prior callback plumbing audit: `docs/step2_broker_callback_plumbing_2026-05-12.md`
