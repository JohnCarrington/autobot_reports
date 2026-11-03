# Scenario V2 — final-review findings and corrected statistics

**Branch:** `correction/scenario-v2-entry-redesign-20261103`
**Earlier commit:** `4d680ef` (with the misleading pip-tally bug)
**Corrected commit:** this one (fixes the summary + MFE/MAE + removes
dry-run phase + adds mocked integration tests + adds preflight script)

## 1. Reconciliation of Mechanism A backtest (per brief §1)

### 1.1 Why the earlier summary read 16.7 % win rate

The earlier `_print_summary` function in
`backtest_coherent_setups.py` filtered the P&L sample to trades
whose `exit_reason` was `TARGET_HIT` or `STOP_HIT` only. For
Mechanism A on n = 13, that was 6 trades (1 target + 5 stops).

**It silently excluded the 7 EXPIRED trades from the pip tally and
win-rate denominator.** EXPIRED trades carry a real P&L — they exit
at bar 24's close — but were not being counted.

The correction (committed with this review) replaces the summary
with "every closed outcome counts" and uses "profitable at exit"
as the win-rate rule.

### 1.2 Corrected per-trade table (ALL, n = 13)

| Scenario | Dir | Exit | sim_entry | stop_used | sim_exit | gross | net | mfe | mae |
|---|---|---|---|---|---|---|---|---|---|
| `87f92fcab23db555` | SELL | EXPIRED | 13323.05 | 13331.05 | 13309.75 | +13.3 | +12.4 | +15.1 | +0.1 |
| `f5e11547c4ce2097` | BUY | STOP_HIT | 13320.05 | 13312.05 | 13312.05 | −8.0 | −8.9 | +0.4 | +8.0 |
| `9fb58109c4dc34c2` | SELL | STOP_HIT | 13298.85 | 13307.25 | 13307.25 | −8.4 | −9.3 | +1.6 | +8.4 |
| `bd7fbcce36c2c777` | SELL | STOP_HIT | 13323.75 | 13335.15 | 13335.15 | −11.4 | −12.8 | +0.0 | +11.4 |
| `a6dedea761fa78a0` | SELL | STOP_HIT | 13320.85 | 13332.75 | 13332.75 | −11.9 | −13.3 | +0.0 | +11.9 |
| `a12b3c0199d9e753` | BUY | EXPIRED | 13404.65 | 13397.75 | 13428.55 | +23.9 | +23.0 | +40.4 | +0.3 |
| `b0ecacea0fc658f1` | BUY | EXPIRED | 13389.65 | 13375.05 | 13405.35 | +15.7 | +13.7 | +23.6 | +9.1 |
| `cd35a44360265147` | SELL | TARGET_HIT | 13415.65 | 13425.65 | 13380.65 | +35.0 | +33.6 | +41.3 | +4.8 |
| `31982bff857d57e3` | BUY | EXPIRED | 13389.65 | 13375.05 | 13405.35 | +15.7 | +13.7 | +23.6 | +9.1 |
| `24d3974ec0fa8d74` | BUY | EXPIRED | 13389.65 | 13375.05 | 13405.35 | +15.7 | +13.7 | +23.6 | +9.1 |
| `7498ece3f17ffbfa` | SELL | STOP_HIT | 13413.25 | 13419.05 | 13419.05 | −5.8 | −6.7 | +0.0 | +5.8 |
| `1ec91ccb09e95b4d` | BUY | EXPIRED | 13414.65 | 13407.65 | 13418.55 | +3.9 | +2.5 | +4.4 | +4.4 |
| `e1c03cad64fa6574` | SELL | EXPIRED | 13410.05 | 13419.75 | 13410.85 | −0.8 | −1.7 | +4.5 | +4.4 |

MFE/MAE above are **bounded to the holding period** (entry → exit
bar inclusive) — the earlier version extended past exit, inflating
figures.

### 1.3 Corrected totals

| Bucket | Trades | Pip total | Avg per trade |
|---|---|---|---|
| TARGET_HIT | 1 | +35.0 | +35.0 |
| STOP_HIT | 5 | −45.5 | −9.1 |
| EXPIRED | 7 | +87.4 | +12.5 |
| of which positive | 6 | +88.2 | +14.7 |
| of which negative | 1 | −0.8 | −0.8 |
| **TOTAL (13 trades)** | **13** | **+76.9** | **+5.92** |
| Session-aware spread cost (round-trip 1.8–2.8 pips) | | ≈ −17.0 | |
| **TOTAL NET** | | **+59.9** | **+4.61** |

**Win rate (profitable at exit): 7 / 13 = 53.8 %** (vs the earlier
16.7 % which only counted target vs stop).

### 1.4 No open / unresolved trades

Every one of the 13 fills resolved at a stop, target, or 24-bar
expiry. Zero "OPEN awaiting exit", zero "ERROR". No excluded trades.

### 1.5 Summary tables now agree

| Mechanism | Fills | Win % (profitable) | Gross | Net | PF | MDD |
|---|---|---|---|---|---|---|
| M1 baseline | 10 | 40.0 | −44.5 | −55.0 | 0.65 | −105.3 |
| **A momentum** | **13** | **53.8** | **+76.9** | **+59.9** | **2.66** | **−39.7** |
| B pullback | 7 | 57.1 | −1.8 | −9.6 | 0.96 | −41.1 |
| C structural | 4 | 50.0 | +6.6 | +3.0 | 1.28 | −13.2 |

**Mechanism A is net-positive on this sample. The previously
reported −17.4 net was a bookkeeping error.** The sample is still
n = 13 — this does NOT establish profitability at any confidence
level. The DEV / VAL split is still too thin.

## 2. Momentum exhaustion analysis (per brief §2)

For each A fill, the entry's position in the preceding 20-bar
high-low range was measured. A "climax" entry is defined as:
- BUY with entry in top 20 % of preceding 20-bar range (buying
  the local high), OR
- SELL with entry in bottom 20 % (selling the local low).

| Scenario | Entry rng_pos | Climax? | Exit | Gross |
|---|---|---|---|---|
| 87f92fc SELL | 0.18 | **YES** | EXPIRED | +13.3 |
| f5e1154 BUY | 0.95 | **YES** | STOP_HIT | −8.0 |
| 9fb5810 SELL | −0.15 | **YES** | STOP_HIT | −8.4 |
| bd7fbcc SELL | 0.34 | no | STOP_HIT | −11.4 |
| a6dedea SELL | 0.52 | no | STOP_HIT | −11.9 |
| a12b3c0 BUY | 0.84 | **YES** | EXPIRED | +23.9 |
| b0ecace BUY | 0.29 | no | EXPIRED | +15.7 |
| cd35a44 SELL | −0.48 | **YES** | TARGET_HIT | +35.0 |
| 31982bf BUY | 0.29 | no | EXPIRED | +15.7 |
| 24d3974 BUY | 0.29 | no | EXPIRED | +15.7 |
| 7498ece SELL | 0.86 | no | STOP_HIT | −5.8 |
| 1ec91cc BUY | 0.44 | no | EXPIRED | +3.9 |
| e1c03ca SELL | −0.06 | **YES** | EXPIRED | −0.8 |

Group totals:

| Group | n | Pip total | Avg | Win % |
|---|---|---|---|---|
| Climax entries | 6 | +55.0 | +9.17 | 50.0 |
| Non-climax entries | 7 | +21.9 | +3.13 | 57.1 |

### 2.1 Finding

**No systemic exhaustion problem on this sample.** Climax entries
average +9.17 p / trade vs non-climax +3.13 p. Both are positive;
neither suggests the momentum rule is systematically catching
exhausted moves. Win rates are within 7 points of each other, which
on n = 6 vs n = 7 is noise.

The brief asked whether "the 1.5× median-range impulse condition
sometimes selects the final candle of an extended move". Specific
instances:

- `f5e1154 BUY` at rng_pos 0.95 — bought near the 20-bar high.
  Stopped out at −8.0 p. V2's target DID reach eventually (post-
  expiry) but this was a classic buy-the-top loss.
- `a12b3c0 BUY` at rng_pos 0.84 — also near 20-bar high. Expired
  at +23.9 p. Not an exhausted move; it continued.
- `cd35a44 SELL` at rng_pos −0.48 — entry BELOW the 20-bar low.
  Target hit at +35.0 p. The "exhausted" position was actually a
  sustained impulse.

**Target-reached-eventually analysis** (any time post-entry, even
after exit):

| Reached V2's structural target later | 7 / 13 (54 %) |
| Never reached | 6 / 13 (46 %) |

Of the 7 that reached target: 1 was captured in-trade
(cd35a44 TARGET_HIT); the other 6 reached target AFTER the trade's
exit. Options the operator should know about:

- **Extend expiry.** 24 M5 bars (2 h) is a design choice; 48 or 72
  bars would catch more targets. Downside: tight-stop setups
  held longer increase the chance of post-expiry adverse reversion.
- **Keep 24 bars.** Fast capital rotation; smaller tail risk.

**No change recommended** without more data. 24 bars is a
reasonable default; the operator may re-tune after live DEMO data
accumulates.

### 2.2 Stop and target validity at entry

For every A fill, direction-correct geometry held: BUY had
`stop < sim_entry < target`; SELL mirrored. The mechanical stops
produced tight invalidation (median 7.7 p vs M1's 21.0 p median)
without geometry violations.

**Conclusion:** no evidence to tighten or loosen the entry filter.
Keeping 1.5× median range + 60 % body + 1 p buffer unchanged.

## 3. IG DEMO integration safety audit (per brief §3)

Line-by-line grep audit of
`impl/v2_demo_executor.py.template` against the 10 requirements:

| # | Requirement | Verified at | Status |
|---|---|---|---|
| 1 | Genuine IG DEMO account only | L67-77 import-time `_assert_demo_at_import` + wrapper exit 3 | **PASS** |
| 2 | Correct market-order execution via existing path | L113-134 lazy import of `autobot.execute_trade` with Phase 1 kwargs | **PASS** |
| 3 | Appropriate position size | L53-54 `V2_SV2_DEMO_POSITION_SIZE=0.5` default; `V2_SV2_DEMO_MAX_SIZE=2.0` hard cap at L79-80 | **PASS** |
| 4 | Broker-valid protective stop | Derived mechanically; `ig_dealing_rules.is_known_too_tight` pre-check at L241 | **PASS** |
| 5 | Target placement | V2's structural `target_price` preserved; passed to `execute_trade` | **PASS** |
| 6 | NMS permission at execution | L231-234 `_nms_evaluate` with `applicable AND not allowed` block | **PASS** |
| 7 | Existing-position / duplicate-order safeguards | Delegated to `trade_executor.execute_trade` EPIC_STATE dedup (central); V2 adds no new state | **PASS** |
| 8 | Broker acknowledgement and reconciliation | Delegated to central `close_sb_now.reconcile_open_positions` + `trade_manager`; V2 adds no exit loop | **PASS** |
| 9 | Rejection and timeout handling | `_submit_demo_order` catches exceptions and returns `DISPATCH_EXCEPTION` with error payload; central `trade_executor._extract_rejection_detail` records IG rejections and consults `ig_dealing_rules` for next cycle | **PASS** |
| 10 | No possibility of routing to funded LIVE account | Only `IG_ACC_TYPE=DEMO` passes the import guard; the string "LIVE" appears only in error messages; zero LIVE code path | **PASS** |

Grep audit for forbidden imports: zero matches for `ig_client`,
`trades_api`, `broker_client`, `requests`, `urllib.request`.

The DEMO executor is a **thin shim** over the existing central
broker infrastructure. No duplicate broker code lives in V2.

## 4. Simulated execution requirements REMOVED (per brief §4)

Per the operator directive, the following have been excised from
the correction:

- `V2_SV2_DEMO_DRY_RUN` env var — DELETED from the executor
  template.
- 3-6 DRY_RUN sweep observation phase — DELETED from
  `DEPLOYMENT_READINESS.md` (replaced by regression tests +
  preflight connectivity check).
- "DRY_RUN" status code in the decision journal — DELETED. The
  only non-active status is `DISABLED` (ENABLED=0) or `SKIPPED`
  (gate failure).

Replacement:

- **Regression + mocked integration tests** (`tests/test_v2_early_setup.py`,
  20 cases including: ENABLED=1 dispatches to a mocked broker,
  NMS block prevents dispatch, IG min-stop block prevents dispatch,
  dispatcher exception recorded not raised, LIVE env refused at
  import). **All 20 PASS.**
- **Read-only broker connectivity preflight**
  (`scripts/preflight_demo_connectivity.py`) — operator runs ONCE
  after install, BEFORE flipping ENABLED=1. Verifies IG_ACC_TYPE,
  approved production SHAs, mode-code patch, DEMO session, min-stop
  rules, NMS gate. Reads only; places no order.

## 5. Final readiness statement

- **Deliverables READY for operator review.**
- **Mechanism:** A (momentum impulse) with mechanical stop below
  impulse bar extreme + 1 p buffer and V2's target preserved;
  24-bar (2 h) expiry.
- **Honest sample result:** n=13; net +59.9 pips; 53.8 % profitable;
  PF 2.66; MDD −39.7. Not sufficient to establish profitability.
  DEMO deployment is a data-accumulation exercise.
- **Not deployed.** Production SHAs unchanged. Awaiting operator
  approval and manual activation steps per
  `DEPLOYMENT_READINESS.md`.

## 6. Precise deployment steps for operator (brief §5)

See `DEPLOYMENT_READINESS.md` §3 for the full command list. Short
summary:

1. **Pre-install:** backup current `/mnt/.../live_obs/agent/`
   `scenario_reasoner.py`, `scenario_recommendation.py`,
   `scenario_quality.py` and `/opt/tradingbot/ownership_identity.py`
   with sha256 sidecar.
2. **Install new modules:** copy
   `impl/v2_early_setup.py` into `/mnt/.../live_obs/agent/`;
   rename `impl/v2_demo_executor.py.template` →
   `v2_demo_executor.py` and install there (edit out the
   first-N-line template notice).
3. **Apply three patches:** `patches/0001-reasoner-prompt-setup-types.patch`,
   `0002-parser-validator-setup-types.patch`,
   `0003-ownership-mode-codes.patch`.
4. **Write wrapper + unit:** operator writes
   `v2_demo_sweeper.sh`, `live-scenario-v2-demo-exec.service`,
   `.timer` based on the design in `IG_DEMO_INTEGRATION.md` §3
   (this correction does NOT ship those executable files — the
   auto-mode classifier blocked their write; operator provides
   them manually).
5. **Preflight connectivity:** run
   `scripts/preflight_demo_connectivity.py`. Expect ALL GREEN.
6. **Install timer with ENABLED=0 first:** confirm no activity for
   one timer cycle (service logs `DISABLED` SKIP rows).
7. **Operator approval checkpoint:** confirm IG_ACC_TYPE=DEMO,
   confirm no LIVE account, confirm EMA_PB / BB_BOUNCE
   unaffected, confirm preflight all green.
8. **Flip V2_SV2_DEMO_ENABLED=1** in the service unit;
   `sudo systemctl daemon-reload`. Next sweep that passes all
   gates submits a REAL IG DEMO order.
9. **Observe for ≥ 30 fills.** Then re-run `scripts/backtest_coherent_setups.py`
   with live fills added to the sample. The operator decides
   whether to continue, revise, or disable.
