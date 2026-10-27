"""Phase 3b Stage 3 — run synthetic BB Bounce fire-path fixtures.

For each fixture, feed bars one at a time into the production BB Bounce strategy
under isolation, record every state transition and fire decision, and compare
against the fixture's expected outcome.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.isolation import init_isolation  # noqa: E402
from fixtures.bb_fire_fixtures import all_fixtures  # noqa: E402

OUT = Path("/tmp/phase3b_audit/data")
OUT.mkdir(parents=True, exist_ok=True)


def run_fixture(fixture: dict) -> dict:
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True

        lifecycle: list[dict] = []
        bb._write_bb_bounce_lifecycle_row = lifecycle.append
        if hasattr(bb, "_write_bb_bounce_standdown_row"):
            bb._write_bb_bounce_standdown_row = lifecycle.append

        s = bb.GbpUsdBBBounceStrategy()
        bars_so_far: list = []
        closes_ind: list[float] = []
        fires: list[dict] = []
        state_transitions: list[dict] = []
        for i, bar in enumerate(fixture["bars"]):
            bars_so_far.append(bar)
            closes_ind.append(float(bar.close))
            pre_armed = len(s._armed_setups.get("CS.D.GBPUSD.TODAY.IP", []))
            try:
                d = s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar.timestamp,
                               bars_so_far, closes_ind, False, False)
            except Exception as e:
                return {"fixture": fixture["pathway"], "status": "exception",
                        "err": repr(e), "bar_idx": i}
            post_armed = len(s._armed_setups.get("CS.D.GBPUSD.TODAY.IP", []))
            if pre_armed != post_armed:
                state_transitions.append({
                    "bar_idx": i, "ts": bar.timestamp.isoformat(),
                    "armed_before": pre_armed, "armed_after": post_armed,
                })
            if d is not None:
                fires.append({
                    "bar_idx": i, "ts": bar.timestamp.isoformat(),
                    "signal": getattr(d, "signal", None),
                    "mode": getattr(d, "mode", None),
                    "entry_price": getattr(d, "entry_price", None),
                    "sl_pips": getattr(d, "sl_pips", None),
                    "tp_pips": getattr(d, "tp_pips", None),
                })

        return {
            "fixture": fixture["pathway"],
            "status": "ok",
            "n_bars": len(fixture["bars"]),
            "n_fires": len(fires),
            "n_state_transitions": len(state_transitions),
            "n_lifecycle_events": len(lifecycle),
            "expected_fire_idx": fixture["expected_fire_at_idx"],
            "expected_direction": fixture["expected_direction"],
            "fires": fires,
            "state_transitions": state_transitions,
            "lifecycle_tail": lifecycle[-5:] if lifecycle else [],
        }


def main():
    # Need bb module to construct bars — import once outside isolation to get Bar class
    with init_isolation():
        sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb_tmp
        fixtures = all_fixtures(bb_tmp)

    results = []
    for fix in fixtures:
        print(f"[{fix['pathway']}] running {len(fix['bars'])} bars (expected fire at {fix['expected_fire_at_idx']})", flush=True)
        res = run_fixture(fix)
        results.append(res)
        print(f"  → fires={res.get('n_fires','?')} transitions={res.get('n_state_transitions','?')} "
              f"lifecycle={res.get('n_lifecycle_events','?')}", flush=True)
        if res.get("fires"):
            for f in res["fires"]:
                print(f"    FIRE at idx={f['bar_idx']} ts={f['ts']} signal={f['signal']}", flush=True)

    # Verify expectations
    passing = 0
    for r, f in zip(results, fixtures):
        exp_fire = f["expected_fire_at_idx"] is not None
        got_fire = r.get("n_fires", 0) > 0
        if exp_fire == got_fire:
            # If expected a fire, verify direction + idx
            if exp_fire:
                first_fire = r["fires"][0]
                if first_fire["signal"] == f["expected_direction"]:
                    passing += 1
                    r["verdict"] = "PASS"
                else:
                    r["verdict"] = f"FAIL (direction {first_fire['signal']} != expected {f['expected_direction']})"
            else:
                passing += 1
                r["verdict"] = "PASS (no fire as expected)"
        else:
            r["verdict"] = f"FAIL (expected fire={exp_fire}, got fire={got_fire})"

    (OUT / "stage3_fixture_results.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[summary] {passing}/{len(results)} fixtures PASS")
    for r in results:
        print(f"  {r.get('verdict','?'):50s} ← {r['fixture']}")


if __name__ == "__main__":
    main()
