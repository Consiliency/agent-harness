"""Claude provider adapter: one bounded, non-coordinating action."""
from __future__ import annotations

from phase_loop_runtime.train_ledger import ConvergenceResultEnvelope

from .base import AdapterExecutionRequest, run_bounded

CLAUDE_EXECUTABLE = "claude"


def run_claude_adapter(request: AdapterExecutionRequest) -> ConvergenceResultEnvelope:
    """Bind the exact claude executable identity and return the frozen envelope."""

    return run_bounded(request, provider=CLAUDE_EXECUTABLE)
