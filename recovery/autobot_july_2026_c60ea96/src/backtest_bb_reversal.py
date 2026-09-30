"""Replay today's REST-reconciled GBPUSD cache through BBReversalStrategy
and simulate full trade lifecycle (entry, BE, MACD exit, time exit, SL, TP).

Does NOT place live trades — pure off-line simulation.
"""
import os
import sys
import logging
import pandas as pd

h = logging.StreamHandler(sys.stdout)
h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger("BBReversal").addHandler(h)
logging.getLogger("BBReversal").setLevel(logging.INFO)

os.environ.setdefault("BB_REVERSAL_ENABLED", "1")

from bb_reversal import (  # noqa: E402
    BBReversalStrategy,
    macd_series,
    evaluate_macd_exit,
)

# Make get_briefing() return something during the offline replay: load the most
# recent GBPUSD briefing from disk and register it in the in-memory map that
# morning_briefing.get_briefing() reads.
def _register_latest_briefing():
    import morning_briefing
    b = morning_briefing._load_latest_briefing_for_today("GBPUSD")
    if b is None:
        print("[backtest] No briefing on disk for today — get_briefing() will return None")
        return None
    morning_briefing._BRIEFINGS["GBPUSD"] = b
    print(f"[backtest] Registered briefing: session={b.get('session')} "
          f"time={b.get('briefing_time')} bias={b.get('daily_bias')}/{b.get('session_bias')}")
    return b

_register_latest_briefing()

CACHE = "/opt/tradingbot/cache/GBPUSD_candles.csv"
ARCHIVE_TODAY = "/opt/tradingbot/data/candles/GBPUSD/2026-04-15.csv"
PPP = 1.0  # IG points per pip for GBPUSD in cache format


def _window_label_for(ts):
    """Return 'W1' or 'W2' for logging only — not used for time exits."""
    from bb_reversal import WINDOW_1, WINDOW_2
    t = ts.time()
    if WINDOW_1[0] <= t <= WINDOW_1[1]:
        return "W1"
    if WINDOW_2[0] <= t <= WINDOW_2[1]:
        return "W2"
    return "OUTSIDE"


def simulate_trade(df, entry_idx, direction, entry_price, sl_pips, tp_pips, tp_plan=None):
    """Walk bars after entry_idx until exit. Return dict with lifecycle info.

    If tp_plan is provided, TP1 hit closes the trade (IG limit behavior).
    Otherwise only SL or MACD crossover exits.
    """
    entry_ts = df["time"].iloc[entry_idx]
    window_label = _window_label_for(entry_ts)

    sl_price = entry_price + sl_pips * PPP if direction == "SELL" else entry_price - sl_pips * PPP
    tp_price = entry_price - tp_pips * PPP if direction == "SELL" else entry_price + tp_pips * PPP

    # SL is fixed at entry for the entire trade (no BE, no trail).
    sl_effective = sl_price
    lifecycle = []

    def _level_reached(bar_high, bar_low, level_price):
        if direction == "BUY":
            return bar_high >= level_price
        return bar_low <= level_price

    # Track which briefing levels were reached (for reporting)
    levels_reached = []

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        ts = row["time"]
        bar_high = float(row["high"])
        bar_low = float(row["low"])
        bar_close = float(row["close"])

        # PnL on close (pips)
        if direction == "BUY":
            pnl_pips = (bar_close - entry_price) / PPP
            best_pips = (bar_high - entry_price) / PPP
        else:
            pnl_pips = (entry_price - bar_close) / PPP
            best_pips = (entry_price - bar_low) / PPP

        # MACD values on the *closed* bar (slice up to and including i)
        closes = df["close"].iloc[: i + 1].astype(float)
        macd, sig = macd_series(closes)
        should_exit, macd_reason, mmeta = evaluate_macd_exit(
            direction,
            macd.tolist(),
            sig.tolist(),
        )

        bar_info = {
            "ts": ts,
            "o": float(row["open"]), "h": bar_high, "l": bar_low, "c": bar_close,
            "pnl_pips_close": round(pnl_pips, 2),
            "best_pips": round(best_pips, 2),
            "macd": round(float(macd.iloc[-1]), 4),
            "signal": round(float(sig.iloc[-1]), 4),
            "diff": round(float(macd.iloc[-1] - sig.iloc[-1]), 4),
            "macd_exit": should_exit,
            "macd_reason": macd_reason,
        }
        lifecycle.append(bar_info)

        # Intrabar SL check (fixed at entry — no BE, no trail).
        if direction == "BUY":
            if bar_low <= sl_effective:
                return {"exit_reason": "SL", "exit_price": sl_effective, "exit_ts": ts,
                        "lifecycle": lifecycle, "window_label": window_label,
                        "levels_reached": levels_reached}
        else:
            if bar_high >= sl_effective:
                return {"exit_reason": "SL", "exit_price": sl_effective, "exit_ts": ts,
                        "lifecycle": lifecycle, "window_label": window_label,
                        "levels_reached": levels_reached}

        # Track briefing-level touches for reporting
        if tp_plan is not None:
            for key in ("tp1", "tp2", "tp3"):
                if key in levels_reached:
                    continue
                if _level_reached(bar_high, bar_low, float(tp_plan[key])):
                    levels_reached.append(key)

        # TP1 limit hit — IG would close here
        if tp_plan is not None and _level_reached(bar_high, bar_low, float(tp_plan["tp1"])):
            return {"exit_reason": "TP1_HIT", "exit_price": float(tp_plan["tp1"]),
                    "exit_ts": ts, "lifecycle": lifecycle, "window_label": window_label,
                    "levels_reached": levels_reached}

        # MACD exit on bar close (backstop — only before TP1)
        if should_exit:
            return {"exit_reason": macd_reason, "exit_price": bar_close, "exit_ts": ts,
                    "lifecycle": lifecycle, "window_label": window_label,
                    "levels_reached": levels_reached}

    return {"exit_reason": "END_OF_DATA", "exit_price": float(df["close"].iloc[-1]),
            "exit_ts": df["time"].iloc[-1], "lifecycle": lifecycle, "window_label": window_label,
            "levels_reached": levels_reached}


def _load_source():
    """Merge archive (full day) with REST cache (latest bars) — dedupe on time."""
    frames = []
    if os.path.exists(ARCHIVE_TODAY):
        a = pd.read_csv(ARCHIVE_TODAY)
        a["time"] = pd.to_datetime(a["timestamp"], utc=True, errors="coerce")
        frames.append(a[["time", "open", "high", "low", "close"]])
    c = pd.read_csv(CACHE)
    c["time"] = pd.to_datetime(c["timestamp"], utc=True, errors="coerce")
    frames.append(c[["time", "open", "high", "low", "close"]])
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["time"]).drop_duplicates(subset=["time"], keep="last")
    df = df.sort_values("time").reset_index(drop=True)
    # Restrict to today only
    df = df[df["time"].dt.date == pd.Timestamp("2026-04-15").date()].reset_index(drop=True)
    return df


def main():
    df = _load_source()

    strat = BBReversalStrategy()
    print(f"Replaying {len(df)} bars from {df['time'].iloc[0]} to {df['time'].iloc[-1]}")
    print("=" * 80)

    trades = []
    for i in range(len(df)):
        slice_df = df.iloc[: i + 1].copy()
        bar_ts = slice_df["time"].iloc[-1]
        dec = strat.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", slice_df, 1.0, float(slice_df["close"].iloc[-1]))
        sig = str(dec.signal or "").upper()
        if sig in ("BUY", "SELL"):
            entry_price = float(dec.entry)
            dbg = dec.debug or {}
            tp_plan_dbg = None
            if dbg.get("tp_plan"):
                tp_plan_dbg = {
                    "tp1": dbg["tp_plan"][0]["price"],
                    "tp2": dbg["tp_plan"][1]["price"],
                    "tp3": dbg["tp_plan"][2]["price"],
                    "tp1_pips": dbg["tp_plan"][0]["pips"],
                    "tp2_pips": dbg["tp_plan"][1]["pips"],
                    "tp3_pips": dbg["tp_plan"][2]["pips"],
                }
            trade = simulate_trade(df, i, sig, entry_price, float(dec.sl), float(dec.tp),
                                   tp_plan=tp_plan_dbg)
            trade["entry_ts"] = bar_ts
            trade["direction"] = sig
            trade["entry_price"] = entry_price
            trade["sl_pips"] = float(dec.sl)
            trade["tp_pips"] = float(dec.tp)
            trade["tp_plan"] = tp_plan_dbg
            trade["briefing_levels_count"] = len(dbg.get("briefing_levels") or [])
            trades.append(trade)

    print(f"\nTrades simulated: {len(trades)}")
    for t in trades:
        print("\n" + "=" * 80)
        print(f"ENTRY {t['window_label']} {t['direction']} @ {t['entry_ts']} "
              f"price={t['entry_price']:.1f} sl={t['sl_pips']:.1f}p tp={t['tp_pips']:.1f}p")
        print(f"{'bar_ts':<26} {'O':>8} {'H':>8} {'L':>8} {'C':>8} "
              f"{'pnl':>7} {'best':>7} {'macd':>9} {'sig':>9} {'diff':>9} exit?")
        for b in t["lifecycle"]:
            print(f"{b['ts'].isoformat():<26} "
                  f"{b['o']:>8.1f} {b['h']:>8.1f} {b['l']:>8.1f} {b['c']:>8.1f} "
                  f"{b['pnl_pips_close']:>7.1f} {b['best_pips']:>7.1f} "
                  f"{b['macd']:>9.4f} {b['signal']:>9.4f} {b['diff']:>9.4f} "
                  f"{b['macd_reason'] if b['macd_exit'] else ''}")
        exit_pnl = (t["exit_price"] - t["entry_price"]) / PPP if t["direction"] == "BUY" \
                   else (t["entry_price"] - t["exit_price"]) / PPP
        print(f"EXIT {t['exit_reason']} @ {t['exit_ts']} price={t['exit_price']:.1f} "
              f"pnl={exit_pnl:+.1f}p")

    print("\n" + "=" * 80)
    print("SUMMARY")
    for t in trades:
        exit_pnl = (t["exit_price"] - t["entry_price"]) / PPP if t["direction"] == "BUY" \
                   else (t["entry_price"] - t["exit_price"]) / PPP
        tp = t.get("tp_plan")
        if tp:
            tp_desc = (f"TP1={tp['tp1']:.1f}({tp['tp1_pips']:.1f}p) "
                       f"TP2={tp['tp2']:.1f}({tp['tp2_pips']:.1f}p) "
                       f"TP3={tp['tp3']:.1f}({tp['tp3_pips']:.1f}p)")
        else:
            tp_desc = "no_briefing_levels (fallback=MACD-only)"
        reached = ",".join(t.get("levels_reached") or []) or "none"
        exit_kind = "TP_HIT" if t["exit_reason"] == "TP1_HIT" else (
            "MACD_BACKSTOP" if t["exit_reason"].startswith("MACD_") else t["exit_reason"]
        )
        print(f"  {t['window_label']} {t['direction']} entry={t['entry_ts']} "
              f"exit={t['exit_ts']} exit_kind={exit_kind} reason={t['exit_reason']} "
              f"pnl={exit_pnl:+.1f}p levels_reached={reached} briefing_levels={t['briefing_levels_count']} "
              f"| {tp_desc}")


if __name__ == "__main__":
    main()
