"""
briefing_training_collector.py — Captures input features + briefing output for ML training.

On each briefing generation, stores:
  1) Full input feature vector (candles, indicators, structure)
  2) Full briefing output (Anthropic API JSON response)
  3) Metadata (timestamp, pair, session, model, prompt version hash)

Storage:
  - Individual: /opt/tradingbot/data/briefing_training/{pair}_{date}_{session}.json
  - Corpus:     /opt/tradingbot/data/briefing_training_corpus.jsonl
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AutoBot")

_TRAINING_DIR = Path("/opt/tradingbot/data/briefing_training")
_CORPUS_FILE = Path("/opt/tradingbot/data/briefing_training_corpus.jsonl")


def _prompt_version_hash(schema: dict, system_prompt: str) -> str:
    """Short hash of the prompt schema + system prompt for version tracking."""
    raw = json.dumps(schema, sort_keys=True) + system_prompt
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def store_training_record(
    data_package: Dict[str, Any],
    briefing: Dict[str, Any],
    model: str = "",
    prompt_hash: str = "",
) -> Optional[str]:
    """Store a training record (input features + output briefing + metadata).

    Returns the file path on success, None on failure.
    """
    try:
        sym = str(data_package.get("symbol", "UNKNOWN")).upper()
        session = str(data_package.get("session", "unknown"))
        date_str = str(data_package.get("briefing_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")))

        record = {
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "epoch": time.time(),
                "symbol": sym,
                "session": session,
                "date": date_str,
                "model": model,
                "prompt_version_hash": prompt_hash,
                "partial": False,
            },
            "input_features": _extract_features(data_package),
            "briefing_output": briefing,
        }

        # Individual file
        _TRAINING_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{sym}_{date_str}_{session}.json"
        filepath = _TRAINING_DIR / filename
        with open(filepath, "w") as f:
            json.dump(record, f, indent=2, default=str)

        # Append to corpus JSONL
        with open(_CORPUS_FILE, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

        logger.info(
            "[training_collector] Stored %s/%s/%s (%s)",
            sym, date_str, session, filepath.name,
        )
        return str(filepath)

    except Exception as e:
        logger.warning("[training_collector] Failed to store record: %s", e)
        return None


def _extract_features(pkg: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the full input feature vector from the data package."""
    return {
        # Core
        "symbol": pkg.get("symbol"),
        "session": pkg.get("session"),
        "current_price": pkg.get("current_price"),
        "briefing_date": pkg.get("briefing_date"),
        "briefing_time_utc": pkg.get("briefing_time_utc"),

        # Multi-timeframe candles
        "d1_candles": pkg.get("d1_candles"),
        "h4_candles": pkg.get("h4_candles"),
        "h1_candles": pkg.get("h1_candles"),

        # 5M indicators
        "ema_5m": pkg.get("ema_5m"),
        "rsi_5m": pkg.get("rsi_5m"),

        # H1 indicators
        "ema_h1": pkg.get("ema_h1"),
        "h1_ema_values": pkg.get("h1_ema_values"),
        "macd_h1_hist": pkg.get("macd_h1_hist"),
        "h1_momentum_summary": pkg.get("h1_momentum_summary"),
        "ema_alignment": pkg.get("ema_alignment"),

        # Bollinger Bands
        "bb_upper": pkg.get("bb_upper"),
        "bb_lower": pkg.get("bb_lower"),

        # Daily structure
        "prev_day_high": pkg.get("prev_day_high"),
        "prev_day_low": pkg.get("prev_day_low"),
        "prev_day_close": pkg.get("prev_day_close"),
        "week_high": pkg.get("week_high"),
        "week_low": pkg.get("week_low"),
        "prev_week_high": pkg.get("prev_week_high"),
        "prev_week_low": pkg.get("prev_week_low"),

        # Price vs EMA context
        "price_vs_h1_ema200_pips": pkg.get("price_vs_h1_ema200_pips"),
        "price_vs_h1_ema50_pips": pkg.get("price_vs_h1_ema50_pips"),
        "h1_ema_trend": pkg.get("h1_ema_trend"),

        # Volatility
        "atr_today_pips": pkg.get("atr_today_pips"),
        "atr_20day_avg_pips": pkg.get("atr_20day_avg_pips"),
        "volatility_regime": pkg.get("volatility_regime"),

        # HTF bias
        "htf_bias": pkg.get("htf_bias"),

        # Previous session
        "prev_session_bias": pkg.get("prev_session_bias"),
        "prev_session_actual_direction": pkg.get("prev_session_actual_direction"),
        "prev_session_pip_move": pkg.get("prev_session_pip_move"),

        # News events
        "news_events": pkg.get("news_events"),

        # USD proxy
        "usd_proxy_bias": pkg.get("usd_proxy_bias"),
        "usd_proxy_pips": pkg.get("usd_proxy_pips"),

        # Recent accuracy
        "accuracy_last_5": pkg.get("accuracy_last_5"),
    }


def get_corpus_stats() -> Dict[str, Any]:
    """Compute corpus statistics for the /training-data endpoint."""
    try:
        if not _CORPUS_FILE.exists():
            return {"total_records": 0, "date_range": None, "pairs": [], "sessions": {}}

        total = 0
        dates: List[str] = []
        pairs: set = set()
        session_confs: Dict[str, List[float]] = {}

        with open(_CORPUS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    meta = rec.get("metadata", {})
                    total += 1
                    if meta.get("date"):
                        dates.append(meta["date"])
                    if meta.get("symbol"):
                        pairs.add(meta["symbol"])
                    session = meta.get("session", "")
                    conf = rec.get("briefing_output", {}).get("bias_confidence")
                    if session and conf is not None:
                        session_confs.setdefault(session, []).append(float(conf))
                except (json.JSONDecodeError, TypeError):
                    continue

        avg_conf_by_session = {}
        for s, confs in session_confs.items():
            avg_conf_by_session[s] = round(sum(confs) / len(confs), 3) if confs else None

        return {
            "total_records": total,
            "date_range": {
                "earliest": min(dates) if dates else None,
                "latest": max(dates) if dates else None,
            },
            "pairs": sorted(pairs),
            "sessions": avg_conf_by_session,
            "corpus_file": str(_CORPUS_FILE),
            "individual_dir": str(_TRAINING_DIR),
            "individual_files": len(list(_TRAINING_DIR.glob("*.json"))) if _TRAINING_DIR.exists() else 0,
        }
    except Exception as e:
        logger.warning("[training_collector] Stats computation failed: %s", e)
        return {"error": str(e)}
