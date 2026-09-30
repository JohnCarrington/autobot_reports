#!/usr/bin/env python3
"""
true_replay.py — Feed historical candles through the live AutoBot stack.

Mocks only IG API calls. Everything else runs as live: evaluate_signals,
trade_manager.monitor_positions, profit management, BE stops, trails.

Trade closes are captured by patching _reset_trade_state to log PnL
before wiping the state dict.

When a specific date is given, the prior 5 days of candles are fed through
the full strategy stack (with synthetic ticks) to warm up indicator state,
briefing state, and strategy singletons before recording begins.

Usage:
    python3 true_replay.py GBPUSD
    python3 true_replay.py GBPUSD 2026-04-10
"""
import sys, os, json, time, logging, argparse, uuid
from pathlib import Path
from unittest.mock import MagicMock
from typing import Any, Dict, List, Optional

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")

from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env", override=True)

# Replay clock — updated each tick so time-based exits work
_replay_epoch = [0.0]
_orig_time_time = time.time
time.time = lambda: _replay_epoch[0] if _replay_epoch[0] > 0 else _orig_time_time()

# Prevent real sleeps during replay (news_calendar retry, close verification, etc.)
_orig_time_sleep = time.sleep
time.sleep = lambda s: None

# Patch autobot's _session_now to use replay clock (it uses datetime.now(tz), not time.time())
import datetime as _dt_mod

# Block ALL external HTTP during replay (Telegram, news_calendar, etc.)
import requests as _req
_FakeResp = type("R", (), {
    "status_code": 200, "text": "[]", "ok": True,
    "json": lambda self: [], "raise_for_status": lambda self: None,
    "content": b"[]", "headers": {},
})
_req.post = lambda *a, **kw: _FakeResp()
_req.get = lambda *a, **kw: _FakeResp()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
for m in ("indicators", "morning_briefing", "regime_router",
          "briefing_liquidity", "briefing_hunt", "london_open_pullback"):
    logging.getLogger(m).setLevel(logging.WARNING)
logger = logging.getLogger("true_replay")

import pandas as pd
import numpy as np
from indicators import add_indicators, IndicatorsConfig

# ── Trade log ────────────────────────────────────────────────────────
_trade_log: List[Dict] = []
_record_from_epoch = [0.0]  # only log trades opened at or after this epoch

# ── Mock IG API ──────────────────────────────────────────────────────
_fake_ig = MagicMock()
_fake_ig.fetch_open_positions.return_value = (200, pd.DataFrame())
_fake_ig.fetch_deal_by_deal_reference = lambda ref: {"dealStatus": "ACCEPTED", "dealId": f"DID_{ref}", "level": None}

import ig_auth
ig_auth.get_ig_session = lambda: (_fake_ig, {"CST": "fake", "X-SECURITY-TOKEN": "fake"}, "FAKE")

import open_sb_now as osb_module
osb_module.open_sb_now = lambda direction, epic, size, limit_distance, stop_distance: {"dealReference": f"REPLAY_{uuid.uuid4().hex[:8]}"}
osb_module.get_ig_session = ig_auth.get_ig_session

import close_sb_now as csb_module

def _mock_close_sb_now(epic):
    """Mock close that deactivates the position in EPIC_STATE so verification passes."""
    for pk, st in trade_executor.EPIC_STATE.items():
        if st.get("active") and st.get("epic") == epic:
            st["active"] = False
    return {"dealStatus": "ACCEPTED"}

def _mock_close_by_deal_id(deal_id, **kw):
    """Mock close-by-deal that deactivates the matching position."""
    for pk, st in trade_executor.EPIC_STATE.items():
        if not st.get("active"):
            continue
        did = st.get("deal_id") or st.get("dealId") or ""
        if str(did) == str(deal_id):
            st["active"] = False
            return {"dealStatus": "ACCEPTED"}
    # Fallback: deactivate first active position (deal_id mismatch)
    for pk, st in trade_executor.EPIC_STATE.items():
        if st.get("active"):
            st["active"] = False
            return {"dealStatus": "ACCEPTED"}
    return {"dealStatus": "ACCEPTED"}

csb_module.close_sb_now = _mock_close_sb_now
csb_module.close_by_deal_id = _mock_close_by_deal_id
csb_module.get_ig_session = ig_auth.get_ig_session

import trade_executor
# Patch trade_executor's own module-level references (imported before our mocks)
trade_executor.close_sb_now = _mock_close_sb_now
trade_executor.close_by_deal_id = _mock_close_by_deal_id

def _mock_get_open_positions():
    """Return IG-shaped position dicts for every active position in EPIC_STATE."""
    positions = []
    for pk, st in trade_executor.EPIC_STATE.items():
        if st.get("active"):
            positions.append({
                "position": {
                    "dealId": st.get("deal_id", ""),
                    "direction": st.get("direction", ""),
                    "size": 1,
                },
                "market": {
                    "epic": st.get("epic", ""),
                },
            })
    return positions

csb_module.get_open_positions = _mock_get_open_positions

def _mock_position_still_open(**kwargs):
    """Return True if the position is tracked as active in EPIC_STATE."""
    epic = kwargs.get("epic", "")
    deal_id = kwargs.get("deal_id", "")
    # When deal_id is provided, check ONLY by deal_id (not epic)
    if deal_id:
        for pk, st in trade_executor.EPIC_STATE.items():
            if st.get("active") and (st.get("deal_id") == deal_id or st.get("dealId") == deal_id):
                return True
        return False
    # Fallback: check by epic
    for pk, st in trade_executor.EPIC_STATE.items():
        if st.get("active") and st.get("epic") == epic:
            return True
    return False

trade_executor._position_still_open = _mock_position_still_open

# ── Intercept _reset_trade_state to capture trade closes ─────────────
_orig_reset = trade_executor._reset_trade_state

def _intercepted_reset(pos_key):
    """Log the trade before the state is wiped."""
    pos_key = str(pos_key).strip()
    st = trade_executor.EPIC_STATE.get(pos_key)
    if st and st.get("entry_price") and st.get("direction"):
        direction = st.get("direction", "")
        entry = float(st.get("entry_price", 0))
        exit_p = float(st.get("exit_price") or st.get("last_mid") or entry)
        mode = st.get("mode", "?")
        reason = st.get("close_reason", "UNKNOWN")
        open_time = st.get("open_time", 0)

        if direction == "BUY":
            pnl = exit_p - entry
        elif direction == "SELL":
            pnl = entry - exit_p
        else:
            pnl = 0

        peak_price = st.get("peak_fav_price")
        peak_time = st.get("peak_fav_time") or 0
        if peak_price is None:
            mfe = max(pnl, 0.0)
            peak_time = open_time
        elif direction == "BUY":
            mfe = max(peak_price - entry, 0.0)
        elif direction == "SELL":
            mfe = max(entry - peak_price, 0.0)
        else:
            mfe = 0.0
        duration_at_peak_before_close = max(0.0, (_replay_epoch[0] - peak_time) / 60.0)

        logger.info(
            f"🔴 CLOSE {direction} {mode} @ {exit_p:.2f} "
            f"(entry={entry:.2f}) PnL={pnl:+.1f}p reason={reason}"
        )
        # Only record trades that opened on the target date (skip warmup trades)
        if open_time >= _record_from_epoch[0]:
            _trade_log.append({
                "mode": mode, "direction": direction,
                "entry": entry, "exit": exit_p,
                "pnl": pnl, "reason": reason,
                "open_time": open_time,
                "close_time": _replay_epoch[0],
                "mfe": mfe,
                "time_at_peak": peak_time,
                "duration_at_peak_before_close": duration_at_peak_before_close,
            })

        # Record WS close time for 60-min cooldown
        if mode == "WINDOW_SWEEP":
            from strategy_logic import evaluate_signals as _es
            if not hasattr(_es, "_ws_last_close"):
                _es._ws_last_close = {}
            # Use pair name from epic (e.g. "CS.D.GBPUSD.TODAY.IP" → "GBPUSD")
            _ws_sym = (st.get("epic", "").split(".")[2] if "." in st.get("epic", "") else "").upper()
            if _ws_sym:
                _es._ws_last_close[_ws_sym] = _replay_epoch[0]

        # Clear profit management state
        from trade_manager import _PROFIT_MGMT_BY_EPIC, _BRIEFING_TP_BY_EPIC, _SWEEP_MGMT_BY_EPIC
        epic = st.get("epic", "")
        for key in [epic, pos_key]:
            _PROFIT_MGMT_BY_EPIC.pop(key, None)
            _BRIEFING_TP_BY_EPIC.pop(key, None)
            _SWEEP_MGMT_BY_EPIC.pop(key, None)

    _orig_reset(pos_key)

trade_executor._reset_trade_state = _intercepted_reset

# ── Intercept execute_trade to set open_time from replay clock ───────
_orig_execute = trade_executor.execute_trade

def _patched_execute(decision, epic):
    result = _orig_execute(decision, epic)
    if result and isinstance(result, dict) and result.get("dealId"):
        # Find the state entry and set open_time to replay clock
        mode = str(getattr(decision, "mode", "DEFAULT")).strip().upper()
        pk = trade_executor._pos_key(str(epic), mode)
        st = trade_executor.EPIC_STATE.get(pk)
        if st:
            st["open_time"] = _replay_epoch[0]
            st["peak_fav_price"] = float(st.get("entry_price", 0) or 0)
            st["peak_fav_time"] = _replay_epoch[0]
            logger.info(
                f"🟢 OPEN {st.get('direction','')} {mode} {epic} "
                f"@ {st.get('entry_price',0):.2f} SL={st.get('sl',0):.1f} TP={st.get('tp',0):.1f}"
            )
    return result

trade_executor.execute_trade = _patched_execute

# ── Candle data ──────────────────────────────────────────────────────
CANDLE_DIR = Path("/opt/tradingbot/data/candles_enriched")
TICK_DIR = Path("/opt/tradingbot/data/ticks")
CFG = IndicatorsConfig(bb_period=20, bb_std=2.0, macd_fast=35, macd_slow=45, macd_signal=30)

def load_candles(pair, dates=None):
    frames = []
    for f in sorted((CANDLE_DIR / pair).glob("*.csv")):
        if dates and f.stem not in dates: continue
        df = pd.read_csv(f); df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed"); frames.append(df)
    if not frames: return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)

def _bsearch_file_offset(filepath, target_date_str, file_size):
    """Binary search a sorted CSV for the first line whose date >= target_date_str."""
    with open(filepath, "r") as fh:
        lo, hi = 1, file_size - 1  # skip header
        while lo < hi:
            mid = (lo + hi) // 2
            fh.seek(mid)
            if mid > 0:
                fh.readline()  # skip partial line
            line = fh.readline()
            if not line:
                hi = mid
                continue
            if line[:10] < target_date_str:
                lo = mid + 1
            else:
                hi = mid
    return lo

def load_real_ticks(pair, start_date, end_date):
    """Load real tick data from histdata CSV, filtered to [start_date, end_date].
    Uses binary search to read only the needed rows from the sorted file.
    Returns dict with numpy arrays for fast iteration."""
    tick_file = TICK_DIR / f"{pair}_ticks_2026.csv"
    if not tick_file.exists():
        logger.warning(f"No tick file at {tick_file}")
        return None
    logger.info(f"Loading real ticks from {tick_file} for {start_date} to {end_date}...")

    import os
    from io import StringIO
    fpath = str(tick_file)
    fsize = os.path.getsize(fpath)
    start_str = str(start_date)[:10]
    end_next_str = str(pd.Timestamp(end_date) + pd.Timedelta(days=1))[:10]

    # Read header
    with open(fpath, "r") as fh:
        header = fh.readline()

    # Binary search for byte offsets of start and end dates
    off_start = _bsearch_file_offset(fpath, start_str, fsize)
    off_end = _bsearch_file_offset(fpath, end_next_str, fsize)

    # Read only the slice between those offsets
    with open(fpath, "r") as fh:
        fh.seek(off_start)
        if off_start > 0:
            fh.readline()  # skip partial line
        lines = []
        while True:
            line = fh.readline()
            if not line or line[:10] >= end_next_str:
                break
            lines.append(line)

    if not lines:
        logger.info("Loaded 0 real ticks")
        return None

    df = pd.read_csv(StringIO(header + "".join(lines)), parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Pre-extract numpy arrays for zero-overhead iteration
    ts_np = df["timestamp"].values
    epochs = ts_np.astype(np.int64) / 1e9
    result = {
        "ts_np": ts_np,
        "epochs": epochs,
        "bids": df["bid"].values,
        "asks": df["ask"].values,
        "mids": df["mid"].values,
        "count": len(df),
    }
    logger.info(f"Loaded {len(df)} real ticks in {len(lines)} lines")
    return result

# ── Main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pair", default="GBPUSD")
    parser.add_argument("date", nargs="?", default=None)
    args = parser.parse_args()

    pair = args.pair.upper()
    epic_map = {pair: f"CS.D.{pair}.TODAY.IP"}
    epic = epic_map[pair]

    dates = None
    if args.date:
        all_csvs = sorted((CANDLE_DIR / pair).glob("*.csv"))
        dates = [f.stem for f in all_csvs if f.stem <= args.date]

    candles = load_candles(pair, dates)
    if candles.empty:
        print(f"No candle data for {pair}"); return

    # Load briefings
    import morning_briefing
    briefing_index = []
    for f in sorted(Path("/opt/tradingbot/logs").glob(f"briefing_{pair}_*.json")):
        try:
            data = json.loads(f.read_text())
            bt = data.get("briefing_time")
            if bt:
                ts = pd.Timestamp(bt)
                ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
                briefing_index.append((ts, data))
        except: pass
    briefing_index.sort(key=lambda x: x[0])

    def _get_briefing_at(candle_ts):
        result = None
        for bts, bdata in briefing_index:
            if bts <= candle_ts: result = bdata
            else: break
        return result

    _current_briefing = {}
    morning_briefing.get_briefing = lambda sym=None: _current_briefing.get(str(sym or "").upper())

    # Initialize AutoBot (after all mocks applied)
    from autobot import AutoBot, candle_builder, load_news_windows, _save_last_trade_times
    import autobot as _autobot_mod2

    # Patch session gate to use replay clock instead of wall-clock datetime.now()
    def _replay_session_now():
        from zoneinfo import ZoneInfo
        if _replay_epoch[0] > 0:
            return _dt_mod.datetime.fromtimestamp(_replay_epoch[0], tz=ZoneInfo(_autobot_mod2.SESSION_TZ))
        return None
    _autobot_mod2._session_now = _replay_session_now

    load_news_windows()
    bot = AutoBot(epic_map)
    candle_builder.set_symbol_epic(pair, epic)

    # Clear stale cooldown timers (loaded from disk with wall-clock timestamps)
    # and prevent replay from writing cooldown state to disk
    bot.last_trade_ts_by_key.clear()
    import autobot as _autobot_mod
    _autobot_mod._save_last_trade_times = lambda d: None

    SPREAD = 0.8
    WARMUP = 50

    # Determine replay start and recording boundary
    if args.date:
        replay_date = pd.Timestamp(args.date).date()
        target_start_idx = next(
            (i for i in range(len(candles)) if candles.iloc[i]["timestamp"].date() == replay_date), None
        )
        if target_start_idx is None:
            print(f"No candles for {args.date}"); return
        # Feed from WARMUP candles into data — warms up indicators + strategy state
        replay_start = WARMUP
        _record_from_epoch[0] = candles.iloc[target_start_idx]["timestamp"].timestamp()
        logger.info(
            f"Warmup: feeding {target_start_idx - replay_start} candles "
            f"({candles.iloc[replay_start]['timestamp'].date()} → {replay_date}) before recording"
        )
    else:
        replay_start = WARMUP
        _record_from_epoch[0] = 0.0  # record everything

    # Load real tick data only for the target date (warmup uses synthetic ticks)
    if args.date:
        first_candle_date = replay_date
    else:
        first_candle_date = candles.iloc[max(0, replay_start - WARMUP)]["timestamp"].date()
    last_candle_date = candles.iloc[-1]["timestamp"].date()
    tick_data = load_real_ticks(pair, first_candle_date, last_candle_date)
    has_real_ticks = tick_data is not None
    if has_real_ticks:
        _rt_ts = tick_data["ts_np"]       # numpy datetime64 array
        _rt_epochs = tick_data["epochs"]   # float64 epoch seconds
        _rt_bids = tick_data["bids"]       # float64 arrays
        _rt_asks = tick_data["asks"]
        _rt_mids = tick_data["mids"]
        logger.info(f"Real ticks available: {_rt_ts[0]} to {_rt_ts[-1]}")

    logger.info(f"Loaded {len(candles)} candles, replaying from index {replay_start}")

    from trade_executor import EPIC_STATE
    def _check_sl_tp(mid_price):
        """Simulate IG SL/TP at this price level."""
        for pk, st in list(EPIC_STATE.items()):
            if not st.get("active") or st.get("epic") != epic:
                continue
            d = st.get("direction", "")
            entry_p = st.get("entry_price", 0)
            sl_dist = st.get("sl", 20)
            tp_dist = st.get("tp", 30)
            if d == "BUY":
                if mid_price <= entry_p - sl_dist:
                    st["exit_price"] = entry_p - sl_dist
                    st["close_reason"] = "SL_HIT"
                    trade_executor.close_trade(pk)
                elif mid_price >= entry_p + tp_dist:
                    st["exit_price"] = entry_p + tp_dist
                    st["close_reason"] = "TP_HIT"
                    trade_executor.close_trade(pk)
            elif d == "SELL":
                if mid_price >= entry_p + sl_dist:
                    st["exit_price"] = entry_p + sl_dist
                    st["close_reason"] = "SL_HIT"
                    trade_executor.close_trade(pk)
                elif mid_price <= entry_p - tp_dist:
                    st["exit_price"] = entry_p - tp_dist
                    st["close_reason"] = "TP_HIT"
                    trade_executor.close_trade(pk)

    def _update_peak(st, mid_price, t_epoch):
        d = st.get("direction", "")
        peak = st.get("peak_fav_price")
        if peak is None:
            st["peak_fav_price"] = mid_price
            st["peak_fav_time"] = t_epoch
            return
        if d == "BUY" and mid_price > peak:
            st["peak_fav_price"] = mid_price
            st["peak_fav_time"] = t_epoch
        elif d == "SELL" and mid_price < peak:
            st["peak_fav_price"] = mid_price
            st["peak_fav_time"] = t_epoch

    def _feed_tick(bid, ask, mid_price, tick_ts):
        """Feed a single price tick through the live stack."""
        for pk, st in EPIC_STATE.items():
            if st.get("active"):
                st["last_mid"] = mid_price
                _update_peak(st, mid_price, tick_ts)
        bot._on_ls_tick(
            symbol=pair, epic=epic,
            bid=bid, ask=ask, mid=mid_price,
            ts=tick_ts, uts=str(pd.Timestamp(tick_ts, unit="s", tz="UTC")), umicro=0,
        )

    TICKS_PER_CANDLE = 20  # fallback synthetic ticks per candle

    def _interpolate(a, b, steps):
        """Generate `steps` prices from a to b inclusive."""
        if steps <= 1:
            return [b]
        return [a + (b - a) * k / (steps - 1) for k in range(steps)]

    real_tick_count = 0
    synth_tick_count = 0

    # Histdata ticks are raw forex (e.g. 1.3343), IG candles are scaled (e.g. 13343)
    # JPY pairs: IG price = rate × 100; all others: IG price = rate × 10000
    _jpy_pairs = {"USDJPY", "GBPJPY", "EURJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY"}
    tick_scale = 100 if pair.upper() in _jpy_pairs else 10000
    if has_real_ticks:
        sample_raw = _rt_mids[tick_data["count"] // 2]
        logger.info(f"Tick price scaling: {tick_scale}x (raw {sample_raw:.6f} → {sample_raw * tick_scale:.2f})")

    # ── FAST MODE ──────────────────────────────────────────────────────
    # Strategy evaluation: 1 tick per candle (at the close) for both
    # warmup and replay days.  SL/TP checking: real tick prices (no
    # strategy eval) for accurate fills.  ~1-2 min per day.
    # ────────────────────────────────────────────────────────────────────
    is_warmup = _record_from_epoch[0] > 0

    for i in range(replay_start, len(candles)):
        row = candles.iloc[i]
        ts = row["timestamp"]
        opn = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        ts_epoch = ts.timestamp()
        in_warmup = is_warmup and ts_epoch < _record_from_epoch[0]

        # Transition from warmup → recording: close stale warmup positions
        if is_warmup and not in_warmup and ts_epoch >= _record_from_epoch[0]:
            is_warmup = False
            for pk in list(EPIC_STATE):
                st = EPIC_STATE.get(pk)
                if st and st.get("active"):
                    st["exit_price"] = float(candles.iloc[i - 1]["close"]) if i > 0 else opn
                    st["close_reason"] = "WARMUP_EOD"
                    trade_executor.close_trade(pk)
            logger.info(f"=== Recording starts: {ts.strftime('%Y-%m-%d %H:%M')} ===")

        _replay_epoch[0] = ts_epoch
        _current_briefing[pair] = _get_briefing_at(ts)

        # Inject pre-enriched slice directly into candle_builder — no recompute
        window_start = max(0, i - 59)
        _slice = candles.iloc[window_start:i + 1]
        _slice_t = _slice.rename(columns={"timestamp": "time"})
        _sym = pair.upper()
        _bld = candle_builder._BUILDER
        _bld._df_ind[_sym] = _slice_t.reset_index(drop=True)
        _bld._df_raw[_sym] = _slice_t[["time", "open", "high", "low", "close"]].reset_index(drop=True)
        _bld.candles[_sym] = [
            {"time": r["time"].to_pydatetime() if hasattr(r["time"], "to_pydatetime") else r["time"],
             "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])}
            for _, r in _slice_t.iterrows()
        ]

        # SL/TP checking on real ticks (fast — no strategy eval)
        if not in_warmup and has_real_ticks:
            ts_dt64 = ts.to_datetime64()
            candle_end_dt64 = (ts + pd.Timedelta(minutes=5)).to_datetime64()
            i_lo = np.searchsorted(_rt_ts, ts_dt64, side="left")
            i_hi = np.searchsorted(_rt_ts, candle_end_dt64, side="left")
            n_ticks = i_hi - i_lo
            if n_ticks >= 3:
                # Subsample ~50 ticks max for SL/TP
                if n_ticks > 50:
                    step = n_ticks // 50
                    idx = np.arange(i_lo, i_hi, step)
                    if idx[-1] != i_hi - 1:
                        idx = np.append(idx, i_hi - 1)
                else:
                    idx = np.arange(i_lo, i_hi)
                for j in idx:
                    _replay_epoch[0] = _rt_epochs[j]
                    mid = _rt_mids[j] * tick_scale
                    for pk, st in EPIC_STATE.items():
                        if st.get("active"):
                            st["last_mid"] = mid
                            _update_peak(st, mid, _rt_epochs[j])
                    _check_sl_tp(mid)
                    real_tick_count += 1
        elif not in_warmup:
            # Fallback: check SL/TP on candle high/low
            _check_sl_tp(high)
            _check_sl_tp(low)

        # Strategy evaluation: single tick at candle close
        _replay_epoch[0] = ts_epoch + 299  # end of 5-min window
        _feed_tick(close - SPREAD/2, close + SPREAD/2, close, _replay_epoch[0])

    logger.info(f"Tick stats: {real_tick_count} real ticks for SL/TP")

    if os.environ.get("TRADE_LOG_OUT"):
        with open(os.environ["TRADE_LOG_OUT"], "w") as _f:
            json.dump(_trade_log, _f)

    # Summary
    if not _trade_log:
        print("\nNo trades recorded.")
        return

    by_mode = {}
    for t in _trade_log:
        by_mode.setdefault(t["mode"], []).append(t)

    print(f"\n{'=' * 120}")
    print(f"  TRUE REPLAY — {pair} — {len(_trade_log)} trades")
    print(f"{'=' * 120}")
    print(f"\n  {'Strategy':<25} {'N':>4} {'W':>3} {'L':>3} {'WR%':>6} {'Total':>8} {'Avg':>7}")
    print(f"  {'─'*25} {'─'*4} {'─'*3} {'─'*3} {'─'*6} {'─'*8} {'─'*7}")

    grand_pnl = grand_n = grand_w = 0
    for mode in sorted(by_mode):
        trades = by_mode[mode]
        n = len(trades)
        pnls = [t["pnl"] for t in trades]
        w = sum(1 for p in pnls if p > 0)
        l = sum(1 for p in pnls if p < 0)
        total = sum(pnls)
        grand_pnl += total; grand_n += n; grand_w += w
        print(f"  {mode:<25} {n:>4} {w:>3} {l:>3} {w/n*100:>5.1f}% {total:>+8.1f} {total/n:>+7.1f}")

    print(f"  {'─'*25} {'─'*4} {'─'*3} {'─'*3} {'─'*6} {'─'*8} {'─'*7}")
    print(f"  {'TOTAL':<25} {grand_n:>4} {grand_w:>3} {grand_n-grand_w:>3} "
          f"{grand_w/grand_n*100:>5.1f}% {grand_pnl:>+8.1f} {grand_pnl/grand_n:>+7.1f}")

    print(f"\n  {'#':<3} {'Open':>16} {'Close':>16} {'Mode':<22} {'Dir':>4} {'Entry':>9} {'Exit':>9} {'PnL':>7} {'MFE':>6} {'Peak':>12} {'HeldAfter':>10} {'Reason'}")
    print(f"  {'─'*3} {'─'*16} {'─'*16} {'─'*22} {'─'*4} {'─'*9} {'─'*9} {'─'*7} {'─'*6} {'─'*12} {'─'*10} {'─'*20}")
    for i, t in enumerate(_trade_log, 1):
        ot = pd.Timestamp(t["open_time"], unit="s", tz="UTC").strftime("%m-%d %H:%M") if t["open_time"] else "?"
        ct = pd.Timestamp(t["close_time"], unit="s", tz="UTC").strftime("%m-%d %H:%M") if t["close_time"] else "?"
        pt = pd.Timestamp(t["time_at_peak"], unit="s", tz="UTC").strftime("%m-%d %H:%M") if t.get("time_at_peak") else "?"
        mfe = t.get("mfe", 0.0)
        held = t.get("duration_at_peak_before_close", 0.0)
        print(f"  {i:<3} {ot:>16} {ct:>16} {t['mode']:<22} {t['direction']:>4} "
              f"{t['entry']:>9.2f} {t['exit']:>9.2f} {t['pnl']:>+7.1f} {mfe:>6.1f} {pt:>12} {held:>9.1f}m {t['reason']}")

    wtl = [t for t in _trade_log if t.get("mfe", 0.0) >= 10.0]
    print(f"\n  Trades with MFE >= 10p (won-then-lost candidates): {len(wtl)}")
    if wtl:
        print(f"  {'#':<3} {'Open':>16} {'Mode':<22} {'Dir':>4} {'MFE':>6} {'PnL':>7} {'HeldAfterPeak':>14}")
        for i, t in enumerate(wtl, 1):
            ot = pd.Timestamp(t["open_time"], unit="s", tz="UTC").strftime("%m-%d %H:%M") if t["open_time"] else "?"
            print(f"  {i:<3} {ot:>16} {t['mode']:<22} {t['direction']:>4} "
                  f"{t['mfe']:>6.1f} {t['pnl']:>+7.1f} {t['duration_at_peak_before_close']:>13.1f}m")
    print()

if __name__ == "__main__":
    main()
