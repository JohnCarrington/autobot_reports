"""
trade_runner.py — IG side of the BB Bounce loop.

Thin wrapper on top of the four copied modules
(ig_auth / ownership_identity / open_sb_now / close_sb_now) that:

  - opens a market trade on a confirmed setup (A11), stamping a
    "HBB-BBB-<epoch10>" dealReference via build_deal_reference
  - records the open to the daily report CSV
  - polls open positions and detects IG-side closes (TP/SL)
  - closes the opposite-direction trade when a confirm fires on the
    other side (A10): new trade is opened FIRST, old trade is then
    closed by its own dealId
  - restores open HBB-prefixed positions at boot (A13)

All IG calls are injected via a ``gateway`` object so tests can
substitute a FakeGateway.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from config import (
    BB_STOP_MODE,
    EPIC,
    MODE_TAG,
    SL_PIPS,
    SYMBOL,
    TP_PIPS,
    TRADE_SIZE,
)
from stop_sizing import plan_stop, StopPlan
from strategy import Dir

logger = logging.getLogger("BBBounce.trade")

# Known-rejection dealStatus / rejectReason values. These are
# DEFINITIVE broker-side rejections — the order did not and will not
# execute. Safe to clear `_pending` and NOT set `_uncertain`.
# Anything OUTSIDE this set is treated as UNKNOWN and promotes the
# direction to "uncertain" state.
#
# 2026-10-27 fix (uncertain-state safety defect): BLOCKED added
# after a live incident where IG returned dealStatus=BLOCKED (its
# risk-system refusal signal — the trade never reached market) and
# the previous code treated that as UNKNOWN. The direction was then
# locked out of further BUY admissions by the admission guard's
# UNCERTAIN_PRIOR_SUBMISSION path. BLOCKED, like REJECTED, is a
# definitive statement from the broker that the order was NOT
# executed.
_KNOWN_IG_REJECTIONS = frozenset({
    "REJECTED",
    "DECLINED",
    "BLOCKED",
    "INSUFFICIENT_FUNDS",
    "MARKET_CLOSED",
    "ATTACHED_ORDER_LEVEL_ERROR",
    "MARKET_OFFLINE",
    "MANUAL_ORDER_TIMEOUT",
    "SIZE_INCREMENT",
})


@dataclass
class Trade:
    direction: Dir
    deal_id: str
    deal_reference: str
    fill_price: float
    tp_level: float
    sl_level: float
    open_time_utc: datetime
    stake: float = TRADE_SIZE
    stop_mode: str = "FIXED_12"
    stop_distance_pips: float = SL_PIPS
    initial_cash_risk_pounds: float = TRADE_SIZE * SL_PIPS


# --------------------------------------------------------------------------
# Gateway interface
# --------------------------------------------------------------------------
# A gateway must provide:
#   open_market(direction: str, mode: str) -> dict | None
#       Confirm dict with 'dealStatus', 'dealId', 'dealReference', 'level'
#   close_by_deal_id(deal_id: str) -> dict | None
#       Confirm dict with 'level' (close price)
#   get_open_positions() -> list[dict] | None
#       List of IG position wrappers {position: {...}, market: {...}}
#   fetch_close_detail(deal_id, direction, open_time, tp_level, sl_level) ->
#       (close_time_utc: datetime, close_price: float, close_type: str)
#       or None
# --------------------------------------------------------------------------


def _tp_sl(direction: Dir, fill: float) -> Tuple[float, float]:
    """Legacy helper — used ONLY by restore_open_positions() for IG state
    reconstruction. New entries go through plan_stop() via _plan_for_setup."""
    if direction is Dir.BUY:
        return fill + TP_PIPS, fill - SL_PIPS
    return fill - TP_PIPS, fill + SL_PIPS


def _plan_for_setup(direction: Dir, fill: float, setup) -> StopPlan:
    """Delegate to stop_sizing.plan_stop with the setup's C1/C2 extremes."""
    c1 = setup.c1
    c2 = setup.c2
    return plan_stop(
        direction=direction, fill=fill,
        c1_low=c1.low if c1 else None, c1_high=c1.high if c1 else None,
        c2_low=c2.low if c2 else None, c2_high=c2.high if c2 else None,
    )


def pips_pnl(direction: Dir, fill: float, close_price: float) -> float:
    delta = close_price - fill
    if direction is Dir.SELL:
        delta = -delta
    # IG stores GBPUSD at the 0.1 pip grid in these units — the delta is
    # already in pips (1 unit = 1 pip). Round to 2 dp of pips to match
    # the 0.1-grid resolution + a safety digit.
    return round(delta, 2)


class TradeRunner:
    """Trade lifecycle manager. Owns the open-trade book and the
    report CSV updates. All IG calls go through ``gateway``.

    ADMISSION GUARD (post-defect-fix):

      self.open_trades[direction]          — IG-confirmed open position
      self._pending[direction]             — order submission in flight
      self._uncertain[direction]           — last submission outcome
                                             unknown (timeout, unknown
                                             IG response); do not retry
                                             until IG confirms absence
      self._restart_reconciliation_pending — True until the first
                                             successful get_open_positions
                                             reply at boot. Blocks ALL
                                             entries until cleared.

    An entry is admitted ONLY if NONE of {open_trades, _pending,
    _uncertain, _restart_reconciliation_pending} would block it. A
    duplicate attempt writes a REJECTED row and NEVER overwrites an
    existing position record.

    A threading.RLock guards all four. The main loop is single-
    threaded today, but check_broker_closes may run in a future thread;
    the lock is cheap insurance.
    """

    def __init__(self, gateway, daily_log, telegram_send):
        self.gw = gateway
        self.daily = daily_log
        self.notify = telegram_send
        self.open_trades: Dict[Dir, Trade] = {}
        self._pending: Set[Dir] = set()
        self._uncertain: Dict[Dir, str] = {}  # direction → reason
        # True until the first successful get_open_positions reply at
        # boot. All entries blocked while True.
        self._restart_reconciliation_pending: bool = True
        self._lock = threading.RLock()

    # ---- Admission guard --------------------------------------
    def _check_admission(self, direction: Dir) -> Optional[str]:
        """Return a human-readable rejection reason if the direction
        is NOT admissible, else None."""
        with self._lock:
            if self._restart_reconciliation_pending:
                return "RESTART_RECONCILIATION_PENDING"
            if direction in self.open_trades:
                return (f"ALREADY_OPEN "
                        f"(dealId={self.open_trades[direction].deal_id})")
            if direction in self._pending:
                return "SUBMISSION_IN_FLIGHT"
            if direction in self._uncertain:
                return (f"UNCERTAIN_PRIOR_SUBMISSION "
                        f"({self._uncertain[direction]})")
            return None

    # ---- Startup restore (A13) ---------------------------------
    def restore_open_positions(self) -> None:
        """Fetch IG positions and populate the book. On success, clear
        the restart-reconciliation gate. On failure (gateway returned
        None or raised), LEAVE THE GATE SET — admissions remain blocked
        until a subsequent successful reconciliation."""
        try:
            raw = self.gw.get_open_positions()
        except Exception as exc:
            logger.error("[restore] get_open_positions raised: %s; "
                         "trading remains blocked.", exc)
            raw = None
        if raw is None:
            # Transient IG failure. DO NOT assume no positions exist.
            logger.error("[restore] get_open_positions returned None; "
                         "assuming reconciliation UNRESOLVED. Trading "
                         "blocked until next successful reconcile.")
            return
        positions = raw
        # Scan FIRST for malformed records on our epic. If any position
        # on our EPIC has a missing/empty dealReference, ownership is
        # AMBIGUOUS — we cannot tell if it is one of ours (and IG
        # didn't echo the reference back) or someone else's. Leave the
        # restart gate SET and bail out. Operator must investigate.
        ambiguous_on_our_epic = 0
        for p in positions:
            pos = p.get("position") or {}
            market = p.get("market") or {}
            if str(market.get("epic") or "") != EPIC:
                continue
            raw_ref = pos.get("dealReference")
            if raw_ref is None or str(raw_ref).strip() == "":
                ambiguous_on_our_epic += 1
                logger.warning(
                    "[restore] AMBIGUOUS position on %s: dealId=%s "
                    "direction=%s openLevel=%s has empty dealReference. "
                    "Cannot establish ownership safely.",
                    EPIC, pos.get("dealId"), pos.get("direction"),
                    pos.get("openLevel"),
                )
        if ambiguous_on_our_epic > 0:
            logger.error(
                "[restore] %d AMBIGUOUS position(s) on %s have no "
                "dealReference. BLOCKING trading until operator resolves. "
                "Restart reconciliation NOT marked complete.",
                ambiguous_on_our_epic, EPIC,
            )
            return

        # Collect HBB-* positions per direction first, so we can detect
        # duplicates. More than one HBB-* position per direction means
        # we previously opened a duplicate (operator must investigate)
        # or an in-flight order was double-submitted. Either way,
        # BLOCK new entries — do not silently pick one.
        hbb_by_direction: Dict[Dir, list] = {}
        for p in positions:
            pos = p.get("position") or {}
            market = p.get("market") or {}
            if str(market.get("epic") or "") != EPIC:
                continue
            ref = str(pos.get("dealReference") or "")
            if not ref.startswith("HBB-"):
                continue
            direction_s = str(pos.get("direction") or "").upper()
            if direction_s not in ("BUY", "SELL"):
                continue
            hbb_by_direction.setdefault(Dir(direction_s), []).append(pos)

        dup_dirs = [d.value for d, lst in hbb_by_direction.items() if len(lst) > 1]
        if dup_dirs:
            for d in dup_dirs:
                positions_for_d = hbb_by_direction[Dir(d)]
                logger.error(
                    "[restore] DUPLICATE HBB-* positions found on %s "
                    "direction=%s: %s. Cannot determine which is current. "
                    "BLOCKING trading until operator resolves.",
                    EPIC, d,
                    [{"dealId": p.get("dealId"),
                      "dealReference": p.get("dealReference"),
                      "openLevel": p.get("openLevel"),
                      "created": p.get("createdDateUTC")}
                     for p in positions_for_d],
                )
            # Leave the gate SET.
            return

        for d, lst in hbb_by_direction.items():
            pos = lst[0]
            ref = str(pos.get("dealReference") or "")
            direction = d
            fill = float(pos.get("openLevel") or pos.get("level") or 0.0)
            tp_level, sl_level = _tp_sl(direction, fill)
            try:
                limit_level = pos.get("limitLevel")
                stop_level = pos.get("stopLevel")
                if limit_level is not None:
                    tp_level = float(limit_level)
                if stop_level is not None:
                    sl_level = float(stop_level)
            except Exception:
                pass
            open_time = _parse_opened(pos)
            t = Trade(
                direction=direction,
                deal_id=str(pos.get("dealId") or ""),
                deal_reference=ref,
                fill_price=fill,
                tp_level=tp_level,
                sl_level=sl_level,
                open_time_utc=open_time or datetime.now(timezone.utc),
            )
            self.open_trades[direction] = t
            # No telegram message on restore (not in A16 list).
            logger.info(
                "[restore] %s %s fill=%s tp=%s sl=%s dealId=%s ref=%s",
                direction.value, EPIC, fill, tp_level, sl_level,
                t.deal_id, ref,
            )
            # If the daily row for this deal does not already exist
            # anywhere, write a partial row (per operator instruction):
            try:
                found = self.daily.update_by_deal_id(t.deal_id, {})
            except Exception:
                found = None
            if not found:
                from daily_file import Row  # local import to keep header light
                self.daily.append(
                    Row(
                        setup_time_utc=t.open_time_utc.isoformat(),
                        direction=direction.value,
                        outcome="TAKEN",
                        deal_id=t.deal_id,
                        deal_reference=t.deal_reference,
                        fill_price=f"{fill}",
                        take_profit_level=f"{tp_level}",
                        stop_level=f"{sl_level}",
                        note="restored after restart, no setup record",
                    ),
                    t.open_time_utc,
                )
        # Successful IG fetch (even if no positions existed).
        with self._lock:
            self._restart_reconciliation_pending = False
        logger.info("[restore] reconciliation complete; %d HBB positions "
                    "restored; trading admission unblocked.",
                    len(self.open_trades))

    # ---- Reconcile uncertain-state directions ------------------
    def reconcile_uncertain(self) -> None:
        """Called from check_broker_closes. If a direction is in
        _uncertain and IG reports a matching HBB-* position, PROMOTE
        it to open_trades. We do NOT auto-clear _uncertain without a
        matching position: operator intervention / restart is required
        to confirm the broker truly rejected / dropped the order."""
        with self._lock:
            if not self._uncertain:
                return
        try:
            raw = self.gw.get_open_positions()
        except Exception as exc:
            logger.warning("[reconcile] get_open_positions raised: %s", exc)
            return
        if raw is None:
            return
        # Same ambiguity gate as restore_open_positions. If any position
        # on our epic has an empty dealReference we cannot safely promote
        # anything from _uncertain — bail out and wait for next poll.
        for p in raw:
            pos = p.get("position") or {}
            market = p.get("market") or {}
            if str(market.get("epic") or "") != EPIC:
                continue
            raw_ref = pos.get("dealReference")
            if raw_ref is None or str(raw_ref).strip() == "":
                logger.warning(
                    "[reconcile] AMBIGUOUS position on %s (dealId=%s) — "
                    "skipping uncertain reconcile this cycle.",
                    EPIC, pos.get("dealId"),
                )
                return
        hbb_by_direction: Dict[Dir, list] = {}
        for p in raw:
            pos = p.get("position") or {}
            market = p.get("market") or {}
            if str(market.get("epic") or "") != EPIC:
                continue
            ref = str(pos.get("dealReference") or "")
            if not ref.startswith("HBB-"):
                continue
            dir_s = str(pos.get("direction") or "").upper()
            if dir_s not in ("BUY", "SELL"):
                continue
            hbb_by_direction.setdefault(Dir(dir_s), []).append(pos)
        # Duplicate protection: if there's >1 HBB-* position for a
        # direction we're uncertain about, DO NOT promote any of them —
        # we don't know which is "ours". Operator must investigate.
        for d, lst in hbb_by_direction.items():
            if len(lst) > 1:
                logger.error(
                    "[reconcile] DUPLICATE HBB-* positions for %s on %s: %s. "
                    "Not promoting; direction STAYS UNCERTAIN.",
                    d.value, EPIC,
                    [{"dealId": p.get("dealId"),
                      "dealReference": p.get("dealReference")}
                     for p in lst],
                )
        found: Dict[Dir, dict] = {d: lst[0] for d, lst in hbb_by_direction.items()
                                   if len(lst) == 1}
        with self._lock:
            for d in list(self._uncertain.keys()):
                if d in found:
                    pos = found[d]
                    fill = float(pos.get("openLevel") or pos.get("level") or 0.0)
                    tp_level, sl_level = _tp_sl(d, fill)
                    try:
                        if pos.get("limitLevel") is not None:
                            tp_level = float(pos["limitLevel"])
                        if pos.get("stopLevel") is not None:
                            sl_level = float(pos["stopLevel"])
                    except Exception:
                        pass
                    self.open_trades[d] = Trade(
                        direction=d,
                        deal_id=str(pos.get("dealId") or ""),
                        deal_reference=str(pos.get("dealReference") or ""),
                        fill_price=fill, tp_level=tp_level, sl_level=sl_level,
                        open_time_utc=_parse_opened(pos) or datetime.now(timezone.utc),
                    )
                    reason = self._uncertain.pop(d)
                    logger.info("[reconcile] %s uncertain promoted → open "
                                "(reason was %s)", d.value, reason)

    # ---- Open on confirm (A11) ---------------------------------
    def open_on_confirm(self, event) -> Optional[Trade]:
        s = event.setup
        direction = s.direction
        mode = BB_STOP_MODE.upper()

        # SHADOW mode: never submits, never touches gateway. The
        # admission guard is NOT required (nothing to protect against)
        # but SHADOW must still check so a prior uncertain state
        # doesn't accidentally allow analysis for a direction that may
        # already be live.
        if mode == "SHADOW":
            try:
                from shadow_mode import record as _shadow_record
                _shadow_record(event)
            except Exception as exc:
                logger.warning("[shadow] record failed: %s", exc)
            self._write_rejection_row(event, note="SHADOW_MODE (no order submitted)")
            return None

        # Admission guard — covers already-open, in-flight, uncertain,
        # and pre-reconciliation-at-boot states. If blocked, write a
        # rejection row and DO NOT touch open_trades (never overwrite).
        guard_reason = self._check_admission(direction)
        if guard_reason is not None:
            logger.warning("[admission] %s BLOCKED: %s",
                           direction.value, guard_reason)
            self._write_rejection_row(
                event, note=f"ADMISSION_BLOCKED: {guard_reason}")
            return None

        if mode == "STRUCTURAL_3":
            # Pre-flight using C3 close as the stand-in fill. If pre-flight
            # rejects (STOP_TOO_TIGHT or STAKE_BELOW_MIN), DO NOT submit.
            provisional_fill = float(event.c3.close) if event.c3 else 0.0
            provisional = _plan_for_setup(direction, provisional_fill, s)
            if provisional.rejected:
                self._write_rejection_row(
                    event,
                    note=f"STRUCTURAL_3 pre-flight rejected: {provisional.rejection_reason}",
                )
                return None

        # Mark pending BEFORE the IG call so a hypothetical concurrent
        # dispatch is correctly blocked.
        with self._lock:
            self._pending.add(direction)

        try:
            if mode == "STRUCTURAL_3":
                confirm = self.gw.open_market(
                    direction=direction.value, mode=MODE_TAG,
                    size=provisional.stake,
                    limit_distance=TP_PIPS,
                    stop_distance=provisional.stop_distance_pips,
                )
            else:  # FIXED_12 (default — unchanged behaviour)
                confirm = self.gw.open_market(direction.value, MODE_TAG)
        except Exception as exc:
            # Exception during submission → outcome genuinely unknown.
            # IG may have accepted. Promote to uncertain. DO NOT clear.
            with self._lock:
                self._pending.discard(direction)
                self._uncertain[direction] = f"EXCEPTION ({exc.__class__.__name__})"
            logger.error("[open] exception during submit; promoted "
                         "%s to UNCERTAIN. %s", direction.value, exc)
            self._write_rejection_row(
                event,
                note=f"SUBMISSION_EXCEPTION ({exc.__class__.__name__}) — "
                     "outcome unknown; direction blocked until reconciled",
            )
            return None

        if confirm is None:
            # None is ambiguous: a true network timeout OR a quiet
            # internal failure. DO NOT treat as rejection — IG may have
            # accepted. Promote to uncertain.
            with self._lock:
                self._pending.discard(direction)
                self._uncertain[direction] = "NO_RESPONSE"
            logger.error("[open] gateway returned None; promoted %s "
                         "to UNCERTAIN (blocked until reconciled).",
                         direction.value)
            self._write_rejection_row(
                event,
                note="SUBMISSION_OUTCOME_UNKNOWN (no gateway response) — "
                     "direction blocked until reconciled",
            )
            return None

        status = str(confirm.get("dealStatus") or "").upper()
        reject_reason = str(
            confirm.get("reason") or confirm.get("rejectReason") or ""
        ).upper()
        # Definitive broker-side rejection: the order did not execute.
        # Safe to clear `_pending` and NOT create an uncertain state.
        # Match either (a) the dealStatus is one of the known rejection
        # codes OR (b) a non-empty rejectReason indicates the broker
        # positively declined even if the status field itself is
        # ambiguous. (b) was the 2026-10-27 defect root cause: IG
        # returned a non-REJECTED status (BLOCKED) that the previous
        # code treated as uncertain, permanently locking out the
        # direction via the admission guard.
        is_definitive_rejection = (
            status in _KNOWN_IG_REJECTIONS
            or (reject_reason and reject_reason in _KNOWN_IG_REJECTIONS)
        )
        if is_definitive_rejection:
            with self._lock:
                self._pending.discard(direction)
            displayed = (reject_reason or status or "REJECTED")
            logger.info("[open] broker rejected %s: status=%r reason=%r",
                         direction.value, status, reject_reason)
            self._write_rejection_row(
                event, note=f"IG rejected: {displayed}",
            )
            # 2026-10-28 — event-driven refresh of IG dealing-rules.
            # Only ATTACHED_ORDER_LEVEL_ERROR (= stop-distance invalid)
            # triggers a single read-only fetch_market_by_epic call.
            # No retry.  Other rejection codes do NOT poll IG.
            if "ATTACHED_ORDER_LEVEL_ERROR" in (
                reject_reason or status or ""
            ).upper():
                try:
                    from ig_dealing_rules import record_rejection as _dr_rec
                    from config import EPIC as _EPIC, SYMBOL as _SYMBOL
                    _dr_rec(_EPIC, _SYMBOL)
                except Exception as _dr_exc:
                    logger.warning(
                        "[open] record_rejection failed after "
                        "ATTACHED_ORDER_LEVEL_ERROR: %s",
                        type(_dr_exc).__name__,
                    )
            return None
        if status != "ACCEPTED":
            # Any OTHER status (empty, PENDING, truly unknown) is
            # UNCERTAIN. Promote to uncertain. Do not treat as rejection.
            with self._lock:
                self._pending.discard(direction)
                self._uncertain[direction] = f"UNKNOWN_STATUS ({status or '<empty>'})"
            logger.error("[open] UNKNOWN dealStatus=%r; promoted %s "
                         "to UNCERTAIN.", status, direction.value)
            self._write_rejection_row(
                event,
                note=f"SUBMISSION_OUTCOME_UNKNOWN (dealStatus={status!r}) — "
                     "direction blocked until reconciled",
            )
            return None

        deal_id = str(confirm.get("dealId") or "")
        deal_ref = str(confirm.get("dealReference") or "")
        fill = float(confirm.get("level") or 0.0)

        if mode == "STRUCTURAL_3":
            # IG attached the stop at `fill ± provisional.stop_distance_pips`
            # because we sent `stopDistance` (not `stopLevel`). The SL level
            # therefore RIDES with fill — it is NOT pinned to the structural
            # extreme. Record what IG actually has, not a recomputed value.
            submitted_distance = provisional.stop_distance_pips
            if direction is Dir.BUY:
                sl_level = round(fill - submitted_distance, 2)
                tp_level = round(fill + TP_PIPS, 2)
            else:
                sl_level = round(fill + submitted_distance, 2)
                tp_level = round(fill - TP_PIPS, 2)
            stake_final = provisional.stake
            stop_mode = "STRUCTURAL_3"
            stop_distance = submitted_distance
            risk_pounds = round(stake_final * submitted_distance, 2)
            # Diagnostic: how far did the fill drift from the provisional?
            drift = round(fill - provisional_fill, 2)
            if abs(drift) >= 2.0:
                logger.warning(
                    "[open] STRUCTURAL_3 fill drift=%s pips "
                    "(provisional=%s actual=%s). IG stop attached at %s; "
                    "intended structural level was %s±3 buffer.",
                    drift, provisional_fill, fill, sl_level,
                    provisional.structural_extreme,
                )
        else:
            tp_level, sl_level = _tp_sl(direction, fill)
            stake_final = TRADE_SIZE
            stop_mode = "FIXED_12"
            stop_distance = float(SL_PIPS)
            risk_pounds = round(float(SL_PIPS) * TRADE_SIZE, 2)

        now = datetime.now(timezone.utc)
        trade = Trade(
            direction=direction,
            deal_id=deal_id,
            deal_reference=deal_ref,
            fill_price=fill,
            tp_level=tp_level,
            sl_level=sl_level,
            open_time_utc=now,
            stake=stake_final,
            stop_mode=stop_mode,
            stop_distance_pips=stop_distance,
            initial_cash_risk_pounds=risk_pounds,
        )
        with self._lock:
            prev_opposite = self.open_trades.get(
                Dir.SELL if direction is Dir.BUY else Dir.BUY
            )
            self.open_trades[direction] = trade
            self._pending.discard(direction)
            self._uncertain.pop(direction, None)
        self._write_open_row(event, trade)
        self._notify_open(trade)
        # A10 opposite-close: new trade is live; now close the old one.
        if prev_opposite is not None:
            self._close_trade(prev_opposite, close_type="OPPOSITE_TRADE")
        return trade

    # ---- Poll IG for autonomous closes (TP/SL) -----------------
    def check_broker_closes(self) -> List[Trade]:
        # Reconcile uncertain-state directions on every poll — this is
        # the path by which a successful-but-silent IG open is promoted
        # back into the book without permitting a duplicate submit.
        self.reconcile_uncertain()
        # If the restart gate is still set, the previous attempt
        # failed; retry a get_open_positions reconcile now. The
        # restore_open_positions() helper will clear the gate on success.
        with self._lock:
            still_blocked = self._restart_reconciliation_pending
        if still_blocked:
            logger.info("[reconcile] retrying boot reconciliation …")
            self.restore_open_positions()
        if not self.open_trades:
            return []
        positions = self.gw.get_open_positions()
        if positions is None:
            return []
        live_ids = set()
        for p in positions:
            pos = p.get("position") or {}
            did = str(pos.get("dealId") or "")
            if did:
                live_ids.add(did)
        closed: List[Trade] = []
        for direction, t in list(self.open_trades.items()):
            if t.deal_id and t.deal_id in live_ids:
                continue
            closed.append(t)
            self._record_broker_close(t)
            with self._lock:
                self.open_trades.pop(direction, None)
        return closed

    # ---- Cancellation CSV writers ------------------------------
    def write_cancelled_setup(self, event) -> None:
        """Record a non-trade terminal setup (CANCELLED or EXPIRED).

        Writes a row at the setup's outcome time.
        """
        from daily_file import Row  # keep header light
        s = event.setup
        now = datetime.now(timezone.utc)
        row = Row(
            setup_time_utc=s.c1.ts.isoformat(),
            direction=s.direction.value,
            c1_high=f"{s.c1.high}",
            c1_low=f"{s.c1.low}",
            c1_bb_upper=f"{s.c1_band.upper}",
            c1_bb_middle=f"{s.c1_band.middle}",
            c1_bb_lower=f"{s.c1_band.lower}",
            outcome=event.kind.value,
            note=s.cancel_reason or "",
        )
        if s.c2 is not None and s.c2_band is not None:
            row.c2_high = f"{s.c2.high}"
            row.c2_low = f"{s.c2.low}"
            row.c2_bb_upper = f"{s.c2_band.upper}"
            row.c2_bb_middle = f"{s.c2_band.middle}"
            row.c2_bb_lower = f"{s.c2_band.lower}"
        if event.c3 is not None and event.c3_band is not None:
            row.c3_high = f"{event.c3.high}"
            row.c3_low = f"{event.c3.low}"
            row.c3_bb_upper = f"{event.c3_band.upper}"
            row.c3_bb_middle = f"{event.c3_band.middle}"
            row.c3_bb_lower = f"{event.c3_band.lower}"
        self.daily.append(row, now)

    # ---- helpers -----------------------------------------------
    def _wick_fields(self, event) -> Dict[str, str]:
        """Compute wick/pierce metrics for the setup. Also computes ATR14
        from completed candles for telemetry only (never affects trading
        decisions)."""
        s = event.setup
        if not s.c1 or not s.c1_band:
            return {}
        # ATR14 from the last 14 completed candles up to the C2 close
        # (or C1 close if C2 is missing). Telemetry only — never affects
        # trade acceptance / sizing.
        atr_val = 0.0
        try:
            from atr import atr14_at
            ref_candle = s.c2 or s.c1
            if ref_candle is not None:
                atr_val = atr14_at(ref_candle.close_time)
        except Exception as exc:
            logger.warning("[atr14] compute failed (non-blocking): %s", exc)
            atr_val = 0.0

        try:
            from wick_metrics import compute as _wmc
            m = _wmc(
                direction=s.direction,
                c1_open=s.c1.open, c1_high=s.c1.high,
                c1_low=s.c1.low, c1_close=s.c1.close,
                c1_band_lower=s.c1_band.lower, c1_band_upper=s.c1_band.upper,
                c2_open=s.c2.open if s.c2 else None,
                c2_high=s.c2.high if s.c2 else None,
                c2_low=s.c2.low if s.c2 else None,
                c2_close=s.c2.close if s.c2 else None,
                c2_band_lower=s.c2_band.lower if s.c2_band else None,
                c2_band_upper=s.c2_band.upper if s.c2_band else None,
                atr_pips=atr_val,
            )
            return {
                "c1_pierce_pips": f"{m.c1_pierce_pips}",
                "c1_wick_pips": f"{m.c1_wick_pips}",
                "c1_wick_body_ratio": f"{m.c1_wick_body_ratio}",
                "c2_pierce_pips": f"{m.c2_pierce_pips}",
                "c2_rejection_wick_pips": f"{m.c2_rejection_wick_pips}",
                "max_c1c2_pierce_pips": f"{m.max_c1c2_pierce_pips}",
                "max_c1c2_rejection_wick": f"{m.max_c1c2_rejection_wick}",
                "atr14_pips": f"{atr_val}" if atr_val > 0 else "",
                "pierce_depth_atr_norm": (
                    f"{m.pierce_depth_atr_norm}" if atr_val > 0 else ""
                ),
            }
        except Exception as exc:
            logger.warning("[wick_metrics] compute failed: %s", exc)
            return {}

    def _write_open_row(self, event, trade: Trade) -> None:
        from daily_file import Row
        s = event.setup
        wick_fields = self._wick_fields(event)
        row = Row(
            setup_time_utc=s.c1.ts.isoformat(),
            direction=s.direction.value,
            c1_high=f"{s.c1.high}",
            c1_low=f"{s.c1.low}",
            c1_bb_upper=f"{s.c1_band.upper}",
            c1_bb_middle=f"{s.c1_band.middle}",
            c1_bb_lower=f"{s.c1_band.lower}",
            c2_high=f"{s.c2.high}",
            c2_low=f"{s.c2.low}",
            c2_bb_upper=f"{s.c2_band.upper}",
            c2_bb_middle=f"{s.c2_band.middle}",
            c2_bb_lower=f"{s.c2_band.lower}",
            c3_high=f"{event.c3.high}",
            c3_low=f"{event.c3.low}",
            c3_bb_upper=f"{event.c3_band.upper}",
            c3_bb_middle=f"{event.c3_band.middle}",
            c3_bb_lower=f"{event.c3_band.lower}",
            outcome="TAKEN",
            deal_id=trade.deal_id,
            deal_reference=trade.deal_reference,
            fill_price=f"{trade.fill_price}",
            take_profit_level=f"{trade.tp_level}",
            stop_level=f"{trade.sl_level}",
            stop_mode=trade.stop_mode,
            stop_distance_pips=f"{trade.stop_distance_pips}",
            stake=f"{trade.stake}",
            initial_cash_risk_pounds=f"{trade.initial_cash_risk_pounds}",
            **wick_fields,
        )
        self.daily.append(row, trade.open_time_utc)

    def _write_rejection_row(self, event, note: str) -> None:
        from daily_file import Row
        s = event.setup
        now = datetime.now(timezone.utc)
        row = Row(
            setup_time_utc=s.c1.ts.isoformat(),
            direction=s.direction.value,
            c1_high=f"{s.c1.high}",
            c1_low=f"{s.c1.low}",
            c1_bb_upper=f"{s.c1_band.upper}",
            c1_bb_middle=f"{s.c1_band.middle}",
            c1_bb_lower=f"{s.c1_band.lower}",
            c2_high=f"{s.c2.high}" if s.c2 else "",
            c2_low=f"{s.c2.low}" if s.c2 else "",
            c2_bb_upper=f"{s.c2_band.upper}" if s.c2_band else "",
            c2_bb_middle=f"{s.c2_band.middle}" if s.c2_band else "",
            c2_bb_lower=f"{s.c2_band.lower}" if s.c2_band else "",
            c3_high=f"{event.c3.high}" if event.c3 else "",
            c3_low=f"{event.c3.low}" if event.c3 else "",
            c3_bb_upper=f"{event.c3_band.upper}" if event.c3_band else "",
            c3_bb_middle=f"{event.c3_band.middle}" if event.c3_band else "",
            c3_bb_lower=f"{event.c3_band.lower}" if event.c3_band else "",
            outcome="REJECTED",
            note=note,
        )
        self.daily.append(row, now)

    def _close_trade(self, trade: Trade, close_type: str) -> None:
        resp = self.gw.close_by_deal_id(trade.deal_id)
        if resp is None:
            logger.error(
                "[close] IG close FAILED for dealId=%s direction=%s — "
                "trade may still be open on IG",
                trade.deal_id, trade.direction.value,
            )
            return
        close_price = float(resp.get("level") or 0.0)
        close_time = datetime.now(timezone.utc)
        pips = pips_pnl(trade.direction, trade.fill_price, close_price)
        pounds = round(pips * TRADE_SIZE, 2)
        self.daily.update_by_deal_id(
            trade.deal_id,
            {
                "close_time_utc": close_time.isoformat(),
                "close_price": f"{close_price}",
                "close_type": close_type,
                "pips": f"{pips}",
                "pounds": f"{pounds}",
            },
        )
        self._notify_close(trade, close_price, close_type, pips, pounds)
        # Remove from the open book — close succeeded on IG.
        with self._lock:
            if self.open_trades.get(trade.direction) is trade:
                self.open_trades.pop(trade.direction, None)

    def _record_broker_close(self, trade: Trade) -> None:
        detail = self.gw.fetch_close_detail(
            trade.deal_id,
            trade.direction.value,
            trade.open_time_utc,
            trade.tp_level,
            trade.sl_level,
        )
        if not detail:
            logger.warning(
                "[close] no close detail for dealId=%s; "
                "writing inferred close",
                trade.deal_id,
            )
            # Infer close by polling-time, mark unknown.
            close_time = datetime.now(timezone.utc)
            close_price = 0.0
            close_type = "UNKNOWN"
            pips = 0.0
            pounds = 0.0
        else:
            close_time, close_price, close_type = detail
            pips = pips_pnl(trade.direction, trade.fill_price, close_price)
            pounds = round(pips * TRADE_SIZE, 2)
        self.daily.update_by_deal_id(
            trade.deal_id,
            {
                "close_time_utc": close_time.isoformat(),
                "close_price": f"{close_price}",
                "close_type": close_type,
                "pips": f"{pips}",
                "pounds": f"{pounds}",
            },
        )
        self._notify_close(trade, close_price, close_type, pips, pounds)

    # ---- Telegram --------------------------------------------------
    def _notify_open(self, t: Trade) -> None:
        body = (
            f"OPEN {t.direction.value} {SYMBOL} "
            f"fill={t.fill_price} "
            f"TP={t.tp_level} "
            f"SL={t.sl_level}"
        )
        self.notify(body, wait=True)

    def _notify_close(
        self,
        t: Trade,
        close_price: float,
        close_type: str,
        pips: float,
        pounds: float,
    ) -> None:
        body = (
            f"CLOSE {t.direction.value} {SYMBOL} "
            f"close={close_price} "
            f"how={close_type} "
            f"pips={pips} "
            f"pnl=£{pounds}"
        )
        self.notify(body, wait=True)


def _parse_opened(pos: Dict[str, Any]) -> Optional[datetime]:
    for key in ("createdDateUTC", "createdDate"):
        raw = pos.get(key)
        if not raw:
            continue
        s = str(raw).strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return None
