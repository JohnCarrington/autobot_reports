# AutoBot July-2026 Recovery — Provenance

**Package build date:** 2026-09-30
**Recovery mode:** READ-ONLY forensic reconstruction. No broker orders, no historical price REST, no service starts.
**Destination:** [autobot_reports](https://github.com/JohnCarrington/autobot_reports) on branch `recovery/autobot-july2026`.

---

## 1. Pinned deployment

| Layer | Value | Source of truth |
|---|---|---|
| Code SHA | **`fcda554`** — `docs(env): flip BB_BOUNCE_LEVEL_GATE_MODE back to shadow` (2026-07-29 15:15:39 +0000) | `git log --until="2026-07-31 23:59:59" -1` in `/opt/tradingbot/` |
| Configuration | **`.env.bak`** (mtime 2026-07-01 18:50:32 UTC, 51,782 bytes) → sanitized as `.env.example` (14 secret keys redacted) | Only surviving July env variant on disk |
| System-installed unit | `/etc/systemd/system/autobot.service` — copied to `deploy/systemd/autobot.service.system-installed` for provenance | Present at build time; unchanged since 2026-02-16 (`stat` mtime) |
| Python | 3.10+ (compatible with `pydantic>=2.0,<3.0`, `pandas==2.1.4`, `numpy==1.26.4`) | `requirements.txt` at SHA fcda554 |

### Why SHA `fcda554`

The mainline moved through **177 commits** between `2026-06-25` and `2026-08-05`. Within July 2026 there is no restart telemetry that maps each commit to a running deployment (§4 of `autobot_early_july_golden_period_reconstruction_20260926.md`). Two candidate pins were considered:

| Candidate | Reason for | Reason against |
|---|---|---|
| `147498b` — `2026-07-01 16:34 UTC` | Aligned with the mtime of `.env.bak` (only surviving July env) | The bot fired essentially **zero trades** between 2026-07-01 and 2026-07-21 (§10 of the golden-period report). Pinning to this SHA delivers a package that has never been observed to trade. |
| **`fcda554` — `2026-07-29 15:15 UTC`** ✔ | (a) It is the **last** commit landing in July 2026. (b) No commits landed between fcda554 and 2026-08-11 — so this SHA is the frozen code state during Jul 30 and Jul 31 activity and stays live for a further ~12 days. (c) All EOD metrics files that survive (`reports/eod/metrics_2026-07-27.json` … `metrics_2026-07-31.json`) were produced under a stack that ended at this SHA. | Jul 27 activity landed under a slightly earlier tip (`a331046` .. `d54080d`); Jul 28 activity under `3ab53df` .. `8a0f192`. The intra-day tips-of-tree are close subsets of `fcda554` — no strategy-file rewrites separate them from `fcda554` (verified by `git log --oneline fcda554..8a0f192 -- gbpusd_bb_bounce.py gbpusd_trend_v3.py gbpusd_structure_break.py briefing_execution.py briefing/v5_pia/`). |

Chosen pin is `fcda554`. It is the best single SHA that (a) has all July strategy modules present, (b) is frozen for the tail of the profitable window, and (c) covers the recorded end-of-July P&L close-out.

### Multi-version disclosure

Because 177 commits landed in the ±5-week window, and because the July trading window (2026-07-22 → 2026-07-31) traversed several intra-day tips, this package cannot claim that the exact code state at the moment of every recorded fire matches `fcda554`. The trading window was, mechanically, a **composite deployment**. Per the brief, the *best-supported reproducible single version* is packaged here; the alternate tips (`d54080d`, `8a0f192`, and `147498b`) are named above so any future reviewer can bisect if needed. `.env.bak` is invariant across the whole window (no `.env`-modifying commit landed 2026-07-01..2026-07-21, §4 of the golden-period report; nor 2026-07-22..2026-07-29 per `git log --since="2026-07-22" --until="2026-07-30" -- .env .env.example .env.sample`).

---

## 2. Confirmed vs inferred vs unavailable configuration

Sources: (a) `.env.bak` mtime 2026-07-01 18:50 UTC — the only July env variant on disk; (b) `git log` on `/opt/tradingbot/` for the window; (c) `logs/*.jsonl` and `reports/eod/*.json` survivors; (d) the prior `autobot_early_july_golden_period_reconstruction_20260926.md`.

### CONFIRMED (direct primary evidence)

| Item | Value | Evidence |
|---|---|---|
| Code SHA range spanning July | 147498b (Jul 1) → fcda554 (Jul 29); frozen fcda554 through Jul 31 | `git log --since=2026-07-01 --until=2026-07-31` |
| No `.env`-modifying commit in the July window | true | `git log --since=2026-07-01 --until=2026-07-31 -- .env .env.example .env.sample` returns empty |
| No `deploy/systemd/*.service`-modifying commit in the July window | true — one auth commit `db08493` on Jul 10 touches auth code, not service files | same `git log` scope |
| `HTF_AUTHORITY_ENABLED=1` at start of window | line 745 of `.env.bak` | verbatim |
| `HTF_REGIME_ENABLED=1` at start of window | line 743 of `.env.bak` | verbatim |
| `NEWS_TICK_ENABLED=0` at start of window | line 307 of `.env.bak` | verbatim |
| `NEWS_STRATEGY_ENABLED=1` at start of window | line 165 of `.env.bak` | verbatim |
| `NEWS_STRATEGY_HIGH_IMPACT_ARM_ENABLED=0` | line 166 of `.env.bak` | verbatim |
| `BRIEFING_EXECUTION_ENABLED=0` | line 197 of `.env.bak` | verbatim; the box that ran this .env was NOT the briefing-execution box |
| `GBPUSD_BB_BOUNCE_ENABLED=1` | line 228 of `.env.bak` | verbatim |
| `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false` | line 687 of `.env.bak` | verbatim; consistent with the `[BB_BOUNCE gates deliberately disabled](../..)` memory |
| `BB_BOUNCE_CASCADE_GATE_ENABLED=0` | line 672 of `.env.bak` | verbatim; same memory |
| `EMA_PULLBACK_ENABLED=0` | line 291 of `.env.bak` | verbatim |
| `TREND_V3_ENABLED=1` | line 21 of `.env.bak` | verbatim |
| `SESSION_WINDOWS_JSON` — GBPUSD 06:45–21:00, EURUSD 06:45–17:00 | line 36 of `.env.bak` | verbatim |
| Concurrent-position cap — GBPUSD 8 max / 5 per direction | lines 574-577 of `.env.bak` | verbatim |
| July settled briefing trades | 15 unique deal_ids (Jul 23–31 inclusive) | `reports-public/2026-09-30_briefing_actual_pnl_3months/trades.csv` |
| July briefing settled £ | +£13.35 (7W/8L, PF 1.07) | `reports-public/2026-09-30_briefing_actual_pnl_3months/summary.json` |
| Top-2 July £ days | 2026-07-28 (+£36.10), 2026-07-27 (+£32.60) | same source |
| Worst July day | 2026-07-31 (−£30.60, 1W/4L over 5 fires) | same source |
| July EOD-reconciled fills (Jul 27–31) | 33 fills, 20W/13L, +28.47 net pips, +18.10 £ | `reports/eod/metrics_2026-07-27.json` … `metrics_2026-07-31.json`, aggregated |
| Trade size at open (early July → 2026-07-28+) | 1.0 → 2.0 | `daily_journal.pnl.trade_size_used`, quoted in briefing_actual_pnl report |

### STRONGLY INFERRED (multi-source triangulation)

- **`.env` values remained as of `.env.bak` for the whole July window.** No `.env`-modifying commit landed, no other July `.env.*` variant exists on disk, and the env-history FIFO's oldest snapshot is 2026-09-21 (too late to catch July mutation). If a manual `.env` edit occurred it left no artefact.
- **Strategy family enable-flags stayed as of `.env.bak`.** Same reasoning.
- **The bot was awake and processing candidates in early July but not firing.** `bb_bounce_standdown.jsonl` shows 75 July standdown rows (candidates seen, standdown taken) but not a corresponding fire log — consistent with an upstream filter stack (HTF authority + arm gates off + briefing-off-on-this-box) rather than a dead process.

### UNAVAILABLE (evidence gap)

| Missing artefact | Impact |
|---|---|
| `logs/htf_authority.jsonl-2026-07-*` | Cannot count HTF block/pass events for July |
| `logs/htf_regime.jsonl-2026-07-*` | Cannot enumerate regime labels |
| `logs/signal_log.jsonl` rows for July | Cannot enumerate candidates at the pre-HTF stage |
| `logs/news_strategy_evals.jsonl-2026-07-*` | Cannot audit news-family decisions |
| Systemd journal for July | Cannot recover restart timestamps, live-env values, or crash traces |
| `env-history/` FIFO before 2026-09-21 | Cannot detect intra-window env changes |
| `reports/eod/metrics_2026-07-{01..26}.json` | 21 daily reconciliations missing; only Jul 27-31 EOD JSON survive |
| Broker settlement statements | Cash figures are bot-derived (`pnl_pips × trade_size`); IG cash flow could differ by spread and overnight funding |

These gaps are cited so that a downstream reviewer knows exactly which claims are unverifiable — not filled in by inference.

---

## 3. Contents of this package

```
autobot_july_2026/
├── PROVENANCE.md                       # this file
├── RECOVERY_README.md                  # how to stand this up
├── .env.example                        # sanitized from .env.bak (14 keys → REPLACE_ME)
├── src/                                # 337 files: production code at SHA fcda554
│   ├── autobot.py                      # main entry point
│   ├── requirements.txt                # pinned top-level deps
│   ├── requirements.lock               # full transitive pin
│   ├── briefing_execution.py           # BRIEFING_EXECUTION strategy
│   ├── briefing/v5_pia/executor.py     # BRIEFING_V5 strategy
│   ├── gbpusd_bb_bounce.py             # BB_BOUNCE_L/_S strategy
│   ├── gbpusd_trend_v3.py              # TREND_V3_L/_S strategy
│   ├── gbpusd_structure_break.py       # STRUCTURE_BREAK_L strategy
│   ├── gbpusd_confirmation_fallback.py # CONFIRMATION_FALLBACK_S strategy
│   ├── htf_authority.py                # HTF authority veto engine
│   ├── htf_regime.py                   # HTF regime classifier
│   ├── news_tick_strategy.py           # PREFLIGHT + reversal engine (gated OFF by env)
│   ├── news_strategy.py                # NEWS_STRATEGY family
│   └── ... 325 more                    #
├── deploy/                             # 18 files: systemd units + drop-ins + dashboard html
│   └── systemd/
│       ├── autobot.service.system-installed   # base unit copied from /etc/systemd/system/
│       ├── autobot.service.d-auth-suspension-guard.conf
│       ├── autobot.service.d-shutdown-tuning.conf
│       ├── autobot.service.d-env-history.conf
│       ├── autobot-start.service, autobot-stop.service
│       ├── autobot-start.timer,   autobot-stop.timer
│       ├── fires-watchdog.service, .timer
│       ├── forensic-backfill.service, .timer
│       └── refresh-news-calendar.service, .timer
├── tests/                              # 122 files: full test suite at SHA fcda554
│   ├── conftest.py                     # top-level pytest configuration
│   └── unit/                           # 60+ unit tests
└── recovery_provenance/                # this package's forensic artefacts
    ├── july_daily_pnl.md               # daily P&L table (all sources reconciled)
    ├── july_daily_pnl.csv              # machine-readable form
    ├── fidelity_at_fcda554.md          # fidelity verification for every recorded strategy label
    ├── missing_evidence.md             # explicit inventory of what could not be recovered
    ├── briefing_outcomes_2026-07.csv   # verbatim copy — the settled ledger
    └── eod_metrics_jul27_31/           # verbatim copy of the 5 EOD JSON files
```

---

## 4. What this package is NOT

- **NOT a live-deployable image.** `.env.example` has `REPLACE_ME` in every credential slot; the operator must inject IG / Telegram / Anthropic / Finnhub / SendGrid keys locally and the file must never be committed to git.
- **NOT a signal replay.** No historical-tick replay is included; the package is code + config for a fresh rebuild. A replay harness against the archived candle CSVs (`data/candles/GBPUSD/2026-07-*.csv` on the source host) is the recommended fidelity next step but is out of scope of this brief.
- **NOT a broker-statement reconciliation.** The £ figures in `recovery_provenance/july_daily_pnl.md` are bot-derived (`pnl_pips × trade_size` at close); real IG cash flow will differ by spread already inside `pnl_pips`, overnight funding for any weekend-carrying trade, and commission (nil on FX at IG).
- **NOT a parameter-tuned version.** No env flag was tuned to match the profitable trades; every value in `.env.example` is the direct sanitization of `.env.bak`.

---

## 5. What "profitable July" actually looked like

The operator's request implies a distinct pre-existing profitable July version. The evidence base does not support that framing:

| Sub-window | Trades | Settled £ | Notes |
|---|---:|---:|---|
| 2026-07-01 → 2026-07-21 | **0–2** across every ledger | ≈ £0 | Bot awake, standing down (`bb_bounce_standdown.jsonl` = 75 rows) |
| 2026-07-22 → 2026-07-26 | 1 sweep + 7 briefing | +£20.70 briefing | ECB decision on Jul 23 |
| 2026-07-27 → 2026-07-28 | 4 briefing + 16 EOD-recorded fills (Jul 27–28 EOD JSON: +£10.5) | **+£68.70 briefing top-2** | Best 2-day window |
| 2026-07-29 → 2026-07-31 | 6 briefing + 17 EOD-recorded fills | **−£59.20 briefing** | Includes Jul 31 −£30.60 (1W/4L, 5 fires) |
| **July whole month** | 15 briefing + 33 EOD-recorded fills | **+£13.35 briefing + £18.10 EOD** | PF 1.07 briefing; PF ≈ 1.34 EOD |

Interpretation: **the "profitable July" is a nine-day-window phenomenon (Jul 22–31), dominated by Jul 27 and Jul 28, offset heavily by Jul 31**. The package recovered here is the code+config that was live during that nine-day window. It is not a distinct version — it is the mainline as of the last July commit.

---

## 6. Reproduction discipline

1. This provenance file, `RECOVERY_README.md`, `.env.example`, `src/`, `deploy/`, `tests/`, and `recovery_provenance/` are the complete deliverable.
2. Credentials are NEVER committed to `autobot_reports`. `REPLACE_ME` markers in `.env.example` MUST be filled from the destination host's key vault.
3. `.gitignore` in this recovery subtree will exclude any file named `.env`, `.env.local`, `.env.production`, or `*.env.bak*` so no operator-side secrets leak on a subsequent commit.
4. The package must not be started against a live IG account without operator explicit approval; per the brief, "Do not deploy or activate it yet."

## 7. Modifications to code-at-SHA for sanitization

For the package to be safely publishable, the following documentation-only redactions were applied to the code at SHA `fcda554` before commit. **No behavioural code path is changed.** Any downstream consumer that wants byte-identical source can re-fetch from the upstream repo at SHA `fcda554`.

| File | Original string | Replaced with | Nature |
|---|---|---|---|
| `src/autobot.py` (comment) | `Z3G4CJ` (live IG account ID) | `REDACTED_IG_ACCT` | Comment |
| `src/rest_allowance.py` (comment) | `Z3G4CJ` | `REDACTED_IG_ACCT` | Comment |
| `tests/unit/test_rest_allowance_ig_capture.py` (docstring) | `Z3G4CJ` | `REDACTED_IG_ACCT` | Docstring |
| `src/docs/RUNBOOK.md` (prose) | `mrjohnnyb` (live IG username) | `REDACTED_IG_USERNAME` | Runbook prose |

These 4 files differ from upstream `fcda554` by exactly one string per file. The strategy engines, gate stacks, HTF authority, briefing executors, and every fire path are unchanged.
