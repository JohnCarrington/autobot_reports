"""Unit tests for the briefing expires_at parser, in both the validator
(scripts/validate_briefing.py) and the executor (briefing_execution.py).

Both must accept the HH:MM[Z] wall-clock form the LLM produces (e.g.
'11:30Z', '17:45Z'), interpreted as today UTC at that wall-clock time,
in addition to the existing 'end_of_day' sentinel and full ISO-8601.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_validator_module():
    """Import scripts/validate_briefing.py as a module without running main()."""
    path = REPO_ROOT / "scripts" / "validate_briefing.py"
    spec = importlib.util.spec_from_file_location("validate_briefing", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_briefing"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def validator():
    return _load_validator_module()


@pytest.fixture(scope="module")
def briefing_execution():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import briefing_execution as be
    return be


# ============================================================
# _validate_plan_expires_at — returns None on valid, error str on invalid
# ============================================================
class TestValidatorExpiresAt:

    def test_whitelisted_12_30z(self, validator):
        assert validator._validate_plan_expires_at("12:30Z") is None

    def test_hhmm_z_17_45(self, validator):
        assert validator._validate_plan_expires_at("17:45Z") is None

    def test_hhmm_z_11_30(self, validator):
        assert validator._validate_plan_expires_at("11:30Z") is None

    def test_hhmm_z_12_00(self, validator):
        assert validator._validate_plan_expires_at("12:00Z") is None

    def test_hhmm_no_z_suffix(self, validator):
        assert validator._validate_plan_expires_at("09:15") is None

    def test_end_of_day(self, validator):
        assert validator._validate_plan_expires_at("end_of_day") is None

    def test_full_iso8601_z(self, validator):
        assert validator._validate_plan_expires_at("2026-04-29T17:45:00Z") is None

    def test_full_iso8601_offset(self, validator):
        assert validator._validate_plan_expires_at("2026-04-29T17:45:00+00:00") is None

    def test_garbage_string(self, validator):
        err = validator._validate_plan_expires_at("abc")
        assert err is not None and "unrecognized" in err

    def test_empty_string(self, validator):
        err = validator._validate_plan_expires_at("")
        assert err is not None and "unrecognized" in err

    def test_missing_none(self, validator):
        assert validator._validate_plan_expires_at(None) == "missing"

    def test_non_string(self, validator):
        err = validator._validate_plan_expires_at(1745)
        assert err is not None and "non-string" in err

    def test_invalid_hour(self, validator):
        # 25:00 is not a valid wall-clock time, must fall through and fail
        err = validator._validate_plan_expires_at("25:00Z")
        assert err is not None and "unrecognized" in err

    def test_invalid_minute(self, validator):
        err = validator._validate_plan_expires_at("12:60Z")
        assert err is not None and "unrecognized" in err


# ============================================================
# _plan_expired — returns bool, reads plan['expires_at']
# ============================================================
class TestExecutorPlanExpired:

    def test_no_expires_at_never_expires(self, briefing_execution):
        now = datetime(2026, 4, 29, 23, 0, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({}, now) is False

    def test_end_of_day_before_2100(self, briefing_execution):
        now = datetime(2026, 4, 29, 20, 59, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "end_of_day"}, now) is False

    def test_end_of_day_at_2100(self, briefing_execution):
        now = datetime(2026, 4, 29, 21, 0, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "end_of_day"}, now) is True

    def test_12_30z_before(self, briefing_execution):
        now = datetime(2026, 4, 29, 12, 29, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "12:30Z"}, now) is False

    def test_12_30z_at(self, briefing_execution):
        now = datetime(2026, 4, 29, 12, 30, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "12:30Z"}, now) is True

    def test_17_45z_before(self, briefing_execution):
        now = datetime(2026, 4, 29, 17, 44, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "17:45Z"}, now) is False

    def test_17_45z_at(self, briefing_execution):
        now = datetime(2026, 4, 29, 17, 45, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "17:45Z"}, now) is True

    def test_17_45z_after(self, briefing_execution):
        now = datetime(2026, 4, 29, 18, 0, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "17:45Z"}, now) is True

    def test_11_30z_at(self, briefing_execution):
        now = datetime(2026, 4, 29, 11, 30, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "11:30Z"}, now) is True

    def test_12_00z_before(self, briefing_execution):
        now = datetime(2026, 4, 29, 11, 59, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "12:00Z"}, now) is False

    def test_12_00z_at(self, briefing_execution):
        now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "12:00Z"}, now) is True

    def test_hhmm_no_z_suffix(self, briefing_execution):
        now = datetime(2026, 4, 29, 9, 15, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "09:15"}, now) is True

    def test_full_iso8601_before(self, briefing_execution):
        now = datetime(2026, 4, 29, 16, 0, tzinfo=timezone.utc)
        plan = {"expires_at": "2026-04-29T17:45:00Z"}
        assert briefing_execution._plan_expired(plan, now) is False

    def test_full_iso8601_after(self, briefing_execution):
        now = datetime(2026, 4, 29, 18, 0, tzinfo=timezone.utc)
        plan = {"expires_at": "2026-04-29T17:45:00Z"}
        assert briefing_execution._plan_expired(plan, now) is True

    def test_garbage_treated_as_never_expiring(self, briefing_execution, caplog):
        now = datetime(2026, 4, 29, 23, 0, tzinfo=timezone.utc)
        with caplog.at_level("WARNING"):
            assert briefing_execution._plan_expired({"expires_at": "abc"}, now) is False
        assert any("unparseable expires_at" in r.message for r in caplog.records)

    def test_empty_string_never_expires(self, briefing_execution):
        # Empty string is falsy → short-circuit "no expires_at" path.
        now = datetime(2026, 4, 29, 23, 0, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": ""}, now) is False

    def test_invalid_hour_falls_through(self, briefing_execution):
        # "25:00Z" isn't a valid wall-clock OR ISO-8601; logged + never-expiring.
        now = datetime(2026, 4, 29, 23, 0, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "25:00Z"}, now) is False

    def test_date_boundary_uses_now_utc_date(self, briefing_execution):
        # '17:45Z' on 2026-04-30 must be evaluated against 2026-04-30, not 04-29.
        now = datetime(2026, 4, 30, 17, 46, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "17:45Z"}, now) is True
        now_before = datetime(2026, 4, 30, 17, 44, tzinfo=timezone.utc)
        assert briefing_execution._plan_expired({"expires_at": "17:45Z"}, now_before) is False
