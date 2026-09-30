# Interface & data formats

## Ledger event (JSONL)

```json
{"id":"12","ts":"2026-09-30T07:15:22.331+00:00","space":"sim","trade_id":"a1b2c3","type":"OPEN_SUBMITTED",
 "payload":{"epic":"GBPUSD","direction":"BUY","stake":2.0,"stop_price":13270.5,"deal_reference":"a1b2c3"}}
```

Event `type` is one of: `OPEN_SUBMITTED`, `OPEN_ACCEPTED`,
`OPEN_REJECTED`, `OPEN_UNCERTAIN`, `CLOSE_SUBMITTED`, `CLOSE_ACCEPTED`,
`CLOSE_REJECTED`, `CLOSED_AWAITING_SETTLEMENT`, `CLOSE_SETTLED`,
`STOP_MOVED`, `POSITION_MISSING`, `NOTE`.

## Telegram outbox (JSONL)

```json
{"alert_id":"49f...","kind":"SIM_OPEN","body":"[Trend Runner DEMO SIMULATED] BUY @ 13270.5 stop=13260.5",
 "created_at":"2026-09-30T07:15:22.331+00:00","status":"PENDING","retry_count":0,"last_error":null,
 "delivered_at":null,"marker":false}
```

Status transitions: `PENDING → SENT` (on ACK) or `PENDING → GIVEN_UP`
(after `MAX_RETRIES`).

## Recorder line (input, from AutoBot recorder)

```json
{"ts":"2026-09-30T07:15:23.412+00:00","epic":"CS.D.GBPUSD.MINI.IP",
 "bid":1.34210,"ask":1.34216,"update_type":"TICK","gen":5}
```

`bid`/`ask` are IG display quotes (5 decimal places) and are
converted to corpus units by multiplying by 10 000 inside
`parse_line`.

## Candle CSV (offline replay)

```
timestamp,open,high,low,close
2026-09-30T07:15:00+00:00,13270.30,13272.50,13268.15,13271.85
```

Values are ``display_quote * 10000`` (see `trend_runner/pips.py`). One
file per calendar UTC day.

## Trade replay JSON (offline replay output)

```json
{
  "trade_id": "...",
  "direction": "UP",
  "entry_time": "...",
  "entry_price": 13270.5,
  "stop_price": 13260.5,
  "exit_time": "...",
  "exit_price": 13290.5,
  "exit_reason": "R3_TARGET",
  "net_pips": 20.0,
  "regime": "GRIND",
  "pivots": {"R3": 13290.5, "S3": 13230.5, "P": 13260.5},
  "stake_gbp_per_pip": 2.0
}
```

## State file (atomic JSON)

`atomic_write_json` accepts any JSON-serialisable dict. The runner may
persist rolling counters here (bar cursor, session cursor). All state
transitions of consequence are journaled to the ledger, not the state
file — the state file is a convenience, not the source of truth.
