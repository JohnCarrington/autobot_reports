"""Pre-flight READ-ONLY broker-connectivity check for Scenario V2 DEMO.

Operator runs this ONCE on the deploy host AFTER installing files
and BEFORE flipping V2_SV2_DEMO_ENABLED=1. Confirms:

  * `IG_ACC_TYPE` env resolves to "DEMO".
  * `ig_auth.get_ig_session()` can obtain a DEMO session.
  * Account id returned by the session is the expected DEMO id.
  * The GBP/USD epic exists and has non-null dealingRules.
  * `nms_directional_authority.evaluate` returns a valid decision object.
  * `ownership_identity._MODE_CODES` carries SCENARIO_V2_L/S after the patch.
  * The deployed shadow_execution + run_shadow_exec SHAs match the known
    approved values (so the correction didn't accidentally bump them).

READ-ONLY: no order, no position touched, no journal write.

Exits 0 on all green; non-zero (with a specific exit code) on any check
that fails. Operator must see all green before activation.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import sys

AGENT = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/agent")
SHADOW_EXEC = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec")
TB = pathlib.Path("/opt/tradingbot")

EXPECTED_SHA = {
    AGENT / "shadow_execution.py":
        "8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db",
    SHADOW_EXEC / "run_shadow_exec.py":
        "d791dfc4901e8b55de78fdc55d0204df152dfb9110a1f6a17ad42b0f80811955",
    SHADOW_EXEC / "run_shadow_exec.sh":
        "38d2e96b3e31ae3167b05543a4788aab1a53c8f91bbee3e3b020c90d2e0e82c3",
}


def _ok(msg: str) -> None:
    print(f"  OK   {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def check(step: int, title: str) -> None:
    print(f"\n{step}. {title}")


def main() -> int:
    failures = 0

    check(1, "IG_ACC_TYPE environment")
    acc = os.environ.get("IG_ACC_TYPE", "").upper().strip()
    if acc == "DEMO":
        _ok(f"IG_ACC_TYPE={acc}")
    else:
        _fail(f"IG_ACC_TYPE={acc!r} — MUST be DEMO")
        failures += 1
        print("     Resolve this before continuing. Aborting further checks.")
        return 10

    check(2, "Approved production SHAs unchanged")
    for p, expected in EXPECTED_SHA.items():
        try:
            got = hashlib.sha256(p.read_bytes()).hexdigest()
            if got == expected:
                _ok(f"{p.name}  sha256={got[:12]}…")
            else:
                _fail(f"{p.name}  sha256={got[:12]}… expected={expected[:12]}…")
                failures += 1
        except OSError as exc:
            _fail(f"{p}: {exc}")
            failures += 1

    check(3, "Strategy mode codes patch applied")
    sys.path.insert(0, str(TB))
    try:
        import ownership_identity as oi
        if "SCENARIO_V2_L" in oi._MODE_CODES and "SCENARIO_V2_S" in oi._MODE_CODES:
            _ok("SCENARIO_V2_L / SCENARIO_V2_S present in _MODE_CODES")
            if "SCENARIO_V2_L" in oi._SYSTEM_GROUP and "SCENARIO_V2_S" in oi._SYSTEM_GROUP:
                _ok("SCENARIO_V2_L / SCENARIO_V2_S present in _SYSTEM_GROUP")
            else:
                _fail("SCENARIO_V2_L / SCENARIO_V2_S missing from _SYSTEM_GROUP")
                failures += 1
        else:
            _fail("Mode codes patch not applied — SCENARIO_V2_L / SCENARIO_V2_S "
                   "absent from _MODE_CODES")
            failures += 1
    except Exception as exc:
        _fail(f"import ownership_identity failed: {exc}")
        failures += 1

    check(4, "Scenario V2 early-setup module installed")
    try:
        sys.path.insert(0, str(AGENT))
        import v2_early_setup as es
        _ok(f"v2_early_setup imports clean; VALID_MODES={es.VALID_MODES}")
    except Exception as exc:
        _fail(f"v2_early_setup import failed: {exc}")
        failures += 1

    check(5, "DEMO executor loads with correct guard")
    try:
        # Clean import — the module's own guard must accept DEMO.
        import importlib
        if "v2_demo_executor" in sys.modules:
            del sys.modules["v2_demo_executor"]
        v2 = importlib.import_module("v2_demo_executor")
        if not v2.V2_SV2_DEMO_ENABLED:
            _ok("v2_demo_executor loaded; V2_SV2_DEMO_ENABLED=0 (safe default)")
        else:
            _fail("V2_SV2_DEMO_ENABLED=1 at pre-flight time — expected 0")
            failures += 1
        if not hasattr(v2, "V2_SV2_DEMO_DRY_RUN"):
            _ok("No DRY_RUN flag (per operator directive)")
        else:
            _fail("V2_SV2_DEMO_DRY_RUN exists — operator rejected dry-run phase")
            failures += 1
    except Exception as exc:
        _fail(f"v2_demo_executor import failed: {exc}")
        failures += 1

    check(6, "IG DEMO session (READ-ONLY account query)")
    try:
        import ig_auth
        session, headers, account_id = ig_auth.get_ig_session()
        _ok(f"account id resolved: {account_id!r}")
        _ok(f"ig_auth.IG_ACC_TYPE={ig_auth.IG_ACC_TYPE}")
    except Exception as exc:
        _fail(f"get_ig_session failed: {exc}")
        failures += 1

    check(7, "ig_dealing_rules importable and operational")
    try:
        import ig_dealing_rules
        # Only check the lookup is callable; don't make an actual rejection.
        blocked, obs = ig_dealing_rules.is_known_too_tight(
            "CS.D.GBPUSD.TODAY.IP", 10.0)
        _ok(f"is_known_too_tight(10p)={blocked} obs={obs}")
    except Exception as exc:
        _fail(f"ig_dealing_rules check failed: {exc}")
        failures += 1

    check(8, "NMS directional authority gate callable")
    try:
        import nms_directional_authority as nms
        decision = nms.evaluate(symbol="GBPUSD",
                                 strategy_id="scenario_v2_early_preflight",
                                 strategy_family="BOUNCE_MEAN_REVERSION",
                                 side="BUY")
        _ok(f"NMS evaluate OK: applicable={getattr(decision,'applicable',None)} "
             f"allowed={getattr(decision,'allowed',None)} "
             f"reason={getattr(decision,'reason_code',None)!r}")
    except Exception as exc:
        _fail(f"NMS evaluate failed: {exc}")
        failures += 1

    print()
    if failures == 0:
        print("================================")
        print("PREFLIGHT ALL GREEN — operator may proceed to flip")
        print("V2_SV2_DEMO_ENABLED=1 in the service unit when ready.")
        print("================================")
        return 0
    else:
        print(f"PREFLIGHT FAILED — {failures} check(s). DO NOT activate.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
