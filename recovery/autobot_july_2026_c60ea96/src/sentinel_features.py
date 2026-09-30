"""
sentinel_features.py — Feature engineering pipeline for briefing ML training.

Takes raw training records from briefing_training_corpus.jsonl (or falls back to
briefing_outcomes.jsonl) and produces a normalised 39-feature vector with output labels.

39 features:
  Numeric (15):
    bias_confidence, plan_probability, day_sin, day_cos, hour_sin, hour_cos,
    entry_zone_width, stop_distance, tp1_distance, tp2_distance,
    risk_reward_tp1, risk_reward_tp2, target_spread, tp_ratio,
    bias_plan_alignment
  Symbol one-hot (3): EURUSD, GBPUSD, USDJPY
  Session one-hot (6): Asian, London, London_Open, Mid-session, NY, NY_Mid
  Expectation one-hot (4): LIQUIDITY_HUNT, TREND, RANGE, NEWS
  Session bias one-hot (3): BULLISH, BEARISH, NEUTRAL
  Plan bias one-hot (2): LONG, SHORT
  Plan confidence one-hot (3): HIGH, MEDIUM, LOW
  Derived (3): implied_range, stop_entry_ratio, entry_mid_norm

Output labels (y): bias_correct, tp1_hit, tp2_hit
"""

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sentinel_features")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CORPUS_PATH = Path("/opt/tradingbot/data/briefing_training_corpus.jsonl")
OUTCOMES_PATH = Path("/opt/tradingbot/data/briefing_outcomes.jsonl")

# ---------------------------------------------------------------------------
# Canonical category sets (order matters — defines one-hot column positions)
# ---------------------------------------------------------------------------
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCAD"]
SESSIONS = ["Asian", "London", "London_Open", "Mid-session", "NY", "NY_Mid", "NY_Data"]
EXPECTATIONS = ["LIQUIDITY_HUNT", "TREND", "RANGE", "NEWS"]
BIASES = ["BULLISH", "BEARISH", "NEUTRAL"]
PLAN_BIASES = ["LONG", "SHORT"]
PLAN_CONFIDENCES = ["HIGH", "MEDIUM", "LOW"]

FEATURE_COUNT = 39


def get_feature_names() -> List[str]:
    """Return ordered list of 39 feature names matching the output vector columns."""
    names = [
        # Numeric (15)
        "bias_confidence",
        "plan_probability",
        "day_sin",
        "day_cos",
        "hour_sin",
        "hour_cos",
        "entry_zone_width",
        "stop_distance",
        "tp1_distance",
        "tp2_distance",
        "risk_reward_tp1",
        "risk_reward_tp2",
        "target_spread",
        "tp_ratio",
        "bias_plan_alignment",
    ]
    # Symbol one-hot (3)
    names += [f"symbol_{s}" for s in SYMBOLS]
    # Session one-hot (6)
    names += [f"session_{s}" for s in SESSIONS]
    # Expectation one-hot (4)
    names += [f"expect_{e}" for e in EXPECTATIONS]
    # Session bias one-hot (3)
    names += [f"bias_{b}" for b in BIASES]
    # Plan bias one-hot (2)
    names += [f"plan_{p}" for p in PLAN_BIASES]
    # Plan confidence one-hot (3)
    names += [f"conf_{c}" for c in PLAN_CONFIDENCES]
    # Derived (3)
    names += ["implied_range", "stop_entry_ratio", "entry_mid_norm"]
    assert len(names) == FEATURE_COUNT, f"Expected {FEATURE_COUNT}, got {len(names)}"
    return names


def _one_hot(value: Optional[str], categories: List[str]) -> List[float]:
    """Return one-hot vector. All zeros if value not in categories."""
    return [1.0 if value == c else 0.0 for c in categories]


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert to float, returning default on failure."""
    if val is None:
        return default
    try:
        v = float(val)
        return v if math.isfinite(v) else default
    except (ValueError, TypeError):
        return default


def _normalise_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a record to a uniform dict regardless of source format.

    Handles both:
      - briefing_training_corpus.jsonl format (nested: metadata, input_features, briefing_output)
      - briefing_outcomes.jsonl format (flat)
    """
    if "metadata" in record and "input_features" in record:
        # Training corpus format — merge all sections flat
        flat = {}
        flat.update(record.get("metadata", {}))
        flat.update(record.get("input_features", {}))
        out = record.get("briefing_output", {})
        if isinstance(out, dict):
            flat.update(out)
        return flat
    # Already flat (outcomes format)
    return record


def extract_features(record: Dict[str, Any]) -> Dict[str, float]:
    """Extract a 39-feature dict from a single raw training/outcome record.

    Returns dict mapping feature name → normalised float value.
    """
    r = _normalise_record(record)

    # --- Numeric features ---
    bias_conf = _safe_float(r.get("bias_confidence"), 0.5)
    plan_prob = _safe_float(r.get("plan_probability"), 0.5)

    # Cyclical day-of-week encoding
    dow = _safe_float(r.get("day_of_week"), 0)
    day_sin = math.sin(2 * math.pi * dow / 7)
    day_cos = math.cos(2 * math.pi * dow / 7)

    # Cyclical hour encoding from briefing_time
    hour = 12.0  # default midday
    bt = r.get("briefing_time") or r.get("briefing_time_utc") or ""
    if isinstance(bt, str) and "T" in bt:
        try:
            time_part = bt.split("T")[1]
            hour = float(time_part[:2]) + float(time_part[3:5]) / 60.0
        except (IndexError, ValueError):
            pass
    hour_sin = math.sin(2 * math.pi * hour / 24)
    hour_cos = math.cos(2 * math.pi * hour / 24)

    # Entry zone / stop / target distances
    entry_zone = r.get("plan_entry_zone") or [0, 0]
    if isinstance(entry_zone, list) and len(entry_zone) >= 2:
        ez_lo, ez_hi = _safe_float(entry_zone[0]), _safe_float(entry_zone[1])
    else:
        ez_lo, ez_hi = 0.0, 0.0
    entry_mid = (ez_lo + ez_hi) / 2.0 if (ez_lo + ez_hi) > 0 else 0.0
    entry_zone_width = abs(ez_hi - ez_lo)

    stop = _safe_float(r.get("plan_stop_loss"))
    stop_distance = abs(entry_mid - stop) if entry_mid and stop else 0.0

    targets = r.get("plan_targets") or [0, 0]
    if isinstance(targets, list) and len(targets) >= 2:
        tp1 = _safe_float(targets[0])
        tp2 = _safe_float(targets[1])
    else:
        tp1, tp2 = 0.0, 0.0
    tp1_distance = abs(tp1 - entry_mid) if entry_mid and tp1 else 0.0
    tp2_distance = abs(tp2 - entry_mid) if entry_mid and tp2 else 0.0

    risk_reward_tp1 = tp1_distance / stop_distance if stop_distance > 0 else 0.0
    risk_reward_tp2 = tp2_distance / stop_distance if stop_distance > 0 else 0.0
    target_spread = abs(tp2_distance - tp1_distance)
    tp_ratio = tp2_distance / tp1_distance if tp1_distance > 0 else 0.0

    # Bias-plan alignment: 1 if bias direction matches plan direction
    s_bias = str(r.get("session_bias", "")).upper()
    p_bias = str(r.get("plan_bias", "")).upper()
    alignment = 1.0 if (
        (s_bias == "BULLISH" and p_bias == "LONG") or
        (s_bias == "BEARISH" and p_bias == "SHORT")
    ) else 0.0

    # --- Categorical one-hot ---
    symbol = str(r.get("symbol", "")).upper()
    session = str(r.get("session", ""))
    expectation = str(r.get("session_expectation", "")).upper()
    plan_conf = str(r.get("plan_confidence", "")).upper()

    oh_symbol = _one_hot(symbol, SYMBOLS)
    oh_session = _one_hot(session, SESSIONS)
    oh_expect = _one_hot(expectation, EXPECTATIONS)
    oh_bias = _one_hot(s_bias, BIASES)
    oh_plan = _one_hot(p_bias, PLAN_BIASES)
    oh_conf = _one_hot(plan_conf, PLAN_CONFIDENCES)

    # --- Derived (3) ---
    # Implied range: distance from stop to furthest target
    all_levels = [l for l in [stop, tp1, tp2] if l > 0]
    implied_range = (max(all_levels) - min(all_levels)) if len(all_levels) >= 2 else 0.0

    stop_entry_ratio = stop_distance / entry_zone_width if entry_zone_width > 0 else 0.0

    # Normalised entry midpoint (divide by 10000 to get ~1.0 scale for FX)
    entry_mid_norm = entry_mid / 10000.0 if entry_mid > 0 else 0.0

    # --- Assemble vector ---
    vec = (
        [bias_conf, plan_prob, day_sin, day_cos, hour_sin, hour_cos,
         entry_zone_width, stop_distance, tp1_distance, tp2_distance,
         risk_reward_tp1, risk_reward_tp2, target_spread, tp_ratio,
         alignment]
        + oh_symbol
        + oh_session
        + oh_expect
        + oh_bias
        + oh_plan
        + oh_conf
        + [implied_range, stop_entry_ratio, entry_mid_norm]
    )

    assert len(vec) == FEATURE_COUNT, f"Vector length {len(vec)} != {FEATURE_COUNT}"

    names = get_feature_names()
    return dict(zip(names, vec))


def _extract_labels(record: Dict[str, Any]) -> Dict[str, float]:
    """Extract output labels from a record."""
    r = _normalise_record(record)
    return {
        "bias_correct": 1.0 if r.get("bias_correct") else 0.0,
        "tp1_hit": 1.0 if r.get("tp1_hit") else 0.0,
        "tp2_hit": 1.0 if r.get("tp2_hit") else 0.0,
    }


def _load_records(corpus_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load records from corpus or fall back to outcomes file."""
    path = Path(corpus_path) if corpus_path else CORPUS_PATH
    if not path.exists() or path.stat().st_size == 0:
        # Fall back to outcomes
        if OUTCOMES_PATH.exists():
            logger.info("Corpus not found at %s, falling back to %s", path, OUTCOMES_PATH)
            path = OUTCOMES_PATH
        else:
            return []

    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def build_feature_matrix(
    corpus_path: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build (X, y) numpy arrays from the training corpus, ready for sklearn.

    X: shape (n_records, 39) — normalised feature matrix
    y: shape (n_records, 3) — labels [bias_correct, tp1_hit, tp2_hit]

    Falls back to briefing_outcomes.jsonl if the training corpus doesn't exist yet.
    """
    records = _load_records(corpus_path)
    if not records:
        return np.empty((0, FEATURE_COUNT)), np.empty((0, 3))

    names = get_feature_names()
    X_rows = []
    y_rows = []

    for rec in records:
        feat = extract_features(rec)
        labels = _extract_labels(rec)
        X_rows.append([feat[n] for n in names])
        y_rows.append([labels["bias_correct"], labels["tp1_hit"], labels["tp2_hit"]])

    X = np.array(X_rows, dtype=np.float64)
    y = np.array(y_rows, dtype=np.float64)

    # Z-score normalisation on continuous columns (skip one-hot columns)
    continuous_mask = np.array([
        not any(name.startswith(p) for p in ("symbol_", "session_", "expect_",
                                              "bias_", "plan_", "conf_"))
        for name in names
    ])
    cont_idx = np.where(continuous_mask)[0]
    if len(cont_idx) > 0 and X.shape[0] > 1:
        means = X[:, cont_idx].mean(axis=0)
        stds = X[:, cont_idx].std(axis=0)
        stds[stds == 0] = 1.0  # avoid div-by-zero
        X[:, cont_idx] = (X[:, cont_idx] - means) / stds

    return X, y


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    X, y = build_feature_matrix()
    names = get_feature_names()
    print(f"Features: {len(names)}")
    print(f"X shape:  {X.shape}")
    print(f"y shape:  {y.shape}")
    if X.shape[0] > 0:
        print(f"\nFeature names: {names}")
        print(f"\nFirst record features:")
        for n, v in zip(names, X[0]):
            print(f"  {n:30s} = {v:.4f}")
        print(f"\nFirst record labels: bias_correct={y[0,0]}, tp1_hit={y[0,1]}, tp2_hit={y[0,2]}")
        print(f"\nLabel distribution:")
        print(f"  bias_correct: {y[:,0].mean():.2%}")
        print(f"  tp1_hit:      {y[:,1].mean():.2%}")
        print(f"  tp2_hit:      {y[:,2].mean():.2%}")
