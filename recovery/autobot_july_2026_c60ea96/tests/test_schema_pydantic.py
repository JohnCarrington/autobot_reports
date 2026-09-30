"""Phase-2 schema tests: Pydantic round-trip + validator failures.

Round-trip test: load each fixture in tests/fixtures/v5_pia/, parse via
Pydantic BriefingV5, re-serialise via to_dict() + json.dumps, and compare
byte-by-byte against a normalised version of the original. Normalisation
matches the orchestrator's write contract (json.dumps(..., indent=2,
default=str)).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from briefing.v5_pia.schema import BriefingV5  # noqa: E402

FIXTURES = sorted((ROOT / "tests" / "fixtures" / "v5_pia").glob("*.json"))


def _normalise(raw: str) -> str:
    """Re-serialise a JSON string the same way the orchestrator writes
    it. Catches incidental formatting differences that aren't part of
    the contract (whitespace, key reordering by editors, etc.).
    """
    return json.dumps(json.loads(raw), indent=2, default=str)


def _example_briefing_kwargs() -> dict:
    """Minimal valid kwargs for an ARMED briefing — used by validator tests."""
    return {
        "schema_version":          "v5_pia",
        "pair":                    "GBPUSD",
        "session":                 "London",
        "generated_at_utc":        "2026-05-05T05:30:00Z",
        "valid_until_utc":         "2026-05-05T12:30:00Z",
        "direction":               "BUY",
        "state":                   "ARMED",
        "confidence":              75,
        "confidence_bucket":       "ARMED",
        "confidence_breakdown":    {"awards": {}},
        "bias_anchor":             13540.0,
        "bias_anchor_label":       "H4_EMA20",
        "entry":                   13540.5,
        "stop":                    13535.5,
        "target":                  13571.0,
        "rr":                      4.69,
        "stop_structural_level":   "swing_low",
        "target_structural_level": "swing_high",
        "support_levels":          [13520.0],
        "resistance_levels":       [13580.0],
        "rationale":               None,
        "stand_aside_reason":      None,
        "news_in_window":          False,
        "news_event":              None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Round-trip: byte-identical against orchestrator-generated fixtures
# ─────────────────────────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_at_least_4_fixtures(self):
        # If this fails, run scripts/gen_v5_fixtures.py first.
        assert len(FIXTURES) >= 4, (
            f"expected ≥4 fixtures in tests/fixtures/v5_pia/, got {len(FIXTURES)}"
        )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
    def test_byte_identical_round_trip(self, fixture):
        original = fixture.read_text()
        # Normalise the fixture once so we're comparing apples to apples
        # (the orchestrator wrote it with json.dumps(..., indent=2)).
        normalised_original = _normalise(original)

        # Parse via Pydantic, then re-serialise the same way the orchestrator does.
        model = BriefingV5(**json.loads(original))
        round_tripped = json.dumps(model.to_dict(), indent=2, default=str)

        assert round_tripped == normalised_original, (
            f"round-trip mismatch for {fixture.name}\n"
            f"--- original (normalised) ---\n{normalised_original[:500]}\n"
            f"--- round-tripped ---\n{round_tripped[:500]}"
        )

    @pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
    def test_field_order_unchanged(self, fixture):
        """The Phase-1 to_dict() pinned a specific key order; the
        Pydantic field declaration order must reproduce it exactly.
        """
        original_keys = list(json.loads(fixture.read_text()).keys())
        model = BriefingV5(**json.loads(fixture.read_text()))
        round_tripped_keys = list(model.to_dict().keys())
        assert round_tripped_keys == original_keys


# ─────────────────────────────────────────────────────────────────────────────
# Validator failures — each rule must reject invalid input
# ─────────────────────────────────────────────────────────────────────────────

class TestValidators:
    def test_valid_baseline(self):
        # Baseline must construct without error.
        BriefingV5(**_example_briefing_kwargs())

    def test_invalid_schema_version(self):
        kw = _example_briefing_kwargs()
        kw["schema_version"] = "v4_legacy"
        with pytest.raises(ValueError, match="schema_version must be 'v5_pia'"):
            BriefingV5(**kw)

    def test_invalid_direction(self):
        kw = _example_briefing_kwargs()
        kw["direction"] = "FOO"
        with pytest.raises(ValueError):
            BriefingV5(**kw)

    def test_invalid_state(self):
        kw = _example_briefing_kwargs()
        kw["state"] = "DELETED"
        with pytest.raises(ValueError):
            BriefingV5(**kw)

    def test_invalid_session(self):
        kw = _example_briefing_kwargs()
        kw["session"] = "Asian"
        with pytest.raises(ValueError):
            BriefingV5(**kw)

    @pytest.mark.parametrize("conf", [-1, 101, 200, -50])
    def test_confidence_out_of_range(self, conf):
        kw = _example_briefing_kwargs()
        kw["confidence"] = conf
        # bucket also has to be valid; force it to a band the conf
        # could plausibly fall into so we test the range rule, not the
        # cross-field rule.
        kw["confidence_bucket"] = "ARMED"
        with pytest.raises(ValueError):
            BriefingV5(**kw)

    def test_confidence_must_be_int(self):
        kw = _example_briefing_kwargs()
        kw["confidence"] = 75.5
        with pytest.raises(ValueError):
            BriefingV5(**kw)

    def test_invalid_bucket(self):
        kw = _example_briefing_kwargs()
        kw["confidence_bucket"] = "MAX_PAIN"
        with pytest.raises(ValueError):
            BriefingV5(**kw)

    @pytest.mark.parametrize("conf,bucket", [
        (30, "ARMED"),               # 30 is STAND_ASIDE band
        (50, "STAND_ASIDE"),         # 50 is WATCH band
        (70, "WATCH"),               # 70 is ARMED band
        (90, "WATCH"),               # 90 is HIGH_CONVICTION band
        (100, "STAND_ASIDE"),
    ])
    def test_bucket_inconsistent_with_confidence(self, conf, bucket):
        kw = _example_briefing_kwargs()
        kw["confidence"] = conf
        kw["confidence_bucket"] = bucket
        with pytest.raises(ValueError, match="inconsistent"):
            BriefingV5(**kw)

    @pytest.mark.parametrize("conf,bucket", [
        (0,   "STAND_ASIDE"),
        (49,  "STAND_ASIDE"),
        (50,  "WATCH"),
        (69,  "WATCH"),
        (70,  "ARMED"),
        (84,  "ARMED"),
        (85,  "HIGH_CONVICTION"),
        (100, "HIGH_CONVICTION"),
    ])
    def test_bucket_consistent_with_confidence(self, conf, bucket):
        kw = _example_briefing_kwargs()
        kw["confidence"] = conf
        kw["confidence_bucket"] = bucket
        BriefingV5(**kw)  # should not raise

    def test_negative_rr_rejected(self):
        kw = _example_briefing_kwargs()
        kw["rr"] = -0.5
        with pytest.raises(ValueError, match="rr must be >= 0"):
            BriefingV5(**kw)

    def test_extra_field_rejected(self):
        kw = _example_briefing_kwargs()
        kw["extra_field"] = "should_not_be_here"
        with pytest.raises(ValueError):
            BriefingV5(**kw)


# ─────────────────────────────────────────────────────────────────────────────
# Phase-1 surface compat
# ─────────────────────────────────────────────────────────────────────────────

class TestPhase1Compat:
    def test_validate_is_noop(self):
        b = BriefingV5(**_example_briefing_kwargs())
        # Phase-1 callers (orchestrator._write_briefing) call this before
        # writing. Pydantic already validated at construction; .validate()
        # exists for symmetry and must not raise on a valid model.
        b.validate()

    def test_to_dict_returns_dict(self):
        b = BriefingV5(**_example_briefing_kwargs())
        d = b.to_dict()
        assert isinstance(d, dict)
        assert d["schema_version"] == "v5_pia"
        assert "execution" in d
