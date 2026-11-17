# STP tab screenshots (17 November 2026, ~23:15 UTC)

Captured by headless Chromium (Playwright) from the **real implemented page**: the branch's `dashboard/static/`
served with the real data service handler (`dashboard/server.py`) in-process on 127.0.0.1, test password.
Desktop 1440×900, mobile 390×844 (2×). No console errors, no horizontal overflow in any capture.

| File | What | Data |
|---|---|---|
| 01_desktop_stp_live_waiting_recommendation | Full STP tab, desktop | **live production planner files** (read only): STP-GBPUSD-20261117-2300-3 WAITING |
| 02_mobile_stp_live_waiting_recommendation | Full STP tab, phone (summary → plan → chart → …) | live |
| 03_desktop_active_recommendation_fixture | ACTIVE recommendation with zone, destinations, invalidation, forecast path | deterministic fixture (`tests/stp_fixtures.py` "active", real keeper output) over the real candle store; fixed clock 09:07 UTC. Fixture zone prices do not correspond to that day's market, so its excursion figures are illustrative only |
| 04_mobile_active_recommendation_fixture | the same on a phone | fixture |
| 05_desktop_historical_recommendation_selected | STP-GBPUSD-20261117-2024-1 reviewed on the chart: original zone/target, created/active/completed markers | live |
| 06_desktop_forecast_evaluation | Forecast evaluation (INSUFFICIENT DATA where n < 3) | live |
| 07_desktop_technical_evidence_expanded | Technical Evidence & Market Structure opened | live |
| 08_desktop_operations_compact_card_only | The compact card on the Operations tab (cropped to the card: the rest of that tab shows account figures) | live |
| 09_desktop_m5_timeframe | M5 candles | live |
| 10_mobile_historical_selected | historical review on a phone | live |

The earlier no-recommendation state (22:05–23:00, explanation D) is shown by the test
`test_18_destination_reached_before_entry` and was captured live at 22:40 UTC during development: `00_desktop_live_no_recommendation_2240utc.png` (an earlier build: chart labels since thinned).
