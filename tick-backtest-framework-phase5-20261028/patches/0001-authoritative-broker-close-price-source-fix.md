# Patch 0001 — close_trade: honest price_source on broker-side close

**File:** `trade_executor.py`
**Function:** `close_trade(pos_key)`
**Status:** **PROPOSAL ONLY — NOT DEPLOYED**

## Defect

`close_trade` fires the `_CLOSE_CALLBACKS` chain without passing a
`price_source` kwarg (see `trade_executor.py:5665-5675`). The callback
registered by `trade_log.record_close` therefore defaults
`price_source=AUTHORITATIVE_BROKER_CLOSE` (`trade_log.py:317`).

This default is only correct when:

1. `close_by_deal_id` returned a `dealReference`, **and**
2. `fetch_deal_by_deal_reference(close_ref)` returned `ACCEPTED` with a
   fresh `level`, **and**
3. that level was written back into `st["exit_price"]`
   (`trade_executor.py:5590-5612`).

In the **broker-side-close branch** (`trade_executor.py:5538-5547`) and
whenever the IG confirmation fetch times out, the label is a lie:
`exit_p` is whatever hint was in `st["exit_price"]` **before** the close
— for external-close sweeps this is `state.last_mid` (set at
`trade_executor.py:6883-6884` by `close_position`, and again at
`trade_manager.py:7915-7927` by the external-close sweep).

## Evidence

See `tick-backtest-framework-phase5-20261028/data/stageA_external_close_reconstruction.json`:

| Metric | n | mean (abs) | median (abs) | p90 (abs) | max (abs) |
|---|---|---|---|---|---|
| `exit_price` delta vs IG `closeLevel` (points) | 41 | 11.46 | 3.05 | 48.95 | 66.85 |
| `pnl_gbp` delta vs IG `profitAndLoss` (£) | 41 | 23.41 | 6.10 | 97.90 | 143.70 |

Reproduces the Phase 4 overnight finding exactly (41 rows, mean £23.41,
max £143.70).

## Proposed patch (surgical, two sites)

### Site 1 — `trade_executor.py::close_trade` callback dispatch

Pass an honest `price_source` and schedule an authoritative fetch when
the close was broker-driven or when the confirmation fetch failed.

```python
# BEFORE (trade_executor.py:5661-5675, approximate line numbers)
_cb_deal_id = deal_id or None
for _cb in _CLOSE_CALLBACKS:
    try:
        _cb(pos_key, exit_p, pnl_pips, _close_reason_str, deal_id=_cb_deal_id)
    except TypeError:
        try:
            _cb(pos_key, exit_p, pnl_pips, _close_reason_str)
        except Exception:
            pass
    except Exception:
        pass
```

```python
# AFTER
_cb_deal_id = deal_id or None

# Label the row honestly. AUTHORITATIVE_BROKER_CLOSE requires an IG fill
# level that originated in /confirms OR /history/transactions.  Without
# a successful confirmation fetch, exit_p is the pre-execution hint
# (last_mid / entry_price) and must be marked estimated.
if broker_side_close or not _ig_confirmation_fetched:
    _price_source = "ESTIMATED_LAST_MID"
else:
    _price_source = "AUTHORITATIVE_BROKER_CLOSE"

for _cb in _CLOSE_CALLBACKS:
    _delivered = False
    try:
        _cb(pos_key, exit_p, pnl_pips, _close_reason_str,
            deal_id=_cb_deal_id, price_source=_price_source)
        _delivered = True
    except TypeError:
        pass
    except Exception:
        _delivered = True
    if _delivered:
        continue
    try:
        _cb(pos_key, exit_p, pnl_pips, _close_reason_str, deal_id=_cb_deal_id)
        _delivered = True
    except TypeError:
        pass
    except Exception:
        _delivered = True
    if _delivered:
        continue
    try:
        _cb(pos_key, exit_p, pnl_pips, _close_reason_str)
    except Exception:
        pass

# Schedule an authoritative IG-history supersession for estimated rows.
# Mirrors the behaviour of _emit_vanished_close; the supersession writes
# a second row with price_source=AUTHORITATIVE_IG_HISTORY once IG's
# /history/transactions reports the real fill level.
if _price_source == "ESTIMATED_LAST_MID" and _cb_deal_id:
    try:
        _spawn_prompt_authoritative_fetch(
            pos_key=pos_key, deal_id=_cb_deal_id,
            direction=direction_s, entry_price=entry_p,
            pair=_pair_from_epic(epic),
        )
    except Exception as _spawn_exc:  # pragma: no cover — defensive
        logger.warning(
            "[CLOSE] prompt-fetch spawn failed pk=%s did=%s: %s",
            pos_key, _cb_deal_id, _spawn_exc,
        )
```

The new `_ig_confirmation_fetched` flag is initialised to `False` at the
top of the function and set `True` only after the body of the
`if conf.get("dealStatus") == "ACCEPTED": fill_level = ...` branch
successfully writes `fill_level` to `st["exit_price"]`
(`trade_executor.py:5600-5610`).

### Site 2 — invariant check at `trade_log.record_close`

Tighten the default so a missing `price_source` can never be silently
reclassified as authoritative when the exit_price is actually a hint.

```python
# BEFORE (trade_log.py:317)
ps = price_source or _AUTHORITATIVE_BROKER_CLOSE
```

```python
# AFTER
# Fail honest: a caller that doesn't supply price_source is almost
# always a legacy call site that lacks IG confirmation guarantees.
# Treating that as authoritative masked the Phase-4 external-close
# defect for 41 trades.  Default to ESTIMATED_LAST_MID so the row is
# superseded by the next IG-history reconciliation pass.
ps = price_source or _ESTIMATED_LAST_MID
```

Combined with Site 1, all deterministic paths pass an explicit
`price_source`, so the fallback is only reached by stale/unforeseen
callers — which should be classified as estimated.

## Deployment

**Do not merge.**  The patch requires:

1. A production dry-run on a fresh IG DEMO account for a full trading
   day, with a shadow reconciler asserting that the `AUTHORITATIVE_*`
   count matches the IG transaction count once the supersession pass
   has run.
2. Operator sign-off.

Phase 5 publishes this proposal and regression evidence only.
