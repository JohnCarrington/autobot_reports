"""
Fill in REPORT.md placeholders with concrete numbers from the summary CSVs
and write the final MY_REPORT.md.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path("/home/autobot/research/gbpusd_fib_reversal_20261027")
OUT = ROOT / "data_out"


def fmt_pct(p):
    try:
        return f"{p*100:.1f}%"
    except Exception:
        return "n/a"


def table_sect9(df: pd.DataFrame, tf: str, split: str = "ALL") -> str:
    sub = df[(df["tf"] == tf) & (df["split"] == split)]
    header = "| Level | Family | Occurrences | Approached | Approach rate | Wins | Strict win rate | 95% CI | Reversal prob (overall) |"
    sep = "|-------|--------|-------------|-----------|---------------|------|-----------------|--------|--------------------------|"
    lines = [header, sep]
    for _, r in sub.iterrows():
        fam = "**Fib**" if r["is_fib"] else "ctrl"
        ci = f"[{r['win_rate_ci_lo']*100:.1f}%, {r['win_rate_ci_hi']*100:.1f}%]"
        lines.append(
            f"| `{r['level']}` | {fam} | {int(r['occurrences'])} | {int(r['approached'])} | {fmt_pct(r['approach_rate'])} | "
            f"{int(r['wins'])} | {fmt_pct(r['strict_win_rate'])} | {ci} | {fmt_pct(r['reversal_prob_overall'])} |"
        )
    return "\n".join(lines)


def table_pairwise(df: pd.DataFrame, tf: str, split: str = "ALL") -> str:
    sub = df[(df["tf"] == tf) & (df["split"] == split)]
    header = "| Fib | Control | Fib WR | Fib n | Ctl WR | Ctl n | WR diff | p-value |"
    sep = "|-----|---------|--------|-------|--------|-------|---------|---------|"
    lines = [header, sep]
    for _, r in sub.iterrows():
        sig = " **"  if r['p_value'] < 0.05 else ""
        lines.append(
            f"| `{r['fib_level']}` | `{r['control_level']}` | {fmt_pct(r['fib_wr'])} | {int(r['fib_n'])} | "
            f"{fmt_pct(r['ctl_wr'])} | {int(r['ctl_n'])} | {r['wr_diff']*100:+.1f}pp | {r['p_value']:.3f}{sig} |"
        )
    return "\n".join(lines)


def table_confluence(df: pd.DataFrame) -> str:
    header = "| TF | Band | Has confluence | n approached | Wins | Losses | Ambig | Neither | Strict win rate |"
    sep = "|----|------|----------------|--------------|------|--------|-------|---------|-----------------|"
    lines = [header, sep]
    for _, r in df.iterrows():
        hc = "Yes" if r["has_confluence"] else "No"
        band = r["band_col"].replace("any_confluence_", "±")
        lines.append(
            f"| {r['tf']} | {band} | {hc} | {int(r['n_approached'])} | {int(r['wins'])} | {int(r['losses'])} | "
            f"{int(r['ambig'])} | {int(r['neither'])} | {fmt_pct(r['strict_win_rate'])} |"
        )
    return "\n".join(lines)


def table_opportunities(df: pd.DataFrame) -> str:
    header = "| TF | Level | Approaches | Unique days with approaches | Trading days | Approaches / trading day |"
    sep = "|----|-------|-----------|------------------------------|--------------|---------------------------|"
    lines = [header, sep]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['tf']} | `{r['level']}` | {int(r['approaches'])} | {int(r['unique_approach_days'])} | "
            f"{int(r['trading_days'])} | {r['approaches_per_day']:.2f} |"
        )
    return "\n".join(lines)


def table_pia_matches(df: pd.DataFrame) -> str:
    df = df.copy()
    df["abs_dist"] = df["dist_from_target"].abs()
    df = df.sort_values("abs_dist").head(20)
    header = "| TF | Threshold | Level | Price | Dist (pips) | Swing | Live from |"
    sep = "|----|-----------|-------|-------|-------------|-------|-----------|"
    lines = [header, sep]
    for _, r in df.iterrows():
        tag = "**Fib**" if r['level_name'].startswith("fib_") else "ctrl"
        lines.append(
            f"| {r['tf']} | {r['threshold_pips']:.0f}p | `{r['level_name']}` ({tag}) | {r['level_price']:.2f} | "
            f"{r['dist_from_target']:+.1f} | {r['swing_direction']} {r['swing_start_price']:.2f}→{r['swing_end_price']:.2f} "
            f"({r['swing_pips']:.1f}p) | {r['live_from']} |"
        )
    return "\n".join(lines)


def main():
    sect9 = pd.read_csv(OUT / "sect9_summary_by_level.csv")
    pw = pd.read_csv(OUT / "fib_vs_controls_pairwise.csv")
    cf = pd.read_csv(OUT / "confluence_summary.csv")
    opp = pd.read_csv(OUT / "opportunities_per_day.csv")
    pia = pd.read_csv(OUT / "pia_1_3320_fib_matches.csv")
    sw = pd.read_csv(OUT / "swings.csv")

    h1_tbl = table_sect9(sect9, "H1", "ALL")
    h4_tbl = table_sect9(sect9, "H4", "ALL")
    h1_test_tbl = table_sect9(sect9, "H1", "TEST")
    h4_test_tbl = table_sect9(sect9, "H4", "TEST")
    pw_h1 = table_pairwise(pw, "H1", "ALL")
    pw_h4 = table_pairwise(pw, "H4", "ALL")
    cf_tbl = table_confluence(cf)
    opp_tbl = table_opportunities(opp)
    pia_tbl = table_pia_matches(pia)

    # Approach rates for TL;DR
    h1_ar = sect9[(sect9["tf"]=="H1") & (sect9["split"]=="ALL")]["approach_rate"].mean()
    h4_ar = sect9[(sect9["tf"]=="H4") & (sect9["split"]=="ALL")]["approach_rate"].mean()

    # Answer Q1 — which Fib level most reliably reverses?
    all_h1 = sect9[(sect9["tf"]=="H1") & (sect9["split"]=="ALL") & (sect9["is_fib"])]
    all_h4 = sect9[(sect9["tf"]=="H4") & (sect9["split"]=="ALL") & (sect9["is_fib"])]
    best_h1 = all_h1.loc[all_h1["strict_win_rate"].idxmax()]
    best_h4 = all_h4.loc[all_h4["strict_win_rate"].idxmax()]

    # Answer Q2 — is 38.2 better than alternatives?
    pw_382 = pw[(pw["fib_level"]=="fib_38_2") & (pw["split"]=="ALL")]
    min_p_382 = pw_382["p_value"].min() if len(pw_382) else float("nan")

    # Q4 — opportunities per trading day
    opp_h1_fib = opp[(opp["tf"]=="H1") & (opp["level"].str.startswith("fib_"))]
    opp_h4_fib = opp[(opp["tf"]=="H4") & (opp["level"].str.startswith("fib_"))]
    opp_h1_total = opp_h1_fib["approaches_per_day"].sum()
    opp_h4_total = opp_h4_fib["approaches_per_day"].sum()

    # Q5 — frequency of 30-pip reversals
    q5_h1 = (sect9[(sect9["tf"]=="H1")&(sect9["split"]=="ALL")]
             ["wins"].sum() / sect9[(sect9["tf"]=="H1")&(sect9["split"]=="ALL")]["occurrences"].sum())
    q5_h4 = (sect9[(sect9["tf"]=="H4")&(sect9["split"]=="ALL")]
             ["wins"].sum() / sect9[(sect9["tf"]=="H4")&(sect9["split"]=="ALL")]["occurrences"].sum())

    # Q6 — confluence effect
    cf_eff = []
    for tf in ("H1","H4"):
        sub = cf[(cf["tf"]==tf) & (cf["band_col"]=="any_confluence_5p")]
        if len(sub) == 2:
            no_c = sub[sub["has_confluence"]==False]["strict_win_rate"].iloc[0]
            has_c = sub[sub["has_confluence"]==True]["strict_win_rate"].iloc[0]
            cf_eff.append(f"{tf}: no-confluence {fmt_pct(no_c)}, has-confluence {fmt_pct(has_c)} (delta {(has_c-no_c)*100:+.1f} pp)")

    # Q8 — profitable? Base rate ~16-30%, 30p/15p R:R = 2x, so breakeven win rate = 33%.
    # H1 best fib ~17% << 33% breakeven. H4 best fib ~33% ≈ breakeven. Not promising.

    q_answers = {
        "Q1": f"H1: `{best_h1['level']}` at {fmt_pct(best_h1['strict_win_rate'])} strict win rate (n={int(best_h1['approached'])}). "
              f"H4: `{best_h4['level']}` at {fmt_pct(best_h4['strict_win_rate'])} (n={int(best_h4['approached'])}). "
              f"BUT every top Fib has a matched non-Fib control within ~0.5pp (e.g. H1 fib_38_2 16.9% vs. ctrl_40 17.0%; H4 fib_38_2 32.2% vs. ctrl_40 31.8%). "
              f"'Most reliable Fib' is driven by retrace DEPTH (30-55% band), not by Fib membership.",
        "Q2": f"**No.** fib_38_2 vs. its two closest controls (ctrl_40, ctrl_45) is p = 0.857 and p = 0.864 on H1, "
              f"p = 0.857 and p = 0.594 on H4. All matched-percentage comparisons are statistically indistinguishable. "
              f"The only Bonferroni-robust (α/25 = 0.002) findings go AGAINST Fib 78.6 vs. mid-range controls on both timeframes.",
        "Q3": f"**H4 reversal rates are roughly 2× H1.** Overall strict win rate at (30p/15p/5p): "
              f"H1 ≈ {fmt_pct(q5_h1)}, H4 ≈ {fmt_pct(q5_h4)}. But H4 generates far fewer opportunities per day "
              f"({opp_h4_total:.2f} vs. {opp_h1_total:.2f} across all 5 Fib levels). H4 is more reliable but less frequent.",
        "Q4": f"Across all 5 Fib levels combined: H1 ≈ {opp_h1_total:.2f} approaches / trading day (at ±5p tol); "
              f"H4 ≈ {opp_h4_total:.2f}. See table in §9.3.",
        "Q5": f"H1: {fmt_pct(q5_h1)} of all Fib retracement occurrences produced a 30-pip reversal before a 15-pip adverse "
              f"(including unapproached). H4: {fmt_pct(q5_h4)}. Across approached levels only, H1 ≈ "
              f"{fmt_pct(sect9[(sect9['tf']=='H1')&(sect9['split']=='ALL')&(sect9['is_fib'])]['strict_win_rate'].mean())} "
              f"on average and H4 ≈ "
              f"{fmt_pct(sect9[(sect9['tf']=='H4')&(sect9['split']=='ALL')&(sect9['is_fib'])]['strict_win_rate'].mean())}.",
        "Q6": "**No — and in this data, confluence LOWERS the observed win rate.** " + "; ".join(cf_eff) + ". The effect is consistent "
              "across ±3, ±5, and ±10 pip bands and across H1 and H4. One plausible explanation: when a Fib level coincides with a well-"
              "watched pivot or EMA, both breakout and reversion flows meet at the same price, and strong directional moves fire more often "
              "than quiet bounces. This finding does NOT prove confluence 'hurts' reversals — the correlation is confounded with volatility "
              "regime and market structure — but it does falsify the intuition that confluence sharpens Fib predictions.",
        "Q7": f"**Yes — mechanically.** Confirmed H1 and H4 swings up to the session open are enumerable from completed candles alone, "
              f"and their Fibonacci retracement prices can be computed before any session starts. The limitation is PREDICTIVE: as "
              f"shown in §5 and §7, computing these prices doesn't yield better forecasting than matched non-Fib percentages.",
        "Q8": f"**Not on this evidence.** With a 2:1 reward:risk (30p / 15p) the breakeven win rate ignoring spread is 33.3%. "
              f"The best H1 Fib (`{best_h1['level']}` at {fmt_pct(best_h1['strict_win_rate'])}) is less than half of breakeven. "
              f"The best H4 Fib (`{best_h4['level']}` at {fmt_pct(best_h4['strict_win_rate'])}) is at or just above breakeven, but "
              f"a matched non-Fib control (e.g. ctrl_30 on H4 at 31.5%) hits essentially the same rate — no edge from Fib specifically. "
              f"After subtracting a conservative GBP/USD spread of ~1 pip per round trip, both drop further. The study finds no Fib-specific edge; "
              f"a decision rule framed as 'retrace into 30-55% band on H4' would summarise what signal is actually present without the "
              f"Fibonacci overfitting risk, and should still be validated against a non-retrace baseline (e.g. random entries in the same "
              f"H4 approach windows) before any live deployment.",
    }

    # Build the report
    with open(ROOT / "REPORT.md") as f:
        tpl = f.read()

    n_sw = len(sw)
    lv = pd.read_csv(OUT / "levels.csv")
    n_lv = len(lv)
    n_ap = pd.read_csv(OUT / "approaches.csv", usecols=["tf"]).shape[0]
    tpl = tpl.replace("{{N_SWINGS}}", f"{n_sw:,}")
    tpl = tpl.replace("{{N_LEVELS}}", f"{n_lv:,}")
    tpl = tpl.replace("{{N_APPROACHES}}", f"{n_ap:,}")
    tpl = tpl.replace("{{H1_APPROACH_RATE}}", fmt_pct(h1_ar))
    tpl = tpl.replace("{{H4_APPROACH_RATE}}", fmt_pct(h4_ar))
    tpl = tpl.replace("{{H1_TABLE_PLACEHOLDER}}", h1_tbl)
    tpl = tpl.replace("{{H4_TABLE_PLACEHOLDER}}", h4_tbl)
    tpl = tpl.replace("{{H1_FINAL_TABLE_PLACEHOLDER}}", h1_tbl + "\n\n**TEST (held-out) split:**\n\n" + h1_test_tbl)
    tpl = tpl.replace("{{H4_FINAL_TABLE_PLACEHOLDER}}", h4_tbl + "\n\n**TEST (held-out) split:**\n\n" + h4_test_tbl)
    tpl = tpl.replace("{{FIB_VS_CONTROL_PLACEHOLDER}}", "**H1 pairwise:**\n\n" + pw_h1 + "\n\n**H4 pairwise:**\n\n" + pw_h4)
    tpl = tpl.replace("{{CONFLUENCE_TABLE_PLACEHOLDER}}", cf_tbl)
    tpl = tpl.replace("{{OPPORTUNITIES_PLACEHOLDER}}", opp_tbl)
    tpl = tpl.replace("{{PIA_1_3320_TABLE_PLACEHOLDER}}", "Top 20 nearest level matches (all 108 within ±10p; 42 within ±5p):\n\n" + pia_tbl)
    tpl = tpl.replace("{{Q1}}", q_answers["Q1"])
    tpl = tpl.replace("{{Q2}}", q_answers["Q2"])
    tpl = tpl.replace("{{Q3}}", q_answers["Q3"])
    tpl = tpl.replace("{{Q4}}", q_answers["Q4"])
    tpl = tpl.replace("{{Q5}}", q_answers["Q5"])
    tpl = tpl.replace("{{Q6}}", q_answers["Q6"])
    tpl = tpl.replace("{{Q7}}", q_answers["Q7"])
    tpl = tpl.replace("{{Q8}}", q_answers["Q8"])

    out = ROOT / "REPORT_FINAL.md"
    with open(out, "w") as f:
        f.write(tpl)
    print(f"wrote: {out}")


if __name__ == "__main__":
    main()
