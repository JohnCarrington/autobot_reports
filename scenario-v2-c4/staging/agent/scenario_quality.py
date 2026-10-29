"""Semantic validators for scenario-reasoner output + publication gate.

Two layers:

1. Flag collectors — pure functions over the structured assessment
   dict + the live packet. Each flag has a code, severity, where, and
   detail. Severities:

     INFO    — observable, no publication impact.
     WARN    — publish with a formatter disclaimer (CAUTION).
     HIGH    — serious defect; promotes assessment to INVALID (do NOT
               publish as actionable opportunity).

2. ``decide_publication(flags)`` — collapses the flag list into a
   single decision (VALID / CAUTION / INVALID) + a human-readable
   reason. The sweeper writes BOTH the raw flags AND the decision
   onto the scenario row and the telemetry row. The notifier reads
   the decision and gates OPPORTUNITY delivery; MORNING / CHANGE
   notifications continue (so operators still see state transitions
   and invalidations), but with a CAUTION/INVALID banner when
   applicable.

Design constraints enforced by operator directive 2026-10-23:
  * Flagging alone is insufficient for serious defects — INVALID
    opportunities are physically suppressed from Telegram.
  * Do NOT silently rewrite historical scenarios — the raw assessment
    is preserved in telemetry + scenarios_shadow.jsonl untouched; the
    decision is a parallel observability field.
  * Do NOT block an entire assessment because one optional economic
    field is missing — INVALID is reserved for genuinely unsafe
    publications: UNVERIFIED-as-catalyst, EXPIRED-as-upcoming,
    wrong-sided stops, false confirmation claims.
  * Preserve creative conditional reasoning: observed packet
    bar-counts (e.g. ``consecutive_closes_beyond=2``) are NEVER
    flagged. Only unobserved MANDATORY future counts are rejected.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any, Iterable


# ---------------------------------------------------------------------
# Regex catalogues
# ---------------------------------------------------------------------

_INDICATOR_PATTERN = re.compile(
    r"\b("
    r"rsi|macd|stochastic|stoch\b|adx|dmi|cci|roc|momentum oscillator|"
    r"obv|on[- ]balance volume|vwap|tpo|williams %r|tsi|psar|"
    r"parabolic sar|supertrend|chaikin|cmf|awesome oscillator|aroon"
    r")\b",
    flags=re.IGNORECASE,
)

_CONFIDENCE_PATTERN = re.compile(
    r"(\d{1,3})\s?%\s*(confidence|probability|likelihood|conviction|certainty)"
    r"|(confidence|probability|likelihood|conviction|certainty)\s+(?:of\s+)?"
    r"(?:approximately\s+)?(\d{1,3})\s?%",
    flags=re.IGNORECASE,
)

# Hard-requirement bar-count language. Softer "would / may / consider /
# suggested / watch for" phrasings are explicitly excluded via the
# qualifier allowlist below.
_HARD_BAR_COUNT_VERBS = (
    r"must|needs to|requires|require|has to|should|needed|is required to"
)
_SOFT_QUALIFIERS = re.compile(
    r"\b(would|may|might|could|consider|suggested|watch for|if sustained|"
    r"if observed|additional supporting evidence)\b",
    flags=re.IGNORECASE,
)
_HARD_BAR_COUNT_PATTERN = re.compile(
    r"\b(?:(?:" + _HARD_BAR_COUNT_VERBS + r")\s+(?:to\s+)?(?:close\s+)?"
    r"(?:at\s+least\s+)?(\d+|one|two|three|four|five|six)\s+"
    r"(?:consecutive\s+)?(?:bars|closes|candles|m5|five[- ]minute))\b",
    flags=re.IGNORECASE,
)

# Observed packet features that already carry a numeric count — if the
# model cites one of these with its CURRENT value we don't flag.
_PACKET_COUNT_FIELDS = (
    "consecutive_closes_beyond",
    "closes_above",
    "closes_below",
    "cumulative_cross_count",
    "interaction_elapsed_bars",
    "n_tests_bucket",
    "elapsed_bars",
)

_UNVERIFIED_REFERENCE_PATTERN = re.compile(
    # Explicit anticipatory wording only.  'Catalyst' alone was in the
    # original pattern but it also matches retrospective sentences
    # like 'Budget EXPIRED, catalyst removed', producing false
    # positives on legitimate acknowledgements that a release has
    # passed without data.  Anticipatory sentences will carry one of
    # the explicit phrases below.
    r"\b(if released|awaits|awaiting|anticipate|pending (?:release|data))\b"
    # Compound 'upcoming catalyst' / 'anticipated catalyst' still fire
    # because the leading 'awaits'/'anticipate' / 'pending' matches.
    r"|\bupcoming\s+catalyst\b"
    r"|\banticipated\s+catalyst\b",
    flags=re.IGNORECASE,
)


@dataclasses.dataclass(frozen=True)
class QualityFlag:
    code: str
    severity: str      # "INFO" | "WARN" | "HIGH"
    where: str
    detail: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _iter_strings(obj: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(obj, str):
        yield path or ".", obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, f"{path}[{i}]")


def _packet_has_indicator(packet: dict | None, name: str) -> bool:
    if not packet:
        return False
    nname = name.strip().lower()
    for key, _ in _iter_strings(packet):
        if nname in key.lower():
            return True
    return False


_EVENT_NAME_STOPWORDS = frozenset({
    "the", "and", "of", "a", "an", "for", "to",
    "index", "flash", "final", "preliminary", "revised",
    "mom", "yoy", "qoq", "qoqa", "pmi", "report",
    "data", "release", "update", "number",
})

# Correction 4 (2026-10-29) — vocabulary that overlaps event names AND
# everyday technical-trigger prose. These words alone cannot
# establish an economic-event dependency.
_EVENT_GENERIC_STOPWORDS = frozenset({
    "price", "prices", "rate", "rates", "growth", "change",
    "activity", "balance", "confidence", "sentiment", "claims",
    "spending", "income", "approvals", "lending", "credit",
    "sales", "orders", "production", "inventories",
    "manufacturing", "services", "consumer", "business",
    "personal", "government", "value", "level", "measure",
    "actual", "forecast", "consensus", "previous",
})

# Correction 4 — identifiers that are unambiguous event references:
# all-caps acronyms (PCE/GDP/CPI/NFP/FOMC...) and known central-bank
# or major-release names. One of these in the trigger text is
# sufficient to establish event reference by itself.
_EVENT_KNOWN_IDENTIFIERS = frozenset({
    "boe", "fomc", "fed", "ecb", "rba", "boj", "snb",
    "boc", "rbnz", "pboc", "nfp", "ism", "adp",
    "pce", "gdp", "cpi", "ppi",
    "nonfarm", "payrolls", "unemployment", "retail", "mortgage",
    "jolts", "jobless", "redbook", "chicago", "philly",
})


def _event_name_tokens(name: str) -> set[str]:
    """Significant-word tokens from an event name, with format
    stopwords AND generic market vocabulary stripped (C4).

    This produces the token set used for FULL-PHRASE matching
    when no distinctive identifier is present.
    """
    out: set[str] = set()
    for raw in re.findall(r"[A-Za-z]+", (name or "")):
        t = raw.lower()
        if len(t) < 2:
            continue
        if t in _EVENT_NAME_STOPWORDS:
            continue
        if t in _EVENT_GENERIC_STOPWORDS:
            continue
        out.add(t)
    return out


def _event_distinctive_identifiers(name: str) -> set[str]:
    """Return tokens that unambiguously name an event (C4).

    Two sources of distinctiveness:
      * ALL-CAPS acronyms (2-5 letters) in the ORIGINAL event name —
        these are unlikely to appear incidentally in a technical
        trigger (PCE, GDP, CPI, NFP, FOMC, ADP, ISM, BoE's acronym
        form, ...).
      * Known-identifier words — curated set of central-bank names
        and major macro release labels.

    An identifier in `text` is sufficient on its own to establish
    event reference, UNLESS the surrounding text explicitly
    disclaims dependency (see `_EVENT_INDEPENDENCE_MARKERS`).
    """
    distinctive: set[str] = set()
    for raw in re.findall(r"[A-Za-z]+", (name or "")):
        if 2 <= len(raw) <= 5 and raw.isupper():
            distinctive.add(raw.lower())
        if raw.lower() in _EVENT_KNOWN_IDENTIFIERS:
            distinctive.add(raw.lower())
    return distinctive


# Correction 4 — phrases that explicitly DISCLAIM an event-dependency
# relationship. If an event identifier appears in text within a short
# window of one of these markers, the match is suppressed.
#
# Example: "downside continuation activates independent of BoE outcome
# (now EXPIRED, no catalyst)" — the author is explicitly denying the
# event is a prerequisite. The validator must respect that.
_EVENT_INDEPENDENCE_MARKERS = re.compile(
    r"\b(independent of|regardless of|irrespective of|"
    r"without regard to|without reference to|not dependent on|"
    r"does not depend on|no catalyst|no dependence on|"
    r"ignoring|setting aside)\b",
    flags=re.IGNORECASE,
)


def _event_bucket_token_map(econ: dict, bucket: str) -> dict[str, set[str]]:
    """``{event_name_lower: {tokens}}`` for a bucket."""
    out: dict[str, set[str]] = {}
    for e in econ.get(bucket) or []:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        toks = _event_name_tokens(name)
        if toks:
            out[name.lower()] = toks
    return out


# ---------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------

def _validate_indicator_grounding(assessment, packet, flags):
    for path, text in _iter_strings(assessment):
        for m in _INDICATOR_PATTERN.finditer(text):
            name = m.group(1)
            if _packet_has_indicator(packet, name):
                continue
            flags.append(QualityFlag(
                code="UNGROUNDED_INDICATOR",
                severity="HIGH",
                where=path,
                detail=f"cites {name!r} without a packet reading: "
                       f"{text[:160]}",
            ))


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


def _validate_hard_bar_counts(assessment, packet, flags):
    """Fire ONLY for mandatory future-bar-count rules that aren't
    directly reading a packet-published counter. Observed counts
    (``closes_above=5``, ``consecutive_closes_beyond=2``) are NEVER
    flagged — the model is permitted and encouraged to cite them."""
    for path, text in _iter_strings(assessment):
        # Permit sentences that cite packet-published counters alongside
        # the bar-count language. If the sentence contains any of the
        # observed-count field names (even if truncated to the stem),
        # we treat the citation as grounded.
        text_l = text.lower()
        cites_observed = any(f.lower() in text_l for f in _PACKET_COUNT_FIELDS)
        for m in _HARD_BAR_COUNT_PATTERN.finditer(text):
            matched = m.group(0)
            # If the surrounding sentence has a soft qualifier (would,
            # may, suggested, watch-for), don't flag — this is already
            # phrased as a suggestion.
            if _SOFT_QUALIFIERS.search(text):
                continue
            if cites_observed:
                continue
            flags.append(QualityFlag(
                code="FABRICATED_BAR_COUNT_RULE",
                severity="HIGH",
                where=path,
                detail=f"hard bar-count requirement '{matched!r}' with no "
                       f"packet-published counter cited: {text[:160]}",
            ))


def _validate_analogue_outcomes(assessment, analogues, flags):
    if not analogues:
        return
    unresolved = sum(1 for a in analogues
                     if (a.get("physical_outcome") or "").upper() == "UNRESOLVED")
    resolved = len(analogues) - unresolved
    if unresolved == 0:
        return
    stem = " ".join(str(assessment.get(k) or "") for k in
                     ("current_interpretation", "narrative"))
    lower = stem.lower()
    for pat in (r"(\d+)\s+of\s+(\d+)\s+(?:previously\s+)?reversed",
                 r"(\d+)\s+of\s+(\d+)\s+(?:previously\s+)?broke",
                 r"(\d+)\s+of\s+(\d+)\s+(?:previously\s+)?confirmed",
                 r"(\d+)\s+of\s+(\d+)\s+(?:prior|previous|past)"):
        for m in re.finditer(pat, lower):
            claimed, total = int(m.group(1)), int(m.group(2))
            if claimed > resolved:
                flags.append(QualityFlag(
                    code="ANALOGUE_UNRESOLVED_MISREPRESENTED",
                    severity="HIGH",
                    where="narrative",
                    detail=(f"claims {claimed}/{total} but only "
                             f"{resolved} resolved ({unresolved} "
                             f"UNRESOLVED)"),
                ))


def _validate_opportunity_sides(assessment, flags):
    for a_idx, act in enumerate(assessment.get("actions") or []):
        if not isinstance(act, dict):
            continue
        for o_idx, opp in enumerate(act.get("opportunities") or []):
            if not isinstance(opp, dict):
                continue
            direction = (opp.get("direction") or "").upper()
            if direction not in ("BUY", "SELL"):
                continue
            text = " ".join(str(opp.get(k) or "") for k in
                              ("required_price_behaviour", "note"))
            lowered = text.lower()
            where = f"actions[{a_idx}].opportunities[{o_idx}]"
            if direction == "SELL":
                if re.search(r"stop[- ]?(?:loss)?\s+(?:is\s+|at\s+|placed\s+)?"
                              r"(?:just\s+)?below", lowered):
                    flags.append(QualityFlag(
                        code="WRONG_SIDED_STOP",
                        severity="HIGH", where=where,
                        detail=f"SELL opportunity names a stop below entry: "
                               f"{text[:160]}"))
                if re.search(r"target[- ]?(?:price)?\s+(?:is\s+|at\s+)?"
                              r"(?:just\s+)?above", lowered):
                    flags.append(QualityFlag(
                        code="CONTRADICTORY_TARGET",
                        severity="HIGH", where=where,
                        detail=f"SELL opportunity names a target above entry: "
                               f"{text[:160]}"))
            else:
                if re.search(r"stop[- ]?(?:loss)?\s+(?:is\s+|at\s+|placed\s+)?"
                              r"(?:just\s+)?above", lowered):
                    flags.append(QualityFlag(
                        code="WRONG_SIDED_STOP",
                        severity="HIGH", where=where,
                        detail=f"BUY opportunity names a stop above entry: "
                               f"{text[:160]}"))
                if re.search(r"target[- ]?(?:price)?\s+(?:is\s+|at\s+)?"
                              r"(?:just\s+)?below", lowered):
                    flags.append(QualityFlag(
                        code="CONTRADICTORY_TARGET",
                        severity="HIGH", where=where,
                        detail=f"BUY opportunity names a target below entry: "
                               f"{text[:160]}"))


def _validate_premature_confirmation(assessment, flags):
    for a_idx, act in enumerate(assessment.get("actions") or []):
        if not isinstance(act, dict):
            continue
        if (act.get("kind") or "").upper() != "REVISE":
            continue
        if (act.get("new_state") or "").upper() != "CONFIRMED":
            continue
        ev = act.get("evidence_supporting") or []
        if ev:
            continue
        flags.append(QualityFlag(
            code="PREMATURE_CONFIRMATION",
            severity="HIGH",
            where=f"actions[{a_idx}]",
            detail=("CONFIRMED state emitted without any "
                     "evidence_supporting entries in this revision"),
        ))


def _validate_unverified_event_references(assessment, economic_context, flags):
    """A reference to an UNVERIFIED or EXPIRED event name as an
    anticipated catalyst is a HIGH flag. These are the exact phrases
    the 2026-10-23 CBI defect produced: 'if released', 'awaits CBI',
    'anticipate', 'catalyst' near an event name whose status is
    UNVERIFIED or EXPIRED. The matcher is lenient on short-forms
    ("CBI" matches "CBI Business Optimism Index") but rejects
    stopwords ("index", "pmi", "mom" alone cannot trigger a false
    positive).

    EXPIRED events (release time passed but no actual recorded) are
    legitimate to discuss retrospectively but MUST NOT be treated as
    upcoming announcements.

    Token-overlap disambiguation (2026-10-28 incident fix):
    When a quarantined event's token also identifies a DIFFERENT
    (non-quarantined) event in the same context, that token is too
    weak to attribute a flag to the quarantined event.  Example:
    'Atlanta Fed GDPNow' (UNVERIFIED) and 'Fed Interest Rate
    Decision' (SCHEDULED) share the token 'fed'.  The bare word
    'fed' in the scenario text identifies the scheduled event's
    name; firing a flag on it over-attributes the reference to the
    quarantined event.  Only tokens UNIQUE to the quarantined event
    (atlanta, gdpnow) remain.

    Preserved: if the quarantined event has a SAME-NAME non-
    quarantined sibling (the classic UNVERIFIED stale-duplicate case
    — e.g., 'CBI Business Optimism Index' RELEASED yesterday AND
    'CBI Business Optimism Index' UNVERIFIED today), the common
    tokens remain in the quarantined set.  Mentioning the same name
    IS ambiguous between retrospective and anticipatory, and the
    'if released'/'anticipate' pattern already discriminates intent.
    """
    econ = economic_context or {}
    quarantined = {
        **_event_bucket_token_map(econ, "unverified"),
        **_event_bucket_token_map(econ, "expired"),
    }
    if not quarantined:
        return
    # Build per-non-quarantined event token sets.  A quarantined-event
    # token is "weak" if it is contained in some other-NAME event's
    # token set; it is "strong" if either (a) it is unique to the
    # quarantined event, OR (b) it is shared only with a same-NAME
    # non-quarantined sibling (the stale-duplicate preserve case).
    non_quarantined_by_name: dict[str, set[str]] = {}
    for bucket in ("scheduled", "released"):
        for name, toks in _event_bucket_token_map(econ, bucket).items():
            non_quarantined_by_name[name] = toks
    quarantined_disambiguated: dict[str, set[str]] = {}
    for q_name, q_toks in quarantined.items():
        kept: set[str] = set()
        for tok in q_toks:
            weak = False
            for other_name, other_toks in non_quarantined_by_name.items():
                if other_name == q_name:
                    # Same-name sibling: preserve this token.
                    continue
                if tok in other_toks:
                    weak = True
                    break
            if not weak:
                kept.add(tok)
        if kept:
            quarantined_disambiguated[q_name] = kept
    if not quarantined_disambiguated:
        return
    # Pre-compute per-name positive token lookup for fast containment.
    for path, text in _iter_strings(assessment):
        text_l = text.lower()
        if not _UNVERIFIED_REFERENCE_PATTERN.search(text_l):
            continue
        for name, tokens in quarantined_disambiguated.items():
            if any(t in text_l for t in tokens):
                flags.append(QualityFlag(
                    code="UNVERIFIED_EVENT_AS_CATALYST",
                    severity="HIGH",
                    where=path,
                    detail=(f"UNVERIFIED/EXPIRED event '{name}' cited "
                             f"as upcoming catalyst — rejected per "
                             f"PART 1 directive. Excerpt: {text[:160]}"),
                ))
                break  # one flag per field is enough


def _validate_directional_reconciliation(assessment, primary, flags):
    """When the primary observer's direction differs from a V2
    opportunity direction, the assessment MUST narrate the
    relationship. The narrative must include at least one of the
    conditional-sequence markers below. Silent disagreement is
    flagged WARN (CAUTION) so the message publishes with a visible
    disclaimer rather than silently contradicting the primary.
    """
    if not primary:
        return
    primary_dir = (primary.get("direction") or "").upper()
    primary_hyp = (primary.get("hypothesis") or "").upper()
    if primary_dir not in ("BUY", "SELL"):
        return
    opp_dirs: set[str] = set()
    for act in assessment.get("actions") or []:
        if not isinstance(act, dict):
            continue
        for opp in act.get("opportunities") or []:
            if isinstance(opp, dict):
                d = (opp.get("direction") or "").upper()
                if d in ("BUY", "SELL"):
                    opp_dirs.add(d)
    if not opp_dirs:
        return
    disagrees = {primary_dir} ^ opp_dirs  # symmetric diff
    if not disagrees:
        return
    narrative_text = " ".join(str(assessment.get(k) or "") for k in
                                ("narrative", "current_interpretation"))
    change_text = " ".join(
        str(a.get("change_from_previous") or "")
        for a in assessment.get("actions") or []
        if isinstance(a, dict))
    joined = (narrative_text + " " + change_text).lower()
    sequence_markers = (
        "subsequent reversal", "reversal if",
        "if subsequently", "after rejection", "if invalidated",
        "primary anticipates", "alternative scenario",
        "sequence:", "first ... then", "first the",
        f"primary {primary_hyp.lower()}", "watch_rejection",
        "primary observer",
    )
    if any(marker in joined for marker in sequence_markers):
        return
    flags.append(QualityFlag(
        code="PRIMARY_V2_DISAGREEMENT_UNEXPLAINED",
        severity="WARN",
        where="narrative",
        detail=(
            f"primary direction={primary_dir}, V2 opportunity "
            f"direction(s)={sorted(opp_dirs)}. Narrative does not "
            f"explain the sequence (subsequent reversal / "
            f"alternative scenario / etc)."),
    ))


# ---------------------------------------------------------------------
# P2 — Opportunity category (A/B/C) validators + field-weight asymmetry
# ---------------------------------------------------------------------

# Trigger-side fields.  A reference to an UNVERIFIED/EXPIRED event in
# one of these fields is HIGH; in any other field it is WARN (and the
# downstream publication gate collapses WARN → CAUTION).
_TRIGGER_SIDE_FIELD_MARKERS = (
    "required_price_behaviour",
    "trade_proposal.entry_trigger",
    "trigger_spec",
)


def _is_trigger_side(where: str) -> bool:
    return any(m in (where or "") for m in _TRIGGER_SIDE_FIELD_MARKERS)


def _apply_field_weight_asymmetry(flags: list) -> list:
    """Downgrade `UNVERIFIED_EVENT_AS_CATALYST` HIGH fires on
    narrative-only fields to WARN.  Trigger-side fires stay HIGH.

    See P2 brief: narrative-only references should not block an
    otherwise independent technical opportunity.
    """
    out = []
    for f in flags:
        if f.code != "UNVERIFIED_EVENT_AS_CATALYST":
            out.append(f)
            continue
        if _is_trigger_side(f.where):
            out.append(f)  # keep HIGH
            continue
        # Narrative-side citation → WARN.  Detail prefix annotates
        # the downgrade for auditability.
        out.append(QualityFlag(
            code=f.code,
            severity="WARN",
            where=f.where,
            detail=f"[FIELD_WEIGHT_ASYMMETRY: narrative-only → WARN] "
                    f"{f.detail}",
        ))
    return out


def _collect_opportunities(assessment: dict) -> list[tuple[str, dict]]:
    """Return list of (path, opp_dict) for every opportunity."""
    out = []
    for a_idx, act in enumerate(assessment.get("actions") or []):
        if not isinstance(act, dict):
            continue
        for o_idx, opp in enumerate(act.get("opportunities") or []):
            if isinstance(opp, dict):
                out.append((f"actions[{a_idx}].opportunities[{o_idx}]", opp))
    return out


def _event_name_tokens_in(text: str, event_name: str) -> bool:
    """Return True if the TEXT contains an EXPLICIT REFERENCE to the
    named economic event — not merely a generic-vocabulary overlap,
    and not a reference the author explicitly disclaims.

    Correction 4 (2026-10-29). The previous rule required only one
    non-stopword token overlap, which caused false positives when
    technical triggers used generic nouns ("Price breaks below ...")
    that also appear in event names ("PCE Price Index MoM" →
    tokens {pce, price}; token `price` would match the generic
    noun). All 30 CATEGORY_A_TRIGGER_WITH_EVENT_NAME flags on
    2026-10-29 shared this mechanism.

    New rule distinguishes GENERIC vocabulary overlap from EXPLICIT
    event reference and from DISCLAIMED mention:

      (1) If the event name has distinctive identifiers (acronyms
          like PCE/GDP/CPI/NFP, or known central-bank/release names
          like BoE / FOMC / Nonfarm / Mortgage), ANY of those
          appearing as a whole word in the text establishes a
          candidate reference.
      (2) Otherwise, the FULL set of significant non-stopword tokens
          from the event name must appear (whole-word, order-
          independent). A single generic overlap is no longer
          sufficient.
      (3) Any candidate reference is SUPPRESSED when the surrounding
          text (±60 chars) contains an independence marker like
          'independent of', 'regardless of', 'no catalyst'. The
          author has explicitly stated the trigger does not depend
          on the event; the validator respects that.

    Whole-word matching uses `\b` boundaries so a token like `pce`
    cannot match a substring inside an unrelated word.
    """
    tl = (text or "").lower()

    distinctive = _event_distinctive_identifiers(event_name)
    match_spans: list[tuple[int, int]] = []

    if distinctive:
        for d in distinctive:
            for m in re.finditer(rf"\b{re.escape(d)}\b", tl):
                match_spans.append((m.start(), m.end()))
        if not match_spans:
            # Event has distinctive identifiers but none appear in
            # the text. Do not fall through to token-set matching
            # for identifier-bearing events — require the explicit
            # acronym/known-identifier.
            return False
    else:
        tokens = _event_name_tokens(event_name)
        if not tokens:
            return False
        positions = {t: [(m.start(), m.end())
                         for m in re.finditer(rf"\b{re.escape(t)}\b", tl)]
                     for t in tokens}
        if not all(positions.values()):
            return False
        # Represent the full-phrase match by the span of the first
        # occurrence of each token (used only for independence-marker
        # suppression context).
        for p in positions.values():
            match_spans.append(p[0])

    # Suppress matches that fall within an independence-marker window.
    for start, end in match_spans:
        wnd_start = max(0, start - 60)
        wnd_end = min(len(tl), end + 30)
        if _EVENT_INDEPENDENCE_MARKERS.search(tl[wnd_start:wnd_end]):
            continue
        return True
    return False


def _validate_opportunity_category(assessment, economic_context, flags):
    """Three families of checks over the explicit `category` field.

    (1) UNDECLARED_OPPORTUNITY_CATEGORY — WARN when category missing.
    (2) CATEGORY_A_TRIGGER_WITH_EVENT_NAME — HIGH when category=A and
        a trigger field cites any event name (regardless of status).
    (3) CATEGORY_C_WITHOUT_VERIFIED_RELEASE — HIGH when category=C but
        the opportunity's narrative/text does not reference an event
        in `economic_context.released`.
    """
    econ = economic_context or {}
    released_names = {(e.get("name") or "").strip().lower()
                       for e in econ.get("released") or []
                       if (e.get("name") or "").strip()}
    # Union of ALL event names (any status) — used by category-A check.
    all_event_names = set()
    for bucket in ("scheduled", "released", "expired", "unverified"):
        for e in econ.get(bucket) or []:
            n = (e.get("name") or "").strip()
            if n:
                all_event_names.add(n)

    for path, opp in _collect_opportunities(assessment):
        category = (opp.get("category") or "").upper() if isinstance(
            opp.get("category"), str) else None
        direction = (opp.get("direction") or "").upper()
        if direction not in ("BUY", "SELL"):
            # WAIT / null — no category requirement.
            continue
        if not category:
            flags.append(QualityFlag(
                code="UNDECLARED_OPPORTUNITY_CATEGORY",
                severity="WARN",
                where=f"{path}.category",
                detail=(f"opportunity direction={direction} but "
                         f"category field missing/null; defaulting "
                         f"to CAUTION publication"),
            ))
            continue
        # Collect trigger-side text for this opportunity
        trigger_text_parts = [opp.get("required_price_behaviour") or ""]
        tp = opp.get("trade_proposal") or {}
        if isinstance(tp, dict):
            trigger_text_parts.append(tp.get("entry_trigger") or "")
        trigger_text = " ".join(trigger_text_parts).strip()

        if category == "A":
            # Any event name token in the trigger text → HIGH.
            for name in all_event_names:
                if _event_name_tokens_in(trigger_text, name):
                    flags.append(QualityFlag(
                        code="CATEGORY_A_TRIGGER_WITH_EVENT_NAME",
                        severity="HIGH",
                        where=f"{path}.required_price_behaviour",
                        detail=(f"category=A trigger text references "
                                 f"event '{name}'; A triggers must be "
                                 f"pure price conditions.  "
                                 f"Excerpt: {trigger_text[:160]}"),
                    ))
                    break
        elif category == "C":
            # Must cite a RELEASED event by name in trigger OR note.
            full_text = " ".join([
                trigger_text,
                opp.get("note") or "",
            ])
            cites_released = False
            for name in released_names:
                if _event_name_tokens_in(full_text, name):
                    cites_released = True
                    break
            if not cites_released:
                flags.append(QualityFlag(
                    code="CATEGORY_C_WITHOUT_VERIFIED_RELEASE",
                    severity="HIGH",
                    where=f"{path}.category",
                    detail=(f"category=C declared but opportunity "
                             f"text does not cite any event in "
                             f"economic_context.released. Category C "
                             f"requires a VERIFIED release before "
                             f"authorisation.  Excerpt: "
                             f"{full_text[:160]}"),
                ))


# ---------------------------------------------------------------------
# P3 — trigger_spec vs natural-language consistency
# ---------------------------------------------------------------------
_RPB_LEVEL_PATTERN = re.compile(
    r"(?:(?:break(?:s)?|close(?:s)?|holds?|sustains?)\s+"
    r"(?:and\s+(?:closes?|breaks?)\s+)?"
    r"(?:above|below|>=?|<=?)\s+"
    # Optional level-NAME label (R1, S2, BB_U, PDH, …) must be LETTERS
    # + optional single digit + underscore only, NOT a run of digits
    # that would eat the leading digit of the actual price.
    r"(?:[A-Za-z][A-Za-z_]*(?:[0-9])?\s+)?)"
    r"(\d{4,6}(?:\.\d+)?)",
    re.IGNORECASE,
)


def _side_from_rpb(text: str) -> str | None:
    """Return 'above' or 'below' if the natural-language trigger text
    unambiguously specifies a break direction; else None."""
    t = (text or "").lower()
    has_above = bool(re.search(
        r"\b(break|close|hold|sustain)[s]?\s+(?:and\s+(?:closes?|breaks?)\s+)?"
        r"(?:above|>=?)\b", t))
    has_below = bool(re.search(
        r"\b(break|close|hold|sustain)[s]?\s+(?:and\s+(?:closes?|breaks?)\s+)?"
        r"(?:below|<=?)\b", t))
    if has_above and not has_below:
        return "above"
    if has_below and not has_above:
        return "below"
    return None


def _price_in_rpb(text: str) -> float | None:
    """First numeric that looks like a GBPUSD level in a break clause."""
    m = _RPB_LEVEL_PATTERN.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _validate_trigger_spec_consistency(assessment, flags):
    """Cross-check that opportunities[*].trigger_spec matches the
    scenario's natural-language description.

    Fires HIGH when a machine-readable trigger_spec contradicts the
    opportunity's `required_price_behaviour` on any of:
      * direction (BUY vs SELL implied by break_above/below)
      * price level (within 2 p tolerance of a level named in the
        natural-language text)
      * trigger type (price_break_above vs _below vs _touch)

    Produces NO flag when the opportunity is:
      * explicitly `allow_discretion: True` (operator opt-out), OR
      * missing `trigger_spec` entirely (handled elsewhere), OR
      * natural-language text contains no parseable price/direction
        (ambiguous — AI retains evaluation).
    """
    for a_idx, act in enumerate(assessment.get("actions") or []):
        if not isinstance(act, dict):
            continue
        for o_idx, opp in enumerate(act.get("opportunities") or []):
            if not isinstance(opp, dict):
                continue
            if opp.get("allow_discretion") is True:
                continue
            ts = opp.get("trigger_spec")
            if not isinstance(ts, dict):
                continue
            spec_type = (ts.get("type") or "").lower()
            spec_level = ts.get("level_price")
            if spec_type not in ("price_break_above", "price_break_below",
                                   "price_touch"):
                continue
            rpb = opp.get("required_price_behaviour") or ""
            if not rpb:
                continue
            direction = (opp.get("direction") or "").upper()
            where_base = f"actions[{a_idx}].opportunities[{o_idx}]"

            # 1. Direction consistency
            # BUY typically pairs with price_break_above; SELL with
            # price_break_below.  price_touch is direction-neutral.
            if direction == "BUY" and spec_type == "price_break_below":
                flags.append(QualityFlag(
                    code="TRIGGER_SPEC_DIRECTION_MISMATCH",
                    severity="HIGH",
                    where=f"{where_base}.trigger_spec",
                    detail=(f"direction=BUY paired with "
                             f"type={spec_type} contradicts natural "
                             f"direction semantics"),
                ))
                continue
            if direction == "SELL" and spec_type == "price_break_above":
                flags.append(QualityFlag(
                    code="TRIGGER_SPEC_DIRECTION_MISMATCH",
                    severity="HIGH",
                    where=f"{where_base}.trigger_spec",
                    detail=(f"direction=SELL paired with "
                             f"type={spec_type} contradicts natural "
                             f"direction semantics"),
                ))
                continue

            # 2. Trigger-type consistency vs RPB side
            rpb_side = _side_from_rpb(rpb)
            if rpb_side is not None:
                if spec_type == "price_break_above" and rpb_side == "below":
                    flags.append(QualityFlag(
                        code="TRIGGER_SPEC_TYPE_MISMATCH",
                        severity="HIGH",
                        where=f"{where_base}.trigger_spec",
                        detail=(f"trigger_spec.type=price_break_above "
                                 f"but required_price_behaviour "
                                 f"describes a break BELOW"),
                    ))
                    continue
                if spec_type == "price_break_below" and rpb_side == "above":
                    flags.append(QualityFlag(
                        code="TRIGGER_SPEC_TYPE_MISMATCH",
                        severity="HIGH",
                        where=f"{where_base}.trigger_spec",
                        detail=(f"trigger_spec.type=price_break_below "
                                 f"but required_price_behaviour "
                                 f"describes a break ABOVE"),
                    ))
                    continue

            # 3. Price level consistency (±2 p tolerance)
            rpb_price = _price_in_rpb(rpb)
            if (spec_level is not None and rpb_price is not None
                    and abs(float(spec_level) - rpb_price) > 2.0):
                flags.append(QualityFlag(
                    code="TRIGGER_SPEC_LEVEL_MISMATCH",
                    severity="HIGH",
                    where=f"{where_base}.trigger_spec",
                    detail=(f"trigger_spec.level_price={spec_level} "
                             f"differs from level cited in "
                             f"required_price_behaviour ({rpb_price})"),
                ))


# ---------------------------------------------------------------------
# Correction 2 — structured trade_proposal validation
# ---------------------------------------------------------------------
# GBPUSD prices in this codebase use the LOI index-scale (1.2727 → 12727.0).
# A price < 100 is almost certainly broker-scale (1.33180) and MUST NOT
# silently mix with the index-scale.  Scales used for sanity:
_PRICE_INDEX_MIN = 10000.0   # typical lower bound in points
_PRICE_INDEX_MAX = 20000.0   # typical upper bound
_PRICE_BROKER_MAX = 10.0     # broker-scale cap (1.33180 etc)


def _is_index_scale(x) -> bool:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return _PRICE_INDEX_MIN <= v <= _PRICE_INDEX_MAX


def _is_broker_scale(x) -> bool:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return 0.0 < v < _PRICE_BROKER_MAX


def _validate_structured_trade_proposal(assessment, flags):
    """Correction 2.  For every opportunity whose category is A or B
    and whose direction is BUY or SELL:

      * All three structured prices (entry/stop/target) MUST be
        present.  Missing fields produce
        ``MISSING_STRUCTURED_PROPOSAL`` WARN — opportunity remains
        INCOMPLETE on the dashboard, not SUPPRESSED.
      * Structured prices MUST be numeric and finite.
      * Structured prices MUST use the index-scale (10000 < p < 20000).
        A broker-scale price (0 < p < 10) emits
        ``PRICE_SCALE_MISMATCH`` HIGH.
      * Structured geometry MUST satisfy direction-specific ordering:
        BUY: stop < entry < target; SELL: stop > entry > target.
        Violations emit ``STRUCTURED_PROPOSAL_GEOMETRY_INVALID`` HIGH.
      * When both structured.entry_price AND natural-language RPB
        contain a parseable price, the two MUST agree within 5 p.
        Divergence emits ``STRUCTURED_VS_NARRATIVE_CONTRADICTION``
        HIGH.
    """
    for a_idx, act in enumerate(assessment.get("actions") or []):
        if not isinstance(act, dict):
            continue
        for o_idx, opp in enumerate(act.get("opportunities") or []):
            if not isinstance(opp, dict):
                continue
            category = (opp.get("category") or "").upper()
            direction = (opp.get("direction") or "").upper()
            if category not in ("A", "B") or direction not in ("BUY", "SELL"):
                continue
            if opp.get("allow_discretion") is True:
                continue
            where_base = f"actions[{a_idx}].opportunities[{o_idx}]"
            tp = opp.get("trade_proposal") or {}
            if not isinstance(tp, dict):
                tp = {}

            e = tp.get("entry_price")
            s = tp.get("stop_price")
            t = tp.get("target_price")

            missing = []
            if e is None:
                missing.append("entry_price")
            if s is None:
                missing.append("stop_price")
            if t is None:
                missing.append("target_price")
            if missing:
                flags.append(QualityFlag(
                    code="MISSING_STRUCTURED_PROPOSAL",
                    severity="WARN",
                    where=f"{where_base}.trade_proposal",
                    detail=(f"category={category} direction={direction} "
                             f"missing structured fields: "
                             f"{', '.join(missing)}.  Narrative-regex "
                             f"fallback may produce incomplete or "
                             f"wrong-geometry results; the recommendation "
                             f"will remain INCOMPLETE until the AI emits "
                             f"explicit numeric prices."),
                ))
                continue   # don't try geometry if fields missing

            # Numeric sanity
            for name, v in [("entry_price", e), ("stop_price", s),
                             ("target_price", t)]:
                try:
                    fv = float(v)
                    if not (fv == fv) or fv in (float("inf"), float("-inf")):
                        raise ValueError("non-finite")
                except (TypeError, ValueError):
                    flags.append(QualityFlag(
                        code="MALFORMED_STRUCTURED_PRICE",
                        severity="HIGH",
                        where=f"{where_base}.trade_proposal.{name}",
                        detail=f"non-numeric or non-finite: {v!r}",
                    ))

            # Scale sanity.  All three must be index-scale.  If any is
            # broker-scale, emit PRICE_SCALE_MISMATCH HIGH (prevents a
            # dangerous silent mix-up).
            for name, v in [("entry_price", e), ("stop_price", s),
                             ("target_price", t)]:
                if _is_broker_scale(v):
                    flags.append(QualityFlag(
                        code="PRICE_SCALE_MISMATCH",
                        severity="HIGH",
                        where=f"{where_base}.trade_proposal.{name}",
                        detail=(f"{name}={v!r} appears to be broker-"
                                 f"scale (0 < p < 10); the LOI packet "
                                 f"uses index-scale (e.g. 12727.0)."),
                    ))
                elif not _is_index_scale(v):
                    # out-of-range but not clearly broker-scale either
                    flags.append(QualityFlag(
                        code="PRICE_SCALE_MISMATCH",
                        severity="HIGH",
                        where=f"{where_base}.trade_proposal.{name}",
                        detail=(f"{name}={v!r} is outside expected "
                                 f"index-scale range "
                                 f"({_PRICE_INDEX_MIN}-{_PRICE_INDEX_MAX})."),
                    ))

            # Geometry
            try:
                e_f = float(e); s_f = float(s); t_f = float(t)
                geom_ok = (
                    (direction == "BUY" and s_f < e_f < t_f) or
                    (direction == "SELL" and s_f > e_f > t_f)
                )
            except (TypeError, ValueError):
                geom_ok = False
            if not geom_ok:
                flags.append(QualityFlag(
                    code="STRUCTURED_PROPOSAL_GEOMETRY_INVALID",
                    severity="HIGH",
                    where=f"{where_base}.trade_proposal",
                    detail=(f"{direction} geometry invalid: "
                             f"entry={e}, stop={s}, target={t}. "
                             f"BUY requires stop<entry<target; "
                             f"SELL requires stop>entry>target."),
                ))

            # Structured vs narrative price agreement.  Structured
            # prices are authoritative; narrative text is secondary.
            # The validator classifies the comparison into three cases
            # so an unreliable natural-language regex extraction
            # cannot invalidate an otherwise-correct structured
            # proposal:
            #
            #   A — Clear contradiction (HIGH → INVALID): narrative
            #       extraction yielded a price > 50 p from the
            #       structured entry AND does not match the structured
            #       stop or target within 2 p.  A 50-p gap exceeds a
            #       typical GBPUSD daily ATR; the narrative describes
            #       a materially different trade.
            #
            #   B — Ambiguous (WARN → CAUTION): narrative yielded a
            #       price 5-50 p from the structured entry and does
            #       not match stop/target.  Could be legitimate
            #       narration drift or a parser mis-pick; operator
            #       sees a CAUTION disclosure, structured remains
            #       authoritative.  Diagnostic only.
            #
            #   C — Consistent (no flag): narrative within 5 p of
            #       entry, OR narrative within 2 p of structured stop
            #       or target (parser likely matched the wrong one of
            #       the three structured prices), OR no narrative
            #       price could be parsed.
            rpb = opp.get("required_price_behaviour") or ""
            rpb_price = _price_in_rpb(rpb)
            try:
                e_f = float(e)
                s_f = float(s) if s is not None else None
                t_f = float(t) if t is not None else None
            except (TypeError, ValueError):
                rpb_price = None   # malformed numbers handled above
            if rpb_price is not None:
                near_entry = abs(e_f - rpb_price) <= 5.0
                near_stop = (s_f is not None
                              and abs(s_f - rpb_price) <= 2.0)
                near_target = (t_f is not None
                                and abs(t_f - rpb_price) <= 2.0)
                diff = abs(e_f - rpb_price)
                if near_entry or near_stop or near_target:
                    pass   # case C — consistent, no flag
                elif diff > 50.0:
                    # case A — clear hard contradiction
                    flags.append(QualityFlag(
                        code="STRUCTURED_VS_NARRATIVE_CONTRADICTION",
                        severity="HIGH",
                        where=f"{where_base}.trade_proposal.entry_price",
                        detail=(f"trade_proposal.entry_price={e_f} "
                                 f"differs from required_price_behaviour-"
                                 f"cited break level {rpb_price} by "
                                 f"{diff:.1f} pips (> 50 p); narrative "
                                 f"and structured describe different "
                                 f"trades.  Resolve by keeping the "
                                 f"narrative sentence aligned with the "
                                 f"structured entry."),
                    ))
                else:
                    # case B — ambiguous drift (5 p < diff ≤ 50 p),
                    # not matched to stop or target either.  Soft
                    # disclosure only.
                    flags.append(QualityFlag(
                        code="STRUCTURED_NARRATIVE_PRICE_DRIFT",
                        severity="WARN",
                        where=f"{where_base}.trade_proposal.entry_price",
                        detail=(f"trade_proposal.entry_price={e_f} and "
                                 f"required_price_behaviour-cited level "
                                 f"{rpb_price} differ by {diff:.1f} pips.  "
                                 f"Structured value remains authoritative; "
                                 f"this is a diagnostic only.  Review "
                                 f"the narrative wording if the two are "
                                 f"intended to match."),
                    ))


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

def validate_assessment(*,
                         assessment: dict,
                         packet: dict | None = None,
                         analogues: list[dict] | None = None,
                         primary_decision: dict | None = None,
                         economic_context: dict | None = None,
                         ) -> list[dict]:
    """Return a list of ``QualityFlag.to_dict()`` records."""
    flags: list[QualityFlag] = []
    try:
        _validate_indicator_grounding(assessment, packet, flags)
        _validate_confidence_claims(assessment, flags)
        _validate_hard_bar_counts(assessment, packet, flags)
        _validate_analogue_outcomes(assessment, analogues, flags)
        _validate_opportunity_sides(assessment, flags)
        _validate_premature_confirmation(assessment, flags)
        _validate_unverified_event_references(
            assessment, economic_context, flags)
        _validate_directional_reconciliation(
            assessment, primary_decision, flags)
        # P2 — category validation + field-weight asymmetry.
        _validate_opportunity_category(
            assessment, economic_context, flags)
        # P3 — trigger_spec vs natural-language consistency.
        _validate_trigger_spec_consistency(assessment, flags)
        # Correction 2 — structured trade_proposal fields.
        _validate_structured_trade_proposal(assessment, flags)
        flags = _apply_field_weight_asymmetry(flags)
    except Exception as exc:  # defensive
        flags.append(QualityFlag(
            code="VALIDATOR_ERROR", severity="WARN", where=".",
            detail=f"{type(exc).__name__}: {exc}",
        ))
    return [f.to_dict() for f in flags]


# ---------------------------------------------------------------------
# Publication decision
# ---------------------------------------------------------------------

PUBLICATION_VALID = "VALID"
PUBLICATION_CAUTION = "CAUTION"
PUBLICATION_INVALID = "INVALID"


def decide_publication(flags: list[dict]) -> dict:
    """Collapse flag severities into a publication decision.

    Rules:
      * Any HIGH flag → INVALID. Opportunities MUST NOT be published
        as actionable; the raw assessment is still preserved for audit.
      * Only WARN flags → CAUTION. Publish, but the formatter must
        prepend a disclaimer and the opportunity labels are prefixed
        with "[CAUTION]".
      * No flags, or only INFO flags → VALID.

    Returns ``{"decision": ..., "reason": ..., "flag_codes": [...]}``.
    """
    codes = [str(f.get("code") or "") for f in flags]
    severities = [str(f.get("severity") or "").upper() for f in flags]
    if any(s == "HIGH" for s in severities):
        reason = (
            "assessment contains at least one HIGH quality flag; "
            "opportunity publication suppressed; raw assessment "
            "preserved in telemetry + scenarios_shadow.jsonl")
        return {
            "decision": PUBLICATION_INVALID,
            "reason": reason,
            "flag_codes": codes,
        }
    if any(s == "WARN" for s in severities):
        return {
            "decision": PUBLICATION_CAUTION,
            "reason": (
                "assessment contains WARN quality flags; publish with "
                "an explicit CAUTION disclaimer"),
            "flag_codes": codes,
        }
    return {
        "decision": PUBLICATION_VALID,
        "reason": "no quality flags",
        "flag_codes": [],
    }


__all__ = [
    "QualityFlag",
    "validate_assessment",
    "decide_publication",
    "PUBLICATION_VALID",
    "PUBLICATION_CAUTION",
    "PUBLICATION_INVALID",
]
