#!/usr/bin/env python3
from dotenv import load_dotenv
load_dotenv()

from ig_auth import get_ig_session

EPICS = [
    "CS.D.EURUSD.CFD.IP",
    "CS.D.EURUSD.TODAY.IP",
]

def main():
    ig, headers, account_id = get_ig_session()
    print("account_id:", account_id)
    print("headers CST/XST present:", bool(headers.get("CST")), bool(headers.get("X-SECURITY-TOKEN")))

    for epic in EPICS:
        print("\n=== epic:", epic)
        # Try and_num_points
        fn = getattr(ig, "fetch_historical_prices_by_epic_and_num_points", None)
        if callable(fn):
            try:
                resp = fn(epic, "MINUTE", 10)
                print("and_num_points type:", type(resp))
                if isinstance(resp, tuple) and len(resp) == 2:
                    print("status:", resp[0], "payload_type:", type(resp[1]))
                    payload = resp[1]
                else:
                    payload = resp
                # print minimal keys
                if hasattr(payload, "head"):
                    print("payload looks like DF, head():")
                    print(payload.head(2))
                elif isinstance(payload, dict):
                    print("payload keys:", list(payload.keys())[:20])
                    prices = payload.get("prices")
                    print("prices type:", type(prices), "len:", (len(prices) if isinstance(prices, list) else "n/a"))
                    if isinstance(prices, list) and prices:
                        print("first price keys sample:", list(prices[0].keys())[:30])
                else:
                    print("payload repr:", repr(payload)[:400])
            except Exception as e:
                print("and_num_points EXC:", type(e).__name__, str(e)[:200])

        # Try by_epic
        fn2 = getattr(ig, "fetch_historical_prices_by_epic", None)
        if callable(fn2):
            try:
                resp2 = fn2(epic=epic, resolution="MINUTE", max=10)
                print("by_epic type:", type(resp2))
                if isinstance(resp2, tuple) and len(resp2) == 2:
                    print("status:", resp2[0], "payload_type:", type(resp2[1]))
            except Exception as e:
                print("by_epic EXC:", type(e).__name__, str(e)[:200])

if __name__ == "__main__":
    main()
