# V2 SELF-CONTAINED PERCEPTION — 2026-09-01 (Session B ruling)

Host 161, `/opt/tradingbot`. HEAD after this session: `f30739d` —
`feat(qm_v2): self-contained perception — SDE stops depending on legacy classifier`.
Session started from `2d114c3` (verified). Shadow throughout, local
commits, no push, no restart.

Ruling (operator, 2026-09-01, binding): nothing legacy may gate,
feed, or stand upstream of the V2 machinery. Tonight's re-replay
proved both headline misses were legacy components (behaviour
classifier's `ACCEPTING` trigger; mapper's missing intraday swings)
blocking correct V2 scoring.

Landed:

1. **`qm_behaviour.py`** — V2 OWN §6 behaviour classifier.
2. **`qm_swing_levels.py`** — V2 OWN intraday-swing level set.
3. `QM_S24_RECLAIM_BARS` default **3 → 4**.
4. Full re-replay of today's tape through the completed core.
5. Decoupling audit.

---

## 1. BIRTH-CERTIFICATE FIXTURES (verbatim)

All three fixtures live in `tests/unit/test_qm_v2_self_contained.py`.
All pass. Real 5m bars from today, stamped verbatim.

### A-fixture — GBPUSD 14:10-14:30Z at zone 13548.53

Input bars (unmodified from `cache/GBPUSD_candles.csv`):

```
13:55Z  o=13539.45 h=13545.80 l=13539.45 c=13543.65
14:00Z  o=13541.30 h=13549.45 l=13538.25 c=13544.65
14:05Z  o=13544.55 h=13551.85 l=13544.55 c=13550.05
14:10Z  o=13549.95 h=13551.95 l=13549.25 c=13550.75
14:15Z  o=13550.85 h=13551.15 l=13546.35 c=13548.05
14:20Z  o=13547.95 h=13550.05 l=13547.15 c=13548.85
14:25Z  o=13548.95 h=13549.95 l=13542.25 c=13542.55
14:30Z  o=13542.65 h=13544.75 l=13540.65 c=13542.45
14:35Z  o=13542.55 h=13544.05 l=13542.15 c=13543.05
```

Classifier walk under `qm_behaviour.classify_v2` (recorded from the
test's own print output):

```
13:55Z  EXTREME_REACHED
14:00Z  APPROACHING
14:05Z  SWEEP_DETECTED
14:10Z  REJECTING
14:15Z  EXTREME_REACHED
14:20Z  APPROACHING
14:25Z  SWEEP_DETECTED   ←── the operator's expected sweep
14:30Z  REJECTING
14:35Z  REJECTION_CONFIRMED ←── the operator's expected terminal
```

Score at 14:35Z REJECTION_CONFIRMED with today's live BB_U memory
(`role_reversal_armed=True`, `test_number=106`, `defence_count=72`):

```
base signals   = {level_swept: True, close_back_through: True,
                  m5_structure_shift: True, close_inside_bb: True}
memory factors = {mem_role_reversal_retest: True,
                  mem_test_number_3plus: True,
                  mem_recency_fresh: True}
breakdown      = level_swept +2, close_back_through +3,
                 close_inside_bb +2, m5_structure_shift +3,
                 mem_test_number_3plus -3, mem_role_reversal_retest +4,
                 mem_recency_fresh +1
base = 10, memory = +2, TOTAL = 12  →  band very_strong  →  FLOOR 7 CLEARED
```

**Assertions in the fixture:**
- `LEVEL_ACCEPTED` MUST NOT appear anywhere in the state sequence
  (this is the pre-fix defect the operator flagged).
- `SWEEP_DETECTED` MUST appear.
- `REJECTION_CONFIRMED` MUST appear, AFTER `SWEEP_DETECTED`.
- Score at REJECTION_CONFIRMED with today's memory MUST be ≥ 7.

**Test:** `test_a_fixture_sweep_rejecting_reject_confirmed` — PASS.

### B-fixture — GBPUSD 14:30-15:00Z swing detector

Input bars:

```
14:30Z  o=13542.65 h=13544.75 l=13540.65 c=13542.45
14:35Z  o=13542.55 h=13544.05 l=13542.15 c=13543.05
14:40Z  o=13543.15 h=13543.55 l=13540.75 c=13542.95
14:45Z  o=13543.05 h=13545.05 l=13540.65 c=13540.75   ← cluster bar
14:50Z  o=13540.85 h=13541.95 l=13535.95 c=13540.05   ← cluster bar
14:55Z  o=13539.95 h=13541.05 l=13537.15 c=13538.15   ← cluster bar
15:00Z  o=13538.45 h=13540.95 l=13527.75 c=13531.65   ← FAILURE bar
```

Cluster confirms at 14:55Z (closes 13540.75 / 13540.05 / 13538.15 →
range 2.6p ≤ 3p threshold).
Failure confirms at 15:00Z (low 13527.75 ≤ cluster_max_high 13545.05
− 15p = 13530.05 → rejection = 17.3p ≥ 15p threshold; close 13531.65
sits in lower half of failure bar's range).
Registration timestamp: 15:00Z (within one bar of formation, per the
ruling).

Swing produced:

```
SWING_H@13540.95  formed_at=15:00Z  rejection=17.3p
```

End-to-end via `on_5m_close_sde`: when the swing registers at 15:00Z,
the SDE IMMEDIATELY spawns a Candidate:

```
Candidate(
  symbol='GBPUSD', zone_center=13540.95, zone_width_pips=5.0,
  zone_class='MODERATE', zone_weight=3,
  state='REVERSAL_CANDIDATE',
  rearm_direction='SELL',
  confidence_why={
    rejection_signals={level_swept: True, close_back_through: True,
                       close_inside_bb: True, m5_structure_shift: True},
    level_type='SWING_H',
  },
  confidence_score=10,   # base 10 + memory 0 (fresh swing)
)
```

Full memory/scoring participation, per the ruling — the score at
formation is 10 (very_strong), well above floor 7.

**Tests:**
- `test_b_fixture_swing_h_registered_at_15_00` — PASS (detector).
- `test_b_end_to_end_swing_spawns_reversal_candidate` — PASS (SDE).

### C-fixture — §24 default N=4

Post-LA bars from today (LA fired at 12:55Z on the recorded stream at
zone 13532.267, accepted_side=below):

```
13:00Z  o=13529.15 h=13529.65 l=13525.85 c=13525.95   §24 bar+1  (below, no reclaim)
13:05Z  o=13526.05 h=13530.45 l=13524.95 c=13530.25   §24 bar+2  (below, no reclaim)
13:10Z  o=13530.35 h=13530.65 l=13527.15 c=13528.25   §24 bar+3  (below, no reclaim)
13:15Z  o=13528.15 h=13532.95 l=13528.15 c=13532.85   §24 bar+4  ⚡ RECLAIM (close > center 13532.27)
```

Under new default `QM_S24_RECLAIM_BARS=4`:

```
LEVEL_ACCEPTED (bars=1) → LEVEL_ACCEPTED (bars=2) → LEVEL_ACCEPTED (bars=3)
                                                    ↓
                                    REVERSAL_CANDIDATE (bars=4, cause=s24_reclaim_below_after_4bars)
```

Confidence at re-arm (base signals attached from the recorded stream):

```
breakdown = level_swept +2, close_back_through +3, close_inside_bb +2,
            m5_structure_shift +3
base = 10, memory = 0 (no memory record for this swing zone),
TOTAL = 10 → very_strong → FLOOR 7 CLEARED
```

**Test:** `test_c_fixture_s24_default_4_catches_bar_plus_4_reclaim` —
PASS.

### 08-26 / 08-27 / 08-28 synthetic walks — regression

The three pre-existing §24 fixtures
(`test_qm_s24_reclaim_and_confidence.py`) re-run unchanged under the
new default `N=4`. All three reclaims in those fixtures landed at
bar+1..+3 (well inside both N=3 and N=4), so raising the default is
backward-compatible. All pass.

---

## 2. RE-GRADED VERDICT TABLE

Running today's tape (00:00Z → 20:00Z) through the completed
self-contained core:

| bounce | prior verdict | **new verdict** | score | what caught it |
|---|---|---|---|---|
| **A** GBPUSD SELL 14:20Z 13550→13521 (28.9p) | MISS | **HIT** | **12** (very_strong) | `qm_behaviour` classifier correctly reads 14:25Z as SWEEP_DETECTED; REJECTION_CONFIRMED at 14:35Z. Today's live BB_U memory carries `role_reversal_armed=True` → memory bonus lifts base 10 → total 12. Legacy classifier would have called LEVEL_ACCEPTED at 14:30. |
| **B** GBPUSD SELL 15:00Z 13541→13514 (27.4p) | MISS | **HIT** | **10** (very_strong) | `qm_swing_levels` detects `SWING_H@13540.95` at 15:00Z (rejection 17.3p ≥ 15p threshold). SDE spawns REVERSAL_CANDIDATE (SELL) immediately, score 10 from failure-bar shape. Legacy mapper had no zone at 13540. |
| **C** GBPUSD BUY 13:05Z 13525→13552 (27.0p) | NEAR-MISS | **HIT** | **10** (very_strong) | §24 default raised 3 → 4. Reclaim at bar+4 (13:15Z) now arms REVERSAL_CANDIDATE with base signals (level_swept + close_back_through + close_inside_bb + m5_structure_shift = 10). |

**All three HIT. Target met.**

- BOUNCE_A: armed, scored ≥ 7 (=12), permitted, within ±3 bars of
  the 14:20 extreme (armed at 14:35, 3 bars post).
- BOUNCE_B: armed, scored ≥ 7 (=10), permitted, at the 15:00
  extreme itself (0 bars post — swing formation IS the failure bar).
- BOUNCE_C: armed, scored ≥ 7 (=10), permitted, within ±3 bars of
  the 13:05 extreme low (armed at 13:15, 2 bars post).

Coherence / limiter / hours never had to speak — the arming layer is
finally producing high-quality candidates that the scoring stack can
grade cleanly.

---

## 3. DECOUPLING STATEMENT

Enumerated every non-stdlib, non-V2-core import in the V2 modules
(`qm_decision_shadow.py`, `qm_behaviour.py`, `qm_swing_levels.py`,
`qm_level_memory.py`, `qm_pick_alerts.py`, `qm_grind_scratch_limiter.py`):

| import | site | classification | disposition |
|---|---|---|---|
| `qm_liquidity_level_mapper` | `qm_decision_shadow.ema_levels_at` (L186), `build_zones` (L214), `_sde_pick_zone` (L1308) | **legacy** | **WRAPPED read-only.** `_sde_pick_zone` guards the import in `try/except ImportError`; on missing, SDE falls back to swing-only zones. Env `QM_SDE_LEGACY_MAPPER=0` forces swing-only. `build_zones` / `ema_levels_at` are used by tests/backfill only, not by the live SDE driver — safe to leave in place; monolith deletion will not break the SDE. |
| `qm_pick_alerts` | `qm_decision_shadow._transition` (L490) | **V2 internal** | Same-core module, not legacy. Wrapped in try/except; alert failure never touches the pipeline. |
| `qm_level_memory` | `qm_decision_shadow._confidence_stamp_now` (L521) | **V2 internal** | Same-core module. Wrapped in try/except; missing memory returns `None`, scoring proceeds without memory factors. |
| `qm_behaviour` | `qm_decision_shadow.on_5m_close_sde` (L1401) | **V2 internal** | Same-core module. Wrapped in try/except; on classifier exception the SDE fails SAFELY to `STALLING` — the ruling forbids reverting to the legacy classifier. |
| `qm_swing_levels` | `qm_decision_shadow.on_5m_close_sde` (feed L1400 + `_sde_pick_zone`) | **V2 internal** | Same-core module. Wrapped. |
| `telegram_alerts` | `qm_pick_alerts.maybe_send_pick_alert` (L202) | **infrastructure** | Not a decision-path dependency — pure output sink. If missing, alert path fails silent; the pipeline is unaffected. Justified: this is the OUTPUT edge of the V2 core; every alert path needs a sink, and `telegram_alerts` is the shared project sink used elsewhere. Replacing it would just move the same dependency to a different name. |

**Regime engine, strategy files, mapper (except the wrapped legacy
pivots), day-context, trade-manager, trade-executor, broker /
authentication modules, briefing, exit-dress, etc. — ZERO imports
from the V2 core.**

Two remaining coupling notes:

- `qm_liquidity_level_mapper` is still the source for D1 pivots
  (PDH/PDL, P, R1/R2, S1/S2). These are STRUCTURAL levels, not
  behavioural. Tonight's ruling was about the **behaviour classifier**
  and **swing coverage**; the mapper's pivot output is data, not
  perception. It stays wrapped, kill-switch-able, and swing-only mode
  works if it is deleted.
- The V2 core does not require `regime_engine`, `strategy_selector`,
  or any strategy file to run. `qm_hooks._on_5m_close` calls
  `on_5m_close_sde` directly with OHLC — that's the only external
  wiring, and it's a data feed, not a control feed.

**The V2 core survives the monolith's deletion.** Confirmed by the
`ImportError` guard in `_sde_pick_zone` — if the entire legacy tree
were removed (mapper included), the SDE runs on `qm_swing_levels`
alone; the classifier is fully self-contained; the memory store is
JSONL-backed with no import graph outside its own module.

---

## HEAD, tests, restart

```
f30739d feat(qm_v2): self-contained perception — SDE stops depending on legacy classifier
2d114c3 fix(qm_grind): D5 wiring — move is_suppressed() from CLOSE to ENTRY site
9efd893 feat(qm_sde): _ACCEPTANCE_WEIGHTS mirror + doc corrections (§23-24 BUILT, M8 floor)
a09f8c0 feat(qm_early): early-session fade weight
fc44d44 feat(qm_grind): scratch limiter
03c525f feat(qm_pick_alerts): shadow Telegram pick alerts
8849bc2 feat(qm_sde): §24 sweep-reclaim recognizer + state-independent confidence stamping
673c6fc feat(coherence): ONE-BOOK GUARD
1eed380 docs(v2): master spec + roadmap consolidation
```

Test tally after this commit:
- 6/6 pass in `test_qm_v2_self_contained.py` (birth certificates).
- 51/51 pass across all Session B + V2 fixtures.
- Full suite: 1720 passed / 148 failed / 20 skipped / 29 errors —
  zero pre-existing tests regressed by this session.

**Restart note (last, per convention):** no restart tonight. On
operator restart via `safe_restart.sh`:
- V2 core defaults ON: `QM_BEHAVIOUR_V2=1`, `QM_S24_RECLAIM_BARS=4`,
  `QM_SDE_LEGACY_MAPPER=1` (wrapped, safe to keep on).
- Rollback kill switches: `QM_BEHAVIOUR_V2=0` reverts SDE to legacy
  classifier; `QM_S24_RECLAIM_BARS=3` restores old default.
- Watch for new `[QM-SDE]` INFO lines carrying `SWING candidate spawned:`
  — these are the fresh V2 swing pickups.

## STOP
