# AutoBot July-2026 Recovery — Correction to Provenance Claims

**Report date:** 2026-09-30 (post-cutover audit of the recovery package published earlier the same day)
**Mode:** READ-ONLY forensic. No IG queries. No code changes. Recovery package unchanged and inactive.
**Scope of this document:** correct three overstated claims in the recovery-package summary, then answer one bounded provenance question with the specific evidence just recovered.

The recovery package on `autobot_reports` branch `recovery/autobot-july2026` (commit `e8eb294`) is **NOT MODIFIED**. This report supersedes the summary language only.

---

## 1. Corrections to the earlier recovery claims

### 1.1 `fcda554` + `.env.bak` (Jul 1) is a CANDIDATE reconstruction, not a verified deployment pair

The previous summary described the pair as the "pinned deployment" that was live during the July profitable window. This is overstated. The correct label is:

> **Candidate reconstruction.** SHA `fcda554` was the working-tree HEAD from 2026-07-29 15:15 UTC through 2026-08-03 08:38 UTC per `git reflog` — so it was the last-of-July code state and would have been the code executing during Jul 30 and Jul 31 fires *if the bot process restarted after each fetch*. `.env.bak` (mtime 2026-07-01 18:50 UTC) was found on disk but is **not corroborated** as the effective `.env` at any point during July (see §2.2). The pair is a defensible candidate for the Jul-30/31 tail sub-window and nothing further.

### 1.2 Dates without EOD-reconciliation are UNKNOWN, not zero/silent

The previous summary asserted "Jul 1–21 essentially silent (0–2 fires)." That was based on `sweep_journal_*.csv` and `briefing_outcomes_2026-07.csv` counts, ignoring the far more comprehensive **signal_log** captured in `backups/eod-review/`.

Correct wording:
- Jul 1–20 have **no EOD-JSON reconciliation** on disk (`reports/eod/metrics_2026-07-{01..26}.json` missing).
- Jul 1–20 **do have signal_log entries** (see §2.3): 121 fires opened, per the eod-review snapshot at 2026-07-21 EOD.
- Prior claim of "silent Jul 1–21" is **wrong**. Correct claim: **fire volume PROVEN, per-day EOD-JSON reconciliation UNKNOWN.**

### 1.3 Keep briefing-only P&L separate from whole-AutoBot P&L

These are two different scopes and must not be summed or conflated.

| scope | trades in July | P&L (July) | source |
|---|---:|---:|---|
| **Briefing-only** (GBPUSD BRIEFING_EXECUTION + BRIEFING_V5 only) | 15 unique deal_ids | **+£13.35** (7W/8L, PF 1.07) | `reports-public/2026-09-30_briefing_actual_pnl_3months/summary.json` |
| **Whole-AutoBot** (all strategies, all pairs) | 182 fires | **+611.0 pips** net | `backups/eod-review/2026-07-31/signal_log.jsonl` — this report §2.3 |

The pip figure is not directly convertible to £ without a per-trade stake schedule. Prior mixing of "briefing settled £" with "EOD-JSON pips" as if they were the same-scope figure is retracted.

---

## 2. Bounded deployment-provenance check (per operator brief)

### 2.1 Sources actually consulted (one pass, no IG)

| source | outcome |
|---|---|
| `journalctl -u autobot -S 2026-07-01 -U 2026-07-31` (as `autobot` user, member of `systemd-journal`) | **`No entries`** — journal `SystemMaxUse=200M` has rotated every pre-2026-09-30 boot out. `journalctl --list-boots` shows only one boot (2026-09-30 16:02 UTC). systemd evidence for July is **UNAVAILABLE**. |
| `git reflog /opt/tradingbot` | **RECOVERABLE.** 1,457 entries; July segment intact. HEAD movements for every commit and reset in the window. |
| `env/40-gates.env` git history | **RECOVERABLE.** 8 commits in July (dc39d87 Jul 25 → fcda554 Jul 29). |
| `env/10-infrastructure.env` git history | untouched in July. |
| `.env` git history | Not tracked in git (gitignored). Only artefact on disk is `.env.bak` mtime 2026-07-01 18:50 UTC. |
| `backups/eod-review/` | **MAJOR find.** Daily snapshot directories from **2026-07-21** onwards, each containing a copy of `signal_log.jsonl` at that day's EOD. This is a full record of executed fires and their outcomes across every strategy — the source that the earlier report missed. |
| `reports/eod/metrics_2026-07-{27..31}.json` | 5 EOD-JSON reconciliations only. Jul 1–26 EOD-JSON files never existed on disk. |

### 2.2 Q1 — Did the Jul-1 `.env.bak` remain effective when `fcda554` ran?

**Answer: NO, and the evidence is direct.**

Falsifying observations, in order of severity:

1. **EMA_PULLBACK fired 19 times between Jul 2 06:30 UTC and Jul 22 09:30 UTC** despite `.env.bak` line 291 setting `EMA_PULLBACK_ENABLED=0`. If `.env.bak` had been the effective config across the whole window, those fires would not have opened. Evidence: `signal_log.jsonl` at eod-review 2026-07-31 contains 21 rows with `strategy: GBPUSD_EMA_PULLBACK_{L,S}` and July timestamps.

2. **The memory `[EMA_PB fully OFF end-to-end]` (updated 2026-07-29)** explicitly records "master + armed ENABLED=0 + armed SHADOW=0" as taking effect on Jul 29 — i.e. the enable flag was ON before Jul 29 and set OFF on Jul 29. `.env.bak` (mtime Jul 1 18:50) already shows the flag as 0, so its state does NOT match the pre-Jul-29 running config.

3. **`env/40-gates.env` changed 8 times in July.** The last change is `fcda554` itself. Between `.env.bak`'s mtime (Jul 1 18:50) and `fcda554` running (Jul 30–31), the layered gate file was rewritten in `dc39d87` (Jul 25 NEWS_STRATEGY_MODE unified gate), `2d80aac` (Jul 25 BB_BOUNCE level-distance gate), `e704089` (Jul 25 threshold docs), `4203e89` (Jul 26 news-momentum observer), `d54080d` (Jul 27 REGIME_MAX_HOLD gate), `c60ea96` (Jul 29 BB_BOUNCE_LEVEL_GATE_MODE alignment). `.env.bak` sits before all of these — it cannot represent the `env/40-gates.env` state that was in effect while `fcda554` ran.

4. **Commit `eb5c7bd` (2026-08-03 08:38 UTC) documents in its subject line:** `"chore(news): NEWS_STRATEGY_MODE off->shadow (Monday flip, executed 2026-07-27)"` — a NEWS_STRATEGY_MODE change was applied to the layered env on Jul 27 (before `fcda554` committed on Jul 29). This is a direct textual record that the effective env-state on Jul 27–31 was NOT the Jul-1 state.

5. **`.env.bak` line 197 has `BRIEFING_EXECUTION_ENABLED=0`.** Signal_log shows **13 BRIEFING_EXECUTION fires** (Jul 23–31, 12 GBPUSD + 1 EURUSD). Either (a) that flag was `=1` in the effective `.env` during those days and `.env.bak` is an unrelated snapshot, or (b) BRIEFING_EXECUTION was reached through a different fire path that ignores that flag. Either way, `.env.bak` line 197 does not correctly predict Jul 23–31 fire behaviour.

**Interpretation.** `.env.bak` is a **backup file, not a runtime record.** Its mtime coincides with a config-editing session on Jul 1 evening (the reflog shows 4 commits landing between 18:54 and 20:35 UTC that day). It captures the *editor's clipboard state* at 18:50 UTC — which may have been a previous state being backed up before an edit, or a candidate state that was subsequently rewritten. It is **NOT** the same as the `.env` that was loaded by `systemd` on subsequent restarts. There is no artefact on disk that records the effective `.env` at any point during July.

### 2.3 Q2 — Is there a better recoverable source/config pair for the profitable period?

**Answer: NO. The month is not represented by any single (SHA, .env) pair, and no better pair is recoverable.**

Whole-AutoBot per-day P&L (net pips, all pairs, all strategies, from `backups/eod-review/2026-07-31/signal_log.jsonl` — outcome fields resolved, W/L derivable from `pnl_pips` sign):

| date | fires | net pips | notable strategies |
|---|---:|---:|---|
| 2026-07-01 | 8 | −23.1 | BB_BOUNCE_L/S, EMA_PB_S, CF_S, TREND_V3, STRUCTURE_BREAK |
| 2026-07-02 | 8 | **+96.8** | TREND_V3_L (5), EMA_PB_L (1), NEWS_STRAT_CONT (2) |
| 2026-07-03 | 7 | +42.9 | BB_BOUNCE_L/S, EMA_PB_L, STRUCTURE_BREAK_S |
| 2026-07-06 | 11 | **+62.1** | TREND_V3_L (4), BB_BOUNCE_S (2), EMA_PB_S (2), EMA_PB_L (1), SB_L (2) |
| 2026-07-07 | 8 | −0.7 | mixed |
| 2026-07-08 | 5 | +18.7 | BB_BOUNCE_L (2), TREND_V3_S (1), EMA_PB_S (1), BB_BOUNCE_S (1) |
| 2026-07-09 | 5 | +13.6 | TREND_V3_L (4), CF_L (1) |
| 2026-07-15 | 25 | **+102.8** | TREND_V3_L (13), BB_BOUNCE_S (4), BB_BOUNCE_L (2), EMA_PB_L (3), CF_L (1), SB_L (2) |
| 2026-07-16 | 5 | −58.5 | BB_BOUNCE_L (4), EMA_PB_L (1) |
| 2026-07-17 | 13 | +38.4 | BB_BOUNCE_L (3), BB_BOUNCE_S (3), CF_L (2), CF_S (1), EMA_PB_S (2), TREND_V3_S (2) |
| 2026-07-20 | 13 | +32.9 | BB_BOUNCE_L (4), BB_BOUNCE_S (2), SB_S (2), EMA_PB_L (1), TREND_V3_L (1), TREND_V3_S (3) |
| 2026-07-21 | 13 | **+138.8** | BB_BOUNCE_L (5), BB_BOUNCE_S (1), CF_L (2), EMA_PB_S (1), SB_S (2), TREND_V3_S (2) |
| 2026-07-22 | 10 | +59.8 | BB_BOUNCE_L (3), BB_BOUNCE_S (3), CF_S (1), EMA_PB_S (2), NEWS_STRAT_REV (1) |
| 2026-07-23 | 12 | −6.1 | BRIEFING_EXECUTION (2), FIFTY_PIP_BREAKOUT (3), MACD_EXTREME (3), P2_EURUSD (1), P2_USDJPY (2), RSI_FADE (1) |
| 2026-07-24 | 6 | −61.2 | BRIEFING_EXECUTION (3), FIFTY_PIP (1), STRUCT_BREAK_L (1), TREND_V3_L (1) |
| 2026-07-27 | 7 | +14.8 | BRIEFING_EXECUTION (1), BB_BOUNCE_L (3), BB_BOUNCE_S (2), CF_S (1) |
| 2026-07-28 | 9 | +37.8 | BRIEFING_EXECUTION (3), BB_BOUNCE_L (1), BB_BOUNCE_S (3), STRUCT_BREAK_L (1), TREND_V3_L (1) |
| 2026-07-29 | 1 | −14.3 | BRIEFING_V5 (1) |
| 2026-07-30 | 4 | +18.5 | BB_BOUNCE_S (1), STRUCT_BREAK_L (1), TREND_V3_L (2) |
| **2026-07-31** | **12** | **+97.2** | BRIEFING_EXECUTION (4), BRIEFING_V5 (1), BB_BOUNCE_L (2), BB_BOUNCE_S (3), CF_S (1), TREND_V3_S (1) |
| **TOTAL** | **182** | **+611.0** | 20 distinct strategy labels |

Top-5 whole-AutoBot P&L days: Jul 21 (+138.8p), Jul 15 (+102.8p), Jul 31 (+97.2p), Jul 2 (+96.8p), Jul 6 (+62.1p) — **only Jul 31 is under `fcda554`**. The other four top days ran under earlier tips whose exact commit at fire-time can be read off the reflog:

| top day | live HEAD at start of day (from reflog) | notes |
|---|---|---|
| 2026-07-02 | `316f330` "news_release_window per-event category widths" (Jul 1 22:36) | 23a9ca0/a0d81ae/e8a9b2b landed intraday Jul 2 |
| 2026-07-06 | `bfe1ac7` "v5_pia gate unconsumed Anthropic rationale" (Jul 5 22:35) | Jul 6 intraday: faf109e, 383c599 |
| 2026-07-15 | `81cab0c` "REVERSAL_WATCH min-delay floor" (Jul 14 22:16) | Jul 15 intraday: ca20dd3, 0f5b488, e3d1161, 96da119, 6c52577 |
| 2026-07-21 | `ea509bd` "ema_pullback hard-gate armed machine" (Jul 20 21:57) | Jul 21 intraday: a7e2892, a59b4da, c0d34cc, e6bfbd1 |
| 2026-07-31 | `fcda554` "flip BB_BOUNCE_LEVEL_GATE_MODE back to shadow" (Jul 29 15:15) | HEAD frozen through Aug 3 |

**No `.env` snapshot exists for any date other than the disputed `.env.bak` (Jul 1).** No env-history FIFO covers July (oldest 2026-09-21). No `env/`-family commit landed on any of the 5 top days above except Jul 31 (fcda554 itself). Therefore even for the top single day (Jul 21 +138.8p), there is no recoverable (SHA + `.env`) pair — only (SHA + git-tracked `env/40-gates.env` + unknown `.env`).

**No better single pair exists.** The published package's pin of `fcda554` remains the best representative commit *for the Jul 30–31 sub-window*, and is defensible strictly for that sub-window.

### 2.4 What can be pinned with confidence

| item | evidence | confidence |
|---|---|---|
| Working-tree HEAD SHA at each moment in July | `git reflog /opt/tradingbot` | HIGH — timestamps precise to the second |
| `env/40-gates.env` state at each moment | `git log -- env/40-gates.env` | HIGH |
| `env/10-infrastructure.env` state | git — no changes in July | HIGH |
| Fires opened per day + strategy + outcome + pnl_pips | `backups/eod-review/2026-07-{21..31}/signal_log.jsonl` (Jul 1–20 accessible via the cumulative snapshot at 2026-07-21 EOD) | HIGH |
| Bot restart / process-start timestamps | systemd journal (unavailable) | **UNKNOWN** |
| `.env` (base) at each moment | none | **UNKNOWN** — `.env.bak` is falsified as a representative snapshot per §2.2 |
| `.env` at the moment `fcda554` was running | none | **UNKNOWN** |
| Whether the bot restarted between fetch of `fcda554` and Jul 30 first fire | systemd journal (unavailable) | **UNKNOWN** — inferential only |

---

## 3. The exact GitHub commit to install

Per the operator brief ("Return … the exact GitHub commit to install"):

- **`autobot_reports` recovery-package commit:** `e8eb294` on branch `recovery/autobot-july2026`. **Unchanged from earlier delivery.** Contains source at SHA `fcda554`, sanitised `.env.example`, provenance markdown, tests, deploy units.
- **Upstream AutoBot source SHA:** `fcda554` (`docs(env): flip BB_BOUNCE_LEVEL_GATE_MODE back to shadow`, 2026-07-29 15:15:39 +0000). This is the correct pin for the frozen Jul 30–31 tail. It is **NOT** a representative pin for the full profitable July.

Per the brief ("No further strategy research, code changes or activation"): the pair remains inactive on the destination. Any decision to install requires operator authorisation and, given the evidence in §2.2, requires reconstructing an effective `.env` from a non-`.env.bak` source before activation.

---

## 4. Confirmed facts

- **Whole-AutoBot July fired 182 trades, net +611.0 pips.** Sourced from `backups/eod-review/2026-07-31/signal_log.jsonl` (whole-month cumulative snapshot). All pairs / all strategies.
- **20 distinct strategy labels fired in July** — including 21 EMA_PULLBACK fires between Jul 1 and Jul 22, and 13 BRIEFING_EXECUTION + 2 BRIEFING_V5 fires between Jul 23 and Jul 31.
- **`fcda554` was the working-tree HEAD from 2026-07-29 15:15:39 UTC through 2026-08-03 08:38:56 UTC.** No commits landed in that ~4.7-day window.
- **`env/40-gates.env` at `fcda554` = last-of-July state**, following 8 July commits. Contents in git and reproducible.
- **`.env.bak` mtime = 2026-07-01 18:50:32 UTC, size 51,782 bytes.** Distinct from live `/opt/tradingbot/.env` (mtime 2026-09-26 20:37 UTC, size 48,340 bytes) on `BRIEFING_EXECUTION_ENABLED` (bak=0, live=1) and total size (Δ = 3,442 bytes).
- **`.env.bak` state contradicts July running-state on at least 3 flags** (see §2.2). It is a **backup snapshot found on disk, not a runtime record**.

## 5. Unknowns

- **Bot restart / process-start timestamps for the entire month of July.** systemd-journal retention is exhausted; only 2026-09-30 boots survive.
- **The exact `.env` in effect at any point during July.** No snapshot on disk. `.env.bak` falsified as the representative snapshot (§2.2).
- **Whether the bot restarted after `fcda554` was fetched into the working tree** (i.e. whether `fcda554` bytecode ever became the running bytecode). Inferential from `Restart=always` in `autobot.service` + typical cadence, but not directly recorded.
- **Per-day whole-AutoBot P&L in currency terms** — the pip figure per day is direct; the £ figure requires a per-day stake schedule which was not extracted in this bounded check.
- **Whether the 15 briefing-only trades were fired on the same host as the whole-AutoBot 182 fires** — the memory `[Bounce route wired via NEWS_TREND_ROUTER]` and `[Phase 1 dispatch-owner flags]` reference "the FXi/144 box" as a separate briefing-execution host. Cross-host attribution is not confirmed from this bounded pass.

---

## 6. Delivery statement

- The recovery package on `autobot_reports` branch `recovery/autobot-july2026` at commit `e8eb294` **is unchanged and inactive**.
- This correction supersedes the earlier summary language, not the package contents.
- The **exact GitHub commit to install**, if authorised: `e8eb294` (recovery-package) / underlying source `fcda554`. Its representativeness is confined to Jul 30–31; for anything earlier a further reconstruction pass would be needed and would face the `.env`-UNKNOWN barrier.

Report artefact only. No orders. No IG queries. No code changes. No activation.
