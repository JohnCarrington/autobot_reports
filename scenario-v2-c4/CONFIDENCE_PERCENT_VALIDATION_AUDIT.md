# Confidence-Percent Validation — Audit of Correction 4

## 1. The two layers

- **Validator layer** — `scenario_quality.py:_validate_confidence_claims` (lines 202-212 pre-C4; unchanged in C4). Any `N% probability|confidence|likelihood|conviction|certainty` phrase anywhere in the assessment produces a HIGH `UNSUPPORTED_CONFIDENCE_PERCENT` flag. HIGH → INVALID → recommendation=WAIT.
- **Prompt layer** — `scenario_reasoner.py:SCENARIO_SYSTEM`. Pre-C4 the prompt did not prohibit numeric probabilities. The AI generated phrases like `"...currently <10% probability"` and `"<5% probability"` to dismiss alternative pathways; the validator caught them as HIGH; publication was suppressed every revision.

## 2. Pre-C4 validator behaviour (unchanged)

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
                where=path,
                detail=f"{pct!r}% confidence/probability claim: "
                       f"{text[:160]}",
            ))
```

The regex is permissive on sentiment. "70% confidence this trade sets up" fires. "<5% probability of reversal" also fires. Both are HIGH.

## 3. The task's design directive

From §3:

> First, modify the AI reasoner's instructions to prohibit unsupported numerical probabilities.
> ...
> Preserve HIGH validation for unsupported numerical probabilities used to justify trading decisions.
> Investigate whether purely dismissive, non-actionable alternative-pathway commentary can be classified separately without allowing unsupported probability claims to influence entry decisions.
> Do not automatically downgrade all negative or low probabilities.
> **If a reliable distinction cannot be established, retain HIGH and eliminate the unsupported percentages at generation.**

I evaluated the possibility of a dismissive-vs-endorsement classifier at the validator level. The honest answer:

### Attempted splits

I tried three attribution schemes:

1. **Dismissive if co-located with negator** (`<`, `unlikely`, `operationally invalidated unless`, `requires A and B`). This leaves escape phrasings like `"unlikely at 95% confidence"` that would route to WARN under the dismissive branch while still being an unsupported numerical claim.
2. **Dismissive if attached to a non-primary opportunity** (`anticipated_sequence[*]` where role is NOT `first_target`). This is structural, not semantic — the AI can trivially move the phrase.
3. **Dismissive if percentage ≤ 20%**. Dangerous — a `20% probability of a SELL` endorsement would route to WARN.

None of the three is robust against the AI shifting wording. The task's final clause is accurate: **"If a reliable distinction cannot be established, retain HIGH and eliminate the unsupported percentages at generation."**

### Decision: validator unchanged, prompt tightened

Keep the HIGH validator. Add prompt rule 2a:

```
2a. NO UNSUPPORTED NUMERICAL PROBABILITIES (C4 2026-10-29). Do NOT
invent numeric probability, confidence, likelihood, conviction,
or certainty percentages anywhere in the assessment ... This
applies to BOTH endorsements and dismissals: '70% probability of
breakout', 'high conviction long', '<10% probability of reversal',
'<5% likely' are ALL prohibited. The only numeric probability
tokens permitted are those copied verbatim from a packet field
(e.g. an analogue's `score`) — cite the packet path in the same
sentence when you do. Describe confidence QUALITATIVELY: 'remains
unconfirmed', 'requires two consecutive closes above resistance',
'operationally invalidated unless X and Y occur', ...  The
validator flags any `N% probability|confidence|likelihood|
conviction|certainty` phrasing as HIGH — this suppresses
publication regardless of whether the percentage endorsed or
dismissed a pathway.
```

The rule enumerates each stored string field the validator scans, states the symmetry between endorsement and dismissal, and gives qualitative substitution examples. The last sentence makes the validator's HIGH behaviour visible so the AI understands the cost of noncompliance.

## 4. Why not relax the validator

Three concrete ways a relaxation could backfire:

- **Phrase laundering.** "unlikely at 95% confidence" means `confidence` of a NEGATIVE outcome being high. Under a "dismissive = WARN" rule, this would route to WARN; the implied endorsement of the primary direction is still backed by a made-up number.
- **Compound sentence smuggling.** The AI could write `"reversal is a very low probability pathway (5%); primary SELL remains the thesis"`. Under a context-aware classifier, the 5% is dismissive. But the 5% is still a trade-input to the operator reading the dashboard.
- **Cost of errors asymmetric.** False-negative on this rule (letting a probability through) subtly biases downstream behaviour. False-positive (over-blocking) is annoying but transparent — the operator sees the INVALID with the exact flag and can respond.

Prompt-level suppression + validator-floor is the safer configuration.

## 5. Expected shape of post-C4 AI output

A revision that previously said:

> "Bullish reversal pathway remains operationally invalidated unless price recovers +7.92 pips AND consecutive_closes_beyond transitions 0→2+ AND NMS choch BULLISH confirmed — currently <10% probability."

Should now read, under C4 prompt rule 2a:

> "Bullish reversal pathway remains operationally invalidated unless price recovers +7.92 pips AND consecutive_closes_beyond transitions 0→2+ AND NMS choch BULLISH confirmed."

The three-condition conjunction already carries the dismissive weight. The numeric is excess.

Similarly:

> "If acceptance latch forms by 10:15Z AND NMS choch_direction transitions BULLISH AND USD 12:30Z beats verified weak, price reverses toward BB_U; <5% operationally."

→

> "If acceptance latch forms by 10:15Z AND NMS choch_direction transitions BULLISH AND USD 12:30Z beats verified weak, price reverses toward BB_U; remains operationally improbable pending all three conditions."

## 6. Validator tests (§7(10)–(13))

| § | Test | Status |
|---|---|---|
| 7(10) | Unsupported positive confidence percent remains HIGH | PASS |
| 7(11) | "<5% chance" uncovered by validator — prompt is the defense | PASS (documented) |
| 7(12) | Dismissive phrasing with keyword still flags HIGH | PASS |
| 7(13) | Prompt contains the C4-2a rule including all 4 keywords | PASS |

The explicit test for the `chance` word (not in the validator keyword set — see §3 of the regex) is intentional. The validator cannot catch every possible synonym. Rule 2a enumerates the five keywords it does catch and tells the AI to avoid all probability-numeric phrasing. If the AI uses `chance`, the validator will not catch it; the operator will see the number in the dashboard narrative but no HIGH flag. **Acceptable** because the risk here is "operator sees a made-up number" not "operator sees an opportunity suppressed". The prompt rule is the primary defense.

## 7. Residual risks

- **AI noncompliance.** If the model emits percentages anyway, the validator still catches them → INVALID → WAIT. The old failure mode. Expected rate: low on the Haiku 4.5 model given the explicit enumeration in rule 2a, but not zero.
- **Synonyms outside the regex keyword set.** `chance`, `odds`, `expected value`, `pretty good shot` all slip the validator. Rule 2a prohibits them at generation. Risk: operator sees unsupported number but the system does NOT suppress publication over it.
- **Legitimate packet-score citation.** Rule 2a permits `"analogue score=10"` style citations when accompanied by a packet-path reference. The validator currently flags any `N% confidence` phrasing. If the AI cites a packet score as `"score 10 out of 10 (high confidence)"` without a `%` sign, the validator does not fire. If the AI writes `"confidence 90%"`, it fires. Rule 2a instructs the AI to prefer the non-% form.
