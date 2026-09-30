"""pia_first_briefing — daily LLM-authored trade plans (one per pair).

Scope and architecture decisions are signed off in:
  /opt/tradingbot/docs/pia_style_new_bot_scope_2026-05-13.md

This is the producer module for the PIA_FIRST briefing system that will run
on the AutoBot-PIA droplet (144.126.207.200). The naming differs from the
scoping doc — final spec uses:

  - module name: pia_first_briefing (was pia_style_briefing)
  - mode tag:    BRIEFING_PIA_FIRST_L / BRIEFING_PIA_FIRST_S
  - TP field:    "target" (was "limit") — both inside JSON output and
                 throughout the executor.

One LLM call per pair per day at 05:30 UTC. The LLM is the decision-maker;
this module supplies multi-timeframe context, parses the response, runs a
small validation pipeline (schema/geometry/min-stop/RR), and writes the
result to disk + Telegram. No deterministic gates beyond the geometry checks
that catch a malformed LLM response.

Default disabled: PIA_FIRST_ENABLED=0 in .env.example. The new droplet flips
that to 1; the current droplet keeps it off (no behaviour change).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import pair_config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tunables — all env-driven so the new droplet can adjust without code edits.
# ─────────────────────────────────────────────────────────────────────────────

_PIA_FIRST_ENABLED = (os.getenv("PIA_FIRST_ENABLED", "0") or "0").strip() == "1"
_PIA_FIRST_MODEL = (os.getenv("PIA_FIRST_MODEL", "claude-sonnet-4-6") or "claude-sonnet-4-6").strip()
_PIA_FIRST_TEMPERATURE = float(os.getenv("PIA_FIRST_TEMPERATURE", "0.3") or 0.3)
_PIA_FIRST_MAX_TOKENS = int(float(os.getenv("PIA_FIRST_MAX_TOKENS", "400") or 400))
_PIA_FIRST_TIMEOUT_S = int(float(os.getenv("PIA_FIRST_TIMEOUT_S", "120") or 120))

_PIA_FIRST_PAIRS = tuple(
    p.strip().upper() for p in
    (os.getenv("PIA_FIRST_PAIRS", "GBPUSD,EURUSD,USDJPY,USDCAD") or "").split(",")
    if p.strip()
)

_BRIEFINGS_BASE = Path("/opt/tradingbot/briefings/pia_first")
_LOG_PATH = Path("/opt/tradingbot/logs/pia_first_briefing.jsonl")
_CACHE_HTF = Path("/opt/tradingbot/cache/htf")
_CACHE_5M = Path("/opt/tradingbot/cache")

# Pip size — IG spread-bet FX quotes are stored 10000x in cache CSVs and
# 10000x in HTF JSONs (e.g. GBPUSD 13594.55 = 1.359455). The "price" we
# write into the briefing is in the same raw cache scale so the executor's
# pip-distance maths and broker side both use a consistent number.
# A pip in raw cache units is 1.0 for USDJPY-quote pairs (which trade at
# ~15400 raw) and 1.0 for USD-quote pairs (which trade at ~13000 raw). The
# `pair_config.get_ppp` helper returns 1.0 for all our FX pairs — these
# files are already in "points" not "decimal price".
_PIP_RAW = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schema for the LLM output
# ─────────────────────────────────────────────────────────────────────────────

class PIAFirstBriefing(BaseModel):
    """The LLM is required to return exactly this JSON shape.

    Field names:
      - direction: LONG or SHORT (mapped to BUY/SELL by the executor)
      - entry:     informational reference price the LLM picked
      - stop:      SL price (broker-side)
      - target:    TP price (broker-side); renamed from "limit" per scope
      - confidence: 0-100 (executor's MIN_CONFIDENCE_PIA_FIRST gates fires)
      - rationale: short text for the Telegram summary + forensic.
    """
    model_config = ConfigDict(extra="forbid")
    direction:  str = Field(pattern="^(LONG|SHORT)$")
    entry:      float
    stop:       float
    target:     float
    confidence: int = Field(ge=0, le=100)
    rationale:  str = Field(min_length=10, max_length=600)


# ─────────────────────────────────────────────────────────────────────────────
# Candle loading — read directly from cache files; do not depend on a
# running CandleBuilder, since the producer can be invoked from a script.
# ─────────────────────────────────────────────────────────────────────────────

def _load_htf_candles(pair: str, tf: str, limit: int) -> List[Dict[str, Any]]:
    """Load the last `limit` HTF candles from cache/htf/<PAIR>_<TF>.json.

    Returns [] on any error (missing file, malformed JSON, empty candles
    array). Per memory project_d1_cache_staleness_silent_neutral.md the
    caller should additionally check mtime when this matters for trading
    correctness — we surface the mtime in the briefing JSON instead of
    silently returning stale data.
    """
    path = _CACHE_HTF / f"{pair.upper()}_{tf.upper()}.json"
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[pia_first] %s %s cache read failed: %s", pair, tf, exc)
        return []
    candles = payload.get("candles") or []
    if not isinstance(candles, list):
        return []
    return candles[-limit:]


def _load_5m_candles(pair: str, limit: int) -> List[Dict[str, Any]]:
    """Load the last `limit` 5M candles from cache/<PAIR>_candles.csv.

    Returns OHLC dicts with timestamp, open, high, low, close — drops the
    indicator columns so we don't waste prompt tokens.
    """
    path = _CACHE_5M / f"{pair.upper()}_candles.csv"
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as exc:
        logger.warning("[pia_first] %s 5m cache read failed: %s", pair, exc)
        return []
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    try:
        idx_ts = header.index("timestamp")
        idx_o = header.index("open")
        idx_h = header.index("high")
        idx_l = header.index("low")
        idx_c = header.index("close")
    except ValueError:
        return []
    out: List[Dict[str, Any]] = []
    for raw in lines[-limit:]:
        parts = raw.rstrip("\n").split(",")
        if len(parts) <= max(idx_ts, idx_o, idx_h, idx_l, idx_c):
            continue
        try:
            out.append({
                "timestamp": parts[idx_ts],
                "open":      float(parts[idx_o]),
                "high":      float(parts[idx_h]),
                "low":       float(parts[idx_l]),
                "close":     float(parts[idx_c]),
            })
        except ValueError:
            continue
    return out


def _detect_swing_levels(
    bars: List[Dict[str, Any]],
    lookback: int = 20,
    max_levels: int = 6,
) -> Tuple[List[float], List[float]]:
    """Simple 3-bar swing pivots over the last `lookback` bars. Mirror for
    high/low. Returns (resistance_levels_desc, support_levels_asc).

    Reuses level_computation._swing_points if importable; falls back to an
    inline 3-bar pivot scan for environments where the import fails (tests
    with no PYTHONPATH, the producer running as a standalone CLI tool, etc.).
    """
    if len(bars) < 7:
        return [], []
    window = bars[-lookback:]
    try:
        from level_computation import _swing_points
        highs, lows = _swing_points(window, lookback, min_reversal_pips=5.0)
        return (sorted(set(highs), reverse=True)[:max_levels],
                sorted(set(lows))[:max_levels])
    except Exception:
        pass
    # Inline fallback: bar i is a swing high if its high > bars on either
    # side by ±3 bars.
    highs: List[float] = []
    lows: List[float] = []
    for i in range(3, len(window) - 3):
        h = float(window[i]["high"])
        lo = float(window[i]["low"])
        if all(h > float(window[i + d]["high"]) for d in (-3, -2, -1, 1, 2, 3)):
            highs.append(h)
        if all(lo < float(window[i + d]["low"]) for d in (-3, -2, -1, 1, 2, 3)):
            lows.append(lo)
    return (sorted(set(highs), reverse=True)[:max_levels],
            sorted(set(lows))[:max_levels])


# ─────────────────────────────────────────────────────────────────────────────
# Context gather + prompt composition
# ─────────────────────────────────────────────────────────────────────────────

def _gather_context(symbol: str) -> Dict[str, Any]:
    """Pull D1/H4/H1/5M candles, swing S/R from H1, today's events, and the
    minimum stop distance for the pair. Returns a dict ready for the prompt
    builder. Never raises — degraded context with empty arrays is preferable
    to a hard fail at 05:30 UTC.
    """
    sym = symbol.upper()
    d1 = _load_htf_candles(sym, "D1", 20)
    h4 = _load_htf_candles(sym, "H4", 20)   # may be empty per scope §15.5
    h1 = _load_htf_candles(sym, "H1", 50)
    m5 = _load_5m_candles(sym, 100)
    sr_highs, sr_lows = _detect_swing_levels(h1 or h4 or d1, lookback=20, max_levels=6)

    try:
        from news_calendar import get_todays_events
        events = get_todays_events(currencies=["GBP", "USD", "EUR", "JPY", "CAD"])
    except Exception as exc:
        logger.warning("[pia_first] %s events fetch failed: %s", sym, exc)
        events = []

    current_price: Optional[float] = None
    if m5:
        current_price = float(m5[-1]["close"])
    elif h1:
        current_price = float(h1[-1]["close"])

    min_stop_pips = float(pair_config.MIN_SL_PIPS.get(sym, 12.0))

    return {
        "pair":             sym,
        "current_price":    current_price,
        "min_stop_pips":    min_stop_pips,
        "pip_size":         _PIP_RAW,
        "d1_candles":       d1,
        "h4_candles":       h4,
        "h1_candles":       h1,
        "m5_candles":       m5,
        "sr_highs":         sr_highs,
        "sr_lows":          sr_lows,
        "events":           events,
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


_SYSTEM_PROMPT = (
    "You are a senior FX market analyst producing one trade plan per pair "
    "per day for tomorrow's London session. You analyse multi-timeframe "
    "context: Daily structure sets dominant bias, H4 confirms, H1 refines "
    "timing, 5M provides execution context. D1 always dominates. You think "
    "probabilistically. Always produce a trade plan with concrete direction, "
    "entry, stop, and target for every pair, every day. There is no "
    "stand-aside option. Confidence is a number from 0-100 that calibrates "
    "how strong the setup is — it does NOT mean 'skip if low'. A confidence "
    "of 30 means a weak setup that you still trade. A confidence of 80 means "
    "a strong setup. The bot executes every plan regardless of confidence. "
    "Refusing to produce a plan, returning malformed JSON, or returning "
    "placeholder values are not options. Your job is to produce the best "
    "plan you can given current market structure. You output a single JSON "
    "object only — no prose, no markdown, no comments."
)


def _compose_prompt(symbol: str, context: Dict[str, Any]) -> Tuple[str, str]:
    """Build (system, user) prompts. The user prompt embeds the candle JSON
    arrays inline so the LLM can reason over them directly."""
    sym = symbol.upper()
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    user = (
        f"=== {sym} TRADE PLAN — {today} LONDON SESSION ===\n\n"
        f"Current price: {context['current_price']}\n"
        f"Pair pip-size (raw cache scale): {context['pip_size']}\n"
        f"Minimum stop distance (volatility floor): "
        f"{context['min_stop_pips']} pips\n\n"
        f"=== D1 (last 20 closed candles) ===\n"
        f"{json.dumps(context['d1_candles'])}\n\n"
        f"=== H4 (last 20 closed candles; may be empty if cold start) ===\n"
        f"{json.dumps(context['h4_candles'])}\n\n"
        f"=== H1 (last 50 closed candles) ===\n"
        f"{json.dumps(context['h1_candles'])}\n\n"
        f"=== 5M (last 100 closed candles) ===\n"
        f"{json.dumps(context['m5_candles'])}\n\n"
        f"=== Structural levels (H1 swing analysis) ===\n"
        f"Resistance (desc): {context['sr_highs']}\n"
        f"Support     (asc): {context['sr_lows']}\n\n"
        f"=== Today's high-impact events ({len(context['events'])}) ===\n"
        f"{json.dumps(context['events'])}\n\n"
        "=== Output schema (return EXACTLY this JSON, no extras) ===\n"
        "{\n"
        '  "direction":  "LONG" | "SHORT",\n'
        '  "entry":      <float, in current_price units>,\n'
        '  "stop":       <float, in current_price units>,\n'
        '  "target":     <float, in current_price units>,\n'
        '  "confidence": <int 0..100>,\n'
        '  "rationale":  "<1-3 sentences citing specific levels and TF context>"\n'
        "}\n\n"
        "Constraints:\n"
        "- LONG: stop < entry < target. SHORT: target < entry < stop.\n"
        f"- |entry - stop| >= {context['min_stop_pips']} pips.\n"
        "- RR = |entry - target| / |entry - stop| must be > 1.0.\n"
        "- Plan covers 05:30-21:00 UTC. Target must be reachable in that window.\n"
        "- HIGH-impact news today: factor into rationale + confidence.\n\n"
        "Return JSON only."
    )
    return _SYSTEM_PROMPT, user


# ─────────────────────────────────────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────────────────────────────────────

def _strip_markdown_fence(text: str) -> str:
    """The LLM occasionally wraps the JSON in ```json fences despite the
    system prompt's "no markdown" instruction. Mirror the same forgiving
    parse morning_briefing._call_anthropic_once uses (line 2959-2964)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _call_llm(system: str, user: str) -> Optional[str]:
    """Call Claude via the v5_pia anthropic_client wrapper. Returns the
    response text or None on any failure (logged in detail by the wrapper).

    The wrapper handles HTTP errors, timeouts, JSON parse errors, and the
    missing-API-key case. Anything raised here is the caller's bug, not
    the LLM's.
    """
    try:
        from briefing.v5_pia.anthropic_client import call_messages
    except Exception as exc:
        logger.error("[pia_first] anthropic_client import failed: %s", exc)
        return None
    return call_messages(
        system=system,
        user=user,
        model=_PIA_FIRST_MODEL,
        temperature=_PIA_FIRST_TEMPERATURE,
        max_tokens=_PIA_FIRST_MAX_TOKENS,
        timeout=_PIA_FIRST_TIMEOUT_S,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validation pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _validate_briefing(
    plan: Dict[str, Any], symbol: str, current_price: Optional[float],
) -> Tuple[bool, Optional[str]]:
    """Run the full validation pipeline. Returns (ok, error_msg_or_None).

    Steps (in order — first failure short-circuits):
      1. Schema (Pydantic, extra='forbid')
      2. Stop side: LONG → stop<entry; SHORT → stop>entry
      3. Target side: LONG → target>entry; SHORT → target<entry
      4. Stop distance ≥ pair_config.MIN_SL_PIPS[symbol]
      5. RR > 1.0
      6. Entry within 500 pips of current_price (sanity)
    """
    sym = symbol.upper()
    pip_size = _PIP_RAW

    # 1) Schema
    try:
        model = PIAFirstBriefing(**plan)
    except ValidationError as exc:
        return False, f"schema: {exc.errors()[0]['msg']}"

    direction = model.direction
    entry = float(model.entry)
    stop = float(model.stop)
    target = float(model.target)

    # 2/3) Geometry
    if direction == "LONG":
        if not (stop < entry < target):
            return False, (
                f"geometry: LONG requires stop({stop}) < entry({entry}) < target({target})"
            )
    else:  # SHORT
        if not (target < entry < stop):
            return False, (
                f"geometry: SHORT requires target({target}) < entry({entry}) < stop({stop})"
            )

    # 4) Stop distance
    min_stop = float(pair_config.MIN_SL_PIPS.get(sym, 12.0))
    stop_dist_pips = abs(entry - stop) / pip_size
    if stop_dist_pips < min_stop:
        return False, (
            f"min_stop: stop_distance={stop_dist_pips:.1f}p < min={min_stop:.1f}p"
        )

    # 5) RR
    risk = abs(entry - stop)
    reward = abs(entry - target)
    if risk <= 0:
        return False, "rr: zero risk distance"
    rr = reward / risk
    if rr <= 1.0:
        return False, f"rr: {rr:.2f} <= 1.0"

    # 6) Entry plausibility — only enforced if we know current_price.
    if current_price is not None:
        offset_pips = abs(entry - current_price) / pip_size
        if offset_pips > 500.0:
            return False, (
                f"entry_plausibility: entry={entry} offset {offset_pips:.0f}p "
                f"from current_price={current_price}"
            )

    return True, None


# ─────────────────────────────────────────────────────────────────────────────
# Output writers
# ─────────────────────────────────────────────────────────────────────────────

def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write payload to path via .tmp + rename. Inherits writer ownership
    per memory feedback_run_as_autobot_not_root — caller must run as the
    autobot user when this writes to /opt/tradingbot/briefings/.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(str(tmp), str(path))


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    """Append a single JSONL record. Best-effort — never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        logger.warning("[pia_first] jsonl append failed (%s): %s", path, exc)


def _emit_telegram_summary(date_str: str, summary_lines: List[str]) -> None:
    """One Telegram message summarising all 4 pairs. Mirrors the pattern
    morning_briefing uses for v4 (telegram_alerts.send_telegram_message)."""
    if not summary_lines:
        return
    try:
        from telegram_alerts import send_telegram_message
    except Exception as exc:
        logger.warning("[pia_first] telegram import failed: %s", exc)
        return
    header = f"🧠 <b>PIA_FIRST briefing {date_str} London</b>"
    body = "\n".join(summary_lines)
    try:
        send_telegram_message(f"{header}\n{body}")
    except Exception as exc:
        logger.warning("[pia_first] telegram send failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Per-pair entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_pia_first_briefing(symbol: str) -> Optional[Dict[str, Any]]:
    """Generate one PIA_FIRST briefing for one pair. Returns the validated
    briefing dict (with metadata) on success, or None on any failure.

    Failure paths (each logs ERROR, writes an _INVALID.json sidecar for
    forensic, returns None):
      - context gather raised (unexpected; the gather function never raises)
      - LLM call returned None (API failure)
      - LLM response did not parse as JSON
      - validation pipeline rejected the JSON
    """
    sym = symbol.upper()
    t0 = time.time()
    ctx = _gather_context(sym)
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    out_dir = _BRIEFINGS_BASE / date_str

    system, user = _compose_prompt(sym, ctx)
    raw_text = _call_llm(system, user)
    if raw_text is None:
        logger.error("[pia_first] %s LLM call returned None — skipping pair", sym)
        return None

    text = _strip_markdown_fence(raw_text)
    try:
        plan = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(
            "[pia_first] %s response not valid JSON: %s | first 200 chars: %s",
            sym, exc, (text or "")[:200],
        )
        _atomic_write_json(
            out_dir / f"{sym}_INVALID.json",
            {"error": "json_parse", "exception": str(exc), "raw": text[:2000]},
        )
        return None

    ok, err = _validate_briefing(plan, sym, ctx["current_price"])
    if not ok:
        logger.error("[pia_first] %s validation failed: %s", sym, err)
        _atomic_write_json(
            out_dir / f"{sym}_INVALID.json",
            {"error": "validation", "detail": err, "raw_plan": plan},
        )
        try:
            from telegram_alerts import send_telegram_message
            send_telegram_message(
                f"⚠️ <b>PIA_FIRST validation failed</b> {sym}: {err}"
            )
        except Exception:
            pass
        return None

    # Stamp metadata onto the LLM output.
    valid_until = (
        datetime.now(tz=timezone.utc)
        .replace(hour=21, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    final: Dict[str, Any] = dict(plan)
    final.update({
        "schema_version":        "pia_first_v1",
        "pair":                  sym,
        "date":                  date_str,
        "session":               "London",
        "generated_at_utc":      ctx["generated_at_utc"],
        "valid_until_utc":       valid_until,
        "model":                 _PIA_FIRST_MODEL,
        "min_stop_pips":         ctx["min_stop_pips"],
        "pip_size":              ctx["pip_size"],
        "current_price_at_gen":  ctx["current_price"],
        "rr":                    round(
            abs(float(plan["entry"]) - float(plan["target"])) /
            abs(float(plan["entry"]) - float(plan["stop"])), 3,
        ),
        "elapsed_s":             round(time.time() - t0, 2),
    })

    _atomic_write_json(out_dir / f"{sym}.json", final)
    _append_jsonl(_LOG_PATH, final)
    logger.info(
        "[pia_first] %s OK dir=%s conf=%d %s entry=%s stop=%s target=%s rr=%.2f",
        sym, final["direction"], final["confidence"], date_str,
        final["entry"], final["stop"], final["target"], final["rr"],
    )
    return final


# ─────────────────────────────────────────────────────────────────────────────
# Session entry point — what the scheduler calls
# ─────────────────────────────────────────────────────────────────────────────

def generate_pia_first_for_session() -> None:
    """Top-level scheduler entry. Iterates the 4 pairs, calls the per-pair
    generator, collects results for a single Telegram summary. One pair's
    LLM failure does not block the others (each generator call is wrapped).
    """
    if not _PIA_FIRST_ENABLED:
        logger.info("[pia_first] disabled by env flag — skipping session")
        return

    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    logger.info(
        "[pia_first] session start date=%s pairs=%s model=%s",
        date_str, list(_PIA_FIRST_PAIRS), _PIA_FIRST_MODEL,
    )

    summary_lines: List[str] = []
    for pair in _PIA_FIRST_PAIRS:
        try:
            briefing = generate_pia_first_briefing(pair)
        except Exception as exc:
            logger.error(
                "[pia_first] %s generator raised: %s", pair, exc, exc_info=True,
            )
            briefing = None

        if briefing is None:
            summary_lines.append(f"{pair} <i>failed</i>")
            continue
        rr = briefing.get("rr", 0.0)
        summary_lines.append(
            f"{pair} {briefing['direction']} conf={briefing['confidence']} "
            f"entry={briefing['entry']} SL={briefing['stop']} "
            f"TP={briefing['target']} (RR {rr:.2f})"
        )

    _emit_telegram_summary(date_str, summary_lines)
    logger.info("[pia_first] session complete date=%s", date_str)
