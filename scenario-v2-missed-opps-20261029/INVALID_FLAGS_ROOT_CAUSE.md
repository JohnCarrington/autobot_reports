# INVALID Flags Root-Cause Investigation — 29 October 2026 09:46 Dashboard

Source files:
- Validator: `/mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_quality.py` (md5 `202d915f0554b0cebc77f9442eb8527e`, mtime 2026-10-28 22:31:08Z).
- Scenario row: `/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenarios_shadow.jsonl` — scenario_id `9fb58109c4dc34c2`, revision_idx 15 (bar_ts_utc `2026-10-29T09:30:00+00:00`, generated_at_utc `2026-10-29T09:41:02.054311+00:00`).
- Quality decision: `/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenario_quality_flags.jsonl` — bar_ts_utc `2026-10-29T09:30:00+00:00`.

The operator's screenshot timestamp was `2026-10-29T09:46:30Z`. Between 09:41:02Z (bar 09:30 scenario published) and 09:51:57Z (bar 09:35 scenario published) the latest-by-`generated_at_utc` revision shown on the dashboard was **the 09:30 bar scenario, revision 15**. The three flags displayed on screen match that row exactly.

## Flag 1 — UNSUPPORTED_CONFIDENCE_PERCENT @ actions[0].change_from_previous

**Validator rule** (scenario_quality.py:57-62, 202-212):
```python
_CONFIDENCE_PATTERN = re.compile(
    r"(\d{1,3})\s?%\s*(confidence|probability|likelihood|conviction|certainty)"
    r"|(confidence|probability|likelihood|conviction|certainty)\s+(?:of\s+)?"
    r"(?:approximately\s+)?(\d{1,3})\s?%",
    flags=re.IGNORECASE,
)
def _validate_confidence_claims(assessment, flags):
    for path, text in _iter_strings(assessment):
        for m in _CONFIDENCE_PATTERN.finditer(text):
            pct = m.group(1) or m.group(4)
            flags.append(QualityFlag(
                code="UNSUPPORTED_CONFIDENCE_PERCENT",
                severity="HIGH",
                ...))
```

Any `N%` adjacent to `confidence|probability|likelihood|conviction|certainty` anywhere in the assessment → **HIGH**. Not softened by hedge words.

**Offending text (full):**
```
Bullish reversal pathway remains operationally invalidated unless price
recovers +7.92 pips AND consecutive_closes_beyond transitions 0→2+ AND
NMS choch BULLISH confirmed — currently <10% probability.
```

**Analysis:**
1. The number is **not a trade confidence**. The sentence states the opposite — the reversal pathway is "operationally invalidated" and the "<10% probability" is used to **dismiss** an alternative scenario, not to support a trade.
2. The validator does not distinguish "I am 70% confident in this trade" (made-up endorsement) from "the reversal pathway is <10% probable" (dismissive hedge). Both match the regex.
3. The number is still arbitrary — the AI has no empirical basis for "<10%".

**Verdict:** Rule literally matched → HIGH is **mechanically correct**. **Semantically a false positive for the harm the rule intends to prevent** (confidence inflation to justify entry). The AI used the number to argue *against* the alternative, which is the opposite failure mode. The three analogues it then cites ("<5% post-BoE expiry", "<10% probability", "<5% operationally") share the same pattern across the day's rows.

## Flag 2 — UNSUPPORTED_CONFIDENCE_PERCENT @ actions[0].anticipated_sequence[3].note

**Offending text (full):**
```
Bullish Choch Conditional Reversal (<5% post-BoE expiry)
If acceptance latch forms by 10:15Z (consecutive_closes_beyond→2+) AND
NMS choch_direction transitions BULLISH AND USD 12:30Z beats verified
(weak data: GDP <3.0% OR Personal Spending <0.4%), price reverses toward
BB_U (13328.07) and R1 (13351.18). Double alignment now required (BoE
expiry removes third condition); currently <5% probability.
```

**Analysis:** Same shape as Flag 1 — this one explicitly LABELS the pathway "Bullish Choch Conditional Reversal (<5%)" i.e. the AI is tagging a low-probability counter-direction scenario so the operator knows not to lean on it. Then also writes "currently <5% probability" inside the note. Two matches, flagged once (deduped by `where` path).

**Verdict:** Mechanically correct, semantic false positive — same category as Flag 1.

**Note on the operator's screenshot showing TWO "UNSUPPORTED_CONFIDENCE_PERCENT" entries:** this is because the dashboard renders one row per `flag_codes` list entry, and `flag_codes` on the 09:30 scenario row was literally `["UNSUPPORTED_CONFIDENCE_PERCENT", "UNSUPPORTED_CONFIDENCE_PERCENT", "CATEGORY_A_TRIGGER_WITH_EVENT_NAME"]` — the same code appeared twice because two different paths in the assessment matched the regex (`change_from_previous` and `anticipated_sequence[3].note`). The code is deduplicated at the `(code, where)` tuple level, not at the `code` level.

## Flag 3 — CATEGORY_A_TRIGGER_WITH_EVENT_NAME @ actions[0].opportunities[0].required_price_behaviour

**Validator rule** (scenario_quality.py:146-180, 548-607):

```python
_EVENT_NAME_STOPWORDS = frozenset({
    "the", "and", "of", "a", "an", "for", "to",
    "index", "flash", "final", "preliminary", "revised",
    "mom", "yoy", "qoq", "qoqa", "pmi", "report",
    "data", "release", "update", "number",
})

def _event_name_tokens(name: str) -> set[str]:
    out: set[str] = set()
    for raw in re.findall(r"[A-Za-z]+", (name or "")):
        t = raw.lower()
        if len(t) < 2:
            continue
        if t in _EVENT_NAME_STOPWORDS:
            continue
        out.add(t)
    return out

def _validate_opportunity_category(...):
    ...
    if category == "A":
        for name in all_event_names:
            if _event_name_tokens_in(trigger_text, name):
                flags.append(QualityFlag(
                    code="CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                    severity="HIGH",
                    ...))
```

**Offending text (`required_price_behaviour`, full):**
```
Price breaks and holds below R00 (13300.0) with confirmed close ≤13300.0
for minimum 2 consecutive bars; acceptance latch remains inoperative
(consecutive_closes_beyond stays 0); NMS bullish structure remains
latent; downside continuation activates independent of BoE outcome
(now EXPIRED, no catalyst)
```

**The validator alleges event name "PCE Price Index MoM".**

Tokenise "PCE Price Index MoM":
- Raw tokens: `pce`, `price`, `index`, `mom`
- Strip stopwords: `index` ∈ STOPWORDS, `mom` ∈ STOPWORDS → removed.
- Remaining tokens: **`{pce, price}`**.

Scan `required_price_behaviour` lowercased:
> **`price` breaks and holds below r00 (13300.0) with confirmed close ≤13300.0 for minimum 2 consecutive bars...**

The lowercase trigger text contains the token **`price`** — matched because `price` is NOT in the stopword list and the generic noun "Price" was used as the subject of the sentence ("Price breaks and holds below…").

**Verdict:** **FALSE POSITIVE — stopword-list defect.**

The event "PCE Price Index MoM" contributes `price` and `pce` to the token set. "Price" is a universal market-structure noun that appears in virtually every trigger description. Any opportunity whose trigger starts with "Price breaks…", "Price closes…", "Price pierces…" and that coexists in a session where any event name contains the word "Price" (e.g. "PCE Price Index MoM", "GDP Price Index QoQ Adv", "Export Prices", "Import Prices", "House Price Index") will FALSELY TRIGGER CATEGORY_A_TRIGGER_WITH_EVENT_NAME.

This is the **primary mechanical defect** behind today's INVALID banner. All 31 scenario revisions on 2026-10-29 (06:50 → 09:50) had the identical structural trigger starting "Price breaks and holds below R00…" and were all rejected the same way once the first "Price"-containing event appeared in `economic_context.all_events` (first such event seen was already in `scheduled` at 06:50 — the USD 12:30Z Core PCE Price Index MoM).

Analogous false matches on later bars:
- 09:35 and 09:40 bars flagged against `"GDP Price Index QoQ Adv"` — same mechanism, token `price` matches.
- 09:20 bar flagged against `"Core PCE Price Index MoM"` — same mechanism.

The validator does not distinguish an event's **generic token overlap** with the trigger text from an actual **reference** to the event name. The intended rule — "if the entry fires because an event prints" — is correctly a HIGH defect. The implemented rule — "any token overlap, even generic nouns, is HIGH" — is too aggressive.

## Fourth flag — not shown on screenshot but present on earlier bars

The 09:25 bar (generated 09:41:51Z) had a 4th flag:

```
CATEGORY_C_WITHOUT_VERIFIED_RELEASE @ actions[0].opportunities[1].category
```

The reversal opportunity (opp[1], BUY to R1) carried `category=C` but the scenario had `economic_context.released = []` (empty — no releases verified yet). Rule at scenario_quality.py:608-630:

```python
elif category == "C":
    full_text = " ".join([trigger_text, opp.get("note") or ""])
    cites_released = False
    for name in released_names:
        if _event_name_tokens_in(full_text, name):
            cites_released = True
            break
    if not cites_released:
        flags.append(QualityFlag(code="CATEGORY_C_WITHOUT_VERIFIED_RELEASE", severity="HIGH", ...))
```

**Verdict:** Mechanically correct. The AI tagged the reversal opp as category C ("post-verified-release") despite no release yet. This is an **AI mis-classification**, not a validator bug. Rule is right.

## Downstream effect — WAIT recommendation

`scenario_recommendation.py:721-726`:
```python
if pub_decision == "INVALID":
    base_payload.update(_wait(
        SUPPRESSED,
        "NO AUTHORISED TRADE — scenario publication_decision=INVALID "
        f"(flags: {', '.join(pub.get('flag_codes') or []) or 'unspecified'})"))
    return base_payload
```

Any HIGH flag → `publication_decision=INVALID` → the recommendation engine returns `WAIT` / `readiness=SUPPRESSED` **before** evaluating entry/stop/target or market freshness. This is the correct ordering (safety first) — but means **a single false-positive HIGH flag is sufficient to suppress a technically valid proposal for the entire scenario's lifetime**.

Today, EVERY one of the 31 scenario revisions between 06:50Z and 09:50Z (3 hours) was tagged INVALID, exclusively by the two bug classes above. Not one revision escaped to CAUTION or VALID.

## Could the unsupported percentages be removed without altering the trade proposal?

Yes. The three structured numeric fields on the row (`trade_proposal.entry_price=13300.0`, `stop_price=13318.0`, `target_price=13285.78`) and the primary opportunity's `direction=SELL`, `structural_target=S1` are completely independent of the percentage phrases, which live inside `change_from_previous` / `anticipated_sequence[3].note`. Deleting both percentages leaves the trade intent unchanged.

Similarly, the generic "Price" subject in `required_price_behaviour` could be rewritten "Close breaks and holds below R00 (13300.0)…" — removing the `price` token — without affecting the technical content of the trigger.

**Recommendation:** address at the AI-prompt level (ban numeric probability phrasing; constrain `required_price_behaviour` wording to avoid the word "Price") AND at the validator level (add `price` + other generic nouns to `_EVENT_NAME_STOPWORDS`; downgrade UNSUPPORTED_CONFIDENCE_PERCENT to WARN when the context is a dismissive hedge rather than a trade endorsement). Both changes together, not either alone — defense in depth.
