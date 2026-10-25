"""H1 trend-compliance audit for 2026-10-23 (read-only, no strategy mutation).

Builds the H1 timeline that the strategy itself would see, classifies every
hour with the strategy's own classify_h1, and binds each of the 23 setups
listed in the corrected replay CSV to the exact H1 snapshot that was in
force at the setup's trigger_ts.

Nothing in this script changes trend.py or any strategy module. It is a
read-only observer.
"""
from __future__ import annotations

import csv
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ema_pullback.candle_reader import CandleReaderError, read_day
from ema_pullback.h1_builder import build_completed_h1
from ema_pullback.indicators import ema
from ema_pullback.trend import classify_h1, BUY, SELL, NONE

ARCHIVE = Path("/opt/tradingbot/data/candles/GBPUSD")
OUT = Path("/home/autobot/ema_pullback/reports/h1_trend_compliance_20261025")
SETUPS_CSV = Path(
    "/home/autobot/ema_pullback/reports/20261025_corrected/"
    "replay_setups_20261025T070353.csv"
)
TARGET_DAY = "2026-10-23"


def load_bars_prefix_through(end_date: str):
    """Load every M5 bar in the archive up to and including end_date."""
    # Build the full set of day CSVs available, then clip to <= end_date.
    files = sorted(ARCHIVE.glob("*.csv"))
    days = []
    for p in files:
        d = p.stem
        if d <= end_date:
            days.append(d)
    # Day-by-day read with fault tolerance (matches replay semantics).
    bars = []
    for d in days:
        day = datetime.fromisoformat(d).date()
        try:
            daily = read_day(ARCHIVE, day)
        except CandleReaderError:
            continue
        # Enforce per-day monotonicity.
        last_ts = None
        ok = True
        for b in daily:
            if last_ts is not None and b.ts <= last_ts:
                ok = False
                break
            last_ts = b.ts
        if not ok:
            continue
        bars.extend(daily)
    return bars


def build_h1_timeline(bars):
    """Build the completed H1 series and classify each hour point-in-time."""
    now_cutoff = bars[-1].ts + timedelta(hours=1)
    h1_all = build_completed_h1(bars, now_cutoff)
    rows = []
    for k in range(len(h1_all)):
        snap = classify_h1(h1_all[: k + 1], min_completed=200)
        if snap is None:
            continue
        rows.append({
            "h1_ts": h1_all[k].ts.isoformat(),
            "open": h1_all[k].open,
            "high": h1_all[k].high,
            "low": h1_all[k].low,
            "close": h1_all[k].close,
            "ema8": snap.ema_fast_now,
            "ema13": snap.ema_mid_now,
            "ema20": snap.ema_slow_now,
            "ema8_prev": snap.ema_fast_prev,
            "ema13_prev": snap.ema_mid_prev,
            "ema20_prev": snap.ema_slow_prev,
            "ema8_slope_1h": snap.ema_fast_now - snap.ema_fast_prev,
            "ema13_slope_1h": snap.ema_mid_now - snap.ema_mid_prev,
            "ema20_slope_1h": snap.ema_slow_now - snap.ema_slow_prev,
            "sep_8_13": snap.ema_fast_now - snap.ema_mid_now,
            "sep_13_20": snap.ema_mid_now - snap.ema_slow_now,
            "sep_8_20": snap.ema_fast_now - snap.ema_slow_now,
            "ordering_ok": snap.ordering_ok,
            "slope_ok": snap.slope_ok,
            "direction": snap.direction,
        })
    return h1_all, rows


def classify_visual(row):
    """Research-only descriptive label — NOT a trading filter.

    A — CLEAR     : |sep_8_20| >= 5p AND same-sign 2-hour slope AND widening.
    B — WEAK      : technically aligned but slopes OR separation small.
    C — FLATTENING: ordered but |sep_8_20| converging over last 2h OR slope near 0.
    D — SIDEWAYS  : ordering_ok=False (direction=NONE)
    E — INSUFFICIENT: no classification possible.

    These thresholds exist solely to make the audit reproducible. The brief
    forbids them being wired into the strategy. We print them explicitly so
    the reader can override by eye.
    """
    if row["direction"] == NONE:
        if not row["ordering_ok"]:
            return "D"
        # Ordered but failed slope — treat as flattening
        return "C"
    sep820 = abs(row["sep_8_20"])
    # Signed slope magnitudes: for BUY must be +, for SELL must be -
    s8 = row["ema8_slope_1h"]
    s13 = row["ema13_slope_1h"]
    s20 = row["ema20_slope_1h"]
    if row["direction"] == BUY:
        slopes_strong = (s8 >= 1.0) and (s13 >= 0.5) and (s20 >= 0.3)
        slopes_marginal = (s8 >= 0.0) and (s13 >= 0.0) and (s20 >= 0.0)
    else:  # SELL
        slopes_strong = (s8 <= -1.0) and (s13 <= -0.5) and (s20 <= -0.3)
        slopes_marginal = (s8 <= 0.0) and (s13 <= 0.0) and (s20 <= 0.0)
    if sep820 >= 5.0 and slopes_strong:
        return "A"
    if sep820 >= 2.0 and slopes_marginal:
        return "B"
    return "C"


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("Loading archive through", TARGET_DAY, "…")
    bars = load_bars_prefix_through(TARGET_DAY)
    print(f"  loaded {len(bars):,} M5 bars")

    print("Building completed H1 timeline…")
    h1_all, h1_rows = build_h1_timeline(bars)
    print(f"  {len(h1_rows):,} classifiable hours")

    # Emit the full-week H1 timeline (10-17 .. 10-23) so chart windows have
    # enough history, plus the single trading day for close reading.
    week_start = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    day_start = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)
    day_end = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
    week_rows = [r for r in h1_rows if week_start.isoformat() <= r["h1_ts"] < day_end.isoformat()]
    day_rows = [r for r in h1_rows if day_start.isoformat() <= r["h1_ts"] < day_end.isoformat()]

    # Add visual class
    for r in h1_rows:
        r["visual_class"] = classify_visual(r)

    # H1_TREND_TIMELINE.csv — the trading day only
    out_fields = [
        "h1_ts", "open", "high", "low", "close",
        "ema8", "ema13", "ema20",
        "ema8_slope_1h", "ema13_slope_1h", "ema20_slope_1h",
        "sep_8_13", "sep_13_20", "sep_8_20",
        "ordering_ok", "slope_ok", "direction", "visual_class",
    ]
    with (OUT / "H1_TREND_TIMELINE.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields)
        w.writeheader()
        for r in day_rows:
            w.writerow({k: r.get(k) for k in out_fields})
    print(f"  wrote H1_TREND_TIMELINE.csv ({len(day_rows)} hours)")

    # H1_TREND_TIMELINE_WEEK.csv — 10-19 through 10-23 (context for charts)
    with (OUT / "H1_TREND_TIMELINE_WEEK.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields)
        w.writeheader()
        for r in week_rows:
            w.writerow({k: r.get(k) for k in out_fields})
    print(f"  wrote H1_TREND_TIMELINE_WEEK.csv ({len(week_rows)} hours)")

    # ------------------------------------------------------------------
    # Setup-level compliance table
    # ------------------------------------------------------------------
    # For each setup, replicate the replay's "latest completed H1 at bar close".
    h1_index = {r["h1_ts"]: i for i, r in enumerate(h1_rows)}
    def _latest_h1_at(bar_close_ts: datetime):
        # Latest completed H1 whose end <= bar_close_ts.
        want_ts = (bar_close_ts - timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0)
        # Walk back if that exact hour not present
        import bisect
        keys = sorted(h1_index.keys())
        idx = bisect.bisect_right(keys, want_ts.isoformat()) - 1
        if idx < 0:
            return None
        return h1_rows[idx]

    setups_out = []
    with SETUPS_CSV.open() as fh:
        for r in csv.DictReader(fh):
            if r["trigger_ts"][:10] != TARGET_DAY:
                continue
            trigger_ts = datetime.fromisoformat(r["trigger_ts"])
            bar_close = trigger_ts + timedelta(minutes=5)
            h1 = _latest_h1_at(bar_close)
            if h1 is None:
                print(f"  WARN no H1 for {r['trigger_ts']}")
                continue
            # Widening check: compare sep_8_20 to the prior H1's sep_8_20
            prior_h1_ts = (datetime.fromisoformat(h1["h1_ts"]) - timedelta(hours=1)).isoformat()
            prior = h1_rows[h1_index.get(prior_h1_ts, -1)] if prior_h1_ts in h1_index else None
            widening = (abs(h1["sep_8_20"]) - abs(prior["sep_8_20"])) if prior else None
            setups_out.append({
                "trigger_ts": r["trigger_ts"],
                "direction": r["direction"],
                "h1_ts": h1["h1_ts"],
                "h1_direction": h1["direction"],
                "h1_ema8": h1["ema8"],
                "h1_ema13": h1["ema13"],
                "h1_ema20": h1["ema20"],
                "h1_ema8_slope_1h": h1["ema8_slope_1h"],
                "h1_ema13_slope_1h": h1["ema13_slope_1h"],
                "h1_ema20_slope_1h": h1["ema20_slope_1h"],
                "h1_sep_8_13": h1["sep_8_13"],
                "h1_sep_13_20": h1["sep_13_20"],
                "h1_sep_8_20": h1["sep_8_20"],
                "h1_sep_widening_vs_prior": widening,
                "h1_visual_class": h1["visual_class"],
                "a_outcome": r["a_outcome"],
                "a_outcome_reason": r["a_outcome_reason"],
                "a_gross_pips": r.get("a_mid_gross_pips") or "",
                "b_outcome": r["b_outcome"],
                "b_eff_pips": r.get("b_effective_pips_full_size") or "",
                "b_mfe_pips": r.get("b_mfe_pips") or "",
                "b_mae_pips": r.get("b_mae_pips") or "",
            })

    with (OUT / "M5_SETUP_H1_COMPLIANCE.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(setups_out[0].keys()))
        w.writeheader()
        for s in setups_out:
            w.writerow(s)
    print(f"  wrote M5_SETUP_H1_COMPLIANCE.csv ({len(setups_out)} setups)")

    # ------------------------------------------------------------------
    # Episode accounting
    # ------------------------------------------------------------------
    # Distinct contiguous H1 episodes within the trading day plus the first
    # non-NONE hour that spans into the day.
    episodes = []
    cur = None
    for r in week_rows:
        d = r["direction"]
        if cur is None or cur["direction"] != d:
            if cur is not None:
                episodes.append(cur)
            cur = {"direction": d, "start": r["h1_ts"], "end": r["h1_ts"], "hours": 1}
        else:
            cur["end"] = r["h1_ts"]
            cur["hours"] += 1
    if cur is not None:
        episodes.append(cur)

    with (OUT / "H1_EPISODES_WEEK.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["direction", "start", "end", "hours"])
        w.writeheader()
        for e in episodes:
            w.writerow(e)
    print(f"  wrote H1_EPISODES_WEEK.csv ({len(episodes)} episodes)")

    # Dump a Python summary too, useful for the write-up
    print()
    print("=== DAY H1 CLASSIFICATION (2026-10-23) ===")
    for r in day_rows:
        print(f"  {r['h1_ts']}  {r['direction']:4s}  "
              f"ema8={r['ema8']:.4f}  ema13={r['ema13']:.4f}  ema20={r['ema20']:.4f}  "
              f"slope(8|13|20)={r['ema8_slope_1h']:+.3f}|{r['ema13_slope_1h']:+.3f}|{r['ema20_slope_1h']:+.3f}  "
              f"sep_8_20={r['sep_8_20']:+.3f}  class={r['visual_class']}")

    print()
    print("=== DAY EPISODES ===")
    for e in episodes:
        if e["start"] >= day_start.isoformat() or (e["start"] < day_start.isoformat() and e["end"] >= day_start.isoformat()):
            print(f"  {e['direction']:4s}  {e['start']}  →  {e['end']}  ({e['hours']}h)")

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    import matplotlib.dates as mdates

    charts_dir = OUT / "H1_TREND_CHARTS"
    charts_dir.mkdir(exist_ok=True)

    # Chart 1 — full week with EMAs + trading-day band
    df = pd.DataFrame(week_rows)
    df["ts"] = pd.to_datetime(df["h1_ts"])
    fig, ax = plt.subplots(figsize=(16, 7))
    # Draw candlesticks (simple vlines + up/down bars)
    width = pd.Timedelta(minutes=40)
    for _, r in df.iterrows():
        up = r["close"] >= r["open"]
        color = "#2ca02c" if up else "#d62728"
        ax.plot([r["ts"], r["ts"]], [r["low"], r["high"]], color=color, linewidth=0.9)
        ax.add_patch(plt.Rectangle(
            (mdates.date2num(r["ts"]) - 0.015, min(r["open"], r["close"])),
            0.03,
            abs(r["close"] - r["open"]) or 0.01,
            facecolor=color, edgecolor=color, linewidth=0,
        ))
    ax.plot(df["ts"], df["ema8"], label="EMA 8", color="#1f77b4", linewidth=1.6)
    ax.plot(df["ts"], df["ema13"], label="EMA 13", color="#ff7f0e", linewidth=1.6)
    ax.plot(df["ts"], df["ema20"], label="EMA 20", color="#9467bd", linewidth=1.6)
    # Setup markers
    for s in setups_out:
        trig = datetime.fromisoformat(s["trigger_ts"])
        y = s["h1_ema8"]
        marker = "v" if s["direction"] == "SELL" else "^"
        ax.scatter([trig], [y], marker=marker, s=70,
                   color="#111111" if "cancelled" in s["b_outcome"] else "#d62728",
                   zorder=5)
    # Trading day band
    ax.axvspan(day_start, day_end, color="#ffff00", alpha=0.07, zorder=0, label="2026-10-23 UTC")
    ax.set_title("GBPUSD H1 — 2026-10-19 to 2026-10-23 (EMA 8/13/20 + 23 setups)")
    ax.set_ylabel("Price (points, pip_size=1.0 archive scale)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(charts_dir / "01_week_overview.png", dpi=120)
    plt.close(fig)
    print(f"  wrote H1_TREND_CHARTS/01_week_overview.png")

    # Chart 2 — trading day only
    df_day = df[(df["ts"] >= pd.Timestamp(day_start)) & (df["ts"] < pd.Timestamp(day_end))]
    fig, ax = plt.subplots(figsize=(16, 7))
    for _, r in df_day.iterrows():
        up = r["close"] >= r["open"]
        color = "#2ca02c" if up else "#d62728"
        ax.plot([r["ts"], r["ts"]], [r["low"], r["high"]], color=color, linewidth=1.2)
        ax.add_patch(plt.Rectangle(
            (mdates.date2num(r["ts"]) - 0.015, min(r["open"], r["close"])),
            0.03,
            abs(r["close"] - r["open"]) or 0.01,
            facecolor=color, edgecolor=color, linewidth=0,
        ))
    ax.plot(df_day["ts"], df_day["ema8"], label="EMA 8", color="#1f77b4", linewidth=1.8)
    ax.plot(df_day["ts"], df_day["ema13"], label="EMA 13", color="#ff7f0e", linewidth=1.8)
    ax.plot(df_day["ts"], df_day["ema20"], label="EMA 20", color="#9467bd", linewidth=1.8)
    # Shade direction bands
    for _, r in df_day.iterrows():
        c = {"BUY": "#2ca02c", "SELL": "#d62728", "NONE": "#aaaaaa"}[r["direction"]]
        ax.axvspan(r["ts"], r["ts"] + pd.Timedelta(hours=1), color=c, alpha=0.04, zorder=0)
    # Setup markers with labels
    for s in setups_out:
        trig = datetime.fromisoformat(s["trigger_ts"])
        y = s["h1_ema8"]
        marker = "v" if s["direction"] == "SELL" else "^"
        filled = s["b_outcome"] not in ("cancelled", "undetermined")
        color = "#000000" if not filled else ("#2ca02c" if (s.get("b_eff_pips") or "0") and float(s["b_eff_pips"] or 0) > 0 else "#d62728")
        ax.scatter([trig], [y], marker=marker, s=90, color=color, edgecolors="white", linewidth=0.6, zorder=5)
    ax.set_title("GBPUSD H1 — 2026-10-23 trading day (markers: setup triggers)")
    ax.set_ylabel("Price (points)")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(charts_dir / "02_trading_day.png", dpi=120)
    plt.close(fig)
    print(f"  wrote H1_TREND_CHARTS/02_trading_day.png")

    # Chart 3 — EMA separation and slope diagnostic
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 9), sharex=True)
    ax1.plot(df_day["ts"], df_day["sep_8_20"], label="EMA8 - EMA20", color="#9467bd", linewidth=1.5)
    ax1.plot(df_day["ts"], df_day["sep_8_13"], label="EMA8 - EMA13", color="#1f77b4", linewidth=1.2)
    ax1.plot(df_day["ts"], df_day["sep_13_20"], label="EMA13 - EMA20", color="#ff7f0e", linewidth=1.2)
    ax1.axhline(0, color="#000", linewidth=0.5)
    ax1.set_ylabel("Separation (points)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper right", fontsize=9)
    ax1.set_title("H1 EMA separation (negative = SELL ordering, positive = BUY ordering)")
    ax2.plot(df_day["ts"], df_day["ema8_slope_1h"], label="EMA8 slope (1h)", color="#1f77b4", linewidth=1.2)
    ax2.plot(df_day["ts"], df_day["ema13_slope_1h"], label="EMA13 slope (1h)", color="#ff7f0e", linewidth=1.2)
    ax2.plot(df_day["ts"], df_day["ema20_slope_1h"], label="EMA20 slope (1h)", color="#9467bd", linewidth=1.2)
    ax2.axhline(0, color="#000", linewidth=0.5)
    ax2.set_ylabel("1-hour EMA slope (points/hour)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper right", fontsize=9)
    ax2.set_title("H1 EMA 1-hour slopes (sign = direction, magnitude = strength)")
    for _, r in df_day.iterrows():
        c = {"BUY": "#2ca02c", "SELL": "#d62728", "NONE": "#aaaaaa"}[r["direction"]]
        ax1.axvspan(r["ts"], r["ts"] + pd.Timedelta(hours=1), color=c, alpha=0.05, zorder=0)
        ax2.axvspan(r["ts"], r["ts"] + pd.Timedelta(hours=1), color=c, alpha=0.05, zorder=0)
    ax2.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(charts_dir / "03_separation_and_slopes.png", dpi=120)
    plt.close(fig)
    print(f"  wrote H1_TREND_CHARTS/03_separation_and_slopes.png")

    # Chart 4 — M5 overlay for the first fill (06:55 SELL) — three-hour window
    # Load the full-day M5 and build a per-5m EMA series.
    m5_day = [b for b in bars if b.ts.date() == datetime(2026,10,23).date()]
    closes = [b.close for b in m5_day]
    e8 = ema(closes, 8).to_list()
    e13 = ema(closes, 13).to_list()
    e21 = ema(closes, 21).to_list()
    df_m5 = pd.DataFrame({
        "ts": [b.ts for b in m5_day],
        "open":  [b.open for b in m5_day],
        "high":  [b.high for b in m5_day],
        "low":   [b.low  for b in m5_day],
        "close": [b.close for b in m5_day],
        "ema8":  e8, "ema13": e13, "ema21": e21,
    })

    # Chart 4 — M5 context around 06:55 and 20:05 (winner + loser)
    for anchor, label in [(datetime(2026,10,23,7,0, tzinfo=timezone.utc), "0700_winner_setup"),
                          (datetime(2026,10,23,20,10,tzinfo=timezone.utc), "2010_loser_setup")]:
        window_start = anchor - timedelta(hours=2)
        window_end = anchor + timedelta(hours=2)
        sub = df_m5[(df_m5["ts"] >= pd.Timestamp(window_start)) & (df_m5["ts"] <= pd.Timestamp(window_end))]
        fig, ax = plt.subplots(figsize=(16, 7))
        for _, r in sub.iterrows():
            up = r["close"] >= r["open"]
            color = "#2ca02c" if up else "#d62728"
            ax.plot([r["ts"], r["ts"]], [r["low"], r["high"]], color=color, linewidth=0.9)
            ax.add_patch(plt.Rectangle(
                (mdates.date2num(r["ts"]) - 0.0012, min(r["open"], r["close"])),
                0.0024,
                abs(r["close"] - r["open"]) or 0.01,
                facecolor=color, edgecolor=color, linewidth=0,
            ))
        ax.plot(sub["ts"], sub["ema8"],  label="M5 EMA 8",  color="#1f77b4", linewidth=1.4)
        ax.plot(sub["ts"], sub["ema13"], label="M5 EMA 13", color="#ff7f0e", linewidth=1.4)
        ax.plot(sub["ts"], sub["ema21"], label="M5 EMA 21", color="#9467bd", linewidth=1.4)
        # Mark setups in this window
        for s in setups_out:
            trig = datetime.fromisoformat(s["trigger_ts"])
            if window_start <= trig <= window_end:
                marker = "v" if s["direction"] == "SELL" else "^"
                color = "#000000"
                ax.scatter([trig], [sub[sub["ts"] == pd.Timestamp(trig)]["ema8"].values[0] if any(sub["ts"] == pd.Timestamp(trig)) else sub["ema8"].mean()],
                           marker=marker, s=90, color=color, edgecolors="white", linewidth=0.6, zorder=5)
        ax.set_title(f"M5 context around {anchor.strftime('%H:%M')} UTC on 2026-10-23")
        ax.set_ylabel("Price (points)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=9)
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(charts_dir / f"04_m5_{label}.png", dpi=120)
        plt.close(fig)
        print(f"  wrote H1_TREND_CHARTS/04_m5_{label}.png")

    print("\nDone.")

if __name__ == "__main__":
    main()
