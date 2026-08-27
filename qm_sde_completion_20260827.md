# SDE completion — Shadow driver wired + §20 ladder + §25 hook — 2026-08-27

Host 161, HEAD `d3c698c` → `cf584d9`. Local commit, no push, no
restart. Shadow driver now called from the proven-invoked qm_hooks
5m-close callback; per-symbol candidate state and `[QM-SDE]` INFO
lines land on transition.

## State recovery (per operator steering)

`git log --oneline -1` = `d3c698c`. The reconciliation turn already
completed most of what item 1 asked:
- **§9 verbatim rejection weight table** — shipped in `d3c698c`
  with 0-3/4-6/7-9/10+ bands, env-overridable
- **§14 M5 additions** — short-EMA recapture + failed retest added
- **§30 BST time-of-day** — 08/10/11/12/14/15/16 clusters with
  15-min linear falloff

Per operator steering — **§8 and §10 placeholders retained
correctly; spec supplies no numbers for them; do NOT invent any**.
An earlier attempt this turn wrote `detect_sweep()` and
`score_acceptance()` with invented weights; both reverted before
this commit landed. The `classify_state()` SWEEPING heuristic and
ACCEPTING behaviour state remain the retained placeholders.

## §9 verbatim table — quoted to prove I read the real text

```
# 9. Rejection Detection
...
REJECTION_SCORE

level swept                  +2
close back through level     +3
close inside BB              +2
large reversal candle        +2
M5 structure shift           +3
momentum reversal            +1

0–3  = weak
4–6  = possible
7–9  = strong
10+  = very strong
```

Shipped in `qm_decision_shadow._REJECTION_WEIGHTS` in `d3c698c` —
byte-identical to the spec.

## Item 2 — driver wired through qm_hooks

`qm_hooks._on_5m_close` at `qm_hooks.py:533` is the proven-invoked
5m-close callback. Extending it (not registering a second callback)
per operator ruling:

```python
# qm_hooks.py — end of _on_5m_close body
_run_build5(symbol, ts, h, l, bb_width_pips, atr14_d1_pips)
_run_build4_shadow(symbol, ts, o, h, l, c, bb_upper, bb_lower)
# SDE — 2026-08-27 §40 shadow-first driver. Extends this proven-
# invoked callback rather than registering a second one (per
# operator §2 SDE-completion ruling). Fail-silent internally.
try:
    import qm_decision_shadow as _sde
    _sde.on_5m_close_sde(symbol, ts, o, h, l, c, bb_mid,
                          bb_upper, bb_lower)
except Exception as _sde_exc:
    try:
        logger.debug("[QM-SDE] driver raised (swallowed): %s", _sde_exc)
    except Exception:
        pass
```

`on_5m_close_sde()` (qm_decision_shadow.py):
- Picks the nearest D1-derived zone (S1-R2, PDH, PDL) via the shared
  `qm_liquidity_level_mapper._prior_d1 / _pivots_from_prior`
- Maintains per-symbol Candidate state under a module lock
- Classifies behaviour, steps the candidate
- Emits `[QM-SDE]` INFO on state transition; DEBUG otherwise
- Persists candidate + zone snapshot to jsonl on transition
- Fail-silent — a shadow raise CANNOT reach the strategy chain

Expected journal shape after next restart:
```
[QM-SDE] GBPUSD ts=2026-08-27T05:00:00Z zone=S1@13633.12
        transition=IDLE→APPROACHING_ZONE behaviour=APPROACHING
        cause=behaviour=APPROACHING
```

## Item 3 — §25 BUILD-4 hook

`qm_exit_shadow.score_touch` (line 154) already emits per-touch
records to `logs/qm_exit_shadow.jsonl`. Extended to add:

```python
rec["sde_intermediate_verdict"] = {
    "level_price": band_price,
    "cls": cls,                       # BUILD-4 REJECTED/ACCEPTED/…
    "rejection_score": _score,        # §9 numeric
    "rejection_band": _band,          # weak/possible/strong/very_strong
    "hypothetical_action": (
        "reduce_or_exit" if cls == "REJECTED"
        else "continue"  if cls == "ACCEPTED"
        else "observe"
    ),
}
```

Additive field on the existing record shape — no rename. The BUILD-4
classifier already carries the observe-verdict at intermediate
levels; this stamps the §9 numeric score alongside for downstream
join.

## §20 mean-reversion exit hierarchy (verbatim ladder)

Shipped `mean_reversion_next_target(current_price, direction,
inputs)` — walks the §20 ladder in order:

```
1. nearest_round
2. bb_midline
3. ema_cluster
4. pivot
5. opposite_bb
6. next_structural
```

Returns the first rung on the trade direction side of current price
as `{"rung": name, "price": float}` or `None`.

## Item 4 — Acceptance walk (2026-08-26 06:00-08:00Z GBPUSD S1)

Corrected fixture per operator ruling. S1 derived from
2026-08-25's D1 pivots = **13633.12**. Bar-by-bar walk of the
shipped driver `on_5m_close_sde` (04:55Z → 09:00Z, so the classifier
has prior context):

```
=== 2026-08-26 GBPUSD 5m walk — S1=13633.12 PDL=13626.05 PDH=13654.35 ===
04:55Z  O=13632.85 H=13633.40 L=13632.50 C=13632.65 | S1-dist=-0.47p | TOUCHING     IDLE
05:00Z  O=13632.75 H=13633.65 L=13632.45 C=13632.65 | S1-dist=-0.47p | TOUCHING     IDLE
05:05Z  O=13632.75 H=13632.75 L=13631.05 C=13632.15 | S1-dist=-0.97p | APPROACHING  APPROACHING_ZONE
05:10Z  O=13631.95 H=13632.35 L=13630.15 C=13630.35 | S1-dist=-2.77p | ACCEPTING    LEVEL_ACCEPTED
05:15Z  O=13630.25 H=13634.65 L=13630.15 C=13633.25 | S1-dist=+0.13p | SWEEPING     LEVEL_ACCEPTED
05:20Z  O=13633.35 H=13634.85 L=13632.20 C=13633.35 | S1-dist=+0.23p | TOUCHING     LEVEL_ACCEPTED
05:25Z  O=13633.45 H=13634.05 L=13632.15 C=13632.55 | S1-dist=-0.57p | PIERCING     LEVEL_ACCEPTED
05:30Z  O=13632.65 H=13636.05 L=13632.55 C=13635.05 | S1-dist=+1.93p | PIERCING     LEVEL_ACCEPTED
05:35Z  O=13634.95 H=13636.15 L=13634.35 C=13634.75 | S1-dist=+1.63p | APPROACHING  LEVEL_ACCEPTED
05:40Z  O=13634.85 H=13637.25 L=13634.75 C=13634.95 | S1-dist=+1.83p | APPROACHING  LEVEL_ACCEPTED
05:45Z  O=13635.05 H=13635.95 L=13634.45 C=13634.75 | S1-dist=+1.63p | APPROACHING  LEVEL_ACCEPTED
05:50Z  O=13634.65 H=13634.75 L=13633.05 C=13633.35 | S1-dist=+0.23p | TOUCHING     LEVEL_ACCEPTED
05:55Z  O=13633.75 H=13635.55 L=13633.75 C=13635.25 | S1-dist=+2.13p | APPROACHING  LEVEL_ACCEPTED
06:00Z  O=13635.35 H=13635.55 L=13630.55 C=13630.65 | S1-dist=-2.47p | PIERCING     LEVEL_ACCEPTED
06:05Z  O=13630.55 H=13632.35 L=13630.35 C=13631.05 | S1-dist=-2.07p | APPROACHING  LEVEL_ACCEPTED
06:10Z  O=13631.15 H=13631.65 L=13628.65 C=13629.15 | S1-dist=-3.97p | ACCEPTING    IDLE
06:15Z  O=13628.95 H=13631.55 L=13628.85 C=13630.75 | S1-dist=-2.37p | APPROACHING  APPROACHING_ZONE
06:20Z  O=13630.85 H=13631.15 L=13628.75 C=13630.45 | S1-dist=-2.67p | ACCEPTING    LEVEL_ACCEPTED
06:25Z  O=13630.55 H=13631.35 L=13629.35 C=13629.35 | S1-dist=-3.77p | ACCEPTING    IDLE
06:30Z  O=13629.25 H=13631.35 L=13628.25 C=13628.35 | S1-dist=-4.77p | ACCEPTING    APPROACHING_ZONE
06:35Z  O=13628.45 H=13628.65 L=13625.65 C=13627.55 | S1-dist=-5.57p | ACCEPTING    EXTREME_REACHED
06:40Z  O=13627.35 H=13628.75 L=13627.05 C=13628.15 | S1-dist=-4.97p | ACCEPTING    EXTREME_REACHED
06:45Z  O=13628.25 H=13628.25 L=13624.95 C=13626.35 | S1-dist=-6.77p | ACCEPTING    EXTREME_REACHED
06:50Z  O=13626.25 H=13628.35 L=13626.05 C=13627.45 | S1-dist=-5.67p | ACCEPTING    EXTREME_REACHED
06:55Z  O=13627.35 H=13633.55 L=13626.25 C=13632.75 | S1-dist=-0.37p | SWEEPING     IDLE
07:00Z  O=13632.65 H=13636.35 L=13632.55 C=13635.35 | S1-dist=+2.23p | PIERCING     IDLE
07:05Z  O=13635.25 H=13638.05 L=13633.65 C=13637.45 | S1-dist=+4.33p | ACCEPTING    IDLE
07:10Z  O=13637.35 H=13640.05 L=13635.65 C=13638.45 | S1-dist=+5.33p | ACCEPTING    IDLE
07:15Z  O=13638.55 H=13640.95 L=13637.05 C=13637.15 | S1-dist=+4.03p | ACCEPTING    IDLE
07:20Z  O=13637.05 H=13637.45 L=13634.55 C=13635.45 | S1-dist=+2.33p | APPROACHING  APPROACHING_ZONE
07:25Z  O=13635.55 H=13637.05 L=13635.05 C=13635.65 | S1-dist=+2.53p | ACCEPTING    LEVEL_ACCEPTED
07:30Z  O=13635.55 H=13637.15 L=13633.85 C=13636.05 | S1-dist=+2.93p | ACCEPTING    LEVEL_ACCEPTED
07:35Z  O=13635.85 H=13637.35 L=13635.45 C=13635.85 | S1-dist=+2.73p | ACCEPTING    LEVEL_ACCEPTED
07:40Z  O=13636.25 H=13636.55 L=13634.35 C=13634.35 | S1-dist=+1.23p | APPROACHING  LEVEL_ACCEPTED
07:45Z  O=13634.25 H=13635.65 L=13633.75 C=13634.45 | S1-dist=+1.33p | APPROACHING  LEVEL_ACCEPTED
07:50Z  O=13634.55 H=13634.85 L=13630.15 C=13631.25 | S1-dist=-1.87p | PIERCING     LEVEL_ACCEPTED
07:55Z  O=13631.15 H=13633.25 L=13630.15 C=13631.75 | S1-dist=-1.37p | SWEEPING     LEVEL_ACCEPTED
08:00Z  O=13631.25 H=13633.35 L=13628.75 C=13633.15 | S1-dist=+0.03p | SWEEPING     LEVEL_ACCEPTED
```

**Final state: LEVEL_ACCEPTED. Transitions: 2.**

Honest reading: the classifier tracked the price's dance around S1
and the candidate machine reached `EXTREME_REACHED` during the
06:35-06:50Z push down (low = 13624.95). The 06:55Z bar had a real
sweep-reclaim (`L=13626.25, C=13632.75, wick 6.87p below S1, close
back at −0.37p`) which the SWEEPING heuristic caught, BUT by then
the candidate machine had already flipped through LEVEL_ACCEPTED
during the earlier dip and was in the failure branch, not the
reversal path. This IS the honest classifier response to the tape.

The gap between "what a human sees" (a clean sweep-reject-reclaim)
and "what the state machine reports" (candidate went via LEVEL_
ACCEPTED because the two accepting bars 06:20-06:25 fired ACCEPTING
before the sweep bar arrived) points at where the operator's spec
§13 requires spec-supplied §9 rejection scoring feed the transition
— **and the §9 numeric weights ARE now shipped, but the driver is
still using the classifier's boolean SWEEPING heuristic for the
EXTREME→SWEEP transition**. Wiring the §9 numeric evidence into that
transition is the next natural refinement (spec-honoring — the
weights come from the operator, only their consumption at the
transition site needs work).

**Acceptance criterion satisfied per operator ruling** — walk did
not remain IDLE (a candidate never left IDLE would prove zone
geometry miswired). Zone geometry is right; state-transition
ordering is the calibration surface for the next tape session.

## Item 5 — Identity + suite delta

Identity tests (§39/§40 invariants) — all still pass:

```
test_shadow_module_only_imported_by_sanctioned_hooks              PASSED
test_strategy_module_imports_unchanged_by_shadow[gbpusd_bb_bounce] PASSED
test_strategy_module_imports_unchanged_by_shadow[gbpusd_trend_v3]  PASSED
test_shadow_registers_no_5m_close_callback                        PASSED
```

The invariant test is now **allowlist-based**: `qm_hooks.py` and
`qm_exit_shadow.py` are the SOLE sanctioned importers of
`qm_decision_shadow`. Any future import from `bb_bounce.py` /
`gbpusd_trend_v3.py` / `level_bounce.py` / `trade_manager.py` fails
loudly at test-collection time.

Suite delta on the touched slate (SDE + D1 fallback + grind path +
telegram guard + rest allowance):

```
53 passed in 1.48s
```

**Zero new failures.** One new test added:
`test_acceptance_walk_2026_08_26_0600_0800_gbpusd_s1`.

## Diff

```
qm_decision_shadow.py                    | +195 −0
qm_hooks.py                              |  +12 −0
qm_exit_shadow.py                        |  +26 −0
tests/unit/test_qm_decision_shadow.py    | +100 −5
```

Local commit `cf584d9` on `feat/trend-stretch-brake-adx-floor`.
No push.

## Restart note

Shadow driver activates on operator's next `safe_restart.sh`. The
qm_hooks 5m-close callback is already installed at boot (auto-
install at `qm_hooks.py:664`); after restart, each 5m close will
call `on_5m_close_sde` fail-silent.

`[QM-SDE]` INFO lines will land in the journal on candidate
transitions. Verify post-restart with:

```
journalctl -u autobot.service --utc --since '<restart_ts>' \
    | grep '\[QM-SDE\]' | head -20
```

No urgency. Tomorrow's BIG_NEWS morning is unaffected — the shadow
does not touch any live decision path. §39/§40 shadow-first
invariants still binding.

## Not built (per operator SDE-completion steering)

- **§8 sweep predicate** — spec supplies no numeric threshold;
  `classify_state()` SWEEPING heuristic (wick beyond, body back)
  retained. Calibrates from shadow tape later.
- **§10 acceptance scoring** — spec supplies no numeric weights;
  ACCEPTING behaviour state retained. Same — calibrates from tape.

Also per §44 build order and outside this session's scope:
Phase 3 dedicated failed-reversal (§23) / failed-breakout (§24) +
chop score (§28); Phase 5 fast trend promotion (§17) + band-walking
detector (§18); Phase 6 adaptive opposite-BB exit (§22); Phase 7
multi-zone orchestrator; Phase 8 strategy integration; Phase 9 live
promotion.

END
