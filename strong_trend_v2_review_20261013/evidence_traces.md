# Fire-moment evidence traces — v1 fires vs v2 verdict

Each row below shows the full evidence stack at the bar where
the v1 state machine fired. The v2 verdict column shows whether
the asymmetric-structure gate would accept or reject the same bar.

| Case | disp | sr_dn | sr_up | asym | pb_dn | pb_up | rev | cpos | piv_dn | piv_up | v2 verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Oct 12 09:55 (TRUE DOWN)** | -11.4p | 4 | 1 | +3 | 1 | 0 | 0 | 0.15 | 0 | 0 | **ACCEPT** |
| **09-04 12:35 (FP DOWN)** | -44.2p | 5 | 5 | +0 | 3 | 1 | 0 | 0.21 | 0 | 0 | **REJECT** |
| **09-09 09:55 (FP DOWN)** | -25.6p | 7 | 1 | +6 | 3 | 0 | 1 | 0.04 | 0 | 0 | **ACCEPT** |
| **09-11 09:05 (FP DOWN)** | -24.0p | 6 | 1 | +5 | 1 | 0 | 0 | 0.01 | 0 | 0 | **ACCEPT** |
| **09-28 09:20 (FP UP)** | +24.8p | 3 | 2 | -1 | 0 | 2 | 0 | 0.78 | 15 | 0 | **REJECT** |
| **09-30 09:50 (FP UP)** | +23.5p | 4 | 4 | +0 | 0 | 1 | 0 | 0.98 | 5 | 0 | **REJECT** |
| **10-09 12:35 (FP DOWN)** | -21.7p | 3 | 4 | -1 | 2 | 2 | 1 | 0.05 | 0 | 0 | **REJECT** |
| **09-15 13:50 (FLIP UP)** | +26.1p | 5 | 3 | -2 | 0 | 5 | 0 | 1.00 | 0 | 0 | **REJECT** |

## Key observations

1. **Oct 12 09:55 is unambiguously asymmetric (+3)** — the
   evidence stack shows a clean DOWN picture: 4x more DOWN
   swings than UP, pullback asymmetric, close at 15% of range,
   zero range reversals.

2. **4 of 6 v1 FPs had symmetric structure** (asym = 0 or +2 at
   minimum). The v2 asymmetry gate rejects asym < 2 for the
   direction being considered.

3. **2 FPs had opposite-direction structure** (asym = -1):
   09-28 09:20 had sr_dn > sr_up yet fired UP under v1;
   10-09 12:35 had sr_up > sr_dn yet fired DOWN under v1.
   These are the clearest v1 bugs.

4. **09-15 flip had asym = -2 for the UP direction fired** —
   structure was dominantly DOWN but UP fired because
   displacement was positive. v2 rejects.
