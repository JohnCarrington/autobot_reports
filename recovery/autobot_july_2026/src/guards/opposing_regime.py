"""Placeholder for the classifier-based opposing-regime guard.

Always returns block=False, reason='not_implemented'. Slot exists so adding
it to GUARD_REGISTRY when the classifier label review passes is a one-line
change rather than a wiring exercise. Do not implement until classifier
labels have ≥4 weeks of validated data.
"""

from __future__ import annotations

from guards.base import Guard, GuardContext, GuardResult


class OpposingRegimeGuard(Guard):
    name = "opposing_regime"
    enabled_env_var = "GUARD_OPPOSING_REGIME_ENABLED"

    def evaluate(self, context: GuardContext) -> GuardResult:
        return GuardResult(self.name, False, "not_implemented", data={})
