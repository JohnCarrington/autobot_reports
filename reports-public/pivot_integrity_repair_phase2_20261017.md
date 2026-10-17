# Pivot Data Integrity Repair — Phase 2

**Authorised research-branch repair only. NOT DEPLOYED.**

- Generated: 2026-10-17
- Branch: `research/level-arrival-turn-20261017`
- Base: `5f54273` (Phase 1 scheduler + replay-script fix)
- Prerequisite reports:
  - `pivot_audit_20261017.md` (defect identification)
  - `pivot_integrity_repair_20261017.md` (Phase 1 fixes)

Phase 2 completes the three remaining pivot-data integrity items:
IG retrieval contract, session-coverage validator, downstream-consumer impact map.

---

## A. Root-cause explanation

### A.1 Original DataFrame-vs-list fault (fully fixed)

Commit `2832285` (2026-10-06) already made `fetch_latest_daily_bars` accept BOTH list-of-dicts (`return_dataframe=False` path) AND the MultiIndex-column DataFrame produced by `trading_ig` under the production default `return_dataframe=True`. The error string `ig_rest_returned_dataframe_not_list` was only observed on **2026-10-06** at 07:33:54–07:36:49 UTC (per `logs/daily_journal.md`), i.e. the same day the fix landed. **It is NOT the current cause of staleness.**

### A.2 Current latent IG-retrieval defects (fixed by this phase)

Phase 2 audit of `fetch_latest_daily_bars` identified two remaining issues:

#### (1) Auth-detection substring bug

```python
# PRE-REPAIR:
if any(k in msg for k in ("unauthorized", "forbidden",
                           "invalid.*session", "token", "auth")):
    raise IGAuthError(...)
```

`"invalid.*session"` is a regex-style string being passed to Python's `in` operator (plain substring match). It only matches the LITERAL string `"invalid.*session"` (with a dot and asterisk between the words), which NEVER appears in real IG error messages like `"Invalid session"` or `"Session expired"`. Consequence: real auth failures slipped through as generic `RuntimeError('ig_rest_fetch_error: ...')`, bypassing the `IGAuthError` sentinel path (which writes an auth-abort file + emits a dedicated Telegram alert).

Fixed to a plain substring set:

```python
auth_markers = (
    "unauthorized", "forbidden",
    "invalid session", "session expired", "session invalid",
    "token", "auth", "401", "403",
)
```

Verified by six new unit tests covering real IG error message patterns.

#### (2) DataFrame shape-mismatch would silently poison the payload

`_df_prices_to_raw_list` reads MultiIndex cells with `cap in ("Open", "High", "Low", "Close")`. If a future `trading_ig` library upgrade renames these to lowercase (or any other variant), **every `(bid, ask)` cell becomes `None`**. `extract_bar_ohlc` then returns `None` for every bar, `previous_daily_bar` picks the last bar (with all-None legs), `build_pivots_payload` raises `RuntimeError("previous_bar_missing_bid_or_ask_leg")` — which `run_daily_fetch` catches as `any_failure=True` and the pivot file is simply NOT written. The operator sees a quiet `[DAILY-PIVOTS] GBPUSD pivot-build failed: previous_bar_missing_bid_or_ask_leg` warning with no clue that the DataFrame columns changed.

Fixed by validating the conversion AFTER `_df_prices_to_raw_list`:

```python
converted = _df_prices_to_raw_list(prices)
if converted:
    ok_rows = 0
    for row in converted:
        for leg in ("openPrice", "highPrice", "lowPrice", "closePrice"):
            node = row.get(leg) or {}
            if any(node.get(k) is not None for k in ("bid", "ask")):
                ok_rows += 1
                break
    if ok_rows == 0:
        raise RuntimeError(
            f"ig_rest_dataframe_shape_mismatch: zero bars had "
            f"non-null bid/ask after conversion. columns={cols_repr}"
        )
```

Now the operator gets an immediate, actionable error that includes the actual DataFrame columns.

### A.3 ASK and BID preserved end-to-end (FACT)

Verified by `TestIGRetrievalDataFramePath::test_dataframe_with_bid_ask_preserved`:

```
bars[0]["openPrice"]["bid"] == 13220.0
bars[0]["openPrice"]["ask"] == 13221.5
bars[0]["highPrice"]["ask"] == 13279.5
bars[0]["lowPrice"]["ask"]  == 13186.75
bars[0]["closePrice"]["ask"] == 13270.75
```

Round-trip through `extract_bar_ohlc(..., basis="ask")` returns the ask leg unchanged.

### A.4 No global IGService configuration change (FACT)

The repair does NOT touch `return_dataframe` on the live IGService singleton. Every other consumer of IGService (news_strategy, trade_executor, dashboards) continues to receive DataFrames. The pivot fetch's defensive conversion is self-contained in `ig_daily_pivots.py`.

---

## B. Minimal code diff

Three files changed on research branch:

### B.1 `ig_daily_pivots.py` — auth marker fix + DataFrame validation

```diff
--- a/ig_daily_pivots.py
+++ b/ig_daily_pivots.py
@@ ig_daily_pivots.py:489-513 (fetch_latest_daily_bars body) @@
     except Exception as exc:
+        # pivot-integrity-repair-20261017 Phase 2 T1: the previous
+        # substring list contained the regex-style ``"invalid.*session"``
+        # which the ``in`` test never matched against real IG error
+        # messages (e.g. ``"Invalid session"``, ``"session expired"``).
         msg = str(exc).lower()
-        if any(k in msg for k in ("unauthorized", "forbidden",
-                                    "invalid.*session", "token", "auth")):
+        auth_markers = (
+            "unauthorized", "forbidden",
+            "invalid session", "session expired", "session invalid",
+            "token", "auth", "401", "403",
+        )
+        if any(k in msg for k in auth_markers):
             raise IGAuthError(f"ig_rest_auth_error: {exc!r}") from exc
         raise RuntimeError(f"ig_rest_fetch_error: {exc!r}") from exc
     if not isinstance(resp, dict):
         raise RuntimeError(f"ig_rest_unexpected_response_type: {type(resp).__name__}")
     prices = resp.get("prices")
     if prices is None:
         raise RuntimeError("ig_rest_no_prices_key")
     if hasattr(prices, "columns") and not isinstance(prices, list):
-        return _df_prices_to_raw_list(prices)
+        converted = _df_prices_to_raw_list(prices)
+        if converted:
+            ok_rows = 0
+            for row in converted:
+                for leg in ("openPrice", "highPrice", "lowPrice", "closePrice"):
+                    node = row.get(leg) or {}
+                    if any(node.get(k) is not None for k in ("bid", "ask")):
+                        ok_rows += 1
+                        break
+            if ok_rows == 0:
+                try:
+                    cols_repr = list(prices.columns)
+                except Exception:
+                    cols_repr = "<unreadable>"
+                raise RuntimeError(
+                    f"ig_rest_dataframe_shape_mismatch: zero bars had "
+                    f"non-null bid/ask after conversion. columns={cols_repr}"
+                )
+        return converted
```

### B.2 `session_coverage.py` — new validator (175 LOC)

New module. Pure, no I/O. Returns `SessionCoverageResult` with:

- `status` ∈ {`OK`, `INVALID`}
- `n_bars_in_window`, `expected_bars`, `missing_count`
- `duplicate_count`, `off_grid_count`, `future_count`, `out_of_window_count`
- `violations: List[str]`, `reason: str`

Supports `closure_windows` for market closures and `allowed_missing_bars` for benign feed glitches. Rejects bars with `ts > as_of_utc` (future-data gate).

### B.3 `scripts/srr_v1_friday_regression.py` — swap heuristic for validator

```diff
-    _in_window = [b for b in bars if _d1_start <= b.ts < _d1_end]
-    if len(_in_window) < 280:
-        raise SystemExit(f"[FATAL] IG D1 window contains only {len(_in_window)} 5m bars")
+    import session_coverage as sc
+    cov = sc.validate_session_coverage(
+        bars=bars,
+        trading_day=datetime.fromisoformat("2026-10-16").date(),
+        as_of_utc=datetime(2026, 10, 16, 22, 0, tzinfo=timezone.utc),
+        allowed_missing_bars=2,
+    )
+    if cov.status != "OK":
+        raise SystemExit(
+            f"[FATAL] IG D1 session-coverage validation FAILED: {cov.reason}"
+        )
```

---

## C. IG retrieval contract tests

`tests/unit/test_pivot_integrity_phase2.py` — 10 new tests exercising the retrieval contract. Combined with Phase 1's 23 tests + SRR V1's 18 tests + authority-loader's 5 tests = **66 total tests, all pass**.

### C.1 List-of-dicts path (`TestIGRetrievalListPath`)
- `test_list_response_passthrough` — happy path.
- `test_malformed_response_wrong_type` — `resp` not a dict → `unexpected_response_type` RuntimeError.
- `test_malformed_response_no_prices_key` → `no_prices_key` RuntimeError.
- `test_prices_wrong_type` → `prices_wrong_type` RuntimeError.

### C.2 Auth detection (`TestIGRetrievalAuthDetection`)
- `test_unauthorized_detected` — "401 Unauthorized" → IGAuthError.
- `test_invalid_session_detected` — **"Invalid session" was MISSED pre-repair; now correctly classified**.
- `test_session_expired_detected`, `test_token_detected`, `test_403_detected` — all → IGAuthError.
- `test_generic_runtime_error_not_classified_as_auth` — "network timeout" → RuntimeError (not IGAuthError).

### C.3 DataFrame path (`TestIGRetrievalDataFramePath`)
- `test_dataframe_with_bid_ask_preserved` — happy path through full `_df_prices_to_raw_list` + `extract_bar_ohlc`.
- `test_dataframe_with_wrong_column_names_raises` — **lowercase column names would silently poison pre-repair; now raises `ig_rest_dataframe_shape_mismatch`**.

---

## D. Session coverage validation results

### D.1 Validator (`session_coverage.validate_session_coverage`) tests

`TestSessionCoverage` (8 tests, all pass):

| test | assertion |
|---|---|
| `test_ok_full_window` | 288 grid-aligned bars → status=OK |
| `test_truncated_rejected` | 220 bars → INVALID, missing=68 |
| `test_duplicates_rejected` | repeated ts → INVALID, duplicate_count=1 |
| `test_off_grid_rejected` | ts at :03 min → INVALID, off_grid_count=1 |
| `test_future_data_rejected` | bars past `as_of_utc` → counted and rejected |
| `test_closure_window_excuses_missing` | declared closure → gap NOT counted as missing |
| `test_out_of_window_counted` | pre-start ts → tracked, status still OK |
| `test_prior_day_monday_to_friday` | Mon→Fri weekend handling |

### D.2 Live result on 2026-10-16 Friday regression

```
session coverage: status=OK n_bars_in_window=288 expected=288
                  missing=0 duplicates=0 off_grid=0 future_rejected=0
                  out_of_window=540
```

The 540 out-of-window bars are 2026-10-14 00:00–22:00 UTC and 2026-10-15 22:00–2026-10-16 end-of-file — correctly ignored because they fall outside the IG D1 window for the 2026-10-16 trading day. The in-window count is exactly the expected 288.

---

## E. Downstream consumer impact map

Every live consumer of `cache/htf/daily_pivots.json` (via `ig_daily_pivots.read_pivots` / `read_dollar_direction`) was inspected. **The authoritative pivot path is enabled in production** (`IG_DAILY_PIVOTS_ENABLED=1` in `.env`).

| consumer | symbol/path | pivot basis read | stale-data handling | fallback behaviour | can fresh pivots change trading decisions? |
|---|---|---|---|---|---|
| **`session_trend_integration.bridge_pivots_to_session_trend`** | GBPUSD | `pairs_ask.pivots_ask` (`P/R1-3/S1-3`) | `read_pivots` returns `None` on `trading_date` mismatch; the bridge is a NO-OP. `session_trend.daily_pivots` keeps the previous value. | Caller: `autobot.py:9772` on every 5m heartbeat. If stale → `session_trend` snapshot's `daily_pivots` is from the LAST successful bridge call (potentially a prior day's state). | **YES, indirectly.** `session_trend_<SYM>.json:daily_pivots` is read by the NMS V3 direction gate's reader context (via `v3_state`), SRR V1's `extract_levels()`, and `view_builder._pivot_levels`. If stale, downstream reads return outdated pivot prices. |
| **`bb_pd_gate._try_ig_daily_pivots`** | GBPUSD | `pivots_ask` + `previous_bar.snapshotTimeUTC` as `pd_source_ts` | Returns `None` on stale `trading_date` → caller falls back to the legacy mid-based D1 calculation (`bb_pd_gate` has its own prior-day OHLC pipeline). | Gated by `IG_DAILY_PIVOTS_ENABLED=1`. Legacy fallback is CURRENTLY ACTIVE on every tick where the cache is stale. The `[PIVOTS] ig_daily_pivots unavailable` warning fires once per request. | **YES, directly.** `bb_pd_gate` participates in BB_BOUNCE admission decisions. Fresh pivots can change the pivot-distance gate's verdict. |
| **`level_ladder._compute_pdh_pdl`** | GBPUSD | `previous_bar.ask.high` / `.low` | Returns `None` on stale → legacy PDH/PDL calculation from local D1 cache. | Gated by `IG_DAILY_PIVOTS_ENABLED=1`. | **YES, indirectly.** Level-ladder PDH/PDL feed into bounce-engine and level-arrival logic. |
| **`view_builder._pivot_levels`** | GBPUSD + others | `pivots_ask` | No special handling — if `read_pivots` returns None, no pivot levels are drawn. | Used by the dashboard view. | **NO — dashboard only.** Not a trading decision. |
| **`bb_bounce_filters.*dollar_direction*`** | DXY only | `read_dollar_direction(trading_date)` → `{dxy_direction, implied_gbpusd_direction, close_d_minus_1, ...}` | On stale → the dollar-direction gate falls through without emitting a direction preference. | Gated by `IG_DAILY_PIVOTS_ENABLED=1`. | **YES, indirectly.** Dollar-direction is one filter among several in BB bounce gating; weight is small. |
| **`session_trend.set_daily_pivots`** (writer, upstream caller of `bridge_pivots_to_session_trend`) | per-symbol | ASK pivots copied verbatim | Idempotent write; keeps `source_date = doc['trading_date']` on success; silent on failure. | n/a (writer). | n/a (writer). |

**NMS V3 Direction Gate**: does NOT read `daily_pivots.json` directly. It reads `cache/session_trend_<SYM>.json:v3_state` (a trend state string, not a pivot price). However, that snapshot's `daily_pivots` dict is **populated via `bridge_pivots_to_session_trend`** — so when the authoritative file is stale, the snapshot carries pivots from the previous successful bridge call. See cascade in the table above.

**Strategy admission (`central_execution_gate`)**: does NOT read `daily_pivots.json`. Admission is pair/family/flag-gated, not pivot-gated.

**Execution (`trade_executor.execute_trade`)**: does NOT read `daily_pivots.json`. Entry/stop/target are set by the strategy proposal, not by pivots.

**Structural exit management (`qm_adaptive_exit`, `exit_dress`, `structure_exit`)**: do NOT read `daily_pivots.json`. Exits are driven by signal-log fields, breakeven stops, structure flips, and in-engine state — not pivot prices.

### Cascade impact when the authoritative file is stale

Pre-this-repair, when the live cache was 2 days stale:
```
daily_pivots.json (stale, 10-14)
       └── bridge_pivots_to_session_trend → NO-OP (returns None)
       └── bb_pd_gate._try_ig_daily_pivots → returns None → LEGACY FALLBACK fires
       └── level_ladder PDH/PDL → LEGACY FALLBACK fires
       └── view_builder → NO LEVELS DRAWN
       └── bb_bounce dollar_direction → no direction preference emitted
```

`session_trend_<SYM>.json:daily_pivots` kept the PRIOR SUCCESSFUL bridge's values (which happened to be the correct 10-14 pivots) — but no update was pushed for 10-15 or 10-16. Downstream readers of session_trend consumed outdated pivot numbers for ~63 hours.

**Confirmed by `logs/daily_journal.md` warning counts** on 10-15 and 10-16 (896-930 "cached date != requested" + 347-358 "ig_daily_pivots unavailable, falling back to legacy" per day).

---

## F. Regression test results

```
$ python3 -m unittest tests.unit.test_pivot_integrity_phase2 \
                      tests.unit.test_pivot_integrity_repair \
                      tests.unit.test_srr_v1 \
                      research.level_arrival_turn.tests.test_authorized_data_io

..................................................................
Ran 66 tests in 0.557s

OK
```

Breakdown:
- `test_pivot_integrity_phase2` — **10 new tests** (IG retrieval contract + session coverage).
- `test_pivot_integrity_repair` — 23 tests (Phase 1 — scheduler, replay, freshness).
- `test_srr_v1` — 18 tests (SRR V1 observer).
- `test_authorized_data_io` — 5 tests (Stage 0b manifest loader).

Also verified: the Friday regression script runs with the new coverage validator:

```
loaded 828 5m bars across ['2026-10-14', '2026-10-15', '2026-10-16']
session coverage: status=OK n_bars_in_window=288 expected=288
                  missing=0 duplicates=0 off_grid=0 future_rejected=0
                  out_of_window=540
```

Critical trade (`GBPUSD_TREND_V3_L 14:35:29 BUY @ 13367.9`) continues to resolve to:
```
nearest major: DAILY_PIVOT_R3 @ 13397.33
distance:       29.4 pips
R:R vs 12p SL:  2.45
```

Trading-rule invariants verified unchanged:
- `central_execution_gate` — no diff.
- `nms_v3_direction_gate` — no diff.
- `trade_executor._execute_trade_impl` — no diff.
- Broker-order payload (entry/stop/limit) — no code touching these in Phase 2.
- TP/SL specifications — no code touching these in Phase 2.
- Strategy enablement flags — no `.env` edits.
- `SRR_V1_ENABLED` — remains `0` default (inert).

---

## G. Production deployment risk assessment

### Changes that WOULD affect production if deployed

| change | behavioural delta on production |
|---|---|
| **`fetch_latest_daily_bars` auth-marker fix** | Real `Invalid session` / `Session expired` IG errors now correctly trigger `IGAuthError` → auth-abort sentinel + Telegram alert (previously silent generic `RuntimeError`). **Strictly safer.** |
| **DataFrame shape-mismatch guard** | A future `trading_ig` library update that renames columns now raises `ig_rest_dataframe_shape_mismatch` with the actual column list, instead of silently writing an all-None payload that fails sanity-floor downstream. **Strictly safer.** |
| **Phase 1 scheduler ordering fix** (prerequisite, already on branch) | Failed fetches retry after 30 min instead of locking the day. **Strictly safer.** |
| `session_coverage.py` | New module. Not imported by any live code path. Zero live effect. |
| `scripts/srr_v1_friday_regression.py` | Offline script. Not deployed. Zero live effect. |

### Changes that do NOT affect production

- `pivot_freshness.py` (Phase 1) — not wired into admission.
- All new test files.
- All regenerated reports under `reports/srr_v1/`.
- The report file in `reports-public/`.

### Deployment risk matrix (if operator chooses to deploy Phase 1 + Phase 2 to production)

| scenario | pre-repair | post-repair | risk delta |
|---|---|---|---|
| IG fetch succeeds | file written, pivots fresh | identical | zero |
| IG fetch returns bad DataFrame shape | file not written, cryptic sanity-floor error, pivots stale for 24 h | explicit error + 30-min retry | **BETTER** |
| IG auth fails (`Invalid session`) | returned as generic RuntimeError, no auth-abort, no Telegram, no retry for 24 h | IGAuthError, auth-abort file written, Telegram alert, scheduler retries after 30 min | **BETTER** |
| IG network timeout | one shot, no retry for 24 h | retries after 30 min | **BETTER** |
| Replay script against truncated candles | silently produced wrong pivots | explicit SystemExit with coverage details | **BETTER** (offline only) |

**No scenario in which the repair makes production worse.** Zero behaviour change on the happy path.

### What is NOT in the deployment scope

- The `IG_DAILY_PIVOTS_ENABLED` flag is unchanged (`=1` in production).
- No new flag is introduced.
- No new log is created in production (SRR V1 shadow journal and pivot-freshness logger are both default-OFF).
- No change to any strategy's trading rules.

---

## H. Outstanding issues

1. **Operational root cause of 10-15 / 10-16 process restarts** — AutoBot process evidence shows "cached date != requested" warnings starting at 14:14 UTC on 10-15 and 14:28 UTC on 10-16. Prior to those timestamps, no activity. The restart cause (systemd journal, host reboot, deploy cutover) is **outside this repair's scope**.
2. **Chart R3 ≈ 1.3380 methodology** — remains **UNRESOLVED** (per `pivot_audit_20261017.md` §5). No standard formula × session boundary reproduces the chart value from available price sources.
3. **IG daily API's "19-pip range" cached bar** — the live cache's `previous_bar.ask` has a suspiciously small range at `snapshotTimeUTC=2026-10-14T00:00:00`. Possibly a Columbus-Day shortened-session artefact from the IG REST side. **Needs IG-side documentation to resolve.**
4. **Non-GBPUSD symbols** — Phase 2 did not add contract tests for USDJPY / EURUSD / USDCAD. The DataFrame conversion is pair-agnostic, but the sanity-floor and the `check_sanity_floor` lookback window may need per-pair tuning (not touched here).
5. **Market-closure calendar** — `session_coverage.validate_session_coverage` accepts a `closure_windows` list but no module in-tree supplies a canonical closure calendar. Operators must pass it explicitly (default is no closures assumed).
6. **Alert on staleness** — the directive did NOT ask for alerts in Phase 2, but when the cache goes `STALE` for N hours, no Telegram alert currently fires. Deferred.
7. **Whether to wire `pivot_freshness` into any admission path** — explicitly deferred per Phase 1 scope.

---

## I. Boundary statement — NO merge, NO deploy

- All commits on `research/level-arrival-turn-20261017`.
- NO merge to any production branch.
- NO deployment.
- `.env` unchanged.
- `/opt/tradingbot/cache/htf/daily_pivots.json` unchanged on the production host.
- `/opt/tradingbot/cache/session_trend_GBPUSD.json` unchanged on the production host.
- No systemd service restarted.

**STOP. Awaiting explicit approval before any production action.**

*— end of pivot integrity repair Phase 2 report —*
