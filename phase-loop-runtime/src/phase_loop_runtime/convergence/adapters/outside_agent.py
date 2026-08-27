"""Outside-agent adapter: conformance-validated, bounded, non-coordinating."""
from __future__ import annotations

from typing import Mapping

from phase_loop_runtime.train_ledger import ConvergenceResultEnvelope, ConvergenceResultStatus

from .base import AdapterExecutionRequest, run_bounded

OUTSIDE_AGENT_EXECUTABLE = "outside-agent"

_DETAIL_UNVALIDATED = "outside-agent submission was not validated"
_DETAIL_NONCONFORMANT = "outside-agent submission failed conformance"


def run_outside_agent_adapter(
    request: AdapterExecutionRequest, submission: Mapping | None = None
) -> ConvergenceResultEnvelope:
    """Run an outside agent only behind a passing conformance verdict.

    A third party's submission is untrusted input, so the absence of one is not
    a permissive default: with nothing to validate there is nothing to admit,
    and the adapter blocks without spawning anything.
    """

    if submission is None:
        return ConvergenceResultEnvelope(
            ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_UNVALIDATED
        )
    from phase_loop_runtime.conformance import validate_outside_agent_submission

    if validate_outside_agent_submission(submission).status.value != "pass":
        return ConvergenceResultEnvelope(
            ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_NONCONFORMANT
        )
    return run_bounded(request, provider=OUTSIDE_AGENT_EXECUTABLE)
