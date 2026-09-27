#!/usr/bin/env python3
"""Mid-only Friday sanity — reproduce the prior study's +34 headline on
the same 1-min bid/ask data I fetched today, aggregated to 5m, using
mid=(bid+ask)/2 everywhere. Uses run.py primitives.
"""
from __future__ import annotations

import datetime as dt
from run import load_pair_bars, detect_candidates, apply_two_slot, MAX_CONCURRENT

FRIDAY = dt.date(2026, 9, 25)
TP, SL = 8, 15


def resolve_mid(bars, cand, tp, sl):
    i0 = cand["bar_index"] + 1
    if i0 >= len(bars):
        return {"resolution": "UNRESOLVED", "net_pips": 0.0}
    nxt = bars[i0]
    entry = (nxt["bid_open"] + nxt["ask_open"]) / 2.0
    side = cand["side"]
    if side == "BUY":
        tp_px = entry + tp
        sl_px = entry - sl
    else:
        tp_px = entry - tp
        sl_px = entry + sl
    for j in range(i0, len(bars)):
        b = bars[j]
        mid_hi = (b["bid_high"] + b["ask_high"]) / 2.0
        mid_lo = (b["bid_low"]  + b["ask_low"])  / 2.0
        if side == "BUY":
            hit_tp = mid_hi >= tp_px
            hit_sl = mid_lo <= sl_px
        else:
            hit_tp = mid_lo <= tp_px
            hit_sl = mid_hi >= sl_px
        if hit_tp and hit_sl:
            return {"resolution": "AMBIGUOUS", "net_pips": 0.0, "exit_ts": b["ts"]}
        if hit_tp:
            return {"resolution": "TP", "net_pips": tp, "exit_ts": b["ts"]}
        if hit_sl:
            return {"resolution": "SL", "net_pips": -sl, "exit_ts": b["ts"]}
    # ran off end
    last = bars[-1]
    last_mid = (last["bid_close"] + last["ask_close"]) / 2.0
    net = last_mid - entry if side == "BUY" else entry - last_mid
    return {"resolution": "UNRESOLVED", "net_pips": net, "exit_ts": last["ts"]}


def main():
    bars_g, _ = load_pair_bars("GBPUSD")
    bars_e, _ = load_pair_bars("EURUSD")
    trades = []
    for pair, bars in (("GBPUSD", bars_g), ("EURUSD", bars_e)):
        for c in detect_candidates(bars):
            if c["entry_ts"].date() != FRIDAY:
                continue
            r = resolve_mid(bars, c, TP, SL)
            trades.append({"pair": pair, "side": c["side"], "band": c["band"],
                           "entry_ts": c["entry_ts"], "exit_ts": r.get("exit_ts"),
                           **{k: r[k] for k in ("resolution", "net_pips")}})
    adm = apply_two_slot(trades)
    only = [t for t in adm if t["admitted"]]
    net = sum(t["net_pips"] for t in only)
    tp_c = sum(1 for t in only if t["resolution"] == "TP")
    sl_c = sum(1 for t in only if t["resolution"] == "SL")
    unr = sum(1 for t in only if t["resolution"] in ("UNRESOLVED", "AMBIGUOUS"))
    print(f"Friday mid-only two-slot TP={TP} SL={SL}: "
          f"admitted={len(only)}  TP={tp_c}  SL={sl_c}  UNR={unr}  net={net:+.2f}p")
    for t in only:
        print(f"  {t['pair']:>7} {t['side']:>5} {t['entry_ts'].isoformat()}  "
              f"{t['resolution']:>6}  {t['net_pips']:+.2f}")


if __name__ == "__main__":
    main()
