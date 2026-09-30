"""standdown_shadow — telemetry for the BB_BOUNCE STRONG_TREND standdown.

Computes THREE candidate verdicts alongside the actual standdown decision
and writes one JSONL row + one INFO log line per consult. Never raises,
never mutates the actual decision — the standdown block that calls into
this module is byte-identical whether or not this file exists.

Candidate verdicts (all env-configurable thresholds):
  - verdict_dwell_n6:  PERMIT if the current STRONG_TREND label has held
                       for fewer than 6 consecutive 5m closes; else SUPPRESS.
  - verdict_dwell_n8:  as above with 8.
  - verdict_pathconf:  PERMIT if regime_label_path == "struct" AND
                       confidence_final < PATHCONF_FLOOR (default 0.30);
                       else "SUPPRESS-as-actual" (i.e. inherits the
                       actual decision so this candidate doesn't
                       independently permit outside the low-confidence
                       struct-promoted zone).

dwell_run_length source: tails the last ~200 lines of
logs/regime_engine.jsonl and counts consecutive rows for the given
symbol whose winning_regime equals `regime`. Stateless — no in-memory
deque, no callback wiring. If the tail can't be read (missing file,
permission, bad JSON), dwell_run_length is None and the two dwell
verdicts are recorded as "UNKNOWN".

Outcome fields `mfe_pips` and `mae_pips` are always emitted as null;
the EOD backfill job (`scripts/standdown_shadow_backfill_outcomes.py`)
fills them once per day.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("AutoBot")

SHADOW_LOG_PATH = Path(
    os.getenv(
        "STANDDOWN_SHADOW_LOG_PATH",
        "/opt/tradingbot/logs/standdown_shadow.jsonl",
    )
)
REGIME_LOG_PATH = Path(
    os.getenv(
        "REGIME_ENGINE_LOG_PATH",
        "/opt/tradingbot/logs/regime_engine.jsonl",
    )
)
PATHCONF_FLOOR = float(os.getenv("STANDDOWN_SHADOW_PATHCONF_FLOOR", "0.30"))
DWELL_N6 = int(os.getenv("STANDDOWN_SHADOW_DWELL_N6", "6"))
DWELL_N8 = int(os.getenv("STANDDOWN_SHADOW_DWELL_N8", "8"))

# Tail size — 200 lines covers >16h of 5m bars for a single symbol,
# enough headroom for any realistic dwell run without loading the full
# ~90 MB regime jsonl.
_TAIL_MAX_BYTES = 262_144  # 256 KiB


def _tail_lines(path: Path, max_bytes: int = _TAIL_MAX_BYTES) -> list[str]:
    """Return the last `max_bytes` of the file as a list of lines.

    Never raises. Returns [] on any I/O or decode failure.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return []
        with path.open("rb") as fh:
            fh.seek(-min(max_bytes, size), os.SEEK_END)
            tail = fh.read().decode("utf-8", errors="replace")
        # Drop the (possibly partial) first line if we started mid-file
        lines = tail.split("\n")
        if size > max_bytes and lines:
            lines = lines[1:]
        return [ln for ln in lines if ln]
    except Exception:
        return []


def dwell_run_length(symbol: str, regime: str) -> Optional[int]:
    """Count consecutive rows for `symbol` whose winning_regime == `regime`,
    walking backward from the tail of the regime jsonl. Break on gap or
    label change. Never raises; returns None on any failure.
    """
    if not symbol or not regime:
        return None
    lines = _tail_lines(REGIME_LOG_PATH)
    if not lines:
        return None
    sym_u = str(symbol).upper()
    reg_u = str(regime).upper()
    run = 0
    for ln in reversed(lines):
        try:
            d = json.loads(ln)
        except Exception:
            # A malformed line ends the run — treat as a gap.
            break
        if str(d.get("symbol") or "").upper() != sym_u:
            continue  # different symbol interleaved — ignore, do not break
        winning = str(d.get("winning_regime") or "").upper()
        if winning == reg_u:
            run += 1
        else:
            break
    return run


def _compute_verdicts(
    actual_decision: str,
    run_length: Optional[int],
    label_path: Optional[str],
    confidence_final: Optional[float],
) -> Dict[str, str]:
    """Compute the three candidate verdicts. Pure function, no I/O."""
    if run_length is None:
        v_n6 = "UNKNOWN"
        v_n8 = "UNKNOWN"
    else:
        v_n6 = "PERMIT" if run_length < DWELL_N6 else "SUPPRESS"
        v_n8 = "PERMIT" if run_length < DWELL_N8 else "SUPPRESS"
    is_struct = str(label_path or "").lower() == "struct"
    try:
        conf_low = (
            confidence_final is not None
            and float(confidence_final) < PATHCONF_FLOOR
        )
    except (TypeError, ValueError):
        conf_low = False
    if is_struct and conf_low:
        v_pc = "PERMIT"
    else:
        v_pc = actual_decision  # "SUPPRESS-as-actual"
    return {
        "verdict_dwell_n6": v_n6,
        "verdict_dwell_n8": v_n8,
        "verdict_pathconf": v_pc,
    }


def record(
    ts_utc: str,
    symbol: str,
    direction: str,
    actual_decision: str,
    regime: str,
    label_path: Optional[str],
    struct_promoted: Optional[bool],
    confidence_final: Optional[float],
    setup_price: Optional[float] = None,
    applied_factor: Optional[float] = None,
    extra_closes_required: Optional[int] = None,
    extra_closes_pending: Optional[int] = None,
    trend_subtype: Optional[str] = None,
    grind_direction: Optional[str] = None,
    qm_context_reason: Optional[str] = None,
) -> None:
    """Compute verdicts + write one JSONL row + one INFO log line.

    Never raises. `direction` is the raw BUY/SELL from the standdown
    consult; `actual_decision` is one of "SUPPRESS", "PERMIT",
    "WEIGHTED", "WEIGHTED_PENDING".

    `applied_factor` / `extra_closes_required` / `extra_closes_pending`
    are populated on WEIGHTED / WEIGHTED_PENDING rows so calibrators
    can reconstruct the sizing bias and the deferral cadence.

    `trend_subtype` / `grind_direction` / `qm_context_reason` are added
    with the REFORM 1 GRIND extension (2026-08-28): a WEIGHTED fire can
    now come from a STRONG_TREND classifier, a GRIND classifier, or
    both agreeing on the same bar. The reason column names which.
    """
    try:
        run = dwell_run_length(symbol, regime)
        verdicts = _compute_verdicts(
            actual_decision, run, label_path, confidence_final,
        )
        row = {
            "ts_utc": ts_utc,
            "symbol": str(symbol).upper() if symbol else None,
            "dir": str(direction).upper() if direction else None,
            "actual_decision": actual_decision,
            "regime": str(regime).upper() if regime else None,
            "label_path": label_path,
            "struct_promoted": bool(struct_promoted) if struct_promoted is not None else None,
            "confidence_final": confidence_final,
            "dwell_run_length": run,
            "verdict_dwell_n6": verdicts["verdict_dwell_n6"],
            "verdict_dwell_n8": verdicts["verdict_dwell_n8"],
            "verdict_pathconf": verdicts["verdict_pathconf"],
            "pathconf_floor": PATHCONF_FLOOR,
            "setup_price": setup_price,
            "mfe_pips": None,
            "mae_pips": None,
            "applied_factor": applied_factor,
            "extra_closes_required": extra_closes_required,
            "extra_closes_pending": extra_closes_pending,
            "trend_subtype": trend_subtype,
            "grind_direction": grind_direction,
            "qm_context_reason": qm_context_reason,
        }
        try:
            SHADOW_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with SHADOW_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except Exception:
            pass
        try:
            logger.info(
                "[STANDDOWN-SHADOW] %s %s %s actual=%s regime=%s "
                "path=%s conf=%s dwell=%s → n6=%s n8=%s pc=%s",
                ts_utc, symbol, direction, actual_decision, regime,
                label_path, confidence_final, run,
                verdicts["verdict_dwell_n6"],
                verdicts["verdict_dwell_n8"],
                verdicts["verdict_pathconf"],
            )
        except Exception:
            pass
    except Exception:
        # Belt-and-suspenders — nothing above should raise, but even if
        # something does the standdown decision path cannot see it.
        pass
