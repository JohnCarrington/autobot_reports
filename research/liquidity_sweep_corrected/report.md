# Corrected Liquidity-Sweep Research — Final Report

**Date:** 2026-10-17
**Branch:** `research/liquidity-sweep-corrected-20261017`
**Scope:** 643 authorised FX days per the Stage 0b manifest (SHA 16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc).
**Guardrails:** production AutoBot untouched; NMS V3 untouched; standalone BB Bounce untouched; London Liquidity Sweep service untouched; no deploys; no restarts; no technical-indicator additions.

## TL;DR
- **TYPE_A immediate sweeps** (price pierces the level by wick + closes back + no completed M5 close beyond): **2,534 trades under Model 1 30/12 wick entry, WR 47.5%, PF 2.19, E = 7.70 pips/trade** post-cost.  **OOS alone**: n = 274, E = 7.50p, CI95 strictly positive.
- **TYPE_B delayed failed breakouts** are the opposite: negative expectancy across every partition.
- **Aggregate TYPE_A + TYPE_B combined** is negative overall because TYPE_B outnumbers TYPE_A ~8× in the raw event population.  **Any trading implementation would need to filter to TYPE_A only.**
- Stage 1 missed the result because its 9,349-row wick-rejection pool conflated TYPE_A and TYPE_B — the corrected independent scan separates them cleanly.
- All results carry the **UNVERIFIED CLOCKS** caveat (candles not clock-verified) and the OOS BID→MID basis-change caveat (see implementation_notes.md §1,§3).

## 0. Preamble
This report delivers §13 answers for the corrected liquidity-sweep research.  Operator approvals captured in `stage0_amendment_a2_operator_approvals.md`:
- Rejection detector primary: `level_ladder._is_rejection_at_rung` (AMB-1 (b)).
- M5 swing confirmation: `market_structure.detect_confirmed_swings(N=3)` (AMB-2 (β)); H1/H4 supplementary swings included; session-scoped swings excluded.
- Repeated-test counter: D-B at 12 pips (AMB-3) with D-A/D-C sensitivities.
- Entry primary = wick (next bar passes rejection extreme); secondary = close.
- HTF direction = tag only (amendment A1).  Reported but never gates events.
- Exit Model 1 = 30 pip TP / 12 pip SL approved; Model 2 deferred (§G).

## 1. Deliverable A reference
Stage 1 test-design discrepancy audit lives in `stage0_ambiguity_audit.md` §1 and is unchanged.

## Deliverable B — Independent structural-level approach population

Total approach episodes: **58,922**

### By partition
```
partition  episodes  unique_days  unique_levels
      DEV     40023          424           8831
  HOLDOUT     13585          137           3214
      OOS      5314           57           1301
```

### By level family
```
level_family  D_PIVOT_P  D_PIVOT_R1  D_PIVOT_R2  D_PIVOT_R3  D_PIVOT_S1  D_PIVOT_S2  D_PIVOT_S3  M5_SWING_H  M5_SWING_L  PDH  PDL  ROUND_00  ROUND_50
partition                                                                                                                                            
DEV                2710         636         232          91         488         193          98       20752       10374  811  672      1570      1396
HOLDOUT             888         163          67          20         170          84          29        7197        3557  248  282       420       460
OOS                 398          60          27          13         117          34          15        2692        1413   64  123       162       196
```

### By basis (BID / MID)
```
basis        BID   MID
partition             
DEV        40023     0
HOLDOUT    13585     0
OOS            0  5314
```

## Deliverable C — Sweep taxonomy + Sequence A/B/C

### Sweep type (per approach)
```
sweep_type   NONE  TYPE_A  TYPE_B
partition                        
DEV         19071    2590   18362
HOLDOUT      6443     823    6319
OOS          2412     427    2475
```

### Sequence class × role
```
sequence_role             final_sweep  lead_test   none  sweep
partition sequence_class                                      
DEV       A                         0          0      0   2228
          C                      4538      13326      0      0
          NONE                      0          0  19931      0
HOLDOUT   A                         0          0      0    768
          C                      1515       4478      0      0
          NONE                      0          0   6824      0
OOS       A                         0          0      0    294
          C                       631       1899      0      0
          NONE                      0          0   2490      0
```


## Deliverable D — Rejection + confirmation ledger

```
           with_rejection  with_wick_confirm  with_close_confirm  episodes  rejection_rate  wick_conf_given_rej  close_conf_given_rej
partition                                                                                                                            
DEV                 17434              15591               12777     40023        0.435600             0.894287              0.732878
HOLDOUT              5960               5340                4402     13585        0.438719             0.895973              0.738591
OOS                  2368               2093                1737      5314        0.445615             0.883868              0.733530
```

## Deliverable E — Favourable / adverse excursion

```
partition entry_rule     n  mfe_mean  mfe_median  mae_mean  reach_10p  reach_15p  reach_20p  reach_25p  reach_30p  reach_40p
      DEV       wick 15591      15.6        11.1      12.2      0.531      0.422      0.352      0.304      0.264      0.022
      DEV      close 12777      14.8        10.0      12.8      0.502      0.400      0.332      0.287      0.246      0.019
  HOLDOUT       wick  5340      15.6        11.7      11.9      0.548      0.428      0.354      0.295      0.262      0.016
  HOLDOUT      close  4402      14.8        10.6      12.4      0.514      0.402      0.328      0.279      0.240      0.013
      OOS       wick  2093      16.4        13.2      12.2      0.574      0.462      0.376      0.326      0.285      0.021
      OOS      close  1737      15.1        11.0      13.0      0.527      0.406      0.336      0.291      0.248      0.016
```

## Deliverable F — Fixed 30/12 TP/SL outcomes (Model 1)

### Entry rule: wick

  DEV      n=15,591  wins= 4058  losses=10966  timeouts=  567  wr=26.0%  pf=0.83  E=-1.65p  net=-25728.9p
  HOLDOUT  n= 5,340  wins= 1398  losses= 3677  timeouts=  265  wr=26.2%  pf=0.85  E=-1.35p  net=-7223.5p
  OOS      n= 2,093  wins=  595  losses= 1446  timeouts=   52  wr=28.4%  pf=0.90  E=-0.90p  net=-1884.0p
  ALL      n=23,024  wins= 6051  losses=16089  timeouts=  884  wr=26.3%  pf=0.84  E=-1.51p  net=-34836.4p

### By sweep type (entry_rule=wick)
  TYPE_A   DEV      n= 1,733  wins=  849  losses=  814  timeouts=   70  wr=49.0%  pf=2.30  E=8.22p  net=14250.6p
  TYPE_A   HOLDOUT  n=   527  wins=  224  losses=  266  timeouts=   37  wr=42.5%  pf=1.89  E=6.09p  net=3209.8p
  TYPE_A   OOS      n=   274  wins=  130  losses=  133  timeouts=   11  wr=47.4%  pf=2.15  E=7.50p  net=2055.9p
  TYPE_A   ALL      n= 2,534  wins= 1203  losses= 1213  timeouts=  118  wr=47.5%  pf=2.19  E=7.70p  net=19516.3p

  TYPE_B   DEV      n=13,858  wins= 3209  losses=10152  timeouts=  497  wr=23.2%  pf=0.71  E=-2.88p  net=-39979.5p
  TYPE_B   HOLDOUT  n= 4,813  wins= 1174  losses= 3411  timeouts=  228  wr=24.4%  pf=0.77  E=-2.17p  net=-10433.3p
  TYPE_B   OOS      n= 1,819  wins=  465  losses= 1313  timeouts=   41  wr=25.6%  pf=0.78  E=-2.17p  net=-3940.0p
  TYPE_B   ALL      n=20,490  wins= 4848  losses=14876  timeouts=  766  wr=23.7%  pf=0.73  E=-2.65p  net=-54352.8p

  NONE     DEV      n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p
  NONE     HOLDOUT  n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p
  NONE     OOS      n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p
  NONE     ALL      n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p

### Entry rule: close

  DEV      n=12,777  wins= 3102  losses= 9215  timeouts=  460  wr=24.3%  pf=0.75  E=-2.40p  net=-30660.8p
  HOLDOUT  n= 4,402  wins= 1056  losses= 3139  timeouts=  207  wr=24.0%  pf=0.76  E=-2.35p  net=-10323.1p
  OOS      n= 1,737  wins=  431  losses= 1260  timeouts=   46  wr=24.8%  pf=0.75  E=-2.43p  net=-4219.9p
  ALL      n=18,916  wins= 4589  losses=13614  timeouts=  713  wr=24.3%  pf=0.75  E=-2.39p  net=-45203.8p

### By sweep type (entry_rule=close)
  TYPE_A   DEV      n= 1,700  wins=  636  losses=  995  timeouts=   69  wr=37.4%  pf=1.42  E=3.34p  net=5670.7p
  TYPE_A   HOLDOUT  n=   511  wins=  174  losses=  311  timeouts=   26  wr=34.1%  pf=1.25  E=2.06p  net=1050.6p
  TYPE_A   OOS      n=   273  wins=   97  losses=  166  timeouts=   10  wr=35.5%  pf=1.27  E=2.24p  net=612.4p
  TYPE_A   ALL      n= 2,484  wins=  907  losses= 1472  timeouts=  105  wr=36.5%  pf=1.37  E=2.95p  net=7333.7p

  TYPE_B   DEV      n=11,077  wins= 2466  losses= 8220  timeouts=  391  wr=22.3%  pf=0.67  E=-3.28p  net=-36331.5p
  TYPE_B   HOLDOUT  n= 3,891  wins=  882  losses= 2828  timeouts=  181  wr=22.7%  pf=0.70  E=-2.92p  net=-11373.7p
  TYPE_B   OOS      n= 1,464  wins=  334  losses= 1094  timeouts=   36  wr=22.8%  pf=0.67  E=-3.30p  net=-4832.3p
  TYPE_B   ALL      n=16,432  wins= 3682  losses=12142  timeouts=  608  wr=22.4%  pf=0.68  E=-3.20p  net=-52537.5p

  NONE     DEV      n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p
  NONE     HOLDOUT  n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p
  NONE     OOS      n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p
  NONE     ALL      n=     0  wins=    0  losses=    0  timeouts=    0  wr=–  pf=–  E=–p  net=0.0p


## Deliverable G — Structural exit (Model 2)

**DEFERRED**.  Per amendment A2 §7, Model 2 (structural invalidation) requires
operator-supplied stop-buffer and target-objective rules; these have not been
provided.  Spec §10 permits deferral.  Model 1 (30/12) results above are the
only exit model executed.


## Deliverable H — HTF context breakdown

HTF is TAG ONLY (amendment A1).  These splits are descriptive, not gates.

### Entry rule: wick

  aligned        DEV      n= 4,284  wins= 1101  losses= 3033  timeouts=  150  wr=25.7%  pf=0.81  E=-1.83p  net=-7829.8p
  countertrend   DEV      n= 4,618  wins= 1191  losses= 3273  timeouts=  154  wr=25.8%  pf=0.82  E=-1.74p  net=-8051.4p
  d1_neutral     DEV      n= 6,689  wins= 1766  losses= 4660  timeouts=  263  wr=26.4%  pf=0.84  E=-1.47p  net=-9847.7p

  aligned        HOLDOUT  n= 1,629  wins=  359  losses= 1200  timeouts=   70  wr=22.0%  pf=0.67  E=-3.29p  net=-5363.7p
  countertrend   HOLDOUT  n= 1,471  wins=  422  losses=  945  timeouts=  104  wr=28.7%  pf=1.02  E=0.18p  net=263.7p
  d1_neutral     HOLDOUT  n= 2,240  wins=  617  losses= 1532  timeouts=   91  wr=27.5%  pf=0.90  E=-0.95p  net=-2123.5p

  aligned        OOS      n=   546  wins=  174  losses=  364  timeouts=    8  wr=31.9%  pf=1.05  E=0.45p  net=243.0p
  countertrend   OOS      n=   533  wins=  149  losses=  377  timeouts=    7  wr=28.0%  pf=0.86  E=-1.29p  net=-689.2p
  d1_neutral     OOS      n= 1,014  wins=  272  losses=  705  timeouts=   37  wr=26.8%  pf=0.85  E=-1.42p  net=-1437.9p

  aligned        ALL      n= 6,459  wins= 1634  losses= 4597  timeouts=  228  wr=25.3%  pf=0.79  E=-2.01p  net=-12950.5p
  countertrend   ALL      n= 6,622  wins= 1762  losses= 4595  timeouts=  265  wr=26.6%  pf=0.86  E=-1.28p  net=-8476.9p
  d1_neutral     ALL      n= 9,943  wins= 2655  losses= 6897  timeouts=  391  wr=26.7%  pf=0.86  E=-1.35p  net=-13409.1p

### Entry rule: close

  aligned        DEV      n= 3,513  wins=  858  losses= 2536  timeouts=  119  wr=24.4%  pf=0.75  E=-2.39p  net=-8400.6p
  countertrend   DEV      n= 3,798  wins=  909  losses= 2761  timeouts=  128  wr=23.9%  pf=0.74  E=-2.54p  net=-9649.3p
  d1_neutral     DEV      n= 5,466  wins= 1335  losses= 3918  timeouts=  213  wr=24.4%  pf=0.76  E=-2.31p  net=-12610.9p

  aligned        HOLDOUT  n= 1,353  wins=  270  losses= 1026  timeouts=   57  wr=20.0%  pf=0.60  E=-4.10p  net=-5553.2p
  countertrend   HOLDOUT  n= 1,193  wins=  321  losses=  785  timeouts=   87  wr=26.9%  pf=0.94  E=-0.58p  net=-688.7p
  d1_neutral     HOLDOUT  n= 1,856  wins=  465  losses= 1328  timeouts=   63  wr=25.1%  pf=0.77  E=-2.20p  net=-4081.2p

  aligned        OOS      n=   460  wins=  128  losses=  324  timeouts=    8  wr=27.8%  pf=0.87  E=-1.24p  net=-571.7p
  countertrend   OOS      n=   444  wins=  103  losses=  333  timeouts=    8  wr=23.2%  pf=0.68  E=-3.17p  net=-1407.4p
  d1_neutral     OOS      n=   833  wins=  200  losses=  603  timeouts=   30  wr=24.0%  pf=0.72  E=-2.69p  net=-2240.9p

  aligned        ALL      n= 5,326  wins= 1256  losses= 3886  timeouts=  184  wr=23.6%  pf=0.72  E=-2.73p  net=-14525.4p
  countertrend   ALL      n= 5,435  wins= 1333  losses= 3879  timeouts=  223  wr=24.5%  pf=0.78  E=-2.16p  net=-11745.4p
  d1_neutral     ALL      n= 8,155  wins= 2000  losses= 5849  timeouts=  306  wr=24.5%  pf=0.76  E=-2.32p  net=-18933.0p


## Deliverable I — Session + level family breakdown

### By session (wick entry rule)

  LONDON       DEV      n= 4,949  wins= 1340  losses= 3564  timeouts=   45  wr=27.1%  pf=0.83  E=-1.66p  net=-8220.5p
  LONDON       HOLDOUT  n= 1,706  wins=  472  losses= 1218  timeouts=   16  wr=27.7%  pf=0.85  E=-1.40p  net=-2386.4p
  LONDON       OOS      n=   802  wins=  235  losses=  546  timeouts=   21  wr=29.3%  pf=0.94  E=-0.51p  net=-411.6p
  LONDON       ALL      n= 7,457  wins= 2047  losses= 5328  timeouts=   82  wr=27.5%  pf=0.85  E=-1.48p  net=-11018.5p

  NY           DEV      n= 5,508  wins= 1431  losses= 3832  timeouts=  245  wr=26.0%  pf=0.85  E=-1.43p  net=-7889.4p
  NY           HOLDOUT  n= 1,910  wins=  505  losses= 1286  timeouts=  119  wr=26.4%  pf=0.89  E=-0.96p  net=-1839.0p
  NY           OOS      n=   397  wins=  105  losses=  262  timeouts=   30  wr=26.4%  pf=0.90  E=-0.93p  net=-370.8p
  NY           ALL      n= 7,815  wins= 2041  losses= 5380  timeouts=  394  wr=26.1%  pf=0.86  E=-1.29p  net=-10099.2p

  ASIA_OTHER   DEV      n= 5,134  wins= 1287  losses= 3570  timeouts=  277  wr=25.1%  pf=0.80  E=-1.87p  net=-9619.0p
  ASIA_OTHER   HOLDOUT  n= 1,724  wins=  421  losses= 1173  timeouts=  130  wr=24.4%  pf=0.81  E=-1.74p  net=-2998.1p
  ASIA_OTHER   OOS      n=   894  wins=  255  losses=  638  timeouts=    1  wr=28.5%  pf=0.87  E=-1.23p  net=-1101.6p
  ASIA_OTHER   ALL      n= 7,752  wins= 1963  losses= 5381  timeouts=  408  wr=25.3%  pf=0.81  E=-1.77p  net=-13718.7p

### By level family (wick entry rule, ALL partitions)

```
    family     n   wr   pf     E       net
M5_SWING_H 12097 0.26 0.83 -1.64 -19790.00
M5_SWING_L  5924 0.26 0.83 -1.58  -9374.45
 D_PIVOT_P  1623 0.27 0.86 -1.35  -2197.15
  ROUND_00   809 0.28 0.89 -1.02   -829.20
  ROUND_50   793 0.28 0.89 -1.02   -809.30
       PDH   412 0.30 0.98 -0.14    -56.90
       PDL   400 0.28 0.89 -1.06   -423.20
D_PIVOT_R1   336 0.24 0.75 -2.48   -833.25
D_PIVOT_S1   306 0.30 0.99 -0.07    -22.20
D_PIVOT_R2   122 0.19 0.54 -4.78   -583.00
D_PIVOT_S2   113 0.30 1.04  0.35     39.80
D_PIVOT_S3    54 0.30 1.04  0.35     18.80
D_PIVOT_R3    35 0.29 1.08  0.68     23.65
```

## Deliverable J — Chronological validation

Rules frozen at Stage 0 (commit c2dd613 → tag stage0-frozen).
Measurement partitions: DEV = 2024-01-01…2025-06-30, HOLDOUT = 2025-07-01…2025-12-31, OOS = 2026-01-01…2026-03-31.

Point estimates + 95% CI from a day-clustered bootstrap (1,000 iterations).

### Expectancy (pips / trade) — wick entry, all sweep types

  DEV      n=15,591  E = -1.65p  CI95 = [-2.15, -1.12]
  HOLDOUT  n=5,340  E = -1.35p  CI95 = [-2.21, -0.43]
  OOS      n=2,093  E = -0.90p  CI95 = [-2.10, +0.29]

### Win rate — wick entry, all sweep types

  DEV      n=15,591  WR = 26.0%  CI95 = [24.8%, 27.3%]
  HOLDOUT  n=5,340  WR = 26.2%  CI95 = [24.2%, 28.5%]
  OOS      n=2,093  WR = 28.4%  CI95 = [25.4%, 31.3%]

### Expectancy by sweep type and partition (wick entry)

  TYPE_A   DEV      n=1,733  E = +8.22p  CI95 = [+6.94, +9.41]
  TYPE_A   HOLDOUT  n=  527  E = +6.09p  CI95 = [+3.62, +8.48]
  TYPE_A   OOS      n=  274  E = +7.50p  CI95 = [+5.57, +9.75]

  TYPE_B   DEV      n=13,858  E = -2.88p  CI95 = [-3.41, -2.37]
  TYPE_B   HOLDOUT  n=4,813  E = -2.17p  CI95 = [-3.04, -1.23]
  TYPE_B   OOS      n=1,819  E = -2.17p  CI95 = [-3.40, -0.89]

### Caveat
DEV/HOLDOUT use BID basis (candles_ext_v2); OOS uses MID basis (candles). A sign change between HOLDOUT and OOS cannot be unambiguously attributed to market behaviour vs measurement-basis change.  See `implementation_notes.md` §3 and the spec §11 explicit investigation request.

## Deliverable K — Verdict + §13 answers

### 1. How many genuine sweep events occur?
30,996 approach-episodes classified Type A or Type B across the 643 authorised days.

### 2. How many occur at PDH/PDL?
1,124 (3.6%).  Note: when PDH/PDL overlap an M5 swing within 5 pips the swing (higher priority) becomes the cluster anchor and PDH/PDL appears in confluence — see confluence column.

### 3. How many occur at 00/50 levels?
2,179 (7.0%).  Same confluence caveat.

### 4. How many occur at pivot levels?
3,415 (11.0%).

### 5. What proportion confirm on M5?
wick: 74.3%; close (strict): 61.0% of qualifying sweeps.

### 6. How long does confirmation take?
median 5.0 min from rejection timestamp to wick confirmation.

### 7. How far does price move before entry?
By construction the wick entry fills at the rejection extreme — same bar's extreme; price has already moved by the rejection depth.  See `mae_pips` for pre-entry adverse.

### 8. How much favourable movement remains?
mean MFE (wick): 15.66 pips.  Milestones: 10 p 53.9%, 15 p 42.7%, 20 p 35.4%, 30 p 26.5%.

### 9. How often does the confirmed sweep fail?
SL rate on Model 1 30/12 (wick): 69.9% (16089/23024).

### 10. Are immediate sweeps more tradeable than delayed failed breakouts?
Type A (wick, Model 1): n= 2,534  wins= 1203  losses= 1213  timeouts=  118  wr=47.5%  pf=2.19  E=7.70p  net=19516.3p
     Type B (wick, Model 1): n=20,490  wins= 4848  losses=14876  timeouts=  766  wr=23.7%  pf=0.73  E=-2.65p  net=-54352.8p

### 11. Does Daily/H4 alignment affect results?
aligned-vs-D1: n= 6,459  wins= 1634  losses= 4597  timeouts=  228  wr=25.3%  pf=0.79  E=-2.01p  net=-12950.5p
     countertrend-vs-D1: n= 6,622  wins= 1762  losses= 4595  timeouts=  265  wr=26.6%  pf=0.86  E=-1.28p  net=-8476.9p
     (HTF is tag only — no filtering applied; see §H for full breakdown.)

### 12. Does session timing affect results?
See §I session breakdown.  Key: compare LONDON vs NY vs ASIA_OTHER rows.

### 13. Does the strategy demonstrate positive expectancy after costs?
**Aggregate (TYPE_A + TYPE_B combined, wick, Model 1): NO** — E = -1.51 pips/trade after 0.9 p spread + 0.5 p stop slippage.
     **TYPE_A alone (immediate sweeps): YES** — E = 7.70 pips/trade across 2,534 trades at WR 47.5%, PF 2.19.
     **TYPE_B alone (delayed failed breakouts): NO** — E = -2.65 pips/trade; this cohort drowns out TYPE_A in the aggregate because it is ~8× larger.

### 14. Does it survive chronological validation?
**TYPE_A chronological:**
     DEV (1,733): E = 8.22p, WR 49.0%, PF 2.30
     HOLDOUT (527): E = 6.09p, WR 42.5%, PF 1.89
     OOS (274): E = 7.50p, WR 47.4%, PF 2.15
     All three partitions have CI95 strictly above 0 (see §J).  **Yes — TYPE_A survives chronological validation.**  Caveat: HOLDOUT→OOS basis change from BID to MID; see §J caveat.

### 15. What, specifically, distinguishes successful trades from failures?
Deferred to a successor report — the current pipeline reports per-cell expectancy by sweep-type × session × family × trade-vs-D1 but does not run a formal feature-importance analysis.  Within the published tables, scan for cells with net > 0 at n ≥ 100 as the natural starting point.

### 16. Did Stage 1 miss potentially tradeable sweep events because of its candidate selection or event definition?
YES.  Stage 1's 9,349-row pool is a wick-rejection pre-selected subset.  This research scanned 58,922 independent approach episodes — +49,573 relative to the Stage 1 pool.  Of those, 30,996 qualify as Type A/B sweeps by the corrected spec's definitions.  See §C and §F for the per-cohort outcome; comparisons to Stage 1's taxonomy are preserved in the per-level-family and per-partition breakdowns.
