"""Plan-label keyword inference for BRIEFING_EXECUTION.

infer_plan_class() maps a briefing plan's label string to a
continuation / fade / unknown class by keyword match — consumed by
briefing_execution.py to stamp decision.debug["plan_class"].

Note: the regime-classifier entry-filter this module once also
provided (allow_entry) was removed in the V1 strip-out — the
autobot.py G10 call-site (step 3d), then the dead subtree (cleanup
step 1).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Plan-label keyword inference (for BRIEFING_EXECUTION) ──────────────

_CONTINUATION_KEYWORDS = ("continuation", "breakout", "trend")
_FADE_KEYWORDS = ("fade", "bounce", "rejection", "sweep", "scalp")

# Tracks plan labels we've already logged inferences for — first
# encounter per label per process lifetime gets a verbose log so we
# can patch keyword rules without redeploy. After that, silent.
_seen_labels_lock = threading.Lock()
_seen_labels: set[str] = set()


def infer_plan_class(plan_label: Optional[str]) -> str:
    """Infer continuation/fade from a BRIEFING_EXECUTION plan label.

    Rule:
      contains 'continuation', 'breakout', 'trend' → 'continuation'
      contains 'fade', 'bounce', 'rejection', 'sweep', 'scalp' → 'fade'
      otherwise → 'unknown'

    First encounter with each label string in this process lifetime
    is logged at INFO so wording mismatches can be patched without
    redeploying. Subsequent encounters are silent.
    """
    raw = str(plan_label or "").strip()
    if not raw:
        return "unknown"
    label_lc = raw.lower()
    if any(w in label_lc for w in _CONTINUATION_KEYWORDS):
        result = "continuation"
    elif any(w in label_lc for w in _FADE_KEYWORDS):
        result = "fade"
    else:
        result = "unknown"

    # Log first encounter only.
    with _seen_labels_lock:
        if raw not in _seen_labels:
            _seen_labels.add(raw)
            logger.info(
                "[REGIME-FILTER] plan_class inference: %r → %s",
                raw, result,
            )
    return result
