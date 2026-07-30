# Briefing pipeline audit — AutoBot-FXi (144)

**Date:** 2026-07-30 · **Mode:** investigate-only (no code, config or service changes)
**Scope:** briefing level generation, trading frequency, executor blockers, direction model.
**Window for frequency/blocker analysis:** the last 20 UTC trading days, **2026-07-03 → 2026-07-30**.

Evidence sources used, in full:

| Source | Path / command |
|---|---|
| Briefing artifacts (v4, the ones BRIEFING_EXECUTION consumes) | `/opt/tradingbot/logs/briefing_<PAIR>_<DATE>_<Session>.json` |
| Briefing artifacts (v2 shadow engine) | `/opt/tradingbot/briefings/v2/<DATE>/<SESSION>/<PAIR>.json` |
| Briefing artifacts (v5 FXi engine) | `/opt/tradingbot/briefings/v5_fxi/briefing_<PAIR>_<DATE>_<Session>.json` |
| Executor + scheduler logs | `journalctl -u autobot --since '2026-07-01' -o short-iso` (3.0 GB journal; full scan) |
| Trade outcomes | `/opt/tradingbot/logs/signal_log.jsonl` |
| Guard evaluations | `/opt/tradingbot/logs/guards_observed.jsonl` |
| Code | `morning_briefing.py`, `briefing_execution.py`, `briefing_direction.py`, `strategy_logic.py`, `trade_executor.py`, `guards/*` |

All commands were run as `autobot`. Nothing was restarted, written or committed except this document.

---

## 0. Two facts that condition everything below

### 0.1 The running process is NOT running today's code or today's `.env`

```
$ systemctl show autobot -p ExecMainStartTimestamp -p ExecMainPID
ExecMainStartTimestamp=Wed 2026-07-29 06:41:48 UTC
ExecMainPID=470536

$ ls -la --time-style=full-iso briefing_execution.py .env
-rw-rw-r-- 1 autobot autobot 131981 2026-07-30 13:47:58.830068249 +0000 briefing_execution.py
-rw-rw-r-- 1 autobot autobot  26525 2026-07-30 13:48:15.004307926 +0000 .env

$ git log -1 --format='%h %ad %s' --date=iso HEAD
8778a7d 2026-07-30 13:52:33 +0000 feat(briefing-exec): wire cascade_disagrees as a live hard block

$ git log -1 --format='%h %ad %s' --date=iso --before='2026-07-29 06:41:47' -- briefing_execution.py
4fea324 2026-06-16 16:47:26 +0000 fix(briefing-exec): fail sweep leg closed when since-arm window unavailable
```

The Python module object for `briefing_execution` was created when the process started on **2026-07-29 06:41:48**. `briefing_execution.py` and `.env` were both edited **2026-07-30 ~13:48**, i.e. ~31 hours later. Python does not reload modules and `.env` is read at import time.

**Therefore the cascade-disagree hard block committed today (`8778a7d`) is on disk but is not executing.** Every statement in Q3/Q4 below about the cascade gate refers to code that will only become live at the next restart. Everything else in this report reflects code that predates the process start and *is* live.

### 0.2 The briefing is an LLM product, not a computed indicator

`morning_briefing.py:3534` — the whole briefing (levels, plans, targets, biases) is produced by one Anthropic API call per pair per session:

```python
logger.info(f"[morning_briefing] {sym}/{session}: calling Anthropic API")
briefing = _call_anthropic(package)
```

Python code assembles a data package and *validates/repairs* the model's output. It does not compute the levels. This is the single most important structural fact for Q1 and Q4.

---

## Q1 — LEVEL SPACING

### 1.1 Where levels come from

**Scheduler.** `morning_briefing.py:84-85` — two runs per weekday, in-process thread (no cron, no systemd timer on this box; `systemctl list-timers | grep -i brief` returns nothing):

```python
_SESSIONS_GMT: List[tuple] = [(5, 30, "London"), (12, 30, "NY")]
_SESSIONS_BST: List[tuple] = [(5, 30, "London"), (12, 30, "NY")]
```

**Raw source data fed to the model** (`morning_briefing.py:754-808`). These are the only price anchors the model is given:

```python
    # BB(20,2) from H1 closes — primary entry levels for BRIEFING_LIQUIDITY
    bb_upper = None
    bb_lower = None
    if len(h1_closes) >= 20:
        _bb_window = h1_closes[-20:]
        _bb_sma = sum(_bb_window) / 20.0
        _bb_var = sum((x - _bb_sma) ** 2 for x in _bb_window) / 20.0
        _bb_std = _bb_var ** 0.5
        bb_upper = round(_bb_sma + 2 * _bb_std, 5)
        bb_lower = round(_bb_sma - 2 * _bb_std, 5)
...
    prev_day_high = prev_day_low = prev_day_close = None
    week_high = week_low = prev_week_high = prev_week_low = None
    if d1_candles:
        prev = d1_candles[-1]
        prev_day_high  = round(float(prev.get("high",  0)), 5)
        prev_day_low   = round(float(prev.get("low",   0)), 5)
        prev_day_close = round(float(prev.get("close", 0)), 5)
    # Current week = last 5 completed weekday candles, prev week = 5 before
    if len(d1_candles) >= 5:
        this_week = d1_candles[-5:]
        week_high = round(max(float(c.get("high", 0)) for c in this_week), 5)
        week_low  = round(min(float(c.get("low",  0)) for c in this_week), 5)
    if len(d1_candles) >= 10:
        last_week = d1_candles[-10:-5]
        prev_week_high = round(max(float(c.get("high", 0)) for c in last_week), 5)
        prev_week_low  = round(min(float(c.get("low",  0)) for c in last_week), 5)
```

Derivation per level type:

| Level type / confluence tag | Source data | Formula | Lookback |
|---|---|---|---|
| `BB_UPPER` / `BB_LOWER` | H1 closes (`_TF_CTX._h1_closed`) | SMA20 ± 2·σ(20) | 20 H1 bars |
| `PREV_DAY_HIGH/LOW/CLOSE` | `cache/htf/{SYM}_D1.json` (IG REST DAY), weekend-filtered by `_load_full_day_d1_candles` | `d1_candles[-1].high/.low/.close` | 1 completed trading day |
| `WEEK_HIGH/LOW` | same D1 cache | `max/min` over `d1_candles[-5:]` | 5 completed weekdays |
| `PREV_WEEK_HIGH/LOW` | same D1 cache | `max/min` over `d1_candles[-10:-5]` | 5 weekdays, offset 5 |
| `EMA_50` / `EMA_200` | H1 closes | `_emas_from_closes(h1_closes)`; only the *distance* is given to the model (`price_vs_h1_ema50_pips`, `morning_briefing.py:801`) | 120 H1 bars |
| `SWING_HIGH/LOW`, `ASIAN_HIGH/LOW`, `ROUND_NUMBER`, `DAILY_PIVOT`, `VWAP` | **not computed anywhere in Python** — the model infers them from the raw H1/H4/D1 candle arrays in the prompt package | n/a |

The model is then asked for the ranked array (`morning_briefing.py:1766-1796`):

```
7. RANKED LEVELS (`levels` array — primary output):
List ONLY the 4-6 most significant price levels for today, ranked by importance.
Do not list secondary or noise levels. Each level must have real confluence and a
specific justification. Adjacent ranks must be at least 15 pips apart in price — if
two candidate levels are closer than 15p, pick the more significant one and drop the
other.
```

Everything downstream (`key_levels`, `major_levels`, `liquidity_pools`, `no_trade_zones`) is *derived* from that array — `_populate_legacy_levels()` at `morning_briefing.py:2046`, `_apply_deterministic_ntz()` at `2223`. Plan targets are snapped onto the same grid by `_snap_plan_targets_to_levels()` at `2130`.

Scale note: on this box prices are IG CFD points ×10⁴ (×10² for JPY). `pair_config.py:19-22` sets

```python
POINTS_PER_PIP: Dict[str, float] = {
    "GBPUSD": 1.0, "EURUSD": 1.0, "USDJPY": 1.0, "USDCAD": 1.0, "GBPJPY": 1.0,
}
```

so 1 point = 1 pip and every pip figure below is a true pip. **No unit/scaling defect was found in the level path.**

### 1.2 The last 10 generated briefings — levels and adjacent spacing

Selected by mtime, `logs/briefing_*_2026-*.json`. Gaps are between **price-adjacent** levels (the spacing a trader actually experiences).

**1. `briefing_USDJPY_2026-07-29_NY.json`** — `briefing_time=2026-07-29T12:34:17Z`

| rank | price | type | confluence |
|---|---|---|---|
| 1 | 16395.20 | RESISTANCE | PREV_DAY_HIGH, WEEK_HIGH, BB_UPPER |
| 2 | 16327.80 | SUPPORT | PREV_DAY_LOW, SWING_LOW |
| 3 | 16371.30 | PIVOT | EMA_50, SWING_LOW |
| 4 | 16344.41 | SUPPORT | BB_LOWER |
| 5 | 16299.00 | SUPPORT | WEEK_LOW |

Gaps (price order): r5→r2 **28.8p**, r2→r4 **16.6p**, r4→r3 **26.9p**, r3→r1 **23.9p**

**2. `briefing_USDCAD_2026-07-29_NY.json`** — `briefing_time=2026-07-29T12:35:45Z`

| rank | price | type | confluence |
|---|---|---|---|
| 1 | 14095.10 | PIVOT | PREV_DAY_CLOSE, EMA_50 |
| 2 | 14113.20 | RESISTANCE | BB_UPPER, SWING_HIGH |
| 3 | 14087.10 | SUPPORT | BB_LOWER, SWING_LOW |
| 4 | 14129.05 | RESISTANCE | PREV_DAY_HIGH, WEEK_HIGH |
| 5 | 14067.50 | SUPPORT | SWING_LOW, ROUND_NUMBER |

Gaps: r5→r3 **19.6p**, r3→r1 **8.0p ← under the 12p tolerance**, r1→r2 **18.1p**, r2→r4 **15.8p**

**3. `briefing_GBPUSD_2026-07-30_London.json`** — `2026-07-30T05:30:04Z`
r4 13260.36(S) → r2 13279.15(S) **18.8p** → r5 13317.11(S) **38.0p** → r3 13366.75(PIV) **49.6p** → r1 13387.25(R) **20.5p**

**4. `briefing_EURUSD_2026-07-30_London.json`** — `2026-07-30T05:31:27Z`
r5 11353.085(S) → r2 11374.50(S) **21.4p** → r3 11414.18(S) **39.7p** → r1 11474.65(R) **60.5p** → r4 11497.68(R) **23.0p**

**5. `briefing_USDJPY_2026-07-30_London.json`** — `2026-07-30T05:33:25Z` (only 3 levels survived)
r2 16323.20(S) → r3 16358.60(PIV) **35.4p** → r1 16390.80(R) **32.2p**

**6. `briefing_USDCAD_2026-07-30_London.json`** — `2026-07-30T05:35:04Z`
r6 14000.00(S) → r1 14023.75(S) **23.8p** → r4 14037.35(PIV) **13.6p** → r5 14058.45(R) **21.1p** → r3 14082.30(R) **23.8p** → r2 14106.95(R) **24.7p**

**7. `briefing_GBPUSD_2026-07-30_NY.json`** — `2026-07-30T12:30:53Z`
r5 13279.15(S) → r4 13305.19(S) **26.0p** → r3 13338.15(S) **33.0p** → r6 13368.13(PIV) **30.0p** → r1 13387.25(R) **19.1p** → r2 13401.26(R) **14.0p**

**8. `briefing_EURUSD_2026-07-30_NY.json`** — `2026-07-30T12:32:22Z`
r5 11405.91(S) → r3 11452.29(S) **46.4p** → r1 11467.25(S) **15.0p** → r2 11484.10(R) **16.9p** → r4 11500.00(R) **15.9p**

**9. `briefing_USDJPY_2026-07-30_NY.json`** — `2026-07-30T12:33:57Z`
r6 16229.00(S) → r5 16282.70(S) **53.7p** → r3 16295.63(S) **12.9p** → r2 16330.60(PIV) **35.0p** → r1 16364.90(R) **34.3p** → r4 16390.80(R) **25.9p**

**10. `briefing_USDCAD_2026-07-30_NY.json`** — `2026-07-30T12:36:55Z`
r1 14023.75(S) · r4 14000.00(S) · r2 14068.65(R) · r3 14106.95(R) · r5 14085.51(R BB_UPPER)
Gaps: 14000.00 → 14023.75 **23.8p** → 14068.65 **44.9p** → 14085.51 **16.9p** → 14106.95 **21.4p**

### 1.3 Systemic measurement over the whole 20-day window

All 96 briefing artifacts dated ≥ 2026-07-03, 326 price-adjacent level pairs:

```
total price-adjacent pairs: 326
min gap 7.2p   median gap 20.0p
pairs < 12p (the enforced env tolerance): 12
pairs < 15p (the tolerance the prompt states): 62   (19.0%)
```

Breakdown of the 62 sub-15p pairs:

```
  ...of which rank-ADJACENT (checked by the validator): 13
  ...of which rank-NON-adjacent                       : 49   <-- invisible to the rank-adjacency check
  ...of which same TYPE (collapsible)                 : 40
  ...of which involve a PIVOT                         : 18   <-- never collapsible (type mismatch)
```

The 12 pairs inside the enforced 12-pip tolerance:

```
briefing_EURUSD_2026-07-21_London.json  r4(PIVOT) 11422.4  ↔ r2(RESISTANCE) 11429.7   7.4p
briefing_USDJPY_2026-07-21_London.json  r2(SUPPORT) 16238.5 ↔ r4(PIVOT) 16249.2      10.7p
briefing_USDJPY_2026-07-21_London.json  r4(PIVOT) 16249.2  ↔ r1(RESISTANCE) 16259.7  10.5p
briefing_USDJPY_2026-07-21_NY.json      r2(SUPPORT) 16260.1 ↔ r4(RESISTANCE) 16270.4 10.3p
briefing_EURUSD_2026-07-23_London.json  r1(SUPPORT) 11406.5 ↔ r3(PIVOT) 11413.7       7.2p
briefing_EURUSD_2026-07-23_NY.json      r1(PIVOT) 11409.2  ↔ r6(RESISTANCE) 11420.8  11.6p
briefing_USDCAD_2026-07-24_London.json  r2(SUPPORT) 14068   ↔ r5(PIVOT) 14079.5      11.5p
briefing_USDCAD_2026-07-24_London.json  r5(PIVOT) 14079.5  ↔ r1(RESISTANCE) 14089.3   9.8p
briefing_USDJPY_2026-07-27_NY.json      r3(PIVOT) 16385.8  ↔ r1(RESISTANCE) 16394.2   8.4p
briefing_USDJPY_2026-07-28_NY.json      r3(SUPPORT) 16380   ↔ r1(RESISTANCE) 16391.3 11.3p
briefing_EURUSD_2026-07-29_NY.json      r4(PIVOT) 11393.9  ↔ r2(RESISTANCE) 11405.4  11.5p
briefing_USDCAD_2026-07-29_NY.json      r3(SUPPORT) 14087.1 ↔ r1(PIVOT) 14095.1       8.0p
```

**10 of these 12 involve a `PIVOT`.**

### 1.4 Why adjacent levels land close together — the responsible code path

**Yes, de-duplication and minimum-spacing rules exist.** Both are in `morning_briefing.py`. They have three specific holes.

**Tolerance value in force** (`.env:127`):

```
BRIEFING_LEVEL_TOLERANCE_PIPS=12
```

read at `morning_briefing.py:171-173`:

```python
_BRIEFING_LEVEL_TOLERANCE_PIPS = float(
    os.getenv("BRIEFING_LEVEL_TOLERANCE_PIPS", "15") or 15.0
)
```

**Hole 1 — the collapse rule only fires on identical `type`.** `morning_briefing.py:2280-2309`:

```python
def _collapse_close_levels(
    cleaned: List[Dict[str, Any]],
    ppp: float,
    min_sep_pips: float,
) -> List[Dict[str, Any]]:
    """Drop higher-rank twins of any level within ``min_sep_pips`` of a kept
    lower-rank one on the SAME side (RESISTANCE vs SUPPORT). Cross-side
    near-pairs survive — they're directional opposites.
    """
    ...
    for lv in sorted(cleaned, key=lambda x: int(x.get("rank", 9999))):
        twin = False
        for kept in keep:
            if kept.get("type") != lv.get("type"):
                continue
```

`_LEVEL_TYPES` (`morning_briefing.py:2254`) is `{"RESISTANCE", "SUPPORT", "PIVOT"}`. `PIVOT` is a third type, so a PIVOT can never collapse against a SUPPORT or a RESISTANCE no matter how close it is. The docstring's stated intent ("cross-side near-pairs survive — they're directional opposites") is defensible for S-vs-R; it is not defensible for PIVOT, which by definition sits *at* current price and therefore right next to whichever S or R is nearest. This produces 18 of the 62 tight pairs — including the 8.0p `USDCAD 2026-07-29 NY` pair and the 7.2p / 7.4p worst cases.

**Hole 2 — the post-collapse separation check compares rank-neighbours, not price-neighbours.** `morning_briefing.py:2460` sorts by rank, then `2481-2488`:

```python
    cleaned.sort(key=lambda lv: lv["rank"])
...
        for i in range(len(cleaned) - 1):
            sep = abs(cleaned[i]["price"] - cleaned[i + 1]["price"]) / ppp
            if sep < _BRIEFING_LEVEL_TOLERANCE_PIPS:
                errors.append(
                    f"rank {cleaned[i]['rank']} ({cleaned[i]['price']:g}) and rank "
                    f"{cleaned[i + 1]['rank']} ({cleaned[i + 1]['price']:g}) are only "
                    f"{sep:.1f} pips apart (min {_BRIEFING_LEVEL_TOLERANCE_PIPS:g})"
                )
```

`rank` is **importance order**, not price order. Two levels that are price-neighbours are usually *not* rank-neighbours, so the loop simply never compares them. Measured: **49 of the 62 sub-15p pairs are rank-non-adjacent and were therefore never examined.** The comment at `2462-2468` shows this was already partially diagnosed on 2026-06-02 and fixed only for the same-side case via `_collapse_close_levels`; the rank-vs-price axis mismatch in the check itself was left in place.

**Hole 3 — the prompt says 15 pips, the enforcement says 12.** Prompt (`morning_briefing.py:1769`): *"Adjacent ranks must be at least 15 pips apart"*. Enforcement uses `BRIEFING_LEVEL_TOLERANCE_PIPS=12`. Anything the model emits between 12.0p and 15.0p violates its own instruction and passes silently — **50 of the 62 tight pairs sit in that 12–15p band**.

**Not the cause.** Three hypotheses in the brief were tested and are *not* supported:

* *Duplicate sources stacking (pivot ≈ round number ≈ PDH).* Confluence tags are merged into one level entry, not emitted as separate levels — e.g. `2026-07-30 London GBPUSD` rank 1 carries `["PREV_DAY_HIGH","WEEK_HIGH","SWING_HIGH"]` as a single 13387.25 entry. Stacking is handled.
* *Narrow prior-day range feeding the formula.* Median price-adjacent gap across the window is 20.0p on a typical 100p daily range; the distribution is not compressed. The tight pairs are localised to PIVOT-adjacency, not to low-range days.
* *Unit/scaling issue.* `POINTS_PER_PIP` is 1.0 for every pair traded here and level prices are consistently in the ×10⁴/×10² point space (quoted above). No mis-scaling found.

**Downstream consequence.** The executor's level-proximity matcher uses a hard 8-pip radius (`briefing_liquidity.py:67-68`, `BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS` default 8, not overridden in `.env`). When two levels sit 7–12p apart, a single entry price is inside the radius of both, and `_match_levels_array` (`briefing_liquidity.py:283-285`) silently returns whichever is nearer. That gate is currently advisory (see Q3), so today the effect is cosmetic — but it is the mechanism by which tight levels would become ambiguous entries if the gate were re-enabled.

---

## Q2 — TRADING FREQUENCY

20 UTC trading days, 2026-07-03 → 2026-07-30. "Armed" counts `[BRIEFING-EXEC] … ARMED n plan(s)` messages in the journal. "Fired" is a broker-confirmed row in `signal_log.jsonl`.

| date | briefing generated? | plan/levels valid? | armed? | fired? (deal ref) | first gate that stopped it |
|---|---|---|---|---|---|
| 2026-07-03 Fri | **No** — 0 files | n/a | no | no | `[morning_briefing] GBPUSD/London: API HTTP error: 400 … {"message":"Your credit balance is too low to access the Anthropic API…"}` → `06:00:24 ⚠️ BRIEFING FAILED — all retries exhausted, strategies disabled for London` |
| 2026-07-06 Mon | **No** | n/a | no | no | same 400 credit error; `06:00:19 ⚠️ BRIEFING FAILED — all retries exhausted … London`, `13:00:26 … NY` |
| 2026-07-07 Tue | **No** | n/a | no | no | same 400 credit error; `06:00:47` / `13:00:38 ⚠️ BRIEFING FAILED` |
| 2026-07-08 Wed | **No** | n/a | no | no | same 400 credit error; `06:00:53` / `13:00:55 ⚠️ BRIEFING FAILED` |
| 2026-07-09 Thu | Yes 4L/4NY, first `05:30:51Z` | yes | 10 | **2** — `DEAL-50` 07:35:02 USDCAD SELL (−0.25p); `DEAL-51` 14:05:03 USDJPY BUY (+0.30p) | fired |
| 2026-07-10 Fri | **No** | n/a | no | no | `05:30:03 ❌ IG login error: HTTP error: 401 {"errorCode":"error.security.client-suspended"}` — process crash-looping, briefing scheduler never reached |
| 2026-07-13 Mon | **No** | n/a | no | no | `05:25:02 ❌ IG login error: HTTP error: 401 {"errorCode":"error.security.client-suspended"}` (full traceback: `autobot.py:5014 → ig_auth.py:408 → ig.create_session()`) |
| 2026-07-14 Tue | **No** | n/a | no | no | `05:30:04 ❌ IG login error: HTTP error: 401 {"errorCode":"error.security.client-suspended"}` |
| 2026-07-15 Wed | Yes 4L/4NY, `05:30:05Z` | yes | 12 | **1** — `DEAL-01` 07:20:03 GBPUSD BUY (−15.55p) | fired |
| 2026-07-16 Thu | Yes 4L/4NY, `05:30:58Z` | yes | 11 | **no** | direction-bias veto first at `05:34:17 [BRIEFING-EXEC] GBPUSD plan_id=London_2 … VETOED by direction-bias resolver \| plan_dir=SELL daily=BUY session=NEUTRAL → resolved=BUY`; surviving plans then blocked by `05:35:03 … skipped — phase2 5m close=13539.65000 did not confirm` (55 times) and `TREND_ENTRY fallback BLOCKED — plan entry_trigger_v2 not satisfied` (114 times) |
| 2026-07-17 Fri | **No** | n/a | 4 (stale NY plans from 07-16) | no | `[morning_briefing] GBPUSD/London: API HTTP error: 400 … credit balance is too low` + `06:01:14 ⚠️ BRIEFING FAILED`; the 07-16 NY plans that re-armed at 12:30 were then killed 35 184× by `plans skipped — briefing age … > PLAN_MAX_AGE_MIN=240` |
| 2026-07-20 Mon | Yes 4L/4NY, `05:30:14Z` | yes | 11 | **no** | `05:31:43 GBPUSD plan_id=London_1 … VETOED by direction-bias resolver \| plan_dir=SELL daily=BUY session=NEUTRAL → resolved=BUY` (7 vetoes that day, incl. all three USDCAD plans); rest died on `06:05:01 EURUSD TREND_ENTRY fallback BLOCKED — plan entry_trigger_v2 not satisfied … failed=['rsi(…)']` (228 occurrences) |
| 2026-07-21 Tue | Yes 4L/4NY, `05:30:13Z` | yes | 10 | **2** — `DEAL-03` 13:15:02 GBPUSD SELL (+2.05p); `DEAL-04` 13:25:03 USDCAD BUY (−12.05p) | fired |
| 2026-07-22 Wed | Yes 4L/4NY, `05:30:58Z` | yes | 12 | **4** — `DEAL-02` 08:20 USDJPY BUY (−13.80); `DEAL-06` 13:30 GBPUSD SELL (+0.55); `DEAL-07` 13:50 USDCAD SELL (−0.25); `DEAL-08` 15:25 USDJPY BUY (unresolved) | fired |
| 2026-07-23 Thu | Yes 4L/4NY but **London late**, first `10:13:38Z` (normal is 05:30) | yes | 17 | **2** — `DEAL-09` 11:50 USDJPY BUY (+35.10); `DEAL-05` 13:15 USDCAD BUY (+0.65) | fired; 3 further USDJPY NY_1 decisions at 12:50/12:55/13:00 were stopped downstream: `[DISPATCH] CS.D.USDJPY.TODAY.IP BUY BRIEFING_EXECUTION blocked — concurrent cap reached (1/1)` |
| 2026-07-24 Fri | Yes 4L/4NY, `05:30:20Z` | yes | 11 | **3** — `DEAL-20` 06:10 USDJPY BUY (−14.70); `DEAL-22` 13:05 USDJPY BUY (−15.20); `DEAL-21` 14:35 EURUSD SELL (+9.80) | fired |
| 2026-07-27 Mon | Yes 4L/4NY, `05:30:10Z` | yes | 9 | **2** — `DEAL-23` 06:55 EURUSD SELL (+40.10); `DEAL-28` 08:05 USDJPY BUY (+21.80) | fired |
| 2026-07-28 Tue | Yes 4L/4NY, `05:30:33Z` | yes | 15 | **1** — `DEAL-19` 14:30 GBPUSD SELL (+0.95) | fired |
| 2026-07-29 Wed | Yes 4L/4NY, `05:30:45Z` | yes | 13 | **no** | `05:32:09 GBPUSD plan_id=London_1 … VETOED by direction-bias resolver \| plan_dir=BUY daily=SELL session=NEUTRAL → resolved=SELL` (10 vetoes that day, hitting USDJPY London_1+NY_1 and USDCAD London_1+NY_1); survivors blocked by `05:35:02 EURUSD plan_id=NY_1 … skipped — phase2 5m close=11398.35000 did not confirm` (45×) and `TREND_ENTRY fallback BLOCKED — plan entry_trigger_v2 not satisfied` (233×) |
| 2026-07-30 Thu | Yes 4L/4NY, `05:30:04Z` | yes | 15 | **1** — `DEAL-47` 09:20:02 GBPUSD SELL (−22.15p) | fired |

**Totals for the window:** 20 trading days · **12 days with a briefing** · 8 days with none · **18 broker-confirmed fires** on 9 days · 11 no-trade days, every one evidenced above.

The single largest cause of no-trade days is not a strategy gate at all — it is **briefing non-production**: 5 days lost to an Anthropic billing failure, 3 days lost to an IG account suspension. That is 8 of 11 no-trade days (73%).

---

## Q3 — BLOCKERS

### 3.1 The fire path in code order

`strategy_logic.py:1965-1989` calls the executor first, every tick:

```python
        from briefing_execution import BriefingExecutionStrategy, BRIEFING_EXECUTION_ENABLED as _BE_ENABLED
        if _BE_ENABLED and _regime_allows("BRIEFING_EXECUTION"):
```

(`_regime_allows` is `strategy_logic.py:1953-1955`: `# Regime gating disabled — observation only, no strategy blocking` / `return True`. It is a no-op.)

| # | Gate | Code | Config in force | Blocks in last 20 days |
|---|---|---|---|---|
| 1 | Strategy enabled | `briefing_execution.py:112` | `.env:151 BRIEFING_EXECUTION_ENABLED=1` | 0 |
| 2 | Regime router | `strategy_logic.py:1953` | hard-coded `return True` | 0 (inert) |
| 3 | `check_expires_at` — drop plans past `expires_at` | `briefing_execution.py:1569-1598` | plan-authored `expires_at` | 14 (`resolver: CONDITIONAL branch plan expired`) |
| 4 | **Plan max age** | `briefing_execution.py:1716-1732` | `.env:571 PLAN_MAX_AGE_MIN=240`; `PLAN_MAX_AGE_ENABLED` unset → default `1` | **200 943 log lines** |
| 5 | Per-session lockout | `briefing_execution.py:1736-1745` | by design, one shot per session | 25 |
| 6 | `_dormant` (London condition false) | `briefing_execution.py:1746-1755` | n/a | 0 |
| 7 | **Direction-bias resolver (arm-time)** | `briefing_execution.py:1768-1789` | `.env:383 BRIEFING_EXEC_DIRECTION_BIAS_ENABLED=1` | **82** |
| 8 | Sweep detection / zone-edge fallback | `briefing_execution.py:1806-1844` | n/a | 67 sweeps seen |
| 9 | TREND_ENTRY needs 2 closes + min minutes | `briefing_execution.py:1861-1863` | `BRIEFING_TREND_ENTRY_MIN_MINUTES` default 30 (`briefing_execution.py:48`) | not separately logged |
| 10 | **TREND_ENTRY fallback requires structured trigger** | `briefing_execution.py:1879-1902` | `BRIEFING_EXEC_FALLBACK_REQUIRE_TRIGGER` unset → default `1` | **1 655** |
| 11 | TREND_ENTRY drift cap 10p past zone | `briefing_execution.py:1910-1917` | hard-coded `10.0` | 68 |
| 12 | TREND_ENTRY needs a target ahead of entry | `briefing_execution.py:1929-1936` | n/a | 0 |
| 13 | Levels-array proximity | `briefing_execution.py:1963-1982`, `2119-2138` | `BRIEFING_EXEC_LEVELS_ARRAY_GATE_ENABLED` unset → default `0` = **advisory only** (`briefing_execution.py:147-149`); radius `BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS` default 8 | 0 blocks / **120 advisory misses** |
| 14 | **`entry_trigger_v2` gate** | `briefing_execution.py:2309-2353` | `.env:399 BRIEFING_EXEC_TRIGGER_V2_MODE=live` | **133** |
| 15 | Phase-2 5M close confirmation | `briefing_execution.py:2093-2117` | n/a | **766** |
| 16 | Plan has no targets | `briefing_execution.py:2153-2159` | n/a | 0 |
| 17 | **Cascade-disagree** | `briefing_execution.py:2570-2611` | `.env:568 BRIEFING_EXEC_CASCADE_GATE_ENABLED=1` | **0 — not loaded in the running process (see §0.1)** |
| 18 | Fire-time direction-bias re-check | `briefing_execution.py:2613-2724` | same flag as #7 | 0 |
| 19 | `[FIRE-SHADOW]` H1 authority | `briefing_execution.py:2648-2713` | `.env:567 FIRE_TIME_HTF_SHADOW_ENABLED=1` — comment: `# shadow logging only — never blocks` | **0 by construction** (21 evaluations, all `verdict=WOULD_ALLOW`) |
| 20 | **Guards stack** (`stale_briefing`, `news_blackout`, `priced_in`) | `briefing_execution.py:2028-2048` / `2219-2242`; `guards/registry.py:14` | `.env:527 GUARDS_ENABLED=1`, `.env:528 GUARDS_OBSERVABLE_ONLY=1`, `.env:569 NEWS_BLACKOUT_ENFORCED=1`, `.env:531 GUARD_NEWS_BLACKOUT_ENABLED=1` | **0 of 21 evaluations blocked** |
| 21 | Concurrency cap (dispatch) | `strategy_logic.py:1845-1869` + `86-112` | `.env:319 CONCURRENT_CAP_DEFAULT=1`; `CONCURRENT_CAP_BRIEFING_EXECUTION` commented out at `.env:322` | **3** (2026-07-23) |
| 22 | **RACE_CAUGHT** candle-lag recheck | `trade_executor.py:813-838` | `CANDLE_LAG_CRITICAL_SECS` unset → `60.0` (`candle_lag_monitor.py:33`) | **0** |

Per-day counts (journal, `[BRIEFING-EXEC]`/`[GUARDS]`/`[RACE_CAUGHT]`):

```
date          plan_age  sess_lock  dir_bias_veto  phase2_no_conf  trigger_v2  fallback_no_trig  drift_cap  lvl_advisory  guards  cascade  race  ARMED  FIRE
2026-07-03       38098          0              0               0           0                 0          0             0       0        0     0      0     0
2026-07-06           0          0              0               0           0                 0          0             0       0        0     0      0     0
2026-07-07           0          0              0               0           0                 0          0             0       0        0     0      0     0
2026-07-08           0          0              0               0           0                 0          0             0       0        0     0      0     0
2026-07-09        9662          3              6              72          11                56         14            10       0        0     0     10     2
2026-07-10           0          0              0               0           0                 0          0             0       0        0     0      0     0
2026-07-13           0          0              0               0           0                 0          0             0       0        0     0      0     0
2026-07-14           0          0              0               0           0                 0          0             0       0        0     0      0     0
2026-07-15       14808          2              7              88          35               100          0            23       0        0     0     12     1
2026-07-16       12793          0              7              55          13               114          0            13       0        0     0     11     0
2026-07-17       35184          0              0               0           0                 0          0             0       0        0     0      4     0
2026-07-20       11180          0              7              60           6               228          7             3       0        0     0     11     0
2026-07-21         695          2              5              75           3                83          2             5       0        0     0     10     2
2026-07-22         153          4              2              50          10               192          0             8       0        0     0     12     4
2026-07-23       13479          4              7              65           6               136         17            11       0        0     0     17     5
2026-07-24       21327          5              8              16           3                71         25             5       0        0     0     11     3
2026-07-27       13798          2              8              55          18               127          0            15       0        0     0      9     2
2026-07-28        2288          2              9              79           7               122          0             5       0        0     0     15     1
2026-07-29       16240          0             10              45           0               233          0             0       0        0     0     13     0
2026-07-30       11238          1              6             106          21               193          3            22       0        0     0     15     1
TOTAL           200943         25             82             766         133              1655         68           120       0        0     0    150    21
```

(`FIRE` counts executor fire *decisions*; 21 decisions → 18 broker-confirmed rows in `signal_log.jsonl`, the 3-row gap being the 2026-07-23 concurrency-cap blocks.)

Representative lines:

```
[plan_age]   2026-07-03 00:00:02,710 [INFO] [BRIEFING-EXEC] USDJPY plans skipped — briefing age 11186 min > PLAN_MAX_AGE_MIN=240 (briefing_time=2026-06-25T05:33:53Z)
[dir_bias]   2026-07-09 05:32:27,335 [INFO] [BRIEFING-EXEC] GBPUSD plan_id=London_1 strategy=BRIEFING_EXECUTION VETOED by direction-bias resolver | plan_dir=SELL daily=BUY session=BUY → resolved=BUY
[phase2]     2026-07-09 05:35:01,910 [INFO] [BRIEFING-EXEC] GBPUSD plan_id=London_2 strategy=BRIEFING_EXECUTION skipped — phase2 5m close=13406.75000 did not confirm (direction=BUY sweep=None zone=…)
[trigger_v2] 2026-07-09 05:45:01,131 [INFO] [BRIEFING-EXEC] EURUSD SELL BLOCKED trigger_v2 plan_id=London_2 briefing_time=2026-07-09T05:32:27Z entry_mode=phase2 reason=['candle_close(5m,below,11430.0…']
[fallback]   2026-07-09 06:10:01,221 [INFO] [BRIEFING-EXEC] USDJPY TREND_ENTRY fallback BLOCKED — plan entry_trigger_v2 not satisfied. plan_id=London_1 plan=Sell-side liquidity sweep then LONG reversal…
[drift_cap]  2026-07-09 07:15:01,602 [INFO] [BRIEFING-EXEC] USDCAD TREND_ENTRY vetoed — entry 14167.95000 is 18.0p past zone (cap 10p). plan_id=London_2 plan=Fade BB_UPPER resistance
[lvl_advis]  2026-07-09 07:35:01,589 [INFO] [BRIEFING-EXEC] USDCAD TREND_ENTRY levels_match=false (advisory; gate disabled, proceeding). proximity=8.0p direction=SELL plan_id=London_2 …
[disp_cap]   2026-07-23 12:50:01,770 [INFO] [DISPATCH] CS.D.USDJPY.TODAY.IP BUY BRIEFING_EXECUTION blocked — concurrent cap reached (1/1)
```

### 3.2 PLAN_MAX_AGE_MIN creates a hard intra-day dead zone

`PLAN_MAX_AGE_MIN=240` is measured from the **briefing timestamp**, not from arming. With briefings at 05:30 and 12:30 UTC, every armed plan dies exactly 4 hours after its briefing. Measured, counting only skip lines whose `briefing_time` is the *same* calendar day:

```
date          n_lines   first_skip   last_skip   age_range(min)
2026-07-09       9662     09:30:55    20:54:47      240-504
2026-07-15      14808     09:30:06    23:59:57      240-690
2026-07-16       1540     10:02:39    23:59:57      265-690
2026-07-20        747     19:40:26    23:58:50      430-689
2026-07-21        306     20:02:55    23:57:59      447-686
2026-07-23      13479     16:30:44    23:59:59      240-689
2026-07-24       9942     09:30:26    20:59:00      240-508
2026-07-27       2549     09:40:33    23:59:51      249-689
2026-07-29      15777     09:30:45    23:59:59      240-690
2026-07-30         17     09:32:06    11:25:39      241-354
```

The London arm dies at ~09:30 UTC and the NY arm at ~16:30 UTC. **The strategy's live windows are 05:30–09:30 and 12:30–16:30 UTC**; the 09:30–12:30 and post-16:30 blocks are structurally dead. The 2026-07-30 fire at 09:20:02 landed 228.6 min after arm — 11 minutes before the gate would have closed it.

Note also that this gate returns *before* the plan loop (`briefing_execution.py:1732: return None`), so it also suppresses NY plan evaluation on days when only a stale briefing exists — exactly what produced the 35 184 skips on 2026-07-17.

### 3.3 The guards stack is comprehensively inert

`guards/registry.py:14`:

```python
    "BRIEFING_EXECUTION": ["stale_briefing", "news_blackout", "priced_in"],
```

`guards/dispatcher.py:38-40` — only `news_blackout` can block while `GUARDS_OBSERVABLE_ONLY=1`:

```python
_PER_GUARD_ENFORCEMENT_ENVS: Dict[str, str] = {
    "news_blackout": "NEWS_BLACKOUT_ENFORCED",
}
```

Every BRIEFING_EXECUTION guard evaluation in the window, from `logs/guards_observed.jsonl`:

```
BRIEFING_EXECUTION rows since 2026-07-03: 21
blocked counter:            Counter({(): 21})
evaluated counter:          Counter({('stale_briefing', 'news_blackout', 'priced_in'): 21})
actually_blocked:           Counter({False: 21})

news_blackout  reasons: Counter({'no_event_in_window': 20, 'outside_buffer': 1})
stale_briefing reasons: Counter({'session_open_unavailable': 11, 'neutral_bias_or_missing': 10})
priced_in      reasons: Counter({'insufficient_lookback_data': 21})
```

* `priced_in` returned `insufficient_lookback_data` on **21 of 21** evaluations — it has never had the data to form an opinion.
* `stale_briefing` split between `session_open_unavailable` ("no 06:00 UTC row in df_5m — skip-no-block fallback") and `neutral_bias_or_missing` — it has never formed an opinion either.
* `news_blackout` found an event in window exactly **once** and it was 24.98 minutes out, outside the 10-minute pre-buffer.

Zero blocks in 20 days from the entire guard stack. Also note: guards run *after* the entry decision is logged, i.e. they are the last gate, not a pre-filter.

### 3.4 News blackout freshness (the 161 failure mode) — checked

**The static file is April-vintage, exactly as on 161:**

```
$ ls -la news_windows.json
-rw-r--r-- 1 autobot autobot 553 May 13 13:02 news_windows.json

$ cat news_windows.json
{
  "_comment": "High-impact GBP/USD news events — all times BST (UTC+1 in summer). Auto-converted to UTC by news_blackout.py. Update weekly.",

  "2026-03-18": ["07:00", "19:00", "19:30"],
  ...
  "2026-04-14": ["07:00", "13:30"]
}
```

12 event dates, **first 2026-03-18, last 2026-04-14**. mtime **2026-05-13 13:02** — 78 days stale as of today, and the newest event in it is 107 days old. Confirmed in the running process's own startup log:

```
2026-07-08T06:03:33 [Blackout] 2026-04-14 BST→UTC: ['07:00', '13:30'] → ['06:00', '12:30']
2026-07-08T06:03:33 [Blackout] Loaded 21 event windows across 13 dates from /opt/tradingbot/news_windows.json (pre=5min, post=5min, close_on_blackout=False, BST auto-converted)
```

`news_blackout.is_news_blackout()` keys strictly on `utc_dt.strftime("%Y-%m-%d")` (`news_blackout.py:110-111`), so **the file contributes exactly zero blackout coverage for any date in this audit window.**

**However — unlike 161, 144 has a second, live feed.** `morning_briefing.py:3793-3808` registers windows from each day's briefing:

```python
        from news_blackout import register_window
        nc = briefing.get("news_context") or {}
        today = _utc_today()
        # avoid_before — pre-existing path, kept verbatim
        for t_str in (nc.get("avoid_before") or []):
            clean = _normalise_hhmm(t_str)
            if clean:
                register_window(today, clean)
        # events[*].time — new in FIX 3b
        if register_events:
            for ev in (nc.get("events") or []):
                clean = _normalise_hhmm((ev or {}).get("time"))
                if clean:
                    register_window(today, clean)
```

Observed in the journal:

```
2026-07-09T05:32:27 [Blackout] Registered dynamic window: 2026-07-09 13:30 UTC
2026-07-09T05:32:27 [Blackout] Registered dynamic window: 2026-07-09 14:00 UTC
2026-07-09T05:35:27 [Blackout] Registered dynamic window: 2026-07-09 05:30 UTC
2026-07-09T05:35:27 [Blackout] Registered dynamic window: 2026-07-09 06:00 UTC
...
2026-07-30T05:33:25 [Blackout] Registered dynamic window: 2026-07-30 08:30 UTC
2026-07-30T12:39:42 [Blackout] Registered dynamic window: 2026-07-30 12:15 UTC
```

Full count of `Registered dynamic window` lines per trading day in the window (73 total):

```
2026-07-03   0      2026-07-15   6      2026-07-23   5
2026-07-06   0      2026-07-16   6      2026-07-24   7
2026-07-07   0      2026-07-17   0      2026-07-27   5
2026-07-08   0      2026-07-20   2      2026-07-28   5
2026-07-09   4      2026-07-21   6      2026-07-29   7
2026-07-10   0      2026-07-22   5      2026-07-30  15
2026-07-13   0
2026-07-14   0
```

The zeros map exactly onto the 8 days with no briefing. Note also that several registered windows are already in the past at registration time (e.g. `2026-07-30 05:33:25 → event 2026-07-30 05:00`, `2026-07-30 12:36:55 → event 2026-07-30 04:30`), and that `register_window` is global rather than per-pair — a GBP event registered from the GBPUSD briefing also gates USDJPY.

**Verdict on freshness:** the blackout feed on 144 is *derived from the briefing*, not from the file. That means (a) the static file is dead weight and should not be trusted as coverage, and (b) **on every day the briefing fails to generate, the news blackout has zero windows and is completely inactive** — the same 8 days that produced no trades would also have produced no news protection had a plan survived. The one event the guard did see in 20 days (`mins_to_event: 24.98` on 2026-07-23 11:50) came from this dynamic path, confirming it works when the briefing works.

### 3.5 RACE_CAUGHT — the fixed version is running

`trade_executor.py:816-822`:

```python
        _live = _clm.live_lag(_sym)
        if _live is not None and _live > _clm.CRITICAL_THRESHOLD_SECS:
            _sig_dbg = _safe_str(getattr(decision, "signal", None)).strip().upper() or "?"
            logger.warning(
                "[RACE_CAUGHT] strategy=%s pair=%s signal=%s lag_at_fire=%.1fs "
                "threshold=%.0fs — fire blocked at execute boundary",
                _race_mode, _sym, _sig_dbg, _live, _clm.CRITICAL_THRESHOLD_SECS,
            )
```

The `_live is not None` guard — the May fix — **is present**. Provenance:

```
b2d2425 2026-05-08 18:33:46 +0100 fix(candle-lag): close fire-time race window with synchronous recheck (#6)
d4e39bf 2026-05-21 10:23:13 +0000 fix(briefing-first): exempt BRIEFING_FIRST from RACE_CAUGHT + fix no-retry trap
```

`trade_executor.py` mtime is **2026-06-12 15:53**, i.e. the file on disk postdates both fixes and predates the 2026-07-29 process start — so the loaded module contains them. Threshold is `CRITICAL_THRESHOLD_SECS = float(os.getenv("CANDLE_LAG_CRITICAL_SECS", "60"))` (`candle_lag_monitor.py:33`), not overridden in `.env`, so 60 s. Regression coverage exists at `scripts/test_candle_lag_race_guard.py:247-250` ("must treat None as no-signal"). **0 RACE_CAUGHT blocks in the 20-day window.**

### 3.6 One more stale-data finding, not on the original list

`briefing_execution.py:2028` and `:2219` import the guard runner *inside* the fire path with a bare `except Exception` that only warns and proceeds:

```python
            except Exception as _g_exc:
                logger.warning(
                    "[BRIEFING-EXEC] guard eval raised (ENTRY, plan_id=%s): %s",
                    plan.get("plan_id"), _g_exc, exc_info=True,
                )
```

The import resolves (`guards/` is a package at `/opt/tradingbot/guards/__init__.py`), so this is currently fine — but combined with §3.3 it means the guard stack is a soft-fail no-op in both the "raises" and the "returns pass" case. There is no path by which a guard failure surfaces as a blocked trade.

---

## Q4 — DIRECTION

### 4.1 The trigger code: how long/short is decided

**Direction is decided at arm time, from the LLM plan's own `bias` field. It is never recomputed from price.**

`briefing_execution.py:1153-1163` — the entire direction model:

```python
        bias = str(plan.get("bias", "") or "").upper()
        if bias == "LONG":
            direction = "BUY"
        elif bias == "SHORT":
            direction = "SELL"
        else:
            logger.warning(
                "[BRIEFING-EXEC] %s plan %r bias %r not LONG/SHORT — skip",
                sym, plan_label, bias,
            )
            return None
```

That `direction` is frozen into the active-plan dict (`briefing_execution.py:1190`) and read verbatim at fire time (`briefing_execution.py:1759`):

```python
            direction = plan["direction"]
```

The only thing that can change it is a **veto** (never a flip), from `briefing_direction.resolve_direction` (`briefing_direction.py:95-116`):

```python
    if d in ("BUY", "SELL"):
        # Rule 1: daily wins.
        ...
        resolved = d
    else:
        # Rule 2: daily neutral → pass plan through.
        resolved = plan_direction_for_default
        ...
    plan_blocked = (p in ("BUY", "SELL")) and (resolved != p)
```

So the complete live direction model is:

1. LLM writes `trading_plans[i].bias ∈ {LONG, SHORT}`.
2. If `briefing.daily_bias` is directional and disagrees → veto the plan (82 vetoes in 20 days).
3. If `briefing.daily_bias` is NEUTRAL → the plan's direction passes through unchecked.
4. `session_bias` is normalised but, in practice, contributes nothing: every fire in the window carried `session_bias=LIQUIDITY_HUNT` or `RANGE`, neither of which is in `_LONG_VOCAB`/`_SHORT_VOCAB` (`briefing_direction.py:31-39`), so `normalize_bias` returns `NEUTRAL` for it.

The entry *triggers* (`entry_trigger_v2`: `sweep` / `rsi` / `candle_close`) only decide **when** to fire, never **which way**.

### 4.2 The last 20 fires joined to outcomes

`signal_log.jsonl`, `strategy == BRIEFING_EXECUTION`, most recent 20 rows:

| open (UTC) | pair | dir | fire_path | pnl (p) | MFE | MAE | close reason |
|---|---|---|---|---|---|---|---|
| 2026-06-25T08:10:05Z | USDCAD | BUY | trend_entry_fallback | +0.75 | 20.75 | 5.15 | Breakeven stop (IG) |
| 2026-07-01T09:05:08Z | EURUSD | SELL | phase2_sweep_reclaim | +0.10 | 13.00 | 0.40 | Breakeven stop (IG) |
| 2026-07-09T07:35:02Z | USDCAD | SELL | trend_entry_fallback | −0.25 | 10.25 | 13.75 | External/manual |
| 2026-07-09T14:05:03Z | USDJPY | BUY | trend_entry_fallback | +0.30 | 12.90 | 0.00 | Breakeven stop (IG) |
| 2026-07-15T07:20:03Z | GBPUSD | BUY | phase2_sweep_reclaim | −15.55 | 0.65 | 11.25 | SL hit |
| 2026-07-21T13:15:02Z | GBPUSD | SELL | trend_entry_fallback | +2.05 | 32.75 | 0.00 | Breakeven stop (IG) |
| 2026-07-21T13:25:03Z | USDCAD | BUY | phase2_sweep_reclaim | −12.05 | 0.65 | 10.35 | SL hit |
| 2026-07-22T08:20:02Z | USDJPY | BUY | phase2_sweep_reclaim | −13.80 | 0.00 | 14.20 | SL hit |
| 2026-07-22T13:30:03Z | GBPUSD | SELL | trend_entry_fallback | +0.55 | 12.15 | 13.35 | Breakeven stop (IG) |
| 2026-07-22T13:50:03Z | USDCAD | SELL | phase2_sweep_reclaim | −0.25 | 11.95 | 8.75 | External/manual |
| 2026-07-22T15:25:01Z | USDJPY | BUY | phase2_sweep_reclaim | — | — | — | still open / unresolved |
| 2026-07-23T11:50:01Z | USDJPY | BUY | trend_entry_fallback | **+35.10** | 50.90 | 2.50 | EOD_CLOSE |
| 2026-07-23T13:15:02Z | USDCAD | BUY | trend_entry_fallback | +0.65 | 14.65 | 14.65 | Breakeven stop (IG) |
| 2026-07-24T06:10:03Z | USDJPY | BUY | phase2_sweep_reclaim | −14.70 | 0.00 | 13.80 | External/manual |
| 2026-07-24T13:05:02Z | USDJPY | BUY | trend_entry_fallback | −15.20 | 0.80 | 12.10 | SL hit |
| 2026-07-24T14:35:02Z | EURUSD | SELL | trend_entry_fallback | +9.80 | — | — | IG_RECONCILE |
| 2026-07-27T06:55:03Z | EURUSD | SELL | phase2_sweep_reclaim | **+40.10** | 41.20 | 2.00 | External/manual |
| 2026-07-27T08:05:03Z | USDJPY | BUY | phase2_sweep_reclaim | **+21.80** | 27.60 | 2.80 | External/manual |
| 2026-07-28T14:30:02Z | GBPUSD | SELL | phase2_sweep_reclaim | +0.95 | 10.15 | 0.95 | Breakeven stop (IG) |
| 2026-07-30T09:20:02Z | GBPUSD | SELL | trend_entry_fallback | −22.15 | 1.75 | 15.85 | SL hit |

**Hit-rate, three ways (19 resolved trades):**

```
naive pnl > 0                     : 11/19 = 57.9%       net +18.20p
pnl >= +5p (real directional win) :  4/19 = 21.1%       net +106.8p
pnl <= -5p (real directional loss):  6/19 = 31.6%       net  -93.5p
scratch (-5p < pnl < +5p)         :  9/19 = 47.4%       net   +4.8p
MFE > |MAE| (direction right before management): 9/18 = 50.0%
```

The naive 57.9% is misleading: 7 of the 11 "wins" are IG breakeven-stop scratches worth +0.10 to +2.05 pips. **On the honest measure — did price go the plan's way before it went against it — the direction model is exactly a coin flip: 50.0% (9 of 18 with MFE/MAE recorded).** Net result over 19 resolved trades is +18.2 pips, and that is entirely carried by three trades (+35.10, +40.10, +21.80 = +97.0p) against six losers totalling −93.5p.

By direction: BUY n=10, 5 with pnl>0, net **−12.7p**. SELL n=9, 6 with pnl>0, net **+30.9p**.

### 4.3 Raw inputs available at fire time that the trigger currently ignores

All of the following are **computed inside the fire path on this box, on this process, and then discarded or logged only.**

**(a) H1 EMA stack / HTF authority — computed, logged, never consulted.**
`briefing_execution.py:2648-2708` runs `compute_htf_authority()` on the last 120 H1 candles at every fire and emits `[FIRE-SHADOW]`. The flag comment in `.env:567` is explicit: `FIRE_TIME_HTF_SHADOW_ENABLED=1  # shadow logging only — never blocks`. All 21 fire evaluations in the window:

```
2026-07-09T07:35:01 [FIRE-SHADOW] sym=USDCAD plan_dir=BEAR h1_dir=NEUTRAL h1_conf=neutral h1_reason='trend stack BEAR but slope -5.3p < 6p threshold' cascade=TREND_UP  cascade_conf=LOW  verdict=WOULD_ALLOW resolver=ALLOWED
2026-07-15T07:20:02 [FIRE-SHADOW] sym=GBPUSD plan_dir=BULL h1_dir=BULL    h1_conf=strong  h1_reason='trend+stack BULL fan=+17.2p slope=+12.3p'      cascade=NEUTRAL   cascade_conf=LOW  verdict=WOULD_ALLOW resolver=ALLOWED
2026-07-22T08:20:01 [FIRE-SHADOW] sym=USDJPY plan_dir=BULL h1_dir=NEUTRAL h1_conf=neutral h1_reason='trend stack BULL but slope -4.8p < 6p threshold' cascade=TREND_DOWN cascade_conf=HIGH verdict=WOULD_ALLOW resolver=ALLOWED
2026-07-30T09:20:02 [FIRE-SHADOW] sym=GBPUSD plan_dir=BEAR h1_dir=NEUTRAL h1_conf=neutral h1_reason='trend stack BULL but slope -3.1p < 6p threshold' cascade=TREND_UP  cascade_conf=HIGH verdict=WOULD_ALLOW resolver=ALLOWED
```

**21 of 21 verdicts were `WOULD_ALLOW`** — because `h1_dir` came back `NEUTRAL` on 14 of 21 fires (the slope thresholds are 6p for trend and 18p for range). As a would-be gate the H1 authority signal, at its current thresholds, would have changed nothing. That is a fact about the *signal's calibration*, not about whether H1 data is available: the EMA fan and slope numbers are right there in the log line and are not used at all.

**(b) 5M cascade / regime state — computed, and on 3 of 19 resolved fires it disagreed, all 3 lost.**
`cascade_stable_at_fire` is recorded in `signal_log.jsonl` on every row:

| open (UTC) | pair | dir | cascade at fire | agree? | pnl |
|---|---|---|---|---|---|
| 2026-07-09T07:35:02Z | USDCAD | SELL | TREND_UP | **DISAGREE** | −0.25 |
| 2026-07-22T08:20:02Z | USDJPY | BUY | TREND_DOWN | **DISAGREE** | −13.80 |
| 2026-07-30T09:20:02Z | GBPUSD | SELL | TREND_UP | **DISAGREE** | −22.15 |

```
cascade DISAGREE at fire: n=3   net -36.20p   wins(pnl>0)=0
cascade not-disagree    : n=16  net +54.40p   wins(pnl>0)=11
label distribution      : NEUTRAL 12, RANGE 4, TREND_UP 3, TREND_DOWN 1
```

Commit `8778a7d` (today, 13:52) wires exactly this as a hard block — but per §0.1 it is **not in the running process**, and the `.env` flag enabling it was written after process start too. As of this audit the cascade signal is read and recorded on every fire and acts on nothing.

**(c) The `regime_state` snapshot** is fetched at `briefing_execution.py:2260-2266` — *after* the `StrategyDecision` is already built — and stuffed into `debug["regime_state"]` for logging. It cannot influence the decision it is attached to.

**(d) The Phase-4B candle regime classifier** runs on every 5M close (`strategy_logic.py:1941-1945`, writing `logs/regime_shadow.jsonl`, 39 MB) and its consumer in the executor is disabled: `REGIME_CLASSIFIER_TP_MODULATION_ENABLED` defaults to `0` (`briefing_execution.py:247-249`), and `_regime_allows()` is hard-wired to `True`.

**(e) Prior-session structure** is in the briefing package (`prior_session_high/low`, `daily_high/low`, `ema_stack_state`, `h1_bias`, `h4_bias`, `d1_bias` — all visible in the v2 artifacts, e.g. `briefings/v2/2026-07-30/LONDON/EURUSD.json`) but the v4 executor reads none of it at fire time; it only reads `daily_bias`/`session_bias` for the veto.

**(f) Spread** is captured at `strategy_logic.py:1890` into `decision.debug["spread"]` *after* the decision. There is no spread gate anywhere in the BRIEFING_EXECUTION path.

**Summary of the direction finding (report only, no recommendation):** the live long/short decision is a straight copy of an LLM-authored `bias` string, filtered by a one-way veto against another LLM-authored `daily_bias` string. Its evidenced direction accuracy over the last 20 fires is 50.0% by MFE/MAE. Four independent price-derived directional signals (H1 EMA authority, 5M cascade, regime classifier, prior-session structure) are computed on the same tick and none of them reaches the decision.

---

## Data gaps and limits

* **`.env` contents at process start are unrecoverable.** `.env` was modified 2026-07-30 13:48:15, after the 2026-07-29 06:41:48 process start. The most recent backup on disk is `.env.bak.20260609_153637`. I can prove the running process cannot be using today's values, but I cannot reconstruct what it *is* using for keys changed today. I have not inferred them. (Env values quoted in Q3 are the current on-disk values, flagged where that matters.)
* **`/proc/470536/environ` is 372 bytes and readable but empty of application config** — the bot reads `.env` via dotenv at import, not via systemd `Environment=`, so the process environment block cannot confirm flag values either.
* **`logs/diagnostics.log` contains no `[BRIEFING-EXEC]` records** (11 `BRIEFING` matches, all `BRIEFING_FIRST_*` header lines). All executor evidence therefore comes from journald, which retains from 2026-07-01 onward on this box (3.0 GB, `journalctl --disk-usage`). The 20-day window is fully covered; anything before 2026-07-01 was not examined.
* **`briefing_time` for 2026-07-23 London is 10:13:38Z**, ~4h45m later than the 05:30 schedule. I did not chase the cause; the day's fires and gates are unaffected in the table above, but the London arm that day was late by construction.
* **One 2026-07-22 fire (`DEAL-08`, 15:25:01 USDJPY BUY) has no close row** in `signal_log.jsonl` and is excluded from all outcome statistics (n=19 resolved, not 20).
* **v2 and v5 briefing engines were not audited.** `BRIEFING_V2_DRY_RUN=1` (`.env:561`) and the v5 artifacts show `min_confidence_to_arm: 70` with `executed: false` on every file inspected. Neither feeds BRIEFING_EXECUTION, which reads only `morning_briefing.get_briefing()` (`strategy_logic.py:1970`).

---

## Conclusions (evidence above, in order of size of effect)

1. **The dominant constraint on trading frequency is not a gate — it is briefing non-production.** 8 of 20 trading days had no briefing at all: 5 to an Anthropic 400 `"Your credit balance is too low"`, 3 to an IG `401 error.security.client-suspended` crash-loop. That is 73% of the no-trade days. No strategy tuning can recover those days.

2. **`PLAN_MAX_AGE_MIN=240` measured from briefing time (not arm time) kills every plan 4 hours after its briefing**, producing hard dead zones 09:30–12:30 and post-16:30 UTC and 200 943 skip lines. On 2026-07-17 it alone accounted for every no-fire event.

3. **Level spacing has two real defects, both in `morning_briefing.py`.** The same-side-only collapse rule (`:2297`) cannot see PIVOT-vs-S/R pairs, and the separation check (`:2481`) compares rank-neighbours in an array ordered by importance rather than by price — so 49 of 62 sub-15p pairs were never examined. 19% of price-adjacent level pairs are inside the tolerance the prompt itself specifies. A third, smaller issue: the prompt states 15p, `.env` enforces 12p.

4. **Every safety gate that reads market data is either advisory, inert, or not loaded.** The guards stack blocked 0 of 21 evaluations (`priced_in` returned `insufficient_lookback_data` 21/21). The levels-proximity gate is advisory by default. The H1 shadow never blocks by design and returned `WOULD_ALLOW` 21/21. The cascade gate exists on disk and is not in the running process. The only gates that actually bit are structural ones: plan age, the direction-bias veto, phase-2 close confirmation, and the trigger_v2 requirement.

5. **The news blackout on 144 is fresher than 161's, but only conditionally.** The static `news_windows.json` is 78 days stale (last event 2026-04-14) and contributes nothing; live coverage comes entirely from `register_window()` fed by each day's briefing. The corollary is that **on the 8 days the briefing failed, news blackout coverage was zero** — the same failure took out both the plan and its news protection.

6. **The direction model is a coin flip and is not using the data it already has.** Long/short is a verbatim copy of an LLM `bias` string; evidenced accuracy is 50.0% by MFE/MAE over 18 fires with MFE/MAE recorded, and net P&L (+18.2p over 19 trades) rests on three outliers. Four price-derived directional signals are computed on the same tick and discarded. The three fires where the 5M cascade contradicted the plan direction all lost, for −36.2 pips combined.

7. **`RACE_CAUGHT` is confirmed running the fixed version** (`_live is not None` guard present, `trade_executor.py:817`; file mtime 2026-06-12 postdates fixes `b2d2425`/`d4e39bf` and predates process start). It blocked 0 fires in 20 days.
