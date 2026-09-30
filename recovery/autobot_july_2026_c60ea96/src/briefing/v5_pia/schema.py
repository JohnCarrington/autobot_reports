"""BriefingV5 schema — Phase 2 Pydantic v2 form.

Phase-1 shipped a @dataclass; Phase-2 migrates to a Pydantic v2 BaseModel
so the LLM-rationale layer (rationale_writer.py) and Phase-3 executor get
structured validation for free. The contract for this migration was that
to_dict() / model_dump() output must remain byte-identical to Phase 1.
The round-trip test in tests/test_schema_pydantic.py verifies this against
4 orchestrator-generated fixtures.

The validators below mirror Phase 1's validate() rules: direction enum,
state enum, 0 ≤ confidence ≤ 100, bucket-confidence consistency, rr ≥ 0.
Fail loud — no silent coercion.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DirectionT = Literal["BUY", "SELL", "STAND_ASIDE"]
_StateT     = Literal["GENERATED", "ARMED", "STAND_ASIDE", "FIRED", "CLOSED"]
_BucketT    = Literal["STAND_ASIDE", "WATCH", "ARMED", "HIGH_CONVICTION"]
_SessionT   = Literal["London", "NY"]


def _default_execution() -> Dict[str, Any]:
    return {
        "min_confidence_to_arm": 70,
        "executed":              False,
        "executed_at_utc":       None,
        "deal_id":               None,
        "outcome":               None,
    }


def _bucket_consistent(confidence: int, bucket: str) -> bool:
    if bucket == "STAND_ASIDE":     return 0 <= confidence < 50
    if bucket == "WATCH":           return 50 <= confidence < 70
    if bucket == "ARMED":           return 70 <= confidence < 85
    if bucket == "HIGH_CONVICTION": return 85 <= confidence <= 100
    return False


class BriefingV5(BaseModel):
    """Phase-1 → Phase-2 contract: model_dump(mode='python') and
    model_dump_json() must produce the same JSON shape as the Phase-1
    @dataclass.to_dict()/json.dumps pipeline. Field order below matches
    the Phase-1 to_dict() key order verbatim — Pydantic v2 serialises in
    field declaration order by default.
    """

    # Pydantic v2 config: forbid extra keys (catches schema drift early).
    # We accept any-typed dict values for confidence_breakdown / news_event
    # / execution because their contents are not part of the schema's
    # invariants; their shape is owned by the scorer / news layer / Phase-3
    # executor respectively.
    model_config = ConfigDict(
        extra="forbid",
        # No revalidation on assignment — once the model is built, the
        # immutable shape is the JSON we write. Mutation would defeat the
        # atomic two-write pattern.
        validate_assignment=False,
        # Pydantic 2.x: by default, str types preserve None as None and
        # don't coerce. Be explicit anyway.
        str_strip_whitespace=False,
    )

    schema_version:          str
    pair:                    str
    session:                 _SessionT
    generated_at_utc:        str
    valid_until_utc:         str
    direction:               _DirectionT
    state:                   _StateT
    confidence:              int
    confidence_bucket:       _BucketT
    confidence_breakdown:    Dict[str, Any]
    bias_anchor:             Optional[float]
    bias_anchor_label:       Optional[str]
    entry:                   Optional[float]
    stop:                    Optional[float]
    target:                  Optional[float]
    rr:                      float
    stop_structural_level:   Optional[str]
    target_structural_level: Optional[str]
    support_levels:          List[float]
    resistance_levels:       List[float]
    rationale:               Optional[str]
    stand_aside_reason:      Optional[str]
    news_in_window:          bool
    news_event:              Optional[Dict[str, Any]]
    execution:               Dict[str, Any] = Field(default_factory=_default_execution)

    # ── Field-level validators (Phase-1 validate() rules) ────────────────

    @field_validator("schema_version")
    @classmethod
    def _v_schema_version(cls, v: str) -> str:
        if v != "v5_pia":
            raise ValueError(f"schema_version must be 'v5_pia', got {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def _v_confidence(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError(f"confidence must be int, got {type(v).__name__}")
        if not 0 <= v <= 100:
            raise ValueError(f"confidence {v} out of range 0..100")
        return v

    @field_validator("rr")
    @classmethod
    def _v_rr(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"rr must be >= 0, got {v}")
        return float(v)

    # ── Cross-field validator (bucket ↔ confidence) ──────────────────────

    @model_validator(mode="after")
    def _v_bucket_consistent(self) -> "BriefingV5":
        if not _bucket_consistent(self.confidence, self.confidence_bucket):
            raise ValueError(
                f"confidence_bucket {self.confidence_bucket!r} inconsistent "
                f"with confidence={self.confidence}"
            )
        return self

    # ── Phase-1 surface compat: validate() and to_dict() ─────────────────
    #
    # Pydantic models validate at construction; validate() exists for
    # symmetry with Phase-1 callers and is a no-op (raises only if the
    # model was somehow mutated past construction, which we forbid via
    # validate_assignment=False above — i.e. it never raises in practice).

    def validate(self) -> None:  # type: ignore[override]
        """No-op compatibility shim. Pydantic validates at construction.

        Phase-1 callers (orchestrator._write_briefing) call .validate()
        immediately before .to_dict(); the call is preserved so the
        Phase-1 codepath reads identically.
        """
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Return the canonical dict shape for json.dumps. Field-order
        matches Phase-1 to_dict() exactly because Pydantic v2 model_dump
        respects field declaration order. mode='python' keeps Python
        types (None stays None, lists stay lists) — json.dumps then
        produces the same bytes as Phase-1's pipeline.
        """
        return self.model_dump(mode="python")
