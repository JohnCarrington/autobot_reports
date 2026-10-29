"""C3 AI acceptance test — real Haiku inference against recorded packets.

Loads a recorded snapshot (packet) for a specific bar+level, enriches it
with the C3 reassessment_triggers + enriched compact_prior, and calls
Haiku with the staged C3 SYSTEM prompt. Records the complete response.

Historical-asof discipline:
  * The snapshot is EXACTLY what the live observer saw at that bar.
  * The prior decision is the recorded decision for the SAME level_id
    from the PREVIOUS bar — this is what compact_prior() would have
    seen had C3 been active.
  * macro_context on the snapshot is already asof-gated to the bar close.
  * The current wall clock does NOT influence the AI's view of the past.

Output: per-bar JSONL + summary to the caller.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time

# C3-staged observer module
HERE = pathlib.Path(__file__).resolve().parent
STAGING = HERE.parent / "staging" / "agent"
sys.path.insert(0, str(STAGING))
import live_market_observer_agent_news as obs  # noqa: E402


def _load_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def _find_snapshot_and_prior(bar_ts: str, level_id: str,
                               snapshots: list[dict],
                               decisions: list[dict]) -> tuple[dict | None, dict | None, dict | None]:
    """Return (snapshot, prior_decision, baseline_decision_at_bar).

    snapshot: packet captured for bar_ts
    prior_decision: last decision on this level BEFORE bar_ts (used to
                    seed compact_prior for the AI)
    baseline_decision_at_bar: the actual AI decision recorded for this
                               bar — the pre-C3 baseline to compare
                               against.
    """
    snap = next((s for s in snapshots if s.get("bar_ts_utc") == bar_ts), None)
    prior_decision = None
    baseline = None
    for d in decisions:
        if d.get("bar_ts_utc") == bar_ts and d.get("level_id") == level_id:
            baseline = d
        if d.get("level_id") != level_id:
            continue
        if d.get("bar_ts_utc", "") < bar_ts:
            # keep most recent prior
            if prior_decision is None or d.get("bar_ts_utc", "") > prior_decision.get("bar_ts_utc", ""):
                prior_decision = d
    return snap, prior_decision, baseline


def _c3_enriched_packet(snap: dict, level_id: str,
                         prior_decision: dict | None,
                         history: list[dict]) -> dict:
    """Return a copy of the snapshot with C3-specific fields added:
    enriched previous_assessments[level_id] and reassessment_triggers."""
    pkt = json.loads(json.dumps(snap, default=str))  # deep copy

    # Enrich previous_assessments with C3 compact_prior shape
    prior_compact = obs.compact_prior(prior_decision) if prior_decision else None
    if "previous_assessments" not in pkt:
        pkt["previous_assessments"] = {}
    pkt["previous_assessments"][level_id] = prior_compact

    # Compute reassessment_triggers for the target level
    inter = None
    for it in pkt.get("interactions", []):
        if it.get("interaction_id") == level_id:
            inter = it
            break
    nms_row = pkt.get("nms")

    if "reassessment_triggers" not in pkt:
        pkt["reassessment_triggers"] = {}
    pkt["reassessment_triggers"][level_id] = obs.compute_reassessment_trigger(
        interactions_row=inter, nms_row=nms_row,
        prior=prior_compact, history=history)

    return pkt


def _call_haiku(pkt: dict, model: str = "claude-haiku-4-5-20251001") -> dict:
    """Call Haiku with the C3 SYSTEM prompt. Mirrors obs.ai_call() but
    skips the stop_reason/retry gymnastics for the single-call case
    we need in acceptance testing.
    """
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    client = anthropic.Anthropic(api_key=key)
    valid_ids = [it.get("interaction_id") for it in pkt.get("interactions", [])]
    schema_note = {
        "level_ids_available": valid_ids,
        "level_id_source_field": "interactions[*].interaction_id",
        "required_contract": (
            "The response field `level_id` MUST be a non-null string copied "
            "verbatim from `level_ids_available`."),
    }
    user_payload = json.dumps({"packet": pkt, "contract": schema_note},
                                default=str, sort_keys=True)
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=obs.SYSTEM,
        messages=[{"role": "user", "content": user_payload}],
        tools=[obs.OBSERVATION_TOOL],
        tool_choice={"type": "tool", "name": "return_observation"},
    )
    tool_input = None
    text_parts = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use" and getattr(block, "name", "") == "return_observation":
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                tool_input = inp
        elif btype == "text":
            text_parts.append(getattr(block, "text", "") or "")
    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", None),
        "output_tokens": getattr(resp.usage, "output_tokens", None),
    }
    return {
        "model": model,
        "stop_reason": getattr(resp, "stop_reason", None),
        "tool_use": tool_input,
        "text_fallback": "\n".join(text_parts) if text_parts else None,
        "usage": usage,
    }


def run(bars: list[dict], out_path: pathlib.Path):
    """bars: list of {bar_ts, level_id, label} dicts."""
    decisions = _load_jsonl(pathlib.Path(
        "/mnt/volume_lon1_1778405456698/research/live_obs/journal/decisions.jsonl"))
    snapshots = _load_jsonl(pathlib.Path(
        "/mnt/volume_lon1_1778405456698/research/live_obs/journal/snapshots.jsonl"))
    decisions.sort(key=lambda r: r.get("bar_ts_utc", ""))

    out_rows = []
    total_cost = 0.0
    # Haiku 4.5 pricing: input $0.80/M, output $4/M (approximate)
    for i, bar in enumerate(bars):
        bar_ts = bar["bar_ts"]
        level_id = bar["level_id"]
        label = bar["label"]
        snap, prior, baseline = _find_snapshot_and_prior(
            bar_ts, level_id, snapshots, decisions)
        if not snap:
            print(f"[{label}] NO SNAPSHOT for {bar_ts}")
            continue

        history = [d for d in decisions if d.get("bar_ts_utc", "") < bar_ts]
        pkt = _c3_enriched_packet(snap, level_id, prior, history)

        trig = pkt.get("reassessment_triggers", {}).get(level_id, {})
        print(f"[{label}] {bar_ts} trigger_fired={trig.get('trigger_fired')} "
              f"n_reasons={len(trig.get('reasons') or [])} age_bars={trig.get('age_bars')}")

        try:
            start = time.time()
            resp = _call_haiku(pkt)
            elapsed = time.time() - start
        except Exception as exc:
            print(f"[{label}] ERROR: {type(exc).__name__}: {exc}")
            baseline_fields = None
            if baseline:
                baseline_fields = {k: baseline.get(k)
                                    for k in ("hypothesis", "direction")}
            out_rows.append({
                "label": label, "bar_ts": bar_ts, "level_id": level_id,
                "error": f"{type(exc).__name__}: {exc}"[:400],
                "baseline": baseline_fields,
            })
            continue

        tool = resp.get("tool_use") or {}
        in_tok = resp.get("usage", {}).get("input_tokens") or 0
        out_tok = resp.get("usage", {}).get("output_tokens") or 0
        est_cost = in_tok * 0.80 / 1_000_000 + out_tok * 4.0 / 1_000_000
        total_cost += est_cost

        row = {
            "label": label,
            "bar_ts": bar_ts,
            "level_id": level_id,
            "trigger_fired": trig.get("trigger_fired"),
            "trigger_reasons": trig.get("reasons"),
            "trigger_age_bars": trig.get("age_bars"),
            "trigger_invalidation_delta": trig.get("prior_invalidation_delta"),
            "prior_hypothesis": (prior.get("hypothesis") if prior else None),
            "prior_direction": (prior.get("direction") if prior else None),
            # Baseline (pre-C3) response for this bar
            "baseline_hypothesis": baseline.get("hypothesis") if baseline else None,
            "baseline_direction": baseline.get("direction") if baseline else None,
            "baseline_narrative": (baseline.get("narrative") or "")[:300] if baseline else None,
            # C3 Haiku response
            "c3_hypothesis": tool.get("hypothesis"),
            "c3_direction": tool.get("direction"),
            "c3_hypothesis_status": tool.get("hypothesis_status"),
            "c3_narrative": (tool.get("narrative") or "")[:300],
            "c3_change_since_previous": (tool.get("change_since_previous") or "")[:300],
            "c3_supporting_evidence": tool.get("supporting_evidence"),
            "c3_counter_evidence": tool.get("counter_evidence"),
            "c3_invalidation_conditions": tool.get("invalidation_conditions"),
            "c3_uncertainty": (tool.get("uncertainty") or "")[:200],
            "haiku_input_tokens": in_tok,
            "haiku_output_tokens": out_tok,
            "haiku_elapsed_sec": round(elapsed, 2),
            "haiku_est_cost_usd": round(est_cost, 5),
            "stop_reason": resp.get("stop_reason"),
        }
        out_rows.append(row)
        with out_path.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")

    print(f"\nDone. Total estimated cost: ${total_cost:.4f} across {len(out_rows)} bars.")
    return out_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--env", default="/opt/tradingbot/.env")
    args = ap.parse_args()

    # Load env for API key
    obs.load_env_once(pathlib.Path(args.env))

    out_path = pathlib.Path(args.out)
    out_path.unlink(missing_ok=True)

    bars = [
        # 27 Oct — 114-bar incident on level b30a32a8d645a176 (S1=13319.27)
        {"bar_ts": "2026-10-27T07:30:00+00:00", "level_id": "b30a32a8d645a176",
         "label": "oct27_streak_bar2_07:30"},
        {"bar_ts": "2026-10-27T09:55:00+00:00", "level_id": "b30a32a8d645a176",
         "label": "oct27_streak_bar30_09:55"},
        {"bar_ts": "2026-10-27T14:05:00+00:00", "level_id": "b30a32a8d645a176",
         "label": "oct27_streak_bar80_14:05"},

        # 29 Oct — 75-bar incident on level 4245f2ce0c4aee0f (PIVOT=13313.27)
        {"bar_ts": "2026-10-29T06:55:00+00:00", "level_id": "4245f2ce0c4aee0f",
         "label": "oct29_streak_bar2_06:55"},
        {"bar_ts": "2026-10-29T08:00:00+00:00", "level_id": "4245f2ce0c4aee0f",
         "label": "oct29_streak_bar14_08:00_peakcontra"},
        {"bar_ts": "2026-10-29T09:20:00+00:00", "level_id": "4245f2ce0c4aee0f",
         "label": "oct29_streak_bar25_09:20_reversal"},

        # 22 Oct — quiet NO_OPPORTUNITY control (level f420037e43419b20)
        {"bar_ts": "2026-10-22T10:45:00+00:00", "level_id": "f420037e43419b20",
         "label": "oct22_quiet_bar20_10:45"},
        {"bar_ts": "2026-10-22T13:05:00+00:00", "level_id": "f420037e43419b20",
         "label": "oct22_quiet_bar40_13:05"},
        {"bar_ts": "2026-10-22T14:45:00+00:00", "level_id": "f420037e43419b20",
         "label": "oct22_quiet_bar60_14:45"},

        # 23 Oct — GENUINE 74-bar sustained rejection on eecc8b93a0c0d716 SELL
        # (97% confirming price-stayed-below behaviour)
        {"bar_ts": "2026-10-23T06:05:00+00:00", "level_id": "eecc8b93a0c0d716",
         "label": "oct23_genuine_rej_bar2_06:05"},
        {"bar_ts": "2026-10-23T07:40:00+00:00", "level_id": "eecc8b93a0c0d716",
         "label": "oct23_genuine_rej_bar20_07:40"},
        {"bar_ts": "2026-10-23T10:30:00+00:00", "level_id": "eecc8b93a0c0d716",
         "label": "oct23_genuine_rej_bar50_10:30"},
    ]
    run(bars, out_path)


if __name__ == "__main__":
    main()
