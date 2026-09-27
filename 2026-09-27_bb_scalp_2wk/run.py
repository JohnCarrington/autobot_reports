#!/usr/bin/env python3
"""Bollinger reversal scalp — two trading weeks executable-price sweep.

Reads every 5m bid/ask CSV under ./data/<PAIR>/ and, for Fri 2026-09-25,
aggregates the 1m bid/ask CSV to 5m bars. Applies the causal BB(20,2)
rejection rule (identical to the Friday-only study, see
../2026-09-25_bb_scalp/report.md §2) at the OPEN of bar i+1, then
resolves TP/SL for every (TP, SL) combo using EXECUTABLE prices:

    BUY  opens at ask,  closes at bid
    SELL opens at bid,  closes at ask

Path metrics:
    BUY :  MFE_pips = max(bid_high) - entry_ask;    MAE_pips = entry_ask - min(bid_low)
    SELL:  MFE_pips = entry_bid - min(ask_low);     MAE_pips = max(ask_high) - entry_bid

Per pair 1 point = 1 pip on IG spread-bet FX (see trade_executor.py:437-443
and the level_ladder comment). File values are stored as IG's "points" —
divide by 10000 for the real price.

Read-only: no orders, no service changes, no live config changes.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
from collections import defaultdict, OrderedDict
from pathlib import Path
from statistics import mean, median
from typing import Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
OUT_DIR = HERE

PAIRS = ["GBPUSD", "EURUSD"]
DIRECTIONS = ["BUY", "SELL"]

# TP/SL grid — user spec:
#   TP ∈ {5, 8, 10} pips
#   SL ∈ [broker_min .. 16] pips
TP_LIST = [5, 8, 10]

# Broker minima captured live 2026-09-27 (dealing_rules.json).
# minNormalStopOrLimitDistance from IG DEMO SPREADBET dealingRules.
CURRENT_IG_MIN_STOP = {"GBPUSD": 4, "EURUSD": 2}
# Bot's configured floor (trade_executor.py:437-443) — used historically:
BOT_MIN_STOP = {"GBPUSD": 12, "EURUSD": 6}

# BB parameters (unchanged from Friday study)
BB_PERIOD = 20
BB_STDDEV = 2.0

# Two-slot cap
MAX_CONCURRENT = 2


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def _read_csv(path: Path) -> List[dict]:
    rows: List[dict] = []
    with open(path) as fh:
        r = csv.DictReader(fh)
        for row in r:
            rows.append(row)
    return rows


def _iso_to_dt(s: str) -> dt.datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s)


def _row_to_bar(row: dict) -> Optional[dict]:
    try:
        ts = _iso_to_dt(row["timestamp"])
    except (KeyError, ValueError):
        return None
    out = {"ts": ts}
    for f in ("bid_open", "bid_high", "bid_low", "bid_close",
              "ask_open", "ask_high", "ask_low", "ask_close"):
        v = row.get(f)
        if v is None or v == "":
            return None
        try:
            out[f] = float(v)
        except ValueError:
            return None
    return out


def _aggregate_1m_to_5m(rows: List[dict]) -> List[dict]:
    """Group consecutive 1-min bid/ask bars into 5-min bars anchored on
    UTC minute boundaries (0,5,10,15,...,55). Only emits a 5m bar if the
    group has bars whose starts fall inside [anchor, anchor+5min).
    """
    out: List[dict] = []
    groups: "OrderedDict[dt.datetime, List[dict]]" = OrderedDict()
    for r in rows:
        b = _row_to_bar(r)
        if b is None:
            continue
        ts = b["ts"]
        anchor = ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)
        groups.setdefault(anchor, []).append(b)
    for anchor, group in groups.items():
        group.sort(key=lambda x: x["ts"])
        first = group[0]
        last = group[-1]
        out.append({
            "ts": anchor,
            "bid_open": first["bid_open"],
            "bid_close": last["bid_close"],
            "bid_high": max(g["bid_high"] for g in group),
            "bid_low": min(g["bid_low"] for g in group),
            "ask_open": first["ask_open"],
            "ask_close": last["ask_close"],
            "ask_high": max(g["ask_high"] for g in group),
            "ask_low": min(g["ask_low"] for g in group),
        })
    return out


def load_pair_bars(pair: str) -> Tuple[List[dict], Dict[str, dict]]:
    """Return (5m bid/ask bars sorted by ts, provenance-per-day)."""
    pair_dir = DATA_DIR / pair
    bars_by_ts: "OrderedDict[dt.datetime, dict]" = OrderedDict()
    provenance: Dict[str, dict] = {}
    files = sorted(pair_dir.glob("*.csv"))
    for f in files:
        stem = f.stem  # e.g. 2026-09-25_minute_bidask or 2026-09-14_minute_5_bidask
        date_str = stem.split("_")[0]
        raw = _read_csv(f)
        if "minute_5" in stem:
            bars = [b for b in (_row_to_bar(r) for r in raw) if b is not None]
            src = "MINUTE_5"
        elif "_minute_bidask" in stem:
            bars = _aggregate_1m_to_5m(raw)
            src = "MINUTE(→5m agg)"
        else:
            continue
        # Track provenance (day = ts.date() of first bar in the fetch)
        if bars:
            first_ts = bars[0]["ts"]
            last_ts = bars[-1]["ts"]
            provenance[date_str] = {
                "src": src,
                "file": f.name,
                "raw_rows": len(raw),
                "bars_after_aggregation": len(bars),
                "first_ts": first_ts.isoformat(),
                "last_ts": last_ts.isoformat(),
            }
        for b in bars:
            # Later fetches for the same anchor overwrite earlier
            bars_by_ts[b["ts"]] = b
    sorted_bars = [bars_by_ts[k] for k in sorted(bars_by_ts.keys())]
    return sorted_bars, provenance


# --------------------------------------------------------------------------
# BB and candidate detection
# --------------------------------------------------------------------------

def _stdev(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / n  # population stdev — matches numpy default when ddof=0
    return math.sqrt(var)


def bollinger(closes: List[float], period: int = BB_PERIOD, k: float = BB_STDDEV):
    """Yield (mid, upper, lower) for each bar, None until enough data."""
    for i in range(len(closes)):
        if i + 1 < period:
            yield (None, None, None)
            continue
        window = closes[i + 1 - period : i + 1]
        mu = sum(window) / period
        sd = _stdev(window)
        yield (mu, mu + k * sd, mu - k * sd)


def detect_candidates(bars: List[dict]) -> List[dict]:
    """Rejection detection on 5m MID close (identical to Friday study).

    Returns a list of candidate dicts, each already carrying the executable
    entry price at OPEN of bar i+1:
      side, band, bar_index, bar_ts, entry_ts, entry_bid_open, entry_ask_open,
      mid_close_i, upper_i, lower_i, middle_i
    """
    if not bars:
        return []
    mid_close = [(b["bid_close"] + b["ask_close"]) / 2.0 for b in bars]
    mid_high  = [(b["bid_high"] + b["ask_high"])   / 2.0 for b in bars]
    mid_low   = [(b["bid_low"]  + b["ask_low"])    / 2.0 for b in bars]
    bbs = list(bollinger(mid_close))
    candidates: List[dict] = []
    # Re-key state: which side is currently blocked awaiting a middle-cross
    upper_blocked = False  # True while a prior upper-rejection is not cleared
    lower_blocked = False
    for i in range(len(bars) - 1):
        mid_i, up_i, lo_i = bbs[i]
        if mid_i is None:
            continue
        # Clear blocks when close crosses back through middle
        if upper_blocked and mid_close[i] < mid_i:
            upper_blocked = False
        if lower_blocked and mid_close[i] > mid_i:
            lower_blocked = False
        upper_touch = mid_high[i] >= up_i
        lower_touch = mid_low[i]  <= lo_i
        upper_rej   = upper_touch and mid_close[i] < up_i and not upper_blocked
        lower_rej   = lower_touch and mid_close[i] > lo_i and not lower_blocked
        # Only one side can fire per bar; if both, prefer the stronger rejection
        # (largest pierce). In practice rare on FX 5m.
        if upper_rej and lower_rej:
            up_pierce = mid_high[i] - up_i
            lo_pierce = lo_i - mid_low[i]
            if up_pierce >= lo_pierce:
                lower_rej = False
            else:
                upper_rej = False
        if upper_rej:
            nxt = bars[i + 1]
            candidates.append({
                "side": "SELL", "band": "UPPER",
                "bar_index": i, "bar_ts": bars[i]["ts"],
                "entry_ts": nxt["ts"],
                # SELL opens at bid, closes at ask
                "entry_bid_open": nxt["bid_open"],
                "entry_ask_open": nxt["ask_open"],
                "mid_close_i": mid_close[i],
                "upper_i": up_i, "lower_i": lo_i, "middle_i": mid_i,
            })
            upper_blocked = True
        elif lower_rej:
            nxt = bars[i + 1]
            candidates.append({
                "side": "BUY", "band": "LOWER",
                "bar_index": i, "bar_ts": bars[i]["ts"],
                "entry_ts": nxt["ts"],
                # BUY opens at ask, closes at bid
                "entry_bid_open": nxt["bid_open"],
                "entry_ask_open": nxt["ask_open"],
                "mid_close_i": mid_close[i],
                "upper_i": up_i, "lower_i": lo_i, "middle_i": mid_i,
            })
            lower_blocked = True
    return candidates


# --------------------------------------------------------------------------
# TP/SL resolution on executable price path
# --------------------------------------------------------------------------

def resolve_trade(bars: List[dict], cand: dict, tp_pips: float, sl_pips: float) -> dict:
    """Simulate one trade using executable prices.

    BUY :  entry = entry_ask_open; TP hit when bid_high >= entry + tp;
                                     SL hit when bid_low  <= entry - sl.
           MFE = max(bid_high) - entry;    MAE = entry - min(bid_low).
    SELL:  entry = entry_bid_open; TP hit when ask_low  <= entry - tp;
                                     SL hit when ask_high >= entry + sl.
           MFE = entry - min(ask_low);     MAE = max(ask_high) - entry.

    Same-bar TP+SL → resolution = "UNRESOLVED" (ambiguous first-touch).
    Runs off end of series → resolution = "UNRESOLVED" (path ambiguous).
    """
    i0 = cand["bar_index"] + 1  # first bar after signal is the entry bar
    if i0 >= len(bars):
        return {"resolution": "UNRESOLVED", "reason": "no_entry_bar"}
    side = cand["side"]
    entry_bid = cand["entry_bid_open"]
    entry_ask = cand["entry_ask_open"]
    if side == "BUY":
        entry = entry_ask
        tp_px = entry + tp_pips
        sl_px = entry - sl_pips
    else:  # SELL
        entry = entry_bid
        tp_px = entry - tp_pips
        sl_px = entry + sl_pips
    mfe = 0.0
    mae = 0.0
    exit_ts = None
    resolution = "UNRESOLVED"
    net_pips = 0.0
    exit_price = None
    for j in range(i0, len(bars)):
        b = bars[j]
        if side == "BUY":
            hi = b["bid_high"]
            lo = b["bid_low"]
            mfe = max(mfe, hi - entry)
            mae = max(mae, entry - lo)
            hit_tp = hi >= tp_px
            hit_sl = lo <= sl_px
            if hit_tp and hit_sl:
                resolution = "AMBIGUOUS"
                exit_ts = b["ts"]
                net_pips = 0.0  # unresolved; caller may reclassify
                exit_price = None
                break
            if hit_tp:
                resolution = "TP"
                exit_ts = b["ts"]
                exit_price = tp_px
                net_pips = tp_pips
                break
            if hit_sl:
                resolution = "SL"
                exit_ts = b["ts"]
                exit_price = sl_px
                net_pips = -sl_pips
                break
        else:
            hi = b["ask_high"]
            lo = b["ask_low"]
            mfe = max(mfe, entry - lo)
            mae = max(mae, hi - entry)
            hit_tp = lo <= tp_px
            hit_sl = hi >= sl_px
            if hit_tp and hit_sl:
                resolution = "AMBIGUOUS"
                exit_ts = b["ts"]
                net_pips = 0.0
                exit_price = None
                break
            if hit_tp:
                resolution = "TP"
                exit_ts = b["ts"]
                exit_price = tp_px
                net_pips = tp_pips
                break
            if hit_sl:
                resolution = "SL"
                exit_ts = b["ts"]
                exit_price = sl_px
                net_pips = -sl_pips
                break
    else:
        # Fell off end — mark path-truncated
        last = bars[-1] if bars else None
        if last is not None:
            resolution = "UNRESOLVED"
            exit_ts = last["ts"]
            # Realised at last bar's *closing* executable price
            if side == "BUY":
                exit_price = last["bid_close"]
                net_pips = last["bid_close"] - entry
            else:
                exit_price = last["ask_close"]
                net_pips = entry - last["ask_close"]
    return {
        "resolution": resolution,
        "entry_ts": cand["entry_ts"], "exit_ts": exit_ts,
        "entry_price": entry, "exit_price": exit_price,
        "mfe_pips": mfe, "mae_pips": mae,
        "net_pips": net_pips,
    }


# --------------------------------------------------------------------------
# Two-slot admission (chronological, no-overlap on the same pair)
# --------------------------------------------------------------------------

def apply_two_slot(all_trades: List[dict]) -> List[dict]:
    """Sort chronologically by entry_ts; admit up to MAX_CONCURRENT open
    trades. Skip trades whose entry_ts falls while too many are open.
    Also block a second open on the same pair (no overlapping same-pair).
    Returns the trades list annotated with 'admitted' (bool) and
    'admit_reason' ('two_slot_full' | 'same_pair_open' | 'admitted').
    """
    open_slots: List[dict] = []  # active trades, sorted by exit_ts
    out: List[dict] = []
    for tr in sorted(all_trades, key=lambda t: (t["entry_ts"], t["pair"], t["side"])):
        # Retire any that closed before this entry
        open_slots = [o for o in open_slots
                      if o.get("exit_ts") and o["exit_ts"] > tr["entry_ts"]]
        # Same-pair overlap block
        same_pair_open = any(o["pair"] == tr["pair"] for o in open_slots)
        if same_pair_open:
            tr = dict(tr, admitted=False, admit_reason="same_pair_open")
        elif len(open_slots) >= MAX_CONCURRENT:
            tr = dict(tr, admitted=False, admit_reason="two_slot_full")
        else:
            tr = dict(tr, admitted=True, admit_reason="admitted")
            open_slots.append(tr)
        out.append(tr)
    return out


# --------------------------------------------------------------------------
# Aggregation into report tables
# --------------------------------------------------------------------------

def _summarise(trades: List[dict], require_admitted: bool = False):
    if require_admitted:
        trades = [t for t in trades if t.get("admitted")]
    n = len(trades)
    tp_count = sum(1 for t in trades if t["resolution"] == "TP")
    sl_count = sum(1 for t in trades if t["resolution"] == "SL")
    unr_count = sum(1 for t in trades if t["resolution"] in ("UNRESOLVED", "AMBIGUOUS"))
    net = sum(t["net_pips"] for t in trades)
    wins = tp_count + sum(1 for t in trades
                          if t["resolution"] == "UNRESOLVED" and t["net_pips"] > 0)
    losses = sl_count + sum(1 for t in trades
                            if t["resolution"] == "UNRESOLVED" and t["net_pips"] < 0)
    wr = (wins / n) if n else 0.0
    mfe = [t["mfe_pips"] for t in trades] or [0.0]
    mae = [t["mae_pips"] for t in trades] or [0.0]
    # max drawdown = worst running sum of ordered trades (chronological)
    running = 0.0
    peak = 0.0
    trough = 0.0
    for t in sorted(trades, key=lambda x: x["entry_ts"]):
        running += t["net_pips"]
        peak = max(peak, running)
        trough = min(trough, running - peak)
    max_dd = trough
    return {
        "taken": n,
        "TP": tp_count, "SL": sl_count, "UNR": unr_count,
        "wins": wins, "losses": losses,
        "win_rate": wr,
        "net_pips": net,
        "net_per_trade": (net / n) if n else 0.0,
        "mfe_mean": mean(mfe), "mfe_med": median(mfe), "mfe_max": max(mfe),
        "mae_mean": mean(mae), "mae_med": median(mae), "mae_max": max(mae),
        "max_dd": max_dd,
    }


def positive_days(trades_admitted: List[dict]) -> Tuple[int, int, dict]:
    per_day: Dict[str, float] = defaultdict(float)
    for t in trades_admitted:
        d = t["entry_ts"].date().isoformat()
        per_day[d] += t["net_pips"]
    pos = sum(1 for v in per_day.values() if v > 0)
    days = len(per_day)
    return pos, days, dict(per_day)


# --------------------------------------------------------------------------
# Main runner
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-prefix", default="sweep")
    args = ap.parse_args()

    # Load bars per pair
    pair_bars: Dict[str, List[dict]] = {}
    provenance: Dict[str, Dict[str, dict]] = {}
    for pair in PAIRS:
        bars, prov = load_pair_bars(pair)
        pair_bars[pair] = bars
        provenance[pair] = prov
    with open(OUT_DIR / "provenance.json", "w") as fh:
        json.dump(provenance, fh, indent=2, default=str)

    # Detect candidates per pair
    all_candidates: List[dict] = []
    for pair in PAIRS:
        cands = detect_candidates(pair_bars[pair])
        for c in cands:
            c2 = dict(c)
            c2["pair"] = pair
            all_candidates.append(c2)

    # Persist candidates
    with open(OUT_DIR / "candidates.csv", "w", newline="") as fh:
        if all_candidates:
            fields = ["pair", "side", "band", "bar_ts", "entry_ts",
                      "entry_bid_open", "entry_ask_open",
                      "mid_close_i", "upper_i", "lower_i", "middle_i"]
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for c in all_candidates:
                w.writerow({k: c.get(k) for k in fields})

    # Full grid sweep: for each pair × direction × (TP, SL) resolve trades
    # We also produce combined-pair summaries and two-slot summaries.

    # For efficiency, resolve every candidate once per (TP, SL); cache by (pair, cand_idx, tp, sl).
    grid_rows: List[dict] = []
    combined_rows: List[dict] = []
    two_slot_rows: List[dict] = []
    per_pair_dir_rows: List[dict] = []
    friday_rows: List[dict] = []
    daily_rows: List[dict] = []

    SL_MAX = 16

    for tp in TP_LIST:
        # Sweep SL from min(2) to 16 (2 is EURUSD current IG min).
        for sl in range(2, SL_MAX + 1):
            # Per-pair trades at this (tp, sl)
            trades_by_pair: Dict[str, List[dict]] = {"GBPUSD": [], "EURUSD": []}
            for cand in all_candidates:
                pair = cand["pair"]
                broker_min = CURRENT_IG_MIN_STOP[pair]
                bars = pair_bars[pair]
                res = resolve_trade(bars, cand, tp, sl)
                tr = {
                    "pair": pair, "side": cand["side"], "band": cand["band"],
                    "tp": tp, "sl": sl,
                    "broker_valid_current": sl >= CURRENT_IG_MIN_STOP[pair],
                    "broker_valid_bot": sl >= BOT_MIN_STOP[pair],
                    "entry_ts": cand["entry_ts"],
                    "bar_ts": cand["bar_ts"],
                    **res,
                }
                trades_by_pair[pair].append(tr)

            # Per-pair × per-direction summary rows
            for pair in PAIRS:
                broker_min_current = CURRENT_IG_MIN_STOP[pair]
                broker_valid_current = sl >= broker_min_current
                for direction in DIRECTIONS:
                    dt_trades = [t for t in trades_by_pair[pair] if t["side"] == direction]
                    stats = _summarise(dt_trades) if broker_valid_current else _summarise([])
                    per_pair_dir_rows.append({
                        "tp": tp, "sl": sl,
                        "pair": pair, "direction": direction,
                        "broker_valid_current": broker_valid_current,
                        "broker_valid_bot": sl >= BOT_MIN_STOP[pair],
                        **stats,
                    })
                # Per-pair aggregate (both directions)
                pair_trades = trades_by_pair[pair] if broker_valid_current else []
                stats = _summarise(pair_trades)
                grid_rows.append({
                    "tp": tp, "sl": sl,
                    "pair": pair, "direction": "BOTH",
                    "broker_valid_current": broker_valid_current,
                    "broker_valid_bot": sl >= BOT_MIN_STOP[pair],
                    **stats,
                })

            # Combined unlimited concurrency (both pairs)
            broker_valid_gbp = sl >= CURRENT_IG_MIN_STOP["GBPUSD"]
            broker_valid_eur = sl >= CURRENT_IG_MIN_STOP["EURUSD"]
            all_trades: List[dict] = []
            if broker_valid_gbp:
                all_trades.extend(trades_by_pair["GBPUSD"])
            if broker_valid_eur:
                all_trades.extend(trades_by_pair["EURUSD"])
            unlimited = _summarise(all_trades)
            combined_rows.append({
                "tp": tp, "sl": sl,
                "broker_valid_gbp_current": broker_valid_gbp,
                "broker_valid_eur_current": broker_valid_eur,
                **unlimited,
            })

            # Two-slot admission
            trades_two = apply_two_slot(all_trades)
            two_slot = _summarise(trades_two, require_admitted=True)
            skipped_two_slot = sum(1 for t in trades_two if not t["admitted"] and t["admit_reason"] == "two_slot_full")
            skipped_same_pair = sum(1 for t in trades_two if not t["admitted"] and t["admit_reason"] == "same_pair_open")
            two_slot_rows.append({
                "tp": tp, "sl": sl,
                "broker_valid_gbp_current": broker_valid_gbp,
                "broker_valid_eur_current": broker_valid_eur,
                "skipped_two_slot": skipped_two_slot,
                "skipped_same_pair": skipped_same_pair,
                **two_slot,
            })

            # Friday-only isolated slice
            friday = dt.date(2026, 9, 25)
            friday_trades_all = [t for t in all_trades if t["entry_ts"].date() == friday]
            friday_unl = _summarise(friday_trades_all)
            friday_two = apply_two_slot([t for t in all_trades if t["entry_ts"].date() == friday])
            friday_two_stat = _summarise(friday_two, require_admitted=True)
            friday_rows.append({
                "tp": tp, "sl": sl, "scope": "unlimited",
                **friday_unl,
            })
            friday_rows.append({
                "tp": tp, "sl": sl, "scope": "two_slot",
                "skipped_two_slot": sum(1 for t in friday_two if not t["admitted"] and t["admit_reason"] == "two_slot_full"),
                "skipped_same_pair": sum(1 for t in friday_two if not t["admitted"] and t["admit_reason"] == "same_pair_open"),
                **friday_two_stat,
            })

            # Per-day rows for the two-slot combo — record per (tp, sl)
            per_day: Dict[str, dict] = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0,
                                                            "unr": 0, "tp_hits": 0, "sl_hits": 0,
                                                            "net": 0.0})
            for t in trades_two:
                if not t["admitted"]:
                    continue
                d = t["entry_ts"].date().isoformat()
                per_day[d]["n"] += 1
                per_day[d]["net"] += t["net_pips"]
                if t["resolution"] == "TP":
                    per_day[d]["tp_hits"] += 1
                elif t["resolution"] == "SL":
                    per_day[d]["sl_hits"] += 1
                else:
                    per_day[d]["unr"] += 1
                if t["net_pips"] > 0:
                    per_day[d]["wins"] += 1
                elif t["net_pips"] < 0:
                    per_day[d]["losses"] += 1
            for d, v in per_day.items():
                daily_rows.append({"target_tp": tp, "target_sl": sl,
                                   "date": d, **v})

    # Write CSVs
    def _write(name: str, rows: List[dict]):
        if not rows:
            (OUT_DIR / f"{name}.csv").write_text("")
            return
        # Union of all keys, preserving insertion order of the first row
        fields: List[str] = list(rows[0].keys())
        seen = set(fields)
        for r in rows[1:]:
            for k in r.keys():
                if k not in seen:
                    fields.append(k)
                    seen.add(k)
        with open(OUT_DIR / f"{name}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    _write(f"{args.out_prefix}_per_pair_dir", per_pair_dir_rows)
    _write(f"{args.out_prefix}_per_pair", grid_rows)
    _write(f"{args.out_prefix}_combined_unlimited", combined_rows)
    _write(f"{args.out_prefix}_combined_two_slot", two_slot_rows)
    _write(f"{args.out_prefix}_friday_only", friday_rows)
    _write(f"{args.out_prefix}_daily_two_slot", daily_rows)

    # Emit a small summary manifest
    manifest = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pairs": PAIRS,
        "current_ig_min_stop": CURRENT_IG_MIN_STOP,
        "bot_min_stop": BOT_MIN_STOP,
        "candidates_per_pair": {p: sum(1 for c in all_candidates if c["pair"] == p) for p in PAIRS},
        "candidates_per_pair_side": {
            f"{p}_{s}": sum(1 for c in all_candidates if c["pair"] == p and c["side"] == s)
            for p in PAIRS for s in DIRECTIONS
        },
        "bars_per_pair": {p: len(pair_bars[p]) for p in PAIRS},
        "coverage_first_ts": {p: pair_bars[p][0]["ts"].isoformat() if pair_bars[p] else None for p in PAIRS},
        "coverage_last_ts": {p: pair_bars[p][-1]["ts"].isoformat() if pair_bars[p] else None for p in PAIRS},
    }
    with open(OUT_DIR / f"{args.out_prefix}_manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=2, default=str)

    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
