"""briefing.v5_pia.executor — Phase 3 trading executor.

Reads v5_pia briefings via `reader.py`, watches per-tick price, and fires
one `StrategyDecision` per briefing when price approaches the committed
entry within a configurable tolerance.

Architectural contract (per `briefing/v5_pia/PHASE1_README.md`):

  - Lives entirely in `briefing/v5_pia/`. Does NOT touch v4
    `briefing_execution.py` or `morning_briefing.py`.
  - Runs on the per-pair-worker thread (PRs #8/#9/#10) via integration
    point in `strategy_logic.evaluate_signals`. The LS callback thread
    only enqueues to the worker; the worker thread invokes
    `evaluate_signals` which invokes this module — fully off the LS
    event-dispatch thread.
  - Gated by `BRIEFING_V5_PARALLEL_MODE` (default 0). When 0 the
    executor is fully inert. When 1 it runs alongside v4; both can
    fire independently within the BRIEFING_MAX_CONCURRENT_LEGS cap.
  - Honours `BRIEFING_EXECUTION_MIN_CONFIDENCE` (default 70). A briefing
    that would otherwise fire is suppressed when confidence < threshold.
  - Honours `BRIEFING_MAX_CONCURRENT_LEGS` (default 2) by counting
    open positions in EPIC_STATE whose mode starts with "BRIEFING_".

Dedup model:

  Per-briefing identity is `(pair, session, generated_at_utc)`. Once a
  briefing has fired, the (pair, briefing-id) pair is recorded; further
  ticks against the same briefing are no-ops, including ticks AFTER the
  position closes (one fire per briefing per spec).

Public API:

  V5_EXECUTOR.evaluate_tick(pair, epic, mid_price, pip_size,
                            now_utc=None) -> Optional[StrategyDecision]
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from briefing.v5_pia.config import (
    BRIEFING_EXECUTION_MIN_CONFIDENCE,
    BRIEFING_MAX_CONCURRENT_LEGS,
    BRIEFING_V5_PARALLEL_MODE,
)
from briefing.v5_pia.reader import (
    is_briefing_active,
    is_briefing_armed,
    load_active_v5_briefing,
)
from briefing.v5_pia.schema import BriefingV5

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────────────

# Entry-zone half-width in pips. Price within ±N pips of briefing.entry
# triggers a fire. Tunable per-deploy; default ±2 matches PIAfirst's
# typical tolerance and the audit's recommended starting point.
def _entry_tol_pips() -> float:
    raw = os.getenv("V5_EXECUTOR_ENTRY_TOL_PIPS", "2.0") or "2.0"
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 2.0


# Strategy mode written to signal_log. Distinct from v4's
# "BRIEFING_EXECUTION" so journalctl + dashboards can filter cleanly.
STRATEGY_MODE = "BRIEFING_V5"


# ─────────────────────────────────────────────────────────────────────────────
# Open-leg counter — used for BRIEFING_MAX_CONCURRENT_LEGS
# ─────────────────────────────────────────────────────────────────────────────

def _count_open_briefing_legs() -> int:
    """Return the number of currently-open positions whose mode starts
    with 'BRIEFING_'. Counts BOTH v4 (BRIEFING_EXECUTION) and v5
    (BRIEFING_V5) so the cap is shared per the user spec ('v5 fires
    count toward the same limit as v4 fires').

    Reads `trade_executor.EPIC_STATE` under EPIC_STATE_LOCK — same
    iteration discipline as `count_open_positions_by_pair_direction`.
    Counts both committed (active=True) and just-staged
    (pending_open=True), matching the "if I add another, would the cap
    be exceeded?" semantics of the existing pair-cap check.
    """
    try:
        from trade_executor import EPIC_STATE, EPIC_STATE_LOCK
    except Exception as exc:
        logger.warning("[v5-exec] EPIC_STATE import failed: %s — assuming 0 legs", exc)
        return 0

    count = 0
    with EPIC_STATE_LOCK:
        items = list(EPIC_STATE.items())
    for _k, st in items:
        if not (st.get("active") or st.get("pending_open")):
            continue
        mode = str(st.get("mode") or "").strip().upper()
        if mode.startswith("BRIEFING_"):
            count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────────
# StrategyDecision builder — converts briefing prices to pip distances
# ─────────────────────────────────────────────────────────────────────────────

def _build_decision(
    *,
    pair: str,
    briefing: BriefingV5,
    mid_price: float,
    pip_size: float,
    briefing_id: str,
):
    """Construct a StrategyDecision matching v4's contract. signal_logger
    interprets `decision.sl` and `decision.tp` as PIP DISTANCES (not
    prices) — convert briefing.stop / briefing.target accordingly.
    """
    # Local import to avoid circular: strategy_logic imports
    # briefing_execution which is allowed; v5 lives outside that ring.
    from strategy_logic import StrategyDecision

    direction = briefing.direction  # BUY or SELL (caller already gated)
    entry_price = float(briefing.entry)
    stop_price = float(briefing.stop)
    target_price = float(briefing.target)

    if direction == "BUY":
        sl_pips = (entry_price - stop_price) / pip_size
        tp_pips = (target_price - entry_price) / pip_size
    else:  # SELL
        sl_pips = (stop_price - entry_price) / pip_size
        tp_pips = (entry_price - target_price) / pip_size

    sl_pips = max(0.0, float(sl_pips))
    tp_pips = max(0.0, float(tp_pips))

    debug: Dict[str, Any] = {
        "pip_size": pip_size,
        "v5_briefing_id": briefing_id,
        "v5_session": briefing.session,
        "v5_generated_at_utc": briefing.generated_at_utc,
        "v5_valid_until_utc": briefing.valid_until_utc,
        "v5_confidence": briefing.confidence,
        "v5_confidence_bucket": briefing.confidence_bucket,
        "v5_briefing_entry": entry_price,
        "v5_briefing_stop": stop_price,
        "v5_briefing_target": target_price,
        "v5_rr": briefing.rr,
        "v5_bias_anchor": briefing.bias_anchor,
        "v5_bias_anchor_label": briefing.bias_anchor_label,
        "v5_stop_structural_level": briefing.stop_structural_level,
        "v5_target_structural_level": briefing.target_structural_level,
    }

    return StrategyDecision(
        symbol=pair,
        regime="BRIEFING_V5",
        signal=direction,
        mode=STRATEGY_MODE,
        entry=mid_price,
        sl=sl_pips,
        tp=tp_pips,
        use_trailing_stop=False,
        reason=(
            f"v5_pia {direction} @ {entry_price:g} ± {_entry_tol_pips():g}p "
            f"conf={briefing.confidence}% ({briefing.confidence_bucket}) "
            f"rr={briefing.rr:.2f}"
        ),
        debug=debug,
        pip_size=pip_size,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Executor — singleton state holds per-pair fire dedup
# ─────────────────────────────────────────────────────────────────────────────

class BriefingV5Executor:
    """Stateful executor — one fire per (pair, briefing-id) per the spec.

    Briefing identity = `f"{pair}|{session}|{generated_at_utc}"`. Once a
    fire has been recorded for a briefing, subsequent ticks against the
    same briefing return None (no re-fires even after the position
    closes). Fires for different briefings are independent.

    State is in-memory; no on-disk persistence. A process restart
    clears the dedup map. That's intentional: at restart, the position
    state is recovered from the broker, and the dedup re-arms only if
    the same briefing re-fires within its valid window. This mirrors
    v4's `_entered` flag behaviour.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # pair → briefing_id of the most-recently-fired briefing
        self._fired: Dict[str, str] = {}
        # (briefing_id, reason_key) set to dedup abstain log lines so
        # journalctl gets one INFO per reason per briefing, not per tick.
        self._abstain_logged: set = set()

    @staticmethod
    def _briefing_id(briefing: BriefingV5) -> str:
        return f"{briefing.pair.upper()}|{briefing.session}|{briefing.generated_at_utc}"

    def _has_fired(self, pair: str, briefing_id: str) -> bool:
        with self._lock:
            return self._fired.get(pair.upper()) == briefing_id

    def _mark_fired(self, pair: str, briefing_id: str) -> None:
        with self._lock:
            self._fired[pair.upper()] = briefing_id

    # ------------------------------------------------------------------
    # Per-tick entry point
    # ------------------------------------------------------------------
    def evaluate_tick(
        self,
        pair: str,
        epic: str,
        mid_price: float,
        pip_size: float,
        now_utc: Optional[datetime] = None,
        df_5m: Any = None,
    ):
        """Per-tick gate sequence. Returns a StrategyDecision when ALL
        gates pass and price is in the entry zone; otherwise None.

        Gate order (cheapest first; each abstain logs its reason):
          1. BRIEFING_V5_PARALLEL_MODE off              → silent return
          2. No active briefing for pair                → debug log
          3. Briefing past valid_until_utc              → info log
          4. Briefing not ARMED (STAND_ASIDE)           → info log (once per briefing-id)
          5. Briefing confidence < MIN_CONFIDENCE       → info log (once per briefing-id)
          6. Already fired this briefing                → debug log
          7. BRIEFING_MAX_CONCURRENT_LEGS reached       → info log
          8. Price not in entry zone (±tol pips)        → debug log
          → fire
        """
        if not BRIEFING_V5_PARALLEL_MODE:
            return None

        when = now_utc or datetime.now(tz=timezone.utc)
        pair_u = pair.upper()

        briefing = load_active_v5_briefing(pair_u, when)
        if briefing is None:
            logger.debug("[v5-exec] %s no active v5 briefing", pair_u)
            return None

        bid = self._briefing_id(briefing)

        if not is_briefing_active(briefing, when):
            logger.info(
                "[v5-exec] %s briefing %s expired (valid_until=%s, now=%s) — abstain",
                pair_u, bid, briefing.valid_until_utc, when.isoformat(),
            )
            return None

        if not is_briefing_armed(briefing):
            self._log_once_per_briefing(
                bid, "stand_aside",
                "[v5-exec] %s briefing %s STAND_ASIDE (state=%s direction=%s reason=%s) — abstain",
                pair_u, bid, briefing.state, briefing.direction,
                briefing.stand_aside_reason or "n/a",
            )
            return None

        if briefing.confidence < BRIEFING_EXECUTION_MIN_CONFIDENCE:
            self._log_once_per_briefing(
                bid, "low_conf",
                "[v5-exec] %s briefing %s confidence=%d%% below MIN=%d%% — abstain",
                pair_u, bid, briefing.confidence, BRIEFING_EXECUTION_MIN_CONFIDENCE,
            )
            return None

        if self._has_fired(pair_u, bid):
            logger.debug(
                "[v5-exec] %s briefing %s already fired — abstain", pair_u, bid,
            )
            return None

        open_legs = _count_open_briefing_legs()
        if open_legs >= BRIEFING_MAX_CONCURRENT_LEGS:
            self._log_once_per_briefing(
                bid, "max_legs",
                "[v5-exec] %s briefing %s blocked: open_briefing_legs=%d >= cap=%d",
                pair_u, bid, open_legs, BRIEFING_MAX_CONCURRENT_LEGS,
            )
            return None

        # Entry-zone check: |mid_price - briefing.entry| <= tolerance
        tol_pips = _entry_tol_pips()
        tol_price = tol_pips * float(pip_size or 1.0)
        try:
            entry_price = float(briefing.entry)
        except (TypeError, ValueError):
            logger.warning(
                "[v5-exec] %s briefing %s ARMED but entry=%r non-numeric — abstain",
                pair_u, bid, briefing.entry,
            )
            return None

        if abs(mid_price - entry_price) > tol_price:
            logger.debug(
                "[v5-exec] %s briefing %s mid=%.5f entry=%.5f distance=%.2fp tol=%.2fp — wait",
                pair_u, bid, mid_price, entry_price,
                abs(mid_price - entry_price) / float(pip_size or 1.0), tol_pips,
            )
            return None

        # ── Fire ──────────────────────────────────────────────────────
        decision = _build_decision(
            pair=pair_u,
            briefing=briefing,
            mid_price=mid_price,
            pip_size=pip_size,
            briefing_id=bid,
        )

        # Mark fired BEFORE returning so a concurrent re-tick on the same
        # briefing can't double-fire. trade_executor.execute_trade is what
        # actually places the order — if that fails, the briefing is still
        # marked fired (we don't retry within the same briefing window;
        # the next briefing arrival re-arms naturally).
        self._mark_fired(pair_u, bid)

        logger.info(
            "[v5-exec] %s FIRE %s briefing=%s mid=%.5f entry=%.5f stop=%.5f target=%.5f "
            "sl_pips=%.1f tp_pips=%.1f conf=%d%% (%s) rr=%.2f open_legs=%d/%d",
            pair_u, briefing.direction, bid, mid_price,
            entry_price, briefing.stop, briefing.target,
            decision.sl, decision.tp,
            briefing.confidence, briefing.confidence_bucket, briefing.rr,
            open_legs, BRIEFING_MAX_CONCURRENT_LEGS,
        )

        # Forensic snapshot — soft-fail. Lives inside the executor so
        # signal_log JOIN to forensic_fires.jsonl resolves on
        # strategy="BRIEFING_V5".
        try:
            from forensic_logger import capture_fire_from_df
            capture_fire_from_df(
                sym=pair_u,
                strategy=STRATEGY_MODE,
                direction=briefing.direction,
                entry_price=mid_price,
                df_5m=df_5m,
                pip_size=pip_size,
                fire_path=f"v5_pia/{briefing.session.lower()}/{briefing.confidence_bucket.lower()}",
            )
        except Exception as exc:
            logger.warning(
                "[v5-exec] %s forensic capture failed: %s: %s",
                pair_u, type(exc).__name__, exc,
            )

        return decision

    # ------------------------------------------------------------------
    # Diagnostic accessors
    # ------------------------------------------------------------------
    def fired_briefings_snapshot(self) -> Dict[str, str]:
        """Snapshot of pair → fired-briefing-id (read-only copy)."""
        with self._lock:
            return dict(self._fired)

    # ------------------------------------------------------------------
    # Once-per-briefing log dedup
    # ------------------------------------------------------------------
    # Avoid spamming journalctl with a STAND_ASIDE reason on every tick.
    # Log once per (briefing_id, reason_key) and rely on the operator to
    # consult the briefing JSON for full context.
    def _log_once_per_briefing(self, briefing_id: str, reason_key: str,
                                msg: str, *args: Any) -> None:
        log_key = f"{briefing_id}::{reason_key}"
        with self._lock:
            if log_key in self._abstain_logged:
                return
            self._abstain_logged.add(log_key)
        logger.info(msg, *args)

# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton (mirrors how v4 holds its strategy on
# evaluate_signals._be_strat — caller can look this up without
# constructing).
# ─────────────────────────────────────────────────────────────────────────────

V5_EXECUTOR = BriefingV5Executor()
