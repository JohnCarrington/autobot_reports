#!/usr/bin/env python3
"""Capture one row per (date, session, pair) for v5_PIA vs verbose-briefing
comparison. Idempotent: dedup key is (date, session, pair).

Usage:
  capture                                                # auto: which session just ended (UTC)
  capture --backfill-date 2026-05-12 --session London    # one-shot for any past session
  capture --backfill-date 2026-05-12 --session London --pair GBPUSD  # narrow to one pair

Schema: see SCHEMA_VERSION constant + module-level field reference at the
top of this file. Output goes to /opt/tradingbot/logs/v5_pia_comparison.jsonl.

The v5 simulated outcome uses an SL-first convention when both SL and TP
land in the same 5M candle's range. v4 outcomes come from signal_log
(broker-confirmed close), not simulation. That asymmetry biases the
comparison against v5 — see analysis script header for the explicit
caveat that gets printed alongside any P&L comparison.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import logging
import os
import sys
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow imports from /opt/tradingbot
sys.path.insert(0, "/opt/tradingbot")

LOG = logging.getLogger("v5_comparison")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

OUT_PATH = Path("/opt/tradingbot/logs/v5_pia_comparison.jsonl")
V4_BRIEFING_DIR = Path("/opt/tradingbot/logs")           # briefing_{SYM}_{DATE}_{SESS}.json
V5_BRIEFING_DIR = Path("/opt/tradingbot/briefings/v5_pia")
SIGNAL_LOG = Path("/opt/tradingbot/logs/signal_log.jsonl")
CACHE_5M_DIR = Path("/opt/tradingbot/cache")             # {SYM}_candles.csv

PAIRS = ("GBPUSD", "EURUSD", "USDJPY", "USDCAD")
SESSIONS = ("London", "NY")
SCHEMA_VERSION = 1

# Per spec — session-end cutoffs for outcome attribution and 5M replay window.
SESSION_END_TIME_UTC: Dict[str, dt_time] = {
    "London": dt_time(12, 0),
    "NY":     dt_time(21, 0),
}

# v5 executor's entry tolerance — must match V5_EXECUTOR_ENTRY_TOL_PIPS in env.
V5_ENTRY_TOL_PIPS = float(os.getenv("V5_EXECUTOR_ENTRY_TOL_PIPS", "2.0"))

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ppp(pair: str) -> float:
    """Pips-per-point for IG quoted prices. Mirrors briefing.v5_pia.data_package.get_ppp."""
    return 0.01 if pair.upper().endswith("JPY") else 1.0

def _read_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        LOG.warning("read failed %s: %s: %s", path, type(e).__name__, e)
        return None

def _parse_iso_utc(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None

def _existing_keys(out_path: Path) -> set:
    keys = set()
    if not out_path.exists():
        return keys
    try:
        with open(out_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("dedup_key"):
                        keys.add(r["dedup_key"])
                except Exception:
                    continue
    except Exception as e:
        LOG.warning("could not read %s for dedup: %s", out_path, e)
    return keys

def _atomic_append(out_path: Path, row: Dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, default=str) + "\n"
    # POSIX advisory lock prevents concurrent timer fires from interleaving.
    with open(out_path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

# ─────────────────────────────────────────────────────────────────────────────
# v4 extraction
# ─────────────────────────────────────────────────────────────────────────────

def _v4_path(pair: str, date: str, session: str) -> Path:
    return V4_BRIEFING_DIR / f"briefing_{pair.upper()}_{date}_{session}.json"

def _v4_signal_filter(brief: Dict[str, Any]) -> str:
    sf = brief.get("signal_filter") or {}
    ab = bool(sf.get("allow_buys"))
    asells = bool(sf.get("allow_sells"))
    if ab and asells:    return "BOTH"
    if ab and not asells: return "BUYS_ONLY"
    if asells and not ab: return "SELLS_ONLY"
    return "NONE"

def _v4_primary(brief: Dict[str, Any]) -> Tuple[str, str, Optional[float]]:
    """Return (direction, text, entry_midpoint) from the rank-1 plan.

    entry_midpoint is the midpoint of the rank-1 plan's entry_zone if
    present, else None. Used for v4_v5_entry_delta_pips.
    """
    plans = brief.get("trading_plans") or []
    rank1 = next((p for p in plans if p.get("rank") == 1), None) or (plans[0] if plans else None)
    if not rank1:
        return ("NONE", brief.get("plan_summary") or "", None)
    bias = str(rank1.get("bias") or "").upper()
    direction = "BUY" if bias == "LONG" else ("SELL" if bias == "SHORT" else "NONE")
    text = brief.get("plan_summary") or rank1.get("label") or ""
    entry_mid: Optional[float] = None
    zone = rank1.get("entry_zone")
    if isinstance(zone, list) and len(zone) == 2:
        try:
            entry_mid = (float(zone[0]) + float(zone[1])) / 2.0
        except (TypeError, ValueError):
            entry_mid = None
    return (direction, text, entry_mid)

# ─────────────────────────────────────────────────────────────────────────────
# v5 extraction
# ─────────────────────────────────────────────────────────────────────────────

def _v5_path(pair: str, date: str, session: str) -> Path:
    return V5_BRIEFING_DIR / f"briefing_{pair.upper()}_{date}_{session}.json"

def _v5_context(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Pull pre_scoring_context from confidence_breakdown if the orchestrator
    populated it (post fold-in commit). Returns {} if absent."""
    bb = brief.get("confidence_breakdown") or {}
    ctx = bb.get("pre_scoring_context")
    return ctx if isinstance(ctx, dict) else {}

# ─────────────────────────────────────────────────────────────────────────────
# signal_log filtering
# ─────────────────────────────────────────────────────────────────────────────

def _signal_log_in_window(
    pair: str, strategy_eq: str, win_start: datetime, win_end: datetime,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not SIGNAL_LOG.exists():
        return rows
    with open(SIGNAL_LOG) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if str(r.get("pair") or "").upper() != pair.upper():
                continue
            if str(r.get("strategy") or "") != strategy_eq:
                continue
            ts = _parse_iso_utc(r.get("timestamp_open") or "")
            if ts is None:
                continue
            if win_start <= ts < win_end:
                rows.append(r)
    return rows

def _v4_fire_summary(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "deal_id":       r.get("deal_id"),
            "direction":     r.get("direction"),
            "entry":         r.get("entry"),
            "sl_pips":       r.get("sl_pips"),
            "tp_pips":       r.get("tp1_pips"),
            "opened_at_utc": r.get("timestamp_open"),
            "closed_at_utc": r.get("timestamp_close"),
            "outcome":       r.get("outcome"),
            "pnl_pips":      r.get("pnl_pips"),
        })
    return out

# ─────────────────────────────────────────────────────────────────────────────
# 5M replay & v5 simulation
# ─────────────────────────────────────────────────────────────────────────────

def _read_5m_window(pair: str, t0: datetime, t1: datetime) -> List[Dict[str, Any]]:
    """Read 5M bars in [t0, t1) from the rolling cache CSV."""
    path = CACHE_5M_DIR / f"{pair.upper()}_candles.csv"
    if not path.exists():
        LOG.warning("5M cache missing: %s", path)
        return []
    out: List[Dict[str, Any]] = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = _parse_iso_utc(row.get("timestamp", ""))
            if ts is None:
                continue
            if t0 <= ts < t1:
                try:
                    out.append({
                        "ts": ts,
                        "open":  float(row["open"]),
                        "high":  float(row["high"]),
                        "low":   float(row["low"]),
                        "close": float(row["close"]),
                    })
                except (KeyError, ValueError):
                    continue
    return out

def _simulate_v5(
    direction: str, entry: float, stop: float, target: float,
    pip_size: float, candles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Conservative simulation of what would have happened to a v5 trade.

    Algorithm:
      1. Find first 5M bar whose [low, high] is within ±tolerance of entry → trigger.
      2. From the bar AFTER trigger, scan forward checking SL/TP:
         * BUY:  TP if high >= target; SL if low <= stop.
         * SELL: TP if low <= target;  SL if high >= stop.
      3. If both SL and TP land in the same bar's range → assume SL hit
         first (CONSERVATIVE).  This biases the comparison AGAINST v5.
         The analysis script surfaces the asymmetry: v4 outcomes come
         from broker-confirmed close (signal_log), v5 outcomes come from
         this simulator. If v5 wins despite the handicap, the result is
         strong; if v5 loses, factor in the handicap.
      4. If neither hit by end of window → OPEN_AT_SESSION_END,
         pnl = (last_close - entry) signed by direction.
    """
    tol_price = V5_ENTRY_TOL_PIPS * pip_size
    triggered_at: Optional[datetime] = None
    trigger_idx: Optional[int] = None

    for i, c in enumerate(candles):
        if c["low"] - tol_price <= entry <= c["high"] + tol_price:
            triggered_at = c["ts"]
            trigger_idx = i
            break

    if trigger_idx is None:
        return {
            "v5_outcome": "NOT_TRIGGERED",
            "v5_simulated_pnl_pips": 0.0,
            "v5_simulated_entry_time_utc": None,
            "v5_simulated_exit_time_utc": None,
        }

    is_buy = direction.upper() == "BUY"
    sign = 1.0 if is_buy else -1.0

    for c in candles[trigger_idx + 1:]:
        hit_tp = (c["high"] >= target) if is_buy else (c["low"] <= target)
        hit_sl = (c["low"]  <= stop)   if is_buy else (c["high"] >= stop)
        if hit_tp and hit_sl:
            # SL-first convention (see docstring).
            return {
                "v5_outcome": "SL_HIT",
                "v5_simulated_pnl_pips": (stop - entry) / pip_size * sign,
                "v5_simulated_entry_time_utc": triggered_at.isoformat(),
                "v5_simulated_exit_time_utc": c["ts"].isoformat(),
            }
        if hit_tp:
            return {
                "v5_outcome": "TP_HIT",
                "v5_simulated_pnl_pips": (target - entry) / pip_size * sign,
                "v5_simulated_entry_time_utc": triggered_at.isoformat(),
                "v5_simulated_exit_time_utc": c["ts"].isoformat(),
            }
        if hit_sl:
            return {
                "v5_outcome": "SL_HIT",
                "v5_simulated_pnl_pips": (stop - entry) / pip_size * sign,
                "v5_simulated_entry_time_utc": triggered_at.isoformat(),
                "v5_simulated_exit_time_utc": c["ts"].isoformat(),
            }

    last_close = candles[-1]["close"]
    return {
        "v5_outcome": "OPEN_AT_SESSION_END",
        "v5_simulated_pnl_pips": (last_close - entry) / pip_size * sign,
        "v5_simulated_entry_time_utc": triggered_at.isoformat(),
        "v5_simulated_exit_time_utc": candles[-1]["ts"].isoformat(),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Agreement
# ─────────────────────────────────────────────────────────────────────────────

def _direction_agreement(v4_dir: str, v5_dir: str, v4_fired: bool) -> str:
    v5_abstain = v5_dir == "STAND_ASIDE"
    v4_no_trade = (v4_dir == "NONE") and (not v4_fired)
    if v5_abstain and v4_no_trade:           return "BOTH_ABSTAIN"
    if v5_abstain:                           return "V5_ABSTAIN"
    if v4_no_trade:                          return "V4_NO_TRADE"
    return "AGREE" if v4_dir == v5_dir else "DISAGREE"

def _d1_agreement(v4_d1_trend: str, v5_d1_bull: Optional[bool]) -> str:
    if v5_d1_bull is None:                    return "UNKNOWN"
    v4_bull = v4_d1_trend.upper() == "BULLISH"
    v4_bear = v4_d1_trend.upper() == "BEARISH"
    if not (v4_bull or v4_bear):              return "UNKNOWN"  # v4 NEUTRAL is incomparable
    return "AGREE" if (v4_bull == v5_d1_bull) else "DISAGREE"

# ─────────────────────────────────────────────────────────────────────────────
# Main per-pair-session
# ─────────────────────────────────────────────────────────────────────────────

def capture_one(date: str, session: str, pair: str, existing: set) -> Optional[Dict[str, Any]]:
    key = f"{date}|{session}|{pair}"
    if key in existing:
        LOG.info("skip (already captured): %s", key)
        return None

    v4 = _read_json_safe(_v4_path(pair, date, session))
    v5 = _read_json_safe(_v5_path(pair, date, session))

    if v4 is None and v5 is None:
        LOG.warning("no briefings found for %s — skipping row", key)
        return None
    if v4 is None:
        LOG.warning("v4 briefing absent for %s — writing row with v4 nulled", key)
    if v5 is None:
        LOG.warning("v5 briefing absent for %s — writing row with v5 nulled", key)

    # Publish time — prefer v4 (earlier), fall back to v5
    pub_iso = (v4 or {}).get("briefing_time") or (v5 or {}).get("generated_at_utc")
    pub_dt = _parse_iso_utc(pub_iso) if pub_iso else None
    end_dt = datetime.combine(
        datetime.strptime(date, "%Y-%m-%d").date(),
        SESSION_END_TIME_UTC[session],
        tzinfo=timezone.utc,
    )
    if pub_dt is None:
        LOG.warning("no publish_time for %s — skipping row", key)
        return None
    # Floor to minute so executor-dispatch trades that fired in the same
    # minute as briefing publish (just before the second) still attribute.
    win_start = pub_dt.replace(second=0, microsecond=0)

    # v4 derived
    if v4 is not None:
        v4_d1_trend = str(v4.get("daily_bias") or "NEUTRAL").upper()
        v4_session_bias = str(v4.get("session_bias") or "NEUTRAL").upper()
        v4_session_bias_conf = float(v4.get("bias_confidence") or 0.0)
        v4_signal_filter = _v4_signal_filter(v4)
        v4_primary_dir, v4_primary_text, v4_primary_entry = _v4_primary(v4)
    else:
        v4_d1_trend = v4_session_bias = v4_signal_filter = "NONE"
        v4_session_bias_conf = 0.0
        v4_primary_dir, v4_primary_text, v4_primary_entry = "NONE", "", None

    # v4 fires from signal_log
    v4_rows = _signal_log_in_window(pair, "BRIEFING_EXECUTION", win_start, end_dt)
    v4_fires = _v4_fire_summary(v4_rows)
    v4_pnl_total = sum((f.get("pnl_pips") or 0.0) for f in v4_fires) if v4_fires else None
    if not v4_fires:
        v4_outcome_agg = None
    elif len(v4_fires) == 1:
        v4_outcome_agg = v4_fires[0].get("outcome")
    else:
        v4_outcome_agg = "MULTIPLE"

    # v5 fields
    v5_ctx = _v5_context(v5 or {})
    if v5 is not None:
        v5_state = "TRADE" if v5.get("state") == "ARMED" and v5.get("entry") is not None else "STAND_ASIDE"
        v5_dir   = str(v5.get("direction") or "STAND_ASIDE").upper()
        v5_d1_bull = v5_ctx.get("d1_bull")
        v5_h4_bull = v5_ctx.get("h4_bull")
        v5_entry  = v5.get("entry")
        v5_stop   = v5.get("stop")
        v5_target = v5.get("target")
        v5_rr     = float(v5.get("rr") or 0.0)
        v5_conf   = int(v5.get("confidence") or 0)
        v5_sa_reason = v5.get("stand_aside_reason") if v5_state == "STAND_ASIDE" else None
    else:
        v5_state = "STAND_ASIDE"; v5_dir = "STAND_ASIDE"
        v5_d1_bull = v5_h4_bull = None
        v5_entry = v5_stop = v5_target = None
        v5_rr = 0.0; v5_conf = 0; v5_sa_reason = "v5_briefing_absent"

    # v5 actual fires + simulation
    v5_actual_rows = _signal_log_in_window(pair, "BRIEFING_V5", win_start, end_dt)
    v5_fired = len(v5_actual_rows) > 0

    candles = _read_5m_window(pair, win_start, end_dt)
    session_high = max((c["high"] for c in candles), default=None)
    session_low  = min((c["low"]  for c in candles), default=None)

    if v5_state == "TRADE" and all(x is not None for x in (v5_entry, v5_stop, v5_target)):
        sim = _simulate_v5(v5_dir, float(v5_entry), float(v5_stop), float(v5_target),
                           _ppp(pair), candles)
    else:
        sim = {
            "v5_outcome": ("STAND_ASIDE" if not v5_fired else (v5_actual_rows[0].get("outcome") or "FIRED")),
            "v5_simulated_pnl_pips": None,
            "v5_simulated_entry_time_utc": None,
            "v5_simulated_exit_time_utc": None,
        }

    # Entry delta — only meaningful when both systems have a directional plan.
    if v5_entry is not None and v4_primary_entry is not None:
        v4_v5_entry_delta_pips = (float(v5_entry) - float(v4_primary_entry)) / _ppp(pair)
    else:
        v4_v5_entry_delta_pips = None

    # Context — read from v5 enrichment if present
    d1_close = v5_ctx.get("d1_close")
    h4_close = v5_ctx.get("h4_close")
    h4_ema20 = v5_ctx.get("h4_ema20")

    row = {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "dedup_key": key,
        "date": date,
        "session": session,
        "pair": pair.upper(),
        "briefing_publish_time_utc": pub_iso,
        "session_end_utc": end_dt.isoformat(),

        "v4_briefing_present": v4 is not None,
        "v4_d1_trend": v4_d1_trend,
        "v4_session_bias": v4_session_bias,
        "v4_session_bias_confidence": v4_session_bias_conf,
        "v4_signal_filter": v4_signal_filter,
        "v4_primary_setup_direction": v4_primary_dir,
        "v4_primary_setup_text": v4_primary_text,
        "v4_primary_entry_midpoint": v4_primary_entry,
        "v4_fires": v4_fires,
        "v4_fired": bool(v4_fires),
        "v4_fired_count": len(v4_fires),
        "v4_pnl_pips_session_total": v4_pnl_total,
        "v4_outcome_aggregate": v4_outcome_agg,

        "v5_briefing_present": v5 is not None,
        "v5_state": v5_state,
        "v5_direction": v5_dir,
        "v5_stand_aside_reason": v5_sa_reason,
        "v5_d1_bull": v5_d1_bull,
        "v5_h4_bull": v5_h4_bull,
        "v5_entry": v5_entry,
        "v5_stop": v5_stop,
        "v5_target": v5_target,
        "v5_rr": v5_rr,
        "v5_confidence": v5_conf,
        "v5_fired": v5_fired,
        **sim,

        "direction_agreement": _direction_agreement(v4_primary_dir, v5_dir, bool(v4_fires)),
        "d1_call_agreement": _d1_agreement(v4_d1_trend, v5_d1_bull),
        "v4_v5_entry_delta_pips": v4_v5_entry_delta_pips,

        "d1_close_at_publish": d1_close,
        "h4_close_at_publish": h4_close,
        "h4_ema20_at_publish": h4_ema20,
        "session_high": session_high,
        "session_low": session_low,
    }
    return row

# ─────────────────────────────────────────────────────────────────────────────
# Auto-mode: which session just ended?
# ─────────────────────────────────────────────────────────────────────────────

def _auto_target() -> Tuple[str, str]:
    """Return (date, session) for the most recently ended session.

    Timer fires at 12:30 UTC (post-London) and 21:30 UTC (post-NY).
    """
    now = datetime.now(timezone.utc)
    if now.time() < dt_time(12, 30):
        # Before 12:30 UTC: most recent ended session is yesterday's NY.
        d = (now.date() - timedelta(days=1)).isoformat()
        return (d, "NY")
    if now.time() < dt_time(21, 30):
        return (now.date().isoformat(), "London")
    return (now.date().isoformat(), "NY")

# ─────────────────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backfill-date", help="YYYY-MM-DD (one-shot mode)")
    p.add_argument("--session", choices=SESSIONS, help="London or NY (one-shot mode)")
    p.add_argument("--pair", choices=PAIRS, help="restrict one-shot mode to a single pair")
    args = p.parse_args()

    if bool(args.backfill_date) ^ bool(args.session):
        p.error("--backfill-date and --session must be used together")

    if args.backfill_date:
        date, session = args.backfill_date, args.session
        LOG.info("one-shot capture: date=%s session=%s pair=%s", date, session, args.pair or "ALL")
    else:
        date, session = _auto_target()
        LOG.info("auto capture: date=%s session=%s", date, session)

    pairs = (args.pair,) if args.pair else PAIRS
    existing = _existing_keys(OUT_PATH)
    written = 0
    for pair in pairs:
        try:
            row = capture_one(date, session, pair, existing)
            if row is not None:
                _atomic_append(OUT_PATH, row)
                existing.add(row["dedup_key"])
                written += 1
                LOG.info("wrote %s", row["dedup_key"])
        except Exception as e:
            LOG.exception("capture failed for %s|%s|%s: %s", date, session, pair, e)
    LOG.info("done: wrote %d row(s) to %s", written, OUT_PATH)
    return 0

if __name__ == "__main__":
    sys.exit(main())
