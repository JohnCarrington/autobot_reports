# Combinations K1..K5 + TREND_V3 T0 comparison

Cohorts: SUS_N20=338, SUS_N30=194, REV_N20=31, REV_N30=5


## Section 1 - Combination results


### N=20

| Combo | n_sus_fired | n_rev_fired | precision | recall | FPR | discrimination | med_bars | med_pips_cons | med_pips_rem | pctMFE_cons |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| K1 | 44/338 | 3/31 | 0.936 | 0.130 | 0.097 | 0.033 | 11.0 | 22.1 | 11.15 | 75.1 |
| K2 | 75/338 | 9/31 | 0.893 | 0.222 | 0.290 | -0.068 | 5 | 15.45 | 21.95 | 40.5 |
| K3 | 121/338 | 6/31 | 0.953 | 0.358 | 0.194 | 0.164 | 32 | 46.05 | 2.25 | 94.6 |
| K4 | 44/338 | 5/31 | 0.898 | 0.130 | 0.161 | -0.031 | 8.0 | 18.45 | 14.1 | 53.8 |
| K5 | 139/338 | 3/31 | 0.979 | 0.411 | 0.097 | 0.315 | 18 | 28.7 | 7.95 | 75.7 |

### N=30

| Combo | n_sus_fired | n_rev_fired | precision | recall | FPR | discrimination | med_bars | med_pips_cons | med_pips_rem | pctMFE_cons |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| K1 | 28/194 | 0/5 | 1.000 | 0.144 | 0.000 | 0.144 | 11.5 | 25.85 | 21.0 | 58.3 |
| K2 | 43/194 | 2/5 | 0.956 | 0.222 | 0.400 | -0.178 | 5 | 15.45 | 31.05 | 34.3 |
| K3 | 92/194 | 1/5 | 0.989 | 0.474 | 0.200 | 0.274 | 25.0 | 48.05 | 6.35 | 88.4 |
| K4 | 29/194 | 0/5 | 1.000 | 0.149 | 0.000 | 0.149 | 12 | 26.25 | 22.75 | 53.1 |
| K5 | 97/194 | 1/5 | 0.990 | 0.500 | 0.200 | 0.300 | 18 | 34.05 | 13.7 | 70.2 |

## Section 2 - Discrimination ranking (N=20) - combos + single features

| rank | name | type | discrimination | prec | recall | FPR | med_bars | med_pips_rem | pctMFE_cons |
|---:|:---|:---|---:|---:|---:|---:|---:|---:|---:|
| 1 | A3_STRUCT_PROG | single | 0.358 | 0.955 | 0.746 | 0.387 | 18.0 | 10.05 | 71.9 |
| 2 | H2b | h12 | 0.326 | 0.954 | 0.680 | 0.355 | 12.0 | 12.6 | None |
| 3 | K5 | combo | 0.315 | 0.979 | 0.411 | 0.097 | 18 | 7.95 | 75.7 |
| 4 | G3_HTF_ALIGN | single | 0.306 | 0.948 | 0.757 | 0.452 | 18.5 | 15.52 | 56.9 |
| 5 | E3_LEVEL_PROGRESSION | single | 0.256 | 0.942 | 0.772 | 0.516 | 12 | 11.55 | 64.9 |
| 6 | B2_TWO_CLOSES_OUTSIDE | single | 0.225 | 0.936 | 0.902 | 0.677 | 20 | 12.25 | 65.4 |
| 7 | D3_EMA21_SLOPE | single | 0.223 | 0.941 | 0.707 | 0.484 | 20 | 8.05 | 78.6 |
| 8 | G2_ADX_25_DI_ALIGN | single | 0.210 | 0.934 | 0.920 | 0.710 | 16 | 10.95 | 69.3 |
| 9 | H1 | h12 | 0.174 | 0.948 | 0.432 | 0.258 | 5.5 | 16.8 | None |
| 10 | H1_AND_H2 | h12 | 0.174 | 0.951 | 0.399 | 0.226 | 10 | 11.1 | None |
| 11 | K3 | combo | 0.164 | 0.953 | 0.358 | 0.194 | 32 | 2.25 | 94.6 |
| 12 | A2_BOS | single | 0.160 | 0.931 | 0.837 | 0.677 | 6 | 18.55 | 45.4 |
| 13 | D2_PRICE_ABOVE_ALL | single | 0.158 | 0.929 | 0.965 | 0.806 | 14.0 | 15.35 | 57.2 |
| 14 | H1_OR_H2 | h12 | 0.158 | 0.929 | 0.932 | 0.774 | 5 | 17.9 | None |
| 15 | H2 | h12 | 0.158 | 0.930 | 0.899 | 0.742 | 6.0 | 16.8 | None |
| 16 | D4_FAN_WIDTH | single | 0.131 | 0.927 | 0.905 | 0.774 | 16.0 | 12.75 | 67.2 |
| 17 | B4_MIDLINE_SLOPE | single | 0.130 | 0.940 | 0.420 | 0.290 | 24.5 | 4.9 | 90.6 |
| 18 | D1_EMA_ALIGN | single | 0.129 | 0.926 | 0.968 | 0.839 | 14 | 15.45 | 56.5 |
| 19 | C3_EFFICIENCY | single | 0.088 | 0.923 | 0.991 | 0.903 | 10 | 13.95 | 57.8 |
| 20 | B1_FIRST_CLOSE_OUTSIDE | single | 0.079 | 0.922 | 0.982 | 0.903 | 12.0 | 15.85 | 52.3 |
| 21 | E2_LEVEL_ACCEPTANCE | single | 0.064 | 0.921 | 0.935 | 0.871 | 5.0 | 18.85 | 44.3 |
| 22 | C4_ATR_NORM | single | 0.059 | 0.920 | 0.994 | 0.935 | 6.0 | 15.55 | 52.5 |
| 23 | K1 | combo | 0.033 | 0.936 | 0.130 | 0.097 | 11.0 | 11.15 | 75.1 |
| 24 | F2_NO_REJECT_BODY | single | 0.029 | 0.918 | 0.997 | 0.968 | 11 | 18.55 | 43.7 |
| 25 | B5_WIDTH_EXPANSION | single | 0.026 | 0.918 | 0.994 | 0.968 | 12.0 | 13.3 | 58.9 |
| 26 | F1_FAILED_LOW | single | 0.026 | 0.918 | 0.994 | 0.968 | 10.0 | 16.83 | 46.6 |
| 27 | A1_HH_HL_or_LH_LL | single | 0.000 | 0.916 | 1.000 | 1.000 | 9.0 | 16.32 | 46.2 |
| 28 | B3_BAND_WALK | single | 0.000 | 0.916 | 1.000 | 1.000 | 3.0 | 21.23 | 31.7 |
| 29 | C5_ACCELERATION | single | 0.000 | 0.916 | 1.000 | 1.000 | 8.0 | 16.45 | 47.6 |
| 30 | F3_RECLAIM_EXTREME | single | -0.003 | 0.916 | 0.997 | 1.000 | 8 | 17.25 | 45.7 |
| 31 | E1_LEVEL_BREAK | single | -0.004 | 0.916 | 0.932 | 0.935 | 5 | 17.95 | 45.4 |
| 32 | G1_ADX_25 | single | -0.009 | 0.915 | 0.991 | 1.000 | 4 | 21.55 | 24.2 |
| 33 | C1_3_CONSEC_DIR | single | -0.012 | 0.915 | 0.988 | 1.000 | 5.0 | 18.7 | 42.3 |
| 34 | K4 | combo | -0.031 | 0.898 | 0.130 | 0.161 | 8.0 | 14.1 | 53.8 |
| 35 | C2_6BAR_NET | single | -0.042 | 0.912 | 0.893 | 0.935 | 8.0 | 11.5 | 65.7 |
| 36 | K2 | combo | -0.068 | 0.893 | 0.222 | 0.290 | 5 | 21.95 | 40.5 |

## Section 3 - TREND_V3 T0 comparison

- TREND_V3 fires in signal_log: 16
- Sustained events (any N) on/after 2026-09-04: 19
- Sustained events with same-date+direction TREND_V3 fire: 5 (26.3% of after-09-04 sus)
- Median delta_bars (T_TREND_V3 - T_ORIGIN): 44
- Median pips_consumed at T_TREND_V3: 34.1
- Median pct_MFE_consumed at T_TREND_V3: 96.5%
- Median pips_remaining at T_TREND_V3: 1.4
- Sustained trends with >=80% MFE already consumed at TREND_V3: 3 / 5
- Sustained trends with >=100% MFE consumed at TREND_V3 (already peaked, retracing): 1 / 5

### Per-event TREND_V3 detail

| date | dir | mfe_pips | delta_bars | pips_cons | pct_MFE_cons | pips_rem | strategy |
|:---|:---|---:|---:|---:|---:|---:|:---|
| 2026-09-16 | DOWN | 35.35 | 30 | 15.4 | 43.6 | 19.95 | GBPUSD_TREND_V3_UM_S |
| 2026-09-16 | DOWN | 35.35 | 44 | 18.4 | 52.1 | 16.95 | GBPUSD_TREND_V3_UM_S |
| 2026-09-16 | DOWN | 35.35 | 79 | 34.1 | 96.5 | 1.25 | GBPUSD_TREND_V3_UM_S |
| 2026-09-17 | DOWN | 51.3 | 67 | 60.9 | 118.7 | -9.6 | GBPUSD_TREND_V3_S |
| 2026-09-22 | DOWN | 41.6 | 29 | 40.2 | 96.6 | 1.4 | GBPUSD_TREND_V3_S |

## Section 4 - K vs TREND_V3 (matched sustained events only)

| Combo | n_matched | n_K_earlier | median_delta_bars (K-TV3) | median_delta_pips (K-TV3) |
|:---|---:|---:|---:|---:|
| K1 | 1 | 1 | -17 | -20.05 |
| K2 | 1 | 1 | -24 | -28.75 |
| K3 | 5 | 2 | 52 | 37.45 |
| K4 | 1 | 1 | -27 | -34.35 |
| K5 | 2 | 2 | -24.5 | -28.5 |
