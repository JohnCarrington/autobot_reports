"""core.Engine (Setup A/C/SQ/TR) historical replay harness.

Drives the production `bounce_engine.core.Engine` through CLEAN days
from the Stage 0b verified manifest. REUSES the engine verbatim:

  * `bounce_engine.core.Config` and `bounce_engine.core.Engine`
  * `view_builder.build_view` for historical structural levels
  * No new entry condition, no new detector, no new exit rule
  * Env is tuned per-process (not .env mutation) for exit-mode flavours

Three exit configurations are supported:

  (a) `june_prod`  — SL 20 / scale half at +10 / TP 30 (production .env)
  (b) `sl12_tp30`  — SL 12 / scale half at +10 / TP 30 (operator spec)
  (c) `levels`     — core.Engine managed-exit mode (no fixed TP/SL)

The core engine honours these via its `BOUNCE_EXIT_MODE` + `.min_stop_pips`
settings; (b) is the SL-isolated variant the operator requested.

QM: supplied as a no-op (`qm_fn` returns None) in this iteration unless
`qm_decision_shadow_replay` is wired. The engine then treats QM as
"no verdict" — identical to production behaviour when the QM module
is OFF or empty.

NMS / HTF direction: supplied via `BOUNCE_HTF_DIRECTION_ENABLED=1`
(the production default); the engine's internal HTF read uses D1 / H4
EMA20 of the SAME archive we feed it (zero-lookahead).
"""
from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)

from autobot_v3_build.approved.stage0b_loader import (
    CleanDay, iter_clean_days, load_day_bars, partition_of,
)

OUT_DIR = Path(__file__).resolve().parent / "replay_out"
OUT_DIR.mkdir(exist_ok=True)


# ── env tuning (process-local only; no .env mutation) ──────────────────

_SET_ENV_DEFAULTS = {
    # Setup A active (default); SQ / TR / C per production:
    "BOUNCE_SQUEEZE_ENABLED": "1",
    "BOUNCE_TREND_ENABLED": "1",
    "BOUNCE_EXHAUSTION_ENABLED": "1",
    "BOUNCE_NEWS_VIEW_ENABLED": "1",
    "BOUNCE_HTF_DIRECTION_ENABLED": "1",
    "BOUNCE_TREND_HTF_PROOF_ENABLED": "1",
    "BOUNCE_C_MACD_FADING_ENABLED": "1",
    "BOUNCE_JUNE_EXHAUSTION_CLOSE_ENABLED": "1",
    "BOUNCE_ENTRY_HOURS_UTC": "06-21",
    "BOUNCE_BROKER_TP_PIPS": "100",
}

EXIT_MODES = {
    "june_prod": {"BOUNCE_EXIT_MODE": "june"},     # SL 20 / TP 30 / 50% at +10
    "sl12_tp30": {"BOUNCE_EXIT_MODE": "june"},     # same, min_stop_pips overridden to 12 in cfg
    "levels":    {"BOUNCE_EXIT_MODE": "levels"},   # managed exit (reference only)
}


def _apply_env(mode: str) -> None:
    """Mutate os.environ for THIS process only. No .env file touched."""
    for k, v in _SET_ENV_DEFAULTS.items():
        os.environ[k] = v
    for k, v in EXIT_MODES[mode].items():
        os.environ[k] = v


# ── Trade capture ──────────────────────────────────────────────────────

@dataclass
class ReplayTrade:
    open_ts: Optional[datetime] = None
    side: str = ""
    entry_price: float = 0.0
    stop: float = 0.0
    setup: str = ""
    mode: str = ""
    close_ts: Optional[datetime] = None
    close_price: float = 0.0
    close_reason: str = ""
    partials: List[Dict[str, Any]] = field(default_factory=list)
    stop_history: List[Dict[str, Any]] = field(default_factory=list)
    gross_pips: Optional[float] = None
    net_pips: Optional[float] = None
    partition: str = ""
    session: str = ""   # LONDON / NY / OTHER


class ReplayOrderPort:
    """Captures all open/close/partial_close/move_stop calls from core.Engine."""

    def __init__(self, pair: str = "GBPUSD", partition: str = "DEV"):
        self.pair = pair
        self.partition = partition
        self.trades: List[ReplayTrade] = []
        self._open: Optional[ReplayTrade] = None

    def _session_for(self, ts: datetime) -> str:
        h = ts.hour
        if 7 <= h < 13:
            return "LONDON"
        if 13 <= h < 22:
            return "NY"
        return "OTHER"

    def open(self, *, side: str, price: float, stop: float, ts: datetime,
             reason: str, setup: Optional[str] = None,
             mode: Optional[str] = None) -> bool:
        # The engine supports multiple slots; capture one trade per call
        # and tag it with (setup, side) uniqueness in the record.
        t = ReplayTrade(
            open_ts=ts, side=side, entry_price=price, stop=stop,
            setup=str(setup or ""), mode=str(mode or ""),
            partition=self.partition, session=self._session_for(ts),
        )
        self._open = t
        self.trades.append(t)
        return True

    def close(self, *, ts: datetime, price: float, reason: str,
              setup: Optional[str] = None, mode: Optional[str] = None) -> bool:
        # Close the MOST RECENT open trade matching setup/mode if provided.
        trade = None
        for t in reversed(self.trades):
            if t.close_ts is not None:
                continue
            if setup is not None and t.setup != str(setup):
                continue
            if mode is not None and t.mode != str(mode):
                continue
            trade = t
            break
        if trade is None:
            return False
        trade.close_ts = ts
        trade.close_price = price
        trade.close_reason = reason
        gross = (price - trade.entry_price) if trade.side == "LONG" else (trade.entry_price - price)
        trade.gross_pips = round(gross, 2)
        return True

    def move_stop(self, *, stop: float, ts: datetime,
                   setup: Optional[str] = None, mode: Optional[str] = None,
                   reason: Optional[str] = None) -> bool:
        for t in reversed(self.trades):
            if t.close_ts is not None:
                continue
            if setup is not None and t.setup != str(setup):
                continue
            if mode is not None and t.mode != str(mode):
                continue
            t.stop_history.append({"ts": ts.isoformat(), "stop": stop,
                                    "reason": reason or ""})
            t.stop = stop
            return True
        return False

    def partial_close(self, *, ts: datetime, price: float, size_ratio: float,
                       reason: str,
                       setup: Optional[str] = None,
                       mode: Optional[str] = None) -> bool:
        for t in reversed(self.trades):
            if t.close_ts is not None:
                continue
            if setup is not None and t.setup != str(setup):
                continue
            if mode is not None and t.mode != str(mode):
                continue
            delta = (price - t.entry_price) if t.side == "LONG" else (t.entry_price - price)
            t.partials.append({
                "ts": ts.isoformat(), "price": price, "size_ratio": size_ratio,
                "reason": reason, "pips": round(delta, 2),
            })
            return True
        return False


# ── Journal sink (silent) ──────────────────────────────────────────────

class _NullJournal:
    def __call__(self, text: str, **facts: Any) -> None:
        return
    def write(self, line: str) -> None:
        return


# ── History aggregators for view_builder ───────────────────────────────

def _m5_to_h1(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group 5m bars (true-UTC timestamped) into H1 OHLC candles. The
    bar's `ts` is the CLOSE of the H1 window at the next hour mark."""
    if not bars:
        return []
    out: Dict[datetime, Dict[str, Any]] = {}
    for b in bars:
        hour_key = b["ts"].replace(minute=0, second=0, microsecond=0)
        d = out.get(hour_key)
        if d is None:
            out[hour_key] = {
                "timestamp": (hour_key + timedelta(hours=1)).isoformat(),
                "open": b["open"],
                "high": b["high"],
                "low":  b["low"],
                "close": b["close"],
            }
        else:
            d["high"] = max(d["high"], b["high"])
            d["low"]  = min(d["low"],  b["low"])
            d["close"] = b["close"]
    return sorted(out.values(), key=lambda c: c["timestamp"])


def _h1_to_d1(h1_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group H1 → D1 by UTC date."""
    out: Dict[str, Dict[str, Any]] = {}
    for b in h1_bars:
        ts = b["timestamp"]
        day = ts[:10]
        d = out.get(day)
        if d is None:
            out[day] = {
                "timestamp": day + "T00:00:00+00:00",
                "open": b["open"],
                "high": b["high"],
                "low":  b["low"],
                "close": b["close"],
            }
        else:
            d["high"] = max(d["high"], b["high"])
            d["low"]  = min(d["low"],  b["low"])
            d["close"] = b["close"]
    return sorted(out.values(), key=lambda c: c["timestamp"])


# ── Historical bars pre-loader ─────────────────────────────────────────

@dataclass
class HistoryPool:
    all_m5: List[Dict[str, Any]] = field(default_factory=list)

    def h1_up_to(self, ts: datetime, lookback_hours: int = 240) -> List[Dict[str, Any]]:
        start = ts - timedelta(hours=lookback_hours)
        m5 = [b for b in self.all_m5 if start <= b["ts"] < ts]
        return _m5_to_h1(m5)

    def d1_up_to(self, ts: datetime, lookback_days: int = 30) -> List[Dict[str, Any]]:
        h1 = self.h1_up_to(ts, lookback_hours=lookback_days * 24 + 48)
        return _h1_to_d1(h1)


# ── Main replay ─────────────────────────────────────────────────────────

def _bars_in_window(all_bars: List[Dict[str, Any]],
                     start: datetime, end: datetime) -> List[Dict[str, Any]]:
    return [b for b in all_bars if start <= b["ts"] < end]


def _view_levels_fn_factory(view_cache: Dict[str, Any], pool: "HistoryPool",
                              cur_price: Dict[str, float]):
    """Returns a closure for core.Engine.levels_fn.

    The engine calls `levels_fn()` with no args per the Config contract.
    We synthesise a view for the CURRENT CALL day using view_builder."""
    def _fn():
        import view_builder as _vb
        from bounce_engine.core import Level as _CL
        day = cur_price.get("today") or ""
        if not day:
            return []
        if day in view_cache:
            raw = view_cache[day]
        else:
            try:
                now_utc = datetime.fromisoformat(day + "T06:30:00+00:00")
                px = cur_price.get("ref", 0.0)
                d1 = pool.d1_up_to(now_utc, lookback_days=30)
                h1 = pool.h1_up_to(now_utc, lookback_hours=240)
                raw = _vb.build_view(
                    now_utc=now_utc, price=float(px),
                    d1_candles=d1, h1_candles=h1,
                    events_for_date_fn=lambda d: [],
                )
            except Exception:
                raw = {"levels": []}
            view_cache[day] = raw
        out = []
        for lv in raw.get("levels") or []:
            try:
                out.append(_CL(price=float(lv["price"]), name=str(lv.get("type") or "level")))
            except Exception:
                continue
        return out
    return _fn


def _qm_fn_no_op(level: Any, side: Any) -> Any:
    """QM-disabled: returns None. Core engine treats as 'no verdict'."""
    return None


def _simulate_broker_stops_pre_bar(eng: Any, port: "ReplayOrderPort", bar: Any) -> None:
    """Fire stop fills that the broker would have executed before this bar's
    close. For each still-open position inside the engine, if the bar's
    high/low breached the position's stop, close that trade in the port
    at the stop price (+0.5 pip adverse slip for cost realism) and clear
    the engine's slot so subsequent management is a no-op.
    """
    # Engine stores positions in self._slots keyed by (setup, side).
    try:
        slots = getattr(eng, "_slots", {})
    except Exception:
        return
    for key, slot in list(slots.items()):
        pos = getattr(slot, "position", None)
        if pos is None:
            continue
        stop = getattr(pos, "stop", None)
        side = getattr(pos, "side", None)
        if stop is None or side is None:
            continue
        # LONG stops at bar.low <= stop; SHORT stops at bar.high >= stop
        if side == "LONG" and bar.low <= stop:
            fill_price = stop  # fill at the stop; adverse slip added in net-pips step
            _close_matching_trade(port, bar.ts, fill_price, "STOP",
                                   setup=pos.setup, side=side)
            slot.position = None
        elif side == "SHORT" and bar.high >= stop:
            fill_price = stop
            _close_matching_trade(port, bar.ts, fill_price, "STOP",
                                   setup=pos.setup, side=side)
            slot.position = None


def _close_matching_trade(port: "ReplayOrderPort", ts: Any, price: float,
                            reason: str, setup: str, side: str) -> None:
    """Match an open trade by (setup, side) only — the port's close()
    filters on `mode` which the Position object does not carry. Walk the
    port's trade list in reverse to find the most recent still-open match."""
    for t in reversed(port.trades):
        if t.close_ts is not None:
            continue
        if t.setup != str(setup):
            continue
        if t.side != str(side):
            continue
        t.close_ts = ts
        t.close_price = price
        t.close_reason = reason
        gross = (price - t.entry_price) if t.side == "LONG" else (t.entry_price - price)
        t.gross_pips = round(gross, 2)
        return


def _events_fn_no_op(now_utc: Optional[datetime] = None) -> List[Dict[str, Any]]:
    return []


def run_replay(mode: str,
                partition: str = "DEV",
                max_days: Optional[int] = None,
                verbose: bool = False) -> Dict[str, Any]:
    """Run core.Engine replay for one exit-mode flavour on `partition` clean days."""
    assert mode in EXIT_MODES, f"unknown mode {mode}"
    _apply_env(mode)
    # Imports deferred until env is primed
    from bounce_engine.core import Bar, Config, Engine

    cfg = Config()
    if mode == "sl12_tp30":
        # Isolated SL variant: June mode exits but with the SL distance
        # reduced from 20 → 12 pips. June TP (30p) and partial-exit at
        # +10p preserved. Config is a frozen dataclass → dataclasses.replace.
        import dataclasses as _dc
        cfg = _dc.replace(cfg, june_sl_pips=12.0)
    port = ReplayOrderPort(partition=partition)
    journal = _NullJournal()

    # Shared view cache + current-day ref — mutated per bar
    view_cache: Dict[str, Any] = {}
    cur_ref: Dict[str, float] = {"today": "", "ref": 0.0}

    # Pre-load all 5m bars across all clean days in partition (TZ corrected)
    pool = HistoryPool()
    days = list(iter_clean_days(partition))
    if max_days is not None:
        days = days[:max_days]
    for cd in days:
        pool.all_m5.extend(load_day_bars(cd))
    pool.all_m5.sort(key=lambda b: b["ts"])
    if verbose:
        print(f"[replay] partition={partition} mode={mode} days={len(days)} bars={len(pool.all_m5)}")

    eng = Engine(
        cfg=cfg,
        levels_fn=_view_levels_fn_factory(view_cache, pool, cur_ref),
        qm_fn=_qm_fn_no_op,
        orders=port,
        journal=journal,
        events_fn=_events_fn_no_op,
    )

    # Warm up: feed engine the first 3 days of pre-partition archive if available
    # (optional; core.Engine falls back gracefully if cold).

    # Drive each bar
    bar_count = 0
    for b in pool.all_m5:
        try:
            day = b["ts"].date().isoformat()
            cur_ref["today"] = day
            cur_ref["ref"] = float(b["close"])
            bar = Bar(ts=b["ts"], open=b["open"], high=b["high"],
                       low=b["low"], close=b["close"])

            # SIMULATE BROKER STOP HITS before the engine processes the
            # bar. core.Engine does not check bar.low/bar.high against the
            # position's stop — it assumes the broker fires the stop. In
            # the replay we must do that ourselves. Favourable-ordering
            # choice: if BOTH stop AND partial could fire on the same
            # bar, we resolve stop FIRST (conservative). Match the live
            # eval_historical.py cost model.
            _simulate_broker_stops_pre_bar(eng, port, bar)

            eng.on_bar_close(bar)
            bar_count += 1
            if verbose and bar_count % 25000 == 0:
                print(f"[replay] processed {bar_count}/{len(pool.all_m5)}")
        except Exception as exc:
            if verbose:
                print(f"[replay] exc at {b['ts']}: {type(exc).__name__}:{exc}")

    # Finalise: compute net pips per trade (gross less costs)
    SPREAD = 0.9
    SLIP = 0.5
    for t in port.trades:
        if t.gross_pips is None:
            continue
        # Simple cost model: 1 round-trip = spread + slip on stop/warning fills
        # Use the exit reason to decide:
        if "STOP" in t.close_reason.upper() or "WARNING" in t.close_reason.upper():
            cost = SPREAD + SLIP
        else:
            cost = SPREAD
        t.net_pips = round(t.gross_pips - cost, 2)

    return _summarise(port, mode, partition, len(days), len(pool.all_m5))


def _summarise(port: ReplayOrderPort, mode: str, partition: str,
                 n_days: int, n_bars: int) -> Dict[str, Any]:
    trades = [t for t in port.trades if t.close_ts is not None]
    opens = [t for t in port.trades if t.close_ts is None]
    wins = [t for t in trades if (t.net_pips or 0) > 0]
    losses = [t for t in trades if (t.net_pips or 0) <= 0]
    gross = sum(t.gross_pips or 0 for t in trades)
    net = sum(t.net_pips or 0 for t in trades)
    gross_wins = sum(t.net_pips or 0 for t in wins)
    gross_losses = sum(abs(t.net_pips or 0) for t in losses)
    pf = (gross_wins / gross_losses) if gross_losses else float("inf")
    # Draw-down (equity curve on net_pips in open order)
    eq = 0.0
    peak = 0.0
    dd = 0.0
    for t in trades:
        eq += (t.net_pips or 0)
        if eq > peak:
            peak = eq
        if peak - eq > dd:
            dd = peak - eq
    # By session
    by_sess = {}
    for s in ("LONDON", "NY", "OTHER"):
        sub = [t for t in trades if t.session == s]
        s_wins = [t for t in sub if (t.net_pips or 0) > 0]
        s_net = sum(t.net_pips or 0 for t in sub)
        by_sess[s] = {
            "n": len(sub),
            "wins": len(s_wins),
            "net_pips": round(s_net, 1),
            "winpct": round(100 * len(s_wins) / max(len(sub), 1), 1),
        }
    # Exit-reason breakdown
    by_reason: Dict[str, int] = {}
    for t in trades:
        by_reason[t.close_reason] = by_reason.get(t.close_reason, 0) + 1
    # Reversal captures (>=30 p realised)
    big_wins = sum(1 for t in trades if (t.net_pips or 0) >= 30)
    big_wins_pips = sum(t.net_pips for t in trades if (t.net_pips or 0) >= 30)

    return {
        "mode": mode,
        "partition": partition,
        "n_clean_days": n_days,
        "n_bars_processed": n_bars,
        "n_trades_closed": len(trades),
        "n_trades_still_open": len(opens),
        "win_rate_pct": round(100 * len(wins) / max(len(trades), 1), 1),
        "gross_pips": round(gross, 1),
        "net_pips": round(net, 1),
        "profit_factor": round(pf, 2) if pf != float("inf") else None,
        "max_drawdown_pips": round(dd, 1),
        "by_session": by_sess,
        "by_exit_reason": by_reason,
        "captures_ge_30p": big_wins,
        "captures_ge_30p_pips": round(big_wins_pips, 1) if big_wins_pips else 0.0,
    }


def write_trades(port: ReplayOrderPort, path: Path) -> None:
    with path.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "open_ts", "close_ts", "side", "setup", "mode", "entry_price",
            "stop", "close_price", "close_reason", "gross_pips", "net_pips",
            "partition", "session", "n_partials",
        ])
        w.writeheader()
        for t in port.trades:
            w.writerow({
                "open_ts": t.open_ts.isoformat() if t.open_ts else "",
                "close_ts": t.close_ts.isoformat() if t.close_ts else "",
                "side": t.side,
                "setup": t.setup,
                "mode": t.mode,
                "entry_price": t.entry_price,
                "stop": t.stop,
                "close_price": t.close_price,
                "close_reason": t.close_reason,
                "gross_pips": t.gross_pips if t.gross_pips is not None else "",
                "net_pips": t.net_pips if t.net_pips is not None else "",
                "partition": t.partition,
                "session": t.session,
                "n_partials": len(t.partials),
            })


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=list(EXIT_MODES), required=True)
    ap.add_argument("--partition", choices=["DEV", "HOLDOUT", "OOS"], default="DEV")
    ap.add_argument("--max-days", type=int, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    summary = run_replay(args.mode, partition=args.partition,
                           max_days=args.max_days, verbose=args.verbose)
    # Dump
    tag = f"{args.mode}_{args.partition}"
    (OUT_DIR / f"summary_{tag}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
