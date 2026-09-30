#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_feed_audit.py — Standalone diagnostic for multi-timeframe data feed reliability.

Usage:
    python3 /opt/tradingbot/data_feed_audit.py

READ-ONLY: no changes to any existing bot logic or state.
Output  : console + /opt/tradingbot/logs/data_feed_audit.log

Sections
--------
1. Data feed check  — 5M / H1 / H4 / D1 per symbol
2. Indicator values — EMA 8/13/21/50/200, BB(20,2), MACD(35/45/30), RSI(3)
3. HTF snapshot     — TimeframeContext replay vs raw EMA relationships
4. News calendar    — NEWS_DAYS state + ForexFactory live feed probe
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = Path("/opt/tradingbot")
CACHE_DIR = BASE_DIR / "cache"
LOG_DIR   = BASE_DIR / "logs"
LOG_FILE  = LOG_DIR  / "data_feed_audit.log"

sys.path.insert(0, str(BASE_DIR))

# Pure project utilities (no I/O, no global state modified on import)
from indicators import ema as _ema_fn, bollinger_bands, macd, rsi
from timeframe_context import TimeframeContext

# ── Audit configuration ───────────────────────────────────────────────────────
SYMBOLS = ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]

TF_SECONDS: Dict[str, int] = {
    "5M":  300,
    "H1":  3600,
    "H4":  14400,
    "D1":  86400,
}

# Flag gap when consecutive-candle diff exceeds this (seconds)
GAP_THRESHOLDS: Dict[str, int] = {
    "5M":  600,      # > 2 missing bars
    "H1":  7200,     # > 2 missing bars
    "H4":  28800,    # > 2 missing bars
    "D1":  172800,   # > 2 days (weekend-safe)
}

# Flag most-recent candle as stale when older than this (seconds)
STALE_THRESHOLDS: Dict[str, int] = {
    "5M":  600,
    "H1":  7200,
    "H4":  28800,
    "D1":  172800,
}

# Indicator params (audit-specific — differ from bot live config)
EMA_PERIODS    = [8, 13, 21, 50, 200]
BB_PERIOD      = 20
BB_STD         = 2.0
MACD_FAST      = 35
MACD_SLOW      = 45
MACD_SIGNAL    = 30
RSI_PERIOD     = 3

# HTF bias uses the same EMA params the bot uses (TimeframeContext defaults)
HTF_EMA_FAST = 20
HTF_EMA_SLOW = 50

# ForexFactory
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_CURRENCIES = {"USD", "GBP", "EUR", "JPY"}


# ── Logging — dual output (console + file) ────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

_fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
_fh.setFormatter(_fmt)

_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)

log = logging.getLogger("data_feed_audit")
log.setLevel(logging.DEBUG)
log.addHandler(_fh)
log.addHandler(_sh)
log.propagate = False


# ── Output helpers ────────────────────────────────────────────────────────────

def banner(title: str) -> None:
    log.info("=" * 72)
    log.info(f"  {title}")
    log.info("=" * 72)


def section(title: str) -> None:
    log.info("")
    pad = max(0, 68 - len(title))
    log.info(f"── {title} {'─' * pad}")


def fp(v: Any, decimals: int = 5) -> str:
    """Format a price/float value for display."""
    if v is None:
        return "n/a"
    try:
        f = float(v)
        if np.isnan(f):
            return "NaN"
        return f"{f:.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_5m_cache(symbol: str) -> Optional[pd.DataFrame]:
    """
    Load the 5m candle CSV written by candle_builder.py.
    Normalises column names and types. Returns None if absent or unreadable.
    """
    path = CACHE_DIR / f"{symbol.upper()}_candles.csv"
    if not path.exists():
        log.warning(f"  [{symbol}] Cache file not found: {path}")
        return None
    try:
        df = pd.read_csv(str(path))
        # normalise timestamp column
        ts_col = next(
            (c for c in df.columns if c.strip().lower() in ("timestamp", "time")),
            None,
        )
        if ts_col is None:
            log.warning(f"  [{symbol}] Cache has no timestamp/time column")
            return None
        df = df.rename(columns={ts_col: "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        for c in ("open", "high", "low", "close"):
            if c not in df.columns:
                log.warning(f"  [{symbol}] Cache missing column: {c}")
                return None
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = (
            df.dropna(subset=["timestamp", "open", "high", "low", "close"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        return df if not df.empty else None
    except Exception as exc:
        log.error(f"  [{symbol}] Failed to read cache: {exc}")
        return None


def aggregate_to_tf(df_5m: pd.DataFrame, tf_seconds: int) -> pd.DataFrame:
    """
    Aggregate 5m OHLCV to a higher timeframe using floor(epoch / tf_seconds).
    Mirrors the approach used in TimeframeContext._update_timeframe.
    """
    if df_5m is None or df_5m.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    df = df_5m.copy()
    df["_epoch"]  = df["timestamp"].apply(lambda x: int(x.timestamp()))
    df["_bucket"] = (df["_epoch"] // tf_seconds) * tf_seconds
    agg = (
        df.groupby("_bucket", sort=True)
        .agg(
            open=("open",  "first"),
            high=("high",  "max"),
            low= ("low",   "min"),
            close=("close","last"),
        )
        .reset_index()
    )
    agg["timestamp"] = pd.to_datetime(agg["_bucket"], unit="s", utc=True)
    return (
        agg[["timestamp", "open", "high", "low", "close"]]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def detect_gaps(
    df: pd.DataFrame,
    expected_seconds: int,
    gap_threshold_seconds: int,
) -> List[Dict[str, Any]]:
    """Return list of gap dicts where consecutive candle spacing > threshold."""
    if df is None or len(df) < 2:
        return []
    gaps: List[Dict[str, Any]] = []
    ts_list = df["timestamp"].tolist()
    for i in range(1, len(ts_list)):
        diff_s = (ts_list[i] - ts_list[i - 1]).total_seconds()
        if diff_s > gap_threshold_seconds:
            gaps.append({
                "from":        ts_list[i - 1].isoformat(),
                "to":          ts_list[i].isoformat(),
                "gap_seconds": int(diff_s),
                "gap_bars":    diff_s / expected_seconds,
            })
    return gaps


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Data feed check
# ══════════════════════════════════════════════════════════════════════════════

def audit_data_feeds(
    symbol: str,
    now_utc: datetime,
) -> Dict[str, Optional[pd.DataFrame]]:
    """
    For each timeframe: count, recency, staleness, gaps, last 3 OHLCV.
    Returns {tf_name: DataFrame} for downstream sections.
    """
    section(f"[{symbol}] SECTION 1 — DATA FEED CHECK")

    df_5m = load_5m_cache(symbol)
    if df_5m is None:
        log.info(f"  [{symbol}] No cache data — all timeframes unavailable")
        return {tf: None for tf in TF_SECONDS}

    log.info(
        f"  [{symbol}] 5m cache: {len(df_5m)} rows  "
        f"| from {df_5m['timestamp'].iloc[0].isoformat()}"
        f"  to {df_5m['timestamp'].iloc[-1].isoformat()}"
    )

    tf_dfs: Dict[str, Optional[pd.DataFrame]] = {"5M": df_5m}
    for tf in ("H1", "H4", "D1"):
        tf_dfs[tf] = aggregate_to_tf(df_5m, TF_SECONDS[tf])

    for tf in ("5M", "H1", "H4", "D1"):
        df = tf_dfs[tf]
        log.info("")
        log.info(f"  ── {symbol} / {tf} ──")

        if df is None or df.empty:
            log.info(f"    No data")
            continue

        n         = len(df)
        last_ts   = df["timestamp"].iloc[-1]
        age_s     = (now_utc - last_ts).total_seconds()
        is_stale  = age_s > STALE_THRESHOLDS[tf]
        age_str   = (
            f"STALE — {age_s / 3600:.1f}h old"
            if is_stale
            else f"OK — {age_s / 60:.0f}m old"
        )
        gaps = detect_gaps(df, TF_SECONDS[tf], GAP_THRESHOLDS[tf])

        log.info(f"    Candles available : {n}")
        log.info(f"    Most recent candle: {last_ts.isoformat()}")
        log.info(f"    Staleness check   : {age_str}")
        log.info(f"    Gaps detected     : {len(gaps)}")
        if gaps:
            show = gaps[-5:] if len(gaps) > 5 else gaps
            for g in show:
                log.info(
                    f"      {g['from']} → {g['to']}"
                    f"  ({g['gap_seconds']}s / {g['gap_bars']:.1f} bars missing)"
                )
            if len(gaps) > 5:
                log.info(f"      … {len(gaps) - 5} earlier gaps not shown")

        log.info(f"    Last 3 candles (OHLCV):")
        for _, row in df.tail(3).iterrows():
            log.info(
                f"      {row['timestamp'].isoformat()}"
                f"  O={fp(row['open'])}"
                f"  H={fp(row['high'])}"
                f"  L={fp(row['low'])}"
                f"  C={fp(row['close'])}"
            )

    return tf_dfs


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Indicator accuracy check
# ══════════════════════════════════════════════════════════════════════════════

def audit_indicators(
    symbol: str,
    tf_dfs: Dict[str, Optional[pd.DataFrame]],
) -> None:
    """
    For each timeframe compute and display:
      EMA 8/13/21/50/200 | BB(20,2) | MACD(35/45/30) | RSI(3)

    Uses indicators.py functions directly (same code path the bot uses).
    """
    section(f"[{symbol}] SECTION 2 — INDICATOR VALUES")

    for tf in ("5M", "H1", "H4", "D1"):
        df = tf_dfs.get(tf)
        n  = len(df) if df is not None else 0
        log.info(f"")
        log.info(f"  ── {symbol} / {tf}  ({n} candles) ──")

        if df is None or df.empty or n < 3:
            log.info(f"    Insufficient data for indicators")
            continue

        closes = df["close"].astype(float)

        # ── EMAs ──────────────────────────────────────────────────────────────
        ema_parts = []
        for p in EMA_PERIODS:
            e = _ema_fn(closes, p)
            ema_parts.append(f"EMA{p}={fp(e.iloc[-1])}")
        log.info(f"    {' | '.join(ema_parts)}")

        # ── Bollinger Bands ───────────────────────────────────────────────────
        bb = bollinger_bands(closes, BB_PERIOD, BB_STD)
        std_key   = f"{BB_STD:g}"   # 2.0 → "2"
        mid_col   = f"BB_MID_{BB_PERIOD}"
        upper_col = f"BB_UPPER_{BB_PERIOD}_{std_key}"
        lower_col = f"BB_LOWER_{BB_PERIOD}_{std_key}"
        bb_mid    = fp(bb[mid_col].iloc[-1])   if mid_col   in bb.columns else "n/a"
        bb_upper  = fp(bb[upper_col].iloc[-1]) if upper_col in bb.columns else "n/a"
        bb_lower  = fp(bb[lower_col].iloc[-1]) if lower_col in bb.columns else "n/a"
        bb_note   = f"  [needs {BB_PERIOD}, have {n}]" if n < BB_PERIOD else ""
        log.info(
            f"    BB({BB_PERIOD},{std_key}):  "
            f"lower={bb_lower}  mid={bb_mid}  upper={bb_upper}{bb_note}"
        )

        # ── MACD(35/45/30) ────────────────────────────────────────────────────
        m          = macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        ml_col     = f"MACD_{MACD_FAST}_{MACD_SLOW}"
        sig_col    = f"MACD_SIGNAL_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"
        hist_col   = f"MACD_HIST_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"
        ml_val     = fp(m[ml_col].iloc[-1])    if ml_col   in m.columns else "n/a"
        sig_val    = fp(m[sig_col].iloc[-1])   if sig_col  in m.columns else "n/a"
        hist_val   = fp(m[hist_col].iloc[-1])  if hist_col in m.columns else "n/a"
        macd_note  = f"  [EWM-seeded, needs {MACD_SLOW}+ for stable values]" if n < MACD_SLOW else ""
        log.info(
            f"    MACD({MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}):  "
            f"line={ml_val}  signal={sig_val}  hist={hist_val}{macd_note}"
        )

        # ── RSI(3) ────────────────────────────────────────────────────────────
        r       = rsi(closes, RSI_PERIOD)
        rsi_val = r.iloc[-1] if not r.empty else None
        try:
            rsi_str = f"{float(rsi_val):.2f}"
        except (TypeError, ValueError):
            rsi_str = "n/a"
        log.info(f"    RSI({RSI_PERIOD}): {rsi_str}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — HTF snapshot comparison
# ══════════════════════════════════════════════════════════════════════════════

def _raw_ema_bias(df: Optional[pd.DataFrame], fast: int, slow: int) -> tuple[str, str]:
    """
    Compute bias from raw EMA(fast) vs EMA(slow) on df.
    Returns (bias_str, detail_str).
    """
    if df is None or len(df) < slow:
        n = len(df) if df is not None else 0
        return "NEUTRAL", f"insufficient data ({n} candles, need {slow})"
    closes = df["close"].astype(float)
    ef = float(_ema_fn(closes, fast).iloc[-1])
    es = float(_ema_fn(closes, slow).iloc[-1])
    spread = ef - es
    if   spread > 0: bias = "BULL"
    elif spread < 0: bias = "BEAR"
    else:            bias = "NEUTRAL"
    return bias, f"EMA{fast}={fp(ef)}  EMA{slow}={fp(es)}  spread={fp(spread, 6)}"


def audit_htf_snapshot(
    symbol: str,
    tf_dfs: Dict[str, Optional[pd.DataFrame]],
) -> None:
    """
    1. Replays the 5m cache through TimeframeContext (stateless, pure) to
       simulate the HTF snapshot sentinel.py would have at this moment.
    2. Independently computes raw EMA bias on aggregated H1/H4/D1.
    3. Compares snapshot vs raw — reports AGREE / DISAGREE.

    Note: TimeframeContext tracks H1 + D1 only (no H4).
          H4 comparison is raw-only and flagged accordingly.
    """
    section(f"[{symbol}] SECTION 3 — HTF SNAPSHOT COMPARISON")

    df_5m = tf_dfs.get("5M")
    if df_5m is None or df_5m.empty:
        log.info(f"  [{symbol}] No 5m data — cannot build HTF snapshot")
        return

    # ── Replay 5m candles through TimeframeContext ────────────────────────────
    # TimeframeContext is pure (no I/O); safe to instantiate here.
    tf_ctx   = TimeframeContext(ema_fast=HTF_EMA_FAST, ema_slow=HTF_EMA_SLOW)
    snapshot: Optional[Dict[str, Any]] = None
    dummy_epic = f"CS.D.{symbol}.TODAY.IP"

    for _, row in df_5m.iterrows():
        ts = row["timestamp"]
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bucket_epoch = int(ts.timestamp())
        payload: Dict[str, Any] = {
            "symbol":       symbol,
            "epic":         dummy_epic,
            "timeframe":    "5m",
            "candle": {
                "timestamp": ts,
                "open":  float(row["open"]),
                "high":  float(row["high"]),
                "low":   float(row["low"]),
                "close": float(row["close"]),
            },
            "candle_ts_utc": ts.isoformat(),
            "bucket_epoch":  bucket_epoch,
            "source":        "AUDIT_REPLAY",
        }
        try:
            snapshot = tf_ctx.on_5m_close(symbol, dummy_epic, payload)
        except Exception as exc:
            log.debug(f"  [{symbol}] HTF replay error at {ts}: {exc}")

    if snapshot is None:
        log.info(f"  [{symbol}] HTF replay produced no snapshot (insufficient closed candles)")
        return

    dbg       = snapshot.get("debug", {})
    h1_dbg    = dbg.get("h1", {})
    d1_dbg    = dbg.get("d1", {})
    h1_anchor = dbg.get("h1_anchor", {})
    counts    = dbg.get("counts", {})

    h1_bias_snap = snapshot.get("h1_bias", "NEUTRAL")
    d1_bias_snap = snapshot.get("d1_bias", "NEUTRAL")
    chosen       = snapshot.get("bias",    "NEUTRAL")

    log.info(f"  [{symbol}] TimeframeContext snapshot  "
             f"(EMA{HTF_EMA_FAST}/{HTF_EMA_SLOW}, bias source: {dbg.get('source', '?')})")
    log.info(f"    h1_bias      = {h1_bias_snap}  "
             f"(spread={fp(h1_dbg.get('spread'), 6)}, "
             f"{counts.get('h1_closed', '?')} closed H1 candles)")
    log.info(f"    d1_bias      = {d1_bias_snap}  "
             f"(spread={fp(d1_dbg.get('spread'), 6)}, "
             f"{counts.get('d1_closed', '?')} closed D1 candles)")
    log.info(f"    chosen_bias  = {chosen}")
    log.info(f"    h1_ema8      = {fp(snapshot.get('h1_ema8'))}  "
             f"h1_ema21={fp(snapshot.get('h1_ema21'))}  "
             f"h1_price={fp(snapshot.get('h1_price'))}")
    log.info(f"    h1_anchor_ready   = {h1_anchor.get('ready', False)}")
    log.info(f"    h1_anchor_buy_ok  = {h1_anchor.get('buy_ok',  False)}")
    log.info(f"    h1_anchor_sell_ok = {h1_anchor.get('sell_ok', False)}")

    # ── Raw EMA relationship vs snapshot ─────────────────────────────────────
    log.info(f"")
    log.info(f"  [{symbol}] Raw EMA({HTF_EMA_FAST}/{HTF_EMA_SLOW}) cross-check:")

    for tf_name, snap_bias in (
        ("H1", h1_bias_snap),
        ("H4", None),          # not tracked by TimeframeContext
        ("D1", d1_bias_snap),
    ):
        df_tf = tf_dfs.get(tf_name)
        raw_bias, detail = _raw_ema_bias(df_tf, HTF_EMA_FAST, HTF_EMA_SLOW)

        if snap_bias is None:
            verdict = "not tracked by TimeframeContext (H4 is H1+D1 only)"
        elif raw_bias == snap_bias:
            verdict = f"AGREE  (both {raw_bias})"
        else:
            verdict = f"DISAGREE  snapshot={snap_bias}  raw={raw_bias}"

        log.info(f"    {tf_name}: {detail}  →  {verdict}")

    log.info(f"")
    log.info(f"  NOTE: TimeframeContext closes H1/D1 buckets only from CLOSED 5m candles.")
    log.info(f"        The current in-progress bucket is excluded — matches live bot behaviour.")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — News calendar feed
# ══════════════════════════════════════════════════════════════════════════════

def _load_news_days() -> set:
    """
    Parse NEWS_DAYS from sweep_journal.py without running the full module.
    Returns the set of YYYY-MM-DD strings.
    """
    path = BASE_DIR / "sweep_journal.py"
    if not path.exists():
        return set()
    try:
        spec   = importlib.util.spec_from_file_location("_sj_audit", str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)          # type: ignore[union-attr]
        return set(getattr(module, "NEWS_DAYS", set()))
    except Exception:
        # Fallback: regex on uncommented date literals
        text  = path.read_text(encoding="utf-8")
        dates = re.findall(r'(?<!#\s{0,8})"(\d{4}-\d{2}-\d{2})"', text)
        return set(dates)


def audit_news_calendar() -> None:
    """
    1. Show current NEWS_DAYS state from sweep_journal.py.
    2. Probe ForexFactory JSON endpoint.
    3. Display today's high-impact events (if accessible).
    4. Assess whether the feed can replace the manual calendar.
    """
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    # ── Current NEWS_DAYS ─────────────────────────────────────────────────────
    log.info(f"  Current sweep_journal.NEWS_DAYS (manual calendar):")
    news_days   = _load_news_days()
    active_days = {d for d in news_days if not d.startswith("#")}

    if active_days:
        for d in sorted(active_days):
            marker = "  ← TODAY" if d == today_str else ""
            log.info(f"    {d}{marker}")
    else:
        log.info(f"    (empty set — news day gating is currently disabled)")

    log.info(
        f"  Today ({today_str}) is "
        f"{'a NEWS DAY' if today_str in active_days else 'NOT flagged as a news day'}"
        f" per NEWS_DAYS"
    )

    # ── ForexFactory probe ────────────────────────────────────────────────────
    log.info(f"")
    log.info(f"  Probing ForexFactory calendar: {FF_URL}")

    try:
        resp = requests.get(
            FF_URL,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; audit-script/1.0)"},
        )
        resp.raise_for_status()
        events: List[Dict[str, Any]] = resp.json()

        log.info(f"  HTTP {resp.status_code}  —  {len(events)} total events returned this week")

        # ForexFactory JSON uses "country" not "currency" in some versions; accept both
        def get_currency(ev: Dict[str, Any]) -> str:
            return str(ev.get("currency") or ev.get("country") or "").upper()

        def get_impact(ev: Dict[str, Any]) -> str:
            return str(ev.get("impact") or "").strip().lower()

        def get_date_str(ev: Dict[str, Any]) -> str:
            raw = str(ev.get("date") or "")
            return raw[:10]  # YYYY-MM-DD

        high_all   = [
            e for e in events
            if get_impact(e) == "high" and get_currency(e) in FF_CURRENCIES
        ]
        high_today = [e for e in high_all if get_date_str(e) == today_str]

        log.info(
            f"  High-impact events this week for {FF_CURRENCIES}: {len(high_all)}"
        )
        log.info(f"  High-impact events today ({today_str}): {len(high_today)}")

        if high_today:
            log.info(f"")
            log.info(f"  Today's high-impact events:")
            for ev in sorted(high_today, key=lambda x: x.get("date", "")):
                dt_raw = str(ev.get("date", ""))
                time_s = dt_raw[11:16] if len(dt_raw) >= 16 else "?"
                ccy    = get_currency(ev)
                title  = ev.get("title", "?")
                prev   = ev.get("previous", "")
                fcast  = ev.get("forecast", "")
                actual = ev.get("actual", "")
                extras = "  ".join(
                    f"{k}={v}" for k, v in
                    [("prev", prev), ("forecast", fcast), ("actual", actual)]
                    if v not in (None, "")
                )
                log.info(f"    [{ccy:3s}] {time_s}  {title}" + (f"  — {extras}" if extras else ""))

        if high_all:
            log.info(f"")
            log.info(f"  Full week high-impact schedule ({len(high_all)} events):")
            for ev in sorted(high_all, key=lambda x: x.get("date", "")):
                log.info(
                    f"    [{get_currency(ev):3s}] "
                    f"{str(ev.get('date', ''))[:16]}  "
                    f"{ev.get('title', '?')}"
                )

        # ── Capability assessment ─────────────────────────────────────────────
        log.info(f"")
        log.info(f"  Feed capability assessment:")
        log.info(f"    [OK] Feed is accessible and returns structured JSON")
        log.info(f"    [OK] Can filter by impact='High'")
        log.info(f"    [OK] Can filter by currency (USD / GBP / EUR / JPY)")
        log.info(f"    [OK] Provides event title, datetime, previous, forecast, actual")
        log.info(f"    [OK] Can replace manual NEWS_DAYS with dynamic daily lookup")
        log.info(f"")
        log.info(f"  Extension path:")
        log.info(f"    Replace _is_news_day() in sweep_journal.py with a live fetch.")
        log.info(f"    Cache the weekly JSON to avoid hitting the endpoint on every call.")
        log.info(f"    Filter high-impact events for the pair's affected currencies,")
        log.info(f"    then gate trades within ±N minutes of the event time.")

    except requests.exceptions.ConnectionError:
        log.warning(f"  Connection refused / unreachable — ForexFactory not accessible from this host")
        log.info(f"  Current fallback: manual NEWS_DAYS in sweep_journal.py")
    except requests.exceptions.Timeout:
        log.warning(f"  Request timed out (10s) — ForexFactory did not respond")
    except requests.exceptions.HTTPError as exc:
        log.warning(f"  HTTP error: {exc}")
    except Exception as exc:
        log.error(f"  Unexpected error: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    now_utc = datetime.now(timezone.utc)

    banner(f"DATA FEED AUDIT  —  {now_utc.isoformat()}")
    log.info(f"  Symbols   : {SYMBOLS}")
    log.info(f"  Cache dir : {CACHE_DIR}")
    log.info(f"  Log file  : {LOG_FILE}")
    log.info(f"  Day (UTC) : {now_utc.strftime('%A %Y-%m-%d %H:%M UTC')}")

    if now_utc.weekday() >= 5:
        log.warning(
            "  Running on a WEEKEND — H4/D1 staleness flags are expected "
            "and do not indicate a feed problem"
        )

    # ── Per-symbol diagnostics ────────────────────────────────────────────────
    all_tf_dfs: Dict[str, Dict[str, Optional[pd.DataFrame]]] = {}
    for sym in SYMBOLS:
        banner(f"SYMBOL: {sym}")
        tf_dfs = audit_data_feeds(sym, now_utc)
        all_tf_dfs[sym] = tf_dfs
        audit_indicators(sym, tf_dfs)
        audit_htf_snapshot(sym, tf_dfs)

    # ── News calendar (once, not per symbol) ─────────────────────────────────
    banner("SECTION 4 — NEWS CALENDAR FEED")
    audit_news_calendar()

    banner(f"AUDIT COMPLETE  —  {datetime.now(timezone.utc).isoformat()}")
    log.info(f"  Full output saved to: {LOG_FILE}")


if __name__ == "__main__":
    main()
