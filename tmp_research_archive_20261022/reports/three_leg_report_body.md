# BB_BOUNCE GBPUSD three-leg convergence audit  (2026-06-01 → 2026-08-04)

**Top line.** *3-of-3 pass does not concentrate winners.* WR at 3-of-3 is essentially the same as at 0/1/2 legs passed; net pips is negative at 3-of-3. See §2 and §3.

**MACD and H1 legs are RECONSTRUCTED from 5m candle archives, not fire-time stamps.**

## Setup
- Corpus: 154 scored `GBPUSD_BB_BOUNCE_S/L` fires in signal_log.jsonl. Class labels: **BIG25** (total_pnl_pips ≥ +25, n=15), **W** (0 < total_pnl_pips < 25, n=82), **L** (total_pnl_pips ≤ 0, n=57).
- 5m candles: `/opt/tradingbot/data/candles/GBPUSD/{date}.csv` — columns `timestamp,open,high,low,close`, ×10000 scale, bar-*open* timestamps (UTC). A bar's close time = open+5min.
- **H1 archive**: `/opt/tradingbot/data/ohlc/GBPUSD/1H/` only extends to 2026-04-10. The whole corpus is after that date, so **H1 bars are resampled from the 5m daily files** (group by UTC hour; H1 close = close of the last 5m bar in that hour). An H1 bar is considered *completed* only if `hour_start + 1h ≤ fire_ts`.
- Seed: for each fire, concatenate the fire's day + up to 6 prior calendar days of 5m bars, then keep only bars whose close ≤ fire_ts. That gives ≥100 prior 5m closes for every fire (checked: no MACD-insufficient fires).

## Legs (as specified)
- **MACD leg** — standard MACD(12,26,9) on 5m closes. EMAs seeded from first available value (simple recursive EMA over the concatenated multi-day series). PASS ↔ histogram is direction-aligned *and improving*: BUY needs `hist[t-1] > hist[t-2]`, SELL needs `hist[t-1] < hist[t-2]`. `t-1` = last completed 5m bar. (Note: this definition alone does not require sign-agreement, only monotonic move in the correct direction over the two most-recent completed histogram values.)
- **H1 leg** — EMA(7,13,21) of completed H1 closes. FAIL only if the stack is *cleanly opposed* to the fire (BUY with e7<e13<e21; SELL with e7>e13>e21). Otherwise PASS.
- **Time leg** — fire hour ∈ {06,07,08,10,11,12,14,15,16,18} UTC.

## Flags
- MACD insufficient (fewer than 27 prior 5m closes available): **0**.
- H1 insufficient (fewer than 21 completed prior H1 bars): **0**.
- Known 5m gap on **2026-07-17 12:00 → 12:20** (missing 5m bars). Fires on 07-17 before 12:20 are unaffected; fires after use the surrounding bars — noted in prior audits, not re-flagged here.
- 5m gaps handled implicitly by keeping bars strictly whose close ≤ fire_ts. Weekend gap (no Fri/Sat/Sun bars) is bridged by the 6-day lookback.

## §1. Per-fire table

Columns: `#  date  time  dir  realised  class  MACD-leg (h[t-2]→h[t-1])  H1-leg (e7 / e13 / e21)  T-leg  legs_passed`.
EMA values ×10000. MACD hist values ×10000 too (i.e., raw scale of closes).

```
  #  date        time      dir       pnl  class   MACD    h[t-2]    h[t-1]   H1           e7        e13        e21   T     #pass
--------------------------------------------------------------------------------------------------------------------------------
  1  2026-06-01  06:15:03  SELL   -10.60  L       PASS     0.417     0.353   fail  13456.190  13454.082  13450.783   PASS      2
  2  2026-06-01  07:05:01  SELL   +10.15  W       PASS     0.557     0.460   fail  13460.230  13456.692  13452.743   PASS      2
  3  2026-06-01  07:55:02  BUY    +10.55  W       PASS    -1.260    -1.006   PASS  13460.230  13456.692  13452.743   PASS      3
  4  2026-06-01  09:55:13  BUY    -16.05  L       PASS    -1.213    -1.058   PASS  13462.939  13459.191  13455.040   fail      2
  5  2026-06-01  12:15:03  SELL   +27.90  BIG25   PASS     0.378     0.215   fail  13463.197  13460.665  13457.038   PASS      2
  6  2026-06-01  13:40:03  BUY    -10.50  L       PASS    -3.861    -3.462   PASS  13463.335  13461.105  13457.648   fail      2
  7  2026-06-01  15:40:01  SELL   -14.80  L       PASS     3.680     3.490   PASS  13447.748  13452.054  13452.271   PASS      3
  8  2026-06-02  06:45:02  SELL   +16.65  W       PASS     1.374     0.966   fail  13458.850  13457.670  13456.648   PASS      2
  9  2026-06-02  09:15:03  BUY     +6.95  W       PASS    -0.775    -0.485   PASS  13465.209  13462.401  13460.146   fail      2
 10  2026-06-02  14:00:04  BUY    +10.25  W       PASS    -0.623    -0.584   PASS  13469.884  13467.159  13464.341   PASS      3
 11  2026-06-02  14:50:02  SELL   +15.55  W       fail     0.781     0.860   fail  13469.884  13467.159  13464.341   PASS      1
 12  2026-06-03  06:05:03  BUY    -10.50  L       PASS    -0.751    -0.687   fail  13459.896  13462.097  13462.991   PASS      2
 13  2026-06-03  06:30:05  BUY     -0.40  L       PASS    -1.635    -1.504   fail  13459.896  13462.097  13462.991   PASS      2
 14  2026-06-03  07:50:03  SELL   +35.20  BIG25   fail     1.819     1.917   PASS  13457.434  13460.376  13461.815   PASS      2
 15  2026-06-03  12:45:05  BUY    -12.10  L       PASS    -2.219    -1.925   fail  13451.244  13454.445  13457.097   PASS      2
 16  2026-06-03  14:55:02  BUY    -10.60  L       PASS     0.216     0.657   fail  13441.734  13447.877  13452.354   PASS      2
 17  2026-06-03  15:05:03  SELL   +20.20  W       PASS     1.236     1.090   PASS  13440.463  13446.273  13450.927   PASS      3
 18  2026-06-04  06:50:02  SELL    +8.75  W       PASS     0.394     0.024   PASS  13426.755  13427.515  13431.105   PASS      3
 19  2026-06-04  08:40:02  SELL   -14.70  L       PASS     1.184     0.937   PASS  13425.865  13426.820  13430.041   PASS      3
 20  2026-06-04  09:45:16  SELL   -10.60  L       PASS     0.926     0.815   PASS  13426.911  13427.282  13430.042   fail      2
 21  2026-06-04  11:35:02  SELL   +20.00  W       PASS     1.743     1.388   PASS  13432.941  13430.779  13431.833   PASS      3
 22  2026-06-04  13:20:01  BUY    -11.60  L       PASS    -1.387    -1.350   PASS  13443.382  13437.708  13436.190   fail      2
 23  2026-06-04  15:00:03  BUY    -10.60  L       PASS    -1.153    -0.682   PASS  13445.049  13440.287  13438.158   PASS      3
 24  2026-06-05  06:30:04  BUY    +38.00  BIG25   PASS    -0.564    -0.353   fail  13426.165  13427.220  13428.840   PASS      2
 25  2026-06-05  07:45:04  SELL   -11.40  L       PASS     1.279     1.046   PASS  13428.586  13428.453  13429.477   PASS      3
 26  2026-06-05  09:20:05  SELL   -11.20  L       PASS     0.286     0.251   fail  13438.370  13434.336  13433.123   fail      1
 27  2026-06-05  10:40:14  SELL   +21.75  W       PASS     1.087     0.911   fail  13444.890  13438.638  13435.971   PASS      2
 28  2026-06-05  13:05:04  BUY    -20.00  L       PASS    -6.487    -6.316   PASS  13443.286  13441.105  13438.637   fail      2
 29  2026-06-09  13:55:02  SELL   +30.65  BIG25   PASS    -0.691    -0.815   fail  13387.819  13376.526  13371.252   fail      1
 30  2026-06-10  09:25:02  BUY    +17.45  W       PASS    -0.624    -0.515   PASS  13385.527  13383.443  13381.268   fail      2
 31  2026-06-10  11:15:20  BUY    -15.20  L       PASS    -1.781    -1.414   PASS  13388.931  13386.114  13383.409   PASS      3
 32  2026-06-10  11:45:19  BUY    +29.75  BIG25   fail    -1.587    -1.670   PASS  13388.931  13386.114  13383.409   PASS      2
 33  2026-06-10  13:55:04  SELL   +17.35  W       PASS     2.809     2.348   fail  13387.083  13385.648  13383.546   fail      1
 34  2026-06-11  06:15:05  BUY     +1.95  W       PASS    -1.212    -0.981   PASS  13378.855  13378.594  13379.383   PASS      3
 35  2026-06-11  07:35:03  SELL   +33.25  BIG25   PASS     1.226     1.146   PASS  13378.654  13378.516  13379.262   PASS      3
 36  2026-06-11  09:00:04  BUY    -10.05  L       PASS    -1.829    -1.817   fail  13375.690  13376.917  13378.133   fail      1
 37  2026-06-16  12:00:03  BUY    +16.70  W       PASS    -1.496    -1.307   PASS  13416.557  13414.922  13415.728   PASS      3
 38  2026-06-16  14:40:02  BUY    +24.30  W       PASS    -0.507    -0.375   PASS  13415.073  13414.503  13415.328   PASS      3
 39  2026-06-16  15:05:01  SELL   -10.90  L       fail     1.557     1.728   PASS  13418.092  13416.310  13416.402   PASS      2
 40  2026-06-16  16:05:02  SELL   +11.05  W       PASS     1.483     1.444   fail  13422.782  13419.244  13418.261   PASS      2
 41  2026-06-17  08:05:10  SELL    +8.55  W       PASS     1.111     1.036   PASS  13423.990  13424.749  13424.183   PASS      3
 42  2026-06-17  11:40:01  BUY    +10.85  W       PASS    -0.992    -0.976   fail  13418.911  13421.304  13422.036   PASS      2
 43  2026-06-17  13:05:02  SELL   +16.35  W       PASS     1.280     1.078   PASS  13415.234  13418.353  13419.953   fail      2
 44  2026-06-18  06:05:03  BUY    +14.75  W       PASS    -1.261    -0.670   fail  13310.643  13322.614  13339.867   PASS      2
 45  2026-06-18  06:40:11  SELL   +27.60  BIG25   PASS     1.894     1.699   PASS  13310.643  13322.614  13339.867   PASS      3
 46  2026-06-18  13:45:05  SELL   +21.45  W       fail     1.764     1.774   PASS  13247.964  13270.822  13294.766   fail      1
 47  2026-06-19  13:00:02  SELL   +20.75  W       fail     0.068     0.329   PASS  13224.176  13218.434  13222.162   fail      1
 48  2026-06-19  13:30:02  BUY    -10.50  L       PASS    -0.810    -0.778   PASS  13224.176  13218.434  13222.162   fail      2
 49  2026-06-19  13:55:01  BUY    +11.45  W       PASS    -1.386    -1.010   PASS  13224.176  13218.434  13222.162   fail      2
 50  2026-06-19  14:55:04  SELL   -12.80  L       PASS     1.693     1.178   PASS  13223.194  13218.693  13221.988   PASS      3
 51  2026-06-22  08:25:01  BUY     +6.15  W       PASS    -1.159    -0.244   fail  13207.794  13211.325  13214.295   PASS      2
 52  2026-06-22  13:50:02  BUY    +16.75  W       fail    -2.920    -3.071   PASS  13232.697  13225.370  13222.560   fail      1
 53  2026-06-22  15:10:01  SELL   +21.25  W       PASS     1.488     1.413   fail  13241.414  13232.396  13227.584   PASS      2
 54  2026-06-23  06:30:01  SELL    +7.95  W       PASS     0.866     0.646   fail  13243.588  13243.393  13240.900   PASS      2
 55  2026-06-23  06:55:01  BUY    +18.45  W       PASS    -0.796    -0.768   PASS  13243.588  13243.393  13240.900   PASS      3
 56  2026-06-23  07:15:01  SELL   +28.15  BIG25   fail     0.665     1.037   PASS  13241.328  13242.130  13240.323   PASS      2
 57  2026-06-23  08:00:01  BUY    -10.20  L       fail    -1.736    -1.800   PASS  13237.734  13239.962  13239.107   PASS      2
 58  2026-06-23  10:10:01  SELL   +17.65  W       PASS     1.688     1.238   PASS  13232.691  13236.226  13236.786   PASS      3
 59  2026-06-24  06:20:02  SELL   +19.05  W       PASS     1.104     0.826   PASS  13196.356  13198.913  13203.559   PASS      3
 60  2026-06-24  07:20:02  BUY    +14.95  W       PASS    -1.698    -1.458   fail  13193.929  13197.161  13202.022   PASS      2
 61  2026-06-24  08:20:02  BUY    +15.55  W       fail    -0.967    -1.087   fail  13192.210  13195.716  13200.661   PASS      1
 62  2026-06-24  12:00:19  SELL   +29.30  BIG25   PASS     2.339     2.044   PASS  13175.918  13183.869  13191.175   PASS      3
 63  2026-06-24  15:00:03  BUY    +25.50  BIG25   PASS    -1.477    -1.284   fail  13162.627  13172.490  13181.734   PASS      2
 64  2026-06-24  15:35:02  SELL   -20.35  L       PASS     1.932     1.910   PASS  13162.627  13172.490  13181.734   PASS      3
 65  2026-06-25  06:15:01  BUY    -10.60  L       PASS    -0.766    -0.552   PASS  13175.258  13172.758  13173.775   PASS      3
 66  2026-06-25  07:45:06  SELL   -10.50  L       PASS     0.804     0.707   PASS  13174.906  13172.914  13173.782   PASS      3
 67  2026-06-25  08:05:02  SELL   -10.40  L       PASS     1.113     1.089   PASS  13177.517  13174.690  13174.833   PASS      3
 68  2026-06-25  09:55:04  BUY    -10.70  L       PASS    -0.993    -0.913   PASS  13180.700  13176.913  13176.235   fail      2
 69  2026-06-25  12:55:02  SELL   -20.00  L       PASS     3.841     3.749   PASS  13172.949  13173.830  13174.477   PASS      3
 70  2026-06-25  14:10:02  SELL   +20.65  W       fail     1.919     2.124   fail  13177.643  13176.335  13175.972   PASS      1
 71  2026-06-25  15:15:01  SELL   +17.20  W       PASS    -0.183    -0.639   fail  13183.520  13179.880  13178.261   PASS      2
 72  2026-06-26  07:45:02  SELL   -20.00  L       fail     0.597     0.989   fail  13197.202  13195.280  13192.723   PASS      1
 73  2026-06-26  09:55:04  SELL   +15.85  W       PASS     0.786     0.766   fail  13203.567  13199.552  13195.933   fail      1
 74  2026-06-26  12:00:03  BUY    +15.15  W       PASS    -1.074    -0.947   PASS  13212.537  13206.844  13201.747   PASS      3
 75  2026-06-26  14:30:02  SELL   +26.65  BIG25   PASS     1.383     1.008   fail  13215.230  13209.863  13204.571   PASS      2
 76  2026-06-29  08:35:04  BUY    +19.85  W       PASS    -2.094    -1.721   PASS  13209.469  13206.662  13205.102   PASS      3
 77  2026-06-29  09:45:01  SELL   -20.20  L       PASS     0.750     0.589   fail  13208.964  13206.774  13205.315   fail      1
 78  2026-06-29  12:40:02  SELL   -19.75  L       PASS     0.439     0.070   fail  13218.472  13213.464  13210.109   PASS      2
 79  2026-06-29  15:40:02  SELL    +8.45  W       PASS     0.341     0.297   fail  13230.714  13222.959  13217.261   PASS      2
 80  2026-06-30  06:05:01  BUY    +19.35  W       fail    -0.119    -0.272   PASS  13236.099  13239.359  13237.474   PASS      2
 81  2026-06-30  08:25:02  BUY     +8.65  W       PASS    -2.024    -1.787   PASS  13236.821  13239.000  13237.586   PASS      3
 82  2026-06-30  10:45:01  SELL    +9.45  W       PASS     0.202     0.163   PASS  13235.584  13237.623  13236.917   PASS      3
 83  2026-06-30  11:30:02  BUY    +21.15  W       fail    -1.173    -1.204   PASS  13235.650  13237.370  13236.820   PASS      2
 84  2026-06-30  15:05:02  SELL   +14.85  W       fail     3.874     3.878   fail  13238.288  13237.115  13236.460   PASS      1
 85  2026-07-01  06:50:01  BUY    +17.55  W       PASS    -0.783    -0.455   PASS  13242.379  13244.449  13244.449   PASS      3
 86  2026-07-01  09:35:01  SELL   -11.40  L       PASS     0.230     0.227   PASS  13243.955  13244.620  13244.542   fail      2
 87  2026-07-01  16:20:01  SELL    +8.55  W       PASS     0.543     0.417   fail  13261.168  13255.099  13251.586   PASS      2
 88  2026-07-03  06:55:01  SELL   +12.75  W       PASS     0.577     0.178   fail  13359.124  13353.858  13345.651   PASS      2
 89  2026-07-03  08:45:01  BUY    -13.95  L       PASS    -0.771    -0.746   PASS  13363.960  13358.160  13349.882   PASS      3
 90  2026-07-03  13:15:01  BUY     +4.15  W       fail    -0.770    -0.846   PASS  13357.984  13357.079  13352.264   fail      1
 91  2026-07-03  15:05:02  SELL   +16.95  W       PASS     0.924     0.725   PASS  13356.050  13356.077  13352.424   PASS      3
 92  2026-07-06  08:05:02  SELL   +15.15  W       PASS     1.406     1.072   PASS  13343.075  13345.420  13347.141   PASS      3
 93  2026-07-06  10:30:02  SELL   -13.35  L       PASS     1.100     0.898   PASS  13340.233  13343.095  13345.327   PASS      3
 94  2026-07-07  08:45:01  SELL   +19.65  W       PASS     1.406     1.134   fail  13384.554  13383.656  13379.061   PASS      2
 95  2026-07-07  12:40:02  SELL    +8.35  W       PASS    -0.050    -0.195   fail  13385.906  13384.978  13381.433   PASS      2
 96  2026-07-07  13:35:02  BUY    -17.75  L       PASS    -0.681    -0.450   PASS  13385.767  13385.031  13381.789   fail      2
 97  2026-07-08  08:35:02  BUY    -20.00  L       PASS    -2.197    -2.092   fail  13359.433  13360.010  13362.697   PASS      2
 98  2026-07-08  13:55:02  SELL    +8.85  W       PASS     2.822     2.093   PASS  13345.298  13349.789  13354.481   fail      2
 99  2026-07-08  15:25:03  BUY    +38.00  BIG25   PASS    -1.817    -1.712   PASS  13356.808  13355.571  13357.447   PASS      3
100  2026-07-15  07:30:01  BUY    -19.85  L       fail    -1.182    -1.264   PASS  13406.242  13403.532  13403.535   PASS      2
101  2026-07-15  09:45:01  BUY    +22.25  W       PASS    -0.091    -0.023   PASS  13402.952  13402.314  13402.755   fail      2
102  2026-07-15  11:15:04  SELL   -17.35  L       PASS     2.163     2.020   PASS  13399.757  13400.461  13401.441   PASS      3
103  2026-07-15  13:15:01  SELL   -22.05  L       PASS     2.171     1.640   fail  13408.767  13405.578  13404.572   fail      1
104  2026-07-15  15:10:01  SELL   -20.05  L       PASS     2.803     2.318   fail  13432.297  13420.363  13414.322   PASS      2
105  2026-07-15  16:35:01  SELL   -19.75  L       fail     0.021     0.024   fail  13448.260  13431.189  13421.761   PASS      1
106  2026-07-16  08:35:01  BUY    -20.05  L       PASS    -1.632    -1.260   PASS  13533.140  13525.489  13510.098   PASS      3
107  2026-07-16  09:45:02  BUY    -21.75  L       PASS    -1.035    -0.842   PASS  13530.192  13524.898  13511.121   fail      2
108  2026-07-16  15:15:03  BUY    -19.55  L       PASS    -3.107    -2.613   PASS  13505.231  13510.438  13506.892   PASS      3
109  2026-07-16  16:35:01  BUY    +13.35  W       PASS    -0.948    -0.780   PASS  13499.611  13506.483  13504.697   PASS      3
110  2026-07-17  08:25:02  BUY    -19.55  L       PASS    -2.090    -2.013   fail  13465.904  13470.671  13476.235   PASS      2
111  2026-07-17  11:10:01  BUY    +13.55  W       PASS    -0.120     0.112   fail  13450.093  13458.976  13467.054   PASS      2
112  2026-07-17  11:45:03  SELL   +13.25  W       PASS     1.802     1.606   PASS  13450.093  13458.976  13467.054   PASS      3
113  2026-07-17  15:40:02  SELL    +8.65  W       PASS    -0.108    -0.239   PASS  13445.435  13451.459  13459.224   PASS      3
114  2026-07-17  16:10:01  BUY    +16.95  W       PASS    -1.117    -1.036   fail  13445.414  13450.586  13457.962   PASS      2
115  2026-07-17  16:35:01  SELL   +13.85  W       fail     0.322     0.367   PASS  13445.414  13450.586  13457.962   PASS      2
116  2026-07-20  06:20:03  BUY    +13.35  W       PASS    -0.732    -0.698   PASS  13460.401  13457.648  13458.054   PASS      3
117  2026-07-20  07:50:02  SELL   +20.75  W       PASS     2.058     1.913   PASS  13459.813  13457.705  13458.054   PASS      3
118  2026-07-20  09:25:02  BUY     +8.15  W       PASS    -1.675    -1.498   PASS  13465.548  13461.801  13460.690   fail      2
119  2026-07-20  10:45:02  SELL   +38.65  BIG25   PASS     1.146     1.145   fail  13464.799  13461.908  13460.859   PASS      2
120  2026-07-20  14:20:02  BUY    -24.65  L       PASS     0.028     0.208   PASS  13460.011  13460.395  13460.269   PASS      3
121  2026-07-20  15:30:01  BUY    +21.25  W       PASS    -2.896    -2.446   fail  13454.921  13457.432  13458.395   PASS      2
122  2026-07-21  06:55:01  SELL    +7.45  W       PASS     0.357     0.163   PASS  13437.112  13437.098  13439.692   PASS      3
123  2026-07-21  10:10:00  BUY    -19.25  L       PASS     0.309     0.397   fail  13434.806  13436.067  13438.323   PASS      2
124  2026-07-21  11:40:01  BUY    -19.85  L       PASS    -0.970    -0.439   fail  13430.192  13433.251  13436.325   PASS      2
125  2026-07-21  12:35:01  BUY    -18.85  L       PASS    -1.697    -1.460   fail  13424.007  13429.279  13433.518   PASS      2
126  2026-07-21  13:50:01  BUY    +21.45  W       PASS    -1.732    -0.852   fail  13415.342  13423.575  13429.503   fail      1
127  2026-07-21  16:25:01  BUY    +16.45  W       PASS     0.067     0.232   fail  13391.762  13405.561  13415.972   PASS      2
128  2026-07-22  06:45:01  BUY    +20.75  W       PASS    -1.508    -1.280   fail  13382.317  13384.574  13390.688   PASS      2
129  2026-07-22  07:40:01  SELL    +8.75  W       PASS     1.518     1.261   PASS  13381.551  13383.814  13389.648   PASS      3
130  2026-07-22  09:35:02  BUY     +7.85  W       PASS    -0.773    -0.437   fail  13379.782  13382.213  13387.609   fail      1
131  2026-07-22  11:15:02  SELL    +6.85  W       PASS     0.535     0.454   PASS  13375.193  13378.792  13384.437   PASS      3
132  2026-07-22  13:50:02  SELL   +13.00  W       PASS     2.500     2.204   PASS  13369.837  13374.657  13380.772   fail      2
133  2026-07-22  15:05:01  BUY     -8.30  L       fail    -1.467    -1.519   fail  13374.149  13376.098  13380.684   PASS      1
134  2026-07-27  07:15:01  BUY    -19.65  L       PASS    -1.341    -1.175   PASS  13350.470  13346.078  13341.668   PASS      3
135  2026-07-27  10:45:01  BUY    -20.10  L       PASS    -0.027     0.119   PASS  13341.235  13341.854  13339.945   PASS      3
136  2026-07-27  13:00:03  BUY    -12.10  L       PASS     0.421     0.713   fail  13326.336  13332.158  13333.931   fail      1
137  2026-07-27  13:55:01  SELL    +9.55  W       PASS     1.190     0.773   PASS  13326.336  13332.158  13333.931   fail      2
138  2026-07-27  16:40:02  SELL   +29.35  BIG25   PASS     1.259     1.202   PASS  13313.758  13322.069  13326.752   PASS      3
139  2026-07-28  06:50:02  SELL   -11.95  L       PASS     1.009     0.858   PASS  13293.187  13296.381  13301.945   PASS      3
140  2026-07-28  08:30:02  SELL   +27.90  BIG25   PASS     0.169     0.156   PASS  13293.821  13295.975  13300.730   PASS      3
141  2026-07-28  11:45:02  SELL   -11.95  L       PASS     1.126     1.048   PASS  13289.091  13292.492  13297.315   PASS      3
142  2026-07-28  14:30:01  BUY    +15.45  W       PASS    -1.116    -1.003   fail  13292.184  13292.905  13296.297   PASS      2
143  2026-07-30  13:50:01  SELL   -20.20  L       fail     2.759     3.645   fail  13370.569  13361.715  13351.764   fail      0
144  2026-07-31  07:00:01  SELL   +13.65  W       PASS     0.946     0.599   fail  13450.522  13447.826  13436.268   PASS      2
145  2026-07-31  08:20:01  BUY    +22.25  W       PASS    -1.143    -1.034   PASS  13451.079  13448.530  13437.767   PASS      3
146  2026-07-31  09:15:01  SELL   +16.75  W       PASS     1.991     1.928   fail  13453.147  13450.076  13439.729   fail      1
147  2026-07-31  13:25:02  BUY    -20.00  L       PASS     0.469     1.293   PASS  13436.999  13441.423  13437.305   fail      2
148  2026-07-31  13:35:01  SELL   +22.75  W       PASS     1.823     1.433   PASS  13436.999  13441.423  13437.305   fail      2
149  2026-08-03  06:10:01  SELL   +18.35  W       PASS     0.435     0.229   fail  13475.944  13475.004  13469.877   PASS      2
150  2026-08-03  10:50:01  SELL   +13.55  W       PASS     1.165     1.043   PASS  13461.963  13466.315  13465.606   PASS      3
151  2026-08-04  06:30:02  SELL   -20.00  L       PASS     0.853     0.768   PASS  13427.087  13430.529  13435.758   PASS      3
152  2026-08-04  13:15:01  BUY     +8.55  W       PASS    -1.275    -1.229   PASS  13440.178  13437.677  13438.264   fail      2
153  2026-08-04  15:25:01  BUY    +12.25  W       PASS    -0.978    -0.914   PASS  13443.216  13440.174  13439.793   PASS      3
154  2026-08-04  16:25:02  SELL    +6.55  W       PASS     0.544     0.371   fail  13446.024  13442.214  13441.126   PASS      2
```

## §2. Count tables

### By legs_passed

```
legs   summary
   0   n=  1  BIG25= 0  W= 0  L= 1  WR=  0.0%  net=  -20.20p
   1   n= 22  BIG25= 1  W=13  L= 8  WR= 63.6%  net= +115.95p
   2   n= 73  BIG25= 8  W=39  L=26  WR= 64.4%  net= +419.55p
   3   n= 58  BIG25= 6  W=30  L=22  WR= 62.1%  net= +261.10p
```

### 3-of-3 vs everything else

```
3/3   n= 58  BIG25= 6  W=30  L=22  WR= 62.1%  net= +261.10p
<3    n= 96  BIG25= 9  W=52  L=35  WR= 63.5%  net= +515.30p
```

### Each leg alone (PASS vs FAIL)

```
MACD  PASS  n=133  BIG25=12  W=71  L=50  WR= 62.4%  net= +608.45p
MACD  fail  n= 21  BIG25= 3  W=11  L= 7  WR= 66.7%  net= +167.95p
H1    PASS  n= 93  BIG25= 9  W=48  L=36  WR= 61.3%  net= +415.15p
H1    fail  n= 61  BIG25= 6  W=34  L=21  WR= 65.6%  net= +361.25p
Time  PASS  n=116  BIG25=14  W=62  L=40  WR= 65.5%  net= +714.75p
Time  fail  n= 38  BIG25= 1  W=20  L=17  WR= 55.3%  net=  +61.65p
```

## §3. BIG25 and worst-loser detail

### The 15 BIG25 fires

```
date        time      dir       pnl  MACD  H1    T     #pass
2026-07-20  10:45:02  SELL   +38.65  PASS  fail  PASS      2
2026-06-05  06:30:04  BUY    +38.00  PASS  fail  PASS      2
2026-07-08  15:25:03  BUY    +38.00  PASS  PASS  PASS      3
2026-06-03  07:50:03  SELL   +35.20  fail  PASS  PASS      2
2026-06-11  07:35:03  SELL   +33.25  PASS  PASS  PASS      3
2026-06-09  13:55:02  SELL   +30.65  PASS  fail  fail      1
2026-06-10  11:45:19  BUY    +29.75  fail  PASS  PASS      2
2026-07-27  16:40:02  SELL   +29.35  PASS  PASS  PASS      3
2026-06-24  12:00:19  SELL   +29.30  PASS  PASS  PASS      3
2026-06-23  07:15:01  SELL   +28.15  fail  PASS  PASS      2
2026-06-01  12:15:03  SELL   +27.90  PASS  fail  PASS      2
2026-07-28  08:30:02  SELL   +27.90  PASS  PASS  PASS      3
2026-06-18  06:40:11  SELL   +27.60  PASS  PASS  PASS      3
2026-06-26  14:30:02  SELL   +26.65  PASS  fail  PASS      2
2026-06-24  15:00:03  BUY    +25.50  PASS  fail  PASS      2
```

BIG25 by legs_passed: {1: 1, 2: 8, 3: 6}

### The 10 worst losers

```
date        time      dir       pnl  MACD  H1    T     #pass
2026-07-20  14:20:02  BUY    -24.65  PASS  PASS  PASS      3
2026-07-15  13:15:01  SELL   -22.05  PASS  fail  fail      1
2026-07-16  09:45:02  BUY    -21.75  PASS  PASS  fail      2
2026-06-24  15:35:02  SELL   -20.35  PASS  PASS  PASS      3
2026-06-29  09:45:01  SELL   -20.20  PASS  fail  fail      1
2026-07-30  13:50:01  SELL   -20.20  fail  fail  fail      0
2026-07-27  10:45:01  BUY    -20.10  PASS  PASS  PASS      3
2026-07-15  15:10:01  SELL   -20.05  PASS  fail  PASS      2
2026-07-16  08:35:01  BUY    -20.05  PASS  PASS  PASS      3
2026-06-05  13:05:04  BUY    -20.00  PASS  PASS  fail      2
```

Worst-10 by legs_passed: {0: 1, 1: 2, 2: 3, 3: 4}
