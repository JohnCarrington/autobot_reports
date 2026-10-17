# Stage 2 Phase 5 — Context + session performance

Generated: 2026-10-17T13:57:49.902864+00:00

Context classification (pre-fire 60 min window):
- STRONG_TREND  |net|/path ≥ 0.6 AND |net| ≥ 15p
- WEAK_TREND    |net|/path ≥ 0.3 AND |net| ≥ 8p
- GRIND         |net|/path ≥ 0.3 AND |net| < 8p
- RANGE         |net|/path < 0.3

All numbers are pessimistic ambig = LOSS. E p = expectancy / trade.

## Method A

### By context

| context | n | W | L | A | U | WR | E p |
|---|---:|---:|---:|---:|---:|---:|---:|
| STRONG_TREND | 4605 | 988 | 3066 | 6 | 545 | 24.3% | -0.73 |
| WEAK_TREND | 12654 | 2394 | 8252 | 19 | 1989 | 22.4% | -1.17 |
| GRIND | 4106 | 614 | 2387 | 5 | 1100 | 20.4% | -0.54 |
| RANGE | 13446 | 2326 | 8665 | 36 | 2419 | 21.1% | -1.32 |

### By session (UK-local)

| session | n | WR | E p |
|---|---:|---:|---:|
| pre_london | 0 | 0.0% | +0.00 |
| london_open | 1078 | 22.8% | +0.24 |
| london_am | 10214 | 22.2% | -0.80 |
| late_london | 2770 | 23.7% | -0.32 |
| ny_open | 2428 | 22.2% | -1.09 |
| overlap | 7254 | 20.7% | -2.32 |
| later_ny | 9917 | 22.8% | -0.90 |

## Method B

### By context

| context | n | W | L | A | U | WR | E p |
|---|---:|---:|---:|---:|---:|---:|---:|
| STRONG_TREND | 377 | 87 | 245 | 0 | 45 | 26.2% | -0.05 |
| WEAK_TREND | 1269 | 233 | 899 | 2 | 135 | 20.5% | -2.25 |
| GRIND | 68 | 10 | 48 | 0 | 10 | 17.2% | -2.51 |
| RANGE | 2048 | 415 | 1416 | 5 | 212 | 22.6% | -1.43 |

### By session (UK-local)

| session | n | WR | E p |
|---|---:|---:|---:|
| pre_london | 31 | 20.0% | -2.57 |
| london_open | 71 | 20.3% | -2.31 |
| london_am | 452 | 25.5% | -0.27 |
| late_london | 310 | 21.2% | -2.12 |
| ny_open | 340 | 22.2% | -1.60 |
| overlap | 711 | 18.5% | -3.60 |
| later_ny | 1726 | 23.8% | -0.86 |

## Method C

### By context

| context | n | W | L | A | U | WR | E p |
|---|---:|---:|---:|---:|---:|---:|---:|
| STRONG_TREND | 518 | 115 | 336 | 2 | 65 | 25.4% | -0.23 |
| WEAK_TREND | 1146 | 225 | 792 | 3 | 126 | 22.1% | -1.71 |
| GRIND | 11 | 1 | 9 | 0 | 1 | 10.0% | -6.71 |
| RANGE | 1104 | 238 | 739 | 3 | 124 | 24.3% | -0.66 |

### By session (UK-local)

| session | n | WR | E p |
|---|---:|---:|---:|
| pre_london | 19 | 18.8% | -2.40 |
| london_open | 32 | 22.2% | -0.71 |
| london_am | 324 | 24.1% | -0.60 |
| late_london | 250 | 22.8% | -1.27 |
| ny_open | 236 | 27.4% | -0.16 |
| overlap | 539 | 23.1% | -1.52 |
| later_ny | 1277 | 23.7% | -0.96 |

## Method D

### By context

| context | n | W | L | A | U | WR | E p |
|---|---:|---:|---:|---:|---:|---:|---:|
| STRONG_TREND | 138 | 24 | 97 | 0 | 17 | 19.8% | -2.17 |
| WEAK_TREND | 377 | 74 | 266 | 0 | 37 | 21.8% | -1.79 |
| GRIND | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.00 |
| RANGE | 195 | 47 | 123 | 1 | 24 | 27.5% | +0.80 |

### By session (UK-local)

| session | n | WR | E p |
|---|---:|---:|---:|
| pre_london | 0 | 0.0% | +0.00 |
| london_open | 9 | 14.3% | -3.78 |
| london_am | 66 | 24.2% | -1.46 |
| late_london | 55 | 30.2% | +1.11 |
| ny_open | 63 | 28.6% | +1.15 |
| overlap | 107 | 16.8% | -4.23 |
| later_ny | 377 | 23.3% | -0.87 |

## Method E

### By context

| context | n | W | L | A | U | WR | E p |
|---|---:|---:|---:|---:|---:|---:|---:|
| STRONG_TREND | 198 | 41 | 130 | 0 | 27 | 24.0% | -0.66 |
| WEAK_TREND | 486 | 87 | 339 | 0 | 60 | 20.4% | -2.01 |
| GRIND | 26 | 4 | 20 | 0 | 2 | 16.7% | -3.98 |
| RANGE | 519 | 102 | 365 | 2 | 50 | 21.7% | -1.79 |

### By session (UK-local)

| session | n | WR | E p |
|---|---:|---:|---:|
| pre_london | 0 | 0.0% | +0.00 |
| london_open | 15 | 35.7% | +2.72 |
| london_am | 169 | 25.0% | -0.14 |
| late_london | 109 | 22.2% | -1.53 |
| ny_open | 103 | 9.6% | -6.50 |
| overlap | 210 | 19.3% | -3.39 |
| later_ny | 591 | 23.5% | -0.89 |

