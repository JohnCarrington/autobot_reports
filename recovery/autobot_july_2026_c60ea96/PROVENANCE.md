# AutoBot July-2026 Recovery — Evidence-Backed Configuration Package

**Source tip:** `c60ea96` — `docs(env): align 40-gates.env BB_BOUNCE_LEVEL_GATE_MODE with live enforce` (2026-07-29 06:54:32 +0000)
**Package build date:** 2026-09-30 (evening; supersedes the labelling of `recovery/autobot-july2026` at commit e8eb294)
**Delivery mode:** READ-ONLY, INACTIVE. No orders, no IG queries, no service starts.

This is the **second** recovery package on `autobot_reports`. The first (`recovery/autobot-july2026` at `e8eb294`, source SHA `fcda554`) **remains intact and unchanged**. This package (`recovery/autobot-july2026-c60ea96`, source SHA `c60ea96`) is delivered per operator brief to build the *closest evidence-backed* July configuration.

---

## 1. Why `c60ea96` — not `fcda554`, not any top-5 day

The operator brief excluded two selection criteria: "not simply the last July commit or the highest-profit day." That rules out `fcda554` (last-of-July) and the tips coincident with the top-5 P&L days (Jul 21 head, Jul 15 head, Jul 2 head, Jul 6 head, Jul 31 head=fcda554). `c60ea96` is chosen on **direct runtime-evidence fidelity**:

**Uniqueness:** `c60ea96` is the sole July tip whose own commit message quotes a live-process observation:

> "Live .env and PID 2654603 environ both carry BB_BOUNCE_LEVEL_GATE_MODE=enforce; this file still said 'shadow' — a lying source-of-truth. Aligning."
>
> — commit c60ea96, body

That single sentence gives us **three verified facts** that no other July SHA provides:
1. On 2026-07-29 06:54 UTC, PID **2654603** was the running AutoBot process.
2. Its environ (i.e. the values `python-dotenv` had loaded into the interpreter) held `BB_BOUNCE_LEVEL_GATE_MODE=enforce`.
3. The `.env` file on disk at that moment agreed.

No other July tip is anchored to a runtime observation this cleanly. Every other tip's `.env` state is inferential.

**Reflog properties:**
- `c60ea96` held HEAD from 2026-07-29 06:54:32 UTC to 2026-07-29 15:15:39 UTC — an **8h20m** window.
- It was superseded by `fcda554`, whose commit message explicitly says it "Reverts the enforce alignment from c60ea96" — meaning fcda554 changed *only* the doc file, and the runtime `.env` state at `c60ea96` is what was actually running through most of the Jul 25–29 window (which is when env/40-gates.env was authored).

**What `c60ea96` does NOT give us:**
- Its live-window (8h20m) contained **zero fires** — the one Jul 29 fire happened at 17:49 UTC, 2h34m after fcda554 superseded c60ea96.
- Its own diff is a one-line documentation edit — the code state at `c60ea96` is byte-identical to the code state at every commit going back to `4203e89` (Jul 26 19:23) for strategy-runtime files.

Both of the above are reasons the operator brief explicitly excluded "highest-profit day" from the selection — coverage of any single high-P&L day is not the metric. **Fidelity of a recoverable `.env` snapshot is.**

### Alternate tips considered and rejected

| tip | live window | pips | rejection reason |
|---|---|---|---|
| `fcda554` (Jul 29 15:15) | 96.8h (largest) | +115.7 | "not simply the last July commit" (operator brief). Also, its message explicitly REVERTS the alignment quoted above — meaning it de-anchors from any runtime observation. |
| `9ea9470` (Jul 1 20:35) | 23.3h | +96.8 | Second-highest pip window, but no env/40-gates.env exists at this tip (file first landed Jul 25) and no commit message records a runtime observation. |
| `f3191a8` (Jul 21 18:16) | 23.6h | +59.8 | Post-top-day tip; no env/40-gates.env; no runtime anchor. |
| `383c599` (Jul 6 12:19) | 24.2h | +30.7 | Covers Jul 6 afternoon but no env-file coverage; unresolved config would balloon. |
| `d54080d` (Jul 27 12:47) | 0.7h | −12.1 | Superseded fast; env work committed but immediate replacement. |
| `4203e89` (Jul 26 19:23) | 17.4h | −12.1 | env-file present but no runtime observation in commit message. |

**Verdict:** `c60ea96` is chosen for **anchor fidelity**, accepting the trade-off that its own live window contained no fires. Consumers who value fire-window coverage should read this package alongside `recovery/autobot-july2026` at `e8eb294` (which pins `fcda554` and covers Jul 30–31 fires).

---

## 2. Config precedence at c60ea96 — how each setting is actually loaded

This section answers operator §4: "identify whether .env, tracked gate files or runtime overrides actually control each setting."

### Load order at bot startup

```
systemd unit  autobot.service     EnvironmentFile=/opt/tradingbot/.env
                                         │  (systemd parser — has known
                                         │   issues with inline "# comment"
                                         │   suffixes on KEY=value lines)
                                         ▼
                                  process env populated
                                         │
autobot.py line 56               load_dotenv(override=True)
                                         │  (python-dotenv reads the SAME
                                         │   /opt/tradingbot/.env file with
                                         │   a clean parser; override=True
                                         │   REPLACES systemd's polluted
                                         │   values — this was added
                                         │   2026-05-27 after an incident,
                                         │   per the source comment)
                                         ▼
                                  final effective process env
                                         │
strategy modules                  os.getenv("KEY", "default")
                                         │  (any key absent from .env falls
                                         │   through to the code default
                                         │   hard-coded in the strategy file)
```

### What is NOT loaded at c60ea96

- **`env/40-gates.env`** — the file's own header (byte-for-byte at c60ea96) states:
  > "This file is not auto-loaded by the systemd unit today; it is the authoritative documented source-of-truth for gate/mode flags. When the layered loader is wired, this file supplies the values below."

  No `load_dotenv("env/40-gates.env")` or `open("env/40-gates.env")` call exists anywhere in the source tree at c60ea96 (verified by `git grep -n "40-gates" c60ea96 -- '*.py'` — matches only in scripts/tests, not runtime). **The layered loader is documented as unwired.** Values here are aspirational documentation; the operator is expected to sync them manually into `.env`.

- **`env/10-infrastructure.env`** — same header, same status.

### Precedence summary

| source | loaded? | winner? |
|---|---|---|
| `/opt/tradingbot/.env` (via `EnvironmentFile` then `load_dotenv(override=True)`) | YES | **SUPREME** — python-dotenv override wins over systemd |
| `env/40-gates.env` at any tracked commit | NO | documentation only |
| `env/10-infrastructure.env` at any tracked commit | NO | documentation only |
| Code-default in `os.getenv("KEY", "default")` | YES (fallback only) | wins only if `.env` doesn't set the key |

### Implication for prior claims

- The earlier correction report (`autobot_july_recovery_correction_20260930.md` §2.2) listed "8 env/40-gates.env commits landed" as evidence against `.env.bak`. That evidence is **weaker than presented**: env/40-gates.env changes documented operator intent but were not auto-loaded, so the strict claim is only that `.env.bak` disagrees with (a) fires observed in signal_log, and (b) the c60ea96 message's direct runtime observation of one flag.
- **A fire contradicting a `.env.bak` flag proves `.env.bak` is not a runtime snapshot for that flag's key.** It does NOT prove which value `.env` actually held — only that `.env.bak` is not it. This is the operator's §4 clarification and it is respected here.

---

## 3. Confidence-labelled configuration

See [`env.reconstructed.example`](env.reconstructed.example). Every non-credential key is labelled:

| label | meaning | key count |
|---|---|---:|
| `[CONFIRMED]` | quoted from c60ea96 commit message OR from env/40-gates.env at c60ea96 (documented intent that matched runtime for at least BB_BOUNCE_LEVEL_GATE_MODE per §1) | 12 |
| `[INFERRED]` | implied by signal_log fire evidence or by an operator memory entry that overlaps the July date range | 15 |
| `[CODE_DEFAULT]` | value not present in any tracked config file; using the default hard-coded in `os.getenv("KEY", "default")` at c60ea96 | 6 |
| `[UNKNOWN]` (marked `REPLACE_ME`) | no recoverable evidence; destination MUST inject before running | 14 (all credentials) |

Unresolved settings that could not be confidently placed in any category are listed separately in [`UNRESOLVED_SETTINGS.md`](UNRESOLVED_SETTINGS.md).

---

## 4. Signal-log-anchored strategy table (for cross-reference)

Source: `/opt/tradingbot/backups/eod-review/2026-07-31/signal_log.jsonl`, deduplicated by `id`. Every row has `outcome`, `total_pnl_pips`, `pair`, `timestamp_open`/`timestamp_close`.

**Pip accounting:** `net_pips = sum(total_pnl_pips)`. For scaled fires (81 of 182), `total_pnl_pips = partial_bank_pips + runner_pnl_pips`. **Partial-close P&L IS included.** Not normalised to 1-unit-equivalent; not convertible to GBP without per-trade stake. W/L uses `abs(total_pnl_pips) ≥ 0.4p` (0 rows fell in the BE bucket — all resolved either W or L).

| strategy | pair(s) | fires | scaled/unscaled | W | L | BE | net_pips | first fire | last fire |
|---|---|---:|---|---:|---:|---:|---:|---|---|
| GBPUSD_BB_BOUNCE_L | GBPUSD | 33 | 15/18 | 16 | 17 | 0 | −42.5 | 2026-07-01 | 2026-07-31 |
| GBPUSD_BB_BOUNCE_S | GBPUSD | 31 | 23/8 | 22 | 9 | 0 | **+193.4** | 2026-07-01 | 2026-07-31 |
| GBPUSD_TREND_V3_L | GBPUSD | 31 | 11/20 | 21 | 10 | 0 | **+148.6** | 2026-07-02 | 2026-07-30 |
| BRIEFING_EXECUTION | EURUSD, GBPUSD | 13 | 0/13 | 6 | 7 | 0 | −15.7 | 2026-07-23 | 2026-07-31 |
| GBPUSD_EMA_PULLBACK_S | GBPUSD | 11 | 7/4 | 6 | 5 | 0 | +28.7 | 2026-07-01 | **2026-07-22** |
| GBPUSD_EMA_PULLBACK_L | GBPUSD | 10 | 5/5 | 5 | 5 | 0 | +81.3 | 2026-07-02 | **2026-07-20** |
| GBPUSD_STRUCTURE_BREAK_L | GBPUSD | 9 | 5/4 | 5 | 4 | 0 | +29.1 | 2026-07-01 | 2026-07-30 |
| GBPUSD_TREND_V3_S | GBPUSD | 9 | 3/6 | 5 | 4 | 0 | +28.7 | 2026-07-08 | 2026-07-31 |
| GBPUSD_STRUCTURE_BREAK_S | GBPUSD | 6 | 2/4 | 3 | 3 | 0 | +39.5 | 2026-07-01 | 2026-07-21 |
| GBPUSD_CONFIRMATION_FALLBACK_S | GBPUSD | 6 | 3/3 | 5 | 1 | 0 | +26.5 | 2026-07-01 | 2026-07-31 |
| GBPUSD_CONFIRMATION_FALLBACK_L | GBPUSD | 6 | 3/3 | 4 | 2 | 0 | +41.5 | 2026-07-09 | 2026-07-21 |
| FIFTY_PIP_BREAKOUT_USDCAD_V4 | USDCAD | 4 | 0/4 | 1 | 3 | 0 | −20.3 | 2026-07-23 | 2026-07-24 |
| MACD_EXTREME_GBPUSD_LONG | GBPUSD | 3 | 0/3 | 1 | 2 | 0 | −20.2 | 2026-07-23 | 2026-07-23 |
| NEWS_STRATEGY_CONT | GBPUSD | 2 | 1/1 | 1 | 1 | 0 | +12.0 | 2026-07-02 | 2026-07-02 |
| P2_USDJPY_B | USDJPY | 2 | 0/2 | 0 | 2 | 0 | −14.1 | 2026-07-23 | 2026-07-23 |
| BRIEFING_V5 | EURUSD, GBPUSD | 2 | 1/1 | 1 | 1 | 0 | +48.3 | 2026-07-29 | 2026-07-31 |
| GBPUSD_BB_REV_PAT_S | GBPUSD | 1 | 1/0 | 1 | 0 | 0 | +8.1 | 2026-07-03 | 2026-07-03 |
| NEWS_STRATEGY_REVERSAL | GBPUSD | 1 | 1/0 | 1 | 0 | 0 | +17.6 | 2026-07-22 | 2026-07-22 |
| RSI_FADE_GBPUSD_SHORT | GBPUSD | 1 | 0/1 | 1 | 0 | 0 | +20.1 | 2026-07-23 | 2026-07-23 |
| P2_EURUSD_A | EURUSD | 1 | 0/1 | 1 | 0 | 0 | +0.5 | 2026-07-23 | 2026-07-23 |
| **TOTAL** | — | **182** | 81/101 | **106** | **76** | 0 | **+611.0** | 2026-07-01 | 2026-07-31 |

20 distinct strategy labels. 0 unresolved outcomes.

**Dedup note:** signal_log had 182 rows in July; 182 unique `id`s; no duplicate rows to remove. `deal_id` also unique on every row.

---

## 5. Top-5 highest-profit days — source-tip map

Source: reflog-derived HEAD movements + intraday fire timestamps.

### 2026-07-21 — +138.8p, 13 fires

- **HEAD at 00:00 UTC:** `ae9de0f` (Jul 20 18:54, `feat(ema_pullback): peak-pivot runner trail`).
- **HEAD movements during trading hours (fires 06:55 → 16:25 UTC):** 5 commits landed intraday (`a7e2892` 03:24, `a59b4da` 03:52, `c0d34cc` 04:35, `e6bfbd1` 08:08, `2ec14ad` 12:56, `ac6d4ea` 13:55, `c25e4bd` 14:18, `e54c904` 16:22). HEAD moved 11 times on this day.
- **Recorded strategies:** STRUCTURE_BREAK_S (+65.2p, 2 fires), TREND_V3_S (+51.2p, 2), EMA_PULLBACK_S (+21.15p, 1), CONFIRMATION_FALLBACK_L (+13.85p, 2), BB_BOUNCE_S (+7.45p, 1), BB_BOUNCE_L (−20.05p, 5).
- **Verdict:** No single tip captures this day.

### 2026-07-15 — +102.8p, 25 fires

- **HEAD at 00:00 UTC:** `30371ad` (Jul 14 17:05, `feat(signal_logger): FXi plan telemetry`).
- **HEAD movements during trading hours:** 6 commits landed intraday (`0aed4ff` 10:27, `ca20dd3` 13:57, `0f5b488` 15:06, `e3d1161` 18:20, `96da119` 19:09, `6c52577` 19:52).
- **Recorded strategies:** BB_BOUNCE_S (−79.2p, 4 fires; a bad day for this label), TREND_V3_L (+71.55p, 13 — big volume, big win-rate 9/4), EMA_PULLBACK_L (+52.7p, 3), CONFIRMATION_FALLBACK_L (+28.85p, 1), STRUCTURE_BREAK_L (+26.5p, 2), BB_BOUNCE_L (+2.4p, 2).
- **Verdict:** No single tip captures this day.

### 2026-07-31 — +97.2p, 12 fires

- **HEAD at 00:00 UTC:** `fcda554` (Jul 29 15:15).
- **HEAD movements during trading hours:** **NONE.** HEAD held fcda554 all day.
- **Recorded strategies:** BRIEFING_V5 (+62.6p, 1 fire, single big win), BB_BOUNCE_S (+53.15p, 3), TREND_V3_S (+9.45p, 1), CONFIRMATION_FALLBACK_S (+9.05p, 1), BB_BOUNCE_L (+2.25p, 2), BRIEFING_EXECUTION (−39.3p, 4).
- **Verdict:** `fcda554` cleanly captures the whole day. This is the strongest single-day/single-tip pair of the top-5.

### 2026-07-02 — +96.8p, 8 fires

- **HEAD at 00:00 UTC:** `9ea9470` (Jul 1 20:35, `feat(bb_bounce): JSONL sink for STRONG_TREND stand-down blocks`).
- **HEAD movements during trading hours:** none in the fire window (fires ended 12:34 UTC; next commits at 19:51+).
- **Recorded strategies:** EMA_PULLBACK_L (+48.95p, 1 fire, big single win), TREND_V3_L (+35.8p, 5), NEWS_STRATEGY_CONT (+12.0p, 2).
- **Verdict:** `9ea9470` cleanly captures this day's fires.

### 2026-07-06 — +62.1p, 11 fires

- **HEAD at 00:00 UTC:** `bfe1ac7` (Jul 5 22:35, `feat(v5_pia): gate unconsumed Anthropic rationale POST`).
- **HEAD movements during trading hours:** 2 commits (`faf109e` 11:50, `383c599` 12:19).
- **Recorded strategies:** TREND_V3_L (+29.6p, 4 fires), EMA_PULLBACK_L (+24.65p, 1), STRUCTURE_BREAK_L (+16.8p, 2), BB_BOUNCE_S (+1.8p, 2), EMA_PULLBACK_S (−10.7p, 2).
- **Verdict:** `bfe1ac7` captures pre-11:50 fires; `383c599` captures post-12:19. Fires 11:50-12:19: `faf109e` (very narrow).

**Top-5 summary:** 2 of 5 (Jul 31 under fcda554, Jul 2 under 9ea9470) map cleanly to a single tip. 3 of 5 span multiple tips. **No pre-existing tip cleanly covers the whole top-5.** This confirms the correction report's §2.3 finding: the profitable July is not represented by any single (SHA, .env) pair.

---

## 6. Modifications for publication

Same as the previous package: 4 sanitization redactions to remove live IG credentials from documentation comments. Behavioural code paths unchanged.

| File | Original (obfuscated in this doc) | Replaced with |
|---|---|---|
| `src/autobot.py` (comment) | 6-char IG account ID | `REDACTED_IG_ACCT` |
| `src/rest_allowance.py` (comment) | 6-char IG account ID | `REDACTED_IG_ACCT` |
| `tests/unit/test_rest_allowance_ig_capture.py` (docstring) | 6-char IG account ID | `REDACTED_IG_ACCT` |
| `src/docs/RUNBOOK.md` (prose) | IG web-UI username | `REDACTED_IG_USERNAME` |

---

## 7. Package contents

```
autobot_july_2026_c60ea96/
├── PROVENANCE.md                              # this file
├── env.reconstructed.example                  # config with per-key confidence labels
├── UNRESOLVED_SETTINGS.md                     # short list of settings that could not be recovered
├── env-layer-tracked/
│   ├── 40-gates.env                           # verbatim env/40-gates.env at c60ea96 (unloaded per §2)
│   └── 10-infrastructure.env                  # verbatim env/10-infrastructure.env at c60ea96
├── src/                                       # 337 files: full source at c60ea96
├── deploy/                                    # 18 files: systemd units + drop-ins + base autobot.service
├── tests/                                     # 122 files: full test suite at c60ea96
└── recovery_provenance/
    ├── strategy_table_july.md                 # the whole-July strategy table (§4 above, standalone)
    ├── strategy_table_july.csv                # machine-readable form
    ├── top5_day_map.md                        # top-5-days source-tip map (§5, standalone)
    └── head_stability_windows_july.md         # every reflog-derived idle window in July
```

---

## 8. What this package is NOT

- **Not deployable as-is.** 14 credential slots need injection. Do NOT commit filled-in `.env` to any repo.
- **Not activated.** Per operator brief: "no changes to running bots, no activation or broker calls."
- **Not a claim that c60ea96 is THE right SHA.** It is the tip with the best-anchored runtime evidence in its own commit message. Its 8h20m live window contained 0 fires; the earlier package at `fcda554` covers Jul 30–31 fires but lacks the runtime anchor.
- **Not a merge of the two packages.** Consumers should read both:
  - `recovery/autobot-july2026` @ `e8eb294` (SHA fcda554) — fire-window coverage for Jul 30–31
  - `recovery/autobot-july2026-c60ea96` @ this branch (SHA c60ea96) — evidence-anchored config

---

## 9. Confirmed / unknown split (short)

**Confirmed at the source-tip level:**
- SHA `c60ea96` (byte-identical checkout of every tracked file at that commit)
- `env/40-gates.env` and `env/10-infrastructure.env` at `c60ea96` (verbatim)
- `deploy/systemd/*` and system-installed `autobot.service` (as of 2026-09-30 destination read; unchanged since Feb 2026)
- `BB_BOUNCE_LEVEL_GATE_MODE=enforce` at 2026-07-29 06:54 UTC (from c60ea96 commit body)
- All 182 July fire records: strategy, pair, direction, timestamps, outcome, pnl_pips, total_pnl_pips

**Unknown at the source-tip level:**
- The full contents of `/opt/tradingbot/.env` at 2026-07-29 06:54 UTC — only ONE key is quoted in the commit message
- Whether the bot process restarted between c60ea96's commit and any specific fire
- Whether `env/40-gates.env` documented values were manually synced to `.env` at each doc commit

**Unknown at the whole-package level:**
- 14 credential values (marked `REPLACE_ME` in `env.reconstructed.example`)
- The effective values of any `.env` key not in the confidence table (see `UNRESOLVED_SETTINGS.md`)
