#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
read_briefing.py — Human-readable formatter for morning briefing JSON files.

Usage:
    python3 read_briefing.py                  # most recent session today
    python3 read_briefing.py --session London # specific session
    python3 read_briefing.py --date 2026-03-18 --session NY

Output is also returned as a string from format_briefings() for use by other modules.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG_DIR  = Path(os.getenv("LOG_DIR", "/opt/tradingbot/logs"))
SYMBOLS  = ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]
SESSIONS = [
    "Asian",        # ~22-00 UTC prior day / early-morning bracket
    "London",       # ~05:30 UTC — pre-open morning briefing
    "London_Open",  # ~08:00 UTC — at/just-after London cash open
    "Mid-session",  # ~10-11 UTC — mid-day update
    "NY",           # ~12:30 UTC — NY cash open
    "NY_Data",      # ~14:00 UTC — US data-release window briefing
    "NY_Mid",       # ~16:00 UTC — mid-NY update
]                   # chronological order; _latest_session_for_date reverses this
WIDTH    = 55


# ─────────────────────────────────────────────────────────────────────────────
# File helpers
# ─────────────────────────────────────────────────────────────────────────────

def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _briefing_path(symbol: str, date: str, session: str) -> Path:
    return LOG_DIR / f"briefing_{symbol}_{date}_{session}.json"


def _latest_session_for_date(symbol: str, date: str) -> Optional[str]:
    """Return the most recently written session name for symbol/date, or None."""
    for session in reversed(SESSIONS):          # NY → London → Asian
        if _briefing_path(symbol, date, session).exists():
            return session
    return None


def _load(symbol: str, date: str, session: str) -> Optional[dict]:
    path = _briefing_path(symbol, date, session)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        return {"_load_error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────────────────────

def _bar() -> str:
    return "═" * WIDTH


def _fmt_filter(sf: dict) -> str:
    allow_buys  = sf.get("allow_buys",  True)
    allow_sells = sf.get("allow_sells", True)
    if allow_buys and allow_sells:
        return "BUYS AND SELLS"
    if allow_buys:
        return "BUYS ONLY"
    if allow_sells:
        return "SELLS ONLY"
    return "ALL TRADES BLOCKED"


def _fmt_levels(vals) -> str:
    if not vals:
        return "—"
    try:
        return " | ".join(str(v) for v in vals)
    except Exception:
        return str(vals)


def _fmt_zones(zones) -> str:
    if not zones:
        return "None"
    parts = []
    for z in zones:
        try:
            parts.append(f"{z[0]}–{z[1]}")
        except Exception:
            parts.append(str(z))
    return "  |  ".join(parts)


def _fmt_trading_plans(plans) -> str:
    if not plans:
        return ""
    lines = []
    lines.append("")
    lines.append("  Trading Plans:")
    for plan in plans:
        try:
            rank       = plan.get("rank", "?")
            label      = plan.get("label", "—")
            prob       = plan.get("probability", "?")
            prob_pct   = f"{int(float(prob)*100)}%" if prob != "?" else "?"
            confidence = plan.get("confidence", "?")
            bias       = plan.get("bias", "?")
            trigger    = plan.get("entry_trigger", "—")
            ez         = plan.get("entry_zone") or []
            ez_str     = f"{ez[0]}–{ez[1]}" if len(ez) == 2 else str(ez)
            sl         = plan.get("stop_loss", "—")
            targets    = plan.get("targets") or []
            tgt_str    = " / ".join(str(t) for t in targets) if targets else "—"
            rr         = plan.get("risk_reward", "—")
            inv        = plan.get("invalidation", "—")
            notes      = plan.get("notes", "")
            lines.append(f"    #{rank} [{confidence}] {label} ({prob_pct}) — {bias}")
            lines.append(f"       Trigger:    {trigger}")
            lines.append(f"       Entry zone: {ez_str}  |  SL: {sl}  |  Targets: {tgt_str}  |  R:R {rr}")
            lines.append(f"       Inv:        {inv}")
            if notes:
                lines.append(f"       Notes:      {notes}")
        except Exception:
            lines.append(f"    {plan}")
    return "\n".join(lines)


def _fmt_news(news_risk: str, events) -> str:
    base = str(news_risk or "NONE")
    if not events:
        return base
    try:
        first = events[0]
        return f"{base} — {first.get('event_name', '')} {first.get('time', '')} UTC"
    except Exception:
        return base


def _fmt_briefing_time(raw: str) -> str:
    """Parse ISO8601 briefing_time → 'Wed 19 Mar 2026 | 07:00 UTC'."""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%a %d %b %Y | %H:%M UTC")
    except Exception:
        return str(raw)


def _format_one(symbol: str, briefing: dict, session: str) -> str:
    lines = []
    lines.append(_bar())

    # Header
    sym_label = f"  {symbol} — {session} Session"
    lines.append(sym_label)
    bt = _fmt_briefing_time(briefing.get("briefing_time", ""))
    lines.append(f"  {bt}")
    lines.append(_bar())

    # Core. daily_bias = D1 multi-day trend; session_bias = today's expected
    # direction (these can disagree by design — see schema). bias_confidence
    # tracks session_bias (the bias_reasoning text is session-level), so it
    # is attached to Session Bias only.
    daily_bias   = briefing.get("daily_bias", "?")
    session_bias = briefing.get("session_bias", "?")
    conf         = briefing.get("bias_confidence", "?")
    sess_exp     = briefing.get("session_expectation", "?")
    news_r       = briefing.get("news_risk", "NONE")
    news_evs     = briefing.get("news_events", [])

    lines.append(f"  D1 Trend:     {daily_bias}")
    lines.append(f"  Session Bias: {session_bias} (confidence: {conf})")
    lines.append(f"  Session Mode: {sess_exp}")
    lines.append(f"  News Risk:    {_fmt_news(news_r, news_evs)}")

    # Reasoning (wrapped at ~50 chars)
    reason = briefing.get("bias_reasoning", "")
    if reason:
        lines.append("")
        lines.append(f"  Reasoning:   {reason}")

    # Key levels
    kl = briefing.get("key_levels") or {}
    resistance = kl.get("resistance") or []
    support    = kl.get("support")    or []
    lines.append("")
    lines.append("  Key Levels:")
    lines.append(f"    Resistance: {_fmt_levels(resistance)}")
    lines.append(f"    Support:    {_fmt_levels(support)}")

    # No-trade zones
    ntz = briefing.get("no_trade_zones") or []
    lines.append("")
    lines.append(f"  No-Trade Zones: {_fmt_zones(ntz)}")

    # Scenarios
    scenarios = briefing.get("scenarios") or []
    if scenarios:
        lines.append("")
        lines.append("  Scenarios:")
        for i, sc in enumerate(scenarios, 1):
            label = sc.get("label", f"Scenario {i}")
            prob  = sc.get("probability", "?")
            prob_pct = f"{int(float(prob)*100)}%" if prob != "?" else "?"
            trig  = sc.get("trigger", "—")
            tgt   = sc.get("target", "—")
            inv   = sc.get("invalidation", "—")
            lines.append(f"    {i}. {label} ({prob_pct})")
            lines.append(f"       Trigger: {trig}")
            lines.append(f"       Target:  {tgt}")
            lines.append(f"       Inv:     {inv}")

    # Trading plans
    plans = briefing.get("trading_plans") or []
    plan_block = _fmt_trading_plans(plans)
    if plan_block:
        lines.append(plan_block)

    # Plan summary
    plan_summary = briefing.get("plan_summary", "")
    if plan_summary:
        lines.append("")
        lines.append(f"  Best Trade:  {plan_summary}")

    # Signal filter
    sf = briefing.get("signal_filter") or {}
    lines.append("")
    lines.append(f"  Signal Filter: {_fmt_filter(sf)}")
    sf_notes = sf.get("notes", "")
    if sf_notes:
        lines.append(f"  Note: {sf_notes}")

    lines.append(_bar())
    return "\n".join(lines)


def _format_missing(symbol: str, session: str, date: str) -> str:
    lines = [
        _bar(),
        f"  {symbol} — {session} Session",
        f"  No briefing file found for {date}",
        f"  (expected: briefing_{symbol}_{date}_{session}.json)",
        _bar(),
    ]
    return "\n".join(lines)


def _format_error(symbol: str, session: str, error: str) -> str:
    lines = [
        _bar(),
        f"  {symbol} — {session} Session",
        f"  ERROR loading briefing: {error}",
        _bar(),
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def format_briefings(session: Optional[str] = None, date: Optional[str] = None) -> str:
    """
    Format all symbol briefings for the given session and date.

    session : "Asian", "London", or "NY". If None, uses most recently written
              briefing for each symbol independently.
    date    : "YYYY-MM-DD". Defaults to today UTC.

    Returns a single formatted string suitable for printing or emailing.
    """
    date = date or _utc_today()
    blocks = []

    for sym in SYMBOLS:
        # Resolve session per-symbol if not specified
        resolved_session = session or _latest_session_for_date(sym, date)

        if resolved_session is None:
            blocks.append(
                _format_missing(sym, session or "any session", date)
            )
            continue

        briefing = _load(sym, date, resolved_session)

        if briefing is None:
            blocks.append(_format_missing(sym, resolved_session, date))
        elif "_load_error" in briefing:
            blocks.append(_format_error(sym, resolved_session, briefing["_load_error"]))
        else:
            blocks.append(_format_one(sym, briefing, resolved_session))

    return "\n\n".join(blocks)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Read today's FX morning briefings")
    parser.add_argument(
        "--session",
        choices=["Asian", "London", "NY"],
        default=None,
        help="Session to display. Defaults to most recent for each symbol.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date in YYYY-MM-DD format. Defaults to today UTC.",
    )
    args = parser.parse_args()
    print(format_briefings(session=args.session, date=args.date))


if __name__ == "__main__":
    main()
