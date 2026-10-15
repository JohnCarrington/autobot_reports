# QM-informed trade management — inventory + wiring proposal

Spec reference: issue #1, §QM-informed management:
> "Objective: allow profitable moves to continue THROUGH levels when
> acceptance/breakaway is established; respond appropriately to adverse
> rejection rather than automatically taking 10 pips at first obstacle.
> **Do not equate QM terminal with immediate exit**; determine causality,
> timing and trade-manager wiring before choosing and testing any new
> exit behaviour.
> QM currently observes; any proposed management wiring must be isolated
> and explicitly evidenced."

Per that ruling, **this document inventories only**. No code is wired.

## 1. QM observer → trade manager — current state

- QM state machine: `qm_level_interactions.py` (unchanged since commit `3239beb` 2026-08-25).
- Observer wrapper: `level_interaction_observer_v6.py` — reuses the state machine verbatim, writes `logs/level_interaction_observer_v6.jsonl`.
- `qm_continuation_veto.py` (UNTRACKED in /opt/tradingbot) demonstrates one narrow seam: VETO `RATCHET_EXHAUSTION` closes when a fresh active-level observation has `final_state ∈ {ACCEPT, BREAK_AWAY}` with `continuation_demonstrated=True`. Flag `RATCHET_EXHAUSTION_VETO_QM_ENABLED` defaults OFF; the file is untracked, not committed.
- Prior investigation: `reports-public/qm_continuation_veto_ratchet_exhaustion_20260923.md` demonstrated +41.4 p vs the live ratchet's +28.1 p on the 2026-09-23 08:20 GBPUSD short, using exactly this seam.

## 2. Candidate wiring points (not yet implemented)

| Seam | File:line (prod) | Current behaviour | Proposed QM-informed behaviour |
|---|---|---|---|
| RATCHET_EXHAUSTION close | `tiered_ratchet.py:626-706` | If `exhausted`: close at market, reason RATCHET_EXHAUSTION. | On `exhausted`: query observer_v6 cache; if a fresh `ACCEPT/BREAK_AWAY + continuation_demonstrated` exists for ANY active-level observation and NO fresh `REJECT`, VETO the close (preserve `no_new_extreme_bars` at threshold so next bar re-triggers). Already drafted untracked in `qm_continuation_veto.py`. Flag `RATCHET_EXHAUSTION_VETO_QM_ENABLED` default OFF. |
| Trade manager scale-out at midline | `trade_manager.py` MIDLINE_* events | Fixed scale/exit. | QM REJECT at the midline → confirm scale-out. QM ACCEPT past midline → defer scale-out; let the move continue. QM OSCILLATING → scale-out as current. |
| BRIEFING_TP ladder TP2/TP3 | `trade_manager.py:5600-5700` | TP ladder with fixed pullback trail. | QM BREAK_AWAY after TP1 → promote remainder to runner (not currently supported for briefing-TP). QM REJECT at TP2 → bank remainder immediately. |
| Opposite-band exit (RANGE trades) | `trade_manager.py` opposite-band events | Full exit on touch. | QM at opposite band: ACCEPT → convert to runner (promote to trend management). REJECT → full exit (current). OSCILLATING → bank partial. |

## 3. Evidence requirements (before any wiring is enabled)

Per the operator rule "QM currently observes; any proposed management wiring must be isolated and explicitly evidenced", each candidate seam needs:

1. **Causal replay demonstration** on ≥ 30 historical cases where the proposed behaviour would have changed the outcome. Target metric: average pips captured vs the current behaviour, with per-case ledger (bar_ts, QM state, decision, counterfactual, realised vs would-be P&L).
2. **Monotonic improvement**: in no replay case should the proposed behaviour lose MORE than the current.
3. **Flag-gated introduction**: a dedicated env flag (e.g. `MIDLINE_QM_INFORMED_SCALE_ENABLED`, default OFF) for each seam. Behaviour under flag OFF must be byte-identical to today.
4. **Operator ruling**: explicit sign-off per seam. The RATCHET_EXHAUSTION seam already has a draft (untracked `qm_continuation_veto.py` + `reports-public/qm_continuation_veto_ratchet_exhaustion_20260923.md`).

## 4. What this build DOES contribute

- The Opening Map (`autobot_v3_build/opening_map.py`) already surfaces the levels, clusters, and HTF/NMS context that would make the QM observations more actionable in management.
- Historical replay (`autobot_v3_build/historical_replay.py`) can be extended per-seam when a specific wiring is approved — the infrastructure (level map, event ledger, candle archive) is already in place.

## 5. What this build EXPLICITLY DOES NOT DO

- Does not modify `trade_manager.py`, `tiered_ratchet.py`, or any other exit-management file.
- Does not read QM observer_v6 cache from trade_manager hot paths.
- Does not implement `qm_continuation_veto.should_veto_exhaustion` as a tiered_ratchet consumer (the untracked file remains untracked).
- Does not propose a specific exit action beyond the inventory above.

A follow-up build (operator-approved) can take any single row from §2 and ship it under its own flag with its own causal-replay evidence.
