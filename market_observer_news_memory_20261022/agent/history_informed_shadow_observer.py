"""History-informed shadow observer.

Sweeps the primary observer's snapshot journal, computes a point-in-time
historical-episode retrieval for each new snapshot, and writes the
analogue packet to a SEPARATE journal:

    /mnt/.../live_obs/journal_shadow/analogues.jsonl

The shadow observer:

  * Reads only from the primary journal (open for reading, never write).
  * Writes only to the shadow journal, under a dedicated directory that
    the primary observer never touches.
  * Makes no LLM calls — pure deterministic retrieval. No ANTHROPIC_API_KEY
    is loaded.
  * Makes no broker calls, no autobot imports.
  * No historical strategy optimisation or new backtests. Each row is a
    neutral list of nearest analogues with their *known* outcomes and
    MFE/MAE — a memory lookup, not a prediction.
  * Resumable: records the byte offset it last processed in
    ``_offset.json`` so interrupted runs continue where they stopped.
  * Idempotent per snapshot_hash so a replay-safe cursor + a dedup set
    guarantee one row per (bar_ts, interaction_id) across runs.

Flags: --once (process pending snapshots and exit) is the default; this
is a timer-driven sweeper, not a long-running daemon. --max-snapshots
caps the batch size so a long outage won't fire an unbounded burst.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import pathlib
import sys
from typing import Any, Iterable

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from historical_episode_memory import (  # noqa: E402
    Analogue,
    Corpus,
    fingerprint_from_snapshot,
    load_corpus,
)

UTC = dt.timezone.utc
LOGGER = logging.getLogger("history_informed_shadow_observer")

DEFAULT_PRIMARY_JOURNAL = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/journal"
)
DEFAULT_SHADOW_JOURNAL = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow"
)

# Hard: the shadow journal must NEVER equal the primary journal.
def _ensure_disjoint(primary: pathlib.Path, shadow: pathlib.Path) -> None:
    p = primary.resolve()
    s = shadow.resolve()
    if p == s or str(s).startswith(str(p) + "/"):
        raise ValueError(
            f"shadow journal {s} must not live under primary {p}")


def _analogue_to_dict(a: Analogue) -> dict:
    d = dataclasses.asdict(a)
    d["episode_end_ts"] = a.episode_end_ts.isoformat()
    d["level_types"] = list(a.level_types)
    return d


def _snapshot_hash(bar_ts: str, interaction_id: str) -> str:
    h = hashlib.sha256()
    h.update(bar_ts.encode("utf-8"))
    h.update(b"\0")
    h.update(interaction_id.encode("utf-8"))
    return h.hexdigest()[:16]


def _load_offset(path: pathlib.Path) -> tuple[int, set[str]]:
    if not path.is_file():
        return 0, set()
    data = json.loads(path.read_text())
    return int(data.get("offset", 0)), set(data.get("seen", []))


def _save_offset(path: pathlib.Path, offset: int, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the dedup set bounded. 10,000 hashes is ~160 KB on disk;
    # since each snapshot produces at most ~10 interactions, this
    # covers ~2 weeks of continuous observation.
    bounded = list(sorted(seen))[-10000:]
    path.write_text(json.dumps({"offset": offset, "seen": bounded}))


def process_snapshot(corpus: Corpus,
                      snapshot: dict,
                      k: int) -> Iterable[dict]:
    """Yield one analogue packet per interaction in the snapshot."""
    interactions = snapshot.get("interactions") or []
    if not interactions:
        return
    for idx, inter in enumerate(interactions):
        try:
            fp = fingerprint_from_snapshot(snapshot, interaction_idx=idx)
        except (IndexError, ValueError) as exc:
            LOGGER.warning("skipping interaction %d: %s", idx, exc)
            continue
        asof = fp.pop("asof")
        analogues = corpus.retrieve(asof, fp, k=k)
        yield {
            "bar_ts_utc": asof.isoformat(),
            "interaction_id": inter.get("interaction_id", ""),
            "interaction_idx": idx,
            "fingerprint": fp,
            "k_requested": k,
            "analogues": [_analogue_to_dict(a) for a in analogues],
            "shadow_schema": "history_informed_shadow.v1.0",
            "generated_at_utc": dt.datetime.now(UTC).isoformat(),
            "primary_journal_only_read": True,
        }


def sweep(primary_journal: pathlib.Path,
          shadow_journal: pathlib.Path,
          corpus: Corpus,
          k: int,
          max_snapshots: int) -> dict:
    _ensure_disjoint(primary_journal, shadow_journal)
    snapshots_file = primary_journal / "snapshots.jsonl"
    if not snapshots_file.is_file():
        LOGGER.info("primary snapshots file not yet present: %s",
                    snapshots_file)
        return {"processed": 0, "written": 0}
    shadow_journal.mkdir(parents=True, exist_ok=True)
    offset_file = shadow_journal / "_offset.json"
    analogues_file = shadow_journal / "analogues.jsonl"
    offset, seen = _load_offset(offset_file)
    processed = 0
    written = 0
    with snapshots_file.open("rb") as f:
        f.seek(offset)
        with analogues_file.open("a", encoding="utf-8") as out:
            for raw in f:
                if processed >= max_snapshots:
                    break
                offset = f.tell()
                try:
                    snapshot = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    LOGGER.warning("skipping malformed snapshot line")
                    continue
                for packet in process_snapshot(corpus, snapshot, k):
                    h = _snapshot_hash(packet["bar_ts_utc"],
                                       packet["interaction_id"])
                    if h in seen:
                        continue
                    seen.add(h)
                    out.write(json.dumps(packet, sort_keys=True) + "\n")
                    written += 1
                processed += 1
            out.flush()
    _save_offset(offset_file, offset, seen)
    LOGGER.info("sweep: processed=%d  written=%d  offset=%d  seen=%d",
                processed, written, offset, len(seen))
    return {"processed": processed, "written": written,
            "offset": offset, "seen": len(seen)}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primary-journal", type=pathlib.Path,
                    default=DEFAULT_PRIMARY_JOURNAL)
    ap.add_argument("--shadow-journal", type=pathlib.Path,
                    default=DEFAULT_SHADOW_JOURNAL)
    ap.add_argument("--k", type=int, default=5,
                    help="analogues per interaction (default 5)")
    ap.add_argument("--max-snapshots", type=int, default=1000,
                    help="cap snapshots processed per sweep (default 1000)")
    ap.add_argument("--corpus", type=pathlib.Path, default=None,
                    help="override corpus path (default: library default)")
    args = ap.parse_args(argv)

    corpus_kwargs = {"path": args.corpus} if args.corpus else {}
    corpus = load_corpus(**corpus_kwargs)
    LOGGER.info("corpus loaded size=%d range=%s", corpus.size, corpus.date_range)
    result = sweep(args.primary_journal, args.shadow_journal,
                   corpus, args.k, args.max_snapshots)
    LOGGER.info("done %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
