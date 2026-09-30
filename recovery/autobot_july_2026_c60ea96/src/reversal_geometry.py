"""
reversal_geometry.py — POST-FIRE TELEMETRY: BB_BOUNCE reversal geometry.

For each BB_BOUNCE fire, N=12 bars after entry, computes and logs:
  - reversal_extreme_price          post-fire LOW (BUY) / HIGH (SELL)
  - reversal_dist_from_level_pips   signed: neg = extreme fell short of the
                                    nearest reference level logged at fire;
                                    pos = extreme pierced through the level
                                    then reversed.
  - mae_past_level_pips             max(0, reversal_dist_from_level_pips) —
                                    the amount price ran THROUGH the level.

Writes to /opt/tradingbot/logs/reversal_geometry.jsonl, joined to
signal_log by trade_id (UUID stable across scale-out: log_open sets it,
log_partial + log_close patch the same record; verified verbatim in
signal_logger.py:1311).

Persistence: sidecar cache/reversal_geometry_pending.json. Pending fires
persist on every mutation; hydrate on module import. Same PATTERN as
profit_mgmt_state.json (persist-on-change, restore-on-startup) but in its
own file — decouples the pending registry from the trade-close meta-clear
path in trade_manager. The window can run its full N bars regardless of
when the position closed.

Independent lifecycle: N-bar window is the sole eval trigger. No trade-
active check, no scale-out check. This is intentional — the reversal
geometry is a market-behavior metric (price vs level over N bars post-
fire), not a per-trade metric. A scale-out at +8p at bar 3 has zero
effect on the bar-12 extreme, which is computed from raw 5m LOW/HIGH.

⚠️ TELEMETRY-ONLY: gates nothing. record_at_entry runs from
signal_logger.log_open (which itself runs AFTER the trade is already
open at IG). The 5m-close evaluator runs on the candle_builder callback
strictly AFTER dispatch on same-tick ordering, and its per-call work is
bounded (~2 pending × int compare + occasional 12-row pandas slice +
occasional JSONL append). Cannot delay, gate, or influence entry.

Kill switch:  REVERSAL_GEOMETRY_ENABLED=0.
Window bars:  REVERSAL_GEOMETRY_WINDOW_BARS=12.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("reversal_geometry")

# ── Config ───────────────────────────────────────────────────────────────
REVERSAL_GEOMETRY_ENABLED = str(
    os.getenv("REVERSAL_GEOMETRY_ENABLED", "1") or "1"
).strip().lower() in ("1", "true", "yes")

REVERSAL_GEOMETRY_WINDOW_BARS = int(
    os.getenv("REVERSAL_GEOMETRY_WINDOW_BARS", "12") or 12
)

LOG_PATH = os.getenv(
    "REVERSAL_GEOMETRY_LOG_PATH",
    "/opt/tradingbot/logs/reversal_geometry.jsonl",
)

STATE_PATH = os.path.join(
    os.getenv("CACHE_DIR", "/opt/tradingbot/cache"),
    "reversal_geometry_pending.json",
)

# ── In-memory state ──────────────────────────────────────────────────────
# trade_id (UUID from signal_log) → {pair, strategy, direction, entry_price,
#     entry_bar_ts, deal_id, nearest_level_type, nearest_level_dist_pips_at_fire,
#     dist_to_pdh_pips, dist_to_pdl_pips, registered_at_utc}
_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_LOCK = threading.Lock()
_WRITE_LOCK = threading.Lock()
_REGISTERED = False


# ── Persistence (sidecar file) ───────────────────────────────────────────
def _persist_state() -> None:
    """Snapshot _PENDING to disk. Called after every mutation
    (record_at_entry, drop-after-eval). Soft-fail — never raises."""
    try:
        d = os.path.dirname(STATE_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _PENDING_LOCK:
            data = {tid: dict(pend) for tid, pend in _PENDING.items()}
        with open(STATE_PATH, "w") as f:
            json.dump(data, f, default=str)
    except Exception as exc:
        logger.warning("[reversal_geometry] persist failed: %s", exc)


def _load_state() -> None:
    """Load pending fires from disk into _PENDING. Called once at module
    import. Soft-fail — missing / corrupt file → empty pending."""
    try:
        if not os.path.exists(STATE_PATH):
            return
        with open(STATE_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        with _PENDING_LOCK:
            for tid, pend in data.items():
                if isinstance(pend, dict):
                    _PENDING[str(tid)] = dict(pend)
        logger.info(
            "[reversal_geometry] restored %d pending fire(s) from %s",
            len(_PENDING), STATE_PATH,
        )
    except Exception as exc:
        logger.warning("[reversal_geometry] load failed: %s", exc)


def _write_record(record: Dict[str, Any]) -> None:
    """Append one JSON line to LOG_PATH. Soft-fail — never raises."""
    try:
        d = os.path.dirname(LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _WRITE_LOCK:
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.warning("[reversal_geometry] write failed: %s", exc)


# ── Public API — called from signal_logger.log_open ──────────────────────
def record_at_entry(
    trade_id: str,
    pair: str,
    direction: str,
    entry_price: float,
    entry_bar_ts: Optional[str],
    debug_dict: Optional[Dict[str, Any]],
    deal_id: Optional[str] = None,
    strategy: Optional[str] = None,
) -> None:
    """Register a BB_BOUNCE fire for N-bar reversal-geometry evaluation.

    Reads the nearest-level fields already put on debug_dict by build 3
    in gbpusd_bb_bounce.py. No-op for non-BB_BOUNCE strategies (all other
    strategies pass through silently). Validates entry_bar_ts parses to
    ISO so evaluate_pending never gets a malformed pending row that can't
    be dropped by bars-elapsed.

    trade_id is the UUID from signal_logger.log_open — stable across
    scale-out (log_partial patches the same record; log_close closes it).
    """
    if not REVERSAL_GEOMETRY_ENABLED:
        return
    if "BB_BOUNCE" not in (strategy or "").upper():
        return
    try:
        # Ingress validation: reject rows whose entry_bar_ts won't parse.
        # Prevents an unevictable row from sitting in the pending file.
        try:
            _ = datetime.fromisoformat(str(entry_bar_ts).replace("Z", "+00:00"))
        except Exception:
            logger.warning(
                "[reversal_geometry] rejecting fire %s — unparseable entry_bar_ts=%r",
                trade_id, entry_bar_ts,
            )
            return

        d = debug_dict or {}
        pend = {
            "trade_id": str(trade_id),
            "deal_id": deal_id,
            "pair": str(pair).upper(),
            "strategy": strategy,
            "direction": str(direction).upper(),
            "entry_price": float(entry_price) if entry_price is not None else None,
            "entry_bar_ts": str(entry_bar_ts),
            "nearest_level_type": d.get("nearest_level_type"),
            "nearest_level_dist_pips_at_fire": d.get("dist_to_nearest_level_pips"),
            "dist_to_pdh_pips": d.get("dist_to_pdh_pips"),
            "dist_to_pdl_pips": d.get("dist_to_pdl_pips"),
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        with _PENDING_LOCK:
            _PENDING[str(trade_id)] = pend
        _persist_state()
    except Exception as exc:
        logger.warning("[reversal_geometry] record_at_entry raised: %s", exc)


# ── 5m-close callback ────────────────────────────────────────────────────
def _evaluate_pending_on_close(payload: Dict[str, Any]) -> None:
    """For every pending fire on this pair whose bars_elapsed >= N,
    compute the extremes over [fire_bar+1 .. cur_bar (capped at
    fire_bar+N)], emit, drop from pending, persist.

    Called on every 5m close by candle_builder. Independent of trade
    active / scale-out state — the window is the sole eval trigger. A
    scale-out at +8p mid-window has zero effect on the extreme, which
    is computed from raw 5m LOW/HIGH.
    """
    if not REVERSAL_GEOMETRY_ENABLED:
        return
    try:
        sym = payload.get("symbol")
        df = payload.get("df_5m")
        if sym is None or df is None or len(df) < 2:
            return
        ts_col = "timestamp" if "timestamp" in df.columns else (
            "time" if "time" in df.columns else None
        )
        if ts_col is None:
            return
        try:
            cur_ts = df[ts_col].iloc[-1]
            cur_ts_iso = cur_ts.isoformat() if hasattr(cur_ts, "isoformat") else str(cur_ts)
        except Exception:
            return

        pair_u = str(sym).upper()
        ready = []
        with _PENDING_LOCK:
            for tid, pend in list(_PENDING.items()):
                if pend.get("pair") != pair_u:
                    continue
                fire_ts = pend.get("entry_bar_ts")
                if not fire_ts:
                    continue
                try:
                    fire_dt = datetime.fromisoformat(
                        str(fire_ts).replace("Z", "+00:00"),
                    )
                    cur_dt = datetime.fromisoformat(
                        str(cur_ts_iso).replace("Z", "+00:00"),
                    )
                    bars_elapsed = int((cur_dt - fire_dt).total_seconds() / 300.0)
                except Exception:
                    continue
                if bars_elapsed >= REVERSAL_GEOMETRY_WINDOW_BARS:
                    ready.append((tid, pend, bars_elapsed))
            # Pop under lock so a concurrent record_at_entry can't re-add
            # a same-trade_id row between iteration and drop.
            for tid, _, _ in ready:
                _PENDING.pop(tid, None)

        if not ready:
            return
        for tid, pend, bars_elapsed in ready:
            try:
                _emit(pend, df, ts_col, cur_ts_iso, bars_elapsed)
            except Exception as inner:
                logger.warning(
                    "[reversal_geometry] emit inner-loop raised for %s: %s",
                    tid, inner,
                )
        _persist_state()
    except Exception as exc:
        logger.warning("[reversal_geometry] evaluate_pending raised: %s", exc)


def _emit(pend, df, ts_col, cur_ts_iso, bars_elapsed) -> None:
    """Compute + write one row joined to signal_log by trade_id.

    Null-safe: any compute failure produces a null field on the record;
    the record still emits with the other fields intact."""
    trade_id = pend.get("trade_id")
    direction = str(pend.get("direction") or "").upper()
    entry_price = pend.get("entry_price")
    entry_bar_ts = pend.get("entry_bar_ts")
    nearest_type = pend.get("nearest_level_type")
    nearest_dist_at_fire = pend.get("nearest_level_dist_pips_at_fire")
    dpdh = pend.get("dist_to_pdh_pips")
    dpdl = pend.get("dist_to_pdl_pips")

    reversal_extreme_price = None
    bars_used = 0
    level_price = None
    reversal_dist_from_level_pips = None
    mae_past_level_pips = None

    # Extreme over the window (strictly after fire_bar, capped at N).
    try:
        fire_dt = datetime.fromisoformat(str(entry_bar_ts).replace("Z", "+00:00"))
        ts_series = df[ts_col]

        def _iso(v):
            return v.isoformat() if hasattr(v, "isoformat") else str(v)

        fire_iso = _iso(fire_dt)
        mask = ts_series.apply(lambda v: _iso(v) > fire_iso)
        window = df[mask]
        if len(window) > REVERSAL_GEOMETRY_WINDOW_BARS:
            window = window.iloc[:REVERSAL_GEOMETRY_WINDOW_BARS]
        bars_used = int(len(window))
        if bars_used > 0:
            if direction == "BUY":
                reversal_extreme_price = float(window["low"].min())
            elif direction == "SELL":
                reversal_extreme_price = float(window["high"].max())
    except Exception as ex_exc:
        logger.debug(
            "[reversal_geometry] extreme compute for %s: %s", trade_id, ex_exc,
        )

    # Reconstruct the level price from nearest_type + fire-time debug
    # fields. BB_BOUNCE = GBPUSD only; pip_size = 1.0 in the debug /
    # signal_log convention (matches signal_logger.py:889 entry%100 math).
    try:
        if entry_price is not None and nearest_type:
            ep = float(entry_price)
            if nearest_type == "pdh" and dpdh is not None:
                # dpdh = (entry - pdh)   →   pdh = entry - dpdh
                level_price = ep - float(dpdh)
            elif nearest_type == "pdl" and dpdl is not None:
                level_price = ep - float(dpdl)
            elif nearest_type == "round_00":
                level_price = round(ep / 100.0) * 100.0
            elif nearest_type == "round_50":
                level_price = round(ep / 50.0) * 50.0
    except Exception:
        level_price = None

    # Signed reversal distance:
    #   positive = extreme pierced through the level;
    #   negative = extreme fell short of the level.
    # Compute adverse-direction pips from entry for both extreme and level,
    # then subtract.
    try:
        if (reversal_extreme_price is not None
                and level_price is not None
                and entry_price is not None):
            ep = float(entry_price)
            ex = float(reversal_extreme_price)
            lv = float(level_price)
            if direction == "BUY":
                ex_adv = ep - ex   # positive if extreme BELOW entry
                lv_adv = ep - lv   # positive if level BELOW entry
            else:  # SELL
                ex_adv = ex - ep
                lv_adv = lv - ep
            reversal_dist_from_level_pips = round(ex_adv - lv_adv, 3)
            mae_past_level_pips = round(
                max(0.0, reversal_dist_from_level_pips), 3,
            )
    except Exception:
        pass

    _write_record({
        "phase": "post_fire",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "trade_id": trade_id,
        "deal_id": pend.get("deal_id"),
        "pair": pend.get("pair"),
        "strategy": pend.get("strategy"),
        "direction": direction,
        "entry_price": entry_price,
        "entry_bar_ts": entry_bar_ts,
        "eval_bar_ts": cur_ts_iso,
        "bars_elapsed": bars_elapsed,
        "bars_used": bars_used,
        "window_bars_configured": REVERSAL_GEOMETRY_WINDOW_BARS,
        "reversal_extreme_price": reversal_extreme_price,
        "level_price": level_price,
        "reversal_dist_from_level_pips": reversal_dist_from_level_pips,
        "mae_past_level_pips": mae_past_level_pips,
        "nearest_level_type": nearest_type,
        "nearest_level_dist_pips_at_fire": nearest_dist_at_fire,
    })


# ── Self-registration + startup hydration ────────────────────────────────
def _register() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        from candle_builder import register_5m_close_callback
        register_5m_close_callback(_evaluate_pending_on_close)
        _REGISTERED = True
        logger.info(
            "[reversal_geometry] registered 5m-close callback → %s "
            "(window=%d bars, enabled=%s)",
            LOG_PATH, REVERSAL_GEOMETRY_WINDOW_BARS, REVERSAL_GEOMETRY_ENABLED,
        )
    except Exception as exc:
        logger.error(
            "[reversal_geometry] failed to register callback: %s", exc,
            exc_info=True,
        )


if REVERSAL_GEOMETRY_ENABLED:
    _load_state()
    _register()
