# Pip / price-unit conventions

## Candle CSV units

The 5-minute candle CSVs in `data/candles/<SYM>/*.csv` are stored in **IG pence-pips** (sometimes called "scaled pips"). This is the native IG REST API scale and matches the AutoBot runtime without conversion.

| Pair    | Scaled sample | True quote | Scale factor | Pip size (true) | Pip size (scaled) |
|---------|---------------|------------|--------------|-----------------|-------------------|
| EURUSD  | `11413.2`     | `1.14132`  | ×10000       | 0.0001          | 1.0 scaled unit   |
| GBPUSD  | `13251.15`    | `1.325115` | ×10000       | 0.0001          | 1.0 scaled unit   |
| USDJPY  | `16385.70`    | `163.857`  | ×100         | 0.01            | 1.0 scaled unit   |
| USDCAD  | `14081.95`    | `1.408195` | ×10000       | 0.0001          | 1.0 scaled unit   |

In other words: **one pip = one unit of the "last decimal" in the scaled column** across all four pairs. A move from `11413.2 → 11414.2` on EURUSD is 1 pip (0.0001 in true quote); a move from `16385.70 → 16386.70` on USDJPY is 1 pip (0.01 in true quote).

Prices in the shipped candles sit between pip and sub-pip resolution — the last digit after the decimal is a fractional pip (0.1 pip). This is what the AutoBot runtime consumes directly.

## Briefing JSON units

Briefing fields `entry`, `stop`, `target`, `bias_anchor`, `support_levels`, `resistance_levels` all use the **same scaled-pip units** as the candle CSVs. No conversion is applied when the executor consumes a briefing.

A briefing with `entry: 11420.5, stop: 11400.0, target: 11460.0` on EURUSD = entry 1.14205, stop 1.14000, target 1.14600, true quote. Risk = 20.5 pips, reward = 40.0 pips, RR ≈ 1.95.

## Dollars-per-pip (reference only)

The AutoBot executor sizes positions by *risk per trade* (expressed as pips × dollars-per-pip at the configured deal size), not by a hardcoded dollars-per-pip. These values are provided only for interpreting briefing P&L in `briefings/samples/`.

Dollars-per-pip depends on deal size (contracts), account currency, and the pair's quote currency. For a 1-mini-lot (10k) deal in a USD-denominated account:

| Pair   | $/pip @ 10k | Comment                                      |
|--------|-------------|----------------------------------------------|
| EURUSD | $1.00       | Pip in quote currency = USD                  |
| GBPUSD | $1.00       | Pip in quote currency = USD                  |
| USDJPY | ~$0.61      | Depends on current USDJPY rate (= 10 / price)|
| USDCAD | ~$0.71      | Depends on current USDCAD rate (= 10 / price)|

Pip values for JPY/CAD-quoted pairs float with the quote; the executor recomputes on each fire. If you need exact P&L reconstruction from the shipped briefings, use the IG executor's position-sizing path — don't re-derive here.
