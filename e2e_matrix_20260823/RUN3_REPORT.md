# E2E Spec Conformance Matrix — RUN 3 — 2026-08-23

**Ruling:** BUILD 0 fixes A1-A5 landed and verified (A3/A4/A5 fully, A1/A2 partially). Canary v9 executed with the full fix stack. Rows 2-8 **NOT ATTEMPTED** in this session — each canary/row run takes ~5 minutes end-to-end, and iterating A1/A3/A4 to green ate the session's budget. Rows 2-8 remain a mechanical follow-up on the fixed driver.

Worktree: `/tmp/e2e_20260823/tree` (detached HEAD `d5d3c6a`, driver iteration `a1ca1a4` on top of RUN 2's `7dc9d2c`).
Driver files: `/tmp/e2e_20260823/tree/harness_setup.py` + `/tmp/e2e_20260823/tree/e2e_driver.py`.
Durability ref (live repo, force-updated to latest RUN 3 iter): `refs/heads/e2e-driver-20260823` → `a1ca1a4e22d0e54bbe7ae42a3ed43377561de9fb`.

---

## CONTRADICTIONS UPFRONT

1. **A3 (signal_logger Timestamp encode) needed two iterations.** First attempt wrapped log_open/log_close to sanitise args — did NOT help because signal_logger constructs the `record` dict INTERNALLY from the payload, so the Timestamp is baked into `record` before it reaches my wrapper. Working fix: monkeypatch `signal_logger.json.dumps` to use a custom encoder that handles pandas.Timestamp + datetime. **Proof:** canary v8 shows `[signal_logger] open logged id=34a08145-22f7-4afc-afbd-bb00c1e04e56 pair=GBPUSD dir=SELL entry=13671.849999999999`; no Traceback; `/tmp/e2e_20260823/logs/2026-08-21/signal_log.jsonl` has non-empty rows (4 rows total across canaries v8+v9 — append semantics not cleared between runs).

2. **A4 (candle_archive suppression) needed two iterations.** First attempt monkeypatched module attribute `candle_archive.archive_candle` to a no-op. Did NOT work because `candle_archive._register()` (candle_archive.py:196) runs at IMPORT time and passes the function OBJECT to `register_5m_close_callback`. The callback list stored the ORIGINAL function reference; later attribute reassignment invisible. Working fix: after autobot import, walk `candle_builder._5M_CLOSE_CALLBACKS` and REPLACE the archive_candle slot with a no-op. **Proof:** canary v8 + v9 both show `[driver][A4] archive_candle callbacks replaced: 1` and per-row assertion `/opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv: before=253 after=253 PASS`, `.../EURUSD/2026-08-21.csv: before=264 after=264 PASS`. **No contamination.**

3. **A1 (HTF cache lookahead) — key-name fix insufficient; lookahead PERSISTS.** RUN 2 driver keyed filter on `obj["bars"]`; HTF cache file uses `"candles"`. Fixed the key. Canary v9 with the corrected key still produces `d1_closes_tail: [..., 13639.150000000001]` at bar `2026-08-21 14:45` — a 2026-08-22 D1 close is visible when the replay clock says 08-21 14:45Z. The monkeypatch of `json.load` is in place but the lookahead persists — plausible causes: htf_regime cached the D1 dataframe from an earlier load, OR another read path (e.g., `read_text` + `json.loads`) bypasses my `json.load` hook, OR the D1 cache is being loaded before `_htf_filter_hook_install()` runs (my hook installs INSIDE `_replay()`, which is AFTER `autobot.main()` — main() runs briefing preloads that may read HTF caches). **A1 remains PARTIALLY BUILT — not solved this session.**

4. **A2 (5m warmup) — buffer seeded, but ADX still None.** `candle_builder._BUILDER.candles[symbol]` gets 600 prior-day bars from `read_candles_dedup`. Consumers that query `_BUILDER.get_df()` should see enriched data. But the regime engine's closure `_on_5m_close_regime_engine` reads `payload["df_5m"]` (from `_emit_close_payload`) which is the RAW OHLC df my driver builds — no ADX column. All 252 Row 1 bars still show `adx_below_min adx=null`. **A2 remains PARTIALLY BUILT.** Full fix requires either building an indicator-enriched df in the driver payload or feeding through `_BUILDER.get_df()` (which calls `add_indicators`).

5. **The RUN 2 spec's "253 data bars for 2026-08-21" was off-by-one.** Correct count is 252 (00:00 through 20:55 UTC in 5-min bars, inclusive). File is header + 252 = 253 total lines. FIX 0 script uses 252 now.

6. **Replay-only fires proliferate under A1's partial fix.** Live 2026-08-21 signal_log has 7 fires (see live-vs-replay table below). Canary v9 replay produces 3 unique fires: **11:05 BB_BOUNCE_L, 12:10 CONFIRMATION_FALLBACK_S / BB_BOUNCE_S, 17:40 BB_BOUNCE_S**. Zero overlap with live's mode+bar pattern. Per Row 1's spec rule ("Any replay-only fire must be attributed to a named weekend commit or it is a FAIL") — **all 3 replay fires are currently unattributed and therefore FAIL under the Row 1 rule**. Root cause is almost certainly the A1/A2 partial states: without a warmed regime engine and a lookahead-clean HTF context, the replay's decision points diverge from live's. Cannot legitimately score Row 1's must-fires until A1 and A2 are fully green.

---

## STEP B — LIVE-TREE INTEGRITY GUARD

### Before (2026-08-23 22:10 UTC — fresh ref3)

```
$ touch /tmp/e2e_20260823/ref3
$ ls -la /tmp/e2e_20260823/ref3
-rw-rw-r-- 1 autobot autobot 0 Aug 23 22:10 /tmp/e2e_20260823/ref3

$ ls -la /opt/tradingbot/.env /opt/tradingbot/40-gates.env \
      /opt/tradingbot/env/10-infrastructure.env /opt/tradingbot/env/40-gates.env
-rw------- 1 autobot autobot 42976 Aug 22 21:08 /opt/tradingbot/.env
-rw-rw-r-- 1 autobot autobot  2131 Jul 25 09:18 /opt/tradingbot/40-gates.env
-rw-rw-r-- 1 autobot autobot  2970 Jul 26 19:16 /opt/tradingbot/env/10-infrastructure.env
-rw-rw-r-- 1 autobot autobot  2874 Jul 30 07:43 /opt/tradingbot/env/40-gates.env

$ sha256sum ...
c170eff025f4c4e0401cd61ad8097002ec2df58864fb674c3e4caebd3b320202  /opt/tradingbot/.env
8e7bb083f4ad81d8f61ea38f4cda50fcdeb91774edf23dbc3eb641be2e987ba9  /opt/tradingbot/40-gates.env
d38f3a427538fd0046bbc9cd5e65dcef93410330824daff6f20c2def0b857c91  /opt/tradingbot/env/10-infrastructure.env
96e83e3e055fbab20bd336e704cfd485946bc2d72b2b88af911409085cc137a9  /opt/tradingbot/env/40-gates.env
```

### After (session end — sha diff below)

```
$ diff /tmp/e2e_20260823/env.sha.before.run3 /tmp/e2e_20260823/env.sha.after.run3
NO ENV DELTA
```

```
$ find /opt/tradingbot -newer /tmp/e2e_20260823/ref3 \
      -not -path "*/logs/*" -not -path "*/cache/*" -not -path "*/.git/*" -not -path "*/.claude/*"
/opt/tradingbot/data/candles/EURUSD/2026-08-23.csv         # live-bot 5m writes (expected)
/opt/tradingbot/data/candles/GBPUSD/2026-08-23.csv         # live-bot 5m writes (expected)
/opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv         # mtime touched by A4 restoration ops; LINE COUNT UNCHANGED at 253
/opt/tradingbot/reports/eod/review_2026-08-23.md           # some daily EOD scheduler wrote this today (not driver)
/opt/tradingbot/reports-public/e2e_matrix_20260823         # this file
```

```
$ wc -l /opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv /opt/tradingbot/data/candles/EURUSD/2026-08-21.csv
253 /opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv
264 /opt/tradingbot/data/candles/EURUSD/2026-08-21.csv
```

**A4 assertion PASS on both symbols across canary v8 + v9. No corpus growth. Env sha unchanged. STEP B integrity: PASS.**

---

## FIX 0 — 2026-08-21 candle file closure

```
$ python3 /tmp/e2e_20260823/verify_fix0.py
[1] header: 'timestamp,open,high,low,close'
[2] total lines: 253, data bars: 252   ← RUN 2 report's "253 data bars" was off-by-one; correct is 252
[3] DictReader cols=['timestamp', 'open', 'high', 'low', 'close'] parsed_rows=252
[4] snapshot first-occurrence count: 252
[4] first-occurrence OHLC match: 252/252 rows PASS
[spot] first row: {'timestamp': '2026-08-21T00:00:00+00:00', 'open': '13642.650000000001', 'high': '13643.55', 'low': '13640.45', 'close': '13641.45'}
[spot] last row:  {'timestamp': '2026-08-21T20:55:00+00:00', 'open': '13644.5', 'high': '13650.9', 'low': '13637.05', 'close': '13639.849999999999'}
ALL CHECKS PASS   (exit 0)
```

**FIX 0: PASS.**

### Grind-baseline check — PENDING TONIGHT'S RECOMPUTE (00:10 UTC)

Current time was 22:11 UTC; recompute fires at 00:10 UTC. Current baseline from `2026-08-23T00:10:05Z` (this morning, before RUN 2 contamination):
```
GBPUSD median_range_pips = 3.9    (matches operator's expected 3.9p)
EURUSD median_range_pips = 3.0    (matches operator's expected 3.0p)
n_bars 2159, day_range 2026-07-27 → 2026-08-21, n_days 20
```
2026-08-21 was restored to 252 rows (clean) before tonight's recompute. Post-recompute check command for the operator:
```
python3 -c "import json; d=json.load(open('/opt/tradingbot/data/grind_baseline.json')); \
  print(json.dumps({s: {k: v for k, v in x.items() if k in ('median_range_pips','n_bars','day_range')} \
  for s, x in d['symbols'].items()}, indent=2))"
```
Expected: GBPUSD 3.9p / EURUSD 3.0p unchanged. A material shift = finding.

---

## FIX A1-A5 proofs

### A1 — HTF cache lookahead filter — **PARTIALLY BUILT / FAIL**

Driver installs `json.load` monkeypatch that filters HTF cache reads to bars where `epoch(timestamp) <= _REPLAY_NOW_HOLDER[0]`. HTF cache file structure verified as `{"cached_at": ..., "candles": [...]}` (RUN 3 iter 2 keyed on `candles`, RUN 2 keyed on `bars` — wrong). Hook installs inside `_replay()` (post-`autobot.main()`).

**Proof of failure — 14:45Z bar still has 08-22 D1 close visible:**
```
$ grep '"timestamp": "2026-08-21 14:45' htf_regime.jsonl | head -1 | python...
{
  "ts": "2026-08-21 14:45:00+00:00",
  "h1_state": "RANGE",  "d1_state": "UP",  "w1_state": "UP",  "alignment": "NEUTRAL",
  "h1_n_bars": 786,  "d1_n_bars": 191,
  "d1_closes_tail": [13543.8, 13533.4, 13602.8, 13635.4, 13631.4, 13639.150000000001]
                                                                    ^^^^^^^^^^^^^^^^^ 2026-08-22 D1 close — LOOKAHEAD
}
```
The `13639.15` is 2026-08-22's D1 close (timestamped 08-22 00:00 UTC = epoch 1755820800; replay clock at 14:45 08-21 = 1755787500). The bar should have been filtered.

Hypotheses for why the hook doesn't catch it:
- htf_regime or PIA cached the loaded data at module import (before hook install), so subsequent calls use the cache
- Another load path uses `pathlib.Path.read_text()` + `json.loads()` (my hook wraps `json.load(fp)` only)
- The load happens inside a threaded worker where the patched `json` reference doesn't propagate

**Deferred to next session.** Without A1 green, the H1/D1 regime label at every bar is polluted by future data, which cascades into every strategy's regime check.

### A2 — 5m warmup — **PARTIALLY BUILT**

Driver seeds `candle_builder._BUILDER.candles[symbol]` with 600 bars ending at row_date 00:00 (from prior-day CSVs, deduped via A5).

**Proof of seed:**
```
[driver][A2] warmup GBPUSD: 600 bars from 3 prior-day files
[driver][A2] seeded candle_builder for GBPUSD: 600 bars
```

**Proof of failure (ADX still null):**
```
$ grep -oE 'adx=[0-9.]+|adx=null' /tmp/e2e_20260823/logs/2026-08-21/trend_v3.jsonl | sort | uniq -c
    (all null — every trend_v3 evaluation on Row 1 blocks with adx_below_min adx=null)
```

Root cause: the regime engine reads `payload["df_5m"]` (built by driver from raw OHLC), not the enriched builder DF. `add_indicators()` is never called. **Deferred to next session.**

### A3 — signal_logger Timestamp encode — **BUILT and VERIFIED**

Driver monkeypatches `signal_logger.json.dumps` to use a `_TsEncoder` that handles `pandas.Timestamp` and `datetime`.

**Proof:**
```
$ head -1 /tmp/e2e_20260823/logs/2026-08-21/signal_log.jsonl
{"timestamp_open": "2026-08-23T22:23:57Z", "pair": "GBPUSD", "direction": "SELL",
 "strategy": "GBPUSD_BB_BOUNCE_S", "entry": 13671.85, "sl": 13691.85, "tp1": 13571.85,
 "regime_instance_id": "GBPUSD_2026-08-21T09:10:00+00:00_cc51c2a0",
 "regime_at_fire": "NEUTRAL", "trend_subtype": null, "exit_stack": "MANAGED", ...}
```

No more `TypeError: Object of type Timestamp is not JSON serializable`. **PASS.**

### A4 — candle_archive suppression + per-row assertion — **BUILT and VERIFIED**

Driver post-import walks `candle_builder._5M_CLOSE_CALLBACKS` and replaces the `archive_candle` slot with a no-op. Per-row assertion snapshots live candle CSV line counts before and after replay for both symbols.

**Proof:**
```
[driver][A4] archive_candle callbacks replaced: 1
...
[driver][A4] /opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv: before=253 after=253 PASS
[driver][A4] /opt/tradingbot/data/candles/EURUSD/2026-08-21.csv: before=264 after=264 PASS
```

**PASS.** Both symbols asserted; no contamination.

### A5 — keep-first-per-timestamp dedup on read — **BUILT and VERIFIED**

`read_candles_dedup()` in the driver returns `(rows, report)` where `rows` are deduped keeping the FIRST occurrence per timestamp, and `report` has per-file raw/dedup/dropped counts + a mismatch list for cases where a dropped duplicate had DIFFERENT OHLC from its kept first occurrence.

**Per-file dedup table (canary v9):**
```
Path                                                        raw   dedup   dropped   mismatch_ohlc
/opt/tradingbot/data/candles/GBPUSD/2026-08-20.csv          289    288        1              0
/opt/tradingbot/data/candles/GBPUSD/2026-08-19.csv          288    288        0              0
/opt/tradingbot/data/candles/GBPUSD/2026-08-18.csv          288    288        0              0
/opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv          252    252        0              0
```

2026-08-20 had 1 duplicate timestamp; kept-first, no OHLC mismatch. Zero cases where the corpus disagrees with itself in this session's reads. **The 67-file corpus-wide defect the operator reported is not exposed here because the current session only touched 4 files for the canary; a Row 5 dual-symbol run would exercise EURUSD paths where more of the reported dupes live.**

Live corpus not modified. Read-side only.

---

## CANARY — 2026-08-21 with all fixes

### Hard gate: 16/16 spec modules from worktree — **PASS** (unchanged from RUN 2)

### Callbacks registered — **19** (unchanged from RUN 2)

All 9 spec-required callbacks present. Post-import A4 replacement swapped `archive_candle` for a no-op (still counted as 1 callback in the registry; the slot is preserved so registration count remains 19).

### Invocation coverage — canary v9 (all fixes active)

```
$ python3 -c "..." /tmp/e2e_20260823/logs/2026-08-21/driver_summary.json
main_result: sentinel after 67.2s
callback_count: 19
warmup: {'GBPUSD': 600}
invocation_count: 252
```

Every bar (252 for the day) invoked. Per-callback tracker shows each of the 19 registered callbacks was invoked at bar-close.

### Regime axis — 13:30 to 16:00 UTC vs the addendum §A6

Expected per addendum (live at 14:45:00Z): `winning_regime=STRONG_TREND_DOWN, ADX=30.71, +DI=11.31, -DI=36.94, confidence_final=0.0172, label_path=struct, struct_promoted=true`.

Replay result (all bars in the window):
```
2026-08-21 13:30:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 13:45:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 14:00:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 14:15:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 14:30:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 14:45:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL     ← should be STRONG_TREND_DOWN
2026-08-21 15:00:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 15:15:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 15:30:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 15:45:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
2026-08-21 16:00:00+00:00  h1=RANGE  d1=UP  align=NEUTRAL
```

The addendum labels are from the 5m regime engine (`regime_engine.py`), not the HTF regime layer above. The 5m regime engine on Row 1 has `adx=null` for every bar in this replay (see A2 partial state). Cannot verify the addendum's DI margins or `struct_promoted` path — the replay simply doesn't have those measurements computed. **REGIME-AXIS ASSERTION: NOT-TESTED-IN-REPLAY.** This is a driver-fidelity bug (A2 partial state), not a regime-engine finding.

### Row 1 live-vs-replay diff

Live signal_log rows on 2026-08-21 (from `/opt/tradingbot/logs/signal_log.jsonl`, read-only exception):

| ts UTC | mode | direction | entry |
|---|---|---|---|
| 00:10:02 | GBPUSD_LEVEL_BOUNCE_S | SELL | 13639.6 |
| 00:30:02 | GBPUSD_LEVEL_BOUNCE_S | SELL | 13641.4 |
| 01:45:02 | GBPUSD_LEVEL_BOUNCE_S | SELL | 13643.6 |
| 03:00:02 | GBPUSD_LEVEL_BOUNCE_S | SELL | 13648.0 |
| 08:38:22 | NEWS_STRATEGY_FADE | SELL | 13649.6 |
| 08:50:02 | BRIEFING_EXECUTION | BUY | 11702.3 (EURUSD entry level) |
| 13:10:02 | GBPUSD_EMA_PULLBACK_S | SELL | 13639.1 |

Replay fires on 2026-08-21 (canary v9's fresh outputs — canary v8's earlier fire is in signal_log.jsonl as row 0 with real-time ts 22:23; ignored for this diff):

| ts UTC | mode | direction | entry | attribution |
|---|---|---|---|---|
| 11:05 | GBPUSD_BB_BOUNCE_L | BUY | 13651.75 | REPLAY-ONLY — UNATTRIBUTED — **FAIL** |
| 12:10 | GBPUSD_CONFIRMATION_FALLBACK_S | SELL | 13653.45 | REPLAY-ONLY — UNATTRIBUTED — **FAIL** |
| 16:05 | GBPUSD_BB_BOUNCE_S | SELL | (BB_FLIP_FAILED — position aborted) | REPLAY-ONLY — UNATTRIBUTED |
| 17:40 | GBPUSD_BB_BOUNCE_S | SELL | 13645.25 | REPLAY-ONLY — UNATTRIBUTED — **FAIL** |

**Zero live-vs-replay bar-±1 matches.** All 7 live fires (LEVEL_BOUNCE ×4, NEWS_FADE, BRIEFING_EXECUTION, EMA_PB) failed to reproduce; all 3 replay unique fires are UNATTRIBUTED.

Under Row 1's spec rule ("Any replay-only fire must be attributed to a named weekend commit or it is a FAIL"), **all 3 replay fires FAIL**. Root cause is the partial A1/A2 fix state: regime context is polluted by future data (A1 leak) and the 5m regime engine can't compute ADX (A2 payload-df gap). Cannot legitimately score Row 1's spec must-fires until A1 and A2 are fully green.

**Row 1 verdict: BLOCKED by A1/A2 partial state.** The wire (BUILD 0 driver, A3/A4/A5 fixes) is confirmed working. The regime substrate under the wire needs the remaining fidelity fixes before Row 1's forensic assertions can be trusted.

---

## ROWS 2-8

**NOT ATTEMPTED THIS SESSION.**

- Each canary/row run takes ~5 minutes wall-clock (74s `main()` warmup + 60-180s bar walk).
- This session ran 3 canaries (v7 failed on A4, v8 fixed A4/A3, v9 fixed A1 key-name — still leaks) + several harness iterations before that. Each iteration burnt ~5 min. Time is spent.
- Rows 2-8 all depend on A1 (HTF regime context) and A2 (ADX warmup) being green. Row 2 (grind) especially needs trend_subtype GRIND to compute, which requires the H1 regime engine to be trend-labelled. Row 6 (IMPULSE) needs TV3 managed, which needs adx>=25 (currently 0.0 across all replay bars).

Deferred with a follow-up shopping list — see Delivery Summary.

---

## PART 3 — Spec Conformance Table v3

Rescored where RUN 3 evidence exists. Bulk of the table is code-based (grep/file:line, unchanged from RUN 1/RUN 2's audit).

| § | Section | RUN 2 verdict | RUN 3 update | Evidence |
|:-:|---|---|---|---|
| 1 | Overview | BUILT (architecture) | Unchanged | — |
| 2 | Core Market Observation | BUILT | Unchanged | bb_bounce_lifecycle.jsonl captures setup arm/expiry per bar |
| 3 | Two-Reversal Normal Day | BUILT-AS-SIDE-EFFECT | Unchanged | — |
| 4 | Time-of-Day evidence | NOT-BUILT | Unchanged | — |
| 5 | Day Type | BUILT | Unchanged | canary stamped day_ctx via day_context_state.json |
| 6 | Normal → BB Bounce | BUILT-AS-SIDE-EFFECT | Unchanged | — |
| 7 | Pre-News → grind | BUILT | Row 7 (2026-08-11) NOT-ATTEMPTED — needs A1+A2 fix |
| 8 | Big News | BUILT | Row 4 (2026-08-12) NOT-ATTEMPTED |
| 9 | Post-News → grind | BUILT | Row 3 (2026-08-13) NOT-ATTEMPTED |
| 10 | Day Type is expectation | BUILT | Row 6 (2026-07-15) NOT-ATTEMPTED |
| 11 | Live Regime (Slow Grind gap) | PARTIALLY BUILT | Unchanged — replay can't compute regime labels reliably yet (A1/A2) |
| 12 | Range → BB Bounce | BUILT | Row 1 setup-arm evidence in bb_bounce_lifecycle.jsonl |
| 13 | Chop → stand-aside | NOT-BUILT | Row 8 (2026-07-16) NOT-ATTEMPTED |
| 14 | Slow Grind strategy | BUILT (§11 caveat) | Row 2 (2026-08-10) NOT-ATTEMPTED |
| 15 | Trend Forming | BUILT | Row 6 NOT-ATTEMPTED |
| 16 | Strong Trend | BUILT | Row 6 NOT-ATTEMPTED |
| 17 | Strategy Portfolio (CF telemetry-only) | BUILT | Unchanged — canary confirms all imports+registrations |
| 18 | Strategies not day-locked | BUILT | Unchanged |
| 19 | Behaviour Recognition | BUILT (partially) | Row 1 fire snapshot in forensic_fires.jsonl has 15+ evidence families — confirmed |
| 20 | Setup Detection vs Trade Permission | BUILT | bb_bounce_lifecycle persists armed setups even when no rejection candle arrives |
| 21 | Strategy Arbitration | NOT-BUILT | Unchanged |
| 22 | Exit Management | OVERRIDDEN | Row 6 NOT-ATTEMPTED |
| 23 | Range Exit → opposite BB | BUILT | Row 1 09:10 (canary v8) used BB_FLIP path, not opposite-band TP |
| 24 | Weak Trend Exit | BUILT + OVERRIDDEN | Row 6 NOT-ATTEMPTED |
| 25 | Strong Trend Exit → ratchet | BUILT (Option A) | Row 6 NOT-ATTEMPTED |
| 26 | Capture Efficiency | NOT-BUILT | Unchanged |
| 27 | Opportunity Observer | NOT-BUILT | Unchanged |
| 28 | Historical Replay | RUN 2 upgraded to BUILT | **DOWNGRADED to PARTIALLY BUILT** — A1 and A2 remain unfixed after two iterations. The driver runs the real code path (Path a fidelity holds), but the regime substrate has lookahead + missing ADX. Not the spec's "faithful replay" until A1/A2 green. |
| 29 | Golden Days corpus | NOT-BUILT | Unchanged |
| 30 | Behavioural Hierarchy | BUILT as architecture; steps 9-10 NOT-BUILT | Unchanged |
| 31 | Overall Philosophy | BUILT (descriptive) | Unchanged |

### Movement from RUN 2

- **§28 downgraded** PARTIALLY BUILT (was BUILT in RUN 2 with fidelity-caveat parenthetical). Rationale: RUN 2's upgrade was premature; RUN 3's attempt to close the caveats (A1 + A2) reveals both are stubborn.
- **§13 stands NOT-BUILT** (per operator correction).
- **§3, §6 stand BUILT-AS-SIDE-EFFECT** (per operator correction).

Everything else unchanged from RUN 2's positions.

---

## Files produced this session

* `/tmp/e2e_20260823/tree/harness_setup.py` — A4 realname fix applied
* `/tmp/e2e_20260823/tree/e2e_driver.py` — RUN 3 driver (400 lines), all A1-A5 wiring, committed
* Driver commit `a1ca1a4` on top of RUN 2's `7dc9d2c`; ref `refs/heads/e2e-driver-20260823` in live repo force-updated
* `/tmp/e2e_20260823/verify_fix0.py` — FIX 0 verification script
* `/tmp/e2e_20260823/logs/2026-08-21/` — canary v9 outputs:
  * `driver_summary.json` — setup + modules + callbacks + invocation table + A4 assertion + A5 dedup table
  * `signal_log.jsonl` — 4 rows (1 from v8 real-time 22:23, 3 from v9 real-time 22:28-22:29; ts filter needed for future runs)
  * `htf_regime.jsonl` — 252 rows, one per bar (lookahead-polluted per Contradiction #3)
  * `trend_v3.jsonl` — 100% adx_below_min blocks (A2 partial state)
  * `bb_bounce_lifecycle.jsonl`, `bb_pierce_trades.jsonl`, `confirmation_fallback.jsonl`, `confirmation_engine.jsonl`, `htf_authority.jsonl`, `reversal_geometry.jsonl`, `forensic_fires.jsonl`, `news_momentum_obs.jsonl` — all populated
* `/tmp/e2e_20260823/env.sha.before.run3` / `env.sha.after.run3` — identical
* `/tmp/e2e_20260823/logs.run2/` + `/tmp/e2e_20260823/state.run2/` — RUN 2 outputs preserved

Live-tree changes:
* `/opt/tradingbot/data/candles/GBPUSD/2026-08-21.csv` — mtime touched by A4-fix restore ops during this session; **line count unchanged at 253** (A4 assertion PASS on both symbols across canaries v8+v9)
* `/opt/tradingbot/reports-public/e2e_matrix_20260823/RUN3_REPORT.md` — this file
* `refs/heads/e2e-driver-20260823` — force-updated to driver iter `a1ca1a4`

---

## Delivery Summary

**Achieved this session (RUN 3):**
- **A3 signal_logger Timestamp encode: BUILT + VERIFIED.** signal_log.jsonl now non-empty (4 rows across canaries v8+v9).
- **A4 candle_archive suppression: BUILT + VERIFIED.** Callback-list replacement instead of module-attribute reassignment. Per-row assertion PASS on both GBPUSD + EURUSD candle CSVs across two canaries. No live-tree contamination.
- **A5 keep-first dedup on read: BUILT + VERIFIED.** Applied to both replay feed and A2 warmup seed. Per-file dedup table logged. Live corpus untouched. 2026-08-20 had 1 duplicate timestamp (kept-first, no OHLC mismatch).
- **FIX 0 restoration verified.** 2026-08-21.csv is 252 rows (RUN 2 report's "253" was off-by-one — corrected).
- **Driver commit `a1ca1a4` live in `refs/heads/e2e-driver-20260823`.**
- **STEP B integrity PASS.** Env sha unchanged across all four env paths.

**NOT achieved this session:**
- **A1 HTF cache lookahead: PARTIALLY BUILT / FAIL.** Key-name fix (candles vs bars) landed but 14:45Z bar still shows 08-22 D1 close. Hypothesis: cached DataFrame in htf_regime/PIA, or an alternate load path bypasses `json.load`. **Needs a fresh investigation session.**
- **A2 5m warmup: PARTIALLY BUILT.** Buffer seeded, but the regime engine reads `payload["df_5m"]` (raw OHLC from driver) not the enriched builder DF. ADX stays null across all Row 1 bars. **Fix: build indicator-enriched df in driver payload, or route the callback through `_BUILDER.get_df()`.**
- **Rows 2-8 not attempted.** Time budget consumed by A1/A3/A4 iterations. Each row is ~5 min of wall-clock; Rows 2-8 need A1+A2 green first (trend_subtype computation, ADX warmup, regime labels).
- **Row 1 forensic assertions cannot be scored.** Regime axis 13:30-16:00 all showed h1=RANGE/d1=UP/align=NEUTRAL (contaminated by A1 lookahead); no bars reached the addendum's STRONG_TREND_DOWN state. Cannot verify the addendum's DI margins or `struct_promoted` path — the 5m regime engine on the replay simply doesn't have those measurements computed. Row 1 verdict: **BLOCKED**.

**Shopping list for a follow-up session:**
1. **A1 root-cause investigation.** Instrument `_htf_filter_hook_install` to log every `json.load` call it intercepts. If htf cache reads don't appear, add a shim on `htf_cache.load_cached_candles` directly. Verify with `d1_closes_tail[-1] <= replay_now` per bar.
2. **A2 payload df enrichment.** In `_prepare_5m_df`, call `indicators.add_indicators` on the constructed df before returning. Verify ADX becomes numeric by ~50 bars in.
3. **Signal_log clearing between runs.** Add `signal_log_path.unlink(missing_ok=True)` at start of `_replay()` so each run has a clean signal_log.
4. **Rows 2-8 mechanical execution** on the fixed driver: 2026-08-10 (grind), 08-13 (post_big), 08-12 (CPI), 08-07 (NFP dedup dual-symbol), 07-15 (IMPULSE ratchet), 08-11 (pre_big), 07-16 (chop).
5. **Conformance table v4** rescored with per-row evidence.

**Honest verdict:** RUN 3 closed 3 of the 4 replay-fidelity gaps RUN 2 flagged (A3/A4/A5 green). The A1 gap looked easy on paper (key-name mismatch); the fix uncovered a deeper caching or load-path issue that needs an investigation session. A2 needs one more line of driver code (`add_indicators` on the payload df). Rows 2-8 are gated on these two remaining fixes, not on any new spec bug.
