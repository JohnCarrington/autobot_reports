#!/usr/bin/env python3
"""
sentinel_api.py — Flask scoring API sidecar for Sentinel.

Scores incoming trade signals using historical outcome data from signal_log.jsonl.
Runs on port 5001. Rebuilds scoring model every 5 minutes from disk.

Scoring model:
  - Primary bucket: (strategy, direction, session) win rate
  - BB width modifier: win rate delta vs strategy baseline
  - ATR modifier: win rate delta vs strategy baseline
  - Final score = 0.70 * primary + 0.15 * bb_modifier + 0.15 * atr_modifier
  - All scores clamped to [0.0, 1.0]
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request

import briefing_outcome_tracker

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SIGNAL_LOG_PATH = Path(os.getenv(
    "SIGNAL_LOG_PATH", "/opt/tradingbot/data/signal_log.jsonl"
))
PORT = int(os.getenv("SENTINEL_API_PORT", "5001"))
RELOAD_INTERVAL_S = 300  # 5 minutes
MIN_SAMPLE_SIZE = 10

BB_BUCKETS = [(0, 20), (20, 30), (30, 45), (45, float("inf"))]
ATR_BUCKETS = [(0, 8), (8, 14), (14, 22), (22, float("inf"))]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sentinel_api] %(levelname)s %(message)s",
)
logger = logging.getLogger("sentinel_api")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Model state (protected by lock)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_model = {
    "primary": {},       # (strategy, direction, session) -> {wins, total}
    "bb_mod": {},        # (strategy, bb_bucket) -> {wins, total}
    "atr_mod": {},       # (strategy, atr_bucket) -> {wins, total}
    "baseline": {},      # strategy -> {wins, total}
    "loaded_at": None,
    "total_records": 0,
}


def _bb_bucket(val):
    """Return bucket label for a BB width value."""
    if val is None:
        return None
    v = float(val)
    for lo, hi in BB_BUCKETS:
        if lo <= v < hi:
            return f"{lo}-{hi}" if hi != float("inf") else f"{lo}+"
    return None


def _atr_bucket(val):
    """Return bucket label for an ATR value."""
    if val is None:
        return None
    v = float(val)
    for lo, hi in ATR_BUCKETS:
        if lo <= v < hi:
            return f"{lo}-{hi}" if hi != float("inf") else f"{lo}+"
    return None


def _is_win(record):
    """A trade is a win if pnl_pips > 0."""
    pnl = record.get("pnl_pips")
    if pnl is None:
        return None  # still open / no outcome
    return float(pnl) > 0


def _win_rate(bucket):
    """Compute win rate from a {wins, total} bucket. Returns None if empty."""
    if not bucket or bucket["total"] == 0:
        return None
    return bucket["wins"] / bucket["total"]


def _load_model():
    """Read signal_log.jsonl and rebuild all scoring buckets."""
    primary = defaultdict(lambda: {"wins": 0, "total": 0})
    bb_mod = defaultdict(lambda: {"wins": 0, "total": 0})
    atr_mod = defaultdict(lambda: {"wins": 0, "total": 0})
    baseline = defaultdict(lambda: {"wins": 0, "total": 0})
    total = 0

    if not SIGNAL_LOG_PATH.exists():
        logger.warning("signal_log not found at %s", SIGNAL_LOG_PATH)
        return

    with open(SIGNAL_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue

            win = _is_win(r)
            if win is None:
                continue  # skip trades without outcomes

            total += 1
            strat = r.get("strategy", "UNKNOWN")
            direction = r.get("direction", "UNKNOWN")
            session = r.get("session", "UNKNOWN")
            w = 1 if win else 0

            # Primary bucket
            key = (strat, direction, session)
            primary[key]["wins"] += w
            primary[key]["total"] += 1

            # Baseline per strategy
            baseline[strat]["wins"] += w
            baseline[strat]["total"] += 1

            # BB width modifier
            bb = _bb_bucket(r.get("bb_width_pips"))
            if bb is not None:
                bb_mod[(strat, bb)]["wins"] += w
                bb_mod[(strat, bb)]["total"] += 1

            # ATR modifier
            atr = _atr_bucket(r.get("atr_pips"))
            if atr is not None:
                atr_mod[(strat, atr)]["wins"] += w
                atr_mod[(strat, atr)]["total"] += 1

    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        _model["primary"] = dict(primary)
        _model["bb_mod"] = dict(bb_mod)
        _model["atr_mod"] = dict(atr_mod)
        _model["baseline"] = dict(baseline)
        _model["loaded_at"] = now
        _model["total_records"] = total

    logger.info("Model loaded: %d records, %d primary buckets", total, len(primary))


def _reload_loop():
    """Background thread: reload model every RELOAD_INTERVAL_S seconds."""
    while True:
        try:
            _load_model()
        except Exception as e:
            logger.error("Model reload error: %s", e)
        time.sleep(RELOAD_INTERVAL_S)


def _score_signal(strategy, direction, session, bb_width_pips, atr_pips):
    """
    Score a signal. Returns dict with score, sample_size, low_confidence, breakdown.
    Never raises — returns safe defaults on error.
    """
    try:
        with _lock:
            primary = _model["primary"]
            bb_mod = _model["bb_mod"]
            atr_mod = _model["atr_mod"]
            base = _model["baseline"]

        # Primary win rate
        pkey = (strategy, direction, session)
        p_bucket = primary.get(pkey, {"wins": 0, "total": 0})
        p_wr = _win_rate(p_bucket)
        sample = p_bucket["total"]

        if sample < MIN_SAMPLE_SIZE:
            return {
                "score": 1.0,
                "sample_size": sample,
                "low_confidence": True,
                "breakdown": {
                    "primary_key": list(pkey),
                    "primary_wr": p_wr,
                    "primary_n": sample,
                    "reason": f"below MIN_SAMPLE_SIZE ({MIN_SAMPLE_SIZE})",
                },
            }

        # Baseline win rate for this strategy
        base_bucket = base.get(strategy, {"wins": 0, "total": 0})
        base_wr = _win_rate(base_bucket)
        if base_wr is None:
            base_wr = p_wr  # fallback

        # BB width modifier (delta from baseline)
        bb_delta = 0.0
        bb_label = _bb_bucket(bb_width_pips)
        bb_wr = None
        bb_n = 0
        if bb_label is not None:
            bb_bucket_data = bb_mod.get((strategy, bb_label))
            if bb_bucket_data and bb_bucket_data["total"] >= 3:
                bb_wr = _win_rate(bb_bucket_data)
                bb_n = bb_bucket_data["total"]
                bb_delta = bb_wr - base_wr

        # ATR modifier (delta from baseline)
        atr_delta = 0.0
        atr_label = _atr_bucket(atr_pips)
        atr_wr = None
        atr_n = 0
        if atr_label is not None:
            atr_bucket_data = atr_mod.get((strategy, atr_label))
            if atr_bucket_data and atr_bucket_data["total"] >= 3:
                atr_wr = _win_rate(atr_bucket_data)
                atr_n = atr_bucket_data["total"]
                atr_delta = atr_wr - base_wr

        # Weighted combination
        score = 0.70 * p_wr + 0.15 * (p_wr + bb_delta) + 0.15 * (p_wr + atr_delta)
        score = max(0.0, min(1.0, score))

        return {
            "score": round(score, 4),
            "sample_size": sample,
            "low_confidence": False,
            "breakdown": {
                "primary_key": list(pkey),
                "primary_wr": round(p_wr, 4),
                "primary_n": sample,
                "baseline_wr": round(base_wr, 4) if base_wr else None,
                "bb_bucket": bb_label,
                "bb_wr": round(bb_wr, 4) if bb_wr is not None else None,
                "bb_n": bb_n,
                "bb_delta": round(bb_delta, 4),
                "atr_bucket": atr_label,
                "atr_wr": round(atr_wr, 4) if atr_wr is not None else None,
                "atr_n": atr_n,
                "atr_delta": round(atr_delta, 4),
            },
        }
    except Exception as e:
        logger.error("Scoring error: %s", e)
        return {
            "score": 1.0,
            "sample_size": 0,
            "low_confidence": True,
            "breakdown": {"error": str(e)},
        }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    with _lock:
        return jsonify({
            "status": "ok",
            "model_loaded_at": _model["loaded_at"],
            "total_records": _model["total_records"],
        })


@app.route("/score", methods=["POST"])
def score():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    strategy = data.get("strategy", "UNKNOWN")
    direction = data.get("direction", "UNKNOWN")
    session = data.get("session", "UNKNOWN")
    bb_width_pips = data.get("bb_width_pips")
    atr_pips = data.get("atr_pips")

    result = _score_signal(strategy, direction, session, bb_width_pips, atr_pips)

    with _lock:
        result["model_loaded_at"] = _model["loaded_at"]
        result["total_records"] = _model["total_records"]

    return jsonify(result)


@app.route("/outcome", methods=["POST"])
def outcome():
    """Ingest a completed trade and append to signal_log.jsonl."""
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    # Validate required fields
    missing = [f for f in ("strategy", "direction", "session", "pnl_pips") if f not in data]
    if missing:
        return jsonify({"error": f"missing fields: {missing}"}), 400

    # Append to signal_log
    try:
        with open(SIGNAL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
    except Exception as e:
        logger.error("Failed to append outcome: %s", e)
        return jsonify({"error": "write failed"}), 500

    # Trigger immediate model rebuild in background
    threading.Thread(target=_load_model, daemon=True).start()

    with _lock:
        total = _model["total_records"]

    return jsonify({"status": "ok", "total_records": total + 1})


@app.route("/stats", methods=["GET"])
def stats():
    with _lock:
        # Serialize tuple keys to strings for JSON
        primary = {
            f"{k[0]}|{k[1]}|{k[2]}": v
            for k, v in _model["primary"].items()
        }
        bb = {
            f"{k[0]}|{k[1]}": v
            for k, v in _model["bb_mod"].items()
        }
        atr = {
            f"{k[0]}|{k[1]}": v
            for k, v in _model["atr_mod"].items()
        }
        baseline = dict(_model["baseline"])

        # Add win rates
        for d in (primary, bb, atr, baseline):
            for k, v in d.items():
                v["wr"] = round(v["wins"] / v["total"], 4) if v["total"] > 0 else None

        return jsonify({
            "model_loaded_at": _model["loaded_at"],
            "total_records": _model["total_records"],
            "min_sample_size": MIN_SAMPLE_SIZE,
            "primary_buckets": primary,
            "bb_modifier_buckets": bb,
            "atr_modifier_buckets": atr,
            "baseline_per_strategy": baseline,
        })


# ---------------------------------------------------------------------------
# Briefing outcome evaluation loop
# ---------------------------------------------------------------------------
OUTCOME_EVAL_INTERVAL_S = 300  # evaluate completed sessions every 5 minutes
BRIEFINGS_DIR = Path(os.getenv(
    "BRIEFINGS_DIR", "/opt/tradingbot/data/briefings_live"
))


def _outcome_eval_loop():
    """Background thread: evaluate completed briefing sessions periodically."""
    # One-time backfill on startup
    try:
        n = briefing_outcome_tracker.backfill_from_briefings(BRIEFINGS_DIR)
        if n:
            logger.info("Briefing outcome backfill: %d outcomes written", n)
    except Exception as e:
        logger.error("Briefing outcome backfill error: %s", e)

    while True:
        try:
            written = briefing_outcome_tracker.evaluate_completed_sessions()
            if written:
                logger.info("Briefing outcome eval: %d new outcomes", written)
        except Exception as e:
            logger.error("Briefing outcome eval error: %s", e)
        time.sleep(OUTCOME_EVAL_INTERVAL_S)


@app.route("/briefing-accuracy", methods=["GET"])
def briefing_accuracy():
    """Return briefing prediction accuracy stats by session, pair, confidence, day of week."""
    try:
        stats = briefing_outcome_tracker.compute_accuracy_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error("briefing-accuracy error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/feature-stats", methods=["GET"])
def feature_stats():
    """Run feature pipeline on current corpus and return diagnostics."""
    try:
        import sentinel_features

        X, y = sentinel_features.build_feature_matrix()
        names = sentinel_features.get_feature_names()

        if X.shape[0] == 0:
            return jsonify({"error": "no records available", "feature_count": 0, "record_count": 0})

        # Feature importance proxy: variance of each feature
        variances = X.var(axis=0).tolist()
        importance = {n: round(v, 6) for n, v in zip(names, variances)}

        # Correlation matrix highlights: pairs with |corr| > 0.7 (excluding self)
        corr = np.corrcoef(X, rowvar=False)
        highlights = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                c = corr[i, j]
                if abs(c) > 0.7 and not (np.isnan(c)):
                    highlights.append({
                        "feature_a": names[i],
                        "feature_b": names[j],
                        "correlation": round(float(c), 4),
                    })
        highlights.sort(key=lambda h: abs(h["correlation"]), reverse=True)

        # Label stats
        label_names = ["bias_correct", "tp1_hit", "tp2_hit"]
        label_rates = {n: round(float(y[:, i].mean()), 4) for i, n in enumerate(label_names)}

        return jsonify({
            "feature_count": len(names),
            "record_count": int(X.shape[0]),
            "feature_names": names,
            "feature_importance_variance": importance,
            "high_correlation_pairs": highlights[:20],
            "label_distribution": label_rates,
            "x_shape": list(X.shape),
            "y_shape": list(y.shape),
        })
    except Exception as e:
        logger.error("feature-stats error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/training-data", methods=["GET"])
def training_data():
    """Return briefing training corpus statistics."""
    try:
        import briefing_training_collector
        stats = briefing_training_collector.get_corpus_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error("training-data error: %s", e)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def main():
    _load_model()
    t = threading.Thread(target=_reload_loop, daemon=True)
    t.start()
    t2 = threading.Thread(target=_outcome_eval_loop, daemon=True)
    t2.start()
    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
