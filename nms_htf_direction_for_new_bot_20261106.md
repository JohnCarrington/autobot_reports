# How higher timeframes influence the direction NMS decides

Host: AutoBot (REDACTED) — read-only audit.
Date: 2026-11-06.
This copy has all server addresses replaced by REDACTED; no account IDs, passwords, keys, tokens or deal references appear in either copy.

Context: supplements the earlier NMS audit (`nms_audit_for_new_bot_20261106.md`), which focused on the 5-minute state machine. This report walks every place where **H1, H4, D1 or W1** information touches the direction the NMS pipeline will allow a bot to trade.

Everywhere below, line numbers refer to files under `/opt/tradingbot/` unless stated. Quotes are verbatim from the source.

Live production flag state at audit time (`/opt/tradingbot/.env`):

```
640:HTF_REGIME_ENABLED=1
1107:NMS_V3_DIRECTIONAL_GATE_ENABLED=1
1124:NMS_V3_H1_ADMISSION_ENABLED=1
1125:NMS_V3_H1_ADMISSION_FAIL_POLICY=closed
1131:DIRECTION_FROM_NMS_SESSION_TREND=1
1141:NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1
```

`HTF_AUTHORITY_ENABLED` is **not set** → defaults to 0.
`REGIME_MATRIX_ENABLED` is **not set** → defaults to 0.

---

## 1. The hourly admission check — what happens when NMS_V3_H1_ADMISSION_ENABLED=1

### 1.1 Which file does it

`/opt/tradingbot/nms_v3_direction_gate.py`. The admission block is the part of `check()` at lines 543–610. The H1 read itself is `_h1_bias()` at lines 202–298.

### 1.2 When the check runs

Only when ALL of the following hold (see `check()` lines 454–462, 525–541, 562):

1. `NMS_V3_DIRECTIONAL_GATE_ENABLED=1` (the parent gate is live).
2. The strategy is in the V3 scope (line 52–56):
   ```
   V3_STRATEGIES = frozenset({
       "V3_BB_L", "V3_BB_S",
       "V3_EMA_L", "V3_EMA_S",
       "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
   })
   ```
3. The 5-minute `session_trend` snapshot is valid (file present, correct schema, matching symbol, timestamp fresher than `NMS_V3_SNAPSHOT_MAX_AGE_S`, default 900 s).
4. The 5-minute v3_state is **not** already directional. The admission check applies **only** to structurally neutral states, listed at lines 63–66:
   ```
   _H1_ADMISSION_NEUTRAL_STATES = frozenset({"RANGE", "NORMAL", "UNKNOWN", ""})
   ```
   If v3_state is `STRONG_UP` / `STRONG_DOWN` / `EMERGING_UP` / `EMERGING_DOWN`, the base V3 rule at lines 525–541 has already blocked (or passed) the fire. The H1 admission is deliberately skipped in those cases — comment at lines 544–557:
   ```
   # STRONG_* and EMERGING_* already supply a directional opinion from V3;
   # we do not want to overwrite the classifier's structural regime there.
   ```
5. `NMS_V3_H1_ADMISSION_ENABLED=1` (default 0). See lines 562–564:
   ```
   if state in _H1_ADMISSION_NEUTRAL_STATES and _env_bool(
       _FLAG_H1_ADMISSION_ENABLED, "0"
   ):
   ```

### 1.3 What it reads from the hourly chart

`_h1_bias()` at lines 202–298 queries two things from `/opt/tradingbot/htf_cache.py` and `/opt/tradingbot/htf_regime.py`:

```
241        try:
242            from htf_cache import load_cached_candles, last_candle_age_secs
243            cached = load_cached_candles(sym_u, "H1") or {}
244            cs = cached.get("candles") if isinstance(cached, dict) else None
245            open_age = last_candle_age_secs(cs) if cs else None
```

That reads the latest completed H1 bars for the symbol from the H1 cache. The cache is point-in-time by construction — it only serves bars that have CLOSED.

Then it calls `htf_regime.classify(sym)` at line 276:

```
275        try:
276            result = _htf.classify(sym_u)
277        except Exception as exc:
278            return None, f"h1_unavailable:{type(exc).__name__}"
```

`classify()` lives at `htf_regime.py` line 650. It computes H1 features (`ema_fan_pips`, `ema8_50_pips`, Bollinger-band mid slope, BB-width percentile, MACD(12,26,9) histogram) and classifies the H1 bar into one of six states (`htf_regime.py` lines 400–479):

- `TRENDING_UP` / `TRENDING_DOWN` — ascending / descending EMA stack + fan ≥ `HTF_H1_FAN_FLOOR_PIPS` (default 4.0 p) + BB-mid slope ≥ `HTF_H1_SLOPE_FLAT_FLOOR` (default 0.5 p/bar) + MACD histogram agreeing.
- `COMPRESSION`, `EXPANSION`, `EXHAUSTION`, `RANGE` — all treated as "no established trend" here.

The admission block treats only `TRENDING_UP` and `TRENDING_DOWN` as an **established H1 trend**. Everything else passes (lines 68–73):

```
68  # H1 state values from htf_regime.py (TRENDING_UP / TRENDING_DOWN).
69  # These are the ONLY two values treated as "established H1 trend" by
70  # the admission cross-check. H1_RANGE / H1_COMPRESSION / H1_EXPANSION /
71  # H1_EXHAUSTION all pass through.
72  _H1_BIAS_UP = "TRENDING_UP"
73  _H1_BIAS_DOWN = "TRENDING_DOWN"
```

### 1.4 Freshness rule for the H1 bar

Measured in **age-since-close**, not age-since-open. The H1 cache's `bucket_epoch` is the bar's open time, so close-age = open-age − 3600. The patch at lines 105–115 explains why:

```
105  # H1 bar duration — htf_cache's `bucket_epoch` is the bar OPEN time, so
106  # the bar's close = bucket_epoch + _H1_BAR_SECONDS. All freshness
107  # arithmetic in `_h1_bias` is based on age-since-close.
108  _H1_BAR_SECONDS = 3600
109  # Default H1 freshness window (seconds past the newest H1 bar's close).
110  # A completed H1 bar remains usable throughout the following H1
111  # interval (3600s) plus 300s slack for feed-write latency at the
112  # hour-boundary refresh. Previous value (4500s) was applied to the
113  # OPEN timestamp, which effectively granted only 900s past close
114  # (2026-10-20T20:46Z incident). The default is now in close-age terms.
115  _DEFAULT_H1_MAX_AGE_SECONDS = 3900
```

Checks performed at lines 250–261:

```
250        close_age = open_age - _H1_BAR_SECONDS
251        if close_age < 0:
...
254            return None, (
255                f"h1_unavailable:incomplete:close_age_s={close_age:.0f}"
256            )
257        if close_age > _h1_max_age_seconds():
258            return None, (
259                f"h1_unavailable:stale:close_age_s={close_age:.0f}"
260            )
```

A negative close-age means a future-dated or still-forming bar and is treated as unavailable.

### 1.5 Exactly what it decides

The block at lines 562–610 produces one of four outcomes.

**Outcome A — H1 is unavailable and policy is `closed` (your production setting):** block the entry with `h1_admission_fail_closed`. Lines 566–575:

```
566        if bias is None and h1_reason.startswith("h1_unavailable"):
567            policy = _h1_admission_fail_policy()
568            if policy == _H1_POLICY_CLOSED:
569                dec.allowed = False
570                dec.binding = "h1_admission_fail_closed"
571                dec.reason_codes = [
572                    f"nms_v3_h1_admission_fail_closed:{h1_reason}",
573                ]
574                _emit_decision(dec)
575                return dec
```

(The default is `open`. Your `.env` sets `closed`.)

**Outcome B — H1 is unavailable and policy is `open`:** pass, but record `h1_fail_open` in the reasons for audit. Lines 576–584:

```
576            # fail-open — fall through to the pass path with a
577            # distinct reason so the audit trail still shows that H1
578            # was consulted and unavailable.
579            dec.reason_codes = [
580                f"nms_v3_direction_pass:state={state or 'empty'}"
581                f":h1_fail_open:{h1_reason}",
582            ]
```

**Outcome C — H1 is TRENDING against the proposed side:** block with `h1_admission_block`. Lines 585–602:

```
585        if bias == "UP" and side_u == "SELL":
586            dec.allowed = False
587            dec.binding = "h1_admission_block"
588            dec.reason_codes = [
589                f"nms_v3_h1_admission_block:v3={state or 'empty'}"
590                f":h1={h1_reason}:side={side_u}",
591            ]
...
594        if bias == "DOWN" and side_u == "BUY":
595            dec.allowed = False
596            dec.binding = "h1_admission_block"
597            dec.reason_codes = [
598                f"nms_v3_h1_admission_block:v3={state or 'empty'}"
599                f":h1={h1_reason}:side={side_u}",
600            ]
```

**Outcome D — H1 does not oppose the side (or H1 is neutral):** pass, with the H1 state recorded in the reason. Lines 603–610:

```
603        # H1 does not oppose this side (or h1 is neutral) — pass with
604        # the enriched reason.
605        dec.reason_codes = [
606            f"nms_v3_direction_pass:state={state or 'empty'}"
607            f":h1={h1_reason}",
608        ]
```

### 1.6 Earned-exception policy

**There is none.** Comment at lines 551–558:

```
551  # No countertrend "earned exception" is implemented in this
552  # repair. The requirement (H1 exhaustion AND M5 price-action
553  # confirmation, both required) is not satisfied by any single
554  # existing signal — see the deliverable report §9's gap analysis
555  # against news_trend_classifier.NewsTrendState. Until the earned-
556  # exception evidence contract is verified end-to-end, every V3-
557  # scope counter-H1 fire is blocked when H1 is trending.
```

So the rule is strict: V3 strategies cannot BUY when H1 is `TRENDING_DOWN`, and cannot SELL when H1 is `TRENDING_UP`, during the structurally-neutral 5-minute states.

### 1.7 How it changes the direction allowed

It never **changes** the direction the trade would be. It **refuses** the trade. The strategy still proposes BUY or SELL; the gate accepts or rejects. There is no mechanism in this module that converts a BUY proposal into a SELL (or vice versa).

Counter-H1 trades are blocked only for the six V3 strategies listed at §1.2. Any other strategy short-circuits to `allowed=True` with `nms_v3_strategy_not_in_scope` at `check()` lines 459–462.

---

## 2. session_trend_integration.py — pivots and IG daily %

File: `/opt/tradingbot/session_trend_integration.py` (153 lines total).

The module is a **pair of bridges**, nothing more. Its own docstring (lines 32–36):

```
32  **No gating.** Pivot support and daily-% are SUPPORTING EVIDENCE
33  labelled in the reason string, never used as establishment /
34  reversal gates. If a bridge fails or data is stale, the state
35  machine behaves exactly as it does today (prior to this bridge)
36  — structural evidence remains the primary driver.
```

### 2.1 The pivot bridge

`bridge_pivots_to_session_trend()` — lines 47–110. Steps:

1. Imports `ig_daily_pivots` and `session_trend` lazily (line 60–61).
2. Calls `ig_daily_pivots.read_pivots(today)` to load the once-a-day JSON file produced by the IG REST ASK-side D-1 bar.
3. Validates the payload holds all seven standard pivots:
   ```
   85    pivots = pair_payload.get("pivots_ask")
   86    if not isinstance(pivots, dict) or not all(
   87        k in pivots for k in ("P", "R1", "R2", "R3", "S1", "S2", "S3")
   88    ):
   ```
4. Pushes them into `session_trend.set_daily_pivots()` (lines 94–99):
   ```
   94    try:
   95        _st.set_daily_pivots(
   96            symbol=symbol,
   97            pivots={k: float(v) for k, v in pivots.items()},
   98            source_date=doc.get("trading_date"),
   99        )
   ```

`session_trend.set_daily_pivots()` is at `/opt/tradingbot/session_trend.py` lines 726–735:

```
726  def set_daily_pivots(symbol: str, pivots: Dict[str, float],
727                        source_date: Optional[str] = None) -> None:
...
732      s = _get_or_create(symbol)
733      with _REGISTRY_LOCK:
734          s.daily_pivots = dict(pivots)
735          s.pivot_source_date = source_date
```

It stores the seven pivot prices on the per-symbol state. Nothing else happens at write time.

### 2.2 How pivots change direction

They enter the state machine only through **pivot rejection events**, which are produced by `_detect_pivot_rejection()` at `/opt/tradingbot/session_trend.py` lines 1766–1797:

```
1766  def _detect_pivot_rejection(
1767      s: _SessionState, bar_ts: datetime,
1768      h: float, l: float, c: float,
1769  ) -> None:
1770      if not s.daily_pivots:
1771          return
1772      for name, lvl in s.daily_pivots.items():
1773          # Only R3 / S3 are first-class "early directional" rejections.
1774          if name not in ("R3", "S3", "R2", "S2"):
1775              continue
1776          if name.startswith("R"):
1777              # Upper band: proximity = how close bar high got to pivot.
1778              dist = h - lvl
1779              # A rejection UP-side pivot is characterised by the bar
1780              # TOUCHING the pivot (|h - lvl| <= proximity) AND the close
1781              # being BELOW the pivot (price pulled away downward).
1782              if abs(dist) <= PIVOT_PROXIMITY_PIPS and c < lvl:
1783                  s.pivot_rejections.append(PivotRejection(
1784                      ts=_iso(bar_ts), pivot_name=name,
1785                      pivot_price=float(lvl),
1786                      rejection_direction="DOWN",
1787                      distance_pips=float(dist),
1788                  ))
1789          else:
1790              dist = l - lvl
1791              if abs(dist) <= PIVOT_PROXIMITY_PIPS and c > lvl:
1792                  s.pivot_rejections.append(PivotRejection(
1793                      ts=_iso(bar_ts), pivot_name=name,
1794                      pivot_price=float(lvl),
1795                      rejection_direction="UP",
1796                      distance_pips=float(dist),
1797                  ))
1798
```

So a pivot rejection fires on a 5-minute bar when:
- The bar touched R2 or R3, and closed below it → **DOWN rejection**.
- The bar touched S2 or S3, and closed above it → **UP rejection**.

Those rejections then feed the **direction establishment** logic in the FIRST-session helpers `_check_establish_down()` (lines 2039–2078) and `_check_establish_up()` (lines 2081–2107):

```
2049      choch_down_cnt = sum(1 for e in s.choch_events if e.direction == "DOWN")
2050      pivot_down_cnt = sum(1 for p in s.pivot_rejections
2051                            if p.rejection_direction == "DOWN"
2052                            and p.pivot_name in ("R3", "R2"))
...
2063      if disp is not None and disp <= -DISPLACEMENT_PIPS_FOR_ESTABLISH \
2064              and (choch_down_cnt >= STRUCTURAL_CHOCH_FOR_ESTABLISH
2065                   or pivot_down_cnt >= 1):
```

A pivot rejection can therefore contribute to:

- **Signal B** at lines 2063–2069 — a big displacement combined with at least one same-direction pivot rejection establishes a DOWN (or UP) session trend.
- **Signal C** at lines 2071–2075 — a CHoCH plus at least one pivot rejection establishes.

Pivot rejections are also summarised into `piv_support` on `STRONG_UP` / `STRONG_DOWN` promotion reasons (lines 2001–2034), where they are **supporting evidence recorded in the reason string** rather than a gate.

### 2.3 The IG daily-% bridge

`bridge_ig_daily_pct_to_session_trend()` — lines 113–147. Fetches the "daily percentage change" IG serves on `/markets` via `session_ig_daily_pct.fetch_and_record()`, which calls `session_trend.set_ig_daily_pct()`:

```
738  def set_ig_daily_pct(symbol: str, pct: float, source: str,
739                        as_of_ts: Optional[datetime] = None) -> None:
...
747      s = _get_or_create(symbol)
748      with _REGISTRY_LOCK:
749          s.ig_daily_pct_change = float(pct)
750          s.ig_daily_pct_source = str(source or "")
751          s.ig_daily_pct_as_of = _iso(as_of_ts) if as_of_ts else None
```

### 2.4 How the IG daily % changes direction

**It does not.** A full-tree grep of every `.py` outside of `_backups/`, `archive/`, `_agent_restore/` returns only three kinds of usage for `ig_daily_pct_change`:

- Dataclass field definition on `_SessionState` (`session_trend.py:367`).
- `to_dict` / `from_dict` serialisation (`session_trend.py:432, 507, 2169`).
- Snapshot payload field (`session_trend.py:557, 601`).
- Two test files that only assert the value is recorded.

There is no reader anywhere in the live code that uses `ig_daily_pct_change` to influence session-trend establishment, prevailing direction, admission, or any gate. It is recorded and published for operator inspection and nothing more.

### 2.5 Snapshot path and consumer

Both pivot rejections and the daily-% value are embedded in the snapshot that `session_trend._write_snapshot()` publishes atomically on every 5-minute bar close:

```
2209  def _write_snapshot(symbol: str, auth: SessionTrendAuthority) -> Optional[Path]:
2210      """Publish the authority snapshot JSON atomically."""
2211      dest = _snapshot_path(symbol)
```

Snapshot location: `/opt/tradingbot/cache/session_trend_<SYMBOL>.json` (configurable via `SESSION_TREND_SNAPSHOT_DIR`). This is the file every downstream NMS gate reads.

---

## 3. Everything else that lets a higher timeframe touch the direction NMS decides

Four other surfaces matter in production, in order of impact. Items the earlier audit missed are called out as such.

### 3.1 BOUNCE rulebook — H1 MACD(35,45,30) histogram "tiring" test (LIVE)

File: `/opt/tradingbot/nms_session_trend_direction.py`.
Flag that enables it: `DIRECTION_FROM_NMS_SESSION_TREND=1` (ON in production, `.env:1131`).

The module docstring at lines 11–19 is the plain-English rule:

```
11    BOUNCE (V3_BB, GBPUSD_BB_BOUNCE, bb-bounce.service)
12      1. Same-direction as the trend         → always allowed.
13      2. RANGE / NORMAL                       → both directions allowed.
14      3. Counter-direction to STRONG_* /
15         EMERGING_*                           → allowed only if H1
16                                                MACD(35,45,30) hist is
17                                                "tiring" (abs forming <
18                                                abs last-completed).
19      UNKNOWN                                 → no trade.
```

The decision is `permit_bounce()` at lines 302–409. The tiring read is:

```
381      if side_u == "SELL" and st in _BOUNCE_COUNTER_UP:
382          t = read_h1_macd_tiring(symbol, now=now)
383          if t.tiring:
384              return DirectionVerdict(
385                  allowed=True, reason=f"bounce_counter_tiring:{st}",
386                  v3_state=st, fresh=True,
387              )
388          return DirectionVerdict(
389              allowed=False,
390              reason=f"bounce_counter_not_tiring:{st}:{t.reason}",
391              v3_state=st, fresh=True,
392          )
```

The tiring snapshot comes from `/opt/tradingbot/cache/h1_macd_tiring_<SYMBOL>.json`, written by `/opt/tradingbot/h1_macd_tiring_writer.py` on every 5-minute bar close. `read_h1_macd_tiring()` at lines 197–225 treats a missing or stale snapshot as `tiring=False` — i.e. **fail-closed on counter-trend bounces**.

**Key fact:** when this rulebook is enforced, the H1 MACD "tiring" flag directly controls whether a counter-trend BOUNCE is allowed. That is H1 influencing NMS admission, in addition to the H1 admission check in §1.

**Note:** `DIRECTION_FROM_NMS_SESSION_TREND=1` also **disables** the parent NMS V3 directional gate inside `trade_executor.execute_trade` at lines 7149–7157:

```
7149      # Operator ruling 2026-10-21: when DIRECTION_FROM_NMS_SESSION_
7150      # TREND=1 this guard is SKIPPED. The new BOUNCE/TREND rulebooks
7151      # (nms_session_trend_direction) replace it at the per-strategy
7152      # seams, so running it here would double-block.
7153      if os.getenv(
7154          "DIRECTION_FROM_NMS_SESSION_TREND", "0",
7155      ).strip() in ("1", "true", "yes", "on"):
7156          pass
7157      else:
```

So in the current production configuration, the per-strategy `permit_trend` / `permit_bounce` **replace** the central_execution_gate V3 check at `trade_executor` admission time. The V3 check still runs at `central_execution_gate.evaluate()` line 2355, which is called from the orchestrator; both paths see it.

### 3.2 Unified Directional Authority — matrix with H1 MACD exhaustion (LIVE)

File: `/opt/tradingbot/nms_directional_authority.py`.
Flag: `NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1` (ON in production, `.env:1141`).

When `permit_bounce` / `permit_trend` in `nms_session_trend_direction.py` run and detect the unified flag is on (lines 265–282, 343–358), they **delegate** to `nms_directional_authority.evaluate()`. That module's own docstring (lines 15–49) documents its matrix:

```
TREND_CONTINUATION / TREND_PULLBACK families (unchanged):

    STRONG_UP     : BUY ALLOW                            SELL BLOCK
    EMERGING_UP   : BUY ALLOW                            SELL BLOCK
    NORMAL        : BUY BLOCK                            SELL BLOCK
    RANGE         : BUY BLOCK                            SELL BLOCK
    EMERGING_DOWN : BUY BLOCK                            SELL ALLOW
    STRONG_DOWN   : BUY BLOCK                            SELL ALLOW
    UNKNOWN/STALE : BUY BLOCK                            SELL BLOCK

BOUNCE_MEAN_REVERSION family (AMENDED):

    STRONG_UP     : BUY ALLOW                            SELL ALLOW iff
                                                         exhaustion READY
                                                         + FRESH + CONFIRMED
                                                         + BUYING_EXHAUSTION
    ...
```

The counter-trend BOUNCE cell is upgraded from the H1 MACD tiring proxy to the full **Central Exhaustion Detector** verdict (`cache/nms_exhaustion_<SYM>.json`). The exhaustion detector itself is a composition of H1 signals — the MACD-histogram tiring flag is one input, but it also uses BB-width, directional velocity, and H1 EMA posture (lines 439–810 of this module show the inputs).

So in the current production path, counter-trend bounces require:

1. The H1 exhaustion snapshot's `exhaustion_state = CONFIRMED`,
2. `exhaustion_direction` matching the proposed trade side (`BUYING_EXHAUSTION` for SELL into UP; `SELLING_EXHAUSTION` for BUY into DOWN),
3. `readiness = READY`,
4. `freshness = FRESH`.

Missing or stale snapshot → no bounce. The matrix in the docstring is the definitive statement of how the H1-layer exhaustion controls which bounce direction is admissible.

**This surface was not in the earlier audit.**

### 3.3 htf_regime.py — H1/D1/W1 classifier + alignment (telemetry only in production)

File: `/opt/tradingbot/htf_regime.py` (746 lines).

`classify()` at line 650 produces per symbol:

- `h1_state` ∈ {`TRENDING_UP`, `TRENDING_DOWN`, `RANGE`, `COMPRESSION`, `EXPANSION`, `EXHAUSTION`}.
- `h1_strength` (float 0..1, only for `TRENDING_*`).
- `d1_state` ∈ {`UP`, `DOWN`, `SIDEWAYS`, `TURNING`}.
- `w1_state` ∈ {`UP`, `DOWN`, `SIDEWAYS`}.
- `alignment` ∈ {`ALIGNED_BULL`, `ALIGNED_BEAR`, `CONFLICTED`, `NEUTRAL`}.

The alignment rule at lines 617–644:

```
617  def _compute_alignment(h1_state: str, d1_state: str, w1_state: str,
618                         h1_debug: Dict[str, Any]) -> str:
...
633      if w1_state == W1_UP and d1_state == D1_UP and h1_dir_up:
634          return ALIGN_BULL
635      if w1_state == W1_DOWN and d1_state == D1_DOWN and h1_dir_dn:
636          return ALIGN_BEAR
637      if (w1_state == W1_UP and d1_state == D1_DOWN) or \
638         (w1_state == W1_WOWN and d1_state == D1_UP):
...
```

This module is the only place where D1 and W1 are classified anywhere in the NMS stack.

**Does it influence direction?** Only indirectly, and only through the H1 part:

- `classify()` is called by `nms_v3_direction_gate._h1_bias()` at line 276 (§1 above). The admission uses `h1_state` only — D1 and W1 are computed but discarded by that caller.
- `classify()` is also called by `htf_authority._classify_market()` which **would** use D1 and W1 via `_compute_alignment()` — but see §3.4.

So D1 and W1 do **not** change any trade-admission decision under the current flag set.

**This surface was not in the earlier audit.**

### 3.4 htf_authority.py — a full HTF direction gate that is currently dormant

File: `/opt/tradingbot/htf_authority.py` (1,090 lines).

`evaluate(symbol, direction, mode)` at line 690:

```
690  def evaluate(symbol: str, direction: str, mode: str) -> Tuple[bool, str, Dict[str, Any]]:
...
695      Behaviour by flag:
696          HTF_AUTHORITY_ENABLED=1  → classify, decide, log (enforced=True), return
697                                      the decision (may BLOCK).
698          HTF_AUTHORITY_ENABLED=0  → classify, log (enforced=False) with the
699                                      decision the gate WOULD have made, then
700                                      return PASS unconditionally.
```

It is called from `trade_executor.py:3395–3414`:

```
3393      if not _REGIME_MATRIX_ENABLED_TE:
3394          try:
3395              import htf_authority as _hauth
3396              _sym_h = _pair_from_epic(epic)
3397              _dir_h = _safe_str(getattr(decision, "signal", None)).strip().upper()
3398              if _sym_h and _dir_h in ("BUY", "SELL"):
3399                  _ok_h, _reason_h, _ = _hauth.evaluate(_sym_h, _dir_h, mode)
3400                  if not _ok_h:
3401                      logger.info(
3402                          "[HTF-AUTHORITY] BLOCKED %s %s %s — %s",
3403                          _sym_h, _dir_h, mode, _reason_h,
3404                      )
```

In the current production `.env`:

- `HTF_AUTHORITY_ENABLED` is unset → defaults to 0 → `evaluate()` always returns PASS.
- `REGIME_MATRIX_ENABLED` is unset → defaults to 0 → the `if not` branch above is taken, so the call still happens.

So `htf_authority` runs on every execute_trade call, writes a telemetry row to `/opt/tradingbot/logs/htf_authority.jsonl`, and influences nothing. If the operator ever sets `HTF_AUTHORITY_ENABLED=1`, this gate would start blocking on H1/D1/W1 alignment via the `_classify_market` + `_structure_dir` primitives. The new bot should decide whether to adopt any of that logic — but none of it is live today.

### 3.5 QM reversal (qm_reversal_detector) — consumes the same V3 gate

File: `/opt/tradingbot/qm_reversal_detector.py` (not an HTF source itself; a consumer).

`qm_reversal_detector` calls `nms_v3_direction_gate.check()` with a synthesised V3-scoped strategy name so the H1 admission applies to QM reversals as well. Lines 257–269 of that file:

```
257      """Return a V3-scoped strategy name so nms_v3_direction_gate.check
...
261      which is in V3_STRATEGIES per nms_v3_direction_gate.py:52-56."""
...
269          import nms_v3_direction_gate as _nms
```

Live proof in the log snippet at §5: the `QM-REV` fire line records `nms_v3:nms_v3_h1_admission_block:v3=NORMAL:h1=TRENDING_DOWN:side=BUY,blocked_by_nms_v3`. So the H1 admission is actively vetoing QM reversal entries that run counter to H1.

---

## 4. Order of authority — who wins when the 5m view and a higher timeframe disagree

The entry path for a V3-scope strategy (production flags on) is, in order:

1. **5-minute v3_state** at `session_trend.v3_state`, produced by `nms_v3_classifier.advance()` on every 5-minute bar close.
2. **NMS V3 directional check** at `nms_v3_direction_gate.check()` lines 525–541. The 5-minute state wins **immediately** if it is directional:
   - `STRONG_UP` or `EMERGING_UP` → blocks SELL.
   - `STRONG_DOWN` or `EMERGING_DOWN` → blocks BUY.
   - This exits before the H1 is ever consulted.
3. **H1 admission** at the same file, lines 562–610. Only runs if the 5-minute state was `RANGE`, `NORMAL`, `UNKNOWN`, or empty. H1 **wins** in that neutral case:
   - `TRENDING_UP` H1 → blocks SELL.
   - `TRENDING_DOWN` H1 → blocks BUY.
4. **BOUNCE rulebook** (`permit_bounce`) — called only for bounce strategies and only when `DIRECTION_FROM_NMS_SESSION_TREND=1`. The 5-minute v3_state is primary. For counter-trend bounces the exhaustion detector's H1 verdict wins (unified authority on) or the H1 MACD tiring flag wins (unified authority off).
5. **TREND/PULLBACK rulebook** (`permit_trend`) — same precedence as (4): 5-minute v3_state is primary; the rulebook only ADMITS same-direction-as-5m. HTF does not re-enter here (no exhaustion exception for same-direction trend continuation).

**Plain-English statement:** the 5-minute picture always speaks first. If the 5-minute picture names a direction, that answer stands and HTF is ignored. The H1 admission only fires when the 5-minute picture is **neutral** — in that case the 5-minute remains silent and the H1 direction is used to refuse the counter-H1 side. Daily and weekly timeframes have **no current influence** on any live gate.

An operator-level kill-switch inversion of this order is `DIRECTION_FROM_NMS_SESSION_TREND=1` (production): it skips the `trade_executor` V3 check and lets the per-strategy rulebooks run instead, which in turn add the H1 MACD tiring (bounce) and the unified authority matrix (bounce/trend). None of these can override a directional 5-minute v3_state — they can only block a side that the 5-minute state has already left admissible.

---

## 5. Records — where decisions are written and three example lines verbatim

### 5.1 Live log stream

Every call to `nms_v3_direction_gate.check()` emits one INFO line via `_emit_decision()` at lines 363–379:

```
366          logger.info(
367              "[NMS_V3_GATE] strategy=%s side=%s symbol=%s state=%s snapshot_ts=%s "
368              "allowed=%s binding=%s reasons=%s",
...
```

These lines land in `journalctl -u autobot.service`. The `[QM-REV] FIRE ...` lines in the same stream carry the same reason concatenated onto their own log for cross-reference.

### 5.2 Snapshot files

- `/opt/tradingbot/cache/session_trend_<SYM>.json` — primary NMS V3 snapshot. Written atomically by `session_trend._write_snapshot()` on every 5-minute bar close.
- `/opt/tradingbot/cache/h1_macd_tiring_<SYM>.json` — the "tiring" flag the BOUNCE rulebook reads. Written by `h1_macd_tiring_writer.py` on every 5-minute bar close under `DIRECTION_FROM_NMS_SESSION_TREND=1` (that file's line 159).
- `/opt/tradingbot/cache/nms_exhaustion_<SYM>.json` — Central Exhaustion Detector snapshot consumed by the unified authority.
- `/opt/tradingbot/logs/htf_regime.jsonl` — one row per `classify()` emit (under `HTF_REGIME_ENABLED=1`).
- `/opt/tradingbot/logs/htf_authority.jsonl` — one row per `htf_authority.evaluate()` call (shadow or enforced).

### 5.3 Three example decision lines, as they appear in production

Pulled via `journalctl -u autobot.service` on this host.

**Example A — 5-minute state wins (base V3 directional block):**

```
2026-11-06 15:06:00,470 [INFO] [NMS_V3_GATE] strategy=GBPUSD_TREND_V3_UM_L side=BUY symbol=EURUSD state=STRONG_DOWN snapshot_ts=2026-11-06T15:00:00+00:00 allowed=False binding=direction_block reasons=nms_v3_direction_block:state=STRONG_DOWN:side=BUY
```

Reading it: a GBPUSD_TREND_V3_UM_L BUY on EURUSD was blocked because the 5-minute v3_state was `STRONG_DOWN`. The H1 admission was never consulted.

**Example B — 5-minute neutral, H1 admission wins:**

```
2026-11-06 00:10:12,200 [INFO] [NMS_V3_GATE] strategy=GBPUSD_TREND_V3_UM_L side=BUY symbol=USDJPY state=NORMAL snapshot_ts=2026-11-06T00:05:00+00:00 allowed=False binding=h1_admission_block reasons=nms_v3_h1_admission_block:v3=NORMAL:h1=TRENDING_DOWN:side=BUY
```

Reading it: 5-minute state was `NORMAL` (neutral), H1 was `TRENDING_DOWN`, trade side was BUY → blocked by `h1_admission_block`.

**Example C — H1 unavailable, fail-closed:**

```
2026-11-05 19:46:57,887 [INFO] [NMS_V3_GATE] strategy=GBPUSD_TREND_V3_UM_S side=SELL symbol=USDCAD state=RANGE snapshot_ts=2026-11-05T19:40:00+00:00 allowed=False binding=h1_admission_fail_closed reasons=nms_v3_h1_admission_fail_closed:h1_unavailable:stale:close_age_s=6418
```

Reading it: 5-minute state was `RANGE` (neutral). The most recent H1 bar's close was 6,418 s old — past the `NMS_V3_H1_MAX_AGE_S` default of 3,900 s — so H1 was treated as unavailable. Because `NMS_V3_H1_ADMISSION_FAIL_POLICY=closed`, the fire was rejected rather than passed.

A fourth illustrative line showing an H1 pass-through (not required by the brief, but useful for symmetry):

```
2026-11-06 15:06:08,086 [INFO] [NMS_V3_GATE] strategy=GBPUSD_TREND_V3_UM_S side=SELL symbol=USDJPY state=RANGE snapshot_ts=2026-11-06T15:00:00+00:00 allowed=True binding=- reasons=nms_v3_direction_pass:state=RANGE:h1=RANGE
```

5-minute = `RANGE`, H1 = `RANGE` → both neutral → allowed, with H1 state recorded on the reason for audit.

---

## Summary table

| Surface | File | Prod flag state | Uses H1? | Uses H4/D1/W1? | Can change direction? |
| --- | --- | --- | --- | --- | --- |
| 5-min v3 directional gate | nms_v3_direction_gate.py:412 | ENABLED=1 | — | No | Rejects fires only |
| H1 admission | nms_v3_direction_gate.py:562–610 | ADMISSION=1, FAIL_POLICY=closed | Yes (TRENDING_* only) | No | Rejects only |
| Pivot bridge | session_trend_integration.py:47 | implicit (runs on every heartbeat) | No (D1 pivots only as setup) | D1-derived support/resist | Influences establish_* reasons |
| IG daily-% bridge | session_trend_integration.py:113 | runs | No | No (record only) | No |
| BOUNCE rulebook | nms_session_trend_direction.py:302 | DIRECTION_FROM_NMS_SESSION_TREND=1 | Yes (H1 MACD tiring OR unified exhaustion) | No | Rejects only |
| Unified Directional Authority | nms_directional_authority.py | NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1 | Yes (central exhaustion incl. H1 inputs) | No | Rejects only |
| htf_regime.classify | htf_regime.py:650 | HTF_REGIME_ENABLED=1 (telemetry) | Yes | Yes (D1 + W1 classified) | No (telemetry only through its own module) |
| htf_authority.evaluate | htf_authority.py:690 | HTF_AUTHORITY_ENABLED=0 | Yes | Yes (via alignment) | **No** — unconditional PASS under flag OFF |

No code path exists anywhere that converts a BUY proposal into a SELL (or vice versa) based on an HTF reading. Every HTF-informed decision in this codebase is a **block** on the proposed side; the original direction is chosen by the 5-minute strategy alone.

---

End of audit.
