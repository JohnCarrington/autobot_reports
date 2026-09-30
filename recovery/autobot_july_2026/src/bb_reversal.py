"""
bb_reversal.py — BB_REVERSAL v4 (rebuild 2026-04-22)

Single strategy replacing BB_REVERSAL v3 + DAILY_DOUBLE. One strategy, one
dispatcher block, one state file, one test suite. GBPUSD only (config-ready
for other pairs).

Behaviour summary:
  - 5M BB pierce + next-bar confirmation candle fires an entry. Confirmation
    uses CURRENT-bar BB reference (Fix 1 preserved).
  - Direction mechanical: lower pierce = BUY, upper = SELL.
  - Two independent windows: W1 06:00–12:15 UTC, W2 12:30–16:00 UTC.
  - Pyramiding: up to PYRAMID_MAX_LEGS (3) concurrent open legs per window,
    minimum PYRAMID_MIN_BAR_GAP (2) bars between successive fires.
  - TP tier = slot: leg 1 → briefing TP1, leg 2 → TP2, leg 3 → TP3. If the
    briefing has no briefing-derived level for a tier (synthetic/fallback
    padding), that slot cannot fire and TP_TIER_UNAVAILABLE is logged.
  - Re-arm: when a leg hits SL, its slot is armed for tighter_filter on the
    next fire in THAT slot (other slots unaffected). tighter_filter is a
    stub (returns True) — MACD-side decision is deferred.
  - LONG and SHORT pierces fire independently. There is no cross-direction
    suppression: an open BUY leg does not block a confirmed SELL pierce
    (and vice versa). Same-direction stacking is governed by the existing
    pyramiding rules (PYRAMID_MAX_LEGS / PYRAMID_MIN_BAR_GAP).
  - State transitions to ACTIVE are gated on trade_opened() confirmation:
    a proposed trade is a _PendingProposal with a 30s TTL. If no open
    callback arrives, the proposal is pruned on the next evaluate and the
    slot stays free. This is the DAILY_DOUBLE dormancy-bug fix.

State persisted in cache/bb_reversal_window_state.json. Legacy
bb_reversal_window_fired.json and daily_double_window_state.json are
removed on first run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

import trend_detection
from strategy_logic import StrategyDecision


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BB_REVERSAL_ENABLED = str(os.getenv("BB_REVERSAL_ENABLED", "1")).strip().lower() in ("1", "true", "yes")
# Suppression gate: when H1 shows a clean trend AGAINST the pierce direction,
# skip the entry. Default-on; toggle off via env if it misbehaves in live data.
TREND_SUPPRESSION_ENABLED = str(
    os.getenv("BB_REVERSAL_TREND_SUPPRESSION_ENABLED", "1")
).strip().lower() in ("1", "true", "yes")
ALLOWED_PAIRS = frozenset(
    p.strip().upper()
    for p in os.getenv("BB_REVERSAL_PAIRS", "GBPUSD").split(",")
    if p.strip()
)
BB_REVERSAL_MODE = "BB_REVERSAL"

BB_PERIOD = int(os.getenv("BB_REVERSAL_PERIOD", "20") or 20)
BB_STD = float(os.getenv("BB_REVERSAL_STD", "2") or 2.0)
ATR_PERIOD = int(os.getenv("BB_REVERSAL_ATR_PERIOD", "14") or 14)


def _sl_pips_for_pair(pair: str) -> float:
    """Per-pair SL from trade_manager.BRIEFING_TP_SL_PIPS, falling back
    to BRIEFING_TP_SL_DEFAULT. This is the EXACT SL BB_REVERSAL fires —
    not a floor. ATR no longer factors into SL sizing."""
    try:
        from trade_manager import BRIEFING_TP_SL_PIPS, BRIEFING_TP_SL_DEFAULT
        return float(BRIEFING_TP_SL_PIPS.get(str(pair).upper(), BRIEFING_TP_SL_DEFAULT))
    except Exception as e:
        logger.warning("SL floor lookup failed for %s: %s — using 20.0", pair, e)
        return 20.0

PYRAMID_MAX_LEGS = int(os.getenv("BB_REVERSAL_MAX_LEGS", "3") or 3)
PYRAMID_MIN_BAR_GAP = int(os.getenv("BB_REVERSAL_MIN_BAR_GAP", "2") or 2)

PROPOSAL_TTL_SECONDS = int(os.getenv("BB_REVERSAL_PROPOSAL_TTL_SEC", "30") or 30)

# Windows (UTC). Inclusive-inclusive bar-time bounds.
WINDOW_1 = (dtime(6, 0), dtime(12, 15))
WINDOW_2 = (dtime(12, 30), dtime(16, 0))

_STATE_FILE = "/opt/tradingbot/cache/bb_reversal_window_state.json"
_LEGACY_FILES = (
    "/opt/tradingbot/cache/bb_reversal_window_fired.json",
    "/opt/tradingbot/cache/daily_double_window_state.json",
)

_LOG_DIR = "/opt/tradingbot/logs"
os.makedirs(_LOG_DIR, exist_ok=True)
logger = logging.getLogger("BBReversal")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _fh = logging.FileHandler(os.path.join(_LOG_DIR, "bb_reversal.log"))
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_fh)
    logger.propagate = True


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class _Pierce:
    direction: str          # "BUY" | "SELL"
    pierce_high: float
    pierce_low: float
    pierce_close: float
    pierce_ts: datetime
    bb_upper_at_pierce: float
    bb_lower_at_pierce: float
    depth: float            # pips beyond the pierced band


@dataclass
class _PendingProposal:
    """An entry proposed but not yet confirmed as opened. Counts toward
    slot occupancy until either promoted to a leg (open callback) or
    pruned (TTL exceeded)."""
    proposal_id: str
    slot: int                  # 1..PYRAMID_MAX_LEGS; also the TP tier.
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    tp_tier: int
    tighter_filter_used: bool
    proposal_bar_ts: datetime  # bar-close ts at time of proposal
    expiry_ts: datetime        # proposal_bar_ts + PROPOSAL_TTL_SECONDS


@dataclass
class _Leg:
    slot: int
    direction: str
    entry_ts: datetime
    entry_price: float
    sl_price: float
    tp_price: float
    tp_tier: int
    pos_key: str
    tighter_filter_used: bool = False
    close_reason: Optional[str] = None
    close_ts: Optional[datetime] = None
    # Broker-side dealId captured at open time. Close-callback match uses
    # this FIRST, pos_key as fallback. The un-suffixed pos_key form is
    # reusable across sequentially-opened legs (after EPIC_STATE reset),
    # so matching purely by pos_key produced phantom-leg accrual on
    # 2026-04-23 when close-callbacks resolved to the wrong leg.
    deal_id: Optional[str] = None


@dataclass
class _WindowState:
    legs: List[_Leg] = field(default_factory=list)
    pending_proposal: Optional[_PendingProposal] = None
    tighter_filter_armed_slots: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tighter-filter re-arm stub.
#
# Signature contract:
#   pierce     : the confirmable _Pierce that would fire
#   candles_df : the 5M dataframe being evaluated (indicator-enriched in
#                prod — carries MACD_{fast}_{slow} column from candle_builder)
#   indicators : dict of extra values (bb_upper, bb_lower, bb_mid, atr,
#                symbol, slot) — symbol + slot are used for the veto log
#                and Telegram throttle key
# Returns:
#   True  → allow the entry
#   False → veto the entry
#
# Filter logic (2-week observation period from 2026-04-23):
#   BUY  passes iff MACD line > 0
#   SELL passes iff MACD line < 0
#   (MACD line == 0 vetoes both directions — treated as wrong-side.)
#
# If the MACD line cannot be extracted (missing column, NaN, short df),
# fails OPEN (returns True) so a broken indicator pipeline does not
# silently block all re-arms. The caller only invokes this hook when
# the slot is in tighter_filter_armed_slots, so first-entry-per-slot is
# never filtered.
# ---------------------------------------------------------------------------
_MACD_FAST_ENV = int(float(os.getenv("MACD_FAST", "35") or 35))
_MACD_SLOW_ENV = int(float(os.getenv("MACD_SLOW", "45") or 45))
_MACD_LINE_COL = f"MACD_{_MACD_FAST_ENV}_{_MACD_SLOW_ENV}"

# Per-symbol throttle for Telegram alerts. 5-minute window prevents
# spam when a window has multiple veto events back-to-back.
_TIGHTER_VETO_ALERT_WINDOW_SECS = 300.0
_TIGHTER_VETO_LAST_ALERT: Dict[str, float] = {}
_TIGHTER_VETO_ALERT_LOCK = threading.Lock()


def _extract_macd_line(candles_df: pd.DataFrame) -> Optional[float]:
    """Pull the latest MACD line value from the indicator-enriched df.
    Returns None if the column is absent or the value is NaN/non-finite."""
    if candles_df is None or not isinstance(candles_df, pd.DataFrame):
        return None
    if _MACD_LINE_COL not in candles_df.columns or len(candles_df) == 0:
        return None
    try:
        v = candles_df[_MACD_LINE_COL].iloc[-1]
        fv = float(v)
    except (TypeError, ValueError):
        return None
    import math
    if not math.isfinite(fv):
        return None
    return fv


def _send_tighter_veto_alert(symbol: str, slot: int, direction: str,
                              macd_line: float) -> None:
    """Send a per-symbol throttled Telegram alert. Silently suppresses
    sends within _TIGHTER_VETO_ALERT_WINDOW_SECS of the previous one."""
    import time
    now = time.time()
    with _TIGHTER_VETO_ALERT_LOCK:
        last = _TIGHTER_VETO_LAST_ALERT.get(symbol, 0.0)
        if now - last < _TIGHTER_VETO_ALERT_WINDOW_SECS:
            logger.debug(
                "[BB_REVERSAL] tighter-veto alert suppressed by 5min throttle "
                "sym=%s last_alert=%.0fs_ago", symbol, now - last,
            )
            return
        _TIGHTER_VETO_LAST_ALERT[symbol] = now
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(
            f"BB_REVERSAL re-arm vetoed: {symbol} slot {slot} {direction} — "
            f"MACD line {macd_line:.6f} on wrong side of zero"
        )
    except Exception as e:
        logger.debug("[BB_REVERSAL] telegram alert send failed: %s", e)


def apply_tighter_filter(pierce: _Pierce, candles_df: pd.DataFrame,
                          indicators: Dict[str, Any]) -> bool:
    macd_line = _extract_macd_line(candles_df)
    if macd_line is None:
        logger.debug(
            "[BB_REVERSAL] tighter-filter MACD unavailable — failing open "
            "sym=%s dir=%s slot=%s",
            indicators.get("symbol", "?") if isinstance(indicators, dict) else "?",
            getattr(pierce, "direction", "?"),
            indicators.get("slot", "?") if isinstance(indicators, dict) else "?",
        )
        return True

    direction = getattr(pierce, "direction", "")
    if direction == "BUY":
        passes = macd_line > 0
    elif direction == "SELL":
        passes = macd_line < 0
    else:
        return True  # unknown direction — fail open

    if passes:
        return True

    symbol = str(indicators.get("symbol", "?"))
    slot = indicators.get("slot", -1)
    logger.info(
        "[BB_REVERSAL] TIGHTER-FILTER-VETO sym=%s slot=%s dir=%s "
        "macd_line=%.6f reason=macd_wrong_side_of_zero",
        symbol, slot, direction, macd_line,
    )
    _send_tighter_veto_alert(symbol, slot, direction, macd_line)
    return False


# ---------------------------------------------------------------------------
# Session / window helpers
# ---------------------------------------------------------------------------
def _which_window(ts: datetime) -> Optional[str]:
    t = ts.astimezone(timezone.utc).time()
    if WINDOW_1[0] <= t <= WINDOW_1[1]:
        return "W1"
    if WINDOW_2[0] <= t <= WINDOW_2[1]:
        return "W2"
    return None


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def _bb(closes: pd.Series, period: int, std: float):
    mid = closes.rolling(window=period, min_periods=period).mean()
    sd = closes.rolling(window=period, min_periods=period).std(ddof=0)
    return mid + std * sd, mid, mid - std * sd


def _atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int):
    prev_close = closes.shift(1)
    tr = pd.concat([
        (highs - lows),
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def _point_per_pip(_symbol: str) -> float:
    # IG FX points == pips in our cache format for all tracked pairs.
    return 1.0


# ---------------------------------------------------------------------------
# Briefing TP plan
# ---------------------------------------------------------------------------
def _load_briefing(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import morning_briefing
        b = morning_briefing.get_briefing(symbol)
    except Exception as e:
        logger.warning("BRIEFING_LOAD_FAIL %s: %s", symbol, e)
        return None
    if not b or not isinstance(b, dict) or not b.get("symbol"):
        return None
    return b


def _extract_tp_levels(briefing: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for src in ("key_levels", "major_levels"):
        d = briefing.get(src, {}) or {}
        maj = (src == "major_levels")
        for v in d.get("resistance", []) or []:
            if v is not None:
                out.append({"price": float(v), "level_type": "resistance", "source": src, "major": maj})
        for v in d.get("support", []) or []:
            if v is not None:
                out.append({"price": float(v), "level_type": "support", "source": src, "major": maj})
    lp = briefing.get("liquidity_pools", {}) or {}
    for v in lp.get("buy_side", []) or []:
        if v is not None:
            out.append({"price": float(v), "level_type": "resistance", "source": "liq", "major": False})
    for v in lp.get("sell_side", []) or []:
        if v is not None:
            out.append({"price": float(v), "level_type": "support", "source": "liq", "major": False})
    return out


def _load_briefing_tp_plan(symbol: str, direction: str, entry_price: float,
                           ) -> Optional[Dict[str, Any]]:
    try:
        from trade_manager import select_tp_levels
    except Exception as e:
        logger.warning("TP_LEVELS_IMPORT_FAIL %s: %s", symbol, e)
        return None
    briefing = _load_briefing(symbol)
    if briefing is None:
        return None
    levels = _extract_tp_levels(briefing)
    want_type = "support" if str(direction).upper() == "SELL" else "resistance"
    filtered = [lv for lv in levels if lv["level_type"] == want_type]
    tp_plan = select_tp_levels(entry_price, direction, filtered, str(symbol).upper())
    return tp_plan


def _tp_for_tier(tp_plan: Optional[Dict[str, Any]], tier: int
                 ) -> Optional[Tuple[float, float]]:
    """Return (tp_pips, tp_price) for the requested briefing tier (1, 2, 3),
    or None if the briefing does not provide a real (non-synthetic) level
    for that tier. Callers MUST treat None as TP_TIER_UNAVAILABLE.
    """
    if tp_plan is None:
        return None
    if tp_plan.get("fallback"):
        return None
    levels_used = tp_plan.get("levels_used") or []
    if tier < 1 or tier > 3:
        return None
    if tier > len(levels_used):
        return None
    lv = levels_used[tier - 1]
    src = str(lv.get("source", "") if isinstance(lv, dict) else "").lower()
    if src == "synthetic":
        return None
    try:
        tp_pips = float(tp_plan[f"tp{tier}_pips"])
        tp_price = float(tp_plan[f"tp{tier}"])
    except (KeyError, TypeError, ValueError):
        return None
    return tp_pips, tp_price


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------
def _migrate_legacy_files() -> None:
    for p in _LEGACY_FILES:
        try:
            if os.path.exists(p):
                os.remove(p)
                logger.info("MIGRATION: removed legacy state file %s", p)
        except Exception as e:
            logger.warning("legacy file remove failed %s: %s", p, e)


def _serialize_state(state: Dict[str, _WindowState], date: str) -> Dict:
    def _leg_dict(l: _Leg) -> Dict:
        d = asdict(l)
        d["entry_ts"] = l.entry_ts.isoformat()
        if l.close_ts:
            d["close_ts"] = l.close_ts.isoformat()
        return d

    def _pp_dict(pp: Optional[_PendingProposal]) -> Optional[Dict]:
        if pp is None:
            return None
        d = asdict(pp)
        d["proposal_bar_ts"] = pp.proposal_bar_ts.isoformat()
        d["expiry_ts"] = pp.expiry_ts.isoformat()
        return d

    return {
        "date": date,
        "windows": {
            key: {
                "legs": [_leg_dict(l) for l in ws.legs],
                "pending_proposal": _pp_dict(ws.pending_proposal),
                "tighter_filter_armed_slots": list(ws.tighter_filter_armed_slots),
            }
            for key, ws in state.items()
        },
    }


def _deserialize_state(raw: Dict) -> Tuple[Optional[str], Dict[str, _WindowState]]:
    if not isinstance(raw, dict):
        return None, {}
    date = raw.get("date")
    out: Dict[str, _WindowState] = {}
    for key, wd in (raw.get("windows") or {}).items():
        if not isinstance(wd, dict):
            continue
        legs: List[_Leg] = []
        for ld in (wd.get("legs") or []):
            try:
                legs.append(_Leg(
                    slot=int(ld["slot"]),
                    direction=str(ld["direction"]),
                    entry_ts=datetime.fromisoformat(ld["entry_ts"]),
                    entry_price=float(ld["entry_price"]),
                    sl_price=float(ld["sl_price"]),
                    tp_price=float(ld["tp_price"]),
                    tp_tier=int(ld.get("tp_tier") or ld["slot"]),
                    pos_key=str(ld["pos_key"]),
                    tighter_filter_used=bool(ld.get("tighter_filter_used", False)),
                    close_reason=ld.get("close_reason"),
                    close_ts=(datetime.fromisoformat(ld["close_ts"])
                              if ld.get("close_ts") else None),
                    deal_id=ld.get("deal_id"),
                ))
            except Exception:
                continue
        pending_proposal = None
        pp = wd.get("pending_proposal")
        if isinstance(pp, dict):
            try:
                pending_proposal = _PendingProposal(
                    proposal_id=str(pp["proposal_id"]),
                    slot=int(pp["slot"]),
                    direction=str(pp["direction"]),
                    entry_price=float(pp["entry_price"]),
                    sl_price=float(pp["sl_price"]),
                    tp_price=float(pp["tp_price"]),
                    tp_tier=int(pp.get("tp_tier") or pp["slot"]),
                    tighter_filter_used=bool(pp.get("tighter_filter_used", False)),
                    proposal_bar_ts=datetime.fromisoformat(pp["proposal_bar_ts"]),
                    expiry_ts=datetime.fromisoformat(pp["expiry_ts"]),
                )
            except Exception:
                pass
        out[key] = _WindowState(
            legs=legs,
            pending_proposal=pending_proposal,
            tighter_filter_armed_slots=list(wd.get("tighter_filter_armed_slots") or []),
        )
    return (date if isinstance(date, str) else None), out


def _load_state_from_disk() -> Tuple[Optional[str], Dict[str, _WindowState]]:
    try:
        if not os.path.exists(_STATE_FILE):
            return None, {}
        with open(_STATE_FILE) as f:
            raw = json.load(f)
        return _deserialize_state(raw)
    except Exception as e:
        logger.warning("state load failed: %s — starting fresh", e)
        return None, {}


def _save_state_to_disk(date: str, state: Dict[str, _WindowState]) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        tmp = _STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_serialize_state(state, date), f)
        os.replace(tmp, _STATE_FILE)
    except Exception as e:
        logger.warning("state save failed: %s", e)


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------
class BBReversalStrategy:
    """Singleton. Construct once at autobot startup."""

    _instance: Optional["BBReversalStrategy"] = None

    def __init__(self) -> None:
        _migrate_legacy_files()
        self._lock = threading.Lock()
        self._state_date, self._windows = _load_state_from_disk()
        # In-memory pierce buffer, per (pair, wkey). Not persisted — rebuilt
        # from live bars. Only needed for the 1-bar confirmation window.
        self._pierce_buf: Dict[str, Dict[str, List[_Pierce]]] = {}
        # De-dupe eval bar
        self._last_eval_bar: Dict[str, datetime] = {}
        # Mid-session restart: rebuild leg state for any broker positions
        # that aren't already in our persisted state.
        self._reconstruct_from_epic_state()

    # ------------------------------------------------------------------
    # Mid-session restart reconstruction
    # ------------------------------------------------------------------
    def _reconstruct_from_epic_state(self) -> None:
        """Rebuild leg records for any open BB_REVERSAL (v3 or v4) or
        DAILY_DOUBLE positions found in trade_executor.EPIC_STATE that
        are not already present in our persisted state.

        Policy:
          - v4-persisted (has slot/tp_tier/window in EPIC_STATE): direct
            reconstruct into _windows[window].legs[slot].
          - Legacy (v3 BB_REVERSAL / DAILY_DOUBLE with no v4 metadata):
            infer window from open_time vs W1/W2 bounds, assign next
            free slot, tier defaults to TP1. Logged LEGACY-POSITION-
            DETECTED at WARN.
          - Unreconcilable (no direction, no open_time, outside windows,
            no free slot): logged RECONSTRUCTION-FAILED at ERROR and a
            Telegram alert is sent. Position stays open at broker
            untracked; manual intervention required.
        """
        try:
            from trade_executor import EPIC_STATE
        except Exception as e:
            logger.warning("reconstruction: cannot import EPIC_STATE: %s", e)
            return

        known_pos_keys = {
            l.pos_key for ws in self._windows.values() for l in ws.legs
        }

        v4_count = 0
        legacy_count = 0
        unreconcilable = 0
        any_reconstructed_leg: Optional[_Leg] = None

        for pk, st in list(EPIC_STATE.items()):
            if not isinstance(st, dict):
                continue
            if not (st.get("active") or st.get("pending_open")):
                continue
            mode = str(st.get("mode") or "").upper()
            if mode not in ("BB_REVERSAL", "DAILY_DOUBLE"):
                continue
            if pk in known_pos_keys:
                continue

            epic = str(st.get("epic") or pk.split("|")[0])
            direction = str(st.get("direction") or "").upper()
            if direction not in ("BUY", "SELL"):
                logger.error(
                    "RECONSTRUCTION-FAILED pos_key=%s mode=%s — no valid "
                    "direction (%r). Position open at broker; strategy "
                    "does NOT track it. Manual reconciliation required.",
                    pk, mode, st.get("direction"),
                )
                self._reconstruction_alert(pk, mode, "missing_direction")
                unreconcilable += 1
                continue

            open_time = st.get("open_time")
            entry_ts: Optional[datetime] = None
            if isinstance(open_time, (int, float)) and open_time > 0:
                try:
                    entry_ts = datetime.fromtimestamp(float(open_time), tz=timezone.utc)
                except Exception:
                    entry_ts = None

            window = st.get("window") if st.get("window") in ("W1", "W2") else None
            slot_raw = st.get("slot")
            tp_tier_raw = st.get("tp_tier")
            has_v4_meta = (
                window in ("W1", "W2")
                and isinstance(slot_raw, int)
                and slot_raw in range(1, PYRAMID_MAX_LEGS + 1)
            )

            # Infer window for legacy positions.
            if window is None:
                if entry_ts is None:
                    logger.error(
                        "RECONSTRUCTION-FAILED pos_key=%s mode=%s — no "
                        "window metadata and no open_time. Manual "
                        "reconciliation required.", pk, mode,
                    )
                    self._reconstruction_alert(pk, mode, "no_window_no_open_time")
                    unreconcilable += 1
                    continue
                inferred = _which_window(entry_ts)
                if inferred is None:
                    logger.error(
                        "RECONSTRUCTION-FAILED pos_key=%s mode=%s — "
                        "open_time %s outside W1/W2 bounds. Manual.",
                        pk, mode, entry_ts.isoformat(),
                    )
                    self._reconstruction_alert(
                        pk, mode, f"outside_windows:{entry_ts.isoformat()}"
                    )
                    unreconcilable += 1
                    continue
                window = inferred

            ws = self._window_state(epic, window)

            # Slot + tier resolution.
            if has_v4_meta:
                slot = int(slot_raw)
                tp_tier = int(tp_tier_raw) if isinstance(tp_tier_raw, int) else slot
            else:
                slot = self._next_free_slot(ws)
                if slot is None:
                    logger.error(
                        "RECONSTRUCTION-FAILED pos_key=%s mode=%s — "
                        "window %s has no free slot (all %d occupied). "
                        "Manual reconciliation required.",
                        pk, mode, window, PYRAMID_MAX_LEGS,
                    )
                    self._reconstruction_alert(
                        pk, mode, f"no_free_slot:{window}"
                    )
                    unreconcilable += 1
                    continue
                tp_tier = 1  # legacy default

            # SL/TP prices reconstructed from the stored pip distances.
            entry_price = st.get("entry_price")
            ep_f = float(entry_price) if entry_price is not None else 0.0
            sl_dist = float(st.get("sl") or _sl_pips_for_pair(epic.split(".")[2] if epic.count(".") >= 2 else "GBPUSD"))
            tp_dist = float(st.get("tp") or 0.0)
            if direction == "BUY":
                sl_price = ep_f - sl_dist
                tp_price = ep_f + tp_dist
            else:
                sl_price = ep_f + sl_dist
                tp_price = ep_f - tp_dist

            _rec_deal_id = str(st.get("dealId") or st.get("deal_id") or "") or None
            leg = _Leg(
                slot=slot,
                direction=direction,
                entry_ts=entry_ts or datetime.now(timezone.utc),
                entry_price=ep_f,
                sl_price=sl_price,
                tp_price=tp_price,
                tp_tier=tp_tier,
                pos_key=pk,
                tighter_filter_used=False,
                close_reason=None,
                deal_id=_rec_deal_id,
            )
            ws.legs.append(leg)
            any_reconstructed_leg = leg

            if has_v4_meta:
                v4_count += 1
                logger.info(
                    "RECONSTRUCTION-V4 pos_key=%s mode=%s epic=%s dir=%s "
                    "window=%s slot=%d tier=TP%d entry_ts=%s",
                    pk, mode, epic, direction, window, slot, tp_tier,
                    leg.entry_ts.isoformat(),
                )
            else:
                legacy_count += 1
                logger.warning(
                    "LEGACY-POSITION-DETECTED pos_key=%s mode=%s epic=%s "
                    "dir=%s window=%s slot=%d tier=TP%d entry_ts=%s — "
                    "reconstructed with inferred fields (no v4 metadata)",
                    pk, mode, epic, direction, window, slot, tp_tier,
                    leg.entry_ts.isoformat(),
                )

        if v4_count or legacy_count or unreconcilable:
            logger.info(
                "RECONSTRUCTION-SUMMARY v4=%d legacy=%d unreconcilable=%d",
                v4_count, legacy_count, unreconcilable,
            )

        if (v4_count or legacy_count):
            # If state_date wasn't set (no persisted file), derive from the
            # most recently reconstructed leg so saves land correctly.
            if self._state_date is None and any_reconstructed_leg is not None:
                self._state_date = any_reconstructed_leg.entry_ts.astimezone(
                    timezone.utc
                ).strftime("%Y-%m-%d")
            if self._state_date:
                _save_state_to_disk(self._state_date, self._windows)

        # Runtime invariant: after reconstruction every open leg in state
        # must correspond to an active broker position (matched by dealId).
        # A mismatch means close-callbacks were missed during a prior run
        # — the exact failure mode that produced the 2026-04-23 phantom
        # legs. Load broker positions once (from EPIC_STATE, already
        # reconciled by the autobot reconcile_open_positions pass) and
        # compare.
        try:
            self._assert_broker_alignment()
        except Exception as _inv_exc:
            logger.warning("[BB_REVERSAL] invariant check skipped: %s", _inv_exc)

    def _assert_broker_alignment(self) -> None:
        """ERROR log + Telegram alert per open leg whose dealId is not
        known to the broker (or EPIC_STATE). Callers decide whether to
        auto-close the leg; this method only reports."""
        try:
            from trade_executor import EPIC_STATE as _EPIC_STATE
        except Exception:
            return
        known_deal_ids: set = set()
        for _pk, _st in _EPIC_STATE.items():
            did = str(_st.get("dealId") or _st.get("deal_id") or "")
            if did and (_st.get("active") or _st.get("pending_open")):
                known_deal_ids.add(did)
        phantom: List[Tuple[str, _Leg]] = []
        for key, ws in self._windows.items():
            for l in ws.legs:
                if l.close_reason is not None:
                    continue
                if not l.deal_id:
                    # Legs from pre-fix state files may lack deal_id; skip
                    # them (can't meaningfully compare).
                    continue
                if l.deal_id not in known_deal_ids:
                    phantom.append((key, l))
        if not phantom:
            return
        for key, l in phantom:
            logger.error(
                "[BB_REVERSAL] PHANTOM-LEG key=%s slot=%d dir=%s deal_id=%s "
                "entry_ts=%s — leg open in state but no matching active "
                "broker position. Close callback was lost.",
                key, l.slot, l.direction, l.deal_id, l.entry_ts.isoformat(),
            )
        try:
            from telegram_alerts import send_telegram_message
            summary = "\n".join(
                f"• {key} slot={l.slot} {l.direction} deal_id={l.deal_id}"
                for key, l in phantom[:5]
            )
            extra = "" if len(phantom) <= 5 else f"\n…and {len(phantom) - 5} more"
            send_telegram_message(
                f"🚨 <b>BB_REVERSAL PHANTOM-LEG</b>\n"
                f"{len(phantom)} leg(s) open in state but no matching "
                f"broker position:\n<pre>{summary}{extra}</pre>\n"
                f"Close callbacks were lost. Inspect "
                f"bb_reversal_window_state.json."
            )
        except Exception as _alert_exc:
            logger.error(
                "PHANTOM-LEG telegram alert failed: %s: %s",
                type(_alert_exc).__name__, _alert_exc,
            )

    def _reconstruction_alert(self, pos_key: str, mode: str, reason: str) -> None:
        try:
            from telegram_alerts import send_telegram_message
            send_telegram_message(
                f"🚨 <b>RECONSTRUCTION-FAILED</b>\n"
                f"pos_key: <code>{pos_key}</code>\n"
                f"mode: <code>{mode}</code>\n"
                f"reason: <code>{reason}</code>\n"
                f"Position open at broker; BB_REVERSAL does NOT track it. "
                f"Manual reconciliation required."
            )
        except Exception as e:
            logger.error(
                "RECONSTRUCTION-FAILED telegram alert also failed: %s: %s",
                type(e).__name__, e,
            )

    # ------------------------------------------------------------------
    # Test / introspection helper
    # ------------------------------------------------------------------
    def window_state_label(self, epic: str, window: str,
                            as_of_ts: Optional[datetime] = None) -> str:
        """Return "NOT_FIRED" | "ACTIVE" | "COMPLETED" for the given window.

        ACTIVE iff there is at least one open leg OR one non-expired pending
        proposal for the window. as_of_ts allows tests to evaluate state at
        a specific bar timestamp; if omitted, uses wall-clock UTC.
        """
        ws = self._windows.get(self._window_key(epic, window))
        if ws is None:
            return "NOT_FIRED"
        if any(l.close_reason is None for l in ws.legs):
            return "ACTIVE"
        if ws.pending_proposal is not None:
            now = as_of_ts or datetime.now(timezone.utc)
            if now < ws.pending_proposal.expiry_ts:
                return "ACTIVE"
        return "NOT_FIRED"

    # ------------------------------------------------------------------
    # Day / key helpers
    # ------------------------------------------------------------------
    def _rotate_if_new_day(self, today_utc: str) -> None:
        if self._state_date != today_utc:
            if self._state_date is not None:
                logger.info(
                    "new UTC day %s → %s — resetting %d window states",
                    self._state_date, today_utc, len(self._windows),
                )
            self._state_date = today_utc
            self._windows = {}
            self._pierce_buf = {}
            _save_state_to_disk(today_utc, self._windows)

    def _window_key(self, epic: str, window: str) -> str:
        return f"{epic}:{window}"

    def _window_state(self, epic: str, window: str) -> _WindowState:
        k = self._window_key(epic, window)
        if k not in self._windows:
            self._windows[k] = _WindowState()
        return self._windows[k]

    # ------------------------------------------------------------------
    # Slot / leg reconciliation
    # ------------------------------------------------------------------
    def _prune_expired_proposal(self, ws: _WindowState, now_ts: datetime) -> None:
        pp = ws.pending_proposal
        if pp is None:
            return
        if now_ts >= pp.expiry_ts:
            logger.info(
                "PROPOSAL-EXPIRED slot=%d dir=%s proposal_id=%s (no open callback within TTL)",
                pp.slot, pp.direction, pp.proposal_id,
            )
            # If this proposal was consuming an armed tighter-filter slot,
            # restore the arm so the replacement can still use it.
            if pp.tighter_filter_used and pp.slot not in ws.tighter_filter_armed_slots:
                ws.tighter_filter_armed_slots.append(pp.slot)
            ws.pending_proposal = None

    def _occupied_slots(self, ws: _WindowState) -> List[int]:
        occ = [l.slot for l in ws.legs if l.close_reason is None]
        if ws.pending_proposal is not None:
            occ.append(ws.pending_proposal.slot)
        return occ

    def _next_free_slot(self, ws: _WindowState) -> Optional[int]:
        occ = set(self._occupied_slots(ws))
        for s in range(1, PYRAMID_MAX_LEGS + 1):
            if s not in occ:
                return s
        return None

    def _most_recent_entry_ts(self, ws: _WindowState) -> Optional[datetime]:
        """Most recent bar ts at which an entry was proposed or opened.
        Used for bar-gap enforcement. Counts pending proposals too."""
        candidates: List[datetime] = []
        for l in ws.legs:
            candidates.append(l.entry_ts)
        if ws.pending_proposal is not None:
            candidates.append(ws.pending_proposal.proposal_bar_ts)
        return max(candidates) if candidates else None

    def _open_legs_any_window(self, epic: str) -> List[_Leg]:
        """All currently-open legs across every window for this epic."""
        out: List[_Leg] = []
        prefix = f"{epic}:"
        for key, ws in self._windows.items():
            if not key.startswith(prefix):
                continue
            for l in ws.legs:
                if l.close_reason is None:
                    out.append(l)
        return out

    # ------------------------------------------------------------------
    # Pierce buffer
    # ------------------------------------------------------------------
    def _register_pierce(self, sym: str, wkey: str, pierce: _Pierce) -> None:
        self._pierce_buf.setdefault(sym, {}).setdefault(wkey, []).append(pierce)

    def _buffered_pierces(self, sym: str, wkey: str) -> List[_Pierce]:
        return self._pierce_buf.get(sym, {}).get(wkey, [])

    def _clear_pierces(self, sym: str, wkey: str,
                       keep_ts_ge: Optional[datetime] = None) -> None:
        """Drop buffered pierces. If keep_ts_ge is provided, pierces whose
        pierce_ts >= keep_ts_ge are retained. This lets a fire preserve a
        same-bar just-pierced setup for the next bar's confirmation check.
        """
        if keep_ts_ge is None:
            self._pierce_buf.setdefault(sym, {})[wkey] = []
            return
        existing = self._pierce_buf.get(sym, {}).get(wkey, [])
        self._pierce_buf.setdefault(sym, {})[wkey] = [
            p for p in existing if p.pierce_ts >= keep_ts_ge
        ]

    # ------------------------------------------------------------------
    # Decision construction
    # ------------------------------------------------------------------
    def _none(self, sym: str, reason: str) -> StrategyDecision:
        return StrategyDecision(
            symbol=sym, regime="BB_REVERSAL", signal="NONE",
            mode=BB_REVERSAL_MODE, entry=None, sl=None, tp=None,
            use_trailing_stop=False, reason=reason,
        )

    def _build_and_stage_proposal(self, sym: str, epic: str, window: str,
                                   p: _Pierce, ws: _WindowState,
                                   slot: int, ppp: float,
                                   tighter_filter_used: bool,
                                   confirm_bar_ts: datetime,
                                   confirm_close: float,
                                   ) -> Optional[StrategyDecision]:
        """Construct the StrategyDecision and register a _PendingProposal on
        the window state. Returns None if the briefing cannot provide a
        real TP level for slot's tier (caller already logged the veto).
        """
        direction = p.direction
        entry = confirm_close
        sl_pips = _sl_pips_for_pair(sym)  # exact — not a floor; ATR no longer a factor
        tier = slot  # slot 1 → TP1, slot 2 → TP2, slot 3 → TP3

        tp_plan = _load_briefing_tp_plan(sym, direction, float(entry))
        tp_tuple = _tp_for_tier(tp_plan, tier)
        if tp_tuple is None:
            logger.warning(
                "TP_TIER_UNAVAILABLE %s dir=%s slot=%d tier=%d — briefing did not "
                "provide a real TP%d level (plan=%s) — vetoing leg",
                sym, direction, slot, tier, tier,
                "fallback" if (tp_plan and tp_plan.get("fallback")) else "no_briefing" if tp_plan is None else "synthetic",
            )
            return None
        tp_pips, tp_price = tp_tuple

        # Detect TP-hit slot reuse. SL-close re-arm is already logged by
        # RE-ARM elsewhere; this is the *non-SL* path (typically TP1/2/3
        # hit) where the slot returns to the pool and a new pierce takes
        # it. Gives us data to evaluate whether re-fires earn their keep.
        _sl_reasons = ("sl", "sl_hit", "stop_loss", "stopped_out", "stop")
        prior_closed_same_slot = [
            l for l in ws.legs
            if l.slot == slot and l.close_reason is not None
            and str(l.close_reason).lower() not in _sl_reasons
        ]
        if prior_closed_same_slot:
            prior = max(
                prior_closed_same_slot,
                key=lambda l: l.close_ts or datetime.min.replace(tzinfo=timezone.utc),
            )
            logger.info(
                "LEG-SLOT-REUSE %s slot=%d prior_tier=TP%d new_tier=TP%d "
                "prior_close_ts=%s prior_close_reason=%s",
                sym, slot, prior.tp_tier, tier,
                prior.close_ts.isoformat() if prior.close_ts else "N/A",
                prior.close_reason,
            )

        if direction == "SELL":
            sl_price = entry + sl_pips * ppp
        else:
            sl_price = entry - sl_pips * ppp

        proposal_id = uuid.uuid4().hex
        pp = _PendingProposal(
            proposal_id=proposal_id,
            slot=slot,
            direction=direction,
            entry_price=float(entry),
            sl_price=float(sl_price),
            tp_price=float(tp_price),
            tp_tier=tier,
            tighter_filter_used=bool(tighter_filter_used),
            proposal_bar_ts=confirm_bar_ts,
            expiry_ts=confirm_bar_ts + timedelta(seconds=PROPOSAL_TTL_SECONDS),
        )

        reason = (
            f"BB_REVERSAL {direction} window={window} slot={slot} tier=TP{tier} "
            f"depth={p.depth:.2f} pierce_ts={p.pierce_ts.isoformat()} "
            f"sl_pips={sl_pips:.1f} tp_pips={tp_pips:.1f} "
            f"tighter_filter_used={tighter_filter_used}"
        )
        logger.info(
            "ENTRY %s %s entry=%.5f sl=%.5f(%.1fp) tp=%.5f(%.1fp) window=%s slot=%d tier=%d depth=%.2f%s proposal_id=%s",
            sym, direction, entry, sl_price, sl_pips, tp_price, tp_pips,
            window, slot, tier, p.depth,
            " tighter_filter=True" if tighter_filter_used else "", proposal_id,
        )

        debug: Dict[str, Any] = {
            "window": window,
            "slot": slot,
            "tp_tier": tier,
            "pyramid_leg_count_proposed": sum(1 for l in ws.legs if l.close_reason is None) + 1,
            "pierce_ts": p.pierce_ts.isoformat(),
            "pierce_depth": p.depth,
            "bb_upper_at_pierce": p.bb_upper_at_pierce,
            "bb_lower_at_pierce": p.bb_lower_at_pierce,
            "sl_price": float(sl_price),
            "tp_price": float(tp_price),
            "tighter_filter_used": bool(tighter_filter_used),
            "bypass_session_cap": True,
            "bbr_proposal_id": proposal_id,
        }

        # Pin regime classifier state at decision-construction time so
        # signal_log carries it with zero log-open staleness.
        try:
            from strategy_logic import get_latest_regime_state as _gls
            _rs = _gls(sym)
            if isinstance(_rs, dict):
                debug["regime_state"] = _rs
        except Exception:
            pass

        # Stage the proposal. Consume tighter-filter arm if used.
        with self._lock:
            ws.pending_proposal = pp
            if tighter_filter_used and slot in ws.tighter_filter_armed_slots:
                ws.tighter_filter_armed_slots.remove(slot)
            if self._state_date:
                _save_state_to_disk(self._state_date, self._windows)

        return StrategyDecision(
            symbol=sym, regime="BB_REVERSAL", signal=direction,
            mode=BB_REVERSAL_MODE, entry=float(entry),
            sl=float(abs(sl_pips)), tp=float(abs(tp_pips)),
            use_trailing_stop=False, reason=reason, debug=debug,
        )

    # ------------------------------------------------------------------
    # Main evaluate
    # ------------------------------------------------------------------
    def evaluate(self, symbol: str, epic: str, df: pd.DataFrame,
                 pip_size: float, mid_price: float) -> StrategyDecision:
        sym = str(symbol).upper()
        if not BB_REVERSAL_ENABLED:
            return self._none(sym, "disabled")
        if sym not in ALLOWED_PAIRS:
            return self._none(sym, "pair_not_allowed")
        if df is None or not isinstance(df, pd.DataFrame) or len(df) < BB_PERIOD + 2:
            return self._none(sym, f"warmup_bars_{len(df) if isinstance(df, pd.DataFrame) else 0}")

        d = df.copy()
        if "timestamp" in d.columns and "time" not in d.columns:
            d = d.rename(columns={"timestamp": "time"})
        for c in ("time", "open", "high", "low", "close"):
            if c not in d.columns:
                return self._none(sym, f"missing_col_{c}")
        d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
        d = d.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

        closes = pd.to_numeric(d["close"], errors="coerce").astype(float)
        highs = pd.to_numeric(d["high"], errors="coerce").astype(float)
        lows = pd.to_numeric(d["low"], errors="coerce").astype(float)
        bb_up_s, bb_mid_s, bb_lo_s = _bb(closes, BB_PERIOD, BB_STD)
        atr_s = _atr(highs, lows, closes, ATR_PERIOD)

        last_idx = len(d) - 1
        last = d.iloc[last_idx]
        last_ts = last["time"].to_pydatetime() if hasattr(last["time"], "to_pydatetime") else last["time"]
        if not isinstance(last_ts, datetime):
            last_ts = pd.Timestamp(last_ts).to_pydatetime()
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)

        if self._last_eval_bar.get(sym) == last_ts:
            return self._none(sym, "already_evaluated")
        self._last_eval_bar[sym] = last_ts

        today_utc = last_ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        self._rotate_if_new_day(today_utc)

        window = _which_window(last_ts)
        bb_up = float(bb_up_s.iloc[last_idx]) if pd.notna(bb_up_s.iloc[last_idx]) else None
        bb_lo = float(bb_lo_s.iloc[last_idx]) if pd.notna(bb_lo_s.iloc[last_idx]) else None
        bb_mid = float(bb_mid_s.iloc[last_idx]) if pd.notna(bb_mid_s.iloc[last_idx]) else None
        atr_val = float(atr_s.iloc[last_idx]) if pd.notna(atr_s.iloc[last_idx]) else 0.0

        logger.info(
            "EVAL %s ts=%s O=%.5f H=%.5f L=%.5f C=%.5f BBu=%s BBl=%s window=%s",
            sym, last_ts.isoformat(),
            float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"]),
            f"{bb_up:.5f}" if bb_up is not None else "NA",
            f"{bb_lo:.5f}" if bb_lo is not None else "NA",
            window or "OUTSIDE",
        )

        if bb_up is None or bb_lo is None or bb_mid is None:
            return self._none(sym, "bb_not_ready")
        if window is None:
            return self._none(sym, "outside_window")

        wkey = f"{today_utc}:{window}"
        ws = self._window_state(epic, window)
        # Prune any stale pending proposal before slot/gap checks.
        self._prune_expired_proposal(ws, last_ts)

        last_high = float(last["high"])
        last_low = float(last["low"])
        last_close = float(last["close"])

        # ------------ 1. Detect a pierce on THIS bar (buffer it) ------------
        pierce_up = last_high >= bb_up
        pierce_dn = last_low <= bb_lo
        if pierce_up and pierce_dn:
            if last_close >= bb_mid:
                pierce_up = False
            else:
                pierce_dn = False

        if pierce_up:
            depth = last_high - bb_up
            self._register_pierce(sym, wkey, _Pierce(
                direction="SELL", pierce_high=last_high, pierce_low=last_low,
                pierce_close=last_close, pierce_ts=last_ts,
                bb_upper_at_pierce=bb_up, bb_lower_at_pierce=bb_lo, depth=depth,
            ))
            logger.info("PIERCE-UP %s H=%.5f >= BBu=%.5f depth=%.5f — buffered SELL",
                        sym, last_high, bb_up, depth)
        elif pierce_dn:
            depth = bb_lo - last_low
            self._register_pierce(sym, wkey, _Pierce(
                direction="BUY", pierce_high=last_high, pierce_low=last_low,
                pierce_close=last_close, pierce_ts=last_ts,
                bb_upper_at_pierce=bb_up, bb_lower_at_pierce=bb_lo, depth=depth,
            ))
            logger.info("PIERCE-DN %s L=%.5f <= BBl=%.5f depth=%.5f — buffered BUY",
                        sym, last_low, bb_lo, depth)

        # ------------ 2. Separate confirmable from just-pierced ------------
        buf = self._buffered_pierces(sym, wkey)
        confirmable = [p for p in buf if p.pierce_ts < last_ts]
        just_pierced = [p for p in buf if p.pierce_ts == last_ts]

        max_conf = max((p.depth for p in confirmable), default=-1.0)
        max_new = max((p.depth for p in just_pierced), default=-1.0)
        if just_pierced and max_new > max_conf:
            logger.info("DEFER %s just_pierced_depth=%.5f > confirmable_depth=%.5f",
                        sym, max_new, max_conf)
            self._pierce_buf[sym][wkey] = list(just_pierced)
            return self._none(sym, "deeper_pierce_pending")

        # LONG and SHORT pierces are evaluated independently. No
        # opposite-direction suppression — same-direction stacking is
        # governed by pyramiding rules below.

        if not confirmable:
            return self._none(sym, "no_confirmable")

        # ------------ 5. Try deepest confirmable first ------------
        confirmable.sort(key=lambda p: p.depth, reverse=True)
        # Cache the H1 trend lookup for this evaluate() call so we don't
        # re-load + recompute per pierce. Loaded lazily on first use.
        _trend_cached: Optional[Tuple[str, Dict[str, Any]]] = None
        for p in confirmable:
            # Confirmation reclaim — current-bar BB reference (Fix 1 preserved)
            if p.direction == "SELL":
                inside_pierce_bar = last_close < p.bb_upper_at_pierce
                inside_for_dir = last_close < bb_up
            else:
                inside_pierce_bar = last_close > p.bb_lower_at_pierce
                inside_for_dir = last_close > bb_lo

            logger.info(
                "CONFIRM-CHECK %s dir=%s depth=%.5f pierce_ts=%s confirm_close=%.5f "
                "inside_for_dir=%s (pierce_bar_ref=%s current_bar_ref=%s)",
                sym, p.direction, p.depth, p.pierce_ts.isoformat(),
                last_close, inside_for_dir, inside_pierce_bar, inside_for_dir,
            )
            if inside_for_dir != inside_pierce_bar:
                logger.warning(
                    "CONFIRM-RECLAIM-DIVERGENCE %s dir=%s close=%.5f "
                    "pierce_bar_bb=%.5f current_bar_bb=%.5f verdict=%s (pierce_ref=%s)",
                    sym, p.direction, last_close,
                    (p.bb_upper_at_pierce if p.direction == "SELL" else p.bb_lower_at_pierce),
                    (bb_up if p.direction == "SELL" else bb_lo),
                    "PASS" if inside_for_dir else "FAIL",
                    "PASS" if inside_pierce_bar else "FAIL",
                )

            if not inside_for_dir:
                logger.info("CONFIRM-FAIL %s %s depth=%.5f", sym, p.direction, p.depth)
                continue

            # ------------ 5b. Trend-suppression gate ------------
            # Counter-trend mean-reversion is the failure mode of this
            # strategy on clean trend days. When H1 shows a clean trend
            # AGAINST this pierce direction, suppress and log the reason.
            # Asymmetric: an UP trend does not block a BUY pierce; only
            # the wrong-side combination blocks.
            if TREND_SUPPRESSION_ENABLED:
                if _trend_cached is None:
                    h1_candles = trend_detection.load_h1_candles_from_cache(sym)
                    _trend_cached = trend_detection.is_clean_trend(sym, h1_candles)
                trend_dir, trend_details = _trend_cached
                blocked = (
                    (p.direction == "BUY"  and trend_dir == "DOWN") or
                    (p.direction == "SELL" and trend_dir == "UP")
                )
                if blocked:
                    logger.info(
                        "TREND-SUPPRESS %s %s pierce — clean H1 %s trend in play "
                        "(price=%.2f ema50=%.2f ema21=%.2f macd_hist=%.4f directional=%d/%d)",
                        sym, p.direction, trend_dir,
                        trend_details.get("current_price", 0.0),
                        trend_details.get("ema50", 0.0),
                        trend_details.get("ema21", 0.0),
                        trend_details.get("macd_hist", 0.0),
                        trend_details.get("directional_count", 0),
                        trend_details.get("lookback", 0),
                    )
                    continue

            # ------------ 6. Pyramid constraints ------------
            occupied = len(self._occupied_slots(ws))
            if occupied >= PYRAMID_MAX_LEGS:
                logger.info(
                    "PYRAMID-MAX %s dir=%s — %d slots occupied >= max %d",
                    sym, p.direction, occupied, PYRAMID_MAX_LEGS,
                )
                continue

            slot = self._next_free_slot(ws)
            if slot is None:
                logger.info("PYRAMID-NO-SLOT %s — all slots occupied", sym)
                continue

            # Bar-gap vs most recent entry (leg or pending proposal)
            most_recent = self._most_recent_entry_ts(ws)
            if most_recent is not None:
                bars_since = int((last_ts - most_recent).total_seconds() // 300)
                if bars_since < PYRAMID_MIN_BAR_GAP:
                    logger.info(
                        "PYRAMID-BAR-GAP %s bars_since_last=%d < min=%d — skipping",
                        sym, bars_since, PYRAMID_MIN_BAR_GAP,
                    )
                    continue

            # Re-arm tighter-filter — MACD-line-side-of-zero check.
            # The detailed veto log (with macd_line value) is emitted
            # from inside apply_tighter_filter; no duplicate log here.
            tighter_used = slot in ws.tighter_filter_armed_slots
            if tighter_used:
                allow = apply_tighter_filter(
                    pierce=p, candles_df=d,
                    indicators={
                        "bb_upper": bb_up, "bb_lower": bb_lo,
                        "bb_mid": bb_mid, "atr": atr_val,
                        "symbol": sym, "slot": slot,
                    },
                )
                if not allow:
                    continue

            # ------------ 7. Stage proposal (NOT a committed leg) ------------
            ppp = _point_per_pip(sym)
            decision = self._build_and_stage_proposal(
                sym, epic, window, p, ws, slot, ppp, tighter_used,
                confirm_bar_ts=last_ts, confirm_close=last_close,
            )
            if decision is None:
                # TP_TIER_UNAVAILABLE — already logged. Try next confirmable.
                continue
            # Preserve any pierce registered on THIS bar (just-pierced) so the
            # next bar's evaluate can try to confirm it. Only the historical
            # confirmable pierces are discarded.
            self._clear_pierces(sym, wkey, keep_ts_ge=last_ts)
            return decision

        return self._none(sym, "no_fire_after_checks")

    # ------------------------------------------------------------------
    # Trade-opened callback (state-gate confirmation)
    # ------------------------------------------------------------------
    def on_trade_opened(self, pos_key: str, decision: Any) -> None:
        """Called by autobot after a trade is ACCEPTED by the broker. Promotes
        the matching _PendingProposal to a committed _Leg. Proposals are
        matched by bbr_proposal_id in decision.debug.
        """
        if not decision:
            return
        try:
            mode = str(getattr(decision, "mode", "") or "").upper()
        except Exception:
            mode = ""
        if mode != BB_REVERSAL_MODE:
            return
        dbg = getattr(decision, "debug", None) or {}
        proposal_id = str(dbg.get("bbr_proposal_id") or "")
        if not proposal_id:
            logger.warning(
                "on_trade_opened: pos_key=%s no bbr_proposal_id in decision.debug — ignoring",
                pos_key,
            )
            return
        with self._lock:
            for key, ws in self._windows.items():
                pp = ws.pending_proposal
                if pp is None or pp.proposal_id != proposal_id:
                    continue
                # Capture broker dealId from EPIC_STATE at open time. The
                # close-callback matcher prefers deal_id over pos_key because
                # un-suffixed pos_keys can be reused across sequential legs
                # (see _Leg.deal_id docstring).
                _opened_deal_id: Optional[str] = None
                try:
                    from trade_executor import EPIC_STATE as _EPIC_STATE
                    _es = _EPIC_STATE.get(pos_key) or {}
                    _raw = _es.get("dealId") or _es.get("deal_id")
                    _opened_deal_id = str(_raw) if _raw else None
                except Exception:
                    _opened_deal_id = None
                leg = _Leg(
                    slot=pp.slot,
                    direction=pp.direction,
                    entry_ts=pp.proposal_bar_ts,
                    entry_price=pp.entry_price,
                    sl_price=pp.sl_price,
                    tp_price=pp.tp_price,
                    tp_tier=pp.tp_tier,
                    pos_key=str(pos_key),
                    tighter_filter_used=pp.tighter_filter_used,
                    deal_id=_opened_deal_id,
                )
                ws.legs.append(leg)
                ws.pending_proposal = None
                if self._state_date:
                    _save_state_to_disk(self._state_date, self._windows)
                logger.info(
                    "LEG-OPENED key=%s slot=%d dir=%s tier=TP%d pos_key=%s deal_id=%s proposal_id=%s",
                    key, leg.slot, leg.direction, leg.tp_tier, pos_key,
                    _opened_deal_id or "-", proposal_id,
                )
                return
        logger.warning(
            "on_trade_opened: pos_key=%s proposal_id=%s did not match any pending proposal",
            pos_key, proposal_id,
        )

    # ------------------------------------------------------------------
    # Trade-closed callback
    # ------------------------------------------------------------------
    def on_trade_close(self, pos_key: str, exit_price: Optional[float],
                        pnl_pips: Optional[float], close_reason: Optional[str],
                        deal_id: Optional[str] = None) -> None:
        # _CLOSE_CALLBACKS in trade_executor are broadcast: every registered
        # callback fires for every close. Filter out closes that clearly
        # belong to other strategies — pos_key carries a "|<MODE>" suffix
        # whenever the manager identifies the owning strategy. Without this
        # gate, BB_REVERSAL would search its windows for an unknown deal_id
        # and emit a spurious PHANTOM-CLOSE alert for every NEWS_TICK / 3CO /
        # BRIEFING_EXECUTION close.
        if pos_key and "|" in pos_key:
            if "|BB_REVERSAL" not in pos_key:
                return  # close belongs to another strategy
        elif not deal_id:
            return  # bare epic without deal_id — cannot disambiguate
        with self._lock:
            target: Optional[Tuple[str, _Leg]] = None
            match_via = ""
            # Preferred: match by broker dealId. Unambiguous across
            # un-suffixed pos_key reuse.
            if deal_id:
                for key, ws in self._windows.items():
                    for l in ws.legs:
                        if l.deal_id == deal_id and l.close_reason is None:
                            target = (key, l)
                            match_via = "deal_id"
                            break
                    if target is not None:
                        break
            # Fallback: pos_key match (back-compat for callers that don't
            # pass deal_id yet, and for legs reconstructed pre-fix without
            # a deal_id field).
            if target is None:
                for key, ws in self._windows.items():
                    for l in ws.legs:
                        if l.pos_key == pos_key and l.close_reason is None:
                            target = (key, l)
                            match_via = "pos_key"
                            break
                    if target is not None:
                        break
            if target is None:
                logger.error(
                    "[BB_REVERSAL] PHANTOM-CLOSE pos_key=%s deal_id=%s reason=%s — "
                    "close callback received but no matching open leg in state",
                    pos_key, deal_id or "-", close_reason,
                )
                try:
                    from telegram_alerts import send_telegram_message
                    send_telegram_message(
                        f"🚨 <b>BB_REVERSAL PHANTOM-CLOSE</b>\n"
                        f"pos_key: <code>{pos_key}</code>\n"
                        f"deal_id: <code>{deal_id or '-'}</code>\n"
                        f"reason: <code>{close_reason}</code>\n"
                        f"Close callback arrived but no open leg matches. "
                        f"State may be divergent — inspect bb_reversal_window_state.json."
                    )
                except Exception:
                    pass
                return
            key, leg = target
            leg.close_reason = close_reason or "unknown"
            leg.close_ts = datetime.now(timezone.utc)

            was_sl = str(close_reason or "").lower() in (
                "sl", "sl_hit", "stop_loss", "stopped_out", "stop",
            )
            ws = self._windows[key]
            if was_sl and leg.slot not in ws.tighter_filter_armed_slots:
                ws.tighter_filter_armed_slots.append(leg.slot)
                logger.info(
                    "RE-ARM slot=%d key=%s reason=sl — tighter filter armed",
                    leg.slot, key,
                )
            logger.info(
                "LEG-CLOSE slot=%d key=%s pnl=%s reason=%s match=%s (open_remaining=%d)",
                leg.slot, key, pnl_pips, close_reason, match_via,
                sum(1 for l in ws.legs if l.close_reason is None),
            )
            if self._state_date:
                _save_state_to_disk(self._state_date, self._windows)


# ---------------------------------------------------------------------------
# Module-level registration helpers
# ---------------------------------------------------------------------------
def get_instance() -> BBReversalStrategy:
    if BBReversalStrategy._instance is None:
        BBReversalStrategy._instance = BBReversalStrategy()
    return BBReversalStrategy._instance


def on_bb_reversal_trade_opened(pos_key: str, decision: Any) -> None:
    try:
        get_instance().on_trade_opened(pos_key, decision)
    except Exception as e:
        logger.warning("on_bb_reversal_trade_opened error: %s", e)


def on_bb_reversal_trade_close(pos_key: str, exit_price: Optional[float],
                                pnl_pips: Optional[float],
                                close_reason: Optional[str],
                                deal_id: Optional[str] = None) -> None:
    try:
        get_instance().on_trade_close(pos_key, exit_price, pnl_pips, close_reason,
                                       deal_id=deal_id)
    except Exception as e:
        logger.warning("on_bb_reversal_trade_close error: %s", e)
