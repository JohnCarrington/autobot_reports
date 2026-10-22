"""Per-setup audit for Thursday 2026-04-30 GBPUSD.

Mirrors the May-1 audit format using the EXACT committed code.
Drives gbpusd_bb_bounce.evaluate + trade_manager._monitor_bb_pierce_run
via the documented test seams. Read-only.
"""
from __future__ import annotations

import os
os.environ.setdefault("GBPUSD_BB_BOUNCE_ENABLED", "1")

import csv
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple

REPO = Path("/opt/tradingbot")
sys.path.insert(0, str(REPO))

import gbpusd_bb_bounce as bbb  # noqa: E402
importlib.reload(bbb)
import trade_manager as tm  # noqa: E402
from trade_executor import _state_for_epic  # noqa: E402

CANDLE_DIR = REPO / "data" / "candles" / "GBPUSD"
EPIC_LONG  = "CS.D.GBPUSD.BBP.LONG"
EPIC_SHORT = "CS.D.GBPUSD.BBP.SHORT"
EVAL_EPIC  = "CS.D.GBPUSD.TODAY.IP"
SPREAD_PIPS = 1.5
PIP_SIZE = 1.0
INITIAL_SL_PIPS = bbb.SL_PIPS
TARGET_DAY = "2026-04-30"

# Test seams
sim_time = [0.0]
class _FakeTime:
    @staticmethod
    def time(): return sim_time[0]
tm.time = _FakeTime
_close_log: List[Dict] = []
def _fake_close(epic, reason, exit_hint):
    _close_log.append({"sim_ts": sim_time[0], "epic": str(epic),
                       "reason": str(reason), "exit_hint": float(exit_hint)})
tm._close_trade_best_effort = _fake_close
def _fake_amend(deal_id, stop_level, limit_level): pass
tm._bb_pierce_run_amend_fn = _fake_amend


def _load_5m(date_str: str) -> List[Dict]:
    f = CANDLE_DIR / f"{date_str}.csv"
    if not f.exists():
        return []
    out = []
    with f.open() as fh:
        for r in csv.DictReader(fh):
            ts = datetime.fromisoformat(r["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append({"ts": ts, "open": float(r["open"]),
                        "high": float(r["high"]), "low": float(r["low"]),
                        "close": float(r["close"])})
    return out


def _bb(closes):
    if len(closes) < bbb.BB_PERIOD: return None
    last20 = closes[-bbb.BB_PERIOD:]
    m = mean(last20); s = pstdev(last20)
    return (m - 2*s, m, m + 2*s)


def _atr14(bars):
    if len(bars) < 15: return None
    trs = []
    for i in range(len(bars) - 14, len(bars)):
        h = bars[i]["high"]; l = bars[i]["low"]; pc = bars[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return mean(trs) if trs else None


def _open_pos(direction, bar):
    if direction == "BUY":
        entry = bar["close"] + SPREAD_PIPS * PIP_SIZE
        initial_sl = entry - INITIAL_SL_PIPS * PIP_SIZE
        epic_key = EPIC_LONG; mode = bbb.MODE_NAME_LONG
    else:
        entry = bar["close"] - SPREAD_PIPS * PIP_SIZE
        initial_sl = entry + INITIAL_SL_PIPS * PIP_SIZE
        epic_key = EPIC_SHORT; mode = bbb.MODE_NAME_SHORT
    open_epoch = bar["ts"].timestamp()
    st = _state_for_epic(epic_key)
    st.clear()
    st.update({"active": True, "mode": mode, "direction": direction,
               "entry_price": float(entry),
               "deal_id": f"BT_{epic_key}_{bar['ts'].isoformat()}",
               "dealId": f"BT_{epic_key}_{bar['ts'].isoformat()}",
               "open_time": open_epoch, "tp": float(bbb.TP_CAP_PIPS),
               "sl": float(INITIAL_SL_PIPS), "pip_size": float(PIP_SIZE),
               "epic": epic_key})
    return {"direction": direction, "epic_key": epic_key,
            "entry_ts": bar["ts"], "entry_price": entry,
            "open_time_epoch": open_epoch, "initial_sl": initial_sl}


def _current_stop(pos):
    st = _state_for_epic(pos["epic_key"])
    last = st.get("_bbpr_last_stop_level")
    return float(last) if last is not None else pos["initial_sl"]


def _process(pos, bar):
    direction = pos["direction"]
    o = bar["open"]; h = bar["high"]; l = bar["low"]; c = bar["close"]; ts = bar["ts"]
    bar_dir = "bullish" if c > o else ("bearish" if c < o else "doji")
    if direction == "BUY":
        adverse_first = bar_dir in ("bullish", "doji")
        adverse_px = l; favorable_px = h
    else:
        adverse_first = bar_dir in ("bearish", "doji")
        adverse_px = h; favorable_px = l

    sim_time[0] = ts.timestamp()
    age_min = max(0.0, (sim_time[0] - pos["open_time_epoch"]) / 60.0)
    if age_min >= bbb.TIME_STOP_MINUTES:
        tm.TradeManager()._monitor_bb_pierce_run(epic=pos["epic_key"], mid_price=c, bid=c, ask=c)
        for sig in _close_log:
            if sig["epic"] == pos["epic_key"] and sig["sim_ts"] >= pos["open_time_epoch"]:
                pnl = (c - pos["entry_price"]) if direction == "BUY" else (pos["entry_price"] - c)
                _close_log.clear()
                st = _state_for_epic(pos["epic_key"])
                return {"exit_ts": ts, "exit_price": c, "exit_reason": sig["reason"],
                        "pnl_pips": pnl, "max_tier": str(st.get("_bbpr_tier") or "init"),
                        "best_pnl_pips": float(st.get("_bbpr_best_pnl_pips") or 0.0)}

    def _drive(mid):
        sim_time[0] = ts.timestamp()
        tm.TradeManager()._monitor_bb_pierce_run(epic=pos["epic_key"],
                                                  mid_price=float(mid),
                                                  bid=float(mid), ask=float(mid))

    def _check_close():
        for sig in _close_log:
            if sig["epic"] == pos["epic_key"] and sig["sim_ts"] >= pos["open_time_epoch"]:
                pnl = (c - pos["entry_price"]) if direction == "BUY" else (pos["entry_price"] - c)
                _close_log.clear()
                st = _state_for_epic(pos["epic_key"])
                return {"exit_ts": ts, "exit_price": c, "exit_reason": sig["reason"],
                        "pnl_pips": pnl, "max_tier": str(st.get("_bbpr_tier") or "init"),
                        "best_pnl_pips": float(st.get("_bbpr_best_pnl_pips") or 0.0)}
        return None

    def _check_sl():
        cur_sl = _current_stop(pos)
        if direction == "BUY" and adverse_px <= cur_sl: return cur_sl
        if direction == "SELL" and adverse_px >= cur_sl: return cur_sl
        return None

    def _record_sl(sl_price):
        pnl = (sl_price - pos["entry_price"]) if direction == "BUY" else (pos["entry_price"] - sl_price)
        st = _state_for_epic(pos["epic_key"])
        tier = str(st.get("_bbpr_tier") or "init")
        if tier == "init": reason = "BROKER_SL"
        elif tier == "be": reason = "BE_SL"
        else: reason = f"TRAIL_{tier.upper()}_SL"
        return {"exit_ts": ts, "exit_price": sl_price, "exit_reason": reason,
                "pnl_pips": pnl, "max_tier": tier,
                "best_pnl_pips": float(st.get("_bbpr_best_pnl_pips") or 0.0)}

    if adverse_first:
        sl = _check_sl()
        if sl is not None: return _record_sl(sl)
        _drive(favorable_px)
        cc = _check_close()
        if cc is not None: return cc
    else:
        _drive(favorable_px)
        cc = _check_close()
        if cc is not None: return cc
        sl = _check_sl()
        if sl is not None: return _record_sl(sl)
    return None


def main():
    pre_day = "2026-04-29"
    day_rows = _load_5m(TARGET_DAY)
    pre_rows = _load_5m(pre_day)
    if not day_rows:
        print(f"No data for {TARGET_DAY}")
        return 1
    print(f"# Per-setup audit — {TARGET_DAY} (Thursday) GBPUSD")
    print(f"# Strategy: BB_PIERCE_RUN — pierce >=2p, BB width >=8p, "
          f"window 07:00-17:00 UTC, single position per direction")
    print(f"# SL=12p, trail BE@20p, T2@40p (-20p), T3@60p (-25p), time stop=240m")
    print(f"# Spread: 1.5p one-way at entry")
    print(f"# Times below in UTC; user reads BST = UTC + 1h")

    # Build full bar stream + BB + ATR for entire 04-29 + 04-30 timeline
    all_bars = list(pre_rows[-(bbb.BB_PERIOD + 14):])
    closes = [r["close"] for r in all_bars]

    # Track all pierces on the target day
    pierces: List[Dict] = []
    rolling_bars = [bbb.Bar(timestamp=r["ts"], open=r["open"], high=r["high"],
                             low=r["low"], close=r["close"]) for r in pre_rows[-6:]]

    open_long = open_short = None
    fires: List[Dict] = []
    active_record: Dict[str, Dict] = {}

    for bar in day_rows:
        # Manage open positions
        if open_long is not None:
            r = _process(open_long, bar)
            if r is not None:
                active_record[open_long["epic_key"]].update(r)
                del active_record[open_long["epic_key"]]
                _state_for_epic(open_long["epic_key"])["active"] = False
                open_long = None
        if open_short is not None:
            r = _process(open_short, bar)
            if r is not None:
                active_record[open_short["epic_key"]].update(r)
                del active_record[open_short["epic_key"]]
                _state_for_epic(open_short["epic_key"])["active"] = False
                open_short = None

        # Update BB stream
        closes.append(bar["close"])
        all_bars.append(bar)
        rolling_bars.append(bbb.Bar(timestamp=bar["ts"], open=bar["open"],
                                     high=bar["high"], low=bar["low"], close=bar["close"]))
        if len(rolling_bars) > 6:
            rolling_bars = rolling_bars[-6:]
        if len(closes) < bbb.BB_PERIOD:
            continue
        bb = _bb(closes)
        if bb is None:
            continue
        bbl, bbm, bbu = bb

        # Record pierce if any (regardless of strategy gate)
        long_p_mag  = bbl - bar["low"]
        short_p_mag = bar["high"] - bbu
        if long_p_mag >= bbb.PIERCE_THRESH_PIPS and short_p_mag >= bbb.PIERCE_THRESH_PIPS:
            # both-band — note but tag specially
            pierces.append({"ts": bar["ts"], "dir": "BOTH",
                            "long_mag": long_p_mag, "short_mag": short_p_mag,
                            "bbl": bbl, "bbu": bbu, "width": bbu - bbl})
        elif long_p_mag >= bbb.PIERCE_THRESH_PIPS:
            pierces.append({"ts": bar["ts"], "dir": "LONG",
                            "long_mag": long_p_mag, "short_mag": 0.0,
                            "bbl": bbl, "bbu": bbu, "width": bbu - bbl,
                            "low": bar["low"], "high": bar["high"], "close": bar["close"]})
        elif short_p_mag >= bbb.PIERCE_THRESH_PIPS:
            pierces.append({"ts": bar["ts"], "dir": "SHORT",
                            "long_mag": 0.0, "short_mag": short_p_mag,
                            "bbl": bbl, "bbu": bbu, "width": bbu - bbl,
                            "low": bar["low"], "high": bar["high"], "close": bar["close"]})

        # Strategy evaluate
        try:
            dec = bbb.strategy.evaluate(
                symbol="GBPUSD", epic=EVAL_EPIC, ts=bar["ts"],
                bars=rolling_bars, closes_ind=closes,
                has_open_long=(open_long is not None),
                has_open_short=(open_short is not None),
            )
        except Exception:
            dec = None
        if dec is None:
            continue
        sig = str(getattr(dec, "signal", "")).upper()
        # Features at fire bar
        atr14 = _atr14(all_bars)
        # Cluster: same-dir pierces in prior 30 min INCL this bar.
        # Note: pierces[] uses "LONG"/"SHORT" tags; strategy signal is
        # "BUY"/"SELL". Map BUY->LONG, SELL->SHORT.
        sig_pierce_dir = "LONG" if sig == "BUY" else "SHORT"
        cutoff_30 = bar["ts"] - timedelta(minutes=30)
        same_count = sum(1 for p in pierces
                         if p["ts"] > cutoff_30 and p["dir"] == sig_pierce_dir)
        # Opp-dir in prior 60 min
        cutoff_60 = bar["ts"] - timedelta(minutes=60)
        opp_dir = "SHORT" if sig == "BUY" else "LONG"
        opp_count = sum(1 for p in pierces
                        if cutoff_60 <= p["ts"] < bar["ts"] and p["dir"] == opp_dir)

        if sig == "BUY" and open_long is None:
            open_long = _open_pos("BUY", bar)
            rec = {"entry_ts": bar["ts"], "direction": "BUY",
                   "entry_price": open_long["entry_price"],
                   "bb_width_pips": (bbu - bbl) / PIP_SIZE,
                   "atr14_pips": atr14, "cluster_size": same_count,
                   "opp_60m": opp_count > 0, "hour_utc": bar["ts"].hour}
            fires.append(rec)
            active_record[open_long["epic_key"]] = rec
        elif sig == "SELL" and open_short is None:
            open_short = _open_pos("SELL", bar)
            rec = {"entry_ts": bar["ts"], "direction": "SELL",
                   "entry_price": open_short["entry_price"],
                   "bb_width_pips": (bbu - bbl) / PIP_SIZE,
                   "atr14_pips": atr14, "cluster_size": same_count,
                   "opp_60m": opp_count > 0, "hour_utc": bar["ts"].hour}
            fires.append(rec)
            active_record[open_short["epic_key"]] = rec

    # EOD close any still-open
    last_bar = day_rows[-1]
    for pos in (open_long, open_short):
        if pos is not None:
            c = last_bar["close"]
            pnl = (c - pos["entry_price"]) if pos["direction"] == "BUY" else (pos["entry_price"] - c)
            st = _state_for_epic(pos["epic_key"])
            rec = active_record.get(pos["epic_key"])
            if rec is not None:
                rec.update({"exit_ts": last_bar["ts"], "exit_price": c,
                            "exit_reason": "EOD", "pnl_pips": pnl,
                            "max_tier": str(st.get("_bbpr_tier") or "init"),
                            "best_pnl_pips": float(st.get("_bbpr_best_pnl_pips") or 0.0)})

    # ─── 1. Pierce list ────────────────────────────────────────────────────
    print()
    print("## 1. Every BB pierce on 2026-04-30 (low<=BBL-2p OR high>=BBU+2p)")
    # Cluster classification: a pierce is part of a same-dir cluster if
    # there is at least one OTHER same-dir pierce within ±30 min.
    print(f"\n  {'ts_UTC':<8} {'BST':<6} {'dir':<6} {'mag_p':>7} {'BB_width':>9} "
          f"{'cluster':<12}")
    for i, p in enumerate(pierces):
        same_dir_within_30 = sum(
            1 for q in pierces if q is not p
            and abs((q["ts"] - p["ts"]).total_seconds()) <= 30 * 60
            and q["dir"] == p["dir"]
        )
        if same_dir_within_30 == 0:
            cluster_label = "single"
        else:
            cluster_label = f"cluster_{same_dir_within_30 + 1}"
        ts = p["ts"]
        bst = (ts + timedelta(hours=1)).strftime("%H:%M")
        mag = p["long_mag"] if p["dir"] == "LONG" else p["short_mag"] if p["dir"] == "SHORT" else max(p["long_mag"], p["short_mag"])
        print(f"  {ts.strftime('%H:%M'):<8} {bst:<6} {p['dir']:<6} "
              f"{mag:>+6.1f}p {p['width']:>+8.1f}p {cluster_label:<12}")

    # ─── 2. Strategy fires ────────────────────────────────────────────────
    print()
    print("## 2. Every BB_PIERCE_RUN fire on 2026-04-30")
    print(f"\n  {'fire_UTC':<8} {'BST':<6} {'dir':<5} {'entry':<8} "
          f"{'exit_UTC':<9} {'exit_px':<8} {'reason':<22} {'pnl':>7} "
          f"{'tier':<6} {'MFE':>7}")
    for f in fires:
        if "pnl_pips" not in f: continue
        ts = f["entry_ts"]
        bst = (ts + timedelta(hours=1)).strftime("%H:%M")
        ets = f["exit_ts"]
        ets_bst = ets.strftime("%H:%M")
        d = "LONG" if f["direction"] == "BUY" else "SHORT"
        print(f"  {ts.strftime('%H:%M'):<8} {bst:<6} {d:<5} "
              f"{f['entry_price']:<8.1f} {ets_bst:<9} {f['exit_price']:<8.1f} "
              f"{f['exit_reason']:<22} {f['pnl_pips']:>+7.1f} "
              f"{f['max_tier']:<6} {f['best_pnl_pips']:>+6.1f}p")

    # ─── 3. Per-fire features ─────────────────────────────────────────────
    print()
    print("## 3. Features at each fire")
    print(f"\n  {'fire_UTC':<8} {'BST':<6} {'dir':<5} "
          f"{'cluster':<8} {'opp_60m':<8} {'BB_w':<7} {'ATR14':<7} {'hour':<5}")
    for f in fires:
        ts = f["entry_ts"]
        bst = (ts + timedelta(hours=1)).strftime("%H:%M")
        d = "LONG" if f["direction"] == "BUY" else "SHORT"
        atr_s = f"{f['atr14_pips']:.1f}p" if f.get("atr14_pips") else "—"
        print(f"  {ts.strftime('%H:%M'):<8} {bst:<6} {d:<5} "
              f"{f['cluster_size']:<8} {str(f['opp_60m']):<8} "
              f"{f['bb_width_pips']:<6.1f}p {atr_s:<7} "
              f"{f['hour_utc']:<5}")

    # ─── 4. Day total ─────────────────────────────────────────────────────
    completed = [f for f in fires if "pnl_pips" in f]
    wins = [f for f in completed if f["pnl_pips"] > 0]
    losses = [f for f in completed if f["pnl_pips"] <= 0]
    net = sum(f["pnl_pips"] for f in completed)
    print()
    print("## 4. Day total")
    print(f"  fires: {len(completed)}   wins: {len(wins)}   losses: {len(losses)}")
    print(f"  net pips: {net:+.1f}")
    print(f"  WR: {(len(wins)/len(completed)*100 if completed else 0):.1f}%")

    # ─── 5. Visual setups: pierce(s) preceding >20p directional move ──────
    print()
    print("## 5. Visual setups — pierce(s) preceding a >20p directional move")
    print("    (forward-looking: from the pierce bar's close, did price")
    print("     run >=20p in the reversal direction within the next 60 min?)")

    # We need to walk forward from each pierce to compute the run
    # First, build a per-bar map keyed by ts on the target day
    by_ts = {b["ts"]: b for b in day_rows}
    sorted_ts = sorted(by_ts.keys())

    def _forward_run(start_ts: datetime, dir_str: str, lookahead_min: int = 60):
        """Max favorable excursion in pips from the close of the pierce
        bar over the next lookahead_min minutes, in the REVERSAL direction
        (LONG pierce -> reversal is UP; SHORT pierce -> reversal is DOWN)."""
        b0 = by_ts.get(start_ts)
        if not b0:
            return 0.0
        anchor_close = b0["close"]
        end = start_ts + timedelta(minutes=lookahead_min)
        run = 0.0
        for ts in sorted_ts:
            if ts <= start_ts:
                continue
            if ts > end:
                break
            b = by_ts[ts]
            if dir_str == "LONG":  # reversal = up
                run = max(run, b["high"] - anchor_close)
            else:  # SHORT pierce; reversal = down
                run = max(run, anchor_close - b["low"])
        return run

    # Group pierces into clusters (consecutive same-dir within 30 min)
    visual_setups = []
    used = set()
    for i, p in enumerate(pierces):
        if i in used:
            continue
        if p["dir"] == "BOTH":
            continue
        # Find all same-dir pierces within 30 min of this one
        cluster = [p]
        used.add(i)
        for j, q in enumerate(pierces[i+1:], start=i+1):
            if j in used: continue
            if q["dir"] != p["dir"]: continue
            if (q["ts"] - cluster[-1]["ts"]).total_seconds() <= 30*60:
                cluster.append(q)
                used.add(j)
        # Compute the run from the FIRST pierce of the cluster — this is
        # what a chart-reader sees as "setup formed at time T, moved X pips".
        # Lookahead is 60 min from FIRST pierce, plus a 30-min cushion for
        # late-extending clusters (so a 14:00-15:00 cluster gets up to 16:00).
        first = cluster[0]
        cushion_min = 60 + max(0, int((cluster[-1]["ts"] - first["ts"]).total_seconds() / 60))
        run = _forward_run(first["ts"], first["dir"], cushion_min)
        if run >= 20.0:
            visual_setups.append({
                "ts_first": cluster[0]["ts"],
                "ts_last": cluster[-1]["ts"],
                "dir": cluster[0]["dir"],
                "size": len(cluster),
                "run_pips": run,
                "max_mag": max(c.get("long_mag", 0) if c["dir"] == "LONG"
                                  else c.get("short_mag", 0) for c in cluster),
                "lookahead_min": cushion_min,
            })

    if not visual_setups:
        print("  (no clusters with a forward >=20p run)")
    else:
        print(f"\n  {'first_UTC':<10} {'BST':<6} {'last_UTC':<9} {'dir':<6} "
              f"{'size':<5} {'run':>9} {'lookahead':>11} {'max_mag':>9}")
        for s in visual_setups:
            bst = (s["ts_first"] + timedelta(hours=1)).strftime("%H:%M")
            print(f"  {s['ts_first'].strftime('%H:%M'):<10} {bst:<6} "
                  f"{s['ts_last'].strftime('%H:%M'):<9} {s['dir']:<6} "
                  f"{s['size']:<5} {s['run_pips']:>+8.1f}p "
                  f"{s['lookahead_min']:>9}m {s['max_mag']:>+8.1f}p")

    # ─── 6. Did strategy fire on each visual setup? ───────────────────────
    print()
    print("## 6. Did the strategy fire on each visual setup?")
    if not visual_setups:
        print("  (no visual setups)")
    else:
        print(f"\n  {'setup_UTC':<10} {'BST':<6} {'dir':<6} {'size':<5} "
              f"{'fired?':<7} {'fire_UTC':<10} {'pnl':>7} {'reason':<22}")
        for s in visual_setups:
            target_dir = "BUY" if s["dir"] == "LONG" else "SELL"
            # match a fire whose entry_ts is anywhere from first_pierce to
            # last_pierce + 5 min, same direction
            window_lo = s["ts_first"] - timedelta(minutes=5)
            window_hi = s["ts_last"] + timedelta(minutes=10)
            match = None
            for f in completed:
                if f["direction"] != target_dir:
                    continue
                if window_lo <= f["entry_ts"] <= window_hi:
                    match = f
                    break
            bst = (s["ts_first"] + timedelta(hours=1)).strftime("%H:%M")
            if match:
                print(f"  {s['ts_first'].strftime('%H:%M'):<10} {bst:<6} "
                      f"{s['dir']:<6} {s['size']:<5} YES     "
                      f"{match['entry_ts'].strftime('%H:%M'):<10} "
                      f"{match['pnl_pips']:>+7.1f} {match['exit_reason']:<22}")
            else:
                # Diagnose why
                first_pierce_ts = s["ts_first"]
                in_window = (bbb.WIN_START <= first_pierce_ts.timetz().replace(tzinfo=None) < bbb.WIN_END)
                if not in_window:
                    why = "outside_window"
                else:
                    why = "blocked_by_position"
                print(f"  {s['ts_first'].strftime('%H:%M'):<10} {bst:<6} "
                      f"{s['dir']:<6} {s['size']:<5} NO      "
                      f"—          —      {why}")


if __name__ == "__main__":
    main()
