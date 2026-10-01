# Timestamp conventions

## Candle CSVs — UTC, bar-start, 5-minute

- Column `timestamp` is ISO-8601 with explicit `+00:00` offset.
- All times are **UTC**. No local-time, no DST shifts, no exchange time.
- The timestamp is the **bar START**. A row with `timestamp=2026-07-01T00:05:00+00:00` represents the bar covering `[00:05:00, 00:10:00)` UTC.
- Each file covers a single UTC calendar day. The first row is typically `00:00:00` and the last row is typically `23:55:00`, giving up to 288 rows per 24h day. Weekend hours (Fri 22:00 UTC → Sun 22:00 UTC) are naturally absent from the CSV; see `coverage_gaps.md`.
- Candle fields: `open, high, low, close` only — no volume, no spread, no bid/ask split. Mid-prices as returned by the IG REST candles API.

Unrelated to this handoff but worth knowing: the TICK archive on the source host (not shipped here) is in **US Eastern Standard Time with no DST** for pre-2026 history and switches partway through 2026 — see `project_tick_tz_mixed_20260928.md` on the source host if tick alignment is ever needed. Candles are always true UTC.

## Briefing JSONs — UTC

- `generated_at_utc` and `valid_until_utc` are both UTC ISO-8601, suffixed with `Z` (e.g. `2026-07-01T05:34:39Z`).
- `generated_at_utc` is wall-clock at the moment the producer wrote the file.
- `valid_until_utc` is the executor-honored expiry. London briefings expire at 12:30Z (end of London session for v5 purposes); NY briefings expire at end-of-day UTC.

## Session convention

- `session: "London"` — briefing produced around 05:30 UTC, intended to cover the London morning window.
- `session: "NY"` — briefing produced around 12:30 UTC, intended to cover the NY afternoon window.

The producer fires on a timer (see `config/scheduler.md`) and expects the executor to be running continuously. There is no in-session re-fire.

## Daylight savings

- Candles and briefings never shift with DST. Everything is UTC.
- The `autobot-start.timer` systemd unit uses `Europe/London` wall-clock (Sun 22:00 BST ↔ 21:00 UTC summer, 22:00 UTC winter) only because FX market open tracks London wall-clock. The producer and candle persistence are UTC-only.
