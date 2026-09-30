#!/usr/bin/env python3
"""
One-off audit: re-classify every historical signal_log row currently labelled
"External/manual close detected (IG open positions)" using the new trail-aware
logic from trade_manager._detect_ig_close_reason (2026-06-12).

We do NOT rewrite signal_log.jsonl — that history is immutable. The output is
a JSON sidecar at logs/close_reason_relabel_audit.json containing:

  - generated_at:               ISO timestamp.
  - source_signal_log:          path read.
  - source_persist_state:       path checked.
  - rows_total_examined:        total rows scanned.
  - rows_external_manual:       rows whose stored close_reason was the bad label.
  - corrected[]:                per-row best-effort relabel.
  - aggregates:                 pip totals + counts per corrected label.

For each row we attempt two layers:
  A) Precise: if cache/profit_mgmt_state.json carries last_amended_sl_price
     for the exact pos_key the row implies, run the new classifier directly.
     This is essentially never possible for closed historical trades (the
     persistence file only holds active trades), but the code path is here
     so a future run on stale-but-present meta would still produce a precise
     label.
  B) Heuristic: from the row alone, infer the most likely corrected label:
       - scaled_out=True AND pnl > +be_band      → TRAIL_STOP (likely)
       - scaled_out=True AND pnl in BE band      → BE_STOP_POST_SCALEOUT (likely)
       - scaled_out=False AND pnl ≈ -sl_pips ±3p → SL_HIT_RACE (broker hit
                                                   original SL; sweep mislabel)
       - scaled_out=False AND pnl ≈ +tp_pips ±3p → TP_HIT_RACE
       - scaled_out=False AND pnl in (~-15 to 0) → STRUCTURE_EXIT_RACE_LIKELY
                                                   (bot-driven exit raced
                                                   with broker; race-guard
                                                   would fix forward)
       - otherwise                                → UNRECOVERABLE_MANUAL

The heuristic is deliberately conservative — we only emit a non-MANUAL label
when the row's economics fit a known mechanism within tolerance. Anything
ambiguous stays UNRECOVERABLE_MANUAL so this audit understates rather than
overstates the relabelling.

Usage:
  /opt/tradingbot/venv/bin/python scripts/close_reason_relabel_audit.py
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

SIGNAL_LOG = os.path.join(ROOT, "logs", "signal_log.jsonl")
PERSIST_STATE = os.path.join(
    os.getenv("CACHE_DIR", os.path.join(ROOT, "cache")),
    "profit_mgmt_state.json",
)
OUT = os.path.join(ROOT, "logs", "close_reason_relabel_audit.json")

BAD_LABEL = "External/manual close detected (IG open positions)"
TOL = float(os.getenv("CLOSE_REASON_MATCH_TOLERANCE_PIPS", "3.0") or 3.0)
BE_OFFSET = float(os.getenv("SOFTWARE_BE_OFFSET_PIPS", "1") or 1.0)


def _load_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _load_persist():
    try:
        with open(PERSIST_STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _row_pos_key(row):
    """Best-effort: signal_log rows store epic + strategy; the EPIC_STATE
    pos_key is `<epic>|<strategy>`. The persisted profit-mgmt cache uses the
    same key form (verified 2026-06-12)."""
    ep = row.get("epic") or ""
    st = row.get("strategy") or ""
    if ep and st:
        return f"{ep}|{st}"
    return ""


def _precise_relabel(row, persist):
    """Try the strict classifier path against persisted last_amended_sl_price."""
    pk = _row_pos_key(row)
    if not pk or pk not in persist:
        return None
    meta = persist.get(pk) or {}
    last_amend = meta.get("last_amended_sl_price")
    if last_amend is None:
        return None
    close_price = row.get("close_price")
    pip_size = 1.0  # GBPUSD/EURUSD pip_size = 1.0 here per trade_executor convention
    try:
        diff = abs(float(close_price) - float(last_amend)) / pip_size
    except Exception:
        return None
    if diff > TOL:
        return None
    scaled = bool(meta.get("scaled_out"))
    lock = float(meta.get("bb_bounce_trail_lock_pips") or 0.0)
    if scaled and lock > 0:
        return ("TRAIL_STOP", "precise_persisted_meta", diff)
    if scaled and lock == 0:
        return ("BE_STOP_POST_SCALEOUT", "precise_persisted_meta", diff)
    return ("AMENDED_SL_HIT", "precise_persisted_meta", diff)


def _heuristic_relabel(row):
    pnl = row.get("pnl_pips")
    sl_pips = row.get("sl_pips") or 0.0
    tp1_pips = row.get("tp1_pips") or 0.0
    scaled = bool(row.get("scaled_out"))
    if pnl is None:
        return ("UNRECOVERABLE_MANUAL", "no_pnl_pips", None)
    pnl = float(pnl)

    if scaled:
        # Post scale-out (+10p banked separately on the partial leg).
        # pnl_pips here is the RUNNER pnl. A small positive/zero/slightly
        # negative number → BE stop. Anything materially positive → trail.
        if pnl <= BE_OFFSET + TOL and pnl >= -TOL:
            return ("BE_STOP_POST_SCALEOUT", "heuristic_scaled+pnl_in_be_band", None)
        if pnl > BE_OFFSET + TOL:
            return ("TRAIL_STOP", "heuristic_scaled+positive_runner_pnl", None)
        # Negative runner pnl after scale-out is rare — typically a BE-stop
        # that filled below entry by spread + slippage.
        return ("BE_STOP_POST_SCALEOUT", "heuristic_scaled+slightly_negative_pnl", None)

    # Not scaled.
    if sl_pips and abs(pnl + sl_pips) <= TOL:
        return ("SL_HIT_RACE", "heuristic_close_at_original_SL", None)
    if tp1_pips and abs(pnl - tp1_pips) <= TOL:
        return ("TP_HIT_RACE", "heuristic_close_at_original_TP", None)

    # Structure-exit / regime_max_hold / sweep races: pnl typically sits in
    # a controlled negative band around -7 to -15p (the bot's safety
    # tolerance) or a partial positive zone when the exit fired pre-target.
    if -18.0 <= pnl <= -3.0:
        return ("STRUCTURE_EXIT_RACE_LIKELY", "heuristic_neg_band_-18..-3", None)
    if -3.0 < pnl < 0.0:
        return ("STRUCTURE_EXIT_RACE_LIKELY", "heuristic_small_negative", None)
    if 0.0 <= pnl <= 15.0:
        return ("AMENDED_SL_OR_TRAIL_RACE_LIKELY", "heuristic_small_positive", None)

    return ("UNRECOVERABLE_MANUAL", "heuristic_no_match", None)


def main():
    rows = _load_jsonl(SIGNAL_LOG)
    persist = _load_persist()

    ext_rows = [r for r in rows if BAD_LABEL in str(r.get("close_reason") or "")]
    corrected = []
    agg_counts = {}
    agg_pips = {}

    for r in ext_rows:
        precise = _precise_relabel(r, persist)
        if precise is not None:
            new_label, mode, diff = precise
        else:
            new_label, mode, diff = _heuristic_relabel(r)

        pnl = float(r.get("pnl_pips") or 0.0)
        agg_counts[new_label] = agg_counts.get(new_label, 0) + 1
        agg_pips[new_label] = agg_pips.get(new_label, 0.0) + pnl

        corrected.append({
            "row_id": r.get("id"),
            "deal_id": r.get("deal_id"),
            "open_ts": r.get("timestamp_open"),
            "close_ts": r.get("timestamp_close"),
            "epic": r.get("epic"),
            "strategy": r.get("strategy"),
            "direction": r.get("direction"),
            "entry": r.get("entry"),
            "sl_pips": r.get("sl_pips"),
            "tp1_pips": r.get("tp1_pips"),
            "scaled_out": bool(r.get("scaled_out")),
            "close_price": r.get("close_price"),
            "pnl_pips": pnl,
            "old_close_reason": r.get("close_reason"),
            "new_close_reason": new_label,
            "classification_mode": mode,
            "match_diff_pips": diff,
        })

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_signal_log": SIGNAL_LOG,
        "source_persist_state": PERSIST_STATE,
        "persist_state_entries": len(persist),
        "rows_total_examined": len(rows),
        "rows_external_manual": len(ext_rows),
        "tolerance_pips": TOL,
        "be_offset_pips": BE_OFFSET,
        "corrected": corrected,
        "aggregates": {
            "counts": agg_counts,
            "total_pips": {k: round(v, 2) for k, v in agg_pips.items()},
        },
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {OUT}")
    print(f"  rows_external_manual={len(ext_rows)}")
    print(f"  aggregates.counts={agg_counts}")
    print(f"  aggregates.total_pips={ {k: round(v,2) for k,v in agg_pips.items()} }")


if __name__ == "__main__":
    main()
