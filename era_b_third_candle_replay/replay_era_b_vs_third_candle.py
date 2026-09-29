#!/usr/bin/env python3
"""
Era B GBPUSD_BB_BOUNCE_S: baseline (rejection-close market SELL) vs
third-candle break-of-rejection-low alternative.

Read-only replay. No config, no service, no broker.

Inputs (paths hard-coded to production layout on host 161):
  1) Deal reference CSV (produced 2026-09-29):
     /opt/tradingbot/reports-public/host_161_bb_bounce_s_deal_reference_20260929.csv
     Provides the 36 Era B BB_BOUNCE_S deals with entry timestamp,
     entry price, SL applied, effective realised pips, MFE, MAE, close
     reason, session, etc. Baseline pnl comes from this ledger — it is
     the *actual* realised result of Era B and cannot be improved on by
     any candle replay.
  2) 5-minute GBPUSD candles:
     /opt/tradingbot/data/candles/GBPUSD/YYYY-MM-DD.csv
     Columns: timestamp,open,high,low,close  (timestamp = bar OPEN,
     UTC-aware, ISO 8601). Bar N with open=T covers [T, T+5min),
     closes at T+5min. Prices are in "IG points" — pip = 10 points.

Method:
  - Baseline: use ledger values verbatim (that is Era B as it ran).
  - Alt entry: for each of the 36 Era B setups, look up the rejection
    bar (bar that closed at floor_5m(entry_ts)) and the next 3 bars
    (N+1, N+2, N+3). Break trigger: first bar in {N+1,N+2,N+3} whose
    low < rejection_low. Fill price (conservative for a SHORT): if
    open of the trigger bar gapped below rejection_low, fill at that
    open; else fill at rejection_low (intra-bar stop trigger). Expiry:
    if none of the three bars breaks, the setup is MISSED.
  - Alt management: applied ONLY when alt fills. Uses Era B config:
      SL         = alt_entry + 20p    (hard stop)
      Scale-out  = alt_entry - 10p    (close 50%, runner to BE)
      Runner BE  = alt_entry          (SL after scale-out)
      Broker TP  = alt_entry - 100p
      Max hold   = 240 min (48 bars, REGIME_MAX_HOLD BB_PIERCE_RUN
                    override; if scale-out fired, exempt)
    Simulation walks 5-minute bars from bar N+k (the break bar) forward.
    Within-bar order: ADVERSE first (conservative — tests SL before
    scale-out / TP on the same bar).
  - Both trades stop at the same broker events. Structure exits,
    QM_BAND_CLOSE_INSIDE, BB_FLIP, LABEL_K_OPERATOR, PRE_NEWS_CLOSE
    and the other soft exits observed in the ledger are NOT
    replicated for the alt trade: 5m OHLC cannot decide them and they
    require live regime / operator input. This is documented as a
    simplification — the alt is measured against the HARD-outcome
    Era B stops (SL, scale-out+BE, broker TP, max-hold), which the
    baseline is compared to as well (see report §Method).

Outputs written to the same directory as this script:
  - era_b_baseline_vs_third_candle_20260929.csv  — per-deal comparison
  - era_b_summary_20260929.json                  — summary metrics
"""
import csv
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------- paths --------------------------------------

HERE            = Path(__file__).resolve().parent
REPO_ROOT       = Path("/opt/tradingbot")
DEAL_REF_CSV    = REPO_ROOT / "reports-public/host_161_bb_bounce_s_deal_reference_20260929.csv"
CANDLE_DIR      = REPO_ROOT / "data/candles/GBPUSD"
OUT_CSV         = HERE / "era_b_baseline_vs_third_candle_20260929.csv"
OUT_JSON        = HERE / "era_b_summary_20260929.json"

# ---------------------------- constants ----------------------------------
# Era B config (from spec §5, effective 2026-05-23 .. 2026-06-24)
# Price convention: /opt/tradingbot/data/candles/GBPUSD/ stores prices as
# GBPUSD mid × 10000 (i.e. 13436.65 CSV units = 1.343665 mid). Since 1 pip
# of GBPUSD = 0.0001, 1 pip = 1.0 CSV unit. Verified against the deal
# reference CSV: DIAAAAXMR2E6ZA2 (entry 13416.45, effective pnl −20.70p)
# implies SL was hit at ~13437.15 = entry + 20.7 units → 1 pip = 1 unit.
PIP_POINTS         = 1.0
SL_PIPS            = 20.0        # hard SL (widened from 12p at commit c85481c)
BROKER_TP_PIPS     = 100.0       # sentinel broker TP
SCALE_OUT_PIPS     = 10.0        # +10p MFE → scale 50 %
RUNNER_BE_OFFSET   = 0.0         # runner SL = entry (BE)
EXPIRY_BARS        = 3           # alt looks at N+1, N+2, N+3
MAX_HOLD_BARS      = 48          # REGIME_MAX_HOLD 240 min for BB_PIERCE_RUN
BAR_SECONDS        = 300
STAKE_PER_PIP_GBP  = 1.0         # £1/pip at size 1.0 (per audit §2 assumption)

# ---------------------------- helpers ------------------------------------

def parse_ts(s: str) -> datetime:
    # ledger uses '2026-05-29T07:05:04Z'
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

def floor_5m(ts: datetime) -> datetime:
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp((epoch // 300) * 300, tz=timezone.utc)

def pips_from_points(points: float) -> float:
    return points / PIP_POINTS

def points_from_pips(pips: float) -> float:
    return pips * PIP_POINTS

# ---------------------------- candle store -------------------------------

_CANDLE_CACHE: Dict[str, List[Dict[str, Any]]] = {}

def load_day(day: str) -> List[Dict[str, Any]]:
    if day in _CANDLE_CACHE:
        return _CANDLE_CACHE[day]
    p = CANDLE_DIR / f"{day}.csv"
    if not p.exists():
        _CANDLE_CACHE[day] = []
        return []
    rows: List[Dict[str, Any]] = []
    with open(p) as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append({
                "ts":    parse_ts(r["timestamp"].replace(" ", "T").replace("+00:00", "+00:00")),
                "open":  float(r["open"]),
                "high":  float(r["high"]),
                "low":   float(r["low"]),
                "close": float(r["close"]),
            })
    _CANDLE_CACHE[day] = rows
    return rows

def get_bar_by_open(ts_open: datetime) -> Optional[Dict[str, Any]]:
    """Return the bar whose timestamp (= bar open) equals ts_open."""
    day = ts_open.strftime("%Y-%m-%d")
    bars = load_day(day)
    # binary or linear search by ts equality (5m aligned)
    for b in bars:
        if b["ts"] == ts_open:
            return b
    return None

def get_bar_stream(start_open: datetime, n_bars: int) -> List[Dict[str, Any]]:
    """Return up to n_bars consecutive bars starting at open=start_open,
    walking across day boundaries. Skips gaps (weekend/holiday) — the
    5m stream in `data/candles/GBPUSD/` already has weekends absent."""
    out: List[Dict[str, Any]] = []
    cursor = start_open
    guard = 0
    while len(out) < n_bars and guard < n_bars * 4:
        guard += 1
        b = get_bar_by_open(cursor)
        if b is not None:
            out.append(b)
            cursor = b["ts"] + timedelta(seconds=BAR_SECONDS)
        else:
            # try next 5m slot — allows skipping session gaps
            cursor = cursor + timedelta(seconds=BAR_SECONDS)
            # if we jump a full weekend (2 calendar days without any
            # bar), stop rather than wander into next Monday's data —
            # the alt trade wouldn't survive that.
            day = cursor.strftime("%Y-%m-%d")
            if not load_day(day):
                # walk forward at most one calendar day gap
                cursor = cursor + timedelta(days=1)
                if not load_day(cursor.strftime("%Y-%m-%d")):
                    break
    return out

# ---------------------------- alt entry ----------------------------------

def find_alt_entry(rejection_bar_open: datetime, rejection_low: float
                   ) -> Tuple[Optional[Dict[str, Any]], Optional[float], Optional[int]]:
    """Look for a break of rejection_low in bars N+1, N+2, N+3.
    Returns (break_bar, fill_price, bar_index) or (None, None, None) if
    no break within EXPIRY_BARS.

    Fill price is conservative for a SHORT:
      - if open of trigger bar <= rejection_low (gap through):
          fill = open of trigger bar (worse than trigger)
      - else (intra-bar break):
          fill = rejection_low (stop triggered on the way down)
    """
    for k in range(1, EXPIRY_BARS + 1):
        next_open_ts = rejection_bar_open + timedelta(seconds=BAR_SECONDS * k)
        b = get_bar_by_open(next_open_ts)
        if b is None:
            # Session gap — skip; alt cannot trigger on a bar that
            # doesn't exist. The setup is treated as still open until
            # EXPIRY_BARS elapse of real bars.
            continue
        if b["low"] < rejection_low:
            fill = min(b["open"], rejection_low)
            return b, fill, k
    return None, None, None

# ---------------------------- management sim -----------------------------

def sim_short_management(alt_entry: float, break_bar: Dict[str, Any],
                         ) -> Dict[str, Any]:
    """5-minute bar-by-bar management of a SHORT position entered at
    alt_entry on the break bar. Adverse-first within-bar ordering.

    Returns dict:
      exit_ts_open   ISO time of the bar the position closed on
      exit_reason    one of SL, TP, SCALE_OUT_BE, MAX_HOLD, OPEN_END
      alt_pips       realised pips (weighted for scale-out)
      mfe_pips       max favorable during the alt trade (positive = down)
      mae_pips       max adverse during the alt trade (positive = up)
      duration_bars  bars held (from break bar inclusive)
      scaled_out     bool
      runner_exit_pips   contribution of the runner half (if scaled)
    """
    entry_pts = alt_entry
    sl_price  = entry_pts + points_from_pips(SL_PIPS)     # for SHORT, above entry
    tp_price  = entry_pts - points_from_pips(BROKER_TP_PIPS)  # for SHORT, below
    so_price  = entry_pts - points_from_pips(SCALE_OUT_PIPS)  # 10p favorable
    be_price  = entry_pts                                     # runner SL after scale

    stream = get_bar_stream(break_bar["ts"], MAX_HOLD_BARS)
    if not stream:
        return {
            "exit_ts_open": break_bar["ts"].isoformat(),
            "exit_reason": "NO_STREAM",
            "alt_pips": 0.0,
            "mfe_pips": 0.0,
            "mae_pips": 0.0,
            "duration_bars": 0,
            "scaled_out": False,
            "runner_exit_pips": 0.0,
        }
    scaled_out = False
    runner_active = False
    mfe = 0.0   # favorable = downward for SHORT
    mae = 0.0   # adverse   = upward   for SHORT
    banked_pips = 0.0        # from scale-out half
    runner_exit_pips = 0.0
    exit_reason = None
    exit_ts_open: Optional[datetime] = None
    duration_bars = 0

    for i, bar in enumerate(stream, start=1):
        duration_bars = i
        # First bar (break bar): entry price is alt_entry, which sits
        # at rejection_low or the bar's open (gap-through). The bar's
        # high/low from that moment onward is not knowable — 5m OHLC
        # aggregates the whole bar. Conservative assumption: entry
        # happens near the top of the down-move (rejection_low from
        # above), so the remainder of the bar's high may or may not
        # have already occurred. We treat bar[i]'s full high/low as
        # accessible for adverse+favorable checks. This is the
        # standard OHLC-simulation compromise, and it favours the
        # adverse side (SL) on i=1 because it counts the whole bar's
        # high, some of which pre-dates entry.
        bar_high = bar["high"]
        bar_low  = bar["low"]

        # Update MFE / MAE
        f_move_pips = pips_from_points(entry_pts - bar_low)   # +ve when price fell
        a_move_pips = pips_from_points(bar_high - entry_pts)  # +ve when price rose
        if f_move_pips > mfe: mfe = f_move_pips
        if a_move_pips > mae: mae = a_move_pips

        # Runner management priority: SL / TP / manage
        if not runner_active:
            # Pre-scale phase. Adverse first (conservative):
            if bar_high >= sl_price:
                # Full SL hit — close entire position at -20p
                exit_reason = "SL"
                exit_ts_open = bar["ts"]
                # Both halves lose 20p (no scale-out fired yet)
                alt_pips = -SL_PIPS
                return {
                    "exit_ts_open": exit_ts_open.isoformat(),
                    "exit_reason": exit_reason,
                    "alt_pips": alt_pips,
                    "mfe_pips": round(mfe, 2),
                    "mae_pips": round(mae, 2),
                    "duration_bars": duration_bars,
                    "scaled_out": False,
                    "runner_exit_pips": 0.0,
                }
            if bar_low <= tp_price:
                # Full broker TP hit — close whole at +100p
                exit_reason = "TP"
                exit_ts_open = bar["ts"]
                return {
                    "exit_ts_open": exit_ts_open.isoformat(),
                    "exit_reason": exit_reason,
                    "alt_pips": BROKER_TP_PIPS,
                    "mfe_pips": round(mfe, 2),
                    "mae_pips": round(mae, 2),
                    "duration_bars": duration_bars,
                    "scaled_out": False,
                    "runner_exit_pips": 0.0,
                }
            if bar_low <= so_price:
                # Scale-out fires — bank +10p on half, runner to BE
                scaled_out = True
                runner_active = True
                banked_pips = SCALE_OUT_PIPS  # on 50 %
                # continue this same bar for runner management (BE stop
                # could hit on the rebound within the same bar).
                # Note: adverse-first ordering was used above, so we
                # already tested bar_high against sl_price and passed.
                # For the runner, sl is now at BE (= entry_pts).
                if bar_high >= be_price:
                    # Rebound triggered BE within same bar
                    runner_exit_pips = 0.0
                    exit_reason = "SCALE_OUT_BE"
                    exit_ts_open = bar["ts"]
                    alt_pips = 0.5 * banked_pips + 0.5 * runner_exit_pips
                    return {
                        "exit_ts_open": exit_ts_open.isoformat(),
                        "exit_reason": exit_reason,
                        "alt_pips": alt_pips,
                        "mfe_pips": round(mfe, 2),
                        "mae_pips": round(mae, 2),
                        "duration_bars": duration_bars,
                        "scaled_out": True,
                        "runner_exit_pips": runner_exit_pips,
                    }
                # Otherwise continue to next bar with runner_active=True.
                continue
            # Nothing happened this bar — carry on.
            continue

        # runner_active — SL is BE (= entry_pts), TP is broker TP.
        if bar_high >= be_price:
            runner_exit_pips = 0.0
            exit_reason = "SCALE_OUT_BE"
            exit_ts_open = bar["ts"]
            alt_pips = 0.5 * banked_pips + 0.5 * runner_exit_pips
            return {
                "exit_ts_open": exit_ts_open.isoformat(),
                "exit_reason": exit_reason,
                "alt_pips": alt_pips,
                "mfe_pips": round(mfe, 2),
                "mae_pips": round(mae, 2),
                "duration_bars": duration_bars,
                "scaled_out": True,
                "runner_exit_pips": runner_exit_pips,
            }
        if bar_low <= tp_price:
            runner_exit_pips = BROKER_TP_PIPS
            exit_reason = "SCALE_OUT_TP"
            exit_ts_open = bar["ts"]
            alt_pips = 0.5 * banked_pips + 0.5 * runner_exit_pips
            return {
                "exit_ts_open": exit_ts_open.isoformat(),
                "exit_reason": exit_reason,
                "alt_pips": alt_pips,
                "mfe_pips": round(mfe, 2),
                "mae_pips": round(mae, 2),
                "duration_bars": duration_bars,
                "scaled_out": True,
                "runner_exit_pips": runner_exit_pips,
            }

    # Fell through MAX_HOLD_BARS.
    # For scaled-out positions, REGIME_MAX_HOLD is exempted by default
    # (per spec §3.7). Close at last bar's close, mark OPEN_END so it
    # is not confused with a real broker fill.
    last = stream[-1]
    if runner_active:
        runner_exit_pips = pips_from_points(entry_pts - last["close"])
        alt_pips = 0.5 * banked_pips + 0.5 * runner_exit_pips
        exit_reason = "OPEN_END_SCALED"
    else:
        exit_pips = pips_from_points(entry_pts - last["close"])
        alt_pips = exit_pips
        exit_reason = "OPEN_END"
    return {
        "exit_ts_open": last["ts"].isoformat(),
        "exit_reason": exit_reason,
        "alt_pips": round(alt_pips, 2),
        "mfe_pips": round(mfe, 2),
        "mae_pips": round(mae, 2),
        "duration_bars": duration_bars,
        "scaled_out": scaled_out,
        "runner_exit_pips": round(runner_exit_pips, 2),
    }

# ---------------------------- main ---------------------------------------

def main() -> None:
    rows = list(csv.DictReader(open(DEAL_REF_CSV)))
    era_b = [r for r in rows if r["era"] == "B_20p_SL_no_regime_arm"]
    assert len(era_b) == 36, f"Expected 36 Era B deals, got {len(era_b)}"

    out_rows: List[Dict[str, Any]] = []
    for r in era_b:
        entry_ts = parse_ts(r["timestamp_open"])
        floor_ts = floor_5m(entry_ts)           # rejection bar CLOSE time
        rej_open = floor_ts - timedelta(seconds=BAR_SECONDS)  # rejection bar OPEN
        setup_open = rej_open - timedelta(seconds=BAR_SECONDS)

        rej_bar   = get_bar_by_open(rej_open)
        setup_bar = get_bar_by_open(setup_open)
        base_entry = float(r["entry_price"])

        # Sanity check: rejection bar close should closely match ledger entry_price
        # (ledger records cur.close as entry, per gbpusd_bb_bounce.py:3174).
        if rej_bar is not None:
            close_match = abs(rej_bar["close"] - base_entry) < 0.2  # within 0.02 pips
        else:
            close_match = False

        break_bar, alt_entry, break_k = (None, None, None)
        if rej_bar is not None:
            break_bar, alt_entry, break_k = find_alt_entry(rej_open, rej_bar["low"])

        alt_result: Dict[str, Any] = {}
        if alt_entry is not None:
            alt_result = sim_short_management(alt_entry, break_bar)
        else:
            alt_result = {
                "exit_ts_open": "",
                "exit_reason": "MISSED",
                "alt_pips": 0.0,
                "mfe_pips": 0.0,
                "mae_pips": 0.0,
                "duration_bars": 0,
                "scaled_out": False,
                "runner_exit_pips": 0.0,
            }

        # Like-for-like baseline: same 4-exit simulator (SL / scale-out+BE
        # / broker TP / max-hold) applied to the ACTUAL entry price.
        # Isolates the entry-timing effect from the simulator's inability
        # to model TRAIL_STOP, QM_BAND_CLOSE_INSIDE, BB_FLIP,
        # STRUCTURE_EXIT and the other soft exits the actual Era B
        # trades used. The bar we walk forward from is the same
        # rejection bar N (the position was market-opened at cur.close;
        # the rest of bar N is the immediate management window).
        base_sim: Dict[str, Any] = {}
        if rej_bar is not None:
            base_sim = sim_short_management(base_entry, rej_bar)
        else:
            base_sim = {
                "exit_ts_open": "",
                "exit_reason": "NO_CANDLE",
                "alt_pips": 0.0,
                "mfe_pips": 0.0,
                "mae_pips": 0.0,
                "duration_bars": 0,
                "scaled_out": False,
                "runner_exit_pips": 0.0,
            }

        base_pips = float(r["effective_pnl_pips"]) if r["effective_pnl_pips"] else None
        base_close_reason = r["close_reason_canonical"]

        # Delta computed only when alt fired
        alt_pips = alt_result["alt_pips"] if alt_entry is not None else None
        diff = None
        if base_pips is not None and alt_pips is not None:
            diff = alt_pips - base_pips

        out_rows.append({
            "deal_id":                       r["deal_id"],
            "trade_date":                    entry_ts.strftime("%Y-%m-%d"),
            "setup_bar_open_utc":            setup_open.isoformat(),
            "setup_bar_high":                round(setup_bar["high"], 3) if setup_bar else "",
            "rejection_bar_open_utc":        rej_open.isoformat(),
            "rejection_bar_open":            round(rej_bar["open"], 3)  if rej_bar else "",
            "rejection_bar_high":            round(rej_bar["high"], 3)  if rej_bar else "",
            "rejection_bar_low":             round(rej_bar["low"], 3)   if rej_bar else "",
            "rejection_bar_close":           round(rej_bar["close"], 3) if rej_bar else "",
            "baseline_entry_price":          base_entry,
            "baseline_entry_ts":             r["timestamp_open"],
            "baseline_rejection_match":      close_match,
            "baseline_realised_pips":        base_pips,
            "baseline_close_reason":         base_close_reason,
            "baseline_mfe_pips":             r["mfe_pips"],
            "baseline_mae_pips":             r["mae_pips"],
            "baseline_duration_min":         r["duration_minutes"],
            "baseline_scaled_out":           r["scaled_out"],
            "alt_break_bar_ts_utc":          break_bar["ts"].isoformat() if break_bar else "",
            "alt_break_bar_index":           break_k if break_k else "",
            "alt_entry_price":               round(alt_entry, 3) if alt_entry else "",
            "alt_missed":                    alt_entry is None,
            "alt_entry_delta_pips":          round(pips_from_points(base_entry - alt_entry), 2) if alt_entry else "",
            "alt_exit_ts_open":              alt_result["exit_ts_open"],
            "alt_exit_reason":               alt_result["exit_reason"],
            "alt_realised_pips":             round(alt_result["alt_pips"], 2) if alt_entry else 0.0,
            "alt_mfe_pips":                  alt_result["mfe_pips"],
            "alt_mae_pips":                  alt_result["mae_pips"],
            "alt_duration_bars":             alt_result["duration_bars"],
            "alt_scaled_out":                alt_result["scaled_out"],
            "alt_runner_exit_pips":          alt_result["runner_exit_pips"],
            "diff_pips_actual_vs_alt":       round(diff, 2) if diff is not None else "",
            "baseline_sim_exit_ts_open":     base_sim["exit_ts_open"],
            "baseline_sim_exit_reason":      base_sim["exit_reason"],
            "baseline_sim_pips":             round(base_sim["alt_pips"], 2),
            "baseline_sim_mfe_pips":         base_sim["mfe_pips"],
            "baseline_sim_mae_pips":         base_sim["mae_pips"],
            "baseline_sim_scaled_out":       base_sim["scaled_out"],
            "diff_pips_sim_baseline_vs_alt": (round(alt_result["alt_pips"] - base_sim["alt_pips"], 2)
                                              if alt_entry else round(-base_sim["alt_pips"], 2)),
            "baseline_realised_gbp_stake1":  round(base_pips * STAKE_PER_PIP_GBP, 2) if base_pips is not None else "",
            "alt_realised_gbp_stake1":       round(alt_result["alt_pips"] * STAKE_PER_PIP_GBP, 2) if alt_entry else 0.0,
        })

    # ---- write comparison CSV ----
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    # ---- summary ----
    base_pips_all = [r["baseline_realised_pips"] for r in out_rows
                     if r["baseline_realised_pips"] is not None]
    alt_pips_all  = [r["alt_realised_pips"] for r in out_rows]  # 0 if missed
    alt_fired     = [r for r in out_rows if not r["alt_missed"]]
    alt_missed    = [r for r in out_rows if r["alt_missed"]]

    def per_day(rows_key: str) -> Dict[str, float]:
        d: Dict[str, float] = {}
        for r in out_rows:
            date = r["trade_date"]
            val = r[rows_key] if isinstance(r[rows_key], (int, float)) else 0.0
            if rows_key == "baseline_realised_pips" and r[rows_key] is None:
                continue
            d[date] = d.get(date, 0.0) + val
        return d

    base_daily = per_day("baseline_realised_pips")
    base_sim_daily = per_day("baseline_sim_pips")
    alt_daily  = per_day("alt_realised_pips")

    def summarise(daily: Dict[str, float], label: str) -> Dict[str, Any]:
        vals = list(daily.values())
        n_days = len(vals)
        pos_days = sum(1 for v in vals if v > 0)
        neg_days = sum(1 for v in vals if v < 0)
        flat_days = n_days - pos_days - neg_days
        # max DD
        cum = 0.0
        peak = 0.0
        mdd = 0.0
        for _, v in sorted(daily.items()):
            cum += v
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)
        # best-3-days
        top3 = sum(sorted(vals, reverse=True)[:3])
        total = sum(vals)
        share = (top3 / total * 100) if total != 0 else 0.0
        return {
            "label": label,
            "n_active_days": n_days,
            "total_pips": round(total, 2),
            "median_day_pips": round(sorted(vals)[n_days // 2], 2) if vals else 0.0,
            "pos_days": pos_days,
            "neg_days": neg_days,
            "flat_days": flat_days,
            "pct_pos_days": round(pos_days / n_days * 100, 1) if n_days else 0.0,
            "max_drawdown_pips": round(mdd, 2),
            "top3_days_share_pct": round(share, 1),
            "best_day_pips": round(max(vals), 2) if vals else 0.0,
            "worst_day_pips": round(min(vals), 2) if vals else 0.0,
        }

    summary = {
        "period_utc": "2026-05-23 → 2026-06-24 (entry-date window, Era B)",
        "n_setups": len(out_rows),
        "baseline_actual_ledger": {
            **summarise(base_daily, "baseline_actual_ledger"),
            "n_fills": len([r for r in out_rows if r["baseline_realised_pips"] is not None]),
            "n_unreconciled": len([r for r in out_rows if r["baseline_realised_pips"] is None]),
            "reconciliation_check_vs_ledger": {
                "reconstructed_total_pips": round(sum(base_pips_all), 2),
                "ledger_total_pips": 395.40,
                "match": abs(sum(base_pips_all) - 395.40) < 0.01,
            },
        },
        "baseline_4exit_simulator": {
            **summarise(base_sim_daily, "baseline_actual_entry_thru_4exit_sim"),
            "n_fills": 36,
            "note": "SAME entry as actual (rejection close market SELL); same 4-exit sim as alt (SL / scale-out+BE / broker-TP / 240m). Enables like-for-like comparison isolating entry-timing, since the actual ledger includes TRAIL_STOP / QM / STRUCTURE / BB_FLIP soft exits that 5m OHLC cannot replicate.",
        },
        "alt_third_candle": {
            **summarise(alt_daily, "alt_third_candle_break"),
            "n_fills": len(alt_fired),
            "n_missed": len(alt_missed),
            "pct_missed": round(len(alt_missed) / len(out_rows) * 100, 1),
        },
        "delta_actual_ledger_vs_alt_sim": {
            "total_pips": round(sum(alt_pips_all) - sum([p for p in base_pips_all if p is not None]), 2),
            "caveat": "Cross-comparison — baseline includes soft exits alt sim cannot model.",
        },
        "delta_like_for_like_sim": {
            "total_pips": round(sum(alt_pips_all) - sum(base_sim_daily.values()), 2),
            "note": "Both use the 4-exit simulator. Delta ≈ entry-timing effect only.",
            "wins_kept": sum(1 for r in out_rows
                             if r["baseline_realised_pips"] is not None
                             and r["baseline_realised_pips"] > 0
                             and (not r["alt_missed"]) and r["alt_realised_pips"] > 0),
            "wins_lost_to_miss": sum(1 for r in out_rows
                                     if r["baseline_realised_pips"] is not None
                                     and r["baseline_realised_pips"] > 0
                                     and r["alt_missed"]),
            "losses_avoided_by_miss": sum(1 for r in out_rows
                                          if r["baseline_realised_pips"] is not None
                                          and r["baseline_realised_pips"] <= 0
                                          and r["alt_missed"]),
        },
        "exit_reason_distribution_alt": {},
    }
    for r in out_rows:
        rr = r["alt_exit_reason"] or "n/a"
        summary["exit_reason_distribution_alt"][rr] = (
            summary["exit_reason_distribution_alt"].get(rr, 0) + 1)

    with open(OUT_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")

if __name__ == "__main__":
    main()
