"""
Briefing Feedback Tracker
─────────────────────────
Tracks trade outcomes against morning briefing scenarios.
Appends to logs/briefing_outcomes_YYYY-MM.csv on each trade close.
"""

import csv
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LOGS_DIR = Path("logs")
_WRITE_LOCK = threading.Lock()

CSV_HEADERS = [
    "date",
    "time",
    "symbol",
    "session",
    "direction",
    "briefing_bias",
    "briefing_confidence",
    "session_expectation",
    "briefing_confirmed",
    "plan_label",
    "pnl_pips",
    "outcome",
    "close_reason",
]


def _outcome_label(pnl_pips: float) -> str:
    if pnl_pips > 0.5:
        return "WIN"
    if pnl_pips < -0.5:
        return "LOSS"
    return "BREAKEVEN"


def _current_session() -> str:
    h = datetime.now(timezone.utc).hour
    if h < 7:
        return "Asian"
    if h < 13:
        return "London"
    return "NY"


def _csv_path(dt: datetime) -> Path:
    return LOGS_DIR / f"briefing_outcomes_{dt.strftime('%Y-%m')}.csv"


class BriefingTracker:
    """Records trade outcomes against briefing predictions."""

    def __init__(self) -> None:
        LOGS_DIR.mkdir(exist_ok=True)

    def record_trade_outcome(
        self,
        symbol: str,
        session: str,
        date: str,
        trade_result: Dict[str, Any],
    ) -> None:
        """
        Called when a trade closes.  Appends one row to the monthly CSV.

        trade_result keys:
            direction, briefing_confirmed, briefing_bias, briefing_confidence,
            session_expectation, plan_label, pnl_pips, close_reason
        """
        try:
            now = datetime.now(timezone.utc)
            pnl = float(trade_result.get("pnl_pips") or 0)
            row = {
                "date": date or now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "symbol": symbol,
                "session": session or _current_session(),
                "direction": trade_result.get("direction", ""),
                "briefing_bias": trade_result.get("briefing_bias", ""),
                "briefing_confidence": trade_result.get("briefing_confidence", ""),
                "session_expectation": trade_result.get("session_expectation", ""),
                "briefing_confirmed": trade_result.get("briefing_confirmed", False),
                "plan_label": trade_result.get("plan_label", ""),
                "pnl_pips": f"{pnl:.1f}",
                "outcome": _outcome_label(pnl),
                "close_reason": trade_result.get("close_reason", ""),
            }

            path = _csv_path(now)
            write_header = not path.exists()

            with _WRITE_LOCK:
                with open(path, "a", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS)
                    if write_header:
                        writer.writeheader()
                    writer.writerow(row)

            logger.info(
                f"[briefing_tracker] Recorded {symbol} {row['outcome']} "
                f"pnl={pnl:.1f} confirmed={row['briefing_confirmed']}"
            )
        except Exception as e:
            logger.error(f"[briefing_tracker] record_trade_outcome failed: {e}")

    def get_statistics(
        self,
        symbol: Optional[str] = None,
        lookback_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Returns accuracy statistics from CSV logs.

        Keys returned:
            total_trades, direction_accuracy, confirmed_win_rate,
            unconfirmed_win_rate, plan1_win_rate,
            confidence_calibration (dict of bucket → win_rate),
            session_expectation_stats (dict of expectation → {trades, wins, win_rate})
        """
        rows = self._load_rows(symbol, lookback_days)
        if not rows:
            return {"total_trades": 0}

        total = len(rows)

        # --- Direction accuracy: briefing bias matched winning trade direction ---
        direction_match = 0
        direction_total = 0
        for r in rows:
            bias = r.get("briefing_bias", "").upper()
            direction = r.get("direction", "").upper()
            outcome = r.get("outcome", "")
            if not bias or bias == "NEUTRAL":
                continue
            direction_total += 1
            expected_dir = "BUY" if bias == "BULLISH" else "SELL"
            if outcome == "WIN" and direction == expected_dir:
                direction_match += 1
            elif outcome == "LOSS" and direction != expected_dir:
                direction_match += 1

        direction_accuracy = (
            round(direction_match / direction_total * 100, 1)
            if direction_total > 0
            else None
        )

        # --- Confirmed vs unconfirmed win rate ---
        confirmed_wins, confirmed_total = 0, 0
        unconfirmed_wins, unconfirmed_total = 0, 0
        for r in rows:
            is_confirmed = str(r.get("briefing_confirmed", "")).lower() in (
                "true",
                "1",
                "yes",
            )
            is_win = r.get("outcome") == "WIN"
            if is_confirmed:
                confirmed_total += 1
                if is_win:
                    confirmed_wins += 1
            else:
                unconfirmed_total += 1
                if is_win:
                    unconfirmed_wins += 1

        confirmed_win_rate = (
            round(confirmed_wins / confirmed_total * 100, 1)
            if confirmed_total > 0
            else None
        )
        unconfirmed_win_rate = (
            round(unconfirmed_wins / unconfirmed_total * 100, 1)
            if unconfirmed_total > 0
            else None
        )

        # --- Plan 1 win rate ---
        plan1_wins, plan1_total = 0, 0
        for r in rows:
            label = r.get("plan_label", "")
            if not label:
                continue
            is_confirmed = str(r.get("briefing_confirmed", "")).lower() in (
                "true",
                "1",
                "yes",
            )
            if not is_confirmed:
                continue
            # Plan 1 is the highest-ranked plan — check if it was the matched one
            # (We record the plan label, so any non-empty label on a confirmed trade counts)
            plan1_total += 1
            if r.get("outcome") == "WIN":
                plan1_wins += 1

        plan1_win_rate = (
            round(plan1_wins / plan1_total * 100, 1) if plan1_total > 0 else None
        )

        # --- Confidence calibration ---
        conf_buckets: Dict[str, List[bool]] = {
            "0.5-0.6": [],
            "0.6-0.7": [],
            "0.7+": [],
        }
        for r in rows:
            try:
                conf = float(r.get("briefing_confidence", 0))
            except (TypeError, ValueError):
                continue
            if conf <= 0:
                continue
            is_win = r.get("outcome") == "WIN"
            if conf < 0.6:
                conf_buckets["0.5-0.6"].append(is_win)
            elif conf < 0.7:
                conf_buckets["0.6-0.7"].append(is_win)
            else:
                conf_buckets["0.7+"].append(is_win)

        confidence_calibration = {}
        for bucket, outcomes in conf_buckets.items():
            if outcomes:
                confidence_calibration[bucket] = round(
                    sum(outcomes) / len(outcomes) * 100, 1
                )

        # --- Session expectation stats ---
        session_stats: Dict[str, Dict[str, int]] = {}
        for r in rows:
            exp = r.get("session_expectation", "").upper()
            if not exp:
                continue
            if exp not in session_stats:
                session_stats[exp] = {"trades": 0, "wins": 0}
            session_stats[exp]["trades"] += 1
            if r.get("outcome") == "WIN":
                session_stats[exp]["wins"] += 1

        session_expectation_stats = {}
        for exp, s in session_stats.items():
            session_expectation_stats[exp] = {
                "trades": s["trades"],
                "wins": s["wins"],
                "win_rate": round(s["wins"] / s["trades"] * 100, 1)
                if s["trades"] > 0
                else 0,
            }

        return {
            "total_trades": total,
            "direction_accuracy": direction_accuracy,
            "confirmed_win_rate": confirmed_win_rate,
            "confirmed_total": confirmed_total,
            "unconfirmed_win_rate": unconfirmed_win_rate,
            "unconfirmed_total": unconfirmed_total,
            "plan1_win_rate": plan1_win_rate,
            "plan1_total": plan1_total,
            "confidence_calibration": confidence_calibration,
            "session_expectation_stats": session_expectation_stats,
        }

    def _load_rows(
        self, symbol: Optional[str], lookback_days: int
    ) -> List[Dict[str, str]]:
        """Load CSV rows within lookback window."""
        rows: List[Dict[str, str]] = []
        now = datetime.now(timezone.utc)
        cutoff = now.strftime("%Y-%m-%d")

        # Compute cutoff date string
        from datetime import timedelta

        cutoff_dt = now - timedelta(days=lookback_days)
        cutoff_str = cutoff_dt.strftime("%Y-%m-%d")

        # Scan matching monthly CSV files
        if not LOGS_DIR.exists():
            return rows

        for path in sorted(LOGS_DIR.glob("briefing_outcomes_*.csv")):
            try:
                with open(path, "r", newline="") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        row_date = row.get("date", "")
                        if row_date < cutoff_str:
                            continue
                        if symbol and row.get("symbol", "").upper() != symbol.upper():
                            continue
                        rows.append(row)
            except Exception as e:
                logger.warning(f"[briefing_tracker] Error reading {path}: {e}")

        return rows
