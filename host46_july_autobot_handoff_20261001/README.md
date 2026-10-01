# Host-46 July AutoBot Dependency & Data Handoff

**Prepared:** 2026-10-01 (source host 161)
**Scope:** GBPUSD candles sufficient to initialise July 2026 H1/H4/D1/W1 lookbacks and continue through the latest completed session, plus the production `briefing_direction.py` module + its upstream deps, with source provenance against commit `c60ea96`.

**Running production was not touched.** Zero service actions, zero `.env` reads, zero IG REST calls. Export-only.

---

## 1. Package layout

```
host46_july_autobot_handoff_20261001/
├── README.md                              ← this file
├── candle_data_inventory.md               ← candle-source details, TZ, precision, coverage, gaps
├── briefing_direction_provenance.md       ← git history of briefing_direction.py and deps vs c60ea96
├── code/
│   ├── briefing_direction.py              ← current production file (c60ea96-compatible, see §3)
│   ├── d1_direction.py                    ← upstream dep (unchanged since b8c05de 2026-05-11)
│   ├── config_d1_direction.yaml           ← upstream config (unchanged since b8c05de)
│   └── MANIFEST.sha256                    ← SHA-256 of the three code artefacts
└── data/
    ├── CANDLE_INVENTORY.csv               ← per-file: source, date, bar count, first/last ts, size
    ├── MANIFEST.sha256                    ← SHA-256 of every CSV in the data tree
    ├── GBPUSD_D1_archive_ext_v2.csv       ← D1 rollup 2024-01-01 → 2025-12-31 (archive-authoritative)
    ├── candles_GBPUSD_live/               ← 5-minute daily CSVs 2026-01-01 → 2026-10-01 (211 files)
    └── candles_GBPUSD_archive_ext_v2/     ← 5-minute daily CSVs 2024-01-01 → 2025-12-31 (627 files)
```

**Nothing in this package is a secret.** No `.env`, no credentials, no API keys.

---

## 2. Candle data — one-paragraph summary

Two per-day 5-minute CSV stores concatenate without overlap and without gap at the 2025-12-31 → 2026-01-01 boundary, giving GBPUSD continuous 5-minute coverage **2024-01-01 → 2026-10-01** (33 months). Daily rollup for the archive window (2024-01-01 → 2025-12-31) is included as `GBPUSD_D1_archive_ext_v2.csv`. D1/H1/H4/W1 lookbacks for 1 July 2026 are satisfied as follows:

| TF | 200-bar lookback need | Covered by |
|---|---|---|
| H1 | ~200 hours (≈8 trading days) | `candles_GBPUSD_live/2026-06-*.csv` resampled 5M→1H |
| H4 | ~800 hours (≈33 trading days) | `candles_GBPUSD_live/2026-05-*.csv` onwards, resampled 5M→4H |
| D1 | ~200 trading days | `GBPUSD_D1_archive_ext_v2.csv` (2024-01→2025-12) + rollup of live 2026 |
| W1 | ~200 weeks | **PARTIALLY covered**: archive gives ~104 weeks (2024-2025); W1(200) needs ~4 years → operator must decide whether a 100-week W1 bootstrap is sufficient or whether an earlier source is required (none available locally). |

Full inventory, timezone/precision/schema notes, and gap list are in [`candle_data_inventory.md`](candle_data_inventory.md).

**Known gaps requiring attention before July runtime:**
- **2026-03-02 → 2026-03-20** — 15 weekday days missing from live corpus (regime boundary). Does **not** affect July H1/H4/D1 bootstrap (all fall >100 days earlier than D1(200) needs), but noted here for transparency.
- **2026-05-15** (Fri) — single weekday gap. Marginal effect on H4(200) seed into July.
- **2026-07-13** (Mon) — single weekday gap **inside July**. Operator should check whether the H1/H4 resampler tolerates this.

---

## 3. briefing_direction.py — provenance & c60ea96 compatibility

**TL;DR:** The current file (bundled as `code/briefing_direction.py`, 55 lines, sha256 `c0042e5a…`) is **semantically compatible with commit c60ea96** and is the authoritative version to run against the July 2026 era. Full trace in [`briefing_direction_provenance.md`](briefing_direction_provenance.md).

Key findings:

- `briefing_direction.py` was **not tracked in git at c60ea96** (2026-07-29). The file first entered git on 2026-09-11 via commit `fb0039f7` under message *"chore(live-state): track live production modules with no git history"* — explicitly a snapshot of what was already running live. That snapshot's content is byte-identical to the current working copy.
- A *different* `briefing_direction.py` (126 lines, API `resolve_direction(daily, session, plan) -> Resolution`) was briefly tracked by commit `df43178` on 2026-06-02 and later superseded. **This file was removed from git before c60ea96** and does not match the live production API.
- At c60ea96, `briefing_execution.py` already imports `from briefing_direction import resolve_briefing_direction` (verified against blob `24343d18`). That function name only matches the current `fb0039f`-era file; the earlier `df43178` file exposed `resolve_direction` with a different signature. Hence the live production file at c60ea96 must have been the one later captured by `fb0039f` — i.e. the file bundled here.
- Upstream dependency `d1_direction.compute_d1_direction` was committed by `b8c05de` (2026-05-11), is present at c60ea96 (blob `6b1fb88f`), and is **unchanged** in the current working tree. The current `code/d1_direction.py` is identical to the c60ea96 version. Same for `config/d1_direction.yaml` (blob `043ddd27` at c60ea96, matches current).

The current `briefing_direction.py` only consumes two keys from the briefing dict (`daily_bias`, `session_bias`) — both of which are populated by `d1_direction.compute_d1_direction` and the briefing producer at c60ea96. No further imports; no additional runtime deps.

---

## 4. Branch / commit / path for host 46

- **Public repo:** `https://github.com/JohnCarrington/autobot_reports`
- **Branch:** `handoff/host46-july-autobot-20261001`
- **Commit:** written on commit — see below (will be filled by publishing step)
- **Package path within the repo:** `host46_july_autobot_handoff_20261001/`

Host-46 recipe:

```bash
git clone --branch handoff/host46-july-autobot-20261001 \
    https://github.com/JohnCarrington/autobot_reports.git host46_handoff
cd host46_handoff/host46_july_autobot_handoff_20261001/
sha256sum -c data/MANIFEST.sha256    # verify every candle CSV
sha256sum -c code/MANIFEST.sha256    # verify the three code artefacts
```

---

## 5. Session hygiene — what this handoff did and did not do

Did:
- Enumerated candle stores on local disk only (`/opt/tradingbot/data/*`).
- Copied two GBPUSD 5-minute daily CSV sets + the D1 rollup verbatim into the package.
- Copied three code files verbatim and SHA-256-hashed them.
- Resolved `briefing_direction.py` provenance by reading git objects (blobs) at `c60ea96`, `df43178`, `fb0039f` — no state mutation.
- Created a new git worktree + new branch for the publish; standing rules permit `worktree add` as the stash substitute. **No `git stash`. No `checkout`, `reset`, `merge`, `rebase` on the working tree of `/opt/tradingbot/reports-public`.**

Did NOT:
- Touch the running AutoBot. No `systemctl`, no `pkill`, no restart.
- Read, decrypt, or export `.env` or `.env.*` files.
- Call the IG REST API or any external data source.
- Fetch, build, or interpolate missing bars for the 2026-03 outage or the 2026-05-15 / 2026-07-13 single-day gaps.
- Force-push, rewrite history, or amend an existing commit.
