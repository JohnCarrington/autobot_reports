# DEAD_FLAGS.md audit — addendum (2026-08-23)

Follow-up to `/tmp/dead_flags_audit_20260823.md`. Investigate-only, no
edits/commits/service actions. Every claim below is backed by verbatim
grep/cat/sed output.

## Contradictions with the original report

1. **GAP 3 finding revises the addendum's evidence base.** The original
   report cited `/proc/2140308/environ` alongside `.env` and treated the
   two as interchangeable. That is correct **only because** `autobot.py`
   loads `.env` with `python-dotenv` at startup and the file has not
   been touched since. If `.env` is ever edited after startup, the two
   sources will diverge and any classification derived from
   `/proc/…/environ` alone will be describing frozen-at-boot state, not
   current-file state. The original report did not flag that
   dependency. GAP 3 below spells it out.
2. **GAP 1: the two `_bbb_dec … not regime_matrix.REGIME_MATRIX_ENABLED`
   sites at `autobot.py:5097` and `:6657` are inside a nested `if _bbb_dec
   is not None` clause, i.e. the guards call is skipped when BB_BOUNCE
   didn't produce a decision on that bar** (not just when the matrix is
   on). The original report described them as "matrix off → guards run"
   which is true only when there is a decision to guard. Neutral point
   for the classification but the phrasing was loose.
3. **GAP 4: `logs/bb_bounce_standdown.jsonl` contains an event at
   2026-08-21T14:45:00Z suppressing a BB_BOUNCE **LONG** entry.** The
   tonight-harness Row 1 must-fire assertion is "bounce LONG ~14:30 UTC
   ±15 min". 14:45Z is inside that window. This is a direct interaction
   the harness needs to plan for — either the assertion is wrong, the
   standdown must be waived for that fire, or the replay must reproduce
   the standdown (in which case the assertion cannot pass byte-clean).
4. **HTF_AUTHORITY_ENABLED, all HTF_AUTH_* sub-flags, and the
   TREND_GUARD_SHADOW / STRUCTURE_REVERSAL_TREND_GUARD family are
   ALL absent from `.env`.** The original report implied "reader
   reached, effect depends on value" for each — verified in the GAP 2
   table below. Every one runs at its code default. Two of them
   (`HTF_AUTH_NEWS_EXEMPT_ENABLED`, `TREND_GUARD_SHADOW_ENABLED`,
   `STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED`) default to `"1"` and
   therefore *do* actively shape behaviour on every fire that reaches
   them. See GAP 2 highlight list.

---

## GAP 1 — Every `REGIME_MATRIX_ENABLED` veto site, quoted verbatim

Full enumeration of live-path readers (excluding `.claude/`, `_*` scratch,
`tests/`, `2/`, `4h/`, `scripts/`, `reports/`):

```
$ grep -rn "REGIME_MATRIX_ENABLED" /opt/tradingbot --include="*.py" \
    | grep -v -E "\.claude/|/_[a-z]|/tests/|/2/|/4h/|scripts/|/reports/" \
    | grep -E "if|_TE|_TM|not .*REGIME_MATRIX_ENABLED|and "
/opt/tradingbot/gbpusd_bb_bounce.py:2464:        if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:
/opt/tradingbot/trade_manager.py:1608:_REGIME_MATRIX_ENABLED_TM = (
/opt/tradingbot/trade_manager.py:4982:            if _REGIME_MATRIX_ENABLED_TM:
/opt/tradingbot/trade_manager.py:5005:        if _REGIME_MATRIX_ENABLED_TM and RANGE_SCALP_ON_PROMOTION == "ride":
/opt/tradingbot/autobot.py:5097:                    if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
/opt/tradingbot/autobot.py:6657:            if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
/opt/tradingbot/trade_executor.py:151:_REGIME_MATRIX_ENABLED_TE = (
/opt/tradingbot/trade_executor.py:1430:    if not _REGIME_MATRIX_ENABLED_TE:
/opt/tradingbot/trade_executor.py:1457:    if not _REGIME_MATRIX_ENABLED_TE:
/opt/tradingbot/trade_executor.py:1496:    if not _REGIME_MATRIX_ENABLED_TE and os.getenv("CROSS_BIAS_GATE_ENABLED", "1") == "1":
/opt/tradingbot/gbpusd_ema_pullback.py:1740:                if not _REGIME_MATRIX_ENABLED:
/opt/tradingbot/gbpusd_structure_break.py:1156:        if regime in RANGE_REGIMES and not _REGIME_MATRIX_ENABLED:
/opt/tradingbot/gbpusd_trend_v3.py:1278:            if regime not in _up_ok_regimes and not _REGIME_MATRIX_ENABLED:
/opt/tradingbot/gbpusd_trend_v3.py:1292:            if regime not in _dn_ok_regimes and not _REGIME_MATRIX_ENABLED:
/opt/tradingbot/gbpusd_confirmation_fallback.py:439:        if _regime_is_trending(regime) and not _REGIME_MATRIX_ENABLED:
/opt/tradingbot/gbpusd_confirmation_fallback.py:698:if _REGIME_MATRIX_ENABLED:
/opt/tradingbot/autobot.py:8021:            _guards_gated = regime_matrix.REGIME_MATRIX_ENABLED
```

15 unique live-path evaluation sites. Since `REGIME_MATRIX_ENABLED` is
falsy at HEAD `d5d3c6a` (both `.env` absent and `/proc/2140308/environ`
absent — see GAP 3), for each site I state what the code does with the
current value.

### Class A — `if not _REGIME_MATRIX_ENABLED_TE:` wraps a block

`trade_executor.py:1430` (HTF-authority) — falsy matrix ⇒ `if not False`
= True ⇒ **block executes**:

```
1425	    # ------------------------------------------------------------
1426	    # HTF-authority gate (2026-06-04). Under REGIME_MATRIX_ENABLED=1
1427	    # the matrix owns enablement — this gate is gated off. Module
1428	    # stays on disk this phase per spec §D.
1429	    # ------------------------------------------------------------
1430	    if not _REGIME_MATRIX_ENABLED_TE:
1431	        try:
1432	            import htf_authority as _hauth
1433	            _sym_h = _pair_from_epic(epic)
1434	            _dir_h = _safe_str(getattr(decision, "signal", None)).strip().upper()
1435	            if _sym_h and _dir_h in ("BUY", "SELL"):
1436	                _ok_h, _reason_h, _ = _hauth.evaluate(_sym_h, _dir_h, mode)
1437	                if not _ok_h:
1438	                    logger.info(
1439	                        "[HTF-AUTHORITY] BLOCKED %s %s %s — %s",
1440	                        _sym_h, _dir_h, mode, _reason_h,
1441	                    )
1442	                    _set_block_info("HTF_AUTHORITY", str(_reason_h))
1443	                    return None
1444	                logger.debug(
1445	                    "[HTF-AUTHORITY] PASS %s %s %s — %s",
1446	                    _sym_h, _dir_h, mode, _reason_h,
1447	                )
1448	        except Exception as _hauth_exc:
1449	            ...
```

Verdict: **falls THROUGH into the block**. Every fire attempt for
BUY/SELL directions triggers `_hauth.evaluate()`.

`trade_executor.py:1457` (Conviction gate) — same shape, same verdict:

```
1453	    # ------------------------------------------------------------
1454	    # Conviction gate (2026-05-29). Gated off under the matrix per
1455	    # spec §D. Module stays on disk this phase.
1456	    # ------------------------------------------------------------
1457	    if not _REGIME_MATRIX_ENABLED_TE:
1458	        try:
1459	            import conviction_gate as _cg
1460	            ...
1463	                _ok, _reason, _details = _cg.evaluate(_sym_cg, _dir_cg, mode)
1464	                if not _ok:
1465	                    ...
1476	                _ok2, _reason2, _ = _cg.evaluate_direction(_sym_cg, _dir_cg, mode)
1477	                if not _ok2:
1478	                    ...
```

Verdict: **falls THROUGH**. `conviction_gate.evaluate()` and
`.evaluate_direction()` both run every fire attempt.

`trade_executor.py:1496` (cross-bias) — one-line AND with the flag
short-circuit:

```
1492	    # ------------------------------------------------------------
1493	    # CROSS-STRATEGY DIRECTIONAL BIAS GATE (2026-07-08). Gated off
1494	    # under the matrix per spec §D.
1495	    # ------------------------------------------------------------
1496	    if not _REGIME_MATRIX_ENABLED_TE and os.getenv("CROSS_BIAS_GATE_ENABLED", "1") == "1":
1497	        try:
1498	            _sym_b = _pair_from_epic(epic)
```

Verdict: matrix off ⇒ first term True ⇒ **second term IS evaluated**.
`.env:794: CROSS_BIAS_GATE_ENABLED=0` ⇒ the AND is False ⇒ block does
NOT execute. Gate is inert **because of the flag, not the matrix**.

### Class B — autobot.py `_bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED`

`autobot.py:5097` (BB_BOUNCE guards, tick-path):

```
5082	                    # classifier can suppress a fire. If the regime classifier
5083	                    # is later wired to gate other fade-class strategies, a
5084	                    # mode-bypass for GBPUSD_BB_BOUNCE_L/_S must be added there.
5085	
5086	                    # Guards (2026-05-02 wireup) — observable-only by default.
5087	                    ...
5091	                    # autobot.py:3547-3569. strategy_mode = "GBPUSD_BB_BOUNCE"
5092	                    # (no L/S suffix) to match the registry key. Direction +
5093	                    ...
5097	                    if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
5098	                        # GUARDS observable-mode gated off under matrix per
5099	                        # Phase 2 spec §D. news_release_window.py continues to
5100	                        # enforce entry-time blackout inside each strategy.
5101	                        try:
5102	                            from guards import check_trade as _bbb_guards_check
5103	                            _bbb_dir = str(getattr(_bbb_dec, "signal", "")).upper()
...
5115	                            _bbb_g_blocked, _bbb_g_reason = _bbb_guards_check(
5116	                                symbol=sym_u,
5117	                                direction=_bbb_dir,
5118	                                strategy_mode="GBPUSD_BB_BOUNCE",
```

Verdict: matrix off ⇒ **second AND term True**. Block runs *when there
is a BB_BOUNCE decision on the current bar* (first AND term). This is
the site through which `GUARD_LEVELS_PROXIMITY_ENABLED` reader is
actually reached.

`autobot.py:6657` (BB_BOUNCE guards, close-callback path):

```
6652	            # Guards (mirrors tick-path autobot.py:4102-4138). current_mid is
6653	            # the just-closed bar's close — the most recent confirmed price
6654	            # at this dispatch point. Same semantics as the tick-path mid_f
6655	            # for the levels_proximity / news_blackout / priced_in checks.
6656	            _mid_for_guards = float(df["close"].iloc[-1])
6657	            if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
6658	                # GUARDS observable-mode gated off under matrix per §D.
6659	                try:
6660	                    from guards import check_trade as _bbb_guards_check
```

Same shape and same verdict.

### Class C — autobot.py `_guards_gated = regime_matrix.REGIME_MATRIX_ENABLED`

`autobot.py:8021` (TREND_V3 guards):

```
8020	            _mid = float(df["close"].iloc[-1])
8021	            _guards_gated = regime_matrix.REGIME_MATRIX_ENABLED
8022	            try:
8023	                if _guards_gated:
8024	                    raise ImportError("guards observable gated off under matrix (§D)")
8025	                from guards import check_trade as _g_check
8026	                _dir = str(getattr(_dec, "signal", "")).upper()
```

Verdict: matrix off ⇒ `_guards_gated = False` ⇒ `if _guards_gated`
skipped ⇒ **`guards.check_trade` DOES run for TREND_V3**. Note however
that `guards/registry.py:12-22` does not have a `"GBPUSD_TREND_V3"`
key — `get_guards_for("GBPUSD_TREND_V3")` returns `[]` and no guards
actually fire. Reader is reached but produces a no-op verdict; the
`GUARD_LEVELS_PROXIMITY_ENABLED` reader is NOT reached through this
site.

### Class D — flag-first AND

`gbpusd_bb_bounce.py:2464` (STRONG_TREND standdown):

```
2449	        # ── STRONG_TREND stand-down (2026-06-29) ─────────────────────────
2450	        # Consume regime_engine.latest_result — the SAME authority
2451	        # EMA_PULLBACK / CONFIRMATION_FALLBACK read. Stand down when this
2452	        # fire would fade a STRONG confirmed trend:
2453	        #   STRONG_TREND_UP + SHORT  → suppress (fading the up-trend)
2454	        #   STRONG_TREND_DOWN + LONG → suppress (fading the down-trend)
2455	        ...
2464	        if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:
2465	            try:
2466	                import regime_engine as _re
2467	                _rg = _re.latest_result("GBPUSD") or {}
2468	                _winning = str(_rg.get("winning_regime") or "").upper()
```

Verdict: `BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED` default `"1"` (not
in .env), matrix off ⇒ **both AND terms True ⇒ block runs on every
BB_BOUNCE evaluation**. This is the direct cause of the 72 events in
`logs/bb_bounce_standdown.jsonl` (see GAP 4).

### Class E — strategy-local regime gates

`gbpusd_ema_pullback.py:1740`:

```
1725	            # requirement. No EMA fan/slope pip number anywhere on this
1726	            # path — H1 EMA fan on GBPUSD is sub-pip and unsuited to a
1727	            # pip floor. Fail-CLOSED on missing/unknown regime.
1728	            _reg = _ema_pb_read_regime_label(symbol)
1729	            if EMA_PB_REGIME_REQUIRE_STRONG:
1730	                _long_ok  = _reg in _EMA_PB_LONG_REGIMES_STRICT
1731	                _short_ok = _reg in _EMA_PB_SHORT_REGIMES_STRICT
1732	                _mode     = "strict"
1733	            else:
1734	                _long_ok  = _reg in _EMA_PB_LONG_REGIMES_WIDE
1735	                _short_ok = _reg in _EMA_PB_SHORT_REGIMES_WIDE
1736	                _mode     = "wide"
1737	            # Under the matrix (REGIME_MATRIX_ENABLED=1) the effective_regime
1738	            # decides enablement; this local strict-STRONG check is bypassed.
1739	            if (is_bull and not _long_ok) or (is_bear and not _short_ok):
1740	                if not _REGIME_MATRIX_ENABLED:
1741	                    _ema_pb_pbfix_log({
1742	                        "ts": cur_bar.timestamp.isoformat(),
1743	                        "verdict": "REJECT",
1744	                        "reason": "regime_not_strong_trend",
1745	                        "direction": ("LONG" if is_bull else "SHORT"),
1746	                        "winning_regime": _reg,
1747	                        "regime_matrix_flag": None,
1748	                    })
1749	                    return None, f"regime_not_strong_trend regime={_reg} mode={_mode}"
```

Verdict: matrix off ⇒ inner `if not False` ⇒ **regime reject fires
normally, returns None**. Under matrix on, the outer regime mismatch
would be silently ignored and the fire would proceed. So the strategy
IS enforcing the STRONG-regime requirement at HEAD `d5d3c6a`.

`gbpusd_trend_v3.py:1278` and `:1292` (matched pair for UP / DOWN):

```
1257	        # ── Regime gate ──
1258	        # Under REGIME_MATRIX_ENABLED=1 the effective_regime → permitted-set
1259	        # decision is owned by regime_matrix; the strict-STRONG_TREND check
1260	        # here is bypassed. Slot / direction assignment is unaffected.
...
1272	        _up_ok_regimes = {"STRONG_TREND_UP"}
1273	        _dn_ok_regimes = {"STRONG_TREND_DOWN"}
1274	        if _grind_widening_active:
1275	            _up_ok_regimes = _up_ok_regimes | {"TREND_FORMING_UP"}
1276	            _dn_ok_regimes = _dn_ok_regimes | {"TREND_FORMING_DOWN"}
1277	        if effective_dir == "UP":
1278	            if regime not in _up_ok_regimes and not _REGIME_MATRIX_ENABLED:
1279	                self._log_block("regime_not_strong_up", daily=daily_dbg,
...
1291	        else:  # DOWN
1292	            if regime not in _dn_ok_regimes and not _REGIME_MATRIX_ENABLED:
1293	                self._log_block("regime_not_strong_down", daily=daily_dbg,
```

Verdict: matrix off ⇒ **regime-not-strong reject fires normally**.
Matches the `trend_v3.jsonl` block reasons `regime_not_strong_up`
(1840 hits) and `regime_not_strong_down` (775 hits) observed in the
prior investigation.

`gbpusd_structure_break.py:1156`:

```
1148	        # Regime gate (whipsaw guard).
1149	        # Gate A only: RANGE/CHOP fail. Bypassed under REGIME_MATRIX_ENABLED
1150	        # (matrix owns enablement). Gate B (ADX floor) and Gate C (retest
1151	        # routing) are setup mechanics and remain enforced regardless of
1152	        # the matrix flag.
1153	        regime, adx = self._regime_and_adx(symbol)
1154	        if regime is None:
1155	            return None, "regime_unavailable"
1156	        if regime in RANGE_REGIMES and not _REGIME_MATRIX_ENABLED:
1157	            logger.info(...)
1158	            return None, f"regime_blocks={regime}"
```

Verdict: matrix off ⇒ **RANGE/CHOP structure-break entries blocked**.

`gbpusd_confirmation_fallback.py:439`:

```
431	        # ── Regime self-gate ──────────────────────────────────────────────
432	        # Legacy role: fire only in non-trending regimes; disarm setups when
433	        # a trend emerges. Under REGIME_MATRIX_ENABLED=1 this role inverts —
434	        # matrix assigns CF to trending regimes and owns dispatch. The
435	        # disarm-on-transition invariant is preserved via a matrix
436	        # on-suppress callback registered at module load (see bottom of
437	        # file); this local block is bypassed under the flag.
438	        regime = _read_regime_label(symbol)
439	        if _regime_is_trending(regime) and not _REGIME_MATRIX_ENABLED:
440	            _write_shadow({
441	                "ts": ts.isoformat(),
442	                "epic": epic,
443	                "phase": "STAND_DOWN",
444	                "reason": "regime_trending",
445	                "regime": regime,
446	            })
447	            # Clear any armed state — a trend has emerged, this strategy
448	            # is no longer the right tool for this bar.
449	            self._armed.pop(epic, None)
450	            return None
```

Verdict: matrix off ⇒ **confirmation_fallback stands down on trending
regimes and clears armed state**.

### Class F — module-load conditionals

`gbpusd_confirmation_fallback.py:698`:

```
685	# REGIME_MATRIX_ENABLED=1 the gate is bypassed, so the disarm is
686	# reinstated via a matrix on-suppress callback that fires when either CF
687	# mode leaves the effective_regime's permitted set on a transition.
688	def _cf_matrix_disarm(_symbol):  # pragma: no cover — exercised by test
689	    """Clear all armed CF setups on any matrix suppression event for this
690	    strategy. Safe to call more than once; idempotent.
691	    """
692	    try:
693	        strategy._armed.clear()
694	    except Exception:
695	        pass
696	
697	
698	if _REGIME_MATRIX_ENABLED:
699	    try:
700	        import regime_matrix as _rm
701	        _rm.register_on_suppress(MODE_NAME_LONG, _cf_matrix_disarm)
702	        _rm.register_on_suppress(MODE_NAME_SHORT, _cf_matrix_disarm)
```

Verdict: matrix off at import time ⇒ **CF matrix-disarm callback NOT
registered**. Not a runtime hot-path but a live divergence from the
matrix-on behaviour.

### Class G — trade_manager sites

`trade_manager.py:4982` and `:5005` — both are `if _REGIME_MATRIX_ENABLED_TM:`
(the positive form). Matrix off ⇒ **block SKIPPED**. These sites are
the RANGE-scalp exit rework blocks:

```
$ sed -n '4975,4990p' /opt/tradingbot/trade_manager.py
```

Not quoted at length because the operator's classification scope is the
per-flag reader reachability; here matrix off = branch skipped ⇒ the
`RANGE_SCALP_ON_PROMOTION == "ride"` reader on line 5005 is NEVER
reached. Live behaviour is the legacy pre-Phase-2 exit path.

### Aggregate verdict for GAP 1

Of the 15 live-path evaluation sites:

| Class | Sites | Effect at `REGIME_MATRIX_ENABLED=0` |
|-------|-------|---------------------------------------|
| A — `if not _..._TE:` before a block | trade_executor.py:1430, :1457, :1496 | Falls through; downstream readers reached (`_hauth.evaluate`, `_cg.evaluate`, and cross-bias getenv). |
| B — nested with `_bbb_dec is not None` | autobot.py:5097, :6657 | Falls through *when a BB_BOUNCE decision exists on this bar*; BB_BOUNCE guards check_trade reached. |
| C — `_guards_gated = matrix` | autobot.py:8021 | Guards check_trade reached for TREND_V3, but registry returns `[]` for that mode ⇒ no per-guard reader reached. |
| D — `flag AND not matrix` | gbpusd_bb_bounce.py:2464 | Both True (flag default 1) ⇒ standdown block runs. |
| E — strategy-local `if regime-mismatch and not matrix` | ema_pullback:1740, trend_v3:1278/1292, structure_break:1156, confirmation_fallback:439 | Strategy's own regime reject fires normally. |
| F — module-load `if matrix:` | confirmation_fallback:698 | Callback registration skipped. |
| G — positive-form `if _..._TM:` | trade_manager.py:4982, :5005 | Branch skipped; downstream readers on lines 5005ff never reached. |

**Not a mixed verdict.** Every "fall through" site does what the
addendum's headline claimed, and every "skip" site is a positive-form
`if` where the flag being false means the matrix-only branch is
bypassed — the legacy code path either runs *instead* (classes A/D/E)
or nothing runs (classes C/F/G). The original report's classification
of the HTF authority / conviction-gate / cross-bias / strategy-regime
sites is correct.

---

## GAP 2 — HTF_AUTH_* + TREND_GUARD family: values, defaults, effects

### Highlight — flags that are effectively truthy AND reader is reached per fire

At HEAD `d5d3c6a`, live PID `2140308`, matrix off:

| Flag | Effective value | Where reached | Effect if truthy |
|------|-----------------|---------------|------------------|
| `HTF_AUTH_NEWS_EXEMPT_ENABLED` | **1** (code default) | `htf_authority.py:861` in `evaluate()` — per fire attempt via `trade_executor.py:1436` | For NEWS_STRATEGY_* modes, overrides any prior BLOCK verdict to PASS (news catalyst governs). Visible in log as `PASS:HTF_EXEMPT:NEWS_STRATEGY:...`. Currently effect-free because `HTF_AUTHORITY_ENABLED=0` runs the whole gate in SHADOW mode — but the exemption line **does** rewrite `would_reason` in the telemetry. |
| `TREND_GUARD_SHADOW_ENABLED` | **1** (code default) | `conviction_gate.py:433` in the same evaluation each fire attempt via `trade_executor.py:1463` | Writes one row to `logs/trend_guard_shadow.jsonl` per reversal-mode fire attempt. Pure telemetry — never blocks. |
| `STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED` | **1** (code default) | `conviction_gate.py:383` | Chooses between `slope_block` (default) and `level_only_block` as the `active_block` verdict. Only matters when `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED=1`, which is default 0 — see below. |

### Full HTF_AUTH_* + TREND_GUARD table

| Flag | `.env` line | `/proc/2140308/environ` | Code default (file:line) | Effective runtime value | One-line effect at call site (citation) |
|------|-------------|-------------------------|--------------------------|-------------------------|------------------------------------------|
| `HTF_AUTHORITY_ENABLED` | ABSENT | ABSENT | `"0"` at `htf_authority.py:708` and `:1058` | 0 | Truthy would flip `evaluate()`'s return from `PASS + "SHADOW(...)"` to the real `(would_pass, would_reason)` — i.e. authority veto starts blocking fires (`htf_authority.py:988-992`). |
| `HTF_AUTH_STRUCTURE_LEADS_ENABLED` | ABSENT | ABSENT | `"0"` at `htf_authority.py:538` and `:1059` | 0 | Truthy replaces the D1/W1-confirmed direction with `structure_dir` from the most recent N-bar flip, forcing `call="TREND"` and `authority_direction=structure_dir` (`htf_authority.py:557-568`). Reshapes what `evaluate()`'s SHADOW row records as the "would" verdict. |
| `HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED` | ABSENT | ABSENT | `"0"` at `htf_authority.py:539` and `:1061` | 0 | Modifies the structure-leads override so RANGE calls are NOT converted to TREND (stand-down instead) — `htf_authority.py:552-556, 569-574`. |
| `HTF_AUTH_STRUCT_EXEMPT_ENABLED` | ABSENT | ABSENT | `"0"` at `htf_authority.py:891` and `:1060` | 0 | Rescues would-BLOCKED reversal fires whose structure-leads flip matched, if the exemption RSI-divergence rule passes (`htf_authority.py:906-915`). |
| `HTF_AUTH_NEWS_EXEMPT_ENABLED` | ABSENT | ABSENT | **`"1"`** at `htf_authority.py:861` | **1** | For any NEWS_STRATEGY_* mode: forces `would_pass=True` regardless of the RANGE/TREND branch's verdict; logs `[HTF-AUTHORITY] NEWS_STRATEGY exempt FIRED` (`htf_authority.py:860-873`). |
| `HTF_AUTH_ADX_OVERRIDE_ENABLED` | ABSENT | ABSENT | `"0"` at `htf_authority.py:589` | 0 | When `call=="RANGE"`, promotes to `TREND` if 5M ADX ≥ `HTF_AUTH_ADX_TREND_FLOOR` (default 25) and direction resolves via structure/regime_engine bias (`htf_authority.py:588-...`). |
| `HTF_AUTH_DRIFT_PIPS_MIN` (numeric) | ABSENT | ABSENT | `15.0` at `htf_authority.py:465` (and `:1025` for shadow-thresh) | 15.0 | Minimum H1-window net-pip drift for the drift-override to consider promoting RANGE→TREND direction — always read per fire (`htf_authority.py:465-475`). |
| `HTF_AUTH_EFF_RATIO_MIN` (numeric) | ABSENT | ABSENT | `0.08` at `htf_authority.py:466` (and `:1026` for shadow-thresh) | 0.08 | Companion efficiency-ratio floor for the drift override — always read per fire. |
| `TREND_GUARD_SHADOW_ENABLED` | ABSENT | ABSENT | **`"1"`** at `conviction_gate.py:433` | **1** | Writes one row to `logs/trend_guard_shadow.jsonl` per reversal-mode conviction-gate evaluation (`conviction_gate.py:433-454`). Never blocks. |
| `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED` | ABSENT | ABSENT | `"0"` at `conviction_gate.py:325` | 0 | Master enforce for the reversal-into-STRONG-TREND block; truthy AND `active_block=True` returns `(False, "reversal_trend_guard_blocked_..")` from `_gate_reversal_trend`, blocking the fire (`conviction_gate.py:468-490` region). |
| `STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED` | ABSENT | ABSENT | **`"1"`** at `conviction_gate.py:383` | **1** | Selects `active_block = slope_block` (default) instead of `level_only_block` — allows a level-only would-block to be vetoed when ADX slope has fallen ≥ `TREND_GUARD_ADX_SLOPE_DELTA` over `TREND_GUARD_ADX_LOOKBACK` bars (`conviction_gate.py:383-399`). Only visible when `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED=1` because otherwise `_gate_reversal_trend` returns early at `:468 "reversal_trend_guard_disabled_log_only"`. |

**Net for the HTF_AUTH_* / TREND_GUARD family under the current
config:** three flags — `HTF_AUTH_NEWS_EXEMPT_ENABLED`,
`TREND_GUARD_SHADOW_ENABLED`, `STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED`
— are effectively ON and their readers ARE reached on every applicable
fire attempt. The first shapes SHADOW telemetry for news-strategy
fires; the second is a pure-logging telemetry write; the third only has
observable effect when the master `STRUCTURE_REVERSAL_TREND_GUARD_ENABLED`
also flips on. Everything else in the family is OFF at default 0.

---

## GAP 3 — Config staleness (file vs process, and env-load mechanism)

### Timestamps

```
$ stat -c '%y  %s bytes' /opt/tradingbot/.env
2026-08-22 21:08:35.949651106 +0000  42976 bytes
$ ps -o lstart= -p 2140308
Sat Aug 22 21:11:17 2026
$ date -u '+%Y-%m-%d %H:%M:%S UTC'
2026-08-23 11:15:00 UTC
```

`.env` mtime is **2026-08-22 21:08:35 UTC**; process start is
**2026-08-22 21:11:17 UTC** (2m 42s later). `.env` has **not** been
modified since PID `2140308` was launched. **File state and process
state are congruent for this audit — no divergence to reconcile.**

Consequence: every classification in the original audit and every
addendum classification below is describing **both** file state and
process state simultaneously, because they are identical. If `.env`
is edited later without a restart, all classifications derived from
values (as opposed to reader reachability, which is a code property)
would need re-verification.

### Env-load mechanism

The systemd unit does source `.env` (`EnvironmentFile=` in
`/etc/systemd/system/autobot.service`, verified in the original
report). It is NOT the only load mechanism — `autobot.py` also loads
it internally via python-dotenv, and does so with `override=True`:

```
$ sed -n '45,57p' /opt/tradingbot/autobot.py
45	from dotenv import load_dotenv
46	
47	# ------------------------------------------------------------
48	# #83: LOAD ENV BEFORE IMPORTING ENV-DEPENDENT MODULES
49	# override=True (2026-05-27): python-dotenv correctly strips trailing
50	# inline `# comment` text on KEY=value lines; systemd's EnvironmentFile
51	# parser does NOT. With override=True, python-dotenv's clean parse
52	# OVERWRITES systemd's polluted environ values on startup, immunising
53	# the bot against any inline-comment pollution in .env (root cause of
54	# the 2026-05-27 GBPUSD_TREND_SELF_DISPATCH=1 silently-OFF incident).
55	# ------------------------------------------------------------
56	load_dotenv(override=True)
```

That `override=True` mutates `os.environ` after startup — but only
once, at process start (module-load time). Subsequent `.env` edits do
not propagate. So `/proc/2140308/environ` is a **snapshot of the
python-dotenv-parsed** `.env` at 2026-08-22 21:11:17 UTC, not a
current-file mirror.

**Cross-check:** a sample of values compared between the two sources
matches:

```
$ tr '\0' '\n' < /proc/2140308/environ | grep -E "^CROSS_BIAS_GATE_ENABLED=|^GUARD_LEVELS_PROXIMITY_ENABLED="
GUARD_LEVELS_PROXIMITY_ENABLED=1
CROSS_BIAS_GATE_ENABLED=0

$ grep -nE "^CROSS_BIAS_GATE_ENABLED=|^GUARD_LEVELS_PROXIMITY_ENABLED=" /opt/tradingbot/.env
629:GUARD_LEVELS_PROXIMITY_ENABLED=1
794:CROSS_BIAS_GATE_ENABLED=0
```

Congruent.

**Explicit statement.** For this audit's classifications:

* File state and process state are identical **right now** because
  `.env` mtime precedes process start and has not been touched since.
* Reader reachability claims (all "PRESENT-LIVE" / "PRESENT-DEAD"
  verdicts) are FILE-state claims — they depend on code at HEAD
  `d5d3c6a` and do not depend on `.env` values.
* Value-derived claims (all "PRESENT-GATED (own flag, value X)"
  verdicts and every value column in the tables) are simultaneously
  FILE-state (from `.env` at rest) and PROCESS-state (from
  `/proc/…/environ`). If `.env` were edited without a restart, these
  would need re-tagging as FILE-only.

---

## GAP 4 — `logs/bb_bounce_standdown.jsonl` full readout

```
$ wc -l /opt/tradingbot/logs/bb_bounce_standdown.jsonl
72 /opt/tradingbot/logs/bb_bounce_standdown.jsonl
```

**File is 72 lines** (small; full contents quotable). Schema is
constant across all rows: `{ts_utc, symbol, pair, strategy, mode,
direction, intended_direction, winning_regime, regime_label_path,
regime_struct_promoted, regime_confidence_final,
regime_directional_bias, setup_price, gate_enabled, verdict, reason}`.
Every row has `verdict:"BLOCKED"`, `reason:"strong_trend_standdown"`,
`gate_enabled:true`, and suppresses a fade against a `winning_regime`
that is either `STRONG_TREND_UP` (SHORT suppression) or
`STRONG_TREND_DOWN` (LONG suppression).

### Distribution by date, direction and regime

| Date | Rows | Suppressed direction × regime |
|------|-----:|--------------------------------|
| 2026-07-02 | 6 | 6× SELL vs STRONG_TREND_UP |
| 2026-07-03 | 1 | 1× SELL vs STRONG_TREND_UP |
| 2026-07-06 | 6 | 5× BUY vs STRONG_TREND_DOWN, 1× SELL vs STRONG_TREND_UP |
| 2026-07-07 | 5 | 5× BUY vs STRONG_TREND_DOWN |
| 2026-07-08 | 4 | 3× BUY vs STRONG_TREND_DOWN, 1× SELL vs STRONG_TREND_UP |
| 2026-07-24 | 2 | 2× SELL vs STRONG_TREND_UP |
| 2026-07-27 | 3 | 3× BUY vs STRONG_TREND_DOWN |
| 2026-07-28 | 6 | 6× SELL vs STRONG_TREND_UP |
| 2026-07-29 | 2 | 2× BUY vs STRONG_TREND_DOWN |
| 2026-07-30 | 5 | 5× SELL vs STRONG_TREND_UP |
| 2026-07-31 | 2 | 2× BUY vs STRONG_TREND_DOWN |
| 2026-08-03 | 5 | 5× BUY vs STRONG_TREND_DOWN |
| 2026-08-04 | 4 | 4× SELL vs STRONG_TREND_UP |
| 2026-08-05 | 4 | 4× SELL vs STRONG_TREND_UP |
| 2026-08-10 | 1 | 1× SELL vs STRONG_TREND_UP |
| 2026-08-11 | 2 | 2× SELL vs STRONG_TREND_UP |
| 2026-08-12 | 2 | 2× BUY vs STRONG_TREND_DOWN |
| 2026-08-13 | 2 | 2× SELL vs STRONG_TREND_UP |
| 2026-08-14 | 3 | 3× SELL vs STRONG_TREND_UP |
| 2026-08-18 | 1 | 1× SELL vs STRONG_TREND_UP |
| 2026-08-19 | 3 | 3× SELL vs STRONG_TREND_UP |
| 2026-08-20 | 1 | 1× SELL vs STRONG_TREND_UP |
| **2026-08-21** | **1** | **1× BUY vs STRONG_TREND_DOWN — see harness alert below** |

Total: **72 suppression events across 23 dates**, 2026-07-02 → 2026-08-21.

### ★ 2026-08-21 event — RELEVANT TO TONIGHT'S HARNESS ROW 1 ★

Row 1 of tonight's conformance harness targets 2026-08-21 with the
must-fire assertion *"bounce LONG ~14:30 UTC ±15 min"*. The file
contains ONE 08-21 row and it falls INSIDE that window:

```
72	{"ts_utc": "2026-08-21T14:45:00Z", "symbol": "GBPUSD", "pair": "GBPUSD",
        "strategy": "GBPUSD_BB_BOUNCE", "mode": "GBPUSD_BB_BOUNCE_L",
        "direction": "BUY", "intended_direction": "LONG",
        "winning_regime": "STRONG_TREND_DOWN", "regime_label_path": "struct",
        "regime_struct_promoted": true, "regime_confidence_final": 0.0172,
        "regime_directional_bias": "SHORT", "setup_price": 13625.55,
        "gate_enabled": true, "verdict": "BLOCKED",
        "reason": "strong_trend_standdown"}
```

**No suppression events on 08-21 in the 07:30-15:00 window other than
this one.** The 14:45Z suppression is at the far end of Row 1's
*~14:30 UTC ±15 min* window; earlier Row 1 must-fire windows (~08:00
UTC bounce LONG, ~09:00 UTC bounce SHORT) do NOT overlap any 08-21
suppression row.

---

## A6 — Operator ruling on Row 1 third must-fire

Operator ruling (verbatim intent): the ~25p bounce was valid, the
market was range-like from ~14:00, STRONG_TREND_DOWN at 14:45Z is a
misclassification. Keep the must-fire; if replay reproduces the
suppression, mark row TESTED-FAIL with root cause
`REGIME_MISCLASSIFICATION`. Do not weaken the assertion.

Pre-flight investigation of the live 2026-08-21 telemetry follows so
the harness has a locked-in comparison target.

### (a) Full per-bar regime label sequence, 13:30 → 16:00 UTC

Source: `/opt/tradingbot/logs/regime_engine.jsonl`, filtered for
`symbol=="GBPUSD"`, timestamp in `[2026-08-21T13:30, 2026-08-21T16:00]`.
31 rows (one per 5-minute bar, all with unique `regime_instance_id`).

| Bar (UTC) | winning_regime | conf_final | ADX | +DI | −DI | adx_slope | EMA_state | directional_bias | regime_instance_id (tail) |
|-----------|----------------|-----------:|----:|----:|----:|----------:|-----------|------------------|---------------------------|
| 13:30:00 | STRONG_TREND_DOWN | 0.0170 | 31.95 | 9.51 | 30.45 | — | BEAR_ALIGNED | SHORT | `_f1a3b277` |
| 13:35:01 | STRONG_TREND_DOWN | 0.0170 | 33.17 | 9.91 | 29.04 | — | BEAR_ALIGNED | SHORT | `_ade3edc8` |
| 13:40:00 | STRONG_TREND_DOWN | 0.0170 | 33.54 | 12.13 | 27.23 | — | BEAR_ALIGNED | SHORT | `_4cc5f729` |
| 13:45:02 | STRONG_TREND_DOWN | 0.0170 | 33.74 | 12.09 | 25.85 | — | BEAR_ALIGNED | SHORT | `_6a00cf87` |
| 13:50:00 | STRONG_TREND_DOWN | 0.0170 | 33.14 | 14.33 | 24.10 | — | BEAR_ALIGNED | SHORT | `_90f5d828` |
| 13:55:00 | **RANGE_ROTATION** | 0.0170 | 31.64 | 17.48 | 22.31 | — | BEAR_ALIGNED | NEUTRAL_BIAS | `_ecfe099f` |
| 14:00:00 | **RANGE_ROTATION** | 0.0170 | 29.51 | 19.90 | 20.61 | — | BEAR_ALIGNED | NEUTRAL_BIAS | `_e5372574` |
| 14:05:00 | **RANGE_ROTATION** | 0.0172 | 28.37 | 18.41 | 24.24 | — | BEAR_ALIGNED | NEUTRAL_BIAS | `_7cec459a` |
| 14:10:00 | STRONG_TREND_DOWN | 0.0172 | 27.78 | 16.47 | 24.74 | — | BEAR_ALIGNED | SHORT | `_20b1d6c0` |
| 14:15:00 | STRONG_TREND_DOWN | 0.0172 | 27.23 | 15.81 | 23.75 | — | BEAR_ALIGNED | SHORT | `_a442dfe4` |
| 14:20:01 | **RANGE_ROTATION** | 0.0172 | 25.90 | 19.09 | 22.70 | −3.60 | BEAR_ALIGNED | NEUTRAL_BIAS | `_e7560205` |
| **14:25:00** | **STRONG_TREND_DOWN** | 0.0172 | 25.67 | 17.43 | 27.68 | −2.70 | BEAR_ALIGNED | SHORT | `_8a613baa` |
| 14:30:00 | STRONG_TREND_DOWN | 0.0172 | 25.92 | 16.03 | 29.19 | −1.86 | BEAR_ALIGNED | SHORT | `_16bbae35` |
| 14:35:00 | STRONG_TREND_DOWN | 0.0172 | 27.20 | 14.32 | 36.72 | — | BEAR_ALIGNED | SHORT | `_220ebc36` |
| 14:40:01 | STRONG_TREND_DOWN | 0.0172 | 28.99 | 12.78 | 40.74 | — | BEAR_ALIGNED | SHORT | `_56459183` |
| **14:45:00** | **STRONG_TREND_DOWN** | 0.0172 | 30.71 | 11.31 | 36.94 | +5.04 | BEAR_ALIGNED | SHORT | `_766a55d4` ← consulted by the standdown |
| 14:50:00 | STRONG_TREND_DOWN | 0.0172 | 32.31 | 10.63 | 34.71 | — | BEAR_ALIGNED | SHORT | `_3cec457d` |
| 14:55:00 | STRONG_TREND_DOWN | 0.0172 | 32.51 | 15.27 | 31.74 | — | BEAR_ALIGNED | SHORT | `_3342d49a` |
| 15:00:00 | STRONG_TREND_DOWN | 0.0172 | 33.14 | 14.30 | 34.42 | — | BEAR_ALIGNED | SHORT | `_ce1d3f0b` |
| 15:05:00 | STRONG_TREND_DOWN | 0.0942 | 33.03 | 16.42 | 31.65 | — | BEAR_ALIGNED | SHORT | `_b0202de0` |
| 15:10:00 | STRONG_TREND_DOWN | 0.0942 | 32.91 | 15.25 | 29.16 | — | BEAR_ALIGNED | SHORT | `_147007e7` |
| 15:15:00 | STRONG_TREND_DOWN | 0.0942 | 32.80 | 14.34 | 27.42 | — | BEAR_ALIGNED | SHORT | `_6f94885a` |
| 15:20:00 | STRONG_TREND_DOWN | 0.0942 | 32.72 | 13.55 | 26.16 | — | BEAR_ALIGNED | SHORT | `_bcb729dc` |
| 15:25:00 | STRONG_TREND_DOWN | 0.0942 | 32.65 | 12.94 | 24.99 | — | BEAR_ALIGNED | SHORT | `_1d6f8e96` |
| 15:30:00 | STRONG_TREND_DOWN | 0.0942 | 31.33 | 17.33 | 23.05 | — | BEAR_ALIGNED | SHORT | `_7038b8e2` |
| 15:35:00 | STRONG_TREND_DOWN | 0.0942 | 29.38 | 20.07 | 21.72 | — | BEAR_ALIGNED | SHORT | `_5fff0a5e` |
| 15:40:00 | STRONG_TREND_DOWN | 0.0942 | 27.63 | 22.29 | 20.21 | — | BEAR_ALIGNED | SHORT | `_952aaacc` |
| 15:45:02 | STRONG_TREND_DOWN | 0.0942 | 26.25 | 21.89 | 18.53 | — | MIXED | SHORT | `_b295a7ab` |
| 15:50:00 | STRONG_TREND_DOWN | 0.0942 | 25.14 | 21.96 | 17.68 | — | MIXED | SHORT | `_d4933c14` |
| 15:55:00 | STRONG_TREND_DOWN | 0.0942 | 24.43 | 22.25 | 16.38 | — | MIXED | SHORT | `_e687e69b` |
| 16:00:00 | STRONG_TREND_DOWN | 0.0942 | 24.22 | 24.39 | 15.78 | — | BULL_PARTIAL | SHORT | `_1434f4c5` |

Notes on the sequence:

* Every row has `winning_regime == winning_regime_pre_override` and
  `vol_override_fired=False`, `tiebreak_fired=False` — no post-classify
  override changed the label on any of these bars.
* Label alternates three times in the 25-minute window 13:55–14:25
  (STRONG_TREND_DOWN → RANGE_ROTATION → STRONG_TREND_DOWN →
  RANGE_ROTATION → STRONG_TREND_DOWN). Alternation proves per-bar
  fresh classification — a latched value cannot alternate.
* `regime_confidence_final` is **0.0170 → 0.0172 → 0.0942** through
  the entire window. Confidence is essentially zero for all 19 bars
  from 14:05 to 15:00 UTC, i.e. the classifier itself is *barely
  certain* that anything applies — the label is technically
  STRONG_TREND_DOWN because that family accumulated the highest score
  in a very small margin, not because the classifier had conviction.
* The two RANGE_ROTATION bars at 13:55–14:00 UTC and the one at 14:20
  UTC line up with the operator's read that "the market was range-like
  from ~14:00". So *the classifier does see the range*, but only for
  isolated bars; the DI-margin swings back to a −DI-dominant reading
  and STRONG_TREND_DOWN reclaims the label.
* At the standdown consult time (14:45:00Z, row consulted by
  `_re.latest_result("GBPUSD")` from `gbpusd_bb_bounce.py:2467`) the
  label is `STRONG_TREND_DOWN`, DI margin −25.6 (36.94 vs 11.31), ADX
  30.71, `adx_slope +5.04`. This is a strong DI-margin bar even though
  the surrounding session-context read (per operator) is range.

### (b) First bar labelled STRONG_TREND_DOWN in the run leading into 14:45

Two ways to interpret "first bar":

**First bar in the 13:30-16:00 window:** row `13:30:00` (`_f1a3b277`).
STRONG_TREND_DOWN with ADX=31.95, +DI=9.51, −DI=30.45 (DI margin
−20.94), EMA=BEAR_ALIGNED, confidence 0.0170. Direct carry from the
pre-13:30 tape; no transition event visible in the window.

**First bar of the uninterrupted run that ends at 14:45Z:** row
`14:25:00` (`_8a613baa`), following the RANGE_ROTATION bar at
`14:20:01`. Feature snapshot at this transition:

| Feature | 14:20:01 (RANGE_ROTATION) | 14:25:00 (STRONG_TREND_DOWN, first of run) |
|---------|--------------------------:|--------------------------------------------:|
| winning_regime | RANGE_ROTATION | STRONG_TREND_DOWN |
| winning_score | 0.0172 | 0.0172 |
| confidence_final | 0.0172 | 0.0172 |
| ADX | 25.9007 | 25.6735 |
| +DI | 19.0924 | 17.4313 |
| −DI | 22.6954 | 27.6810 |
| DI margin (−DI − +DI) | +3.60 | **+10.25** |
| adx_slope | −3.6050 | −2.7014 |
| EMA_state | BEAR_ALIGNED | BEAR_ALIGNED |
| directional_bias | NEUTRAL_BIAS | SHORT |
| vol_override_fired | False | False |
| tiebreak_fired | False | False |
| regime_instance_id | `..._e7560205` | `..._8a613baa` |

Trigger for the flip: **DI margin expanded from +3.60 to +10.25 in a
single bar** (−DI jumped +4.99, +DI dropped −1.66). ADX itself dipped
slightly (−0.23) and adx_slope stayed negative. The classifier's
STRONG_TREND family scoring — which weighs the DI margin heavily above
a threshold — took the crown from the range family by that DI-margin
step.

**Score fields I would normally cite are absent from the row.** The
current `_telemetry_record()` schema at
`/opt/tradingbot/regime_engine.py:1984-2101` writes
`winning_score / score_margin / runner_up_score` but NOT
`score_trend_down / score_trend_up / score_range / score_chop /
score_breakout / score_compression`. Historical rows from 2026-05-22
carry them; recent rows do not. The classifier is scoring internally,
but the per-family breakdown is not persisted in the current row
format. This means the exact `score_trend_down > score_range`
comparison that flipped the label at 14:25:00 is **not directly
readable from the log** — the closest inference is the feature step
above.

`regime_label_path` on the 14:45 standdown row is `"struct"` and
`regime_struct_promoted=true` — meaning the label at consult time was
NOT the pure historical scoring but a structural OR-path promotion.
For a fully authoritative "what inputs drove the STRONG_TREND_DOWN
promotion at 14:45", the harness will need to walk
`d.get("regime_struct_detail")` on that bar (persisted via
`_compact_struct_detail()` at `regime_engine.py:2003` — full detail is
in `regime_shadow.jsonl`, 48 MB, mtime 2026-08-22 22:05, not opened
here to avoid noise). Recording that requirement for the replay.

### (c) Fresh classification vs latched state — code-path verdict

**The 14:45:00Z label is FRESH per-bar classification, not latched
state.** Three independent proofs:

1. **`regime_instance_id` is unique on every bar** — `..._766a55d4`
   at 14:45 is distinct from `..._56459183` at 14:40, `..._220ebc36`
   at 14:35, and every other bar in the sequence. `_telemetry_record`
   at `regime_engine.py:1990` reads `result["regime_instance_id"]`
   which is minted at each `classify_regime` call.
2. **The label ALTERNATES three times in the 25 minutes preceding
   14:45** (13:50 STD → 13:55 RR → 14:05 RR → 14:10 STD → 14:15 STD →
   14:20 RR → 14:25 STD). A latched value would flatten this into a
   run.
3. **`confidence_final` steps at 15:05** from 0.0172 to 0.0942 — the
   number changes bar-by-bar with the underlying features. A latched
   value would freeze it.

**The "latch bug found this week"** was in a different module and did
not affect the BB_BOUNCE standdown path. Commit `ee18d63` (2026-08-20)
`fix(day_posture): read winning_regime/confidence_final from
latest_result`:

> `_regime_snapshot` was reading `r.get("regime")` /
> `r.get("confidence")` from `regime_engine.latest_result()`, but the
> cached rows are produced by `_telemetry_record()` which flattens
> `result["regime"]` to `"winning_regime"` and
> `debug["confidence_final"]` to `"confidence_final"` — the legacy
> keys do not exist on the record. Every call therefore fell through
> to the CHOP/0.0 fallback ...
>
> Cross-check: **BB_BOUNCE strong-trend stand-down (which reads the
> SAME cache via `_rg.get("winning_regime")`) correctly identified
> STRONG_TREND_UP and blocked SELL fades** — proving the engine was
> live and the bug is scoped to day_posture's key mismatch.

The BB_BOUNCE standdown reads the correct key
(`_rg.get("winning_regime")` at `gbpusd_bb_bounce.py:2468`), the
day_posture-only bug was fixed on 2026-08-20 (a day BEFORE our
14:45:00Z event on 2026-08-21), and the day_posture path is not on
the BB_BOUNCE standdown code path at all. So the 14:45Z suppression
is **fresh per-bar** consumption of a **correctly-cached** label — the
misclassification (per operator ruling) is at the classifier
scoring layer, not the caching/consumption layer.

### Harness pre-verdict — Row 1 third must-fire

If the replay uses live `regime_engine.jsonl` state (or a byte-clean
re-classification from the same 5m/H1 candles + same env), it **will**
reproduce the 14:45:00Z `STRONG_TREND_DOWN` label with the same
feature snapshot (ADX 30.71, DI margin +25.6, EMA_state BEAR_ALIGNED,
`regime_label_path="struct"`, `regime_struct_promoted=true`,
`confidence_final=0.0172`). Consumption path via
`gbpusd_bb_bounce.py:2467` is deterministic and matrix-off (see GAP 1
class D). Therefore:

* **Predicted harness outcome for Row 1 third must-fire:
  TESTED-FAIL, root cause `REGIME_MISCLASSIFICATION`.**
* Assertion NOT weakened, per ruling.
* Evidence bundle the harness must record: (i) full 13:30-16:00 bar
  sequence above; (ii) 14:25:00 transition-bar feature diff vs
  14:20:01; (iii) 14:45:00Z consulted row verbatim; (iv) statement
  that the label was fresh per-bar classification, not a
  day_posture-style stale-latch, with the `ee18d63` commit cite.
* If the replay somehow produces a DIFFERENT label at 14:45Z (e.g.
  because the harness's candle-source differs from the live cache in
  a way that shifts one DI/ADX read), that itself is a harness bug
  and needs surfacing — the live 5m/H1 cache at HEAD `d5d3c6a` for
  2026-08-21T14:45Z is `STRONG_TREND_DOWN` and the code path that
  reads it is deterministic.

Underlying-classifier misclassification hypothesis (per operator
ruling) is consistent with the evidence: the tape at 14:00-14:45 UTC
saw the classifier flip RANGE_ROTATION → STRONG_TREND_DOWN three
times, and the "winning" STRONG_TREND_DOWN label was held with
`confidence_final=0.0172` — a value the classifier itself signals as
"near-zero certainty". A ~25p bounce entry from that setup would be
correctly gated by a well-calibrated classifier as *do not stand
down* at this confidence, but the current standdown at
`gbpusd_bb_bounce.py:2464` reads only `winning_regime`, not
`regime_confidence_final`, and so treats every STRONG_TREND_DOWN as
authoritative regardless of confidence.

That final observation is a candidate action for the V2 rebuild scope
but is not being proposed here — inventory only.

---

## End of addendum

All four gaps closed with cited evidence, and the A6 operator ruling
is pre-answered with the exact per-bar sequence and code-path
attribution the harness will produce. Findings are additive to
`/tmp/dead_flags_audit_20260823.md`; no classification in that report
is retracted.
