# Grind path — rolling window ruling — 2026-08-27

Host 161, HEAD verified at `33d0162` before change. Operator ruling
applied at `cbe9b75` (local, no push).

Detection: ALWAYS-ON (rolling trailing window; no session anchor).
Firing: UNCHANGED (TREND_V3_SESSION_START/END gate 07:00-16:00 UTC).

## Contradictions first

- **Session anchor removed from the classifier.** Prior code read the
  `time` column to filter for `_times >= 07:00`. New code does not
  consult the time column at all — the trailing window walks the buffer
  bar-by-bar, so a 00:05Z bar's window reads 23 prior 5m ratios from the
  tail of the previous UTC day. No state reset at midnight.

- **`insufficient_rolling_history` is virtually unreachable under
  default configs**, because the earlier `insufficient_history` check
  (buffer < 122 rows) fires first for cold buffers. Under normal
  operation with a warm buffer the trailing 24 rolling ratios are
  always available; the new reason string only appears if the operator
  bumps `GRIND_ROLL_MIN_BARS` above what the buffer supplies, or if
  the buffer has NaN gaps that erode the trailing ratios. This matches
  the operator ruling ("should only ever appear at Sunday open / after
  gaps") — both scenarios collapse to a `None`-return no-fire, which
  is the operator-visible behaviour they specified.

- **Chop-leak class-separation preserved.** The 07-16 chop-day tape
  test (large bars, no drift) still lands `subtype=None
  reason=day_ratio_too_high` on non-trending labels and `IMPULSE` on
  trending — same as under the session-anchored form.

- **07:00-anchor session bar count → rolling bar count is a rename,
  not a semantic shift.** The RATIO computed is unchanged (mean of
  the last 12 bar ranges / baseline_pips). Only the SET over which we
  take the median changed: from "same-date session-in bars ≥ 07:00Z"
  to "trailing GRIND_ROLL_WINDOW_BARS non-NaN ratios."

## Build — regime_engine.py

Env config table:
| Env | Old default | New default | Kept? |
|---|---|---|---|
| `GRIND_DAY_RATIO_MAX` | 1.05 | 1.05 | ✅ |
| `GRIND_DAY_MIN_BARS` | 24 | — | ❌ removed |
| `GRIND_DAY_SESSION_ANCHOR_UTC` | 07:00 | — | ❌ removed |
| `GRIND_ROLL_WINDOW_BARS` | — | 24 | ✅ new |
| `GRIND_ROLL_MIN_BARS` | — | 24 | ✅ new |

Output-dict field renames (also propagated through `debug`, top-level
classify return, `_telemetry_record`, and TV3 `_latest_regime`):
- `session_bars_elapsed` → `rolling_bars_available`
- `day_median_bar_ratio` → `rolling_median_bar_ratio`

Reason string rename:
- `day_context_warmup` → `insufficient_rolling_history`

`[GRIND-PATH]` verdict tag rename:
- `warmup` → `insufficient_history`

Classifier body change (`_compute_trend_subtype`, ~40 lines simplified
to ~20):

```python
# Before (session-anchored)
if _ts_col and "high" in df.columns and "low" in df.columns:
    _ts_all = pd.to_datetime(df[_ts_col], utc=True, errors="coerce")
    ...
    _session_mask = ((_dates == _last_date)
                     & (_times >= _GRIND_DAY_SESSION_ANCHOR))
    _session_ratios = _ratio_all[_session_mask].dropna()
    _sess_bars = int(len(_session_ratios))
    if _sess_bars > 0:
        _day_med = float(_session_ratios.median())

# After (rolling)
if "high" in df.columns and "low" in df.columns:
    _range_all = (df["high"].astype(float) - df["low"].astype(float))
    _ratio_all = (
        _range_all.rolling(GRIND_BAR_WINDOW).mean() / float(base)
    ).dropna()
    _trail = _ratio_all.tail(GRIND_ROLL_WINDOW_BARS)
    _rolling_bars = int(len(_trail))
    if _rolling_bars > 0:
        _rolling_med = float(_trail.median())
```

Downstream in `_compute_trend_subtype`, unchanged:
- Chop-leak guard (`bar_size_ratio <= GRIND_BAR_RATIO_MAX AND
  one_sided_ema72 >= GRIND_ONESIDED_MIN`)
- Trending-vs-non-trending branch (line ~1290)
- `day_ratio_too_high` / `non_trending_no_grind` reasons

## TV3 verification — no session changes

`gbpusd_trend_v3.py` diff scope:
- `_latest_regime` forwards renamed keys only (`rolling_median_bar_ratio`,
  `rolling_bars_available`).
- Session gate (`SESSION_GATE_ENABLED=1`, `SESSION_START_UTC=07:00`,
  `SESSION_END_UTC=16:00`) — untouched. Verified by `grep`:
  ```
  SESSION_GATE_ENABLED = _env_bool("TREND_V3_SESSION_GATE_ENABLED", "1")
  SESSION_START        = _env_hhmm("TREND_V3_SESSION_START_UTC", "07:00")
  SESSION_END          = _env_hhmm("TREND_V3_SESSION_END_UTC",   "16:00")
  ```
- All grind-path gates in `evaluate()` — untouched. The consolidation-
  break trigger (`gbpusd_trend_v3.py:1503-1541`), grind cooldown, and
  regime widening logic all read `reg_dbg.get("trend_subtype")` and are
  agnostic to how the day-scale was computed.
- Pre-07:00 GRIND state + post-07:00 first-in-session fire integration
  test: **passes** (see below).

## Tests

`tests/unit/test_grind_path_suppression_logging.py` (11 tests, all
pass):

| Test | Purpose |
|---|---|
| `test_insufficient_rolling_history_emits_grind_path_info_line` | Verdict tag = `insufficient_history` |
| `test_grind_path_verdict_deduped_per_bar` | Idempotent per (symbol, ts) |
| `test_grind_path_verdict_grind_stamps_verdict_grind` | GRIND state emits verdict=grind |
| `test_tv3_log_block_mirrors_grind_reason_to_journal` | TV3 grind-tagged block → journal |
| `test_tv3_log_block_mirrors_grind_regime_block` | grind_widening=True flag → journal |
| `test_tv3_log_block_non_grind_reason_stays_jsonl_only` | Scope test — no firehose |
| `test_rolling_median_arithmetic_matches_manual_computation` | ✨ Ruling §6: rolling arithmetic |
| `test_midnight_continuity_no_reset_at_0005z` | ✨ Ruling §2: midnight span |
| `test_sunday_open_2105z_insufficient_history` | ✨ Ruling §6: Sunday gap |
| `test_pre_0700_grind_state_survives_to_post_0700_fire` | ✨ Ruling §4: state persists |
| `test_0716_chop_tape_classifies_no_grind` | ✨ Ruling §3: chop-leak preserved |

`tests/unit/test_phase1_3d_grind_dayscale_and_direction.py` (11
tests, all pass): 4 day-scale tests migrated to rolling equivalents;
7 concern tests (spine deferral, C-5 widening, schema contract)
unchanged and still green.

## Suite delta

Grind/regime/tv3 slate: 97 pass, 1 pre-existing failure
(`test_anti_drift_all_dispatch_sites_have_permits_call` — unrelated,
about `_on_5m_close_pivot_break` missing a `regime_matrix.permits`
call; verified pre-existing via `git stash --keep-index`).

Zero new failures.

## Diffs (summary)

```
regime_engine.py                                              | +91 -115
gbpusd_trend_v3.py                                            |  +8 -7
tests/unit/test_phase1_3d_grind_dayscale_and_direction.py    | +71 -71
tests/unit/test_grind_path_suppression_logging.py            | +212 -22
```

Local commit: `cbe9b75` on `feat/trend-stretch-brake-adx-floor`. No
push.

## Restart note

Activates at operator's next `safe_restart.sh` at a chosen boundary
(EOD flat or similar). First post-restart bar close will emit
`[GRIND-PATH]` with the rolling-form scalars:

```
[GRIND-PATH] symbol=GBPUSD ts=<...> regime=<...> verdict=<...>
             subtype=<...> reason=<...>
             rolling_bars=<0-24> rolling_med=<float|None>
             grind_dir=<UP|DOWN|-> one_sided=<float>
             bar_ratio=<float>
```

Sanity check post-restart (in-session, ~15 min after warm-up):

```
journalctl -u autobot.service --utc --since '<restart_ts>' \
    | grep '\[GRIND-PATH\]' | tail -5
```

Expected: `verdict=grind|impulse|blocked`, `reason=-` or a specific
non-warmup reason. If `verdict=insufficient_history` persists past
~10 minutes of ticks, the buffer never warmed — separate issue
(candle_builder / htf_cache).

Overnight verification (once past midnight): search for the same
tag between 00:00-06:00Z. Expected: nonzero lines with populated
`rolling_med` values matching the tape.

END
