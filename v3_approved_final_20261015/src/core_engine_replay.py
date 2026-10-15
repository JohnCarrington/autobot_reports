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
from autobot_v3_build.approved.tick_fills import TickResolver
from autobot_v3_build.approved.historical_qm import HistoricalQM

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
    # realised_pips is the correct per-leg-weighted total: sum over all legs
    # (every partial + the final close) of leg_distance_pips × size_closed.
    # gross_pips is kept as an alias of realised_pips for CSV compatibility.
    gross_pips: Optional[float] = None
    realised_pips: Optional[float] = None
    net_pips: Optional[float] = None
    # Fill-source tagging: "bar" (bar-high/low breach), "tick" (intra-bar tick
    # fired the stop), or "" (engine-managed close via on_bar_close).
    fill_source: str = ""
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
        # Store the raw unweighted leg distance only. The realised-pips
        # and net-pips totals are computed by finalise_pnl() which sums
        # all legs (partials + final) weighted by their respective
        # size_ratio.
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


def _simulate_broker_stops_pre_bar(eng: Any, port: "ReplayOrderPort", bar: Any,
                                     ticks: Optional[TickResolver] = None,
                                     bar_window_seconds: int = 300) -> None:
    """Fire stop fills that the broker would have executed before this bar's
    close. For each still-open position inside the engine, if a tick in
    [bar.ts, bar.ts + 5min) breached the position's stop (tick-based,
    preferred) OR the bar's high/low did (bar-close fallback), close
    that trade in the port and clear the engine's slot so subsequent
    management is a no-op.

    Tick-based resolution gives the true intra-bar fill time + price
    (bid for LONG stops, ask for SHORT stops). The bar-close fallback
    is used only when `ticks` is None or the day is not in the tick
    cache. See `project_tick_tz_mixed_20260928` for TZ coverage rules.
    """
    try:
        slots = getattr(eng, "_slots", {})
    except Exception:
        return
    bar_end = bar.ts + timedelta(seconds=bar_window_seconds)
    iso = bar.ts.date().isoformat()
    tick_coverage = (ticks is not None) and ticks.has_coverage(iso)
    for key, slot in list(slots.items()):
        pos = getattr(slot, "position", None)
        if pos is None:
            continue
        stop = getattr(pos, "stop", None)
        side = getattr(pos, "side", None)
        setup = getattr(pos, "setup", None)
        if stop is None or side is None or setup is None:
            continue
        hit_ts: Optional[datetime] = None
        hit_px: Optional[float] = None
        fill_source = ""
        if tick_coverage:
            res = ticks.first_breach(bar.ts, bar_end, side=side, stop=float(stop))
            if res is not None:
                hit_ts, hit_px = res
                fill_source = "tick"
        if hit_ts is None:
            # Fall back to bar-close resolution: fill at the stop price on
            # the breaching bar (only when no tick coverage, e.g. 2026-04+).
            if side == "LONG" and bar.low <= stop:
                hit_ts, hit_px, fill_source = bar.ts, float(stop), "bar"
            elif side == "SHORT" and bar.high >= stop:
                hit_ts, hit_px, fill_source = bar.ts, float(stop), "bar"
        if hit_ts is None:
            continue
        _close_matching_trade(port, hit_ts, hit_px, "STOP",
                               setup=str(setup), side=str(side),
                               fill_source=fill_source)
        slot.position = None


def _close_matching_trade(port: "ReplayOrderPort", ts: Any, price: float,
                            reason: str, setup: str, side: str,
                            fill_source: str = "bar") -> None:
    """Match an open trade by (setup, side) only — the port's close()
    filters on `mode` which the Position object does not carry. Walk the
    port's trade list in reverse to find the most recent still-open match.
    The realised_pips total is computed later by finalise_pnl()."""
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
        t.fill_source = fill_source
        return


def finalise_pnl(trade: "ReplayTrade", spread: float = 0.9,
                 slip_on_stop: float = 0.5) -> None:
    """Compute per-leg weighted realised_pips and net_pips for a closed
    trade.

      realised = Σ (leg_distance_pips × size_closed_this_leg)
      net      = realised − Σ (cost_this_leg × size_closed_this_leg)

    Costs: every exit leg pays `spread` (0.9 pip adverse). A leg paying
    at the stop or on a protective-exit warning additionally pays
    `slip_on_stop` (0.5 pip).

    Partials are target-like (no slip). The final leg carries slip only
    when `close_reason` is a STOP/WARNING event. If the engine never
    closed the trade (replay ended with it still open), realised stays
    at the partial sum and net is reduced only by partial costs.
    """
    if trade.open_ts is None or trade.entry_price == 0.0:
        return
    pip_sign = 1.0 if trade.side == "LONG" else -1.0
    realised = 0.0
    cost = 0.0
    size_closed = 0.0
    for p in trade.partials:
        try:
            ratio = float(p.get("size_ratio", 0.0))
            pips_leg = pip_sign * (float(p["price"]) - trade.entry_price)
        except (KeyError, TypeError, ValueError):
            continue
        realised += pips_leg * ratio
        cost += spread * ratio   # target-like, no slip
        size_closed += ratio
    final_ratio = max(0.0, 1.0 - size_closed)
    if trade.close_ts is not None and final_ratio > 1e-9:
        final_pips_leg = pip_sign * (trade.close_price - trade.entry_price)
        realised += final_pips_leg * final_ratio
        reason_upper = (trade.close_reason or "").upper()
        # Slip model:
        #   fill_source = "tick"  → the fill price already reflects the
        #     real bid/ask at the breach tick; any gap-fill loss is
        #     baked into realised_pips. Do NOT add nominal slip.
        #   fill_source = "bar"   → fill is at the stop price only; apply
        #     the 0.5p slip estimate from eval_historical.py.
        #   fill_source = ""      → engine-managed close (TP, exhaustion,
        #     BE); no slip (target-like).
        is_stop = ("STOP" in reason_upper) or ("WARNING" in reason_upper)
        slip = slip_on_stop if (is_stop and trade.fill_source == "bar") else 0.0
        cost += (spread + slip) * final_ratio
    trade.realised_pips = round(realised, 2)
    trade.gross_pips = trade.realised_pips      # alias for backward-compat
    trade.net_pips = round(realised - cost, 2)


def _events_fn_no_op(now_utc: Optional[datetime] = None) -> List[Dict[str, Any]]:
    return []


def run_replay(mode: str,
                partition: str = "DEV",
                max_days: Optional[int] = None,
                verbose: bool = False,
                use_ticks: bool = True,
                use_qm: bool = True) -> Dict[str, Any]:
    """Run core.Engine replay for one exit-mode flavour on `partition` clean days.

    use_qm=True binds the engine's qm_fn to the HistoricalQM shadow driver
    (`autobot_v3_build/approved/historical_qm.py`). use_qm=False preserves
    the earlier QM-disabled behaviour (qm_fn → None).
    """
    assert mode in EXIT_MODES, f"unknown mode {mode}"
    _apply_env(mode)
    # Imports deferred until env is primed
    from bounce_engine.core import Bar, Config, Engine
    # Verify we're really inside production bounce_engine/core.py, not
    # some v3 variant. Both the class and its config dataclass live in
    # /opt/tradingbot/bounce_engine/core.py.
    _eng_module = Engine.__module__
    _cfg_file = Config.__module__
    assert _eng_module == "bounce_engine.core", (
        f"Engine class is not bounce_engine.core.Engine (got {_eng_module!r})")
    assert _cfg_file == "bounce_engine.core", (
        f"Config class is not bounce_engine.core.Config (got {_cfg_file!r})")

    cfg = Config()
    if verbose:
        print(f"[replay] engine={Engine.__module__}.{Engine.__name__} "
              f"cfg.exit_mode={cfg.exit_mode!r} "
              f"cfg.june_sl_pips={cfg.june_sl_pips} "
              f"cfg.june_tp_pips={cfg.june_tp_pips} "
              f"cfg.june_partial_pips={cfg.june_partial_pips} "
              f"cfg.squeeze_enabled={cfg.squeeze_enabled} "
              f"cfg.trend_enabled={cfg.trend_enabled} "
              f"cfg.htf_direction_enabled={cfg.htf_direction_enabled}")
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

    # Tick resolver for intra-bar stop fills. 2026-04-01+ is unusable
    # (per project_tick_tz_mixed_20260928) so OOS partition cannot use
    # ticks beyond 2026-03-31 — all OOS dates in this manifest are
    # ≤ 2026-03-31 so coverage is complete. For DEV/HOLDOUT (2024-2025)
    # ticks are complete.
    ticks: Optional[TickResolver] = None
    if use_ticks:
        target = {cd.date_iso for cd in days}
        ticks = TickResolver(pair="GBPUSD", target_dates=target, verbose=verbose)
        ticks.prepare()
        if verbose:
            covered = sum(1 for cd in days if ticks.has_coverage(cd.date_iso))
            print(f"[replay] tick coverage: {covered}/{len(days)} clean days")

    hqm: Optional[HistoricalQM] = HistoricalQM() if use_qm else None
    eng = Engine(
        cfg=cfg,
        levels_fn=_view_levels_fn_factory(view_cache, pool, cur_ref),
        qm_fn=(hqm.qm_fn if hqm is not None else _qm_fn_no_op),
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
            # bar, we resolve stop FIRST (conservative). Tick-based
            # resolution (bid for LONG stops, ask for SHORT stops) is
            # preferred; bar-close fallback applies only when the day
            # has no tick coverage.
            _simulate_broker_stops_pre_bar(eng, port, bar, ticks=ticks)

            eng.on_bar_close(bar)
            if hqm is not None:
                hqm.push_bar(bar)
            bar_count += 1
            if verbose and bar_count % 25000 == 0:
                print(f"[replay] processed {bar_count}/{len(pool.all_m5)}")
        except Exception as exc:
            if verbose:
                print(f"[replay] exc at {b['ts']}: {type(exc).__name__}:{exc}")

    # Finalise: compute per-leg weighted realised_pips + net_pips for
    # every trade. This replaces the previous single-leg accounting that
    # ignored partial exits (producing +30 for a +30 TP trade that was
    # actually +20 after the +10 half-partial).
    for t in port.trades:
        finalise_pnl(t)

    summary = _summarise(port, mode, partition, len(days), len(pool.all_m5))
    if hqm is not None:
        summary["qm_verdict_counts"] = dict(hqm.verdicts)
        summary["use_qm"] = True
    else:
        summary["use_qm"] = False
    summary["use_ticks"] = bool(use_ticks)
    return summary


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
    # Fill-source attribution (which stops were tick-resolved vs. bar-close
    # fallback — tells us how much of the realised bleed is tick-faithful).
    stop_trades = [t for t in trades if t.fill_source in ("tick", "bar")]
    stop_tick = sum(1 for t in stop_trades if t.fill_source == "tick")
    stop_bar = sum(1 for t in stop_trades if t.fill_source == "bar")
    partial_count = sum(1 for t in trades if t.partials)

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
        "stops_resolved_via_tick": stop_tick,
        "stops_resolved_via_bar": stop_bar,
        "trades_with_partial_banked": partial_count,
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
    ap.add_argument("--no-ticks", action="store_true",
                    help="disable intra-bar tick resolution (use bar-close fallback only)")
    ap.add_argument("--no-qm", action="store_true",
                    help="disable the HistoricalQM shadow (qm_fn → None, as the original build)")
    args = ap.parse_args()
    summary = run_replay(args.mode, partition=args.partition,
                           max_days=args.max_days, verbose=args.verbose,
                           use_ticks=not args.no_ticks,
                           use_qm=not args.no_qm)
    # Dump — filename includes mode + partition + qm/tick flags so
    # comparison runs don't clobber each other.
    qm_tag = "qmON" if not args.no_qm else "qmOFF"
    tick_tag = "tickON" if not args.no_ticks else "tickOFF"
    tag = f"{args.mode}_{args.partition}_{qm_tag}_{tick_tag}"
    (OUT_DIR / f"summary_{tag}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
