# V3 approved-build — technical reconciliation

**Date:** 2026-10-15
**Operator ruling:** validation report v2 (commit `d48e939` on `feat/v3-approved-build-20261015`, published to `report/v3-approved-build-continuation-20261015`) is **rejected**. This document reconciles the seven points the operator required, before any further evaluation is run.
**Class:** READ-ONLY investigation. **No new backtest executed.** No production edit, no .env change, no service restart, no deploy, no PAA.

---

## 0. One-line conclusion

**The evaluator that produced the rejected V3 Bounce results runs `bounce_engine.v3.engine.V3Engine` — "AutoBot V3 Structural Momentum". That engine does not consult structural levels or QM, uses SL 12 and NO fixed TP (swing trail), and is NOT the engine the approved spec describes.** The spec's description ("executes valid structural reversals near pre-established significant levels" + "QM observations inform the existing trade manager") maps to a **different** engine (`bounce_engine.core.Engine`, Setup A/C/SQ/TR, modes `BOUNCE_A/C/SQ/TR`), which already consumes `view_levels` and `qm_verdict` and uses `BOUNCE_EXIT_MODE=june` (SL 20p / scale-half at +10p / TP 30p). The rejected evaluation measured V3Engine's raw BB/EMA detection, which has no overlap with the spec's intended composition. Stage 0b compliance cannot be verified from host 161.

---

## 1. P1 — Production V3 Bounce entry conditions

### 1.1 Two engines claim the "V3 Bounce" name

| Engine | File | Mode tags | Flag | Consumes levels? | Consumes QM? |
|---|---|---|---|---|---|
| **`bounce_engine.core.Engine`** ("Setup A/C/SQ/TR") | `/opt/tradingbot/bounce_engine/core.py` | `BOUNCE_A_L/S`, `BOUNCE_C_L/S`, `BOUNCE_SQ_L/S`, `BOUNCE_TR_L/S` | `BOUNCE_ENGINE_ENABLED=1` (.env:1050) | **Yes** — `levels_fn=view_levels` (`ports.py:30`) | **Yes** — `qm_fn=qm_verdict` (`ports.py:59`) |
| **`bounce_engine.v3.engine.V3Engine`** ("AutoBot V3 Structural Momentum") | `/opt/tradingbot/bounce_engine/v3/engine.py` | `V3_BB_L/S`, `V3_EMA_L/S` | `V3_ENABLED=1` (.env:1072) | **No** | **No** |

Both are LIVE in production.

### 1.2 `bounce_engine.core.Engine` entry conditions

`Engine.__init__` (`core.py:424`) accepts:

```python
def __init__(self, *, cfg: Config, levels_fn: Callable[[], List[Level]],
             qm_fn: QMFn, orders, journal, events_fn=None) -> None:
```

The live wiring (`bounce_engine_live.py:471`):

```python
from bounce_engine.core import Config, Engine
from bounce_engine.ports import (
    Journal, events_today, qm_verdict, view_levels,
)
...
_ENGINE = Engine(
    cfg=Config(),
    levels_fn=view_levels,
    qm_fn=qm_verdict,
    orders=port,
    journal=journal,
    events_fn=events_today,
)
```

Setup gates (`core.Config`, `core.py:94-150`):

- **Setup A** (BB pierce → rejection → level): active unconditionally (default).
- **Setup C** (exhaustion, 25p arm): `BOUNCE_EXHAUSTION_ENABLED=1` (prod .env:1053).
- **Setup SQ** (Aroon squeeze → H1 breakout at level): `BOUNCE_SQUEEZE_ENABLED=1` (.env:1051).
- **Setup TR** (H1 trend proof + 5m pullback into EMA band): `BOUNCE_TREND_ENABLED=1` (.env:1052).
- **HTF direction gate** (D1 EMA20 + H4 EMA20): `BOUNCE_HTF_DIRECTION_ENABLED=1` (.env:1059).
- **TR requires HTF proof**: `BOUNCE_TREND_HTF_PROOF_ENABLED=1` (.env:1060).
- **C requires MACD contraction on failure candle**: `BOUNCE_C_MACD_FADING_ENABLED=1` (.env:1061).
- **News view** (journals news-day proposition): `BOUNCE_NEWS_VIEW_ENABLED=1` (.env:1054).
- **Exhaustion close** (June mode): `BOUNCE_JUNE_EXHAUSTION_CLOSE_ENABLED=1` (.env:1063).

Entry invariants (`Config`):

- `bb_period=20, bb_std=2.0` — Bollinger (confirmed).
- `level_window_pips=5.0` — "at a level" = within 5 pips of a structural level from `view_levels`.
- `arm_expiry_bars=5` — armed stop order lives 5 candles.
- `min_stop_pips=12.0` — IG minimum stop distance (regulator floor).
- `exhaustion_arm_pips=25.0` — Setup C arm threshold.

### 1.3 `bounce_engine.v3.engine.V3Engine` entry conditions

Four entry detectors — `detect_bb_short/long` and `detect_ema_short/long` (`detectors.py:209, 318, 466, 512`).

- `detect_bb_*` requires:
  - 5m close pierces BB(20, 2) upper/lower.
  - Rejection body strength (`body_rel_min=1.0` relative to median body in `body_window=12`).
  - Optional repeat-failure arm (`repeat_lookback=12`, `repeat_touches=2`, `repeat_near_pips=1.0`).
- `detect_ema_*` requires:
  - 5m close touches / closes beyond the EMA cluster (8/13/21).
  - Cluster-bound reclaim rules.
- Internal "levels" in V3Engine are EMA cluster boundaries, NOT external structural pivots. The term "`level_name`" in `engine.py:677/711/720` refers to the cluster index, not `view_levels`.
- No call to `view_levels`, `qm_verdict`, `qm_level_interactions`, `level_snapshot_v6`, or any external level service. **V3Engine is self-contained on indicators + bars.**
- NMS gate: `V3_NMS_AUTHORITY_GATE_ENABLED` env flag — **defaults OFF**; status in prod .env not set (reads `0`). V3Engine is thus NOT gated by NMS today.

### 1.4 Which engine does the spec describe?

Spec §Execution ¶1:
> *"V3 Bounce (NOT legacy standalone BB Bounce) executes valid structural reversals near pre-established significant levels."*

Spec §QM-informed management:
> *"Existing QM REJECT / ACCEPT / BREAK_AWAY / OSCILLATING observations inform the existing trade manager as positions approach significant levels."*

**`core.Engine` matches both clauses verbatim** — it is "V3 Bounce near pre-established significant levels" with `view_levels` + `qm_verdict` already wired. **`V3Engine` does not consume levels or QM at all.** The name "V3" is shared across both; this is why the rejection is correct.

A reasonable reading of the spec is: the approved model is `core.Engine` (NOT `V3Engine`). An alternative reading is: `V3Engine` should be WRAPPED with a level/QM filter — but that would require code changes which the operator forbids ("do not introduce new strategies, detectors or trading gates").

A third reading: both engines run concurrently in production today; the spec expects the composed PORTFOLIO behaviour (BOUNCE_A/C/SQ/TR + V3_BB/EMA + Trend V3 + EMA Pullback) to be validated jointly. The evaluation I performed covered only ONE of these.

---

## 2. P2 — Historical evaluator import chain

### 2.1 Entry point

```
/opt/tradingbot/bounce_engine/v3/eval_historical.py
```

Invocation used for the rejected report:

```
python3 -m bounce_engine.v3.eval_historical --partition dev     --anchor FRIDAY --size 2.0 --out-dir /tmp/v3_eval_dev
python3 -m bounce_engine.v3.eval_historical --partition oos2026 --anchor FRIDAY --size 2.0 --out-dir /tmp/v3_eval_oos
```

### 2.2 Imports (eval_historical.py:24-28)

```python
from .engine import V3Config, V3Engine
from .pivot_compare import anchor_for, pivots_from
from .types import LONG, SHORT, M5Bar
from .window import in_entry_window, london_date_for
```

The evaluator imports **`V3Engine` from `bounce_engine.v3.engine`** — this is engine (B) in §1.1. It does **not** import `bounce_engine.core.Engine`, nor `view_levels`, nor `qm_verdict`.

### 2.3 Engine construction (eval_historical.py:264-269)

```python
cfg = V3Config()
cfg.feed_gap_tolerance_s = 30 * 60   # research override (prod: 360)
cfg.auto_clear_unknown_after_bars = 12  # research override (prod: 0)
eng = V3Engine(cfg=cfg, pivot_provider=_pivot_provider(anchor))
```

Only two overrides vs production:

- `feed_gap_tolerance_s`: 1800 s (research) vs 360 s (prod). Rationale: tolerate one or two missing archive bars.
- `auto_clear_unknown_after_bars`: 12 (research) vs 0 (prod). Rationale: a DST / holiday archive gap should not mute a 1.5-year backtest.

Both are documented as "research-only" in `V3Config` docstring (`engine.py:98-150`).

### 2.4 Engine driver loop

- Loads M5 bars from `STORE_BID = /opt/tradingbot/data/candles_ext_v2/GBPUSD` (dev) or `STORE_MID = /opt/tradingbot/data/candles/GBPUSD` (OOS2026).
- Groups bars by UTC day.
- For each bar: calls `eng.on_bar_close(bar)` and processes the returned `V3Event` list.
- Materialises a `Trade` for each `TRIGGER` event and tracks it through `STOP_HIT` / `EXIT_WARNING_BREAK` events.
- `_apply_exit(...)` applies the cost model (0.9 pip spread, 0.5 pip stop/warning slip, SHORT = entry_bid - exit_ask, LONG = exit_bid - entry_ask).

### 2.5 What the evaluator does NOT invoke

- No `bounce_engine.core.Engine` — Setup A/C/SQ/TR entries never fire in this harness.
- No `view_levels` / `view_builder` — structural levels never enter.
- No `qm_verdict` / `qm_decision_shadow` — QM observations never gate decisions.
- No `nms_v3_direction_gate.check` — NMS is bypassed.
- No `htf_authority.evaluate` — HTF context (D1/H4) is applied internally by V3Engine only.
- No `trade_manager.py` / `tiered_ratchet.py` — the real exit stack is not exercised.

**The evaluator measures only V3Engine's self-contained BB/EMA detection + swing-trail exit.**

---

## 3. P3 — TP/SL baseline verification

### 3.1 Spec baseline

> *"The required baseline is TP 30 pips, SL 12 pips, subject to verifying the existing production configuration."*

### 3.2 V3Engine (what the evaluator used)

`V3Config` (`engine.py:98-150`):

```python
initial_stop_pips: float = 12.0        # confirmed
trail_eligible_pips: float = 10.0      # confirmed
trail_offset_pips: float = 3.0         # confirmed
# NO take-profit field exists.
```

Exit mechanics (`engine.py`):

- `STOP_HIT` — price touches `initial_stop_pips=12` (or the trailed version).
- `EXIT_WARNING_BREAK` — swing-trail trigger (opposite swing breaks).
- **No `TARGET_HIT` / TP exit.** Grep for `tp`, `TP`, `target`, `TARGET` across all V3 modules returned no profit-target configuration.

**V3Engine matches the spec's SL (12 pips) but has NO fixed TP.** The eval report `v3_bounce_oos2026_eval.md` shows exits only as `STOP: 947` and `WARNING_BREAK: 1493` across 2,440 trades — no TP exits recorded, which is consistent.

### 3.3 `core.Engine` under `BOUNCE_EXIT_MODE=june` (production live)

`core.py:143`:

> *"A4: BOUNCE_EXIT_MODE = 'levels' (default, current managed-exit) or 'june' (SL 20p; at +10p close half + stop-to-entry; TP 30p or BE)."*

Production .env:1062: `BOUNCE_EXIT_MODE=june`. Production .env:1065: `BOUNCE_BROKER_TP_PIPS=100` (the broker-side ceiling, superseded by the June TP of 30p). Also `BOUNCE_JUNE_EXHAUSTION_CLOSE_ENABLED=1` (.env:1063).

Direct quote (`core.py:1668`): *"Remainder: TP at entry+/-30, or close at BE if price retraces."*

So **`core.Engine` under June mode uses SL=20, scale-half at +10, TP=30**.

### 3.4 Comparison matrix

| | Spec baseline | V3Engine (eval target) | core.Engine @ june (prod live) | core.Engine @ levels |
|---|---|---|---|---|
| SL (initial) | **12 p** | 12 p ✓ | 20 p ✗ | structural (managed) |
| TP | **30 p** | **none** ✗ | 30 p ✓ | structural (managed) |
| Scale half at +10 p | — | no | yes | no |
| Trail | n/a | swing trail | n/a | n/a |

**No single engine configuration in production matches the spec's "TP 30 / SL 12" exactly.** V3Engine matches SL only; core.Engine @ june matches TP only. If the spec's "subject to verifying the existing production configuration" clause means *adopt whichever production configuration exists*, then June mode's `20/30` is the production baseline — not `12/30`. If the spec intends a NEW configuration (SL 12 AND TP 30 on either engine), it does not exist in code today and would require an operator-approved parameter change (which this build is forbidden to make).

### 3.5 The rejected report's cost-model statement vs the engine's actual behaviour

The rejected report cited the evaluator's own cost-model block (spread 0.9, stop slip 0.5) correctly. However the evaluator's exit outcomes are **swing-trail / stop** only. The report did not call out the absence of a TP mechanism in the evaluated engine. That omission is where the "TP 30" clause of the spec went unverified.

---

## 4. P4 — Evaluator vs production parity

### 4.1 Parity table (V3Engine vs its live-production path)

| Element | Production path (bounce_engine/v3/live.py) | Evaluator (eval_historical.py) | Parity |
|---|---|---|---|
| Engine class | `V3Engine` from `.engine` | same | ✓ |
| Config source | `V3Config.from_env()` | `V3Config()` default + 2 overrides | **differs** (research overrides) |
| Pivot anchor source | `pivot_compare.anchor_for` live | same via `_pivot_provider` | ✓ |
| Bar input | `candle_builder.register_5m_close_callback` live stream | `load_m5(store, ...)` from CSV archive | ✓ (bars identical; timing is replay) |
| Tick input | `autobot._on_ls_tick` → `V3Engine.on_tick` | **BYPASSED** — eval synthesises a 2-tick sequence per bar (`_tick_sequence_for_bar`) | **differs** (no mid-bar ticks; stop/warning hits can only register at bar boundaries) |
| Order port | `LiveIGOrderPort` from `bounce_engine_live` | **NOT USED** — evaluator materialises `Trade` directly from engine events | differs by design |
| Journal | `Journal` to `logs/*.jsonl` | **NOT USED** | differs by design |
| State persistence | `.persist.load/save` to `state/v3_<SYMBOL>.json` | **NOT USED** — evaluator starts from a clean engine per partition | differs by design |
| NMS gate | `nms_v3_direction_gate.check` (gated by `V3_NMS_AUTHORITY_GATE_ENABLED`, default off → no block) | **BYPASSED** (same as live default-off) | ✓ in current prod state |
| View levels (`view_levels`) | **NOT CALLED by V3Engine** | **not called** | ✓ |
| QM (`qm_verdict` / `qm_level_interactions`) | **NOT CALLED by V3Engine** | **not called** | ✓ |
| Trade-manager exits (`trade_manager.py`, `tiered_ratchet.py`) | **NOT USED by V3Engine** — V3Engine owns its own exit stack | same | ✓ |
| Spread | **mid-price feed in live tick path; no explicit spread subtraction at exit — relies on IG fills** | **0.9 pip FIXED** adverse applied at every exit | **differs materially** (live has no fixed spread; eval assumes 0.9p) |
| Slippage | **IG broker fills** | **0.5 pip adverse** on every STOP / WARNING_BREAK | **differs** |

### 4.2 Interpretation

- The evaluator **IS** faithful to V3Engine's bar-level entry/exit **state transitions**: same code, same config family, same pivot stream, same bar discipline.
- The evaluator **IS NOT** faithful to:
  - **Mid-bar tick dynamics** — a stop or warning break that fires inside a bar (not at bar-close) is approximated by a 2-tick (OHLC-ordered) sequence; live ticks arrive continuously.
  - **IG execution costs** — the eval's 0.9 pip spread + 0.5 pip slip is an engineering assumption. Actual IG fills are quote-driven and vary.
  - **Portfolio and position-cap interactions** — V3Engine is single-position per instrument; the eval respects that, but any cross-strategy capacity reservations (BB_BOUNCE_ADMIT, ONE_STRATEGY concurrent cap, etc.) are not modelled.
- Crucially, the evaluator **IS NOT a replay of the SPEC's model** — it is a replay of V3Engine's self-contained behaviour. §1.4 and §2.5 cover why.

---

## 5. P5 — Stage 0b candle-timestamp verification

### 5.1 What the spec requires

> *"Verify the historical candle timestamps against the completed Stage 0b correction manifest."*

### 5.2 What exists on host 161

- **No Stage 0b correction manifest is reachable on host 161 under `/opt/tradingbot/`.** `grep -rE "Stage 0b|STAGE_0B|stage_0b|clock_verdict"` across the production tree returns no hits.
- **`autobot_reports` carries three STAGE_0B_PREREG commits** (2026-10-08: `b1b1b62` → `38dcb9c` → `15d9a83`) — these are **pre-registration documents, not a completion manifest**. The pre-reg describes the methodology for establishing candle timestamp authority via release-anchored price search; it does **not** record a verdict for any store.
- **`reports/v3/FREEZE.md:176`** (committed by the operator to the research tree) states explicitly: *"Stage 0b clock verdicts: NOT present on 161 under `/opt/tradingbot/`. ... The historical evaluation in section 6 is therefore labelled UNVERIFIED CLOCKS on both stores."*
- **The rejected eval's own output** (`v3_bounce_oos2026_eval.md:7`) preserves this caveat: *"Clocks on the candle store are UNVERIFIED (no Stage 0b verdict on 161) — results labelled accordingly."*

### 5.3 Conclusion

The verification requested cannot be performed from host 161 as of 2026-10-15. The Stage 0b correction manifest the operator references is either (a) in a worktree / repo not reachable from this host, (b) a planned artefact not yet produced, or (c) a document held outside the version-control systems I can read. **This is a prerequisite for a faithful eval. Any evaluation that proceeds without it carries the same UNVERIFIED CLOCKS caveat.**

The pre-reg methodology (12 release anchors with per-anchor provenance blocks + mechanical rules for AMBIGUOUS_ANCHOR / NO_TICK_ANCHOR) is clear enough that, once the manifest lands, applying it to `candles_ext_v2` / `candles` / tick archives is mechanical.

---

## 6. P6 — Where significant levels and QM enter the approved model

### 6.1 Spec clauses

- *"V3 Bounce executes valid structural reversals near pre-established significant levels."*
- *"Structural levels and QM supply information about upcoming obstacles and destinations, not unvalidated new entry vetoes."*
- *"Existing QM REJECT / ACCEPT / BREAK_AWAY / OSCILLATING observations inform the existing trade manager as positions approach significant levels."*

### 6.2 Production surfaces where these quantities are already consumed

| Surface | File:line | What it reads | What it does |
|---|---|---|---|
| **`core.Engine` entry** | `core.py:619` | `levels_fn=view_levels` → list of `Level` | Checks "price at a level within `level_window_pips=5.0`" before arming entries. |
| **`core.Engine` QM gate** | `core.py:979` | `qm_fn(level, side) → CONTINUATION / REVERSAL / None` | Journals the QM verdict against the active level; influences Setup A / SQ / TR decisioning. |
| **`qm_decision_shadow`** | shadow module | Running state of QM decision candidates | Supplies `qm_verdict` the engine consumes. |
| **`qm_continuation_veto.py`** | untracked prod file | observer_v6 cache | Flag-gated veto of `RATCHET_EXHAUSTION` closes — a trade-manager seam (default OFF). |
| **`level_interaction_observer_v6`** | prod | Live writer of `logs/level_interaction_observer_v6.jsonl` | Observation only; no entry/exit effect today. |

### 6.3 Surfaces where the spec implies they SHOULD enter

- **Trend V3 / EMA Pullback entries**: no current consumption of `view_levels` or QM. The spec is informational-only ("obstacles and destinations"), not an entry gate. Operator rule: "not unvalidated new entry vetoes."
- **`trade_manager.py` exits**: current exits (RATCHET_STOP, RATCHET_EXHAUSTION, RATCHET_FLAT_2040, NY_CLOSE, etc.) do NOT consult QM. The `qm_continuation_veto` seam exists as a narrow draft but is OFF. The spec permits QM to inform exits once isolated and evidenced.

### 6.4 What the rejected eval tested in this regard

**Nothing.** The eval used V3Engine, which does not consume `view_levels` or `qm_verdict`. The levels/QM clauses of the spec were therefore not exercised by the rejected report.

### 6.5 What a faithful eval must do

- **For `core.Engine`**: materialise a historical `view_builder` output per trading day, and a historical `qm_decision_shadow` state per bar. Feed both into `core.Engine` via `levels_fn` / `qm_fn`. The engine then arms / fires / exits with full level + QM awareness.
- **For `V3Engine`** (if the spec's intent is level-aware V3): either (a) WRAP V3Engine's `TRIGGER` events with a post-filter that discards non-level triggers (operator rule check: this may count as a "new entry gate"), or (b) run `V3Engine` AS-IS and accept the result is V3Engine, not "V3 Bounce near significant levels".
- **For trade-manager QM-informed exits**: this is scoped by the `qm_continuation_veto` draft (file + report `reports-public/qm_continuation_veto_ratchet_exhaustion_20260923.md`) — but applies to `tiered_ratchet`, which is a Trend V3 exit path, not a V3 Bounce path.

### 6.6 Historical availability

- `view_builder` cache (`cache/view/<date>.json`) — needs to exist for every day in the eval window; typically written daily by `view_builder` at 06:30 UTC. **Live cache window on host 161: not surveyed in this report.** A faithful backtest requires a chronological reconstruction of these files (via `view_builder.build_from_history` if available, else from the raw inputs).
- `qm_decision_shadow` state — a running shadow process that evolves per bar. For historical replay, needs to be reconstructed by stepping qm_decision_shadow through the archive. Prior report `reports-public/qm_successor_investigation_20260923.md` documents the primitives.

---

## 7. P7 — Combined V3 Bounce + Trend V3 + EMA Pullback replay design

### 7.1 What the spec requires

- Combined portfolio replay of **all enabled strategies** on the same corpus.
- Spread, SL, TP, trade-manager semantics faithful to production.
- Position cap / portfolio interference modelled.
- Dev vs untouched validation split.
- Levels + QM injected per §6.

### 7.2 Required components for a faithful combined replay

| Component | Status | Notes |
|---|---|---|
| Candle archive (5m) with Stage 0b verdict | **MISSING verdict** | §5 blocker. |
| Tick archive (`/mnt/volume_lon1_1778405456698/ticks/GBPUSD_ticks_*.csv`) | Present (2024, 2025, 2026) | Required for mid-bar stop/trigger fills. |
| `view_builder` historical cache | NOT reconstructed | Required for `core.Engine.levels_fn`. |
| `qm_decision_shadow` historical state | NOT reconstructed | Required for `core.Engine.qm_fn`. |
| `session_trend` state reconstruction | NOT reconstructed | Required for NMS gating decisions in Trend V3 / EMA Pullback (and the V3Engine NMS gate flag). |
| `htf_regime.classify` historical state | NOT reconstructed | Required for Trend V3 ribbon-gate and `core.Engine` HTF direction gate (`BOUNCE_HTF_DIRECTION_ENABLED=1`). |
| Enriched df_5m indicator pipeline | NOT reconstructed | Required for Trend V3 / EMA Pullback / core.Engine Setup C. Production pipeline is `strategy_logic._enrich_frame` + `indicators.*`. |
| Trade manager state machine replay | NOT replayed | Required for exit mechanics parity (RATCHET_*, BE moves, scale-outs, time flattens). |
| Position cap / portfolio arbitration | NOT replayed | ONE_STRATEGY cap, V3_ALLOW_OPPOSING_POSITIONS, BOUNCE admit gates in `central_execution_gate` all need historical reconstruction. |

### 7.3 Deliberately out-of-scope for the next build (per operator rules)

- **No new entry condition** inside any engine. Any "level-aware filter" added as a wrapper is at risk of being a "new entry gate" (spec forbidden) unless the operator confirms it is a *filter on existing triggers* only.
- **No new exit code** anywhere; QM-informed exits only within the `qm_continuation_veto` seam (flag-gated, default off).

### 7.4 Minimum spec for the replay harness

A faithful combined-replay harness must:

1. For each UTC day in `[from_date, to_date]`:
   1. Reconstruct `view_builder` output for the day (open-structure levels + news context).
   2. Reconstruct `htf_regime.classify` and `session_trend.session_authority` as the day begins and update per bar.
2. For each 5m bar close:
   1. Build enriched df_5m (ADX, MACD, ATR, BB, EMA cluster) from the strict `<= bar_ts` archive.
   2. Advance `qm_decision_shadow` by one bar.
   3. Dispatch the bar to each enabled engine in strict order:
      - `core.Engine.on_bar_close(bar)` — with current `view_levels` + `qm_verdict`.
      - `V3Engine.on_bar_close(bar)` — self-contained.
      - `gbpusd_trend_v3.strategy.evaluate(symbol, epic, ts, bars, closes_ind, df_5m, has_open_*)` — with current `htf_regime` + `session_trend` state.
      - `gbpusd_ema_pullback.strategy.evaluate(...)` — similar.
   4. Collect decision outputs → check against the arbitration layer (central_execution_gate: ONE_STRATEGY admit, position caps, news-release windows).
   5. For every open position: advance the trade manager (`trade_manager.monitor_positions` or an equivalent per-mode replay); respect SL / TP / scale / BE / trail / time-flatten rules.
3. During tick dispatch (fine-grained stop/trigger fills):
   1. For each tick in the window matching the open position's instrument, advance each engine's `on_tick` entry point.
4. Record each trade: entry_ts, entry_price, side, mode, SL, TP, intermediate scales, exit_ts, exit_price, exit_reason.
5. Report per-partition (DEV / HOLDOUT / OOS):
   - Opportunities (per the ORIGINAL London/NY bounce ledger — distinguish from the 11,951 census per spec).
   - Captured ≥30 p reversals: counts and net pips.
   - Trend-day performance (Trend V3 + EMA Pullback net).
   - QM-informed vs baseline exits (counterfactual).
   - Realised net / win rate / PF / max DD / exit-reason breakdown.
   - Missed / rejected entries with reason.

### 7.5 What the next build must NOT do

- Run V3Engine alone and report its P&L as "V3 Bounce". That is the rejected pattern.
- Substitute the Phase 4A 11,951 BB-reversal census for the "original ~30-35 p twice-daily session bounces" without labelling.
- Mint synthetic stop-slip or spread numbers without record of the Stage 0b verdict (or an explicit UNVERIFIED CLOCKS label if the verdict is still absent).
- Modify any production file, `.env`, service, or deploy.

---

## 8. Reconciliation summary — what was tested vs what should have been tested

| Spec requirement | Rejected eval did | Faithful eval should do |
|---|---|---|
| "V3 Bounce executes near pre-established significant levels" | Ran V3Engine (no level consumption). | Run `core.Engine` with `levels_fn=view_levels` historically reconstructed, or wrap V3Engine with a level filter (operator ruling needed on the wrapper classification). |
| TP 30 / SL 12 baseline | Used V3Engine's SL=12, no TP (swing trail). | Clarify: adopt `core.Engine` June mode (SL 20 / scale +10 / TP 30), OR change `V3Config.initial_stop_pips` and add a TP mechanism to V3Engine (production parameter change — not permitted in this build). |
| Candle timestamps vs Stage 0b | Carried the evaluator's own UNVERIFIED CLOCKS caveat. | Apply the Stage 0b manifest (when reachable) and re-label every store accordingly. |
| QM informs trade manager | Not exercised (wrapper existed but not wired to any evaluated trades). | For each open position in the combined replay, call `qm_continuation_veto.should_veto_exhaustion` (or the offline-reconstructed equivalent) at every `tiered_ratchet` exhaustion decision and record counterfactual P&L. |
| Combined V3 + Trend V3 + EMA PB replay | Ran V3Engine only. | §7.4 — full historical state reconstruction, every engine dispatched per bar, every open position managed via the trade-manager model, arbitration honoured. |
| Dev vs validation split | Dev 2024-01 → 2025-06 (bid), OOS 2026-01 → 2026-10-09 (mid), per the production evaluator's partitions. | **Same partitions** — the production evaluator is correct on this axis. Add the Holdout partition (2025-07 → 2025-12, currently NOT RUN). |

---

## 9. Changes required to make the evaluator faithful

Ordered by prerequisite dependency:

1. **Operator ruling on "V3 Bounce" semantics**: does the spec's "V3 Bounce" mean (a) `core.Engine` with its existing level/QM consumption, (b) `V3Engine` wrapped with an external level filter, or (c) both engines evaluated independently and reported separately? This determines everything downstream.
2. **Operator ruling on the TP 30 / SL 12 baseline**: adopt production June mode as-is (SL 20 / TP 30), adopt the spec's numbers via a parameter change (would require .env or code change — currently forbidden), or report BOTH?
3. **Produce / publish the Stage 0b correction manifest** so timestamp verification can be applied. If not reachable on 161, provide the path or branch.
4. **Reconstruct `view_builder` historical cache** (`cache/view/<date>.json` for each UTC day in the eval window). Required for `core.Engine.levels_fn`.
5. **Reconstruct `qm_decision_shadow` historical state** (per-bar advance). Required for `core.Engine.qm_fn` and for QM-informed exit counterfactuals.
6. **Reconstruct `session_trend` + `htf_regime` historical states** per bar. Required for Trend V3 / EMA Pullback and for `core.Engine` HTF direction gate.
7. **Build the combined dispatcher** per §7.4. Each engine dispatched per bar; central_execution_gate arbitration honoured; trade manager replayed; portfolio capacity modelled.
8. **Add tick-driven stop/trigger fill resolution** against the tick archive to replace the eval's 2-tick-per-bar approximation.
9. **Operator ruling on spread / slip assumptions**: continue the eval's 0.9 / 0.5 fixed numbers, or sample them from the tick archive's quoted spread?

Steps 3-7 are substantial — on the order of 1,500-3,000 lines of harness code — and each lands as its own flag-gated, isolated module per the spec's "do not modify production" rule.

---

## 10. Scope compliance (verified)

- `/opt/tradingbot/` live tree unchanged. All reads via `grep` / `cat` on existing files.
- No evaluation run. No new backtest.
- No `.env` modified. No service restarted. No live trade. No PAA activation. No deploy.
- All source references above are file:line in the production tree HEAD at the time of this reconciliation.

---

## 11. Stop

This reconciliation does not request any evaluation. It identifies the gap between what the rejected report measured and what the spec requires. The next build will not run until the operator rulings in §9.1-9.2 and (where available) the Stage 0b manifest from §5.3 are provided.
