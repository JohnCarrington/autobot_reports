"""auto_k.py — automated premise-death cut (universal, per-family thresholds).

Spec source: operator's own labelled kills (week of 2026-08-03).

Cut an open position when ALL of:
  (1) MAE ≥ AUTOK_MAE_MIN_PIPS_<family> (default 6.0p / briefing 10.0p).
      MAE = -pnl_pips at eval time, evaluated per completed 5m bar.
  (2) The adverse move is accelerating: ribbon_state.velocity_state on
      the pair's current 5m completed bars returns state==OK,
      dir_of_move is AGAINST the position, and accel ≥ AUTOK_ACCEL_MIN
      (default 1.0). DEAD_TAPE and UNKNOWN abstain (no cut).
  (3) The position has NEVER touched +AUTOK_TOUCHED_LOCK_PIPS (default
      5.0p) favourable — meta["best_pnl_pips"] < 5.0.
      (Wobble-winners stay protected — the 06-30-class case.)

Action: close ENTIRE position at market via trade_executor.close_position
        with reason="AUTO_K_PREMISE" — same primitive as
        bb_bounce_labeller._handle_kill_fire uses for
        LABEL_K_OPERATOR (bb_bounce_labeller.py:586).
        Telegram: [AUTO-K] closed <strat> <dir> #<label_n if bound>
                  @ <price> MAE=<x> accel=<x> — premise-death cut.

Per-family threshold (amended 2026-08-09):
  DEFAULT  (AUTOK_MAE_MIN_PIPS_DEFAULT=6.0)
    GBPUSD_BB_BOUNCE_L / _S
    GBPUSD_CONFIRMATION_FALLBACK_L / _S
    EMA_PULLBACK, GBPUSD_EMA_PULLBACK_L / _S
    GBPUSD_TREND_V3_L / _S
    GBPUSD_STRUCTURE_BREAK_L / _S
  BRIEFING (AUTOK_MAE_MIN_PIPS_BRIEFING=10.0)
    BRIEFING_EXECUTION, and any mode carrying "BRIEFING_V5"
    — must NOT front-run their own STRUCTURE_EXIT; whichever triggers
      first closes, both log.
  EXCLUDED (AUTOK_EXCLUDE, default "NEWS_CONTINUATION,PIVOT_BREAK,H1_PIERCE")
    NEWS_CONT_LEG — structural stop + high-accel tape = false-trigger by
    construction; K-manual covers it.
    PIVOT_BREAK — coil-at-pivot geometry: slow grind with small-negative MAE
    by design (see gbpusd_pivot_break.py "No timeout").
    H1_PIERCE — reversal pattern's adverse excursion before working is by
    design (research: A-variant median adverse 11.4p vs median excursion
    12.10p — /tmp/bb_pierce_entry_timing_v2.txt).

Master flag: AUTOK_ENABLED=1 (default off in code, on in .env).

Senior/independent (auto-K never front-runs):
  Operator K       — bb_bounce_labeller._handle_kill_fire
  Broker stop      — attached SL on the deal
  STRUCTURE_EXIT   — the strategy-side structural invalidation exit

Interaction with the exit profile (2026-08-06 SQUEEZE / EXPANDED / …):
  Auto-K is evaluated AFTER _apply_exit_profile in the management pass.
  A SQUEEZE-mode position with a working full-close target IS still
  auto-K eligible — if it goes underwater +MAE with accelerating adverse
  velocity and has never touched +5, the premise is dead regardless of
  the SQUEEZE ceiling and the cut takes precedence. Wobble-winners
  (best_pnl_pips ≥ 5.0) are the ONLY exit-profile-managed positions
  auto-K refuses to cut.

Never raises to caller. Fail-open: on any internal error, returns None
and the position rides as it would without auto-K.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


REASON_CODE = "AUTO_K_PREMISE"


# ─── Env accessors ─────────────────────────────────────────────────────────
def _env(name: str, default: str) -> str:
    return str(os.getenv(name, default))


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)).strip())
    except Exception:
        return float(default)


def _env_bool(name: str, default: str) -> bool:
    return _env(name, default).strip().lower() in ("1", "true", "yes", "on")


def _enabled() -> bool:
    return _env_bool("AUTOK_ENABLED", "0")


def _premise_enabled() -> bool:
    # Branch-specific kill switch for the MAE + ribbon-velocity premise-death
    # cut (Gates 1/2/3 below). Retired 2026-09-02 on counterfactual evidence
    # from reports-public/host161_autok_labelk_counterfactual_20260902.md:
    # 18/27 (67%) of AUTO_K_PREMISE cuts in W33-W36 recovered to entry within
    # 36 five-minute bars; hold-to-mechanical (BE for RECOVERED / -20p SL for
    # WORSENED / midpoint for MIXED) beat cut-at-market by +73.1p. The 6p MAE
    # trigger duplicates the 20p broker SL's protection at a depth normal
    # winners routinely visit.
    #
    # Default 0 (premise branch inert). REFORM-2 LEVEL_BOUNCE acceptance
    # branch, gate-3 lock heartbeats, shadow verdicts, and every other
    # auto_k function are UNAFFECTED — they run on the master AUTOK_ENABLED
    # flag as before. Flip to 1 to restore the pre-2026-09-02 behaviour.
    return _env_bool("AUTOK_PREMISE_ENABLED", "0")


def _accel_min() -> float:
    return _env_float("AUTOK_ACCEL_MIN", 1.0)


def _touched_lock_pips() -> float:
    return _env_float("AUTOK_TOUCHED_LOCK_PIPS", 5.0)


def _touched_lock_on_close() -> bool:
    # 2026-08-11: gate 3 arms on the completed 5m bar close, not the running
    # per-tick best_pnl_pips. Cases: 2026-08-07 13:15 EMA_PB_L locked at
    # +11.20 from a bar-high tick then ran to -14.5p uncut; 2026-08-11 both
    # open BB_BOUNCE positions locked at best=5.10 / best=10.30 and rode
    # adverse without an auto-cut. Default OFF — flag-off is byte-identical
    # to today.
    return _env_bool("AUTOK_TOUCHED_LOCK_ON_CLOSE", "0")


def _shadow_lock_pips() -> float:
    # 2026-08-15: counterfactual lock threshold used by the [AUTO-CUT-SHADOW*]
    # log line. When gate 3 (touched_favourable_lock) suppresses a live cut,
    # we also compute what the verdict would have been at this raised
    # threshold, gate the log by the shadow's own lock arithmetic, and log
    # only. Zero effect on live decisions.
    return _env_float("AUTOK_SHADOW_LOCK_PIPS", 8.0)


def _mae_min_default_pips() -> float:
    return _env_float("AUTOK_MAE_MIN_PIPS_DEFAULT", 6.0)


def _mae_min_briefing_pips() -> float:
    return _env_float("AUTOK_MAE_MIN_PIPS_BRIEFING", 10.0)


def _exclude_families() -> Tuple[str, ...]:
    # PIVOT_BREAK is on the default exclusion list because its coil-at-
    # pivot geometry expects a slow grind with small-negative MAE and
    # adverse velocity before the breakout — auto-K's velocity gate
    # would prematurely close the setup this strategy is built around.
    # See gbpusd_pivot_break.py module docstring, "No timeout" section.
    raw = _env("AUTOK_EXCLUDE", "NEWS_CONTINUATION,PIVOT_BREAK,H1_PIERCE,LEVEL_BOUNCE")
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


# ─── Family classification ─────────────────────────────────────────────────
# One family per mode. Family is a tag matched against AUTOK_EXCLUDE and
# used to select the MAE threshold. Substring match on the upper-cased
# mode string — order-sensitive so the most specific token wins first.
_FAMILY_ORDER: Tuple[Tuple[str, str, str], ...] = (
    # (family_tag, substring_match, threshold_tier)
    ("NEWS_CONTINUATION",     "NEWS_CONT_LEG",        "excluded"),
    ("PIVOT_BREAK",           "PIVOT_BREAK",          "excluded"),
    ("H1_PIERCE",             "H1_PIERCE",            "excluded"),
    # LEVEL_BOUNCE — three-candle level bounce (gbpusd_level_bounce.py).
    # Unmanaged by design: 100p SL is the only exit. Excluded from
    # auto_k so a premise-death cut can never override the SL.
    ("LEVEL_BOUNCE",          "LEVEL_BOUNCE",         "excluded"),
    ("BRIEFING_V5",           "BRIEFING_V5",          "briefing"),
    ("BRIEFING_EXECUTION",    "BRIEFING_EXECUTION",   "briefing"),
    ("BB_BOUNCE",             "BB_BOUNCE",            "default"),
    ("CONFIRMATION_FALLBACK", "CONFIRMATION_FALLBACK", "default"),
    ("EMA_PULLBACK",          "EMA_PULLBACK",         "default"),
    ("TREND_V3",              "TREND_V3",             "default"),
    ("STRUCTURE_BREAK",       "STRUCTURE_BREAK",      "default"),
)


def family_for_mode(mode: Any) -> Optional[str]:
    """Return family tag for a mode string, or None if the mode doesn't
    map to any of auto-K's supported families (auto-K skips it)."""
    if not mode:
        return None
    m = str(mode).upper()
    for tag, sub, _tier in _FAMILY_ORDER:
        if sub in m:
            return tag
    return None


def threshold_for_mode(mode: Any) -> Optional[float]:
    """Return the MAE threshold in pips for this mode, or None if the
    mode is EXCLUDED (per AUTOK_EXCLUDE) or unrecognised."""
    fam = family_for_mode(mode)
    if fam is None:
        return None
    excl = _exclude_families()
    if fam in excl:
        return None
    tier = None
    for tg, _sub, tr in _FAMILY_ORDER:
        if tg == fam:
            tier = tr
            break
    if tier == "briefing":
        return _mae_min_briefing_pips()
    return _mae_min_default_pips()


# ─── Kill-binding lookup (for the telegram label #) ────────────────────────
def _label_seq_for_trade(trade_id: str) -> Optional[int]:
    """Return the bb_bounce_labeller kill-binding sequence # for a trade,
    or None if no binding. Look-only — does not mutate the labeller."""
    try:
        import bb_bounce_labeller as _lb
        with _lb._lock:
            for seq, binding in list(_lb._kill_bindings.items()):
                if str(binding.get("trade_id") or "") == str(trade_id):
                    return int(seq)
    except Exception:
        return None
    return None


# ─── Telegram ──────────────────────────────────────────────────────────────
def _send_alert(pair_label: str, mode: str, direction: str,
                seq: Optional[int], price: float,
                mae_pips: float, accel: float) -> None:
    try:
        from telegram_alerts import send_telegram_message
        tag = f"#{seq}" if seq is not None else ""
        strat_short = str(mode).replace("GBPUSD_", "").replace("_", " ")
        send_telegram_message(
            f"<b>[AUTO-K]</b> closed {strat_short} {direction} {tag} "
            f"@ {float(price):.2f} MAE={mae_pips:.2f} accel={accel:.3f} "
            f"— premise-death cut ({pair_label})"
        )
    except Exception as exc:
        logger.warning("[AUTO-K] telegram alert failed: %s", exc)


def _emit_no_cut_heartbeat(
    mode: Any, direction: Any, mae_pips: Any,
    accel: Any, best_pnl_pips: Any, best_close_pnl_pips: Any, reason: str,
) -> None:
    # Caller (trade_manager.py) already invokes eval_and_close at most once
    # per position per completed 5m bar, so this line-per-return equals the
    # requested one-line-per-position-per-bar volume.
    try:
        mae_s = f"{float(mae_pips):.2f}" if mae_pips is not None else "-"
        accel_s = f"{float(accel):.3f}" if accel is not None else "-"
        best_s = f"{float(best_pnl_pips):.2f}" if best_pnl_pips is not None else "-"
        best_close_s = (
            f"{float(best_close_pnl_pips):.2f}"
            if best_close_pnl_pips is not None else "-"
        )
        logger.info(
            "[AUTO-CUT] eval %s %s mae=%s accel=%s best=%s best_close=%s"
            " -> NO_CUT (%s)",
            mode, direction, mae_s, accel_s, best_s, best_close_s, reason,
        )
    except Exception:
        pass


def _emit_shadow_verdict(
    *, mode: Any, direction_u: str, entry_price: float, current_price: float,
    ppp: float, threshold_pips: float,
    closes_5m: Sequence[float], highs_5m: Sequence[float],
    lows_5m: Sequence[float], lock_val: float,
) -> None:
    """When gate 3 suppresses a live cut, log the counterfactual verdict
    under AUTOK_SHADOW_LOCK_PIPS (default 8.0). Evaluates gates 1 and 2
    identically to the live path — same MAE arithmetic, same ribbon_state
    call, same accel/direction gates — and emits [AUTO-CUT-SHADOW{N}].
    Log-only; no close, no meta write, no telegram. Fail-open on any
    error (the heartbeat is diagnostic, not load-bearing)."""
    try:
        _shadow = _shadow_lock_pips()
        # If the live lock arms at ≥ shadow threshold too, gate 3 wins under
        # both configs — no counterfactual to report. This is the ≥8p bucket
        # (34% of current lock verdicts per the 08-15 dead-zone analysis).
        if lock_val >= _shadow:
            return
        if direction_u == "BUY":
            _pnl = (float(current_price) - float(entry_price)) / float(ppp)
        else:
            _pnl = (float(entry_price) - float(current_price)) / float(ppp)
        _mae = -_pnl
        _accel: Optional[float] = None
        _would_cut = False
        if _mae < float(threshold_pips):
            _reason = "mae_below_threshold"
        else:
            try:
                import ribbon_state as _rs
                rd = _rs.velocity_state(
                    list(closes_5m), list(highs_5m), list(lows_5m),
                )
            except Exception as _v_exc:
                _reason = f"velocity_state_error:{type(_v_exc).__name__}"
            else:
                _accel = rd.accel
                if rd.state != _rs.VelocityState.OK:
                    _reason = f"velocity_state_{rd.state.value}"
                elif rd.accel is None or float(rd.accel) < _accel_min():
                    _reason = "accel_below_min"
                else:
                    _adverse = -1 if direction_u == "BUY" else 1
                    if int(rd.dir_of_move) != _adverse:
                        _reason = "dir_not_adverse"
                    else:
                        _would_cut = True
                        _reason = "all_gates_pass"
        _accel_s = f"{float(_accel):.3f}" if _accel is not None else "-"
        logger.info(
            "[AUTO-CUT-SHADOW%d] eval %s %s would_cut=%s mae=%.2f accel=%s"
            " lock_val=%.2f live_lock=%.1f shadow_lock=%.1f — %s",
            int(_shadow), mode, direction_u,
            ("Y" if _would_cut else "N"), _mae, _accel_s,
            lock_val, _touched_lock_pips(), _shadow, _reason,
        )
    except Exception as _exc:
        logger.debug("[AUTO-CUT-SHADOW] emit failed: %s", _exc)


# ─── Public evaluator ──────────────────────────────────────────────────────
def _qm_accept_closes() -> int:
    """QM_KILL_ACCEPT_CLOSES — consecutive 5m closes required beyond the
    level to accept invalidation. Default 2 per SESSION 2 spec §6.2/§9."""
    return max(1, int(_env_float("QM_KILL_ACCEPT_CLOSES", 2)))


def _qm_accept_bars() -> int:
    """QM_KILL_ACCEPT_BARS — number of bars the acceptance state must
    hold (window over which every close must be beyond the level).
    Default 2."""
    return max(1, int(_env_float("QM_KILL_ACCEPT_BARS", 2)))


def _eval_level_bounce_acceptance(
    *, epic: str, pos_key: str, pair: str, mode: str, direction_u: str,
    entry_price: float, current_price: float, ppp: float,
    closes_5m: Sequence[float],
    strategy_meta: Dict[str, Any],
    trade_id: Optional[str], now_utc: Optional[datetime],
) -> Dict[str, Any]:
    """LEVEL_BOUNCE premise-kill via ACCEPTANCE EVIDENCE (SESSION 2).

    Kill iff every one of the last max(CLOSES, BARS) 5m closes lies on
    the adverse side of the reclaimed/lost level:
      - BUY (S1/S2/S3 reclaimed from below) → close < level_price
      - SELL (R1/R2/R3 lost from above)     → close > level_price

    A sweep-through that closes back inside the window (any single close
    on the level's protected side) NEVER kills — the acceptance criterion
    resets on interruption because the window is a strict all()-check.

    Between penetration and acceptance, this authority does not close the
    position; the attached broker SL (100p per gbpusd_level_bounce.py
    STOP_PIPS) remains the sole catastrophic-protection authority.
    """
    level_price = strategy_meta.get("level_price")
    if level_price is None:
        _emit_no_cut_heartbeat(
            mode, direction_u, None, None, None, None,
            "level_price_missing",
        )
        return {
            "kind": "NO_CUT", "reason": "level_price_missing",
            "mode": mode, "direction": direction_u,
        }
    try:
        level_price_f = float(level_price)
    except (TypeError, ValueError):
        return {
            "kind": "NO_CUT", "reason": "level_price_unparseable",
            "mode": mode, "direction": direction_u,
        }
    n_closes = _qm_accept_closes()
    n_bars = _qm_accept_bars()
    window = max(n_closes, n_bars)
    if len(closes_5m) < window:
        _emit_no_cut_heartbeat(
            mode, direction_u, None, None, None, None,
            "acceptance_window_short",
        )
        return {
            "kind": "NO_CUT", "reason": "acceptance_window_short",
            "window": window, "closes_len": len(closes_5m),
            "level_price": level_price_f,
        }
    tail = [float(c) for c in closes_5m[-window:]]
    if direction_u == "BUY":
        all_beyond = all(c < level_price_f for c in tail)
    else:
        all_beyond = all(c > level_price_f for c in tail)
    if not all_beyond:
        _emit_no_cut_heartbeat(
            mode, direction_u, None, None, None, None,
            "acceptance_not_met",
        )
        return {
            "kind": "NO_CUT", "reason": "acceptance_not_met",
            "level_price": level_price_f,
            "tail_closes": tail,
            "closes_required": n_closes,
            "bars_required": n_bars,
            "window": window,
        }
    if direction_u == "BUY":
        pnl_pips = (float(current_price) - float(entry_price)) / ppp
    else:
        pnl_pips = (float(entry_price) - float(current_price)) / ppp
    mae_pips = -pnl_pips
    seq = _label_seq_for_trade(str(trade_id or ""))
    _send_alert(pair, mode, direction_u, seq,
                float(current_price), float(mae_pips), 0.0)
    close_ok = False
    try:
        from trade_executor import close_position
        _res = close_position(pos_key=pos_key, reason=REASON_CODE)
        close_ok = _res is not None
    except Exception as exc:
        logger.error(
            "[AUTO-K] LEVEL_BOUNCE acceptance close_position raised "
            "for %s: %s", pos_key, exc, exc_info=True,
        )
    decision = {
        "kind": "CUT",
        "reason_code": REASON_CODE,
        "reason": "level_bounce_acceptance",
        "epic": epic, "pos_key": pos_key, "pair": pair, "mode": mode,
        "direction": direction_u,
        "current_price": float(current_price),
        "entry_price": float(entry_price),
        "pnl_pips": float(pnl_pips),
        "mae_pips": float(mae_pips),
        "level_price": level_price_f,
        "level_name": strategy_meta.get("level_name"),
        "level_side": strategy_meta.get("level_side"),
        "closes_required": n_closes,
        "bars_required": n_bars,
        "window": window,
        "tail_closes": tail,
        "label_seq": seq,
        "close_dispatched": close_ok,
        "ts_utc": (now_utc or datetime.now(timezone.utc)).isoformat(),
    }
    logger.warning(
        "[AUTO-K] LEVEL_BOUNCE CUT %s %s @ %.5f MAE=%.2fp level=%.5f "
        "tail=%s window=%d close_ok=%s",
        mode, direction_u, float(current_price), float(mae_pips),
        level_price_f, tail, window, close_ok,
    )
    return decision


def eval_and_close(
    *,
    epic: str,
    pos_key: str,
    pair: str,
    mode: str,
    direction: str,
    entry_price: float,
    current_price: float,
    ppp: float,
    best_pnl_pips: float,
    closes_5m: Sequence[float],
    highs_5m: Sequence[float],
    lows_5m: Sequence[float],
    trade_id: Optional[str] = None,
    now_utc: Optional[datetime] = None,
    best_close_pnl_pips: Optional[float] = None,
    strategy_meta: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Evaluate auto-K on a single open position. Returns a dict describing
    the decision (kind in {"CUT", "NO_CUT"}), or None if the module is
    disabled / the mode is excluded / no evaluation was performed.

    `strategy_meta` is a strategy-provided context dict (typically a copy
    of decision.debug from EPIC_STATE[pk]["decision_debug"]). LEVEL_BOUNCE
    uses `level_price`, `level_name`, and `level_side` from it to run the
    ACCEPTANCE EVIDENCE premise-kill instead of the generic MAE test.
    """
    try:
        if not _enabled():
            return None
        direction_u = str(direction).upper()
        if direction_u not in ("BUY", "SELL"):
            return None
        _ppp = float(ppp) if ppp else 1.0

        # 2026-08-26 SESSION 2 — LEVEL_BOUNCE ACCEPTANCE EVIDENCE branch.
        # LEVEL_BOUNCE's premise-kill is a fundamentally different rule: a
        # slow-classifier's MAE threshold cannot RETIRE a fade that hasn't
        # been ACCEPTED by price. Kill only when the level has been
        # decisively lost/reclaimed by N consecutive 5m closes beyond it,
        # sustained through M bars — a sweep-through that closes back
        # inside never kills. Broker SL (attached to the deal at open,
        # see gbpusd_level_bounce.py's 100p STOP_PIPS + trade_executor's
        # open_sb_now(size, sl, tp) call at ~2094) remains the sole
        # catastrophic-protection authority; auto_k neither reads nor
        # modifies it and only ever calls close_position at market.
        _fam = family_for_mode(mode)
        _excl = _exclude_families()
        if _fam in _excl:
            return None  # explicit env exclusion — no eval, no CUT.
        if _fam == "LEVEL_BOUNCE":
            return _eval_level_bounce_acceptance(
                epic=epic, pos_key=pos_key, pair=pair, mode=mode,
                direction_u=direction_u,
                entry_price=float(entry_price),
                current_price=float(current_price),
                ppp=_ppp, closes_5m=closes_5m,
                strategy_meta=strategy_meta or {},
                trade_id=trade_id, now_utc=now_utc,
            )

        # ── PREMISE BRANCH KILL SWITCH (2026-09-02) ──────────────────────
        # AUTOK_PREMISE_ENABLED=0 (default) makes the MAE + ribbon-velocity
        # premise-death cut inert while leaving the LEVEL_BOUNCE acceptance
        # branch above and every other auto_k function untouched. Retired
        # on counterfactual evidence — see _premise_enabled() docstring and
        # reports-public/host161_autok_labelk_counterfactual_20260902.md.
        if not _premise_enabled():
            _emit_no_cut_heartbeat(
                mode, direction_u, None, None, best_pnl_pips,
                best_close_pnl_pips, "premise_disabled",
            )
            return {
                "kind": "NO_CUT", "reason": "premise_disabled",
                "flag": "AUTOK_PREMISE_ENABLED=0",
            }

        threshold_pips = threshold_for_mode(mode)
        if threshold_pips is None:
            return None  # excluded / unrecognised

        # Gate 3: never-touched-+lock guard (wobble-winner protection).
        # 2026-08-11: when AUTOK_TOUCHED_LOCK_ON_CLOSE=1, arm on the
        # completed-bar-close ratchet (best_close_pnl_pips) rather than the
        # per-tick MFE (best_pnl_pips). See _touched_lock_on_close() for the
        # motivating cases.
        _lock_on_close = (
            _touched_lock_on_close() and best_close_pnl_pips is not None
        )
        _lock_val = (
            float(best_close_pnl_pips) if _lock_on_close
            else float(best_pnl_pips)
        )
        _lock_field = "best_close_pnl_pips" if _lock_on_close else "best_pnl_pips"
        if _lock_val >= _touched_lock_pips():
            _emit_no_cut_heartbeat(
                mode, direction_u, None, None, best_pnl_pips,
                best_close_pnl_pips, "touched_favourable_lock",
            )
            # Shadow-only counterfactual: what would the verdict be if the
            # lock threshold were raised to AUTOK_SHADOW_LOCK_PIPS? Answers
            # the operator's 2026-08-15 dead-zone question (54/82 lock
            # verdicts sit in the [5, 8) band). Log-only — no acting.
            _emit_shadow_verdict(
                mode=mode, direction_u=direction_u,
                entry_price=float(entry_price),
                current_price=float(current_price), ppp=_ppp,
                threshold_pips=float(threshold_pips),
                closes_5m=closes_5m, highs_5m=highs_5m, lows_5m=lows_5m,
                lock_val=_lock_val,
            )
            return {
                "kind": "NO_CUT", "reason": "touched_favourable_lock",
                _lock_field: _lock_val,
                "touched_lock_pips": _touched_lock_pips(),
            }

        # Gate 1: MAE — pnl_pips vs current price (unrealized excursion).
        if direction_u == "BUY":
            pnl_pips = (float(current_price) - float(entry_price)) / _ppp
        else:
            pnl_pips = (float(entry_price) - float(current_price)) / _ppp
        mae_pips = -pnl_pips  # positive when underwater
        if mae_pips < float(threshold_pips):
            _emit_no_cut_heartbeat(
                mode, direction_u, mae_pips, None, best_pnl_pips,
                best_close_pnl_pips, "mae_below_threshold",
            )
            return {
                "kind": "NO_CUT", "reason": "mae_below_threshold",
                "mae_pips": float(mae_pips),
                "threshold_pips": float(threshold_pips),
            }

        # Gate 2: velocity — adverse, accelerating, not dead tape.
        try:
            import ribbon_state as _rs
            rd = _rs.velocity_state(
                list(closes_5m), list(highs_5m), list(lows_5m),
            )
        except Exception as exc:
            logger.debug("[AUTO-K] velocity_state raised (abstain): %s", exc)
            _emit_no_cut_heartbeat(
                mode, direction_u, mae_pips, None, best_pnl_pips,
                best_close_pnl_pips,
                f"velocity_state_error:{type(exc).__name__}",
            )
            return {
                "kind": "NO_CUT", "reason": "velocity_state_error",
                "mae_pips": float(mae_pips),
                "error": type(exc).__name__,
            }
        if rd.state != _rs.VelocityState.OK:
            _emit_no_cut_heartbeat(
                mode, direction_u, mae_pips, rd.accel, best_pnl_pips,
                best_close_pnl_pips, f"velocity_state_{rd.state.value}",
            )
            return {
                "kind": "NO_CUT", "reason": f"velocity_state_{rd.state.value}",
                "mae_pips": float(mae_pips),
            }
        if rd.accel is None or float(rd.accel) < _accel_min():
            _emit_no_cut_heartbeat(
                mode, direction_u, mae_pips, rd.accel, best_pnl_pips,
                best_close_pnl_pips, "accel_below_min",
            )
            return {
                "kind": "NO_CUT", "reason": "accel_below_min",
                "mae_pips": float(mae_pips),
                "accel": (float(rd.accel) if rd.accel is not None else None),
                "accel_min": _accel_min(),
            }
        adverse_dir = -1 if direction_u == "BUY" else 1
        if int(rd.dir_of_move) != adverse_dir:
            _emit_no_cut_heartbeat(
                mode, direction_u, mae_pips, rd.accel, best_pnl_pips,
                best_close_pnl_pips, "dir_not_adverse",
            )
            return {
                "kind": "NO_CUT", "reason": "dir_not_adverse",
                "mae_pips": float(mae_pips),
                "dir_of_move": int(rd.dir_of_move),
                "adverse_dir": adverse_dir,
            }

        # All gates pass — CUT.
        seq = _label_seq_for_trade(str(trade_id or ""))
        _send_alert(pair, mode, direction_u, seq,
                    float(current_price), float(mae_pips), float(rd.accel))

        close_ok = False
        try:
            from trade_executor import close_position
            _res = close_position(pos_key=pos_key, reason=REASON_CODE)
            close_ok = _res is not None
        except Exception as exc:
            logger.error("[AUTO-K] close_position raised for %s: %s",
                         pos_key, exc, exc_info=True)

        decision = {
            "kind": "CUT",
            "reason_code": REASON_CODE,
            "epic": epic,
            "pos_key": pos_key,
            "pair": pair,
            "mode": mode,
            "direction": direction_u,
            "current_price": float(current_price),
            "entry_price": float(entry_price),
            "pnl_pips": float(pnl_pips),
            "mae_pips": float(mae_pips),
            "threshold_pips": float(threshold_pips),
            "best_pnl_pips": float(best_pnl_pips),
            "best_close_pnl_pips": (
                float(best_close_pnl_pips)
                if best_close_pnl_pips is not None else None
            ),
            "vel_3": (float(rd.vel_3) if rd.vel_3 is not None else None),
            "vel_12": (float(rd.vel_12) if rd.vel_12 is not None else None),
            "accel": float(rd.accel),
            "atr_mult": (float(rd.atr_mult) if rd.atr_mult is not None else None),
            "dir_of_move": int(rd.dir_of_move),
            "label_seq": seq,
            "close_dispatched": close_ok,
            "ts_utc": (now_utc or datetime.now(timezone.utc)).isoformat(),
        }
        logger.warning(
            "[AUTO-K] CUT %s %s %s @ %.5f MAE=%.2fp accel=%.3f "
            "best_pnl=%.2f close_ok=%s",
            mode, direction_u, epic, float(current_price),
            float(mae_pips), float(rd.accel), float(best_pnl_pips), close_ok,
        )
        return decision
    except Exception as exc:
        logger.debug("[AUTO-K] eval_and_close error (fail-open): %s",
                     exc, exc_info=True)
        return None
