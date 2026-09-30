# Unresolved settings — `c60ea96` recovery package

These `.env` keys **cannot** be reliably reconstructed from evidence available in the tracked source tree, the tracked env-layer docs, operator memory, or the surviving signal_log. Each entry is listed with the closest evidence that exists and the recommended fallback.

Format:
- **key** — closest evidence — fallback recommendation

## Credential slots (14 keys, all REPLACE_ME in env.reconstructed.example)

`IG_USERNAME`, `IG_PASSWORD`, `IG_API_KEY`, `IG_ACCOUNT_ID`, `TELEGRAM_CHAT_ID`, `TELEGRAM_TOKEN`, `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `SENDGRID_API_KEY`, `EMAIL_FROM`, `EMAIL_TO`, `HEARTBEAT_PING_URL`, `DASHBOARD_PASSWORD`, `DASHBOARD_SECRET_KEY`

Fallback: inject on destination host from key vault. Never commit filled values.

## Strategy sub-thresholds — code-default fallthrough

The strategy modules at `c60ea96` read dozens of tuning knobs via `os.getenv("X", "default")`. Where `.env.bak` (falsified as runtime record) and `env/40-gates.env` (unloaded) are silent, the effective value at runtime **was** the code default — but we cannot confirm the operator didn't override any of them in the actual `.env`. Non-exhaustive:

- `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED` — .env.bak (Jul 1) sets `false`; memory `[BB_BOUNCE gates deliberately disabled]` confirms "since 2026-05-28"; presume `false` at c60ea96.
- `BB_BOUNCE_CASCADE_GATE_ENABLED` — same, presume `0`.
- `BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS` — env/40-gates.env at c60ea96 comment: "default 8.0"; UNKNOWN whether operator overrode.
- `BB_BOUNCE_RUNNER_TRAIL_ACTIVATE_PIPS`, `BB_BOUNCE_RUNNER_TRAIL_OFFSET_PIPS` — .env.bak values were 12/6; used as INFERRED.
- `TREND_V3_MAX_SL_PIPS` — landed as 12p hard cap on Jul 15 (`96da119`). At c60ea96 (Jul 29), the code cap is 12p; whether env-override was in place: UNKNOWN.
- `REGIME_MAX_HOLD_MINUTES` — landed with `d54080d` (Jul 27); default not extracted; UNKNOWN.
- `RUNNER_MOMENTUM_CHECK_MODE` — set to `shadow` in env/40-gates.env at c60ea96; UNKNOWN whether operator also placed in `.env`.
- `HTF_AUTH_ADX_TREND_FLOOR` — .env.bak sets 25.0; UNKNOWN at c60ea96.

## Strategy enable flags with ambiguous evidence

- `BRIEFING_EXECUTION_ENABLED` — `.env.bak` (Jul 1) sets `0`; signal_log shows 13 fires Jul 23–31. Either the flag was `1` in the actual `.env` by Jul 23, or the fires came from a different host (memory `[Phase 1 dispatch-owner flags]` references "the FXi/144 box" as briefing-execution host). Package `env.reconstructed.example` uses `1` per fire evidence, but cross-host attribution is not confirmed.
- `BRIEFING_V5_ENABLED` — signal_log shows 2 fires Jul 29 + Jul 31. Code path exists; env override UNKNOWN.
- `NEWS_STRATEGY_MODE` — env/40-gates.env at c60ea96 documents `off`. Commit `eb5c7bd` (Aug 3) documents a shadow-flip "executed 2026-07-27" — implying the doc-value at c60ea96 ought to have been `shadow`. Whether `.env` was flipped is UNKNOWN. NEWS_STRATEGY_CONT + NEWS_STRATEGY_REVERSAL fires (3 in total, Jul 2 + Jul 22) suggest the strategy could emit even under `off` for certain sub-paths, OR mode was `shadow`/`enforce` at fire time. **Ambiguous.**
- `NEWS_STRATEGY_HIGH_IMPACT_ARM_ENABLED` — .env.bak sets `0`; no HIGH-arm fires observed; presume `0` at c60ea96 but not verified.

## Layered-env keys not present in `.env`

The following keys exist in `env/40-gates.env` at c60ea96 but that file **is not loaded** (per its own header). If the operator did not manually copy each of these into `.env`, the runtime value was `os.getenv` default:

- `SB_ENTRY_PATH_MODE=prefer_retest` (code default: `current`) — signal_log doesn't distinguish; UNKNOWN which value was live
- `NEWS_MOMENTUM_MODE=observe` (only mode implemented) — no `.env` sync needed for behaviour
- `NEWS_MIN_IMPACT=HIGH`, `NEWS_DECISION_CANDLES=3`, `NEWS_SPIKE_MIN_PIPS=25`, `NEWS_FADE_BODY_PCT=0.50`, `NEWS_SL_PIPS=20`, `NEWS_TP_PIPS=60` — release-anchored evaluator params; only relevant if `NEWS_STRATEGY_MODE` reached `shadow`/`enforce`
- `NEWS_CONTINUATION_ENABLED=0`
- `REGIME_MAX_HOLD_ENABLED=1`, `RUNNER_MOMENTUM_CHECK_MODE=shadow`

## Runtime overrides not tracked anywhere

- Position sizes at each fire time — the trades in signal_log carry `pnl_pips` and `total_pnl_pips` but not the operator's per-trade stake schedule. From the `briefing_actual_pnl_20260930` report, trade_size stepped from 1.0 (early July) to 2.0 (from 2026-07-28 onward). Whether this change was env-driven or code-driven: UNKNOWN.
- Anti-hedge / portfolio-limit runtime state — landed `a59b4da` on Jul 21; state at c60ea96 UNKNOWN.
- Any `.env` key set by a manual `export KEY=value` in the operator's shell before `systemctl start autobot` — would appear in process environ but never in `.env`. UNKNOWN.

## Bootstrap / restart timing

- systemd journal for July: UNAVAILABLE (rotated).
- Whether the bot restarted between the commit of `c60ea96` and any specific fire: UNKNOWN.
- Whether the bot process (PID 2654603 per c60ea96 message) was still alive on Jul 31: UNKNOWN.

## Guidance for the destination

- Fill the 14 credential slots.
- For every setting labelled `[UNKNOWN]` or listed above, decide whether to leave to code default or override — and record the decision. Do not silently drop.
- Run the destination in DEMO for a research window before considering LIVE.
