# v8 FINAL EVALUATION — frozen variant A (wick ≥ 8p alone)

## 1. Headline across partitions

| Part | Days | ≥30p/day | Trades | /day | TP | SL | WR | Net | Pips/day | PF | MaxDD | Mean entry dist | Median entry dist |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 3.84 | 317 | 0.71 | 76 | 209 | 24.0% | -19 | -0.04 | 0.993 | 542 | +14.0p | +11.9p |
| HOLDOUT | 139 | 3.64 | 76 | 0.55 | 14 | 49 | 18.4% | -88 | -0.63 | 0.860 | 154 | +15.1p | +13.8p |
| OOS | 57 | 4.31 | 52 | 0.91 | 17 | 31 | 32.7% | +168 | +2.95 | 1.443 | 135 | +14.1p | +11.0p |

## 2. Opportunity capture by partition

| Part | Physical ≥30p | TP captured | Capture % |
|---|---:|---:|---:|
| DEV | 1553 | 43 | 2.8% |
| HOLDOUT | 480 | 9 | 1.9% |
| OOS | 237 | 11 | 4.6% |

## 3. Daily P&L distribution per partition

| Part | Negative | 0 (no trade) | 1-29p | 30-59p | 60-89p | ≥90p | %≥30p days | %≥60p days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 111 | 260 | 43 | 30 | 3 | 0 | 7.4% | 0.7% |
| HOLDOUT | 33 | 88 | 11 | 7 | 0 | 0 | 5.0% | 0.0% |
| OOS | 14 | 29 | 9 | 3 | 1 | 1 | 8.8% | 3.5% |

## 4. Missed-reversal classification per partition

For each ≥30p physical reversal NOT captured by a v8 TP in the 30-minute window, classify the reason.


### DEV
Missed reversals: 1503
| reason | n | % |
|---|---:|---:|
| no signal (wick < 8p or BB not pierced) | 988 | 65.7% |
| outside eligible hours | 382 | 25.4% |
| signal fired but SL hit | 110 | 7.3% |
| signal fired, no trade | 23 | 1.5% |

### HOLDOUT
Missed reversals: 468
| reason | n | % |
|---|---:|---:|
| no signal (wick < 8p or BB not pierced) | 313 | 66.9% |
| outside eligible hours | 107 | 22.9% |
| signal fired but SL hit | 41 | 8.8% |
| signal fired, no trade | 7 | 1.5% |

### OOS
Missed reversals: 224
| reason | n | % |
|---|---:|---:|
| no signal (wick < 8p or BB not pierced) | 121 | 54.0% |
| outside eligible hours | 80 | 35.7% |
| signal fired but SL hit | 20 | 8.9% |
| signal fired, no trade | 3 | 1.3% |

## 5. False-trade analysis (SL/EOD losers)


### DEV (218 losing trades)
| reason | n | % |
|---|---:|---:|
| false fire; real reversal in same direction within 2h | 102 | 46.8% |
| no subsequent reversal within 2h | 75 | 34.4% |
| false fire; later reversal was opposite direction | 41 | 18.8% |

### HOLDOUT (53 losing trades)
| reason | n | % |
|---|---:|---:|
| false fire; real reversal in same direction within 2h | 24 | 45.3% |
| no subsequent reversal within 2h | 22 | 41.5% |
| false fire; later reversal was opposite direction | 7 | 13.2% |

### OOS (31 losing trades)
| reason | n | % |
|---|---:|---:|
| false fire; real reversal in same direction within 2h | 22 | 71.0% |
| no subsequent reversal within 2h | 5 | 16.1% |
| false fire; later reversal was opposite direction | 4 | 12.9% |
