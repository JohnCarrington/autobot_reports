# NMS audit for new-bot design — AutoBot host-ip=REDACTED (2026-11-06)

READ-ONLY audit. No file was changed, no service touched. Every rule
is quoted verbatim from the running code (including uncommitted
modifications on disk), with file:line citations. Facts labelled
CONFIRMED (read in code and verified). Anything not fully verified
labelled UNSURE.

Target state list in the brief: **Ranging**, **Emerging trend**,
**Trend**, **Exhaustion**, **Possible reversal**, **Consolidation**.
The code does not use exactly these six labels; each is listed in
§3 with its real counterpart (or an explicit "NOT FOUND").

---

## 1. Where NMS lives (every file, full path)

NMS on this host is a **five-piece ensemble** of library modules
linked into `autobot.service`. There is no "NMS service" — nothing
runs stand-alone.

**CONFIRMED** — all files below exist and were read in the course of
this audit.

| # | Full path | Size / mtime | Role |
|---|---|---|---|
| 1 | `/opt/tradingbot/normal_market_state.py` | 82,116 B — 2026-10-12 | **Companion NMS** — 4-state regime classifier (`UNKNOWN / PRODUCTIVE_RANGE / FLAT_OR_COMPRESSED / TRADABLE_NON_RANGE`) + demonstrated-direction via CHoCH |
| 2 | `/opt/tradingbot/session_trend.py` | 98,490 B — 2026-11-03 **(+52 uncommitted lines vs HEAD)** | Driver for the **session-trend v3 classifier**; writes `cache/session_trend_<SYM>.json` |
| 3 | `/opt/tradingbot/nms_v3_classifier.py` | 46,654 B — 2026-11-04 **(+275 uncommitted lines vs HEAD)** | Pure state-machine: `NORMAL / RANGE / EMERGING_UP / EMERGING_DOWN / STRONG_UP / STRONG_DOWN` |
| 4 | `/opt/tradingbot/nms_exhaustion_detector.py` | 54,618 B — 2026-10-27 | Six-family exhaustion aggregator (CANDLE_REJECTION / MOMENTUM / STRUCTURE / FAILED_EXTENSION / COMPRESSION / LEVEL_REACTION) → `NO_EXHAUSTION / EXHAUSTION_DEVELOPING / EXHAUSTION_CONFIRMED / UNKNOWN` |
| 5 | `/opt/tradingbot/nms_exhaustion_driver.py` | 19,164 B — 2026-10-27 | Runs the detector each M5 close, writes `cache/nms_exhaustion_<SYM>.json` + `logs/nms_exhaustion.jsonl` |
| 6 | `/opt/tradingbot/nms_watch_state_machine.py` | 48,775 B — 2026-10-28 | Sticky WATCH_AND_WAIT lifecycle (`TREND_TRADING / WATCH_AND_WAIT / CONTINUATION_CONFIRMED / REVERSAL_CONFIRMED`) |
| 7 | `/opt/tradingbot/nms_watch_state_driver.py` | 19,079 B — 2026-10-28 | Runs the watch machine each M5 close, writes `cache/nms_watch_state_<SYM>.json` + `logs/nms_watch_state.jsonl` |
| 8 | `/opt/tradingbot/nms_directional_authority.py` | 60,380 B — 2026-10-27 | Unified ALLOW/BLOCK decision per (strategy family × side) |
| 9 | `/opt/tradingbot/nms_session_trend_direction.py` | 18,215 B — 2026-10-27 | Thin wrapper publishing `permit_trend()` / `permit_bounce()` to the central gate and bounce_engine_live |
| 10 | `/opt/tradingbot/nms_v3_direction_gate.py` | 22,762 B — 2026-10-20 | Older gate layer feeding `central_execution_gate.evaluate()`; still called (CONFIRMED, see §8) |
| 11 | `/opt/tradingbot/nms_second_gate.py` | 10,685 B — 2026-10-22 | Per-strategy stand-aside check on top of companion NMS — **env-disabled on live** (§3.6) |
| 12 | `/opt/tradingbot/nms_family_snapshot.py` | 15,267 B — 2026-11-04 | Helper that bundles the three snapshot JSONs for consumers |
| 13 | `/opt/tradingbot/nms_admission_matrix.py` | 9,179 B — 2026-11-04 | Static admission matrix used by `bounce_engine_live` |
| 14 | `/opt/tradingbot/nms_reversal_oracles.py` | 7,430 B — 2026-10-27 | QM-reversal signal reader used by the watch state machine |
| 15 | `/opt/tradingbot/nms_range_tm_boot.py` | 1,661 B — 2026-11-04 | Boot entry for the Range Trade-Management overlay (live) |
| 16 | `/opt/tradingbot/nms_range_tm/nms_transition.py` | — | State-machine body for the Range TM overlay |
| 17 | `/opt/tradingbot/regime_engine.py` | 137,037 B — 2026-09-11 | Provides `_range_features` + `_compression_chop_shadow` — the raw inputs for companion NMS |
| 18 | `/opt/tradingbot/market_structure.py` | 15,936 B — 2026-08-24 | `detect_confirmed_swings` + `classify_structure` — provides the swing/CHoCH primitives |
| 19 | `/opt/tradingbot/session_trend_integration.py` | 5,457 B — 2026-10-12 | Bridges daily pivots + IG daily % into session_trend |
| 20 | `/opt/tradingbot/session_trend_guard.py` | 7,366 B — 2026-10-12 | **(Different file from the BB-Bounce standalone one below.)** Server-side helper |
| 21 | `/opt/tradingbot/demonstrated_direction.py` | 23,468 B — 2026-10-05 | Separate Stage-9 Build-1 direction layer — **NOT read by the five NMS pieces** (§8 note) |

**Snapshot and journal files** written by NMS (CONFIRMED by `ls`
2026-11-06 09:15 UTC):

```
/opt/tradingbot/cache/nms_authority_GBPUSD.json       5,301 B   09:15
/opt/tradingbot/cache/session_trend_GBPUSD.json       1,411 B   09:15
/opt/tradingbot/cache/nms_exhaustion_GBPUSD.json      1,205 B   09:15
/opt/tradingbot/cache/nms_watch_state_GBPUSD.json     1,153 B   09:15
/opt/tradingbot/cache/normal_market_state.json       40,836 B   09:15
/opt/tradingbot/cache/session_trend_state.json       33,615 B   09:15
/opt/tradingbot/logs/normal_state_journal.jsonl      — rotated daily
/opt/tradingbot/logs/nms_exhaustion.jsonl            — rotated daily
/opt/tradingbot/logs/nms_watch_state.jsonl           — rotated daily
```

**Standalone reader stubs on other services** (CONFIRMED by grep,
read-only):

```
/opt/bb_bounce/session_trend_guard.py                 ← reads cache/session_trend_<SYM>.json
/opt/bb_bounce/nms_family_snapshot.py                 ← reads cache/nms_watch_state_<SYM>.json
/opt/ema_pullback/ema_pullback/nms_gate.py            ← reads cache/session_trend_<SYM>.json
/opt/ema_pullback/ema_pullback/watch_state_gate.py    ← reads cache/nms_watch_state_<SYM>.json
```

---

## 2. What NMS reads — prices, timeframes, indicators

### 2.1 The one upstream: completed 5-minute candles

All five pieces update on the main `on_bar_close` callback in
autobot. (CONFIRMED CITE `autobot.py:3943-3990`.) The bar payload
carries `(symbol, ts, o, h, l, c)` plus a `candles_5m_closed_df`
DataFrame used by the exhaustion driver.

No tick data, no 1-minute data, no H4 data, no weekly, no daily.
**Daily pivots and the IG daily % change ARE read** — but only via
session_trend_integration.py as inputs to session_trend, not as
inputs to the state decisions themselves. (CONFIRMED CITE
`autobot.py:9946-9962`.)

H1 input for the Exhaustion Detector comes from a pre-computed
sidecar file `cache/h1_macd_tiring_<SYM>.json` that autobot writes
separately on every M5 close — the detector itself never queries
H1 directly. (CONFIRMED CITE `nms_exhaustion_detector.py:108-110`.)

### 2.2 Indicators used (settings quoted from code)

**Bollinger Bands** — 20 periods, 2 standard deviations (`BB(20,2)`).
Used three ways:

- **Band width in pips** — `bb_w_pips`. In companion NMS the gate
  is `bb_w_pips >= 8.0` for PRODUCTIVE_RANGE and `< 8.0` to arm the
  chop shadow.
    CITE `/opt/tradingbot/regime_engine.py:530`:
    > `CHOP_BB_WIDTH_MAX_PIPS      = float(os.getenv("CHOP_BB_WIDTH_MAX_PIPS",      "8.0"))`
    CITE `/opt/tradingbot/normal_market_state.py:692-696`:
    > `bb_min_range = _env_float("NORMAL_STATE_BB_MIN_RANGE_PIPS", 8.0)`
    > `if (not chop_active and float(er10) < er_max_range`
    > ` and float(bb_w) >= bb_min_range`
    > ` and int(cross) >= cross_min_range):`
- **Midline slope** — `BB_MID_20` slope over `CHOP_SLOPE_LOOKBACK=6`
  M5 bars in pips/bar. Chop is active when `|slope| < 0.5`.
    CITE `/opt/tradingbot/regime_engine.py:531-532`:
    > `CHOP_SLOPE_LOOKBACK         = int(float(os.getenv("CHOP_SLOPE_LOOKBACK",     "6")))`
    > `CHOP_SLOPE_MAX_PIPS_PER_BAR = float(os.getenv("CHOP_SLOPE_MAX_PIPS_PER_BAR", "0.5"))`
- **Midline crossings count** — how many times `close` crosses
  `BB_MID_20` in the trailing 12 bars.
    CITE `/opt/tradingbot/regime_engine.py:452`:
    > `REGIME_RANGE_CROSSING_WINDOW    = int(float(os.getenv("REGIME_RANGE_CROSSING_WINDOW", "12")))`

**Kaufman Efficiency Ratio (ER10)** — ten-period Kaufman ER on
closes.
    CITE `/opt/tradingbot/regime_engine.py:464`:
    > `REGIME_RANGE_ER_BARS            = int(float(os.getenv("REGIME_RANGE_ER_BARS",         "10")))`
    CITE `/opt/tradingbot/regime_engine.py:698`:
    > `out["er10"] = _kaufman_er_from_series(df["close"], REGIME_RANGE_ER_BARS)`

**ATR14** — fourteen-period ATR in pips. Computed but **only used
for telemetry**, not for state decisions in companion NMS or v3.
(CONFIRMED CITE `regime_engine.py:686`.)

**MACD** appears in **two separate places**:

- v3 classifier uses an M5 MACD **(12, 26, 9)** (standard) to feed
  the E8 evidence rule.
    CITE `/opt/tradingbot/nms_v3_classifier.py:487-498`:
    > `ema12 = ema(closes, 12)`
    > `ema26 = ema(closes, 26)`
    > `macd = [a - b for a, b in zip(ema12, ema26)]`
    > `sig = ema(macd, 9)`
    > `return macd[-1] - sig[-1]`
- Exhaustion Detector uses a **non-standard M5 MACD (35, 45, 30)**
  over a 12-bar window plus an H1 MACD sidecar.
    CITE `/opt/tradingbot/nms_exhaustion_detector.py:172-178`:
    > `_M5_MACD_FAST = 35`
    > `_M5_MACD_SLOW = 45`
    > `_M5_MACD_SIGNAL = 30`
    > `_M5_MACD_WINDOW = int(`
    > `    os.getenv("NMS_EXHAUSTION_M5_MACD_WINDOW", "12") or "12"`
    > `)`
    > `_M5_MACD_MIN_CLOSES = _M5_MACD_SLOW + _M5_MACD_SIGNAL  # 75`

**EMAs** — only used in the v3 classifier E7 rule. `EMA_7`, `EMA_13`,
`EMA_21` on M5 closes. Rule is **stack + persistence**, not a
fanning-apart measurement.
    CITE `/opt/tradingbot/nms_v3_classifier.py:845-867`:
    > `def _advance_e7(s: Dict[str, Any], bar: Dict[str, Any], fired: List) -> None:`
    > `    if s["ema7"] is None or s["ema13"] is None or s["ema21"] is None:`
    > `        return`
    > `    stacked_up = s["ema7"] > s["ema13"] > s["ema21"]`
    > `    stacked_dn = s["ema7"] < s["ema13"] < s["ema21"]`
    > `    if stacked_up:`
    > `        s["ema_rising_bars"] = max(0, s["ema_rising_bars"]) + 1`
    > `    elif stacked_dn:`
    > `        s["ema_rising_bars"] = min(0, s["ema_rising_bars"]) - 1`
    > `    else:`
    > `        s["ema_rising_bars"] = 0`
    > `    if s["ema_rising_bars"] == 3:`
    > `        fired.append({`
    > `            "kind": "E7", "family": "F-supporting", "direction": "UP",`
    > `            "points": 1, ... "note": "EMA 7>13>21 three bars",`

**EMA slope** — **NOT USED anywhere in the five NMS pieces**. Grep
over `normal_market_state.py`, `session_trend.py`,
`nms_v3_classifier.py`, `nms_exhaustion_detector.py`,
`nms_watch_state_machine.py` returns no `ema_slope` reader.
**CONFIRMED NOT FOUND.**

**EMAs fanning apart** — **NOT USED anywhere in the five NMS
pieces**. The v3 E7 rule tests EMA **stack**, not **fan separation**.
A separate module (`ema_pullback.py` / `bb_bounce_filters.py`) uses
EMA-fan width, but that is a strategy filter, not part of NMS.
**CONFIRMED NOT FOUND in NMS.**

**RSI** — **NOT USED anywhere in the five NMS pieces**. Grep for
`RSI` or `rsi_` in the five NMS files returns zero hits.
**CONFIRMED NOT FOUND.** (External strategies on the host do use
RSI, but NMS does not.)

### 2.3 Session anchoring

Companion NMS session anchor = later of (00:00 UTC, 06:00 UTC on
this calendar day). **12 bars** must have closed since the anchor,
and **25 enriched bars** must be available, before classification
starts.
    CITE `/opt/tradingbot/normal_market_state.py:189-191`:
    > `_ANCHOR_HOUR_DEFAULT = 6`
    > `_MIN_BARS_DEFAULT = 12          # 60 min post-anchor before classification`
    > `_MIN_ENRICH_BARS_DEFAULT = 25   # BB/ATR need at least 21+ bars to be valid`

Session-trend v3 anchors on the **London 08:00 Europe/London**
open, DST-aware via `zoneinfo`.
    CITE `/opt/tradingbot/nms_v3_classifier.py:_london_open_for` ~L470:
    > `local_open = datetime.combine(d, time(8, 0, 0), tzinfo=_LONDON_TZ)`
    > `return local_open.astimezone(timezone.utc)`

### 2.4 Freshness / staleness caps

| Piece | Cap | Env var |
|---|---|---|
| Companion NMS | 360 s | `NMS_READINESS_STALENESS_SECS=360` (default) |
| Exhaustion | 360 s, min 25 bars | `NMS_EXHAUSTION_STALENESS_SECS=360`, `NMS_EXHAUSTION_MIN_BARS=25` |
| WATCH snapshot | 360 s | `NMS_WATCH_SNAPSHOT_MAX_AGE_SECONDS=360` |
| Unified Authority | 360 s | `NMS_UNIFIED_AUTHORITY_MAX_AGE_SECONDS=360` |
| nms_session_trend_direction (bb-bounce consumer) | 900 s | `DEFAULT_MAX_AGE_SECONDS=900` |

---

## 3. The six states the brief asks about

For each requested state, this section says whether a one-to-one
counterpart exists in the live code, quotes the exact rule, and
flags any gap.

### 3.1 Ranging → `PRODUCTIVE_RANGE` (companion) + `RANGE` (v3)

There are **two different Range labels**, in two different pieces.

**Companion NMS `PRODUCTIVE_RANGE`** (meaningful rotation inside a
tradable band). All four conditions must hold **on the same M5
bar**:
    CITE `/opt/tradingbot/normal_market_state.py:689-696`:
    > `er_max_range = _env_float("NORMAL_STATE_ER_MAX_RANGE", 0.5)`
    > `bb_min_range = _env_float("NORMAL_STATE_BB_MIN_RANGE_PIPS", 8.0)`
    > `cross_min_range = _env_int("NORMAL_STATE_CROSS_MIN_RANGE", 2)`
    > `if (not chop_active and float(er10) < er_max_range`
    > `        and float(bb_w) >= bb_min_range`
    > `        and int(cross) >= cross_min_range):`
    > `    return PRODUCTIVE_RANGE, (`

Numerically: chop shadow is **off**, `er10 < 0.5` (inefficient =
not decisively trending), `bb_w_pips >= 8.0` (band wide enough to
trade to), and the close has crossed the midline at least 2 times
in the last 12 bars.

**Session-trend v3 `RANGE`** — seeded automatically as soon as the
first London bar is received, and re-entered from
EMERGING_*/STRONG_* on any invalidation rule.
    CITE `/opt/tradingbot/nms_v3_classifier.py:270-277`:
    > `# First London bar: seed anchor.`
    > `if s["london_open_ts"] is None:`
    > `    s["london_open_ts"] = bar["ts"]`
    > `    s["london_open_price"] = bar["o"]`
    > `    s["state"] = "RANGE"`
    > `    s["state_since"] = bar["ts"]`

v3 does not have a numerical threshold for entering RANGE — it is
a **default residual state** whenever no EMERGING or STRONG
conditions hold.

### 3.2 Emerging trend → `EMERGING_UP` / `EMERGING_DOWN` (v3)

Lives only in v3. Target state becomes EMERGING_UP when **all** of
the following hold on the current bar; it then has to **persist for
2 bars** before the state actually flips (see §4).
    CITE `/opt/tradingbot/nms_v3_classifier.py:1057-1065`:
    > `em_up_ok = (`
    > `    up_score >= EMERGING_ENTRY_THRESHOLD`
    > `    and down_score <= EMERGING_OPPOSING_CAP`
    > `    and _emerging_struct_present(up_fams)`
    > `)`

CITE for thresholds `/opt/tradingbot/nms_v3_classifier.py:122-123`:
> `EMERGING_ENTRY_THRESHOLD = 3`
> `EMERGING_OPPOSING_CAP = 0           # strict`

CITE for "struct present" `/opt/tradingbot/nms_v3_classifier.py:629-633`:
> `def _emerging_struct_present(fams: Dict[str, int]) -> bool:`
> `    """EMERGING needs at least one structural anchor from`
> `    {E1, E3, E4}. Proxied by F-structural + F-structure > 0."""`
> `    return fams["F-structural"] > 0 or fams["F-structure"] > 0`

Meaning in plain English: the TTL-filtered up-score (built from the
eight evidence rules) is at least 3 and the down-score is zero, and
at least one of (opening-range break, break of a prior swing high,
new higher-low) has fired within the last 24 bars.

### 3.3 Trend → `STRONG_UP` / `STRONG_DOWN` (v3)

Lives in v3. Promotion from RANGE or EMERGING requires **all** of:
    CITE `/opt/tradingbot/nms_v3_classifier.py:1041-1053`:
    > `strong_up_ok = (`
    > `    up_score >= STRONG_ENTRY_THRESHOLD`
    > `    and down_score <= STRONG_OPPOSING_CAP`
    > `    and _strong_struct_present(s, "UP", bar["ts"])`
    > `    and s["range_reversals_count"] <= MAX_RANGE_REVERSALS_FOR_STRONG`
    > `)`

Thresholds at `/opt/tradingbot/nms_v3_classifier.py:124-129`:
> `STRONG_ENTRY_THRESHOLD = 6`
> `STRONG_OPPOSING_CAP = 1             # strict`
> `PERSISTENCE_BARS = 2`
> `EVIDENCE_TTL_BARS = 24              # 120 min`
> `MAX_RANGE_REVERSALS_FOR_STRONG = 1  # strict`

Structural anchor at `/opt/tradingbot/nms_v3_classifier.py:635-648`:
> `def _strong_struct_present(`
> `    s: Dict[str, Any], direction: str, now_ts_str: str,`
> `) -> bool:`
> `    """STRICT: ≥ 2 E4 confirmed HLs OR (E1 AND E3 AND ≥ 1 E4)."""`
> `    ... `
> `    return e4_count >= STRONG_MIN_HL_COUNT or (has_e3 and has_e1 and e4_count >= 1)`

STRONG_MIN_HL_COUNT = 2 (CITE L136). Plain English: up-score ≥ 6,
down-score ≤ 1, at most one range-reversal has happened in the
session, AND either two new higher-lows have been confirmed inside
the 24-bar TTL window, or the opening-range was broken AND a prior
swing high was taken AND one higher-low has been confirmed.

### 3.4 Exhaustion → `EXHAUSTION_DEVELOPING` / `EXHAUSTION_CONFIRMED`

Lives in piece 3. Decision rule:
    CITE `/opt/tradingbot/nms_exhaustion_detector.py:1143-1174`:
    > `def _aggregate(`
    > `    evidence: Sequence[Evidence],`
    > `) -> Tuple[str, str, Tuple[str, ...], str]:`
    > `    """Return (state, direction, families_active, reason).`
    > `    Rules:`
    > `      * NO_EXHAUSTION with DIR_NONE when evidence is empty.`
    > `      * UNKNOWN when evidence items disagree on direction.`
    > `      * DEVELOPING when exactly 1 family fires, or when every active`
    > `        family is "supporting" (MOMENTUM-only, or COMPRESSION-only).`
    > `      * CONFIRMED when ≥2 distinct families agree AND at least one is`
    > `        an INDEPENDENT family.`
    > `    """`
    > `    ...`
    > `    independent_hit = any(f in _INDEPENDENT_FAMILIES for f in families)`
    > `    if len(families) == 1:`
    > `        return STATE_DEVELOPING, direction, families, "single_family"`
    > `    if not independent_hit:`
    > `        return (STATE_DEVELOPING, direction, families,`
    > `                "supporting_families_only")`
    > `    return STATE_CONFIRMED, direction, families, "multi_family_independent"`

Independent families (CITE L259):
> `_INDEPENDENT_FAMILIES = (FAM_CANDLE, FAM_STRUCTURE, FAM_FAILED_EXT, FAM_LEVEL)`

Plain English: at least two distinct families must agree on the
same direction (BUYING_EXHAUSTION or SELLING_EXHAUSTION), AND at
least one of the firing families must be CANDLE_REJECTION,
STRUCTURE, FAILED_EXTENSION or LEVEL_REACTION. Momentum plus
Compression alone can only reach DEVELOPING, never CONFIRMED.

### 3.5 Possible reversal → closest counterpart is `WATCH_AND_WAIT` / `REVERSAL_CONFIRMED` (piece 4)

The name "possible reversal" has **no state of its own**. The
closest thing is the WATCH_AND_WAIT state (piece 4), which the code
describes as "the system has credible exhaustion against an
established trend and is withholding new entries while waiting to
see whether the trend continues or reverses". Only a
**REVERSAL_CONFIRMED** verdict (triggered by a fresh QM_REVERSAL
signal, see §5.4) represents an actual reversal call.
    CITE `/opt/tradingbot/nms_watch_state_machine.py:36-55`:
    > `TREND_TRADING          Default. Existing matrix applies.`
    > `WATCH_AND_WAIT         Credible exhaustion against the prevailing`
    > `                       trend. New BUY and SELL entries are blocked`
    > `                       for applicable families. ...`
    > `CONTINUATION_CONFIRMED Short-lived transitional state when`
    > `                       exhaustion evidence has disappeared and`
    > `                       the original trend has resumed. ...`
    > `REVERSAL_CONFIRMED     A qualifying structural reversal has fired`
    > `                       (QM_REVERSAL ONLY — V2 Pick is DISABLED ...).`

### 3.6 Consolidation → closest counterpart is `FLAT_OR_COMPRESSED` (companion) + `CONSOLIDATION` m5_regime refinement (v3)

**Companion NMS `FLAT_OR_COMPRESSED`** — the chop shadow is on:
    CITE `/opt/tradingbot/normal_market_state.py:704-710`:
    > `# FLAT_OR_COMPRESSED — chop-shadow is active (both BB width AND`
    > `# midline slope are below their thresholds). RangeQuality`
    > `# subclassifies this downstream.`
    > `if chop_active:`
    > `    return FLAT_OR_COMPRESSED, (`
    > `        f"flat_or_compressed:bb_w={bb_w:.1f}p,"`
    > `        f"slope={feats.get('chop_shadow_slope_ppb')},"`
    > `        f"cross={cross}"`
    > `    )`

Chop-shadow condition (CITE `regime_engine.py:751-755`):
> `if wp is not None and slope_ppb is not None:`
> `    out["active"] = (`
> `        wp < CHOP_BB_WIDTH_MAX_PIPS`
> `        and abs(slope_ppb) < CHOP_SLOPE_MAX_PIPS_PER_BAR`
> `    )`

Plain English: band width under 8 pips AND |midline slope over 6
bars| under 0.5 pips/bar.

**v3 `CONSOLIDATION` label** — an additive refined label stamped
on `m5_regime` only when `NMS_V3_C4_MULTI_DIM=1` (live):
    CITE `/opt/tradingbot/nms_v3_classifier.py:378-389`:
    > `elif s["state"] == "RANGE":`
    > `    prior = s.get("prior_trend_state")`
    > `    if prior in ("EMERGING_UP", "STRONG_UP"):`
    > `        if down_score <= -EMERGING_ENTRY_THRESHOLD + 1 and up_score < 1:`
    > `            m5_regime = "TRANSITION"`
    > `        else:`
    > `            m5_regime = "CONSOLIDATION"`
    > `    elif prior in ("EMERGING_DOWN", "STRONG_DOWN"):`
    > `        if up_score >= EMERGING_ENTRY_THRESHOLD - 1 and down_score > -1:`
    > `            m5_regime = "TRANSITION"`
    > `        else:`
    > `            m5_regime = "CONSOLIDATION"`

Plain English: v3 flipped from a trend back into RANGE, but no
opposite-direction evidence is yet building — the market has stopped
and is sitting still. **Important caveat:** `m5_regime` is written
but no live gate currently consumes it (see §9).

### 3.7 Summary table

| Brief's state | Live code name | Module | CONFIRMED? |
|---|---|---|---|
| Ranging | `PRODUCTIVE_RANGE` (companion) + `RANGE` (v3) | normal_market_state.py / nms_v3_classifier.py | CONFIRMED |
| Emerging trend | `EMERGING_UP` / `EMERGING_DOWN` | nms_v3_classifier.py | CONFIRMED |
| Trend | `STRONG_UP` / `STRONG_DOWN` | nms_v3_classifier.py | CONFIRMED |
| Exhaustion | `EXHAUSTION_DEVELOPING` / `EXHAUSTION_CONFIRMED` | nms_exhaustion_detector.py | CONFIRMED |
| Possible reversal | `WATCH_AND_WAIT` (watching) + `REVERSAL_CONFIRMED` (fired) | nms_watch_state_machine.py | CONFIRMED |
| Consolidation | `FLAT_OR_COMPRESSED` (companion) + `CONSOLIDATION` (m5_regime, telemetry only) | normal_market_state.py / nms_v3_classifier.py | CONFIRMED |

The brief's state list is **not** all produced by one component. A
new bot that wants a single six-state enum will have to pick which
piece's vocabulary to canonicalise and discard the extras.

---

## 4. Moving between states — triggers and debounce

### 4.1 Companion NMS

**No debounce. No hysteresis. No minimum duration.** Every bar the
features are recomputed and the partition rule is re-evaluated. If
features cross a threshold on a single bar the state flips that bar.
    CITE `/opt/tradingbot/normal_market_state.py:668-716` — the full
    `_decide` body is a straight partition, no history.

This is why in the live journal (§7) you see one-bar PRODUCTIVE_RANGE
visits — a single bar whose `bb_w` dipped under 8 or whose `cross`
dropped below 2 is enough to flip to TRADABLE_NON_RANGE, and the
next bar can flip back.

### 4.2 Session-trend v3 — three mechanisms

**(a) 2-bar persistence gate on upgrades.** `_decide_want` computes
the target state each bar; the state only flips when the same target
has been wanted for 2 consecutive bars.
    CITE `/opt/tradingbot/nms_v3_classifier.py:332-351`:
    > `# 2-bar persistence.`
    > `transition_fired = False`
    > `if want_state != s["state"]:`
    > `    if s.get("pending_state") == want_state:`
    > `        s["pending_bars"] += 1`
    > `    else:`
    > `        s["pending_state"] = want_state`
    > `        s["pending_bars"] = 1`
    > `    if s["pending_bars"] >= PERSISTENCE_BARS:`
    > `        s["state"] = want_state`
    > `        s["state_since"] = bar["ts"]`
    > `        s["pending_state"] = None`
    > `        s["pending_bars"] = 0`
    > `        transition_fired = True`

**(b) Evidence TTL = 24 bars (120 minutes).** Evidence credits are
aged out on every bar; a quiet market cools the score back toward
zero within two hours.
    CITE `/opt/tradingbot/nms_v3_classifier.py:127`:
    > `EVIDENCE_TTL_BARS = 24              # 120 min`

**(c) Explicit invalidation — fast exit, no persistence gate.** The
STRONG → RANGE rules and the EMERGING → RANGE rules fire same-bar.
    CITE `/opt/tradingbot/nms_v3_classifier.py:1114-1125` for R1/R2/R3:
    > `def _r1_up_invalid(s: Dict[str, Any], bar: Dict[str, Any]) -> bool:`
    > `    hls = [sw for sw in s["confirmed_swings"]`
    > `           if sw["kind"] == "L" and sw["confirmed_at"] <= bar["ts"]]`
    > `    if len(hls) < 2: return False`
    > `    recent = hls[-2:]`
    > `    return bar["c"] < min(sw["price"] for sw in recent)`
    > ``
    > `def _r2_up_invalid(s: Dict[str, Any], bar: Dict[str, Any]) -> bool:`
    > `    disp = bar["c"] - (s["london_open_price"] or bar["c"])`
    > `    return disp <= -R2_RELEASE_PIPS`
    > ``
    > `def _r3_invalid(s: Dict[str, Any], bar: Dict[str, Any]) -> bool:`
    > `    return s["range_reversals_count"] > MAX_RANGE_REVERSALS_AFTER_STRONG`

Numerically: R1 = close below the lower of the last two confirmed
higher-lows; R2 = displacement 10 pips against the trend from the
London open; R3 = more than 3 confirmed range-reversals in the
session. **CONFIRMED** CITE `nms_v3_classifier.py:132`
`R2_RELEASE_PIPS = 10.0` and `:129` `MAX_RANGE_REVERSALS_AFTER_STRONG = 3`.

EMERGING → RANGE on any one of (CITE L1073-1091):
- `up_score < EMERGING_ENTRY_THRESHOLD - 1` after TTL decay (so
  score drops below 2)
- close < `emerging_entry_price - 3p`
- a single confirmed lower-high (`C1:UP`) during the EMERGING window

### 4.3 Exhaustion Detector

**No debounce.** Each M5 close is a fresh classification over the
primitives' individual lookback windows (MACD window = 12 bars,
failed-ext lookback = 20 bars, compression lead = 20 bars). There
is no state carry-over. A single bar of no evidence drops the state
from CONFIRMED to NO_EXHAUSTION. (CONFIRMED CITE
`nms_exhaustion_detector.py:1143-1174`.)

### 4.4 WATCH_AND_WAIT

**Only sticky piece.** The driver persists the state to
`cache/nms_watch_state_<SYM>.json` and re-hydrates it on restart.
Transitions:

- **TREND_TRADING → WATCH_AND_WAIT.** All five must hold on the
  same bar: v3 is STRONG_* or EMERGING_*; exhaustion readiness=READY
  and freshness=FRESH; exhaustion state is DEVELOPING or CONFIRMED;
  exhaustion direction opposes the v3 trend; and at least one
  INDEPENDENT family is active. (CITE
  `/opt/tradingbot/nms_watch_state_machine.py:38-55`.)
- **WATCH_AND_WAIT → CONTINUATION_CONFIRMED** (per operator spec
  2026-10-27 pm + floor-break correction 2026-10-28 pm). Four must
  hold on the same bar: v3 unchanged in trend direction; exhaustion
  = NO_EXHAUSTION with READY+FRESH; companion `demonstrated_direction`
  positively matches the trend; **AND** the current close is
  **strictly past** the stored `watch_extreme_price`. If
  `watch_extreme_price` is None (missing persisted state) or
  `last_bar_close` is None, the gate **fails closed** — holds WATCH
  and seeds the extreme from the current bar's low/high. (CITE
  `/opt/tradingbot/nms_watch_state_machine.py:57-107`.)
- **WATCH_AND_WAIT → REVERSAL_CONFIRMED.** Fresh QM_REVERSAL signal
  under 900 s old, opposite direction to trend,
  `memory_defence_count >= 1`. V2_PICK is explicitly DISABLED as a
  reversal oracle. (CITE L109-116.)
- **REVERSAL_CONFIRMED → TREND_TRADING.** Either v3 flips (operator-
  sanctioned trend reversal), OR reversal evidence expires past
  freshness AND exhaustion has cleared. (CITE L118-123.)
- **Any → TREND_TRADING** on v3=UNKNOWN or STALE (defence in depth).

There is **no maximum WATCH duration**. A watch can sit indefinitely.

### 4.5 Unified Directional Authority

Has no persistent state. Each `evaluate()` call recomposes the four
snapshots. Snapshots older than 360 s or a replay-in-progress flag
force a BLOCK. (CITE `/opt/tradingbot/nms_directional_authority.py:
105-108` and `70-78`.)

---

## 5. How NMS recognises a trend — slow grind vs strong push

Trend recognition lives entirely in the v3 classifier. A single
`up_score`/`down_score` number is **not** used to distinguish grind
from push — but **STRONG vs EMERGING is**.

### 5.1 Up-score and down-score are built from eight evidence rules

Each rule adds or subtracts points into one of four "families"
(F-structural, F-structure, F-momentum, F-supporting). The
TTL-filtered sum, with family caps, is the per-direction score. The
family caps **are the key to the grind-vs-push distinction**:
    CITE `/opt/tradingbot/nms_v3_classifier.py:138-144`:
    > `FAMILY_CAPS = {`
    > `    "F-structural": 999,`
    > `    "F-momentum":   1,     # strict (base was 2)`
    > `    "F-supporting": 1,`
    > `    "F-structure":  999,`
    > `}`

F-momentum and F-supporting can contribute at most 1 point each to
the total per session. F-structural and F-structure are uncapped.
So a market that is grinding higher with momentum noise but no
structural breaks can reach at most `1 + 1 = 2` from the two capped
families — not enough even for EMERGING.

To reach EMERGING (score ≥ 3) **requires at least one firing from
the structural or structure families** (CITE L629-633 quoted in
§3.2). Those are E1 (opening-range break), E3 (close past a prior
confirmed swing), E4 (new confirmed higher-low), E5 (continuation
after a pullback), and the negative C1/C2 counter-swing events.

To reach STRONG (score ≥ 6 with structural anchor ≥ 2 confirmed
higher-lows, or E1 + E3 + E4) you need **multiple** confirmed
higher-lows inside a 2-hour window, i.e. a clearly stepped march,
not drift.

### 5.2 Slow grind vs strong push — the operative mechanism

The code does **not** carry an explicit "slow trend" state. Instead:

- A slow, steady grind that keeps closing higher but produces few
  new confirmed higher-lows will land in **EMERGING** (score 3-5
  with a structural anchor), and can sit there for the whole
  session.
- A strong push that keeps printing new higher-lows will promote to
  **STRONG** on the bar where two confirmed higher-lows (or the
  E1+E3+E4 combo) land inside the 24-bar TTL window.

The operator-locked `STRONG_OPPOSING_CAP = 1` (any score ≥ 2 on the
opposite side blocks STRONG) means a push with **even light
counter-structure** cannot be rated STRONG — it stays EMERGING.

**Additional signal of push intensity:** the `trend_strength` field
(not consumed anywhere as a gate; written to the result dict):
    CITE `/opt/tradingbot/nms_v3_classifier.py:393`:
    > `trend_strength = max(up_score, -down_score, 0)`

This is emitted in the per-bar classifier result but no production
module reads it. (CONFIRMED by grep.)

### 5.3 Companion NMS has no trend state at all

Companion NMS can only say `TRADABLE_NON_RANGE` (meaning
"non-chop, non-rotating") versus `PRODUCTIVE_RANGE` versus
`FLAT_OR_COMPRESSED` versus `UNKNOWN`. It makes **no distinction
between a slow grind and a strong push**. Both are
`TRADABLE_NON_RANGE`. The direction information in companion NMS
comes from the `demonstrated_direction` field (CHoCH-corrected
structural swings), which is categorical UP/DOWN/None with no
strength.

---

## 6. "Session trend" vs "normal market state"

Both exist as separate modules, serving different layers of the
decision.

### 6.1 "Normal market state" (NMS proper) — the 4-state regime

Lives in `normal_market_state.py` (piece 1). **Describes the
behaviour of the market**, not its direction:

- `PRODUCTIVE_RANGE` — ranging and tradable
- `FLAT_OR_COMPRESSED` — compressed / chopping
- `TRADABLE_NON_RANGE` — moving but not range-bound
- `UNKNOWN` — insufficient / stale data

Consumed by `central_execution_gate._delegate_normal_routing`
(CITE `central_execution_gate.py:2131-2170`) which uses the state
to pick an admission row from `permission_matrix`. A separate field
`demonstrated_direction` carries the UP/DOWN/None directional view.

### 6.2 "Session trend" — the sticky directional memory + v3 classifier

Lives in `session_trend.py` (piece 2). **Describes the direction
and strength of the London session**, independent of companion NMS:

- Keeps `prevailing` (UP / DOWN / RANGE / UNKNOWN) as a sticky
  session-level verdict for the BB-Bounce guard contract.
- Delegates the actual state machine to `nms_v3_classifier` (piece
  3), which returns NORMAL / RANGE / EMERGING_UP / EMERGING_DOWN /
  STRONG_UP / STRONG_DOWN.
- Publishes both `prevailing` (v2-mapped) and `v3_state` (full
  6-state) in the snapshot file.

CITE `/opt/tradingbot/session_trend.py:1-45` for the module intent:
> `"""session_trend.py — Persistent, independent session-trend memory. ...`
> `  "The session trend must have INDEPENDENT authority and memory"`
> `  "DOWN retained through M5 RANGE / PLATEAU / pullbacks"`
> `  "Do not merely extend the existing M5 direction epochs"`

### 6.3 How they relate to the six target states

The two **answer different questions** and the brief's six states
need pieces of both:

| Brief state | Which piece answers it |
|---|---|
| Ranging | Companion NMS (`PRODUCTIVE_RANGE`) + v3 (`RANGE`) |
| Emerging trend | Session trend / v3 only |
| Trend | Session trend / v3 only |
| Exhaustion | Exhaustion Detector only (piece 3) — independent of both |
| Possible reversal | WATCH_AND_WAIT (piece 4) — reads BOTH session trend + exhaustion |
| Consolidation | Companion NMS (`FLAT_OR_COMPRESSED`) + v3 refined label (`CONSOLIDATION`) |

So a new NMS that wants a single clean six-state enum will have to
**merge** the regime-type question with the direction-strength
question. The live code keeps them orthogonal (behaviour × direction
are two axes).

---

## 7. Records — files and three example lines each

### 7.1 Companion NMS — `/opt/tradingbot/logs/normal_state_journal.jsonl`

One row per symbol per completed M5 bar (rotated daily, 7 archives
retained). Three example lines verbatim from the head of the live
journal (bar close 2026-11-04T23:55 UTC):

```
{"anchor_ts": "2026-11-04T06:00:00+00:00", "bar_ts": "2026-11-04T23:55:00+00:00", "bars_since_anchor": 60, "demonstrated_direction": null, "demonstrated_evidence": {"choch_buffer_pips": 2.0, "choch_confirm_bars": 3, "choch_direction": null, "classify_structure_state": "NEUTRAL", "hh": false, "hl": true, "last_swing_high_price": 13972.85, "last_swing_low_price": 13970.9, "lh": true, "ll": false, "n_confirmed_highs": 6, "n_confirmed_lows": 5, "swing_n": 3}, "demonstrated_reason": "structure_neutral:mixed", "reason": "tradable_non_range:er10=0.1148,bb_w=16.1p,cross=0", "state": "TRADABLE_NON_RANGE", "symbol": "USDCAD", "written_at": "2026-11-05T00:00:05.188937+00:00"}
```
```
{"anchor_ts": "2026-11-04T06:00:00+00:00", "bar_ts": "2026-11-04T23:55:00+00:00", "bars_since_anchor": 60, "demonstrated_direction": "UP", "demonstrated_evidence": {"choch_buffer_pips": 2.0, "choch_confirm_bars": 3, "choch_direction": null, "classify_structure_state": "BULLISH", "hh": true, "hl": true, "last_swing_high_price": 13476.7, "last_swing_low_price": 13474.85, "lh": false, "ll": false, "n_confirmed_highs": 6, "n_confirmed_lows": 5, "swing_n": 3}, "demonstrated_reason": "structure_bullish:hh_hl", "reason": "flat_or_compressed:bb_w=7.5p,slope=0.2529166666663514,cross=0", "state": "FLAT_OR_COMPRESSED", "symbol": "GBPUSD", "written_at": "2026-11-05T00:00:05.311085+00:00"}
```
```
{"anchor_ts": "2026-11-04T06:00:00+00:00", "bar_ts": "2026-11-04T23:55:00+00:00", "bars_since_anchor": 60, "demonstrated_direction": "UP", "demonstrated_evidence": {"choch_buffer_pips": 2.0, "choch_confirm_bars": 3, "choch_direction": null, "classify_structure_state": "BULLISH", "hh": true, "hl": true, "last_swing_high_price": 11234.25, "last_swing_low_price": 11228.2, "lh": false, "ll": false, "n_confirmed_highs": 7, "n_confirmed_lows": 5, "swing_n": 3}, "demonstrated_reason": "structure_bullish:hh_hl", "reason": "tradable_non_range:er10=0.2353,bb_w=8.6p,cross=1", "state": "TRADABLE_NON_RANGE", "symbol": "EURUSD", "written_at": "2026-11-05T00:00:09.801787+00:00"}
```

### 7.2 Exhaustion Detector — `/opt/tradingbot/logs/nms_exhaustion.jsonl`

One row per symbol per completed M5 bar. Three example lines:

```
{"demonstrated_direction": null, "evaluation_ts": "2026-11-05T00:00:06.169673+00:00", "evidence": [{"detail": {"c": 13972.45, "h": 13974.45, "l": 13971.8, "lead_dir": "UP", "o": 13972.25}, "direction": "BUYING_EXHAUSTION", "family": "CANDLE_REJECTION", "timeframe": "M5", "timestamp_utc": "2026-11-04T23:55:00+00:00", "type": "SHOOTING_STAR"}], "exhaustion_direction": "BUYING_EXHAUSTION", "exhaustion_state": "EXHAUSTION_DEVELOPING", "families_active": ["CANDLE_REJECTION"], "freshness": "FRESH", "last_bar_ts": "2026-11-04T23:55:00+00:00", "nms_trend_state": "RANGE", "readiness": "READY", "reason": "single_family", "schema_version": "nms_exhaustion.v1", "symbol": "USDCAD"}
```
```
{"demonstrated_direction": "UP", "evaluation_ts": "2026-11-05T00:00:06.495368+00:00", "evidence": [{"detail": {"latest_abs_hist": 0.31464388690450906, "latest_sign": 1.0, "prior_max_abs_hist": 0.32101301029497886, "window": 12}, "direction": "BUYING_EXHAUSTION", "family": "MOMENTUM", "timeframe": "M5", "timestamp_utc": "2026-11-04T23:55:00+00:00", "type": "M5_MACD_CONTRACTION"}], "exhaustion_direction": "BUYING_EXHAUSTION", "exhaustion_state": "EXHAUSTION_DEVELOPING", "families_active": ["MOMENTUM"], "freshness": "FRESH", "last_bar_ts": "2026-11-04T23:55:00+00:00", "nms_trend_state": "RANGE", "readiness": "READY", "reason": "single_family", "schema_version": "nms_exhaustion.v1", "symbol": "GBPUSD"}
```
```
{"demonstrated_direction": "UP", "evaluation_ts": "2026-11-05T00:00:10.654548+00:00", "evidence": [{"detail": {"latest_abs_hist": 0.5258246543842879, "latest_sign": 1.0, "prior_max_abs_hist": 0.5456636671674804, "window": 12}, "direction": "BUYING_EXHAUSTION", "family": "MOMENTUM", "timeframe": "M5", "timestamp_utc": "2026-11-04T23:55:00+00:00", "type": "M5_MACD_CONTRACTION"}], "exhaustion_direction": "BUYING_EXHAUSTION", "exhaustion_state": "EXHAUSTION_DEVELOPING", "families_active": ["MOMENTUM"], "freshness": "FRESH", "last_bar_ts": "2026-11-04T23:55:00+00:00", "nms_trend_state": "RANGE", "readiness": "READY", "reason": "single_family", "schema_version": "nms_exhaustion.v1", "symbol": "EURUSD"}
```

### 7.3 WATCH_AND_WAIT — `/opt/tradingbot/logs/nms_watch_state.jsonl`

One row per symbol per completed M5 bar. Three example lines from
2026-11-05T23:55 UTC:

```
{"companion_direction": null, "evaluation_ts": "2026-11-06T00:00:06.791981+00:00", "exhaustion_direction": "NONE", "exhaustion_families_active": [], "exhaustion_freshness": "FRESH", "exhaustion_readiness": "READY", "exhaustion_state": "NO_EXHAUSTION", "exhaustion_trigger_direction": null, "last_bar_ts": "2026-11-05T23:55:00+00:00", "nms_v3_fresh": true, "nms_v3_state": "RANGE", "previous_state": "TREND_TRADING", "reason_code": "TREND_TRADING_NO_ESTABLISHED_TREND", "reason_detail": "v3_state=RANGE", "reversal_direction": null, "reversal_level_price": null, "reversal_level_type": null, "reversal_memory_defence_count": null, "reversal_oracle": null, "reversal_signal_bar_ts": null, "reversal_signal_fingerprint": null, "reversal_signal_ts": null, "schema_version": "nms_watch_state.v1", "state": "TREND_TRADING", "symbol": "USDCAD", "watch_extreme_price": null, "watch_triggered_at": null, "watched_trend_direction": null}
```
```
{"companion_direction": "UP", "evaluation_ts": "2026-11-06T00:00:08.428829+00:00", "exhaustion_direction": "SELLING_EXHAUSTION", "exhaustion_families_active": ["CANDLE_REJECTION"], "exhaustion_freshness": "FRESH", "exhaustion_readiness": "READY", "exhaustion_state": "EXHAUSTION_DEVELOPING", "exhaustion_trigger_direction": null, "last_bar_ts": "2026-11-05T23:55:00+00:00", "nms_v3_fresh": true, "nms_v3_state": "RANGE", "previous_state": "TREND_TRADING", "reason_code": "TREND_TRADING_NO_ESTABLISHED_TREND", "reason_detail": "v3_state=RANGE", "reversal_direction": null, "reversal_level_price": null, "reversal_level_type": null, "reversal_memory_defence_count": null, "reversal_oracle": null, "reversal_signal_bar_ts": null, "reversal_signal_fingerprint": null, "reversal_signal_ts": null, "schema_version": "nms_watch_state.v1", "state": "TREND_TRADING", "symbol": "EURUSD", "watch_extreme_price": null, "watch_triggered_at": null, "watched_trend_direction": null}
```
```
{"companion_direction": null, "evaluation_ts": "2026-11-06T00:00:09.657143+00:00", "exhaustion_direction": "SELLING_EXHAUSTION", "exhaustion_families_active": ["CANDLE_REJECTION"], "exhaustion_freshness": "FRESH", "exhaustion_readiness": "READY", "exhaustion_state": "EXHAUSTION_DEVELOPING", "exhaustion_trigger_direction": null, "last_bar_ts": "2026-11-05T23:55:00+00:00", "nms_v3_fresh": true, "nms_v3_state": "RANGE", "previous_state": "TREND_TRADING", "reason_code": "TREND_TRADING_NO_ESTABLISHED_TREND", "reason_detail": "v3_state=RANGE", "reversal_direction": null, "reversal_level_price": null, "reversal_level_type": null, "reversal_memory_defence_count": null, "reversal_oracle": null, "reversal_signal_bar_ts": null, "reversal_signal_fingerprint": null, "reversal_signal_ts": null, "schema_version": "nms_watch_state.v1", "state": "TREND_TRADING", "symbol": "GBPUSD", "watch_extreme_price": null, "watch_triggered_at": null, "watched_trend_direction": null}
```

### 7.4 Session trend (v3) — NOT JOURNALLED

The session-trend snapshot `/opt/tradingbot/cache/session_trend_<SYM>.json`
is **overwritten every bar**. There is no append-log. To reconstruct
v3_state history, replay is required. **UNSURE** whether this is
deliberate (snapshot-only contract) or an unfinished rollout. For a
new bot, journaling v3 explicitly is recommended.

---

## 8. Who reads NMS — producer→consumer map (file:line)

**CONFIRMED** by grep across `/opt/tradingbot`, `/opt/bb_bounce`,
`/opt/ema_pullback`.

### 8.1 In-process consumers (same Python process as autobot)

| Consumer file | Line | What it reads |
|---|---|---|
| `autobot.py` | 3943 | `import normal_market_state as _nms_bar; _nms_bar.on_bar_close(...)` — drives the companion NMS classification each bar |
| `autobot.py` | 10415 | `import normal_market_state as _nms_boot` — restore companion NMS on startup |
| `autobot.py` | 10449 | `import session_trend as _st_boot` — restore session-trend state on startup |
| `autobot.py` | 8207 | `_nmsd_bbb.permit_bounce(sym_u, _nmsd_side)` — BB Bounce authority consultation |
| `central_execution_gate.py` | 1156 | `import normal_market_state as _nms_rip; if _nms_rip.is_replay_in_progress(pair)` — replay guard |
| `central_execution_gate.py` | 1878 | `nms_choch_ctx = _nms.snapshot(pair) or {}` — read CHoCH context |
| `central_execution_gate.py` | 1975 | `import normal_market_state as _nms` — snapshot for TRADABLE_NON_RANGE delegate |
| `central_execution_gate.py` | 2131 | `market_snap = _nms.snapshot(pair); market_state = str(market_snap.get("state"))` — primary route decision |
| `central_execution_gate.py` | 2355 | `_nms_decision = _nms_v3_gate.check(...)` — v3 direction gate check |
| `central_execution_gate.py` | 1560 | `import nms_directional_authority as _nda` |
| `central_execution_gate.py` | 2023 | `import nms_directional_authority as _nda` |
| `candidate_time_context.py` | 103 | `import normal_market_state as _nms` — demonstrated_direction fallback for candidate direction |
| `strategy_dispatch_adapter.py` | 258 | `import normal_market_state as _nms; nms_snap = _nms.snapshot(pair)` — stamp candidate `market_state_snapshot` |
| `interaction_resolution.py` | 826 | `from normal_market_state import snapshot as _nms` — Stage 8 observability |
| `bounce_engine_live.py` | 661 | `import nms_second_gate as _nms2; _sg_dec = _nms2.check(...)` — stand-aside gate call |
| `bounce_engine_live.py` | 717 | `import nms_session_trend_direction as _nmsd` — then `_nmsd.permit_bounce(...)` / `permit_trend(...)` at L725/L727 |
| `bounce_engine_live.py` | 811 | `from nms_family_snapshot import load_family_snapshot as _lfs` + `from nms_admission_matrix import ...` |
| `nms_session_trend_direction.py` | 266 | `import nms_directional_authority as _nda; decision = _nda.evaluate(...)` — authority wrapper |
| `nms_session_trend_direction.py` | 344 | second `_nda.evaluate(...)` call (bounce path) |
| `nms_exhaustion_driver.py` | 358 | `import normal_market_state as _nms` — companion snapshot input to the detector |
| `nms_exhaustion_driver.py` | 379 | `auth = _st.session_authority(symbol)` — session-trend input |
| `nms_watch_state_driver.py` | 228 | `auth = _st.session_authority(symbol)` — session-trend input |
| `nms_watch_state_driver.py` | 240 | `blob = _st.load_session_authority_snapshot(symbol)` — fallback file read |
| `nms_directional_authority.py` | 407 | `auth = _st.session_authority(symbol)` — in-process session_trend read |
| `nms_directional_authority.py` | 430 | `import normal_market_state as _nms` — companion NMS snapshot |
| `nms_directional_authority.py` | 475 | companion NMS second consultation site |
| `nms_second_gate.py` | 118 / 155 | `import normal_market_state as _nms` — stand-aside refinement |

### 8.2 File-reader consumers (separate services on 161)

| Consumer file | Line | Snapshot file read |
|---|---|---|
| `/opt/bb_bounce/session_trend_guard.py` | 101 | `_env_snapshot_dir() / f"session_trend_{symbol}.json"` |
| `/opt/bb_bounce/open_sb_now.py` | 41 | `from session_trend_guard import should_block_order as _nms_should_block` |
| `/opt/bb_bounce/open_sb_now.py` | 92 | `_SESSION_TREND_PATH = "/opt/tradingbot/cache/session_trend_{sym}.json"` |
| `/opt/bb_bounce/open_sb_now.py` | 99 | `_WATCH_STATE_PATH = "/opt/tradingbot/cache/nms_watch_state_{sym}.json"` |
| `/opt/bb_bounce/nms_family_snapshot.py` | 222 | `_cache_dir / f"nms_watch_state_{symbol}.json"` |
| `/opt/ema_pullback/ema_pullback/nms_gate.py` | 107 | `self.snapshot_dir / f"session_trend_{symbol}.json"` |
| `/opt/ema_pullback/ema_pullback/watch_state_gate.py` | 5-7 | reads `nms_watch_state_<SYM>.json` |
| `/opt/tradingbot/paa/level_map.py` | 213-215 | consumes a `session_trend`-shaped dict to produce session H/L Levels |

### 8.3 Strategies gated by NMS (end-to-end)

Confirmed admissions blocked or admitted by NMS verdicts in recent
production logs (from this audit series):

- `TREND_V3`, `TREND_V3_UM`, `V3_EMA` — go through `_delegate_normal_routing` (`central_execution_gate.py:2131-2170`) + `permit_trend` (via `nms_session_trend_direction.py`)
- `GBPUSD_BB_BOUNCE`, `BB_BOUNCE` — go through `permit_bounce`
- `V3_BB`, `BOUNCE_TR`, `BOUNCE_SQ` — go through central gate + authority
- `EMA_PULLBACK` (standalone ema-pullback.service) — gated by nms_gate.py (session_trend) and watch_state_gate.py (W&W)

---

## 9. Code that looks wrong, unused, switched off, duplicated or contradictory

**Reporting these as observations, per the brief — no fixes.**

### 9.1 `trend_strength` field published but never read (unfinished rollout)

`nms_v3_classifier.py:393` publishes `trend_strength = max(up_score, -down_score, 0)` in the per-bar result. **Grep across `/opt/tradingbot`, `/opt/bb_bounce`, `/opt/ema_pullback` returns zero readers of this field** other than tests and the dashboard. If strength-based admission is intended, the wire is missing. **CONFIRMED.**

### 9.2 `m5_regime` (C4 refined label including `CONSOLIDATION` and `TRANSITION`) also unread

`nms_v3_classifier.py:361-392` computes `m5_regime` ∈ {`INSUFFICIENT_DATA`, `CONSOLIDATION`, `TRANSITION`} as an additive label. **No production gate reads it.** Dashboard-only. A new bot that intends to use `CONSOLIDATION` as a real state should wire a reader. **CONFIRMED.**

### 9.3 `NMS_V3_C3_REBALANCED_SCORING` off on live, the other three C-flags on

`.env` sets `NMS_V3_C1_CORRECTED_RECLAIM=1`, `C2_DIRECTIONAL_PENALTY=1`, `C4_MULTI_DIM=1` but does **not** set `NMS_V3_C3_REBALANCED_SCORING`, so C3 defaults OFF. This is a partially-deployed 2026-11-03 correction suite. **CONFIRMED.**

### 9.4 `NMS_SECOND_GATE_ENABLED` not present in live `.env`

`nms_second_gate.py` describes itself as `"master; default 0 (behaviour byte-identical to today)"` (CITE L21-22). The env file does not set the flag, so the second gate is **always bypassed**. The module (10 kB) is dead code in the live decision path. Check with the operator whether this is intentional. **CONFIRMED absence; UNSURE on intent.**

### 9.5 V2_PICK as a reversal oracle is reserved but hard-disabled

`nms_watch_state_machine.py:25-28` says V2 Pick is "DISABLED and cannot be an evidence source until operator authorisation". `REASON_RESOLVE_REVERSAL_V2` exists as a public reason code (L178) but no code path emits it. Half-wired. **CONFIRMED.**

### 9.6 `data_provenance` field is published as "UNKNOWN" every bar

The companion-NMS authority snapshot includes `data_provenance` but the writer never sets it to any non-UNKNOWN value on this host. The live GBPUSD snapshot at 09:15 reads `"data_provenance": "UNKNOWN"`. Appears to be an unfinished replay-vs-live marker. **CONFIRMED.**

### 9.7 LEVEL_REACTION family dark on this host

`nms_exhaustion_detector.py` lists `LEVEL_REACTION` as one of four INDEPENDENT families required to reach CONFIRMED. But the family only fires if the caller passes a level list — and **the live driver passes none**. Daily pivots **are** injected into session_trend via `session_trend_integration.py`, but no code path routes those pivots into the exhaustion driver. One of six evidence families is permanently inactive. **CONFIRMED.**

### 9.8 Session-trend v3 is not journalled

Only pieces 1, 3 and 4 have append-only journals. Session_trend overwrites the per-symbol snapshot every bar. Historical reproduction requires replaying the candle archive through `nms_v3_classifier.advance`. **CONFIRMED.**

### 9.9 Three "C-prefixed" concepts share names

v3 has rules `C1`/`C2`/`C3`/`C4` (counter-swing + reclaim), v3 **also** has feature flags `C1_CORRECTED_RECLAIM`/`C2_DIRECTIONAL_PENALTY`/`C3_REBALANCED_SCORING`/`C4_MULTI_DIM`, BB Bounce has states `C1`/`C2`/`C3`/`C4` (pierce/confirmation/break/intrabar), and the exhaustion family label `CANDLE_REJECTION` is often abbreviated. Naming collision — not a bug in itself but a documented source of confusion in prior audits. **CONFIRMED.**

### 9.10 Companion NMS has NO debounce; one-bar flicker shows up in state_epochs

A grep of the live `cache/nms_authority_GBPUSD.json` shows `state_epochs` with multiple **single-bar** entries (e.g. one bar of `PRODUCTIVE_RANGE` between 23:20 and 23:25 UTC on 2026-11-05). This is behaviourally correct per the code — but downstream readers that cache the state may see it toggle. A new bot should either add explicit hysteresis to the regime classifier or make all consumers idempotent to one-bar flips. **CONFIRMED.**

### 9.11 WATCH_AND_WAIT asymmetric gate on exhaustion

Entry condition accepts `DEVELOPING` OR `CONFIRMED`; exit condition requires `NO_EXHAUSTION` with READY+FRESH. A CONFIRMED exhaustion that decays to DEVELOPING cannot clear the watch — only a full collapse to NO_EXHAUSTION can. **CONFIRMED. UNSURE** whether intentional.

### 9.12 Two separate helpers named `session_trend_guard.py`

`/opt/tradingbot/session_trend_guard.py` (7,366 B, 2026-10-12) and `/opt/bb_bounce/session_trend_guard.py` are **different files** doing the same job on two different runtimes. Duplicated implementation — when the contract changes, both must be updated by hand. **CONFIRMED.**

### 9.13 `nms_v3_direction_gate.py` and `nms_directional_authority.py` partially overlap

Both consult v3_state for direction-admission decisions. `nms_v3_direction_gate` is invoked at `central_execution_gate.py:2355`, and `nms_directional_authority` is invoked at `:1560` and `:2023`. Two gates reading the same source, applied at different points in the gate stack — not a bug but a complexity that a new bot can collapse into one. **CONFIRMED.**

### 9.14 `demonstrated_direction.py` is an orphan relative to NMS

`/opt/tradingbot/demonstrated_direction.py` (23 kB) is a thin Stage-9 normalisation layer that wraps `direction_state.get_snapshot(pair)`. The module docstring (CITE L30-37) states it has zero execution authority. **It is not read by the five NMS pieces.** It belongs to the Build-1 Stage-9 observability pathway, not NMS. A new bot can safely ignore it unless replicating Build-1. **CONFIRMED.**

### 9.15 Uncommitted +275 / +52 line patches in `nms_v3_classifier.py` and `session_trend.py`

Live tree has uncommitted modifications vs HEAD. The C1-C4 correction suite (§9.3) and the `m5_regime` label (§9.2), plus the C6 day-rollover reset, are **only** in the live tree — not in the committed repo. A redeploy from HEAD would silently revert all four corrections. **CONFIRMED.**

---

## 10. Live `.env` values for every NMS switch (verbatim)

From `/opt/tradingbot/.env` (CONFIRMED — read this audit):

```
NMS_V3_DIRECTIONAL_GATE_ENABLED=1
NMS_V3_H1_ADMISSION_ENABLED=1
NMS_V3_H1_ADMISSION_FAIL_POLICY=closed
NMS_EXHAUSTION_DETECTOR_ENABLED=1
NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED=1
NMS_WATCH_AND_WAIT_ENABLED=1
NMS_V3_C6_DAYROLL_RESET=1
NMS_V3_C1_CORRECTED_RECLAIM=1
NMS_V3_C2_DIRECTIONAL_PENALTY=1
NMS_V3_C4_MULTI_DIM=1
NMS_RANGE_TM_ENABLED=1
NMS_RANGE_TM_SHADOW_MODE=0
NMS_RANGE_TM_SYMBOLS=GBPUSD
NMS_RANGE_TM_STATE_DIR=/opt/tradingbot/state/nms_range_tm
NMS_RANGE_TM_TICK_INTERVAL_S=2.0
NMS_RANGE_TM_LOW_MOD_THRESHOLD=15.0
NMS_RANGE_TM_TARGET_LOW_MOD=8.0
NMS_RANGE_TM_TARGET_HIGH=10.0
NMS_RANGE_TM_BE_PLUS_BUFFER_PIPS=1.0
REGIME_MAX_HOLD_ENABLED=0
REGIME_STRONG_TREND_ADX_MIN=17
CHOP_MODE_ENABLED=1
CHOP_MODE_BB_ONLY=1
CHOP_MODE_FORCE_SQUEEZE=1
CHOP_BREAK_BUFFER_PIPS=2.5
CHOP_RELEASE_ON_REGIME=0
```

Switches that affect NMS but are NOT in `.env` (so defaults apply):

- `NMS_V3_C3_REBALANCED_SCORING` → default `0` (OFF)
- `NMS_SECOND_GATE_ENABLED` → default `0` (OFF)
- `V3_BB_RANGE_ONLY_ENABLED` → default `0` (OFF)
- `NMS_DIRECTION_CHOCH_AUTHORITY_ENABLED` → default `1` (ON)
- `NMS_DIRECTION_CHOCH_CONFIRM_BARS` → default `3`
- `NMS_DIRECTION_CHOCH_BUFFER_PIPS` → default `2.0`
- `NORMAL_STATE_ANCHOR_HOUR` → default `6`
- `NORMAL_STATE_MIN_BARS` → default `12`
- `NORMAL_STATE_MIN_ENRICH_BARS` → default `25`
- `NORMAL_STATE_ER_MAX_RANGE` → default `0.5`
- `NORMAL_STATE_BB_MIN_RANGE_PIPS` → default `8.0`
- `NORMAL_STATE_CROSS_MIN_RANGE` → default `2`
- `CHOP_BB_WIDTH_MAX_PIPS` → default `8.0`
- `CHOP_SLOPE_LOOKBACK` → default `6`
- `CHOP_SLOPE_MAX_PIPS_PER_BAR` → default `0.5`
- `NMS_EXHAUSTION_MIN_BARS` → default `25`
- `NMS_EXHAUSTION_STALENESS_SECS` → default `360`
- `NMS_WATCH_SNAPSHOT_MAX_AGE_SECONDS` → default `360`
- `NMS_UNIFIED_AUTHORITY_MAX_AGE_SECONDS` → default `360`

---

## UNSURE list

- Whether `trend_strength` and `m5_regime` are intentionally
  observability-only, or unfinished wire-ups. (§9.1, §9.2)
- Original design intent for the `data_provenance` field. (§9.6)
- Whether the WATCH exit asymmetry (CONFIRMED→DEVELOPING does not
  clear the watch) is intentional. (§9.11)
- Whether session-trend v3's absence from the append-only journals
  is intentional (snapshot-only contract) or an unfinished rollout.
  (§9.8)
- Whether the operator intends `NMS_SECOND_GATE_ENABLED` to stay OFF
  permanently. (§9.4)
- Whether having two `session_trend_guard.py` files is deliberate
  (process isolation) or duplication to be collapsed. (§9.12)
- Whether the uncommitted on-disk corrections to v3 + session_trend
  are a staged commit or an abandoned branch. (§9.15)

---

*End of audit.*
