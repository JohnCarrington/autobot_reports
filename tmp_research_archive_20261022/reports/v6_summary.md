# SLR v6 — real continuation adapter wired in

## 1. v4 / v5 / v6 — headline comparison

| | DEV PF | DEV net | HOLDOUT PF | HOLDOUT net | OOS PF | OOS net |
|---|---:|---:|---:|---:|---:|---:|
| **v4** | 0.822 | -927 | 1.056 | +99 | 1.086 | +59 |
| **v5** | 0.884 | -622 | 1.139 | +233 | 0.765 | -195 |
| **v6** | 0.957 | -222 | 1.060 | +102 | 0.772 | -188 |

## 2. v6 trigger attribution

| Partition | n total | REJ n | REJ PF | REJ net | CONT n | CONT PF | CONT net |
|---|---:|---:|---:|---:|---:|---:|---:|
| DEV | 604 | 581 | 0.978 | -108.2 | 23 | 0.513 | -114.1 |
| HOLDOUT | 207 | 204 | 1.029 | +49.6 | 3 | 8.053 | +52.9 |
| OOS | 94 | 91 | 0.794 | -164.9 | 3 | 0.045 | -23.4 |

## 3. Confusion matrix — physical classification vs AutoBot decision


### DEV
| Physical | AutoBot decisions |
|---|---|
| REJECTION (n=172) | REJECTION wrong-dir: 56, REJECTION ✓ TP: 46, REJECTION right-dir LOSS: 42, Missed: 20, CONTINUATION wrong-dir: 4, CONTINUATION ✓ TP: 2, CONTINUATION right-dir LOSS: 2 |
| CONTINUATION (n=276) | REJECTION wrong-dir: 110, REJECTION right-dir LOSS: 58, Missed: 56, REJECTION ✓ TP: 39, CONTINUATION wrong-dir: 7, CONTINUATION right-dir LOSS: 4, CONTINUATION ✓ TP: 2 |
| OTHER (n=14) | REJECTION wrong-dir: 6, Missed: 4, REJECTION right-dir LOSS: 2, REJECTION ✓ TP: 2 |

### HOLDOUT
| Physical | AutoBot decisions |
|---|---|
| REJECTION (n=60) | REJECTION wrong-dir: 24, REJECTION ✓ TP: 15, REJECTION right-dir LOSS: 15, Missed: 5, CONTINUATION ✓ TP: 1 |
| CONTINUATION (n=90) | REJECTION wrong-dir: 42, Missed: 22, REJECTION right-dir LOSS: 15, REJECTION ✓ TP: 11 |
| OTHER (n=7) | REJECTION wrong-dir: 3, REJECTION ✓ TP: 2, CONTINUATION ✓ TP: 1, REJECTION right-dir LOSS: 1 |

### OOS
| Physical | AutoBot decisions |
|---|---|
| REJECTION (n=27) | REJECTION wrong-dir: 10, REJECTION ✓ TP: 10, REJECTION right-dir LOSS: 6, CONTINUATION right-dir LOSS: 1 |
| CONTINUATION (n=36) | REJECTION wrong-dir: 18, REJECTION right-dir LOSS: 10, REJECTION ✓ TP: 7, CONTINUATION wrong-dir: 1 |
| OTHER (n=3) | REJECTION right-dir LOSS: 2, REJECTION wrong-dir: 1 |

## 4. v6 opportunity capture

| Partition | London avail ≥30p | London captured | % | NY avail ≥30p | NY captured | % | both avail | both captured | % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 156 | 21 | 13.5% | 306 | 70 | 22.9% | 139 | 3 | 2.2% |
| HOLDOUT | 53 | 14 | 26.4% | 104 | 16 | 15.4% | 45 | 4 | 8.9% |
| OOS | 41 | 10 | 24.4% | 25 | 7 | 28.0% | 22 | 3 | 13.6% |

## 5. Captured vs available pips

| Partition | avail mean/med | capt mean/med | ratio |
|---|---|---|---:|
| DEV | 66.6/66.5 | -0.5/-12.0 | -0.7% |
| HOLDOUT | 71.1/64.1 | 0.7/-12.0 | 1.0% |
| OOS | 76.5/77.5 | -3.3/-10.9 | -4.3% |

## 6. v6 full headline

| Partition | Days | Trades | /day | TP | SL | WR | Net | PF | MDD | %pos | %≥30p | %≥60p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 447 | 604 | 1.35 | 155 | 422 | 25.7% | -222 | 0.957 | 530 | 34% | 14% | 3% |
| HOLDOUT | 139 | 207 | 1.49 | 58 | 140 | 28.0% | +102 | 1.060 | 196 | 38% | 14% | 4% |
| OOS | 57 | 94 | 1.65 | 19 | 65 | 20.2% | -188 | 0.772 | 261 | 32% | 11% | 5% |
