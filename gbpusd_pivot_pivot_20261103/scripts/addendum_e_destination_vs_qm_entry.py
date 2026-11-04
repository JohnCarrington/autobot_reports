"""Addendum E — Does entering AT the nearest pivot (destination-aware) beat
QM's actual entry on the historical graded-candidate record?

For each of the 102 QM graded ENTRY_ARMED candidates (BID 2026-09-15 to
2026-11-04), construct an alternative "destination-aware" trade:

  * Direction: same as QM.
  * Entry price: the NEAREST daily pivot to QM's entry (if |QM_entry - nearest_pivot|
    <= 20p), using the PRIOR-DAY ASK D1 bar for pivot calculation.
    If no pivot within 20p, skip the row (not destination-aware).
  * Stop: same size (pips) as QM's stop, applied from the alternative entry.
  * Target: same STRUCT-derived target as QM, measured in pips, re-applied from
    the alternative entry.
  * Resolution: using the same 240-bar outcome horizon that the grader used,
    simulate which hits first (stop or target) at the alternative entry.

Because the original grader records `stop_first/target_first/mae_pips/mfe_pips`
over 240 bars, and the alternative entry sits WITHIN that window, we can resolve
the alternative entry's outcome from the MFE/MAE + the entry-shift pips:

  alt_entry_shift = alt_entry - qm_entry    (signed; positive for BUY entry above QM, etc.)

  * BUY: alt_SL  hit iff (alt_entry - stop_pips)  reached via original MAE -> original mae_pips >= (alt_entry - qm_entry)*10000 + stop_pips
           alt_TP  hit iff (alt_entry + target_pips) reached via original MFE -> original mfe_pips >= target_pips - (alt_entry - qm_entry)*10000
  * SELL symmetric.

This is approximate (the order of MAE vs MFE matters; we don't know which hit
first UNDER THE SHIFTED PRICE). We make a conservative assumption: if both
would have hit under the alternative, record the ORIGINAL outcome (don't flip).
If only one would have hit under the alternative, record that.

Writes csv/addendum_e_destination_vs_actual.csv.
"""

from __future__ import annotations

import csv
import pathlib

CSV_IN  = pathlib.Path(__file__).parent.parent / "csv" / "addendum_b1_qm_graded.csv"
OUT_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_e_destination_vs_actual.csv"

SPREAD_PIPS = 1.5
PROXIMITY_MAX_PIPS = 20.0

def main() -> None:
    rows = list(csv.DictReader(CSV_IN.open()))
    print(f"Loaded {len(rows)} QM graded rows")

    out = []
    kept = 0
    for r in rows:
        if r["net_pips_after_spread"] == "UNRESOLVED":
            continue
        qm_entry   = float(r["entry"])
        qm_stop_p  = float(r["stop_pips"])
        qm_tgt_p   = float(r["target_pips"])
        near_dist  = float(r["nearest_pivot_dist_pips_abs"])
        near_signed = float(r["nearest_pivot_dist_pips_signed"])
        near_val   = float(r["nearest_pivot_value"])
        side       = r["side"]
        stop_first = int(r["stop_first"])
        tgt_first  = int(r["target_first"])
        qm_mfe     = float(r["mfe_pips"])
        qm_mae     = float(r["mae_pips"])

        if near_dist > PROXIMITY_MAX_PIPS:
            continue  # not destination-aware
        kept += 1

        # Alternative entry = nearest pivot
        alt_entry = near_val
        # Entry shift (signed, pips): positive if alt_entry > qm_entry
        shift_pips = (alt_entry - qm_entry) * 10000.0

        # Alternative outcome resolution
        # For a BUY: stop sits at alt_entry - stop_pips/10000. Target at alt_entry + target_pips/10000.
        # Did MAE from QM entry (going down from qm_entry to the low) reach alt_stop?
        #   lowest post-entry price = qm_entry - qm_mae/10000
        #   alt_stop price = alt_entry - qm_stop_p/10000
        #   stop hit iff lowest <= alt_stop iff (qm_entry - alt_entry + alt_stop_offset) > 0
        #   i.e. qm_mae + shift_pips >= qm_stop_p
        # Target hit iff highest >= alt_target iff qm_mfe - shift_pips >= qm_tgt_p
        # For SELL symmetric.
        if side == "BUY":
            alt_stop_hit = (qm_mae + shift_pips) >= qm_stop_p
            alt_tgt_hit  = (qm_mfe - shift_pips) >= qm_tgt_p
        else:
            alt_stop_hit = (qm_mae - shift_pips) >= qm_stop_p
            alt_tgt_hit  = (qm_mfe + shift_pips) >= qm_tgt_p

        # Resolve in a conservative order: if both flags true, trust the ORIGINAL ordering
        # (if QM original was stop_first, assume alt was stop_first too).
        # If only one flag true, use that one.
        if alt_stop_hit and alt_tgt_hit:
            alt_stop_first = bool(stop_first)
            alt_tgt_first  = bool(tgt_first)
        elif alt_stop_hit:
            alt_stop_first = True; alt_tgt_first = False
        elif alt_tgt_hit:
            alt_stop_first = False; alt_tgt_first = True
        else:
            alt_stop_first = False; alt_tgt_first = False  # unresolved

        if alt_tgt_first:
            alt_net = qm_tgt_p - SPREAD_PIPS
        elif alt_stop_first:
            alt_net = -qm_stop_p - SPREAD_PIPS
        else:
            alt_net = None

        qm_net = float(r["net_pips_after_spread"])
        delta  = (alt_net - qm_net) if alt_net is not None else None

        out.append({
            "opened_at": r["opened_at"],
            "side": side,
            "nearest_pivot_name": r["nearest_pivot_name"],
            "qm_entry": r["entry"],
            "alt_entry": f"{alt_entry:.5f}",
            "entry_shift_pips": f"{shift_pips:+.1f}",
            "stop_pips": r["stop_pips"],
            "target_pips": r["target_pips"],
            "qm_mfe_pips": r["mfe_pips"],
            "qm_mae_pips": r["mae_pips"],
            "qm_stop_first": stop_first,
            "qm_target_first": tgt_first,
            "qm_net_pips": r["net_pips_after_spread"],
            "alt_stop_hit_reachable": int(alt_stop_hit),
            "alt_tgt_hit_reachable":  int(alt_tgt_hit),
            "alt_net_pips": "UNRESOLVED" if alt_net is None else f"{alt_net:+.1f}",
            "delta_pips_vs_qm": "n/a" if delta is None else f"{delta:+.1f}",
            "session": r["session"],
            "basis_of_pivots": r["basis_of_pivots"],
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"Kept (within {PROXIMITY_MAX_PIPS}p of a pivot): {kept}   wrote {OUT_CSV}")

    # Summary
    alt_resolved = [r for r in out if r["alt_net_pips"] != "UNRESOLVED"]
    qm_resolved  = [r for r in out if r["qm_net_pips"] != "UNRESOLVED"]
    print(f"\nAlternative resolved: {len(alt_resolved)}  QM resolved: {len(qm_resolved)}")
    if alt_resolved:
        alt_total = sum(float(r["alt_net_pips"]) for r in alt_resolved)
        alt_wins  = sum(1 for r in alt_resolved if float(r["alt_net_pips"]) > 0)
        print(f"  ALT: win%={100*alt_wins/len(alt_resolved):.1f}  total={alt_total:+.1f}p  mean={alt_total/len(alt_resolved):+.2f}p/trade")
    if qm_resolved:
        qm_total = sum(float(r["qm_net_pips"]) for r in qm_resolved)
        qm_wins  = sum(1 for r in qm_resolved if float(r["qm_net_pips"]) > 0)
        print(f"  QM:  win%={100*qm_wins/len(qm_resolved):.1f}  total={qm_total:+.1f}p  mean={qm_total/len(qm_resolved):+.2f}p/trade")

    # Head-to-head: on rows where BOTH resolved, how many improved?
    both = [r for r in out if r["alt_net_pips"] != "UNRESOLVED" and r["qm_net_pips"] != "UNRESOLVED"]
    print(f"\nHead-to-head rows: {len(both)}")
    improved = sum(1 for r in both if float(r["alt_net_pips"]) > float(r["qm_net_pips"]))
    worse    = sum(1 for r in both if float(r["alt_net_pips"]) < float(r["qm_net_pips"]))
    same     = len(both) - improved - worse
    print(f"  ALT better: {improved}   ALT worse: {worse}   same: {same}")
    delta_sum = sum(float(r["alt_net_pips"]) - float(r["qm_net_pips"]) for r in both)
    print(f"  Aggregate delta ALT - QM: {delta_sum:+.1f}p  mean={delta_sum/len(both):+.2f}p/trade")

    # Break down by whether alt entry was ABOVE (worse for BUY) or BELOW (better for BUY)
    print()
    for side in ("BUY", "SELL"):
        buy_rows = [r for r in both if r["side"] == side]
        better_entry = [r for r in buy_rows if
                         (side == "BUY" and float(r["entry_shift_pips"]) < 0) or
                         (side == "SELL" and float(r["entry_shift_pips"]) > 0)]
        worse_entry = [r for r in buy_rows if
                        (side == "BUY" and float(r["entry_shift_pips"]) > 0) or
                        (side == "SELL" and float(r["entry_shift_pips"]) < 0)]
        print(f"  {side}: total={len(buy_rows)}  pivot_entry_more_favourable={len(better_entry)}  less_favourable={len(worse_entry)}")

if __name__ == "__main__":
    main()
