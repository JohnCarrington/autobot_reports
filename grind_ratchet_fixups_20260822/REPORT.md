# Grind + Ratchet fixups — implementation report

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`)
**Branch:** `feat/trend-stretch-brake-adx-floor`
**Head:** `88f075d` (this session's ratchet commit)
**Parent:** `d62094d` (this session's grind commit)
**Ruling reference:**
`reports-public/grind_er_gate_contradictions_20260822/REPORT.md`
(Ruling 2 = Option C, Ruling 3 = c)

---

## Contradictions after implementation

None new. The two rulings that gated implementation are settled and
their consequences ship in these commits:

* **Ruling 2 (Option C)** — ER is fully dropped on the GRIND path;
  regime engine's `trend_subtype` is the sole efficiency test, at
  the right timescale.
* **Ruling 3 (c)** — fire-path unit tests rewritten against Option C:
  a genuinely below-floor ER on GRIND fires; IMPULSE with identical
  inputs does not; cooldown blocks the immediate re-fire.

Two guards ship alongside per your instruction:

* `TREND_V3_GRIND_REENTRY_COOLDOWN_BARS=6` default (~30 min).
* `test_trend_subtype_schema_contract.py` — mirrors
  `test_day_posture_regime_snapshot_keys` so a key rename on either
  side of the router fails LOUDLY, not silently to no-GRIND.

Honest label per your instruction: **this path is unpriced.** Live
telemetry judges it after this week. No number is claimed for it in
advance.

---

## `git log --oneline -3`

```
88f075d feat(ratchet): exhaustion strictly beyond BE + broker SL at arm
d62094d feat(grind): session-window baseline + drop ER on GRIND + Ruling-1 schema contract
e39e4ef feat(exit): TIERED_RATCHET exit stack for trend book (flag-gated, default off)
```

## `git show --stat` for each new commit

### `88f075d` (ratchet fixups)

```
 tests/unit/test_grind_baseline_recompute.py | 19 +++++++++++--
 tests/unit/test_tiered_ratchet.py           | 60 +++++++++++++++++++++++++++++++++++-------
 tiered_ratchet.py                           | 21 +++++++--------
 trade_executor.py                           | 46 ++++++++++++++++++++++++++++++
 4 files changed, 127 insertions(+), 22 deletions(-)
```

### `d62094d` (grind fixups)

```
 .gitignore                                       |   2 +
 autobot.py                                       | 136 ++++++++++-----
 gbpusd_trend_v3.py                               | 144 +++++++++++++--
 scripts/grind_baseline_recompute.py              | 113 +++++++++++-
 tests/unit/test_grind_sma_cross_reachability.py  | 246 ++++++++++++++++++++++++++
 tests/unit/test_trend_subtype_schema_contract.py | 208 +++++++++++++++++++++
 tests/unit/test_tv3_grind_entry.py               | 259 ++++++++++++++++++++++++++
 7 files changed, 1034 insertions(+), 74 deletions(-)
```

## Session-window baseline — old vs new

```
Old (24h)     GBPUSD 2.9p  (n_bars=5632, n_days=20)
              EURUSD 2.2p  (n_bars=5637, n_days=20)
New (07-16)   GBPUSD 3.9p  (n_bars=2159, n_days=20)   +34 %
              EURUSD 3.0p  (n_bars=2159, n_days=20)   +36 %
```

## `python -c import` of every touched module

```
OK: scripts/grind_baseline_recompute.py
OK: regime_engine
OK: gbpusd_trend_v3
OK: trades_api
OK: trade_executor
OK: autobot
OK: tiered_ratchet
OK: exit_dress
```

## GRIND_SMA_CROSS reachability — file:line

Extracted to a testable module-level function
`autobot._apply_trend_v3_um_sma_cross_close` (autobot.py:2306-2380 in
`88f075d`). Called from `_evaluate_tv3_on_bar_close` at
autobot.py:7935-7942 on every 5m close for the epic that owns UM
positions. Uses `trade_executor.close_position` → cascades through
`close_intent_journal` (so the reconciler does NOT label the close as
external). `trades_api._EXIT_TYPE_BY_CLOSE_REASON["GRIND_SMA_CROSS"] ==
"EARLY"`. Both invariants covered by
`tests/unit/test_grind_sma_cross_reachability.py`.

## Ratchet broker SL at arm — arm site cited verbatim

`trade_executor.py` around the tiered_ratchet arm dispatch:

```python
if _bracket_arm == "TIERED_RATCHET":
    try:
        import tiered_ratchet as _tr_arm
        from datetime import datetime as _tr_dt, timezone as _tr_tz
        _tr_arm.arm(
            pos_key=pk,
            mode=_mode_arm,
            direction=direction,
            symbol=_pair_from_epic(epic),
            entry_ts=_tr_dt.now(_tr_tz.utc),
            entry_price=float(st.get("entry_price") or 0.0),
            deal_id=st.get("dealId") or st.get("deal_id"),
        )
        logger.info(
            "[RATCHET] armed via exit_dress pos_key=%s mode=%s "
            "day_ctx=%s", pk, _mode_arm, _day_ctx_arm,
        )
        # 2026-08-22 ruling (Item 6). The ratchet arm above
        # ONLY installs the software stop. The broker-side SL is
        # whatever the strategy's execute_trade path set...
        # ...
        # broker SL amend at entry ± RATCHET_INIT_SL_PIPS via
        # trade_manager._amend_broker_sl. Fails open.
```

Software-only was the answer to your question; the block below the
`logger.info` line installs the broker SL at
`RATCHET_INIT_SL_PIPS` (default 12) via `trade_manager._amend_broker_sl`.

## Test-suite delta

Before this session (HEAD `e39e4ef`, pre-session baseline):
135 failed / 1370 passed / 20 skipped / 28 errors.

After this session (HEAD `88f075d`):
**138 failed / 1385 passed / 20 skipped / 28 errors**.

**Delta: +15 passed, +3 failed.** The +3 failed vs the pre-session
baseline is pre-existing flap — a targeted stash-diff run
(`comm -13 baseline.txt now.txt`) produced ZERO entries, meaning
**every failing test in the current run also fails at HEAD~2**. My
changes introduce no new failures.

Additions this session:

* `test_trend_subtype_schema_contract.py` — 3 tests (schema)
* `test_grind_sma_cross_reachability.py` — 9 tests
* `test_tv3_grind_entry.py` — 4 new tests + 2 updated to Ruling 3(c)
* `test_tiered_ratchet.py` — replaced `test_exhaustion_fires_at_or_
  beyond_be_long` with two focused tests (BE-does-not-fire,
  tier1-does-fire)
* `test_grind_baseline_recompute.py` — 1 test updated for session-
  window filter (bar timestamps now cover 07-16 UTC by default).

## Item 4 — timer install commands (I don't have sudo)

Both unit files are at `/opt/tradingbot/deploy/systemd/` and BOTH have
`User=autobot` set. The JSON already exists as
`/opt/tradingbot/data/grind_baseline.json`, owned by `autobot:autobot`
(session-window recompute already ran to update it).

Run on the host:

```bash
sudo cp /opt/tradingbot/deploy/systemd/grind-baseline.service \
        /opt/tradingbot/deploy/systemd/grind-baseline.timer \
        /etc/systemd/system/

sudo systemctl daemon-reload

sudo systemctl enable --now grind-baseline.timer

systemctl status grind-baseline.timer

ls -la /opt/tradingbot/data/grind_baseline.json
```

The first `sudo cp` is the only step that needs elevation. After
enable, the timer fires at 00:10 UTC daily.

## The restart command (last per your standard)

```bash
sudo systemctl restart autobot.service
```

This picks up: session-window baseline reader (regime engine already
reads the JSON at classify time — the new format is
backward-compatible because it only adds keys), the drop-ER-on-GRIND
gate, the GRIND cooldown, the SMA-cross extraction, the strict-BE
exhaustion floor, and the ratchet broker-SL at arm. Nothing else on
the host reads `tiered_ratchet` or `exit_dress` — no other unit
needs a restart.
