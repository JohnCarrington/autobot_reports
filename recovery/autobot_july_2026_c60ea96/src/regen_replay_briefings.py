#!/usr/bin/env python3
"""
Generate briefings for GBPUSD last 7 trading days using the current
production prompt against historical candle data.
Output: data/briefings_replay/briefing_GBPUSD_{date}_{session}.json
"""

import sys, os, json, time, logging, requests
sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env")

import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("regen_replay")

from morning_briefing import (
    SYSTEM_PROMPT, ANTHROPIC_URL, ANTHROPIC_MODEL,
    _h1_momentum_summary, _ema_alignment_summary,
    _emas_from_closes, _macd_hist_from_closes,
    _POINTS_PER_PIP, _derive_session_bias_from_h1,
    _build_user_message,
)
from indicators import add_indicators, IndicatorsConfig

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUT_DIR = Path("/opt/tradingbot/data/briefings_replay")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAIR = "GBPUSD"
DATES = ["2026-04-02", "2026-04-03", "2026-04-06", "2026-04-07", "2026-04-08"]
SESSIONS = ["London", "Mid-session", "NY"]

SESSIONS_UTC = {
    "London":      {"gmt": (6, 30), "bst": (5, 30)},
    "Mid-session": {"gmt": (10, 45), "bst": (9, 45)},
    "NY":          {"gmt": (13, 0),  "bst": (12, 0)},
}

IND_CFG = IndicatorsConfig(
    ema_period=50, bb_period=20, bb_std=2.0,
    macd_fast=35, macd_slow=45, macd_signal=30, aroon_period=14,
)


def _is_bst(date_str: str) -> bool:
    m, d = int(date_str.split("-")[1]), int(date_str.split("-")[2])
    return m >= 4 or (m == 3 and d >= 29)


def load_candles(pair: str, date: str) -> pd.DataFrame:
    """Load 5M candles from JSON cache or CSV."""
    p = Path(f"cache/test_candles_{pair}_{date}.json")
    if p.exists():
        with open(p) as f:
            raw = json.load(f)
        if raw:
            df = pd.DataFrame(raw)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            return df.sort_values("timestamp").reset_index(drop=True)

    csv_p = Path(f"data/candles/{pair}/{date}.csv")
    if csv_p.exists():
        df = pd.read_csv(csv_p, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"])
        return df.sort_values("timestamp").reset_index(drop=True)

    return pd.DataFrame()


def aggregate_h1(df_5m: pd.DataFrame, before_ts: datetime) -> list:
    df = df_5m[df_5m["timestamp"] < before_ts].copy()
    if len(df) < 12:
        return []
    df["hour"] = df["timestamp"].dt.floor("h")
    grouped = df.groupby("hour").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        count=("close", "count"),
    ).reset_index()
    grouped = grouped[grouped["count"] >= 10]
    candles = []
    for _, r in grouped.iterrows():
        candles.append({
            "time": str(r["hour"]),
            "open": round(float(r["open"]), 5),
            "high": round(float(r["high"]), 5),
            "low": round(float(r["low"]), 5),
            "close": round(float(r["close"]), 5),
        })
    return candles[-20:]


def build_data_package(pair, date, session, df_all, briefing_ts, prev_briefing=None):
    sym = pair.upper()
    ppp = _POINTS_PER_PIP.get(sym, 1.0)

    pre = df_all[df_all["timestamp"] <= briefing_ts]
    if len(pre) < 20:
        return None

    current_price = round(float(pre.iloc[-1]["close"]), 5)

    # Enrich with indicators
    try:
        pre_ind = add_indicators(pre[["timestamp", "open", "high", "low", "close"]].copy(), IND_CFG)
    except Exception:
        pre_ind = pre

    ema_5m = {}
    for p in (8, 13, 21, 50, 200):
        col = f"EMA_{p}"
        if col in pre_ind.columns and pd.notna(pre_ind[col].iloc[-1]):
            ema_5m[str(p)] = round(float(pre_ind[col].iloc[-1]), 5)

    h1_candles = aggregate_h1(df_all, briefing_ts)
    h1_closes = [float(c["close"]) for c in h1_candles]
    ema_h1 = _emas_from_closes(h1_closes)
    macd_h1_hist = _macd_hist_from_closes(h1_closes)
    h1_momentum = _h1_momentum_summary(h1_candles)
    ema_alignment = _ema_alignment_summary(current_price, ema_h1)

    bb_upper = bb_lower = None
    if len(h1_closes) >= 20:
        w = h1_closes[-20:]
        sma = sum(w) / 20
        std = (sum((x - sma) ** 2 for x in w) / 20) ** 0.5
        bb_upper = round(sma + 2 * std, 5)
        bb_lower = round(sma - 2 * std, 5)

    ema200 = ema_h1.get("200")
    ema50 = ema_h1.get("50")
    price_vs_200 = round((current_price - float(ema200)) / ppp, 1) if ema200 else None
    price_vs_50 = round((current_price - float(ema50)) / ppp, 1) if ema50 else None
    ema_trend = "NEUTRAL"
    if ema50 and ema200:
        diff = (float(ema50) - float(ema200)) / ppp
        if diff > 5:
            ema_trend = "BULLISH"
        elif diff < -5:
            ema_trend = "BEARISH"

    prev_bias = prev_briefing.get("session_bias") if prev_briefing else None

    # USD proxy from USDJPY
    usd_proxy_bias = usd_proxy_pips = None
    jpy_df = load_candles("USDJPY", date)
    if not jpy_df.empty and len(jpy_df) >= 72:
        jpre = jpy_df[jpy_df["timestamp"] <= briefing_ts]
        if len(jpre) >= 72:
            jh1 = []
            jtail = jpre.tail(72)
            for i in range(0, len(jtail), 12):
                block = jtail.iloc[i:i + 12]
                if len(block) >= 10:
                    jh1.append(float(block.iloc[-1]["close"]))
            if len(jh1) >= 2:
                last6 = jh1[-6:]
                jpy_move = last6[-1] - last6[0]
                usd_proxy_pips = round(jpy_move, 1)
                if jpy_move > 5:
                    usd_proxy_bias = "USD_STRONG"
                elif jpy_move < -5:
                    usd_proxy_bias = "USD_WEAK"
                else:
                    usd_proxy_bias = "USD_NEUTRAL"

    return {
        "symbol": sym,
        "current_price": current_price,
        "session": session,
        "briefing_date": date,
        "briefing_time_utc": briefing_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "h1_candles": h1_candles,
        "ema_5m": ema_5m,
        "ema_h1": ema_h1,
        "h1_ema_values": {k: v for k, v in ema_h1.items() if k in ("8", "13", "21", "50")},
        "macd_h1_hist": macd_h1_hist,
        "h1_momentum_summary": h1_momentum,
        "ema_alignment": ema_alignment,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "price_vs_h1_ema200_pips": price_vs_200,
        "price_vs_h1_ema50_pips": price_vs_50,
        "h1_ema_trend": ema_trend,
        "prev_session_bias": prev_bias,
        "prev_session_actual_direction": None,
        "prev_session_pip_move": None,
        "usd_proxy_bias": usd_proxy_bias,
        "usd_proxy_pips": usd_proxy_pips,
        "news_events": [],
        "recent_signals": [],
        "recent_accuracy": [],
        "accuracy_last_5": None,
    }


def call_api(sym, session, pkg):
    user_msg = _build_user_message(sym, session, pkg)

    for attempt in range(2):
        try:
            resp = requests.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 4096,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_msg}],
                },
                timeout=120,
            )
            resp.raise_for_status()
            body = resp.json()
            text = body["content"][0]["text"].strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()
            briefing = json.loads(text)

            if not briefing.get("session_bias"):
                derived = _derive_session_bias_from_h1(pkg)
                if derived:
                    briefing["session_bias"] = derived
                    logger.warning("  session_bias missing — derived %s from H1", derived)
                elif str(briefing.get("daily_bias", "")).upper() in ("BULLISH", "BEARISH"):
                    briefing["session_bias"] = briefing["daily_bias"]

            return briefing
        except Exception as e:
            logger.warning("  attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(5)
    return None


def main():
    print("=" * 70)
    print("  Re-generating GBPUSD briefings for replay")
    print(f"  Dates: {', '.join(DATES)}")
    print(f"  Sessions: {', '.join(SESSIONS)}")
    print(f"  Output: {OUT_DIR}")
    print(f"  Model: {ANTHROPIC_MODEL}")
    print("=" * 70)

    # Pre-load all candle data across dates for continuity
    all_candles = pd.DataFrame()
    for date in DATES:
        df = load_candles(PAIR, date)
        if not df.empty:
            all_candles = pd.concat([all_candles, df], ignore_index=True)
    all_candles = all_candles.sort_values("timestamp").reset_index(drop=True)
    print(f"\n  Total 5M candles loaded: {len(all_candles)}")

    total_calls = 0
    total_success = 0
    prev_briefing = None

    for date in DATES:
        bst = _is_bst(date)
        day_candles = all_candles[all_candles["timestamp"].dt.strftime("%Y-%m-%d") == date]
        if len(day_candles) < 20:
            logger.info("SKIP %s (only %d candles)", date, len(day_candles))
            continue

        for sess in SESSIONS:
            out_file = OUT_DIR / f"briefing_{PAIR}_{date}_{sess}.json"
            if out_file.exists():
                prev_briefing = json.load(open(out_file))
                logger.info("SKIP %s %s (already exists)", date, sess)
                continue

            times = SESSIONS_UTC[sess]
            t = times["bst"] if bst else times["gmt"]
            y, m, d = map(int, date.split("-"))
            briefing_ts = datetime(y, m, d, t[0], t[1], tzinfo=timezone.utc)

            # Use all candles up to briefing time for maximum context
            pkg = build_data_package(PAIR, date, sess, all_candles, briefing_ts, prev_briefing)
            if pkg is None:
                logger.warning("SKIP %s %s (insufficient data)", date, sess)
                continue

            total_calls += 1
            logger.info("CALL [%d] %s %s (price=%.1f, H1 candles=%d)...",
                         total_calls, date, sess, pkg["current_price"], len(pkg["h1_candles"]))
            briefing = call_api(PAIR, sess, pkg)

            if briefing:
                total_success += 1
                with open(out_file, "w") as f:
                    json.dump(briefing, f, indent=2)
                sb = briefing.get("session_bias", "?")
                conf = briefing.get("bias_confidence", 0)
                logger.info("  -> session_bias=%s conf=%.2f", sb, conf)
                prev_briefing = briefing
            else:
                logger.error("  -> FAILED")

            time.sleep(2)

    print(f"\nDone: {total_success}/{total_calls} successful API calls")
    print(f"Briefings saved to {OUT_DIR}")

    # Show summary
    print(f"\n  {'Date':>12} {'Session':>14} {'Bias':>10} {'Conf':>6} {'Expect':>15}")
    print(f"  {'-'*60}")
    for date in DATES:
        for sess in SESSIONS:
            p = OUT_DIR / f"briefing_{PAIR}_{date}_{sess}.json"
            if p.exists():
                b = json.load(open(p))
                print(f"  {date:>12} {sess:>14} {b.get('session_bias','?'):>10} "
                      f"{b.get('bias_confidence',0):>5.2f} {b.get('session_expectation','?'):>15}")


if __name__ == "__main__":
    main()
