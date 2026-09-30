"""LLM rationale writer for briefing.v5_pia (Phase 2).

Given a deterministic BriefingV5 (already produced by the orchestrator
with rationale=None), call Anthropic Sonnet 4.6 with the PIA-style system
prompt and return a 4-6 line plain-text rationale. Validation is applied
post-LLM; failure either way returns None and the briefing keeps
rationale=null.

NO retries. Failures fail loud and return None. The orchestrator must
already have written the deterministic plan to disk before calling this.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from briefing.v5_pia.anthropic_client import call_messages
from briefing.v5_pia.schema import BriefingV5

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants — model + sampling parameters fixed by the Phase-2 spec
# ─────────────────────────────────────────────────────────────────────────────

RATIONALE_MODEL       = "claude-sonnet-4-6"
RATIONALE_TEMPERATURE = 0.2
RATIONALE_MAX_TOKENS  = 250
RATIONALE_TIMEOUT_SEC = 60

# Validation thresholds. Tuned for a 4-6 line rationale:
#   - 50 chars ≈ one short sentence; below that the LLM almost certainly
#     truncated or returned an apology.
#   - 600 chars ≈ ~5-6 lines × ~100 chars/line — leaves headroom but
#     catches a runaway LLM that ignored the line cap.
RATIONALE_MIN_CHARS   = 50
RATIONALE_MAX_CHARS   = 600

# Markdown characters we forbid (per Phase-2 spec). Asterisks and hashes
# are the most common offenders; backticks too because triple-backtick
# fences sneak in when the model thinks it's writing code.
_FORBIDDEN_MARKDOWN_CHARS = ("#", "*", "`")


# ─────────────────────────────────────────────────────────────────────────────
# System prompt — verbatim from Phase-2 spec, do not paraphrase
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior FX technical analyst writing intraday trade briefings in the PIA-First house style. You will receive structured market data and a pre-computed trade plan. Your only job is to write the rationale field.

Input format notes:
- market_data.h4_ohlc_table and market_data.d1_ohlc_table are compact "O/H/L/C, O/H/L/C, ..." strings, oldest first. Use them to read multi-day structure (~10 calendar days on H4, ~4 weeks on D1).
- market_data.news_events lists today's HIGH-impact events for the pair's currency bases.
- A separate "Upcoming high-impact events (next 5 days):" block may appear after the JSON, with relative-time hints like "(today, in 6h)" or "(Mon, in 60h)". When present, it lists scheduled HIGH-impact prints that may shape positioning. Do not invent events not in this list.

You MUST NOT:
- Change the direction, entry, stop, target, or confidence values
- Invent new levels not in support_levels or resistance_levels
- Reference levels by name that aren't in the bias_anchor_label or stop_structural_level fields
- Recommend exit management, partial fills, or news handling

You MUST:
- Write 4-6 short lines, declarative, present tense
- Open with "We look to {Buy|Sell} at {entry}" if direction != STAND_ASIDE
- Reference the bias_anchor by its label
- State the directional bias in one line
- Mention one structural justification for the stop
- If direction == STAND_ASIDE, explain in 2-3 lines why confluence failed; do not suggest alternative trades
- If the Upcoming high-impact events block contains an event for the pair's currency in the next 24-48h, mention "calendar pressure" briefly (one line). Do not invent levels around it.

Style examples (PIA voice):
- "We look to Sell at 1.3535"
- "Our short term bias remains negative"
- "20 4hour EMA is at 1.3535"
- "Offers ample risk/reward to sell at the market"
- "There is no clear indication that the downward move is coming to an end"
- "Overnight gains have been limited"

Output: plain text, no markdown, no preamble."""


# ─────────────────────────────────────────────────────────────────────────────
# User-message construction
# ─────────────────────────────────────────────────────────────────────────────

def _compact_ohlc_table(candles: List[Dict[str, Any]]) -> str:
    """Render a candle list as a compact, parseable OHLC string.

    Format: "O/H/L/C, O/H/L/C, ..." (oldest → newest). Numbers preserve
    raw IG-points form (no /10000 division — same form the rest of
    market_data uses for d1_ema_20 etc, so the LLM sees consistent
    magnitudes). One token per number is dominated by digits, so 4
    numbers/bar × ~5-7 chars ≈ ~24-30 chars/bar; 40 H4 bars ≈ 1200 chars
    ≈ ~300 tokens. The format is deliberately stable + cheap.
    """
    if not candles:
        return ""
    parts: List[str] = []
    for c in candles:
        try:
            o = c.get("o", c.get("open"))
            h = c.get("h", c.get("high"))
            lo = c.get("l", c.get("low"))
            cl = c.get("c", c.get("close"))
            if None in (o, h, lo, cl):
                continue
            parts.append(f"{float(o)}/{float(h)}/{float(lo)}/{float(cl)}")
        except (TypeError, ValueError):
            continue
    return ", ".join(parts)


def _format_relative_time(dt_iso: str, now_utc: datetime) -> str:
    """Render a relative-time hint like "today, in 6h" / "Mon, in 60h".

    Returns "" on parse failure so the caller can omit the bracketed hint.
    """
    try:
        ev_dt = datetime.fromisoformat(str(dt_iso))
        if ev_dt.tzinfo is None:
            ev_dt = ev_dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    delta = ev_dt - now_utc
    hours = round(delta.total_seconds() / 3600.0)
    today = now_utc.date()
    ev_date = ev_dt.date()
    if ev_date == today:
        day_label = "today"
    elif (ev_date - today).days == 1:
        day_label = "tomorrow"
    else:
        day_label = ev_dt.strftime("%a")
    return f"{day_label}, in {hours}h"


def _format_upcoming_events_section(
    events: List[Dict[str, Any]], now_utc: datetime,
) -> str:
    """Render the multi-day forward calendar as a structured prompt
    section. Returns "" when there are no events so the caller can omit
    the header entirely (per Fix 4 spec).
    """
    if not events:
        return ""
    lines: List[str] = ["Upcoming high-impact events (next 5 days):"]
    for e in events:
        try:
            dt_iso = str(e.get("datetime_utc") or "")
            ev_dt = datetime.fromisoformat(dt_iso)
            if ev_dt.tzinfo is None:
                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
            stamp = ev_dt.strftime("%Y-%m-%d %H:%M UTC")
        except (TypeError, ValueError):
            stamp = f"{e.get('date_utc','')} {e.get('time','')} UTC".strip()
        rel = _format_relative_time(str(e.get("datetime_utc") or ""), now_utc)
        ccy = str(e.get("currency", "")).upper()
        name = str(e.get("event_name", "")).strip()
        rel_part = f" ({rel})" if rel else ""
        lines.append(f"- {stamp} {ccy}: {name}{rel_part}")
    return "\n".join(lines)


def _market_data_summary(
    market_data: Dict[str, Any], now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Extract a structured summary of the v5 market_data dict for the
    user message.

    Phase 1 dropped ~80% of v4-computed fields here (audit Gap D). This
    summary now restores them: prev day/week structure, htf_bias, USD
    proxy, prior-session signal, plus compact OHLC tables for the H4 and
    D1 series so the LLM can reason about multi-day structure.

    The candle arrays are passed as compact "O/H/L/C, O/H/L/C, ..."
    strings rather than raw lists to keep the JSON parseable while
    bounding token cost. The format is documented in the system prompt.
    """
    md = market_data or {}
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    h4 = (md.get("h4_candles") or [])
    d1 = (md.get("d1_candles") or [])
    last_h4 = h4[-1] if h4 else {}
    h1 = (md.get("h1_candles") or [])

    # Recent pip move: last close vs 6h-prior close on H1, in pips.
    recent_move_pips: Optional[float] = None
    try:
        if len(h1) >= 7:
            ppp = float(md.get("ppp", 1.0)) or 1.0
            last_close = float(h1[-1].get("c", h1[-1].get("close")))
            ref_close  = float(h1[-7].get("c", h1[-7].get("close")))
            recent_move_pips = round((last_close - ref_close) / ppp, 1)
    except (TypeError, ValueError, KeyError):
        recent_move_pips = None

    return {
        # ── Existing v5 scalars ────────────────────────────────────────
        "current_price":     md.get("current_price"),
        "d1_ema_20":         md.get("d1_ema_20"),
        "h4_ema_20":         md.get("h4_ema_20"),
        "h4_close":          float(last_h4.get("c", last_h4.get("close"))) if last_h4 else None,
        "h1_recent_pip_move_6h": recent_move_pips,
        "atr_pctl_14":       md.get("atr_pctl_14"),
        "atr_h4_pips":       md.get("atr_h4_pips"),
        "phase4_structure":  md.get("phase4_structure"),
        "ema_stack_state":   md.get("ema_stack_state"),
        # ── v4-computed fields (audit Gap D) ───────────────────────────
        "prev_day_high":     md.get("prev_day_high"),
        "prev_day_low":      md.get("prev_day_low"),
        "prev_day_close":    md.get("prev_day_close"),
        "week_high":         md.get("week_high"),
        "week_low":          md.get("week_low"),
        "prev_week_high":    md.get("prev_week_high"),
        "prev_week_low":     md.get("prev_week_low"),
        "htf_bias":          md.get("htf_bias"),
        "usd_proxy_bias":    md.get("usd_proxy_bias"),
        "prev_session_actual_direction": md.get("prev_session_actual_direction"),
        "prev_session_pip_move":         md.get("prev_session_pip_move"),
        # ── News (today + forward 5 days) ──────────────────────────────
        "news_events":       md.get("news_events") or [],
        # ── Compact OHLC tables (oldest → newest) ──────────────────────
        # Format: "O/H/L/C, O/H/L/C, ...". 40 H4 bars ≈ ~10 calendar days
        # of structure visibility; 20 D1 bars ≈ ~4 weeks. The system
        # prompt documents the format so the LLM knows how to read it.
        "h4_ohlc_table":     _compact_ohlc_table(h4),
        "h4_bars_count":     len(h4),
        "d1_ohlc_table":     _compact_ohlc_table(d1),
        "d1_bars_count":     len(d1),
    }


def build_user_message(
    briefing: BriefingV5,
    market_data: Dict[str, Any],
    now_utc: Optional[datetime] = None,
) -> str:
    """Build the structured JSON the LLM receives as its user message.

    Schema deliberately small and named so the LLM has the exact
    references the system prompt requires (bias_anchor_label,
    stop_structural_level, support_levels, resistance_levels). Hard-gate
    failures are surfaced for STAND_ASIDE briefings so the LLM can
    explain what failed.

    Forward calendar: upcoming_events is rendered as a separate plain-text
    section after the JSON payload (see _format_upcoming_events_section).
    Inserted only when there are events — empty section header is
    suppressed so the prompt stays clean on slow news weeks.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    bd = briefing.to_dict()
    breakdown = bd.get("confidence_breakdown") or {}
    payload: Dict[str, Any] = {
        "pair":                    bd.get("pair"),
        "direction":               bd.get("direction"),
        "entry":                   bd.get("entry"),
        "stop":                    bd.get("stop"),
        "target":                  bd.get("target"),
        "rr":                      bd.get("rr"),
        "bias_anchor":             bd.get("bias_anchor"),
        "bias_anchor_label":       bd.get("bias_anchor_label"),
        "stop_structural_level":   bd.get("stop_structural_level"),
        "support_levels":          bd.get("support_levels") or [],
        "resistance_levels":       bd.get("resistance_levels") or [],
        "confidence":              bd.get("confidence"),
        "confidence_bucket":       bd.get("confidence_bucket"),
        "stand_aside_reason":      bd.get("stand_aside_reason"),
        "hard_gate_failures":      list(breakdown.get("hard_gate_failures") or []),
        "market_data":             _market_data_summary(market_data, now_utc=now_utc),
    }
    json_block = json.dumps(payload, indent=2, default=str)

    # Append the forward calendar section. The LLM can correlate the
    # "in Nh" annotations with the prompt's pre_news_bypass diagnostics
    # (in confidence_breakdown.diagnostics) to recognise positioning
    # regimes — this is the prompt-side counterpart to Fix 1.
    upcoming = (market_data or {}).get("upcoming_events") or []
    section = _format_upcoming_events_section(upcoming, now_utc)
    if section:
        return f"{json_block}\n\n{section}"
    return json_block


# ─────────────────────────────────────────────────────────────────────────────
# Public surface
# ─────────────────────────────────────────────────────────────────────────────

def write_rationale(briefing: BriefingV5, market_data: Dict[str, Any]) -> Optional[str]:
    """Call the LLM and return the rationale text.

    Returns None on any of: missing API key, HTTP/parse failure, output
    that fails post-LLM validation. The caller (orchestrator) is expected
    to handle None by leaving briefing.rationale = null.

    NO retries. Phase-2 spec is fail-loud: one shot, log, return None.
    """
    user = build_user_message(briefing, market_data)
    try:
        text = call_messages(
            system=SYSTEM_PROMPT,
            user=user,
            model=RATIONALE_MODEL,
            temperature=RATIONALE_TEMPERATURE,
            max_tokens=RATIONALE_MAX_TOKENS,
            timeout=RATIONALE_TIMEOUT_SEC,
        )
    except Exception as exc:
        logger.error(
            "RATIONALE_LLM_FAILED pair=%s session=%s direction=%s "
            "exception=%s",
            briefing.pair, briefing.session, briefing.direction, exc,
            exc_info=True,
        )
        return None

    if text is None:
        logger.error(
            "RATIONALE_LLM_FAILED pair=%s session=%s direction=%s "
            "reason=client_returned_none",
            briefing.pair, briefing.session, briefing.direction,
        )
        return None

    # Post-LLM validation. On failure: log loudly, return None.
    if not validate_rationale(text, briefing):
        # validate_rationale already logs the specific failed rule.
        return None

    return text


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────

def _format_price_for_pair(value: float, pair: str) -> str:
    """Render a price the way the LLM would naturally type it.

    The candles use IG points (e.g. 13540.5 for GBPUSD = 1.35405). The
    LLM is more likely to write 1.35405 than 13540.5, so we accept BOTH
    representations during the entry/anchor presence check. Returns the
    decimal-quoted form.
    """
    pair = (pair or "").upper()
    if "JPY" in pair:
        # JPY decimal quote: divide by 100 (e.g. 15700.5 → 157.005)
        return f"{value / 100.0:.3f}"
    return f"{value / 10000.0:.5f}"


def _entry_or_anchor_referenced(text: str, briefing: BriefingV5) -> bool:
    """True if the rationale mentions the entry value or bias_anchor in
    EITHER IG-points form OR decimal-quote form.
    """
    candidates: list[str] = []
    for v in (briefing.entry, briefing.bias_anchor):
        if v is None:
            continue
        # Raw points form (drop trailing zeros and ".0" for tidier match).
        raw = f"{v:.5f}".rstrip("0").rstrip(".")
        candidates.append(raw)
        candidates.append(f"{v}")
        # Decimal-quote form
        candidates.append(_format_price_for_pair(v, briefing.pair))
    return any(c and c in text for c in candidates)


def validate_rationale(rationale: str, briefing: BriefingV5) -> bool:
    """Apply the four Phase-2 validation rules. Logs the specific
    failed rule on rejection. Returns True on pass, False on fail.

    Rules:
      1. Length 50–600 chars
      2. Non-STAND_ASIDE: must reference entry OR bias_anchor in EITHER
         IG-points form (e.g. "13540.5") OR decimal-quote form (e.g.
         "1.35405"). The literal Phase-2 spec wording was "must contain
         entry value as a string token (formatted to the pair's price
         precision)" — we extend this to accept both forms because the
         system prompt's style examples ("We look to Sell at 1.3535",
         "20 4hour EMA is at 1.3535") all use decimal-quote form, so a
         well-behaved LLM following the prompt will produce decimal,
         not IG-points. Rejecting decimal would fail every valid PIA
         rationale. The conversion is /10000 for non-JPY pairs and /100
         for JPY pairs; see _format_price_for_pair below.
      3. Must NOT contain markdown chars (#, *, `)
      4. STAND_ASIDE: must NOT contain "We look to Buy" or "We look to
         Sell" — STAND_ASIDE rationales explain why we're not entering;
         the system prompt forbids alternative-trade suggestions.
    """
    if rationale is None:
        logger.error("RATIONALE_VALIDATION_FAILED rule=null_input")
        return False

    text = str(rationale).strip()
    n = len(text)

    # Rule 1: length
    if n < RATIONALE_MIN_CHARS or n > RATIONALE_MAX_CHARS:
        logger.error(
            "RATIONALE_VALIDATION_FAILED rule=length pair=%s "
            "len=%d bounds=%d-%d rationale=%r",
            briefing.pair, n, RATIONALE_MIN_CHARS, RATIONALE_MAX_CHARS, text[:200],
        )
        return False

    # Rule 3 (checked early — cheap, format-only): no markdown
    for ch in _FORBIDDEN_MARKDOWN_CHARS:
        if ch in text:
            logger.error(
                "RATIONALE_VALIDATION_FAILED rule=markdown pair=%s "
                "char=%r rationale=%r",
                briefing.pair, ch, text[:200],
            )
            return False

    # Rule 2: non-STAND_ASIDE must reference entry or anchor
    if briefing.direction != "STAND_ASIDE":
        if not _entry_or_anchor_referenced(text, briefing):
            logger.error(
                "RATIONALE_VALIDATION_FAILED rule=entry_or_anchor_not_referenced "
                "pair=%s entry=%s bias_anchor=%s rationale=%r",
                briefing.pair, briefing.entry, briefing.bias_anchor, text[:300],
            )
            return False

    # Rule 4: STAND_ASIDE must not look like a recommendation
    if briefing.direction == "STAND_ASIDE":
        lowered = text.lower()
        if "we look to buy" in lowered or "we look to sell" in lowered:
            logger.error(
                "RATIONALE_VALIDATION_FAILED rule=stand_aside_recommends_trade "
                "pair=%s rationale=%r",
                briefing.pair, text[:300],
            )
            return False

    return True
