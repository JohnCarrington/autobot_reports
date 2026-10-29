"""Scenario reasoning schema with append-only persistence.

The Market Observer uses scenarios to describe anticipated multi-stage
market developments. A scenario is NOT a trade: it is a hypothesis of
how price might traverse structural levels given current context, with
explicit confirmation/invalidation conditions.

Design contract
---------------

* **Append-only.** Every state change writes a NEW row to the
  scenarios journal; the original creation row is never mutated. The
  state machine is reconstructed by replaying all rows in bar_ts order.

* **Deterministic IDs.** scenario_id = sha256-16 of
  ``(pair, bar_ts_utc, primary_level_id, initial_sequence_hash)`` at
  creation time. A revision of the SAME scenario preserves the
  scenario_id and increments revision_idx.

* **Lookahead safety.** A revision row's ``bar_ts_utc`` MUST be
  strictly greater than or equal to the creation row's ``bar_ts_utc``.
  Enforced at write time; a replay harness that provides a snapshot at
  bar_ts cannot inject a revision whose bar_ts is in the past (which
  would simulate seeing the future outcome).

* **Interpretation separation.** ``initial_interpretation`` (the
  original hypothesis, verbatim) is written only once at creation and
  carried forward unchanged. Revisions may add ``current_interpretation``
  but never rewrite ``initial_interpretation``.

* **Opportunities ≠ trades.** The ``opportunities`` field lists
  potential directional/reversal setups with the price behaviour
  required before any entry would be considered. The schema itself
  grants no execution authority. ``execution_authority="NONE"`` is
  recorded on every row.

States
------
PROPOSED      — scenario freshly hypothesised; no confirming price action yet.
WATCHING      — a precondition has been met; waiting for the move to begin.
DEVELOPING    — price is moving as anticipated but destinations not yet reached.
CONFIRMED     — a confirmation criterion has been satisfied (not an entry!).
INVALIDATED   — an invalidation condition has fired.
COMPLETED     — the scenario reached its final anticipated stage.

Transitions follow a DAG (self-loops allowed for WATCHING/DEVELOPING
revisions that update supporting evidence without changing the state):

    PROPOSED  -> WATCHING -> DEVELOPING -> CONFIRMED -> COMPLETED
                                        -> INVALIDATED
              -> INVALIDATED (direct from any non-terminal state)
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable

UTC = dt.timezone.utc

VALID_STATES = frozenset({
    "PROPOSED", "WATCHING", "DEVELOPING",
    "CONFIRMED", "INVALIDATED", "COMPLETED",
})

TERMINAL_STATES = frozenset({"CONFIRMED", "INVALIDATED", "COMPLETED"})

ALLOWED_TRANSITIONS = {
    "PROPOSED":    {"PROPOSED", "WATCHING", "DEVELOPING", "INVALIDATED"},
    "WATCHING":    {"WATCHING", "DEVELOPING", "INVALIDATED"},
    "DEVELOPING":  {"DEVELOPING", "CONFIRMED", "INVALIDATED", "COMPLETED"},
    "CONFIRMED":   {"CONFIRMED", "COMPLETED", "INVALIDATED"},
    # Terminal states can revise their own metadata (same-state rows) but
    # cannot change state. We allow self-rows only.
    "INVALIDATED": {"INVALIDATED"},
    "COMPLETED":   {"COMPLETED"},
}


def _iso(d: dt.datetime) -> str:
    if d.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    if d.utcoffset() != dt.timedelta(0):
        raise ValueError("timestamps must be UTC")
    return d.isoformat()


def parse_utc(value: str | dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class StructuralDestination:
    """One leg in the anticipated sequence (e.g., 'R1' → 'PIVOT'→ 'S1')."""
    label: str                # 'R1', 'PIVOT', 'S1', 'PDH', 'PDL', 'SWING_HI_13433', ...
    price: float | None       # None if label is nominal only (e.g., 'POSSIBLE_REVERSAL')
    role: str                 # 'start', 'first_target', 'extension', 'reversal_zone'
    note: str = ""            # free-form, bounded by prompt caller

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Opportunity:
    """A potential trade set-up, NOT an entry."""
    kind: str                 # 'INITIAL_DIRECTIONAL' | 'SUBSEQUENT_REVERSAL' | 'WAIT'
    direction: str | None     # 'BUY' | 'SELL' | None
    required_price_behaviour: str
    structural_target: str | None
    note: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class EvidenceBundle:
    supporting: tuple[str, ...]
    contradicting: tuple[str, ...]
    needed_info: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "supporting": list(self.supporting),
            "contradicting": list(self.contradicting),
            "needed_info": list(self.needed_info),
            "invalidation_conditions": list(self.invalidation_conditions),
        }


@dataclasses.dataclass(frozen=True)
class ScenarioRow:
    """One row in the scenarios journal — immutable after write.

    Required invariants:
      * scenario_id is derived from the creation row; revisions reuse it.
      * revision_idx starts at 0 and strictly increases per scenario_id.
      * created_at_utc is the creation row's bar_ts_utc, carried forward.
      * revised_at_utc is this row's bar_ts_utc; monotonic across rows.
      * generated_at_utc is the ACTUAL wall-clock when the AI call that
        produced this row completed. Distinct from bar_ts_utc so a
        downstream consumer can tell "live analysis of this bar" from
        "retrospective reconstruction of this bar". May be the empty
        string on legacy rows written before this field existed; new
        writes always set it.
    """
    scenario_id: str
    revision_idx: int
    created_at_utc: str            # ISO UTC, carried forward verbatim
    revised_at_utc: str            # ISO UTC, THIS row's observation ts
    bar_ts_utc: str                # Observation bar that triggered this row
    agent: str                     # 'primary' | 'shadow'
    pair: str
    state: str
    initial_interpretation: str    # Verbatim from creation; never mutated
    current_interpretation: str    # Updated with revisions
    anticipated_sequence: list[StructuralDestination]
    opportunities: list[Opportunity]
    evidence: EvidenceBundle
    economic_context: dict         # {'scheduled': [...], 'released': [...], 'surprise': [...]}
    confirmation_criteria: list[str]
    change_from_previous: str      # Why this revision was written
    analogue_refs: list[dict]      # Shadow only; empty for primary
    source_model: str              # e.g., 'claude-haiku-4-5-20251001'
    execution_authority: str       # Always 'NONE'
    schema_version: str            # 'scenario.v1.0'
    generated_at_utc: str = ""     # Wall-clock AI generation time
    primary_hypothesis: str = ""   # Primary observer's hypothesis at this bar
    primary_direction: str = ""    # Primary observer's direction (BUY/SELL/'')
    publication_decision: dict = dataclasses.field(default_factory=dict)
    # {"decision": VALID/CAUTION/INVALID, "reason": "...", "flag_codes": [...]}
    trade_proposal: dict = dataclasses.field(default_factory=dict)
    # Optional structured proposal: {"direction": BUY/SELL, "entry_price",
    # "stop_price", "target_price", "entry_trigger", "stop_rationale",
    # "target_rationale"}. Empty dict when the AI did not supply one.


# ---------------------------------------------------------------------
# ID derivation
# ---------------------------------------------------------------------

def derive_scenario_id(pair: str,
                       creation_bar_ts: str,
                       primary_level_id: str,
                       sequence_labels: Iterable[str]) -> str:
    """Deterministic id for a NEW scenario."""
    h = hashlib.sha256()
    h.update(pair.encode())
    h.update(b"\0")
    h.update(creation_bar_ts.encode())
    h.update(b"\0")
    h.update(primary_level_id.encode())
    h.update(b"\0")
    for lab in sequence_labels:
        h.update(str(lab).encode()); h.update(b",")
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------
# Row serialisation
# ---------------------------------------------------------------------

def row_to_dict(row: ScenarioRow) -> dict:
    d = {
        "scenario_id": row.scenario_id,
        "revision_idx": row.revision_idx,
        "created_at_utc": row.created_at_utc,
        "revised_at_utc": row.revised_at_utc,
        "bar_ts_utc": row.bar_ts_utc,
        "generated_at_utc": row.generated_at_utc,
        "agent": row.agent,
        "pair": row.pair,
        "state": row.state,
        "initial_interpretation": row.initial_interpretation,
        "current_interpretation": row.current_interpretation,
        "anticipated_sequence": [s.to_dict() for s in row.anticipated_sequence],
        "opportunities": [o.to_dict() for o in row.opportunities],
        "evidence": row.evidence.to_dict(),
        "economic_context": row.economic_context,
        "confirmation_criteria": list(row.confirmation_criteria),
        "change_from_previous": row.change_from_previous,
        "analogue_refs": list(row.analogue_refs),
        "source_model": row.source_model,
        "execution_authority": row.execution_authority,
        "schema_version": row.schema_version,
        "primary_hypothesis": row.primary_hypothesis,
        "primary_direction": row.primary_direction,
        "publication_decision": row.publication_decision,
        "trade_proposal": row.trade_proposal,
    }
    return d


def dict_to_row(d: dict) -> ScenarioRow:
    seq = [StructuralDestination(**{**x, "price": _coerce_float(x.get("price"))})
           for x in (d.get("anticipated_sequence") or [])]
    # Opportunity-level ``trade_proposal`` is a schema extension; the
    # dataclass does not store it as a field, so we strip the key here
    # (its contents are already carried on the row's top-level
    # ``trade_proposal`` block via apply_actions).
    _opp_fields = {f.name for f in dataclasses.fields(Opportunity)}
    ops = [Opportunity(**{k: v for k, v in x.items() if k in _opp_fields})
           for x in (d.get("opportunities") or [])]
    ev = EvidenceBundle(
        supporting=tuple((d.get("evidence") or {}).get("supporting") or []),
        contradicting=tuple((d.get("evidence") or {}).get("contradicting") or []),
        needed_info=tuple((d.get("evidence") or {}).get("needed_info") or []),
        invalidation_conditions=tuple((d.get("evidence") or {}).get("invalidation_conditions") or []),
    )
    return ScenarioRow(
        scenario_id=d["scenario_id"],
        revision_idx=int(d["revision_idx"]),
        created_at_utc=d["created_at_utc"],
        revised_at_utc=d["revised_at_utc"],
        bar_ts_utc=d["bar_ts_utc"],
        generated_at_utc=d.get("generated_at_utc", ""),
        agent=d["agent"],
        pair=d.get("pair", "GBPUSD"),
        state=d["state"],
        initial_interpretation=d["initial_interpretation"],
        current_interpretation=d.get("current_interpretation", d["initial_interpretation"]),
        anticipated_sequence=seq,
        opportunities=ops,
        evidence=ev,
        economic_context=d.get("economic_context") or {},
        confirmation_criteria=list(d.get("confirmation_criteria") or []),
        change_from_previous=d.get("change_from_previous", ""),
        analogue_refs=list(d.get("analogue_refs") or []),
        source_model=d.get("source_model", ""),
        execution_authority=d.get("execution_authority", "NONE"),
        schema_version=d.get("schema_version", "scenario.v1.0"),
        primary_hypothesis=d.get("primary_hypothesis", ""),
        primary_direction=d.get("primary_direction", ""),
        publication_decision=d.get("publication_decision") or {},
        trade_proposal=d.get("trade_proposal") or {},
    )


def _coerce_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# Append-only store
# ---------------------------------------------------------------------

class ScenarioStore:
    """Append-only JSONL store for scenario rows.

    Reads are stream-friendly (iter_rows / open_scenarios). The only
    write method is ``append_row`` and it refuses to:

      * accept a row whose scenario_id has a prior row with
        ``revised_at_utc`` strictly greater than this row's
        ``revised_at_utc`` (would simulate editing the past).
      * accept a revision_idx that duplicates an existing idx for the
        same scenario_id.
      * accept a state transition not in ALLOWED_TRANSITIONS from the
        latest state.
    """

    def __init__(self, path: pathlib.Path):
        self._path = pathlib.Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> pathlib.Path:
        return self._path

    def iter_rows(self) -> Iterable[ScenarioRow]:
        if not self._path.is_file():
            return
        with self._path.open(encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    yield dict_to_row(json.loads(ln))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

    def latest_by_id(self) -> dict[str, ScenarioRow]:
        latest: dict[str, ScenarioRow] = {}
        for r in self.iter_rows():
            prev = latest.get(r.scenario_id)
            if prev is None or r.revision_idx > prev.revision_idx:
                latest[r.scenario_id] = r
        return latest

    def open_scenarios(self) -> list[ScenarioRow]:
        return [r for r in self.latest_by_id().values()
                if r.state not in TERMINAL_STATES]

    def append_row(self, row: ScenarioRow) -> None:
        self._validate(row)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row_to_dict(row), sort_keys=True, default=str) + "\n")

    def _validate(self, row: ScenarioRow) -> None:
        if row.state not in VALID_STATES:
            raise ValueError(f"invalid state {row.state!r}")
        if row.execution_authority != "NONE":
            raise ValueError(
                "execution_authority must be 'NONE' on every scenario row")
        parse_utc(row.created_at_utc) or (_ := None)
        parse_utc(row.revised_at_utc) or (_ := None)
        parse_utc(row.bar_ts_utc) or (_ := None)
        if parse_utc(row.revised_at_utc) < parse_utc(row.created_at_utc):
            raise ValueError("revised_at_utc < created_at_utc (lookahead)")
        if parse_utc(row.bar_ts_utc) < parse_utc(row.created_at_utc):
            raise ValueError("bar_ts_utc < created_at_utc (lookahead)")

        latest = self.latest_by_id().get(row.scenario_id)
        if latest is None:
            if row.revision_idx != 0:
                raise ValueError(
                    f"creation row must have revision_idx=0, got {row.revision_idx}")
            return
        if row.revision_idx <= latest.revision_idx:
            raise ValueError(
                f"revision_idx {row.revision_idx} does not strictly exceed "
                f"existing {latest.revision_idx} for scenario {row.scenario_id}")
        if parse_utc(row.revised_at_utc) < parse_utc(latest.revised_at_utc):
            raise ValueError(
                f"revision revised_at_utc {row.revised_at_utc} precedes "
                f"existing {latest.revised_at_utc} (lookahead)")
        if row.state not in ALLOWED_TRANSITIONS.get(latest.state, set()):
            raise ValueError(
                f"disallowed transition {latest.state} -> {row.state}")
        # Immutable fields carried forward verbatim.
        if row.scenario_id != latest.scenario_id:
            raise ValueError("scenario_id mismatch on revision")
        if row.created_at_utc != latest.created_at_utc:
            raise ValueError("created_at_utc must be stable across revisions")
        if row.initial_interpretation != latest.initial_interpretation:
            raise ValueError(
                "initial_interpretation must be stable across revisions")

    # Helper: create and append a new scenario in one step.
    def propose(self, *,
                pair: str,
                bar_ts_utc: str,
                agent: str,
                primary_level_id: str,
                initial_interpretation: str,
                anticipated_sequence: list[StructuralDestination],
                opportunities: list[Opportunity],
                evidence: EvidenceBundle,
                economic_context: dict,
                confirmation_criteria: list[str],
                change_from_previous: str,
                analogue_refs: list[dict] | None = None,
                source_model: str = "",
                initial_state: str = "PROPOSED",
                generated_at_utc: str = "",
                primary_hypothesis: str = "",
                primary_direction: str = "",
                publication_decision: dict | None = None,
                trade_proposal: dict | None = None) -> ScenarioRow:
        if initial_state not in {"PROPOSED", "WATCHING"}:
            raise ValueError(
                "initial_state must be PROPOSED or WATCHING (not "
                f"{initial_state!r})")
        scenario_id = derive_scenario_id(
            pair=pair,
            creation_bar_ts=bar_ts_utc,
            primary_level_id=primary_level_id,
            sequence_labels=[d.label for d in anticipated_sequence],
        )
        row = ScenarioRow(
            scenario_id=scenario_id,
            revision_idx=0,
            created_at_utc=bar_ts_utc,
            revised_at_utc=bar_ts_utc,
            bar_ts_utc=bar_ts_utc,
            agent=agent,
            pair=pair,
            state=initial_state,
            initial_interpretation=initial_interpretation,
            current_interpretation=initial_interpretation,
            anticipated_sequence=anticipated_sequence,
            opportunities=opportunities,
            evidence=evidence,
            economic_context=economic_context,
            confirmation_criteria=confirmation_criteria,
            change_from_previous=change_from_previous,
            analogue_refs=analogue_refs or [],
            source_model=source_model,
            execution_authority="NONE",
            schema_version="scenario.v1.0",
            generated_at_utc=generated_at_utc,
            primary_hypothesis=primary_hypothesis,
            primary_direction=primary_direction,
            publication_decision=publication_decision or {},
            trade_proposal=trade_proposal or {},
        )
        self.append_row(row)
        return row

    def revise(self, *,
               scenario_id: str,
               bar_ts_utc: str,
               agent: str,
               new_state: str,
               current_interpretation: str | None = None,
               anticipated_sequence: list[StructuralDestination] | None = None,
               opportunities: list[Opportunity] | None = None,
               evidence: EvidenceBundle | None = None,
               economic_context: dict | None = None,
               confirmation_criteria: list[str] | None = None,
               change_from_previous: str = "",
               analogue_refs: list[dict] | None = None,
               source_model: str = "",
               generated_at_utc: str = "",
               primary_hypothesis: str = "",
               primary_direction: str = "",
               publication_decision: dict | None = None,
               trade_proposal: dict | None = None) -> ScenarioRow:
        latest = self.latest_by_id().get(scenario_id)
        if latest is None:
            raise ValueError(f"no scenario with id {scenario_id!r}")
        row = ScenarioRow(
            scenario_id=scenario_id,
            revision_idx=latest.revision_idx + 1,
            created_at_utc=latest.created_at_utc,
            revised_at_utc=bar_ts_utc,
            bar_ts_utc=bar_ts_utc,
            agent=agent,
            pair=latest.pair,
            state=new_state,
            initial_interpretation=latest.initial_interpretation,
            current_interpretation=current_interpretation or latest.current_interpretation,
            anticipated_sequence=anticipated_sequence or latest.anticipated_sequence,
            opportunities=opportunities if opportunities is not None else latest.opportunities,
            evidence=evidence or latest.evidence,
            economic_context=economic_context if economic_context is not None else latest.economic_context,
            confirmation_criteria=confirmation_criteria if confirmation_criteria is not None else latest.confirmation_criteria,
            change_from_previous=change_from_previous,
            analogue_refs=analogue_refs if analogue_refs is not None else latest.analogue_refs,
            source_model=source_model or latest.source_model,
            execution_authority="NONE",
            schema_version="scenario.v1.0",
            generated_at_utc=generated_at_utc,
            primary_hypothesis=primary_hypothesis or latest.primary_hypothesis,
            primary_direction=primary_direction or latest.primary_direction,
            publication_decision=publication_decision or {},
            trade_proposal=trade_proposal if trade_proposal is not None
                              else latest.trade_proposal,
        )
        self.append_row(row)
        return row


# ---------------------------------------------------------------------
# Economic-context helper
# ---------------------------------------------------------------------

def classify_economic_context(macro_packet: dict) -> dict:
    """Split a macro packet into scheduled/released/expired/unverified
    buckets + a surprises list derived only from RELEASED events.

    Four buckets correspond to the authoritative event states:
      scheduled  — status=UPCOMING (future catalyst with no suspected
                   stale-duplicate sibling).
      released   — status=RELEASED (release_at_utc <= asof AND actual
                   value present).
      expired    — status=EXPIRED (release_at_utc <= asof BUT no actual
                   value — the catalyst fired but we have no numeric
                   reading; the AI must not pretend to anticipate it).
      unverified — status=UNVERIFIED (a sibling (currency,name) was
                   RELEASED within the trailing stale-duplicate
                   window; the UPCOMING entry is likely a Finnhub
                   duplicate — DO NOT anticipate as a second release).

    Reused by the scenario prompt so the LLM never has to distinguish
    these states from raw text; the module does it from the macro
    adapter's explicit fields.
    """
    events = (macro_packet or {}).get("events") or []
    scheduled: list[dict] = []
    released: list[dict] = []
    expired: list[dict] = []
    unverified: list[dict] = []
    surprises: list[dict] = []
    for e in events:
        status = (e.get("status") or "").upper()
        if status == "RELEASED":
            released.append(e)
            try:
                actual = e.get("actual_value") if "actual_value" in e else e.get("actual")
                forecast = e.get("forecast") if e.get("forecast") is not None else e.get("consensus")
                if actual is not None and forecast is not None:
                    surprises.append({
                        "event_id": e.get("event_id"),
                        "name": e.get("name"),
                        "currency": e.get("currency"),
                        "actual": actual,
                        "forecast": forecast,
                        "surprise_abs": float(actual) - float(forecast),
                        "surprise_direction": (
                            "HIGHER_THAN_FORECAST" if float(actual) > float(forecast)
                            else "LOWER_THAN_FORECAST" if float(actual) < float(forecast)
                            else "AT_FORECAST"),
                    })
            except (TypeError, ValueError):
                pass
        elif status == "EXPIRED":
            expired.append(e)
        elif status == "UNVERIFIED":
            unverified.append(e)
        else:
            # Any residual value (including the historical "UPCOMING" and
            # anything the adapter hasn't tagged) stays in scheduled.
            scheduled.append(e)
    return {
        "asof_utc": (macro_packet or {}).get("asof_utc"),
        "status": (macro_packet or {}).get("status"),
        "scheduled": scheduled,
        "released": released,
        "expired": expired,
        "unverified": unverified,
        "surprises": surprises,
    }


__all__ = [
    "VALID_STATES", "TERMINAL_STATES", "ALLOWED_TRANSITIONS",
    "StructuralDestination", "Opportunity", "EvidenceBundle",
    "ScenarioRow", "ScenarioStore",
    "derive_scenario_id", "row_to_dict", "dict_to_row",
    "classify_economic_context",
]
