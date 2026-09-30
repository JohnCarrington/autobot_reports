"""
trades_api.py — Lightweight read-only REST API for closed trade data.

Serves GET /trades from IG Markets closed positions history on port 8080.
Enriches IG data with strategy/close_reason from sweep journal CSVs
where a matching trade exists (pair + entry_price within tolerance).
Caches results for 60 seconds to avoid hammering the IG API.
Runs as a background daemon thread inside AutoBot.
"""

import csv
import datetime as dt
import json as _json
import logging
import math
import os
import re as _re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/opt/tradingbot")

from datetime import timedelta

from flask import Flask, jsonify, request, session

logger = logging.getLogger("AutoBot")

app = Flask(__name__)

# Cookie-based dashboard auth (2026-06-16). Replaces the nginx Basic-auth
# gate. Secret MUST be a fixed literal in .env so a trades-api restart
# doesn't invalidate every signed-in browser.
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

PAIR_MAP = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "USD/CAD": "USDCAD",
    "GBP/JPY": "GBPJPY",
    "AUD/USD": "AUDUSD",
    "EUR/GBP": "EURGBP",
}

HISTORY_DAYS = int(os.getenv("TRADES_API_HISTORY_DAYS", "30"))
CACHE_TTL_S = 60

_cache_lock = threading.Lock()
# Legacy single-account cache. Used when DASHBOARD_ENV_TOGGLE_ENABLED=0
# (default) so /trades is byte-equivalent to the pre-toggle behaviour.
# Keyed by view ("grouped" | "raw") so the Grouped⇄Raw dashboard toggle
# doesn't invalidate the other view's TTL.
_cache: dict[str, dict] = {}

# Env-keyed cache for the LIVE/DEMO toggle (Part 3). Lazily populated.
# Each env holds a per-view bucket so live↔demo↔raw↔grouped never cross-
# contaminate. We keep BOTH the legacy and the env caches alive so
# single-account callers (no ?env) never invalidate the toggle's data
# and vice versa.
_env_cache_lock = threading.Lock()
_env_cache: dict[str, dict[str, dict]] = {
    "demo": {},
    "live": {},
}

# Per-env IG session cache for the toggle path. Demo on a host whose
# host-level IG_ACC_TYPE is already DEMO routes to the existing
# ig_auth singleton (no second login). Other combinations build a
# fresh IGService keyed by env and stash it here.
_env_session_lock = threading.Lock()
_env_session_cache: dict[str, object | None] = {"demo": None, "live": None}

DASHBOARD_ENV_TOGGLE_ENABLED = (
    os.getenv("DASHBOARD_ENV_TOGGLE_ENABLED", "0") or "0"
).strip() == "1"
DEFAULT_DASHBOARD_ENV = (
    os.getenv("DEFAULT_DASHBOARD_ENV", "demo") or "demo"
).strip().lower()
if DEFAULT_DASHBOARD_ENV not in ("demo", "live"):
    DEFAULT_DASHBOARD_ENV = "demo"


def _fetch_from_ig() -> list[dict]:
    """Query IG transaction history and return closed trades."""
    try:
        from ig_auth import get_ig_session
        session = get_ig_session()
        ig = session[0] if isinstance(session, (tuple, list)) else session

        ms = HISTORY_DAYS * 24 * 3600 * 1000
        txns = ig.fetch_transaction_history_by_type_and_period(ms, "ALL")

        deals = txns[txns["transactionType"] == "DEAL"]

        trades = []
        for _, row in deals.iterrows():
            instrument = str(row.get("instrumentName", ""))
            pair = PAIR_MAP.get(instrument, instrument.replace("/", ""))

            size_str = str(row.get("size", ""))
            if size_str.startswith("+"):
                direction = "BUY"
            elif size_str.startswith("-"):
                direction = "SELL"
            else:
                direction = "UNKNOWN"

            # Parse PnL from "£-12.00" or "£3.70" format
            pnl_raw = str(row.get("profitAndLoss", ""))
            try:
                pnl_gbp = float(pnl_raw.replace("£", "").replace(",", ""))
            except (ValueError, TypeError):
                pnl_gbp = None

            entry = _to_float(row.get("openLevel"))
            close = _to_float(row.get("closeLevel"))

            # Calculate pips PnL from entry/close
            pips_pnl = None
            if entry is not None and close is not None:
                if direction == "BUY":
                    pips_pnl = round(close - entry, 1)
                elif direction == "SELL":
                    pips_pnl = round(entry - close, 1)

            # Parse date from DD/MM/YY format
            date_str = str(row.get("date", ""))
            try:
                d, m, y = date_str.split("/")
                ts = f"20{y}-{m}-{d}T00:00:00Z"
            except Exception:
                ts = date_str

            size_val = None
            try:
                size_val = abs(int(size_str))
            except (ValueError, TypeError):
                pass

            trades.append({
                "timestamp": ts,
                "pair": pair,
                "direction": direction,
                "entry_price": entry,
                "close_price": close,
                "pips_pnl": pips_pnl,
                "pnl_gbp": pnl_gbp,
                "size": size_val,
                "strategy": "",
                "close_reason": "",
                "session": "",
            })

        return trades

    except Exception as e:
        logger.warning("trades_api: IG fetch failed: %s", e)
        return []


def _to_float(val) -> float | None:
    # IG's open-positions response uses NaN sentinels for missing levels
    # (e.g. an open position with no take-profit set returns
    # limitLevel=NaN). float("NaN") parses successfully and `is None`
    # doesn't catch it, so the NaN propagates into the /trades response
    # and Flask's jsonify (allow_nan=True by default) emits literal NaN
    # — which browsers reject as invalid JSON. Coerce non-finite to None.
    if val is None:
        return None
    try:
        v = float(val)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, 2)


def _session_from_timestamp(ts: str) -> str:
    """Derive session name from ISO timestamp hour."""
    try:
        hour = int(ts[11:13])
    except (IndexError, ValueError):
        return ""
    if hour >= 22 or hour < 6:
        return "Asian"
    if hour < 12:
        return "London"
    if hour < 17:
        return "New York"
    return "Late"


LOG_DIR = Path("/opt/tradingbot/logs")
SIGNAL_LOG_PATH = LOG_DIR / "signal_log.jsonl"
_ENTRY_PRICE_TOLERANCE = 2.0  # points — match if entry prices are within this
_DATE_MATCH_TOLERANCE_DAYS = 1  # journal date must be within ±1 day of IG date


# Part F (2026-07-16): cash restatement. Signal-log pips are size-blind;
# a scaled winner banks at half size, an unscaled loser dies at full
# size. Cash = (partial_bank + runner_pnl) × (TRADE_SIZE/2) for scaled
# fires, pnl_pips × TRADE_SIZE for unscaled. Fail-safe: returns None
# when pnl fields are missing so the caller can distinguish "unknown"
# from "£0.00".
_TRADES_API_TRADE_SIZE_DEFAULT = 2.0


def _trade_size_gbp_per_point() -> float:
    try:
        v = float(os.getenv("TRADE_SIZE", str(_TRADES_API_TRADE_SIZE_DEFAULT)))
        return v if v > 0 else _TRADES_API_TRADE_SIZE_DEFAULT
    except (TypeError, ValueError):
        return _TRADES_API_TRADE_SIZE_DEFAULT


def _fire_cash_gbp(row: dict) -> "float | None":
    try:
        ts = _trade_size_gbp_per_point()
        pb = row.get("partial_bank_pips")
        if pb is not None:
            total = row.get("total_pnl_pips")
            if total is None:
                pnl = row.get("pnl_pips")
                if pb is not None and pnl is not None:
                    total = float(pb) + float(pnl)
            if total is None:
                return None
            return round(float(total) * (ts / 2.0), 2)
        pnl = row.get("pnl_pips")
        if pnl is None:
            return None
        return round(float(pnl) * float(ts), 2)
    except (TypeError, ValueError):
        return None


def _date_from_iso(ts: str) -> str:
    """Return YYYY-MM-DD from an ISO timestamp, or '' on failure."""
    if not ts or len(ts) < 10:
        return ""
    return ts[:10]


def _dates_within_one_day(a: str, b: str) -> bool:
    """True if both YYYY-MM-DD strings are within ±1 calendar day."""
    if not a or not b:
        return False
    from datetime import date
    try:
        da = date.fromisoformat(a)
        db = date.fromisoformat(b)
    except ValueError:
        return False
    return abs((da - db).days) <= _DATE_MATCH_TOLERANCE_DAYS


def _load_journal_index() -> dict:
    """Build lookup index from sweep journal CSVs.

    Returns dict keyed by (pair, direction, entry_price_rounded, journal_date)
    → {strategy, close_reason, timestamp}. Including the journal date in the
    key prevents an old journal entry's metadata (and timestamp) from being
    applied to an IG deal that simply shares the same rounded entry price.
    """
    index = {}
    try:
        for path in sorted(LOG_DIR.glob("sweep_journal_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].csv")):
            try:
                with open(path, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row.get("taken") != "True":
                            continue
                        pair = row.get("symbol", "")
                        direction = row.get("signal", "")
                        entry_s = row.get("entry_price", "")
                        timestamp = row.get("timestamp", "")
                        journal_date = _date_from_iso(timestamp)
                        if not pair or not direction or not entry_s or not journal_date:
                            continue
                        try:
                            entry_rounded = round(float(entry_s))
                        except (ValueError, TypeError):
                            continue
                        key = (pair, direction, entry_rounded, journal_date)
                        # Keep the most recent entry for each key
                        index[key] = {
                            "strategy": row.get("mode", ""),
                            "close_reason": row.get("close_reason", ""),
                            "timestamp": timestamp,
                        }
            except Exception:
                continue
    except Exception:
        pass
    return index


def _enrich_with_journal(trades: list[dict]) -> list[dict]:
    """Join IG trades with sweep journal metadata.

    Match requires (pair, direction, rounded entry within ±2) AND that the
    journal date is within ±1 day of the IG record's date. Without the date
    constraint, an old journal entry whose entry_price rounds to the same
    integer as a recent IG deal would re-stamp that deal with the journal's
    timestamp, mis-dating the deal by weeks.
    """
    index = _load_journal_index()
    if not index:
        return trades

    # Group keys by (pair, direction, entry_rounded) so we can scan candidate
    # journal dates quickly.
    by_pde: dict = {}
    for (pair, direction, entry_r, journal_date), val in index.items():
        by_pde.setdefault((pair, direction, entry_r), []).append((journal_date, val))

    for trade in trades:
        pair = trade.get("pair", "")
        direction = trade.get("direction", "")
        entry = trade.get("entry_price")
        if not pair or not direction or entry is None:
            continue

        ig_date = _date_from_iso(trade.get("timestamp", ""))

        entry_rounded = round(entry)
        match = None
        for offset in (0, 1, -1, 2, -2):
            candidates = by_pde.get((pair, direction, entry_rounded + offset))
            if not candidates:
                continue
            # Prefer same-day matches, then within-tolerance matches.
            same_day = [v for d, v in candidates if d == ig_date]
            if same_day:
                match = same_day[0]
                break
            within_tol = [v for d, v in candidates if _dates_within_one_day(d, ig_date)]
            if within_tol:
                match = within_tol[0]
                break

        if match:
            trade["strategy"] = match["strategy"]
            trade["close_reason"] = match["close_reason"]
            # Date proximity has already been verified by the match logic, so
            # the timestamp overwrite is safe.
            if match["timestamp"] and trade["timestamp"].endswith("T00:00:00Z"):
                trade["timestamp"] = match["timestamp"]
            trade["session"] = _session_from_timestamp(trade["timestamp"])

    return trades


# ── BOT FIRES FROM signal_log.jsonl ──────────────────────────────────────────
# signal_log already stores one canonical row per fire with partial_bank_pips
# folded into total_pnl_pips, so dashboards see one trade per decision instead
# of one row per IG close leg.

def _load_signal_log_fires(days: int = HISTORY_DAYS) -> list[dict]:
    """Read signal_log.jsonl and return one canonical record per fire,
    bucketed by open date (UTC). Most-recent first."""
    if not SIGNAL_LOG_PATH.exists():
        return []
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date()
    fires: list[dict] = []
    try:
        with open(SIGNAL_LOG_PATH, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = _json.loads(ln)
                except Exception:
                    continue
                ts_open = (o.get("timestamp_open") or "").strip()
                if len(ts_open) < 10:
                    continue
                try:
                    open_date = dt.date.fromisoformat(ts_open[:10])
                except ValueError:
                    continue
                if open_date < cutoff:
                    continue
                # Prefer total_pnl_pips (folds the partial bank). Fall back to
                # pnl_pips (runner-only) for rows that predate the field.
                total_pips = o.get("total_pnl_pips")
                if total_pips is None:
                    total_pips = o.get("pnl_pips")
                # Part F (2026-07-16): cash-equivalent from leg × size.
                # Scaled trades run each leg at TRADE_SIZE/2; unscaled at
                # TRADE_SIZE. Fail-safe: cash is None when pnl fields are
                # missing (readers must treat as unknown, not £0.00).
                cash_gbp = _fire_cash_gbp(o)
                fires.append({
                    # backward-compat /trades fields
                    "timestamp": ts_open,
                    "pair": o.get("pair"),
                    "direction": o.get("direction"),
                    "entry_price": o.get("entry"),
                    "close_price": o.get("close_price"),
                    # Legacy: pips_pnl is size-blind. Kept for existing
                    # consumers; new consumers should prefer cash_gbp.
                    "pips_pnl": total_pips,
                    "pips_pnl_size_blind": total_pips,
                    "cash_gbp": cash_gbp,
                    "pnl_gbp": cash_gbp,   # populate the previously-null field
                    "size": None,
                    "strategy": o.get("strategy") or "",
                    "close_reason": o.get("close_reason") or "",
                    "session": o.get("session") or _session_from_timestamp(ts_open),
                    # extras (additive — safe for existing consumers)
                    "deal_id": o.get("deal_id"),
                    "timestamp_close": o.get("timestamp_close"),
                    "open_date": open_date.isoformat(),
                    "scaled_out": bool(o.get("scaled_out")),
                    "partial_bank_pips": o.get("partial_bank_pips"),
                    "runner_pnl_pips": o.get("runner_pnl_pips"),
                    "total_pnl_pips": total_pips,
                    "outcome": o.get("outcome") or "",
                    "source": "bot",
                })
    except Exception as e:
        logger.warning("trades_api: signal_log load failed: %s", e)
        return []
    fires.sort(key=lambda x: x["timestamp"], reverse=True)
    return fires


# ── IG ACTIVITY API RECONCILIATION ───────────────────────────────────────────
# IG's transaction-history `reference` field is the CLOSE deal_id, which does
# not match signal_log.deal_id (the OPEN deal_id). Use the activity API
# instead — its open-event `dealId` is the same namespace signal_log records,
# and it carries `channel` (API / Mobile / System / Web) to identify the
# originating client.

_OPENED_RE = _re.compile(r"Position opened:\s*([A-Z0-9]+)", _re.IGNORECASE)
_CLOSED_RE = _re.compile(r"Position(?:/s)? closed:\s*([A-Z0-9]+)", _re.IGNORECASE)


def _parse_position_suffix(result: str) -> str:
    """Extract the position suffix from an IG activity `result` text, used to
    pair an open event with its later close event(s)."""
    if not result:
        return ""
    m = _OPENED_RE.search(result)
    if m:
        return m.group(1).upper()
    m = _CLOSED_RE.search(result)
    if m:
        return m.group(1).upper()
    return ""


def _fetch_ig_activity(days: int = HISTORY_DAYS):
    """Pull IG account activity for the window. Returns the IGService
    DataFrame or None on failure."""
    try:
        from ig_auth import get_ig_session
        session = get_ig_session()
        ig = session[0] if isinstance(session, (tuple, list)) else session
        today = dt.date.today()
        frm = today - dt.timedelta(days=days)
        # IG accepts end-date inclusive; add 1 day so today's events are included.
        return ig.fetch_account_activity_by_date(frm, today + dt.timedelta(days=1))
    except Exception as e:
        logger.warning("trades_api: IG activity fetch failed: %s", e)
        return None


def _build_external_deals(activity_df, fire_deal_ids: set) -> list[dict]:
    """Walk IG activity events, pair opens to closes by suffix, and return
    any opens whose dealId is NOT a bot fire — these are the externals
    (manual web/mobile trades or another API client on the same account)."""
    opens: dict = {}
    closes: dict = {}
    try:
        for _, row in activity_df.iterrows():
            res = str(row.get("result", "") or "")
            suf = _parse_position_suffix(res)
            if not suf:
                continue
            rd = {
                "deal_id":     str(row.get("dealId", "") or "").strip(),
                "date":        str(row.get("date", "") or ""),         # DD/MM/YY BST
                "time":        str(row.get("time", "") or ""),         # HH:MM BST
                "marketName":  str(row.get("marketName", "") or ""),
                "channel":     str(row.get("channel", "") or ""),
                "activity":    str(row.get("activity", "") or ""),
                "size_str":    str(row.get("size", "") or ""),
                "level":       _to_float(row.get("level")),
                "result":      res,
            }
            if "opened" in res.lower():
                opens[suf] = rd
            elif "closed" in res.lower():
                # If a position has multiple legs (a partial then a runner)
                # both will report the same suffix; keep the latest close
                # we encounter so the recorded close_level / pips reflect
                # the final exit rather than the partial bank.
                closes[suf] = rd
    except Exception as e:
        logger.warning("trades_api: IG activity parse failed: %s", e)
        return []

    externals: list[dict] = []
    for suf, op in opens.items():
        did = op["deal_id"]
        if did and did in fire_deal_ids:
            continue
        cl = closes.get(suf)
        sz = op["size_str"]
        if sz.startswith("+"):
            direction = "BUY"
        elif sz.startswith("-"):
            direction = "SELL"
        else:
            direction = "UNKNOWN"
        try:
            size_val = abs(int(float(sz)))
        except (ValueError, TypeError):
            size_val = None
        open_level = op["level"]
        close_level = cl["level"] if cl else None
        pips_pnl = None
        if open_level is not None and close_level is not None:
            if direction == "BUY":
                pips_pnl = round(close_level - open_level, 1)
            elif direction == "SELL":
                pips_pnl = round(open_level - close_level, 1)
        externals.append({
            "deal_id": did,
            "pair": PAIR_MAP.get(op["marketName"], op["marketName"].replace("/", "")),
            "direction": direction,
            "size": size_val,
            "channel": op["channel"],            # API / Mobile / System / Web
            "ig_open_date": op["date"],
            "ig_open_time": op["time"],
            "ig_close_date": cl["date"] if cl else None,
            "ig_close_time": cl["time"] if cl else None,
            "open_level": open_level,
            "close_level": close_level,
            "pips_pnl": pips_pnl,
            "still_open": cl is None,
            "result": op["result"],
            "activity": op["activity"],
            "source": "external",
        })

    # Best-effort enrichment of externals from the sweep journal (strategy /
    # close-reason hints only — they are advisory for externals).
    if externals:
        enrich_input = [{
            "pair": e["pair"],
            "direction": e["direction"],
            "entry_price": e["open_level"],
            "timestamp": "",
            "strategy": "",
            "close_reason": "",
            "session": "",
        } for e in externals]
        try:
            enriched = _enrich_with_journal(enrich_input)
            for e, en in zip(externals, enriched):
                if en.get("strategy"):
                    e["journal_strategy_hint"] = en["strategy"]
                if en.get("close_reason"):
                    e["journal_close_reason_hint"] = en["close_reason"]
        except Exception:
            pass

    # Stable order: most-recent open first (by IG date+time string sort).
    externals.sort(key=lambda x: (x.get("ig_open_date") or "", x.get("ig_open_time") or ""), reverse=True)
    return externals


def _reconcile(days: int = HISTORY_DAYS) -> dict:
    """Cross-reference signal_log fires with IG activity opens. Returns the
    summary payload served by /trades/summary."""
    fires = _load_signal_log_fires(days)
    fire_deal_ids = {f["deal_id"] for f in fires if f.get("deal_id")}

    activity_df = _fetch_ig_activity(days)
    if activity_df is None or len(activity_df) == 0:
        externals: list[dict] = []
    else:
        externals = _build_external_deals(activity_df, fire_deal_ids)

    bot_pips = [f["total_pnl_pips"] for f in fires if f.get("total_pnl_pips") is not None]
    bot_w = sum(1 for p in bot_pips if p > 0)
    bot_l = sum(1 for p in bot_pips if p < 0)
    bot_net = round(sum(bot_pips), 2) if bot_pips else 0.0
    # Part F: cash restatement. Cash-per-fire is computed at load time
    # (`_load_signal_log_fires`) so this is a straight sum. None values
    # are dropped so unrecorded fires don't skew the total to £0.
    bot_cash_vals = [f["cash_gbp"] for f in fires if f.get("cash_gbp") is not None]
    bot_net_cash = round(sum(bot_cash_vals), 2) if bot_cash_vals else 0.0

    ext_pips = [e["pips_pnl"] for e in externals if e.get("pips_pnl") is not None]
    ext_net = round(sum(ext_pips), 2) if ext_pips else 0.0

    return {
        "bot_trades": fires,
        "external_deals": externals,
        "summary": {
            "window_days": days,
            "bot_count": len(fires),
            "bot_w": bot_w,
            "bot_l": bot_l,
            # Legacy `bot_net_pips` retained; the size-blind flavour is
            # exposed alongside so new consumers pick it explicitly.
            # `bot_net_cash_gbp` is the true P&L in £ (Part A leg math).
            "bot_net_pips": bot_net,
            "bot_net_pips_size_blind": bot_net,
            "bot_net_cash_gbp": bot_net_cash,
            "external_count": len(externals),
            "external_net_pips": ext_net,
            "external_still_open": sum(1 for e in externals if e.get("still_open")),
        },
    }


# ── IG SPINE PATH (env-gated, opt-in) ────────────────────────────────────────
# When TRADES_USE_IG_SPINE=1 we reconstruct the trade list from the shared IG
# account: transactions for £-PnL and detailed activity for stop/limit/parent
# linkage. Each transaction `reference` is a closing-leg dealId; the matching
# activity row carries `affectedDealId` (the parent open position dealId) and
# the leg's stopLevel/limitLevel. We aggregate legs by parent dealId so the
# dashboard sees one row per position, then enrich from 161's signal_log via
# the open dealId. The legacy signal-log-only path stays unchanged and is
# used as the fallback whenever an IG fetch or join fails.

USE_IG_SPINE = (os.getenv("TRADES_USE_IG_SPINE", "0") or "0").strip() == "1"
AGGREGATE_POSITIONS = (os.getenv("TRADES_AGGREGATE_POSITIONS", "1") or "1").strip() == "1"

# Mapping of distinct signal_log close_reason prefixes → exit_type. Built from
# the live signal_log on 2026-06-03 (see commit message). Anything not listed
# falls through to the IG-level heuristic, then UNKNOWN.
_EXIT_TYPE_BY_CLOSE_REASON: dict[str, str] = {
    "SL hit": "STOP",
    "TP hit": "TARGET",
    "Breakeven stop hit (IG server-side)": "BREAKEVEN",
    "BRIEFING_SL_HIT_OPEN": "STOP",
    "BRIEFING_TP1_CLOSE": "TARGET",
    # BRIEFING_TP_SL_OPEN can be either TP or SL — resolved by pnl sign below.
    "STRUCTURE_EXIT": "EARLY",
    "MANAGER_PROFIT_PROTECT": "EARLY",
    "REGIME_MAX_HOLD": "EARLY",
    "PRE_NEWS_CLOSE": "EARLY",
    "NY_CLOSE": "EARLY",
    "BIAS_FLIP_CLOSE": "EARLY",
    "BRIEF_INVALIDATED": "EARLY",
    "BRIEFING_EXEC_INVALIDATION": "EARLY",
    "BRIEFING_EXEC_TIME_EXIT": "EARLY",
    "session_close_16_utc": "EARLY",
    "macd_line_zero_cross": "EARLY",
    "External/manual close detected (IG open positions)": "EXTERNAL",
    "IG_RECONCILE": "EXTERNAL",
    "PHANTOM_NEVER_EXECUTED": "UNKNOWN",
}

_LEVEL_NEAR_PTS = 1.5  # close-level "≈" stop/limit tolerance, in price points


def _close_reason_prefix(s: str) -> str:
    """Strip the trailing ':<details>' from a close_reason so the prefix can
    key into _EXIT_TYPE_BY_CLOSE_REASON."""
    s = (s or "").strip()
    if not s:
        return ""
    return s.split(":", 1)[0].strip()


def _parse_pnl_gbp(raw) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).replace("£", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_size_signed(raw) -> tuple[str, float | None]:
    """Parse '+3' / '-3' / '3.0' → (direction, signed_size)."""
    s = str(raw or "").strip()
    direction = "UNKNOWN"
    if s.startswith("+"):
        direction = "BUY"
    elif s.startswith("-"):
        direction = "SELL"
    try:
        v = float(s)
        if direction == "UNKNOWN":
            direction = "BUY" if v >= 0 else "SELL"
        return direction, v
    except (ValueError, TypeError):
        return direction, None


_BST_TZ_BUG_RE = _re.compile(r"(\d{2}:\d{2}:\d{2}) (\d{2}:\d{2})$")


def _normalize_bst_tz(s: str) -> str:
    """trading_ig occasionally surfaces a row whose timezone offset arrives as
    "2026-05-07T10:11:43 01:00" — a SPACE instead of the '+' that ISO-8601
    requires. `datetime.fromisoformat` raises on the space form. Replace the
    final " HH:MM" with "+HH:MM" so downstream parsers don't blow up.

    Idempotent: strings already in ISO form or with no offset are returned
    unchanged. Pure string op — never raises."""
    try:
        if not s:
            return s
        return _BST_TZ_BUG_RE.sub(r"\1+\2", str(s))
    except Exception:
        return s


def _iso_z(s) -> str:
    """Normalize an IG datetime string to YYYY-MM-DDTHH:MM:SSZ. Returns '' on
    failure so the dashboard's date keying stays predictable.

    Defensively normalises the trading_ig BST-space-offset bug before the
    19-char slice — even though the slice itself drops the broken portion,
    routing through `_normalize_bst_tz` first means a future caller that
    needs the full timestamp (e.g. for fromisoformat) gets a parseable
    string instead of a silent truncate."""
    if not s:
        return ""
    s = _normalize_bst_tz(str(s).strip())
    if not s:
        return ""
    if s.endswith("Z"):
        return s
    if "T" in s and len(s) >= 19:
        return s[:19] + "Z"
    return s


def _fetch_ig_transactions(ig, from_date: dt.datetime, to_date: dt.datetime) -> list[dict]:
    """Paginated DEAL-only transactions via fetch_transaction_history. The IG
    library does NOT paginate this endpoint internally, so we walk pages until
    a short page comes back (or we hit the safety bound)."""
    rows: list[dict] = []
    page = 1
    PAGE_SIZE = 100
    SAFETY_PAGES = 50
    while page <= SAFETY_PAGES:
        df = ig.fetch_transaction_history(
            from_date=from_date,
            to_date=to_date,
            page_size=PAGE_SIZE,
            page_number=page,
        )
        if df is None or len(df) == 0:
            break
        for _, r in df.iterrows():
            if str(r.get("transactionType", "")).upper() != "DEAL":
                continue
            rows.append({
                "dateUtc":         str(r.get("dateUtc") or r.get("date") or ""),
                "openDateUtc":     str(r.get("openDateUtc") or ""),
                "instrumentName":  str(r.get("instrumentName") or ""),
                "openLevel":       _to_float(r.get("openLevel")),
                "closeLevel":      _to_float(r.get("closeLevel")),
                "profitAndLoss":   _parse_pnl_gbp(r.get("profitAndLoss")),
                "size_str":        str(r.get("size") or ""),
                "reference":       str(r.get("reference") or "").strip(),
            })
        if len(df) < PAGE_SIZE:
            break
        page += 1
    return rows


_ACTIVITY_DT_STRIP_RE = _re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*$")


def _strip_tz_for_activity(value: str) -> str:
    """IG's /history/activity v3 endpoint rejects any timezone suffix on
    the from/to params, including a clean "+01:00" — the only form it
    accepts is "YYYY-MM-DDTHH:MM:SS". Our naive datetimes already
    serialise that way on the FIRST page (trading_ig calls
    strftime('%Y-%m-%dT%H:%M:%S') with no %z). On the SECOND page,
    however, IG's own `next` URL embeds a `+01:00` BST offset that the
    same endpoint then refuses. Strip the suffix back to the bare
    YYYY-MM-DDTHH:MM:SS form before re-sending."""
    if not value:
        return value
    m = _ACTIVITY_DT_STRIP_RE.match(str(value).strip())
    return m.group(1) if m else str(value).strip()


def _fetch_ig_activity_detailed(ig, from_date: dt.datetime, to_date: dt.datetime):
    """Detailed activity DataFrame.

    trading_ig 0.x's fetch_account_activity has a BST-window pagination
    bug: IG's own `next` URL embeds a BST offset (`+01:00`) on the
    from/to params, and IG's v3 activity endpoint then refuses any
    suffix beyond YYYY-MM-DDTHH:MM:SS — leading to HTTP 400 ("Unable
    to parse datetime=…") on the second page of any DST-crossing
    window. The library also extracts those params via parse_qs which
    decodes `+` as space, compounding the bug.

    We re-implement the pagination loop here: read the `next` URL via
    parse_qsl, then strip the timezone suffix back to the bare
    seconds form before sending the next request. Falls back to the
    library's fetch_account_activity if our manual path raises (we'd
    rather get the original error in the journal than mask new bug
    shapes)."""
    from urllib.parse import urlparse, parse_qsl
    import pandas as _pd
    try:
        params: dict[str, object] = {}
        if from_date:
            params["from"] = from_date.strftime('%Y-%m-%dT%H:%M:%S')
        if to_date:
            params["to"] = to_date.strftime('%Y-%m-%dT%H:%M:%S')
        params["detailed"] = "true"
        params["pageSize"] = 500
        all_activities: list[dict] = []
        more = True
        guard = 0
        while more and guard < 200:
            guard += 1
            resp = ig._req("read", "/history/activity/", params, None, "3")
            data = ig.parse_response(resp.text)
            all_activities.extend(data.get("activities", []) or [])
            paging = (data.get("metadata") or {}).get("paging") or {}
            nxt = paging.get("next")
            if not nxt:
                more = False
                continue
            # parse_qsl URL-decodes `+` as space (form-encoding). We
            # then strip back to YYYY-MM-DDTHH:MM:SS because IG itself
            # refuses any timezone suffix on this endpoint — the only
            # variant that survives a paginated /history/activity walk.
            q = dict(parse_qsl(urlparse(nxt).query, keep_blank_values=True))
            for k in ("from", "to"):
                if k in q and q[k]:
                    params[k] = _strip_tz_for_activity(q[k])
                elif k in params:
                    del params[k]
        data_out: dict = {"activities": all_activities}
        if getattr(ig, "return_dataframe", False):
            try:
                data_out = ig.format_activities(data_out)
            except Exception:
                data_out = _pd.DataFrame(all_activities)
        return data_out
    except Exception as exc:
        logger.warning(
            "trades_api(spine): patched activity path raised (%s) — "
            "falling back to library default",
            exc,
        )
        return ig.fetch_account_activity(
            from_date=from_date,
            to_date=to_date,
            detailed=True,
            page_size=500,
        )


def _fetch_ig_open_positions(ig) -> list[dict]:
    """Currently-open positions across the shared account. Closed-trade
    history (transactions) doesn't include these, so a spine-only feed
    would silently drop the live book. We surface them with exit_type=OPEN
    and live pips/£ from the bid/offer mid."""
    rows: list[dict] = []
    try:
        df = ig.fetch_open_positions()
    except Exception as e:
        logger.warning("trades_api(spine): open_positions fetch failed: %s", e)
        return rows
    if df is None or len(df) == 0:
        return rows
    for _, r in df.iterrows():
        rows.append({
            "dealId":         str(r.get("dealId") or "").strip(),
            "size":           _to_float(r.get("size")),
            "direction":      str(r.get("direction") or "").strip().upper(),
            "level":          _to_float(r.get("level")),
            "stopLevel":      _to_float(r.get("stopLevel")),
            "limitLevel":     _to_float(r.get("limitLevel")),
            "instrumentName": str(r.get("instrumentName") or ""),
            "createdDateUTC": str(r.get("createdDateUTC") or ""),
            "bid":            _to_float(r.get("bid")),
            "offer":          _to_float(r.get("offer")),
            "currency":       str(r.get("currency") or ""),
        })
    return rows


def _build_open_position_rows(open_positions: list[dict],
                              signal_log_by_id: dict[str, dict]) -> list[dict]:
    """Project open IG positions into the /trades row shape with exit_type=OPEN.
    Pips/£ are live mid-price estimates so the dashboard can show a running
    PnL; they're not booked yet."""
    out: list[dict] = []
    for p in open_positions:
        deal_id = p["dealId"]
        direction = p["direction"] if p["direction"] in ("BUY", "SELL") else "UNKNOWN"
        entry = p["level"]
        bid, offer = p["bid"], p["offer"]
        mid = ((bid + offer) / 2.0) if (bid is not None and offer is not None) else None
        # Live pips against mid; £ is mid × size on a £1/pip spreadbet.
        if entry is not None and mid is not None and direction in ("BUY", "SELL"):
            live_pips = round((mid - entry) if direction == "BUY" else (entry - mid), 1)
        else:
            live_pips = None
        size_abs = abs(p["size"]) if p["size"] is not None else None
        if live_pips is not None and size_abs:
            # Spreadbet £/pt = stake size, so £ ≈ pips × size for the four
            # majors we trade (£/pt expressed in account currency).
            live_pnl_gbp = round(live_pips * size_abs, 2)
        else:
            live_pnl_gbp = None

        instrument = p["instrumentName"]
        pair = PAIR_MAP.get(instrument, instrument.replace("/", ""))
        open_time = _iso_z(p["createdDateUTC"])

        enr = signal_log_by_id.get(deal_id) or {}
        strategy = enr.get("strategy") or ""
        source = "bot" if enr else "ig_only"
        session = enr.get("session") or _session_from_timestamp(open_time)

        out.append({
            # core /trades schema:
            "timestamp":     open_time,  # bucket on open date until it closes
            "pair":          pair,
            "direction":     direction,
            "entry_price":   entry,
            "close_price":   None,
            "pips_pnl":      live_pips,
            "pnl_gbp":       live_pnl_gbp,
            "size":          int(size_abs) if (size_abs and abs(size_abs - round(size_abs)) < 1e-6) else size_abs,
            "strategy":      strategy,
            "close_reason":  "",
            "session":       session,
            # additive spine fields:
            "exit_type":         "OPEN",
            "position_id":       deal_id,
            "open_time":         open_time,
            "leg_count":         0,
            "linkage_missing":   False,
            "stop_level":        p["stopLevel"],
            "limit_level":       p["limitLevel"],
            "stop_moved_to_be":  False,
            "is_open":           True,
            "live_mid":          mid,
            # enrichment passthrough:
            "outcome":           enr.get("outcome") or "",
            "scaled_out":        bool(enr.get("scaled_out")),
            "partial_bank_pips": enr.get("partial_bank_pips"),
            "runner_pnl_pips":   enr.get("runner_pnl_pips"),
            "source":            source,
        })
    return out


def _index_activity_by_dealid(activity_df) -> tuple[dict, dict]:
    """Returns (by_dealid, by_affected). by_dealid keys on activity.dealId (a
    closing-leg dealId for CLOSED rows, the open dealId for OPENED rows).
    by_affected groups all action rows by their action.affectedDealId so we
    can find stop amendments / open events for a given parent position."""
    by_dealid: dict[str, dict] = {}
    by_affected: dict[str, list[dict]] = {}
    if activity_df is None or len(activity_df) == 0:
        return by_dealid, by_affected
    try:
        for _, r in activity_df.iterrows():
            rec = {
                "dealId":         str(r.get("dealId") or "").strip(),
                "actionType":     str(r.get("actionType") or "").strip().upper(),
                "affectedDealId": str(r.get("affectedDealId") or "").strip(),
                "direction":      str(r.get("direction") or "").strip().upper(),
                "level":          _to_float(r.get("level")),
                "stopLevel":      _to_float(r.get("stopLevel")),
                "limitLevel":     _to_float(r.get("limitLevel")),
                "date":           str(r.get("date") or ""),
                "marketName":     str(r.get("marketName") or ""),
                "channel":        str(r.get("channel") or ""),
            }
            if rec["dealId"]:
                # First write wins for a given dealId — typically one action
                # per dealId for CLOSED/OPENED events. Amendments share the
                # parent dealId and would otherwise stomp the close row, so
                # skip if we already have a non-amend record on this key.
                cur = by_dealid.get(rec["dealId"])
                if cur is None or cur["actionType"] == "STOP_LIMIT_AMENDED":
                    by_dealid[rec["dealId"]] = rec
            if rec["affectedDealId"]:
                by_affected.setdefault(rec["affectedDealId"], []).append(rec)
    except Exception as e:
        logger.warning("trades_api: activity index failed: %s", e)
    return by_dealid, by_affected


def _signal_log_by_deal_id(days: int) -> dict[str, dict]:
    """Return {deal_id → raw signal_log record}, keyed by the OPEN dealId that
    161 persisted at fire time."""
    if not SIGNAL_LOG_PATH.exists():
        return {}
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date()
    out: dict[str, dict] = {}
    try:
        with open(SIGNAL_LOG_PATH, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = _json.loads(ln)
                except Exception:
                    continue
                did = (o.get("deal_id") or "").strip()
                if not did:
                    continue
                ts_open = (o.get("timestamp_open") or "").strip()
                if len(ts_open) >= 10:
                    try:
                        if dt.date.fromisoformat(ts_open[:10]) < cutoff:
                            continue
                    except ValueError:
                        pass
                # Most-recent wins (signal_log is append-only, last write is
                # typically the post-close enrichment).
                out[did] = o
    except Exception as e:
        logger.warning("trades_api: signal_log index failed: %s", e)
    return out


def _classify_exit_type(
    close_reason_prefix: str,
    pnl_pips: float | None,
    pnl_gbp: float | None,
    close_level: float | None,
    stop_level: float | None,
    limit_level: float | None,
    stop_was_amended_toward_entry: bool,
    has_levels: bool,
) -> str:
    """Priority: signal_log close_reason → IG levels → UNKNOWN."""
    # (a) signal_log enrichment
    # 2026-07-28: `{MODE}_TIER_SL_{phase}` is the strategy-attributed form
    # emitted by trade_manager._monitor_briefing_tp for non-briefing tiers
    # (BB_BOUNCE, BB_REV_PAT, EMA_PULLBACK, CONFIRMATION_FALLBACK). Same
    # TP-or-SL ambiguity as BRIEFING_TP_SL — the tier machinery's SL check
    # fires at either edge — so we disambiguate on pnl sign identically.
    if (close_reason_prefix == "BRIEFING_TP_SL_OPEN"
            or close_reason_prefix.endswith("_TIER_SL_OPEN")):
        # Briefing-execution / tier-managed exit could be either side; tiebreak on pnl.
        sign_source = pnl_pips if pnl_pips is not None else pnl_gbp
        if sign_source is not None:
            return "TARGET" if sign_source > 0 else "STOP"
        return "UNKNOWN"
    mapped = _EXIT_TYPE_BY_CLOSE_REASON.get(close_reason_prefix)
    if mapped:
        return mapped
    # (b) IG-level heuristic
    if close_level is not None:
        if limit_level is not None and abs(close_level - limit_level) <= _LEVEL_NEAR_PTS:
            return "TARGET"
        if stop_level is not None and abs(close_level - stop_level) <= _LEVEL_NEAR_PTS:
            return "BREAKEVEN" if stop_was_amended_toward_entry else "STOP"
        if has_levels:
            return "EARLY"
    return "UNKNOWN"


def _aggregate_positions(
    transactions: list[dict],
    activity_by_dealid: dict[str, dict],
    activity_by_affected: dict[str, list[dict]],
    signal_log_by_id: dict[str, dict],
) -> list[dict]:
    """Group transaction legs by parent open dealId, derive position-level
    fields, and enrich from 161's signal_log."""
    # Bucket txns by parent dealId (affectedDealId). Linkage-missing legs
    # are kept as their own one-leg position so they don't vanish silently.
    by_parent: dict[str, list[dict]] = {}
    linkage_missing: dict[str, bool] = {}
    for txn in transactions:
        ref = txn["reference"]
        act = activity_by_dealid.get(ref) if ref else None
        parent = (act or {}).get("affectedDealId") or ref or ""
        if not parent:
            continue
        if act is None or not act.get("affectedDealId"):
            linkage_missing[parent] = True
        txn["_close_activity"] = act
        by_parent.setdefault(parent, []).append(txn)

    positions: list[dict] = []
    for parent_id, legs in by_parent.items():
        # Sort legs chronologically so first=open, last=final close.
        legs_sorted = sorted(legs, key=lambda t: t.get("dateUtc") or "")
        first_leg = legs_sorted[0]
        final_leg = legs_sorted[-1]

        # Net signed size across legs; direction from sign. IG transaction
        # history reports `size` signed by the OPENING direction (+ = BUY,
        # − = SELL), so a long position with a partial bank + runner has
        # both legs reporting positive size — verified against signal_log
        # for several DIAAAA... opens on 2026-06-02.
        signed_sizes = []
        for t in legs_sorted:
            _, sz = _parse_size_signed(t["size_str"])
            if sz is not None:
                signed_sizes.append(sz)
        net_size = sum(signed_sizes) if signed_sizes else None
        if signed_sizes:
            leg_sign_sum = sum(signed_sizes)
            direction = "BUY" if leg_sign_sum > 0 else ("SELL" if leg_sign_sum < 0 else "UNKNOWN")
        else:
            direction = "UNKNOWN"

        pnl_gbp = sum((t["profitAndLoss"] or 0.0) for t in legs_sorted) if any(t.get("profitAndLoss") is not None for t in legs_sorted) else None

        entry_price = first_leg["openLevel"]
        close_price = final_leg["closeLevel"]
        open_time = _iso_z(first_leg["openDateUtc"]) or _iso_z(first_leg["dateUtc"])
        timestamp = _iso_z(final_leg["dateUtc"])  # real close time, never midnight

        # Size-weighted pips PnL across legs: a multi-leg scale-out closes
        # at different prices, so the position-level pip number must weight
        # each leg's pips by that leg's size (not just compare first-entry
        # to final-close, which discards the partial bank).
        weighted_num = 0.0
        weight_den = 0.0
        for t in legs_sorted:
            ent = t["openLevel"]
            cls = t["closeLevel"]
            _, sz_signed = _parse_size_signed(t["size_str"])
            if ent is None or cls is None or sz_signed is None:
                continue
            if direction == "BUY":
                leg_pips = cls - ent
            elif direction == "SELL":
                leg_pips = ent - cls
            else:
                continue
            wt = abs(sz_signed)
            weighted_num += leg_pips * wt
            weight_den += wt
        if weight_den > 0:
            pips_pnl = round(weighted_num / weight_den, 1)
        elif entry_price is not None and close_price is not None and direction in ("BUY", "SELL"):
            pips_pnl = round((close_price - entry_price) if direction == "BUY" else (entry_price - close_price), 1)
        else:
            pips_pnl = None

        instrument = first_leg["instrumentName"]
        pair = PAIR_MAP.get(instrument, instrument.replace("/", ""))

        size_abs = None
        if net_size is not None:
            size_abs = abs(int(round(net_size))) if abs(net_size) >= 1 else abs(round(net_size, 2))

        # Activity metadata for exit_type heuristic.
        close_act = final_leg.get("_close_activity") or {}
        stop_level = close_act.get("stopLevel")
        limit_level = close_act.get("limitLevel")

        amendments = [
            a for a in activity_by_affected.get(parent_id, [])
            if a["actionType"] == "STOP_LIMIT_AMENDED"
        ]
        stop_was_amended_toward_entry = False
        if amendments and entry_price is not None:
            for a in amendments:
                sl = a.get("stopLevel")
                if sl is None:
                    continue
                if direction == "BUY" and sl >= entry_price - _LEVEL_NEAR_PTS:
                    stop_was_amended_toward_entry = True
                    break
                if direction == "SELL" and sl <= entry_price + _LEVEL_NEAR_PTS:
                    stop_was_amended_toward_entry = True
                    break

        # Enrichment from 161's signal_log (only matches 161-placed trades).
        enr = signal_log_by_id.get(parent_id) or {}
        strategy = enr.get("strategy") or ""
        close_reason = (enr.get("close_reason") or "").strip()
        outcome = enr.get("outcome") or ""
        scaled_out = bool(enr.get("scaled_out"))
        partial_bank_pips = enr.get("partial_bank_pips")
        runner_pnl_pips = enr.get("runner_pnl_pips")
        source = "bot" if enr else "ig_only"

        exit_type = _classify_exit_type(
            close_reason_prefix=_close_reason_prefix(close_reason),
            pnl_pips=pips_pnl,
            pnl_gbp=pnl_gbp,
            close_level=close_price,
            stop_level=stop_level,
            limit_level=limit_level,
            stop_was_amended_toward_entry=stop_was_amended_toward_entry,
            has_levels=(stop_level is not None or limit_level is not None),
        )

        session = enr.get("session") or _session_from_timestamp(open_time or timestamp)

        positions.append({
            # core /trades schema the dashboard reads:
            "timestamp":    timestamp or open_time,
            "pair":         pair,
            "direction":    direction,
            "entry_price":  entry_price,
            "close_price":  close_price,
            "pips_pnl":     pips_pnl,
            "pnl_gbp":      pnl_gbp,
            "size":         size_abs,
            "strategy":     strategy,
            "close_reason": close_reason,
            "session":      session,
            # additive spine fields:
            "exit_type":         exit_type,
            "position_id":       parent_id,
            "open_time":         open_time,
            "leg_count":         len(legs_sorted),
            "linkage_missing":   linkage_missing.get(parent_id, False),
            "stop_level":        stop_level,
            "limit_level":       limit_level,
            "stop_moved_to_be":  stop_was_amended_toward_entry,
            "is_open":           False,
            "live_mid":          None,
            # signal_log enrichment (None when IG-only):
            "outcome":           outcome,
            "scaled_out":        scaled_out,
            "partial_bank_pips": partial_bank_pips,
            "runner_pnl_pips":   runner_pnl_pips,
            "source":            source,
        })

    positions.sort(key=lambda p: p.get("timestamp") or "", reverse=True)
    return positions


def _explode_legs(
    transactions: list[dict],
    activity_by_dealid: dict[str, dict],
    signal_log_by_id: dict[str, dict],
) -> list[dict]:
    """Per-leg "raw" view: one row per IG close transaction, no blending.
    Mirrors IG's Closed-positions tab — pair, direction, time, open→close
    levels, £ P&L. pips/exit_type are not computed (raw rows show £ not
    pips, and the IG-style UI hides the exit pill).

    Consumes the SAME `transactions` list as _aggregate_positions, so a
    group's per-leg £ rows always sum to the grouped £ — both come from
    `profitAndLoss` per leg."""
    legs: list[dict] = []
    for t in transactions:
        act = activity_by_dealid.get(t["reference"]) or {}
        parent_id = act.get("affectedDealId") or t["reference"]
        enr = signal_log_by_id.get(parent_id) or {}
        direction, sz_signed = _parse_size_signed(t["size_str"])
        size_abs = None
        if sz_signed is not None:
            size_abs = abs(int(round(sz_signed))) if abs(sz_signed) >= 1 else abs(round(sz_signed, 2))
        ts_close = _iso_z(t["dateUtc"])
        legs.append({
            "timestamp":    ts_close,
            "pair":         PAIR_MAP.get(t["instrumentName"], t["instrumentName"].replace("/", "")),
            "direction":    direction,
            "entry_price":  t["openLevel"],
            "close_price":  t["closeLevel"],
            "pips_pnl":     None,
            "pnl_gbp":      t["profitAndLoss"],
            "size":         size_abs,
            "strategy":     enr.get("strategy") or "",
            "close_reason": (enr.get("close_reason") or ""),
            "session":      enr.get("session") or _session_from_timestamp(ts_close),
            "exit_type":    "UNKNOWN",
            "position_id":  parent_id,
            "deal_id":      t["reference"],
            "open_time":    _iso_z(t["openDateUtc"]),
            "leg_count":    1,
            "is_open":      False,
            "source":       "bot" if enr else "ig_only",
        })
    legs.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return legs


# Markers IG returns when the cached session has expired. Matched
# substring-wise against the str() of whatever exception the trading_ig
# library raised — covers IGException, requests.HTTPError, and the
# library-internal RuntimeError shapes we've observed in the wild.
_SESSION_EXPIRED_MARKERS = (
    "error.security.client-token-invalid",
    "client-token-invalid",
    "error.security.oauth-token-invalid",
    "oauth-token-invalid",
)


def _is_session_expired_error(exc: BaseException) -> bool:
    """True iff this exception's text looks like IG telling us our cached
    session/token is no longer valid. We match on the string rather than
    the type because trading_ig wraps the underlying 401 in several
    different exception classes depending on version + code path."""
    try:
        msg = str(exc) or ""
        msg_lower = msg.lower()
        return any(m in msg_lower for m in _SESSION_EXPIRED_MARKERS)
    except Exception:
        return False


def _get_ig_session_with_self_heal(refresh: bool = False):
    """Return the spine IG client (or None on permanent failure). When
    `refresh=True`, drop the cached session via ig_auth.refresh_session()
    and force a fresh login. INFO-logs every refresh so a service
    operator can see in the journal that the 06-08 cached-session 401
    cascade has self-healed."""
    try:
        from ig_auth import get_ig_session, refresh_session
        if refresh:
            logger.info("trades_api(spine): refreshing IG session after 401")
            session = refresh_session()
        else:
            session = get_ig_session()
        return session[0] if isinstance(session, (tuple, list)) else session
    except Exception as e:
        logger.warning("trades_api(spine): IG session unavailable: %s", e)
        return None


def _spine_call_with_self_heal(label: str, fn, *args, **kwargs):
    """Call `fn(*args, **kwargs)`. If it raises with a session-expired
    marker, re-auth once via refresh_session() and retry exactly once
    with the freshly cached ig client substituted into the first positional
    slot. Returns the result, or re-raises the second exception so the
    caller's existing try/except handles it normally.

    Callers always pass `ig` as the first positional arg; on retry we
    re-pull the cache (which refresh_session has just repopulated) so
    even if our local copy of `ig` was stale, the second attempt gets a
    live client.

    `label` is the diagnostic string used in INFO/WARN log lines so the
    operator can see WHICH spine call triggered the self-heal."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if not _is_session_expired_error(exc):
            raise
        logger.info(
            "trades_api(spine): %s saw session-expired (%s) — refreshing once",
            label, type(exc).__name__,
        )
        ig = _get_ig_session_with_self_heal(refresh=True)
        if ig is None:
            logger.warning(
                "trades_api(spine): %s refresh_session() failed; not retrying",
                label,
            )
            raise
        new_args = (ig,) + args[1:] if args else (ig,)
        result = fn(*new_args, **kwargs)
        logger.info("trades_api(spine): %s succeeded after session refresh", label)
        return result


def _load_trades_from_spine(days: int = HISTORY_DAYS, view: str = "grouped") -> list[dict]:
    """IG-spine + signal_log enrichment path. Returns [] on any error so the
    caller can fall back to _load_signal_log_fires.

    view="grouped" (default): one row per logical position (legs blended
    via _aggregate_positions). view="raw": one row per IG close deal
    (_explode_legs) — IG-Closed-tab style. Both views derive from the
    SAME single transactions fetch so they always reconcile.

    Each IG call is wrapped in _spine_call_with_self_heal so a stale
    cached session (the 401 cascade that ground this service to a halt
    on 2026-06-08) self-heals without an operator restart."""
    if _get_ig_session_with_self_heal(refresh=False) is None:
        return []

    to_date = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    from_date = to_date - dt.timedelta(days=days)

    # Re-pull ig from cache before EACH call. After self-heal refresh
    # the cache holds a fresh client; the previous local handle is
    # stale and would trigger a second self-heal next call.
    try:
        ig = _get_ig_session_with_self_heal(refresh=False)
        transactions = _spine_call_with_self_heal(
            "transactions", _fetch_ig_transactions, ig, from_date, to_date,
        )
    except Exception as e:
        logger.warning("trades_api(spine): transactions fetch failed: %s", e)
        return []

    try:
        ig = _get_ig_session_with_self_heal(refresh=False)
        activity_df = _spine_call_with_self_heal(
            "activity", _fetch_ig_activity_detailed, ig, from_date, to_date,
        )
    except Exception as e:
        logger.warning("trades_api(spine): activity fetch failed: %s", e)
        return []

    # Open positions: closed-trade history doesn't surface these, so a
    # spine-only feed without them would silently drop the live book.
    try:
        ig = _get_ig_session_with_self_heal(refresh=False)
        open_positions = _spine_call_with_self_heal(
            "open_positions", _fetch_ig_open_positions, ig,
        )
    except Exception as e:
        logger.warning("trades_api(spine): open_positions fetch failed: %s", e)
        open_positions = []

    try:
        by_dealid, by_affected = _index_activity_by_dealid(activity_df)
        sl_by_id = _signal_log_by_deal_id(days)
        # view=raw forces per-leg regardless of AGGREGATE_POSITIONS.
        # The env switch only gates grouped→per-leg legacy behaviour.
        use_grouped = (view == "grouped") and AGGREGATE_POSITIONS
        if use_grouped:
            closed_rows = _aggregate_positions(transactions, by_dealid, by_affected, sl_by_id)
        else:
            closed_rows = _explode_legs(transactions, by_dealid, sl_by_id)
        open_rows = _build_open_position_rows(open_positions, sl_by_id)
        combined = open_rows + closed_rows
        combined.sort(key=lambda p: p.get("timestamp") or "", reverse=True)
        return combined
    except Exception as e:
        logger.warning("trades_api(spine): aggregation failed: %s", e)
        return []


# ── CACHED ACCESSORS + ROUTES ────────────────────────────────────────────────

_summary_cache_lock = threading.Lock()
_summary_cache: dict = {"data": {}, "ts": 0}


# ── env-keyed session manager (Part 3) ──────────────────────────────────────
_VALID_ENVS = ("demo", "live")


def _normalize_env(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    return v if v in _VALID_ENVS else DEFAULT_DASHBOARD_ENV


def _env_creds(env: str) -> dict | None:
    """Read IG_<ENV>_* creds from the environment. Returns None if any
    required field is missing — caller surfaces "unconfigured" so the
    LIVE tab can render an explicit state rather than throwing."""
    prefix = f"IG_{env.upper()}_"
    creds = {
        "username":    os.getenv(prefix + "USERNAME"),
        "password":    os.getenv(prefix + "PASSWORD"),
        "api_key":     os.getenv(prefix + "API_KEY"),
        "account_id":  os.getenv(prefix + "ACCOUNT_ID"),
        # Optional override for the IG REST endpoint — defaults to the
        # standard demo-api / api hostnames inside trading_ig.
        "base_url":    os.getenv(prefix + "BASE_URL"),
    }
    if not creds["username"] or not creds["password"] or not creds["api_key"]:
        return None
    return creds


def _build_env_ig(env: str):
    """Create a fresh IGService for the requested env using IG_<ENV>_*
    creds. Returns None on missing creds or login failure. Never raises."""
    creds = _env_creds(env)
    if not creds:
        logger.info(
            "trades_api(env=%s): IG_%s_* creds not configured — tab will "
            "render 'unconfigured'",
            env, env.upper(),
        )
        return None
    try:
        from ig_auth import IGService  # re-export inside ig_auth
    except Exception:
        try:
            from trading_ig import IGService
        except Exception as exc:
            logger.warning(
                "trades_api(env=%s): trading_ig import failed: %s", env, exc,
            )
            return None
    try:
        ig = IGService(
            username=creds["username"],
            password=creds["password"],
            api_key=creds["api_key"],
            acc_type=env.upper(),
        )
        ig.create_session()
    except Exception as exc:
        logger.warning(
            "trades_api(env=%s): create_session failed: %s",
            env, exc,
        )
        return None
    return ig


def _get_env_session(env: str, refresh: bool = False):
    """Return an IG client for `env`, or None if unconfigured / login
    failed. With `refresh=True`, drop any cached client and re-build.

    Routing rules:
    1. If env matches the host's ig_auth.IG_ACC_TYPE (the live process
       session), reuse it — no second login.
    2. Otherwise read IG_<ENV>_* creds and build a separate IGService.

    `refresh=True` honours rule 2 — for rule 1 we delegate to
    ig_auth.refresh_session so the host's singleton is invalidated."""
    with _env_session_lock:
        if not refresh and _env_session_cache.get(env) is not None:
            return _env_session_cache[env]
        try:
            import ig_auth as _ia
        except Exception:
            _ia = None
        # Rule 1: reuse host singleton when env matches.
        host_env = (getattr(_ia, "IG_ACC_TYPE", "") or "").lower()
        if _ia is not None and host_env == env:
            try:
                if refresh:
                    session = _ia.refresh_session()
                else:
                    session = _ia.get_ig_session()
                ig = session[0] if isinstance(session, (tuple, list)) else session
                _env_session_cache[env] = ig
                return ig
            except Exception as exc:
                logger.warning(
                    "trades_api(env=%s): host singleton fetch failed: %s",
                    env, exc,
                )
                # fall through to env-creds path
        # Rule 2: separate IGService built from IG_<ENV>_* creds.
        ig = _build_env_ig(env)
        _env_session_cache[env] = ig
        return ig


def _env_spine_call_with_self_heal(env: str, label: str, fn, *args, **kwargs):
    """Same contract as _spine_call_with_self_heal but on the env-keyed
    session cache. Invalidates THIS env's client only — never touches
    the other env."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if not _is_session_expired_error(exc):
            raise
        logger.info(
            "trades_api(env=%s,spine): %s saw session-expired (%s) — "
            "refreshing once",
            env, label, type(exc).__name__,
        )
        ig = _get_env_session(env, refresh=True)
        if ig is None:
            logger.warning(
                "trades_api(env=%s,spine): %s refresh failed; not retrying",
                env, label,
            )
            raise
        new_args = (ig,) + args[1:] if args else (ig,)
        result = fn(*new_args, **kwargs)
        logger.info(
            "trades_api(env=%s,spine): %s succeeded after refresh", env, label,
        )
        return result


def _load_trades_from_spine_env(env: str, days: int = HISTORY_DAYS, view: str = "grouped") -> list[dict]:
    """Env-aware spine loader. Same shape as _load_trades_from_spine but
    keyed on the per-env session. view="grouped"|"raw" — see
    _load_trades_from_spine. Returns [] on any error."""
    ig = _get_env_session(env, refresh=False)
    if ig is None:
        return []
    to_date = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    from_date = to_date - dt.timedelta(days=days)
    try:
        ig = _get_env_session(env, refresh=False)
        transactions = _env_spine_call_with_self_heal(
            env, "transactions", _fetch_ig_transactions, ig, from_date, to_date,
        )
    except Exception as e:
        logger.warning("trades_api(env=%s,spine): transactions fetch failed: %s", env, e)
        return []
    try:
        ig = _get_env_session(env, refresh=False)
        activity_df = _env_spine_call_with_self_heal(
            env, "activity", _fetch_ig_activity_detailed, ig, from_date, to_date,
        )
    except Exception as e:
        logger.warning("trades_api(env=%s,spine): activity fetch failed: %s", env, e)
        return []
    try:
        ig = _get_env_session(env, refresh=False)
        open_positions = _env_spine_call_with_self_heal(
            env, "open_positions", _fetch_ig_open_positions, ig,
        )
    except Exception as e:
        logger.warning("trades_api(env=%s,spine): open_positions fetch failed: %s", env, e)
        open_positions = []
    try:
        by_dealid, by_affected = _index_activity_by_dealid(activity_df)
        sl_by_id = _signal_log_by_deal_id(days)
        use_grouped = (view == "grouped") and AGGREGATE_POSITIONS
        if use_grouped:
            closed_rows = _aggregate_positions(transactions, by_dealid, by_affected, sl_by_id)
        else:
            closed_rows = _explode_legs(transactions, by_dealid, sl_by_id)
        open_rows = _build_open_position_rows(open_positions, sl_by_id)
        combined = open_rows + closed_rows
        combined.sort(key=lambda p: p.get("timestamp") or "", reverse=True)
        return combined
    except Exception as e:
        logger.warning("trades_api(env=%s,spine): aggregation failed: %s", env, e)
        return []


def _filter_signal_log_rows_by_env(rows: list[dict], env: str) -> list[dict]:
    """signal_log rows pre-Part-3 have no env stamp. Treat unstamped as
    DEMO so historical data stays visible under the demo tab and never
    bleeds under the live tab."""
    out: list[dict] = []
    for r in rows:
        row_env = (r.get("env") or "demo").strip().lower()
        if row_env == env:
            out.append(r)
    return out


def _get_trades_with_source_env(env: str, view: str = "grouped") -> tuple[list[dict], str]:
    """Env-aware variant of _get_trades_with_source. Routes via the
    per-env session cache + signal_log fallback filtered to this env.
    Source values: "spine" | "signal_log_fallback" | "unconfigured".
    view="grouped"|"raw" — caches independently per (env, view) so a
    dashboard toggle doesn't invalidate the other view."""
    env = _normalize_env(env)
    now = time.time()
    with _env_cache_lock:
        env_bucket = _env_cache.setdefault(env, {})
        entry = env_bucket.setdefault(view, {"trades": [], "ts": 0, "source": ""})
        if (now - entry["ts"] < CACHE_TTL_S and entry["trades"]
                and entry.get("source")):
            return entry["trades"], entry["source"]

    trades: list[dict] = []
    source = ""

    # If creds aren't configured AND we can't reuse the host singleton
    # for this env, surface "unconfigured" explicitly. The session
    # manager itself returns None in that case.
    ig = _get_env_session(env, refresh=False)
    if ig is None:
        source = "unconfigured"
        logger.info(
            "trades_api(env=%s): no session — returning unconfigured", env,
        )
    elif USE_IG_SPINE:
        trades = _load_trades_from_spine_env(env, HISTORY_DAYS, view=view)
        if trades:
            source = "spine"
        else:
            logger.warning(
                "trades_api(env=%s): spine returned no trades — falling "
                "back to signal_log", env,
            )

    if source not in ("spine", "unconfigured"):
        raw = _load_signal_log_fires(HISTORY_DAYS)
        trades = _filter_signal_log_rows_by_env(raw, env)
        source = "signal_log_fallback"

    with _env_cache_lock:
        _env_cache.setdefault(env, {})[view] = {
            "trades": trades, "source": source, "ts": time.time(),
        }
    return trades, source


def _get_trades_with_source(view: str = "grouped") -> tuple[list[dict], str]:
    """Return cached bot trades AND a tag identifying which path produced
    them: "spine" or "signal_log_fallback".

    The source tag is what the dashboard uses to decide whether the
    OTHER-host filter can be honoured at all — signal_log only ever
    contains this host's fires, so a fallback dataset can't answer
    `who=other` correctly and the UI needs to know that.

    Default path (TRADES_USE_IG_SPINE=0): one row per signal_log fire,
    backward-compatible flat-list shape — the live dashboard reads this.

    Spine path (TRADES_USE_IG_SPINE=1): reconstruct from IG transaction +
    activity history (shared account, both boxes' trades) and enrich from
    161's signal_log by deal_id. Falls back to the default path on any
    failure so the dashboard never breaks.

    view="grouped"|"raw" — caches independently per view so the dashboard
    toggle doesn't invalidate the other view's TTL."""
    now = time.time()
    with _cache_lock:
        bucket = _cache.setdefault(view, {"trades": [], "ts": 0, "source": ""})
        if (now - bucket["ts"] < CACHE_TTL_S
                and bucket["trades"]
                and bucket.get("source")):
            return bucket["trades"], bucket["source"]

    trades: list[dict] = []
    source = "signal_log_fallback"
    if USE_IG_SPINE:
        trades = _load_trades_from_spine(HISTORY_DAYS, view=view)
        if trades:
            source = "spine"
        else:
            logger.warning(
                "trades_api: spine path returned no trades — "
                "falling back to signal_log"
            )
    if not trades:
        trades = _load_signal_log_fires(HISTORY_DAYS)
        source = "signal_log_fallback"

    with _cache_lock:
        _cache[view] = {"trades": trades, "source": source, "ts": time.time()}

    return trades, source


def _get_trades() -> list[dict]:
    """Back-compat shim: returns just the trades list. Used by any
    in-process callers that pre-date the source-tag plumbing."""
    trades, _ = _get_trades_with_source()
    return trades


# ── who-filter helpers ──────────────────────────────────────────────────────
_VALID_WHO = ("all", "mine", "other")


def _normalize_who(raw: str) -> str:
    """Map `?who=...` to a canonical value; unknown → 'all'."""
    v = (raw or "").strip().lower()
    return v if v in _VALID_WHO else "all"


def _apply_who_filter(trades: list[dict], who: str) -> list[dict]:
    """Filter the trades list per the `who` arg.

    mine  = trades whose source == "bot" (matched to THIS host's signal_log
            by dealId at the spine layer).
    other = trades whose source == "ig_only" (open on the shared IG account
            but NOT matched to this host's signal_log — usually a sibling
            droplet's fire or a manual click).
    all   = unfiltered.

    The OTHER filter is only meaningful when the spine produced the data;
    callers should refuse to set who=other if source != 'spine' (see route
    handler). This function applies the requested filter regardless — it
    is the caller's responsibility to gate based on source."""
    if who == "mine":
        return [t for t in trades if t.get("source") == "bot"]
    if who == "other":
        return [t for t in trades if t.get("source") == "ig_only"]
    return list(trades)


def _get_summary() -> dict:
    """Return cached reconciliation summary."""
    now = time.time()
    with _summary_cache_lock:
        if now - _summary_cache["ts"] < CACHE_TTL_S and _summary_cache["data"]:
            return _summary_cache["data"]

    data = _reconcile(HISTORY_DAYS)

    with _summary_cache_lock:
        _summary_cache["data"] = data
        _summary_cache["ts"] = time.time()

    return data


def _sanitize_json(obj):
    """Recursively convert non-finite floats (NaN / Inf / -Inf) to None.
    Flask's jsonify defaults to allow_nan=True, which emits literal
    `NaN`/`Infinity` — browsers reject those as invalid JSON and the
    dashboard then shows stale cached data. _to_float guards values at
    source; this is the belt-and-suspenders pass for anything that
    bypasses it (e.g. arithmetic on valid floats that yields inf)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/trades", methods=["GET"])
def trades():
    """Return the cached trades list.

    Backwards compatible: with NO query params, the response is the
    legacy flat list — byte-equivalent to the pre-2026-06-12 dashboard.

    Query params (any combination):
      who:  mine | other | all     (default all)
      env:  live | demo            (honoured only when
                                    DASHBOARD_ENV_TOGGLE_ENABLED=1;
                                    silently ignored otherwise)
      view: grouped | raw          (default grouped; raw = one row per
                                    IG close deal, IG-Closed-tab style)

    When a recognised param is present, the response is wrapped:
        {
          "trades": [...],
          "env":          "demo" | "live" | "" (when toggle off),
          "source":       "spine" | "signal_log_fallback" | "unconfigured",
          "who":          canonical value,
          "who_disabled": [...]   # filters the client should grey out,
          "toggle_enabled": bool,
          "view":         "grouped" | "raw"
        }

    who=other under a signal_log_fallback / unconfigured source returns
    an EMPTY list rather than the silently-wrong full list — the
    dashboard renders a fallback warning chip + disables the OTHER pill."""
    from flask import request
    raw_who = request.args.get("who")
    raw_env = request.args.get("env")
    raw_view = request.args.get("view")
    view = (raw_view or "").strip().lower()
    if view not in ("grouped", "raw"):
        view = "grouped"

    # Param-recognition decision tree:
    # - Toggle disabled: who is recognised; env is treated as if absent.
    # - Toggle enabled:  who and env are both recognised.
    env_param_recognised = bool(raw_env) and DASHBOARD_ENV_TOGGLE_ENABLED
    any_param = (raw_who is not None) or env_param_recognised or (raw_view is not None)

    # Resolve env + data source.
    if env_param_recognised:
        env_resolved = _normalize_env(raw_env)
        trades_list, source = _get_trades_with_source_env(env_resolved, view=view)
    else:
        env_resolved = "" if not DASHBOARD_ENV_TOGGLE_ENABLED else DEFAULT_DASHBOARD_ENV
        if DASHBOARD_ENV_TOGGLE_ENABLED and raw_who is not None and raw_env is None:
            trades_list, source = _get_trades_with_source_env(env_resolved, view=view)
        else:
            trades_list, source = _get_trades_with_source(view=view)

    # No recognised param → byte-equivalent legacy shape.
    if not any_param:
        return jsonify(_sanitize_json(trades_list))

    who = _normalize_who(raw_who)

    # OTHER is honourable only when the spine produced the data. Both
    # signal_log_fallback (this host's fires only) and unconfigured
    # (no data at all) must disable it.
    who_disabled: list[str] = []
    if source in ("signal_log_fallback", "unconfigured"):
        who_disabled.append("other")

    if who == "other" and source in ("signal_log_fallback", "unconfigured"):
        filtered: list[dict] = []
    else:
        filtered = _apply_who_filter(trades_list, who)

    return jsonify(_sanitize_json({
        "trades": filtered,
        "env":            env_resolved,
        "source":         source,
        "who":            who,
        "who_disabled":   who_disabled,
        "toggle_enabled": DASHBOARD_ENV_TOGGLE_ENABLED,
        "view":           view,
    }))


@app.route("/trades/summary", methods=["GET"])
def trades_summary():
    return jsonify(_get_summary())


# ── BRIEFINGS ENDPOINT ────────────────────────────────────────────────────────

BRIEFING_FIELDS = (
    "symbol", "session", "briefing_time", "daily_bias", "bias_confidence",
    "session_expectation", "bias_reasoning", "plan_summary", "key_levels",
)

_briefing_cache_lock = threading.Lock()
_briefing_cache: dict = {"data": [], "ts": 0}
BRIEFING_CACHE_TTL_S = 120


_DATE_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_briefings(date_str: str | None = None) -> list[dict]:
    """Read briefing JSON files for a given date (default: today)."""
    import json as _json
    from datetime import date

    day = date_str if (date_str and _DATE_RE.match(date_str)) else date.today().isoformat()
    results = []

    try:
        for path in sorted(LOG_DIR.glob(f"briefing_*_{day}_*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = _json.load(f)
                entry = {k: raw.get(k) for k in BRIEFING_FIELDS}
                entry["file"] = path.name
                results.append(entry)
            except Exception:
                continue
    except Exception:
        pass

    # Sort: most recent briefing_time first, then by symbol
    results.sort(key=lambda b: (b.get("briefing_time") or "", b.get("symbol") or ""), reverse=True)
    return results


def _get_briefings() -> list[dict]:
    now = time.time()
    with _briefing_cache_lock:
        if now - _briefing_cache["ts"] < BRIEFING_CACHE_TTL_S and _briefing_cache["data"]:
            return _briefing_cache["data"]

    data = _load_briefings()

    with _briefing_cache_lock:
        _briefing_cache["data"] = data
        _briefing_cache["ts"] = time.time()

    return data


@app.route("/briefings", methods=["GET"])
def briefings():
    from flask import request
    d = (request.args.get("date") or "").strip()
    if d:
        return jsonify(_load_briefings(d))
    return jsonify(_get_briefings())


# ── NEWS-STATE ENDPOINT ───────────────────────────────────────────────────────
# Returns the Finnhub economic-calendar snapshot — same dict that
# htf_authority.evaluate() attaches to each telemetry row. news_state owns
# its own once-per-day Finnhub fetch + disk cache; it does NOT depend on
# autobot in-process state, so this endpoint works whether the bot is up
# or down. Never raises — failure maps to news_state="UNKNOWN" with the
# reason in news_state_source.
@app.route("/news-state", methods=["GET"])
def news_state_endpoint():
    try:
        import news_state as _ns
        return jsonify(_ns.news_state_snapshot())
    except Exception as exc:
        return jsonify({
            "news_state": "UNKNOWN",
            "news_state_source": f"endpoint_error_{type(exc).__name__}",
            "error": str(exc),
        })


# ── PASSWORD / AUTH ───────────────────────────────────────────────────────────

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")


@app.route("/auth", methods=["POST"])
def auth():
    """Sign the browser in by setting a 30-day signed-cookie session.
    Body: {"password": "..."}. Empty DASHBOARD_PASSWORD means "no gate".
    """
    expected = os.getenv("DASHBOARD_PASSWORD")
    data = request.get_json(silent=True) or {}
    if not expected or data.get("password") == expected:
        session.permanent = True
        session["authed"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401


@app.route("/auth-check", methods=["GET", "POST"])
def auth_check():
    """Subrequest target for nginx auth_request — 200 if cookie validates,
    401 otherwise. Body is dropped by nginx; both verbs accepted as
    insurance against a future gated POST endpoint."""
    return ("", 200) if session.get("authed") else ("", 401)


@app.route("/logout", methods=["POST"])
def logout():
    """Clear the authed flag from the session cookie."""
    session.clear()
    return jsonify({"ok": True})


_VALID_SESSIONS = {"Asian", "London", "London_Open", "Mid-session", "NY", "NY_Data", "NY_Mid"}


@app.route("/admin/brief", methods=["POST"])
def admin_brief():
    """Manually trigger a briefing from inside the running autobot process.

    Query params:
      session: required, one of Asian/London/London_Open/Mid-session/NY/NY_Mid
      pair:    optional, single symbol (e.g. GBPUSD). Omitted => all active pairs.
      password: required if DASHBOARD_PASSWORD is set.
    """
    from flask import request
    pw = request.args.get("password", "") or (request.get_json(silent=True) or {}).get("password", "")
    if DASHBOARD_PASSWORD and pw != DASHBOARD_PASSWORD:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    session = request.args.get("session", "").strip()
    if session not in _VALID_SESSIONS:
        return jsonify({"ok": False, "error": f"session must be one of {sorted(_VALID_SESSIONS)}"}), 400

    pair = (request.args.get("pair") or "").strip().upper() or None

    import morning_briefing as mb
    today = mb._utc_now().strftime("%Y-%m-%d")
    lock_path = mb._session_lock_path(session, today)
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception as exc:
        logger.warning("[admin/brief] could not clear lock %s: %s", lock_path, exc)

    def _worker():
        try:
            if pair:
                logger.info("[admin/brief] manual trigger: %s/%s", pair, session)
                briefing = mb._refresh_symbol(pair, session)
                ok = bool(briefing and briefing.get("daily_bias"))
                logger.info("[admin/brief] %s/%s complete — ok=%s", pair, session, ok)
            else:
                logger.info("[admin/brief] manual trigger: all pairs / %s", session)
                mb._run_briefing(session)
        except Exception as exc:
            logger.exception("[admin/brief] worker failed: %s", exc)

    threading.Thread(target=_worker, name=f"admin-brief-{session}", daemon=True).start()
    return jsonify({"ok": True, "session": session, "pair": pair or "ALL", "status": "started"})


def start_trades_api(port: int = 8080) -> threading.Thread:
    """Launch the trades API in a daemon thread."""
    def _run():
        wlog = logging.getLogger("werkzeug")
        wlog.setLevel(logging.WARNING)
        app.run(host="0.0.0.0", port=port, threaded=True)

    t = threading.Thread(target=_run, name="trades-api", daemon=True)
    t.start()
    logger.info("📊 Trades API listening on port %d (IG source, %dd history, %ds cache)",
                port, HISTORY_DAYS, CACHE_TTL_S)
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Standalone entry point — used by deploy/trades-api.service.
#
# start_trades_api() spins a daemon thread and returns; that's right for the
# in-process autobot path but wrong for systemd, where the main thread would
# exit immediately and the daemon would die with it. So when run as a script
# we call app.run() in the foreground — systemd's SIGTERM stops it cleanly.
# Env knobs: TRADES_API_HOST (default 0.0.0.0), TRADES_API_PORT (default 8080).
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    _STANDALONE_HOST = os.getenv("TRADES_API_HOST", "0.0.0.0")
    _STANDALONE_PORT = int(os.getenv("TRADES_API_PORT", "8080"))
    logger.info(
        "📊 Trades API STANDALONE start: host=%s port=%d (IG source, %dd history, %ds cache)",
        _STANDALONE_HOST, _STANDALONE_PORT, HISTORY_DAYS, CACHE_TTL_S,
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host=_STANDALONE_HOST, port=_STANDALONE_PORT, threaded=True)
