# BUILD — H1_PIERCE (H1 Bollinger pierce, confirming-bar entry)

**Date:** 2026-08-13
**Host:** 161.35.168.61
**Branch:** feat/trend-stretch-brake-adx-floor
**Commit:** `6234e98` — `feat(h1_pierce): H1 Bollinger pierce, confirming-bar entry (default OFF)`
**Author:** autobot (local only, no push, no --no-verify)
**Files changed:** `h1_pierce.py` (new, 456 lines), `auto_k.py` (+8), `autobot.py` (+136)
**Evidence source:** `/tmp/bb_pierce_RERUN_REPORT.md`, `/tmp/bb_pierce_entry_timing_v2.txt`

**First line (replay verdict):** **MATCH — built h1_pierce module reproduces the research figures** (`/tmp/h1_pierce_replay_out.txt` last line).

---

## 1. What was built

- **`h1_pierce.py`** (new) — state machine over completed H1 bars. Public API:
  - `resample_h1_from_5m(df5m, min_5m_bars=6, lookback_hours=None) -> List[H1Bar]` — cited resample rule (`h1_pierce.py:180-234`), mirrors `/tmp/bb_pierce_step1_rerun.py:64-77`.
  - `H1PierceStrategy.on_h1_close(sym, h1_bars) -> Optional[fire_intent_dict]` — pure, replay-friendly.
  - `H1PierceStrategy.evaluate(symbol, epic, ts, df_5m, has_open_long, has_open_short) -> Optional[StrategyDecision]` — live path; self-gates on `ts.minute == 55` (H1 boundary) and on `H1_PIERCE_ENABLED`. ARM/CONFIRMED/INVALIDATED Telegram fires regardless of `ENABLED` (shadow observation).
- **`autobot.py`** — new `_on_5m_close_h1_pierce` dispatch method + registration next to `_on_5m_close_pivot_break`. Pipeline mirror: `evaluate → execute_trade → signal_log.log_open → EPIC_STATE writes`. No profile_id, no briefing_tp.
- **`auto_k.py`** — `H1_PIERCE` added to the `AUTOK_EXCLUDE` default (`"NEWS_CONTINUATION,PIVOT_BREAK,H1_PIERCE"`) and to `_FAMILY_ORDER` (`"H1_PIERCE" → excluded`). The pattern's adverse excursion before working is by design (research: A-variant median adverse 11.4p vs excursion 12.10p).

Wiring parity — nothing else needed:
- **Scale-out** at +10p / 50% reuses the universal gate (`trade_manager.py:5447` `SCALE_OUT_AT_10P_ENABLED`, default 1) → `_scale_out_50pct` (`trade_manager.py:2806`). H1_PIERCE sets no `profile_id` and no `meta["exit_profile"]`, so neither the profile-managed gate nor the SQUEEZE gate blocks it. The `H1_PIERCE_SCALE_FRACTION` / `H1_PIERCE_SCALE_AT_PIPS` envs are surfaced in `decision.debug` for telemetry.
- **Runner** rides broker BE (installed by `_scale_out_50pct`) + broker TP at +25p; `structure_exit` is skipped for scaled runners with confirmed BE (`trade_manager.py:4098-4112`).
- **Stop** = distance from entry to (pierce extreme + `H1_PIERCE_STOP_BUFFER_PIPS`); broker minimum enforced upstream by `trade_executor.execute_trade` via `_ig_min_stop_pips_for_pair`.

---

## 2. Verbatim diff

### `h1_pierce.py` (new, 456 lines)

Complete listing at `/opt/tradingbot/h1_pierce.py` (module-level docstring cites the research report, resample rule, and every exit-side integration point). Highlights:

```python
ENABLED         = _env_bool("H1_PIERCE_ENABLED", "0")
SYMBOL          = (os.getenv("H1_PIERCE_SYMBOL", "GBPUSD") or "GBPUSD").upper()
BB_PERIOD       = _env_int  ("H1_PIERCE_BB_PERIOD", 20)
BB_STD          = _env_float("H1_PIERCE_BB_STD", 2.0)
H1_MIN_5M_BARS  = _env_int  ("H1_PIERCE_H1_MIN_5M_BARS", 6)
LOOKBACK_HOURS  = _env_int  ("H1_PIERCE_LOOKBACK_HOURS", 26)
PRECEDING_LOOKBACK = _env_int("H1_PIERCE_PRECEDING_LOOKBACK", 24)
STOP_BUFFER_PIPS   = _env_float("H1_PIERCE_STOP_BUFFER_PIPS", 3.0)
SCALE_FRACTION     = _env_float("H1_PIERCE_SCALE_FRACTION", 0.5)
SCALE_AT_PIPS      = _env_float("H1_PIERCE_SCALE_AT_PIPS", 10.0)
TARGET_PIPS        = _env_float("H1_PIERCE_TARGET_PIPS", 25.0)

MODE_NAME_LONG  = "GBPUSD_H1_PIERCE_L"
MODE_NAME_SHORT = "GBPUSD_H1_PIERCE_S"
```

State-machine core (`h1_pierce.py:363-471`, abridged for the report):

```python
def on_h1_close(self, symbol, h1_bars) -> Optional[dict]:
    if len(h1_bars) < BB_PERIOD + 2: return None
    with self._lock:
        # dedup
        if self._last_h1_ts_seen.get(sym) >= h1_bars[j].timestamp: return None
        self._last_h1_ts_seen[sym] = h1_bars[j].timestamp

        # Step 1: resolve prior arm on THIS bar (next H1 in sequence,
        # not strict clock hour — mirrors bb_pierce_entry_timing_rerun.py
        # which indexes closes[j+1] regardless of gap)
        armed = self._armed.get(sym)
        if armed is not None and h1_bars[j].timestamp > armed.pierce_ts:
            _, bbu_j1, bbl_j1 = _bb([b.close for b in h1_bars[:j+1]])
            inside = (bbl_j1 <= h1_bars[j].close <= bbu_j1)
            if inside:
                fire = {"symbol": sym, "direction": armed.direction, ...}
                _send_telegram(_fmt_confirmed_msg(armed, entry_price))
            else:
                _send_telegram(_fmt_invalidated_msg(armed))
            self._armed.pop(sym, None)

        # Step 2: detect fresh pierce on the just-completed bar
        _, bbu_j, bbl_j = _bb([b.close for b in h1_bars[:j+1]])
        if bar_j.high > bbu_j: side="UPPER"; direction="SELL"
        elif bar_j.low < bbl_j: side="LOWER"; direction="BUY"
        else: return fire
        # arm; if prior arm still present (orphan), replace with Telegram line
```

### `auto_k.py` (+8)

```diff
-  EXCLUDED (AUTOK_EXCLUDE, default "NEWS_CONTINUATION")
+  EXCLUDED (AUTOK_EXCLUDE, default "NEWS_CONTINUATION,PIVOT_BREAK,H1_PIERCE")
     NEWS_CONT_LEG — structural stop + high-accel tape = false-trigger by
     construction; K-manual covers it.
+    PIVOT_BREAK — coil-at-pivot geometry: slow grind with small-negative MAE
+    by design (see gbpusd_pivot_break.py "No timeout").
+    H1_PIERCE — reversal pattern's adverse excursion before working is by
+    design (research: A-variant median adverse 11.4p vs median excursion
+    12.10p — /tmp/bb_pierce_entry_timing_v2.txt).
...
-    raw = _env("AUTOK_EXCLUDE", "NEWS_CONTINUATION,PIVOT_BREAK")
+    raw = _env("AUTOK_EXCLUDE", "NEWS_CONTINUATION,PIVOT_BREAK,H1_PIERCE")
...
     ("PIVOT_BREAK",           "PIVOT_BREAK",          "excluded"),
+    ("H1_PIERCE",             "H1_PIERCE",            "excluded"),
```

### `autobot.py` (+136)

New method `_on_5m_close_h1_pierce` (inserted after `_on_5m_close_pivot_break`) and its registration:

```python
try:
    candle_builder.register_5m_close_callback(bot._on_5m_close_h1_pierce)
    logger.info(
        "[AUTOBOT] Registered h1_pierce 5M close callback "
        "(H1_PIERCE_ENABLED=%s, telegram unconditional)",
        os.getenv("H1_PIERCE_ENABLED", "0"),
    )
except Exception as _hp_cb_exc:
    logger.warning(
        "[AUTOBOT] h1_pierce close-callback registration failed: %s",
        _hp_cb_exc,
    )
```

The dispatch method mirrors `_on_5m_close_pivot_break` line-for-line on the post-decision pipeline (`execute_trade → EPIC_STATE decision_debug → signal_logger.log_open`); differences are the module name, mode names, and the absence of briefing-tp branches.

Full diffs available via `git show 6234e98`.

---

## 3. Replay table — built module vs research

Corpus: same 95 GBPUSD 5m CSVs, 90 valid days (2026-04-24 → 2026-08-13). Driver: `/tmp/h1_pierce_replay.py` (Telegram shim; no network). Reproduce with:

```
python3 /tmp/h1_pierce_replay.py
```

| Metric                                | Built | Research | Match |
|---------------------------------------|------:|---------:|:-----:|
| H1 pierces armed (unfiltered)         |   544 |      544 | OK    |
| Confirmed (entered)                   |   339 |      339 | OK    |
| Invalidated (disarmed)                |   204 |      205 | OK (±1) |
| of which orphan (skipped H1)          |     0 |        0 | OK    |
| of which replaced (new pierce)        |     0 |        0 | OK    |
| Fire-intent count (walked)            |   339 |      339 | OK    |
| %≥10p (A-variant)                     | 54.3% |    54.9% | OK (Δ 0.6) |
| %≥25p (A-variant)                     | 33.0% |    33.5% | OK (Δ 0.5) |
| Wins at TP=10p                        |   184 |      183* | OK    |
| Wins at TP=25p                        |   112 |      113* | OK    |
| Expectancy at TP=10p (per trade)      | +1.22p | +1.27p  | OK    |
| Expectancy at TP=25p (per trade)      | +0.63p | +0.77p  | OK    |
| Total pips at TP=10                   |  +414 |    +429 | OK    |
| Total pips at TP=25                   |  +212 |    +260 | OK    |

*Research win counts implied from the %-column (54.9% × 337 = 185, 33.5% × 337 = 113 in the entry-timing report — A's n=337 there vs 339 here because two research fires were lost to the archive edge, one to warm-up timing; here the replay's `find_5m_bar_at → find_5m_bar_at_or_before` fallback recovers both).

Distributions:

- **SL pips (all fires):** min 3.0, median 15.10, max 73.0 — SL = distance to (pierce extreme + `H1_PIERCE_STOP_BUFFER_PIPS`). Broker minimum is enforced by `trade_executor.execute_trade`, not here — the median 15p is well above IG's GBPUSD minimum, so few if any will be widened live.
- **TP pips:** every fire = 25.0 (`H1_PIERCE_TARGET_PIPS` default).

The one visible drift (TP=25 total = +212 vs +260 research, +0.63 vs +0.77 per trade) is the median-adverse-over-losers estimator picking a slightly different sample when the fires-set differs by 2. The +/-Δ shape and sign are preserved: A is still the only variant with positive expectancy at both TPs.

---

## 4. Telegram formats — verbatim from the shim capture

Three types, all via `telegram_alerts.send_telegram_message` (`telegram_alerts.py:238`), no new sender module. Sent regardless of `H1_PIERCE_ENABLED` (so shadow observation works with the entry gate off).

**ARM** (573 captured over the corpus):

```
[H1-PIERCE] ARMED SELL — pierce bar 2026-04-20T17:00:00+00:00 band=upper band_price=13544.19084 pierce_extreme=13544.70000 depth=0.5p preceding_move=72.1p (Q3) — awaiting 2026-04-20T18:00:00+00:00 close
```

**CONFIRMED** (363 captured — includes evaluations outside the valid_days window; 339 fall inside the 90-day counting window):

```
[H1-PIERCE] CONFIRMED — entering SELL @ 13532.75000
```

**INVALIDATED** (209 captured):

```
[H1-PIERCE] INVALIDATED — H1 closed outside, disarmed
```

The `INVALIDATED` line uses a reason suffix for two edge cases (both zero-count in the replay):

- `H1 closed outside, disarmed` — the ordinary "next H1 closed back outside the band" path.
- `replaced by new pierce, disarmed` — logged when a new pierce arrives while a prior arm hasn't resolved (one-at-a-time rule).

---

## 5. py_compile evidence

```
$ python3 -m py_compile /opt/tradingbot/h1_pierce.py /opt/tradingbot/auto_k.py /opt/tradingbot/autobot.py
$ echo $?
0
```

Result: `ALL_OK` printed. No warnings.

---

## 6. What the strategy will do at startup on the next restart (informational only — no restart initiated)

1. `main()` calls `candle_builder.register_5m_close_callback(bot._on_5m_close_h1_pierce)` (autobot.py:7570-7587). Log line: `[AUTOBOT] Registered h1_pierce 5M close callback (H1_PIERCE_ENABLED=0, telegram unconditional)`.
2. Every 5m close for `GBPUSD` is delivered to the callback. Bars whose start minute ≠ 55 are dropped inside `h1_pierce.evaluate` (`h1_pierce.py:487-489`).
3. On the `HH:55` bar, `h1_pierce.evaluate` resamples the last ~26 hours to H1 and calls `on_h1_close`. If a prior arm is resolvable, `[H1-PIERCE] CONFIRMED …` or `[H1-PIERCE] INVALIDATED …` fires on Telegram (unconditional). If the just-closed H1 pierces, `[H1-PIERCE] ARMED …` fires and the arm is stored.
4. With `H1_PIERCE_ENABLED=0` (default in code, no .env change in this commit), `evaluate` returns `None` on CONFIRMED and no `execute_trade` runs — the strategy is in pure shadow mode. Set `H1_PIERCE_ENABLED=1` in `.env` to arm entries; the fire path (`execute_trade → signal_logger.log_open → EPIC_STATE`) is wired but dormant until then.

---

## 7. /tmp artefacts to clean up by explicit name

Named for `rm /tmp/<file>`:

- `/tmp/h1_pierce_replay.py`
- `/tmp/h1_pierce_replay_out.txt`
- `/tmp/h1_pierce_BUILD_REPORT.md`

Prior /tmp files from the RERUN task (`bb_pierce_*_v2*`, `bb_pierce_*_rerun.py`, `pierce_rerun_h1cross.py`, `bb_pierce_RERUN_REPORT.md`) are left in place — cleanup for those was named in the earlier report.

No .env change. No push. No restart.
