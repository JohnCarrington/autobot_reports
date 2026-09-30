"""V5 briefing orchestrator (Phase 1).

Pulls market_data via the shared v4 helper (extended), builds a deterministic
trade plan, scores confidence, writes JSON. Does not call any LLM.
rationale field is null in Phase 1.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from briefing.v5_pia.config import (
    BRIEFINGS_DIR,
    BRIEFING_EXECUTION_MIN_CONFIDENCE,
)
from briefing.v5_pia.confidence_scorer import score_confidence
from briefing.v5_pia.schema import BriefingV5
from briefing.v5_pia.trade_plan_builder import build_trade_plan

logger = logging.getLogger(__name__)


# Minutes from generated_at_utc until the briefing is considered stale.
# London plans expire 12:30Z, NY plans expire end-of-day. We encode that
# in valid_until_utc — the executor (Phase 3) will respect it.
_VALID_HOURS_BY_SESSION = {
    "London": 7,    # ~05:30Z to ~12:30Z
    "NY":     8,    # ~12:30Z to ~21:00Z
}


def _valid_until_utc(now_utc: datetime, session: str) -> datetime:
    hours = _VALID_HOURS_BY_SESSION.get(session, 7)
    return now_utc + timedelta(hours=hours)


def _briefing_path(pair: str, now_utc: datetime, session: str) -> Path:
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = now_utc.strftime("%Y-%m-%d")
    return BRIEFINGS_DIR / f"briefing_{pair.upper()}_{date_str}_{session}.json"


def _state_from_bucket(bucket: str) -> str:
    """Bucket → state mapping per spec.
       STAND_ASIDE / WATCH → state=STAND_ASIDE (won't execute, dashboard only)
       ARMED / HIGH_CONVICTION → state=ARMED
    """
    if bucket in ("ARMED", "HIGH_CONVICTION"):
        return "ARMED"
    return "STAND_ASIDE"


def _pre_scoring_context(market_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Pull D1/H4 close + H4 EMA20 + d1/h4 bull bools from market_data.

    Surfaced in confidence_breakdown["pre_scoring_context"] so the
    v5_PIA-vs-v4 comparison logger can read them without re-deriving
    from D1/H4 cache. Cheap, additive — no schema migration. Called
    from BOTH stand-aside and ARMED paths so the field is always
    present regardless of state.

    Any field that's missing or unparseable is None (never raises).
    """
    if not market_data:
        return {}
    out: Dict[str, Any] = {}
    try:
        d1 = market_data.get("d1_candles") or []
        h4 = market_data.get("h4_candles") or []
        d1_close = float(d1[-1]["close"]) if d1 else None
        h4_close = float(h4[-1]["close"]) if h4 else None
        d1_ema20 = market_data.get("d1_ema_20")
        h4_ema20 = market_data.get("h4_ema_20")
        d1_ema20_f = float(d1_ema20) if d1_ema20 is not None else None
        h4_ema20_f = float(h4_ema20) if h4_ema20 is not None else None
        out["d1_close"]  = d1_close
        out["h4_close"]  = h4_close
        out["d1_ema20"] = d1_ema20_f
        out["h4_ema20"] = h4_ema20_f
        out["d1_bull"]  = (d1_close > d1_ema20_f) if (d1_close is not None and d1_ema20_f is not None) else None
        out["h4_bull"]  = (h4_close > h4_ema20_f) if (h4_close is not None and h4_ema20_f is not None) else None
    except (TypeError, ValueError, KeyError, IndexError):
        return out  # whatever we got is what we got
    return out


def _build_stand_aside(
    pair: str, session: str, now_utc: datetime, reason: str,
    plan: Optional[Dict[str, Any]] = None,
    market_data: Optional[Dict[str, Any]] = None,
) -> BriefingV5:
    """Build a STAND_ASIDE briefing — no scoring needed, all numerics zeroed.

    market_data (when available) is used to populate
    confidence_breakdown["pre_scoring_context"] with d1/h4 close + EMA20
    + bull bools, so the comparison logger can distinguish
    insufficient_h4_bars from d1_h4_bias_disagree without re-deriving.
    """
    plan = plan or {}
    breakdown: Dict[str, Any] = {}
    ctx = _pre_scoring_context(market_data)
    if ctx:
        breakdown["pre_scoring_context"] = ctx
    return BriefingV5(
        schema_version          = "v5_pia",
        pair                    = pair.upper(),
        session                 = session,
        generated_at_utc        = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        valid_until_utc         = _valid_until_utc(now_utc, session).strftime("%Y-%m-%dT%H:%M:%SZ"),
        direction               = "STAND_ASIDE",
        state                   = "STAND_ASIDE",
        confidence              = 0,
        confidence_bucket       = "STAND_ASIDE",
        confidence_breakdown    = breakdown,
        bias_anchor             = plan.get("bias_anchor"),
        bias_anchor_label       = plan.get("bias_anchor_label"),
        entry                   = None,
        stop                    = None,
        target                  = None,
        rr                      = 0.0,
        stop_structural_level   = None,
        target_structural_level = None,
        support_levels          = list(plan.get("support_levels") or []),
        resistance_levels       = list(plan.get("resistance_levels") or []),
        rationale               = None,  # phase 2 LLM
        stand_aside_reason      = reason,
        news_in_window          = False,
        news_event              = None,
        execution               = {
            "min_confidence_to_arm": BRIEFING_EXECUTION_MIN_CONFIDENCE,
            "executed":              False,
            "executed_at_utc":       None,
            "deal_id":               None,
            "outcome":               None,
        },
    )


def _write_briefing(briefing: BriefingV5, now_utc: datetime) -> Path:
    """Validate + atomically write JSON. Returns the written path.

    Atomic write: open .tmp, write, fsync the file descriptor, rename
    over the target. Survives a process kill mid-write — readers either
    see the previous JSON (if any) or the new one, never a torn file.
    The two-write pattern in generate_briefing_v5 calls this twice:
    first with rationale=None, then again after the LLM returns.
    """
    briefing.validate()
    path = _briefing_path(briefing.pair, now_utc, briefing.session)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(briefing.to_dict(), indent=2, default=str)
    # Write + fsync via low-level os calls so we don't depend on the
    # file object's __exit__ semantics across Python implementations.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(str(tmp), str(path))
    return path


def generate_briefing_v5(
    pair: str, session: str, now_utc: Optional[datetime] = None,
    *,
    market_data: Optional[Dict[str, Any]] = None,
    news_calendar: Optional[list] = None,
    write_to_disk: bool = True,
) -> BriefingV5:
    """Generate a v5 briefing.

    The default path (market_data=None) calls the runtime
    assemble_v5_data_package which requires morning_briefing.start() to
    have been called first. Tests / dry-runs pass a pre-built market_data
    dict to bypass that requirement.

    write_to_disk is False in tests; True everywhere else.
    """
    now_utc = now_utc or datetime.now(timezone.utc)

    # ── 1. Assemble market_data ──────────────────────────────────────────
    if market_data is None:
        from briefing.v5_pia.data_package import assemble_v5_data_package
        market_data = assemble_v5_data_package(pair, session, now_utc)
        if market_data is None:
            # No market_data → no pre_scoring_context to surface; comparison
            # logger will see {} and infer data_unavailable from the reason.
            briefing = _build_stand_aside(pair, session, now_utc, "data_unavailable")
            if write_to_disk:
                _write_briefing(briefing, now_utc)
            return briefing

    # ── 2. News + phase4 from market_data ────────────────────────────────
    news = list(news_calendar) if news_calendar is not None else list(market_data.get("news_events") or [])
    phase4 = str(market_data.get("phase4_structure") or "NEUTRAL")

    # ── 3. Build trade plan ──────────────────────────────────────────────
    plan = build_trade_plan(pair, session, market_data, now_utc)

    if plan["direction"] == "STAND_ASIDE":
        briefing = _build_stand_aside(
            pair, session, now_utc,
            plan.get("stand_aside_reason") or "stand_aside",
            plan, market_data,
        )
        if write_to_disk:
            # Two-write pattern even on STAND_ASIDE so the LLM gets a
            # chance to explain why confluence failed (per PIA system
            # prompt). If the LLM crashes, the deterministic STAND_ASIDE
            # is already on disk from the first write.
            _write_briefing(briefing, now_utc)
            briefing = _populate_rationale_and_rewrite(briefing, market_data, now_utc)
            # No telegram for STAND_ASIDE — Phase-2 spec says only ARMED/HIGH_CONVICTION.
        return briefing

    # ── 4. Score confidence — feed plan-derived levels into market_data ──
    md_for_scorer = dict(market_data)
    md_for_scorer.setdefault("support_levels", plan.get("support_levels") or [])
    md_for_scorer.setdefault("resistance_levels", plan.get("resistance_levels") or [])
    md_for_scorer.setdefault("h4_swing_highs_recent", plan.get("h4_swing_highs_recent") or [])
    md_for_scorer.setdefault("h4_swing_lows_recent", plan.get("h4_swing_lows_recent") or [])

    breakdown = score_confidence(
        pair        = pair,
        direction   = plan["direction"],
        entry       = plan["entry"],
        stop        = plan["stop"],
        target      = plan["target"],
        market_data = md_for_scorer,
        news_calendar = news,
        phase4_structure = phase4,
        now_utc     = now_utc,
    )

    # Surface the same pre_scoring_context shape into the ARMED breakdown
    # so the comparison logger reads from one place regardless of state.
    breakdown["pre_scoring_context"] = _pre_scoring_context(market_data)

    # ── 5. State derivation from bucket ──────────────────────────────────
    state = _state_from_bucket(breakdown["bucket"])

    # ── 6. Compose briefing ──────────────────────────────────────────────
    news_in_window = bool(breakdown["diagnostics"].get("news_clear", {}).get("hits_in_window"))
    news_event = None
    if news_in_window:
        hits = breakdown["diagnostics"]["news_clear"].get("hits_in_window") or []
        news_event = hits[0] if hits else None

    briefing = BriefingV5(
        schema_version          = "v5_pia",
        pair                    = pair.upper(),
        session                 = session,
        generated_at_utc        = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        valid_until_utc         = _valid_until_utc(now_utc, session).strftime("%Y-%m-%dT%H:%M:%SZ"),
        direction               = plan["direction"] if state == "ARMED" else "STAND_ASIDE",
        state                   = state,
        confidence              = int(breakdown["displayed"]),
        confidence_bucket       = breakdown["bucket"],
        confidence_breakdown    = breakdown,
        bias_anchor             = plan.get("bias_anchor"),
        bias_anchor_label       = plan.get("bias_anchor_label"),
        entry                   = plan.get("entry"),
        stop                    = plan.get("stop"),
        target                  = plan.get("target"),
        rr                      = float(plan.get("rr") or 0.0),
        stop_structural_level   = plan.get("stop_structural_level"),
        target_structural_level = plan.get("target_structural_level"),
        support_levels          = list(plan.get("support_levels") or []),
        resistance_levels       = list(plan.get("resistance_levels") or []),
        rationale               = None,  # phase 2 LLM
        stand_aside_reason      = (
            None if state == "ARMED"
            else (
                "; ".join(breakdown.get("hard_gate_failures") or []) or
                f"bucket={breakdown['bucket']}_below_arm_threshold"
            )
        ),
        news_in_window          = news_in_window,
        news_event              = news_event,
        execution               = {
            "min_confidence_to_arm": BRIEFING_EXECUTION_MIN_CONFIDENCE,
            "executed":              False,
            "executed_at_utc":       None,
            "deal_id":               None,
            "outcome":               None,
        },
    )

    if write_to_disk:
        # ── First write: deterministic plan, rationale=None ───────────────
        # Hits disk BEFORE the LLM call so a crash in rationale_writer
        # cannot lose the trade plan.
        path = _write_briefing(briefing, now_utc)
        logger.info(
            "[briefing.v5_pia] %s %s briefing v1 written: %s "
            "(state=%s, conf=%d, bucket=%s, rationale=null)",
            pair.upper(), session, path,
            briefing.state, briefing.confidence, briefing.confidence_bucket,
        )

        # ── Second write: same JSON with rationale populated (or null) ───
        briefing = _populate_rationale_and_rewrite(briefing, market_data, now_utc)

        # ── Telegram only on ARMED / HIGH_CONVICTION ──────────────────────
        if briefing.confidence_bucket in ("ARMED", "HIGH_CONVICTION"):
            _send_telegram_armed(briefing)

    return briefing


# ─────────────────────────────────────────────────────────────────────────────
# Rationale layer — atomic second write + Telegram notifier
# ─────────────────────────────────────────────────────────────────────────────

def _populate_rationale_and_rewrite(
    briefing: BriefingV5, market_data: Dict[str, Any], now_utc: datetime,
) -> BriefingV5:
    """Call the LLM rationale writer and re-write the briefing JSON with
    the rationale populated. On LLM failure the briefing keeps
    rationale=null and the (already-written) v1 file is rewritten
    unchanged — that's intentional: the second write is an idempotent
    upsert, not a separate file.
    """
    # Gate: skip the Anthropic rationale POST when disabled. The v1 file
    # written upstream (rationale=null) is the final state. Default ON.
    if os.getenv("V5_RATIONALE_ENABLED", "1") != "1":
        return briefing

    # Local import to avoid circulars at module import (rationale_writer
    # imports the schema, which imports pydantic, which is fine but the
    # local import keeps the orchestrator import-light for tests that
    # never touch rationale).
    from briefing.v5_pia.rationale_writer import write_rationale

    rationale: Optional[str] = None
    try:
        rationale = write_rationale(briefing, market_data)
    except Exception as exc:
        # rationale_writer.write_rationale() already swallows expected
        # failures and returns None; this catch is for genuinely
        # unexpected breakage. NO retries.
        logger.error(
            "RATIONALE_LLM_FAILED pair=%s session=%s exception_at_call=%s",
            briefing.pair, briefing.session, exc, exc_info=True,
        )
        rationale = None

    # Build a new BriefingV5 with rationale set. Pydantic validates; if
    # for some reason the construction fails, we keep the v1 on disk and
    # log loudly.
    try:
        new_dict = briefing.to_dict()
        new_dict["rationale"] = rationale
        rewritten = BriefingV5(**new_dict)
    except Exception as exc:
        logger.error(
            "[briefing.v5_pia] failed to rebuild briefing with rationale "
            "(pair=%s, session=%s): %s — keeping v1 on disk",
            briefing.pair, briefing.session, exc, exc_info=True,
        )
        return briefing

    path = _write_briefing(rewritten, now_utc)
    logger.info(
        "[briefing.v5_pia] %s %s briefing v2 written: %s "
        "(rationale_present=%s, len=%d)",
        rewritten.pair, rewritten.session, path,
        rationale is not None, len(rationale or ""),
    )
    return rewritten


def _send_telegram_armed(briefing: BriefingV5) -> None:
    """Send the BRIEFING_V5_ARMED telegram message. Failures are
    swallowed (telegram_alerts.send_telegram_message has its own retry).
    """
    try:
        from telegram_alerts import send_telegram_message
    except Exception as exc:
        logger.error("[briefing.v5_pia] telegram import failed: %s", exc)
        return

    rationale_block = briefing.rationale or "[rationale unavailable]"
    msg = (
        f"📋 Briefing v5 {briefing.pair} {briefing.session}\n"
        f"Direction: {briefing.direction}\n"
        f"Confidence: {briefing.confidence}% ({briefing.confidence_bucket})\n"
        f"Entry {briefing.entry} | Stop {briefing.stop} | "
        f"Target {briefing.target} | R:R {briefing.rr}\n\n"
        f"{rationale_block}"
    )
    try:
        send_telegram_message(msg, parse_mode="HTML")
    except Exception as exc:
        logger.error(
            "[briefing.v5_pia] telegram send failed pair=%s: %s",
            briefing.pair, exc,
        )


def generate_v5_for_session(session: str, pairs: Optional[list] = None) -> Dict[str, BriefingV5]:
    """Run generate_briefing_v5 for every pair in *pairs* (defaults to
    pair_config.PAIRS). Used by the morning_briefing scheduler hook.

    A failure in any pair is logged at ERROR, sent to Telegram, and
    re-raised. Caught silently at WARNING was the cause of the
    2026-05-06 NY miss where all 4 pairs failed to write JSON due to
    a directory ownership bug and no operator alert fired.
    """
    from pair_config import PAIRS
    pairs = pairs or list(PAIRS)
    out: Dict[str, BriefingV5] = {}
    now_utc = datetime.now(timezone.utc)
    for p in pairs:
        try:
            out[p] = generate_briefing_v5(p, session, now_utc)
        except Exception as exc:
            logger.error(
                "[briefing.v5_pia] %s %s briefing FAILED: %s: %s",
                p, session, type(exc).__name__, exc, exc_info=True,
            )
            try:
                from telegram_alerts import send_telegram_message
                send_telegram_message(
                    "🚨 <b>v5_pia write FAILED</b>\n"
                    f"pair=<code>{p}</code> session=<code>{session}</code>\n"
                    f"<code>{type(exc).__name__}</code>: {exc}",
                    parse_mode="HTML",
                )
            except Exception as tg_exc:
                logger.error(
                    "[briefing.v5_pia] telegram alert failed for %s %s: %s",
                    p, session, tg_exc,
                )
            raise
    return out
