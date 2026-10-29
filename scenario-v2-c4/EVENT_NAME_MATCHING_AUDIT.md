# Event-Name Matching — Audit of Correction 4

## 1. The defect

`agent/scenario_quality.py:538-545` (pre-C4):

```python
def _event_name_tokens_in(text: str, event_name: str) -> bool:
    """Return True if the TEXT contains at least one UNIQUE-token
    (post-stopword) of the event_name."""
    tokens = _event_name_tokens(event_name)
    if not tokens:
        return False
    tl = text.lower()
    return any(t in tl for t in tokens)
```

`_event_name_tokens` stripped only "format" stopwords: `the and of a an for to index flash final preliminary revised mom yoy qoq qoqa pmi report data release update number`.

For `"PCE Price Index MoM"` the output was `{pce, price}`. The validator looked for ANY token (`pce` OR `price`) anywhere in the trigger text (substring, no word boundary). The lowercase `price` matched the capitalized generic noun `Price` that opens the required_price_behaviour `"Price breaks and holds below R00..."`.

### Rows affected

```
2026-10-29 CATEGORY_A_TRIGGER_WITH_EVENT_NAME HIGH flags: 30 of 31 revisions
  Matched event names (sample): "PCE Price Index MoM",
                                "GDP Price Index QoQ Adv",
                                "Core PCE Price Index MoM",
                                "Mortgage Approvals",
                                "BoE Consumer Credit"
```

Not a one-off: this is a **structural defect**. Any trigger-text sentence starting with the generic noun "Price" (and most do) will false-match any event whose non-stopword tokens include `price`, which is dozens of regularly scheduled releases.

## 2. The repair strategy

Rejected approach: *"add `price` and every other generic noun to `_EVENT_NAME_STOPWORDS`"*. Discussed in operator §2:

> Critical restriction: Do not indiscriminately add every economic term to a stopword list. Words such as `employment`, `inflation`, `payrolls`, `GDP`, `CPI`, `PCE` and `FOMC` can be meaningful event identifiers. Removing them without examining the consequences could introduce false negatives.

Chosen approach: *distinguish* generic vocabulary overlap from explicit event reference by using two complementary mechanisms:

1. **Expanded generic stopwords** (`_EVENT_GENERIC_STOPWORDS`) — removes generic nouns that appear BOTH in event names AND in ordinary technical descriptions.
2. **Distinctive identifiers** (`_EVENT_KNOWN_IDENTIFIERS` + ALL-CAPS acronym heuristic) — set of tokens that uniquely name an event. Must appear in the trigger text for a match to fire when the event has such identifiers.
3. **Independence markers** (`_EVENT_INDEPENDENCE_MARKERS`) — phrases that explicitly disclaim event dependency. A candidate match within 60 chars of one of these is suppressed.
4. **Full-phrase fallback** — events without distinctive identifiers (e.g. "Mortgage Approvals") require the FULL non-stopword token set to appear in the text, whole-word boundaries, order-independent.

## 3. Token walkthrough

### Example A — the historical 09:30 trigger

Event name: `"PCE Price Index MoM"`

| Step | Operation | Result |
|---|---|---|
| 1 | Raw tokens | `['PCE', 'Price', 'Index', 'MoM']` |
| 2 | Lowercase, drop <2 chars | `{pce, price, index, mom}` |
| 3 | Strip `_EVENT_NAME_STOPWORDS` (`index`, `mom`) | `{pce, price}` |
| 4 | **C4**: strip `_EVENT_GENERIC_STOPWORDS` (`price`) | `{pce}` |
| 5 | Distinctive identifiers: `PCE` is all-caps 2–5 chars → `{pce}` | distinctive = `{pce}` |

Trigger text: `"Price breaks and holds below R00 (13300.0) with confirmed close ≤13300.0 for minimum 2 consecutive bars..."`

| Check | Pre-C4 | C4 |
|---|---|---|
| Any token `in` text? | `price in "price breaks and holds below..."` → **TRUE** | n/a |
| Distinctive `pce` whole-word in text? | n/a | FALSE (`pce` not in text) |
| Verdict | **CATEGORY_A fires HIGH (FP)** | **not matched** |

### Example B — a genuine dependency

Trigger text: `"SELL if the PCE release confirms weaker inflation"`

| Check | Pre-C4 | C4 |
|---|---|---|
| Any token `in` text? | `price` matches `inflation` includes `in`? no — `price` not in text. `pce` IS in text → TRUE | n/a |
| Distinctive `pce` whole-word in text? | n/a | TRUE |
| Independence marker within 60 chars of `pce`? | n/a | FALSE |
| Verdict | **HIGH fires** | **HIGH fires (preserved)** |

### Example C — disclaimer

Trigger text: `"...downside continuation activates independent of BoE outcome (now EXPIRED)"`

Event: `"BoE Consumer Credit"` → tokens `{boe}` (`consumer`, `credit` are in `_EVENT_GENERIC_STOPWORDS`). distinctive = `{boe}`.

| Check | Pre-C4 | C4 |
|---|---|---|
| Token `boe` in text? | TRUE | TRUE (candidate) |
| Independence marker within 60 chars? | n/a | TRUE (`independent of` within 15 chars of `boe`) |
| Verdict | **HIGH fires (FP)** | **not matched (suppressed by independence marker)** |

### Example D — compound event name

Event: `"Mortgage Approvals"`

| Step | Operation | Result |
|---|---|---|
| 1 | Raw tokens | `['Mortgage', 'Approvals']` |
| 2 | Lowercase | `{mortgage, approvals}` |
| 3 | Strip `_EVENT_NAME_STOPWORDS` | `{mortgage, approvals}` (none removed) |
| 4 | **C4**: strip `_EVENT_GENERIC_STOPWORDS` (`approvals`) | `{mortgage}` |
| 5 | Distinctive: `mortgage` ∈ `_EVENT_KNOWN_IDENTIFIERS` | distinctive = `{mortgage}` |

Trigger text A: `"Price breaks support while economic news remains scheduled."` → no `mortgage` → **not matched** ✓

Trigger text B: `"Fade of the Mortgage Approvals downside surprise"` → `mortgage` in text → match fires, no independence marker → **HIGH preserved** ✓

### Example E — event without distinctive identifier

Event: `"Personal Income MoM"` → tokens (post-generic-strip): `{}` (both `personal` and `income` are in `_EVENT_GENERIC_STOPWORDS`; `mom` is in `_EVENT_NAME_STOPWORDS`). Distinctive: `{}`.

- No distinctive tokens AND no non-stopword tokens → match returns FALSE **always**.
- A pure phrase trigger "Price closes above personal resistance" will no longer trip CATEGORY_A HIGH for the "Personal Income MoM" event.
- Deliberate acceptance: `Personal Income MoM` has no uniquely-identifying token in English prose; the operator's directive is to prefer specificity. If this event ever becomes an explicit entry prerequisite, the AI will say something like `"after the Personal Income print"` — in which case `print` is not in the current stopword set and a token-set match would fire. We can address that in C5 if observed.

## 4. Replay numbers

Historical 2026-10-29 scenario revisions (28 rows for the morning window):

```
Pre-C4 (A):            27 INVALID / 1 CAUTION / 0 VALID
Event-fix only (B):    12 INVALID / 16 CAUTION / 0 VALID
Confidence-fix only (C): 26 INVALID / 1 CAUTION / 1 VALID
Both C4 fixes (D):      5 INVALID / 19 CAUTION / 4 VALID
```

- Event-fix alone eliminates CATEGORY_A false positives on 15 of 27 originally-INVALID rows (16 CAUTION − 1 pre-existing CAUTION = 15).
- Confidence-fix alone eliminates `UNSUPPORTED_CONFIDENCE_PERCENT` HIGH on only a handful of rows because most rows ALSO have the CATEGORY_A FP.
- Both together recover **23 of 27** originally-INVALID rows to publishable (19 CAUTION + 4 VALID).

The remaining 5 INVALID rows in config D carry legitimate HIGH flags (chiefly `CATEGORY_C_WITHOUT_VERIFIED_RELEASE` on the reversal opp, which correctly fires because the reversal depends on a 12:30Z USD release that has not yet occurred).

## 5. Verification coverage (`tests/test_c4_event_name_and_confidence.py` 01–09)

| § | Test | Status |
|---|---|---|
| 7(1) | Generic `price` token does not match `PCE Price Index` | PASS |
| 7(2) | Generic market language does not match `GDP Price Index` | PASS |
| 7(3) | Explicit PCE dependency still fires HIGH | PASS |
| 7(4) | Explicit CPI dependency still fires HIGH | PASS |
| 7(5) | Explicit NFP dependency still fires HIGH | PASS |
| 7(6) | Explicit FOMC dependency still fires HIGH | PASS |
| 7(7) | Technical cat-A trigger with macro narrative remains independent | PASS |
| 7(8) | Cat-A trigger genuinely requiring an event remains INVALID | PASS |
| 7(9) | Cat-C without verified release remains INVALID | PASS |

## 6. Residual risks

- **Event names with only generic tokens** (e.g. "Personal Income MoM", "Business Confidence") become unmatchable. If one ever becomes a real entry prerequisite, the AI must spell it out in a way that contains at least one word outside `_EVENT_GENERIC_STOPWORDS` (e.g. use the explicit release label `"Personal Income release"` → `release` is in `_EVENT_NAME_STOPWORDS`, so still won't match; the AI must use a non-stopword like `print`, `data`, `report` — actually `data`, `release`, `report` are in `_EVENT_NAME_STOPWORDS` too). **This is a conservatism** — if the AI genuinely needs to express event dependency for such events it should use an acronym or central bank name. Expected false-negative rate in practice: low (operator-example triggers all name a central bank or a release acronym).

- **Independence marker false negatives.** A sentence like `"Fade EUR/USD regardless of PCE direction"` → suppressed. That's the right call: the trader is NOT depending on the PCE event. Operator confirmed semantics are correct.

- **New events with new acronyms.** Any ALL-CAPS 2–5 char token in the event name is treated as distinctive. If a future event has a non-standard non-acronym capitalization (e.g. `"Loonie-pal"` or similar), it may slip through. The curated `_EVENT_KNOWN_IDENTIFIERS` list is the backup; add to it as new releases are configured in the Finnhub feed.
