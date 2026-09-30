#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_cache_from_ticks.py
Build /opt/tradingbot/cache/*_candles.csv from Lightstreamer ticks (NO REST).

It subscribes to the same TODAY epics, builds 5m candles via candle_builder,
and writes CSVs once each symbol reaches TARGET_BARS closed candles.

Usage:
  (venv) python /opt/tradingbot/build_cache_from_ticks.py

Env overrides (optional):
  CACHE_DIR=/opt/tradingbot/cache
  TARGET_BARS=50
  MIN_ROWS_TO_WRITE=20
"""

import os
import time
import json
import logging
from typing import Any, Dict

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("AutoBot")
if not logger.handlers:
    logging.basicConfig(
        level=(os.getenv("LOG_LEVEL", "INFO") or "INFO").strip().upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

CACHE_DIR = (os.getenv("CACHE_DIR", "/opt/tradingbot/cache") or "/opt/tradingbot/cache").strip()
TARGET_BARS = int(float(os.getenv("TARGET_BARS", "50") or 50))
MIN_ROWS_TO_WRITE = int(float(os.getenv("MIN_ROWS_TO_WRITE", "20") or 20))

EPIC_MAP_DEFAULT = {
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURGBP": "CS.D.EURGBP.TODAY.IP",
    "AUDUSD": "CS.D.AUDUSD.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}

def _load_epic_map() -> Dict[str, str]:
    j = (os.getenv("EPIC_MAP_JSON", "") or "").strip()
    if j:
        try:
            obj = json.loads(j)
            if isinstance(obj, dict) and obj:
                return {str(k).upper(): str(v) for k, v in obj.items() if k and v}
        except Exception:
            pass

    fpath = (os.getenv("EPIC_MAP_FILE", "") or "").strip()
    if fpath and os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict) and obj:
                return {str(k).upper(): str(v) for k, v in obj.items() if k and v}
        except Exception:
            pass

    return dict(EPIC_MAP_DEFAULT)

def _cache_path(sym: str) -> str:
    return os.path.join(CACHE_DIR, f"{sym.upper()}_candles.csv")

def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

# IMPORTANT: imports after dotenv
from streamer_ls import start_streaming  # noqa
import candle_builder  # noqa

DONE: Dict[str, bool] = {}
LAST_WRITE_TS: Dict[str, float] = {}

def _write_cache(sym: str) -> int:
    df = candle_builder.get_df(sym)
    if df is None or df.empty:
        return 0

    # Normalize schema for autobot preload reader: timestamp,open,high,low,close
    out = df.copy()
    if "time" in out.columns and "timestamp" not in out.columns:
        out = out.rename(columns={"time": "timestamp"})
    out["timestamp"] = out["timestamp"].astype("datetime64[ns, UTC]")
    out = out[["timestamp", "open", "high", "low", "close"]].dropna().reset_index(drop=True)

    if len(out) < MIN_ROWS_TO_WRITE:
        return int(len(out))

    if len(out) > TARGET_BARS:
        out = out.iloc[-TARGET_BARS:].reset_index(drop=True)

    path = _cache_path(sym)
    _ensure_dir(path)
    out.to_csv(path, index=False)

    # Make it readable by the service user; you can chown later if you want strict autobot ownership
    try:
        os.chmod(path, 0o664)
    except Exception:
        pass

    return int(len(out))

def _on_5m_close_payload(payload: Dict[str, Any]) -> None:
    try:
        sym = str(payload.get("symbol") or "").upper()
        if not sym or sym not in DONE:
            return

        # throttle writes a bit (avoid writing every candle close)
        now = time.time()
        last = float(LAST_WRITE_TS.get(sym, 0.0))
        if now - last < 2.0:
            return

        df = payload.get("candles_5m_closed_df")
        n = 0
        try:
            if df is not None:
                n = int(len(df))
        except Exception:
            n = 0

        if n >= MIN_ROWS_TO_WRITE:
            wrote = _write_cache(sym)
            LAST_WRITE_TS[sym] = now
            logger.info(f"[CACHE] {sym}: wrote {wrote} bars -> {_cache_path(sym)}")

            if wrote >= TARGET_BARS:
                DONE[sym] = True
                logger.info(f"[DONE] {sym} reached TARGET_BARS={TARGET_BARS}")

    except Exception as e:
        logger.error(f"_on_5m_close_payload error: {type(e).__name__}: {e}", exc_info=True)

def main() -> None:
    epics = _load_epic_map()
    os.makedirs(CACHE_DIR, exist_ok=True)

    # initialize DONE set for every symbol we care about
    for sym in epics.keys():
        DONE[sym.upper()] = False

    # Make sure payload includes epic
    for sym, epic in epics.items():
        try:
            candle_builder.set_epic_mapping(sym.upper(), epic)
        except Exception:
            pass

    candle_builder.register_5m_close_callback(_on_5m_close_payload)

    def _tick_adapter(symbol: str, epic: str, bid: Any, ask: Any, mid: Any, ts: float, uts: Any, umicro: Any) -> None:
        # Feed ticks into candle builder
        try:
            candle_builder.update_candles(symbol.upper(), bid, ask, update_time=uts, update_micro=umicro)
        except TypeError:
            candle_builder.update_candles(symbol.upper(), bid, ask, uts, umicro)

    logger.info(f"Starting LS streaming. CACHE_DIR={CACHE_DIR} TARGET_BARS={TARGET_BARS} MIN_ROWS_TO_WRITE={MIN_ROWS_TO_WRITE}")
    start_streaming(epics, _tick_adapter)

    # run until done
    while True:
        remaining = [s for s, ok in DONE.items() if not ok]
        if not remaining:
            logger.info("All symbols reached target bars. Exiting.")
            return
        logger.info(f"Waiting… remaining={remaining}")
        time.sleep(30)

if __name__ == "__main__":
    main()
