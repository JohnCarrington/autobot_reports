#!/usr/bin/env python3
"""
scripts/smoke_strategies.py — instantiate every enabled strategy with the
uniform (symbol, epic, df, pip_size, mid_price, briefing) evaluate()
signature and run one synthetic evaluation per strategy. Exits non-zero
on any exception or unexpected return shape.

Run standalone:           ./scripts/smoke_strategies.py
Run via pre-push hook:    automatic, see scripts/pre-push.hook

Synthetic data: 60 rows of indicator-rich 5M OHLC that avoid arming any
strategy (to keep the test focused on import/init/evaluate plumbing, not
on producing a signal). Any exception from a strategy's evaluate() is
a fail — callers must return a StrategyDecision (even a NONE one) for
every input rather than raising.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from datetime import datetime, timezone

# Ensure /opt/tradingbot is importable when invoked from anywhere.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd


def _synthetic_df(n: int = 60) -> pd.DataFrame:
    """Build a boring, indicator-complete 5M df — flat market, mid-band."""
    base = 13500.0
    ts_end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []
    # Low-amplitude drift so BB width, ATR, RSI etc. are non-degenerate.
    for i in range(n):
        drift = np.sin(i / 6.0) * 2.0
        o = base + drift
        c = base + drift + np.cos(i / 4.0) * 0.8
        h = max(o, c) + 1.2
        l = min(o, c) - 1.2
        ts = ts_end - pd.Timedelta(minutes=5 * (n - 1 - i))
        rows.append({
            "timestamp": ts.isoformat(),
            "open": o, "high": h, "low": l, "close": c,
        })
    df = pd.DataFrame(rows)

    closes = df["close"]
    df["BB_MID_20"] = closes.rolling(20, min_periods=1).mean()
    std = closes.rolling(20, min_periods=1).std().fillna(0.5)
    df["BB_UPPER_20_2"] = df["BB_MID_20"] + 2 * std
    df["BB_LOWER_20_2"] = df["BB_MID_20"] - 2 * std
    df["BB_WIDTH_20_2"] = df["BB_UPPER_20_2"] - df["BB_LOWER_20_2"]
    df["BB_WIDTH_DELTA_20_2"] = df["BB_WIDTH_20_2"].diff().fillna(0)
    df["BB_WIDTH_EXPANDING_20_2"] = df["BB_WIDTH_DELTA_20_2"] > 0
    df["BB_WIDTH_CONTRACTING_20_2"] = df["BB_WIDTH_DELTA_20_2"] < 0
    df["BB_WIDTH_FLAT_20_2"] = df["BB_WIDTH_DELTA_20_2"].abs() < 0.1
    df["BB_UPPER_SLOPE_20_2"] = df["BB_UPPER_20_2"].diff().fillna(0)
    df["BB_LOWER_SLOPE_20_2"] = df["BB_LOWER_20_2"].diff().fillna(0)
    df["BB_MID_SLOPE_20"] = df["BB_MID_20"].diff().fillna(0)
    df["BB_UPPER_SLOPE_20_2_DELTA"] = df["BB_UPPER_SLOPE_20_2"].diff().fillna(0)
    df["BB_LOWER_SLOPE_20_2_DELTA"] = df["BB_LOWER_SLOPE_20_2"].diff().fillna(0)

    # RSI3
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_g = gain.ewm(alpha=1 / 3, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / 3, adjust=False).mean()
    rs = avg_g / avg_l.replace(0, np.nan)
    df["RSI_3"] = (100 - 100 / (1 + rs)).fillna(50.0)
    df["RSI_3_DELTA"] = df["RSI_3"].diff().fillna(0)

    # MACD 35/45/30
    fast = closes.ewm(span=35, adjust=False).mean()
    slow = closes.ewm(span=45, adjust=False).mean()
    line = fast - slow
    sig = line.ewm(span=30, adjust=False).mean()
    df["MACD_35_45"] = line
    df["MACD_SIGNAL_35_45_30"] = sig
    df["MACD_HIST_35_45_30"] = line - sig
    df["MACD_35_45_DELTA"] = line.diff().fillna(0)
    df["MACD_HIST_35_45_30_DELTA"] = df["MACD_HIST_35_45_30"].diff().fillna(0)
    df["MACD_HIST_35_45_30_DECEL2"] = df["MACD_HIST_35_45_30_DELTA"].diff().fillna(0)
    df["MACD_HIST_35_45_30_DECREASING2"] = df["MACD_HIST_35_45_30_DELTA"] < 0

    # ATR14
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - closes.shift(1)).abs(),
                    (df["low"] - closes.shift(1)).abs()], axis=1).max(axis=1)
    df["ATR_14"] = tr.rolling(14, min_periods=1).mean()

    # Aroon 14
    df["AROON_UP_14"] = 50.0
    df["AROON_DOWN_14"] = 50.0

    # EMAs
    df["EMA_8"] = closes.ewm(span=8, adjust=False).mean()
    df["EMA_13"] = closes.ewm(span=13, adjust=False).mean()
    df["EMA_21"] = closes.ewm(span=21, adjust=False).mean()
    df["EMA_50"] = closes.ewm(span=50, adjust=False).mean()
    df["EMA_50_SLOPE"] = df["EMA_50"].diff().fillna(0)
    df["EMA_200"] = closes.ewm(span=200, adjust=False).mean()
    return df


def _synthetic_briefing() -> dict:
    return {
        "symbol": "GBPUSD",
        "session": "London",
        "session_bias": "BULLISH",
        "daily_bias": "BULLISH",
        "bias_confidence": 0.6,
        "bias_change": False,
        "_prev_session_bias": None,
        "bb_upper": 13520.0,
        "bb_lower": 13480.0,
        "key_levels": {"resistance": [13520.0], "support": [13480.0]},
        "major_levels": {"resistance": [], "support": []},
        "liquidity_pools": {"buy_side": [13522.0], "sell_side": [13478.0]},
        "no_trade_zones": [],
        "trading_plans": [],
        "news_events": [],
    }


# (module, class, label). All share evaluate(sym, epic, df, pip_size, mid, briefing).
STRATEGY_TARGETS = [
    ("reversal_sweep",          "ReversalSweepStrategy",         "REVERSAL_SWEEP"),
    ("continuation_sweep",      "ContinuationSweepStrategy",     "CONTINUATION_SWEEP"),
    ("exhaustion_reversal",     "ExhaustionReversalStrategy",    "EXHAUSTION_REVERSAL"),
    ("session_impulse_breakout","SessionImpulseBreakoutStrategy","SESSION_IMPULSE_BREAKOUT"),
    ("ema_pullback",            "EmaPullbackStrategy",           "EMA_PULLBACK"),
    ("london_open_pullback",    "LondonOpenPullbackStrategy",    "LONDON_PULLBACK"),
    # Full-search portfolio pilot (added 2026-05-10): RSI/MACD extreme fade.
    # Synthetic flat-market data does not breach RSI(14)>69 / RSI(14)<35 /
    # MACD<-6 thresholds, so these will return signal=NONE — confirming
    # only that import + init + evaluate plumbing is intact.
    ("rsi_extreme_fade",        "RsiExtremeFadeStrategy",        "RSI_EXTREME_FADE"),
    ("macd_extreme_fade",       "MacdExtremeFadeStrategy",       "MACD_EXTREME_FADE"),
    # BB Pattern 2 fade pilot (added 2026-05-10): synthetic flat-market data
    # never produces an isolated wick-only pierce, so this returns NONE —
    # confirming only that import + init + evaluate plumbing is intact.
    ("bb_pattern2_fade",        "BBPattern2FadeStrategy",        "BB_PATTERN2_FADE"),
]


def _call_strategy(strat, symbol, epic, df, pip_size, mid_price, briefing):
    """Invoke evaluate() adapting to a couple of known signatures."""
    try:
        return strat.evaluate(symbol, epic, df, pip_size, mid_price, briefing)
    except TypeError:
        # NewsStrategy has no briefing arg.
        return strat.evaluate(symbol, epic, df, pip_size, mid_price)


def main() -> int:
    df = _synthetic_df()
    briefing = _synthetic_briefing()
    symbol = "GBPUSD"
    epic = "CS.D.GBPUSD.TODAY.IP"
    pip_size = 1.0
    mid_price = float(df["close"].iloc[-1])

    results = []   # (label, status, note)
    for mod_name, class_name, label in STRATEGY_TARGETS:
        try:
            mod = __import__(mod_name)
        except Exception as e:
            results.append((label, "IMPORT_FAIL", f"{type(e).__name__}: {e}"))
            continue
        try:
            cls = getattr(mod, class_name)
        except AttributeError as e:
            results.append((label, "CLASS_MISSING", str(e)))
            continue
        try:
            inst = cls()
        except Exception as e:
            results.append((label, "INIT_FAIL", f"{type(e).__name__}: {e}"))
            continue
        try:
            dec = _call_strategy(inst, symbol, epic, df, pip_size, mid_price, briefing)
        except Exception as e:
            results.append((label, "EVAL_RAISED", f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=3)))
            continue

        # Validate shape: must have .signal attribute
        sig = getattr(dec, "signal", None)
        if sig is None:
            results.append((label, "BAD_RETURN", f"evaluate returned {type(dec).__name__} without .signal"))
            continue
        results.append((label, "OK", f"signal={sig} reason={getattr(dec,'reason',None)}"))

    # Also cover NewsStrategy which has a different signature:
    #   evaluate(symbol, epic, mid, bid, ask, ts, ppp, *, is_blackout=, blackout_reason=)
    # Synthesise bid/ask around mid_price and a current timestamp; ppp=1.0
    # is a smoke-test placeholder (not a production value).
    try:
        import time as _time_smoke
        from news_strategy import NewsStrategy
        inst = NewsStrategy()
        _bid = mid_price - 0.5
        _ask = mid_price + 0.5
        _ts = _time_smoke.time()
        _ppp = 1.0
        dec = inst.evaluate(symbol, epic, mid_price, _bid, _ask, _ts, _ppp)
        sig = getattr(dec, "signal", None)
        if sig is None:
            results.append(("NEWS_STRATEGY", "BAD_RETURN", f"returned {type(dec).__name__} without .signal"))
        else:
            results.append(("NEWS_STRATEGY", "OK", f"signal={sig} reason={getattr(dec,'reason',None)}"))
    except Exception as e:
        results.append(("NEWS_STRATEGY", "EVAL_RAISED",
                        f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=3)))

    # FIFTY_PIP_BREAKOUT (added 2026-05-10) — tick-driven entry like
    # NEWS_STRATEGY, no evaluate() per uniform sig. Smoke covers import +
    # tick_update plumbing + configs_summary; synthetic single-tick + empty
    # df guarantees no fire, so signal=None is the expected OK shape.
    try:
        import time as _time_fpb
        import fifty_pip_breakout as _fpb_mod
        _fpb_summary = _fpb_mod.configs_summary()
        assert isinstance(_fpb_summary, list) and _fpb_summary, "configs_summary empty"
        _fpb_res = _fpb_mod.tick_update(
            symbol="USDCAD", epic="CS.D.USDCAD.TODAY.IP",
            mid=13500.0, bid=13499.5, ask=13500.5,
            ts=_time_fpb.time(), ppp=1.0,
            df_5m=df,  # synthetic 5m frame (anchor window not populated)
            has_open_for_mode_fn=lambda e, m: False,
        )
        if _fpb_res is None:
            results.append(("FIFTY_PIP_BREAKOUT", "OK",
                            f"signal=NONE configs={len(_fpb_summary)}"))
        else:
            # Unexpected for synthetic — but treat as OK if shape sane.
            sig = _fpb_res.get("signal")
            if sig in ("BUY", "SELL"):
                results.append(("FIFTY_PIP_BREAKOUT", "OK",
                                f"signal={sig} reason={_fpb_res.get('reason')}"))
            else:
                results.append(("FIFTY_PIP_BREAKOUT", "BAD_RETURN",
                                f"tick_update returned {_fpb_res!r}"))
    except Exception as e:
        results.append(("FIFTY_PIP_BREAKOUT", "EVAL_RAISED",
                        f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=3)))

    # GBPUSD_BB_REV_PAT (V + Arc) — uses a different evaluate signature
    # (symbol, epic, ts, bars, closes_ind, has_open_long, has_open_short).
    # Returns None on no-fire (the synthetic flat market never arms a
    # pattern), so we treat None as OK — only an exception is a fail.
    try:
        import os as _os_smoke
        _os_smoke.environ["GBPUSD_BB_REVERSAL_PATTERNS_ENABLED"] = "1"
        from gbpusd_bb_reversal_patterns import (
            GbpUsdBBReversalPatternsStrategy,
            Bar as _BRPBar,
        )
        from datetime import datetime as _dt_smoke, timezone as _tz_smoke
        inst = GbpUsdBBReversalPatternsStrategy()
        _bars = [
            _BRPBar(
                timestamp=_dt_smoke.fromisoformat(str(row["timestamp"])).astimezone(_tz_smoke.utc),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
            )
            for _, row in df.iterrows()
        ]
        _closes = [float(c) for c in df["close"].tolist()]
        dec = inst.evaluate(
            symbol=symbol, epic=epic, ts=_bars[-1].timestamp,
            bars=_bars, closes_ind=_closes,
        )
        # None is acceptable — synthetic flat data should not arm.
        if dec is None or getattr(dec, "signal", None) is not None:
            results.append(("BB_REV_PAT", "OK",
                            f"signal={getattr(dec,'signal','NONE')}"))
        else:
            results.append(("BB_REV_PAT", "BAD_RETURN",
                            f"returned {type(dec).__name__} without .signal"))
    except Exception as e:
        results.append(("BB_REV_PAT", "EVAL_RAISED",
                        f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=3)))

    # Report
    fails = [r for r in results if r[1] != "OK"]
    print(f"\nstrategy smoke test — {len(results)} strategies, "
          f"{len(results) - len(fails)} OK, {len(fails)} FAIL\n")
    for label, status, note in results:
        marker = "✓" if status == "OK" else "✗"
        print(f"  {marker} {label:28s} {status:14s} {note.splitlines()[0][:120]}")
    if fails:
        print("\nFailures:")
        for label, status, note in fails:
            print(f"\n--- {label} ({status}) ---")
            print(note)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
