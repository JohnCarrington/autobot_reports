"""trade_log.py — unified one-row-per-trade capture across every route.

Rationale
---------
Build 1 and earlier emit signal_log rows per-strategy via ~20 call sites in
``autobot.py`` and leave several ``execute_trade`` paths without any log at
all (NEWS_CONTINUATION, BB_REV_L, BIG_REV, OVERNIGHT_SWEEP, BB_PREMIRROR_L,
NY_CONTINUATION_L, ROUTER regime, RAW_REVERSAL, CONFIRMATION_FALLBACK — see
the Build 2 wiring report). The result is that reconciliation reports have
to merge ``signal_log.jsonl``, ``sweep_journal_*.csv``, bb_pierce traces,
and foreign-deal observations to approximate "every executed trade".

This module registers callbacks on ``trade_executor``'s open + close seams
(``register_trade_open_callback`` / ``register_trade_close_callback``) so
EVERY successful ``execute_trade`` and EVERY ``close_position`` produces a
row in ``logs/unified_trades.jsonl`` regardless of which caller invoked
the primitive. OPEN and CLOSE rows share ``deal_id``.

Price basis + GBP convention are unchanged: ``pnl_gbp = pnl_pips *
trade_size`` (unscaled) or ``pnl_pips * trade_size / 2`` when a scale-out
banked a partial — mirrors ``daily_journal._fire_cash_gbp``.

File location: ``logs/unified_trades.jsonl`` (append-only JSONL).

Wiring (contract)
-----------------
    initializer: ``trade_log.install()``        called from ``autobot.py``
                                                startup once.
    driver:      ``trade_executor._fire_open_callbacks`` at the three
                 ACCEPTED-return paths (``trade_executor.py:4006, 4334,
                 4436``) and ``_fire_close_callbacks`` at
                 ``trade_executor.py:4738``.
    consumer:    append to ``logs/unified_trades.jsonl``; a replay harness
                 or trades-api reader can parse the file independently of
                 ``signal_log.jsonl``.

Fails open: any exception during row build or append is swallowed; the
trade primitive must not be broken by telemetry.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("AutoBot")

# ── Output location ───────────────────────────────────────────────────
_DEFAULT_LOG_DIR = os.getenv("TRADE_LOG_DIR", "/opt/tradingbot/logs")
LOG_PATH = Path(_DEFAULT_LOG_DIR) / "unified_trades.jsonl"

# ── Serialisation lock ────────────────────────────────────────────────
# The open + close callbacks fire from different threads (strategy fire +
# trade_manager poll). A single flock-free lock here is sufficient because
# every writer in this process goes through the same ``_append`` call.
_WRITE_LOCK = threading.Lock()

# ── Installer state ───────────────────────────────────────────────────
_installed = False
_INSTALL_LOCK = threading.Lock()


# ── Route derivation ──────────────────────────────────────────────────
# Translates decision.mode / debug.family → a stable route tag the user's
# scoping question refers to.  The full set is intentionally small so the
# downstream reports can slice by route without owning a mapping table.
_ROUTE_ONE_STRATEGY = "ONE_STRATEGY"
_ROUTE_BB_BOUNCE = "BB_BOUNCE"
_ROUTE_QM_V2 = "QM_V2"
_ROUTE_V2_PICK = "V2_PICK"
_ROUTE_BRIEFING = "BRIEFING"
_ROUTE_LEGACY = "LEGACY"  # anything else (news, sweep, trend_v3, …)


def _derive_route(decision: Any, state: Dict[str, Any]) -> str:
    """Collapse the many strategy modes into a route label.

    Decision-first (per-fire mode), state as fallback (survives reboots
    via EPIC_STATE which carries the mode persisted into the pending-deal
    ledger).  Unknown strategies hit LEGACY so the row is still captured
    with its real ``strategy`` string in the row body.
    """
    mode = ""
    try:
        mode = str(getattr(decision, "mode", "") or "").upper()
    except Exception:
        pass
    if not mode:
        mode = str((state or {}).get("mode", "") or "").upper()

    # route tags: ordered by specificity so a QM_V2 fire inside a
    # BB_BOUNCE family stays QM_V2.
    if mode.startswith("ONE_STRATEGY") or mode == "ONE_STRATEGY":
        return _ROUTE_ONE_STRATEGY
    if "V2_PICK" in mode:
        return _ROUTE_V2_PICK
    if "QM_V2" in mode:
        return _ROUTE_QM_V2
    if "BB_BOUNCE" in mode or "BB_PIERCE" in mode:
        return _ROUTE_BB_BOUNCE
    if "BRIEFING" in mode:
        return _ROUTE_BRIEFING
    return _ROUTE_LEGACY


# ── Decision-context extraction ───────────────────────────────────────
# Reads whatever the strategy stashed on decision.debug + state. Fields
# are nullable; the point is to capture whatever was available at fire
# time so downstream analysis can filter without rerunning strategies.
_PRESSURE_KEYS = (
    "pressure_reading", "pressure_vector", "v1_pressure",
    "pressure_direction", "pressure_at_fire",
)
_VIEW_ZONE_KEYS = (
    "view_zone", "qm_zone_center", "zone_center", "briefing_level",
    "level_price",
)
_CLOSEBACK_KEYS = (
    "closeback_state", "close_back_state", "close_back_inside",
    "close_back_through", "closeback",
)


def _first_present(dbg: Dict[str, Any], keys) -> Any:
    for k in keys:
        if k in dbg and dbg[k] is not None:
            return dbg[k]
    return None


def _extract_context(decision: Any, state: Dict[str, Any]) -> Dict[str, Any]:
    """Pull pressure / view_zone / closeback from decision.debug + state.

    Non-presence is a null — the row is still emitted. Callers that want
    to enforce these fields should run the ``test_trade_log`` tests
    where the schema is enforced on a canned decision shape.
    """
    dbg: Dict[str, Any] = {}
    try:
        dbg = dict(getattr(decision, "debug", None) or {})
    except Exception:
        dbg = {}
    # EPIC_STATE snapshot sometimes carries the briefing meta.
    try:
        bm = dict((state or {}).get("briefing_meta") or {})
        for k, v in bm.items():
            dbg.setdefault(k, v)
    except Exception:
        pass
    return {
        "pressure_reading": _first_present(dbg, _PRESSURE_KEYS),
        "view_zone": _first_present(dbg, _VIEW_ZONE_KEYS),
        "closeback_state": _first_present(dbg, _CLOSEBACK_KEYS),
    }


# ── Append ────────────────────────────────────────────────────────────

def _append(row: Dict[str, Any]) -> None:
    """Serialise + append one row. Fails open on any IO error."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, sort_keys=True, default=str)
        with _WRITE_LOCK:
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[trade_log] append failed: %s", e)


# ── Core row builders ─────────────────────────────────────────────────

def _epic_state_snapshot(pos_key: str) -> Dict[str, Any]:
    """Grab a shallow snapshot of EPIC_STATE[pos_key] without pulling the
    lock across the append. Fails open to {}."""
    try:
        from trade_executor import EPIC_STATE, EPIC_STATE_LOCK  # local
        with EPIC_STATE_LOCK:
            st = EPIC_STATE.get(pos_key) or {}
            # shallow copy of just the keys we read; keep the snapshot small
            # so we don't accidentally pin large pandas frames.
            keys = (
                "deal_id", "dealId", "dealReference", "epic", "mode",
                "size", "direction", "entry_price", "open_time",
                "briefing_meta", "decision_debug",
                "mfe_pips", "mae_pips",
                "partial_bank_pips", "total_pnl_pips", "runner_pnl_pips",
            )
            return {k: st.get(k) for k in keys}
    except Exception:
        return {}


def _trade_size_from(state: Dict[str, Any]) -> float:
    try:
        s = state.get("size")
        if s is None:
            return 1.0
        return float(s)
    except Exception:
        return 1.0


def _pnl_gbp(pnl_pips: Optional[float], state: Dict[str, Any]) -> Optional[float]:
    """pnl_pips × trade_size, with scaled-trade halving per daily_journal
    convention (``_fire_cash_gbp``). ``None`` only when pnl_pips is None."""
    if pnl_pips is None:
        return None
    try:
        size = _trade_size_from(state)
        if state.get("partial_bank_pips") is not None:
            # scaled: pips here is the runner leg; cash is total × size/2
            total = state.get("total_pnl_pips")
            if total is not None:
                return round(float(total) * (size / 2.0), 2)
        return round(float(pnl_pips) * size, 2)
    except Exception:
        return None


# ── Callback endpoints (public: imported by autobot startup) ──────────

def record_open(pos_key: str, decision: Any) -> None:
    """``trade_executor.register_trade_open_callback`` target.

    Signature matches the registered contract. Any exception here fires
    the LEG-ORPHAN-DETECTED alert in ``_fire_open_callbacks`` — but we
    MUST NOT raise, because that would mark the strategy as orphaned
    even though every other callback succeeded. Any failure stays
    silent at WARNING level inside ``_append``.
    """
    try:
        state = _epic_state_snapshot(pos_key)
        deal_id = state.get("deal_id") or state.get("dealId") or ""
        route = _derive_route(decision, state)
        side = ""
        entry_price = None
        try:
            side = str(getattr(decision, "signal", "") or "").upper()
            entry_price = state.get("entry_price")
            if entry_price is None:
                entry_price = getattr(decision, "entry_price", None)
            if entry_price is not None:
                entry_price = float(entry_price)
        except Exception:
            entry_price = None
        ctx = _extract_context(decision, state)
        strategy_mode = ""
        try:
            strategy_mode = str(getattr(decision, "mode", "") or "")
        except Exception:
            pass
        row = {
            "event": "OPEN",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "pos_key": str(pos_key),
            "deal_id": str(deal_id) if deal_id else None,
            "deal_reference": str(state.get("dealReference") or "") or None,
            "epic": str(state.get("epic") or "") or None,
            "route": route,
            "strategy": strategy_mode or None,
            "side": side or None,
            "entry_price": entry_price,
            "size": _trade_size_from(state),
            "pressure_reading": ctx["pressure_reading"],
            "view_zone": ctx["view_zone"],
            "closeback_state": ctx["closeback_state"],
        }
        _append(row)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[trade_log] record_open failed: %s", e)


def record_close(
    pos_key: str,
    exit_price: Optional[float],
    pnl_pips: Optional[float],
    close_reason: Optional[str],
    *,
    deal_id: Optional[str] = None,
    price_source: Optional[str] = None,
) -> None:
    """``trade_executor.register_trade_close_callback`` target.

    Signature matches both the deal_id-aware and the legacy forms (the
    firing site at ``trade_executor.py:4738`` tries kwarg-form first,
    falls back without it).

    ``price_source`` labels the provenance of ``exit_price`` + ``pnl_pips``:
      * ``AUTHORITATIVE_BROKER_CLOSE`` — close_trade / close_position
        succeeded and IG confirmed the real fill price.
      * ``AUTHORITATIVE_IG_HISTORY`` — signal_log_integrity matched the
        trade against ``/history/transactions`` (``closeLevel`` field).
        Prompt-fetched or picked up by the daily reconciler.
      * ``ESTIMATED_LAST_MID`` — vanished-close path (IG_RECONCILE_CLEAR,
        ORPHAN_SWEEP). ``exit_price`` is the last tick mid, ``pnl_pips``
        is derived from that estimate (or null).
      * ``None`` (default) — kept for the legacy close callback firing
        site that has not been updated; readers should treat None as
        AUTHORITATIVE_BROKER_CLOSE (``close_trade`` is the only caller
        that still passes None).

    Readers of ``logs/unified_trades.jsonl`` that see multiple CLOSE rows
    for one deal_id MUST take AUTHORITATIVE_* over ESTIMATED_LAST_MID.
    See ``read_closes_by_deal_id`` below for the canonical reader.
    """
    try:
        state = _epic_state_snapshot(pos_key)
        did = deal_id or state.get("deal_id") or state.get("dealId") or ""
        # Phase 5 Stage A fix — fail honest: callers that don't supply
        # price_source have not proved IG-authoritative provenance. The
        # Phase 4 overnight audit found 41 external-close rows carrying
        # the AUTHORITATIVE_BROKER_CLOSE default while their exit_price
        # was actually the pre-execution last_mid hint (mean £23 delta,
        # max £143). Default to ESTIMATED_LAST_MID so the
        # authoritative-IG-history supersession path replaces this row
        # with the real IG fill level within _PROMPT_AUTH_DELAY_SECS.
        ps = price_source or _ESTIMATED_LAST_MID
        row = {
            "event": "CLOSE",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "pos_key": str(pos_key),
            "deal_id": str(did) if did else None,
            "epic": str(state.get("epic") or "") or None,
            "exit_price": float(exit_price) if exit_price is not None else None,
            "pnl_pips": float(pnl_pips) if pnl_pips is not None else None,
            "pnl_gbp": _pnl_gbp(pnl_pips, state),
            "close_reason": str(close_reason) if close_reason else None,
            "price_source": ps,
            "mfe_pips": state.get("mfe_pips"),
            "mae_pips": state.get("mae_pips"),
            "size": _trade_size_from(state),
            "partial_bank_pips": state.get("partial_bank_pips"),
            "total_pnl_pips": state.get("total_pnl_pips"),
            "runner_pnl_pips": state.get("runner_pnl_pips"),
        }
        _append(row)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[trade_log] record_close failed: %s", e)


# ── Verdict + continue-or-reverse decisions ───────────────────────────
# Build 2 (operator ruling 2026-10-05): every QM/V2 verdict read at a
# view level AND every continue-or-reverse decision gets a row in the
# unified log so the single-file reconciliation stays complete.
#
# EVENT="VERDICT_LOCKED": the FIRST non-None QM/V2 verdict for a visit.
# EVENT="COR_DECISION":   the HOLD / CLOSE_AND_REVERSE action locked on
#                         that verdict + the entry-rule snapshot.
#
# Both are idempotent at the continue_or_reverse module layer — this
# function just appends; the caller must not re-emit after lock.

def record_verdict(
    *,
    visit_key: str,
    pair: str,
    pos_key: str,
    level_id: str,
    verdict: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a VERDICT_LOCKED row. Fail-silent."""
    try:
        row = {
            "event": "VERDICT_LOCKED",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "visit_key": str(visit_key),
            "pair": str(pair).upper(),
            "pos_key": str(pos_key),
            "level_id": str(level_id),
            "verdict": str(verdict),
        }
        if isinstance(extra, dict):
            for k, v in extra.items():
                row.setdefault(k, v)
        _append(row)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[trade_log] record_verdict failed: %s", e)


def record_cor_decision(
    *,
    visit_key: str,
    pair: str,
    pos_key: str,
    level_id: str,
    action: str,
    reason: str,
    locked_verdict: Optional[str] = None,
    opposite_side: Optional[str] = None,
    entry_rules: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a COR_DECISION row — one per visit when the action locks.
    Fail-silent."""
    try:
        row = {
            "event": "COR_DECISION",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "visit_key": str(visit_key),
            "pair": str(pair).upper(),
            "pos_key": str(pos_key),
            "level_id": str(level_id),
            "action": str(action),
            "reason": str(reason),
            "locked_verdict": locked_verdict,
            "opposite_side": opposite_side,
            "entry_rules": entry_rules,
        }
        if isinstance(extra, dict):
            for k, v in extra.items():
                row.setdefault(k, v)
        _append(row)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[trade_log] record_cor_decision failed: %s", e)


# ── price_source labels (public) ──────────────────────────────────────
_AUTHORITATIVE_BROKER_CLOSE = "AUTHORITATIVE_BROKER_CLOSE"
_AUTHORITATIVE_IG_HISTORY = "AUTHORITATIVE_IG_HISTORY"
_ESTIMATED_LAST_MID = "ESTIMATED_LAST_MID"

AUTHORITATIVE_BROKER_CLOSE = _AUTHORITATIVE_BROKER_CLOSE
AUTHORITATIVE_IG_HISTORY = _AUTHORITATIVE_IG_HISTORY
ESTIMATED_LAST_MID = _ESTIMATED_LAST_MID


def read_closes_by_deal_id(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Return the best (= authoritative-preferred) CLOSE row per deal_id.

    Canonical supersession rule for consumers of the unified log:
      * ``AUTHORITATIVE_IG_HISTORY`` or ``AUTHORITATIVE_BROKER_CLOSE``
        wins over ``ESTIMATED_LAST_MID`` for the same deal_id.
      * Among authoritative rows the latest ``ts_utc`` wins (reconciler
        reruns are idempotent on the data side, but if operator rules
        change we honour the most recent authoritative statement).
      * Among estimated-only, the latest ts_utc wins.
    Rows with no ``deal_id`` are keyed by ``pos_key`` + ``ts_utc`` and
    returned unchanged — those are orphan sweeps the reader must handle
    on their own.
    """
    path = Path(path) if path else LOG_PATH
    best: Dict[str, Dict[str, Any]] = {}
    try:
        if not path.exists():
            return best
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("event") != "CLOSE":
                continue
            did = row.get("deal_id") or f"__orphan__{row.get('pos_key')}@{row.get('ts_utc')}"
            cur = best.get(did)
            if cur is None:
                best[did] = row
                continue
            cur_ps = cur.get("price_source") or _AUTHORITATIVE_BROKER_CLOSE
            new_ps = row.get("price_source") or _AUTHORITATIVE_BROKER_CLOSE
            cur_auth = cur_ps.startswith("AUTHORITATIVE")
            new_auth = new_ps.startswith("AUTHORITATIVE")
            if new_auth and not cur_auth:
                best[did] = row
            elif new_auth == cur_auth:
                # Same tier — latest ts wins.
                if str(row.get("ts_utc", "")) > str(cur.get("ts_utc", "")):
                    best[did] = row
            # cur_auth and not new_auth → keep cur (authoritative beats estimated)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[trade_log] read_closes_by_deal_id failed: %s", e)
    return best


# ── Installer — single idempotent entry point ─────────────────────────

def install() -> None:
    """Register the open + close callbacks on ``trade_executor``.

    Idempotent — safe to call multiple times during tests or startup.
    Must be called ONCE at process boot (``autobot.py`` main). The
    installer imports ``trade_executor`` lazily so unit tests that
    stub trade_executor can patch registration without side effects.
    """
    global _installed
    with _INSTALL_LOCK:
        if _installed:
            return
        try:
            import trade_executor  # local
            trade_executor.register_trade_open_callback(record_open)
            trade_executor.register_trade_close_callback(record_close)
            _installed = True
            logger.info("[trade_log] installed → %s", LOG_PATH)
        except Exception as e:  # pragma: no cover — defensive
            logger.error("[trade_log] install failed: %s", e, exc_info=True)


# ── Test helpers (not part of the public contract) ────────────────────

def _reset_for_tests() -> None:
    """Clear installer state so a test can re-register. Not for prod."""
    global _installed
    with _INSTALL_LOCK:
        _installed = False


# ── Side-effect install (mirrors candle_archive.py:235) ───────────────
# Import-time registration so ``import trade_log`` from autobot startup
# is enough to wire the callbacks. Disabled by env for tests that need
# to control registration manually.
# Phase 5 research isolation — never autoinstall in the research harness
# (install() reaches into /opt/tradingbot/trade_executor which is live).
if False and os.getenv("TRADE_LOG_AUTOINSTALL", "1") != "0":
    install()
