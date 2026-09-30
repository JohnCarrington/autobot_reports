#!/usr/bin/env python3
"""guards_observable_review.py — hourly poller, self-removing.

Fires when any of:
  A) all 4 guards (stale_briefing, news_blackout, priced_in,
     levels_proximity) have >= 10 rows in guards_observed.jsonl
  B) UTC now >= 2026-05-08 12:00 (hard fallback)
  C) 7 days have elapsed since the anchor file was written
     (anchor = install time, written by install step)

On fire: aggregate per-guard counts + verdicts, cross-reference blocked
rows with signal_log.jsonl, build Telegram digest, write markdown
summary, remove the cron file. Exits with 0 on every path so cron
doesn't email noise.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

JSONL_PATH      = Path("/opt/tradingbot/logs/guards_observed.jsonl")
SIGNAL_LOG_PATH = Path("/opt/tradingbot/logs/signal_log.jsonl")
LOGS_DIR        = Path("/opt/tradingbot/logs")
ANCHOR_FILE     = Path("/opt/tradingbot/cache/guards_review_anchor.txt")
ENV_FILE        = Path("/opt/tradingbot/.env")
CRON_MARKER     = "# ONE-SHOT guards_observable_review"

EXPECTED_GUARDS = ("stale_briefing", "news_blackout", "priced_in", "levels_proximity")
ROWS_PER_GUARD_THRESHOLD = 10
NOMINAL_DAYS_POST_ANCHOR = 7
FALLBACK_FIRE_AT = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

PROMOTE_MIN_BLOCKS  = 5
PROMOTE_MAX_WINNERS = 1


def _load_env():
    env: Dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _per_guard_eval_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        for g in r.get("guards_evaluated") or []:
            counts[g] += 1
    return counts


def _check_fire(rows: List[Dict[str, Any]]) -> Tuple[bool, str]:
    now = datetime.now(timezone.utc)

    if now >= FALLBACK_FIRE_AT:
        return True, "fallback_2026-05-08_12:00_reached"

    counts = _per_guard_eval_counts(rows)
    if all(counts.get(g, 0) >= ROWS_PER_GUARD_THRESHOLD for g in EXPECTED_GUARDS):
        return True, f"all_4_guards_at_{ROWS_PER_GUARD_THRESHOLD}_rows"

    if ANCHOR_FILE.exists():
        try:
            anchor_str = ANCHOR_FILE.read_text().strip()
            anchor = datetime.fromisoformat(anchor_str)
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            if (now - anchor) >= timedelta(days=NOMINAL_DAYS_POST_ANCHOR):
                return True, f"7d_post_anchor_{anchor.isoformat()}"
        except Exception:
            pass

    return False, "waiting"


def _signal_strategy_match(br_mode: str, sr_strategy: str) -> bool:
    sr_u = (sr_strategy or "").upper()
    if br_mode == "TREND_CONTINUATION":
        return "TREND_CONT" in sr_u
    if br_mode == "BRIEFING_EXECUTION":
        return "BRIEFING_EXECUTION" in sr_u
    if br_mode == "BRIEFING_SWEEP":
        return "BRIEFING_SWEEP" in sr_u
    if br_mode == "3CO":
        return sr_u == "3CO"
    return False


def _crossref_outcome(br: Dict[str, Any], signal_rows: List[Dict[str, Any]]
                       ) -> Optional[Dict[str, Any]]:
    br_ts = br.get("ts", "")
    br_sym = br.get("symbol")
    br_mode = br.get("strategy_mode", "")
    if not br_ts or not br_sym:
        return None
    try:
        br_dt = datetime.fromisoformat(br_ts.replace("Z", "+00:00"))
    except Exception:
        return None
    best = None
    best_diff = None
    for sr in signal_rows:
        if sr.get("pair") != br_sym:
            continue
        if not _signal_strategy_match(br_mode, sr.get("strategy", "")):
            continue
        sr_ts = sr.get("timestamp_open", "")
        if not sr_ts:
            continue
        try:
            sr_dt = datetime.fromisoformat(sr_ts.replace("Z", "+00:00"))
        except Exception:
            continue
        diff = abs((sr_dt - br_dt).total_seconds())
        if diff > 120:
            continue
        if best_diff is None or diff < best_diff:
            best = sr
            best_diff = diff
    return best


def _per_guard_stats(rows: List[Dict[str, Any]],
                     signal_rows: List[Dict[str, Any]]
                     ) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {
        g: {"evals": 0, "blocks": 0, "block_rate": 0.0,
            "blocked_rows": [], "blocked_outcomes": [],
            "winners_caught": 0, "losers_caught": 0,
            "pips_avoided_losses": 0.0}
        for g in EXPECTED_GUARDS
    }
    for r in rows:
        for g in r.get("guards_evaluated") or []:
            if g in stats:
                stats[g]["evals"] += 1
        for g in r.get("guards_blocked") or []:
            if g in stats:
                stats[g]["blocks"] += 1
                stats[g]["blocked_rows"].append(r)

    for g, s in stats.items():
        s["block_rate"] = (s["blocks"] / s["evals"] * 100.0) if s["evals"] else 0.0
        for br in s["blocked_rows"]:
            sr = _crossref_outcome(br, signal_rows)
            if sr is None:
                s["blocked_outcomes"].append({"row": br, "signal": None, "pnl_pips": None})
                continue
            try:
                pnl = float(sr.get("pnl_pips")) if sr.get("pnl_pips") is not None else None
            except (TypeError, ValueError):
                pnl = None
            s["blocked_outcomes"].append({"row": br, "signal": sr, "pnl_pips": pnl})
            if pnl is None:
                continue
            if pnl > 0:
                s["winners_caught"] += 1
            else:
                s["losers_caught"] += 1
                s["pips_avoided_losses"] += abs(pnl)
    return stats


def _verdict(stats: Dict[str, Any]) -> Tuple[str, str]:
    blocks = stats["blocks"]
    if blocks < PROMOTE_MIN_BLOCKS:
        return "KEEP_OBSERVABLE", f"only_{blocks}_blocks_lt_{PROMOTE_MIN_BLOCKS}"
    pnls = [o["pnl_pips"] for o in stats["blocked_outcomes"] if o["pnl_pips"] is not None]
    if not pnls:
        return "KEEP_OBSERVABLE", "no_signal_log_outcome_matches"
    mean_pnl = sum(pnls) / len(pnls)
    if mean_pnl >= 0:
        return "TUNE", f"mean_blocked_pnl_{mean_pnl:+.1f}p_not_negative"
    if stats["winners_caught"] > PROMOTE_MAX_WINNERS:
        return "TUNE", f"{stats['winners_caught']}_winners_caught_gt_{PROMOTE_MAX_WINNERS}"
    return "PROMOTE", f"mean_{mean_pnl:+.1f}p_winners_{stats['winners_caught']}"


def _levels_proximity_threshold_check(rows: List[Dict[str, Any]],
                                       signal_rows: List[Dict[str, Any]]
                                       ) -> Dict[str, Any]:
    """For each non-blocking levels_proximity evaluation, was there a level
    in the trade direction within 3-7p? Outcomes for those trades suggest
    whether widening from 3p to 5p or 7p would have caught more losers.

    Two paths:
      (1) Direct: row has guard_results.levels_proximity.data.nearest_level_in_path
          — populated by the dispatcher schema after the 2026-04-30 tweak.
          Direction-accurate, no proxy needed.
      (2) Fallback: legacy rows without guard_results — fall back to
          signal_log.distance_from_level_pips proxy (nearest-level-not-
          direction-aware) and flag the rows in 'fallback_used'.
    """
    in_band_direct: List[Dict[str, Any]] = []
    fallback_used = 0

    for r in rows:
        gres = (r.get("guard_results") or {}).get("levels_proximity")
        if not gres or gres.get("block") is True:
            continue
        nearest = (gres.get("data") or {}).get("nearest_level_in_path")
        if not nearest:
            continue
        try:
            d = float(nearest.get("distance_pips"))
        except (TypeError, ValueError):
            continue
        if not (3.0 < d <= 7.0):
            continue
        sr = _crossref_outcome(r, signal_rows)
        in_band_direct.append({"row": r, "signal": sr,
                                "distance_pips": d,
                                "level": nearest})

    in_band_proxy: List[Dict[str, Any]] = []
    if not in_band_direct:
        for sr in signal_rows:
            strat = (sr.get("strategy") or "").upper()
            if not ("TREND_CONT" in strat or strat == "3CO"):
                continue
            d_raw = sr.get("distance_from_level_pips")
            if d_raw is None:
                continue
            try:
                d = float(d_raw)
            except (TypeError, ValueError):
                continue
            if 3.0 < d <= 7.0:
                in_band_proxy.append({"signal": sr, "distance_pips": d})
                fallback_used += 1

    in_band = in_band_direct or in_band_proxy

    def _pnl(item):
        sig = item.get("signal")
        if not sig:
            return None
        try:
            v = sig.get("pnl_pips")
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    losers = [b for b in in_band if (p := _pnl(b)) is not None and p < 0]
    winners = [b for b in in_band if (p := _pnl(b)) is not None and p > 0]

    suggestion = "keep_3p"
    if len(in_band) >= 5:
        non_null = [b for b in in_band if _pnl(b) is not None]
        if non_null:
            loss_rate = len(losers) / len(non_null)
            if loss_rate >= 0.7:
                suggestion = "try_7p"
            elif loss_rate >= 0.55:
                suggestion = "try_5p"

    return {
        "trades_in_3_to_7p_band": len(in_band),
        "losers_in_band": len(losers),
        "winners_in_band": len(winners),
        "suggestion": suggestion,
        "source": ("direct_per_evaluation_data" if in_band_direct
                   else ("signal_log_proxy" if in_band_proxy else "no_data")),
        "fallback_used": fallback_used,
    }


def _send_telegram(text: str, env: Dict[str, str]) -> bool:
    token   = env.get("TELEGRAM_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"[guards_review] telegram send failed: {exc}", file=sys.stderr)
        return False


def _build_telegram(total_evals: int, stats: Dict[str, Dict[str, Any]],
                    threshold_check: Dict[str, Any]) -> str:
    lines = [
        "Guards module 7-day observable review",
        "",
        f"Total evaluations: {total_evals}",
        "",
        "Per-guard:",
    ]
    for g in EXPECTED_GUARDS:
        s = stats[g]
        verdict, why = _verdict(s)
        lines.append(f"  {g}: {s['evals']} eval, {s['blocks']} blocks ({s['block_rate']:.0f}% rate)")
        lines.append(f"                  Hypothetical impact: +{s['pips_avoided_losses']:.0f} pips avoided losses "
                     f"(W/L caught: {s['winners_caught']}/{s['losers_caught']})")
        if g == "levels_proximity":
            lines.append(f"                  Threshold tightness check ({threshold_check['source']}):")
            lines.append(f"                    {threshold_check['trades_in_3_to_7p_band']} trades at level 3-7p in path "
                         f"(L:{threshold_check['losers_in_band']} W:{threshold_check['winners_in_band']})")
            lines.append(f"                  Threshold tune suggestion: {threshold_check['suggestion']}")
        lines.append(f"                  Verdict: {verdict} ({why})")
        lines.append("")

    fp_rows = []
    for g, s in stats.items():
        for o in s["blocked_outcomes"]:
            sig = o.get("signal") or {}
            if o.get("pnl_pips") is not None and o["pnl_pips"] > 0:
                fp_rows.append((g, sig.get("deal_id", "?"), sig.get("pair", "?"),
                                o["pnl_pips"]))
    lines.append(f"False positives flagged: {len(fp_rows)}")
    for g, did, pair, pnl in fp_rows[:8]:
        lines.append(f"  - {g} {pair} {did} (pnl={pnl:+.1f}p)")
    if len(fp_rows) > 8:
        lines.append(f"  ... and {len(fp_rows) - 8} more")
    lines.append("")

    promote = sum(1 for g in EXPECTED_GUARDS if _verdict(stats[g])[0] == "PROMOTE")
    tune    = sum(1 for g in EXPECTED_GUARDS if _verdict(stats[g])[0] == "TUNE")
    obs     = sum(1 for g in EXPECTED_GUARDS if _verdict(stats[g])[0] == "KEEP_OBSERVABLE")
    if promote >= 1:
        rec = f"Promote {promote} guard(s) to live, tune {tune}, keep {obs} observable"
    elif tune >= 1:
        rec = f"Tune {tune} guard(s); keep {obs} observable"
    else:
        rec = "Continue observable across all guards"
    lines.append(f"Recommendation: {rec}")
    return "\n".join(lines)


def _build_markdown(total_evals: int, stats: Dict[str, Dict[str, Any]],
                    threshold_check: Dict[str, Any], fire_reason: str) -> str:
    now = datetime.now(timezone.utc)
    lines = [
        f"# Guards module observable review — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Fire reason: `{fire_reason}`",
        f"Total evaluations: {total_evals}",
        "",
        "## Per-guard breakdown",
        "",
    ]
    for g in EXPECTED_GUARDS:
        s = stats[g]
        verdict, why = _verdict(s)
        lines.append(f"### {g}")
        lines.append("")
        lines.append(f"- evals: **{s['evals']}**")
        lines.append(f"- blocks: **{s['blocks']}** ({s['block_rate']:.1f}% block rate)")
        lines.append(f"- winners caught: {s['winners_caught']}")
        lines.append(f"- losers caught: {s['losers_caught']}")
        lines.append(f"- pips avoided (loss side): {s['pips_avoided_losses']:.1f}p")
        lines.append(f"- verdict: **{verdict}** — {why}")
        if g == "levels_proximity":
            lines.append("")
            lines.append("**Threshold tightness check:**")
            lines.append(f"- data source: `{threshold_check['source']}` "
                         f"(direct = direction-accurate per-evaluation; proxy = "
                         f"signal_log fallback for legacy rows)")
            lines.append(f"- trades fired with nearest in-path level 3–7p away: {threshold_check['trades_in_3_to_7p_band']}")
            lines.append(f"  - losers: {threshold_check['losers_in_band']}")
            lines.append(f"  - winners: {threshold_check['winners_in_band']}")
            lines.append(f"- suggested action: `{threshold_check['suggestion']}`")
            if threshold_check['source'] == 'signal_log_proxy':
                lines.append("- note: no rows yet in guards_observed.jsonl carry "
                             "the post-tweak schema. Re-run after autobot restart "
                             "for direction-accurate band counts.")
        lines.append("")

    return "\n".join(lines)


def _self_remove_cron() -> Tuple[bool, str]:
    """Remove our marker line from root's crontab. Mirrors the pattern in
    scripts/restart_recovery_verify.py so anyone reviewing one-shots sees
    the same approach.
    """
    try:
        existing = subprocess.check_output(
            ["crontab", "-l"], text=True, errors="replace", timeout=10,
        )
    except subprocess.SubprocessError as exc:
        return False, f"cron_read_failed_{exc}"
    out_lines: List[str] = []
    removed = 0
    for ln in existing.splitlines():
        if CRON_MARKER in ln and "guards_observable_review" in ln:
            removed += 1
            continue
        out_lines.append(ln)
    new_text = "\n".join(out_lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    try:
        subprocess.run(
            ["crontab", "-"], input=new_text, text=True, check=True, timeout=10,
        )
    except subprocess.SubprocessError as exc:
        return False, f"cron_write_failed_{exc}"
    return True, f"removed_{removed}_line(s)"


def main() -> int:
    rows = _load_jsonl(JSONL_PATH)
    fire, why = _check_fire(rows)
    if not fire:
        counts = _per_guard_eval_counts(rows)
        per_g = " ".join(f"{g}={counts.get(g,0)}" for g in EXPECTED_GUARDS)
        print(f"[guards_review] not yet — {why} | {per_g}")
        return 0

    print(f"[guards_review] firing: {why} (rows={len(rows)})")
    signal_rows = _load_jsonl(SIGNAL_LOG_PATH)
    stats = _per_guard_stats(rows, signal_rows)
    threshold_check = _levels_proximity_threshold_check(rows, signal_rows)

    env = _load_env()
    tg_msg = _build_telegram(len(rows), stats, threshold_check)
    md_summary = _build_markdown(len(rows), stats, threshold_check, why)

    md_path = LOGS_DIR / f"guards_review_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
    try:
        md_path.write_text(md_summary)
        print(f"[guards_review] wrote {md_path}")
    except Exception as exc:
        print(f"[guards_review] markdown write failed: {exc}", file=sys.stderr)

    sent = _send_telegram(tg_msg, env)
    print(f"[guards_review] telegram sent={sent}")

    ok, msg = _self_remove_cron()
    print(f"[guards_review] self-remove: {ok} {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
