# News post-release rest-and-break event study — STOP report

**Date:** 2026-10-07
**Repo HEAD:** `08cbae4` on branch `fix/h1-trend-guard`
**Status:** STOP — the "existing consolidation primitive" in `news_continuation.py` cannot be called standalone to satisfy this specification. No lookalike has been written. No simulated numbers reported.

---

## Period that would have been covered

| Pair | Candle dir | First file | Last file | File count |
|---|---|---|---|---|
| GBPUSD | `/opt/tradingbot/data/candles/GBPUSD/` | `2026-01-01.csv` | `2026-10-07.csv` | 216 |
| EURUSD | `/opt/tradingbot/data/candles/EURUSD/` | `2026-03-30.csv` | `2026-10-07.csv` | 158 |

Candle schema: `timestamp, open, high, low, close`, 5-minute bars, timestamps in UTC, prices quoted in pip-tenths (e.g. `13471.50` = 1.34715; one pip = `1.0` in these units).

Spec would have required: every UK and US release across tiers BIG / MIDDLE / SMALL per `news_tier_classifier.classify_news_tier`, forecast/previous/actual via Finnhub (`news_calendar.get_todays_events` / `te_calendar`), surprise direction for GBPUSD via `news_strategy.GOOD_FOR_CURRENCY`, control groups `IN_LINE` (actual == forecast) and `NO_VALUES` (no numeric actual or forecast), rest + break via the existing consolidation primitive in `news_continuation.py`, continued observation after COUNTER break until ALIGNED break or 21:00 UTC, MFE/MAE at 30 / 60 / 120 min and to 21:00 UTC minus a 1.0-pip spread.

---

## Why the primitive is not callable standalone

### B1. There is no separate "consolidation primitive" function

`news_continuation.py` has 17 top-level functions. None of them is a reusable rest/break detector. All of the consolidation accumulation, invalidation, and break logic lives inline inside **`on_bar_close`** (`news_continuation.py:707-1046`), interleaved with arming, direction-lock, calendar lookup, FIRE-side geometry (`compute_initial_sl` / `compute_initial_tp`), live-position collision guard, and sticky FIRE-key dedup.

The research spec calls for `(rest, break)` extraction on arbitrary input bars; the module exports only a bar-by-bar entrypoint that drives a sticky state machine toward a trade decision. The two are not the same shape.

### B2. Whitelist filter excludes the required scope

`on_bar_close` only arms on events that pass `matches_whitelist()` (`news_continuation.py:262-272`), which checks substring membership in `NEWS_CONT_EVENT_WHITELIST` — currently `PAYROLLS,FOMC,INTEREST RATE DECISION,CORE INFLATION RATE` (`.env:700`). The call site is `_qualifying_release_for_bar` at `news_continuation.py:306`:

```python
if impact != "high":
    continue
if ccy not in ccys:
    continue
if not matches_whitelist(name):
    continue
```

The spec requires **BIG / MIDDLE / SMALL** across all UK and US releases. The primitive drops MIDDLE and SMALL at `impact != "high"`, drops every HIGH that is not NFP / FOMC / Rate decision / CPI at the whitelist line, and arms on only ~4–6 release types.

### B3. Calendar lookup is today-only and feed-coupled

`_qualifying_release_for_bar` (`news_continuation.py:274-321`) calls `news_calendar.get_todays_events()` (`news_calendar.py:359`). That returns the in-memory events populated by `_refresh_if_needed()` from the Finnhub cache for the current date only. There is no public hook to inject historical events for a different date. Replaying 2026-01-01 → 2026-10-07 would require either (a) swapping the `news_calendar` module's internal state per date and re-importing, or (b) monkey-patching `_qualifying_release_for_bar`. Both are patches around the primitive, not calls into it.

### B4. FIRE-and-terminate semantics forbid continued observation

After the first qualifying bar closes beyond the prior CONS extreme, the primitive sets `st.fired = True`, adds the release to `_fired_release_keys` (`news_continuation.py:1004`), and all subsequent `on_bar_close` calls for the pair short-circuit at line 833:

```python
if st is None or st.fired or st.stand_down:
    return None
```

The spec requires: **"After a COUNTER break, keep observing: the next rest (same primitive) and its break, until an ALIGNED break occurs or 21:00 UTC."** The primitive has no state transition that re-arms for a second rest+break after a FIRE. Reaching a second break for the same release would require manually clearing `st.fired`, resetting `st.consol_bar_count`, `st.consol_bar_indices`, `st.consol_high`, `st.consol_low`, and re-establishing a new spike-lock anchor — a sequence of writes that constructs a new in-primitive state the module itself does not emit. That is reimplementation under the primitive's name, not a call.

### B5. Rest reference ≠ "the spike extreme"

The spec paraphrases the rest as "three completed 5M candles not extending the spike extreme". The actual primitive qualifies a CONS bar on `low > pre_release_ref` (UP) / `high < pre_release_ref` (DOWN), where `pre_release_ref` is `max(preN_high, release_bar_mid)` for UP or `min(preN_low, release_bar_mid)` for DOWN (`news_continuation.py:830-842`, `_prebars_lookback()` defaults to the last 12 pre-release 5m bars). `pre_release_ref` is **not** the spike extreme (`st.spike_extreme_at_lock`); it sits well inside the spike. A spike-extreme-based rest and a pre-release-reference-based rest produce different qualifying-bar sets and therefore different break candles. Delivering results labelled "rest = spike-extreme hold" while the primitive measures hold-vs-pre-release-reference would be a reporting error.

### B6. Collision guard assumes a live-position queryable broker

`_news_position_open_anywhere()` at `news_continuation.py:674-706` consults live state and will DECLINE a FIRE if any news-tagged position is open across the pair set (`news_continuation.py:987-1001`). In research mode this must be stubbed; in a true "call the primitive" execution it is load-bearing.

---

## What would be required to run this study by calling existing code

Three surgical options exist. All three change code or require patches that go beyond calling an existing standalone function; the operator's standing instruction forbids writing a lookalike without consent.

1. **Factor out a pure helper.** Add `is_qualifying_cons_bar(bar, direction, pre_release_ref) -> bool` and `prior_cons_extreme(cons_bars, direction) -> float` to `news_continuation.py`, rewrite `on_bar_close:830-855` to call them, then import and use them from a research driver. Keeps production semantics identical by construction (passes existing tests). Does not resolve blockers B2, B3, B4, B5 of the spec by itself; the research driver would still need to run the arming/direction-lock/invalidation sequence against synthesised events.

2. **Replay driver with monkey-patch surface.** Patch `news_continuation.matches_whitelist` → `lambda _: True`, `news_continuation._qualifying_release_for_bar` → injected event, `news_continuation._news_position_open_anywhere` → `False`, clear `_state_by_pair` and `_fired_release_keys` per release. Drive bars through `on_bar_close`. For the "continue after COUNTER break" leg, after FIRE forcibly reset `st.fired` / `st.consol_*` and continue — this step **re-enters a state the primitive never produces** and so is not "calling the primitive" in the operator's sense.

3. **Build a research-only replica next to the primitive, with a parity test** that feeds identical bars + release to both and asserts the same cons-bar indices and first-break ts/close across a sampled fixture set. This is explicitly the "lookalike" the operator's instruction forbids without consent.

---

## Also noted during scoping (no data produced)

- `news_tier_classifier.classify_news_tier` (`news_tier_classifier.py:483`) is callable standalone with a plain event dict and returns `{tier, matched_rule, deviation, under_new_rules, ...}`. Verified on today's FOMC Minutes row during the prior report. No blocker for the tier axis of the spec.
- `news_strategy.GOOD_FOR_CURRENCY` (`news_strategy.py:351-401`) is a plain dict mapping event-name substrings to `("POSITIVE"|"INVERSE", pattern)`. Callable standalone. The surprise-direction label (ALIGNED / COUNTER) can be computed from `(actual, forecast)` + GOOD_FOR_CURRENCY + the pair-currency legs in `_PAIR_CCYS`. No blocker for the surprise axis of the spec.
- `news_calendar.get_todays_events()` returns only today's events. Historical calendar access across the full candle period is not exposed; the Finnhub cache files `/opt/tradingbot/cache/news_state_finnhub_<YYYY-MM-DD>.json` exist on disk but there is no public reader that returns events for a specified historical date.
- `fewer-permission-prompts` note: `.env` was modified earlier in this session (operator-directed, backup written to `.env.pre-newscontleg.20261007T112800Z`). This report is pure-read research; no .env, no services, no live state were touched to produce it.

---

## Nothing to merge; no commit downstream of this file

The research would have produced a per-release row table at the end of this document. Because the primitive is not callable within the operator's constraints, that table is not populated. No simulated / lookalike numbers are reported anywhere in this file.

End of report.
