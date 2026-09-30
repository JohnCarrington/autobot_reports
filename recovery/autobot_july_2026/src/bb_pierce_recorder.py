"""
bb_pierce_recorder.py — passive, always-on Bollinger-band pierce recorder
for GBPUSD 5M. Zero trading impact.

Every outer BB pierce (upper or lower, 24h, weekdays) is recorded as if
it were a trade — the wick-past-band condition using the SAME band
source, the SAME PIERCE_THRESH, and the SAME rejection contract the
live strategy uses. Nothing is filtered. Nothing is gated. This is a
data product, not a strategy.

Pierce definition (shared): reuses `_bb_20_2` and PIERCE_THRESH_PIPS
from gbpusd_bb_bounce. Wick past the band (bar low <= BBL - thresh, or
bar high >= BBU + thresh) — that condition is what the strategy calls
a "pierce" at gbpusd_bb_bounce.py:553-554. `open_inside_band` is
recorded as a flag; it is NOT a filter here (the strategy uses it as
its own arm-gate — recorder captures the population, not just the
arm-gate-compatible subset).

Rejection contract (shared): reuses REJECTION_WINDOW_BARS,
REJECTION_TOLERANCE_PIPS, MIN_REJECTION_BODY_PIPS from
gbpusd_bb_bounce, matched to the code at gbpusd_bb_bounce.py:1437-1446
— first qualifying bar within N=3 bars wins; otherwise
resolution_type="no_rejection" at pierce+3 bars.

Isolation contract: every entry point is wrapped in a blanket
try/except that logs and never re-raises. A recorder crash must never
touch the trading loop. Kill-switch: BB_PIERCE_RECORDER_ENABLED. Set
=0 to fully disable (skips registration and never runs).

Output: append-only jsonl at logs/bb_pierce_trades.jsonl. TWO records
per pierce:
  (a) PIERCE record on detection — at-fire context stamp using the
      SAME helpers signal_logger.log_open uses for real trades.
  (b) RESOLUTION record when the virtual trade resolves.
A header record documents the schema on first write.

Backfill: on first import, if the jsonl is empty (or header-only),
replays the CANDLE_ARCHIVE_DIR daily CSVs from BB_PIERCE_RECORDER_BACKFILL_START
(default 2026-05-04, matches the BB_BOUNCE strategy's live generation)
forward. Backfill rows are marked backfill=true.

No restart is required in the trading loop for this module — it
registers itself at import and lives in the same process.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import threading
from collections import deque
from datetime import datetime, date, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("bb_pierce_recorder")

# ── SHARED CODE — imported so the two paths cannot diverge ────────────
# All pierce/rejection/band parameters live in gbpusd_bb_bounce; we
# never redefine them here. The parity unit check confirms this.
try:
    from gbpusd_bb_bounce import (
        Bar as _BBBar,
        PIP_SIZE as _PIP_SIZE,
        BB_PERIOD as _BB_PERIOD,
        BB_STD as _BB_STD,
        PIERCE_THRESH_PIPS as _PIERCE_THRESH_PIPS,
        REJECTION_WINDOW_BARS as _REJ_WIN_BARS,
        REJECTION_TOLERANCE_PIPS as _REJ_TOL_PIPS,
        MIN_REJECTION_BODY_PIPS as _REJ_MIN_BODY_PIPS,
        _bb_20_2 as _shared_bb_20_2,
        _detect_pierce_setup as _shared_detect_pierce_setup,
    )
    _SHARED_OK = True
except Exception as _shared_exc:  # noqa: BLE001
    logger.error(
        "[bb_pierce_recorder] failed to import shared BB code from "
        "gbpusd_bb_bounce (%s) — recorder disabled",
        _shared_exc,
    )
    _SHARED_OK = False

# ── ENV-DRIVEN KNOBS (recorder-owned) ─────────────────────────────────
def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


ENABLED = _env_bool("BB_PIERCE_RECORDER_ENABLED", "1")
BACKFILL_ENABLED = _env_bool("BB_PIERCE_RECORDER_BACKFILL_ENABLED", "1")
BACKFILL_START_STR = os.getenv("BB_PIERCE_RECORDER_BACKFILL_START", "2026-05-04")
MFE_HORIZON_HOURS = _env_float("BB_PIERCE_RECORDER_HORIZON_HOURS", 4.0)
LOG_PATH = Path(
    os.getenv(
        "BB_PIERCE_RECORDER_LOG_PATH",
        "/opt/tradingbot/logs/bb_pierce_trades.jsonl",
    )
)
ARCHIVE_DIR = Path(
    os.getenv("CANDLE_ARCHIVE_DIR", "/opt/tradingbot/data/candles")
) / "GBPUSD"

SESSION_END_UTC_HOUR = _env_int("BB_PIERCE_RECORDER_SESSION_END_H", 21)

SCHEMA_VERSION = 1

# ── STATE ─────────────────────────────────────────────────────────────
# Open virtual trades — pierces awaiting rejection / resolution.
# Each entry is a dict; see _new_pierce_state.
_OPEN_LOCK = threading.Lock()
_OPEN: List[Dict[str, Any]] = []
_WRITE_LOCK = threading.Lock()
_STARTED = False


# ── UTILS ─────────────────────────────────────────────────────────────
def _to_utc(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _to_bst_iso(ts_utc: datetime) -> str:
    # BST = UTC+1 as a rough label; DST-aware conversion is out of scope
    # for a passive recorder. Analysts read UTC anyway; BST is convenience.
    try:
        return (ts_utc + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S BST")
    except Exception:
        return ""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    try:
        return float(obj)
    except Exception:
        return str(obj)


def _write_jsonl(record: Dict[str, Any]) -> None:
    """Append a single JSON line. Never raises."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, default=_json_default, separators=(",", ":"))
        with _WRITE_LOCK:
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bb_pierce_recorder] jsonl write failed: %s", exc)


def _write_header_if_missing() -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 0:
            return
        header = {
            "record_type": "HEADER",
            "schema_version": SCHEMA_VERSION,
            "written_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "instrument": "GBPUSD",
            "timeframe": "5m",
            "band_params": {
                "bb_period": _BB_PERIOD if _SHARED_OK else None,
                "bb_std": _BB_STD if _SHARED_OK else None,
                "stdev_flavour": "population",
                "series": "5m_close",
                "pip_size": _PIP_SIZE if _SHARED_OK else None,
            },
            "pierce_thresh_pips": _PIERCE_THRESH_PIPS if _SHARED_OK else None,
            "rejection_contract": {
                "window_bars": _REJ_WIN_BARS if _SHARED_OK else None,
                "tolerance_pips": _REJ_TOL_PIPS if _SHARED_OK else None,
                "min_body_pips": _REJ_MIN_BODY_PIPS if _SHARED_OK else None,
                "reference_bb": "current_bar_bb",
                "shared_with_strategy": True,
                "source_module": "gbpusd_bb_bounce",
            },
            "horizon": {
                "mfe_hours_from_entry": MFE_HORIZON_HOURS,
                "session_end_utc_hour": SESSION_END_UTC_HOUR,
                "also_bounded_by": "session_end_or_horizon_whichever_first",
            },
            "fetch_note": (
                "jsonl at " + str(LOG_PATH) + " — CSV export via "
                "scripts/bb_pierce_export.py"
            ),
        }
        _write_jsonl(header)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bb_pierce_recorder] header write failed: %s", exc)


# ── PIERCE DETECTION (uses SHARED code) ───────────────────────────────
def _detect_pierce_on_bar(bar_ohlc: Dict[str, float],
                          bb_lower: float, bb_upper: float,
                          ) -> Tuple[Optional[str], float, bool]:
    """Return (side, distance_beyond_band_pips, open_inside_band).

    Uses SHARED PIERCE_THRESH_PIPS so this cannot diverge from strategy.
    side in {"LOWER","UPPER",None}. Both-band overlap → None (matches
    strategy's "both_bands" reject at gbpusd_bb_bounce.py:557).
    """
    if not _SHARED_OK:
        return None, 0.0, False
    lo = float(bar_ohlc["low"])
    hi = float(bar_ohlc["high"])
    op = float(bar_ohlc["open"])
    thresh_price = float(_PIERCE_THRESH_PIPS) * float(_PIP_SIZE)
    long_pierce = (bb_lower - lo) >= thresh_price
    short_pierce = (hi - bb_upper) >= thresh_price
    if long_pierce and short_pierce:
        return None, 0.0, False
    if long_pierce:
        dist = (bb_lower - lo) / float(_PIP_SIZE)
        return "LOWER", round(dist, 3), (op >= bb_lower)
    if short_pierce:
        dist = (hi - bb_upper) / float(_PIP_SIZE)
        return "UPPER", round(dist, 3), (op <= bb_upper)
    return None, 0.0, False


def _is_rejection_bar(side: str, bar_ohlc: Dict[str, float],
                      bb_lower_now: float, bb_upper_now: float,
                      ) -> bool:
    """Verbatim of the strategy's `_is_rejection` inner fn at
    gbpusd_bb_bounce.py:1437-1446, adapted to OHLC dict."""
    if not _SHARED_OK:
        return False
    body = abs(float(bar_ohlc["close"]) - float(bar_ohlc["open"]))
    if body < float(_REJ_MIN_BODY_PIPS) * float(_PIP_SIZE):
        return False
    tol = float(_REJ_TOL_PIPS) * float(_PIP_SIZE)
    if side == "LOWER":  # fade LONG (BUY): bullish rejection back inside
        return (
            float(bar_ohlc["close"]) > float(bar_ohlc["open"])
            and float(bar_ohlc["close"]) >= bb_lower_now - tol
        )
    # UPPER — fade SHORT (SELL): bearish rejection back inside
    return (
        float(bar_ohlc["close"]) < float(bar_ohlc["open"])
        and float(bar_ohlc["close"]) <= bb_upper_now + tol
    )


# ── AT-FIRE ENRICHMENT (reuses signal_logger helpers) ─────────────────
def _enrich_at_pierce(df_5m: Any, ts_utc: datetime,
                      side: str, virtual_direction: str,
                      entry_price_at_pierce_close: float,
                      is_backfill: bool,
                      ) -> Dict[str, Any]:
    """Full at-pierce context stamp, mirroring signal_logger.log_open.

    Every field is captured on best-effort — a null on any single sub-
    read never blocks the record. is_backfill=True skips the live-only
    reads (engine cache, briefing, FXi, EPIC_STATE profile) since those
    caches don't hold historic state.
    """
    out: Dict[str, Any] = {}
    pip_size = float(_PIP_SIZE) if _SHARED_OK else 1.0

    # ── grid distances (arithmetic; works for backfill too) ─────────
    try:
        _ep = float(entry_price_at_pierce_close)
        _mod100 = _ep % 100.0
        _mod050 = _ep % 50.0
        out["dist_to_00_pips"] = round(min(_mod100, 100.0 - _mod100), 2)
        out["dist_to_0050_pips"] = round(min(_mod050, 50.0 - _mod050), 2)
    except Exception:
        out["dist_to_00_pips"] = None
        out["dist_to_0050_pips"] = None

    # ── df_5m-driven reads (work for backfill IF the df is enriched) ─
    has_df = df_5m is not None and hasattr(df_5m, "empty") and not df_5m.empty
    if has_df:
        try:
            import signal_logger as _sl
            out["ema_aligned"] = _sl._ema_aligned(df_5m, virtual_direction)
            out["macd_direction"] = _sl._macd_direction(df_5m)
            out["atr_pips"] = _sl._atr_pips(df_5m, pip_size)
            out["bb_width_pips"] = _sl._bb_width_pips(df_5m, pip_size)
            out["price_vs_daily_open"] = _sl._price_vs_daily_open(
                df_5m, entry_price_at_pierce_close, pip_size, ts_utc,
            )
            out["vwap_distance_pips"] = _sl._vwap_distance_pips(
                df_5m, entry_price_at_pierce_close, pip_size, ts_utc,
            )
            out["entry_candle_pattern"] = _sl._entry_candle_pattern(df_5m)
            out["entry_candle_body_pct"] = _sl._entry_candle_body_pct(df_5m)
            out["entry_candle_wick_ratio"] = _sl._entry_candle_wick_ratio(df_5m)
            out["atr_vs_20day_avg"] = _sl._atr_vs_20day_avg(df_5m, pip_size)
            out["bb_squeeze"] = _sl._bb_squeeze(df_5m)
            out["minutes_since_london_open"] = _sl._minutes_since_london_open(ts_utc)
            out["session"] = _sl._session_from_utc_hour(ts_utc.hour)
            # Day-type stamps (session_action, adx, er, bbw slope, day-range,
            # day-net, news tier). Live-only for accuracy; backfill uses same
            # helpers but they only need the df_5m + calendar cache.
            out["session_name"] = _sl._day_session_name(ts_utc)
            try:
                sess_df = _sl._session_frame(df_5m, ts_utc)
                if sess_df is not None and not sess_df.empty:
                    if "ADX_14" in sess_df.columns:
                        out["session_adx"] = _sl._last_num(sess_df["ADX_14"])
                    if "close" in sess_df.columns:
                        out["session_er"] = _sl._kaufman_er_from_closes(
                            sess_df["close"], 10,
                        )
                    _bbw_col = next(
                        (c for c in sess_df.columns if c.startswith("BB_WIDTH_20")),
                        None,
                    )
                    if _bbw_col is not None:
                        _v = _sl._last_num(sess_df[_bbw_col])
                        out["session_bbw_pips"] = round(_v / pip_size, 2) \
                            if _v is not None else None
                    _bbw_slope = _sl._bbw_pips_slope_from_column(
                        sess_df, pip_size, 6,
                    )
                    out["session_action_so_far"] = _sl._classify_market_action(
                        out.get("session_adx"),
                        out.get("session_er"),
                        _bbw_slope,
                    )
            except Exception:
                pass
            try:
                today_df = _sl._today_candles(df_5m, ts_utc)
                if not today_df.empty:
                    import pandas as _pd
                    _day_open = float(today_df.iloc[0]["open"])
                    _day_high = float(_pd.to_numeric(
                        today_df["high"], errors="coerce"
                    ).max())
                    _day_low = float(_pd.to_numeric(
                        today_df["low"], errors="coerce"
                    ).min())
                    _day_close = float(today_df.iloc[-1]["close"])
                    out["day_range_so_far_pips"] = round(
                        (_day_high - _day_low) / pip_size, 2,
                    )
                    out["day_net_so_far_pips"] = round(
                        (_day_close - _day_open) / pip_size, 2,
                    )
            except Exception:
                pass
            try:
                if "EMA_21" in df_5m.columns:
                    _v = df_5m["EMA_21"].iloc[-1]
                    import pandas as _pd
                    if _pd.notna(_v):
                        out["ema21_at_fire"] = float(_v)
                if "ATR_14" in df_5m.columns:
                    _v = df_5m["ATR_14"].iloc[-1]
                    import pandas as _pd
                    if _pd.notna(_v):
                        out["atr_at_fire"] = float(_v)
                if (
                    out.get("ema21_at_fire") is not None
                    and out.get("atr_at_fire") is not None
                    and out["atr_at_fire"] > 0
                ):
                    out["stretch_atr_at_fire"] = round(
                        abs(entry_price_at_pierce_close - out["ema21_at_fire"])
                        / out["atr_at_fire"],
                        3,
                    )
            except Exception:
                pass
        except Exception as _sl_exc:  # noqa: BLE001
            logger.debug("[bb_pierce_recorder] signal_logger enrich fail: %s", _sl_exc)

    # ── Live-only reads (engine cache, briefing, FXi, EPIC_STATE) ────
    if not is_backfill:
        # 5M MACD histogram + 3-bar trend — small compute over closes
        try:
            if has_df and "close" in df_5m.columns:
                try:
                    from gbpusd_bb_bounce import _compute_5m_macd_hist_now as _mnow
                    _closes = [float(c) for c in df_5m["close"].tolist()]
                    _hist = _mnow(_closes)
                    if _hist is not None:
                        out["macd_hist_5m_at_fire"] = float(_hist)
                except Exception:
                    pass
                try:
                    import indicators as _ind
                    import pandas as _pd
                    _s = _pd.Series([float(c) for c in df_5m["close"].tolist()])
                    _m = _ind.macd(_s, 12, 26, 9)
                    _hist_col = _m.iloc[:, 2]
                    if len(_hist_col) >= 3:
                        out["macd_hist_5m_3bar_trend"] = round(
                            float(_hist_col.iloc[-1] - _hist_col.iloc[-3]), 5,
                        )
                except Exception:
                    pass
        except Exception:
            pass

        # regime_engine cache — H1 label & confidence
        try:
            import regime_engine as _re
            _eng = _re.latest_result("GBPUSD") or {}
            if isinstance(_eng, dict):
                out["engine_regime_at_fire"] = _eng.get("winning_regime")
                out["engine_regime_confidence_at_fire"] = _eng.get("confidence_final")
                out["engine_regime_bias_at_fire"] = _eng.get("directional_bias")
                out["engine_regime_bar_ts"] = _eng.get("timestamp")
                out["regime_label_path"] = _eng.get("regime_label_path")
                out["regime_instance_id"] = _eng.get("regime_instance_id")
        except Exception:
            pass

        # H1 EMA-stack (h1_ema_direction) + H1 histogram context
        try:
            import indicators as _ind
            _h1 = _ind.h1_ema_direction("GBPUSD", pip_size=pip_size)
            if isinstance(_h1, dict):
                out["h1_stack_direction"] = _h1.get("direction")
                # h1_ema_direction returns "separation_strength" (indicators.py:1630),
                # not "strength" — the misspelled key made every recorded value null.
                out["h1_stack_strength"] = _h1.get("separation_strength")
                out["h1_hist_now"] = _h1.get("h1_hist")
        except Exception:
            pass

        # FXi plan (fxi_briefing_reader) — verbatim + agreement
        try:
            import fxi_briefing_reader as _fxi
            _plan = _fxi.get_today_plan("GBPUSD")
            if isinstance(_plan, dict):
                _plan_dir = str(_plan.get("direction") or "").upper()
                out["fxi_direction"] = _plan_dir or None
                out["fxi_confidence"] = _plan.get("confidence")
                out["fxi_state"] = _plan.get("state")
                out["fxi_levels_source"] = _plan.get("levels_source")
                _pv = _plan.get("plan_entry")
                out["fxi_plan_entry"] = float(_pv) if isinstance(_pv, (int, float)) else None
                _pv = _plan.get("plan_stop")
                out["fxi_plan_stop"] = float(_pv) if isinstance(_pv, (int, float)) else None
                _pv = _plan.get("plan_target")
                out["fxi_plan_target"] = float(_pv) if isinstance(_pv, (int, float)) else None
                _pv = _plan.get("plan_rr")
                out["fxi_plan_rr"] = float(_pv) if isinstance(_pv, (int, float)) else None
                if virtual_direction in ("BUY", "SELL") and _plan_dir in ("BUY", "SELL"):
                    out["fxi_direction_agree"] = (virtual_direction == _plan_dir)
        except Exception:
            pass

        # day news tier
        try:
            import signal_logger as _sl
            out["day_news_tier"] = _sl._day_news_tier_for(ts_utc)
        except Exception:
            pass

    return out


# ── PIERCE-STATE HELPERS ──────────────────────────────────────────────
def _new_pierce_state(pierce_ts: datetime,
                      side: str,
                      virtual_direction: str,
                      bar_ohlc: Dict[str, float],
                      bb: Dict[str, float],
                      distance_beyond_band_pips: float,
                      open_inside_band: bool,
                      strategy_would_arm: bool,
                      at_pierce_context: Dict[str, Any],
                      is_backfill: bool,
                      ) -> Dict[str, Any]:
    return {
        "pierce_ts_utc": pierce_ts,
        "side": side,
        "virtual_direction": virtual_direction,
        "bar_open": float(bar_ohlc["open"]),
        "bar_high": float(bar_ohlc["high"]),
        "bar_low": float(bar_ohlc["low"]),
        "bar_close": float(bar_ohlc["close"]),
        "bb_upper": float(bb["upper"]),
        "bb_mid": float(bb["mid"]),
        "bb_lower": float(bb["lower"]),
        "bb_width_pips": round(
            (float(bb["upper"]) - float(bb["lower"])) / float(_PIP_SIZE), 3,
        ),
        "distance_beyond_band_pips": distance_beyond_band_pips,
        "open_inside_band": bool(open_inside_band),
        "strategy_would_arm": bool(strategy_would_arm),
        "at_pierce_context": at_pierce_context,
        "is_backfill": bool(is_backfill),

        # Resolution state — mutated by _update_open_trades
        "entry_price": None,
        "entry_ts_utc": None,
        "resolution_type": None,   # "rejection", "no_rejection"
        "bars_since_pierce": 0,
        "mfe_pips": 0.0,
        "mae_pips": 0.0,
        "t_to_10p_mins": None,
        "t_to_20p_mins": None,
        "t_to_30p_mins": None,
        "t_to_40p_mins": None,
        "t_to_60p_mins": None,
        "sl_20p_hit_at_ts": None,
        "resolved": False,
    }


def _emit_pierce_record(st: Dict[str, Any]) -> None:
    record: Dict[str, Any] = {
        "record_type": "PIERCE",
        "schema_version": SCHEMA_VERSION,
        "backfill": st["is_backfill"],
        "pierce_ts_utc": st["pierce_ts_utc"],
        "pierce_ts_bst": _to_bst_iso(st["pierce_ts_utc"]),
        "instrument": "GBPUSD",
        "side": st["side"],
        "virtual_direction": st["virtual_direction"],
        "bar_open": st["bar_open"],
        "bar_high": st["bar_high"],
        "bar_low": st["bar_low"],
        "bar_close": st["bar_close"],
        "bb_upper": st["bb_upper"],
        "bb_mid": st["bb_mid"],
        "bb_lower": st["bb_lower"],
        "bb_width_pips": st["bb_width_pips"],
        "distance_beyond_band_pips": st["distance_beyond_band_pips"],
        "open_inside_band": st["open_inside_band"],
        "strategy_would_arm": st["strategy_would_arm"],
    }
    # merge enrichment context flat into the record
    for k, v in st["at_pierce_context"].items():
        record[k] = v
    _write_jsonl(record)


def _live_bot_status_for_pierce(pierce_ts: datetime) -> Dict[str, Any]:
    """Best-effort read of what the LIVE bot did against this pierce.

    Looks in signal_log.jsonl for any BB_BOUNCE row whose timestamp_open
    is within [pierce_ts, pierce_ts + REJECTION_WINDOW_BARS*5m + 60s]
    (mirrors _build_bb_pierce_ledger.py). Returns {} if none / lookup
    fails. Never raises.
    """
    result: Dict[str, Any] = {
        "live_bot_armed": None,
        "live_bot_fired": None,
        "live_bot_deal_id": None,
    }
    try:
        sl_path = Path(
            os.getenv("SIGNAL_LOG_PATH", "/opt/tradingbot/logs/signal_log.jsonl")
        )
        if not sl_path.exists():
            return result
        lo = pierce_ts
        hi = pierce_ts + timedelta(seconds=int(_REJ_WIN_BARS) * 300 + 60)
        fired = False
        deal_id = None
        with sl_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not isinstance(r, dict):
                    continue
                strat = str(r.get("strategy") or "")
                if not strat.startswith("GBPUSD_BB_BOUNCE"):
                    continue
                ts_s = r.get("timestamp_open")
                if not ts_s:
                    continue
                try:
                    ts_dt = datetime.strptime(
                        str(ts_s), "%Y-%m-%dT%H:%M:%SZ",
                    ).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if lo <= ts_dt <= hi:
                    fired = True
                    deal_id = r.get("deal_id")
                    break
        result["live_bot_fired"] = fired
        result["live_bot_deal_id"] = deal_id
    except Exception:
        pass
    return result


def _finalize_resolution(st: Dict[str, Any]) -> None:
    """Write the RESOLUTION record for a virtual trade."""
    mfe = float(st["mfe_pips"])
    mae = float(st["mae_pips"])

    # Reference exits — pure arithmetic.
    # For each (tp, sl) pair: if favorable-hit-time comes before adverse
    # 20p breach, pnl = +tp. Vice-versa pnl = -sl. Neither hit: pnl at
    # horizon = mfe if mfe >= mae else -mae (i.e., realistic best-case
    # trailing view). No exit is endorsed — this is arithmetic only.
    def _pnl(tp_p: float, sl_p: float) -> Optional[float]:
        try:
            t_tp = None
            if tp_p <= 10.0:
                t_tp = st.get("t_to_10p_mins")
            elif tp_p <= 20.0:
                t_tp = st.get("t_to_20p_mins")
            elif tp_p <= 30.0:
                t_tp = st.get("t_to_30p_mins")
            elif tp_p <= 40.0:
                t_tp = st.get("t_to_40p_mins")
            elif tp_p <= 60.0:
                t_tp = st.get("t_to_60p_mins")
            t_sl = st.get("sl_20p_hit_at_ts")

            tp_hit = t_tp is not None and (mfe >= tp_p)
            sl_hit = t_sl is not None and (mae >= sl_p)

            if tp_hit and not sl_hit:
                return float(tp_p)
            if sl_hit and not tp_hit:
                return -float(sl_p)
            if tp_hit and sl_hit:
                # Whichever came first (t_tp is minutes-from-entry;
                # t_sl is an ISO string — convert to minutes-from-entry).
                try:
                    entry_ts = st.get("entry_ts_utc")
                    if isinstance(entry_ts, str):
                        entry_dt = datetime.strptime(
                            entry_ts, "%Y-%m-%dT%H:%M:%SZ",
                        ).replace(tzinfo=timezone.utc)
                    else:
                        entry_dt = entry_ts
                    sl_dt = datetime.strptime(
                        str(t_sl), "%Y-%m-%dT%H:%M:%SZ",
                    ).replace(tzinfo=timezone.utc)
                    sl_mins = (sl_dt - entry_dt).total_seconds() / 60.0
                    if float(t_tp) <= sl_mins:
                        return float(tp_p)
                    return -float(sl_p)
                except Exception:
                    return None
            # neither hit: leave at final mfe/mae realised
            if mfe >= mae:
                return round(mfe, 2)
            return round(-mae, 2)
        except Exception:
            return None

    live_status = _live_bot_status_for_pierce(st["pierce_ts_utc"])

    record: Dict[str, Any] = {
        "record_type": "RESOLUTION",
        "schema_version": SCHEMA_VERSION,
        "backfill": st["is_backfill"],
        "pierce_ts_utc": st["pierce_ts_utc"],
        "instrument": "GBPUSD",
        "side": st["side"],
        "virtual_direction": st["virtual_direction"],
        "resolution_type": st["resolution_type"],
        "entry_price": st.get("entry_price"),
        "entry_ts_utc": st.get("entry_ts_utc"),
        "bars_after_pierce_to_entry": (
            round(
                (
                    (st["entry_ts_utc"] - st["pierce_ts_utc"]).total_seconds()
                    if isinstance(st.get("entry_ts_utc"), datetime)
                    else 0
                ) / 300.0,
                2,
            ) if st.get("entry_ts_utc") else None
        ),
        "mfe_pips": round(mfe, 2),
        "mae_pips": round(mae, 2),
        "t_to_10p_mins": st.get("t_to_10p_mins"),
        "t_to_20p_mins": st.get("t_to_20p_mins"),
        "t_to_30p_mins": st.get("t_to_30p_mins"),
        "t_to_40p_mins": st.get("t_to_40p_mins"),
        "t_to_60p_mins": st.get("t_to_60p_mins"),
        "sl_20p_hit_at_ts": st.get("sl_20p_hit_at_ts"),

        # arithmetic virtual outcomes — NO exit is endorsed
        "pnl_at_tp20sl20_pips": _pnl(20.0, 20.0),
        "pnl_at_tp30sl20_pips": _pnl(30.0, 20.0),
        "pnl_at_tp40sl20_pips": _pnl(40.0, 20.0),
        "pnl_at_tp60sl20_pips": _pnl(60.0, 20.0),

        # what the live bot did (best-effort signal_log lookup)
        "live_bot_fired": live_status.get("live_bot_fired"),
        "live_bot_deal_id": live_status.get("live_bot_deal_id"),
    }
    _write_jsonl(record)


# ── UPDATE OPEN TRADES ON EACH BAR CLOSE ──────────────────────────────
def _fade_signed(side: str, current_px: float, entry_px: float) -> float:
    """Return signed pip pnl in the fade direction from entry.
    LOWER pierce → BUY → +pips if price rises above entry.
    UPPER pierce → SELL → +pips if price falls below entry.
    """
    if side == "LOWER":
        return (float(current_px) - float(entry_px)) / float(_PIP_SIZE)
    return (float(entry_px) - float(current_px)) / float(_PIP_SIZE)


def _update_open_trades(cur_ts: datetime,
                        cur_bar: Dict[str, float],
                        bb_lower_now: float, bb_upper_now: float,
                        ) -> None:
    """For each open pierce state:
      • If not yet entered: check rejection contract on THIS bar. On
        qualifying rejection → set entry price = cur.close, entry_ts.
        If pierce+REJECTION_WINDOW_BARS elapsed → resolution=no_rejection,
        finalize.
      • If entered: update MFE/MAE and first-hit times. Finalize once
        horizon elapsed or session-end reached.
    """
    to_finalize: List[Dict[str, Any]] = []
    with _OPEN_LOCK:
        for st in _OPEN:
            if st.get("resolved"):
                continue
            age_secs = (cur_ts - st["pierce_ts_utc"]).total_seconds()
            age_bars = age_secs / 300.0

            if st.get("entry_price") is None:
                # Not yet entered → still in rejection-search window
                if 1 <= round(age_bars) <= int(_REJ_WIN_BARS):
                    if _is_rejection_bar(
                        st["side"], cur_bar, bb_lower_now, bb_upper_now,
                    ):
                        st["entry_price"] = float(cur_bar["close"])
                        st["entry_ts_utc"] = cur_ts
                        st["resolution_type"] = "rejection"
                        continue  # start MFE tracking next bar
                if age_bars > int(_REJ_WIN_BARS) + 0.001:
                    # No rejection within window → resolved
                    st["resolution_type"] = "no_rejection"
                    st["resolved"] = True
                    to_finalize.append(st)
                continue

            # Entered — track MFE/MAE from entry
            entry_px = float(st["entry_price"])
            entry_ts = st["entry_ts_utc"]
            # favorable = fade direction; adverse = opposite
            # For LOWER (BUY): favorable price movement = up (high favors);
            #                  adverse = down (low hurts).
            # For UPPER (SELL): favorable = down (low favors); adverse = up.
            if st["side"] == "LOWER":
                fav_pips = (float(cur_bar["high"]) - entry_px) / float(_PIP_SIZE)
                adv_pips = (entry_px - float(cur_bar["low"])) / float(_PIP_SIZE)
            else:
                fav_pips = (entry_px - float(cur_bar["low"])) / float(_PIP_SIZE)
                adv_pips = (float(cur_bar["high"]) - entry_px) / float(_PIP_SIZE)

            if fav_pips > st["mfe_pips"]:
                st["mfe_pips"] = float(fav_pips)
            if adv_pips > st["mae_pips"]:
                st["mae_pips"] = float(adv_pips)

            mins_since_entry = (cur_ts - entry_ts).total_seconds() / 60.0
            for thresh, key in ((10, "t_to_10p_mins"),
                                (20, "t_to_20p_mins"),
                                (30, "t_to_30p_mins"),
                                (40, "t_to_40p_mins"),
                                (60, "t_to_60p_mins")):
                if st.get(key) is None and st["mfe_pips"] >= thresh:
                    st[key] = round(mins_since_entry, 1)
            if st.get("sl_20p_hit_at_ts") is None and st["mae_pips"] >= 20.0:
                st["sl_20p_hit_at_ts"] = cur_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Horizon check
            horizon_secs = float(MFE_HORIZON_HOURS) * 3600.0
            session_end_dt = cur_ts.replace(
                hour=int(SESSION_END_UTC_HOUR), minute=0, second=0, microsecond=0,
            )
            if entry_ts.date() != cur_ts.date():
                # crossed midnight — session_end is on the ENTRY's date
                session_end_dt = entry_ts.replace(
                    hour=int(SESSION_END_UTC_HOUR), minute=0, second=0, microsecond=0,
                )
            hit_horizon = (cur_ts - entry_ts).total_seconds() >= horizon_secs
            hit_session_end = cur_ts >= session_end_dt
            if hit_horizon or hit_session_end:
                st["resolved"] = True
                to_finalize.append(st)

        # Purge resolved
        if to_finalize:
            _OPEN[:] = [s for s in _OPEN if not s.get("resolved")]

    # Emit outside the lock (jsonl write has its own lock)
    for st in to_finalize:
        try:
            _finalize_resolution(st)
        except Exception as _exc:  # noqa: BLE001
            logger.warning(
                "[bb_pierce_recorder] finalize failed for pierce_ts=%s: %s",
                st.get("pierce_ts_utc"), _exc,
            )


# ── MAIN CALLBACK — 5M CLOSE ──────────────────────────────────────────
def _process_close(df_5m: Any, is_backfill: bool = False) -> None:
    """Detect pierce on the last row + update open-trades.
    Precondition: df_5m has columns timestamp,open,high,low,close and
    at least BB_PERIOD+1 rows. Never raises."""
    if not _SHARED_OK or df_5m is None:
        return
    try:
        n = len(df_5m)
        if n < int(_BB_PERIOD) + 1:
            return
        closes = [float(c) for c in df_5m["close"].tolist()]
        try:
            bb_lo_now, bb_mid_now, bb_up_now = _shared_bb_20_2(closes)
        except ValueError:
            return

        # last-row OHLC + ts
        last = df_5m.iloc[-1]
        ts_col = "timestamp" if "timestamp" in df_5m.columns else "time"
        ts_raw = last[ts_col]
        cur_ts = _to_utc(
            ts_raw.to_pydatetime() if hasattr(ts_raw, "to_pydatetime") else ts_raw,
        )
        if cur_ts is None:
            return
        cur_bar = {
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
        }

        # 1) update open trades against cur bar first (so a bar can be
        #    both a rejection for an older pierce AND a new pierce)
        _update_open_trades(cur_ts, cur_bar, bb_lo_now, bb_up_now)

        # 2) detect NEW pierce on cur bar using BB @ this close
        side, dist_pips, open_inside = _detect_pierce_on_bar(
            cur_bar, bb_lo_now, bb_up_now,
        )
        if side is None:
            return

        # Strategy arm-gate compatibility: reuse the strategy's own
        # detector so this label is definitionally identical.
        try:
            strat_bar = _BBBar(
                timestamp=cur_ts,
                open=cur_bar["open"], high=cur_bar["high"],
                low=cur_bar["low"], close=cur_bar["close"],
            )
            strat_dir, strat_reason = _shared_detect_pierce_setup(
                strat_bar, bb_lo_now, bb_up_now,
            )
            strategy_would_arm = strat_dir is not None
        except Exception:
            strategy_would_arm = False

        virt_dir = "BUY" if side == "LOWER" else "SELL"
        at_pierce_context = _enrich_at_pierce(
            df_5m, cur_ts, side, virt_dir, cur_bar["close"], is_backfill,
        )
        st = _new_pierce_state(
            pierce_ts=cur_ts,
            side=side,
            virtual_direction=virt_dir,
            bar_ohlc=cur_bar,
            bb={"upper": bb_up_now, "mid": bb_mid_now, "lower": bb_lo_now},
            distance_beyond_band_pips=dist_pips,
            open_inside_band=open_inside,
            strategy_would_arm=strategy_would_arm,
            at_pierce_context=at_pierce_context,
            is_backfill=is_backfill,
        )
        _emit_pierce_record(st)
        with _OPEN_LOCK:
            _OPEN.append(st)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bb_pierce_recorder] _process_close failed: %s", exc)


def on_5m_close(payload: Dict[str, Any]) -> None:
    """5M-close callback entry. BLANKET try/except — never raises."""
    try:
        if not ENABLED or not _SHARED_OK:
            return
        sym = str(payload.get("symbol") or "").upper()
        if sym != "GBPUSD":
            return
        df = payload.get("df_5m")
        if df is None:
            df = payload.get("candles_5m_closed_df")
        _process_close(df, is_backfill=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bb_pierce_recorder] on_5m_close failed: %s", exc)


# ── BACKFILL FROM CANDLE ARCHIVE ──────────────────────────────────────
def _load_backfill_df() -> Any:
    """Read the daily archive CSVs (BACKFILL_START..today) into a
    single DataFrame sorted by timestamp with columns:
        timestamp, open, high, low, close
    No indicator enrichment — backfill enrichment fields will be null
    where they depend on enriched columns."""
    try:
        import pandas as pd
        start_dt = datetime.strptime(BACKFILL_START_STR, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        frames: List[Any] = []
        for csv_path in sorted(ARCHIVE_DIR.glob("*.csv")):
            try:
                dstr = csv_path.stem
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
            except Exception:
                continue
            if d < start_dt or d > today:
                continue
            try:
                df = pd.read_csv(csv_path)
                if "timestamp" not in df.columns and "time" in df.columns:
                    df = df.rename(columns={"time": "timestamp"})
                frames.append(df[["timestamp", "open", "high", "low", "close"]])
            except Exception as _rd_exc:  # noqa: BLE001
                logger.warning(
                    "[bb_pierce_recorder] backfill read %s failed: %s",
                    csv_path.name, _rd_exc,
                )
        if not frames:
            return None
        out = pd.concat(frames, ignore_index=True)
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        out = out.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bb_pierce_recorder] backfill load failed: %s", exc)
        return None


def _run_backfill() -> int:
    """Replay the archive through _process_close row-by-row. Returns
    count of PIERCE records written. Never raises."""
    if not BACKFILL_ENABLED or not _SHARED_OK:
        return 0
    try:
        df = _load_backfill_df()
        if df is None or len(df) < int(_BB_PERIOD) + 1:
            return 0
        # Enrich with EMA_21 + ATR_14 + BB_UPPER_20_2 + BB_LOWER_20_2 +
        # BB_WIDTH_20 + ADX_14 + MACD_HIST_12_26_9 so signal_logger
        # helpers can populate their fields. Best-effort; on failure the
        # per-row enrichment simply nulls.
        try:
            import indicators as _ind
            cfg = _ind.IndicatorsConfig()
            df = _ind.add_indicators(df, cfg)
        except Exception as _ind_exc:  # noqa: BLE001
            logger.warning(
                "[bb_pierce_recorder] backfill enrichment failed (nulls preserved): %s",
                _ind_exc,
            )

        count_before = _count_pierces_in_file()
        # Walk row-by-row, feeding progressive slices to _process_close.
        # First BB_PERIOD rows are warmup; nothing detectable there.
        # For memory efficiency on ~15k rows, we don't copy — .iloc slice
        # returns a view.
        total = len(df)
        # Progress logging every 1000 rows so a slow backfill leaves
        # a breadcrumb trail.
        for i in range(int(_BB_PERIOD), total):
            slice_df = df.iloc[: i + 1]
            _process_close(slice_df, is_backfill=True)
            if (i - int(_BB_PERIOD)) and ((i - int(_BB_PERIOD)) % 2000 == 0):
                logger.info(
                    "[bb_pierce_recorder] backfill progress: %d / %d rows",
                    i, total,
                )

        # Flush any still-open pierces at end of backfill as no_rejection
        # / horizon-end so the file has no orphaned PIERCE-without-
        # RESOLUTION rows.
        with _OPEN_LOCK:
            leftover = list(_OPEN)
            _OPEN.clear()
        for st in leftover:
            try:
                if st.get("resolution_type") is None:
                    st["resolution_type"] = "no_rejection"
                st["resolved"] = True
                _finalize_resolution(st)
            except Exception:  # noqa: BLE001
                pass

        count_after = _count_pierces_in_file()
        written = max(0, count_after - count_before)
        logger.info(
            "[bb_pierce_recorder] backfill complete: %d PIERCE records written",
            written,
        )
        return written
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bb_pierce_recorder] backfill failed: %s", exc)
        return 0


def _count_pierces_in_file() -> int:
    try:
        if not LOG_PATH.exists():
            return 0
        n = 0
        with LOG_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                if '"record_type":"PIERCE"' in line:
                    n += 1
        return n
    except Exception:
        return 0


def _file_has_any_rows_beyond_header() -> bool:
    try:
        if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
            return False
        with LOG_PATH.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i == 0:
                    continue
                if line.strip():
                    return True
        return False
    except Exception:
        return False


# ── REGISTRATION ──────────────────────────────────────────────────────
def start(*, register_callback: bool = True,
          run_backfill: bool = True) -> None:
    """Idempotent startup. Writes header + runs backfill (once) and
    registers itself on the 5M-close chain. Any per-step failure is
    logged but does not abort registration.
    """
    global _STARTED
    if not ENABLED:
        logger.info("[bb_pierce_recorder] disabled via BB_PIERCE_RECORDER_ENABLED=0")
        return
    if not _SHARED_OK:
        logger.error("[bb_pierce_recorder] shared-code import failed; not starting")
        return
    if _STARTED:
        return
    _STARTED = True
    try:
        _write_header_if_missing()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bb_pierce_recorder] header write failed: %s", exc)

    # Backfill only if the file has no non-header rows yet.
    if run_backfill and not _file_has_any_rows_beyond_header():
        try:
            _run_backfill()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[bb_pierce_recorder] backfill wrapper failed: %s", exc)

    if register_callback:
        try:
            from candle_builder import register_5m_close_callback
            register_5m_close_callback(on_5m_close)
            logger.info(
                "[bb_pierce_recorder] registered 5m-close callback → %s",
                LOG_PATH,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[bb_pierce_recorder] callback registration failed: %s",
                exc,
            )


# Auto-register on import so callers only need `import bb_pierce_recorder`.
# Wrapped so an import-time failure NEVER touches the trading loop.
try:
    start()
except Exception as _imp_exc:  # noqa: BLE001
    logger.error(
        "[bb_pierce_recorder] import-time start failed: %s", _imp_exc,
    )
