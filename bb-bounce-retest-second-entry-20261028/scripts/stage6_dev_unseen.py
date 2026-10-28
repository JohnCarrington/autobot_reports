"""Phase 7 Stage 6 — DEV / UNSEEN chronological split.

Pre-registered cutoff per PROGRESS.md §1.1: `2026-01-01` UTC.

Reads the per-opportunity pnl table from Stage 2 and reports per-cell
DEV / UNSEEN expectancy and PF.  Includes monthly net-pips for the two
most interesting Strategy B cells so overfitting is visible.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"


def _stats(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=np.float64)
    taken = x[x != 0.0]  # for B/C, zero == NO_TRADE
    winners = x[x > 0]
    losers = x[x < 0]
    gw = float(winners.sum())
    gl = float(abs(losers.sum()))
    return {
        "opportunities": int(len(x)),
        "trades_taken": int(len(taken)),
        "winners": int((x > 0).sum()),
        "losers": int((x < 0).sum()),
        "win_rate_taken_pct": round(100.0 * (x > 0).sum() / max(1, len(taken)), 2),
        "net_pips": round(float(x.sum()), 1),
        "expectancy_per_opp_pips": round(float(x.mean()) if len(x) else 0.0, 3),
        "profit_factor": round(gw / gl, 3) if gl > 0 else None,
    }


def main() -> int:
    df = pd.read_parquet(DATA / "stage2_abc_trades.parquet")
    df["fill_dt"] = pd.to_datetime(df["fill_ts_ns"], unit="ns", utc=True)
    cutoff = pd.Timestamp("2026-01-01", tz="UTC")
    dev_mask = (df["fill_dt"] < cutoff).values
    uns_mask = ~dev_mask
    print(f"n_dev={dev_mask.sum()}  n_unseen={uns_mask.sum()}")

    report = {
        "cutoff_pre_registered": "2026-01-01",
        "n_dev": int(dev_mask.sum()),
        "n_unseen": int(uns_mask.sum()),
        "A": {}, "B": {}, "C": {},
    }

    pnl_cols = [c for c in df.columns if c.endswith("_pnl")]
    for col in pnl_cols:
        arr = df[col].values.astype(np.float64)
        row = {"DEV": _stats(arr[dev_mask]), "UNSEEN": _stats(arr[uns_mask])}
        if col.startswith("A_"):
            report["A"][col.replace("A_", "").replace("_pnl", "")] = row
        elif col.startswith("B_"):
            report["B"][col.replace("B_", "").replace("_pnl", "")] = row
        elif col.startswith("C_"):
            report["C"][col.replace("C_", "").replace("_pnl", "")] = row

    # Rank cells by DEV expectancy; check UNSEEN sign agreement
    def _top_cells(block: dict, k: int = 10):
        return sorted(block.items(),
                      key=lambda kv: -(kv[1]["DEV"]["expectancy_per_opp_pips"]))[:k]

    report["A_top10_dev"] = _top_cells(report["A"])
    report["B_top10_dev"] = _top_cells(report["B"])
    report["C_top10_dev"] = _top_cells(report["C"])

    # Monthly net pips for two interesting B cells
    for cell in ["B_s8_t60_w60", "B_s12_t60_w60", "B_s8_t50_w60"]:
        col = cell + "_pnl"
        if col not in df.columns:
            continue
        tmp = pd.DataFrame({"fill_dt": df["fill_dt"], "pnl": df[col]})
        tmp["ym"] = tmp["fill_dt"].dt.strftime("%Y-%m")
        monthly = tmp.groupby("ym")["pnl"].agg(["sum", "count"]).round(2)
        monthly.columns = ["net_pips", "opportunities"]
        tmp2 = df[df[col] != 0.0]
        tmp2 = tmp2.assign(ym=tmp2["fill_dt"].dt.strftime("%Y-%m"))
        taken = tmp2.groupby("ym")[col].count().rename("trades_taken")
        monthly = monthly.join(taken).fillna(0)
        monthly["trades_taken"] = monthly["trades_taken"].astype(int)
        report.setdefault("monthly", {})[cell] = monthly.round(1).reset_index().to_dict(orient="records")

    (DATA / "stage6_dev_unseen.json").write_text(
        json.dumps(report, indent=2, default=str)
    )

    # Terse print: top 5 B cells by DEV expectancy + their UNSEEN rank
    print("\nTop 5 Strategy B cells by DEV expectancy:")
    for i, (name, stats) in enumerate(report["B_top10_dev"][:5]):
        print(f"  #{i+1} {name}: DEV expy={stats['DEV']['expectancy_per_opp_pips']} "
              f"PF={stats['DEV']['profit_factor']}; "
              f"UNSEEN expy={stats['UNSEEN']['expectancy_per_opp_pips']} "
              f"PF={stats['UNSEEN']['profit_factor']}")
    print("\nTop 5 Strategy C cells by DEV expectancy:")
    for i, (name, stats) in enumerate(report["C_top10_dev"][:5]):
        print(f"  #{i+1} {name}: DEV expy={stats['DEV']['expectancy_per_opp_pips']} "
              f"PF={stats['DEV']['profit_factor']}; "
              f"UNSEEN expy={stats['UNSEEN']['expectancy_per_opp_pips']} "
              f"PF={stats['UNSEEN']['profit_factor']}")
    print("\nTop 5 Strategy A cells by DEV expectancy:")
    for i, (name, stats) in enumerate(report["A_top10_dev"][:5]):
        print(f"  #{i+1} {name}: DEV expy={stats['DEV']['expectancy_per_opp_pips']} "
              f"PF={stats['DEV']['profit_factor']}; "
              f"UNSEEN expy={stats['UNSEEN']['expectancy_per_opp_pips']} "
              f"PF={stats['UNSEEN']['profit_factor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
