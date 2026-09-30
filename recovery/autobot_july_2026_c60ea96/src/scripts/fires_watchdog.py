#!/usr/bin/env python3
"""fires_watchdog.py — daily zero-fills digest (ITEM 3).

Standalone script — independent of autobot.service. Runs via
fires-watchdog.timer at 17:30 UTC daily and reports strategies whose
trailing 10-trading-day average is above a threshold but whose today
count is zero. ONE digest Telegram; silence otherwise.

Design rules:
- No dependence on autobot process state (a dead bot cannot report its
  own silence).
- Read-only on logs/signal_log.jsonl.
- Weekend rows and estate-wide zero-fill days excluded from averages.
- Enabled-strategy set determined from the most recent registration
  block in the systemd journal (or /opt/tradingbot/logs/autobot*.log
  files if the journal has been vacuumed). Fallback: include all
  strategies meeting the average bar and note in the footer.
- Fully wrapped: any exception -> log to logs/fires_watchdog.log, exit 0.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = Path("/opt/tradingbot")
SIGNAL_LOG = REPO_ROOT / "logs" / "signal_log.jsonl"
LOG_FILE = REPO_ROOT / "logs" / "fires_watchdog.log"
LOG_GLOB = "autobot*.log"

ENV_HISTORY_DIR = REPO_ROOT / "env-history"
LAYERED_ENV_FILES = [REPO_ROOT / ".env", REPO_ROOT / "40-gates.env"]
NEWS_STRATEGY_EVALS_PATH = REPO_ROOT / "logs" / "news_strategy_evals.jsonl"
NEWS_MOMENTUM_OBS_PATH = REPO_ROOT / "logs" / "news_momentum_obs.jsonl"
TELEGRAM_MAX_CHARS = 4096

FIRES_WATCHDOG_MIN_AVG = float(os.getenv("FIRES_WATCHDOG_MIN_AVG", "3.0") or 3.0)
FIRES_WATCHDOG_TRAIL_DAYS = int(
    float(os.getenv("FIRES_WATCHDOG_TRAIL_DAYS", "10") or 10)
)

# Match lines emitted at boot listing the enabled strategy set. Format:
#   [STRATEGY-REGISTRY] enabled=[NAME1,NAME2,NAME3]
# Absence is not an error — the fallback path handles it.
_REGISTRY_LINE_RE = re.compile(
    r"\[STRATEGY-REGISTRY\]\s+enabled=\[([^\]]+)\]"
)


def _configure_logger() -> logging.Logger:
    log = logging.getLogger("fires_watchdog")
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(LOG_FILE)
    except Exception:
        fh = logging.StreamHandler(sys.stderr)
    fh.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
    log.addHandler(fh)
    return log


# ---------------------------------------------------------------------------
# Signal log reader
# ---------------------------------------------------------------------------

def _iter_signal_rows(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except Exception:
                continue


def _row_utc_date(row: dict) -> Optional[datetime]:
    ts = row.get("timestamp_open") or row.get("timestamp") or row.get("ts")
    if not ts:
        return None
    try:
        # Handle both "...Z" and "...+00:00" variants
        s = str(ts).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def _counts_by_strategy_day(
    rows: Iterable[dict],
) -> Dict[str, Dict[str, int]]:
    """Return {strategy: {"YYYY-MM-DD": count}}."""
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        strat = r.get("strategy")
        if not strat:
            continue
        ts = _row_utc_date(r)
        if ts is None:
            continue
        day = ts.date().isoformat()
        out.setdefault(str(strat), {})[day] = out.setdefault(str(strat), {}).get(day, 0) + 1
    return out


# ---------------------------------------------------------------------------
# Trailing-average computation
# ---------------------------------------------------------------------------

def _trading_days_backwards(today: datetime, n: int) -> List[str]:
    """Return the n most recent trading days STRICTLY BEFORE `today`, skipping
    Sat/Sun."""
    out: List[str] = []
    cur = today - timedelta(days=1)
    while len(out) < n:
        if cur.weekday() < 5:  # Mon..Fri
            out.append(cur.date().isoformat())
        cur = cur - timedelta(days=1)
    return out


def _estate_zero_days(
    counts: Dict[str, Dict[str, int]],
    days: List[str],
) -> Set[str]:
    """Days on which NO strategy had any fill are estate-wide zero-fill days
    and must be excluded from the trailing average (they typically reflect
    outages, not strategy behaviour)."""
    zero: Set[str] = set()
    for d in days:
        total = sum(cs.get(d, 0) for cs in counts.values())
        if total == 0:
            zero.add(d)
    return zero


def _avg_over(days_counts: Dict[str, int], candidate_days: List[str]) -> float:
    """Sum(count on kept days) / len(kept days). Zero-length -> 0.0."""
    if not candidate_days:
        return 0.0
    total = sum(days_counts.get(d, 0) for d in candidate_days)
    return total / float(len(candidate_days))


# ---------------------------------------------------------------------------
# Enabled-strategy discovery
# ---------------------------------------------------------------------------

def _read_journal_registry() -> Optional[List[str]]:
    """Return the enabled-strategy list from the latest
    [STRATEGY-REGISTRY] enabled=[...] journal line, or None if the
    journal is unreadable/silent on this pattern."""
    try:
        proc = subprocess.run(
            ["journalctl", "-u", "autobot.service", "--no-pager",
             "--since", "14 days ago"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    hits = _REGISTRY_LINE_RE.findall(proc.stdout)
    if not hits:
        return None
    last = hits[-1]
    return [s.strip() for s in last.split(",") if s.strip()]


def _read_file_log_registry() -> Optional[List[str]]:
    """Fallback: scan logs/autobot*.log for the last registry line."""
    logs_dir = REPO_ROOT / "logs"
    try:
        candidates = sorted(logs_dir.glob(LOG_GLOB), key=lambda p: p.stat().st_mtime)
    except Exception:
        return None
    for path in reversed(candidates):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        hits = _REGISTRY_LINE_RE.findall(text)
        if hits:
            return [s.strip() for s in hits[-1].split(",") if s.strip()]
    return None


def _discover_enabled_strategies() -> Tuple[Optional[List[str]], str]:
    """Return (list_or_None, source_label). source_label is one of:
      'journal', 'file-log', 'undeterminable'.
    """
    lst = _read_journal_registry()
    if lst:
        return lst, "journal"
    lst = _read_file_log_registry()
    if lst:
        return lst, "file-log"
    return None, "undeterminable"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def _build_digest(
    counts: Dict[str, Dict[str, int]],
    today_iso: str,
    trailing_days: List[str],
    enabled: Optional[List[str]],
    source_label: str,
) -> Optional[str]:
    zero_days = _estate_zero_days(counts, trailing_days)
    kept_days = [d for d in trailing_days if d not in zero_days]

    enabled_set = set(enabled) if enabled else set(counts.keys())

    silent: List[Tuple[str, float]] = []
    for strat, days_c in counts.items():
        if enabled_set and strat not in enabled_set:
            continue
        today_count = days_c.get(today_iso, 0)
        avg = _avg_over(days_c, kept_days)
        if today_count == 0 and avg >= FIRES_WATCHDOG_MIN_AVG:
            silent.append((strat, avg))

    # Strategies enabled but not present in the log at all: also eligible
    # when using the enabled-set path. Their avg is 0 so they never trip
    # the >= FIRES_WATCHDOG_MIN_AVG threshold — correct behaviour.

    if not silent:
        return None

    silent.sort(key=lambda t: (-t[1], t[0]))
    host_label = (os.getenv("ALERT_HOST_LABEL") or "").strip()
    prefix = f"[{host_label}] " if host_label else ""
    body = ", ".join(f"{s} (avg {a:.1f}/day)" for s, a in silent)
    msg = f"{prefix}SILENT TODAY: {body}"
    if source_label == "undeterminable":
        msg += " (strategy list undeterminable — included all above avg bar)"
    return msg


def _send_telegram(text: str, log: logging.Logger) -> None:
    try:
        import telegram_alerts  # imports .env via dotenv fallback
        telegram_alerts.send_telegram_message(text, parse_mode="")
    except Exception as exc:
        log.warning("telegram send failed %s: %s", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# SHADOW LEDGER (2026-07-27)
# ---------------------------------------------------------------------------
# Appends a per-mechanism shadow-mode roll-up to the daily digest so any
# shadow mechanism nearing (or past) its decision date is visible without
# having to trawl the journal. Registry is hard-coded on purpose — new
# shadow mechanisms require an explicit code change to appear here.

SHADOW_LEDGER_REGISTRY: List[dict] = [
    {
        "name": "BB_LEVEL_GATE",
        "mode_env": "BB_BOUNCE_LEVEL_GATE_MODE",
        "evidence": "journal_bb_level_gate",
        "decision_due": "2026-07-31",
    },
    {
        "name": "RUNNER_MOMENTUM",
        "mode_env": "RUNNER_MOMENTUM_CHECK_MODE",
        "evidence": "journal_runner_momentum",
        "decision_due": "2026-08-03",
    },
    {
        "name": "NEWS_STRATEGY",
        "mode_env": "NEWS_STRATEGY_MODE",
        "evidence": "jsonl_news_strategy",
        "decision_due": "2026-08-10",
    },
    {
        "name": "NEWS_MOMENTUM",
        "mode_env": "NEWS_MOMENTUM_MODE",
        "evidence": "jsonl_news_momentum",
        "decision_due": "2026-08-10",
    },
    {
        "name": "HTF_AUTHORITY",
        "mode_env": None,  # special-cased: no mode var, always OVERDUE
        "evidence": "journal_htf_authority",
        "decision_due": None,
    },
]

_ENV_KV_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def _parse_env_file(path: Path) -> Dict[str, str]:
    """Return KEY=VALUE map from a .env-style file. Non-crashing on any error."""
    out: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _ENV_KV_RE.match(s)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        # Strip matching quotes if present, do NOT expand escapes.
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        out[k] = v
    return out


def _layered_env_lookup(var: str, paths: List[Path]) -> Optional[str]:
    """Last-writer-wins over the layered env files. None if unset."""
    val: Optional[str] = None
    for p in paths:
        d = _parse_env_file(p)
        if var in d:
            val = d[var]
    return val


def _read_service_environ() -> Optional[Dict[str, str]]:
    """Return the autobot.service main-PID environ as a dict, or None.

    Any failure (no PID, unreadable /proc, systemctl absent) -> None so
    the caller can fall back to layered env files.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "show", "-p", "ExecMainPID", "--value",
             "autobot.service"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    pid_s = (proc.stdout or "").strip()
    if not pid_s or pid_s == "0":
        return None
    try:
        raw = Path(f"/proc/{pid_s}/environ").read_bytes()
    except Exception:
        return None
    out: Dict[str, str] = {}
    for chunk in raw.split(b"\x00"):
        if not chunk:
            continue
        try:
            s = chunk.decode("utf-8", errors="replace")
        except Exception:
            continue
        if "=" in s:
            k, _, v = s.partition("=")
            out[k] = v
    return out or None


def _resolve_mode(var: Optional[str],
                  process_env: Optional[Dict[str, str]],
                  layered_paths: List[Path]) -> Tuple[str, str]:
    """Return (mode_display, source_tag).

    source_tag is one of 'process', 'file', 'process,file-mismatch',
    'unset', or (for the HTF_AUTHORITY special-case) the caller
    substitutes its own display string.
    """
    if var is None:
        return ("shadow (no mode var — enforcement flag "
                "HTF_AUTHORITY_ENFORCE unset)", "special")
    proc_val = process_env.get(var) if process_env else None
    file_val = _layered_env_lookup(var, layered_paths)
    if proc_val is None and file_val is None:
        return "unset", "unset"
    if proc_val is not None and file_val is not None and proc_val != file_val:
        return f"{proc_val} (process; file={file_val})", "process,file-mismatch"
    if proc_val is not None:
        return proc_val, "process"
    return file_val, "file"  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Days-in-shadow via env-history snapshots
# ---------------------------------------------------------------------------

_SNAPSHOT_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def _snapshot_datetime(path: Path) -> datetime:
    """Extract the UTC datetime encoded in an env-history filename; fall
    back to file mtime if the pattern doesn't match."""
    m = _SNAPSHOT_TS_RE.search(path.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        except Exception:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _env_history_files(env_history_dir: Path) -> List[Path]:
    try:
        files = [p for p in env_history_dir.iterdir() if p.is_file()]
    except Exception:
        return []
    files.sort(key=_snapshot_datetime)
    return files


def _first_snapshot_with_var(var: str,
                             env_history_dir: Path) -> Optional[Path]:
    """Oldest env-history snapshot that contains `<var>=`, or None."""
    pattern = re.compile(rf"^\s*{re.escape(var)}\s*=", re.MULTILINE)
    for p in _env_history_files(env_history_dir):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if pattern.search(text):
            return p
    return None


def _days_in_shadow(var: Optional[str],
                    today: datetime,
                    env_history_dir: Path) -> Tuple[str, str]:
    """Return (days_display, method) — e.g. ('3', 'exact') or ('≥15', 'floor').

    - method='exact': var found in a snapshot; days = today - that snapshot's date.
    - method='floor': var never found; days = today - oldest snapshot date; prefix '≥'.
    - method='unknown': no snapshots at all; days_display = '?'.
    """
    if var is None:
        # HTF_AUTHORITY special case still gets a floor from snapshot history.
        files = _env_history_files(env_history_dir)
        if not files:
            return "?", "unknown"
        start = _snapshot_datetime(files[0])
        days = max(0, (today - start).days)
        return f"≥{days}", "floor"
    hit = _first_snapshot_with_var(var, env_history_dir)
    if hit is not None:
        start = _snapshot_datetime(hit)
        days = max(0, (today - start).days)
        return str(days), "exact"
    files = _env_history_files(env_history_dir)
    if not files:
        return "?", "unknown"
    start = _snapshot_datetime(files[0])
    days = max(0, (today - start).days)
    return f"≥{days}", "floor"


# ---------------------------------------------------------------------------
# Evidence collectors — each returns a short summary string. Any exception
# is turned into "unavailable (<reason>)" by _collect_evidence().
# ---------------------------------------------------------------------------

def _run_journal_since(since_iso: str, timeout: int = 30) -> Optional[str]:
    """Return the raw journalctl text for autobot.service since `since_iso`,
    or None if unreadable/empty. Wrapped."""
    try:
        proc = subprocess.run(
            ["journalctl", "-u", "autobot.service", "--no-pager",
             "--since", since_iso],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as exc:
        raise RuntimeError(f"journalctl_failed:{type(exc).__name__}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"journalctl_rc={proc.returncode}")
    return proc.stdout or ""


def _since_iso_for_var(var: Optional[str], today: datetime,
                       env_history_dir: Path,
                       max_days: int = 14) -> str:
    """Choose a journalctl --since window. Bounded by max_days because
    the journal is typically vacuumed after ~2 weeks."""
    if var is None:
        start = today - timedelta(days=7)
        return start.strftime("%Y-%m-%d %H:%M:%S UTC")
    hit = _first_snapshot_with_var(var, env_history_dir)
    if hit is not None:
        start = _snapshot_datetime(hit)
    else:
        files = _env_history_files(env_history_dir)
        start = _snapshot_datetime(files[0]) if files else today - timedelta(days=max_days)
    floor = today - timedelta(days=max_days)
    if start < floor:
        start = floor
    return start.strftime("%Y-%m-%d %H:%M:%S UTC")


def _count_journal_bb_level_gate(text: str) -> str:
    lines = [l for l in text.splitlines() if "[BB-LEVEL-GATE]" in l]
    n_pass = sum(1 for l in lines if "verdict=PASS" in l)
    n_would = sum(1 for l in lines if "verdict=WOULD_BLOCK" in l)
    return f"PASS={n_pass} WOULD_BLOCK={n_would}"


def _count_journal_runner_momentum(text: str) -> str:
    lines = [l for l in text.splitlines() if "[RUNNER-MOMENTUM]" in l]
    n_hold = sum(1 for l in lines if "verdict=HOLD" in l)
    n_would = sum(1 for l in lines if "verdict=WOULD_EXIT" in l)
    return f"HOLD={n_hold} WOULD_EXIT={n_would}"


def _count_journal_htf_authority(text: str) -> str:
    n_block = sum(
        1 for l in text.splitlines()
        if "[HTF-AUTHORITY]" in l and "SHADOW(BLOCKED" in l
    )
    return f"SHADOW(BLOCKED)={n_block} (last 7d, journal retention applies)"


_DECLINE_KIND_RE = re.compile(
    r'"kind"\s*:\s*"(DECLINE|SKIP_NO_ACTUALS|CONS_TIMEOUT|WOULD_DECLINE)"'
)
_WOULD_FIRE_RE = re.compile(r'"kind"\s*:\s*"WOULD_FIRE"')


def _count_news_strategy_jsonl(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"missing_log:{path.name}")
    n_would = 0
    n_decl = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if _WOULD_FIRE_RE.search(line):
                n_would += 1
            if _DECLINE_KIND_RE.search(line):
                n_decl += 1
    return f"WOULD_FIRE={n_would} DECLINE={n_decl}"


def _count_news_momentum_jsonl(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"missing_log:{path.name}")
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return f"rows={n}"


def _collect_evidence(spec: dict, today: datetime,
                      env_history_dir: Path,
                      journal_fetcher) -> Tuple[str, bool]:
    """Return (summary, ok). ok=False -> summary is 'unavailable (...)'.

    journal_fetcher: callable(since_iso) -> journal text (may raise).
    Injected so tests can supply a fixture without touching journalctl.
    """
    kind = spec["evidence"]
    try:
        if kind == "journal_bb_level_gate":
            since = _since_iso_for_var(spec["mode_env"], today, env_history_dir)
            text = journal_fetcher(since) or ""
            return _count_journal_bb_level_gate(text), True
        if kind == "journal_runner_momentum":
            since = _since_iso_for_var(spec["mode_env"], today, env_history_dir)
            text = journal_fetcher(since) or ""
            return _count_journal_runner_momentum(text), True
        if kind == "journal_htf_authority":
            since = (today - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S UTC")
            text = journal_fetcher(since) or ""
            return _count_journal_htf_authority(text), True
        if kind == "jsonl_news_strategy":
            return _count_news_strategy_jsonl(NEWS_STRATEGY_EVALS_PATH), True
        if kind == "jsonl_news_momentum":
            return _count_news_momentum_jsonl(NEWS_MOMENTUM_OBS_PATH), True
        return f"unavailable (unknown_evidence:{kind})", False
    except FileNotFoundError as exc:
        return f"unavailable ({exc})", False
    except Exception as exc:
        return f"unavailable ({type(exc).__name__}:{exc})", False


# ---------------------------------------------------------------------------
# Ledger assembly
# ---------------------------------------------------------------------------

def _is_overdue(spec: dict, today: datetime) -> bool:
    if spec.get("decision_due") is None:
        # HTF_AUTHORITY: never reviewed → always overdue.
        return True
    try:
        due = datetime.strptime(spec["decision_due"], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        return False
    return due.date() < today.date()


def _format_ledger_line(spec: dict, today: datetime,
                       env_history_dir: Path,
                       process_env: Optional[Dict[str, str]],
                       layered_paths: List[Path],
                       journal_fetcher) -> Tuple[bool, str]:
    """Return (overdue, formatted_line)."""
    name = spec["name"]
    mode_display, _src = _resolve_mode(spec["mode_env"], process_env, layered_paths)
    days_display, _method = _days_in_shadow(
        spec["mode_env"], today, env_history_dir
    )
    evidence, _ok = _collect_evidence(
        spec, today, env_history_dir, journal_fetcher
    )
    due = spec.get("decision_due") or "N/A (never reviewed)"
    overdue = _is_overdue(spec, today)
    prefix = "OVERDUE " if overdue else ""
    line = (
        f"{prefix}{name}  {mode_display} {days_display}d — "
        f"evidence: {evidence} — decision due {due}"
    )
    return overdue, line


def _build_shadow_ledger(today: datetime,
                         env_history_dir: Path = ENV_HISTORY_DIR,
                         layered_paths: Optional[List[Path]] = None,
                         process_env: Optional[Dict[str, str]] = "__auto__",
                         journal_fetcher=None) -> List[str]:
    """Return the ordered list of ledger lines (header + one per mechanism).

    Overdue entries sort to the top. On top-level failure inside any single
    entry, that entry becomes an 'unavailable' line — never a raise."""
    if layered_paths is None:
        layered_paths = LAYERED_ENV_FILES
    if process_env == "__auto__":
        try:
            process_env = _read_service_environ()
        except Exception:
            process_env = None
    if journal_fetcher is None:
        journal_fetcher = _run_journal_since

    graded: List[Tuple[bool, str, str]] = []
    for spec in SHADOW_LEDGER_REGISTRY:
        try:
            overdue, line = _format_ledger_line(
                spec, today, env_history_dir, process_env,
                layered_paths, journal_fetcher,
            )
        except Exception as exc:
            overdue = _is_overdue(spec, today)
            due = spec.get("decision_due") or "N/A (never reviewed)"
            prefix = "OVERDUE " if overdue else ""
            line = (f"{prefix}{spec['name']}  unavailable "
                    f"({type(exc).__name__}:{exc}) — decision due {due}")
        # Sort key: overdue first (0), then original order.
        graded.append((overdue, spec["name"], line))

    graded.sort(key=lambda t: (0 if t[0] else 1,
                               [s["name"] for s in SHADOW_LEDGER_REGISTRY].index(t[1])))
    return ["SHADOW LEDGER"] + [t[2] for t in graded]


def _combine_digest_and_ledger(digest: Optional[str],
                               ledger_lines: List[str]) -> Tuple[List[str], bool]:
    """Return (messages_to_send, appended_flag).

    appended_flag: True if the ledger was appended to the digest as a single
    message; False if it was split into a standalone message.
    """
    ledger_block = "\n".join(ledger_lines)
    if not digest:
        return [ledger_block], False
    combined = f"{digest}\n\n{ledger_block}"
    if len(combined) <= TELEGRAM_MAX_CHARS:
        return [combined], True
    return [digest, ledger_block], False


def _run() -> None:
    log = _configure_logger()

    today = datetime.now(timezone.utc)
    today_iso = today.date().isoformat()

    rows = list(_iter_signal_rows(SIGNAL_LOG))
    counts = _counts_by_strategy_day(rows)

    trailing_days = _trading_days_backwards(today, FIRES_WATCHDOG_TRAIL_DAYS)
    enabled, source_label = _discover_enabled_strategies()

    digest = _build_digest(counts, today_iso, trailing_days, enabled, source_label)
    if digest is None:
        log.info(
            "no silent strategies today=%s (trailing=%d days, source=%s)",
            today_iso, FIRES_WATCHDOG_TRAIL_DAYS, source_label,
        )
    else:
        log.warning("silent-today digest fired: %s", digest)

    try:
        ledger_lines = _build_shadow_ledger(today)
    except Exception as exc:
        log.error("shadow-ledger crashed at top level: %s", exc)
        ledger_lines = ["SHADOW LEDGER",
                        f"unavailable ({type(exc).__name__}:{exc})"]

    messages, appended = _combine_digest_and_ledger(digest, ledger_lines)
    log.info("shadow-ledger delivery: appended=%s messages=%d",
             appended, len(messages))
    for msg in messages:
        _send_telegram(msg, log)


def main() -> int:
    try:
        _run()
    except Exception:
        try:
            log = _configure_logger()
            log.error("fires_watchdog crashed: %s", traceback.format_exc())
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
