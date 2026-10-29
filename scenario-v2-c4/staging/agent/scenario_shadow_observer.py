"""History-informed scenario-reasoning shadow observer.

Pairs with ai_shadow_observer.py but produces SCENARIO rows instead of
single-shot observation rows. Writes to:

    /mnt/.../journal_shadow/scenarios_shadow.jsonl

Append-only. Each row is an immutable ScenarioRow (creation OR revision).
The scenario store validates the state DAG and refuses lookahead
revisions (revised_at_utc >= created_at_utc).

Lookahead safety (identical to ai_shadow_observer):
  * Corpus._eligible(asof) filters to episode_end_ts <= asof.
  * Macro context is rebuilt via build_macro_packet(asof=bar_close).
  * known_at_utc filter on verified_events.jsonl drops any row the
    primary could not have seen at that bar.

Cost controls (reuse ai_shadow_observer.CostCap + DedupSet):
  * Per-UTC-date USD cap.
  * Per-call cost ceiling pre-flight check.
  * (bar_ts, level_id, 'scenario') dedup prevents re-scoring one bar.
  * --max-pairs cap per sweep.
  * --dry-run never imports the Anthropic SDK.
  * execution_authority=NONE on every scenario row.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import logging
import pathlib
import sys
from typing import Any, Iterable

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from ai_shadow_observer import (  # noqa: E402
    CostCap,
    DedupSet,
    PRICING_HAIKU_4_5,
    _cost_estimate_usd,
    _dedup_key,
    _ensure_disjoint,
    _focal_interaction_idx,
    _format_analogue,
    _index_snapshots_by_bar_ts,
    append_jsonl,
    build_shadow_packet,
    iter_jsonl,
    load_env_once,
)
from historical_episode_memory import (  # noqa: E402
    Corpus,
    fingerprint_from_snapshot,
    load_corpus,
)
from scenario_reasoner import (  # noqa: E402
    apply_actions,
    build_scenario_prompt,
    call_scenario_model,
)
from scenario_quality import (  # noqa: E402
    decide_publication,
    validate_assessment,
)
from scenario_schema import (  # noqa: E402
    ScenarioStore,
    classify_economic_context,
    row_to_dict,
)

UTC = dt.timezone.utc
LOGGER = logging.getLogger("scenario_shadow_observer")

DEFAULT_PRIMARY_JOURNAL = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/journal"
)
DEFAULT_SHADOW_JOURNAL = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow"
)
DEFAULT_MACRO_EVENTS = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/news/verified_events.jsonl"
)


def _scenario_dedup_key(bar_ts: str, level_id: str) -> str:
    return _dedup_key(bar_ts, "scenario:" + (level_id or ""))


def _dry_assessment(prompt_obj: dict) -> dict:
    """Deterministic WAIT assessment used by --dry-run and offline tests.

    The reasoner is responsible for proposing scenarios; a dry run must
    never silently fabricate scenarios the live model never saw.
    """
    return {
        "current_interpretation": "DRY_RUN: no API call issued.",
        "narrative": "DRY_RUN",
        "waiting_for": ["DRY_RUN"],
        "what_would_invalidate": ["DRY_RUN"],
        "macro_scenarios": [],
        "actions": [{"kind": "WAIT"}],
        "model": "dry_run",
        "llm_provider": "none",
        "latency_ms": 0,
        "stop_reason": "dry_run",
        "usage_input_tokens": 0,
        "usage_output_tokens": 0,
        "usage_cache_read_tokens": 0,
        "usage_cache_creation_tokens": 0,
    }


def _parse_iso_utc(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def sweep(primary_journal: pathlib.Path,
          shadow_journal: pathlib.Path,
          corpus: Corpus,
          k: int,
          max_pairs: int,
          daily_usd_cap: float,
          per_call_usd_ceiling: float,
          model: str,
          max_tokens: int,
          macro_events: pathlib.Path | None,
          macro_source: str,
          dry_run: bool = False,
          agent_label: str = "shadow",
          max_primary_age_minutes: int = 120,
          max_sweep_seconds: int = 270,
          now_utc: dt.datetime | None = None) -> dict:
    import time as _time
    _ensure_disjoint(primary_journal, shadow_journal)
    shadow_journal.mkdir(parents=True, exist_ok=True)
    now_utc = now_utc or dt.datetime.now(UTC)
    sweep_deadline = _time.monotonic() + float(max_sweep_seconds)

    cost = CostCap(
        daily_usd_cap=daily_usd_cap,
        ledger_path=shadow_journal / "scenario_cost_ledger.json",
    )
    dedup = DedupSet.load(shadow_journal / "scenario_dedup.json")
    failure_counts_path = shadow_journal / "scenario_failure_counts.json"
    failure_counts: dict[str, int] = {}
    if failure_counts_path.is_file():
        try:
            failure_counts = json.loads(failure_counts_path.read_text())
        except (OSError, json.JSONDecodeError):
            failure_counts = {}
    max_failure_retries = 3
    scenarios_path = shadow_journal / "scenarios_shadow.jsonl"
    telemetry_path = shadow_journal / "scenario_shadow_telemetry.jsonl"
    errors_path = shadow_journal / "scenario_shadow_errors.jsonl"
    store = ScenarioStore(scenarios_path)

    snapshots_by_ts = _index_snapshots_by_bar_ts(primary_journal)
    decisions_path = primary_journal / "decisions.jsonl"

    processed = 0; emitted = 0; skipped_dedup = 0; skipped_budget = 0
    skipped_missing_snapshot = 0; errored = 0
    skipped_historical_backlog = 0
    actions_log: list[dict] = []

    # ------------------------------------------------------------------
    # Freshness gate: never spend live-session AI credits reconstructing
    # yesterday's backlog. The sweeper is responsible for yielding
    # control to TODAY's observations.
    #
    # Rule: a primary decision is "eligible" iff its evaluated_at_utc
    # (= actual generation wall-clock, NOT bar_ts) is within
    # max_primary_age_minutes of now. Older primaries are permanently
    # dedup-marked so a subsequent sweep does not reconsider them. The
    # append-only decisions / scenarios journals are UNTOUCHED.
    #
    # Fresh primaries are sorted DESCENDING by evaluated_at_utc so the
    # latest observation is serviced first when max_pairs is binding.
    # ------------------------------------------------------------------
    age_cutoff = now_utc - dt.timedelta(minutes=max_primary_age_minutes)
    eligible: list[tuple[dt.datetime, dict, str]] = []
    for primary in iter_jsonl(decisions_path):
        bar_ts = primary.get("bar_ts_utc")
        level_id = primary.get("level_id")
        if not bar_ts or not level_id:
            continue
        key = _scenario_dedup_key(bar_ts, level_id)
        if dedup.contains(key):
            skipped_dedup += 1
            continue
        primary_gen = _parse_iso_utc(primary.get("evaluated_at_utc"))
        if primary_gen is None or primary_gen < age_cutoff:
            # Historical backlog: mark permanently so we never
            # repeatedly reconsider or pay to replay it. Preserves the
            # append-only primary journal — only our own dedup grows.
            dedup.add(key)
            skipped_historical_backlog += 1
            continue
        eligible.append((primary_gen, primary, key))

    # Newest-first so operators see today's latest assessment ASAP.
    eligible.sort(key=lambda item: item[0], reverse=True)

    # Persist the fresh dedup additions NOW so a crash before the first
    # LLM call still leaves the historical backlog permanently skipped.
    dedup.save()

    sweep_timeouts = 0
    for _primary_gen, primary, key in eligible:
        # Hard bound ONLY on count. The old 6-per-sweep ceiling could
        # indefinitely delay the newest eligible primary when a backlog
        # grew faster than the per-sweep bound; now max_pairs defaults
        # unlimited (0 → treated as no bound). Wall-clock budget
        # protects a single invocation from running past the next timer
        # firing without stopping observation after a financial cap.
        if max_pairs and processed >= max_pairs:
            break
        if _time.monotonic() > sweep_deadline:
            sweep_timeouts += 1
            break
        bar_ts = primary.get("bar_ts_utc")
        level_id = primary.get("level_id")
        snapshot = snapshots_by_ts.get(bar_ts)
        if snapshot is None:
            skipped_missing_snapshot += 1
            continue
        # Bounded failure recovery: a key that has already failed
        # ``max_failure_retries`` times is permanently dedup-marked so
        # a persistently broken prompt cannot park every sweep. Under
        # the max_failure_retries threshold the key stays eligible and
        # will be retried on the next sweep.
        if failure_counts.get(key, 0) >= max_failure_retries:
            dedup.add(key)
            skipped_dedup += 1
            continue
        # Pre-flight budget reservation (2x per-call ceiling covers the
        # single max_tokens-truncation retry). Only enforced when the
        # operator has set a positive daily_usd_cap; a cap of 0 means
        # "no hard cap, let the sweep run throughout the session".
        # Loop safety is still guaranteed by max_pairs and the dedup
        # set; the per-call ceiling is still logged as a runaway-detect
        # signal after each call.
        if cost.would_exceed(per_call_usd_ceiling * 2):
            skipped_budget += 1
            processed += 1
            continue
        processed += 1

        # Build the same lookahead-safe packet the single-shot shadow uses.
        try:
            shadow_pkt, analogues_full = build_shadow_packet(
                snapshot=snapshot,
                primary_decision=primary,
                corpus=corpus,
                k=k,
                macro_events_file=macro_events,
                macro_source=macro_source,
            )
        except (ValueError, IndexError) as exc:
            append_jsonl(errors_path, {
                "bar_ts_utc": bar_ts, "level_id": level_id,
                "stage": "build_packet",
                "error": f"{type(exc).__name__}: {exc}",
                "at_utc": dt.datetime.now(UTC).isoformat(),
            })
            failure_counts[key] = failure_counts.get(key, 0) + 1
            errored += 1
            continue

        econ = classify_economic_context(
            (shadow_pkt["packet"].get("macro_context") or {}))
        prompt_obj = build_scenario_prompt(
            snapshot=snapshot,
            macro_packet=shadow_pkt["packet"].get("macro_context"),
            open_scenarios=[row_to_dict(r) for r in store.open_scenarios()
                             if r.agent == agent_label and r.pair == snapshot.get("pair", "GBPUSD")],
            analogues=shadow_pkt.get("historical_analogues") or [],
            agent_name=agent_label,
            primary_decision=primary,
        )

        if dry_run:
            assessment = _dry_assessment(prompt_obj)
            est_cost = 0.0
        else:
            try:
                assessment = call_scenario_model(
                    prompt_obj=prompt_obj,
                    model=model,
                    max_tokens=max_tokens,
                )
            except (RuntimeError, ValueError) as exc:
                append_jsonl(errors_path, {
                    "bar_ts_utc": bar_ts, "level_id": level_id,
                    "stage": "ai_call",
                    "error": f"{type(exc).__name__}: {exc}",
                    "at_utc": dt.datetime.now(UTC).isoformat(),
                    "failure_count": failure_counts.get(key, 0) + 1,
                    "max_failure_retries": max_failure_retries,
                })
                failure_counts[key] = failure_counts.get(key, 0) + 1
                try:
                    failure_counts_path.write_text(
                        json.dumps(failure_counts, sort_keys=True),
                        encoding="utf-8")
                except OSError:
                    pass
                errored += 1
                continue
            est_cost = _cost_estimate_usd(assessment)
            cost.add(est_cost)

        # Semantic validation of the model's output BEFORE we apply it.
        # Each flag lands in the telemetry row AND in a dedicated
        # quality-flags journal. The flag list is then collapsed into a
        # single publication decision (VALID / CAUTION / INVALID). The
        # notifier reads the decision to gate OPPORTUNITY delivery; the
        # raw assessment is still appended to the journal untouched so
        # audit tooling can replay it.
        quality_flags = validate_assessment(
            assessment=assessment,
            packet=shadow_pkt["packet"],
            analogues=analogues_full,
            primary_decision=primary,
            economic_context=econ,
        )
        publication = decide_publication(quality_flags)
        if quality_flags:
            quality_log_path = shadow_journal / "scenario_quality_flags.jsonl"
            append_jsonl(quality_log_path, {
                "bar_ts_utc": bar_ts,
                "level_id": level_id,
                "generated_at_utc": dt.datetime.now(UTC).isoformat(),
                "flags": quality_flags,
                "publication_decision": publication,
            })

        # Translate actions into scenario-store writes.
        pair = snapshot.get("pair", "GBPUSD")
        generated_at_utc = dt.datetime.now(UTC).isoformat()
        apply_results = apply_actions(
            store=store,
            actions=assessment.get("actions") or [],
            bar_ts_utc=bar_ts,
            pair=pair,
            agent=agent_label,
            model=assessment.get("model", model),
            economic_context=econ,
            analogue_refs=analogues_full,
            generated_at_utc=generated_at_utc,
            primary_hypothesis=primary.get("hypothesis") or "",
            primary_direction=primary.get("direction") or "",
            publication_decision=publication,
        )

        telem_row = {
            "bar_ts_utc": bar_ts,
            "level_id": level_id,
            "agent": agent_label,
            "evaluated_at_utc": generated_at_utc,
            "generated_at_utc": generated_at_utc,
            "pair": pair,
            "execution_authority": "NONE",
            "schema": "scenario_shadow_telemetry.v1.0",
            "current_interpretation": assessment.get("current_interpretation"),
            "narrative": assessment.get("narrative"),
            "waiting_for": assessment.get("waiting_for") or [],
            "what_would_invalidate": assessment.get("what_would_invalidate") or [],
            "macro_scenarios": assessment.get("macro_scenarios") or [],
            "actions_requested": assessment.get("actions") or [],
            "actions_applied": apply_results,
            "primary_hypothesis": primary.get("hypothesis"),
            "primary_direction": primary.get("direction"),
            "primary_level_id": level_id,
            "primary_evaluated_at_utc": primary.get("evaluated_at_utc"),
            "model": assessment.get("model"),
            "latency_ms": assessment.get("latency_ms"),
            "stop_reason": assessment.get("stop_reason"),
            "usage_input_tokens": assessment.get("usage_input_tokens"),
            "usage_output_tokens": assessment.get("usage_output_tokens"),
            "usage_cache_read_tokens": assessment.get("usage_cache_read_tokens"),
            "usage_cache_creation_tokens": assessment.get("usage_cache_creation_tokens"),
            "api_cost_usd_est": round(est_cost, 6),
            "daily_usd_cap": daily_usd_cap,
            "dry_run": dry_run,
            "k_analogues": k,
            "analogue_fingerprint": shadow_pkt.get("fingerprint"),
            "economic_context_summary": {
                "scheduled": len(econ.get("scheduled") or []),
                "released": len(econ.get("released") or []),
                "expired": len(econ.get("expired") or []),
                "unverified": len(econ.get("unverified") or []),
                "surprises": len(econ.get("surprises") or []),
            },
            "quality_flags": quality_flags,
            "publication_decision": publication,
        }
        # Dedup is added AFTER the scenario + telemetry write succeeds
        # so a failed call never marks an observation as "done".
        # Failures on the AI call branch above do NOT reach this point.
        append_jsonl(telemetry_path, telem_row)
        dedup.add(key)
        # Successful handling clears any accumulated failure count so
        # a flaky-then-healthy observation isn't penalised.
        failure_counts.pop(key, None)
        emitted += 1
        actions_log.extend(apply_results)
        # Persist progress incrementally so a SIGTERM mid-sweep (e.g.
        # systemd TimeoutStartSec) leaves this observation marked
        # complete and the next sweep does not re-pay for it.
        try:
            dedup.save()
            failure_counts_path.write_text(
                json.dumps(failure_counts, sort_keys=True),
                encoding="utf-8")
        except OSError:
            pass

    dedup.save()
    # Persist failure counts so bounded recovery survives restarts.
    try:
        failure_counts_path.write_text(
            json.dumps(failure_counts, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    summary = {
        "processed": processed,
        "emitted": emitted,
        "skipped_dedup": skipped_dedup,
        "skipped_historical_backlog": skipped_historical_backlog,
        "skipped_budget": skipped_budget,
        "skipped_missing_snapshot": skipped_missing_snapshot,
        "errored": errored,
        "actions_total": len(actions_log),
        "actions_propose": sum(1 for a in actions_log if a.get("action") == "PROPOSE"),
        "actions_revise": sum(1 for a in actions_log if a.get("action") == "REVISE"),
        "actions_wait": sum(1 for a in actions_log if a.get("action") == "WAIT"),
        "actions_failed": sum(1 for a in actions_log if not a.get("ok")),
        "spent_today_usd": round(cost.spent_today(), 6),
        "daily_usd_cap": daily_usd_cap,
        "max_primary_age_minutes": max_primary_age_minutes,
        "max_sweep_seconds": max_sweep_seconds,
        "sweep_timed_out": sweep_timeouts > 0,
    }
    LOGGER.info("sweep summary=%s", summary)
    return summary


def _acquire_single_instance_lock(lock_path: pathlib.Path):
    """Return the open fd on success, or None if another sweep holds it.

    A single-instance guard: systemd Type=oneshot already serialises
    this unit, but if the timer fires before the previous sweep has
    finished (long AI call) the overlapping fire exits cleanly rather
    than running a second concurrent sweep.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "a+")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        return None
    return fd


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primary-journal", type=pathlib.Path,
                    default=DEFAULT_PRIMARY_JOURNAL)
    ap.add_argument("--shadow-journal", type=pathlib.Path,
                    default=DEFAULT_SHADOW_JOURNAL)
    ap.add_argument("--corpus", type=pathlib.Path, default=None)
    ap.add_argument("--macro-events", type=pathlib.Path,
                    default=DEFAULT_MACRO_EVENTS)
    ap.add_argument("--macro-source",
                    choices=("operator_jsonl", "host_live", "both"),
                    default="operator_jsonl")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--max-pairs", type=int, default=0,
                    help=("Maximum eligible primaries to analyse per sweep. "
                          "0 (default) = unlimited. Wall-clock budget "
                          "(--max-sweep-seconds) still bounds a single "
                          "sweep. Dedup set prevents re-processing."))
    ap.add_argument("--max-sweep-seconds", type=int, default=270,
                    help=("Wall-clock budget per sweep in seconds. Defaults "
                          "to 270 (= 4m30s), below the systemd "
                          "TimeoutStartSec=300s on the service unit "
                          "and under the 10-min timer cadence. "
                          "Non-financial safety guard."))
    ap.add_argument("--daily-usd-cap", type=float, default=0.00,
                    help=("Daily USD hard cap for Scenario V2 shadow sweeps. "
                          "0 (default) disables the cap — the ledger still "
                          "records spend for observability but no pre-flight "
                          "check gates the sweep. A positive value enforces "
                          "the cap. Infinite-loop prevention is provided by "
                          "--max-pairs and the dedup set."))
    ap.add_argument("--per-call-usd-ceiling", type=float, default=0.08)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--env", type=pathlib.Path,
                    default=pathlib.Path("/opt/tradingbot/.env"))
    ap.add_argument("--agent-label", default="shadow")
    ap.add_argument("--max-primary-age-minutes", type=int, default=120,
                    help=("Primary decisions whose evaluated_at_utc is older "
                          "than this many minutes are permanently skipped "
                          "(dedup-marked) rather than replayed. Prevents a "
                          "live sweep from burning today's AI budget on "
                          "yesterday's backlog."))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    load_env_once(args.env)

    lock_path = args.shadow_journal / "scenario_shadow.lock"
    lock_fd = _acquire_single_instance_lock(lock_path)
    if lock_fd is None:
        LOGGER.info(
            "another scenario-shadow sweep is already running; "
            "skipping this invocation (lock=%s)", lock_path)
        return 0

    corpus_kwargs: dict = {"path": args.corpus} if args.corpus else {}
    corpus = load_corpus(**corpus_kwargs)
    LOGGER.info("corpus loaded size=%d range=%s", corpus.size, corpus.date_range)
    result = sweep(
        primary_journal=args.primary_journal,
        shadow_journal=args.shadow_journal,
        corpus=corpus,
        k=args.k,
        max_pairs=args.max_pairs,
        daily_usd_cap=args.daily_usd_cap,
        per_call_usd_ceiling=args.per_call_usd_ceiling,
        model=args.model,
        max_tokens=args.max_tokens,
        macro_events=args.macro_events,
        macro_source=args.macro_source,
        dry_run=args.dry_run,
        agent_label=args.agent_label,
        max_primary_age_minutes=args.max_primary_age_minutes,
        max_sweep_seconds=args.max_sweep_seconds,
    )
    LOGGER.info("done %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
