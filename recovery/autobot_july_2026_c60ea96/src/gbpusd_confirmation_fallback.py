"""gbpusd_confirmation_fallback.py — CHOP-bucket sweep / reclaim / M5-confirm sequencer.

Self-dispatching strategy intended to populate the regime stand-down bucket
that TREND/RANGE strategies (EMA_PULLBACK, BB_BOUNCE) do not cover. The
regime router is dormant on this deployment (REGIME_ROUTER_ENGINE_ENABLED=0),
so this module mirrors the BB_BOUNCE pattern: self-dispatch from autobot.py
and self-gate on regime internally.

Sequence (BUY; SELL is the mirror):
  1. SWEEP    — a CLOSED 5M bar's LOW pierces a sell-side liquidity level
                (PDL / Asian low / H1 swing low) below current price. The
                swept level + bar are recorded; subsequent bars never
                re-derive the level.
  2. RECLAIM  — a SUBSEQUENT closed 5M bar's CLOSE prints above the swept
                level. Confirms the sweep was not held below.
  3. CONFIRM  — a closed 5M bar prints a bullish body (close > open) AND
                closes above the reclaimed level. Reclaim+confirm can land
                on the same bar (and usually will when the move is clean).

Sequence expiry: if reclaim+confirm don't both occur within
CONFIRMATION_FALLBACK_SEQUENCE_MAX_BARS (default 6) of the sweep bar, the
setup is abandoned.

Non-repainting discipline:
  - Every phase is evaluated only on bars[-1] (the just-closed bar) and
    earlier. The in-progress bar is never read here — autobot only invokes
    this strategy on 5M close (BB_BOUNCE's `_is_new_5m` path).
  - The swept level is captured at sweep time and stored in the armed
    state. No later bar recomputes it.
  - Per-bar dedup via self._last_eval_bar prevents double-evaluation of
    the same closed bar.

Kill-switches:
  CONFIRMATION_FALLBACK_ENABLED   "0" (default OFF) — never evaluated.
  CONFIRMATION_FALLBACK_SHADOW    "1" (default ON ) — when ENABLED=1 the
                                  sequencer runs and writes
                                  logs/confirmation_fallback.jsonl, but
                                  evaluate() returns None instead of a
                                  StrategyDecision, so execute_trade is
                                  never called. Flip SHADOW=0 to trade
                                  live once the JSONL trace looks right.

Known gaps (v1):
  - No spread gate. The live entry path has no spread filter (verified
    2026-06-28). If wide-spread sweeps show up as a problem in real
    fills, a gate gets added here — not assumed elsewhere.
  - No runner trail. GBPUSD_CONFIRMATION_FALLBACK_L/S is NOT in any of
    trade_manager's *_TRAIL_MODES allowlists, so v1 is scale-out (+8p/50%)
    + runner-to-BE only. Adding a trail = explicit allowlist entry.
  - Equal-highs / equal-lows are NOT v1 level inputs (no extractor exists
    in level_computation).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_confirmation_fallback")

LOG_TAG = "CONFIRMATION_FALLBACK"

MODE_NAME_LONG  = "GBPUSD_CONFIRMATION_FALLBACK_L"
MODE_NAME_SHORT = "GBPUSD_CONFIRMATION_FALLBACK_S"

PIP_SIZE = 1.0  # GBPUSD TODAY epic, mirrors other strategies in this repo.


# ─── env helpers ───────────────────────────────────────────────────────────
def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# ─── KILL-SWITCH (must remain the first runtime-relevant constants) ────────
# Default OFF — nothing fires until the operator flips this.
ENABLED = _env_bool("CONFIRMATION_FALLBACK_ENABLED", "0")
_REGIME_MATRIX_ENABLED = _env_bool("REGIME_MATRIX_ENABLED", "0")
# Default SHADOW=1 — when ENABLED is later flipped on, the first runs
# write JSONL telemetry only; live trading needs SHADOW=0 too.
SHADOW  = _env_bool("CONFIRMATION_FALLBACK_SHADOW",  "1")


# ─── Session window (UTC, weekdays only) — mirrors BB_BOUNCE idiom ─────────
WIN_START = dtime(_env_int("CONFIRMATION_FALLBACK_WIN_START_H", 6),  0)
WIN_END   = dtime(_env_int("CONFIRMATION_FALLBACK_WIN_END_H",   17), 0)


# ─── Sequencer params ──────────────────────────────────────────────────────
SEQUENCE_MAX_BARS = _env_int("CONFIRMATION_FALLBACK_SEQUENCE_MAX_BARS", 6)
COOLDOWN_BARS     = _env_int("CONFIRMATION_FALLBACK_COOLDOWN_BARS", 12)   # 60 min
WARMUP_BARS       = _env_int("CONFIRMATION_FALLBACK_WARMUP_BARS",   30)

# Only sweep levels that are within this distance of current price. Stops
# the strategy chasing a 200p-away PDH on a quiet morning.
LEVEL_MAX_DIST_PIPS = _env_float("CONFIRMATION_FALLBACK_LEVEL_MAX_DIST_PIPS", 30.0)


# ─── Risk geometry ─────────────────────────────────────────────────────────
# SL: just beyond the sweep extreme (the lowest low of the sweep bar for
# BUY, or the highest high for SELL) by SL_BUFFER_PIPS, then clamp to
# [MIN_SL_PIPS, MAX_SL_PIPS]. MIN_SL_PIPS=12 is the IG broker floor for
# GBPUSD. Hard-coded "15p max" caps from any external design doc are
# ignored — those values are wrong for this pair.
SL_BUFFER_PIPS = _env_float("CONFIRMATION_FALLBACK_SL_BUFFER_PIPS", 2.0)
MIN_SL_PIPS    = _env_float("CONFIRMATION_FALLBACK_MIN_SL_PIPS",   12.0)
MAX_SL_PIPS    = _env_float("CONFIRMATION_FALLBACK_MAX_SL_PIPS",   30.0)

# Broker TP cap. Real exit is downstream: trade_manager._scale_out_50pct
# fires at +SCALE_OUT_TRIGGER_PIPS, then runner sits at BE (this mode is
# not in any trade_manager *_TRAIL_MODES allowlist for v1).
RUNNER_TP_PIPS = _env_float("CONFIRMATION_FALLBACK_RUNNER_TP_PIPS", 80.0)


# ─── Liquidity level tags we accept from level_computation ─────────────────
# Vocab tags from level_computation._CATEGORY_TO_VOCAB_TAG:
#   sell-side levels (BELOW price, BUY-direction sweep candidates) ──
_BUY_SIDE_TAGS  = frozenset({"PREV_DAY_LOW",  "ASIAN_LOW",  "SWING_LOW"})
#   buy-side levels (ABOVE price, SELL-direction sweep candidates) ──
_SELL_SIDE_TAGS = frozenset({"PREV_DAY_HIGH", "ASIAN_HIGH", "SWING_HIGH"})


# ─── Regime self-gate — strategy is ACTIVE when regime is NOT trending ─────
# Anything outside this set (CHOP, COMPRESSION, RANGE_ROTATION,
# VOLATILITY_EXPANSION, BREAKOUT_FORMING_*, None, unknown) → strategy
# runs. When regime IS trending, EMA_PULLBACK / structure_break own the
# bar — this strategy stands down.
_TRENDING_REGIMES = frozenset({
    "STRONG_TREND_UP",  "STRONG_TREND_DOWN",
    "TREND_FORMING_UP", "TREND_FORMING_DOWN",
})


# ─── Shadow / telemetry JSONL ──────────────────────────────────────────────
SHADOW_LOG_PATH = os.getenv(
    "CONFIRMATION_FALLBACK_LOG_PATH",
    "/opt/tradingbot/logs/confirmation_fallback.jsonl",
)
_shadow_lock = threading.Lock()


def _write_shadow(rec: Dict[str, Any]) -> None:
    """Append one JSONL row. Never raises — telemetry failures must not
    affect the sequencer or the trade path."""
    try:
        d = os.path.dirname(SHADOW_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _shadow_lock:
            with open(SHADOW_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[%s] shadow write failed: %s", LOG_TAG, exc)


# ─── Bar dataclass (mirrors gbpusd_bb_bounce.Bar) ──────────────────────────
@dataclass
class Bar:
    """A closed 5M candle. `timestamp` is tz-aware UTC."""
    timestamp: datetime
    open:  float
    high:  float
    low:   float
    close: float


# ─── Regime read (mirrors gbpusd_ema_pullback._ema_pb_read_regime_label) ───
def _read_regime_label(symbol: str) -> Optional[str]:
    """Read winning_regime from regime_engine.latest_result. Returns None
    on any failure — caller treats None as 'no trending regime asserted',
    which means this strategy is ELIGIBLE (we run in the negative-of-trend
    bucket). This is the inverse of EMA_PULLBACK's fail-CLOSED rule: there
    the regime gate is required to assert; here a missing regime is
    legitimate stand-down territory and the strategy still runs."""
    try:
        import regime_engine as _re
        r = _re.latest_result(symbol) or {}
    except Exception as exc:
        logger.warning(
            "[%s] regime_engine.latest_result failed: %s — treating as non-trending",
            LOG_TAG, exc,
        )
        return None
    w = r.get("winning_regime")
    return str(w).upper() if w else None


def _regime_is_trending(label: Optional[str]) -> bool:
    """True iff label is one of the four trending labels."""
    return label is not None and label.upper() in _TRENDING_REGIMES


# ─── News blackout passthrough — uses the shared release-window suppressor ─
def _news_blackout(now_utc: datetime) -> Tuple[bool, str]:
    try:
        from news_release_window import is_in_release_window
        return is_in_release_window(now_utc)
    except Exception as exc:
        # Suppressor failure → fail-OPEN per news_release_window.py contract.
        logger.debug("[%s] news_release_window import/eval failed: %s", LOG_TAG, exc)
        return False, ""


# ─── Level selection — reuse level_computation, do NOT re-derive ───────────
def _select_liquidity_levels(
    symbol: str,
    now_utc: datetime,
    current_close: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (below_levels, above_levels), each a list of
        {"price": float, "label": str, "tags": List[str]}
    sorted by closeness to current_close. Filtered to the
    CONFIRMATION_FALLBACK_LEVEL_MAX_DIST_PIPS band.

    Reuses level_computation.get_ranked_levels — does NOT re-derive PDH/
    PDL / Asian H-L / H1 swings here.
    """
    try:
        import level_computation as _lc
        levels, _meta = _lc.get_ranked_levels(symbol, now_utc=now_utc)
    except Exception as exc:
        logger.debug("[%s] get_ranked_levels failed: %s", LOG_TAG, exc)
        return [], []

    below: List[Dict[str, Any]] = []
    above: List[Dict[str, Any]] = []
    max_dist_px = float(LEVEL_MAX_DIST_PIPS) * PIP_SIZE
    for lv in levels or []:
        try:
            price = float(getattr(lv, "price"))
            tags  = list(getattr(lv, "confluence", []) or [])
        except Exception:
            continue
        dist = abs(price - current_close)
        if dist > max_dist_px:
            continue
        tag_set = {str(t).upper() for t in tags}
        rec = {"price": price, "tags": sorted(tag_set), "label": ",".join(sorted(tag_set))}
        if price < current_close and (tag_set & _BUY_SIDE_TAGS):
            below.append(rec)
        elif price > current_close and (tag_set & _SELL_SIDE_TAGS):
            above.append(rec)
    below.sort(key=lambda r: current_close - r["price"])  # nearest first
    above.sort(key=lambda r: r["price"] - current_close)
    return below, above


# ─── Strategy class — singleton, mirrors BB_BOUNCE structure ───────────────
class GbpUsdConfirmationFallbackStrategy:
    """Per-epic sweep / reclaim / confirm sequencer.

    State machine (BUY direction — SELL is the mirror):

        phase=NONE
          on every closed bar:
            * detect sweep: bar.low < some level in `below_levels`.
              If found → store armed state with phase=SWEPT,
                          level_price, level_label, sweep_bar_ts,
                          sweep_low.

        phase=SWEPT
          age_bars = #closed bars elapsed since sweep (exclusive).
          on every closed bar:
            * if age_bars > SEQUENCE_MAX_BARS  → abandon (phase=NONE).
            * else if bar.close > level_price  → phase=RECLAIMED,
                                                  reclaim_bar_ts=current.
            * (fall-through to RECLAIMED checks below WITHIN THE SAME bar
              call, so an instant-reclaim-AND-confirm bar fires the same
              bar — no lookahead, the bar is already closed.)

        phase=RECLAIMED
          on every closed bar (including the reclaim bar itself):
            * if age_bars > SEQUENCE_MAX_BARS  → abandon.
            * else if bar.close <= level_price → abandon (lost reclaim).
            * else if bar.close > bar.open AND bar.close > level_price
                                              → FIRE.
    """

    _instance: Optional["GbpUsdConfirmationFallbackStrategy"] = None

    @classmethod
    def instance(cls) -> "GbpUsdConfirmationFallbackStrategy":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        # epic → armed state dict (see _arm_sweep for shape).
        self._armed: Dict[str, Dict[str, Any]] = {}
        # epic → last evaluated bar.timestamp (dedup).
        self._last_eval_bar: Dict[str, datetime] = {}
        # epic → last FIRE bar.timestamp (cooldown).
        self._last_fire_bar: Dict[str, datetime] = {}

    # ── helpers ────────────────────────────────────────────────────────────
    def _in_window(self, ts_utc: datetime) -> bool:
        ts = ts_utc.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return WIN_START <= t < WIN_END

    def _cooldown_ok(self, epic: str, ts: datetime) -> bool:
        last = self._last_fire_bar.get(epic)
        if last is None:
            return True
        return (ts - last).total_seconds() >= COOLDOWN_BARS * 300.0

    def _bars_between(self, prev: datetime, cur: datetime) -> int:
        try:
            return max(0, int((cur - prev).total_seconds() // 300))
        except Exception:
            return 0

    # ── sequencer phase detectors ─────────────────────────────────────────
    def _detect_sweep(
        self,
        bar: Bar,
        below_levels: List[Dict[str, Any]],
        above_levels: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return armed-state dict on sweep, else None.

        BUY sweep: bar.low pierces a below-current level (bar.low < level.price)
        SELL sweep: bar.high pierces an above-current level (bar.high > level.price)

        Prefers the NEAREST level. Does not require a directional close
        on the sweep bar — the close direction is judged at reclaim/confirm.
        """
        # BUY sweep candidates
        for lv in below_levels:
            if bar.low < lv["price"]:
                return {
                    "direction":     "BUY",
                    "phase":         "SWEPT",
                    "level_price":   float(lv["price"]),
                    "level_label":   str(lv["label"] or "below"),
                    "sweep_bar_ts":  bar.timestamp,
                    "sweep_extreme": float(bar.low),
                    "reclaim_bar_ts": None,
                }
        # SELL sweep candidates
        for lv in above_levels:
            if bar.high > lv["price"]:
                return {
                    "direction":     "SELL",
                    "phase":         "SWEPT",
                    "level_price":   float(lv["price"]),
                    "level_label":   str(lv["label"] or "above"),
                    "sweep_bar_ts":  bar.timestamp,
                    "sweep_extreme": float(bar.high),
                    "reclaim_bar_ts": None,
                }
        return None

    def _detect_reclaim(self, armed: Dict[str, Any], bar: Bar) -> bool:
        """Reclaim test: bar.close back across the swept level."""
        if armed["direction"] == "BUY":
            return bar.close > armed["level_price"]
        return bar.close < armed["level_price"]

    def _detect_confirm(self, armed: Dict[str, Any], bar: Bar) -> bool:
        """OWN confirmation — do NOT use confirmation_engine. The
        confirmation bar must (a) hold the reclaim — close on the right
        side of the swept level — AND (b) print a body in the trade
        direction (close > open for BUY, close < open for SELL)."""
        if armed["direction"] == "BUY":
            return (bar.close > armed["level_price"]) and (bar.close > bar.open)
        return (bar.close < armed["level_price"]) and (bar.close < bar.open)

    def _invalidates_reclaim(self, armed: Dict[str, Any], bar: Bar) -> bool:
        """After reclaim, a subsequent bar closing back across the level
        invalidates the setup. Symmetric for SELL."""
        if armed["direction"] == "BUY":
            return bar.close <= armed["level_price"]
        return bar.close >= armed["level_price"]

    # ── public evaluate (called per closed 5M bar by autobot) ─────────────
    def evaluate(self,
                 symbol: str,
                 epic: str,
                 ts: datetime,
                 bars: Sequence[Bar],
                 has_open_long: bool = False,
                 has_open_short: bool = False,
                 ) -> Optional["StrategyDecision"]:
        """Called by autobot on each new 5M close for GBPUSD."""
        if not ENABLED or str(symbol).upper() != "GBPUSD":
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

        if not self._in_window(ts):
            return None

        if not self._cooldown_ok(epic, ts):
            return None

        if not bars or len(bars) < max(2, WARMUP_BARS // 6):
            return None

        # Per-epic per-bar dedup. Critical for non-repaint: never advance
        # the state machine twice on the same closed bar.
        last_seen = self._last_eval_bar.get(epic)
        if last_seen is not None and bars[-1].timestamp <= last_seen:
            return None
        self._last_eval_bar[epic] = bars[-1].timestamp

        # ── Regime self-gate ──────────────────────────────────────────────
        # Legacy role: fire only in non-trending regimes; disarm setups when
        # a trend emerges. Under REGIME_MATRIX_ENABLED=1 this role inverts —
        # matrix assigns CF to trending regimes and owns dispatch. The
        # disarm-on-transition invariant is preserved via a matrix
        # on-suppress callback registered at module load (see bottom of
        # file); this local block is bypassed under the flag.
        regime = _read_regime_label(symbol)
        if _regime_is_trending(regime) and not _REGIME_MATRIX_ENABLED:
            _write_shadow({
                "ts": ts.isoformat(),
                "epic": epic,
                "phase": "STAND_DOWN",
                "reason": "regime_trending",
                "regime": regime,
            })
            # Clear any armed state — a trend has emerged, this strategy
            # is no longer the right tool for this bar.
            self._armed.pop(epic, None)
            return None

        # ── News blackout ─────────────────────────────────────────────────
        is_black, why = _news_blackout(ts)
        if is_black:
            _write_shadow({
                "ts": ts.isoformat(),
                "epic": epic,
                "phase": "STAND_DOWN",
                "reason": "news_blackout",
                "why": why,
            })
            return None

        cur = bars[-1]
        current_close = float(cur.close)

        # ── State machine ────────────────────────────────────────────────
        armed = self._armed.get(epic)

        # phase = NONE → look for sweep
        if armed is None:
            # Slot interlock: if an existing CONFIRMATION_FALLBACK position
            # is open on the epic (either side), do not arm a new sequence.
            if has_open_long or has_open_short:
                return None
            below, above = _select_liquidity_levels(symbol, ts, current_close)
            new_armed = self._detect_sweep(cur, below, above)
            if new_armed is None:
                return None
            self._armed[epic] = new_armed
            _write_shadow({
                "ts": ts.isoformat(),
                "epic": epic,
                "phase": "SWEPT",
                "direction": new_armed["direction"],
                "level_price": new_armed["level_price"],
                "level_label": new_armed["level_label"],
                "sweep_bar_ts": new_armed["sweep_bar_ts"].isoformat(),
                "sweep_extreme": new_armed["sweep_extreme"],
                "regime": regime,
            })
            # Reclaim must be a SUBSEQUENT bar per spec ("a subsequent bar
            # closes back above the swept level"). Even if the sweep bar
            # itself closed back across the level, we do NOT transition
            # to RECLAIMED on this call — wait for the next 5M close.
            return None

        # Sequence expiry — bars elapsed since the sweep bar (exclusive).
        age = self._bars_between(armed["sweep_bar_ts"], cur.timestamp)
        if age > SEQUENCE_MAX_BARS:
            _write_shadow({
                "ts": ts.isoformat(),
                "epic": epic,
                "phase": "ABANDONED_EXPIRY",
                "direction": armed["direction"],
                "level_price": armed["level_price"],
                "age_bars": age,
                "max_bars": SEQUENCE_MAX_BARS,
            })
            self._armed.pop(epic, None)
            return None

        # phase = SWEPT → look for reclaim on a SUBSEQUENT bar
        if armed["phase"] == "SWEPT":
            if cur.timestamp == armed["sweep_bar_ts"]:
                # Same bar as sweep; reclaim must wait for a subsequent
                # bar (per the spec: "a subsequent bar closes back…").
                return None
            if self._detect_reclaim(armed, cur):
                armed["phase"] = "RECLAIMED"
                armed["reclaim_bar_ts"] = cur.timestamp
                _write_shadow({
                    "ts": ts.isoformat(),
                    "epic": epic,
                    "phase": "RECLAIMED",
                    "direction": armed["direction"],
                    "level_price": armed["level_price"],
                    "reclaim_bar_ts": cur.timestamp.isoformat(),
                })
            else:
                # Still waiting for reclaim.
                return None

        # phase = RECLAIMED → look for confirmation
        if armed["phase"] == "RECLAIMED":
            # If a later bar closes back across the swept level, abandon.
            if (armed.get("reclaim_bar_ts") is not None
                    and cur.timestamp > armed["reclaim_bar_ts"]
                    and self._invalidates_reclaim(armed, cur)):
                _write_shadow({
                    "ts": ts.isoformat(),
                    "epic": epic,
                    "phase": "ABANDONED_RECLAIM_LOST",
                    "direction": armed["direction"],
                    "level_price": armed["level_price"],
                })
                self._armed.pop(epic, None)
                return None
            if self._detect_confirm(armed, cur):
                return self._fire(symbol, epic, ts, cur, armed,
                                  has_open_long, has_open_short, regime)

        return None

    # ── FIRE — build StrategyDecision and clear armed state ───────────────
    def _fire(self,
              symbol: str,
              epic: str,
              ts: datetime,
              cur: Bar,
              armed: Dict[str, Any],
              has_open_long: bool,
              has_open_short: bool,
              regime: Optional[str],
              ) -> Optional["StrategyDecision"]:
        direction = armed["direction"]  # "BUY" or "SELL"
        mode = MODE_NAME_LONG if direction == "BUY" else MODE_NAME_SHORT
        entry = float(cur.close)
        sweep_ext = float(armed["sweep_extreme"])
        level     = float(armed["level_price"])

        # SL: just beyond the sweep extreme. The sweep extreme is the
        # lowest low of the sweep bar (BUY) or highest high (SELL).
        if direction == "BUY":
            raw_sl_pips = (entry - sweep_ext) / PIP_SIZE + SL_BUFFER_PIPS
        else:
            raw_sl_pips = (sweep_ext - entry) / PIP_SIZE + SL_BUFFER_PIPS
        sl_pips = max(MIN_SL_PIPS, min(MAX_SL_PIPS, raw_sl_pips))
        tp_pips = float(RUNNER_TP_PIPS)

        reason = (
            f"confirmation_fallback {'buy' if direction == 'BUY' else 'sell'} "
            f"sweep={armed['level_label']}@{level:.5f} "
            f"sweep_extreme={sweep_ext:.5f} entry={entry:.5f} "
            f"sl_pips={sl_pips:.1f} regime={regime or 'None'}"
        )

        shadow_row = {
            "ts": ts.isoformat(),
            "epic": epic,
            "phase": "FIRE" if not SHADOW else "WOULD_FIRE",
            "direction": direction,
            "mode": mode,
            "entry": entry,
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "level_price": level,
            "level_label": armed["level_label"],
            "sweep_extreme": sweep_ext,
            "sweep_bar_ts": armed["sweep_bar_ts"].isoformat(),
            "reclaim_bar_ts":
                armed["reclaim_bar_ts"].isoformat() if armed.get("reclaim_bar_ts") else None,
            "regime": regime,
        }
        _write_shadow(shadow_row)

        # Clear armed state regardless of shadow vs live — the sequence
        # has resolved.
        self._armed.pop(epic, None)
        # Stamp cooldown only when a real fire would happen.
        self._last_fire_bar[epic] = cur.timestamp

        if SHADOW:
            logger.info(
                "[%s] %s WOULD_FIRE @ %.5f | SL=%.1fp TP=%.0fp | %s",
                LOG_TAG, direction, entry, sl_pips, tp_pips, reason,
            )
            return None

        # Slot interlock — same defensive check that BB_BOUNCE / SB do.
        # Without this, a stale state could open a second leg.
        if (direction == "BUY" and has_open_long) or \
           (direction == "SELL" and has_open_short):
            logger.info(
                "[%s] %s fire suppressed: open %s position already exists",
                LOG_TAG, direction, direction,
            )
            return None

        # Build StrategyDecision (lazy import — same pattern BB_BOUNCE uses).
        try:
            from strategy_logic import StrategyDecision
        except Exception as exc:
            logger.error("[%s] StrategyDecision import failed: %s", LOG_TAG, exc)
            return None

        debug = {
            "strategy": LOG_TAG,
            "regime_at_fire": regime,
            "level_price": level,
            "level_label": armed["level_label"],
            "sweep_extreme": sweep_ext,
            "sweep_bar_ts": armed["sweep_bar_ts"].isoformat(),
            "reclaim_bar_ts":
                armed["reclaim_bar_ts"].isoformat() if armed.get("reclaim_bar_ts") else None,
            "fire_bar_ts": cur.timestamp.isoformat(),
            "sl_components": {
                "raw_sl_pips":    round(raw_sl_pips, 3),
                "buffer_pips":    SL_BUFFER_PIPS,
                "clamped_sl_pips": round(sl_pips, 3),
                "min_sl_pips":    MIN_SL_PIPS,
                "max_sl_pips":    MAX_SL_PIPS,
            },
        }
        decision = StrategyDecision(
            symbol="GBPUSD",
            regime=LOG_TAG,
            signal=direction,
            mode=mode,
            entry=entry,
            sl=round(sl_pips, 2),
            tp=round(tp_pips, 2),
            use_trailing_stop=False,
            reason=reason,
            debug=debug,
            pip_size=PIP_SIZE,
        )
        logger.info(
            "[%s] %s ENTRY @ %.5f | SL=%.1fp TP=%.0fp | %s",
            LOG_TAG, direction, entry, sl_pips, tp_pips, reason,
        )
        return decision


# ─── Module-level singleton + dispatch helper (mirrors BB_BOUNCE) ──────────
strategy = GbpUsdConfirmationFallbackStrategy.instance()


def evaluate(*args, **kwargs):  # pragma: no cover — thin pass-through
    return strategy.evaluate(*args, **kwargs)


# Preserve the armed-state disarm invariant under the matrix. The legacy
# gate at evaluate() disarms setups when regime turns trending; under
# REGIME_MATRIX_ENABLED=1 the gate is bypassed, so the disarm is
# reinstated via a matrix on-suppress callback that fires when either CF
# mode leaves the effective_regime's permitted set on a transition.
def _cf_matrix_disarm(_symbol):  # pragma: no cover — exercised by test
    """Clear all armed CF setups on any matrix suppression event for this
    strategy. Safe to call more than once; idempotent.
    """
    try:
        strategy._armed.clear()
    except Exception:
        pass


if _REGIME_MATRIX_ENABLED:
    try:
        import regime_matrix as _rm
        _rm.register_on_suppress(MODE_NAME_LONG, _cf_matrix_disarm)
        _rm.register_on_suppress(MODE_NAME_SHORT, _cf_matrix_disarm)
    except Exception:
        # regime_matrix is a Phase 2 dependency; missing it means the
        # legacy path (flag off) is in effect and no callback is required.
        pass


__all__ = [
    "ENABLED",
    "SHADOW",
    "MODE_NAME_LONG",
    "MODE_NAME_SHORT",
    "Bar",
    "GbpUsdConfirmationFallbackStrategy",
    "strategy",
    "evaluate",
]
