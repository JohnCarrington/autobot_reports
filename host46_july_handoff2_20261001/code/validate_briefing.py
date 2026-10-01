#!/usr/bin/env python3
"""validate_briefing.py — Post-deploy sanity check for the briefing
schema (Phase 1 — ranked levels + plan expiry; Phase 2 — London/NY plan
split with london_condition gates).

Reads the four pair briefings for a given UTC date / session and emits a
consolidated report via Telegram. Falls back to a logfile if Telegram fails.

Usage:
  validate_briefing.py                     # today UTC, London, send Telegram
  validate_briefing.py --dry-run           # print to stdout
  validate_briefing.py --date 2026-04-27   # override date
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


PAIRS                    = ("GBPUSD", "EURUSD", "USDJPY", "USDCAD")
LOG_DIR                  = Path("/opt/tradingbot/logs")
ENV_FILE                 = Path("/opt/tradingbot/.env")

LEVEL_TYPES              = {"RESISTANCE", "SUPPORT", "PIVOT"}
LEVEL_ROLES              = {"primary", "secondary", "extension"}
LEVEL_INTENTS            = {"BOUNCE", "FADE", "BREAK"}
LEVEL_DIRECTIONS         = {"BUY", "SELL", "NONE"}
LEVEL_STRENGTHS          = {"HIGH", "MEDIUM", "LOW"}
LEVEL_CONFLUENCE_VOCAB   = {
    "PREV_DAY_HIGH", "PREV_DAY_LOW", "PREV_DAY_CLOSE",
    "WEEK_HIGH", "WEEK_LOW", "PREV_WEEK_HIGH", "PREV_WEEK_LOW",
    "ASIAN_HIGH", "ASIAN_LOW",
    "SWING_HIGH", "SWING_LOW",
    "BB_UPPER", "BB_LOWER",
    "EMA_50", "EMA_200",
    "ROUND_NUMBER", "DAILY_PIVOT", "VWAP",
}
LEVELS_MIN_COUNT         = 4
LEVELS_MAX_COUNT         = 6
LEVELS_MIN_SEPARATION    = 15.0
LEVELS_JUSTIFICATION_MAX = 30
BIAS_VALUES              = {"BULLISH", "BEARISH", "NEUTRAL"}

# Phase 2 — London/NY plan split + london_condition gating
PLAN_SESSIONS                  = {"London", "NY"}
LONDON_CONDITION_TYPES         = {
    "close_above", "close_below", "ranged", "swept_then_reversed", "held_at",
}
LONDON_CONDITION_NEEDS_TOL     = {"ranged", "held_at"}
LONDON_CONDITION_DESC_MAX_W    = 25
PLANS_PER_SESSION_MIN          = 2
PLANS_PER_SESSION_MAX          = 3
PLANS_TOTAL_MIN                = 4
PLANS_TOTAL_MAX                = 6
NY_COND_LEVEL_RANGE_TOL_PIPS   = 50.0  # NY condition.level must be within
                                       # ±50p of the levels[] price range

# Briefings run sequentially after 05:30 UTC; the slowest pair (USDCAD)
# can take 10-15 min on slow LLM days. The timer fires at 05:35, so wait
# for any missing files to land before validating to avoid false MISSING.
WAIT_FOR_BRIEFINGS_MAX_SEC     = 900   # 15 min budget
WAIT_FOR_BRIEFINGS_POLL_SEC    = 30


def _briefing_path(pair: str, date: str, session: str) -> Path:
    return LOG_DIR / f"briefing_{pair}_{date}_{session}.json"


def _wait_for_briefings(date: str, session: str) -> List[str]:
    """Poll until all 4 briefing files exist or the budget expires.

    Returns the list of pairs still missing at the deadline. Empty list
    means all 4 landed in time.
    """
    deadline = time.monotonic() + WAIT_FOR_BRIEFINGS_MAX_SEC
    while True:
        missing = [
            pair for pair in PAIRS
            if not _briefing_path(pair, date, session).exists()
        ]
        if not missing:
            return []
        if time.monotonic() >= deadline:
            return missing
        time.sleep(WAIT_FOR_BRIEFINGS_POLL_SEC)


def _load_env_telegram() -> Tuple[Optional[str], Optional[str]]:
    """Read TELEGRAM_TOKEN / TELEGRAM_CHAT_ID from /opt/tradingbot/.env if not
    already in the process environment. Returns (token, chat_id), either may
    be None.
    """
    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return token, chat_id
    if not ENV_FILE.exists():
        return token, chat_id
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k == "TELEGRAM_TOKEN" and not token:
                token = v
            elif k == "TELEGRAM_CHAT_ID" and not chat_id:
                chat_id = v
    except Exception:
        pass
    return token, chat_id


def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    """POST to Telegram. Returns True on success."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


# ─── Validation helpers ────────────────────────────────────────────────────

def _validate_levels(levels: Any, ref_price: Optional[float]) -> List[str]:
    """Return a list of human-readable violation strings (empty = OK)."""
    errs: List[str] = []
    if not isinstance(levels, list):
        return [f"levels[] is {type(levels).__name__}, not a list"]

    if not (LEVELS_MIN_COUNT <= len(levels) <= LEVELS_MAX_COUNT):
        errs.append(
            f"levels[] has {len(levels)} entries (want {LEVELS_MIN_COUNT}-{LEVELS_MAX_COUNT})"
        )

    cleaned: List[Dict[str, Any]] = []
    for idx, lv in enumerate(levels):
        if not isinstance(lv, dict):
            errs.append(f"level[{idx}] is not an object")
            continue
        # required fields
        for f in ("rank", "price", "type", "role", "confluence", "justification",
                  "intent", "trade_direction", "strength"):
            if f not in lv:
                errs.append(f"level[{idx}] missing field '{f}'")
        if any(f"level[{idx}]" in e for e in errs):
            continue

        try:
            rank = int(lv["rank"])
        except (TypeError, ValueError):
            errs.append(f"level[{idx}] rank={lv.get('rank')!r} not an integer")
            continue
        try:
            price = float(lv["price"])
        except (TypeError, ValueError):
            errs.append(f"level[{idx}] price={lv.get('price')!r} not numeric")
            continue

        if str(lv.get("type", "")).upper() not in LEVEL_TYPES:
            errs.append(f"level[{idx}] type={lv.get('type')!r} not in {sorted(LEVEL_TYPES)}")
        if str(lv.get("role", "")).lower() not in LEVEL_ROLES:
            errs.append(f"level[{idx}] role={lv.get('role')!r} not in {sorted(LEVEL_ROLES)}")
        if str(lv.get("intent", "")).upper() not in LEVEL_INTENTS:
            errs.append(f"level[{idx}] intent={lv.get('intent')!r} not in {sorted(LEVEL_INTENTS)}")
        if str(lv.get("trade_direction", "")).upper() not in LEVEL_DIRECTIONS:
            errs.append(
                f"level[{idx}] trade_direction={lv.get('trade_direction')!r} not in {sorted(LEVEL_DIRECTIONS)}"
            )
        if str(lv.get("strength", "")).upper() not in LEVEL_STRENGTHS:
            errs.append(
                f"level[{idx}] strength={lv.get('strength')!r} not in {sorted(LEVEL_STRENGTHS)}"
            )

        conf = lv.get("confluence")
        if not isinstance(conf, list) or not conf:
            errs.append(f"level[{idx}] confluence is empty/missing")
        else:
            unknown = [c for c in conf if str(c).upper() not in LEVEL_CONFLUENCE_VOCAB]
            if unknown:
                errs.append(f"level[{idx}] confluence has unknown tags {unknown}")

        just = str(lv.get("justification", "") or "").strip()
        if not just:
            errs.append(f"level[{idx}] justification is empty")
        else:
            wc = len(just.split())
            if wc > LEVELS_JUSTIFICATION_MAX:
                errs.append(
                    f"level[{idx}] justification has {wc} words (max {LEVELS_JUSTIFICATION_MAX})"
                )

        # price sanity vs ref
        if ref_price and ref_price > 0:
            if not (0.5 * ref_price <= price <= 2.0 * ref_price):
                errs.append(
                    f"level[{idx}] price={price:g} outside [0.5x..2x] of ref={ref_price:g}"
                )

        cleaned.append({"rank": rank, "price": price})

    if cleaned:
        cleaned.sort(key=lambda x: x["rank"])
        ranks = [x["rank"] for x in cleaned]
        if ranks != list(range(1, len(cleaned) + 1)):
            errs.append(f"ranks not contiguous 1..{len(cleaned)}: got {ranks}")
        if 1 not in ranks:
            errs.append("no level has rank=1")

        for i in range(len(cleaned) - 1):
            sep = abs(cleaned[i]["price"] - cleaned[i + 1]["price"])
            if sep < LEVELS_MIN_SEPARATION:
                errs.append(
                    f"adjacent ranks {cleaned[i]['rank']}-{cleaned[i+1]['rank']} only "
                    f"{sep:.1f}p apart (min {LEVELS_MIN_SEPARATION:g}p)"
                )

    return errs


def _validate_plan_expires_at(value: Any) -> Optional[str]:
    """Return None if the value matches the expires_at vocabulary, else an error string.

    Accepted forms:
      - 'end_of_day' (sentinel; executor maps to 21:00 UTC)
      - 'HH:MM' or 'HH:MMZ' (wall-clock today UTC, e.g. '12:30Z', '17:45Z')
      - Full ISO-8601 datetime (Z or +00:00 offset)
    """
    if value is None:
        return "missing"
    if not isinstance(value, str):
        return f"non-string value {value!r}"
    if value == "end_of_day":
        return None

    # HH:MM[Z] — wall-clock time-of-day, interpreted as today UTC.
    hhmm = value[:-1] if value.endswith("Z") else value
    try:
        datetime.strptime(hhmm, "%H:%M")
        return None
    except ValueError:
        pass

    # Full ISO-8601 — accept trailing Z or +00:00.
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return None
    except ValueError:
        return f"unrecognized value {value!r}"


def _validate_london_condition(
    cond: Any,
    plan_idx: int,
    plan_label: str,
    levels_lo: Optional[float],
    levels_hi: Optional[float],
) -> List[str]:
    """Validate one NY plan's london_condition object.

    Returns a list of error strings (empty = OK). When *levels_lo* /
    *levels_hi* are provided, condition.level is sanity-checked against
    that range ±NY_COND_LEVEL_RANGE_TOL_PIPS.
    """
    errs: List[str] = []
    if not isinstance(cond, dict):
        return [
            f"plan[{plan_idx}] {plan_label!r} NY plan requires london_condition object, "
            f"got {type(cond).__name__}"
        ]

    ctype = str(cond.get("type") or "").strip()
    if ctype not in LONDON_CONDITION_TYPES:
        errs.append(
            f"plan[{plan_idx}] {plan_label!r} london_condition.type={ctype!r} not in "
            f"{sorted(LONDON_CONDITION_TYPES)}"
        )
        return errs  # downstream checks need a known type

    lvl = cond.get("level")
    lvl_num: Optional[float] = None
    if not isinstance(lvl, (int, float)) or isinstance(lvl, bool):
        errs.append(
            f"plan[{plan_idx}] {plan_label!r} london_condition.level "
            f"must be numeric, got {lvl!r}"
        )
    else:
        lvl_num = float(lvl)

    if ctype in LONDON_CONDITION_NEEDS_TOL:
        tol = cond.get("tolerance_pips")
        if not isinstance(tol, (int, float)) or isinstance(tol, bool) or tol <= 0:
            errs.append(
                f"plan[{plan_idx}] {plan_label!r} london_condition.tolerance_pips "
                f"must be a positive number for type={ctype!r}, got {tol!r}"
            )

    desc = str(cond.get("description") or "").strip()
    if not desc:
        errs.append(
            f"plan[{plan_idx}] {plan_label!r} london_condition.description is required"
        )
    else:
        wc = len(desc.split())
        if wc > LONDON_CONDITION_DESC_MAX_W:
            errs.append(
                f"plan[{plan_idx}] {plan_label!r} london_condition.description has "
                f"{wc} words (max {LONDON_CONDITION_DESC_MAX_W})"
            )

    # Level-range sanity: condition references a price reasonably close to
    # the levels[] price set. Catches model hallucinations like a level of
    # 13530 when today's range is 13800-13900.
    if lvl_num is not None and levels_lo is not None and levels_hi is not None:
        lo_bound = levels_lo - NY_COND_LEVEL_RANGE_TOL_PIPS
        hi_bound = levels_hi + NY_COND_LEVEL_RANGE_TOL_PIPS
        if not (lo_bound <= lvl_num <= hi_bound):
            errs.append(
                f"plan[{plan_idx}] {plan_label!r} london_condition.level={lvl_num:g} "
                f"outside levels[] range {levels_lo:g}-{levels_hi:g} "
                f"(±{NY_COND_LEVEL_RANGE_TOL_PIPS:g}p tolerance)"
            )
    return errs


def _validate_briefing(b: Dict[str, Any]) -> Tuple[List[str], Dict[str, int]]:
    """Run schema + sanity checks on one briefing dict.

    Returns (errors, stats). stats = {'levels': N, 'london': N, 'ny': N}.
    """
    errs: List[str] = []
    stats = {"levels": 0, "london": 0, "ny": 0}

    # bias values
    for f in ("daily_bias", "session_bias"):
        v = str(b.get(f, "")).upper()
        if v not in BIAS_VALUES:
            errs.append(f"{f}={v!r} not in {sorted(BIAS_VALUES)}")

    bc = b.get("bias_confidence")
    if not isinstance(bc, (int, float)) or not (0.0 <= float(bc) <= 1.0):
        errs.append(f"bias_confidence={bc!r} not in [0.0, 1.0]")

    # ref price for level sanity check: midpoint of bb_upper/bb_lower if both present
    bb_upper = b.get("bb_upper")
    bb_lower = b.get("bb_lower")
    ref_price: Optional[float] = None
    if isinstance(bb_upper, (int, float)) and isinstance(bb_lower, (int, float)) and bb_upper > 0:
        ref_price = (float(bb_upper) + float(bb_lower)) / 2.0

    # levels
    levels = b.get("levels")
    if isinstance(levels, list):
        stats["levels"] = len(levels)
    errs.extend(_validate_levels(levels, ref_price))

    # Levels price-range bounds, used to sanity-check NY condition.level
    levels_lo: Optional[float] = None
    levels_hi: Optional[float] = None
    if isinstance(levels, list) and levels:
        prices: List[float] = []
        for lv in levels:
            if isinstance(lv, dict):
                try:
                    prices.append(float(lv["price"]))
                except (KeyError, TypeError, ValueError):
                    continue
        if prices:
            levels_lo = min(prices)
            levels_hi = max(prices)

    # plans (Phase 2: London/NY split + per-plan validation)
    plans = b.get("trading_plans")
    if not isinstance(plans, list) or not plans:
        errs.append("trading_plans is empty/missing")
    else:
        for i, p in enumerate(plans):
            if not isinstance(p, dict):
                errs.append(f"plan[{i}] is not an object")
                continue

            label = str(p.get("label") or f"#{i}")

            # session
            sess_raw = str(p.get("session") or "").strip()
            sess = sess_raw.capitalize() if sess_raw.lower() != "ny" else "NY"
            if sess not in PLAN_SESSIONS:
                errs.append(
                    f"plan[{i}] {label!r} session={sess_raw!r} not in {sorted(PLAN_SESSIONS)}"
                )
                # Skip session-conditional checks, but keep validating other fields
            else:
                if sess == "London":
                    stats["london"] += 1
                    if p.get("london_condition") is not None:
                        errs.append(
                            f"plan[{i}] {label!r} London plan must have london_condition=null, "
                            f"got {type(p.get('london_condition')).__name__}"
                        )
                else:  # NY
                    stats["ny"] += 1
                    cond = p.get("london_condition")
                    if cond is None:
                        errs.append(
                            f"NY plan {label!r} missing london_condition"
                        )
                    else:
                        errs.extend(_validate_london_condition(
                            cond, i, label, levels_lo, levels_hi,
                        ))

            # expires_at
            exp_err = _validate_plan_expires_at(p.get("expires_at"))
            if exp_err:
                errs.append(f"plan[{i}] {label!r} expires_at: {exp_err}")

            # entry_zone
            ez = p.get("entry_zone")
            if not (isinstance(ez, list) and len(ez) == 2):
                errs.append(f"plan[{i}] {label!r} entry_zone is not a 2-element list")
            else:
                try:
                    lo, hi = float(ez[0]), float(ez[1])
                    if lo >= hi:
                        errs.append(f"plan[{i}] {label!r} entry_zone {lo}..{hi}: low>=high")
                except (TypeError, ValueError):
                    errs.append(f"plan[{i}] {label!r} entry_zone has non-numeric values: {ez!r}")

            # targets
            tgts = p.get("targets")
            if not isinstance(tgts, list) or not tgts:
                errs.append(f"plan[{i}] {label!r} targets is empty/missing")

        # plan-count gates
        if not (PLANS_PER_SESSION_MIN <= stats["london"] <= PLANS_PER_SESSION_MAX):
            errs.append(
                f"London plan count is {stats['london']}; "
                f"need {PLANS_PER_SESSION_MIN}-{PLANS_PER_SESSION_MAX}"
            )
        if not (PLANS_PER_SESSION_MIN <= stats["ny"] <= PLANS_PER_SESSION_MAX):
            errs.append(
                f"NY plan count is {stats['ny']}; "
                f"need {PLANS_PER_SESSION_MIN}-{PLANS_PER_SESSION_MAX}"
            )
        total = stats["london"] + stats["ny"]
        if not (PLANS_TOTAL_MIN <= total <= PLANS_TOTAL_MAX):
            errs.append(
                f"total plan count is {total}; "
                f"need {PLANS_TOTAL_MIN}-{PLANS_TOTAL_MAX}"
            )

    # legacy fields
    kl = b.get("key_levels") or {}
    if not (kl.get("resistance") or []):
        errs.append("key_levels.resistance is empty")
    if not (kl.get("support") or []):
        errs.append("key_levels.support is empty")

    lp = b.get("liquidity_pools") or {}
    if not (lp.get("buy_side") or []):
        errs.append("liquidity_pools.buy_side is empty")
    if not (lp.get("sell_side") or []):
        errs.append("liquidity_pools.sell_side is empty")

    return errs, stats


# ─── Per-pair loader ───────────────────────────────────────────────────────

def _check_pair(pair: str, date: str, session: str) -> Tuple[str, str, Dict[str, int]]:
    """Return (status_label, detail, stats).
      status_label ∈ {'PASS', 'FAIL', 'MISSING', 'PARSE_ERROR'}
    """
    path = _briefing_path(pair, date, session)
    if not path.exists():
        return "MISSING", f"no briefing fired for {pair}", {"levels": 0, "london": 0, "ny": 0}
    try:
        b = json.loads(path.read_text())
    except Exception as exc:
        return "PARSE_ERROR", f"{pair}: {exc}", {"levels": 0, "london": 0, "ny": 0}

    errs, stats = _validate_briefing(b)
    if errs:
        first = errs[0]
        more  = f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""
        return "FAIL", f"{first}{more}", stats
    return "PASS", "", stats


# ─── Report formatting ─────────────────────────────────────────────────────

def _format_report(date: str, session: str, results: List[Tuple[str, str, str, Dict[str, int]]]) -> str:
    """results: [(pair, status, detail, stats)]"""
    try:
        when = datetime.strptime(date, "%Y-%m-%d").strftime("%a %Y-%m-%d")
    except ValueError:
        when = date

    lines = [f"Phase validation review — {when} ({session})", ""]
    for pair, status, detail, stats in results:
        if status == "PASS":
            lines.append(
                f"{pair}: PASS  ({stats.get('levels', 0)} levels, "
                f"{stats.get('london', 0)} London + {stats.get('ny', 0)} NY plans)"
            )
        elif status == "MISSING":
            lines.append(f"{pair}: MISSING — {detail}")
        elif status == "PARSE_ERROR":
            lines.append(f"{pair}: PARSE_ERROR — {detail}")
        else:
            lines.append(f"{pair}: FAIL  — {detail}")
    pass_count = sum(1 for _, s, *_ in results if s == "PASS")
    lines.append("")
    lines.append(f"Pass: {pass_count}/{len(results)}")
    return "\n".join(lines)


# ─── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="UTC date to validate (YYYY-MM-DD). Default: today UTC.",
    )
    parser.add_argument("--session", default="London", help="Session name. Default: London.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout instead of sending Telegram.")
    parser.add_argument("--no-wait", action="store_true",
                        help="Skip the wait-for-briefings poll (validate immediately).")
    args = parser.parse_args()

    # Phase validation review is briefing QA — belongs with the briefing-home
    # box (FXi 144). Default OFF on the 161 box. No consumer reads this
    # script's output (only Telegram + log fallback; EOD pipeline does not
    # ingest it). Set BRIEFING_PHASE_VALIDATION_ENABLED=1 to re-enable.
    _enabled = (os.getenv("BRIEFING_PHASE_VALIDATION_ENABLED", "0") or "0").strip() == "1"
    if not _enabled and not args.dry_run:
        print(
            "[validate_briefing] disabled on this box "
            "(BRIEFING_PHASE_VALIDATION_ENABLED!=1) — exiting 0",
            file=sys.stderr,
        )
        return 0

    if not args.no_wait:
        still_missing = _wait_for_briefings(args.date, args.session)
        if still_missing:
            print(
                f"[validate_briefing] {len(still_missing)} pair(s) still missing after "
                f"{WAIT_FOR_BRIEFINGS_MAX_SEC // 60} min wait: {', '.join(still_missing)}",
                file=sys.stderr,
            )

    results: List[Tuple[str, str, str, Dict[str, int]]] = []
    for pair in PAIRS:
        status, detail, stats = _check_pair(pair, args.date, args.session)
        results.append((pair, status, detail, stats))

    report = _format_report(args.date, args.session, results)

    if args.dry_run:
        print(report)
        return 0

    token, chat_id = _load_env_telegram()
    sent = False
    if token and chat_id:
        sent = _send_telegram(token, chat_id, report)
    if sent:
        print("[validate_briefing_phase1] report sent to Telegram", file=sys.stderr)
        return 0

    fallback = LOG_DIR / f"phase1_validation_{args.date}.txt"
    try:
        fallback.write_text(report + "\n")
        print(f"[validate_briefing_phase1] Telegram failed; wrote {fallback}",
              file=sys.stderr)
    except Exception as exc:
        print(f"[validate_briefing_phase1] Telegram failed AND fallback write failed: {exc}",
              file=sys.stderr)
        print(report)  # last resort: stdout
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
