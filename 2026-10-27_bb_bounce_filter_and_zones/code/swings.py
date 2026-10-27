"""
Zig-zag swing detection with explicit confirmation time (no look-ahead).

A swing is the move between two extrema (one high, one low). The *extremum*
itself is only known in hindsight — the swing is CONFIRMED when price has
retraced from the running extremum by at least `threshold_pips`. From that
confirmation moment onward, any trader could draw the swing and compute Fib
retracements. All downstream analysis uses `conf_time` as the earliest point
at which a level is "live".

Algorithm (per-bar, OHLC):
  Bootstrap (direction unknown): track running highest-high and lowest-low
  since start. Direction is established the first time price retraces
  threshold_pips from one of those extrema. The emitted swing runs from the
  earlier-timestamped extremum to the later-timestamped extremum.

  Post-bootstrap state=UP (previously-confirmed low → looking for swing high):
    - running_high advances on new highs.
    - If (running_high - current_bar.low) >= threshold_pips → confirm swing
      (low → running_high) UP, flip to state=DOWN, seed running_low=bar.low.

  Mirror for state=DOWN.
"""

from __future__ import annotations

import pandas as pd


def detect_swings(bars: pd.DataFrame, threshold_pips: float) -> pd.DataFrame:
    assert threshold_pips > 0
    assert len(bars) >= 2
    bars = bars.reset_index(drop=True)

    rows = []
    swing_id = 0

    first = bars.iloc[0]
    high = float(first["high"]); high_t = first["timestamp"]
    low = float(first["low"]); low_t = first["timestamp"]
    state: str | None = None

    def emit_up(bt, bl):
        nonlocal swing_id, state, low, low_t
        swing_id += 1
        rows.append({
            "swing_id": swing_id,
            "direction": "UP",
            "start_time": low_t, "start_price": low,
            "end_time": high_t, "end_price": high,
            "pips": high - low,
            "conf_time": bt, "conf_price": bl,
        })
        state = "DOWN"
        low = bl; low_t = bt

    def emit_down(bt, bh):
        nonlocal swing_id, state, high, high_t
        swing_id += 1
        rows.append({
            "swing_id": swing_id,
            "direction": "DOWN",
            "start_time": high_t, "start_price": high,
            "end_time": low_t, "end_price": low,
            "pips": high - low,
            "conf_time": bt, "conf_price": bh,
        })
        state = "UP"
        high = bh; high_t = bt

    for i in range(1, len(bars)):
        row = bars.iloc[i]
        bh = float(row["high"]); bl = float(row["low"]); bt = row["timestamp"]

        if state is None:
            # Advance running extrema
            if bh > high:
                high = bh; high_t = bt
            if bl < low:
                low = bl; low_t = bt
            # Did price retrace threshold_pips from either extremum?
            fell_from_high = (high - bl) >= threshold_pips
            rose_from_low = (bh - low) >= threshold_pips
            if fell_from_high and rose_from_low:
                # Both on the same bar: emit based on chronological order of
                # the extrema (the earlier one is the start of the swing).
                if low_t <= high_t:
                    emit_up(bt, bl)
                else:
                    emit_down(bt, bh)
            elif fell_from_high:
                # Price has fallen threshold from high; swing is low→high UP.
                # But direction only makes sense if the low came before the high.
                # If the current bar's low is a new low AFTER the high, the
                # swing is actually DOWN (high → bar.low). Pick by chronology.
                if low_t <= high_t:
                    emit_up(bt, bl)
                else:
                    emit_down(bt, bh)
            elif rose_from_low:
                if high_t <= low_t:
                    emit_down(bt, bh)
                else:
                    emit_up(bt, bl)
            continue

        if state == "UP":
            if bh > high:
                high = bh; high_t = bt
            if (high - bl) >= threshold_pips:
                emit_up(bt, bl)
            continue

        # state == "DOWN"
        if bl < low:
            low = bl; low_t = bt
        if (bh - low) >= threshold_pips:
            emit_down(bt, bh)

    out = pd.DataFrame(rows)
    if len(out) == 0:
        return out
    # Validate chronology
    bad = out[out["end_time"] < out["start_time"]]
    if len(bad):
        raise AssertionError(f"{len(bad)} swings have end_time < start_time; detector bug.")
    bad2 = out[out["conf_time"] < out["end_time"]]
    if len(bad2):
        raise AssertionError(f"{len(bad2)} swings have conf_time < end_time; detector bug.")
    # duration_bars = index(end) - index(start) + 1
    ts_to_idx = {t: j for j, t in enumerate(bars["timestamp"].tolist())}
    out["duration_bars"] = out.apply(
        lambda r: ts_to_idx[r["end_time"]] - ts_to_idx[r["start_time"]] + 1, axis=1
    )
    return out
