#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SENTINEL — MAXIMAL EDITION
--------------------------
Unified Neural Trading AI:
 • Candle Builder (1m/5m/1h)
 • Lightstreamer ingestion
 • AiBrain (Transformer + NMC + MetaLearning)
 • Causal Transformer
 • Meta-Genome Controller
 • Experience Replay
 • Regime detection + forecasting
 • PatternEngine Fallback + Router
 • A/B Evaluation
 • Rollback Safety
 • Deployment Safety
 • IG Trading
"""

# ===========================================================
# 0. LOAD .ENV FIRST
# ===========================================================
import os, sys, json, time, logging
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path("/opt/tradingbot")
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR/".env")
    load_dotenv()
except: pass

# ===========================================================
# 1. STANDARD IMPORTS
# ===========================================================
import pandas as pd

# ===========================================================
# 2. CORE PROJECT IMPORTS
# ===========================================================
from ig_auth import get_ig_session
from trade_manager import TradeManager
from candle_builder import get_candles, preload_from_df, register_5m_close_callback, set_symbol_epic, get_builder as get_candle_builder
import candle_archive  # side-effect: registers daily OHLCV archive callback
from streamer_ls import start_streaming
from timeframe_context import TimeframeContext
import news_calendar
import morning_briefing

# ===========================================================
# 3. AI SYSTEM IMPORTS
# ===========================================================
from ai_brain import ai_brain_decide, ai_brain_feedback   # module-level functions
from orchestrator import on_tick as orchestrator_on_tick, run_safety_checks, veto_analytics

# Optional — meta_genome_controller uses per-regime PE files not yet present
try:
    META_GENOME_ENABLED = True
except ImportError:
    META_GENOME_ENABLED = False

# ===========================================================
# 4. FALLBACK / SAFETY MODULES
# ===========================================================
from regime_detector import detect_regime
from regime_forecaster import forecast_regime
from ab_engine import evaluate as evaluate_ab

# Optional Telegram alerts — graceful no-op if module absent
try:
    from telegram_alerts import send_trade_open_alert, send_trade_close_alert
except ImportError:
    def send_trade_open_alert(*a, **kw): pass
    def send_trade_close_alert(*a, **kw): pass

# ===========================================================
# LOGGING
# ===========================================================
logger = logging.getLogger("Sentinel")

def _configure_logging():
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        fh = logging.FileHandler(BASE_DIR/"sentinel.log")
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

# ===========================================================
# MARKET CONFIG
# ===========================================================
ACTIVE = {
    "EURUSD": {
        "trade_epic": os.getenv("EURUSD_TRADE_EPIC","CS.D.EURUSD.TODAY.IP"),
        "stream_epic": os.getenv("EURUSD_STREAM_EPIC","CS.D.EURUSD.TODAY.IP"),
    },
    "GBPUSD": {
        "trade_epic": os.getenv("GBPUSD_TRADE_EPIC","CS.D.GBPUSD.TODAY.IP"),
        "stream_epic": os.getenv("GBPUSD_STREAM_EPIC","CS.D.GBPUSD.TODAY.IP"),
    },
    "USDJPY": {
        "trade_epic": os.getenv("USDJPY_TRADE_EPIC","CS.D.USDJPY.TODAY.IP"),
        "stream_epic": os.getenv("USDJPY_STREAM_EPIC","CS.D.USDJPY.TODAY.IP"),
    },
    "USDCAD": {
        "trade_epic": os.getenv("USDCAD_TRADE_EPIC","CS.D.USDCAD.TODAY.IP"),
        "stream_epic": os.getenv("USDCAD_STREAM_EPIC","CS.D.USDCAD.TODAY.IP"),
    },
}

REQUIRED_5M = int(os.getenv("REQUIRED_CANDLES","20"))
REQUIRED_1H = 10
OPEN_COOLDOWN = int(os.getenv("OPEN_COOLDOWN_SECONDS","30"))
TICK_LOG_MS  = int(os.getenv("TICK_LOG_EVERY_MS","500"))

# REGIME HISTORY FILE
REGIME_HISTORY = BASE_DIR / "regime_history.json"

# ===========================================================
# REGISTRIES
# ===========================================================
MANAGERS = {}
EPICS = {}

LAST_MID = {}
LAST_LOG = {}
LAST_OPEN = {}

# Regime history — buffered in memory, flushed to disk every 60s
_REGIME_BUFFER = []
_REGIME_LAST_FLUSH = 0.0

# ===========================================================
# HTF SNAPSHOT (TimeframeContext — required by evaluate_signals)
# ===========================================================
_TF_CTX: TimeframeContext = TimeframeContext()
_HTF_SNAPSHOT: dict = {}   # keyed by symbol (upper)

def _on_5m_close(payload: dict) -> None:
    """Update the per-symbol HTF snapshot on every 5m candle close."""
    try:
        sym  = str(payload.get("symbol") or "").upper()
        epic = str(payload.get("epic") or "")
        if sym and epic:
            _HTF_SNAPSHOT[sym] = _TF_CTX.on_5m_close(sym, epic, payload)
            logger.info(f"[HTF] snapshot updated for {sym} @ {payload.get('candle_ts_utc')}")
            morning_briefing.update_htf_snapshot(sym, _HTF_SNAPSHOT[sym])
    except Exception as e:
        logger.warning(f"[HTF] on_5m_close error: {e}", exc_info=True)

register_5m_close_callback(_on_5m_close)

# Briefing invalidation check on every 5M close (all strategies)
try:
    from trade_manager import check_briefing_invalidation
    register_5m_close_callback(check_briefing_invalidation)
    logger.info("[SENTINEL] Registered briefing invalidation 5M callback")
except ImportError as e:
    logger.warning("[SENTINEL] Could not register invalidation callback: %s", e)

# ===========================================================
# AI MODULES
# ai_brain_decide() and ai_brain_feedback() are called directly
# as module-level functions — no class instantiation needed.
# push_experience() / sample_batch() replace ExperienceBuffer class.
# update_meta_learning() / load_ml_state() replace MetaLearningController class.
# ===========================================================

# ===========================================================
# HELPERS
# ===========================================================
def _should_log(sym, now, tup):
    last = LAST_LOG.get(sym)
    if not last: return True
    return (now - last).total_seconds()*1000 >= TICK_LOG_MS

_PIP_SIZE = {"USDJPY": 1.0, "GBPJPY": 1.0}
_PIP_SIZE_DEFAULT = 0.0001


def _pip_size(symbol: str) -> float:
    return _PIP_SIZE.get(str(symbol).upper(), _PIP_SIZE_DEFAULT)


def _pips(a, b, symbol: str = ""):
    if a is None or b is None: return 30
    return abs(a - b) / _pip_size(symbol)

# ===========================================================
# INIT MARKET
# ===========================================================
def _init_market(symbol,cfg):
    logger.info(f"[{symbol}] init…")
    epic = cfg["trade_epic"]
    EPICS[symbol] = epic
    set_symbol_epic(symbol, epic)
    if epic not in MANAGERS:
        MANAGERS[epic] = TradeManager()

    # Warm up candle builder from on-disk cache so get_candles() is never
    # empty after a restart, even when the market is currently closed.
    cache_dir = Path(os.getenv("CACHE_DIR", str(BASE_DIR / "cache")))
    cache_path = cache_dir / f"{symbol.upper()}_candles.csv"
    if cache_path.exists():
        try:
            n = preload_from_df(symbol, pd.read_csv(str(cache_path)))
            logger.info(f"[{symbol}] Warmed up {n} candles from cache ({cache_path.name})")
        except Exception as e:
            logger.warning(f"[{symbol}] Cache warm-up failed: {e}")

# ===========================================================
# TICK HANDLER
# ===========================================================
def _on_tick(symbol, epic, bid, ask, mid, ts, uts=None, umicro=0):
    now = datetime.now(timezone.utc)
    tup = (bid, ask, mid)
    if _should_log(symbol, now, tup):
        logger.info(f"[TICK {symbol}] bid={bid} ask={ask} mid={mid}")
        LAST_LOG[symbol] = now

    # 5m candles arrive via the native_5m_source subscription (see main()).
    # _on_tick no longer aggregates ticks into bars — the 2026-04-23 native-5m
    # migration removed candle_builder.update_candles(); callers reach a stub
    # raising NotImplementedError. Sentinel reads the rolling buffer below
    # and lets the native subscription keep it fresh.
    df1  = None
    df5  = get_candles(symbol)
    df1h = None

    if df5 is None or len(df5) < REQUIRED_5M:  return

    # Ignore duplicate prices
    prev = LAST_MID.get(symbol)
    LAST_MID[symbol] = mid
    if prev and abs(mid - prev) < 1e-6:
        return

    epic = EPICS[symbol]

    # ── Regime history buffer (flushed every 60s) ─────────────────
    global _REGIME_BUFFER, _REGIME_LAST_FLUSH
    try:
        current_regime = detect_regime(df5.tail(100))
        future_regime  = forecast_regime(df5)
        _REGIME_BUFFER.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol":    symbol,
            "regime":    current_regime,
            "forecast":  future_regime,
        })
        now_ts = time.time()
        if now_ts - _REGIME_LAST_FLUSH >= 60:
            _REGIME_LAST_FLUSH = now_ts
            try:
                data = json.loads(REGIME_HISTORY.read_text()) if REGIME_HISTORY.exists() else {"history": []}
                data["history"].extend(_REGIME_BUFFER)
                data["history"] = data["history"][-500:]
                REGIME_HISTORY.write_text(json.dumps(data))
                _REGIME_BUFFER.clear()
            except Exception:
                pass
    except Exception:
        pass

    # ── Delegate entirely to orchestrator ─────────────────────────
    # The orchestrator runs AutoBot + Sentinel, applies all gates,
    # executes the trade, and manages TradeManager state.
    try:
        orchestrator_on_tick(
            symbol=symbol,
            df1=df1,
            df5=df5,
            df1h=df1h,
            mid=mid,
            epic=epic,
            bid=bid,
            ask=ask,
            htf_snapshot=_HTF_SNAPSHOT.get(symbol.upper()),
        )
    except Exception as e:
        logger.error(f"[{symbol}] orchestrator error: {e}", exc_info=True)

# ===========================================================
# MAIN
# ===========================================================
def main():
    _configure_logging()
    logger.info("=== SENTINEL LIVE ===")

    ig,headers,account = get_ig_session()

    for sym,cfg in ACTIVE.items():
        _init_market(sym,cfg)

    # HTF preload — replay cached 5M candles into TimeframeContext
    _htf_cache_dir = Path(os.getenv("CACHE_DIR", str(BASE_DIR / "cache")))
    for _htf_sym, _htf_cfg in ACTIVE.items():
        try:
            _htf_epic = _htf_cfg["trade_epic"]
            _htf_path = _htf_cache_dir / f"{_htf_sym.upper()}_candles.csv"
            _deep_path = _htf_cache_dir / f"{_htf_sym.upper()}_candles_deep.csv"

            # Prefer deep cache for fuller HTF history
            _htf_df = None
            _htf_src = "standard"
            if _deep_path.exists():
                try:
                    _htf_df = pd.read_csv(str(_deep_path))
                    if _htf_df is not None and len(_htf_df) > 0:
                        _htf_src = f"deep({len(_htf_df)} bars)"
                    else:
                        _htf_df = None
                except Exception:
                    _htf_df = None
            if _htf_df is None and _htf_path.exists():
                try:
                    _htf_df = pd.read_csv(str(_htf_path))
                    if _htf_df is not None and len(_htf_df) > 0:
                        _htf_src = f"standard({len(_htf_df)} bars)"
                    else:
                        _htf_df = None
                except Exception:
                    _htf_df = None
            if _htf_df is None or len(_htf_df) == 0:
                logger.info(f"[HTF-PRELOAD] {_htf_sym}: no cache file — HTF context starts empty")
                continue

            _htf_summary = _TF_CTX.preload_from_5m_cache(_htf_sym, _htf_epic, _htf_df)

            _ts_col = "timestamp" if "timestamp" in _htf_df.columns else "time"
            _last_row = _htf_df.iloc[-1]
            _last_ts = pd.Timestamp(str(_last_row[_ts_col]))
            if _last_ts.tzinfo is None:
                _last_ts = _last_ts.tz_localize("UTC")
            _HTF_SNAPSHOT[_htf_sym.upper()] = _TF_CTX.on_5m_close(
                _htf_sym.upper(), _htf_epic,
                {
                    "timeframe": "5m",
                    "symbol": _htf_sym.upper(),
                    "epic": _htf_epic,
                    "candle": {
                        "timestamp": _last_ts,
                        "open": float(_last_row["open"]),
                        "high": float(_last_row["high"]),
                        "low": float(_last_row["low"]),
                        "close": float(_last_row["close"]),
                    },
                    "bucket_epoch": int(_last_ts.timestamp()) // 300 * 300,
                },
            )
            logger.info(
                f"[HTF-PRELOAD] {_htf_sym}: H1={_htf_summary['h1_candles']} H4={_htf_summary['h4_candles']} "
                f"D1={_htf_summary['d1_candles']} | bias: h1={_htf_summary.get('h1_bias','?')} "
                f"h4={_htf_summary.get('h4_bias','?')} d1={_htf_summary.get('d1_bias','?')} | src={_htf_src}"
            )
        except Exception as _htf_e:
            logger.warning(f"[HTF-PRELOAD] {_htf_sym}: failed: {type(_htf_e).__name__}: {_htf_e}")

    # D1 cache preload — load pre-built D1 candles directly
    for _htf_sym, _htf_cfg in ACTIVE.items():
        _htf_epic = _htf_cfg["trade_epic"]
        _d1_path = _htf_cache_dir / f"{_htf_sym.upper()}_candles_d1.csv"
        if _d1_path.exists():
            try:
                _d1_df = pd.read_csv(str(_d1_path))
                if _d1_df is not None and len(_d1_df) > 0:
                    _d1_summary = _TF_CTX.preload_from_d1_cache(_htf_sym, _htf_epic, _d1_df)
                    logger.info(
                        f"[HTF-PRELOAD] {_htf_sym}: D1={_d1_summary['d1_candles']} candles from d1 cache "
                        f"| bias={_d1_summary['d1_bias']}"
                    )
            except Exception as _d1_e:
                logger.warning(f"[HTF-PRELOAD] {_htf_sym}: D1 cache load failed: {_d1_e}")

    news_calendar.prefetch()
    morning_briefing.start(tf_ctx=_TF_CTX, builder=get_candle_builder())

    epics={sym:cfg["stream_epic"] for sym,cfg in ACTIVE.items()}
    controller = start_streaming(epics, _on_tick)

    # Native 5m candle subscription. Mirrors autobot.py's wiring exactly so
    # both droplets read closed bars from the same IG CHART:{epic}:5MINUTE
    # feed instead of aggregating from L1 ticks (the old path was removed
    # by branch migrate/native-5m-candle-feed, 2026-04-23). Reuses the LS
    # client returned by start_streaming.
    try:
        import native_5m_source
        _seed_counts = native_5m_source.seed_builder_from_cache(epics)
        logger.info(f"[native-5m] cold-start seed counts: {_seed_counts}")
    except Exception as _seed_exc:
        logger.warning(f"[native-5m] cache seed failed: {_seed_exc}", exc_info=True)
    try:
        _native_sub, _native_listener = native_5m_source.subscribe_native_5m(
            controller.client, epics
        )
        controller.add_subscription(_native_sub)
        logger.info("✔ Native 5m subscription active (CHART:{epic}:5MINUTE).")
    except Exception as _sub_exc:
        # Hard-fail: without the native subscription Sentinel has no source of
        # closed bars. _on_5m_close handlers (HTF snapshot, briefing
        # invalidation) silently never fire — same broken state we're porting
        # away from. Crash early.
        logger.error(f"[native-5m] subscription FAILED: {_sub_exc}", exc_info=True)
        raise

    _SAFETY_LAST  = 0.0
    _AB_LAST      = 0.0
    _VETO_LAST    = 0.0

    while True:
        time.sleep(5)
        now_ts = time.time()

        # Safety checks + genome rollback (every 60s)
        if now_ts - _SAFETY_LAST >= 60:
            _SAFETY_LAST = now_ts
            run_safety_checks()

        # A/B evaluation (every 5 minutes)
        if now_ts - _AB_LAST >= 300:
            _AB_LAST = now_ts
            ok, msg = evaluate_ab()
            logger.info(f"[A/B] {msg}")

        # Veto analytics summary (every 30 minutes)
        if now_ts - _VETO_LAST >= 1800:
            _VETO_LAST = now_ts
            stats = veto_analytics(last_n=500)
            logger.info(
                f"[Veto Analytics] trades={stats.get('trades')} "
                f"vetoes={stats.get('vetoes')} "
                f"veto_rate={stats.get('veto_rate')} "
                f"avg_conf_traded={stats.get('avg_confidence_traded')} "
                f"avg_conf_vetoed={stats.get('avg_confidence_vetoed')} "
                f"threshold={stats.get('current_threshold')}"
            )

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt:
        logger.info("Sentinel stopped.")
    except Exception as e:
        logger.error(f"Fatal: {e}",exc_info=True)
        raise
