"""Live GBPUSD market observer agent — news-enriched Anthropic variant.

This file ADDS verified macro news context to the existing, running
Anthropic-adapted observer. It does NOT replace the running agent, and
is intentionally a sibling file so operator can review and perform a
clean switchover at a session boundary.

Diff versus /mnt/.../research/live_obs/agent/live_market_observer_agent.py:
  * imports market_observer_macro and injects a `macro_context` block
    into every packet before AI inference.
  * SYSTEM prompt grows one paragraph instructing the model to treat
    macro_context strictly as point-in-time facts, to distinguish
    scheduled vs. released, and to reason about competing bullish /
    bearish scenarios without asserting a certain GBPUSD direction.
  * New CLI flags:
      --macro-source   {host_live,operator_jsonl,both}  default host_live
      --macro-events   path to operator-approved verified_events.jsonl
                       (required when source is operator_jsonl / both)
      --news-state     if set, also fetch the approved localhost
                       /news-state endpoint for state-label context.
  * Macro failures are LOGGED to errors.jsonl but DO NOT fail the bar —
    the observer continues to emit a decision with `macro_context.status
    = UNAVAILABLE`, exactly as the upstream `missing_streams` discipline
    handles level_map / nms absences.

Hard contract preserved from the running agent:
  * No AutoBot imports, no broker calls, no systemd / service calls.
  * Fails CLOSED on missing ANTHROPIC_API_KEY.
  * Output path MUST be outside the production root.
  * Validates every LLM response (hypothesis, direction, level_id,
    evidence lists).
  * Stamps execution_authority=NONE on every decision.
  * --once or bounded --end-utc required.
  * 10-minute-from-close freshness ceiling on LOI v6 bars.
  * GBPUSD-only; nested raw.bar_ts; qm computed_at; undated LOI file.

NEVER permits data published AFTER a candle's observation time to
influence that earlier assessment — the macro adapter is strictly
asof-gated and the decisions file is append-only.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
from zoneinfo import ZoneInfo

# Sibling module (same directory). We extend sys.path so this runs under
# the same invocation convention operator already uses.
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from market_observer_macro import build_macro_packet  # noqa: E402

NOMINATED = {6, 7, 8, 10, 11, 12, 13, 14, 16}
STATES = {"NO_OPPORTUNITY", "WATCH_REJECTION", "WATCH_BREAKOUT",
          "OPPORTUNITY_TO_REVIEW", "INVALIDATED"}

SYSTEM = (
    "You are an observational GBPUSD market analyst, NOT a trading system.\n"
    "Interpret the developing market as an experienced, sceptical observer would.\n"
    "Pay special attention to MULTIPLE TESTS of the SAME structural level:\n"
    "differences in penetration, rejection, pace, retests, acceptance and failure.\n"
    "Use ONLY the provided timestamped packet and previous signed observations.\n"
    "Distinguish genuine new evidence from stale or unchanged observations.\n"
    "Never invent candles, news, price levels, trades, P&L or confidence scores.\n"
    "Use macro_context only for timestamped verified events; distinguish\n"
    "scheduled, consensus, forecast and released actual. Never assert a speech\n"
    "implies a rate change without an explicit verified basis. Explain competing\n"
    "bullish and bearish macro scenarios WITHOUT asserting a certain GBPUSD\n"
    "direction; missing fields mean UNKNOWN, not an inferred value. The host's\n"
    "feed does NOT carry speaker identity, speech subject, or revised previous\n"
    "values; those appear as absent_fields and must not be fabricated.\n"
    "Abstain when ambiguous. Repeated testing can lead to breakout OR rejection.\n"
    "HYPOTHESIS LIFECYCLE DISCIPLINE (C3, 2026-10-29).\n"
    " 7. RECONSIDER WHEN TRIGGERED. The packet includes "
    "`reassessment_triggers[level_id]` with:\n"
    "    * `trigger_fired` — boolean, true when deterministic rules detect "
    "material contradictory evidence against the prior hypothesis on this "
    "level;\n"
    "    * `reasons` — short list describing which rules fired;\n"
    "    * `age_bars` — number of prior consecutive bars with the same "
    "(hypothesis, direction) on this level;\n"
    "    * `prior_invalidation_delta` — your previous invalidation conditions "
    "that are now FIRED or PARTIAL per deterministic matching.\n"
    "  When trigger_fired=true for the level you are observing, you MUST "
    "explicitly address each reason in `change_since_previous` AND state "
    "the lifecycle status of your prior hypothesis using the new optional "
    "field `hypothesis_status` with one of: ACTIVE (reasons do not apply), "
    "CHALLENGED (reasons apply, direction remains unresolved), INVALIDATED "
    "(prior invalidation conditions have fired), RESOLVED (anticipated "
    "market event has occurred), EXPIRED (observation objective lapsed).\n"
    "  Do NOT continue a hypothesis solely because the previous label was "
    "the same. Repeating `WATCH_REJECTION` while narrating contradictory "
    "evidence is label-anchoring and is prohibited.\n"
    " 8. UNRESOLVED DIRECTION IS A VALID OUTCOME. If the prior hypothesis "
    "is challenged or invalidated but no new direction is yet confirmed, "
    "emit `hypothesis=NO_OPPORTUNITY` and `direction=null`. This signals "
    "that the previous expectation is no longer supported. Do NOT flip to "
    "the opposite direction without independent confirming evidence (NMS "
    "flip in the new direction + consecutive_closes_beyond + distance). "
    "Invalidating a SELL hypothesis does NOT authorise a BUY hypothesis.\n"
    " 9. PREVIOUS HYPOTHESIS IS CONTEXT, NOT EVIDENCE. Never cite "
    "`previous_assessments[level].hypothesis` as independent supporting "
    "evidence. The prior conclusion is a historical interpretation of "
    "earlier evidence, not a fact. New supporting evidence must come from "
    "the current packet (interactions, nms, macro_context, level_map).\n"
    "OUTPUT STRICT BUDGET: narrative <= 400 chars; each evidence/invalidation "
    "list item <= 120 chars; cap each list at 6 items; change_since_previous "
    "<= 220 chars; uncertainty <= 180 chars; macro_scenarios items <= 180 chars "
    "and cap at 4. Prefer concise, specific field pointers (e.g. "
    "\"interactions[0].bars_since_init=9\") over prose paraphrase.\n"
    "You MUST call the return_observation tool exactly once. Do NOT reply with "
    "free-form text or markdown fences. Returning any other structure "
    "violates the contract and the response will be discarded."
)


def load_env_once(env_path: pathlib.Path) -> None:
    """Load KEY=VALUE pairs from .env into os.environ if not already set.

    Never prints values. Only populates the few keys we actually need."""
    if not env_path.exists():
        return
    try:
        text = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    wanted = {"ANTHROPIC_API_KEY"}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name in wanted and name not in os.environ:
            v = value.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            os.environ[name] = v


def last_rows(path: pathlib.Path, limit: int = 300) -> list[dict]:
    """Read-only recent completed rows. Missing/invalid files fail closed."""
    from collections import deque
    if not path.exists():
        return []
    with path.open("r", encoding="utf8") as f:
        tail = deque(f, maxlen=limit)
    rows: list[dict] = []
    for line in tail:
        try:
            rows.append(json.loads(line))
        except (ValueError, TypeError):
            continue
    return rows


def timestamp(v):
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v, dt.timezone.utc)
    if not isinstance(v, str):
        return None
    try:
        x = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return x.replace(tzinfo=dt.timezone.utc) if x.tzinfo is None else x.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def bar_time(row):
    """Verified-schema timestamp extractor.

    Order:
      1. Nested LOI v6 raw.bar_ts.
      2. Top-level bar_ts / ts / timestamp / bar_ts_utc.
      3. qm_level_map computed_at.
    """
    raw = row.get("raw")
    if isinstance(raw, dict):
        for key in ("bar_ts", "ts"):
            if key in raw:
                t = timestamp(raw[key])
                if t is not None:
                    return t
    for key in ("bar_ts", "ts", "timestamp", "bar_ts_utc", "computed_at"):
        if key in row:
            t = timestamp(row[key])
            if t is not None:
                return t
    return None


def key_for(row):
    return str(row.get("interaction_id") or row.get("level_id") or "")


def resolve_loi_path(log_dir: pathlib.Path, now: dt.datetime) -> pathlib.Path:
    """Prefer the live undated LOI v6 file; fall back to today's dated file."""
    live = log_dir / "level_interaction_observer_v6.jsonl"
    if live.exists():
        return live
    return log_dir / ("level_interaction_observer_v6.jsonl-" + now.strftime("%Y%m%d"))


def packet(root: pathlib.Path, now: dt.datetime, prior: dict,
            history: list[dict] | None = None) -> dict:
    log = root / "logs"
    loi_path = resolve_loi_path(log, now)
    loi = last_rows(loi_path, 1200)
    qm = last_rows(log / "qm_level_map.jsonl", 300)
    nms = last_rows(log / "normal_state_journal.jsonl", 150)

    loi_gbp = [x for x in loi if x.get("pair") == "GBPUSD"]
    qm_gbp = [x for x in qm if x.get("symbol") == "GBPUSD"]
    nms_gbp = [x for x in nms if x.get("symbol") == "GBPUSD"]

    BAR_LENGTH_SECONDS = 300
    FRESHNESS_FROM_CLOSE_SECONDS = 600
    latest = max((bar_time(x) for x in loi_gbp if bar_time(x) and bar_time(x) <= now),
                 default=None)
    if latest is None:
        raise RuntimeError(f"LOI feed missing GBPUSD bars (path={loi_path})")
    bar_close = latest + dt.timedelta(seconds=BAR_LENGTH_SECONDS)
    if bar_close > now:
        raise RuntimeError(
            f"LOI feed references an unclosed bar: bar_close={bar_close.isoformat()} > now")
    age_from_close_s = (now - bar_close).total_seconds()
    if age_from_close_s > FRESHNESS_FROM_CLOSE_SECONDS:
        raise RuntimeError(
            f"LOI feed stale: GBPUSD latest bar start {latest.isoformat()}, "
            f"close {bar_close.isoformat()}, age from close {age_from_close_s:.0f}s "
            f"(freshness ceiling {FRESHNESS_FROM_CLOSE_SECONDS}s)")
    age_s = (now - latest).total_seconds()

    matching = [x for x in loi_gbp if bar_time(x) == latest and key_for(x)]
    if not matching:
        raise RuntimeError("No identifiable GBPUSD LOI interactions at latest bar")
    if len(matching) > 30:
        matching = matching[-30:]

    def nearest(rows: list[dict], window_seconds: int = 900):
        candidates = []
        for x in rows:
            t = bar_time(x)
            if t is None or t > latest:
                continue
            if (latest - t).total_seconds() <= window_seconds:
                candidates.append((t, x))
        if not candidates:
            return None
        candidates.sort(key=lambda kv: kv[0])
        return candidates[-1][1]

    level_map = nearest(qm_gbp, window_seconds=900)
    nms_row = nearest(nms_gbp, window_seconds=900)

    uk = latest.astimezone(ZoneInfo("Europe/London"))
    prev = {key_for(x): compact_prior(prior.get(key_for(x))) for x in matching}

    # Correction 3 — deterministic reassessment trigger per level.
    reassessment: dict[str, dict] = {}
    for x in matching:
        k = key_for(x)
        reassessment[k] = compute_reassessment_trigger(
            interactions_row=x, nms_row=nms_row,
            prior=prev.get(k), history=history)

    missing = []
    if level_map is None:
        missing.append("level_map")
    if nms_row is None:
        missing.append("nms")

    return {
        "bar_ts_utc": latest.isoformat(),
        "bar_age_at_receipt_seconds": int(age_s),
        "received_at_utc": now.isoformat(),
        "uk_time": uk.isoformat(),
        "nominated_uk_hour": uk.hour in NOMINATED,
        "interactions": matching,
        "level_map": level_map,
        "nms": nms_row,
        "previous_assessments": prev,
        # C3 — deterministic reassessment-trigger evaluation per level.
        "reassessment_triggers": reassessment,
        "missing_streams": missing,
        "price_scale":
            "GBPUSD prices are IG-index x 10000 (1 unit = 1 pip); do not rescale",
        "pair": "GBPUSD",
        "loi_source_path": str(loi_path),
    }


def compact_prior(decision: dict | None) -> dict | None:
    """Rolling-memory compaction (Correction 3, 2026-10-29).

    Prior-memory contract (C3):
      * The AI must see the TEXT CONTENT of its previous invalidation
        conditions so it can check whether they have fired. Count alone
        is insufficient (root cause: WATCH_REJECTION_ROOT_CAUSE.md).
      * The AI must see its previous counter_evidence so it can judge
        whether the contradictory evidence has materially grown.
      * Remaining prior fields preserved from pre-C3 shape so existing
        readers do not break.

    Budget: adds ~400-800 chars per level. Up to 30 open levels per
    packet → max input growth ~24 KB. Within Haiku 4.5's 200K context.
    """
    if not isinstance(decision, dict):
        return None
    narr = (decision.get("narrative") or "")
    inv_conds = decision.get("invalidation_conditions") or []
    counter_ev = decision.get("counter_evidence") or []
    return {
        "hypothesis": decision.get("hypothesis"),
        "direction": decision.get("direction"),
        "level_id": decision.get("level_id"),
        "bar_ts_utc": decision.get("bar_ts_utc"),
        "evaluated_at_utc": decision.get("evaluated_at_utc"),
        "narrative_tail_200": narr[-200:],
        # C3 (new) — pass CONTENT of prior conditions / counter-evidence
        "prior_invalidation_conditions": list(inv_conds)[:6],
        "prior_counter_evidence": list(counter_ev)[:6],
        # Diagnostics preserved
        "supporting_evidence_count": len(decision.get("supporting_evidence") or []),
        "counter_evidence_count": len(counter_ev),
        "invalidation_conditions_count": len(inv_conds),
        "uncertainty_tail_120": (decision.get("uncertainty") or "")[-120:],
        # C3 (new) — carry prior hypothesis_status when present
        "prior_hypothesis_status": decision.get("hypothesis_status"),
    }


# ---------------------------------------------------------------------
# Correction 3 — deterministic reassessment-trigger evaluator
# ---------------------------------------------------------------------

_INV_COND_KEYWORDS = {
    "closes_above": re.compile(r"\bcloses?\s+above\b|\bacceptance.*above\b", re.IGNORECASE),
    "closes_below": re.compile(r"\bcloses?\s+below\b|\bacceptance.*below\b", re.IGNORECASE),
    "high_penetrates": re.compile(r"\bhigh\s+penetrat(?:ion|es?)\b|\bbreak(?:s|out)?\s+above\b", re.IGNORECASE),
    "low_penetrates": re.compile(r"\blow\s+penetrat(?:ion|es?)\b|\bbreak(?:s|out)?\s+below\b", re.IGNORECASE),
    "nms_bullish": re.compile(r"\bnms.*bullish\b|\bHH\+HL\b|\bhigher[- ]high\b", re.IGNORECASE),
    "nms_bearish": re.compile(r"\bnms.*bearish\b|\bLH\+LL\b|\blower[- ]low\b", re.IGNORECASE),
    "acceptance_latch": re.compile(r"\bacceptance[\s_]latch\b|\bacceptance[\s_]latched\b", re.IGNORECASE),
    "sustain_above": re.compile(r"\bsustain(?:s|ed)?\s+above\b|\bhold(?:s|ing)?\s+above\b", re.IGNORECASE),
    "sustain_below": re.compile(r"\bsustain(?:s|ed)?\s+below\b|\bhold(?:s|ing)?\s+below\b", re.IGNORECASE),
}
_INV_COND_PIPS_RX = re.compile(r"(\d+(?:\.\d+)?)\s*(?:pips?|p\b)", re.IGNORECASE)
_INV_COND_BARS_RX = re.compile(r"(\d+)\s*(?:\+\s*)?(?:bars?|closes?|m5)", re.IGNORECASE)


def _evaluate_invalidation_condition(cond: str,
                                       raw: dict,
                                       nms_row: dict | None) -> str:
    """FIRED | PARTIAL | NOT_FIRED for one invalidation-condition string.

    Deliberately conservative: ambiguous wording returns NOT_FIRED.
    """
    text = cond or ""
    if not text:
        return "NOT_FIRED"
    closes_above = raw.get("closes_above") or 0
    closes_below = raw.get("closes_below") or 0
    consec_beyond = raw.get("consecutive_closes_beyond") or 0
    max_above = raw.get("max_excursion_above_pips") or 0
    max_below = raw.get("max_excursion_below_pips") or 0
    close_side = (raw.get("close_side") or "").lower()
    high_pen = raw.get("high_penetration_pips") or 0
    low_pen = raw.get("low_penetration_pips") or 0

    bar_counts = [int(m.group(1)) for m in _INV_COND_BARS_RX.finditer(text)]
    pip_counts = [float(m.group(1)) for m in _INV_COND_PIPS_RX.finditer(text)]

    if (_INV_COND_KEYWORDS["closes_above"].search(text)
            or _INV_COND_KEYWORDS["sustain_above"].search(text)
            or _INV_COND_KEYWORDS["acceptance_latch"].search(text)):
        req_bars = bar_counts[0] if bar_counts else 2
        if closes_above >= req_bars and (
                close_side == "above" or consec_beyond >= req_bars):
            return "FIRED"
        if closes_above >= max(1, req_bars - 1):
            return "PARTIAL"
    if (_INV_COND_KEYWORDS["closes_below"].search(text)
            or _INV_COND_KEYWORDS["sustain_below"].search(text)):
        req_bars = bar_counts[0] if bar_counts else 2
        if closes_below >= req_bars and (
                close_side == "below" or consec_beyond >= req_bars):
            return "FIRED"
        if closes_below >= max(1, req_bars - 1):
            return "PARTIAL"

    if _INV_COND_KEYWORDS["high_penetrates"].search(text) and pip_counts:
        req_pips = pip_counts[0]
        if abs(max_above) >= req_pips or abs(high_pen) >= req_pips:
            return "FIRED"
    if _INV_COND_KEYWORDS["low_penetrates"].search(text) and pip_counts:
        req_pips = pip_counts[0]
        if abs(max_below) >= req_pips or abs(low_pen) >= req_pips:
            return "FIRED"

    if nms_row:
        hh = bool(nms_row.get("hh"))
        hl = bool(nms_row.get("hl"))
        lh = bool(nms_row.get("lh"))
        ll = bool(nms_row.get("ll"))
        if _INV_COND_KEYWORDS["nms_bullish"].search(text):
            if hh and hl:
                return "FIRED"
            if hh or hl:
                return "PARTIAL"
        if _INV_COND_KEYWORDS["nms_bearish"].search(text):
            if lh and ll:
                return "FIRED"
            if lh or ll:
                return "PARTIAL"

    return "NOT_FIRED"


def _compute_hypothesis_age_bars(level_id: str,
                                   current_hypothesis: str,
                                   current_direction,
                                   history: list[dict]) -> int:
    """Prior consecutive bars on `level_id` with same (hypothesis, direction).
    0 if first bar.
    """
    streak = 0
    for row in reversed(history or []):
        if row.get("level_id") != level_id:
            continue
        if (row.get("hypothesis") == current_hypothesis
                and (row.get("direction") or None) == (current_direction or None)):
            streak += 1
        else:
            break
    return streak


def compute_reassessment_trigger(interactions_row: dict,
                                   nms_row: dict | None,
                                   prior: dict | None,
                                   history: list[dict] | None = None) -> dict:
    """Deterministic reassessment-trigger evaluation (C3, 2026-10-29).

    Reads structured packet fields and returns which deterministic
    conditions suggest the prior hypothesis should be reconsidered on
    this level. Does NOT choose a new hypothesis — AI remains the sole
    emitter.

    Threshold rationale: CORRECTION3_DESIGN.md §5. Conservative;
    backed by 27-Oct / 29-Oct replay; quiet-range sessions do NOT fire.
    """
    reasons: list[str] = []
    inv_delta: dict[str, str] = {}

    if prior is None:
        return {"trigger_fired": False, "reasons": [], "age_bars": 0,
                "prior_invalidation_delta": {}}

    raw = (interactions_row or {}).get("raw") or {}
    closes_above = raw.get("closes_above") or 0
    closes_below = raw.get("closes_below") or 0
    consec_beyond = raw.get("consecutive_closes_beyond") or 0
    distance_pips = abs(raw.get("distance_from_level_pips") or 0)
    max_above = abs(raw.get("max_excursion_above_pips") or 0)
    max_below = abs(raw.get("max_excursion_below_pips") or 0)
    close_side = (raw.get("close_side") or "").lower()

    prior_hyp = (prior.get("hypothesis") or "")
    prior_dir = (prior.get("direction") or "").upper()
    level_id = prior.get("level_id") or ""

    # Rule A — WATCH_REJECTION/SELL contradicted by sustained acceptance above.
    #   The AI expected price to reject OFF a resistance (= bounce down).
    #   Sustained acceptance ABOVE invalidates the rejection framing.
    if prior_hyp == "WATCH_REJECTION" and prior_dir == "SELL":
        if closes_above >= 3 and distance_pips >= 5 and close_side == "above":
            reasons.append(
                "prior WATCH_REJECTION/SELL but closes_above="
                f"{closes_above} >= 3, distance=+{distance_pips:.1f}p, "
                "close_side=above (sustained acceptance above level)")
        if max_above >= 10 and consec_beyond >= 2:
            reasons.append(
                f"max_excursion_above={max_above:.1f}p >= 10 and "
                f"consecutive_closes_beyond={consec_beyond} >= 2 "
                "(breakaway signature)")

    # Rule B — WATCH_REJECTION/BUY contradicted by sustained acceptance below.
    #   The AI expected price to reject OFF a support (= bounce up).
    #   Sustained acceptance BELOW invalidates the rejection framing.
    if prior_hyp == "WATCH_REJECTION" and prior_dir == "BUY":
        if closes_below >= 3 and distance_pips >= 5 and close_side == "below":
            reasons.append(
                "prior WATCH_REJECTION/BUY but closes_below="
                f"{closes_below} >= 3, distance=-{distance_pips:.1f}p, "
                "close_side=below (sustained acceptance below level)")
        if max_below >= 10 and consec_beyond >= 2:
            reasons.append(
                f"max_excursion_below={max_below:.1f}p >= 10 and "
                f"consecutive_closes_beyond={consec_beyond} >= 2 "
                "(breakaway signature)")

    # Rule A2 — WATCH_BREAKOUT/BUY contradicted by sustained retreat below.
    #   The AI expected an upside breakout to continue. If price has
    #   retreated BELOW the level with sustained closes, the breakout
    #   has failed and the hypothesis needs reassessment.
    if prior_hyp == "WATCH_BREAKOUT" and prior_dir == "BUY":
        if closes_below >= 3 and distance_pips >= 5 and close_side == "below":
            reasons.append(
                "prior WATCH_BREAKOUT/BUY but closes_below="
                f"{closes_below} >= 3, distance=-{distance_pips:.1f}p, "
                "close_side=below (breakout failed; price retreated)")

    # Rule B2 — WATCH_BREAKOUT/SELL contradicted by sustained recovery above.
    if prior_hyp == "WATCH_BREAKOUT" and prior_dir == "SELL":
        if closes_above >= 3 and distance_pips >= 5 and close_side == "above":
            reasons.append(
                "prior WATCH_BREAKOUT/SELL but closes_above="
                f"{closes_above} >= 3, distance=+{distance_pips:.1f}p, "
                "close_side=above (breakdown failed; price recovered)")

    # Rule C — NMS structure opposes prior direction (HH+HL / LH+LL both).
    if nms_row:
        demo_dir = (nms_row.get("demonstrated_direction") or "").upper()
        hh = bool(nms_row.get("hh"))
        hl = bool(nms_row.get("hl"))
        lh = bool(nms_row.get("lh"))
        ll = bool(nms_row.get("ll"))
        if (prior_dir == "SELL" and demo_dir == "UP" and hh and hl
                and prior_hyp in ("WATCH_REJECTION", "WATCH_BREAKOUT")):
            reasons.append(
                "NMS demonstrated_direction=UP with HH+HL opposes prior "
                f"SELL on {prior_hyp}")
        if (prior_dir == "BUY" and demo_dir == "DOWN" and lh and ll
                and prior_hyp in ("WATCH_REJECTION", "WATCH_BREAKOUT")):
            reasons.append(
                "NMS demonstrated_direction=DOWN with LH+LL opposes prior "
                f"BUY on {prior_hyp}")

    # Rule D — explicit invalidation-condition deltas.
    # Only fire for priors that represent a DIRECTIONAL anchor
    # (WATCH_REJECTION, WATCH_BREAKOUT, OPPORTUNITY_TO_REVIEW).
    # A NO_OPPORTUNITY prior is already uncommitted — the AI
    # transitioning to WATCH_* when a condition fires is normal
    # evolution, not anchor-breaking. False-positive mitigation per
    # extended-replay findings 2026-10-29.
    if prior_hyp in ("WATCH_REJECTION", "WATCH_BREAKOUT",
                       "OPPORTUNITY_TO_REVIEW"):
        prior_conds = prior.get("prior_invalidation_conditions") or []
        for cond in prior_conds:
            if not isinstance(cond, str) or not cond.strip():
                continue
            delta = _evaluate_invalidation_condition(cond, raw, nms_row)
            if delta != "NOT_FIRED":
                inv_delta[cond] = delta
                if delta == "FIRED":
                    reasons.append(
                        "prior invalidation condition fired: "
                        f"\"{cond[:120]}\"")

    age_bars = _compute_hypothesis_age_bars(
        level_id, prior_hyp, prior.get("direction"), history or [])

    return {
        "trigger_fired": len(reasons) > 0,
        "reasons": reasons,
        "age_bars": age_bars,
        "prior_invalidation_delta": inv_delta,
    }


def attach_macro(packet_obj: dict, args) -> None:
    """Attach macro_context to the packet. Point-in-time asof is the bar
    close time, NOT the current wall clock — this guarantees no post-candle
    data can influence that earlier assessment."""
    bar_close = (dt.datetime.fromisoformat(packet_obj["bar_ts_utc"].replace("Z", "+00:00"))
                 + dt.timedelta(minutes=5))
    event_file = pathlib.Path(args.macro_events) if args.macro_events else None
    try:
        packet_obj["macro_context"] = build_macro_packet(
            asof=bar_close,
            source_mode=args.macro_source,
            event_file=event_file,
            read_news_state=args.news_state,
        )
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        packet_obj["macro_context"] = {
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
            "source_mode": args.macro_source,
            "asof_utc": bar_close.isoformat(),
        }


OBSERVATION_TOOL = {
    "name": "return_observation",
    "description": (
        "Record a single structured observation about a GBPUSD "
        "structural level interaction. Call exactly once per response."),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "hypothesis", "direction", "level_id", "narrative",
            "supporting_evidence", "counter_evidence",
            "change_since_previous", "invalidation_conditions", "uncertainty",
        ],
        "properties": {
            "hypothesis": {
                "type": "string",
                "enum": sorted(STATES),
            },
            "direction": {
                "oneOf": [
                    {"type": "string", "enum": ["BUY", "SELL"]},
                    {"type": "null"},
                ],
            },
            "level_id": {
                "type": "string",
                "description": "Must be a string copied verbatim from "
                               "packet.interactions[*].interaction_id.",
                "minLength": 1,
                "maxLength": 64,
            },
            "narrative": {"type": "string", "maxLength": 400},
            "supporting_evidence": {
                "type": "array", "maxItems": 6,
                "items": {"type": "string", "maxLength": 120},
            },
            "counter_evidence": {
                "type": "array", "maxItems": 6,
                "items": {"type": "string", "maxLength": 120},
            },
            "change_since_previous": {"type": "string", "maxLength": 220},
            "invalidation_conditions": {
                "type": "array", "maxItems": 6,
                "items": {"type": "string", "maxLength": 120},
            },
            "uncertainty": {"type": "string", "maxLength": 180},
            "macro_scenarios": {
                "type": "array", "maxItems": 4,
                "items": {"type": "string", "maxLength": 180},
            },
            # Correction 3 — optional lifecycle status of the prior
            # hypothesis relative to the current bar's evidence.
            "hypothesis_status": {
                "oneOf": [
                    {"type": "string", "enum": [
                        "ACTIVE", "CHALLENGED", "INVALIDATED",
                        "RESOLVED", "EXPIRED",
                    ]},
                    {"type": "null"},
                ],
            },
        },
    },
}


def _extract_tool_use(resp) -> tuple[dict | None, str]:
    """Return (tool_input_dict, raw_text_fallback) from an Anthropic response."""
    tool_input: dict | None = None
    text_parts: list[str] = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use" and getattr(block, "name", "") == "return_observation":
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                tool_input = inp
        elif btype == "text":
            text_parts.append(getattr(block, "text", "") or "")
    return tool_input, "".join(text_parts).strip()


def _call_haiku(client, model: str, system_text: str, user_payload: str,
                max_tokens: int):
    """One Anthropic call. Return (resp, tool_input, raw_text)."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_text,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_payload}],
        tools=[OBSERVATION_TOOL],
        tool_choice={"type": "tool", "name": "return_observation"},
    )
    tool_input, raw_text = _extract_tool_use(resp)
    return resp, tool_input, raw_text


def _usage(resp) -> dict:
    u = getattr(resp, "usage", None)
    return {
        "usage_input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "usage_output_tokens": int(getattr(u, "output_tokens", 0) or 0),
        "usage_cache_read_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "usage_cache_creation_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    }


class TruncatedResponse(RuntimeError):
    """Raised when stop_reason == 'max_tokens' and the tool_use JSON is incomplete."""


def ai_call(pkt: dict, model: str, *, max_tokens: int = 4096,
            retry_on_truncation: bool = True,
            raw_debug_dir: pathlib.Path | None = None) -> dict:
    """Request a single structured observation from Haiku.

    Reliability contract:
      * Uses Anthropic tool_use so the response is a JSON object matching
        OBSERVATION_TOOL.input_schema — no fence-stripping or free-form
        parsing.
      * If stop_reason == 'max_tokens' AND the tool_use block is absent or
        malformed, raises TruncatedResponse so the caller can retry with
        tighter instructions.
      * Validates every field against the same contract the running agent
        enforced (hypothesis in STATES, direction in BUY/SELL/null,
        level_id ∈ interaction_ids, three lists are arrays, optional
        macro_scenarios is a list).
      * Stamps execution_authority=NONE.
      * Does NOT fabricate a decision on parse failure.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY missing: real AI inference unavailable "
            "(check /opt/tradingbot/.env; do not print the value)")
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(f"anthropic SDK unavailable: {exc}")
    client = anthropic.Anthropic(api_key=key)
    valid_ids = [key_for(it) for it in pkt["interactions"]]
    schema_note = {
        "level_ids_available": valid_ids,
        "level_id_source_field": "interactions[*].interaction_id",
        "required_contract": (
            "The response field `level_id` MUST be a non-null string copied "
            "verbatim from `level_ids_available`. Required even when "
            "`hypothesis` is NO_OPPORTUNITY. Returning anything else "
            "violates the contract and the response will be discarded."),
    }
    user_payload = json.dumps({"packet": pkt, "contract": schema_note},
                              default=str, sort_keys=True)

    attempts: list[dict] = []
    resp, tool_input, raw_text = _call_haiku(
        client, model, SYSTEM, user_payload, max_tokens=max_tokens)
    stop_reason = getattr(resp, "stop_reason", None)
    attempts.append({"attempt": 1, "stop_reason": stop_reason, **_usage(resp),
                     "had_tool_use": tool_input is not None,
                     "raw_text_len": len(raw_text)})

    if (tool_input is None or stop_reason == "max_tokens") and retry_on_truncation:
        # Retry ONCE with a stricter brevity nudge AND the maximum output
        # budget. Haiku 4.5's input_schema maxLength caps already apply, but
        # the model occasionally overshoots them for narrative; the nudge
        # reinforces the budget and the higher ceiling absorbs any residue.
        strict_system = SYSTEM + (
            "\n\nREPEAT: narrative <= 400 chars, evidence items <= 120 chars, "
            "lists <= 6 items. Produce the tool call in one shot. If prior "
            "attempt was truncated, be shorter.")
        resp2, tool_input2, raw_text2 = _call_haiku(
            client, model, strict_system, user_payload, max_tokens=8192)
        attempts.append({"attempt": 2, "stop_reason": getattr(resp2, "stop_reason", None),
                         **_usage(resp2), "had_tool_use": tool_input2 is not None,
                         "raw_text_len": len(raw_text2), "retry_reason":
                         "truncation" if stop_reason == "max_tokens" else "missing_tool_use"})
        if tool_input2 is not None:
            resp, tool_input, raw_text = resp2, tool_input2, raw_text2
            stop_reason = getattr(resp2, "stop_reason", None)

    if tool_input is None:
        if raw_debug_dir is not None:
            try:
                raw_debug_dir.mkdir(parents=True, exist_ok=True)
                dump = raw_debug_dir / (
                    "raw_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    + ".json")
                dump.write_text(json.dumps({
                    "bar_ts_utc": pkt.get("bar_ts_utc"),
                    "stop_reason": stop_reason,
                    "attempts": attempts,
                    "raw_text": raw_text,
                }, default=str), encoding="utf-8")
            except OSError:
                pass
        raise TruncatedResponse(
            f"Haiku returned no usable tool_use (stop_reason={stop_reason!r}; "
            f"attempts={attempts}; raw_text[:200]={raw_text[:200]!r})")

    obj = dict(tool_input)
    # Validation (same contract as the running agent, plus macro_scenarios).
    if obj.get("hypothesis") not in STATES:
        raise ValueError(f"Unexpected AI hypothesis: {obj.get('hypothesis')!r}")
    if obj.get("direction") not in ("BUY", "SELL", None):
        raise ValueError(f"Invalid direction: {obj.get('direction')!r}")
    ids = {key_for(i) for i in pkt["interactions"]}
    if obj.get("level_id") not in ids:
        raise ValueError(
            f"LLM cited unknown level_id {obj.get('level_id')!r}; valid={sorted(ids)}")
    for field in ("supporting_evidence", "counter_evidence", "invalidation_conditions"):
        if not isinstance(obj.get(field), list):
            raise ValueError(f"Invalid evidence structure at {field!r}")
    if "macro_scenarios" in obj and not isinstance(obj["macro_scenarios"], list):
        raise ValueError("macro_scenarios present but not a list")

    obj["execution_authority"] = "NONE"
    obj["bar_ts_utc"] = pkt["bar_ts_utc"]
    obj["evaluated_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    obj["model"] = model
    obj["llm_provider"] = "anthropic"
    obj["stop_reason"] = stop_reason
    obj.update(_usage(resp))
    obj["attempts"] = len(attempts)
    obj["attempt_log"] = attempts
    mc = pkt.get("macro_context") or {}
    obj["macro_source_mode"] = mc.get("source_mode")
    obj["macro_status"] = mc.get("status")
    obj["macro_event_count"] = len(mc.get("events") or [])
    return obj


def append(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf8") as f:
        f.write(json.dumps(obj, default=str, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def run(args) -> int:
    root = pathlib.Path(args.root)
    out = pathlib.Path(args.out)
    if str(out.resolve()).startswith(str(root.resolve()) + os.sep):
        raise ValueError("Output MUST be outside production root")
    load_env_once(root / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY missing; refuse to run without an AI reasoning service")
    if args.macro_source in ("operator_jsonl", "both") and not args.macro_events:
        raise ValueError("--macro-events is required for --macro-source operator_jsonl|both")
    statefile = out / "memory.jsonl"
    history = last_rows(statefile, 1000) if statefile.exists() else []
    prev = {x["level_id"]: x for x in history if x.get("level_id")}
    seen = {x.get("bar_ts_utc") for x in history}
    # Per-bar failure accounting: don't thrash the same bar every poll.
    bar_fail_count: dict[str, int] = {}
    FAIL_CEILING = 2  # one real call + one tool_use retry already inside ai_call
    raw_debug_dir = out / "raw_failures"
    deadline = timestamp(args.end_utc) if args.end_utc else None
    if not args.once and deadline is None:
        raise ValueError("Bounded --end-utc is required unless --once")
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        if deadline and now >= deadline:
            break
        try:
            p = packet(root, now, prev, history=history)
            attach_macro(p, args)
            bar_ts = p["bar_ts_utc"]
            if bar_ts in seen:
                print(json.dumps({
                    "bar_ts_utc": bar_ts,
                    "note": "already observed this bar; silent until new bar closes",
                }), flush=True)
            elif bar_fail_count.get(bar_ts, 0) >= FAIL_CEILING:
                print(json.dumps({
                    "bar_ts_utc": bar_ts,
                    "note": "bar skipped after FAIL_CEILING outer retries; "
                            "awaiting next bar close",
                    "outer_retries": bar_fail_count[bar_ts],
                }), flush=True)
            else:
                append(out / "snapshots.jsonl", p)
                try:
                    result = ai_call(p, args.model,
                                     max_tokens=args.max_tokens,
                                     retry_on_truncation=True,
                                     raw_debug_dir=raw_debug_dir)
                except TruncatedResponse as texc:
                    bar_fail_count[bar_ts] = bar_fail_count.get(bar_ts, 0) + 1
                    append(out / "errors.jsonl", {
                        "observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "error": "TruncatedResponse",
                        "bar_ts_utc": bar_ts,
                        "outer_retries": bar_fail_count[bar_ts],
                        "detail": str(texc)[:400],
                        "recovery": "will not retry this bar further; "
                                    "awaiting next bar close",
                    })
                    if args.once:
                        raise
                else:
                    append(out / "decisions.jsonl", result)
                    seen.add(bar_ts)
                    prev[result["level_id"]] = result
                    # C3 — maintain history for age-tracking across bars.
                    history.append(result)
                    if len(history) > 1000:
                        history[:] = history[-1000:]
                    append(statefile, result)
                    print(json.dumps({
                        "bar_ts_utc": result["bar_ts_utc"],
                        "level_id": result["level_id"],
                        "hypothesis": result["hypothesis"],
                        "direction": result.get("direction"),
                        "evaluated_at_utc": result["evaluated_at_utc"],
                        "macro_source_mode": result.get("macro_source_mode"),
                        "macro_event_count": result.get("macro_event_count"),
                        "attempts": result.get("attempts"),
                        "stop_reason": result.get("stop_reason"),
                        "output_tokens": result.get("usage_output_tokens"),
                    }), flush=True)
        except (OSError, RuntimeError, ValueError, KeyError, TimeoutError) as exc:
            append(out / "errors.jsonl", {
                "observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "error": type(exc).__name__,
                "detail": str(exc)[:300],
            })
            if args.once:
                raise
        if args.once:
            break
        time.sleep(max(30, args.poll_seconds))
    return 0


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--root", default="/opt/tradingbot")
    a.add_argument("--out", required=True)
    a.add_argument("--model", default="claude-haiku-4-5-20251001")
    a.add_argument("--poll-seconds", type=int, default=60)
    a.add_argument("--end-utc", help="UTC ISO8601; mandatory unless --once")
    a.add_argument("--once", action="store_true")
    a.add_argument("--macro-source", choices=("host_live", "operator_jsonl", "both"),
                   default="host_live")
    a.add_argument("--macro-events", help="Path to operator-approved verified_events.jsonl "
                                          "(required when --macro-source is operator_jsonl|both)")
    a.add_argument("--news-state", action="store_true",
                   help="Also fetch approved localhost /news-state (optional)")
    a.add_argument("--max-tokens", type=int, default=4096,
                   help="First-attempt Haiku max_tokens; truncation retry "
                        "automatically escalates to 8192")
    sys.exit(run(a.parse_args()))
