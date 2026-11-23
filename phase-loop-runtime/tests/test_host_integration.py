"""Unit tests for the host-neutral integration seam (JEVHOST amendment, GAPS §2).

The seam is imported test-locally. On a tree without the module, every test fails at
an explicit ``host_integration`` availability assertion that names the missing
interface (GAPS §3.0), rather than at a collection error.
"""

import ast
import importlib
import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from phase_loop_runtime.models import ModelSelection

_MODULE = "phase_loop_runtime.host_integration"


def _seam(*names):
    spec = importlib.util.find_spec(_MODULE)
    assert spec is not None, f"host_integration is unavailable: missing interface {', '.join(names)}"
    module = importlib.import_module(_MODULE)
    missing = [name for name in names if not hasattr(module, name)]
    assert not missing, f"host_integration is missing interface {', '.join(missing)}"
    return module


_NS = 1_000_000  # nanoseconds per millisecond


def test_retry_budget_arithmetic_and_exhaustion():
    hi = _seam("RetryBudget", "ACCEPTANCE_FAILURE_CLASSES", "notify_acceptance")
    start = 5_000 * _NS
    budget = hi.RetryBudget(max_attempts=3, total_deadline_ms=1_000, first_started_ns=start)

    # Positive elapsed arithmetic.
    assert budget.remaining(1, start + 400 * _NS) == (2, 600)
    assert budget.remaining(0, start) == (3, 1_000)
    # Floor division to an integer millisecond count.
    remaining_attempts, remaining_ms = budget.remaining(1, start + 400 * _NS + 1)
    assert (remaining_attempts, remaining_ms) == (2, 599)
    assert type(remaining_ms) is int and type(remaining_attempts) is int
    # The exact boundary: zero at the deadline, never negative after it.
    assert budget.remaining(1, start + 1_000 * _NS) == (2, 0)
    assert budget.remaining(1, start + 1_000 * _NS - 1) == (2, 0)
    assert budget.remaining(1, start + 999 * _NS) == (2, 1)
    assert budget.remaining(1, start + 5_000 * _NS) == (2, 0)
    assert budget.remaining(9, start) == (0, 1_000)

    # Exhaustion by attempts alone and by time alone.
    assert not budget.exhausted(2, start + 999 * _NS)
    assert budget.exhausted(3, start)
    assert budget.exhausted(4, start)
    assert budget.exhausted(0, start + 1_000 * _NS)
    assert budget.exhausted(0, start + 1_000 * _NS - 1)

    # Tighten-only: smaller cap, smaller deadline, earlier start; never widens.
    wider = hi.RetryBudget(max_attempts=5, total_deadline_ms=2_000, first_started_ns=start + 50 * _NS)
    assert budget.tighten(wider) == budget
    assert wider.tighten(budget) == budget
    mixed = hi.RetryBudget(max_attempts=2, total_deadline_ms=4_000, first_started_ns=start - 10 * _NS)
    assert budget.tighten(mixed) == hi.RetryBudget(
        max_attempts=2, total_deadline_ms=1_000, first_started_ns=start - 10 * _NS)
    with pytest.raises(Exception):
        budget.max_attempts = 10  # frozen

    # The failure-class vocabulary, and an unknown class raises.
    assert hi.ACCEPTANCE_FAILURE_CLASSES == ("infrastructure", "quality")
    calls = []

    class Observer:
        def record_acceptance_outcome(self, execution_run_id, *, passed, failure_class):
            calls.append((execution_run_id, passed, failure_class))

    with pytest.raises(ValueError):
        hi.notify_acceptance(Observer(), "run-1", passed=False, failure_class="flaky")
    with pytest.raises(ValueError):
        hi.notify_acceptance(Observer(), "run-1", passed=False, failure_class=None)
    with pytest.raises(ValueError):
        hi.notify_acceptance(Observer(), "run-1", passed=True, failure_class="quality")
    assert calls == []


def test_notify_acceptance_calls_only_an_implementing_observer():
    hi = _seam("AcceptanceObserver", "notify_acceptance")
    calls = []

    class Observer:
        def record_acceptance_outcome(self, execution_run_id, *, passed, failure_class):
            calls.append((execution_run_id, passed, failure_class))

    observer = Observer()
    assert isinstance(observer, hi.AcceptanceObserver)
    assert hi.notify_acceptance(observer, "run-1", passed=False, failure_class="infrastructure") is True
    assert hi.notify_acceptance(observer, "run-2", passed=False, failure_class="quality") is True
    assert hi.notify_acceptance(observer, "run-3", passed=True, failure_class=None) is True
    assert calls == [("run-1", False, "infrastructure"), ("run-2", False, "quality"), ("run-3", True, None)]

    assert hi.notify_acceptance(None, "run-4", passed=True, failure_class=None) is False
    assert hi.notify_acceptance(object(), "run-5", passed=False, failure_class="quality") is False
    assert not isinstance(object(), hi.AcceptanceObserver)

    class Raising:
        def record_acceptance_outcome(self, execution_run_id, *, passed, failure_class):
            raise RuntimeError("observer broke")

    # The seam catches nothing; the runner owns error handling.
    with pytest.raises(RuntimeError, match="observer broke"):
        hi.notify_acceptance(Raising(), "run-6", passed=True, failure_class=None)


def test_deactivation_reason_order():
    hi = _seam("DEACTIVATION_REASONS", "deactivation_reason")
    assert hi.DEACTIVATION_REASONS == (
        "guidance_scoped_to_task_prompt", "executor_unavailable", "executor_identity_mismatch",
        "launch_canceled", "launch_aborted")
    reason = hi.deactivation_reason
    everything = dict(available=False, identity_mismatch=True, interrupted=True)
    assert reason(result_returned=False, **everything) == "launch_aborted"
    assert reason(result_returned=False, available=True, identity_mismatch=False,
                  interrupted=False) == "launch_aborted"
    assert reason(result_returned=True, **everything) == "executor_unavailable"
    assert reason(result_returned=True, available=True, identity_mismatch=True,
                  interrupted=True) == "executor_identity_mismatch"
    assert reason(result_returned=True, available=True, identity_mismatch=False,
                  interrupted=True) == "launch_canceled"
    assert reason(result_returned=True, available=True, identity_mismatch=False,
                  interrupted=False) == "guidance_scoped_to_task_prompt"
    for args in ((True, True, False, False), (False, False, False, False), (True, False, False, True)):
        assert reason(result_returned=args[0], available=args[1], identity_mismatch=args[2],
                      interrupted=args[3]) in hi.DEACTIVATION_REASONS


def test_disconnect_advice_is_exact_per_operation():
    hi = _seam("disconnect_advice")
    check = "Check that the configured integration CLI starts and answers --help."
    assert hi.disconnect_advice("route") == (
        check,
        "Retry the launch once the integration is reachable, or run without the integration; "
        "an unrouted launch remains subject to the ordinary launch authority.",
    )
    assert hi.disconnect_advice("report") == (
        check,
        "The report stays queued and is retried after its backoff on a later flush, unless it "
        "expires, overflows the queue or its task is deleted.",
    )
    with pytest.raises(ValueError):
        hi.disconnect_advice("launch")


@pytest.mark.parametrize("operation", ["route", "report"])
def test_annotate_disconnect_returns_the_same_object(operation):
    hi = _seam("annotate_disconnect", "disconnect_advice")
    for exc in (FileNotFoundError(2, "missing"), TimeoutError("slow"), OSError("down")):
        result = hi.annotate_disconnect(exc, operation)
        assert result is exc
        assert type(result) is type(exc)
        assert exc.resolution_advice == hi.disconnect_advice(operation)
    with pytest.raises(ValueError):
        hi.annotate_disconnect(OSError("down"), "launch")


def _selection(source="user_override", model="op-model", effort="high"):
    return ModelSelection(profile="execute", model=model, effort=effort, source=source)


class _Integration:
    def __init__(self, change):
        self.change = change
        self.calls = []

    def prepare(self, *, mode, dry_run, **kwargs):
        self.calls.append((mode, dry_run))
        return {**kwargs, "model_selection": self.change(kwargs["model_selection"])}


def _in_place(selection):
    object.__setattr__(selection, "model", "routed-model")
    return selection


_OVERRIDE_CHANGES = {
    "model": lambda s: replace(s, model="routed-model"),
    "effort": lambda s: replace(s, effort="low"),
    "source": lambda s: replace(s, source="jevdrill"),
    "in_place": _in_place,
}


@pytest.mark.parametrize("field", list(_OVERRIDE_CHANGES))
def test_build_host_request_refuses_override_changes(field):
    hi = _seam("build_host_request", "HostOverrideViolation")
    assert issubclass(hi.HostOverrideViolation, ValueError)
    built = []
    integration = _Integration(_OVERRIDE_CHANGES[field])
    with pytest.raises(hi.HostOverrideViolation):
        hi.build_host_request(integration, lambda **kw: built.append(kw), mode="main", dry_run=False,
                              executor="codex", model_selection=_selection(), action="run")
    assert integration.calls == [("main", False)]
    assert built == []


def test_build_host_request_passes_preserved_override_and_default_routing():
    hi = _seam("build_host_request", "HostOverrideViolation")

    def builder(**kw):
        return ("built", kw)

    # A preserved operator override passes through unchanged.
    override = _selection()
    preserved = _Integration(lambda s: s)
    kind, kw = hi.build_host_request(preserved, builder, mode="lane", dry_run=True,
                                     executor="codex", model_selection=override, action="run")
    assert kind == "built" and kw["model_selection"] is override and kw["action"] == "run"
    assert preserved.calls == [("lane", True)]
    # An equal-valued replacement object is still a preserved override.
    kind, kw = hi.build_host_request(_Integration(lambda s: replace(s)), builder, mode="main",
                                     dry_run=False, executor="codex", model_selection=_selection())
    assert (kw["model_selection"].model, kw["model_selection"].effort,
            kw["model_selection"].source) == ("op-model", "high", "user_override")

    # Default and executor-default selections may be replaced by routing.
    routed = lambda s: replace(s, model="routed-model", effort="low", source="jevdrill")  # noqa: E731
    for source in ("default", "codex_default"):
        kind, kw = hi.build_host_request(_Integration(routed), builder, mode="delegated", dry_run=False,
                                         executor="codex", model_selection=_selection(source=source))
        assert (kw["model_selection"].model, kw["model_selection"].effort,
                kw["model_selection"].source) == ("routed-model", "low", "jevdrill")
    # Another executor's default is an override for this executor.
    with pytest.raises(hi.HostOverrideViolation):
        hi.build_host_request(_Integration(routed), builder, mode="main", dry_run=False,
                              executor="codex", model_selection=_selection(source="claude_default"))

    # With no integration it is exactly builder(**kwargs).
    sentinel = object()
    seen = []

    def plain(**kw):
        seen.append(kw)
        return sentinel

    selection = _selection()
    assert hi.build_host_request(None, plain, mode="main", dry_run=False, executor="codex",
                                 model_selection=selection, action="run") is sentinel
    assert seen == [{"executor": "codex", "model_selection": selection, "action": "run"}]


def test_seam_is_host_neutral():
    hi = _seam("build_host_request")
    tree = ast.parse(Path(hi.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    forbidden = {"subprocess", "ctypes", "socket", "sqlite3", "os", "shutil", "pathlib", "io"}
    assert not imported & forbidden, imported & forbidden
    assert not any("jevdrill" in name for name in imported), imported
