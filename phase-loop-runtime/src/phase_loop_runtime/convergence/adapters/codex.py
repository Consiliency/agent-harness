"""Codex provider adapter: one bounded, non-coordinating action."""
from __future__ import annotations

from phase_loop_runtime.train_ledger import ConvergenceResultEnvelope

from .base import AdapterExecutionRequest, run_bounded

CODEX_EXECUTABLE = "codex"


def run_codex_adapter(request: AdapterExecutionRequest) -> ConvergenceResultEnvelope:
    """Bind the exact codex executable identity and return the frozen envelope."""

    return run_bounded(request, provider=CODEX_EXECUTABLE)
