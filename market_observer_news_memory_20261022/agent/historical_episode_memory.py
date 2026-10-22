"""Point-in-time historical episode memory for the Live Market Observer.

Reads the phase7b.v1.0 interaction corpus (17,804 GBPUSD episodes,
2024-01-01 .. 2026-09-25) and exposes a strict as-of retriever.

Hard contract — enforced by every public call:

  * ``asof`` is a timezone-aware UTC datetime. An episode E is eligible
    at asof ONLY if ``E.episode_end_ts <= asof``. Episodes still open at
    asof — i.e. whose outcome would require future bars to determine —
    are INVISIBLE. This holds whether the asof lies inside the corpus
    (replay against a historical bar) or after it (live use).

  * Field ``physical_outcome`` is a *past* fact at the point ``episode_end_ts``.
    Returning it only after the end-ts gate is what makes retrieval
    leak-free.

  * No AutoBot imports. No broker calls. Pure file reader + in-memory
    index. Reads only files beneath the research volume and the
    read-only corpus path.

Fingerprint
-----------
Live observations arrive from the primary observer snapshot schema:
  * ``bar_ts_utc`` — ISO UTC string.
  * ``interactions[]`` with ``level_type`` and raw structural fields.
  * ``nms`` with ``state`` and ``demonstrated_direction``.

The retrieval fingerprint uses the SAME fields present in the corpus
rows, mapped mechanically from the live snapshot:
  * ``session``  — bucket derived from ``bar_ts_utc`` hour.
  * ``hour_utc`` — raw hour, used with a +-1 tolerance.
  * ``level_type`` — the specific level under observation.
  * ``approach`` — UP / DOWN / AMBIGUOUS derived from close_side.
  * ``n_tests_bucket`` — bucket of interaction_elapsed_bars / 5.

Match scoring is deterministic and documented; no LLM call is made.

Public API
----------
  * ``load_corpus(path=DEFAULT_CORPUS)`` → ``Corpus``
  * ``Corpus.retrieve(asof, fingerprint, k=5)`` → list[Analogue]
  * ``fingerprint_from_snapshot(snapshot, interaction_idx)`` → dict

All timestamps are aware UTC.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import pathlib
from typing import Any, Iterable

LOGGER = logging.getLogger("historical_episode_memory")

UTC = dt.timezone.utc

DEFAULT_CORPUS = pathlib.Path(
    "/mnt/volume_lon1_1778405456698/derived/"
    "interaction_corpus/GBPUSD_phase7b_v1.jsonl"
)


def parse_utc(value: str | dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def session_bucket(hour: int) -> str:
    if 0 <= hour < 6:
        return "ASIA"
    if 6 <= hour < 11:
        return "LONDON"
    if 11 <= hour < 16:
        return "LONDON_NY"
    if 16 <= hour < 21:
        return "NY"
    return "LATE_NY"


def approach_from_live(close_side: str | None,
                        demonstrated_direction: str | None) -> str:
    """Map live snapshot into corpus ``approach`` taxonomy (UP/DOWN/AMBIGUOUS).

    close_side is the live LOI field ``raw.close_side`` ∈ {"above","below"}.
    demonstrated_direction is the NMS field ∈ {"UP","DOWN", None}.
    """
    if demonstrated_direction == "UP":
        return "UP"
    if demonstrated_direction == "DOWN":
        return "DOWN"
    if close_side == "above":
        return "UP"
    if close_side == "below":
        return "DOWN"
    return "AMBIGUOUS"


def fingerprint_from_snapshot(snapshot: dict,
                               interaction_idx: int = 0) -> dict:
    """Build a corpus fingerprint from a live snapshot row.

    ``interaction_idx`` selects which ``interactions[]`` entry to use.
    Raises IndexError if the snapshot has no interactions at that index.
    """
    bar_ts = parse_utc(snapshot.get("bar_ts_utc"))
    if bar_ts is None:
        raise ValueError("snapshot missing bar_ts_utc")
    interactions = snapshot.get("interactions") or []
    if not interactions or interaction_idx >= len(interactions):
        raise IndexError(f"interactions[{interaction_idx}] not present")
    inter = interactions[interaction_idx]
    raw = inter.get("raw") or {}
    nms = snapshot.get("nms") or {}
    hour = bar_ts.hour
    return {
        "pair": snapshot.get("pair", "GBPUSD"),
        "asof": bar_ts,
        "session": session_bucket(hour),
        "hour_utc": hour,
        "level_type": inter.get("level_type"),
        "approach": approach_from_live(
            raw.get("close_side"),
            nms.get("demonstrated_direction")
            or (nms.get("demonstrated_evidence") or {}).get("demonstrated_direction"),
        ),
        "n_tests_bucket": _n_tests_bucket(raw.get("interaction_elapsed_bars")),
    }


def _n_tests_bucket(elapsed_bars: int | None) -> str:
    if elapsed_bars is None:
        return "UNK"
    if elapsed_bars <= 5:
        return "SHORT"
    if elapsed_bars <= 20:
        return "MED"
    if elapsed_bars <= 60:
        return "LONG"
    return "VERY_LONG"


def _n_tests_bucket_corpus(n_tests: int | None) -> str:
    return _n_tests_bucket(n_tests)


@dataclasses.dataclass(frozen=True)
class Episode:
    episode_id: str
    pair: str
    date: str
    session: str
    hour_utc: int
    level_types: tuple[str, ...]
    approach: str
    n_tests: int
    n_tests_bucket: str
    physical_outcome: str
    mfe_mae_from_early: dict
    T0: dt.datetime
    T1: dt.datetime
    episode_end_ts: dt.datetime
    T4_early_ts: dt.datetime | None
    T5_confirmed_ts: dt.datetime | None


@dataclasses.dataclass(frozen=True)
class Analogue:
    episode_id: str
    date: str
    session: str
    hour_utc: int
    level_types: tuple[str, ...]
    approach: str
    n_tests_bucket: str
    physical_outcome: str
    mfe_60: float | None
    mae_60: float | None
    score: int
    episode_end_ts: dt.datetime


class Corpus:
    """In-memory corpus with as-of filter and fingerprint-based retrieval."""

    def __init__(self, episodes: list[Episode], source: pathlib.Path):
        self._episodes = episodes
        self._source = source
        # Sort by episode_end_ts to enable binary search by asof upper bound.
        self._by_end = sorted(episodes, key=lambda e: e.episode_end_ts)
        self._end_ts_list = [e.episode_end_ts for e in self._by_end]

    @property
    def size(self) -> int:
        return len(self._episodes)

    @property
    def source(self) -> pathlib.Path:
        return self._source

    @property
    def date_range(self) -> tuple[str, str]:
        if not self._episodes:
            return ("", "")
        return (
            min(e.date for e in self._episodes),
            max(e.date for e in self._episodes),
        )

    def _eligible(self, asof: dt.datetime) -> list[Episode]:
        """All episodes with episode_end_ts <= asof (strictly past)."""
        import bisect
        # bisect_right returns first index whose end_ts > asof.
        cut = bisect.bisect_right(self._end_ts_list, asof)
        return self._by_end[:cut]

    def retrieve(self,
                 asof: dt.datetime,
                 fingerprint: dict,
                 k: int = 5) -> list[Analogue]:
        """Top-k historical analogues at asof (strict episode_end_ts <= asof).

        Scoring (higher = better):
          +4  same approach
          +3  level_type in episode.level_types
          +2  same session
          +1  hour within +-1
          +1  same n_tests_bucket
        Ties broken by (recency, episode_id).
        Returns an empty list if nothing qualifies.
        """
        if asof.tzinfo is None:
            raise ValueError("asof must be timezone-aware UTC")
        if asof.tzinfo.utcoffset(asof) != dt.timedelta(0):
            raise ValueError("asof must be UTC")
        fp_approach = fingerprint.get("approach")
        fp_level = fingerprint.get("level_type")
        fp_session = fingerprint.get("session")
        fp_hour = fingerprint.get("hour_utc")
        fp_bucket = fingerprint.get("n_tests_bucket")
        scored: list[tuple[int, Episode]] = []
        for e in self._eligible(asof):
            score = 0
            if fp_approach and e.approach == fp_approach:
                score += 4
            if fp_level and fp_level in e.level_types:
                score += 3
            if fp_session and e.session == fp_session:
                score += 2
            if fp_hour is not None and abs(e.hour_utc - fp_hour) <= 1:
                score += 1
            if fp_bucket and e.n_tests_bucket == fp_bucket:
                score += 1
            if score > 0:
                scored.append((score, e))
        # Sort by (score desc, episode_end_ts desc for recency, episode_id).
        scored.sort(key=lambda t: (-t[0],
                                   -t[1].episode_end_ts.timestamp(),
                                   t[1].episode_id))
        out: list[Analogue] = []
        for score, e in scored[:k]:
            m60 = (e.mfe_mae_from_early or {}).get("60") or {}
            out.append(Analogue(
                episode_id=e.episode_id,
                date=e.date,
                session=e.session,
                hour_utc=e.hour_utc,
                level_types=e.level_types,
                approach=e.approach,
                n_tests_bucket=e.n_tests_bucket,
                physical_outcome=e.physical_outcome,
                mfe_60=m60.get("mfe"),
                mae_60=m60.get("mae"),
                score=score,
                episode_end_ts=e.episode_end_ts,
            ))
        return out


def _row_to_episode(row: dict) -> Episode | None:
    try:
        comps = row.get("components") or []
        level_types = tuple(sorted({c.get("type") for c in comps if c.get("type")}))
        episode_end = parse_utc(row.get("episode_end_ts"))
        T0 = parse_utc(row.get("T0"))
        T1 = parse_utc(row.get("T1"))
        if episode_end is None or T0 is None or T1 is None:
            return None
        hour_utc = T1.hour
        return Episode(
            episode_id=row["episode_id"],
            pair=row.get("pair", "GBPUSD"),
            date=row.get("date", ""),
            session=session_bucket(hour_utc),
            hour_utc=hour_utc,
            level_types=level_types,
            approach=row.get("approach", "AMBIGUOUS"),
            n_tests=int(row.get("n_tests") or 0),
            n_tests_bucket=_n_tests_bucket_corpus(row.get("n_tests")),
            physical_outcome=row.get("physical_outcome", "UNRESOLVED"),
            mfe_mae_from_early=row.get("mfe_mae_from_early") or {},
            T0=T0,
            T1=T1,
            episode_end_ts=episode_end,
            T4_early_ts=parse_utc(row.get("T4_early_ts")),
            T5_confirmed_ts=parse_utc(row.get("T5_confirmed_ts")),
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("skipping malformed row: %s", exc)
        return None


def load_corpus(path: pathlib.Path = DEFAULT_CORPUS) -> Corpus:
    path = pathlib.Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    episodes: list[Episode] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ep = _row_to_episode(row)
            if ep is not None:
                episodes.append(ep)
    LOGGER.info("loaded %d episodes from %s", len(episodes), path)
    return Corpus(episodes, source=path)


__all__ = [
    "Corpus",
    "Episode",
    "Analogue",
    "fingerprint_from_snapshot",
    "approach_from_live",
    "session_bucket",
    "parse_utc",
    "load_corpus",
    "DEFAULT_CORPUS",
]
