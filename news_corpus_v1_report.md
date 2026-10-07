# News Corpus v1 — STOP at step 0 (access check)

**Study version:** R4A (news-event corpus v1)
**Date:** 2026-10-07
**Worktree:** `/home/autobot/tradingbot-wt/news-rest` on branch `research/news-rest`
**Lineage:** R1 `c172ece` → R2 `c12e6af` → R3 `de9d918`
**STOP point:** Step 0 — Trading Economics PIT access probe.

---

## 1. Effective TE credential

- `te_calendar.py:28` reads `TRADING_ECONOMICS_API_KEY = os.getenv("TRADING_ECONOMICS_API_KEY", "guest:guest")`.
- No `TRADING_ECONOMICS_API_KEY`, `TE_API_KEY`, or `TE_KEY` is present in the shell environment or in `/opt/tradingbot/.env` (grep for the names returned zero rows).
- Effective credential used for the probe = module default = **`guest`** (literal guest:guest, the TE free tier).
- No file was edited to change the credential. No swap was proposed. No retry with a different key.

**Credential prefix reported to operator:** `guest`.

---

## 2. TE PIT access probe (step 0A)

Two probes, both via the TE historical calendar endpoint
`GET https://api.tradingeconomics.com/calendar/country/{country}/{d1}/{d2}?c=guest:guest&f=json`.

The two windows deliberately cover one UK BIG and one US BIG release (BoE Bank Rate ~2026-02-05, US NFP ~2026-02-06).

### UK probe

- URL (credential masked): `https://api.tradingeconomics.com/calendar/country/united kingdom/2026-02-01/2026-02-07?c=guest:***&f=json`
- HTTP status: **410 Gone**
- Response byte count: 214
- Response body (verbatim, first 500 chars):

```
<p>We are sorry, but the guest account has been discontinued.</p>
<p>Please subscribe to a plan at <a href="https://tradingeconomics.com/api/pricing.aspx">
    https://tradingeconomics.com/api/pricing.aspx</a>.</p>
```

### US probe

- URL (credential masked): `https://api.tradingeconomics.com/calendar/country/united states/2026-02-01/2026-02-07?c=guest:***&f=json`
- HTTP status: **410 Gone**
- Response byte count: 214
- Response body (verbatim, first 500 chars):

```
<p>We are sorry, but the guest account has been discontinued.</p>
<p>Please subscribe to a plan at <a href="https://tradingeconomics.com/api/pricing.aspx">
    https://tradingeconomics.com/api/pricing.aspx</a>.</p>
```

---

## 3. Verdict

**STOP at step 0 — no PIT access.**

The default `guest:guest` credential that `te_calendar.py` falls back to has been **discontinued by Trading Economics**. Both the UK and US historical-calendar requests return HTTP 410 with an identical subscription-required HTML stub. This is a subscription-restricted response (matches the step-0A STOP criterion: *"Is 401/403/subscription-restricted → STOP"* — 410 is semantically equivalent, "guest account has been discontinued, subscribe"). The response is not an empty array, not an unauthenticated empty rowset, and not a limited vintage — the endpoint flat-out denies the request.

No corpus build has been attempted. No raw/, normalized/, first_print_maps/ files were created. No TE requests beyond the two probe calls were issued. No code under `/opt/tradingbot/*.py` was touched. `.env` was not edited. No service was restarted. No further step was executed.

---

## 4. Standing-rules compliance checklist

- `/opt/tradingbot/*.py` — unmodified.
- `.env` — unmodified.
- Shell profiles — unmodified.
- `te_calendar.py` — unmodified.
- Services — unrestarted.
- R3 report `news_rest_break_event_study_20261007.md` — unmodified.
  - Pre-run sha256: `3c14f484b441390b0b5fa90300efede4daaf9bebb5286b6f7ceb365903f5ddf7`
  - Post-run sha256 recorded below in commit log.
- No credential value appears in this report beyond the first-four-chars (`guest`) prefix.
- Research-branch commits: none added for R4A (STOP at step 0; no corpus artefacts to freeze).

---

## 5. What would unblock R4A

A funded Trading Economics historical-calendar subscription (or an equivalent PIT provider) exposing `/calendar/country/{country}/{d1}/{d2}` with the full `Actual / Forecast / Previous / Revised / LastUpdate` field set. Supplying such credentials via `.env` is an operator action — I will not propose or install one.

R4A will resume at step 1 the next session, with the probe re-run against whatever credential is then effective, provided it clears the step-0 gate.

---

## 6. Explicit STOP marker

R4A step 1 (raw PIT acquisition) **not started.**
R4A step 2 (normalisation) **not started.**
R4A step 3 (tier assignment) **not started.**
R4A step 4 (component surprise) **not started.**
R4A step 5 (event grouping) **not started.**
R4A step 6 (first-print verification via ALFRED/ONS) **not started.**
R4A step 7 (freeze + manifest) **not started.**
R4B (candle data + outcomes) **not started.**
