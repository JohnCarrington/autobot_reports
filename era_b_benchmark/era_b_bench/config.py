"""Era B pinned constants + UNKNOWNS list.

Every constant carries a citation to §... of the spec or a git commit
that established it. Values marked UNKNOWN or ASSUMED are the ones
Project Thirty must confirm before a live DEMO run.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List


# ─── Price scale ────────────────────────────────────────────────────────
# data/candles/GBPUSD/*.csv stores prices as GBPUSD_mid × 10000.
# One pip = 0.0001 = 1.0 CSV unit. Verified in the third-candle-break
# report against deal DIAAAAXMR2E6ZA2 (entry 13416.45, realised −20.70p).
PIP_UNITS = 1.0


# ─── Session filter (spec §2.1, §4) ─────────────────────────────────────
# WIN_START/WIN_END are UTC and weekend-excluded.
WIN_START = time(6, 0)      # env GBPUSD_BB_BOUNCE_WIN_START_H = 6
WIN_END   = time(17, 0)     # env GBPUSD_BB_BOUNCE_WIN_END_H   = 17


# ─── Bollinger Bands (spec §2.2, §4) ────────────────────────────────────
BB_LEN = 20
BB_STD = 2.0


# ─── Entry — pierce setup (spec §2.3) ───────────────────────────────────
# Code default at Era B (commit c85481c): 0.5 pips (via commit 232076c).
# The .env at that time is NOT recoverable (env-history archive begins
# 2026-09-21). Two plausible effective values: 0.5 (code default) or
# 2.0 (an operator override; the current .env sets 2.0 per spec §4).
# → UNKNOWN. Benchmark runs both and reports which yields 36 matched
# fires; see parity report §Sensitivity.
PIERCE_THRESH_PIPS_CANDIDATES = [0.5, 2.0]
PIERCE_THRESH_PIPS_DEFAULT = 0.5   # code default at c85481c


# ─── Entry — rejection candle (spec §2.4) ───────────────────────────────
# All three of these were on the code defaults during Era B. No commit
# in the git range 2026-04-30 .. 2026-06-24 changed them.
REJECTION_WINDOW_BARS      = 3    # env GBPUSD_BB_BOUNCE_REJECTION_WINDOW_BARS
MIN_REJECTION_BODY_PIPS    = 1.5  # env GBPUSD_BB_BOUNCE_MIN_REJECTION_BODY_PIPS
REJECTION_TOLERANCE_PIPS   = 1.0  # env GBPUSD_BB_BOUNCE_REJECTION_TOLERANCE_PIPS

# Adaptive rejection body: commit 77414d3 landed 2026-08-07 (Era E).
# NOT active in Era B — hard-coded off here.
ADAPTIVE_BODY_ENABLED = False

# Near-touch setup path: commit added 2026-07-10 (Era D). NOT active
# in Era B — the pierce path is the only path.
NEAR_TOUCH_ENABLED = False


# ─── Entry — direction (spec §2.5) ──────────────────────────────────────
# This benchmark implements the SHORT side only (BB_BOUNCE_S). LONG side
# is a symmetric mirror and out of scope.
DIRECTION = "SELL"


# ─── Risk (spec §5 Era B row) ───────────────────────────────────────────
# Era B *effective* values, per the ledger. Code defaults at c85481c
# were 12p SL; env override widened to 20p on 2026-05-23.
SL_PIPS         = 20.0
BROKER_TP_PIPS  = 100.0    # sentinel — hit by ~0 % of Era B fills in practice
TP1_FALLBACK_PIPS = 30.0   # used only for briefing tier — see UNKNOWNS


# ─── Scale-out (spec §3.2) ──────────────────────────────────────────────
SCALE_OUT_TRIGGER_PIPS = 10.0     # env SCALE_OUT_TRIGGER_PIPS
SCALE_OUT_FRACTION     = 0.5      # env SCALE_OUT_FRACTION
# Scale-out requires size >= 2.0 in the real trader (trade_manager.py:
# 3627). The benchmark deliberately ignores this size gate: it assumes
# scale-out fires whenever the +10 p MFE condition is met, at any
# stake. This matches the ledger's behaviour on the 141/172 fills that
# have populated total_pnl_pips (audit §2), where QM / EW multipliers
# had bumped size above 2.0.


# ─── Post-scale runner (spec §3.3) ──────────────────────────────────────
# Runner SL after scale-out moves to entry (BE).
RUNNER_BE_OFFSET_PIPS = 0.0

# Floor stop (BB_BOUNCE_POST_SCALE_FLOOR): the actual Era B code adds a
# +5p floor once MFE >= 10p once scaled and BE-amend confirmed. We
# leave it OFF in this benchmark for two reasons:
#   1. The floor requires a broker-side BE amend confirmation, which
#      we cannot simulate from OHLC.
#   2. Testing showed the floor rarely bites within 240m on GBPUSD 5m.
# Enabling it would require a tick-level rebound test.
POST_SCALE_FLOOR_ENABLED = False

# Runner trail (GBPUSD_BB_BOUNCE_S_RUNNER_TRAIL_LOCK_PIPS = 4): tick-
# based, cannot be simulated from 5m OHLC. → UNKNOWN for benchmark.
RUNNER_TRAIL_ENABLED = False


# ─── Hold time (spec §3.7) ──────────────────────────────────────────────
MAX_HOLD_MIN  = 240
MAX_HOLD_BARS = MAX_HOLD_MIN // 5   # 48


# ─── Within-bar ordering (report §1.4, adopted convention) ─────────────
# ADVERSE-FIRST: on any bar, check SL / BE-stop before scale-out / TP.
# Conservative for both SHORT and LONG. Symmetric across baseline and
# alt in the earlier report; retained here for consistency.
ADVERSE_FIRST = True


# ─── Stake ──────────────────────────────────────────────────────────────
# Nominal £1/pip @ size 1.0. Matches audit §2 assumption. Actual per-
# deal size in Era B is unknown from the ledger (only pip P&L stored).
STAKE_GBP_PER_PIP = 1.0


# ─── Broker submission ─────────────────────────────────────────────────
# HARD-CODED disabled. This benchmark has no IG imports; the token
# below is only for callers that want to assert the state.
IG_SUBMISSION_ENABLED = False
BROKER = "NONE (benchmark; simulation only)"


# ─── UNKNOWNS: parameters the spec + deal CSV cannot establish ─────────
@dataclass(frozen=True)
class Unknown:
    name: str
    where_used: str
    reason: str
    default_taken: str


UNKNOWNS: List[Unknown] = [
    Unknown(
        name="PIERCE_THRESH_PIPS (Era B effective)",
        where_used="entry.detect_pierce_setup — depth beyond BBU that the setup wick must reach",
        reason="Code default at c85481c was 0.5p (via 232076c). Live .env value cannot be recovered — env-history archive begins 2026-09-21. Current .env (spec §4) shows 2.0.",
        default_taken="0.5 (code default), also run at 2.0; parity report picks the value that yields best signal match.",
    ),
    Unknown(
        name="Cascade-disagree gate",
        where_used="entry filter that removed pierces conflicting with the cascade direction",
        reason="Active in Era B per spec §5 (commit 7af663d, still ON post-Era-A). Algorithm and inputs not stated in the spec; requires cascade-vector regime module. Not implemented in benchmark.",
        default_taken="OFF. Benchmark may over-fire vs ledger; false-positives flagged.",
    ),
    Unknown(
        name="regime_filter_trending gate",
        where_used="entry filter that suppressed fires during trending regimes",
        reason="Active in Era B per spec §5 (restored 2026-05-13 via commit 1c28480 after brief removal). Algorithm not specified. Not implemented.",
        default_taken="OFF. May over-fire vs ledger; false-positives flagged.",
    ),
    Unknown(
        name="Counter-H1 BB-pierce-reversal build",
        where_used="entry rules extended around H1 direction from 2026-05-23 (commit e8fc9dd)",
        reason="Commit message says 'the reversal half of the opportunity' but the spec doesn't detail the semantics. Not implemented.",
        default_taken="OFF. Any fires that depended on counter-H1 logic will differ.",
    ),
    Unknown(
        name="Per-fill position size",
        where_used="scale-out size gate + £ conversion",
        reason="Ledger stores pips only; audit §2 flags £ P&L as unverified. QM / EW multipliers in trade_executor.py:3549-3661 can bump size to 2.0+ but the moment is not logged per deal.",
        default_taken="1.0. Scale-out fires unconditionally when +10p MFE reached (see config.SCALE_OUT_FRACTION note).",
    ),
    Unknown(
        name="Within-bar tick order",
        where_used="whether SL or scale-out fires first on the same 5m bar",
        reason="5m OHLC hides the tick sequence. Adverse-first is the pessimistic convention (report §1.4).",
        default_taken="Adverse-first.",
    ),
    Unknown(
        name="Executable bid/ask at entry / partial-close / exit",
        where_used="realised pips at broker granularity",
        reason="Tick archive covers 2024-01 → 2026-04-10; Era B is beyond. Benchmark uses candle close / OHLC crossings as fill proxy.",
        default_taken="Mid-price fills. Real broker would add spread + slippage of ~0.6-1.0 p per fill; not modelled.",
    ),
    Unknown(
        name="Soft-exit reproduction (TRAIL_STOP, QM_BAND_CLOSE_INSIDE, BRIEFING_TP1_CLOSE, BRIEFING_TP_SL_OPEN, STRUCTURE_EXIT, BB_FLIP, BB_RANGE_TARGET, EXTERNAL_MANUAL, IG_RECONCILE, LABEL_K_OPERATOR, PRE_NEWS_CLOSE, NY_CLOSE, EXIT_PROFILE_SQUEEZE, AUTO_K_PREMISE)",
        where_used="close_reason of many Era B fills",
        reason="These exits require live briefing / regime / structure / operator inputs that this benchmark deliberately does not import. 5m OHLC cannot decide them.",
        default_taken="Not reproduced. Parity report flags any ledger deal whose close_reason falls in this set as 'exit_unreproducible'.",
    ),
]


UNREPRODUCIBLE_CLOSE_REASONS = {
    # Soft exits — require live subsystems this benchmark does not import
    "TRAIL_STOP",
    "QM_BAND_CLOSE_INSIDE",
    "BRIEFING_TP1_CLOSE",
    "BRIEFING_TP_SL_OPEN",
    "GBPUSD_BB_BOUNCE_S_TIER_SL_OPEN",
    "STRUCTURE_EXIT",
    "BB_FLIP",
    "BB_RANGE_TARGET",
    "EXTERNAL_MANUAL",
    "IG_RECONCILE",
    "LABEL_K_OPERATOR",
    "PRE_NEWS_CLOSE",
    "NY_CLOSE",
    "EXIT_PROFILE_SQUEEZE",
    "AUTO_K_PREMISE",
    "MANAGER_PROFIT_PROTECT",
    # Broker-side exits — the benchmark's SL / TP / BE-hit are similar
    # but not bit-identical (spread / slippage / server-side timing).
    "BE_HIT_IG",
}

REPRODUCIBLE_CLOSE_REASONS = {
    "SL_HIT",
    "TP_HIT",
    "BE_STOP_POST_SCALEOUT",
    "FLOOR_STOP_POST_SCALEOUT",   # only if POST_SCALE_FLOOR_ENABLED
    "REGIME_MAX_HOLD",
}
