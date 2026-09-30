"""V5 market_data assembly — extends v4's _assemble_data_package with the
fields the deterministic scorer needs that v4 never computed.

The single source of truth for the v4 fields is morning_briefing._assemble_data_package.
This module imports it and enriches the output, rather than reimplementing
candle aggregation. That is deliberate — see PHASE1_README.md.

Two callable surfaces:

  assemble_v5_data_package(symbol, session, now_utc) -> Optional[dict]
      Production / runtime path. Requires morning_briefing.start() to have
      been called first (i.e. _BUILDER and _TF_CTX are populated). Pulls
      v4 data, then computes the additional fields below and returns the
      merged dict.

  assemble_v5_data_package_offline(symbol, session, now_utc, df_5m,
                                   df_h1, df_h4, df_d1) -> dict
      Offline / dry-run path. Takes pre-aggregated DataFrames so a CLI
      can produce a market_data dict without sentinel running. Used by
      scripts/dry_run_v5_pia.py for the Phase-1 verification report.

Fields added on top of the v4 package:

    d1_ema_20                   float       latest D1 close-EMA(20)
    h4_ema_20                   float       latest H4 close-EMA(20)
    h4_ema_20_5bar_diff_pips    float       (ema20[t] - ema20[t-5]) / ppp, signed
    atr_h4_pips                 float       mean(high-low) over last 14 H4 bars / ppp
    atr_pctl_14                 float|None  ATR_PCTL_14 from 5M df (last bar)
    bb_width_pctl_20_2          float|None  BB_WIDTH_PCTL_20_2 from 5M df
    ema_stack_state             str |None   EMA_STACK_STATE from 5M df
    phase4_structure            str         "TRENDING" | "RANGE" | "NEUTRAL"
    phase4_structure_raw        str         raw classifier label (TRENDING_BULL/...)
    phase4_features             dict        classifier info["features"] echo
    ppp                         float       points-per-pip (pair_config)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from pair_config import get_ppp


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def _ema_series(closes: List[float], period: int) -> Optional[pd.Series]:
    """EMA via pandas .ewm — same convention as morning_briefing._ewm
    (adjust=False, span=period). Returns None if too few inputs."""
    if not closes or len(closes) < max(2, period // 4):
        return None
    s = pd.Series(closes, dtype="float64")
    return s.ewm(span=period, adjust=False).mean()


def _last_ema(closes: List[float], period: int) -> Optional[float]:
    s = _ema_series(closes, period)
    if s is None or s.empty:
        return None
    v = float(s.iloc[-1])
    return v if pd.notna(v) else None


def _ema_5bar_diff_pips(
    closes: List[float], period: int, ppp: float, direction_bull: bool,
) -> Optional[float]:
    """Signed pip difference (ema[t] - ema[t-5]) / ppp.

    Sign convention: positive when the EMA is rising (bullish slope).
    The scorer flips the comparison itself based on trade direction.
    """
    s = _ema_series(closes, period)
    if s is None or len(s) < 6:
        return None
    diff = float(s.iloc[-1]) - float(s.iloc[-6])
    return round(diff / ppp, 4)


def _atr_pips(candles_olhc: List[Dict[str, Any]], period: int, ppp: float) -> Optional[float]:
    """Simple high-low range mean over last *period* bars, in pips.

    Spec calls for "ATR(H4)" but doesn't pin down Wilder vs simple. We use
    simple mean(H-L) for now — same shape v4 uses for atr_today_pips and
    atr_20day_avg_pips. If shadow data calls for Wilder we swap it in
    Phase 2 alongside the LLM rationale work.
    """
    if not candles_olhc or len(candles_olhc) < period:
        return None
    ranges_pips = []
    for c in candles_olhc[-period:]:
        try:
            h = float(c.get("h", c.get("high")))
            lo = float(c.get("l", c.get("low")))
            ranges_pips.append((h - lo) / ppp)
        except (TypeError, ValueError):
            continue
    if not ranges_pips:
        return None
    return round(sum(ranges_pips) / len(ranges_pips), 2)


def _closes_from(candles: List[Dict[str, Any]]) -> List[float]:
    out: List[float] = []
    for c in candles:
        for k in ("c", "close"):
            if k in c:
                try:
                    out.append(float(c[k]))
                except (TypeError, ValueError):
                    pass
                break
    return out


def _scalar_from_5m_col(df_5m: Optional[pd.DataFrame], col: str) -> Optional[Any]:
    if df_5m is None or not isinstance(df_5m, pd.DataFrame) or df_5m.empty:
        return None
    if col not in df_5m.columns:
        return None
    v = df_5m[col].iloc[-1]
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return v


def _classify_phase4(
    symbol: str, df_5m: Optional[pd.DataFrame], pip_size: float,
) -> Dict[str, Any]:
    """Map CandleRegimeClassifier output → v5 phase4 fields.

    Returns a dict with keys: phase4_structure, phase4_structure_raw,
    phase4_features. The mapping TRENDING_BULL/TRENDING_BEAR → "TRENDING"
    is per Phase-1 spec; the raw label is preserved separately so the
    scorer can still check direction alignment.
    """
    out = {
        "phase4_structure":     "NEUTRAL",
        "phase4_structure_raw": "NEUTRAL",
        "phase4_features":      {},
    }
    if df_5m is None or not isinstance(df_5m, pd.DataFrame) or df_5m.empty:
        return out
    try:
        from regime_classifier import CandleRegimeClassifier
    except Exception:
        return out
    try:
        clf = CandleRegimeClassifier(symbol=symbol, pip_size=pip_size)
        raw, info = clf.update_from_df(df_5m, pip_size=pip_size)
    except Exception:
        return out
    raw = str(raw or "NEUTRAL").upper()
    if raw in ("TRENDING_BULL", "TRENDING_BEAR"):
        mapped = "TRENDING"
    elif raw == "RANGE":
        mapped = "RANGE"
    else:
        mapped = "NEUTRAL"
    out["phase4_structure"]     = mapped
    out["phase4_structure_raw"] = raw
    if isinstance(info, dict):
        out["phase4_features"] = info.get("features", {}) or {}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment — runs against any v4-shape base dict
# ─────────────────────────────────────────────────────────────────────────────

def _enrich(
    base: Dict[str, Any], symbol: str, df_5m: Optional[pd.DataFrame],
) -> Dict[str, Any]:
    """Append the v5-specific fields onto the v4 data package in-place."""
    ppp = float(get_ppp(symbol))
    base["ppp"] = ppp

    h4 = base.get("h4_candles") or []
    d1 = base.get("d1_candles") or []
    h4_closes = _closes_from(h4)
    d1_closes = _closes_from(d1)

    base["d1_ema_20"] = _last_ema(d1_closes, 20)
    base["h4_ema_20"] = _last_ema(h4_closes, 20)
    base["h4_ema_20_5bar_diff_pips"] = _ema_5bar_diff_pips(
        h4_closes, 20, ppp, direction_bull=True,
    )
    base["atr_h4_pips"] = _atr_pips(h4, period=14, ppp=ppp)

    base["atr_pctl_14"]        = _scalar_from_5m_col(df_5m, "ATR_PCTL_14")
    base["bb_width_pctl_20_2"] = _scalar_from_5m_col(df_5m, "BB_WIDTH_PCTL_20_2")
    base["ema_stack_state"]    = _scalar_from_5m_col(df_5m, "EMA_STACK_STATE")

    base.update(_classify_phase4(symbol, df_5m, pip_size=ppp))

    # Forward calendar — 5 days HIGH-impact for the pair's currency bases.
    # Failures are swallowed (returns []) so calendar outages can never
    # break briefing assembly.
    base["upcoming_events"] = _fetch_upcoming_for_symbol(symbol)
    return base


def _fetch_upcoming_for_symbol(symbol: str) -> List[Dict[str, Any]]:
    try:
        import news_calendar
    except Exception:
        return []
    try:
        return news_calendar.get_upcoming_events(
            hours_ahead=_UPCOMING_HOURS_AHEAD,
            currencies=_currencies_for_symbol(symbol),
            impact_min="HIGH",
        )
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Runtime entry point
# ─────────────────────────────────────────────────────────────────────────────

# Forward window (hours) for upcoming_events injected into market_data.
# 120 hours = 5 calendar days. The Finnhub cache holds 7 days but exposing
# 5 keeps the prompt body bounded.
_UPCOMING_HOURS_AHEAD = 120


# Local pair → currency-bases map. Mirrors morning_briefing.SYMBOL_CURRENCIES;
# duplicated locally so this module doesn't import morning_briefing for a
# 5-line constant (PHASE1_README's "no v4 dep" rule).
_SYMBOL_CURRENCIES: Dict[str, List[str]] = {
    "GBPUSD": ["GBP", "USD"],
    "EURUSD": ["EUR", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCAD": ["USD", "CAD"],
    "GBPJPY": ["GBP", "JPY"],
}


def _currencies_for_symbol(symbol: str) -> List[str]:
    s = (symbol or "").upper()
    if s in _SYMBOL_CURRENCIES:
        return list(_SYMBOL_CURRENCIES[s])
    if len(s) == 6 and s.isalpha():
        return [s[:3], s[3:]]
    return ["USD"]


# H4 / D1 / H1 history depth for the v5 producer. Spec for
# trade_plan_builder asks for 40 H4 bars (`_LEVEL_LOOKBACK_BARS`); v4's
# _assemble_data_package hardcodes a 20-bar [-20:] slice (morning_briefing.py
# ~639-641) which silently truncates the level-discovery window from the
# spec's ~6.7 days back to ~3.3 days. We re-pull H4 directly from _TF_CTX
# at v5-fetch time to widen the window WITHOUT perturbing v4's shape — v4
# consumers in briefing_execution.py / morning_briefing.py read base off a
# fresh dict each call; v5's wider slice does not flow back to them.
_V5_H4_DEPTH = 40
_V5_D1_DEPTH = 20
_V5_H1_DEPTH = 20


def _widen_h4_for_v5(base: Dict[str, Any], symbol: str) -> None:
    """Re-pull H4 candles directly from the timeframe-context cache at the
    v5 producer's preferred depth (40 bars), in-place on `base`.

    Falls back to the v4 [-20:] slice already on `base` if _TF_CTX or the
    formatter is unavailable (e.g. in tests that bypass start()).
    """
    try:
        import morning_briefing as _mb
    except Exception:
        return
    tf = getattr(_mb, "_TF_CTX", None)
    if tf is None:
        return
    sym = symbol.upper()
    try:
        h4_full = list(tf._h4_closed.get(sym, []))[-_V5_H4_DEPTH:]
    except Exception:
        return
    if not h4_full:
        return
    fmt = getattr(_mb, "_fmt_candles", None)
    try:
        base["h4_candles"] = fmt(h4_full) if fmt is not None else h4_full
    except Exception:
        # Keep v4 slice rather than crash the briefing.
        return


def assemble_v5_data_package(
    symbol: str, session: str, now_utc: datetime,
) -> Optional[Dict[str, Any]]:
    """Production path. Calls morning_briefing._assemble_data_package then
    enriches. Returns None when v4 returns None (insufficient data).
    Requires morning_briefing.start() to have been called first."""
    import morning_briefing  # local import — avoid circular at module load
    base = morning_briefing._assemble_data_package(symbol, session)
    if base is None:
        return None
    # Widen H4 to 40 bars for v5 (spec-driven; see trade_plan_builder
    # _LEVEL_LOOKBACK_BARS=40). Mutates `base` in place.
    _widen_h4_for_v5(base, symbol)
    df_5m = None
    try:
        if morning_briefing._BUILDER is not None:
            df_5m = morning_briefing._BUILDER.get_df(symbol)
    except Exception:
        df_5m = None
    return _enrich(base, symbol, df_5m)


# ─────────────────────────────────────────────────────────────────────────────
# Offline / dry-run entry point
# ─────────────────────────────────────────────────────────────────────────────

def assemble_v5_data_package_offline(
    symbol: str, session: str, now_utc: datetime,
    *, df_5m: pd.DataFrame, df_h1: pd.DataFrame, df_h4: pd.DataFrame,
    df_d1: pd.DataFrame,
) -> Dict[str, Any]:
    """Offline path used by scripts/dry_run_v5_pia.py and tests. Takes
    pre-aggregated frames so the call works without _TF_CTX / _BUILDER.

    The synthesised "base" mirrors only the keys the v5 scorer + plan
    builder actually read (d1_candles, h4_candles, h1_candles,
    current_price, news_events). Any v4 field the scorer doesn't touch
    is omitted — keeps the dry-run output readable.
    """
    base: Dict[str, Any] = {
        "symbol":            symbol.upper(),
        "session":           session,
        "current_price":     float(df_5m["close"].iloc[-1]) if len(df_5m) else None,
        "d1_candles":        _df_to_olhc_dicts(df_d1),
        # The offline path historically passes whatever the caller hands
        # in (up to max_n=50). Don't truncate to 40 here — that breaks
        # bar-set parity with regression fixtures that rely on the wider
        # window for EMA calibration. The runtime widening logic
        # (_widen_h4_for_v5) is the only enforcement point for the
        # spec-mandated 40-bar minimum on live data.
        "h4_candles":        _df_to_olhc_dicts(df_h4),
        "h1_candles":        _df_to_olhc_dicts(df_h1),
        "news_events":       [],  # caller may overwrite from news_calendar.get_todays_events
        "briefing_time_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return _enrich(base, symbol, df_5m)


def _df_to_olhc_dicts(df: pd.DataFrame, max_n: int = 50) -> List[Dict[str, Any]]:
    """Convert a candle DataFrame to v4 short-key dicts (t/o/h/l/c)."""
    if df is None or df.empty:
        return []
    out: List[Dict[str, Any]] = []
    tail = df.tail(max_n)
    for _, row in tail.iterrows():
        try:
            ts = row.get("timestamp", row.name)
            ts_str = str(ts.isoformat()) if hasattr(ts, "isoformat") else str(ts)
            out.append({
                "t": ts_str,
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out
