"""Scenario V2 → trade-recommendation + shadow-execution core.

PURE research module. Reads the append-only scenario / snapshot journals
and the M5 candle feed; produces structured trade proposals and shadow
position records. ABSOLUTELY NO BROKER CALLS: this file does not import
any IG, trades-api, autobot, or execution client.

Honest resolution rules (operator directive 2026-10-23):
  * The ``anticipated_sequence`` prices stored on the scenario row are
    the authoritative structural destinations — they are the AI's
    numeric commitments at creation time. The snapshot's ``level_map``
    is only consulted when the sequence lacks a price.
  * A structural target is NOT automatically a take-profit order. For
    a shadow trade proposal we require THREE independently resolvable
    numbers: entry trigger, protective stop, and target. If any one
    is missing we mark the proposal INCOMPLETE and emit WAIT —
    nothing is invented.
  * Publication gate is authoritative. INVALID or UNVALIDATED or an
    INVALIDATED/COMPLETED scenario state always yields WAIT regardless
    of other fields.
  * Shadow lifecycle uses ONLY M5 bars whose close is strictly after
    the proposal's generation timestamp. When stop and target could
    both have been touched in the same bar and the true intrabar
    order is unknown we record AMBIGUOUS, not a profit.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib
import re
from typing import Any

UTC = dt.timezone.utc


# =====================================================================
# Target / level resolver
# =====================================================================

# Known structural tokens. The scenario's `structural_target` or a
# sequence `label` often names a short code ("R00", "S1") decorated
# with free text ("S1 downside target", "NEAREST_00 (R00) retest").
# The resolver normalises the tokens.
_STOPWORDS = frozenset({
    "the", "and", "of", "a", "an", "for", "to", "retest", "target",
    "support", "resistance", "cluster", "zone", "secondary", "primary",
    "downside", "upside", "overshoot", "undershoot", "test",
    "the", "level", "between", "near",
})


def _tokens(label: str | None) -> set[str]:
    out: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9_+]+", (label or "")):
        t = raw.lower()
        if len(t) < 2 or t in _STOPWORDS:
            continue
        out.add(t)
    return out


def _price_from_sequence(label: str, sequence: list[dict],
                          role_hint: str | None = None) -> tuple[float | None, str]:
    """Resolve a target label to a price using the scenario's own
    anticipated_sequence. Returns (price, provenance)."""
    if not sequence:
        return (None, "sequence_empty")
    norm = (label or "").strip().lower()
    needle_tokens = _tokens(label)
    # 1) Exact match.
    for d in sequence:
        if (d.get("label") or "").strip().lower() == norm and d.get("price") is not None:
            return (d.get("price"), f"sequence_exact_label='{d.get('label')}'")
    # 2) Token containment: 'R00' is a token of 'NEAREST_00 (R00) retest'.
    for d in sequence:
        lab_tokens = _tokens(d.get("label"))
        if needle_tokens and lab_tokens and (needle_tokens & lab_tokens):
            if d.get("price") is not None:
                return (d.get("price"), f"sequence_token_match='{d.get('label')}'")
    # 3) Role fallback.
    if role_hint:
        for d in sequence:
            if (d.get("role") or "").lower() == role_hint and d.get("price") is not None:
                return (d.get("price"),
                        f"sequence_role='{role_hint}' label='{d.get('label')}'")
    return (None, "not_in_sequence")


def _price_from_level_map(label: str, snapshot: dict) -> tuple[float | None, str]:
    """Resolve a label to a price via the snapshot's authoritative level
    map (clusters / outer_pivots / other_levels / p_level)."""
    if not label:
        return (None, "no_label")
    lm = snapshot.get("level_map") or {}
    needle_tokens = _tokens(label)
    if not needle_tokens:
        return (None, "label_had_no_tokens")

    def _has_token(name: str, token_set: set[str]) -> bool:
        return bool(_tokens(name) & token_set)

    # Clusters: match on label or member_types.
    for c in lm.get("clusters") or []:
        c_label = c.get("label") or ""
        c_mem = ",".join(c.get("member_types") or [])
        if _has_token(c_label, needle_tokens) or _has_token(c_mem, needle_tokens):
            price = c.get("center_price") or c.get("p_price")
            if price is not None:
                return (price,
                        f"level_map_cluster='{c_label}'")
    # Outer pivots: type == label.
    for p in lm.get("outer_pivots") or []:
        ptype = (p.get("type") or "").upper()
        if ptype.lower() in needle_tokens:
            return (p.get("price"),
                    f"level_map_outer_pivot='{ptype}'")
    # Other levels.
    for p in lm.get("other_levels") or []:
        ptype = (p.get("type") or "").upper()
        if ptype.lower() in needle_tokens:
            return (p.get("price"),
                    f"level_map_other_level='{ptype}'")
    # p_level.
    plv = lm.get("p_level") or {}
    if ("pivot" in needle_tokens or "p" in needle_tokens):
        if plv.get("price") is not None:
            return (plv.get("price"), "level_map_p_level")
    return (None, "not_in_level_map")


def resolve_target(*, label: str | None, direction: str | None,
                     scenario_row: dict, snapshot: dict,
                     role_hint: str | None = None) -> dict:
    """Return a dict of (price, provenance, reason).

    Priority:
      1) anticipated_sequence exact label match (price field).
      2) anticipated_sequence token-match (price field).
      3) anticipated_sequence role fallback (first_target / reversal_zone).
      4) snapshot.level_map lookup.
    Returns ``{"price": None, "unavailable_reason": "..."}`` when
    nothing resolves. NEVER invents a numeric target.
    """
    sequence = scenario_row.get("anticipated_sequence") or []
    # First attempt with the requested label.
    price, prov = _price_from_sequence(label or "", sequence,
                                         role_hint=role_hint)
    if price is not None:
        return {"price": price, "provenance": prov,
                "label_resolved": label or ""}
    # If the label is empty/None, go directly to role_hint sequence lookup.
    if role_hint:
        for d in sequence:
            if (d.get("role") or "").lower() == role_hint and d.get("price") is not None:
                return {"price": d.get("price"),
                        "provenance": f"sequence_role='{role_hint}'",
                        "label_resolved": d.get("label") or ""}
    # Try the level_map.
    price, prov = _price_from_level_map(label or "", snapshot)
    if price is not None:
        return {"price": price, "provenance": prov,
                "label_resolved": label or ""}
    return {"price": None,
            "unavailable_reason": (
                "scenario sequence lacks a price for this label AND the "
                "snapshot level_map does not carry it either"),
            "label_resolved": label or ""}


def _pips_distance(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(abs(a - b), 1)


# =====================================================================
# Trade recommendation
# =====================================================================

READY = "READY"
INCOMPLETE = "INCOMPLETE"
CONDITIONAL = "CONDITIONAL"
HISTORICAL = "HISTORICAL"
SUPPRESSED = "SUPPRESSED"
STALE = "STALE"
EXPIRED_ENTRY = "EXPIRED_ENTRY"


# =====================================================================
# Temporal validation
# =====================================================================

# Match absolute UTC bar / event references the AI commonly uses:
#   "next bar (10:10 UTC)"
#   "11:00 UTC"
#   "at 13:45 UTC"
#   "by 08:30 UTC"
_HHMM_UTC_PATTERN = re.compile(
    r"\b([01]?\d|2[0-3]):([0-5]\d)\s*UTC\b", re.IGNORECASE)
# Match relative descriptors like "next bar" / "next M5 bar". We
# interpret these as the FIRST bar whose ts_open is strictly after
# gen_dt. They are legitimate (not expired) unless accompanied by a
# UTC time clamp — the HH:MM UTC pattern above handles the clamp.
_RELATIVE_NEXT_BAR = re.compile(
    r"\bnext\s+(?:bar|m5|candle)\b", re.IGNORECASE)
# News-release descriptors with an explicit UTC time are checked
# against the same HH:MM UTC regex. We only consider them "news"
# triggers when the surrounding phrase names a release.
_NEWS_TRIGGER = re.compile(
    r"\b(?:pmi|cpi|cbi|nfp|retail\s+sales|michigan|interest\s+rate|"
    r"non[- ]farm|unemployment|gdp|release|announcement)\b",
    re.IGNORECASE)


def check_temporal_validity(*, text: str | None,
                              generated_at_utc: str) -> dict:
    """Scan a confirmation / entry-condition narrative for timestamp
    references that are ALREADY in the past at proposal generation.

    Returns::
        {
          "status": "VALID" | "EXPIRED",
          "elapsed_references": [
             {"token": "10:10 UTC", "utc": "2026-10-23T10:10:00+00:00",
              "kind": "bar"|"news", "age_minutes": 154}
          ],
          "future_references": [...],   # UTC times still ahead of gen
          "relative_references": [...], # "next bar" without explicit UTC
          "reason": "..."
        }

    EXPIRED fires when:
      * The text names a specific "HH:MM UTC" (bar or news release)
        that is strictly earlier than ``generated_at_utc`` AND no
        future-dated bar/news reference also appears in the same
        text — i.e. the ONLY temporal anchors in the opportunity are
        all in the past.
      * The caller must then treat the proposal as INCOMPLETE /
        EXPIRED_ENTRY and recommend WAIT.
    VALID fires when every explicit UTC timestamp is ≥ generated_at_utc
    OR no explicit UTC references appear (relative "next bar" only).
    """
    if not text:
        return {"status": "VALID", "elapsed_references": [],
                "future_references": [], "relative_references": [],
                "reason": "no text to validate"}
    try:
        gen_dt = dt.datetime.fromisoformat(
            generated_at_utc.replace("Z", "+00:00"))
        if gen_dt.tzinfo is None:
            gen_dt = gen_dt.replace(tzinfo=UTC)
    except (TypeError, ValueError, AttributeError):
        return {"status": "VALID", "elapsed_references": [],
                "future_references": [], "relative_references": [],
                "reason": "unparsable generated_at_utc"}

    gen_date = gen_dt.date()
    elapsed: list[dict] = []
    future: list[dict] = []
    for m in _HHMM_UTC_PATTERN.finditer(text):
        hh = int(m.group(1))
        mm = int(m.group(2))
        # Anchor the HH:MM on the proposal's UTC date. A "10:10 UTC"
        # reference in a proposal generated at 12:44 UTC is anchored
        # at 10:10 UTC on the same date → 2 h in the past → EXPIRED.
        anchor = dt.datetime(gen_date.year, gen_date.month, gen_date.day,
                               hh, mm, tzinfo=UTC)
        # Determine kind by the surrounding context (news vs bar).
        start = max(0, m.start() - 40)
        end   = min(len(text), m.end() + 40)
        context = text[start: end]
        kind = "news" if _NEWS_TRIGGER.search(context) else "bar"
        rec = {"token": m.group(0),
               "utc": anchor.isoformat(),
               "kind": kind,
               "context_excerpt": context.strip()[:160]}
        if anchor < gen_dt:
            rec["age_minutes"] = round(
                (gen_dt - anchor).total_seconds() / 60.0, 1)
            elapsed.append(rec)
        else:
            rec["minutes_until"] = round(
                (anchor - gen_dt).total_seconds() / 60.0, 1)
            future.append(rec)

    relative = [m.group(0) for m in _RELATIVE_NEXT_BAR.finditer(text)]

    if elapsed and not future:
        reason = (
            f"opportunity text references {len(elapsed)} time anchor(s) "
            f"all in the past at proposal generation: " +
            ", ".join(f"{r['token']} ({r['age_minutes']} min ago, {r['kind']})"
                      for r in elapsed[:3])
        )
        return {"status": "EXPIRED",
                "elapsed_references": elapsed,
                "future_references": [],
                "relative_references": relative,
                "reason": reason}
    return {"status": "VALID",
            "elapsed_references": elapsed,
            "future_references": future,
            "relative_references": relative,
            "reason": ("some anchors expired but future anchors present"
                       if elapsed else "all anchors are future or relative")}


def _extract_stop_price_from_text(text: str | None,
                                   direction: str) -> tuple[float | None, str]:
    """Pull a numeric stop from the invalidation narrative, iff the AI
    explicitly stated a price with the correct side.

    Supported forms (SELL stop MUST sit ABOVE entry; BUY mirrors):
      * "close above 13385"             ← verbal
      * "above 13390 on 2+ bars"
      * ">13390 on next 1-2 bars"       ← literal comparator
      * ">=13390"
      * "closes >13390"
      * "above R00 (13400)"              ← level-labelled
      * "close >R00 (13400)"

    Still conservative: a direction-correct comparator OR direction-
    correct side word must appear; the number must follow it within
    60 characters. We never invent a stop.
    """
    if not text:
        return (None, "no_text")
    direction = (direction or "").upper()
    if direction == "SELL":
        side_word = "above"
        # Verbal: 'close above NNNN', '... above R00 (NNNN)'
        verbal = re.compile(
            r"\b(?:close(?:s)?|closes?\s+and\s+(?:holds?|sustains?))?\s*above\b",
            re.IGNORECASE,
        )
        # Comparator: '>13390' or 'closes >13390' or 'close >R00 (13400)'
        comp = re.compile(
            r"(?:>=?)(?=\s*(?:R\d|BB_?U|SWING_?H|PDH|R00|NEAREST|P|PIVOT|\d))",
            re.IGNORECASE,
        )
    elif direction == "BUY":
        side_word = "below"
        verbal = re.compile(
            r"\b(?:close(?:s)?|closes?\s+and\s+(?:holds?|sustains?))?\s*below\b",
            re.IGNORECASE,
        )
        comp = re.compile(
            r"(?:<=?)(?=\s*(?:S\d|BB_?L|SWING_?L|PDL|R00|NEAREST|P|PIVOT|\d))",
            re.IGNORECASE,
        )
    else:
        return (None, "no_direction")

    for pat, kind in ((verbal, side_word), (comp, "comparator")):
        for m in pat.finditer(text):
            window = text[m.end(): m.end() + 60]
            n = re.search(r"(\d{4,6}(?:\.\d+)?)", window)
            if n:
                try:
                    return (float(n.group(1)),
                            f"invalidation_text:{kind} {n.group(1)}")
                except ValueError:
                    continue
    return (None, f"no_price_after_'{side_word}'_or_comparator_in_invalidation")


def _extract_stop_price_from_invalidation_list(
        invalidation_conditions: list[str] | None,
        direction: str) -> tuple[float | None, str]:
    """Preferred path — walk the structured invalidation_conditions
    list that the AI emits, element by element. The first element
    that yields a side-correct numeric stop wins. This is more
    reliable than concatenating prose and running one regex because
    each list item is already a self-contained invalidation clause.
    """
    if not invalidation_conditions:
        return (None, "no_invalidation_conditions")
    for i, cond in enumerate(invalidation_conditions):
        price, prov = _extract_stop_price_from_text(str(cond), direction)
        if price is not None:
            return (price,
                    f"invalidation_conditions[{i}] {prov}")
    return (None, "no_side_correct_price_in_invalidation_conditions")


def _extract_entry_price_from_text(text: str | None,
                                     direction: str) -> tuple[float | None, str]:
    """Return the FIRST numeric price that appears within 60 characters
    of a direction-correct trigger phrase.

    Supported shapes (SELL direction; BUY mirrors with 'above' / '>'):
      * "breaks below 13371.25"
      * "closes below 13371.25"
      * "break and closes below S1 (13365.23)"
      * "closes <S1 (13365.23)"           ← literal less-than symbol
      * "closes <13365.23"
      * "sustained close <= 13365"
      * "<13365.23 on next 1-2 bars"       ← bare prefix form (direction-aware)

    The parser is still conservative: the trigger token (word OR comparator)
    MUST be present within the sentence, and the number MUST appear within
    60 characters AFTER it. Nothing is invented, and the original
    required_price_behaviour text is preserved verbatim upstream.
    """
    if not text:
        return (None, "no_text")
    direction = (direction or "").upper()
    if direction == "SELL":
        # Match either a verbal trigger ("closes/break(s) below") OR the
        # literal comparator "<" (which the live AI uses in the 2026-10-23
        # revisions). The lookbehind on the comparator rejects "<=" so we
        # don't double-count; both forms are then checked below.
        trigger_pat = re.compile(
            r"(?:\b(?:breaks?|close(?:s)?|holds?|sustains?)"
            r"\s+(?:and\s+(?:closes?|breaks?)\s+)?(?:below|<=?))"
            r"|(?:(?:closes?|close)\s*<=?)"
            r"|(?:<=?(?=\s*(?:S\d|BB_?L|SWING_?L|PDL|R00|NEAREST|P|PIVOT|\d)))",
            re.IGNORECASE,
        )
        side_word = "break-below"
    elif direction == "BUY":
        trigger_pat = re.compile(
            r"(?:\b(?:breaks?|close(?:s)?|holds?|sustains?)"
            r"\s+(?:and\s+(?:closes?|breaks?)\s+)?(?:above|>=?))"
            r"|(?:(?:closes?|close)\s*>=?)"
            r"|(?:>=?(?=\s*(?:R\d|BB_?U|SWING_?H|PDH|R00|NEAREST|P|PIVOT|\d)))",
            re.IGNORECASE,
        )
        side_word = "break-above"
    else:
        return (None, "no_direction")
    for m in trigger_pat.finditer(text):
        window = text[m.end(): m.end() + 60]
        # First numeric in the window; may be preceded by a level name
        # like 'S1 (' / 'BB_L (' / 'R00 ('.
        n = re.search(r"(\d{4,6}(?:\.\d+)?)", window)
        if n:
            try:
                return (float(n.group(1)),
                        f"required_behaviour:{side_word} {n.group(1)}")
            except ValueError:
                continue
    return (None, f"no_price_near_'{side_word}'_in_required_behaviour")


def _primary_and_reversal_opps(row: dict) -> tuple[dict | None, dict | None]:
    """From the scenario's opportunities list, pick:
      * primary = first opportunity with direction in {BUY, SELL} and
        kind in {INITIAL_DIRECTIONAL, SUBSEQUENT_REVERSAL} (ignores WAIT).
      * reversal = first opportunity whose kind is SUBSEQUENT_REVERSAL
        OR whose direction is opposite to the primary.
    Both may be None.
    """
    directional = [o for o in (row.get("opportunities") or [])
                   if isinstance(o, dict)
                   and (o.get("direction") or "").upper() in ("BUY", "SELL")]
    if not directional:
        return (None, None)
    primary = directional[0]
    reversal = next(
        (o for o in directional[1:]
         if (o.get("kind") or "").upper() == "SUBSEQUENT_REVERSAL"
         or (o.get("direction") or "").upper() !=
            (primary.get("direction") or "").upper()),
        None,
    )
    return (primary, reversal)


def _market_data_fresh(snapshot: dict, now: dt.datetime) -> tuple[bool, str, int | None]:
    """Return (is_fresh, status_label, age_s). FRESH if bar close is
    within 180 s of now; AGEING ≤ 600 s; STALE > 600 s."""
    bar_ts = snapshot.get("bar_ts_utc") if snapshot else None
    if not bar_ts:
        return (False, "UNKNOWN", None)
    try:
        bar_open = dt.datetime.fromisoformat(bar_ts.replace("Z", "+00:00"))
    except ValueError:
        return (False, "UNKNOWN", None)
    close = bar_open + dt.timedelta(seconds=300)
    age = max(0, int((now - close).total_seconds()))
    if age <= 180:
        return (True, "FRESH", age)
    if age <= 600:
        return (True, "AGEING", age)
    return (False, "STALE", age)


def build_trade_recommendation(*,
                                 scenario_row: dict,
                                 snapshot: dict,
                                 primary_decision: dict,
                                 now_utc: dt.datetime | None = None,
                                 ) -> dict:
    """Compute a structured trade recommendation.

    Returns a dict of shape::
        {
          "recommendation": "BUY" | "SELL" | "WAIT",
          "readiness": "READY" | "INCOMPLETE" | "CONDITIONAL" |
                        "HISTORICAL" | "SUPPRESSED" | "STALE",
          "reason": "...",
          "market_bias": "BUY" | "SELL" | "NEUTRAL",
          "scenario": {...},
          "current_price": float | None,
          "entry": {"price": ..., "trigger": ..., "provenance": ...},
          "stop":  {"price": ..., "provenance": ...},
          "target": {"label": ..., "price": ..., "provenance": ...},
          "subsequent_reversal": {...},
          "risk_pips": float | None,
          "reward_pips": float | None,
          "rr": float | None,
          "confirmation_evidence": [...],
          "invalidation_conditions": [...],
          "economic_context_summary": {...},
          "publication": {...},
          "market_data_status": "FRESH" | "AGEING" | "STALE" | "UNKNOWN",
          "generated_at_utc": "...",
        }
    """
    now = now_utc or dt.datetime.now(UTC)
    bias_primary = (primary_decision.get("direction") or "").upper() or "NEUTRAL"

    # Publication gate ---------------------------------------------------
    pub = scenario_row.get("publication_decision") or {}
    pub_decision_raw = (pub.get("decision") or "").upper()
    if pub_decision_raw not in {"VALID", "CAUTION", "INVALID"}:
        pub_decision = "UNVALIDATED"
    else:
        pub_decision = pub_decision_raw
    publishable = pub_decision in ("VALID", "CAUTION")

    # Current price + authoritative candle stream ------------------------
    # Both are read from the primary observer's snapshot — the SAME
    # stream the AI consumed when it produced the scenario, so a bar
    # that reaches the AI is immediately visible to the recommender.
    close_price = None
    inter = snapshot.get("interactions") or []
    if inter:
        close_price = (inter[0].get("raw") or {}).get("close")

    # Freshness check ----------------------------------------------------
    md_fresh, md_status, md_age = _market_data_fresh(snapshot, now)

    # Resolve the primary + reversal opps and their targets --------------
    primary_opp, reversal_opp = _primary_and_reversal_opps(scenario_row)
    direction = (primary_opp.get("direction") or "").upper() if primary_opp else "NEUTRAL"
    target = resolve_target(
        label=(primary_opp or {}).get("structural_target"),
        direction=direction,
        scenario_row=scenario_row,
        snapshot=snapshot,
        role_hint="first_target",
    ) if primary_opp else {"price": None,
                             "unavailable_reason": "no_directional_opportunity"}
    rev_target = resolve_target(
        label=(reversal_opp or {}).get("structural_target"),
        direction=(reversal_opp or {}).get("direction"),
        scenario_row=scenario_row,
        snapshot=snapshot,
        role_hint="reversal_zone",
    ) if reversal_opp else {"price": None, "unavailable_reason": "no_reversal_opp"}

    # Entry trigger + stop extraction ------------------------------------
    required_price_behaviour = (primary_opp or {}).get("required_price_behaviour") or ""

    # Preferred: structured trade_proposal field on the scenario row
    # (new tool-call schema). Falls back to the prose parser when the
    # AI did not fill the structured block.
    structured = (scenario_row.get("trade_proposal") or
                   (primary_opp or {}).get("trade_proposal") or {})
    structured_dir = (structured.get("direction") or "").upper() or None
    # Correction 2 — the structured trade_proposal fields, when
    # present, are AUTHORITATIVE.  Prefer them over narrative regex
    # extraction so misparsed natural-language targets cannot slip
    # through.  All three fields (entry/stop/target) must be present
    # for the structured path to be taken; otherwise fall back to
    # the pre-existing narrative extraction (and the quality gate's
    # MISSING_STRUCTURED_PROPOSAL WARN keeps the dashboard visible).
    use_structured = (
        structured_dir == direction and
        structured.get("entry_price") is not None and
        structured.get("stop_price") is not None and
        structured.get("target_price") is not None
    )

    if use_structured:
        entry_price = float(structured["entry_price"])
        entry_prov = f"trade_proposal.entry_price={entry_price}"
        stop_price = float(structured["stop_price"])
        stop_prov = f"trade_proposal.stop_price={stop_price}"
        # Target also authoritative; override whatever resolve_target
        # may have found in the sequence / level_map.  Attach a
        # provenance tag so the dashboard can see the source.
        try:
            structured_target = float(structured["target_price"])
            target = {
                **(target or {}),
                "price": structured_target,
                "provenance": f"trade_proposal.target_price={structured_target}",
            }
        except (TypeError, ValueError):
            pass
    else:
        entry_price, entry_prov = _extract_entry_price_from_text(
            required_price_behaviour, direction)
        invalidation_list = (
            (scenario_row.get("evidence") or {}).get(
                "invalidation_conditions") or [])
        stop_price, stop_prov = _extract_stop_price_from_invalidation_list(
            invalidation_list, direction)
        if stop_price is None:
            # Secondary fallback — scan the opportunity text itself.
            stop_price, stop_prov = _extract_stop_price_from_text(
                required_price_behaviour, direction)

    # Compute distances --------------------------------------------------
    # ``distance_to_target_pips`` is an informational metric from the
    # current market price (what the operator sees on the dashboard).
    # ``reward_pips`` is the EXPECTED trade reward, measurable ONLY
    # once an entry has been resolved from the scenario text.
    # ``risk_pips`` + ``rr`` require all three independently resolved
    # (entry, stop, target). Falling back to current price for reward
    # when no entry exists is dishonest and was removed.
    distance_to_target_pips = _pips_distance(target.get("price"), close_price)
    reward_pips = (_pips_distance(target.get("price"), entry_price)
                   if entry_price is not None else None)
    risk_pips = (_pips_distance(stop_price, entry_price)
                 if (entry_price is not None and stop_price is not None)
                 else None)
    rr = None
    if (reward_pips is not None and risk_pips is not None
            and risk_pips > 0):
        rr = round(reward_pips / risk_pips, 2)

    # Decide readiness ---------------------------------------------------
    scen_state = (scenario_row.get("state") or "").upper()

    def _wait(readiness, reason):
        return {
            "recommendation": "WAIT",
            "readiness": readiness,
            "reason": reason,
        }

    base_payload = {
        "scenario": {
            "scenario_id": scenario_row.get("scenario_id"),
            "revision_idx": scenario_row.get("revision_idx"),
            "state": scenario_row.get("state"),
            "bar_ts_utc": scenario_row.get("bar_ts_utc"),
            "generated_at_utc": scenario_row.get("generated_at_utc")
                                  or scenario_row.get("revised_at_utc"),
        },
        "market_bias": bias_primary,
        "primary": {
            "hypothesis": primary_decision.get("hypothesis"),
            "direction": primary_decision.get("direction"),
            "generated_at_utc": primary_decision.get("evaluated_at_utc"),
        },
        "current_price": close_price,
        "market_data_status": md_status,
        "market_data_age_seconds": md_age,
        "direction": direction,
        "entry": {
            "price": entry_price,
            "trigger": required_price_behaviour[:300] if required_price_behaviour else None,
            "provenance": entry_prov,
        },
        "stop": {
            "price": stop_price,
            "provenance": stop_prov,
        },
        "target": {
            "label": (primary_opp or {}).get("structural_target") or
                      target.get("label_resolved") or "",
            "price": target.get("price"),
            "provenance": target.get("provenance",
                                       target.get("unavailable_reason")),
            "pips_from_market": _pips_distance(target.get("price"), close_price),
        },
        "subsequent_reversal": {
            "direction": (reversal_opp or {}).get("direction"),
            "kind": (reversal_opp or {}).get("kind"),
            "label": (reversal_opp or {}).get("structural_target") or
                       rev_target.get("label_resolved") or "",
            "price": rev_target.get("price"),
            "provenance": rev_target.get("provenance",
                                           rev_target.get("unavailable_reason")),
            "pips_from_market": _pips_distance(rev_target.get("price"), close_price),
        },
        "distance_to_target_pips": distance_to_target_pips,
        "reward_pips": reward_pips,
        "risk_pips": risk_pips,
        "rr": rr,
        "confirmation_evidence": list(
            scenario_row.get("confirmation_criteria") or []),
        "invalidation_conditions": list(
            (scenario_row.get("evidence") or {}).get("invalidation_conditions") or []),
        "economic_context_summary": {
            k: len((scenario_row.get("economic_context") or {}).get(k) or [])
            for k in ("scheduled", "released", "expired", "unverified", "surprises")
        },
        "publication": {
            "decision": pub_decision,
            "publishable": publishable,
            "flag_codes": pub.get("flag_codes") or [],
            "reason": pub.get("reason") or "",
        },
        "execution_mode": "SHADOW_ONLY",
        "generated_at_utc": now.isoformat(),
    }

    # Hard gates ---------------------------------------------------------
    if scen_state in {"INVALIDATED", "COMPLETED"}:
        base_payload.update(_wait(SUPPRESSED,
                                   f"scenario state is {scen_state}"))
        return base_payload
    if pub_decision == "INVALID":
        base_payload.update(_wait(
            SUPPRESSED,
            "NO AUTHORISED TRADE — scenario publication_decision=INVALID "
            f"(flags: {', '.join(pub.get('flag_codes') or []) or 'unspecified'})"))
        return base_payload
    if pub_decision == "UNVALIDATED":
        base_payload.update(_wait(
            HISTORICAL,
            "WAIT — historical scenario revision without a validated "
            "publication_decision; not eligible for execution"))
        return base_payload
    if not direction:
        base_payload.update(_wait(
            INCOMPLETE,
            "no directional opportunity surfaced on the latest revision"))
        return base_payload
    if md_status == "STALE":
        base_payload.update(_wait(
            STALE,
            f"market-data stale ({md_age}s since last bar close)"))
        return base_payload

    missing: list[str] = []
    if target.get("price") is None:
        missing.append("target")
    if entry_price is None:
        missing.append("entry")
    if stop_price is None:
        missing.append("stop")
    if missing:
        base_payload.update(_wait(
            INCOMPLETE,
            f"INCOMPLETE — unresolved fields: {', '.join(missing)}; "
            f"recommend WAIT until the scenario specifies them"))
        return base_payload

    # Temporal validity — reject entry triggers whose explicit UTC
    # anchors are all in the past at proposal generation.
    gen_ts = scenario_row.get("generated_at_utc") or scenario_row.get("revised_at_utc") or ""
    temp = check_temporal_validity(
        text=required_price_behaviour, generated_at_utc=gen_ts)
    base_payload["temporal_validity"] = temp
    if temp.get("status") == "EXPIRED":
        base_payload.update(_wait(
            EXPIRED_ENTRY,
            f"ENTRY EXPIRED — {temp.get('reason')}"))
        return base_payload

    # Entry/stop/target geometry — the entry extractor already matches
    # on direction-correct break-below/above and the stop extractor
    # requires the opposite side word; still, assert the final numbers
    # agree with the primary direction so no reversal opp can inherit
    # the primary trade's stop or target.
    tp = target.get("price")
    geom_ok = True
    geom_reason = ""
    if direction == "SELL":
        if not (stop_price > entry_price > tp):
            geom_ok = False
            geom_reason = (f"SELL geometry violated: expect stop > entry > "
                            f"target, got stop={stop_price}, "
                            f"entry={entry_price}, target={tp}")
    elif direction == "BUY":
        if not (stop_price < entry_price < tp):
            geom_ok = False
            geom_reason = (f"BUY geometry violated: expect stop < entry < "
                            f"target, got stop={stop_price}, "
                            f"entry={entry_price}, target={tp}")
    base_payload["geometry_ok"] = geom_ok
    base_payload["geometry_reason"] = geom_reason
    if not geom_ok:
        base_payload.update(_wait(
            INCOMPLETE,
            f"INCOMPLETE — {geom_reason}"))
        return base_payload

    # Pre-entry invalidation check: has the latest completed-bar close
    # already crossed the stop? If so, the proposal is dead on arrival.
    if close_price is not None:
        if direction == "SELL" and close_price >= stop_price:
            base_payload.update(_wait(
                INCOMPLETE,
                f"INCOMPLETE — current close ({close_price}) already at/above "
                f"invalidation ({stop_price}); scenario invalidated pre-entry"))
            return base_payload
        if direction == "BUY" and close_price <= stop_price:
            base_payload.update(_wait(
                INCOMPLETE,
                f"INCOMPLETE — current close ({close_price}) already at/below "
                f"invalidation ({stop_price}); scenario invalidated pre-entry"))
            return base_payload

    # Reversal-direction target must NOT equal the primary target
    # (prevents the SUBSEQUENT_REVERSAL opportunity from inheriting the
    # initial trade's take-profit).
    rev_price = rev_target.get("price")
    if rev_price is not None and tp is not None and abs(rev_price - tp) < 1e-6:
        # Clear the reversal field so downstream never shows the primary
        # TP as the reversal destination; this is a cosmetic cleanup,
        # not a hard failure.
        base_payload["subsequent_reversal"]["price"] = None
        base_payload["subsequent_reversal"]["provenance"] = (
            "cleared_duplicate_of_primary_target")

    # Correction 1 (2026-10-28) — scenario_v2 CAUTION → WAIT trap fix.
    #
    # The previous code at this point returned WAIT/CONDITIONAL
    # unconditionally for every pub_decision == "CAUTION".  P2's
    # field-weight asymmetry demotes narrative-only
    # UNVERIFIED_EVENT_AS_CATALYST (and similar informational flags)
    # to WARN → CAUTION, with the explicit design intent that the
    # scenario remain *publishable with a disclaimer*.  The previous
    # WAIT path nullified that intent.
    #
    # Correction 1 lets CAUTION fall through to the terminal
    # recommendation emit — the direction is published with
    # ``readiness = CONDITIONAL`` and the attached disclaimer /
    # flag codes, so the operator sees "BUY (CAUTION — ...)"
    # instead of a bare WAIT.
    #
    # CAUTION DOES NOT BYPASS ANY HARD SAFETY GATE: every
    # pre-existing check above (scenario INVALIDATED/COMPLETED,
    # publication_decision == INVALID, missing entry/stop/target,
    # geometry violation, stale market data, EXPIRED entry,
    # pre-entry invalidation) already returned WAIT with the
    # appropriate ``readiness`` before this block.  Correction 1
    # only unblocks the FINAL step for a CAUTION scenario that
    # has already satisfied all earlier gates.
    is_caution = pub_decision == "CAUTION"
    if is_caution:
        caution_flag_codes = list(pub.get("flag_codes") or [])
        caution_disclaimer = (
            pub.get("reason")
            or "scenario is CAUTION — publishable with disclaimer")
        base_payload.update({
            "recommendation": direction,
            "readiness": CONDITIONAL,
            "caution_flag_codes": caution_flag_codes,
            "caution_disclaimer": caution_disclaimer,
            "reason": (
                f"CAUTION {direction} — fully specified entry/stop/target "
                f"and freshness/geometry/invalidation checks all passed; "
                f"disclaimer flags: "
                f"{', '.join(caution_flag_codes) or 'unspecified'}"),
        })
        return base_payload

    # Fully specified AND VALID -----------------------------------------
    base_payload.update({
        "recommendation": direction,
        "readiness": READY,
        "reason": "VALID scenario with resolved entry, stop and target",
    })
    return base_payload


__all__ = [
    "build_trade_recommendation",
    "resolve_target",
    "check_temporal_validity",
    # Readiness enum values (strings) are exported as module constants.
    "READY", "INCOMPLETE", "CONDITIONAL", "HISTORICAL",
    "SUPPRESSED", "STALE", "EXPIRED_ENTRY",
]
