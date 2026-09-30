#!/usr/bin/env python3
"""
shadow_audit.py — formal audit of BRIEFING_EXEC_TRIGGER_V2_MODE=shadow output.

Joins [BRIEFING-EXEC-SHADOW] log lines to briefing_outcomes.jsonl trade
outcomes and reports a confusion matrix, per-condition contribution,
per-symbol breakdown, and a recommendation. Optionally cross-checks
trade rows against IG's /history/transactions endpoint.

Usage:
    python3 scripts/shadow_audit.py --since YYYY-MM-DD
        [--until YYYY-MM-DD]
        [--output text|json|csv]
        [--ig-cross-check]
        [--epic-filter EPIC]

Test/dev overrides (env vars):
    SHADOW_LOG_FILE       — read shadow log lines from a flat file instead
                            of journalctl. One journalctl-style line per
                            row.
    BRIEFING_OUTCOMES_FILE — override the outcomes path (default
                             /opt/tradingbot/data/briefing_outcomes.jsonl).
    IG_TX_FIXTURE         — JSON file with a {"transactions": [...]} payload
                            used in place of a live IG REST call.

The script reads but does not modify any production data.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("shadow_audit")
logging.basicConfig(
    level=os.environ.get("SHADOW_AUDIT_LOG", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

DEFAULT_OUTCOMES_PATH = Path(
    os.environ.get(
        "BRIEFING_OUTCOMES_FILE",
        "/opt/tradingbot/data/briefing_outcomes.jsonl",
    )
)
SHADOW_TAG = "[BRIEFING-EXEC-SHADOW]"

# Same map signal_log_integrity.py uses; trimmed to the four pairs we trade.
INSTR_TO_EPIC = {
    "GBP/USD": "CS.D.GBPUSD.TODAY.IP",
    "EUR/USD": "CS.D.EURUSD.TODAY.IP",
    "USD/JPY": "CS.D.USDJPY.TODAY.IP",
    "AUD/USD": "CS.D.AUDUSD.TODAY.IP",
}
EPIC_TO_SYMBOL = {
    "CS.D.GBPUSD.TODAY.IP": "GBPUSD",
    "CS.D.EURUSD.TODAY.IP": "EURUSD",
    "CS.D.USDJPY.TODAY.IP": "USDJPY",
    "CS.D.AUDUSD.TODAY.IP": "AUDUSD",
}

# journalctl default short format: "Apr 25 10:32:15 host autobot[123]: <msg>"
# We don't need the year (logs are filtered by --since/--until) but we do
# want the full timestamp. journalctl also emits ISO-8601 with -o short-iso;
# we accept both.
RE_JOURNALCTL_ISO = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:?\d{2}|Z)?)\s"
)
RE_JOURNALCTL_SHORT = re.compile(
    r"^(?P<mon>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s"
)
RE_SHADOW = re.compile(
    re.escape(SHADOW_TAG)
    + r"\s+(?P<sym>\S+)\s+would_block=(?P<wb>\S+)\s+failed=(?P<failed>\[.*?\])\s+"
    r"briefing_time=(?P<bt>\S+)\s+entry_mode=(?P<em>\S+)"
)
RE_COND_TYPE = re.compile(r"\b(release_event|sweep|candle_close|rsi|consecutive_closes)\(")

# When matching shadow log lines to outcome rows the prompt allows up to 60s
# of slack between the shadow line timestamp and the entry timestamp.
JOIN_TIME_SLACK = timedelta(seconds=60)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ShadowEntry:
    ts: datetime
    symbol: str
    would_block: bool
    failed: List[str]
    briefing_time: str
    entry_mode: str
    raw: str

    @property
    def condition_types(self) -> List[str]:
        # Each element of self.failed reads e.g.
        #   "release_event(NFP): now=14:30:00 ..."
        # or
        #   "sweep(13265.0, below, tol=2p): lo=..."
        out: List[str] = []
        for f in self.failed:
            m = RE_COND_TYPE.search(f)
            if m:
                out.append(m.group(1))
        return out


@dataclass
class Outcome:
    briefing_time: str
    symbol: str
    raw: Dict[str, Any]
    won: Optional[bool]
    pnl_pips: Optional[float]
    deal_id: Optional[str]
    entry_ts: Optional[datetime]


@dataclass
class JoinedRow:
    shadow: ShadowEntry
    outcome: Outcome


@dataclass
class AuditResult:
    since: str
    until: str
    epic_filter: Optional[str]
    shadow_count: int
    outcome_count: int
    joined: List[JoinedRow] = field(default_factory=list)
    unjoined_shadow: List[ShadowEntry] = field(default_factory=list)
    unjoined_outcomes: List[Outcome] = field(default_factory=list)
    ig_cross_check: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_journalctl_ts(line: str, fallback_year: int) -> Optional[datetime]:
    """Return the timestamp at the start of a journalctl line, or None."""
    m = RE_JOURNALCTL_ISO.match(line)
    if m:
        ts = m.group("ts").replace("Z", "+00:00").replace(" ", "T")
        # Normalise no-colon offsets (+0000 → +00:00) for older Python's
        # stricter fromisoformat.
        ts = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", ts)
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    m = RE_JOURNALCTL_SHORT.match(line)
    if m:
        try:
            dt = datetime.strptime(
                f"{fallback_year} {m.group('mon')} {m.group('day')} {m.group('time')}",
                "%Y %b %d %H:%M:%S",
            )
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _parse_failed(payload: str) -> List[str]:
    """Best-effort parse of the Python-list repr emitted by the logger."""
    try:
        v = ast.literal_eval(payload)
        if isinstance(v, list):
            return [str(x) for x in v]
    except (ValueError, SyntaxError):
        pass
    # Fall back to splitting by comma when the repr is malformed.
    inner = payload.strip().lstrip("[").rstrip("]")
    if not inner:
        return []
    return [s.strip().strip("'\"") for s in inner.split(",") if s.strip()]


def parse_shadow_lines(lines: Iterable[str], fallback_year: int) -> List[ShadowEntry]:
    out: List[ShadowEntry] = []
    for raw in lines:
        if SHADOW_TAG not in raw:
            continue
        ts = _parse_journalctl_ts(raw, fallback_year) or datetime.now(timezone.utc)
        m = RE_SHADOW.search(raw)
        if not m:
            continue
        out.append(
            ShadowEntry(
                ts=ts,
                symbol=m.group("sym"),
                would_block=(m.group("wb") == "True"),
                failed=_parse_failed(m.group("failed")),
                briefing_time=m.group("bt"),
                entry_mode=m.group("em"),
                raw=raw.rstrip("\n"),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Outcome loading — tolerant of multiple schemas
# ---------------------------------------------------------------------------


def _coerce_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _row_to_outcome(rec: Dict[str, Any]) -> Optional[Outcome]:
    bt = rec.get("briefing_time")
    sym = rec.get("symbol") or rec.get("pair")
    if not bt or not sym:
        return None

    # win/loss — explicit first, fall back to TP-hit, then bias_correct
    won: Optional[bool] = None
    if "won" in rec:
        won = bool(rec["won"])
    elif "win" in rec:
        won = bool(rec["win"])
    elif "pnl_pips" in rec and rec["pnl_pips"] is not None:
        try:
            won = float(rec["pnl_pips"]) > 0
        except (TypeError, ValueError):
            won = None
    elif "tp1_hit" in rec:
        won = bool(rec.get("tp1_hit"))
    elif "bias_correct" in rec:
        won = bool(rec.get("bias_correct"))

    # pnl_pips — explicit first, fall back to pip_move (which is signed
    # session move and tracks bias direction at briefing-level outcomes).
    pnl: Optional[float] = None
    if rec.get("pnl_pips") is not None:
        try:
            pnl = float(rec["pnl_pips"])
        except (TypeError, ValueError):
            pnl = None
    elif rec.get("pip_move") is not None and rec.get("plan_bias"):
        try:
            sign = 1.0 if str(rec["plan_bias"]).upper() in ("LONG", "BUY") else -1.0
            pnl = float(rec["pip_move"]) * sign
        except (TypeError, ValueError):
            pnl = None

    entry_ts = (
        _coerce_dt(rec.get("entry_time"))
        or _coerce_dt(rec.get("timestamp_open"))
        or _coerce_dt(rec.get("briefing_time"))
    )

    return Outcome(
        briefing_time=str(bt),
        symbol=str(sym).upper(),
        raw=rec,
        won=won,
        pnl_pips=pnl,
        deal_id=rec.get("dealId") or rec.get("deal_id") or rec.get("id"),
        entry_ts=entry_ts,
    )


def load_outcomes(
    path: Path,
    since: datetime,
    until: datetime,
    epic_filter: Optional[str],
) -> List[Outcome]:
    if not path.exists():
        logger.error("outcomes file missing: %s", path)
        sys.exit(1)
    out: List[Outcome] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except json.JSONDecodeError:
                continue
            o = _row_to_outcome(rec)
            if o is None:
                continue
            bt_dt = _coerce_dt(o.briefing_time)
            if bt_dt is None or not (since <= bt_dt < until):
                continue
            if epic_filter:
                want = EPIC_TO_SYMBOL.get(epic_filter, epic_filter).upper()
                if o.symbol != want:
                    continue
            out.append(o)
    return out


# ---------------------------------------------------------------------------
# journalctl source
# ---------------------------------------------------------------------------


def _journalctl_lines(since: datetime, until: datetime) -> List[str]:
    fixture = os.environ.get("SHADOW_LOG_FILE")
    if fixture:
        with open(fixture, "r", encoding="utf-8") as f:
            return f.readlines()
    cmd = [
        "journalctl",
        "-u",
        "autobot.service",
        "--since",
        since.strftime("%Y-%m-%d %H:%M:%S"),
        "--until",
        until.strftime("%Y-%m-%d %H:%M:%S"),
        "--no-pager",
        "-o",
        "short-iso",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.error("journalctl unavailable: %s", e)
        sys.exit(1)
    if proc.returncode != 0:
        logger.error(
            "journalctl exited %d: %s",
            proc.returncode,
            (proc.stderr or "").strip(),
        )
        sys.exit(1)
    return proc.stdout.splitlines()


# ---------------------------------------------------------------------------
# Join logic
# ---------------------------------------------------------------------------


def join(
    shadows: List[ShadowEntry],
    outcomes: List[Outcome],
) -> Tuple[List[JoinedRow], List[ShadowEntry], List[Outcome]]:
    """Match shadow log lines to outcome rows.

    Primary key: (symbol, briefing_time).
    Tiebreaker: prefer outcomes whose entry_ts is within JOIN_TIME_SLACK of
    the shadow line timestamp; if no entry_ts is available, fall back to
    briefing_time match alone.

    Each shadow line consumes at most one outcome; each outcome at most one
    shadow line. If multiple shadow lines share the same key (e.g. trend
    re-entry attempts), we prefer the closest in time to the outcome's
    entry_ts.
    """
    by_key: Dict[Tuple[str, str], List[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_key[(o.symbol.upper(), o.briefing_time)].append(o)

    used_outcomes: set = set()
    joined: List[JoinedRow] = []
    unjoined_shadow: List[ShadowEntry] = []

    # Process shadow lines in time order so earlier attempts get first crack
    # at their matching outcome.
    for s in sorted(shadows, key=lambda x: x.ts):
        candidates = by_key.get((s.symbol.upper(), s.briefing_time), [])
        candidates = [c for c in candidates if id(c) not in used_outcomes]
        if not candidates:
            unjoined_shadow.append(s)
            continue
        best = candidates[0]
        if any(c.entry_ts for c in candidates):
            # pick by minimum |entry_ts - shadow.ts|, ignoring candidates
            # without entry_ts unless none have it
            scored = [
                (abs((c.entry_ts - s.ts).total_seconds()), c)
                for c in candidates
                if c.entry_ts is not None
            ]
            if scored:
                scored.sort(key=lambda t: t[0])
                if scored[0][0] <= JOIN_TIME_SLACK.total_seconds():
                    best = scored[0][1]
        used_outcomes.add(id(best))
        joined.append(JoinedRow(shadow=s, outcome=best))

    unjoined_outcomes = [o for o in outcomes if id(o) not in used_outcomes]
    return joined, unjoined_shadow, unjoined_outcomes


# ---------------------------------------------------------------------------
# Confusion matrix + metrics
# ---------------------------------------------------------------------------


def confusion(joined: List[JoinedRow]) -> Dict[str, int]:
    """Counts cells of:

                       v2 ALLOW    v2 BLOCK
        Trade WON         N1          N2
        Trade LOST        N3          N4
    """
    n1 = n2 = n3 = n4 = unknown = 0
    for j in joined:
        won = j.outcome.won
        block = j.shadow.would_block
        if won is None:
            unknown += 1
            continue
        if won and not block:
            n1 += 1
        elif won and block:
            n2 += 1
        elif (not won) and not block:
            n3 += 1
        else:
            n4 += 1
    return {
        "allow_won": n1,
        "block_won": n2,
        "allow_lost": n3,
        "block_lost": n4,
        "unknown_outcome": unknown,
    }


def decision_metrics(c: Dict[str, int], joined: List[JoinedRow]) -> Dict[str, Any]:
    n1 = c["allow_won"]
    n2 = c["block_won"]
    n3 = c["allow_lost"]
    n4 = c["block_lost"]

    def _ratio(num: int, den: int) -> Optional[float]:
        return (num / den) if den > 0 else None

    sum_pnl_allow = sum(
        j.outcome.pnl_pips
        for j in joined
        if (not j.shadow.would_block) and j.outcome.pnl_pips is not None
    )
    sum_pnl_block = sum(
        j.outcome.pnl_pips
        for j in joined
        if j.shadow.would_block and j.outcome.pnl_pips is not None
    )
    return {
        "true_positive_rate": _ratio(n4, n3 + n4),
        "false_positive_rate": _ratio(n2, n1 + n2),
        "sensitivity": _ratio(n4, n2 + n4),
        "net_edge_if_enforced_pips": round(sum_pnl_allow - sum_pnl_block, 2),
        "sample_size": n1 + n2 + n3 + n4,
    }


def per_condition(joined: List[JoinedRow]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    types = ("release_event", "sweep", "candle_close", "rsi", "consecutive_closes")
    for t in types:
        blocks = 0
        trades = 0
        blocked_pnl = 0.0
        for j in joined:
            if not j.shadow.would_block:
                continue
            if t in j.shadow.condition_types:
                blocks += 1
                trades += 1
                if j.outcome.pnl_pips is not None:
                    blocked_pnl += j.outcome.pnl_pips
        out[t] = {
            "blocks": blocks,
            "trades": trades,
            "blocked_pnl_pips": round(blocked_pnl, 2),
        }
    return out


def per_symbol(joined: List[JoinedRow]) -> Dict[str, Dict[str, int]]:
    syms: Dict[str, List[JoinedRow]] = defaultdict(list)
    for j in joined:
        syms[j.outcome.symbol].append(j)
    return {sym: confusion(rows) for sym, rows in syms.items()}


def recommendation(
    metrics: Dict[str, Any],
    ig_check: Optional[Dict[str, Any]],
) -> List[str]:
    out: List[str] = []
    fpr = metrics.get("false_positive_rate")
    tpr = metrics.get("true_positive_rate")
    n = metrics.get("sample_size", 0)
    n_block_won = metrics_n_block_won(metrics)
    n_block_lost = metrics.get("_n_block_lost", 0)
    n_allow_lost = metrics.get("_n_allow_lost", 0)
    n_blocks = n_block_won + n_block_lost
    n_losers = n_allow_lost + n_block_lost
    if fpr is not None and fpr > 0:
        out.append(
            f"Hold off on live; v2 would have killed {n_block_won} winners"
        )
    if (
        (tpr is not None and tpr > 0.6 and fpr == 0)
        or (n_blocks == 0 and n_losers == 0 and n > 0)
    ):
        out.append("Safe to consider live")
    if n < 10:
        out.append(f"Insufficient data; extend shadow window (n={n} < 10)")
    if ig_check and ig_check.get("pnl_mismatches"):
        out.append(
            "briefing_outcomes.jsonl drift detected; investigate before any decision"
        )
    if not out:
        out.append("No recommendation triggers fired")
    return out


def metrics_n_block_won(metrics: Dict[str, Any]) -> int:
    # Helper used only inside recommendation() — extracts n2 if cached on metrics.
    return metrics.get("_n_block_won", 0)


# ---------------------------------------------------------------------------
# IG cross-check (optional)
# ---------------------------------------------------------------------------


def _fetch_ig_transactions(since: datetime, until: datetime) -> Optional[List[Dict[str, Any]]]:
    fixture = os.environ.get("IG_TX_FIXTURE")
    if fixture:
        with open(fixture, "r", encoding="utf-8") as f:
            return json.load(f).get("transactions", [])
    try:
        sys.path.insert(0, "/opt/tradingbot")
        import ig_auth  # type: ignore
        import requests  # type: ignore

        _, headers, _ = ig_auth.get_ig_session()
    except Exception as e:
        logger.warning(
            "[ig_cross_check] IG REST unavailable (%s) — audit completed without IG cross-check.",
            e,
        )
        return None
    h = dict(headers)
    h["Version"] = "2"
    h["Accept"] = "application/json; charset=UTF-8"
    url = (
        "https://demo-api.ig.com/gateway/deal/history/transactions"
        f"?type=ALL_DEAL"
        f"&from={since.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&to={until.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&pageSize=500"
    )
    try:
        r = requests.get(url, headers=h, timeout=20)
    except Exception as e:
        logger.warning("[ig_cross_check] IG REST request failed: %s", e)
        return None
    if r.status_code == 403:
        logger.warning(
            "[ig_cross_check] 403 from IG REST — allowance exceeded. "
            "Audit completed without IG cross-check."
        )
        return None
    if r.status_code != 200:
        logger.warning(
            "[ig_cross_check] IG REST HTTP %d — audit completed without IG cross-check.",
            r.status_code,
        )
        return None
    try:
        return r.json().get("transactions", []) or []
    except ValueError:
        return None


def cross_check_ig(
    outcomes: List[Outcome], since: datetime, until: datetime
) -> Dict[str, Any]:
    txs = _fetch_ig_transactions(since, until)
    if txs is None:
        return {"available": False, "reason": "IG REST unavailable or 403"}
    matched = 0
    not_in_ig: List[Dict[str, Any]] = []
    pnl_mismatches: List[Dict[str, Any]] = []
    missing_deal_ids: List[Dict[str, Any]] = []

    by_deal: Dict[str, Dict[str, Any]] = {}
    for t in txs:
        ref = t.get("reference") or t.get("dealReference") or t.get("dealId")
        if ref:
            by_deal[str(ref)] = t

    for o in outcomes:
        if not o.deal_id:
            missing_deal_ids.append(
                {
                    "briefing_time": o.briefing_time,
                    "symbol": o.symbol,
                }
            )
            continue
        tx = by_deal.get(str(o.deal_id))
        if not tx:
            not_in_ig.append(
                {
                    "deal_id": o.deal_id,
                    "briefing_time": o.briefing_time,
                    "symbol": o.symbol,
                }
            )
            continue
        matched += 1
        # PnL comparison: tracker pnl_pips vs IG-derived (close-open)*sign
        if o.pnl_pips is None:
            continue
        try:
            open_lvl = float(tx.get("openLevel"))
            close_lvl = float(tx.get("closeLevel"))
            size = str(tx.get("size") or "")
            sign = 1.0 if size.startswith("+") else -1.0
            ig_pnl = (close_lvl - open_lvl) * sign
            if abs(ig_pnl - o.pnl_pips) > 0.1:
                pnl_mismatches.append(
                    {
                        "deal_id": o.deal_id,
                        "tracker_pnl_pips": round(o.pnl_pips, 4),
                        "ig_pnl_pips": round(ig_pnl, 4),
                    }
                )
        except (TypeError, ValueError):
            continue

    return {
        "available": True,
        "trades_matched": matched,
        "trades_not_in_ig": not_in_ig,
        "pnl_mismatches": pnl_mismatches,
        "missing_deal_ids": missing_deal_ids,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def render_text(result: AuditResult) -> str:
    buf = io.StringIO()
    w = buf.write
    w(f"Audit window: {result.since} to {result.until}\n")
    if result.epic_filter:
        w(f"Epic filter:  {result.epic_filter}\n")
    w(f"Shadow log entries:           {result.shadow_count}\n")
    w(f"Outcomes in window:           {result.outcome_count}\n")
    w(f"Joined:                       {len(result.joined)}")
    if result.shadow_count:
        w(f" ({len(result.joined) / result.shadow_count * 100:.1f}%)\n")
    else:
        w("\n")
    w(f"Unjoined shadow entries:      {len(result.unjoined_shadow)}\n")
    w(f"Unjoined outcomes:            {len(result.unjoined_outcomes)}\n")
    w("\n")

    c = confusion(result.joined)
    m = decision_metrics(c, result.joined)
    m["_n_block_won"] = c["block_won"]
    m["_n_block_lost"] = c["block_lost"]
    m["_n_allow_lost"] = c["allow_lost"]

    w("Confusion matrix:\n")
    w("                  v2 ALLOW    v2 BLOCK\n")
    w(f"  Trade WON   {c['allow_won']:>10}  {c['block_won']:>10}\n")
    w(f"  Trade LOST  {c['allow_lost']:>10}  {c['block_lost']:>10}\n")
    if c["unknown_outcome"]:
        w(f"  (unknown outcome on {c['unknown_outcome']} joined rows — excluded)\n")
    w("\n")

    def _fmt(x: Optional[float]) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    w("Decision metrics:\n")
    w(f"  True positive rate (block + lost):  {_fmt(m['true_positive_rate'])}\n")
    w(f"  False positive rate (block + won):  {_fmt(m['false_positive_rate'])}\n")
    w(f"  Sensitivity:                        {_fmt(m['sensitivity'])}\n")
    w(f"  Net edge if v2 enforced (pips):     {m['net_edge_if_enforced_pips']:+.2f}\n")
    w(f"  Sample size:                        {m['sample_size']}\n")
    w("\n")

    pc = per_condition(result.joined)
    w("Per-condition contribution:\n")
    for t, row in pc.items():
        w(
            f"  {t:<22} blocks={row['blocks']:<3} trades={row['trades']:<3} "
            f"blocked_pnl={row['blocked_pnl_pips']:+.2f} pips\n"
        )
    w("\n")

    w("By-symbol breakdown:\n")
    by_sym = per_symbol(result.joined)
    if not by_sym:
        w("  (no joined rows)\n")
    for sym, cs in sorted(by_sym.items()):
        w(
            f"  {sym}: allow_won={cs['allow_won']} block_won={cs['block_won']} "
            f"allow_lost={cs['allow_lost']} block_lost={cs['block_lost']}\n"
        )
    w("\n")

    w("Recommendations:\n")
    for r in recommendation(m, result.ig_cross_check):
        w(f"  - {r}\n")
    w("\n")

    if result.ig_cross_check is not None:
        ig = result.ig_cross_check
        w("IG cross-check report:\n")
        if not ig.get("available"):
            w(f"  unavailable: {ig.get('reason', 'unknown')}\n")
        else:
            w(f"  trades matched:     {ig['trades_matched']}\n")
            w(f"  trades not in IG:   {len(ig['trades_not_in_ig'])}\n")
            for row in ig["trades_not_in_ig"][:10]:
                w(f"    - {row}\n")
            w(f"  pnl mismatches:     {len(ig['pnl_mismatches'])}\n")
            for row in ig["pnl_mismatches"][:10]:
                w(f"    - {row}\n")
            w(f"  missing deal ids:   {len(ig['missing_deal_ids'])}\n")
    return buf.getvalue()


def render_json(result: AuditResult) -> str:
    c = confusion(result.joined)
    m = decision_metrics(c, result.joined)
    m["_n_block_won"] = c["block_won"]
    m["_n_block_lost"] = c["block_lost"]
    m["_n_allow_lost"] = c["allow_lost"]
    rec = recommendation(m, result.ig_cross_check)
    payload = {
        "since": result.since,
        "until": result.until,
        "epic_filter": result.epic_filter,
        "shadow_count": result.shadow_count,
        "outcome_count": result.outcome_count,
        "joined": len(result.joined),
        "unjoined_shadow": len(result.unjoined_shadow),
        "unjoined_outcomes": len(result.unjoined_outcomes),
        "confusion_matrix": c,
        "decision_metrics": {k: v for k, v in m.items() if not k.startswith("_")},
        "per_condition": per_condition(result.joined),
        "per_symbol": per_symbol(result.joined),
        "recommendations": rec,
        "ig_cross_check": result.ig_cross_check,
    }
    return json.dumps(payload, indent=2, default=str)


def render_csv(result: AuditResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "ts",
            "symbol",
            "would_block",
            "entry_mode",
            "briefing_time",
            "won",
            "pnl_pips",
            "deal_id",
            "failed_conditions",
        ]
    )
    for j in result.joined:
        w.writerow(
            [
                j.shadow.ts.isoformat(),
                j.shadow.symbol,
                j.shadow.would_block,
                j.shadow.entry_mode,
                j.shadow.briefing_time,
                j.outcome.won,
                j.outcome.pnl_pips,
                j.outcome.deal_id,
                ";".join(j.shadow.failed),
            ]
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    p.add_argument("--since", required=True, help="audit window start, YYYY-MM-DD")
    p.add_argument(
        "--until",
        default=None,
        help="audit window end, YYYY-MM-DD (default: today)",
    )
    p.add_argument(
        "--output",
        choices=("text", "json", "csv"),
        default="text",
    )
    p.add_argument("--ig-cross-check", action="store_true")
    p.add_argument("--epic-filter", default=None)
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.error("--since must be YYYY-MM-DD")
        return 2
    if args.until:
        try:
            until_dt = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.error("--until must be YYYY-MM-DD")
            return 2
    else:
        # End of today, in UTC. Inclusive of today's events.
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        until_dt = today + timedelta(days=1)

    if until_dt <= since_dt:
        logger.error("--until must be after --since")
        return 2

    # 1. Load shadow log lines
    raw_lines = _journalctl_lines(since_dt, until_dt)
    shadows_all = parse_shadow_lines(raw_lines, fallback_year=since_dt.year)
    # journalctl will only give us lines inside the requested window when we
    # used --since/--until, but the SHADOW_LOG_FILE override may include
    # more — clip explicitly.
    shadows = [s for s in shadows_all if since_dt <= s.ts < until_dt]
    if args.epic_filter:
        want = EPIC_TO_SYMBOL.get(args.epic_filter, args.epic_filter).upper()
        shadows = [s for s in shadows if s.symbol.upper() == want]

    if not shadows:
        print(
            "No shadow logs in window — has MODE been flipped to shadow?",
            file=sys.stderr,
        )
        return 0

    # 2. Load outcomes
    outcomes = load_outcomes(
        DEFAULT_OUTCOMES_PATH, since_dt, until_dt, args.epic_filter
    )

    # 3. Join
    joined, unjoined_shadow, unjoined_outcomes = join(shadows, outcomes)

    # 4. Optional IG cross-check
    ig_check: Optional[Dict[str, Any]] = None
    if args.ig_cross_check:
        ig_check = cross_check_ig([j.outcome for j in joined], since_dt, until_dt)

    result = AuditResult(
        since=args.since,
        until=args.until or until_dt.strftime("%Y-%m-%d"),
        epic_filter=args.epic_filter,
        shadow_count=len(shadows),
        outcome_count=len(outcomes),
        joined=joined,
        unjoined_shadow=unjoined_shadow,
        unjoined_outcomes=unjoined_outcomes,
        ig_cross_check=ig_check,
    )

    if args.output == "json":
        print(render_json(result))
    elif args.output == "csv":
        print(render_csv(result))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
