"""Re-run April backtest, record per-fire features, compare winners vs
losers. Also probe the two missed May 1 setups (07:30 + 07:45 BST).

Features per fire:
  - cluster_size: number of same-direction pierces in the prior 30 min
                  (incl. the firing bar). 1 = single; >=2 = cluster.
  - opp_60m: True if at least one OPPOSITE-direction pierce in the prior
             60 min (i.e. proper reversal context).
  - bb_width_pips: BB upper - BB lower at the firing bar.
  - atr14_pips: 14-period ATR on 5m, computed as the mean true range over
                the prior 14 closed bars.
  - hour_utc: bar.ts.hour
  - pnl, exit_reason, max_tier — from backtest result.

Outputs distributions for wins vs losses across each feature.
"""
from __future__ import annotations

import os
os.environ.setdefault("GBPUSD_BB_BOUNCE_ENABLED", "1")

import csv
import importlib
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median, pstdev
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

# ─── Test seams ────────────────────────────────────────────────────────────
sim_time = [0.0]
class _FakeTime:
    @staticmethod
    def time(): return sim_time[0]
tm.time = _FakeTime
_amend_log: List[Dict] = []
def _fake_amend(deal_id, stop_level, limit_level):
    _amend_log.append({"sim_ts": sim_time[0], "stop": float(stop_level)})
tm._bb_pierce_run_amend_fn = _fake_amend
_close_log: List[Dict] = []
def _fake_close(epic, reason, exit_hint_price):
    _close_log.append({"sim_ts": sim_time[0], "epic": str(epic),
                       "reason": str(reason), "exit_hint": float(exit_hint_price)})
tm._close_trade_best_effort = _fake_close


# ─── Data ──────────────────────────────────────────────────────────────────
def _load_5m(date_str: str):
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


def _weekdays(d0, d1):
    a = datetime.fromisoformat(d0).date()
    b = datetime.fromisoformat(d1).date()
    out = []
    cur = a
    while cur <= b:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur = cur + timedelta(days=1)
    return out


# ─── Indicators ────────────────────────────────────────────────────────────
def _bb_20_2(closes):
    if len(closes) < bbb.BB_PERIOD:
        return None
    last20 = closes[-bbb.BB_PERIOD:]
    m = mean(last20); s = pstdev(last20)
    return (m - 2*s, m, m + 2*s)


def _atr14(bars: List[Dict]) -> Optional[float]:
    """14-period 5m ATR over the closed bars list (last 14 + 1 prior close)."""
    if len(bars) < 15:
        return None
    trs = []
    for i in range(len(bars) - 14, len(bars)):
        h = bars[i]["high"]; l = bars[i]["low"]
        pc = bars[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return mean(trs) if trs else None


def _pierce_dir(bar, bb_lower, bb_upper) -> Optional[str]:
    """Same gate as the strategy module."""
    long_p  = (bb_lower - bar["low"])  >= bbb.PIERCE_THRESH_PIPS * PIP_SIZE
    short_p = (bar["high"] - bb_upper) >= bbb.PIERCE_THRESH_PIPS * PIP_SIZE
    if long_p and short_p:
        return None  # both-band
    width = (bb_upper - bb_lower) / PIP_SIZE
    if width < bbb.BB_WIDTH_FLOOR_PIPS:
        return None
    if long_p:
        return "BUY"
    if short_p:
        return "SELL"
    return None


# ─── Per-fire analysis driver ──────────────────────────────────────────────
@dataclass
class FireFeature:
    entry_ts: datetime
    direction: str
    pnl_pips: float
    exit_reason: str
    max_tier: str
    bb_width_pips: float
    atr14_pips: Optional[float]
    cluster_size: int
    opp_60m: bool
    hour_utc: int


def _open_position(direction, bar):
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
    return {"direction": direction, "epic_key": epic_key, "entry_ts": bar["ts"],
            "entry_price": entry, "open_time_epoch": open_epoch,
            "initial_sl": initial_sl, "closed": False}


def _current_stop(pos):
    st = _state_for_epic(pos["epic_key"])
    last = st.get("_bbpr_last_stop_level")
    return float(last) if last is not None else pos["initial_sl"]


def _process_bar(pos, bar):
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
        mgr = tm.TradeManager()
        mgr._monitor_bb_pierce_run(epic=pos["epic_key"], mid_price=c, bid=c, ask=c)
        for sig in _close_log:
            if sig["epic"] == pos["epic_key"] and sig["sim_ts"] >= pos["open_time_epoch"]:
                pnl = (c - pos["entry_price"]) if direction == "BUY" else (pos["entry_price"] - c)
                _close_log.clear()
                st = _state_for_epic(pos["epic_key"])
                return {"exit_ts": ts, "exit_price": c, "exit_reason": sig["reason"],
                        "pnl_pips": pnl, "max_tier": str(st.get("_bbpr_tier") or "init")}

    def _drive(mid):
        sim_time[0] = ts.timestamp()
        tm.TradeManager()._monitor_bb_pierce_run(epic=pos["epic_key"],
                                                 mid_price=float(mid), bid=float(mid), ask=float(mid))

    def _check_close():
        for sig in _close_log:
            if sig["epic"] == pos["epic_key"] and sig["sim_ts"] >= pos["open_time_epoch"]:
                pnl = (c - pos["entry_price"]) if direction == "BUY" else (pos["entry_price"] - c)
                _close_log.clear()
                st = _state_for_epic(pos["epic_key"])
                return {"exit_ts": ts, "exit_price": c, "exit_reason": sig["reason"],
                        "pnl_pips": pnl, "max_tier": str(st.get("_bbpr_tier") or "init")}
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
                "pnl_pips": pnl, "max_tier": tier}

    if adverse_first:
        sl = _check_sl()
        if sl is not None: return _record_sl(sl)
        _drive(favorable_px)
        c2 = _check_close()
        if c2 is not None: return c2
    else:
        _drive(favorable_px)
        c2 = _check_close()
        if c2 is not None: return c2
        sl = _check_sl()
        if sl is not None: return _record_sl(sl)
    return None


def run_backtest_with_features(date_start: str, date_end: str) -> List[FireFeature]:
    days = _weekdays(date_start, date_end)
    pre_day = (datetime.fromisoformat(date_start) - timedelta(days=1)).date().isoformat()
    pre_rows = _load_5m(pre_day)

    # All-bars list, BB precomputed per bar, pierce list precomputed.
    all_bars: List[Dict] = list(pre_rows[-(bbb.BB_PERIOD + 14):])  # warmup
    running_closes: List[float] = [r["close"] for r in all_bars]

    # We'll rebuild a stream of bars as we walk days for the strategy, but
    # also keep a pierce-list (regardless of fire) to compute cluster /
    # opposite-context features at fire time.
    pierce_stream: List[Tuple[datetime, str]] = []  # (ts, dir)

    open_long = open_short = None
    fires: List[Dict] = []
    # Map epic_key -> active fire-record dict (so we can update it on close
    # without unreliable id() lookups).
    active_record: Dict[str, Dict] = {}

    rolling_bars: List[bbb.Bar] = [
        bbb.Bar(timestamp=r["ts"], open=r["open"], high=r["high"], low=r["low"], close=r["close"])
        for r in pre_rows[-6:]
    ]

    last_bar = None

    for day in days:
        rows = _load_5m(day)
        if not rows:
            continue
        for bar in rows:
            last_bar = bar

            # Manage open positions on this bar
            if open_long is not None:
                rec = _process_bar(open_long, bar)
                if rec is not None:
                    active_record[open_long["epic_key"]].update(rec)
                    del active_record[open_long["epic_key"]]
                    _state_for_epic(open_long["epic_key"])["active"] = False
                    open_long = None
            if open_short is not None:
                rec = _process_bar(open_short, bar)
                if rec is not None:
                    active_record[open_short["epic_key"]].update(rec)
                    del active_record[open_short["epic_key"]]
                    _state_for_epic(open_short["epic_key"])["active"] = False
                    open_short = None

            # Eval strategy on bar close
            running_closes.append(bar["close"])
            all_bars.append(bar)
            rolling_bars.append(bbb.Bar(timestamp=bar["ts"], open=bar["open"],
                                        high=bar["high"], low=bar["low"], close=bar["close"]))
            if len(rolling_bars) > 6:
                rolling_bars = rolling_bars[-6:]

            if len(running_closes) < bbb.BB_PERIOD:
                continue

            bb = _bb_20_2(running_closes)
            if bb is None:
                continue
            bbl, _bm, bbu = bb

            # Track pierces (regardless of strategy gate logic) for
            # cluster/opposite-context features
            pd = _pierce_dir(bar, bbl, bbu)
            if pd is not None:
                pierce_stream.append((bar["ts"], pd))

            # Strategy evaluate (uses its own internal pierce check)
            try:
                dec = bbb.strategy.evaluate(
                    symbol="GBPUSD", epic=EVAL_EPIC, ts=bar["ts"],
                    bars=rolling_bars, closes_ind=running_closes,
                    has_open_long=(open_long is not None),
                    has_open_short=(open_short is not None),
                )
            except Exception as e:
                dec = None
            if dec is None:
                continue
            sig = str(getattr(dec, "signal", "")).upper()

            # Compute features at this fire bar
            atr14 = _atr14(all_bars)
            bb_width = (bbu - bbl) / PIP_SIZE
            # Cluster: count same-dir pierces in prior 30 min INCLUDING this bar
            cutoff_30 = bar["ts"] - timedelta(minutes=30)
            same_count = sum(1 for (pt, pd2) in pierce_stream
                             if pt > cutoff_30 and pd2 == sig)
            # Opposite-dir pierce in prior 60 min
            cutoff_60 = bar["ts"] - timedelta(minutes=60)
            opp_dir = "SELL" if sig == "BUY" else "BUY"
            opp_count = sum(1 for (pt, pd2) in pierce_stream
                            if cutoff_60 <= pt < bar["ts"] and pd2 == opp_dir)

            if sig == "BUY" and open_long is None:
                open_long = _open_position("BUY", bar)
                rec = {"entry_ts": bar["ts"], "direction": "BUY",
                       "bb_width_pips": bb_width, "atr14_pips": atr14,
                       "cluster_size": same_count, "opp_60m": opp_count > 0,
                       "hour_utc": bar["ts"].hour}
                fires.append(rec)
                active_record[open_long["epic_key"]] = rec
            elif sig == "SELL" and open_short is None:
                open_short = _open_position("SELL", bar)
                rec = {"entry_ts": bar["ts"], "direction": "SELL",
                       "bb_width_pips": bb_width, "atr14_pips": atr14,
                       "cluster_size": same_count, "opp_60m": opp_count > 0,
                       "hour_utc": bar["ts"].hour}
                fires.append(rec)
                active_record[open_short["epic_key"]] = rec

    # EOD close any still-open
    for pos in (open_long, open_short):
        if pos is not None and last_bar is not None:
            c = last_bar["close"]
            pnl = (c - pos["entry_price"]) if pos["direction"] == "BUY" else (pos["entry_price"] - c)
            st = _state_for_epic(pos["epic_key"])
            rec = active_record.get(pos["epic_key"])
            if rec is not None:
                rec.update({"exit_ts": last_bar["ts"], "exit_price": c,
                            "exit_reason": "EOD", "pnl_pips": pnl,
                            "max_tier": str(st.get("_bbpr_tier") or "init")})

    out: List[FireFeature] = []
    for f in fires:
        if "pnl_pips" not in f:
            continue
        out.append(FireFeature(
            entry_ts=f["entry_ts"], direction=f["direction"],
            pnl_pips=f["pnl_pips"], exit_reason=f["exit_reason"],
            max_tier=f["max_tier"], bb_width_pips=f["bb_width_pips"],
            atr14_pips=f["atr14_pips"], cluster_size=f["cluster_size"],
            opp_60m=f["opp_60m"], hour_utc=f["hour_utc"],
        ))
    return out


# ─── Distribution helpers ──────────────────────────────────────────────────
def _stats(label, values: List[float]):
    if not values:
        return f"  {label}: (empty)"
    return (f"  {label}: n={len(values)}  "
            f"min={min(values):.1f}  med={median(values):.1f}  "
            f"mean={mean(values):.1f}  max={max(values):.1f}")


def _bin_counts(values: List[float], bins: List[Tuple[float, float, str]]):
    out = []
    for lo, hi, label in bins:
        c = sum(1 for v in values if lo <= v < hi)
        out.append((label, c, len(values)))
    return out


def _hour_bucket(h: int) -> str:
    if   7 <= h < 9:   return "07-09 (Lon-pre)"
    elif 9 <= h < 11:  return "09-11 (Lon-AM)"
    elif 11 <= h < 13: return "11-13 (Lunch)"
    elif 13 <= h < 15: return "13-15 (NY-AM)"
    elif 15 <= h < 17: return "15-17 (NY-late)"
    return "other"


def main():
    print("Computing features per fire...", file=sys.stderr)
    fires = run_backtest_with_features("2026-04-01", "2026-04-30")
    print(f"Captured {len(fires)} fires", file=sys.stderr)

    wins = [f for f in fires if f.pnl_pips > 0]
    losses = [f for f in fires if f.pnl_pips <= 0]

    print(f"\nApril 2026 fires: {len(fires)}  ({len(wins)} wins, {len(losses)} losses)")
    print(f"Net: {sum(f.pnl_pips for f in fires):+.1f}p")

    # ── Cluster size ───────────────────────────────────────────────────────
    print("\n## Cluster size (same-dir pierces in prior 30 min, incl. fire bar)")
    print(f"{'cluster':<10} {'wins':>6} {'losses':>8} {'win%':>6} {'net':>8} {'avg_pnl':>9}")
    for label, lo, hi in [("1 (single)", 1, 2), ("2", 2, 3), ("3", 3, 4),
                          ("4", 4, 5), ("5+", 5, 999)]:
        ws = [f for f in wins   if lo <= f.cluster_size < hi]
        ls = [f for f in losses if lo <= f.cluster_size < hi]
        n = len(ws) + len(ls)
        net = sum(f.pnl_pips for f in (ws + ls))
        wp = (len(ws) / n * 100) if n else 0.0
        avg = (net / n) if n else 0.0
        print(f"{label:<10} {len(ws):>6} {len(ls):>8} {wp:>5.1f}% {net:>+8.1f} {avg:>+8.2f}")

    # ── Opposite-dir context ───────────────────────────────────────────────
    print("\n## Opposite-direction pierce in prior 60 min (reversal context)")
    print(f"{'opp_60m':<8} {'wins':>6} {'losses':>8} {'win%':>6} {'net':>8} {'avg_pnl':>9}")
    for flag in (True, False):
        ws = [f for f in wins   if f.opp_60m == flag]
        ls = [f for f in losses if f.opp_60m == flag]
        n = len(ws) + len(ls)
        net = sum(f.pnl_pips for f in (ws + ls))
        wp = (len(ws) / n * 100) if n else 0.0
        avg = (net / n) if n else 0.0
        print(f"{str(flag):<8} {len(ws):>6} {len(ls):>8} {wp:>5.1f}% {net:>+8.1f} {avg:>+8.2f}")

    # ── BB width ───────────────────────────────────────────────────────────
    print("\n## BB width at pierce bar (pips)")
    print("  Wins:   " + _stats("bb_width", [f.bb_width_pips for f in wins]).strip())
    print("  Losses: " + _stats("bb_width", [f.bb_width_pips for f in losses]).strip())
    print(f"\n  {'bin':<14} {'wins':>6} {'losses':>8} {'win%':>6} {'net':>8} {'avg_pnl':>9}")
    for lo, hi, label in [(8, 15, "8-15p"), (15, 25, "15-25p"), (25, 40, "25-40p"),
                          (40, 60, "40-60p"), (60, 999, "60p+")]:
        ws = [f for f in wins   if lo <= f.bb_width_pips < hi]
        ls = [f for f in losses if lo <= f.bb_width_pips < hi]
        n = len(ws) + len(ls)
        net = sum(f.pnl_pips for f in (ws + ls))
        wp = (len(ws) / n * 100) if n else 0.0
        avg = (net / n) if n else 0.0
        print(f"  {label:<14} {len(ws):>6} {len(ls):>8} {wp:>5.1f}% {net:>+8.1f} {avg:>+8.2f}")

    # ── ATR ────────────────────────────────────────────────────────────────
    print("\n## ATR(14) on 5m at pierce bar (pips)")
    print("  Wins:   " + _stats("atr14",
        [f.atr14_pips for f in wins if f.atr14_pips is not None]).strip())
    print("  Losses: " + _stats("atr14",
        [f.atr14_pips for f in losses if f.atr14_pips is not None]).strip())
    print(f"\n  {'bin':<14} {'wins':>6} {'losses':>8} {'win%':>6} {'net':>8} {'avg_pnl':>9}")
    for lo, hi, label in [(0, 4, "<4p"), (4, 6, "4-6p"), (6, 9, "6-9p"),
                          (9, 14, "9-14p"), (14, 999, "14p+")]:
        ws = [f for f in wins   if f.atr14_pips and lo <= f.atr14_pips < hi]
        ls = [f for f in losses if f.atr14_pips and lo <= f.atr14_pips < hi]
        n = len(ws) + len(ls)
        net = sum(f.pnl_pips for f in (ws + ls))
        wp = (len(ws) / n * 100) if n else 0.0
        avg = (net / n) if n else 0.0
        print(f"  {label:<14} {len(ws):>6} {len(ls):>8} {wp:>5.1f}% {net:>+8.1f} {avg:>+8.2f}")

    # ── Hour buckets ───────────────────────────────────────────────────────
    print("\n## Hour of day (UTC bucket)")
    print(f"  {'bucket':<18} {'wins':>6} {'losses':>8} {'win%':>6} {'net':>8} {'avg_pnl':>9}")
    buckets = ["07-09 (Lon-pre)", "09-11 (Lon-AM)", "11-13 (Lunch)",
               "13-15 (NY-AM)",   "15-17 (NY-late)"]
    for b in buckets:
        ws = [f for f in wins   if _hour_bucket(f.hour_utc) == b]
        ls = [f for f in losses if _hour_bucket(f.hour_utc) == b]
        n = len(ws) + len(ls)
        net = sum(f.pnl_pips for f in (ws + ls))
        wp = (len(ws) / n * 100) if n else 0.0
        avg = (net / n) if n else 0.0
        print(f"  {b:<18} {len(ws):>6} {len(ls):>8} {wp:>5.1f}% {net:>+8.1f} {avg:>+8.2f}")

    # ── Probe missed May 1 setups ──────────────────────────────────────────
    print("\n## Why the two May 1 setups didn't fire")
    print("Setup A: 07:30 BST (06:30 UTC) LONG single pierce, ran +30p")
    print("Setup B: 07:45 BST (06:45 UTC) SHORT 3-pierce cluster, ran +20p")

    # Load May 1 + warmup, scan bars 06:00-07:30 UTC
    rows_may1 = _load_5m("2026-05-01")
    pre = _load_5m("2026-04-30")
    warmup_closes = [r["close"] for r in pre[-bbb.BB_PERIOD:]]
    # Walk every bar from 06:00 to 08:00 UTC, print BB / pierce / window status
    print()
    print(f"  {'ts_UTC':<8} {'low':<8} {'high':<8} {'close':<8} "
          f"{'BBl':<8} {'BBu':<8} {'width':>7} {'pierce':<7} {'in_win':<7} {'fire?':<6}")
    closes = list(warmup_closes)
    for r in rows_may1:
        closes.append(r["close"])
        if len(closes) < bbb.BB_PERIOD:
            continue
        bb = _bb_20_2(closes)
        if bb is None:
            continue
        bbl, _bm, bbu = bb
        h = r["ts"].hour; mt = r["ts"].minute
        if h < 6 or (h == 8 and mt > 0) or h > 8:
            continue
        long_p  = (bbl - r["low"])  >= bbb.PIERCE_THRESH_PIPS
        short_p = (r["high"] - bbu) >= bbb.PIERCE_THRESH_PIPS
        width = (bbu - bbl) / PIP_SIZE
        if long_p and short_p:
            pdir = "BOTH"
        elif long_p:
            pdir = "LONG"
        elif short_p:
            pdir = "SHORT"
        else:
            pdir = "—"
        in_window = (bbb.WIN_START <= r["ts"].timetz().replace(tzinfo=None) < bbb.WIN_END)
        # Would the strategy fire?
        gate_pass = (pdir in ("LONG", "SHORT")) and (width >= bbb.BB_WIDTH_FLOOR_PIPS) and in_window
        print(f"  {r['ts'].strftime('%H:%M'):<8} {r['low']:<8.1f} {r['high']:<8.1f} "
              f"{r['close']:<8.1f} {bbl:<8.1f} {bbu:<8.1f} {width:>6.1f}p "
              f"{pdir:<7} {str(in_window):<7} {'YES' if gate_pass else 'no':<6}")


if __name__ == "__main__":
    main()
