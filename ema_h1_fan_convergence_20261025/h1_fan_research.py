"""H1 fan-convergence research — read-only, no strategy mutation.

Builds the complete H1 time series from the AutoBot M5 archive for
2026-01-01 → 2026-10-23, classifies the EMA 8/13/20 fan at each
completed H1 bar, measures subsequent 1/2/3/4-hour price action, and
joins the strategy's replay setups to the fan class in force at each
setup's trigger H1.

Outputs (into reports/h1_fan_convergence_validation_20261025/):
  * H1_FAN_EVENTS.csv              one row per completed H1 bar
  * TREND_CONTINUATION_RESULTS.csv H1 bar + 1/2/3/4h outcome windows
  * M5_PULLBACK_BY_FAN_STATE.csv   replay setups annotated with fan class
  * TRADE_LEVEL_RESULTS.csv        per-trade outcomes bucketed by fan class
  * TREND_EPISODE_RESULTS.csv      per contiguous H1 trend episode

Terminology:
  - fan class is computed from the two ADJACENT separations evaluated
    in trend direction:
        BUY  trend_sep_8_13 = ema8 - ema13 (expected > 0, growing)
        SELL trend_sep_8_13 = ema13 - ema8 (expected > 0, growing)
    (and analogous for 13-20).
  - The one-hour delta is the (now - prev) change in each adjacent
    separation. An hour qualifies for classification only when
    the H1 direction classifier returns BUY or SELL (strict ordering +
    all three same-signed single-hour EMA deltas, i.e. the strategy's
    own trend.classify_h1).
  - EXPANDING : both adjacent separations widen more than TOL points.
  - CONVERGING: both narrow more than TOL points.
  - STABLE   : both are within [-TOL, +TOL].
  - MIXED    : one widens, the other narrows (or sign-mixed within TOL
               but with large magnitudes on each side).
  - Default TOL = 0.3 point (= 0.03 pip on GBPUSD-TODAY epic).
    Sensitivity is reported separately for TOL in {0.1, 0.3, 0.5, 1.0}.

Continuation outcome (pre-registered):
  continuation_pips_threshold = 10.0 pips (100 points).
  For each horizon N in {1, 2, 3, 4} hours:
    net = (close_{T+N} - close_T) * direction_sign
      (direction_sign = +1 BUY, -1 SELL)
    outcome:
      continuation  iff net >= continuation_pips_threshold
      reversal      iff net <= -continuation_pips_threshold
      consolidation otherwise

Scope: no change to strategy code; same `candle_reader`, `h1_builder`,
`indicators.ema`, `trend.classify_h1` used throughout. The replay
setups CSV at reports/20261025_corrected/ is treated as read-only
historical evidence.
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ema_pullback.candle_reader import M5Bar, CandleReaderError, read_day
from ema_pullback.h1_builder import build_completed_h1, H1Bar
from ema_pullback.indicators import ema
from ema_pullback.trend import classify_h1, BUY, SELL, NONE

ARCHIVE = Path("/opt/tradingbot/data/candles/GBPUSD")
OUT = Path("/home/autobot/ema_pullback/reports/h1_fan_convergence_validation_20261025")
SETUPS_CSV = Path(
    "/home/autobot/ema_pullback/reports/20261025_corrected/"
    "replay_setups_20261025T070353.csv"
)
START = "2026-01-01"
END = "2026-10-23"

# Pre-registered constants.
PIP = 10.0                                   # 10 points = 1 pip (GBPUSD-TODAY)
# Two outcome thresholds, pre-registered:
#   MODEST: 3 pips (30 points) — modest continuation / reversal.
#   STRONG: 10 pips (100 points) — strong continuation / reversal.
# A move in the alignment direction above MODEST is "modest continuation";
# a move against alignment above MODEST is "modest reversal"; otherwise
# the hour is "consolidation" under the MODEST threshold. STRONG applies
# the same categorisation at the stricter threshold.
MODEST_PIPS = 3.0
STRONG_PIPS = 10.0
DEFAULT_TOL_POINTS = 0.3                     # fan STABLE band half-width (points)
H1_MIN_COMPLETED = 200                       # match strategy guard

OUT.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Load M5 archive (tolerant of per-day integrity issues).
# ------------------------------------------------------------------

def load_m5_window(start: str, end: str) -> List[M5Bar]:
    start_day = datetime.fromisoformat(start).date()
    end_day = datetime.fromisoformat(end).date()
    day = start_day
    out: List[M5Bar] = []
    skipped: List[Tuple[str, str]] = []
    while day <= end_day:
        try:
            daily = read_day(ARCHIVE, day)
            last_ts = None
            ok = True
            for b in daily:
                if last_ts is not None and b.ts <= last_ts:
                    ok = False
                    break
                last_ts = b.ts
            if not ok:
                skipped.append((day.isoformat(), "non_monotonic_after_parse"))
                day = day + timedelta(days=1)
                continue
            out.extend(daily)
        except CandleReaderError as e:
            skipped.append((day.isoformat(), f"candle_reader_error: {e}"))
        except FileNotFoundError:
            pass
        day = day + timedelta(days=1)
    out.sort(key=lambda b: b.ts)
    print(f"loaded {len(out)} M5 bars; skipped {len(skipped)} days")
    for s in skipped:
        print(f"  skip {s[0]}: {s[1]}")
    return out


# ------------------------------------------------------------------
# Build the point-in-time H1 series with EMAs + fan metrics.
# ------------------------------------------------------------------

def build_h1_df(m5s: Sequence[M5Bar]) -> pd.DataFrame:
    """Return a DataFrame with one row per completed H1 bar, including
    EMAs computed on all closes up to and including that bar (causal)
    and both adjacent separations and their 1-hour deltas."""
    # Produce every COMPLETED H1 bar through END.
    now_utc = datetime.fromisoformat(END + "T23:59:59+00:00")
    h1_bars = build_completed_h1(list(m5s), now_utc)
    rows = []
    for b in h1_bars:
        rows.append({
            "h1_ts": b.ts,
            "h1_open": b.open,
            "h1_high": b.high,
            "h1_low": b.low,
            "h1_close": b.close,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("h1_ts").reset_index(drop=True)
    # EMAs on completed closes.
    df["ema8"] = ema(df["h1_close"].tolist(), 8).values
    df["ema13"] = ema(df["h1_close"].tolist(), 13).values
    df["ema20"] = ema(df["h1_close"].tolist(), 20).values
    # Slopes = 1-hour delta.
    df["ema8_slope_1h"] = df["ema8"].diff()
    df["ema13_slope_1h"] = df["ema13"].diff()
    df["ema20_slope_1h"] = df["ema20"].diff()
    # Signed adjacent separations in POINTS (ema differences at same
    # scale as the input mid price).
    df["sep_8_13"] = df["ema8"] - df["ema13"]
    df["sep_13_20"] = df["ema13"] - df["ema20"]
    df["sep_8_20"] = df["ema8"] - df["ema20"]
    df["abs_sep_8_13"] = df["sep_8_13"].abs()
    df["abs_sep_13_20"] = df["sep_13_20"].abs()
    df["abs_sep_8_20"] = df["sep_8_20"].abs()
    df["abs_sep_8_13_delta"] = df["abs_sep_8_13"].diff()
    df["abs_sep_13_20_delta"] = df["abs_sep_13_20"].diff()
    df["abs_sep_8_20_delta"] = df["abs_sep_8_20"].diff()
    # Direction via the strategy's own classifier run on a growing H1
    # list — same algorithm, same warm-up guard. Done row-by-row so a
    # replay-faithful direction is attached to each H1 bar.
    directions: List[str] = []
    for i in range(len(h1_bars)):
        subset = h1_bars[: i + 1]
        snap = classify_h1(subset, min_completed=H1_MIN_COMPLETED)
        directions.append(snap.direction if snap is not None else "INSUFF")
    df["direction"] = directions
    return df


# ------------------------------------------------------------------
# Fan classification.
# ------------------------------------------------------------------

def classify_fan(row: pd.Series, tol: float = DEFAULT_TOL_POINTS) -> str:
    """Pure classifier: EXPANDING / STABLE / CONVERGING / MIXED / NA.

    NA applies when direction is NONE / INSUFF, when the prior deltas
    are NaN (first bar), or when ordering/direction cannot be used.
    """
    dirn = row["direction"]
    if dirn not in (BUY, SELL):
        return "NA"
    d1 = row["abs_sep_8_13_delta"]
    d2 = row["abs_sep_13_20_delta"]
    if pd.isna(d1) or pd.isna(d2):
        return "NA"
    if d1 > tol and d2 > tol:
        return "EXPANDING"
    if d1 < -tol and d2 < -tol:
        return "CONVERGING"
    if abs(d1) <= tol and abs(d2) <= tol:
        return "STABLE"
    return "MIXED"


def attach_fan_class(df: pd.DataFrame, tol: float = DEFAULT_TOL_POINTS,
                    column: str = "fan_class") -> pd.DataFrame:
    df[column] = df.apply(lambda r: classify_fan(r, tol=tol), axis=1)
    return df


# ------------------------------------------------------------------
# Trend continuation outcome measurement.
# ------------------------------------------------------------------

def attach_continuation_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """For each H1 row attach mfe/mae/net over N future hours, signed
    to the alignment direction. net > CONTINUATION_PIPS_THRESHOLD →
    continuation, < -threshold → reversal, else consolidation.

    Horizon windows look at future H1 bars at index i+1..i+N
    inclusive, so N=1 means the SINGLE next completed hour's OHLC.
    """
    highs = df["h1_high"].values
    lows = df["h1_low"].values
    closes = df["h1_close"].values
    dirs = df["direction"].values
    n = len(df)
    for N in (1, 2, 3, 4):
        mfe_arr = [None] * n
        mae_arr = [None] * n
        net_arr = [None] * n
        out_arr = [None] * n
        for i in range(n - N):
            dirn = dirs[i]
            if dirn not in (BUY, SELL):
                continue
            close_t = closes[i]
            sign = 1 if dirn == BUY else -1
            # Future window [i+1, i+N] inclusive.
            fh = highs[i + 1 : i + N + 1]
            fl = lows[i + 1 : i + N + 1]
            fc = closes[i + N]
            if sign == 1:
                mfe = max(fh) - close_t          # max distance up
                mae = close_t - min(fl)          # max distance down
            else:
                mfe = close_t - min(fl)          # max distance down
                mae = max(fh) - close_t          # max distance up
            net = (fc - close_t) * sign
            mfe_arr[i] = mfe
            mae_arr[i] = mae
            net_arr[i] = net
            net_pips = net / PIP
            if net_pips >= STRONG_PIPS:
                out_arr[i] = "continuation"
            elif net_pips <= -STRONG_PIPS:
                out_arr[i] = "reversal"
            else:
                out_arr[i] = "consolidation"
        df[f"mfe_{N}h_points"] = mfe_arr
        df[f"mae_{N}h_points"] = mae_arr
        df[f"net_{N}h_points"] = net_arr
        df[f"outcome_{N}h"] = out_arr
        # Also compute MODEST (3-pip) outcome at the lower threshold.
        mod_arr: List[Optional[str]] = [None] * n
        for i in range(n - N):
            if net_arr[i] is None:
                continue
            npips = net_arr[i] / PIP
            if npips >= MODEST_PIPS:
                mod_arr[i] = "continuation"
            elif npips <= -MODEST_PIPS:
                mod_arr[i] = "reversal"
            else:
                mod_arr[i] = "consolidation"
        df[f"outcome_modest_{N}h"] = mod_arr
    return df


# ------------------------------------------------------------------
# Setups replay — read & join to fan state.
# ------------------------------------------------------------------

def load_replay_setups() -> pd.DataFrame:
    df = pd.read_csv(SETUPS_CSV)
    df["trigger_ts"] = pd.to_datetime(df["trigger_ts"])
    df["h1_ts"] = pd.to_datetime(df["h1_ts"])
    # Filter to study window.
    start_ts = pd.Timestamp(START + "T00:00:00+00:00")
    end_ts = pd.Timestamp(END + "T23:59:59+00:00")
    df = df[(df["trigger_ts"] >= start_ts) & (df["trigger_ts"] <= end_ts)].copy()
    return df


def join_setups_with_fan(setups: pd.DataFrame, h1: pd.DataFrame,
                         tol: float = DEFAULT_TOL_POINTS) -> pd.DataFrame:
    """Left-join setups on h1_ts to the H1 fan class."""
    local_h1 = h1[["h1_ts", "direction", "ema8", "ema13", "ema20",
                   "abs_sep_8_13", "abs_sep_13_20", "abs_sep_8_20",
                   "abs_sep_8_13_delta", "abs_sep_13_20_delta",
                   "ema8_slope_1h", "ema13_slope_1h", "ema20_slope_1h"]].copy()
    # Attach fan at the chosen tolerance.
    local_h1 = attach_fan_class(local_h1, tol=tol, column=f"fan_class_tol{tol:g}")
    merged = setups.merge(local_h1, left_on="h1_ts", right_on="h1_ts",
                          how="left",
                          suffixes=("", "_h1"))
    return merged


# ------------------------------------------------------------------
# Aggregations.
# ------------------------------------------------------------------

def aggregate_by_fan_state(trades: pd.DataFrame, fan_col: str, exit_mode: str) -> pd.DataFrame:
    """Compute summary stats bucketed by fan class.

    exit_mode in {"a", "b"}:
      a → Baseline A: a_outcome, a_mid_gross_pips
      b → Method B:   b_outcome, b_effective_pips_full_size
    """
    rows = []
    if exit_mode == "a":
        outcome_col = "a_outcome"
        pip_col = "a_mid_gross_pips"
        mae_col = None   # Baseline A has no MAE/MFE tracker column.
        mfe_col = None
        fill_outcomes = {"filled_mid_tp", "filled_mid_sl", "filled_mid_ambiguous"}
        win_outcomes = {"filled_mid_tp"}
    else:
        outcome_col = "b_outcome"
        pip_col = "b_effective_pips_full_size"
        mae_col = "b_mae_pips"
        mfe_col = "b_mfe_pips"
        fill_outcomes = {"trailing_exit", "break_even_exit", "software_sl_full",
                         "broker_sl_full", "broker_tp_full", "ambiguous_full"}
        win_outcomes = {"trailing_exit"}   # trailing exits realise > BE; BE itself is break-even

    for cls, sub in trades.groupby(fan_col, dropna=False):
        n_setups = len(sub)
        filled = sub[sub[outcome_col].isin(fill_outcomes)].copy()
        n_filled = len(filled)
        n_cancelled = (sub[outcome_col] == "cancelled").sum()
        wins = (filled[pip_col] > 0).sum() if n_filled > 0 else 0
        losses = (filled[pip_col] <= 0).sum() if n_filled > 0 else 0
        avg_pips = filled[pip_col].mean() if n_filled > 0 else None
        total_pips = filled[pip_col].sum() if n_filled > 0 else 0
        win_pips = filled.loc[filled[pip_col] > 0, pip_col].sum() if n_filled > 0 else 0
        loss_pips_abs = -filled.loc[filled[pip_col] <= 0, pip_col].sum() if n_filled > 0 else 0
        pf = (win_pips / loss_pips_abs) if loss_pips_abs > 0 else (float("inf") if win_pips > 0 else None)
        rows.append({
            "fan_class": cls if cls is not None else "NA",
            "n_setups": n_setups,
            "n_filled": n_filled,
            "n_cancelled": int(n_cancelled),
            "wins": int(wins),
            "losses": int(losses),
            "win_rate": (wins / n_filled) if n_filled > 0 else None,
            "avg_pips_per_fill": avg_pips,
            "total_pips": total_pips,
            "profit_factor": pf,
            "avg_mae_pips": filled[mae_col].mean() if (mae_col and n_filled > 0) else None,
            "avg_mfe_pips": filled[mfe_col].mean() if (mfe_col and n_filled > 0) else None,
        })
    return pd.DataFrame(rows).sort_values("fan_class")


# ------------------------------------------------------------------
# Episode construction & aggregation.
# ------------------------------------------------------------------

def build_episodes(h1: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with one row per contiguous same-direction H1
    episode (direction in {BUY, SELL}). NONE / INSUFF hours split
    episodes. Includes fan-class evolution counts for the default tol."""
    rows = []
    cur_dir: Optional[str] = None
    cur_start: Optional[pd.Timestamp] = None
    cur_count = 0
    fan_tallies: Dict[str, int] = {}
    def flush(end_ts: pd.Timestamp):
        nonlocal cur_dir, cur_start, cur_count, fan_tallies
        if cur_dir is not None:
            rows.append({
                "direction": cur_dir,
                "start_ts": cur_start,
                "end_ts": end_ts,
                "n_hours": cur_count,
                "n_expanding": fan_tallies.get("EXPANDING", 0),
                "n_stable": fan_tallies.get("STABLE", 0),
                "n_converging": fan_tallies.get("CONVERGING", 0),
                "n_mixed": fan_tallies.get("MIXED", 0),
                "n_na": fan_tallies.get("NA", 0),
            })
        cur_dir = None
        cur_start = None
        cur_count = 0
        fan_tallies = {}
    for _, r in h1.iterrows():
        d = r["direction"]
        cls = r["fan_class"]
        if d not in (BUY, SELL):
            flush(r["h1_ts"])
            continue
        if cur_dir is None or d != cur_dir:
            flush(r["h1_ts"])
            cur_dir = d
            cur_start = r["h1_ts"]
            cur_count = 1
            fan_tallies = {cls: 1}
        else:
            cur_count += 1
            fan_tallies[cls] = fan_tallies.get(cls, 0) + 1
    # Flush trailing episode with its last bar's ts.
    if cur_dir is not None:
        flush(h1["h1_ts"].iloc[-1])
    return pd.DataFrame(rows)


def episode_outcomes(episodes: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Attach per-episode trade aggregates (both Method A and B)."""
    out_rows = []
    for _, ep in episodes.iterrows():
        mask = (
            (trades["trigger_ts"] >= ep["start_ts"]) &
            (trades["trigger_ts"] <= ep["end_ts"]) &
            (trades["direction"] == ep["direction"])
        )
        tr = trades[mask]
        n_setups = len(tr)
        # Method B
        b_filled = tr[tr["b_outcome"].isin({
            "trailing_exit", "break_even_exit", "software_sl_full",
            "broker_sl_full", "broker_tp_full", "ambiguous_full"})]
        b_wins = (b_filled["b_effective_pips_full_size"] > 0).sum() if len(b_filled) else 0
        b_losses = (b_filled["b_effective_pips_full_size"] <= 0).sum() if len(b_filled) else 0
        b_total = b_filled["b_effective_pips_full_size"].sum() if len(b_filled) else 0
        # Method A
        a_filled = tr[tr["a_outcome"].isin({"filled_mid_tp", "filled_mid_sl", "filled_mid_ambiguous"})]
        a_total = a_filled["a_mid_gross_pips"].sum() if len(a_filled) else 0
        # Dominant fan class.
        dominant = "NA"
        counts = [("EXPANDING", ep["n_expanding"]),
                  ("STABLE", ep["n_stable"]),
                  ("CONVERGING", ep["n_converging"]),
                  ("MIXED", ep["n_mixed"]),
                  ("NA", ep["n_na"])]
        counts.sort(key=lambda t: -t[1])
        if counts[0][1] > 0:
            dominant = counts[0][0]
        pct_conv = (ep["n_converging"] / ep["n_hours"]) if ep["n_hours"] > 0 else None
        out_rows.append({
            "episode_start": ep["start_ts"].isoformat(),
            "episode_end": ep["end_ts"].isoformat(),
            "direction": ep["direction"],
            "n_hours": ep["n_hours"],
            "n_expanding": ep["n_expanding"],
            "n_stable": ep["n_stable"],
            "n_converging": ep["n_converging"],
            "n_mixed": ep["n_mixed"],
            "pct_converging": pct_conv,
            "dominant_fan_class": dominant,
            "n_setups": n_setups,
            "n_b_filled": len(b_filled),
            "b_wins": int(b_wins),
            "b_losses": int(b_losses),
            "b_total_pips": float(b_total),
            "n_a_filled": len(a_filled),
            "a_total_pips": float(a_total),
        })
    return pd.DataFrame(out_rows)


# ------------------------------------------------------------------
# Dev / OOS split and sensitivity.
# ------------------------------------------------------------------

DEV_END = "2026-07-31"
OOS_START = "2026-08-01"


def split_dev_oos(trades: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    dev_end = pd.Timestamp(DEV_END + "T23:59:59+00:00")
    oos_start = pd.Timestamp(OOS_START + "T00:00:00+00:00")
    dev = trades[trades["trigger_ts"] <= dev_end].copy()
    oos = trades[trades["trigger_ts"] >= oos_start].copy()
    return dev, oos


def main() -> int:
    print(f"loading M5 archive {START} → {END}")
    m5s = load_m5_window(START, END)
    print(f"building H1 series")
    h1 = build_h1_df(m5s)
    print(f"attaching fan class (TOL={DEFAULT_TOL_POINTS} pts)")
    h1 = attach_fan_class(h1, tol=DEFAULT_TOL_POINTS, column="fan_class")
    print("attaching continuation outcomes (1/2/3/4h)")
    h1 = attach_continuation_outcomes(h1)

    # Save H1 events.
    cols = [
        "h1_ts", "h1_open", "h1_high", "h1_low", "h1_close",
        "ema8", "ema13", "ema20",
        "ema8_slope_1h", "ema13_slope_1h", "ema20_slope_1h",
        "sep_8_13", "sep_13_20", "sep_8_20",
        "abs_sep_8_13", "abs_sep_13_20", "abs_sep_8_20",
        "abs_sep_8_13_delta", "abs_sep_13_20_delta", "abs_sep_8_20_delta",
        "direction", "fan_class",
    ]
    h1[cols].to_csv(OUT / "H1_FAN_EVENTS.csv", index=False)

    # Continuation.
    cont_cols = cols + [
        "mfe_1h_points", "mae_1h_points", "net_1h_points", "outcome_1h",
        "mfe_2h_points", "mae_2h_points", "net_2h_points", "outcome_2h",
        "mfe_3h_points", "mae_3h_points", "net_3h_points", "outcome_3h",
        "mfe_4h_points", "mae_4h_points", "net_4h_points", "outcome_4h",
    ]
    h1[cont_cols].to_csv(OUT / "TREND_CONTINUATION_RESULTS.csv", index=False)

    # Setups.
    setups = load_replay_setups()
    print(f"loaded {len(setups)} replay setups in window")
    merged = join_setups_with_fan(setups, h1, tol=DEFAULT_TOL_POINTS)
    merged["fan_class"] = merged[f"fan_class_tol{DEFAULT_TOL_POINTS:g}"]
    # Preserve the pullback outcome columns and the fan class attached.
    cols2 = list(setups.columns) + [
        "ema8", "ema13", "ema20",
        "abs_sep_8_13", "abs_sep_13_20", "abs_sep_8_20",
        "abs_sep_8_13_delta", "abs_sep_13_20_delta",
        "ema8_slope_1h", "ema13_slope_1h", "ema20_slope_1h",
        "fan_class",
    ]
    merged[cols2].to_csv(OUT / "M5_PULLBACK_BY_FAN_STATE.csv", index=False)

    # Trade-level aggregates — full window, dev, OOS, Method A and B.
    all_rows = []
    for exit_mode in ("a", "b"):
        for scope_name, scope_df in (("ALL", merged), ("DEV", split_dev_oos(merged)[0]),
                                     ("OOS", split_dev_oos(merged)[1])):
            agg = aggregate_by_fan_state(scope_df, "fan_class", exit_mode)
            agg["scope"] = scope_name
            agg["exit_mode"] = "method_b" if exit_mode == "b" else "baseline_a"
            all_rows.append(agg)
    trade_level = pd.concat(all_rows, ignore_index=True)
    trade_level = trade_level[["scope", "exit_mode", "fan_class", "n_setups", "n_filled",
                              "n_cancelled", "wins", "losses", "win_rate",
                              "avg_pips_per_fill", "total_pips", "profit_factor",
                              "avg_mae_pips", "avg_mfe_pips"]]
    trade_level.to_csv(OUT / "TRADE_LEVEL_RESULTS.csv", index=False)

    # Episode results.
    episodes = build_episodes(h1)
    ep_out = episode_outcomes(episodes, merged)
    ep_out.to_csv(OUT / "TREND_EPISODE_RESULTS.csv", index=False)

    # Continuation outcome contingency.
    cont_rows = []
    for N in (1, 2, 3, 4):
        for cls, sub in h1.groupby("fan_class", dropna=False):
            if cls in (None, "NA"):
                continue
            # Only alignment-active hours.
            sub = sub[sub[f"outcome_{N}h"].notna()]
            n = len(sub)
            if n == 0:
                continue
            # STRONG (10-pip) outcomes.
            cont_s = (sub[f"outcome_{N}h"] == "continuation").sum()
            cons_s = (sub[f"outcome_{N}h"] == "consolidation").sum()
            rev_s = (sub[f"outcome_{N}h"] == "reversal").sum()
            # MODEST (3-pip) outcomes.
            cont_m = (sub[f"outcome_modest_{N}h"] == "continuation").sum()
            cons_m = (sub[f"outcome_modest_{N}h"] == "consolidation").sum()
            rev_m = (sub[f"outcome_modest_{N}h"] == "reversal").sum()
            net_series = sub[f"net_{N}h_points"].astype(float) / PIP
            cont_rows.append({
                "horizon_h": N,
                "fan_class": cls,
                "n_h1": n,
                # Strong 10-pip outcomes:
                "strong_cont_pct": cont_s / n,
                "strong_cons_pct": cons_s / n,
                "strong_rev_pct": rev_s / n,
                # Modest 3-pip outcomes:
                "modest_cont_pct": cont_m / n,
                "modest_cons_pct": cons_m / n,
                "modest_rev_pct": rev_m / n,
                # Net move distribution (pips).
                "net_pips_mean": net_series.mean(),
                "net_pips_median": net_series.median(),
                "net_pips_p25": net_series.quantile(0.25),
                "net_pips_p75": net_series.quantile(0.75),
                "net_pips_std": net_series.std(),
                "pct_net_positive": (net_series > 0).mean(),
                "pct_net_negative": (net_series < 0).mean(),
                "avg_mfe_pips": sub[f"mfe_{N}h_points"].astype(float).mean() / PIP,
                "avg_mae_pips": sub[f"mae_{N}h_points"].astype(float).mean() / PIP,
            })
    cont_summary = pd.DataFrame(cont_rows)
    cont_summary.to_csv(OUT / "TREND_CONTINUATION_SUMMARY.csv", index=False)

    print("outputs written to", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
