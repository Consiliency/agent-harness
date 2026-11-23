"""Host-neutral seam for out-of-process routing integrations (IF-0-JEVHOST-5).

This module holds only the parts any host integration shares (GAPS §2 of
``plans/artifacts/jevhost-host-gaps-v1.md``):

- the retry-budget arithmetic (``RetryBudget``), owned by the trusted host request and
  only ever tightened;
- the acceptance-observer protocol (``AcceptanceObserver``, ``notify_acceptance``);
- the closed deactivation vocabulary (``DEACTIVATION_REASONS``, ``deactivation_reason``);
- per-operation disconnect advice (``disconnect_advice``, ``annotate_disconnect``);
- the operator-model override guard (``build_host_request``, ``HostOverrideViolation``).

It names no integration's schema, path or CLI flag, and it does no IO, spawn or ctypes.
Ledgers, readiness ordering, argv budgets, declarations and every integration-specific
mapping stay in the integration's own adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

__all__ = [
    "ACCEPTANCE_FAILURE_CLASSES",
    "AcceptanceObserver",
    "DEACTIVATION_REASONS",
    "HostOverrideViolation",
    "RetryBudget",
    "annotate_disconnect",
    "build_host_request",
    "deactivation_reason",
    "disconnect_advice",
    "notify_acceptance",
]

_NS_PER_MS = 1_000_000

ACCEPTANCE_FAILURE_CLASSES = ("infrastructure", "quality")


@dataclass(frozen=True)
class RetryBudget:
    """A retry budget taken from the trusted host request.

    ``first_started_ns`` is a ``time.monotonic_ns()`` value from the task's first routed
    request. A later request may only ``tighten`` the budget.
    """

    max_attempts: int
    total_deadline_ms: int
    first_started_ns: int

    def remaining(self, attempts_used: int, now_ns: int) -> tuple[int, int]:
        """Return ``(remaining_attempts, remaining_time_ms)``, both integers >= 0."""
        remaining_attempts = max(0, self.max_attempts - attempts_used)
        elapsed_ns = now_ns - self.first_started_ns
        remaining_time_ms = max(0, (self.total_deadline_ms * _NS_PER_MS - elapsed_ns) // _NS_PER_MS)
        return remaining_attempts, remaining_time_ms

    def exhausted(self, attempts_used: int, now_ns: int) -> bool:
        """True when either the attempts or the time remaining is zero."""
        remaining_attempts, remaining_time_ms = self.remaining(attempts_used, now_ns)
        return remaining_attempts == 0 or remaining_time_ms == 0

    def tighten(self, other: RetryBudget) -> RetryBudget:
        """Return the stricter combination: smaller cap and deadline, earlier start."""
        return RetryBudget(
            max_attempts=min(self.max_attempts, other.max_attempts),
            total_deadline_ms=min(self.total_deadline_ms, other.total_deadline_ms),
            first_started_ns=min(self.first_started_ns, other.first_started_ns),
        )


@runtime_checkable
class AcceptanceObserver(Protocol):
    """An integration that learns the host's acceptance verdict for a launched run."""

    def record_acceptance_outcome(self, execution_run_id: str, *, passed: bool,
                                  failure_class: str | None) -> None: ...


def notify_acceptance(integration: Any, execution_run_id: str, *, passed: bool,
                      failure_class: str | None) -> bool:
    """Report an acceptance verdict to ``integration`` if it observes verdicts.

    ``failure_class`` must be ``None`` when ``passed`` and one of
    ``ACCEPTANCE_FAILURE_CLASSES`` otherwise. Returns whether the observer was called.
    No exception from the observer is caught; the caller owns error handling.
    """
    if passed:
        if failure_class is not None:
            raise ValueError("A passed verdict carries no failure class")
    elif failure_class not in ACCEPTANCE_FAILURE_CLASSES:
        raise ValueError(f"Unknown acceptance failure class: {failure_class!r}")
    record = getattr(integration, "record_acceptance_outcome", None)
    if not callable(record):
        return False
    record(execution_run_id, passed=passed, failure_class=failure_class)
    return True


DEACTIVATION_REASONS = (
    "guidance_scoped_to_task_prompt",
    "executor_unavailable",
    "executor_identity_mismatch",
    "launch_canceled",
    "launch_aborted",
)


def deactivation_reason(*, result_returned: bool, available: bool, identity_mismatch: bool,
                        interrupted: bool) -> str:
    """Return why injected guidance ended; the first matching rule wins."""
    if not result_returned:
        return "launch_aborted"
    if not available:
        return "executor_unavailable"
    if identity_mismatch:
        return "executor_identity_mismatch"
    if interrupted:
        return "launch_canceled"
    return "guidance_scoped_to_task_prompt"


_CHECK_CLI = "Check that the configured integration CLI starts and answers --help."
_DISCONNECT_ADVICE = {
    "route": (
        _CHECK_CLI,
        "Retry the launch once the integration is reachable, or run without the integration; "
        "an unrouted launch remains subject to the ordinary launch authority.",
    ),
    "report": (
        _CHECK_CLI,
        "The report stays queued and is retried after its backoff on a later flush, unless it "
        "expires, overflows the queue or its task is deleted.",
    ),
}


def disconnect_advice(operation: str) -> tuple[str, ...]:
    """Return the supported resolution steps for a disconnect during ``operation``."""
    try:
        return _DISCONNECT_ADVICE[operation]
    except KeyError:
        raise ValueError(f"Unknown integration operation: {operation!r}") from None


def annotate_disconnect(exc: BaseException, operation: str) -> BaseException:
    """Attach ``resolution_advice`` for ``operation`` to ``exc`` and return the same object."""
    exc.resolution_advice = disconnect_advice(operation)
    return exc


class HostOverrideViolation(ValueError):
    """An integration replaced an operator or policy model override."""


def _selection_fields(selection: Any) -> tuple[Any, Any, Any]:
    return (selection.model, selection.effort, selection.source)


def build_host_request(integration: Any, builder: Callable[..., Any], *, mode: str, dry_run: bool,
                       **kwargs: Any) -> Any:
    """Let ``integration`` prepare the request kwargs, then call ``builder``.

    The ``(model, effort, source)`` of ``kwargs["model_selection"]`` are captured before
    ``prepare`` runs. When that source is an override (not ``"default"`` or
    ``executor + "_default"``), the prepared selection must carry the same three values,
    or ``HostOverrideViolation`` is raised before ``builder`` runs. With no integration
    this is exactly ``builder(**kwargs)``.
    """
    if integration is None:
        return builder(**kwargs)
    original = kwargs.get("model_selection")
    snapshot = _selection_fields(original) if original is not None else None
    defaults = ("default", f"{kwargs.get('executor')}_default")
    prepared = integration.prepare(mode=mode, dry_run=dry_run, **kwargs)
    if snapshot is not None and snapshot[2] not in defaults:
        chosen = prepared.get("model_selection")
        if chosen is None or _selection_fields(chosen) != snapshot:
            raise HostOverrideViolation("Integration would replace an operator or policy model override")
    return builder(**prepared)
