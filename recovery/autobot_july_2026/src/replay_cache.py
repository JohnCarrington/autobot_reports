#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
replay_cache.py — replay cached 5m candles through strategy_logic (NO live trading)

PRE-CHECK (House rules / Continual Errors / Contracts):
- #24 / #104: NO price normalization. Prices remain in native IG points.
- #106: StrategyDecision.sl/tp are pip distances (not absolute prices).
- #111: Use canonical pip-size mapping when converting points<->pips.
- This tool is OFFLINE / replay only. It MUST NOT place orders.

What this does:
- Loads a candle CSV with columns: timestamp, open, high, low, close
- Replays candle-by-candle into strategy_logic.evaluate_signals(...)
- Optionally runs a simple paper-trade simulator:
    - max 1 open trade at a time (per symbol)
    - entry at candle close (mid proxy)
    - SL/TP distances from decision.sl/decision.tp (pips)
    - exits evaluated using next candles' high/low (intrabar)
"""

import argparse
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

import strategy_logic


logger = logging.getLogger("AutoBot")


# ---------------------------
# IO
# ---------------------------
def load_cache(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "timestamp" not in df.columns:
        raise ValueError("CSV missing 'timestamp' column")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    for c in ["open", "high", "low", "close"]:
        if c not in df.columns:
            raise ValueError(f"CSV missing '{c}' column")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df


# ---------------------------
# Strategy call adapter
# ---------------------------
def call_evaluate_signals(symbol: str, df_slice: pd.DataFrame, mid: float, has_open_position: bool):
    fn = strategy_logic.evaluate_signals
    sig = inspect.signature(fn)
    params = sig.parameters

    kwargs: Dict[str, Any] = {}
    if "symbol" in params:
        kwargs["symbol"] = symbol
    if "df" in params:
        kwargs["df"] = df_slice
    if "mid_price" in params:
        kwargs["mid_price"] = float(mid)
    if "has_open_position" in params:
        kwargs["has_open_position"] = bool(has_open_position)

    # Optional supported inputs (keep None unless you wire snapshots)
    if "htf_snapshot" in params:
        kwargs["htf_snapshot"] = None
    if "levels_snapshot" in params:
        kwargs["levels_snapshot"] = None
    if "config" in params:
        kwargs["config"] = None

    return fn(**kwargs)


def safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


# ---------------------------
# Indicator enrichment
# ---------------------------
def _has_bb_columns(df: pd.DataFrame) -> bool:
    cols = list(df.columns)
    return any(c.startswith("BB_LOWER_") for c in cols) and any(c.startswith("BB_UPPER_") for c in cols)


def enrich_indicators(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    """
    Prefer indicators.add_indicators() because it produces BB_* columns used by the LS playbook.
    Fall back to strategy_logic.compute_indicators() if needed.
    """
    # 1) indicators.add_indicators(df)
    try:
        import indicators  # type: ignore

        if hasattr(indicators, "add_indicators"):
            out = indicators.add_indicators(df.copy())
            if _has_bb_columns(out):
                return out, "indicators.add_indicators"
            # still return it, but mark as partial
            return out, "indicators.add_indicators(partial)"
    except Exception as e:
        logger.debug("Indicator enrich via indicators.add_indicators failed: %s", e, exc_info=True)

    # 2) indicators.calculate_indicators(df) (older naming)
    try:
        import indicators  # type: ignore

        if hasattr(indicators, "calculate_indicators"):
            out = indicators.calculate_indicators(df.copy())  # type: ignore
            if _has_bb_columns(out):
                return out, "indicators.calculate_indicators"
            return out, "indicators.calculate_indicators(partial)"
    except Exception as e:
        logger.debug("Indicator enrich via indicators.calculate_indicators failed: %s", e, exc_info=True)

    # 3) strategy_logic.compute_indicators(df) (may NOT produce BB_* columns)
    if hasattr(strategy_logic, "compute_indicators"):
        try:
            out = strategy_logic.compute_indicators(df.copy())  # type: ignore
            return out, "strategy_logic.compute_indicators"
        except Exception as e:
            logger.debug("Indicator enrich via strategy_logic.compute_indicators failed: %s", e, exc_info=True)

    return df, "none"


# ---------------------------
# Paper trading
# ---------------------------
@dataclass
class PaperTrade:
    direction: str  # BUY/SELL
    entry_ts: pd.Timestamp
    entry: float
    sl_pips: float
    tp_pips: float
    stop: float
    limit: float


def _pip_size_points(symbol: str) -> float:
    # Prefer canonical mapping from strategy_logic if present
    ps = None
    try:
        ps = getattr(strategy_logic, "PIP_SIZES_POINTS_PER_PIP", {}).get(symbol.upper())
    except Exception:
        ps = None
    if ps is None:
        # Safe fallback; you can extend if needed
        if symbol.upper() == "EURUSD":
            return 0.1
        return 1.0
    return float(ps)


def _exit_on_candle(trade: PaperTrade, row: pd.Series) -> Optional[Tuple[float, str]]:
    """
    Returns (exit_price, exit_reason) if stop or limit is hit on this candle; else None.
    Conservative ordering: if both hit in same candle, assume STOP first.
    """
    high = float(row["high"])
    low = float(row["low"])

    if trade.direction == "BUY":
        hit_stop = low <= trade.stop
        hit_tp = high >= trade.limit
        if hit_stop and hit_tp:
            return trade.stop, "SL_and_TP_same_candle_assume_SL"
        if hit_stop:
            return trade.stop, "SL"
        if hit_tp:
            return trade.limit, "TP"
        return None

    # SELL
    hit_stop = high >= trade.stop
    hit_tp = low <= trade.limit
    if hit_stop and hit_tp:
        return trade.stop, "SL_and_TP_same_candle_assume_SL"
    if hit_stop:
        return trade.stop, "SL"
    if hit_tp:
        return trade.limit, "TP"
    return None


def _pnl_pips(trade: PaperTrade, exit_price: float, pip_size_points: float) -> float:
    pts = (exit_price - trade.entry)
    if trade.direction == "SELL":
        pts = -pts
    return float(pts) / float(pip_size_points)


# ---------------------------
# Main
# ---------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, help="e.g. GBPUSD")
    ap.add_argument("--csv", required=True, help="e.g. /opt/tradingbot/cache/GBPUSD_candles.csv")
    ap.add_argument("--warmup", type=int, default=50, help="candles before allowing signals (default 50)")
    ap.add_argument("--print-none", action="store_true", help="print one-line NONE diagnostics when reason changes")
    ap.add_argument("--paper", action="store_true", help="simulate 1 open trade at a time; compute PnL in pips")
    ap.add_argument("--no-enrich", action="store_true", help="do not add indicators; pass raw OHLC only")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    symbol = args.symbol.strip().upper()
    df_all = load_cache(args.csv)

    print(f"Using strategy_logic.evaluate_signals signature: {inspect.signature(strategy_logic.evaluate_signals)}")

    pip_size = _pip_size_points(symbol)
    print(f"Pip size (points per pip) for {symbol}: {pip_size}")

    # Enrich once up-front (fast + consistent)
    if not args.no_enrich:
        logger.info("Enriching indicators …")
        df_all, method = enrich_indicators(df_all)
        logger.info("Indicator enrichment method: %s", method)

    hits: List[Tuple[pd.Timestamp, str, str, Any, Any, Any]] = []
    last_reason = None

    open_trade: Optional[PaperTrade] = None
    closed_trades: List[float] = []  # pnl pips per trade
    wins = losses = flats = 0

    for i in range(len(df_all)):
        df_slice = df_all.iloc[: i + 1].copy()
        if len(df_slice) < args.warmup:
            continue

        row = df_slice.iloc[-1]
        ts = row["timestamp"]
        mid = float(row["close"])  # single evaluation per candle (close-as-mid proxy)

        # Paper exit check (evaluate exits using this candle AFTER it exists)
        if args.paper and open_trade is not None:
            exit_hit = _exit_on_candle(open_trade, row)
            if exit_hit is not None:
                exit_price, exit_reason = exit_hit
                pnl = _pnl_pips(open_trade, exit_price, pip_size)
                closed_trades.append(pnl)
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                else:
                    flats += 1
                open_trade = None

        decision = call_evaluate_signals(
            symbol=symbol,
            df_slice=df_slice,
            mid=mid,
            has_open_position=(open_trade is not None),
        )

        sig = (safe_get(decision, "signal", "NONE") or "NONE").upper()
        reason = safe_get(decision, "reason", "") or ""
        regime = safe_get(decision, "regime", "") or ""
        entry = safe_get(decision, "entry", None)
        sl = safe_get(decision, "sl", None)
        tp = safe_get(decision, "tp", None)
        debug = safe_get(decision, "debug", None)

        if sig != "NONE":
            hits.append((ts, sig, reason, entry, sl, tp))
            print(f"{ts}  {symbol}  SIGNAL={sig}  entry={entry}  sl={sl}  tp={tp}  reason={reason}")

            # Paper entry (1 trade at a time)
            if args.paper and open_trade is None and sig in ("BUY", "SELL"):
                # Require sl/tp pip distances
                try:
                    sl_pips = float(sl)
                    tp_pips = float(tp)
                except Exception:
                    sl_pips = tp_pips = 0.0

                if sl_pips > 0 and tp_pips > 0:
                    entry_px = float(entry) if entry is not None else mid
                    sl_points = sl_pips * pip_size
                    tp_points = tp_pips * pip_size

                    if sig == "BUY":
                        stop = entry_px - sl_points
                        limit = entry_px + tp_points
                    else:
                        stop = entry_px + sl_points
                        limit = entry_px - tp_points

                    open_trade = PaperTrade(
                        direction=sig,
                        entry_ts=ts,
                        entry=entry_px,
                        sl_pips=sl_pips,
                        tp_pips=tp_pips,
                        stop=stop,
                        limit=limit,
                    )
        elif args.print_none:
            if reason != last_reason:
                last_reason = reason
                dbg = ""
                if isinstance(debug, dict) and debug:
                    keys = list(debug.keys())[:6]
                    dbg = " | debug: " + ", ".join(f"{k}={debug.get(k)}" for k in keys)
                print(f"{ts}  {symbol}  NONE  regime={regime}  reason={reason}{dbg}")

    # If trade still open at end, close at last close for reporting
    if args.paper and open_trade is not None:
        last_close = float(df_all.iloc[-1]["close"])
        pnl = _pnl_pips(open_trade, last_close, pip_size)
        closed_trades.append(pnl)
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
        else:
            flats += 1
        open_trade = None

    print("\n--- SUMMARY ---")
    print(f"candles: {len(df_all)} | warmup: {args.warmup} | signals: {len(hits)}")

    if args.paper:
        n = len(closed_trades)
        total = float(sum(closed_trades)) if n else 0.0
        avg = (total / n) if n else 0.0
        winpct = (100.0 * wins / n) if n else 0.0
        print(f"paper trades opened: {n} | closed: {n} | still open: 0")
        print(f"total pnl: {total:.2f} pips | avg/trade: {avg:.2f} pips | win%: {winpct:.1f}%")
        print(f"wins: {wins} | losses: {losses} | flats: {flats}")

    if hits:
        print("first/last signal:")
        print("  first:", hits[0][0], hits[0][1], hits[0][2])
        print("  last :", hits[-1][0], hits[-1][1], hits[-1][2])


if __name__ == "__main__":
    main()
