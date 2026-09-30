"""Tests for IG-authoritative allowance capture on the historical-prices
fetch path.

Two hosts share IG account REDACTED_IG_ACCT's 10k weekly pool but neither can see
the other's spend. The observation change (2026-07-23) reads
allowance.remainingAllowance / totalAllowance / allowanceExpiry from every
successful REST response, logs them at INFO and persists them alongside
the local budget counter. It must NOT change budget gating or fetch
behaviour.

These tests pin:
  1. A well-formed allowance block persists all four fields.
  2. A malformed / missing allowance block persists nothing and does not
     raise — a fetch must never fail because the allowance was odd-shaped.
  3. consume() / remaining() byte-identical to before the change: same
     return values AND same on-disk JSON structure for the counter fields.

The live /opt/tradingbot/cache/rest_allowance.json is never touched;
ALLOWANCE_FILE is redirected to a tmp path and md5 verified before/after.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest


LIVE_STATE_FILE = "/opt/tradingbot/cache/rest_allowance.json"


def _md5(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


@pytest.fixture
def isolated_allowance(tmp_path, monkeypatch):
    """Reload rest_allowance with ALLOWANCE_FILE pointed at tmp_path so the
    live cache file is never touched. Also asserts the live file is
    byte-identical after the test.
    """
    live_md5_before = _md5(LIVE_STATE_FILE) if os.path.exists(LIVE_STATE_FILE) else None

    tmp_file = tmp_path / "rest_allowance.json"
    monkeypatch.setenv("REST_ALLOWANCE_FILE", str(tmp_file))

    import rest_allowance
    importlib.reload(rest_allowance)
    assert rest_allowance.ALLOWANCE_FILE == str(tmp_file)

    yield rest_allowance, tmp_file

    # Reload again to restore the module for other tests, back to whatever
    # REST_ALLOWANCE_FILE resolves to after monkeypatch undo.
    importlib.reload(rest_allowance)

    if live_md5_before is not None:
        assert _md5(LIVE_STATE_FILE) == live_md5_before, (
            "live cache/rest_allowance.json was modified during the test"
        )


def _read_json(path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# (a) well-formed allowance persists all four fields
# ---------------------------------------------------------------------------
def test_persist_ig_allowance_writes_all_four_fields(isolated_allowance):
    ra, tmp_file = isolated_allowance

    ok = ra.persist_ig_allowance(
        remaining=9318,
        total=10000,
        expiry_s=604796,
        observed_at=1_753_000_000,
    )
    assert ok is True

    state = _read_json(tmp_file)
    assert state["ig_allowance_remaining"] == 9318
    assert state["ig_allowance_total"] == 10000
    assert state["ig_allowance_expiry_s"] == 604796
    assert state["ig_allowance_observed_at"] == 1_753_000_000


def test_persist_ig_allowance_defaults_observed_at_to_now(isolated_allowance, monkeypatch):
    ra, tmp_file = isolated_allowance

    # Freeze time so we can assert the fallback branch precisely.
    monkeypatch.setattr(ra.time, "time", lambda: 1_753_111_111.5)
    ok = ra.persist_ig_allowance(9000, 10000, 500000)
    assert ok is True

    state = _read_json(tmp_file)
    assert state["ig_allowance_observed_at"] == 1_753_111_111


# ---------------------------------------------------------------------------
# (b) malformed / missing block persists nothing and does not raise
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "remaining,total,expiry_s",
    [
        (None, 10000, 604796),           # missing remaining
        (9318, None, 604796),            # missing total
        (9318, 10000, None),             # missing expiry
        ("9318", 10000, 604796),         # string coercible - should still work
        ("abc", 10000, 604796),          # string non-coercible - reject
        (9318, "xyz", 604796),           # string non-coercible - reject
        (9318, 10000, "not-a-number"),   # string non-coercible - reject
        (-1, 10000, 604796),             # negative - reject
        (9318, -1, 604796),              # negative - reject
        (9318, 10000, -1),               # negative - reject
    ],
)
def test_persist_ig_allowance_rejects_malformed(
    isolated_allowance, remaining, total, expiry_s
):
    ra, tmp_file = isolated_allowance

    # Seed a normal consume() state first so we can prove nothing was written.
    ra.consume(100)
    md5_before = _md5(tmp_file)

    # The only case in the parametrize list that SHOULD succeed is the
    # ("9318", 10000, 604796) row — int("9318") is a valid coercion.
    if remaining == "9318":
        ok = ra.persist_ig_allowance(remaining, total, expiry_s)
        assert ok is True
        state = _read_json(tmp_file)
        assert state["ig_allowance_remaining"] == 9318
        return

    ok = ra.persist_ig_allowance(remaining, total, expiry_s)
    assert ok is False
    assert _md5(tmp_file) == md5_before, (
        "persist_ig_allowance modified state despite malformed input"
    )
    state = _read_json(tmp_file)
    assert "ig_allowance_remaining" not in state
    assert "ig_allowance_total" not in state
    assert "ig_allowance_expiry_s" not in state
    assert "ig_allowance_observed_at" not in state


def test_persist_ig_allowance_never_raises_on_junk(isolated_allowance):
    ra, _tmp_file = isolated_allowance

    # object() is neither int-coercible nor sensible; must return False, not raise.
    for junk in (object(), {"nested": "dict"}, [1, 2, 3], b"bytes"):
        assert ra.persist_ig_allowance(junk, 10000, 604796) is False
        assert ra.persist_ig_allowance(9318, junk, 604796) is False
        assert ra.persist_ig_allowance(9318, 10000, junk) is False


# ---------------------------------------------------------------------------
# (c) consume()/remaining() byte-identical to pre-change behaviour
# ---------------------------------------------------------------------------
def test_consume_return_value_and_state_unchanged(isolated_allowance):
    """consume() must charge exactly `points` against points_used, return
    True/False on the same threshold, and leave the same counter keys on
    disk. This is the byte-identical assertion the spec calls for.
    """
    ra, tmp_file = isolated_allowance

    # Fresh state — no file yet.
    assert not tmp_file.exists() or _read_json(tmp_file) == {}, "unexpected pre-state"

    # A consume() call should create the file with only counter keys.
    assert ra.consume(500) is True
    state = _read_json(tmp_file)
    assert set(state.keys()) == {"week_start", "points_used", "points_budget"}
    assert state["points_used"] == 500

    # Second consume adds up.
    assert ra.consume(1500) is True
    state = _read_json(tmp_file)
    assert state["points_used"] == 2000

    # Budget rejection at boundary.
    budget = state["points_budget"]
    over_by_one = (budget - 2000) + 1
    assert ra.consume(over_by_one) is False
    # Rejection must NOT change points_used.
    state = _read_json(tmp_file)
    assert state["points_used"] == 2000


def test_remaining_return_value_unchanged(isolated_allowance):
    ra, _tmp_file = isolated_allowance

    assert ra.consume(1234) is True
    r1 = ra.remaining()
    # Now persist IG allowance and re-check — remaining() must be the same.
    assert ra.persist_ig_allowance(9318, 10000, 604796) is True
    r2 = ra.remaining()
    assert r1 == r2, "IG allowance persist changed local remaining() output"


def test_persist_preserves_counter_fields_and_does_not_bump_used(isolated_allowance):
    """Persisting IG allowance must not modify points_used, points_budget or
    week_start.
    """
    ra, tmp_file = isolated_allowance

    ra.consume(750)
    before = _read_json(tmp_file)

    ra.persist_ig_allowance(9200, 10000, 500000, observed_at=1_753_222_222)
    after = _read_json(tmp_file)

    assert after["week_start"] == before["week_start"]
    assert after["points_used"] == before["points_used"] == 750
    assert after["points_budget"] == before["points_budget"]
    # And the new fields showed up.
    assert after["ig_allowance_remaining"] == 9200
    assert after["ig_allowance_total"] == 10000
    assert after["ig_allowance_expiry_s"] == 500000
    assert after["ig_allowance_observed_at"] == 1_753_222_222


def test_consume_after_persist_still_atomic(isolated_allowance):
    """After IG allowance fields exist in the state file, consume() must
    still atomically charge points_used without disturbing the IG fields.
    """
    ra, tmp_file = isolated_allowance

    ra.persist_ig_allowance(9318, 10000, 604796, observed_at=1_753_000_000)
    before = _read_json(tmp_file)

    assert ra.consume(400) is True
    after = _read_json(tmp_file)

    assert after["points_used"] == before.get("points_used", 0) + 400
    # IG fields untouched.
    assert after["ig_allowance_remaining"] == 9318
    assert after["ig_allowance_total"] == 10000
    assert after["ig_allowance_expiry_s"] == 604796
    assert after["ig_allowance_observed_at"] == 1_753_000_000
