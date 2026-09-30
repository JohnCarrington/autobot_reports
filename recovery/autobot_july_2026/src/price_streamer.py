"""
price_streamer.py
───────────────────────────────────────────────
Lightweight safe polling streamer that updates CandleBuilder5M
from /markets/{epic} snapshots without hitting IG rate limits.
"""

import time
import threading
import logging

logger = logging.getLogger("AutoBot")


class PriceStreamer:
    def __init__(self, ig, builders, poll_interval: float = 5.0, debug: bool = False):
        """
        :param ig: Active IGService session
        :param builders: Dict of CandleBuilder5M objects keyed by epic
        :param poll_interval: Seconds between polling cycles per epic
        :param debug: Log each tick
        """
        self.ig = ig
        self.builders = builders
        self.poll_interval = poll_interval
        self.debug = debug
        self._threads = []
        self._stop = threading.Event()

    # ------------------------------------------------------------
    def start_all(self):
        for epic in self.builders.keys():
            t = threading.Thread(target=self._run_loop, args=(epic,), daemon=True)
            t.start()
            self._threads.append(t)
            logger.info(f"▶️ Starting price streamer for {epic} (safe polling mode)")

    def stop_all(self):
        self._stop.set()
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=2)
        logger.info("🛑 All price streamer threads stopped.")

    # ------------------------------------------------------------
    def _run_loop(self, epic: str):
        builder = self.builders[epic]
        while not self._stop.is_set():
            try:
                resp = self.ig.fetch_market_by_epic(epic)
                snapshot = getattr(resp, "snapshot", None)
                if snapshot:
                    bid = float(snapshot.get("bid"))
                    ask = float(snapshot.get("offer"))
                    if self.debug:
                        logger.info(f"[{epic}] bid={bid:.5f} ask={ask:.5f}")
                    builder.update(epic, bid, ask)
                else:
                    logger.warning(f"⚠️ No snapshot returned for {epic}")
            except Exception as e:
                logger.warning(f"⚠️ Streamer error for {epic}: {e}")

            time.sleep(self.poll_interval)
