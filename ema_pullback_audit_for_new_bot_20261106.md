# EMA Pullback standalone service — audit for new-bot design — host-ip=REDACTED (2026-11-06)

READ-ONLY audit. No code, config, service or trade touched. Every
rule is quoted verbatim from the running source with file:line.
Facts labelled **CONFIRMED** (read and verified). **UNSURE** means
not fully verified.

---

## 1. Where it lives

### 1.1 Production tree — `/opt/ema_pullback/` (CONFIRMED by `ls` 2026-11-06)

```
/opt/ema_pullback/
├── .env                                        # live config
├── .env.example                                # template
├── ema_pullback/                               # Python package
├── systemd/ema-pullback.service                # systemd unit
├── venv/                                       # virtualenv
├── state/                                      # runtime state
│   ├── setup_history.jsonl                     # append-only setup records
│   └── broker_tracker_state.json               # broker position tracker
├── logs/ema_pullback.log                       # file-logger output
├── reports/                                    # weekly inventory reports
├── docs/                                       # specs + register
│   ├── EMA_PULLBACK_REMEDIATION_REGISTER.md    # source-vs-code audit
│   └── reference/
│       └── Scalping_strategy_original_transcript.md   # original spec
├── scripts/                                    # dev-only replay scripts
├── tests/                                      # pytest suite
├── backups/                                    # prior deployment snapshots
└── _backups/                                   # patch-rollback snapshots
```

### 1.2 Python package `/opt/ema_pullback/ema_pullback/`

| File | Lines | Role |
|---|---|---|
| `config.py` | 443 | Dataclass + .env loader — all runtime knobs |
| `main.py` | 400 | Entry point; shutdown policy |
| `service.py` | 3438 | Main loop (`EmaPullbackService`) |
| `trend.py` | 622 | H1 direction + qualification + H4 context |
| `pullback.py` | 86 | M5 pullback trigger rule |
| `entry.py` | 108 | 5-preceding-candle entry price |
| `intrabar.py` | 265 | Intrabar EMA8 touch + entry-level crossing |
| `entry_bar_guard.py` | 86 | Skips SL/TP evaluation on fill bar |
| `state_machine.py` | 253 | Setup lifecycle states |
| `exit_management.py` | 249 | Method B exit arithmetic |
| `exit_state_machine.py` | 252 | Post-fill exit SM |
| `exit_simulator.py` | — | Replay-mode exit simulator |
| `nms_gate.py` | 277 | Reads AutoBot session_trend_<SYM>.json |
| `watch_state_gate.py` | 318 | Reads AutoBot nms_watch_state_<SYM>.json |
| `trading_hours.py` | 208 | Mon-Fri 06:45-20:30 London gate |
| `live_execution_gates.py` | 189 | Installation-root + systemd-ppid guard |
| `execution_owner.py` | — | flock-based single-executor guard |
| `broker_submit.py` | 230 | MARKET-on-trigger submission flow |
| `broker_position_tracker.py` | — | Stage-E broker-side tracker |
| `candle_reader.py` | — | Reads `/opt/tradingbot/data/candles/GBPUSD/*.csv` |
| `h1_builder.py` | 96 | Rolls M5 candles to H1 |
| `h4_builder.py` | — | Rolls M5 candles to H4 (info only) |
| `indicators.py` | 18 | Pandas `ema` helper |
| `ig_client.py` | — | Thin IG REST client |
| `ig_dealing_rules.py` | — | IG min-stop lookup |
| `price_source.py` | 382 | OHLC walker + live price feed |
| `setup_logger.py` | 155 | Writes setup_history.jsonl |
| `escalation_resolve.py` | — | Operator CLI for UNCERTAIN/ESCALATED |
| `inventory_tool.py` | — | Working-order inventory CLI |
| `ownership.py` | 40 | `EMAPB-<B\|S>-<epoch>-<setupId>` reference builder |
| `ema_pullback_integration.py` | — | Boot wire-up helper |

### 1.3 Written specs / design documents (CONFIRMED)

| Path | Lines | What it is |
|---|---|---|
| `/opt/ema_pullback/docs/reference/Scalping_strategy_original_transcript.md` | 1602 | **Source transcript** of the YouTube strategy ("my five minute scalping strategy"), verbatim from the user-supplied `.docx`. The ORIGINAL rule set. |
| `/opt/ema_pullback/docs/EMA_PULLBACK_REMEDIATION_REGISTER.md` | 32 | **Confirmed adaptations register** — separates original source rules from owner-directed amendments, with discrepancy table. |
| `/opt/ema_pullback/TRADING_HOURS_DEPLOYMENT.md` | 100+ | Trading-hours deployment runbook (2026-10-30). |
| `/opt/ema_pullback/reports/legacy_wo_inventory_*.md` | — | Rolling legacy working-order inventories (not a spec; snapshot reports). |
| `/opt/ema_pullback/backups/pre-market-deploy-20261029T190000Z/BACKUP_NOTES.md` | — | Historical change note. |

**No `BUILD_SPEC.md` or `DESIGN.md`** is present on disk. The
transcript + remediation register are the authoritative design
documents. **CONFIRMED NOT FOUND** for a standalone build-spec.

### 1.4 Systemd unit — `/opt/ema_pullback/systemd/ema-pullback.service`

Installed to `/etc/systemd/system/ema-pullback.service` with
`ExecStart=/opt/ema_pullback/venv/bin/python -u -m ema_pullback.main`.
`User=autobot`, hardened with `NoNewPrivileges`, `ProtectSystem=strict`.
**CONFIRMED.**

---

## 2. What it reads

### 2.1 Primary data input — completed M5 candles from AutoBot's archive

CITE `/opt/ema_pullback/.env`:
```
CANDLE_ARCHIVE=/opt/tradingbot/data/candles/GBPUSD
```

That directory contains one CSV per UTC day of completed 5-minute
candles written by AutoBot. The service reads them read-only.
**CONFIRMED.**

### 2.2 Live price feed (intrabar)

Two optional live sources (both enabled on live):

```
INTRABAR_ENABLED=true
LIVE_PRICE_FEED_ENABLED=true
LIVE_PRICE_POLL_SECONDS=2.0
LIVE_PRICE_STALE_SECONDS=15.0
```

The live tick is polled from IG every 2 seconds. A tick older than
15 s marks the feed stale. **CONFIRMED** CITE `config.py:159-163`.

### 2.3 Timeframes

| Timeframe | Role | Built from | CITE |
|---|---|---|---|
| **M5** | pullback trigger + entry calc + cancellation | archive CSV + live tick | `pullback.py` + `intrabar.py` |
| **H1** | direction + qualification | `h1_builder.py` rolls M5 → H1 | `h1_builder.py:1-96` |
| **H4** | context only (NEVER gates) | `h4_builder.py` rolls M5 → H4 | `trend.py:544` |
| D1 / weekly | NOT USED. **CONFIRMED NOT FOUND**. | — | — |
| tick | used only to detect EMA8 touch + entry-level crossing | IG live feed | `intrabar.py` |

### 2.4 Indicators + exact settings (all from live `.env`)

CITE `/opt/ema_pullback/.env`:
```
H1_EMA_FAST=8
H1_EMA_MID=13
H1_EMA_SLOW=20
H1_MIN_COMPLETED_CANDLES=200
M5_EMA_FAST=8
M5_EMA_MID=13
M5_EMA_SLOW=21
H4_EMA_FAST=8   (default — not overridden in .env)
H4_EMA_MID=13   (default)
H4_EMA_SLOW=20  (default)
H4_MIN_COMPLETED_CANDLES=60 (default)
```

EMAs are computed with `pandas.ewm(span=n, adjust=False, min_periods=1)` —
standard exponential moving averages. CITE `indicators.py:1-18` +
`intrabar.py:17-27`.

**No RSI, no MACD, no ADX, no Bollinger Bands, no ATR, no stochastic.**
Grep over `/opt/ema_pullback/ema_pullback/` for `RSI`, `MACD`, `ADX`,
`bollinger`, `ATR`, `stoch` returns zero hits in production modules.
**CONFIRMED NOT FOUND** for all five.

### 2.5 External NMS inputs (read-only cache files)

The service reads TWO cache files that AutoBot writes atomically on
every M5 close; it never writes them:

| File (read-only) | Consumer module | Freshness cap |
|---|---|---|
| `/opt/tradingbot/cache/session_trend_GBPUSD.json` | `nms_gate.py` | 900 s |
| `/opt/tradingbot/cache/nms_watch_state_GBPUSD.json` | `watch_state_gate.py` | 900 s |

CITE `nms_gate.py:106-118`:
> `class FileSnapshotProvider:`
> `    """Reads the deployed NMS v3 snapshot JSON for a symbol.`
> `    The snapshot is written by ``/opt/tradingbot/session_trend.py``...`
> `    def load(self, symbol: str) -> Optional[Dict[str, Any]]:`
> `        p = self.snapshot_dir / f"session_trend_{symbol.upper()}.json"`

CITE `watch_state_gate.py:1-8`:
> `"""NMS WATCH_AND_WAIT directional-permission gate for EMA Pullback.`
> `A read-only consumer of the authoritative WATCH_AND_WAIT lifecycle`
> `published by the AutoBot proper at`
> `/opt/tradingbot/cache/nms_watch_state_<SYM>.json.`

---

## 3. How it decides price is trending

**ONLY H1 is used to admit a setup.** H4 is read but never gates
anything. NMS is a separate blocking filter (§3.3).

### 3.1 H1 direction — ordering + slope

CITE `/opt/ema_pullback/ema_pullback/trend.py:488-504`:
> `buy_order = (f_now > m_now) and (m_now > s_now)`
> `sell_order = (f_now < m_now) and (m_now < s_now)`
> `buy_slope = (f_now > f_prev) and (m_now > m_prev) and (s_now > s_prev)`
> `sell_slope = (f_now < f_prev) and (m_now < m_prev) and (s_now < s_prev)`
> ``
> `if buy_order and buy_slope:`
> `    direction = BUY`
> `    ordering_ok, slope_ok = True, True`
> `elif sell_order and sell_slope:`
> `    direction = SELL`
> `    ordering_ok, slope_ok = True, True`
> `else:`
> `    direction = NONE`

Plain English for BUY: the latest completed H1 bar must have
EMA8 > EMA13 > EMA20 **and** all three must be rising vs the
previous H1 (one-bar delta). Mirror for SELL.

### 3.2 H1 qualification — slope magnitude + EMA separation

**Both the ordering test AND the magnitude gates must pass**
before a new setup can arm. All thresholds default-on when
`h1_enforce_qualification=True` (live default).

CITE `/opt/ema_pullback/ema_pullback/trend.py:80-96`:
> `DEFAULT_MIN_EMA8_SLOPE_PIPS_PER_HR = 0.16`
> `DEFAULT_MIN_EMA13_SLOPE_PIPS_PER_HR = 0.16`
> `DEFAULT_MIN_EMA20_SLOPE_PIPS_PER_HR = 0.16`
> `DEFAULT_MIN_SEP_8_13_PIPS = 0.25`
> `DEFAULT_MIN_SEP_13_20_PIPS = 0.20`
> `DEFAULT_SLOPE_LOOKBACK_BARS = 3`

Interpretation:
- **3-bar slope** of each H1 EMA (closed-bar `[-1]` minus closed-bar
  `[-(1+3)]` divided by 3, expressed in pips per hour) must have the
  right sign and absolute magnitude ≥ 0.16 pips/hour.
- **Pairwise EMA separation** — the gap between EMA8 and EMA13 must
  be ≥ 0.25 pips (absolute), and EMA13 to EMA20 ≥ 0.20 pips.

If either any slope is below floor or either gap is too narrow, the
H1 qualifies as the direction (ordering + slope-sign ok) but
`admission_allowed=False` and no new setup can arm.

Documentation of the recalibration (CITE `trend.py:74-87`):
> `# Default thresholds (recalibrated 2026-10-26).`
> `# Slope floor = p50 of weakest-slope distribution over 2026-01-01→2026-10-23`
> `# (2,677 BUY/SELL H1 bars, reports/h1_qualification_recommendation_20261025.md §2).`
> `# Gap floors = p25 of sep_8_13 / sep_13_20 columns of the same distribution.`

### 3.3 NMS directional-protection block (reads AutoBot session_trend)

CITE `/opt/ema_pullback/ema_pullback/nms_gate.py:59-61`:
> `# Mirrors /opt/tradingbot/nms_v3_direction_gate.py:59-60. Any change to`
> `# the deployed gate's block set must be matched here.`
> `_STATES_BLOCK_SELL = frozenset({"STRONG_UP", "EMERGING_UP"})`
> `_STATES_BLOCK_BUY = frozenset({"STRONG_DOWN", "EMERGING_DOWN"})`

Plain English: before arming a new setup the service reads AutoBot's
`session_trend_GBPUSD.json`. If AutoBot's NMS v3 says
STRONG_UP or EMERGING_UP, a SELL cannot arm; mirror for DOWN. RANGE
/ NORMAL / UNKNOWN pass through. Snapshot older than 900 s or
malformed → fail-closed (block). CITE `nms_gate.py:236-250`.

### 3.4 WATCH_AND_WAIT directional-permission gate

CITE `/opt/ema_pullback/ema_pullback/watch_state_gate.py:72-77`:
> `_BLOCKING_STATES = frozenset({`
> `    "WATCH_AND_WAIT",         # operator spec §4 — both directions blocked`
> `    "REVERSAL_CONFIRMED",     # EMA PB is not the qm_reversal strategy`
> `})`

Plain English: the service reads AutoBot's
`nms_watch_state_GBPUSD.json`. If AutoBot says the market is in
WATCH_AND_WAIT (trend showing confirmed exhaustion), EMA PB blocks
new arms AND cancels any pending ARMED / ORDER_WAITING setup. If the
state is REVERSAL_CONFIRMED, EMA PB also blocks because it is not the
reversal strategy. TREND_TRADING and CONTINUATION_CONFIRMED pass.

### 3.5 H4 is diagnostic only

CITE `/opt/ema_pullback/ema_pullback/trend.py:544-561`:
> `def classify_h4(`
> `    h4_bars: Sequence[H4Bar],`
> `    ...`
> `) -> Optional[H4Context]:`
> `    """Classify the latest completed H4 bar as BUY / SELL / NEUTRAL.`
> `    Rule mirrors `classify_h1`: strict ordering (EMA8 vs EMA13 vs EMA20)`
> `    plus 1-bar same-signed slope. Anything else is NEUTRAL.`
> `    ...`
> `    H4 is attached to the step diagnostic for operator audit. The`
> `    service `_h1_admits` helper does NOT consult H4 — a valid new H1`
> `    direction admits regardless of H4 context, so H4 cannot`
> `    "permanently lock" the strategy into a stale BUY or SELL.`

---

## 4. Entry rules, step by step

### 4.1 BUY entry — ordered exactly as the service applies them

**Step 0 — Preconditions (all must hold before the touch is considered):**

1. **Trading hours open** (§7). Default Mon-Fri 06:45-20:30 London.
2. **No other setup is already active.** CITE `service.py:486`:
   > `if self.cfg.execution_enabled and self.active is not None:`
   Only one setup in {ARMED, SUBMITTING, UNCERTAIN, ESCALATED,
   ORDER_WAITING, IN_TRADE} is permitted at any time.
3. **H1 direction = BUY** with full qualification (§3.1, §3.2):
   EMA8 > EMA13 > EMA20, all three rising, 3-bar slope of each EMA
   ≥ 0.16 pips/hour, sep(EMA8,EMA13) ≥ 0.25 pips, sep(EMA13,EMA20)
   ≥ 0.20 pips.
4. **NMS v3 permits BUY** — session_trend snapshot state not in
   `{STRONG_DOWN, EMERGING_DOWN}`, snapshot fresh (<900 s).
5. **WATCH_AND_WAIT permits** — nms_watch_state snapshot state in
   `{TREND_TRADING, CONTINUATION_CONFIRMED}`.

**Step 1 — Pullback trigger (M5 EMA8 touch during the forming bar).**

CITE `/opt/ema_pullback/ema_pullback/intrabar.py:30-37`:
> `Touch rule under intrabar execution:`
> `  BUY  :  live_price <= live_ema8      (price has reached or crossed EMA8`
> `                                        downwards during the forming bar)`
> `  SELL :  live_price >= live_ema8      (price has reached or crossed EMA8`
> `                                        upwards during the forming bar)`
> `  The tracker fires AT MOST ONCE per forming bar — repeated touches do`
> `  not re-arm.`

The live M5 EMA8 is recomputed on each live tick with:
CITE `intrabar.py:17-23`:
> `  alpha  = 2 / (n + 1)`
> `  EMA_t  = alpha * close_t + (1 - alpha) * EMA_{t-1}`

For BUY: as soon as the live price goes **at or below** the live M5
EMA8 at any moment while a bar is forming, the touch fires. The
service arms **immediately** — it does not wait for the touch bar
to close.

**Step 2 — Setup validity check: not already cancelled.**

The pullback module separately checks the current completed-M5 shape
for BUY:

CITE `/opt/ema_pullback/ema_pullback/pullback.py:72-82`:
> `def evaluate_trigger(ctx: M5Context, h1_direction: str) -> TriggerResult:`
> `    """Classify a single M5 context against the H1 direction. Pure."""`
> `    if h1_direction == BUY:`
> `        if not (ctx.bar.low <= ctx.ema_fast):`
> `            return TriggerResult(False, "", ctx, "low_above_ema8")`
> `        if not (ctx.bar.close >= ctx.ema_slow):`
> `            return TriggerResult(False, "", ctx, "close_below_ema21")`
> `        return TriggerResult(True, BUY, ctx, "ok")`

Plain English: the touched bar's low must have reached EMA8 **and**
its close must be at or above EMA21. A close that has already slipped
below EMA21 disqualifies the setup even if EMA8 was touched.

**Step 3 — Compute entry level from the 5 PRECEDING completed bars.**

CITE `/opt/ema_pullback/ema_pullback/entry.py:1-13`:
> `Owner rule (2026-10-25) — five-candle preceding-reference breakout:`
> `  * BUY  entry = highest high of the 5 completed M5 bars IMMEDIATELY`
> `                 PRECEDING the EMA8-touch bar + 3 pips.`
> `  * SELL entry = lowest  low  of the 5 completed M5 bars IMMEDIATELY`
> `                 PRECEDING the EMA8-touch bar − 3 pips.`
> `  * The touch/forming candle itself is EXCLUDED from the lookback.`
> `  * The entry level is computed and FROZEN at the moment of arming`
> `    (not at a later candle close); the working order is placed at the`
> `    same moment so a tick that crosses the trigger immediately after`
> `    arming fills the order.`

CITE `entry.py:56-68` for the arithmetic:
> `buf = float(buffer_pips) * float(pip_size)`
> `if direction == BUY:`
> `    extreme = max(b.high for b in lookback)`
> `    entry = extreme + buf`
> `else:`
> `    extreme = min(b.low for b in lookback)`
> `    entry = extreme - buf`

With `ENTRY_BUFFER_PIPS=3` (live) and `PIP_SIZE=1.0`, a BUY entry is
3 pips above the highest high of the five preceding M5 bars.

**Step 4 — Submit a MARKET order when the next tick crosses that
entry level.**

Mechanical entry mode is `market_on_trigger` on live (CITE
`.env:MECHANICAL_ENTRY_MODE=market_on_trigger`). The setup stays
LOCAL in state `ARMED` until the live tick satisfies the crossing
test, at which moment a MARKET order is submitted.

CITE `service.py:1785-1812` (slippage + staleness gates on the
triggering tick):
> `age_budget = float(getattr(self.cfg, "quote_max_age_seconds", 3.0))`
> `...`
> `if age_s > age_budget:`
> `    (setup refused)`
> `slip_budget = float(getattr(self.cfg, "max_entry_slippage_pips", 2.0))`
> `...`
> `if slip_pips > slip_budget:`
> `    (setup refused)`

Plain English: the triggering tick must be no older than 3 seconds
and no further than 2 pips beyond the frozen entry level. Fail
either budget and the service refuses to submit.

**Step 5 — Transition to IN_TRADE at the broker's fill price.**

The service waits for the dealing-confirm from IG. The actual broker
fill may differ from the frozen entry level by up to the slippage
budget; the service records both. CITE `service.py:1911-1922`:
> `slip_budget = float(getattr(self.cfg, "max_entry_slippage_pips", 2.0))`
> `if realised_slip_pips > slip_budget:`
> `    (logged; fill is NOT reversed)`

**Exact moment and price at which a BUY opens:**
- The moment is the first live tick, after arming, whose price satisfies
  `tick_price >= entry_level` AND whose timestamp is within 3 s of
  wall clock AND whose deviation from entry_level is within 2 pips.
- The price is IG's broker fill (MARKET order); the frozen
  `entry_level` is recorded alongside for audit.

### 4.2 SELL entry

Mirror of BUY throughout:
- H1 direction = SELL with qualification (EMA8 < EMA13 < EMA20 all
  falling, all slope/gap gates in the SELL sign).
- Trigger: live price **≥** live M5 EMA8 during forming bar.
- Validity on touch bar: `high >= EMA8` AND `close <= EMA21`.
- Entry: lowest low of 5 preceding bars **minus** 3 pips.
- Fills when live tick crosses `tick_price <= entry_level`, with the
  same 3-s / 2-pip budgets.

### 4.3 The strategy owner's documented "owner rule 2026-10-25"

CITE `state_machine.py:70-78`:
> `Entry rule (owner, 2026-10-25):`
> `    When live M5 price touches EMA8 in the qualifying direction, arm`
> `    the setup IMMEDIATELY. The entry level is computed at the arming`
> `    moment from the five COMPLETED M5 candles immediately preceding`
> `    the touch candle (the touch/forming candle is excluded). BUY entry`
> `    = highest high + 3 pips; SELL entry = lowest low − 3 pips. The`
> `    entry level is frozen at arming and the working order is placed`
> `    at the same moment, so a tick that crosses the trigger immediately`
> `    after arming fills the order.`

---

## 5. What cancels a setup

**Only two cancellation paths exist** before fill. Both are enforced
in `_check_cancellations` / `_check_watch_state_cancellation`.

### 5.1 Completed-M5 close beyond EMA21 against trade direction

CITE `/opt/ema_pullback/ema_pullback/state_machine.py:58-65`:
> `Cancellation condition (ORDER_WAITING only; owner rule 2026-10-25):`
> `    * ONLY a completed M5 close beyond EMA 21 against trade direction cancels`
> `      an unfilled setup. Any completed M5 candle after the setup has armed`
> `      — including the arming candle itself — qualifies; wicks do NOT cancel.`

CITE `/opt/ema_pullback/ema_pullback/pullback.py:72-88`:
> `if direction == BUY:`
> `    ...`
> `    if not (ctx.bar.close >= ctx.ema_slow):`
> `        return TriggerResult(False, "", ctx, "close_below_ema21")`

Plain English:
- BUY setup cancels if any completed M5 bar from the touch bar onward
  closes **below** M5 EMA21.
- SELL setup cancels if any completed M5 bar closes **above** M5
  EMA21.
- Wicks beyond EMA21 within a bar do NOT cancel. Only the close counts.

CITE `state_machine.py:67-70`:
> `H1 changes AFTER arming must NOT cancel the setup — a reversal of the H1`
> `trend while a working order is pending has no effect on that order. The`
> `H1 trend is consulted only when arming a NEW setup (admission); it never`
> `cancels, modifies, or closes an existing one.`

### 5.2 NMS WATCH_AND_WAIT cancellation

CITE `watch_state_gate.py:28-30`:
> `* Default-disabled. Flipping ``EMAPB_WATCH_STATE_GATE_ENABLED=1``
> `  activates the gate for a staged rollout; default behaviour is`
> `  byte-identical to pre-patch EMA Pullback.`

Live flag is `=1`. If AutoBot's watch state transitions to
WATCH_AND_WAIT or REVERSAL_CONFIRMED while a setup is pending, the
service cancels the ARMED / ORDER_WAITING setup and returns to
WATCHING. CITE `service.py:1419` (the `_check_watch_state_cancellation`
entry).

### 5.3 Setup validity window (expiry)

CITE `/opt/ema_pullback/ema_pullback/config.py:306-316`:
> `# ── Setup validity window (2026-11-04) ──────────────────────────────`
> `# Maximum age in seconds between the original EMA8 touch (a setup's`
> `# ``trigger_ts``) and the breakout fire. ARMED / ORDER_WAITING setups`
> `# that exceed this budget are transitioned to EXPIRED by`
> `# ``EmaPullbackService._check_setup_expiry`` BEFORE any intrabar tick`
> `# can fill them. ...`
> `setup_max_age_seconds: float = 1200.0`

Live value: `SETUP_MAX_AGE_SECONDS=1200` (20 minutes). ARMED and
ORDER_WAITING setups that haven't filled within 20 minutes of the
EMA8 touch are moved to EXPIRED. SUBMITTING / UNCERTAIN / ESCALATED
are EXEMPT.

### 5.4 Pre-fill HTTP rejections / escalation

Technical refusal paths:

- **REJECTED** — broker HTTP 4xx. Terminal; slot freed.
- **UNCERTAIN** — HTTP error or missing confirm on a submitted order.
  Reconciler polls `/positions` + `/history/activity` until
  resolved. Slot stays occupied.
- **ESCALATED** — UNCERTAIN unresolved after
  `UNCERTAIN_ESCALATION_SECONDS=300` (5 min). Slot STAYS occupied
  until operator resolves via CLI `ema_pullback.escalation_resolve`.
- **SKIPPED** — rejected pre-order (e.g. `slot_occupied`,
  entry-budget breach). Terminal; slot freed.

### 5.5 Service shutdown

CITE `/opt/ema_pullback/systemd/ema-pullback.service` + `main.py:
95-158`:
- **`cancel_orders_only` (live default)** — SIGTERM cancels all
  EMAPB-prefixed working orders broker-side; open positions stay (IG
  protective SL/TP still on them).
- `cancel_and_close` — also closes open positions at market.
- `leave_everything` — stop without any broker call.

---

## 6. Stops, targets and exits

### 6.1 Exit mode

`EXIT_MODE=method_b` on live (CITE `.env`). "Method A" (legacy 12 SL /
15 TP full close) is retained in the code for replay comparison but
is not the active exit path.

### 6.2 Method B levels (all computed at fill time)

CITE `/opt/ema_pullback/ema_pullback/exit_management.py:11-19`:
> `Method B replaces the old 12 SL / 15 TP full exit with:`
> `    * broker protective stop        12 pips  (unconditional backstop)`
> `    * broker take profit           100 pips  (deliberately distant)`
> `    * software structural stop    trigger-candle extreme +/- 3 pips`
> `    * TP1                          1R                (close 50%)`
> `    * remainder stop             break-even -> 3-candle trailing`

| Level | Direction | Formula | CITE |
|---|---|---|---|
| **Broker SL** | BUY | `fill − BROKER_SL_PIPS` (=12p) | `exit_management.py:97` |
|  | SELL | `fill + BROKER_SL_PIPS` | same |
| **Broker TP** | BUY | `fill + BROKER_TP_PIPS` (=100p) | `exit_management.py:111` |
|  | SELL | `fill − BROKER_TP_PIPS` | same |
| **Software structural stop** | BUY | `trigger_bar.low − STRUCTURAL_BUFFER_PIPS` (=3p) | `exit_management.py:36-45` |
|  | SELL | `trigger_bar.high + STRUCTURAL_BUFFER_PIPS` | same |
| **TP1 (partial)** | BUY | `fill + initial_risk_pips` (1R; close 50%) | `exit_management.py:81-92` |
|  | SELL | `fill − initial_risk_pips` | same |

`initial_risk_pips = |fill − structural_sl|` (CITE L54-73).

### 6.3 Post-fill state machine

CITE `/opt/ema_pullback/ema_pullback/exit_state_machine.py:94-99`:
> `self.phase = FULL_POSITION_OPEN`
> `self.software_sl: float = plan.structural_sl`
> `self.break_even_level: Optional[float] = None`

On every tick (BUY uses bid; SELL uses ask — CITE L128-130):

**Phase 1 — `FULL_POSITION_OPEN`** (CITE L128-146):
- If price hits broker SL → full close, reason `broker_sl`.
- Else if price hits software structural SL → full close, reason
  `software_sl`.
- Else if price hits TP1 → **partial close 50%**, reason `tp1_partial`.
  After partial-close confirmation, phase advances to
  `REMAINING_50_PERCENT`, software SL is moved to break-even (=fill).
- Else if price hits broker TP → full close, reason `broker_tp`.

CITE `exit_state_machine.py:192-205`:
> `def confirm_partial_close(self, exit_price: float, ts: datetime) -> None:`
> `    """Call this ONLY after IG confirms the TP1 50% close succeeded."""`
> `    ...`
> `    self.phase = REMAINING_50_PERCENT`
> `    self.break_even_level = self.plan.fill_price`
> `    self.software_sl = advance_software_stop(`
> `        self.plan.direction, self.software_sl, self.break_even_level,`
> `        break_even_floor=self.break_even_level,`
> `    )`

**Phase 2 — `REMAINING_50_PERCENT`** (CITE L149-161):
- Software SL now moves with a 3-candle trailing stop:
  CITE `exit_management.py:124-135`:
  > `def three_candle_trail_level(`
  > `    direction: str,`
  > `    last_three_completed: Sequence[M5Bar],`
  > `    buffer_pips: float = 3.0,`
  > `    pip_size: float = 1.0,`
  > `) -> Optional[float]:`
  > `    """Trailing stop candidate from the LAST THREE COMPLETED M5 bars`
  > `    BUY  trail = min(low)  - buffer_pips`
  > `    SELL trail = max(high) + buffer_pips`
- Trail NEVER moves backwards and NEVER goes below break-even (CITE
  `exit_management.py:139-162`).
- If price hits broker SL → full close `broker_sl`.
- If price hits software SL (either break-even or trailing) → full
  close with reason `break_even` or `trailing_stop`.
- If price hits broker TP → full close `broker_tp`.

### 6.4 Fill-bar guard

CITE `/opt/ema_pullback/ema_pullback/entry_bar_guard.py:1-24`:
> `Entry-bar false-SL guard — correction package 2026-11-04.`
> `...`
> `in production has twice caused the service's exit_state_machine to`
> `declare a false broker_sl "final_exit" at the fill-bar's start-of-bar`
> `timestamp, while the IG broker position remained alive — abandoning the`
> `trade to broker-side SL / TP only.`

The service skips SL/TP evaluation on the M5 bar that contains the
fill timestamp. Two historical regressions prompted this patch.

### 6.5 Stale-price safety

CITE `exit_state_machine.py:76-80`:
> `If the executable-price source goes stale (ingest_price not called within`
> `stale_seconds) the SM reports ACTION_STALE_PRICE on the next tick —`
> `the caller must preserve the broker protective stop.`

Default stale window 15 s. Configurable via
`LIVE_PRICE_STALE_SECONDS`.

---

## 7. Limits

### 7.1 Trading hours

Mon-Fri **06:45-20:30 Europe/London**, half-open (20:30 BLOCKS).
Timezone-aware via `zoneinfo`.

CITE `/opt/ema_pullback/ema_pullback/trading_hours.py:52-55`:
> `DEFAULT_START = dtime(6, 45)`
> `DEFAULT_END = dtime(20, 30)`

Live `.env`:
```
TRADING_HOURS_ENABLED=1
TRADING_HOURS_SHADOW_MODE=1
TRADING_HOURS_START=06:45
TRADING_HOURS_END=20:30
```

**`SHADOW_MODE=1` on live** means blocks are **logged** as
`[TRADING_HOURS_BLOCK_SHADOW]` but entries are **still admitted**.
CITE `trading_hours.py:30-32`:
> `TRADING_HOURS_SHADOW_MODE (default 0) — when 1, emit`
> `[TRADING_HOURS_BLOCK_SHADOW] log but admit anyway. For the`
> `one-complete-trading-session shadow validation before enforcement.`

Admission rule is "fail-closed" when enforcement is live (an
exception → BLOCK). Cancellation at cutoff is "fail-open" (never
aggressively cancel on error).

### 7.2 News rules

**NOT FOUND.** Grep over `/opt/ema_pullback/ema_pullback/` for
`news`, `NEWS`, `calendar`, `event_blackout` returns zero hits.
EMA Pullback does **not** read AutoBot's news calendar nor apply
its own news blackout. CONFIRMED.

### 7.3 Concurrent trades

**Exactly one setup at a time.** CITE `state_machine.py:49-53`:
> `Only ONE active setup at a time. While ARMED / SUBMITTING / UNCERTAIN /`
> `ESCALATED / ORDER_WAITING / IN_TRADE, additional triggers are ignored`
> `(recorded as SKIPPED with reason='slot_occupied').`

CITE `service.py:486`:
> `if self.cfg.execution_enabled and self.active is not None:`

The live `.env` does set `ACCOUNT_WIDE_POSITION_BUDGET=0` — grep
shows this budget key is loaded into `Config` but is **not read** by
any gate in the production codebase. **Unused** per grep. (See §11.)

### 7.4 Trade size

CITE `.env`:
```
TRADE_SIZE=2.0
```

£2 per IG point on an IG spread-bet contract. Same unit AutoBot uses.
No position-sizing logic: every trade is 2.0 regardless of stop
distance. CITE `config.py:170-172`.

---

## 8. Switches — live `.env` verbatim

CITE `/opt/ema_pullback/.env` (secrets masked with <SECRET>):

```
SERVICE_NAME=ema-pullback
MARKET=GBPUSD
ACCOUNT_MODE=DEMO
EXECUTION_ENABLED=true
EMA_PULLBACK_LIVE_APPROVED=true
TRADE_SIZE=2.0
IG_EXPIRY=DFB
IG_CURRENCY_CODE=GBP
AUTOBOT_ENV_PATH=/opt/tradingbot/.env
AUTOBOT_ROOT=/opt/tradingbot
EMAPB_SHUTDOWN_POLICY=cancel_orders_only
CANDLE_ARCHIVE=/opt/tradingbot/data/candles/GBPUSD
H1_EMA_FAST=8
H1_EMA_MID=13
H1_EMA_SLOW=20
H1_MIN_COMPLETED_CANDLES=200
M5_EMA_FAST=8
M5_EMA_MID=13
M5_EMA_SLOW=21
ENTRY_BUFFER_PIPS=3
STOP_LOSS_PIPS=12
TAKE_PROFIT_PIPS=15
EXIT_MODE=method_b
BROKER_SL_PIPS=12
BROKER_TP_PIPS=100
STRUCTURAL_BUFFER_PIPS=3
TRAILING_BUFFER_PIPS=3
TP1_RISK_MULTIPLE=1.0
PARTIAL_CLOSE_FRACTION=0.5
PIP_SIZE=1.0
OWNERSHIP_HOST_PREFIX=EMAPB
IG_API_URL=<BROKER_API_URL_REDACTED>
IG_EPIC=<IG_EPIC_REDACTED>
IG_API_KEY=<SECRET>
IG_USERNAME=<SECRET>
IG_PASSWORD=<SECRET>
IG_ACC_ID=<SECRET>
ACCOUNT_WIDE_POSITION_BUDGET=0
POLL_SECONDS=20
STATE_DIR=/opt/ema_pullback/state
LOG_DIR=/opt/ema_pullback/logs
REPORT_DIR=/opt/ema_pullback/reports
NMS_GATE_ENABLED=true
NMS_SNAPSHOT_DIR=/opt/tradingbot/cache
NMS_SNAPSHOT_MAX_AGE_SECONDS=900
NMS_FAIL_POLICY=closed
MECHANICAL_ENTRY_MODE=market_on_trigger
MAX_ENTRY_SLIPPAGE_PIPS=2.0
QUOTE_MAX_AGE_SECONDS=3.0
UNCERTAIN_ESCALATION_SECONDS=300
UNCERTAIN_RESOLUTION_TIMEOUT_SECONDS=300
EXECUTION_OWNER_ENFORCED=true
EXECUTION_OWNER_SERVICE_NAME=ema-pullback.service
PRODUCTION_INSTALLATION_ROOT=/opt/ema_pullback
REQUIRE_SYSTEMD_CONTEXT=true
LEGACY_WORKING_ORDER_INVENTORY_ENABLED=true
MARKET_ON_TRIGGER_STARTUP_CANCEL_EXISTING_WORKING_ORDERS=false
INTRABAR_ENABLED=true
LIVE_PRICE_FEED_ENABLED=true
LIVE_PRICE_POLL_SECONDS=2.0
LIVE_PRICE_STALE_SECONDS=15.0
TRADING_HOURS_ENABLED=1
TRADING_HOURS_SHADOW_MODE=1
TRADING_HOURS_START=06:45
TRADING_HOURS_END=20:30
STAGE_E_SHADOW_MODE=0
SETUP_MAX_AGE_SECONDS=1200
EMAPB_WATCH_STATE_GATE_ENABLED=1
EMAPB_WATCH_STATE_SNAPSHOT_DIR=/opt/tradingbot/cache
EMAPB_WATCH_STATE_MAX_AGE_SECONDS=900
EMAPB_WATCH_STATE_FAIL_POLICY=closed
```

### 8.1 H1 qualification defaults (in `config.py`, not overridden in `.env`)

CITE `config.py:126-137`:
```
H1_MIN_EMA8_SLOPE_PIPS_PER_HR    = 0.16  # default; unset in .env
H1_MIN_EMA13_SLOPE_PIPS_PER_HR   = 0.16
H1_MIN_EMA20_SLOPE_PIPS_PER_HR   = 0.16
H1_MIN_SEP_8_13_PIPS             = 0.25
H1_MIN_SEP_13_20_PIPS            = 0.20
H1_SLOPE_LOOKBACK_BARS           = 3
H1_POINTS_PER_PIP                = 1.0
H1_ENFORCE_QUALIFICATION         = true
```

---

## 9. Spec vs code

The authoritative spec is the YouTube-video transcript at
`/opt/ema_pullback/docs/reference/Scalping_strategy_original_transcript.md`.
The remediation register documents 6 confirmed divergences — I
quote them verbatim and add my own observations after reading the
current code.

CITE `/opt/ema_pullback/docs/EMA_PULLBACK_REMEDIATION_REGISTER.md`:

| Topic | Original transcript says | Current code does | Register's disposition |
|---|---|---|---|
| **H1 anchor** | H1 EMA8 vs EMA21 + price on correct side of both (timestamps 02:29-03:40, 07:31-08:43) | H1 EMA8 / EMA13 / EMA20 ordering + slope + numeric qualification; no explicit price-vs-EMAs check | Owner-directed adaptation, recorded |
| **M5 trend fanning** | M5 EMA8/13/21 fanned in H1 direction (timestamps 03:50-04:05) | M5 EMAs computed but **NOT required to fan** — only EMA8 touch + close-not-past-EMA21 | **Unresolved strategy-fidelity discrepancy**; do not add gate without owner confirmation |
| **Trigger** | M5 EMA8 touch, invalidated by completed close through EMA21 | **IMPLEMENTED** (intrabar touch + completed-close cancellation) | Keep, verify on real tick chronology |
| **Entry** | Five candles **before** trigger, BUY high+3p, SELL low−3p | **IMPLEMENTED** (`entry.py`) | Keep; add event-level tick replay comparison |
| **Original stop** | Trigger-candle extreme ±3 pips | Method A: fixed 12 pip SL (adaptation); Method B: structural ±3p + broker 12p backstop (hybrid) | Treat as **distinct variants**; never call Method A "original" |
| **Original exits** | 50 % at 1R, remainder BE then 2R or 3-candle trailing (timestamps 06:01-06:53, 10:00-10:31, 13:00-14:28) | Method B approximates the 1R + trailing variant; Method A fixed 15 pip TP is an adaptation | Audit Method B chronologically; do not merge variants |

### 9.1 Register's own listed defects (quoted verbatim)

CITE register §"Confirmed implementation defects / evidence gaps":

> `1. Same-bar chronology not identifiable from M5 OHLC. A candle containing`
> `   an EMA8 touch and an entry-price crossing does not prove which`
> `   occurred first. Replay uses an adverse-first synthetic path; it is`
> `   a *scenario*, not a historical fact. ...`
> `2. Intrabar live execution blocked. `service._open_setup_intrabar``
> `   records `intrabar_touch_execution_blocked` when execution is enabled;`
> `   it does not place the working order. Do not deploy or enable trading`
> `   before explicit approval and end-to-end broker tests.`
> `3. Replay and runtime configuration are separate. ...`
> `4. Source/reference conflict. H1 EMA periods and M5 fanning differ from`
> `   original transcript. This is not permission to overwrite the owner's`
> `   subsequent strategy specification.`
> `5. No historical timestamped tick validation presented. Reproduce`
> `   touch, arming, order placement, fill and cancellation in order using`
> `   timestamped prices.`

### 9.2 Additional divergences I found while reading the code

1. **Broker TP = 100 pips, NOT 2R as the transcript implies.** The
   transcript describes "remainder to 2R or 3-candle trail". Live
   broker TP is a far-distant 100-pip failsafe; the ACTUAL exit for
   the remainder is only ever (a) break-even stop, (b) 3-candle
   trailing stop, or (c) the broker TP fence at 100 pips. There is
   **no explicit "2R take" rule in production code**. Grep for
   `2R`, `tp2`, `second_target` in `/opt/ema_pullback/ema_pullback/`
   returns no production reader.
2. **Trading-hours gate is in SHADOW** (`TRADING_HOURS_SHADOW_MODE=1`)
   on live — blocks are logged but entries proceed. Not a defect,
   but not what the deployment runbook calls "enforcement".
3. **`ACCOUNT_WIDE_POSITION_BUDGET=0` is unused** (see §7.3). Loaded
   into config, read by no gate.
4. **`STOP_LOSS_PIPS=12` and `TAKE_PROFIT_PIPS=15`** appear in `.env`
   but these are the Method A (legacy) values. With
   `EXIT_MODE=method_b` the service uses the Method B field set
   (broker_sl_pips=12 + broker_tp_pips=100). The 15-pip TP never
   fires. Not a defect — kept for replay comparison.
5. **Live-execution dual gates default to OFF** (`NMS_GATE_ENABLED`
   and `EMAPB_WATCH_STATE_GATE_ENABLED` both default False in
   `config.py`; they are `=true` on live only via `.env`). A fresh
   install **without** the deployed `.env` therefore has NO NMS
   protection — operator must explicitly enable.

---

## 10. Real results — from `/opt/ema_pullback/state/setup_history.jsonl`

### 10.1 Date range

**CONFIRMED** from file metadata:
- Earliest event: `2026-10-27T09:53:36Z`
- Latest event: `2026-11-06T13:29:37Z` (as of this audit, 2026-11-06)

Approximately **8 full trading days** of production records (Mon
2026-10-27 to Fri 2026-11-06, excluding weekends).

### 10.2 Volumes (CONFIRMED by replay of `setup_history.jsonl`)

**522 unique setups**, with these FINAL states:

| Final event | Setups | Note |
|---|---|---|
| CANCELLED | **373** | 71.5 % — mostly EMA21 close-against |
| NMS_V3_BLOCKED | **61** | NMS v3 blocked the arm |
| REJECTED | **42** | IG broker HTTP 4xx |
| CLOSED | **21** | Reached a trade and closed |
| WATCH_STATE_BLOCKED | **16** | Watch-state gate blocked the arm |
| EXPIRED | **7** | Setup aged out at 1200 s |
| ARMED (still live at audit time) | 2 | — |
| **Total** | **522** | — |

### 10.3 Closed trades (fill → exit) — ACTUAL BROKER P&L

**21 trades filled and closed** since 2026-10-27:

| Metric | Value |
|---|---|
| Trades | 21 |
| Wins | 2 (+47.1 pips) |
| Losses | 19 (−213.9 pips) |
| Flats | 0 |
| **NET** | **−166.8 pips** |

Exit-reason breakdown:

| Reason | Trades |
|---|---|
| `broker_closed` (broker-side SL/TP on a service that had no live post-fill tracking) | 16 |
| `broker_sl` | 2 |
| `software_sl` | 2 |
| `trailing_stop` | 1 |

**Only one trade in 21 reached the 3-candle trailing stop.** The
large `broker_closed` count reflects the known gap addressed by
the 2026-11-04 entry-bar guard (§6.4): the service had been
abandoning the post-fill tracker and relying on the broker's 12 pip
hard stop for most trades.

**Two partial TP1 closes were recorded** across all 21 trades
(CITE event counts: `TP1_PARTIAL_CLOSED: 2`).

### 10.4 Earliest and latest trades (verbatim)

Earliest BUY: `2026-10-29 14:20:22 UTC` — fill 1.33367, broker_sl at
1.33247, **−12.0 pips**.

Latest closed (as of audit): `2026-11-06 08:16:34 UTC` — SELL fill
1.34171, exit 1.34291, reason `broker_closed`, **−12.0 pips**.

**Caveat on reading these numbers.** Two issues are documented in
`entry_bar_guard.py` + the register:
- The service's post-fill tracker has been fixing false-SL events on
  the fill bar only since 2026-11-04 — losses before that date may be
  partially an artifact of the exit state machine, not the strategy.
- Shadow trading-hours means some trades happened outside 06:45-20:30
  London — they count in the P&L above.

---

## 11. Code that looks wrong, unused, switched off, duplicated, contradictory

**Observations only. No fixes.**

### 11.1 `TRADING_HOURS_SHADOW_MODE=1` on live

The deployment runbook calls this the pre-enforcement validation
phase. Blocks are logged but trades are **still admitted** outside
06:45-20:30 London. Not a defect per the runbook, but the
"trading hours" gate is not currently binding. **CONFIRMED.**

### 11.2 `ACCOUNT_WIDE_POSITION_BUDGET` is loaded but never read

CITE `.env`: `ACCOUNT_WIDE_POSITION_BUDGET=0`. Grep for
`account_wide_budget` in `/opt/ema_pullback/ema_pullback/` returns
only `config.py:93` where it's parsed. No gate consumes it.
**CONFIRMED unused.**

### 11.3 Legacy Method A fields in `.env`

`STOP_LOSS_PIPS=12` and `TAKE_PROFIT_PIPS=15` are Method A values
kept for replay-harness compatibility. With `EXIT_MODE=method_b`,
neither is consulted. Harmless but misleading when reading `.env`.
**CONFIRMED.**

### 11.4 `broker_closed` dominates the exit-reason mix (16 of 21)

The post-fill `ExitStateMachine` is the authoritative exit for live
trades, but two production incidents (`<DEAL_REF_REDACTED_1>` 2026-10-29
and `<DEAL_REF_REDACTED_2>` 2026-11-04 — both referenced in
`entry_bar_guard.py`) show the state machine declared a false
"final_exit" at the fill bar's open while the IG position remained
alive. Trades then closed on the broker 12-pip hard stop without
being tracked. Patch landed 2026-11-04. **CONFIRMED.**

### 11.5 Two separate ARMING code paths in `service.py`

`_open_setup` (completed-bar arming) and `_open_setup_intrabar`
(intrabar arming) are parallel code paths. The intrabar path is the
live one under `INTRABAR_ENABLED=true`; the completed-bar path is
used for replay. Each has its own gates and audit stamps. Not a
defect, but any new design should unify. **CONFIRMED.**

### 11.6 Backup trees in production path

`/opt/ema_pullback/backups/` and `/opt/ema_pullback/_backups/` contain
old copies of `config.py`, `service.py`, `state_machine.py` etc.
with their own `.env` files. Harmless because Python imports
`ema_pullback.*` from the top-level package only — but `grep -r`
investigations easily surface stale definitions.

### 11.7 H4 context is computed every bar but gates nothing

CITE `trend.py:548-556`:
> `H4 is attached to the step diagnostic for operator audit. The`
> `service `_h1_admits` helper does NOT consult H4 — a valid new H1`
> `direction admits regardless of H4 context, so H4 cannot`
> `"permanently lock" the strategy into a stale BUY or SELL.`

Not a defect — documented design — but the H4 EMA build runs on every
step. Pure overhead for observability. **CONFIRMED.**

### 11.8 Legacy percentile-model qualification thresholds in `H1Qualification`

`slope_gate / sep_8_13_gate / sep_13_20_gate / sep_8_20_gate` are
still present in the dataclass and the `.env` has placeholders
(`H1_MIN_SLOPE_PTS`, `H1_MIN_SEP_8_13_PTS`, `H1_MIN_SEP_13_20_PTS`,
`H1_MIN_SEP_8_20_PTS`) — all unset in live `.env`, all documented
as "never gates admission even when configured". Dead schema kept
for backward compatibility. **CONFIRMED.**

### 11.9 M5 EMA fanning requirement is **absent** vs the transcript

The transcript (03:50-04:05) specifies that M5 EMA8/13/21 must be
**fanned** in the H1 direction. The current implementation only
checks EMA8 **touch** + EMA21 **close-not-past**. The register flags
this as "unresolved strategy-fidelity discrepancy — do not add a
gate without owner confirmation". **CONFIRMED.**

### 11.10 No news blackout

A new bot design that intends to run during NFP / BoE / Fed hours
needs to add one. EMA PB currently has none. §7.2 **CONFIRMED NOT
FOUND.**

### 11.11 `EMAPB_SHUTDOWN_POLICY=cancel_orders_only` leaves positions
open across restart

On `systemctl stop` the service cancels working orders but leaves
open positions. The broker's 12-pip protective SL is the only
protection during the restart window. **CONFIRMED** (documented, not
a defect).

### 11.12 Shadow Stage-E has been turned OFF on live (`STAGE_E_SHADOW_MODE=0`)

Live broker closes are enabled. Prior to 2026-11-04 the service
would record simulated TP1 / final-close intents without calling
the broker. Now it probes-then-submits via `broker_submit.py`.
**CONFIRMED.**

---

## UNSURE list

- Whether the H4 EMA builder (`h4_builder.py`) was read in full — I
  only inspected its usage site. Threshold constants not verified.
- Whether the M5 EMA fanning could be reintroduced as an owner
  decision — the register explicitly says "do not add a gate without
  owner confirmation", so this depends on operator intent.
- Whether the "2R target" ever fires in the live code — grep found
  no explicit reader of the 2R level; it may be reachable only via
  the broker TP fence at 100 pips, which is deliberately distant.

---

*End of audit.*
