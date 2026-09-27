#!/usr/bin/env python3
"""Reproduce the prior study's Friday result on the *identical* window
(2026-09-25T00:00 UTC → 20:55 UTC) using IG bid/ask data, mid-price rule.
Then rerun the same window under executable prices for direct comparison.
"""
from __future__ import annotations

import datetime as dt
from run import load_pair_bars, detect_candidates, apply_two_slot, resolve_trade

TP, SL = 8, 15
WINDOW_START = dt.datetime(2026, 9, 25, 0, 0, tzinfo=dt.timezone.utc)
WINDOW_END   = dt.datetime(2026, 9, 25, 20, 55, tzinfo=dt.timezone.utc)


def in_window(ts: dt.datetime) -> bool:
    return WINDOW_START <= ts <= WINDOW_END


def resolve_mid(bars, cand, tp, sl):
    """Resolve on the same bar list detect_candidates ran on (fresh BB state)."""
    i0 = cand["bar_index"] + 1
    if i0 >= len(bars):
        return {"resolution": "UNRESOLVED", "net_pips": 0.0, "exit_ts": None}
    nxt = bars[i0]
    entry = (nxt["bid_open"] + nxt["ask_open"]) / 2.0
    side = cand["side"]
    if side == "BUY":
        tp_px = entry + tp; sl_px = entry - sl
    else:
        tp_px = entry - tp; sl_px = entry + sl
    for j in range(i0, len(bars)):
        b = bars[j]
        mid_hi = (b["bid_high"] + b["ask_high"]) / 2.0
        mid_lo = (b["bid_low"]  + b["ask_low"])  / 2.0
        if side == "BUY":
            hit_tp = mid_hi >= tp_px; hit_sl = mid_lo <= sl_px
        else:
            hit_tp = mid_lo <= tp_px; hit_sl = mid_hi >= sl_px
        if hit_tp and hit_sl:
            return {"resolution": "AMBIGUOUS", "net_pips": 0.0, "exit_ts": b["ts"]}
        if hit_tp:
            return {"resolution": "TP", "net_pips": tp, "exit_ts": b["ts"]}
        if hit_sl:
            return {"resolution": "SL", "net_pips": -sl, "exit_ts": b["ts"]}
    last = bars[-1]
    last_mid = (last["bid_close"] + last["ask_close"]) / 2.0
    net = last_mid - entry if side == "BUY" else entry - last_mid
    return {"resolution": "UNRESOLVED", "net_pips": net, "exit_ts": last["ts"]}


def run(mode: str):
    all_trades = []
    for pair in ("GBPUSD", "EURUSD"):
        bars, _ = load_pair_bars(pair)
        # Match the prior study exactly: BB warmup + re-key state start fresh
        # on the day window; resolver walks only the day's bars.
        day_bars = [b for b in bars if WINDOW_START <= b["ts"] <= WINDOW_END]
        for c in detect_candidates(day_bars):
            if not in_window(c["entry_ts"]):
                continue
            if mode == "mid":
                r = resolve_mid(day_bars, c, TP, SL)
            else:
                r = resolve_trade(day_bars, c, TP, SL)
            all_trades.append({"pair": pair, "side": c["side"],
                               "entry_ts": c["entry_ts"], **r})
    adm = apply_two_slot(all_trades)
    only = [t for t in adm if t["admitted"]]
    net = sum(t["net_pips"] for t in only)
    tp_c = sum(1 for t in only if t["resolution"] == "TP")
    sl_c = sum(1 for t in only if t["resolution"] == "SL")
    unr = sum(1 for t in only if t["resolution"] in ("UNRESOLVED","AMBIGUOUS"))
    return only, all_trades, {"admitted": len(only), "TP": tp_c, "SL": sl_c, "UNR": unr,
                              "net": net}


def main():
    for mode in ("mid", "exec"):
        only, all_tr, s = run(mode)
        print(f"\n=== Friday window 00:00–20:55 UTC   mode={mode}   TP={TP} SL={SL} two-slot ===")
        print(f"  admitted={s['admitted']}  TP={s['TP']}  SL={s['SL']}  UNR={s['UNR']}  net={s['net']:+.2f}p")
        for t in only:
            print(f"  {t['pair']:>7} {t['side']:>5} entry={t['entry_ts'].isoformat()}  "
                  f"exit={t.get('exit_ts')}  {t['resolution']:>6}  {t['net_pips']:+.2f}")


if __name__ == "__main__":
    main()
