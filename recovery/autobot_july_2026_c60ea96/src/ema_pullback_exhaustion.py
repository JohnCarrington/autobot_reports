"""EMA_PULLBACK exhaustion + trend-trap telemetry — capture-only.

Captures two separable post-fire reads so they can later be joined against
real-fill outcomes:

  exhaustion_confluence_3 (0-3) — the divergence-exhaustion view:
    1. RSI(14) divergence vs prior swing (against fire direction).
    2. MACD-hist magnitude + whether it is shrinking into the entry.
    3. Price extension from EMA50 in pips beyond a placeholder threshold.

  trend_trap_score (0-4) — the falling-knife / fading-stacked-fan view.
  Adds:
    4. entry_against_fan: LONG into a cleanly bearish-stacked EMA fan
       (8<13<21<50) or SHORT into a bullish-stacked one. Designed to flag
       mean-reversion longs firing into a strong downtrend — the trade
       type RSI-divergence alone does NOT catch.

The two scores intentionally overlap on legs 1-3 and stay reported
separately: divergence-exhaustion and fan-trap catch different trade
types and should be analysed apart.

GATES NOTHING. The kill-switch EMA_PULLBACK_EXHAUSTION_TELEMETRY_ENABLED
defaults OFF; nothing runs and no file is written unless the flag is set
on a deliberate restart.

RSI(14) is computed fresh from df_5m['close']. The live IndicatorsConfig
pins rsi_period=3 so the RSI_3 column on df_5m is NOT the right signal
here — substituting it would be a bug.

Prior-swing window reused verbatim from htf_authority._exemption_check
(bars [n-31, n-16) relative to the last closed 5M bar) so the two reads
join apples-to-apples.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger("ema_pullback_exhaustion")

LOG_PATH = os.getenv(
    "EMA_PULLBACK_EXHAUSTION_LOG_PATH",
    "/opt/tradingbot/logs/ema_pullback_exhaustion.jsonl",
)
KILL_SWITCH_ENV = "EMA_PULLBACK_EXHAUSTION_TELEMETRY_ENABLED"

# Placeholder — calibrate once enough fires-with-outcomes are joined. Used
# only by the "price extended beyond EMA50" leg of exhaustion_confluence;
# nothing else in the system reads it.
EXTENSION_FROM_EMA50_PIPS_PLACEHOLDER: float = 8.0

# RSI(14) prior-swing window: [n-1-LOOKBACK, n-1-HALF) relative to the last
# closed bar (i.e. 15 bars centred ~22 bars before setup). Identical to the
# window used by htf_authority._exemption_check so the two telemetry reads
# share a definition.
SWING_LOOKBACK_BARS: int = 30
SWING_HALF_BARS: int = 15

# Fan-widening comparison: current min-adjacent-gap vs the gap N bars back.
# Placeholder — calibrate once enough fires-with-outcomes are joined.
FAN_WIDENING_LOOKBACK_BARS: int = 5

_lock = threading.Lock()


def _env_bool(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def is_enabled() -> bool:
    return _env_bool(KILL_SWITCH_ENV, "0")


def compute(
    df_5m: "pd.DataFrame",
    direction: str,
    pip_size: float,
    decision_debug: Optional[Dict[str, Any]] = None,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the exhaustion + trend-trap telemetry dict for the fire context.

    Pure read — never raises, never mutates df_5m. Errors short-circuit to
    a dict with `err` populated so the caller still gets a partial row.

    decision_debug is an optional pass-through of the strategy's
    decision.debug dict; only `fan_width_pips_at_fire` is read if present
    (used in preference to the helper's own min-adjacent-gap so the
    telemetry matches what the strategy itself recorded).

    symbol enables the H1-EMA-direction capture. We call the SAME
    indicators.h1_ema_direction(symbol, pip_size=ps) entry point the live
    BB_BOUNCE gate uses (gbpusd_bb_bounce.py:473), so the logged
    h1_direction/h1_strength are identical to what a gate would decide
    on at this exact moment. h1_source records provenance:
      "live_call"   — h1_ema_direction returned a dict
      "unavailable" — function returned None or raised; fields stay None
      "cache_replay"— reserved (not used here; documented for symmetry)
    No silent reconstruction — if the live call returns nothing we log
    that and move on, so the JSONL reflects what a gate would actually
    see, including when it sees nothing.
    """
    out: Dict[str, Any] = {
        "err": None,
        "n_bars": 0,
        "swing_window": [SWING_LOOKBACK_BARS, SWING_HALF_BARS],
        "fan_widening_lookback_bars": FAN_WIDENING_LOOKBACK_BARS,
        "rsi14_now": None,
        "rsi14_at_prior_swing": None,
        "price_at_prior_swing": None,
        "price_now": None,
        "rsi14_divergence": None,
        "macd_hist_now": None,
        "macd_hist_shrinking": None,
        "macd_hist_last3": None,
        "price_vs_ema8_pips": None,
        "price_vs_ema21_pips": None,
        "price_vs_ema50_pips": None,
        "extension_threshold_pips": EXTENSION_FROM_EMA50_PIPS_PLACEHOLDER,
        "price_extended_against_direction": None,
        "ema8": None,
        "ema13": None,
        "ema21": None,
        "ema50": None,
        "ema200": None,
        "fan_stack_order": None,
        "fan_is_bearish_stacked": None,
        "fan_is_bullish_stacked": None,
        "fan_width_pips": None,
        "fan_width_pips_source": None,
        "fan_widening": None,
        "entry_against_fan": None,
        "h1_direction": None,
        "h1_strength": None,
        "h1_separation_pips": None,
        "h1_source": "unavailable",
        "exhaustion_confluence_3": None,
        "trend_trap_score": None,
    }

    direction_u = str(direction or "").upper()
    is_long = direction_u in ("BUY", "LONG", "L")
    is_short = direction_u in ("SELL", "SHORT", "S")
    if not (is_long or is_short):
        out["err"] = "unknown_direction"
        return out

    if df_5m is None or len(df_5m) == 0:
        out["err"] = "no_df_5m"
        return out

    try:
        ps = float(pip_size)
    except (TypeError, ValueError):
        out["err"] = "invalid_pip_size"
        return out
    if ps <= 0:
        out["err"] = "non_positive_pip_size"
        return out

    n = int(len(df_5m))
    out["n_bars"] = n
    if n < 35:
        out["err"] = "insufficient_5m_bars"
        return out

    try:
        from indicators import rsi as _rsi
        closes = df_5m["close"].astype(float)
        r14 = _rsi(closes, 14)
    except Exception as exc:
        out["err"] = f"rsi_indicator_error:{exc}"
        return out

    try:
        rsi_now = float(r14.iloc[-1])
        price_now = float(closes.iloc[-1])
    except Exception as exc:
        out["err"] = f"tail_read_error:{exc}"
        return out
    out["rsi14_now"] = round(rsi_now, 2)
    out["price_now"] = round(price_now, 5)

    lo = n - 1 - SWING_LOOKBACK_BARS
    hi = n - 1 - SWING_HALF_BARS
    if lo < 0 or hi <= lo:
        out["err"] = "swing_window_degenerate"
        return out

    try:
        if is_long:
            # LONG ⇒ bearish-divergence warning: setup high above prior swing
            # high while RSI prints lower.
            seg_h = df_5m["high"].iloc[lo:hi].astype(float).values
            j_off = int(seg_h.argmax())
            prior_px = float(seg_h[j_off])
            prior_rsi = float(r14.iloc[lo + j_off])
            setup_extreme = float(df_5m["high"].iloc[-1])
            div = bool(setup_extreme > prior_px and rsi_now < prior_rsi)
        else:
            # SHORT ⇒ bullish-divergence warning: setup low below prior swing
            # low while RSI prints higher.
            seg_l = df_5m["low"].iloc[lo:hi].astype(float).values
            j_off = int(seg_l.argmin())
            prior_px = float(seg_l[j_off])
            prior_rsi = float(r14.iloc[lo + j_off])
            setup_extreme = float(df_5m["low"].iloc[-1])
            div = bool(setup_extreme < prior_px and rsi_now > prior_rsi)
        out["price_at_prior_swing"] = round(prior_px, 5)
        out["rsi14_at_prior_swing"] = round(prior_rsi, 2)
        out["rsi14_divergence"] = div
    except Exception as exc:
        out["err"] = f"swing_compute_error:{exc}"
        return out

    hist_col = "MACD_HIST_35_45_30"
    dec_col = "MACD_HIST_35_45_30_DECREASING2"
    if hist_col in df_5m.columns:
        try:
            hist_series = df_5m[hist_col].astype(float)
            v_now = hist_series.iloc[-1]
            out["macd_hist_now"] = None if pd.isna(v_now) else float(v_now)
            if n >= 3:
                last3 = [
                    None if pd.isna(x) else float(x)
                    for x in hist_series.iloc[-3:].tolist()
                ]
                out["macd_hist_last3"] = last3
        except Exception as exc:
            out["err"] = (out["err"] or "") + f"|macd_hist_read:{exc}"
    if dec_col in df_5m.columns:
        try:
            v = df_5m[dec_col].iloc[-1]
            out["macd_hist_shrinking"] = None if pd.isna(v) else bool(v)
        except Exception as exc:
            out["err"] = (out["err"] or "") + f"|macd_dec_read:{exc}"

    try:
        if "EMA_8" in df_5m.columns:
            v = df_5m["EMA_8"].iloc[-1]
            if not pd.isna(v):
                out["price_vs_ema8_pips"] = round((price_now - float(v)) / ps, 2)
        if "EMA_21" in df_5m.columns:
            v = df_5m["EMA_21"].iloc[-1]
            if not pd.isna(v):
                out["price_vs_ema21_pips"] = round((price_now - float(v)) / ps, 2)
        if "PRICE_VS_EMA50_PIPS" in df_5m.columns:
            v = df_5m["PRICE_VS_EMA50_PIPS"].iloc[-1]
            out["price_vs_ema50_pips"] = None if pd.isna(v) else round(float(v), 2)
        elif "EMA_50" in df_5m.columns:
            v = df_5m["EMA_50"].iloc[-1]
            if not pd.isna(v):
                out["price_vs_ema50_pips"] = round((price_now - float(v)) / ps, 2)
    except Exception as exc:
        out["err"] = (out["err"] or "") + f"|ema_distance_read:{exc}"

    ev = out["price_vs_ema50_pips"]
    if ev is not None:
        thr = EXTENSION_FROM_EMA50_PIPS_PLACEHOLDER
        if is_long:
            out["price_extended_against_direction"] = bool(ev >= thr)
        else:
            out["price_extended_against_direction"] = bool(ev <= -thr)

    # ── Fan-state capture ────────────────────────────────────────────────
    # Raw EMA values at fire + stack-order string + bearish/bullish-stacked
    # flags + fan_width_pips + widening flag + entry_against_fan
    # (falling-knife flag — see trend_trap_score below).
    try:
        def _last(col: str) -> Optional[float]:
            if col not in df_5m.columns:
                return None
            v = df_5m[col].iloc[-1]
            return None if pd.isna(v) else float(v)

        e8, e13, e21, e50, e200 = (
            _last("EMA_8"), _last("EMA_13"), _last("EMA_21"),
            _last("EMA_50"), _last("EMA_200"),
        )
        out["ema8"], out["ema13"], out["ema21"], out["ema50"], out["ema200"] = (
            (None if e8 is None else round(e8, 5)),
            (None if e13 is None else round(e13, 5)),
            (None if e21 is None else round(e21, 5)),
            (None if e50 is None else round(e50, 5)),
            (None if e200 is None else round(e200, 5)),
        )

        fan_emas = [(8, e8), (13, e13), (21, e21), (50, e50)]
        if all(v is not None for _, v in fan_emas):
            # Sort the fan EMAs descending by value to derive the stack
            # string top-to-bottom. Tie comparator (rare on float EMAs)
            # falls back to period order so the string is deterministic.
            ordered = sorted(fan_emas, key=lambda kv: (-kv[1], kv[0]))
            parts = [str(p) for p, _ in ordered]
            out["fan_stack_order"] = ">".join(parts)
            out["fan_is_bullish_stacked"] = bool(e8 > e13 > e21 > e50)
            out["fan_is_bearish_stacked"] = bool(e8 < e13 < e21 < e50)

            gaps = [abs(e8 - e13), abs(e13 - e21), abs(e21 - e50)]
            min_gap_now = min(gaps)
            dbg_fan = None
            if decision_debug is not None:
                dbg_fan = decision_debug.get("fan_width_pips_at_fire")
            if dbg_fan is not None and not pd.isna(dbg_fan):
                out["fan_width_pips"] = round(float(dbg_fan), 2)
                out["fan_width_pips_source"] = "decision_debug"
            else:
                out["fan_width_pips"] = round(min_gap_now / ps, 2)
                out["fan_width_pips_source"] = "min_adjacent_gap"

            lb = FAN_WIDENING_LOOKBACK_BARS
            if (
                n > lb
                and all(c in df_5m.columns for c in ("EMA_8", "EMA_13", "EMA_21", "EMA_50"))
            ):
                try:
                    e8p = float(df_5m["EMA_8"].iloc[-1 - lb])
                    e13p = float(df_5m["EMA_13"].iloc[-1 - lb])
                    e21p = float(df_5m["EMA_21"].iloc[-1 - lb])
                    e50p = float(df_5m["EMA_50"].iloc[-1 - lb])
                    if not any(pd.isna(x) for x in (e8p, e13p, e21p, e50p)):
                        min_gap_prior = min(
                            abs(e8p - e13p), abs(e13p - e21p), abs(e21p - e50p)
                        )
                        out["fan_widening"] = bool(min_gap_now > min_gap_prior)
                except Exception:
                    pass

            if is_long:
                out["entry_against_fan"] = bool(out["fan_is_bearish_stacked"])
            else:
                out["entry_against_fan"] = bool(out["fan_is_bullish_stacked"])
    except Exception as exc:
        out["err"] = (out["err"] or "") + f"|fan_state_read:{exc}"

    # ── H1 EMA direction + strength capture (live-call only) ─────────────
    # Uses the SAME entry point the BB_BOUNCE COUNTER-H1 gate calls
    # (gbpusd_bb_bounce.py:473 → indicators.h1_ema_direction(symbol,
    # pip_size=PIP_SIZE)). Capture-only here — value is logged raw, not
    # folded into any score, not gated on. If the live call returns None
    # or raises, h1_source stays "unavailable" and the fields stay None
    # (no fallback / reconstruction — we want to log what a gate would
    # actually have seen, including misses).
    if symbol:
        try:
            from indicators import h1_ema_direction as _h1_dir
            _h1 = _h1_dir(str(symbol), pip_size=ps)
        except Exception as exc:
            _h1 = None
            out["err"] = (out["err"] or "") + f"|h1_call:{exc}"
        if isinstance(_h1, dict):
            try:
                _strength = _h1.get("separation_strength")
                _sep_pips = _h1.get("separation_pips")
                out["h1_direction"] = _h1.get("direction")
                out["h1_strength"] = (
                    None if _strength is None else round(float(_strength), 4)
                )
                out["h1_separation_pips"] = (
                    None if _sep_pips is None else round(float(_sep_pips), 3)
                )
                out["h1_source"] = "live_call"
            except Exception as exc:
                out["err"] = (out["err"] or "") + f"|h1_unpack:{exc}"

    legs3 = [
        out["rsi14_divergence"],
        out["macd_hist_shrinking"],
        out["price_extended_against_direction"],
    ]
    out["exhaustion_confluence_3"] = int(sum(1 for v in legs3 if v is True))
    legs4 = legs3 + [out["entry_against_fan"]]
    out["trend_trap_score"] = int(sum(1 for v in legs4 if v is True))

    return out


def log_fire(
    *,
    trade_id: str,
    deal_id: Optional[str],
    epic: str,
    symbol: str,
    direction: str,
    fire_ts_utc: Optional[datetime],
    df_5m: "pd.DataFrame",
    pip_size: float,
    decision_debug: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one JSONL row to LOG_PATH. Swallowing writer — telemetry-only,
    must never raise back into the entry path. Caller is responsible for
    gating on is_enabled()."""
    try:
        rec = compute(
            df_5m,
            direction,
            pip_size,
            decision_debug=decision_debug,
            symbol=symbol,
        )
        rec["trade_id"] = trade_id
        rec["deal_id"] = deal_id
        rec["epic"] = epic
        rec["symbol"] = (symbol or "").upper()
        rec["direction"] = (direction or "").upper()
        if fire_ts_utc is not None:
            try:
                rec["fire_ts_utc"] = fire_ts_utc.isoformat()
            except Exception:
                rec["fire_ts_utc"] = str(fire_ts_utc)
        rec["logged_at_utc"] = datetime.now(timezone.utc).isoformat()

        d = os.path.dirname(LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _lock:
            with open(LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[ema_pullback_exhaustion] log_fire failed: %s", exc)
