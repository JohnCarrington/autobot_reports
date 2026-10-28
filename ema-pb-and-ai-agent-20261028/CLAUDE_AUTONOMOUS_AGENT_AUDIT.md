# Claude Autonomous Trading Agent Audit — 2026-10-28

**Service:** `/home/autobot/ai_trading_agent/` + systemd `ai-trading-agent.service` (`.timer` fires Mon–Fri 06:45 Europe/London). Current build runs `claude-sonnet-4-6` at ~16 s mean decision latency.

**Window audited:** first decision 2026-10-24T16:58:03 UTC → last decision 2026-10-28T17:56:06 UTC (approx 4 live trading days).

**Access level:** READ-ONLY. The audit queries SQLite journals (`data_cache/journal.db` 19 MB, `data_cache/broker.db` 24 KB) and copies the agent's own daily report JSONs/MDs. **No agent config changes, no restarts, no prompt edits, no broker calls.**

**Raw evidence:** `data/all_decisions.csv` (506 rows), `data/all_trades.csv` (3 rows), `data/rejection_breakdown.csv` (1 row), `data/ai_agent_summary.json` (aggregates).

---

## 1. Headline

- **506 Claude decisions**, **416 submitted to execution** (415 accepted + 1 rejected), **90 schema-validation failures** (not Claude's fault — see §5).
- **3 completed paper trades.** All losses. Total **−29.1 pips / −£29.10.** PF 0. Max DD 29.1 p.
- **Zero NMS vetoes.** The directional gate (`risk/nms_gate.py` + `execution/controller.py:99-133`) ran on every execution and never blocked a Claude trade in the audit window — because the AI did not propose a direction that NMS would have rejected.
- **API spend $13.19 USD** over 506 decisions (2.80 M input + 320 K output tokens). ≈ $0.026 per decision, $4.39 per completed trade, 16.2 s mean decision latency.
- **373 of 506 (73.7%) decisions were WAIT.** The AI is NOT trigger-happy.

## 2. Is the AI genuinely autonomous?

**Decision axes** (recovered from the schema at `ai_trading_agent/ai/schema.py` + the gate logic at `execution/controller.py`):

| axis | Claude's freedom | hard constraint |
|---|---|---|
| **Direction** | Free initial choice | NMS V3 directional veto applied **post-decision** (SELL blocked into STRONG_UP / EMERGING_UP; BUY blocked into STRONG_DOWN / EMERGING_DOWN). Fail-closed on stale/missing snapshot. **Zero vetoes observed in window.** |
| **Setup type** | Free (MARKET / STOP / LIMIT) | — |
| **Entry price** | Free | Must pass unit-magnitude sanity check (fractional ~0.5–5.0 or `ig_pip_units` ~5000–50000) to prevent 10,000× misconversions. |
| **Invalidation level** | Free | Validated on the losing side of entry: BUY requires `inval ≤ entry`; SELL requires `inval ≥ entry`. **(The sole observed rejection was `buy_limit_not_below_market` — Claude placed a BUY LIMIT at 13329.65 when market was already at ~13330.)** |
| **Stop distance** | Chosen implicitly by invalidation | Broker minimum stop: 12 pips. If Claude's invalidation implies a tighter stop, the broker stop widens to the 12-pip floor. Stop can only tighten or breakeven, never widen (`paper.py:144-161`). |
| **Take-profit distance** | **No freedom** — fixed at 100 pips (`config/default.yaml: broker.broker_take_profit_pips`) regardless of Claude's `profit_objective`. |
| **Hold duration** | Free via `profit_objective.dynamic=true` (reassess on structural change) or `dynamic=false` (fixed objective price). WAIT fully supported. |
| **Position management** | Free: HOLD / CLOSE / PARTIAL_CLOSE / MODIFY_PROTECTION (tighten / breakeven / trail). |
| **Position size** | Hint via `position_size_hint.gbp_per_pip`; clamped at 2.0 (config). Default 1.0. |

Deterministic **post-decision** envelope (`risk/envelope.py` — can veto Claude after Claude has decided):

- market_closed (calendar check), snapshot_stale (>600 s), spread_too_wide (>3.0 p), max_simultaneous_positions (default 1), size_cap (>2.0 £/p), risk_per_trade (stop × size > 30 p), daily_loss (<= −60 p), consecutive_loss (>= 4), **entry_cutoff ≥ 18:00 UK**, API cost cap, broker_min_stop (<12 p), stop-direction validity.

**Verdict:** the AI's control over DIRECTION, SETUP, ENTRY, SL, and POSITION-MANAGEMENT is genuine. Its control over TP is fixed at 100 p and cannot be overridden. NMS **does act as a direction veto** at the execution boundary, but it is informational to the AI (included in the snapshot payload under `snapshot.nms.v3_state`) rather than silent — Claude sees it and sometimes aligns with it, sometimes not, and NMS vetoes if the final decision conflicts. In the audit window Claude's choices did not trigger an NMS veto a single time.

## 3. What has Claude actually traded?

Three completed positions. Numbers from `data/all_trades.csv`; theses in full in that CSV (truncated here).

| # | opened (UTC) | side | entry (IG pts) | exit (IG pts) | pnl (p) | close reason | thesis (compressed) |
|---|---|---|---|---|---|---|---|
| 1 | 2026-10-26T17:20:22 | BUY | 13357.15 | 13345.15 | **−12.0** | **broker_stop** | "Breakout M5 bars at 17:10/17:15 session high. Pullback 0.1 p. Round 13350 cleared. Target S1/prev-day-low 13361–62 cluster." (6929 s hold) |
| 2 | 2026-10-27T09:35:32 | SELL | 13309.45 | 13317.25 | −7.8 | **ai_close** | "Clear intraday downtrend, lower highs on H1. M5 lower highs. Just took out session low 13309.35. Target S2 13293 / 13300." (4491 s hold) |
| 3 | 2026-10-27T12:55:56 | BUY | 13329.35 | 13320.05 | −9.3 | **ai_close** | "~12-pip M5 thrust from ~13318. Cleared prev-day-low 13328, converting to support. Target pivot P 13353 / round 13350." (2065 s hold) |

**All three are losses. Two of three were discretionary loss-cuts** — Claude actively closed the position when the thesis invalidated, rather than parking on the broker stop:

- **Trade 2 (SELL):** closed at −7.8 p (−52% toward its 15.25-p stop) with the explicit rationale "`price has climbed back above M5 EMA slow (~13316.69) and is now pressing against the recent swing high at 13320.05 … halfway to stop … USD high-impact release (Durable Goods) at 12:30 UTC`". That is a lucid trade-management decision: the entry condition (lower-highs structure, just-broken session low) had been structurally reclaimed, so the thesis no longer held.
- **Trade 3 (BUY):** closed at −9.3 p (−72% toward its 13-p stop) with the rationale "`H1 EMA fan is firmly bearish … M5 close below EMA slow … broken below prev_day_low (13328) which was a key support`". Same shape — explicit thesis invalidation.
- **Trade 1 (BUY):** rode to the broker stop. The exit sequence here is less telling because the broker stop is a hard rule, not a decision.

**Sample size caveat:** 3 trades is far too few to say anything about expectancy, win rate, PF, or edge. What the sample DOES establish is that:

1. Claude does trade (not a WAIT-only observer).
2. Claude's exits display explicit thesis-invalidation reasoning (not stop-only exits).
3. The three entries were structurally reasoned (prior-day-low breaks, EMA/pivot confluence, swing-based stops).
4. None of them worked out in this window.

## 4. WAIT behaviour

373 of 506 (73.7%) decisions were WAIT. Primary reasons harvested from decision theses (not formally classified by the schema — Claude writes free-text rationale in `primary_thesis`):

- No high-conviction setup (ranging / low-volatility / near a key level).
- Pre-news "wait for release" (Claude is aware of calendar events — the FOMC-adjacent 2026-10-28 FOMC day is in the window; see `incident/scenario-v2-fomc-gate-20261028` branch for related V2 investigation).
- Insufficient momentum / unclear structure.
- Just-closed-a-position cool-down (37 HOLD + CLOSE sequences include "monitor for new setup after this closes").

The AI's willingness to WAIT is a non-trivial feature. By comparison, the mechanical EMA PB service armed and cancelled a setup every ~5 minutes for most of 2026-10-27 (53 arm attempts in 25 h).

## 5. The 90 "NULL action" schema failures (not a trading defect)

90 decisions have `action = NULL` because Claude emitted a `management.proposed_action` as free-text (e.g. "Hold current position. Broker stop at 13345.15 is correctly placed and at minimum distance") instead of selecting from the enum `{close, partial_close, tighten_stop, move_stop_to_breakeven, trail, hold}`. The JSON-schema validator rejects the field.

In every spot-checked case the top-level `action` was `HOLD` and the trade intent was preserved; the validator rejected the ancillary field. This is a **prompt / schema contract issue**, not a Claude decisioning issue. Suggested fixes (operator-only, out of scope for this audit): tighten the system prompt to explicitly list the enum values; or relax the validator to accept the top-level action when the management field is a free-text summary; or use Anthropic tool-use to make the schema binding.

## 6. NMS V3 role

Formally classified against the four categories the user requested:

- **(A) informational**: YES. The NMS v3_state is included in every snapshot sent to Claude (`snapshot.nms.v3_state`). The system prompt (`ai_trading_agent/ai/prompts.py:48-62`) tells Claude explicitly that this is both an input to its reasoning and "a hard directional veto on the system side."
- **(B) influence on reasoning**: YES, insofar as Claude cites NMS state in its theses when supportive (e.g. trade 2's SELL cites "NMS shows EMERGING_DOWN which supports the bearish macro bias"); it does not override NMS when NMS disagrees — in the window Claude did not propose a direction NMS would block, so there was no conflict to resolve.
- **(C) mandatory veto**: YES at the execution boundary (`execution/controller.py:99-133`). Fail-closed on stale/missing snapshot (`nms_gate.py:95-115`, 900 s staleness ceiling).
- **(D) silent block of trades Claude considered valid**: **NO occurrence in window**. Of 416 executions, 415 were accepted and 1 was rejected for `buy_limit_not_below_market` (an invalidation-direction check, unrelated to NMS). No `nms_v3_veto` rejection in the entire 4-day window.

NMS state distribution across 1,966 snapshots during the window: ABSENT 919 (early run, pre-wiring), RANGE 446, EMERGING_DOWN 422, EMERGING_UP 168, NORMAL 11. So EMERGING_DOWN and RANGE were the dominant regimes — Claude's one SELL on 2026-10-27 and two BUYs on 2026-10-26/27 do not sit in NMS states that would have been blocked.

## 7. Costs

| metric | value |
|---|---|
| total API spend | $13.185 USD |
| input tokens | 2,796,404 |
| output tokens | 320,152 |
| decisions | 506 |
| trades | 3 |
| **cost per decision** | **$0.026** |
| **cost per trade** | **$4.39** |
| mean decision latency | 16.23 s |

The `ai-trading-agent.service` is configured with a cost cap via `--max-cost-usd` (observed 5.0 in prior service args; the audit window spent $13.19 cumulatively, so the cap was raised somewhere along the way or multiple sessions reset the counter — the audit does not resolve this, since the reconstruction counts tokens from the journal, not from a running cap). The envelope.py rule `envelope.py:107-108` would reject new BUY/SELL entries once the cumulative spend crosses the cap for the current session.

## 8. What the audit explicitly does NOT do

- Does not change prompts, schema, cost caps, cutoff times, NMS config, or any other agent file.
- Does not resume closed positions, re-run trades, or back-fill missing journal rows.
- Does not evaluate Claude against a "ground truth" of what it should have done — only reports what it did and what the outcome was.
- Does not propose an AI-assisted mechanical variant. (See the comparison report for a bounded discussion of that question.)

## 9. Pointers

- Full decision log: `data/all_decisions.csv` (snapshot NMS state, H1 direction, M5 close, spread, accepted flag per decision).
- Full trade log: `data/all_trades.csv` (entry/exit, SL/TP, open thesis, close thesis for the two ai_close exits).
- Rejections: `data/rejection_breakdown.csv` (just the one `buy_limit_not_below_market`).
- Aggregate stats: `data/ai_agent_summary.json`.
