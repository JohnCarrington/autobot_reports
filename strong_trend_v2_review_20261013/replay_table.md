# 34-day replay — detailed per-day table (v2)

All data from the live GBPUSD candle archive at /opt/tradingbot/data/candles/GBPUSD.
Day truth independent of session_trend: UP if close >= open + 20p AND close
in top 60% of range; DOWN mirror; RANGE if |close-open| < 20p AND range <= 60p;
NORMAL otherwise.

| date | truth | ST final | first establish | first dir | fire reason |
|---|---|---|---|---|---|
| 2026-09-01 | DOWN | DOWN | 2026-09-01T16:35:00+00:00 | DOWN | `strong_down:struct=[dn=7,up=5,asym=+2]|pullback=[dn=3,up=2]|reversals=1|close_pos=0.16|disp=-14.8p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-02 | DOWN | RANGE | 2026-09-02T10:40:00+00:00 | DOWN | `strong_down:struct=[dn=5,up=3,asym=+2]|pullback=[dn=1,up=0]|reversals=1|close_pos=0.01|disp=-13.3p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-03 | UP | RANGE | — | — | `—` |
| 2026-09-04 | NORMAL | DOWN | 2026-09-04T09:55:00+00:00 | DOWN | `strong_down:struct=[dn=4,up=2,asym=+2]|pullback=[dn=2,up=1]|reversals=0|close_pos=0.04|disp=-19.2p(meaningful)|piv_support=0|persistence_bars=2` |
| 2026-09-06 | RANGE | UNKNOWN | — | — | `—` |
| 2026-09-07 | UP | UP | 2026-09-07T08:35:00+00:00 | UP | `strong_up:struct=[up=3,dn=1,asym=+2]|pullback=[up=1,dn=0]|reversals=1|close_pos=0.71|disp=+12.1p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-08 | RANGE | UNKNOWN | 2026-09-08T08:55:00+00:00 | DOWN | `strong_down:struct=[dn=3,up=1,asym=+2]|pullback=[dn=2,up=0]|reversals=0|close_pos=0.18|disp=-11.0p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-09 | RANGE | DOWN | 2026-09-09T08:25:00+00:00 | DOWN | `strong_down:struct=[dn=3,up=1,asym=+2]|pullback=[dn=2,up=0]|reversals=1|close_pos=0.04|disp=-13.3p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-10 | DOWN | DOWN | 2026-09-10T11:10:00+00:00 | DOWN | `strong_down:struct=[dn=5,up=3,asym=+2]|pullback=[dn=3,up=1]|reversals=1|close_pos=0.12|disp=-24.3p(meaningful)|piv_support=0|persistence_bars=2` |
| 2026-09-11 | RANGE | DOWN | 2026-09-11T08:10:00+00:00 | DOWN | `strong_down:struct=[dn=3,up=1,asym=+2]|pullback=[dn=1,up=0]|reversals=0|close_pos=0.16|disp=-11.7p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-13 | RANGE | UNKNOWN | — | — | `—` |
| 2026-09-14 | NORMAL | RANGE | — | — | `—` |
| 2026-09-15 | DOWN | UNKNOWN | — | — | `—` |
| 2026-09-16 | DOWN | DOWN | 2026-09-16T16:40:00+00:00 | DOWN | `strong_down:struct=[dn=6,up=4,asym=+2]|pullback=[dn=6,up=0]|reversals=2|close_pos=0.14|disp=-31.4p(strong)|piv_support=0|persistence_bars=2` |
| 2026-09-17 | DOWN | RANGE | — | — | `—` |
| 2026-09-18 | UP | UNKNOWN | 2026-09-18T10:45:00+00:00 | DOWN | `strong_down:struct=[dn=4,up=2,asym=+2]|pullback=[dn=2,up=1]|reversals=0|close_pos=0.03|disp=-18.7p(meaningful)|piv_support=0|persistence_bars=2` |
| 2026-09-21 | RANGE | RANGE | — | — | `—` |
| 2026-09-22 | DOWN | RANGE | — | — | `—` |
| 2026-09-23 | DOWN | DOWN | 2026-09-23T09:45:00+00:00 | DOWN | `strong_down:struct=[dn=3,up=1,asym=+2]|pullback=[dn=2,up=0]|reversals=2|close_pos=0.06|disp=-35.1p(strong)|piv_support=0|persistence_bars=2` |
| 2026-09-24 | DOWN | DOWN | 2026-09-24T09:55:00+00:00 | DOWN | `strong_down:struct=[dn=6,up=4,asym=+2]|pullback=[dn=3,up=2]|reversals=2|close_pos=0.15|disp=-14.8p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-25 | UP | UP | 2026-09-25T08:50:00+00:00 | UP | `strong_up:struct=[up=3,dn=1,asym=+2]|pullback=[up=1,dn=0]|reversals=0|close_pos=0.83|disp=+12.8p(small)|piv_support=0|persistence_bars=2` |
| 2026-09-27 | RANGE | RANGE | — | — | `—` |
| 2026-09-28 | NORMAL | UP | 2026-09-28T13:50:00+00:00 | UP | `strong_up:struct=[up=6,dn=4,asym=+2]|pullback=[up=2,dn=0]|reversals=0|close_pos=0.82|disp=+26.3p(strong)|piv_support=0|persistence_bars=2` |
| 2026-09-29 | NORMAL | RANGE | — | — | `—` |
| 2026-09-30 | NORMAL | RANGE | — | — | `—` |
| 2026-10-01 | DOWN | DOWN | 2026-10-01T08:40:00+00:00 | DOWN | `strong_down:struct=[dn=3,up=1,asym=+2]|pullback=[dn=2,up=0]|reversals=2|close_pos=0.00|disp=-47.5p(strong)|piv_support=0|persistence_bars=2` |
| 2026-10-02 | UP | RANGE | 2026-10-02T12:10:00+00:00 | DOWN | `strong_down:struct=[dn=5,up=2,asym=+3]|pullback=[dn=5,up=2]|reversals=1|close_pos=0.02|disp=-13.7p(small)|piv_support=0|persistence_bars=2` |
| 2026-10-04 | RANGE | UNKNOWN | — | — | `—` |
| 2026-10-05 | NORMAL | RANGE | 2026-10-05T08:20:00+00:00 | UP | `strong_up:struct=[up=3,dn=1,asym=+2]|pullback=[up=2,dn=1]|reversals=1|close_pos=0.94|disp=+14.9p(small)|piv_support=11|persistence_bars=2` |
| 2026-10-06 | UP | UP | 2026-10-06T07:55:00+00:00 | UP | `strong_up:struct=[up=3,dn=1,asym=+2]|pullback=[up=2,dn=0]|reversals=1|close_pos=0.88|disp=+20.8p(meaningful)|piv_support=0|persistence_bars=2` |
| 2026-10-07 | DOWN | DOWN | 2026-10-07T08:10:00+00:00 | DOWN | `strong_down:struct=[dn=4,up=1,asym=+3]|pullback=[dn=1,up=0]|reversals=2|close_pos=0.30|disp=-14.7p(small)|piv_support=0|persistence_bars=2` |
| 2026-10-08 | NORMAL | RANGE | — | — | `—` |
| 2026-10-09 | RANGE | UNKNOWN | 2026-10-09T08:25:00+00:00 | UP | `strong_up:struct=[up=4,dn=1,asym=+3]|pullback=[up=2,dn=0]|reversals=0|close_pos=0.82|disp=+10.4p(small)|piv_support=0|persistence_bars=2` |
| 2026-10-12 | DOWN | DOWN | 2026-10-12T09:50:00+00:00 | DOWN | `strong_down:struct=[dn=4,up=1,asym=+3]|pullback=[dn=1,up=0]|reversals=0|close_pos=0.16|disp=-11.2p(small)|piv_support=0|persistence_bars=2` |

## Summary

- **Correct trend classifications:** 11 / 18
- **Direction flips at EOD:** 0
- **False positives:** 4
- **Missed trends:** 7
- **Within-day wrong-direction fires:** 2 (both release before EOD)
