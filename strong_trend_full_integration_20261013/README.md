# NMS inputs completion + wrong-direction + news investigation

**Baseline:** AutoBot `f90ffd2` → this change `6bc768e`.
**BB-Bounce dev:** `da1babd` (unchanged; snapshot shape backward-compat).
**Status:** DEVELOPMENT. No deployment, no merges, no services
touched, no `.env` edited, no IG orders.

Four-part review.

---

## PART A — Wiring the IG daily-% + pivot bridges (COMPLETED)

### A.1-A.2 — Changes committed in `6bc768e`

New module `session_trend_integration.py` with two bridges:

| Bridge | What it does | Reads | Writes |
|---|---|---|---|
| `bridge_pivots_to_session_trend` | Transfers today's authoritative pivot payload into session_trend's state | `ig_daily_pivots.read_pivots(today)` → `pairs.GBPUSD.pivots_ask` | `session_trend.set_daily_pivots` + `pivot_source_date` |
| `bridge_ig_daily_pct_to_session_trend` | Fetches daily-% from `/markets/{epic}` and stamps the state | `IGService.fetch_market_by_epic` (via `session_ig_daily_pct.fetch_and_record`) | `session_trend.set_ig_daily_pct` |

Wired into `autobot.py`:

- **Boot-time** (`autobot.py:10534-10547`) — after
  `ig_daily_pivots.startup_catch_up`, call both bridges once with
  the live, already-authenticated IGService. **No new POST /session.**
- **Heartbeat loop** (`autobot.py:9740-9759`) — after
  `ig_daily_pivots.maybe_run_scheduled`, refresh pivots every tick
  (bridge is idempotent — no-op when payload is for a prior
  trading_date). Refresh daily-% in the first 5 min of each hour.

### A.3 — Population + freshness guarantees

**Pivots:**
- Source: `/opt/tradingbot/cache/htf/daily_pivots.json` written by
  `ig_daily_pivots.run_daily_fetch()` (classic-floor computed from the
  ASK side of IG's own D-1 bar; keyed by `trading_date`).
- Freshness: `ig_daily_pivots.read_pivots(trading_date)` compares the
  file's `trading_date` to today's UTC date. Mismatch → returns None.
  The bridge receives None and is a no-op; `session_trend.daily_pivots`
  retains its last known value.
- Provenance: `session_trend.pivot_source_date` is set to the trading
  date (not the ISO file timestamp). Surfaces in snapshot JSON.

**IG daily-%:**
- Source: `GET /markets/{epic}` → `snapshot.percentageChange`.
- Freshness: IG resets percentageChange at 00:00 London local time
  (23:00 UTC during BST; 00:00 UTC during GMT). The bridge records
  `ig_daily_pct_as_of` (ISO-UTC wall-clock of the fetch), so a
  downstream consumer can detect staleness.
- Refresh cadence: once per hour (minutes 0-4) in production.

### A.4 — Stale/unavailable inputs cannot mislead

**Zero behaviour change on classification** regardless of bridge
state. Both inputs populate SUPPORTING EVIDENCE fields that surface
in reason strings and snapshots but are **not gates** in the state
machine. The 34-day replay produces identical results before and
after wiring:

```
                            baseline (f90ffd2)    post-wiring (6bc768e)
VALID_FIRE                  16                    16
WRONG_DIRECTION             5                     5
MISSED_INTRADAY             9                     9
CORRECT_QUIET               4                     4
Oct 12 first DOWN           09:50 UTC             09:50 UTC
Oct 12 pinned BUYs blocked  4/4                   4/4
```

Fail-safe matrix (unit tests):

| Scenario | Pivot bridge | Daily-% bridge |
|---|---|---|
| Payload / snapshot present and today | populate ✓ | populate ✓ |
| Payload stale (prior `trading_date`) | no-op ✓ | — |
| File missing | no-op ✓ | — |
| Payload malformed | no-op ✓ | no-op ✓ |
| No IG session passed | — | no-op ✓ |
| IG returns null `percentageChange` | — | no-op ✓ |
| Bridge raises | caught + logged DEBUG | caught + logged DEBUG |

### A.5 — End-to-end data flow to BB-Bounce guard

**Verified by test:**

```
tests/data_continuity/test_session_trend_integration.py
  test_end_to_end_bridges_through_snapshot — PASSED

  bridges called → state populated → on_bar_close triggers
  _write_snapshot → snapshot JSON on disk includes:
    daily_pivots.R3 = 13321.57
    daily_pivots.S3 = 13172.17
    pivot_source_date = "2026-10-12"
    ig_daily_pct_change = -0.21
    ig_daily_pct_as_of = ISO-UTC timestamp
```

BB-Bounce guard integration unchanged:

```
tests/test_session_trend_guard_integration.py  — 10 passed
```

The guard reads `prevailing` only. Supporting fields are
informational (future dashboards can consume them). No permission
logic change.

### A.6 — Test runs

```
cd /home/autobot/tradingbot-wt/nms-continuity-20261012
python -m pytest tests/data_continuity/

102 passed in 5.07s

cd /home/autobot/bb-bounce-wt/session-trend-20261013
python -m pytest tests/test_session_trend_guard_integration.py

10 passed in 0.16s
```

9 new integration tests (pivot bridge, daily-% bridge, end-to-end
snapshot) pass.

---

## PART B — 5 wrong-direction case studies

For each date, chronological evidence at fire moment, time since
London open, release moment, and whether restrictions persisted.

### Operator framing

> "Do not classify an earlier decision as wrong solely because
> price moved the other way later."

Under this framing, a fire that captures a legitimate first-leg
structure is **not** wrong. The question is whether the restriction
was retained after the trend ceased.

### Summary

| Date | Fire | Fire direction | Minutes since London | Release | Elapsed | Final state |
|---|---|---|---|---|---|---|
| 09-02 | 10:40 UTC | DOWN | 220 min | 13:55 UTC (+20.7p reclaim ×2 bars) | 3h15m | RANGE |
| 09-08 | 08:55 UTC | DOWN | 115 min | 12:20 UTC (+10.1p reclaim ×2 bars) | 3h25m | UNKNOWN |
| 10-02 | 12:10 UTC | DOWN | 310 min | 12:35 UTC (+22.8p reclaim ×2 bars) | **25 min** | RANGE |
| 10-05 | 08:20 UTC | UP | 80 min | 13:15 UTC (−11.3p reclaim ×2 bars) | 4h55m | RANGE |
| 10-09 | 08:25 UTC | UP | 85 min | 12:10 UTC (−14.6p reclaim ×2 bars) | 3h45m | UNKNOWN |

**All 5 released before EOD.** None retained the restriction after
the trend ceased. The release path functioned correctly in every
case.

### Per-day verdict

#### 2026-09-02 — DOWN at 10:40 UTC
Evidence: `sr=[dn=5,up=3,asym=+2] pb=[dn=1,up=0] rev=1 cpos=0.01 disp=−13.3p`.
Clean asymmetric DOWN structure with close at session low. 220 min
of structure accumulation.
**Fire justified at that moment.** Day's intraday peak hit +20.7p
UP later (just at the 20p threshold). Release fired 3h15m later
when disp crossed +20.7p for 2 bars.

#### 2026-09-08 — DOWN at 08:55 UTC
Evidence: `sr=[dn=3,up=1,asym=+2] pb=[dn=2,up=0] rev=0 cpos=0.18 disp=−11.0p`.
Clean morning DOWN picture.
**Fire justified at that moment.** Day eventually reversed. Release
fired after 3h25m when disp reclaimed +10.1p.

#### 2026-10-02 — DOWN at 12:10 UTC — **news-driven reversal**
Evidence: `sr=[dn=5,up=2,asym=+3] pb=[dn=5,up=2] rev=1 cpos=0.02 disp=−13.7p`.
Very strong asymmetric DOWN with 5 pullback-and-continue events,
close at session low. 310 min of structure accumulation.
**Fire extremely strong by every structural metric.**
**20 minutes later, 12:30 UTC NFP release caused a 36.3-pip range
bar** (vs typical 5-10p) — the single-event reversal. Release
fired just one bar later (12:35) when disp reclaimed +22.8p. See
Part D for news anatomy.

#### 2026-10-05 — UP at 08:20 UTC — early morning
Evidence: `sr=[up=3,dn=1,asym=+2] pb=[up=2,dn=1] rev=1 cpos=0.94 disp=+14.9p piv_support=11`.
UP at session high, 80 min after London open. Fast fire.
Note `pb_dn=1` — one DOWN pullback already present.
**Fire marginally justified**: asymmetry is minimum (+2), with 1
opposing pullback. Day eventually went to −25p DOWN. Release fired
after 4h55m. Longest "wrong-direction" window of the 5.

#### 2026-10-09 — UP at 08:25 UTC — early morning
Evidence: `sr=[up=4,dn=1,asym=+3] pb=[up=2,dn=0] rev=0 cpos=0.82 disp=+10.4p`.
Clean asymmetric UP picture, 85 min after London open.
**Fire justified at that moment.** Day eventually went to −28p DOWN.
Release fired after 3h45m.

### Pattern

- 3 of 5 fires (10-02, 10-05, 10-09) occurred within the first 1h30m
  of London session or very late (post-5h). The intermediate
  09-02/09-08 fired at 115-220 min — normal.
- 10-05 and 10-09 fired early-session UP at session high. The
  minimum asymmetry gate (+2) was satisfied, but subsequent action
  showed the morning UP was a false start.
- 10-02 is the only clearly news-driven case (see Part D).

### Affected BB-Bounce signals

The BB-Bounce production journal (`/opt/bb_bounce/reports/*.csv`)
only exists from 2026-10-12 onward. For Sep-Oct dates before
10-12 the historical journal does not exist, so direct trade
impact can't be computed. The guard logic is:

- 09-02 DOWN window (10:40 → 13:55): BUY entries would have been
  blocked, SELL allowed. ~3h15m.
- 09-08 DOWN window (08:55 → 12:20): same shape, 3h25m.
- 10-02 DOWN window (12:10 → 12:35): 25 min. Minimal exposure.
- 10-05 UP window (08:20 → 13:15): SELL entries blocked, BUY
  allowed. 4h55m — the longest window.
- 10-09 UP window (08:25 → 12:10): 3h45m.

Under the operator's framing none of these are a "wrong decision"
— each window captured a legitimate first-leg structure. The
BB-Bounce entries blocked during these windows would have been
*counter* to the then-prevailing structural evidence; the release
path cleared the restriction once the structure genuinely broke.

---

## PART C — 34-day validation + Oct 12

### Full scorecard (intraday-dominant truth: peak |disp| ≥ 20p)

| Category | Count |
|---|---|
| VALID_FIRE | **16** |
| WRONG_DIRECTION (final-state label) | **5** |
| MISSED_INTRADAY | **9** |
| CORRECT_QUIET | **4** |
| Total | 34 |

### Recognition timestamps for VALID_FIRE days

London times are UTC. BST applies through Sun 2026-10-25.

| Date | ST fire | Direction | Minutes after London open |
|---|---|---|---|
| 09-01 | 16:35 UTC | DOWN | +575 |
| 09-04 | 09:55 UTC | DOWN | +175 |
| 09-07 | 08:35 UTC | UP | +95 |
| 09-09 | 08:25 UTC | DOWN | +85 |
| 09-10 | 11:10 UTC | DOWN | +250 |
| 09-11 | 08:10 UTC | DOWN | +70 |
| 09-16 | 16:40 UTC | DOWN | +580 |
| 09-18 | 10:45 UTC | DOWN | +225 |
| 09-23 | 09:45 UTC | DOWN | +165 |
| 09-24 | 09:55 UTC | DOWN | +175 |
| 09-25 | 08:50 UTC | UP | +110 |
| 09-28 | 13:50 UTC | UP | +410 |
| 10-01 | 08:40 UTC | DOWN | +100 |
| 10-06 | 07:55 UTC | UP | +55 |
| 10-07 | 08:10 UTC | DOWN | +70 |
| **10-12** | **09:50 UTC** | **DOWN** | **+170** |

### 2026-10-12 regression

```
First DOWN establishment: 2026-10-12T09:50:00+00:00
intraday_truth:           DOWN (min_disp = −42.6p)
final state (EOD):        DOWN
pinned trade decisions:
    08:10 SELL  → allow
    09:35 BUY   → allow
    10:20 BUY   → block:established_down   ✓
    11:18 BUY   → block:established_down   ✓
    12:20 SELL  → allow
    14:10 BUY   → block:established_down   ✓
    15:25 SELL  → allow
    16:10 BUY   → block:established_down   ✓

tests/data_continuity/test_phase8_oct12_regression.py — PASSED
```

### Missed strong trends (9 days)

Lost protection opportunities. No false restriction (guard allows
both BUY and SELL on these days). Pattern below for Part D.

| Date | Intraday peak | News present? |
|---|---|---|
| 09-03 | UP +55.6p | — |
| 09-14 | BOTH ±26p | — |
| 09-15 | UP +26.1p | — |
| 09-17 | DOWN −58.5p | — |
| 09-22 | DOWN −50.0p | — |
| 09-27 | DOWN −21.8p | — |
| 09-29 | DOWN −35.1p | BOC Rate Decision 13:31, JOLTs 14:00 |
| 09-30 | UP +47.9p | EU Inflation + Core PCE 12:30 |
| 10-08 | UP +53.5p | EU Balance of Trade 06:00 |

### Correctly blocked counter-trend signals

Across 16 VALID_FIRE days, the guard would block counter-direction
BB-Bounce entries throughout each day (or until release fires).
Only Oct 12 has a historical BB-Bounce journal (`/opt/bb_bounce/
reports/2026-10-12.csv`) that documents actual signals:

```
2026-10-12  — 4 of 4 pinned historical BUYs correctly blocked
            — SELLs permitted throughout the DOWN session
```

For the 15 remaining VALID_FIRE days, aligned-direction entries
would be permitted and counter-direction entries would be blocked —
exactly the design intent.

---

## PART D — News-spike investigation

### Economic releases on the 5 wrong-direction dates

Sourced from `/opt/tradingbot/logs/news_strategy_evals.jsonl*`
(records post-launch of the news strategy — Sept 2026 pre-launch
has no entries).

| Date | Release | Time (UTC) | Impact |
|---|---|---|---|
| 09-02 | — (no journal entries) | — | — |
| 09-08 | — (no journal entries) | — | — |
| **10-02** | **USD Non Farm Payrolls** | **12:30** | **high** |
| 10-02 | EUR Inflation Rate YoY Flash | 09:00 | medium |
| 10-05 | USD ISM Services PMI | 14:00 | medium |
| 10-05 | CAD BOC Interest Rate Decision | 22:40+ | after session |
| 10-09 | CAD Unemployment Rate | 12:30 | medium |
| 10-09 | USD Michigan Consumer Sentiment | 14:00 | medium |

### M5 candle anatomy

For each release, 7 bars around the event:

#### 2026-10-02 Non Farm Payrolls — 12:30 UTC

| Bar | O | H | L | C | Body | Range |
|---|---|---|---|---|---|---|
| 12:10 (fire bar) | 13201.7 | 13203.7 | 13199.2 | 13199.5 | −2.1p | 4.5p |
| 12:15 | 13199.5 | 13200.3 | 13195.8 | 13198.0 | −1.4p | 4.6p |
| 12:20 | 13197.5 | 13206.8 | 13197.5 | 13205.7 | **+8.1p** | 9.2p |
| 12:25 | 13205.5 | 13210.0 | 13201.0 | 13209.5 | +4.0p | 9.0p |
| **12:30 ← NFP** | **13209.6** | **13244.7** | **13208.4** | **13227.5** | **+17.9p** | **36.3p** |
| 12:35 | 13227.6 | 13237.5 | 13223.0 | 13236.0 | +8.4p | 14.6p |
| 12:40 | 13236.1 | 13238.0 | 13221.5 | 13222.2 | −13.9p | 16.4p |

**Classic news spike.** 36.3p range vs. typical 4-6p — a **6× ATR
expansion** on the release bar. Body +17.9p, high overshoot +35p.
This is the single-event reversal that invalidated the DOWN
structure that had accumulated over 5 hours.

The subsequent 12:40 bar has a −13.9p body — a textbook post-spike
rejection candle. Range stays elevated 10-16p for 2-3 bars then
decays to normal.

**ST fire DOWN at 12:10 was 20 min before NFP.** Release fired at
12:35 (one bar after NFP) when disp reclaimed +22.8p. The release
window was 25 min — tight.

**NEWS_IMPULSE classification candidate.** This day shows the
clearest spike-and-reversal pattern of the 5.

#### 2026-10-05 ISM Services — 14:00 UTC

| Bar | O | H | L | C | Body | Range |
|---|---|---|---|---|---|---|
| 13:45 | 13196.0 | 13197.8 | 13190.2 | 13197.2 | +1.2p | 7.7p |
| 13:55 | 13194.5 | 13199.0 | 13193.0 | 13198.5 | +4.0p | 6.0p |
| **14:00 ← ISM** | 13199.4 | 13206.5 | 13195.5 | 13203.3 | +3.9p | **11.1p** |
| 14:05 | 13203.5 | 13206.2 | 13196.8 | 13205.7 | +2.2p | 9.4p |
| 14:30 | 13203.5 | 13210.5 | 13203.2 | 13204.5 | +1.0p | 7.3p |

Mild 11.1p range at release — maybe 2× ATR, not a classic spike.
No sharp rejection candle. **The reversal happened before ISM**
(ST released at 13:15, 45 min before ISM). **Not news-driven**.

#### 2026-10-09 CAD Unemp 12:30 / Michigan 14:00 UTC

| Bar | O | H | L | C | Body | Range |
|---|---|---|---|---|---|---|
| 12:25 | 13219.0 | 13221.3 | 13218.3 | 13219.2 | +0.2p | 3.0p |
| **12:30 ← CAD Unemp** | 13219.0 | 13220.0 | 13214.2 | 13214.3 | −4.7p | 5.8p |
| 12:35 | 13214.2 | 13215.5 | 13211.2 | 13213.0 | −1.2p | 4.2p |
| ...<br>**14:00 ← Michigan** | 13226.2 | 13228.9 | 13221.5 | 13223.7 | −2.5p | 7.4p |

Neither release shows spike characteristics (5-8p ranges, no
3×ATR expansion). ST released at 12:10 — **20 min BEFORE CAD
Unemp**. Reversal was pre-news. **Not news-driven**.

#### 2026-09-02 / 2026-09-08 (no news log)

No news-strategy journal entries for either day (likely pre-launch
of the news strategy observer). I examined M5 candles at common
UK/EU/US release slots (09:30, 12:30, 14:00 UTC) for both:

| Day | Release slot | Max range in ±30min window | Spike pattern? |
|---|---|---|---|
| 09-02 | 09:30 | 5.7p | no |
| 09-02 | 12:30 | 7.3p | no |
| 09-02 | 14:00 | 9.8p | mild, not news-spike |
| 09-08 | 09:30 | 6.2p | no |
| 09-08 | 12:30 | 5.9p | no |
| 09-08 | 14:00 | 5.3p | no |

**Neither day shows news-spike signatures** in the available data.

### Missed-trend days with news

| Date | Missed direction | News | Reversal direction? |
|---|---|---|---|
| 09-29 | DOWN −35p | BOC + JOLTs 13:31-14:00 | — (no reversal; just a legitimate DOWN trend ST missed) |
| 09-30 | UP +48p | EU Inflation + Core PCE 12:30 | — (news likely drove the +48p UP; ST missed) |
| 10-08 | UP +53p | EU Balance of Trade 06:00 | — (06:00 EUR data likely drove early UP) |

**09-30 and 10-08** are likely news-driven trends that ST missed.
Had a NEWS_IMPULSE detector existed, these might have been
flagged early. But the operator asked for findings, not
implementation.

### Spike classification (operator's A/B/C taxonomy)

| Day | Pattern | Classification |
|---|---|---|
| 10-02 | Spike at NFP reversed the DOWN session | **(A) Spike and reversal** — the whole-day direction was defined by the single release |
| 09-02 | No clear spike; gradual mean reversion | None |
| 09-08 | No clear spike; secondary buying pressure | None |
| 10-05 | No spike; reversal was pre-news (slow trend) | None |
| 10-09 | No spike; reversal pre-news (slow trend) | None |

Missed-trend candidates where news **drove the trend ST missed**:
- 09-30 Core PCE 12:30 → likely a **(B) spike followed by sustained
  trend** — would be valuable to detect prospectively.
- 10-08 EUR 06:00 — pre-London data; outside session_trend's
  current observation window anyway.

### Recommended distinction (if operator supports)

**NEWS_IMPULSE** — detected after the fact as:

- Current M5 bar's range ≥ 3× the trailing 14-bar ATR
- Bar close falls within ±30 min of a scheduled high-impact release
- Return to pre-release price within ≤ 2 bars → sub-flag `NEWS_REJECTION`
- Price continues to extend past the spike for ≥ 3 bars → sub-flag `NEWS_CONTINUATION`

This is only one high-conviction case (10-02 NFP) in the 34-day
window. The reward of implementing a NEWS_IMPULSE detector is
**modest at this sample size**:

- Would improve the 10-02 case (DOWN restrictions during a day
  that was defined by NFP) — but the current release path already
  caught the reversal 5 min after NFP.
- Could help prospectively catch news-driven trends (09-30
  type) — but historical sample is thin.

**Recommendation:** defer the NEWS_IMPULSE classifier. The data
does **not strongly support** a new classifier at this sample
size. If operator wants it, start by instrumenting detection
(logging only) without any classification side-effects, then
re-evaluate after accumulating more days.

**No blanket news blackout** — not requested, not required by
data. 4 of 5 wrong-direction days have no clear news driver;
blacking them out would silence legitimate structural evidence.

---

## Summary — operator decisions

| Request | Status | Notes |
|---|---|---|
| A.1 Wire fetch_and_record | ✓ done | boot + hourly refresh |
| A.2 Wire set_daily_pivots | ✓ done | boot + heartbeat |
| A.3 Population verified | ✓ done | 9 integration tests |
| A.4 Stale-input safety | ✓ done | no-op on stale/missing/malformed |
| A.5 End-to-end BB-Bounce chain | ✓ verified | 10 guard tests pass |
| B — 5 case studies | ✓ done | 0 of 5 are "wrong decision at the moment" under operator framing; all 5 released correctly |
| C — 34-day revalidation | ✓ done | identical scorecard; Oct 12 preserved |
| D — News investigation | ✓ done | only 10-02 is clearly news-driven; NEWS_IMPULSE classifier **not recommended** at this sample size |

### Outstanding questions

1. Approve the bridge wiring on main branch for deployment?
2. Investigate the 10-05 / 10-09 early-morning fires further (both
   fired within 90 min of London open at session extreme)? Consider
   a soft "first-90-min cautious" posture?
3. Defer NEWS_IMPULSE classifier (recommended) or begin instrumentation?

STOP FOR REVIEW.
