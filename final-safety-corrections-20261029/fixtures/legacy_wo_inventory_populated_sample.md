# Legacy EMA Pullback Working-Order Inventory

- generated_utc: `2026-10-29T19:30:00+00:00`
- ownership_prefix: `EMAPB`
- record_count: 2

This file is produced READ-ONLY. To cancel orders listed below:

    sudo -u autobot /opt/ema_pullback/venv/bin/python -m \
        ema_pullback.inventory_tool --cancel <this-file> --confirm

Delete lines for orders you do NOT want cancelled before running the cancellation command. Lines starting with `#` are ignored by the parser.

## Entries

- dealRef=`EMAPB-S-1793094815-00B6B8` dealId=`DIAAAAYQQ87XZBS` direction=SELL entry=13304.65 size=2.0 stopDist=12.0 limitDist=100.0 goodTill='GTC' created='2026-10-27T09:53:36' status='WORKING_ORDER' owned_by_this_prefix=True
- dealRef=`EMAPB-B-1793137821-3B35D0` dealId=`DIAAAAYQ6DAMRAS` direction=BUY entry=13306.0 size=2.0 stopDist=12.0 limitDist=100.0 goodTill='GTC' created='2026-10-27T21:50:21' status='WORKING_ORDER' owned_by_this_prefix=True

