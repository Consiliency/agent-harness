"""Codex provider adapter: one bounded, non-coordinating action."""
from __future__ import annotations

from phase_loop_runtime.train_ledger import ConvergenceResultEnvelope

from .base import AdapterExecutionRequest, run_bounded

CODEX_EXECUTABLE = "codex"


def run_codex_adapter(request: AdapterExecutionRequest) -> ConvergenceResultEnvelope:
    """Bind the exact codex executable identity and return the frozen envelope."""

    return run_bounded(request, provider=CODEX_EXECUTABLE)


def run_codex_patch_return(prepared, *, config_bytes, state_root, cancel=None):
    from pathlib import Path
    from .patch_return import WorkerResult, run_patch_return
    if Path(prepared.view.inputs.executable.path).name != CODEX_EXECUTABLE:
        return WorkerResult(None, "refused", None, "provider_mismatch", 0, None, None, None, True)
    return run_patch_return(prepared, config_bytes=config_bytes, state_root=state_root, cancel=cancel)
