"""Era B .env history — reconstructed from backups/*.env snapshots.

Provenance: /opt/tradingbot/backups/{scaleout_20260523, bb_bounce_counter_h1_20260523,
env-batch2-stranglers-20260524T152536Z, cascade-gate-disable-20260525T170419Z,
env-pierce-comment-fix-20260525T183638Z, .env.bak.bb_trail-pre.20260605_035226,
.env.bak.pierce_thresh-pre.20260605_041746, .env.bak.structure_break_enable-pre.20260615_120821,
.env.2026-06-16T120455Z.bak}.

Each snapshot is a "PRE" backup — captures state IMMEDIATELY BEFORE a change.
So the config valid in a window [t_i, t_{i+1}) is the config from snapshot_i.

Reduced schema (only fields the benchmark reads).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass(frozen=True)
class EnvSnapshot:
    """A subset of .env keys the Era B benchmark cares about."""
    valid_from:               datetime          # inclusive
    valid_to:                 Optional[datetime]  # exclusive; None → open-ended (Era B end)
    source:                   str               # path of the backup file
    pierce_thresh_pips:       float
    rejection_tolerance_pips: float
    h1_counter_gate_enabled:  bool              # env override; code default is True
    briefing_tp_enabled:      bool              # gates the tier machinery
    runner_trail_enabled:     bool
    runner_trail_activate_pips: float
    runner_trail_offset_pips:   float
    scale_out_trigger_pips:   float
    scale_out_fraction:       float
    sl_pips:                  float
    news_blackout_enabled:    bool
    regime_filter_enabled:    bool
    cascade_gate_enabled:     bool
    macd_extended_momentum_gate_enabled: bool


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ─── Era B env-history table ────────────────────────────────────────────
# Each entry is the state VALID FROM its timestamp until the NEXT entry.
# Sources are the backup files that captured the "PRE" state (i.e., the
# state in force UNTIL the next change was applied).
#
# Key observations:
#   - Every gate other than the base pierce+rejection was OFF in Era B
#     per every snapshot inspected. The spec's earlier claim that
#     cascade / regime filters were "active" was incorrect for Era B.
#   - PIERCE_THRESH_PIPS moved: 0.5 → 2.0 (2026-05-23) → 0.5 (2026-06-05)
#     → 1.0 (2026-06-05) → 1.0 (through 2026-06-24).
#   - Runner trail flipped ON at 2026-06-05 03:52 UTC. Before that, no
#     trail; after that, ACTIVATE=12p / OFFSET=6p.
#   - SCALE_OUT_TRIGGER_PIPS tightened 10 → 8 sometime before 2026-06-15.
#   - BRIEFING_TP_ENABLED went 1 → 0 between 05-23 17:34 and 05-25 08:51.
ERA_B_HISTORY: List[EnvSnapshot] = [
    EnvSnapshot(
        valid_from = _dt("2026-05-23T00:00:00"),
        valid_to   = _dt("2026-05-24T15:25:36"),  # env-batch2-stranglers
        source     = "backups/bb_bounce_counter_h1_20260523/.env (@2026-05-23T17:34)",
        pierce_thresh_pips       = 0.5,
        rejection_tolerance_pips = 1.0,        # env absent → code default 1.0
        h1_counter_gate_enabled  = True,       # code default; env not set here (pre e8fc9dd's env update)
        briefing_tp_enabled      = True,
        runner_trail_enabled     = False,
        runner_trail_activate_pips = 12.0,
        runner_trail_offset_pips   = 6.0,
        scale_out_trigger_pips   = 10.0,
        scale_out_fraction       = 0.5,
        sl_pips                  = 20.0,       # widened by c85481c
        news_blackout_enabled    = False,
        regime_filter_enabled    = False,
        cascade_gate_enabled     = False,
        macd_extended_momentum_gate_enabled = False,
    ),
    EnvSnapshot(
        valid_from = _dt("2026-05-24T15:25:36"),
        valid_to   = _dt("2026-05-25T08:51:23"),  # BRIEFING_TP flipped off between here
        source     = "backups/env-batch2-stranglers-20260524T152536Z/.env",
        pierce_thresh_pips       = 2.0,
        rejection_tolerance_pips = 0.5,
        h1_counter_gate_enabled  = True,       # env not present → code default (True)
        briefing_tp_enabled      = True,
        runner_trail_enabled     = False,
        runner_trail_activate_pips = 12.0,
        runner_trail_offset_pips   = 6.0,
        scale_out_trigger_pips   = 10.0,
        scale_out_fraction       = 0.5,
        sl_pips                  = 20.0,
        news_blackout_enabled    = False,
        regime_filter_enabled    = False,
        cascade_gate_enabled     = False,
        macd_extended_momentum_gate_enabled = False,
    ),
    EnvSnapshot(
        valid_from = _dt("2026-05-25T08:51:23"),
        valid_to   = _dt("2026-06-05T03:52:26"),  # bb_trail-pre → RUNNER_TRAIL flipped on
        source     = "backups/clean-run-flips-20260525T085123Z/.env",
        pierce_thresh_pips       = 2.0,
        rejection_tolerance_pips = 0.5,
        h1_counter_gate_enabled  = False,     # env explicitly false starting somewhere in this window
        briefing_tp_enabled      = False,     # DEAD per the .env comment; ledger's BRIEFING_TP* closes unexplained
        runner_trail_enabled     = False,
        runner_trail_activate_pips = 12.0,
        runner_trail_offset_pips   = 6.0,
        scale_out_trigger_pips   = 10.0,
        scale_out_fraction       = 0.5,
        sl_pips                  = 20.0,
        news_blackout_enabled    = False,
        regime_filter_enabled    = False,
        cascade_gate_enabled     = False,
        macd_extended_momentum_gate_enabled = False,
    ),
    EnvSnapshot(
        valid_from = _dt("2026-06-05T03:52:26"),   # bb_trail-pre captured, trail about to be flipped
        valid_to   = _dt("2026-06-05T04:17:46"),  # pierce_thresh-pre captured, thresh about to change
        source     = "backups/.env.bak.bb_trail-pre.20260605_035226",
        pierce_thresh_pips       = 0.5,        # env still 0.5 in this snapshot
        rejection_tolerance_pips = 0.5,
        h1_counter_gate_enabled  = False,
        briefing_tp_enabled      = False,
        runner_trail_enabled     = False,     # about to flip on
        runner_trail_activate_pips = 12.0,
        runner_trail_offset_pips   = 6.0,
        scale_out_trigger_pips   = 10.0,
        scale_out_fraction       = 0.5,
        sl_pips                  = 20.0,
        news_blackout_enabled    = False,
        regime_filter_enabled    = False,
        cascade_gate_enabled     = False,
        macd_extended_momentum_gate_enabled = False,
    ),
    EnvSnapshot(
        valid_from = _dt("2026-06-05T04:17:46"),   # pierce_thresh-pre captured, still 0.5; trail=1 already
        valid_to   = _dt("2026-06-15T07:00:00"),  # structure_break_enable-pre shows pierce=1.0 already
        source     = "backups/.env.bak.pierce_thresh-pre.20260605_041746 → (thresh set to 1.0 right after)",
        pierce_thresh_pips       = 1.0,        # inferred: change applied at 04:17:46
        rejection_tolerance_pips = 0.5,
        h1_counter_gate_enabled  = False,
        briefing_tp_enabled      = False,
        runner_trail_enabled     = True,      # trail was just enabled at 03:52
        runner_trail_activate_pips = 12.0,
        runner_trail_offset_pips   = 6.0,
        scale_out_trigger_pips   = 10.0,
        scale_out_fraction       = 0.5,
        sl_pips                  = 20.0,
        news_blackout_enabled    = False,
        regime_filter_enabled    = False,
        cascade_gate_enabled     = False,
        macd_extended_momentum_gate_enabled = False,
    ),
    EnvSnapshot(
        valid_from = _dt("2026-06-15T07:00:00"),
        valid_to   = None,   # runs to Era B end (2026-06-24 23:59)
        source     = "backups/.env.bak.structure_break_enable-pre.20260615_120821 → +2026-06-16T120455Z snapshot",
        pierce_thresh_pips       = 1.0,
        rejection_tolerance_pips = 0.5,
        h1_counter_gate_enabled  = False,
        briefing_tp_enabled      = False,
        runner_trail_enabled     = True,
        runner_trail_activate_pips = 12.0,
        runner_trail_offset_pips   = 6.0,
        scale_out_trigger_pips   = 8.0,       # tightened before 06-15
        scale_out_fraction       = 0.5,
        sl_pips                  = 20.0,
        news_blackout_enabled    = False,
        regime_filter_enabled    = False,
        cascade_gate_enabled     = False,
        macd_extended_momentum_gate_enabled = False,
    ),
]


def env_at(ts: datetime) -> EnvSnapshot:
    """Return the env snapshot valid at ts. Falls back to the last
    snapshot for any ts past Era B end."""
    for snap in ERA_B_HISTORY:
        end = snap.valid_to or datetime(2099, 1, 1, tzinfo=timezone.utc)
        if snap.valid_from <= ts < end:
            return snap
    return ERA_B_HISTORY[-1]


# ─── Distinct pierce thresholds observed in Era B env history ───────────
# For sensitivity / variant runs, these are the discrete values worth
# testing separately. Do NOT collapse them into a single "best fit" — the
# thresholds moved during the period and each variant models a different
# slice.
DISTINCT_PIERCE_THRESHOLDS = [0.5, 1.0, 2.0]
