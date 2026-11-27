"""agent-harness#1823: a jailed Gemini seat's refusals keep their typed code on the board.

A refusal raised while the seat is prepared or run used to escape ``_parent_infer``'s
jailed-Gemini branch untyped, cross the broker client's wrapper without its cause, and reach
the operator as ``unknown failure; CLI output not retained``. These tests assert the
BOARD-LEVEL ``detail`` (``PanelLegResult.detail`` after the closed-vocabulary validator) for
each refusal class, and the closed ``stage`` / ``refusal`` fields of the leg's ``leg_exec.v1``
record. No provider, broker child, jail or network is started.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress, sandbox_policy, seat_jail
from phase_loop_runtime.executable_dependency import ExecutableDependencyError

KEY = "gemini:gemini-4-argon:medium:alternative-approach"
UNKNOWN = "unknown failure; CLI output not retained"
GATE = ("dependency_route_unwired", "Gemini host credential refresh")


def _board_detail(failure) -> str:
    """What the operator sees: the stored detail of a leg built from ``failure`` on an
    advisor board with no stream directory."""
    leg = pi.PanelLegResult(leg="gemini", status="DEGRADED", text="",
                            detail=pi._resolve_leg_detail(failure, None, KEY), seat_key=KEY)
    return leg.detail


ADAPTER_FAILURE = pi._advisor_board_backing.CredentiallessAdapterFailure


def _wrapped(exc: BaseException) -> ValueError:
    """The broker client's failure when its adapter's exception was the whole failure: the
    one transparent wrapper, chained as `run_credentialless_client` raises it."""
    try:
        raise ADAPTER_FAILURE(f"credentialless broker client failed: {exc}") from exc
    except ADAPTER_FAILURE as wrapper:
        return wrapper


def _opaque(exc: BaseException, kind: type[BaseException] = ValueError) -> BaseException:
    """An outer exception that is NOT a transparent wrapper, explicitly chained from ``exc``."""
    try:
        raise kind("an unrelated failure") from exc
    except kind as outer:
        return outer


# ---------------------------------------------------------------- the classifier

TYPED = [
    pytest.param(ExecutableDependencyError(*GATE), "gemini_credential_near_expiry",
                 id="login-freshness-gate"),
    pytest.param(sandbox_egress.SeatIdentityUnverified("gemini_credential_refresh_timeout"),
                 "gemini_credential_refresh_timeout", id="refresh-timeout"),
    pytest.param(sandbox_egress.SeatIdentityUnverified("seat_launch_owner_required"),
                 "seat_launch_owner_required", id="launch-owner"),
    pytest.param(sandbox_egress.EgressUnavailable(
        "egress isolation unavailable; refusing to launch WITHOUT network restriction"),
        "egress isolation unavailable; refusing to launch WITHOUT network restriction",
        id="egress"),
    pytest.param(ValueError("gemini_heartbeat_capability_unavailable"),
                 "gemini_heartbeat_capability_unavailable", id="value-error-code"),
    pytest.param(seat_jail.SeatSandboxRefused(seat_jail.refused("jail_build")),
                 "seat_sandbox_refused:jail_build", id="seat-sandbox"),
    pytest.param(pi._ReviewOperationCancelled("review_operation_cancelled"),
                 "review_operation_cancelled", id="cancelled"),
]


@pytest.mark.parametrize("exc,code", TYPED)
@pytest.mark.parametrize("through_broker", [False, True], ids=["direct", "broker-wrapped"])
def test_a_typed_refusal_keeps_its_code_on_the_board(exc, code, through_broker):
    failure = pi._exception_failure(_wrapped(exc) if through_broker else exc)
    assert failure == code
    assert _board_detail(failure) == code


UNTYPED = [
    pytest.param(ExecutableDependencyError("dependency_route_unwired", "Gemini heartbeat"),
                 id="other-dependency-refusal"),
    pytest.param(ExecutableDependencyError("dependency_revalidation_failed"), id="dependency-code"),
    pytest.param(KeyError("access_token"), id="key-error"),
    pytest.param(OSError(5, "boom"), id="os-error"),
    pytest.param(ValueError("prefix gemini_credential_near_expiry"), id="text-contains-a-code"),
]


@pytest.mark.parametrize("exc", UNTYPED)
@pytest.mark.parametrize("through_broker", [False, True], ids=["direct", "broker-wrapped"])
def test_anything_else_is_the_unknown_failure(exc, through_broker):
    failure = pi._exception_failure(_wrapped(exc) if through_broker else exc)
    assert type(failure) is pi._LegFailure and failure.unknown
    assert _board_detail(failure) == UNKNOWN


def test_the_cause_walk_takes_exact_types_only():
    class Sly(ValueError):
        pass

    class SlyCode(str):
        pass

    class SlyWrapper(ADAPTER_FAILURE):
        pass

    assert pi._exception_failure(_wrapped(Sly("gemini_credential_near_expiry"))).unknown
    spoofed = ExecutableDependencyError(SlyCode(GATE[0]), GATE[1])
    assert pi._exception_failure(_wrapped(spoofed)).unknown
    wrapper = SlyWrapper("credentialless broker client failed: x")
    wrapper.__cause__ = ExecutableDependencyError(*GATE)
    assert pi._exception_failure(wrapper).unknown  # a subclass is not the transparent wrapper


def test_an_unrelated_outer_exception_keeps_its_own_classification():
    """Only the transparent wrapper is looked through: an outer I/O or cleanup failure, or the
    broker's own (opaque) failure, chained from a login refusal is not a login problem."""
    gate = ExecutableDependencyError(*GATE)
    for outer, label in ((_opaque(gate, OSError), "OSError"), (_opaque(gate), "ValueError"),
                         (_opaque(gate, RuntimeError), "RuntimeError")):
        failure = pi._exception_failure(outer)
        assert type(failure) is pi._LegFailure and failure.unknown
        assert _board_detail(failure) == UNKNOWN
        assert pi._exec_refusal(outer, failure) == label
    # The unknown failure keeps its own private detail, not the nested refusal's.
    assert "an unrelated failure" in pi._exception_failure(_opaque(gate, OSError)).raw


def _chain(links: int) -> BaseException:
    deep: BaseException = ExecutableDependencyError(*GATE)
    for _ in range(links):
        outer = ADAPTER_FAILURE("credentialless broker client failed: wrapper")
        outer.__cause__ = deep
        deep = outer
    return deep


def test_the_cause_walk_is_bounded_and_survives_a_cycle():
    bound = pi._EXCEPTION_CAUSE_DEPTH
    assert pi._exception_failure(_chain(bound)) == "gemini_credential_near_expiry"
    assert pi._exception_failure(_chain(bound + 1)).unknown  # one link past the bound
    first, second = ADAPTER_FAILURE("a"), ADAPTER_FAILURE("b")
    first.__cause__, second.__cause__ = second, first
    assert pi._exception_failure(first).unknown
    assert pi._exec_refusal(first, pi._exception_failure(first)) == "unclassified"


def test_an_implicit_context_is_not_followed():
    for kind in (RuntimeError, ADAPTER_FAILURE):
        try:
            try:
                raise ExecutableDependencyError(*GATE)
            except ExecutableDependencyError:
                raise kind("unrelated")  # noqa: B904 -- context only, deliberately
        except kind as exc:
            assert exc.__cause__ is None and exc.__context__ is not None
            assert pi._exception_failure(exc).unknown


def test_the_freshness_code_carries_its_renewal_notice():
    code = "gemini_credential_near_expiry"
    assert code in seat_jail.NOTICE_CODES and code in pi._HARNESS_DETAIL_CODES
    _what, _why, fix = seat_jail.NOTICES[code]
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/dev/null agy models" in fix


def test_the_watch_refusal_is_in_the_closed_vocabulary():
    code = "seat_sandbox_refused:watch_unavailable"
    assert pi._finalize_leg_detail(pi._LegFailure(template=code)) == code
    assert _board_detail(code) == code
    # A detail code only: the mode-line closure (seat_route_contract) is unchanged.
    assert code not in seat_jail.NOTICE_CODES


BACKING = pi._advisor_board_backing
_CLEAN = dict(timed_out=False, cancelled=False, serving=False, adapter_quiescent=True,
              client_exit_expected=True, returncode=1)


def _client_failure(error, adapter_failure, **changes):
    return BACKING._credentialless_client_failure(
        error, adapter_failure=adapter_failure, **{**_CLEAN, **changes})


def test_the_broker_chains_an_adapter_refusal_that_is_the_whole_failure():
    """The adapter's own outcome is the sole failure: the client's truncated read (no
    response frame was sent) follows from it, so the refusal is the cause."""
    refusal = ExecutableDependencyError(*GATE)
    failure = _client_failure([refusal], refusal)
    assert type(failure) is ADAPTER_FAILURE and failure.__cause__ is refusal
    assert _board_detail(pi._exception_failure(failure)) == "gemini_credential_near_expiry"


@pytest.mark.parametrize("independent", [
    {"timed_out": True}, {"cancelled": True}, {"serving": True}, {"adapter_quiescent": False},
    {"client_exit_expected": False},
], ids=["deadline", "cancellation", "serve-thread-alive", "adapter-not-quiescent",
        "client-exit-abnormal-or-unknown"])
def test_a_simultaneous_broker_failure_is_never_chained(independent):
    refusal = ExecutableDependencyError(*GATE)
    errors = [refusal, *([ValueError("broker operation cancelled or closed")]
                         if independent.get("cancelled") else [])]
    failure = _client_failure(errors, refusal, **independent)
    assert type(failure) is ValueError and failure.__cause__ is None
    assert _board_detail(pi._exception_failure(failure)) == UNKNOWN


@pytest.mark.parametrize("cleanup", [
    OSError(32, "broken pipe"),                    # closing a client pipe
    subprocess.TimeoutExpired(["client"], 2),      # the final client read
    RuntimeError("terminate failed"),              # terminating the client's group
    ValueError("adapter cancel failed"),           # the adapter's cancellation hook
], ids=["pipe-close", "final-read", "termination", "cancellation-cleanup"])
def test_an_adapter_refusal_with_an_independent_cleanup_error_keeps_the_broker_failure(cleanup):
    """The shared error list also collects cleanup failures; the adapter's outcome is tracked
    apart, and a second, independent failure keeps the broker's own (opaque) failure."""
    refusal = ExecutableDependencyError(*GATE)
    failure = _client_failure([refusal, cleanup], refusal)
    assert type(failure) is ValueError and failure.__cause__ is None
    assert _board_detail(pi._exception_failure(failure)) == UNKNOWN
    # A cleanup error alone, or ahead of the adapter's, is never the adapter's outcome either.
    assert _client_failure([cleanup], None).__cause__ is None
    assert _client_failure([cleanup, refusal], refusal).__cause__ is None


def test_an_error_that_is_not_the_adapters_own_outcome_is_never_chained():
    """A serve failure before the adapter ran (peer, grammar, binding) is the broker's."""
    serve_error = ValueError("broker request binding")
    failure = _client_failure([serve_error], None)
    assert type(failure) is ValueError and failure.__cause__ is None


def test_a_client_failure_without_an_adapter_error_is_the_brokers_own():
    for changes in ({}, {"timed_out": True, "returncode": None}):
        failure = _client_failure([], None, **changes)
        assert type(failure) is ValueError and failure.__cause__ is None
        assert pi._exception_failure(failure).unknown


def test_a_serve_error_first_seen_past_the_deadline_counts_as_the_deadline():
    decide = BACKING._client_wait_decision
    assert decide(cancelled=False, failed=True, elapsed_s=12.0, deadline_s=10.0) == "deadline"
    assert decide(cancelled=False, failed=True, elapsed_s=5.0, deadline_s=10.0) == "failed"
    assert decide(cancelled=True, failed=True, elapsed_s=12.0, deadline_s=10.0) == "cancelled"
    assert decide(cancelled=False, failed=False, elapsed_s=5.0, deadline_s=10.0) is None
    assert decide(cancelled=False, failed=True, elapsed_s=10 ** 6, deadline_s=None) == "failed"
    # ... and so the adapter's refusal is not chained past it.
    refusal = ExecutableDependencyError(*GATE)
    assert _client_failure([refusal], refusal, timed_out=True).__cause__ is None


def test_only_the_expected_truncated_exit_lets_the_refusal_through():
    expected = BACKING._client_exit_expected
    wait = BACKING._ClientWait

    def seen(status, at):
        return wait(exit_status=status, exit_ns=at)

    # The client's own truncated-response exit, observed after the adapter failed.
    assert expected(seen(BACKING._CLIENT_TRUNCATED_EXIT, 300), 200) is True
    # A signal death or any other status, even observed after the adapter failed: abnormal.
    assert expected(seen(-9, 300), 200) is False
    assert expected(seen(2, 300), 200) is False
    # An exit before the adapter failed, or no adapter failure: not a consequence of it.
    assert expected(seen(1, 100), 200) is False
    assert expected(seen(1, 300), None) is False
    # No observation of the client's own exit (it was still running, or no wait at all).
    assert expected(wait(), 200) is False
    assert expected(None, 200) is False


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def monotonic_ns(self):
        return int(self.now * 1_000_000_000)


class _FakeClient:
    """A client whose each `communicate` call runs one scripted step: the fake clock
    advances, the serve thread may record the adapter's refusal meanwhile, and the call then
    times out (``exit`` None) or returns with the client's exit status."""

    def __init__(self, clock, steps):
        self.clock, self.steps, self.returncode, self.calls = clock, list(steps), None, []

    def communicate(self, payload=None, timeout=None):
        self.calls.append((payload, timeout))
        step = self.steps.pop(0)
        self.clock.now += step.get("advance", 0.05)
        if step.get("serve"):
            step["serve"]()
        if step.get("exit") is None:
            raise subprocess.TimeoutExpired(["client"], timeout)
        self.returncode = step["exit"]
        return b"", b"client trace"


def _broker_wait(steps, *, deadline_s=10.0, failed_first=False, adapter_fails_later=False):
    """The broker's own wait and classification -- `_await_client`, `_client_exit_expected`
    and `_credentialless_client_failure`, composed as `run_credentialless_client` composes
    them -- over a fake client and clock. A step marked ``serves`` is where the serve thread
    records the adapter's refusal (the shared error list and the adapter outcome)."""
    clock, error, recorded = _Clock(), [], {}
    refusal = ExecutableDependencyError(*GATE)

    def serve():
        error.append(refusal)
        recorded["at"] = clock.monotonic_ns()

    scripted = [{**step, "serve": serve if step.get("serves") else None} for step in steps]
    client = _FakeClient(clock, scripted)
    if failed_first:
        serve()
    wait = BACKING._await_client(
        client, b"request", failed=lambda: bool(error), cancelled=lambda: False,
        started=clock.monotonic(), deadline_s=deadline_s, clock=clock.monotonic,
        clock_ns=clock.monotonic_ns)
    if adapter_fails_later:
        clock.now += 0.5
        serve()  # the adapter fails only after the client's own exit (e.g. on cancellation)
    failure = BACKING._credentialless_client_failure(
        error, adapter_failure=refusal if error else None, timed_out=wait.timed_out,
        cancelled=wait.cancelled, serving=False, adapter_quiescent=True,
        client_exit_expected=BACKING._client_exit_expected(wait, recorded.get("at")),
        returncode=client.returncode)
    return wait, failure, client


def test_broker_the_expected_truncated_exit_chains_the_refusal():
    wait, failure, _client = _broker_wait([{}, {"serves": True, "exit": 1}])
    assert (wait.exit_status, wait.timed_out) == (1, False)
    assert type(failure) is ADAPTER_FAILURE
    assert _board_detail(pi._exception_failure(failure)) == "gemini_credential_near_expiry"


def test_broker_a_signal_death_recorded_after_the_refusal_keeps_the_broker_failure():
    """The race: the client dies from a signal while the adapter runs, and the serve thread
    records the refusal before the parent's read returns -- the exit is observed AFTER the
    refusal, so timing alone would chain it; the abnormal status does not."""
    wait, failure, _client = _broker_wait([{}, {"serves": True, "exit": -9}])
    assert wait.exit_status == -9
    assert type(failure) is ValueError and failure.__cause__ is None
    assert _board_detail(pi._exception_failure(failure)) == UNKNOWN


def test_broker_a_serve_error_with_no_exit_observation_keeps_the_broker_failure():
    """The loop breaks on the serve error; the client is given its grace to exit on its own
    and is still running, so its exit is unknown before cleanup signals it."""
    wait, failure, client = _broker_wait([{"serves": True}, {"advance": 1.0}])
    assert wait.exit_status is None and client.calls[-1] == (None, BACKING._CLIENT_EXIT_GRACE_S)
    assert type(failure) is ValueError and failure.__cause__ is None


def test_broker_a_serve_error_then_the_truncated_exit_within_the_grace_chains():
    wait, failure, _client = _broker_wait([{"serves": True}, {"exit": 1}])
    assert wait.exit_status == 1
    assert type(failure) is ADAPTER_FAILURE


def test_broker_a_read_completing_just_past_the_deadline_is_a_timeout():
    """The read starts just before the deadline and returns just after it (its 100 ms
    timeout): the completion path rechecks the deadline, so the refusal is not chained."""
    threshold = max(1.0, 10.0) + 2.0
    wait, failure, _client = _broker_wait(
        [{"advance": threshold - 0.05}, {"advance": 0.1, "serves": True, "exit": 1}])
    assert wait.timed_out is True and wait.exit_status == 1
    assert type(failure) is ValueError and failure.__cause__ is None


def test_broker_a_client_exit_before_the_adapter_failed_keeps_the_broker_failure():
    wait, failure, _client = _broker_wait([{"exit": 1}], adapter_fails_later=True)
    assert wait.exit_status == 1
    assert type(failure) is ValueError and failure.__cause__ is None


def test_broker_a_serve_error_before_the_client_had_its_request_is_the_brokers():
    wait, failure, client = _broker_wait([], failed_first=True)
    assert client.calls == [] and wait.exit_status is None
    assert type(failure) is ValueError and failure.__cause__ is None


def test_the_broker_client_raises_through_its_one_decision():
    """`run_credentialless_client` builds its failure only through
    `_credentialless_client_failure`, waits through `_await_client` (which decides through `_client_wait_decision`), and
    judges the client's own exit (observed in `_await_client`) through `_client_exit_expected`; `serve_once` records the
    adapter invocation's own outcome."""
    source = Path(BACKING.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    client = ast.unparse(functions["run_credentialless_client"])
    raised = [ast.unparse(node.exc) for node in ast.walk(functions["run_credentialless_client"])
              if isinstance(node, ast.Raise) and node.exc is not None]
    assert any(text.startswith("_credentialless_client_failure(") for text in raised)
    assert not any("credentialless broker client failed" in text for text in raised)
    assert "_await_client(" in client and "client_exit_expected=_client_exit_expected(" in client
    assert "adapter_failure=adapter_failure" in client
    # The client's own exit is observed inside the try whose finally signals it.
    wrapped = [node for node in ast.walk(functions["run_credentialless_client"])
               if isinstance(node, ast.Try) and node.finalbody
               and "_terminate_process_group" in ast.unparse(node.finalbody)]
    assert wrapped and "_await_client(" in ast.unparse(wrapped[0].body)
    assert "_client_wait_decision(" in ast.unparse(functions["_await_client"])
    serve = functions["serve_once"]
    guarded = [node for node in ast.walk(serve) if isinstance(node, ast.Try)
               and "adapter.invoke()" in ast.unparse(node.body)]
    assert guarded and "self._adapter_failure" in ast.unparse(guarded[0].handlers)


# ------------------------------------------------- the leg record's closed fields

UNKNOWN_CODE = "fixtureopaquevalue123456789"  # matches the old shape check; not one of ours


@pytest.mark.parametrize("exc,expected", [
    (ExecutableDependencyError(*GATE), "gemini_credential_near_expiry"),
    (_wrapped(ExecutableDependencyError("dependency_route_unwired", "Gemini heartbeat")),
     "ExecutableDependencyError:dependency_route_unwired"),
    (ExecutableDependencyError(UNKNOWN_CODE), "ExecutableDependencyError"),
    (_wrapped(ExecutableDependencyError(UNKNOWN_CODE, "detail")), "ExecutableDependencyError"),
    (_wrapped(KeyError("x")), "KeyError"),
    (type("Foreign", (Exception,), {})("x"), "unclassified"),
])
def test_the_refusal_is_closed_and_never_the_message(exc, expected):
    refusal = pi._exec_refusal(exc, pi._exception_failure(exc))
    assert refusal == expected and pi._exec_refusal_valid(refusal)
    assert "credentialless" not in refusal and "Gemini heartbeat" not in refusal
    assert UNKNOWN_CODE not in refusal


def test_the_dependency_allowlist_holds_every_code_the_package_raises():
    """Every literal `ExecutableDependencyError` code is named exactly; anything else gets
    the bare class label."""
    import re

    root = Path(pi.__file__).parent
    literal = re.compile(r'ExecutableDependencyError\(\s*"([a-z_]+)"')
    raised = {code for path in root.rglob("*.py") for code in literal.findall(path.read_text())}
    assert raised and raised <= pi._EXEC_DEPENDENCY_CODES
    assert UNKNOWN_CODE not in pi._EXEC_DEPENDENCY_CODES


@pytest.mark.parametrize("value", [
    "credentialless broker client failed: x", "ExecutableDependencyError:Not A Code",
    "ExecutableDependencyError:", f"ExecutableDependencyError:{UNKNOWN_CODE}", None, 7,
])
def test_a_record_drops_an_open_refusal_or_stage(value):
    record = pi.leg_exec_record("gemini", None, [], stage=value, refusal=value, launched=False)
    assert record["refusal"] is None and record["stage"] is None


def test_the_record_outcome_says_unlaunched_only_when_nothing_started():
    assert pi.leg_exec_record("gemini", None, [], launched=False)["outcome"] == (
        "leg_execution_unlaunched")
    # Launched with no exit observed (a timed-out seat) stays failed, as does "not known".
    assert pi.leg_exec_record("gemini", None, [], launched=True)["outcome"] == (
        "leg_execution_failed")
    assert pi.leg_exec_record("gemini", None, [])["outcome"] == "leg_execution_failed"
    assert pi.leg_exec_record("gemini", 0, [], launched=False)["outcome"] == (
        "leg_execution_completed")
    assert pi.leg_exec_record("gemini", 3, [], launched=False)["outcome"] == (
        "leg_execution_failed")


@pytest.mark.parametrize("stage,count,expected", [
    ("subject", 0, False), ("prepare", 0, False), ("jail_build", 0, False),
    # A launch may have begun past these, before a spawn was counted.
    ("admission", 0, None), ("credential", 0, None), ("launch", 0, None), ("stream", 0, None),
    ("cleanup", 0, None), ("broker", 0, None), ("unlaunched", 0, None), (None, 0, None),
    ("prepare", 1, True), ("launch", 2, True),
])
def test_launch_certainty(stage, count, expected):
    counter = pi._SpawnCounter()
    counter.increment(count)
    assert pi._exec_launched({"spawns": counter, "stage": stage}) is expected
    assert pi._exec_launched({"stage": stage}) is None  # no counter: not known


# ------------------------------------------- through the production spawn boundary

@dataclass(frozen=True, slots=True)
class _Route:
    jailed: bool


@dataclass(frozen=True, slots=True)
class _Prepared:
    review_dir: Path
    local_tree: Path
    snapshot_sha256: str
    sandbox_ref: str


class _Backend:
    name = "local"

    def commit(self, prepared, request):
        return None

    def release(self, prepared):
        return None


@dataclass(frozen=True, slots=True)
class _Placement:
    backend: object
    prepared: object
    authorization_sha256: str

    def record_backend_receipt(self, receipt):
        return None


class _Broker:
    """Only the transport is faked: the REAL adapter (`_parent_infer`) runs; an exception it
    lets escape is re-raised (a provider-group quiescence failure) or wrapped, as
    `run_credentialless_client` does when its own checks held (the transparent, chained
    wrapper)."""

    #: False: an opaque wrapper with no cause (as before agent-harness#1823, or a broker that
    #: also failed on its own), so only the seat boundary in `_parent_infer` can keep a code.
    chained = True

    def __init__(self, *args, **kwargs):
        self.evidence = {}

    def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
        try:
            status, text = adapter.invoke()
        except pi.ProviderProcessGroupQuiescenceError:
            raise
        except Exception as exc:
            if type(self).chained:
                raise ADAPTER_FAILURE(f"credentialless broker client failed: {exc}") from exc
            raise ValueError(f"credentialless broker client failed: {exc}") from None
        return {"schema": "parent_unix_broker_v1", "status": status, "text": text}, self.evidence

    def close(self):
        return None


def _jailed_gemini_spawn(monkeypatch, tmp_path, *, prepare, execute=None, chained=True,
                         window_board=None):
    """Drive `_default_spawn`'s brokered jailed-Gemini branch with ``prepare`` (and
    ``execute``) in place of the seat functions; returns the spawn result and its record."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    authorization = SimpleNamespace(staged_tree_sha256="c" * 64)

    def mkdtemp(*, prefix, dir):
        path = Path(dir) / f"{prefix}{len(list(Path(dir).iterdir()))}"
        path.mkdir()
        return str(path)

    def prepare_local_stage(repo, review_dir, *, floor_bytes, mark):
        tree = Path(review_dir) / pi._review_stage.REVIEW_STAGE_TREE_DIRNAME
        (tree / ".git").mkdir(parents=True)
        (tree / ".git" / "phase-loop-source-commit").write_text("d" * 40, encoding="utf-8")
        return _Prepared(Path(review_dir), tree, "c" * 64, "local:fixture")

    @contextmanager
    def lease_seat_id(count):
        yield 2

    @contextmanager
    def start_proxy(*, allowlist_id, refuse_all=False):
        yield SimpleNamespace(socket="proxy.sock", allowlist_sha256="b" * 64,
                              proxy_url="http://127.0.0.1:3128", private_proxy_token=b"fixture")

    @contextmanager
    def isolated_network(*, timeout_s, seat_uid_map=False, required=False,
                         proxy_socket=None, proxy_port=None, private_proxy=None):
        yield ("namespace",)

    def unreached(*a, **k):
        pytest.fail("the seat ran after its preparation refused")

    backend = _Backend()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(pi.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", lambda: scratch)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda path: tmp_path)
    monkeypatch.setattr(pi, "_has_injected_review_execution_seam", lambda *, leg=None: False)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (_Route(True), [], None))
    monkeypatch.setattr(pi._sandbox_policy, "effective_floor_bytes", lambda path: 1)
    monkeypatch.setattr(pi._sandbox_retention, "reap_until_free", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_refuse_unless_executed_remotely", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_policy, "select_sandbox_root",
                        lambda **kw: sandbox_policy.SandboxRootChoice(None, scratch, False))
    monkeypatch.setattr(pi._sandbox_placement, "resolve_backend", lambda choice: backend)
    monkeypatch.setattr(pi, "_placement_gate", lambda value: None)
    monkeypatch.setattr(pi._sandbox_placement, "prepare_local_stage", prepare_local_stage)
    monkeypatch.setattr(pi._sandbox_placement, "LegPlacement",
                        lambda value, prepared, *, scheme, authorization_sha256:
                        _Placement(value, prepared, authorization_sha256))
    monkeypatch.setattr(pi, "_record_sandbox_facts", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._seat_uid, "subordinate_range", lambda path: (1, 2))
    monkeypatch.setattr(pi._seat_uid, "seat_id_count", lambda uids, gids: 1)
    monkeypatch.setattr(pi._seat_uid, "lease_seat_id", lease_seat_id)
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda prefix: 71)
    monkeypatch.setattr(pi._seat_egress_proxy, "start_private_gemini_proxy", start_proxy)
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda proxy: {})
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", isolated_network)
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda *, applied: {})
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: SimpleNamespace(expires_monotonic_ns=10**30))
    monkeypatch.setattr(pi, "ParentUnixBroker", _Broker)
    monkeypatch.setattr(_Broker, "chained", chained)
    monkeypatch.setattr(pi, "_render_broker_pointer_prompt", lambda *a, **k: "frame")
    monkeypatch.setattr(pi._review_stage, "remove_review_stage", lambda path: None)
    monkeypatch.setattr(pi, "_bind_route_qualification", lambda seat, route: seat)
    monkeypatch.setattr(pi, "_registered_window_board", lambda authorization: window_board)
    monkeypatch.setattr(pi, "_prepare_jailed_gemini", prepare)
    monkeypatch.setattr(pi, "_exec_jailed_gemini_leg", execute or unreached)
    spawned = pi._default_spawn(
        "gemini", "ARTIFACT", repo_dir=tmp_path, mode="review", model="fixture",
        review_authorization=authorization, canonical_repo_authority=tmp_path,
    )
    records = list(state.rglob("leg-*.json"))
    assert len(records) == 1
    return spawned, json.loads(records[0].read_text())


def _raising(exc, stage="prepare"):
    def prepare(*args, **kwargs):
        pi._note_exec_stage("subject")
        pi._note_exec_stage(stage)
        raise exc
    return prepare


def _spawn_detail(spawned) -> str:
    return _board_detail(spawned[2])


PREPARE_CASES = [
    pytest.param(ExecutableDependencyError(*GATE), "gemini_credential_near_expiry",
                 "gemini_credential_near_expiry", id="login-freshness-gate"),
    pytest.param(sandbox_egress.SeatIdentityUnverified("gemini_credential_near_expiry"),
                 "gemini_credential_near_expiry", "gemini_credential_near_expiry",
                 id="near-expiry-after-renewal"),
    pytest.param(ValueError("gemini_heartbeat_capability_unavailable"),
                 "gemini_heartbeat_capability_unavailable",
                 "gemini_heartbeat_capability_unavailable", id="admission"),
    pytest.param(ExecutableDependencyError("dependency_route_unwired", "Gemini heartbeat"),
                 UNKNOWN, "ExecutableDependencyError:dependency_route_unwired",
                 id="untyped-dependency-refusal"),
    pytest.param(KeyError("access_token"), UNKNOWN, "KeyError", id="untyped"),
]


@pytest.mark.parametrize("chained", [True, False], ids=["chained", "legacy-wrapper"])
@pytest.mark.parametrize("exc,detail,refusal", PREPARE_CASES)
def test_a_preparation_refusal_reaches_the_board_typed(monkeypatch, tmp_path, exc, detail,
                                                       refusal, chained):
    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path, prepare=_raising(exc),
                                           chained=chained)
    assert tuple(spawned)[:2] == ("DEGRADED", "")
    assert _spawn_detail(spawned) == detail
    noticed = detail in seat_jail.NOTICE_CODES
    assert (detail in spawned.seat_notices) is noticed
    assert record["stage"] == "prepare" and record["refusal"] == refusal
    assert record["outcome"] == "leg_execution_unlaunched" and record["exit_code"] is None
    assert str(exc) not in json.dumps(record) or str(exc) == refusal


def test_a_sandbox_refusal_in_preparation_keeps_its_code_and_record(monkeypatch, tmp_path):
    exc = seat_jail.SeatSandboxRefused(seat_jail.refused("jail_build"), "free text")
    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path,
                                           prepare=_raising(exc, "jail_build"))
    assert _spawn_detail(spawned) == "seat_sandbox_refused:jail_build"
    assert "seat_sandbox_refused:jail_build" in spawned.seat_notices
    assert record["stage"] == "jail_build"
    assert record["refusal"] == "seat_sandbox_refused:jail_build"
    assert record["outcome"] == "leg_execution_unlaunched"


def _seat(*args, **kwargs):
    return SimpleNamespace(notices=[])


EXEC_CASES = [
    pytest.param(sandbox_egress.SeatIdentityUnverified("seat_launch_owner_required"),
                 "seat_launch_owner_required", id="launch-owner"),
    pytest.param(sandbox_egress.EgressUnavailable(
        "egress isolation unavailable; refusing to launch WITHOUT network restriction"),
        "egress isolation unavailable; refusing to launch WITHOUT network restriction",
        id="egress"),
    pytest.param(OSError(5, "boom"), UNKNOWN, id="os-error"),
]


@pytest.mark.parametrize("chained", [True, False], ids=["chained", "legacy-wrapper"])
@pytest.mark.parametrize("exc,detail", EXEC_CASES)
def test_an_execution_refusal_reaches_the_board_typed(monkeypatch, tmp_path, exc, detail,
                                                      chained):
    def execute(seat, **kwargs):
        pi._note_exec_stage("launch")
        raise exc

    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path, prepare=_seat, execute=execute,
                                           chained=chained)
    assert tuple(spawned)[:2] == ("DEGRADED", "")
    assert _spawn_detail(spawned) == detail
    assert record["stage"] == "launch"
    assert record["refusal"] == (detail if detail != UNKNOWN else "OSError")
    # Past the launch boundary: not proven unlaunched, so the outcome stays failed.
    assert record["outcome"] == "leg_execution_failed"


def test_the_watch_refusal_reaches_the_board(monkeypatch, tmp_path):
    def execute(seat, *, failure_detail_sink, **kwargs):
        return pi._jailed_failure("seat_sandbox_refused:watch_unavailable", failure_detail_sink)

    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path, prepare=_seat, execute=execute)
    assert _spawn_detail(spawned) == "seat_sandbox_refused:watch_unavailable"
    assert record["refusal"] == "seat_sandbox_refused:watch_unavailable"


_REAL_EXEC = pi._exec_jailed_gemini_leg
_PROXY_VALUE = "b7c0f2e1a9d34e5f8c1b2a3d4e5f6071"


def _jailed_seat(*args, **kwargs):
    jail = SimpleNamespace(
        env={"HTTPS_PROXY": "http://127.0.0.1:3128"},
        profile_digest="d", profile_id="p", filter_digest="f",
        redacted_owner=lambda: [], pass_fds=(), dependency=None)
    return pi._JailedGeminiSeat(jail=jail, probe_jail=jail, holder_pid=1,
                          private_proxy_token=_PROXY_VALUE.encode(),
                          token=b"ya29.fixture-access-token-value",
                          review_dir=Path("/nonexistent"), seat_dir=Path("/nonexistent"),
                          expires_at=None)


def test_an_exec_time_proxy_refusal_attaches_the_board_notice(monkeypatch, tmp_path):
    seat = _jailed_seat()
    seat.private_proxy_token = b""
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness",
                        lambda *a, **k: pytest.fail("the provider ran without a proxy token"))

    spawned, record = _jailed_gemini_spawn(
        monkeypatch, tmp_path, prepare=lambda *a, **k: seat, execute=_REAL_EXEC)

    code = "seat_sandbox_refused:gemini_proxy_token_missing"
    assert tuple(spawned)[:2] == ("DEGRADED", "")
    assert _spawn_detail(spawned) == record["refusal"] == code
    assert code in spawned.seat_notices


def test_the_real_watcher_refusal_records_its_code(monkeypatch, tmp_path):
    """The qualification board's watcher declines to start: the real leg returns the typed
    code without raising, and the record keeps it."""
    board = SimpleNamespace(proxy=None, start=lambda *a, **k: False, finish=lambda *a, **k: None)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness",
                        lambda *a, **k: pytest.fail("the provider ran without its watcher"))
    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path, prepare=_jailed_seat,
                                           execute=_REAL_EXEC, window_board=board)
    assert _spawn_detail(spawned) == "seat_sandbox_refused:watch_unavailable"
    assert record["refusal"] == "seat_sandbox_refused:watch_unavailable"
    assert record["stage"] == "launch"


def test_the_token_guard_return_records_its_code(monkeypatch, tmp_path):
    seat = _jailed_seat()
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"event":"init","x":"' + seat.token.decode() + '"}\n', stderr=""))
    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path, prepare=lambda *a, **k: seat,
                                           execute=_REAL_EXEC)
    assert _spawn_detail(spawned) == "gemini_seat_token_in_output"
    assert record["refusal"] == "gemini_seat_token_in_output"
    assert seat.token.decode() not in json.dumps(record)


@pytest.mark.parametrize(("expires_at", "expected"), [(None, "permission_denied"), (0, "auth_expired")])
def test_jailed_broker_retains_native_exit_class(monkeypatch, tmp_path, expires_at, expected, caplog):
    seat = _jailed_seat()
    seat.expires_at = expires_at
    stdout = "PRIVATE_STDOUT_SENTINEL"
    stderr = "HTTP 403 PRIVATE_STDERR_SENTINEL"

    def run(*args, native_run, **kwargs):
        native_run.update(native_exit_code=1, native_signal=None,
                          native_stdout_bytes=len(stdout), native_stderr_bytes=len(stderr))
        return pi._LegRun(1, stdout, stderr)

    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    spawned, record = _jailed_gemini_spawn(
        monkeypatch, tmp_path, prepare=lambda *a, **k: seat, execute=_REAL_EXEC,
    )
    assert tuple(spawned)[:2] == ("DEGRADED", "")
    evidence = spawned.harden_isolation_evidence
    assert evidence["provider_error_class"] == expected
    assert evidence["provider_response_bytes"] == 0
    assert evidence["native_exit_code"] == 1
    assert evidence["native_stdout_bytes"] == len(stdout)
    assert evidence["native_stderr_bytes"] == len(stderr)
    leg = pi.PanelLegResult(leg="gemini", status=spawned[0], text=spawned[1],
                            detail=_spawn_detail(spawned))
    pi.attach_harden_isolation_evidence(leg, evidence)
    pi._write_incremental_verdict(tmp_path, 0, leg)
    raw_verdict = next(tmp_path.glob("leg-*.verdict.json")).read_text()
    assert json.loads(raw_verdict)["provider_error_class"] == expected
    for retained in (json.dumps(evidence), json.dumps(record), raw_verdict, caplog.text):
        assert stdout not in retained
        assert stderr not in retained
        assert "PRIVATE_STDERR_SENTINEL" not in retained


@pytest.mark.parametrize(("native_rc", "result_fields", "expected"), [
    (0, {"status": "ERROR", "error": {"code": 429, "message": "RESOURCE_EXHAUSTED PRIVATE_RESULT_SENTINEL"}}, "quota_exhausted"),
    (1, {"status": "FAILED", "error_code": 401, "error_message": "UNAUTHENTICATED PRIVATE_RESULT_SENTINEL"}, "auth_missing"),
    (0, {"status": "ERROR", "response": "", "message": "MODEL_NOT_FOUND PRIVATE_RESULT_SENTINEL"}, "model_error"),
])
def test_jailed_broker_classifies_failed_ndjson_result_without_retaining_raw_text(
    monkeypatch, tmp_path, native_rc, result_fields, expected, caplog,
):
    seat = _jailed_seat()
    stdout = json.dumps({
        "event": "result",
        "conversation_id": "fixture-session",
        "result": result_fields,
    }) + "\n"
    stderr = "unrecognized diagnostic PRIVATE_STDERR_SENTINEL\n"

    def run(*args, native_run, **kwargs):
        native_run.update(native_exit_code=native_rc, native_signal=None,
                          native_stdout_bytes=len(stdout), native_stderr_bytes=len(stderr))
        return pi._LegRun(native_rc, stdout, stderr)

    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    spawned, record = _jailed_gemini_spawn(
        monkeypatch, tmp_path, prepare=lambda *a, **k: seat, execute=_REAL_EXEC,
    )
    assert tuple(spawned)[:2] == ("DEGRADED", "")
    evidence = spawned.harden_isolation_evidence
    assert evidence["provider_error_class"] == expected
    assert evidence["provider_response_bytes"] == 0
    assert evidence["native_exit_code"] == native_rc
    leg = pi.PanelLegResult(leg="gemini", status=spawned[0], text=spawned[1],
                            detail=_spawn_detail(spawned))
    pi.attach_harden_isolation_evidence(leg, evidence)
    pi._write_incremental_verdict(tmp_path, 0, leg)
    raw_verdict = next(tmp_path.glob("leg-*.verdict.json")).read_text()
    assert json.loads(raw_verdict)["provider_error_class"] == expected
    for retained in (json.dumps(evidence), json.dumps(record), raw_verdict, caplog.text):
        assert "PRIVATE_RESULT_SENTINEL" not in retained
        assert "PRIVATE_STDERR_SENTINEL" not in retained


def test_a_launch_that_fails_after_its_gate_opened_stays_failed(monkeypatch, tmp_path):
    """A capped child can exec once its gate opens even when its launcher then raises (the
    caps reaper or witness failing): no spawn was counted, yet the outcome must stay
    `leg_execution_failed`, never `unlaunched`."""
    def post_gate_failure(*args, **kwargs):
        raise seat_jail.SeatSandboxRefused("seat_resource_caps_unavailable",
                                           "the capped child exited before its gate opened")

    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", post_gate_failure)
    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path, prepare=_jailed_seat,
                                           execute=_REAL_EXEC)
    assert _spawn_detail(spawned) == "seat_resource_caps_unavailable"
    assert record["stage"] == "launch" and record["refusal"] == "seat_resource_caps_unavailable"
    assert record["outcome"] == "leg_execution_failed" and record["exit_code"] is None


def test_a_cancellation_still_propagates_and_reaches_the_board_typed(monkeypatch, tmp_path):
    # Cancellation is not turned into a degraded leg at the seat boundary: it crosses the
    # broker as before. When the adapter's cancellation is the broker's whole failure, the
    # transparent wrapper keeps its code (a broker that also failed on its own is opaque).
    spawned, record = _jailed_gemini_spawn(
        monkeypatch, tmp_path,
        prepare=_raising(pi._ReviewOperationCancelled("review_operation_cancelled"), "credential"))
    assert _spawn_detail(spawned) == "review_operation_cancelled"
    assert record["refusal"] == "review_operation_cancelled"
    assert record["stage"] == "credential"


def test_a_provider_group_quiescence_failure_is_never_a_degraded_leg(monkeypatch, tmp_path):
    with pytest.raises(pi.ProviderProcessGroupQuiescenceError):
        _jailed_gemini_spawn(
            monkeypatch, tmp_path,
            prepare=_raising(pi.ProviderProcessGroupQuiescenceError("group still alive")))


# ------------------------- the zero-launch reproduction, converted (triage §7 R0)

def _stale_login_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    store = home / ".gemini" / "antigravity-cli"
    store.mkdir(parents=True, mode=0o700)
    expired = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    login = store / "antigravity-oauth-token"
    login.write_text(json.dumps({"token": {"access_token": "fixture", "expiry": expired}}))
    login.chmod(0o600)
    return home


def test_a_stale_login_on_a_dependency_route_refuses_before_any_launch(monkeypatch, tmp_path):
    """The reported board run (agent-harness#1823): the front-door agy resolves as a
    managed-release subject (a bound dependency) and the host login has expired. The seat
    refuses before it builds anything -- no `--help` measurement, no renewal, no seat
    directory -- and the board says why, with the renewal fix, instead of the unknown
    template; the record names the stage and the closed refusal."""
    home = _stale_login_home(tmp_path)
    assert pi._gemini_credential_fresh(home) is False

    def sentinel(name):
        def reached(*a, **k):
            pytest.fail(f"{name} reached")
        return reached

    monkeypatch.setattr(pi.gemini_heartbeat, "admit", sentinel("admit (help measurement)"))
    monkeypatch.setattr(pi, "_refresh_gemini_credential", sentinel("host credential refresh"))
    monkeypatch.setattr(pi.subprocess, "Popen", sentinel("a process launch"))
    subject = SimpleNamespace(source="managed_release", subject_path=tmp_path / "agy")
    dependency = SimpleNamespace(subject_source=str(tmp_path / "agy"))
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda leg, env: (subject, dependency))
    monkeypatch.setattr(pi, "_validate_jail_dependency", lambda leg, dep: None)
    real_prepare = pi._prepare_jailed_gemini
    seat_dirs: list[Path] = []

    def prepare(review_dir, seat_dir, *args, **kwargs):
        seat_dirs.append(Path(seat_dir))
        return real_prepare(review_dir, seat_dir, *args, env={"HOME": str(home)},
                            **{k: v for k, v in kwargs.items() if k != "env"})

    spawned, record = _jailed_gemini_spawn(monkeypatch, tmp_path, prepare=prepare)
    assert tuple(spawned)[:2] == ("DEGRADED", "")
    assert _spawn_detail(spawned) == "gemini_credential_near_expiry"
    assert "gemini_credential_near_expiry" in spawned.seat_notices
    assert seat_dirs and not any(path.exists() for path in seat_dirs)
    assert record["stage"] == "prepare"
    assert record["refusal"] == "gemini_credential_near_expiry"
    assert record["outcome"] == "leg_execution_unlaunched" and record["exit_code"] is None
    assert record["model_turn"] is None and record["verdict"] is None


def test_the_reproduced_refusal_is_the_gate_s_exact_exception(monkeypatch, tmp_path):
    """The gate itself is unchanged (agent-harness#1782): it still raises its typed
    dependency refusal; only its reporting changed."""
    home = _stale_login_home(tmp_path)
    subject = SimpleNamespace(source="managed_release", subject_path=tmp_path / "agy")
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda leg, env: (
        subject, SimpleNamespace(subject_source=str(tmp_path / "agy"))))
    monkeypatch.setattr(pi, "_validate_jail_dependency", lambda leg, dep: None)
    with pytest.raises(ExecutableDependencyError) as raised:
        pi._prepare_jailed_gemini(tmp_path / "review", tmp_path / "seat", None, 0, 0, ("", ""),
                                  SimpleNamespace(proxy_url="http://127.0.0.1:3128", private_proxy_token=b"fixture"),
                                  env={"HOME": str(home)})
    assert (raised.value.code, raised.value.detail) == GATE
    assert not (tmp_path / "seat").exists()
    # Before this change the board rendered it as the unknown template, as it still does for
    # an opaque wrapper.
    legacy = ValueError(f"credentialless broker client failed: {raised.value}")
    assert _board_detail(pi._exception_failure(legacy)) == UNKNOWN
    assert _board_detail(pi._exception_failure(_opaque(raised.value))) == UNKNOWN
    assert _board_detail(pi._exception_failure(_wrapped(raised.value))) == (
        "gemini_credential_near_expiry")


# -------------------------------------------------- the seat-mode preflight (F2)

def test_the_preflight_reports_an_unrenewable_login_up_front(monkeypatch, tmp_path):
    from phase_loop_runtime import seat_subject

    home = _stale_login_home(tmp_path)
    env = {"HOME": str(home), "PATH": os.defpath}
    for source, expected in (("managed_release", True), ("session_lease", True),
                             ("standalone", False)):
        monkeypatch.setattr(seat_subject, "resolve_seat_subject",
                            lambda leg, e, source=source: SimpleNamespace(source=source))
        assert pi._gemini_login_unrenewable(env) is expected
    monkeypatch.setattr(pi, "_gemini_credential_fresh", lambda home: True)
    assert pi._gemini_login_unrenewable(env) is False


def test_the_preflight_never_breaks_the_board(monkeypatch, tmp_path):
    from phase_loop_runtime import seat_subject

    def broken(*a, **k):
        raise FileNotFoundError("seat_provider_unavailable")

    monkeypatch.setattr(seat_subject, "resolve_seat_subject", broken)
    assert pi._gemini_login_unrenewable({"HOME": str(_stale_login_home(tmp_path))}) is False
    assert pi._gemini_login_unrenewable({"HOME": str(tmp_path / "absent")}) is False
