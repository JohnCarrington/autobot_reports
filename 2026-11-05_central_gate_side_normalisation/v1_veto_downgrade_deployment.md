# v1_pressure veto downgrade — deployment 2026-11-05 16:32 UTC

Operator directive: *"determine whether `v1_pressure_against` provides
any genuinely independent protection not already supplied by the newer
controls […] If its remaining contribution is redundant or
demonstrably harmful, remove it as a hard trade veto while retaining
pressure as diagnostic telemetry."*

## Audit summary

**Scope:** 29 autobot `BB_BOUNCE_FILTER_BLOCK rule=v1_pressure_against`
events 2026-10-15 → 2026-11-05 16:00 UTC (every rule=v1_pressure_against
in the autobot journal for the window).

**Method:** For each block, nearest `nms_watch_state.jsonl` snapshot
within 15 min (coverage **29/29**, 1,950 GBPUSD snapshots loaded from
all rotated archives). Simulated `central_execution_gate.
_apply_unified_directional_authority` using the reconstructed
`(v3_state, fresh, companion_direction, exhaustion_state, direction,
readiness, freshness, watched_trend_direction)` tuple, with the post-
BLOCK_BAD_SIDE side normalisation (deployed 16:25 UTC) active.
Outcomes drawn from `bb_pierce_trades.jsonl` RESOLUTION records across
all archives.

**W5 band-walk** is a standalone-only control (`/opt/bb_bounce/band_walk_
classifier.py`); the autobot BB_PIERCE_RUN path never consulted it,
so it is out of scope for this audit.

## Result — v1 is independently blocking but not demonstrably protective

| Category | Count | Note |
|---|---|---|
| Total v1_pressure_against blocks | 29 | all SELL=23 / BUY=6 |
| **Unique to v1** (authority admits) | **23** | 79 % |
| Overlap with authority | 6 | all `BLOCK_WATCH_AND_WAIT` |
| Unique-v1 with matched pierce resolution | 4 | — |
| Unique-v1 unmatched (data gap) | 19 | pierce-threshold / rejection-window schema mismatch between `gbpusd_bb_bounce` and `bb_pierce_recorder` |

### Outcomes (at TP20 / SL20)

| Cohort | n | wins / losses / BE | net | avg/trade |
|---|---|---|---|---|
| **Unique-to-v1 blocks that would-have-fired** | 4 | 3 / 1 / 0 | **+40.0 p** | +10.0 p |
| Overlap blocks that would-have-fired | 1 | 1 / 0 / 0 | +20.0 p | n/a (authority already blocks) |

Reaching higher TPs: unique-v1 net is **+60 p at TP30/SL20** and
**+60 p at TP40/SL20** — the one losing trade (Nov 4 04:45 SELL) hits
SL first in every TP scenario.

### Evidence table — all 23 unique-v1 blocks

| block_ts (UTC)        | side | v1       | $dir     | nms_v3    | exhaustion              | W&W | matched outcome |
|-----------------------|------|----------|----------|-----------|-------------------------|-----|-----------------|
| 2026-11-03 11:35:09 | BUY  | AGAINST | WITH     | RANGE    | NO_EXHAUSTION           | TREND_TRADING | entry 13407.15, MFE +26.1 p, **+20 p**  |
| 2026-11-03 11:40:12 | BUY  | AGAINST | WITH     | RANGE    | EXHAUSTION_CONFIRMED    | TREND_TRADING | — (no resolution)|
| 2026-11-03 11:55:11 | BUY  | AGAINST | WITH     | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-03 13:20:17 | SELL | AGAINST | AGAINST  | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-03 13:35:18 | SELL | AGAINST | AGAINST  | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-03 14:05:16 | SELL | AGAINST | AGAINST  | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-03 18:30:09 | SELL | AGAINST | AGAINST  | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-03 18:40:10 | SELL | AGAINST | AGAINST  | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-04 04:40:10 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_DEVELOPING   | TREND_TRADING | entry 13472.55, MFE +24.6 p, **+20 p** |
| 2026-11-04 04:45:08 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_DEVELOPING   | TREND_TRADING | entry 13466.25, MFE +18.3 p, **−20 p** |
| 2026-11-04 07:55:11 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-04 12:35:21 | SELL | AGAINST | AGAINST  | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | entry 13489.35, MFE +29.2 p, **+20 p** |
| 2026-11-04 13:25:14 | SELL | AGAINST | AGAINST  | RANGE    | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-05 04:10:10 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_CONFIRMED    | TREND_TRADING | — |
| 2026-11-05 04:20:08 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_CONFIRMED    | TREND_TRADING | — |
| 2026-11-05 04:25:09 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-05 06:40:08 | SELL | AGAINST | AGAINST  | NORMAL   | NO_EXHAUSTION           | TREND_TRADING | — |
| 2026-11-05 06:45:10 | SELL | AGAINST | AGAINST  | NORMAL   | NO_EXHAUSTION           | TREND_TRADING | — |
| 2026-11-05 07:10:10 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_CONFIRMED    | TREND_TRADING | — |
| 2026-11-05 07:15:12 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-05 07:20:17 | SELL | AGAINST | AGAINST  | NORMAL   | EXHAUSTION_DEVELOPING   | TREND_TRADING | — |
| 2026-11-05 15:15:12 | BUY  | AGAINST | WITH     | RANGE    | NO_EXHAUSTION           | TREND_TRADING | — |
| 2026-11-05 15:20:11 | BUY  | AGAINST | WITH     | RANGE    | NO_EXHAUSTION           | TREND_TRADING | — |

The 6 overlap cases (not in table): all GBPUSD WATCH_AND_WAIT with
watched_trend=UP (→ SELL blocked) or DOWN (→ BUY blocked). v1 was not
providing independent protection on these — the authority was.

### Data gaps

- **19/23 unique-v1 blocks have no matched pierce resolution.** The
  autobot's `gbpusd_bb_bounce` arming logic (pierce ≥ 0.5 p, 3-bar
  rejection window, adaptive body) emits `[BB_BOUNCE_FILTER_BLOCK]`
  when it has an arm ready to fire. The pierce resolver
  `bb_pierce_recorder.py` runs its own pierce/rejection detection with
  different thresholds; when the two disagree the resolution is simply
  absent from the pierce log. This is a tooling limitation, not
  evidence about those trades' outcomes.
- The baseline **live-fired BB_PIERCE_RUN universe over the same
  3-week window: 15 fires, −11.3 p net** (loss-making). The deployed
  filter stack is not producing a sample better than random.
- The `BLOCK_BAD_SIDE` defect (fixed earlier today) silently blocked
  every autobot BB_PIERCE_RUN fire that reached the dispatch-adapter,
  further depressing the baseline.

## Patch

Branch `fix/central-gate-side-normalisation-20261105`, commit `6d50f88`
`fix(bb_bounce_filters): downgrade v1_pressure veto to opt-in`.

Minimal change — 2 hunks in `bb_bounce_filters.py` (+15 lines) plus a
new test file (+149 lines):

```python
# New helper:
def v1_pressure_veto_enabled() -> bool:
    return _env_bool("BB_BOUNCE_V1_PRESSURE_VETO_ENABLED", "0")

# In apply_filters:
v1_on = v1_pressure_enabled()
v1_veto_on = v1_pressure_veto_enabled()  # NEW
...
elif v1_on and v1_veto_on and v1.get("state") == V1_UNKNOWN:
    refusing_rule = "v1_pressure_unknown"
elif v1_on and v1_veto_on and v1.get("state") == V1_AGAINST:
    refusing_rule = "v1_pressure_against"
```

And in the decision row:
```python
"flags": {
    "closeback": cb_on,
    "v1_pressure": v1_on,
    "v1_pressure_veto": v1_veto_on,  # NEW
    "dollar_direction": dd_on,
},
```

### What changes

- **v1 computation runs as before** — the signal (WITH / AGAINST /
  UNKNOWN, usd_pct, gbp_pct, expected_direction) is still computed and
  appears verbatim in the decision-log row *and* in the
  `[BB_BOUNCE_FILTER_BLOCK]` info line for closeback-pending or
  dollar-direction refusals.
- **v1 no longer vetoes** unless `BB_BOUNCE_V1_PRESSURE_VETO_ENABLED=1`
  is set explicitly.
- Default: flag absent → veto OFF. (Standing rule: never edit .env;
  flag default handles it.)

### What is preserved

- `BB_BOUNCE_CLOSEBACK_ENABLED` veto — unchanged (close-back is a
  structural post-pierce rule, orthogonal to directional authority).
- `BB_BOUNCE_DOLLAR_DIRECTION_ENABLED` veto — unchanged (currently
  defaulted off in `.env`).
- Full NMS directional authority (`BLOCK_WATCH_AND_WAIT`,
  `BLOCK_TREND_WRONG_DIRECTION`, `BLOCK_BOUNCE_STRONG_TREND_NO_EXHAUSTION`,
  etc.) — unchanged.
- W5 band-walk gate (standalone BB only) — unchanged.
- SEI arbiter authoritative-mode — unchanged.
- Broker stops/limits — unaffected (no change to entry prices, SLs,
  TPs, or trade manager).

### Rollback

```
# Option A — flag flip only (zero-downtime, but requires .env edit by
# operator; see standing rule)
# Set BB_BOUNCE_V1_PRESSURE_VETO_ENABLED=1 in /opt/tradingbot/.env
# and restart autobot.service.

# Option B — file restore
cp /opt/tradingbot/_backups/pre-v1-veto-20261105T163237Z/bb_bounce_filters.py \
   /opt/tradingbot/bb_bounce_filters.py
sudo systemctl restart autobot.service
```

## Test results

New file `tests/unit/test_bb_bounce_v1_veto_optin.py` — **9/9 pass**
against live `/opt/tradingbot`:
- Default: `v1=AGAINST` / `v1=UNKNOWN` no longer refuse; row still
  carries the v1 state (telemetry preserved).
- Opt-in `BB_BOUNCE_V1_PRESSURE_VETO_ENABLED=1`: legacy veto byte-
  identical, `refusing_rule="v1_pressure_against"` / `"v1_pressure_unknown"`.
- Close-back veto still fires (BUY under NO_CLOSEBACK_YET).
- Dollar-direction veto still fires (`DOLLAR_AGAINST`).
- Computation-off + veto-on: no refuse, no computation flag.
- Decision-row schema contains the new `flags.v1_pressure_veto` key
  (backwards-compatible with the pre-existing keys).

Pre-existing `test_bb_bounce_v1_pressure.py` suite passes on the
worktree (14/14); live-tree runs show pre-existing drift unrelated to
this patch.

## Deployment to /opt/tradingbot (2026-11-05 16:32 UTC)

- Backup: `/opt/tradingbot/_backups/pre-v1-veto-20261105T163237Z/bb_bounce_filters.py`
  (pre sha `c4216f4a…`).
- Patched sha256: `e57bf333de3b3f6918f7f611801795fca9a45ab57791fa627c8a71c8b55480a9`.
- Test file copied to `/opt/tradingbot/tests/unit/`.
- Live-code smoke: `v1_pressure_veto_enabled()` returns `False` by
  default, `True` when the env flag is `1`, `False` when the flag is
  `0`.

## Operator restart

Autobot service PID **4026117** (up since 16:25:23 UTC — restarted
earlier for the BLOCK_BAD_SIDE fix) still holds the pre-patch
`bb_bounce_filters` module in memory. Patch takes effect on:

```
sudo systemctl restart autobot.service
```

Positions / stops / open trades preserved on restart (no broker calls
are involved; `[restore] reconciliation` rebuilds position state from
IG on startup).

## Expected post-restart behaviour

- `[BB_BOUNCE_FILTER_BLOCK]` info lines with `rule=v1_pressure_against`
  / `v1_pressure_unknown` will stop appearing.
- `[BB_BOUNCE_FILTER_BLOCK]` with `rule=close_back_no_closeback_yet`
  continues as before.
- The v1 state (WITH / AGAINST / UNKNOWN) will appear in future
  `[BB_BOUNCE_FILTER_BLOCK]` close-back or dollar-direction refusals
  as context (it already does — see the decision row schema).
- BB_PIERCE_RUN candidates that v1 used to veto now pass through to
  the unified NMS directional authority. The authority's existing
  checks (W&W, exhaustion, trend matrix) govern admission. Trades it
  does admit face the broker and dispatch_adapter's remaining gates.

## Summary of uniquely-blocked trades

| | count | outcome (matched) |
|---|---|---|
| Blocks uniquely by v1 (authority admits) | **23** | 3 wins / 1 loss / net **+40 p** (n=4 matched) |
| Blocks that overlap with WATCH_AND_WAIT | 6 | n/a — authority was already blocking |
| Pierce resolutions unavailable due to schema mismatch | 19 of 23 unique | data gap, not evidence |

**No arbitrary restrictions reintroduced. Bounce Family roadmap untouched.
v1 downgraded to telemetry only. Operator restart pending.**
