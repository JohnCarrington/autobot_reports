"""daily_journal.py — Daily trading journal.

Reads existing logs and produces a per-day journal entry for later
pattern-spotting. Read-only; never touches the trading path.

Usage:
    python daily_journal.py                       # today, UTC
    python daily_journal.py --date 2026-07-02
    python daily_journal.py --dry-run             # print, don't write
    python daily_journal.py --date 2026-07-02 --dry-run

Kill-switch:
    DAILY_JOURNAL_ENABLED=0  → exits 0 without writing

Outputs (both appended, JSONL is idempotent per date):
    logs/daily_journal.jsonl     (one row per day, structured)
    logs/daily_journal.md        (dated section per day, human-readable)

Session windows (UTC), the bot's own signal_logger._session_from_utc_hour
splits the day 00-06 / 06-11 / 11-16 / 16-24 (Asian/London/NY/Late) which
does not cover the full trading day this journal describes. We therefore
use the fallback the task spec calls for:
    Asia    00:00 - 07:00
    London  07:00 - 13:00
    NY      13:00 - 21:00
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import re
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from datetime import date as _date_t, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("daily_journal")

ROOT = Path("/opt/tradingbot")
CANDLE_DIR = ROOT / "data" / "candles" / "GBPUSD"
LOG_DIR = ROOT / "logs"
CACHE_DIR = ROOT / "cache"

JSONL_OUT = LOG_DIR / "daily_journal.jsonl"
MD_OUT = LOG_DIR / "daily_journal.md"
# Part D (2026-07-16): compact one-line-per-day summary for downstream
# day-type analysis. Serialised from the same fields the journal already
# computes; write failure never breaks the JSONL/MD path.
DAY_SUMMARY_OUT = LOG_DIR / "day_summary.jsonl"

SESSIONS: List[Tuple[str, int, int]] = [
    ("Asia", 0, 7),
    ("London", 7, 13),
    ("NY", 13, 21),
]

MARKET_ACTION_THRESHOLDS = {
    "trending_adx_min": 25.0,
    "trending_er_min": 0.40,
    "ranging_er_max": 0.30,
    "ranging_adx_max": 20.0,
    "chop_er_max": 0.20,
    "chop_adx_max": 15.0,
    "consolidation_bbw_slope_max_pips": -1.5,  # bb width contracting
}

BLOCKED_WOULD_HAVE_RUN_PIPS = 15.0
BLOCKED_LOOKAHEAD_MIN = 60
STRATEGY_BLEED_LOOKBACK = 5
STRATEGY_BLEED_MIN_NEG = 3


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _session_for(dt: datetime) -> Optional[str]:
    h = dt.hour
    for name, start, end in SESSIONS:
        if start <= h < end:
            return name
    return None


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _pips(x: float) -> float:
    """GBPUSD candles are stored as price * 10000, so a delta of 1.0 = 1 pip."""
    return round(float(x), 2)


# ---------------------------------------------------------------------------
# Candles + indicators
# ---------------------------------------------------------------------------

def load_candles(day: _date_t) -> List[Dict[str, Any]]:
    p = CANDLE_DIR / f"{day.isoformat()}.csv"
    rows: List[Dict[str, Any]] = []
    if not p.exists():
        return rows
    with p.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            ts = _parse_ts(r.get("timestamp"))
            if ts is None:
                continue
            try:
                rows.append({
                    "ts": ts,
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                })
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: x["ts"])
    return rows


def _wilder_adx(bars: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    tr_list: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    for i in range(1, len(bars)):
        h, l, c = bars[i]["high"], bars[i]["low"], bars[i]["close"]
        ph, pl, pc = bars[i-1]["high"], bars[i-1]["low"], bars[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
        up = h - ph
        dn = pl - l
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
    if len(tr_list) < period:
        return None
    atr = sum(tr_list[:period]) / period
    pdm = sum(plus_dm[:period]) / period
    mdm = sum(minus_dm[:period]) / period
    dx_series: List[float] = []
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        pdm = (pdm * (period - 1) + plus_dm[i]) / period
        mdm = (mdm * (period - 1) + minus_dm[i]) / period
        if atr <= 0:
            continue
        pdi = 100.0 * pdm / atr
        mdi = 100.0 * mdm / atr
        denom = pdi + mdi
        if denom <= 0:
            continue
        dx = 100.0 * abs(pdi - mdi) / denom
        dx_series.append(dx)
    if len(dx_series) < period:
        return None
    adx = sum(dx_series[:period]) / period
    for j in range(period, len(dx_series)):
        adx = (adx * (period - 1) + dx_series[j]) / period
    return adx


def _efficiency_ratio(bars: List[Dict[str, Any]], n: int = 10) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    closes = [b["close"] for b in bars[-(n + 1):]]
    net = abs(closes[-1] - closes[0])
    path = sum(abs(closes[i] - closes[i-1]) for i in range(1, len(closes)))
    if path <= 0:
        return None
    return net / path


def _bb_width_pips(bars: List[Dict[str, Any]], period: int = 20, k: float = 2.0) -> Optional[float]:
    if len(bars) < period:
        return None
    closes = [b["close"] for b in bars[-period:]]
    mean = sum(closes) / period
    var = sum((c - mean) ** 2 for c in closes) / period
    std = math.sqrt(var)
    return 2.0 * k * std  # already in pip units


def _bbw_slope_pips(bars: List[Dict[str, Any]], period: int = 20, lookback: int = 6) -> Optional[float]:
    if len(bars) < period + lookback:
        return None
    now = _bb_width_pips(bars, period)
    then = _bb_width_pips(bars[:-lookback], period)
    if now is None or then is None:
        return None
    return now - then


def _classify_market_action(adx: Optional[float], er: Optional[float],
                            bbw: Optional[float], bbw_slope: Optional[float]) -> str:
    t = MARKET_ACTION_THRESHOLDS
    if adx is None or er is None:
        return "unknown"
    if adx >= t["trending_adx_min"] and er >= t["trending_er_min"]:
        return "trending"
    if bbw_slope is not None and bbw_slope <= t["consolidation_bbw_slope_max_pips"]:
        return "consolidation"
    if adx <= t["chop_adx_max"] and er <= t["chop_er_max"]:
        return "chop"
    if adx < t["ranging_adx_max"] and er < t["ranging_er_max"]:
        return "ranging"
    return "mixed"


def _shape(o: float, h: float, l: float, c: float) -> str:
    rng = h - l
    if rng <= 0:
        return "flat"
    body = abs(c - o)
    body_pct = body / rng
    if body_pct >= 0.7:
        return "directional"
    if body_pct <= 0.3:
        return "indecisive"
    return "mixed"


def session_price_action(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not bars:
        return {
            "bars": 0, "open": None, "close": None, "high": None, "low": None,
            "range_pips": 0.0, "net_pips": 0.0, "direction": "flat",
            "shape": "n/a", "adx": None, "er": None, "bb_width_pips": None,
            "bbw_slope_pips": None, "market_action": "no_data",
            "narrative": "no data",
        }
    o = bars[0]["open"]
    c = bars[-1]["close"]
    h = max(b["high"] for b in bars)
    l = min(b["low"] for b in bars)
    net = c - o
    direction = "up" if net > 1.0 else "down" if net < -1.0 else "flat"
    shape = _shape(o, h, l, c)
    adx = _wilder_adx(bars, 14)
    er = _efficiency_ratio(bars, 10)
    bbw = _bb_width_pips(bars, 20)
    bbw_slope = _bbw_slope_pips(bars, 20, 6)
    action = _classify_market_action(adx, er, bbw, bbw_slope)
    rng = h - l
    verb = {"up": "trended up", "down": "trended down", "flat": "closed flat"}[direction]
    expansion = ""
    if bbw_slope is not None:
        expansion = " on expanding range" if bbw_slope > 1.0 else " on contracting range" if bbw_slope < -1.0 else ""
    narrative = f"{verb} {net:+.1f}p (range {rng:.1f}p){expansion}, {shape}."
    return {
        "bars": len(bars),
        "open": _pips(o), "close": _pips(c),
        "high": _pips(h), "low": _pips(l),
        "range_pips": _pips(rng), "net_pips": _pips(net),
        "direction": direction, "shape": shape,
        "adx": None if adx is None else round(adx, 2),
        "er": None if er is None else round(er, 3),
        "bb_width_pips": None if bbw is None else _pips(bbw),
        "bbw_slope_pips": None if bbw_slope is None else _pips(bbw_slope),
        "market_action": action,
        "narrative": narrative,
    }


# ---------------------------------------------------------------------------
# Regime engine
# ---------------------------------------------------------------------------

def summarize_regime(day: _date_t) -> Dict[str, Dict[str, Any]]:
    """Per-session distribution of winning_regime plus declamp/downgrade counts."""
    per_session: Dict[str, Dict[str, Any]] = {
        s: {"count": 0, "labels": Counter(), "path": Counter(),
            "declamp_certified": 0, "hist_freshness_downgraded": 0,
            "adx_lt_20": 0, "strong_trend_bars": 0}
        for s, _, _ in SESSIONS
    }
    day_str = day.isoformat()
    for row in _iter_jsonl(LOG_DIR / "regime_engine.jsonl"):
        if row.get("symbol") != "GBPUSD":
            continue
        ts = _parse_ts(row.get("timestamp"))
        if ts is None or ts.date() != day:
            continue
        sess = _session_for(ts)
        if sess is None:
            continue
        b = per_session[sess]
        b["count"] += 1
        wr = row.get("winning_regime") or "UNKNOWN"
        b["labels"][wr] += 1
        b["path"][row.get("regime_label_path") or "unknown"] += 1
        if row.get("struct_declamp_certified"):
            b["declamp_certified"] += 1
        if row.get("hist_freshness_downgraded"):
            b["hist_freshness_downgraded"] += 1
        adx = row.get("ADX")
        if isinstance(adx, (int, float)) and adx < 20.0:
            b["adx_lt_20"] += 1
        if "STRONG_TREND" in wr:
            b["strong_trend_bars"] += 1
    # finalize: convert to percentages + dominant label
    out: Dict[str, Dict[str, Any]] = {}
    for sess, b in per_session.items():
        total = b["count"]
        pct: Dict[str, float] = {}
        dominant = None
        if total > 0:
            for lab, n in b["labels"].most_common():
                pct[lab] = round(100.0 * n / total, 1)
            dominant = b["labels"].most_common(1)[0][0]
        out[sess] = {
            "bars": total,
            "dominant": dominant,
            "distribution_pct": pct,
            "label_path_counts": dict(b["path"]),
            "struct_declamp_certified_bars": b["declamp_certified"],
            "hist_freshness_downgraded_bars": b["hist_freshness_downgraded"],
            "adx_lt_20_bars": b["adx_lt_20"],
            "strong_trend_bars": b["strong_trend_bars"],
        }
    return out


# ---------------------------------------------------------------------------
# Signal log (PnL)
# ---------------------------------------------------------------------------

# Part F (2026-07-16): cash-equivalent restatement. Journal pips are a
# raw sum of leg pips (size-blind) — a scaled winner banks +10p at half
# size and its runner rides at half size, while an unscaled loser dies at
# full size. To reproduce IG-realised £, sum each leg × its size.
# TRADE_SIZE is the fleet's base position size (units → £/pt on GBPUSD
# DFB). Scale-out closes 50%, so each leg trades at TRADE_SIZE/2.
_TRADE_SIZE_ENV_DEFAULT = 2.0


def _trade_size() -> float:
    try:
        v = float(os.getenv("TRADE_SIZE", str(_TRADE_SIZE_ENV_DEFAULT)))
        return v if v > 0 else _TRADE_SIZE_ENV_DEFAULT
    except (TypeError, ValueError):
        return _TRADE_SIZE_ENV_DEFAULT


def _fire_cash_gbp(r: Dict[str, Any], trade_size: float) -> Optional[float]:
    """Cash equivalent for a single fire, in GBP.

    Scaled trades (`partial_bank_pips` set):
        cash = (partial_bank + runner_pnl) × (TRADE_SIZE/2)
             = total_pnl_pips × (TRADE_SIZE/2)
    Unscaled trades:
        cash = pnl_pips × TRADE_SIZE

    Returns None only when no pnl fields are present — callers treat as 0
    for aggregation, but the null is preserved on per-fire output so the
    distinction between "no data" and "£0.00" is legible in reports.
    """
    try:
        pb = r.get("partial_bank_pips")
        if pb is not None:
            total = r.get("total_pnl_pips")
            if total is None:
                # Should not happen (log_close writes total when partial
                # exists) — belt-and-braces via bank + runner_pnl.
                pnl = r.get("pnl_pips")
                if pb is not None and pnl is not None:
                    total = float(pb) + float(pnl)
            if total is None:
                return None
            return round(float(total) * (trade_size / 2.0), 2)
        pnl = r.get("pnl_pips")
        if pnl is None:
            return None
        return round(float(pnl) * float(trade_size), 2)
    except (TypeError, ValueError):
        return None


def summarize_pnl(day: _date_t) -> Dict[str, Any]:
    fires: List[Dict[str, Any]] = []
    for row in _iter_jsonl(LOG_DIR / "signal_log.jsonl"):
        if row.get("pair") != "GBPUSD":
            continue
        ts = _parse_ts(row.get("timestamp_open"))
        if ts is None or ts.date() != day:
            continue
        fires.append(row)

    trade_size = _trade_size()

    def _pnl(r: Dict[str, Any]) -> float:
        val = r.get("total_pnl_pips")
        if val is None:
            val = r.get("pnl_pips")
        try:
            return float(val) if val is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _cash(r: Dict[str, Any]) -> float:
        c = _fire_cash_gbp(r, trade_size)
        return c if c is not None else 0.0

    total_pips = round(sum(_pnl(r) for r in fires), 2)
    total_cash = round(sum(_cash(r) for r in fires), 2)
    wins = sum(1 for r in fires if _pnl(r) > 0)
    win_rate = round(100.0 * wins / len(fires), 1) if fires else 0.0

    by_strategy: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"fires": 0, "wins": 0, "pips": 0.0, "cash": 0.0}
    )
    by_session: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"fires": 0, "wins": 0, "pips": 0.0, "cash": 0.0}
    )
    out_of_hours: List[Dict[str, Any]] = []

    for r in fires:
        pips = _pnl(r)
        cash = _cash(r)
        strat = r.get("strategy") or "UNKNOWN"
        ts = _parse_ts(r.get("timestamp_open"))
        sess = _session_for(ts) if ts else None
        by_strategy[strat]["fires"] += 1
        by_strategy[strat]["pips"] += pips
        by_strategy[strat]["cash"] += cash
        if pips > 0:
            by_strategy[strat]["wins"] += 1
        if sess:
            by_session[sess]["fires"] += 1
            by_session[sess]["pips"] += pips
            by_session[sess]["cash"] += cash
            if pips > 0:
                by_session[sess]["wins"] += 1
        if ts is not None and (ts.hour < 7 or ts.hour >= 21):
            out_of_hours.append({
                "ts": ts.isoformat(),
                "strategy": strat,
                "direction": r.get("direction"),
                "pnl_pips": pips,
                "cash_gbp": cash,
            })

    def _finalize(d: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {
            k: {
                "fires": v["fires"],
                "wins": v["wins"],
                "win_rate_pct": round(100.0 * v["wins"] / v["fires"], 1) if v["fires"] else 0.0,
                # Legacy `net_pips` kept for backwards compat; the same
                # value is exposed under `net_pips_size_blind` so any new
                # consumer picks the size-blind label explicitly. Cash
                # under `net_cash_gbp` is the true P&L in £.
                "net_pips": round(v["pips"], 2),
                "net_pips_size_blind": round(v["pips"], 2),
                "net_cash_gbp": round(v["cash"], 2),
            }
            for k, v in d.items()
        }

    return {
        "fires": len(fires),
        "wins": wins,
        "win_rate_pct": win_rate,
        # Legacy field kept for compatibility (readers may still consume
        # `net_pips`); the size-blind label is added alongside so any new
        # reader distinguishes it from cash.
        "net_pips": total_pips,
        "net_pips_size_blind": total_pips,
        "net_cash_gbp": total_cash,
        "trade_size_used": trade_size,
        "by_strategy": _finalize(by_strategy),
        "by_session": _finalize(by_session),
        "out_of_hours_fires": out_of_hours,
        "_raw_fires": fires,  # kept internal for later flag rules
    }


# ---------------------------------------------------------------------------
# News → day-type
# ---------------------------------------------------------------------------

def load_high_impact_events(day: _date_t) -> List[Dict[str, Any]]:
    p = CACHE_DIR / f"news_state_finnhub_{day.isoformat()}.json"
    if not p.exists():
        return []
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    events = blob.get("events", []) or []
    out: List[Dict[str, Any]] = []
    for e in events:
        ts = _parse_ts(e.get("ts"))
        if ts is None or ts.date() != day:
            continue
        if str(e.get("impact", "")).upper() != "HIGH":
            continue
        if str(e.get("currency", "")).upper() not in ("GBP", "USD"):
            continue
        out.append({"ts": ts.isoformat(), "currency": e.get("currency"),
                    "event": e.get("event")})
    out.sort(key=lambda x: x["ts"])
    return out


def classify_day_type(events: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Return (day_type, rule_explanation)."""
    if not events:
        return "normal", "no high-impact GBP/USD release today"
    # Timing: back-half of trading day = >= 16:00 UTC
    times = [datetime.fromisoformat(e["ts"]).hour for e in events]
    early = [t for t in times if t < 12]
    mid = [t for t in times if 12 <= t < 16]
    late = [t for t in times if t >= 16]
    if mid and not early and not late:
        return "big-news", "single mid-day high-impact release"
    if mid or early:
        return "big-news", f"{len(events)} high-impact release(s) at or before 16:00 UTC"
    if late and not (early or mid):
        return "pre-news", "high-impact release only in back-half (>=16:00 UTC)"
    return "big-news", "multiple high-impact releases spanning the day"


# ---------------------------------------------------------------------------
# News-tier classifier telemetry (Step-1, telemetry-only surface)
# ---------------------------------------------------------------------------

NEWS_TIER_LOG = LOG_DIR / "news_tier_classification.jsonl"

_TIER_NEW_RULES_TEXT = {
    "BIG": "trade+blackout+extended-eligible",
    "MIDDLE": "trade+blackout",
    "SMALL": "no-trade, no-blackout",
}

_CURRENT_BEHAVIOUR_TEXT = {
    "arm_evaluated": "armed",
    "armed": "armed",
    "pair_not_affected": "pair-not-affected",
    "outside_window": "outside-window",
    "outside-window": "outside-window",
}


def _fmt_deviation(dev: Any) -> str:
    if dev is None:
        return "n/a"
    try:
        d = float(dev)
    except (TypeError, ValueError):
        return "n/a"
    return f"{d:+.1f}%"


def summarize_news_tiers(day: _date_t) -> Dict[str, Any]:
    """Read logs/news_tier_classification.jsonl and surface the day's tier evidence.

    Read-only against telemetry. Never affects trading. Returns a dict with:
      status: "ok" | "no_file" | "no_data"
      events: [ {time, currency, event_name, tier, matched_rule, deviation,
                 under_new_rules, current_behaviour, movement}, ... ]
      note:   human-readable note when no events / file missing / empty
    """
    if not NEWS_TIER_LOG.exists():
        return {"status": "no_file", "events": [],
                "note": "Classification telemetry unavailable (no log file)."}

    dedup: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    parsed_any = False
    try:
        with NEWS_TIER_LOG.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                s = raw.strip()
                if not s:
                    continue
                try:
                    row = json.loads(s)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                parsed_any = True
                # Filter to this day — event_date_utc preferred, ts_utc fallback.
                row_day: Optional[_date_t] = None
                ed = row.get("event_date_utc")
                if ed:
                    try:
                        row_day = _date_t.fromisoformat(str(ed))
                    except ValueError:
                        row_day = None
                if row_day is None:
                    ts = _parse_ts(row.get("ts_utc"))
                    if ts is not None:
                        row_day = ts.date()
                if row_day != day:
                    continue
                key = (
                    str(row.get("event_name") or ""),
                    str(row.get("currency") or ""),
                    str(row.get("event_time") or ""),
                )
                # Keep the latest ts_utc per (event_name, currency, event_time).
                prev = dedup.get(key)
                if prev is not None:
                    prev_ts = _parse_ts(prev.get("ts_utc"))
                    cur_ts = _parse_ts(row.get("ts_utc"))
                    if prev_ts is not None and cur_ts is not None and cur_ts < prev_ts:
                        continue
                dedup[key] = row
    except OSError:
        return {"status": "no_file", "events": [],
                "note": "Classification telemetry unavailable (no log file)."}
    except Exception:  # noqa: BLE001 — fail soft, never break journal
        return {"status": "no_data", "events": [],
                "note": "Classification telemetry unavailable."}

    if not parsed_any:
        return {"status": "no_data", "events": [],
                "note": "Classification telemetry unavailable."}

    if not dedup:
        return {"status": "no_data", "events": [],
                "note": "No HIGH-impact events classified today."}

    events_out: List[Dict[str, Any]] = []
    for row in dedup.values():
        tier = str(row.get("mapped_tier") or "").upper() or "UNKNOWN"
        new_rules_text = _TIER_NEW_RULES_TEXT.get(tier, "n/a")
        cb_raw = str(row.get("current_behaviour") or "").strip()
        current_text = _CURRENT_BEHAVIOUR_TEXT.get(cb_raw, cb_raw or "n/a")
        movement: Optional[Dict[str, Any]] = None
        # Surface any pre-computed movement fields if the row carries them.
        for mk in ("post_release_movement", "movement", "post_release_m5_m60"):
            mv = row.get(mk)
            if isinstance(mv, dict) and mv:
                movement = mv
                break
        events_out.append({
            "time": str(row.get("event_time") or ""),
            "currency": str(row.get("currency") or ""),
            "event_name": str(row.get("event_name") or ""),
            "tier": tier,
            "matched_rule": str(row.get("matched_rule") or ""),
            "deviation": _fmt_deviation(row.get("deviation")),
            "under_new_rules": new_rules_text,
            "current_behaviour": current_text,
            "movement": movement,
        })

    events_out.sort(key=lambda x: (x["time"], x["currency"], x["event_name"]))
    return {"status": "ok", "events": events_out, "note": ""}


# ---------------------------------------------------------------------------
# Blocked-setups + health
# ---------------------------------------------------------------------------

GATE_SOURCES = [
    ("bb_bounce_standdown.jsonl", "bb_bounce_standdown",
     ("BLOCKED", "SUPPRESS", "BLOCK")),
    ("sb_daily_filter.jsonl", "sb_daily_filter",
     ("BLOCK", "BLOCKED", "SUPPRESS")),
    ("range_gate.jsonl", "range_gate",
     ("SUPPRESS", "BLOCK", "BLOCKED")),
    ("trend_entry_gate.jsonl", "trend_entry_gate",
     ("BLOCK", "SUPPRESS")),
    ("htf_authority.jsonl", "htf_authority",
     ("BLOCK",)),
    ("trend_stretch_brake.jsonl", "trend_stretch_brake",
     ("BLOCK", "SUPPRESS")),
]


def _gate_ts(row: Dict[str, Any]) -> Optional[datetime]:
    for k in ("ts_utc", "timestamp", "ts"):
        v = row.get(k)
        if v:
            return _parse_ts(v)
    return None


def _gate_verdict(row: Dict[str, Any]) -> Optional[str]:
    v = row.get("verdict") or row.get("decision")
    return str(v).upper() if v else None


def _gate_direction(row: Dict[str, Any]) -> Optional[str]:
    for k in ("direction", "intended_direction", "sb_direction"):
        v = row.get(k)
        if v:
            s = str(v).upper()
            if s in ("BUY", "LONG"):
                return "LONG"
            if s in ("SELL", "SHORT"):
                return "SHORT"
    return None


def summarize_blocks(day: _date_t, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_session: Dict[str, Dict[str, Any]] = {
        s: {"total": 0, "by_gate": Counter(), "by_reason": Counter()}
        for s, _, _ in SESSIONS
    }
    would_have_run: List[Dict[str, Any]] = []

    for fname, gate_name, block_verdicts in GATE_SOURCES:
        p = LOG_DIR / fname
        for row in _iter_jsonl(p):
            ts = _gate_ts(row)
            if ts is None or ts.date() != day:
                continue
            sym = str(row.get("symbol") or row.get("pair") or "GBPUSD")
            if sym and sym != "GBPUSD":
                continue
            verdict = _gate_verdict(row)
            if verdict not in block_verdicts:
                continue
            sess = _session_for(ts)
            if sess is None:
                continue
            per_session[sess]["total"] += 1
            per_session[sess]["by_gate"][gate_name] += 1
            reason = row.get("reason") or row.get("why") or "n/a"
            per_session[sess]["by_reason"][str(reason)[:80]] += 1

            # would-have-run lookahead: does price move >= threshold
            # in blocked direction within window?
            direction = _gate_direction(row)
            if direction and candles:
                px = row.get("setup_price") or row.get("price") or row.get("entry_px")
                try:
                    px = float(px) if px is not None else None
                except (TypeError, ValueError):
                    px = None
                if px is None:
                    # fall back to close of most recent candle at/before ts
                    prior = [c for c in candles if c["ts"] <= ts]
                    px = prior[-1]["close"] if prior else None
                if px is not None:
                    end_ts = ts + timedelta(minutes=BLOCKED_LOOKAHEAD_MIN)
                    window = [c for c in candles if ts <= c["ts"] <= end_ts]
                    if window:
                        if direction == "LONG":
                            best = max(c["high"] for c in window)
                            move = best - px
                        else:
                            best = min(c["low"] for c in window)
                            move = px - best
                        if move >= BLOCKED_WOULD_HAVE_RUN_PIPS:
                            would_have_run.append({
                                "gate": gate_name,
                                "ts": ts.isoformat(),
                                "session": sess,
                                "direction": direction,
                                "would_have_run_pips": round(move, 1),
                                "reason": str(row.get("reason") or row.get("why") or "")[:120],
                            })

    out = {}
    for sess, b in per_session.items():
        out[sess] = {
            "total": b["total"],
            "by_gate": dict(b["by_gate"]),
            "top_reasons": [{"reason": r, "count": n}
                            for r, n in b["by_reason"].most_common(5)],
        }
    return {"per_session": out, "would_have_run": would_have_run}


def summarize_health(day: _date_t) -> Dict[str, Any]:
    red = 0
    amber = 0
    flags: List[Dict[str, Any]] = []
    for row in _iter_jsonl(LOG_DIR / "health_cycles.jsonl"):
        ts = _parse_ts(row.get("ts"))
        if ts is None or ts.date() != day:
            continue
        overall = str(row.get("overall") or "").upper()
        if overall == "RED":
            red += 1
        elif overall == "AMBER":
            amber += 1
        if overall in ("RED", "AMBER") and len(flags) < 8:
            f = {"ts": ts.isoformat(), "overall": overall}
            for k, v in (row.get("signals") or {}).items():
                if isinstance(v, dict) and v.get("state") in ("RED", "AMBER"):
                    f[k] = v.get("state")
            flags.append(f)
    return {"red_cycles": red, "amber_cycles": amber, "sample_flags": flags}


# ---------------------------------------------------------------------------
# Journal error/warning families (added 2026-07-17)
#
# health_cycles.jsonl only covers infra plumbing (buffer_depth, tick_age,
# close_cadence, indicator_sanity, rest_allowance, crash_loop). Strategy
# exceptions (BB_BOUNCE register_bb_range_scalp missing, briefing API
# failures, bb_pierce_recorder DataFrame bugs, ...) fire ERROR/WARNING
# into journald and are invisible to summarize_health. This function
# reads the systemd journal for autobot.service, buckets by message
# shape, and separates NEW-today families from RECURRING (baseline) so
# the reader sees the signal, not the noise.
#
# NOTE (do not "improve" back to -p err): the app writes level tags as
# TEXT ([ERROR], [WARNING]) via logging on stdout. journald tags stdout
# with priority=6/info regardless of Python's level, so -p err returns
# zero even when [ERROR] lines exist. --grep on the message text is the
# only correct filter — verified 2026-07-17: `-p err → 0 hits`,
# `--grep '\[ERROR\]' → 59 hits` for the same 24 h window.
#
# CAPS (_JE_NEW_MAX=15, _JE_REC_MAX=10) were validated against
# 2026-07-17 which had two live regressions and produced NEW=10 /
# RECURRING=14 — both fit within the caps. A normal day should be well
# under. If a normal day shows double-digit NEW consistently, the
# normalizer is under-stripping something and the caps should be
# revisited BEFORE they are raised.
#
# Read-only. Fail-soft: journalctl unavailable → {"status": "unavailable"}
# and the render sites treat that as a graceful no-op.
# ---------------------------------------------------------------------------

# Normalizer strippers, applied in order (most-specific first).
_JE_REQID_RX   = re.compile(r"req_[A-Za-z0-9]{15,}")
_JE_UUID_RX    = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_JE_HXLOCAL_RX = re.compile(r"_hx_local_\d+")
_JE_THREAD_RX  = re.compile(r"Thread-\d+")
_JE_POSKEY_RX  = re.compile(r"CS\.D\.[A-Z]+\.[A-Z0-9]+\.IP\|[A-Z_0-9]+")
_JE_EPIC_RX    = re.compile(r"CS\.D\.[A-Z]+\.[A-Z0-9]+\.IP")
_JE_DEALID_RX  = re.compile(r"\bDI[A-Z0-9]{10,20}\b")
_JE_IP_RX      = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_JE_TS_RX      = re.compile(r"\d{4}-\d{2}-\d{2}[T ][\d:,.+\-Zz]+")
_JE_HTTPVER_RX = re.compile(r"HTTP/\d\.\d")
_JE_FLOAT_RX   = re.compile(r"-?\d+\.\d+")
_JE_PAIR_RX    = re.compile(r"\b(?:GBPUSD|EURUSD|USDJPY|USDCAD|XAUUSD|GBPJPY)\b")
_JE_INT_RX     = re.compile(r"\b-?\d+\b")
_JE_TOK_RX     = re.compile(r"'[A-Z_]{4,}'")

_JE_LINE_RX    = re.compile(r"\[(ERROR|WARNING)\]\s+(.*)$")

_JE_NEW_MAX = 15
_JE_REC_MAX = 10


def _je_normalize(msg: str) -> str:
    """Collapse a log message to its shape (family key)."""
    for rx, repl in (
        (_JE_REQID_RX,   "<REQID>"),
        (_JE_UUID_RX,    "<UUID>"),
        (_JE_HXLOCAL_RX, "<HXLOCAL>"),
        (_JE_THREAD_RX,  "Thread-<N>"),
        (_JE_POSKEY_RX,  "<POSKEY>"),
        (_JE_EPIC_RX,    "<EPIC>"),
        (_JE_DEALID_RX,  "<DEALID>"),
        (_JE_IP_RX,      "<IP>"),
        (_JE_TS_RX,      "<TS>"),
        (_JE_HTTPVER_RX, "HTTP/<V>"),
        (_JE_FLOAT_RX,   "<F>"),
        (_JE_PAIR_RX,    "<PAIR>"),
        (_JE_INT_RX,     "<N>"),
        (_JE_TOK_RX,     "'<TOK>'"),
    ):
        msg = rx.sub(repl, msg)
    return msg.strip()


def _je_earliest_retained_ts() -> Optional[str]:
    """First retained ISO timestamp for autobot.service, or None."""
    try:
        r = subprocess.run(
            ["journalctl", "-q", "-u", "autobot.service",
             "--utc", "--output=short-iso"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return None
        first = r.stdout.splitlines()
        return first[0].split(" ", 1)[0] if first else None
    except Exception:
        return None


def _je_read(since: str, until: str) -> List[Tuple[str, str, str]]:
    """Return [(iso_ts, level, family_shape), ...] for the window.
    Filter pushed into journalctl via --grep (PCRE2, systemd 249) so
    non-matching lines never cross into Python. Empty list on failure."""
    try:
        r = subprocess.run(
            ["journalctl", "-q", "-u", "autobot.service",
             "--since", since, "--until", until,
             "--utc",
             "--grep=\\[(ERROR|WARNING)\\]",
             "--output=short-iso"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return []
        rows: List[Tuple[str, str, str]] = []
        for line in r.stdout.splitlines():
            m = _JE_LINE_RX.search(line)
            if not m:
                continue
            rows.append((line.split(" ", 1)[0], m.group(1),
                         _je_normalize(m.group(2))))
        return rows
    except Exception:
        return []


def summarize_journal_errors(day: _date_t) -> Dict[str, Any]:
    day_start = f"{day.isoformat()} 00:00:00"
    day_end   = f"{(day + timedelta(days=1)).isoformat()} 00:00:00"

    # Dynamic baseline. Compare against min(30d, actual retention). The
    # heading MUST always disclose the window actually used — the number
    # in `baseline_days` describes the window compared against, not the
    # journal's total age. When the earliest retained line cannot be
    # parsed at all, baseline_days is None and the render treats that as
    # "baseline window unknown" rather than omitting the disclaimer.
    thirty_ago_str = (day - timedelta(days=30)).isoformat() + " 00:00:00"
    thirty_ago_dt  = datetime.combine(
        day - timedelta(days=30), time.min, tzinfo=timezone.utc,
    )
    day_start_dt = datetime.combine(day, time.min, tzinfo=timezone.utc)

    base_start = thirty_ago_str
    retention_days: Optional[int] = None
    earliest_iso = _je_earliest_retained_ts()
    if earliest_iso:
        try:
            # journalctl --output=short-iso emits "+0000" (no colon in
            # the tz offset); datetime.fromisoformat before Python 3.11
            # rejects that. Normalise to +HH:MM. Also handle a bare "Z".
            iso = earliest_iso.replace("Z", "+00:00")
            iso = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso)
            e_dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
            if e_dt > thirty_ago_dt:
                base_start = e_dt.strftime("%Y-%m-%d %H:%M:%S")
                retention_days = max(0, (day_start_dt - e_dt).days)
            else:
                # Journal is older than the 30d cap; the cap is the
                # window actually used, not the journal's full age.
                retention_days = 30
        except Exception:
            retention_days = None  # rendered as "unknown"

    today_rows    = _je_read(day_start, day_end)
    baseline_rows = _je_read(base_start, day_start)
    if not today_rows and not baseline_rows:
        return {"status": "unavailable"}

    baseline_shapes = {shape for _, _, shape in baseline_rows}
    fam: Dict[str, Dict[str, Any]] = {}
    for ts, lvl, shape in today_rows:
        f = fam.setdefault(shape, {"level": lvl, "count": 0,
                                   "first": ts, "last": ts})
        f["count"] += 1
        f["last"]  = ts
        if lvl == "ERROR":
            f["level"] = "ERROR"  # ERROR wins if a shape sees both

    new_fam: List[Dict[str, Any]] = []
    rec_fam: List[Dict[str, Any]] = []
    for shape, meta in fam.items():
        row = {"shape": shape, **meta}
        (new_fam if shape not in baseline_shapes else rec_fam).append(row)
    new_fam.sort(key=lambda r: (-r["count"], r["first"]))
    rec_fam.sort(key=lambda r: -r["count"])
    return {
        "status":           "ok",
        "baseline_days":    retention_days,
        "new":              new_fam[:_JE_NEW_MAX],
        "new_total":        len(new_fam),
        "recurring":        rec_fam[:_JE_REC_MAX],
        "recurring_total":  len(rec_fam),
    }


# ---------------------------------------------------------------------------
# Regime-vs-reality scorecard
# ---------------------------------------------------------------------------

def _regime_family(label: Optional[str]) -> str:
    if not label:
        return "unknown"
    L = label.upper()
    if "STRONG_TREND" in L or "TREND_FORMING" in L or "TREND" in L:
        return "trend"
    if "CHOP" in L:
        return "chop"
    if "RANGE" in L:
        return "range"
    if "COMPRESS" in L:
        return "compression"
    if "BREAKOUT" in L:
        return "breakout"
    return "other"


def score_regime_vs_reality(
    per_session_price: Dict[str, Dict[str, Any]],
    per_session_regime: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for sess, _, _ in SESSIONS:
        action = per_session_price.get(sess, {}).get("market_action", "unknown")
        dominant = per_session_regime.get(sess, {}).get("dominant")
        fam = _regime_family(dominant)
        if action == "unknown" or dominant is None:
            verdict = "no_data"
        elif action == "trending" and fam == "trend":
            verdict = "agree"
        elif action == "ranging" and fam in ("range", "chop"):
            verdict = "agree"
        elif action == "chop" and fam == "chop":
            verdict = "agree"
        elif action == "consolidation" and fam in ("compression", "range"):
            verdict = "agree"
        elif action == "mixed":
            verdict = "partial"
        else:
            verdict = "disagree"
        result[sess] = {
            "market_action": action,
            "dominant_regime": dominant,
            "regime_family": fam,
            "verdict": verdict,
        }
    return result


# ---------------------------------------------------------------------------
# Suggestions (mechanical flags)
# ---------------------------------------------------------------------------

def _load_prior_journal_rows(days: int, upto: _date_t) -> List[Dict[str, Any]]:
    if not JSONL_OUT.exists():
        return []
    out: List[Dict[str, Any]] = []
    for row in _iter_jsonl(JSONL_OUT):
        try:
            d = _date_t.fromisoformat(row.get("date"))
        except (TypeError, ValueError):
            continue
        if d < upto and (upto - d).days <= days:
            out.append(row)
    return out


def build_flags(
    day: _date_t,
    price: Dict[str, Dict[str, Any]],
    regime: Dict[str, Dict[str, Any]],
    scorecard: Dict[str, Any],
    pnl: Dict[str, Any],
    blocks: Dict[str, Any],
    health: Dict[str, Any],
) -> List[Dict[str, str]]:
    flags: List[Dict[str, str]] = []

    for sess in [s for s, _, _ in SESSIONS]:
        p = price.get(sess, {})
        r = regime.get(sess, {})
        action = p.get("market_action")
        dist = r.get("distribution_pct") or {}
        bars = r.get("bars", 0)
        chop_pct = sum(v for k, v in dist.items() if "CHOP" in k)
        if action == "trending" and chop_pct > 50.0:
            flags.append({
                "code": "regime_under_called_trend",
                "session": sess,
                "evidence": (f"price {p.get('narrative')} but regime CHOP="
                             f"{chop_pct:.1f}% of {bars} bars"),
            })
        strong_trend = r.get("strong_trend_bars", 0)
        adx_lt_20 = r.get("adx_lt_20_bars", 0)
        if strong_trend >= 6 and adx_lt_20 >= 6 and strong_trend > 0.5 * bars:
            flags.append({
                "code": "possible_stuck_strong_trend_label",
                "session": sess,
                "evidence": (f"STRONG_TREND on {strong_trend}/{bars} bars but ADX<20 on "
                             f"{adx_lt_20} bars"),
            })

    # Blocked-winner
    for w in blocks.get("would_have_run", []):
        flags.append({
            "code": "blocked_winner",
            "session": w["session"],
            "evidence": (f"{w['gate']} blocked {w['direction']} at {w['ts']} → price ran "
                         f"{w['would_have_run_pips']}p within {BLOCKED_LOOKAHEAD_MIN}m"),
        })

    # Strategy bleed
    priors = _load_prior_journal_rows(STRATEGY_BLEED_LOOKBACK, day)
    today_neg = {
        s for s, v in pnl.get("by_strategy", {}).items() if v["net_pips"] < 0
    }
    for strat in today_neg:
        neg_days = 1
        for row in priors:
            per = (row.get("pnl") or {}).get("by_strategy") or {}
            if strat in per and per[strat].get("net_pips", 0) < 0:
                neg_days += 1
        if neg_days >= STRATEGY_BLEED_MIN_NEG:
            flags.append({
                "code": "strategy_bleed",
                "session": "day",
                "evidence": f"{strat} net-negative {neg_days} of last {STRATEGY_BLEED_LOOKBACK + 1} entries (incl. today)",
            })

    # Out-of-hours fires
    for f in pnl.get("out_of_hours_fires", []):
        flags.append({
            "code": "out_of_hours_fire",
            "session": "day",
            "evidence": f"{f['strategy']} {f['direction']} at {f['ts']} ({f['pnl_pips']}p)",
        })

    # Infra
    if health.get("red_cycles", 0) > 0:
        flags.append({
            "code": "infra_red_health",
            "session": "day",
            "evidence": f"{health['red_cycles']} RED health cycles today",
        })
    if health.get("amber_cycles", 0) >= 3:
        flags.append({
            "code": "infra_amber_health",
            "session": "day",
            "evidence": f"{health['amber_cycles']} AMBER health cycles today",
        })

    # Scorecard disagreements (aggregate)
    for sess, s in scorecard.items():
        if s["verdict"] == "disagree":
            flags.append({
                "code": "scorecard_disagree",
                "session": sess,
                "evidence": (f"market_action={s['market_action']} but "
                             f"dominant regime={s['dominant_regime']}"),
            })
    return flags


# ---------------------------------------------------------------------------
# Assemble + write
# ---------------------------------------------------------------------------

def build_suggestions(entry: Dict[str, Any]) -> List[Dict[str, str]]:
    """Turn the day's flags + stats into concrete, mechanical suggestions.

    Each suggestion: {code, message} where message ends in a "→ consider/
    review/watch" phrasing. Deterministic — no LLM. Returns [] when no
    rules fire; caller renders 'No suggestions flagged today — clean day.'
    """
    out: List[Dict[str, str]] = []
    flags: List[Dict[str, str]] = entry.get("flags", []) or []
    pnl = entry.get("pnl", {}) or {}
    regime = entry.get("per_session_regime", {}) or {}
    scorecard = entry.get("scorecard", {}) or {}

    # Rule 1: blocked-winner aggregation, per gate. Sum "would-have-run" pips
    # per gate; a gate that blocked ≥1 setup that ran ≥15p becomes a review
    # suggestion. Detail includes count and total pips.
    blocked_winner = [f for f in flags if f["code"] == "blocked_winner"]
    if blocked_winner:
        per_gate: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "pips": 0.0, "sessions": Counter()}
        )
        for w in entry.get("blocks", {}).get("would_have_run", []) or []:
            g = w["gate"]
            per_gate[g]["count"] += 1
            per_gate[g]["pips"] += float(w["would_have_run_pips"])
            per_gate[g]["sessions"][w["session"]] += 1
        for gate, agg in sorted(per_gate.items(), key=lambda kv: -kv[1]["pips"]):
            sess = ", ".join(f"{s}×{n}" for s, n in agg["sessions"].most_common())
            out.append({
                "code": "gate_blocked_winners",
                "message": (
                    f"{gate} blocked {agg['count']} setup(s) today that ran a "
                    f"total of {agg['pips']:.1f}p in the blocked direction "
                    f"({sess}) → review whether this gate is too strict."
                ),
            })

    # Rule 2: possible stuck STRONG_TREND label. Aggregate the sessions and
    # cite the new declamp/freshness telemetry, so the reader can see whether
    # the fixes are firing.
    stuck = [f for f in flags if f["code"] == "possible_stuck_strong_trend_label"]
    if stuck:
        sess_list = ", ".join(f["session"] for f in stuck)
        declamp = sum((regime.get(f["session"], {}) or {}).get("struct_declamp_certified_bars", 0)
                      for f in stuck)
        downgrade = sum((regime.get(f["session"], {}) or {}).get("hist_freshness_downgraded_bars", 0)
                        for f in stuck)
        out.append({
            "code": "stuck_regime_label_watch",
            "message": (
                f"Regime held STRONG_TREND in {sess_list} while ADX<20 for a chunk "
                f"of bars — declamp/freshness fixes today: declamp_certified="
                f"{declamp}, hist_freshness_downgraded={downgrade} → watch whether "
                f"the stuck-label count drops as the fixes bed in."
            ),
        })

    # Rule 3: out-of-hours fires, aggregated per strategy.
    ooh = [f for f in flags if f["code"] == "out_of_hours_fire"]
    if ooh:
        per_strat: Dict[str, List[str]] = defaultdict(list)
        for f in ooh:
            # evidence: "<strategy> <dir> at <ts> (<pips>p)"
            ev = f["evidence"]
            strat = ev.split(" ", 1)[0]
            per_strat[strat].append(ev)
        for strat, evs in per_strat.items():
            times = ", ".join(e.split(" at ")[1].split("+")[0]
                              for e in evs if " at " in e)
            out.append({
                "code": "out_of_hours_strategy",
                "message": (
                    f"{len(evs)} out-of-hours fire(s) from {strat} today (times: "
                    f"{times}) — outside 07:00–21:00 UTC → review session gating "
                    f"for {strat}."
                ),
            })

    # Rule 4: strategy bleed (multi-day negative streaks).
    bleed = [f for f in flags if f["code"] == "strategy_bleed"]
    for f in bleed:
        out.append({
            "code": "strategy_bleed_review",
            "message": (
                f"{f['evidence']} → consider standing the strategy down or "
                f"reviewing its recent gate/regime interaction."
            ),
        })

    # Rule 5: scorecard disagreements/partials in trending sessions.
    for sess, s in scorecard.items():
        if s.get("verdict") not in ("disagree", "partial"):
            continue
        action = s.get("market_action")
        dr = s.get("dominant_regime")
        # only flag partials when there's a real mismatch worth reviewing
        if s["verdict"] == "partial" and action == "mixed":
            # mixed price is expected to be partial — skip unless dominant is CHOP
            fam = s.get("regime_family", "")
            if fam == "trend":
                continue
        out.append({
            "code": "regime_reality_mismatch",
            "message": (
                f"Regime {s['verdict']} in {sess} (market={action}, "
                f"regime={dr}) → possible classifier gap for that session's "
                f"pattern."
            ),
        })

    # Rule 6: strong PnL concentrated in a single strategy.
    net = pnl.get("net_pips", 0.0)
    by_strat = pnl.get("by_strategy", {}) or {}
    if net > 40.0 and by_strat:
        top_strat, top_val = max(by_strat.items(), key=lambda kv: kv[1]["net_pips"])
        top_pips = top_val["net_pips"]
        if top_pips > 0 and net > 0:
            share = top_pips / net
            if share >= 0.60 and len(by_strat) >= 2:
                out.append({
                    "code": "single_strategy_dependence",
                    "message": (
                        f"Net {net:+.1f}p but {top_pips:+.1f}p ({share*100:.0f}%) "
                        f"from {top_strat} — single-strategy dependence today, "
                        f"watch diversification tomorrow."
                    ),
                })

    # Rule 7: infra flags on a day that also traded (health context that matters).
    health = entry.get("health", {}) or {}
    if health.get("red_cycles", 0) > 0 or health.get("amber_cycles", 0) >= 3:
        out.append({
            "code": "infra_review",
            "message": (
                f"Infra health flagged today (RED={health.get('red_cycles', 0)}, "
                f"AMBER={health.get('amber_cycles', 0)}) → review "
                f"logs/health_cycles.jsonl for the flagged signals."
            ),
        })

    return out


def build_entry(day: _date_t) -> Dict[str, Any]:
    candles = load_candles(day)
    per_session_bars: Dict[str, List[Dict[str, Any]]] = {
        s: [c for c in candles if s == _session_for(c["ts"])]
        for s, _, _ in SESSIONS
    }
    per_session_price = {s: session_price_action(per_session_bars[s]) for s, _, _ in SESSIONS}
    day_stats = session_price_action(candles) if candles else session_price_action([])

    day_open = day_stats["open"]
    day_close = day_stats["close"]
    day_high = day_stats["high"]
    day_low = day_stats["low"]
    close_pos = None
    if day_close is not None and day_high is not None and day_low is not None and day_high > day_low:
        # position of close in the day range, 0.0 = at low, 1.0 = at high
        close_pos = round((day_close - day_low) / (day_high - day_low), 2)

    events = load_high_impact_events(day)
    day_type, day_type_rule = classify_day_type(events)

    regime = summarize_regime(day)
    pnl = summarize_pnl(day)
    blocks = summarize_blocks(day, candles)
    health = summarize_health(day)
    try:
        journal_errors = summarize_journal_errors(day)
    except Exception:
        journal_errors = {"status": "unavailable"}
    scorecard = score_regime_vs_reality(per_session_price, regime)
    flags = build_flags(day, per_session_price, regime, scorecard, pnl, blocks, health)

    # Step-1 news-tier telemetry — surface-only, must never break the journal.
    try:
        news_tiers = summarize_news_tiers(day)
    except Exception:  # noqa: BLE001
        news_tiers = {"status": "no_data", "events": [],
                      "note": "Classification telemetry unavailable."}

    pnl_out = {k: v for k, v in pnl.items() if not k.startswith("_")}

    entry = {
        "date": day.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_windows_utc": {s: [start, end] for s, start, end in SESSIONS},
        "day_type": day_type,
        "day_type_rule": day_type_rule,
        "high_impact_events": events,
        "day_stats": {
            "open": day_open, "close": day_close,
            "high": day_high, "low": day_low,
            "range_pips": day_stats["range_pips"],
            "net_pips": day_stats["net_pips"],
            "close_position_in_range": close_pos,
            "market_action": day_stats["market_action"],
            "adx": day_stats["adx"], "er": day_stats["er"],
            "bb_width_pips": day_stats["bb_width_pips"],
        },
        "per_session_price": per_session_price,
        "per_session_regime": regime,
        "scorecard": scorecard,
        "pnl": pnl_out,
        "blocks": blocks,
        "health": health,
        "journal_errors": journal_errors,
        "news_tiers": news_tiers,
        "flags": flags,
        "suggestions": [],  # filled just below now that entry dict exists
        "thresholds": {
            "market_action": MARKET_ACTION_THRESHOLDS,
            "blocked_would_have_run_pips": BLOCKED_WOULD_HAVE_RUN_PIPS,
            "blocked_lookahead_min": BLOCKED_LOOKAHEAD_MIN,
            "strategy_bleed_lookback_days": STRATEGY_BLEED_LOOKBACK,
            "strategy_bleed_min_negative_days": STRATEGY_BLEED_MIN_NEG,
        },
    }
    entry["suggestions"] = build_suggestions(entry)
    return entry


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def render_markdown(e: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"## {e['date']}  ({e['day_type']})")
    lines.append(f"_generated {e['generated_at']}_")
    lines.append("")
    lines.append(f"**Day-type rule:** {e['day_type_rule']}")
    if e["high_impact_events"]:
        ev = ", ".join(f"{x['ts'][11:16]} {x['currency']} {x['event']}"
                       for x in e["high_impact_events"])
        lines.append(f"**High-impact releases:** {ev}")
    lines.append("")
    ds = e["day_stats"]
    lines.append(
        f"**Day:** open {ds['open']} / high {ds['high']} / low {ds['low']} / close {ds['close']} "
        f"→ net {ds['net_pips']:+}p, range {ds['range_pips']}p, "
        f"close_pos {ds['close_position_in_range']} (0=low,1=high). "
        f"Market action: {ds['market_action']}."
    )
    lines.append("")

    lines.append("### Price action per session")
    lines.append("| Session | O | H | L | C | Net | Range | Action | ADX | ER | BBw |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for sess, _, _ in SESSIONS:
        p = e["per_session_price"][sess]
        lines.append(
            f"| {sess} | {p['open']} | {p['high']} | {p['low']} | {p['close']} | "
            f"{p['net_pips']:+} | {p['range_pips']} | {p['market_action']} | "
            f"{p['adx']} | {p['er']} | {p['bb_width_pips']} |"
        )
    lines.append("")
    for sess, _, _ in SESSIONS:
        p = e["per_session_price"][sess]
        lines.append(f"- **{sess}:** {p['narrative']}")
    lines.append("")

    lines.append("### Regime calls per session")
    for sess, _, _ in SESSIONS:
        r = e["per_session_regime"][sess]
        if r["bars"] == 0:
            lines.append(f"- **{sess}:** no regime bars")
            continue
        dist = ", ".join(f"{k} {v}%" for k, v in
                         sorted(r["distribution_pct"].items(), key=lambda kv: -kv[1]))
        lines.append(
            f"- **{sess}:** {dist} (bars={r['bars']}; "
            f"declamp_certified={r['struct_declamp_certified_bars']}, "
            f"hist_freshness_downgraded={r['hist_freshness_downgraded_bars']})"
        )
    lines.append("")

    lines.append("### Regime-vs-reality scorecard")
    for sess, s in e["scorecard"].items():
        lines.append(
            f"- **{sess}:** market={s['market_action']}, regime={s['dominant_regime']} "
            f"({s['regime_family']}) → **{s['verdict']}**"
        )
    lines.append("")

    p = e["pnl"]
    _cash_day = p.get("net_cash_gbp")
    _cash_day_str = f" / cash **£{_cash_day:+.2f}**" if _cash_day is not None else ""
    lines.append("### PnL")
    lines.append(
        f"- **Day:** {p['fires']} fires, {p['wins']} wins ({p['win_rate_pct']}%), "
        f"net **{p['net_pips']:+}p** (size-blind){_cash_day_str}"
    )
    if p["by_strategy"]:
        lines.append("- **Per strategy:**")
        for k, v in sorted(p["by_strategy"].items()):
            _c = v.get("net_cash_gbp")
            _cs = f", £{_c:+.2f}" if _c is not None else ""
            lines.append(
                f"  - {k}: {v['fires']} fires, {v['win_rate_pct']}% win, "
                f"{v['net_pips']:+}p (size-blind){_cs}"
            )
    if p["by_session"]:
        lines.append("- **Per session:**")
        for k, v in p["by_session"].items():
            _c = v.get("net_cash_gbp")
            _cs = f", £{_c:+.2f}" if _c is not None else ""
            lines.append(
                f"  - {k}: {v['fires']} fires, {v['win_rate_pct']}% win, "
                f"{v['net_pips']:+}p (size-blind){_cs}"
            )
    lines.append("")

    b = e["blocks"]
    lines.append("### Blocked setups")
    for sess, _, _ in SESSIONS:
        seg = b["per_session"][sess]
        if seg["total"] == 0:
            lines.append(f"- **{sess}:** none")
            continue
        gates = ", ".join(f"{k}={v}" for k, v in seg["by_gate"].items())
        lines.append(f"- **{sess}:** {seg['total']} total ({gates})")
    if b["would_have_run"]:
        lines.append("- **Would-have-run cases (≥15p in blocked direction ≤60m):**")
        for w in b["would_have_run"]:
            lines.append(
                f"  - {w['ts']} {w['gate']} blocked {w['direction']} → "
                f"{w['would_have_run_pips']}p — {w['reason']}"
            )
    lines.append("")

    h = e["health"]
    lines.append(
        f"### Infra health: RED={h['red_cycles']}, AMBER={h['amber_cycles']}"
    )
    if h["sample_flags"]:
        for f in h["sample_flags"][:5]:
            lines.append(f"  - {f['ts']} {f['overall']}")
    lines.append("")

    je = e.get("journal_errors") or {}
    if je.get("status") == "ok":
        bd = je.get("baseline_days")
        window = (f" (vs prior {bd} days, journal retains {bd})"
                  if bd is not None
                  else " (baseline window unknown)")
        lines.append(
            f"### Journal errors today: NEW={je['new_total']}, "
            f"RECURRING={je['recurring_total']}{window}"
        )
        if je["new"]:
            lines.append("**NEW families (first occurrence in window):**")
            for r in je["new"]:
                lines.append(
                    f"  - [{r['level']}] ×{r['count']} "
                    f"({r['first'][11:19]}..{r['last'][11:19]}) {r['shape']}"
                )
            tail = je["new_total"] - len(je["new"])
            if tail > 0:
                lines.append(f"  - _+{tail} more NEW families_")
        if je["recurring"]:
            lines.append("**RECURRING families (also in prior window):**")
            for r in je["recurring"]:
                lines.append(
                    f"  - [{r['level']}] ×{r['count']} "
                    f"({r['first'][11:19]}..{r['last'][11:19]}) {r['shape']}"
                )
            tail = je["recurring_total"] - len(je["recurring"])
            if tail > 0:
                lines.append(f"  - _+{tail} more RECURRING families_")
    elif je.get("status") == "unavailable":
        lines.append(
            "### Journal errors today: unavailable (journalctl not reachable)"
        )
    lines.append("")

    # News tiers today — Step-1 classifier telemetry surface. Wrapped so any
    # failure here NEVER breaks the rest of the journal.
    try:
        nt = e.get("news_tiers") or {}
        lines.append("### News tiers today")
        events = nt.get("events") or []
        if not events:
            note = nt.get("note") or "No HIGH-impact events classified today."
            lines.append(f"- {note}")
        else:
            for ev in events:
                lines.append(
                    f"- {ev['time']} {ev['currency']} {ev['event_name']} → "
                    f"**{ev['tier']}** ({ev['matched_rule']}) | dev: {ev['deviation']} | "
                    f"new-rules: {ev['under_new_rules']} | current: {ev['current_behaviour']}"
                )
                mv = ev.get("movement")
                if isinstance(mv, dict) and mv:
                    parts_mv = ", ".join(f"{k}={v}" for k, v in mv.items())
                    lines.append(f"    - post-release: {parts_mv}")
        lines.append("")
    except Exception:  # noqa: BLE001
        lines.append("### News tiers today")
        lines.append("- Classification telemetry unavailable.")
        lines.append("")

    lines.append("### Flags")
    if not e["flags"]:
        lines.append("- (none)")
    else:
        for f in e["flags"]:
            lines.append(f"- **[{f['code']}]** ({f['session']}) {f['evidence']}")
    lines.append("")

    lines.append("### Suggestions for improvement")
    sugg = e.get("suggestions") or []
    if not sugg:
        lines.append("- No suggestions flagged today — clean day.")
    else:
        for s in sugg:
            lines.append(f"- **[{s['code']}]** {s['message']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML renderer (inline styles — Hotmail/Outlook strip <style> blocks)
# ---------------------------------------------------------------------------

def _esc(s: Any) -> str:
    """Minimal HTML escape."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# Inline style constants — kept short so email clients don't choke.
_S_BODY = ("font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
           "color:#222;line-height:1.4;max-width:820px;")
_S_H2 = "margin:0 0 4px 0;color:#111;"
_S_H3 = "margin:20px 0 6px 0;color:#333;border-bottom:1px solid #ddd;padding-bottom:2px;"
_S_META = "color:#777;font-size:12px;margin:0 0 12px 0;"
_S_TABLE = ("border-collapse:collapse;margin:8px 0;font-size:13px;")
_S_TH = "border:1px solid #999;padding:4px 8px;background:#f0f0f0;text-align:left;"
_S_TD = "border:1px solid #ccc;padding:4px 8px;"
_S_UL = "margin:6px 0;padding-left:20px;"
_S_LI = "margin:2px 0;"
_S_FLAG_BADGE = ("display:inline-block;padding:1px 6px;margin-right:6px;"
                 "background:#fff3cd;color:#664d03;border:1px solid #ffe69c;"
                 "border-radius:3px;font-family:monospace;font-size:11px;")
_S_SUG_BADGE = ("display:inline-block;padding:1px 6px;margin-right:6px;"
                "background:#cfe2ff;color:#084298;border:1px solid #9ec5fe;"
                "border-radius:3px;font-family:monospace;font-size:11px;")
_S_PNL_POS = "color:#0a7a0a;font-weight:bold;"
_S_PNL_NEG = "color:#b02a2a;font-weight:bold;"
_S_PNL_FLAT = "color:#555;font-weight:bold;"


def _pnl_style(pips: float) -> str:
    if pips > 0:
        return _S_PNL_POS
    if pips < 0:
        return _S_PNL_NEG
    return _S_PNL_FLAT


def render_html(e: Dict[str, Any]) -> str:
    ds = e["day_stats"]
    net = float(e["pnl"]["net_pips"])
    parts: List[str] = []
    parts.append(f'<div style="{_S_BODY}">')
    parts.append(
        f'<h2 style="{_S_H2}">{_esc(e["date"])} '
        f'<span style="color:#666;font-weight:normal;">({_esc(e["day_type"])})</span></h2>'
    )
    parts.append(f'<div style="{_S_META}">generated {_esc(e["generated_at"])}</div>')

    parts.append(f'<div><strong>Day-type rule:</strong> {_esc(e["day_type_rule"])}</div>')
    if e["high_impact_events"]:
        ev = ", ".join(
            f'{_esc(x["ts"][11:16])} {_esc(x["currency"])} {_esc(x["event"])}'
            for x in e["high_impact_events"]
        )
        parts.append(f'<div><strong>High-impact releases:</strong> {ev}</div>')

    day_line = (
        f'open <strong>{_esc(ds["open"])}</strong> / '
        f'high <strong>{_esc(ds["high"])}</strong> / '
        f'low <strong>{_esc(ds["low"])}</strong> / '
        f'close <strong>{_esc(ds["close"])}</strong> → '
        f'net <span style="{_pnl_style(ds["net_pips"])}">{ds["net_pips"]:+}p</span>, '
        f'range {_esc(ds["range_pips"])}p, close_pos {_esc(ds["close_position_in_range"])} '
        f'(0=low,1=high). Market action: <strong>{_esc(ds["market_action"])}</strong>.'
    )
    parts.append(f'<div style="margin-top:8px;"><strong>Day:</strong> {day_line}</div>')

    # ---- Price action table ----
    parts.append(f'<h3 style="{_S_H3}">Price action per session</h3>')
    parts.append(f'<table style="{_S_TABLE}">')
    parts.append(
        "<tr>"
        + "".join(f'<th style="{_S_TH}">{h}</th>' for h in
                  ["Session", "O", "H", "L", "C", "Net", "Range",
                   "Action", "ADX", "ER", "BBw"])
        + "</tr>"
    )
    for sess, _, _ in SESSIONS:
        p = e["per_session_price"][sess]
        parts.append(
            "<tr>"
            + f'<td style="{_S_TD}"><strong>{_esc(sess)}</strong></td>'
            + f'<td style="{_S_TD}">{_esc(p["open"])}</td>'
            + f'<td style="{_S_TD}">{_esc(p["high"])}</td>'
            + f'<td style="{_S_TD}">{_esc(p["low"])}</td>'
            + f'<td style="{_S_TD}">{_esc(p["close"])}</td>'
            + f'<td style="{_S_TD};{_pnl_style(p["net_pips"])}">{p["net_pips"]:+}</td>'
            + f'<td style="{_S_TD}">{_esc(p["range_pips"])}</td>'
            + f'<td style="{_S_TD}"><em>{_esc(p["market_action"])}</em></td>'
            + f'<td style="{_S_TD}">{_esc(p["adx"])}</td>'
            + f'<td style="{_S_TD}">{_esc(p["er"])}</td>'
            + f'<td style="{_S_TD}">{_esc(p["bb_width_pips"])}</td>'
            + "</tr>"
        )
    parts.append("</table>")
    parts.append(f'<ul style="{_S_UL}">')
    for sess, _, _ in SESSIONS:
        p = e["per_session_price"][sess]
        parts.append(
            f'<li style="{_S_LI}"><strong>{_esc(sess)}:</strong> {_esc(p["narrative"])}</li>'
        )
    parts.append("</ul>")

    # ---- Regime calls ----
    parts.append(f'<h3 style="{_S_H3}">Regime calls per session</h3>')
    parts.append(f'<ul style="{_S_UL}">')
    for sess, _, _ in SESSIONS:
        r = e["per_session_regime"][sess]
        if r["bars"] == 0:
            parts.append(f'<li style="{_S_LI}"><strong>{_esc(sess)}:</strong> no regime bars</li>')
            continue
        dist = ", ".join(
            f'{_esc(k)} {v}%'
            for k, v in sorted(r["distribution_pct"].items(), key=lambda kv: -kv[1])
        )
        parts.append(
            f'<li style="{_S_LI}"><strong>{_esc(sess)}:</strong> {dist} '
            f'(bars={r["bars"]}; declamp_certified={r["struct_declamp_certified_bars"]}, '
            f'hist_freshness_downgraded={r["hist_freshness_downgraded_bars"]})</li>'
        )
    parts.append("</ul>")

    # ---- Scorecard ----
    parts.append(f'<h3 style="{_S_H3}">Regime-vs-reality scorecard</h3>')
    parts.append(f'<ul style="{_S_UL}">')
    for sess, s in e["scorecard"].items():
        v = s["verdict"]
        colour = "#0a7a0a" if v == "agree" else "#b08600" if v == "partial" else "#b02a2a" if v == "disagree" else "#555"
        parts.append(
            f'<li style="{_S_LI}"><strong>{_esc(sess)}:</strong> market={_esc(s["market_action"])}, '
            f'regime={_esc(s["dominant_regime"])} ({_esc(s["regime_family"])}) → '
            f'<strong style="color:{colour}">{_esc(v)}</strong></li>'
        )
    parts.append("</ul>")

    # ---- PnL ----
    p = e["pnl"]
    _cash_day = p.get("net_cash_gbp")
    _cash_day_html = (
        f' / <span style="{_pnl_style(_cash_day)}">£{_cash_day:+.2f}</span>'
        if _cash_day is not None else ""
    )
    parts.append(f'<h3 style="{_S_H3}">PnL</h3>')
    parts.append(
        f'<div><strong>Day:</strong> {p["fires"]} fires, {p["wins"]} wins '
        f'({p["win_rate_pct"]}%), net '
        f'<span style="{_pnl_style(p["net_pips"])}">{p["net_pips"]:+}p</span> '
        f'<span style="color:#888;font-size:0.9em;">(size-blind)</span>'
        f'{_cash_day_html}</div>'
    )
    if p["by_strategy"]:
        parts.append(f'<div style="margin-top:6px;"><strong>Per strategy:</strong></div>')
        parts.append(f'<ul style="{_S_UL}">')
        for k, v in sorted(p["by_strategy"].items()):
            _c = v.get("net_cash_gbp")
            _ch = (f' / <span style="{_pnl_style(_c)}">£{_c:+.2f}</span>'
                   if _c is not None else "")
            parts.append(
                f'<li style="{_S_LI}">{_esc(k)}: {v["fires"]} fires, '
                f'{v["win_rate_pct"]}% win, '
                f'<span style="{_pnl_style(v["net_pips"])}">{v["net_pips"]:+}p</span>'
                f' <span style="color:#888;font-size:0.85em;">(size-blind)</span>'
                f'{_ch}</li>'
            )
        parts.append("</ul>")
    if p["by_session"]:
        parts.append(f'<div><strong>Per session:</strong></div>')
        parts.append(f'<ul style="{_S_UL}">')
        for k, v in p["by_session"].items():
            _c = v.get("net_cash_gbp")
            _ch = (f' / <span style="{_pnl_style(_c)}">£{_c:+.2f}</span>'
                   if _c is not None else "")
            parts.append(
                f'<li style="{_S_LI}">{_esc(k)}: {v["fires"]} fires, '
                f'{v["win_rate_pct"]}% win, '
                f'<span style="{_pnl_style(v["net_pips"])}">{v["net_pips"]:+}p</span>'
                f' <span style="color:#888;font-size:0.85em;">(size-blind)</span>'
                f'{_ch}</li>'
            )
        parts.append("</ul>")

    # ---- Blocks ----
    b = e["blocks"]
    parts.append(f'<h3 style="{_S_H3}">Blocked setups</h3>')
    parts.append(f'<ul style="{_S_UL}">')
    for sess, _, _ in SESSIONS:
        seg = b["per_session"][sess]
        if seg["total"] == 0:
            parts.append(f'<li style="{_S_LI}"><strong>{_esc(sess)}:</strong> none</li>')
            continue
        gates = ", ".join(f'{_esc(k)}={v}' for k, v in seg["by_gate"].items())
        parts.append(
            f'<li style="{_S_LI}"><strong>{_esc(sess)}:</strong> {seg["total"]} total ({gates})</li>'
        )
    parts.append("</ul>")
    if b["would_have_run"]:
        parts.append('<div><strong>Would-have-run cases (≥15p in blocked direction ≤60m):</strong></div>')
        parts.append(f'<ul style="{_S_UL}">')
        for w in b["would_have_run"]:
            parts.append(
                f'<li style="{_S_LI}">{_esc(w["ts"])} {_esc(w["gate"])} blocked '
                f'{_esc(w["direction"])} → <strong>{w["would_have_run_pips"]}p</strong> — '
                f'<span style="color:#666">{_esc(w["reason"])}</span></li>'
            )
        parts.append("</ul>")

    # ---- Health ----
    h = e["health"]
    parts.append(
        f'<h3 style="{_S_H3}">Infra health: RED={h["red_cycles"]}, AMBER={h["amber_cycles"]}</h3>'
    )
    if h["sample_flags"]:
        parts.append(f'<ul style="{_S_UL}">')
        for f in h["sample_flags"][:5]:
            parts.append(f'<li style="{_S_LI}">{_esc(f["ts"])} {_esc(f["overall"])}</li>')
        parts.append("</ul>")

    # ---- Journal errors today ----
    je = e.get("journal_errors") or {}
    if je.get("status") == "ok":
        bd = je.get("baseline_days")
        window = (f" (vs prior {bd} days, journal retains {bd})"
                  if bd is not None
                  else " (baseline window unknown)")
        parts.append(
            f'<h3 style="{_S_H3}">Journal errors today: '
            f'NEW={je["new_total"]}, RECURRING={je["recurring_total"]}'
            f'{_esc(window)}</h3>'
        )
        if je["new"]:
            parts.append(
                '<div><strong>NEW families '
                '(first occurrence in window):</strong></div>'
            )
            parts.append(f'<ul style="{_S_UL}">')
            for r in je["new"]:
                parts.append(
                    f'<li style="{_S_LI}">[<strong>{_esc(r["level"])}</strong>] '
                    f'×{r["count"]} '
                    f'({_esc(r["first"][11:19])}..{_esc(r["last"][11:19])}) '
                    f'<code>{_esc(r["shape"])}</code></li>'
                )
            tail = je["new_total"] - len(je["new"])
            if tail > 0:
                parts.append(
                    f'<li style="{_S_LI}"><em>+{tail} more NEW families</em></li>'
                )
            parts.append("</ul>")
        if je["recurring"]:
            parts.append(
                '<div><strong>RECURRING families '
                '(also in prior window):</strong></div>'
            )
            parts.append(f'<ul style="{_S_UL}">')
            for r in je["recurring"]:
                parts.append(
                    f'<li style="{_S_LI}">[<strong>{_esc(r["level"])}</strong>] '
                    f'×{r["count"]} '
                    f'({_esc(r["first"][11:19])}..{_esc(r["last"][11:19])}) '
                    f'<code>{_esc(r["shape"])}</code></li>'
                )
            tail = je["recurring_total"] - len(je["recurring"])
            if tail > 0:
                parts.append(
                    f'<li style="{_S_LI}"><em>+{tail} more RECURRING families</em></li>'
                )
            parts.append("</ul>")
    elif je.get("status") == "unavailable":
        parts.append(
            f'<h3 style="{_S_H3}">Journal errors today: '
            f'unavailable (journalctl not reachable)</h3>'
        )

    # ---- News tiers today (Step-1 classifier telemetry surface) ----
    # Fail-soft wrapper: any failure renders a graceful line and never
    # propagates to the rest of the journal.
    try:
        nt = e.get("news_tiers") or {}
        parts.append(f'<h3 style="{_S_H3}">News tiers today</h3>')
        events = nt.get("events") or []
        if not events:
            note = nt.get("note") or "No HIGH-impact events classified today."
            parts.append(f'<div style="color:#555">{_esc(note)}</div>')
        else:
            parts.append(f'<ul style="{_S_UL}">')
            for ev in events:
                tier = ev["tier"]
                tier_col = ("#b02a2a" if tier == "BIG"
                            else "#b08600" if tier == "MIDDLE"
                            else "#0a7a0a" if tier == "SMALL"
                            else "#555")
                parts.append(
                    f'<li style="{_S_LI}">'
                    f'{_esc(ev["time"])} {_esc(ev["currency"])} '
                    f'<strong>{_esc(ev["event_name"])}</strong> → '
                    f'<span style="color:{tier_col};font-weight:bold">{_esc(tier)}</span> '
                    f'({_esc(ev["matched_rule"])}) | '
                    f'dev: {_esc(ev["deviation"])} | '
                    f'new-rules: {_esc(ev["under_new_rules"])} | '
                    f'current: <em>{_esc(ev["current_behaviour"])}</em>'
                )
                mv = ev.get("movement")
                if isinstance(mv, dict) and mv:
                    parts_mv = ", ".join(f"{_esc(k)}={_esc(v)}" for k, v in mv.items())
                    parts.append(
                        f'<div style="color:#666;font-size:12px;margin-left:8px">'
                        f'post-release: {parts_mv}</div>'
                    )
                parts.append('</li>')
            parts.append("</ul>")
    except Exception:  # noqa: BLE001
        parts.append(f'<h3 style="{_S_H3}">News tiers today</h3>')
        parts.append('<div style="color:#555">Classification telemetry unavailable.</div>')

    # ---- Flags ----
    parts.append(f'<h3 style="{_S_H3}">Flags</h3>')
    if not e["flags"]:
        parts.append(f'<div style="color:#0a7a0a">(none — clean day)</div>')
    else:
        parts.append(f'<ul style="{_S_UL}">')
        for f in e["flags"]:
            parts.append(
                f'<li style="{_S_LI}">'
                f'<span style="{_S_FLAG_BADGE}">{_esc(f["code"])}</span>'
                f'<em>({_esc(f["session"])})</em> {_esc(f["evidence"])}'
                f'</li>'
            )
        parts.append("</ul>")

    # ---- Suggestions ----
    parts.append(f'<h3 style="{_S_H3}">Suggestions for improvement</h3>')
    sugg = e.get("suggestions") or []
    if not sugg:
        parts.append(f'<div style="color:#0a7a0a">No suggestions flagged today — clean day.</div>')
    else:
        parts.append(f'<ul style="{_S_UL}">')
        for s in sugg:
            parts.append(
                f'<li style="{_S_LI}">'
                f'<span style="{_S_SUG_BADGE}">{_esc(s["code"])}</span>'
                f'{_esc(s["message"])}'
                f'</li>'
            )
        parts.append("</ul>")

    parts.append('<hr style="margin:20px 0;border:none;border-top:1px solid #ccc;"/>')
    parts.append('</div>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Idempotent writes
# ---------------------------------------------------------------------------

def write_jsonl_idempotent(entry: Dict[str, Any]) -> None:
    JSONL_OUT.parent.mkdir(parents=True, exist_ok=True)
    day = entry["date"]
    rows: List[Dict[str, Any]] = []
    if JSONL_OUT.exists():
        for row in _iter_jsonl(JSONL_OUT):
            if row.get("date") != day:
                rows.append(row)
    rows.append(entry)
    tmp = JSONL_OUT.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")))
            fh.write("\n")
    tmp.replace(JSONL_OUT)


def write_day_summary_idempotent(entry: Dict[str, Any]) -> None:
    """Serialise the day-type slice of the journal entry to
    logs/day_summary.jsonl (one row per day, idempotent by date).
    Reads from `entry` verbatim — no re-computation. Best-effort; the
    caller wraps this in a try/except so a corrupted summary write never
    breaks the main journal path."""
    DAY_SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    day = entry["date"]
    ds = entry.get("day_stats") or {}
    per_sess = entry.get("per_session_price") or {}
    news = entry.get("news_tiers") or {}
    news_events = news.get("events") if isinstance(news, dict) else None
    # Take the max classifier tier among today's HIGH GBP/USD events; the
    # journal's `news_tiers` payload already carries the per-event tier.
    tier_rank = {"none": 0, "SMALL": 1, "MIDDLE": 2, "BIG": 3}
    max_tier = "none"
    if isinstance(news_events, list):
        for ev in news_events:
            t = str((ev or {}).get("tier") or "").upper()
            if tier_rank.get(t, 0) > tier_rank.get(max_tier, 0):
                max_tier = t

    summary = {
        "date": day,
        "day_type": entry.get("day_type"),
        "day_type_rule": entry.get("day_type_rule"),
        "market_action": ds.get("market_action"),
        "day_open":  ds.get("open"),
        "day_high":  ds.get("high"),
        "day_low":   ds.get("low"),
        "day_close": ds.get("close"),
        "net_pips":  ds.get("net_pips"),
        "range_pips": ds.get("range_pips"),
        "close_position_in_range": ds.get("close_position_in_range"),
        "adx": ds.get("adx"), "er": ds.get("er"),
        "bb_width_pips": ds.get("bb_width_pips"),
        "per_session_action": {
            s: (per_sess.get(s) or {}).get("market_action")
            for s, _, _ in SESSIONS
        },
        "per_session_net_pips": {
            s: (per_sess.get(s) or {}).get("net_pips")
            for s, _, _ in SESSIONS
        },
        "day_news_tier": max_tier,
        "high_impact_events": entry.get("high_impact_events") or [],
    }
    rows: List[Dict[str, Any]] = []
    if DAY_SUMMARY_OUT.exists():
        for row in _iter_jsonl(DAY_SUMMARY_OUT):
            if row.get("date") != day:
                rows.append(row)
    rows.append(summary)
    tmp = DAY_SUMMARY_OUT.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")))
            fh.write("\n")
    tmp.replace(DAY_SUMMARY_OUT)


def append_markdown(entry: Dict[str, Any]) -> None:
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    text = render_markdown(entry)
    # If the same date section already exists (previous run), replace it in place.
    if MD_OUT.exists():
        existing = MD_OUT.read_text(encoding="utf-8")
        header = f"## {entry['date']}"
        if header in existing:
            parts = existing.split(header)
            before = parts[0]
            after = parts[1]
            # everything up to the next "## " header (or end)
            nxt = after.find("\n## ")
            after_rest = after[nxt:] if nxt >= 0 else ""
            MD_OUT.write_text(before + text.rstrip("\n") + "\n" + after_rest,
                              encoding="utf-8")
            return
    with MD_OUT.open("a", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# Email delivery (SendGrid — same creds as briefing_emailer.py)
# ---------------------------------------------------------------------------

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def _mail_cfg(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _mail_configured() -> Tuple[bool, str]:
    """(ok, missing_key_list). Recipient resolves to JOURNAL_EMAIL_TO or EMAIL_TO."""
    missing = []
    if not _mail_cfg("EMAIL_FROM"):
        missing.append("EMAIL_FROM")
    if not (_mail_cfg("JOURNAL_EMAIL_TO") or _mail_cfg("EMAIL_TO")):
        missing.append("JOURNAL_EMAIL_TO or EMAIL_TO")
    if not _mail_cfg("SENDGRID_API_KEY"):
        missing.append("SENDGRID_API_KEY")
    return (not missing, ",".join(missing))


def send_journal_email(entry: Dict[str, Any], md_text: str,
                       html_text: Optional[str] = None) -> bool:
    """Send the day's journal entry via SendGrid.

    Sends BOTH a text/plain part (the exact markdown already written to
    logs/daily_journal.md — verbatim fallback for text-only clients) AND a
    text/html part (rich rendering for Hotmail/Gmail/Outlook).

    Returns True on 2xx, False on any failure. Never raises.
    """
    ok, missing = _mail_configured()
    if not ok:
        logger.warning("[daily_journal.email] not configured (missing: %s)", missing)
        return False

    import requests  # already an autobot dependency; imported lazily

    from_addr = _mail_cfg("EMAIL_FROM")
    to_raw = _mail_cfg("JOURNAL_EMAIL_TO") or _mail_cfg("EMAIL_TO")
    to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]
    api_key = _mail_cfg("SENDGRID_API_KEY")

    subject = (
        f"AutoBot Journal — {entry['date']} ({entry['day_type']}) "
        f"— net {entry['pnl']['net_pips']:+}p"
    )

    # SendGrid requires text/plain BEFORE text/html per RFC 1341 (multipart
    # ordering: the last part is preferred). Mail clients that support HTML
    # will render that; text-only clients fall back to the plain part.
    content = [{"type": "text/plain", "value": md_text}]
    if html_text:
        content.append({"type": "text/html", "value": html_text})

    payload = {
        "personalizations": [{"to": [{"email": a} for a in to_addrs]}],
        "from": {"email": from_addr},
        "subject": subject,
        "content": content,
    }

    try:
        resp = requests.post(
            SENDGRID_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
    except Exception as ex:  # noqa: BLE001
        logger.warning("[daily_journal.email] request failed: %s", ex)
        return False

    body_snip = (resp.text or "")[:200]
    if 200 <= resp.status_code < 300:
        logger.info(
            "[daily_journal.email] sent '%s' → %s (status=%s)",
            subject, to_addrs, resp.status_code,
        )
        print(f"daily_journal: email sent to {to_addrs} "
              f"(status={resp.status_code} sendgrid_msg_id="
              f"{resp.headers.get('X-Message-Id', 'n/a')})")
        return True
    logger.warning(
        "[daily_journal.email] SendGrid %s: %s", resp.status_code, body_snip
    )
    print(f"daily_journal: email FAILED (status={resp.status_code}): {body_snip}",
          file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> int:
    ap = argparse.ArgumentParser(description="Daily trading journal generator")
    ap.add_argument("--date", help="YYYY-MM-DD (UTC). Default: today.")
    ap.add_argument("--dry-run", action="store_true", help="Print entry, no writes")
    ap.add_argument("--email-test", action="store_true",
                    help="Force one email send regardless of DAILY_JOURNAL_EMAIL_ENABLED")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if str(os.getenv("DAILY_JOURNAL_ENABLED", "1")).strip().lower() not in ("1", "true", "yes", "on"):
        print("daily_journal: disabled via DAILY_JOURNAL_ENABLED, exiting 0")
        return 0

    if args.date:
        try:
            day = _date_t.fromisoformat(args.date)
        except ValueError:
            print(f"daily_journal: bad --date {args.date!r}", file=sys.stderr)
            return 2
    else:
        day = datetime.now(timezone.utc).date()

    try:
        entry = build_entry(day)
    except Exception as ex:  # noqa: BLE001
        print(f"daily_journal: build failed: {ex}", file=sys.stderr)
        traceback.print_exc()
        return 1

    md_text = render_markdown(entry)
    html_text = render_html(entry)

    if args.dry_run:
        print(json.dumps(entry, indent=2, default=str))
        print("\n---MARKDOWN---\n")
        print(md_text)
        if args.email_test:
            try:
                send_journal_email(entry, md_text, html_text)
            except Exception as ex:  # noqa: BLE001
                # Belt-and-braces — send_journal_email already swallows,
                # but never let email crash a dry-run either.
                print(f"daily_journal: email exception (non-fatal): {ex}",
                      file=sys.stderr)
        return 0

    try:
        write_jsonl_idempotent(entry)
        append_markdown(entry)
    except Exception as ex:  # noqa: BLE001
        print(f"daily_journal: write failed: {ex}", file=sys.stderr)
        traceback.print_exc()
        return 1

    # Part D (2026-07-16): day-type serialization — best-effort, must
    # never fail the primary journal write above.
    try:
        write_day_summary_idempotent(entry)
    except Exception as ex:  # noqa: BLE001
        print(f"daily_journal: day_summary write failed (non-fatal): {ex}",
              file=sys.stderr)

    print(f"daily_journal: wrote entry for {day.isoformat()} "
          f"({len(entry['flags'])} flags, {len(entry.get('suggestions') or [])} suggestions, "
          f"net {entry['pnl']['net_pips']:+}p)")

    email_enabled = str(
        os.getenv("DAILY_JOURNAL_EMAIL_ENABLED", "0")
    ).strip().lower() in ("1", "true", "yes", "on")
    if email_enabled or args.email_test:
        try:
            send_journal_email(entry, md_text, html_text)
        except Exception as ex:  # noqa: BLE001
            # send_journal_email already catches every documented failure —
            # this outer guard exists only so an unexpected error never
            # propagates out of the CLI after the JSONL/MD have been written.
            print(f"daily_journal: email exception (non-fatal): {ex}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
